"""Iter248 — Sprint 3 (Backfill Onda 2 + Refactor AI routes) tests.

Validates:
  T1. DB state: synthetic backfill collection counts.
  T2. Watchtower summary endpoint: alertas.trilha_sintetica/sem_trilha/total.
  T3. Watchtower 4-card schema preserved.
  T4. Refactor code presence (static) — execute_transfer called in
       _move_ont_for_install, _move_ont_for_withdraw and ai_review_decision
       return_to_company; approve_reuse and scrap_defect do NOT call it.
  T5. Idempotency: dry-run script returns 0 orphans (executed via subprocess).

Notes:
  - Backfill foi aplicado offline. Não cria seed nem reset.
  - Refactor end-to-end via finalize OS é exercício fora do escopo deste
    iteration (não há OS aberta com técnico/cliente configurados em estado
    estável). Cobertura aqui é estática + DB-state + endpoint público.
"""
import os
import re
import subprocess
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


@pytest.fixture(scope="module")
def mongo_db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
        timeout=20,
    )
    assert r.status_code == 200, f"Login falhou: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, f"Token ausente: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ─────────────────────────────────────────────────────────────────────
# T1. DB-state: synthetic backfill collection counts
# ─────────────────────────────────────────────────────────────────────
class TestBackfillDBState:
    def test_synthetic_total_31(self, mongo_db):
        n = mongo_db.inventory_movements_synthetic_backfill.count_documents(
            {"company_id": "co-demo"})
        assert n == 31, f"Esperado 31, achou {n}"

    def test_synthetic_needs_human_review_15(self, mongo_db):
        n = mongo_db.inventory_movements_synthetic_backfill.count_documents(
            {"company_id": "co-demo", "needs_human_review": True})
        assert n == 15, f"Esperado 15 needs_human_review, achou {n}"

    def test_synthetic_by_type_breakdown(self, mongo_db):
        pipe = [
            {"$match": {"company_id": "co-demo"}},
            {"$group": {"_id": "$movement_type", "n": {"$sum": 1}}},
        ]
        rows = list(
            mongo_db.inventory_movements_synthetic_backfill.aggregate(pipe))
        by_type = {r["_id"]: r["n"] for r in rows}
        assert by_type.get("synthetic_purchase_genesis_backfill") == 10
        assert by_type.get("synthetic_scan_genesis_backfill") == 6
        assert by_type.get("synthetic_unknown_genesis_backfill") == 15

    def test_canonical_audit_NOT_polluted(self, mongo_db):
        """0 docs com is_synthetic=true em inventory_os_movements_audit."""
        n = mongo_db.inventory_os_movements_audit.count_documents(
            {"company_id": "co-demo", "is_synthetic": True})
        assert n == 0, (
            f"PRINCÍPIO QUEBRADO: canonical foi poluído com is_synthetic=true "
            f"({n} docs).")

    def test_stok_onts_flags_marked(self, mongo_db):
        applied = mongo_db.stok_onts.count_documents(
            {"company_id": "co-demo", "synthetic_backfill_applied": True})
        needs = mongo_db.stok_onts.count_documents({
            "company_id": "co-demo",
            "synthetic_backfill_applied": True,
            "synthetic_backfill_needs_review": True,
        })
        assert applied == 31, f"Esperado 31 ONTs flagadas, achou {applied}"
        assert needs == 15, f"Esperado 15 ONTs needs_review, achou {needs}"


# ─────────────────────────────────────────────────────────────────────
# T2/T3. Watchtower summary endpoint
# ─────────────────────────────────────────────────────────────────────
class TestWatchtowerSummary:
    @pytest.fixture(scope="class")
    def summary(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/watchtower/estoque/summary?fresh=true",
            headers=auth_headers, timeout=30,
        )
        assert r.status_code == 200, (
            f"GET /summary não-200: {r.status_code} {r.text[:300]}")
        return r.json()

    def test_4_cards_schema(self, summary):
        """T3 — schema: 4 cards top-level."""
        for k in ("patrimonio", "operacao", "qualidade", "alertas"):
            assert k in summary, f"Card '{k}' ausente em /summary"

    def test_alertas_has_trilha_sintetica_field(self, summary):
        assert "trilha_sintetica" in summary["alertas"], (
            "Novo campo 'trilha_sintetica' ausente em alertas")

    def test_alertas_trilha_sintetica_eq_15(self, summary):
        assert summary["alertas"]["trilha_sintetica"] == 15, (
            f"trilha_sintetica esperado=15 atual="
            f"{summary['alertas']['trilha_sintetica']}")

    def test_alertas_sem_trilha_residual(self, summary):
        """Após backfill, sem_trilha deve estar próximo de 0 (residual)."""
        st = summary["alertas"]["sem_trilha"]
        assert st <= 5, (
            f"sem_trilha={st} alto demais após backfill — esperava ≤5 "
            f"(documentado: 1).")

    def test_alertas_total_inclui_trilha_sintetica(self, summary):
        """total = autosn + needs_review + sem_trilha + trilha_sintetica
                  + reconciliacoes_30d + duplicadas."""
        a = summary["alertas"]
        expected = (
            a.get("autosn", 0) + a.get("needs_review", 0)
            + a.get("sem_trilha", 0) + a.get("trilha_sintetica", 0)
            + a.get("reconciliacoes_30d", 0) + a.get("duplicadas", 0))
        assert a.get("total") == expected, (
            f"total inconsistente: campo={a.get('total')} computed={expected}")


