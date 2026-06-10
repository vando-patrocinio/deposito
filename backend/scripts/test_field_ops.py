"""SMART FIELD OPS — 12 testes ZERO MOCK contra o Mongo real + API real.

Roda: cd /app/backend && python3 scripts/test_field_ops.py

Cobertura (contrato /app/docs/SMART_FIELD_OPS_CONNECTION.md §8):
 1. Técnico só vê OS dele.
 2. Técnico não acessa OS de outra empresa (404).
 3. Sem JWT não acessa nada (401).
 4. Não finaliza OS sem checklist obrigatório.
 5. Foto obrigatória bloqueia finalização.
 6. GPS obrigatório bloqueia início.
 7. Uso de material baixa estoque (stok_stock real).
 8. Retirada devolve equipamento ao estoque (stok_onts real).
 9. Retirada gera impacto financeiro (field_equipment_returns).
10. Lousa atualiza após ação no App (tickets + ticket_logs).
11. Evento é gerado para Presidente IA (motor_ia_events field.*).
12. Frota pendente bloqueia abertura de OS quando regra ativa.

Fixtures REAIS criadas no co-demo e removidas no final. Nenhum mock.
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
OTHER_COLLAB_ID = "col-fieldtest-b"
T1 = "tkt-ftest-1"   # do técnico de teste (instalacao, hoje)
T2 = "tkt-ftest-2"   # de OUTRO técnico, mesma empresa
T3 = "tkt-ftest-3"   # de OUTRA empresa
OTHER_CO = "co-fieldtest-x"
MAC_FIX = "AA:BB:CC:00:FE:01"
PHOTO = "data:image/jpeg;base64," + ("QUJDREVGRw==" * 4)

RESULTS = []


def check(name: str, ok: bool, info: str = ""):
    RESULTS.append((name, ok, info))
    print(f"{'✅ PASS' if ok else '❌ FAIL'} — {name}{(' · ' + info) if info else ''}")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def today_sched(hour=10):
    d = datetime.now(SP).replace(hour=hour, minute=0, second=0, microsecond=0)
    return d.astimezone(timezone.utc).isoformat()


def mk_ticket(tid, collab, company, ttype="instalacao"):
    return {
        "id": tid, "company_id": company,
        "client_id": f"cli-{tid}",
        "client_snapshot": {
            "name": f"CLIENTE TESTE {tid.upper()}",
            "address": "Rua dos Testes, 100", "neighborhood": "Centro",
            "phone": "21999990000", "relato": "Fixture de teste field ops",
            "pppoe_user": "teste@fieldops",
        },
        "type": ttype, "priority": "normal",
        "scheduled_time": today_sched(),
        "position": 999999, "status": "pendente",
        "assigned_collaborator_id": collab,
        "company": company,
        "opened_at": None, "closed_at": None,
        "whatsapp_status": "nao_enviado",
        "created_at": now_iso(), "test_fixture": True,
    }


async def setup():
    await teardown()  # idempotente
    await db.collaborators.insert_many([
        {"id": COLLAB_ID, "name": "TECNICO FIELD TEST", "email": TEST_EMAIL,
         "role": "Tecnico", "company_id": CO, "clock_in_enabled": False,
         "cpf": "99988877701",
         "test_fixture": True, "created_at": now_iso()},
        {"id": OTHER_COLLAB_ID, "name": "OUTRO TECNICO TEST",
         "email": "fieldtest-b@empresa.com", "role": "Tecnico",
         "company_id": CO, "clock_in_enabled": False,
         "cpf": "99988877702",
         "test_fixture": True, "created_at": now_iso()},
    ])
    await db.users.insert_one({
        "id": f"usr-{uuid.uuid4().hex[:10]}", "email": TEST_EMAIL,
        "name": "Tecnico Field Test", "role": "colaborador",
        "password_hash": hash_password(TEST_PASS),
        "collaborator_id": COLLAB_ID, "active": True, "company_id": CO,
        "created_at": now_iso(), "updated_at": now_iso(),
        "test_fixture": True,
    })
    await db.tickets.insert_many([
        mk_ticket(T1, COLLAB_ID, CO),
        mk_ticket(T2, OTHER_COLLAB_ID, CO),
        mk_ticket(T3, COLLAB_ID, OTHER_CO),
    ])
    # saldo inicial de material p/ teste de baixa
    await db.stok_stock.update_one(
        {"company_id": CO, "location": COLLAB_ID},
        {"$set": {"company_id": CO, "location": COLLAB_ID}}, upsert=True)


async def teardown():
    await db.users.delete_many({"email": TEST_EMAIL})
    await db.collaborators.delete_many(
        {"id": {"$in": [COLLAB_ID, OTHER_COLLAB_ID]}})
    await db.tickets.delete_many({"id": {"$in": [T1, T2, T3]}})
    await db.ticket_logs.delete_many({"ticket_id": {"$in": [T1, T2, T3]}})
    await db.stok_stock.delete_many({"location": COLLAB_ID})
    await db.stok_onts.delete_many({"mac": MAC_FIX})
    await db.stok_services.delete_many({"ticket_id": {"$in": [T1, T2, T3]}})
    await db.stok_history.delete_many({"ticket_id": {"$in": [T1, T2, T3]}})
    await db.field_vehicle_inspections.delete_many(
        {"collaborator_id": COLLAB_ID})
    await db.field_equipment_returns.delete_many(
        {"collaborator_id": COLLAB_ID})
    await db.lousa_manager_callback_requests.delete_many(
        {"ticket_id": {"$in": [T1, T2, T3]}})
    await db.notifications.delete_many({"ticket_id": {"$in": [T1, T2, T3]}})
    await db.motor_ia_events.delete_many(
        {"source": "field_ops", "payload.collaborator_id": COLLAB_ID})
    await db.audit_log.delete_many({"collaborator_id": COLLAB_ID})
    await db.whatsapp_log.delete_many({"ticket_id": {"$in": [T1, T2, T3]}})


async def set_toggles(client, admin_h, **kw):
    r = await client.put(f"{BASE}/api/field/settings", json=kw, headers=admin_h)
    assert r.status_code == 200, f"settings PUT falhou: {r.status_code} {r.text}"


async def main():
    print("=" * 70)
    print("SMART FIELD OPS — TESTES ZERO MOCK (Mongo real + API real)")
    print("=" * 70)
    await setup()
    orig_toggles = None
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            # Logins REAIS
            r = await client.post(f"{BASE}/api/auth/login", json={
                "email": TEST_EMAIL, "password": TEST_PASS})
            assert r.status_code == 200, f"login técnico falhou: {r.text}"
            tech_h = {"Authorization": f"Bearer {r.json()['access_token']}"}
            r = await client.post(f"{BASE}/api/auth/login", json={
                "email": "admin@empresa.com", "password": "123456"})
            assert r.status_code == 200, f"login admin falhou: {r.text}"
            admin_h = {"Authorization": f"Bearer {r.json()['access_token']}"}

            r = await client.get(f"{BASE}/api/field/settings", headers=admin_h)
            orig_toggles = r.json()

            # ---- T3: sem JWT → 401 -------------------------------------
            r = await client.get(f"{BASE}/api/field/dashboard")
            check("3. Sem JWT não acessa nada (401)", r.status_code == 401,
                  f"status={r.status_code}")

            # ---- T1: técnico só vê OS dele -----------------------------
            r = await client.get(f"{BASE}/api/field/os/today", headers=tech_h)
            ids = [t["id"] for t in r.json().get("items", [])]
            check("1. Técnico só vê OS dele",
                  r.status_code == 200 and T1 in ids and T2 not in ids
                  and T3 not in ids, f"ids={ids}")

            # ---- T2: cross-company / cross-técnico → 404 ----------------
            r2 = await client.get(f"{BASE}/api/field/os/{T3}", headers=tech_h)
            r3 = await client.get(f"{BASE}/api/field/os/{T2}", headers=tech_h)
            check("2. OS de outra empresa/técnico → 404",
                  r2.status_code == 404 and r3.status_code == 404,
                  f"outra_empresa={r2.status_code} outro_tecnico={r3.status_code}")

            # ---- T6: GPS obrigatório bloqueia início --------------------
            await set_toggles(client, admin_h, gps_required=True)
            r = await client.post(f"{BASE}/api/field/os/{T1}/start",
                                  json={}, headers=tech_h)
            gps_block = r.status_code == 412
            await set_toggles(client, admin_h, gps_required=False)
            check("6. GPS obrigatório bloqueia início (412)", gps_block,
                  f"status={r.status_code}")

            # ---- T12: frota pendente bloqueia abertura ------------------
            await set_toggles(client, admin_h, vehicle_inspection_required=True)
            r = await client.post(f"{BASE}/api/field/os/{T1}/start",
                                  json={"latitude": -22.8, "longitude": -43.3},
                                  headers=tech_h)
            blocked = (r.status_code == 412
                       and "VEHICLE_INSPECTION_PENDING" in r.text)
            # faz a vistoria (KM + 4 fotos) e tenta de novo
            r = await client.post(f"{BASE}/api/field/vehicle/inspection", json={
                "plate": "TST1A23", "km": 12345,
                "photo_front": PHOTO, "photo_rear": PHOTO,
                "photo_left": PHOTO, "photo_right": PHOTO,
            }, headers=tech_h)
            insp_ok = r.status_code == 200
            r = await client.post(f"{BASE}/api/field/os/{T1}/start",
                                  json={"latitude": -22.8, "longitude": -43.3},
                                  headers=tech_h)
            start_ok = r.status_code == 200
            await set_toggles(client, admin_h, vehicle_inspection_required=False)
            check("12. Frota pendente bloqueia OS; vistoria libera",
                  blocked and insp_ok and start_ok,
                  f"block={blocked} vistoria={insp_ok} start_apos={start_ok}")

            # ---- T10: Lousa atualiza após ação do App -------------------
            tdoc = await db.tickets.find_one({"id": T1}, {"_id": 0, "status": 1})
            r = await client.post(f"{BASE}/api/field/os/{T1}/arrive", json={
                "latitude": -22.81, "longitude": -43.31}, headers=tech_h)
            arrive_ok = r.status_code == 200
            tdoc2 = await db.tickets.find_one(
                {"id": T1}, {"_id": 0, "field_arrived_at": 1})
            logs = await db.ticket_logs.count_documents({"ticket_id": T1})
            check("10. Lousa atualiza após ação no App",
                  tdoc and tdoc["status"] == "aberta" and arrive_ok
                  and bool(tdoc2.get("field_arrived_at")) and logs >= 2,
                  f"status_db={tdoc and tdoc['status']} logs={logs}")

            # ---- T11: evento para Presidente IA -------------------------
            ev = await db.motor_ia_events.find_one({
                "event_type": "field.os.started", "company_id": CO,
                "payload.ticket_id": T1}, {"_id": 0, "id": 1})
            ev2 = await db.motor_ia_events.find_one({
                "event_type": "field.os.arrived", "company_id": CO,
                "payload.ticket_id": T1}, {"_id": 0, "id": 1})
            check("11. Eventos field.* gerados p/ Presidente IA",
                  bool(ev) and bool(ev2), "field.os.started + field.os.arrived")

            # ---- T7: material baixa estoque REAL ------------------------
            r = await client.get(f"{BASE}/api/field/materials/catalog",
                                 headers=tech_h)
            cat = r.json()["items"]
            cons_id = cat[0]["id"]
            before = await db.stok_stock.find_one(
                {"company_id": CO, "location": COLLAB_ID}, {"_id": 0})
            qty_before = (before or {}).get(cons_id, 0) or 0
            r = await client.post(
                f"{BASE}/api/field/os/{T1}/material-used",
                json={"items": [{"consumable_id": cons_id, "quantity": 3}]},
                headers=tech_h)
            after = await db.stok_stock.find_one(
                {"company_id": CO, "location": COLLAB_ID}, {"_id": 0})
            qty_after = (after or {}).get(cons_id, 0) or 0
            check("7. Material usado baixa estoque (stok_stock)",
                  r.status_code == 200 and qty_after == qty_before - 3,
                  f"{cons_id}: {qty_before} → {qty_after}")

            # ---- T4: checklist obrigatório bloqueia finalização ---------
            r = await client.post(f"{BASE}/api/field/os/{T1}/finish", json={
                "completion_data": {}, "latitude": -22.8, "longitude": -43.3,
            }, headers=tech_h)
            still = await db.tickets.find_one({"id": T1}, {"_id": 0, "status": 1})
            check("4. Sem checklist obrigatório NÃO finaliza",
                  r.status_code in (400, 422) and still["status"] == "aberta",
                  f"status={r.status_code} db={still['status']}")

            # ---- T5: foto obrigatória bloqueia finalização --------------
            full_cd = {"sinal": -20.5, "qtd_drop": 1, "esticadores": 2,
                       "conectores_fast": 2, "cabo_rede": 0,
                       "conectores_rede": 0, "ont": "AA:BB:CC:DD:EE:99",
                       "fotos": []}
            r = await client.post(f"{BASE}/api/field/os/{T1}/finish", json={
                "completion_data": full_cd,
                "latitude": -22.8, "longitude": -43.3,
            }, headers=tech_h)
            still = await db.tickets.find_one({"id": T1}, {"_id": 0, "status": 1})
            check("5. Foto obrigatória bloqueia finalização",
                  r.status_code in (400, 422) and still["status"] == "aberta",
                  f"status={r.status_code} detail={r.text[:90]}")

            # ---- T8: retirada devolve equipamento ao estoque ------------
            r = await client.post(f"{BASE}/api/field/equipment/return", json={
                "ticket_id": T1, "mac": MAC_FIX, "recovered": True,
                "physical_state": "bom",
            }, headers=tech_h)
            ont = await db.stok_onts.find_one(
                {"company_id": CO, "mac": MAC_FIX}, {"_id": 0})
            check("8. Retirada devolve equipamento ao estoque (stok_onts)",
                  r.status_code == 200 and ont
                  and ont["location_type"] == "tecnico"
                  and ont["location_id"] == COLLAB_ID
                  and ont["status"] == "retirada_com_tecnico",
                  f"status_ont={(ont or {}).get('status')}")

            # ---- T9: retirada gera impacto financeiro -------------------
            rec = await db.field_equipment_returns.find_one(
                {"company_id": CO, "mac": MAC_FIX, "recovered": True},
                {"_id": 0})
            r = await client.post(f"{BASE}/api/field/equipment/return", json={
                "ticket_id": T1, "sn": "SN-FTEST-LOSS", "recovered": False,
                "physical_state": "bom",
            }, headers=tech_h)
            loss = await db.field_equipment_returns.find_one(
                {"company_id": CO, "sn": "SN-FTEST-LOSS"}, {"_id": 0})
            notif = await db.notifications.find_one(
                {"company_id": CO, "type": "field_equipment_loss",
                 "ticket_id": T1}, {"_id": 0, "id": 1})
            check("9. Retirada gera impacto financeiro + notifica financeiro",
                  rec and rec.get("value_recovered", 0) > 0
                  and loss and loss.get("value_lost", 0) > 0 and bool(notif),
                  f"recuperado=R${(rec or {}).get('value_recovered')} "
                  f"perda=R${(loss or {}).get('value_lost')}")

            # Extra: auditoria gravada
            audits = await db.audit_log.count_documents(
                {"company_id": CO, "source": "field_ops",
                 "collaborator_id": COLLAB_ID})
            check("Extra. audit_log gravado em toda ação", audits >= 5,
                  f"{audits} registros")

        finally:
            if orig_toggles:
                await client.put(f"{BASE}/api/field/settings",
                                 json=orig_toggles, headers=admin_h)
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
