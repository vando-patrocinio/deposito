"""Iter 100 — Orçamento "Importar Pronto" (extract preços + auto-print)."""
import io
import os
import uuid

import httpx
import pytest
import pytest_asyncio
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
BASE = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://dual-combine-3.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE}/api"


@pytest_asyncio.fixture
async def db():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    yield cli[os.environ["DB_NAME"]]
    cli.close()


async def _token():
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{API}/auth/login", json={
            "email": "admin@empresa.com", "password": "123456",
        })
    return r.json().get("access_token") or r.json().get("token")


@pytest.mark.asyncio
async def test_1_csv_with_prices_marks_ready_to_print(db):
    token = await _token()
    headers = {"Authorization": f"Bearer {token}"}
    csv = (
        "item;qtde;unidade;preco\n"
        "Cabo Drop FTTH;200;m;3.50\n"
        "Conector Fast SC/APC;10;un;8.90\n"
        "ONU XPON;1;un;220.00\n"
    )
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{API}/budget", headers=headers,
                            json={"name": f"PyTest {uuid.uuid4().hex[:6]}",
                                    "description": "test"})
        bid = r.json()["id"]
        try:
            files = {"file": ("orca.csv", csv.encode(), "text/csv")}
            r2 = await c.post(f"{API}/budget/{bid}/upload",
                                  headers=headers, files=files)
            assert r2.status_code == 200, r2.text
            j = r2.json()
            assert j["items_count"] == 3
            assert j["items_with_price"] == 3
            assert j["ready_to_print"] is True
            # GET budget — status deve ser 'analyzed' e itens com manual_override
            r3 = await c.get(f"{API}/budget/{bid}", headers=headers)
            d = r3.json()
            assert d["status"] == "analyzed"
            overrides = [i.get("manual_override") for i in d["items"]]
            assert all(o and o > 0 for o in overrides), overrides
            assert overrides[0] == 3.5
            assert overrides[2] == 220.0
        finally:
            await c.delete(f"{API}/budget/{bid}", headers=headers)


@pytest.mark.asyncio
async def test_2_csv_brazilian_money_format(db):
    """CSV com R$ 1.234,56 deve normalizar pra 1234.56."""
    token = await _token()
    headers = {"Authorization": f"Bearer {token}"}
    csv = (
        "item;qtde;unidade;preco\n"
        "Switch 8 portas;1;un;R$ 1.234,56\n"
    )
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{API}/budget", headers=headers,
                            json={"name": "BR Money", "description": "x"})
        bid = r.json()["id"]
        try:
            files = {"file": ("o.csv", csv.encode(), "text/csv")}
            r2 = await c.post(f"{API}/budget/{bid}/upload",
                                  headers=headers, files=files)
            assert r2.status_code == 200
            d = (await c.get(f"{API}/budget/{bid}",
                              headers=headers)).json()
            assert d["items"][0]["manual_override"] == 1234.56
        finally:
            await c.delete(f"{API}/budget/{bid}", headers=headers)


@pytest.mark.asyncio
async def test_3_csv_without_prices_stays_draft(db):
    token = await _token()
    headers = {"Authorization": f"Bearer {token}"}
    csv = "item;qtde;unidade\nCabo;100;m\nConector;5;un\n"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{API}/budget", headers=headers,
                            json={"name": "No Prices", "description": "x"})
        bid = r.json()["id"]
        try:
            files = {"file": ("o.csv", csv.encode(), "text/csv")}
            r2 = await c.post(f"{API}/budget/{bid}/upload",
                                  headers=headers, files=files)
            j = r2.json()
            assert j["ready_to_print"] is False
            assert j["items_with_price"] == 0
            d = (await c.get(f"{API}/budget/{bid}",
                              headers=headers)).json()
            assert d["status"] == "draft"
        finally:
            await c.delete(f"{API}/budget/{bid}", headers=headers)


@pytest.mark.asyncio
async def test_4_pdf_generates_with_imported_prices(db):
    token = await _token()
    headers = {"Authorization": f"Bearer {token}"}
    csv = "item;qtde;unidade;preco\nFio;100;m;2.50\n"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{API}/budget", headers=headers,
                            json={"name": "PDF Auto", "description": "x"})
        bid = r.json()["id"]
        try:
            await c.post(f"{API}/budget/{bid}/upload", headers=headers,
                            files={"file": ("o.csv", csv.encode(),
                                              "text/csv")})
            r2 = await c.get(f"{API}/budget/{bid}/pdf", headers=headers)
            assert r2.status_code == 200
            assert len(r2.content) > 1000
            assert r2.content[:4] == b"%PDF"
        finally:
            await c.delete(f"{API}/budget/{bid}", headers=headers)


@pytest.mark.asyncio
async def test_5_image_format_accepted(db):
    """Endpoint deve ACEITAR upload .png (mesmo que o Vision falhe sem
    LLM real disponível, deve cair em 503 ou retornar 200 — não 415)."""
    token = await _token()
    headers = {"Authorization": f"Bearer {token}"}
    # 1x1 PNG válido (mínimo)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8"
        b"\xcf\xc0\x00\x00\x00\x03\x00\x01\xc8\x9e\xab\xc4\x00\x00\x00\x00"
        b"IEND\xaeB`\x82"
    )
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post(f"{API}/budget", headers=headers,
                            json={"name": "Img Test", "description": "x"})
        bid = r.json()["id"]
        try:
            files = {"file": ("foto.png", png_bytes, "image/png")}
            r2 = await c.post(f"{API}/budget/{bid}/upload",
                                  headers=headers, files=files)
            # Aceito o caminho de imagem — qualquer status que NÃO seja 415.
            assert r2.status_code != 415, (
                f"Imagem rejeitada como formato: {r2.text}"
            )
        finally:
            await c.delete(f"{API}/budget/{bid}", headers=headers)
