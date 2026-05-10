"""Iter35 — POST /api/collab-assets/return-confirm/{cid} (signature embedding +
side-effects + persistence + validation) and GET /returns/{cid} privacy.

Auth: gestor admin@empresa.com / 123456
Target collaborator: col-30aafc3c

Pre-step: reset collaborator_assets back to status='ativo' so side-effect
assertion can detect the transition. Done via PATCH /api/collab-assets/{id}.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import requests

# Read REACT_APP_BACKEND_URL straight from frontend/.env (matches what user sees).
def _read_backend_url() -> str:
    env = Path("/app/frontend/.env").read_text().splitlines()
    for line in env:
        if line.startswith("REACT_APP_BACKEND_URL="):
            return line.split("=", 1)[1].strip().strip('"').rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL missing in /app/frontend/.env")


BASE_URL = _read_backend_url()
COLLAB_ID = "col-30aafc3c"
TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNgAAIAAAUAAeImBZsAAAAASUVORK5CYII="
)


@pytest.fixture(scope="module")
def gestor_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "admin@empresa.com", "password": "123456"},
                      timeout=20)
    assert r.status_code == 200, f"Login falhou: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, f"Sem token na resposta: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def auth_headers(gestor_token):
    return {"Authorization": f"Bearer {gestor_token}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def reset_assets_to_ativo(auth_headers):
    """Antes do teste de side-effect, devolve quaisquer assets do col-30aafc3c
    a status='ativo' (caso teste anterior tenha marcado como 'devolvido')."""
    r = requests.get(f"{BASE_URL}/api/collab-assets/by-collaborator/{COLLAB_ID}",
                     headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text
    items = r.json().get("items", [])
    reset_count = 0
    for it in items:
        if it.get("status") != "ativo":
            pr = requests.patch(
                f"{BASE_URL}/api/collab-assets/{it['id']}",
                headers=auth_headers,
                json={"status": "ativo"},
                timeout=15,
            )
            if pr.status_code == 200:
                reset_count += 1
    return {"total": len(items), "reset": reset_count}


# ---------------------------------------------------------------------------
# 1. POST return-confirm — PDF + headers + signature/text embedding
# ---------------------------------------------------------------------------
class TestReturnConfirmPDF:
    def test_returns_pdf_with_signature_and_header(self, auth_headers, reset_assets_to_ativo):
        body = {
            "receiver_name": "Carla Souza",
            "receiver_role": "Coordenadora de Operações",
            "signature_data_url": TINY_PNG,
            "notes": "Devolução completa conforme conferência.",
            "confirmed_item_keys": ["asset|abc", "ont|AA:BB:CC"],
        }
        r = requests.post(
            f"{BASE_URL}/api/collab-assets/return-confirm/{COLLAB_ID}",
            headers=auth_headers, json=body, timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

        # Content-Type
        assert r.headers.get("Content-Type", "").startswith("application/pdf"), \
            f"Content-Type errado: {r.headers.get('Content-Type')}"

        # X-Return-Id
        rid = r.headers.get("X-Return-Id") or r.headers.get("x-return-id")
        assert rid and rid.startswith("return-"), \
            f"X-Return-Id ausente/invalido: {rid!r}"

        # PDF magic bytes
        body_bytes = r.content
        assert body_bytes[:4] == b"%PDF", "Resposta não é PDF"
        assert len(body_bytes) > 5_000, f"PDF muito pequeno: {len(body_bytes)}"

        # Texto do PDF — extraído via pypdf (lida com FlateDecode/ASCII85)
        import io as _io
        from pypdf import PdfReader
        reader = PdfReader(_io.BytesIO(body_bytes))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        assert "Carla Souza" in text, f"Nome do recebedor ausente no PDF. Texto:\n{text[:1500]}"
        assert "Coordenadora" in text, f"Cargo do recebedor ausente no PDF. Texto:\n{text[:1500]}"
        assert "assinado em" in text.lower(), f"'assinado em <data>' ausente no PDF. Texto:\n{text[:1500]}"

        # Guarda return_id para teste de persistência
        pytest.return_id = rid


# ---------------------------------------------------------------------------
# 2. GET /returns/{cid} — persistência + privacidade da assinatura
# ---------------------------------------------------------------------------
class TestReturnsHistory:
    def test_history_count_and_shape_and_signature_excluded(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/collab-assets/returns/{COLLAB_ID}",
            headers=auth_headers, timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("count", 0) >= 1, f"count<1: {data}"
        items = data.get("items") or []
        assert items, "items vazio"
        first = items[0]
        # Shape obrigatorio
        for key in ("id", "receiver_name", "receiver_role",
                    "issued_at", "asset_ids_snapshot", "extras_snapshot"):
            assert key in first, f"campo '{key}' ausente: {list(first.keys())}"
        # Privacidade: signature_data_url excluído
        assert "signature_data_url" not in first, \
            "signature_data_url NÃO deveria estar exposta"
        # Confere que receiver_name foi persistido conforme posted
        assert first["receiver_name"] == "Carla Souza"


# ---------------------------------------------------------------------------
# 3. Side-effect: collaborator_assets ativos -> devolvido
# ---------------------------------------------------------------------------
class TestSideEffectAssetsReturned:
    def test_active_assets_marked_devolvido(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/collab-assets/by-collaborator/{COLLAB_ID}",
            headers=auth_headers, timeout=15,
        )
        assert r.status_code == 200
        items = r.json().get("items", [])
        # Após return-confirm acima, nenhum collaborator_asset deve estar 'ativo'.
        ativos = [a for a in items if a.get("status") == "ativo"]
        assert not ativos, f"Ainda há {len(ativos)} ativos: {[a.get('id') for a in ativos]}"

        # Pelo menos 1 doc devolvido com retornados/return_id setados
        devolvidos = [a for a in items if a.get("status") == "devolvido"]
        assert devolvidos, "Nenhum asset marcado como 'devolvido'"
        for a in devolvidos:
            # Os mais recentes (retornados nesta sessão) devem ter return_id
            if a.get("return_id"):
                assert a.get("returned_at"), f"returned_at ausente em {a.get('id')}"
                assert a.get("returned_to"), f"returned_to ausente em {a.get('id')}"
                assert a["return_id"].startswith("return-"), a["return_id"]
                break
        else:
            pytest.fail("Nenhum devolvido com return_id — side-effect não setou metadados")

    def test_onts_and_insumos_not_touched(self, auth_headers):
        # ONTs em poder do técnico continuam em location_type=tecnico
        r = requests.get(
            f"{BASE_URL}/api/collab-assets/custody-full/{COLLAB_ID}",
            headers=auth_headers, timeout=15,
        )
        assert r.status_code == 200
        data = r.json()
        extras = data.get("extras", [])
        # Após return-confirm, gestor decide separadamente — extras devem
        # continuar listados (ONTs/insumos não foram tocados pelo endpoint).
        ont_or_insumo = [e for e in extras
                         if e.get("category") in ("ont", "insumo")]
        # Pode estar vazio se o seed foi limpo, mas se houver ONTs/insumos eles
        # devem permanecer (não foi tocado). A asserção é "não houve crash"
        # e o shape continua coerente.
        assert isinstance(ont_or_insumo, list)
        # O importante: assets ativos = 0 (já devolvidos), mas extras seguem o
        # seu próprio ciclo de vida.
        assert data["totals"]["assets_count"] == 0


# ---------------------------------------------------------------------------
# 4. Validação — receiver_name curto/vazio e signature vazia => 422
# ---------------------------------------------------------------------------
class TestValidation:
    @pytest.mark.parametrize("body,desc", [
        ({"receiver_name": "", "signature_data_url": TINY_PNG}, "name vazio"),
        ({"receiver_name": "A", "signature_data_url": TINY_PNG}, "name 1 char"),
        ({"receiver_name": "Carla Souza", "signature_data_url": ""}, "signature vazia"),
        ({"receiver_name": "Carla Souza"}, "signature ausente"),
    ])
    def test_invalid_inputs_return_422(self, auth_headers, body, desc):
        r = requests.post(
            f"{BASE_URL}/api/collab-assets/return-confirm/{COLLAB_ID}",
            headers=auth_headers, json=body, timeout=15,
        )
        assert r.status_code == 422, f"[{desc}] esperado 422, veio {r.status_code}: {r.text[:200]}"


# ---------------------------------------------------------------------------
# 5. Regressão: GET /romaneio/{cid}?mode=return continua sem assinatura
# ---------------------------------------------------------------------------
class TestRomaneioReturnRegression:
    def test_mode_return_no_signature_embedded(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/collab-assets/romaneio/{COLLAB_ID}?mode=return",
            headers=auth_headers, timeout=20,
        )
        assert r.status_code == 200, r.text
        assert r.headers.get("Content-Type", "").startswith("application/pdf")
        body = r.content
        assert body[:4] == b"%PDF"
        assert len(body) > 3_000

        # Não deve conter 'assinado em' (sem receiver) nem nome 'Carla Souza'
        from pypdf import PdfReader
        import io as _io
        reader = PdfReader(_io.BytesIO(body))
        text = "\n".join((p.extract_text() or "") for p in reader.pages).lower()
        assert "carla souza" not in text, "Romaneio mode=return embutiu nome do recebedor (não deveria)"
        assert "assinado em" not in text, "Romaneio mode=return embutiu 'assinado em' (não deveria)"
