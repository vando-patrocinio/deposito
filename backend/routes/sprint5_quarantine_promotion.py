"""Promover Quarentena — Phase D Add-on · CEO 19/06/2026

Tela para o gestor revisar manualmente as ONUs em quarentena que NÃO 
foram promovidas automaticamente pela Phase C.2 (confidence < 0.90).

Endpoints:
- GET  /api/sprint5/quarantine/candidates    → lista com matches sugeridos
- POST /api/sprint5/quarantine/{id}/approve  → promove tier=quarantine→official
- POST /api/sprint5/quarantine/{id}/reject   → marca como permanent_quarantine
- GET  /api/sprint5/quarantine/search-subscribers?q=...
- GET  /api/sprint5/quarantine/stats         → KPIs da fila

Zero delete. Cada ação grava em `quarantine_promotion_actions` com hash SHA-256.
"""
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorClient

from core import require_role

router = APIRouter(prefix="/api/sprint5/quarantine",
                   tags=["sprint5-quarantine-promotion"])

_client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = _client[os.environ["DB_NAME"]]


def _user_company(user: dict) -> str:
    return user.get("company_id") or "co-demo"


def _norm(s):
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _build_subscriber_index(company_id: str) -> Dict[str, List[Dict]]:
    """Indexa subscribers por nome/pppoe normalizado."""
    idx: Dict[str, List[Dict]] = {}
    cur = db.subscribers.find({"company_id": company_id},
        {"_id": 0, "id": 1, "name": 1, "full_name": 1, "pppoe_user": 1,
         "pppoe": 1, "status": 1, "cto_id": 1, "cto_port_number": 1})
    async for s in cur:
        names = [s.get("name"), s.get("full_name"),
                 s.get("pppoe_user"), s.get("pppoe")]
        for n in names:
            nn = _norm(n)
            if nn and len(nn) >= 5:
                idx.setdefault(nn, []).append(s)
    return idx


def _suggest_for(q: dict, subs_index: Dict[str, List[Dict]]) -> List[Dict]:
    """Sugere até 3 candidatos com confidence + motivo."""
    cn = _norm(q.get("client_name"))
    if not cn or len(cn) < 5:
        return []
    suggestions = []
    seen_ids = set()
    # exact
    if cn in subs_index:
        for s in subs_index[cn]:
            if s["id"] in seen_ids:
                continue
            suggestions.append({
                "subscriber_id": s["id"], "subscriber_name": s.get("name"),
                "confidence": 0.95 if len(subs_index[cn]) == 1 else 0.85,
                "match_path": "exact_pppoe_match",
                "match_evidence":
                    f"{q.get('client_name')} ≡ {s.get('pppoe_user')}",
            })
            seen_ids.add(s["id"])
    # substring
    if len(suggestions) < 3:
        hits = sorted(
            [k for k in subs_index if (cn in k or k in cn) and k != cn],
            key=lambda k: abs(len(k) - len(cn)))[:6]
        for h in hits:
            for s in subs_index[h]:
                if s["id"] in seen_ids:
                    continue
                # confidence proporcional à proximidade de tamanho
                lp = min(len(cn), len(h)) / max(len(cn), len(h))
                conf = round(0.70 + 0.15 * lp, 2)
                suggestions.append({
                    "subscriber_id": s["id"],
                    "subscriber_name": s.get("name"),
                    "confidence": conf,
                    "match_path": "substring_match",
                    "match_evidence":
                        f"{q.get('client_name')} ⊃ {s.get('pppoe_user')}",
                })
                seen_ids.add(s["id"])
                if len(suggestions) >= 3:
                    break
            if len(suggestions) >= 3:
                break
    return suggestions[:3]


