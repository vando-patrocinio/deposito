"""iter209 — Detecção e reparo de cabos órfãos (incluindo zumbis).

Cobre:
- `_cable_loose_endpoints`: identifica pontas null E pontas zumbi (apontam
  para CTO/CE que não existe mais)
- `_is_orphan_cable`: decisão unificada do que é órfão
- Audit detalhado por critério
- Repair que limpa referências zumbi + marca is_loose=true
"""
import pytest


def test_loose_endpoints_with_null_from():
    from routes.rede_ia import _cable_loose_endpoints
    cab = {
        "from_element_id": None,
        "to_element_id": "cto-1",
        "route_geometry": [[-22.5, -43.5], [-22.6, -43.6]],
    }
    out = _cable_loose_endpoints(cab, existing_ids={"cto-1"})
    assert len(out) == 1
    assert out[0]["end"] == "from"
    assert out[0]["lat"] == -22.5
    assert out[0]["zombie_id"] is None


def test_loose_endpoints_with_zombie_to():
    """to_element_id aponta para CTO deletada → vira loose."""
    from routes.rede_ia import _cable_loose_endpoints
    cab = {
        "from_element_id": "cto-1",
        "to_element_id": "cto-deleted",
        "route_geometry": [[-22.5, -43.5], [-22.7, -43.7]],
    }
    out = _cable_loose_endpoints(cab, existing_ids={"cto-1"})
    assert len(out) == 1
    assert out[0]["end"] == "to"
    assert out[0]["zombie_id"] == "cto-deleted"


def test_loose_endpoints_both_zombie():
    from routes.rede_ia import _cable_loose_endpoints
    cab = {
        "from_element_id": "zombie-a",
        "to_element_id": "zombie-b",
        "route_geometry": [[-22.5, -43.5], [-22.6, -43.6]],
    }
    out = _cable_loose_endpoints(cab, existing_ids=set())
    assert len(out) == 2
    assert {e["zombie_id"] for e in out} == {"zombie-a", "zombie-b"}


def test_loose_endpoints_all_connected_returns_empty():
    from routes.rede_ia import _cable_loose_endpoints
    cab = {
        "from_element_id": "cto-1",
        "to_element_id": "cto-2",
        "route_geometry": [[-22.5, -43.5], [-22.6, -43.6]],
    }
    out = _cable_loose_endpoints(cab, existing_ids={"cto-1", "cto-2"})
    assert out == []


def test_loose_endpoints_without_existing_ids_only_detects_nulls():
    """Compatibilidade retroativa: sem `existing_ids`, só detecta nulls."""
    from routes.rede_ia import _cable_loose_endpoints
    cab = {
        "from_element_id": "zombie",  # zumbi
        "to_element_id": None,         # null
        "route_geometry": [[-22.5, -43.5], [-22.6, -43.6]],
    }
    out = _cable_loose_endpoints(cab, existing_ids=None)
    # Sem set de existentes, zumbi não é detectado — só null
    assert len(out) == 1
    assert out[0]["end"] == "to"


@pytest.mark.asyncio
async def test_is_orphan_cable_status_cabo_solto():
    from routes.rede_ia import _is_orphan_cable
    cab = {"status": "cabo_solto",
           "from_element_id": "cto-1", "to_element_id": "cto-2"}
    assert await _is_orphan_cable(cab, {"cto-1", "cto-2"}) is True


@pytest.mark.asyncio
async def test_is_orphan_cable_is_loose_flag():
    from routes.rede_ia import _is_orphan_cable
    cab = {"is_loose": True,
           "from_element_id": "cto-1", "to_element_id": "cto-2"}
    assert await _is_orphan_cable(cab, {"cto-1", "cto-2"}) is True


@pytest.mark.asyncio
async def test_is_orphan_cable_null_endpoint():
    from routes.rede_ia import _is_orphan_cable
    cab = {"from_element_id": None, "to_element_id": "cto-2"}
    assert await _is_orphan_cable(cab, {"cto-2"}) is True


@pytest.mark.asyncio
async def test_is_orphan_cable_zombie_endpoint():
    from routes.rede_ia import _is_orphan_cable
    cab = {"from_element_id": "cto-1", "to_element_id": "deleted"}
    assert await _is_orphan_cable(cab, {"cto-1"}) is True


@pytest.mark.asyncio
async def test_is_orphan_cable_fully_connected():
    """Cabo normal, ambas pontas em CTOs ativas → NÃO é órfão."""
    from routes.rede_ia import _is_orphan_cable
    cab = {"from_element_id": "cto-1", "to_element_id": "cto-2",
           "status": "validated"}
    assert await _is_orphan_cable(cab, {"cto-1", "cto-2"}) is False
