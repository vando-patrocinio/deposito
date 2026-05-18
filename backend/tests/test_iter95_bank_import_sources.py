"""Iter 95 — Bank Import extended to 3 sources (Sicoob/Outros/Atlaz).

Validates:
  - POST /upload?source=sicoob still works (regression iter94)
  - POST /upload?source=outros stores source='outros' in staging
  - GET /atlaz-summary returns paid_invoices + first/last paid_date
  - POST /atlaz-fetch with valid window returns staging w/ source='atlaz'
  - POST /atlaz-fetch with empty window returns 404
  - Confirm works for atlaz staging (income movement created)
"""
import os
import uuid
import pytest
import requests

# Load REACT_APP_BACKEND_URL from frontend/.env if not in env
if not os.environ.get("REACT_APP_BACKEND_URL"):
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    os.environ["REACT_APP_BACKEND_URL"] = line.split(
                        "=", 1)[1].strip()
                    break
    except Exception:
        pass

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"
RUN_TAG = uuid.uuid4().hex[:6].upper()


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
    r = session.get(f"{API}/financeiro/cash-accounts", timeout=20)
    assert r.status_code == 200
    accs = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
    assert accs, "no cash account available"
    return accs[0]


def _make_ofx(transactions):
    """Build minimal OFX from list of (date, amount, fitid, memo)."""
    parts = []
    for date, amount, fitid, memo in transactions:
        ttype = "CREDIT" if amount > 0 else "DEBIT"
        parts.append(
            f"<STMTTRN>\n<TRNTYPE>{ttype}\n<DTPOSTED>{date}\n"
            f"<TRNAMT>{amount:.2f}\n<FITID>{fitid}\n<MEMO>{memo}\n"
            f"</STMTTRN>\n")
    return (
        "OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\nSECURITY:NONE\n"
        "ENCODING:USASCII\nCHARSET:1252\nCOMPRESSION:NONE\n"
        "OLDFILEUID:NONE\nNEWFILEUID:NONE\n\n<OFX>\n<BANKMSGSRSV1>\n"
        "<STMTTRNRS>\n<STMTRS>\n<CURDEF>BRL\n<BANKACCTFROM>\n<BANKID>756\n"
        "<ACCTID>00012345\n<ACCTTYPE>CHECKING\n</BANKACCTFROM>\n"
        "<BANKTRANLIST>\n<DTSTART>20260201\n<DTEND>20260228\n"
        + "".join(parts)
        + "</BANKTRANLIST>\n<LEDGERBAL>\n<BALAMT>0.00\n<DTASOF>20260228\n"
        "</LEDGERBAL>\n</STMTRS>\n</STMTTRNRS>\n</BANKMSGSRSV1>\n</OFX>\n"
    )


# ----------------- Tests -------------------------

class TestUploadSources:
    """Regression + extension for /upload?source=..."""

    def test_upload_sicoob_default(self, session):
        ofx = _make_ofx([
            ("20260210", 100.00, f"S{RUN_TAG}1",
             f"PIX REC TEST {RUN_TAG} SICOOB"),
        ]).encode("utf-8")
        files = {"file": (f"sicoob_{RUN_TAG}.ofx", ofx,
                          "application/x-ofx")}
        r = session.post(
            f"{API}/financeiro/bank-import/upload?source=sicoob",
            files=files, timeout=120)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data["total"] == 1
        sid = data["staging_id"]
        # Verify source persisted in staging doc
        g = session.get(
            f"{API}/financeiro/bank-import/staging/{sid}", timeout=20)
        assert g.status_code == 200
        assert g.json().get("source") == "sicoob"

    def test_upload_outros_source_persisted(self, session):
        ofx = _make_ofx([
            ("20260211", 222.00, f"O{RUN_TAG}1",
             f"PIX REC TEST {RUN_TAG} OUTROS BCO"),
        ]).encode("utf-8")
        files = {"file": (f"outros_{RUN_TAG}.ofx", ofx,
                          "application/x-ofx")}
        r = session.post(
            f"{API}/financeiro/bank-import/upload?source=outros",
            files=files, timeout=120)
        assert r.status_code == 200, r.text[:300]
        sid = r.json()["staging_id"]
        g = session.get(
            f"{API}/financeiro/bank-import/staging/{sid}", timeout=20)
        assert g.status_code == 200
        assert g.json().get("source") == "outros", \
            f"expected source='outros', got {g.json().get('source')}"

    def test_upload_invalid_source_falls_back_to_sicoob(self, session):
        ofx = _make_ofx([
            ("20260212", 50.00, f"I{RUN_TAG}", f"TEST {RUN_TAG} INVALID SRC"),
        ]).encode("utf-8")
        files = {"file": (f"x_{RUN_TAG}.ofx", ofx, "application/x-ofx")}
        r = session.post(
            f"{API}/financeiro/bank-import/upload?source=bradesco",
            files=files, timeout=60)
        assert r.status_code == 200
        sid = r.json()["staging_id"]
        g = session.get(
            f"{API}/financeiro/bank-import/staging/{sid}", timeout=20)
        # Backend coerces unknown source to 'sicoob'
        assert g.json().get("source") == "sicoob"


