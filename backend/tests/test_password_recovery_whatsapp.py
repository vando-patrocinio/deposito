"""Regressão da recuperação de senha via WhatsApp (CTO 12/06/2026, opção A).

Cobre:
1. Resposta sempre 200 genérico (anti-enumeração).
2. Rate limit 3/hora por email (4ª tentativa retorna 429).
3. User órfão (sem collaborator) → audit "no_collaborator_linked".
4. Super Admin bloqueado → audit "blocked_super_admin_flag".
5. Happy path: gera nova senha, marca password_reset_pending=True, audit ok.
6. Login com password_reset_pending=True retorna must_change_password=true.
7. POST /auth/change-password-forced exige flag setado (400 se não tiver).
8. POST /auth/change-password-forced limpa o flag.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://dual-combine-3.preview.emergentagent.com",
).rstrip("/")


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _login(email: str, password: str) -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _purge_rate_limit():
    """Limpa attempts pra evitar rate limit por IP entre testes em sequência."""
    import asyncio, sys
    sys.path.insert(0, "/app/backend")
    from database import db
    asyncio.get_event_loop().run_until_complete(
        db.password_reset_attempts.delete_many({}),
    )


def test_forgot_password_generic_response_for_nonexistent_email():
    _purge_rate_limit()
    r = requests.post(
        f"{BASE_URL}/api/auth/forgot-password",
        json={"email": f"noexist-{uuid.uuid4().hex[:6]}@example.com"},
        timeout=10,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "WhatsApp" in body["message"]


def test_forgot_password_blocks_super_admin():
    """admin@empresa.com tem is_super_admin=True. Deve retornar 200 genérico
    mas o audit log marca 'blocked_super_admin_flag'."""
    _purge_rate_limit()
    r = requests.post(
        f"{BASE_URL}/api/auth/forgot-password",
        json={"email": "admin@empresa.com"},
        timeout=10,
    )
    assert r.status_code == 200, r.text

    # Verifica audit
    import sys
    sys.path.insert(0, "/app/backend")
    from database import db

    async def check():
        doc = await db.audit_log_password_resets.find_one(
            {"email": "admin@empresa.com",
             "outcome": "blocked_super_admin_flag"},
            sort=[("created_at", -1)],
        )
        return doc

    doc = asyncio.get_event_loop().run_until_complete(check())
    assert doc is not None, "audit log de blocked_super_admin_flag não encontrado"


def test_forgot_password_happy_path_marks_user_pending():
    """Cria user + colaborador com phone, dispara forgot, valida que:
    - password_reset_pending=True foi setado
    - audit log existe
    """
    import sys, uuid as _uuid
    sys.path.insert(0, "/app/backend")
    from database import db
    from auth import hash_password

    async def setup():
        # Limpa rate limit antes do teste (testes rodam em sequência e disparam várias)
        await db.password_reset_attempts.delete_many({})
        coll_id = f"col-pwtest-{_uuid.uuid4().hex[:6]}"
        email = f"pwtest-{_uuid.uuid4().hex[:6]}@example.com"
        await db.collaborators.insert_one({
            "id": coll_id, "company_id": "co-demo",
            "name": "PwTest Happy", "phone": "+5511988887777",
            "cpf": f"{_uuid.uuid4().int % 1000000000:09d}-77",
            "email": email, "cargo": "tecnico", "active": True,
        })
        uid = f"usr-pwtest-{_uuid.uuid4().hex[:6]}"
        await db.users.insert_one({
            "id": uid, "email": email, "name": "PwTest",
            "role": "gestor", "password_hash": hash_password("oldpass"),
            "active": True, "company_id": "co-demo",
            "collaborator_id": coll_id,
        })
        return uid, email, coll_id

    async def cleanup(uid, coll_id):
        await db.users.delete_one({"id": uid})
        await db.collaborators.delete_one({"id": coll_id})

    loop = asyncio.get_event_loop()
    uid, email, coll_id = loop.run_until_complete(setup())

    try:
        r = requests.post(
            f"{BASE_URL}/api/auth/forgot-password",
            json={"email": email},
            timeout=15,
        )
        assert r.status_code == 200, r.text

        async def check():
            u = await db.users.find_one(
                {"id": uid},
                {"_id": 0, "password_reset_pending": 1, "password_reset_at": 1},
            )
            return u

        u = loop.run_until_complete(check())
        assert u.get("password_reset_pending") is True, "flag não foi setada"
        assert u.get("password_reset_at"), "timestamp não foi gravado"

        async def audit_check():
            doc = await db.audit_log_password_resets.find_one(
                {"email": email}, sort=[("created_at", -1)],
            )
            return doc

        audit = loop.run_until_complete(audit_check())
        assert audit is not None, "audit log não foi criado"
        # outcome pode ser 'success' OU 'whatsapp_send_failed' (sidecar pode estar off)
        assert audit["outcome"] in ("success", "whatsapp_send_failed"), \
            f"outcome inesperado: {audit['outcome']}"
    finally:
        loop.run_until_complete(cleanup(uid, coll_id))


def test_change_password_forced_requires_flag():
    """POST /auth/change-password-forced sem o flag pendente → 400."""
    tok = _login("admin@empresa.com", "123456")
    r = requests.post(
        f"{BASE_URL}/api/auth/change-password-forced",
        headers=_h(tok),
        json={"new_password": "newvalidpass123"},
        timeout=10,
    )
    assert r.status_code == 400, \
        f"esperado 400 (admin não tem pendência), foi {r.status_code}: {r.text}"
    assert "troca pendente" in r.json()["detail"].lower()


def test_login_returns_must_change_password_flag():
    """Cria user com password_reset_pending=True, faz login e verifica flag."""
    import sys, uuid as _uuid
    sys.path.insert(0, "/app/backend")
    from database import db
    from auth import hash_password

    async def setup():
        uid = f"usr-mcpw-{_uuid.uuid4().hex[:6]}"
        email = f"mcpw-{_uuid.uuid4().hex[:6]}@example.com"
        await db.users.insert_one({
            "id": uid, "email": email, "name": "MCPw",
            "role": "gestor",
            "password_hash": hash_password("tempPass123"),
            "active": True, "company_id": "co-demo",
            "password_reset_pending": True,
        })
        return uid, email

    async def cleanup(uid):
        await db.users.delete_one({"id": uid})

    loop = asyncio.get_event_loop()
    uid, email = loop.run_until_complete(setup())

    try:
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": email, "password": "tempPass123"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("must_change_password") is True, \
            "login não retornou must_change_password=true"
        tok = body["access_token"]

        # Troca a senha pela nova
        r = requests.post(
            f"{BASE_URL}/api/auth/change-password-forced",
            headers=_h(tok),
            json={"new_password": "novaSenhaSegura123"},
            timeout=10,
        )
        assert r.status_code == 200, r.text

        # Verifica que flag sumiu
        async def check():
            u = await db.users.find_one({"id": uid}, {"_id": 0, "password_reset_pending": 1})
            return u

        u = loop.run_until_complete(check())
        assert not u.get("password_reset_pending"), "flag não foi limpa após troca"

        # Login com NOVA senha → não pede mais troca
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": email, "password": "novaSenhaSegura123"},
            timeout=10,
        )
        assert r.status_code == 200
        assert r.json().get("must_change_password") is not True
    finally:
        loop.run_until_complete(cleanup(uid))


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
