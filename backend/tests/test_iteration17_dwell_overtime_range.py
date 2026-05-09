"""Tests for iteration 17 - new endpoints:
- GET /api/locations/dwell-analysis (geofence/dwell + AI evaluation)
- GET /api/dashboard/overtime/range (monthly/accumulated ranges)
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://selfie-attendance-7.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------------- dwell-analysis ----------------
class TestDwellAnalysis:
    def test_dwell_no_ai_contract(self, api_client):
        r = api_client.get(f"{API}/locations/dwell-analysis", params={"use_ai": "false"}, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        # top-level keys
        for k in ["generated_at", "hours", "radius_m", "stationary_threshold_min",
                  "use_ai", "items", "alerts"]:
            assert k in data, f"missing key {k}"
        assert data["use_ai"] is False
        assert isinstance(data["items"], list)
        assert isinstance(data["alerts"], list)
        assert data["stationary_threshold_min"] == 30  # default
        # per-item contract (if any)
        for it in data["items"]:
            for k in ["collaborator_id", "name", "current_dwell_min",
                      "out_of_fence", "nearest_fence_distance_m", "stays",
                      "current_location", "has_fences", "ai_evaluation"]:
                assert k in it, f"item missing key {k}"
            assert isinstance(it["out_of_fence"], bool)
            assert isinstance(it["stays"], list)
            # no AI requested
            assert it["ai_evaluation"] is None
            # current_location structure
            cl = it["current_location"]
            assert "lat" in cl and "lng" in cl and "recorded_at" in cl

    def test_dwell_respects_min_dur_min(self, api_client):
        # Different thresholds may change number of alerts/stays
        r30 = api_client.get(f"{API}/locations/dwell-analysis",
                             params={"use_ai": "false", "min_dur_min": 30}, timeout=20)
        r60 = api_client.get(f"{API}/locations/dwell-analysis",
                             params={"use_ai": "false", "min_dur_min": 60}, timeout=20)
        assert r30.status_code == 200 and r60.status_code == 200
        d30 = r30.json()
        d60 = r60.json()
        assert d30["stationary_threshold_min"] == 30
        assert d60["stationary_threshold_min"] == 60

        # With higher threshold, alerts count <= with lower threshold (monotonic)
        # count only dwell alerts (fence alerts are independent of threshold)
        dwell_alerts_30 = [a for a in d30["alerts"] if a["id"].startswith("dwell:")]
        dwell_alerts_60 = [a for a in d60["alerts"] if a["id"].startswith("dwell:")]
        assert len(dwell_alerts_60) <= len(dwell_alerts_30), \
            f"higher threshold should reduce dwell alerts: 30={len(dwell_alerts_30)} 60={len(dwell_alerts_60)}"

        # similarly per-item stays (alert stays only) should be monotonic
        stays60_by_cid = {i["collaborator_id"]: len(i["stays"]) for i in d60["items"]}
        for it in d30["items"]:
            cid = it["collaborator_id"]
            s30 = len(it["stays"])
            s60 = stays60_by_cid.get(cid, 0)
            assert s60 <= s30, f"cid {cid} stays monotonicity broken s30={s30} s60={s60}"

    def test_dwell_min_dur_min_clamping(self, api_client):
        # min_dur_min is clamped to [5, 240]
        r_low = api_client.get(f"{API}/locations/dwell-analysis",
                               params={"use_ai": "false", "min_dur_min": 1}, timeout=20)
        assert r_low.status_code == 200
        assert r_low.json()["stationary_threshold_min"] == 5

        r_high = api_client.get(f"{API}/locations/dwell-analysis",
                                params={"use_ai": "false", "min_dur_min": 999}, timeout=20)
        assert r_high.status_code == 200
        assert r_high.json()["stationary_threshold_min"] == 240

    def test_dwell_alerts_structure(self, api_client):
        r = api_client.get(f"{API}/locations/dwell-analysis",
                           params={"use_ai": "false", "min_dur_min": 30}, timeout=20)
        assert r.status_code == 200
        data = r.json()
        for a in data["alerts"]:
            for k in ["id", "level", "collaborator_id", "title", "message"]:
                assert k in a, f"alert missing {k}"
            assert a["level"] in ("warning", "danger")
            assert a["id"].startswith(("dwell:", "fence:"))

    def test_dwell_use_ai_true_does_not_break(self, api_client):
        # With use_ai=true, if no LLM key/backend it should still return 200
        # and ai_evaluation may be null. Allow generous timeout.
        t0 = time.time()
        r = api_client.get(f"{API}/locations/dwell-analysis",
                           params={"use_ai": "true", "min_dur_min": 30}, timeout=60)
        dt = time.time() - t0
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["use_ai"] is True
        # structure maintained
        assert isinstance(data["items"], list)
        # For flagged items, ai_evaluation may be dict OR null (if LLM failed/not configured)
        for it in data["items"]:
            flagged = it["current_dwell_min"] >= data["stationary_threshold_min"] or it["out_of_fence"]
            if it["ai_evaluation"] is not None:
                ev = it["ai_evaluation"]
                for k in ["risk", "summary", "suggested_action"]:
                    assert k in ev, f"ai_evaluation missing {k}"
                assert ev["risk"] in ("baixo", "medio", "alto")
            else:
                # null allowed for non-flagged or when LLM failed
                assert it["ai_evaluation"] is None
        print(f"[info] dwell use_ai=true took {dt:.2f}s flagged="
              f"{sum(1 for i in data['items'] if i['current_dwell_min']>=data['stationary_threshold_min'] or i['out_of_fence'])}")


# ---------------- overtime range ----------------
class TestOvertimeRange:
    def test_monthly_basic(self, api_client):
        r = api_client.get(f"{API}/dashboard/overtime/range",
                           params={"year_from": 2025, "month_from": 1,
                                   "year_to": 2025, "month_to": 3,
                                   "mode": "monthly"}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ["mode", "year_from", "month_from", "year_to", "month_to",
                  "series", "top_debit"]:
            assert k in data, f"missing {k}"
        assert data["mode"] == "monthly"
        assert len(data["series"]) == 3  # jan, feb, mar
        labels = [s["label"] for s in data["series"]]
        assert labels == ["01/2025", "02/2025", "03/2025"]
        for s in data["series"]:
            for k in ["year", "month", "label", "total_overtime_min",
                      "total_paid_brl", "projected_overtime_min",
                      "projected_paid_brl", "is_current"]:
                assert k in s

    def test_accumulated_mode(self, api_client):
        r = api_client.get(f"{API}/dashboard/overtime/range",
                           params={"year_from": 2025, "month_from": 1,
                                   "year_to": 2025, "month_to": 6,
                                   "mode": "accumulated"}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data["mode"] == "accumulated"
        assert len(data["series"]) == 6

    def test_range_normalization_inverted(self, api_client):
        # yf/mf > yt/mt -> should swap and still return valid series
        r = api_client.get(f"{API}/dashboard/overtime/range",
                           params={"year_from": 2025, "month_from": 6,
                                   "year_to": 2025, "month_to": 3,
                                   "mode": "monthly"}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data["year_from"] == 2025 and data["month_from"] == 3
        assert data["year_to"] == 2025 and data["month_to"] == 6
        assert len(data["series"]) == 4

    def test_range_single_month(self, api_client):
        r = api_client.get(f"{API}/dashboard/overtime/range",
                           params={"year_from": 2025, "month_from": 5,
                                   "year_to": 2025, "month_to": 5,
                                   "mode": "monthly"}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert len(data["series"]) == 1
        assert data["series"][0]["label"] == "05/2025"

    def test_range_cross_year(self, api_client):
        r = api_client.get(f"{API}/dashboard/overtime/range",
                           params={"year_from": 2024, "month_from": 11,
                                   "year_to": 2025, "month_to": 2,
                                   "mode": "monthly"}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        labels = [s["label"] for s in data["series"]]
        assert labels == ["11/2024", "12/2024", "01/2025", "02/2025"]

    def test_range_invalid_month(self, api_client):
        r = api_client.get(f"{API}/dashboard/overtime/range",
                           params={"year_from": 2025, "month_from": 13,
                                   "year_to": 2025, "month_to": 5,
                                   "mode": "monthly"}, timeout=15)
        assert r.status_code == 400

    def test_range_invalid_year(self, api_client):
        r = api_client.get(f"{API}/dashboard/overtime/range",
                           params={"year_from": 1999, "month_from": 1,
                                   "year_to": 2025, "month_to": 5,
                                   "mode": "monthly"}, timeout=15)
        assert r.status_code == 400

    def test_range_mode_fallback(self, api_client):
        # invalid mode string should fall back to monthly (per code logic)
        r = api_client.get(f"{API}/dashboard/overtime/range",
                           params={"year_from": 2025, "month_from": 1,
                                   "year_to": 2025, "month_to": 2,
                                   "mode": "garbage"}, timeout=15)
        assert r.status_code == 200
        assert r.json()["mode"] == "monthly"

    def test_range_safety_cap(self, api_client):
        # safety cap is 36 months in implementation. A 4-year window should be capped.
        r = api_client.get(f"{API}/dashboard/overtime/range",
                           params={"year_from": 2022, "month_from": 1,
                                   "year_to": 2025, "month_to": 12,
                                   "mode": "monthly"}, timeout=60)
        assert r.status_code == 200
        data = r.json()
        assert len(data["series"]) <= 36
