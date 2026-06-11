"""
Enhancement testing (Jan-2026): magic-link expiration + WhatsApp send.

Covers:
  * POST /api/users/{uid}/magic-link/rotate body {expires_in_days:N}
      → active.expires_at presente e ~ now+N days; reserve.expires_at NÃO presente.
  * POST /api/auth/magic-login com token expirado
      → revoga (status='revoked', revoked_reason='expired') e responde 401.
  * POST /api/users/{uid}/magic-link/send {phone,channel:'whatsapp'}
      → 200 com {ok,channel,phone,sent_at,sidecar_response}.
  * POST /api/users/{uid}/magic-link/send sem phone e sem collaborator → 400.
  * POST /api/users/{uid}/magic-link/send channel='sms' → 400.
"""
import os
import uuid
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"
MAYARA_EMAIL = "msaldanhavargasmiranda@gmail.com"


# ─────────────────── fixtures ───────────────────
@pytest.fixture(scope="session")
def admin_headers():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=20)
    assert r.status_code == 200, f"login admin: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def mayara_uid(admin_headers):
    r = requests.get(f"{BASE_URL}/api/users", headers=admin_headers, timeout=20)
    users = r.json() if isinstance(r.json(), list) else r.json().get("items") or r.json().get("users") or []
    u = next((x for x in users if x.get("email") == MAYARA_EMAIL), None)
    assert u, "Mayara user nao encontrado"
    return u["id"]


@pytest.fixture(scope="session")
def fresh_user(admin_headers):
    """User dedicado pra não interferir com Mayara nos testes de rotate de expiração."""
    email = f"TEST_exp_{uuid.uuid4().hex[:6]}@example.com"
    r = requests.post(f"{BASE_URL}/api/users", headers=admin_headers, json={
        "email": email, "name": "TEST exp user", "password": "Test1234!", "role": "gestor"
    }, timeout=20)
    assert r.status_code in (200, 201), f"create user: {r.status_code} {r.text}"
    uid = r.json()["id"]
    yield {"id": uid, "email": email}
    requests.delete(f"{BASE_URL}/api/users/{uid}", headers=admin_headers, timeout=10)


