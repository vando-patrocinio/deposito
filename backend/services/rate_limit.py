"""Rate limiting global via slowapi.

Estratégia:
  • Limitador padrão geral (por IP) bem permissivo (100 req/min).
  • Limites específicos mais agressivos via decorator em endpoints sensíveis.
  • Em DEV (REACT_APP_BACKEND_URL contém 'preview.emergent' ou 'localhost'),
    limites são 10x mais permissivos para não travar testes locais.

Uso:
  from services.rate_limit import limiter, get_limit
  @router.post(...)
  @limiter.limit(get_limit("auth_login"))
  async def login(request: Request, ...):
      ...
"""
from __future__ import annotations

import logging
import os

from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger("ponto.rate_limit")


def _is_dev() -> bool:
    base = (os.environ.get("PUBLIC_BACKEND_URL", "") + " "
            + os.environ.get("PUBLIC_FRONTEND_URL", "")).lower()
    return "preview.emergent" in base or "localhost" in base


# Multiplicador de limite em DEV (10x mais permissivo)
_MULT = 10 if _is_dev() else 1

# Limites específicos — string slowapi format "N/period"
_LIMITS = {
    # Auth — proteção brute force
    "auth_login": f"{5 * _MULT}/minute",
    "auth_register": f"{3 * _MULT}/minute",
    "auth_password_reset": f"{3 * _MULT}/minute",
    # Mass messaging — proteção spam interno
    "mass_create": f"{10 * _MULT}/minute",
    "mass_start": f"{5 * _MULT}/minute",
    # Secretaria IA — proteção contra abuso de LLM custos
    "secretaria_ask": f"{30 * _MULT}/minute",
    # Webhooks — protege contra flood (Twilio, Meta retry burst)
    "webhook_inbound": f"{120 * _MULT}/minute",
    # Default fallback
    "default": f"{100 * _MULT}/minute",
}


def get_limit(name: str) -> str:
    return _LIMITS.get(name, _LIMITS["default"])


def _key_func(request) -> str:
    """Chave do limitador: prioriza X-Forwarded-For (Kubernetes ingress),
    senão usa get_remote_address."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(
    key_func=_key_func,
    default_limits=[_LIMITS["default"]],
    storage_uri="memory://",  # In-memory; per-pod. Para multi-pod, redis://
    headers_enabled=False,  # FastAPI dict-returns conflitam com inject_headers
)

logger.info("[rate-limit] inicializado. dev=%s, multiplicador=%dx",
            _is_dev(), _MULT)
