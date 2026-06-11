"""Lousa AI · Triagem — IA que classifica tickets novos com Claude.

Quando um ticket entra na Lousa (manual, via Atlaz, via WhatsApp), Claude
analisa em <2s e preenche/sugere:

- type           — reparo / instalacao / retirada / prioridade / preventiva / venda
- priority       — normal / horario / prioridade
- suggested_column   — nome da coluna ideal (se workflow customizado)
- suggested_collaborator_id  — técnico ideal baseado em proximidade + carga
- sla_estimate_minutes  — SLA estimado em minutos
- tags           — ["VIP", "Recorrente", "Em pane", "Sem internet há 2h", ...]
- risk_score     — 0-100 (chance de virar reclamação/cancelamento)
- triage_summary — 1 parágrafo justificando

Salvo em `ticket.ai_triage` (subdoc). Usuário pode reverter com 1 clique
(`ai_triage.reverted=true`), o que vira sinal de aprendizado.

Worker autônomo: roda a cada 60s e tria tickets `ai_triage_pending=true`
(criados mas ainda não triados). Modo manual: POST /api/lousa-ai/triage/{ticket_id}.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "operacoes",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["ticket.updated"],
    "company_id_required": True,
}

import asyncio
import json as _json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core import DEMO_COMPANY_ID, now_iso
from database import db

logger = logging.getLogger("lousa_ai_triagem")

INTERVAL_SECONDS = 60
ACTIVE_TYPES = ("reparo", "instalacao", "retirada", "prioridade", "preventiva", "venda")
PRIORITIES = ("normal", "horario", "prioridade")


async def _candidate_technicians(company_id: str, max_n: int = 20) -> List[Dict[str, Any]]:
    """Lista técnicos ativos + carga atual de tickets ativos. Usado pra sugestão."""
    techs: List[Dict[str, Any]] = []
    async for c in db.collaborators.find(
        {"company_id": company_id, "active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1, "neighborhoods": 1, "skills": 1},
    ).limit(max_n):
        active_count = await db.tickets.count_documents({
            "company_id": company_id,
            "assigned_collaborator_id": c["id"],
            "status": {"$nin": ["finalizada", "cancelada", "encerrada", "reagendada"]},
        })
        techs.append({
            "id": c["id"],
            "name": c.get("name") or c["id"],
            "neighborhoods": c.get("neighborhoods") or [],
            "skills": c.get("skills") or [],
            "active_tickets": active_count,
        })
    techs.sort(key=lambda t: t["active_tickets"])
    return techs


async def _client_recurrence(company_id: str, phone: Optional[str]) -> Dict[str, Any]:
    """Quantos tickets esse cliente tem nos últimos 30/90 dias."""
    out = {"last_30d": 0, "last_90d": 0, "is_vip": False}
    if not phone:
        return out
    now = datetime.now(timezone.utc)
    cutoff_30 = (now - timedelta(days=30)).isoformat()
    cutoff_90 = (now - timedelta(days=90)).isoformat()
    out["last_30d"] = await db.tickets.count_documents({
        "company_id": company_id, "phone": phone,
        "created_at": {"$gte": cutoff_30},
    })
    out["last_90d"] = await db.tickets.count_documents({
        "company_id": company_id, "phone": phone,
        "created_at": {"$gte": cutoff_90},
    })
    # VIP: subscriber com flag vip ou plano premium
    sub = await db.subscribers.find_one(
        {"company_id": company_id, "phones.number": phone},
        {"_id": 0, "vip": 1, "plan_name": 1},
    )
    if sub:
        plan = (sub.get("plan_name") or "").lower()
        out["is_vip"] = bool(sub.get("vip")) or "premium" in plan or "vip" in plan
    return out


async def _active_outage_for(company_id: str, neighborhood: Optional[str],
                                phone: Optional[str]) -> Optional[Dict[str, Any]]:
    """Verifica se há outage ativo afetando esse bairro/telefone."""
    if phone:
        o = await db.network_outages.find_one(
            {"company_id": company_id, "status": "active",
             "affected_phones": phone},
            {"_id": 0, "olt_name": 1, "board": 1, "port": 1, "severity_pct": 1},
        )
        if o:
            return o
    return None


def _strip_json(raw: str) -> Optional[Dict[str, Any]]:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").lstrip("json").strip()
    if "{" in raw and "}" in raw:
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
    try:
        return _json.loads(raw)
    except Exception:
        return None


def _coerce_type(v: Any) -> str:
    s = str(v or "").lower().strip()
    return s if s in ACTIVE_TYPES else "reparo"


def _coerce_priority(v: Any) -> str:
    s = str(v or "").lower().strip()
    return s if s in PRIORITIES else "normal"


def _coerce_int(v: Any, default: int, lo: int, hi: int) -> int:
    try:
        n = int(float(v))
        return max(lo, min(hi, n))
    except Exception:
        return default


async def triage_ticket(company_id: str, ticket_id: str,
                          force: bool = False) -> Dict[str, Any]:
    """Tria um ticket específico. Retorna a triagem salva ou dict de erro."""
    t = await db.tickets.find_one({"id": ticket_id, "company_id": company_id},
                                     {"_id": 0})
    if not t:
        return {"ok": False, "error": "ticket não encontrado"}
    if t.get("ai_triage") and not force:
        return {"ok": True, "already": True, "triage": t["ai_triage"]}

    techs = await _candidate_technicians(company_id)
    recurrence = await _client_recurrence(company_id, t.get("phone"))
    outage = await _active_outage_for(company_id, t.get("neighborhood"), t.get("phone"))

    hr_brt = (datetime.now(timezone.utc) - timedelta(hours=3)).hour
    period = ("madrugada" if hr_brt < 6 else "manhã" if hr_brt < 12
              else "tarde" if hr_brt < 18 else "noite")

    techs_list = "\n".join(
        f"- {tt['name']} (id={tt['id']}) · {tt['active_tickets']} tickets ativos · "
        f"bairros={','.join(tt['neighborhoods'][:3]) or '—'}"
        for tt in techs[:10]
    ) or "— (sem técnicos ativos)"

    user_msg = (
        "TICKET NOVO PRA TRIAGEM:\n"
        f"- Cliente: {t.get('client_name')}\n"
        f"- Telefone: {t.get('phone') or '—'}\n"
        f"- Endereço: {t.get('address') or '—'}\n"
        f"- Bairro: {t.get('neighborhood') or '—'}\n"
        f"- Relato/descrição: {(t.get('relato') or t.get('description') or '')[:600]}\n"
        f"- Tipo inicial (placeholder): {t.get('type')}\n"
        f"- Prioridade inicial (placeholder): {t.get('priority')}\n"
        f"- Agendamento: {t.get('scheduled_time') or '—'}\n"
        f"- Horário atual: {period} (BRT ~{hr_brt}h)\n"
        f"- Recorrência: {recurrence['last_30d']} tickets/30d · "
        f"{recurrence['last_90d']}/90d · "
        f"{'VIP' if recurrence['is_vip'] else 'comum'}\n"
        f"- Pane ativa na região: "
        f"{'SIM ' + str(outage) if outage else 'NÃO'}\n\n"
        f"TÉCNICOS DISPONÍVEIS:\n{techs_list}\n\n"
        "Responda APENAS em JSON, sem markdown, sem texto extra:\n"
        "{\n"
        '  "type": "reparo" | "instalacao" | "retirada" | "prioridade" | "preventiva" | "venda",\n'
        '  "priority": "normal" | "horario" | "prioridade",\n'
        '  "suggested_collaborator_id": "id de algum técnico da lista, ou null",\n'
        '  "sla_estimate_minutes": <int 30-1440>,\n'
        '  "tags": ["até 5 tags curtas em PT-BR"],\n'
        '  "risk_score": <int 0-100>,\n'
        '  "triage_summary": "1 parágrafo curto justificando todas as decisões, max 280 chars"\n'
        "}"
    )

    sys_msg = (
        "Você é o agente de TRIAGEM da Lousa de tickets de um provedor de internet "
        "(ISP). Para cada ticket novo, decida: tipo, prioridade, técnico ideal, "
        "SLA, tags e risk_score (chance de reclamação/cancelamento). Use TUDO no "
        "contexto: relato, horário, recorrência, pane ativa, carga dos técnicos, "
        "proximidade geográfica (bairros que o técnico atende vs bairro do "
        "ticket). Se houver pane na região, sinalize tag 'Pane em curso'. Se for "
        "VIP, suba a prioridade e o risk_score. Se for cancelamento, risk_score "
        "alto. Resposta APENAS o JSON pedido."
    )

    try:
        from services.motor_ia import chat_completion
        result = await chat_completion(
            company_id,
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg},
            ],
            model="anthropic/claude-sonnet-4.5",
            temperature=0.2,
            max_tokens=420,
            json_mode=False,
            purpose="lousa_triagem",
            agent="lousa_triagem",
        )
        parsed = _strip_json(result.get("content") or "")
        if not parsed:
            return {"ok": False, "error": "LLM não retornou JSON válido"}
    except Exception as e:
        logger.exception("[lousa-ai] triage falhou ticket %s: %s", ticket_id, e)
        return {"ok": False, "error": str(e)}

    # Sanitiza e monta triagem
    valid_tech_ids = {tt["id"] for tt in techs}
    suggested_tech = parsed.get("suggested_collaborator_id")
    if suggested_tech and suggested_tech not in valid_tech_ids:
        suggested_tech = None
    tags_raw = parsed.get("tags") or []
    if isinstance(tags_raw, str):
        tags_raw = [tags_raw]
    tags = [str(x)[:32] for x in tags_raw[:5] if x]

    triage = {
        "type": _coerce_type(parsed.get("type")),
        "priority": _coerce_priority(parsed.get("priority")),
        "suggested_collaborator_id": suggested_tech,
        "sla_estimate_minutes": _coerce_int(parsed.get("sla_estimate_minutes"),
                                                default=240, lo=30, hi=1440),
        "tags": tags,
        "risk_score": _coerce_int(parsed.get("risk_score"),
                                     default=20, lo=0, hi=100),
        "triage_summary": str(parsed.get("triage_summary") or "")[:400],
        "model": result.get("model"),
        "generated_at": now_iso(),
        "reverted": False,
    }

    await db.tickets.update_one(
        {"id": ticket_id, "company_id": company_id},
        {"$set": {
            "ai_triage": triage,
            "ai_triage_pending": False,
            # Aplica type+priority direto (não-destrutivo: só se o ticket
            # estava com defaults). User pode reverter no card.
            "type": triage["type"] if t.get("type") in (None, "reparo") else t.get("type"),
            "priority": triage["priority"] if t.get("priority") in (None, "normal") else t.get("priority"),
        }},
    )
    logger.info("[lousa-ai] triagem aplicada ticket=%s type=%s priority=%s risk=%s",
                 ticket_id, triage["type"], triage["priority"], triage["risk_score"])
    return {"ok": True, "triage": triage}


async def revert_triage(company_id: str, ticket_id: str,
                          user_email: str) -> Dict[str, Any]:
    """Marca a triagem como revertida pelo humano (sinal de aprendizado)."""
    res = await db.tickets.update_one(
        {"id": ticket_id, "company_id": company_id,
         "ai_triage": {"$exists": True}},
        {"$set": {
            "ai_triage.reverted": True,
            "ai_triage.reverted_at": now_iso(),
            "ai_triage.reverted_by": user_email,
        }},
    )
    try:
        from services.event_bus import emit_event
        await emit_event(
            "ticket.updated",
            company_id=company_id,
            source="lousa_ai_triagem",
            payload={},
        )
    except Exception:
        pass
    if res.matched_count == 0:
        return {"ok": False, "error": "Ticket não encontrado ou sem triagem"}
    return {"ok": True}


async def stats(company_id: str) -> Dict[str, Any]:
    cutoff_24 = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    triaged_24h = await db.tickets.count_documents({
        "company_id": company_id,
        "ai_triage.generated_at": {"$gte": cutoff_24},
    })
    reverted = await db.tickets.count_documents({
        "company_id": company_id,
        "ai_triage.reverted": True,
        "ai_triage.generated_at": {"$gte": cutoff_24},
    })
    pending = await db.tickets.count_documents({
        "company_id": company_id,
        "ai_triage_pending": True,
    })
    avg_risk = 0
    pipe = [
        {"$match": {"company_id": company_id,
                      "ai_triage.generated_at": {"$gte": cutoff_24}}},
        {"$group": {"_id": None, "avg": {"$avg": "$ai_triage.risk_score"}}},
    ]
    async for r in db.tickets.aggregate(pipe):
        avg_risk = round(r.get("avg") or 0, 1)
    accuracy = round((1 - (reverted / triaged_24h)) * 100, 1) if triaged_24h else None
    return {
        "triaged_24h": triaged_24h,
        "reverted_24h": reverted,
        "pending": pending,
        "avg_risk_score": avg_risk,
        "accuracy_pct": accuracy,
    }


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
_worker_task: Optional[asyncio.Task] = None


async def _worker_loop():
    while True:
        try:
            await _scan_pending(DEMO_COMPANY_ID)
        except Exception as e:
            logger.exception("[lousa-ai] worker err: %s", e)
        await asyncio.sleep(INTERVAL_SECONDS)


async def _scan_pending(company_id: str):
    pending = await db.tickets.find(
        {"company_id": company_id, "ai_triage_pending": True},
        {"_id": 0, "id": 1},
    ).limit(10).to_list(10)
    for t in pending:
        try:
            await triage_ticket(company_id, t["id"])
        except Exception as e:
            logger.info("[lousa-ai] scan pending err ticket=%s: %s", t["id"], e)


def start_worker():
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_worker_loop())
    logger.info("[lousa-ai] worker iniciado (intervalo=%ds)", INTERVAL_SECONDS)


def stop_worker():
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