# ─────────────────── 1. ROTATE com expires_in_days ───────────────────
class TestRotateExpiration:
    def test_rotate_with_expires_in_days_sets_active_expires_at(self, admin_headers, fresh_user):
        before = datetime.now(timezone.utc)
        r = requests.post(f"{BASE_URL}/api/users/{fresh_user['id']}/magic-link/rotate",
                          headers=admin_headers, json={"expires_in_days": 7}, timeout=20)
        assert r.status_code == 200, f"rotate: {r.status_code} {r.text}"
        body = r.json()
        assert body["ok"] is True
        active = body["active"]
        reserve = body["reserve"]
        # ACTIVE deve ter expires_at preenchido (~ now + 7d)
        assert active.get("expires_at"), f"active.expires_at faltando: {active}"
        exp_dt = datetime.fromisoformat(active["expires_at"].replace("Z", "+00:00"))
        delta = exp_dt - before
        assert timedelta(days=6, hours=23) < delta < timedelta(days=7, hours=1), \
            f"expires_at fora da janela esperada: delta={delta}"
        # RESERVA NÃO deve carregar expires_at
        assert not reserve.get("expires_at"), f"reserve nao deveria ter expires_at: {reserve}"

    def test_rotate_without_expires_in_days_active_has_no_expires(self, admin_headers, fresh_user):
        r = requests.post(f"{BASE_URL}/api/users/{fresh_user['id']}/magic-link/rotate",
                          headers=admin_headers, json={}, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        # active.expires_at deve ser None/ausente quando não passado dias
        assert not body["active"].get("expires_at"), f"active nao deveria ter expires_at: {body['active']}"


# ─────────────────── 2. magic-login com token expirado → 401 + revoke ───────────────────
class TestMagicLoginExpired:
    def test_expired_token_is_revoked_and_returns_401(self, admin_headers):
        """Insere doc direto no DB com expires_at no passado + status=active, chama magic-login."""
        from motor.motor_asyncio import AsyncIOMotorClient
        mongo_url = os.environ.get("MONGO_URL")
        db_name = os.environ.get("DB_NAME")
        assert mongo_url and db_name, "MONGO_URL/DB_NAME ausentes"

        fake_token = f"TESTEXP{uuid.uuid4().hex}"  # >12 chars
        past_iso = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        doc = {
            "id": f"mlk-test-{uuid.uuid4().hex[:8]}",
            "user_id": "usr-fake-test",
            "company_id": "co-demo",
            "token": fake_token,
            "status": "active",
            "generation": 99999,
            "created_at": past_iso,
            "expires_at": past_iso,
            "reason": "test-expired",
        }

        async def _setup_and_check():
            cli = AsyncIOMotorClient(mongo_url)
            try:
                d = cli[db_name]
                # garante user fake existe (magic_login checa users.find_one)
                await d.users.update_one(
                    {"id": "usr-fake-test"},
                    {"$set": {"id": "usr-fake-test", "email": "fake-exp@test.io",
                              "role": "gestor", "company_id": "co-demo", "active": True}},
                    upsert=True,
                )
                await d.user_magic_links.insert_one(doc)
                return cli, d
            except Exception:
                cli.close()
                raise

        async def _cleanup(cli, d):
            try:
                await d.user_magic_links.delete_many({"token": fake_token})
                await d.users.delete_one({"id": "usr-fake-test"})
            finally:
                cli.close()

        loop = asyncio.new_event_loop()
        try:
            cli, d = loop.run_until_complete(_setup_and_check())

            # Chama o magic-login
            r = requests.post(f"{BASE_URL}/api/auth/magic-login",
                              json={"token": fake_token}, timeout=15)
            assert r.status_code == 401, f"esperava 401, veio {r.status_code} {r.text}"
            assert "expirado" in r.text.lower(), f"mensagem nao menciona expirado: {r.text}"

            # Verifica que foi revogado no DB
            async def _check_doc():
                return await d.user_magic_links.find_one({"token": fake_token})

            updated = loop.run_until_complete(_check_doc())
            assert updated is not None
            assert updated.get("status") == "revoked", f"status deveria ser revoked, foi {updated.get('status')}"
            assert updated.get("revoked_reason") == "expired", \
                f"revoked_reason deveria ser 'expired', foi {updated.get('revoked_reason')}"
            assert updated.get("revoked_at")
        finally:
            try:
                loop.run_until_complete(_cleanup(cli, d))
            except Exception:
                pass
            loop.close()


# ─────────────────── 3,4,5. SEND via WhatsApp ───────────────────
class TestSendMagicLink:
    def test_send_whatsapp_with_phone_returns_ok(self, admin_headers, fresh_user):
        # Garante que tem um active link
        requests.post(f"{BASE_URL}/api/users/{fresh_user['id']}/magic-link/rotate",
                      headers=admin_headers, json={}, timeout=20)
        r = requests.post(
            f"{BASE_URL}/api/users/{fresh_user['id']}/magic-link/send",
            headers=admin_headers,
            json={"phone": "5511999990000", "channel": "whatsapp"},
            timeout=30,
        )
        assert r.status_code == 200, f"send WhatsApp: {r.status_code} {r.text}"
        body = r.json()
        assert body["ok"] is True
        assert body["channel"] == "whatsapp"
        assert body["phone"] == "5511999990000"
        assert body.get("sent_at"), "sent_at faltando"
        # sidecar_response pode ser None ou dict (em homolog pode ter blocked_by_gateway:true)
        assert "sidecar_response" in body

    def test_send_without_phone_and_no_collaborator_returns_400(self, admin_headers, fresh_user):
        # fresh_user nao tem collaborator_id → deve falhar
        r = requests.post(
            f"{BASE_URL}/api/users/{fresh_user['id']}/magic-link/send",
            headers=admin_headers,
            json={"channel": "whatsapp"},
            timeout=15,
        )
        assert r.status_code == 400, f"esperava 400 sem phone+collaborator, veio {r.status_code} {r.text}"
        assert "telefone" in r.text.lower() or "phone" in r.text.lower()

    def test_send_with_sms_channel_returns_400(self, admin_headers, fresh_user):
        r = requests.post(
            f"{BASE_URL}/api/users/{fresh_user['id']}/magic-link/send",
            headers=admin_headers,
            json={"phone": "5511999990000", "channel": "sms"},
            timeout=15,
        )
        assert r.status_code == 400, f"esperava 400 para canal sms, veio {r.status_code} {r.text}"
        assert "whatsapp" in r.text.lower() or "habilitado" in r.text.lower()
