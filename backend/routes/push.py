"""Endpoints de Web Push (notificações ao gestor)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, get_current_user, is_super_admin, require_role
from database import db
from push_service import (
    broadcast as push_broadcast,
    get_or_create_vapid,
    list_subscriptions as push_list_subs,
    remove_subscription as push_remove_sub,
    save_subscription as push_save_sub,
)

router = APIRouter(prefix="/api/push", tags=["push"])


class PushSubscriptionIn(BaseModel):
    endpoint: str
    keys: dict
    user_agent: Optional[str] = None


@router.get("/vapid-public-key")
async def push_vapid_key():
    keys = await get_or_create_vapid(db)
    return {"public_key": keys["vapid_public_key"]}


@router.post("/subscribe")
async def push_subscribe(payload: PushSubscriptionIn, current_user: dict = Depends(get_current_user)):
    cid = current_user.get("company_id") or DEMO_COMPANY_ID
    sub = await push_save_sub(db, current_user.get("id"), payload.model_dump(), company_id=cid)
    return {"ok": True, "endpoint": sub["endpoint"]}


@router.post("/unsubscribe")
async def push_unsubscribe(payload: dict, current_user: dict = Depends(get_current_user)):
    endpoint = (payload or {}).get("endpoint")
    if not endpoint:
        raise HTTPException(400, "endpoint obrigatório")
    ok = await push_remove_sub(db, endpoint)
    return {"ok": ok}


@router.get("/subscriptions")
async def push_subscriptions(user: dict = Depends(require_role("gestor", "auditor"))):
    cid = None if is_super_admin(user) else (user.get("company_id") or DEMO_COMPANY_ID)
    subs = await push_list_subs(db, only_active=True, allowed_roles=["gestor", "auditor"], company_id=cid)
    return [{
        "endpoint": s["endpoint"][:80] + ("..." if len(s["endpoint"]) > 80 else ""),
        "user_id": s.get("user_id"),
        "user_agent": s.get("user_agent"),
        "created_at": s.get("created_at"),
    } for s in subs]


@router.post("/test")
async def push_test(user: dict = Depends(require_role("gestor", "auditor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    payload = {
        "title": "🔔 Teste de notificação",
        "body": "Notificações habilitadas com sucesso para o painel do gestor.",
        "tag": "push-test",
        "url": "/?tab=gestor",
    }
    return await push_broadcast(db, payload, allowed_roles=["gestor", "auditor"], company_id=cid)
