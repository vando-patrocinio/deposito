"""iter240 — Treasury: range de período (month_from/month_to) + DRE by period."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASSWORD = "123456"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("token") or data.get("access_token")
    assert tok, f"no token in response: {data}"
    return tok


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ───── kpis-by-month with range ─────────────────────────────────────────────
class TestKpisByMonthRange:
    def test_range_two_months(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/treasury/kpis-by-month",
            params={"month_from": "2026-05", "month_to": "2026-06"},
            headers=headers, timeout=20,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        period = data.get("period") or {}
        assert "gte" in period and "lt" in period
        assert period.get("month_from") == "2026-05"
        assert period.get("month_to") == "2026-06"
        # gte should start at 2026-05-01 and lt should be 2026-07-01 (exclusive)
        assert period["gte"].startswith("2026-05"), period
        assert period["lt"].startswith("2026-07"), period
        totals = data.get("totals") or {}
        for k in ("paid", "pending", "overdue", "blocked", "failed", "cancelled"):
            assert k in totals, f"missing totals.{k}"
            assert isinstance(totals[k], (int, float))
        counts = data.get("counts") or {}
        for k in ("paid", "pending", "sent", "total"):
            assert k in counts
            assert isinstance(counts[k], int)

    def test_single_month_compat(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/treasury/kpis-by-month",
            params={"month": "2026-06"},
            headers=headers, timeout=20,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("month") == "2026-06"
        period = data.get("period") or {}
        assert period["gte"].startswith("2026-06")
        assert period["lt"].startswith("2026-07")
        assert "totals" in data and "counts" in data

    def test_range_sum_matches_single_months(self, headers):
        """Sum of single-month totals.paid should equal range totals.paid."""
        r_may = requests.get(
            f"{BASE_URL}/api/treasury/kpis-by-month",
            params={"month": "2026-05"}, headers=headers, timeout=20,
        )
        r_jun = requests.get(
            f"{BASE_URL}/api/treasury/kpis-by-month",
            params={"month": "2026-06"}, headers=headers, timeout=20,
        )
        r_range = requests.get(
            f"{BASE_URL}/api/treasury/kpis-by-month",
            params={"month_from": "2026-05", "month_to": "2026-06"},
            headers=headers, timeout=20,
        )
        assert r_may.status_code == r_jun.status_code == r_range.status_code == 200
        paid_sum = r_may.json()["totals"]["paid"] + r_jun.json()["totals"]["paid"]
        paid_range = r_range.json()["totals"]["paid"]
        assert abs(paid_sum - paid_range) < 0.01, f"paid sum mismatch: {paid_sum} vs {paid_range}"


# ───── dre-by-period ────────────────────────────────────────────────────────
class TestDREByPeriod:
    def test_dre_single_month_range(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/treasury/dre-by-period",
            params={"month_from": "2026-06", "month_to": "2026-06"},
            headers=headers, timeout=20,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "period" in data
        assert "total_paid" in data
        assert "total_committed" in data
        assert isinstance(data["total_paid"], (int, float))
        assert isinstance(data["total_committed"], (int, float))
        for key in ("by_category", "by_payee", "by_method"):
            assert key in data, f"missing {key}"
            assert isinstance(data[key], list)
            for row in data[key]:
                assert "label" in row
                assert "amount" in row
                assert "count" in row
                assert "pct" in row

    def test_dre_total_paid_matches_kpis(self, headers):
        params = {"month_from": "2026-06", "month_to": "2026-06"}
        r_dre = requests.get(f"{BASE_URL}/api/treasury/dre-by-period",
                             params=params, headers=headers, timeout=20)
        r_kpi = requests.get(f"{BASE_URL}/api/treasury/kpis-by-month",
                             params=params, headers=headers, timeout=20)
        assert r_dre.status_code == 200 and r_kpi.status_code == 200
        dre_paid = r_dre.json()["total_paid"]
        kpi_paid = r_kpi.json()["totals"]["paid"]
        assert abs(dre_paid - kpi_paid) < 0.01, f"dre {dre_paid} vs kpi {kpi_paid}"

    def test_dre_pct_sums_per_group(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/treasury/dre-by-period",
            params={"month_from": "2026-06", "month_to": "2026-06"},
            headers=headers, timeout=20,
        )
        assert r.status_code == 200
        data = r.json()
        if data["total_paid"] <= 0:
            pytest.skip("no paid data in period")
        for group in ("by_category", "by_payee", "by_method"):
            rows = data.get(group, [])
            if not rows:
                continue
            total_pct = sum(row["pct"] for row in rows)
            # Allow tolerance, as group is limited to 12 entries
            assert 0 <= total_pct <= 100.5, f"{group} pct sum out of range: {total_pct}"

    def test_dre_no_params_defaults_to_current_month(self, headers):
        r = requests.get(f"{BASE_URL}/api/treasury/dre-by-period",
                         headers=headers, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "period" in data
        assert "total_paid" in data
        assert isinstance(data.get("by_category"), list)

    def test_dre_invalid_params(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/treasury/dre-by-period",
            params={"month_from": "lixo"}, headers=headers, timeout=20,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"

    def test_kpis_invalid_params(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/treasury/kpis-by-month",
            params={"month_from": "lixo"}, headers=headers, timeout=20,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
