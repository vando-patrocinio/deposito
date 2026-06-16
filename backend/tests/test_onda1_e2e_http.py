"""ONDA 1 — E2E HTTP test against running backend (localhost:8001).

Tests all 7 destructive routes via real HTTP + JWT (auditor and gestor).
Validates per agent-to-agent contract:
  (1) HTTP 400 when reason missing
  (2) audit_id and audit_hash present in 200 response
  (3) destructive_actions_audit doc has before_snapshot.docs full dump
  (4) after_snapshot attached with verified_at timestamp
  (5) cross-reference (destructive_audit_id) appears in legacy logs
  (6) wipe_all_tickets emits reverse trail in inventory_os_movements_audit
  (7) audit_hash is SHA-256 hex (64 chars)

Uses isolated tenant TEST_CID = "co-onda1-testing-agent" — does NOT touch co-demo.
"""
from __future__ import annotations

import os
import re
import sys
import time
import uuid
import asyncio
import pytest
import requests
from pathlib import Path

# Make backend imports work
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Load backend .env early so auth.create_access_token finds JWT_SECRET
from dotenv import load_dotenv  # type: ignore
load_dotenv(str(ROOT / ".env"))

from auth import create_access_token  # noqa: E402
from database import db  # noqa: E402
from services.destructive_audit import PHYSICAL_COLLECTION as DA_COLLECTION  # noqa: E402

BASE_URL = "http://localhost:8001"  # internal, bypass ingress
TEST_CID = "co-onda1-testing-agent"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

AUDITOR = {
    "id": "u-test-auditor-onda1",
    "email": "auditor.onda1@test.local",
    "name": "Auditor Onda1",
    "role": "auditor",
    "active": True,
    "company_id": TEST_CID,
}
GESTOR = {
    "id": "u-test-gestor-onda1",
    "email": "gestor.onda1@test.local",
    "name": "Gestor Onda1",
    "role": "gestor",
    "active": True,
    "company_id": TEST_CID,
}


# ─── async helpers ──────────────────────────────────────────────────────────
def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _seed():
    # Wipe fixtures
    for c in ("users", "stok_onts", "stok_consumables", "stok_history",
              "stok_stock", "stok_admin_log", "purchases",
              "purchases_deletion_audit", "tickets", "lousa_logs",
              "inventory_os_movements_audit", DA_COLLECTION):
        await db[c].delete_many({"company_id": TEST_CID})
    # Insert users (no password_hash needed; auth path only checks active)
    await db.users.delete_many({"id": {"$in": [AUDITOR["id"], GESTOR["id"]]}})
    await db.users.insert_many([dict(AUDITOR), dict(GESTOR)])
    # Seed ONTs for reset_full
    await db.stok_onts.insert_many([
        {"id": f"ont-rf-{i}", "company_id": TEST_CID,
         "mac": f"AA:BB:CC:0{i}:00:00", "scan_sn": f"SN-RF-{i}",
         "model": "FIBERHOME", "status": "disponivel",
         "location_type": "empresa", "location_id": None}
        for i in range(1, 4)
    ])
    await db.stok_consumables.insert_one({
        "id": "cons-rf-1", "company_id": TEST_CID,
        "name": "Cabo Drop", "unit": "m", "qty": 100,
    })


async def _seed_granular():
    await db.stok_onts.insert_many([
        {"id": f"ont-gr-{i}", "company_id": TEST_CID,
         "mac": f"AA:BB:DD:0{i}:00:00", "scan_sn": f"SN-GR-{i}",
         "model": "FIBERHOME", "status": "disponivel",
         "location_type": "colaborador",
         "location_id": "u-tec-1",
         "client_name": None}
        for i in range(1, 3)
    ])


async def _seed_purchase():
    pid = f"pur-{uuid.uuid4().hex[:8]}"
    sfx = uuid.uuid4().hex[:6].upper()
    await db.purchases.insert_one({
        "id": pid, "company_id": TEST_CID, "type": "ont",
        "status": "confirmed", "supplier": "Test Supplier",
        "qty": 2, "unit_cost": 85.0, "total_cost": 170.0,
        "created_at": "2026-01-01T00:00:00Z",
    })
    await db.stok_onts.insert_many([
        {"id": f"ont-pur-{uuid.uuid4().hex[:6]}", "company_id": TEST_CID,
         "mac": f"AA:BB:EE:{sfx[:2]}:{sfx[2:4]}:0{i}", "scan_sn": f"SN-PUR-{sfx}-{i}",
         "model": "FIBERHOME", "status": "disponivel",
         "location_type": "empresa", "purchase_id": pid}
        for i in range(1, 3)
    ])
    return pid


