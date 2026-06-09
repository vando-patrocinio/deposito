"""Teste end-to-end do Reajuste IPCA com cascata.

Roda todos os asserts dentro de uma única função async para evitar
conflito de event loop com motor (driver MongoDB async).
"""
import asyncio
import sys
import uuid
from datetime import datetime, timezone


def test_readjustment_cascade_end_to_end():
    """Cobre: pendências, cascata IPCA histórico, apply persiste logs."""
    sys.path.insert(0, "/app/backend")

    from database import db
    from services.inflation import refresh_index_cache
    from services.readjustment import (
        apply_readjustment,
        calculate_readjustment_preview,
        compute_pending_anniversaries,
    )

    async def _run():
        # Setup: garante série histórica do IPCA cacheada
        await refresh_index_cache("IPCA")

        # ------- Caso 1: 5 anos sem reajuste → 5 pendências -------
        sub = {
            "installation_date": "2021-01-27T00:00:00+00:00",
            "last_readjustment_at": None,
        }
        pending = compute_pending_anniversaries(sub)
        assert len(pending) >= 4, \
            f"Esperava >=4 pendências, veio {len(pending)}"
        assert pending[0].year == 2022 and pending[0].month == 1

        # ------- Caso 2: instalado recente → 0 pendências -------
        sub2 = {
            "installation_date": "2025-12-01T00:00:00+00:00",
            "last_readjustment_at": None,
        }
        assert len(compute_pending_anniversaries(sub2)) == 0

        # ------- Caso 3: Preview cascata usa IPCA histórico -------
        sub3 = {
            "id": "test-cascade-x",
            "name": "Teste",
            "installation_date": "2021-01-27T00:00:00+00:00",
            "last_readjustment_at": None,
            "plan_price": 100.0,
            "readjustment_index": "IPCA",
        }
        preview = await calculate_readjustment_preview(sub3)
        assert preview is not None
        assert preview["is_due"] is True
        assert preview["pending_count"] >= 4

        pcts = [s["accumulated_pct"] for s in preview["cascade"]]
        distinct = len(set(round(p, 1) for p in pcts))
        assert distinct >= 3, \
            f"IPCAs muito iguais ({pcts}) — provavelmente fallback"
        assert preview["new_price"] > 100.0
        assert preview["accumulated_pct_total"] > max(pcts)

        # ------- Caso 4: Apply persiste múltiplos logs -------
        sub_id = f"test-apply-{uuid.uuid4().hex[:8]}"
        sub4 = {
            "id": sub_id, "company_id": "co-test", "name": "Apply Test",
            "installation_date": "2022-03-15T00:00:00+00:00",
            "last_readjustment_at": None,
            "plan_price": 89.90, "readjustment_index": "IPCA",
        }
        await db.subscribers.insert_one({**sub4, "status": "ATIVO"})
        try:
            result = await apply_readjustment(sub4, actor="test")
            assert result["applied"] is True
            assert result["applied_count"] >= 2

            logs = await db.subscriber_readjustments.find(
                {"subscriber_id": sub_id}, {"_id": 0},
            ).to_list(50)
            assert len(logs) == result["applied_count"]

            updated = await db.subscribers.find_one(
                {"id": sub_id}, {"_id": 0})
            assert updated["plan_price"] == result["final_price"]
            assert updated["last_readjustment_at"] is not None
        finally:
            await db.subscribers.delete_one({"id": sub_id})
            await db.subscriber_readjustments.delete_many(
                {"subscriber_id": sub_id})

        # ------- Caso 5: sem virada vencida + sem force → não aplica -------
        sub_id5 = f"test-notdue-{uuid.uuid4().hex[:8]}"
        sub5 = {
            "id": sub_id5, "company_id": "co-test", "name": "Not Due",
            "installation_date": datetime.now(timezone.utc).isoformat(),
            "plan_price": 99.90,
        }
        await db.subscribers.insert_one({**sub5, "status": "ATIVO"})
        try:
            result5 = await apply_readjustment(sub5, actor="test",
                                                force=False)
            assert result5["applied"] is False
            assert result5["reason"] == "not_due_yet"
        finally:
            await db.subscribers.delete_one({"id": sub_id5})

    asyncio.run(_run())
