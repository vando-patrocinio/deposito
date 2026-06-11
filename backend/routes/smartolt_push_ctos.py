"""
smartolt_push_ctos.py — Worker que sincroniza CTOs locais para o SmartOLT (iter211bd)

Para cada CTO em `db.ctos` com `smartolt_eligible=True` e
`smartolt_sync_pending=True`, chama `add_zone()` da SmartOLT API criando
a Zone correspondente (Zone == CTO no vocabulário SmartOLT).

Após sucesso, marca:
  • `smartolt_sync_pending = False`
  • `smartolt_synced_at = ISO timestamp`
  • `smartolt_zone_name = nome usado no SmartOLT`

Em caso de falha, mantém pending=True e incrementa contador para retry
exponencial (backoff: 1min, 5min, 15min, 60min).

Modos de uso:
  • Worker em background (loop a cada 60s) — registrado em startup.
  • Endpoint manual `POST /api/smartolt-push-ctos/run` para gestor forçar.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "infra-team",
    "domain": "rede",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from core import get_current_user
from database import db
from services.smartolt_zones import add_zone, list_zones

logger = logging.getLogger("smartolt.push_ctos")
router = APIRouter(prefix="/api/smartolt-push-ctos", tags=["smartolt-push"])

_RUN_LOCK = asyncio.Lock()
_INTERVAL_SEC = 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _backoff_seconds(attempts: int) -> int:
    """1min → 5min → 15min → 60min → 60min..."""
    table = [60, 300, 900, 3600]
    return table[min(attempts, len(table) - 1)]


async def _sync_one(cid: str, cto: dict) -> dict:
    """Sincroniza uma CTO. Retorna dict com resultado pra audit."""
    cto_id = cto["id"]
    zone_name = (cto.get("name") or "").strip()
    if not zone_name:
        # Sem nomenclatura — não dá pra sincronizar
        await db.ctos.update_one(
            {"id": cto_id, "company_id": cid},
            {"$set": {"smartolt_sync_pending": False,
                       "smartolt_last_error": "CTO sem nomenclatura (name vazio)",
                       "smartolt_last_attempt_at": _now_iso()}},
        )
        return {"cto_id": cto_id, "ok": False, "reason": "empty-name"}

    try:
        # 1) Lista zones atuais (com cache 60s). Se já existir, considera sync OK.
        zones = await list_zones(cid)
        already = any((z.get("zone") or z.get("name") or "").strip().upper()
                       == zone_name.upper() for z in zones)
        if not already:
            await add_zone(cid, zone_name)
        # Marca sucesso
        await db.ctos.update_one(
            {"id": cto_id, "company_id": cid},
            {"$set": {
                "smartolt_sync_pending": False,
                "smartolt_synced_at": _now_iso(),
                "smartolt_zone_name": zone_name,
                "smartolt_last_error": None,
                "smartolt_sync_attempts": 0,
            }},
        )
        await db.smartolt_actions.insert_one({
            "company_id": cid,
            "action": "push_cto",
            "external_id": zone_name,
            "result_ok": True,
            "detail": "already-exists" if already else "created",
            "timestamp": _now_iso(),
        })
        logger.info("[smartolt-push] CTO %s sincronizada (zone=%s, novo=%s)",
                     cto_id, zone_name, not already)
        return {"cto_id": cto_id, "ok": True,
                 "detail": "already-exists" if already else "created"}
    except Exception as e:
        # Marca falha + agenda próxima tentativa
        attempts = int(cto.get("smartolt_sync_attempts") or 0) + 1
        await db.ctos.update_one(
            {"id": cto_id, "company_id": cid},
            {"$set": {
                "smartolt_last_error": str(e)[:300],
                "smartolt_last_attempt_at": _now_iso(),
                "smartolt_sync_attempts": attempts,
            }},
        )
        await db.smartolt_actions.insert_one({
            "company_id": cid,
            "action": "push_cto",
            "external_id": zone_name,
            "result_ok": False,
            "detail": str(e)[:400],
            "timestamp": _now_iso(),
        })
        logger.warning("[smartolt-push] CTO %s falhou (try %d): %s",
                       cto_id, attempts, e)
        return {"cto_id": cto_id, "ok": False, "reason": str(e)[:200]}


async def run_once() -> dict:
    """Sweep: lista todas CTOs eligible+pending de todas as empresas e tenta sync."""
    if _RUN_LOCK.locked():
        return {"skipped": True, "reason": "already-running"}
    async with _RUN_LOCK:
        now_ts = datetime.now(timezone.utc)
        results: list[dict] = []
        # Agrupa por company_id (cada empresa pode ter SmartOLT diferente)
        pipe = [
            {"$match": {"smartolt_eligible": True, "smartolt_sync_pending": True}},
            {"$group": {"_id": "$company_id",
                         "ctos": {"$push": {
                             "id": "$id", "name": "$name",
                             "smartolt_sync_attempts": "$smartolt_sync_attempts",
                             "smartolt_last_attempt_at": "$smartolt_last_attempt_at",
                         }}}},
        ]
        async for row in db.ctos.aggregate(pipe):
            cid = row["_id"]
            # Verifica se SmartOLT está configurado pra essa empresa
            cfg = await db.smartolt_config.find_one(
                {"company_id": cid}, {"_id": 0, "enabled": 1, "api_key": 1, "subdomain": 1},
            )
            if not cfg or not cfg.get("enabled") or not cfg.get("api_key"):
                continue  # ignora silenciosamente
            for cto in row["ctos"]:
                # Backoff: respeita intervalo desde a última tentativa
                last_iso = cto.get("smartolt_last_attempt_at")
                attempts = int(cto.get("smartolt_sync_attempts") or 0)
                if last_iso and attempts > 0:
                    try:
                        last_dt = datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
                        wait = _backoff_seconds(attempts - 1)
                        if (now_ts - last_dt).total_seconds() < wait:
                            continue  # ainda no backoff
                    except Exception:
                        pass
                res = await _sync_one(cid, cto)
                results.append(res)
        ok = sum(1 for r in results if r.get("ok"))
        fail = len(results) - ok
        return {"processed": len(results), "ok": ok, "fail": fail,
                 "ts": _now_iso(), "items": results[:50]}


async def _worker_loop():
    """Loop infinito chamado em startup. Roda a cada _INTERVAL_SEC."""
    logger.info("[smartolt-push] worker iniciado (intervalo=%ds)", _INTERVAL_SEC)
    while True:
        try:
            await run_once()
        except Exception as e:
            logger.exception("[smartolt-push] worker error: %s", e)
        await asyncio.sleep(_INTERVAL_SEC)


def start_worker():
    """Disparado no startup do FastAPI."""
    loop = asyncio.get_event_loop()
    loop.create_task(_worker_loop())


# ─── Endpoints admin/manual ────────────────────────────────────────────────

def _require_manager(user: dict):
    roles = user.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    if (user.get("is_super_admin")
        or any(r in {"gestor", "admin", "super_admin", "gestor_rede"}
                for r in roles)):
        return
    raise HTTPException(403, "Acesso negado (admin/gestor)")


@router.post("/run")
async def run_manually(user: dict = Depends(get_current_user)):
    """Força um sweep imediato (resposta imediata, sem aguardar todos)."""
    _require_manager(user)
    return await run_once()


@router.get("/queue")
async def list_queue(user: dict = Depends(get_current_user)):
    """Lista CTOs aguardando sync (pendentes ou já sincronizadas)."""
    _require_manager(user)
    cid = user.get("company_id")
    pending_cur = db.ctos.find(
        {"company_id": cid, "smartolt_eligible": True,
          "smartolt_sync_pending": True},
        {"_id": 0, "id": 1, "name": 1, "vlan": 1, "smartolt_olt_name": 1,
         "smartolt_sync_attempts": 1, "smartolt_last_attempt_at": 1,
         "smartolt_last_error": 1, "created_at": 1},
    ).sort("created_at", -1).limit(200)
    pending = await pending_cur.to_list(200)

    synced_cur = db.ctos.find(
        {"company_id": cid, "smartolt_eligible": True,
          "smartolt_sync_pending": False, "smartolt_synced_at": {"$ne": None}},
        {"_id": 0, "id": 1, "name": 1, "vlan": 1, "smartolt_olt_name": 1,
         "smartolt_synced_at": 1},
    ).sort("smartolt_synced_at", -1).limit(50)
    synced = await synced_cur.to_list(50)

    return {"pending": pending, "synced_recent": synced,
            "pending_count": len(pending)}


@router.get("/health")
async def smartolt_health(user: dict = Depends(get_current_user)):
    """iter211bh — Stats agregadas pro Dashboard:
       • total: # CTOs
       • eligible: # em VLAN com OLT
       • synced: # já registradas no SmartOLT
       • pending: # aguardando sync
       • orphans: # sem OLT (só Base de Portas)
       • failing: # com 3+ tentativas falhas
    """
    cid = user.get("company_id")
    pipeline = [
        {"$match": {"company_id": cid}},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "eligible": {"$sum": {"$cond": [{"$eq": ["$smartolt_eligible", True]}, 1, 0]}},
            "synced": {"$sum": {"$cond": [
                {"$and": [{"$eq": ["$smartolt_eligible", True]},
                            {"$eq": ["$smartolt_sync_pending", False]},
                            {"$ne": ["$smartolt_synced_at", None]}]},
                1, 0]}},
            "pending": {"$sum": {"$cond": [
                {"$and": [{"$eq": ["$smartolt_eligible", True]},
                            {"$eq": ["$smartolt_sync_pending", True]}]},
                1, 0]}},
            "failing": {"$sum": {"$cond": [
                {"$gte": [{"$ifNull": ["$smartolt_sync_attempts", 0]}, 3]},
                1, 0]}},
        }},
    ]
    row = None
    async for r in db.ctos.aggregate(pipeline):
        row = r
        break
    if not row:
        return {"total": 0, "eligible": 0, "synced": 0, "pending": 0,
                "orphans": 0, "failing": 0, "sync_pct": 100}
    total = row.get("total", 0)
    eligible = row.get("eligible", 0)
    synced = row.get("synced", 0)
    pending = row.get("pending", 0)
    failing = row.get("failing", 0)
    orphans = total - eligible
    sync_pct = round((synced / eligible) * 100) if eligible > 0 else 100
    return {"total": total, "eligible": eligible, "synced": synced,
             "pending": pending, "orphans": orphans, "failing": failing,
             "sync_pct": sync_pct}


@router.post("/retry/{cto_id}")
async def retry_one(cto_id: str, user: dict = Depends(get_current_user)):
    """Força nova tentativa para uma CTO específica (reseta backoff)."""
    _require_manager(user)
    cid = user.get("company_id")
    cto = await db.ctos.find_one({"id": cto_id, "company_id": cid}, {"_id": 0})
    if not cto:
        raise HTTPException(404, "CTO não encontrada")
    if not cto.get("smartolt_eligible"):
        raise HTTPException(400, "CTO não é elegível para SmartOLT")
    # Reseta contador e dispara
    await db.ctos.update_one(
        {"id": cto_id, "company_id": cid},
        {"$set": {"smartolt_sync_pending": True,
                   "smartolt_sync_attempts": 0,
                   "smartolt_last_attempt_at": None}},
    )
    res = await _sync_one(cid, await db.ctos.find_one(
        {"id": cto_id, "company_id": cid}, {"_id": 0}))
    return res


@router.post("/retry-all")
async def retry_all_pending(user: dict = Depends(get_current_user)):
    """iter211bi — Reseta backoff de TODAS as CTOs pendentes e dispara sweep imediato."""
    _require_manager(user)
    cid = user.get("company_id")
    r = await db.ctos.update_many(
        {"company_id": cid, "smartolt_eligible": True,
          "smartolt_sync_pending": True},
        {"$set": {"smartolt_sync_attempts": 0,
                   "smartolt_last_attempt_at": None}},
    )
    sweep = await run_once()
    return {"reset_count": r.modified_count, "sweep": sweep}
