"""isabella_outcome_recorder — Sprint A (P0 CEO 17/02/2026).

Fecha o **learning loop** da Isabella: para cada oportunidade `expired`
sem outcome registrado, deriva o resultado real a partir de SINAIS
OPERACIONAIS no banco (subscriber_invoices, atlaz_clients_cache,
payment_audit_logs) — SEM backfill, SEM simulação.

Cada outcome classificado:
  1. Cria doc em `isabella_outcomes` (success | failure | partial | unknown)
  2. Chama `isabella_learning.record_*` → ajusta peso do playbook
  3. Atualiza a opp com `outcome_id` e `outcome_recorded_at`

Regra dura: **somente fatos**. Se não há sinal claro, marca `unknown` e
NÃO conta como aprendizado positivo nem negativo.

Suportes por kind:
  - dunning   : olha `subscriber_invoices.status` das faturas referenciadas
  - revenue   : olha pagamentos do subscriber no período pós-opp
  - churn     : olha `atlaz_clients_cache.is_active` + cancelamentos
  - twin/shield_alert : olha próxima detecção (recorrência ou ausência)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db
from services import isabella_learning

logger = logging.getLogger("ponto.isabella_outcome_recorder")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Classificadores por KIND ──────────────────────────────────


async def _classify_dunning(opp: Dict[str, Any]) -> Dict[str, Any]:
    """Outcome de cobrança: olha status atual das faturas referenciadas."""
    invoices = ((opp.get("evidence") or {}).get("invoices") or [])
    if not invoices:
        return {"outcome": "unknown", "signal": "no_invoice_ref"}
    paid = 0
    open_ = 0
    examined: List[str] = []
    for inv in invoices:
        inv_id = inv.get("id")
        if not inv_id:
            continue
        examined.append(inv_id)
        doc = await db.subscriber_invoices.find_one(
            {"id": inv_id}, {"_id": 0, "status": 1, "paid_date": 1})
        if not doc:
            continue
        st = (doc.get("status") or "").lower()
        if st == "paid":
            paid += 1
        elif st in ("open", "overdue", "pending"):
            open_ += 1
    total = paid + open_
    if total == 0:
        return {"outcome": "unknown", "signal": "invoices_missing",
                "examined": examined}
    if paid == total:
        return {"outcome": "success", "signal": "all_invoices_paid",
                "paid_count": paid, "examined": examined}
    if paid > 0:
        return {"outcome": "partial", "signal": "some_invoices_paid",
                "paid_count": paid, "open_count": open_,
                "examined": examined}
    return {"outcome": "failure", "signal": "all_invoices_still_open",
            "open_count": open_, "examined": examined}


async def _classify_churn(opp: Dict[str, Any]) -> Dict[str, Any]:
    """Cliente segue ativo? success se ativo após período, failure se
    cancelou ou ficou inativo."""
    ext_id = (
        (opp.get("evidence_at_open") or {}).get("subscriber_external_id")
        or (opp.get("recommended_action") or {}).get("subscriber_external_id")
    )
    if not ext_id:
        return {"outcome": "unknown", "signal": "no_subscriber_ref"}
    cache = await db.atlaz_clients_cache.find_one(
        {"$or": [{"external_id": str(ext_id)},
                  {"external_id": int(ext_id) if str(ext_id).isdigit() else ext_id}]},
        {"_id": 0, "status": 1, "is_active": 1, "blocked": 1})
    if not cache:
        return {"outcome": "unknown", "signal": "subscriber_not_in_cache"}
    is_active = (cache.get("is_active") is True
                 or (cache.get("status") or "").lower() in ("ativo", "active"))
    if is_active and not cache.get("blocked"):
        return {"outcome": "success", "signal": "subscriber_still_active"}
    if cache.get("blocked"):
        return {"outcome": "partial", "signal": "subscriber_blocked"}
    return {"outcome": "failure", "signal": "subscriber_canceled"}


async def _classify_revenue(opp: Dict[str, Any]) -> Dict[str, Any]:
    """Receita: olha se houve pagamento do subscriber após a opp ser
    criada (subscriber_invoices.paid_date > opp.created_at)."""
    target_id = opp.get("target_id")
    ext_id = (opp.get("evidence_at_open") or {}).get("subscriber_external_id")
    opp_ts = opp.get("created_at") or ""
    q: Dict[str, Any] = {"status": "paid", "paid_date": {"$gt": opp_ts}}
    if ext_id:
        q["subscriber_external_id"] = str(ext_id)
    elif target_id:
        q["subscriber_id"] = target_id
    else:
        return {"outcome": "unknown", "signal": "no_subscriber_ref"}
    paid_inv = await db.subscriber_invoices.find_one(
        q, {"_id": 0, "id": 1, "amount": 1, "paid_date": 1})
    if paid_inv:
        return {"outcome": "success", "signal": "revenue_confirmed",
                "evidence_invoice_id": paid_inv.get("id"),
                "amount_recovered": paid_inv.get("amount")}
    return {"outcome": "failure", "signal": "no_revenue_after_opp"}


async def _classify_twin_or_shield(opp: Dict[str, Any]) -> Dict[str, Any]:
    """Anomalia (twin/shield_alert): se foi detectada DE NOVO depois,
    ainda existe → failure. Se sumiu → success."""
    target_id = opp.get("target_id")
    kind = opp.get("kind")
    subkind = opp.get("subkind")
    after = opp.get("expires_at") or opp.get("created_at")
    if not (target_id and after):
        return {"outcome": "unknown", "signal": "missing_ref"}
    later = await db.isabella_commander_opportunities.find_one(
        {"kind": kind, "subkind": subkind, "target_id": target_id,
         "created_at": {"$gt": after}},
        {"_id": 0, "id": 1})
    if later:
        return {"outcome": "failure", "signal": "anomaly_recurred",
                "next_opp_id": later.get("id")}
    return {"outcome": "success", "signal": "anomaly_resolved"}


# Dispatcher principal
_CLASSIFIERS = {
    "dunning": _classify_dunning,
    "churn": _classify_churn,
    "revenue": _classify_revenue,
    "twin": _classify_twin_or_shield,
    "shield_alert": _classify_twin_or_shield,
}


async def classify_opportunity(opp: Dict[str, Any]) -> Dict[str, Any]:
    kind = (opp.get("kind") or "").lower()
    fn = _CLASSIFIERS.get(kind)
    if fn is None:
        return {"outcome": "unknown", "signal": f"unsupported_kind:{kind}"}
    return await fn(opp)


# ── Registro com efeito colateral ─────────────────────────────


async def record_outcome_for(opp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Classifica + persiste + ajusta peso. Idempotente: se a opp já tem
    `outcome_id`, retorna o existente."""
    if opp.get("outcome_id"):
        existing = await db.isabella_outcomes.find_one(
            {"id": opp["outcome_id"]}, {"_id": 0})
        if existing:
            return existing
    result = await classify_opportunity(opp)
    outcome_val = result.get("outcome") or "unknown"
    now = _now()
    cid = opp.get("company_id") or "co-demo"
    kind = opp.get("kind") or "_"
    subkind = opp.get("subkind") or "_"
    playbook = ((opp.get("recommended_action") or {}).get("template")
                or (opp.get("recommended_action") or {}).get("type")
                or "default")
    outcome_id = f"out-{kind}-{uuid.uuid4().hex[:10]}"
    impact = float(opp.get("impact_brl") or 0)
    roi_real = 0.0
    if outcome_val == "success":
        roi_real = impact
    elif outcome_val == "partial":
        roi_real = impact * 0.5
    doc = {
        "id": outcome_id,
        "opp_id": opp.get("id"),
        "company_id": cid,
        "kind": kind,
        "subkind": subkind,
        "playbook": playbook,
        "target_type": opp.get("target_type"),
        "target_id": opp.get("target_id"),
        "target_label": opp.get("target_label"),
        "score_pred": opp.get("score"),
        "probability_pred": opp.get("probability"),
        "impact_pred_brl": impact,
        "actor": "isabella_outcome_recorder",
        "outcome": outcome_val,
        "result": outcome_val,
        "signal": result.get("signal"),
        "evidence_classification": result,
        "roi_real_brl": roi_real,
        "created_at": _iso(now),
        "measured_at": _iso(now),
        "evidence_at_open": opp.get("evidence_at_open")
                              or opp.get("evidence") or {},
    }
    await db.isabella_outcomes.insert_one(doc)
    # Pontua o motor de pesos (somente para outcome decisivo)
    try:
        if outcome_val == "success":
            await isabella_learning.record_attempt(
                company_id=cid, kind=kind, subkind=subkind, playbook=playbook)
            await isabella_learning.record_outcome(
                company_id=cid, kind=kind, subkind=subkind,
                playbook=playbook, success=True, impact_brl=impact)
        elif outcome_val == "failure":
            await isabella_learning.record_attempt(
                company_id=cid, kind=kind, subkind=subkind, playbook=playbook)
            await isabella_learning.record_outcome(
                company_id=cid, kind=kind, subkind=subkind,
                playbook=playbook, success=False)
        elif outcome_val == "partial":
            # tratamento light: conta tentativa mas não move peso
            await isabella_learning.record_attempt(
                company_id=cid, kind=kind, subkind=subkind, playbook=playbook)
    except Exception as e:  # noqa: BLE001
        logger.exception("[outcome_recorder] learning record exc: %s", e)
    # Atualiza a opp com o link do outcome
    await db.isabella_commander_opportunities.update_one(
        {"id": opp.get("id"), "company_id": cid},
        {"$set": {"outcome_id": outcome_id,
                  "outcome_recorded_at": _iso(now),
                  "outcome": outcome_val,
                  "outcome_signal": result.get("signal")}})
    logger.info("[outcome_recorder] opp=%s kind=%s -> %s (%s)",
                opp.get("id"), kind, outcome_val, result.get("signal"))
    doc.pop("_id", None)
    return doc


