"""Testes da FASE 5 — AI Center OS executive endpoints."""
from __future__ import annotations
import asyncio, os, sys
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _run(coro_factory):
    async def _wrap():
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        import importlib
        import database as database_mod
        database_mod.db = db
        from services import (revenue_attribution, data_quality_v2,
                               nervous_coverage, smartolt_twin)
        for m in (revenue_attribution, data_quality_v2,
                   nervous_coverage, smartolt_twin):
            importlib.reload(m)
        try:
            return await coro_factory(db)
        finally:
            c.close()
    return asyncio.run(_wrap())


def test_executive_endpoint_imports_ok():
    """Verifica que o module loads e expõe o router."""
    from routes import ai_center_home
    assert ai_center_home.router is not None
    # 4 endpoints esperados
    routes = [r.path for r in ai_center_home.router.routes]
    assert "/api/ai-center/executive-summary" in routes
    assert "/api/ai-center/decisions" in routes
    assert "/api/ai-center/actions" in routes
    assert "/api/ai-center/learnings" in routes


def test_briefing_kpis_shape():
    """Smoke test: kpis tem todas as chaves esperadas pela home."""
    async def go(db):
        # Apenas garantir os services agregadores funcionam juntos
        from services.revenue_attribution import summary
        from services.smartolt_twin import revenue_at_risk
        s = await summary("co-demo")
        r = await revenue_at_risk("co-demo")
        assert "_total_BRL" in s
        assert "monthly_BRL_at_risk" in r
    _run(go)
