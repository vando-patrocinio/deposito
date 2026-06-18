"""Célula REDE (Tier 2) — escalonamento de OS da Lousa para técnico de rede.

Mandato CEO 18/06/2026:
  • Botão "REDE" substitui o "IA" na bolha de OS.
  • Fluxo: campo → modal → IA sugere causa → checklist → escalar OU
    "IA me ajudou, não preciso escalar" (KPI Escalações Evitadas).
  • Coluna virtual REDE (análoga ao SALA) recebe os escalados; gestor atribui
    depois para técnico de rede específico.

Best practices ITSM (Tier 2) aplicadas:
  • Escalation rate, MTTR, FTFR, Reopen rate, Top causas, Escalações evitadas
  • Antes de escalar, técnico confirma checks físicos (limpeza + power cycle)
  • IA Tier 2 sugere causa baseado em sinal/histórico antes do escalonamento
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database import db
from core import get_current_user  # type: ignore

router = APIRouter(prefix="/api/lousa", tags=["rede-cell"])
watch_router = APIRouter(prefix="/api/watchtower", tags=["watchtower"])

REDE_VIRTUAL_KIND = "rede_cell"
REDE_VIRTUAL_NAME = "REDE"
SIGNAL_CRITICAL_THRESHOLD = -27.0  # GPON cutoff por best-practice FTTH


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _rede_collab_id(company_id: str) -> str:
    return f"col-rede-{company_id}"


async def ensure_rede_virtual_collaborator(company_id: str) -> str:
    """Garante que existe a coluna virtual REDE para a empresa.

    Idempotente. Retorna o id do collaborator virtual.
    """
    cid = _rede_collab_id(company_id)
    doc = await db.collaborators.find_one({"company_id": company_id, "id": cid})
    if not doc:
        doc = {
            "id": cid,
            "company_id": company_id,
            "name": REDE_VIRTUAL_NAME,
            "cargo": "rede",
            "cpf": f"virt-rede-{company_id}",  # único, não null (evita conflito com index cpf_1)
            "is_virtual": True,
            "virtual_kind": REDE_VIRTUAL_KIND,
            "active": True,
            "avatar_data_url": None,
            "created_at": _now_iso(),
            "created_by": "rede_cell_bootstrap",
        }
        await db.collaborators.insert_one(doc)
    return cid


# ═════════════════════════════════════════════════════════════════════════
# IA SUGESTÃO — Tier 2 pré-escalonamento
# ═════════════════════════════════════════════════════════════════════════

class AISuggestResponse(BaseModel):
    suggestions: List[Dict[str, Any]]
    can_avoid_escalation: bool
    advice_text: str
    signal_dbm: Optional[float] = None
    used_model: str


async def _ai_suggest_cause(ticket: Dict[str, Any]) -> AISuggestResponse:
    """Pergunta para a IA qual a causa provável e se dá pra resolver sem escalar.

    Usa Emergent Universal Key (Claude Sonnet 4.5 — text generation barato).
    Fallback: heurística determinística se IA falhar.
    """
    # Coleta evidências
    signal = None
    sa_open = ticket.get("signal_at_open") or {}
    cd = ticket.get("completion_data") or {}
    co = ticket.get("central_ont") or {}
    for src in (cd.get("sinal"), sa_open.get("rx_dbm"), co.get("sinal")):
        if isinstance(src, (int, float)):
            signal = float(src)
            break
    ticket_type = ticket.get("type") or "?"
    description = (cd.get("descricao") or ticket.get("description") or "")[:240]
    onu_serial = cd.get("ont") or co.get("sn") or ""

    fallback = _heuristic_suggest(signal, ticket_type, description)

    # Tenta IA real (se key existir)
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        return AISuggestResponse(
            suggestions=fallback["suggestions"],
            can_avoid_escalation=fallback["can_avoid_escalation"],
            advice_text=fallback["advice_text"],
            signal_dbm=signal,
            used_model="heuristic_v1",
        )
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage  # noqa: PLC0415
        session_id = f"rede-cell-{ticket.get('id')}-{uuid.uuid4().hex[:6]}"
        system = (
            "Você é um engenheiro de rede sênior FTTH/GPON brasileiro. "
            "Sua tarefa: dado o estado de uma OS de campo, sugerir 3 causas "
            "prováveis (com probabilidade %) e dizer se dá pra evitar "
            "escalonamento para a célula REDE. "
            "Limiar crítico GPON: -27 dBm. Acima disso (mais negativo) é "
            "perda física quase certa. Responda APENAS em JSON: "
            '{"suggestions":[{"cause":"...","probability_pct":NN,'
            '"action":"...","tier":"campo|rede"},...3 itens],'
            '"can_avoid_escalation":bool,"advice_text":"resumo curto pt-BR"}'
        )
        user_msg = (
            f"OS tipo: {ticket_type}\n"
            f"Sinal RX: {signal} dBm (limiar crítico -27 dBm)\n"
            f"ONU serial: {onu_serial}\n"
            f"Descrição: {description}\n"
            "Devolva o JSON puro, sem markdown, sem comentários."
        )
        chat = LlmChat(api_key=key, session_id=session_id,
                        system_message=system).with_model(
            "anthropic", "claude-sonnet-4-5-20250929")
        raw = await chat.send_message(UserMessage(text=user_msg))
        import json
        # Parser tolerante: pega o primeiro JSON do texto
        txt = (raw or "").strip()
        if "```" in txt:
            txt = txt.split("```", 2)[1]
            if txt.startswith("json"):
                txt = txt[4:]
        # Trim para o primeiro {...}
        i, j = txt.find("{"), txt.rfind("}")
        if i >= 0 and j > i:
            txt = txt[i:j+1]
        parsed = json.loads(txt)
        suggestions = parsed.get("suggestions") or []
        # Sanitiza
        clean: List[Dict[str, Any]] = []
        for s in suggestions[:3]:
            clean.append({
                "cause": str(s.get("cause", ""))[:80],
                "probability_pct": float(s.get("probability_pct", 0)),
                "action": str(s.get("action", ""))[:160],
                "tier": s.get("tier") if s.get("tier") in ("campo", "rede") else "rede",
            })
        if not clean:
            return AISuggestResponse(
                suggestions=fallback["suggestions"],
                can_avoid_escalation=fallback["can_avoid_escalation"],
                advice_text=fallback["advice_text"],
                signal_dbm=signal,
                used_model="heuristic_v1_fallback",
            )
        return AISuggestResponse(
            suggestions=clean,
            can_avoid_escalation=bool(parsed.get("can_avoid_escalation")),
            advice_text=str(parsed.get("advice_text", ""))[:400],
            signal_dbm=signal,
            used_model="claude-sonnet-4-5-20250929",
        )
    except Exception as e:  # noqa: BLE001
        return AISuggestResponse(
            suggestions=fallback["suggestions"],
            can_avoid_escalation=fallback["can_avoid_escalation"],
            advice_text=fallback["advice_text"] + f" [fallback: {type(e).__name__}]",
            signal_dbm=signal,
            used_model="heuristic_v1_fallback",
        )


def _heuristic_suggest(signal: Optional[float], ttype: str,
                        description: str) -> Dict[str, Any]:
    """Heurística determinística sem LLM — fallback robusto."""
    if signal is not None and signal <= SIGNAL_CRITICAL_THRESHOLD:
        return {
            "suggestions": [
                {"cause": "Perda física na fibra (rompimento/atenuação)",
                 "probability_pct": 55, "tier": "rede",
                 "action": "OTDR + inspeção da rota; possível splicing"},
                {"cause": "Conector sujo/queimado",
                 "probability_pct": 25, "tier": "campo",
                 "action": "Limpar conector da ONT e do drop"},
                {"cause": "Splitter degradado / SFP OLT",
                 "probability_pct": 20, "tier": "rede",
                 "action": "REDE verifica SFP da porta OLT e splitter"},
            ],
            "can_avoid_escalation": False,
            "advice_text": (
                f"Sinal {signal} dBm ≤ -27 dBm (limiar GPON). "
                "Probabilidade alta de perda física. Antes de escalar, "
                "limpe os conectores e reinicie a ONT. Se persistir, escale."
            ),
        }
    if signal is not None and signal <= -24.0:
        return {
            "suggestions": [
                {"cause": "Sinal degradado mas tolerável",
                 "probability_pct": 45, "tier": "campo",
                 "action": "Limpar conector, refazer fusão se houver"},
                {"cause": "Conector sujo",
                 "probability_pct": 35, "tier": "campo",
                 "action": "Cleaner de fibra + inspeção visual"},
                {"cause": "Rota com perda acumulada",
                 "probability_pct": 20, "tier": "rede",
                 "action": "Avaliar projeto da rota"},
            ],
            "can_avoid_escalation": True,
            "advice_text": (
                f"Sinal {signal} dBm está em zona amarela. "
                "Tente limpar e refazer conexão antes de escalar."
            ),
        }
    if "rogue" in description.lower() or "ofuscando" in description.lower():
        return {
            "suggestions": [
                {"cause": "Rogue ONU na rota",
                 "probability_pct": 70, "tier": "rede",
                 "action": "REDE roda show pon rogue-onu na OLT"},
                {"cause": "Interferência cruzada",
                 "probability_pct": 20, "tier": "rede",
                 "action": "Mapear porta com problema"},
                {"cause": "Sinal saturado",
                 "probability_pct": 10, "tier": "campo",
                 "action": "Atenuador na ONT"},
            ],
            "can_avoid_escalation": False,
            "advice_text": "Sintoma de rogue ONU. Escale para REDE.",
        }
    # Sinal OK ou desconhecido
    return {
        "suggestions": [
            {"cause": "Problema no equipamento do cliente",
             "probability_pct": 50, "tier": "campo",
             "action": "Substituir ONT/cabos LAN"},
            {"cause": "Configuração de provisionamento",
             "probability_pct": 30, "tier": "rede",
             "action": "REDE valida VLAN/perfil do cliente"},
            {"cause": "Plano/contrato",
             "probability_pct": 20, "tier": "campo",
             "action": "Confirmar plano contratado"},
        ],
        "can_avoid_escalation": True,
        "advice_text": (
            "Sinal não crítico ou ausente. "
            "Tente troubleshoot local antes de escalar."
        ),
    }


# ═════════════════════════════════════════════════════════════════════════
# ENDPOINT — IA sugere antes do escalonamento
# ═════════════════════════════════════════════════════════════════════════

@router.post("/tickets/{ticket_id}/rede/ai-suggest")
async def rede_ai_suggest(ticket_id: str,
                            user: dict = Depends(get_current_user)):
    company_id = user.get("company_id")
    t = await db.tickets.find_one({"id": ticket_id, "company_id": company_id},
                                     {"_id": 0})
    if not t:
        raise HTTPException(404, "Ticket não encontrado")
    suggest = await _ai_suggest_cause(t)
    sug_id = f"sug-{uuid.uuid4().hex[:10]}"
    await db.rede_ai_suggestions.insert_one({
        "id": sug_id,
        "company_id": company_id,
        "ticket_id": ticket_id,
        "user_id": user.get("id"),
        "user_email": user.get("email"),
        "created_at": _now_iso(),
        "signal_dbm": suggest.signal_dbm,
        "can_avoid_escalation": suggest.can_avoid_escalation,
        "used_model": suggest.used_model,
        "suggestions": suggest.suggestions,
        "advice_text": suggest.advice_text,
        "outcome": "pending",
    })
    payload = suggest.model_dump()
    payload["_sug_id"] = sug_id
    return payload


# ═════════════════════════════════════════════════════════════════════════
# ENDPOINT — Escalonar para REDE (move ticket para coluna virtual REDE)
# ═════════════════════════════════════════════════════════════════════════

class EscalateRequest(BaseModel):
    cause: str = Field(..., max_length=80)
    sub_cause: Optional[str] = Field(None, max_length=80)
    signal_dbm: Optional[float] = None
    observations: Optional[str] = Field(None, max_length=600)
    checklist: Dict[str, bool] = Field(default_factory=dict)
    ai_suggestion_id: Optional[str] = None


@router.post("/tickets/{ticket_id}/rede/escalate")
async def rede_escalate(ticket_id: str, payload: EscalateRequest,
                          user: dict = Depends(get_current_user)):
    company_id = user.get("company_id")
    t = await db.tickets.find_one({"id": ticket_id, "company_id": company_id},
                                     {"_id": 0})
    if not t:
        raise HTTPException(404, "Ticket não encontrado")
    # Idempotência: se já escalado em aberto, retorna 200 sem duplicar
    open_esc = await db.rede_escalations.find_one({
        "company_id": company_id, "ticket_id": ticket_id,
        "status": {"$in": ["pendente", "em_atendimento"]},
    })
    if open_esc:
        return {"ok": True, "already_escalated": True,
                "escalation_id": open_esc["id"]}

    # Garante coluna virtual REDE
    rede_id = await ensure_rede_virtual_collaborator(company_id)

    # Snapshot do técnico de campo (para depois medir "campo→rede")
    prior_collab = t.get("assigned_collaborator_id")

    esc_id = f"esc-{uuid.uuid4().hex[:10]}"
    now = _now_iso()
    esc_doc = {
        "id": esc_id,
        "company_id": company_id,
        "ticket_id": ticket_id,
        "ticket_type": t.get("type"),
        "client_id": t.get("client_id"),
        "from_collaborator_id": prior_collab,
        "to_collaborator_id": rede_id,
        "cause": payload.cause,
        "sub_cause": payload.sub_cause,
        "signal_dbm": payload.signal_dbm,
        "observations": payload.observations,
        "checklist": payload.checklist or {},
        "ai_suggestion_id": payload.ai_suggestion_id,
        "escalated_by": user.get("email"),
        "escalated_by_id": user.get("id"),
        "escalated_at": now,
        "status": "pendente",
        "assigned_to_id": None,
        "assigned_at": None,
        "resolved_at": None,
        "resolution_text": None,
        "resolution_outcome": None,
        "returned_to_field": False,
    }
    await db.rede_escalations.insert_one(esc_doc)

    # Atualiza ticket: aponta para a coluna virtual REDE, mas mantém o
    # técnico original em `field_origin_collaborator_id` para o KPI de retorno
    await db.tickets.update_one(
        {"id": ticket_id, "company_id": company_id},
        {"$set": {
            "assigned_collaborator_id": rede_id,
            "assigned_to": rede_id,
            "rede_escalation_id": esc_id,
            "rede_escalated_at": now,
            "field_origin_collaborator_id": prior_collab,
        }})

    # Log no ticket_logs
    await db.ticket_logs.insert_one({
        "id": f"tlg-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "ticket_id": ticket_id,
        "action": "rede_escalate",
        "actor_email": user.get("email"),
        "actor_id": user.get("id"),
        "at": now,
        "meta": {
            "escalation_id": esc_id,
            "cause": payload.cause,
            "signal_dbm": payload.signal_dbm,
            "from_collab": prior_collab,
        },
    })

    # Marca a sugestão IA como "escalada"
    if payload.ai_suggestion_id:
        await db.rede_ai_suggestions.update_one(
            {"id": payload.ai_suggestion_id, "company_id": company_id},
            {"$set": {"outcome": "escalated",
                      "outcome_at": now,
                      "outcome_escalation_id": esc_id}})

    return {"ok": True, "escalation_id": esc_id, "to_collaborator_id": rede_id}


# ═════════════════════════════════════════════════════════════════════════
# ENDPOINT — IA evitou escalonamento (técnico decidiu resolver)
# ═════════════════════════════════════════════════════════════════════════

class AIAvoidedRequest(BaseModel):
    ai_suggestion_id: str
    chosen_action: Optional[str] = Field(None, max_length=160)
    notes: Optional[str] = Field(None, max_length=400)


@router.post("/tickets/{ticket_id}/rede/ai-avoided")
async def rede_ai_avoided(ticket_id: str, payload: AIAvoidedRequest,
                            user: dict = Depends(get_current_user)):
    """Técnico viu sugestão da IA, resolveu sem escalar — registra o ganho."""
    company_id = user.get("company_id")
    sug = await db.rede_ai_suggestions.find_one({
        "id": payload.ai_suggestion_id,
        "company_id": company_id,
        "ticket_id": ticket_id,
    })
    if not sug:
        raise HTTPException(404, "Sugestão IA não encontrada")
    now = _now_iso()
    await db.rede_ai_suggestions.update_one(
        {"id": payload.ai_suggestion_id, "company_id": company_id},
        {"$set": {"outcome": "avoided_escalation",
                  "outcome_at": now,
                  "outcome_chosen_action": payload.chosen_action,
                  "outcome_notes": payload.notes}})
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════════
# ENDPOINT — Gestor REDE atribui escalonamento para técnico específico
# ═════════════════════════════════════════════════════════════════════════

class AssignRedeRequest(BaseModel):
    escalation_id: str
    collaborator_id: str


@router.post("/rede/assign")
async def rede_assign(payload: AssignRedeRequest,
                       user: dict = Depends(get_current_user)):
    company_id = user.get("company_id")
    esc = await db.rede_escalations.find_one(
        {"id": payload.escalation_id, "company_id": company_id})
    if not esc:
        raise HTTPException(404, "Escalation não encontrada")
    collab = await db.collaborators.find_one(
        {"id": payload.collaborator_id, "company_id": company_id})
    if not collab:
        raise HTTPException(404, "Colaborador não encontrado")
    now = _now_iso()
    await db.rede_escalations.update_one(
        {"id": payload.escalation_id, "company_id": company_id},
        {"$set": {"assigned_to_id": payload.collaborator_id,
                  "assigned_at": now,
                  "status": "em_atendimento"}})
    await db.tickets.update_one(
        {"id": esc["ticket_id"], "company_id": company_id},
        {"$set": {"assigned_collaborator_id": payload.collaborator_id,
                  "assigned_to": payload.collaborator_id}})
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════════
# ENDPOINT — Watchtower KPIs da Célula REDE
# ═════════════════════════════════════════════════════════════════════════

@watch_router.get("/rede/kpis")
async def watchtower_rede_kpis(
    days: int = Query(30, ge=1, le=180),
    user: dict = Depends(get_current_user),
):
    cid = user.get("company_id")
    cutoff = (_now() - timedelta(days=days)).isoformat()

    # ── 1. Status atual da fila ──────────────────────────────────────
    aguardando = await db.rede_escalations.count_documents(
        {"company_id": cid, "status": "pendente"})
    em_atend = await db.rede_escalations.count_documents(
        {"company_id": cid, "status": "em_atendimento"})

    # ── 2. Totais no período ─────────────────────────────────────────
    total_period = await db.rede_escalations.count_documents(
        {"company_id": cid, "escalated_at": {"$gte": cutoff}})
    total_resolvidos = await db.rede_escalations.count_documents(
        {"company_id": cid, "status": "resolvido",
         "escalated_at": {"$gte": cutoff}})
    total_devolvidos = await db.rede_escalations.count_documents(
        {"company_id": cid, "returned_to_field": True,
         "escalated_at": {"$gte": cutoff}})

    # ── 3. Total de OS de campo elegíveis (denominador da Taxa) ─────
    elig_q = {"company_id": cid,
               "type": {"$in": ["reparo", "instalacao", "rompimento"]},
               "created_at": {"$gte": cutoff}}
    total_eligible = await db.tickets.count_documents(elig_q)
    taxa_escalacao = round(
        total_period / total_eligible * 100, 1) if total_eligible else 0.0

    # ── 4. MTTR REDE (tempo de escalated_at até resolved_at) ─────────
    mttr_pipe = [
        {"$match": {"company_id": cid, "status": "resolvido",
                     "escalated_at": {"$gte": cutoff},
                     "resolved_at": {"$ne": None}}},
        {"$project": {"dur_min": {
            "$divide": [
                {"$subtract": [
                    {"$dateFromString": {"dateString": "$resolved_at"}},
                    {"$dateFromString": {"dateString": "$escalated_at"}},
                ]},
                60000,
            ]}}},
        {"$group": {"_id": None, "avg": {"$avg": "$dur_min"}}},
    ]
    mttr_min = 0.0
    async for d in db.rede_escalations.aggregate(mttr_pipe):
        mttr_min = round(d.get("avg") or 0.0, 1)

    # ── 5. Tempo médio em fila (escalated → assigned) ────────────────
    fila_pipe = [
        {"$match": {"company_id": cid,
                     "escalated_at": {"$gte": cutoff},
                     "assigned_at": {"$ne": None}}},
        {"$project": {"dur_min": {
            "$divide": [
                {"$subtract": [
                    {"$dateFromString": {"dateString": "$assigned_at"}},
                    {"$dateFromString": {"dateString": "$escalated_at"}},
                ]},
                60000,
            ]}}},
        {"$group": {"_id": None, "avg": {"$avg": "$dur_min"}}},
    ]
    fila_min = 0.0
    async for d in db.rede_escalations.aggregate(fila_pipe):
        fila_min = round(d.get("avg") or 0.0, 1)

    # ── 6. FTFR REDE (resolvidos sem retorno ao campo) ───────────────
    ftfr_resolvidos = total_resolvidos - total_devolvidos
    ftfr_pct = round(ftfr_resolvidos / total_resolvidos * 100, 1) \
        if total_resolvidos else 0.0

    # ── 7. Reopen / retorno ao campo ─────────────────────────────────
    reopen_pct = round(total_devolvidos / total_period * 100, 1) \
        if total_period else 0.0

    # ── 8. Top 5 causas ──────────────────────────────────────────────
    top_causes_pipe = [
        {"$match": {"company_id": cid,
                     "escalated_at": {"$gte": cutoff}}},
        {"$group": {"_id": "$cause", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": 5},
    ]
    top_causes: List[Dict[str, Any]] = []
    async for d in db.rede_escalations.aggregate(top_causes_pipe):
        top_causes.append({"cause": d["_id"] or "(sem causa)",
                            "count": d["n"]})

    # ── 9. Escalações Evitadas pela IA ───────────────────────────────
    avoided = await db.rede_ai_suggestions.count_documents({
        "company_id": cid, "outcome": "avoided_escalation",
        "outcome_at": {"$gte": cutoff},
    })
    total_sug = await db.rede_ai_suggestions.count_documents({
        "company_id": cid, "created_at": {"$gte": cutoff},
    })
    # Horas economizadas: assume MTTR REDE atual como referência por
    # escalação evitada (cada uma "valeria" um MTTR REDE de trabalho).
    avoided_hours = round(avoided * (mttr_min or 60) / 60, 1)

    return {
        "company_id": cid,
        "window_days": days,
        "now": _now_iso(),
        "queue": {
            "aguardando": aguardando,
            "em_atendimento": em_atend,
            "total_ativo": aguardando + em_atend,
        },
        "throughput": {
            "total_escaladas_periodo": total_period,
            "total_eligible_periodo": total_eligible,
            "taxa_escalacao_pct": taxa_escalacao,
            "total_resolvidos": total_resolvidos,
            "total_devolvidos_campo": total_devolvidos,
        },
        "sla": {
            "mttr_minutes": mttr_min,
            "tempo_medio_fila_minutes": fila_min,
            "ftfr_pct": ftfr_pct,
            "reopen_pct": reopen_pct,
        },
        "top_causes": top_causes,
        "ai_value": {
            "escalations_avoided": avoided,
            "total_ai_suggestions": total_sug,
            "avoid_rate_pct": round(avoided / max(total_sug, 1) * 100, 1),
            "hours_saved_estimate": avoided_hours,
            "model_default": "claude-sonnet-4-5-20250929",
        },
    }


@watch_router.get("/rede/queue")
async def watchtower_rede_queue(user: dict = Depends(get_current_user)):
    """Lista de escalonamentos pendentes/em atendimento para o gestor da REDE."""
    cid = user.get("company_id")
    items: List[Dict[str, Any]] = []
    async for d in db.rede_escalations.find(
            {"company_id": cid,
             "status": {"$in": ["pendente", "em_atendimento"]}},
            {"_id": 0}).sort("escalated_at", 1).limit(200):
        items.append(d)
    return {"items": items, "count": len(items)}
