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

from fastapi import APIRouter, Depends, HTTPException, Header, Query, UploadFile, File, Form
from fastapi.responses import RedirectResponse, StreamingResponse
from google_auth_oauthlib.flow import Flow
from pydantic import BaseModel

from core import get_current_user, require_role
from database import db
from services.drive_backup import (
    _build_files_tarball,
    _collect_snapshot,
    disconnect as drive_disconnect,
    download_backup,
    get_connection_info,
    get_snapshot_info,
    is_connected,
    list_backups,
    list_remote_files,
    restore_backup,
    restore_backup_from_bytes,
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


@router.get("/drive/snapshot-info")
async def drive_snapshot_info(user: dict = Depends(require_role("gestor"))):
    """Pré-visualiza conteúdo do próximo backup (sem persistir nada)."""
    cid = user.get("company_id") or "co-demo"
    return await get_snapshot_info(cid)


# ============================================================
# Backup LOCAL — gera snapshot e devolve como download direto.
# Não precisa de Drive conectado. Não tem rate limit. Sem persistir
# remoto. Útil quando o usuário só quer guardar manualmente ou usar
# em "Provisionamento 1-clique" sem depender do Drive.
# ============================================================
@router.post("/drive/backup-local")
@router.get("/drive/backup-local")
async def drive_backup_local(
    include_secrets: bool = False,
    include_files: bool = True,
    include_optional_files: bool = True,
    t: Optional[str] = Query(default=None,
                              description="JWT alternativo via query (uso em "
                              "<a href> ou window.open quando o navegador "
                              "não permite headers customizados)."),
    authorization: Optional[str] = Header(default=None),
):
    """Gera snapshot completo (MongoDB + arquivos opcional) e devolve como
    arquivo ZIP pro download imediato do navegador.

    Auth: aceita `Authorization: Bearer ...` (padrão fetch/axios) OU
    `?t=<jwt>` (necessário para download direto via <a href> ou nova aba,
    pois o navegador não envia headers customizados em navegação).
    """
    # Resolve usuário aceitando os 2 modos de auth
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif t:
        token = t
    if not token:
        raise HTTPException(401, "Token requerido (header ou ?t=)")
    try:
        from auth import decode_token
        payload = decode_token(token)
    except Exception:
        raise HTTPException(401, "Token inválido ou expirado")
    user_id = payload.get("sub")
    user = await db.users.find_one(
        {"id": user_id}, {"_id": 0, "password_hash": 0})
    if not user or not user.get("active", True):
        raise HTTPException(401, "Usuário inativo")
    # Role check — gestor/administrador/super_admin
    role = user.get("role") or ""
    if role not in ("gestor", "administrador") and not user.get("is_super_admin"):
        raise HTTPException(403, "Apenas gestor/administrador pode baixar backup.")
    user["company_id"] = user.get("company_id") or payload.get("company_id") or "co-demo"

    import io
    import zipfile
    from datetime import datetime, timezone

    cid = user.get("company_id") or "co-demo"
    started = datetime.now(timezone.utc)

    # 1. Snapshot MongoDB
    snapshot = await _collect_snapshot(cid, include_secrets)
    snapshot_bytes = __import__("json").dumps(
        snapshot, ensure_ascii=False, indent=2, default=str,
    ).encode("utf-8")

    # 2. Tarball arquivos físicos (opcional)
    tar_bytes = None
    if include_files:
        # Run in executor pra não bloquear loop (compressão pesada)
        import asyncio
        loop = asyncio.get_event_loop()
        tar_bytes = await loop.run_in_executor(
            None, _build_files_tarball, include_optional_files,
        )

    # 3. README.txt com instruções de restore
    readme = f"""SmartProv Backup Local
=========================
Empresa: {cid}
Gerado em: {started.strftime("%d/%m/%Y %H:%M:%S UTC")}
Secrets mascarados: {"NÃO (sensível!)" if include_secrets else "Sim (seguro p/ compartilhar)"}

CONTEÚDO
--------
- snapshot.json  → MongoDB completo (82 coleções, configs, dados operacionais)
- files.tar.gz   → Arquivos físicos (fotos, holerites, imagens WhatsApp)
                   {"INCLUSO" if tar_bytes else "NÃO INCLUSO (include_files=false)"}

COMO RESTAURAR (servidor novo)
-------------------------------
1. Acesse o SmartProv → Inteligência → Secretária Ligo → Backup Drive
2. Card "Provisionamento 1-clique":
   - Selecione o snapshot.json
   - (Opcional) Anexe o files.tar.gz
   - Modo: "Replace" para servidor vazio, "Merge" para somar
3. Confirme. Em segundos toda configuração + arquivos são restaurados.
4. Reinicie o backend (sudo supervisorctl restart backend).
5. (Opcional) Reconecte o Google Drive nesta instância.

SUPORTE
-------
Em caso de dúvidas, consulte a equipe de TI ou a documentação interna.
"""

    # 4. Empacota tudo num ZIP
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("snapshot.json", snapshot_bytes)
        if tar_bytes:
            zf.writestr("files.tar.gz", tar_bytes)
        zf.writestr("README.txt", readme.encode("utf-8"))
    zip_buf.seek(0)
    total_size = zip_buf.getbuffer().nbytes

    ts = started.strftime("%Y%m%d-%H%M%S")
    filename = f"smartprov-backup-{cid}-{ts}.zip"

    # Loga no histórico (mesmo schema dos backups remotos, mas com triggered_by=local)
    try:
        await db.drive_backups.insert_one({
            "id": f"bkp-local-{__import__('uuid').uuid4().hex[:10]}",
            "company_id": cid,
            "file_name": filename,
            "size_bytes": total_size,
            "include_secrets": include_secrets,
            "triggered_by": "local_download",
            "status": "ok",
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "snapshot_bytes": len(snapshot_bytes),
            "tarball_bytes": len(tar_bytes) if tar_bytes else 0,
            "actor": user.get("email"),
        })
    except Exception:
        pass  # log opcional, não bloqueia o download

    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Snapshot-Bytes": str(len(snapshot_bytes)),
            "X-Tarball-Bytes": str(len(tar_bytes) if tar_bytes else 0),
            "X-Total-Bytes": str(total_size),
        },
    )


