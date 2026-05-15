"""Iter 72 — Tests for unified Connections card and Financeiro Phase 2 CRUDs."""
from __future__ import annotations

import os

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback to frontend env (we read it in conftest typically)
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
               timeout=10)
    assert r.status_code == 200, f"Login falhou: {r.status_code} {r.text}"
    data = r.json()
    token = data.get("token") or data.get("access_token")
    if token:
        s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="module")
def gestor_session():
    """Create a 'gestor' user (role gestor, NOT in super_admin allowlist)."""
    s = requests.Session()
    # try to login a generic gestor; if none, register one
    # We'll create a unique test gestor via admin endpoint
    admin = requests.Session()
    r = admin.post(f"{BASE_URL}/api/auth/login",
                   json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=10)
    if r.status_code != 200:
        pytest.skip("Admin login failed; cannot create gestor")
    tok = (r.json().get("token") or r.json().get("access_token"))
    if tok:
        admin.headers.update({"Authorization": f"Bearer {tok}"})

    email = "TEST_gestor_iter72@empresa.com"
    payload = {"email": email, "password": "Test@1234",
               "name": "Gestor Iter72", "role": "gestor"}
    cr = admin.post(f"{BASE_URL}/api/users", json=payload, timeout=10)
    # 200/201 if created, ~409/400 if already exists
    if cr.status_code not in (200, 201, 400, 409):
        pytest.skip(f"Não foi possível criar gestor: {cr.status_code} {cr.text[:200]}")

    lr = s.post(f"{BASE_URL}/api/auth/login",
                json={"email": email, "password": "Test@1234"}, timeout=10)
    if lr.status_code != 200:
        pytest.skip(f"Gestor login falhou: {lr.status_code}")
    tok2 = (lr.json().get("token") or lr.json().get("access_token"))
    if tok2:
        s.headers.update({"Authorization": f"Bearer {tok2}"})
    return s


