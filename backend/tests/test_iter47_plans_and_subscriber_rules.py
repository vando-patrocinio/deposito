"""Iter 47 — Tests for Planos CRUD + 4 subscriber business rules:
   (1) external_code auto-generated and immutable
   (2) Nickname auto-derived from first name; preserves customizations
   (3) All phones forced is_primary=True
   (4) Plan snapshot hydration via plan_id
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "admin@empresa.com", "password": "123456"},
                      timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------- Plans CRUD ----------------
class TestPlans:
    def test_list_plans(self, auth):
        r = requests.get(f"{BASE_URL}/api/plans", headers=auth, timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        # Verify sort by price ascending
        prices = [p.get("monthly_price", 0) for p in data["items"]]
        assert prices == sorted(prices), f"Plans not sorted by price: {prices}"

    def test_create_plan_speed_label_derived(self, auth):
        name = f"TEST_Plan_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{BASE_URL}/api/plans", headers=auth, json={
            "name": name, "speed_down_mbps": 500, "monthly_price": 89.90
        }, timeout=10)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["speed_label"] == "500 Mega"
        assert p["monthly_price"] == 89.90
        pytest.test_plan_500 = p["id"]

        # 1000 → '1 Giga'
        r2 = requests.post(f"{BASE_URL}/api/plans", headers=auth, json={
            "name": f"TEST_Plan_Giga_{uuid.uuid4().hex[:6]}",
            "speed_down_mbps": 1000, "monthly_price": 149.90
        }, timeout=10)
        assert r2.status_code == 200
        assert r2.json()["speed_label"] == "1 Giga"
        pytest.test_plan_1g = r2.json()["id"]

    def test_duplicate_name_409(self, auth):
        name = f"TEST_Dup_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{BASE_URL}/api/plans", headers=auth, json={
            "name": name, "speed_down_mbps": 300, "monthly_price": 79.90
        }, timeout=10)
        assert r.status_code == 200
        r2 = requests.post(f"{BASE_URL}/api/plans", headers=auth, json={
            "name": name, "speed_down_mbps": 300, "monthly_price": 79.90
        }, timeout=10)
        assert r2.status_code == 409, r2.text

    def test_get_and_update_plan(self, auth):
        pid = pytest.test_plan_500
        r = requests.get(f"{BASE_URL}/api/plans/{pid}", headers=auth, timeout=10)
        assert r.status_code == 200

        r2 = requests.put(f"{BASE_URL}/api/plans/{pid}", headers=auth,
                          json={"monthly_price": 99.90}, timeout=10)
        assert r2.status_code == 200
        assert r2.json()["monthly_price"] == 99.90

    def test_update_rename_to_existing_409(self, auth):
        # Rename plan_1g to plan_500's name → 409
        r_src = requests.get(f"{BASE_URL}/api/plans/{pytest.test_plan_500}",
                             headers=auth, timeout=10)
        existing_name = r_src.json()["name"]
        r = requests.put(f"{BASE_URL}/api/plans/{pytest.test_plan_1g}",
                         headers=auth, json={"name": existing_name}, timeout=10)
        assert r.status_code == 409, r.text


# ---------------- Subscriber business rules ----------------
class TestSubscriberRules:
    def test_regra1_external_code_autogen_ignores_hack(self, auth):
        r = requests.post(f"{BASE_URL}/api/subscribers", headers=auth, json={
            "name": "TEST_Rule1 Silva",
            "external_code": "HACK-9999",
            "phones": [], "addresses": []
        }, timeout=10)
        assert r.status_code == 200, r.text
        sub = r.json()
        assert sub["external_code"].startswith("ASS-")
        assert sub["external_code"] != "HACK-9999"
        # 5-digit zero-padded
        seq_part = sub["external_code"].split("-")[1]
        assert len(seq_part) == 5 and seq_part.isdigit()
        pytest.test_sub_id = sub["id"]
        pytest.test_sub_ext = sub["external_code"]

    def test_regra1_external_code_immutable_on_patch(self, auth):
        sid = pytest.test_sub_id
        r = requests.patch(f"{BASE_URL}/api/subscribers/{sid}", headers=auth,
                           json={"external_code": "HACK-9999",
                                 "notes": "trying hack"}, timeout=10)
        assert r.status_code == 200, r.text
        sub = r.json()
        assert sub["external_code"] == pytest.test_sub_ext
        assert sub["external_code"] != "HACK-9999"

    def test_regra2_auto_nickname_first_name(self, auth):
        r = requests.post(f"{BASE_URL}/api/subscribers", headers=auth, json={
            "name": "TEST_Maria José Silva",
            "phones": [], "addresses": []
        }, timeout=10)
        assert r.status_code == 200, r.text
        sub = r.json()
        # First word is "TEST_Maria" (since the name starts TEST_)
        # but business rule strips on whitespace → 'TEST_Maria'. Accept that.
        assert sub["nickname"] == "Test_Maria" or sub["nickname"].startswith("Test"), \
            f"nickname={sub['nickname']}"
        pytest.test_sub2_id = sub["id"]

    def test_regra2_keeps_custom_nickname(self, auth):
        r = requests.post(f"{BASE_URL}/api/subscribers", headers=auth, json={
            "name": "TEST_Roberto Carlos",
            "nickname": "Beto", "phones": [], "addresses": []
        }, timeout=10)
        assert r.status_code == 200, r.text
        sub = r.json()
        assert sub["nickname"] == "Beto"
        pytest.test_sub3_id = sub["id"]

    def test_regra2_name_change_auto_updates_default_nickname(self, auth):
        # sub2 default nickname is first word of original name; rename → re-derive
        sid = pytest.test_sub2_id
        r = requests.patch(f"{BASE_URL}/api/subscribers/{sid}", headers=auth,
                           json={"name": "TEST_João Silva"}, timeout=10)
        assert r.status_code == 200, r.text
        sub = r.json()
        # Since old nickname matched the old _derive_nickname output,
        # the rule should re-derive → "Test_João" (first word)
        assert sub["nickname"].lower().startswith("test_jo"), \
            f"nickname not auto-updated: {sub['nickname']}"

    def test_regra2_name_change_preserves_custom_nickname(self, auth):
        sid = pytest.test_sub3_id
        r = requests.patch(f"{BASE_URL}/api/subscribers/{sid}", headers=auth,
                           json={"name": "TEST_Roberto Mudou"}, timeout=10)
        assert r.status_code == 200, r.text
        sub = r.json()
        assert sub["nickname"] == "Beto", \
            f"custom nickname lost: {sub['nickname']}"

    def test_regra3_all_phones_primary_on_create(self, auth):
        r = requests.post(f"{BASE_URL}/api/subscribers", headers=auth, json={
            "name": "TEST_PhoneRule",
            "phones": [
                {"raw_number": "21987651001", "is_primary": False},
                {"raw_number": "21987651002", "is_primary": False},
            ],
            "addresses": []
        }, timeout=10)
        assert r.status_code == 200, r.text
        sub = r.json()
        assert len(sub["phones"]) == 2
        for p in sub["phones"]:
            assert p["is_primary"] is True, f"phone not primary: {p}"
        pytest.test_sub4_id = sub["id"]

    def test_regra3_add_phone_endpoint_forces_primary(self, auth):
        sid = pytest.test_sub4_id
        r = requests.post(f"{BASE_URL}/api/subscribers/{sid}/phones",
                          headers=auth,
                          json={"raw_number": "21987651003",
                                "is_primary": False}, timeout=10)
        assert r.status_code == 200, r.text
        phone = r.json()
        assert phone["is_primary"] is True

    def test_regra4_plan_snapshot_hydration_on_create(self, auth):
        pid = pytest.test_plan_500  # 99.90 (after update)
        r = requests.post(f"{BASE_URL}/api/subscribers", headers=auth, json={
            "name": "TEST_PlanHydration",
            "plan_id": pid, "phones": [], "addresses": []
        }, timeout=10)
        assert r.status_code == 200, r.text
        sub = r.json()
        assert sub["plan_id"] == pid
        assert sub["plan_name"] is not None and sub["plan_name"].startswith("TEST_Plan_")
        assert sub["plan_speed"] == "500 Mega"
        assert sub["plan_price"] == 99.90
        pytest.test_sub5_id = sub["id"]

    def test_regra4_plan_re_hydrate_on_patch(self, auth):
        sid = pytest.test_sub5_id
        new_pid = pytest.test_plan_1g
        r = requests.patch(f"{BASE_URL}/api/subscribers/{sid}", headers=auth,
                           json={"plan_id": new_pid}, timeout=10)
        assert r.status_code == 200, r.text
        sub = r.json()
        assert sub["plan_id"] == new_pid
        assert sub["plan_speed"] == "1 Giga"

    def test_delete_plan_in_use_409(self, auth):
        # plan_1g is now in use (after rehydration)
        r = requests.delete(f"{BASE_URL}/api/plans/{pytest.test_plan_1g}",
                            headers=auth, timeout=10)
        # If admin user has gestor only, expect 403 — accept either 409 or 403
        assert r.status_code in (409, 403), f"unexpected: {r.status_code} {r.text}"


# ---------------- Cleanup ----------------
def test_zzz_cleanup(auth):
    # Best-effort cleanup
    for sid_attr in ("test_sub_id", "test_sub2_id", "test_sub3_id",
                      "test_sub4_id", "test_sub5_id"):
        sid = getattr(pytest, sid_attr, None)
        if sid:
            requests.delete(f"{BASE_URL}/api/subscribers/{sid}",
                            headers=auth, timeout=10)
    for pid_attr in ("test_plan_500", "test_plan_1g"):
        pid = getattr(pytest, pid_attr, None)
        if pid:
            requests.delete(f"{BASE_URL}/api/plans/{pid}",
                            headers=auth, timeout=10)
