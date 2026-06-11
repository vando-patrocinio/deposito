"""ISABELLA INCIDENT COMMANDER — testes ZERO MOCK (Mongo real + API real).

Roda: cd /app/backend && python3 scripts/test_isabella_incident.py

Valida:
 1. Varredura detecta cluster de CTO (≥3 reparos/48h) com probabilidade,
    criticidade, clientes afetados (portas reais), churn e impacto financeiro.
 2. Bolha CRÍTICA (OS coletiva) criada na Lousa com análise Isabella rank #1.
 3. Cluster de bairro (≥5 reparos/48h) detectado.
 4. Eventos auditáveis: incident.predicted / cto.cluster / neighborhood.cluster.
 5. Dedup: segunda varredura ATUALIZA (não duplica).
 6. Trava de reparo individual: criar reparo p/ cliente da CTO em incidente
    → 409 + cliente AGRUPADO no incidente.
 7. Confirmação → incident.confirmed.
 8. Feed da Rede IA com CTO suspeita + tendência.
 9. Presidente IA: summary com bloco de incidentes.
10. Resolução + RBAC (técnico não varre; sem JWT = 401).
"""

NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx

sys.path.insert(0, "/app/backend")
from auth import hash_password  # noqa: E402
from database import db  # noqa: E402

BASE = "http://localhost:8001"
CO = "co-demo"
COLLAB_ID = "col-inctest"
TEST_EMAIL = "inctest@empresa.com"
TEST_PASS = "IncTest#2026"
CTO_ID = "cto-inctest"
NEIGH = "BairroIncTest"
RESULTS = []


def check(name, ok, info=""):
    RESULTS.append((name, ok, info))
    print(f"{'✅ PASS' if ok else '❌ FAIL'} — {name}{(' · ' + info) if info else ''}")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def mk_repair(i, client_id, neigh, relato="Sem internet"):
    return {
        "id": f"tkt-inctest-{i}", "company_id": CO, "client_id": client_id,
        "client_snapshot": {"id": client_id, "name": f"CLIENTE INC{i}",
                            "address": "Rua Incidente, 1", "neighborhood": neigh,
                            "phone": "21", "relato": relato},
        "type": "reparo", "priority": "normal",
        "scheduled_time": now_iso(), "position": 900000 + i,
        "status": "pendente", "assigned_collaborator_id": COLLAB_ID,
        "company": CO, "opened_at": None, "closed_at": None,
        "whatsapp_status": "nao_enviado", "created_at": now_iso(),
        "test_fixture": True,
    }


async def setup():
    await teardown()
    await db.collaborators.insert_one({
        "id": COLLAB_ID, "name": "TECNICO INC TEST", "email": TEST_EMAIL,
        "role": "Tecnico", "company_id": CO, "clock_in_enabled": False,
        "cpf": "99988877703", "test_fixture": True, "created_at": now_iso()})
    await db.users.insert_one({
        "id": f"usr-{uuid.uuid4().hex[:10]}", "email": TEST_EMAIL,
        "name": "Tecnico Inc", "role": "colaborador",
        "password_hash": hash_password(TEST_PASS),
        "collaborator_id": COLLAB_ID, "active": True, "company_id": CO,
        "created_at": now_iso(), "updated_at": now_iso(),
        "test_fixture": True})
    # CTO real com 4 portas ocupadas (clientes reais p/ contagem de afetados)
    await db.ctos.insert_one({
        "id": CTO_ID, "company_id": CO, "name": "CTO-INCTEST-01",
        "address": f"Rua Incidente, {NEIGH}", "capacity": 8,
        "gps": {"lat": -22.5, "lng": -44.1},
        "ports": [{"number": n, "status": "used"} for n in range(1, 5)],
        "test_fixture": True, "created_at": now_iso()})
    for n in range(1, 5):
        cid = f"sub-inc-{n}"
        await db.cto_ports.insert_one({
            "id": f"{CTO_ID}-p{n}", "company_id": CO, "cto_id": CTO_ID,
            "cto_name": "CTO-INCTEST-01", "port_number": n,
            "status": "occupied", "subscriber_id": cid,
            "subscriber_name": f"CLIENTE INC{n}", "neighborhood": NEIGH,
            "sn": None, "test_fixture": True, "last_updated_at": now_iso()})
        await db.subscribers.insert_one({
            "id": cid, "company_id": CO, "name": f"CLIENTE INC{n}",
            "pppoe_user": f"inc{n}@test", "neighborhood": NEIGH,
            "test_fixture": True, "created_at": now_iso()})
    # 3 reparos/48h na CTO (clientes 1-3) → regra 1
    repairs = [mk_repair(n, f"sub-inc-{n}", NEIGH) for n in range(1, 4)]
    # +2 reparos no MESMO bairro (clientes sem porta) → regra 2 (5 no bairro)
    repairs += [mk_repair(n, f"cli-inc-extra-{n}", NEIGH) for n in range(4, 6)]
    await db.tickets.insert_many(repairs)


