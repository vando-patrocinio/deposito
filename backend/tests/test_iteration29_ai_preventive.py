"""E2E tests AI Preventiva (iter 29)."""
import uuid
import pytest


@pytest.fixture(scope="module")
def admin_token(base_url, api):
    r = api.post(f"{base_url}/api/auth/login",
                 json={"email": "admin@empresa.com", "password": "123456"})
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def test_settings_default(base_url, api, headers):
    r = api.get(f"{base_url}/api/ai/preventive/settings", headers=headers)
    assert r.status_code == 200
    d = r.json()
    assert d["enabled"] is True
    assert d["critical_rx_dbm"] <= -20
    assert 7 <= d["pace_lookback_days"] <= 90


def test_capacity_dashboard(base_url, api, headers):
    r = api.get(f"{base_url}/api/ai/preventive/capacity", headers=headers)
    assert r.status_code == 200
    d = r.json()
    assert "techs" in d and "total_capacity_today" in d
    assert isinstance(d["techs"], list)
    assert d["techs"], "Pelo menos 1 técnico deve aparecer"
    for t in d["techs"]:
        for k in ("id", "name", "ritmo_efetivo", "carga_hoje", "capacity_today"):
            assert k in t


def test_scan_force_creates_suggestions(base_url, api, headers):
    r = api.post(f"{base_url}/api/ai/preventive/scan?force=true", headers=headers,
                 timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["scanned_clients"] > 0
    assert d["suggestions_created"] > 0
    sample = d["suggestions"][0]
    for k in ("id", "client_name", "rx_dbm", "tech_id", "tech_name", "urgency"):
        assert k in sample
    # Reject 1 sugestão pra testar
    sid = sample["id"]
    rj = api.post(f"{base_url}/api/ai/preventive/reject/{sid}", headers=headers)
    assert rj.status_code == 200


def test_accept_creates_bubble(base_url, api, headers):
    """Aceita uma sugestão e verifica que cria bolha tipo 'preventiva'."""
    pendings = api.get(f"{base_url}/api/ai/preventive/suggestions",
                       headers=headers, params={"status": "pending"}).json()
    if not pendings:
        # Gera novas se não tiver
        api.post(f"{base_url}/api/ai/preventive/scan?force=true", headers=headers, timeout=60)
        pendings = api.get(f"{base_url}/api/ai/preventive/suggestions",
                           headers=headers, params={"status": "pending"}).json()
    assert pendings, "deveria ter sugestões pendentes"
    s = pendings[0]
    r = api.post(f"{base_url}/api/ai/preventive/accept/{s['id']}", headers=headers)
    assert r.status_code == 200, r.text
    tid = r.json()["ticket_id"]

    # Verifica que a bolha existe e tem type=preventiva
    grid = api.get(f"{base_url}/api/lousa/grid", headers=headers).json()
    found = None
    for col in grid["columns"]:
        for sl in col.get("slots", []):
            for t in sl.get("tickets", []):
                if t["id"] == tid:
                    found = t
        for t in col.get("unscheduled", []):
            if t["id"] == tid:
                found = t
    assert found is not None, f"bolha {tid} não encontrada no grid"
    assert found["type"] == "preventiva"
    assert "🤖" in (found.get("client_snapshot") or {}).get("relato", "")
    # Cleanup
    api.delete(f"{base_url}/api/lousa/tickets/{tid}", headers=headers)


def test_double_accept_returns_400(base_url, api, headers):
    pendings = api.get(f"{base_url}/api/ai/preventive/suggestions",
                       headers=headers, params={"status": "pending"}).json()
    if not pendings:
        api.post(f"{base_url}/api/ai/preventive/scan?force=true", headers=headers, timeout=60)
        pendings = api.get(f"{base_url}/api/ai/preventive/suggestions",
                           headers=headers, params={"status": "pending"}).json()
    s = pendings[0]
    r1 = api.post(f"{base_url}/api/ai/preventive/accept/{s['id']}", headers=headers)
    assert r1.status_code == 200
    r2 = api.post(f"{base_url}/api/ai/preventive/accept/{s['id']}", headers=headers)
    assert r2.status_code == 400
    # Cleanup
    api.delete(f"{base_url}/api/lousa/tickets/{r1.json()['ticket_id']}", headers=headers)


def test_unauthorized(base_url, api):
    r = api.post(f"{base_url}/api/ai/preventive/scan")
    assert r.status_code in (401, 403)


def test_notifications_endpoint_exists(base_url, api, headers):
    r = api.get(f"{base_url}/api/notifications", headers=headers)
    assert r.status_code == 200
    d = r.json()
    assert "items" in d and "unread_count" in d