# ─────────────────────────────────────────────────────────────────────
# T4. Static code review — refactor das 3 rotas AI
# ─────────────────────────────────────────────────────────────────────
class TestAIRoutesRefactor:
    @pytest.fixture(scope="class")
    def stok_src(self):
        with open("/app/backend/routes/stok.py", "r", encoding="utf-8") as f:
            return f.read()

    def test_install_uses_execute_transfer_with_origin_ai_scan_install(
            self, stok_src):
        # _move_ont_for_install — bloco SmartOLT bate (case 1)
        block = stok_src[1600 * 0 + stok_src.find(
            "_move_ont_for_install"):]
        block = block[:block.find("_move_ont_for_withdraw")]
        assert "execute_transfer" in block
        assert "\"origin\": \"ai_scan_install\"" in block
        assert "origin_type=\"tecnico\"" in block
        assert "destination_type=\"cliente\"" in block

    def test_withdraw_unified_via_execute_transfer(self, stok_src):
        block = stok_src[stok_src.find("_move_ont_for_withdraw"):]
        # parar antes da próxima função (router.post depois)
        cut = block.find("\n@router.")
        block = block[:cut] if cut > 0 else block
        assert "execute_transfer" in block
        assert "\"origin\": \"ai_scan_retirada\"" in block
        assert "withdraw_inconsistency" in block
        assert "destination_type=\"tecnico\"" in block

    def test_ai_review_return_to_company_uses_execute_transfer(self, stok_src):
        block = stok_src[stok_src.find("ai_review_decision"):]
        cut = block.find("\n@router.")
        if cut > 0:
            block = block[:cut]
        assert "execute_transfer" in block
        assert "\"origin\": \"ai_review_decision\"" in block
        assert "destination_type=\"empresa\"" in block
        assert "manual=True" in block

    def test_ai_review_approve_reuse_no_transfer(self, stok_src):
        """approve_reuse SEM execute_transfer (apenas update_set)."""
        # localiza bloco approve_reuse até o próximo elif
        i = stok_src.find('decision == "approve_reuse"')
        j = stok_src.find('decision == "return_to_company"', i)
        block = stok_src[i:j]
        assert "execute_transfer" not in block, (
            "approve_reuse NÃO deve chamar execute_transfer")

    def test_ai_review_scrap_defect_no_transfer(self, stok_src):
        i = stok_src.find('decision == "scrap_defect"')
        # avança até próximo bloco lógico (await db.stok_onts.update_one)
        j = stok_src.find("await db.stok_onts.update_one", i)
        block = stok_src[i:j]
        assert "execute_transfer" not in block, (
            "scrap_defect NÃO deve chamar execute_transfer")


# ─────────────────────────────────────────────────────────────────────
# T5. Idempotency: dry-run script
# ─────────────────────────────────────────────────────────────────────
class TestBackfillIdempotency:
    def test_dry_run_zero_orphans(self):
        proc = subprocess.run(
            ["python", "-m", "scripts.backfill_onda2_orphans",
             "--company", "co-demo", "--dry-run"],
            cwd="/app/backend", capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, (
            f"script falhou: rc={proc.returncode} stderr={proc.stderr}")
        out = proc.stdout + proc.stderr
        m = re.search(r"Órfãs detectadas:\s+(\d+)", out)
        assert m, f"Output sem 'Órfãs detectadas': {out}"
        n = int(m.group(1))
        assert n == 0, (
            f"Idempotência QUEBRADA: dry-run retornou {n} órfãos "
            f"(esperado 0). Output:\n{out}")
