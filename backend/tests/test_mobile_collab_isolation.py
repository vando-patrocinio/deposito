"""E2E pra garantir que app mobile do colaborador SÓ mostra bolhas
atribuídas a ele, mesmo quando o admin/auditor é o próprio colaborador.

Cenários:
  1. Técnico normal acessa sua Lousa → vê só suas bolhas, não as de outro
     técnico.
  2. Admin/auditor (sem collaborator_id no token) acessa /by-collaborator/{cid}
     com admin_test=1 → vê todas as bolhas do company (modo cross).
  3. Admin que TAMBÉM é colaborador acessa o PRÓPRIO id com admin_test=1
     → vê APENAS suas bolhas (não as de outros técnicos).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import httpx
import pytest

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8001")


@pytest.mark.asyncio
async def test_mobile_strict_isolation():
    from database import db
    import jwt
    from auth import _jwt_secret, JWT_ALGORITHM
    from datetime import timedelta

    def _make_token(role: str, collab_id: str = None):
        payload = {
            "sub": f"u-{role}",
            "email": f"{role}@test.com",
            "role": role,
            "company_id": cid,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "iat": datetime.now(timezone.utc),
            "type": "access",
        }
        if collab_id:
            payload["collaborator_id"] = collab_id
        return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)

    cid = "co-demo"
    suffix = uuid.uuid4().hex[:6]
    today = datetime.now(timezone.utc).isoformat()
    # Bate ponto pra liberar a lousa (clock_in_enabled default = True)
    today_br = datetime.now(timezone.utc).astimezone(
        timezone(__import__("datetime").timedelta(hours=-3))
    ).strftime("%Y-%m-%d")

    coll_a_id = f"collab-A-{suffix}"
    coll_b_id = f"collab-B-{suffix}"
    tk_a_id = f"tkt-A-{suffix}"
    tk_b_id = f"tkt-B-{suffix}"

    # 2 colaboradores no mesmo company
    await db.collaborators.insert_many([
        {"id": coll_a_id, "company_id": cid, "name": f"Tec A {suffix}",
          "role": "tecnico", "clock_in_enabled": False, "active": True,
          "cpf": f"cpf-A-{suffix}"},
        {"id": coll_b_id, "company_id": cid, "name": f"Tec B {suffix}",
          "role": "tecnico", "clock_in_enabled": False, "active": True,
          "cpf": f"cpf-B-{suffix}"},
    ])

    # 1 ticket pendente atribuído a A, outro atribuído a B (hoje)
    base_ticket = {
        "company_id": cid, "status": "pendente", "priority": "normal",
        "type": "instalacao",
        "client_snapshot": {"name": "Cliente Teste", "phone": "21999"},
        "scheduled_date": today_br,
        "opened_at": today, "created_at": today,
    }
    await db.tickets.insert_many([
        {**base_ticket, "id": tk_a_id, "assigned_collaborator_id": coll_a_id},
        {**base_ticket, "id": tk_b_id, "assigned_collaborator_id": coll_b_id},
    ])

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # ── 1. Sem token: app normal do Tec A → vê só tk_a ──
            r1 = await client.get(
                f"{BACKEND}/api/lousa/by-collaborator/{coll_a_id}",
            )
            assert r1.status_code == 200, r1.text
            tickets_1 = [t["id"] for t in r1.json().get("tickets", [])]
            assert tk_a_id in tickets_1, "Tec A não vê o próprio ticket!"
            assert tk_b_id not in tickets_1, \
                f"BUG: Tec A vê ticket de Tec B! {tickets_1}"
            print(f"✓ Tec A vê só suas bolhas (sem token): {tickets_1}")

            # ── 2. Admin SEM collaborator_id + admin_test=1 → vê todas ──
            admin_token = _make_token("administrador", collab_id=None)
            r2 = await client.get(
                f"{BACKEND}/api/lousa/by-collaborator/{coll_a_id}"
                f"?admin_test=1",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert r2.status_code == 200, r2.text
            tickets_2 = [t["id"] for t in r2.json().get("tickets", [])]
            assert tk_a_id in tickets_2 and tk_b_id in tickets_2, \
                f"Admin cross-collab deveria ver os 2 tickets: {tickets_2}"
            print(f"✓ Admin (sem collab_id) cross-mode vê todos: "
                    f"{len(tickets_2)} tickets")

            # ── 3. Admin que TAMBÉM é Tec A (collaborator_id=coll_a_id)
            #       acessa o PRÓPRIO id com admin_test=1 → SÓ vê suas. ──
            admin_self_token = _make_token("administrador",
                                                collab_id=coll_a_id)
            r3 = await client.get(
                f"{BACKEND}/api/lousa/by-collaborator/{coll_a_id}"
                f"?admin_test=1",
                headers={"Authorization": f"Bearer {admin_self_token}"},
            )
            assert r3.status_code == 200, r3.text
            tickets_3 = [t["id"] for t in r3.json().get("tickets", [])]
            assert tk_a_id in tickets_3, "Tec A (admin) não vê o próprio!"
            assert tk_b_id not in tickets_3, \
                (f"BUG: Tec A (admin) viendo bolha alheia! "
                  f"{tickets_3}")
            print(f"✓ Admin que é Tec A (collaborator_id=cid + admin_test=1) "
                    f"NÃO vê bolhas alheias: {tickets_3}")

            # ── 4. Admin que é Tec A acessa o id de Tec B → vê só de B ──
            r4 = await client.get(
                f"{BACKEND}/api/lousa/by-collaborator/{coll_b_id}"
                f"?admin_test=1",
                headers={"Authorization": f"Bearer {admin_self_token}"},
            )
            assert r4.status_code == 200, r4.text
            tickets_4 = [t["id"] for t in r4.json().get("tickets", [])]
            # admin acessando OUTRO collab com admin_test → cross mode ativa
            assert tk_a_id in tickets_4 and tk_b_id in tickets_4, \
                (f"Admin acessando outro collab com admin_test=1 deveria "
                  f"ver todos do company: {tickets_4}")
            print(f"✓ Admin acessando OUTRO collab cross-mode vê todos: "
                    f"{len(tickets_4)} tickets")

    finally:
        await db.collaborators.delete_many({"id": {"$in": [coll_a_id, coll_b_id]}})
        await db.tickets.delete_many({"id": {"$in": [tk_a_id, tk_b_id]}})
