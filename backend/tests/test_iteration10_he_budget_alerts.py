"""Iteration 10 — HE budget + threshold alerts no Painel."""
import os
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
COL_DEMO = "col-demo-001"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@example.com", "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module", autouse=True)
def setup_carlos_paid(auth_headers):
    """Configura Carlos com policy=pago, hourly_rate=30 e GARANTE budget=0 ao final."""
    # snapshot inicial
    r = requests.get(f"{BASE_URL}/api/collaborators/{COL_DEMO}")
    assert r.status_code == 200
    coll = r.json()
    original_policy = coll.get("overtime_policy", {})

    # configura como pago
    payload = {
        "name": coll["name"], "cpf": coll["cpf"], "email": coll["email"], "phone": coll["phone"],
        "role": coll.get("role", "Colaborador de Campo"), "company": coll.get("company", "Operação SP"),
        "schedule": coll.get("schedule", {}),
        "overtime_policy": {"mode": "pago", "hourly_rate_brl": 30.0, "weekday_multiplier": 1.5, "sunday_multiplier": 2.0},
        "city": coll.get("city"), "state": coll.get("state"),
    }
    r = requests.put(f"{BASE_URL}/api/collaborators/{COL_DEMO}", json=payload)
    assert r.status_code == 200, r.text

    yield

    # restaura policy original e zera budget
    if original_policy:
        payload["overtime_policy"] = original_policy
        requests.put(f"{BASE_URL}/api/collaborators/{COL_DEMO}", json=payload)
    requests.put(f"{BASE_URL}/api/settings", json={"he_monthly_budget_brl": 0.0, "he_alert_threshold_pct": 30.0})


# ---------- Settings ----------

def test_settings_get_has_new_fields():
    r = requests.get(f"{BASE_URL}/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "he_monthly_budget_brl" in data
    assert "he_alert_threshold_pct" in data
    assert isinstance(data["he_monthly_budget_brl"], (int, float))
    assert isinstance(data["he_alert_threshold_pct"], (int, float))


def test_settings_put_accepts_new_fields():
    r = requests.put(f"{BASE_URL}/api/settings", json={"he_monthly_budget_brl": 500.0, "he_alert_threshold_pct": 25.0})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["he_monthly_budget_brl"] == 500.0
    assert data["he_alert_threshold_pct"] == 25.0
    # GET verifica persistência
    g = requests.get(f"{BASE_URL}/api/settings")
    gd = g.json()
    assert gd["he_monthly_budget_brl"] == 500.0
    assert gd["he_alert_threshold_pct"] == 25.0


# ---------- Trend / alerts ----------

def test_trend_returns_alerts_budget_threshold_fields():
    requests.put(f"{BASE_URL}/api/settings", json={"he_monthly_budget_brl": 0.0, "he_alert_threshold_pct": 30.0})
    r = requests.get(f"{BASE_URL}/api/dashboard/overtime/trend?months=3")
    assert r.status_code == 200
    data = r.json()
    assert "alerts" in data
    assert "budget_brl" in data
    assert "threshold_pct" in data
    assert isinstance(data["alerts"], list)
    assert data["budget_brl"] == 0.0
    assert data["threshold_pct"] == 30.0


def test_trend_no_budget_alert_when_budget_zero():
    requests.put(f"{BASE_URL}/api/settings", json={"he_monthly_budget_brl": 0.0, "he_alert_threshold_pct": 30.0})
    r = requests.get(f"{BASE_URL}/api/dashboard/overtime/trend?months=3")
    data = r.json()
    ids = [a["id"] for a in data["alerts"]]
    assert "budget_exceeded" not in ids
    assert "budget_close" not in ids


def test_trend_budget_exceeded_alert():
    """Budget=50 com Carlos pago/30 deve gerar budget_exceeded (danger)."""
    requests.put(f"{BASE_URL}/api/settings", json={"he_monthly_budget_brl": 50.0, "he_alert_threshold_pct": 30.0})
    r = requests.get(f"{BASE_URL}/api/dashboard/overtime/trend?months=3")
    data = r.json()
    alerts = data["alerts"]
    by_id = {a["id"]: a for a in alerts}
    # Pode ou não ter projection_jump (depende do dia atual). Mas budget_exceeded deve estar presente
    # se há HE projetada > 50. Verifica que a projeção é > budget.
    cur = next((s for s in data["series"] if s.get("is_current")), None)
    assert cur is not None
    if cur["projected_paid_brl"] > 50:
        assert "budget_exceeded" in by_id, f"esperava budget_exceeded, alerts={alerts}"
        assert by_id["budget_exceeded"]["level"] == "danger"


def test_trend_budget_close_alert():
    """Budget ~95% da projeção deve gerar budget_close (warning)."""
    r = requests.get(f"{BASE_URL}/api/dashboard/overtime/trend?months=3")
    cur = next((s for s in r.json()["series"] if s.get("is_current")), None)
    proj = cur["projected_paid_brl"]
    if proj <= 0:
        pytest.skip("Sem projeção de HE no mês corrente, não dá para testar budget_close")
    # budget = projeção / 0.95 (faz com que projeção/budget = 0.95, dentro de [0.9, 1.0])
    budget = round(proj / 0.95, 2)
    requests.put(f"{BASE_URL}/api/settings", json={"he_monthly_budget_brl": budget, "he_alert_threshold_pct": 30.0})
    r = requests.get(f"{BASE_URL}/api/dashboard/overtime/trend?months=3")
    data = r.json()
    by_id = {a["id"]: a for a in data["alerts"]}
    assert "budget_close" in by_id, f"esperava budget_close, alerts={data['alerts']}"
    assert by_id["budget_close"]["level"] == "warning"
    assert "budget_exceeded" not in by_id


def test_trend_projection_jump_alert():
    """Quando há HE realizada e projeção > realizado*(1+threshold), deve emitir projection_jump."""
    requests.put(f"{BASE_URL}/api/settings", json={"he_monthly_budget_brl": 0.0, "he_alert_threshold_pct": 30.0})
    r = requests.get(f"{BASE_URL}/api/dashboard/overtime/trend?months=3")
    data = r.json()
    cur = next((s for s in data["series"] if s.get("is_current")), None)
    realized = cur["total_paid_brl"]
    projected = cur["projected_paid_brl"]
    by_id = {a["id"]: a for a in data["alerts"]}
    if realized > 0 and projected > realized * 1.30:
        assert "projection_jump" in by_id
        assert by_id["projection_jump"]["level"] == "warning"


# ---------- Regressão ----------

def test_login_admin_auditor_vando():
    for email, pwd in [("admin@example.com", "admin123"), ("auditor@example.com", "auditor123"), ("vando@example.com", "123456")]:
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pwd})
        assert r.status_code == 200, f"{email} falhou: {r.text}"
        assert r.json().get("access_token")


def test_dashboard_overtime_endpoint_still_works():
    r = requests.get(f"{BASE_URL}/api/dashboard/overtime/trend?months=6")
    assert r.status_code == 200
    data = r.json()
    assert "series" in data and len(data["series"]) >= 1
