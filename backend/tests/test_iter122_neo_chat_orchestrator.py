"""
Iteration 122 — NEO Chat orchestrator + 4 new report types + ask_neo tool in Secretaria.

Tests:
- /api/neo-chat/ask (multiple intents, freeform, phone extraction)
- /api/neo-chat/history, /sessions, /tools
- /api/neo-reports/schedules (POST with 4 new types) + /run (PDF > 1000 bytes)
- /api/neo-reports/report-types must list 7 types
- /api/secretaria/ask invoking ask_neo internally
- Auth: /api/neo-chat/* requires role gestor (401/403 without token)
"""
import os
import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
KNOWN_TOOLS = {
    "isabella_kpis", "alvaro_tickets", "camila_billing",
    "secretaria_intents", "customer_timeline",
    "neo_reports_recent", "list_schedules", "freeform",
}


# ----------------- fixtures -----------------
@pytest.fixture(scope="session")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "gestor@empresa.com", "password": "123456"},
        timeout=20,
    )
    assert r.status_code == 200, f"login fail: {r.status_code} {r.text}"
    tok = r.json().get("access_token")
    assert tok
    return tok


@pytest.fixture(scope="session")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ----------------- AUTH GUARD -----------------
class TestNeoChatAuth:
    def test_ask_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/neo-chat/ask",
                          json={"question": "oi"}, timeout=15)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"

    def test_history_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/neo-chat/history", timeout=15)
        assert r.status_code in (401, 403)

    def test_sessions_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/neo-chat/sessions", timeout=15)
        assert r.status_code in (401, 403)

    def test_tools_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/neo-chat/tools", timeout=15)
        assert r.status_code in (401, 403)


