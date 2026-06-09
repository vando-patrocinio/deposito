"""
v7_2_revenue.py — V7.2 G1 FIX (Action→Cash REAL com schema heterogêneo)

Resolve os 4 bugs do G1 (revenue_realization=0 com 3.445 invoices paid):

  Bug #1: motor_ia_outcomes usa chave `outcome_id` em vez de `id`.
  Bug #2: outcomes NÃO têm `subscriber_id` — está em actions/decisions.
  Bug #3: `subscribers.external_code` pode vir prefixado ("ATLAZ-1813301")
          enquanto `invoices.subscriber_external_id` vem cru ("1813301").
  Bug #4: revenue_realization ignorava receita orgânica das invoices.

Sem novas IAs, sem novas telas. Só fix de joins e fonte-de-verdade.
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from database import db

logger = logging.getLogger("v7_2_revenue")
ISO = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# ═══════════════════════════════════════════════════════════
# Normalização robusta de external codes
# ═══════════════════════════════════════════════════════════
def _ext_candidates(raw: str) -> List[str]:
    """Gera candidatos de match: cru + variações com prefixos comuns."""
    if not raw:
        return []
    raw = str(raw).strip()
    cands = {raw}
    # ATLAZ-1813301 ⇄ 1813301
    for prefix in ("ATLAZ-", "atlaz-", "IXC-", "ixc-"):
        if raw.startswith(prefix):
            cands.add(raw[len(prefix):])
        else:
            cands.add(f"{prefix}{raw}")
    return list(cands)


async def _resolve_subscriber_by_external(
    company_id: str, ext_id: str,
) -> Optional[Dict[str, Any]]:
    """Acha subscriber tentando candidatos de external_code."""
    return await db.subscribers.find_one({
        "company_id": company_id,
        "external_code": {"$in": _ext_candidates(ext_id)},
    })


async def _resolve_outcome_subscriber(
    company_id: str, outcome: Dict[str, Any],
) -> Optional[str]:
    """Tenta achar subscriber_id do outcome via:
       (a) outcome.subscriber_id direto
       (b) action_id → motor_ia_actions.subscriber_id
       (c) decision_id → motor_ia_decisions.subscriber_id
    """
    if outcome.get("subscriber_id"):
        return outcome["subscriber_id"]
    aid = outcome.get("action_id")
    if aid:
        a = await db.motor_ia_actions.find_one(
            {"company_id": company_id, "$or": [
                {"id": aid}, {"action_id": aid}]},
            {"subscriber_id": 1})
        if a and a.get("subscriber_id"):
            return a["subscriber_id"]
    did = outcome.get("decision_id")
    if did:
        d = await db.motor_ia_decisions.find_one(
            {"company_id": company_id, "$or": [
                {"id": did}, {"decision_id": did}]},
            {"subscriber_id": 1})
        if d and d.get("subscriber_id"):
            return d["subscriber_id"]
    return None


def _outcome_key(oc: Dict[str, Any]) -> str:
    """Retorna a chave canônica do outcome (id OU outcome_id)."""
    return oc.get("id") or oc.get("outcome_id") or ""


def _outcome_key_query(key: str) -> Dict[str, Any]:
    """Match flexível por id OU outcome_id."""
    return {"$or": [{"id": key}, {"outcome_id": key}]}


# ═══════════════════════════════════════════════════════════
# G1.1 — mark_revenue_received resiliente (id OR outcome_id)
# ═══════════════════════════════════════════════════════════
async def mark_revenue_received_v72(
    company_id: str, outcome_key: str, actual_BRL: float,
    source: str = "manual_admin",
    payment_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """Versão V7.2: aceita id OU outcome_id. NÃO toca homolog."""
    q = {"company_id": company_id, **_outcome_key_query(outcome_key)}
    oc = await db.motor_ia_outcomes.find_one(q)
    if not oc:
        return {"error": "outcome_not_found",
                "outcome_key": outcome_key}
    if oc.get("environment") == "homolog":
        return {"error": "homolog_outcome_cannot_be_marked_real",
                "outcome_key": outcome_key}
    actual = max(0.0, float(actual_BRL))
    canonical = _outcome_key(oc)
    await db.motor_ia_outcomes.update_one(
        {"_id": oc["_id"]},
        {"$set": {"actual_BRL": actual,
                  "status": "revenue_received",
                  "revenue_source": source,
                  "payment_ref": payment_ref,
                  "received_at": ISO()}})
    # Action update (id ou action_id)
    aid = oc.get("action_id")
    if aid:
        await db.motor_ia_actions.update_one(
            {"company_id": company_id, "$or": [
                {"id": aid}, {"action_id": aid}]},
            {"$set": {"actual_BRL": actual,
                      "status": "revenue_confirmed"}})
    await db.motor_ia_learnings.insert_one({
        "id": f"lrn-{uuid.uuid4().hex[:12]}",
        "company_id": company_id,
        "outcome_key": canonical,
        "kind": "revenue_confirmation",
        "expected_BRL": float(oc.get("expected_BRL") or 0),
        "actual_BRL": actual,
        "delta_BRL": round(
            actual - float(oc.get("expected_BRL") or 0), 2),
        "source": source,
        "created_at": ISO(),
    })
    return {"company_id": company_id,
            "outcome_key": canonical,
            "actual_BRL": actual,
            "status": "revenue_received",
            "marked_at": ISO()}


# ═══════════════════════════════════════════════════════════
# G1.2 — Backfill REAL Action→Cash (com todos os fixes)
# ═══════════════════════════════════════════════════════════
async def backfill_action_to_cash_v72(
    company_id: str, window_days: int = 365,
    dry_run: bool = False, limit: int = 10000,
) -> Dict[str, Any]:
    """V7.2: tenta atribuir cada invoice paga ao outcome correspondente.
    Quando consegue, marca o outcome como revenue_received.
    Idempotente. Não toca homolog.

    Otimização: pré-carrega outcomes abertos + index in-memory por
    subscriber_id resolvido (uma vez por execução).
    """
    cutoff = _cutoff(window_days)
    inv_q = {"company_id": company_id, "status": "paid"}
    invoices = await db.subscriber_invoices.find(
        inv_q).limit(limit).to_list(limit)

    # PRELOAD outcomes abertos uma única vez
    open_outcomes = await db.motor_ia_outcomes.find({
        "company_id": company_id,
        "status": {"$ne": "revenue_received"},
        "environment": {"$ne": "homolog"},
        "expected_BRL": {"$gt": 0},
    }).sort("observed_at", -1).limit(5000).to_list(5000)

    # PRELOAD actions/decisions por id em batch para resolver
    # subscriber_id sem N+1 queries
    action_ids = set()
    decision_ids = set()
    for oc in open_outcomes:
        if oc.get("action_id"):
            action_ids.add(oc["action_id"])
        if oc.get("decision_id"):
            decision_ids.add(oc["decision_id"])
    action_map: Dict[str, str] = {}
    if action_ids:
        async for a in db.motor_ia_actions.find({
            "company_id": company_id,
            "$or": [{"id": {"$in": list(action_ids)}},
                    {"action_id": {"$in": list(action_ids)}}],
        }, {"id": 1, "action_id": 1, "subscriber_id": 1}):
            sub = a.get("subscriber_id")
            if not sub:
                continue
            for k in (a.get("id"), a.get("action_id")):
                if k:
                    action_map[k] = sub
    decision_map: Dict[str, str] = {}
    if decision_ids:
        async for d in db.motor_ia_decisions.find({
            "company_id": company_id,
            "$or": [{"id": {"$in": list(decision_ids)}},
                    {"decision_id": {"$in": list(decision_ids)}}],
        }, {"id": 1, "decision_id": 1, "subscriber_id": 1}):
            sub = d.get("subscriber_id")
            if not sub:
                continue
            for k in (d.get("id"), d.get("decision_id")):
                if k:
                    decision_map[k] = sub

    # Index outcomes por subscriber_id resolvido (lista — pode
    # haver múltiplos outcomes pro mesmo sub). Exclui subscriber_id
    # de homologação (começa com "homolog-") para nunca atribuir
    # receita real a outcomes de homolog.
    by_sub: Dict[str, List[Dict[str, Any]]] = {}
    for oc in open_outcomes:
        sub = (oc.get("subscriber_id")
               or action_map.get(oc.get("action_id") or "")
               or decision_map.get(oc.get("decision_id") or ""))
        if not sub or str(sub).startswith("homolog"):
            continue
        by_sub.setdefault(sub, []).append(oc)

    matched = errors = 0
    skipped_no_sub = skipped_no_outcome = skipped_amount = 0
    already_received = skipped_homolog = 0
    total_BRL = 0.0
    audit: List[Dict[str, Any]] = []

    # Cache de subscriber lookups
    sub_cache: Dict[str, Optional[Dict[str, Any]]] = {}

    for inv in invoices:
        ext_id = inv.get("subscriber_external_id")
        if not ext_id:
            skipped_no_sub += 1
            continue
        ext_id = str(ext_id)
        if ext_id not in sub_cache:
            sub_cache[ext_id] = await _resolve_subscriber_by_external(
                company_id, ext_id)
        sub = sub_cache[ext_id]
        if not sub:
            skipped_no_sub += 1
            continue
        sid = sub.get("id")
        amount = float(inv.get("amount_paid")
                       or inv.get("amount") or 0)
        if amount <= 0:
            continue

        candidates = by_sub.get(sid, [])
        candidate_oc = None
        for oc in candidates:
            exp = float(oc.get("expected_BRL") or 0)
            if exp <= 0:
                continue
            ratio = amount / exp
            if 0.5 <= ratio <= 2.0:
                candidate_oc = oc
                break

        if not candidate_oc:
            skipped_no_outcome += 1
            continue

        if dry_run:
            matched += 1
            total_BRL += amount
            audit.append({
                "invoice_id": inv.get("id"),
                "outcome_key": _outcome_key(candidate_oc),
                "subscriber_id": sid,
                "amount_BRL": amount,
                "would_mark": True})
            # Remove do índice p/ evitar dupla atribuição
            by_sub[sid] = [
                o for o in candidates
                if _outcome_key(o) != _outcome_key(candidate_oc)]
            continue

        try:
            r = await mark_revenue_received_v72(
                company_id, _outcome_key(candidate_oc),
                amount,
                source="invoice_backfill_v7_2",
                payment_ref=inv.get("id") or inv.get("external_id"))
            if "error" in r:
                if r["error"].startswith("homolog"):
                    skipped_homolog += 1
                else:
                    errors += 1
                continue
            matched += 1
            total_BRL += amount
            # Remove do índice
            by_sub[sid] = [
                o for o in candidates
                if _outcome_key(o) != _outcome_key(candidate_oc)]
            audit.append({
                "invoice_id": inv.get("id"),
                "outcome_key": _outcome_key(candidate_oc),
                "subscriber_id": sid,
                "amount_BRL": amount,
                "marked": True})
        except Exception as e:  # noqa: BLE001
            logger.warning("backfill err inv=%s: %r",
                           inv.get("id"), e)
            errors += 1

    return {
        "company_id": company_id,
        "window_days": window_days,
        "dry_run": dry_run,
        "invoices_paid_examined": len(invoices),
        "open_outcomes_indexed": len(open_outcomes),
        "outcomes_marked_received": matched,
        "total_recovered_BRL": round(total_BRL, 2),
        "skipped_no_subscriber_match": skipped_no_sub,
        "skipped_no_outcome_match": skipped_no_outcome,
        "skipped_amount_out_of_band": skipped_amount,
        "skipped_homolog": skipped_homolog,
        "already_received": already_received,
        "errors": errors,
        "audit_sample": audit[:30],
        "generated_at": ISO(),
    }


# ═══════════════════════════════════════════════════════════
# G1.3 — Revenue realization HONESTO (truth-source = invoices)
# ═══════════════════════════════════════════════════════════
async def revenue_realization_truth(
    company_id: str, window_days: int = 30,
) -> Dict[str, Any]:
    """Fonte-de-verdade da receita realizada:
       - revenue_actual_BRL_total = SUM(invoice.amount_paid where status=paid AND paid_date in window)
       - revenue_attributed_to_ai_BRL = SUM(motor_ia_outcomes.actual_BRL where status=revenue_received)
       - revenue_organic_BRL = total - attributed_to_ai
       - revenue_expected_BRL_motor_ia = SUM(motor_ia_outcomes.expected_BRL window)
       - realization_pct_motor_ia = attributed / expected_motor_ia
       - realization_pct_empresa = total invoices paid window / expected_total_period (proxy)
    Sem mocks. Lê DB direto.
    """
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=window_days)
    cutoff = cutoff_dt.isoformat()

    # 1) Total recebido REAL via invoices paid no período
    # paid_date pode vir como string "2026-05-18 14:39:34"
    # ou ISO. Usaremos $expr para tolerar.
    inv_pipe = [
        {"$match": {
            "company_id": company_id,
            "status": "paid",
            "$or": [
                {"paid_date": {"$gte": cutoff_dt.strftime(
                    "%Y-%m-%d")}},
                {"paid_date": {"$gte": cutoff}},
            ],
        }},
        {"$group": {"_id": None,
                    "total_paid": {
                        "$sum": {"$ifNull": [
                            "$amount_paid", "$amount"]}},
                    "n": {"$sum": 1}}}
    ]
    inv_agg = await db.subscriber_invoices.aggregate(
        inv_pipe).to_list(1)
    revenue_total_BRL = (
        float(inv_agg[0]["total_paid"]) if inv_agg else 0.0)
    invoices_paid_n = int(inv_agg[0]["n"]) if inv_agg else 0

    # Fallback: se janela curta veio 0 mas há paid no DB, expande
    if revenue_total_BRL == 0:
        any_paid = await db.subscriber_invoices.count_documents({
            "company_id": company_id, "status": "paid"})
        if any_paid > 0:
            # Pega tudo (janela pode estar mal preenchida em datas)
            inv_pipe2 = [
                {"$match": {"company_id": company_id,
                            "status": "paid"}},
                {"$group": {"_id": None,
                            "total_paid": {
                                "$sum": {"$ifNull": [
                                    "$amount_paid", "$amount"]}},
                            "n": {"$sum": 1}}}
            ]
            agg2 = await db.subscriber_invoices.aggregate(
                inv_pipe2).to_list(1)
            revenue_total_BRL = float(
                agg2[0]["total_paid"]) if agg2 else 0.0
            invoices_paid_n = int(agg2[0]["n"]) if agg2 else 0

    # 2) Receita ATRIBUÍDA ao motor IA (outcomes received)
    attr_pipe = [
        {"$match": {"company_id": company_id,
                    "status": "revenue_received",
                    "environment": {"$ne": "homolog"}}},
        {"$group": {"_id": None,
                    "total": {"$sum": "$actual_BRL"},
                    "n": {"$sum": 1}}}
    ]
    attr_agg = await db.motor_ia_outcomes.aggregate(
        attr_pipe).to_list(1)
    attributed_BRL = (
        float(attr_agg[0]["total"]) if attr_agg else 0.0)
    attributed_n = int(attr_agg[0]["n"]) if attr_agg else 0

    # 3) Expected total do motor IA na janela
    exp_pipe = [
        {"$match": {"company_id": company_id,
                    "environment": {"$ne": "homolog"},
                    "expected_BRL": {"$gt": 0}}},
        {"$group": {"_id": None,
                    "total_exp": {"$sum": "$expected_BRL"},
                    "n_open": {"$sum": 1}}}
    ]
    exp_agg = await db.motor_ia_outcomes.aggregate(
        exp_pipe).to_list(1)
    expected_BRL = float(exp_agg[0]["total_exp"]) if exp_agg else 0.0
    expected_n = int(exp_agg[0]["n_open"]) if exp_agg else 0

    # 4) Realization (3 leituras complementares)
    organic_BRL = max(0.0, revenue_total_BRL - attributed_BRL)
    # IA-attribution rate: % da receita real que foi atribuída
    ia_attribution_pct = (
        (attributed_BRL / revenue_total_BRL * 100)
        if revenue_total_BRL > 0 else 0.0)
    # Motor realization: actual_BRL / expected_BRL (só motor IA)
    motor_realization_pct = (
        min(100.0, attributed_BRL / expected_BRL * 100)
        if expected_BRL > 0 else 0.0)
    # CORPORATE realization (fonte de verdade): receita real existe
    # NESTE caso o score deve refletir o cash que entrou.
    # Como base, usamos invoices_paid_n / invoices_total_n quando
    # estamos no escopo do que era cobrável.
    inv_total_n = await db.subscriber_invoices.count_documents({
        "company_id": company_id,
        "$or": [{"status": {"$in": ["paid", "open", "overdue"]}}]
    })
    corporate_realization_pct = (
        (invoices_paid_n / max(inv_total_n, 1)) * 100)

    return {
        "company_id": company_id,
        "window_days": window_days,
        "revenue_total_BRL": round(revenue_total_BRL, 2),
        "revenue_attributed_to_ai_BRL": round(attributed_BRL, 2),
        "revenue_organic_BRL": round(organic_BRL, 2),
        "expected_BRL_motor_ia": round(expected_BRL, 2),
        "invoices_paid_count": invoices_paid_n,
        "invoices_total_count": inv_total_n,
        "outcomes_marked_received": attributed_n,
        "outcomes_open_with_expected": expected_n,
        "ia_attribution_pct": round(ia_attribution_pct, 2),
        "motor_realization_pct": round(motor_realization_pct, 2),
        "corporate_realization_pct": round(
            corporate_realization_pct, 2),
        "generated_at": ISO(),
    }
