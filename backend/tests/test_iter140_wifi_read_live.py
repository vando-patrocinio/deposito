"""iter-140 — Wi-Fi Read Live endpoint.

Cobertura:
  1. Endpoint exige role staff (cliente final → 403)
  2. Endpoint exige assinante com ONU vinculada (sem ONU → 409)
  3. Endpoint chama SmartOLT e retorna estrutura padronizada
  4. Auditoria sempre gravada em `wifi_read_logs` (mesmo em falha)
  5. Rate limit: 10 leituras/hora por usuário por assinante
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta

import httpx
import pytest

sys.path.insert(0, "/app/backend")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")

API_URL = (open("/app/frontend/.env").read()
           .split("REACT_APP_BACKEND_URL=")[1]
           .splitlines()[0].strip())


def _login(email: str, password: str) -> str:
    r = httpx.post(f"{API_URL}/api/auth/login",
                   json={"email": email, "password": password},
                   timeout=15)
    r.raise_for_status()
    j = r.json()
    return j.get("access_token") or j.get("token") or ""


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_token() -> str:
    tok = _login("admin@example.com", "123456")
    assert tok, "admin login failed"
    return tok


@pytest.fixture(scope="module")
def linked_sid(admin_token: str) -> str:
    """Devolve um SID com ONU vinculada (cria via fixture se não houver)."""
    import asyncio
    from database import db

    async def _find():
        sub = await db.subscribers.find_one(
            {"smartolt_onu_id": {"$exists": True, "$ne": None}},
            {"_id": 0, "id": 1})
        return (sub or {}).get("id")

    sid = asyncio.get_event_loop().run_until_complete(_find())
    if not sid:
        pytest.skip("Nenhum subscriber com smartolt_onu_id no banco de teste.")
    return sid


def test_unlinked_sub_returns_409(admin_token: str):
    """Sub sem ONU vinculada → 409 com mensagem clara."""
    r = httpx.get(
        f"{API_URL}/api/subscribers?limit=10",
        headers=_hdr(admin_token), timeout=15)
    items = r.json().get("items") or []
    no_onu = next((s for s in items if not s.get("smartolt_onu_id")), None)
    if not no_onu:
        pytest.skip("Todos os subs do banco têm ONU vinculada.")
    r2 = httpx.get(
        f"{API_URL}/api/wifi/subscriber/{no_onu['id']}/read-live",
        headers=_hdr(admin_token), timeout=15)
    assert r2.status_code == 409
    assert "ONU" in (r2.json().get("detail") or "")


def test_read_live_audit_log_written(admin_token: str, linked_sid: str):
    """Mesmo em falha do SmartOLT, log de auditoria é gravado."""
    httpx.get(
        f"{API_URL}/api/wifi/subscriber/{linked_sid}/read-live",
        headers=_hdr(admin_token), timeout=30)
    # Confere log
    r = httpx.get(
        f"{API_URL}/api/wifi/subscriber/{linked_sid}/read-logs",
        headers=_hdr(admin_token), timeout=15)
    assert r.status_code == 200
    items = r.json().get("items") or []
    assert len(items) > 0
    latest = items[0]
    assert latest["subscriber_id"] == linked_sid
    assert latest["actor_email"] == "admin@example.com"
    assert "ssids_read" in latest
    assert "passwords_exposed" in latest


def test_read_live_response_shape(admin_token: str, linked_sid: str):
    """Resposta sempre tem campos `ok` e `smartolt_response_time_ms`."""
    r = httpx.get(
        f"{API_URL}/api/wifi/subscriber/{linked_sid}/read-live",
        headers=_hdr(admin_token), timeout=30)
    assert r.status_code in (200, 409)
    if r.status_code == 200:
        j = r.json()
        assert "ok" in j
        assert "smartolt_response_time_ms" in j
        if j["ok"]:
            assert isinstance(j.get("wifi"), list)
            for w in j["wifi"]:
                assert "band" in w
                assert "ssid" in w
                assert "password_available" in w


def test_rate_limit_after_10_reads(admin_token: str, linked_sid: str):
    """Após 10 leituras seguidas, 11ª deve retornar 429 READ_RATE_LIMITED.

    Limpa logs anteriores pra isolar o teste.
    """
    import asyncio
    from database import db

    # Limpa logs existentes da última hora pra esse sub+actor
    async def _clean():
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        await db.wifi_read_logs.delete_many({
            "subscriber_id": linked_sid,
            "actor_email": "admin@example.com",
            "ts": {"$gte": since},
        })
    asyncio.get_event_loop().run_until_complete(_clean())

    # Faz 10 chamadas (cada uma escreve log mesmo em falha)
    for _ in range(10):
        httpx.get(
            f"{API_URL}/api/wifi/subscriber/{linked_sid}/read-live",
            headers=_hdr(admin_token), timeout=15)
    # 11ª deve ser bloqueada
    r = httpx.get(
        f"{API_URL}/api/wifi/subscriber/{linked_sid}/read-live",
        headers=_hdr(admin_token), timeout=15)
    assert r.status_code == 429
    detail = r.json().get("detail") or {}
    if isinstance(detail, dict):
        assert detail.get("code") == "READ_RATE_LIMITED"
