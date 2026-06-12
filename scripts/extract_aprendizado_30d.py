"""Extrai amostras concretas do aprendizado dos agentes (30d) — SEM inventar."""
import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient


async def go():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    now = datetime.now(timezone.utc)
    cutoff_30d = (now - timedelta(days=30)).isoformat()

    def s(obj, n=120):
        if obj is None:
            return ""
        if isinstance(obj, (dict, list)):
            return json.dumps(obj, default=str)[:n]
        return str(obj)[:n]

    print("\n══════════ 1) MOTOR IA — APRENDIZADO REAL (30d) ══════════")
    # Distribuição por tipo
    print("\n[A] motor_ia_learnings — distribuição por kind:")
    async for r in db.motor_ia_learnings.aggregate([
        {"$match": {"created_at": {"$gte": cutoff_30d}}},
        {"$group": {"_id": "$kind", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 15}]):
        print(f"   {r['_id']}: {r['n']}")

    # Amostra do que foi aprendido
    print("\n[B] motor_ia_learnings — 5 amostras mais recentes (30d):")
    async for d in db.motor_ia_learnings.find(
            {"created_at": {"$gte": cutoff_30d}}).sort("_id", -1).limit(5):
        print(f"   kind={d.get('kind')} agent={d.get('agent') or d.get('source')}")
        print(f"     learned: {s(d.get('learning') or d.get('content') or d.get('summary') or d.get('text'))}")
        print(f"     ts={d.get('created_at')}")

    print("\n[C] motor_ia_outcomes — distribuição por outcome:")
    async for r in db.motor_ia_outcomes.aggregate([
        {"$match": {"created_at": {"$gte": cutoff_30d}}},
        {"$group": {"_id": "$outcome", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 10}]):
        print(f"   outcome={r['_id']}: {r['n']}")

    print("\n[D] motor_ia_outcomes — 3 amostras:")
    async for d in db.motor_ia_outcomes.find(
            {"created_at": {"$gte": cutoff_30d}}).sort("_id", -1).limit(3):
        print(f"   outcome={d.get('outcome')} agent={d.get('agent')}")
        print(f"     value={s(d.get('value') or d.get('result') or d.get('data'))}")

    print("\n══════════ 2) ISABELLA — APRENDIZADO REAL (30d) ══════════")
    print("\n[A] isabella_executive_policies (políticas aprendidas):")
    async for d in db.isabella_executive_policies.find(
            {"company_id": "co-demo"}).sort("_id", -1).limit(4):
        print(f"   id={d.get('id')} kind={d.get('kind') or d.get('policy_kind')}")
        print(f"     content: {s(d.get('policy') or d.get('content') or d.get('description'))}")
        print(f"     ts={d.get('created_at')}")

    print("\n[B] isabella_outcomes — vendas/perdas:")
    async for d in db.isabella_outcomes.find(
            {"company_id": "co-demo"}).sort("_id", -1).limit(4):
        print(f"   outcome={d.get('outcome')} signal={d.get('signal')}")
        print(f"     data: {s(d)}")

    print("\n[C] isabella_playbook_weights (promoções/rebaixamentos):")
    async for d in db.isabella_playbook_weights.find(
            {"company_id": "co-demo"}):
        print(f"   key={d.get('key')} weight={d.get('weight')}")
        print(f"     reason={d.get('reason')}")
        print(f"     updates={s(d.get('history'), 200)}")

    print("\n[D] isabella_precision_audits (auto-auditoria):")
    async for d in db.isabella_precision_audits.find(
            {"company_id": "co-demo"}).sort("_id", -1).limit(3):
        print(f"   id={d.get('id')}")
        print(f"     by_kind={s(d.get('by_kind'), 200)}")
        print(f"     totals={s(d.get('totals'), 200)}")

    print("\n══════════ 3) AVALIADOR — CORREÇÕES REAIS (30d) ══════════")
    print("\n[A] ai_corrections — distribuição:")
    async for r in db.ai_corrections.aggregate([
        {"$match": {"created_at": {"$gte": cutoff_30d}}},
        {"$group": {"_id": "$correction_type", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}]):
        print(f"   type={r['_id']}: {r['n']}")
    print("\n[B] ai_corrections — 5 amostras:")
    async for d in db.ai_corrections.find(
            {"created_at": {"$gte": cutoff_30d}}).sort("_id", -1).limit(5):
        print(f"   type={d.get('correction_type')} target={d.get('target_agent') or d.get('agent')}")
        print(f"     desc: {s(d.get('description') or d.get('correction') or d.get('what'))}")

    print("\n[C] ai_evaluations — TOP agentes avaliados (30d):")
    async for r in db.ai_evaluations.aggregate([
        {"$match": {"created_at": {"$gte": cutoff_30d}}},
        {"$group": {"_id": "$agent", "n": {"$sum": 1},
                     "avg_score": {"$avg": "$score"}}},
        {"$sort": {"n": -1}}, {"$limit": 10}]):
        avg = r.get("avg_score")
        avg_s = f"{avg:.2f}" if avg is not None else "—"
        print(f"   agent={r['_id']}: count={r['n']} avg_score={avg_s}")

    print("\n══════════ 4) CAMILA / TESOURARIA / PRESIDENTE ══════════")
    print("\n[A] treasurer_ai_decisions (Tesouraria):")
    n = await db.treasurer_ai_decisions.count_documents(
        {"company_id": "co-demo"})
    n30 = await db.treasurer_ai_decisions.count_documents(
        {"company_id": "co-demo", "created_at": {"$gte": cutoff_30d}})
    print(f"   total={n} new_30d={n30}")
    async for d in db.treasurer_ai_decisions.find(
            {"company_id": "co-demo"}).sort("_id", -1).limit(3):
        print(f"   decision={d.get('decision') or d.get('action')} reason={s(d.get('reason') or d.get('rationale'), 80)}")

    print("\n[B] motor_ia_daily_briefings (Presidente — Álvaro/Camila):")
    n = await db.motor_ia_daily_briefings.count_documents(
        {"company_id": "co-demo"})
    n30 = await db.motor_ia_daily_briefings.count_documents(
        {"company_id": "co-demo", "created_at": {"$gte": cutoff_30d}})
    print(f"   total={n} new_30d={n30}")
    async for d in db.motor_ia_daily_briefings.find(
            {"company_id": "co-demo"}).sort("_id", -1).limit(2):
        print(f"   id={d.get('id')} agent={d.get('agent') or d.get('persona')} kind={d.get('kind')}")
        print(f"     body: {s(d.get('body') or d.get('briefing'), 200)}")

    print("\n[C] knowledge_graph_nodes (Corpus operacional):")
    n = await db.knowledge_graph_nodes.count_documents({})
    print(f"   total={n}")
    async for d in db.knowledge_graph_nodes.find({}).limit(5):
        print(f"   type={d.get('type')} label={d.get('label')} content={s(d.get('content'), 80)}")

    print("\n══════════ 5) PROMOVIDO / REBAIXADO / DESCARTADO ══════════")
    print("\n[A] Promovido — weights > 1.0:")
    async for d in db.isabella_playbook_weights.find(
            {"company_id": "co-demo", "weight": {"$gt": 1.0}}):
        print(f"   {d.get('key')}: weight={d.get('weight')} reason={d.get('reason')}")
    print("\n[B] Rebaixado — weights < 1.0:")
    async for d in db.isabella_playbook_weights.find(
            {"company_id": "co-demo", "weight": {"$lt": 1.0}}):
        print(f"   {d.get('key')}: weight={d.get('weight')} reason={d.get('reason')}")

    # Agentes desativados/deprecated
    print("\n[C] aihub_agents — status:")
    async for r in db.aihub_agents.aggregate([
        {"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        print(f"   status={r['_id']}: {r['n']}")


asyncio.run(go())
