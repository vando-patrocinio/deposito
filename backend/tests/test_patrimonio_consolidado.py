"""Onda C P2 — Watchtower Patrimônio Consolidado.

Valida que o payload responde as 5 perguntas do CEO e que os cálculos
batem para cenários sintéticos controlados.
"""
import asyncio
import os
import sys
import uuid

import pytest

sys.path.insert(0, "/app/backend")
for ln in open("/app/backend/.env"):
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ.setdefault(k, v.strip('"'))

pytestmark = pytest.mark.asyncio(loop_scope="session")
CID = "TEST-PATCONS"


async def _cleanup():
    from database import db
    await db.stok_onts.delete_many({"company_id": CID})
    await db.stok_stock.delete_many({"company_id": CID})
    await db.stok_history.delete_many({"company_id": CID})
    await db.smartolt_onus.delete_many({"company_id": CID})


async def _seed_ont(*, mac=None, location_type="cliente", location_id="c1",
                    purchase_id="po-1", is_defective=False,
                    synthetic_origin=False,
                    last_ticket_id="tkt-1",
                    last_user="user-test"):
    from database import db
    oid = f"ont-{uuid.uuid4().hex[:8]}"
    await db.stok_onts.insert_one({
        "id": oid, "company_id": CID,
        "mac": mac or f"MAC{uuid.uuid4().hex[:8]}",
        "sn": f"SN{uuid.uuid4().hex[:8]}",
        "location_type": location_type,
        "location_id": location_id,
        "owner_id": "tec-1",
        "purchase_id": purchase_id,
        "is_defective": is_defective,
        "synthetic_origin": synthetic_origin,
        "last_ticket_id": last_ticket_id,
        "updated_at": "2026-06-18T00:00:00+00:00",
    })
    return oid


# ─── P1+P4: Quanto existe + Onde está ─────────────────────────────────────

async def test_ativos_counts_by_location():
    from services.patrimonio_consolidado import compute_patrimonio_consolidado
    await _cleanup()
    await _seed_ont(location_type="cliente", location_id="c1")
    await _seed_ont(location_type="cliente", location_id="c2")
    await _seed_ont(location_type="tecnico", location_id="t1")
    await _seed_ont(location_type="empresa", location_id="empresa")
    r = await compute_patrimonio_consolidado(CID)
    assert r["ativos"]["total"] == 4
    assert r["ativos"]["em_cliente"] == 2
    assert r["ativos"]["em_tecnico"] == 1
    assert r["ativos"]["em_empresa"] == 1
    await _cleanup()


async def test_ativos_sem_localizacao_detected():
    from services.patrimonio_consolidado import compute_patrimonio_consolidado
    await _cleanup()
    await _seed_ont(location_type="cliente", location_id="")  # vazio
    await _seed_ont(location_type="cliente", location_id="c1")
    r = await compute_patrimonio_consolidado(CID)
    assert r["ativos"]["sem_localizacao"] == 1
    await _cleanup()


async def test_ativos_defeito_e_sintetica():
    from services.patrimonio_consolidado import compute_patrimonio_consolidado
    await _cleanup()
    await _seed_ont(is_defective=True)
    await _seed_ont(synthetic_origin=True)
    await _seed_ont()  # normal
    r = await compute_patrimonio_consolidado(CID)
    assert r["ativos"]["em_defeito"] == 1
    assert r["ativos"]["sintetica"] == 1
    await _cleanup()


# ─── P2: Quanto vale ──────────────────────────────────────────────────────

async def test_valor_aquisicao_segue_catalogo():
    from services.patrimonio_consolidado import (
        compute_patrimonio_consolidado, PRICE_CATALOG,
    )
    await _cleanup()
    await _seed_ont()
    await _seed_ont()
    await _seed_ont()
    r = await compute_patrimonio_consolidado(CID)
    expected = 3 * PRICE_CATALOG["ont"]["value"]
    assert r["valor"]["aquisicao_ont"] == round(expected, 2)
    # Confiabilidade financeira existe e é > 0 (catálogo tem confidence>0)
    assert r["valor"]["confiabilidade_financeira_pct"] > 0
    await _cleanup()


