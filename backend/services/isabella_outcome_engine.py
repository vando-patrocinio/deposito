"""ISABELLA AI_OUTCOME ENGINE — fechamento do ciclo de aprendizado.

Toda oportunidade aprovada/executada/dismissada vira um `isabella_outcomes`
com `outcome_id` único. Um job de **resolução** verifica no mundo real
(`subscribers`, `subscriber_invoices`, `tickets`) se a hipótese se
realizou — e atualiza `result` (success/failure) + `roi_real`.

Convenção:
  • outcome_id = "out-<kind>-<n>-<hash>" (ex: out-churn-000142-a3b9)
  • Cada outcome aponta para `opp_id` (1:1)
  • result = pending | success | failure | inconclusive
  • measured_at = ISO timestamp da medição real
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db
from services.event_bus import EventType, emit_event

log = logging.getLogger("ponto.isabella_outcome_engine")

# Janelas de espera para verificar outcome real após execução
RESOLUTION_DAYS = {
    "churn": 30,       # cliente cancelou em até 30d após retenção?
    "dunning": 21,     # fatura pagou em até 21d após cobrança?
    "revenue": 30,     # cliente upgradou em até 30d?
    "expansion": 60,   # leads converteram em até 60d?
    "twin": 14,        # ativo falhou de fato em 14d?
}


def _now():
    return datetime.now(timezone.utc)


def _iso(d):
    return d.isoformat()


async def ensure_indexes() -> None:
    try:
        await db.isabella_outcomes.create_index(
            [("company_id", 1), ("kind", 1), ("result", 1)])
        await db.isabella_outcomes.create_index([("opp_id", 1)], unique=True)
        await db.isabella_outcomes.create_index([("resolution_due_at", 1)])
        await db.isabella_outcomes.create_index(
            [("company_id", 1), ("created_at", -1)])
    except Exception as e:  # noqa
        log.warning("[outcome] ensure_indexes: %s", e)


async def open_outcome(opp: Dict[str, Any], *,
                        actor: Optional[str] = None,
                        playbook: Optional[str] = None) -> Dict[str, Any]:
    """Abre outcome quando uma oportunidade é APROVADA/EXECUTADA."""
    kind = opp["kind"]
    days = RESOLUTION_DAYS.get(kind, 30)
    now = _now()
    out = {
        "id": f"out-{kind}-{uuid.uuid4().hex[:10]}",
        "opp_id": opp["id"],
        "company_id": opp["company_id"],
        "kind": kind,
        "subkind": opp.get("subkind"),
        "playbook": playbook or (opp.get("recommended_action") or {}).get("playbook")
                     or (opp.get("recommended_action") or {}).get("type"),
        "target_type": opp.get("target_type"),
        "target_id": opp.get("target_id"),
        "target_label": opp.get("target_label"),
        "score_pred": opp.get("score"),
        "probability_pred": opp.get("probability"),
        "impact_pred_brl": opp.get("impact_brl"),
        "actor": actor,
        "result": "pending",
        "result_reason": None,
        "roi_real_brl": None,
        "created_at": _iso(now),
        "resolution_due_at": _iso(now + timedelta(days=days)),
        "measured_at": None,
        "evidence_at_open": opp.get("evidence") or {},
    }
    try:
        await db.isabella_outcomes.insert_one(dict(out))
    except Exception as e:
        # Já existe (dedup por opp_id) — não é erro
        existing = await db.isabella_outcomes.find_one({"opp_id": opp["id"]},
                                                         {"_id": 0})
        return existing or {}
    out.pop("_id", None)
    return out


async def _measure_churn(out: Dict[str, Any]) -> Dict[str, Any]:
    """Resultado real: o cliente cancelou após X dias?"""
    sub = await db.subscribers.find_one(
        {"id": out["target_id"]},
        {"_id": 0, "cancellation_date": 1, "contract_status": 1,
         "plan_price": 1})
    if not sub:
        return {"result": "inconclusive",
                "result_reason": "subscriber não encontrado"}
    cancel = sub.get("cancellation_date")
    if cancel and cancel >= out["created_at"]:
        return {"result": "failure",
                "result_reason": f"cliente cancelou em {cancel}",
                "roi_real_brl": -float(out.get("impact_pred_brl") or 0)}
    # ainda ativo após o prazo → retenção bem sucedida
    return {"result": "success",
            "result_reason": "cliente continua ativo após período de risco",
            "roi_real_brl": float(out.get("impact_pred_brl") or 0)}


async def _measure_dunning(out: Dict[str, Any]) -> Dict[str, Any]:
    """Cliente pagou faturas pendentes após a ação?"""
    sub = await db.subscribers.find_one(
        {"id": out["target_id"]}, {"_id": 0, "external_code": 1})
    if not sub:
        return {"result": "inconclusive",
                "result_reason": "subscriber não encontrado"}
    ext = sub.get("external_code", "")
    norm = ext.split("-", 1)[1] if ext.upper().startswith("ATLAZ-") else ext
    # Faturas que existiam na evidência
    invoices = (out.get("evidence_at_open") or {}).get("invoices") or []
    if not invoices:
        return {"result": "inconclusive",
                "result_reason": "sem snapshot de faturas"}
    inv_ids = [i.get("id") for i in invoices if i.get("id")]
    paid = await db.subscriber_invoices.count_documents(
        {"id": {"$in": inv_ids}, "status": "paid"})
    total_due = float((out.get("evidence_at_open") or {}).get("total_due_brl") or 0)
    if paid >= max(1, len(inv_ids) // 2):
        return {"result": "success",
                "result_reason": f"{paid}/{len(inv_ids)} fatura(s) pagas",
                "roi_real_brl": total_due * (paid / max(len(inv_ids), 1))}
    return {"result": "failure",
            "result_reason": f"{paid}/{len(inv_ids)} fatura(s) pagas (<50%)",
            "roi_real_brl": 0.0}


async def _measure_revenue(out: Dict[str, Any]) -> Dict[str, Any]:
    """Cliente fez upgrade após a ação?"""
    sub = await db.subscribers.find_one(
        {"id": out["target_id"]}, {"_id": 0, "plan_price": 1})
    if not sub:
        return {"result": "inconclusive",
                "result_reason": "subscriber não encontrado"}
    open_price = float((out.get("evidence_at_open") or {}).get("current_price") or 0)
    new_price = float(sub.get("plan_price") or 0)
    if new_price > open_price + 5:
        delta = new_price - open_price
        return {"result": "success",
                "result_reason": f"plano subiu de R${open_price:.2f} para R${new_price:.2f}",
                "roi_real_brl": delta * 12}
    return {"result": "failure",
            "result_reason": "plano não alterado dentro da janela",
            "roi_real_brl": 0.0}


async def _measure_twin(out: Dict[str, Any]) -> Dict[str, Any]:
    """A falha prevista realmente aconteceu?"""
    sub = out.get("target_type")
    tid = out.get("target_id")
    cutoff = out["created_at"]
    if sub == "cto":
        n = await db.tickets.count_documents(
            {"company_id": out["company_id"],
             "atlaz_id_ponto": tid,
             "type": {"$in": ["reparo", "ONU_OFFLINE", "ONU_LOW_SIGNAL"]},
             "opened_at": {"$gte": cutoff}})
        if n >= 2:
            return {"result": "success",
                    "result_reason": f"falha confirmada ({n} reparos posteriores)",
                    "roi_real_brl": float(out.get("impact_pred_brl") or 0)}
        return {"result": "failure",
                "result_reason": "previsão sem confirmação (CTO estável)",
                "roi_real_brl": 0.0}
    if sub == "onu":
        o = await db.smartolt_onus.find_one(
            {"sn": tid}, {"_id": 0, "signal_1490": 1, "status": 1})
        if o and (o.get("status") != "Online"
                  or float(o.get("signal_1490") or 0) <= -28):
            return {"result": "success",
                    "result_reason": "ONU continua degradada/offline",
                    "roi_real_brl": float(out.get("impact_pred_brl") or 0)}
        return {"result": "failure",
                "result_reason": "ONU recuperou",
                "roi_real_brl": 0.0}
    return {"result": "inconclusive",
            "result_reason": f"target_type={sub} sem medição automática"}


async def _measure_expansion(out: Dict[str, Any]) -> Dict[str, Any]:
    """Houve conversão de leads na região recomendada?"""
    region = (out.get("target_label") or "").upper()
    if not region:
        return {"result": "inconclusive", "result_reason": "região sem rótulo"}
    n = await db.subscribers.count_documents(
        {"company_id": out["company_id"],
         "activation_date": {"$gte": out["created_at"]},
         "address": {"$regex": region, "$options": "i"}})
    if n >= 1:
        arpu = float((out.get("evidence_at_open") or {}).get("arpu_brl") or 109.9)
        return {"result": "success",
                "result_reason": f"{n} novo(s) cliente(s) na região",
                "roi_real_brl": n * arpu * 12}
    return {"result": "failure",
            "result_reason": "nenhuma nova ativação na região",
            "roi_real_brl": 0.0}


MEASURERS = {
    "churn": _measure_churn,
    "dunning": _measure_dunning,
    "revenue": _measure_revenue,
    "twin": _measure_twin,
    "expansion": _measure_expansion,
}


async def resolve_due(*, force: bool = False,
                       limit: int = 500) -> Dict[str, Any]:
    """Resolve outcomes cujo `resolution_due_at` já passou.
    `force=True` resolve TODOS pending mesmo sem prazo (útil em testes)."""
    now_iso = _iso(_now())
    q: Dict[str, Any] = {"result": "pending"}
    if not force:
        q["resolution_due_at"] = {"$lte": now_iso}
    pending = await db.isabella_outcomes.find(q, {"_id": 0}).limit(limit) \
        .to_list(limit)
    resolved = {"success": 0, "failure": 0, "inconclusive": 0}
    for out in pending:
        measurer = MEASURERS.get(out["kind"])
        if not measurer:
            patch = {"result": "inconclusive",
                      "result_reason": f"sem measurer para kind={out['kind']}"}
        else:
            try:
                patch = await measurer(out)
            except Exception as e:
                patch = {"result": "inconclusive",
                          "result_reason": f"erro: {e}"}
        patch["measured_at"] = _iso(_now())
        await db.isabella_outcomes.update_one(
            {"id": out["id"]}, {"$set": patch})
        resolved[patch.get("result", "inconclusive")] = \
            resolved.get(patch.get("result", "inconclusive"), 0) + 1
        # Atualiza learning engine
        try:
            from services.isabella_learning import record_outcome
            await record_outcome(
                company_id=out["company_id"],
                kind=out["kind"],
                subkind=out.get("subkind") or "",
                playbook=out.get("playbook") or "",
                success=(patch.get("result") == "success"),
                impact_brl=float(patch.get("roi_real_brl") or 0))
        except Exception as e:
            log.warning("[outcome] learning update fail: %s", e)
        await emit_event(
            EventType.AI_OUTCOME,
            company_id=out["company_id"], source="outcome_engine",
            severity="alta" if patch.get("result") == "success" else "media",
            payload={"outcome_id": out["id"], "opp_id": out["opp_id"],
                      "kind": out["kind"], "result": patch.get("result"),
                      "roi_real_brl": patch.get("roi_real_brl")})
    return {"resolved": sum(resolved.values()), **resolved,
            "scanned": len(pending)}


async def stats(company_id: str, *, days: int = 90) -> Dict[str, Any]:
    """Estatísticas de outcome por kind/subkind/playbook."""
    cutoff = _iso(_now() - timedelta(days=days))
    pipe = [
        {"$match": {"company_id": company_id,
                      "created_at": {"$gte": cutoff},
                      "result": {"$ne": "pending"}}},
        {"$group": {
            "_id": {"kind": "$kind", "subkind": "$subkind",
                       "playbook": "$playbook"},
            "n_total": {"$sum": 1},
            "n_success": {"$sum": {"$cond": [
                {"$eq": ["$result", "success"]}, 1, 0]}},
            "n_failure": {"$sum": {"$cond": [
                {"$eq": ["$result", "failure"]}, 1, 0]}},
            "n_inconclusive": {"$sum": {"$cond": [
                {"$eq": ["$result", "inconclusive"]}, 1, 0]}},
            "roi_real_sum": {"$sum": "$roi_real_brl"},
            "impact_pred_sum": {"$sum": "$impact_pred_brl"},
        }},
        {"$sort": {"n_total": -1}},
    ]
    rows = await db.isabella_outcomes.aggregate(pipe).to_list(500)
    out: List[Dict[str, Any]] = []
    totals = {"n_total": 0, "n_success": 0, "n_failure": 0,
                "roi_real": 0.0, "impact_pred": 0.0}
    for r in rows:
        n = r["n_total"]
        s = r["n_success"]
        out.append({
            **r["_id"],
            "n_total": n, "n_success": s,
            "n_failure": r["n_failure"],
            "n_inconclusive": r["n_inconclusive"],
            "success_rate": round(s / max(n, 1), 4),
            "roi_real_brl": round(float(r.get("roi_real_sum") or 0), 2),
            "impact_pred_brl": round(float(r.get("impact_pred_sum") or 0), 2),
            "precision": round(float(r.get("roi_real_sum") or 0)
                                / max(float(r.get("impact_pred_sum") or 1), 1), 4),
        })
        totals["n_total"] += n
        totals["n_success"] += s
        totals["n_failure"] += r["n_failure"]
        totals["roi_real"] += float(r.get("roi_real_sum") or 0)
        totals["impact_pred"] += float(r.get("impact_pred_sum") or 0)
    totals["success_rate"] = round(totals["n_success"]
                                    / max(totals["n_total"], 1), 4)
    totals["precision"] = round(totals["roi_real"]
                                  / max(totals["impact_pred"], 1), 4)
    return {"company_id": company_id, "window_days": days,
            "totals": totals, "by_playbook": out}
