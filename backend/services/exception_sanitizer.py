"""Exception sanitizer middleware — ART.13 SECURITY_LOCK.

Devolve mensagens GENÉRICAS ao cliente, mas registra full stack server-side.
Aplicado em server.py via app.exception_handler.
"""
from __future__ import annotations

import logging
import uuid
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("security.exception_handler")


GENERIC_BY_STATUS = {
    400: "Bad request",
    401: "Authentication required",
    403: "Forbidden",
    404: "Not found",
    409: "Conflict",
    422: "Unprocessable entity",
    500: "Internal server error",
    503: "Service unavailable",
}


def _is_safe_message(msg) -> bool:
    """Heurística: mensagens de negócio curtas e em PT/EN sem detalhe técnico.

    Bloqueia se contém: caminhos de arquivo, traceback, str() de Exception,
    schemas, hostnames internos.
    """
    if not isinstance(msg, str):
        return True   # detail estruturado (dict/list) — caller controla
    if len(msg) > 200:
        return False
    bad_signals = (
        "/app/", "Traceback", "<class ", "0x", "psycopg", "Motor",
        "pymongo", "sqlalchemy", "object at 0x", "/usr/", "site-packages",
    )
    return not any(s in msg for s in bad_signals)


async def sanitized_http_exception_handler(
    request: Request, exc: StarletteHTTPException
):
    if _is_safe_message(exc.detail):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None) or {},
        )
    # mensagem suspeita: troca por genérica + log server-side
    error_id = uuid.uuid4().hex[:12]
    logger.warning(
        "[security.exception] error_id=%s status=%s path=%s detail=%r",
        error_id, exc.status_code, request.url.path, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": GENERIC_BY_STATUS.get(
            exc.status_code, "Request rejected"),
                 "error_id": error_id},
    )


async def sanitized_unhandled_exception_handler(
    request: Request, exc: Exception
):
    error_id = uuid.uuid4().hex[:12]
    logger.exception(
        "[security.unhandled] error_id=%s path=%s", error_id, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error_id": error_id},
    )


# --------------------------------------------------------------------- #
# Helper utilizado nas rotas para substituir `HTTPException(NNN, str(e))`
# por mensagem genérica + log server-side (SECURITY_LOCK ART.13).
# --------------------------------------------------------------------- #
_GENERIC_DETAIL = {
    400: "Bad request",
    401: "Authentication required",
    403: "Forbidden",
    404: "Not found",
    409: "Conflict",
    422: "Unprocessable entity",
    500: "Internal server error",
    502: "Upstream service error",
    503: "Service unavailable",
}


def safe_detail(status_code: int, exc: Exception, context: str = "") -> str:
    """ART.13 helper: registra a exceção no logger e devolve mensagem genérica
    curta para o cliente.

    Uso:
        try:
            ...
        except Exception as e:
            raise HTTPException(500, safe_detail(500, e, "endpoint_x"))
    """
    error_id = uuid.uuid4().hex[:8]
    logger.warning(
        "[security.detail] error_id=%s ctx=%s status=%s exc=%s: %s",
        error_id, context or "-", status_code, type(exc).__name__, str(exc)[:300],
    )
    return _GENERIC_DETAIL.get(status_code, "Request rejected")
