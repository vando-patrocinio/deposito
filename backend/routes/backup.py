"""iter205 — Endpoints de backup do MongoDB para super-admin.

Permite gerar backups on-demand e baixar a partir da VPS do cliente.
Importante para LGPD/compliance: só super_admin acessa.

Endpoints:
  - POST /api/admin/backup/create  → roda mongodump + tar.gz; devolve filename + size
  - GET  /api/admin/backup/list    → lista backups disponíveis em /app/backups
  - GET  /api/admin/backup/download/{filename} → stream do .tar.gz
  - DELETE /api/admin/backup/{filename} → apaga um backup (limpeza)
"""
from __future__ import annotations


from services.exception_sanitizer import safe_detail  # SECURITY_LOCK ART.13
NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import io
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core import get_current_user, is_super_admin

logger = logging.getLogger("ponto.backup")
router = APIRouter(prefix="/api/admin/backup", tags=["admin-backup"])

BACKUP_DIR = Path("/app/backups")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# Limita o nome de arquivo para evitar path traversal
SAFE_FILENAME = re.compile(r"^mongo-dump-\d{8}-\d{6}\.tar\.gz$")


def _require_super_admin(user: Dict[str, Any]) -> None:
    if not is_super_admin(user):
        raise HTTPException(403, "Apenas super-admin pode acessar backups.")


def _list_backups() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not BACKUP_DIR.exists():
        return items
    for p in sorted(BACKUP_DIR.glob("mongo-dump-*.tar.gz"), reverse=True):
        try:
            st = p.stat()
            items.append({
                "filename": p.name,
                "size_bytes": st.st_size,
                "size_human": f"{st.st_size / (1024*1024):.1f} MB",
                "created_at": datetime.fromtimestamp(
                    st.st_mtime, tz=timezone.utc).isoformat(),
            })
        except OSError:
            continue
    return items


@router.get("/list")
async def list_backups(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Lista os backups disponíveis no disco do pod."""
    _require_super_admin(user)
    items = _list_backups()
    total_bytes = sum(i["size_bytes"] for i in items)
    return {
        "backups": items,
        "count": len(items),
        "total_size_bytes": total_bytes,
        "total_size_human": f"{total_bytes / (1024*1024):.1f} MB",
        "dir": str(BACKUP_DIR),
    }


@router.post("/create")
async def create_backup(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Roda mongodump + tar.gz e devolve o nome do arquivo gerado."""
    import asyncio
    _require_super_admin(user)
    try:
        info = await asyncio.to_thread(_run_mongodump_sync)
    except RuntimeError as e:
        raise HTTPException(503, safe_detail(503, e))
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "mongodump excedeu o tempo limite (15min).")
    except Exception as e:
        logger.exception("[backup] erro inesperado")
        raise HTTPException(500, f"Erro: {e!s}")
    size = info["size_bytes"]
    logger.info("[backup] manual dump ok %s (%.1f MB) by %s",
                info["filename"], size / (1024 * 1024), user.get("email"))
    return {
        "ok": True,
        "filename": info["filename"],
        "size_bytes": size,
        "size_human": f"{size / (1024*1024):.1f} MB",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "download_url": f"/api/admin/backup/download/{info['filename']}",
    }


@router.get("/download/{filename}")
async def download_backup(filename: str,
                          user: dict = Depends(get_current_user)) -> FileResponse:
    """Stream do .tar.gz para download."""
    _require_super_admin(user)
    if not SAFE_FILENAME.match(filename):
        raise HTTPException(400, "Nome de arquivo inválido.")
    target = BACKUP_DIR / filename
    if not target.exists():
        raise HTTPException(404, "Backup não encontrado.")
    return FileResponse(
        path=str(target),
        media_type="application/gzip",
        filename=filename,
    )


