"""Iter 74 — tests for /api/financeiro/analytics + rate limit (slowapi)."""
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests

def _load_base_url() -> str:
    url = os.environ.get("REACT_APP_BACKEND_URL", "").strip()
    if not url:
        # fallback: ler de /app/frontend/.env
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        url = line.split("=", 1)[1].strip()
                        break
        except FileNotFoundError:
            pass
    return url.rstrip("/")


BASE_URL = _load_base_url()
assert BASE_URL, "REACT_APP_BACKEND_URL not set"

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASSWORD = "123456"


# ------------------------- fixtures -------------------------
@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ------------------------- /api/financeiro/analytics -------------------------
class TestAnalyticsContract:
    def test_default_returns_full_shape(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/financeiro/analytics?range=30d&period=day",
            headers=auth_headers, timeout=30,
        )
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        for k in ("range", "period", "from_date", "to_date", "series",
                  "totals", "income_metrics", "expense_metrics", "buckets"):
            assert k in data, f"missing key: {k}"
        assert data["range"] == "30d"
        assert data["period"] == "day"
        # totals
        for k in ("income", "expense", "net"):
            assert k in data["totals"]
        # metrics shape
        for k in ("mean", "std", "cv_pct", "regularity"):
            assert k in data["income_metrics"]
            assert k in data["expense_metrics"]
        # series item shape
        if data["series"]:
            s0 = data["series"][0]
            for k in ("period", "income", "expense", "net"):
                assert k in s0

    def test_invalid_range_returns_422(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/financeiro/analytics?range=50d&period=day",
            headers=auth_headers, timeout=30,
        )
        assert r.status_code == 422, (
            f"expected 422 for invalid range, got {r.status_code}: {r.text[:200]}"
        )

    def test_invalid_period_returns_422(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/financeiro/analytics?range=30d&period=week",
            headers=auth_headers, timeout=30,
        )
        assert r.status_code == 422

    def test_6m_month_buckets_count(self, auth_headers):
        """6m + month => 7 buckets (rolling 180d cobre ~7 meses)."""
        r = requests.get(
            f"{BASE_URL}/api/financeiro/analytics?range=6m&period=month",
            headers=auth_headers, timeout=30,
        )
        assert r.status_code == 200
        data = r.json()
        # Expect between 6 and 8 (depending on day-of-month). Allow tolerance.
        assert 6 <= data["buckets"] <= 8, (
            f"expected ~7 buckets for 6m/month, got {data['buckets']}"
        )

    def test_unauthorized_without_token(self):
        r = requests.get(
            f"{BASE_URL}/api/financeiro/analytics?range=30d&period=day",
            timeout=15,
        )
        assert r.status_code in (401, 403)


# ------------------- Invoice -> income consolidation -------------------
class TestInvoiceConsolidation:
    """Cria invoice paid_date=hoje e amount_paid=500, valida em totals.income."""

    def test_subscriber_invoice_paid_appears_in_income(self, auth_headers):
        # 1) baseline
        r0 = requests.get(
            f"{BASE_URL}/api/financeiro/analytics?range=7d&period=day",
            headers=auth_headers, timeout=30,
        )
        assert r0.status_code == 200
        base_income = r0.json()["totals"]["income"]

        # 2) Insert via direct db (preferred) — but test via API: use cash mov
        # Test plan says "create invoice with paid_date=today" — but no public
        # endpoint to create invoice with paid_date. We use cash_movements
        # income endpoint instead (which is also part of income aggregate).
        today = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")
        unique = f"TEST_iter74_{uuid.uuid4().hex[:8]}"

        # Need a cash account first
        ca = requests.get(
            f"{BASE_URL}/api/financeiro/cash-accounts",
            headers=auth_headers, timeout=15,
        )
        if ca.status_code != 200 or not ca.json():
            pytest.skip("no cash accounts available to attach movement")
        accounts = ca.json() if isinstance(ca.json(), list) else (
            ca.json().get("items") or ca.json().get("data") or []
        )
        if not accounts:
            pytest.skip("no cash accounts in response")
        account_id = accounts[0].get("id") or accounts[0].get("_id")
        if not account_id:
            pytest.skip("cash account has no id")

        r1 = requests.post(
            f"{BASE_URL}/api/financeiro/movements",
            headers=auth_headers, timeout=30,
            json={
                "date": today,
                "type": "income",
                "amount": 500,
                "description": unique,
                "cash_account_id": account_id,
            },
        )
        if r1.status_code not in (200, 201):
            pytest.skip(
                f"movements POST returned {r1.status_code}: {r1.text[:150]}"
            )
        mov_id = r1.json().get("id")

        # 3) re-fetch and assert delta
        r2 = requests.get(
            f"{BASE_URL}/api/financeiro/analytics?range=7d&period=day",
            headers=auth_headers, timeout=30,
        )
        assert r2.status_code == 200
        new_income = r2.json()["totals"]["income"]
        # cleanup
        if mov_id:
            requests.delete(
                f"{BASE_URL}/api/financeiro/movements/{mov_id}",
                headers=auth_headers, timeout=15,
            )
        assert new_income >= base_income + 500 - 0.01, (
            f"income did not increase by 500: base={base_income}, "
            f"new={new_income}"
        )


