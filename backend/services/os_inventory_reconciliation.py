"""
os_inventory_reconciliation.py — Worker de Reconciliação (CTO 2026-02, Q4=b).

Reprocessa periodicamente OS marcadas como `pendente_conciliacao` (SmartOLT
estava indisponível na finalização). Re-consulta o SmartOLT, valida SN/MAC/
PPPoE, anexa snapshot e marca como `conciliado=True` quando resolve.

Limites:
  - MAX_RETRIES por ticket (default 6 → ~6h se intervalo for 1h)
  - Após MAX_RETRIES, gera notificação `manager_callback_required` pro gestor
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from database import db


logger = logging.getLogger("os_inventory_reconciliation")

MAX_RETRIES = int(os.environ.get("OS_RECONCILIATION_MAX_RETRIES", "6"))
INTERVAL_SEC = int(os.environ.get("OS_RECONCILIATION_INTERVAL_SEC", "3600"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _try_reconcile_one(t: Dict[str, Any]) -> Dict[str, Any]:
    """Tenta conciliar um ticket. Retorna {status, reason, snapshot}."""
    from services.os_inventory_guardrail import _validate_smartolt
    completion = t.get("completion_data") or {}
    sn = (completion.get("new_ont_sn") or completion.get("ont_sn")
          or completion.get("scan_sn"))
    mac = completion.get("new_ont_mac") or completion.get("ont")
    reasons: List[str] = []
    snap = await _validate_smartolt(t, sn, mac, reasons)
    if not snap.get("available"):
        return {"status": "still_pending",
                "reason": "smartolt_indisponivel",
                "snapshot": snap}
    if reasons:
        # divergência detectada — não auto-resolve, alerta gestor
        return {"status": "diverge",
                "reason": "|".join(reasons),
                "snapshot": snap}
    # Conciliado
    return {"status": "ok", "reason": None, "snapshot": snap}


async def _alert_manager(t: Dict[str, Any], reason: str) -> None:
    """Cria notificação ao gestor após esgotar retries."""
    snap = t.get("client_snapshot") or {}
    await db.notifications.insert_one({
        "id": f"notif-recon-{t.get('id')}",
        "company_id": t.get("company_id") or "co-demo",
        "type": "os_reconciliation_failed",
        "severity": "critical",
        "title": "OS Pendente de Conciliação — limite excedido",
        "body": (
            f"Ticket {t.get('id')} ({snap.get('name') or '?'}) ficou "
            f"{MAX_RETRIES}x na fila de reconciliação SmartOLT e não foi "
            f"resolvido. Última causa: {reason}. Verifique manualmente."
        ),
        "ticket_id": t.get("id"),
        "target_roles": ["gestor", "administrador"],
        "read_by": [],
        "created_at": _now_iso(),
    })


async def run_reconciliation_pass() -> Dict[str, int]:
    """Executa 1 passagem do worker. Retorna stats {scanned, resolved,
    still_pending, escalated}."""
    stats = {"scanned": 0, "resolved": 0, "still_pending": 0,
             "escalated": 0, "diverge": 0}
    cursor = db.tickets.find({"status": "pendente_conciliacao"},
                              {"_id": 0})
    async for t in cursor:
        stats["scanned"] += 1
        retries = int(t.get("pending_conciliation_retries") or 0)
        result = await _try_reconcile_one(t)
        if result["status"] == "ok":
            await db.tickets.update_one(
                {"id": t["id"]},
                {"$set": {"status": "finalizada",
                          "conciliado": True,
                          "pending_conciliation_resolved_at": _now_iso(),
                          "pending_conciliation_snapshot": result["snapshot"]}},
            )
            await db.inventory_os_movements_audit.insert_one({
                "id": f"reconaud-{t['id']}-{retries}",
                "ticket_id": t["id"], "company_id": t.get("company_id"),
                "movement_type": "reconciliation_resolved",
                "actor_origin": "reconciliation_worker",
                "snapshot": result["snapshot"],
                "created_at": _now_iso(),
                "hash_auditoria": "",  # reuso de hash não obrigatório aqui
            })
            stats["resolved"] += 1
            continue
        # ainda pendente — incrementa retry
        new_retries = retries + 1
        upd = {
            "pending_conciliation_retries": new_retries,
            "pending_conciliation_last_try_at": _now_iso(),
            "pending_conciliation_last_reason": result["reason"],
        }
        if result["status"] == "diverge":
            stats["diverge"] += 1
        else:
            stats["still_pending"] += 1
        if new_retries >= MAX_RETRIES:
            upd["pending_conciliation_escalated"] = True
            await _alert_manager(t, result["reason"] or "?")
            stats["escalated"] += 1
        await db.tickets.update_one({"id": t["id"]}, {"$set": upd})
    return stats


async def worker_loop() -> None:
    """Loop infinito para uvicorn startup_event. Cancelável."""
    logger.info("[os_recon] worker started — interval=%ss max_retries=%s",
                INTERVAL_SEC, MAX_RETRIES)
    while True:
        try:
            stats = await run_reconciliation_pass()
            if stats["scanned"]:
                logger.info("[os_recon] pass complete: %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # pragma: no cover
            logger.warning("[os_recon] pass failed: %s", e)
        await asyncio.sleep(INTERVAL_SEC)
