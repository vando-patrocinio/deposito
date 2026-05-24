"""
================================================================
SmartProv — Sistema de Gestão para Provedores de Internet
Copyright (c) 2025-2026  V S DO PATROCINIO PROVEDOR DE INTERNET ME
CNPJ: 13.302.883/0001-36  ·  vando@ligotelecom.com
All rights reserved. Proprietary software — see LICENSE.
================================================================

Módulo de identidade do produto.

Centraliza todas as informações de copyright, CNPJ e fingerprints
para uso por endpoints públicos, middleware HTTP e logs.

NUNCA edite/remova este arquivo sem autorização da proprietária.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

# --------------------------------------------------------------------- #
# Identidade da proprietária (fonte canônica única)
# --------------------------------------------------------------------- #
OWNER = {
    "company": "V S DO PATROCINIO PROVEDOR DE INTERNET ME",
    "trade_name": "SmartProv",
    "cnpj": "13.302.883/0001-36",
    "email": "vando@ligotelecom.com",
    "copyright": "© 2025-2026 V S DO PATROCINIO PROVEDOR DE INTERNET ME",
    "rights": "All rights reserved",
    "license": "Proprietary — see /LICENSE",
}

PRODUCT = {
    "name": "SmartProv",
    "description": "ISP Suite — Billing, Network (RADIUS/PPPoE), "
                    "Fleet Management, AI Operations",
    "version": "1.0.0",
}

# Timestamp imutável de boot do processo — entra no fingerprint
_BOOT_AT = datetime.now(timezone.utc).isoformat()


def _fingerprint() -> str:
    """Hash determinístico que identifica esta instância como autêntica.

    Combina CNPJ + razão social + boot time. Mesmo se alguém clonar o código,
    o hash retornado por /api/about será reprodutível APENAS por quem tem o
    CNPJ correto. Funciona como prova de origem em disputas.
    """
    secret = os.environ.get("OWNER_SIGN_SECRET", OWNER["cnpj"])
    raw = f"{OWNER['cnpj']}|{OWNER['company']}|{secret}|{_BOOT_AT}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def about_payload() -> dict:
    """Payload retornado por /api/about. NÃO contém segredos."""
    return {
        "product": PRODUCT,
        "owner": OWNER,
        "boot_at": _BOOT_AT,
        "fingerprint_sha256": _fingerprint(),
        "notice": (
            f"This software is proprietary and confidential. "
            f"Property of {OWNER['company']} (CNPJ {OWNER['cnpj']}). "
            f"Unauthorized copy, reverse engineering or redistribution "
            f"is prohibited under Lei 9.609/98 and Lei 9.610/98."
        ),
    }


def x_powered_by_value() -> str:
    """String compacta para o header HTTP X-Powered-By."""
    return f"{PRODUCT['name']} © {OWNER['cnpj']}"
