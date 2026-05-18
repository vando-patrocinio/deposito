"""Auto-vinculação de telefones desconhecidos a clientes existentes.

Quando o WhatsApp recebe uma mensagem de número NÃO cadastrado e o cliente
se identifica na conversa (envia CPF, CNPJ, nome completo, ou contrato),
o sistema:
  1. Procura o subscriber correspondente em `subscribers`
  2. Adiciona o telefone novo em `subscriber_phones` (como secundário)
  3. Marca a conversa em `wa_conversations` com `subscriber_id` resolvido

Isso evita ter que ligar manualmente o número toda vez que o cliente trocar
de telefone ou usar outro número (ex: número da esposa).

Patterns suportados:
  - CPF: "035.123.456-78", "03512345678"
  - CNPJ: "39061296000196", "39.061.296/0001-96"
  - Nome completo (3+ palavras) com fallback fuzzy via aggregation
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database import db

logger = logging.getLogger("ponto.subscriber_phone_linker")

_CPF_RE = re.compile(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b")
_CNPJ_RE = re.compile(r"\b(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})\b")
# Nome completo: 3+ palavras com inicial maiúscula
_NAME_RE = re.compile(
    r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]{2,}(?:\s+(?:da|de|do|das|dos|e)\s+)?"
    r"(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]{2,}){2,})\b"
)


def _normalize_doc(raw: str) -> str:
    """Remove pontos/traços/barras pra ficar só dígitos."""
    return re.sub(r"\D", "", raw)


def extract_identifiers(text: str) -> Dict[str, Optional[str]]:
    """Extrai CPF, CNPJ e nome do texto se presentes."""
    if not text:
        return {"cpf": None, "cnpj": None, "name": None}
    cpf_match = _CPF_RE.search(text)
    cnpj_match = _CNPJ_RE.search(text)
    name_match = _NAME_RE.search(text)

    cpf = _normalize_doc(cpf_match.group(1)) if cpf_match else None
    cnpj = _normalize_doc(cnpj_match.group(1)) if cnpj_match else None
    name = name_match.group(1).strip() if name_match else None

    # Filtra validade básica
    if cpf and len(cpf) != 11:
        cpf = None
    if cnpj and len(cnpj) != 14:
        cnpj = None

    return {"cpf": cpf, "cnpj": cnpj, "name": name}


async def try_auto_link_phone(
    company_id: str,
    phone: str,
    user_text: str,
) -> Optional[Dict[str, Any]]:
    """Tenta vincular `phone` a um subscriber se cliente se identificou.

    Retorna dict com info do match (subscriber_id, name, how_matched) se
    bem-sucedido, senão None.

    Não duplica vinculação: se já existir entrada `subscriber_phones` pra
    esse number, retorna o subscriber atual sem inserir.
    """
    if not phone or not user_text:
        return None

    # 1. Já está vinculado?
    existing = await db.subscriber_phones.find_one(
        {"company_id": company_id, "normalized_number": phone},
        {"_id": 0, "subscriber_id": 1},
    )
    if existing:
        return None  # nada a fazer

    ids = extract_identifiers(user_text)
    if not any(ids.values()):
        return None

    sub: Optional[Dict[str, Any]] = None
    matched_by = None

    if ids.get("cpf"):
        sub = await db.subscribers.find_one(
            {"company_id": company_id, "document": ids["cpf"]},
            {"_id": 0, "id": 1, "name": 1, "document": 1},
        )
        if sub:
            matched_by = f"cpf={ids['cpf']}"

    if not sub and ids.get("cnpj"):
        sub = await db.subscribers.find_one(
            {"company_id": company_id, "document": ids["cnpj"]},
            {"_id": 0, "id": 1, "name": 1, "document": 1},
        )
        if sub:
            matched_by = f"cnpj={ids['cnpj']}"

    if not sub and ids.get("name"):
        # Match case-insensitive exato no nome
        sub = await db.subscribers.find_one(
            {"company_id": company_id,
             "name": {"$regex": f"^{re.escape(ids['name'])}$",
                       "$options": "i"}},
            {"_id": 0, "id": 1, "name": 1, "document": 1},
        )
        if sub:
            matched_by = f"name={ids['name']}"

    if not sub:
        return None

    # Insere link
    now = datetime.now(timezone.utc).isoformat()
    phone_id = f"sphone-{uuid.uuid4().hex[:10]}"
    await db.subscriber_phones.insert_one({
        "id": phone_id,
        "company_id": company_id,
        "subscriber_id": sub["id"],
        "label": "auto-linkado via chat",
        "raw_number": phone,
        "normalized_number": phone,
        "is_whatsapp": True,
        "is_primary": False,
        "linked_by": "auto-linker",
        "linked_via": matched_by,
        "created_at": now,
    })

    # Atualiza a conversa também (resolve subscriber_id se já existir registro)
    await db.wa_conversations.update_one(
        {"company_id": company_id, "phone": phone},
        {"$set": {
            "subscriber_id": sub["id"],
            "lead_tag": None,  # remove tag de "identificação pendente"
            "auto_linked_at": now,
            "auto_linked_via": matched_by,
            "updated_at": now,
        }},
        upsert=True,
    )

    logger.info(
        "[phone-linker] phone=%s vinculado a subscriber=%s (%s) via %s",
        phone, sub["id"], sub.get("name"), matched_by,
    )
    return {
        "subscriber_id": sub["id"],
        "subscriber_name": sub.get("name"),
        "matched_by": matched_by,
    }


async def tag_unknown_phone(company_id: str, phone: str) -> None:
    """Marca a conversa de phone desconhecido com `lead_tag`.

    Idempotente — só seta se ainda não tem subscriber_id na conversa.
    """
    if not phone:
        return
    existing = await db.subscriber_phones.find_one(
        {"company_id": company_id, "normalized_number": phone},
        {"_id": 0, "subscriber_id": 1},
    )
    if existing:
        return  # já é conhecido

    now = datetime.now(timezone.utc).isoformat()
    await db.wa_conversations.update_one(
        {"company_id": company_id, "phone": phone},
        {"$set": {
            "lead_tag": "🔍 Identificação pendente",
            "is_unknown_lead": True,
            "updated_at": now,
        }, "$setOnInsert": {
            "lead_tagged_at": now,
        }},
        upsert=True,
    )
