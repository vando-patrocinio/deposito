"""Onda C P0.1 — RCA Fibra Guardrails (CEO 18/06/2026).

Cobre as 3 validações server-side no endpoint POST /api/rede/cables:
  • Guardrail #1: Tokens proibidos (TEST/TST/ABCD/DUMMY/FAKE/MOCK) em
    cable_serial / invoice_number / purchase_id.
  • Guardrail #2: Tiers de comprimento (5km warn, 20km confirm, 50km block).
  • Guardrail #3: purchase_id obrigatório OU admin_override_reason (≥20).
  • Guardrail #4 (card): anomalous_movements no diagnostico endpoint.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

sys.path.insert(0, "/app/backend")
for ln in open("/app/backend/.env"):
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ.setdefault(k, v.strip('"'))

pytestmark = pytest.mark.asyncio(loop_scope="session")
CID = "TEST-RCA-GUARDRAILS"


def _user():
    return {"company_id": CID, "name": "ceo_test", "role": "administrador"}


def _body(**overrides):
    from routes.rede_ia_map import CableIn, CableSegment
    base = {
        "type": "12fo",
        "segments": [CableSegment(lat=-23.5, lng=-46.6),
                     CableSegment(lat=-23.51, lng=-46.61)],
        "length_m": 1500.0,
        "cable_serial": "FB-REAL-9999",
        "invoice_number": "NF-12345",
        "purchase_id": "purchase-real-xyz",
    }
    base.update(overrides)
    return CableIn(**base)


async def _cleanup():
    from database import db
    await db.network_cables.delete_many({"company_id": CID})


# ─────────────────────── GUARDRAIL #1 — Tokens ───────────────────────────

async def test_g1_serial_with_test_token_blocked():
    from routes.rede_ia_map import _validate_cable_guardrails
    body = _body(cable_serial="ABCD-TEST-001")
    with pytest.raises(HTTPException) as exc:
        _validate_cable_guardrails(body, _user(), 1500.0)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "guardrail_test_token_blocked"
    assert "ABCD" in exc.value.detail["human_reason"] or \
        "TEST" in exc.value.detail["human_reason"]


async def test_g1_invoice_with_fake_blocked():
    from routes.rede_ia_map import _validate_cable_guardrails
    body = _body(invoice_number="NF-FAKE-001")
    with pytest.raises(HTTPException) as exc:
        _validate_cable_guardrails(body, _user(), 1500.0)
    assert exc.value.detail["error"] == "guardrail_test_token_blocked"


async def test_g1_purchase_with_dummy_blocked():
    from routes.rede_ia_map import _validate_cable_guardrails
    body = _body(purchase_id="DUMMY-1")
    with pytest.raises(HTTPException) as exc:
        _validate_cable_guardrails(body, _user(), 1500.0)
    assert exc.value.detail["error"] == "guardrail_test_token_blocked"


async def test_g1_real_data_passes():
    from routes.rede_ia_map import _validate_cable_guardrails
    body = _body()
    # não deve levantar
    _validate_cable_guardrails(body, _user(), 1500.0)


async def test_g1_drop_does_not_validate():
    from routes.rede_ia_map import _validate_cable_guardrails
    body = _body(type="drop", cable_serial="TEST-WHATEVER",
                  invoice_number=None, purchase_id=None)
    # Drop é isento dos guardrails (volume pequeno, alta freq)
    _validate_cable_guardrails(body, _user(), 1500.0)


# ─────────────────────── GUARDRAIL #2 — Comprimento ──────────────────────

async def test_g2_under_5km_passes():
    from routes.rede_ia_map import _validate_cable_guardrails
    body = _body()
    _validate_cable_guardrails(body, _user(), 4000.0)


async def test_g2_between_5_20km_warn_only_passes():
    from routes.rede_ia_map import _validate_cable_guardrails, _length_warning_tier
    body = _body()
    # passa sem confirm (só warn — não bloqueia)
    _validate_cable_guardrails(body, _user(), 8000.0)
    assert _length_warning_tier(8000.0) == "length_warn_tier"


async def test_g2_between_20_50km_without_confirm_blocked():
    from routes.rede_ia_map import _validate_cable_guardrails
    body = _body(confirm_unusual_length=False)
    with pytest.raises(HTTPException) as exc:
        _validate_cable_guardrails(body, _user(), 25000.0)
    assert exc.value.detail["error"] == "guardrail_length_confirm_required"


async def test_g2_between_20_50km_with_confirm_passes():
    from routes.rede_ia_map import _validate_cable_guardrails, _length_warning_tier
    body = _body(confirm_unusual_length=True)
    _validate_cable_guardrails(body, _user(), 25000.0)
    assert _length_warning_tier(25000.0) == "length_confirm_tier"


async def test_g2_over_50km_without_override_blocked():
    from routes.rede_ia_map import _validate_cable_guardrails
    body = _body(confirm_unusual_length=True)  # nem confirm salva
    with pytest.raises(HTTPException) as exc:
        _validate_cable_guardrails(body, _user(), 60000.0)
    assert exc.value.detail["error"] == "guardrail_length_block"


async def test_g2_over_50km_with_admin_override_passes():
    from routes.rede_ia_map import _validate_cable_guardrails, _length_warning_tier
    body = _body(
        admin_override_reason="Cabo backbone metropolitano regional "
                              "validado pelo gestor",
        confirm_unusual_length=True,
    )
    _validate_cable_guardrails(body, _user(), 60000.0)
    assert _length_warning_tier(60000.0) == "length_block_tier"


# ─────────────────────── GUARDRAIL #3 — purchase_id ──────────────────────

async def test_g3_no_purchase_id_no_override_blocked():
    from routes.rede_ia_map import _validate_cable_guardrails
    body = _body(purchase_id=None, admin_override_reason=None)
    with pytest.raises(HTTPException) as exc:
        _validate_cable_guardrails(body, _user(), 1500.0)
    assert exc.value.detail["error"] == "guardrail_purchase_id_required"


async def test_g3_no_purchase_id_short_override_blocked():
    from routes.rede_ia_map import _validate_cable_guardrails
    body = _body(purchase_id=None, admin_override_reason="curta")
    with pytest.raises(HTTPException) as exc:
        _validate_cable_guardrails(body, _user(), 1500.0)
    assert exc.value.detail["error"] == "guardrail_purchase_id_required"


async def test_g3_no_purchase_id_long_override_passes():
    from routes.rede_ia_map import _validate_cable_guardrails
    body = _body(
        purchase_id=None,
        admin_override_reason="Cabo doado por parceiro Telebrasil, "
                              "termo de doação anexo número 4521",
    )
    _validate_cable_guardrails(body, _user(), 1500.0)


# ─────────────────────── GUARDRAIL #4 — Card Watchtower ──────────────────

async def test_g4_anomalous_movements_returned():
    """Endpoint diagnostico retorna chave anomalous_movements com 4 buckets."""
    from routes.watchtower_estoque_diagnostico import (
        watchtower_estoque_diagnostico,
    )
    res = await watchtower_estoque_diagnostico(
        user={"company_id": "co-demo", "role": "gestor"},
        window_hours=168,
    )
    assert "anomalous_movements" in res
    a = res["anomalous_movements"]
    for key in ("cables_anomalous_count", "cables_anulados_count",
                "estornos_count", "admin_overrides_count"):
        assert key in a, f"{key} missing in anomalous_movements"
    # Os 4 cabos anulados pela RCA devem aparecer.
    assert a["cables_anulados_count"] >= 4, \
        f"esperado >=4 anulados (RCA Fibra), achei {a['cables_anulados_count']}"
    # Os 4 estornos da RCA devem estar lá.
    assert a["estornos_count"] >= 4, \
        f"esperado >=4 estornos (RCA Fibra), achei {a['estornos_count']}"


if __name__ == "__main__":
    async def _main():
        await test_g1_serial_with_test_token_blocked()
        await test_g1_invoice_with_fake_blocked()
        await test_g1_purchase_with_dummy_blocked()
        await test_g1_real_data_passes()
        await test_g1_drop_does_not_validate()
        await test_g2_under_5km_passes()
        await test_g2_between_5_20km_warn_only_passes()
        await test_g2_between_20_50km_without_confirm_blocked()
        await test_g2_between_20_50km_with_confirm_passes()
        await test_g2_over_50km_without_override_blocked()
        await test_g2_over_50km_with_admin_override_passes()
        await test_g3_no_purchase_id_no_override_blocked()
        await test_g3_no_purchase_id_short_override_blocked()
        await test_g3_no_purchase_id_long_override_passes()
        await test_g4_anomalous_movements_returned()
        print("✅ RCA Fibra Guardrails — 15/15 tests PASS")
    asyncio.run(_main())
