"""Rotas do Google Drive Backup.

OAuth flow (multi-tenant):
  - GET /api/oauth/drive/connect       → gera authorization URL (state=company_id)
  - GET /api/oauth/drive/callback      → callback público, troca code por tokens
  - POST /api/oauth/drive/disconnect   → revoga local

Backup/restore:
  - GET  /api/drive/status             → conectado? quem? folder?
  - POST /api/drive/backup             → backup agora (manual)
  - GET  /api/drive/backups            → histórico
  - GET  /api/drive/remote-files       → lista direto do Drive
  - POST /api/drive/restore            → restaura snapshot escolhido
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from pydantic import BaseModel

from core import get_current_user, require_role
from database import db
from services.drive_backup import (
    disconnect as drive_disconnect,
    download_backup,
    get_connection_info,
    is_connected,
    list_backups,
    list_remote_files,
    restore_backup,
    run_backup,
)

logger = logging.getLogger("routes.drive")
router = APIRouter(prefix="/api", tags=["drive"])


SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _flow() -> Flow:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.environ.get("GOOGLE_DRIVE_REDIRECT_URI")
    if not (client_id and client_secret and redirect_uri):
        raise HTTPException(500, "Google OAuth não configurado no servidor (.env).")
    return Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )


# ============================================================
# OAuth flow
# ============================================================
@router.get("/oauth/drive/connect")
async def oauth_connect(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or "co-demo"
    flow = _flow()
    auth_url, _state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # força consent pra garantir refresh_token
        state=cid,
    )
    # PKCE: salva o code_verifier indexado por state pra recuperar no callback
    code_verifier = getattr(flow, "code_verifier", None)
    if code_verifier:
        from core import now_iso
        await db.drive_oauth_state.update_one(
            {"state": cid},
            {"$set": {"state": cid, "code_verifier": code_verifier, "created_at": now_iso()}},
            upsert=True,
        )
    return {"authorization_url": auth_url}


@router.get("/oauth/drive/callback")
async def oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
):
    """Callback público — Google chama aqui após o usuário aceitar."""
    frontend_url = os.environ.get("PUBLIC_FRONTEND_URL") or ""
    if error:
        return RedirectResponse(f"{frontend_url}/?drive_error={error}")
    if not code or not state:
        raise HTTPException(400, "Missing code or state")

    cid = state
    try:
        flow = _flow()
        # PKCE: recupera o code_verifier salvo no /connect (mesmo state)
        st_doc = await db.drive_oauth_state.find_one({"state": cid}, {"_id": 0, "code_verifier": 1})
        if st_doc and st_doc.get("code_verifier"):
            flow.code_verifier = st_doc["code_verifier"]
        flow.fetch_token(code=code)
        creds = flow.credentials
        # Limpa o verifier consumido
        await db.drive_oauth_state.delete_one({"state": cid})
    except Exception as e:
        logger.exception("[drive] callback fetch_token failed: %s", e)
        return RedirectResponse(f"{frontend_url}/?drive_error=fetch_token")

    # Descobre o e-mail Google de quem autorizou (informativo)
    user_email = None
    try:
        from googleapiclient.discovery import build
        oauth2_service = build("oauth2", "v2", credentials=creds, cache_discovery=False)
        info = oauth2_service.userinfo().get().execute()
        user_email = info.get("email")
    except Exception as e:
        logger.info("[drive] couldn't fetch user_email: %s", e)

    await db.drive_credentials.update_one(
        {"company_id": cid},
        {"$set": {
            "company_id": cid,
            "access_token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes) if creds.scopes else SCOPES,
            "expiry": creds.expiry.isoformat() if creds.expiry else None,
            "user_email": user_email,
            "connected_at": (creds.expiry or None) and creds.expiry.isoformat(),
            "updated_at": creds.expiry.isoformat() if creds.expiry else None,
        }},
        upsert=True,
    )
    # Re-grava connected_at certo
    from core import now_iso
    await db.drive_credentials.update_one(
        {"company_id": cid},
        {"$set": {"connected_at": now_iso()}},
    )

    return RedirectResponse(f"{frontend_url}/?drive_connected=1")


@router.post("/oauth/drive/disconnect")
async def oauth_disconnect(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or "co-demo"
    await drive_disconnect(cid)
    return {"ok": True}


# ============================================================
# Backup / Restore
# ============================================================
@router.get("/drive/status")
async def drive_status(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or "co-demo"
    info = await get_connection_info(cid)
    return info


class BackupIn(BaseModel):
    include_secrets: bool = False


@router.post("/drive/backup")
async def drive_backup(payload: BackupIn = BackupIn(),
                         user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or "co-demo"
    if not await is_connected(cid):
        raise HTTPException(400, "Conecte ao Google Drive primeiro.")
    try:
        return await run_backup(cid, include_secrets=payload.include_secrets,
                                  triggered_by="manual")
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("[drive] backup failed: %s", e)
        raise HTTPException(500, f"Falha ao fazer backup: {e}")


@router.get("/drive/backups")
async def drive_backup_list(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or "co-demo"
    items = await list_backups(cid, limit=30)
    return {"items": items}


@router.get("/drive/remote-files")
async def drive_remote_files(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or "co-demo"
    if not await is_connected(cid):
        raise HTTPException(400, "Drive não conectado.")
    files = await list_remote_files(cid)
    return {"items": files}


class RestoreIn(BaseModel):
    file_id: str
    collections: Optional[List[str]] = None
    mode: str = "merge"  # "merge" | "replace"


@router.post("/drive/restore")
async def drive_restore(payload: RestoreIn,
                          user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or "co-demo"
    if payload.mode not in ("merge", "replace"):
        raise HTTPException(400, "mode deve ser merge ou replace")
    if not await is_connected(cid):
        raise HTTPException(400, "Drive não conectado.")
    try:
        return await restore_backup(cid, payload.file_id,
                                       collections=payload.collections,
                                       mode=payload.mode)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("[drive] restore failed: %s", e)
        raise HTTPException(500, f"Falha ao restaurar: {e}")
