"""
test_iter211v_nav_access_tags_parity.py
========================================
REGRA: toda aba/sub-aba em `frontend/src/App.js → NAV_GROUPS` precisa
ter uma tag correspondente em `backend/access_tags.py → TAGS`.

Este teste garante que quando alguém adicionar uma nova aba sem criar
a tag, a build quebra antes de subir pra produção.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from access_tags import TAGS  # noqa: E402
from nav_tabs_registry import (  # noqa: E402
    all_nav_ids,
    audit_against_catalog,
    parse_nav_tabs,
)


def test_nav_groups_parses_at_least_main_categories():
    groups = parse_nav_tabs()
    # Esperamos pelo menos estas categorias bem-conhecidas. Se uma sumir,
    # provavelmente alguém renomeou — explicitar o erro ajuda o debug.
    expected = {
        "Operação", "Frota", "Projetos", "Inteligência", "Cadastro",
        "Relatórios", "RH", "Financeiro", "Comercial", "Sistema",
    }
    missing = expected - set(groups.keys())
    assert not missing, (
        f"Categorias NAV ausentes (renomeou em App.js?): {missing}. "
        f"Encontradas: {list(groups.keys())}"
    )


def test_every_nav_tab_has_access_tag():
    """Falha se alguma aba do sidebar não tem tag no catálogo backend."""
    catalog_keys = [t["key"] for t in TAGS]
    audit = audit_against_catalog(catalog_keys)
    assert audit["in_sync"], (
        "iter211v — Faltam tags em /app/backend/access_tags.py para as "
        f"seguintes abas declaradas em NAV_GROUPS:\n  {audit['missing_in_catalog']}"
        f"\nAdicione cada uma como {{'key': '<id>', 'label': '...', 'icon': '...', 'category': '...'}} "
        "em TAGS e (opcional) em DEFAULT_TAGS_BY_ROLE."
    )


def test_nav_ids_are_unique():
    ids = all_nav_ids()
    dups = [i for i in ids if ids.count(i) > 1]
    assert not dups, f"NAV_GROUPS tem ids duplicados: {set(dups)}"


def test_catalog_keys_are_unique_and_lowercase():
    keys = [t["key"] for t in TAGS]
    dups = [k for k in keys if keys.count(k) > 1]
    assert not dups, f"access_tags TAGS tem keys duplicadas: {set(dups)}"
    bad = [k for k in keys if k != k.strip().lower()]
    assert not bad, f"access_tags TAGS deve usar keys lowercase: {bad}"
