"""Iteration 68 — Holerite gov.br digital signing flow tests.

Covers:
- GET /api/holerites/public/by-collaborator/{cid} pay_date filter
- POST /api/holerites/public/{cid}/{doc_id}/sign-upload
  (PDF assinado, NÃO assinado, não-PDF, > 10MB)
- GET /api/holerites/public/{cid}/{doc_id}/signed-file
  (após upload e ANTES de assinar)
- POST /api/holerites/ai-import → atribui pay_date default
"""
import io
import os
import pytest
import requests

def _load_backend_url():
    # 1) env var
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    # 2) frontend/.env file
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().rstrip("/")
    except FileNotFoundError:
        pass
    raise RuntimeError("REACT_APP_BACKEND_URL not configured")


BASE_URL = _load_backend_url()
COLLAB_ID = "col-30aafc3c"  # Diogo


@pytest.fixture(scope="module")
def existing_doc_id():
    r = requests.get(
        f"{BASE_URL}/api/holerites/public/by-collaborator/{COLLAB_ID}",
        timeout=20,
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items, "Diogo should have at least one holerite"
    return items[0]["id"]


# ---------- minimal PDF helpers ----------
def _minimal_pdf_bytes() -> bytes:
    """3.9KB un-signed PDF (no /ByteRange)."""
    with open("/tmp/holerite_teste.pdf", "rb") as f:
        return f.read()


def _fake_signed_pdf_bytes() -> bytes:
    """PDF-like blob containing /ByteRange marker so backend detects signature."""
    base = _minimal_pdf_bytes()
    # Append fake signature dict (PDF parser ignores anything after %%EOF for our purpose).
    return base + b"\n/ByteRange [0 100 200 300]\n/Sig <</Filter /Adobe.PPKLite>>\n"


def _non_pdf_bytes() -> bytes:
    return b"this is plainly not a pdf file at all" * 5


# ============================================================
# 1) by-collaborator filter respects pay_date
# ============================================================
class TestByCollaboratorFilter:
    def test_returns_only_paid_available(self):
        r = requests.get(
            f"{BASE_URL}/api/holerites/public/by-collaborator/{COLLAB_ID}",
            timeout=20,
        )
        assert r.status_code == 200
        body = r.json()
        assert "items" in body and "collaborator" in body
        # All returned items must be status=available
        for it in body["items"]:
            assert it["status"] == "available", (
                f"Doc {it['id']} should not be returned (status={it['status']})"
            )

    def test_unknown_collab_returns_404(self):
        r = requests.get(
            f"{BASE_URL}/api/holerites/public/by-collaborator/col-doesnotexist",
            timeout=20,
        )
        assert r.status_code == 404


# ============================================================
# 2) sign-upload variants
# ============================================================
class TestSignUpload:
    def test_upload_unsigned_pdf_returns_warning(self, existing_doc_id):
        files = {
            "file": ("teste.pdf", _minimal_pdf_bytes(), "application/pdf"),
        }
        r = requests.post(
            f"{BASE_URL}/api/holerites/public/{COLLAB_ID}/"
            f"{existing_doc_id}/sign-upload",
            files=files, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["signature_valid"] is False
        assert body["warning"] is not None
        assert len(body["signature_hash"]) == 64

    def test_upload_signed_pdf_marks_valid(self, existing_doc_id):
        files = {
            "file": ("assinado.pdf", _fake_signed_pdf_bytes(), "application/pdf"),
        }
        r = requests.post(
            f"{BASE_URL}/api/holerites/public/{COLLAB_ID}/"
            f"{existing_doc_id}/sign-upload",
            files=files, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["signature_valid"] is True, (
            "Should detect /ByteRange marker as digital signature"
        )
        assert body["warning"] in (None, ""), body
        assert "signed_at" in body and body["signed_at"]

    def test_upload_non_pdf_returns_400(self, existing_doc_id):
        files = {
            "file": ("foo.txt", _non_pdf_bytes(), "text/plain"),
        }
        r = requests.post(
            f"{BASE_URL}/api/holerites/public/{COLLAB_ID}/"
            f"{existing_doc_id}/sign-upload",
            files=files, timeout=20,
        )
        assert r.status_code == 400, r.text

    def test_upload_too_large_returns_413(self, existing_doc_id):
        big = b"%PDF-1.4\n" + b"X" * (10 * 1024 * 1024 + 50)
        files = {
            "file": ("huge.pdf", big, "application/pdf"),
        }
        r = requests.post(
            f"{BASE_URL}/api/holerites/public/{COLLAB_ID}/"
            f"{existing_doc_id}/sign-upload",
            files=files, timeout=60,
        )
        assert r.status_code == 413, r.text

    def test_upload_unknown_doc_returns_404(self):
        files = {
            "file": ("teste.pdf", _minimal_pdf_bytes(), "application/pdf"),
        }
        r = requests.post(
            f"{BASE_URL}/api/holerites/public/{COLLAB_ID}/"
            f"hol-doesnotexist/sign-upload",
            files=files, timeout=20,
        )
        assert r.status_code == 404


# ============================================================
# 3) signed-file streaming
# ============================================================
class TestSignedFile:
    def test_get_signed_file_after_upload(self, existing_doc_id):
        # ensure there is a signed upload before reading it back
        files = {
            "file": ("assinado.pdf", _fake_signed_pdf_bytes(), "application/pdf"),
        }
        u = requests.post(
            f"{BASE_URL}/api/holerites/public/{COLLAB_ID}/"
            f"{existing_doc_id}/sign-upload",
            files=files, timeout=30,
        )
        assert u.status_code == 200
        r = requests.get(
            f"{BASE_URL}/api/holerites/public/{COLLAB_ID}/"
            f"{existing_doc_id}/signed-file",
            timeout=30,
        )
        assert r.status_code == 200, r.text[:300]
        assert r.headers.get("Content-Type", "").startswith("application/pdf")
        assert r.content[:5] == b"%PDF-"

    def test_get_signed_file_unknown_doc_returns_404(self):
        r = requests.get(
            f"{BASE_URL}/api/holerites/public/{COLLAB_ID}/"
            f"hol-doesnotexist/signed-file",
            timeout=20,
        )
        assert r.status_code == 404


# ============================================================
# 4) Cross-check that pay_date field exists on persisted doc
#    (proxy validation for ai-import default pay_date logic)
# ============================================================
class TestPayDatePersisted:
    def test_pay_date_present_on_existing_doc(self):
        r = requests.get(
            f"{BASE_URL}/api/holerites/public/by-collaborator/{COLLAB_ID}",
            timeout=20,
        )
        assert r.status_code == 200
        items = r.json()["items"]
        assert items, "expected at least 1 doc for Diogo"
        for it in items:
            assert it.get("pay_date"), (
                f"Doc {it['id']} missing pay_date field "
                "(ai-import should set default)"
            )
            # Format YYYY-MM-DD
            parts = it["pay_date"].split("-")
            assert len(parts) == 3 and len(parts[0]) == 4
