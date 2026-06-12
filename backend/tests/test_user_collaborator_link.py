"""Regressão dos endpoints de vínculo manual user ↔ colaborador.

Cobre:
1. GET /api/users/unlinked retorna apenas users sem collaborator_id.
2. POST /api/collaborators/{cid}/link-user/{uid} vincula com sucesso.
3. Linking propaga profile_id+access_tags do collaborador para o user.
4. Duplo link no mesmo colaborador retorna 409.
5. DELETE /api/collaborators/{cid}/link-user desvincula com sucesso.
6. User volta para a lista de unlinked após unlink.
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://dual-combine-3.preview.emergentagent.com",
).rstrip("/")

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


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


@pytest.fixture(scope="module")
def admin_tok():
    return _login(ADMIN_EMAIL, ADMIN_PASS)


@pytest.fixture
def temp_colab(admin_tok):
    """Cria colaborador efêmero, devolve dict + cleanup automático."""
    suffix = uuid.uuid4().hex[:6]
    payload = {
        "name": f"Link Test {suffix}",
        "cpf": f"{uuid.uuid4().int % 1000000000:09d}-99",
        "email": f"link-{suffix}@example.com",
        "phone": "+5511999999990",
        "cargo": "tecnico",
    }
    r = requests.post(f"{BASE_URL}/api/collaborators", headers=_h(admin_tok), json=payload, timeout=10)
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    yield {"id": cid, **payload}
    requests.delete(f"{BASE_URL}/api/collaborators/{cid}", headers=_h(admin_tok), timeout=10)


def _pick_unlinked_user(tok: str) -> str:
    r = requests.get(f"{BASE_URL}/api/users/unlinked", headers=_h(tok), timeout=10)
    assert r.status_code == 200, r.text
    users = r.json()
    # Escolhe um user ativo qualquer (que não seja super admin via flag)
    candidate = next(
        (u for u in users
         if u.get("active") is True
         and not u.get("is_super_admin")
         and "@" in (u.get("email") or "")),
        None,
    )
    assert candidate is not None, "nenhum user unlinked disponível para teste"
    return candidate["id"]


def test_list_unlinked_users(admin_tok):
    r = requests.get(f"{BASE_URL}/api/users/unlinked", headers=_h(admin_tok), timeout=10)
    assert r.status_code == 200, r.text
    users = r.json()
    assert isinstance(users, list)
    # Garantia: nenhum user na lista tem collaborator_id
    for u in users:
        assert not u.get("collaborator_id"), f"user {u.get('email')} tem collab_id={u.get('collaborator_id')}"


def test_link_and_unlink_user(admin_tok, temp_colab):
    cid = temp_colab["id"]
    uid = _pick_unlinked_user(admin_tok)

    # 1) LINK
    r = requests.post(
        f"{BASE_URL}/api/collaborators/{cid}/link-user/{uid}",
        headers=_h(admin_tok),
        timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["user"]["collaborator_id"] == cid

    # 2) User saiu da lista unlinked
    r = requests.get(f"{BASE_URL}/api/users/unlinked", headers=_h(admin_tok), timeout=10)
    ids = {u["id"] for u in r.json()}
    assert uid not in ids, "user ainda aparece como unlinked após link"

    # 3) UNLINK
    r = requests.delete(
        f"{BASE_URL}/api/collaborators/{cid}/link-user",
        headers=_h(admin_tok),
        timeout=10,
    )
    assert r.status_code == 200, r.text
    assert r.json()["unlinked"] >= 1

    # 4) User voltou pra unlinked
    r = requests.get(f"{BASE_URL}/api/users/unlinked", headers=_h(admin_tok), timeout=10)
    ids = {u["id"] for u in r.json()}
    assert uid in ids, "user não voltou para lista unlinked"


def test_link_propagates_collaborator_profile(admin_tok):
    """Se o colaborador tem profile_id, ao linkar, o user herda."""
    # Pega perfil "colaborador" do tenant
    r = requests.get(f"{BASE_URL}/api/access-profiles", headers=_h(admin_tok), timeout=10)
    profiles = r.json()
    col_pid = next(p["id"] for p in profiles if p["key"] == "colaborador")
    col_profile = next(p for p in profiles if p["key"] == "colaborador")

    # Cria colaborador COM profile_id
    suffix = uuid.uuid4().hex[:6]
    r = requests.post(
        f"{BASE_URL}/api/collaborators",
        headers=_h(admin_tok),
        json={
            "name": f"Link Propag {suffix}",
            "cpf": f"{uuid.uuid4().int % 1000000000:09d}-99",
            "email": f"propag-{suffix}@example.com",
            "phone": "+5511999999990",
            "cargo": "tecnico",
            "profile_id": col_pid,
        },
        timeout=10,
    )
    assert r.status_code == 200
    cid = r.json()["id"]

    uid = _pick_unlinked_user(admin_tok)

    try:
        r = requests.post(
            f"{BASE_URL}/api/collaborators/{cid}/link-user/{uid}",
            headers=_h(admin_tok),
            timeout=10,
        )
        assert r.status_code == 200, r.text
        user = r.json()["user"]
        assert user["profile_id"] == col_pid, "profile_id não propagou"
        assert len(user.get("access_tags") or []) == len(col_profile["access_tags"]), \
            "access_tags não sincronizou"
    finally:
        requests.delete(f"{BASE_URL}/api/collaborators/{cid}/link-user",
                        headers=_h(admin_tok), timeout=10)
        requests.delete(f"{BASE_URL}/api/collaborators/{cid}",
                        headers=_h(admin_tok), timeout=10)


def test_link_blocks_duplicate(admin_tok, temp_colab):
    """Tentar linkar 2 users diferentes ao mesmo colaborador → 409."""
    cid = temp_colab["id"]
    uid1 = _pick_unlinked_user(admin_tok)

    r = requests.post(
        f"{BASE_URL}/api/collaborators/{cid}/link-user/{uid1}",
        headers=_h(admin_tok),
        timeout=10,
    )
    assert r.status_code == 200, r.text

    # Tenta linkar um segundo user → 409
    r2 = requests.get(f"{BASE_URL}/api/users/unlinked", headers=_h(admin_tok), timeout=10)
    other = next(
        (u for u in r2.json()
         if u["id"] != uid1 and u.get("active") is True
         and not u.get("is_super_admin")),
        None,
    )
    if other:
        r3 = requests.post(
            f"{BASE_URL}/api/collaborators/{cid}/link-user/{other['id']}",
            headers=_h(admin_tok),
            timeout=10,
        )
        assert r3.status_code == 409, f"esperado 409 em duplicate link, foi {r3.status_code}"

    # Cleanup link
    requests.delete(f"{BASE_URL}/api/collaborators/{cid}/link-user",
                    headers=_h(admin_tok), timeout=10)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
