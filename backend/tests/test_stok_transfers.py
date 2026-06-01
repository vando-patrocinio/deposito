"""Backend tests for stok_transfers endpoints (iter 144).

Cobre fluxo completo:
- Estoque do técnico (Novos+Retirados)
- Estoque do cliente
- Preview-mac (match / mismatch / smartolt ausente)
- Fluxo install MATCH OK (transferência sucesso)
- Fluxo install MISMATCH (pendente_aprovacao_gestor)
- Pending list / approve / reject
- KPIs
- Auth role check (gestor)
"""
from __future__ import annotations

import os
import uuid
import time

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
CID = "co-demo"
TECH_ID = "col-30aafc3c"

# Seed identifiers (used to identify rows for cleanup)
TEST_TAG = f"TEST_iter144_{uuid.uuid4().hex[:6]}"
MAC_MATCH = "AA:BB:CC:DD:EE:11"
MAC_MISMATCH = "CC:DD:EE:FF:00:11"
MAC_SMART_DIFF = "CC:DD:EE:FF:00:99"
MAC_CLIENT_ONT = "DD:EE:FF:00:11:22"
SVC_MATCH = f"svc-{uuid.uuid4().hex[:8]}"
SVC_MISMATCH = f"svc-{uuid.uuid4().hex[:8]}"
SVC_WITHDRAW = f"svc-{uuid.uuid4().hex[:8]}"
CLIENT_ID_MATCH = f"cli-{uuid.uuid4().hex[:8]}"
CLIENT_ID_MISMATCH = f"cli-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def mongo():
    cl = MongoClient(MONGO_URL)
    db = cl[DB_NAME]
    yield db
    # Cleanup ALL test data created
    db.stok_onts.delete_many({"company_id": CID, "mac": {"$in": [MAC_MATCH, MAC_MISMATCH, MAC_CLIENT_ONT]}})
    db.smartolt_onus.delete_many({"company_id": CID, "client_id": {"$in": [CLIENT_ID_MATCH, CLIENT_ID_MISMATCH]}})
    db.stok_services.delete_many({"id": {"$in": [SVC_MATCH, SVC_MISMATCH, SVC_WITHDRAW]}})
    db.stok_pending_transfers.delete_many({"company_id": CID,
                                             "client_id": {"$in": [CLIENT_ID_MATCH, CLIENT_ID_MISMATCH]}})
    db.clients.delete_many({"id": {"$in": [CLIENT_ID_MATCH, CLIENT_ID_MISMATCH]}})
    cl.close()


@pytest.fixture(scope="module")
def gestor_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": "gestor@empresa.com", "password": "123456"})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def H(gestor_token):
    return {"Authorization": f"Bearer {gestor_token}",
              "Content-Type": "application/json"}


@pytest.fixture(scope="module", autouse=True)
def seed_data(mongo, gestor_token):
    """Insere ONTs, clients, smartolt_onus, services no banco."""
    now = "2026-01-01T00:00:00+00:00"
    # Clients
    mongo.clients.update_one(
        {"id": CLIENT_ID_MATCH},
        {"$set": {"id": CLIENT_ID_MATCH, "company_id": CID, "name": "Cliente Match"}},
        upsert=True)
    mongo.clients.update_one(
        {"id": CLIENT_ID_MISMATCH},
        {"$set": {"id": CLIENT_ID_MISMATCH, "company_id": CID, "name": "Cliente Mismatch"}},
        upsert=True)

    # ONT match (novo, com técnico)
    mongo.stok_onts.delete_many({"company_id": CID, "mac": {"$in": [MAC_MATCH, MAC_MISMATCH, MAC_CLIENT_ONT]}})
    mongo.stok_onts.insert_one({
        "company_id": CID, "mac": MAC_MATCH, "model": "Huawei HG8245",
        "location_type": "tecnico", "location_id": TECH_ID,
        "status": "no_estoque", "source": "transferencia_almoxarife",
        "scan_sn": "SN_MATCH_001", "created_at": now,
    })
    mongo.stok_onts.insert_one({
        "company_id": CID, "mac": MAC_MISMATCH, "model": "Huawei HG8245",
        "location_type": "tecnico", "location_id": TECH_ID,
        "status": "no_estoque", "source": "ai_scan_retirada",
        "scan_sn": "SN_MISMATCH_001", "created_at": now,
        "withdrawn_from_client_id": CLIENT_ID_MISMATCH,
        "withdrawn_from_client_name": "Cliente Antigo",
        "withdrawn_by_email": "tec@empresa.com",
        "withdrawn_at": now,
    })
    # ONT vinculada ao cliente (para teste /client/{cid}/onts)
    mongo.stok_onts.insert_one({
        "company_id": CID, "mac": MAC_CLIENT_ONT, "model": "ZTE F660",
        "location_type": "cliente", "location_id": CLIENT_ID_MATCH,
        "status": "instalada", "scan_sn": "SN_CLI_001",
        "client_name": "Cliente Match", "installed_at": now, "created_at": now,
    })

    # smartolt_onus
    mongo.smartolt_onus.delete_many({"company_id": CID, "client_id": {"$in": [CLIENT_ID_MATCH, CLIENT_ID_MISMATCH]}})
    mongo.smartolt_onus.insert_one({
        "company_id": CID, "client_id": CLIENT_ID_MATCH,
        "unique_external_id": MAC_MATCH, "sn": "SN_MATCH_001",
        "status": "online", "name": "Cliente Match",
    })
    mongo.smartolt_onus.insert_one({
        "company_id": CID, "client_id": CLIENT_ID_MISMATCH,
        "unique_external_id": MAC_SMART_DIFF, "sn": "SN_DIFF_999",
        "status": "online", "name": "Cliente Mismatch",
    })

    # Services
    mongo.stok_services.delete_many({"id": {"$in": [SVC_MATCH, SVC_MISMATCH, SVC_WITHDRAW]}})
    mongo.stok_services.insert_one({
        "id": SVC_MATCH, "company_id": CID, "type": "instalacao",
        "client_id": CLIENT_ID_MATCH, "client_name": "Cliente Match",
        "technician_id": TECH_ID, "status": "ativo",
        "created_at": now,
    })
    mongo.stok_services.insert_one({
        "id": SVC_MISMATCH, "company_id": CID, "type": "instalacao",
        "client_id": CLIENT_ID_MISMATCH, "client_name": "Cliente Mismatch",
        "technician_id": TECH_ID, "status": "ativo",
        "created_at": now,
    })
    yield


