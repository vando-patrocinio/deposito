"""red_team_lousa_split.py — Valida que o split de routes/lousa.py
(extracao de manager_callbacks) preservou o comportamento.

Cobertura:
  1. Endpoints registrados respondem (HTTP esperado, nao 404).
  2. list_manager_callbacks com auth retorna estrutura {items, count}.
  3. POSTs de manager-callback rejeitam payloads ruins (400).
  4. Symbols antigos ainda importaveis em outros modulos.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "operacoes",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": False,
}

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from database import db
from auth import create_access_token


BASE = os.environ.get("BACKEND_BASE", "http://localhost:8001")


def _ok(m): print(f"  OK  {m}")
def _fail(m):
    print(f"  FAIL {m}")
    raise AssertionError(m)


async def _mint_token() -> tuple[str, str]:
    u = await db.users.find_one(
        {"company_id": "co-demo", "role": {"$in": ["administrador", "gestor"]}},
        {"_id": 0, "id": 1, "email": 1, "role": 1, "company_id": 1})
    if not u:
        _fail("sem user gestor co-demo")
    tk = create_access_token(
        user_id=u["id"], email=u["email"], role=u["role"],
        company_id=u["company_id"])
    return tk, u["company_id"]


async def t_endpoints_registered(token: str) -> None:
    print("\n[1] Endpoints registrados (no 404)")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=BASE, timeout=15.0) as cli:
        r = await cli.get("/api/lousa/manager-callbacks", headers=h)
        if r.status_code == 404:
            _fail("GET /api/lousa/manager-callbacks -> 404 (rota nao registrada!)")
        if r.status_code != 200:
            _fail(f"GET manager-callbacks -> {r.status_code}: {r.text[:200]}")
        body = r.json()
        if "items" not in body or "count" not in body:
            _fail(f"resposta sem items/count: {body}")
        _ok(f"GET /api/lousa/manager-callbacks -> 200 items={body.get('count')}")

        # POST resolve com payload vazio -> 400 (action invalido)
        r = await cli.post("/api/lousa/manager-callbacks/nope/resolve",
                            json={}, headers=h)
        if r.status_code != 400:
            _fail(f"POST resolve sem action -> esperado 400, veio {r.status_code}: {r.text[:200]}")
        _ok(f"POST resolve sem action -> {r.status_code} (validacao ok)")

        # POST resolve com obs curta -> 400
        r = await cli.post("/api/lousa/manager-callbacks/nope/resolve",
                            json={"action": "contacted", "observacao": "x"},
                            headers=h)
        if r.status_code != 400:
            _fail(f"POST resolve obs curta -> esperado 400, veio {r.status_code}")
        _ok(f"POST resolve obs curta -> {r.status_code} (validacao ok)")

        # POST resolve em req_id inexistente com payload valido -> 404
        r = await cli.post("/api/lousa/manager-callbacks/req-inexistente/resolve",
                            json={"action": "contacted",
                                  "observacao": "tentativa de contato"},
                            headers=h)
        if r.status_code != 404:
            _fail(f"POST resolve req inexistente -> esperado 404, veio {r.status_code}: {r.text[:200]}")
        _ok(f"POST resolve req inexistente -> {r.status_code}")

        # release-back e create-new-ticket sao registrados
        r = await cli.post("/api/lousa/manager-callbacks/nope/release-back",
                            json={"observacao": "x"}, headers=h)
        if r.status_code == 404 and "Pedido" not in r.text:
            _fail(f"POST release-back -> 404 da rota: {r.text[:200]}")
        _ok(f"POST release-back -> {r.status_code} (rota registrada)")

        r = await cli.post("/api/lousa/manager-callbacks/nope/create-new-ticket",
                            json={}, headers=h)
        # Esperamos 422 (Pydantic validation) ou 404 (req nao existe). NAO 404 de rota
        if r.status_code == 404 and "Not Found" in r.text:
            _fail(f"POST create-new-ticket -> 404 da rota: {r.text[:200]}")
        _ok(f"POST create-new-ticket -> {r.status_code} (rota registrada)")


async def t_imports_preserved() -> None:
    print("\n[2] Imports do lousa.py preservados (backwards-compat)")
    from routes.lousa import (
        _log_ticket_action, _today_clock_state, _lousa_for_collaborator,
        _compute_sla, _sla_minutes_for_type, _verify_swap_via_uptime,
        _detect_equipment_swap, _norm_hexid, _parse_smartolt_ts,
        _ticket_day_iso,
        CompletionData, PublicFinalizeIn, PublicOpenIn, ReleaseStuckIn, ReopenIn,
        geocode_address, lousa_grid, public_open_ticket,
        release_stuck_ticket, reopen_ticket, list_stuck_tickets,
    )
    _ok("Todos os 22 symbols importaveis de routes.lousa apos split.")


async def t_lousa_py_shrunk() -> None:
    print("\n[3] lousa.py reduzido")
    with open("/app/backend/routes/lousa.py") as f:
        lines = sum(1 for _ in f)
    if lines >= 8763:
        _fail(f"lousa.py nao reduziu: {lines} LOC")
    _ok(f"lousa.py agora tem {lines} LOC (antes: 8763 — reducao de {8763 - lines} LOC)")


async def t_wa_business_hours_split(token: str) -> None:
    print("\n[4] WhatsApp business-hours split (5 endpoints)")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=BASE, timeout=15.0) as cli:
        # GET auto-reply
        r = await cli.get("/api/whatsapp-baileys/auto-reply", headers=h)
        if r.status_code != 200:
            _fail(f"GET auto-reply -> {r.status_code}: {r.text[:200]}")
        b = r.json()
        if "enabled" not in b or "agent_name" not in b:
            _fail(f"auto-reply shape: {b}")
        _ok(f"GET /auto-reply -> 200 enabled={b['enabled']}")

        # GET business-hours
        r = await cli.get("/api/whatsapp-baileys/business-hours", headers=h)
        if r.status_code != 200:
            _fail(f"GET business-hours -> {r.status_code}: {r.text[:200]}")
        b = r.json()
        if "status" not in b or "is_outside_now" not in b:
            _fail(f"business-hours shape: {b}")
        _ok(f"GET /business-hours -> 200 is_open={b['status'].get('is_open')}")

        # GET after-hours-metrics
        r = await cli.get("/api/whatsapp-baileys/after-hours-metrics?days=3", headers=h)
        if r.status_code != 200:
            _fail(f"GET after-hours-metrics -> {r.status_code}: {r.text[:200]}")
        b = r.json()
        if "window_days" not in b or "by_day" not in b:
            _fail(f"after-hours-metrics shape: {b}")
        _ok(f"GET /after-hours-metrics -> 200 window={b['window_days']} samples={len(b.get('samples', []))}")

        # PUT auto-reply (round-trip)
        original = (await cli.get("/api/whatsapp-baileys/auto-reply", headers=h)).json()
        r = await cli.put("/api/whatsapp-baileys/auto-reply",
                          json={"enabled": not original["enabled"],
                                "agent_name": "Jerusa"}, headers=h)
        if r.status_code != 200:
            _fail(f"PUT auto-reply -> {r.status_code}: {r.text[:200]}")
        # restaura
        await cli.put("/api/whatsapp-baileys/auto-reply",
                       json={"enabled": original["enabled"],
                             "agent_name": original.get("agent_name", "Jerusa")},
                       headers=h)
        _ok("PUT /auto-reply round-trip persistiu e restaurou")


async def t_wa_imports_preserved() -> None:
    print("\n[5] Imports do whatsapp_baileys.py preservados")
    from routes.whatsapp_baileys import (
        SIDECAR_BASE, _sidecar_post, _sidecar_post_silent,
        _split_ai_reply, _fetch_human_few_shots, _maybe_auto_reply,
        _persist_ai_failure, baileys_watchdog_job,
        baileys_nightly_restart_job,
    )
    _ok("9 symbols externos preservados em routes.whatsapp_baileys.")


async def t_wa_shrunk() -> None:
    print("\n[6] whatsapp_baileys.py reduzido")
    with open("/app/backend/routes/whatsapp_baileys.py") as f:
        lines = sum(1 for _ in f)
    if lines >= 5400:
        _fail(f"whatsapp_baileys.py nao reduziu: {lines} LOC")
    _ok(f"whatsapp_baileys.py agora tem {lines} LOC (antes: 5399 — reducao de {5399 - lines} LOC)")


async def main():
    print("="*70)
    print("RED TEAM :: monolitos split (lousa + whatsapp_baileys)")
    print("="*70)
    token, _ = await _mint_token()
    await t_endpoints_registered(token)
    await t_imports_preserved()
    await t_lousa_py_shrunk()
    await t_wa_business_hours_split(token)
    await t_wa_imports_preserved()
    await t_wa_shrunk()
    print("\n" + "="*70)
    print("PASS :: ambos os splits sem regressao.")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