async def _seed_ticket():
    tid = f"tkt-{uuid.uuid4().hex[:8]}"
    await db.tickets.insert_one({
        "id": tid, "company_id": TEST_CID,
        "status": "finalizada",
        "os_inventory_guardrail": True,
        "client_id": "cli-test-1",
        "client_snapshot": {"name": "Cliente Teste"},
        "completion_data": {"ont": "AA:BB:FF:01:00:00",
                            "ont_sn": "SN-TKT-1"},
        "created_at": "2026-01-01T00:00:00Z",
    })
    return tid


async def _seed_defective(mac: str):
    await db.stok_onts.delete_many({"company_id": TEST_CID, "mac": mac})
    await db.stok_onts.insert_one({
        "id": f"ont-def-{uuid.uuid4().hex[:6]}",
        "company_id": TEST_CID, "mac": mac,
        "scan_sn": f"SN-DEF-{uuid.uuid4().hex[:6]}",
        "model": "FIBERHOME", "status": "defeito_em_analise",
        "location_type": "empresa",
    })


async def _audit_doc(audit_id: str):
    return await db[DA_COLLECTION].find_one({"id": audit_id}, {"_id": 0})


# ─── pytest fixtures ────────────────────────────────────────────────────────
@pytest.fixture(scope="module", autouse=True)
def seed_module():
    _run(_seed())
    yield
    # leave fixtures for inspection


@pytest.fixture(scope="module")
def auditor_headers():
    tok = create_access_token(
        user_id=AUDITOR["id"], email=AUDITOR["email"],
        role="auditor", company_id=TEST_CID,
    )
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def gestor_headers():
    tok = create_access_token(
        user_id=GESTOR["id"], email=GESTOR["email"],
        role="gestor", company_id=TEST_CID,
    )
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ─── Helpers ────────────────────────────────────────────────────────────────
def _assert_audit_response(data: dict):
    assert "audit_id" in data, f"audit_id missing: {data}"
    assert "audit_hash" in data, f"audit_hash missing: {data}"
    assert HEX64.match(data["audit_hash"]), f"audit_hash not SHA-256 64hex: {data['audit_hash']!r}"


def _assert_audit_doc(doc: dict, *, action_type: str, min_docs: int = 1):
    assert doc is not None, "audit doc not persisted"
    assert doc["action_type"] == action_type
    assert doc["company_id"] == TEST_CID
    assert HEX64.match(doc["audit_hash"])
    assert doc.get("before_snapshot"), "before_snapshot missing"
    docs = doc["before_snapshot"].get("docs") or []
    assert len(docs) >= min_docs, f"before_snapshot.docs has only {len(docs)} (expected ≥{min_docs})"
    # after_snapshot attached
    after = doc.get("after_snapshot")
    assert after is not None, "after_snapshot not attached"
    assert "verified_at" in after, "after_snapshot.verified_at missing"


# ═══════════ Onda 1.2 — stok_admin/reset ═══════════════════════════════════
class TestOnda12Reset:
    def test_reset_rejects_without_reason(self, auditor_headers):
        r = requests.post(f"{BASE_URL}/api/stok/admin/reset",
                          headers=auditor_headers,
                          json={"confirm": "ZERAR ESTOQUE"})
        assert r.status_code == 400, r.text
        body = r.json()
        # FastAPI HTTPException(400, dict) → {"detail": {...}}
        det = body.get("detail", body)
        if isinstance(det, dict):
            assert det.get("error") == "destructive_reason_required"

    def test_reset_happy_path(self, auditor_headers):
        # re-seed fresh
        _run(_seed())
        r = requests.post(f"{BASE_URL}/api/stok/admin/reset",
                          headers=auditor_headers,
                          json={"confirm": "ZERAR ESTOQUE",
                                "reset_history": True,
                                "reset_onts": True,
                                "reset_insumos": True,
                                "reason": {"code": "Inventário incorreto"}})
        assert r.status_code == 200, r.text
        data = r.json()
        _assert_audit_response(data)

        # Validate audit doc
        doc = _run(_audit_doc(data["audit_id"]))
        _assert_audit_doc(doc, action_type="stok_reset_full", min_docs=3)
        # After delete: counts must be 0
        post_count = _run(db.stok_onts.count_documents({"company_id": TEST_CID}))
        assert post_count == 0

        # Cross-reference in stok_admin_log
        log = _run(db.stok_admin_log.find_one(
            {"company_id": TEST_CID,
             "destructive_audit_id": data["audit_id"]}))
        assert log is not None, "stok_admin_log missing cross-reference"


