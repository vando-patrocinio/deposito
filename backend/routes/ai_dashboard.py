"""IA Dashboards & Insights — centraliza tudo de IA do produto.

Endpoints:
- Overview KPIs
- Tech Spending (gastos de insumos por técnico × notas fechadas)
- Repair Map (geo-coordenadas das reclamações com sinal/tipo)
- Defective Equipment (modelos/MAC com mais ocorrências)
- Common Issues (reclamações por OLT/board/port)
- Recurring Tickets (clientes que mais reclamam)
- Insight Generator (LLM com Universal Key — Gemini Flash)
"""
from __future__ import annotations

import logging
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, EMERGENT_LLM_KEY, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.ai_dashboard")
router = APIRouter(prefix="/api/ai/dashboard", tags=["ai_dashboard"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _norm_complaint(text: str) -> str:
    """Normaliza relato pra agrupamento — minúsculas, remove números/pontuação."""
    if not text:
        return ""
    t = text.lower().strip()
    t = re.sub(r"\d+", "", t)
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:80]


def _classify_complaint(text: str) -> str:
    """Classifica relato em uma de ~10 categorias."""
    t = (text or "").lower()
    if any(k in t for k in ("sem internet", "sem sinal", "não conecta", "fora", "queda")):
        return "Sem internet"
    if "lent" in t or "ruim" in t:
        return "Lentidão"
    if "wifi" in t or "wi-fi" in t or "senha" in t:
        return "Wi-Fi/Senha"
    if "tv" in t or "iptv" in t:
        return "TV/IPTV"
    if "trav" in t or "instabilidade" in t or "oscila" in t:
        return "Instabilidade"
    if "ond" in t or "onu" in t:
        return "ONT/Equipamento"
    if "tomada" in t or "energia" in t or "queim" in t:
        return "Energia/Tomada"
    if "instala" in t or "ativa" in t:
        return "Instalação"
    if "trocar" in t or "substitu" in t:
        return "Troca de equipamento"
    return "Outros"


# ---------------------------------------------------------------------------
# 1) Overview KPIs
# ---------------------------------------------------------------------------
@router.get("/overview")
async def overview(days: int = 30, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cutoff = _cutoff(days)
    # Tickets stats
    total = await db.tickets.count_documents({"company_id": cid, "created_at": {"$gte": cutoff}})
    finalizadas = await db.tickets.count_documents(
        {"company_id": cid, "closed_at": {"$gte": cutoff}, "status": "finalizada"})
    canceladas = await db.tickets.count_documents(
        {"company_id": cid, "closed_at": {"$gte": cutoff}, "status": "cancelada"})
    abertas = await db.tickets.count_documents(
        {"company_id": cid, "status": {"$in": ["aberta", "aguardando_atendimento", "pendente"]}})
    # Técnicos ativos
    techs = await db.collaborators.count_documents(
        {"company_id": cid, "atlaz_inbox": {"$ne": True}, "active": {"$ne": False}})
    # AI Preventivas
    prev_pending = await db.ai_preventive_suggestions.count_documents(
        {"company_id": cid, "status": "pending"})
    prev_accepted = await db.ai_preventive_suggestions.count_documents(
        {"company_id": cid, "status": "accepted", "created_at": {"$gte": cutoff}})
    # SmartOLT
    onus_total = await db.smartolt_onus.count_documents({"company_id": cid})
    onus_critical = await db.smartolt_onus.count_documents(
        {"company_id": cid, "status": "Online",
         "$or": [{"signal_1490": {"$lte": -27}}, {"signal_text": {"$in": ["Bad", "Warning"]}}]})
    # Notifications
    notif_unread = await db.notifications.count_documents(
        {"company_id": cid, "audience_role": "gestor",
         "$or": [{"read_by": {"$exists": False}}, {"read_by": []}, {"read": False}]})
    # Estoque erro
    stok_errors = await db.stok_services.count_documents(
        {"company_id": cid, "status": "erro_estoque"})

    return {
        "period_days": days,
        "tickets": {"total": total, "finalizadas": finalizadas, "canceladas": canceladas, "abertas": abertas,
                    "fechamento_pct": round(100 * finalizadas / max(1, total), 1)},
        "technicians": {"ativos": techs},
        "ai_preventive": {"pending": prev_pending, "accepted_period": prev_accepted},
        "smartolt": {"onus_total": onus_total, "onus_critical": onus_critical,
                      "critical_pct": round(100 * onus_critical / max(1, onus_total), 1)},
        "alerts": {"notif_unread": notif_unread, "stok_errors": stok_errors},
    }


# ---------------------------------------------------------------------------
# 2) Tech Spending — gasto de insumos por técnico × notas fechadas
# ---------------------------------------------------------------------------
@router.get("/tech-spending")
async def tech_spending(days: int = 30, user: dict = Depends(require_role("gestor"))):
    """Para cada técnico:
    - notas_fechadas (período)
    - insumos_total (m de drop + un esticador + un fast + ...)
    - custo_estimado_brl (parametrizado)
    - media_por_nota (insumos / notas)
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cutoff = _cutoff(days)
    # Custo estimado por insumo (BRL) — heurística inicial
    PRICE_BRL = {"drop": 0.35, "esticador": 1.20, "conector_fast": 2.50,
                 "cabo_rede": 0.80, "conector_rede": 1.10, "conector_fibra": 4.00}

    # Histórico de baixa = stok_history com tag auto_finalize_lousa ou instalacao/retirada
    cur = db.stok_history.find(
        {"company_id": cid, "date": {"$gte": cutoff},
         "type": {"$in": ["instalacao", "retirada"]},
         "tag": "auto_finalize_lousa"},
        {"_id": 0, "user": 1, "description": 1},
    )
    # Parse description: "OS-XXX (auto-baixa Lousa) - 30m drop, 4un conector_fast | 1 esticador - Técnico NOME"
    by_tech: Dict[str, Dict[str, float]] = {}
    async for h in cur:
        desc = h.get("description", "")
        # Extract qty/unidade
        qty_pattern = re.findall(r"(\d+(?:\.\d+)?)\s*(m|un)\s+([a-z_]+)", desc)
        # Sometimes format is "30m drop", "4un conector_fast"
        # Get técnico name
        m = re.search(r"Técnico ([^\[\-]+)", desc)
        tech_name = (m.group(1).strip() if m else h.get("user", "?")).strip()
        bucket = by_tech.setdefault(tech_name, {"insumos": {}, "custo_brl": 0.0, "notas_count": 0})
        bucket["notas_count"] += 1
        for qty_str, unit, item_id in qty_pattern:
            try:
                q = float(qty_str)
            except ValueError:
                continue
            bucket["insumos"][item_id] = bucket["insumos"].get(item_id, 0) + q
            bucket["custo_brl"] += q * PRICE_BRL.get(item_id, 0)

    # Cross-check com notas finalizadas (para média)
    techs_collab = await db.collaborators.find(
        {"company_id": cid, "atlaz_inbox": {"$ne": True}}, {"_id": 0, "id": 1, "name": 1},
    ).to_list(200)
    name_to_id = {t["name"]: t["id"] for t in techs_collab}
    rows: List[dict] = []
    for tname, b in by_tech.items():
        finalizadas = await db.tickets.count_documents(
            {"company_id": cid, "closed_at": {"$gte": cutoff}, "status": "finalizada",
             "assigned_collaborator_id": name_to_id.get(tname)})
        rows.append({
            "tech_name": tname,
            "tech_id": name_to_id.get(tname),
            "notas_baixadas_estoque": b["notas_count"],
            "notas_finalizadas_lousa": finalizadas,
            "insumos_totais": {k: round(v, 1) for k, v in b["insumos"].items()},
            "custo_estimado_brl": round(b["custo_brl"], 2),
            "custo_medio_por_nota": round(b["custo_brl"] / max(1, b["notas_count"]), 2),
        })
    rows.sort(key=lambda r: r["custo_estimado_brl"], reverse=True)
    total_custo = sum(r["custo_estimado_brl"] for r in rows)
    total_notas = sum(r["notas_baixadas_estoque"] for r in rows)
    return {
        "period_days": days,
        "rows": rows,
        "totals": {"custo_brl": round(total_custo, 2), "notas": total_notas,
                    "custo_medio_por_nota": round(total_custo / max(1, total_notas), 2)},
        "price_table_brl": PRICE_BRL,
    }


# ---------------------------------------------------------------------------
# 3) Repair Map — coordenadas das reclamações
# ---------------------------------------------------------------------------
@router.get("/repair-map")
async def repair_map(days: int = 30,
                       only_finalized: bool = False,
                       user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cutoff = _cutoff(days)
    q: Dict[str, Any] = {"company_id": cid, "created_at": {"$gte": cutoff}}
    if only_finalized:
        q["status"] = "finalizada"
    cur = db.tickets.find(q, {
        "_id": 0, "id": 1, "type": 1, "status": 1, "priority": 1,
        "client_snapshot": 1, "scheduled_time": 1, "created_at": 1, "live_signal": 1,
    })
    out: List[dict] = []
    type_counter: Counter = Counter()
    async for t in cur:
        snap = t.get("client_snapshot") or {}
        lat, lng = snap.get("latitude"), snap.get("longitude")
        if lat is None or lng is None:
            continue
        out.append({
            "id": t["id"], "type": t.get("type"), "status": t.get("status"),
            "priority": t.get("priority"),
            "client_name": snap.get("name"), "address": snap.get("address"),
            "neighborhood": snap.get("neighborhood"), "phone": snap.get("phone"),
            "pppoe_user": snap.get("pppoe_user"),
            "relato": (snap.get("relato") or "")[:160],
            "category": _classify_complaint(snap.get("relato") or ""),
            "latitude": lat, "longitude": lng,
            "rx_dbm": (t.get("live_signal") or {}).get("rx_dbm"),
            "signal_quality": (t.get("live_signal") or {}).get("quality"),
            "created_at": t.get("created_at"),
            "scheduled_time": t.get("scheduled_time"),
        })
        type_counter[t.get("type") or "?"] += 1
    return {
        "period_days": days, "count": len(out), "points": out,
        "by_type": dict(type_counter.most_common()),
    }


# ---------------------------------------------------------------------------
# 4) Defective Equipment — equipamentos com mais ocorrências
# ---------------------------------------------------------------------------
@router.get("/defective-equipment")
async def defective_equipment(days: int = 90,
                                user: dict = Depends(require_role("gestor"))):
    """Cruza reclamações com SmartOLT pra agrupar por modelo de ONT."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cutoff = _cutoff(days)
    # Tickets com pppoe → match no smartolt_onus
    tickets = await db.tickets.find(
        {"company_id": cid, "created_at": {"$gte": cutoff},
         "type": {"$in": ["reparo", "troca_endereco", "troca_titularidade"]}},
        {"_id": 0, "id": 1, "client_snapshot.name": 1, "client_snapshot.pppoe_user": 1,
         "client_snapshot.relato": 1, "type": 1},
    ).to_list(2000)
    # Agrupa por modelo + por ONT individual
    from routes.smartolt import _norm
    by_model: Dict[str, Dict[str, Any]] = {}
    by_ont: Dict[str, Dict[str, Any]] = {}
    for t in tickets:
        snap = t.get("client_snapshot") or {}
        key = _norm(snap.get("pppoe_user")) or _norm(snap.get("name"))
        if not key:
            continue
        onu = await db.smartolt_onus.find_one(
            {"company_id": cid, "name_norm": key},
            {"_id": 0, "unique_external_id": 1, "name": 1, "onu_type_name": 1,
             "olt_name": 1, "board": 1, "port": 1, "signal_1490": 1, "status": 1, "sn": 1},
        )
        if not onu:
            continue
        model = onu.get("onu_type_name") or "Desconhecido"
        bucket_m = by_model.setdefault(model, {"count": 0, "tickets": [], "macs": set()})
        bucket_m["count"] += 1
        bucket_m["macs"].add(onu.get("unique_external_id") or onu.get("sn"))
        ext_id = onu.get("unique_external_id") or onu.get("sn") or "?"
        bucket_o = by_ont.setdefault(ext_id, {
            "count": 0, "model": model, "name": onu.get("name"),
            "olt": onu.get("olt_name"), "board": onu.get("board"), "port": onu.get("port"),
            "current_signal": onu.get("signal_1490"), "current_status": onu.get("status"),
            "categorias": Counter(),
        })
        bucket_o["count"] += 1
        bucket_o["categorias"][_classify_complaint(snap.get("relato") or "")] += 1

    models_rows = sorted([
        {"model": k, "ocorrencias": v["count"], "equipamentos_distintos": len(v["macs"])}
        for k, v in by_model.items()
    ], key=lambda r: r["ocorrencias"], reverse=True)
    onts_rows = sorted([
        {"external_id": k, "name": v["name"], "model": v["model"],
         "olt": v["olt"], "board": v["board"], "port": v["port"],
         "current_signal": v["current_signal"], "current_status": v["current_status"],
         "ocorrencias": v["count"],
         "top_categoria": v["categorias"].most_common(1)[0][0] if v["categorias"] else None}
        for k, v in by_ont.items()
    ], key=lambda r: r["ocorrencias"], reverse=True)[:50]
    return {
        "period_days": days, "models": models_rows, "top_onts": onts_rows,
        "total_matched_tickets": sum(b["count"] for b in by_model.values()),
    }


# ---------------------------------------------------------------------------
# 5) Common Issues — reclamações por OLT/board/port
# ---------------------------------------------------------------------------
@router.get("/common-issues")
async def common_issues(days: int = 30,
                          user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cutoff = _cutoff(days)
    tickets = await db.tickets.find(
        {"company_id": cid, "created_at": {"$gte": cutoff}},
        {"_id": 0, "client_snapshot.relato": 1, "client_snapshot.pppoe_user": 1,
         "client_snapshot.name": 1},
    ).to_list(5000)
    cat_counter: Counter = Counter()
    olt_counter: Counter = Counter()
    pp_counter: Counter = Counter()
    from routes.smartolt import _norm
    for t in tickets:
        snap = t.get("client_snapshot") or {}
        cat = _classify_complaint(snap.get("relato") or "")
        cat_counter[cat] += 1
        key = _norm(snap.get("pppoe_user")) or _norm(snap.get("name"))
        if key:
            onu = await db.smartolt_onus.find_one(
                {"company_id": cid, "name_norm": key},
                {"_id": 0, "olt_name": 1, "board": 1, "port": 1},
            )
            if onu:
                olt_counter[onu.get("olt_name") or "?"] += 1
                pp_counter[f"{onu.get('olt_name', '?')} · B{onu.get('board', '?')} / P{onu.get('port', '?')}"] += 1
    return {
        "period_days": days,
        "by_category": [{"category": k, "count": v} for k, v in cat_counter.most_common()],
        "by_olt": [{"olt": k, "count": v} for k, v in olt_counter.most_common()],
        "by_port": [{"location": k, "count": v} for k, v in pp_counter.most_common(20)],
    }


# ---------------------------------------------------------------------------
# 6) Recurring Tickets — clientes/técnicos com mais reincidência
# ---------------------------------------------------------------------------
@router.get("/recurring-tickets")
async def recurring_tickets(days: int = 30,
                              user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cutoff = _cutoff(days)
    cur = db.tickets.find(
        {"company_id": cid, "created_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "client_snapshot.name": 1, "client_snapshot.pppoe_user": 1,
         "client_snapshot.address": 1, "assigned_collaborator_id": 1,
         "type": 1, "status": 1, "created_at": 1},
    )
    by_client: Dict[str, Dict[str, Any]] = {}
    techs_revisits: Dict[str, Dict[str, Any]] = {}
    techs_collab = await db.collaborators.find(
        {"company_id": cid}, {"_id": 0, "id": 1, "name": 1},
    ).to_list(200)
    tid_to_name = {t["id"]: t["name"] for t in techs_collab}
    from routes.smartolt import _norm
    async for t in cur:
        snap = t.get("client_snapshot") or {}
        key = _norm(snap.get("pppoe_user")) or _norm(snap.get("name") or "") or t["id"]
        b = by_client.setdefault(key, {
            "client_name": snap.get("name"), "pppoe_user": snap.get("pppoe_user"),
            "address": snap.get("address"), "tickets": [], "techs": Counter(),
            "types": Counter(),
        })
        b["tickets"].append(t["id"])
        b["techs"][tid_to_name.get(t.get("assigned_collaborator_id"), "?")] += 1
        b["types"][t.get("type") or "?"] += 1

    # Técnicos que mais voltam ao mesmo cliente
    for client_key, b in by_client.items():
        if len(b["tickets"]) < 2:
            continue
        for tech_name, n in b["techs"].items():
            if n >= 2:
                tr = techs_revisits.setdefault(tech_name, {"revisits": 0, "clients": []})
                tr["revisits"] += n - 1  # cada repetição além da 1ª
                tr["clients"].append({"client": b["client_name"], "count": n,
                                       "pppoe": b["pppoe_user"]})

    clients_rows = sorted([
        {"client_name": v["client_name"], "pppoe_user": v["pppoe_user"],
         "address": v["address"], "total_tickets": len(v["tickets"]),
         "techs_envolvidos": dict(v["techs"]),
         "tipos": dict(v["types"])}
        for v in by_client.values() if len(v["tickets"]) >= 2
    ], key=lambda r: r["total_tickets"], reverse=True)[:50]

    techs_rows = sorted([
        {"tech_name": k, "revisits_count": v["revisits"],
         "top_clients": v["clients"][:5]}
        for k, v in techs_revisits.items()
    ], key=lambda r: r["revisits_count"], reverse=True)

    return {
        "period_days": days,
        "top_recurring_clients": clients_rows,
        "techs_revisits": techs_rows,
        "total_clients_with_2_plus": len(clients_rows),
    }


# ---------------------------------------------------------------------------
# 7) Insight Generator (LLM)
# ---------------------------------------------------------------------------
class InsightRequest(BaseModel):
    dashboard: str  # "overview" | "tech_spending" | "common_issues" | "recurring" | "defective"
    context_days: int = 30


@router.post("/insight")
async def generate_insight(payload: InsightRequest,
                              user: dict = Depends(require_role("gestor"))):
    if not EMERGENT_LLM_KEY:
        raise HTTPException(500, "EMERGENT_LLM_KEY não configurada.")
    # Coleta dados conforme o dashboard pedido
    cid = user.get("company_id") or DEMO_COMPANY_ID
    days = payload.context_days
    user_dep = user
    data: Dict[str, Any] = {}
    try:
        if payload.dashboard == "overview":
            data = await overview(days, user=user_dep)
        elif payload.dashboard == "tech_spending":
            data = await tech_spending(days, user=user_dep)
        elif payload.dashboard == "common_issues":
            data = await common_issues(days, user=user_dep)
        elif payload.dashboard == "recurring":
            data = await recurring_tickets(days, user=user_dep)
        elif payload.dashboard == "defective":
            data = await defective_equipment(days, user=user_dep)
        else:
            raise HTTPException(400, "dashboard inválido")
    except Exception as e:
        raise HTTPException(500, f"Falha ao coletar dados: {e}")

    # Chama LLM (Gemini Flash via Universal Key)
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"insight-{cid}-{uuid.uuid4().hex[:8]}",
        system_message=(
            "Você é um analista sênior de operações de provedores de internet (FTTH). "
            "Recebe um JSON com KPIs do último período e gera 3-5 insights ACIONÁVEIS, "
            "no formato bullet em PORTUGUÊS, focados em redução de custo, qualidade de "
            "serviço e produtividade dos técnicos. Cada insight deve citar números do JSON. "
            "Não invente dados. Termine com 1 ação RECOMENDADA prioritária."
        ),
    ).with_model("gemini", "gemini-2.5-flash")
    import json as _json
    prompt = (f"Dashboard: {payload.dashboard}\nPeríodo: {days} dias\n"
              f"Dados:\n```json\n{_json.dumps(data, ensure_ascii=False, default=str)[:8000]}\n```")
    try:
        resp = await chat.send_message(UserMessage(text=prompt))
        text = resp if isinstance(resp, str) else getattr(resp, "text", str(resp))
    except Exception as e:
        raise HTTPException(502, f"LLM falhou: {e}")

    # Persiste pra histórico
    rec = {
        "id": f"insight-{uuid.uuid4().hex[:10]}",
        "company_id": cid, "dashboard": payload.dashboard,
        "context_days": days, "generated_at": now_iso(),
        "generated_by": user.get("name"), "text": text,
    }
    await db.ai_insights.insert_one(rec)
    rec.pop("_id", None)
    return {"id": rec["id"], "text": text, "dashboard": payload.dashboard}


@router.get("/insights/history")
async def insights_history(limit: int = 20, user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cur = db.ai_insights.find({"company_id": cid}, {"_id": 0}).sort("generated_at", -1).limit(limit)
    return await cur.to_list(limit)
