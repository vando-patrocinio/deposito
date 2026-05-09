"""Iter16 — Atlaz Integration backend tests.
Covers GET/PUT /api/atlaz/settings, test-connection, sync-now, sync-logs,
role auth, push_close via admin-close, regression on /api/server-time and lousa.
"""
import os
import asyncio
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")


def _login(api, email, password):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login {email} -> {r.status_code} {r.text[:200]}"
    return r.json().get("token") or r.json().get("access_token")


@pytest.fixture(scope="module")
def gestor_headers(api):
    tok = _login(api, "gestor@empresa.com", "123456")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_headers(api):
    tok = _login(api, "admin@empresa.com", "123456")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def collab_headers(api):
    tok = _login(api, "colaborador@empresa.com", "123456")
    return {"Authorization": f"Bearer {tok}"}


# ---------- GET /api/atlaz/settings ----------
class TestAtlazSettings:
    def test_get_settings_defaults(self, api, gestor_headers):
        r = api.get(f"{BASE_URL}/api/atlaz/settings", headers=gestor_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        # Default fields
        assert d.get("base_url", "").startswith("http")
        assert d.get("api_key_header") == "X-API-Key"
        assert "/v1/ordens-servico" in d.get("list_path", "")
        assert "{id}" in d.get("close_path", "")
        assert "{id}" in d.get("cancel_path", "")
        assert "{id}" in d.get("reschedule_path", "")
        assert d.get("list_query_status") == "aberta"
        # sync_interval may have been changed by previous tests; just validate range
        assert 1 <= int(d.get("sync_interval_minutes", 0)) <= 1440
        assert d.get("auto_create_bubbles") is True
        assert d.get("auto_push_on_close") is True
        # type_map
        tm = d.get("type_map") or {}
        assert tm.get("REPARO") == "reparo"
        assert tm.get("INSTALACAO") == "instalacao"
        # field_map
        fm = d.get("field_map") or {}
        assert fm.get("client_name") == "cliente_nome"
        assert fm.get("address") == "endereco"
        # api_key_set flag
        assert "api_key_set" in d

    def test_get_settings_collab_forbidden(self, api, collab_headers):
        r = api.get(f"{BASE_URL}/api/atlaz/settings", headers=collab_headers)
        assert r.status_code == 403

    def test_get_settings_unauth(self, api):
        r = api.get(f"{BASE_URL}/api/atlaz/settings")
        assert r.status_code in (401, 403)


# ---------- PUT /api/atlaz/settings ----------
class TestAtlazPut:
    def test_put_save_apikey_and_mask(self, api, gestor_headers):
        payload = {
            "enabled": True,
            "base_url": "https://api.seuatlaz.com",
            "api_key": "TESTKEY_abcd1234efgh5678",
            "filiais": ["FILIAL_TESTE"],
            "sync_interval_minutes": 15,
        }
        r = api.put(f"{BASE_URL}/api/atlaz/settings", json=payload, headers=gestor_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("enabled") is True
        assert d.get("api_key_set") is True
        # mask format aaaa…bbbb
        ak = d.get("api_key") or ""
        assert "…" in ak or "..." in ak
        assert "TESTKEY" in ak[:6] or ak.startswith("TEST")
        assert d.get("sync_interval_minutes") == 15
        assert d.get("filiais") == ["FILIAL_TESTE"]

    def test_put_partial_does_not_overwrite_apikey(self, api, gestor_headers):
        # send empty api_key; should not overwrite
        r = api.put(f"{BASE_URL}/api/atlaz/settings",
                    json={"api_key": "", "list_query_status": "aberta"},
                    headers=gestor_headers)
        assert r.status_code == 200
        d = r.json()
        assert d.get("api_key_set") is True, "api_key should still be set"
        assert d.get("api_key") and ("…" in d["api_key"] or "..." in d["api_key"])

    def test_put_collab_forbidden(self, api, collab_headers):
        r = api.put(f"{BASE_URL}/api/atlaz/settings", json={"enabled": False}, headers=collab_headers)
        assert r.status_code == 403


# ---------- test-connection ----------
class TestAtlazTest:
    def test_test_connection_dns_invalid_graceful(self, api, gestor_headers):
        r = api.post(f"{BASE_URL}/api/atlaz/test-connection", headers=gestor_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        # placeholder DNS doesn't resolve → ok=false with error/url
        assert "ok" in d
        if not d.get("ok"):
            assert d.get("error") or d.get("reason")
            assert d.get("url", "").startswith("http")
        # otherwise (in case of success), should have status/url
        else:
            assert "status" in d

    def test_test_connection_collab_forbidden(self, api, collab_headers):
        r = api.post(f"{BASE_URL}/api/atlaz/test-connection", headers=collab_headers)
        assert r.status_code == 403


# ---------- sync-now ----------
class TestAtlazSyncNow:
    def test_sync_now_enabled_with_dns_fail(self, api, gestor_headers):
        # Already enabled in earlier test
        r = api.post(f"{BASE_URL}/api/atlaz/sync-now", headers=gestor_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        # endpoint shouldn't crash even if fetch fails
        assert d.get("ok") is True
        assert "created" in d
        assert "skipped" in d
        assert "errors" in d

    def test_sync_now_disabled_returns_disabled(self, api, gestor_headers):
        # disable
        api.put(f"{BASE_URL}/api/atlaz/settings", json={"enabled": False}, headers=gestor_headers)
        r = api.post(f"{BASE_URL}/api/atlaz/sync-now", headers=gestor_headers)
        assert r.status_code == 200
        d = r.json()
        assert d.get("ok") is False
        assert d.get("reason") == "disabled"
        # re-enable for downstream tests
        api.put(f"{BASE_URL}/api/atlaz/settings", json={"enabled": True}, headers=gestor_headers)


# ---------- sync-logs ----------
class TestAtlazLogs:
    def test_sync_logs_returns_items(self, api, gestor_headers):
        r = api.get(f"{BASE_URL}/api/atlaz/sync-logs?limit=20", headers=gestor_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "items" in d and "count" in d
        assert isinstance(d["items"], list)
        assert d["count"] == len(d["items"])
        if d["items"]:
            ev = d["items"][0]
            for k in ("id", "company_id", "event", "status", "at"):
                assert k in ev, f"missing {k} in log item"
            assert ev["event"] in ("test", "pull", "push_encerrar", "push_cancelar", "push_reagendar")
            assert ev["status"] in ("ok", "error", "partial")

    def test_sync_logs_collab_forbidden(self, api, collab_headers):
        r = api.get(f"{BASE_URL}/api/atlaz/sync-logs", headers=collab_headers)
        assert r.status_code == 403


# ---------- Push close via admin-close ----------
class TestAtlazPushClose:
    def test_admin_close_pushes_atlaz_when_external_id(self, api, gestor_headers):
        """Manually inject atlaz_external_id on a ticket via DB then admin-close."""
        listing = api.get(f"{BASE_URL}/api/lousa/all", headers=gestor_headers)
        if listing.status_code != 200:
            pytest.skip(f"lousa/all not available: {listing.status_code}")
        tickets = listing.json().get("tickets", [])
        ticket_id = None
        for t in tickets:
            if t.get("status") in ("pendente", "em_andamento") and not t.get("atlaz_external_id"):
                ticket_id = t["id"]
                break
        if not ticket_id:
            pytest.skip("no open ticket found")

        # inject via direct DB call using pymongo (sync) - load .env
        import subprocess
        script = (
            "from dotenv import load_dotenv\n"
            "load_dotenv('/app/backend/.env')\n"
            "import os\n"
            "from pymongo import MongoClient\n"
            "c = MongoClient(os.environ['MONGO_URL'])\n"
            "db = c[os.environ['DB_NAME']]\n"
            f"r = db.tickets.update_one({{'id':'{ticket_id}'}}, {{'$set':{{'atlaz_external_id':'TEST-ATLAZ-001','atlaz_filial':'TEST'}}}})\n"
            "print('matched:', r.matched_count, 'modified:', r.modified_count)\n"
        )
        result = subprocess.run(
            ["python3", "-c", script],
            capture_output=True, text=True, cwd="/app/backend",
        )
        assert result.returncode == 0, result.stderr

        # now admin-close
        r = api.post(f"{BASE_URL}/api/lousa/tickets/{ticket_id}/admin-close",
                     json={"action": "encerrar", "notes": "iter16 test"},
                     headers=gestor_headers)
        assert r.status_code in (200, 400, 403), f"unexpected {r.status_code}: {r.text[:200]}"
        # admin-close must NOT crash even when push fails (DNS bad)
        # check log was created
        import time; time.sleep(1)
        logs = api.get(f"{BASE_URL}/api/atlaz/sync-logs?limit=10", headers=gestor_headers).json()
        push_events = [e for e in logs.get("items", []) if str(e.get("event", "")).startswith("push_")]
        # Push event should exist if admin-close succeeded
        if r.status_code == 200:
            assert push_events, "no push log found after admin-close on atlaz ticket"


# ---------- Regression ----------
class TestRegression:
    def test_server_time(self, api):
        r = api.get(f"{BASE_URL}/api/server-time")
        assert r.status_code == 200
        d = r.json()
        assert "server_time" in d or "now" in d or "iso" in d or "timestamp" in d

    def test_lousa_grid_no_filters(self, api, gestor_headers):
        r = api.get(f"{BASE_URL}/api/lousa/grid", headers=gestor_headers)
        assert r.status_code == 200, r.text

    def test_lousa_grid_with_date(self, api, gestor_headers):
        r = api.get(f"{BASE_URL}/api/lousa/grid?date=2026-01-15", headers=gestor_headers)
        assert r.status_code == 200, r.text


# ---------- Cleanup ----------
@pytest.fixture(scope="module", autouse=True)
def _cleanup_after(api, request):
    yield
    # disable atlaz to leave system clean
    try:
        tok = _login(api, "gestor@empresa.com", "123456")
        api.put(
            f"{BASE_URL}/api/atlaz/settings",
            json={"enabled": False},
            headers={"Authorization": f"Bearer {tok}"},
        )
    except Exception:
        pass
