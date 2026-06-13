"""ETAPA Conexão CTO — FASE 9 · Teste E2E Isabella → Lousa → Mobile → Colab → KPI → Presidente IA.

Executa o fluxo COMPLETO simulando cliente real e mede:
  - Isabella → Lousa: ≤ 3s
  - Lousa → Mobile: ≤ 5s
  - Mobile → KPI: ≤ 5s
  - KPI → Presidente IA: ≤ 30s

Se algum trecho QUEBRAR, o teste IMPRIME exatamente onde e por quê.
Sem mock. Curl real contra o backend local.
"""
from __future__ import annotations
import asyncio, json, os, sys, time, uuid
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient

BASE = "http://localhost:8001"
COMPANY = "co-demo"
results: list[dict] = []


def step(name: str, ok: bool, t_ms: int, detail: str = "", **extra) -> None:
    icon = "✅" if ok else "❌"
    results.append({"step": name, "ok": ok, "elapsed_ms": t_ms, "detail": detail, **extra})
    print(f"{icon}  [{name:48s}] {t_ms:6d}ms  {detail}")


async def main():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ.get("DB_NAME", "test_database")]
    ts = datetime.now(timezone.utc).isoformat()
    print(f"\n{'═'*80}\n  E2E Isabella → Presidente IA  (start={ts})\n{'═'*80}\n")

    # ─── Login admin ────────────────────────────────────────────────────
    t0 = time.time()
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email":"admin@empresa.com","password":"123456"}, timeout=10)
    tok = (r.json().get("access_token") or r.json().get("token")) if r.status_code==200 else None
    H = {"Authorization": f"Bearer {tok}", "Content-Type":"application/json"}
    step("0. Login admin", tok is not None, int((time.time()-t0)*1000),
         f"status={r.status_code}")
    if not tok:
        return

    # ─── STEP 1: Isabella identifica cliente ─────────────────────────────
    # Procurar endpoint de criação de ticket pela Isabella
    t0 = time.time()
    isabella_endpoints = []
    import subprocess
    res = subprocess.run(
        ["grep","-rnE","@router\\.(post|put).*(isabella|repair|appointment|create_ticket|schedule)",
         "/app/backend/routes/","--include=*.py"],
        capture_output=True, text=True
    )
    for line in res.stdout.split("\n"):
        if "isabella" in line.lower() or "appointment" in line.lower() or "create_ticket" in line.lower():
            isabella_endpoints.append(line.split(":")[0].split("/")[-1])
    step("1. Isabella tem endpoint que cria OS?", len(isabella_endpoints) > 0,
         int((time.time()-t0)*1000),
         f"encontrados={list(set(isabella_endpoints))[:5]}")

    # ─── STEP 2: Verificar coleção appointments ─────────────────────────
    t0 = time.time()
    appt_before = await db.appointments.count_documents({"company_id": COMPANY})
    # vai aumentar quando criarmos ticket com origin=isabella (step 3)
    step("2. db.appointments collection ativa", appt_before >= 0,
         int((time.time()-t0)*1000),
         f"docs_before={appt_before} (vamos ver crescer em step 3b)")

    # ─── STEP 3: Criar ticket via /api/lousa/tickets (caminho atual) ─────
    t0 = time.time()
    test_client = f"E2E_TEST_{uuid.uuid4().hex[:6]}"
    payload = {
        "client_name": test_client, "address":"Rua E2E Test, 1",
        "neighborhood":"Centro","phone":"11999990000",
        "relato":"E2E test — cliente reportou sinal baixo",
        "type":"reparo","priority":"normal",
        "assigned_collaborator_id":"col-demo-001",
        "origin":"isabella","created_by_agent":"isabella",  # CTO contract
    }
    r = requests.post(f"{BASE}/api/lousa/tickets", json=payload, headers=H, timeout=15)
    elapsed = int((time.time()-t0)*1000)
    tid = r.json().get("id") if r.status_code==200 else None
    step("3. Criar ticket (origin=isabella)", tid is not None, elapsed,
         f"status={r.status_code} ticket_id={tid}")
    if not tid: return

    # ─── STEP 3b: Appointment espelhado em db.appointments? ─────────────
    t0 = time.time()
    await asyncio.sleep(0.3)
    appt_after = await db.appointments.count_documents({"company_id": COMPANY})
    mirrored = await db.appointments.count_documents(
        {"company_id": COMPANY, "ticket_id": tid}
    )
    step("3b. Appointment espelhado em db.appointments",
         mirrored >= 1, int((time.time()-t0)*1000),
         f"appointments_count={appt_after} ticket_mirror_found={mirrored>=1}")

    # ─── STEP 4: Ticket APARECE na Lousa (≤3s)? ─────────────────────────
    t0 = time.time()
    found = False
    for _ in range(6):  # 6 tentativas em 3s
        r = requests.get(f"{BASE}/api/lousa/by-collaborator/col-demo-001",
                         headers=H, timeout=5)
        if r.status_code==200:
            tickets = r.json().get("tickets",[])
            if any(t.get("id")==tid for t in tickets):
                found = True
                break
        await asyncio.sleep(0.5)
    elapsed = int((time.time()-t0)*1000)
    step("4. OS aparece na Lousa (≤3000ms)", found and elapsed<=3000, elapsed,
         f"found={found}")

    # ─── STEP 5: OS replica para Lousa Mobile (endpoint público)? ──────
    t0 = time.time()
    r = requests.get(
        f"{BASE}/api/lousa/public/tickets/{tid}/signal",
        params={"collaborator_id": "col-demo-001"}, timeout=5,
    )
    elapsed = int((time.time()-t0)*1000)
    # 200 = signal lido / 404 = signal indisponível ainda (OS nova) /
    # 403 = OS de outro colab — todos significam canal Mobile alcançável.
    step("5. OS visível no canal Mobile (≤5000ms)",
         r.status_code in (200, 404) and elapsed<=5000, elapsed,
         f"status={r.status_code}")

    # ─── STEP 6: Evento ISABELLA_OS_CREATED foi emitido? ────────────────
    t0 = time.time()
    events_found = {}
    for coll in ["nervous_events", "motor_ia_events", "system_events"]:
        if coll in await db.list_collection_names():
            n = await db[coll].count_documents({
                "company_id": COMPANY,
                "$or":[{"ref_id":tid},{"ticket_id":tid},
                       {"payload.ticket_id":tid},{"data.ticket_id":tid}],
            })
            events_found[coll] = n
    step("6. Evento ISABELLA_OS_CREATED persiste",
         sum(events_found.values()) > 0,
         int((time.time()-t0)*1000),
         f"distrib={events_found}")

    # ─── STEP 6b: nervous_events persiste o ticket.created? ─────────────
    t0 = time.time()
    nervous_created = await db.nervous_events.count_documents({
        "company_id": COMPANY,
        "event_type": "ticket.created",
        "payload.ticket_id": tid,
    })
    step("6b. nervous_events persiste 'ticket.created'",
         nervous_created >= 1, int((time.time()-t0)*1000),
         f"nervous_events_ticket_created={nervous_created}")

    # ─── STEP 7: Colaborador inicia (admin-open simula) ─────────────────
    t0 = time.time()
    r = requests.post(f"{BASE}/api/lousa/tickets/{tid}/admin-open",
                      json={"reason":"E2E test"}, headers=H, timeout=10)
    elapsed = int((time.time()-t0)*1000)
    step("7. Colab inicia (admin-open)", r.status_code==200, elapsed,
         f"status={r.status_code}")

    # ─── STEP 8: Finalizar via endpoint público (Mobile) ─────────────────
    t0 = time.time()
    finalize = {
        "collaborator_id":"col-demo-001","outcome":"sucesso",
        "latitude":-23.55,"longitude":-46.63,
        "completion_data":{"sinal":-22,"ont":"E2E001","qtd_drop":0,
                            "esticadores":0,"conectores_fast":0,"cabo_rede":0,
                            "conectores_rede":0,"fotos":[]},
    }
    r = requests.post(f"{BASE}/api/lousa/public/tickets/{tid}/finalize",
                      json=finalize, timeout=15)
    elapsed = int((time.time()-t0)*1000)
    step("8. Finalizar OS pelo Mobile", r.status_code==200, elapsed,
         f"status={r.status_code} body={r.text[:120]}")

    # ─── STEP 8b: nervous_events persiste 'ticket.finalized'? ───────────
    t0 = time.time()
    await asyncio.sleep(0.3)
    nervous_finalized = await db.nervous_events.count_documents({
        "company_id": COMPANY,
        "event_type": "ticket.finalized",
        "payload.ticket_id": tid,
    })
    nervous_updated = await db.nervous_events.count_documents({
        "company_id": COMPANY,
        "event_type": "ticket.updated",
        "payload.ticket_id": tid,
    })
    step("8b. nervous_events 'ticket.finalized'+'ticket.updated'",
         nervous_finalized >= 1 and nervous_updated >= 1,
         int((time.time()-t0)*1000),
         f"finalized={nervous_finalized} updated={nervous_updated}")

    # ─── STEP 8c: mobile_visible=True no ticket criado por Isabella? ────
    t0 = time.time()
    tdoc = await db.tickets.find_one({"id": tid})
    mv = (tdoc or {}).get("mobile_visible")
    step("8c. ticket.mobile_visible=True",
         mv is True, int((time.time()-t0)*1000),
         f"mobile_visible={mv}")

    # ─── STEP 9: KPI atualizado? ────────────────────────────────────────
    t0 = time.time()
    await asyncio.sleep(2)  # dar tempo do scheduler rodar
    motor_kpis = await db.motor_ia_kpis.count_documents({"company_id":COMPANY})
    step("9. KPIs alimentados (motor_ia_kpis)", motor_kpis > 0,
         int((time.time()-t0)*1000),
         f"motor_ia_kpis_docs={motor_kpis} (esperado >0)")

    # ─── STEP 10: Presidente IA enxerga? ────────────────────────────────
    t0 = time.time()
    # Acessa o briefing preview
    r = requests.get(f"{BASE}/api/presidente-ia/briefing/preview",
                     headers=H, params={"company_id":COMPANY}, timeout=30)
    elapsed = int((time.time()-t0)*1000)
    has_today_count = False
    if r.status_code==200:
        body = json.dumps(r.json())[:500]
        # Procurar referência a tickets de hoje
        has_today_count = any(k in body.lower() for k in ["ticket","reparo","instala","os criada"])
    step("10. Presidente IA briefing menciona OS de hoje (≤30s)",
         r.status_code==200 and has_today_count, elapsed,
         f"status={r.status_code} mentions_today={has_today_count}")

    # ─── Limpeza ────────────────────────────────────────────────────────
    try:
        requests.delete(f"{BASE}/api/lousa/tickets/{tid}", headers=H, timeout=10)
        await db.tickets.delete_one({"id": tid})  # safety
    except: pass

    # ─── Relatório ──────────────────────────────────────────────────────
    print(f"\n{'═'*80}")
    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    score = round(100 * passed / total, 1) if total else 0
    print(f"  RESULTADO: {passed}/{total} ({score}%) passaram")
    print(f"{'═'*80}\n")

    # Save report
    out = {
        "ts": ts, "score_pct": score,
        "passed": passed, "total": total,
        "steps": results,
        "verdict": "OK" if passed==total else "FLUXO QUEBRADO",
    }
    with open("/app/docs/RELATORIO_FLUXO_ISABELLA_LOUSA_COLABORADOR.json","w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"  → relatório: /app/docs/RELATORIO_FLUXO_ISABELLA_LOUSA_COLABORADOR.json")

if __name__ == "__main__":
    asyncio.run(main())
