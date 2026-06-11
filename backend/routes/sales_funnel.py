"""Sales Funnel — pipeline de vendas integrado ao WhatsApp.

Endpoints:
  GET  /api/sales/dashboard          — KPIs do funil
  GET  /api/sales/leads              — lista leads (hot/warm/cold)
  GET  /api/sales/leads/{phone}      — detalhe de 1 lead
  POST /api/sales/leads/{phone}/convert — converte lead em ticket de instalação
  POST /api/sales/leads/{phone}/score   — força/atualiza intent score
  GET  /api/sales/cold-leads         — leads frios para reativar
  POST /api/sales/reactivate         — dispara reativação em massa

Implementação:
- "Lead" = conversa WhatsApp SEM subscriber_id vinculado E que mencionou
  termos de venda nos últimos 60 dias.
- `intent_score` (0-100) calculado por heurística de palavras-chave +
  metadata da Isabella (markers [HOT_LEAD], [VENDA_AGENDADA]).
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "vendas-team",
    "domain": "comercial",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.sales")
router = APIRouter(prefix="/api/sales", tags=["sales"])


# ---------------------------------------------------------------------------
# Heurística de intent score
# ---------------------------------------------------------------------------
# Pesos por palavra (somam até 100).
HOT_KEYWORDS = {  # > 60 — sinaliza intenção forte
    "quero contratar": 40, "vamos fechar": 40, "pode marcar": 35,
    "fechar negocio": 35, "como faço pra contratar": 30,
    "pode instalar": 30, "agendar instalação": 35,
    "qual valor": 15, "quanto custa": 15, "qual o preço": 15,
}
WARM_KEYWORDS = {  # 30-60 — interesse
    "fibra": 10, "internet": 8, "plano": 10, "megabits": 12, "mbps": 12,
    "cobertura": 15, "tem na minha rua": 20, "atende meu bairro": 18,
    "promoção": 10, "desconto": 8, "boleto": 5,
}
COLD_KEYWORDS = {  # < 30 — curiosidade só
    "só queria saber": -10, "depois eu vejo": -10, "talvez": -5,
}

# Marker que a Isabella/Vendas escreve na resposta quando detecta venda quente
HOT_LEAD_MARKER = "[HOT_LEAD]"
SALE_AGREED_MARKER = "[VENDA_AGENDADA]"
# Markers de roteamento (Isabella decide pra onde mandar)
ROUTE_HUMAN_MARKER = "[ROTEAR_HUMANO]"
ROUTE_SUPPORT_MARKER = "[ROTEAR_SUPORTE]"
ROUTE_FINANCE_MARKER = "[ROTEAR_FINANCEIRO]"
CHURN_RISK_MARKER = "[CHURN_RISK]"
ALL_MARKERS = [
    HOT_LEAD_MARKER, SALE_AGREED_MARKER,
    ROUTE_HUMAN_MARKER, ROUTE_SUPPORT_MARKER,
    ROUTE_FINANCE_MARKER, CHURN_RISK_MARKER,
]


def _calc_intent_score(text: str) -> int:
    """Calcula score 0-100 baseado em palavras-chave."""
    if not text:
        return 0
    t = text.lower()
    score = 0
    for kw, w in {**HOT_KEYWORDS, **WARM_KEYWORDS, **COLD_KEYWORDS}.items():
        if kw in t:
            score += w
    return max(0, min(100, score))


def _temp_from_score(score: int) -> str:
    if score >= 70:
        return "hot"
    if score >= 35:
        return "warm"
    if score > 0:
        return "cold"
    return "none"


async def _aggregate_lead_score(cid: str, phone: str) -> Dict[str, Any]:
    """Agrega score considerando últimas 20 msgs inbound + markers."""
    msgs = await db.aihub_wa_messages.find(
        {"company_id": cid, "phone": phone, "direction": "inbound"},
        {"_id": 0, "text": 1, "created_at": 1},
    ).sort("created_at", -1).limit(20).to_list(20)
    raw_score = 0
    last_text = ""
    last_msg_at = None
    for m in msgs:
        raw_score = max(raw_score, _calc_intent_score(m.get("text") or ""))
        if not last_text:
            last_text = (m.get("text") or "")[:120]
            last_msg_at = m.get("created_at")

    # Bonus por markers da IA
    has_hot_marker = await db.aihub_wa_messages.find_one(
        {"company_id": cid, "phone": phone, "direction": "outbound",
          "text": {"$regex": re.escape(HOT_LEAD_MARKER)}}, {"_id": 0, "id": 1},
    )
    has_sale_marker = await db.aihub_wa_messages.find_one(
        {"company_id": cid, "phone": phone, "direction": "outbound",
          "text": {"$regex": re.escape(SALE_AGREED_MARKER)}}, {"_id": 0, "id": 1},
    )
    if has_sale_marker:
        raw_score = 100
    elif has_hot_marker:
        raw_score = max(raw_score, 85)

    return {
        "phone": phone, "score": raw_score, "temperature": _temp_from_score(raw_score),
        "last_text": last_text, "last_msg_at": last_msg_at,
        "has_hot_marker": bool(has_hot_marker),
        "has_sale_marker": bool(has_sale_marker),
        "msgs_count": len(msgs),
    }


# ---------------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------------
@router.get("/dashboard")
async def sales_dashboard(days: int = 30,
                            user: dict = Depends(require_role("gestor"))):
    """KPIs do funil de vendas dos últimos N dias."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Total de conversas inbound sem subscriber_id (= leads)
    leads_total = await db.wa_conversations.count_documents({
        "company_id": cid,
        "last_msg_at": {"$gte": cutoff},
        "$or": [{"subscriber_id": None}, {"subscriber_id": {"$exists": False}}],
    })

    # Hot leads (com marker)
    hot_leads = await db.aihub_wa_messages.distinct("phone", {
        "company_id": cid, "direction": "outbound",
        "text": {"$regex": re.escape(HOT_LEAD_MARKER)},
        "created_at": {"$gte": cutoff},
    })
    # Vendas agendadas
    sales_agreed = await db.aihub_wa_messages.distinct("phone", {
        "company_id": cid, "direction": "outbound",
        "text": {"$regex": re.escape(SALE_AGREED_MARKER)},
        "created_at": {"$gte": cutoff},
    })
    # Convertidos (tickets de instalacao criados pela origem "sales_funnel")
    converted = await db.tickets.count_documents({
        "company_id": cid, "origin_source": "sales_funnel",
        "created_at": {"$gte": cutoff},
    })

    return {
        "period_days": days,
        "leads_total": leads_total,
        "hot_leads": len(hot_leads),
        "sales_agreed": len(sales_agreed),
        "converted_to_install": converted,
        "conversion_rate": round((converted / leads_total * 100), 1) if leads_total else 0,
    }


