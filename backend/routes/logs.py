"""Endpoint /api/logs — visão consolidada de eventos do sistema (gestor/auditor).

Agrega múltiplas collections em uma timeline unificada:
- login_attempts (tentativas de login senha)
- impersonation_log (auditor logando como gestor)
- system_alerts (falhas de IA/holidays/etc)
- collaborator_sessions (logins Google de colaboradores)
- push_alerts_log (alertas de campo enviados via push)
- clock_records.audit (edições manuais, criação manual, aprovações)
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends

from core import DEMO_COMPANY_ID, is_super_admin, require_role, tenant_filter
from database import db

router = APIRouter(prefix="/api/logs", tags=["logs"])


def _to_iso(v: Any) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v) if v is not None else ""


@router.get("")
async def list_logs(
    days: int = 7,
    types: Optional[str] = None,
    limit: int = 300,
    user: dict = Depends(require_role("gestor", "auditor")),
):
    """Retorna timeline consolidada nos últimos `days`.
    `types` é CSV opcional; se vazio, devolve todos os tipos.
    """
    days = max(1, min(int(days), 90))
    limit = max(10, min(int(limit), 1000))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.isoformat()
    type_set = {t.strip() for t in (types or "").split(",") if t.strip()}

    super_view = is_super_admin(user)
    cid = user.get("company_id") or DEMO_COMPANY_ID

    # Pré-computa colaboradores do tenant para escopar logs derivados
    coll_ids: dict[str, str] = {}
    coll_q = {} if super_view else {"company_id": cid}
    async for c in db.collaborators.find(coll_q, {"_id": 0, "id": 1, "name": 1}):
        coll_ids[c["id"]] = c.get("name", c["id"])

    out: list[dict] = []

    # 1. login_attempts
    if not type_set or "login" in type_set:
        async for d in db.login_attempts.find(
            {"$or": [{"at": {"$gte": since_iso}}, {"at": {"$gte": since}}]},
            {"_id": 0},
        ).sort("at", -1).limit(limit):
            out.append({
                "type": "login",
                "at": _to_iso(d.get("at")),
                "actor": d.get("email", ""),
                "title": "Login " + ("✅ sucesso" if d.get("success") else "❌ falha"),
                "detail": f"E-mail: {d.get('email','')}",
                "level": "info" if d.get("success") else "warning",
                "raw": d,
            })

    # 2. impersonation_log
    if not type_set or "impersonation" in type_set:
        async for d in db.impersonation_log.find(
            {"at": {"$gte": since_iso}}, {"_id": 0},
        ).sort("at", -1).limit(limit):
            verb = "iniciou" if d.get("action") == "start" else "encerrou"
            out.append({
                "type": "impersonation",
                "at": d.get("at", ""),
                "actor": d.get("auditor_email", ""),
                "title": f"Auditor {verb} impersonation",
                "detail": f"como {d.get('target_email','?')} ({d.get('target_role','?')})",
                "level": "warning",
                "raw": d,
            })

    # 3. system_alerts
    if not type_set or "system" in type_set:
        async for d in db.system_alerts.find(
            {"at": {"$gte": since_iso}}, {"_id": 0},
        ).sort("at", -1).limit(limit):
            out.append({
                "type": "system",
                "at": d.get("at", ""),
                "actor": "Sistema",
                "title": d.get("type", "Alerta de sistema"),
                "detail": d.get("message", ""),
                "level": d.get("severity", "warning"),
                "raw": d,
            })

    # 4. collaborator_sessions (logins Google de colaboradores)
    if not type_set or "collab_login" in type_set:
        sess_q: dict = {"created_at": {"$gte": since_iso}}
        if not super_view:
            sess_q["collaborator_id"] = {"$in": list(coll_ids.keys())}
        async for d in db.collaborator_sessions.find(
            sess_q, {"_id": 0},
        ).sort("created_at", -1).limit(limit):
            ua = d.get("user_agent", "")
            short_ua = ua[:80] + ("..." if len(ua) > 80 else "")
            out.append({
                "type": "collab_login",
                "at": d.get("created_at", ""),
                "actor": d.get("google_email", ""),
                "title": "Login Google do colaborador",
                "detail": f"Device: {d.get('device_id','?')[:18]}... · {short_ua}",
                "level": "info",
                "raw": {**d, "user_agent": short_ua},
            })

    # 5. push_alerts_log
    if not type_set or "push" in type_set:
        async for d in db.push_alerts_log.find(
            {"sent_at": {"$gte": since_iso}}, {"_id": 0},
        ).sort("sent_at", -1).limit(limit):
            res = d.get("result", {})
            out.append({
                "type": "push",
                "at": d.get("sent_at", ""),
                "actor": "Sistema",
                "title": "Notificação push enviada",
                "detail": f"{d.get('title','?')} · entregues: {res.get('sent',0)} · falhas: {res.get('failed',0)}",
                "level": d.get("level", "warning"),
                "raw": d,
            })

    # 6. clock_records — edições manuais e ações relevantes (a partir do array audit)
    if not type_set or "clock" in type_set:
        clock_q: dict = {
            "$or": [
                {"manually_edited": True},
                {"created_at": {"$gte": since_iso}},
            ]
        }
        if not super_view:
            clock_q["collaborator_id"] = {"$in": list(coll_ids.keys())}
        async for r in db.clock_records.find(
            clock_q,
            {"_id": 0, "selfie_url": 0, "face_validation": 0},
        ).sort("created_at", -1).limit(limit * 2):
            audit = r.get("audit", []) or []
            cname = coll_ids.get(r.get("collaborator_id", ""), r.get("collaborator_id", ""))
            for entry in audit:
                at = entry.get("at")
                if not at or at < since_iso:
                    continue
                action = entry.get("action", "")
                if not any(k in action.lower() for k in ("manual", "aprov", "recus", "edição", "remov")):
                    continue
                out.append({
                    "type": "clock",
                    "at": at,
                    "actor": entry.get("actor", "—"),
                    "title": f"{action} · {r.get('type','')}",
                    "detail": (f"{cname} · {r.get('date','')} {r.get('time','')}" +
                               (f" · {entry.get('reason','')}" if entry.get("reason") else "")),
                    "level": "warning" if "remov" in action.lower() else "info",
                    "raw": {"record_id": r.get("id"), **entry},
                })

    out.sort(key=lambda x: x.get("at") or "", reverse=True)
    out = out[:limit]

    counts: dict[str, int] = {}
    for it in out:
        counts[it["type"]] = counts.get(it["type"], 0) + 1

    return {
        "days": days,
        "limit": limit,
        "total": len(out),
        "by_type": counts,
        "items": out,
    }
