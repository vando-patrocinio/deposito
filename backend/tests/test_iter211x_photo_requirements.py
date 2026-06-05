"""
test_iter211x_photo_requirements.py
====================================
Garante o cardápio de fotos obrigatórias por OS:
  - Auto-seed na 1ª chamada com 3 defaults (cto, equipamento, sn)
  - PUT permite toggle, edit, add custom items
  - Defaults nunca somem (reanexados como required=false se omitidos)
  - IDs duplicados → 400
  - Filtra ticket_types inválidos
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_iter211x_photo_reqs")

from database import db  # noqa: E402
from routes.lousa import (  # noqa: E402
    list_photo_requirements, update_photo_requirements,
    PhotoRequirementIn, PhotoRequirementsIn,
)


@pytest.mark.asyncio
async def test_photo_requirements_full_flow():
    from fastapi import HTTPException
    test_co = f"co-test-{uuid.uuid4().hex[:8]}"
    user = {"role": "gestor", "company_id": test_co,
            "email": "g@t", "name": "G", "id": "u-1"}

    try:
        # 1) GET inicial — auto-seed com 3 defaults
        r = await list_photo_requirements(user)
        assert len(r["items"]) == 3
        ids = sorted(it["id"] for it in r["items"])
        assert ids == ["cto", "equipamento", "sn"]
        assert all(it["is_default"] for it in r["items"])
        assert all(it["required"] for it in r["items"])
        assert "instalacao" in r["valid_ticket_types"]
        # iter211y — defaults vêm com cto.stamp_location=True
        by_id = {it["id"]: it for it in r["items"]}
        assert by_id["cto"]["stamp_location"] is True
        assert by_id["equipamento"]["stamp_location"] is False
        assert by_id["sn"]["stamp_location"] is False

        # 2) PUT custom: desliga 'equipamento', adiciona 'comprovante' com stamp_location
        payload = PhotoRequirementsIn(items=[
            PhotoRequirementIn(id="cto", label="Foto da CTO", icon="📦",
                                ticket_types=["instalacao", "reparo"],
                                required=True, sort_order=10,
                                stamp_location=True),
            PhotoRequirementIn(id="equipamento", label="ONT", icon="📡",
                                ticket_types=["instalacao"],
                                required=False, sort_order=20),
            PhotoRequirementIn(id="comprovante", label="Comprovante assinado",
                                icon="✍️",
                                ticket_types=["instalacao", "retirada"],
                                required=True, sort_order=30,
                                stamp_location=True),
        ])
        out = await update_photo_requirements(payload, user)
        assert out["ok"] is True
        items_by_id = {it["id"]: it for it in out["items"]}
        # 'sn' (default) foi omitido no PUT → backend reanexa como required=False
        assert "sn" in items_by_id
        assert items_by_id["sn"]["required"] is False
        assert items_by_id["sn"]["is_default"] is True
        # Custom novo com selo
        assert items_by_id["comprovante"]["required"] is True
        assert items_by_id["comprovante"]["is_default"] is False
        assert items_by_id["comprovante"]["stamp_location"] is True
        assert items_by_id["equipamento"]["required"] is False
        assert items_by_id["cto"]["stamp_location"] is True

        # 3) GET retorna o estado persistido (sem auto-seed segundo)
        r2 = await list_photo_requirements(user)
        assert len(r2["items"]) == 4  # 3 defaults + 1 custom
        ids2 = sorted(it["id"] for it in r2["items"])
        assert ids2 == ["comprovante", "cto", "equipamento", "sn"]

        # 4) PUT com id duplicado → 400
        dup_payload = PhotoRequirementsIn(items=[
            PhotoRequirementIn(id="cto", label="CTO 1", icon="📷",
                                ticket_types=[], required=True),
            PhotoRequirementIn(id="cto", label="CTO 2", icon="📷",
                                ticket_types=[], required=True),
        ])
        with pytest.raises(HTTPException) as exc:
            await update_photo_requirements(dup_payload, user)
        assert exc.value.status_code == 400
        assert "duplicado" in exc.value.detail.lower()

        # 5) ticket_types inválidos são filtrados (não derruba)
        weird_payload = PhotoRequirementsIn(items=[
            PhotoRequirementIn(id="cto", label="CTO", icon="📦",
                                ticket_types=["instalacao", "marciano",
                                                "reparo"],
                                required=True),
        ])
        out2 = await update_photo_requirements(weird_payload, user)
        cto_item = next(it for it in out2["items"] if it["id"] == "cto")
        assert "marciano" not in cto_item["ticket_types"]
        assert "instalacao" in cto_item["ticket_types"]
        assert "reparo" in cto_item["ticket_types"]
    finally:
        await db.lousa_photo_requirements.delete_one({"company_id": test_co})


def test_photo_requirement_payload_rejects_bad_id():
    from pydantic import ValidationError
    # ID com maiúscula
    with pytest.raises(ValidationError):
        PhotoRequirementIn(id="CTO", label="CTO", icon="📦")
    # ID muito curto
    with pytest.raises(ValidationError):
        PhotoRequirementIn(id="a", label="A", icon="📷")
    # ID com espaço
    with pytest.raises(ValidationError):
        PhotoRequirementIn(id="foto cto", label="X", icon="📷")
    # Label muito curto
    with pytest.raises(ValidationError):
        PhotoRequirementIn(id="ok-id", label="A", icon="📷")
    # OK
    ok = PhotoRequirementIn(id="painel-rua", label="Painel da rua",
                              icon="🪧", ticket_types=["instalacao"])
    assert ok.id == "painel-rua"
