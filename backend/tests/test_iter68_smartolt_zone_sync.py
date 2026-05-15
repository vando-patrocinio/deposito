"""Iteration 68 — Sync inversa Rede_IA → SmartOLT (Zones)

Valida o ciclo idempotente de criar zone no SmartOLT a partir da
aprovação de CTO. Roda contra o ambiente real (SmartOLT configurado
para co-demo).

Casos cobertos:
1) GET /api/rede-ia/smartolt/zones — lista (200, items array)
2) GET /api/rede-ia/smartolt/zone-audit — auditoria (200, items array)
3) POST /api/rede-ia/ctos/{unknown}/sync-smartolt-zone → 404
4) POST /api/rede-ia/ctos/{pending}/sync-smartolt-zone → 409 (apenas aprovadas)
5) POST /api/rede-ia/ctos/{approved}/sync-smartolt-zone → 200 idempotente
   (created=false, "já existe" — porque sync original aconteceu na aprovação)
6) Audit cresce com pelo menos 1 entry "already_exists" após o force-sync
"""
import os
import pytest
import requests


def _load_base_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    url = line.strip().split("=", 1)[1]
                    break
    assert url, "REACT_APP_BACKEND_URL not found"
    return url.rstrip("/")


BASE_URL = _load_base_url()


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "admin@empresa.com", "password": "123456"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def ctos_by_status(auth_headers):
    """Mapeia CTOs por status para reusar nos testes."""
    r = requests.get(f"{BASE_URL}/api/rede-ia/ctos", headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    items = r.json().get("items", [])
    by = {"approved": [], "pending_validation": [], "rejected": []}
    for c in items:
        by.setdefault(c.get("status"), []).append(c)
    return by


def test_1_list_zones(auth_headers):
    r = requests.get(f"{BASE_URL}/api/rede-ia/smartolt/zones",
                     headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body
    assert isinstance(body["items"], list)
    assert body.get("total") == len(body["items"])


def test_2_zone_audit(auth_headers):
    r = requests.get(f"{BASE_URL}/api/rede-ia/smartolt/zone-audit",
                     headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body
    assert isinstance(body["items"], list)
    for it in body["items"]:
        assert "action" in it and "zone_name" in it and "result" in it
        assert it["result"] in (
            "created", "already_exists", "race_duplicate",
            "http_error", "network_error", "unexpected",
        )


def test_3_force_sync_unknown_cto_returns_404(auth_headers):
    r = requests.post(
        f"{BASE_URL}/api/rede-ia/ctos/cto-DOES-NOT-EXIST/sync-smartolt-zone",
        headers=auth_headers, timeout=15,
    )
    assert r.status_code == 404, r.text


def test_4_force_sync_pending_cto_returns_409(auth_headers, ctos_by_status):
    pending = ctos_by_status.get("pending_validation") or []
    if not pending:
        pytest.skip("Sem CTO em pending_validation no ambiente")
    cto_id = pending[0]["id"]
    r = requests.post(
        f"{BASE_URL}/api/rede-ia/ctos/{cto_id}/sync-smartolt-zone",
        headers=auth_headers, timeout=15,
    )
    assert r.status_code == 409, r.text
    assert "aprovadas" in r.json().get("detail", "").lower()


def test_5_force_sync_approved_is_idempotent(auth_headers, ctos_by_status):
    approved = ctos_by_status.get("approved") or []
    if not approved:
        pytest.skip("Sem CTO aprovada no ambiente")
    cto_id = approved[0]["id"]
    r = requests.post(
        f"{BASE_URL}/api/rede-ia/ctos/{cto_id}/sync-smartolt-zone",
        headers=auth_headers, timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    # Zone já foi criada na aprovação inicial → re-sync deve ser no-op
    assert body.get("created") is False, body
    assert "já existe" in body.get("message", "").lower() or \
           "ja existe" in body.get("message", "").lower()


def test_6_audit_records_force_sync(auth_headers, ctos_by_status):
    """Após test_5, o audit deve ter ao menos 1 entry 'already_exists' recente
    para a CTO aprovada."""
    approved = ctos_by_status.get("approved") or []
    if not approved:
        pytest.skip("Sem CTO aprovada no ambiente")
    zone_name = approved[0]["name"]
    r = requests.get(f"{BASE_URL}/api/rede-ia/smartolt/zone-audit",
                     headers=auth_headers, timeout=15)
    assert r.status_code == 200
    items = r.json().get("items", [])
    matching = [it for it in items
                if it.get("zone_name") == zone_name and it.get("result") == "already_exists"]
    assert matching, f"Esperado audit 'already_exists' para zone={zone_name}, items={items[:5]}"
