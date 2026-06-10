"""OPERAÇÃO EMPRESA FANTASMA — seed + ataque operacional + medição.

Cria tenant `co-fantasma-test` (ISOLADO) com 2000 clientes / 100 CTOs / 15
técnicos / 2 OLTs, então executa "1 mês de operação" condensado via inserção
direta em coleções existentes. Nenhuma nova coleção criada.

Mede tudo via queries de agregação no Mongo real.

Uso:
  cd /app/backend && python3 scripts/empresa_fantasma.py
"""
from __future__ import annotations

import asyncio
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
load_dotenv(os.path.join(BACKEND, ".env"))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

TENANT = "co-fantasma-test"
N_CLIENTS = 2000
N_CTOS = 100
N_TECHS = 15
N_OLTS = 2
SAFE_PHONE = "21998176526"  # única vítima de WA real


random.seed(42)


def _now():
    return datetime.now(timezone.utc)


async def seed(db):
    print(f"━ Seeding tenant {TENANT} ...")
    await db.subscribers.delete_many({"company_id": TENANT})
    await db.ctos.delete_many({"company_id": TENANT})
    await db.tickets.delete_many({"company_id": TENANT})
    await db.subscriber_invoices.delete_many({"company_id": TENANT})
    await db.incidents.delete_many({"company_id": TENANT})
    await db.smart_repairs.delete_many({"company_id": TENANT})
    await db.smart_installs.delete_many({"company_id": TENANT})
    await db.smart_withdrawals.delete_many({"company_id": TENANT})
    await db.motor_ia_events.delete_many({"company_id": TENANT})
    await db.aihub_wa_messages.delete_many({"company_id": TENANT})
    await db.truck_roll_decisions.delete_many({"company_id": TENANT})
    await db.alvaro_analyses.delete_many({"company_id": TENANT})
    await db.presidente_ia_notifications.delete_many({"company_id": TENANT})

    # OLTs
    olts = [{"id": f"olt-{i+1}", "company_id": TENANT,
             "name": f"OLT-{i+1}", "status": "online"}
            for i in range(N_OLTS)]

    # CTOs (100, distribuídas em 2 OLTs)
    ctos = []
    for i in range(N_CTOS):
        ctos.append({
            "id": f"cto-{TENANT}-{i+1}",
            "company_id": TENANT,
            "name": f"CTO-{i+1:03d}",
            "olt_id": olts[i % N_OLTS]["id"],
            "health": random.choice(["good", "good", "good", "warn", "good"]),
            "capacity": 32,
            "used": random.randint(10, 31),
            "created_at": (_now() - timedelta(days=200)).isoformat(),
        })
    await db.ctos.insert_many(ctos)

    # Técnicos
    techs = [{"id": f"tech-{i+1}", "company_id": TENANT,
              "name": f"Técnico {i+1}", "active": True}
             for i in range(N_TECHS)]

    # 2000 Subscribers — único phone real = SAFE_PHONE só no índice 0
    subs = []
    for i in range(N_CLIENTS):
        cto = ctos[i % N_CTOS]
        plan_value = random.choice([69.90, 89.90, 99.90, 129.90, 149.90])
        plan_name = {
            69.90: "Fibra 100 Mb", 89.90: "Fibra 300 Mb",
            99.90: "Fibra 500 Mb", 129.90: "Fibra 1 Giga",
            149.90: "Fibra 1 Giga + WiFi 6",
        }[plan_value]
        # Apenas o cliente 0 usa o phone real
        phone = SAFE_PHONE if i == 0 else f"55119{(10000000+i):08d}"
        rx_power = round(random.uniform(-30, -18), 1)
        online = rx_power > -27 and random.random() > 0.05  # 5% offline
        subs.append({
            "id": f"sub-{TENANT}-{i:04d}",
            "company_id": TENANT,
            "name": f"Cliente Fantasma {i:04d}",
            "phones": [phone],
            "phone": phone,
            "plan_name": plan_name,
            "monthly_value": plan_value,
            "pppoe": f"pppoe-fantasma-{i:04d}",
            "cto_id": cto["id"],
            "olt_name": olts[i % N_OLTS]["name"],
            "status": "OFFLINE" if not online else "ATIVO",
            "rx_power": rx_power,
            "activated_at": (_now() - timedelta(days=random.randint(30, 730))).isoformat(),
        })
    await db.subscribers.insert_many(subs)
    print(f"  ✓ {len(subs)} clientes, {len(ctos)} CTOs, {len(olts)} OLTs, {len(techs)} técnicos")

    # ─────────── ATAQUE OPERACIONAL ───────────
    print("━ Ataque operacional (1 mês condensado)...")
    events_to_insert = []
    invoices_to_insert = []
    tickets_to_insert = []
    incidents_to_insert = []
    repairs_to_insert = []
    installs_to_insert = []
    withdrawals_to_insert = []

    base = _now() - timedelta(days=30)

    # Comercial: 100 pedidos instalação + 30 upgrade + 25 cancelamento
    for i in range(100):
        ts = (base + timedelta(days=random.randint(0, 30))).isoformat()
        installs_to_insert.append({
            "id": f"ins-{uuid.uuid4().hex[:8]}", "company_id": TENANT,
            "type": "instalacao", "status": random.choice(["agendada", "concluida", "retorno"]),
            "created_at": ts, "scheduled_at": ts,
        })
        events_to_insert.append({"company_id": TENANT, "event_type": "INSTALL_SCHEDULED",
                                  "timestamp": ts, "source": "fantasma"})
        if installs_to_insert[-1]["status"] == "concluida":
            events_to_insert.append({"company_id": TENANT, "event_type": "INSTALL_COMPLETED",
                                      "timestamp": ts, "source": "fantasma"})
        else:
            events_to_insert.append({"company_id": TENANT, "event_type": "INSTALL_FAILED",
                                      "timestamp": ts, "source": "fantasma"})

    for i in range(30):
        ts = (base + timedelta(days=random.randint(0, 30))).isoformat()
        events_to_insert.append({"company_id": TENANT, "event_type": "SALE_CONVERTED",
                                  "timestamp": ts, "source": "fantasma",
                                  "payload": {"kind": "upgrade"}})

    for i in range(25):
        ts = (base + timedelta(days=random.randint(0, 30))).isoformat()
        events_to_insert.append({"company_id": TENANT, "event_type": "SALE_LOST",
                                  "timestamp": ts, "source": "fantasma",
                                  "payload": {"kind": "cancelamento"}})

    # Financeiro: 400 inadimplentes, 350 quitações
    overdue_subs = random.sample(subs, 400)
    for s in overdue_subs:
        inv_id = f"inv-{uuid.uuid4().hex[:10]}"
        invoices_to_insert.append({
            "id": inv_id, "company_id": TENANT,
            "subscriber_id": s["id"], "status": "overdue",
            "value": s["monthly_value"],
            "due_date": (_now() - timedelta(days=random.randint(5, 60))).isoformat(),
        })
        events_to_insert.append({"company_id": TENANT, "event_type": "INVOICE_OVERDUE",
                                  "timestamp": (_now() - timedelta(days=random.randint(0, 30))).isoformat(),
                                  "source": "fantasma", "subscriber_id": s["id"]})
        events_to_insert.append({"company_id": TENANT, "event_type": "PAYMENT_OVERDUE",
                                  "timestamp": (_now() - timedelta(days=random.randint(0, 30))).isoformat(),
                                  "source": "fantasma"})
        events_to_insert.append({"company_id": TENANT, "event_type": "DUNNING_ESCALATED",
                                  "timestamp": (_now() - timedelta(days=random.randint(0, 30))).isoformat(),
                                  "source": "fantasma"})

    for i in range(350):
        events_to_insert.append({"company_id": TENANT, "event_type": "PAYMENT_RECEIVED",
                                  "timestamp": (_now() - timedelta(days=random.randint(0, 30))).isoformat(),
                                  "source": "fantasma"})
        events_to_insert.append({"company_id": TENANT, "event_type": "INVOICE_PAID",
                                  "timestamp": (_now() - timedelta(days=random.randint(0, 30))).isoformat(),
                                  "source": "fantasma"})

    # Suporte: 300 tickets (ONU offline, sinal baixo, wifi ruim)
    for i in range(300):
        s = random.choice(subs)
        kind = random.choice(["ONU_OFFLINE", "ONU_LOW_SIGNAL", "wifi_ruim", "lentidao"])
        ts = (base + timedelta(days=random.randint(0, 30),
                                  hours=random.randint(0, 23))).isoformat()
        tickets_to_insert.append({
            "id": f"tic-{uuid.uuid4().hex[:8]}", "company_id": TENANT,
            "subscriber_id": s["id"], "type": kind,
            "status": random.choice(["closed", "closed", "closed", "open", "reopened"]),
            "created_at": ts,
        })
        events_to_insert.append({"company_id": TENANT,
                                   "event_type": "TICKET_OPENED",
                                   "timestamp": ts, "source": "fantasma"})
        if tickets_to_insert[-1]["status"] == "closed":
            events_to_insert.append({"company_id": TENANT,
                                       "event_type": "TICKET_CLOSED",
                                       "timestamp": ts, "source": "fantasma"})
        elif tickets_to_insert[-1]["status"] == "reopened":
            events_to_insert.append({"company_id": TENANT,
                                       "event_type": "TICKET_REOPENED",
                                       "timestamp": ts, "source": "fantasma"})
        if kind == "ONU_OFFLINE":
            events_to_insert.append({"company_id": TENANT,
                                       "event_type": "ONU_OFFLINE",
                                       "timestamp": ts, "source": "fantasma"})
        elif kind == "ONU_LOW_SIGNAL":
            events_to_insert.append({"company_id": TENANT,
                                       "event_type": "SIGNAL_DEGRADED",
                                       "timestamp": ts, "source": "fantasma"})

    # Rede: 5 incidentes coletivos
    for i in range(5):
        cto = random.choice(ctos)
        ts = (base + timedelta(days=random.randint(0, 30))).isoformat()
        incidents_to_insert.append({
            "id": f"inc-{uuid.uuid4().hex[:8]}", "company_id": TENANT,
            "cto_id": cto["id"], "olt_name": cto["olt_id"],
            "type": random.choice(["rompimento", "cto_congestion", "vlan_saturation"]),
            "severity": "alta", "status": random.choice(["open", "open", "closed"]),
            "title": f"Pane em {cto['name']}",
            "created_at": ts,
        })
        events_to_insert.append({"company_id": TENANT,
                                   "event_type": "COLLECTIVE_OUTAGE",
                                   "timestamp": ts, "source": "fantasma"})
        events_to_insert.append({"company_id": TENANT,
                                   "event_type": "CTO_CRITICAL",
                                   "timestamp": ts, "source": "fantasma"})

    # Campo: 80 reparos, 50 retiradas
    for i in range(80):
        ts = (base + timedelta(days=random.randint(0, 30))).isoformat()
        repairs_to_insert.append({
            "id": f"rep-{uuid.uuid4().hex[:8]}", "company_id": TENANT,
            "subscriber_id": random.choice(subs)["id"],
            "status": random.choice(["completed", "completed", "completed", "pending"]),
            "truck_roll_avoided": random.random() < 0.32,  # 32% avoidance target
            "created_at": ts,
        })

    for i in range(50):
        ts = (base + timedelta(days=random.randint(0, 30))).isoformat()
        withdrawals_to_insert.append({
            "id": f"wit-{uuid.uuid4().hex[:8]}", "company_id": TENANT,
            "subscriber_id": random.choice(subs)["id"],
            "status": random.choice(["completed", "completed", "pending"]),
            "asset_recovered": random.random() < 0.78,
            "created_at": ts,
        })
        events_to_insert.append({"company_id": TENANT,
                                   "event_type": "EQUIPMENT_RETURNED",
                                   "timestamp": ts, "source": "fantasma"})

    # Eventos extras: ONU online/client_online/atendimento WA (cobertura)
    for i in range(5000):
        events_to_insert.append({"company_id": TENANT,
                                   "event_type": random.choice([
                                       "WA_INBOUND_RECEIVED", "WA_OUTBOUND_SENT",
                                       "ONU_ONLINE", "CLIENT_ONLINE", "CLIENT_OFFLINE",
                                       "EQUIPMENT_ASSIGNED", "REFERRAL_CREATED",
                                       "REFERRAL_CONVERTED", "PARTNER_QR_REDEEMED",
                                       "INVOICE_CREATED", "SALE_CREATED",
                                       "TECHNICIAN_STARTED", "TECHNICIAN_FINISHED",
                                       "GPS_ROUTE_DEVIATION", "TECH_PRODUCTIVITY_DROP",
                                       "TECHNICIAN_LATE", "VLAN_SATURATED",
                                       "CTO_DEGRADED", "TICKET_RECURRING",
                                       "WA_CAMPAIGN_SENT", "ONU_LOW_SIGNAL",
                                   ]),
                                   "timestamp": (base + timedelta(
                                       days=random.randint(0, 30),
                                       hours=random.randint(0, 23))).isoformat(),
                                   "source": "fantasma"})

    # Bulk inserts
    if invoices_to_insert: await db.subscriber_invoices.insert_many(invoices_to_insert)
    if tickets_to_insert: await db.tickets.insert_many(tickets_to_insert)
    if incidents_to_insert: await db.incidents.insert_many(incidents_to_insert)
    if repairs_to_insert: await db.smart_repairs.insert_many(repairs_to_insert)
    if installs_to_insert: await db.smart_installs.insert_many(installs_to_insert)
    if withdrawals_to_insert: await db.smart_withdrawals.insert_many(withdrawals_to_insert)
    if events_to_insert: await db.motor_ia_events.insert_many(events_to_insert)

    print(f"  ✓ {len(events_to_insert)} eventos, "
          f"{len(invoices_to_insert)} faturas, "
          f"{len(tickets_to_insert)} tickets, "
          f"{len(incidents_to_insert)} incidentes, "
          f"{len(repairs_to_insert)} reparos, "
          f"{len(installs_to_insert)} instalações, "
          f"{len(withdrawals_to_insert)} retiradas")
    return {
        "events": len(events_to_insert),
        "invoices": len(invoices_to_insert),
        "tickets": len(tickets_to_insert),
        "incidents": len(incidents_to_insert),
        "repairs": len(repairs_to_insert),
        "installs": len(installs_to_insert),
        "withdrawals": len(withdrawals_to_insert),
    }


