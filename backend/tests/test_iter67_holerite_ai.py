"""Backend tests — Iteration 67: Holerite IA + public endpoints for collaborator app.

Covers:
- POST /api/holerites/ai-parse (PDF upload + Claude parsing + fuzzy match)
- Validation errors: non-PDF (400), oversize (413), bad threshold (400)
- POST /api/holerites/ai-import (creates payroll_documents)
- GET  /api/holerites/public/by-collaborator/{cid} (public, no JWT)
- GET  /api/holerites/public/{cid}/{doc_id}/file (public PDF stream)
"""
import io
import os
import pytest
import requests

def _load_base_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        # Fallback to frontend/.env when pytest runs without env var loaded
        env_path = "/app/frontend/.env"
        if os.path.exists(env_path):
            with open(env_path) as fh:
                for line in fh:
                    if line.strip().startswith("REACT_APP_BACKEND_URL="):
                        url = line.split("=", 1)[1].strip().strip('"')
                        break
    if not url:
        raise RuntimeError("REACT_APP_BACKEND_URL not configured")
    return url.rstrip("/")


BASE_URL = _load_base_url()
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASSWORD = "123456"
HOLERITE_PDF = "/tmp/holerite_teste.pdf"
TEST_COLLAB_ID = "col-30aafc3c"  # Diogo Henrique (per test_credentials)


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    if r.status_code != 200:
        pytest.skip(f"Admin login failed: {r.status_code} {r.text[:200]}")
    data = r.json()
    token = data.get("token") or data.get("access_token")
    if not token:
        pytest.skip("No token in admin login response")
    return token


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ----- /api/holerites/ai-parse ------------------------------------------------
class TestAiParse:
    def test_ai_parse_pdf_success(self, admin_headers):
        assert os.path.exists(HOLERITE_PDF), "Test PDF missing in /tmp"
        with open(HOLERITE_PDF, "rb") as f:
            files = {"file": ("holerite.pdf", f, "application/pdf")}
            data = {"threshold": "85"}
            r = requests.post(
                f"{BASE_URL}/api/holerites/ai-parse",
                files=files, data=data, headers=admin_headers, timeout=90,
            )
        assert r.status_code == 200, f"ai-parse failed: {r.status_code} {r.text[:300]}"
        body = r.json()
        assert body.get("ok") is True
        assert "parse_id" in body and body["parse_id"].startswith("hai-")
        assert "matches" in body and isinstance(body["matches"], list)
        assert len(body["matches"]) >= 1
        stats = body.get("stats", {})
        assert "parsed_count" in stats
        assert "matched_count" in stats
        assert stats["parsed_count"] >= 1
        # Stash parse_id for next test
        pytest.parse_id = body["parse_id"]
        pytest.first_match = body["matches"][0]

    def test_ai_parse_rejects_non_pdf(self, admin_headers):
        files = {"file": ("fake.txt", io.BytesIO(b"not a pdf"), "text/plain")}
        r = requests.post(
            f"{BASE_URL}/api/holerites/ai-parse",
            files=files, data={"threshold": "85"}, headers=admin_headers,
            timeout=30,
        )
        assert r.status_code == 400, (
            f"Expected 400 for non-PDF, got {r.status_code}: {r.text[:200]}"
        )

    def test_ai_parse_rejects_oversize(self, admin_headers):
        # 11MB of garbage (with PDF header so signature passes, size check fires first)
        payload = b"%PDF-1.4\n" + (b"X" * (11 * 1024 * 1024))
        files = {"file": ("big.pdf", io.BytesIO(payload), "application/pdf")}
        r = requests.post(
            f"{BASE_URL}/api/holerites/ai-parse",
            files=files, data={"threshold": "85"}, headers=admin_headers,
            timeout=60,
        )
        assert r.status_code == 413, (
            f"Expected 413 for >10MB, got {r.status_code}: {r.text[:200]}"
        )

    def test_ai_parse_rejects_bad_threshold(self, admin_headers):
        with open(HOLERITE_PDF, "rb") as f:
            files = {"file": ("holerite.pdf", f, "application/pdf")}
            r = requests.post(
                f"{BASE_URL}/api/holerites/ai-parse",
                files=files, data={"threshold": "30"},
                headers=admin_headers, timeout=60,
            )
        assert r.status_code == 400, (
            f"Expected 400 for threshold<50, got {r.status_code}: {r.text[:200]}"
        )


# ----- /api/holerites/ai-import -----------------------------------------------
class TestAiImport:
    def test_ai_import_with_skip_all(self, admin_headers):
        """Don't pollute DB: skip every item to verify response shape."""
        parse_id = getattr(pytest, "parse_id", None)
        if not parse_id:
            pytest.skip("ai-parse must succeed first")
        # First re-fetch to know how many matches we got
        first = getattr(pytest, "first_match", None)
        items = [
            {"parsed_index": 0, "employee_id": None, "skip": True},
            {"parsed_index": 1, "employee_id": None, "skip": True},
            {"parsed_index": 2, "employee_id": None, "skip": True},
        ]
        r = requests.post(
            f"{BASE_URL}/api/holerites/ai-import",
            json={
                "parse_id": parse_id,
                "competence_month": 12,
                "competence_year": 2025,
                "items": items,
            },
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, f"ai-import: {r.status_code} {r.text[:300]}"
        body = r.json()
        assert body.get("ok") is True
        assert body.get("imported") == 0
        assert body.get("skipped") >= 1
        _ = first  # unused but kept for context

    def test_ai_import_unknown_parse_id(self, admin_headers):
        r = requests.post(
            f"{BASE_URL}/api/holerites/ai-import",
            json={
                "parse_id": "hai-doesnotexist",
                "competence_month": 1,
                "competence_year": 2025,
                "items": [],
            },
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 404


# ----- Public collaborator endpoints (no JWT) ---------------------------------
class TestPublicCollabHolerites:
    def test_list_public_by_collaborator(self):
        r = requests.get(
            f"{BASE_URL}/api/holerites/public/by-collaborator/{TEST_COLLAB_ID}",
            timeout=15,
        )
        assert r.status_code == 200, f"public list: {r.status_code} {r.text[:200]}"
        body = r.json()
        assert "items" in body and isinstance(body["items"], list)
        assert "count" in body
        assert "collaborator" in body
        # Stash a doc_id (if any) for next test
        if body["items"]:
            pytest.collab_doc_id = body["items"][0]["id"]

    def test_list_public_unknown_collaborator(self):
        r = requests.get(
            f"{BASE_URL}/api/holerites/public/by-collaborator/col-zzzzz-unknown",
            timeout=15,
        )
        assert r.status_code == 404

    def test_public_file_stream(self):
        doc_id = getattr(pytest, "collab_doc_id", None)
        if not doc_id:
            pytest.skip("No payroll document exists for collaborator")
        r = requests.get(
            f"{BASE_URL}/api/holerites/public/{TEST_COLLAB_ID}/{doc_id}/file",
            timeout=30, stream=True,
        )
        assert r.status_code == 200, f"public file: {r.status_code} {r.text[:200]}"
        ct = r.headers.get("Content-Type", "")
        assert "pdf" in ct.lower(), f"Expected PDF, got Content-Type={ct}"
        chunk = r.raw.read(8)
        assert chunk.startswith(b"%PDF-"), f"Stream not PDF: {chunk!r}"

    def test_public_file_404_unknown_doc(self):
        r = requests.get(
            f"{BASE_URL}/api/holerites/public/{TEST_COLLAB_ID}/hol-zzzzz/file",
            timeout=15,
        )
        assert r.status_code == 404
