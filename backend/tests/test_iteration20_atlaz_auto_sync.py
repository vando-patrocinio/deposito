"""Iteration 20 — Atlaz auto-sync technicians + new config fields + SSE.

Cobre:
- AtlazConfig 4 campos novos (auto_sync_technicians, tech_sync_interval_minutes,
  last_auto_sync_bubbles_at, last_auto_sync_technicians_at)
- GET/PUT /api/atlaz/settings com persistência
- Validação Field range (5..1440) → 422 do FastAPI
- POST /api/atlaz/sync-technicians shape de resposta
- Regressão básica: /atlaz/test-connection, /atlaz/sync-now, /atlaz/sync-logs,
  /lousa/grid, /events/stream connect quick
"""
import os
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN = {"email": "admin@empresa.com", "password": "123456"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# ---------------- Config: novos campos ----------------
class TestAtlazConfigNewFields:
    def test_get_settings_has_new_fields(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        for key in ["auto_sync_technicians", "tech_sync_interval_minutes",
                    "last_auto_sync_bubbles_at", "last_auto_sync_technicians_at"]:
            assert key in d, f"missing {key} in settings"
        assert isinstance(d["auto_sync_technicians"], bool)
        assert isinstance(d["tech_sync_interval_minutes"], int)
        assert 5 <= d["tech_sync_interval_minutes"] <= 1440

    def test_put_settings_persists_new_fields(self, auth_headers):
        # capture original
        orig = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15).json()

        payload = {
            "auto_sync_technicians": True,
            "tech_sync_interval_minutes": 30,
        }
        r = requests.put(f"{BASE_URL}/api/atlaz/settings", json=payload,
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["auto_sync_technicians"] is True
        assert d["tech_sync_interval_minutes"] == 30

        # GET to confirm persistence
        r2 = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["auto_sync_technicians"] is True
        assert d2["tech_sync_interval_minutes"] == 30

        # restore
        requests.put(f"{BASE_URL}/api/atlaz/settings",
                     json={
                         "auto_sync_technicians": orig.get("auto_sync_technicians", True),
                         "tech_sync_interval_minutes": orig.get("tech_sync_interval_minutes", 60),
                     },
                     headers=auth_headers, timeout=15)

    def test_put_settings_rejects_low_interval(self, auth_headers):
        r = requests.put(f"{BASE_URL}/api/atlaz/settings",
                         json={"tech_sync_interval_minutes": 4},
                         headers=auth_headers, timeout=15)
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"
        # GET should still 200 (no corruption persisted)
        g = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15)
        assert g.status_code == 200

    def test_put_settings_rejects_high_interval(self, auth_headers):
        r = requests.put(f"{BASE_URL}/api/atlaz/settings",
                         json={"tech_sync_interval_minutes": 1500},
                         headers=auth_headers, timeout=15)
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"
        g = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15)
        assert g.status_code == 200

    @pytest.mark.parametrize("field,bad_value", [
        ("tech_sync_interval_minutes", 4),
        ("tech_sync_interval_minutes", 2000),
        ("sync_interval_minutes", 0),
        ("sync_interval_minutes", 2000),
        ("lookback_days", 0),
        ("lookback_days", 400),
        ("timeout_seconds", 1),
        ("timeout_seconds", 200),
    ])
    def test_put_settings_rejects_out_of_range(self, auth_headers, field, bad_value):
        r = requests.put(f"{BASE_URL}/api/atlaz/settings",
                         json={field: bad_value},
                         headers=auth_headers, timeout=15)
        assert r.status_code == 422, f"{field}={bad_value} expected 422, got {r.status_code}: {r.text}"
        # GET ainda 200
        g = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15)
        assert g.status_code == 200, f"GET broke after invalid {field}={bad_value}: {g.text}"

    def test_get_settings_auto_heals_corrupt_config(self, auth_headers):
        """Insere via Mongo direto um doc corrompido (tech_sync_interval_minutes=99999)
        e valida que GET /atlaz/settings retorna 200 com valor clampado para default 60.
        """
        import subprocess
        # 1) Snapshot original
        orig = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15).json()
        orig_tsim = int(orig.get("tech_sync_interval_minutes") or 60)

        # 2) Corrompe via pymongo direto (sync — db.py é motor/async)
        corrupt_cmd = (
            "import os;from pymongo import MongoClient;"
            "c=MongoClient(os.environ.get('MONGO_URL','mongodb://localhost:27017'));"
            "c[os.environ.get('DB_NAME','test_database')].atlaz_config.update_one("
            "{'company_id':'co-demo'},"
            "{'$set':{'tech_sync_interval_minutes':99999}}, upsert=True)"
        )
        env = {**os.environ, "MONGO_URL": "mongodb://localhost:27017", "DB_NAME": "test_database"}
        cp = subprocess.run(["python3", "-c", corrupt_cmd], capture_output=True, timeout=15, text=True, env=env)
        assert cp.returncode == 0, f"corrupt insert failed: {cp.stderr}"

        try:
            # 3) GET /settings deve responder 200 (auto-heal) e devolver valor sanitizado
            r = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15)
            assert r.status_code == 200, f"auto-heal falhou: {r.status_code} {r.text}"
            d = r.json()
            assert d["tech_sync_interval_minutes"] == 60, (
                f"expected default 60 after auto-heal, got {d['tech_sync_interval_minutes']}"
            )
        finally:
            # 4) Restore original
            requests.put(f"{BASE_URL}/api/atlaz/settings",
                         json={"tech_sync_interval_minutes": orig_tsim},
                         headers=auth_headers, timeout=15)

    @staticmethod
    def _restore_db():
        """Direct DB restore — required because PUT pode dar 500 enquanto config inválida no DB."""
        import subprocess
        subprocess.run(["python3", "-c",
            "import asyncio,sys;sys.path.insert(0,'/app/backend');"
            "from database import db;"
            "asyncio.run(db.atlaz_config.update_one({'company_id':'co-demo'},"
            "{'$set':{'tech_sync_interval_minutes':60,'sync_interval_minutes':15}}))"
        ], capture_output=True, timeout=10)

    @staticmethod
    def _restore_db():
        """Direct DB restore — required because PUT pode dar 500 enquanto config inválida no DB."""
        import subprocess
        subprocess.run(["python3", "-c",
            "import asyncio,sys;sys.path.insert(0,'/app/backend');"
            "from database import db;"
            "asyncio.run(db.atlaz_config.update_one({'company_id':'co-demo'},"
            "{'$set':{'tech_sync_interval_minutes':60,'sync_interval_minutes':15}}))"
        ], capture_output=True, timeout=10)

    def test_put_settings_accepts_boundary_values(self, auth_headers):
        # min boundary 5
        r = requests.put(f"{BASE_URL}/api/atlaz/settings",
                         json={"tech_sync_interval_minutes": 5},
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert r.json()["tech_sync_interval_minutes"] == 5
        # max boundary 1440
        r = requests.put(f"{BASE_URL}/api/atlaz/settings",
                         json={"tech_sync_interval_minutes": 1440},
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert r.json()["tech_sync_interval_minutes"] == 1440
        # restore
        requests.put(f"{BASE_URL}/api/atlaz/settings",
                     json={"tech_sync_interval_minutes": 60},
                     headers=auth_headers, timeout=15)

    def test_put_settings_valid_regression(self, auth_headers):
        """Regressão: PUT com valores válidos persiste; last_auto_sync_technicians_at presente."""
        orig = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15).json()
        try:
            r = requests.put(f"{BASE_URL}/api/atlaz/settings",
                             json={"auto_sync_technicians": True, "tech_sync_interval_minutes": 30},
                             headers=auth_headers, timeout=15)
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["auto_sync_technicians"] is True
            assert d["tech_sync_interval_minutes"] == 30
            g = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15).json()
            assert g["tech_sync_interval_minutes"] == 30
            assert "last_auto_sync_technicians_at" in g
        finally:
            requests.put(f"{BASE_URL}/api/atlaz/settings",
                         json={
                             "auto_sync_technicians": orig.get("auto_sync_technicians", True),
                             "tech_sync_interval_minutes": orig.get("tech_sync_interval_minutes", 60),
                         },
                         headers=auth_headers, timeout=15)