# ═══════════ Onda 1.2 — stok_admin/reset-granular ══════════════════════════
class TestOnda12ResetGranular:
    def test_granular_rejects_without_reason(self, auditor_headers):
        _run(_seed_granular())
        r = requests.post(f"{BASE_URL}/api/stok/admin/reset-granular",
                          headers=auditor_headers,
                          json={"confirm": "ZERAR ESTOQUE",
                                "scope": "collaborator",
                                "target_id": "u-tec-1"})
        assert r.status_code == 400, r.text

    def test_granular_happy_path(self, auditor_headers):
        _run(_seed_granular())
        r = requests.post(f"{BASE_URL}/api/stok/admin/reset-granular",
                          headers=auditor_headers,
                          json={"confirm": "ZERAR ESTOQUE",
                                "scope": "collaborator",
                                "target_id": "u-tec-1",
                                "reason": {"code": "Erro operacional"}})
        assert r.status_code == 200, r.text
        data = r.json()
        _assert_audit_response(data)
        doc = _run(_audit_doc(data["audit_id"]))
        _assert_audit_doc(doc, action_type="stok_reset_granular", min_docs=1)


# ═══════════ Onda 1.3 — DELETE /purchases/{id} ═════════════════════════════
class TestOnda13DeletePurchase:
    def test_delete_rejects_without_reason_code(self, auditor_headers):
        pid = _run(_seed_purchase())
        r = requests.delete(f"{BASE_URL}/api/purchases/{pid}",
                            headers=auditor_headers)
        assert r.status_code == 400, r.text

    def test_delete_happy_path(self, auditor_headers):
        pid = _run(_seed_purchase())
        r = requests.delete(
            f"{BASE_URL}/api/purchases/{pid}"
            f"?reason_code=Devolu%C3%A7%C3%A3o%20fornecedor",
            headers=auditor_headers)
        assert r.status_code == 200, r.text
        data = r.json()
        _assert_audit_response(data)
        doc = _run(_audit_doc(data["audit_id"]))
        # before_snapshot.docs deve conter purchase (1) + ONTs (2) = 3 docs
        _assert_audit_doc(doc, action_type="delete_purchase", min_docs=3)
        # Legacy audit cross-reference
        leg = _run(db.purchases_deletion_audit.find_one({
            "company_id": TEST_CID, "deleted_purchase_id": pid,
            "destructive_audit_id": data["audit_id"]}))
        assert leg is not None, "purchases_deletion_audit missing cross-ref"


# ═══════════ Onda 1.3 — POST /purchases/batch-delete ═══════════════════════
class TestOnda13BatchDelete:
    def test_batch_rejects_without_reason(self, auditor_headers):
        pid = _run(_seed_purchase())
        r = requests.post(f"{BASE_URL}/api/purchases/batch-delete",
                          headers=auditor_headers,
                          json={"ids": [pid]})
        assert r.status_code == 400, r.text

    def test_batch_happy_path(self, auditor_headers):
        pid1 = _run(_seed_purchase())
        pid2 = _run(_seed_purchase())
        r = requests.post(f"{BASE_URL}/api/purchases/batch-delete",
                          headers=auditor_headers,
                          json={"ids": [pid1, pid2],
                                "reason": {"code": "Duplicidade de cadastro"}})
        assert r.status_code == 200, r.text
        data = r.json()
        results = data.get("results") or []
        ok_results = [x for x in results if x.get("ok")]
        assert len(ok_results) == 2, f"Expected 2 oks, got: {results}"
        # One audit per id
        for item in ok_results:
            assert item.get("audit_id")
            doc = _run(_audit_doc(item["audit_id"]))
            _assert_audit_doc(doc, action_type="batch_delete_purchases",
                              min_docs=1)


# ═══════════ Onda 1.3 — POST /lousa/tickets/wipe-all ═══════════════════════
class TestOnda13WipeTickets:
    def test_wipe_rejects_without_reason(self, auditor_headers):
        _run(_seed_ticket())
        r = requests.post(f"{BASE_URL}/api/lousa/tickets/wipe-all",
                          headers=auditor_headers,
                          json={"confirm": "APAGAR TUDO"})
        assert r.status_code == 400, r.text

    def test_wipe_happy_path_with_reverse_trail(self, auditor_headers):
        tid = _run(_seed_ticket())
        r = requests.post(
            f"{BASE_URL}/api/lousa/tickets/wipe-all",
            headers=auditor_headers,
            json={"confirm": "APAGAR TUDO",
                  "reason": {"code": "Determinação diretoria"}})
        assert r.status_code == 200, r.text
        data = r.json()
        _assert_audit_response(data)
        doc = _run(_audit_doc(data["audit_id"]))
        _assert_audit_doc(doc, action_type="wipe_tickets", min_docs=1)

        # Reverse trail in inventory_os_movements_audit
        mv = _run(db.inventory_os_movements_audit.find_one({
            "company_id": TEST_CID,
            "movement_type": "ticket_reopen_revert",
            "destructive_audit_id": data["audit_id"]}))
        assert mv is not None, "reverse compensation movement missing"
        assert mv.get("reason") == "ticket_wipe_compensation"
        assert HEX64.match(mv.get("audit_hash") or "")

        # lousa_logs cross-reference
        log = _run(db.lousa_logs.find_one({
            "company_id": TEST_CID,
            "destructive_audit_id": data["audit_id"]}))
        assert log is not None, "lousa_logs cross-ref missing"