# ----------------- TOOLS LISTING -----------------
class TestNeoTools:
    def test_list_tools(self, auth):
        r = requests.get(f"{BASE_URL}/api/neo-chat/tools",
                         headers=auth, timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert "tools" in data
        names = {t["name"] for t in data["tools"]}
        expected = {"isabella_kpis", "alvaro_tickets", "camila_billing",
                    "secretaria_intents", "customer_timeline",
                    "neo_reports_recent", "list_schedules"}
        assert expected.issubset(names), f"missing tools: {expected - names}"
        assert len(data["tools"]) == 7


# ----------------- ASK (LLM) -----------------
class TestNeoAsk:
    def _ask(self, auth, question, session_id=None, timeout=90):
        body = {"question": question}
        if session_id:
            body["session_id"] = session_id
        last = None
        for _ in range(2):
            try:
                r = requests.post(f"{BASE_URL}/api/neo-chat/ask",
                                  json=body, headers=auth, timeout=timeout)
                last = r
                if r.status_code == 200:
                    return r
            except requests.exceptions.ReadTimeout as e:
                last = e
                continue
        if isinstance(last, Exception):
            raise last
        return last

    def test_ask_isabella_kpis(self, auth):
        r = self._ask(auth, "KPIs da Isabella últimos 7 dias")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("answer"), "answer should be non-empty"
        assert isinstance(data.get("answer"), str)
        assert data.get("tool") in KNOWN_TOOLS, f"unexpected tool {data.get('tool')}"
        # tool_data may be None for freeform; if isabella_kpis, must be dict
        if data["tool"] == "isabella_kpis":
            assert isinstance(data.get("tool_data"), dict)
            assert data["tool_data"].get("agent") == "Isabella"
        assert "session_id" in data

    def test_ask_camila_billing_month(self, auth):
        r = self._ask(auth, "quanto a Pâmela cobrou este mês?")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("answer")
        assert data.get("tool") in KNOWN_TOOLS
        if data["tool"] == "camila_billing":
            assert isinstance(data.get("tool_data"), dict)
            # Accept either 30 days or another sensible value
            assert data["tool_data"].get("period_days") in (7, 30, 31)

    def test_ask_alvaro_today(self, auth):
        r = self._ask(auth, "quantos tickets o Álvaro resolveu hoje?")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("answer")
        assert data.get("tool") in KNOWN_TOOLS
        if data["tool"] == "alvaro_tickets":
            assert isinstance(data.get("tool_data"), dict)
            assert data["tool_data"].get("agent") in ("Álvaro", "Alvaro")

    def test_ask_customer_timeline(self, auth):
        r = self._ask(auth, "timeline do 5582999998888")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("answer")
        assert data.get("tool") in KNOWN_TOOLS
        if data["tool"] == "customer_timeline":
            td = data.get("tool_data") or {}
            # phone digits must be in the response
            assert "82999998888" in (td.get("phone") or "") or td.get("error")

    def test_ask_freeform(self, auth):
        r = self._ask(auth, "oi NEO, tudo bem?")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("answer"), "freeform must still return answer"
        # tool may be 'freeform' or other; both acceptable
        assert data.get("tool") in KNOWN_TOOLS


# ----------------- HISTORY / SESSIONS -----------------
class TestNeoHistorySessions:
    def test_history_and_sessions(self, auth):
        # create a session with deterministic id
        sid = "neo-test-iter122"
        r1 = requests.post(f"{BASE_URL}/api/neo-chat/ask",
                           json={"question": "olá NEO, teste pytest",
                                 "session_id": sid},
                           headers=auth, timeout=60)
        assert r1.status_code == 200
        # history
        h = requests.get(f"{BASE_URL}/api/neo-chat/history",
                         params={"session_id": sid},
                         headers=auth, timeout=20)
        assert h.status_code == 200
        hdata = h.json()
        assert hdata["total"] >= 2  # user + assistant
        # chronological order
        ats = [m.get("at") for m in hdata["items"]]
        assert ats == sorted(ats), "history must be chronological"
        # roles present
        roles = {m.get("role") for m in hdata["items"]}
        assert {"user", "assistant"}.issubset(roles)

        # sessions list
        s = requests.get(f"{BASE_URL}/api/neo-chat/sessions",
                         headers=auth, timeout=20)
        assert s.status_code == 200
        sdata = s.json()
        sids = {x.get("session_id") for x in sdata.get("items", [])}
        assert sid in sids, "our session must show up"
        # last_at field present
        ours = next(x for x in sdata["items"] if x["session_id"] == sid)
        assert ours.get("last_at")
        assert ours.get("msg_count", 0) >= 2


# ----------------- REPORT TYPES (4 new) -----------------
NEW_TYPES = ["isabella_kpis", "alvaro_tickets",
             "camila_billing", "secretaria_intents"]


class TestNeoReportsNewTypes:
    def test_report_types_lists_7(self, auth):
        r = requests.get(f"{BASE_URL}/api/neo-reports/report-types",
                         headers=auth, timeout=20)
        assert r.status_code == 200
        data = r.json()
        items = data.get("items") or data.get("types") or data
        # try multiple shapes
        if isinstance(items, dict):
            items = items.get("items") or list(items.values())
        keys = []
        for it in items:
            if isinstance(it, dict):
                keys.append(it.get("key") or it.get("type") or it.get("id"))
            else:
                keys.append(it)
        keys = [k for k in keys if k]
        for t in NEW_TYPES + ["ctos_occupancy", "closed_tickets", "dre"]:
            assert t in keys, f"missing report type {t}; got {keys}"
        assert len(keys) >= 7

    @pytest.mark.parametrize("rtype", NEW_TYPES)
    def test_schedule_create_and_run(self, auth, rtype):
        # create schedule
        body = {
            "name": f"TEST_{rtype}",
            "report_type": rtype,
            "frequency": "daily",
            "hour": 8,
            "channels": ["email"],
            "recipients": ["test@example.com"],
        }
        r = requests.post(f"{BASE_URL}/api/neo-reports/schedules",
                          json=body, headers=auth, timeout=30)
        assert r.status_code in (200, 201), f"{rtype} create failed: {r.status_code} {r.text}"
        sch = r.json()
        sch_id = sch.get("id") or (sch.get("item") or {}).get("id")
        assert sch_id, f"no id in response: {sch}"
        assert sch.get("next_run_at") or (sch.get("item") or {}).get("next_run_at"), "next_run_at must be computed"

        # run it
        run_r = requests.post(
            f"{BASE_URL}/api/neo-reports/schedules/{sch_id}/run",
            headers=auth, timeout=60,
        )
        assert run_r.status_code in (200, 201), f"{rtype} run failed: {run_r.status_code} {run_r.text}"
        run = run_r.json()
        # accept either status or success flag
        status = run.get("status") or run.get("result", {}).get("status")
        size = run.get("pdf_size_bytes") or run.get("result", {}).get("pdf_size_bytes") or run.get("size_bytes")
        assert status in ("success", "ok", "done"), f"{rtype} status: {status}; run={run}"
        assert size and int(size) > 1000, f"{rtype} pdf too small: {size}"

        # cleanup
        try:
            requests.delete(f"{BASE_URL}/api/neo-reports/schedules/{sch_id}",
                            headers=auth, timeout=15)
        except Exception:
            pass


# ----------------- SECRETARIA → NEO -----------------
class TestSecretariaAskNeo:
    def test_ask_neo_via_secretaria(self, auth):
        r = requests.post(
            f"{BASE_URL}/api/secretaria/ask",
            json={"question": "Use o NEO pra me dar KPIs da Isabella"},
            headers=auth, timeout=120,
        )
        assert r.status_code == 200, f"secretaria/ask failed: {r.status_code} {r.text}"
        data = r.json()
        assert data.get("answer"), f"empty answer: {data}"
        iters = data.get("iterations") or data.get("steps") or 0
        if isinstance(iters, list):
            iters = len(iters)
        assert int(iters) >= 1, f"expected iterations>=1, got {iters}; resp={data}"