# ===========================================================================
# CONNECTIONS
# ===========================================================================
class TestConnections:
    def test_list_returns_8_integrations(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/connections/", timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "connections" in data
        ids = [c["id"] for c in data["connections"]]
        expected = {"atlaz", "smartolt", "twilio", "meta", "openrouter",
                    "resend", "stripe", "google_drive"}
        assert set(ids) == expected, f"Got: {ids}"
        # mascaramento: campos secret devem ter '*_set' boolean
        for conn in data["connections"]:
            secret_fields = [f for f in conn["fields"] if f.get("secret")]
            for sf in secret_fields:
                assert f"{sf['key']}_set" in conn["values"], \
                    f"{conn['id']}.{sf['key']}_set missing"

    def test_update_atlaz_empty_secret_keeps_current(self, admin_session):
        # 1) set a value
        r1 = admin_session.put(
            f"{BASE_URL}/api/connections/atlaz",
            json={"values": {"api_key": "TEST_atlaz_token_xyz_iter72",
                             "tenant_domain": "https://test72.atlaz.com.br"}},
            timeout=10)
        assert r1.status_code == 200, r1.text

        # 2) verify api_key_set=True
        rg = admin_session.get(f"{BASE_URL}/api/connections/", timeout=10)
        atlaz = next(c for c in rg.json()["connections"] if c["id"] == "atlaz")
        assert atlaz["values"]["api_key_set"] is True
        masked_before = atlaz["values"]["api_key"]

        # 3) send empty api_key + new tenant_domain
        r2 = admin_session.put(
            f"{BASE_URL}/api/connections/atlaz",
            json={"values": {"api_key": "",
                             "tenant_domain": "https://test72b.atlaz.com.br"}},
            timeout=10)
        assert r2.status_code == 200, r2.text

        # 4) verify api_key_set is still True (kept) and tenant_domain updated
        rg2 = admin_session.get(f"{BASE_URL}/api/connections/", timeout=10)
        atlaz2 = next(c for c in rg2.json()["connections"] if c["id"] == "atlaz")
        assert atlaz2["values"]["api_key_set"] is True
        assert atlaz2["values"]["api_key"] == masked_before
        assert atlaz2["values"]["tenant_domain"] == "https://test72b.atlaz.com.br"

    def test_update_openrouter_settings_prefix(self, admin_session):
        r = admin_session.put(
            f"{BASE_URL}/api/connections/openrouter",
            json={"values": {"api_key": "sk-or-v1-test72-iter",
                             "model": "deepseek/deepseek-v4-flash"}},
            timeout=10)
        assert r.status_code == 200, r.text
        rg = admin_session.get(f"{BASE_URL}/api/connections/", timeout=10)
        orouter = next(c for c in rg.json()["connections"] if c["id"] == "openrouter")
        assert orouter["values"]["api_key_set"] is True
        assert orouter["values"]["model"] == "deepseek/deepseek-v4-flash"

    def test_update_unknown_integration_returns_404(self, admin_session):
        r = admin_session.put(
            f"{BASE_URL}/api/connections/notexist",
            json={"values": {"api_key": "x"}}, timeout=10)
        assert r.status_code == 404


# ===========================================================================
# FINANCEIRO — SUMMARY
# ===========================================================================
class TestFinanceiroSummary:
    def test_summary_returns_counters(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/financeiro/summary", timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        for key in ("categories", "suppliers", "payment_methods",
                    "cash_accounts", "total_balance"):
            assert key in d
        assert isinstance(d["categories"], int)
        assert isinstance(d["total_balance"], (int, float))


# ===========================================================================
# FINANCEIRO — CATEGORIES
# ===========================================================================
class TestCategoryCRUD:
    created_id = None

    def test_create_category(self, admin_session):
        payload = {"name": "TEST_cat_iter72", "kind": "expense", "color": "#ff0000"}
        r = admin_session.post(f"{BASE_URL}/api/financeiro/categories",
                               json=payload, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == payload["name"]
        assert d["kind"] == "expense"
        assert "id" in d
        TestCategoryCRUD.created_id = d["id"]

    def test_list_categories_contains_created(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/financeiro/categories", timeout=10)
        assert r.status_code == 200
        ids = [c["id"] for c in r.json()]
        assert TestCategoryCRUD.created_id in ids

    def test_update_category(self, admin_session):
        cid = TestCategoryCRUD.created_id
        assert cid
        r = admin_session.put(f"{BASE_URL}/api/financeiro/categories/{cid}",
                              json={"name": "TEST_cat_iter72_upd",
                                    "kind": "income"}, timeout=10)
        assert r.status_code == 200, r.text
        # Verify via GET
        rg = admin_session.get(f"{BASE_URL}/api/financeiro/categories", timeout=10)
        cat = next(c for c in rg.json() if c["id"] == cid)
        assert cat["name"] == "TEST_cat_iter72_upd"
        assert cat["kind"] == "income"

    def test_create_category_invalid_kind_returns_422(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/financeiro/categories",
                               json={"name": "TEST_invalid", "kind": "xyz"},
                               timeout=10)
        assert r.status_code == 422

    def test_delete_category(self, admin_session):
        cid = TestCategoryCRUD.created_id
        r = admin_session.delete(f"{BASE_URL}/api/financeiro/categories/{cid}",
                                 timeout=10)
        assert r.status_code == 200
        # Verify gone
        rg = admin_session.get(f"{BASE_URL}/api/financeiro/categories", timeout=10)
        ids = [c["id"] for c in rg.json()]
        assert cid not in ids


# ===========================================================================
# FINANCEIRO — SUPPLIERS
# ===========================================================================
class TestSupplierCRUD:
    created_id = None

    def test_create_supplier(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/financeiro/suppliers",
                               json={"name": "TEST_sup_iter72",
                                     "document": "12.345.678/0001-90",
                                     "email": "test@sup.com"}, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == "TEST_sup_iter72"
        TestSupplierCRUD.created_id = d["id"]

    def test_update_supplier(self, admin_session):
        sid = TestSupplierCRUD.created_id
        r = admin_session.put(f"{BASE_URL}/api/financeiro/suppliers/{sid}",
                              json={"name": "TEST_sup_iter72_upd"}, timeout=10)
        assert r.status_code == 200
        rg = admin_session.get(f"{BASE_URL}/api/financeiro/suppliers", timeout=10)
        s = next(x for x in rg.json() if x["id"] == sid)
        assert s["name"] == "TEST_sup_iter72_upd"

    def test_delete_supplier(self, admin_session):
        sid = TestSupplierCRUD.created_id
        r = admin_session.delete(f"{BASE_URL}/api/financeiro/suppliers/{sid}",
                                 timeout=10)
        assert r.status_code == 200


# ===========================================================================
# FINANCEIRO — PAYMENT METHODS
# ===========================================================================
class TestPaymentMethodCRUD:
    created_id = None

    def test_create_pm(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/financeiro/payment-methods",
                               json={"name": "TEST_pm_iter72", "kind": "pix",
                                     "fee_percent": 1.5, "settle_days": 1},
                               timeout=10)
        assert r.status_code == 200, r.text
        TestPaymentMethodCRUD.created_id = r.json()["id"]

    def test_update_pm(self, admin_session):
        pid = TestPaymentMethodCRUD.created_id
        r = admin_session.put(f"{BASE_URL}/api/financeiro/payment-methods/{pid}",
                              json={"name": "TEST_pm_iter72_upd", "kind": "boleto",
                                    "fee_percent": 2.0, "settle_days": 2},
                              timeout=10)
        assert r.status_code == 200
        rg = admin_session.get(f"{BASE_URL}/api/financeiro/payment-methods", timeout=10)
        pm = next(x for x in rg.json() if x["id"] == pid)
        assert pm["kind"] == "boleto"

    def test_delete_pm(self, admin_session):
        pid = TestPaymentMethodCRUD.created_id
        r = admin_session.delete(f"{BASE_URL}/api/financeiro/payment-methods/{pid}",
                                 timeout=10)
        assert r.status_code == 200


# ===========================================================================
# FINANCEIRO — CASH ACCOUNTS
# ===========================================================================
class TestCashAccountCRUD:
    created_id = None

    def test_create_cash_account_with_opening_balance(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/financeiro/cash-accounts",
                               json={"name": "TEST_ca_iter72", "kind": "bank",
                                     "opening_balance": 1500.0,
                                     "current_balance": 0.0},
                               timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        # current_balance deve ter sido inicializado a partir do opening_balance
        assert d["current_balance"] == 1500.0, \
            f"Esperado current_balance=1500, recebido {d['current_balance']}"
        TestCashAccountCRUD.created_id = d["id"]

    def test_update_cash_account(self, admin_session):
        aid = TestCashAccountCRUD.created_id
        r = admin_session.put(f"{BASE_URL}/api/financeiro/cash-accounts/{aid}",
                              json={"name": "TEST_ca_iter72_upd", "kind": "bank",
                                    "opening_balance": 1500.0,
                                    "current_balance": 2000.0},
                              timeout=10)
        assert r.status_code == 200

    def test_delete_cash_account(self, admin_session):
        aid = TestCashAccountCRUD.created_id
        r = admin_session.delete(f"{BASE_URL}/api/financeiro/cash-accounts/{aid}",
                                 timeout=10)
        assert r.status_code == 200


# ===========================================================================
# RBAC — gestor (não super admin) deve receber 403 em endpoints financeiros
# ===========================================================================
class TestFinanceiroRBAC:
    def test_gestor_forbidden_summary(self, gestor_session):
        r = gestor_session.get(f"{BASE_URL}/api/financeiro/summary", timeout=10)
        assert r.status_code == 403, \
            f"Gestor deveria receber 403, recebeu {r.status_code}"

    def test_gestor_forbidden_categories(self, gestor_session):
        r = gestor_session.get(f"{BASE_URL}/api/financeiro/categories", timeout=10)
        assert r.status_code == 403
