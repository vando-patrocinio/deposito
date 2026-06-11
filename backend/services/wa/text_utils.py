"""Utilitários de processamento de texto para o pipeline WhatsApp.

Extraído de routes/whatsapp_baileys.py em iter106 (refactor).
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

import re
from typing import List


def _split_ai_reply(text: str, max_chunks: int = 6,
                     min_chunk_chars: int = 12) -> List[str]:
    """Quebra a resposta da IA em chunks que viram bolhas separadas no
    WhatsApp.

    Regras:
    1. PRIORIDADE: se a resposta vier como múltiplas strings entre aspas
       (padrão Isabella V6 — cada bolha em uma linha entre `"..."`), cada
       string vira uma bolha. Strings vazias `""` são marcadores de quebra
       e descartadas. Isso permite a IA controlar onde quebrar com precisão
       (regra do gestor: "" separa bolha).
    2. Caso contrário, separa por linhas em branco (`\\n\\n`) ou marcador
       explícito `---`.
    3. Junta chunks micro (< min_chunk_chars) no chunk seguinte para
       evitar bolhas de 1-2 palavras.
    4. Cap em `max_chunks`: o excedente é concatenado no último chunk
       (assim a IA não consegue 'flood' o cliente).
    5. Quebras de linha simples (`\\n`) DENTRO de um chunk são preservadas
       (ex.: lista de bullets).
    6. Se a resposta for curta ou inteira numa linha só, devolve [text].
    """
    if not text:
        return []
    raw = text.replace("\r\n", "\n").strip()

    # Detecta padrão "bolhas-aspas Isabella": linhas que começam e terminam
    # com aspas (ou são `""` vazio). Se a maioria das linhas não-vazias
    # seguir esse padrão, tratamos cada uma como bolha individual.
    lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
    quoted_lines = [
        ln for ln in lines
        if (ln.startswith('"') and ln.endswith('"')
            and len(ln) >= 2)
    ]
    if lines and len(quoted_lines) >= max(2, int(len(lines) * 0.6)):
        # Modo bolhas-aspas: cada string entre aspas é uma bolha.
        # `""` (vazio) é separador puro e some.
        bubbles: List[str] = []
        for ln in quoted_lines:
            inner = ln[1:-1].strip()
            if inner:
                bubbles.append(inner)
        if bubbles:
            # Cap igual ao caminho normal
            if len(bubbles) > max_chunks:
                head = bubbles[: max_chunks - 1]
                tail = "\n\n".join(bubbles[max_chunks - 1:])
                bubbles = head + [tail]
            return bubbles

    # --- caminho clássico (parágrafos por linha em branco) ---
    # Separador explícito `---` em linha sozinha vira "\n\n" pra unificar
    raw = re.sub(r"\n\s*---+\s*\n", "\n\n", raw)
    # Linha contendo só "" também serve como separador explícito
    raw = re.sub(r'\n\s*""\s*\n', "\n\n", raw)
    parts = re.split(r"\n{2,}", raw)
    # Limpa e remove vazios
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return []
    # Junta micros (< min_chunk_chars) com o próximo
    merged: List[str] = []
    buf = ""
    for p in parts:
        if len(p) < min_chunk_chars and not buf:
            buf = p
            continue
        if buf:
            merged.append((buf + "\n\n" + p).strip())
            buf = ""
        else:
            merged.append(p)
    if buf:
        if merged:
            merged[-1] = (merged[-1] + "\n\n" + buf).strip()
        else:
            merged.append(buf)
    # Cap em max_chunks (overflow junta no último)
    if len(merged) > max_chunks:
        head = merged[: max_chunks - 1]
        tail = "\n\n".join(merged[max_chunks - 1:])
        merged = head + [tail]
    return merged
