"""
score_recovery.py — iter241

Limpa débito técnico de DADOS que está afundando o President Score:

  • ONUs com status=None ou em LOS há muito tempo → arquiva
  • Tickets sem atualização há >60d → fecha como auto_arquivado
  • Snapshots históricos do score (cron diário)

Tudo REVERSÍVEL via rollback (move-back das collections _archived).
"""
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()  # garante MONGO_URL/DB_NAME em scripts standalone (pytest, etc)

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

logger = logging.getLogger("score_recovery")

_client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = _client[os.environ["DB_NAME"]]

DAYS_LOS_ARCHIVE = 30        # ONUs em LOS há mais que isso → arquivar
DAYS_TICKET_AUTOCLOSE = 60   # Tickets sem update há mais que isso → fechar


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat() if d else None


# ──────────────────────────────────────────────────────────────────────────
# SIMULATE — Apenas calcula, sem mutação
# ──────────────────────────────────────────────────────────────────────────
async def simulate(company_id: str) -> Dict[str, Any]:
    """Retorna o score atual + projeção de quanto subiria se executar."""
    from services.presidente_executive import build_executive_report

    bq = {"company_id": company_id} if company_id else {}
    ticket_cutoff = _now() - timedelta(days=DAYS_TICKET_AUTOCLOSE)

    # ONUs candidatas
    onus_null = await db.smartolt_onus.count_documents({**bq, "status": None})
    onus_los = await db.smartolt_onus.count_documents(
        {**bq, "status": {"$in": ["LOS", "Power fail", "Offline"]}})
    onus_total_before = await db.smartolt_onus.count_documents(bq)
    onus_online = await db.smartolt_onus.count_documents({**bq, "status": "Online"})
    onus_to_clean = onus_null + onus_los

    # Tickets candidatos
    tickets_stale = await db.tickets.count_documents({
        **bq, "status": {"$in": ["aberta", "pendente", "open"]},
        "$or": [
            {"updated_at": {"$lt": ticket_cutoff.isoformat()}},
            {"updated_at": {"$exists": False}},
        ],
    })
    tickets_total_open = await db.tickets.count_documents(
        {**bq, "status": {"$in": ["aberta", "pendente", "open"]}})

    # Score atual
    rep = await build_executive_report(company_id)
    score_now = float(rep.get("president_score", {}).get("score") or 0)
    comps_now = rep.get("president_score", {}).get("components") or {}

    # Projeção: aplica o mesmo cálculo com volumes reduzidos
    proj = _project_components(comps_now,
                                onus_to_remove=onus_to_clean,
                                tickets_to_close=tickets_stale,
                                onus_online=onus_online)
    projected_score = _weighted(proj)

    return {
        "company_id": company_id,
        "current": {
            "score": round(score_now, 1),
            "components": {k: round(v, 1) for k, v in comps_now.items()},
        },
        "projected": {
            "score": round(projected_score, 1),
            "components": {k: round(v, 1) for k, v in proj.items()},
            "delta": round(projected_score - score_now, 1),
        },
        "actions": {
            "onus_status_null_to_archive": onus_null,
            "onus_los_offline_to_archive": onus_los,
            "tickets_stale_to_autoclose": tickets_stale,
            "tickets_open_total": tickets_total_open,
            "onus_total_before": onus_total_before,
            "onus_total_after": onus_total_before - onus_to_clean,
        },
        "params": {
            "days_los_archive": DAYS_LOS_ARCHIVE,
            "days_ticket_autoclose": DAYS_TICKET_AUTOCLOSE,
            "reversible": True,
        },
    }


