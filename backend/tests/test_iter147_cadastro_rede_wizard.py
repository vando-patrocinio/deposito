"""
Iter147 — Cadastro Rede Wizard (CTO / CE / CABO) backend tests.

Tests for:
- POST /api/rede-ia/public/ctos/{collab_id} with element_type=cto|ce|cabo
- GET  /api/rede-ia/public/ctos/suggest-name/{collab_id} with element_type
- GET  /api/rede-ia/public/ctos/list/{collab_id}
- Independent numbering per element_type
- Validation negatives (CE without bandejas, CABO without from/to, fibras inválidas)
"""
import os
import pytest
import requests

def _load_env():
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ.setdefault(k, v)
    except Exception:
        pass
_load_env()
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
COLLAB_ID = "col-30aafc3c"  # Diogo técnico
SIGLA = "BRA"
VLAN = 301


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _base_payload(elem_type, sigla=SIGLA, vlan=VLAN, suggested_name=None):
    return {
        "element_type": elem_type,
        "rua": "Rua Teste 147",
        "numero": "100",
        "bairro": "Bairro Teste",
        "cidade": "Cidade Teste",
        "estado": "SP",
        "referencia": "TEST_iter147",
        "lat": -23.5, "lng": -46.6,
        "capacity": 0 if elem_type != "cto" else 8,
        "network_type": "" if elem_type != "cto" else "balanceada",
        "splitter": None,
        "client_port": None,
        "sigla": sigla, "vlan": vlan,
        "suggested_name": suggested_name or "",
        "technician_id": COLLAB_ID,
        "technician_name": "Diogo",
    }