# ---------------------------------------------------------------------------
# 1. AUTH role check
# ---------------------------------------------------------------------------
class TestAuthGuard:
    def test_no_token_returns_401_or_403(self):
        r = requests.get(f"{BASE_URL}/api/stok/tech/{TECH_ID}/onts")
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}"

    def test_invalid_token_returns_401_or_403(self):
        r = requests.get(f"{BASE_URL}/api/stok/tech/{TECH_ID}/onts",
                          headers={"Authorization": "Bearer invalid_token_xxx"})
        assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# 2. GET /api/stok/tech/{tech_id}/onts (Novos+Retirados)
# ---------------------------------------------------------------------------
class TestTechOnts:
    def test_list_all(self, H):
        r = requests.get(f"{BASE_URL}/api/stok/tech/{TECH_ID}/onts", headers=H)
        assert r.status_code == 200
        d = r.json()
        assert "novos" in d and "retirados" in d and "total" in d
        macs_novos = [o["mac"] for o in d["novos"]]
        macs_retirados = [o["mac"] for o in d["retirados"]]
        assert MAC_MATCH in macs_novos, f"MAC_MATCH não está em novos: {macs_novos}"
        assert MAC_MISMATCH in macs_retirados, f"MAC_MISMATCH (ai_scan_retirada) não está em retirados: {macs_retirados}"

    def test_group_novos(self, H):
        r = requests.get(f"{BASE_URL}/api/stok/tech/{TECH_ID}/onts?group=novos", headers=H)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d and "total" in d
        macs = [o["mac"] for o in d["items"]]
        assert MAC_MATCH in macs
        assert MAC_MISMATCH not in macs  # retirado, não deve estar em novos

    def test_group_retirados(self, H):
        r = requests.get(f"{BASE_URL}/api/stok/tech/{TECH_ID}/onts?group=retirados", headers=H)
        assert r.status_code == 200
        d = r.json()
        macs = [o["mac"] for o in d["items"]]
        assert MAC_MISMATCH in macs
        # Verifica campos withdrawn_*
        item = next(o for o in d["items"] if o["mac"] == MAC_MISMATCH)
        assert item.get("withdrawn_from_client_id") == CLIENT_ID_MISMATCH
        assert item.get("withdrawn_from_client_name") == "Cliente Antigo"
        assert item.get("withdrawn_by_email") == "tec@empresa.com"
        assert item.get("withdrawn_at") is not None


# ---------------------------------------------------------------------------
# 3. GET /api/stok/client/{client_id}/onts
# ---------------------------------------------------------------------------
class TestClientOnts:
    def test_list_client_onts(self, H):
        r = requests.get(f"{BASE_URL}/api/stok/client/{CLIENT_ID_MATCH}/onts", headers=H)
        assert r.status_code == 200
        d = r.json()
        macs = [o["mac"] for o in d["items"]]
        assert MAC_CLIENT_ONT in macs
        item = next(o for o in d["items"] if o["mac"] == MAC_CLIENT_ONT)
        assert item.get("status") == "instalada"


