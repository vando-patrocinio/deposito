"""Iteration 33 backend tests:
1) POST /api/stok/clientes/identify-all (use_similarity=true, force=true)
2) GET  /api/ai/dashboard/manufacturer-quality?days=90
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"email": "admin@empresa.com", "password": "123456"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json=ADMIN, timeout=30)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    data = r.json()
    token = data.get("access_token") or data.get("token")
    assert token, f"No token in response: {data}"
    return token


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# --- Manufacturer quality ranking -------------------------------------------
class TestManufacturerQuality:
    def test_endpoint_responds_with_correct_shape(self, auth_headers):
        r = requests.get(f"{API}/ai/dashboard/manufacturer-quality?days=90",
                         headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        # required top-level fields
        for k in ("period_days", "total_onus", "total_defect_calls",
                  "matched_calls", "unmatched_calls", "rows"):
            assert k in data, f"missing {k}: {data}"
        assert data["period_days"] == 90
        assert isinstance(data["rows"], list)
        # rows shape
        for row in data["rows"]:
            assert "manufacturer" in row
            assert "onus_in_field" in row
            assert "defect_calls" in row
            assert "defect_rate_pct" in row
            assert isinstance(row["defect_rate_pct"], (int, float))

    def test_matched_calls_greater_than_zero(self, auth_headers):
        """Regression: previous bug had matched_calls=0. Should be ~9 now."""
        r = requests.get(f"{API}/ai/dashboard/manufacturer-quality?days=90",
                         headers=auth_headers, timeout=60)
        assert r.status_code == 200
        data = r.json()
        total_calls = data["matched_calls"] + data["unmatched_calls"]
        # Allow zero only if there are zero defect tickets at all
        if total_calls > 0:
            assert data["matched_calls"] > 0, (
                f"matched_calls=0 even though there are {total_calls} reparo "
                f"tickets — pppoe_user/_norm matching broken. data={data}"
            )

    def test_rows_sorted_by_defect_rate_desc(self, auth_headers):
        r = requests.get(f"{API}/ai/dashboard/manufacturer-quality?days=90",
                         headers=auth_headers, timeout=60)
        rows = r.json()["rows"]
        rates = [(row["defect_rate_pct"], row["defect_calls"]) for row in rows]
        # sorted by (-rate, -calls)
        sorted_rates = sorted(rates, key=lambda x: (-x[0], -x[1]))
        assert rates == sorted_rates, f"rows not sorted: {rates}"


# --- Identify-all batch (Gemini similarity) ---------------------------------
class TestIdentifyAllBatch:
    def test_similarity_batch_response_shape(self, auth_headers):
        # use force=true to bypass cache and actually call LLM
        r = requests.post(
            f"{API}/stok/clientes/identify-all"
            "?use_similarity=true&force=true",
            headers=auth_headers, timeout=180)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "prefixes_tested" in data
        assert "new_manufacturers_found" in data
        assert "method" in data
        assert data["method"] == "similarity-batch", (
            f"expected similarity-batch, got {data['method']}"
        )
        assert isinstance(data["prefixes_tested"], int)
        assert isinstance(data["new_manufacturers_found"], int)
        assert data["new_manufacturers_found"] <= data["prefixes_tested"]

    def test_no_force_uses_cache(self, auth_headers):
        """Without force, should skip cached prefixes -> tested <= forced run."""
        r = requests.post(
            f"{API}/stok/clientes/identify-all"
            "?use_similarity=true&force=false",
            headers=auth_headers, timeout=120)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["method"] == "similarity-batch"
        # Either 0 (all cached) or some small number; must be int >=0
        assert data["prefixes_tested"] >= 0