async def teardown():
    await db.users.delete_many({"email": TEST_EMAIL})
    await db.collaborators.delete_many({"id": COLLAB_ID})
    await db.tickets.delete_many({"id": {"$regex": "^tkt-inctest-"}})
    incs = await db.isabella_incidents.find(
        {"company_id": CO, "$or": [{"scope.cto_id": CTO_ID},
                                   {"scope.neighborhood": NEIGH}]},
        {"_id": 0, "id": 1, "collective_ticket_id": 1}).to_list(50)
    for i in incs:
        if i.get("collective_ticket_id"):
            await db.tickets.delete_many({"id": i["collective_ticket_id"]})
    await db.isabella_incidents.delete_many(
        {"company_id": CO, "$or": [{"scope.cto_id": CTO_ID},
                                   {"scope.neighborhood": NEIGH}]})
    await db.ctos.delete_many({"id": CTO_ID})
    await db.cto_ports.delete_many({"cto_id": CTO_ID})
    await db.subscribers.delete_many({"id": {"$regex": "^sub-inc-"}})
    await db.motor_ia_events.delete_many(
        {"source": "isabella_incident",
         "$or": [{"payload.scope.cto_id": CTO_ID},
                 {"payload.scope.neighborhood": NEIGH}]})
    await db.notifications.delete_many(
        {"type": "isabella_incident", "company_id": CO,
         "title": {"$regex": "INCTEST|BairroIncTest|CTO-INCTEST"}})
    await db.audit_log.delete_many({"collaborator_id": COLLAB_ID})


async def ev_exists(event_type, **m):
    q = {"company_id": CO, "event_type": event_type,
         "source": "isabella_incident"}
    for k, v in m.items():
        q[f"payload.{k}"] = v
    return bool(await db.motor_ia_events.find_one(q, {"_id": 0, "id": 1}))


