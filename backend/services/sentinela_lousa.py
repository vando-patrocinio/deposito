"""Sentinela Lousa AI — worker autônomo de monitoramento da Lousa (Kanban).

Roda a cada 120s e detecta 5 padrões de risco em tickets ativos:
1. **stuck** — Ticket parado há > N horas sem update (status != finalizada/encerrada)
2. **sla_warning** — SLA prestes a estourar (faltam ≤ 30 min)
3. **sla_breach** — SLA já estourou (overdue)
4. **technician_overload** — Técnico com ≥ N tickets ativos simultâneos
5. **recurring** — Mesmo cliente abrindo 2+ tickets em 24h (problema crônico)
6. **field_stuck** — Ticket "aberta" (em campo) há > N horas (técnico travado)

Cria/atualiza docs em `lousa_alerts` com dedup por (ticket_id, kind).
Resolve alerta automaticamente quando a condição deixa de existir.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from core import DEMO_COMPANY_ID, now_iso
from database import db

logger = logging.getLogger("sentinela_lousa")

INTERVAL_SECONDS = 120
STUCK_HOURS = 6                # ticket parado sem update há ≥ 6h
FIELD_STUCK_HOURS = 4          # ticket "em campo" há ≥ 4h
SLA_WARNING_MIN = 30           # alerta SLA quando faltam ≤ 30 min
OVERLOAD_TICKETS = 8           # técnico com ≥ 8 tickets ativos = sobrecarga
RECURRING_HOURS = 24           # janela pra detectar recorrência

ACTIVE_STATUSES = ("pendente", "aberta", "aguardando_atendimento",
                     "aguardando_cliente", "em_pausa")
CLOSED_STATUSES = ("finalizada", "cancelada", "encerrada", "reagendada")


def _iso_to_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _sev_for_kind(kind: str) -> str:
    return {
        "sla_breach": "high",
        "sla_warning": "medium",
        "stuck": "medium",
        "field_stuck": "high",
        "technician_overload": "medium",
        "recurring": "high",
    }.get(kind, "low")


async def _generate_ai_insight(company_id: str, alert_doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Claude analisa um alerta novo e gera priorização + recomendação acionável.

    Falha silenciosa — alerta funciona sem o insight. Retorna
    {priority, headline, recommendation, root_cause, model} ou None.
    """
    try:
        from services.motor_ia import chat_completion
    except ImportError:
        return None

    kind = alert_doc.get("kind", "")
    d = alert_doc.get("details") or {}
    # Coleta contexto extra do ticket se houver
    ticket_ctx = ""
    if alert_doc.get("ticket_id"):
        t = await db.tickets.find_one(
            {"id": alert_doc["ticket_id"]},
            {"_id": 0, "type": 1, "priority": 1, "neighborhood": 1, "address": 1,
             "description": 1, "client_name": 1, "scheduled_time": 1,
             "created_at": 1, "status": 1, "history": 1},
        )
        if t:
            hist = (t.get("history") or [])[-3:]
            hist_str = "; ".join(f"{h.get('event', '')}={h.get('to', '')}" for h in hist)
            ticket_ctx = (
                f"TICKET: tipo={t.get('type')} prio={t.get('priority')} "
                f"bairro={t.get('neighborhood')} status={t.get('status')}\n"
                f"DESC: {(t.get('description') or '')[:200]}\n"
                f"HISTÓRICO recente: {hist_str}"
            )
    # Histórico do mesmo cliente (últimos 30 dias)
    customer_ctx = ""
    if d.get("phone"):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        prev_count = await db.tickets.count_documents({
            "company_id": company_id,
            "phone": d["phone"],
            "created_at": {"$gte": cutoff},
        })
        if prev_count > 1:
            customer_ctx = f"\nCLIENTE tem {prev_count} tickets nos últimos 30 dias."

    hr_brt = (datetime.now(timezone.utc) - timedelta(hours=3)).hour
    period = ("madrugada" if hr_brt < 6 else "manhã" if hr_brt < 12
              else "tarde" if hr_brt < 18 else "noite")

    sys_msg = (
        "Você é um analista de operações de campo para provedor de internet (ISP) "
        "atuando sobre uma Lousa de tickets (Kanban). Analise alertas detectados "
        "pelo monitor automático e gere recomendação acionável em PT-BR. Considere: "
        "severidade do alerta, horário (madrugada × comercial), recorrência do cliente, "
        "carga do técnico, tipo de serviço (instalação × reparo × cancelamento). "
        "Resposta APENAS em JSON, sem markdown:\n"
        "{\n"
        '  "priority": "critica" | "alta" | "media" | "baixa",\n'
        '  "headline": "1 frase, máx 80 chars",\n'
        '  "recommendation": "1 parágrafo curto, máx 240 chars, ação concreta",\n'
        '  "root_cause": "hipótese de causa raiz, máx 120 chars, opcional"\n'
        "}"
    )
    user_msg = (
        f"ALERTA: {kind}\n"
        f"HEADLINE ORIGINAL: {alert_doc.get('headline')}\n"
        f"SEVERIDADE (regra): {alert_doc.get('severity')}\n"
        f"DETALHES: {d}\n"
        f"{ticket_ctx}"
        f"{customer_ctx}\n"
        f"HORÁRIO: {period} (BRT ~{hr_brt}h)\n\n"
        "Gere análise no JSON pedido."
    )

    try:
        result = await chat_completion(
            company_id,
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg},
            ],
            model="anthropic/claude-sonnet-4.5",
            temperature=0.3,
            max_tokens=300,
            json_mode=False,
            purpose="sentinela_insight",
            agent="sentinela_lousa",
        )
        import json as _json
        raw = (result.get("content") or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip("json").strip()
        if "{" in raw and "}" in raw:
            raw = raw[raw.index("{"):raw.rindex("}") + 1]
        parsed = _json.loads(raw)
        priority = str(parsed.get("priority") or "media").lower()
        if priority not in ("critica", "alta", "media", "baixa"):
            priority = "media"
        return {
            "priority": priority,
            "headline": (parsed.get("headline") or "")[:120],
            "recommendation": (parsed.get("recommendation") or "")[:400],
            "root_cause": (parsed.get("root_cause") or "")[:200],
            "model": result.get("model"),
            "generated_at": now_iso(),
        }
    except Exception as e:
        logger.info("[sentinela-lousa] LLM insight falhou (silencioso): %s", e)
        return None


async def _upsert_alert(company_id: str, kind: str,
                          ticket_id: Optional[str],
                          headline: str,
                          details: Dict[str, Any],
                          related_user_id: Optional[str] = None) -> str:
    """Insere/atualiza um alerta ativo com dedup por (kind, ticket_id, user)."""
    now = now_iso()
    key = {"company_id": company_id, "kind": kind, "status": "active"}
    if ticket_id:
        key["ticket_id"] = ticket_id
    if related_user_id:
        key["related_user_id"] = related_user_id

    existing = await db.lousa_alerts.find_one(key, {"_id": 0, "id": 1,
                                                       "occurrences": 1})
    if existing:
        await db.lousa_alerts.update_one(
            {"id": existing["id"]},
            {"$set": {
                "headline": headline,
                "details": details,
                "last_seen_at": now,
                "occurrences": (existing.get("occurrences") or 1) + 1,
            }},
        )
        return existing["id"]
    alert_id = f"sla-{uuid.uuid4().hex[:10]}"
    alert_doc = {
        "id": alert_id,
        "company_id": company_id,
        "kind": kind,
        "ticket_id": ticket_id,
        "related_user_id": related_user_id,
        "headline": headline,
        "details": details,
        "severity": _sev_for_kind(kind),
        "status": "active",
        "first_detected_at": now,
        "last_seen_at": now,
        "occurrences": 1,
    }
    # Claude analisa antes de salvar (priorização inteligente)
    try:
        insight = await _generate_ai_insight(company_id, alert_doc)
        if insight:
            alert_doc["ai_insight"] = insight
    except Exception:
        pass
    await db.lousa_alerts.insert_one(alert_doc)
    logger.info("[sentinela-lousa] novo alerta %s: %s%s", kind, headline,
                  f" · IA={alert_doc.get('ai_insight', {}).get('priority')}"
                  if alert_doc.get("ai_insight") else "")
    return alert_id


async def _auto_resolve_inactive(company_id: str,
                                    active_keys: Set[str]) -> int:
    """Resolve alertas que não foram tocados nesta varredura."""
    resolved = 0
    async for a in db.lousa_alerts.find(
        {"company_id": company_id, "status": "active"},
        {"_id": 0, "id": 1, "kind": 1, "ticket_id": 1,
         "related_user_id": 1},
    ):
        key = f"{a['kind']}|{a.get('ticket_id') or ''}|{a.get('related_user_id') or ''}"
        if key in active_keys:
            continue
        await db.lousa_alerts.update_one(
            {"id": a["id"]},
            {"$set": {"status": "resolved", "resolved_at": now_iso()}},
        )
        resolved += 1
    return resolved


async def _detect_sla(company_id: str) -> List[str]:
    """SLA warning + breach. Retorna chaves de alertas ativos."""
    keys: List[str] = []
    from routes.lousa import _compute_sla, _sla_minutes_for_type
    cursor = db.tickets.find(
        {"company_id": company_id, "status": {"$nin": list(CLOSED_STATUSES)}},
        {"_id": 0},
    )
    async for t in cursor:
        try:
            sla_min = await _sla_minutes_for_type(t.get("type") or "reparo", company_id)
            info = _compute_sla(t, sla_min)
        except Exception:
            continue
        status = info.get("status")
        remaining = info.get("remaining_minutes")
        if status == "overdue":
            await _upsert_alert(
                company_id, "sla_breach", t.get("id"),
                f"SLA ESTOURADO · {t.get('client_name', 'cliente')}",
                {
                    "client_name": t.get("client_name"),
                    "phone": t.get("phone"),
                    "type": t.get("type"),
                    "neighborhood": t.get("neighborhood"),
                    "status": t.get("status"),
                    "minutes_overdue": abs(remaining) if remaining is not None else None,
                    "assignee_id": t.get("assigned_collaborator_id"),
                },
            )
            keys.append(f"sla_breach|{t['id']}|")
        elif (remaining is not None and 0 < remaining <= SLA_WARNING_MIN
                and status in ("ok", "yellow", "red")):
            await _upsert_alert(
                company_id, "sla_warning", t.get("id"),
                f"SLA quase estourando · {int(remaining)}min restantes",
                {
                    "client_name": t.get("client_name"),
                    "type": t.get("type"),
                    "remaining_minutes": int(remaining),
                    "assignee_id": t.get("assigned_collaborator_id"),
                },
            )
            keys.append(f"sla_warning|{t['id']}|")
    return keys


async def _detect_stuck(company_id: str) -> List[str]:
    """Tickets parados há ≥ STUCK_HOURS sem updated_at."""
    keys: List[str] = []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=STUCK_HOURS)).isoformat()
    cursor = db.tickets.find(
        {"company_id": company_id, "status": {"$nin": list(CLOSED_STATUSES)},
         "$or": [{"updated_at": {"$lt": cutoff}},
                  {"updated_at": {"$exists": False}, "created_at": {"$lt": cutoff}}]},
        {"_id": 0, "id": 1, "client_name": 1, "created_at": 1,
         "updated_at": 1, "status": 1, "type": 1, "priority": 1,
         "assigned_collaborator_id": 1, "phone": 1},
    )
    async for t in cursor:
        ref = t.get("updated_at") or t.get("created_at")
        ref_dt = _iso_to_dt(ref) if ref else None
        hours = "?" if not ref_dt else int(
            (datetime.now(timezone.utc) - ref_dt).total_seconds() / 3600)
        await _upsert_alert(
            company_id, "stuck", t.get("id"),
            f"Ticket parado há {hours}h · {t.get('client_name', '')}",
            {
                "client_name": t.get("client_name"),
                "phone": t.get("phone"),
                "status": t.get("status"),
                "type": t.get("type"),
                "priority": t.get("priority"),
                "hours_idle": hours,
                "assignee_id": t.get("assigned_collaborator_id"),
            },
        )
        keys.append(f"stuck|{t['id']}|")
    return keys


