"""E2E tests para WhatsApp Config: Business Hours, Quick Images, PDF Export."""
import os
import io
import httpx
import pytest

BACKEND_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
BASE = f"{BACKEND_URL}/api"
LOGIN = {"email": "admin@empresa.com", "password": "123456"}


def _login() -> str:
    r = httpx.post(f"{BASE}/auth/login", json=LOGIN, timeout=15)
    assert r.status_code == 200, r.text
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def token():
    return _login()


@pytest.fixture(scope="module")
def hdr(token):
    return {"Authorization": f"Bearer {token}"}


# ===== BUSINESS HOURS =====
def test_business_hours_get_default(hdr):
    r = httpx.get(f"{BASE}/whatsapp-baileys/business-hours", headers=hdr, timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["enabled"] is True
    assert "weekly_schedule" in data
    assert set(data["weekly_schedule"].keys()) == set("0123456")


def test_business_hours_update(hdr):
    payload = {
        "enabled": True,
        "timezone_offset_hours": -3,
        "weekly_schedule": {
            "0": {"enabled": False, "open": "08:00", "close": "18:00"},
            "1": {"enabled": True, "open": "09:00", "close": "19:00"},
            "2": {"enabled": True, "open": "08:00", "close": "18:00"},
            "3": {"enabled": True, "open": "08:00", "close": "18:00"},
            "4": {"enabled": True, "open": "08:00", "close": "18:00"},
            "5": {"enabled": True, "open": "08:00", "close": "18:00"},
            "6": {"enabled": True, "open": "08:00", "close": "13:00"},
        },
        "holidays": ["2026-12-25", "2026-01-01"],
        "fora_de_hora_message": "Estamos fechados, retornaremos em breve.",
    }
    r = httpx.put(f"{BASE}/whatsapp-baileys/business-hours",
                   json=payload, headers=hdr, timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["config"]["weekly_schedule"]["1"]["open"] == "09:00"
    assert "2026-12-25" in data["config"]["holidays"]
    assert "is_outside_now" in data


def test_business_hours_invalid_holiday(hdr):
    payload = {
        "enabled": True,
        "weekly_schedule": {
            str(i): {"enabled": True, "open": "08:00", "close": "18:00"} for i in range(7)
        },
        "holidays": ["bad-date"],
    }
    r = httpx.put(f"{BASE}/whatsapp-baileys/business-hours",
                   json=payload, headers=hdr, timeout=10)
    assert r.status_code == 400


# ===== QUICK IMAGES =====
def test_quick_images_list(hdr):
    r = httpx.get(f"{BASE}/whatsapp-baileys/quick-images", headers=hdr, timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert data["max"] == 5
    assert isinstance(data["items"], list)


def test_quick_images_upload_and_delete(hdr, token):
    # Create a tiny valid PNG (1x1 transparent)
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6300010000000500017a3decb50000000049454e44ae426082"
    )
    files = {"file": ("test.png", png_bytes, "image/png")}
    data = {"label": "Teste pytest"}
    r = httpx.post(f"{BASE}/whatsapp-baileys/quick-images",
                    files=files, data=data, headers=hdr, timeout=10)
    assert r.status_code == 200, r.text
    created = r.json()
    img_id = created["id"]
    assert created["label"] == "Teste pytest"
    assert created["url"] == f"/api/whatsapp-baileys/quick-images/{img_id}/file"

    # Download via URL (token via query)
    r2 = httpx.get(f"{BACKEND_URL}{created['url']}?t={token}", timeout=10)
    assert r2.status_code == 200
    assert r2.content[:4] == b"\x89PNG"

    # Cleanup
    r3 = httpx.delete(f"{BASE}/whatsapp-baileys/quick-images/{img_id}",
                       headers=hdr, timeout=10)
    assert r3.status_code == 200


def test_quick_images_max_5(hdr):
    # Lista quantas já tem
    r = httpx.get(f"{BASE}/whatsapp-baileys/quick-images", headers=hdr, timeout=10)
    existing = len(r.json()["items"])
    if existing >= 5:
        # Tenta criar mais — deve falhar
        png_bytes = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c6300010000000500017a3decb50000000049454e44ae426082"
        )
        r2 = httpx.post(f"{BASE}/whatsapp-baileys/quick-images",
                         files={"file": ("x.png", png_bytes, "image/png")},
                         headers=hdr, timeout=10)
        assert r2.status_code == 400
        assert "Limite" in r2.json().get("detail", "")


# ===== PDF EXPORT =====
def test_pdf_export(hdr, token):
    # Pega uma conversa real
    r = httpx.get(f"{BASE}/whatsapp-baileys/conversations", headers=hdr, timeout=15)
    assert r.status_code == 200
    items = r.json().get("items", [])
    if not items:
        pytest.skip("Nenhuma conversa disponível")
    phone = items[0]["phone"]

    r2 = httpx.post(f"{BASE}/whatsapp-baileys/conversation/{phone}/export-pdf",
                     headers=hdr, timeout=30)
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["ok"] is True
    assert data["document"]["type"] == "wa_transcript"
    assert data["document"]["phone"] == phone
    assert data["message_count"] > 0
    assert data["download_url"].startswith("/api/whatsapp-baileys/transcripts/")

    # Download PDF e valida header
    r3 = httpx.get(f"{BACKEND_URL}{data['download_url']}?t={token}", timeout=15)
    assert r3.status_code == 200
    assert r3.content[:4] == b"%PDF"


def test_pdf_export_404(hdr):
    r = httpx.post(f"{BASE}/whatsapp-baileys/conversation/nonexistent12345/export-pdf",
                    headers=hdr, timeout=15)
    assert r.status_code == 404