# ---------------------------------------------------------------------------
# LISTA DE LEADS
# ---------------------------------------------------------------------------
@router.get("/leads")
async def list_leads(temperature: Optional[str] = None, limit: int = 100,
                       days: int = 30,
                       user: dict = Depends(require_role("gestor"))):
    """Lista leads (conversas WhatsApp sem subscriber_id) com score.

    Query params:
      - temperature: hot|warm|cold|none
      - days: janela (padrão 30)
      - limit: máximo de leads retornados
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    convs = await db.wa_conversations.find(
        {"company_id": cid,
          "last_msg_at": {"$gte": cutoff},
          "$or": [{"subscriber_id": None}, {"subscriber_id": {"$exists": False}}]},
        {"_id": 0, "phone": 1, "push_name": 1, "last_msg_at": 1,
          "last_text": 1, "unread_count": 1},
    ).sort("last_msg_at", -1).limit(limit * 2).to_list(limit * 2)

    leads = []
    for c in convs:
        score = await _aggregate_lead_score(cid, c["phone"])
        if temperature and score["temperature"] != temperature:
            continue
        leads.append({
            "phone": c["phone"],
            "push_name": c.get("push_name"),
            "last_msg_at": c.get("last_msg_at"),
            "last_text": (c.get("last_text") or score.get("last_text") or "")[:140],
            "unread_count": c.get("unread_count", 0),
            "score": score["score"],
            "temperature": score["temperature"],
            "has_hot_marker": score["has_hot_marker"],
            "has_sale_marker": score["has_sale_marker"],
        })
        if len(leads) >= limit:
            break
    leads.sort(key=lambda x: (-x["score"], -(x["unread_count"] or 0)))
    return {"items": leads, "total": len(leads), "period_days": days}


# ---------------------------------------------------------------------------
# DETALHE
# ---------------------------------------------------------------------------
@router.get("/leads/{phone}")
async def lead_detail(phone: str,
                        user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    conv = await db.wa_conversations.find_one(
        {"company_id": cid, "phone": phone}, {"_id": 0},
    )
    if not conv:
        raise HTTPException(404, "Conversa não encontrada")
    score = await _aggregate_lead_score(cid, phone)
    recent = await db.aihub_wa_messages.find(
        {"company_id": cid, "phone": phone},
        {"_id": 0, "text": 1, "direction": 1, "created_at": 1},
    ).sort("created_at", -1).limit(20).to_list(20)
    return {"conv": conv, "score": score, "recent_messages": recent}


# ---------------------------------------------------------------------------
# CONVERTER LEAD → TICKET DE INSTALAÇÃO
# ---------------------------------------------------------------------------
class ConvertIn(BaseModel):
    client_name: str = Field(..., min_length=2)
    cpf: Optional[str] = None
    address: str = Field(..., min_length=3)
    neighborhood: Optional[str] = None
    city: Optional[str] = None
    plan_name: Optional[str] = None
    scheduled_date: Optional[str] = None  # ISO YYYY-MM-DD
    scheduled_time: Optional[str] = None  # HH:MM
    notes: Optional[str] = None


@router.post("/leads/{phone}/convert")
async def convert_lead_to_ticket(phone: str, payload: ConvertIn,
                                       user: dict = Depends(require_role("gestor"))):
    """Cria pre_subscriber + ticket de instalação a partir de um lead.

    Não cria assinante de fato — vira "pre_subscriber" (status=lead) para o
    gestor confirmar. O ticket fica em status `aberto` aguardando atribuição
    de técnico na Lousa.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    now = now_iso()

    # 1. Cria pre_subscriber (não vai pra subscribers oficial até aprovação)
    pre_sub = {
        "id": f"pre-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "phone": phone,
        "name": payload.client_name.strip(),
        "cpf": (payload.cpf or "").strip() or None,
        "address": payload.address.strip(),
        "neighborhood": payload.neighborhood,
        "city": payload.city,
        "plan_name": payload.plan_name,
        "status": "lead",
        "origin": "sales_funnel",
        "captured_by": user.get("email"),
        "created_at": now,
    }
    await db.pre_subscribers.insert_one(dict(pre_sub))

    # 2. Cria ticket de instalação
    ticket = {
        "id": f"tkt-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "type": "instalacao",
        "status": "aberto",
        "priority": "alta",
        "client_snapshot": {
            "name": payload.client_name,
            "phone": phone,
            "cpf": payload.cpf,
            "address": payload.address,
            "neighborhood": payload.neighborhood,
            "city": payload.city,
            "plan_name": payload.plan_name,
        },
        "pre_subscriber_id": pre_sub["id"],
        "origin_source": "sales_funnel",
        "origin_phone": phone,
        "captured_by": user.get("email"),
        "scheduled_date": payload.scheduled_date,
        "scheduled_time": payload.scheduled_time,
        "notes": payload.notes,
        "created_at": now,
    }
    await db.tickets.insert_one(dict(ticket))

    # Sprint 19 — emit sale.created + ticket.opened
    try:
        from services.event_emitters import emit_business
        await emit_business(
            kind="sale.created", actor=user,
            payload={"lead_id": pre_sub["id"],
                       "ticket_id": ticket["id"],
                       "phone": phone,
                       "plan_name": payload.plan_name},
            severity="media", source="sales_funnel.convert")
        await emit_business(
            kind="ticket.opened", actor=user,
            payload={"ticket_id": ticket["id"],
                       "type": "instalacao",
                       "priority": "alta"},
            severity="media", source="sales_funnel.convert")
    except Exception:
        pass

    # 3. Marca conversa como "convertida" pra parar de aparecer em leads
    await db.wa_conversations.update_one(
        {"company_id": cid, "phone": phone},
        {"$set": {"converted_at": now,
                    "converted_ticket_id": ticket["id"],
                    "converted_pre_subscriber_id": pre_sub["id"]}},
    )

    # 4. Log de auditoria
    await db.sales_funnel_log.insert_one({
        "id": f"sfl-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "action": "convert",
        "phone": phone,
        "ticket_id": ticket["id"],
        "pre_subscriber_id": pre_sub["id"],
        "performed_by": user.get("email"),
        "at": now,
    })

    return {"ok": True, "ticket_id": ticket["id"],
             "pre_subscriber_id": pre_sub["id"]}


