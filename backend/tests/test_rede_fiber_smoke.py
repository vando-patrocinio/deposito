"""Smoke tests — Auto-baixa de fibra no mapa interativo + Auditoria.

Cobre:
- POST /api/rede-ia/cables (12fo/6fo/24fo) debita fibra do estoque empresa.
- PUT /cables/{id} faz diff atômico (devolve antigo + debita novo).
- DELETE /cables/{id} faz refund completo.
- GET /map/fiber-kpi retorna timeline + by_type + by_user.
- GET /map/fiber-alerts retorna alertas por threshold.
- POST /cables/bulk-delete EXIGE role 'auditor'.
- bulk-delete sem confirm_token rejeitado.
- bulk-delete com IDs específicos funciona sem token.
- Refund automático ao apagar em lote.
"""
import os

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, pw):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _hdr(t): return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@empresa.com", "123456")


@pytest.fixture(scope="module")
def gestor_tok():
    return _login("gestor@empresa.com", "123456")


@pytest.fixture(scope="module")
def auditor_tok():
    """Vando: super_admin + auditor."""
    return _login("vando@example.com", "vando123")


@pytest.fixture(scope="module")
def two_ces(admin_tok):
    """Cria 2 CEs para conectar cabos. Cleanup ao final do módulo."""
    ce1 = requests.post(f"{API}/rede-ia/ces", headers=_hdr(admin_tok),
                         json={"name": "CE-TEST-SMOKE-A",
                               "lat": -22.95, "lng": -43.20,
                               "capacity_fo": 12, "type": "primaria"},
                         timeout=15).json()
    ce2 = requests.post(f"{API}/rede-ia/ces", headers=_hdr(admin_tok),
                         json={"name": "CE-TEST-SMOKE-B",
                               "lat": -22.951, "lng": -43.205,
                               "capacity_fo": 12, "type": "primaria"},
                         timeout=15).json()
    yield ce1["id"], ce2["id"]
    # cleanup
    for cid in (ce1["id"], ce2["id"]):
        try:
            requests.delete(f"{API}/rede-ia/ces/{cid}",
                              headers=_hdr(admin_tok), timeout=10)
        except Exception:
            pass


def _company_stock(tok, key):
    r = requests.get(f"{API}/stok/stock", headers=_hdr(tok), timeout=10)
    return int(r.json().get("empresa", {}).get(key, 0) or 0)