class TestAtlazFetch:
    """Atlaz: summary + fetch staging + confirm."""

    def test_atlaz_summary(self, session):
        r = session.get(
            f"{API}/financeiro/bank-import/atlaz-summary", timeout=20)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        assert "paid_invoices" in data
        assert "first_paid_date" in data
        assert "last_paid_date" in data
        assert isinstance(data["paid_invoices"], int)
        assert data["paid_invoices"] >= 0
        pytest.atlaz_summary = data

    def test_atlaz_fetch_returns_staging(self, session):
        summary = pytest.atlaz_summary
        if summary["paid_invoices"] == 0:
            pytest.skip("no paid invoices in demo DB")
        # Use the last 7 days around last_paid_date to ensure hits
        last = (summary.get("last_paid_date") or "")[:10]
        first = (summary.get("first_paid_date") or "")[:10]
        body = {"from_date": first, "to_date": last, "limit": 20}
        r = session.post(
            f"{API}/financeiro/bank-import/atlaz-fetch",
            json=body, timeout=120)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        data = r.json()
        assert "staging_id" in data
        assert data["total"] >= 1
        # All items must be income
        for it in data["items"]:
            assert it["type"] == "income", \
                f"expected income, got {it['type']}: {it['description']}"
            assert "ATLAZ" in it["description"].upper()
        # Source persisted as 'atlaz'
        sid = data["staging_id"]
        g = session.get(
            f"{API}/financeiro/bank-import/staging/{sid}", timeout=20)
        assert g.status_code == 200
        assert g.json().get("source") == "atlaz"
        pytest.atlaz_staging = data

    def test_atlaz_fetch_empty_window_returns_404(self, session):
        # Far-future window unlikely to have any paid invoices
        body = {"from_date": "2099-01-01", "to_date": "2099-12-31",
                "limit": 50}
        r = session.post(
            f"{API}/financeiro/bank-import/atlaz-fetch",
            json=body, timeout=30)
        assert r.status_code == 404, f"expected 404, got {r.status_code}"
        detail = (r.json() or {}).get("detail", "")
        assert "fatura" in detail.lower() or "nenhuma" in detail.lower()

    def test_atlaz_confirm_creates_income_movement(self, session,
                                                       cash_account):
        if not hasattr(pytest, "atlaz_staging"):
            pytest.skip("no atlaz staging from previous test")
        staging = pytest.atlaz_staging
        # Confirm only non-duplicate items
        items_payload = []
        for it in staging["items"]:
            items_payload.append({
                "idx": it["idx"],
                "type": it["type"],
                "date": it["date"],
                "amount": it["amount"],
                "description": it["description"],
                "cash_account_id": cash_account["id"],
                "supplier_id": it.get("supplier_id"),
                "category_id": it.get("category_id"),
                "skip": bool(it.get("duplicate")),
            })
        payload = {"staging_id": staging["staging_id"],
                   "items": items_payload}
        r = session.post(f"{API}/financeiro/bank-import/confirm",
                         json=payload, timeout=60)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data["ok"] is True
        # Either created or all-duplicate (still ok)
        assert (data["created"] + data["skipped"]) >= 1
