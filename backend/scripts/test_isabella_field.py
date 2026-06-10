"""ISABELLA FIELD PRESIDENT — testes ZERO MOCK (Mongo real + API real).

Roda: cd /app/backend && python3 scripts/test_isabella_field.py

Valida o critério de aceite do CTO:
 1. Briefing dinâmico real (saudação, contagens, recomendação com motivos).
 2. Evento field.isabella.recommendation.created emitido.
 3. Rota otimizada (reordenação real) + eventos route.optimized e
    priority.changed.
 4. Estoque Inteligente: alerta real + evento stock.alert.
 5. Brief de Instalação Inteligente (CTO/porta/materiais/risco reais).
 6. Brief de Reparo Inteligente (roteiro de testes + histórico).
 7. Pós-OS: nota Isabella persistida + causa raiz + eventos repair.scored
    e root_cause.detected (fluxo REAL de finalize da Lousa).
 8. Frota IA: nota Isabella + análise Álvaro gravada na vistoria + evento
    vehicle.scored.
 9. Isabella preside a Lousa: tickets.isabella persistido em toda bolha.
10. Presidente IA: summary consolidado com indicadores reais.
"""
import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

sys.path.insert(0, "/app/backend")
from auth import hash_password  # noqa: E402
from database import db  # noqa: E402

BASE = "http://localhost:8001"
CO = "co-demo"
SP = ZoneInfo("America/Sao_Paulo")

TEST_EMAIL = "fieldtest@empresa.com"
TEST_PASS = "FieldTest#2026"
COLLAB_ID = "col-fieldtest"
TI1 = "tkt-isatest-inst"   # instalação, horário fixo
TR1 = "tkt-isatest-rep"    # reparo — será executada e finalizada
CTO_ID = "cto-isatest"
PHOTO = "data:image/jpeg;base64," + ("QUJDREVGRw==" * 4)

RESULTS = []


def check(name, ok, info=""):
    RESULTS.append((name, ok, info))
    print(f"{'✅ PASS' if ok else '❌ FAIL'} — {name}{(' · ' + info) if info else ''}")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def sched_today(hour):
    d = datetime.now(SP).replace(hour=hour, minute=0, second=0, microsecond=0)
    return d.astimezone(timezone.utc).isoformat()


def mk_ticket(tid, ttype, hour, priority="normal"):
    return {
        "id": tid, "company_id": CO, "client_id": f"cli-{tid}",
        "client_snapshot": {
            "id": f"cli-{tid}",
            "name": f"CLIENTE ISA {tid[-4:].upper()}",
            "address": "Rua Isabella, 42", "neighborhood": "Centro",
            "phone": "21988887777", "relato": "Fixture Isabella Field",
        },
        "type": ttype, "priority": priority,
        "scheduled_time": sched_today(hour),
        "position": 999998, "status": "pendente",
        "assigned_collaborator_id": COLLAB_ID, "company": CO,
        "opened_at": None, "closed_at": None,
        "whatsapp_status": "nao_enviado",
        "created_at": now_iso(), "test_fixture": True,
    }


async def setup():
    await teardown()
    await db.collaborators.insert_one({
        "id": COLLAB_ID, "name": "TECNICO FIELD TEST", "email": TEST_EMAIL,
        "role": "Tecnico", "company_id": CO, "clock_in_enabled": False,
        "cpf": "99988877701", "test_fixture": True, "created_at": now_iso()})
    await db.users.insert_one({
        "id": f"usr-{uuid.uuid4().hex[:10]}", "email": TEST_EMAIL,
        "name": "Tecnico Field Test", "role": "colaborador",
        "password_hash": hash_password(TEST_PASS),
        "collaborator_id": COLLAB_ID, "active": True, "company_id": CO,
        "created_at": now_iso(), "updated_at": now_iso(),
        "test_fixture": True})
    # Agenda: reparo 06h (atrasada, normal) + instalação 09h (horário fixo)
    await db.tickets.insert_many([
        mk_ticket(TR1, "reparo", 6, "normal"),
        mk_ticket(TI1, "instalacao", 9, "horario"),
    ])
    # CTO real com porta livre (p/ brief de instalação e finish do reparo)
    await db.ctos.insert_one({
        "id": CTO_ID, "company_id": CO, "name": "CTO-ISATEST-01",
        "address": "Rua Isabella, Centro", "capacity": 8,
        "gps": {"lat": -22.52, "lng": -44.10},
        "ports": [{"number": n, "status": "free"} for n in range(1, 9)],
        "test_fixture": True,
        "created_at": now_iso()})
    await db.cto_ports.insert_one({
        "id": f"{CTO_ID}-p1", "company_id": CO, "cto_id": CTO_ID,
        "cto_name": "CTO-ISATEST-01", "port_number": 1, "status": "free",
        "signal_dbm": -19.5, "test_fixture": True,
        "last_updated_at": now_iso()})
    # Estoque do técnico vazio (gera alerta real p/ 1 instalação)
    await db.stok_stock.update_one(
        {"company_id": CO, "location": COLLAB_ID},
        {"$set": {"company_id": CO, "location": COLLAB_ID}}, upsert=True)


