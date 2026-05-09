"""Tests for Phase 1 features: POST /api/clock-records/manual/batch-fix-schedule.

Validates:
- Creates manual entries for all incomplete weekdays of given month using collaborator schedule
- Skips Saturdays/Sundays/future days
- overwrite_existing=False does not overwrite existing valid entries; True overwrites
- 400 if reason missing or <3 chars
- 404 if collaborator_id does not exist
- Created records have manually_edited=True and audit entry "Criação manual"
"""
import calendar
from datetime import date

import pytest
import requests

# Module: batch fix schedule API


def _create_test_collaborator(api, base_url, suffix=""):
    payload = {
        "name": f"TEST_BatchFix_{suffix}",
        "cpf": f"000.000.000-{suffix[-2:].zfill(2)}",
        "email": f"test_batch_{suffix}@example.com",
        "phone": "+55 11 90000-0000",
        "role": "Colaborador",
        "company": "TEST",
        "schedule": {"entrada": "08:00", "inicio_intervalo": "12:00", "fim_intervalo": "13:00", "saida": "17:00"},
    }
    r = api.post(f"{base_url}/api/collaborators", json=payload)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _delete_collaborator(api, base_url, cid):
    try:
        api.delete(f"{base_url}/api/collaborators/{cid}")
    except Exception:
        pass


def _pick_past_month():
    """Pick a month fully in the past so all weekdays count and no 'future' filtering."""
    today = date.today()
    # use previous month
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


@pytest.fixture(scope="module")
def collab(api, base_url):
    c = _create_test_collaborator(api, base_url, suffix="01")
    yield c
    _delete_collaborator(api, base_url, c["id"])


# ---------- Validation tests ----------


def test_batch_fix_missing_reason_returns_400(api, base_url, collab):
    y, m = _pick_past_month()
    r = api.post(
        f"{base_url}/api/clock-records/manual/batch-fix-schedule",
        json={"collaborator_id": collab["id"], "year": y, "month": m, "reason": ""},
    )
    assert r.status_code == 400
    body = r.json()
    assert "detail" in body


def test_batch_fix_short_reason_returns_400(api, base_url, collab):
    y, m = _pick_past_month()
    r = api.post(
        f"{base_url}/api/clock-records/manual/batch-fix-schedule",
        json={"collaborator_id": collab["id"], "year": y, "month": m, "reason": "ab"},
    )
    assert r.status_code == 400


def test_batch_fix_unknown_collaborator_returns_404(api, base_url):
    y, m = _pick_past_month()
    r = api.post(
        f"{base_url}/api/clock-records/manual/batch-fix-schedule",
        json={"collaborator_id": "DOES_NOT_EXIST_xx", "year": y, "month": m, "reason": "teste valido"},
    )
    assert r.status_code == 404


# ---------- Functional tests ----------


def _count_weekdays_until_today(year, month):
    """Count weekdays (Mon-Fri) in (year,month) that are <= today."""
    last_day = calendar.monthrange(year, month)[1]
    today = date.today()
    count = 0
    for d in range(1, last_day + 1):
        cur = date(year, month, d)
        if cur > today:
            continue
        if cur.weekday() < 5:
            count += 1
    return count