@router.delete("/{filename}")
async def delete_backup(filename: str,
                        user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Apaga um backup (limpeza de disco)."""
    _require_super_admin(user)
    if not SAFE_FILENAME.match(filename):
        raise HTTPException(400, "Nome de arquivo inválido.")
    target = BACKUP_DIR / filename
    if not target.exists():
        raise HTTPException(404, "Backup não encontrado.")
    target.unlink()
    logger.info("[backup] deleted %s by %s", filename, user.get("email"))
    return {"ok": True, "deleted": filename}


@router.get("/drive-status")
async def drive_status(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Mostra se o Google Drive está conectado p/ upload dos backups."""
    _require_super_admin(user)
    from core import DEMO_COMPANY_ID
    from services.drive_backup import is_connected, get_connection_info
    cid = user.get("company_id") or DEMO_COMPANY_ID
    connected = await is_connected(cid)
    if not connected:
        return {"connected": False, "company_id": cid}
    info = await get_connection_info(cid)
    return {"connected": True, "company_id": cid, **info}


@router.post("/upload-drive/{filename}")
async def upload_to_drive_now(filename: str,
                               user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Sobe um backup específico já no disco para o Google Drive."""
    _require_super_admin(user)
    if not SAFE_FILENAME.match(filename):
        raise HTTPException(400, "Nome de arquivo inválido.")
    target = BACKUP_DIR / filename
    if not target.exists():
        raise HTTPException(404, "Backup não encontrado.")
    try:
        await _upload_to_drive(filename)
    except RuntimeError as e:
        # Drive não conectado
        raise HTTPException(503, safe_detail(503, e))
    except Exception as e:
        logger.exception("[backup] upload-drive falhou")
        raise HTTPException(500, f"Falha no upload: {e!s}")
    return {"ok": True, "uploaded": filename}


# ---------------------------------------------------------------------------
# Restore (mongorestore a partir de um .tar.gz)
# ---------------------------------------------------------------------------
@router.post("/restore")
async def restore_backup(
    file: UploadFile = File(...),
    drop_existing: str = Form("false"),
    confirm: str = Form(""),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Restaura o MongoDB a partir de um .tar.gz gerado por `/create`.

    OPERAÇÃO DESTRUTIVA. Requer:
      - super-admin
      - campo `confirm` = "RESTORE" (digitado pelo usuário)
      - `drop_existing="true"` para sobrescrever coleções existentes
        (sem isso só ADICIONA documentos novos; ignora os com _id existente)

    Fluxo (nativo Python):
      1. Lê o upload em memória / tempfile
      2. Extrai tar.gz via `tarfile` (sem depender de binário tar)
      3. Para cada `<collection>.bson` dentro:
         - decode_all → lista de docs
         - se drop_existing: drop_collection
         - insert_many(ordered=False) → ignora duplicates se não houver --drop
    """
    import asyncio
    import tarfile
    import tempfile

    import bson

    _require_super_admin(user)
    if confirm != "RESTORE":
        raise HTTPException(400,
            "Você precisa digitar 'RESTORE' no campo 'confirm' "
            "para validar a operação.")
    drop_flag = (drop_existing or "").strip().lower() in ("true", "1", "yes")

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise HTTPException(503, "MONGO_URL/DB_NAME não configurados.")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Arquivo vazio.")
    if len(raw) > 2_000_000_000:  # 2 GB hard cap
        raise HTTPException(413, "Arquivo > 2 GB — restaure manualmente.")

    op_id = f"_restore_{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    # Artefato transitório: /tmp (o disco da app é volátil e não é storage)
    work_dir = Path(tempfile.mkdtemp(prefix=f"{op_id}_work_"))
    extract_dir = Path(tempfile.mkdtemp(prefix=op_id, dir=str(work_dir)))
    try:
        logger.warning("[restore] iniciando %s drop=%s by=%s file=%s size=%dMB",
                       op_id, drop_flag, user.get("email"), file.filename,
                       len(raw) // (1024 * 1024))

        # 1) Extrai tar.gz com tarfile (nativo, anti-traversal), em memória
        try:
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
                # Anti-traversal: garante que membros não escapam de extract_dir
                for m in tar.getmembers():
                    if m.name.startswith("/") or ".." in Path(m.name).parts:
                        raise HTTPException(400, safe_detail(400, ValueError("tar membro inválido"), "Tar"))
                # SECURITY: filter="data" (Python 3.12+) rejeita symlinks/hardlinks/specials.
                # A pré-validação acima já cobre path traversal.
                try:
                    tar.extractall(path=str(extract_dir), filter="data")  # nosec B202
                except TypeError:
                    # Python <3.12: fallback usando getmembers já validados
                    tar.extractall(path=str(extract_dir))  # nosec B202
        except tarfile.TarError as e:
            raise HTTPException(400, f"Tar inválido: {e!s}")

        # 2) Encontra os arquivos .bson dentro de mongo-dump-*/<db_name>/
        bson_files = list(extract_dir.rglob("*.bson"))
        if not bson_files:
            raise HTTPException(400,
                "Nenhum arquivo .bson encontrado no dump.")
        # Detecta nome do DB no dump (parent dos .bson)
        dump_db_name = bson_files[0].parent.name

        # 3) Restore via Python: pra cada coleção, decode + insert_many
        result = await asyncio.to_thread(_restore_bson_files_sync,
                                          bson_files, mongo_url, db_name, drop_flag)

        logger.warning("[restore] CONCLUÍDO %s drop=%s by=%s · colls=%d docs=%d",
                       op_id, drop_flag, user.get("email"),
                       result["collections"], result["docs_total"])
        return {
            "ok": True,
            "operation_id": op_id,
            "drop_used": drop_flag,
            "source_db_in_dump": dump_db_name,
            "target_db": db_name,
            "collections_restored": result["collections"],
            "docs_total": result["docs_total"],
            "warnings": result["warnings"][:5],  # cap
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[restore] erro inesperado")
        raise HTTPException(500, f"Erro: {e!s}")
    finally:
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except OSError:
            pass


def _restore_bson_files_sync(bson_files: List[Path],
                              mongo_url: str, db_name: str,
                              drop: bool) -> Dict[str, Any]:
    """Lê cada .bson e popula a coleção correspondente no DB target.

    Retorna {collections, docs_total, warnings}.
    """
    import bson
    from pymongo import MongoClient
    from pymongo.errors import BulkWriteError

    warnings: List[str] = []
    docs_total = 0
    colls = 0
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=10000)
    try:
        target_db = client[db_name]
        for path in bson_files:
            coll_name = path.stem
            if coll_name.endswith(".metadata"):
                continue  # ignora metadata json (não BSON real)
            try:
                data = path.read_bytes()
                if not data:
                    continue
                docs = bson.decode_all(data)
                if not docs:
                    continue
                if drop:
                    target_db[coll_name].drop()
                # iter205h — insert em batches de 500 p/ evitar BSON 16MB limit
                # ordered=False → continua mesmo com duplicate keys (modo idempotente)
                BATCH = 500
                for i in range(0, len(docs), BATCH):
                    batch = docs[i:i + BATCH]
                    try:
                        target_db[coll_name].insert_many(batch, ordered=False)
                    except BulkWriteError as bwe:
                        write_errors = bwe.details.get("writeErrors", [])
                        dups = sum(1 for e in write_errors
                                   if e.get("code") == 11000)
                        others = len(write_errors) - dups
                        if others:
                            warnings.append(
                                f"{coll_name}[{i}:{i+len(batch)}]: "
                                f"{others} erros não-duplicate")
                colls += 1
                docs_total += len(docs)
            except Exception as e:
                warnings.append(f"{coll_name}: {e!s}")
    finally:
        client.close()
    return {"collections": colls, "docs_total": docs_total,
            "warnings": warnings}


# ---------------------------------------------------------------------------
# Daily cron job (rotação 7 dias)
# ---------------------------------------------------------------------------
KEEP_LAST_N = 7


def _run_mongodump_sync() -> Dict[str, Any]:
    """Versão síncrona reutilizada pelo cron e por testes.

    Suporta dois modos:
    - **Nativo (pymongo + bson + tarfile)**: funciona em qualquer pod, sem
      depender de binários `mongodump`/`tar`. Usado por padrão.
    - **Binários do sistema**: usado só se forçado via env `BACKUP_USE_BINARIES=1`.
    """
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise RuntimeError("MONGO_URL/DB_NAME não configurados.")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive = BACKUP_DIR / f"mongo-dump-{ts}.tar.gz"

    if os.environ.get("BACKUP_USE_BINARIES") == "1" and shutil.which("mongodump"):
        # Modo legado (mantido p/ retrocompatibilidade local)
        return _run_mongodump_via_binaries(ts, archive, mongo_url, db_name)

    # Modo nativo: usa pymongo (sync) + bson + tarfile
    _run_mongodump_native(ts, archive, mongo_url, db_name)
    return {"filename": archive.name, "size_bytes": archive.stat().st_size}


def _run_mongodump_native(ts: str, archive: Path,
                          mongo_url: str, db_name: str) -> None:
    """Dump nativo Python: enumera coleções, serializa em BSON, empacota em tar.gz.

    Estrutura interna idêntica ao mongodump:
      mongo-dump-<ts>/<db_name>/<collection>.bson
      mongo-dump-<ts>/<db_name>/<collection>.metadata.json
    """
    import bson
    import json
    import tarfile
    from pymongo import MongoClient

    client = MongoClient(mongo_url, serverSelectionTimeoutMS=10000)
    try:
        db = client[db_name]
        coll_names = sorted(db.list_collection_names())
        logger.info("[backup-native] %s coleções a dump", len(coll_names))

        # Cria archive direto em streaming
        with tarfile.open(archive, "w:gz") as tar:
            for coll_name in coll_names:
                bson_buf = bytearray()
                count = 0
                # Cursor paginado para não estourar memória em coleções grandes
                cursor = db[coll_name].find({}, no_cursor_timeout=False).batch_size(1000)
                try:
                    for doc in cursor:
                        bson_buf.extend(bson.encode(doc))
                        count += 1
                finally:
                    cursor.close()

                # Grava arquivo BSON no tar
                info = tarfile.TarInfo(
                    name=f"mongo-dump-{ts}/{db_name}/{coll_name}.bson")
                info.size = len(bson_buf)
                info.mtime = int(datetime.now(timezone.utc).timestamp())
                tar.addfile(info, fileobj=_bytes_reader(bytes(bson_buf)))

                # metadata.json (estrutura compatível com mongorestore se algum dia
                # voltar a usar binário)
                meta = json.dumps({
                    "options": {},
                    "indexes": [],
                    "uuid": "",
                    "collectionName": coll_name,
                    "type": "collection",
                }).encode()
                info_m = tarfile.TarInfo(
                    name=f"mongo-dump-{ts}/{db_name}/{coll_name}.metadata.json")
                info_m.size = len(meta)
                info_m.mtime = info.mtime
                tar.addfile(info_m, fileobj=_bytes_reader(meta))
        logger.info("[backup-native] %s arquivo %.1f MB",
                    archive.name, archive.stat().st_size / (1024 * 1024))
    finally:
        client.close()


def _bytes_reader(data: bytes):
    """tarfile.addfile precisa de um file-like obj com .read()."""
    import io
    return io.BytesIO(data)


def _run_mongodump_via_binaries(ts: str, archive: Path,
                                 mongo_url: str, db_name: str) -> Dict[str, Any]:
    """Modo legado (binários). Mantido para retrocompatibilidade."""
    dump_dir = BACKUP_DIR / f"mongo-dump-{ts}"
    proc = subprocess.run(
        ["mongodump", f"--uri={mongo_url}", f"--db={db_name}",
         f"--out={dump_dir}", "--quiet"],
        capture_output=True, text=True, timeout=900,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"mongodump rc={proc.returncode}: {proc.stderr[:300]}")
    proc2 = subprocess.run(
        ["tar", "czf", str(archive), "-C", str(BACKUP_DIR),
         f"mongo-dump-{ts}"],
        capture_output=True, text=True, timeout=600,
    )
    if proc2.returncode != 0:
        raise RuntimeError(f"tar rc={proc2.returncode}: {proc2.stderr[:300]}")
    shutil.rmtree(dump_dir, ignore_errors=True)
    return {"filename": archive.name, "size_bytes": archive.stat().st_size}


def _rotate_backups(keep: int = KEEP_LAST_N) -> List[str]:
    """Mantém apenas os `keep` backups mais recentes; apaga o resto."""
    items = sorted(BACKUP_DIR.glob("mongo-dump-*.tar.gz"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    removed: List[str] = []
    for p in items[keep:]:
        try:
            p.unlink()
            removed.append(p.name)
        except OSError as e:
            logger.warning("[backup] rotate fail %s: %s", p.name, e)
    return removed


async def daily_backup_job() -> None:
    """Cron diário 03:00 UTC — gera backup, rotaciona local e (opcional) sobe pro Drive.

    Upload pro Drive só roda se o Google Drive estiver conectado na empresa
    DEMO_COMPANY_ID. Se não estiver, apenas faz log e segue (não falha).
    """
    import asyncio
    try:
        info = await asyncio.to_thread(_run_mongodump_sync)
        removed = await asyncio.to_thread(_rotate_backups)
        logger.info("[backup-cron] %s (%.1f MB) · rotated_local=%d %s",
                    info["filename"], info["size_bytes"] / (1024 * 1024),
                    len(removed), removed)
    except Exception:
        logger.exception("[backup-cron] mongodump falhou")
        return

    # Upload pro Google Drive (best-effort, não bloqueia se falhar)
    try:
        await _upload_to_drive(info["filename"])
    except Exception:
        logger.exception("[backup-cron] upload Drive falhou (ignorado)")


async def _upload_to_drive(filename: str) -> None:
    """Sobe o arquivo .tar.gz para o Google Drive da empresa default.

    Mantém apenas os últimos KEEP_LAST_N no Drive também.
    Se Drive não está conectado ou o token foi revogado, marca a empresa
    como `needs_reconnect` e apenas faz log (não falha).
    """
    from core import DEMO_COMPANY_ID
    from services.drive_backup import (
        is_connected, upload_file_to_drive,
        _is_invalid_grant, _mark_token_revoked,
    )
    cid = DEMO_COMPANY_ID
    if not await is_connected(cid):
        logger.info("[backup-cron] Drive não conectado p/ %s — skip upload", cid)
        return
    path = BACKUP_DIR / filename
    if not path.exists():
        logger.warning("[backup-cron] arquivo %s sumiu antes do upload", filename)
        return
    content = path.read_bytes()
    try:
        result = await upload_file_to_drive(
            company_id=cid,
            content=content,
            file_name=filename,
            mime_type="application/gzip",
            subfolder="MongoDB-Dumps",
            description=f"Backup completo do MongoDB · {len(content) / (1024*1024):.1f} MB",
        )
    except Exception as e:
        # Token expirou/revogado — marca p/ usuário reconectar e propaga
        if _is_invalid_grant(e):
            await _mark_token_revoked(cid, str(e))
            logger.warning("[backup-cron] token Drive revogado para %s; "
                           "usuário precisa reconectar.", cid)
        raise
    logger.info("[backup-cron] Drive upload ok file_id=%s url=%s",
                result.get("file_id"), result.get("file_url"))


# ---------------------------------------------------------------------------
# Migrate from remote (iter205f) — pega dump direto de OUTRO ambiente Emergent
# ---------------------------------------------------------------------------
class MigratePayload(BaseModel):
    source_url: str = Field(..., description="https://outro-app.emergent.host")
    source_token: str = Field(..., description="JWT do super-admin no ambiente origem")
    drop_existing: bool = Field(False, description="Sobrescrever coleções existentes")


ALLOWED_REMOTE_DOMAINS = (
    ".emergent.host",
    ".emergentagent.com",
    ".cluster-7.deploy.emergentcf.cloud",
)


def _is_safe_remote(url: str) -> bool:
    """Restringe URL alvo aos domínios oficiais da Emergent (anti-SSRF)."""
    from urllib.parse import urlparse
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("https", "http"):
        return False
    host = (p.hostname or "").lower()
    return any(host.endswith(d) for d in ALLOWED_REMOTE_DOMAINS)


@router.post("/migrate-from-remote")
async def migrate_from_remote(
    payload: MigratePayload,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Migra dados de OUTRO ambiente Emergent → este.

    Fluxo:
      1. Chama `POST {source_url}/api/admin/backup/create` com `source_token`
      2. Baixa `{source_url}/api/admin/backup/download/{filename}` (stream)
      3. Salva em /app/backups/_migrate_*.tar.gz
      4. Restaura via mongorestore (mesma lógica do /restore)

    OPERAÇÃO DESTRUTIVA se drop_existing=true.
    """
    import asyncio
    import tempfile

    import httpx

    _require_super_admin(user)

    source = payload.source_url.rstrip("/")
    if not _is_safe_remote(source):
        raise HTTPException(400,
            "URL não permitida. Use só domínios .emergent.host, "
            ".emergentagent.com ou .cluster-7.deploy.emergentcf.cloud.")
    if not payload.source_token or len(payload.source_token) < 20:
        raise HTTPException(400, "Token de origem inválido.")
    db_name = os.environ.get("DB_NAME")
    if not os.environ.get("MONGO_URL") or not db_name:
        raise HTTPException(503, "MONGO_URL/DB_NAME não configurados.")

    op_id = f"_migrate_{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    headers = {"Authorization": f"Bearer {payload.source_token}"}

    logger.warning("[migrate] iniciando %s source=%s drop=%s by=%s",
                   op_id, source, payload.drop_existing, user.get("email"))

    # 1) Pede o create no source (gera dump remoto)
    try:
        async with httpx.AsyncClient(timeout=900.0) as cx:
            r = await cx.post(f"{source}/api/admin/backup/create",
                              headers=headers)
            if r.status_code == 401:
                raise HTTPException(401,
                    "Token de origem inválido ou expirado.")
            if r.status_code == 403:
                raise HTTPException(403,
                    "Token de origem não é super-admin.")
            if r.status_code != 200:
                raise HTTPException(502,
                    f"Source recusou /create: HTTP {r.status_code} "
                    f"{r.text[:200]}")
            create_data = r.json()
            remote_filename = create_data.get("filename")
            if not remote_filename:
                raise HTTPException(502,
                    "Source não devolveu filename.")
            logger.info("[migrate] %s dump remoto criado: %s (%.1f MB)",
                        op_id, remote_filename,
                        create_data.get("size_bytes", 0) / (1024 * 1024))

            # 2) Baixa o tar.gz (stream)
            upload_path = BACKUP_DIR / f"{op_id}.tar.gz"
            async with cx.stream("GET",
                f"{source}/api/admin/backup/download/{remote_filename}",
                headers=headers) as resp:
                if resp.status_code != 200:
                    raise HTTPException(502,
                        f"Source recusou /download: HTTP {resp.status_code}")
                total = 0
                with upload_path.open("wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=1024*1024):
                        f.write(chunk)
                        total += len(chunk)
                        if total > 2_000_000_000:
                            f.close()
                            upload_path.unlink(missing_ok=True)
                            raise HTTPException(413,
                                "Dump remoto > 2 GB — abortando.")
            logger.info("[migrate] %s download ok %.1f MB",
                        op_id, total / (1024 * 1024))
    except HTTPException:
        raise
    except httpx.RequestError as e:
        raise HTTPException(502, f"Erro de rede: {e!s}")
    except Exception as e:
        logger.exception("[migrate] download falhou")
        raise HTTPException(500, f"Erro: {e!s}")

    # 3) Restore local nativo (sem mongorestore/tar binários)
    import tarfile

    extract_dir = Path(tempfile.mkdtemp(prefix=op_id, dir=str(BACKUP_DIR)))
    try:
        try:
            with tarfile.open(upload_path, "r:gz") as tar:
                for m in tar.getmembers():
                    if m.name.startswith("/") or ".." in Path(m.name).parts:
                        raise HTTPException(400, safe_detail(400, ValueError("tar membro inválido"), "Tar"))
                # SECURITY: filter="data" (Python 3.12+) rejeita symlinks/hardlinks/specials.
                try:
                    tar.extractall(path=str(extract_dir), filter="data")  # nosec B202
                except TypeError:
                    tar.extractall(path=str(extract_dir))  # nosec B202
        except tarfile.TarError as e:
            raise HTTPException(500, f"Tar inválido: {e!s}")

        bson_files = list(extract_dir.rglob("*.bson"))
        if not bson_files:
            raise HTTPException(500, "Dump remoto sem coleções (.bson).")
        source_db = bson_files[0].parent.name

        result = await asyncio.to_thread(_restore_bson_files_sync,
                                          bson_files, os.environ["MONGO_URL"],
                                          db_name, payload.drop_existing)

        logger.warning("[migrate] CONCLUÍDO %s source=%s drop=%s · colls=%d docs=%d",
                       op_id, source, payload.drop_existing,
                       result["collections"], result["docs_total"])
        return {
            "ok": True,
            "operation_id": op_id,
            "source_url": source,
            "source_db_in_dump": source_db,
            "target_db": db_name,
            "drop_used": payload.drop_existing,
            "remote_filename": remote_filename,
            "downloaded_bytes": total,
            "downloaded_human": f"{total / (1024*1024):.1f} MB",
            "collections_restored": result["collections"],
            "docs_total": result["docs_total"],
            "warnings": result["warnings"][:5],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[migrate] restore falhou")
        raise HTTPException(500, f"Erro: {e!s}")
    finally:
        try:
            if upload_path.exists():
                upload_path.unlink()
            shutil.rmtree(extract_dir, ignore_errors=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# iter205g — Migração automática semanal (config persistente + cron)
# ---------------------------------------------------------------------------
SETTINGS_KEY = "mongo_migrate_config"


class MigrateConfig(BaseModel):
    enabled: bool = False
    source_url: str = ""
    source_token: str = ""
    drop_existing: bool = True


async def _load_migrate_config() -> Dict[str, Any]:
    """Lê config persistente da migração agendada."""
    from database import db
    doc = await db.backup_config.find_one({"_id": SETTINGS_KEY}) or {}
    doc.pop("_id", None)
    return doc


async def _save_migrate_config(cfg: Dict[str, Any]) -> None:
    from database import db
    await db.backup_config.update_one(
        {"_id": SETTINGS_KEY}, {"$set": cfg}, upsert=True)


@router.get("/migrate-config")
async def get_migrate_config(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Lê config da migração automática (token sai mascarado)."""
    _require_super_admin(user)
    cfg = await _load_migrate_config()
    tok = cfg.get("source_token", "") or ""
    return {
        "enabled": bool(cfg.get("enabled")),
        "source_url": cfg.get("source_url", ""),
        "source_token_preview": (tok[:10] + "..." + tok[-6:]) if tok else "",
        "has_token": bool(tok),
        "drop_existing": bool(cfg.get("drop_existing", True)),
        "schedule_cron": "domingo 04:00 UTC (01:00 BRT)",
        "last_run_at": cfg.get("last_run_at"),
        "last_status": cfg.get("last_status"),
        "last_error": cfg.get("last_error"),
        "last_op_id": cfg.get("last_op_id"),
    }


@router.post("/migrate-config")
async def set_migrate_config(payload: MigrateConfig,
                              user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Salva config da migração automática."""
    _require_super_admin(user)
    if payload.enabled:
        if not payload.source_url or not _is_safe_remote(payload.source_url):
            raise HTTPException(400, "URL inválida (use *.emergent.host etc.)")
        if not payload.source_token or len(payload.source_token) < 20:
            raise HTTPException(400, "Token inválido.")
    update: Dict[str, Any] = {
        "enabled": payload.enabled,
        "source_url": payload.source_url,
        "drop_existing": payload.drop_existing,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": user.get("email"),
    }
    # Só atualiza o token se vier preenchido (permite editar URL sem reenviar token)
    if payload.source_token:
        update["source_token"] = payload.source_token
    await _save_migrate_config(update)
    logger.info("[migrate-config] saved enabled=%s url=%s drop=%s by=%s",
                payload.enabled, payload.source_url,
                payload.drop_existing, user.get("email"))
    return {"ok": True, "enabled": payload.enabled}


async def weekly_migrate_job() -> None:
    """Cron domingo 04:00 UTC — migra PROD → este ambiente automaticamente.

    Só roda se `enabled=True` na config. Logs em [migrate-cron].
    """
    cfg = await _load_migrate_config()
    if not cfg.get("enabled"):
        logger.info("[migrate-cron] desabilitado — skip")
        return
    if not cfg.get("source_url") or not cfg.get("source_token"):
        logger.warning("[migrate-cron] config incompleta — skip")
        return

    payload = MigratePayload(
        source_url=cfg["source_url"],
        source_token=cfg["source_token"],
        drop_existing=bool(cfg.get("drop_existing", True)),
    )
    # Reaproveita migrate_from_remote criando um user "system"
    fake_user = {"is_super_admin": True, "role": "auditor",
                 "email": "cron@system", "company_id": "co-demo"}
    try:
        result = await migrate_from_remote(payload, fake_user)
        await _save_migrate_config({
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_status": "ok",
            "last_error": None,
            "last_op_id": result.get("operation_id"),
        })
        logger.warning("[migrate-cron] OK %s baixado=%s",
                       result.get("operation_id"),
                       result.get("downloaded_human"))
    except HTTPException as e:
        await _save_migrate_config({
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_status": "error",
            "last_error": f"HTTP {e.status_code}: {e.detail}",
        })
        logger.error("[migrate-cron] falhou: %s", e.detail)
    except Exception as e:
        await _save_migrate_config({
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_status": "error",
            "last_error": str(e),
        })
        logger.exception("[migrate-cron] erro inesperado")



# ─────────────── FASE A3 — Off-site backup AWS S3 ───────────────
#  Fallback do Google Drive (token OAuth expirado). Super-admin only.

@router.get("/s3/status")
async def s3_backup_status(user: Dict[str, Any] = Depends(get_current_user)):
    """Diagnóstico: mostra se S3 está configurado e o que falta."""
    _require_super_admin(user)
    from services import s3_backup
    return s3_backup.get_status()


@router.post("/s3/upload-latest")
async def s3_backup_upload_latest(
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Empacota o último mongodump e envia para S3. Idempotente."""
    _require_super_admin(user)
    from services import s3_backup
    return s3_backup.upload_latest_snapshot()


@router.post("/s3/daily")
async def s3_backup_daily(
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Roda o ciclo completo: snapshot local + upload S3 + purge."""
    _require_super_admin(user)
    from services import s3_backup
    return await s3_backup.daily_backup_job()


@router.get("/s3/list")
async def s3_backup_list(
    limit: int = 50,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Lista snapshots remotos no bucket."""
    _require_super_admin(user)
    from services import s3_backup
    return {"items": s3_backup.list_remote_backups(limit=limit)}