async def _detect_field_stuck(company_id: str) -> List[str]:
    """Tickets em status 'aberta' (técnico em campo) há ≥ FIELD_STUCK_HOURS."""
    keys: List[str] = []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=FIELD_STUCK_HOURS)).isoformat()
    cursor = db.tickets.find(
        {"company_id": company_id, "status": "aberta",
         "opened_at": {"$lt": cutoff}},
        {"_id": 0, "id": 1, "client_name": 1, "opened_at": 1, "type": 1,
         "assigned_collaborator_id": 1, "phone": 1},
    )
    async for t in cursor:
        odt = _iso_to_dt(t.get("opened_at"))
        hours = "?" if not odt else int(
            (datetime.now(timezone.utc) - odt).total_seconds() / 3600)
        await _upsert_alert(
            company_id, "field_stuck", t.get("id"),
            f"Visita técnica travada há {hours}h",
            {
                "client_name": t.get("client_name"),
                "phone": t.get("phone"),
                "type": t.get("type"),
                "hours_in_field": hours,
                "assignee_id": t.get("assigned_collaborator_id"),
            },
        )
        keys.append(f"field_stuck|{t['id']}|")
    return keys


async def _detect_overload(company_id: str) -> List[str]:
    """Técnicos com ≥ OVERLOAD_TICKETS tickets ativos."""
    keys: List[str] = []
    pipe = [
        {"$match": {"company_id": company_id,
                      "status": {"$nin": list(CLOSED_STATUSES)},
                      "assigned_collaborator_id": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$assigned_collaborator_id", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gte": OVERLOAD_TICKETS}}},
    ]
    overload = []
    async for r in db.tickets.aggregate(pipe):
        overload.append({"user_id": r["_id"], "count": r["n"]})
    for ov in overload:
        u = await db.collaborators.find_one(
            {"id": ov["user_id"]}, {"_id": 0, "name": 1, "email": 1}
        ) or await db.users.find_one(
            {"id": ov["user_id"]}, {"_id": 0, "name": 1, "email": 1}
        ) or {}
        name = u.get("name") or u.get("email") or ov["user_id"]
        await _upsert_alert(
            company_id, "technician_overload", None,
            f"{name} com {ov['count']} tickets ativos",
            {"user_id": ov["user_id"], "name": name,
             "active_tickets": ov["count"]},
            related_user_id=ov["user_id"],
        )
        keys.append(f"technician_overload||{ov['user_id']}")
    return keys