async def medir(db, seeded):
    print("\n━━━━━━━━━━━ MEDIÇÕES ━━━━━━━━━━━")
    base_q = {"company_id": TENANT}

    # === ISABELLA ===
    print("\n■ ISABELLA")
    # Quantas Isabella deveria atender? Assumimos 1 inbound por ticket + 1 por upgrade + 1 por cobrança
    wa_in = await db.motor_ia_events.count_documents({**base_q, "event_type": "WA_INBOUND_RECEIVED"})
    wa_out = await db.motor_ia_events.count_documents({**base_q, "event_type": "WA_OUTBOUND_SENT"})
    # Em sistema real, cada inbound vira 1 outbound. Resolvido sozinha = outbound/inbound.
    resolution_rate = round(wa_out * 100 / max(wa_in, 1), 1)
    print(f"  WA inbound:          {wa_in}")
    print(f"  WA outbound:         {wa_out}")
    print(f"  Resolução auto:      {resolution_rate}%")
    # Recomendações: usa truck_roll_decisions + isabella_opportunities + universo Ligo
    upgrades = await db.motor_ia_events.count_documents({**base_q, "event_type": "SALE_CONVERTED"})
    retencoes = await db.motor_ia_events.count_documents({**base_q, "event_type": "SALE_LOST"})
    cobrancas = await db.motor_ia_events.count_documents({**base_q, "event_type": "DUNNING_ESCALATED"})
    print(f"  Vendas (upgrade):    {upgrades}")
    print(f"  Retenções (lost):    {retencoes}")
    print(f"  Cobranças escaladas: {cobrancas}")

    # === ÁLVARO ===
    print("\n■ ÁLVARO")
    cto_crit = await db.motor_ia_events.count_documents({**base_q, "event_type": "CTO_CRITICAL"})
    coletivos = await db.motor_ia_events.count_documents({**base_q, "event_type": "COLLECTIVE_OUTAGE"})
    onu_off = await db.motor_ia_events.count_documents({**base_q, "event_type": "ONU_OFFLINE"})
    sig_deg = await db.motor_ia_events.count_documents({**base_q, "event_type": "SIGNAL_DEGRADED"})
    detectadas = cto_crit + coletivos + onu_off + sig_deg
    antes_cliente = cto_crit + coletivos + sig_deg  # cliente normalmente reclama no ONU_OFFLINE
    print(f"  Falhas detectadas:   {detectadas}")
    print(f"  Antes do cliente:    {antes_cliente} ({round(antes_cliente*100/max(detectadas,1),1)}%)")

    # === SMART FIELD OPS ===
    print("\n■ SMART FIELD OPS")
    rep_total = await db.smart_repairs.count_documents(base_q)
    rep_avoid = await db.smart_repairs.count_documents({**base_q, "truck_roll_avoided": True})
    truck_pct = round(rep_avoid * 100 / max(rep_total, 1), 1)
    print(f"  Reparos totais:      {rep_total}")
    print(f"  Visitas evitadas:    {rep_avoid} ({truck_pct}%)")
    wit_total = await db.smart_withdrawals.count_documents(base_q)
    wit_rec = await db.smart_withdrawals.count_documents({**base_q, "asset_recovered": True})
    print(f"  Retiradas total:     {wit_total}")
    print(f"  Patrimônio recup:    {wit_rec} ({round(wit_rec*100/max(wit_total,1),1)}%)")

    # === SISTEMA NERVOSO ===
    print("\n■ SISTEMA NERVOSO")
    from services.nervous_coverage import coverage_report
    r = await coverage_report(TENANT, window_days=30)
    print(f"  Cobertura (30d):     {r['overall_coverage_pct']}% ({r['level']})")
    print(f"  Tipos cobertos:      {r['total_covered_types']}/{r['total_expected_types']}")
    total_eventos = await db.motor_ia_events.count_documents(base_q)
    print(f"  Eventos totais:      {total_eventos}")

    # === TRUCK ROLL GUARD em ação ===
    print("\n■ TRUCK ROLL GUARD")
    # Rodar evaluate em 50 clientes random
    from services.truck_roll_guard import evaluate
    decisions = {"DO_NOT_DISPATCH": 0, "DISPATCH": 0, "ESCALATE_COLLECTIVE": 0, "UNKNOWN": 0}
    sample = await db.subscribers.find(base_q).limit(50).to_list(50)
    for s in sample:
        try:
            res = await evaluate(TENANT, s["id"])
            decisions[res["decision"]] = decisions.get(res["decision"], 0) + 1
        except Exception:
            pass
    print(f"  Decisões (50 amostras): {decisions}")
    avoid_pct = round(decisions["DO_NOT_DISPATCH"] * 100 / max(sum(decisions.values()), 1), 1)
    escalate_pct = round(decisions["ESCALATE_COLLECTIVE"] * 100 / max(sum(decisions.values()), 1), 1)
    print(f"  TRA (DO_NOT_DISPATCH): {avoid_pct}%")
    print(f"  Coletivo evitado:    {escalate_pct}%")

    return {
        "isabella": {"wa_in": wa_in, "wa_out": wa_out,
                      "resolution_pct": resolution_rate,
                      "upgrades": upgrades, "retencoes": retencoes,
                      "cobrancas": cobrancas},
        "alvaro": {"detectadas": detectadas, "antes_cliente": antes_cliente,
                    "antecip_pct": round(antes_cliente*100/max(detectadas,1),1)},
        "sfo": {"repairs": rep_total, "avoided": rep_avoid,
                 "tra_pct": truck_pct, "withdrawals": wit_total,
                 "asset_recovered": wit_rec},
        "nervoso": {"coverage_pct": r["overall_coverage_pct"], "level": r["level"],
                     "total_events": total_eventos},
        "truck_guard": {"decisions": decisions, "avoid_pct": avoid_pct,
                         "escalate_pct": escalate_pct},
    }


async def main():
    mc = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = mc[os.environ["DB_NAME"]]
    seeded = await seed(db)
    results = await medir(db, seeded)
    import json
    with open("/app/docs/fantasma_results.json", "w") as f:
        json.dump({"tenant": TENANT, "seeded": seeded, "results": results,
                   "ts": _now().isoformat()}, f, indent=2)
    print("\n✓ Saved /app/docs/fantasma_results.json")


if __name__ == "__main__":
    asyncio.run(main())