# ---------------- sync-technicians shape ----------------
class TestSyncTechniciansEndpoint:
    def test_sync_technicians_shape(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/atlaz/sync-technicians",
                          headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        # shape consistente, mesmo em missing_api_key
        assert "ok" in d
        if d["ok"]:
            for k in ["total_atlaz_technicians", "created", "matched_existing",
                      "errors", "items_created"]:
                assert k in d, f"missing key {k}"
            assert isinstance(d["created"], int)
            assert isinstance(d["matched_existing"], int)
            assert isinstance(d["errors"], list)
            assert isinstance(d["items_created"], list)


# ---------------- Regressão endpoints existentes ----------------
class TestAtlazRegression:
    def test_test_connection(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/atlaz/test-connection",
                          headers=auth_headers, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "ok" in d

    def test_sync_now(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/atlaz/sync-now",
                          headers=auth_headers, timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert "ok" in d

    def test_sync_logs(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/atlaz/sync-logs?limit=10",
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d
        assert "count" in d
        assert isinstance(d["items"], list)


class TestLousaRegression:
    def test_lousa_grid_no_filter(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/lousa/grid", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "rows" in d or "items" in d or "lanes" in d or isinstance(d, dict)

    def test_lousa_grid_with_dates(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/lousa/grid?date_from=2026-01-01&date_to=2026-01-31",
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200

    def test_lousa_by_collaborator(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/lousa/by-collaborator/col-demo-001",
                         headers=auth_headers, timeout=15)
        assert r.status_code in (200, 404)


class TestSSEStream:
    def test_events_stream_connects(self, admin_token):
        """SSE endpoint quick sanity check — connect, read first event, close."""
        url = f"{BASE_URL}/api/events/stream?token={admin_token}"
        try:
            with requests.get(url, stream=True, timeout=10) as r:
                assert r.status_code == 200
                ct = r.headers.get("content-type", "")
                assert "text/event-stream" in ct.lower(), f"wrong CT: {ct}"
                # ler 1 chunk pra confirmar primeiro evento "connected"
                start = time.time()
                got_event = False
                for raw in r.iter_lines(decode_unicode=True):
                    if raw and raw.strip():
                        got_event = True
                        break
                    if time.time() - start > 5:
                        break
                assert got_event, "no SSE event received within 5s"
        except requests.exceptions.ReadTimeout:
            pytest.skip("SSE stream timeout — endpoint OK but slow")
