"""red_team_colaborador_rbac.py — Mobile do colaborador NUNCA pega 403.

Auditoria de RBAC para role=colaborador. Garante que os endpoints
chamados pelo `LousaMobile.js` / `CollaboratorApp.js` respondem com
qualquer status EXCETO 403.

Validacao da regressao do bug DIOGO HENRIQUE — onde o middleware
RBAC bloqueava `role=colaborador` em `/api/lousa/by-collaborator/*`
e o app ficava preso em "Carregando lousa...".
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "rbac",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
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


async def main():
    print("="*70)
    print("RED TEAM :: role=colaborador NUNCA pega 403 no app mobile")
    print("="*70)

    user = await db.users.find_one(
        {"email": "diogo@empresa.com"}, {"_id": 0})
    if not user or user.get("role") != "colaborador":
        _fail(f"Usuario DIOGO deve ter role=colaborador (hoje: {user.get('role') if user else None!r})")
    tk = create_access_token(
        user_id=user["id"], email=user["email"],
        role=user["role"], company_id=user.get("company_id"))

    diogo = await db.collaborators.find_one(
        {"name": {"$regex": "DIOGO"}}, {"_id": 0, "id": 1})
    cid = diogo["id"]

    # Endpoints que o LousaMobile / CollaboratorApp realmente chama.
    # Se algum responder 403, mobile fica preso (loop infinito de spinner).
    endpoints = [
        ("GET", f"/api/lousa/by-collaborator/{cid}",   "Carregando lousa…"),
        ("GET", "/api/lousa/me",                         "Lousa do proprio user"),
        ("GET", f"/api/clock-records?collaborator_id={cid}&days=1",
                                                          "Estado de ponto do dia"),
        ("GET", f"/api/collaborators/{cid}",            "Proprio cadastro"),
        ("GET", f"/api/fleet/odom/today/public/{cid}",  "Odometro do dia"),
    ]

    headers = {"Authorization": f"Bearer {tk}"}
    blocked: list[str] = []

    async with httpx.AsyncClient(base_url=BASE, timeout=15.0) as cli:
        for method, path, label in endpoints:
            r = await cli.request(method, path, headers=headers)
            if r.status_code == 403:
                blocked.append(
                    f"{method} {path} -> 403 ({label}) :: {r.text[:120]}")
            else:
                _ok(f"{method} {path} -> {r.status_code} ({label})")

        # POST mobile/health-event tem que aceitar colaborador
        r = await cli.post("/api/mobile/health-event", headers=headers, json={
            "kind": "lousa_load_failed",
            "collaborator_id": cid,
            "status": 520,
            "detail": "red_team probe",
            "ua": "red-team/1.0",
            "url": "https://test/",
        })
        if r.status_code != 200:
            blocked.append(f"POST /api/mobile/health-event -> {r.status_code} :: {r.text[:200]}")
        else:
            _ok(f"POST /api/mobile/health-event -> 200 (telemetria mobile)")

    if blocked:
        print("")
        for b in blocked:
            print(f"  FAIL {b}")
        _fail(f"{len(blocked)} endpoint(s) ainda bloqueando role=colaborador.")

    print("\n" + "="*70)
    print("PASS :: nenhum endpoint critico do mobile retorna 403 pra colaborador.")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
