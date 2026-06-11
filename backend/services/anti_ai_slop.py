"""ANTI-AI-SLOP — reescritor mecânico dos 13 vícios que denunciam IA.

Regras impostas pelo CTO:
  1. Narração de trabalho ("Verifiquei", "Consultei", "Localizei", "Analisei")
  2. Confirmações vazias ("Entendi", "Compreendo", "Perfeito", "Claro")
  3. Explicação excessiva (frases >40 palavras com "será encaminhada")
  4. Manual de instruções ("Para prosseguir, será necessário")
  5. Repetir o nome (já tratado pelo bubble_splitter)
  6. Repetir pergunta do cliente ("Entendo que você está sem internet")
  7. Frases corporativas ("Agradecemos o contato", "Sua satisfação é...")
  8. Pedir info que já tem (delegado ao anti_cpf_guardian)
  9. Excessivamente educada ("Peço gentilmente que aguarde")
 10. Empatia genérica ("Entendo sua frustração", "Lamento o ocorrido")
 11. Mesmo formato sempre (problema/explicação/conclusão) — não dá pra
     normatizar mecanicamente, mas o prompt cobra variação
 12. Parecer inteligente ("Após análise aprofundada do cenário")
 13. Lista negra de frases proibidas

Filosofia da regra única: ENTREGUE A RESPOSTA. Depois explique se preciso.
Pare de narrar que está trabalhando.
"""
from __future__ import annotations

import logging
import re
from typing import List, Tuple

log = logging.getLogger("ponto.anti_ai_slop")


# ════════════════════════════════════════════════════════════════════
# REGRA 1+2+10+12 — Aberturas/narrações descartáveis
# Removidas se aparecem no INÍCIO da frase ou bolha.
# ════════════════════════════════════════════════════════════════════
_OPENER_DROP = [
    # confirmações vazias
    r"entendi[!.,]?",
    r"compreendo[!.,]?",
    r"perfeito[!.,]?",
    r"claro[!.,]?",
    r"certo[!.,]?",
    r"sem problemas?[!.,]?",
    r"sem problema[!.,]?",
    r"posso ajudar[!.,]?",
    r"estou aqui (?:para|pra) ajudar[!.,]?",
    # narração de trabalho
    r"verifiquei (?:aqui|seu cadastro|o sistema)?[!.,]?",
    r"consultei (?:aqui|o sistema|seu cadastro)?[!.,]?",
    r"analisei (?:as informaç[õo]es?|aqui)?[!.,]?",
    r"localizei (?:seu cadastro|aqui)?[!.,]?",
    r"identifiquei (?:aqui|seu cadastro)?[!.,]?",
    # parecer inteligente — só a oração introdutória, NÃO a principal
    r"ap[óo]s an[áa]lise (?:aprofundada|detalhada)(?:[^,\.\!\?]*),\s*",
    # corporativas
    r"agradecemos o (?:seu )?contato[!.,]?",
    r"estamos [àa] disposi[çc][ãa]o[!.,]?",
    # entendo+rephrase (regra 6)
    r"entendo que voc[êe] (?:est[áa]|tem|n[ãa]o tem)[^\.\!\?]*[\.\!\?]?",
    r"compreendo que voc[êe] (?:est[áa]|tem|n[ãa]o tem)[^\.\!\?]*[\.\!\?]?",
    # empatia genérica (regra 10)
    r"entendo sua frustra[çc][ãa]o[!.,]?",
    r"compreendo sua insatisfa[çc][ãa]o[!.,]?",
    r"lamento o ocorrido[!.,]?",
    r"sentimos muito (?:pelo|pela) (?:transtorno|inconv[êe]ni[êe]ncia)[!.,]?",
]

_OPENER_RX = [
    re.compile(rf"(?:^|[\.\!\?]\s+){p}\s*", re.IGNORECASE)
    for p in _OPENER_DROP
]

