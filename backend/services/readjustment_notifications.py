"""Notificação WhatsApp 30 dias antes do reajuste anual.

REGRA ANATEL: cliente DEVE ser notificado com antecedência sobre o reajuste.
30 dias antes é o padrão recomendado para SCM (internet fibra).

Mensagem:
  "Oi [Nome]! Em DD/MM sua mensalidade Ligo será reajustada pelo [ÍNDICE]
   (+X.XX%): passará de R$ X pra R$ Y. Qualquer dúvida, é só chamar! 💙"

Evita duplicar usando coleção `subscriber_readjustment_notifications`.
"""
import logging
from datetime import datetime, timedelta, timezone

import httpx

from database import db
from services.readjustment import (
    _next_readjustment_date, calculate_readjustment_preview,
)

logger = logging.getLogger(__name__)


async def _send_whatsapp(phone: str, text: str) -> bool:
    """Envia mensagem via sidecar Baileys (mesmo gateway usado pela Isabella)."""
    import os
    base = os.environ.get("WA_SIDECAR_URL")
    if not base:
        logger.warning("[readjustment-notify] WA_SIDECAR_URL não configurado")
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(f"{base}/send",
                                json={"phone": phone, "text": text})
            return r.status_code == 200
    except Exception as e:
        logger.warning("[readjustment-notify] envio falhou: %s", e)
        return False


def _format_message(name: str, next_date: datetime, index_name: str,
                    pct: float, current: float, new_price: float) -> str:
    """Mensagem amigável (Isabella tone)."""
    first_name = (name or "").strip().split()[0] if name else "Tudo bem"
    return (
        f"Oi {first_name}! 💙\n\n"
        f"Em *{next_date.strftime('%d/%m')}* sua mensalidade Ligo Fibra "
        f"será reajustada pelo *{index_name}* (+{pct:.2f}%):\n\n"
        f"• Valor atual: R$ {current:.2f}\n"
        f"• Novo valor: R$ {new_price:.2f}\n\n"
        f"Esse reajuste é anual e segue a inflação oficial — exigência "
        f"contratual prevista em contrato.\n\n"
        f"Qualquer dúvida, é só me chamar aqui mesmo! 😊"
    )


async def notify_upcoming_readjustments(company_id: str,
                                          days_ahead: int = 30) -> dict:
    """Para cada cliente com reajuste nos próximos N dias, envia WhatsApp.

    Idempotente: não envia 2x ao mesmo cliente pra mesmo reajuste.
    """
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=days_ahead)
    sent = 0
    skipped_already_notified = 0
    failed = 0

    async for sub in db.subscribers.find(
        {"company_id": company_id,
         "installation_date": {"$exists": True, "$ne": None},
         "status": {"$in": ["ATIVO", "ativo"]}},
        {"_id": 0},
    ):
        next_date = _next_readjustment_date(sub)
        if not next_date or next_date <= now or next_date > horizon:
            continue

        # Já notificado pra esta data?
        notif_key = (f"{sub['id']}_{next_date.strftime('%Y-%m')}")
        existing = await db.subscriber_readjustment_notifications.find_one(
            {"key": notif_key}, {"_id": 0},
        )
        if existing:
            skipped_already_notified += 1
            continue

        preview = await calculate_readjustment_preview(sub)
        if not preview or preview.get("accumulated_pct", 0) <= 0:
            continue

        # Pega 1º telefone primary
        phones = sub.get("phones") or []
        primary = next((p for p in phones if p.get("is_primary")),
                       phones[0] if phones else None)
        if not primary:
            continue
        phone_raw = (primary.get("raw_number") or "").replace("+", "")
        if not phone_raw:
            continue

        msg = _format_message(
            sub.get("name") or "Cliente",
            next_date, preview["index_name"],
            preview["accumulated_pct"], preview["current_price"],
            preview["new_price"],
        )
        ok = await _send_whatsapp(phone_raw, msg)
        if ok:
            sent += 1
            await db.subscriber_readjustment_notifications.insert_one({
                "key": notif_key,
                "subscriber_id": sub["id"],
                "company_id": company_id,
                "phone": phone_raw,
                "scheduled_for": next_date.isoformat(),
                "preview": preview,
                "sent_at": now.isoformat(),
            })
        else:
            failed += 1

    logger.info("[readjustment-notify] %s: sent=%s skip=%s fail=%s",
                company_id, sent, skipped_already_notified, failed)
    return {"sent": sent,
            "skipped_already_notified": skipped_already_notified,
            "failed": failed}