async def main():
    print("=" * 70)
    print("ISABELLA INCIDENT COMMANDER — TESTES ZERO MOCK")
    print("=" * 70)
    await setup()
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            r = await client.post(f"{BASE}/api/auth/login", json={
                "email": "admin@empresa.com", "password": "123456"})
            ah = {"Authorization": f"Bearer {r.json()['access_token']}"}
            r = await client.post(f"{BASE}/api/auth/login", json={
                "email": TEST_EMAIL, "password": TEST_PASS})
            th = {"Authorization": f"Bearer {r.json()['access_token']}"}

            # ---- 1. Varredura: cluster de CTO -------------------------
            r = await client.post(
                f"{BASE}/api/field/isabella/incidents/scan", headers=ah)
            scan = r.json()
            all_new = scan.get("new_incidents", [])
            cto_inc = next((i for i in all_new
                            if i["kind"] == "cto_cluster"
                            and i["scope"].get("cto_id") == CTO_ID), None)
            check("1. Cluster de CTO detectado (3 reparos/48h)",
                  r.status_code == 200 and cto_inc
                  and cto_inc["evidence_count"] >= 3
                  and cto_inc["probability"] >= 60
                  and cto_inc["affected_clients_estimated"] == 4,
                  f"prob={cto_inc and cto_inc['probability']}% "
                  f"afetados={cto_inc and cto_inc['affected_clients_estimated']}")
            inc_doc = await db.isabella_incidents.find_one(
                {"company_id": CO, "scope.cto_id": CTO_ID,
                 "kind": "cto_cluster"}, {"_id": 0})

            # ---- 2. Bolha coletiva na Lousa ---------------------------
            bolha = None
            if inc_doc and inc_doc.get("collective_ticket_id"):
                bolha = await db.tickets.find_one(
                    {"id": inc_doc["collective_ticket_id"]}, {"_id": 0})
            check("2. OS coletiva CRÍTICA criada na Lousa",
                  bolha and bolha.get("is_collective")
                  and bolha.get("priority") == "alta"
                  and "INCIDENTE COLETIVO" in (bolha.get("client_snapshot") or {}).get("name", "")
                  and (bolha.get("isabella") or {}).get("priority_rank") == 1
                  and bolha.get("assigned_collaborator_id") == COLLAB_ID,
                  f"bolha={bolha and bolha['id']} tecnico={bolha and bolha.get('assigned_collaborator_id')}")

            # ---- 3. Cluster de bairro ---------------------------------
            nb_inc = next((i for i in all_new
                           if i["kind"] == "neighborhood_cluster"
                           and (i["scope"].get("neighborhood") or "").lower() == NEIGH.lower()), None)
            check("3. Cluster de bairro detectado (5 reparos/48h)",
                  nb_inc and nb_inc["evidence_count"] >= 5,
                  f"n={nb_inc and nb_inc['evidence_count']}")

            # ---- 4. Eventos auditáveis --------------------------------
            e1 = await ev_exists("incident.predicted", incident_id=inc_doc["id"])
            e2 = await ev_exists("incident.cto.cluster", incident_id=inc_doc["id"])
            e3 = bool(await db.motor_ia_events.find_one(
                {"company_id": CO, "event_type": "incident.neighborhood.cluster",
                 "payload.scope.neighborhood": NEIGH}, {"_id": 0}))
            notif = await db.notifications.find_one(
                {"company_id": CO, "type": "isabella_incident",
                 "incident_id": inc_doc["id"]}, {"_id": 0, "id": 1})
            check("4. Eventos predicted/cto.cluster/neighborhood + notificação",
                  e1 and e2 and e3 and bool(notif))

            # ---- 5. Dedup: segunda varredura não duplica ---------------
            r = await client.post(
                f"{BASE}/api/field/isabella/incidents/scan", headers=ah)
            scan2 = r.json()
            dup = [i for i in scan2.get("new_incidents", [])
                   if i["scope"].get("cto_id") == CTO_ID
                   or (i["scope"].get("neighborhood") or "").lower() == NEIGH.lower()]
            upd = [i for i in scan2.get("updated_incidents", [])
                   if i["scope"].get("cto_id") == CTO_ID]
            check("5. Dedup: 2ª varredura atualiza em vez de duplicar",
                  not dup and len(upd) >= 1,
                  f"novos_dup={len(dup)} atualizados={len(upd)}")

            # ---- 6. Trava de reparo individual + agrupamento -----------
            r = await client.post(f"{BASE}/api/lousa/tickets", json={
                "client_name": "CLIENTE INC4", "address": "Rua Incidente, 4",
                "neighborhood": NEIGH, "phone": "21999990004",
                "relato": "Sem internet de novo", "pppoe_user": "inc4@test",
                "type": "reparo", "priority": "normal",
                "assigned_collaborator_id": COLLAB_ID,
            }, headers=ah)
            blocked = (r.status_code == 409
                       and "COLLECTIVE_INCIDENT_OPEN" in r.text)
            inc_after = await db.isabella_incidents.find_one(
                {"id": inc_doc["id"]}, {"_id": 0, "grouped_clients": 1,
                                        "affected_client_ids": 1})
            grouped = any(g.get("pppoe_user") == "inc4@test"
                          for g in (inc_after or {}).get("grouped_clients") or [])
            check("6. Reparo individual TRAVADO (409) + cliente agrupado",
                  blocked and grouped
                  and "sub-inc-4" in (inc_after or {}).get("affected_client_ids", []),
                  f"status={r.status_code} grouped={grouped}")

            # ---- 7. Confirmação ----------------------------------------
            r = await client.post(
                f"{BASE}/api/field/isabella/incidents/{inc_doc['id']}/confirm",
                headers=ah)
            e_conf = await ev_exists("incident.confirmed",
                                     incident_id=inc_doc["id"])
            check("7. Confirmação → incident.confirmed",
                  r.status_code == 200 and e_conf)

            # ---- 8. Feed da Rede IA ------------------------------------
            r = await client.get(
                f"{BASE}/api/field/isabella/incidents/network-feed",
                headers=ah)
            feed = r.json()
            has_cto = any(c["cto_id"] == CTO_ID
                          for c in feed.get("suspect_ctos", []))
            has_region = any((c.get("neighborhood") or "").lower() == NEIGH.lower()
                             for c in feed.get("suspect_regions", []))
            check("8. Rede IA: feed com CTO/região suspeitas + tendência",
                  r.status_code == 200 and has_cto and has_region
                  and feed.get("trend", {}).get("degradation") in
                  ("baixa", "media", "alta"),
                  f"trend={feed.get('trend', {}).get('degradation')}")

            # ---- 9. Presidente IA: summary com incidentes --------------
            r = await client.get(
                f"{BASE}/api/field/isabella/president-summary", headers=ah)
            ps = r.json()
            incs = ps.get("incidents") or {}
            check("9. Presidente IA: bloco de incidentes no summary",
                  r.status_code == 200 and incs.get("open", 0) >= 1
                  and incs.get("confirmed", 0) >= 1
                  and incs.get("monthly_revenue_at_risk_brl", 0) > 0
                  and incs.get("clients_at_churn_risk", 0) >= 1,
                  f"open={incs.get('open')} receita_risco="
                  f"R${incs.get('monthly_revenue_at_risk_brl')}")

            # ---- 10. Resolução + RBAC ----------------------------------
            r1 = await client.post(
                f"{BASE}/api/field/isabella/incidents/{inc_doc['id']}/resolve",
                headers=ah)
            doc = await db.isabella_incidents.find_one(
                {"id": inc_doc["id"]}, {"_id": 0, "status": 1})
            r2 = await client.post(
                f"{BASE}/api/field/isabella/incidents/scan", headers=th)
            r3 = await client.get(f"{BASE}/api/field/isabella/incidents")
            check("10. Resolução + RBAC (técnico 403, sem JWT 401)",
                  r1.status_code == 200 and doc["status"] == "resolved"
                  and r2.status_code == 403 and r3.status_code == 401,
                  f"resolve={r1.status_code} tec={r2.status_code} "
                  f"nojwt={r3.status_code}")
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
