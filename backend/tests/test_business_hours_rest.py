"""REST tests for /api/whatsapp-baileys/business-hours endpoints.

Validates:
- GET returns 7-day schedule (keys "0"-"6") + status + after_hours_message
- PUT accepts partial schedule and persists changes
- Auth (role=gestor) required
- Restoration after test
"""
from __future__ import annotations

import os
import copy

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://dual-combine-3.preview.emergentagent.com",
).rstrip("/")

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


@pytest.fixture(scope="module")
def auth_session():
    s = requests.Session()
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    token = data.get("access_token") or data.get("token")
    if token:
        s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def test_get_business_hours_returns_schedule(auth_session):
    r = auth_session.get(
        f"{BASE_URL}/api/whatsapp-baileys/business-hours", timeout=15,
    )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    data = r.json()
    assert "schedule" in data
    assert "tz_offset" in data
    assert "after_hours_message" in data
    assert "status" in data

    # 7 dias (0-6)
    for d in range(7):
        assert str(d) in data["schedule"], f"missing day {d}"

    st = data["status"]
    assert "is_open" in st
    assert "status" in st
    assert "now_iso" in st
    assert "next_open_human" in st or st["is_open"] is True


def test_put_business_hours_persists(auth_session):
    # Backup
    r0 = auth_session.get(
        f"{BASE_URL}/api/whatsapp-baileys/business-hours", timeout=15,
    )
    assert r0.status_code == 200
    original = r0.json()
    orig_payload = {
        "tz_offset": original["tz_offset"],
        "schedule": original["schedule"],
        "after_hours_message": original["after_hours_message"],
    }

    try:
        # Modify: domingo aberto 09:00-12:00
        new_schedule = copy.deepcopy(original["schedule"])
        new_schedule["6"] = {"open": "09:00", "close": "12:00",
                                "active": True}
        marker_msg = "TEST_MARKER_BH msg custom"
        put_payload = {
            "tz_offset": -3,
            "schedule": new_schedule,
            "after_hours_message": marker_msg,
        }
        r1 = auth_session.put(
            f"{BASE_URL}/api/whatsapp-baileys/business-hours",
            json=put_payload,
            timeout=15,
        )
        assert r1.status_code == 200, f"{r1.status_code}: {r1.text}"
        d1 = r1.json()
        assert d1.get("ok") is True
        assert d1["after_hours_message"] == marker_msg
        assert d1["schedule"]["6"]["active"] is True
        assert d1["schedule"]["6"]["open"] == "09:00"

        # GET de novo deve refletir a persistência
        r2 = auth_session.get(
            f"{BASE_URL}/api/whatsapp-baileys/business-hours", timeout=15,
        )
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["after_hours_message"] == marker_msg
        assert d2["schedule"]["6"]["open"] == "09:00"
        assert d2["schedule"]["6"]["close"] == "12:00"
    finally:
        # Restaura
        auth_session.put(
            f"{BASE_URL}/api/whatsapp-baileys/business-hours",
            json=orig_payload,
            timeout=15,
        )


def test_business_hours_requires_auth():
    r = requests.get(
        f"{BASE_URL}/api/whatsapp-baileys/business-hours", timeout=15,
    )
    assert r.status_code in (401, 403), \
        f"expected 401/403 without auth, got {r.status_code}"
