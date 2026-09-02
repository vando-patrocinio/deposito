"""Resolução de destino WhatsApp para contatos com número oculto (LID).

Quando o cliente ativa privacidade no WhatsApp, o Baileys entrega o remetente
como `<lid>@lid` e o número real fica indisponível. Nesses casos o `phone`
gravado na conversa é o próprio LID — enviar para `<lid>@s.whatsapp.net`
resulta em mensagem não entregue. O alvo correto é `<lid>@lid`.
"""
import re
from typing import Optional

from database import db


def lid_jid(lid: str) -> str:
    digits = re.sub(r"\D", "", str(lid))
    return f"{digits}@lid"


async def resolve_send_target(company_id: str, phone: Optional[str]) -> str:
    """Devolve o alvo de envio para um telefone de conversa.

    - contato normal        → dígitos do telefone
    - contato com LID       → `<lid>@lid`
    """
    raw = str(phone or "")
    if "@" in raw:
        return raw
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return raw
    conv = await db.wa_conversations.find_one(
        {"company_id": company_id, "phone": digits},
        {"_id": 0, "phone_is_lid": 1, "lid": 1},
    )
    if conv and conv.get("phone_is_lid") and conv.get("lid"):
        return lid_jid(conv["lid"])
    return digits
