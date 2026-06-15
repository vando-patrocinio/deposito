"""CORPORATE GOALS — fonte de verdade das metas anuais por tenant.

Substitui o hardcode METAS_2026 em executive_memory.py.
Schema em MongoDB collection `corporate_goals`:
    {
      id, company_id, kpi_key, baseline, target, direction,
      baseline_date, owner, deadline,
      status: "active" | "archived",
      created_at, updated_at, source
    }

Regras:
- KPI canônico = kpi_key (ex: clientes_ativos, mrr, inadimplencia_brl,
  embaixadores, fundadores_aptos).
- Só metas com status="active" entram em snapshot/course_correction.
- Tenants sintéticos são bloqueados pelo executive_memory (não aqui).
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "ceo_digital",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from database import db

logger = logging.getLogger(__name__)

# Seed canônico (15/06/2026). Usado APENAS se a collection estiver vazia
# para o tenant — caso contrário, MongoDB é a fonte de verdade.
SEED_METAS_2026 = {
    "clientes_ativos": {
        "baseline": 2753, "target": 3500, "direction": "up",
        "owner": "ceo", "deadline": "2026-12-31",
    },
    "mrr": {
        "baseline": 325241.59, "target": 450000.0, "direction": "up",
        "owner": "ceo", "deadline": "2026-12-31",
    },
    "inadimplencia_brl": {
        "baseline": 62485.08, "target": 31000.0, "direction": "down",
        "owner": "cfo", "deadline": "2026-12-31",
    },
    "embaixadores": {
        "baseline": 1, "target": 50, "direction": "up",
        "owner": "ceo", "deadline": "2026-12-31",
    },
    "fundadores_aptos": {
        "baseline": 2, "target": 30, "direction": "up",
        "owner": "ceo", "deadline": "2026-12-31",
    },
}
BASELINE_DATE = "2026-06-15"


async def ensure_seeded(cid: str) -> dict:
    """Idempotente. Insere SEED_METAS_2026 se ainda não houver doc CEO ativo
    para o tenant. Retorna {seeded: int, skipped: int}.
    """
    # Hardening: índice composto previne race em workers concorrentes.
    # partialFilterExpression isola do schema legado Isabella (sem kpi_key).
    try:
        await db.corporate_goals.create_index(
            [("company_id", 1), ("kpi_key", 1), ("status", 1)],
            unique=True,
            partialFilterExpression={"kpi_key": {"$exists": True}},
            name="uniq_ceo_goal_per_kpi_status",
        )
    except Exception:
        logger.exception("não foi possível criar índice corporate_goals (não-fatal)")

    now = datetime.now(timezone.utc).isoformat()
    seeded = 0
    skipped = 0
    for kpi_key, m in SEED_METAS_2026.items():
        existing = await db.corporate_goals.find_one({
            "company_id": cid, "kpi_key": kpi_key, "status": "active"})
        if existing:
            skipped += 1
            continue
        doc = {
            "id": f"goal-{uuid.uuid4().hex[:14]}",
            "company_id": cid,
            "kpi_key": kpi_key,
            "baseline": float(m["baseline"]),
            "target": float(m["target"]),
            "direction": m["direction"],
            "baseline_date": BASELINE_DATE,
            "owner": m["owner"],
            "deadline": m["deadline"],
            "status": "active",
            "source": "seed_metas_2026",
            "created_at": now,
            "updated_at": now,
        }
        await db.corporate_goals.insert_one(doc)
        seeded += 1
    return {"seeded": seeded, "skipped": skipped}


async def get_metas(cid: str, auto_seed: bool = True) -> dict[str, dict]:
    """Lê metas ATIVAS do MongoDB para um tenant.

    Filtra por kpi_key existente para isolar do schema Isabella legado
    (que usa metric/area/target_value). Retorna dict {kpi_key: {...}}.
    """
    # Filtro com kpi_key garantido: isola dos goals Isabella legados.
    flt = {"company_id": cid, "status": "active",
           "kpi_key": {"$exists": True, "$ne": None}}
    cur = db.corporate_goals.find(flt, {"_id": 0})
    items = await cur.to_list(length=200)
    if not items and auto_seed:
        await ensure_seeded(cid)
        cur = db.corporate_goals.find(flt, {"_id": 0})
        items = await cur.to_list(length=200)

    out: dict[str, dict] = {}
    for it in items:
        out[it["kpi_key"]] = {
            "baseline": float(it.get("baseline") or 0),
            "target": float(it.get("target") or 0),
            "direction": it.get("direction") or "up",
            "owner": it.get("owner"),
            "deadline": it.get("deadline"),
        }
    return out


async def list_goals(cid: str) -> list[dict]:
    """Lista CEO goals (kpi_key based). Não retorna Isabella legacy goals."""
    flt = {"company_id": cid, "kpi_key": {"$exists": True, "$ne": None}}
    cur = db.corporate_goals.find(flt, {"_id": 0})
    return await cur.to_list(length=500)


async def upsert_goal(cid: str, kpi_key: str, payload: dict) -> dict:
    """Cria ou atualiza um CEO goal (filtra por kpi_key)."""
    now = datetime.now(timezone.utc).isoformat()
    existing = await db.corporate_goals.find_one({
        "company_id": cid, "kpi_key": kpi_key, "status": "active"})
    set_doc = {k: v for k, v in payload.items() if v is not None}
    set_doc["updated_at"] = now
    if existing:
        await db.corporate_goals.update_one(
            {"id": existing["id"]}, {"$set": set_doc})
        return {"ok": True, "id": existing["id"], "action": "updated"}

    doc = {
        "id": f"goal-{uuid.uuid4().hex[:14]}",
        "company_id": cid,
        "kpi_key": kpi_key,
        "baseline": float(payload.get("baseline") or 0),
        "target": float(payload.get("target") or 0),
        "direction": payload.get("direction") or "up",
        "baseline_date": payload.get("baseline_date") or BASELINE_DATE,
        "owner": payload.get("owner") or "ceo",
        "deadline": payload.get("deadline") or "2026-12-31",
        "status": payload.get("status") or "active",
        "source": "manual",
        "created_at": now,
        "updated_at": now,
    }
    await db.corporate_goals.insert_one(doc)
    return {"ok": True, "id": doc["id"], "action": "created"}
