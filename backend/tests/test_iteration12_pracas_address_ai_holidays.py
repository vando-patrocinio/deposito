import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _test_secrets import TEST_ADMIN_PASSWORD, TEST_AUDITOR_PASSWORD  # noqa: E402
"""Iteration 12 — Praças endereço completo + IA de feriados (discover/apply)."""
import os
import time
import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://selfie-attendance-7.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


# ---------- auth ----------
@pytest.fixture(scope="module")
def admin_headers():
    r = requests.post(f"{API}/auth/login", json={"email": "admin@example.com", "password": TEST_ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------- CRUD with new address fields ----------
class TestPracasAddressFields:
    def test_create_praca_with_full_address(self, admin_headers):
        payload = {
            "name": "TEST_Iter12_AddrPraca",
            "city": "Cachoeiras de Macacu",
            "state": "RJ",
            "full_address": "Rua das Flores, 123 - Centro, Cachoeiras de Macacu - RJ",
            "street": "Rua das Flores",
            "number": "123",
            "neighborhood": "Centro",
            "postal_code": "28680-000",
            "lat": -22.4646,
            "lng": -42.6532,
            "holidays_extra": [],
        }
        r = requests.post(f"{API}/pracas", json=payload, headers=admin_headers)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("full_address", "street", "number", "neighborhood", "postal_code", "lat", "lng"):
            assert data.get(k) == payload[k], f"campo {k} não persistido"
        pid = data["id"]

        # GET list inclui campos novos
        r = requests.get(f"{API}/pracas")
        praca = next((p for p in r.json() if p["id"] == pid), None)
        assert praca is not None
        assert praca.get("full_address") == payload["full_address"]
        assert praca.get("street") == "Rua das Flores"
        assert praca.get("postal_code") == "28680-000"
        assert praca.get("lat") == pytest.approx(-22.4646, abs=1e-4)

        # PUT atualiza campos
        upd = {**payload, "neighborhood": "Centro Novo", "number": "456",
               "full_address": "Rua das Flores, 456 - Centro Novo, Cachoeiras de Macacu - RJ"}
        r = requests.put(f"{API}/pracas/{pid}", json=upd, headers=admin_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["neighborhood"] == "Centro Novo"
        assert d["number"] == "456"
        assert "456" in (d.get("full_address") or "")

        # cleanup
        requests.delete(f"{API}/pracas/{pid}", headers=admin_headers)


# ---------- Discover holidays (IA) ----------
class TestDiscoverHolidays:
    @pytest.fixture(scope="class")
    def test_praca_id(self, admin_headers):
        r = requests.post(f"{API}/pracas", json={
            "name": "TEST_Iter12_AI",
            "city": "Cachoeiras de Macacu",
            "state": "RJ",
            "holidays_extra": [
                {"date": "2026-04-15", "name": "Aniversário Pré-existente", "scope": "municipal"}
            ],
        }, headers=admin_headers)
        assert r.status_code == 200
        pid = r.json()["id"]
        yield pid
        requests.delete(f"{API}/pracas/{pid}", headers=admin_headers)

    def test_discover_requires_auth(self, test_praca_id):
        r = requests.post(f"{API}/pracas/{test_praca_id}/discover-holidays?year=2026")
        assert r.status_code in (401, 403)

    def test_discover_invalid_year(self, admin_headers, test_praca_id):
        r = requests.post(f"{API}/pracas/{test_praca_id}/discover-holidays?year=1900",
                          headers=admin_headers)
        assert r.status_code == 400

    def test_discover_returns_ai_suggestions(self, admin_headers, test_praca_id):
        # IA pode levar 5-10s
        r = requests.post(
            f"{API}/pracas/{test_praca_id}/discover-holidays?year=2026",
            headers=admin_headers,
            timeout=60,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["year"] == 2026
        assert data["city"] == "Cachoeiras de Macacu"
        assert data["state"] == "RJ"
        suggestions = data["suggestions"]
        assert isinstance(suggestions, list)
        # Cachoeiras de Macacu / RJ deveria retornar pelo menos uma sugestão
        assert len(suggestions) >= 1, f"esperava >=1 sugestão, recebeu: {suggestions}"
        for s in suggestions:
            assert s["date"].startswith("2026-")
            assert s["name"]
            assert s["scope"] in ("estadual", "municipal", "facultativo")
            assert s["source"] == "ai"

    def test_apply_holidays_dedupe_and_preserve(self, admin_headers, test_praca_id):
        # apply: 2 novas + 1 já existente (mesma data)
        body = {
            "holidays": [
                {"date": "2026-04-15", "name": "Aniv (sobrescreve)", "scope": "municipal", "source": "ai"},
                {"date": "2026-02-17", "name": "Carnaval", "scope": "facultativo", "source": "ai"},
                {"date": "2026-06-04", "name": "Corpus Christi", "scope": "estadual", "source": "ai"},
            ]
        }
        r = requests.post(
            f"{API}/pracas/{test_praca_id}/apply-holidays",
            json=body,
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["added"] == 2  # apenas 2 novas (15/04 já existia)
        # total = 3 (1 pré-existente + 2 novas, com 15/04 dedup)
        assert data["total"] == 3
        dates = {h["date"] for h in data["holidays_extra"]}
        assert dates == {"2026-04-15", "2026-02-17", "2026-06-04"}
        # source ai marcado nas novas
        carnaval = next(h for h in data["holidays_extra"] if h["date"] == "2026-02-17")
        assert carnaval["source"] == "ai"
        assert carnaval["scope"] == "facultativo"

        # idempotência: re-apply mesmas → added=0
        r = requests.post(
            f"{API}/pracas/{test_praca_id}/apply-holidays",
            json=body,
            headers=admin_headers,
        )
        assert r.status_code == 200
        d2 = r.json()
        assert d2["added"] == 0
        assert d2["total"] == 3

    def test_apply_invalid_body(self, admin_headers, test_praca_id):
        r = requests.post(
            f"{API}/pracas/{test_praca_id}/apply-holidays",
            json={"holidays": "not_a_list"},
            headers=admin_headers,
        )
        assert r.status_code == 400
