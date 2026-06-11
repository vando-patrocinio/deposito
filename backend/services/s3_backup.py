"""s3_backup.py — Off-site backup para AWS S3 (Fase A3).

Fallback do Google Drive (bloqueado por OAuth). Empacota o último
snapshot mongodump em .tar.gz e faz upload para o bucket.

Variáveis de ambiente:
    - AWS_ACCESS_KEY_ID         (obrigatória)
    - AWS_SECRET_ACCESS_KEY     (obrigatória)
    - AWS_REGION                (default: us-east-1)
    - S3_BACKUP_BUCKET          (obrigatória)
    - S3_BACKUP_PREFIX          (default: smartprov/mongo-backups)
    - S3_BACKUP_RETENTION_DAYS  (default: 30)

Quando alguma var obrigatória está ausente, retorna
``{"ok": False, "configured": False, ...}`` para sinalizar
ao CTO que precisa configurar — não levanta exceção.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import os
import tarfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("s3_backup")


# ── Configuração ────────────────────────────────────────────────
def _cfg() -> Dict[str, Optional[str]]:
    return {
        "access_key": os.environ.get("AWS_ACCESS_KEY_ID"),
        "secret_key": os.environ.get("AWS_SECRET_ACCESS_KEY"),
        "region": os.environ.get("AWS_REGION") or "us-east-1",
        "bucket": os.environ.get("S3_BACKUP_BUCKET"),
        "prefix": (os.environ.get("S3_BACKUP_PREFIX")
                    or "smartprov/mongo-backups").strip("/"),
        "retention_days": int(
            os.environ.get("S3_BACKUP_RETENTION_DAYS") or 30),
    }


def is_configured() -> bool:
    c = _cfg()
    return all([c["access_key"], c["secret_key"], c["bucket"]])


def get_status() -> Dict[str, Any]:
    """Para o painel: mostra o que está faltando sem expor secret."""
    c = _cfg()
    missing = [k for k in ("access_key", "secret_key", "bucket")
               if not c[k]]
    return {
        "configured": is_configured(),
        "bucket": c["bucket"],
        "region": c["region"],
        "prefix": c["prefix"],
        "retention_days": c["retention_days"],
        "missing_env_vars": [
            {"access_key": "AWS_ACCESS_KEY_ID",
             "secret_key": "AWS_SECRET_ACCESS_KEY",
             "bucket": "S3_BACKUP_BUCKET"}[k] for k in missing
        ],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


# ── S3 client (lazy) ────────────────────────────────────────────
def _client():
    import boto3  # lazy import
    c = _cfg()
    return boto3.client(
        "s3",
        aws_access_key_id=c["access_key"],
        aws_secret_access_key=c["secret_key"],
        region_name=c["region"],
    )


# ── Empacota dump em tar.gz ─────────────────────────────────────
def _tarball_latest_dump() -> Optional[Path]:
    """Cria um .tar.gz do snapshot mongodump mais recente."""
    from services.mongo_backup import list_backups
    items = list_backups()
    if not items:
        return None
    latest_dir = Path(items[0]["path"])
    if not latest_dir.exists():
        return None
    tgz = latest_dir.parent / f"{latest_dir.name}.tar.gz"
    if tgz.exists() and tgz.stat().st_mtime >= latest_dir.stat().st_mtime:
        return tgz
    with tarfile.open(tgz, "w:gz") as t:
        t.add(latest_dir, arcname=latest_dir.name)
    return tgz


# ── Upload ──────────────────────────────────────────────────────
def upload_latest_snapshot() -> Dict[str, Any]:
    """Faz upload do último mongodump para o S3."""
    if not is_configured():
        return {"ok": False, "configured": False,
                "error": "S3 não configurado",
                "status": get_status()}

    tgz = _tarball_latest_dump()
    if not tgz:
        return {"ok": False, "configured": True,
                "error": "Nenhum snapshot mongodump local encontrado. "
                          "Rode services.mongo_backup.snapshot_now() antes."}

    c = _cfg()
    key = f"{c['prefix']}/{tgz.name}"
    try:
        size = tgz.stat().st_size
        _client().upload_file(str(tgz), c["bucket"], key,
                                ExtraArgs={"StorageClass": "STANDARD_IA"})
        logger.info("[s3_backup] uploaded %s (%d bytes) → s3://%s/%s",
                     tgz.name, size, c["bucket"], key)
        purged = purge_old_remote()
        return {"ok": True, "configured": True,
                "bucket": c["bucket"], "key": key,
                "size_bytes": size,
                "size_mb": round(size / 1024 / 1024, 2),
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "purged_remote": purged}
    except Exception as e:  # noqa: BLE001
        logger.exception("[s3_backup] upload fail")
        return {"ok": False, "configured": True, "error": repr(e)[:500]}


def list_remote_backups(limit: int = 50) -> List[Dict[str, Any]]:
    """Lista objetos no prefix do bucket. Vazio se não configurado."""
    if not is_configured():
        return []
    c = _cfg()
    try:
        resp = _client().list_objects_v2(
            Bucket=c["bucket"], Prefix=c["prefix"] + "/",
            MaxKeys=limit)
        items = []
        for obj in resp.get("Contents", []):
            items.append({
                "key": obj["Key"],
                "size_bytes": obj["Size"],
                "size_mb": round(obj["Size"] / 1024 / 1024, 2),
                "last_modified":
                    obj["LastModified"].astimezone(timezone.utc).isoformat(),
            })
        return sorted(items, key=lambda x: x["last_modified"], reverse=True)
    except Exception as e:  # noqa: BLE001
        logger.exception("[s3_backup] list fail")
        return [{"error": repr(e)[:200]}]


def purge_old_remote() -> List[str]:
    """Apaga objetos remotos mais antigos que retention_days."""
    if not is_configured():
        return []
    c = _cfg()
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=c["retention_days"])
    purged: List[str] = []
    try:
        resp = _client().list_objects_v2(
            Bucket=c["bucket"], Prefix=c["prefix"] + "/")
        to_delete = [
            {"Key": obj["Key"]} for obj in resp.get("Contents", [])
            if obj["LastModified"].astimezone(timezone.utc) < cutoff
        ]
        if to_delete:
            _client().delete_objects(
                Bucket=c["bucket"], Delete={"Objects": to_delete})
            purged = [o["Key"] for o in to_delete]
            logger.info("[s3_backup] purged %d remote objects",
                         len(purged))
    except Exception as e:  # noqa: BLE001
        logger.warning("[s3_backup] purge remote err: %r", e)
    return purged


# ── Job diário ──────────────────────────────────────────────────
async def daily_backup_job() -> Dict[str, Any]:
    """Job para o APScheduler. Snapshot local + upload S3 + purge."""
    from services.mongo_backup import snapshot_now
    snap = snapshot_now()
    if not snap.get("ok"):
        logger.warning("[s3_backup] daily skipped: snapshot fail: %s",
                        snap.get("error"))
        return {"ok": False, "stage": "local_snapshot", **snap}
    up = upload_latest_snapshot()
    return {"ok": up.get("ok"), "stage": "upload", "snapshot": snap,
              "upload": up}