# ---------------------------------------------------------------------------
# 4. GET /api/stok/services/{sid}/preview-mac
# ---------------------------------------------------------------------------
class TestPreviewMac:
    def test_preview_match_ok(self, H):
        r = requests.get(f"{BASE_URL}/api/stok/services/{SVC_MATCH}/preview-mac",
                          params={"mac": MAC_MATCH}, headers=H)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["match"] is True
        assert d["predicted_status"] == "transferencia_sucesso"
        assert d["client_name"] == "Cliente Match"

    def test_preview_mismatch(self, H):
        r = requests.get(f"{BASE_URL}/api/stok/services/{SVC_MISMATCH}/preview-mac",
                          params={"mac": MAC_MISMATCH}, headers=H)
        assert r.status_code == 200
        d = r.json()
        assert d["match"] is False
        assert d["predicted_status"] == "pendente_mac_divergente"

    def test_preview_smartolt_ausente(self, mongo, H):
        # cliente sem smartolt_onus → predicted_status pendente_smartolt_ausente
        tmp_client = f"cli-tmp-{uuid.uuid4().hex[:6]}"
        tmp_svc = f"svc-tmp-{uuid.uuid4().hex[:6]}"
        mongo.stok_services.insert_one({
            "id": tmp_svc, "company_id": CID, "type": "instalacao",
            "client_id": tmp_client, "client_name": "Sem SmartOLT",
            "technician_id": TECH_ID, "status": "ativo",
        })
        try:
            r = requests.get(f"{BASE_URL}/api/stok/services/{tmp_svc}/preview-mac",
                              params={"mac": "11:22:33:44:55:66"}, headers=H)
            assert r.status_code == 200
            d = r.json()
            assert d["match"] is False
            assert d["predicted_status"] == "pendente_smartolt_ausente"
        finally:
            mongo.stok_services.delete_one({"id": tmp_svc})

    def test_preview_empty_mac(self, H):
        """MAC vazio dispara 400. NOTA: normalize_mac apenas .strip().upper(),
        não valida formato — strings inválidas tipo 'INVALID_MAC' passam.
        Reportado em critical_code_review_comments."""
        r = requests.get(f"{BASE_URL}/api/stok/services/{SVC_MATCH}/preview-mac",
                          params={"mac": "   "}, headers=H)
        assert r.status_code == 400

    def test_preview_service_not_found(self, H):
        r = requests.get(f"{BASE_URL}/api/stok/services/svc-does-not-exist/preview-mac",
                          params={"mac": MAC_MATCH}, headers=H)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 5. FLUXO INSTALL MATCH OK
