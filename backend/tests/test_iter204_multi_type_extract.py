"""iter204 — valida que o split de drafts por tipo gera N lançamentos.

A IA Claude classifica cada item de uma NF com um `type`. O helper
`_split_draft_by_type` em purchases.py deve agrupar items por type e
retornar 1 draft por grupo (ex: NF com 3 ONTs + 50m drop + 1 alicate →
3 drafts: ont, insumo, ferramenta).

O frontend (CentralComprasPanel.js) então cria 1 purchase por draft.
"""
from routes.purchases import _split_draft_by_type


def test_single_type_returns_original_draft():
    """Se todos itens são do mesmo tipo, retorna 1 draft (sem ruído)."""
    draft = {
        "supplier_name": "Furukawa",
        "invoice_number": "12345",
        "type": "ont",
        "items": [
            {"description": "ONT Huawei HG6145D", "quantity": 5,
             "type": "ont", "unit_price": 190.40},
            {"description": "ONT ZTE F660", "quantity": 5,
             "type": "ont", "unit_price": 180.00},
        ],
    }
    result = _split_draft_by_type(draft)
    assert len(result) == 1
    assert result[0]["type"] == "ont"
    assert len(result[0]["items"]) == 2


def test_multi_type_splits_into_n_drafts():
    """NF mista (ONT + insumos + ferramentas) → 3 drafts separados."""
    draft = {
        "supplier_name": "Furukawa Telecom",
        "invoice_number": "98765",
        "invoice_date": "2026-02-15",
        "type": "ont",  # dominante
        "items": [
            {"description": "ONT Huawei", "quantity": 10,
             "type": "ont", "unit_price": 190.40},
            {"description": "Cabo Drop FTTH", "quantity": 500,
             "type": "insumo", "unit_price": 0.85, "insumo_id": "drop"},
            {"description": "Conector Fast SC/APC", "quantity": 50,
             "type": "insumo", "unit_price": 4.50,
             "insumo_id": "conector_fast"},
            {"description": "Alicate Decapador", "quantity": 1,
             "type": "ferramenta", "unit_price": 350.00},
        ],
    }
    result = _split_draft_by_type(draft)
    assert len(result) == 3, f"esperava 3 drafts, veio {len(result)}"
    by_type = {d["type"]: d for d in result}
    assert "ont" in by_type and "insumo" in by_type and "ferramenta" in by_type
    # ONT vem primeiro (ordem fixa)
    assert result[0]["type"] == "ont"
    # Insumos: 2 itens (drop + conector)
    assert len(by_type["insumo"]["items"]) == 2
    # Ferramenta: 1 item
    assert len(by_type["ferramenta"]["items"]) == 1
    # Total proporcional do grupo insumo: 500*0.85 + 50*4.50 = 650
    assert by_type["insumo"]["total_value"] == 650.0
    # Metadados preservados em cada draft
    for d in result:
        assert d["supplier_name"] == "Furukawa Telecom"
        assert d["invoice_number"] == "98765"
        assert d["invoice_date"] == "2026-02-15"
        assert d.get("split_from_invoice") is True
        assert d.get("split_part")  # ex "1/3", "2/3"...


def test_items_without_type_inherit_dominant():
    """Items sem `type` herdam o type dominante (fallback)."""
    draft = {
        "type": "insumo",
        "items": [
            {"description": "Conector A", "quantity": 100},  # sem type
            {"description": "Conector B", "quantity": 50,
             "type": "insumo"},
        ],
    }
    result = _split_draft_by_type(draft)
    # Como ambos viram "insumo", devolve 1 draft só
    assert len(result) == 1
    assert result[0]["type"] == "insumo"


def test_empty_items_returns_original():
    """Sem items, devolve draft original."""
    draft = {"type": "ont", "items": []}
    result = _split_draft_by_type(draft)
    assert result == [draft]


def test_order_is_fixed_ont_first():
    """Ordem dos drafts: ont → insumo → equipamento → ferramenta → outros."""
    draft = {
        "type": "outros",
        "items": [
            {"description": "Alicate", "type": "ferramenta", "quantity": 1,
             "unit_price": 100},
            {"description": "ONT", "type": "ont", "quantity": 1,
             "unit_price": 200},
            {"description": "Switch", "type": "equipamento", "quantity": 1,
             "unit_price": 500},
            {"description": "Drop", "type": "insumo", "quantity": 100,
             "unit_price": 1},
        ],
    }
    result = _split_draft_by_type(draft)
    types = [d["type"] for d in result]
    assert types == ["ont", "insumo", "equipamento", "ferramenta"]
