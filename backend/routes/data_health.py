"""Data Health — painel de saúde dos dados (backup, migrations, contagens).

Endpoint admin-only que mostra:
- Última hora do backup MongoDB e tamanho
- Contagem por coleção protegida (cadastros do cliente)
- Migrations aplicadas vs disponíveis (detecta drift)
- Alertas de saúde

Ver `/app/memory/DATA_PERSISTENCE.md` para política completa.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from core import get_current_user, is_super_admin, require_role
from database import db

router = APIRouter(prefix="/api/admin", tags=["admin-data-health"])

# Coleções "protegidas" — carregam dados de cliente, nunca podem ser perdidas.
# Manter alinhado com /app/memory/DATA_PERSISTENCE.md.
PROTECTED_COLLECTIONS: List[str] = [
    # Cadastros mestres
    "users", "collaborators", "companies", "company_branding",
    "settings_by_company", "fin_suppliers", "fin_categories",
    "fin_cash_accounts", "fin_filiais",
    "subscribers", "subscriber_phones", "subscriber_addresses",
    "subscriber_invoices",
    # Operação
    "tickets", "clock_records", "geofences",
    "fin_cash_movements", "fin_bills_payable", "fin_bills_receivable",
    "fin_installments",
    # IA e WhatsApp
    "aihub_agents", "isabella_prompt_fragments", "bank_import_memory",
    "wa_auth_state", "wa_conversations", "wa_messages",
    # Auditoria
    "platform_audit", "audit_log",
]

BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/var/backups/smartprov-mongo"))


def _latest_backup() -> Dict[str, Any]:
    """Encontra o backup mais recente e calcula tempo desde criação."""
    if not BACKUP_DIR.exists():
        return {
            "exists": False,
            "path": str(BACKUP_DIR),
            "hint": "Diretório de backup não existe. Em produção, agendar "
                    "cron com /app/backend/scripts/backup_mongo.sh",
        }
    files = sorted(
        BACKUP_DIR.glob("smartprov-*.archive.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return {
            "exists": False,
            "path": str(BACKUP_DIR),
            "hint": "Diretório existe mas nenhum backup encontrado.",
        }
    latest = files[0]
    stat = latest.stat()
    age_seconds = datetime.now().timestamp() - stat.st_mtime
    return {
        "exists": True,
        "file": latest.name,
        "size_bytes": stat.st_size,
        "size_human": _human_size(stat.st_size),
        "modified_at": datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc).isoformat(),
        "age_seconds": int(age_seconds),
        "age_human": _human_duration(age_seconds),
        "total_backups": len(files),
    }


def _human_size(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {unit}" if unit != "B" else f"{int(b)} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def _human_duration(s: float) -> str:
    if s < 60:
        return f"{int(s)}s"
    if s < 3600:
        return f"{int(s / 60)}min"
    if s < 86400:
        return f"{s / 3600:.1f}h"
    return f"{s / 86400:.1f}d"


@router.get("/data-health")
async def data_health(
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retorna painel completo de saúde dos dados. Admin/Gestor apenas."""
    if not (is_super_admin(user) or user.get("role") in ("administrador",
                                                              "gestor")):
        raise HTTPException(403, "Apenas admin/gestor pode acessar")
    # 1) Backup
    backup_info = _latest_backup()

    # 2) Contagem por coleção protegida
    collections_info: List[Dict[str, Any]] = []
    total_documents = 0
    for coll_name in PROTECTED_COLLECTIONS:
        try:
            count = await db[coll_name].estimated_document_count()
        except Exception:
            count = 0
        collections_info.append({"name": coll_name, "count": count})
        total_documents += count

    # 3) Migrations aplicadas vs disponíveis
    try:
        from scripts.migrations import MIGRATIONS as defined_migrations
    except Exception:
        defined_migrations = []
    applied = []
    async for m in db.schema_migrations.find({}, {"_id": 0}).sort(
            "applied_at", 1):
        applied.append(m)
    applied_ids = {m["id"] for m in applied}
    defined_ids = {mid for mid, _ in defined_migrations}
    pending = sorted(defined_ids - applied_ids)
    orphan = sorted(applied_ids - defined_ids)  # rodou mas código sumiu (drift)

    # 4) Alertas
    alerts: List[Dict[str, str]] = []
    if not backup_info.get("exists"):
        alerts.append({
            "level": "critical",
            "message": "Nenhum backup encontrado. Em produção, agendar "
                       "cron com backup_mongo.sh a cada 6h.",
        })
    elif backup_info.get("age_seconds", 0) > 86400:
        alerts.append({
            "level": "warn",
            "message": f"Último backup tem mais de 24h "
                       f"({backup_info['age_human']}).",
        })
    if pending:
        alerts.append({
            "level": "warn",
            "message": f"{len(pending)} migration(s) pendentes "
                       f"(restart do backend deve aplicar): "
                       f"{', '.join(pending[:3])}",
        })
    if orphan:
        alerts.append({
            "level": "warn",
            "message": f"{len(orphan)} migration(s) registradas mas o "
                       f"código sumiu (drift): {', '.join(orphan[:3])}",
        })
    # Coleções vazias críticas (ex: users vazio = problema sério)
    critical_empty = [c["name"] for c in collections_info
                       if c["count"] == 0
                       and c["name"] in ("users", "companies")]
    if critical_empty:
        alerts.append({
            "level": "critical",
            "message": f"Coleções críticas vazias: "
                       f"{', '.join(critical_empty)}",
        })

    # 5) Status geral
    has_critical = any(a["level"] == "critical" for a in alerts)
    has_warn = any(a["level"] == "warn" for a in alerts)
    overall = ("critical" if has_critical
                 else "warn" if has_warn else "ok")

    return {
        "overall": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "backup": backup_info,
        "collections": collections_info,
        "collections_total_documents": total_documents,
        "migrations": {
            "applied": applied,
            "pending": pending,
            "orphan": orphan,
            "applied_count": len(applied),
            "defined_count": len(defined_ids),
        },
        "alerts": alerts,
        "policy_doc": "/app/memory/DATA_PERSISTENCE.md",
    }


@router.post("/data-health/run-migrations")
async def force_run_migrations(
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Força execução de migrations pendentes (idempotente)."""
    if not is_super_admin(user):
        raise HTTPException(403, "Apenas super admin")
    from scripts.migrations import run_pending_migrations
    result = await run_pending_migrations(db)
    return {"ok": True, **result}
