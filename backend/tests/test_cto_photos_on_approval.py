"""E2E: validação de CTO aprovada persiste a foto em ctos.photos[]
e a galeria é exposta via /api/rede-ia/map/data.

Cenários:
  1. Cria CTO + validation pendente com photo_data_url.
  2. Aprova via POST /rede-ia/ctos/{id}/validations/{vid}/decide.
  3. Verifica que `ctos.photos[0]` foi criado com url + uploaded_by_name.
  4. Endpoint /map/data retorna a CTO com `photos: [...]` populado.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import httpx
import pytest

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8001")
TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjC"
    "B0C8AAAAASUVORK5CYII="
)


@pytest.mark.asyncio
async def test_cto_photo_persisted_on_approval_and_exposed_on_map():
    from database import db
    import jwt
    from auth import _jwt_secret, JWT_ALGORITHM
    from datetime import timedelta as _td

    cid = "co-demo"
    suffix = uuid.uuid4().hex[:6]
    cto_id = f"cto-photo-{suffix}"
    val_id = f"val-photo-{suffix}"
    now = datetime.now(timezone.utc)

    # Token gestor (usa user real existente no banco)
    real_user = await db.users.find_one(
        {"email": "admin@empresa.com"}, {"_id": 0, "id": 1, "role": 1},
    )
    user_id = (real_user or {}).get("id") or f"u-admin-{suffix}"
    user_role = (real_user or {}).get("role") or "administrador"
    admin_token = jwt.encode({
        "sub": user_id,
        "email": "admin@empresa.com",
        "role": user_role,
        "company_id": cid,
        "exp": now + _td(hours=1),
        "iat": now,
        "type": "access",
    }, _jwt_secret(), algorithm=JWT_ALGORITHM)

    # SETUP: CTO pending_validation com 1 validação aguardando
    await db.ctos.insert_one({
        "id": cto_id, "company_id": cid, "name": f"CTO-PHOTO-{suffix}",
        "vlan": 100, "capacity": 16, "ports": [],
        "status": "pending_validation",
        "gps": {"lat": -22.9, "lng": -43.2},
        "address": {"rua": "Teste", "bairro": "Centro"},
        "created_at": now.isoformat(),
    })
    await db.cto_validations.insert_one({
        "id": val_id, "company_id": cid, "cto_id": cto_id,
        "technician_id": "tec-test", "technician_name": "João Técnico",
        "status": "pending",
        "cto_snapshot": {
            "name": f"CTO-PHOTO-{suffix}",
            "capacity": 16, "vlan": 100,
            "photo_data_url": TINY_PNG,
            "address": {"rua": "Teste", "bairro": "Centro"},
        },
        "created_at": now.isoformat(),
    })

    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            # APROVA
            r = await cli.post(
                f"{BACKEND}/api/rede-ia/ctos/{cto_id}/validate",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"action": "approve", "comment": "Aprovado pelo teste"},
            )
            assert r.status_code == 200, r.text

            # Confirma `photos[]` populado no banco
            cto = await db.ctos.find_one({"id": cto_id}, {"_id": 0})
            assert cto["status"] == "approved"
            photos = cto.get("photos") or []
            assert len(photos) == 1, f"esperava 1 foto, veio {len(photos)}"
            ph = photos[0]
            assert ph["url"] == TINY_PNG
            assert ph["uploaded_by_name"] == "João Técnico"
            assert ph["source"] == "validation_approved"
            assert ph["id"].startswith("ph-")
            print(f"✓ photo persistida no cadastro da CTO: {ph['id']}")

            # /map/data deve trazer photos[] populado
            r2 = await cli.get(
                f"{BACKEND}/api/rede-ia/map/data",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert r2.status_code == 200, r2.text
            data = r2.json()
            target = next(
                (c for c in data.get("ctos", []) if c["id"] == cto_id),
                None,
            )
            assert target is not None, "CTO não apareceu em /map/data"
            assert "photos" in target
            assert len(target["photos"]) == 1
            assert target["photos"][0]["url"] == TINY_PNG
            assert target["photos"][0]["uploaded_by_name"] == "João Técnico"
            print(f"✓ /map/data retorna CTO com photos[]: "
                    f"{len(target['photos'])} foto(s)")

    finally:
        await db.ctos.delete_one({"id": cto_id})
        await db.cto_validations.delete_one({"id": val_id})
