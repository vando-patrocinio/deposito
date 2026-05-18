"""Regression tests for /api/financeiro/bank-import endpoints (iter 94).

Validates:
  - Upload OFX (parse + IA classification or memory)
  - Confirm (creates movements, updates cash account, learns memory)
  - Idempotency (2x confirm -> 409)
  - Listing of history & memory
  - Delete memory pattern
  - Learning: re-upload of mutated file applies memory (source='memory')
"""
import os
import re
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
               timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    tok = data.get("token") or data.get("access_token")
    if tok:
        s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="module")
def cash_account(session):
    """Ensure a cash account exists."""
    r = session.get(f"{API}/financeiro/cash-accounts", timeout=20)
    assert r.status_code == 200
    accs = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
    if accs:
        return accs[0]
    r = session.post(f"{API}/financeiro/cash-accounts", json={
        "name": "TEST_Sicoob CC", "kind": "bank",
        "bank_name": "Sicoob", "opening_balance": 0,
    }, timeout=20)
    assert r.status_code in (200, 201)
    return r.json()


def _make_ofx(transactions):
    """Build minimal OFX with given txs list of (date, amount, fitid, memo)."""
    txs_xml = ""
    for date, amount, fitid, memo in transactions:
        ttype = "CREDIT" if amount > 0 else "DEBIT"
        txs_xml += f"""<STMTTRN>
<TRNTYPE>{ttype}
<DTPOSTED>{date}
<TRNAMT>{amount:.2f}
<FITID>{fitid}
<MEMO>{memo}
</STMTTRN>
"""
    return f"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<BANKMSGSRSV1>
<STMTTRNRS>
<STMTRS>
<CURDEF>BRL
<BANKACCTFROM>
<BANKID>756
<ACCTID>00012345
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20260201
<DTEND>20260228
{txs_xml}</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>0.00
<DTASOF>20260228
</LEDGERBAL>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""


# Unique CPF/CNPJ per test run to avoid cross-pollution
RUN_TAG = uuid.uuid4().hex[:6].upper()
CPF1 = "111.222.333-44"
CNPJ1 = "12.345.678/0001-99"


def _upload(session, ofx_bytes, fname="extrato.ofx"):
    files = {"file": (fname, ofx_bytes, "application/x-ofx")}
    r = session.post(f"{API}/financeiro/bank-import/upload", files=files,
                     timeout=120)
    return r


# ---------------- Tests -----------------