async def teardown():
    await db.users.delete_many({"email": TEST_EMAIL})
    await db.collaborators.delete_many({"id": COLLAB_ID})
    await db.tickets.delete_many({"id": {"$in": [TI1, TR1]}})
    await db.ticket_logs.delete_many({"ticket_id": {"$in": [TI1, TR1]}})
    await db.ctos.delete_many({"id": CTO_ID})
    await db.cto_ports.delete_many({"cto_id": CTO_ID})
    await db.client_event_history.delete_many(
        {"client_id": {"$in": [f"cli-{TI1}", f"cli-{TR1}"]}})
    await db.stok_stock.delete_many({"location": COLLAB_ID})
    await db.stok_services.delete_many({"ticket_id": {"$in": [TI1, TR1]}})
    await db.stok_history.delete_many({"ticket_id": {"$in": [TI1, TR1]}})
    await db.field_vehicle_inspections.delete_many(
        {"collaborator_id": COLLAB_ID})
    await db.isabella_field_briefings.delete_many(
        {"collaborator_id": COLLAB_ID})
    await db.motor_ia_events.delete_many(
        {"source": {"$in": ["field_ops", "isabella_field"]},
         "$or": [{"payload.collaborator_id": COLLAB_ID},
                 {"payload.ticket_id": {"$in": [TI1, TR1]}}]})
    await db.audit_log.delete_many({"collaborator_id": COLLAB_ID})
    await db.whatsapp_log.delete_many({"ticket_id": {"$in": [TI1, TR1]}})
    await db.notifications.delete_many({"ticket_id": {"$in": [TI1, TR1]}})


async def ev_exists(event_type, **payload_match):
    q = {"company_id": CO, "event_type": event_type}
    for k, v in payload_match.items():
        q[f"payload.{k}"] = v
    return bool(await db.motor_ia_events.find_one(q, {"_id": 0, "id": 1}))


