"""OPERAÇÃO VALUATION AUDIT — read-only, zero escrita em banco.

Inspeciona stok_onts + purchases para responder:
  - Distribuição de campos de valor (existem? em quantos %?)
  - Distribuição de modelo (genérico vs específico)
  - Confronto SN/MAC presente vs valor ausente
  - Range mínimo/máximo de patrimônio
  - Grau de confiança
"""
import asyncio
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import db  # noqa: E402


PRICE_REFERENCE = {
    "F601": 65.0, "F660": 75.0, "F670L": 95.0,
    "HG6145D2": 220.0, "HG8145V5": 180.0,
    "WIFI6": 250.0, "WIFI7": 380.0,
    "GENERIC": 85.0, "UNKNOWN": 85.0,
}


async def inspect_stok_onts_schema():
    print("\n" + "═" * 70)
    print("§ A — SCHEMA REAL DE stok_onts")
    print("═" * 70)
    total = await db.stok_onts.count_documents({})
    print(f"Total de ONTs no sistema: {total}")
    if total == 0:
        return None
    sample = await db.stok_onts.find({}, {"_id": 0}).limit(50).to_list(50)
    field_freq = Counter()
    for d in sample:
        for k in d.keys():
            field_freq[k] += 1
    print(f"\nCampos presentes (amostra de {len(sample)} docs):")
    for k, n in field_freq.most_common():
        pct = (n / len(sample)) * 100
        print(f"  {k:30s} · {n:3d} / {len(sample)} ({pct:5.1f}%)")
    return total


async def inspect_value_fields():
    print("\n" + "═" * 70)
    print("§ B — CAMPOS DE VALOR FINANCEIRO EM stok_onts")
    print("═" * 70)
    total = await db.stok_onts.count_documents({})
    if total == 0:
        print("  banco vazio — pulando")
        return
    candidate_value_fields = [
        "unit_price", "unit_cost", "price", "cost",
        "valor", "valor_unitario", "valor_nf", "valor_medio",
        "valor_referencia", "purchase_price",
        "asset_value", "book_value",
    ]
    for f in candidate_value_fields:
        n_exists = await db.stok_onts.count_documents({f: {"$exists": True}})
        n_not_null = await db.stok_onts.count_documents(
            {f: {"$exists": True, "$ne": None}})
        n_gt0 = await db.stok_onts.count_documents(
            {f: {"$gt": 0}})
        if n_exists or n_not_null or n_gt0:
            print(f"  {f:25s} exists={n_exists} not_null={n_not_null} >0={n_gt0}")
        else:
            print(f"  {f:25s} 🔴 INEXISTENTE")
    # Bridge via purchase_id?
    n_with_pid = await db.stok_onts.count_documents({"purchase_id": {"$exists": True, "$ne": None}})
    print(f"\n  ONTs com purchase_id (bridge para preço NF): {n_with_pid} / {total} ({n_with_pid/total*100:.1f}%)")


async def inspect_model_field():
    print("\n" + "═" * 70)
    print("§ C — DISTRIBUIÇÃO DE MODELO (ONT)")
    print("═" * 70)
    candidate_model_fields = ["model", "modelo", "ont_model", "device_model",
                                "brand", "marca", "type", "tipo"]
    for f in candidate_model_fields:
        n = await db.stok_onts.count_documents({f: {"$exists": True}})
        if n:
            print(f"  '{f}' presente em {n} docs")
            rows = await db.stok_onts.aggregate([
                {"$group": {"_id": f"${f}", "n": {"$sum": 1}}},
                {"$sort": {"n": -1}}, {"$limit": 20}
            ]).to_list(20)
            for r in rows:
                print(f"    {str(r['_id']):30s} · {r['n']}")
        else:
            print(f"  '{f}' 🔴 INEXISTENTE")


async def inspect_purchases_unit_prices():
    print("\n" + "═" * 70)
    print("§ D — PREÇOS NA TABELA purchases (origem NF)")
    print("═" * 70)
    total = await db.purchases.count_documents({})
    print(f"Total de purchases: {total}")
    if total == 0:
        return
    sample = await db.purchases.find({}, {"_id": 0}).limit(20).to_list(20)
    if sample:
        # campos presentes
        keys = Counter()
        for d in sample:
            for k in d.keys():
                keys[k] += 1
        print("\n  Campos top-10 nas purchases:")
        for k, n in keys.most_common(15):
            print(f"    {k:30s} · {n}/{len(sample)}")
    # itens
    pipe = [
        {"$match": {"type": "ont"}},
        {"$project": {
            "id": 1, "status": 1, "type": 1,
            "items": 1, "total": 1, "unit_price": 1,
            "ont_count": {"$size": {"$ifNull": ["$items", []]}},
        }},
        {"$limit": 10},
    ]
    rows = await db.purchases.aggregate(pipe).to_list(10)
    print("\n  Top 10 ONT purchases (preview):")
    for r in rows:
        print(f"    id={r.get('id')} status={r.get('status')} "
              f"total={r.get('total')} unit_price={r.get('unit_price')} "
              f"items_count={r.get('ont_count')}")
    # Existem unit_price em items?
    sample_items = await db.purchases.find_one({"type": "ont", "items": {"$exists": True}})
    if sample_items and sample_items.get("items"):
        first_item = sample_items["items"][0]
        print(f"\n  Estrutura do 1º item (1º purchase):")
        for k, v in first_item.items():
            print(f"    {k}: {v}")