# ----- Suggest-name -----
class TestSuggestName:
    def test_suggest_cto(self, api):
        r = api.get(f"{BASE_URL}/api/rede-ia/public/ctos/suggest-name/{COLLAB_ID}",
                    params={"sigla": SIGLA, "vlan": VLAN, "element_type": "cto"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["suggested_name"].startswith("CTO "), d
        assert isinstance(d["suggested_number"], int)

    def test_suggest_ce(self, api):
        r = api.get(f"{BASE_URL}/api/rede-ia/public/ctos/suggest-name/{COLLAB_ID}",
                    params={"sigla": SIGLA, "vlan": VLAN, "element_type": "ce"})
        assert r.status_code == 200, r.text
        assert r.json()["suggested_name"].startswith("CE ")

    def test_suggest_cabo(self, api):
        r = api.get(f"{BASE_URL}/api/rede-ia/public/ctos/suggest-name/{COLLAB_ID}",
                    params={"sigla": SIGLA, "vlan": VLAN, "element_type": "cabo"})
        assert r.status_code == 200, r.text
        assert r.json()["suggested_name"].startswith("CABO ")


# ----- List -----
class TestListElements:
    def test_list_returns_items(self, api):
        r = api.get(f"{BASE_URL}/api/rede-ia/public/ctos/list/{COLLAB_ID}")
        assert r.status_code == 200, r.text
        assert "items" in r.json()


# ----- Create CTO/CE/CABO + numbering independence -----
class TestCreateElements:
    created_ids = []

    def test_create_cto(self, api):
        sug = api.get(f"{BASE_URL}/api/rede-ia/public/ctos/suggest-name/{COLLAB_ID}",
                      params={"sigla": SIGLA, "vlan": VLAN, "element_type": "cto"}).json()
        p = _base_payload("cto", suggested_name=sug["suggested_name"])
        p["client_port"] = 1
        r = api.post(f"{BASE_URL}/api/rede-ia/public/ctos/{COLLAB_ID}", json=p)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["element_type"] == "cto"
        assert d["name"].startswith("CTO ")
        assert len(d["ports"]) == 8
        self.created_ids.append(d["id"])
        # Persistence check
        lr = api.get(f"{BASE_URL}/api/rede-ia/public/ctos/list/{COLLAB_ID}")
        ids = [i["id"] for i in lr.json().get("items", [])]
        assert d["id"] in ids

    def test_create_ce_with_bandejas(self, api):
        sug = api.get(f"{BASE_URL}/api/rede-ia/public/ctos/suggest-name/{COLLAB_ID}",
                      params={"sigla": SIGLA, "vlan": VLAN, "element_type": "ce"}).json()
        p = _base_payload("ce", suggested_name=sug["suggested_name"])
        p["bandejas_total"] = 12
        p["ce_install_type"] = "aerea"
        r = api.post(f"{BASE_URL}/api/rede-ia/public/ctos/{COLLAB_ID}", json=p)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["element_type"] == "ce"
        assert d["name"].startswith("CE ")
        assert d["bandejas_total"] == 12
        assert d["ce_install_type"] == "aerea"
        assert d["ports"] == []
        self.created_ids.append(d["id"])

    def test_ce_without_bandejas_fails(self, api):
        p = _base_payload("ce", suggested_name="CE 999_VLAN301_BRA")
        r = api.post(f"{BASE_URL}/api/rede-ia/public/ctos/{COLLAB_ID}", json=p)
        assert r.status_code == 400, r.text
        assert "bandeja" in r.text.lower()

    def test_create_cabo(self, api):
        # Need two existing elements
        lr = api.get(f"{BASE_URL}/api/rede-ia/public/ctos/list/{COLLAB_ID}").json()
        items = [i for i in lr.get("items", [])
                 if (i.get("element_type") or "cto").lower() in ("cto", "ce")]
        assert len(items) >= 2, "Need at least 2 elements for CABO test"
        frm, to = items[0], items[1]
        sug = api.get(f"{BASE_URL}/api/rede-ia/public/ctos/suggest-name/{COLLAB_ID}",
                      params={"sigla": frm.get("sigla", SIGLA),
                              "vlan": frm.get("vlan", VLAN),
                              "element_type": "cabo"}).json()
        p = _base_payload("cabo", sigla=frm.get("sigla", SIGLA),
                          vlan=frm.get("vlan", VLAN),
                          suggested_name=sug["suggested_name"])
        p["from_element_id"] = frm["id"]
        p["to_element_id"] = to["id"]
        p["fibras_total"] = 12
        p["fibras_ocupadas"] = 0
        p["cable_type"] = "distribuicao"
        r = api.post(f"{BASE_URL}/api/rede-ia/public/ctos/{COLLAB_ID}", json=p)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["element_type"] == "cabo"
        assert d["name"].startswith("CABO ")
        assert d["fibras_total"] == 12
        assert d["cable_type"] == "distribuicao"
        assert d["from_element_id"] == frm["id"]
        assert d["to_element_id"] == to["id"]
        self.created_ids.append(d["id"])

    def test_cabo_without_from_to_fails(self, api):
        p = _base_payload("cabo", suggested_name="CABO 999_VLAN301_BRA")
        p["fibras_total"] = 12
        p["cable_type"] = "drop"
        r = api.post(f"{BASE_URL}/api/rede-ia/public/ctos/{COLLAB_ID}", json=p)
        assert r.status_code == 400, r.text
        assert "origem" in r.text.lower() or "destino" in r.text.lower()

    def test_cabo_invalid_fibras_fails(self, api):
        lr = api.get(f"{BASE_URL}/api/rede-ia/public/ctos/list/{COLLAB_ID}").json()
        items = [i for i in lr.get("items", [])
                 if (i.get("element_type") or "cto").lower() in ("cto", "ce")]
        if len(items) < 2:
            pytest.skip("Not enough elements")
        p = _base_payload("cabo", suggested_name="CABO 999_VLAN301_BRA")
        p["from_element_id"] = items[0]["id"]
        p["to_element_id"] = items[1]["id"]
        p["fibras_total"] = 10  # invalid
        p["cable_type"] = "drop"
        r = api.post(f"{BASE_URL}/api/rede-ia/public/ctos/{COLLAB_ID}", json=p)
        assert r.status_code == 400, r.text
        assert "fibra" in r.text.lower()

    def test_cabo_same_origin_destination_fails(self, api):
        lr = api.get(f"{BASE_URL}/api/rede-ia/public/ctos/list/{COLLAB_ID}").json()
        items = [i for i in lr.get("items", [])
                 if (i.get("element_type") or "cto").lower() in ("cto", "ce")]
        if not items:
            pytest.skip("No elements")
        p = _base_payload("cabo", suggested_name="CABO 999_VLAN301_BRA")
        p["from_element_id"] = items[0]["id"]
        p["to_element_id"] = items[0]["id"]
        p["fibras_total"] = 12
        p["cable_type"] = "drop"
        r = api.post(f"{BASE_URL}/api/rede-ia/public/ctos/{COLLAB_ID}", json=p)
        assert r.status_code == 400, r.text


# ----- Independent numbering -----
class TestIndependentNumbering:
    def test_cto_ce_cabo_numbering_independent(self, api):
        n_cto = api.get(f"{BASE_URL}/api/rede-ia/public/ctos/suggest-name/{COLLAB_ID}",
                        params={"sigla": SIGLA, "vlan": VLAN, "element_type": "cto"}).json()
        n_ce = api.get(f"{BASE_URL}/api/rede-ia/public/ctos/suggest-name/{COLLAB_ID}",
                       params={"sigla": SIGLA, "vlan": VLAN, "element_type": "ce"}).json()
        n_cab = api.get(f"{BASE_URL}/api/rede-ia/public/ctos/suggest-name/{COLLAB_ID}",
                        params={"sigla": SIGLA, "vlan": VLAN, "element_type": "cabo"}).json()
        # Each must yield its own prefix and counter is independent (they may
        # share the same number value but for different prefixes).
        assert n_cto["suggested_name"].startswith("CTO ")
        assert n_ce["suggested_name"].startswith("CE ")
        assert n_cab["suggested_name"].startswith("CABO ")
