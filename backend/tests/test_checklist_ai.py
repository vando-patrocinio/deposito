"""Iter55 — Checklist AI endpoints (4 IA features).

- POST  /api/vehicle-checklist/ai/{chk_id}/analyze-damage
- GET   /api/vehicle-checklist/ai/recurrent-insights
- POST  /api/vehicle-checklist/ai/ocr-paper
- GET   /api/vehicle-checklist/ai/collaborator-health/{cid}
"""
import base64
import io
import os
import pytest
import requests
from PIL import Image, ImageDraw, ImageFont

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PWD = "123456"


# ---------- helpers ----------
@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PWD}, timeout=30)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    j = r.json()
    tok = j.get("access_token") or j.get("token")
    assert tok, f"no access_token in response: {j}"
    return tok


@pytest.fixture(scope="session")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _png_with_text(text: str = "TEST PLATE ABC-1D23 KM 12345") -> str:
    """Generate a real PNG with visual features (text + lines) — not solid color."""
    img = Image.new("RGB", (480, 240), (245, 245, 245))
    d = ImageDraw.Draw(img)
    # draw text & lines so it's not uniform
    d.rectangle([10, 10, 470, 230], outline=(0, 0, 0), width=3)
    for y in (60, 110, 160, 200):
        d.line([(20, y), (460, y)], fill=(120, 120, 120), width=1)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
    except Exception:
        font = ImageFont.load_default()
    d.text((25, 25), "CHECKLIST VEICULAR", fill=(0, 0, 0), font=font)
    d.text((25, 70), text, fill=(20, 20, 20), font=font)
    d.text((25, 120), "[X] CRLV atualizado", fill=(0, 100, 0), font=font)
    d.text((25, 170), "[X] Pneus pressao OK", fill=(0, 100, 0), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


# ---------- 1) recurrent-insights (cheap, no images) ----------
class TestRecurrentInsights:
    def test_recurrent_insights_basic(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/vehicle-checklist/ai/recurrent-insights",
            params={"days": 60, "min_count": 2},
            headers=headers, timeout=60,
        )
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:300]}"
        data = r.json()
        assert "period_days" in data and data["period_days"] == 60
        assert "min_count" in data and data["min_count"] == 2
        assert "alerts" in data and isinstance(data["alerts"], list)
        assert "ai" in data and isinstance(data["ai"], dict)
        ai = data["ai"]
        assert "summary" in ai
        assert "bullets" in ai
        # top_priority pode ser None
        assert "top_priority" in ai

    def test_recurrent_insights_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/vehicle-checklist/ai/recurrent-insights",
                         params={"days": 30, "min_count": 3}, timeout=15)
        assert r.status_code in (401, 403)


# ---------- 2) collaborator-health ----------
class TestCollaboratorHealth:
    def test_health_diogo(self, headers):
        cid = "col-30aafc3c"
        r = requests.get(
            f"{BASE_URL}/api/vehicle-checklist/ai/collaborator-health/{cid}",
            params={"days": 60}, headers=headers, timeout=60,
        )
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:300]}"
        data = r.json()
        assert "collaborator" in data and data["collaborator"]
        assert data["period_days"] == 60
        assert "history_count" in data and isinstance(data["history_count"], int)
        assert "ai" in data
        ai = data["ai"]
        # campos esperados
        for k in ("score", "status", "summary", "trend", "open_critical", "next_action"):
            assert k in ai, f"missing key {k} in ai: {ai}"
        # status deve ser uma das 3 categorias (ou seja, IA respondeu corretamente)
        assert ai["status"] in ("bom", "atenção", "atencao", "crítico", "critico"), f"status={ai['status']}"

    def test_health_not_found(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/vehicle-checklist/ai/collaborator-health/col-DOES-NOT-EXIST",
            params={"days": 60}, headers=headers, timeout=15,
        )
        assert r.status_code == 404


# ---------- 3) analyze-damage ----------
class TestAnalyzeDamage:
    def _find_chk_with_photo(self, headers):
        r = requests.get(f"{BASE_URL}/api/vehicle-checklist",
                         params={"limit": 30}, headers=headers, timeout=30)
        assert r.status_code == 200, r.text[:300]
        items = r.json() if isinstance(r.json(), list) else r.json().get("items") or []
        for it in items:
            atts = it.get("attachments") or []
            for idx, a in enumerate(atts):
                du = a.get("data_url") or ""
                if du.startswith("data:image/jpeg") or du.startswith("data:image/png") or du.startswith("data:image/webp"):
                    return it.get("id"), idx
        return None, None

    def test_analyze_damage(self, headers):
        chk_id, idx = self._find_chk_with_photo(headers)
        if not chk_id:
            pytest.skip("no checklist with JPEG/PNG attachment in DB")
        r = requests.post(
            f"{BASE_URL}/api/vehicle-checklist/ai/{chk_id}/analyze-damage",
            json={"attachment_indices": [idx]}, headers=headers, timeout=120,
        )
        # 502 aceitável (IA pode dar formato inválido), 500 NÃO é aceitável
        assert r.status_code != 500, f"500 server error: {r.text[:300]}"
        assert r.status_code in (200, 502), f"unexpected {r.status_code}: {r.text[:300]}"
        if r.status_code == 200:
            data = r.json()
            assert "analysis" in data
            an = data["analysis"]
            assert "id" in an and "result" in an
            res = an["result"]
            assert "items" in res and isinstance(res["items"], list) and len(res["items"]) >= 1
            assert "overall" in res
            assert "max_severity" in res

    def test_analyze_damage_404(self, headers):
        r = requests.post(
            f"{BASE_URL}/api/vehicle-checklist/ai/vchk-DOES-NOT-EXIST/analyze-damage",
            json={"attachment_indices": [0]}, headers=headers, timeout=15,
        )
        assert r.status_code == 404


# ---------- 4) ocr-paper ----------
class TestOcrPaper:
    def test_ocr_paper(self, headers):
        png = _png_with_text()
        payload = {
            "image_data_url": png,
            "template_items": ["CRLV atualizado", "Pneus pressão", "Faróis"],
        }
        r = requests.post(f"{BASE_URL}/api/vehicle-checklist/ai/ocr-paper",
                          json=payload, headers=headers, timeout=120)
        assert r.status_code != 500, f"500: {r.text[:300]}"
        assert r.status_code in (200, 502), f"unexpected {r.status_code}: {r.text[:300]}"
        if r.status_code == 200:
            data = r.json()
            assert "ocr" in data and "model" in data
            ocr = data["ocr"]
            # campos chave (alguns podem ser null)
            for k in ("plate", "km_initial", "items", "confidence"):
                assert k in ocr, f"missing {k} in ocr: {ocr}"
            assert isinstance(ocr["items"], list)

    def test_ocr_paper_invalid_image(self, headers):
        # SVG should be rejected (mime filter)
        bad = "data:image/svg+xml;base64,PHN2Zy8+"
        r = requests.post(f"{BASE_URL}/api/vehicle-checklist/ai/ocr-paper",
                          json={"image_data_url": bad}, headers=headers, timeout=15)
        assert r.status_code == 400
