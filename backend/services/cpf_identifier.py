"""CPF Identifier — busca o assinante por CPF quando não foi possível por telefone.

Fluxo (state machine simples por phone):
1. inbound chega → routes/whatsapp_baileys.py não acha subscriber por telefone
2. Salva em wa_identification: {phone, state: 'awaiting_cpf', tries: 0}
3. IA pede CPF ao cliente (orientação injetada no system_prompt)
4. próxima inbound: detecta CPF na mensagem (regex 11 dígitos)
5. valida no DB (subscribers.cpf == digits ou subscribers.documents.cpf)
6. se acha → atualiza wa_conversations.subscriber_id, marca state='identified'
   + adiciona telefone novo na lista do subscriber (com flag added_via='ai_cpf')
7. se não acha → tries++, se >3 marca state='failed' e libera handover humano
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import re
from typing import Any, Dict, Optional, Tuple

from core import now_iso
from database import db

logger = logging.getLogger("cpf_identifier")

CPF_REGEX = re.compile(r"(?<!\d)(\d{3}[.\s-]?\d{3}[.\s-]?\d{3}[.\s-]?\d{2})(?!\d)")
MAX_TRIES = 3


def extract_cpf(text: str) -> Optional[str]:
    """Extrai CPF de qualquer formato (com ou sem pontos/traços). Retorna 11 dígitos.
    NÃO faz validação dos dígitos verificadores — apenas extração."""
    if not text:
        return None
    m = CPF_REGEX.search(text)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    if len(digits) != 11:
        return None
    return digits


def validate_cpf(digits: str) -> bool:
    """Algoritmo oficial de validação de CPF (dígitos verificadores)."""
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    try:
        nums = [int(d) for d in digits]
        # Primeiro dígito verificador
        s = sum(nums[i] * (10 - i) for i in range(9))
        d1 = (s * 10 % 11) % 10
        if d1 != nums[9]:
            return False
        # Segundo dígito verificador
        s = sum(nums[i] * (11 - i) for i in range(10))
        d2 = (s * 10 % 11) % 10
        return d2 == nums[10]
    except Exception:
        return False


async def _normalize_phone(p: str) -> str:
    return "".join(c for c in (p or "") if c.isdigit())


async def find_subscriber_by_cpf(company_id: str, cpf_digits: str) -> Optional[Dict[str, Any]]:
    """Busca assinante por CPF. Verifica vários campos onde o CPF pode estar."""
    if not cpf_digits or len(cpf_digits) != 11:
        return None
    # Variações comuns de armazenamento
    cpf_formatted = f"{cpf_digits[:3]}.{cpf_digits[3:6]}.{cpf_digits[6:9]}-{cpf_digits[9:]}"
    queries = [
        {"company_id": company_id, "cpf": cpf_digits},
        {"company_id": company_id, "cpf": cpf_formatted},
        {"company_id": company_id, "documents.cpf": cpf_digits},
        {"company_id": company_id, "documents.cpf": cpf_formatted},
        {"company_id": company_id, "tax_id": cpf_digits},
        {"company_id": company_id, "tax_id": cpf_formatted},
    ]
    for q in queries:
        sub = await db.subscribers.find_one(q, {"_id": 0})
        if sub:
            return sub
    return None


async def get_or_create_id_state(company_id: str, phone: str) -> Dict[str, Any]:
    """Estado da máquina de identificação para um phone específico."""
    ph = await _normalize_phone(phone)
    doc = await db.wa_identification.find_one(
        {"company_id": company_id, "phone": ph}, {"_id": 0}
    )
    if not doc:
        doc = {
            "company_id": company_id,
            "phone": ph,
            "state": "awaiting_cpf",
            "tries": 0,
            "created_at": now_iso(),
        }
        await db.wa_identification.insert_one({**doc})
    return doc


async def reset_state(company_id: str, phone: str) -> None:
    ph = await _normalize_phone(phone)
    await db.wa_identification.delete_one(
        {"company_id": company_id, "phone": ph}
    )


async def handle_unidentified_inbound(
    company_id: str, phone: str, user_text: str,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Processa uma inbound de um phone que não tem subscriber vinculado.

    Retorna (subscriber_or_None, instruction_for_ai_dict).

    instruction_for_ai_dict tem chave 'directive' (texto pra injetar no
    system_prompt da IA) e 'state' atual.

    Lógica:
    - Se a mensagem contém um CPF válido → tenta achar assinante
      - Se achar: linka o telefone ao subscriber e instrui a IA a saudar
        pelo nome (confirmação implícita)
      - Se não achar: incrementa tries. Se atingiu MAX_TRIES, marca como
        falha e instrui a IA a oferecer handover humano
    - Se NÃO contém CPF e o estado é 'awaiting_cpf' → instrui a IA a pedir CPF
    - Estado inicial (sem doc no DB) → cria 'awaiting_cpf' e pede CPF
    """
    ph = await _normalize_phone(phone)
    state = await get_or_create_id_state(company_id, ph)

    # Já estava em falha? Mantém o estado, só sinaliza
    if state.get("state") == "failed":
        return None, {
            "state": "failed",
            "directive": (
                "=== CLIENTE NÃO IDENTIFICADO (após várias tentativas) ===\n"
                "Este número não está vinculado a nenhum cliente e o CPF "
                "informado não foi encontrado em nossa base. NÃO insista mais "
                "no CPF. Ofereça transferir para um atendente humano que pode "
                "verificar manualmente, ou pergunte se a pessoa quer abrir um "
                "novo cadastro (venda nova)."
            ),
        }

    # Extrai CPF da mensagem atual
    cpf = extract_cpf(user_text)
    if cpf:
        is_valid = validate_cpf(cpf)
        if not is_valid:
            # CPF mal formado/inválido
            new_tries = state.get("tries", 0) + 1
            await db.wa_identification.update_one(
                {"company_id": company_id, "phone": ph},
                {"$set": {"tries": new_tries, "last_attempt_at": now_iso(),
                            "last_cpf_invalid": cpf}},
            )
            if new_tries >= MAX_TRIES:
                await db.wa_identification.update_one(
                    {"company_id": company_id, "phone": ph},
                    {"$set": {"state": "failed", "failed_at": now_iso()}},
                )
                return None, {
                    "state": "failed",
                    "directive": (
                        "=== FALHA NA IDENTIFICAÇÃO ===\n"
                        "CPF informado não passa na validação após várias "
                        "tentativas. Ofereça transferir para atendente humano "
                        "que pode verificar pessoalmente."
                    ),
                }
            return None, {
                "state": "awaiting_cpf",
                "directive": (
                    "=== CPF INVÁLIDO ===\n"
                    "O CPF informado pelo cliente está mal formado (dígitos "
                    "verificadores não conferem). Peça GENTILMENTE que ele "
                    "confira e envie novamente, em qualquer formato "
                    "(123.456.789-00 ou só números). Não seja burocrático."
                ),
            }
        # CPF válido pelo algoritmo — busca no DB
        subscriber = await find_subscriber_by_cpf(company_id, cpf)
        if subscriber:
            # ENCONTROU! Vincula telefone + atualiza estado
            await _link_phone_to_subscriber(company_id, subscriber, ph)
            await db.wa_identification.update_one(
                {"company_id": company_id, "phone": ph},
                {"$set": {
                    "state": "identified",
                    "identified_subscriber_id": subscriber.get("id"),
                    "identified_at": now_iso(),
                    "matched_cpf": cpf,
                }},
            )
            # Atualiza conversa
            await db.wa_conversations.update_one(
                {"company_id": company_id, "phone": ph},
                {"$set": {"subscriber_id": subscriber.get("id")}},
                upsert=True,
            )
            logger.info("[cpf-identifier] phone=%s vinculado ao subscriber=%s via CPF",
                         ph, subscriber.get("id"))
            return subscriber, {
                "state": "identified",
                "directive": (
                    "=== CLIENTE IDENTIFICADO POR CPF (acabou de confirmar) ===\n"
                    f"Você acabou de validar a identidade do cliente "
                    f"**{subscriber.get('name')}** (plano: "
                    f"{subscriber.get('plan_name') or '—'}). Saúde pelo "
                    "PRIMEIRO NOME, confirme que está tudo certo com a "
                    "identificação, e pergunte como pode ajudar. NÃO peça CPF "
                    "de novo."
                ),
            }
        # CPF válido MAS não achado — pode ser cliente novo ou erro de digitação
        new_tries = state.get("tries", 0) + 1
        await db.wa_identification.update_one(
            {"company_id": company_id, "phone": ph},
            {"$set": {"tries": new_tries, "last_attempt_at": now_iso(),
                        "last_cpf_not_found": cpf}},
        )
        if new_tries >= MAX_TRIES:
            await db.wa_identification.update_one(
                {"company_id": company_id, "phone": ph},
                {"$set": {"state": "failed", "failed_at": now_iso()}},
            )
            return None, {
                "state": "failed",
                "directive": (
                    "=== CPF NÃO ENCONTRADO NA BASE ===\n"
                    "O CPF informado é válido mas NÃO está cadastrado em "
                    "nossa base. Pergunte: 'Você já é nosso cliente?' Se for "
                    "venda nova, colete endereço e ofereça verificar cobertura. "
                    "Se diz que é cliente antigo, ofereça transferir para "
                    "atendente humano."
                ),
            }
        return None, {
            "state": "awaiting_cpf",
            "directive": (
                "=== CPF VÁLIDO MAS NÃO ENCONTRADO ===\n"
                "O CPF informado é válido pelos dígitos, mas não consta na "
                "nossa base. Peça GENTILMENTE para o cliente conferir se "
                "digitou certo, ou perguntar se quem fala é o titular "
                "do contrato (pode estar usando o telefone do cônjuge/filho)."
            ),
        }

    # Não há CPF na mensagem
    # Se ele acabou de chegar (1ª inbound não-identificada), pede CPF
    return None, {
        "state": "awaiting_cpf",
        "directive": (
            "=== IDENTIFICAÇÃO POR CPF NECESSÁRIA ===\n"
            "Este telefone NÃO está vinculado a nenhum cliente cadastrado em "
            "nossa base. Antes de responder qualquer dúvida ou solicitação, "
            "peça GENTILMENTE o CPF do TITULAR do contrato para você poder "
            "ajudar com segurança. Exemplo: 'Pra te atender melhor, pode me "
            "passar o CPF do titular do contrato? Pode ser só os números, "
            "sem pontos.' NÃO responda dúvidas sobre fatura/plano/conexão "
            "antes de validar o CPF. Se o cliente disser que é venda nova, "
            "aí sim siga o fluxo de vendas (não precisa de CPF agora)."
        ),
    }


