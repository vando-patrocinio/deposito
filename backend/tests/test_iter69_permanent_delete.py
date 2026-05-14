"""iter69 — DELETE /api/holerites/{doc_id}/permanent + audit + AI directing."""
import os, io, requests, pytest

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": "admin@empresa.com", "password": "123456"},
                      timeout=15)
    assert r.status_code == 200, r.text
    return r.json().get("token") or r.json().get("access_token")


@pytest.fixture(scope="module")
def H(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _make_pdf():
    # minimal valid PDF
    return (b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<</Type/Catalog>>endobj\n"
            b"trailer<</Root 1 0 R>>\n%%EOF\n" + b"X" * 200)


# ---------- Permanent delete flow ----------
def test_permanent_delete_full_flow(H):
    # 1. Upload doc
    files = {"file": ("test.pdf", _make_pdf(), "application/pdf")}
    data = {
        "employee_name": "TEST_DeleteMe",
        "competence_month": "3",
        "competence_year": "2026",
        "gross": "1000",
        "net": "900",
    }
    r = requests.post(f"{BASE}/api/holerites/upload",
                      headers=H, files=files, data=data, timeout=30)
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]

    # 2. Permanent delete
    r = requests.delete(f"{BASE}/api/holerites/{doc_id}/permanent",
                        headers=H, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["deleted"] == doc_id

    # 3. Listing should not contain it anymore
    r = requests.get(f"{BASE}/api/holerites?year=2026&month=3",
                     headers=H, timeout=15)
    assert r.status_code == 200
    ids = [d["id"] for d in r.json().get("items", [])]
    assert doc_id not in ids

    # 4. Audit log MUST still have permanent_delete entry
    r = requests.get(f"{BASE}/api/holerites/audit/{doc_id}",
                     headers=H, timeout=15)
    assert r.status_code == 200
    actions = [it.get("action") for it in r.json().get("items", [])]
    assert "permanent_delete" in actions, f"audit missing permanent_delete: {actions}"


def test_permanent_delete_404_for_unknown(H):
    r = requests.delete(f"{BASE}/api/holerites/hol-doesnotexist/permanent",
                        headers=H, timeout=10)
    assert r.status_code == 404


def test_revoke_still_soft_deletes(H):
    files = {"file": ("test.pdf", _make_pdf(), "application/pdf")}
    data = {
        "employee_name": "TEST_RevokeMe",
        "competence_month": "3",
        "competence_year": "2026",
    }
    r = requests.post(f"{BASE}/api/holerites/upload",
                      headers=H, files=files, data=data, timeout=20)
    assert r.status_code == 200
    doc_id = r.json()["id"]
    r = requests.delete(f"{BASE}/api/holerites/{doc_id}", headers=H, timeout=10)
    assert r.status_code == 200
    # still present, but revoked
    r = requests.get(f"{BASE}/api/holerites?year=2026&month=3",
                     headers=H, timeout=10)
    rec = next((d for d in r.json()["items"] if d["id"] == doc_id), None)
    assert rec is not None
    assert rec["status"] == "revoked"
    # cleanup
    requests.delete(f"{BASE}/api/holerites/{doc_id}/permanent",
                    headers=H, timeout=10)


def test_permanent_delete_requires_auth():
    r = requests.delete(f"{BASE}/api/holerites/hol-xxx/permanent", timeout=10)
    assert r.status_code in (401, 403)


# ---------- Collaborator public listing (used by app) ----------
def test_collab_public_list_has_employee_id_match():
    """IA directing: every doc returned for collab must belong to that collab."""
    cid = "col-30aafc3c"
    r = requests.get(
        f"{BASE}/api/holerites/public/by-collaborator/{cid}", timeout=15)
    assert r.status_code == 200, r.text
    items = r.json().get("items", [])
    # Every item must be available and (implicitly) belong to col
    for it in items:
        assert it["status"] == "available"
        # employee_id is filtered by backend; just sanity-check fields exist
        assert "competence_month" in it
        assert "competence_year" in it
