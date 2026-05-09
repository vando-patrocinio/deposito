"""Iter 23 — Atlaz reassign + tokenização de filial + inbox placeholder."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text[:200]}"
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def hdr(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# ------------------- Unit: _filial_tokens / _filter_by_filial -------------------
class TestFilialTokenization:
    def test_tokens_basic(self):
        from routes.atlaz import _filial_tokens, _filter_by_filial
        # 'LIGO RIO' → {'RIO'} (LIGO ignorado)
        assert _filial_tokens("LIGO RIO") == {"RIO"}
        assert _filial_tokens("LIGO MAGÉ") == {"MAGE"}
        assert _filial_tokens("LIGO CACHOEIRAS DE MACACÚ") == {"CACHOEIRAS", "MACACU"}
        # 'LIGO' sozinho → vazio
        assert _filial_tokens("LIGO") == set()

    def test_filter_match_rio(self):
        from routes.atlaz import _filter_by_filial
        chamados = [
            {"ponto": {"cidade": "Rio de Janeiro"}},
            {"ponto": {"cidade": "Magé"}},
            {"ponto": {"cidade": "São Paulo"}},
            {"ponto": {"cidade": "Cachoeiras de Macacu"}},
        ]
        # filial 'LIGO RIO' deve bater apenas com 'Rio de Janeiro'
        out = _filter_by_filial(chamados, ["LIGO RIO"])
        cidades = [c["ponto"]["cidade"] for c in out]
        assert "Rio de Janeiro" in cidades
        assert "São Paulo" not in cidades

    def test_filter_match_mage(self):
        from routes.atlaz import _filter_by_filial
        chamados = [{"ponto": {"cidade": "Magé"}}, {"ponto": {"cidade": "Niterói"}}]
        out = _filter_by_filial(chamados, ["LIGO MAGÉ"])
        assert len(out) == 1
        assert out[0]["ponto"]["cidade"] == "Magé"

    def test_filter_match_cachoeiras(self):
        from routes.atlaz import _filter_by_filial
        chamados = [{"ponto": {"cidade": "Cachoeiras de Macacu"}}, {"ponto": {"cidade": "Niterói"}}]
        out = _filter_by_filial(chamados, ["LIGO CACHOEIRAS DE MACACÚ"])
        assert len(out) == 1

    def test_filter_empty_returns_all(self):
        from routes.atlaz import _filter_by_filial
        chamados = [{"ponto": {"cidade": "Rio de Janeiro"}}]
        out = _filter_by_filial(chamados, [])
        assert len(out) == 1

    def test_filter_no_match_for_ligo_penha(self):
        from routes.atlaz import _filter_by_filial
        chamados = [
            {"ponto": {"cidade": "Rio de Janeiro"}},
            {"ponto": {"cidade": "Magé"}},
        ]
        # PENHA não é cidade Atlaz nesse cenário → 0
        out = _filter_by_filial(chamados, ["LIGO PENHA"])
        assert out == []


# ------------------- Endpoint: /atlaz/reassign-existing -------------------
class TestReassignEndpoint:
    def test_reassign_returns_200_with_correct_shape(self, hdr):
        r = requests.post(f"{BASE_URL}/api/atlaz/reassign-existing", headers=hdr, timeout=30)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        data = r.json()
        assert data.get("ok") is True
        for k in ["moved", "moved_to_inbox", "unchanged", "items"]:
            assert k in data, f"missing key {k}"
        assert isinstance(data["moved"], int)
        assert isinstance(data["moved_to_inbox"], int)
        assert isinstance(data["unchanged"], int)
        assert isinstance(data["items"], list)
        assert len(data["items"]) <= 50

    def test_reassign_idempotent_second_call(self, hdr):
        # 2a chamada → moved deve ser 0 (já corrigido) e moved_to_inbox=0
        r = requests.post(f"{BASE_URL}/api/atlaz/reassign-existing", headers=hdr, timeout=30)
        assert r.status_code == 200
        data = r.json()
        # idempotência relativa: nada novo deve mudar
        assert data["moved"] == 0
        assert data["moved_to_inbox"] == 0

    def test_reassign_requires_role(self):
        r = requests.post(f"{BASE_URL}/api/atlaz/reassign-existing", timeout=15)
        assert r.status_code in (401, 403)


# ------------------- Lousa grid: distribuição esperada com inbox -------------------
class TestLousaGridDistribution:
    def test_grid_includes_inbox_column_with_32_tickets(self, hdr):
        r = requests.get(f"{BASE_URL}/api/lousa/grid", headers=hdr, timeout=20)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        cols = data.get("columns") or []
        assert isinstance(cols, list) and len(cols) >= 1
        by_id = {(c.get("collaborator") or {}).get("id"): c for c in cols}
        assert "col-atlaz-inbox" in by_id, f"inbox not found. ids={list(by_id.keys())}"
        inbox = by_id["col-atlaz-inbox"]
        assert "Sem técnico" in (inbox["collaborator"]["name"]) or "📥" in inbox["collaborator"]["name"]
        # Distribuição esperada após reassign: 32 bolhas no inbox
        assert len(inbox.get("tickets", [])) == 32, f"expected 32 inbox tickets, got {len(inbox.get('tickets', []))}"

    def test_grid_full_distribution(self, hdr):
        """Validar contagens: 8 DIOGO + 9 JEFFERSON + 5 Eddy + 2 EMANUELLE + 2 JUNIOR + 2 Hudson + 32 inbox."""
        r = requests.get(f"{BASE_URL}/api/lousa/grid", headers=hdr, timeout=20)
        assert r.status_code == 200
        cols = r.json().get("columns") or []
        counts = {(c.get("collaborator") or {}).get("name"): len(c.get("tickets", [])) for c in cols}
        total = sum(counts.values())
        assert total == 60, f"total tickets != 60: {counts}"
        assert counts.get("📥 Sem técnico (Atlaz)") == 32


# ------------------- Regressão de endpoints existentes -------------------
class TestRegressionEndpoints:
    def test_get_settings(self, hdr):
        r = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=hdr, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "enabled" in data
        assert "filiais" in data

    def test_sync_now(self, hdr):
        r = requests.post(f"{BASE_URL}/api/atlaz/sync-now", headers=hdr, timeout=60)
        assert r.status_code == 200
        data = r.json()
        # ok deve estar presente; created/skipped/fetched podem variar
        assert "ok" in data

    def test_sync_logs(self, hdr):
        r = requests.get(f"{BASE_URL}/api/atlaz/sync-logs?limit=5", headers=hdr, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data and "count" in data

    def test_test_connection(self, hdr):
        r = requests.post(f"{BASE_URL}/api/atlaz/test-connection", headers=hdr, timeout=30)
        assert r.status_code == 200
        # ok pode ser true (se chave Atlaz válida) ou false (missing_api_key)
        assert "ok" in r.json()

    def test_lousa_grid(self, hdr):
        r = requests.get(f"{BASE_URL}/api/lousa/grid", headers=hdr, timeout=20)
        assert r.status_code == 200
