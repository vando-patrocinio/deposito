"""Tests for new timesheet enhancements: full-month grid, PDF download, manual entry, soft delete."""
import os
import calendar
from datetime import date, timedelta

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://selfie-attendance-7.preview.emergentagent.com").rstrip("/")
CID = "col-demo-001"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def ym():
    today = date.today()
    return today.year, today.month


# ---- Timesheet grid ------------------------------------------------------
class TestTimesheetGrid:
    def test_full_month_grid(self, session, ym):
        y, m = ym
        r = session.get(f"{BASE_URL}/api/timesheets/{CID}/{y}/{m}")
        assert r.status_code == 200, r.text
        data = r.json()
        last = calendar.monthrange(y, m)[1]
        assert len(data["days"]) == last, f"expected {last} days, got {len(data['days'])}"
        # required fields
        for d in data["days"]:
            assert "is_future" in d
            assert "is_today" in d
            assert "missing" in d
            assert "date" in d
        # at least one is_today should be True for current month
        today_str = date.today().strftime("%Y-%m-%d")
        today_row = next((d for d in data["days"] if d["date"] == today_str), None)
        assert today_row is not None
        assert today_row["is_today"] is True

    def test_future_days_zeroed(self, session, ym):
        y, m = ym
        r = session.get(f"{BASE_URL}/api/timesheets/{CID}/{y}/{m}")
        data = r.json()
        today_str = date.today().strftime("%Y-%m-%d")
        future_days = [d for d in data["days"] if d["date"] > today_str]
        for d in future_days:
            assert d["is_future"] is True
            assert d["worked"] == 0
            assert d["balance"] == 0
            assert d["status"] == "Futuro"
            assert d["entrada"] is None
            assert d["saida"] is None

    def test_collaborator_404(self, session, ym):
        y, m = ym
        r = session.get(f"{BASE_URL}/api/timesheets/INVALID/{y}/{m}")
        assert r.status_code == 404


# ---- PDF -----------------------------------------------------------------
class TestTimesheetPdf:
    def test_pdf_download(self, session, ym):
        y, m = ym
        r = session.get(f"{BASE_URL}/api/timesheets/{CID}/{y}/{m}/pdf")
        assert r.status_code == 200, r.text
        assert "application/pdf" in r.headers.get("content-type", "")
        assert len(r.content) > 1024, f"PDF too small: {len(r.content)} bytes"
        assert r.content[:4] == b"%PDF", "Invalid PDF magic bytes"


# ---- Manual entry --------------------------------------------------------
class TestManualEntry:
    @pytest.fixture(scope="class")
    def past_date(self):
        # use a past date in current month to avoid future restrictions
        d = date.today() - timedelta(days=2)
        return d.strftime("%Y-%m-%d")

    def test_create_manual_entry(self, session, past_date):
        payload = {
            "collaborator_id": CID,
            "type": "Entrada",
            "date": past_date,
            "time": "08:15",
            "reason": "TEST_manual entry creation",
            "actor": "Gestor",
        }
        r = session.post(f"{BASE_URL}/api/clock-records/manual", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["manually_edited"] is True
        assert data["time"] == "08:15"
        assert data["status"] == "Válido"
        assert data["type"] == "Entrada"
        assert data["date"] == past_date
        assert isinstance(data.get("audit"), list) and len(data["audit"]) >= 1
        assert data["audit"][-1]["reason"] == "TEST_manual entry creation"

    def test_replace_existing_entry(self, session, past_date):
        # Replace the entry created above
        payload = {
            "collaborator_id": CID,
            "type": "Entrada",
            "date": past_date,
            "time": "08:30",
            "reason": "TEST_replacement of time",
            "actor": "Gestor",
        }
        r = session.post(f"{BASE_URL}/api/clock-records/manual", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["time"] == "08:30"
        assert data["manually_edited"] is True
        # audit trail kept and grew
        assert len(data["audit"]) >= 2
        last = data["audit"][-1]
        assert last.get("from_time") == "08:15"
        assert last.get("to_time") == "08:30"

    def test_reason_required(self, session, past_date):
        payload = {
            "collaborator_id": CID,
            "type": "Saída",
            "date": past_date,
            "time": "17:00",
            "reason": "ab",  # too short
        }
        r = session.post(f"{BASE_URL}/api/clock-records/manual", json=payload)
        assert r.status_code == 400

    def test_reason_empty(self, session, past_date):
        payload = {
            "collaborator_id": CID,
            "type": "Saída",
            "date": past_date,
            "time": "17:00",
            "reason": "   ",
        }
        r = session.post(f"{BASE_URL}/api/clock-records/manual", json=payload)
        assert r.status_code == 400

    def test_invalid_type(self, session, past_date):
        payload = {
            "collaborator_id": CID,
            "type": "Almoço",
            "date": past_date,
            "time": "12:00",
            "reason": "TEST_invalid type",
        }
        r = session.post(f"{BASE_URL}/api/clock-records/manual", json=payload)
        assert r.status_code == 400

    def test_invalid_collaborator(self, session, past_date):
        payload = {
            "collaborator_id": "col-does-not-exist",
            "type": "Entrada",
            "date": past_date,
            "time": "08:00",
            "reason": "TEST_invalid collab",
        }
        r = session.post(f"{BASE_URL}/api/clock-records/manual", json=payload)
        assert r.status_code == 404

    def test_timesheet_reflects_manually_edited(self, session, past_date, ym):
        y, m = ym
        r = session.get(f"{BASE_URL}/api/timesheets/{CID}/{y}/{m}")
        assert r.status_code == 200
        data = r.json()
        day_row = next((d for d in data["days"] if d["date"] == past_date), None)
        assert day_row is not None, f"Day {past_date} not found"
        assert day_row.get("manually_edited") is True


# ---- Delete clock record (soft) -----------------------------------------
class TestDeleteRecord:
    def test_delete_marks_as_recusado(self, session):
        # Create a manual record to delete
        past = (date.today() - timedelta(days=3)).strftime("%Y-%m-%d")
        create = session.post(f"{BASE_URL}/api/clock-records/manual", json={
            "collaborator_id": CID,
            "type": "Fim intervalo",
            "date": past,
            "time": "13:00",
            "reason": "TEST_to be deleted",
        })
        assert create.status_code == 200, create.text
        rid = create.json()["id"]

        # Delete it
        d = session.delete(f"{BASE_URL}/api/clock-records/{rid}", params={"reason": "TEST_remove"})
        assert d.status_code == 200, d.text
        assert d.json().get("ok") is True

        # Verify status becomes Recusado + audit entry
        g = session.get(f"{BASE_URL}/api/clock-records/{rid}")
        assert g.status_code == 200
        rec = g.json()
        assert rec["status"] == "Recusado"
        assert rec.get("manually_edited") is True
        actions = [a.get("action") for a in rec.get("audit", [])]
        assert any("Removido" in (a or "") for a in actions)

    def test_delete_invalid_id(self, session):
        r = session.delete(f"{BASE_URL}/api/clock-records/INVALID-ID")
        assert r.status_code == 404
