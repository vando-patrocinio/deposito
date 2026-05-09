"""Tests for reset-face endpoint (iteration_4)."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def created_collab():
    """Cria um colaborador TEST_ para os testes (cleanup no final)."""
    suffix = uuid.uuid4().hex[:6]
    payload = {
        "name": f"TEST_ResetFace_{suffix}",
        "cpf": f"999.{suffix[:3]}.{suffix[3:6]}-00",
        "email": f"test_{suffix}@example.com",
        "phone": "+55 11 90000-0000",
        "role": "QA",
    }
    r = requests.post(f"{API}/collaborators", json=payload)
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    yield cid
    requests.delete(f"{API}/collaborators/{cid}")


# Reset face em colaborador existente
def test_reset_face_existing_returns_ok_and_message(created_collab):
    r = requests.post(f"{API}/collaborators/{created_collab}/reset-face")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert "message" in body and isinstance(body["message"], str) and len(body["message"]) > 0


# Após reset, GET deve mostrar avatar_data_url=None/null
def test_get_after_reset_avatar_is_null(created_collab):
    requests.post(f"{API}/collaborators/{created_collab}/reset-face")
    r = requests.get(f"{API}/collaborators/{created_collab}")
    assert r.status_code == 200
    data = r.json()
    assert data.get("avatar_data_url") in (None, ""), f"avatar_data_url esperado vazio, got={data.get('avatar_data_url')!r}"


# Reset em ID inexistente deve dar 404
def test_reset_face_unknown_id_returns_404():
    fake_id = f"col-doesnotexist-{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{API}/collaborators/{fake_id}/reset-face")
    assert r.status_code == 404
    body = r.json()
    assert "detail" in body or "message" in body


# Reset deve ser idempotente (chamar 2x não quebra)
def test_reset_face_idempotent(created_collab):
    r1 = requests.post(f"{API}/collaborators/{created_collab}/reset-face")
    r2 = requests.post(f"{API}/collaborators/{created_collab}/reset-face")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json().get("ok") is True


# Lista de colaboradores ainda funciona após reset
def test_list_collaborators_after_reset(created_collab):
    r = requests.get(f"{API}/collaborators")
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    found = next((c for c in items if c["id"] == created_collab), None)
    assert found is not None
    assert found.get("avatar_data_url") in (None, "")


# Reset no demo (col-demo-001) - se existir
def test_reset_face_demo_collaborator():
    r = requests.get(f"{API}/collaborators/col-demo-001")
    if r.status_code != 200:
        pytest.skip("col-demo-001 não existe")
    r2 = requests.post(f"{API}/collaborators/col-demo-001/reset-face")
    assert r2.status_code == 200
    assert r2.json().get("ok") is True
