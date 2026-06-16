"""ONDA R1.1 — Smoke tests do helper inventory_valuation.

Valida:
1. is_model_garbage: detecta lixo (None, vazio, TestModel, ?, xxx).
2. lookup_model_canonical: prefere match longo (greedy).
3. Grade A: ONT com purchase_id + NF resolvível.
4. Grade B: purchase_id sem unit_price → weighted_avg.
5. Grade C: sem purchase_id mas modelo válido.
6. Grade D: sem purchase_id e modelo desconhecido (não-lixo).
7. Grade F: sem purchase_id e modelo lixo.
8. effective_value segue prioridade CEO.
9. ensure_indexes é idempotente.

Uso: python3 scripts/test_r1_1_valuation.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import db  # noqa: E402
from services.inventory_valuation import (  # noqa: E402
    MODEL_CANONICAL, DEFAULT_REFERENCE_PRICE,
    is_model_garbage, lookup_model_canonical,
    resolve_valuation, effective_value, ensure_indexes,
)

TEST_CID = "co-r1-valuation-test"


def test_is_model_garbage():
    # Lixo
    for s in [None, "", "  ", "?", "xxx", "TestModel", "test",
              "Desconhecido", "None", "null", "AB"]:
        assert is_model_garbage(s) is True, f"{s!r} deveria ser lixo"
    # Válidos
    for s in ["FIBERHOME HG6145D", "ZTE F660", "Huawei HG8245",
              "WiFi 7", "MODELO_X"]:
        assert is_model_garbage(s) is False, f"{s!r} NÃO deveria ser lixo"
    print("✅ test_is_model_garbage")


def test_lookup_model_canonical_greedy():
    # Match longo deve ganhar do curto
    res = lookup_model_canonical("FIBERHOME HG6145D ONT AC1200")
    assert res is not None
    brand, model, price = res
    assert brand == "FIBERHOME" and model == "HG6145D" and price == 220.0
    # Fallback genérico Fiberhome quando não cai nas específicas
    res2 = lookup_model_canonical("Fiberhome XYZ qualquer")
    assert res2 is not None and res2[1] == "GENERIC" and res2[0] == "FIBERHOME"
    # ZTE F660
    res3 = lookup_model_canonical("zte f660 v6")
    assert res3 is not None and res3[1] == "F660" and res3[2] == 75.0
    # Lixo retorna None
    assert lookup_model_canonical("TestModel") is None
    assert lookup_model_canonical("") is None
    print("✅ test_lookup_model_canonical_greedy")


async def setup_test_data():
    """Prepara purchase + ONTs de teste."""
    await db.purchases.delete_many({"company_id": TEST_CID})
    await db.stok_onts.delete_many({"company_id": TEST_CID})
    pid = "pur-r1-test"
    await db.purchases.insert_one({
        "id": pid, "company_id": TEST_CID, "type": "ont",
        "status": "confirmed",
        "items": [
            {"description": "HG6145D", "quantity": 2, "unit_price": 300.0,
             "macs": ["AA:01:02:03:04:01", "AA:01:02:03:04:02"]},
        ],
        "total": 600.0,
    })
    return pid


async def cleanup():
    await db.purchases.delete_many({"company_id": TEST_CID})
    await db.stok_onts.delete_many({"company_id": TEST_CID})


async def test_grade_A_nf_resolvable():
    pid = await setup_test_data()
    ont = {"company_id": TEST_CID, "mac": "AA:01:02:03:04:01",
           "purchase_id": pid, "model": "FIBERHOME HG6145D"}
    v = await resolve_valuation(ont)
    assert v["valuation_grade"] == "A"
    assert v["valuation_source"] == "nf"
    assert v["valor_nf"] == 300.0
    assert v["valuation_needs_human_review"] is False
    print(f"✅ test_grade_A_nf_resolvable (nf={v['valor_nf']})")


async def test_grade_B_weighted_avg():
    """ONT com purchase_id mas a NF não tem unit_price → weighted_avg."""
    # Cria purchase sem unit_price nos items
    pid_b = "pur-r1-test-b"
    await db.purchases.insert_one({
        "id": pid_b, "company_id": TEST_CID, "type": "ont",
        "status": "confirmed",
        "items": [{"description": "X", "quantity": 1, "macs": []}],
    })
    ont = {"company_id": TEST_CID, "mac": "AA:99:99:99:99:99",
           "purchase_id": pid_b, "model": "ZTE F660"}
    # Como já temos a NF de R$ 300 do test_grade_A, weighted_avg=300.0
    v = await resolve_valuation(ont)
    assert v["valuation_grade"] == "B", f"esperava B, got {v['valuation_grade']}"
    assert v["valor_medio_ponderado"] == 300.0
    print(f"✅ test_grade_B_weighted_avg (avg={v['valor_medio_ponderado']})")


async def test_grade_C_model_canonical():
    """Sem purchase_id mas modelo válido."""
    ont = {"company_id": TEST_CID, "mac": "BB:00:00:00:00:01",
           "purchase_id": None, "model": "FIBERHOME HG6145D"}
    v = await resolve_valuation(ont)
    assert v["valuation_grade"] == "C"
    assert v["valuation_source"] == "model_canonical"
    assert v["valor_referencia"] == 220.0
    assert v["valor_nf"] is None
    print(f"✅ test_grade_C_model_canonical (ref={v['valor_referencia']})")


async def test_grade_D_reference_fallback():
    """Sem purchase_id, modelo não-lixo mas fora do MODEL_CANONICAL."""
    ont = {"company_id": TEST_CID, "mac": "CC:00:00:00:00:01",
           "purchase_id": None, "model": "Modelo Exótico XPTO"}
    v = await resolve_valuation(ont)
    assert v["valuation_grade"] == "D"
    assert v["valuation_source"] == "reference"
    assert v["valor_referencia"] == DEFAULT_REFERENCE_PRICE
    print(f"✅ test_grade_D_reference_fallback (ref={v['valor_referencia']})")


async def test_grade_F_phantom():
    """Sem purchase_id, modelo lixo → fantasma."""
    for bad_model in [None, "", "TestModel", "Desconhecido", "?"]:
        ont = {"company_id": TEST_CID, "mac": "DD:00:00:00:00:01",
               "purchase_id": None, "model": bad_model}
        v = await resolve_valuation(ont)
        assert v["valuation_grade"] == "F", \
            f"esperava F para model={bad_model!r}, got {v['valuation_grade']}"
        assert v["valuation_needs_human_review"] is True
        assert v["valuation_source"] == "unknown"
    print("✅ test_grade_F_phantom (5 variantes)")


def test_effective_value_priority():
    # NF ganha
    v1 = {"valor_nf": 300.0, "valor_medio_ponderado": 250.0, "valor_referencia": 85.0}
    assert effective_value(v1) == 300.0
    # weighted_avg quando NF None
    v2 = {"valor_nf": None, "valor_medio_ponderado": 250.0, "valor_referencia": 85.0}
    assert effective_value(v2) == 250.0
    # referencia quando ambos None
    v3 = {"valor_nf": None, "valor_medio_ponderado": None, "valor_referencia": 85.0}
    assert effective_value(v3) == 85.0
    # default quando tudo falta
    v4 = {}
    assert effective_value(v4) == DEFAULT_REFERENCE_PRICE
    print("✅ test_effective_value_priority")


async def test_ensure_indexes_idempotent():
    res1 = await ensure_indexes()
    assert all(res1.values()), f"índices falharam: {res1}"
    res2 = await ensure_indexes()  # 2ª chamada deve ser idempotente
    assert all(res2.values())
    print(f"✅ test_ensure_indexes_idempotent ({len(res1)} índices)")


async def main():
    await cleanup()
    test_is_model_garbage()
    test_lookup_model_canonical_greedy()
    await test_grade_A_nf_resolvable()
    await test_grade_B_weighted_avg()
    await test_grade_C_model_canonical()
    await test_grade_D_reference_fallback()
    await test_grade_F_phantom()
    test_effective_value_priority()
    await test_ensure_indexes_idempotent()
    await cleanup()
    print("\n🟢 TODOS OS SMOKE TESTS DA R1.1 PASSARAM")


if __name__ == "__main__":
    asyncio.run(main())