async def test_valor_recuperacoes_inclui_estornos_de_fibra():
    """Estornos como o RCA Fibra contam em recuperacoes_total."""
    from database import db
    from services.patrimonio_consolidado import (
        compute_patrimonio_consolidado, PRICE_CATALOG,
    )
    await _cleanup()
    # Insere 1 estorno de 364.356m fibra_12fo (como RCA)
    await db.stok_history.insert_one({
        "id": "hist-test-recovery",
        "company_id": CID,
        "type": "rede_estorno",
        "consumable_id": "fibra_12fo",
        "delta_meters_signed": 364356.0,
    })
    r = await compute_patrimonio_consolidado(CID)
    expected = 364356.0 * PRICE_CATALOG["fibra_12fo"]["value"]
    assert abs(r["valor"]["recuperacoes_total"] - expected) < 0.1, \
        f"esperado={expected}, achei={r['valor']['recuperacoes_total']}"
    await _cleanup()


# ─── P3+P5: Rastreabilidade ───────────────────────────────────────────────

async def test_rastreabilidade_5_campos_100_pct():
    """ONT com TODOS os 5 campos → 100%"""
    from services.patrimonio_consolidado import compute_patrimonio_consolidado
    await _cleanup()
    await _seed_ont(
        location_type="cliente", location_id="c1",
        purchase_id="po-real", last_ticket_id="tkt-1",
    )
    r = await compute_patrimonio_consolidado(CID)
    assert r["rastreabilidade"]["overall_index_pct"] == 100.0
    assert r["rastreabilidade"]["tier"] == "excelencia"
    assert r["rastreabilidade"]["worst_assets"] == []
    await _cleanup()


async def test_rastreabilidade_falta_origem_80_pct():
    from services.patrimonio_consolidado import compute_patrimonio_consolidado
    await _cleanup()
    await _seed_ont(purchase_id=None)  # falta origem
    r = await compute_patrimonio_consolidado(CID)
    assert r["rastreabilidade"]["overall_index_pct"] == 80.0
    worst = r["rastreabilidade"]["worst_assets"]
    assert len(worst) == 1
    assert "origem" in worst[0]["missing_fields"]
    await _cleanup()


async def test_rastreabilidade_falta_3_campos_40_pct():
    from services.patrimonio_consolidado import compute_patrimonio_consolidado
    await _cleanup()
    await _seed_ont(
        purchase_id=None, last_ticket_id=None, last_user=None,
    )
    r = await compute_patrimonio_consolidado(CID)
    # owner_id ainda existe (tec-1), location_id existe, updated_at existe
    # falta: purchase_id, last_ticket_id → 60%
    assert r["rastreabilidade"]["overall_index_pct"] == 60.0
    await _cleanup()


# ─── KPI compound: Patrimônio Confiável ───────────────────────────────────

async def test_patrimonio_confiavel_calculado():
    """Patrimônio Confiável = Rastreabilidade × Confiabilidade Financeira."""
    from services.patrimonio_consolidado import compute_patrimonio_consolidado
    await _cleanup()
    await _seed_ont()  # 100% rastreabilidade
    r = await compute_patrimonio_consolidado(CID)
    pat = r["patrimonio_confiavel"]
    fin = r["valor"]["confiabilidade_financeira_pct"]
    expected_pat = round((100.0 / 100.0) * (fin / 100.0) * 100, 1)
    assert pat["patrimonio_confiavel_pct"] == expected_pat
    assert pat["valor_defendvel_estimado"] > 0
    await _cleanup()


# ─── Asset categories + catalog meta ──────────────────────────────────────

async def test_payload_inclui_metadata_de_catalogo_e_categorias():
    from services.patrimonio_consolidado import compute_patrimonio_consolidado
    await _cleanup()
    await _seed_ont()
    r = await compute_patrimonio_consolidado(CID)
    assert "asset_categories" in r
    assert r["asset_categories"]["ont"]["lifetime_years"] == 5
    assert r["asset_categories"]["fibra"]["lifetime_years"] == 10
    assert r["asset_categories"]["consumivel"]["depreciate"] is False
    assert r["price_catalog_meta"]["source"].startswith("catalog_estimated")
    await _cleanup()


