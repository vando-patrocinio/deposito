"""sprint5_onda6 — Auto Balanço Patrimonial Mensal (CEO 19/02/2026)

Endpoints (prefix /api/sprint5/onda6):
  POST /run-snapshot              — snapshot diário (idempotente, cron 00:05)
  POST /close-month?year_month=   — fechamento mensal + certidão
  GET  /latest                    — último fechamento publicado
  GET  /history                   — todos os fechamentos
  GET  /current-month-kpis        — KPIs do mês corrente em tempo real
"""

NERVOUS_METADATA = {
    "owner": "infra-team",
    "domain": "patrimonio",
    "criticality": "critical",
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core import require_role
from database import db
from services.balance_engine import (
    BALANCE_COLLECTION, BALANCE_VERSION,
    compute_monthly_balance, get_latest_closing, _month_key,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sprint5/onda6", tags=["sprint5", "onda6"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_company(user: dict) -> str:
    cid = user.get("company_id")
    if not cid:
        raise HTTPException(400, "Usuário sem company_id")
    return cid


@router.post("/run-snapshot")
async def run_snapshot(
    year_month: Optional[str] = Query(None,
        description="Default: mês corrente UTC (YYYY-MM)"),
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Snapshot diário (não-fechamento). Pode ser chamado pelo cron 00:05."""
    cid = _user_company(user)
    ym = year_month or _month_key(datetime.now(timezone.utc))
    doc = await compute_monthly_balance(
        db, cid, ym, snapshot_only=True,
        actor_user_id=user.get("id") or "system")
    return {
        "snapshot_id": doc["snapshot_id"],
        "year_month": ym,
        "is_closing": False,
        "kpis": doc["kpis"],
        "status": doc["status"],
        "hash_sha256": doc["hash_sha256"],
        "generated_at": doc["generated_at"],
    }


@router.post("/close-month")
async def close_month(
    year_month: str = Query(..., description="YYYY-MM"),
    confirm: bool = Query(False, description="DEVE ser true"),
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Fechamento oficial do mês — emite CERTIDÃO assinada SHA-256."""
    if not confirm:
        raise HTTPException(400,
            "close-month requer ?confirm=true")
    cid = _user_company(user)
    # Validar formato YYYY-MM
    try:
        datetime.strptime(year_month, "%Y-%m")
    except ValueError:
        raise HTTPException(400, "year_month deve ser YYYY-MM")

    doc = await compute_monthly_balance(
        db, cid, year_month, snapshot_only=False,
        actor_user_id=user.get("id") or "system")

    try:
        await db.sprint5_audit_log.insert_one({
            "id": f"o6a-{uuid.uuid4().hex[:14]}",
            "batch_id": doc["snapshot_id"],
            "company_id": cid,
            "wave": "sprint5_onda6",
            "action": "month_closed",
            "target": f"{BALANCE_COLLECTION}/{year_month}",
            "payload": {
                "kpis": doc["kpis"],
                "status": doc["status"],
                "hash_sha256": doc["hash_sha256"],
            },
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "created_at": _now_iso(),
        })
    except Exception:
        pass

    return doc


@router.get("/latest")
async def latest(
    year_month: Optional[str] = Query(None),
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    doc = await get_latest_closing(db, cid, year_month)
    if not doc:
        raise HTTPException(404,
            f"Nenhum fechamento encontrado para {year_month or 'qualquer mês'}")
    return doc


@router.get("/history")
async def history(
    limit: int = Query(24, ge=1, le=120),
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    items = await db[BALANCE_COLLECTION].find(
        {"company_id": cid, "is_closing": True},
        {"_id": 0, "snapshot_id": 1, "year_month": 1, "status": 1,
         "hash_sha256": 1, "kpis": 1, "generated_at": 1}
    ).sort("year_month", -1).limit(limit).to_list(length=limit)
    return {"items": items, "count": len(items)}


@router.get("/current-month-kpis")
async def current_month_kpis(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    """KPIs do mês corrente sem persistir snapshot (read-only)."""
    cid = _user_company(user)
    ym = _month_key(datetime.now(timezone.utc))
    doc = await compute_monthly_balance(
        db, cid, ym, snapshot_only=True,
        actor_user_id=user.get("id") or "system")
    # Remove o doc recém-criado para manter read-only
    await db[BALANCE_COLLECTION].delete_one({"id": doc["id"]})
    return {
        "year_month": ym,
        "kpis": doc["kpis"],
        "status_projection": doc["status"],
        "hash_sha256": doc["hash_sha256"],
        "abertura": doc["abertura"],
        "movimentacao": doc["movimentacao"],
        "fechamento": doc["fechamento"],
        "balance_version": BALANCE_VERSION,
        "issued_at": _now_iso(),
    }
