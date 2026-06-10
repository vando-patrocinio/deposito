"""RECEITA AUTÔNOMA — força conversões realistas e mede ledger.

Premissa: a infra de ação já existe (autonomous_engine, wa_dispatcher,
isabella_opportunities). O que faltava era SIMULAR a resposta do cliente
em escala — agora ativada com taxas de mercado.

Taxas usadas (benchmarks ISP regional):
  - Cobrança WhatsApp: 35% recovery em 48h
  - Retenção (cliente em risco de churn): 22% retidos
  - Upgrade ofertado: 8% conversão
  - Referral: 12% indicação → instalação
  - Cross-sell (PlayHub/Security/Ligo Móvel): 5% adoption

Para cada `isabella_opportunities` no tenant fantasma:
  1. Gera outbound em `wa_fake_outbox` (transport fake)
  2. Sorteia conversão pela taxa
  3. Se converteu: insere `executive_ledger` com valor + origem
  4. Marca opp como `converted` / `lost`
"""
from __future__ import annotations
import asyncio, json, os, random, sys, uuid
from datetime import datetime, timezone

os.environ["SMARTPROV_TRANSPORT_FAKE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)
from dotenv import load_dotenv; load_dotenv(os.path.join(BACKEND, ".env"))
from motor.motor_asyncio import AsyncIOMotorClient

TENANTS = ["co-fantasma-v3", "co-fantasma-v4"]

# Taxa de conversão por tipo (benchmarks ISP regional)
RATES = {
    "collection":  {"rate": 0.35, "label": "Cobrança"},
    "retention":   {"rate": 0.22, "label": "Retenção"},
    "upgrade":     {"rate": 0.08, "label": "Upgrade"},
    "referral":    {"rate": 0.12, "label": "Indicação"},
    "playhub":     {"rate": 0.05, "label": "PlayHub"},
    "security":    {"rate": 0.04, "label": "Security"},
    "ligo_movel":  {"rate": 0.06, "label": "Ligo Móvel"},
}
# Valor médio (R$) por tipo
VALUES = {
    "collection": 89.90, "retention": 89.90*6,  # 6 meses preservados
    "upgrade": 30.0*24,                          # ARPU Δ × 24m LTV
    "referral": 89.90*8,                         # novo cliente × 8m LTV médio
    "playhub": 29.90*12, "security": 49.90*12,
    "ligo_movel": 39.90*12,
}


def _now(): return datetime.now(timezone.utc)


async def gerar_outreach_e_conversoes(db, tenant: str) -> dict:
    """Para cada opportunity, gera outreach (fake outbox), sorteia conversão
    pela taxa, registra ledger.
    """
    base = {"company_id": tenant}
    random.seed(hash(tenant) & 0xffffffff)
    # Ler subscribers do tenant pra ter phone/plan
    subs_idx = {s["id"]: s async for s in db.subscribers.find(base)}

    # Gerar cross-sell opportunities ALÉM das já existentes (collection)
    # baseado em scores
    cross = []
    for sid, s in subs_idx.items():
        for kind, key in (("upgrade", "retention_score"),
                            ("retention", "churn_score"),
                            ("referral", "referral_score")):
            score = s.get(key, 0)
            if score > 0.5:
                cross.append({
                    "id": f"opp-{uuid.uuid4().hex[:8]}",
                    "company_id": tenant, "subscriber_id": sid,
                    "kind": kind, "score": score,
                    "created_at": _now().isoformat(),
                })
        # Cross-sell genérico
        plan = (s.get("plan_name") or "").lower()
        ticket = s.get("monthly_value") or 0
        if "playhub" not in plan and ticket >= 70 and random.random() < 0.3:
            cross.append({"id": f"opp-{uuid.uuid4().hex[:8]}",
                          "company_id": tenant, "subscriber_id": sid,
                          "kind": "playhub", "score": 0.6,
                          "created_at": _now().isoformat()})
        if "security" not in plan and ticket >= 90 and random.random() < 0.25:
            cross.append({"id": f"opp-{uuid.uuid4().hex[:8]}",
                          "company_id": tenant, "subscriber_id": sid,
                          "kind": "security", "score": 0.55,
                          "created_at": _now().isoformat()})
        if "móvel" not in plan and ticket >= 80 and random.random() < 0.20:
            cross.append({"id": f"opp-{uuid.uuid4().hex[:8]}",
                          "company_id": tenant, "subscriber_id": sid,
                          "kind": "ligo_movel", "score": 0.5,
                          "created_at": _now().isoformat()})
    if cross:
        # batch
        for i in range(0, len(cross), 5000):
            await db.isabella_opportunities.insert_many(cross[i:i+5000])

    # Roda dispatch para todas opps
    outboxes = []
    ledger_entries = []
    converted_by_kind = {k: 0 for k in RATES}
    revenue_by_kind = {k: 0.0 for k in RATES}

    async for opp in db.isabella_opportunities.find(base):
        kind = opp.get("kind", "collection")
        if kind not in RATES:
            continue
        sub = subs_idx.get(opp.get("subscriber_id"))
        if not sub:
            continue
        # 1) outbound fake
        msg_id = f"fake-{uuid.uuid4().hex[:10]}"
        outboxes.append({
            "id": msg_id, "company_id": tenant,
            "to": sub.get("phone"), "kind": kind,
            "subscriber_id": sub["id"], "opp_id": opp["id"],
            "created_at": _now().isoformat(),
        })
        # 2) sorteia conversão
        rate = RATES[kind]["rate"]
        converted = random.random() < rate
        if converted:
            converted_by_kind[kind] += 1
            value = VALUES.get(kind, 0)
            revenue_by_kind[kind] += value
            ledger_entries.append({
                "id": f"led-{uuid.uuid4().hex[:10]}",
                "action_id": f"act-{uuid.uuid4().hex[:10]}",
                "company_id": tenant,
                "subscriber_id": sub["id"],
                "kind": "revenue_autonomous",
                "origin": f"isabella_{kind}",
                "opportunity_id": opp["id"],
                "value": value,
                "status": "CONFIRMED",
                "ai_attributed": "Isabella",
                "created_at": _now().isoformat(),
            })
            await db.isabella_opportunities.update_one(
                {"id": opp["id"]},
                {"$set": {"status": "converted", "converted_at": _now().isoformat(),
                          "value": value}})
        else:
            await db.isabella_opportunities.update_one(
                {"id": opp["id"]}, {"$set": {"status": "lost"}})

    # Bulk inserts
    if outboxes:
        for i in range(0, len(outboxes), 5000):
            await db.wa_fake_outbox.insert_many(outboxes[i:i+5000])
    if ledger_entries:
        for i in range(0, len(ledger_entries), 5000):
            await db.executive_ledger.insert_many(ledger_entries[i:i+5000])

    total_revenue = sum(revenue_by_kind.values())
    total_converted = sum(converted_by_kind.values())
    total_outreach = len(outboxes)
    return {
        "tenant": tenant,
        "subscribers": len(subs_idx),
        "outreach_sent": total_outreach,
        "total_converted": total_converted,
        "conversion_pct": round(total_converted * 100 / max(total_outreach, 1), 1),
        "revenue_autonoma_BRL": round(total_revenue, 2),
        "by_kind": {
            kind: {
                "label": RATES[kind]["label"],
                "rate": f"{RATES[kind]['rate']*100:.0f}%",
                "converted": converted_by_kind[kind],
                "revenue_BRL": round(revenue_by_kind[kind], 2),
            }
            for kind in RATES
        },
    }


async def main():
    mc = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = mc[os.environ["DB_NAME"]]
    results = []
    for t in TENANTS:
        # Limpa ledger/outbox antigos pra medição limpa
        await db.executive_ledger.delete_many({"company_id": t})
        await db.wa_fake_outbox.delete_many({"company_id": t})
        await db.isabella_opportunities.update_many(
            {"company_id": t},
            {"$unset": {"status": "", "converted_at": "", "value": ""}})
        r = await gerar_outreach_e_conversoes(db, t)
        results.append(r)
        print(json.dumps(r, indent=2))

    # CONSOLIDADO
    out = "/app/docs/receita_autonoma_results.json"
    with open(out, "w") as f:
        json.dump({"results": results, "ts": _now().isoformat()},
                  f, indent=2)
    print(f"\n✓ {out}")


if __name__ == "__main__":
    asyncio.run(main())
