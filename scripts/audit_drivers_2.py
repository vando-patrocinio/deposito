"""audit drivers 2 (estoque), 4 (vendas), 5 (segurança)"""
import asyncio
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient


async def go():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    cols = sorted(await db.list_collection_names())

    print("════════════ DRIVER 2 — ESTOQUE ════════════")
    patterns = ["estoque", "stok", "inventory", "equipamento", "equipment",
                "retir", "instal", "asset", "warehouse", "sku"]
    hits = set()
    for p in patterns:
        for c in cols:
            if p in c.lower():
                hits.add(c)
    print(f"\n[A] Collections candidatas a estoque:")
    for c in sorted(hits):
        n = await db[c].count_documents({})
        print(f"  {c}: {n} docs")

    print("\n[B] Detalhe das mais relevantes:")
    for col in ["stok_items", "stok_movements", "stok_transfers",
                "client_equipment_history", "field_equipment_returns",
                "retirada_workflows", "smart_field_v2_items",
                "asset_assignments", "atlaz_estoque", "equipment_used"]:
        if col in cols:
            n = await db[col].count_documents({})
            d = await db[col].find_one({}, sort=[("_id", -1)])
            keys = sorted((d or {}).keys())[:8] if d else []
            print(f"  {col}: count={n} sample_keys={keys}")

    print("\n════════════ DRIVER 4 — VENDAS / FUNIL ════════════")
    print("\n[A] Collections candidatas:")
    for p in ["sales", "lead", "proposta", "proposal", "instala", "ativacao",
              "winback", "opportun", "funnel"]:
        for c in cols:
            if p in c.lower():
                n = await db[c].count_documents({"company_id": "co-demo"})
                d = await db[c].find_one({}, sort=[("_id", -1)])
                keys = sorted((d or {}).keys())[:6] if d else []
                print(f"  {c}: count(co-demo)={n} keys={keys}")

    print("\n[B] isabella_opportunities — distribuição por status:")
    async for r in db.isabella_opportunities.aggregate([
        {"$match": {"company_id": "co-demo"}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 15}]):
        print(f"  {r['_id']}: {r['n']}")

    print("\n[C] subscribers — distribuição por status:")
    async for r in db.subscribers.aggregate([
        {"$match": {"company_id": "co-demo"}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 10}]):
        print(f"  {r['_id']}: {r['n']}")

    print("\n[D] subscribers novos por mês (created_at):")
    async for r in db.subscribers.aggregate([
        {"$match": {"company_id": "co-demo", "created_at": {"$exists": True}}},
        {"$project": {"ym": {"$substr": ["$created_at", 0, 7]}}},
        {"$group": {"_id": "$ym", "n": {"$sum": 1}}},
        {"$sort": {"_id": -1}}, {"$limit": 6}]):
        print(f"  {r['_id']}: {r['n']} novos")

    print("\n════════════ DRIVER 5 — SEGURANÇA ════════════")
    print("\n[A] Collections candidatas:")
    for p in ["shield", "audit", "security", "lgpd", "kill_switch",
              "rbac", "mock", "anti_", "tribunal"]:
        for c in cols:
            if p in c.lower():
                n = await db[c].count_documents({})
                d = await db[c].find_one({}, sort=[("_id", -1)])
                keys = sorted((d or {}).keys())[:6] if d else []
                print(f"  {c}: count={n} keys={keys}")


asyncio.run(go())
