"""Web Push (VAPID) — geração de chaves, inscrições e envio.

Usa pywebpush + py_vapid. Chaves VAPID geradas no primeiro uso e persistidas
em Mongo (`settings` doc id="global", campos vapid_*). Inscrições gravadas em
`push_subscriptions` por usuário.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPushException, webpush

logger = logging.getLogger("push")

VAPID_CLAIM_SUB = os.environ.get("VAPID_CLAIM_SUB", "mailto:admin@ponto.local")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _generate_vapid_keys() -> dict[str, str]:
    """Gera par de chaves EC P-256 para VAPID e devolve em base64url + PEM."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    pub_numbers = private_key.public_key().public_numbers()
    pub_bytes = (
        b"\x04"
        + pub_numbers.x.to_bytes(32, "big")
        + pub_numbers.y.to_bytes(32, "big")
    )
    public_b64 = _b64url(pub_bytes)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    # também guardamos a private em b64url (32 bytes — o "k" da JWK) para debug
    priv_int = private_key.private_numbers().private_value
    private_b64 = _b64url(priv_int.to_bytes(32, "big"))
    return {
        "vapid_public_key": public_b64,
        "vapid_private_pem": private_pem,
        "vapid_private_b64": private_b64,
    }


async def ensure_push_indexes(db) -> None:
    await db.push_subscriptions.create_index("endpoint", unique=True)
    await db.push_subscriptions.create_index("user_id")
    await db.push_alerts_log.create_index("alert_id")
    await db.push_alerts_log.create_index([("alert_id", 1), ("sent_at", -1)])


async def get_or_create_vapid(db) -> dict[str, str]:
    """Garante que existem chaves VAPID gravadas em settings/global."""
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0}) or {}
    if doc.get("vapid_public_key") and doc.get("vapid_private_pem"):
        return {
            "vapid_public_key": doc["vapid_public_key"],
            "vapid_private_pem": doc["vapid_private_pem"],
        }
    keys = _generate_vapid_keys()
    await db.settings.update_one(
        {"id": "global"}, {"$set": {
            "vapid_public_key": keys["vapid_public_key"],
            "vapid_private_pem": keys["vapid_private_pem"],
            "vapid_private_b64": keys["vapid_private_b64"],
        }}, upsert=True,
    )
    logger.info("[push] novas chaves VAPID geradas e gravadas em settings/global")
    return {
        "vapid_public_key": keys["vapid_public_key"],
        "vapid_private_pem": keys["vapid_private_pem"],
    }


async def save_subscription(db, user_id: Optional[str], subscription: dict[str, Any],
                             company_id: Optional[str] = None) -> dict[str, Any]:
    """Persiste uma inscrição por endpoint (upsert)."""
    endpoint = subscription.get("endpoint")
    if not endpoint or "keys" not in subscription:
        raise ValueError("subscription inválida (faltando endpoint/keys)")
    doc = {
        "endpoint": endpoint,
        "keys": subscription["keys"],
        "user_id": user_id,
        "company_id": company_id,
        "user_agent": subscription.get("user_agent"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "active": True,
    }
    await db.push_subscriptions.update_one(
        {"endpoint": endpoint}, {"$set": doc}, upsert=True,
    )
    doc.pop("_id", None)
    return doc


async def list_subscriptions(db, only_active: bool = True,
                              allowed_roles: Optional[list[str]] = None,
                              company_id: Optional[str] = None) -> list[dict]:
    q: dict = {"active": True} if only_active else {}
    if company_id:
        q["company_id"] = company_id
    subs = await db.push_subscriptions.find(q, {"_id": 0}).to_list(1000)
    if not allowed_roles:
        return subs
    user_ids = [s.get("user_id") for s in subs if s.get("user_id")]
    if not user_ids:
        return []
    users = await db.users.find(
        {"id": {"$in": user_ids}, "role": {"$in": allowed_roles}, "active": True},
        {"_id": 0, "id": 1, "role": 1},
    ).to_list(1000)
    allowed_user_ids = {u["id"] for u in users}
    return [s for s in subs if s.get("user_id") in allowed_user_ids]


async def remove_subscription(db, endpoint: str) -> bool:
    res = await db.push_subscriptions.update_one(
        {"endpoint": endpoint}, {"$set": {"active": False}},
    )
    return res.modified_count > 0


async def send_one(sub: dict[str, Any], payload: dict[str, Any], vapid_pem: str) -> tuple[bool, Optional[str]]:
    """Envia um push. Retorna (ok, error_msg)."""
    try:
        webpush(
            subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]},
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=vapid_pem,
            vapid_claims={"sub": VAPID_CLAIM_SUB},
            ttl=60,
        )
        return True, None
    except WebPushException as e:
        # 404/410: endpoint inválido → remover
        status = getattr(e.response, "status_code", None) if getattr(e, "response", None) else None
        msg = f"WebPushException status={status} {str(e)[:200]}"
        return False, msg
    except Exception as e:
        return False, f"erro_envio: {str(e)[:200]}"


