"""execute fix drivers — iter242b

Limpeza de débito histórico:
  • 671 tickets seeds Atlaz (operação) → arquivados
  • 213 ONUs órfãs (rede) → arquivadas

Tudo reversível: move pra collections _archived_iter242b.
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient


async def go():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    batch = f"iter242b-{uuid.uuid4().hex[:8]}"
    started = datetime.now(timezone.utc).isoformat()
    print(f"\nbatch_id = {batch}")
    print(f"started  = {started}\n")

    # ──────── DRIVER 1 — OPERAÇÃO ────────
    # Critério: co-demo, status aberto, subject vazio/null, criado no batch Atlaz
    # (vimos que 671 docs tem mesmo timestamp de criação)
    op_q = {
        "company_id": "co-demo",
        "status": {"$in": ["aberta", "pendente", "open"]},
        "$or": [
            {"subject": None}, {"subject": ""}, {"subject": {"$exists": False}},
        ],
    }
    op_match = await db.tickets.count_documents(op_q)
    print(f"OPERAÇÃO — Tickets matching seeds Atlaz: {op_match}")

    if op_match > 0:
        docs = []
        async for d in db.tickets.find(op_q):
            d["_archived_at"] = started
            d["_archived_batch_id"] = batch
            d["_archived_reason"] = "iter242b_atlaz_seed_no_subject"
            d["_archived_from"] = "tickets"
            docs.append(d)
        if docs:
            await db.tickets_archived_iter242b.insert_many(docs)
            res = await db.tickets.delete_many(op_q)
            print(f"  → arquivados: {len(docs)} | deletados de tickets: {res.deleted_count}")
    else:
        print("  → nada a arquivar")

    # ──────── DRIVER 3 — REDE ────────
    rede_q = {
        "company_id": "co-demo",
        "status": {"$in": ["LOS", "Power fail", "Offline"]},
        "$or": [
            {"subscriber_id": {"$exists": False}},
            {"subscriber_id": None}, {"subscriber_id": ""},
        ],
    }
    r_match = await db.smartolt_onus.count_documents(rede_q)
    print(f"\nREDE — ONUs críticas órfãs: {r_match}")

    if r_match > 0:
        docs = []
        async for d in db.smartolt_onus.find(rede_q):
            d["_archived_at"] = started
            d["_archived_batch_id"] = batch
            d["_archived_reason"] = "iter242b_onu_critica_orfa_sem_subscriber"
            d["_archived_from"] = "smartolt_onus"
            docs.append(d)
        if docs:
            await db.smartolt_onus_archived.insert_many(docs)
            res = await db.smartolt_onus.delete_many(rede_q)
            print(f"  → arquivados: {len(docs)} | deletados: {res.deleted_count}")
    else:
        print("  → nada a arquivar")

    # Registro de auditoria
    await db.iter242b_cleanup_batches.insert_one({
        "batch_id": batch,
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "tickets_archived": op_match,
        "onus_archived": r_match,
        "reversible_via": {
            "tickets": "db.tickets_archived_iter242b → tickets",
            "onus": "db.smartolt_onus_archived → smartolt_onus (filter _archived_batch_id)",
        },
    })

    print(f"\n✓ batch {batch} concluído")
    print(f"  tickets: {op_match} arquivados")
    print(f"  onus:    {r_match} arquivadas")


asyncio.run(go())