# ---------------------------------------------------------------------------
class TestInstallMatch:
    def test_install_match_moves_to_client(self, H, mongo):
        r = requests.post(
            f"{BASE_URL}/api/stok/services/{SVC_MATCH}/close",
            json={"ont_mac": MAC_MATCH, "used_items": []},
            headers=H,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        # Verifica ONT no banco
        ont = mongo.stok_onts.find_one({"company_id": CID, "mac": MAC_MATCH})
        assert ont is not None
        assert ont["location_type"] == "cliente"
        assert ont["location_id"] == CLIENT_ID_MATCH
        assert ont["status"] == "instalada"


# ---------------------------------------------------------------------------
# 6. FLUXO INSTALL MISMATCH (pending)
# ---------------------------------------------------------------------------
class TestInstallMismatch:
    pending_id_holder = {}

    def test_install_mismatch_creates_pending(self, H, mongo):
        # Move MAC_MISMATCH temporariamente para 'novos' para passar pelo install
        # (o close exige ONT no estoque do técnico — está). Status era retirada_com_tecnico
        # mas a função não checa status, só location.
        r = requests.post(
            f"{BASE_URL}/api/stok/services/{SVC_MISMATCH}/close",
            json={"ont_mac": MAC_MISMATCH, "used_items": []},
            headers=H,
        )
        assert r.status_code == 200, r.text
        # ONT NÃO foi movida, status = pendente_aprovacao_gestor
        ont = mongo.stok_onts.find_one({"company_id": CID, "mac": MAC_MISMATCH})
        assert ont is not None
        assert ont["status"] == "pendente_aprovacao_gestor"
        assert ont.get("pending_install_to_client") == CLIENT_ID_MISMATCH
        # pending_transfer existe
        pt = mongo.stok_pending_transfers.find_one(
            {"company_id": CID, "stock_mac": MAC_MISMATCH, "status": "pending"})
        assert pt is not None
        assert pt["kind"] == "install_mac_mismatch"
        assert pt["client_id"] == CLIENT_ID_MISMATCH
        TestInstallMismatch.pending_id_holder["id"] = pt["id"]


# ---------------------------------------------------------------------------
# 7. GET /api/stok/pending-transfers
# ---------------------------------------------------------------------------
class TestPendingList:
    def test_list_pending(self, H):
        pt_id = TestInstallMismatch.pending_id_holder.get("id")
        assert pt_id, "pending id missing — install mismatch test não rodou"
        r = requests.get(f"{BASE_URL}/api/stok/pending-transfers?status=pending", headers=H)
        assert r.status_code == 200
        d = r.json()
        ids = [i["id"] for i in d["items"]]
        assert pt_id in ids
        item = next(i for i in d["items"] if i["id"] == pt_id)
        # Enriquecimento técnico
        assert "technician_name" in item


# ---------------------------------------------------------------------------
# 8. POST /api/stok/pending-transfers/{id}/reject (testar reject antes de approve em outro)
# ---------------------------------------------------------------------------
class TestRejectAndReapprove:
    def test_reject(self, H, mongo):
        pt_id = TestInstallMismatch.pending_id_holder.get("id")
        r = requests.post(
            f"{BASE_URL}/api/stok/pending-transfers/{pt_id}/reject",
            json={"note": "test reject"}, headers=H)
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "rejected"
        # ONT voltou pro estoque
        ont = mongo.stok_onts.find_one({"company_id": CID, "mac": MAC_MISMATCH})
        assert ont["status"] == "no_estoque"
        assert "pending_install_to_client" not in ont or ont.get("pending_install_to_client") is None

    def test_reject_again_returns_404(self, H):
        pt_id = TestInstallMismatch.pending_id_holder.get("id")
        r = requests.post(
            f"{BASE_URL}/api/stok/pending-transfers/{pt_id}/reject",
            json={"note": ""}, headers=H)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 9. POST /api/stok/pending-transfers/{id}/approve
# ---------------------------------------------------------------------------
class TestApprove:
    """Cria nova pendência, aprova, verifica movimentação."""

    def test_approve_moves_to_client(self, H, mongo):
        # Cria pendência manualmente (já que MAC_MISMATCH foi rejected)
        pt_id = f"pt-{uuid.uuid4().hex[:12]}"
        # Garante que ONT está no estoque do técnico
        mongo.stok_onts.update_one(
            {"company_id": CID, "mac": MAC_MISMATCH},
            {"$set": {"status": "pendente_aprovacao_gestor",
                       "pending_install_to_client": CLIENT_ID_MISMATCH,
                       "pending_transfer_id": pt_id}})
        mongo.stok_pending_transfers.insert_one({
            "id": pt_id, "company_id": CID,
            "service_id": SVC_MISMATCH, "kind": "install_mac_mismatch",
            "technician_id": TECH_ID, "client_id": CLIENT_ID_MISMATCH,
            "client_name": "Cliente Mismatch",
            "stock_mac": MAC_MISMATCH, "status": "pending",
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        r = requests.post(
            f"{BASE_URL}/api/stok/pending-transfers/{pt_id}/approve",
            json={"note": "ok aprovado"}, headers=H)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "approved"
        ont = mongo.stok_onts.find_one({"company_id": CID, "mac": MAC_MISMATCH})
        assert ont["location_type"] == "cliente"
        assert ont["location_id"] == CLIENT_ID_MISMATCH
        assert ont["status"] == "instalada"
        assert ont.get("approved_by_email")
        # Flags pendentes removidas
        assert "pending_install_to_client" not in ont or ont.get("pending_install_to_client") is None

    def test_approve_invalid_id(self, H):
        r = requests.post(
            f"{BASE_URL}/api/stok/pending-transfers/pt-not-exists/approve",
            json={"note": ""}, headers=H)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 10. KPIs
# ---------------------------------------------------------------------------
class TestKpis:
    def test_kpis_30_days(self, H):
        r = requests.get(f"{BASE_URL}/api/stok/transfers/kpis?days=30", headers=H)
        assert r.status_code == 200
        d = r.json()
        for key in ["installed_direct", "pending", "approved", "rejected",
                     "withdrawn", "match_pct", "top_pending_techs", "period_days"]:
            assert key in d, f"missing kpi key: {key}"
        assert d["period_days"] == 30
        assert isinstance(d["top_pending_techs"], list)
        assert len(d["top_pending_techs"]) <= 5
        # Verifica que approved/rejected/installed_direct refletem o que fizemos
        assert d["approved"] >= 1
        assert d["rejected"] >= 1
        assert d["installed_direct"] >= 1
        # match_pct deve ser número
        assert isinstance(d["match_pct"], (int, float))
