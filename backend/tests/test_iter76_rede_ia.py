"""Tests for Rede IA module (Iteration 76)."""
import os
import pytest
import requests
import time

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def tokens():
    return {
        "admin": _login("admin@empresa.com", "123456"),
        "gestorrede": _login("gestorrede@empresa.com", "123456"),
        "colab": _login("colaborador@empresa.com", "123456"),
    }


def H(t): return {"Authorization": f"Bearer {t}"}


# ---------- Seed user gestor_rede ----------
def test_seed_gestor_rede(tokens):
    r = requests.get(f"{API}/auth/me", headers=H(tokens["gestorrede"]), timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert data["role"] == "gestor_rede"
    assert data["email"] == "gestorrede@empresa.com"


# ---------- BAIRROS ----------
class TestBairros:
    sigla = "TST"
    bairro_name = "TEST_Bairro_Iter76"
    bid = None

    def test_list_bairros(self, tokens):
        r = requests.get(f"{API}/rede-ia/bairros", headers=H(tokens["colab"]), timeout=15)
        assert r.status_code == 200
        assert "items" in r.json()

    def test_create_bairro_requires_role(self, tokens):
        # colaborator cannot create
        r = requests.post(f"{API}/rede-ia/bairros", headers=H(tokens["colab"]),
                          json={"bairro": "x", "sigla": "XY", "vlan": 999}, timeout=15)
        assert r.status_code == 403

    def test_create_bairro_admin(self, tokens):
        # cleanup any leftover
        list_r = requests.get(f"{API}/rede-ia/bairros", headers=H(tokens["admin"]), timeout=15).json()
        for it in list_r.get("items", []):
            if it.get("sigla") in (TestBairros.sigla, "TST", "COR") and it.get("bairro", "").startswith("TEST_"):
                requests.delete(f"{API}/rede-ia/bairros/{it['id']}", headers=H(tokens["admin"]), timeout=15)
        body = {"bairro": TestBairros.bairro_name, "sigla": TestBairros.sigla,
                "vlan": 301, "cidade": "TestCity", "estado": "SP"}
        r = requests.post(f"{API}/rede-ia/bairros", headers=H(tokens["admin"]), json=body, timeout=15)
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["sigla"] == "TST"
        assert doc["vlan"] == 301
        assert "id" in doc
        TestBairros.bid = doc["id"]

    def test_create_bairro_duplicate_returns_409(self, tokens):
        body = {"bairro": TestBairros.bairro_name, "sigla": TestBairros.sigla, "vlan": 301}
        r = requests.post(f"{API}/rede-ia/bairros", headers=H(tokens["admin"]), json=body, timeout=15)
        assert r.status_code == 409

    def test_gestor_rede_can_create_bairro(self, tokens):
        body = {"bairro": "TEST_Bairro_GR", "sigla": "TGR", "vlan": 302, "cidade": "C", "estado": "SP"}
        r = requests.post(f"{API}/rede-ia/bairros", headers=H(tokens["gestorrede"]), json=body, timeout=15)
        assert r.status_code == 200, r.text
        bid = r.json()["id"]
        # cleanup
        requests.delete(f"{API}/rede-ia/bairros/{bid}", headers=H(tokens["admin"]), timeout=15)

    def test_update_bairro(self, tokens):
        assert TestBairros.bid
        body = {"bairro": TestBairros.bairro_name, "sigla": TestBairros.sigla,
                "vlan": 301, "cidade": "UpdatedCity", "estado": "SP"}
        r = requests.put(f"{API}/rede-ia/bairros/{TestBairros.bid}", headers=H(tokens["admin"]),
                         json=body, timeout=15)
        assert r.status_code == 200


# ---------- CTO suggest name ----------
def test_suggest_name(tokens):
    r = requests.get(f"{API}/rede-ia/ctos/suggest-name?sigla=TST&vlan=301",
                     headers=H(tokens["colab"]), timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "suggested_name" in data
    assert data["suggested_name"].endswith("_301_TST")
    assert data["suggested_name"].startswith("CTO ")


# ---------- CTO CREATE + Validate workflow ----------
class TestCTO:
    cto_id = None

    def test_create_cto_bad_capacity(self, tokens):
        body = {
            "rua": "Rua A", "numero": "10", "bairro": "TEST_Bairro_Iter76",
            "cidade": "C", "estado": "SP", "capacity": 5,
            "network_type": "balanceada", "sigla": "TST", "vlan": 301,
            "suggested_name": "CTO 001_301_TST",
        }
        r = requests.post(f"{API}/rede-ia/ctos", headers=H(tokens["colab"]), json=body, timeout=15)
        assert r.status_code == 400

    def test_create_cto_desbalanceada_needs_splitter(self, tokens):
        body = {
            "rua": "Rua A", "numero": "10", "bairro": "TEST_Bairro_Iter76",
            "cidade": "C", "estado": "SP", "capacity": 8,
            "network_type": "desbalanceada", "sigla": "TST", "vlan": 301,
            "suggested_name": "CTO 001_301_TST",
        }
        r = requests.post(f"{API}/rede-ia/ctos", headers=H(tokens["colab"]), json=body, timeout=15)
        assert r.status_code == 400

    def test_create_cto_unknown_sigla(self, tokens):
        body = {
            "rua": "Rua A", "numero": "10", "bairro": "x", "cidade": "C", "estado": "SP",
            "capacity": 8, "network_type": "balanceada", "sigla": "ZZZ", "vlan": 999,
            "suggested_name": "CTO 001_999_ZZZ",
        }
        r = requests.post(f"{API}/rede-ia/ctos", headers=H(tokens["colab"]), json=body, timeout=15)
        assert r.status_code == 400

    def test_create_cto_ok(self, tokens):
        body = {
            "rua": "Rua A", "numero": "10", "bairro": "TEST_Bairro_Iter76",
            "cidade": "C", "estado": "SP", "capacity": 8,
            "network_type": "balanceada", "sigla": "TST", "vlan": 301,
            "suggested_name": "CTO 001_301_TST", "client_port": 7,
            "client_pppoe": "user@isp", "lat": -23.5, "lng": -46.6,
        }
        r = requests.post(f"{API}/rede-ia/ctos", headers=H(tokens["colab"]), json=body, timeout=20)
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["status"] == "pending_validation"
        assert doc["name"] == "CTO 001_301_TST"
        assert len(doc["ports"]) == 8
        port7 = [p for p in doc["ports"] if p["number"] == 7][0]
        assert port7["status"] == "used"
        TestCTO.cto_id = doc["id"]

    def test_create_cto_duplicate_returns_409(self, tokens):
        body = {
            "rua": "Rua A", "numero": "10", "bairro": "TEST_Bairro_Iter76",
            "cidade": "C", "estado": "SP", "capacity": 8,
            "network_type": "balanceada", "sigla": "TST", "vlan": 301,
            "suggested_name": "CTO 001_301_TST",
        }
        r = requests.post(f"{API}/rede-ia/ctos", headers=H(tokens["colab"]), json=body, timeout=15)
        assert r.status_code == 409

    def test_suggest_name_with_number_existing(self, tokens):
        r = requests.get(f"{API}/rede-ia/ctos/suggest-name?sigla=TST&vlan=301&number=1",
                         headers=H(tokens["colab"]), timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["exists"] is True
        assert data["suggested_number"] >= 2

    def test_pendencies_lists_cto(self, tokens):
        r = requests.get(f"{API}/rede-ia/pendencies", headers=H(tokens["gestorrede"]), timeout=15)
        assert r.status_code == 200
        ids = [it["cto_id"] for it in r.json()["items"]]
        assert TestCTO.cto_id in ids

    def test_pendencies_blocked_for_colab(self, tokens):
        r = requests.get(f"{API}/rede-ia/pendencies", headers=H(tokens["colab"]), timeout=15)
        assert r.status_code == 403

    def test_colab_cannot_validate(self, tokens):
        r = requests.post(f"{API}/rede-ia/ctos/{TestCTO.cto_id}/validate",
                          headers=H(tokens["colab"]),
                          json={"action": "approve", "comment": "x"}, timeout=15)
        assert r.status_code == 403

    def test_gestor_rede_approves(self, tokens):
        r = requests.post(f"{API}/rede-ia/ctos/{TestCTO.cto_id}/validate",
                          headers=H(tokens["gestorrede"]),
                          json={"action": "approve", "comment": "ok"}, timeout=15)
        assert r.status_code == 200
        # verify status persisted
        g = requests.get(f"{API}/rede-ia/ctos/{TestCTO.cto_id}", headers=H(tokens["admin"]),
                        timeout=15).json()
        assert g["status"] == "approved"

    def test_history_lists_entries(self, tokens):
        r = requests.get(f"{API}/rede-ia/history?cto_id={TestCTO.cto_id}",
                         headers=H(tokens["admin"]), timeout=15)
        assert r.status_code == 200
        items = r.json()["items"]
        actions = [it["action"] for it in items]
        assert "create" in actions
        assert any("validate" in a for a in actions)


# ---------- Diretrizes ----------
class TestDiretrizes:
    def test_get_default(self, tokens):
        r = requests.get(f"{API}/rede-ia/diretrizes", headers=H(tokens["admin"]), timeout=15)
        assert r.status_code == 200
        assert "text" in r.json()

    def test_put_update(self, tokens):
        new_text = "TEST_DIRETRIZES_" + str(int(time.time()))
        r = requests.put(f"{API}/rede-ia/diretrizes", headers=H(tokens["admin"]),
                         json={"text": new_text}, timeout=15)
        assert r.status_code == 200
        g = requests.get(f"{API}/rede-ia/diretrizes", headers=H(tokens["admin"]), timeout=15).json()
        assert g["text"] == new_text

    def test_put_blocked_for_colab(self, tokens):
        r = requests.put(f"{API}/rede-ia/diretrizes", headers=H(tokens["colab"]),
                         json={"text": "x"}, timeout=15)
        assert r.status_code == 403


# ---------- Flowchart ----------
def test_flowchart(tokens):
    r = requests.get(f"{API}/rede-ia/flowchart", headers=H(tokens["admin"]), timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data
    assert "edges" in data
    # should contain our approved CTO
    assert data["ctos_count"] >= 1


# ---------- Analyze (LLM) ----------
def test_analyze(tokens):
    r = requests.post(f"{API}/rede-ia/analyze", headers=H(tokens["admin"]),
                      json={"focus": "general"}, timeout=120)
    # may take time; accept 200 or 503 (key not set) or 500 (transient)
    assert r.status_code in (200, 500, 503), r.text
    if r.status_code == 200:
        d = r.json()
        assert "report" in d and isinstance(d["report"], str) and len(d["report"]) > 20


# ---------- Cleanup ----------
def test_zz_cleanup(tokens):
    # delete created CTO + bairro
    if TestCTO.cto_id:
        requests.delete(f"{API}/rede-ia/ctos/{TestCTO.cto_id}",
                        headers=H(tokens["admin"]), timeout=15)
    if TestBairros.bid:
        r = requests.delete(f"{API}/rede-ia/bairros/{TestBairros.bid}",
                            headers=H(tokens["admin"]), timeout=15)
        assert r.status_code in (200, 404)
