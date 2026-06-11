"""
ai_center_data_quality.py — FASE 2 da Constituição V3.0
Endpoints REST do Data Quality v2.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["subscriber.updated"],
    "company_id_required": True,
}

import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from rbac import require_roles
from database import db
from services import data_quality_v2 as dq


router = APIRouter(prefix="/api/ai-center/data-quality",
                    tags=["ai-center-data-quality"])


def _company_id(user: Dict[str, Any]) -> str:
    cid = user.get("company_id") or user.get("user", {}).get("company_id")
    if not cid:
        raise HTTPException(400, "company_id ausente")
    return cid


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/score")
async def get_score(
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    """Score corporativo completo (6 domínios + overall + revenue impact)."""
    company_id = _company_id(user)
    r = await dq.full_report(company_id)
    # Snapshot histórico (para timeline)
    snapshot = {
        "id": f"dq-{uuid.uuid4().hex[:14]}",
        "company_id": company_id,
        "created_at": _iso(),
        "overall_score": r["overall_score"],
        "overall_level": r["overall_level"],
        "domain_scores": {k: v["score"] for k, v in r["domains"].items()},
        "locked_BRL": r["revenue_impact"]["locked_BRL"],
    }
    try:
        await db.data_quality_snapshots.insert_one(snapshot.copy())
    except Exception:
        pass

    # Verifica drop/recovery vs último snapshot
    try:
        last = await db.data_quality_snapshots.find_one(
            {"company_id": company_id,
             "id": {"$ne": snapshot["id"]}},
            sort=[("created_at", -1)],
        )
        if last:
            delta = snapshot["overall_score"] - last["overall_score"]
            if abs(delta) >= 1.0:
                from services.event_bus import emit_business
                event_type = ("DATA_QUALITY_DROP" if delta < 0
                              else "DATA_QUALITY_RECOVERY")
                try:
                    await emit_business(
                        event_type=event_type,
                        source="data_quality_v2",
                        company_id=company_id,
                        payload={
                            "from": last["overall_score"],
                            "to": snapshot["overall_score"],
                            "delta": round(delta, 2),
                            "level": snapshot["overall_level"],
                        },
                    )
                except Exception:
                    pass
    except Exception:
        pass

    return r


@router.get("/timeline")
async def get_timeline(
    days: int = 30,
    user: Dict[str, Any] = Depends(
        require_roles("administrador", "auditor", "gestor")),
):
    """Histórico de overall_score (snapshot por chamada)."""
    company_id = _company_id(user)
    cur = db.data_quality_snapshots.find(
        {"company_id": company_id}
    ).sort("created_at", -1).limit(200)
    items = []
    async for d in cur:
        d.pop("_id", None)
        items.append(d)
    return {"items": items}


@router.post("/run-backfill")
async def run_backfill(
    user: Dict[str, Any] = Depends(require_roles("administrador")),
):
    """Re-executa backfill (admin). Returns delta antes/depois."""
    company_id = _company_id(user)
    # subprocess seria ideal, mas chamamos in-process
    import sys
    from pathlib import Path
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        # Mede antes
        before = await dq.full_report(company_id)
        # Chama a lógica de backfill (recriada inline)
        from backfill_subscribers_contact import (
            normalize_phone,
        )
        from collections import defaultdict
        phones = await db.subscriber_phones.find(
            {"company_id": company_id}).to_list(None)
        by_sub: Dict[str, list] = defaultdict(list)
        for p in phones:
            by_sub[p["subscriber_id"]].append(p)
        updated = 0
        for sid, plist in by_sub.items():
            plist.sort(key=lambda p: (
                not bool(p.get("is_primary")),
                p.get("is_whatsapp") is not True,
            ))
            ph = None
            wa = None
            for p in plist:
                n = normalize_phone(
                    p.get("normalized_number") or p.get("raw_number"))
                if not n:
                    continue
                if not ph:
                    ph = n
                if p.get("is_whatsapp") is not False and not wa:
                    wa = n
            upd = {}
            if ph:
                upd["phone"] = ph
            if wa:
                upd["whatsapp"] = wa
            if upd:
                upd["phone_backfilled_at"] = _iso()
                await db.subscribers.update_one(
                    {"id": sid, "company_id": company_id},
                    {"$set": upd})
                try:
                    from services.event_bus import emit_event
                    await emit_event(
                        "subscriber.updated",
                        company_id=company_id,
                        source="ai_center_data_quality",
                        payload={},
                    )
                except Exception:
                    pass
                updated += 1
        after = await dq.full_report(company_id)
        return {
            "ok": True,
            "subscribers_updated": updated,
            "before": {"overall_score": before["overall_score"]},
            "after": {"overall_score": after["overall_score"]},
            "delta": round(
                after["overall_score"] - before["overall_score"], 2),
        }
    except Exception as e:
        raise HTTPException(500, f"backfill_failed: {e}")
