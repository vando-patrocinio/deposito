"""BUBBLE SPLITTER — quebra resposta em bolhas de WhatsApp (≤180 chars).

O LLM ignora o "MÁX 180 chars" do prompt e despeja respostas de 300+
chars em uma única bolha com 2-3 perguntas no mesmo turno.

Esta camada mecânica corrige:
  • Hard limit de 180 chars por bolha
  • Quebra em pontuação natural (. ! ? \n)
  • Detecta e separa múltiplas perguntas (1 pergunta por bolha)
  • Remove emojis duplicados, escape de "Pamela," repetido
  • Hard cap: máx 3 bolhas por turn (evita inundação)
  • Cap absoluto: cada bolha 180 chars
"""
from __future__ import annotations

import re
from typing import List

MAX_BUBBLE_CHARS = 180
MAX_BUBBLES = 3
# Símbolos que sinalizam quebra natural
_SENT_RX = re.compile(r"(?<=[\.!\?…])\s+(?=[A-ZÁÉÍÓÚÂÊÔÇ0-9])")
_NL_RX = re.compile(r"\n+")
_TRIPLE_SPACE = re.compile(r"\s{2,}")
# Emojis comuns que LLM repete (😊🚀✨🎉)
_EMOJI_DUP = re.compile(r"([\U0001F600-\U0001F9FF\u2600-\u27BF])\1+")
# Greeting saturation ("Oi Pamela! Pamela, ... Pamela ...")
_NAME_GREETING_RX = re.compile(
    r"^(oi|olá|ola|opa)\s+([A-ZÁÉÍÓÚ][\w]+)[!,.\s]+", re.IGNORECASE)


def _clean(text: str) -> str:
    text = (text or "").strip()
    text = _NL_RX.sub("\n", text)
    text = _EMOJI_DUP.sub(r"\1", text)
    text = _TRIPLE_SPACE.sub(" ", text)
    return text.strip()


def _split_sentences(text: str) -> List[str]:
    """Quebra em frases preservando pontuação."""
    parts: List[str] = []
    for chunk in _NL_RX.split(text):
        for sent in _SENT_RX.split(chunk):
            sent = sent.strip()
            if sent:
                parts.append(sent)
    return parts


def _pack_into_bubbles(sentences: List[str]) -> List[str]:
    """Agrega frases em bolhas respeitando MAX_BUBBLE_CHARS.

    Estilo humano: 1 frase = 1 bolha quando a frase tem entidade própria
    (saudação, pergunta, declaração). Só agrupa frases curtas adjacentes.
    """
    bubbles: List[str] = []
    buf = ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        # Frase isolada > 180 → hard split por palavras
        if len(s) > MAX_BUBBLE_CHARS:
            if buf:
                bubbles.append(buf)
                buf = ""
            for piece in _hard_word_split(s, MAX_BUBBLE_CHARS):
                bubbles.append(piece)
            continue
        # Quebra natural: pergunta SEMPRE em bolha própria (estilo humano)
        is_question = s.rstrip().endswith("?")
        # Saudação curta também (Oi/Olá/Opa + nome)
        is_greeting = bool(_NAME_GREETING_RX.match(s))
        # Frase muito curta (<50c) pode acompanhar próxima
        is_tiny = len(s) < 50 and not is_question and not is_greeting

        if is_question or is_greeting:
            if buf:
                bubbles.append(buf)
                buf = ""
            bubbles.append(s)
            continue
        if is_tiny:
            candidate = (buf + " " + s).strip() if buf else s
            if len(candidate) <= MAX_BUBBLE_CHARS:
                buf = candidate
                continue
        # Frase normal (50-180c)
        if buf:
            bubbles.append(buf)
        buf = s
    if buf:
        bubbles.append(buf)
    return bubbles


def _hard_word_split(s: str, limit: int) -> List[str]:
    """Quebra frase longa em pedaços por palavras."""
    words = s.split()
    out: List[str] = []
    cur = ""
    for w in words:
        candidate = (cur + " " + w).strip() if cur else w
        if len(candidate) <= limit:
            cur = candidate
        else:
            if cur:
                out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return out


