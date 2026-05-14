"""Iteration 64 — Validate removal of single-session-per-user check.

Tests:
1. Login admin returns 200 + access_token.
2. Two consecutive logins for the same user produce DIFFERENT tokens, both
   simultaneously valid against /api/auth/me and /api/aihub/agents.
3. Token A (older SID) keeps working even after Token B issued — should
   NOT respond 'Sessão substituída por novo login' anymore.
4. /api/auth/logout returns ok=True; afterwards the token still works
   (new behavior: logout just clears active_session_id but does not
   invalidate the JWT — JWT is valid until natural exp).
5. Expired JWT (forged with past exp) returns 401 'Sessão expirada'.
6. Garbage / payload-invalid token returns 401 'Token inválido'.
7. JWT with type != 'access' returns 401 'Tipo de token inválido'.
8. Brute force protection still works — 5 fails for same email = 429.
"""

import os
import time
import uuid
import jwt as pyjwt
import requests
import pytest
from datetime import datetime, timedelta, timezone

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@empresa.com", "password": "123456"}


# ---------- helpers ----------

def _login(email=ADMIN["email"], password=ADMIN["password"]):
    return requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)


def _me(token):
    return requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=20)


def _agents(token):
    return requests.get(f"{API}/aihub/agents", headers={"Authorization": f"Bearer {token}"}, timeout=20)


def _jwt_secret():
    # Mirror backend logic — read JWT_SECRET from backend/.env
    from dotenv import dotenv_values
    cfg = dotenv_values("/app/backend/.env")
    return cfg.get("JWT_SECRET") or os.environ.get("JWT_SECRET")


# ---------- 1. login basic ----------
class TestLoginBasic:
    def test_login_returns_200_with_token(self):
        r = _login()
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True
        assert isinstance(data.get("access_token"), str) and len(data["access_token"]) > 20
        assert data["user"]["email"] == ADMIN["email"]
        assert data["user"]["role"] in ("administrador", "gestor", "auditor")


# ---------- 2 & 3. two parallel sessions ----------
class TestNoSingleSessionInvalidation:
    def test_two_parallel_tokens_both_valid(self):
        r1 = _login()
        assert r1.status_code == 200, r1.text
        token_a = r1.json()["access_token"]

        # small pause to avoid identical iat/jti collisions if any
        time.sleep(1)

        r2 = _login()
        assert r2.status_code == 200, r2.text
        token_b = r2.json()["access_token"]

        assert token_a != token_b, "expected different tokens for two consecutive logins"

        # Both tokens must be accepted on /api/auth/me
        me_a = _me(token_a)
        me_b = _me(token_b)
        assert me_a.status_code == 200, f"Token A /auth/me failed: {me_a.status_code} {me_a.text}"
        assert me_b.status_code == 200, f"Token B /auth/me failed: {me_b.status_code} {me_b.text}"
        assert me_a.json()["email"] == ADMIN["email"]
        assert me_b.json()["email"] == ADMIN["email"]

        # Both must work on /api/aihub/agents
        ag_a = _agents(token_a)
        ag_b = _agents(token_b)
        assert ag_a.status_code == 200, f"Token A /aihub/agents failed: {ag_a.status_code} {ag_a.text}"
        assert ag_b.status_code == 200, f"Token B /aihub/agents failed: {ag_b.status_code} {ag_b.text}"

    def test_old_token_not_rejected_with_session_replaced_message(self):
        """Explicitly assert the deprecated error message no longer occurs."""
        token_a = _login().json()["access_token"]
        time.sleep(1)
        _ = _login().json()["access_token"]  # new login → new SID written
        r = _me(token_a)
        assert r.status_code == 200, (
            f"Old token must remain valid, got {r.status_code}: {r.text}"
        )
        body_lower = r.text.lower()
        assert "sessão substituída" not in body_lower
        assert "sessão encerrada" not in body_lower


# ---------- 4. logout does NOT invalidate token anymore ----------
class TestLogoutBehavior:
    def test_logout_ok_and_token_still_valid(self):
        token = _login().json()["access_token"]
        out = requests.post(f"{API}/auth/logout", headers={"Authorization": f"Bearer {token}"}, timeout=20)
        assert out.status_code == 200, out.text
        assert out.json().get("ok") is True

        # New behavior: same token should still authenticate (JWT is stateless
        # until exp). Single-session check was removed.
        after = _me(token)
        assert after.status_code == 200, (
            f"After logout, JWT should remain valid until exp. Got {after.status_code}: {after.text}"
        )


# ---------- 5. expired token ----------
class TestExpiredToken:
    def test_expired_jwt_rejected_with_session_expired(self):
        secret = _jwt_secret()
        if not secret:
            pytest.skip("JWT_SECRET not accessible from test env")
        payload = {
            "sub": "usr-fake",
            "email": ADMIN["email"],
            "role": "administrador",
            "company_id": "co-demo",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "type": "access",
            "sid": uuid.uuid4().hex,
        }
        token = pyjwt.encode(payload, secret, algorithm="HS256")
        r = _me(token)
        assert r.status_code == 401, r.text
        assert "expirada" in r.text.lower()


# ---------- 6. garbage token ----------
class TestInvalidToken:
    def test_garbage_token_returns_401(self):
        r = _me("not-a-valid-jwt-string")
        assert r.status_code == 401, r.text
        assert "inválido" in r.text.lower() or "invalid" in r.text.lower()


# ---------- 7. wrong type token ----------
class TestWrongTypeToken:
    def test_token_type_refresh_rejected(self):
        secret = _jwt_secret()
        if not secret:
            pytest.skip("JWT_SECRET not accessible")
        payload = {
            "sub": "usr-fake",
            "email": ADMIN["email"],
            "role": "administrador",
            "company_id": "co-demo",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "iat": datetime.now(timezone.utc),
            "type": "refresh",  # NOT access
            "sid": uuid.uuid4().hex,
        }
        token = pyjwt.encode(payload, secret, algorithm="HS256")
        r = _me(token)
        assert r.status_code == 401, r.text
        assert "tipo" in r.text.lower() or "type" in r.text.lower()


# ---------- 8. brute force lockout ----------
class TestBruteForceLockout:
    def test_5_fails_trigger_429_lockout(self):
        # Use a unique throwaway email to not pollute admin lockout counter
        bad_email = f"brute_{uuid.uuid4().hex[:8]}@example.com"
        # First, attempt 5 logins with wrong password against an existing
        # user (admin) — that's what triggers the per-identifier counter.
        # We use admin email but ensure we re-login at the end so lockout
        # clears.
        target_email = f"locktest_{uuid.uuid4().hex[:8]}@empresa.com"
        # The login_attempts collection is keyed by identifier (email) — even
        # unknown emails count, since record_login_attempt is called on every
        # failed lookup. So use a non-existent email to avoid locking admin.
        last_status = None
        last_body = None
        for i in range(6):
            r = requests.post(f"{API}/auth/login",
                              json={"email": target_email, "password": "wrong"},
                              timeout=20)
            last_status = r.status_code
            last_body = r.text
        # After 5+ fails, we expect 429
        assert last_status == 429, f"Expected 429 lockout, got {last_status} body={last_body}"
        assert "15" in last_body or "minut" in last_body.lower()
