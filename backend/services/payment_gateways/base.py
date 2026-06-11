"""Interface comum pra todos os payment gateways."""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "billing-team",
    "domain": "financeiro",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from abc import ABC, abstractmethod
from typing import Any, Literal, Optional
from datetime import date

from pydantic import BaseModel, Field


BillingType = Literal["BOLETO", "PIX", "UNDEFINED"]


class GatewayError(Exception):
    """Erro genérico do gateway (auth, 4xx, 5xx, payload inválido)."""


class CustomerIn(BaseModel):
    """Dados pra criar/sincronizar cliente no gateway."""
    name: str
    cpf_cnpj: str
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile_phone: Optional[str] = None
    postal_code: Optional[str] = None
    address: Optional[str] = None
    address_number: Optional[str] = None
    complement: Optional[str] = None
    province: Optional[str] = None  # bairro
    external_reference: Optional[str] = None  # id do subscriber local


class ChargeIn(BaseModel):
    """Dados pra criar uma cobrança."""
    customer_gateway_id: str  # id do cliente no gateway
    billing_type: BillingType
    due_date: date
    amount: float = Field(..., gt=0)
    description: str
    external_reference: Optional[str] = None  # id local da fatura
    fine_pct: Optional[float] = None    # multa por atraso (%)
    interest_pct: Optional[float] = None  # juros ao mês (%)


class ChargeOut(BaseModel):
    """Retorno padronizado de uma cobrança criada/consultada."""
    gateway: str
    gateway_charge_id: str
    status: str  # PENDING | RECEIVED | CONFIRMED | OVERDUE | CANCELED | REFUNDED | etc
    billing_type: BillingType
    amount: float
    due_date: str  # ISO YYYY-MM-DD
    # Boleto
    boleto_url: Optional[str] = None
    boleto_digitable_line: Optional[str] = None
    # Pix
    pix_qr_code: Optional[str] = None
    pix_qr_code_image_url: Optional[str] = None
    pix_copy_paste: Optional[str] = None
    # raw — útil pra debug e reconciliação
    raw: Optional[dict] = None


class WebhookEvent(BaseModel):
    """Evento decodificado do webhook."""
    gateway: str
    event_type: str  # PAYMENT_CONFIRMED | PAYMENT_RECEIVED | ...
    charge_id: str   # id no gateway
    status: str
    external_reference: Optional[str] = None
    raw: dict


class PaymentGateway(ABC):
    """Interface comum.

    Implementações:
      - asaas.py (Asaas — Brasil)
      - cora.py (futuro)
      - sicoob.py (futuro)
    """

    name: str = "abstract"
    env_var_key: str = ""       # ex: "ASAAS_API_KEY"
    env_var_token: str = ""     # ex: "ASAAS_WEBHOOK_TOKEN"

    @abstractmethod
    def is_configured(self) -> bool:
        """True se as credenciais existem no env."""

    @abstractmethod
    async def create_customer(self, customer: CustomerIn) -> str:
        """Retorna gateway_customer_id."""

    @abstractmethod
    async def create_charge(self, charge: ChargeIn) -> ChargeOut:
        """Cria cobrança e retorna dados (boleto URL, Pix QR, etc)."""

    @abstractmethod
    async def get_charge(self, gateway_charge_id: str) -> ChargeOut:
        """Consulta status/dados de uma cobrança."""

    @abstractmethod
    async def cancel_charge(self, gateway_charge_id: str) -> dict:
        """Cancela cobrança pendente (DELETE no Asaas)."""

    @abstractmethod
    async def refund_charge(self, gateway_charge_id: str,
                            value: Optional[float] = None) -> dict:
        """Estorna cobrança já recebida."""

    @abstractmethod
    def verify_webhook(self, headers: dict[str, Any], body: bytes) -> bool:
        """Valida assinatura/token do webhook."""

    @abstractmethod
    def parse_webhook(self, payload: dict) -> WebhookEvent:
        """Decodifica payload do webhook em formato padronizado."""
