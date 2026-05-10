"""Iteration 30 — Validate Vehicle Checklist DAMAGE MARKS + ATTACHMENTS + AI insights.

Covers:
- POST /api/vehicle-checklist with damage_marks + attachments
- POST /api/vehicle-checklist/{id}/attachment (single upload)
- DELETE /api/vehicle-checklist/{id}/attachment/{idx}
- GET /api/vehicle-checklist/{id}/pdf — must contain extra page (silhouettes + attachments) and stay valid even when an attachment is corrupted
- GET /api/vehicle-checklist/insights/recurrent-defects
"""
from __future__ import annotations

import base64
import io
import os

import pytest
import requests
from PIL import Image

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
ADMIN = {"email": "admin@empresa.com", "password": "123456"}


# ---------- helpers ----------
def _png_data_url(color=(220, 80, 80), size=(220, 140)) -> str:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _bad_data_url() -> str:
    # base64 of "this-is-not-a-real-image" — declared as image/png on purpose
    raw = b"not-an-image-this-is-corrupted-bytes" * 10
    return "data:image/png;base64," + base64.b64encode(raw).decode()


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"Auth failed {r.status_code} {r.text[:120]}")
    token = r.json().get("access_token") or r.json().get("token")
    if not token:
        pytest.skip("No token returned by /api/auth/login")
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def collaborator_id(session):
    r = session.get(f"{BASE_URL}/api/collaborators?limit=1")
    assert r.status_code == 200, r.text
    raw = r.json()
    items = raw if isinstance(raw, list) else (raw.get("items") or [])
    assert items, "No collaborators in DB"
    return items[0]["id"]


# Shared state across tests
STATE = {"chk_id_full": None, "chk_id_corrupt": None, "recurrent_ids": []}