async def broadcast(db, payload: dict[str, Any], allowed_roles: Optional[list[str]] = None,
                    company_id: Optional[str] = None) -> dict[str, Any]:
    """Envia o mesmo payload para todas as inscrições ativas.
    Se `allowed_roles` for fornecido, envia apenas para subscrições cujo `user_id`
    tem um desses papéis (default: gestor + auditor para alertas operacionais).
    Se `company_id` for fornecido, envia apenas para subs daquele tenant.
    """
    vapid = await get_or_create_vapid(db)
    pem = vapid["vapid_private_pem"]
    subs = await list_subscriptions(db, only_active=True, allowed_roles=allowed_roles, company_id=company_id)
    if not subs:
        return {"sent": 0, "failed": 0, "removed": 0, "details": []}

    sent = failed = removed = 0
    details = []
    for sub in subs:
        ok, err = await send_one(sub, payload, pem)
        if ok:
            sent += 1
        else:
            failed += 1
            # 404/410 → desativa
            if err and ("status=410" in err or "status=404" in err or "Gone" in err or "NotFound" in err):
                await remove_subscription(db, sub["endpoint"])
                removed += 1
            details.append({"endpoint": sub["endpoint"][:60] + "...", "error": err})
    return {"sent": sent, "failed": failed, "removed": removed, "details": details}


async def broadcast_dwell_alerts(db, alerts: list[dict]) -> dict[str, Any]:
    """Filtra alertas já notificados nos últimos 5 min e envia só os novos."""
    if not alerts:
        return {"sent": 0, "failed": 0, "throttled": 0}
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    new_alerts = []
    for a in alerts:
        aid = a.get("id")
        if not aid:
            continue
        recent = await db.push_alerts_log.find_one({"alert_id": aid, "sent_at": {"$gte": cutoff}})
        if recent:
            continue
        new_alerts.append(a)

    if not new_alerts:
        return {"sent": 0, "failed": 0, "throttled": len(alerts), "new_alerts": 0}

    # 1 push por alerta para que o gestor veja cada caso
    total_sent = 0
    total_failed = 0
    for a in new_alerts:
        payload = {
            "title": f"⚠️ {a.get('title', 'Alerta de campo')}",
            "body": a.get("message") or "Verifique o painel do gestor.",
            "tag": a.get("id"),
            "level": a.get("level", "warning"),
            "url": "/?tab=gestor",
            "alert_id": a.get("id"),
            "collaborator_id": a.get("collaborator_id"),
        }
        # Alertas operacionais: gestor + auditor da MESMA empresa do colaborador
        target_cid = a.get("company_id")
        result = await broadcast(db, payload, allowed_roles=["gestor", "auditor"], company_id=target_cid)
        total_sent += result.get("sent", 0)
        total_failed += result.get("failed", 0)
        await db.push_alerts_log.insert_one({
            "alert_id": a.get("id"),
            "company_id": target_cid,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "title": a.get("title"),
            "level": a.get("level"),
            "result": {"sent": result.get("sent", 0), "failed": result.get("failed", 0)},
        })
    return {"sent": total_sent, "failed": total_failed, "throttled": len(alerts) - len(new_alerts), "new_alerts": len(new_alerts)}


__all__ = [
    "broadcast", "broadcast_dwell_alerts", "ensure_push_indexes",
    "get_or_create_vapid", "list_subscriptions", "remove_subscription",
    "save_subscription",
]