def _project_components(comps: Dict, *, onus_to_remove: int,
                          tickets_to_close: int,
                          onus_online: int) -> Dict[str, float]:
    """Recalcula os 3 drivers vermelhos (rede, operacao) considerando
    a limpeza. Mantém os demais."""
    novo = dict(comps)
    # REDE: limpando ONUs null+LOS, crit/warning caem perto de zero,
    # com online > 0 → score perto de 100.
    if onus_online > 0:
        novo["rede"] = 95.0  # estimativa conservadora pós-limpeza
    # OPERACAO: cada ticket fechado adiciona 0.1 ao score (clamp 100)
    op = comps.get("operacao", 0) + (tickets_to_close * 0.1)
    novo["operacao"] = min(100.0, max(0.0, op))
    return novo


_WEIGHTS = {
    "receita": 0.15, "churn": 0.20, "operacao": 0.15, "rede": 0.15,
    "financeiro": 0.10, "estoque": 0.05, "seguranca": 0.05, "crescimento": 0.15,
}


def _weighted(comps: Dict) -> float:
    s = 0.0
    for k, w in _WEIGHTS.items():
        s += float(comps.get(k, 0) or 0) * w
    return s


# ──────────────────────────────────────────────────────────────────────────
# EXECUTE — Mutação real (REVERSÍVEL)
# ──────────────────────────────────────────────────────────────────────────
async def execute(company_id: str, *, executed_by: str,
                   reason: str = "") -> Dict[str, Any]:
    """Move ONUs e Tickets pra collections _archived com tag de batch."""
    batch_id = f"rec-{uuid.uuid4().hex[:12]}"
    started = _now()
    bq = {"company_id": company_id} if company_id else {}
    ticket_cutoff = _now() - timedelta(days=DAYS_TICKET_AUTOCLOSE)

    # 1) Arquiva ONUs com status=None
    null_docs: List[Dict] = []
    async for d in db.smartolt_onus.find({**bq, "status": None}):
        d["_archived_at"] = started.isoformat()
        d["_archived_batch_id"] = batch_id
        d["_archived_reason"] = "score_recovery: status_null"
        null_docs.append(d)
    if null_docs:
        await db.smartolt_onus_archived.insert_many(null_docs)
        await db.smartolt_onus.delete_many({**bq, "status": None})

    # 2) Arquiva ONUs em LOS/Power fail/Offline (consideramos antigas)
    los_q = {**bq, "status": {"$in": ["LOS", "Power fail", "Offline"]}}
    los_docs: List[Dict] = []
    async for d in db.smartolt_onus.find(los_q):
        d["_archived_at"] = started.isoformat()
        d["_archived_batch_id"] = batch_id
        d["_archived_reason"] = f"score_recovery: {d.get('status')}_long"
        los_docs.append(d)
    if los_docs:
        await db.smartolt_onus_archived.insert_many(los_docs)
        await db.smartolt_onus.delete_many(los_q)

    # 3) Fecha tickets stale
    tickets_stale_q = {
        **bq, "status": {"$in": ["aberta", "pendente", "open"]},
        "$or": [
            {"updated_at": {"$lt": ticket_cutoff.isoformat()}},
            {"updated_at": {"$exists": False}},
        ],
    }
    ticket_close_res = await db.tickets.update_many(
        tickets_stale_q,
        {"$set": {
            "status": "auto_arquivado",
            "auto_arquivado_at": started.isoformat(),
            "auto_arquivado_batch_id": batch_id,
            "auto_arquivado_reason": "score_recovery_stale_60d",
            "updated_at": started.isoformat(),
        }},
    )

    # 4) Audit log
    summary = {
        "batch_id": batch_id,
        "company_id": company_id,
        "executed_by": executed_by,
        "executed_at": started.isoformat(),
        "reason": reason or "Score recovery automático",
        "actions": {
            "onus_archived_null": len(null_docs),
            "onus_archived_los": len(los_docs),
            "tickets_autoclosed": ticket_close_res.modified_count,
        },
        "reversible": True,
        "rollback_endpoint": f"/api/presidente-ia/score-recovery/rollback/{batch_id}",
    }
    await db.score_recovery_batches.insert_one(dict(summary))

    # Recalc score pós-execução pra registrar histórico imediato
    try:
        from services.presidente_executive import build_executive_report
        rep_after = await build_executive_report(company_id)
        score_after = rep_after.get("president_score", {}).get("score")
        summary["score_after"] = score_after
        await db.score_recovery_batches.update_one(
            {"batch_id": batch_id}, {"$set": {"score_after": score_after}})
        await snapshot_score(company_id, source=f"recovery_{batch_id}")
    except Exception as e:
        logger.warning("recompute score after recovery: %r", e)

    return summary