async def _detect_recurring(company_id: str) -> List[str]:
    """Clientes (por phone) com 2+ tickets em RECURRING_HOURS — problema crônico."""
    keys: List[str] = []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=RECURRING_HOURS)).isoformat()
    pipe = [
        {"$match": {"company_id": company_id,
                      "phone": {"$nin": [None, ""]},
                      "created_at": {"$gte": cutoff}}},
        {"$group": {"_id": "$phone",
                      "count": {"$sum": 1},
                      "ticket_ids": {"$push": "$id"},
                      "client_names": {"$addToSet": "$client_name"}}},
        {"$match": {"count": {"$gte": 2}}},
    ]
    async for r in db.tickets.aggregate(pipe):
        phone = r["_id"]
        client = (r["client_names"] or [None])[0] or "cliente"
        for tid in r["ticket_ids"]:
            await _upsert_alert(
                company_id, "recurring", tid,
                f"{client} abriu {r['count']} tickets em {RECURRING_HOURS}h",
                {"phone": phone, "count": r["count"],
                 "client_name": client,
                 "related_tickets": r["ticket_ids"]},
            )
            keys.append(f"recurring|{tid}|")
    return keys


async def run_sentinel(company_id: str = DEMO_COMPANY_ID) -> Dict[str, Any]:
    """Executa uma varredura completa. Retorna sumário."""
    all_keys: Set[str] = set()
    for fn in (_detect_sla, _detect_stuck, _detect_field_stuck,
                  _detect_overload, _detect_recurring):
        try:
            ks = await fn(company_id)
            all_keys.update(ks)
        except Exception as e:
            logger.exception("[sentinela-lousa] %s falhou: %s", fn.__name__, e)
    resolved = await _auto_resolve_inactive(company_id, all_keys)
    return {
        "scanned_at": now_iso(),
        "active_alerts": len(all_keys),
        "auto_resolved": resolved,
    }


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------
_worker_task: Optional[asyncio.Task] = None


