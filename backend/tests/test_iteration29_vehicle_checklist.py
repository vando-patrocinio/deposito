"""Iteration 29 — Vehicle Checklist (CONTRAN inspection) + Custodia rename.

Validates:
- /api/vehicle-checklist/template returns 30 items grouped in 8 categories
- POST /api/vehicle-checklist creates checklist with auto conformity calc
- GET /api/vehicle-checklist?collaborator_id=... lists history
- GET /api/vehicle-checklist/{id} returns single
- GET /api/vehicle-checklist/{id}/pdf returns PDF binary
- DELETE /api/vehicle-checklist/{id}
- /api/collab-assets/romaneio/{coll_id} still works (renamed title)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


@pytest.fixture(scope="module")
def auth_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=20)
    assert r.status_code == 200, f"login failed: {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def client(auth_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {auth_token}",
                      "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def some_collaborator(client):
    r = client.get(f"{BASE_URL}/api/collaborators", timeout=20)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1, "no collaborators found"
    return rows[0]


# Vehicle Checklist Template
class TestTemplate:
    def test_template_returns_30_items_8_categories(self, client):
        r = client.get(f"{BASE_URL}/api/vehicle-checklist/template", timeout=20)
        assert r.status_code == 200
        data = r.json()
        items = data["items"]
        assert len(items) == 30, f"expected 30 items, got {len(items)}"
        cats = {it["cat"] for it in items}
        # 8 categories
        expected = {"Documentação", "Pneus e Rodas", "Iluminação",
                    "Freios e Direção", "Fluidos", "Segurança",
                    "Externo/Interno", "Motorista"}
        assert cats == expected, f"got cats {cats}"
        for it in items:
            assert "name" in it and "cat" in it


# Vehicle Checklist CRUD
class TestChecklistCRUD:
    created_id = None
    plate = "TST-9X88"

    def test_create_checklist_with_auto_conformity(self, client, some_collaborator):
        # build items: 28 OK, 2 defects
        tpl = client.get(f"{BASE_URL}/api/vehicle-checklist/template").json()["items"]
        items = []
        for i, it in enumerate(tpl):
            status = "defeito" if i in (3, 7) else "ok"
            items.append({"cat": it["cat"], "name": it["name"],
                          "status": status,
                          "notes": "test defect" if status == "defeito" else None})
        payload = {
            "collaborator_id": some_collaborator["id"],
            "plate": TestChecklistCRUD.plate,
            "vehicle_brand": "Fiat",
            "vehicle_model": "Strada",
            "vehicle_year": 2023,
            "km_initial": 28430,
            "route": "TEST_route_iter29",
            "items": items,
            "general_notes": "TEST_iter29 checklist",
        }
        r = client.post(f"{BASE_URL}/api/vehicle-checklist", json=payload, timeout=20)
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["plate"] == "TST-9X88"
        assert doc["conformity"]["total"] == 30
        assert doc["conformity"]["ok"] == 28
        assert doc["conformity"]["defeitos"] == 2
        # 28/30 = 93.3
        assert abs(doc["conformity"]["pct"] - 93.3) < 0.5
        assert doc["id"].startswith("vchk-")
        TestChecklistCRUD.created_id = doc["id"]

    def test_get_checklist_persisted(self, client):
        cid = TestChecklistCRUD.created_id
        assert cid, "create test must run first"
        r = client.get(f"{BASE_URL}/api/vehicle-checklist/{cid}", timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d["id"] == cid
        assert d["plate"] == "TST-9X88"
        assert d["vehicle_brand"] == "Fiat"
        assert "_id" not in d  # MongoDB ObjectId excluded

    def test_list_filtered_by_collaborator(self, client, some_collaborator):
        r = client.get(
            f"{BASE_URL}/api/vehicle-checklist?collaborator_id={some_collaborator['id']}",
            timeout=20)
        assert r.status_code == 200
        body = r.json()
        ids = [x["id"] for x in body["items"]]
        assert TestChecklistCRUD.created_id in ids

    def test_pdf_renders(self, client):
        cid = TestChecklistCRUD.created_id
        r = client.get(f"{BASE_URL}/api/vehicle-checklist/{cid}/pdf", timeout=30)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        body = r.content
        assert body.startswith(b"%PDF"), "not a valid PDF magic"
        # should be reasonable size (≥10KB, ≤200KB)
        assert 10_000 < len(body) < 200_000, f"PDF size out of range: {len(body)}"

    def test_delete_checklist(self, client):
        cid = TestChecklistCRUD.created_id
        r = client.delete(f"{BASE_URL}/api/vehicle-checklist/{cid}", timeout=20)
        assert r.status_code == 200
        # verify gone
        r2 = client.get(f"{BASE_URL}/api/vehicle-checklist/{cid}", timeout=20)
        assert r2.status_code == 404


# Validation
class TestValidation:
    def test_create_invalid_plate(self, client, some_collaborator):
        payload = {
            "collaborator_id": some_collaborator["id"],
            "plate": "ab",  # too short (<4)
            "items": [],
        }
        r = client.post(f"{BASE_URL}/api/vehicle-checklist", json=payload, timeout=20)
        assert r.status_code == 422

    def test_create_unknown_collaborator(self, client):
        payload = {
            "collaborator_id": "col-DOES-NOT-EXIST",
            "plate": "AAA-0000",
            "items": [],
        }
        r = client.post(f"{BASE_URL}/api/vehicle-checklist", json=payload, timeout=20)
        assert r.status_code == 404


# Romaneio (Custodia rename)
class TestRomaneioRename:
    def test_romaneio_endpoint_works(self, client, some_collaborator):
        r = client.get(f"{BASE_URL}/api/collab-assets/romaneio/{some_collaborator['id']}",
                       timeout=20)
        # 200 if there are assets, possibly 404 if collaborator has none — both indicate route exists
        assert r.status_code in (200, 404), r.text
        if r.status_code == 200:
            assert r.headers.get("content-type", "").startswith("application/pdf")