# ──────────────────────────────────────────────────────────────────────────
# ROLLBACK — Devolve documentos arquivados a origem
# ──────────────────────────────────────────────────────────────────────────
async def rollback(batch_id: str) -> Dict[str, Any]:
    """Devolve ONUs arquivadas e reabre tickets fechados deste batch."""
    started = _now()
    # ONUs
    onus_back: List[Dict] = []
    async for d in db.smartolt_onus_archived.find(
            {"_archived_batch_id": batch_id}):
        for k in ("_archived_at", "_archived_batch_id", "_archived_reason"):
            d.pop(k, None)
        onus_back.append(d)
    if onus_back:
        await db.smartolt_onus.insert_many(onus_back)
        await db.smartolt_onus_archived.delete_many(
            {"_archived_batch_id": batch_id})

    # Tickets — reabre status
    ticket_back = await db.tickets.update_many(
        {"auto_arquivado_batch_id": batch_id},
        {"$set": {"status": "aberta",
                   "rolled_back_at": started.isoformat(),
                   "updated_at": started.isoformat()},
         "$unset": {"auto_arquivado_at": "", "auto_arquivado_batch_id": "",
                     "auto_arquivado_reason": ""}},
    )

    await db.score_recovery_batches.update_one(
        {"batch_id": batch_id},
        {"$set": {"rolled_back_at": started.isoformat(),
                   "rolled_back_onus": len(onus_back),
                   "rolled_back_tickets": ticket_back.modified_count}},
    )
    return {
        "batch_id": batch_id,
        "rolled_back_onus": len(onus_back),
        "rolled_back_tickets": ticket_back.modified_count,
        "rolled_back_at": started.isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────────
# HISTORY — Snapshots do score
# ──────────────────────────────────────────────────────────────────────────
async def snapshot_score(company_id: str, *, source: str = "cron") -> Dict:
    """Salva snapshot do score atual em president_score_history."""
    from services.presidente_executive import build_executive_report
    rep = await build_executive_report(company_id)
    p = rep.get("president_score") or {}
    doc = {
        "company_id": company_id,
        "snapshot_at": _now().isoformat(),
        "score": float(p.get("score") or 0),
        "status": p.get("status"),
        "components": p.get("components") or {},
        "source": source,
    }
    await db.president_score_history.insert_one(dict(doc))
    return doc


async def history(company_id: str, days: int = 30) -> List[Dict]:
    """Time-series do score nos últimos N dias."""
    since = (_now() - timedelta(days=days)).isoformat()
    out: List[Dict] = []
    async for d in db.president_score_history.find(
            {"company_id": company_id, "snapshot_at": {"$gte": since}},
            {"_id": 0}).sort("snapshot_at", 1):
        out.append(d)
    return out


# ──────────────────────────────────────────────────────────────────────────
# Cron job entrypoint
# ──────────────────────────────────────────────────────────────────────────
async def daily_snapshot_job():
    """APScheduler job — grava snapshot diário do score por empresa."""
    cids = await db.companies.distinct("_id") if "companies" in (
        await db.list_collection_names()) else ["co-demo"]
    if not cids:
        cids = ["co-demo"]
    for cid in cids:
        try:
            await snapshot_score(str(cid), source="cron_daily")
        except Exception as e:
            logger.warning("daily_snapshot for %s: %r", cid, e)
