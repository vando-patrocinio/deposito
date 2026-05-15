"""Drive Backup Service — exporta dados do PontoIA para o Google Drive.

Coleções incluídas no snapshot (read-only):
  - settings, branding, plans, subscribers, collaborators, pracas
  - aihub_agents, aihub_integrations (com secrets MASCARADOS por padrão)
  - motor_ia_config (mascarado)
  - secretaria_config (mascarado)
  - whatsapp settings, tab_permissions
  - sla / churn / signature configs

NÃO incluímos (volume e privacidade):
  - tickets, lousa_logs, clock_records, wa_messages históricos
  - audit logs, motor_ia_usage

O foco é re-criar o sistema funcional do ZERO. Histórico operacional fica
no backup do MongoDB hospedado (responsabilidade do provedor de banco).
"""
from __future__ import annotations

import io
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest

from core import DEMO_COMPANY_ID, now_iso
from database import db

logger = logging.getLogger("drive_backup")

DRIVE_FOLDER_NAME = "PontoIA-Backups"

# Coleções que entram no snapshot. Tupla (collection, mascarar_secrets).
BACKUP_COLLECTIONS: List[tuple[str, bool]] = [
    ("settings", False),
    ("branding", False),
    ("plans", False),
    ("subscribers", False),
    ("collaborators", False),
    ("pracas", False),
    ("aihub_agents", False),
    ("aihub_integrations", True),
    ("aihub_settings", False),
    ("aihub_templates", False),
    ("motor_ia_config", True),
    ("secretaria_config", True),
    ("ai_agent_switches", False),
    ("smartolt_olts", True),  # url/token podem ser sensíveis
    ("users", True),
    ("companies", False),
    ("plan_adjustments_scheduled", False),
]

SECRET_FIELDS = {
    "openrouter_api_key", "openai_audio_key",
    "webhook_token", "key", "secret", "password_hash",
    "atlaz_token", "atlaz_api_key", "stripe_secret", "url_password",
    "client_secret", "api_key", "api_secret",
    "smartolt_token", "smartolt_api_key", "smartolt_password",
    "magnusbilling_key", "magnusbilling_secret",
}


# ============================================================
# Credentials management
# ============================================================
async def _get_credentials(company_id: str) -> Optional[Credentials]:
    """Carrega credenciais OAuth para a empresa. Faz auto-refresh."""
    doc = await db.drive_credentials.find_one({"company_id": company_id}, {"_id": 0})
    if not doc:
        return None
    creds = Credentials(
        token=doc.get("access_token"),
        refresh_token=doc.get("refresh_token"),
        token_uri=doc.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=doc.get("client_id") or os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=doc.get("client_secret") or os.environ.get("GOOGLE_CLIENT_SECRET"),
        scopes=doc.get("scopes") or ["https://www.googleapis.com/auth/drive.file"],
    )
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(GoogleRequest())
            await db.drive_credentials.update_one(
                {"company_id": company_id},
                {"$set": {
                    "access_token": creds.token,
                    "expiry": creds.expiry.isoformat() if creds.expiry else None,
                    "updated_at": now_iso(),
                }},
            )
        except Exception as e:
            logger.warning("[drive] refresh token failed for %s: %s", company_id, e)
            return None
    return creds


async def is_connected(company_id: str) -> bool:
    """True se a empresa já autorizou Drive."""
    doc = await db.drive_credentials.find_one(
        {"company_id": company_id}, {"_id": 0, "refresh_token": 1, "user_email": 1}
    )
    return bool(doc and doc.get("refresh_token"))


async def get_connection_info(company_id: str) -> Dict[str, Any]:
    doc = await db.drive_credentials.find_one(
        {"company_id": company_id},
        {"_id": 0, "user_email": 1, "connected_at": 1, "folder_id": 1, "folder_url": 1},
    )
    if not doc:
        return {"connected": False}
    return {
        "connected": True,
        "user_email": doc.get("user_email"),
        "connected_at": doc.get("connected_at"),
        "folder_id": doc.get("folder_id"),
        "folder_url": doc.get("folder_url"),
    }


async def disconnect(company_id: str) -> None:
    await db.drive_credentials.delete_one({"company_id": company_id})


# ============================================================
# Drive helpers
# ============================================================
def _build_service(creds: Credentials):
    """Cria o objeto google-api-client. Roda sync (a lib não tem versão async).

    Encapsulamos em loop.run_in_executor pra não bloquear o event loop."""
    return build("drive", "v3", credentials=creds, cache_discovery=False)


