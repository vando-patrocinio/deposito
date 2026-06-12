"""
iter239 — Backend tests for Treasury Receipt Config (WhatsApp).
Covers GET/PUT/POST upload/DELETE/preview endpoints + auth.
"""
import os
import base64
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")

CREDS = {"email": "admin@empresa.com", "password": "123456"}

MIN_PDF_BYTES = (
    b"%PDF-1.4\n1 0 obj<<>>endobj\n"
    b"trailer<<>>\n%%EOF\n"
)


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=CREDS, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("token") or data.get("access_token")
    assert tok, f"no token in: {data}"
    return tok


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module", autouse=True)
def _clean(auth_headers):
    """Start from a clean slate: delete any existing pdf, and reset to defaults via update."""
    try:
        requests.delete(f"{BASE_URL}/api/treasury/config/receipt/pdf", headers=auth_headers, timeout=10)
    except Exception:
        pass
    yield


# ---------- AUTH ----------
def test_auth_required():
    r = requests.get(f"{BASE_URL}/api/treasury/config/receipt", timeout=10)
    assert r.status_code in (401, 403), f"unprotected! {r.status_code}"


# ---------- GET default ----------
def test_get_default_template(auth_headers):
    # First force-clear by removing the doc entirely
    # Use direct delete and put-revert is not feasible; we just check current state
    r = requests.get(f"{BASE_URL}/api/treasury/config/receipt", headers=auth_headers, timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "template_text" in data
    assert "signature" in data
    # Whether default or customized, the text/signature MUST be present
    assert isinstance(data["template_text"], str) and len(data["template_text"]) > 0
    # Best-effort: when no doc exists, is_default=True and contains SmartProv default
    if data.get("is_default"):
        assert "*COMPROVANTE DE PAGAMENTO*" in data["template_text"]
        assert "SmartProv" in data["signature"]
        assert data["has_pdf"] is False


# ---------- PUT customize ----------
def test_put_custom_template(auth_headers):
    payload = {
        "template_text": "PAGO PRA *{payee_name}* — {amount}\n{signature}",
        "signature": "LIGO Fibra",
        "attach_pdf": False,
    }
    r = requests.put(f"{BASE_URL}/api/treasury/config/receipt",
                     json=payload, headers=auth_headers, timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["template_text"] == payload["template_text"]
    assert data["signature"] == "LIGO Fibra"
    assert data["attach_pdf"] is False
    assert data["has_pdf"] is False
    # GET to verify persistence
    g = requests.get(f"{BASE_URL}/api/treasury/config/receipt", headers=auth_headers, timeout=10)
    assert g.status_code == 200
    gd = g.json()
    assert gd["template_text"] == payload["template_text"]
    assert gd["signature"] == "LIGO Fibra"
    assert gd.get("is_default") in (False, None)


# ---------- POST upload PDF ----------
def test_upload_pdf_ok(auth_headers):
    files = {"file": ("fake.pdf", MIN_PDF_BYTES, "application/pdf")}
    r = requests.post(f"{BASE_URL}/api/treasury/config/receipt/upload",
                      files=files, headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["size_bytes"] > 0
    assert data["attach_pdf"] is True
    # Verify via GET
    g = requests.get(f"{BASE_URL}/api/treasury/config/receipt", headers=auth_headers, timeout=10)
    gd = g.json()
    assert gd["has_pdf"] is True
    assert gd["pdf_filename"] == "fake.pdf"
    assert gd["pdf_mimetype"] == "application/pdf"
    assert gd["pdf_size_bytes"] > 0


def test_upload_invalid_type(auth_headers):
    files = {"file": ("evil.txt", b"hello world", "text/plain")}
    r = requests.post(f"{BASE_URL}/api/treasury/config/receipt/upload",
                      files=files, headers=auth_headers, timeout=20)
    assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"


# ---------- GET preview ----------
def test_preview_renders_placeholders(auth_headers):
    r = requests.get(f"{BASE_URL}/api/treasury/config/receipt/preview",
                     headers=auth_headers, timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "text" in data
    text = data["text"]
    # template was set: "PAGO PRA *{payee_name}* — {amount}\n{signature}"
    assert "ACME Fornecimentos" in text
    assert "1.850,00" in text
    assert "LIGO Fibra" in text
    # No raw placeholder leftovers (the ones used in our template)
    for ph in ("{payee_name}", "{amount}", "{signature}"):
        assert ph not in text
    # PDF was uploaded
    assert data.get("has_pdf") is True
    assert data.get("pdf_filename") == "fake.pdf"


# ---------- DELETE PDF ----------
def test_delete_pdf(auth_headers):
    r = requests.delete(f"{BASE_URL}/api/treasury/config/receipt/pdf",
                        headers=auth_headers, timeout=10)
    assert r.status_code == 200, r.text
    # Verify via GET
    g = requests.get(f"{BASE_URL}/api/treasury/config/receipt", headers=auth_headers, timeout=10)
    gd = g.json()
    assert gd["has_pdf"] is False
    assert gd["attach_pdf"] is False
