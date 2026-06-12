"""Audita o aprendizado de cada agente — últimos 30 dias.
Sem construir nada. Só descobrir.
"""
import asyncio
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient


async def go():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    cols = sorted(await db.list_collection_names())
    now = datetime.now(timezone.utc)
    cutoff_30d = (now - timedelta(days=30)).isoformat()

    def find_cols(*patterns):
        out = []
        for c in cols:
            for p in patterns:
                if p in c.lower():
                    out.append(c); break
        return out

    bq = {"company_id": "co-demo"}

    print("\n══════════════════════════════════════════════════════════════")
    print("AUDIT — APRENDIZADO PERSISTIDO POR AGENTE (últimos 30 dias)")
    print(f"db={os.environ['DB_NAME']}  company=co-demo")
    print(f"cutoff_30d={cutoff_30d}")
    print("══════════════════════════════════════════════════════════════\n")

    # 1) BUSCAR ESTRUTURAS DE APRENDIZADO
    learn_cols = find_cols("learning", "learnings", "lesson", "knowledge",
                            "memory", "memoria", "evolution", "evolutionary",
                            "feedback", "outcome", "corpus")
    print(f"[A] Collections candidatas a 'aprendizado': {len(learn_cols)}")
    for c in learn_cols:
        n = await db[c].count_documents({})
        n30 = await db[c].count_documents({"created_at": {"$gte": cutoff_30d}})
        n30b = await db[c].count_documents({"updated_at": {"$gte": cutoff_30d}})
        n30c = await db[c].count_documents({"ts": {"$gte": cutoff_30d}})
        recent = max(n30, n30b, n30c)
        flag = "VIVO" if recent > 0 else ("FRIO" if n > 0 else "VAZIO")
        print(f"   {flag:6s} | {c}: total={n}, 30d_atividade={recent}")

    # 2) ISABELLA — aprendizado evolutivo
    print("\n[B] ISABELLA — aprendizado evolutivo:")
    isab_learn = [c for c in cols if "isabella" in c.lower() and any(
        k in c.lower() for k in ("learn", "outcome", "memo",
                                    "experience", "scoring", "feedback",
                                    "policies", "playbook", "audit"))]
    for c in isab_learn:
        n = await db[c].count_documents(bq)
        n30 = await db[c].count_documents({**bq, "created_at": {"$gte": cutoff_30d}})
        d = await db[c].find_one(bq, sort=[("_id", -1)])
        last = (d or {}).get("created_at") or (d or {}).get("updated_at")
        print(f"   {c}: count(co-demo)={n} new_30d={n30} last={last}")

    # 3) ÁLVARO — aprendizado técnico
    print("\n[C] ÁLVARO — aprendizado técnico:")
    alv = [c for c in cols if "alvaro" in c.lower()]
    for c in alv:
        n = await db[c].count_documents(bq)
        n30 = await db[c].count_documents({**bq, "created_at": {"$gte": cutoff_30d}})
        d = await db[c].find_one(bq, sort=[("_id", -1)])
        last = (d or {}).get("created_at") or (d or {}).get("analyzed_at") or (d or {}).get("finished_at")
        sample_keys = sorted((d or {}).keys())[:8] if d else []
        print(f"   {c}: count(co-demo)={n} new_30d={n30} last={last}")
        print(f"      sample_keys={sample_keys}")

    # 4) Promoção/rebaixamento — playbook weights
    print("\n[D] PROMOÇÃO/REBAIXAMENTO (isabella_playbook_weights):")
    if "isabella_playbook_weights" in cols:
        n = await db.isabella_playbook_weights.count_documents(bq)
        n30 = await db.isabella_playbook_weights.count_documents({**bq,
            "updated_at": {"$gte": cutoff_30d}})
        promoted = await db.isabella_playbook_weights.count_documents({
            **bq, "weight": {"$gt": 1.0}})
        demoted = await db.isabella_playbook_weights.count_documents({
            **bq, "weight": {"$lt": 1.0}})
        print(f"   total={n} updated_30d={n30} promoted(>1.0)={promoted} demoted(<1.0)={demoted}")
        # 5 mais promovidos
        print("   Top 5 promovidos:")
        async for d in db.isabella_playbook_weights.find(bq).sort(
                "weight", -1).limit(5):
            print(f"     {d.get('key','?')}: weight={d.get('weight'):.2f} reason={(d.get('reason') or '')[:50]}")
        print("   Top 5 rebaixados:")
        async for d in db.isabella_playbook_weights.find(bq).sort(
                "weight", 1).limit(5):
            print(f"     {d.get('key','?')}: weight={d.get('weight'):.2f} reason={(d.get('reason') or '')[:50]}")
    else:
        print("   AUSENTE")

    # 5) Outcomes — vendas/rejeições
    print("\n[E] ISABELLA_OUTCOMES (vendas/rejeições/aprendizado):")
    if "isabella_outcomes" in cols:
        n = await db.isabella_outcomes.count_documents(bq)
        n30 = await db.isabella_outcomes.count_documents(
            {**bq, "created_at": {"$gte": cutoff_30d}})
        async for r in db.isabella_outcomes.aggregate([
            {"$match": bq},
            {"$group": {"_id": "$outcome", "n": {"$sum": 1}}}]):
            print(f"     outcome={r['_id']}: {r['n']}")
        print(f"   total={n} new_30d={n30}")
    else:
        print("   AUSENTE")

    # 6) Avaliador IA — fiscalização
    print("\n[F] AVALIADOR IA — fiscalização (últimos 30d):")
    for c in find_cols("avaliad", "tribunal", "ai_evaluation",
                         "ai_correction", "precision_audit"):
        n = await db[c].count_documents({"company_id": "co-demo"})
        n30 = await db[c].count_documents(
            {"company_id": "co-demo", "created_at": {"$gte": cutoff_30d}})
        print(f"   {c}: total={n} new_30d={n30}")

    # 7) Long-term memory / corpus
    print("\n[G] CORPUS / MEMÓRIA LONGA:")
    for c in find_cols("long_term", "corpus", "knowledge_graph",
                         "executive_memory", "policies"):
        n = await db[c].count_documents({})
        print(f"   {c}: total={n}")


asyncio.run(go())
