"""treasury_receipts — gera mensagem de comprovante e dispara WhatsApp.

A mensagem é "assinada by SmartProv" e enviada via o sidecar Baileys
através do helper `_sidecar_post_silent` (mesma stack do resto do sistema).
Sem JWT — operação interna.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services.wa.sidecar import _sidecar_post_silent

log = logging.getLogger("treasury_receipts")


def _fmt_brl(v: float) -> str:
    s = f"{float(v or 0):.2f}".replace(".", ",")
    parts = s.split(",")
    parts[0] = re.sub(r"(\d)(?=(\d{3})+$)", r"\1.", parts[0])
    return "R$ " + ",".join(parts)


def _fmt_dt(iso: Optional[str]) -> str:
    if not iso:
        return "-"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return iso[:16]


def build_receipt_text(payment: Dict[str, Any]) -> str:
    """Comprovante texto formal — assinatura SmartProv obrigatória."""
    method = (payment.get("method") or "pix").upper()
    when = (payment.get("paid_at") or payment.get("sent_at")
            or payment.get("updated_at") or datetime.now(timezone.utc).isoformat())
    provider_id = (payment.get("provider_transfer_id")
                   or payment.get("provider_bill_id") or "-")
    lines = [
        "✅ *COMPROVANTE DE PAGAMENTO*",
        "",
        f"*Beneficiário:* {payment.get('payee_name') or '-'}",
        f"*CPF/CNPJ:* {payment.get('payee_document') or '-'}",
        f"*Valor:* {_fmt_brl(payment.get('amount_brl', 0))}",
        f"*Forma:* {method}",
        f"*Data/hora:* {_fmt_dt(when)}",
        f"*ID transação:* `{provider_id}`",
    ]
    if payment.get("description"):
        lines.append(f"*Descrição:* {payment['description']}")
    if payment.get("category"):
        lines.append(f"*Categoria:* {payment['category']}")
    lines.append("")
    lines.append("_Operação processada e auditada pela IA Tesoureira._")
    lines.append("─────────────────────")
    lines.append("*by SmartProv* — Tesouraria autônoma")
    return "\n".join(lines)


def _normalize_phone(raw: str) -> Optional[str]:
    """E.164 BR. Aceita '11999999999', '+5511999999999', '(11) 99999-9999'."""
    if not raw:
        return None
    digits = re.sub(r"\D+", "", raw)
    if not digits:
        return None
    if digits.startswith("55") and len(digits) >= 12:
        return digits
    if len(digits) in (10, 11):  # DDD + número
        return f"55{digits}"
    return digits


async def send_receipt_whatsapp(payment: Dict[str, Any], phone: str) -> Dict[str, Any]:
    """Envia comprovante texto via sidecar Baileys.

    Retorna {ok, message_id?, error?}. NUNCA levanta exceção.
    """
    norm = _normalize_phone(phone)
    if not norm:
        return {"ok": False, "error": "phone_invalid"}
    text = build_receipt_text(payment)
    try:
        out = await _sidecar_post_silent("/send", {"phone": norm, "text": text})
    except Exception as e:  # pragma: no cover
        log.warning("send_receipt_whatsapp falhou: %s", e)
        return {"ok": False, "error": str(e)}
    if not isinstance(out, dict):
        return {"ok": False, "error": "sidecar_unknown_response"}
    if out.get("ok"):
        return {"ok": True, "message_id": out.get("message_id"),
                "phone": norm, "text_preview": text[:160]}
    return {"ok": False, "error": out.get("error") or "sidecar_failed", "raw": out}