class BackupIn(BaseModel):
    include_secrets: bool = False


@router.post("/drive/backup")
async def drive_backup(payload: BackupIn = BackupIn(),
                         user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or "co-demo"
    if not await is_connected(cid):
        raise HTTPException(400, "Conecte ao Google Drive primeiro.")
    # Check token health BEFORE attempting backup
    info = await get_connection_info(cid)
    if info.get("needs_reconnect"):
        raise HTTPException(
            401,
            "Token do Google Drive expirou ou foi revogado. "
            "Clique em 'Reconectar Google Drive' antes de fazer backup.",
        )
    try:
        return await run_backup(cid, include_secrets=payload.include_secrets,
                                  triggered_by="manual")
    except RuntimeError as e:
        msg = str(e)
        if "invalid_grant" in msg or "revoked" in msg.lower() or "expired" in msg.lower():
            raise HTTPException(401,
                "Token revogado. Clique em 'Reconectar Google Drive'.")
        raise HTTPException(400, msg)
    except Exception as e:
        msg = str(e)
        logger.exception("[drive] backup failed: %s", e)
        if "invalid_grant" in msg:
            raise HTTPException(401,
                "Token revogado. Clique em 'Reconectar Google Drive'.")
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


# ============================================================
# Provisionamento 1-clique — restore a partir de arquivo local
# ============================================================
@router.post("/drive/restore-upload")
async def drive_restore_upload(
    file: UploadFile = File(...),
    files_tarball: Optional[UploadFile] = File(None),
    mode: str = Form("merge"),
    user: dict = Depends(require_role("gestor")),
):
    """Restaura backup a partir de UPLOAD do navegador (não precisa Drive).

    Use-case principal: bootstrap de servidor novo.
    1. Usuário baixa o JSON de backup do Drive antigo (ou tem em mãos)
    2. (Opcional) baixa o `.files.tar.gz` correspondente
    3. Conecta no servidor novo, vai em Backup → Provisionamento
    4. Sobe o arquivo + (opcional) o tarball + escolhe modo
    5. Em segundos o servidor novo está com toda config + imagens/PDFs
    """
    cid = user.get("company_id") or "co-demo"
    if mode not in ("merge", "replace"):
        raise HTTPException(400, "mode deve ser merge ou replace")
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(400, "Arquivo deve ser .json")
    raw = await file.read()
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(413, "Arquivo muito grande (limite 50MB)")
    try:
        result = await restore_backup_from_bytes(
            cid, raw, mode=mode, source=f"upload:{file.filename}",
        )
        result["filename"] = file.filename
        result["size_bytes"] = len(raw)
        # Restaurar tarball também se foi enviado
        if files_tarball and files_tarball.filename:
            from services.drive_backup import _extract_files_tarball
            if not files_tarball.filename.lower().endswith((".tar.gz", ".tgz")):
                raise HTTPException(400, "Tarball deve ser .tar.gz")
            tar_raw = await files_tarball.read()
            if len(tar_raw) > 200 * 1024 * 1024:
                raise HTTPException(413, "Tarball muito grande (limite 200MB)")
            try:
                files_res = await _extract_files_tarball(tar_raw)
            except Exception as e:
                raise HTTPException(
                    400, f"Tarball inválido (não é um .tar.gz válido): {e}",
                )
            result["files_extracted"] = files_res
            result["files_tarball_filename"] = files_tarball.filename
            result["files_tarball_size_bytes"] = len(tar_raw)
        return result
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("[drive] restore-upload failed: %s", e)
        raise HTTPException(500, f"Falha ao restaurar: {e}")