def test_batch_fix_creates_for_all_incomplete_weekdays(api, base_url, collab):
    y, m = _pick_past_month()
    expected_weekdays = _count_weekdays_until_today(y, m)
    expected_created = expected_weekdays * 4  # 4 events per day

    r = api.post(
        f"{base_url}/api/clock-records/manual/batch-fix-schedule",
        json={
            "collaborator_id": collab["id"],
            "year": y,
            "month": m,
            "reason": "Acerto inicial via teste automatizado",
            "actor": "Tester",
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["created_or_updated"] == expected_created, (
        f"Expected {expected_created}, got {data['created_or_updated']}"
    )
    assert len(data["days_affected"]) == expected_weekdays
    # Verify no Saturday/Sunday in days_affected
    for d_str in data["days_affected"]:
        yy, mm, dd = map(int, d_str.split("-"))
        assert date(yy, mm, dd).weekday() < 5, f"{d_str} is weekend!"


def test_batch_fix_skips_saturdays_sundays_and_future(api, base_url, collab):
    """Re-run on same month should skip everything (already filled)."""
    y, m = _pick_past_month()
    # Already filled by previous test
    r = api.post(
        f"{base_url}/api/clock-records/manual/batch-fix-schedule",
        json={
            "collaborator_id": collab["id"],
            "year": y,
            "month": m,
            "reason": "Segunda execucao - deve pular existentes",
            "overwrite_existing": False,
        },
    )
    assert r.status_code == 200
    data = r.json()
    # nothing new created
    assert data["created_or_updated"] == 0
    assert data["skipped"] > 0


def test_batch_fix_records_persisted_with_manual_flag_and_audit(api, base_url, collab):
    """GET timesheet and check that records have manually_edited=True and audit['Criação manual']."""
    y, m = _pick_past_month()
    r = api.get(f"{base_url}/api/timesheets/{collab['id']}/{y}/{m}")
    assert r.status_code == 200
    sheet = r.json()
    # find any record
    found_manual_audit = False
    for d in sheet["days"]:
        for rec in d["records"]:
            if rec.get("manually_edited") is True:
                actions = [a.get("action") for a in (rec.get("audit") or [])]
                if "Criação manual" in actions:
                    found_manual_audit = True
                    break
        if found_manual_audit:
            break
    assert found_manual_audit, "Nenhum registro com manually_edited=True e audit 'Criação manual' encontrado"


def test_batch_fix_overwrite_true_replaces_existing(api, base_url):
    """Create dedicated collaborator for clean overwrite test."""
    coll = _create_test_collaborator(api, base_url, suffix="02")
    cid = coll["id"]
    try:
        y, m = _pick_past_month()
        # First fill
        r = api.post(
            f"{base_url}/api/clock-records/manual/batch-fix-schedule",
            json={"collaborator_id": cid, "year": y, "month": m, "reason": "primeiro fill"},
        )
        assert r.status_code == 200
        first_count = r.json()["created_or_updated"]
        assert first_count > 0

        # Manually change one entry to a different time via /clock-records/manual
        # then overwrite via batch with overwrite_existing=True; expect re-write back to schedule
        last_day = calendar.monthrange(y, m)[1]
        # find first weekday
        first_wd = None
        for d in range(1, last_day + 1):
            if date(y, m, d).weekday() < 5:
                first_wd = d
                break
        d_str = f"{y:04d}-{m:02d}-{first_wd:02d}"
        # change Entrada to 09:30
        r2 = api.post(
            f"{base_url}/api/clock-records/manual",
            json={
                "collaborator_id": cid,
                "type": "Entrada",
                "date": d_str,
                "time": "09:30",
                "reason": "ajuste pontual",
            },
        )
        assert r2.status_code == 200, r2.text

        # Now run batch with overwrite=True
        r3 = api.post(
            f"{base_url}/api/clock-records/manual/batch-fix-schedule",
            json={
                "collaborator_id": cid, "year": y, "month": m,
                "reason": "overwrite forcado para retornar ao horario base",
                "overwrite_existing": True,
            },
        )
        assert r3.status_code == 200
        data = r3.json()
        # since overwrite=True, every weekday-event should be touched
        assert data["created_or_updated"] >= first_count

        # verify Entrada returned to 08:00
        r4 = api.get(f"{base_url}/api/timesheets/{cid}/{y}/{m}")
        sheet = r4.json()
        target_day = next((d for d in sheet["days"] if d["date"] == d_str), None)
        assert target_day is not None
        entrada_rec = next((rec for rec in target_day["records"] if rec["type"] == "Entrada"), None)
        assert entrada_rec is not None
        assert entrada_rec["time"] == "08:00"
    finally:
        _delete_collaborator(api, base_url, cid)


def test_batch_fix_overwrite_false_preserves_existing(api, base_url):
    coll = _create_test_collaborator(api, base_url, suffix="03")
    cid = coll["id"]
    try:
        y, m = _pick_past_month()
        # set Entrada manually to 09:45 BEFORE batch
        last_day = calendar.monthrange(y, m)[1]
        first_wd = next(d for d in range(1, last_day + 1) if date(y, m, d).weekday() < 5)
        d_str = f"{y:04d}-{m:02d}-{first_wd:02d}"
        api.post(
            f"{base_url}/api/clock-records/manual",
            json={"collaborator_id": cid, "type": "Entrada", "date": d_str,
                  "time": "09:45", "reason": "preset"},
        )
        # Run batch with overwrite=False (default)
        r = api.post(
            f"{base_url}/api/clock-records/manual/batch-fix-schedule",
            json={"collaborator_id": cid, "year": y, "month": m,
                  "reason": "preencher faltantes apenas"},
        )
        assert r.status_code == 200
        # Verify entrada kept 09:45
        r2 = api.get(f"{base_url}/api/timesheets/{cid}/{y}/{m}")
        sheet = r2.json()
        target_day = next(d for d in sheet["days"] if d["date"] == d_str)
        entrada_rec = next(rec for rec in target_day["records"] if rec["type"] == "Entrada")
        assert entrada_rec["time"] == "09:45", f"Entrada nao deveria ter sido sobrescrito, got {entrada_rec['time']}"
    finally:
        _delete_collaborator(api, base_url, cid)
