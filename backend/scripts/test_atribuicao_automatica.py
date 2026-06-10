"""OPERAÇÃO REGISTRO AUTOMÁTICO DE ATRIBUIÇÃO — 8 cenários reais.

Valida que cada hook persiste em executive_ledger EM TEMPO REAL e que
re-execução não duplica (chave idempotente
company_id + action_id + kind).

Cenários:
  1. truck_roll_guard.evaluate → DO_NOT_DISPATCH cria TRUCK_ROLL_AVOIDED
  2. smart_field_v2.track_equipment_stage(REAPROVEITAMENTO) cria EQUIPMENT_REUSED
  3. lousa_coo.alvaro_command_loop escala incidente → INCIDENT_REVENUE_PROTECTED
     + ALVARO_INCIDENT_DETECTED + ALVARO_CLIENTS_PROTECTED
  4. isabella_lousa_scheduler.confirm_and_create_os cria ISABELLA_OS_CREATED (pending)
  5. mark_isabella_os_resolved promove pending → confirmed + cria ISABELLA_OS_RESOLVED
  6. isabella decide NO_OS para subscriber identificado → ISABELLA_TRUCK_ROLL_BLOCKED
  7. enforce_preventive_ratio cria PREVENTIVE_AVOIDED_VISIT (pending)
  8. Re-execução de todos os hooks NÃO duplica nada
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")

from database import db  # noqa: E402
from services import truck_roll_guard, smart_field_v2, lousa_coo  # noqa: E402
from services import isabella_lousa_scheduler as ils  # noqa: E402
from services import presidente_financeiro as pf  # noqa: E402


TENANT = "co-attribution-test"


async def setup() -> dict:
    # Limpa tenant
    for c in ("subscribers", "smartolt_onus", "ctos", "incidents",
              "smart_repairs", "tickets", "ticket_logs", "users",
              "collaborators", "client_equipment_history",
              "truck_roll_decisions", "executive_ledger",
              "ai_evaluations", "subscriber_phones"):
        await db[c].delete_many({"company_id": TENANT})

    # Subscriber com tudo OK (vai gerar DO_NOT_DISPATCH) — OLT limpa
    sub_ok = "sub-attr-OK"
    await db.subscribers.insert_one({
        "id": sub_ok, "company_id": TENANT, "name": "Cliente OK",
        "phones": ["5511990001111"], "plan_price": 99.90,
        "status": "ACTIVE", "cto_id": "cto-clean-A",
        "olt_name": "OLT-CLEAN", "pppoe": "p-ok"})
    await db.smartolt_onus.insert_one({
        "id": "onu-ok", "company_id": TENANT, "subscriber_id": sub_ok,
        "pppoe": "p-ok", "online": True, "rx_power": -22,
        "signal_1310": -22, "status": "Online",
        "unique_external_id": "onu-ok"})

    # Subscriber com sinal ruim — também OLT limpa
    sub_bad = "sub-attr-BAD"
    await db.subscribers.insert_one({
        "id": sub_bad, "company_id": TENANT, "name": "Cliente BAD",
        "phones": ["5511990002222"], "plan_price": 99.90,
        "status": "ACTIVE", "cto_id": "cto-clean-B",
        "olt_name": "OLT-CLEAN", "pppoe": "p-bad"})
    await db.smartolt_onus.insert_one({
        "id": "onu-bad", "company_id": TENANT, "subscriber_id": sub_bad,
        "pppoe": "p-bad", "online": False, "rx_power": -30,
        "signal_1310": -30, "status": "Offline",
        "unique_external_id": "onu-bad"})

    # Incidente coletivo aberto + 30 subs sob OUTRA OLT (não conflita)
    for i in range(30):
        sid = f"sub-attr-inc-{i:02d}"
        await db.subscribers.insert_one({
            "id": sid, "company_id": TENANT, "name": f"INC {i}",
            "phones": [], "plan_price": 99.90, "status": "ACTIVE",
            "cto_id": "cto-attr-INC", "olt_name": "OLT-ATTR-INC"})
    await db.incidents.insert_one({
        "id": "inc-attr-1", "company_id": TENANT,
        "type": "collective_outage", "severity": "high", "status": "open",
        "cto_id": "cto-attr-INC", "olt_name": "OLT-ATTR-INC",
        "created_at": datetime.now(timezone.utc).isoformat()})

    # Colaborador
    await db.collaborators.insert_one({
        "id": "col-attr-1", "company_id": TENANT,
        "cpf": f"99988877{uuid.uuid4().hex[:3]}",
        "name": "Tech Attr 1", "cargo": "tecnico_rede"})

    return {"sub_ok": sub_ok, "sub_bad": sub_bad}


async def main():
    seed = await setup()
    sub_ok = seed["sub_ok"]
    sub_bad = seed["sub_bad"]

    before = await db.executive_ledger.count_documents(
        {"company_id": TENANT, "category": "PRESIDENTE_FINANCEIRO"})

    results = {}

    # ─── Cenário 1: truck_roll_guard ───────────────────────────────────
    r = await truck_roll_guard.evaluate(TENANT, sub_ok)
    led = await db.executive_ledger.find_one(
        {"company_id": TENANT, "kind": "TRUCK_ROLL_AVOIDED",
         "subscriber_id": sub_ok}, {"_id": 0, "status": 1,
                                       "valor_confirmado_brl": 1})
    results["1_truck_roll_guard"] = {
        "decision": r["decision"], "ledger": led,
        "pass": bool(led)}

    # ─── Cenário 2: smart_field_v2 REAPROVEITAMENTO ────────────────────
    eq_id = f"eqp-attr-{uuid.uuid4().hex[:6]}"
    await smart_field_v2.track_equipment_stage(
        company_id=TENANT, equipment_id=eq_id, serial="SN1",
        stage="REAPROVEITAMENTO", subscriber_id=sub_ok)
    led = await db.executive_ledger.find_one(
        {"company_id": TENANT, "kind": "EQUIPMENT_REUSED",
         "evidence.equipment_id": eq_id}, {"_id": 0, "status": 1,
                                              "valor_confirmado_brl": 1})
    results["2_equipment_reused"] = {"ledger": led,
                                       "pass": (led or {}).get("valor_confirmado_brl") == 120.0}

    # ─── Cenário 3: alvaro_command_loop incidente ──────────────────────
    r3 = await lousa_coo.alvaro_command_loop(TENANT, max_actions=20)
    led_inc = await db.executive_ledger.find_one(
        {"company_id": TENANT, "kind": "INCIDENT_REVENUE_PROTECTED",
         "evidence.incident_id": "inc-attr-1"},
        {"_id": 0, "status": 1, "valor_confirmado_brl": 1,
         "evidence.clients_affected": 1})
    led_alv = await db.executive_ledger.find_one(
        {"company_id": TENANT, "kind": "ALVARO_INCIDENT_DETECTED"},
        {"_id": 0})
    led_cli = await db.executive_ledger.find_one(
        {"company_id": TENANT, "kind": "ALVARO_CLIENTS_PROTECTED"},
        {"_id": 0, "valor_confirmado_brl": 1})
    results["3_incident_alvaro"] = {
        "incident_ledger_brl": (led_inc or {}).get("valor_confirmado_brl"),
        "alvaro_ledger": bool(led_alv),
        "clients_protected_brl": (led_cli or {}).get("valor_confirmado_brl"),
        "pass": bool(led_inc) and bool(led_alv) and bool(led_cli)}

    # ─── Cenário 4: ISABELLA_OS_CREATED ────────────────────────────────
    # Força DISPATCH no sub_bad
    prop = await ils.propose_window(TENANT, sub_bad,
                                       "sem internet, ONU vermelha")
    created = await ils.confirm_and_create_os(
        company_id=TENANT, subscriber_id=sub_bad,
        phone="5511990002222", user_text="sem internet",
        proposal=prop, confirmation_text="sim")
    tid = (created.get("ticket") or {}).get("id")
    led_iso_create = await db.executive_ledger.find_one(
        {"company_id": TENANT, "kind": "ISABELLA_OS_CREATED",
         "evidence.ticket_id": tid},
        {"_id": 0, "status": 1, "valor_confirmado_brl": 1})
    results["4_isabella_os_created"] = {
        "ticket_id": tid, "ledger": led_iso_create,
        "is_pending": (led_iso_create or {}).get("status") == "pending_confirmation",
        "pass": bool(led_iso_create) and led_iso_create["status"] == "pending_confirmation"}

    # ─── Cenário 5: mark_isabella_os_resolved promove pending → confirmed
    if tid:
        await ils.mark_isabella_os_resolved(TENANT, tid)
    led_after = await db.executive_ledger.find_one(
        {"company_id": TENANT, "kind": "ISABELLA_OS_CREATED",
         "evidence.ticket_id": tid},
        {"_id": 0, "status": 1})
    led_resolved = await db.executive_ledger.find_one(
        {"company_id": TENANT, "kind": "ISABELLA_OS_RESOLVED",
         "evidence.ticket_id": tid},
        {"_id": 0, "status": 1, "valor_confirmado_brl": 1})
    results["5_isabella_os_resolved"] = {
        "created_now_confirmed": (led_after or {}).get("status") == "confirmed",
        "resolved_ledger": led_resolved,
        "pass": ((led_after or {}).get("status") == "confirmed"
                  and bool(led_resolved))}

    # ─── Cenário 6: Isabella decide NO_OS ──────────────────────────────
    # Sub_ok já tem sinal bom → decide_action retorna NO_OS para "lento"
    dec = await ils.decide_action(TENANT, sub_ok, "internet lerda hoje")
    led_block = await db.executive_ledger.find_one(
        {"company_id": TENANT, "kind": "ISABELLA_TRUCK_ROLL_BLOCKED",
         "subscriber_id": sub_ok},
        {"_id": 0, "status": 1, "valor_confirmado_brl": 1})
    results["6_isabella_truck_roll_blocked"] = {
        "decision_action": dec.get("action"),
        "ledger": led_block,
        "pass": dec.get("action") == "NO_OS" and bool(led_block)}

    # ─── Cenário 7: enforce_preventive_ratio cria PREVENTIVE_AVOIDED_VISIT
    # Garante repairs_24h > 0 (do cenário anterior já temos OS Isabella)
    # Adiciona ONU degradada para gerar preventiva
    await db.smartolt_onus.insert_one({
        "id": "onu-degraded", "company_id": TENANT,
        "subscriber_id": sub_bad,
        "pppoe": "p-deg", "online": True, "rx_power": -29,
        "signal_1310": -29, "status": "Online",
        "unique_external_id": "onu-degraded"})
    # Garante meta superior ao atual: cria 12 repairs corretivos
    for i in range(12):
        await db.smart_repairs.insert_one({
            "id": f"rep-attr-{i}", "company_id": TENANT,
            "origin": "customer", "subscriber_id": "x",
            "created_at": datetime.now(timezone.utc).isoformat()})
    res_enf = await lousa_coo.enforce_preventive_ratio(TENANT)
    led_prev = await db.executive_ledger.count_documents(
        {"company_id": TENANT, "kind": "PREVENTIVE_AVOIDED_VISIT"})
    results["7_preventive_avoided_visit"] = {
        "enforce_result": res_enf,
        "ledger_count": led_prev,
        "pass": led_prev > 0}

    # ─── Cenário 8: REEXECUÇÃO NÃO DUPLICA ─────────────────────────────
    # Verifica idempotência POR EVENTO (mesmas chaves não duplicam).
    # Não inclui enforce_preventive_ratio porque ele PODE criar novas
    # preventivas a cada chamada quando há ONUs degradadas novas (correto).
    snapshot1_truck = await db.executive_ledger.count_documents(
        {"company_id": TENANT,
         "kind": {"$in": ["TRUCK_ROLL_AVOIDED",
                            "ISABELLA_TRUCK_ROLL_BLOCKED",
                            "EQUIPMENT_REUSED",
                            "INCIDENT_REVENUE_PROTECTED",
                            "ALVARO_INCIDENT_DETECTED",
                            "ALVARO_CLIENTS_PROTECTED",
                            "ISABELLA_OS_CREATED",
                            "ISABELLA_OS_RESOLVED"]}})
    # Re-roda os hooks que são naturalmente idempotentes
    await truck_roll_guard.evaluate(TENANT, sub_ok)
    await smart_field_v2.track_equipment_stage(
        company_id=TENANT, equipment_id=eq_id, serial="SN1",
        stage="REAPROVEITAMENTO", subscriber_id=sub_ok)
    # Re-abre o incident para revalidar
    await db.incidents.update_one(
        {"id": "inc-attr-1", "company_id": TENANT},
        {"$set": {"status": "open"}})
    await lousa_coo.alvaro_command_loop(TENANT, max_actions=20)
    await ils.decide_action(TENANT, sub_ok, "internet lerda hoje")
    if tid:
        await ils.mark_isabella_os_resolved(TENANT, tid)
    snapshot2_truck = await db.executive_ledger.count_documents(
        {"company_id": TENANT,
         "kind": {"$in": ["TRUCK_ROLL_AVOIDED",
                            "ISABELLA_TRUCK_ROLL_BLOCKED",
                            "EQUIPMENT_REUSED",
                            "INCIDENT_REVENUE_PROTECTED",
                            "ALVARO_INCIDENT_DETECTED",
                            "ALVARO_CLIENTS_PROTECTED",
                            "ISABELLA_OS_CREATED",
                            "ISABELLA_OS_RESOLVED"]}})
    snapshot1 = snapshot1_truck
    snapshot2 = snapshot2_truck
    results["8_idempotente"] = {
        "before_reexec": snapshot1,
        "after_reexec": snapshot2,
        "delta": snapshot2 - snapshot1,
        "pass": snapshot1 == snapshot2}

    # Resumo final
    after = await db.executive_ledger.count_documents(
        {"company_id": TENANT, "category": "PRESIDENTE_FINANCEIRO"})
    pending = await db.executive_ledger.count_documents(
        {"company_id": TENANT, "category": "PRESIDENTE_FINANCEIRO",
         "status": "pending_confirmation"})
    confirmed = await db.executive_ledger.count_documents(
        {"company_id": TENANT, "category": "PRESIDENTE_FINANCEIRO",
         "status": "confirmed"})
    pipe = [{"$match": {"company_id": TENANT,
                          "category": "PRESIDENTE_FINANCEIRO"}},
             {"$group": {"_id": "$kind", "count": {"$sum": 1},
                            "valor": {"$sum": "$valor_confirmado_brl"}}}]
    breakdown = []
    async for r in db.executive_ledger.aggregate(pipe):
        breakdown.append({"kind": r["_id"], "count": r["count"],
                           "valor_brl": round(r["valor"], 2)})

    # Batch reconciliação (run_attribution_cycle) — deve adicionar 0
    rec_before = await db.executive_ledger.count_documents(
        {"company_id": TENANT, "category": "PRESIDENTE_FINANCEIRO"})
    batch = await pf.run_attribution_cycle(TENANT, window_days=30)
    rec_after = await db.executive_ledger.count_documents(
        {"company_id": TENANT, "category": "PRESIDENTE_FINANCEIRO"})

    passed = sum(1 for v in results.values() if v.get("pass"))
    total = len(results)

    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tenant": TENANT,
        "passed": passed, "total": total,
        "ledger_before": before,
        "ledger_after_hooks": after,
        "auto_attributed": after - before,
        "pending": pending,
        "confirmed": confirmed,
        "kind_breakdown": breakdown,
        "batch_reconciliation": {
            "delta": rec_after - rec_before,
            "total_brl_attributed": batch.get("total_brl_attributed"),
        },
        "results": results,
    }
    path = "/app/docs/RELATORIO_ATRIBUICAO_AUTOMATICA.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n═══ RESUMO ═══")
    print(f"Passed: {passed}/{total}")
    print(f"Ledger entries antes dos hooks: {before}")
    print(f"Ledger entries depois: {after}")
    print(f"Auto-atribuídas em tempo real: {after - before}")
    print(f"Pending: {pending} | Confirmed: {confirmed}")
    print(f"Batch reconcil delta: {rec_after - rec_before}")
    print(f"\nBreakdown por kind:")
    for b in breakdown:
        print(f"  {b['kind']:35s} count={b['count']:3d} R$ {b['valor_brl']:>10.2f}")
    print(f"\nCenários:")
    for k, v in results.items():
        print(f"  {'✅' if v.get('pass') else '❌'} {k}")
    print(f"\n[ok] gravado em {path}")


if __name__ == "__main__":
    asyncio.run(main())