async def reconcile_batch(*, company_id: Optional[str] = None,
                            limit: int = 50,
                            only_kinds: Optional[List[str]] = None
                            ) -> Dict[str, Any]:
    """Varre opps `expired` sem outcome_id e classifica em batch.

    Idempotente. Designed pra rodar via scheduler (a cada 1h) e via
    endpoint admin de disparo manual.
    """
    q: Dict[str, Any] = {
        "status": "expired",
        "outcome_id": {"$exists": False},
    }
    if company_id:
        q["company_id"] = company_id
    if only_kinds:
        q["kind"] = {"$in": only_kinds}
    cursor = (db.isabella_commander_opportunities
              .find(q, {"_id": 0}).sort("expires_at", 1).limit(limit))
    docs = await cursor.to_list(limit)
    summary: Dict[str, int] = {
        "examined": 0, "success": 0, "failure": 0,
        "partial": 0, "unknown": 0, "errors": 0,
    }
    for opp in docs:
        summary["examined"] += 1
        try:
            out = await record_outcome_for(opp)
            v = (out or {}).get("outcome") or "unknown"
            summary[v] = summary.get(v, 0) + 1
        except Exception as e:  # noqa: BLE001
            summary["errors"] += 1
            logger.exception(
                "[outcome_recorder] error on opp=%s: %s",
                opp.get("id"), e)
    return summary


# ── Scheduler hook ────────────────────────────────────────────


def register_scheduler(scheduler) -> None:
    """Roda reconciliação a cada 1h em todas as companies. Idempotente."""
    async def _tick():
        try:
            r = await reconcile_batch(limit=200)
            logger.info("[outcome_recorder.tick] %s", r)
        except Exception as e:  # noqa: BLE001
            logger.exception("[outcome_recorder.tick] %s", e)

    scheduler.add_job(
        _tick, "interval", minutes=60,
        id="isabella_outcome_recorder",
        replace_existing=True, max_instances=1, coalesce=True)
    logger.info("[outcome_recorder] registered every 60min")
