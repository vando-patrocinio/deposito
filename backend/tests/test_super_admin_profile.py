"""Regressão do 5º seed profile 'Super Admin' e do guard RBAC associado.

Valida:
1. Seed cria/possui o perfil Super Admin com flags corretos.
2. Lista de perfis inclui super_admin com is_super_admin_profile=True.
3. Admin (is_super_admin=true legado) consegue atribuir Super Admin a outro user.
4. Após reset, perfil pode ser desatribuído por outro Super Admin.
5. Helpers `is_super_admin_profile_id` e `user_has_super_admin_profile`.
"""
from __future__ import annotations

import asyncio
import os

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://dual-combine-3.preview.emergentagent.com",
).rstrip("/")

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"
TARGET_EMAIL = "msaldanhavargasmiranda@gmail.com"


def _login(email: str, password: str) -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def test_seed_super_admin_profile_present():
    tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    # Re-run seed (idempotente)
    r = requests.post(f"{BASE_URL}/api/access-profiles/seed", headers=_h(tok), timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "skipped" in body  # seed idempotente

    # Lista
    r = requests.get(f"{BASE_URL}/api/access-profiles", headers=_h(tok), timeout=10)
    assert r.status_code == 200
    profiles = r.json()
    by_key = {p["key"]: p for p in profiles}

    # Os 5 seeds devem estar presentes
    expected = {"colaborador", "gestao", "administrador", "auditor", "super_admin"}
    assert expected.issubset(set(by_key.keys())), f"perfis ausentes: {expected - set(by_key.keys())}"

    sa = by_key["super_admin"]
    assert sa["is_seed"] is True
    assert sa["is_super_admin_profile"] is True
    assert sa["is_admin_level"] is True
    assert len(sa["access_tags"]) >= 50  # acesso total (ALL_TAG_KEYS)

    # Outros seeds NÃO podem ter is_super_admin_profile=True
    for key in ("colaborador", "gestao", "administrador", "auditor"):
        assert by_key[key]["is_super_admin_profile"] is False, f"{key} não deveria ser super admin profile"


def test_admin_can_assign_and_revoke_super_admin_profile():
    tok = _login(ADMIN_EMAIL, ADMIN_PASS)

    # IDs dos perfis
    r = requests.get(f"{BASE_URL}/api/access-profiles", headers=_h(tok), timeout=10)
    profiles = r.json()
    super_pid = next(p["id"] for p in profiles if p["key"] == "super_admin")

    # User alvo
    r = requests.get(f"{BASE_URL}/api/users", headers=_h(tok), timeout=10)
    users = r.json()
    users_list = users if isinstance(users, list) else users.get("items") or users.get("users") or []
    target = next((u for u in users_list if u.get("email") == TARGET_EMAIL), None)
    assert target is not None, f"user {TARGET_EMAIL} não encontrado"
    target_uid = target["id"]
    original_pid = target.get("profile_id")

    # Atribui Super Admin (admin tem is_super_admin=true legado, deve passar)
    r = requests.put(
        f"{BASE_URL}/api/users/{target_uid}",
        headers=_h(tok),
        json={"profile_id": super_pid},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    assert r.json()["profile_id"] == super_pid

    # Revoga (idem, admin pode)
    r = requests.put(
        f"{BASE_URL}/api/users/{target_uid}",
        headers=_h(tok),
        json={"profile_id": original_pid},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    assert r.json().get("profile_id") == original_pid


def test_helpers_directly():
    """Testa helpers de services.access_profiles sem passar pela API."""
    import sys
    sys.path.insert(0, "/app/backend")
    from services.access_profiles import (
        is_super_admin_profile_id,
        user_has_super_admin_profile,
    )
    from database import db

    async def run():
        # Acha o super_admin profile no tenant demo
        p = await db.access_profiles.find_one(
            {"company_id": "co-demo", "key": "super_admin"},
            {"_id": 0, "id": 1},
        )
        assert p is not None, "Super Admin profile não existe em co-demo"
        super_pid = p["id"]

        assert await is_super_admin_profile_id(super_pid, "co-demo") is True
        assert await is_super_admin_profile_id("prof-fake", "co-demo") is False

        # User com profile_id = super_admin
        fake_user = {"company_id": "co-demo", "profile_id": super_pid}
        assert await user_has_super_admin_profile(fake_user) is True

        # User sem profile_id
        assert await user_has_super_admin_profile({"company_id": "co-demo"}) is False

        # User com profile diferente
        gestao = await db.access_profiles.find_one(
            {"company_id": "co-demo", "key": "gestao"}, {"_id": 0, "id": 1},
        )
        if gestao:
            assert await user_has_super_admin_profile(
                {"company_id": "co-demo", "profile_id": gestao["id"]},
            ) is False

    asyncio.get_event_loop().run_until_complete(run())


def test_rbac_visibility_filters_super_admin_from_non_super():
    """RBAC visual: gestor/auditor comum NÃO vê o perfil Super Admin
    em GET /api/access-profiles nem GET /api/access-profiles/{id}.
    Apenas Super Admin vê.
    """
    # ADMIN (is_super_admin=true legado) vê os 5 seeds
    admin_tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    r = requests.get(f"{BASE_URL}/api/access-profiles", headers=_h(admin_tok), timeout=10)
    assert r.status_code == 200
    admin_keys = {p["key"] for p in r.json()}
    assert "super_admin" in admin_keys, "Admin (super) deveria ver super_admin"

    # Pega o id do super_admin
    super_pid = next(p["id"] for p in r.json() if p["key"] == "super_admin")

    # Admin acessa detail → 200
    r = requests.get(f"{BASE_URL}/api/access-profiles/{super_pid}", headers=_h(admin_tok), timeout=10)
    assert r.status_code == 200, "Admin (super) deveria poder GET o detail"

    # Cria um gestor temp em memória via Mongo direto para testar filtro
    # (evita dependência de credenciais persistidas)
    import asyncio, sys
    sys.path.insert(0, "/app/backend")
    from database import db
    from auth import hash_password, create_access_token
    import uuid as _uuid

    async def setup_temp_gestor():
        uid = f"usr-test-{_uuid.uuid4().hex[:6]}"
        await db.users.insert_one({
            "id": uid,
            "email": f"test-rbac-{_uuid.uuid4().hex[:6]}@local",
            "name": "RBAC Test Gestor",
            "role": "gestor",
            "password_hash": hash_password("x"),
            "active": True,
            "company_id": "co-demo",
            "is_super_admin": False,
        })
        return uid

    async def cleanup_temp_gestor(uid):
        await db.users.delete_one({"id": uid})

    loop = asyncio.get_event_loop()
    temp_uid = loop.run_until_complete(setup_temp_gestor())
    try:
        # Cria token diretamente (bypass login flow)
        token = create_access_token(
            user_id=temp_uid,
            email=f"test-token-{temp_uid}@local",
            role="gestor",
            company_id="co-demo",
            is_super_admin=False,
        )
        h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # Gestor lista perfis → NÃO deve ver super_admin
        r = requests.get(f"{BASE_URL}/api/access-profiles", headers=h, timeout=10)
        assert r.status_code == 200, r.text
        gestor_keys = {p["key"] for p in r.json()}
        assert "super_admin" not in gestor_keys, \
            f"Gestor NÃO deveria ver super_admin. Viu: {gestor_keys}"
        assert {"colaborador", "gestao", "administrador", "auditor"}.issubset(gestor_keys)

        # Gestor GET direto no super_admin → 404
        r = requests.get(f"{BASE_URL}/api/access-profiles/{super_pid}", headers=h, timeout=10)
        assert r.status_code == 404, \
            f"Gestor GET direto super_admin deveria ser 404, foi {r.status_code}: {r.text}"
    finally:
        loop.run_until_complete(cleanup_temp_gestor(temp_uid))


def test_rbac_visibility_filters_super_admin_users_from_list():
    """RBAC visual: GET /api/users esconde usuários com perfil Super Admin
    do solicitante que não é Super Admin.
    """
    import asyncio, sys, uuid as _uuid
    sys.path.insert(0, "/app/backend")
    from database import db
    from auth import hash_password, create_access_token

    admin_tok = _login(ADMIN_EMAIL, ADMIN_PASS)

    # Pega super_pid + cria um user super-admin temp + um gestor temp
    async def setup():
        sa = await db.access_profiles.find_one(
            {"company_id": "co-demo", "key": "super_admin"}, {"_id": 0, "id": 1, "access_tags": 1},
        )
        # cria user com perfil super_admin
        sa_uid = f"usr-test-sa-{_uuid.uuid4().hex[:6]}"
        await db.users.insert_one({
            "id": sa_uid,
            "email": f"test-sa-{_uuid.uuid4().hex[:6]}@local",
            "name": "RBAC SA Target",
            "role": "gestor",
            "password_hash": hash_password("x"),
            "active": True,
            "company_id": "co-demo",
            "profile_id": sa["id"],
            "access_tags": sa.get("access_tags") or [],
            "is_super_admin": False,
        })
        # cria gestor temp como solicitante (role=administrador para passar
        # o require_role mas SEM is_super_admin flag → meu filtro deve agir)
        req_uid = f"usr-test-req-{_uuid.uuid4().hex[:6]}"
        await db.users.insert_one({
            "id": req_uid,
            "email": f"test-req-{_uuid.uuid4().hex[:6]}@local",
            "name": "RBAC Requester",
            "role": "administrador",
            "password_hash": hash_password("x"),
            "active": True,
            "company_id": "co-demo",
            "is_super_admin": False,
        })
        return sa_uid, req_uid

    async def cleanup(sa_uid, req_uid):
        await db.users.delete_one({"id": sa_uid})
        await db.users.delete_one({"id": req_uid})

    loop = asyncio.get_event_loop()
    sa_uid, req_uid = loop.run_until_complete(setup())
    try:
        # Token do solicitante (administrador comum sem super admin)
        token = create_access_token(
            user_id=req_uid,
            email=f"test-req-{req_uid}@local",
            role="administrador",
            company_id="co-demo",
            is_super_admin=False,
        )
        h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        r = requests.get(f"{BASE_URL}/api/users", headers=h, timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        items = data if isinstance(data, list) else data.get("items") or data.get("users") or []
        ids = {u.get("id") for u in items}

        # O SA temp NÃO deve aparecer; o requester DEVE aparecer (ele é gestor comum)
        assert sa_uid not in ids, "Usuário com perfil Super Admin NÃO deveria aparecer"
        assert req_uid in ids, "Solicitante deveria se ver na lista"

        # Confere com admin: SA temp APARECE
        r = requests.get(f"{BASE_URL}/api/users", headers=_h(admin_tok), timeout=10)
        assert r.status_code == 200
        data = r.json()
        items = data if isinstance(data, list) else data.get("items") or data.get("users") or []
        ids_admin = {u.get("id") for u in items}
        assert sa_uid in ids_admin, "Admin (super) deveria ver o SA temp"
    finally:
        loop.run_until_complete(cleanup(sa_uid, req_uid))


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
