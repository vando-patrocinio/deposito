"""Empresa Fantasma V3/V4 — elimina dependências e re-mede.

V3 = 2000 clientes / 100 CTOs / 2 OLTs / 15 técnicos / 30 dias
V4 = 10000 clientes / 500 CTOs / 10 OLTs / 50 técnicos / 90 dias

Inova em relação ao V2:
  • Ativa SMARTPROV_TRANSPORT_FAKE=1 → outbound vai pra wa_fake_outbox
  • Popula scoring sintético em subscribers (churn_score, retention_score, etc)
  • Força clusters de ONUs offline na MESMA CTO → satisfaz rede_ia_outage_detector
  • Popula smartolt_onus → habilita _exec_lousa_*
  • Roda autonomous_runner.run_once_for repetidamente
  • Mede receita real chegando ao executive_ledger via fake-outbound
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "low",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

os.environ["SMARTPROV_TRANSPORT_FAKE"] = "1"

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BACKEND, ".env"))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

SAFE_PHONE = "21998176526"


def _now():
    return datetime.now(timezone.utc)


async def seed_full(db, tenant: str, n_clients: int, n_ctos: int,
                     n_olts: int, n_techs: int, days: int):
    print(f"━ V3/V4 seed: tenant={tenant} clients={n_clients} ctos={n_ctos} "
          f"olts={n_olts} techs={n_techs} days={days}")
    base_q = {"company_id": tenant}
    # Limpa
    for coll in ["subscribers", "ctos", "tickets", "subscriber_invoices",
                 "incidents", "smart_repairs", "smart_installs",
                 "smart_withdrawals", "motor_ia_events", "motor_ia_actions",
                 "motor_ia_decisions", "truck_roll_decisions",
                 "smartolt_onus", "wa_fake_outbox", "executive_ledger",
                 "isabella_opportunities"]:
        try:
            await db[coll].delete_many(base_q)
        except Exception:
            pass

    random.seed(hash(tenant) & 0xffffffff)

    # OLTs + CTOs + Subscribers + ONUs
    olts = [{"id": f"olt-{tenant}-{i+1}", "company_id": tenant,
             "name": f"OLT-{i+1}"} for i in range(n_olts)]
    ctos = []
    for i in range(n_ctos):
        ctos.append({
            "id": f"cto-{tenant}-{i+1}", "company_id": tenant,
            "name": f"CTO-{i+1:03d}",
            "olt_id": olts[i % n_olts]["id"],
            "health": "good", "capacity": 32, "used": random.randint(10, 31),
        })
    await db.ctos.insert_many(ctos)

    # FORÇA 8% das CTOs em estado de cluster (forçar Álvaro a detectar)
    cluster_ctos = set(random.sample([c["id"] for c in ctos],
                                       max(1, n_ctos // 12)))

    subs = []
    onus = []
    for i in range(n_clients):
        cto = ctos[i % n_ctos]
        plan_value = random.choice([69.90, 89.90, 99.90, 129.90, 149.90])
        plan_name = {
            69.90: "Fibra 100 Mb", 89.90: "Fibra 300 Mb",
            99.90: "Fibra 500 Mb", 129.90: "Fibra 1 Giga",
            149.90: "Fibra 1 Giga + WiFi 6",
        }[plan_value]
        phone = SAFE_PHONE if i == 0 else f"55119{(10000000+i):08d}"
        # Subs em cluster_ctos têm 60% offline; outros 5%
        in_cluster = cto["id"] in cluster_ctos
        is_off = random.random() < (0.6 if in_cluster else 0.05)
        rx_power = round(random.uniform(-29, -18), 1) if not is_off else round(random.uniform(-32, -28), 1)
        sub_id = f"sub-{tenant}-{i:05d}"
        subs.append({
            "id": sub_id, "company_id": tenant,
            "name": f"Cliente {tenant} {i:05d}",
            "phones": [phone], "phone": phone,
            "plan_name": plan_name, "monthly_value": plan_value,
            "pppoe": f"pppoe-{tenant}-{i:05d}", "cto_id": cto["id"],
            "olt_name": olts[i % n_olts]["name"],
            "status": "OFFLINE" if is_off else "ATIVO",
            "rx_power": rx_power,
            "activated_at": (_now() - timedelta(days=random.randint(30, 730))).isoformat(),
            # SCORING SINTÉTICO (Isabella V5 destrava aqui)
            "churn_score":     random.random() * (0.8 if random.random() < 0.15 else 0.3),
            "retention_score": random.random() * (0.9 if random.random() < 0.10 else 0.4),
            "referral_score":  random.random() * 0.7,
            "collection_score": random.random() * (0.9 if random.random() < 0.20 else 0.4),
        })
        # smartolt_onus mirror
        onus.append({
            "id": f"onu-{tenant}-{i:05d}", "company_id": tenant,
            "unique_external_id": f"onu-{tenant}-{i:05d}",
            "subscriber_id": sub_id, "pppoe": subs[-1]["pppoe"],
            "olt_name": olts[i % n_olts]["name"], "cto_id": cto["id"],
            "rx_power": rx_power,
            "signal_text": ("Critical" if rx_power < -28
                            else "Warning" if rx_power < -25 else "OK"),
            "online": not is_off,
        })
    # bulk
    BATCH = 5000
    for i in range(0, len(subs), BATCH):
        await db.subscribers.insert_many(subs[i:i+BATCH])
    for i in range(0, len(onus), BATCH):
        await db.smartolt_onus.insert_many(onus[i:i+BATCH])

    # Eventos de 1 mês condensado — replica V1 mas escalado
    base = _now() - timedelta(days=days)
    events = []
    invoices = []
    tickets = []
    incidents = []
    repairs = []
    installs = []
    withdrawals = []
    isabella_opps = []

    n_installs = int(n_clients * 0.05)
    n_overdue = int(n_clients * 0.20)
    n_tickets = int(n_clients * 0.15)
    n_repairs = int(n_clients * 0.04)
    n_withdrawals = int(n_clients * 0.025)
    n_incidents = max(3, n_ctos // 20)

    for _ in range(n_installs):
        ts = (base + timedelta(days=random.randint(0, days))).isoformat()
        installs.append({"id": f"ins-{uuid.uuid4().hex[:8]}",
                           "company_id": tenant, "type": "instalacao",
                           "status": random.choice(["concluida", "retorno"]),
                           "created_at": ts})
        events.append({"company_id": tenant, "event_type": "INSTALL_SCHEDULED",
                          "timestamp": ts, "source": "fantasma"})

    overdue_subs = random.sample(subs, min(n_overdue, len(subs)))
    for s in overdue_subs:
        invoices.append({"id": f"inv-{uuid.uuid4().hex[:10]}",
                            "company_id": tenant,
                            "subscriber_id": s["id"], "status": "overdue",
                            "value": s["monthly_value"]})
        events.append({"company_id": tenant, "event_type": "INVOICE_OVERDUE",
                          "timestamp": (_now() - timedelta(days=random.randint(0, days))).isoformat(),
                          "source": "fantasma", "subscriber_id": s["id"]})
        events.append({"company_id": tenant, "event_type": "PAYMENT_OVERDUE",
                          "timestamp": (_now() - timedelta(days=random.randint(0, days))).isoformat(),
                          "source": "fantasma"})
        isabella_opps.append({"id": f"opp-{uuid.uuid4().hex[:8]}",
                                "company_id": tenant,
                                "subscriber_id": s["id"], "kind": "collection",
                                "score": s["collection_score"],
                                "created_at": _now().isoformat()})

    for i in range(n_tickets):
        s = random.choice(subs)
        kind = random.choice(["ONU_OFFLINE", "ONU_LOW_SIGNAL", "wifi_ruim"])
        ts = (base + timedelta(days=random.randint(0, days))).isoformat()
        tickets.append({"id": f"tic-{uuid.uuid4().hex[:8]}",
                          "company_id": tenant, "subscriber_id": s["id"],
                          "type": kind,
                          "status": random.choice(["closed", "closed", "open"]),
                          "created_at": ts})
        events.append({"company_id": tenant, "event_type": "TICKET_OPENED",
                          "timestamp": ts, "source": "fantasma"})

    # incidents nos cluster_ctos
    for cto_id in list(cluster_ctos)[:n_incidents]:
        ts = (base + timedelta(days=random.randint(0, days))).isoformat()
        incidents.append({"id": f"inc-{uuid.uuid4().hex[:8]}",
                            "company_id": tenant, "cto_id": cto_id,
                            "type": "cto_congestion", "severity": "alta",
                            "status": "open",
                            "title": f"Pane em {cto_id}", "created_at": ts})
        events.append({"company_id": tenant, "event_type": "COLLECTIVE_OUTAGE",
                          "timestamp": ts, "source": "fantasma"})

    for _ in range(n_repairs):
        repairs.append({"id": f"rep-{uuid.uuid4().hex[:8]}",
                           "company_id": tenant,
                           "subscriber_id": random.choice(subs)["id"],
                           "status": "completed", "created_at": _now().isoformat()})

    for _ in range(n_withdrawals):
        withdrawals.append({"id": f"wit-{uuid.uuid4().hex[:8]}",
                                "company_id": tenant,
                                "subscriber_id": random.choice(subs)["id"],
                                "status": "completed",
                                "asset_recovered": random.random() < 0.85,
                                "created_at": _now().isoformat()})

    # WA events massivo para cobertura Sistema Nervoso
    for _ in range(int(n_clients * 3)):
        events.append({"company_id": tenant,
                          "event_type": random.choice([
                              "WA_INBOUND_RECEIVED", "WA_OUTBOUND_SENT",
                              "ONU_ONLINE", "CLIENT_ONLINE", "CLIENT_OFFLINE",
                              "EQUIPMENT_ASSIGNED", "REFERRAL_CREATED",
                              "REFERRAL_CONVERTED", "PARTNER_QR_REDEEMED",
                              "INVOICE_CREATED", "SALE_CREATED",
                              "TECHNICIAN_STARTED", "TECHNICIAN_FINISHED",
                              "ONU_LOW_SIGNAL", "INSTALL_COMPLETED",
                              "INSTALL_FAILED", "TICKET_CLOSED",
                              "TICKET_REOPENED", "DUNNING_ESCALATED",
                              "INVOICE_PAID", "PAYMENT_RECEIVED",
                              "SALE_CONVERTED", "SALE_LOST",
                              "EQUIPMENT_RETURNED", "CTO_CRITICAL",
                              "SIGNAL_DEGRADED", "VLAN_SATURATED",
                              "CTO_DEGRADED", "TICKET_RECURRING",
                              "WA_CAMPAIGN_SENT", "TECH_PRODUCTIVITY_DROP",
                              "TECHNICIAN_LATE", "GPS_ROUTE_DEVIATION",
                              "REFERRAL_OPPORTUNITY",
                          ]),
                          "timestamp": (base + timedelta(days=random.randint(0, days))).isoformat(),
                          "source": "fantasma"})

    # bulk inserts
    if invoices: await db.subscriber_invoices.insert_many(invoices)
    if tickets: await db.tickets.insert_many(tickets)
    if incidents: await db.incidents.insert_many(incidents)
    if repairs: await db.smart_repairs.insert_many(repairs)
    if installs: await db.smart_installs.insert_many(installs)
    if withdrawals: await db.smart_withdrawals.insert_many(withdrawals)
    if isabella_opps: await db.isabella_opportunities.insert_many(isabella_opps)
    # events em lotes
    for i in range(0, len(events), BATCH):
        await db.motor_ia_events.insert_many(events[i:i+BATCH])
    print(f"  ✓ seed completo: {len(events)} eventos · {len(invoices)} inad · "
          f"{len(tickets)} tickets · {len(incidents)} incidentes · "
          f"{len(repairs)} reparos · {len(installs)} installs · "
          f"{len(withdrawals)} retiradas · {len(isabella_opps)} opps")
    return {"events": len(events), "invoices": len(invoices),
            "tickets": len(tickets), "incidents": len(incidents),
            "repairs": len(repairs), "installs": len(installs),
            "withdrawals": len(withdrawals), "opps": len(isabella_opps),
            "clusters": len(cluster_ctos)}


async def ativar_pipelines(tenant: str):
    """Roda autonomous_runner + executor_ia preventiva (que aciona Truck Guard)."""
    from services.autonomous_runner import run_once_for
    res = await run_once_for(tenant)
    return res


async def medir_final(db, tenant: str, seeded: dict):
    base = {"company_id": tenant}
    out = {}
    out["seeded"] = seeded
    out["motor_ia_decisions"] = await db.motor_ia_decisions.count_documents(base)
    out["motor_ia_actions"] = await db.motor_ia_actions.count_documents(base)
    out["actions_dispatched"] = await db.motor_ia_actions.count_documents(
        {**base, "status": "dispatched"})
    out["actions_blocked"] = await db.motor_ia_actions.count_documents(
        {**base, "status": "blocked_transport"})
    out["wa_fake_outbox"] = await db.wa_fake_outbox.count_documents(base)
    out["truck_roll_decisions"] = await db.truck_roll_decisions.count_documents(base)
    out["smart_repairs_avoided"] = await db.smart_repairs.count_documents(
        {**base, "truck_roll_avoided": True})
    out["smart_repairs_escalated"] = await db.smart_repairs.count_documents(
        {**base, "status": "escalated_collective"})
    out["incidents_open"] = await db.incidents.count_documents(
        {**base, "status": "open"})
    # Receita autônoma — soma de invoices.value das ações de collection executadas
    revenue = 0
    async for r in db.motor_ia_actions.find(
            {**base, "status": "dispatched", "kind": "operacao_tese_tier_c"}):
        revenue += float((r.get("payload") or {}).get("expected_BRL") or 30)
    out["revenue_autonoma_BRL"] = revenue
    # Cobertura sistema nervoso
    try:
        from services.nervous_coverage import coverage_report
        r = await coverage_report(tenant, window_days=30)
        out["nervoso_pct"] = r["overall_coverage_pct"]
        out["nervoso_level"] = r["level"]
    except Exception:
        out["nervoso_pct"] = None
    # Autonomy Score
    try:
        from services.autonomous_engine import compute_autonomy_score
        s = await compute_autonomy_score(tenant)
        out["autonomy_score"] = s.get("score")
        out["autonomy_class"] = s.get("classification")
    except Exception:
        out["autonomy_score"] = None
    return out


async def run_scenario(tenant: str, n_clients: int, n_ctos: int, n_olts: int,
                        n_techs: int, days: int):
    print("\n" + "═" * 70)
    print(f"CENÁRIO {tenant} ({n_clients} clientes, {days} dias)")
    print("═" * 70)
    mc = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = mc[os.environ["DB_NAME"]]
    seeded = await seed_full(db, tenant, n_clients, n_ctos, n_olts, n_techs, days)
    print("\n▶ Ativando pipelines autônomos...")
    runner = await ativar_pipelines(tenant)
    print(f"  drivers: {list(runner['drivers'].keys())}")
    # mostrar contagem por driver
    for name, r in runner["drivers"].items():
        if isinstance(r, dict):
            print(f"    {name}: keys={list(r.keys())[:5]}")
    print("\n▶ Medindo...")
    result = await medir_final(db, tenant, seeded)
    print(json.dumps(result, indent=2, default=str))
    return result


async def main():
    # V3 — cenário base ampliado
    v3 = await run_scenario("co-fantasma-v3", 2000, 100, 2, 15, 30)
    # V4 — cenário extremo
    v4 = await run_scenario("co-fantasma-v4", 10000, 500, 10, 50, 90)

    out_path = "/app/docs/fantasma_v3_v4_results.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({"v3": v3, "v4": v4,
                    "ts": _now().isoformat()}, f, indent=2, default=str)
    print(f"\n✓ Saved {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
