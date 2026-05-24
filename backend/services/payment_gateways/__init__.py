"""Payment gateways — arquitetura plug-in.

Cada gateway implementa a interface `PaymentGateway` em base.py.
Usar `get_gateway("asaas")` pra obter uma instância já configurada
com env vars (chaves carregadas de /app/backend/.env).

Gateways disponíveis (iter108):
  - asaas   — boletos + Pix (Brasil)
  - cora    — TODO: futuro (boletos + Pix)
  - sicoob  — TODO: futuro (boletos)
"""
from .base import PaymentGateway, GatewayError, ChargeIn, ChargeOut, CustomerIn
from .asaas import AsaasGateway

_REGISTRY = {
    "asaas": AsaasGateway,
}


def get_gateway(name: str) -> PaymentGateway:
    """Retorna instância já configurada do gateway pelo nome."""
    name = (name or "").lower().strip()
    cls = _REGISTRY.get(name)
    if not cls:
        raise GatewayError(f"Gateway '{name}' não suportado. "
                           f"Disponíveis: {list(_REGISTRY)}")
    return cls()


def list_gateways() -> list[str]:
    return list(_REGISTRY)


__all__ = [
    "PaymentGateway", "GatewayError", "ChargeIn", "ChargeOut", "CustomerIn",
    "get_gateway", "list_gateways",
]
