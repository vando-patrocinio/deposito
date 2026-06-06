"""Backend tests for Lousa TV public link + Rompimento (Claude IA) features.

Covers:
- /api/lousa/tv-link (auth) + rotate
- /api/lousa/public/tv-grid/{token} (no auth)
- /api/lousa/public/rompimento/parse-preview (Claude Sonnet 4.5 — slow, real)
- POST /api/lousa/tickets with type='rompimento'
- POST /api/lousa/public/tickets/{id}/rompimento-finalize
"""
import os
import re
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
    "https://dual-combine-3.preview.emergentagent.com"
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASSWORD = "123456"

session = requests.Session()
session.headers.update({"Content-Type": "application/json"})


@pytest.fixture(scope="module")
def admin_token():
    r = session.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no access_token in login response: {data}"
    return tok


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def tv_token(auth_headers):
    r = session.get(f"{BASE_URL}/api/lousa/tv-link", headers=auth_headers, timeout=20)
    assert r.status_code == 200, f"tv-link failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    assert "token" in data and "company_id" in data
    tok = data["token"]
    assert isinstance(tok, str) and len(tok) == 32 and re.fullmatch(r"[0-9a-f]{32}", tok), \
        f"token format invalid: {tok!r}"
    return tok


@pytest.fixture(scope="module")
def collaborator_id(auth_headers):
    """Get any active collaborator with a praca."""
    r = session.get(f"{BASE_URL}/api/collaborators", headers=auth_headers, timeout=20)
    if r.status_code != 200:
        # try alt
        r = session.get(f"{BASE_URL}/api/lousa/collaborators", headers=auth_headers, timeout=20)
    assert r.status_code == 200, f"collaborators list failed: {r.status_code}"
    items = r.json()
    if isinstance(items, dict):
        items = items.get("items") or items.get("collaborators") or []
    assert items, "no collaborators available"
    # Prefer one with praca
    for c in items:
        if c.get("praca_id") or c.get("warehouse_praca_id"):
            return c["id"]
    return items[0]["id"]


# ============================================================================
# 1) TV link endpoints
# ============================================================================
class TestLousaTvLink:
    def test_tv_link_get_returns_token(self, tv_token):
        # implicitly validated by fixture
        assert len(tv_token) == 32

    def test_tv_link_rotate_generates_new_token(self, auth_headers, tv_token):
        r = session.post(
            f"{BASE_URL}/api/lousa/tv-link/rotate",
            headers=auth_headers, timeout=20,
        )
        assert r.status_code == 200, f"rotate failed: {r.status_code} {r.text[:300]}"
        new_tok = r.json().get("token")
        assert new_tok and new_tok != tv_token, "rotated token must differ"
        assert re.fullmatch(r"[0-9a-f]{32}", new_tok), f"bad rotated token: {new_tok}"

        # Re-fetch GET to make tv_token fixture still consistent for following tests
        # (subsequent tests will fetch fresh token via /tv-link if needed)

    def test_public_tv_grid_no_auth_works(self):
        # Fetch a fresh token first via auth
        r = session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            timeout=20,
        )
        token_login = r.json().get("access_token") or r.json().get("token")
        hdrs = {"Authorization": f"Bearer {token_login}"}
        link = session.get(f"{BASE_URL}/api/lousa/tv-link", headers=hdrs, timeout=20).json()
        tok = link["token"]

        # NOTE: explicitly no Authorization header
        clean = requests.Session()
        r2 = clean.get(f"{BASE_URL}/api/lousa/public/tv-grid/{tok}", timeout=30)
        assert r2.status_code == 200, f"public grid failed: {r2.status_code} {r2.text[:300]}"
        data = r2.json()
        assert "columns" in data, f"no columns in payload keys={list(data.keys())}"
        assert "sla_map" in data, f"no sla_map in payload"
        assert "rompimento" in data["sla_map"], \
            f"sla_map missing 'rompimento' key: {list(data['sla_map'].keys())}"

    def test_public_tv_grid_invalid_token_404(self):
        clean = requests.Session()
        r = clean.get(f"{BASE_URL}/api/lousa/public/tv-grid/token_invalido_curto", timeout=15)
        assert r.status_code == 404, f"expected 404, got {r.status_code} {r.text[:200]}"