async def _ensure_root_folder(company_id: str, service) -> Dict[str, str]:
    """Garante que existe a pasta `PontoIA-Backups` na raiz do Drive da conta.

    Retorna {"id": ..., "url": ...}. Salva no doc da empresa para reuso.
    """
    cred_doc = await db.drive_credentials.find_one({"company_id": company_id}, {"_id": 0})
    if cred_doc and cred_doc.get("folder_id"):
        # Valida que ainda existe — se foi apagado, recria
        try:
            service.files().get(fileId=cred_doc["folder_id"], fields="id,name,trashed").execute()
            return {"id": cred_doc["folder_id"], "url": cred_doc.get("folder_url") or ""}
        except HttpError:
            pass  # cai pra criar de novo

    metadata = {
        "name": DRIVE_FOLDER_NAME,
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = service.files().create(body=metadata, fields="id, webViewLink").execute()
    folder_id = folder["id"]
    folder_url = folder.get("webViewLink", "")
    await db.drive_credentials.update_one(
        {"company_id": company_id},
        {"$set": {"folder_id": folder_id, "folder_url": folder_url}},
    )
    return {"id": folder_id, "url": folder_url}


def _mask(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Mascara campos sensíveis recursivamente."""
    if not isinstance(doc, dict):
        return doc
    out = {}
    for k, v in doc.items():
        if k in SECRET_FIELDS and isinstance(v, str) and v:
            out[k] = f"***REDACTED***(len={len(v)})"
        elif isinstance(v, dict):
            out[k] = _mask(v)
        elif isinstance(v, list):
            out[k] = [_mask(x) if isinstance(x, dict) else x for x in v]
        else:
            out[k] = v
    return out


async def _collect_snapshot(company_id: str, include_secrets: bool) -> Dict[str, Any]:
    """Lê as coleções listadas em BACKUP_COLLECTIONS e devolve dict serializável."""
    snapshot: Dict[str, Any] = {
        "_meta": {
            "company_id": company_id,
            "exported_at": now_iso(),
            "include_secrets": include_secrets,
            "version": "1.0",
        }
    }
    for coll_name, must_mask in BACKUP_COLLECTIONS:
        try:
            cur = db[coll_name].find({"company_id": company_id}, {"_id": 0})
            docs = await cur.to_list(10000)
            if must_mask and not include_secrets:
                docs = [_mask(d) for d in docs]
            snapshot[coll_name] = docs
        except Exception as e:
            logger.warning("[drive] collect %s failed: %s", coll_name, e)
            snapshot[coll_name] = []
    return snapshot


# ============================================================
# Backup
# ============================================================
async def run_backup(company_id: str, include_secrets: bool = False,
                       triggered_by: str = "manual") -> Dict[str, Any]:
    """Executa o backup: snapshot → upload JSON pro Drive."""
    cid = company_id or DEMO_COMPANY_ID
    started = datetime.now(timezone.utc)

    creds = await _get_credentials(cid)
    if not creds:
        raise RuntimeError("Google Drive não conectado para essa empresa.")

    import asyncio
    loop = asyncio.get_event_loop()
    service = await loop.run_in_executor(None, _build_service, creds)

    root = await _ensure_root_folder(cid, service)
    snapshot = await _collect_snapshot(cid, include_secrets)
    content = json.dumps(snapshot, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    size = len(content)

    file_name = f"pontoia-backup-{started.strftime('%Y%m%d-%H%M%S')}.json"
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype="application/json", resumable=False)
    file_metadata = {
        "name": file_name,
        "parents": [root["id"]],
        "description": f"PontoIA snapshot ({triggered_by}) - company={cid}",
    }

    try:
        result = await loop.run_in_executor(None,
            lambda: service.files().create(body=file_metadata, media_body=media,
                                              fields="id, webViewLink, size").execute()
        )
    except Exception as e:
        await _log_backup(cid, "failed", file_name, size, triggered_by, error=str(e)[:300])
        raise

    file_id = result.get("id")
    url = result.get("webViewLink")

    record = {
        "id": f"bkp-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "file_id": file_id,
        "file_name": file_name,
        "file_url": url,
        "size_bytes": size,
        "include_secrets": include_secrets,
        "triggered_by": triggered_by,
        "collections": [c[0] for c in BACKUP_COLLECTIONS],
        "status": "ok",
        "started_at": started.isoformat(),
        "finished_at": now_iso(),
        "elapsed_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
    }
    await db.drive_backups.insert_one(dict(record))

    # Limita histórico — manter apenas últimos 30 dias no Drive
    await _prune_old_files(cid, service, root["id"], keep_days=30)

    return {
        "ok": True,
        "file_id": file_id,
        "file_name": file_name,
        "file_url": url,
        "size_bytes": size,
        "elapsed_ms": record["elapsed_ms"],
    }


async def _log_backup(cid: str, status: str, name: str, size: int,
                       triggered_by: str, error: Optional[str] = None) -> None:
    try:
        await db.drive_backups.insert_one({
            "id": f"bkp-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "file_name": name,
            "size_bytes": size,
            "triggered_by": triggered_by,
            "status": status,
            "error": error,
            "started_at": now_iso(),
            "finished_at": now_iso(),
        })
    except Exception:
        pass


# ============================================================
# Generic file upload (Rede IA PDFs, fotos, relatórios)
# ============================================================
async def upload_file_to_drive(
    company_id: str,
    content: bytes,
    file_name: str,
    mime_type: str = "application/pdf",
    subfolder: str = "Rede-IA",
    description: str = "",
) -> Dict[str, Any]:
    """Upload arbitrário ao Drive em subpasta da PontoIA-Backups.

    Usado por:
      - Rede IA: PDF de CTOs aprovadas
      - Outros relatórios

    Retorna {file_id, file_url, size_bytes}. Levanta RuntimeError se Drive
    não estiver conectado.
    """
    cid = company_id or DEMO_COMPANY_ID
    creds = await _get_credentials(cid)
    if not creds:
        raise RuntimeError("Google Drive não conectado para essa empresa.")

    import asyncio
    loop = asyncio.get_event_loop()
    service = await loop.run_in_executor(None, _build_service, creds)

    root = await _ensure_root_folder(cid, service)

    # Garante subpasta dentro de PontoIA-Backups
    subfolder_id = await loop.run_in_executor(None,
        lambda: _ensure_subfolder(service, root["id"], subfolder))

    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=False)
    metadata = {
        "name": file_name,
        "parents": [subfolder_id],
        "description": description or f"Rede IA - {file_name}",
    }
    result = await loop.run_in_executor(None,
        lambda: service.files().create(body=metadata, media_body=media,
                                          fields="id, webViewLink, size").execute())
    return {
        "file_id": result.get("id"),
        "file_url": result.get("webViewLink"),
        "size_bytes": len(content),
        "subfolder": subfolder,
    }


def _ensure_subfolder(service, parent_id: str, name: str) -> str:
    """Cria (ou reusa) subpasta dentro da pasta-raiz do Drive."""
    q = (f"'{parent_id}' in parents and trashed=false "
         f"and mimeType='application/vnd.google-apps.folder' and name='{name}'")
    try:
        existing = service.files().list(q=q, fields="files(id,name)").execute()
        files = existing.get("files", [])
        if files:
            return files[0]["id"]
    except HttpError:
        pass
    folder = service.files().create(body={
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }, fields="id").execute()
    return folder["id"]


async def _prune_old_files(cid: str, service, folder_id: str, keep_days: int = 30) -> None:
    """Apaga backups > keep_days dias no Drive. Mantém últimos 7 sempre."""
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        q = f"'{folder_id}' in parents and trashed=false and mimeType='application/json'"
        result = await loop.run_in_executor(None,
            lambda: service.files().list(q=q, orderBy="createdTime desc",
                                            fields="files(id,name,createdTime)").execute()
        )
        files = result.get("files", [])
        # Manter os 7 mais novos sempre
        to_check = files[7:]
        cutoff = datetime.now(timezone.utc).timestamp() - keep_days * 86400
        for f in to_check:
            try:
                created = datetime.fromisoformat(f["createdTime"].replace("Z", "+00:00")).timestamp()
                if created < cutoff:
                    await loop.run_in_executor(None,
                        lambda fid=f["id"]: service.files().delete(fileId=fid).execute()
                    )
            except Exception:
                pass
    except Exception as e:
        logger.info("[drive] prune skip: %s", e)


# ============================================================
# Restore
# ============================================================
async def list_backups(company_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    """Histórico de backups da empresa (do banco)."""
    cur = db.drive_backups.find(
        {"company_id": company_id},
        {"_id": 0},
    ).sort("started_at", -1).limit(limit)
    return await cur.to_list(limit)


async def list_remote_files(company_id: str) -> List[Dict[str, Any]]:
    """Lista direto do Drive (caso queira restaurar arquivo que NÃO está mais no banco)."""
    creds = await _get_credentials(company_id)
    if not creds:
        raise RuntimeError("Google Drive não conectado.")
    import asyncio
    loop = asyncio.get_event_loop()
    service = await loop.run_in_executor(None, _build_service, creds)
    root = await _ensure_root_folder(company_id, service)
    q = f"'{root['id']}' in parents and trashed=false and mimeType='application/json'"
    result = await loop.run_in_executor(None,
        lambda: service.files().list(q=q, orderBy="createdTime desc",
                                        fields="files(id,name,createdTime,size,webViewLink)").execute()
    )
    return result.get("files", [])


async def download_backup(company_id: str, file_id: str) -> bytes:
    creds = await _get_credentials(company_id)
    if not creds:
        raise RuntimeError("Google Drive não conectado.")
    import asyncio
    loop = asyncio.get_event_loop()
    service = await loop.run_in_executor(None, _build_service, creds)

    def _do_download() -> bytes:
        request = service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()

    return await loop.run_in_executor(None, _do_download)


async def restore_backup(company_id: str, file_id: str,
                           collections: Optional[List[str]] = None,
                           mode: str = "merge") -> Dict[str, Any]:
    """Restaura snapshot do Drive.

    Args:
        collections: lista opcional de coleções específicas a restaurar
                     (default: todas presentes no snapshot).
        mode: "merge" (upsert por id) | "replace" (apaga doc da empresa e re-insere).

    Returns: {"restored": {coll: count}, "skipped": [...]}
    """
    raw = await download_backup(company_id, file_id)
    snapshot = json.loads(raw.decode("utf-8"))
    meta = snapshot.pop("_meta", {})

    if meta.get("company_id") and meta.get("company_id") != company_id:
        # Backup veio de outra empresa — só permite com flag explícita
        raise RuntimeError(
            f"Backup pertence a outra empresa ({meta.get('company_id')}). "
            "Não posso restaurar entre empresas diferentes."
        )

    collection_filter = set(collections) if collections else None
    restored: Dict[str, int] = {}
    skipped: List[str] = []
    secrets_redacted = bool(meta.get("include_secrets") is False)

    for coll_name, docs in snapshot.items():
        if collection_filter and coll_name not in collection_filter:
            skipped.append(coll_name)
            continue
        if not isinstance(docs, list) or not docs:
            continue
        # Modo replace: limpa antes
        if mode == "replace":
            await db[coll_name].delete_many({"company_id": company_id})
        # Upsert por id (se houver) ou bulk insert
        inserted = 0
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            # Não restaura campos REDACTED — preserva o atual no banco
            if secrets_redacted:
                doc = {k: v for k, v in doc.items()
                         if not (isinstance(v, str) and v.startswith("***REDACTED***"))}
            doc["company_id"] = company_id
            doc_id = doc.get("id")
            if doc_id:
                await db[coll_name].replace_one(
                    {"company_id": company_id, "id": doc_id}, doc, upsert=True
                )
            else:
                await db[coll_name].insert_one(doc)
            inserted += 1
        restored[coll_name] = inserted

    await db.drive_restore_log.insert_one({
        "id": f"rst-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "file_id": file_id,
        "mode": mode,
        "collections_restored": list(restored.keys()),
        "total_docs": sum(restored.values()),
        "secrets_redacted_in_source": secrets_redacted,
        "created_at": now_iso(),
    })
    return {"ok": True, "restored": restored, "skipped": skipped,
            "secrets_redacted_in_source": secrets_redacted}


# ============================================================
# Daily scheduler
# ============================================================
async def daily_backup_worker() -> None:
    """Worker async: roda diariamente entre 03:00-03:05 BRT (06:00-06:05 UTC).

    Para cada empresa com Drive conectado e backup habilitado, executa o backup.
    """
    import asyncio
    logger.info("[drive-scheduler] worker iniciado")
    last_run_date: Optional[str] = None
    while True:
        try:
            now = datetime.now(timezone.utc)
            # 06:00 UTC = 03:00 BRT
            if now.hour == 6 and now.minute < 5:
                today = now.strftime("%Y-%m-%d")
                if today != last_run_date:
                    await _run_all_companies()
                    last_run_date = today
        except Exception as e:
            logger.exception("[drive-scheduler] tick fail: %s", e)
        await asyncio.sleep(120)


async def _run_all_companies() -> None:
    cur = db.drive_credentials.find({}, {"_id": 0, "company_id": 1})
    async for doc in cur:
        cid = doc.get("company_id")
        if not cid:
            continue
        try:
            await run_backup(cid, include_secrets=False, triggered_by="scheduled")
            logger.info("[drive-scheduler] backup OK company=%s", cid)
        except Exception as e:
            logger.warning("[drive-scheduler] backup FAIL company=%s: %s", cid, e)
