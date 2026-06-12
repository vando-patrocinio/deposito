"""Regressão do vínculo colaborador ↔ perfil de acesso (RBAC).

Cobre:
1. Criar colaborador com profile_id válido.
2. Sync automático: atualizar profile_id no colaborador → User vinculado herda.
3. Herança passiva: criar User sem profile_id mas com collaborator_id que
   tem profile_id → User herda.
4. Guard Super Admin: gestor comum não pode atribuir profile=super_admin a
   colaborador (403).
5. Blindagem contra zero-out acidental: PUT sem mexer em profile_id mantém o
   valor anterior.
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


def _new_collab_payload(profile_id: str | None = None) -> dict:
    suffix = uuid.uuid4().hex[:6]
    payload = {
        "name": f"Test Colab {suffix}",
        "cpf": f"{uuid.uuid4().int % 1000000000:09d}-99",
        "email": f"test-colab-{suffix}@example.com",
        "phone": "+5511999999990",
        "cargo": "tecnico",
    }
    if profile_id:
        payload["profile_id"] = profile_id
    return payload


def test_create_collaborator_with_profile_id():
    tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    profiles = requests.get(f"{BASE_URL}/api/access-profiles", headers=_h(tok), timeout=10).json()
    col_pid = next(p["id"] for p in profiles if p["key"] == "colaborador")

    r = requests.post(
        f"{BASE_URL}/api/collaborators",
        headers=_h(tok),
        json=_new_collab_payload(profile_id=col_pid),
        timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile_id"] == col_pid
    cid = body["id"]

    # cleanup
    requests.delete(f"{BASE_URL}/api/collaborators/{cid}", headers=_h(tok), timeout=10)


def test_sync_profile_id_to_linked_user_on_update():
    tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    profiles = requests.get(f"{BASE_URL}/api/access-profiles", headers=_h(tok), timeout=10).json()
    gestao_pid = next(p["id"] for p in profiles if p["key"] == "gestao")

    # 1) cria colaborador sem profile
    payload = _new_collab_payload()
    r = requests.post(f"{BASE_URL}/api/collaborators", headers=_h(tok), json=payload, timeout=10)
    assert r.status_code == 200, r.text
    coll = r.json()
    col_id = coll["id"]

    # 2) cria user vinculado sem profile_id
    suffix = uuid.uuid4().hex[:6]
    r = requests.post(
        f"{BASE_URL}/api/users",
        headers=_h(tok),
        json={
            "name": f"Sync User {suffix}",
            "email": f"sync-user-{suffix}@example.com",
            "password": "abc12345",
            "role": "gestor",
            "collaborator_id": col_id,
        },
        timeout=10,
    )
    assert r.status_code == 200, r.text
    user_id = r.json()["id"]
    assert r.json().get("profile_id") is None

    try:
        # 3) PUT colaborador atribuindo gestao → user deve herdar
        update_payload = {**payload, "profile_id": gestao_pid}
        r = requests.put(
            f"{BASE_URL}/api/collaborators/{col_id}",
            headers=_h(tok),
            json=update_payload,
            timeout=10,
        )
        assert r.status_code == 200, r.text

        # Lista usuários e verifica sync
        users = requests.get(f"{BASE_URL}/api/users", headers=_h(tok), timeout=10).json()
        users_list = users if isinstance(users, list) else users.get("items") or users.get("users") or []
        target = next((u for u in users_list if u["id"] == user_id), None)
        assert target is not None, "user vinculado sumiu da lista"
        assert target["profile_id"] == gestao_pid, \
            f"user.profile_id={target['profile_id']} ≠ esperado {gestao_pid}"
        gestao_profile = next(p for p in profiles if p["key"] == "gestao")
        assert len(target.get("access_tags") or []) == len(gestao_profile["access_tags"]), \
            "tags do user não sincronizaram com tags do perfil gestao"
    finally:
        requests.delete(f"{BASE_URL}/api/users/{user_id}", headers=_h(tok), timeout=10)
        requests.delete(f"{BASE_URL}/api/collaborators/{col_id}", headers=_h(tok), timeout=10)


def test_user_inherits_profile_id_from_collaborator_on_create():
    tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    profiles = requests.get(f"{BASE_URL}/api/access-profiles", headers=_h(tok), timeout=10).json()
    col_pid = next(p["id"] for p in profiles if p["key"] == "colaborador")
    col_profile = next(p for p in profiles if p["key"] == "colaborador")

    # 1) cria colaborador COM profile_id
    r = requests.post(
        f"{BASE_URL}/api/collaborators",
        headers=_h(tok),
        json=_new_collab_payload(profile_id=col_pid),
        timeout=10,
    )
    assert r.status_code == 200, r.text
    col_id = r.json()["id"]

    # 2) cria user SEM profile_id no payload → herda
    suffix = uuid.uuid4().hex[:6]
    r = requests.post(
        f"{BASE_URL}/api/users",
        headers=_h(tok),
        json={
            "name": f"Heritage User {suffix}",
            "email": f"heritage-{suffix}@example.com",
            "password": "abc12345",
            "role": "gestor",
            "collaborator_id": col_id,
        },
        timeout=10,
    )
    assert r.status_code == 200, r.text
    user = r.json()
    assert user["profile_id"] == col_pid, \
        f"User não herdou profile_id do colaborador: {user.get('profile_id')}"
    assert len(user.get("access_tags") or []) == len(col_profile["access_tags"])

    # cleanup
    requests.delete(f"{BASE_URL}/api/users/{user['id']}", headers=_h(tok), timeout=10)
    requests.delete(f"{BASE_URL}/api/collaborators/{col_id}", headers=_h(tok), timeout=10)


def test_guard_super_admin_profile_on_collaborator_assignment():
    """Gestor comum não pode atribuir o perfil Super Admin a um colaborador."""
    # Login como gestor (não-super)
    try:
        gestor_tok = _login("manusanttos395@gmail.com", "Ligo@Gestor2026!")
    except Exception:
        pytest.skip("gestor comum não disponível em test_credentials")

    admin_tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    profiles = requests.get(f"{BASE_URL}/api/access-profiles", headers=_h(admin_tok), timeout=10).json()
    super_pid = next(p["id"] for p in profiles if p["key"] == "super_admin")

    r = requests.post(
        f"{BASE_URL}/api/collaborators",
        headers=_h(gestor_tok),
        json=_new_collab_payload(profile_id=super_pid),
        timeout=10,
    )
    assert r.status_code == 403, \
        f"esperado 403 para gestor atribuindo Super Admin, foi {r.status_code}: {r.text}"
    assert "Super Admin" in r.json().get("detail", "")


def test_partial_update_preserves_profile_id():
    """PUT sem campo profile_id no payload (toggleClockInEnabled etc.) deve
    PRESERVAR o profile_id existente, não zerar."""
    tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    profiles = requests.get(f"{BASE_URL}/api/access-profiles", headers=_h(tok), timeout=10).json()
    col_pid = next(p["id"] for p in profiles if p["key"] == "colaborador")

    # cria colaborador com profile_id
    payload = _new_collab_payload(profile_id=col_pid)
    r = requests.post(f"{BASE_URL}/api/collaborators", headers=_h(tok), json=payload, timeout=10)
    assert r.status_code == 200, r.text
    col_id = r.json()["id"]

    try:
        # PUT enviando payload SEM profile_id (simulando toggleClockInEnabled)
        update_payload = {k: v for k, v in payload.items() if k != "profile_id"}
        update_payload["clock_in_enabled"] = False  # mudou outra coisa
        r = requests.put(
            f"{BASE_URL}/api/collaborators/{col_id}",
            headers=_h(tok),
            json=update_payload,
            timeout=10,
        )
        assert r.status_code == 200, r.text

        # GET o colab e confirma profile_id PRESERVADO
        r = requests.get(f"{BASE_URL}/api/collaborators/{col_id}", headers=_h(tok), timeout=10)
        assert r.status_code == 200
        assert r.json()["profile_id"] == col_pid, \
            "PUT parcial zerou profile_id (blindagem falhou!)"

        # Agora testa REMOÇÃO EXPLÍCITA via string vazia ""
        update_payload["profile_id"] = ""
        r = requests.put(
            f"{BASE_URL}/api/collaborators/{col_id}",
            headers=_h(tok),
            json=update_payload,
            timeout=10,
        )
        assert r.status_code == 200, r.text
        r = requests.get(f"{BASE_URL}/api/collaborators/{col_id}", headers=_h(tok), timeout=10)
        assert r.json()["profile_id"] is None, \
            "PUT explícito com '' deveria zerar profile_id"
    finally:
        requests.delete(f"{BASE_URL}/api/collaborators/{col_id}", headers=_h(tok), timeout=10)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