async def main():
    print("=" * 70)
    print("ISABELLA FIELD PRESIDENT — TESTES ZERO MOCK")
    print("=" * 70)
    await setup()
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            r = await client.post(f"{BASE}/api/auth/login", json={
                "email": TEST_EMAIL, "password": TEST_PASS})
            assert r.status_code == 200, f"login técnico: {r.text}"
            th = {"Authorization": f"Bearer {r.json()['access_token']}"}
            r = await client.post(f"{BASE}/api/auth/login", json={
                "email": "admin@empresa.com", "password": "123456"})
            ah = {"Authorization": f"Bearer {r.json()['access_token']}"}

            # ---- 1. Briefing dinâmico --------------------------------
            r = await client.get(f"{BASE}/api/field/isabella/briefing",
                                 headers=th)
            b = r.json()
            rec = b.get("recommended_os") or {}
            check("1. Briefing dinâmico com dados reais",
                  r.status_code == 200
                  and "Carlos" not in b["headline"]
                  and "2 OS hoje" in b["headline"]
                  and rec.get("ticket_id") in (TI1, TR1)
                  and len(rec.get("reasons") or []) >= 2,
                  f"headline='{b.get('headline', '')[:80]}'")

            # ---- 2. Evento recommendation.created --------------------
            ok = await ev_exists("field.isabella.recommendation.created",
                                 collaborator_id=COLLAB_ID)
            check("2. Evento field.isabella.recommendation.created", ok)

            # ---- 3. Rota otimizada + eventos -------------------------
            r = await client.get(f"{BASE}/api/field/isabella/route",
                                 headers=th)
            rt = r.json()
            route = rt.get("route") or []
            order = [x["ticket_id"] for x in route]
            # naive = [TR1(06h), TI1(09h)]; Isabella deve subir TI1 (janela fixa)
            reordered = order and order[0] == TI1
            ev_route = await ev_exists("field.isabella.route.optimized",
                                       collaborator_id=COLLAB_ID)
            ev_prio = await ev_exists("field.isabella.priority.changed",
                                      collaborator_id=COLLAB_ID)
            check("3. Rota reordenada + eventos route/priority",
                  r.status_code == 200 and len(route) == 2 and reordered
                  and rt.get("changed_vs_schedule") and ev_route and ev_prio,
                  f"ordem={order}")

            # ---- 4. Estoque Inteligente ------------------------------
            alerts = b.get("stock_alerts") or []
            ev_stock = await ev_exists("field.isabella.stock.alert",
                                       collaborator_id=COLLAB_ID)
            check("4. Alerta de estoque real + evento stock.alert",
                  any("ONU" in (a.get("item") or "") for a in alerts)
                  and ev_stock,
                  f"{len(alerts)} alertas")

            # ---- 5. Instalação Inteligente (brief) -------------------
            r = await client.get(
                f"{BASE}/api/field/isabella/os/{TI1}/brief", headers=th)
            bi = r.json()
            cto = bi.get("cto_suggestion") or {}
            check("5. Brief de instalação (CTO/porta/sinal/materiais)",
                  r.status_code == 200
                  and bi.get("resolution_probability") is not None
                  and bi.get("suggested_materials")
                  and cto.get("cto_id") == CTO_ID
                  and cto.get("port_number") == 1
                  and cto.get("expected_signal_dbm") == -19.5
                  and bi.get("region_risk", {}).get("neighborhood") == "Centro",
                  f"cto={cto.get('cto_name')} porta={cto.get('port_number')} "
                  f"sinal={cto.get('expected_signal_dbm')}")

            # ---- 6. Reparo Inteligente (brief) -----------------------
            r = await client.get(
                f"{BASE}/api/field/isabella/os/{TR1}/brief", headers=th)
            br = r.json()
            check("6. Brief de reparo (roteiro de testes + histórico)",
                  r.status_code == 200
                  and len(br.get("test_guidance") or []) >= 3
                  and "probable_causes" in br,
                  f"causas={len(br.get('probable_causes') or [])}")

            # ---- 7. Pós-OS: nota + causa raiz (fluxo REAL) -----------
            r = await client.post(f"{BASE}/api/field/os/{TR1}/start",
                                  json={"latitude": -22.5, "longitude": -44.1},
                                  headers=th)
            assert r.status_code == 200, f"start: {r.text}"
            await client.post(f"{BASE}/api/field/os/{TR1}/signal-test",
                              json={"dbm": -29.0, "phase": "before"},
                              headers=th)
            await client.post(f"{BASE}/api/field/os/{TR1}/signal-test",
                              json={"dbm": -19.0, "phase": "after"},
                              headers=th)
            r = await client.post(f"{BASE}/api/field/os/{TR1}/finish", json={
                "completion_data": {
                    "sinal": -19.0, "qtd_drop": 20, "esticadores": 2,
                    "conectores_fast": 2, "cabo_rede": 0,
                    "conectores_rede": 0,
                    "cto_id": CTO_ID, "cto_port_number": 1,
                    "fotos": [PHOTO],
                },
                "latitude": -22.5, "longitude": -44.1, "outcome": "sucesso",
            }, headers=th)
            fin = r.json() if r.status_code == 200 else {}
            tdoc = await db.tickets.find_one(
                {"id": TR1}, {"_id": 0, "status": 1, "isabella_score": 1,
                              "isabella_root_cause": 1})
            ev_scored = await ev_exists("field.isabella.repair.scored",
                                        ticket_id=TR1)
            ev_root = await ev_exists("field.isabella.root_cause.detected",
                                      ticket_id=TR1)
            check("7. Finish real → nota Isabella + causa raiz + eventos",
                  r.status_code == 200
                  and tdoc.get("status") == "finalizada"
                  and (tdoc.get("isabella_score") or {}).get("nota_final")
                  and tdoc.get("isabella_root_cause")
                  and (fin.get("isabella_score") or {}).get("nota_final")
                  and ev_scored and ev_root,
                  f"nota={((tdoc.get('isabella_score') or {}).get('nota_final'))} "
                  f"causa='{tdoc.get('isabella_root_cause')}' "
                  f"(finish={r.status_code})")

            # ---- 8. Frota IA: Isabella + Álvaro ----------------------
            r = await client.post(f"{BASE}/api/field/vehicle/inspection",
                                  json={"plate": "ISA1B23", "km": 50000,
                                        "photo_front": PHOTO,
                                        "photo_rear": PHOTO,
                                        "photo_left": PHOTO,
                                        "photo_right": PHOTO},
                                  headers=th)
            vd = r.json() if r.status_code == 200 else {}
            insp_id = vd.get("inspection_id")
            ev_veh = await ev_exists("field.isabella.vehicle.scored",
                                     inspection_id=insp_id)
            alvaro = None
            for _ in range(25):  # até ~100s p/ análise Álvaro (vision/fallback)
                doc = await db.field_vehicle_inspections.find_one(
                    {"id": insp_id}, {"_id": 0, "alvaro": 1})
                alvaro = (doc or {}).get("alvaro")
                if alvaro:
                    break
                await asyncio.sleep(4)
            check("8. Frota: nota Isabella + evento + análise Álvaro",
                  r.status_code == 200
                  and (vd.get("isabella_score") or {}).get("nota") is not None
                  and ev_veh and alvaro
                  and alvaro.get("risco_quebra") in ("baixo", "medio", "alto"),
                  f"nota={((vd.get('isabella_score') or {}).get('nota'))} "
                  f"alvaro_engine={(alvaro or {}).get('engine')}")

            # ---- 9. Isabella preside a Lousa -------------------------
            r = await client.get(
                f"{BASE}/api/field/isabella/lousa-analysis", headers=ah)
            la = r.json() if r.status_code == 200 else {}
            ti = await db.tickets.find_one({"id": TI1},
                                           {"_id": 0, "isabella": 1})
            isa_block = (ti or {}).get("isabella") or {}
            check("9. Lousa presidida: análise persistida em toda bolha",
                  r.status_code == 200 and la.get("count", 0) >= 1
                  and isa_block.get("priority_rank")
                  and isa_block.get("risk") in ("alto", "medio", "baixo")
                  and isa_block.get("analysis")
                  and isa_block.get("prediction"),
                  f"count={la.get('count')} rank={isa_block.get('priority_rank')} "
                  f"risk={isa_block.get('risk')}")

            # ---- 10. Presidente IA: summary --------------------------
            r = await client.get(
                f"{BASE}/api/field/isabella/president-summary", headers=ah)
            ps = r.json() if r.status_code == 200 else {}
            my_row = next((t for t in ps.get("techs_today", [])
                           if t["collaborator_id"] == COLLAB_ID), None)
            check("10. Presidente IA recebe indicadores consolidados",
                  r.status_code == 200
                  and ps.get("finalizadas_hoje", 0) >= 1
                  and my_row and my_row.get("nota_media") is not None
                  and "truck_roll_avoidance_30d" in ps
                  and "fleet_score_avg_30d" in ps,
                  f"finalizadas={ps.get('finalizadas_hoje')} "
                  f"nota_tecnico={my_row and my_row.get('nota_media')}")

            # Segurança: técnico NÃO acessa endpoints de governança
            r1 = await client.get(
                f"{BASE}/api/field/isabella/lousa-analysis", headers=th)
            r2 = await client.get(f"{BASE}/api/field/isabella/briefing")
            check("Extra. RBAC: governança só gestor; sem JWT = 401",
                  r1.status_code == 403 and r2.status_code == 401,
                  f"lousa={r1.status_code} no_jwt={r2.status_code}")
        finally:
            await teardown()

    print("=" * 70)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"RESULTADO: {passed}/{len(RESULTS)} testes passaram")
    if passed < len(RESULTS):
        for n, ok, info in RESULTS:
            if not ok:
                print(f"  FALHOU: {n} — {info}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
