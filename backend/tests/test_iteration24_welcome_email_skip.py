"""Iteration 24 — validates the 3 changes:
1) POST /api/saas/signup still works end-to-end (creates company, returns token)
2) Welcome email is fired in background and does NOT block signup when RESEND_API_KEY empty
3) Smoke regression: demo login, /api/saas/me, /api/collaborators tenant scoped
"""
import os
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback to frontend/.env if backend env var not set in test process
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.strip().split("=", 1)[1].strip().strip('"').rstrip("/")
                    break
    except Exception:
        pass

assert BASE_URL, "BASE_URL not set"


@pytest.fixture
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---- Welcome email / signup ------------------------------------------------
class TestWelcomeEmailSkip:
    def test_signup_completes_quickly_with_empty_resend_key(self, session):
        """Signup must not hang on background email send."""
        ts = int(time.time() * 1000)
        email = f"welcome+{ts}@example.com"
        payload = {
            "company_name": f"TEST_Welcome_{ts}",
            "admin_name": "Welcome Tester",
            "email": email,
            "password": "123456",
        }
        t0 = time.time()
        r = session.post(f"{BASE_URL}/api/saas/signup", json=payload, timeout=15)
        elapsed = time.time() - t0
        assert r.status_code == 200, f"signup failed: {r.status_code} {r.text}"
        # Signup should be quick — background task must not block
        assert elapsed < 8.0, f"signup blocked too long ({elapsed:.2f}s) — background task likely sync"
        data = r.json()
        assert data.get("ok") is True
        assert data.get("access_token")
        assert data["user"]["email"] == email
        assert data["company"]["name"] == payload["company_name"]
        assert data["company"]["status"] == "trialing"
        # token works end-to-end
        token = data["access_token"]
        me = session.get(
            f"{BASE_URL}/api/saas/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        assert me.status_code == 200, me.text
        me_data = me.json()
        assert me_data["id"] == data["company"]["id"]
        assert me_data["status_effective"] in ("trialing", "active")

    def test_duplicate_signup_rejected(self, session):
        ts = int(time.time() * 1000)
        email = f"welcome+dup{ts}@example.com"
        payload = {
            "company_name": f"TEST_WelcomeDup_{ts}",
            "admin_name": "Dup",
            "email": email,
            "password": "123456",
        }
        r1 = session.post(f"{BASE_URL}/api/saas/signup", json=payload, timeout=15)
        assert r1.status_code == 200
        r2 = session.post(f"{BASE_URL}/api/saas/signup", json=payload, timeout=15)
        assert r2.status_code == 400
        assert "cadastrado" in r2.text.lower()


# ---- Smoke regression ------------------------------------------------------
class TestSmokeRegression:
    def test_demo_admin_login(self, session):
        r = session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@example.com", "password": "admin123"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "access_token" in data
        token = data["access_token"]
        # /api/saas/me
        me = session.get(
            f"{BASE_URL}/api/saas/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        assert me.status_code == 200, me.text
        assert me.json().get("id")
        # /api/collaborators tenant-scoped (returns array)
        cols = session.get(
            f"{BASE_URL}/api/collaborators",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        assert cols.status_code == 200, cols.text
        assert isinstance(cols.json(), list)

    def test_collaborators_tenant_scope(self, session):
        """New tenant from signup should see 0 collaborators (its own scope)."""
        ts = int(time.time() * 1000)
        signup = session.post(
            f"{BASE_URL}/api/saas/signup",
            json={
                "company_name": f"TEST_TenantScope_{ts}",
                "admin_name": "Scope",
                "email": f"scope+{ts}@example.com",
                "password": "123456",
            },
            timeout=15,
        )
        assert signup.status_code == 200
        token = signup.json()["access_token"]
        cols = session.get(
            f"{BASE_URL}/api/collaborators",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        assert cols.status_code == 200
        assert cols.json() == [], "new tenant should have 0 collaborators"