def _suppress_repeated_name(bubbles: List[str]) -> List[str]:
    """Garante que o nome do cliente apareça no máx UMA vez total.

    Heurística: scaneia todas as bolhas, identifica o primeiro nome
    próprio que aparece como vocativo (", Nome!" / "Nome,") e remove
    todas as ocorrências subsequentes.
    """
    # Stopwords (palavras capitalizadas que NÃO são nome próprio)
    _NOT_NAMES = {
        "Oi", "Olá", "Ola", "Opa", "Bom", "Boa", "Perfeito", "Beleza",
        "Show", "Top", "Legal", "Massa", "Certo", "Ok", "OK", "Sim",
        "Não", "Nao", "Claro", "Combinado", "Pronto", "Entendi",
        "Combinou", "Fechou", "Maravilha", "Excelente", "Ótimo", "Otimo",
        "Vou", "Vamos", "Mas", "Vi", "Se", "É", "Você", "Voce",
    }
    candidate_rx = re.compile(
        r"(?:[,!]\s+|^)([A-ZÁÉÍÓÚÂÊÔÇ][a-záéíóúâêôç]{2,15})(?=[,!\.\s])")
    captured: str = ""
    for b in bubbles:
        for m in candidate_rx.finditer(b):
            name = m.group(1)
            if name not in _NOT_NAMES:
                captured = name
                break
        if captured:
            break
    if not captured:
        return [b.strip() for b in bubbles if b.strip()]

    out: List[str] = []
    name_used = False
    for b in bubbles:
        if name_used:
            patterns = [
                rf",?\s*{re.escape(captured)}[!,.]\s*",
                rf"^{re.escape(captured)}[,!.]\s+",
                rf"\s+{re.escape(captured)}\b[!,.]?",
            ]
            for p in patterns:
                b = re.sub(p, " ", b, flags=re.IGNORECASE)
            b = _TRIPLE_SPACE.sub(" ", b).strip()
            b = re.sub(r"^[,\s]+", "", b)
        else:
            if captured.lower() in b.lower():
                name_used = True
        out.append(b.strip())
    return [b for b in out if b]


def _enforce_single_question(bubbles: List[str]) -> List[str]:
    """Se uma bolha contém 2+ perguntas, mantém só a primeira."""
    out: List[str] = []
    for b in bubbles:
        q_count = b.count("?")
        if q_count >= 2:
            # Mantém até a 1ª "?" + frase anterior se houver
            idx = b.find("?")
            b = b[: idx + 1]
        out.append(b)
    return out


def _cap_bubbles(bubbles: List[str]) -> List[str]:
    """Hard cap em MAX_BUBBLES. Sobras viram resumo curto."""
    if len(bubbles) <= MAX_BUBBLES:
        return bubbles
    return bubbles[:MAX_BUBBLES]


def split_into_bubbles(text: str, *,
                         max_bubble_chars: int = MAX_BUBBLE_CHARS,
                         max_bubbles: int = MAX_BUBBLES) -> List[str]:
    """Pipeline completo:
      1. Limpa (whitespace, emojis duplicados)
      2. Quebra em frases
      3. Empacota em bolhas ≤180 chars
      4. Suprime nome repetido (anti-Pamela-Pamela)
      5. 1 pergunta por bolha
      6. Hard cap 3 bolhas
    """
    text = _clean(text)
    if not text:
        return []
    # Override globais (chamador pode customizar)
    global MAX_BUBBLE_CHARS, MAX_BUBBLES
    orig_mbc, orig_mb = MAX_BUBBLE_CHARS, MAX_BUBBLES
    MAX_BUBBLE_CHARS = max_bubble_chars
    MAX_BUBBLES = max_bubbles
    try:
        sents = _split_sentences(text)
        bubbles = _pack_into_bubbles(sents)
        bubbles = _suppress_repeated_name(bubbles)
        bubbles = _enforce_single_question(bubbles)
        bubbles = _cap_bubbles(bubbles)
        # Garante hard limit final
        bubbles = [b[:max_bubble_chars].strip() for b in bubbles if b.strip()]
        return bubbles
    finally:
        MAX_BUBBLE_CHARS = orig_mbc
        MAX_BUBBLES = orig_mb


def estimate_typing_delay(bubble: str) -> float:
    """Delay de digitação humano: ~30 chars/s + base 0.6s. Cap 4.5s."""
    base = 0.6
    chars_per_sec = 30.0
    return min(4.5, base + len(bubble) / chars_per_sec)
