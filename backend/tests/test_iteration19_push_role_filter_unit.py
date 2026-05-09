"""Direct unit test on push_service.list_subscriptions filtering by allowed_roles.
Inserts two synthetic users (one auditor, one colaborador) and one push sub per user,
then asserts list_subscriptions(allowed_roles=['gestor','auditor']) returns ONLY
the auditor sub. Cleans up at end.
"""
import os
import sys
import uuid
import asyncio
import pytest

sys.path.insert(0, "/app/backend")

from database import db  # noqa: E402
from push_service import list_subscriptions  # noqa: E402


@pytest.mark.asyncio
async def test_list_subscriptions_role_filter():
    suffix = uuid.uuid4().hex[:8]
    auditor_uid = f"TEST_iter19_aud_{suffix}"
    col_uid = f"TEST_iter19_col_{suffix}"
    aud_endpoint = f"https://fcm.googleapis.com/test/aud_{suffix}"
    col_endpoint = f"https://fcm.googleapis.com/test/col_{suffix}"

    # seed users
    await db.users.insert_one({
        "id": auditor_uid, "email": f"{auditor_uid}@t.com", "role": "auditor",
        "active": True, "name": "TEST_iter19_aud", "password_hash": "x",
    })
    await db.users.insert_one({
        "id": col_uid, "email": f"{col_uid}@t.com", "role": "colaborador",
        "active": True, "name": "TEST_iter19_col", "password_hash": "x",
    })
    # seed subs
    await db.push_subscriptions.insert_one({
        "endpoint": aud_endpoint, "user_id": auditor_uid, "active": True,
        "keys": {"p256dh": "x", "auth": "y"}, "user_agent": "pytest",
    })
    await db.push_subscriptions.insert_one({
        "endpoint": col_endpoint, "user_id": col_uid, "active": True,
        "keys": {"p256dh": "x", "auth": "y"}, "user_agent": "pytest",
    })

    try:
        # Without filter — both should appear (or at least our 2 are present)
        all_subs = await list_subscriptions(db, only_active=True)
        eps_all = {s["endpoint"] for s in all_subs}
        assert aud_endpoint in eps_all
        assert col_endpoint in eps_all

        # With filter — only the auditor sub
        filtered = await list_subscriptions(db, only_active=True, allowed_roles=["gestor", "auditor"])
        eps_filtered = {s["endpoint"] for s in filtered}
        assert aud_endpoint in eps_filtered, "auditor sub MUST be present"
        assert col_endpoint not in eps_filtered, "colaborador sub LEAKED — filter broken"
    finally:
        await db.users.delete_many({"id": {"$in": [auditor_uid, col_uid]}})
        await db.push_subscriptions.delete_many({"endpoint": {"$in": [aud_endpoint, col_endpoint]}})