# ------------------------------------------------------------------ #
# 1) Create checklist with 5 damage_marks + 2 attachments
# ------------------------------------------------------------------ #
def test_create_with_marks_and_attachments(session, collaborator_id):
    payload = {
        "collaborator_id": collaborator_id,
        "plate": "TST-I30A",
        "vehicle_brand": "VW",
        "vehicle_model": "Saveiro",
        "items": [
            {"cat": "Pneus e Rodas", "name": "Pressão dos pneus (conforme manual)", "status": "defeito", "notes": "Pneu dianteiro direito baixo"},
            {"cat": "Iluminação", "name": "Faróis (alto e baixo)", "status": "ok"},
        ],
        "damage_marks": [
            {"view": "front", "x": 100, "y": 60, "code": "D", "ord": 1, "notes": "amassado capô"},
            {"view": "rear", "x": 90, "y": 70, "code": "S", "ord": 2, "notes": "risco porta-malas"},
            {"view": "left", "x": 60, "y": 65, "code": "F", "ord": 3, "notes": "retrovisor quebrado"},
            {"view": "right", "x": 140, "y": 65, "code": "V", "ord": 4, "notes": "vidro trincado"},
            {"view": "top", "x": 100, "y": 50, "code": "P", "ord": 5, "notes": "pintura desbotada"},
        ],
        "attachments": [
            {"kind": "photo", "label": "Foto frente", "data_url": _png_data_url((30, 144, 255))},
            {"kind": "paper_checklist", "label": "Checklist papel", "data_url": _png_data_url((50, 200, 50))},
        ],
        "general_notes": "Teste iter30 marcas + anexos",
    }
    r = session.post(f"{BASE_URL}/api/vehicle-checklist", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["plate"] == "TST-I30A"
    assert len(data["damage_marks"]) == 5
    assert len(data["attachments"]) == 2
    # ord must be preserved
    assert sorted(m["ord"] for m in data["damage_marks"]) == [1, 2, 3, 4, 5]
    # all 5 views present
    assert {m["view"] for m in data["damage_marks"]} == {"front", "rear", "left", "right", "top"}
    STATE["chk_id_full"] = data["id"]


# ------------------------------------------------------------------ #
# 2) Append a single attachment via dedicated endpoint
# ------------------------------------------------------------------ #
def test_attachment_post_endpoint(session):
    chk_id = STATE["chk_id_full"]
    payload = {"kind": "photo", "label": "Avaria extra", "data_url": _png_data_url((250, 200, 50))}
    r = session.post(f"{BASE_URL}/api/vehicle-checklist/{chk_id}/attachment", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["attachment"]["label"] == "Avaria extra"
    assert "uploaded_at" in body["attachment"]

    # Verify persistence
    g = session.get(f"{BASE_URL}/api/vehicle-checklist/{chk_id}")
    assert g.status_code == 200
    assert len(g.json()["attachments"]) == 3


# ------------------------------------------------------------------ #
# 3) Delete attachment by index
# ------------------------------------------------------------------ #
def test_attachment_delete_endpoint(session):
    chk_id = STATE["chk_id_full"]
    r = session.delete(f"{BASE_URL}/api/vehicle-checklist/{chk_id}/attachment/0")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert r.json()["remaining"] == 2

    g = session.get(f"{BASE_URL}/api/vehicle-checklist/{chk_id}")
    assert g.status_code == 200
    assert len(g.json()["attachments"]) == 2


def test_attachment_delete_out_of_range(session):
    chk_id = STATE["chk_id_full"]
    r = session.delete(f"{BASE_URL}/api/vehicle-checklist/{chk_id}/attachment/99")
    assert r.status_code == 404


# ------------------------------------------------------------------ #
# 4) PDF generation has multiple pages and contains attachments page
# ------------------------------------------------------------------ #
def test_pdf_with_marks_and_attachments(session):
    chk_id = STATE["chk_id_full"]
    r = session.get(f"{BASE_URL}/api/vehicle-checklist/{chk_id}/pdf")
    assert r.status_code == 200, r.text[:200]
    assert r.headers.get("content-type", "").startswith("application/pdf")
    body = r.content
    assert body[:4] == b"%PDF", "Not a valid PDF"
    # Multi-page (look for /Type /Page entries — at least 2)
    page_count = body.count(b"/Type /Page")
    # ReportLab may write "/Type /Page" or "/Type/Page"
    page_count = max(page_count, body.count(b"/Type/Page"))
    assert page_count >= 2, f"Expected ≥2 pages, got {page_count}"
    # Reasonable size with 2 PNG attachments
    assert len(body) > 15_000, f"PDF too small ({len(body)} bytes)"


# ------------------------------------------------------------------ #
# 5) PDF resilience — corrupted attachment must NOT crash the endpoint
# ------------------------------------------------------------------ #
def test_pdf_resilient_to_corrupted_attachment(session, collaborator_id):
    payload = {
        "collaborator_id": collaborator_id,
        "plate": "TST-I30B",
        "items": [{"cat": "Iluminação", "name": "Faróis (alto e baixo)", "status": "ok"}],
        "damage_marks": [{"view": "front", "x": 100, "y": 60, "code": "D", "ord": 1}],
        "attachments": [
            {"kind": "photo", "label": "Bom", "data_url": _png_data_url((10, 200, 100))},
            {"kind": "photo", "label": "Corrompido", "data_url": _bad_data_url()},
        ],
    }
    r = session.post(f"{BASE_URL}/api/vehicle-checklist", json=payload)
    assert r.status_code == 200, r.text
    chk_id = r.json()["id"]
    STATE["chk_id_corrupt"] = chk_id

    pdf = session.get(f"{BASE_URL}/api/vehicle-checklist/{chk_id}/pdf")
    assert pdf.status_code == 200, pdf.text[:200]
    body = pdf.content
    assert body[:4] == b"%PDF"
    # Should still have multi-page output (2 attachments → 1 valid + 1 placeholder)
    page_count = max(body.count(b"/Type /Page"), body.count(b"/Type/Page"))
    assert page_count >= 2


# ------------------------------------------------------------------ #
# 6) Recurrent defects insights
# ------------------------------------------------------------------ #
def test_recurrent_defects_endpoint(session, collaborator_id):
    # Create 3 checklists on same plate with same defective item
    plate = "TST-RC01"
    item = {"cat": "Iluminação", "name": "Faróis (alto e baixo)", "status": "defeito",
            "notes": "Farol esq apagado"}
    created = []
    for _ in range(3):
        r = session.post(f"{BASE_URL}/api/vehicle-checklist", json={
            "collaborator_id": collaborator_id,
            "plate": plate,
            "items": [item, {"cat": "Iluminação", "name": "Setas / piscas / pisca-alerta", "status": "ok"}],
        })
        assert r.status_code == 200, r.text
        created.append(r.json()["id"])
    STATE["recurrent_ids"] = created

    r = session.get(f"{BASE_URL}/api/vehicle-checklist/insights/recurrent-defects?days=30&min_count=3")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["period_days"] == 30
    assert data["min_count"] == 3
    assert isinstance(data["alerts"], list)
    found = next((a for a in data["alerts"] if a["plate"] == plate), None)
    assert found, f"Plate {plate} not in recurrent alerts: {data}"
    assert found["count"] >= 3
    assert "Faróis" in found["item"]


def test_recurrent_defects_min_count_filter(session):
    # min_count=99 should yield 0 alerts
    r = session.get(f"{BASE_URL}/api/vehicle-checklist/insights/recurrent-defects?days=30&min_count=99")
    assert r.status_code == 200
    assert r.json()["total"] == 0


# ------------------------------------------------------------------ #
# 7) Validation — bad damage mark coords / code
# ------------------------------------------------------------------ #
def test_validation_bad_mark_view(session, collaborator_id):
    r = session.post(f"{BASE_URL}/api/vehicle-checklist", json={
        "collaborator_id": collaborator_id,
        "plate": "TST-VAL1",
        "items": [{"cat": "Iluminação", "name": "Faróis", "status": "ok"}],
        "damage_marks": [{"view": "diagonal", "x": 1, "y": 1, "code": "D", "ord": 1}],
    })
    assert r.status_code == 422


def test_validation_bad_mark_xy(session, collaborator_id):
    r = session.post(f"{BASE_URL}/api/vehicle-checklist", json={
        "collaborator_id": collaborator_id,
        "plate": "TST-VAL2",
        "items": [{"cat": "Iluminação", "name": "Faróis", "status": "ok"}],
        "damage_marks": [{"view": "front", "x": 9999, "y": 1, "code": "D", "ord": 1}],
    })
    assert r.status_code == 422


# ------------------------------------------------------------------ #
# 8) Cleanup
# ------------------------------------------------------------------ #
def test_zz_cleanup(session):
    for cid in [STATE.get("chk_id_full"),
                STATE.get("chk_id_corrupt"),
                *(STATE.get("recurrent_ids") or [])]:
        if cid:
            session.delete(f"{BASE_URL}/api/vehicle-checklist/{cid}")