@router.get("/stats")
async def stats(
    user: dict = Depends(require_role(
        "administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    total = await db.stok_onts.count_documents({
        "company_id": cid, "asset_status": "pending_validation",
    })
    permanent = await db.stok_onts.count_documents({
        "company_id": cid, "asset_status": "permanent_quarantine",
    })
    promoted_manual = await db.stok_onts.count_documents({
        "company_id": cid, "tier": "official",
        "promotion_evidence.matched_via": "manual_review",
    })
    return {
        "company_id": cid,
        "pending_review": total,
        "permanent_quarantine": permanent,
        "promoted_manually": promoted_manual,
    }


@router.get("/candidates")
async def candidates(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_role(
        "administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    subs_idx = await _build_subscriber_index(cid)
    cur = db.stok_onts.find({
        "company_id": cid, "asset_status": "pending_validation",
    }, {"_id": 0, "id": 1, "sn": 1, "mac": 1, "model": 1, "client_name": 1,
        "olt_name": 1, "port_olt": 1, "smartolt_status": 1,
        "signal_1490": 1, "data_confidence": 1, "imported_at": 1}
    ).sort("imported_at", -1).skip(offset).limit(limit)
    items: List[Dict[str, Any]] = []
    async for q in cur:
        items.append({
            "ont": q,
            "suggestions": _suggest_for(q, subs_idx),
        })
    total = await db.stok_onts.count_documents({
        "company_id": cid, "asset_status": "pending_validation",
    })
    return {"items": items, "total": total,
            "limit": limit, "offset": offset}


@router.get("/search-subscribers")
async def search_subscribers(
    q: str = Query(..., min_length=3),
    limit: int = Query(10, ge=1, le=30),
    user: dict = Depends(require_role(
        "administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    regex = {"$regex": re.escape(q), "$options": "i"}
    cur = db.subscribers.find({
        "company_id": cid,
        "$or": [{"name": regex}, {"full_name": regex},
                {"pppoe_user": regex}, {"pppoe": regex}],
    }, {"_id": 0, "id": 1, "name": 1, "full_name": 1, "pppoe_user": 1,
        "status": 1, "cto_id": 1}).limit(limit)
    return {"items": await cur.to_list(length=limit)}


async def _audit_action(
    *, run_id: str, company_id: str, ont_id: str, action: str,
    actor: dict, payload: Dict[str, Any],
):
    doc = {
        "id": f"qpa-{uuid.uuid4().hex[:10]}",
        "run_id": run_id,
        "company_id": company_id,
        "ont_id": ont_id,
        "action": action,
        "actor_user_id": actor.get("id"),
        "actor_email": actor.get("email"),
        "payload": payload,
        "created_at": _now_iso(),
    }
    doc["hash_sha256"] = hashlib.sha256(
        json.dumps(doc, sort_keys=True, default=str).encode()
    ).hexdigest()
    await db.quarantine_promotion_actions.insert_one(doc)
    return doc


@router.post("/{ont_id}/approve")
async def approve(
    ont_id: str,
    payload: Dict[str, Any] = Body(...),
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Promove ONT da quarentena → official com subscriber_id escolhido.

    payload: { subscriber_id: str, confidence: float, reason: str }
    """
    cid = _user_company(user)
    sub_id = payload.get("subscriber_id")
    conf = float(payload.get("confidence") or 0.0)
    reason = (payload.get("reason") or "").strip()
    if not sub_id:
        raise HTTPException(400, "subscriber_id obrigatório")
    if conf < 0.50:
        raise HTTPException(400, "confidence mínimo 0.50")
    if len(reason) < 10:
        raise HTTPException(400, "reason mínimo 10 chars")

    ont = await db.stok_onts.find_one(
        {"id": ont_id, "company_id": cid}, {"_id": 0})
    if not ont:
        raise HTTPException(404, "ONT não encontrada")
    if ont.get("asset_status") != "pending_validation":
        raise HTTPException(409,
            f"ONT em status {ont.get('asset_status')}; "
            "esperado pending_validation")
    sub = await db.subscribers.find_one(
        {"id": sub_id, "company_id": cid}, {"_id": 0, "id": 1, "name": 1})
    if not sub:
        raise HTTPException(404, "Subscriber não encontrado")

    run_id = f"qpr-{uuid.uuid4().hex[:8]}"
    await db.stok_onts.update_one(
        {"id": ont_id},
        {"$set": {
            "tier": "official",
            "asset_status": "validado",
            "exclude_from_balance": False,
            "subscriber_id": sub_id,
            "data_confidence": conf,
            "data_confidence_path": "manual_review",
            "promoted_at": _now_iso(),
            "promoted_by": user.get("id") or "manual",
            "manual_promotion_run_id": run_id,
            "promotion_evidence": {
                "matched_subscriber_id": sub_id,
                "matched_subscriber_name": sub.get("name"),
                "matched_via": "manual_review",
                "reviewer_user_id": user.get("id"),
                "reviewer_email": user.get("email"),
                "reviewer_reason": reason,
                "confidence_assigned": conf,
            },
        }},
    )
    audit = await _audit_action(
        run_id=run_id, company_id=cid, ont_id=ont_id,
        action="approve", actor=user,
        payload={"subscriber_id": sub_id,
                  "subscriber_name": sub.get("name"),
                  "confidence": conf, "reason": reason},
    )
    return {"ok": True, "ont_id": ont_id, "subscriber_id": sub_id,
            "run_id": run_id, "audit_id": audit["id"]}


@router.post("/{ont_id}/reject")
async def reject(
    ont_id: str,
    payload: Dict[str, Any] = Body(...),
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Marca ONT como permanent_quarantine (sem cliente identificado).

    payload: { reason: str (≥20 chars) }
    """
    cid = _user_company(user)
    reason = (payload.get("reason") or "").strip()
    if len(reason) < 20:
        raise HTTPException(400, "reason mínimo 20 chars")

    ont = await db.stok_onts.find_one(
        {"id": ont_id, "company_id": cid}, {"_id": 0})
    if not ont:
        raise HTTPException(404, "ONT não encontrada")
    if ont.get("asset_status") != "pending_validation":
        raise HTTPException(409,
            f"ONT em status {ont.get('asset_status')}; "
            "esperado pending_validation")

    run_id = f"qpr-{uuid.uuid4().hex[:8]}"
    await db.stok_onts.update_one(
        {"id": ont_id},
        {"$set": {
            "asset_status": "permanent_quarantine",
            "exclude_from_balance": True,
            "permanently_quarantined_at": _now_iso(),
            "permanently_quarantined_by": user.get("id") or "manual",
            "permanent_quarantine_reason": reason,
            "manual_review_run_id": run_id,
        }},
    )
    audit = await _audit_action(
        run_id=run_id, company_id=cid, ont_id=ont_id,
        action="reject", actor=user, payload={"reason": reason},
    )
    return {"ok": True, "ont_id": ont_id,
            "run_id": run_id, "audit_id": audit["id"]}
