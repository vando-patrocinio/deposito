"""
Iteration 6 backend tests — Overtime policy (Banco vs Pago) + Brazilian holidays cache.
Coverage:
  - GET /api/holidays/{year}
  - POST /api/holidays/refresh/{year}
  - GET /api/system/alerts
  - POST /api/collaborators with overtime_policy + city/state
  - GET /api/timesheets/{cid}/{year}/{month} (HE breakdown + holiday day)
  - GET /api/dashboard/overtime/{year}/{month}
"""
import os
import uuid
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path("/app/frontend/.env"))
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
HEADERS = {"Content-Type": "application/json"}

YEAR = 2026
MONTH = 5  # Mai/2026 — contém 01/05 (Dia do Trabalho) e sábado 02/05


# ---------- Holidays ----------
class TestHolidays:
    def test_list_holidays_2026(self):
        r = requests.get(f"{API}/holidays/{YEAR}", timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 13, f"esperava 13 feriados nacionais, veio {len(data)}"
        # 01/05/2026 deve existir e ser Dia do trabalho
        labour = next((h for h in data if h["date"] == "2026-05-01"), None)
        assert labour is not None
        assert "trabalho" in labour["name"].lower()
        assert labour["scope"] == "national"

    def test_refresh_holidays(self):
        r = requests.post(f"{API}/holidays/refresh/{YEAR}", timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["year"] == YEAR
        assert data["count"] == 13
        assert any(h["date"] == "2026-05-01" for h in data["holidays"])

    def test_system_alerts_endpoint_exists(self):
        r = requests.get(f"{API}/system/alerts", timeout=10)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ---------- Collaborator with overtime_policy + city/state ----------
@pytest.fixture(scope="module")
def collab_paid():
    """Cria colaborador com policy=pago, hourly_rate=50."""
    payload = {
        "name": f"TEST_OT_Paid_{uuid.uuid4().hex[:6]}",
        "cpf": f"999.{uuid.uuid4().int % 1000:03d}.{uuid.uuid4().int % 1000:03d}-{uuid.uuid4().int % 100:02d}",
        "email": f"test_ot_paid_{uuid.uuid4().hex[:5]}@example.com",
        "phone": "+55 11 90000-0000",
        "city": "Cachoeiras de Macacu",
        "state": "RJ",
        "overtime_policy": {
            "mode": "pago",
            "hourly_rate_brl": 50.0,
            "weekday_multiplier": 1.5,
            "sunday_multiplier": 2.0,
        },
    }
    r = requests.post(f"{API}/collaborators", json=payload, headers=HEADERS, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    cid = data["id"]
    assert data["city"] == "Cachoeiras de Macacu"
    assert data["state"] == "RJ"
    assert data["overtime_policy"]["mode"] == "pago"
    assert data["overtime_policy"]["hourly_rate_brl"] == 50.0
    yield cid
    requests.delete(f"{API}/collaborators/{cid}", timeout=10)


@pytest.fixture(scope="module")
def collab_banco():
    payload = {
        "name": f"TEST_OT_Banco_{uuid.uuid4().hex[:6]}",
        "cpf": f"888.{uuid.uuid4().int % 1000:03d}.{uuid.uuid4().int % 1000:03d}-{uuid.uuid4().int % 100:02d}",
        "email": f"test_ot_banco_{uuid.uuid4().hex[:5]}@example.com",
        "phone": "+55 11 90000-0001",
        "city": "São Paulo",
        "state": "SP",
        "overtime_policy": {"mode": "banco", "hourly_rate_brl": 0.0},
    }
    r = requests.post(f"{API}/collaborators", json=payload, headers=HEADERS, timeout=15)
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    yield cid
    requests.delete(f"{API}/collaborators/{cid}", timeout=10)


def _manual(cid, ev_type, d, t, reason="seed"):
    return requests.post(
        f"{API}/clock-records/manual",
        json={"collaborator_id": cid, "type": ev_type, "date": d, "time": t, "reason": reason},
        headers=HEADERS,
        timeout=10,
    )


class TestTimesheetOvertime:
    def test_timesheet_holiday_no_work_marks_feriado(self, collab_paid):
        r = requests.get(f"{API}/timesheets/{collab_paid}/{YEAR}/{MONTH}", timeout=20)
        assert r.status_code == 200
        data = r.json()
        # Top-level fields
        for k in (
            "total_overtime_min",
            "total_overtime_weekday_min",
            "total_overtime_sunday_holiday_min",
            "paid_overtime_brl",
            "policy_mode",
            "hourly_rate_brl",
        ):
            assert k in data, f"campo {k} faltando"
        assert data["policy_mode"] == "pago"
        assert data["hourly_rate_brl"] == 50.0

        # Day 01/05/2026 = feriado, sem trabalho
        d_may1 = next(d for d in data["days"] if d["date"] == "2026-05-01")
        assert d_may1["is_holiday"] is True
        assert d_may1["holiday"] is not None
        assert "trabalho" in d_may1["holiday"]["name"].lower()
        assert d_may1["status"] == "Feriado"
        assert d_may1["weekday"] == 4  # 01/05/2026 = sexta-feira

        # Saturday 02/05 must be is_weekend=True
        d_may2 = next(d for d in data["days"] if d["date"] == "2026-05-02")
        assert d_may2["is_weekend"] is True

    def test_overtime_weekday_calc(self, collab_paid):
        # Marcar dia útil (segunda 04/05/2026): 08:00-19:00 com 1h almoço => worked=10h, expected=8h, OT weekday=2h
        d = "2026-05-04"
        for ev, t in [("Entrada", "08:00"), ("Início intervalo", "12:00"), ("Fim intervalo", "13:00"), ("Saída", "19:00")]:
            assert _manual(collab_paid, ev, d, t, reason="test_weekday_ot").status_code == 200

        r = requests.get(f"{API}/timesheets/{collab_paid}/{YEAR}/{MONTH}", timeout=20)
        data = r.json()
        day = next(x for x in data["days"] if x["date"] == d)
        assert day["worked"] == 600  # 10h
        assert day["expected"] == 480  # 8h
        assert day["overtime_min"] == 120
        assert day["overtime_kind"] == "weekday"
        assert day["status"] in ("Extra",)

    def test_overtime_holiday_all_worked_is_overtime(self, collab_paid):
        # 01/05/2026 (feriado) — qualquer hora trabalhada vira HE 100%
        d = "2026-05-01"
        for ev, t in [("Entrada", "09:00"), ("Saída", "13:00")]:
            assert _manual(collab_paid, ev, d, t, reason="test_holiday_ot").status_code == 200
        r = requests.get(f"{API}/timesheets/{collab_paid}/{YEAR}/{MONTH}", timeout=20)
        data = r.json()
        day = next(x for x in data["days"] if x["date"] == d)
        assert day["is_holiday"] is True
        assert day["worked"] == 240  # 4h
        assert day["overtime_min"] == 240
        assert day["overtime_kind"] == "sunday_or_holiday"
        assert day["status"] == "Feriado trabalhado"

    def test_paid_overtime_calculation(self, collab_paid):
        """weekday 120min @ rate 50 * 1.5 = 150; sunday/holiday 240min @ 50 * 2.0 = 400; total=550."""
        r = requests.get(f"{API}/timesheets/{collab_paid}/{YEAR}/{MONTH}", timeout=20)
        data = r.json()
        # totals can include other days from prior iteration test data; we asserted exact two days were inserted now.
        assert data["total_overtime_weekday_min"] >= 120
        assert data["total_overtime_sunday_holiday_min"] >= 240
        # Compute expected from totals to be robust
        expected = round(
            (data["total_overtime_weekday_min"] / 60.0) * 50.0 * 1.5
            + (data["total_overtime_sunday_holiday_min"] / 60.0) * 50.0 * 2.0,
            2,
        )
        assert abs(data["paid_overtime_brl"] - expected) < 0.01

    def test_banco_policy_paid_zero(self, collab_banco):
        # Marcar HE em dia útil
        d = "2026-05-05"
        for ev, t in [("Entrada", "08:00"), ("Início intervalo", "12:00"), ("Fim intervalo", "13:00"), ("Saída", "20:00")]:
            assert _manual(collab_banco, ev, d, t, reason="banco").status_code == 200
        r = requests.get(f"{API}/timesheets/{collab_banco}/{YEAR}/{MONTH}", timeout=20)
        data = r.json()
        assert data["policy_mode"] == "banco"
        assert data["paid_overtime_brl"] == 0.0
        assert data["total_overtime_min"] >= 180  # 3h


# ---------- Dashboard ----------
class TestDashboardOvertime:
    def test_dashboard_overtime_structure(self, collab_paid, collab_banco):
        r = requests.get(f"{API}/dashboard/overtime/{YEAR}/{MONTH}", timeout=30)
        assert r.status_code == 200
        data = r.json()
        for k in ("rows", "top3_overtime", "top3_paid", "total_paid_brl", "total_overtime_min"):
            assert k in data
        # Encontrar nossas linhas
        ids = [r["collaborator_id"] for r in data["rows"]]
        assert collab_paid in ids
        assert collab_banco in ids
        paid_row = next(r for r in data["rows"] if r["collaborator_id"] == collab_paid)
        banco_row = next(r for r in data["rows"] if r["collaborator_id"] == collab_banco)
        assert paid_row["policy_mode"] == "pago"
        assert paid_row["paid_overtime_brl"] > 0
        assert banco_row["policy_mode"] == "banco"
        assert banco_row["paid_overtime_brl"] == 0.0
        # top3_paid só inclui mode=pago
        for t in data["top3_paid"]:
            assert t["policy_mode"] == "pago"
            assert t["paid_overtime_brl"] > 0
        # top3 ordering desc
        ot_vals = [t["total_overtime_min"] for t in data["top3_overtime"]]
        assert ot_vals == sorted(ot_vals, reverse=True)