# ═══════════ Onda 1.4 — scrap/revert defective ONT ═════════════════════════
class TestOnda14ScrapRevert:
    def test_scrap_rejects_without_code(self, gestor_headers):
        mac = "AA:BB:00:01:00:00"
        _run(_seed_defective(mac))
        r = requests.post(
            f"{BASE_URL}/api/stok/defective-onts/{mac}/scrap",
            headers=gestor_headers, json={})
        assert r.status_code == 400, r.text

    def test_scrap_happy_path(self, gestor_headers):
        mac = "AA:BB:00:02:00:00"
        _run(_seed_defective(mac))
        r = requests.post(
            f"{BASE_URL}/api/stok/defective-onts/{mac}/scrap",
            headers=gestor_headers,
            json={"code": "Equipamento condenado"})
        assert r.status_code == 200, r.text
        data = r.json()
        _assert_audit_response(data)
        assert data["new_status"] == "sucateada"
        doc = _run(_audit_doc(data["audit_id"]))
        _assert_audit_doc(doc, action_type="scrap_ont", min_docs=1)
        # ONT now scrapped
        ont = _run(db.stok_onts.find_one({"company_id": TEST_CID, "mac": mac}))
        assert ont["status"] == "sucateada"
        assert ont.get("destructive_audit_id") == data["audit_id"]

    def test_revert_rejects_without_code(self, gestor_headers):
        mac = "AA:BB:00:03:00:00"
        _run(_seed_defective(mac))
        r = requests.post(
            f"{BASE_URL}/api/stok/defective-onts/{mac}/revert",
            headers=gestor_headers, json={})
        assert r.status_code == 400, r.text

    def test_revert_happy_path_outro_requires_20_chars(self, gestor_headers):
        mac = "AA:BB:00:04:00:00"
        _run(_seed_defective(mac))
        # Reject if details < 20 chars
        r1 = requests.post(
            f"{BASE_URL}/api/stok/defective-onts/{mac}/revert",
            headers=gestor_headers,
            json={"code": "Outro", "details": "curto"})
        assert r1.status_code == 400, r1.text
        # Accept with >=20 chars
        r2 = requests.post(
            f"{BASE_URL}/api/stok/defective-onts/{mac}/revert",
            headers=gestor_headers,
            json={"code": "Outro",
                  "details": "Reverter por solicitação do supervisor da regional ABC"})
        assert r2.status_code == 200, r2.text
        data = r2.json()
        _assert_audit_response(data)
        assert data["new_status"] == "disponivel"
        doc = _run(_audit_doc(data["audit_id"]))
        _assert_audit_doc(doc, action_type="revert_defective_ont", min_docs=1)


# ═══════════ Cross-cutting: validates DESTRUCTIVE_REASONS whitelist ═══════
class TestCrossCutting:
    def test_invalid_reason_code_rejected(self, auditor_headers):
        _run(_seed())
        r = requests.post(f"{BASE_URL}/api/stok/admin/reset",
                          headers=auditor_headers,
                          json={"confirm": "ZERAR ESTOQUE",
                                "reason": {"code": "MOTIVO INVENTADO"}})
        assert r.status_code == 400, r.text

    def test_outro_requires_20_chars_in_reset(self, auditor_headers):
        _run(_seed())
        r = requests.post(f"{BASE_URL}/api/stok/admin/reset",
                          headers=auditor_headers,
                          json={"confirm": "ZERAR ESTOQUE",
                                "reason": {"code": "Outro",
                                            "details": "muito curto"}})
        assert r.status_code == 400, r.text

    def test_destructive_collection_isolated(self):
        """destructive_actions_audit deve ser collection SEPARADA das outras."""
        cnt = _run(db[DA_COLLECTION].count_documents({"company_id": TEST_CID}))
        assert cnt >= 1, "no destructive_actions_audit docs persisted"
        # Verify NOT same as legacy
        assert DA_COLLECTION == "destructive_actions_audit"
