"""Iteration 143 — ONT Label Scanner + retirada move-on-create.

Tests for:
1. POST /api/stok/retirada/scan-ont (Claude 4.6 vision OCR of MAC/SN)
2. _move_ont_for_withdraw via POST /api/stok/services/{id}/close — paths:
   a. MAC not in stok_onts -> create new doc, location=tecnico, status=retirada_com_tecnico, source=ai_scan_retirada
   b. MAC in wrong location -> force move + withdraw_inconsistency=true
   c. MAC at the right client -> normal flow, moves to technician
"""
from __future__ import annotations

import base64
import io
import os
import uuid

import pytest
import requests
from PIL import Image, ImageDraw

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL is required"

CREDS = {"email": "gestor@empresa.com", "password": "123456"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def token() -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login", json=CREDS, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def technician_id(auth_headers) -> str:
    """Pick any collaborator id from /api/collaborators to act as technician."""
    r = requests.get(f"{BASE_URL}/api/collaborators", headers=auth_headers, timeout=30)
    assert r.status_code == 200, f"collaborators list failed: {r.text}"
    colabs = r.json()
    assert colabs, "no collaborators present in demo company"
    return colabs[0]["id"]


def _png_label_b64(mac_text: str = "1A:2B:3C:4D:5E:6F",
                    sn_text: str = "HWTC98765432") -> str:
    img = Image.new("RGB", (800, 400), "white")
    draw = ImageDraw.Draw(img)
    # Big readable text — no system font dependency
    draw.text((40, 80),  f"MAC: {mac_text}", fill="black")
    draw.text((40, 160), f"S/N: {sn_text}", fill="black")
    draw.text((40, 240), "ONT Huawei HG6145", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _create_retirada_service(auth_headers, technician_id, client_id=None):
    """Create a stok_service of type=retirada; returns service dict."""
    cid = client_id or f"cli-test-{uuid.uuid4().hex[:6]}"
    payload = {
        "type": "retirada",
        "client_id": cid,
        "client_name": f"TEST_Client_{cid[:10]}",
        "technician_id": technician_id,
        "reason": "iter143 test",
    }
    r = requests.post(f"{BASE_URL}/api/stok/services",
                       headers=auth_headers, json=payload, timeout=30)
    assert r.status_code in (200, 201), f"create service failed: {r.status_code} {r.text}"
    return r.json()


# ---------------------------------------------------------------------------
# 1) /scan-ont — happy path
# ---------------------------------------------------------------------------
class TestScanOntEndpoint:
    def test_scan_ont_happy_path_claude_vision(self, auth_headers):
        """Synthetic PNG with MAC + SN → Claude returns normalized values."""
        b64 = _png_label_b64("1A:2B:3C:4D:5E:6F", "HWTC98765432")
        r = requests.post(
            f"{BASE_URL}/api/stok/retirada/scan-ont",
            headers=auth_headers,
            json={"image_base64": b64, "hint": "ONT Huawei"},
            timeout=120,
        )
        assert r.status_code == 200, f"scan-ont failed: {r.status_code} {r.text}"
        data = r.json()
        # Schema checks
        for k in ("ok", "mac", "sn", "confidence"):
            assert k in data, f"missing key {k} in {data}"
        # mac normalized AA:BB:CC:DD:EE:FF, uppercased
        assert data["mac"] == "1A:2B:3C:4D:5E:6F", f"mac mismatch: {data['mac']}"
        assert data["sn"] == "HWTC98765432", f"sn mismatch: {data['sn']}"
        assert isinstance(data["confidence"], (int, float))
        assert 0.0 <= float(data["confidence"]) <= 1.0
        assert data["ok"] is True

    def test_scan_ont_invalid_base64(self, auth_headers):
        """Garbage base64 → 400 'Imagem base64 inválida'."""
        bad = "!!!!@@@@####$$$%%%%^^^&&&((((not_base64_at_all))))" * 5
        r = requests.post(
            f"{BASE_URL}/api/stok/retirada/scan-ont",
            headers=auth_headers,
            json={"image_base64": bad},
            timeout=30,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"
        body = r.json()
        msg = str(body.get("detail") or body.get("message") or body)
        assert "base64" in msg.lower() or "inv" in msg.lower(), f"unexpected error: {body}"

    def test_scan_ont_too_short_payload_pydantic(self, auth_headers):
        """min_length=100 → 422 from Pydantic."""
        r = requests.post(
            f"{BASE_URL}/api/stok/retirada/scan-ont",
            headers=auth_headers,
            json={"image_base64": "abc123"},
            timeout=30,
        )
        assert r.status_code == 422, f"expected 422 from pydantic, got {r.status_code} {r.text}"

    def test_scan_ont_requires_auth(self):
        """No Bearer → 401/403."""
        b64 = _png_label_b64()
        r = requests.post(
            f"{BASE_URL}/api/stok/retirada/scan-ont",
            headers={"Content-Type": "application/json"},
            json={"image_base64": b64},
            timeout=30,
        )
        # 401 expected (some FastAPI deps return 403; accept either)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code} {r.text}"


# ---------------------------------------------------------------------------
# 2) _move_ont_for_withdraw via /services/{id}/close
# ---------------------------------------------------------------------------
class TestMoveOntForWithdraw:
    def test_close_retirada_creates_new_ont_when_mac_unknown(
        self, auth_headers, technician_id,
    ):
        """MAC not in stok_onts -> creates new doc on the technician."""
        # Pick a fresh MAC that surely does not exist
        new_mac = ":".join([f"{(ord('A')+i)%256:02X}" for i in range(6)])  # AA:BB:CC:DD:EE:FF
        new_mac = "BE:EF:CA:FE:" + ":".join(uuid.uuid4().hex[:4].upper()[i:i+2] for i in (0, 2))
        # Make sure new_mac normalized matches strip+upper
        new_mac = new_mac.upper()

        # Confirm it's not present already
        r0 = requests.get(f"{BASE_URL}/api/stok/onts", headers=auth_headers, timeout=30)
        assert r0.status_code == 200
        existing = {o.get("mac") for o in r0.json()}
        assert new_mac not in existing, "test MAC must not pre-exist"

        svc = _create_retirada_service(auth_headers, technician_id)
        sid = svc["id"]

        close_body = {
            "ont_mac": new_mac,
            "used_items": [],
            "tag": "retirada",
        }
        r = requests.post(
            f"{BASE_URL}/api/stok/services/{sid}/close",
            headers=auth_headers, json=close_body, timeout=60,
        )
        assert r.status_code == 200, f"close failed: {r.status_code} {r.text}"
        assert r.json().get("ok") is True

        # Verify ONT was created and is on the technician
        r1 = requests.get(f"{BASE_URL}/api/stok/onts", headers=auth_headers, timeout=30)
        assert r1.status_code == 200
        ont = next((o for o in r1.json() if o.get("mac") == new_mac), None)
        assert ont is not None, f"new ONT not found after close (mac={new_mac})"
        assert ont["location_type"] == "tecnico", f"location_type={ont['location_type']}"
        assert ont["location_id"] == technician_id
        assert ont["status"] == "retirada_com_tecnico"
        assert ont.get("source") == "ai_scan_retirada"

    def test_close_retirada_mac_at_wrong_location_marks_inconsistency(
        self, auth_headers, technician_id,
    ):
        """MAC exists but on wrong client → force move + withdraw_inconsistency=true."""
        # Seed an ONT at empresa (warehouse) — wrong location for retirada
        mac = "AA:11:22:33:44:" + uuid.uuid4().hex[:2].upper()
        seed_payload = {"macs": [mac], "model": "TestModel"}
        r_seed = requests.post(
            f"{BASE_URL}/api/stok/onts/bulk", headers=auth_headers, json=seed_payload, timeout=30,
        )
        assert r_seed.status_code in (200, 201), f"seed ont failed: {r_seed.status_code} {r_seed.text}"

        svc = _create_retirada_service(auth_headers, technician_id, client_id="cli-different-xyz")
        sid = svc["id"]

        close_body = {"ont_mac": mac, "used_items": [], "tag": "retirada"}
        r = requests.post(
            f"{BASE_URL}/api/stok/services/{sid}/close",
            headers=auth_headers, json=close_body, timeout=60,
        )
        assert r.status_code == 200, f"close failed: {r.status_code} {r.text}"

        r1 = requests.get(f"{BASE_URL}/api/stok/onts", headers=auth_headers, timeout=30)
        ont = next((o for o in r1.json() if o.get("mac") == mac), None)
        assert ont is not None, "ONT disappeared"
        assert ont["location_type"] == "tecnico"
        assert ont["location_id"] == technician_id
        assert ont["status"] == "retirada_com_tecnico"
        assert ont.get("withdraw_inconsistency") is True, f"missing inconsistency flag: {ont}"

    def test_close_retirada_mac_at_right_client_moves_to_tech(
        self, auth_headers, technician_id,
    ):
        """MAC already at the correct client → original flow (move client→tech)."""
        mac = "C0:FF:EE:00:11:" + uuid.uuid4().hex[:2].upper()
        client_id = f"cli-correct-{uuid.uuid4().hex[:6]}"
        client_name = f"TEST_Client_Correct_{client_id[:10]}"

        # Seed ONT directly at the client by creating service of type instalacao? Simpler:
        # Use bulk create then transfer to tech then close install. But easier: create at empresa
        # then manually transfer via existing endpoint to client.  Use stok internal helper
        # via the install close flow. Simpler still: just bulk-insert at empresa, then use the
        # admin "transfer" endpoint. We'll fall back to inserting via service flow:
        # create ONT at empresa
        r_seed = requests.post(
            f"{BASE_URL}/api/stok/onts/bulk", headers=auth_headers,
            json={"macs": [mac], "model": "TestModel"}, timeout=30,
        )
        assert r_seed.status_code in (200, 201), r_seed.text

        # transfer to technician
        r_xfer = requests.post(
            f"{BASE_URL}/api/stok/onts/transfer-to-tech",
            headers=auth_headers,
            json={"mac": mac, "technician_id": technician_id},
            timeout=30,
        )
        assert r_xfer.status_code == 200, f"transfer-to-tech failed: {r_xfer.text}"

        # 2. open instalacao service and close to put ONT at client
        inst_payload = {
            "type": "instalacao",
            "client_id": client_id,
            "client_name": client_name,
            "technician_id": technician_id,
        }
        r_inst = requests.post(f"{BASE_URL}/api/stok/services",
                                headers=auth_headers, json=inst_payload, timeout=30)
        assert r_inst.status_code in (200, 201), r_inst.text
        inst_id = r_inst.json()["id"]
        r_close_inst = requests.post(
            f"{BASE_URL}/api/stok/services/{inst_id}/close",
            headers=auth_headers,
            json={"ont_mac": mac, "used_items": [], "tag": "instalacao"},
            timeout=60,
        )
        assert r_close_inst.status_code == 200, r_close_inst.text

        # Now open retirada and close to test client→tech move
        svc = _create_retirada_service(auth_headers, technician_id, client_id=client_id)
        sid = svc["id"]
        r_close = requests.post(
            f"{BASE_URL}/api/stok/services/{sid}/close",
            headers=auth_headers,
            json={"ont_mac": mac, "used_items": [], "tag": "retirada"},
            timeout=60,
        )
        assert r_close.status_code == 200, f"close retirada failed: {r_close.text}"

        # Verify ONT is back to technician with retirada status, no inconsistency
        r_list = requests.get(f"{BASE_URL}/api/stok/onts", headers=auth_headers, timeout=30)
        ont = next((o for o in r_list.json() if o.get("mac") == mac), None)
        assert ont is not None
        assert ont["location_type"] == "tecnico"
        assert ont["location_id"] == technician_id
        assert ont["status"] == "retirada_com_tecnico"
        assert ont.get("withdraw_inconsistency") in (None, False), \
            f"unexpected inconsistency flag for clean flow: {ont}"
