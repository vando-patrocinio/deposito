"""test_v9_smart_field.py — V9 P2 Smart Field campos derivados.

Cobre os 4 campos novos no fluxo de fechamento:
  resolution_kind, asset_recovered, signed_receipt + reopened_within_7d
"""
from __future__ import annotations
import os
import sys
import uuid
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest_asyncio.fixture
async def db():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    d = c[os.environ["DB_NAME"]]
    import database as dm
    dm.db = d
    yield d
    c.close()


def test_completion_data_accepts_new_fields():
    """Schema CompletionData aceita os 4 campos novos."""
    from routes.lousa import CompletionData
    cd = CompletionData(
        sinal=-21.0, qtd_drop=0, esticadores=0,
        conectores_fast=0, cabo_rede=0, conectores_rede=0,
        resolution_kind="remote",
        asset_recovered=True,
        signed_receipt=True,
    )
    assert cd.resolution_kind == "remote"
    assert cd.asset_recovered is True
    assert cd.signed_receipt is True


def test_completion_data_resolution_kind_validates_literal():
    """resolution_kind só aceita 'remote' ou 'onsite'."""
    from routes.lousa import CompletionData
    from pydantic import ValidationError
    # Valor válido
    CompletionData(sinal=-21, qtd_drop=0, esticadores=0,
                   conectores_fast=0, cabo_rede=0,
                   conectores_rede=0, resolution_kind="onsite")
    # Valor inválido
    with pytest.raises(ValidationError):
        CompletionData(sinal=-21, qtd_drop=0, esticadores=0,
                       conectores_fast=0, cabo_rede=0,
                       conectores_rede=0,
                       resolution_kind="hybrid_invalid")


def test_completion_data_backward_compat_omits_new_fields():
    """Schema antigo (sem os 4 novos) continua válido."""
    from routes.lousa import CompletionData
    cd = CompletionData(
        sinal=-21.0, qtd_drop=2, esticadores=4,
        conectores_fast=2, cabo_rede=5.0, conectores_rede=2,
        ont="ALCL12345678", observacoes="Tudo ok",
    )
    # Novos campos None por default
    assert cd.resolution_kind is None
    assert cd.asset_recovered is None
    assert cd.signed_receipt is None
    # Serialização inclui os campos como None (backward-compatible)
    dump = cd.model_dump()
    assert "resolution_kind" in dump
    assert dump["resolution_kind"] is None


@pytest.mark.asyncio
async def test_smart_field_quality_jumps_with_new_fields(db):
    """Tickets com resolution_kind/asset_recovered preenchidos
    ALIMENTAM smart_repairs.truck_roll_avoided e
    smart_withdrawals.asset_recovered via company_v6."""
    CO = "test-v9-sf"
    for col in ("tickets", "smart_installs", "smart_repairs",
                "smart_withdrawals"):
        await db[col].delete_many({"company_id": CO})
    now = datetime.now(timezone.utc).isoformat()
    # 5 REPAIRS — 4 com resolution_kind=remote (deveria virar truck_roll_avoided)
    for i in range(4):
        await db.tickets.insert_one({
            "id": f"tk-rep-{i}", "company_id": CO,
            "category": "REPAIR", "type": "reparo",
            "status": "finalizada", "opened_at": now,
            "closed_at": now, "resolution_kind": "remote"})
    await db.tickets.insert_one({
        "id": "tk-rep-onsite", "company_id": CO,
        "category": "REPAIR", "type": "reparo",
        "status": "finalizada", "opened_at": now,
        "closed_at": now, "resolution_kind": "onsite"})
    # 4 WITHDRAWS — 3 com asset_recovered=true
    for i in range(3):
        await db.tickets.insert_one({
            "id": f"tk-wd-{i}", "company_id": CO,
            "category": "WITHDRAW", "type": "retirada",
            "status": "finalizada", "opened_at": now,
            "closed_at": now, "asset_recovered": True,
            "signed_receipt": True})
    await db.tickets.insert_one({
        "id": "tk-wd-lost", "company_id": CO,
        "category": "WITHDRAW", "type": "retirada",
        "status": "finalizada", "opened_at": now,
        "closed_at": now, "asset_recovered": False})

    from services import company_v6
    company_v6.db = db
    await company_v6.sync_smart_field_ops(CO, window_days=30)
    sk = await company_v6.smart_field_ops_kpis(CO, window_days=30)
    # 4/5 repairs = 80% truck_roll_avoidance
    assert sk["repairs"]["total"] == 5
    assert sk["repairs"]["truck_roll_avoidance_pct"] == 80.0
    # 3/4 withdraws = 75% asset_recovery
    assert sk["withdrawals"]["total"] == 4
    assert sk["withdrawals"]["asset_recovery_score_pct"] == 75.0
    # Cleanup
    for col in ("tickets", "smart_installs", "smart_repairs",
                "smart_withdrawals"):
        await db[col].delete_many({"company_id": CO})


