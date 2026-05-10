"""Iter34 — Romaneio de DEVOLUÇÃO à empresa (mode=return).

Cobertura solicitada:
1. /custody-full/{cid} (gestor) — deve retornar assets+extras+totals (col-30aafc3c → 4 assets + 12 extras).
2. /romaneio/{cid}?mode=return (gestor) — PDF com Content-Disposition contendo "devolucao_"; texto
   inclui CHECKLIST DE DEVOLUÇÃO À EMPRESA, TERMO DE RECEBIMENTO, "Devolvido" header, frases
   de Colaborador (devolvendo) / Responsável pela empresa (recebendo) e categorias ONT / INSUMO.
3. /romaneio/{cid} (sem mode) — regressão: PDF padrão com TERMO DE RESPONSABILIDADE, sem
   coluna "Devolvido".
4. /romaneio/{cid}?mode=invalid — 422 (regex valida só delivery|return).
"""
import io
import os
import pytest
import requests
from pypdf import PdfReader

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASSWORD = "123456"
TEST_CID = "col-30aafc3c"  # DIOGO HENRIQUE


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD,
    }, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"Login admin falhou: {r.status_code} {r.text[:200]}")
    tok = r.json().get("token") or r.json().get("access_token")
    if not tok:
        pytest.skip("Token não retornado no login")
    return tok


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _extract_pdf_text(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    parts = []
    for p in reader.pages:
        try:
            parts.append(p.extract_text() or "")
        except Exception:
            pass
    return "\n".join(parts)


# 1. custody-full ----------------------------------------------------------
class TestCustodyFull:
    def test_custody_full_shape_and_counts(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/collab-assets/custody-full/{TEST_CID}",
                         headers=auth_headers, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        # Shape
        assert "collaborator" in data
        assert "assets" in data and isinstance(data["assets"], list)
        assert "extras" in data and isinstance(data["extras"], list)
        assert "totals" in data
        totals = data["totals"]
        assert "assets_count" in totals
        assert "extras_count" in totals
        assert "value_brl" in totals
        # Counts (expect 4 assets + 12 extras = 8 ONTs + 4 insumos)
        assert totals["assets_count"] == len(data["assets"])
        assert totals["extras_count"] == len(data["extras"])
        assert totals["assets_count"] == 4, f"esperado 4 assets, veio {totals['assets_count']}"
        assert totals["extras_count"] == 12, f"esperado 12 extras, veio {totals['extras_count']}"
        # Categorias dos extras
        cats = [e.get("category") for e in data["extras"]]
        assert cats.count("ont") == 8, f"esperado 8 ONTs, veio {cats.count('ont')}"
        assert cats.count("insumo") == 4, f"esperado 4 insumos, veio {cats.count('insumo')}"
        # Collaborator name disponível
        assert (data["collaborator"] or {}).get("name")

    def test_custody_full_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/collab-assets/custody-full/{TEST_CID}", timeout=15)
        assert r.status_code in (401, 403), f"esperava 401/403 sem auth, veio {r.status_code}"


# 2. Romaneio mode=return --------------------------------------------------
class TestRomaneioReturn:
    @pytest.fixture(scope="class")
    def return_pdf(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/collab-assets/romaneio/{TEST_CID}",
                         params={"mode": "return"},
                         headers=auth_headers, timeout=30)
        assert r.status_code == 200, r.text[:300]
        return r

    def test_content_type_and_disposition(self, return_pdf):
        assert return_pdf.headers.get("content-type", "").startswith("application/pdf")
        cd = return_pdf.headers.get("content-disposition", "")
        assert "devolucao_" in cd, f"Content-Disposition sem 'devolucao_': {cd}"

    def test_pdf_signature_and_size(self, return_pdf):
        body = return_pdf.content
        assert body[:5] == b"%PDF-", "não é PDF válido"
        assert len(body) > 5000, f"PDF muito pequeno: {len(body)} bytes"

    def test_pdf_text_contains_devolucao_keywords(self, return_pdf):
        txt = _extract_pdf_text(return_pdf.content)
        # Título e termo
        assert "CHECKLIST DE DEVOLUÇÃO" in txt.upper(), txt[:500]
        assert "TERMO DE RECEBIMENTO" in txt.upper()
        # Header "Devolvido" (coluna de checkbox)
        assert "Devolvido" in txt, "header da coluna 'Devolvido' não encontrado"
        # Linhas de assinatura
        assert "Colaborador (devolvendo" in txt
        assert "Responsável pela empresa (recebendo" in txt
        # Categorias normalizadas
        upper = txt.upper()
        assert "ONT" in upper, "categoria ONT ausente"
        assert "INSUMO" in upper, "categoria INSUMO ausente"


# 3. Regressão: mode=delivery (padrão) -------------------------------------
class TestRomaneioDeliveryRegression:
    @pytest.fixture(scope="class")
    def delivery_pdf(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/collab-assets/romaneio/{TEST_CID}",
                         headers=auth_headers, timeout=30)
        assert r.status_code == 200, r.text[:300]
        return r

    def test_delivery_disposition_no_devolucao(self, delivery_pdf):
        cd = delivery_pdf.headers.get("content-disposition", "")
        assert "romaneio_" in cd
        assert "devolucao_" not in cd, f"modo delivery não deveria ter 'devolucao_': {cd}"

    def test_delivery_text_termo_responsabilidade(self, delivery_pdf):
        txt = _extract_pdf_text(delivery_pdf.content)
        assert "TERMO DE RESPONSABILIDADE" in txt.upper()
        # Não deve ter coluna Devolvido nem termo de RECEBIMENTO no header
        assert "TERMO DE RECEBIMENTO" not in txt.upper(), \
            "modo delivery não deveria conter 'TERMO DE RECEBIMENTO'"
        # A coluna 'Devolvido' (checkbox) é específica do return
        assert "CHECKLIST DE DEVOLUÇÃO" not in txt.upper()


# 4. Validação do regex mode=invalid ---------------------------------------
class TestRomaneioInvalidMode:
    def test_invalid_mode_returns_422(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/collab-assets/romaneio/{TEST_CID}",
                         params={"mode": "invalid"},
                         headers=auth_headers, timeout=15)
        assert r.status_code in (400, 422), \
            f"esperado 400/422 para mode=invalid, veio {r.status_code}: {r.text[:200]}"
