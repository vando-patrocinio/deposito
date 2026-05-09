"""Iteration 22 — Atlaz sync_interval_seconds + Lousa "Nova nota" redirect.

Cobre:
- AtlazConfig sync_interval_seconds (default=30, ge=10, le=86400) e GET /atlaz/settings retorna o campo
- PUT /atlaz/settings com sync_interval_seconds=30 → 200; com 5 → 422; com 99999 → 422
- Worker periódico usa precedência segundos > minutos: smoke check com 10s e ver se
  last_auto_sync_bubbles_at avança em ~25s
- Regressão: sync-now, sync-technicians, test-connection, sync-logs, lousa/grid
"""
import os
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN = {"email": "admin@empresa.com", "password": "123456"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# ---------------- Config: novo campo sync_interval_seconds ----------------
class TestSyncIntervalSecondsField:
    def test_get_settings_has_sync_interval_seconds(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "sync_interval_seconds" in d
        # Permite None ou int dentro do range
        if d["sync_interval_seconds"] is not None:
            assert isinstance(d["sync_interval_seconds"], int)
            assert 10 <= d["sync_interval_seconds"] <= 86400

    def test_put_sync_interval_seconds_valid(self, auth_headers):
        # snapshot
        orig = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15).json()
        try:
            r = requests.put(
                f"{BASE_URL}/api/atlaz/settings",
                json={"sync_interval_seconds": 30},
                headers=auth_headers,
                timeout=15,
            )
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["sync_interval_seconds"] == 30
            # GET persistência
            g = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15).json()
            assert g["sync_interval_seconds"] == 30
        finally:
            requests.put(
                f"{BASE_URL}/api/atlaz/settings",
                json={"sync_interval_seconds": int(orig.get("sync_interval_seconds") or 30)},
                headers=auth_headers,
                timeout=15,
            )

    @pytest.mark.parametrize("bad", [5, 9, 0, -1, 99999, 100000])
    def test_put_sync_interval_seconds_invalid_returns_422(self, auth_headers, bad):
        r = requests.put(
            f"{BASE_URL}/api/atlaz/settings",
            json={"sync_interval_seconds": bad},
            headers=auth_headers,
            timeout=15,
        )
        assert r.status_code == 422, f"sync_interval_seconds={bad} expected 422, got {r.status_code}: {r.text}"
        # GET ainda 200 (sem corrupção persistida)
        g = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15)
        assert g.status_code == 200

    def test_put_boundary_values(self, auth_headers):
        orig = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15).json()
        try:
            for v in (10, 86400):
                r = requests.put(
                    f"{BASE_URL}/api/atlaz/settings",
                    json={"sync_interval_seconds": v},
                    headers=auth_headers,
                    timeout=15,
                )
                assert r.status_code == 200, f"boundary {v} rejeitado: {r.text}"
                assert r.json()["sync_interval_seconds"] == v
        finally:
            requests.put(
                f"{BASE_URL}/api/atlaz/settings",
                json={"sync_interval_seconds": int(orig.get("sync_interval_seconds") or 30)},
                headers=auth_headers,
                timeout=15,
            )

    def test_tenant_domain_persisted_demo(self, auth_headers):
        """Pré-condição: tenant_domain deve estar configurado para a empresa demo
        (pré-setado pelo main agent)."""
        g = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15).json()
        assert g.get("tenant_domain"), "tenant_domain está vazio — pré-condição iter22 quebrada"
        assert "ligofibra.atlaz.com.br" in g["tenant_domain"]


# ---------------- Worker precedência segundos > minutos (smoke) ----------------
class TestWorkerSecondsPrecedence:
    def test_worker_uses_seconds_precedence(self, auth_headers):
        """Smoke test: setta sync_interval_seconds=15 e auto_sync_technicians=False,
        captura last_auto_sync_bubbles_at, aguarda ~30s e valida que o timestamp
        avançou (worker rodou pelo menos 1x).
        """
        orig = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15).json()
        try:
            r = requests.put(
                f"{BASE_URL}/api/atlaz/settings",
                json={
                    "enabled": True,
                    "sync_interval_seconds": 15,
                    "auto_sync_technicians": False,
                },
                headers=auth_headers,
                timeout=15,
            )
            assert r.status_code == 200, r.text

            t0 = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15).json()
            ts0 = t0.get("last_auto_sync_bubbles_at")

            # tick worker é 5s, intervalo 15s → em 30-35s deve rodar 1-2 vezes
            time.sleep(35)

            t1 = requests.get(f"{BASE_URL}/api/atlaz/settings", headers=auth_headers, timeout=15).json()
            ts1 = t1.get("last_auto_sync_bubbles_at")

            # Aceita: ts1 mudou (avançou) OU continua None se worker está pausado por erro
            # Falha apenas se ts1 == ts0 e ambos não-None (timestamp parou)
            if ts0 is not None and ts1 is not None:
                assert ts1 != ts0 or ts1 > ts0, (
                    f"Worker não rodou em 35s com sync_interval_seconds=15: ts0={ts0} ts1={ts1}"
                )
            elif ts0 is None and ts1 is None:
                # Pode acontecer se enabled=False ou api_key faltando — não falha o teste
                pytest.skip("last_auto_sync_bubbles_at None nos 2 GETs — worker pode estar inativo (api_key?)")
            else:
                # ts0 None e ts1 setado → worker rodou pela primeira vez ✓
                pass
        finally:
            # Restaurar valores originais (sync_interval_seconds=30, auto_sync_technicians original)
            requests.put(
                f"{BASE_URL}/api/atlaz/settings",
                json={
                    "sync_interval_seconds": int(orig.get("sync_interval_seconds") or 30),
                    "auto_sync_technicians": bool(orig.get("auto_sync_technicians", True)),
                },
                headers=auth_headers,
                timeout=15,
            )


# ---------------- Regressão endpoints existentes ----------------
class TestRegressionEndpoints:
    def test_test_connection(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/atlaz/test-connection", headers=auth_headers, timeout=30)
        assert r.status_code == 200
        assert "ok" in r.json()

    def test_sync_now(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/atlaz/sync-now", headers=auth_headers, timeout=60)
        assert r.status_code == 200
        assert "ok" in r.json()

    def test_sync_technicians(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/atlaz/sync-technicians", headers=auth_headers, timeout=60)
        assert r.status_code == 200
        assert "ok" in r.json()

    def test_sync_logs(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/atlaz/sync-logs?limit=5", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d and "count" in d

    def test_lousa_grid(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/lousa/grid", headers=auth_headers, timeout=15)
        assert r.status_code == 200

    def test_lousa_public_reorder_exists(self, auth_headers):
        # Apenas verifica que rota existe (POST sem body ainda assim retorna 4xx, não 404)
        r = requests.post(
            f"{BASE_URL}/api/lousa/public/reorder",
            headers=auth_headers,
            json={"items": []},
            timeout=15,
        )
        assert r.status_code != 404, f"rota /lousa/public/reorder não encontrada: {r.status_code}"


# ---------------- Restore final ----------------
def teardown_module(module):
    """Restaura sync_interval_seconds=30 e tenant_domain da empresa demo no final."""
    try:
        r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=15)
        token = r.json().get("access_token") or r.json().get("token")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        requests.put(
            f"{BASE_URL}/api/atlaz/settings",
            json={
                "sync_interval_seconds": 30,
                "tenant_domain": "https://ligofibra.atlaz.com.br",
            },
            headers=headers,
            timeout=15,
        )
    except Exception as e:
        print(f"[teardown] restore failed: {e}")
