"""iter244 — Auditoria honesta dos 8 testes CTO.

Para cada teste:
  - Query exata no DB.
  - Resultado bruto.
  - Sem inferência. Sem projeção.
"""
import asyncio
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient


async def go():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    bq = {"company_id": "co-demo"}

    print("\n══════════ TESTE 1 — RECEITA REAL (não hipótese) ══════════")
    # Pega 5 docs FAILED com phone e cruza com pagamentos reais
    print("\n[A] 5 docs FAILED do autonomous_engine — trilha completa:")
    n = 0
    async for d in db.motor_ia_learnings.find(
        {"agent": "autonomous_engine",
         "learning_text": {"$regex": "FAILED"}}).sort("_id", -1).limit(5):
        n += 1
        action_id = d.get("action_id")
        # Procura a action original
        action = await db.motor_ia_actions.find_one(
            {"$or": [{"action_id": action_id}, {"id": action_id}]})
        phone = (action or {}).get("phone") or (action or {}).get("target_phone")
        print(f"\n  [{n}] action_id={action_id} delta=R$ {d.get('financial_delta_BRL',0):.2f}")
        print(f"      phone={phone}")
        print(f"      ts={d.get('created_at')}")
        if phone:
            paid = await db.payments.count_documents({"phone": phone})
            inv = await db.invoices.count_documents({"phone": phone})
            sub = await db.subscribers.find_one({"phone": phone})
            print(f"      cliente_existe={'YES' if sub else 'NO'}")
            print(f"      payments={paid} invoices={inv}")
    # Receita real medida: payments com valor>0 nos últimos 30d
    print("\n[B] Receita real medida no DB (payments com amount>0, 30d):")
    paid_30d = []
    pipeline = [
        {"$match": {"created_at": {"$gte": cutoff}}},
        {"$group": {"_id": None,
                     "total": {"$sum": "$amount"},
                     "n": {"$sum": 1}}},
    ]
    async for r in db.payments.aggregate(pipeline):
        paid_30d.append(r)
    if paid_30d:
        print(f"   payments 30d: count={paid_30d[0]['n']} total=R$ {paid_30d[0]['total']:.2f}")
    else:
        print("   payments 30d: vazio")
    # Receita real atribuída ao motor_ia (action→cash)
    print("\n[C] Action→Cash REAL (motor_ia_outcomes com actual_BRL>0):")
    async for r in db.motor_ia_outcomes.aggregate([
        {"$match": {"actual_BRL": {"$gt": 0},
                     "created_at": {"$gte": cutoff}}},
        {"$group": {"_id": None,
                     "total": {"$sum": "$actual_BRL"},
                     "n": {"$sum": 1}}}]):
        print(f"   outcomes com cash real: count={r['n']} total=R$ {r['total']:.2f}")

    print("\n══════════ TESTE 2 — ISABELLA produção ══════════")
    # Total atendimentos
    msg_in = await db.aihub_wa_messages.count_documents(
        {**bq, "direction": "in"})
    msg_out = await db.aihub_wa_messages.count_documents(
        {**bq, "direction": "out"})
    conversas = await db.wa_conversations.count_documents(bq)
    opp_total = await db.isabella_opportunities.count_documents(bq)
    opp_cmd = await db.isabella_commander_opportunities.count_documents(bq)
    follow = await db.isabella_followups.count_documents(bq)
    outcomes = await db.isabella_outcomes.count_documents(bq)
    print(f"   msgs IN: {msg_in}  OUT: {msg_out}")
    print(f"   conversas: {conversas}")
    print(f"   opportunities (isabella): {opp_total}")
    print(f"   opportunities (commander): {opp_cmd}")
    print(f"   followups: {follow}")
    print(f"   outcomes: {outcomes}")
    # Opps por status
    print("\n[B] isabella_opportunities por status:")
    async for r in db.isabella_opportunities.aggregate([
        {"$match": bq},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 10}]):
        print(f"   {r['_id']}: {r['n']}")

    print("\n══════════ TESTE 3 — ÁLVARO ══════════")
    smartolt_total = await db.smartolt_onus.count_documents(bq)
    # Eventos smartolt
    n_events = 0
    for c in ["smartolt_zone_audit", "smartolt_predictive",
              "smartolt_zone_logs", "rede_ia_events"]:
        if c in await db.list_collection_names():
            cnt = await db[c].count_documents({})
            n_events += cnt
            print(f"   {c}: {cnt}")
    # Analyses produzidas
    analyses = await db.alvaro_analyses.count_documents(bq)
    reports = await db.alvaro_reports.count_documents(bq)
    # Quantos eventos smartolt viraram conhecimento (motor_ia_learnings smartolt)
    learnings_smart = await db.motor_ia_learnings.count_documents(
        {"kind": "smartolt_enrichment"})
    print(f"\n   eventos SmartOLT registrados: {n_events}")
    print(f"   alvaro_analyses: {analyses}")
    print(f"   alvaro_reports: {reports}")
    print(f"   learnings smartolt_enrichment: {learnings_smart}")
    # Ações Álvaro
    actions_alvaro = await db.motor_ia_actions.count_documents(
        {**bq, "agent": "alvaro"})
    print(f"   motor_ia_actions com agent=alvaro: {actions_alvaro}")

    print("\n══════════ TESTE 4 — MEMÓRIA ORGANIZACIONAL ══════════")
    weights_total = await db.isabella_playbook_weights.count_documents(bq)
    promoted = await db.isabella_playbook_weights.count_documents(
        {**bq, "weight": {"$gt": 1.0}})
    demoted = await db.isabella_playbook_weights.count_documents(
        {**bq, "weight": {"$lt": 1.0}})
    print(f"   playbook_weights total: {weights_total}")
    print(f"   promoted (>1.0): {promoted}")
    print(f"   demoted (<1.0): {demoted}")
    # Versionamento de prompts/policies
    print("\n[B] isabella_executive_policies — versões:")
    async for r in db.isabella_executive_policies.aggregate([
        {"$match": bq},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        print(f"   {r['_id']}: {r['n']}")
    print("\n[C] Existe automação que promove/rebaixa? Procurando schedulers...")
    # Cron jobs registrados? olha o server.py refs
    print("   busca services/isabella_learning.py para update lógico...")

    print("\n══════════ TESTE 5 — EVOLUÇÃO AUTOMÁTICA ══════════")
    # Top 50 aprendizados (com financial_delta_BRL)
    top = []
    async for d in db.motor_ia_learnings.find(
            {"financial_delta_BRL": {"$exists": True}}
        ).sort("financial_delta_BRL", -1).limit(50):
        top.append({
            "text": (d.get("learning_text") or "")[:80],
            "delta": d.get("financial_delta_BRL"),
            "agent": d.get("agent"),
            "ts": d.get("created_at"),
        })
    print(f"   top 50 aprendizados captados: {len(top)}")
    if top:
        print(f"   #1 melhor: delta=R$ {top[0]['delta']:.2f} {top[0]['text'][:60]}")
        print(f"   #50 pior:  delta=R$ {top[-1]['delta']:.2f} {top[-1]['text'][:60]}")
    # Classificação automatica? Procura tags
    n_classified = await db.motor_ia_learnings.count_documents(
        {"status": {"$in": ["promoted", "observation",
                              "demoted", "discarded"]}})
    print(f"   docs com status de classificação: {n_classified}")

    print("\n══════════ TESTE 6 — PRESIDENTE GOVERNA? ══════════")
    # Decisões registradas
    for c in ["presidente_decisions", "presidente_actions",
              "conselho_ia_decisions", "motor_ia_actions"]:
        if c in await db.list_collection_names():
            n = await db[c].count_documents({**bq,
                "created_at": {"$gte": cutoff}})
            print(f"   {c}: novos em 30d = {n}")

    print("\n══════════ TESTE 7 — TESOURARIA ══════════")
    print("\n[A] treasurer_ai_decisions detalhe:")
    async for d in db.treasurer_ai_decisions.find(bq).sort("_id", -1).limit(8):
        print(f"   decision={d.get('decision')} reason={d.get('reason') or '(sem razão)'}")
        print(f"     payment_id={d.get('payment_id')} amount={d.get('amount_brl')}")
    # bloqueios efetivos
    blocked = await db.scheduled_payments.count_documents(
        {**bq, "status": "blocked_risk"})
    print(f"\n   scheduled_payments com blocked_risk: {blocked}")

    print("\n══════════ TESTE 8 — UNIVERSO LIGO conversão ══════════")
    pitches = await db.referrals.count_documents(bq) if "referrals" in await db.list_collection_names() else 0
    # Loyalty opportunities por status
    print("\n[A] loyalty_opportunities por status:")
    if "loyalty_opportunities" in await db.list_collection_names():
        async for r in db.loyalty_opportunities.aggregate([
            {"$match": bq},
            {"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
            print(f"   {r['_id']}: {r['n']}")
    # Receita Universo Ligo
    print("\n[B] executive_ledger kinds Universo Ligo:")
    async for r in db.executive_ledger.aggregate([
        {"$match": {**bq, "kind": {"$regex": "LIGO|UNIVERSO", "$options": "i"}}},
        {"$group": {"_id": "$kind",
                     "n": {"$sum": 1},
                     "value": {"$sum": "$value_brl"}}}]):
        v = r.get("value") or 0
        print(f"   {r['_id']}: n={r['n']} valor_total=R$ {v:.2f}")


asyncio.run(go())
