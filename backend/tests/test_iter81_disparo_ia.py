"""Iter 81 — Disparo IA backend tests (endpoints contract + DB shape)."""
import os
import uuid
import asyncio
from datetime import datetime, timezone

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") \
    else None
if not BASE:
    # fallback to frontend .env
    import re as _re
    with open("/app/frontend/.env") as f:
        for ln in f:
            m = _re.match(r"REACT_APP_BACKEND_URL=(.+)", ln.strip())
            if m:
                BASE = m.group(1).strip().rstrip("/")
                break

CID = "co-demo"
def _read_env(key):
    v = os.environ.get(key)
    if v:
        return v.strip().strip('"').strip("'")
    with open("/app/backend/.env") as f:
        for ln in f:
            if ln.startswith(f"{key}="):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return None

MONGO_URL = _read_env("MONGO_URL")
DB_NAME = _read_env("DB_NAME")


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": "admin@empresa.com", "password": "123456"},
                      timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def db():
    cli = AsyncIOMotorClient(MONGO_URL)
    return cli[DB_NAME]


# --- 1. Catalog: 6 types
def test_types(h):
    r = requests.get(f"{BASE}/api/disparo-ia/types", headers=h, timeout=10)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    ids = {it["id"] for it in items}
    assert ids == {"churn_recovery", "plan_upsell", "friendly_billing",
                   "nps_csat", "coverage_expansion", "reactivation"}
    for it in items:
        assert "label" in it and "goal" in it


# --- 2. KPIs 10-metric shape
def test_kpis_shape(h):
    r = requests.get(f"{BASE}/api/disparo-ia/kpis?days=30", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("campaigns_count", "sent", "delivered", "failed",
              "delivery_rate", "read_rate", "reply_rate",
              "positive_reply_rate", "block_rate",
              "save_signals", "upsell_signals", "replies"):
        assert k in d, f"missing KPI {k}"


# --- 3. ACL: unauthenticated rejected
def test_acl_unauth():
    r = requests.get(f"{BASE}/api/disparo-ia/types", timeout=10)
    assert r.status_code in (401, 403)


# --- 4. List suggestions pending
def test_list_pending(h):
    r = requests.get(f"{BASE}/api/disparo-ia/suggestions?status=pending",
                     headers=h, timeout=10)
    assert r.status_code == 200
    js = r.json()
    assert "items" in js and "total" in js


# --- 5. List campaigns (disparo origin filter)
def test_list_campaigns(h):
    r = requests.get(f"{BASE}/api/disparo-ia/campaigns", headers=h, timeout=10)
    assert r.status_code == 200
    items = r.json()["items"]
    for c in items:
        assert c.get("origin") == "disparo_ia"


# --- 6. Generate-suggestions validation: bad type
def test_generate_invalid_type(h):
    r = requests.post(f"{BASE}/api/disparo-ia/generate-suggestions",
                      headers=h, json={"types": ["bogus_type"], "max_suggestions": 1},
                      timeout=10)
    assert r.status_code == 400, r.text


# --- 7. Approve flow with manually-crafted suggestion (avoid expensive LLM)
@pytest.mark.asyncio
async def test_approve_flow(db, h):
    sug_id = f"disp-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": sug_id,
        "company_id": CID,
        "run_id": "disp-run-test",
        "type": "nps_csat",
        "title": "TEST_Disparo NPS",
        "rationale": "test seed",
        "audience": {"description": "todos ativos", "filters": {"status": "ATIVO"}},
        "audience_preview": {"size": 1, "preview": []},
        "message_template": "Oi {{nome}}, teste TEST_disparo.",
        "isabella_briefing": "Tom amigável.",
        "expected_kpis": {"reply_rate_min": 0.2},
        "target_send_window": {},
        "cadence": {},
        "priority": "media",
        "alvaro_run_id": None,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "approved_at": None, "approved_by": None, "campaign_id": None,
    }
    await db.disparo_suggestions.insert_one(doc)

    try:
        # GET single
        r = requests.get(f"{BASE}/api/disparo-ia/suggestions/{sug_id}",
                         headers=h, timeout=10)
        assert r.status_code == 200
        assert r.json()["id"] == sug_id
        assert r.json()["status"] == "pending"

        # Approve with broader filter (plan_contains=null already in seed via status=ATIVO)
        # Adjust filter in-place: use empty filters to match all subscribers
        await db.disparo_suggestions.update_one(
            {"id": sug_id}, {"$set": {"audience.filters": {}}},
        )

        # Verify subscribers exist
        subs_count = await db.subscribers.count_documents({"company_id": CID})
        if subs_count == 0:
            pytest.skip("No subscribers in db — cannot test approve")

        r = requests.post(
            f"{BASE}/api/disparo-ia/suggestions/{sug_id}/approve",
            headers=h,
            json={"channel": "meta_cloud", "throttle_per_min": 60,
                  "edited_message": "Oi {{nome}}, mensagem ajustada TEST_.",
                  "edited_briefing": "Briefing ajustado TEST_.",
                  "notes": "TEST_approve"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        out = r.json()
        camp_id = out["campaign_id"]
        assert out["recipients_inserted"] >= 0

        # Verify mass_campaign in db
        camp = await db.mass_campaigns.find_one({"id": camp_id})
        assert camp is not None
        assert camp["origin"] == "disparo_ia"
        assert camp["disparo_type"] == "nps_csat"
        assert camp["disparo_suggestion_id"] == sug_id
        assert camp["isabella_briefing"] == "Briefing ajustado TEST_."
        assert camp["text"] == "Oi {{nome}}, mensagem ajustada TEST_."
        assert camp["status"] == "draft"

        # Verify suggestion now approved
        s2 = await db.disparo_suggestions.find_one({"id": sug_id})
        assert s2["status"] == "approved"
        assert s2["campaign_id"] == camp_id

        # Re-approve should fail (status != pending)
        r2 = requests.post(
            f"{BASE}/api/disparo-ia/suggestions/{sug_id}/approve",
            headers=h, json={"channel": "meta_cloud", "throttle_per_min": 60},
            timeout=10,
        )
        assert r2.status_code == 400

        # cleanup
        await db.mass_campaigns.delete_one({"id": camp_id})
        await db.mass_recipients.delete_many({"campaign_id": camp_id})
    finally:
        await db.disparo_suggestions.delete_one({"id": sug_id})


# --- 8. Reject flow
@pytest.mark.asyncio
async def test_reject_flow(db, h):
    sug_id = f"disp-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": sug_id, "company_id": CID, "type": "reactivation",
        "title": "TEST_reject", "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "audience": {}, "audience_preview": {"size": 0, "preview": []},
        "message_template": "x", "isabella_briefing": "",
    }
    await db.disparo_suggestions.insert_one(doc)
    try:
        r = requests.post(
            f"{BASE}/api/disparo-ia/suggestions/{sug_id}/reject",
            headers=h, timeout=10,
        )
        assert r.status_code == 200, r.text
        s2 = await db.disparo_suggestions.find_one({"id": sug_id})
        assert s2["status"] == "rejected"
    finally:
        await db.disparo_suggestions.delete_one({"id": sug_id})


# --- 9. 404 detail
def test_detail_404(h):
    r = requests.get(f"{BASE}/api/disparo-ia/suggestions/disp-nonexistent",
                     headers=h, timeout=10)
    assert r.status_code == 404