async def _worker_loop():
    while True:
        try:
            await run_sentinel(DEMO_COMPANY_ID)
        except Exception as e:
            logger.exception("[sentinela-lousa] worker err: %s", e)
        await asyncio.sleep(INTERVAL_SECONDS)


def start_worker():
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_worker_loop())
    logger.info("[sentinela-lousa] worker iniciado (intervalo=%ds)", INTERVAL_SECONDS)


def stop_worker():
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()


# ---------------------------------------------------------------------------
# Queries para UI
# ---------------------------------------------------------------------------
async def list_active_alerts(company_id: str,
                                severity: Optional[str] = None,
                                limit: int = 100) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"company_id": company_id, "status": "active"}
    if severity:
        q["severity"] = severity
    items = await db.lousa_alerts.find(q, {"_id": 0}) \
        .sort([("severity", -1), ("first_detected_at", -1)]) \
        .limit(limit).to_list(limit)
    return items


async def count_alerts_24h(company_id: str) -> Dict[str, int]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    active = await db.lousa_alerts.count_documents(
        {"company_id": company_id, "status": "active"})
    new_24h = await db.lousa_alerts.count_documents(
        {"company_id": company_id, "first_detected_at": {"$gte": cutoff}})
    resolved_24h = await db.lousa_alerts.count_documents(
        {"company_id": company_id, "status": "resolved",
         "resolved_at": {"$gte": cutoff}})
    by_kind_pipe = [
        {"$match": {"company_id": company_id, "status": "active"}},
        {"$group": {"_id": "$kind", "n": {"$sum": 1}}},
    ]
    by_kind: Dict[str, int] = {}
    async for r in db.lousa_alerts.aggregate(by_kind_pipe):
        by_kind[r["_id"]] = r["n"]
    return {
        "active": active, "new_24h": new_24h, "resolved_24h": resolved_24h,
        "by_kind": by_kind,
    }
