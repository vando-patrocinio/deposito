"""
auto_emit_middleware.py — Sprint 13 (Cobertura Nervosa Massiva)
Middleware HTTP que detecta mutations relevantes (POST/PUT/PATCH/DELETE)
em paths estratégicos e auto-emite eventos no event_bus.

Trade-off: payload semântico é genérico (vem do body) — para eventos
mais ricos, plugar `emit_business` manualmente nos handlers.

PATH → kind mapping:
    POST   /api/tickets*          → ticket.opened
    PATCH  /api/tickets/*/close   → ticket.closed
    POST   /api/subscribers*      → client.created
    POST   /api/sales*            → sale.created
    POST   /api/financeiro/cobrar → dunning.escalated
    POST   /api/whatsapp/send*    → wa.campaign_sent
    POST   /api/wa/webhook*       → wa.inbound
    DELETE /api/* (qualquer)      → audit.delete (já no rbac.audit_log)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional, Tuple

from fastapi import Request

log = logging.getLogger("auto_emit")

# (regex de path, método, kind, severity)
RULES = [
    (r"^/api/tickets/?$",                "POST",   "ticket.opened",       "media"),
    (r"^/api/tickets/[^/]+/close$",      "POST",   "ticket.closed",       "baixa"),
    (r"^/api/tickets/[^/]+/close$",      "PATCH",  "ticket.closed",       "baixa"),
    (r"^/api/subscribers/?$",            "POST",   "client.created",      "baixa"),
    (r"^/api/sales(/funnel)?/?$",        "POST",   "sale.created",        "media"),
    (r"^/api/sales/[^/]+/lost$",         "POST",   "sale.lost",           "media"),
    (r"^/api/financeiro/cobrar",         "POST",   "dunning.escalated",   "media"),
    (r"^/api/billing/charge",            "POST",   "payment.overdue",     "media"),
    (r"^/api/whatsapp/campaigns",        "POST",   "wa.campaign_sent",    "baixa"),
    (r"^/api/wa/webhook",                "POST",   "wa.inbound",          "baixa"),
    (r"^/api/baileys/webhook",           "POST",   "wa.inbound",          "baixa"),
    (r"^/api/partners/[^/]+/qr/redeem",  "POST",   "partner.qr_redeemed", "media"),
    (r"^/api/referrals/[^/]+/convert",   "POST",   "referral.converted",  "media"),
    (r"^/api/fleet/gps/deviation",       "POST",   "gps.route_deviation", "alta"),
]

# Pré-compila
_RULES = [(re.compile(p), m, k, s) for (p, m, k, s) in RULES]


def _match(path: str, method: str) -> Optional[Tuple[str, str]]:
    """Retorna (kind, severity) ou None."""
    for rx, m, k, s in _RULES:
        if m == method and rx.match(path):
            return k, s
    return None


def _extract_payload(body: bytes, max_keys: int = 6) -> dict:
    """Best-effort extraction de IDs do body JSON."""
    try:
        obj = json.loads(body)
    except Exception:
        return {}
    if not isinstance(obj, dict):
        return {}
    interesting = {}
    keys_of_interest = (
        "id", "subscriber_id", "ticket_id", "lead_id",
        "company_id", "cto_id", "onu_id", "user_id",
        "amount", "value", "campaign_id", "channel",
        "reason", "tech_id", "code",
    )
    for k in keys_of_interest:
        if k in obj:
            interesting[k] = obj[k]
        if len(interesting) >= max_keys:
            break
    return interesting


async def auto_emit_middleware(request: Request, call_next):
    """Middleware FastAPI. Roda APÓS o handler. Só emite em status 2xx.

    Otimização: só consome `request.body()` se o path/método casa com
    alguma RULE. Caso contrário, deixa o body intacto para o handler
    (evita 'No response returned' em uploads/streams).
    """
    match = _match(request.url.path, request.method)
    if not match:
        # rota não interessa ao auto-emit — não toca no body
        return await call_next(request)

    # Captura body apenas para rotas mapeadas
    body = b""
    try:
        body = await request.body()
    except Exception:
        body = b""

    response = await call_next(request)

    try:
        if 200 <= response.status_code < 300:
            kind, severity = match
            user = getattr(request.state, "user", None)
            company_id = None
            if isinstance(user, dict):
                company_id = user.get("company_id")
            payload = _extract_payload(body)
            from services.event_emitters import emit_business
            await emit_business(
                kind=kind,
                company_id=company_id,
                actor=user if isinstance(user, dict) else None,
                payload={**payload,
                         "_auto_emitted": True,
                         "path": request.url.path,
                         "method": request.method},
                severity=severity,
                source="auto_emit_middleware",
            )
    except Exception as e:  # noqa: BLE001
        log.debug("[auto_emit] falha: %s", e)
    return response
