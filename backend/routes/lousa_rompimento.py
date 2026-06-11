"""Lousa Rompimento — fechamento de OS de rompimento de rede via relato livre.

No serviço de ROMPIMENTO, o técnico não escolhe insumos pré-definidos. Ele
descreve em texto o que fez (ex: "passei 80m de drop, troquei 2 conectores
fast e usei 3 esticadores no poste"). A IA (Claude Sonnet 4.5) lê o relato
e identifica os insumos consumidos, mapeando para o catálogo do estoque.

Os itens identificados são baixados do estoque da PRAÇA do técnico.
Se faltar saldo, o estoque pode ficar NEGATIVO — o gestor recebe uma
notificação e regulariza posteriormente com lançamento de entrada.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "operacoes",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso
from database import db
from routes.stok import CONSUMABLE_CATALOG, CONSUMABLE_BY_ID

logger = logging.getLogger("ponto")
router = APIRouter(prefix="/api", tags=["lousa-rompimento"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class RompimentoFinalizeIn(BaseModel):
    collaborator_id: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    report_text: str
    observacoes: Optional[str] = None
    # iter215: ids de OUTRAS notas (reparo) que foram causadas pelo mesmo
    # rompimento — fechadas em lote junto com a OS-pai.
    linked_ticket_ids: List[str] = []


class RompimentoParsePreviewIn(BaseModel):
    report_text: str


class RompimentoSuggestLinksIn(BaseModel):
    collaborator_id: str
    report_text: Optional[str] = None


class _DetectedItem(BaseModel):
    consumable_id: str
    quantity: float
    confidence: float = 0.8
    raw_excerpt: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _build_ai_system_prompt() -> str:
    catalog_lines = []
    for c in CONSUMABLE_CATALOG:
        catalog_lines.append(
            f"  - id='{c['id']}' | nome='{c['name']}' | unidade='{c['unit']}'"
        )
    catalog = "\n".join(catalog_lines)
    return (
        "Você é um assistente de operações de campo de um provedor de internet "
        "fibra (ISP). O técnico vai descrever um serviço de ROMPIMENTO de rede "
        "(fibra ou rede metálica) em linguagem natural, em Português do Brasil. "
        "Sua tarefa é identificar QUAIS insumos foram consumidos e em QUE "
        "quantidade, mapeando para o catálogo abaixo.\n\n"
        f"Catálogo de insumos disponíveis:\n{catalog}\n\n"
        "Regras importantes:\n"
        "1) Responda APENAS um JSON válido, sem texto antes ou depois, sem markdown.\n"
        "2) Estrutura: {\"items\": [ {\"consumable_id\": \"<id>\", \"quantity\": "
        "<numero>, \"confidence\": <0..1>, \"raw_excerpt\": \"<trecho>\"} ], "
        "\"summary\": \"<resumo curto em PT-BR>\"}\n"
        "3) Use APENAS os ids do catálogo. Se algo for ambíguo, escolha o id "
        "mais próximo e abaixe a confidence.\n"
        "4) Quantidades em METROS para itens de unidade 'm' (drop, cabo de rede, "
        "fibras). Quantidades INTEIRAS para itens 'un' (conectores, esticadores).\n"
        "5) Se o técnico não mencionar nenhum insumo identificável, retorne "
        "items vazio: {\"items\": [], \"summary\": \"Nenhum insumo identificado\"}.\n"
        "6) Reconheça abreviações comuns: 'm' = metros, 'mts' = metros, 'pç' = peça, "
        "'un' = unidade, 'cx' = caixa, 'fast' = conector fast, 'sc/apc' = conector de fibra.\n"
    )


def _parse_ai_response(raw: str) -> Dict[str, Any]:
    """Extrai JSON da resposta do LLM (resiliente a markdown)."""
    if not raw:
        return {"items": [], "summary": ""}
    # Remove cercas markdown se houver
    txt = raw.strip()
    txt = re.sub(r"^```(?:json)?\s*", "", txt)
    txt = re.sub(r"\s*```$", "", txt)
    # Busca primeiro objeto JSON
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    if not m:
        return {"items": [], "summary": ""}
    try:
        return json.loads(m.group(0))
    except Exception as e:
        logger.warning("[lousa-rompimento] JSON inválido da IA: %s", e)
        return {"items": [], "summary": ""}


async def _call_claude_for_items(report_text: str) -> Dict[str, Any]:
    key = os.environ.get("EMERGENT_LLM_KEY") or ""
    if not key:
        raise HTTPException(503, "EMERGENT_LLM_KEY não configurada — IA indisponível.")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        raise HTTPException(503, f"emergentintegrations indisponível: {e}") from e

    chat = LlmChat(
        api_key=key,
        session_id=f"rompimento-{uuid.uuid4().hex[:8]}",
        system_message=_build_ai_system_prompt(),
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")

    msg = UserMessage(text=f"Relato do técnico:\n\n{report_text.strip()}")
    raw = ""
    try:
        raw = await chat.send_message(msg)
    except Exception as e:
        logger.exception("[lousa-rompimento] Claude falhou: %s", e)
        raise HTTPException(502, f"Falha ao consultar IA: {e}") from e
    parsed = _parse_ai_response(str(raw or ""))
    return parsed


def _sanitize_items(raw_items: List[Dict[str, Any]]) -> List[_DetectedItem]:
    out: List[_DetectedItem] = []
    for it in raw_items or []:
        cid = (it or {}).get("consumable_id")
        if cid not in CONSUMABLE_BY_ID:
            continue
        try:
            qty = float(it.get("quantity") or 0)
        except Exception:
            continue
        if qty <= 0:
            continue
        unit = CONSUMABLE_BY_ID[cid]["unit"]
        # Insumos em 'un' devem ser inteiros
        if unit == "un":
            qty = float(int(round(qty)))
        out.append(_DetectedItem(
            consumable_id=cid,
            quantity=qty,
            confidence=float(it.get("confidence") or 0.7),
            raw_excerpt=(it.get("raw_excerpt") or None),
        ))
    return out


async def _resolve_praca_for_collab(company_id: str,
                                       collaborator_id: str) -> Optional[str]:
    coll = await db.collaborators.find_one(
        {"id": collaborator_id, "company_id": company_id},
        {"_id": 0, "praca_id": 1, "warehouse_praca_id": 1},
    ) or {}
    return coll.get("praca_id") or coll.get("warehouse_praca_id")


async def _decrement_praca_stock(company_id: str, praca_id: str,
                                    items: List[_DetectedItem],
                                    ticket_id: str) -> List[Dict[str, Any]]:
    """Baixa insumos do estoque da praça (location='praca:<id>'). Permite saldo
    negativo: retorna lista de quebras pra notificar o gestor."""
    location = f"praca:{praca_id}"
    cur_doc = await db.stok_stock.find_one(
        {"company_id": company_id, "location": location}, {"_id": 0},
    ) or {}
    inc: Dict[str, float] = {}
    shortages: List[Dict[str, Any]] = []
    for it in items:
        inc[it.consumable_id] = inc.get(it.consumable_id, 0) - it.quantity
        cur = float(cur_doc.get(it.consumable_id, 0) or 0)
        if cur < it.quantity:
            meta = CONSUMABLE_BY_ID[it.consumable_id]
            shortages.append({
                "consumable_id": it.consumable_id,
                "name": meta["name"],
                "unit": meta["unit"],
                "current": cur,
                "needed": it.quantity,
                "deficit": it.quantity - cur,
            })
    if inc:
        await db.stok_stock.update_one(
            {"company_id": company_id, "location": location},
            {"$inc": inc,
             "$setOnInsert": {"company_id": company_id, "location": location,
                              "praca_id": praca_id}},
            upsert=True,
        )
    # Histórico
    await db.stok_history.insert_one({
        "id": f"romp-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "type": "rompimento",
        "tag": "rompimento_ia",
        "description": (
            f"Rompimento OS {ticket_id} — baixa IA: " +
            "; ".join(
                f"{CONSUMABLE_BY_ID[k]['name']} {abs(v)} {CONSUMABLE_BY_ID[k]['unit']}"
                for k, v in inc.items()
            )
        ),
        "user": "lousa-rompimento-ia",
        "created_at": now_iso(),
        "ticket_id": ticket_id,
        "praca_id": praca_id,
    })
    return shortages


async def _notify_gestor(company_id: str, ticket_id: str, praca_id: str,
                            items: List[_DetectedItem],
                            shortages: List[Dict[str, Any]],
                            tech_name: str) -> None:
    if not items:
        return
    detected = "; ".join(
        f"{CONSUMABLE_BY_ID[i.consumable_id]['name']}: {i.quantity} "
        f"{CONSUMABLE_BY_ID[i.consumable_id]['unit']}"
        for i in items
    )
    deficit_txt = ""
    if shortages:
        deficit_txt = " ⚠️ Saldo negativo: " + ", ".join(
            f"{s['name']} (-{s['deficit']} {s['unit']})" for s in shortages
        )
    await db.notifications.insert_one({
        "id": f"notif-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "type": "rompimento_ia_closure",
        "title": f"💥 Rompimento fechado por {tech_name}",
        "message": (
            f"OS de rompimento {ticket_id[-6:]} fechada com baixa de "
            f"insumos identificados pela IA: {detected}.{deficit_txt} "
            f"Verifique o estoque da praça e regularize se necessário."
        ),
        "severity": "warning" if shortages else "info",
        "created_at": now_iso(),
        "read_by": [],
        "audience_role": "gestor",
        "ticket_id": ticket_id,
        "praca_id": praca_id,
    })


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/lousa/public/rompimento/parse-preview")
async def parse_preview(payload: RompimentoParsePreviewIn):
    """Devolve a IA-parsing do relato SEM fechar a OS. Útil para o app
    mostrar pré-visualização antes do técnico confirmar."""
    text = (payload.report_text or "").strip()
    if len(text) < 5:
        raise HTTPException(400, "Relato muito curto. Descreva o serviço executado.")
    parsed = await _call_claude_for_items(text)
    items = _sanitize_items(parsed.get("items") or [])
    return {
        "items": [
            {
                "consumable_id": i.consumable_id,
                "name": CONSUMABLE_BY_ID[i.consumable_id]["name"],
                "unit": CONSUMABLE_BY_ID[i.consumable_id]["unit"],
                "quantity": i.quantity,
                "confidence": i.confidence,
                "raw_excerpt": i.raw_excerpt,
            } for i in items
        ],
        "summary": parsed.get("summary") or "",
    }


@router.post("/lousa/public/tickets/{ticket_id}/rompimento-finalize")
async def rompimento_finalize(ticket_id: str, payload: RompimentoFinalizeIn,
                                  request: Request = None):
    """Fecha uma OS de rompimento usando IA pra extrair insumos do relato."""
    text = (payload.report_text or "").strip()
    if len(text) < 5:
        raise HTTPException(400, {
            "code": "ROMPIMENTO_REQUIRES_REPORT",
            "message": "Descreva no relato o que foi feito (mín. 5 caracteres).",
        })

    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    if t.get("status") != "aberta":
        raise HTTPException(400, "Somente notas abertas podem ser finalizadas")
    if t.get("assigned_collaborator_id") != payload.collaborator_id:
        raise HTTPException(404, "Nota não pertence a este colaborador")
    if t.get("type") != "rompimento":
        raise HTTPException(400, "Esta OS não é do tipo 'rompimento'")

    company_id = t.get("company_id") or DEMO_COMPANY_ID
    praca_id = await _resolve_praca_for_collab(company_id, payload.collaborator_id)

    # IA: identifica insumos
    parsed = await _call_claude_for_items(text)
    items = _sanitize_items(parsed.get("items") or [])

    # Baixa estoque da praça (permite negativo)
    shortages: List[Dict[str, Any]] = []
    if items and praca_id:
        shortages = await _decrement_praca_stock(
            company_id, praca_id, items, ticket_id)

    # Fecha o ticket
    closed_at = now_iso()
    rompimento_meta = {
        "report_text": text,
        "ai_summary": parsed.get("summary") or "",
        "ai_items": [i.dict() for i in items],
        "shortages": shortages,
        "praca_id": praca_id,
    }
    await db.tickets.update_one(
        {"id": ticket_id},
        {"$set": {
            "status": "finalizada",
            "closed_at": closed_at,
            "finalized_at": closed_at,
            "outcome": "sucesso",
            "rompimento_closure": rompimento_meta,
            "completion_data": {
                "observacoes": payload.observacoes or text[:500],
                "fotos": [], "sinal": 0,
                "qtd_drop": 0, "esticadores": 0, "conectores_fast": 0,
                "cabo_rede": 0, "conectores_rede": 0,
                "fibra_06fo": 0, "fibra_12fo": 0, "fibra_24fo": 0,
            },
            "finalized_latitude": payload.latitude,
            "finalized_longitude": payload.longitude,
        }},
    )

    # ------------------------------------------------------------------
    # Fechamento em lote de notas individuais causadas pelo rompimento
    # (iter215): o técnico pré-selecionou IDs de outras OSes do colaborador
    # que serão fechadas junto. Evita closar uma a uma.
    # ------------------------------------------------------------------
    linked_results: List[Dict[str, Any]] = []
    for linked_id in payload.linked_ticket_ids or []:
        if linked_id == ticket_id:
            continue
        lt = await db.tickets.find_one({"id": linked_id}, {"_id": 0})
        if not lt:
            linked_results.append({"id": linked_id, "ok": False,
                                       "reason": "not_found"})
            continue
        if lt.get("company_id") != company_id:
            linked_results.append({"id": linked_id, "ok": False,
                                       "reason": "tenant_mismatch"})
            continue
        if lt.get("assigned_collaborator_id") != payload.collaborator_id:
            linked_results.append({"id": linked_id, "ok": False,
                                       "reason": "not_owner"})
            continue
        if lt.get("status") not in ("aberta", "pendente"):
            linked_results.append({"id": linked_id, "ok": False,
                                       "reason": "already_closed"})
            continue
        # Fecha a nota individual referenciando o rompimento
        await db.tickets.update_one(
            {"id": linked_id},
            {"$set": {
                "status": "finalizada",
                "closed_at": closed_at,
                "finalized_at": closed_at,
                "outcome": "rompimento_solucionado",
                "linked_rompimento_id": ticket_id,
                "completion_data": {
                    "observacoes": (
                        f"Fechada pelo Rompimento {ticket_id[-6:]}. "
                        f"Causa: rede rompida. Resolvido em lote."
                    ),
                    "fotos": [], "sinal": 0,
                    "qtd_drop": 0, "esticadores": 0, "conectores_fast": 0,
                    "cabo_rede": 0, "conectores_rede": 0,
                    "fibra_06fo": 0, "fibra_12fo": 0, "fibra_24fo": 0,
                },
                "finalized_latitude": payload.latitude,
                "finalized_longitude": payload.longitude,
            }},
        )
        linked_results.append({"id": linked_id, "ok": True,
                                  "client_name": (lt.get("client_snapshot") or {}).get("name")})

    # Notifica gestor
    tech_name = t.get("assigned_collaborator_name") or "técnico"
    if items:
        await _notify_gestor(company_id, ticket_id, praca_id or "—",
                                 items, shortages, tech_name)

    return {
        "ok": True,
        "items": [
            {
                "consumable_id": i.consumable_id,
                "name": CONSUMABLE_BY_ID[i.consumable_id]["name"],
                "unit": CONSUMABLE_BY_ID[i.consumable_id]["unit"],
                "quantity": i.quantity,
                "confidence": i.confidence,
            } for i in items
        ],
        "summary": parsed.get("summary") or "",
        "shortages": shortages,
        "praca_id": praca_id,
        "linked_results": linked_results,
        "linked_count_ok": sum(1 for r in linked_results if r["ok"]),
    }


# ---------------------------------------------------------------------------
# Endpoint auxiliar: lista OSes do colaborador que podem ser vinculadas ao
# rompimento atual (mesmo colaborador, ainda abertas/pendentes, não-rompimento).
# ---------------------------------------------------------------------------
@router.get("/lousa/public/tickets/{ticket_id}/related-open")
async def related_open_tickets(ticket_id: str, collaborator_id: str):
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    if t.get("assigned_collaborator_id") != collaborator_id:
        raise HTTPException(403, "Nota não pertence a este colaborador")
    if t.get("type") != "rompimento":
        raise HTTPException(400, "Disponível apenas para OS de rompimento")

    cursor = db.tickets.find(
        {
            "company_id": t.get("company_id") or DEMO_COMPANY_ID,
            "assigned_collaborator_id": collaborator_id,
            "status": {"$in": ["aberta", "pendente"]},
            "type": {"$ne": "rompimento"},
            "id": {"$ne": ticket_id},
        },
        {"_id": 0, "id": 1, "type": 1, "status": 1, "scheduled_time": 1,
         "created_at": 1, "client_snapshot": 1, "priority": 1, "relato": 1},
    ).sort("created_at", -1).limit(50)
    items = []
    async for row in cursor:
        snap = row.get("client_snapshot") or {}
        items.append({
            "id": row["id"],
            "type": row.get("type") or "reparo",
            "status": row.get("status"),
            "priority": row.get("priority") or "normal",
            "scheduled_time": row.get("scheduled_time"),
            "created_at": row.get("created_at"),
            "client_name": snap.get("name") or "",
            "address": snap.get("address") or "",
            "neighborhood": snap.get("neighborhood") or "",
            "pppoe_user": snap.get("pppoe_user") or "",
            "relato": (snap.get("relato") or "")[:140],
        })
    return {"items": items, "count": len(items)}


# ---------------------------------------------------------------------------
# IA: sugere quais notas devem ser vinculadas ao rompimento.
# Usa Claude 4.5 + bairro do rompimento + relatos das notas abertas.
# ---------------------------------------------------------------------------
def _build_suggest_links_prompt() -> str:
    return (
        "Você é um técnico de campo de provedor de internet fibra (ISP). "
        "Você recebeu uma OS de ROMPIMENTO de rede em um bairro/endereço e "
        "uma lista de outras OSes individuais abertas atribuídas a você. "
        "Sua tarefa é identificar quais OSes individuais foram CAUSADAS "
        "PELO MESMO ROMPIMENTO (mesmo bairro/rua/região, sintomas como "
        "'sem sinal', 'LOS', 'sem internet', 'fibra rompida', 'caiu', etc.).\n\n"
        "Regras:\n"
        "1) Responda APENAS um JSON válido, sem texto antes/depois, sem markdown.\n"
        "2) Estrutura: {\"suggested_ids\": [\"<id1>\", ...], \"reasoning\": "
        "{\"<id>\": \"motivo curto em PT-BR\"}}\n"
        "3) Inclua um id na sugestão SOMENTE se tiver alta confiança "
        "(bairro/rua próximos AO rompimento E sintoma compatível com queda "
        "de rede).\n"
        "4) Se NENHUMA OS individual parecer relacionada, devolva "
        "{\"suggested_ids\": [], \"reasoning\": {}}.\n"
        "5) Não considere OSes de tipo 'instalacao' ou 'venda' — só as que "
        "claramente são 'reparo'/'preventiva' por queda."
    )


@router.post("/lousa/public/tickets/{ticket_id}/rompimento/suggest-links")
async def suggest_links(ticket_id: str, payload: RompimentoSuggestLinksIn):
    """Sugere via IA Claude 4.5 quais notas individuais devem ser vinculadas
    ao rompimento. Retorna {suggested_ids, reasoning}."""
    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Nota não encontrada")
    if t.get("assigned_collaborator_id") != payload.collaborator_id:
        raise HTTPException(403, "Nota não pertence a este colaborador")
    if t.get("type") != "rompimento":
        raise HTTPException(400, "Disponível apenas para OS de rompimento")

    cid = t.get("company_id") or DEMO_COMPANY_ID
    # Lista notas abertas
    cursor = db.tickets.find(
        {"company_id": cid, "assigned_collaborator_id": payload.collaborator_id,
         "status": {"$in": ["aberta", "pendente"]},
         "type": {"$ne": "rompimento"}, "id": {"$ne": ticket_id}},
        {"_id": 0, "id": 1, "type": 1, "client_snapshot": 1},
    ).sort("created_at", -1).limit(50)
    candidates = []
    async for row in cursor:
        snap = row.get("client_snapshot") or {}
        candidates.append({
            "id": row["id"],
            "tipo": row.get("type") or "reparo",
            "cliente": snap.get("name") or "",
            "endereco": snap.get("address") or "",
            "bairro": snap.get("neighborhood") or "",
            "relato": (snap.get("relato") or "")[:200],
        })
    if not candidates:
        return {"suggested_ids": [], "reasoning": {}, "candidates_count": 0}

    rs = t.get("client_snapshot") or {}
    user_msg = {
        "rompimento": {
            "cliente": rs.get("name") or "",
            "endereco": rs.get("address") or "",
            "bairro": rs.get("neighborhood") or "",
            "relato_cliente": (rs.get("relato") or "")[:300],
        },
        "relato_tecnico": (payload.report_text or "").strip()[:600] or None,
        "os_individuais_abertas": candidates,
    }

    key = os.environ.get("EMERGENT_LLM_KEY") or ""
    if not key:
        raise HTTPException(503, "EMERGENT_LLM_KEY não configurada — IA indisponível.")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        raise HTTPException(503, f"emergentintegrations indisponível: {e}") from e

    chat = LlmChat(
        api_key=key,
        session_id=f"romp-suggest-{uuid.uuid4().hex[:8]}",
        system_message=_build_suggest_links_prompt(),
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")
    msg = UserMessage(text=json.dumps(user_msg, ensure_ascii=False, indent=2))
    raw = ""
    try:
        raw = await chat.send_message(msg)
    except Exception as e:
        logger.exception("[lousa-rompimento] suggest-links falhou: %s", e)
        raise HTTPException(502, f"Falha ao consultar IA: {e}") from e

    parsed = _parse_ai_response(str(raw or ""))
    valid_ids = {c["id"] for c in candidates}
    suggested = [i for i in (parsed.get("suggested_ids") or []) if i in valid_ids]
    reasoning = parsed.get("reasoning") or {}
    return {
        "suggested_ids": suggested,
        "reasoning": {k: v for k, v in reasoning.items() if k in valid_ids},
        "candidates_count": len(candidates),
    }
