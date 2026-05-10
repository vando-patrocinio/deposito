"""Normalização de telefones brasileiros para vinculação assinante↔conversa.

Aceita qualquer formato (com/sem DDI, com/sem zero, com/sem máscara, sufixo
WhatsApp `@c.us`/`@s.whatsapp.net`) e retorna a forma canônica `5521998176526`.

Também produz variantes de busca para casar com cadastros antigos que
porventura tenham sido salvos sem DDI.

REGRA MÁXIMA: `link_phone_to_subscriber` é chamado a cada inbound + a cada
listagem de conversas — sempre que um telefone aparece sem `subscriber_id`,
o sistema tenta vincular novamente (caso o cliente tenha sido cadastrado
posteriormente, ele passa a ser identificado retroativamente).
"""
from __future__ import annotations

import re
from typing import List, Optional, Dict, Any


_WHATSAPP_SUFFIXES = ("@c.us", "@s.whatsapp.net", "@g.us", "@lid")


def normalize_brazilian_phone(input_value: str) -> str:
    """Converte qualquer formato BR para canônico `55<DDD><número>`.

    Regras:
    - Remove sufixo WhatsApp e tudo que não for dígito.
    - Remove zero inicial antes do DDD (021... → 21...).
    - Se começar com 55 e tiver tamanho compatível, mantém.
    - Se não começar com 55, adiciona.
    - Retorna string vazia se não for possível normalizar (telefone < 10 dígitos
      após DDD).
    """
    if not input_value:
        return ""
    s = str(input_value).strip().lower()
    for suf in _WHATSAPP_SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)]
    digits = re.sub(r"\D", "", s)
    if not digits:
        return ""

    # Remove zero inicial antes do DDD (ex.: 021... → 21...)
    if digits.startswith("0") and len(digits) >= 11:
        digits = digits.lstrip("0")

    # Se começa com 55 e tem ao menos 12 dígitos (55 + DDD 2 + 8 número), mantém.
    # Se não começa com 55 e tem 10 ou 11 dígitos (DDD + número), adiciona.
    if digits.startswith("55") and len(digits) >= 12:
        canonical = digits
    elif len(digits) in (10, 11):
        canonical = "55" + digits
    elif len(digits) >= 12:
        # já tem DDI mas não 55 — mantém como está
        canonical = digits
    else:
        return ""

    # Sanidade: total entre 12 e 13 dígitos esperado (55 + 10 ou 11)
    if not 12 <= len(canonical) <= 14:
        return ""
    return canonical


def get_phone_lookup_variants(input_value: str) -> List[str]:
    """Retorna a forma canônica + variantes para busca em registros antigos."""
    canonical = normalize_brazilian_phone(input_value)
    variants = set()
    if canonical:
        variants.add(canonical)
        # Sem DDI
        if canonical.startswith("55") and len(canonical) >= 12:
            variants.add(canonical[2:])
        # Com zero antes do DDD
        if canonical.startswith("55"):
            variants.add("0" + canonical[2:])
    # Mantém também o original (após strip de máscara) caso o cadastro antigo
    # esteja exatamente nesse formato.
    raw_digits = re.sub(r"\D", "", str(input_value or ""))
    if raw_digits:
        variants.add(raw_digits)
    return [v for v in variants if v]


async def link_phone_to_subscriber(
        phone: str, company_id: str) -> Optional[Dict[str, Any]]:
    """REGRA MÁXIMA: tenta vincular um telefone a um assinante cadastrado.

    Chamada por TODO inbound do WhatsApp (e por toda listagem de conversas
    para enriquecer registros antigos). Retorna `{subscriber_id, subscriber_name}`
    quando há match único, ou `None` quando não há match ou há conflito (que
    devem ser resolvidos manualmente na UI de Assinantes).

    Implementação delega para `find_subscriber_by_phone` em routes.subscribers
    (única fonte de verdade pra match).
    """
    # Import dentro da função para evitar ciclo (routes.subscribers importa daqui)
    from routes.subscribers import find_subscriber_by_phone
    try:
        result = await find_subscriber_by_phone(company_id, phone)
    except Exception:
        return None
    if not result or result.get("status") != "matched":
        return None
    sub = result.get("subscriber") or {}
    if not sub.get("id"):
        return None
    return {
        "subscriber_id": sub["id"],
        "subscriber_name": sub.get("name"),
        "branch": sub.get("branch"),
        "plan_name": sub.get("plan_name"),
        "status": sub.get("status"),
        "external_code": sub.get("external_code"),
    }
