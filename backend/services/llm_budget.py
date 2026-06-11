"""
llm_budget.py — Budget guard do Estrategista IA.

Conta chamadas LLM por (company_id, ano-mês) e bloqueia quando o
orçamento mensal estoura.

Configuração via env:
    ESTRATEGISTA_BUDGET_MONTHLY  -- limite global (default 1000)
    ESTRATEGISTA_BUDGET_PER_CO   -- limite por company_id (default 200)
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import os
from datetime import datetime, timezone
from typing import Dict, Optional

from database import db


def _ym() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _global_limit() -> int:
    try:
        return int(os.environ.get("ESTRATEGISTA_BUDGET_MONTHLY", "1000"))
    except Exception:
        return 1000


def _per_co_limit() -> int:
    try:
        return int(os.environ.get("ESTRATEGISTA_BUDGET_PER_CO", "200"))
    except Exception:
        return 200


async def check_budget(company_id: Optional[str] = None) -> Dict[str, object]:
    """Retorna {ok: bool, reason: str, used: int, limit: int, ym: str}.

    `ok=False` indica que a chamada NÃO deve ser feita.
    """
    ym = _ym()
    doc = await db.llm_budget.find_one({"_id": ym}) or {}
    global_used = int(doc.get("global", 0))
    per_co = doc.get("by_company") or {}
    co_used = int(per_co.get(company_id or "_anon_", 0))

    g_limit = _global_limit()
    c_limit = _per_co_limit()

    if global_used >= g_limit:
        return {"ok": False, "reason": "global_limit_reached",
                "used": global_used, "limit": g_limit, "ym": ym}
    if company_id and co_used >= c_limit:
        return {"ok": False, "reason": "company_limit_reached",
                "used": co_used, "limit": c_limit, "ym": ym}
    return {"ok": True, "reason": "within_budget",
            "used": global_used, "limit": g_limit, "ym": ym,
            "company_used": co_used, "company_limit": c_limit}


async def increment(company_id: Optional[str] = None) -> None:
    """Incrementa contador após uma chamada LLM bem-sucedida."""
    ym = _ym()
    key_co = f"by_company.{company_id or '_anon_'}"
    try:
        await db.llm_budget.update_one(
            {"_id": ym},
            {"$inc": {"global": 1, key_co: 1},
             "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    except Exception:
        pass


async def get_status(company_id: Optional[str] = None) -> Dict[str, object]:
    """Retorna uso atual do mês (admin/monitoramento)."""
    ym = _ym()
    doc = await db.llm_budget.find_one({"_id": ym}) or {}
    return {
        "ym": ym,
        "global_used": int(doc.get("global", 0)),
        "global_limit": _global_limit(),
        "per_company_limit": _per_co_limit(),
        "by_company": doc.get("by_company") or {},
    }
