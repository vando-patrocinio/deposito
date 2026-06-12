"""
asaas_client.py — Cliente Asaas (CTO P0 11/06/2026 + iter235 produção)

CONSTRAINTS:
- ASAAS_ENV decide o ambiente: 'sandbox' (default) | 'producao'/'production'.
- ASAAS_API_KEY lido de env. Nunca logado.
- Headers compatíveis com docs Asaas v3 (access_token).
- Produção exige ASAAS_ENV=producao + ASAAS_API_KEY válida + ASAAS_PROD_ENABLED=true
  (kill-switch extra pra evitar acionamento acidental).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

log = logging.getLogger("asaas_client")

SANDBOX_BASE = "https://api-sandbox.asaas.com/v3"
PROD_BASE = "https://api.asaas.com/v3"

_PROD_ALIASES = {"producao", "produção", "production", "prod", "live"}


def _env() -> str:
    raw = (os.environ.get("ASAAS_ENV") or "sandbox").strip().lower()
    return "producao" if raw in _PROD_ALIASES else "sandbox"


def is_production() -> bool:
    return _env() == "producao"


def _prod_enabled() -> bool:
    v = (os.environ.get("ASAAS_PROD_ENABLED") or "false").strip().lower()
    return v in ("1", "true", "yes", "on")


def _base_url() -> str:
    return PROD_BASE if is_production() else SANDBOX_BASE


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
    # Kill-switch de produção: exige toggle explícito mesmo com ASAAS_ENV=producao
    if is_production() and not _prod_enabled():
        raise RuntimeError(
            "ASAAS produção bloqueada — defina ASAAS_PROD_ENABLED=true em backend/.env "
            "depois de confirmar chave/webhook reais.")
    if not os.environ.get("ASAAS_API_KEY"):
        # Sinaliza ausência de chave de forma estruturada
        raise _AsaasNoKey()
    url = f"{_base_url()}{path}"
    log.info("asaas[%s] %s %s", _env(), method, path)  # NÃO loga payload nem key
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.request(method, url, headers=_headers(), **kwargs)
    return resp


class _AsaasNoKey(Exception):
    pass


def _no_key_response() -> Dict[str, Any]:
    return {
        "ok": False,
        "error": "asaas_key_missing",
        "message": "ASAAS_API_KEY ausente — modo sandbox sem chave. Configure ASAAS_API_KEY no backend/.env.",
    }


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
    try:
        r = await _request("GET", "/finance/balance")
    except _AsaasNoKey:
        return _no_key_response()
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
    try:
        r = await _request("POST", "/transfers", json=payload)
    except _AsaasNoKey:
        return _no_key_response()
    if r.status_code in (200, 201):
        return {"ok": True, **r.json()}
    return normalize_error(r)


async def get_transfer_status(transfer_id: str) -> Dict[str, Any]:
    try:
        r = await _request("GET", f"/transfers/{transfer_id}")
    except _AsaasNoKey:
        return _no_key_response()
    if r.status_code == 200:
        return {"ok": True, **r.json()}
    return normalize_error(r)


async def list_transfers(limit: int = 20, offset: int = 0) -> Dict[str, Any]:
    try:
        r = await _request("GET", "/transfers", params={"limit": limit, "offset": offset})
    except _AsaasNoKey:
        return _no_key_response()
    if r.status_code == 200:
        return {"ok": True, **r.json()}
    return normalize_error(r)


async def cancel_transfer_if_possible(transfer_id: str) -> Dict[str, Any]:
    try:
        r = await _request("POST", f"/transfers/{transfer_id}/cancel")
    except _AsaasNoKey:
        return _no_key_response()
    if r.status_code in (200, 201):
        return {"ok": True, **r.json()}
    return normalize_error(r)


# ───────────────────────── BOLETO (Conta a Pagar) ─────────────────────────
# Asaas chama isso de "Bill" — pagamento de boletos/concessionárias por linha
# digitável ou código de barras. Doc: https://docs.asaas.com/reference/criar-um-pagamento-de-conta

async def create_bill_payment(
    *,
    identification_field: Optional[str] = None,  # linha digitável (47/48 dígitos)
    bar_code: Optional[str] = None,              # cód barras (44 dígitos) — alternativa
    value: Optional[float] = None,               # alguns boletos exigem valor
    due_date: Optional[str] = None,              # YYYY-MM-DD do vencimento
    schedule_date: Optional[str] = None,         # YYYY-MM-DD agendamento
    description: Optional[str] = None,
    external_reference: Optional[str] = None,
    discount: Optional[float] = None,            # desconto em R$ (se aplicável)
) -> Dict[str, Any]:
    """POST /bill — paga boleto (concessionária, fornecedor, tributo).

    Para boletos de concessionária a Asaas calcula o valor pelo código.
    Para boletos de fornecedor é obrigatório passar `value`.
    """
    if not identification_field and not bar_code:
        return {"ok": False, "error": "missing_code",
                "message": "Informe identification_field (linha digitável) OU bar_code."}
    payload: Dict[str, Any] = {}
    if identification_field:
        payload["identificationField"] = identification_field.replace(" ", "").replace(".", "")
    if bar_code:
        payload["barCode"] = bar_code.replace(" ", "")
    if value is not None:
        payload["value"] = float(value)
    if due_date:
        payload["dueDate"] = due_date
    if schedule_date:
        payload["scheduleDate"] = schedule_date
    if description:
        payload["description"] = description[:140]
    if external_reference:
        payload["externalReference"] = external_reference[:60]
    if discount is not None:
        payload["discount"] = float(discount)
    try:
        r = await _request("POST", "/bill", json=payload)
    except _AsaasNoKey:
        return _no_key_response()
    if r.status_code in (200, 201):
        return {"ok": True, **r.json()}
    return normalize_error(r)


async def get_bill_payment_status(bill_id: str) -> Dict[str, Any]:
    try:
        r = await _request("GET", f"/bill/{bill_id}")
    except _AsaasNoKey:
        return _no_key_response()
    if r.status_code == 200:
        return {"ok": True, **r.json()}
    return normalize_error(r)


async def cancel_bill_payment(bill_id: str) -> Dict[str, Any]:
    try:
        r = await _request("POST", f"/bill/{bill_id}/cancel")
    except _AsaasNoKey:
        return _no_key_response()
    if r.status_code in (200, 201):
        return {"ok": True, **r.json()}
    return normalize_error(r)


async def simulate_bill_payment(
    identification_field: Optional[str] = None,
    bar_code: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /bill/simulate — valida o boleto antes de criar (vencimento/valor)."""
    payload: Dict[str, Any] = {}
    if identification_field:
        payload["identificationField"] = identification_field.replace(" ", "").replace(".", "")
    if bar_code:
        payload["barCode"] = bar_code.replace(" ", "")
    if not payload:
        return {"ok": False, "error": "missing_code"}
    try:
        r = await _request("POST", "/bill/simulate", json=payload)
    except _AsaasNoKey:
        return _no_key_response()
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
