"""ad-hoc audit driver 1+3 — operação e rede"""
import asyncio
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient


async def go():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    print("════════════ DRIVER 1 — OPERAÇÃO: AUDITORIA TICKETS ════════════")

    print("\n[A] Por status:")
    async for r in db.tickets.aggregate(
        [{"$group": {"_id": "$status", "n": {"$sum": 1}}},
         {"$sort": {"n": -1}}]):
        print(f"  {r['_id']}: {r['n']}")

    print("\n[B] Open por company_id:")
    async for r in db.tickets.aggregate([
        {"$match": {"status": {"$in": ["aberta", "pendente", "open"]}}},
        {"$group": {"_id": "$company_id", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}]):
        print(f"  {r['_id']}: {r['n']}")

    print("\n[C] Idade dos abertos (co-demo):")
    now = datetime.now(timezone.utc)
    boundaries = [7, 30, 90, 365]
    prev = 0
    for d in boundaries + [99999]:
        cutoff_old = (now - timedelta(days=d)).isoformat()
        cutoff_new = (now - timedelta(days=prev)).isoformat() if prev else None
        q = {"status": {"$in": ["aberta", "pendente", "open"]},
             "company_id": "co-demo"}
        if cutoff_new:
            q["updated_at"] = {"$gte": cutoff_old, "$lt": cutoff_new}
        else:
            q["updated_at"] = {"$gte": cutoff_old}
        n = await db.tickets.count_documents(q)
        label = f"<={d}d" if d != 99999 else ">365d"
        print(f"  {label}: {n}")
        prev = d
    n_no_upd = await db.tickets.count_documents(
        {"status": {"$in": ["aberta", "pendente", "open"]},
         "company_id": "co-demo",
         "updated_at": {"$exists": False}})
    print(f"  sem updated_at: {n_no_upd}")

    # Created_at distribution
    print("\n[D] Idade dos abertos por created_at:")
    prev = 0
    for d in boundaries + [99999]:
        cutoff_old = (now - timedelta(days=d)).isoformat()
        cutoff_new = (now - timedelta(days=prev)).isoformat() if prev else None
        q = {"status": {"$in": ["aberta", "pendente", "open"]},
             "company_id": "co-demo"}
        if cutoff_new:
            q["created_at"] = {"$gte": cutoff_old, "$lt": cutoff_new}
        else:
            q["created_at"] = {"$gte": cutoff_old}
        n = await db.tickets.count_documents(q)
        label = f"<={d}d" if d != 99999 else ">365d"
        print(f"  {label}: {n}")
        prev = d

    print("\n[E] Marcados como seed:")
    n_seed = await db.tickets.count_documents({
        "status": {"$in": ["aberta", "pendente", "open"]},
        "company_id": "co-demo",
        "$or": [{"is_seed": True}, {"source": "seed"},
                {"is_demo": True}, {"seed": True}]})
    print(f"  is_seed/source=seed/is_demo: {n_seed}")

    print("\n[F] Duplicatas por subject+phone+status:")
    async for r in db.tickets.aggregate([
        {"$match": {"status": {"$in": ["aberta", "pendente", "open"]},
                     "company_id": "co-demo"}},
        {"$group": {"_id": {"subject": "$subject", "phone": "$phone"},
                     "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 5}]):
        print(f"  subject={r['_id'].get('subject','')[:30]} phone={r['_id'].get('phone','')} count={r['n']}")

    print("\n[G] Amostra dos 5 abertos mais antigos:")
    async for d in db.tickets.find(
        {"status": {"$in": ["aberta", "pendente", "open"]},
         "company_id": "co-demo"}, sort=[("_id", 1)]).limit(5):
        keys = sorted(d.keys())[:10]
        print(f"  id={d.get('id')} created={d.get('created_at')} "
              f"updated={d.get('updated_at')} status={d.get('status')} "
              f"source={d.get('source')} keys={keys}")

    print("\n════════════ DRIVER 3 — REDE: AUDITORIA ONUs ════════════")

    bq = {"company_id": "co-demo"}
    crit_q = {**bq, "status": {"$in": ["LOS", "Power fail", "Offline"]}}
    crit = await db.smartolt_onus.count_documents(crit_q)
    print(f"\n[A] Críticas totais (LOS/Power fail/Offline): {crit}")

    print("\n[B] Críticas por status:")
    async for r in db.smartolt_onus.aggregate([
        {"$match": crit_q},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        print(f"  {r['_id']}: {r['n']}")

    print("\n[C] Críticas idade (por updated_at se existir):")
    prev = 0
    for d in [30, 90, 365, 99999]:
        cutoff_old = (now - timedelta(days=d)).isoformat()
        cutoff_new = (now - timedelta(days=prev)).isoformat() if prev else None
        q = dict(crit_q)
        if cutoff_new:
            q["last_seen"] = {"$gte": cutoff_old, "$lt": cutoff_new}
        else:
            q["last_seen"] = {"$gte": cutoff_old}
        n = await db.smartolt_onus.count_documents(q)
        label = f"<={d}d" if d != 99999 else ">365d"
        print(f"  {label}: {n}")
        prev = d
    n_no = await db.smartolt_onus.count_documents(
        {**crit_q, "last_seen": {"$exists": False}})
    print(f"  sem last_seen: {n_no}")

    print("\n[D] Críticas órfãs (sem subscriber_id vinculado):")
    n_orfa = await db.smartolt_onus.count_documents({**crit_q,
        "$or": [{"subscriber_id": {"$exists": False}},
                {"subscriber_id": None}, {"subscriber_id": ""}]})
    print(f"  órfãs: {n_orfa}")

    print("\n[E] Outages recentes (incidents):")
    n_inc = await db.incidents.count_documents(bq)
    print(f"  incidents total: {n_inc}")
    async for r in db.incidents.aggregate([
        {"$match": bq},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        print(f"  {r['_id']}: {r['n']}")

    print("\n[F] network_outages:")
    n_out = await db.network_outages.count_documents(bq)
    open_out = await db.network_outages.count_documents(
        {**bq, "resolved_at": {"$exists": False}})
    print(f"  total: {n_out} abertos(sem resolved_at): {open_out}")


asyncio.run(go())