# ---------------------------------------------------------------------------
# COLD LEADS — reativação
# ---------------------------------------------------------------------------
@router.get("/cold-leads")
async def cold_leads(min_days: int = 14, max_days: int = 90,
                       user: dict = Depends(require_role("gestor"))):
    """Leads que perguntaram sobre plano entre min_days e max_days atrás e
    não foram convertidos. Candidatos a reativação."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    now = datetime.now(timezone.utc)
    cut_max = (now - timedelta(days=max_days)).isoformat()
    cut_min = (now - timedelta(days=min_days)).isoformat()

    convs = await db.wa_conversations.find(
        {"company_id": cid,
          "last_msg_at": {"$gte": cut_max, "$lte": cut_min},
          "converted_at": {"$exists": False},
          "$or": [{"subscriber_id": None}, {"subscriber_id": {"$exists": False}}]},
        {"_id": 0, "phone": 1, "push_name": 1, "last_msg_at": 1, "last_text": 1},
    ).sort("last_msg_at", -1).limit(500).to_list(500)

    items = []
    for c in convs:
        sc = await _aggregate_lead_score(cid, c["phone"])
        if sc["score"] >= 15:  # mostrou ALGUM interesse
            items.append({
                "phone": c["phone"], "push_name": c.get("push_name"),
                "last_msg_at": c.get("last_msg_at"),
                "score_then": sc["score"],
                "days_idle": (now - datetime.fromisoformat(
                    c["last_msg_at"].replace("Z", "+00:00"))).days
                    if c.get("last_msg_at") else None,
            })
    return {"items": items, "total": len(items)}


class ReactivateIn(BaseModel):
    phones: List[str] = Field(..., min_items=1, max_items=200)
    message: str = Field(..., min_length=10, max_length=600)


@router.post("/reactivate")
async def reactivate_cold_leads(payload: ReactivateIn,
                                    user: dict = Depends(require_role("gestor"))):
    """Dispara mensagem de reativação para lista de leads frios via Baileys.

    Cria 1 registro por phone em `mass_messages_jobs` (mesma estrutura do
    disparo em massa) — o worker existente envia em rajada controlada.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    now = now_iso()
    job_id = f"rj-{uuid.uuid4().hex[:10]}"
    items = []
    for ph in payload.phones[:200]:
        items.append({
            "id": f"rmi-{uuid.uuid4().hex[:10]}",
            "company_id": cid, "job_id": job_id,
            "phone": ph, "message": payload.message,
            "status": "pending", "created_at": now,
        })
    if items:
        await db.mass_messages_jobs.insert_many(items)
    await db.sales_funnel_log.insert_one({
        "id": f"sfl-{uuid.uuid4().hex[:10]}",
        "company_id": cid, "action": "reactivate",
        "job_id": job_id, "count": len(items),
        "performed_by": user.get("email"), "at": now,
    })
    return {"ok": True, "job_id": job_id, "queued": len(items)}


# ---------------------------------------------------------------------------
# Score em tempo real (para frontend buscar de uma conversa específica)
# ---------------------------------------------------------------------------
@router.get("/leads/{phone}/score")
async def lead_score(phone: str,
                       user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await _aggregate_lead_score(cid, phone)
