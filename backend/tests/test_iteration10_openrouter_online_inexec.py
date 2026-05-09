"""Iteration 10 backend regression tests.

Covers:
  (A) GET /api/lousa/grid → columns[].clock_state.is_online + last_record_at + online_threshold_minutes
  (B) GET /api/lousa/grid → tickets[].in_execution (true if status=='aberta')
  (C) POST /api/lousa/tickets/{id}/transfer with status='aberta' → 409
  (D) DELETE /api/lousa/tickets/{id} with status='aberta' → 409
  (E) GET /api/settings → openrouter_* + online_threshold_minutes
  (F) PUT /api/settings → persists openrouter fields + online_threshold_minutes (1..1440)
  (G) PUT /api/settings → 422 for online_threshold_minutes out of range
  (H) GET /api/server-time → public (no auth) and shape {iso, epoch_ms, tz, sync_enabled, max_drift_seconds}
"""
import os
import uuid
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


# ---------- helpers ----------
def login(email: str, password: str = "123456") -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
        timeout=20,
    )
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    body = r.json()
    return body.get("access_token") or body.get("token")


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------- (H) /api/server-time public ----------
class TestServerTimePublic:
    def test_server_time_no_auth(self):
        r = requests.get(f"{API}/server-time", timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("iso", "epoch_ms", "tz", "sync_enabled", "max_drift_seconds"):
            assert k in d, f"missing key {k}: {d}"
        assert isinstance(d["epoch_ms"], int)
        assert isinstance(d["sync_enabled"], bool)
        assert isinstance(d["max_drift_seconds"], int)
        assert isinstance(d["iso"], str) and "T" in d["iso"]


# ---------- (E) GET /api/settings includes openrouter + online_threshold ----------
class TestSettingsOpenRouterOnlineThreshold:
    def test_settings_get_shape(self):
        tok = login("admin@empresa.com")
        r = requests.get(f"{API}/settings", headers=auth_headers(tok), timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("openrouter_enabled", "openrouter_model",
                  "openrouter_api_key", "openrouter_api_key_set",
                  "online_threshold_minutes"):
            assert k in d, f"missing settings key {k}: {list(d.keys())}"
        # Default model is 'deepseek/deepseek-v4-flash' or similar — just check it's a non-empty string
        assert isinstance(d["openrouter_model"], str)
        assert isinstance(d["openrouter_enabled"], bool)
        assert isinstance(d["openrouter_api_key_set"], bool)
        assert isinstance(d["online_threshold_minutes"], int)
        assert 1 <= d["online_threshold_minutes"] <= 1440

    # ---------- (F) PUT /api/settings persists openrouter + threshold ----------
    def test_put_settings_persists_openrouter_and_threshold(self):
        tok = login("admin@empresa.com")
        # Read current to restore later
        cur = requests.get(f"{API}/settings", headers=auth_headers(tok), timeout=20).json()
        original_threshold = cur.get("online_threshold_minutes", 5)
        original_enabled = cur.get("openrouter_enabled", False)
        original_model = cur.get("openrouter_model", "deepseek/deepseek-v4-flash")

        # Update
        new_key = "sk-or-v1-" + uuid.uuid4().hex
        payload = {
            "openrouter_enabled": True,
            "openrouter_api_key": new_key,
            "openrouter_model": "deepseek/deepseek-v4-flash",
            "online_threshold_minutes": 7,
        }
        r = requests.put(f"{API}/settings", json=payload, headers=auth_headers(tok), timeout=20)
        assert r.status_code == 200, r.text

        # GET back and check masking + persistence
        r2 = requests.get(f"{API}/settings", headers=auth_headers(tok), timeout=20).json()
        assert r2["openrouter_enabled"] is True
        assert r2["openrouter_api_key_set"] is True
        # Mascarada: contém "***" e NÃO retorna a chave inteira
        assert "***" in r2["openrouter_api_key"]
        assert new_key not in r2["openrouter_api_key"]
        # 'sk-or-v1' (prefixo fixo) + *** + 4 últimos
        assert r2["openrouter_api_key"].startswith("sk-or-v1")
        assert r2["openrouter_api_key"].endswith(new_key[-4:])
        assert r2["openrouter_model"] == "deepseek/deepseek-v4-flash"
        assert r2["online_threshold_minutes"] == 7

        # Restore (best effort)
        requests.put(
            f"{API}/settings",
            json={
                "openrouter_enabled": original_enabled,
                "openrouter_model": original_model,
                "online_threshold_minutes": original_threshold,
            },
            headers=auth_headers(tok),
            timeout=20,
        )

    # ---------- (G) Validation 422 ----------
    def test_put_threshold_too_low_returns_422(self):
        tok = login("admin@empresa.com")
        r = requests.put(
            f"{API}/settings",
            json={"online_threshold_minutes": 0},
            headers=auth_headers(tok),
            timeout=20,
        )
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"

    def test_put_threshold_too_high_returns_422(self):
        tok = login("admin@empresa.com")
        r = requests.put(
            f"{API}/settings",
            json={"online_threshold_minutes": 2000},
            headers=auth_headers(tok),
            timeout=20,
        )
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"


# ---------- (A) (B) /api/lousa/grid is_online + in_execution ----------
class TestLousaGridOnlineInExecution:
    def test_grid_columns_shape(self):
        tok = login("admin@empresa.com")
        r = requests.get(f"{API}/lousa/grid", headers=auth_headers(tok), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "columns" in data and isinstance(data["columns"], list)
        assert len(data["columns"]) > 0, "expected at least one collaborator column"
        col0 = data["columns"][0]
        assert "clock_state" in col0
        cs = col0["clock_state"]
        for k in ("is_online", "last_record_at", "online_threshold_minutes"):
            assert k in cs, f"clock_state missing {k}: {list(cs.keys())}"
        assert isinstance(cs["is_online"], bool)
        assert isinstance(cs["online_threshold_minutes"], int)
        # last_record_at can be None or string
        assert cs["last_record_at"] is None or isinstance(cs["last_record_at"], str)

    def test_grid_tickets_have_in_execution_flag(self):
        tok = login("admin@empresa.com")
        r = requests.get(f"{API}/lousa/grid", headers=auth_headers(tok), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        found_any_ticket = False
        for col in data["columns"]:
            for t in col.get("tickets") or []:
                found_any_ticket = True
                assert "in_execution" in t, f"ticket missing in_execution: {list(t.keys())}"
                assert isinstance(t["in_execution"], bool)
                # consistency: in_execution must equal status=='aberta'
                assert t["in_execution"] == (t.get("status") == "aberta"), (
                    f"in_execution flag mismatch for ticket {t.get('id')}: status={t.get('status')} flag={t['in_execution']}"
                )
        assert found_any_ticket, "no tickets found in grid for assertions"


# ---------- (C) (D) transfer/delete 409 when status='aberta' ----------
class TestTransferDeleteOpenTicketBlocked:
    def _create_pending_ticket(self, tok: str) -> dict:
        # Find a collaborator id from grid
        g = requests.get(f"{API}/lousa/grid", headers=auth_headers(tok), timeout=30).json()
        cid = None
        for col in g["columns"]:
            cid = col["collaborator"]["id"]
            if cid:
                break
        assert cid, "no collaborator found"
        payload = {
            "client_name": f"TEST_iter10_{uuid.uuid4().hex[:6]}",
            "address": "Rua Teste, 100, São Paulo, SP",
            "neighborhood": "Centro",
            "phone": "+5511999999999",
            "relato": "Teste iter10 — bloqueio em execução",
            "type": "reparo",
            "priority": "normal",
            "assigned_collaborator_id": cid,
        }
        r = requests.post(f"{API}/lousa/tickets", json=payload, headers=auth_headers(tok), timeout=30)
        assert r.status_code in (200, 201), r.text
        return r.json()

    def _admin_open(self, tok: str, ticket_id: str) -> dict:
        r = requests.post(
            f"{API}/lousa/tickets/{ticket_id}/admin-open",
            headers=auth_headers(tok),
            timeout=20,
        )
        assert r.status_code == 200, f"admin-open failed: {r.status_code} {r.text}"
        return r.json()

    def test_transfer_returns_409_when_aberta(self):
        tok = login("admin@empresa.com")
        t = self._create_pending_ticket(tok)
        tid = t["id"]
        try:
            self._admin_open(tok, tid)
            # Try transfer to same collaborator (still must 409 first)
            r = requests.post(
                f"{API}/lousa/tickets/{tid}/transfer",
                json={"new_grid_slot": "sem_horario"},
                headers=auth_headers(tok),
                timeout=20,
            )
            assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"
            body = r.json()
            msg = (body.get("detail") or body.get("message") or "").lower()
            assert "execução" in msg or "execucao" in msg, f"expected message about execução, got: {body}"
        finally:
            # Force admin-close+delete cleanup (best-effort)
            requests.post(
                f"{API}/lousa/tickets/{tid}/admin-close",
                json={"action": "cancelar", "notes": "cleanup iter10"},
                headers=auth_headers(tok),
                timeout=15,
            )
            requests.delete(f"{API}/lousa/tickets/{tid}", headers=auth_headers(tok), timeout=10)

    def test_delete_returns_409_when_aberta(self):
        tok = login("admin@empresa.com")
        t = self._create_pending_ticket(tok)
        tid = t["id"]
        try:
            self._admin_open(tok, tid)
            r = requests.delete(f"{API}/lousa/tickets/{tid}", headers=auth_headers(tok), timeout=20)
            assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"
            body = r.json()
            msg = (body.get("detail") or body.get("message") or "").lower()
            assert "execução" in msg or "execucao" in msg, f"expected message about execução, got: {body}"
        finally:
            requests.post(
                f"{API}/lousa/tickets/{tid}/admin-close",
                json={"action": "cancelar", "notes": "cleanup iter10"},
                headers=auth_headers(tok),
                timeout=15,
            )
            requests.delete(f"{API}/lousa/tickets/{tid}", headers=auth_headers(tok), timeout=10)