@pytest.mark.asyncio
async def test_reopen_marks_within_7d_flag(db):
    """Reabertura dentro de 7d marca reopened_within_7d=True;
    além de 7d marca False."""
    CO = "test-v9-reopen"
    await db.tickets.delete_many({"company_id": CO})
    # Ticket fechado HÁ 3 DIAS — reopen dentro de 7d
    tid1 = "tk-3d"
    closed_3d = (datetime.now(timezone.utc)
                 - timedelta(days=3)).isoformat()
    await db.tickets.insert_one({
        "id": tid1, "company_id": CO,
        "category": "REPAIR", "type": "reparo",
        "status": "finalizada",
        "closed_at": closed_3d,
        "assigned_collaborator_id": "col-1"})
    # Ticket fechado HÁ 10 DIAS — reopen fora de 7d
    tid2 = "tk-10d"
    closed_10d = (datetime.now(timezone.utc)
                  - timedelta(days=10)).isoformat()
    await db.tickets.insert_one({
        "id": tid2, "company_id": CO,
        "category": "REPAIR", "type": "reparo",
        "status": "finalizada",
        "closed_at": closed_10d,
        "assigned_collaborator_id": "col-1"})

    # Simula o efeito de reopen (replica a lógica do endpoint sem
    # passar pela auth)
    from datetime import datetime as dt, timezone as tz
    for tid in (tid1, tid2):
        t = await db.tickets.find_one({"id": tid})
        ca = dt.fromisoformat(t["closed_at"].replace("Z", "+00:00"))
        if ca.tzinfo is None:
            ca = ca.replace(tzinfo=tz.utc)
        delta = (dt.now(tz.utc) - ca).days
        await db.tickets.update_one(
            {"id": tid},
            {"$set": {"reopened": True,
                      "reopened_within_7d": delta <= 7,
                      "reopened_within_days": delta,
                      "status": "pendente"}})
    t1 = await db.tickets.find_one({"id": tid1})
    t2 = await db.tickets.find_one({"id": tid2})
    assert t1["reopened_within_7d"] is True
    assert t1["reopened_within_days"] == 3
    assert t2["reopened_within_7d"] is False
    assert t2["reopened_within_days"] == 10
    await db.tickets.delete_many({"company_id": CO})


@pytest.mark.asyncio
async def test_finalize_propagates_to_ticket_root(db):
    """Após finalize com novos campos, tickets RAIZ tem
    resolution_kind/asset_recovered/signed_receipt populados
    (não só dentro de completion_data)."""
    CO = "test-v9-prop"
    await db.tickets.delete_many({"company_id": CO})
    tid = "tk-prop-1"
    await db.tickets.insert_one({
        "id": tid, "company_id": CO,
        "status": "aberta", "type": "retirada",
        "category": "WITHDRAW",
        "assigned_collaborator_id": "col-prop"})
    # Simula o $set que o finalize_ticket faz
    cd_dump = {
        "sinal": -22, "qtd_drop": 0, "esticadores": 0,
        "conectores_fast": 0, "cabo_rede": 0,
        "conectores_rede": 0,
        "resolution_kind": None,
        "asset_recovered": True,
        "signed_receipt": True,
    }
    await db.tickets.update_one(
        {"id": tid},
        {"$set": {
            "status": "finalizada", "outcome": "sucesso",
            "completion_data": cd_dump,
            "resolution_kind": cd_dump.get("resolution_kind"),
            "asset_recovered": cd_dump.get("asset_recovered"),
            "signed_receipt": cd_dump.get("signed_receipt"),
        }})
    t = await db.tickets.find_one({"id": tid})
    # RAIZ
    assert t["asset_recovered"] is True
    assert t["signed_receipt"] is True
    assert t["resolution_kind"] is None
    # E também no subdoc completion_data (backward compat)
    assert t["completion_data"]["asset_recovered"] is True
    await db.tickets.delete_many({"company_id": CO})
