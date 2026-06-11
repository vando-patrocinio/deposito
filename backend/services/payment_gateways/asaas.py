"""Asaas — implementação do PaymentGateway (Brasil).

Docs: https://docs.asaas.com/reference
- Sandbox: https://sandbox.asaas.com/api/v3
- Production: https://api.asaas.com/v3
- Auth: header `access_token: <api_key>`
- Webhook: header `asaas-access-token` deve bater com ASAAS_WEBHOOK_TOKEN
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "billing-team",
    "domain": "financeiro",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import os
from typing import Any, Optional

import httpx

from .base import (
    PaymentGateway, GatewayError,
    CustomerIn, ChargeIn, ChargeOut, WebhookEvent,
)


class AsaasGateway(PaymentGateway):
    name = "asaas"
    env_var_key = "ASAAS_API_KEY"
    env_var_token = "ASAAS_WEBHOOK_TOKEN"

    def __init__(self) -> None:
        self.api_key = os.environ.get("ASAAS_API_KEY", "")
        self.env = (os.environ.get("ASAAS_ENV") or "sandbox").lower()
        self.webhook_token = os.environ.get("ASAAS_WEBHOOK_TOKEN", "")
        if self.env == "production":
            self.base_url = "https://api.asaas.com/v3"
        else:
            self.base_url = "https://sandbox.asaas.com/api/v3"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    # -------------------------------------------------------------------
    # HTTP helpers
    # -------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise GatewayError(
                "ASAAS_API_KEY não configurada em /app/backend/.env")
        return {
            "access_token": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _post(self, path: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{self.base_url}{path}",
                                  headers=self._headers(), json=payload)
        if r.status_code >= 400:
            raise GatewayError(f"Asaas {r.status_code}: {r.text}")
        return r.json()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(f"{self.base_url}{path}",
                                 headers=self._headers(), params=params)
        if r.status_code >= 400:
            raise GatewayError(f"Asaas {r.status_code}: {r.text}")
        return r.json()

    async def _delete(self, path: str) -> dict:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.delete(f"{self.base_url}{path}",
                                    headers=self._headers())
        if r.status_code >= 400:
            raise GatewayError(f"Asaas {r.status_code}: {r.text}")
        return r.json()

    # -------------------------------------------------------------------
    # Customer
    # -------------------------------------------------------------------
    async def create_customer(self, customer: CustomerIn) -> str:
        payload = {
            "name": customer.name,
            "cpfCnpj": customer.cpf_cnpj,
        }
        if customer.email: payload["email"] = customer.email
        if customer.phone: payload["phone"] = customer.phone
        if customer.mobile_phone: payload["mobilePhone"] = customer.mobile_phone
        if customer.postal_code: payload["postalCode"] = customer.postal_code
        if customer.address: payload["address"] = customer.address
        if customer.address_number: payload["addressNumber"] = customer.address_number
        if customer.complement: payload["complement"] = customer.complement
        if customer.province: payload["province"] = customer.province
        if customer.external_reference:
            payload["externalReference"] = customer.external_reference

        r = await self._post("/customers", payload)
        cid = r.get("id")
        if not cid:
            raise GatewayError(f"Asaas customer create — sem id no retorno: {r}")
        return cid

    # -------------------------------------------------------------------
    # Charge (payment)
    # -------------------------------------------------------------------
    async def create_charge(self, charge: ChargeIn) -> ChargeOut:
        payload = {
            "customer": charge.customer_gateway_id,
            "billingType": charge.billing_type,
            "dueDate": charge.due_date.isoformat(),
            "value": charge.amount,
            "description": charge.description,
        }
        if charge.external_reference:
            payload["externalReference"] = charge.external_reference
        if charge.fine_pct is not None and charge.fine_pct > 0:
            payload["fine"] = {"value": charge.fine_pct, "type": "PERCENTAGE"}
        if charge.interest_pct is not None and charge.interest_pct > 0:
            payload["interest"] = {"value": charge.interest_pct,
                                    "type": "PERCENTAGE"}

        r = await self._post("/payments", payload)
        return self._charge_from_payload(r, charge.billing_type)

    async def get_charge(self, gateway_charge_id: str) -> ChargeOut:
        r = await self._get(f"/payments/{gateway_charge_id}")
        billing_type = r.get("billingType") or "UNDEFINED"
        return self._charge_from_payload(r, billing_type)

    async def cancel_charge(self, gateway_charge_id: str) -> dict:
        return await self._delete(f"/payments/{gateway_charge_id}")

    async def refund_charge(self, gateway_charge_id: str,
                            value: Optional[float] = None) -> dict:
        payload: dict = {}
        if value is not None:
            payload["value"] = value
        return await self._post(f"/payments/{gateway_charge_id}/refund",
                                payload)

    # -------------------------------------------------------------------
    # Webhook
    # -------------------------------------------------------------------
    def verify_webhook(self, headers: dict[str, Any], body: bytes) -> bool:
        """Asaas envia o token no header `asaas-access-token`."""
        if not self.webhook_token:
            # Se token não configurado, aceita (modo dev). Em prod log warn.
            return True
        # Headers podem vir com casing variado
        token = (headers.get("asaas-access-token")
                  or headers.get("Asaas-Access-Token")
                  or headers.get("ASAAS-ACCESS-TOKEN") or "")
        return token == self.webhook_token

    def parse_webhook(self, payload: dict) -> WebhookEvent:
        ev = payload.get("event") or "UNKNOWN"
        pay = payload.get("payment") or {}
        if not pay.get("id"):
            raise GatewayError(f"Asaas webhook sem payment.id: {payload}")
        return WebhookEvent(
            gateway=self.name,
            event_type=ev,
            charge_id=pay["id"],
            status=pay.get("status") or "UNKNOWN",
            external_reference=pay.get("externalReference"),
            raw=payload,
        )

    # -------------------------------------------------------------------
    # internals
    # -------------------------------------------------------------------
    def _charge_from_payload(self, p: dict, billing_type: str) -> ChargeOut:
        """Decodifica resposta /payments do Asaas pro modelo padrão."""
        return ChargeOut(
            gateway=self.name,
            gateway_charge_id=p.get("id"),
            status=p.get("status") or "PENDING",
            billing_type=billing_type,
            amount=float(p.get("value") or 0),
            due_date=p.get("dueDate") or "",
            boleto_url=p.get("bankSlipUrl"),
            boleto_digitable_line=p.get("identificationField"),
            pix_qr_code=p.get("pixQrCode"),
            pix_qr_code_image_url=p.get("pixQrCodeImage"),
            pix_copy_paste=p.get("pixQrCode"),
            raw=p,
        )
