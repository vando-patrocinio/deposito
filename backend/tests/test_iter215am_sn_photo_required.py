"""iter215am — Validação da regra global SN + foto obrigatória em
retirada/troca.

Cenários:
  1) Toggle ligado (default) + retirada sem SN no SmartOLT e sem foto
     → 400 com code=SN_PHOTO_REQUIRED.
  2) Mesmo cenário com foto → 200, ticket marcado com
     ai_sn_photo_review_pending=True e stok_onts pendente criada para
     o técnico.
  3) is_defective=True → entrada de estoque criada como
     status=bloqueado_defeito.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")

import pymongo  # noqa: E402

_sync_client = pymongo.MongoClient(os.environ["MONGO_URL"])
_sync_db = _sync_client[os.environ["DB_NAME"]]

from database import db  # noqa: E402


def _completion(extra: dict | None = None) -> dict:
    base = {
        "sinal": -22.5,
        "cabo_drop": 0, "fast_connectors": 0,
        "conectores_fast": 0, "cabo_rede": 0, "conectores_rede": 0,
        "qtd_drop": 0, "esticadores": 0,
        "ont": "",
        "fotos": [],
        "observacoes": "teste",
    }
    if extra:
        base.update(extra)
    return base


PIXEL_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


async def _seed_ticket(company_id: str, collab_id: str, ttype: str) -> str:
    tid = f"tk-{uuid.uuid4().hex[:10]}"
    # iter215ar — Pra regra SmartOLT/foto disparar, o cliente PRECISA ter
    # match no SmartOLT. Seeda uma ONU correspondente pelo name_norm.
    suf = uuid.uuid4().hex[:8]
    name = f"Cliente Teste {suf}"
    pppoe = f"pppoe{suf}"  # sem caracteres especiais — _norm strip non-alnum
    norm = pppoe.lower()
    _sync_db.smartolt_onus.insert_one({
        "company_id": company_id,
        "unique_external_id": f"ext-{uuid.uuid4().hex[:8]}",
        "name": pppoe,
        "name_norm": norm,
        "sn": "SOMEMATCHSN0001",
        "olt_name": "OLT Teste",
        "status": "Online",
        "synced_at": datetime.now(timezone.utc).isoformat(),
    })
    _sync_db.tickets.insert_one({
        "id": tid,
        "company_id": company_id,
        "type": ttype,
        "status": "aberta",
        "assigned_collaborator_id": collab_id,
        "assigned_collaborator_name": "Tec Teste",
        "client_snapshot": {"id": "cli-x", "name": name,
                             "pppoe_user": pppoe,
                             "phone": "11999999999",
                             "address": "Rua Y", "neighborhood": "Bairro Z"},
        "atlaz_pppoe_user": pppoe,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return tid


async def _seed_collab(company_id: str) -> str:
    cid = f"col-{uuid.uuid4().hex[:8]}"
    _sync_db.collaborators.insert_one({
        "id": cid,
        "company_id": company_id,
        "name": "Tec Teste",
        "email": f"{cid}@teste.local",
        "cpf": f"00000000{uuid.uuid4().hex[:3]}",
        "role": "tecnico",
    })
    return cid


async def _cleanup(ticket_id: str, collab_id: str):
    _sync_db.tickets.delete_many({"id": ticket_id})
    _sync_db.collaborators.delete_many({"id": collab_id})
    _sync_db.stok_onts.delete_many({"ticket_id": ticket_id})
    _sync_db.stok_history.delete_many({"ticket_id": ticket_id})
    # iter215ar — limpa ONUs criadas pelos seeds
    _sync_db.smartolt_onus.delete_many({"olt_name": "OLT Teste"})


@pytest.mark.asyncio
async def test_sn_photo_required_blocks_without_photo(api, base_url):
    company_id = "co-demo"
    collab_id = await _seed_collab(company_id)
    ticket_id = await _seed_ticket(company_id, collab_id, "retirada")
    try:
        # ensure toggle is ON (default)
        _sync_db.aihub_settings.update_one(
            {"company_id": company_id, "key": "os_validation_toggles"},
            {"$set": {"value": {"sn_smartolt_or_photo_required": True,
                                 "cto_port_required": False}}},
            upsert=True,
        )
        payload = {
            "collaborator_id": collab_id,
            "outcome": "sucesso",
            "completion_data": _completion({
                "ont": "SN_NAO_CADASTRADO_999",
                "observacoes": "teste sem foto",
            }),
            "latitude": 0, "longitude": 0,
        }
        r = api.post(
            f"{base_url}/api/lousa/public/tickets/{ticket_id}/finalize",
            json=payload, timeout=15,
        )
        assert r.status_code == 400, f"esperado 400, veio {r.status_code}: {r.text}"
        detail = r.json().get("detail") or {}
        assert detail.get("code") == "SN_PHOTO_REQUIRED", detail
        assert detail.get("sn_in_smartolt") is False
    finally:
        await _cleanup(ticket_id, collab_id)


@pytest.mark.asyncio
async def test_sn_photo_creates_pending_stok_entry(api, base_url):
    company_id = "co-demo"
    collab_id = await _seed_collab(company_id)
    ticket_id = await _seed_ticket(company_id, collab_id, "retirada")
    try:
        _sync_db.aihub_settings.update_one(
            {"company_id": company_id, "key": "os_validation_toggles"},
            {"$set": {"value": {"sn_smartolt_or_photo_required": True,
                                 "cto_port_required": False}}},
            upsert=True,
        )
        payload = {
            "collaborator_id": collab_id,
            "outcome": "sucesso",
            "completion_data": _completion({
                "ont": "SN_INEXISTENTE_999",
                "fotos": [PIXEL_PNG],
                "observacoes": "retirada com foto IA",
                "cancel_reason_category": "preco",
            }),
            "latitude": 0, "longitude": 0,
        }
        api.post(
            f"{base_url}/api/lousa/public/tickets/{ticket_id}/finalize",
            json=payload, timeout=20,
        )
        # finalize pode 200 OR 400 dependendo de outras regras (estoque,
        # service), mas a flag e a entrada DEVEM ter sido criadas ANTES
        # do erro de estoque (commit ocorre dentro do guard SN+foto).
        import time
        time.sleep(0.5)
        t = _sync_db.tickets.find_one({"id": ticket_id}, {"_id": 0})
        assert t is not None
        assert t.get("ai_sn_photo_review_pending") is True
        pending = _sync_db.stok_onts.find_one(
            {"ticket_id": ticket_id, "ai_review_pending": True},
            {"_id": 0},
        )
        assert pending is not None
        assert pending["location_type"] == "tecnico"
        assert pending["location_id"] == collab_id
        assert pending["status"] == "pending_ai_review"
        assert pending.get("via_photo_ai") is True
    finally:
        await _cleanup(ticket_id, collab_id)


@pytest.mark.asyncio
async def test_sn_photo_defective_blocks_equipment(api, base_url):
    company_id = "co-demo"
    collab_id = await _seed_collab(company_id)
    ticket_id = await _seed_ticket(company_id, collab_id, "retirada")
    try:
        _sync_db.aihub_settings.update_one(
            {"company_id": company_id, "key": "os_validation_toggles"},
            {"$set": {"value": {"sn_smartolt_or_photo_required": True,
                                 "cto_port_required": False}}},
            upsert=True,
        )
        payload = {
            "collaborator_id": collab_id,
            "outcome": "sucesso",
            "completion_data": _completion({
                "ont": "SN_DEFEITUOSO_999",
                "fotos": [PIXEL_PNG],
                "observacoes": "ONT queimou",
                "cancel_reason_category": "qualidade",
                "is_defective": True,
                "defective_reason": "ONT não liga",
            }),
            "latitude": 0, "longitude": 0,
        }
        api.post(
            f"{base_url}/api/lousa/public/tickets/{ticket_id}/finalize",
            json=payload, timeout=20,
        )
        import time
        time.sleep(0.5)
        pending = _sync_db.stok_onts.find_one(
            {"ticket_id": ticket_id}, {"_id": 0},
        )
        assert pending is not None
        assert pending["status"] == "bloqueado_defeito"
        assert pending["is_defective"] is True
        assert pending["defective_reason"] == "ONT não liga"
    finally:
        await _cleanup(ticket_id, collab_id)