async def cross_check_pid_to_price():
    print("\n" + "═" * 70)
    print("§ E — CROSS-CHECK: ONTs com purchase_id têm preço resolvível?")
    print("═" * 70)
    total = await db.stok_onts.count_documents({})
    if total == 0:
        return
    cur = db.stok_onts.find({}, {"_id": 0, "id": 1, "mac": 1, "scan_sn": 1,
                                  "purchase_id": 1, "model": 1, "modelo": 1,
                                  "status": 1, "location_type": 1})
    onts = await cur.to_list(2000)
    has_pid = [o for o in onts if o.get("purchase_id")]
    print(f"  ONTs c/ purchase_id: {len(has_pid)} / {len(onts)}")
    resolved = 0
    unresolved = 0
    null_price = 0
    pids_seen = set()
    for o in has_pid:
        pid = o["purchase_id"]
        pids_seen.add(pid)
    for pid in pids_seen:
        p = await db.purchases.find_one({"id": pid}, {"_id": 0, "unit_price": 1,
                                                            "items": 1, "total": 1})
        if not p:
            unresolved += sum(1 for o in has_pid if o["purchase_id"] == pid)
            continue
        # tenta resolver preço
        unit_price = p.get("unit_price")
        if not unit_price and p.get("items"):
            it0 = p["items"][0] if p["items"] else {}
            unit_price = it0.get("unit_price") or it0.get("price")
        if not unit_price and p.get("total") and p.get("items"):
            try:
                unit_price = float(p["total"]) / max(1, len(p["items"]))
            except Exception:
                unit_price = None
        if unit_price and float(unit_price) > 0:
            resolved += sum(1 for o in has_pid if o["purchase_id"] == pid)
        else:
            null_price += sum(1 for o in has_pid if o["purchase_id"] == pid)
    print(f"  ONTs com preço NF resolvível: {resolved}")
    print(f"  ONTs com purchase_id mas preço NULL: {null_price}")
    print(f"  ONTs com purchase_id apontando para compra inexistente: {unresolved}")
    print(f"  ONTs SEM purchase_id (zero rastreabilidade): {len(onts) - len(has_pid)}")


async def confidence_grade():
    print("\n" + "═" * 70)
    print("§ F — GRAU DE CONFIANÇA DO VALUATION")
    print("═" * 70)
    total = await db.stok_onts.count_documents({})
    if total == 0:
        return
    with_pid = await db.stok_onts.count_documents({"purchase_id": {"$exists": True, "$ne": None}})
    with_sn = await db.stok_onts.count_documents({"scan_sn": {"$exists": True, "$ne": None}})
    with_mac = await db.stok_onts.count_documents({"mac": {"$exists": True, "$ne": None}})
    autosn = await db.stok_onts.count_documents({"scan_sn": {"$regex": "^AUTOSN_", "$options": "i"}})
    # heurística de confiança
    confidence_high = with_pid  # tem purchase_id → tenta NF
    confidence_low = total - with_pid
    print(f"  Total ONTs: {total}")
    print(f"  Com purchase_id: {with_pid} ({with_pid/total*100:.1f}%) — possível NF")
    print(f"  Sem purchase_id: {confidence_low} ({confidence_low/total*100:.1f}%) — apenas referência")
    print(f"  SN AUTOSN_* (bloqueado D3=a): {autosn}")
    print(f"  Com SN válido: {with_sn}")
    print(f"  Com MAC válido: {with_mac}")


async def patrimony_range():
    print("\n" + "═" * 70)
    print("§ G — RANGE PATRIMONIAL (mínimo / máximo possíveis)")
    print("═" * 70)
    total = await db.stok_onts.count_documents({})
    if total == 0:
        return
    # min: ONT mais barata do mercado (~R$ 50 modelo entry F601)
    min_unit = 50.0
    # max: ONT high-end WiFi 7 (~R$ 400)
    max_unit = 400.0
    # ref: R$ 85
    ref = 85.0
    print(f"  Cenário MIN  (R$ {min_unit:.2f}/un):  R$ {total * min_unit:,.2f}")
    print(f"  Cenário REF  (R$ {ref:.2f}/un):       R$ {total * ref:,.2f}")
    print(f"  Cenário MAX  (R$ {max_unit:.2f}/un): R$ {total * max_unit:,.2f}")
    print(f"  Δ MAX-MIN: R$ {(max_unit - min_unit) * total:,.2f} (incerteza absoluta)")
    print(f"  Δ MAX-MIN / REF: {((max_unit - min_unit) / ref) * 100:.0f}% (incerteza relativa)")


async def main():
    print("\n" + "█" * 70)
    print("█  OPERAÇÃO VALUATION AUDIT — read-only")
    print("█" * 70)
    await inspect_stok_onts_schema()
    await inspect_value_fields()
    await inspect_model_field()
    await inspect_purchases_unit_prices()
    await cross_check_pid_to_price()
    await confidence_grade()
    await patrimony_range()
    print("\n" + "█" * 70)
    print("█  DONE")
    print("█" * 70)


if __name__ == "__main__":
    asyncio.run(main())