# ============================================================================
# 2) Rompimento Claude IA preview
# ============================================================================
class TestRompimentoParsePreview:
    def test_parse_preview_short_text_400(self):
        clean = requests.Session()
        r = clean.post(
            f"{BASE_URL}/api/lousa/public/rompimento/parse-preview",
            json={"report_text": "abc"}, timeout=15,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text[:200]}"

    def test_parse_preview_valid_text_returns_items(self):
        """Claude IA real - may take 5-15s."""
        clean = requests.Session()
        r = clean.post(
            f"{BASE_URL}/api/lousa/public/rompimento/parse-preview",
            json={"report_text": (
                "Atendi um rompimento de fibra na rua principal. "
                "Usei 50 metros de drop e troquei 2 conectores fast no poste."
            )},
            timeout=60,
        )
        assert r.status_code == 200, f"parse-preview failed: {r.status_code} {r.text[:500]}"
        data = r.json()
        assert "items" in data, f"no items key: {data}"
        items = data["items"]
        assert isinstance(items, list)
        # Claude may interpret loosely — require at least 1 valid item recognized
        assert len(items) >= 1, f"Claude returned no items: {data}"
        for it in items:
            assert "consumable_id" in it
            assert "quantity" in it
            assert isinstance(it["quantity"], (int, float))
            assert it["quantity"] > 0


# ============================================================================
# 3) Ticket rompimento creation
# ============================================================================
class TestRompimentoTicketCreation:
    def test_create_ticket_type_rompimento(self, auth_headers, collaborator_id):
        payload = {
            "client_name": "TEST_Cliente Rompimento",
            "address": "Rua de Teste, 100, Centro",
            "neighborhood": "Centro",
            "phone": "11999999999",
            "relato": "Cabo rompido na esquina",
            "type": "rompimento",
            "priority": "normal",
            "assigned_collaborator_id": collaborator_id,
        }
        r = session.post(
            f"{BASE_URL}/api/lousa/tickets", json=payload,
            headers=auth_headers, timeout=30,
        )
        assert r.status_code == 200, \
            f"create ticket failed: {r.status_code} {r.text[:500]}"
        data = r.json()
        assert data.get("type") == "rompimento", \
            f"type not persisted: {data.get('type')}"
        assert data.get("id"), "no id"
        pytest.ticket_id = data["id"]
        pytest.ticket_collab_id = collaborator_id

    def test_open_and_finalize_rompimento(self, auth_headers):
        ticket_id = getattr(pytest, "ticket_id", None)
        collab = getattr(pytest, "ticket_collab_id", None)
        if not ticket_id:
            pytest.skip("no ticket created")

        # Open via admin endpoint (bypasses ponto check)
        open_r = session.post(
            f"{BASE_URL}/api/lousa/tickets/{ticket_id}/admin-open",
            headers=auth_headers, timeout=20,
        )
        # Accept 200 or 400 if already open
        if open_r.status_code not in (200, 400):
            pytest.fail(f"open failed: {open_r.status_code} {open_r.text[:300]}")

        clean = requests.Session()
        clean.headers.update({"Content-Type": "application/json"})

        # Finalize via rompimento-finalize (real Claude call ~5-15s)
        fin = clean.post(
            f"{BASE_URL}/api/lousa/public/tickets/{ticket_id}/rompimento-finalize",
            json={
                "collaborator_id": collab,
                "report_text": (
                    "Rompimento de drop entre poste 12 e 14. "
                    "Usei 80 metros de drop e 2 conectores fast."
                ),
                "latitude": -23.5, "longitude": -46.6,
            },
            timeout=60,
        )
        assert fin.status_code == 200, \
            f"finalize failed: {fin.status_code} {fin.text[:500]}"
        data = fin.json()
        assert data.get("ok") is True
        assert "items" in data
        assert "summary" in data
        # Verify ticket is finalized via admin GET
        # (using auth_headers indirectly: re-login)
        login = session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=20).json()
        token = login.get("access_token") or login.get("token")
        hdrs = {"Authorization": f"Bearer {token}"}
        g = session.get(f"{BASE_URL}/api/lousa/tickets/{ticket_id}",
                        headers=hdrs, timeout=15)
        if g.status_code == 200:
            t = g.json()
            assert t.get("status") == "finalizada", \
                f"ticket not finalized: status={t.get('status')}"
