"""admin_safety.py — Endpoints administrativos das 3 medidas P0.

Kill Switch + Backup + Secrets Vault. Acesso restrito a super_admin.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Body
from typing import Optional

from core import require_role
from services import kill_switch as ks
from services import mongo_backup as bk
from services import secrets_vault as vault

router = APIRouter(prefix="/api/admin/safety", tags=["admin-safety"])


def _actor(user):
    return (user.get("email") or user.get("user", {}).get("email")
            or "unknown_admin")


# ─────────────── KILL SWITCH ───────────────
@router.get("/killswitch/status")
async def killswitch_status(company_id: Optional[str] = None,
                            user=Depends(require_role("administrador",
                                                      "auditor"))):
    return await ks.get_all_states(company_id)


@router.post("/killswitch/{component}")
async def killswitch_toggle(component: str,
                            body: dict = Body(...),
                            user=Depends(require_role("administrador"))):
    if component not in ks.COMPONENTS:
        raise HTTPException(400, f"componente inválido (usar: {ks.COMPONENTS})")
    off = bool(body.get("off", body.get("on") is False))
    reason = body.get("reason", "")
    company_id = body.get("company_id")
    return await ks.set_state(component, off=off, reason=reason,
                              updated_by=_actor(user),
                              company_id=company_id)


# ─────────────── BACKUP ───────────────
@router.get("/backup/list")
async def backup_list(user=Depends(require_role("administrador", "auditor"))):
    items = bk.list_backups()
    return {"count": len(items), "items": items}


@router.post("/backup/snapshot")
async def backup_snapshot(user=Depends(require_role("administrador"))):
    return bk.snapshot_now()


@router.post("/backup/purge-old")
async def backup_purge(user=Depends(require_role("administrador"))):
    purged = bk.purge_old()
    return {"purged_count": len(purged), "purged": purged}


# ─────────────── SECRETS VAULT ───────────────
@router.get("/secrets/list")
async def secrets_list(scope: Optional[str] = None,
                       user=Depends(require_role("administrador"))):
    return await vault.list_secrets(scope=scope)


@router.post("/secrets/{name}")
async def secrets_set(name: str,
                      body: dict = Body(...),
                      user=Depends(require_role("administrador"))):
    value = body.get("value")
    if not value:
        raise HTTPException(400, "value obrigatório")
    return await vault.set_secret(
        name=name, value=value,
        scope=body.get("scope", "global"),
        updated_by=_actor(user),
        hint=body.get("hint", ""))


@router.delete("/secrets/{name}")
async def secrets_delete(name: str,
                         scope: str = "global",
                         user=Depends(require_role("administrador"))):
    return await vault.delete_secret(name=name, scope=scope,
                                     deleted_by=_actor(user))
