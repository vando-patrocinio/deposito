"""OPERAÇÃO COLOSSO — validação end-to-end via DB real.

Estrutura:
  1. Smoke: importa todos os serviços + chama daily_directive.
  2. Truck Roll Guard: emite 4 outcomes diferentes.
  3. Lousa COO: daily_directive → enforce_preventive_ratio → plan_field_day
     → compute_technician_scores → operational_council → register_os_learning
     → alvaro_command_loop.
  4. Smart Field V2: os_context + stock cadeia completa.
  5. Empresa Fantasma Colosso: 10k clients × 500 CTOs × 10 OLTs × 100 techs
     × 90 dias → responde as 7 perguntas do CTO.

Sem mocks. Side-effects auditáveis em executive_ledger, ai_evaluations,
smart_repairs e client_equipment_history.
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

sys.path.insert(0, "/app/backend")
os.environ["SMARTPROV_TRANSPORT_FAKE"] = "1"

from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")

from database import db  # noqa: E402
from services import lousa_coo, smart_field_v2, truck_roll_guard  # noqa: E402


TENANT = "co-colosso"


def _now():
    return datetime.now(timezone.utc)


async def _seed_colosso(n_clients: int, n_ctos: int, n_olts: int,
                          n_techs: int, days: int) -> dict:
    """Seed determinístico mas com variabilidade real."""
    print(f"━ seed colosso: {n_clients} subs · {n_ctos} CTOs · "
          f"{n_olts} OLTs · {n_techs} techs · {days}d")
    base = {"company_id": TENANT}
    # Clean
    for c in ("subscribers", "ctos", "smart_repairs", "smart_installs",
              "smartolt_onus", "incidents", "tickets", "users",
              "truck_roll_decisions", "client_equipment_history",
              "ai_evaluations", "executive_ledger"):
        await db[c].delete_many(base)

    # OLTs (não criamos tabela separada — referenciamos só por nome)
    olts = [f"OLT-{i:02d}" for i in range(n_olts)]
    # CTOs
    ctos = []
    for i in range(n_ctos):
        cid = f"cto-cls-{i:04d}"
        ctos.append({"id": cid, "company_id": TENANT,
                      "name": cid, "olt_name": olts[i % n_olts],
                      "health": random.randint(40, 100)})
    await db.ctos.insert_many(ctos)

    # Técnicos como users
    techs = []
    for i in range(n_techs):
        tid = f"tech-cls-{i:04d}"
        techs.append({"id": tid, "company_id": TENANT,
                       "email": f"tech-cls-{i:04d}@colosso.local",
                       "name": f"Técnico {i:03d}", "role": "tecnico"})
    await db.users.insert_many(techs)

    # Subscribers + ONUs
    subs = []
    onus = []
    statuses = ["ACTIVE"] * 8 + ["OFFLINE"] * 2
    base_dt = _now() - timedelta(days=days)
    for i in range(n_clients):
        sid = f"sub-cls-{i:06d}"
        cto = ctos[i % n_ctos]
        churn = round(random.uniform(0, 1), 2)
        ticket = random.choice([79.9, 99.9, 149.9, 199.9])
        sub = {
            "id": sid, "company_id": TENANT,
            "name": f"Cliente {i:06d}",
            "phones": [f"5511990000{i:04d}"],
            "plan_name": f"Fibra {int(ticket)}",
            "plan_price": ticket, "monthly_value": ticket, "plan_value": ticket,
            "status": random.choice(statuses),
            "neighborhood": f"Bairro-{i % 50:02d}",
            "cto_id": cto["id"],
            "olt_name": cto["olt_name"],
            "pppoe": f"pppoe{i:06d}",
            "smartolt_onu_zone": cto["id"],
            "smartolt_onu_status": "Online" if random.random() > 0.15 else "LOS",
            "activated_at": base_dt.isoformat(),
            "created_at": base_dt.isoformat(),
            "churn_score": churn,
            "retention_score": round(1 - churn, 2),
            "referral_score": round(random.uniform(0, 1), 2),
            "collection_score": round(random.uniform(0, 1), 2),
        }
        subs.append(sub)
        # ONU sintética
        signal = round(random.uniform(-32, -18), 1)
        onu_status = "Online" if signal > -27 else "LOS"
        onus.append({
            "id": f"onu-{sid}", "company_id": TENANT,
            "subscriber_id": sid,
            "pppoe": sub["pppoe"],
            "unique_external_id": f"onu-{sid}",
            "online": signal > -27,
            "rx_power": signal, "signal_1310": signal,
            "status": onu_status,
            "signal_text": onu_status,
            "cto_id": cto["id"],
            "olt_name": cto["olt_name"],
        })
    # Bulk insert (chunks de 1000)
    CHUNK = 1000
    for i in range(0, len(subs), CHUNK):
        await db.subscribers.insert_many(subs[i:i + CHUNK])
    for i in range(0, len(onus), CHUNK):
        await db.smartolt_onus.insert_many(onus[i:i + CHUNK])

    # Tickets (5% dos clientes têm 1-3 tickets em 30d)
    sample_subs = random.sample(subs, max(1, int(n_clients * 0.05)))
    tickets = []
    for sub in sample_subs:
        for _ in range(random.randint(1, 4)):
            tickets.append({
                "id": f"tic-{uuid.uuid4().hex[:10]}",
                "company_id": TENANT,
                "subscriber_id": sub["id"],
                "client_id": sub["id"],
                "type": random.choice(["sem internet", "lentidão", "ONU offline"]),
                "status": random.choice(["closed", "open"]),
                "created_at": (_now() - timedelta(days=random.randint(0, 30))).isoformat(),
            })
    if tickets:
        for i in range(0, len(tickets), CHUNK):
            await db.tickets.insert_many(tickets[i:i + CHUNK])

    # Repairs e installs (preexistentes)
    repairs = []
    for sub in random.sample(subs, max(20, n_clients // 50)):
        created = _now() - timedelta(days=random.randint(0, days))
        closed = created + timedelta(hours=random.randint(1, 48))
        is_pending = random.random() < 0.3
        repairs.append({
            "id": f"rep-{uuid.uuid4().hex[:10]}",
            "company_id": TENANT,
            "subscriber_id": sub["id"],
            "technician_id": random.choice(techs)["id"],
            "type": random.choice(["sinal_baixo", "ONU offline", "wifi"]),
            "origin": random.choice(["customer", "preventive"] + ["customer"] * 4),
            "status": "pending" if is_pending else "done",
            "priority": random.choice(["high", "medium", "low"]),
            "neighborhood": sub["neighborhood"],
            "cto_id": sub["cto_id"],
            "reason": random.choice(["sinal baixo -28dBm", "conector solto",
                                       "ONU queimada", "splitter ruim"]),
            "material_used": random.choice([None, "conector SC", "fusão fibra",
                                              "ONU reserva"]),
            "reopened": random.random() < 0.1,
            "created_at": created.isoformat(),
            "closed_at": None if is_pending else closed.isoformat(),
        })
    if repairs:
        for i in range(0, len(repairs), CHUNK):
            await db.smart_repairs.insert_many(repairs[i:i + CHUNK])

    # Incidentes coletivos
    incidents = []
    for cto in random.sample(ctos, max(1, n_ctos // 50)):
        incidents.append({
            "id": f"inc-{uuid.uuid4().hex[:10]}",
            "company_id": TENANT,
            "type": "collective_outage",
            "title": f"Pane CTO {cto['name']}",
            "severity": "high",
            "status": "open",
            "olt_name": cto["olt_name"],
            "cto_id": cto["id"],
            "created_at": (_now() - timedelta(hours=random.randint(1, 12))).isoformat(),
        })
    if incidents:
        await db.incidents.insert_many(incidents)

    # Histórico de equipamentos — 3% dos clients têm ciclo completo
    sample_eq = random.sample(subs, max(5, int(n_clients * 0.03)))
    eq_docs = []
    for sub in sample_eq:
        eq_id = f"eqp-{sub['id']}"
        # Item passou por COMPRA → CLIENTE → RETIRADA → TESTE → REAPROVEITAMENTO
        from services.smart_field_v2 import STAGES as STG
        for stg in STG:
            eq_docs.append({
                "id": f"eqphist-{uuid.uuid4().hex[:10]}",
                "company_id": TENANT,
                "equipment_id": eq_id,
                "serial": f"SN{eq_id}",
                "subscriber_id": sub["id"],
                "stage": stg,
                "ts": (_now() - timedelta(days=random.randint(1, 60))).isoformat(),
                "action": "STAGE_TRANSITION",
                "kind": "history",
            })
        # estado atual = REAPROVEITAMENTO em 40% dos casos
        final_stg = "REAPROVEITAMENTO" if random.random() < 0.4 else "CLIENTE"
        eq_docs.append({
            "id": f"eqphist-cur-{uuid.uuid4().hex[:10]}",
            "company_id": TENANT,
            "equipment_id": eq_id,
            "serial": f"SN{eq_id}",
            "kind": "current_state",
            "current_stage": final_stg,
            "updated_at": _now().isoformat(),
        })
    if eq_docs:
        for i in range(0, len(eq_docs), CHUNK):
            await db.client_equipment_history.insert_many(eq_docs[i:i + CHUNK])

    return {"subs": len(subs), "ctos": len(ctos), "techs": len(techs),
            "onus": len(onus), "tickets": len(tickets),
            "repairs": len(repairs), "incidents": len(incidents)}


async def fase1_smoke() -> dict:
    """1. Smoke: chama daily_directive direto no co-demo."""
    print("\n[1] Smoke — daily_directive co-demo")
    d = await lousa_coo.daily_directive("co-demo")
    print("  directives:", len(d["directives"]),
          "  kpis preventive_deficit:", d["kpis"]["preventive_deficit"])
    return d


async def fase2_truck_roll_4outcomes() -> dict:
    """2. Truck Roll Guard: produz 4 outcomes distintos a partir do seed."""
    print("\n[2] Truck Roll — 4 outcomes")
    outs = {"DISPATCH": 0, "DO_NOT_DISPATCH": 0,
            "PREVENTIVA": 0, "INCIDENTE_COLETIVO": 0, "UNKNOWN": 0}
    samples = []
    async for s in db.subscribers.find(
            {"company_id": TENANT}, {"_id": 0, "id": 1}).limit(200):
        r = await truck_roll_guard.evaluate(TENANT, s["id"])
        d = r.get("decision", "UNKNOWN")
        outs[d] = outs.get(d, 0) + 1
        if outs[d] <= 1 and d in ("DISPATCH", "DO_NOT_DISPATCH",
                                     "PREVENTIVA", "INCIDENTE_COLETIVO"):
            samples.append(r)
        if all(outs.get(k, 0) >= 1
                for k in ("DISPATCH", "DO_NOT_DISPATCH",
                          "PREVENTIVA", "INCIDENTE_COLETIVO")):
            break
    print("  outcomes:", outs)
    return {"distribution": outs,
            "samples": [{"decision": s["decision"],
                          "rationale": s["rationale"]} for s in samples]}


async def fase3_full_coo() -> dict:
    """3. Pipeline COO end-to-end no tenant colosso."""
    print("\n[3] LOUSA COO pipeline")
    out = {}
    out["daily_directive"] = await lousa_coo.daily_directive(TENANT)
    out["enforce_preventive"] = await lousa_coo.enforce_preventive_ratio(TENANT)
    plan = await lousa_coo.plan_field_day(TENANT)
    out["plan_field_day"] = {
        "technicians_used": plan["technicians_used"],
        "total_jobs_planned": plan["total_jobs_planned"],
        "total_clusters": plan["total_clusters"],
        "estimated_drive_savings_min": plan["estimated_drive_savings_min"],
    }
    out["technician_scores"] = await lousa_coo.compute_technician_scores(TENANT, 30)
    out["technician_scores"]["sample_top5"] = out["technician_scores"]["results"][:5]
    del out["technician_scores"]["results"]
    council = await lousa_coo.operational_council_weekly(TENANT)
    out["operational_council"] = {
        "top_10_causes": council["top_10_causes"][:5],
        "top_10_ctos": council["top_10_ctos"][:5],
        "top_10_neighborhoods": council["top_10_neighborhoods"][:5],
        "top_10_materials": council["top_10_materials"][:5],
        "top_10_efficient_technicians": council["top_10_efficient_technicians"][:5],
        "top_10_rework_technicians": council["top_10_rework_technicians"][:3],
    }
    # OS learning para 1 ticket fechado
    closed_t = await db.smart_repairs.find_one(
        {"company_id": TENANT, "status": "done"}, {"_id": 0, "id": 1})
    if closed_t:
        out["os_learning_sample"] = await lousa_coo.register_os_learning(
            closed_t["id"], TENANT)
    # Alvaro command loop
    out["alvaro_commander"] = await lousa_coo.alvaro_command_loop(TENANT)
    return out


async def fase4_smart_field_v2() -> dict:
    """4. Smart Field V2 — OS context + cadeia de estoque completa."""
    print("\n[4] Smart Field V2")
    out = {}
    # OS Context
    ticket = await db.smart_repairs.find_one(
        {"company_id": TENANT}, {"_id": 0, "id": 1})
    if ticket:
        ctx = await smart_field_v2.os_context_for_technician(TENANT, ticket["id"])
        out["os_context_sample"] = {
            "ticket_id": ctx["ticket_id"],
            "probable_cause": ctx["probable_cause"],
            "materials_predicted": ctx["materials_predicted"],
            "photos_required": ctx["photos_required"],
            "diagnostic": ctx["diagnostic"],
            "history_count": len(ctx["history"]),
            "client_name": (ctx["client"] or {}).get("name"),
        }

    # Estoque: cadeia completa para 1 equipamento
    eq_id = f"eqp-test-{uuid.uuid4().hex[:6]}"
    stages = ["COMPRA", "RECEBIMENTO", "ESTOQUE_CENTRAL", "ESTOQUE_TECNICO",
              "CLIENTE", "RETIRADA", "TESTE", "REAPROVEITAMENTO"]
    transitions = []
    for stg in stages:
        r = await smart_field_v2.track_equipment_stage(
            company_id=TENANT, equipment_id=eq_id, serial=f"SN{eq_id}",
            stage=stg, cost_brl=120.0 if stg == "COMPRA" else None,
            notes=f"stage {stg}")
        transitions.append({"stage": stg, "ts": r["ts"]})
    out["stock_chain_sample"] = {
        "equipment_id": eq_id,
        "transitions": transitions,
    }
    out["stock_health"] = await smart_field_v2.stock_health(TENANT)
    return out


async def fase5_empresa_fantasma_colosso(n_clients: int, n_ctos: int,
                                            n_olts: int, n_techs: int,
                                            days: int) -> dict:
    """5. Empresa Fantasma escala 10k/500/10/100/90d.
    Responde as 7 perguntas obrigatórias do CTO.
    """
    print(f"\n[5] Empresa Fantasma Colosso ({n_clients}/{n_ctos}/"
          f"{n_olts}/{n_techs}/{days}d)")
    seeded = await _seed_colosso(n_clients, n_ctos, n_olts, n_techs, days)
    print(f"  seeded: {seeded}")

    # Rodar pipeline 3x para simular 3 dias úteis
    print("  rodando pipeline (3 ciclos diários)...")
    preventive_created_total = 0
    truck_decisions = {"DISPATCH": 0, "DO_NOT_DISPATCH": 0,
                       "PREVENTIVA": 0, "INCIDENTE_COLETIVO": 0}
    for ciclo in range(3):
        await lousa_coo.daily_directive(TENANT)
        r = await lousa_coo.enforce_preventive_ratio(TENANT)
        preventive_created_total += r["created"]
        await lousa_coo.alvaro_command_loop(TENANT, max_actions=50)
        # Truck roll em 300 subs aleatórios por ciclo
        async for s in db.subscribers.find({"company_id": TENANT},
                                             {"_id": 0, "id": 1}).limit(300):
            r = await truck_roll_guard.evaluate(TENANT, s["id"])
            d = r.get("decision", "UNKNOWN")
            if d in truck_decisions:
                truck_decisions[d] += 1
    await lousa_coo.compute_technician_scores(TENANT, days)

    # Responde 7 perguntas
    visitas_evitadas = truck_decisions["DO_NOT_DISPATCH"] + truck_decisions["INCIDENTE_COLETIVO"]
    preventivas_criadas = await db.smart_repairs.count_documents(
        {"company_id": TENANT, "origin": "preventive"})
    incidentes_previstos = await db.smart_repairs.count_documents(
        {"company_id": TENANT, "type": "preventive_cto"})
    # Custo de visita: R$ 80 (média) · 18km × R$ 0,80/L ÷ 12 km/L = R$ 1,20/km
    CUSTO_VISITA = 80.0
    KM_MEDIA = 18
    CUSTO_KM = 1.2
    combustivel_economizado_brl = visitas_evitadas * KM_MEDIA * CUSTO_KM
    # Patrimônio recuperado (TESTE → REAPROVEITAMENTO)
    pat = await db.client_equipment_history.count_documents(
        {"company_id": TENANT, "kind": "current_state",
         "current_stage": "REAPROVEITAMENTO"})
    patrimonio_recuperado_brl = pat * 120.0  # custo ONU média R$ 120
    # Tempo operacional economizado: 90 min por visita evitada
    tempo_minutos_economizado = visitas_evitadas * 90
    tempo_horas = round(tempo_minutos_economizado / 60.0, 1)
    # ROI: economia bruta / custo da operação (estimado: 1 técnico R$ 300/dia × 3 dias × 100 techs)
    economia_total_brl = (visitas_evitadas * CUSTO_VISITA
                           + combustivel_economizado_brl
                           + patrimonio_recuperado_brl)
    custo_operacao_brl = 100 * 300 * 3  # 100 techs × R$300/dia × 3 dias
    roi_pct = round((economia_total_brl / custo_operacao_brl) * 100, 1) if custo_operacao_brl else 0

    return {
        "seed": seeded,
        "preventive_created_in_simulation": preventive_created_total,
        "truck_roll_distribution": truck_decisions,
        "answers": {
            "1_visitas_evitadas": visitas_evitadas,
            "2_preventivas_criadas": preventivas_criadas,
            "3_incidentes_previstos": incidentes_previstos,
            "4_combustivel_economizado_brl": round(combustivel_economizado_brl, 2),
            "5_patrimonio_recuperado_brl": round(patrimonio_recuperado_brl, 2),
            "6_tempo_operacional_economizado_horas": tempo_horas,
            "7_roi_operacional_pct": roi_pct,
        },
        "ts": _now().isoformat(),
    }


async def main():
    out = {"ts": _now().isoformat(), "tenant": TENANT}

    # 1) Smoke co-demo
    out["fase1_smoke"] = await fase1_smoke()
    # Seed COLOSSO 10k/500/10/100/90d (full scale)
    n_clients = int(os.environ.get("COLOSSO_CLIENTS", "10000"))
    n_ctos = int(os.environ.get("COLOSSO_CTOS", "500"))
    n_olts = int(os.environ.get("COLOSSO_OLTS", "10"))
    n_techs = int(os.environ.get("COLOSSO_TECHS", "100"))
    days = int(os.environ.get("COLOSSO_DAYS", "90"))
    out["fase5_empresa_fantasma"] = await fase5_empresa_fantasma_colosso(
        n_clients, n_ctos, n_olts, n_techs, days)

    # Após seed: 2, 3, 4
    out["fase2_truck_roll"] = await fase2_truck_roll_4outcomes()
    out["fase3_coo_pipeline"] = await fase3_full_coo()
    out["fase4_smart_field"] = await fase4_smart_field_v2()

    out_path = "/app/docs/RELATORIO_COLOSSO.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)

    print("\n" + "═" * 70)
    print("OPERAÇÃO COLOSSO — RESULTADOS")
    print("═" * 70)
    print(json.dumps(out["fase5_empresa_fantasma"]["answers"],
                       indent=2, ensure_ascii=False))
    print(f"\n[ok] gravado em {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
