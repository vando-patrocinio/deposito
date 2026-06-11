"""
asaas_client.py — Cliente Asaas Sandbox (CTO P0 11/06/2026)

CONSTRAINTS:
- ASAAS_ENV deve ser 'sandbox'. Não opera em produção.
- ASAAS_API_KEY lido de env. Nunca logado.
- Headers compatíveis com docs Asaas v3 (access_token).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

log = logging.getLogger("asaas_client")

SANDBOX_BASE = "https://api-sandbox.asaas.com/v3"
PROD_BASE = "https://api.asaas.com/v3"


def _env() -> str:
    return (os.environ.get("ASAAS_ENV") or "sandbox").lower()


def _base_url() -> str:
    return SANDBOX_BASE if _env() == "sandbox" else PROD_BASE


def _headers() -> Dict[str, str]:
    key = os.environ.get("ASAAS_API_KEY", "")
    if not key:
        raise RuntimeError("ASAAS_API_KEY ausente em env")
    return {
        "Content-Type": "application/json",
        "User-Agent": "ligo-tesoureira/1.0",
        "access_token": key,
    }


def _redact(s: str) -> str:
    """Nunca expor a chave em logs."""
    if not s or len(s) < 8:
        return "***"
    return s[:6] + "***" + s[-2:]


async def _request(method: str, path: str, **kwargs) -> httpx.Response:
    if _env() != "sandbox":
        raise RuntimeError("ASAAS_ENV != sandbox — operação bloqueada")
    url = f"{_base_url()}{path}"
    log.info("asaas %s %s", method, path)  # NÃO loga payload nem key
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.request(method, url, headers=_headers(), **kwargs)
    return resp


def normalize_error(resp: httpx.Response) -> Dict[str, Any]:
    """Converte erro Asaas em dict estável."""
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text[:200]}
    return {
        "ok": False,
        "http_status": resp.status_code,
        "asaas_error": body,
    }


async def get_balance() -> Dict[str, Any]:
    """GET /finance/balance"""
    r = await _request("GET", "/finance/balance")
    if r.status_code == 200:
        return {"ok": True, **r.json()}
    return normalize_error(r)


async def create_transfer_pix(
    *,
    value: float,
    pix_key: str,
    pix_key_type: str,  # CPF|CNPJ|EMAIL|PHONE|EVP
    schedule_date: Optional[str] = None,  # YYYY-MM-DD
    description: Optional[str] = None,
    external_reference: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /transfers — PIX out (transferência para chave Pix)."""
    payload: Dict[str, Any] = {
        "value": float(value),
        "pixAddressKey": pix_key,
        "pixAddressKeyType": pix_key_type,
    }
    if schedule_date:
        payload["scheduleDate"] = schedule_date
    if description:
        payload["description"] = description[:140]
    if external_reference:
        payload["externalReference"] = external_reference[:60]
    r = await _request("POST", "/transfers", json=payload)
    if r.status_code in (200, 201):
        return {"ok": True, **r.json()}
    return normalize_error(r)


async def get_transfer_status(transfer_id: str) -> Dict[str, Any]:
    r = await _request("GET", f"/transfers/{transfer_id}")
    if r.status_code == 200:
        return {"ok": True, **r.json()}
    return normalize_error(r)


async def list_transfers(limit: int = 20, offset: int = 0) -> Dict[str, Any]:
    r = await _request("GET", "/transfers", params={"limit": limit, "offset": offset})
    if r.status_code == 200:
        return {"ok": True, **r.json()}
    return normalize_error(r)


async def cancel_transfer_if_possible(transfer_id: str) -> Dict[str, Any]:
    r = await _request("POST", f"/transfers/{transfer_id}/cancel")
    if r.status_code in (200, 201):
        return {"ok": True, **r.json()}
    return normalize_error(r)


def verify_webhook_token(provided: str) -> bool:
    expected = os.environ.get("ASAAS_WEBHOOK_TOKEN", "")
    if not expected or not provided:
        return False
    # comparação constante
    if len(provided) != len(expected):
        return False
    diff = 0
    for a, b in zip(provided, expected):
        diff |= ord(a) ^ ord(b)
    return diff == 0
