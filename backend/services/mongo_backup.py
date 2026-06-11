"""mongo_backup.py — Snapshot binário do MongoDB via mongodump.

Resolve o gap crítico R2 (sem snapshot Mongo binário) listado em
RELEASE_LOCK.md item 7 e LOST_FEATURE_CHECK.md.

Operação:
  - Executa `mongodump --gzip --out <dir>` para arquivo local.
  - Retém últimos N backups (rotação simples por data).
  - Pode ser disparado manualmente (route admin) ou via scheduler.

Variáveis de ambiente respeitadas:
  - MONGO_URL (obrigatório)
  - DB_NAME (obrigatório)
  - BACKUP_DIR (default: /app/backups)
  - BACKUP_RETENTION_DAYS (default: 14)
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

import os
import logging
import shutil
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("mongo_backup")


def _now_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")


def _backup_dir() -> Path:
    return Path(os.environ.get("BACKUP_DIR", "/app/backups"))


def _retention_days() -> int:
    try:
        return int(os.environ.get("BACKUP_RETENTION_DAYS", "14"))
    except (TypeError, ValueError):
        return 14


def list_backups() -> List[Dict[str, Any]]:
    """Lista snapshots existentes no diretório."""
    root = _backup_dir()
    if not root.exists():
        return []
    out = []
    for item in sorted(root.iterdir(), reverse=True):
        if item.is_dir() and item.name.startswith("mongo-"):
            try:
                size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
            except OSError:
                size = 0
            out.append({
                "name": item.name,
                "path": str(item),
                "size_bytes": size,
                "size_mb": round(size / 1024 / 1024, 2),
                "created_at": datetime.fromtimestamp(
                    item.stat().st_mtime, tz=timezone.utc).isoformat(),
            })
    return out


def snapshot_now() -> Dict[str, Any]:
    """Executa mongodump imediato. Retorna metadados do snapshot."""
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        return {"ok": False, "error": "MONGO_URL ou DB_NAME ausente"}

    root = _backup_dir()
    root.mkdir(parents=True, exist_ok=True)
    tag = _now_tag()
    target = root / f"mongo-{db_name}-{tag}"
    target.mkdir(parents=True, exist_ok=True)

    cmd = ["mongodump",
           f"--uri={mongo_url}",
           f"--db={db_name}",
           "--gzip",
           f"--out={target}"]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600)
        ok = proc.returncode == 0
        stderr = (proc.stderr or "")[-2000:]
        if not ok:
            logger.error("[backup] mongodump fail: %s", stderr)
            shutil.rmtree(target, ignore_errors=True)
            return {"ok": False, "error": stderr, "tag": tag}
        # Tamanho final
        size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
        logger.info("[backup] snapshot ok %s (%d bytes)", target, size)
        # Rotação
        purged = purge_old()
        return {"ok": True, "tag": tag, "path": str(target),
                "size_bytes": size, "size_mb": round(size / 1024 / 1024, 2),
                "purged": purged,
                "generated_at": datetime.now(timezone.utc).isoformat()}
    except FileNotFoundError:
        return {"ok": False,
                "error": "mongodump não encontrado no PATH (instalar mongodb-database-tools)"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout (>600s)"}
    except Exception as e:
        logger.exception("[backup] erro inesperado")
        return {"ok": False, "error": repr(e)[:500]}


def purge_old() -> List[str]:
    """Remove snapshots mais antigos que BACKUP_RETENTION_DAYS."""
    root = _backup_dir()
    if not root.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=_retention_days())
    purged = []
    for item in root.iterdir():
        if item.is_dir() and item.name.startswith("mongo-"):
            mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                try:
                    shutil.rmtree(item)
                    purged.append(item.name)
                except OSError as e:
                    logger.warning("[backup] purge fail %s: %s", item, e)
    if purged:
        logger.info("[backup] purged %d snapshots", len(purged))
    return purged
