"""
nav_tabs_registry.py — Fonte de verdade que reflete a estrutura de abas
do sidebar declarada em `/app/frontend/src/App.js → NAV_GROUPS`.

REGRA DE OURO (iter211v):
========================
Toda aba (e sub-aba) criada no sidebar do `App.js` PRECISA aparecer aqui
e no catálogo de tags em `/app/backend/access_tags.py`. Quando isso for
violado, o startup do backend emite WARNING, o endpoint
`GET /api/users/access-tags/audit` retorna a divergência, e o pytest
`tests/test_iter211v_nav_access_tags_parity.py` falha.

Este módulo NÃO duplica a definição visual (ícones, labels traduzidos).
Ele apenas guarda os `id`s estruturais para que possamos validar a
paridade automaticamente.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple


# Caminho default do App.js (override em testes via env).
APP_JS_PATH = os.environ.get(
    "FRONTEND_APP_JS_PATH", "/app/frontend/src/App.js"
)


def _read_app_js() -> str:
    try:
        with open(APP_JS_PATH, "r", encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


_NAV_GROUPS_RE = re.compile(
    r"const\s+NAV_GROUPS\s*=\s*\[", re.MULTILINE,
)
_LABEL_RE = re.compile(r"label:\s*['\"]([^'\"]+)['\"]")
_ITEMS_RE = re.compile(r"items:\s*\[")
_ID_RE = re.compile(r"id:\s*['\"]([a-zA-Z0-9_\-]+)['\"]")
_CHILDREN_RE = re.compile(r"children:\s*\[")


def _strip_js_noise(src: str) -> str:
    """Remove comentários // e /* */ e literais de string para que o
    contador de chaves não seja confundido por { } dentro de comentários
    ou strings."""
    out: List[str] = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        # // line comment
        if ch == "/" and nxt == "/":
            j = src.find("\n", i)
            i = n if j == -1 else j
            continue
        # /* block comment */
        if ch == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        # strings 'x', "x", `x` — mantemos as aspas mas substituímos o
        # corpo por espaços (preserva regex `label:"..."`).
        if ch in ("'", '"', "`"):
            quote = ch
            out.append(ch)
            i += 1
            while i < n and src[i] != quote:
                if src[i] == "\\" and i + 1 < n:
                    out.append(" ")  # come o escape
                    out.append(" ")
                    i += 2
                    continue
                # mantém o caractere se for printável "seguro" (necessário
                # para que `label:"Financeiro"` continue legível)
                out.append(src[i])
                i += 1
            if i < n:
                out.append(quote)
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _slice_balanced(src: str, start: int, open_ch: str, close_ch: str) -> Tuple[int, int]:
    """Dado src[start] == open_ch, retorna (start, end_inclusive) do bloco
    balanceado, ou (start, start) se não encontrar."""
    depth = 0
    for i in range(start, len(src)):
        if src[i] == open_ch:
            depth += 1
        elif src[i] == close_ch:
            depth -= 1
            if depth == 0:
                return start, i
    return start, start


def parse_nav_tabs(source: Optional[str] = None) -> Dict[str, List[Tuple[str, Optional[str]]]]:
    """Parseia `NAV_GROUPS` de `App.js` e retorna:
        { "<categoria>": [ (id, parent_id_or_None), ... ] }
    Não falha se App.js for inacessível — retorna {}.
    """
    raw = source if source is not None else _read_app_js()
    if not raw:
        return {}
    text = _strip_js_noise(raw)
    m = _NAV_GROUPS_RE.search(text)
    if not m:
        return {}
    arr_start = m.end() - 1  # posição do '['
    _, arr_end = _slice_balanced(text, arr_start, "[", "]")
    body = text[arr_start + 1 : arr_end]
    out: Dict[str, List[Tuple[str, Optional[str]]]] = {}
    # Itera sobre cada objeto top-level no array.
    i = 0
    while i < len(body):
        if body[i] != "{":
            i += 1
            continue
        _, gend = _slice_balanced(body, i, "{", "}")
        group_src = body[i : gend + 1]
        i = gend + 1
        lm = _LABEL_RE.search(group_src)
        if not lm:
            continue
        label = lm.group(1)
        # Encontra items: [ ... ] dentro do grupo.
        im = _ITEMS_RE.search(group_src)
        if not im:
            continue
        items_start = group_src.index("[", im.end() - 1)
        _, items_end = _slice_balanced(group_src, items_start, "[", "]")
        items_src = group_src[items_start + 1 : items_end]
        entries: List[Tuple[str, Optional[str]]] = []
        # Itera sobre cada item do array de items.
        k = 0
        while k < len(items_src):
            if items_src[k] != "{":
                k += 1
                continue
            _, iend = _slice_balanced(items_src, k, "{", "}")
            item_src = items_src[k : iend + 1]
            k = iend + 1
            ids = _ID_RE.findall(item_src)
            if not ids:
                continue
            parent_id = ids[0]
            entries.append((parent_id, None))
            cm = _CHILDREN_RE.search(item_src)
            if cm:
                ch_start = item_src.index("[", cm.end() - 1)
                _, ch_end = _slice_balanced(item_src, ch_start, "[", "]")
                ch_src = item_src[ch_start + 1 : ch_end]
                for cid in _ID_RE.findall(ch_src):
                    entries.append((cid, parent_id))
        if entries:
            out[label] = entries
    return out


def all_nav_ids(source: Optional[str] = None) -> List[str]:
    """Lista plana de todos os ids declarados em NAV_GROUPS (pais+filhos),
    preservando ordem e removendo duplicatas."""
    seen: set = set()
    out: List[str] = []
    for entries in parse_nav_tabs(source).values():
        for tid, _ in entries:
            if tid not in seen:
                seen.add(tid)
                out.append(tid)
    return out


def audit_against_catalog(catalog_keys: List[str],
                          source: Optional[str] = None) -> Dict:
    """Compara ids do NAV_GROUPS com chaves do catálogo de access_tags.
    Retorna dict pronto pra expor via endpoint/log."""
    nav_ids = all_nav_ids(source)
    nav_set = set(nav_ids)
    cat_set = set(catalog_keys)
    missing = sorted(nav_set - cat_set)   # presente no sidebar, faltando no catálogo
    extra = sorted(cat_set - nav_set)     # presente no catálogo, sem aba no sidebar
    return {
        "nav_total": len(nav_set),
        "catalog_total": len(cat_set),
        "matches": sorted(nav_set & cat_set),
        "missing_in_catalog": missing,
        "extra_in_catalog": extra,
        "in_sync": len(missing) == 0,
    }
