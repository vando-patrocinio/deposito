"""Detecção determinística de handoff entre agentes IA.

Quando uma conversa já tem agente vinculado (`routed_agent_id`) e o cliente
manda uma mensagem que CLARAMENTE pertence a OUTRA área, o LLM nem sempre
gera o marker `[ROTEAR_X]` — pode tentar resolver fora do escopo.

Este módulo expõe `detect_forced_handoff(current_agent_name, user_text)`
que retorna o nome do agente alvo se for um caso óbvio, ou None.

Usado no pipeline whatsapp_baileys.py para forçar handoff ANTES de invocar
a LLM (economiza tokens + corrige leak de escopo).

Extraído/criado em iter106.
"""
from __future__ import annotations

import re
from typing import Optional

# Padrões fortes que indicam troca de área. Cada conjunto exige UMA keyword
# inequívoca + ausência de keywords contraditórias.
_SUPORTE_STRONG = re.compile(
    r"\b("
    r"sem\s+(internet|net|sinal|conex[aã]o)|"
    r"internet\s+(caiu|n[aã]o\s+funciona|lenta|oscilando|oscilou|travando)|"
    r"sinal\s+(caiu|fraco|oscilou|sumiu)|"
    r"caiu\s+o\s+(sinal|net|internet)|"
    r"onu\s+(piscando|vermelho|apagada)|"
    r"led\s+(vermelho|apagado|piscando)|"
    r"modem\s+(travado|reiniciar)|"
    r"sem\s+conex[aã]o"
    r")\b",
    re.IGNORECASE,
)

_COBRANCA_STRONG = re.compile(
    r"\b("
    r"2\s*via\s+(do\s+)?boleto|"
    r"segunda\s+via|"
    r"manda(r)?\s+(o\s+)?(boleto|pix)|"
    r"pix\s+(da\s+)?fatura|"
    r"pagar\s+(a\s+)?fatura|"
    r"fatura\s+(em\s+)?atrasada?|"
    r"desbloque(io|ar)\s+por\s+pagamento|"
    r"vencimento\s+(da|do)\s+(fatura|boleto)"
    r")\b",
    re.IGNORECASE,
)

_VENDAS_STRONG = re.compile(
    r"\b("
    r"(quero|interesse|gostaria|tenho\s+interesse)\s+(em\s+)?(contratar|assinar|comprar)|"
    r"(quanto\s+custa|qual\s+(o\s+)?(pre[çc]o|valor))\s+(do|de)\s+plano|"
    r"plano\s+de\s+\d+\s*mega|"
    r"upgrade\s+(de|do)\s+plano|"
    r"trocar\s+(o\s+)?plano|"
    r"(quero|vou)\s+cancelar"  # retenção
    r")\b",
    re.IGNORECASE,
)

# Mapeamento agente alvo
_TARGET_PATTERNS = [
    ("Alvaro",   _SUPORTE_STRONG),
    ("Camila",   _COBRANCA_STRONG),
    ("Isabella", _VENDAS_STRONG),
]


def detect_forced_handoff(current_agent_name: Optional[str],
                            user_text: str,
                            recent_handoff: bool = False) -> Optional[str]:
    """Retorna o nome do agente alvo se a mensagem do cliente claramente
    pertence a outra área. Retorna None se:
      - texto vazio
      - o match é pro próprio agente atual
      - nenhum padrão forte casa
      - `recent_handoff=True` (anti-loop: conversa acabou de ser rerroteada)

    Conservador: prefere falso-negativo (deixa o LLM decidir) a
    falso-positivo (handoff errado).
    """
    if not user_text or len(user_text.strip()) < 5:
        return None
    if recent_handoff:
        # Anti-loop: se acabou de receber handoff, não força novo
        return None
    text = user_text.strip()
    current = (current_agent_name or "").lower()
    for target, pat in _TARGET_PATTERNS:
        if pat.search(text) and target.lower() != current:
            return target
    return None
