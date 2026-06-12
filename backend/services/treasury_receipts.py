"""treasury_receipts — gera mensagem de comprovante e dispara WhatsApp.

iter239: Suporta TEMPLATE customizado por empresa + anexo PDF.
- Template salvo em db.treasury_receipt_templates (singleton por company_id)
- Variáveis suportadas: {payee_name} {document} {amount} {method} {datetime}
  {transaction_id} {description} {category} {signature}
- Anexo PDF (b64) é enviado junto pelo /send-document do sidecar.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database import db
from services.wa.sidecar import _sidecar_post_silent

log = logging.getLogger("treasury_receipts")


DEFAULT_TEMPLATE = """✅ *COMPROVANTE DE PAGAMENTO*

*Beneficiário:* {payee_name}
*CPF/CNPJ:* {document}
*Valor:* {amount}
*Forma:* {method}
*Data/hora:* {datetime}
*ID transação:* `{transaction_id}`
*Descrição:* {description}

_Operação processada e auditada pela IA Tesoureira._
─────────────────────
{signature}"""

DEFAULT_SIGNATURE = "*by SmartProv* — Tesouraria autônoma"


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


async def get_template(company_id: str) -> Dict[str, Any]:
    """Retorna template salvo ou default."""
    doc = await db.treasury_receipt_templates.find_one(
        {"company_id": company_id}, {"_id": 0})
    if doc:
        return doc
    return {
        "company_id": company_id,
        "template_text": DEFAULT_TEMPLATE,
        "signature": DEFAULT_SIGNATURE,
        "attach_pdf": False,
        "pdf_filename": None,
        "pdf_b64": None,
    }


def render_template(payment: Dict[str, Any],
                    template: Dict[str, Any]) -> str:
    text = template.get("template_text") or DEFAULT_TEMPLATE
    signature = template.get("signature") or DEFAULT_SIGNATURE
    method = (payment.get("method") or "pix").upper()
    when = (payment.get("paid_at") or payment.get("sent_at")
            or payment.get("updated_at") or datetime.now(timezone.utc).isoformat())
    provider_id = (payment.get("provider_transfer_id")
                   or payment.get("provider_bill_id") or "-")
    placeholders = {
        "payee_name": payment.get("payee_name") or "-",
        "document": payment.get("payee_document") or "-",
        "amount": _fmt_brl(payment.get("amount_brl", 0)),
        "method": method,
        "datetime": _fmt_dt(when),
        "transaction_id": provider_id,
        "description": payment.get("description") or "-",
        "category": payment.get("category") or "-",
        "signature": signature,
    }
    out = text
    for k, v in placeholders.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def build_receipt_text(payment: Dict[str, Any],
                        template: Optional[Dict[str, Any]] = None) -> str:
    """Compatibilidade: aceita chamada sem template (usa default)."""
    if template is None:
        template = {
            "template_text": DEFAULT_TEMPLATE,
            "signature": DEFAULT_SIGNATURE,
        }
    return render_template(payment, template)


def _normalize_phone(raw: str) -> Optional[str]:
    if not raw:
        return None
    digits = re.sub(r"\D+", "", raw)
    if not digits:
        return None
    if digits.startswith("55") and len(digits) >= 12:
        return digits
    if len(digits) in (10, 11):
        return f"55{digits}"
    return digits


async def send_receipt_whatsapp(payment: Dict[str, Any],
                                 phone: str) -> Dict[str, Any]:
    """Envia comprovante texto + (opcional) anexo PDF do template.

    Retorna {ok, message_id?, document_sent?, error?}. NUNCA levanta.
    """
    norm = _normalize_phone(phone)
    if not norm:
        return {"ok": False, "error": "phone_invalid"}
    cid = payment.get("company_id")
    template = await get_template(cid) if cid else {
        "template_text": DEFAULT_TEMPLATE, "signature": DEFAULT_SIGNATURE,
    }
    text = render_template(payment, template)
    out_text: Dict[str, Any] = {}
    try:
        out_text = await _sidecar_post_silent("/send", {"phone": norm, "text": text})
    except Exception as e:  # pragma: no cover
        log.warning("send text falhou: %s", e)
        return {"ok": False, "error": str(e)}
    if not isinstance(out_text, dict) or not out_text.get("ok"):
        return {"ok": False, "error": (out_text or {}).get("error")
                or "sidecar_failed", "raw": out_text}

    result: Dict[str, Any] = {
        "ok": True,
        "message_id": out_text.get("message_id"),
        "phone": norm,
        "text_preview": text[:160],
        "document_sent": False,
    }

    # Anexo PDF
    if template.get("attach_pdf") and template.get("pdf_b64"):
        try:
            doc_out = await _sidecar_post_silent("/send-document", {
                "phone": norm,
                "document_b64": template["pdf_b64"],
                "filename": template.get("pdf_filename") or "comprovante.pdf",
                "mimetype": "application/pdf",
            })
            result["document_sent"] = bool((doc_out or {}).get("ok"))
            if not result["document_sent"]:
                result["document_error"] = (doc_out or {}).get("error")
        except Exception as e:
            log.warning("send_document falhou: %s", e)
            result["document_error"] = str(e)
    return result