def _create_cable(tok, ce1, ce2, cable_type="12fo", length_m=50):
    r = requests.post(f"{API}/rede-ia/cables", headers=_hdr(tok),
                       json={"type": cable_type,
                             "from_id": ce1, "from_type": "ce",
                             "to_id": ce2, "to_type": "ce",
                             "length_m": length_m},
                       timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
class TestAutoDebitOnCableCreate:
    def test_create_12fo_cable_debits_company(self, admin_tok, two_ces):
        ce1, ce2 = two_ces
        before = _company_stock(admin_tok, "fibra_12fo")
        cab = _create_cable(admin_tok, ce1, ce2, "12fo", 33)
        try:
            after = _company_stock(admin_tok, "fibra_12fo")
            assert after == before - 33, f"esperado {before-33}, got {after}"
            # stok_debit retornado no doc
            sd = cab.get("stok_debit")
            assert sd is not None
            assert sd["consumable_id"] == "fibra_12fo"
            assert sd["meters_signed"] == -33
            assert sd["location"] == "empresa"
        finally:
            requests.delete(f"{API}/rede-ia/cables/{cab['id']}",
                              headers=_hdr(admin_tok), timeout=10)

    def test_update_cable_diff_adjusts_stock(self, admin_tok, two_ces):
        ce1, ce2 = two_ces
        before = _company_stock(admin_tok, "fibra_12fo")
        cab = _create_cable(admin_tok, ce1, ce2, "12fo", 50)
        try:
            mid = _company_stock(admin_tok, "fibra_12fo")
            assert mid == before - 50
            # update p/ 80m: devolve 50, debita 80 -> net -30 sobre before
            r = requests.put(f"{API}/rede-ia/cables/{cab['id']}",
                              headers=_hdr(admin_tok),
                              json={"type": "12fo",
                                    "from_id": ce1, "from_type": "ce",
                                    "to_id": ce2, "to_type": "ce",
                                    "length_m": 80},
                              timeout=15)
            assert r.status_code == 200, r.text
            after = _company_stock(admin_tok, "fibra_12fo")
            assert after == before - 80, f"esperado {before-80}, got {after}"
        finally:
            requests.delete(f"{API}/rede-ia/cables/{cab['id']}",
                              headers=_hdr(admin_tok), timeout=10)

    def test_delete_cable_refunds_full(self, admin_tok, two_ces):
        ce1, ce2 = two_ces
        before = _company_stock(admin_tok, "fibra_12fo")
        cab = _create_cable(admin_tok, ce1, ce2, "12fo", 42)
        assert _company_stock(admin_tok, "fibra_12fo") == before - 42
        # delete
        r = requests.delete(f"{API}/rede-ia/cables/{cab['id']}",
                              headers=_hdr(admin_tok), timeout=10)
        assert r.status_code == 200
        after = _company_stock(admin_tok, "fibra_12fo")
        assert after == before, f"refund falhou: {before} -> {after}"

    def test_drop_cable_does_not_debit_fiber(self, admin_tok, two_ces):
        """drop não está em _CABLE_TYPE_TO_STOK_ID — não deve mexer em fibra."""
        ce1, ce2 = two_ces
        before = _company_stock(admin_tok, "fibra_12fo")
        cab = _create_cable(admin_tok, ce1, ce2, "drop", 20)
        try:
            assert _company_stock(admin_tok, "fibra_12fo") == before
            assert cab.get("stok_debit") is None
        finally:
            requests.delete(f"{API}/rede-ia/cables/{cab['id']}",
                              headers=_hdr(admin_tok), timeout=10)


# ---------------------------------------------------------------------------
class TestFiberKpiAndAlerts:
    def test_fiber_kpi_basic(self, admin_tok):
        r = requests.get(f"{API}/rede-ia/map/fiber-kpi?days=7",
                          headers=_hdr(admin_tok), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "total_meters" in d
        assert "by_type" in d
        assert set(d["by_type"].keys()) >= {"6fo", "12fo", "24fo"}
        assert "by_user" in d
        assert "timeline" in d
        # timeline tem 7 entradas (1 por dia)
        assert len(d["timeline"]) == 7
        for t in d["timeline"]:
            assert "date" in t and "meters" in t

    def test_fiber_alerts_endpoint(self, admin_tok):
        r = requests.get(f"{API}/rede-ia/map/fiber-alerts?threshold_m=10000",
                          headers=_hdr(admin_tok), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["threshold"] == 10000
        assert isinstance(d["alerts"], list)
        # Com threshold gigantesco, qualquer fibra cadastrada vira alerta
        for a in d["alerts"][:3]:
            assert "location_label" in a and "qty" in a
            assert a["severity"] in ("critical", "warning", "info")


# ---------------------------------------------------------------------------
class TestAuditBulkDelete:
    def test_gestor_cannot_bulk_delete(self, gestor_tok):
        r = requests.post(f"{API}/rede-ia/cables/bulk-delete",
                           headers=_hdr(gestor_tok),
                           json={"cable_types": ["12fo"],
                                 "confirm_token": "APAGAR LANCAMENTOS"},
                           timeout=10)
        assert r.status_code == 403, r.text

    def test_auditor_bulk_delete_requires_confirm_token(self, auditor_tok):
        """Varredura (sem cable_ids) exige confirm_token literal."""
        r = requests.post(f"{API}/rede-ia/cables/bulk-delete",
                           headers=_hdr(auditor_tok),
                           json={"cable_types": ["12fo"]},  # sem token
                           timeout=10)
        assert r.status_code == 400, r.text
        assert "APAGAR LANCAMENTOS" in r.json().get("detail", "")

    def test_auditor_bulk_delete_by_ids_refunds_stock(self, admin_tok, auditor_tok, two_ces):
        """Auditor apaga IDs específicos + refund automático de fibra."""
        ce1, ce2 = two_ces
        before = _company_stock(admin_tok, "fibra_24fo")
        # Cria 2 cabos 24FO
        cab1 = _create_cable(admin_tok, ce1, ce2, "24fo", 20)
        cab2 = _create_cable(admin_tok, ce1, ce2, "24fo", 30)
        after_create = _company_stock(admin_tok, "fibra_24fo")
        assert after_create == before - 50

        # Bulk delete por IDs (sem confirm_token — não exige p/ IDs específicos)
        r = requests.post(f"{API}/rede-ia/cables/bulk-delete",
                           headers=_hdr(auditor_tok),
                           json={"cable_ids": [cab1["id"], cab2["id"]],
                                 "refund_stock": True},
                           timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["deleted"] == 2
        assert len(d["refunded"]) == 2

        # Saldo retornou
        after_delete = _company_stock(admin_tok, "fibra_24fo")
        assert after_delete == before, \
            f"refund falhou: {before} -> {after_delete} (esperado igual)"

    def test_auditor_bulk_delete_with_token_varredura(self, admin_tok, auditor_tok, two_ces):
        """Varredura por tipo com confirm_token apaga todos do tipo no escopo."""
        ce1, ce2 = two_ces
        before = _company_stock(admin_tok, "fibra_06fo")
        cab1 = _create_cable(admin_tok, ce1, ce2, "6fo", 15)
        cab2 = _create_cable(admin_tok, ce1, ce2, "6fo", 25)
        # Garante que estamos abaixo
        assert _company_stock(admin_tok, "fibra_06fo") == before - 40

        # Bulk delete TODOS 6fo via varredura
        r = requests.post(f"{API}/rede-ia/cables/bulk-delete",
                           headers=_hdr(auditor_tok),
                           json={"cable_types": ["6fo"],
                                 "refund_stock": True,
                                 "confirm_token": "APAGAR LANCAMENTOS"},
                           timeout=20)
        assert r.status_code == 200, r.text
        # Saldo deve ter retornado para >= before (pode subir mais se havia
        # outros cabos 6FO no banco que foram apagados também)
        after = _company_stock(admin_tok, "fibra_06fo")
        assert after >= before
        # E ambos os IDs criados devem estar na lista deletada
        deleted_ids = set(r.json().get("cable_ids", []))
        assert cab1["id"] in deleted_ids
        assert cab2["id"] in deleted_ids