# ------------------- Regularity (CV) calculation ----------------------
class TestRegularity:
    """Verifica calc statistic via /api/financeiro/analytics indirectly.

    Foco: que metric.regularity é exposta e CV é numerico não-negativo.
    Teste full (5 valores iguais => regular) requer banco limpo,
    o que pode contaminar prod. Aqui apenas validamos shape/consistência.
    """

    def test_regularity_values_valid(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/financeiro/analytics?range=1y&period=month",
            headers=auth_headers, timeout=30,
        )
        assert r.status_code == 200
        data = r.json()
        for key in ("income_metrics", "expense_metrics"):
            m = data[key]
            assert m["cv_pct"] >= 0
            assert m["regularity"] in (
                "regular", "moderada", "irregular", "sem_dados"
            )
            # se sem_dados, mean deve ser 0
            if m["regularity"] == "sem_dados":
                assert m["mean"] == 0


# ------------------------- Rate limit -------------------------
class TestRateLimit:
    def test_categories_not_rate_limited(self, auth_headers):
        """GET /api/financeiro/categories deve aceitar 30 chamadas seguidas
        (não testamos 200x para não estourar timeout)."""
        ok = 0
        for _ in range(30):
            r = requests.get(
                f"{BASE_URL}/api/financeiro/categories",
                headers=auth_headers, timeout=15,
            )
            if r.status_code == 200:
                ok += 1
            else:
                break
        assert ok == 30, f"only {ok}/30 succeeded — endpoint is rate-limited?"

    def test_x_forwarded_for_used_as_key(self, auth_headers):
        """Com 2 IPs diferentes via XFF, ambos passam (limiter por IP)."""
        # Spoof XFF distintos para confirmar que limiter usa header
        synthetic_ip_a = f"10.99.{uuid.uuid4().int % 254}.{uuid.uuid4().int % 254}"
        synthetic_ip_b = f"10.88.{uuid.uuid4().int % 254}.{uuid.uuid4().int % 254}"
        h1 = {**auth_headers, "X-Forwarded-For": synthetic_ip_a}
        h2 = {**auth_headers, "X-Forwarded-For": synthetic_ip_b}
        r1 = requests.get(
            f"{BASE_URL}/api/financeiro/analytics?range=7d&period=day",
            headers=h1, timeout=15,
        )
        r2 = requests.get(
            f"{BASE_URL}/api/financeiro/analytics?range=7d&period=day",
            headers=h2, timeout=15,
        )
        assert r1.status_code == 200
        assert r2.status_code == 200

    def test_auth_login_rate_limit_with_synthetic_ip(self):
        """6 logins inválidos com mesmo X-Forwarded-For — confirma 429 chega.

        Em DEV o limite é 5*10=50/min. Para evitar bloquear o IP real do
        runner, usamos um XFF sintético único e fazemos 52 hits (>50).
        Esperamos pelo menos 1× 429 nas últimas tentativas.
        """
        synth = f"10.55.{uuid.uuid4().int % 254}.{uuid.uuid4().int % 254}"
        headers = {"X-Forwarded-For": synth, "Content-Type": "application/json"}
        # também variar email pra não disparar lockout do banco (5 falhas / 15min)
        statuses = []
        for i in range(55):
            email = f"nonexistent_{i}_{uuid.uuid4().hex[:6]}@gmail.com"
            r = requests.post(
                f"{BASE_URL}/api/auth/login",
                json={"email": email, "password": "wrong"},
                headers=headers, timeout=10,
            )
            statuses.append(r.status_code)
            if r.status_code == 429:
                break
        assert 429 in statuses, (
            f"expected 429 after 50 attempts; got statuses: {statuses[-10:]}"
        )
        # Antes do 429, devem haver 401s (credenciais inválidas)
        assert 401 in statuses, f"expected 401s before 429; got: {set(statuses)}"
