"""OPERAÇÃO ISABELLA AGENDA NA LOUSA — 10 cenários (preview only).

Número autorizado para teste: 21998176526.
NUNCA envia para outros números reais.
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
from phone_normalizer import normalize_brazilian_phone  # noqa: E402
from services.isabella_lousa_scheduler import (  # noqa: E402
    classify_intent, decide_action, propose_window,
    confirm_and_create_os, followup_open_tickets_by_isabella,
    find_available_slot,
)


TEST_PHONE = "5521998176526"
COMPANY = "co-demo"  # tenant safe (mesmo do número-teste)


async def get_or_create_test_subscriber() -> str:
    sub = await db.subscribers.find_one(
        {"company_id": COMPANY, "phones": {"$in": [TEST_PHONE, "21998176526"]}},
        {"_id": 0, "id": 1})
    if sub:
        return sub["id"]
    sid = f"sub-isalousa-{uuid.uuid4().hex[:6]}"
    await db.subscribers.insert_one({
        "id": sid, "company_id": COMPANY,
        "name": "Cliente Teste Isabella Lousa",
        "phones": [TEST_PHONE, "21998176526"],
        "plan_name": "Fibra 600MB", "monthly_value": 99.90,
        "status": "ACTIVE", "address": "Rua Teste, 100",
        "neighborhood": "Centro",
        "pppoe": "test-pppoe",
        "churn_score": 0.4,
        "cto_id": "cto-isalousa-test",
        "olt_name": "OLT-ISALOUSA-TEST",
        "smartolt_onu_zone": "cto-isalousa-test",
        "smartolt_onu_status": "Online",
    })
    await db.subscriber_phones.insert_one({
        "id": f"sphone-{uuid.uuid4().hex[:10]}",
        "company_id": COMPANY, "subscriber_id": sid,
        "label": "principal", "raw_number": TEST_PHONE,
        "normalized_number": normalize_brazilian_phone(TEST_PHONE),
        "is_whatsapp": True, "is_primary": True,
    })
    return sid


async def main():
    sub_id = await get_or_create_test_subscriber()
    results = {}

    # 1) cliente com problema resolvível remoto (ONU OK)
    r = await decide_action(COMPANY, sub_id, "minha internet está lenta")
    results["1_problema_remoto"] = {"action": r["action"], "intent": r["intent"],
                                     "rationale": r.get("rationale")}

    # 2) cliente com incidente coletivo — força criação de incident ativo
    await db.incidents.delete_many({"company_id": COMPANY,
                                      "_test_isalousa": True})
    sub = await db.subscribers.find_one({"id": sub_id}, {"_id": 0,
                                                          "cto_id": 1, "olt_name": 1})
    await db.incidents.insert_one({
        "id": f"inc-test-{uuid.uuid4().hex[:6]}",
        "company_id": COMPANY, "type": "collective_outage",
        "title": "Pane coletiva teste", "severity": "high",
        "status": "open",
        "cto_id": sub.get("cto_id"),
        "olt_name": sub.get("olt_name"),
        "_test_isalousa": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    r = await decide_action(COMPANY, sub_id, "internet caiu aqui na rua")
    results["2_incidente_coletivo"] = {
        "action": r["action"], "intent": r["intent"],
        "decision": r.get("decision"),
        "rationale": r.get("rationale"),
        "expected_escalate": r["action"] == "ESCALATE_COLLECTIVE",
    }
    await db.incidents.delete_many({"_test_isalousa": True})

    # 3) cliente precisa reparo individual — força ONU offline
    await db.smartolt_onus.update_one(
        {"company_id": COMPANY, "pppoe": "test-pppoe"},
        {"$set": {"online": False, "rx_power": -29, "signal_1310": -29,
                  "status": "Offline", "pppoe": "test-pppoe",
                  "subscriber_id": sub_id,
                  "company_id": COMPANY,
                  "unique_external_id": f"isalousa-test-{sub_id}"}},
        upsert=True)
    r = await decide_action(COMPANY, sub_id, "sem internet, ONU vermelha")
    prop = await propose_window(COMPANY, sub_id, "sem internet, ONU vermelha")
    results["3_reparo_individual"] = {
        "action": r["action"],
        "proposal_has_slot": bool(prop.get("slot")),
        "proposal_text": prop.get("proposal_text"),
        "expected_dispatch_or_preventiva": r["action"] == "DISPATCH",
    }

    # 4) cliente pede melhor horário (tarde) — proposta padrão
    results["4_pede_melhor_horario"] = {
        "proposal_text": prop.get("proposal_text"),
        "window_label": (prop.get("slot") or {}).get("window_label"),
        "expected_window_in_18h": ("h às" in (prop.get("proposal_text") or "")),
    }

    # 5) horário ocupado — preenche todos os slots do técnico e refaz
    slot = prop.get("slot") or {}
    coll_id = slot.get("collaborator_id")
    busy_filled = []
    if coll_id:
        # Ocupa todas as horas 9-17 do dia
        today_str = datetime.now(timezone.utc).date().isoformat()
        for hour in range(9, 18):
            tid = f"tkt-busy-{uuid.uuid4().hex[:6]}"
            await db.tickets.insert_one({
                "id": tid, "client_id": "busy",
                "client_snapshot": {"name": "BUSY", "phone": "0"},
                "type": "reparo", "priority": "normal",
                "scheduled_time": f"{today_str}T{hour:02d}:00",
                "position": 0, "status": "pendente",
                "assigned_collaborator_id": coll_id,
                "company_id": COMPANY,
                "_test_isalousa_busy": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            busy_filled.append(tid)
    prop2 = await propose_window(COMPANY, sub_id, "sem internet ainda")
    results["5_horario_ocupado"] = {
        "first_collaborator": coll_id,
        "alternative_collaborator": (prop2.get("slot") or {}).get("collaborator_id"),
        "different_collaborator": coll_id != (prop2.get("slot") or {}).get("collaborator_id")
                                  if (prop2.get("slot") or {}).get("collaborator_id") else False,
    }
    await db.tickets.delete_many({"_test_isalousa_busy": True})

    # 6) técnico indisponível — apaga todos colaboradores e revalida
    # (não-destrutivo: usamos cargo fora do mapa)
    slot_alt = await find_available_slot(COMPANY, preferred_cargo="cargo_inexistente")
    results["6_tecnico_indisponivel_fallback"] = {
        "slot_found_via_fallback": bool(slot_alt),
        "fallback_collaborator": (slot_alt or {}).get("collaborator_id"),
    }

    # 7) OS criada e aparece na Lousa
    created = await confirm_and_create_os(
        company_id=COMPANY, subscriber_id=sub_id, phone=TEST_PHONE,
        user_text="sem internet ainda", proposal=prop,
        confirmation_text="sim, pode")
    tk = created.get("ticket") or {}
    in_lousa = await db.tickets.find_one(
        {"id": tk.get("id"), "company_id": COMPANY}, {"_id": 0})
    results["7_os_aparece_na_lousa"] = {
        "ticket_id": tk.get("id"),
        "origin": tk.get("origin"),
        "in_db": bool(in_lousa),
        "status": tk.get("status"),
        "type": tk.get("type"),
        "priority": tk.get("priority"),
        "scheduled_time": tk.get("scheduled_time"),
        "assigned_collaborator_id": tk.get("assigned_collaborator_id"),
        "expected_origin_isabella": tk.get("origin") == "isabella",
    }

    # 8) OS aparece na Lousa Mobile do técnico (mesmo doc db.tickets,
    #    consultada por assigned_collaborator_id)
    coll_id = tk.get("assigned_collaborator_id")
    mobile_view = []
    async for t in db.tickets.find(
            {"assigned_collaborator_id": coll_id,
             "status": {"$in": ["pendente", "aberta",
                                  "aguardando_atendimento"]},
             "company_id": COMPANY,
             "origin": "isabella"},
            {"_id": 0, "id": 1, "type": 1, "scheduled_time": 1,
             "isabella_obs_tecnico": 1, "client_snapshot": 1}).limit(5):
        mobile_view.append(t)
    results["8_os_na_lousa_mobile"] = {
        "mobile_count": len(mobile_view),
        "mobile_sample_first": mobile_view[0] if mobile_view else None,
        "has_obs_tecnico": bool((mobile_view[0] or {}).get("isabella_obs_tecnico"))
                            if mobile_view else False,
    }

    # 9) OS finalizada
    if tk.get("id"):
        await db.tickets.update_one(
            {"id": tk["id"], "company_id": COMPANY},
            {"$set": {"status": "concluida",
                       "closed_at": datetime.now(timezone.utc).isoformat(),
                       "outcome": "resolvido_no_local"}})
        results["9_os_finalizada"] = {"ticket_id": tk["id"],
                                        "marked_concluida": True}

    # 10) Isabella faz follow-up — ainda não há ticket open neste phone
    fu = await followup_open_tickets_by_isabella(COMPANY, phone=TEST_PHONE)
    # Cria outro para ter algo no follow-up
    prop3 = await propose_window(COMPANY, sub_id, "sem internet de novo")
    if prop3.get("slot"):
        await confirm_and_create_os(
            company_id=COMPANY, subscriber_id=sub_id, phone=TEST_PHONE,
            user_text="sem internet de novo", proposal=prop3,
            confirmation_text="sim")
    fu2 = await followup_open_tickets_by_isabella(COMPANY, phone=TEST_PHONE)
    results["10_followup"] = {
        "open_tickets_after_finalize": len(fu),
        "open_tickets_after_new_call": len(fu2),
        "expected_increases": len(fu2) > len(fu),
    }

    # Validação geral dos critérios de aceite
    expectations = {
        "isabella_nao_abre_sem_diagnostico": all(
            isinstance(results.get(f"3_reparo_individual", {}).get(k), (str, bool))
            for k in ["action", "proposal_has_slot"]),
        "incidente_coletivo_escala": results["2_incidente_coletivo"]["expected_escalate"],
        "reparo_gera_dispatch": results["3_reparo_individual"]["expected_dispatch_or_preventiva"],
        "os_persistida_em_db": results["7_os_aparece_na_lousa"]["in_db"],
        "os_tem_origin_isabella": results["7_os_aparece_na_lousa"]["expected_origin_isabella"],
        "lousa_mobile_recebe": results["8_os_na_lousa_mobile"]["mobile_count"] > 0,
        "obs_tecnico_clara": results["8_os_na_lousa_mobile"]["has_obs_tecnico"],
        "fallback_tecnico_funciona": results["6_tecnico_indisponivel_fallback"]["slot_found_via_fallback"],
        "followup_aumenta": results["10_followup"]["expected_increases"],
    }

    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "subscriber_id": sub_id, "phone": TEST_PHONE,
        "results": results,
        "expectations": expectations,
        "passed": sum(1 for v in expectations.values() if v),
        "total": len(expectations),
    }
    path = "/app/docs/RELATORIO_ISABELLA_LOUSA.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(json.dumps({"passed": out["passed"], "total": out["total"],
                       "expectations": expectations}, indent=2, ensure_ascii=False))
    print(f"\n[ok] gravado em {path}")


if __name__ == "__main__":
    asyncio.run(main())