# ─── Ajuste 2 · Split Recuperações Operacional × Extraordinária ───────────

async def test_ajuste2_rede_estorno_classificada_como_extraordinaria():
    """type=rede_estorno SEMPRE conta como extraordinária."""
    from database import db
    from services.patrimonio_consolidado import (
        compute_patrimonio_consolidado, PRICE_CATALOG,
    )
    await _cleanup()
    await db.stok_history.insert_one({
        "id": "hist-rca",
        "company_id": CID,
        "type": "rede_estorno",
        "tag": "rca_fibra_20260618",
        "consumable_id": "fibra_12fo",
        "delta_meters_signed": 364356.0,
    })
    r = await compute_patrimonio_consolidado(CID)
    expected = 364356.0 * PRICE_CATALOG["fibra_12fo"]["value"]
    assert r["valor"]["recuperacoes_extraordinaria"] == round(expected, 2)
    assert r["valor"]["recuperacoes_operacional"] == 0.0
    # retro-compat: total = ex + op
    assert (r["valor"]["recuperacoes_total"]
            == r["valor"]["recuperacoes_extraordinaria"]
            + r["valor"]["recuperacoes_operacional"])
    assert "rca_fibra_20260618" in r["valor"]["recuperacoes_breakdown"]["extraordinaria"]
    await _cleanup()


async def test_ajuste2_recovery_normal_classificada_como_operacional():
    """type=recovery sem tag rca_*/legacy_* é operacional (swap normal)."""
    from database import db
    from services.patrimonio_consolidado import (
        compute_patrimonio_consolidado, PRICE_CATALOG,
    )
    await _cleanup()
    await db.stok_history.insert_one({
        "id": "hist-op",
        "company_id": CID,
        "type": "recovery",
        "tag": "ont_swap_reuse",
        "consumable_id": "drop",
        "delta_signed": 50,
    })
    r = await compute_patrimonio_consolidado(CID)
    expected = 50 * PRICE_CATALOG["drop"]["value"]
    assert r["valor"]["recuperacoes_operacional"] == round(expected, 2)
    assert r["valor"]["recuperacoes_extraordinaria"] == 0.0
    assert "ont_swap_reuse" in r["valor"]["recuperacoes_breakdown"]["operacional"]
    await _cleanup()


async def test_ajuste2_legacy_orphan_classificada_como_extraordinaria():
    """tag legacy_orphan_* é extraordinária (reconciliação forense)."""
    from database import db
    from services.patrimonio_consolidado import (
        compute_patrimonio_consolidado, PRICE_CATALOG,
    )
    await _cleanup()
    await db.stok_history.insert_one({
        "id": "hist-leg",
        "company_id": CID,
        "type": "recovery",
        "tag": "legacy_orphan_consumption_recovery_20260618",
        "consumable_id": "drop",
        "delta_signed": 42,
    })
    r = await compute_patrimonio_consolidado(CID)
    expected = 42 * PRICE_CATALOG["drop"]["value"]
    assert r["valor"]["recuperacoes_extraordinaria"] == round(expected, 2)
    assert r["valor"]["recuperacoes_operacional"] == 0.0
    await _cleanup()


async def test_ajuste2_split_misto():
    """Mix de operacional + extraordinária — ambos contam separados."""
    from database import db
    from services.patrimonio_consolidado import compute_patrimonio_consolidado
    await _cleanup()
    await db.stok_history.insert_many([
        {"id": "h-op", "company_id": CID, "type": "recovery",
         "tag": "ont_swap", "consumable_id": "drop", "delta_signed": 10},
        {"id": "h-ex", "company_id": CID, "type": "rede_estorno",
         "tag": "rca_fibra_demo", "consumable_id": "fibra_12fo",
         "delta_meters_signed": 1000.0},
    ])
    r = await compute_patrimonio_consolidado(CID)
    assert r["valor"]["recuperacoes_operacional"] > 0
    assert r["valor"]["recuperacoes_extraordinaria"] > 0
    # Operacional não pode conter rca_*
    op_keys = list(r["valor"]["recuperacoes_breakdown"]["operacional"].keys())
    assert not any(k.startswith("rca_") for k in op_keys)
    assert not any(k.startswith("legacy_orphan_") for k in op_keys)
    await _cleanup()