# ════════════════════════════════════════════════════════════════════
# REGRA 4 — "Para prosseguir, será necessário" → "Preciso de"
# ════════════════════════════════════════════════════════════════════
_REWRITES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"para prosseguir(?:\s+com\s+sua\s+solicita[çc][ãa]o)?,?\s+ser[áa] necess[áa]rio (?:realizar os seguintes procedimentos\.?)?",
                re.IGNORECASE), "Preciso de"),
    (re.compile(r"sua solicita[çc][ãa]o foi recebida(?:\s+e\s+ser[áa]\s+encaminhada(?:[^\.\!\?]*))?\.?",
                re.IGNORECASE), "Abri o chamado."),
    (re.compile(r"a equipe respons[áa]vel ir[áa] analisar[^\.\!\?]*\.?",
                re.IGNORECASE), "A equipe vai analisar e retornar."),
    # excessivamente educadas: substitui pela versão curta humana
    (re.compile(
        r"pe[çc]o gentilmente que aguarde(?:\s+mais)?\s+alguns\s+instantes"
        r"(?:\s+enquanto\s+[^\.\!\?]*)?[\.\!\?]?",
        re.IGNORECASE), "Só um instante."),
    (re.compile(
        r"pe[çc]o (?:apenas |que )?(?:aguarde|paci[êe]ncia)[^\.\!\?]*[\.\!\?]?",
        re.IGNORECASE), "Só um instante."),
    # corporativa de satisfação — frase inteira (em qualquer posição)
    (re.compile(
        r"sua satisfa[çc][ãa]o [ée] muito importante(?:\s+para n[óo]s)?[!.,\s]*",
        re.IGNORECASE), ""),
    (re.compile(r"para melhor atend[êe]-lo[!.,]?", re.IGNORECASE), ""),
    (re.compile(r"pe[çc]o que informe", re.IGNORECASE), "Me diga"),
]


# ════════════════════════════════════════════════════════════════════
# REGRA 13 — Lista negra (frases que aparecem soltas)
# Removidas COMPLETAMENTE (a frase inteira que contém).
# ════════════════════════════════════════════════════════════════════
_BLACKLIST_RX = re.compile(
    r"(entendo sua solicita[çc][ãa]o|"
    r"compreendo sua preocupa[çc][ãa]o|"
    r"como posso (?:ajudar|te ajudar)\??|"
    r"em que posso (?:ajudar|te ajudar)\??)",
    re.IGNORECASE)


def _strip_openers(text: str) -> str:
    """Remove aberturas descartáveis no início de cada frase."""
    out = text
    for rx in _OPENER_RX:
        out = rx.sub(" ", out)
    return out


def _apply_rewrites(text: str) -> str:
    for rx, repl in _REWRITES:
        text = rx.sub(repl, text)
    return text


def _drop_blacklist_sentences(text: str) -> str:
    """Remove a frase inteira que contém uma expressão proibida."""
    parts: List[str] = []
    for sent in re.split(r"(?<=[\.\!\?])\s+", text):
        if _BLACKLIST_RX.search(sent or ""):
            continue
        parts.append(sent)
    return " ".join(parts)


def _normalize_whitespace(text: str) -> str:
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([\.\!\?,])", r"\1", text)
    text = re.sub(r"^[\s,\.]+", "", text)
    return text.strip()


def _capitalize_first(text: str) -> str:
    if not text:
        return text
    # primeira letra alfabética sobe pra maiúscula
    for i, ch in enumerate(text):
        if ch.isalpha():
            return text[:i] + ch.upper() + text[i+1:]
    return text


def deslop(text: str) -> str:
    """Pipeline anti-IA-slop: aplica todas as regras em ordem.

    Idempotente: pode rodar várias vezes sem destruir frases válidas.
    """
    if not text or len(text) < 4:
        return text
    out = text
    out = _strip_openers(out)
    out = _apply_rewrites(out)
    out = _drop_blacklist_sentences(out)
    out = _normalize_whitespace(out)
    out = _capitalize_first(out)
    return out


def detect_slop(text: str) -> List[str]:
    """Lista todas as violações encontradas (sem reescrever).
    Útil para painel de qualidade."""
    if not text:
        return []
    violations: List[str] = []
    for rx in _OPENER_RX:
        m = rx.search(text)
        if m:
            violations.append(m.group(0).strip()[:60])
    for rx, _ in _REWRITES:
        if rx.search(text):
            violations.append(rx.pattern[:60])
    if _BLACKLIST_RX.search(text):
        m = _BLACKLIST_RX.search(text)
        violations.append(f"blacklist:{m.group(0)}")
    return violations
