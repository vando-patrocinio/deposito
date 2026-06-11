"""Detecção de conclusão de venda no WhatsApp.

Quando a Isabella encerra uma venda, o backend muda o status da
conversa e dispara handoff pro humano para validar/confirmar.

Extraído de routes/whatsapp_baileys.py em iter106 (refactor).
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "vendas-team",
    "domain": "comercial",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import re

_SALES_DONE_PATTERNS = [
    # frases típicas que a Isabella usa ao fechar uma venda
    r"vou\s+conduzir\s+(?:a|o)\s+valida",
    r"vou\s+conduzir\s+(?:a|o)\s+restante",
    r"obrigad[oa]\s+por\s+escolher",
    r"agradeço\s+(?:a\s+)?(?:sua\s+)?confianç",
    r"ficamos\s+(?:muito\s+)?felizes\s+(?:por|em)",
    r"sua\s+(?:contratação|instalação)\s+(?:foi\s+)?(?:registrada|confirmada|agendada)",
    r"protocolo\s+de\s+contrataç",
    r"contrataç[ãa]o\s+(?:foi\s+)?(?:concluída|finalizada|registrada)",
    r"(?:proposta|pedido)\s+(?:foi\s+)?(?:registrad[oa]|enviad[oa])",
    # combinação: "concluído" perto de palavras de venda
    r"conclu[íi]d[oa]\s*[!.,]?.*(?:valida|atend|equipe|t[ée]cnico)",
]

_SALES_DONE_RE = re.compile(
    "|".join(f"(?:{p})" for p in _SALES_DONE_PATTERNS),
    re.IGNORECASE,
)


def is_sales_completion(text: str) -> bool:
    """Detecta se o texto da Isabella encerra uma venda. Conservador: só
    retorna True quando o padrão é claro de handoff/finalização — evita
    falsos positivos como "obrigada pela mensagem" no meio da conversa.
    """
    if not text or len(text) < 15:
        return False
    return bool(_SALES_DONE_RE.search(text))