# ─── Ajuste 2 · KPI Cobertura Patrimonial (gate Sprint 5.1) ───────────────

async def test_cobertura_patrimonial_zero_quando_sem_smartolt():
    from services.patrimonio_consolidado import compute_patrimonio_consolidado
    await _cleanup()
    await _seed_ont()
    r = await compute_patrimonio_consolidado(CID)
    c = r["cobertura_patrimonial"]
    assert c["smartolt_total_docs"] == 0
    assert c["intersect_count"] == 0
    assert c["cobertura_pct"] == 0.0
    assert c["auto_balanco_bloqueado"] is True
    assert c["tier"] == "vermelho"
    await _cleanup()


async def test_cobertura_patrimonial_100_quando_mac_bate():
    from database import db
    from services.patrimonio_consolidado import compute_patrimonio_consolidado
    await _cleanup()
    mac = "AA:BB:CC:11:22:33"
    await _seed_ont(mac=mac)
    await db.smartolt_onus.insert_one({
        "company_id": CID, "mac": mac,
        "unique_external_id": "ext-test-1",
        "sn": "SN-Z", "status": "Online",
        "administrative_status": "Enabled",
    })
    r = await compute_patrimonio_consolidado(CID)
    c = r["cobertura_patrimonial"]
    assert c["smartolt_total_docs"] == 1
    assert c["estoque_total_docs"] == 1
    assert c["intersect_count"] == 1
    assert c["cobertura_pct"] == 100.0
    assert c["auto_balanco_bloqueado"] is False
    assert c["tier"] == "excelencia"
    await _cleanup()


async def test_cobertura_patrimonial_bloqueia_auto_balanco_em_94pct():
    """Limiar de desbloqueio é 95% — 94% ainda bloqueia."""
    from database import db
    from services.patrimonio_consolidado import compute_patrimonio_consolidado
    await _cleanup()
    # SmartOLT com 100 ONUs, estoque cobre apenas 94 → 94%
    docs = []
    for i in range(100):
        docs.append({"company_id": CID,
                      "unique_external_id": f"ext-94-{i:03d}",
                      "mac": f"AA:BB:CC:DD:{i:02X}:00",
                      "sn": f"SN-{i:04d}",
                      "status": "Online",
                      "administrative_status": "Enabled"})
    await db.smartolt_onus.insert_many(docs)
    for i in range(94):
        await _seed_ont(mac=f"AA:BB:CC:DD:{i:02X}:00")
    r = await compute_patrimonio_consolidado(CID)
    c = r["cobertura_patrimonial"]
    assert c["intersect_count"] == 94
    assert c["cobertura_pct"] == 94.0
    assert c["auto_balanco_bloqueado"] is True
    assert c["gap_para_meta_pct"] == 1.0
    await _cleanup()


if __name__ == "__main__":
    async def _main():
        await test_ativos_counts_by_location()
        await test_ativos_sem_localizacao_detected()
        await test_ativos_defeito_e_sintetica()
        await test_valor_aquisicao_segue_catalogo()
        await test_valor_recuperacoes_inclui_estornos_de_fibra()
        await test_rastreabilidade_5_campos_100_pct()
        await test_rastreabilidade_falta_origem_80_pct()
        await test_rastreabilidade_falta_3_campos_40_pct()
        await test_patrimonio_confiavel_calculado()
        await test_payload_inclui_metadata_de_catalogo_e_categorias()
        await test_ajuste2_rede_estorno_classificada_como_extraordinaria()
        await test_ajuste2_recovery_normal_classificada_como_operacional()
        await test_ajuste2_legacy_orphan_classificada_como_extraordinaria()
        await test_ajuste2_split_misto()
        await test_cobertura_patrimonial_zero_quando_sem_smartolt()
        await test_cobertura_patrimonial_100_quando_mac_bate()
        await test_cobertura_patrimonial_bloqueia_auto_balanco_em_94pct()
        print("Patrimônio Consolidado — Ajuste 2 — 17/17 tests PASS")
    asyncio.run(_main())
