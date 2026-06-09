"""test_v9_p23_adoption.py — V9 P2.3 telemetria de adoção."""
import os, sys, uuid, pytest, pytest_asyncio
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
CO = "test-v9-adoption"


@pytest_asyncio.fixture
async def db():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    d = c[os.environ["DB_NAME"]]
    import database as dm
    dm.db = d
    from services import v7_2_2_data_quality
    v7_2_2_data_quality.db = d
    await d.tickets.delete_many({"company_id": CO})
    yield d
    await d.tickets.delete_many({"company_id": CO})
    c.close()


@pytest.mark.asyncio
async def test_adoption_zero_when_no_data(db):
    from services.v7_2_2_data_quality import smart_field_adoption
    r = await smart_field_adoption(CO)
    assert r["categories"]["REPAIR"]["30d"]["pct"] == 0
    assert r["status"] == "INSUFICIENTE"


@pytest.mark.asyncio
async def test_adoption_calculates_pct_correctly(db):
    from services.v7_2_2_data_quality import smart_field_adoption
    now = datetime.now(timezone.utc).isoformat()
    # 4 REPAIR fechados — 3 com resolution_kind
    for i in range(3):
        await db.tickets.insert_one({
            "id": f"rep-{i}", "company_id": CO,
            "category": "REPAIR", "status": "finalizada",
            "closed_at": now, "resolution_kind": "remote",
            "assigned_to": "col-1"})
    await db.tickets.insert_one({
        "id": "rep-vazio", "company_id": CO,
        "category": "REPAIR", "status": "finalizada",
        "closed_at": now, "resolution_kind": None,
        "assigned_to": "col-2"})
    # 2 WITHDRAW — 1 com asset_recovered
    await db.tickets.insert_one({
        "id": "wd-1", "company_id": CO,
        "category": "WITHDRAW", "status": "finalizada",
        "closed_at": now, "asset_recovered": True,
        "signed_receipt": True, "assigned_to": "col-1"})
    await db.tickets.insert_one({
        "id": "wd-2", "company_id": CO,
        "category": "WITHDRAW", "status": "finalizada",
        "closed_at": now, "assigned_to": "col-2"})
    r = await smart_field_adoption(CO)
    # REPAIR 30d: 3/4 = 75%
    assert r["categories"]["REPAIR"]["30d"]["pct"] == 75.0
    # WITHDRAW asset_recovered 30d: 1/2 = 50%
    assert (r["categories"]["WITHDRAW"]["asset_recovered"][
            "30d"]["pct"]) == 50.0
    # avg = (75 + 50 + 50) / 3 = 58.33 → INSUFICIENTE
    assert r["adoption_avg_30d_pct"] == 58.33
    assert r["meta_minima_70"] is False
    # Ranking tem col-1 e col-2
    tids = [t["technician_id"] for t in r["technician_ranking"]]
    assert "col-1" in tids and "col-2" in tids
    # Pendentes: rep-vazio + wd-2
    pending_ids = [p["ticket_id"] for p in r["pending_sample"]]
    assert "rep-vazio" in pending_ids
    assert "wd-2" in pending_ids


@pytest.mark.asyncio
async def test_adoption_status_excellent_at_90pct(db):
    from services.v7_2_2_data_quality import smart_field_adoption
    now = datetime.now(timezone.utc).isoformat()
    # 10 REPAIR fechados, todos preenchidos
    for i in range(10):
        await db.tickets.insert_one({
            "id": f"rep-{i}", "company_id": CO,
            "category": "REPAIR", "status": "finalizada",
            "closed_at": now, "resolution_kind": "onsite"})
    # 10 WITHDRAW todos preenchidos
    for i in range(10):
        await db.tickets.insert_one({
            "id": f"wd-{i}", "company_id": CO,
            "category": "WITHDRAW", "status": "finalizada",
            "closed_at": now, "asset_recovered": True,
            "signed_receipt": True})
    r = await smart_field_adoption(CO)
    assert r["adoption_avg_30d_pct"] == 100.0
    assert r["status"] == "EXCELENTE"
    assert r["meta_ideal_90"] is True