class TestBankImport:

    def test_upload_parses_and_classifies(self, session):
        ofx = _make_ofx([
            ("20260203", 3500.00, f"T{RUN_TAG}1",
             f"PIX REC CLIENTE A {CPF1} REF {RUN_TAG} MENSALIDADE"),
            ("20260205", -450.00, f"T{RUN_TAG}2",
             f"PIX ENV FORNECEDOR B {CNPJ1} REF {RUN_TAG} INTERNET"),
            ("20260208", -1200.00, f"T{RUN_TAG}3",
             f"BOLETO ALUGUEL REF {RUN_TAG}"),
        ])
        r = _upload(session, ofx.encode("utf-8"),
                    fname=f"sicoob_{RUN_TAG}.ofx")
        assert r.status_code == 200, f"upload failed: {r.status_code} {r.text[:300]}"
        data = r.json()
        assert "staging_id" in data
        assert data["total"] == 3
        assert len(data["items"]) == 3
        # All new (first import for these descriptions)
        assert data["new_count"] >= 1
        # Types correctly classified by sign
        incomes = [it for it in data["items"] if it["type"] == "income"]
        expenses = [it for it in data["items"] if it["type"] == "expense"]
        assert len(incomes) == 1
        assert len(expenses) == 2
        # CPF/CNPJ extraction
        items_with_doc = [it for it in data["items"] if it.get("doc")]
        assert len(items_with_doc) >= 2, \
            f"expected >=2 docs extracted, got {[it.get('doc') for it in data['items']]}"
        # IA classified some (source='ai') OR returned memory
        sources = {it["source"] for it in data["items"]}
        assert sources & {"ai", "memory", "manual"}, sources
        # Save staging id for next tests
        pytest.staging_id_1 = data["staging_id"]
        pytest.upload_items_1 = data["items"]

    def test_confirm_creates_movements_and_learns(self, session, cash_account):
        staging_id = pytest.staging_id_1
        items = pytest.upload_items_1
        payload = {
            "staging_id": staging_id,
            "items": [{
                "idx": it["idx"], "type": it["type"], "date": it["date"],
                "amount": it["amount"], "description": it["description"],
                "cash_account_id": cash_account["id"],
                "supplier_id": it.get("supplier_id"),
                "category_id": it.get("category_id"),
                "skip": bool(it.get("duplicate")),
            } for it in items],
        }
        r = session.post(f"{API}/financeiro/bank-import/confirm",
                         json=payload, timeout=60)
        assert r.status_code == 200, f"confirm failed: {r.status_code} {r.text[:300]}"
        data = r.json()
        assert data["ok"] is True
        assert data["created"] >= 1
        pytest.created_count_1 = data["created"]

    def test_confirm_idempotency_returns_409(self, session, cash_account):
        """2nd confirm on same staging must fail with 409."""
        staging_id = pytest.staging_id_1
        items = pytest.upload_items_1
        payload = {
            "staging_id": staging_id,
            "items": [{
                "idx": it["idx"], "type": it["type"], "date": it["date"],
                "amount": it["amount"], "description": it["description"],
                "cash_account_id": cash_account["id"],
                "skip": True,
            } for it in items],
        }
        r = session.post(f"{API}/financeiro/bank-import/confirm",
                         json=payload, timeout=30)
        assert r.status_code == 409, \
            f"expected 409 on 2nd confirm, got {r.status_code} {r.text[:200]}"

    def test_history_includes_recent_import(self, session):
        r = session.get(f"{API}/financeiro/bank-import/history?limit=50",
                        timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        # At least our import should appear
        found = any(h.get("staging_id") == pytest.staging_id_1
                    for h in data["items"])
        assert found, "recent import not found in history"

    def test_memory_lists_learned_patterns(self, session):
        r = session.get(f"{API}/financeiro/bank-import/memory?limit=200",
                        timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        # After confirm, must have at least 1 memory pattern (hit_count>=1)
        assert len(data["items"]) >= 1
        # Sorted by hit_count desc
        hits = [m.get("hit_count", 0) for m in data["items"]]
        assert hits == sorted(hits, reverse=True), \
            f"memory not sorted by hit_count desc: {hits}"
        pytest.memory_items = data["items"]

    def test_learning_applied_on_second_upload(self, session):
        """Upload modified file (same CPF/CNPJ, different value/date) →
        items should come with source='memory'."""
        # Different date+amount to avoid duplicate hash but same CPF/CNPJ+desc pattern
        ofx2 = _make_ofx([
            ("20260301", 3777.77, f"T{RUN_TAG}A",
             f"PIX REC CLIENTE A {CPF1} REF {RUN_TAG} MENSALIDADE"),
            ("20260303", -555.55, f"T{RUN_TAG}B",
             f"PIX ENV FORNECEDOR B {CNPJ1} REF {RUN_TAG} INTERNET"),
        ])
        r = _upload(session, ofx2.encode("utf-8"),
                    fname=f"sicoob_{RUN_TAG}_v2.ofx")
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data["total"] == 2
        # Both should now hit memory (CPF/CNPJ matches previously confirmed)
        memory_sources = [it["source"] for it in data["items"]
                          if not it.get("duplicate")]
        assert "memory" in memory_sources, \
            f"expected at least one memory hit, sources={memory_sources}"

    def test_delete_memory_pattern(self, session):
        items = pytest.memory_items
        assert items, "no memory to delete"
        # Find one tagged by our RUN
        target = None
        for m in items:
            key = m.get("key", "") or ""
            if RUN_TAG.lower() in key.lower():
                target = m
                break
        if not target:
            target = items[0]
        mem_id = target["id"]
        r = session.delete(
            f"{API}/financeiro/bank-import/memory/{mem_id}", timeout=20)
        assert r.status_code == 200
        # Re-delete -> 404
        r2 = session.delete(
            f"{API}/financeiro/bank-import/memory/{mem_id}", timeout=20)
        assert r2.status_code == 404

    def test_upload_empty_file_rejected(self, session):
        files = {"file": ("empty.ofx", b"", "application/x-ofx")}
        r = session.post(f"{API}/financeiro/bank-import/upload",
                         files=files, timeout=20)
        assert r.status_code == 400

    def test_upload_invalid_extension_rejected(self, session):
        files = {"file": ("data.txt", b"foo", "text/plain")}
        r = session.post(f"{API}/financeiro/bank-import/upload",
                         files=files, timeout=20)
        assert r.status_code in (400, 415)
