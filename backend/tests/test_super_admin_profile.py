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


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
