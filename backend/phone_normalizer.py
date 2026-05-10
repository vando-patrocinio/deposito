"""Normalização de telefones brasileiros para vinculação assinante↔conversa.

Aceita qualquer formato (com/sem DDI, com/sem zero, com/sem máscara, sufixo
WhatsApp `@c.us`/`@s.whatsapp.net`) e retorna a forma canônica `5521998176526`.

Também produz variantes de busca para casar com cadastros antigos que
porventura tenham sido salvos sem DDI.
"""
from __future__ import annotations

import re
from typing import List


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
