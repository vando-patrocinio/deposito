"""SECURITY: QR Code do cliente NÃO pode vazar nome+CPF em texto puro.

Testes via HTTP real (não unit) porque o rate-limit do slowapi exige
contexto FastAPI completo. O fluxo cobre:
1. Geração de token → QR payload SEM PII.
2. Resolve com auth retorna dados corretos.
3. Single-use: 2ª tentativa = 404.
4. Sem auth = 401.
5. TTL expirado = 410.
"""
import asyncio
import os
import sys


def test_qr_security_end_to_end():
    sys.path.insert(0, "/app/backend")
    import httpx
    from datetime import datetime, timedelta, timezone
    from database import db
    from routes.referrals import _customer_token

    BACKEND = os.environ.get("REACT_APP_BACKEND_URL")
    if not BACKEND:
        # Lê do .env do frontend
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        BACKEND = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass
    assert BACKEND, "REACT_APP_BACKEND_URL não definido"

    async def _run():
        # Pega um subscriber para o cliente token
        sub = await db.subscribers.find_one(
            {"name": {"$ne": None}}, {"_id": 0, "id": 1, "name": 1,
                                       "document": 1})
        assert sub
        ctk = _customer_token(sub["id"])

        # Login admin
        async with httpx.AsyncClient(base_url=BACKEND, timeout=10) as c:
            r = await c.post("/api/auth/login", json={
                "email": "admin@empresa.com", "password": "123456"})
            assert r.status_code == 200
            admin_tk = r.json()["access_token"]

            # 1. Issue QR token
            r = await c.get("/api/qr-token",
                            headers={"Authorization": f"Bearer {ctk}"})
            assert r.status_code == 200, f"Issue falhou: {r.text}"
            payload = r.json()["qr_payload"]
            assert payload.startswith("LIGO:")
            token = payload.replace("LIGO:", "")

            # PII check
            name = (sub.get("name") or "").lower()
            assert name not in token.lower(), "VAZAMENTO: nome no token"
            doc = (sub.get("document") or "")\
                .replace(".", "").replace("-", "")
            if doc:
                assert doc not in token, "VAZAMENTO: CPF no token"

            # 2. Resolve com auth
            r2 = await c.get(f"/api/customer/qr-resolve/{token}",
                             headers={"Authorization": f"Bearer {admin_tk}"})
            assert r2.status_code == 200
            assert r2.json()["name"] == sub.get("name")

            # 3. Single-use
            r3 = await c.get(f"/api/customer/qr-resolve/{token}",
                             headers={"Authorization": f"Bearer {admin_tk}"})
            assert r3.status_code == 404

            # 4. Sem auth
            r4 = await c.get("/api/customer/qr-resolve/FAKE")
            assert r4.status_code == 401

            # 5. Token expirado — insere manualmente um expirado
            expired = "EXPIRED-TEST-PYTEST-789"
            await db.customer_qr_ephemeral.insert_one({
                "token": expired,
                "subscriber_id": sub["id"],
                "company_id": "co-demo",
                "created_at": datetime.now(timezone.utc),
                "expires_at": datetime.now(timezone.utc)
                    - timedelta(seconds=30),
            })
            r5 = await c.get(f"/api/customer/qr-resolve/{expired}",
                             headers={"Authorization": f"Bearer {admin_tk}"})
            assert r5.status_code == 410
            # Cleanup
            await db.customer_qr_ephemeral.delete_one({"token": expired})

    asyncio.run(_run())
