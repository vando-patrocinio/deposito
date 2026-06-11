"""Coaching automático de técnicos via WhatsApp.

Quando um técnico fecha N bolhas seguidas SEM teste de ping (`ping_summary`
ausente ou "NÃO FOI REALIZADO"), dispara uma mensagem coaching no número do
gestor configurado em `aihub_settings.lousa_coaching_alerts`.

Cooldown: não alerta de novo o mesmo técnico nas próximas 2h (anti-spam).

Plug-in barato:
    from services.lousa_coaching import check_ping_skip_streak
    await check_ping_skip_streak(company_id, collaborator_id, ticket_id)
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

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from database import db

logger = logging.getLogger("ponto.lousa_coaching")

_COACHING_KEY = "lousa_coaching_alerts"
_DEFAULT_THRESHOLD = 3
_COOLDOWN_HOURS = 2


def _has_ping(summary: Optional[str]) -> bool:
    s = (summary or "").strip()
    if not s:
        return False
    return "NÃO FOI REALIZADO" not in s.upper()


async def get_coaching_config(company_id: str) -> dict:
    doc = await db.aihub_settings.find_one(
        {"company_id": company_id, "key": _COACHING_KEY},
        {"_id": 0},
    )
    return {
        "enabled": bool((doc or {}).get("enabled", False)),
        "manager_phone": (doc or {}).get("manager_phone") or "",
        "threshold": int((doc or {}).get("threshold") or _DEFAULT_THRESHOLD),
    }


async def save_coaching_config(company_id: str, enabled: bool,
                                  manager_phone: str, threshold: int) -> dict:
    threshold = max(2, min(threshold, 10))
    phone = re.sub(r"[^\d+]", "", manager_phone or "")
    await db.aihub_settings.update_one(
        {"company_id": company_id, "key": _COACHING_KEY},
        {"$set": {
            "enabled": bool(enabled),
            "manager_phone": phone,
            "threshold": threshold,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return await get_coaching_config(company_id)


async def check_ping_skip_streak(company_id: str, collaborator_id: str,
                                    last_ticket_id: str) -> Optional[dict]:
    """Verifica se o técnico fechou N bolhas seguidas sem ping. Se sim, envia
    alerta WhatsApp pro gestor. Retorna o doc do alerta enviado ou None.

    Roda sempre depois do `tickets.update_one(...status=finalizada)`.
    """
    cfg = await get_coaching_config(company_id)
    if not cfg["enabled"] or not cfg["manager_phone"]:
        return None
    threshold = cfg["threshold"]

    # Pega as últimas `threshold` bolhas finalizadas desse técnico, mais recentes primeiro.
    recent = await db.tickets.find(
        {"assigned_collaborator_id": collaborator_id,
         "status": "finalizada"},
        {"_id": 0, "id": 1, "closed_at": 1,
         "completion_data.ping_summary": 1,
         "client_snapshot": 1},
    ).sort("closed_at", -1).limit(threshold).to_list(threshold)

    if len(recent) < threshold:
        return None
    # Todas precisam estar sem ping
    if any(_has_ping((t.get("completion_data") or {}).get("ping_summary"))
            for t in recent):
        return None

    # Cooldown: não alerta de novo se já alertamos esse técnico há < 2h
    cooldown_since = (datetime.now(timezone.utc)
                       - timedelta(hours=_COOLDOWN_HOURS)).isoformat()
    last_alert = await db.lousa_coaching_alerts.find_one(
        {"company_id": company_id,
         "collaborator_id": collaborator_id,
         "created_at": {"$gte": cooldown_since}},
        {"_id": 0, "id": 1},
    )
    if last_alert:
        logger.info("[coaching] cooldown ativo collab=%s", collaborator_id)
        return None

    coll = await db.collaborators.find_one(
        {"id": collaborator_id}, {"_id": 0, "name": 1, "nickname": 1},
    ) or {}
    tech_name = coll.get("nickname") or coll.get("name") or "Técnico"

    # Lista os clientes das 3 bolhas pra dar contexto
    client_lines = []
    for i, t in enumerate(recent, 1):
        cli = (t.get("client_snapshot") or {}).get("name") or "—"
        client_lines.append(f"{i}. {cli}")
    clients_blob = "\n".join(client_lines)

    text = (
        f"🚨 *Coaching automático — Isabella*\n\n"
        f"@{tech_name} você fechou *{threshold} bolhas seguidas* sem realizar "
        f"o teste de ping na ONU.\n\n"
        f"📋 Bolhas envolvidas:\n{clients_blob}\n\n"
        f"👉 Na próxima visita, me manda o resultado do ping antes de fechar — "
        f"ou abre um chamado de qualidade explicando porque pulou.\n\n"
        f"_Mensagem gerada automaticamente após fechamento sem ping._"
    )

    # Envia via Baileys sidecar (silencioso — não derruba o fechamento)
    sent_ok = False
    sent_error = None
    try:
        from services.wa.sidecar import _sidecar_post_silent
        resp = await _sidecar_post_silent(
            "/send", {"phone": cfg["manager_phone"], "text": text},
        )
        sent_ok = bool(resp and resp.get("ok"))
        if not sent_ok:
            sent_error = (resp or {}).get("error") or "sidecar respondeu negativo"
    except Exception as e:
        sent_error = str(e)
        logger.warning("[coaching] envio falhou: %s", e)

    alert_id = f"coach-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{collaborator_id[:6]}"
    doc = {
        "id": alert_id,
        "company_id": company_id,
        "collaborator_id": collaborator_id,
        "collaborator_name": tech_name,
        "manager_phone": cfg["manager_phone"],
        "threshold": threshold,
        "ticket_ids": [t.get("id") for t in recent],
        "last_ticket_id": last_ticket_id,
        "text": text,
        "delivery_status": "sent" if sent_ok else "failed",
        "delivery_error": sent_error,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await db.lousa_coaching_alerts.insert_one(dict(doc))
        doc.pop("_id", None)
    except Exception as e:
        logger.warning("[coaching] persist alert falhou: %s", e)

    logger.info(
        "[coaching] alerta enviado collab=%s status=%s",
        collaborator_id, doc["delivery_status"],
    )
    return doc
