"""Tests for can_attend_whatsapp role gating on Collaborator + sync to linked User."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auditor_token():
    return _login("admin@empresa.com", "123456")


@pytest.fixture(scope="module")
def gestor_token():
    return _login("gestor@empresa.com", "123456")


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _new_collab_payload(can_flag=False):
    suf = uuid.uuid4().hex[:6]
    return {
        "name": f"TEST WP {suf}",
        "cpf": f"000.000.{suf[:3]}-{suf[3:5]}",
        "email": f"test_wp_{suf}@example.com",
        "phone": "+55 11 99999-0000",
        "role": "Colaborador de Campo",
        "can_attend_whatsapp": can_flag,
    }


class TestRoleGatingCreate:
    """POST /api/collaborators role gating."""

    def test_gestor_cannot_enable_flag_on_create(self, gestor_token):
        r = requests.post(f"{BASE_URL}/api/collaborators",
                          json=_new_collab_payload(can_flag=True), headers=_hdr(gestor_token))
        assert r.status_code == 200, r.text
        cid = r.json()["id"]
        # Should be silently False
        g = requests.get(f"{BASE_URL}/api/collaborators/{cid}", headers=_hdr(gestor_token))
        assert g.status_code == 200
        assert g.json().get("can_attend_whatsapp") is False, \
            f"gestor was able to set flag on create: {g.json()}"
        # cleanup
        requests.delete(f"{BASE_URL}/api/collaborators/{cid}", headers=_hdr(gestor_token))

    def test_auditor_can_enable_flag_on_create(self, auditor_token):
        r = requests.post(f"{BASE_URL}/api/collaborators",
                          json=_new_collab_payload(can_flag=True), headers=_hdr(auditor_token))
        assert r.status_code == 200, r.text
        cid = r.json()["id"]
        g = requests.get(f"{BASE_URL}/api/collaborators/{cid}", headers=_hdr(auditor_token))
        assert g.status_code == 200
        assert g.json().get("can_attend_whatsapp") is True
        requests.delete(f"{BASE_URL}/api/collaborators/{cid}", headers=_hdr(auditor_token))


class TestRoleGatingUpdate:
    """PUT /api/collaborators/{id} - gestor cannot change flag; auditor can toggle."""

    def test_gestor_cannot_turn_on_flag(self, gestor_token, auditor_token):
        # create as gestor (flag=False)
        c = requests.post(f"{BASE_URL}/api/collaborators",
                          json=_new_collab_payload(False), headers=_hdr(gestor_token)).json()
        cid = c["id"]
        # gestor tries to set true
        upd = _new_collab_payload(True)
        upd["name"] = c["name"]; upd["cpf"] = c["cpf"]; upd["email"] = c["email"]
        r = requests.put(f"{BASE_URL}/api/collaborators/{cid}", json=upd, headers=_hdr(gestor_token))
        assert r.status_code == 200, r.text
        assert r.json().get("can_attend_whatsapp") is False
        requests.delete(f"{BASE_URL}/api/collaborators/{cid}", headers=_hdr(auditor_token))

    def test_gestor_cannot_turn_off_after_auditor_set(self, gestor_token, auditor_token):
        c = requests.post(f"{BASE_URL}/api/collaborators",
                          json=_new_collab_payload(False), headers=_hdr(gestor_token)).json()
        cid = c["id"]
        # auditor enables it
        up = _new_collab_payload(True); up["name"]=c["name"]; up["cpf"]=c["cpf"]; up["email"]=c["email"]
        r1 = requests.put(f"{BASE_URL}/api/collaborators/{cid}", json=up, headers=_hdr(auditor_token))
        assert r1.json().get("can_attend_whatsapp") is True
        # gestor sends false - should stay true
        up2 = _new_collab_payload(False); up2["name"]=c["name"]; up2["cpf"]=c["cpf"]; up2["email"]=c["email"]
        r2 = requests.put(f"{BASE_URL}/api/collaborators/{cid}", json=up2, headers=_hdr(gestor_token))
        assert r2.status_code == 200
        assert r2.json().get("can_attend_whatsapp") is True, "gestor was able to disable flag"
        # auditor turns off
        r3 = requests.put(f"{BASE_URL}/api/collaborators/{cid}", json=up2, headers=_hdr(auditor_token))
        assert r3.json().get("can_attend_whatsapp") is False
        requests.delete(f"{BASE_URL}/api/collaborators/{cid}", headers=_hdr(auditor_token))


class TestSyncWithLinkedUser:
    """When auditor sets flag on collaborator, linked users should mirror it."""

    def test_sync_to_linked_user(self, auditor_token, gestor_token):
        # create collaborator
        c = requests.post(f"{BASE_URL}/api/collaborators",
                          json=_new_collab_payload(False), headers=_hdr(gestor_token)).json()
        cid = c["id"]
        # create user linked to collab
        suf = uuid.uuid4().hex[:6]
        u_payload = {
            "email": f"test_link_{suf}@example.com",
            "password": "test1234",
            "name": "TEST Linked User",
            "role": "gestor",
            "collaborator_id": cid,
        }
        ur = requests.post(f"{BASE_URL}/api/users", json=u_payload, headers=_hdr(auditor_token))
        assert ur.status_code in (200, 201), ur.text
        uid = ur.json().get("id")
        # auditor enables flag on collab
        up = _new_collab_payload(True); up["name"]=c["name"]; up["cpf"]=c["cpf"]; up["email"]=c["email"]
        r = requests.put(f"{BASE_URL}/api/collaborators/{cid}", json=up, headers=_hdr(auditor_token))
        assert r.json().get("can_attend_whatsapp") is True
        # verify user got synced
        users = requests.get(f"{BASE_URL}/api/users", headers=_hdr(auditor_token)).json()
        linked = next((u for u in users if u.get("id") == uid), None)
        assert linked is not None, "linked user not found"
        assert linked.get("can_attend_whatsapp") is True, \
            f"user sync did not propagate: {linked}"
        # cleanup
        if uid:
            requests.delete(f"{BASE_URL}/api/users/{uid}", headers=_hdr(auditor_token))
        requests.delete(f"{BASE_URL}/api/collaborators/{cid}", headers=_hdr(auditor_token))