async def _link_phone_to_subscriber(company_id: str, subscriber: Dict[str, Any],
                                      phone: str) -> None:
    """Adiciona o telefone à lista do subscriber se ainda não estiver lá.

    Marca com flag added_via='ai_cpf_validation' para auditoria.

    IMPORTANTE: também cria entry em `subscriber_phones` (collection separada
    usada pelo lookup phone→subscriber em routes/subscribers.find_subscriber_by_phone).
    Sem isso, próximas mensagens deste número não seriam vinculadas
    automaticamente — o cliente teria que mandar CPF de novo!
    """
    ph = await _normalize_phone(phone)
    if not ph:
        return
    existing_phones = subscriber.get("phones") or []
    already_in_embedded = False
    for p in existing_phones:
        if isinstance(p, dict):
            if "".join(c for c in (p.get("number") or "") if c.isdigit()) == ph:
                already_in_embedded = True
                break
        else:
            if "".join(c for c in str(p) if c.isdigit()) == ph:
                already_in_embedded = True
                break
    if not already_in_embedded:
        new_phone = {
            "number": phone,
            "kind": "mobile",
            "added_via": "ai_cpf_validation",
            "added_at": now_iso(),
        }
        await db.subscribers.update_one(
            {"id": subscriber["id"]},
            {"$push": {"phones": new_phone}},
        )
        logger.info(
            "[cpf-identifier] telefone %s adicionado ao subscriber %s",
            phone, subscriber.get("id"),
        )

    # 2) ALSO insert em subscriber_phones (collection separada usada pelo
    # phone→subscriber lookup). Sem isso o próximo inbound não vincula!
    import uuid as _uuid
    existing_sp = await db.subscriber_phones.find_one(
        {"company_id": company_id, "normalized_number": ph,
         "subscriber_id": subscriber["id"]},
        {"_id": 0, "id": 1},
    )
    if not existing_sp:
        await db.subscriber_phones.insert_one({
            "id": f"sphone-{_uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "subscriber_id": subscriber["id"],
            "label": "ai_cpf_validation",
            "raw_number": phone,
            "normalized_number": ph,
            "is_whatsapp": True,
            "is_primary": False,
            "created_at": now_iso(),
        })
        logger.info(
            "[cpf-identifier] subscriber_phones criado para %s → %s",
            ph, subscriber.get("id"),
        )
