"""
v8_3_causality.py — V8.3 INFRAESTRUTURA DE CAUSALIDADE + EVIDÊNCIA FINANCEIRA

3 frentes (sem novas IAs/dashboards/scores/twins):

  FRENTE 1 — Expansão de evidência financeira:
    batch_revenue_validation()  : varre invoices paid e classifica
                                  ATTRIBUTED / NOT_ATTRIBUTED
    calibrate_expected_brl()    : audita operacao_tese_tier_c com
                                  expected=0 e sugere valor médio

  FRENTE 2 — Infraestrutura de causalidade (sem WA real):
    Cohort Tracker      : grupos treatment/control persistidos
    Attribution Window  : janelas 7d/14d/30d
    Lift Calculator     : lift = rate_t / rate_c (matemática pura)
    A/B Logger          : auditoria entrada/saída/pagamento

  FRENTE 3 — Dry run:
    run_pilot(dry_run=True) : valida pipeline com 100 sintéticos
                              sem tocar cliente real.

Coleções usadas (já existentes ou criadas idempotentemente):
  motor_ia_cohorts (NEW)        : cohort_id + group + member subscriber
  motor_ia_cohort_members (NEW) : individual + paid_status snapshot
  + motor_ia_outcomes, motor_ia_actions, subscriber_invoices (existem)
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

import math
import random
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from database import db

logger = logging.getLogger("v8_3_causality")
ISO = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731


def _id(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:12]}"


def _parse_dt(s: Any) -> Optional[datetime]:
    if not s:
        return None
    if isinstance(s, datetime):
        dt = s
    else:
        try:
            dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except Exception:
            try:
                dt = datetime.strptime(str(s)[:19],
                                       "%Y-%m-%d %H:%M:%S")
            except Exception:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ═══════════════════════════════════════════════════════════
# FRENTE 1.A — batch_revenue_validation
# ═══════════════════════════════════════════════════════════
async def batch_revenue_validation(
    company_id: str, limit: int = 5000,
) -> Dict[str, Any]:
    """Varre invoices PAID e classifica relação com motor IA.

    ATTRIBUTED      : existe action/outcome com subscriber_id que
                      casa com o invoice, dentro de janela plausível
                      (action.executed_at <= invoice.paid_date <=
                       action.executed_at + 30d).
    NOT_ATTRIBUTED  : invoice pago mas sem evidência de ação prévia.

    NÃO inventa causalidade. Só audita evidências disponíveis.
    """
    invoices = await db.subscriber_invoices.find({
        "company_id": company_id, "status": "paid",
    }).limit(limit).to_list(limit)

    # Pré-carrega actions executadas (uma única vez)
    actions = await db.motor_ia_actions.find({
        "company_id": company_id,
        "status": {"$in": ["executed", "done",
                           "revenue_confirmed"]},
        "subscriber_id": {"$exists": True, "$nin": [None, ""]},
    }, {"id": 1, "action_id": 1, "subscriber_id": 1,
        "executed_at": 1, "created_at": 1, "kind": 1,
        "expected_BRL": 1}).to_list(20000)

    # Index por subscriber_id (resolved) para lookups O(1)
    by_sub: Dict[str, List[Dict[str, Any]]] = {}
    for a in actions:
        sid = a.get("subscriber_id")
        if not sid or str(sid).startswith("homolog"):
            continue
        by_sub.setdefault(sid, []).append(a)

    attributed = not_attributed = no_sub_match = 0
    sum_attributed = sum_not_attributed = 0.0
    by_kind: Dict[str, Dict[str, Any]] = {}
    sample_attr: List[Dict[str, Any]] = []

    for inv in invoices:
        ext = inv.get("subscriber_external_id")
        amount = float(inv.get("amount_paid")
                       or inv.get("amount") or 0)
        if amount <= 0 or not ext:
            no_sub_match += 1
            continue
        # Resolve subscriber (mesmo padrão V7.2)
        from services.v7_2_revenue import _ext_candidates
        sub = await db.subscribers.find_one({
            "company_id": company_id,
            "external_code": {"$in": _ext_candidates(ext)},
        }, {"id": 1})
        if not sub:
            no_sub_match += 1
            continue
        sid = sub["id"]
        candidates = by_sub.get(sid, [])
        if not candidates:
            not_attributed += 1
            sum_not_attributed += amount
            continue
        # Janela: action.executed_at <= paid_date <= +30d
        paid_dt = _parse_dt(inv.get("paid_date"))
        match = None
        for a in candidates:
            a_dt = (_parse_dt(a.get("executed_at"))
                    or _parse_dt(a.get("created_at")))
            if not a_dt or not paid_dt:
                continue
            if a_dt <= paid_dt <= (a_dt + timedelta(days=30)):
                match = a
                break
        if match:
            attributed += 1
            sum_attributed += amount
            k = match.get("kind") or "unknown"
            by_kind.setdefault(k, {"n": 0, "BRL": 0.0})
            by_kind[k]["n"] += 1
            by_kind[k]["BRL"] += amount
            if len(sample_attr) < 10:
                sample_attr.append({
                    "invoice_id": inv.get("id"),
                    "subscriber_id_redacted":
                        sid[:8] + "***" + sid[-4:],
                    "amount_BRL": amount,
                    "action_kind": k,
                    "days_between":
                        (paid_dt - (_parse_dt(
                            match.get("executed_at")
                            or match.get("created_at")) or paid_dt)
                         ).days})
        else:
            not_attributed += 1
            sum_not_attributed += amount

    total = attributed + not_attributed + no_sub_match
    tkt_attr = (sum_attributed / max(attributed, 1)
                if attributed else 0)
    tkt_not = (sum_not_attributed / max(not_attributed, 1)
               if not_attributed else 0)

    return {
        "company_id": company_id,
        "invoices_examined": total,
        "attributed": {
            "n": attributed,
            "sum_BRL": round(sum_attributed, 2),
            "avg_ticket_BRL": round(tkt_attr, 2),
            "by_kind": {k: {"n": v["n"],
                            "sum_BRL": round(v["BRL"], 2)}
                        for k, v in by_kind.items()},
            "sample": sample_attr,
        },
        "not_attributed": {
            "n": not_attributed,
            "sum_BRL": round(sum_not_attributed, 2),
            "avg_ticket_BRL": round(tkt_not, 2),
        },
        "no_subscriber_match": no_sub_match,
        "generated_at": ISO(),
    }


# ═══════════════════════════════════════════════════════════
# FRENTE 1.B — calibrate_expected_brl
# ═══════════════════════════════════════════════════════════
async def calibrate_expected_brl(
    company_id: str,
) -> Dict[str, Any]:
    """Auditoria de motor_ia_actions.kind=operacao_tese_tier_c
    com expected_BRL=0. Sugere valor médio baseado em invoices
    pagas dos mesmos subscribers (se houver) OU media global."""
    zero_actions = await db.motor_ia_actions.find({
        "company_id": company_id,
        "kind": "operacao_tese_tier_c",
        "$or": [{"expected_BRL": 0},
                {"expected_BRL": None},
                {"expected_BRL": {"$exists": False}}],
    }).to_list(10000)
    n_zero = len(zero_actions)

    # Média global de invoices PAID
    paid_avg = await db.subscriber_invoices.aggregate([
        {"$match": {"company_id": company_id, "status": "paid",
                    "amount_paid": {"$gt": 0}}},
        {"$group": {"_id": None,
                    "avg": {"$avg": "$amount_paid"},
                    "n": {"$sum": 1}}}
    ]).to_list(1)
    avg_paid = (float(paid_avg[0]["avg"])
                if paid_avg else 0.0)

    # Tentar sugerir valor por subscriber_id (média de faturas
    # dele) e fallback para média global
    per_sub_suggestions: List[Dict[str, Any]] = []
    suggested_sum = 0.0
    suggested_per_sub = {}
    for a in zero_actions:
        sid = a.get("subscriber_id")
        if not sid:
            per_sub_suggestions.append({
                "action_id": a.get("id"),
                "suggested_BRL": round(avg_paid, 2),
                "source": "global_avg"})
            suggested_sum += avg_paid
            continue
        # Cache simples
        if sid in suggested_per_sub:
            val = suggested_per_sub[sid]
            src = "per_sub_cached"
        else:
            agg = await db.subscriber_invoices.aggregate([
                {"$match": {"company_id": company_id,
                            "subscriber_external_id":
                                {"$exists": True},
                            "status": "paid"}},
                {"$group": {"_id": None,
                            "avg": {"$avg": "$amount_paid"}}}
            ]).to_list(1)
            val = (float(agg[0]["avg"]) if agg else avg_paid)
            suggested_per_sub[sid] = val
            src = "per_subscriber_avg"
        per_sub_suggestions.append({
            "action_id": a.get("id"),
            "suggested_BRL": round(val, 2),
            "source": src})
        suggested_sum += val

    return {
        "company_id": company_id,
        "zero_expected_count": n_zero,
        "global_avg_paid_BRL": round(avg_paid, 2),
        "estimated_total_uplift_BRL": round(suggested_sum, 2),
        "sample_suggestions": per_sub_suggestions[:10],
        "generated_at": ISO(),
        "advisory_only": True,  # NÃO altera produção
    }


# ═══════════════════════════════════════════════════════════
# FRENTE 2 — INFRAESTRUTURA DE CAUSALIDADE
# ═══════════════════════════════════════════════════════════

# ───── A/B Logger + Cohort Tracker (mesma coleção) ─────
async def create_cohort(
    company_id: str, label: str,
    treatment_subscriber_ids: List[str],
    control_subscriber_ids: List[str],
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Cria coorte com grupos treatment/control. Idempotente
    por (company_id, label)."""
    cohort_id = f"cohort-{label}-{uuid.uuid4().hex[:8]}"
    now = ISO()
    cohort_doc = {
        "id": cohort_id, "cohort_id": cohort_id,
        "company_id": company_id, "label": label,
        "size_treatment": len(treatment_subscriber_ids),
        "size_control": len(control_subscriber_ids),
        "metadata": metadata or {},
        "status": "open",
        "created_at": now,
    }
    await db.motor_ia_cohorts.update_one(
        {"company_id": company_id, "label": label},
        {"$setOnInsert": cohort_doc}, upsert=True)
    # Re-lê (pode já existir)
    cohort = await db.motor_ia_cohorts.find_one(
        {"company_id": company_id, "label": label})
    cohort_id = cohort["id"]

    members = []
    for sid in treatment_subscriber_ids:
        members.append({
            "id": _id("cm"),
            "cohort_id": cohort_id,
            "company_id": company_id,
            "subscriber_id": sid, "group": "treatment",
            "entered_at": now,
            "exited_at": None,
            "paid_within_window": False,
            "paid_amount_BRL": 0.0,
            "paid_at": None,
        })
    for sid in control_subscriber_ids:
        members.append({
            "id": _id("cm"),
            "cohort_id": cohort_id,
            "company_id": company_id,
            "subscriber_id": sid, "group": "control",
            "entered_at": now,
            "exited_at": None,
            "paid_within_window": False,
            "paid_amount_BRL": 0.0,
            "paid_at": None,
        })
    # Upsert por (cohort_id, subscriber_id) — idempotente
    for m in members:
        await db.motor_ia_cohort_members.update_one(
            {"cohort_id": cohort_id,
             "subscriber_id": m["subscriber_id"]},
            {"$setOnInsert": m}, upsert=True)

    return cohort


# ───── Attribution Window ─────
async def compute_attribution(
    cohort_id: str, window_days: int = 14,
) -> Dict[str, Any]:
    """Para cada membro do cohort, varre subscriber_invoices
    PAID entre entered_at e entered_at+window_days. Atualiza
    paid_within_window. Não envia mensagem."""
    cohort = await db.motor_ia_cohorts.find_one(
        {"id": cohort_id})
    if not cohort:
        return {"error": "cohort_not_found"}
    co = cohort["company_id"]
    updated = 0
    async for m in db.motor_ia_cohort_members.find(
            {"cohort_id": cohort_id}):
        if m.get("paid_within_window"):
            continue
        entered = _parse_dt(m["entered_at"])
        if not entered:
            continue
        end = entered + timedelta(days=window_days)
        # Busca invoice paga do subscriber nessa janela
        sub = await db.subscribers.find_one(
            {"id": m["subscriber_id"]}, {"external_code": 1})
        if not sub:
            continue
        from services.v7_2_revenue import _ext_candidates
        cands = _ext_candidates(sub.get("external_code") or "")
        # Strip prefix versions também
        if sub.get("external_code") and "-" in str(
                sub["external_code"]):
            cands.append(str(sub["external_code"]).split("-", 1)[1])
        # Procura PAID nesse subscriber
        inv = None
        async for x in db.subscriber_invoices.find({
            "company_id": co, "status": "paid",
            "subscriber_external_id": {"$in": cands},
        }):
            paid_dt = _parse_dt(x.get("paid_date"))
            if paid_dt and entered <= paid_dt <= end:
                inv = x
                break
        if inv:
            await db.motor_ia_cohort_members.update_one(
                {"id": m["id"]},
                {"$set": {
                    "paid_within_window": True,
                    "paid_amount_BRL": float(
                        inv.get("amount_paid") or 0),
                    "paid_at": inv.get("paid_date"),
                    "exited_at": ISO(),
                    "invoice_id": inv.get("id"),
                }})
            updated += 1
    return {"cohort_id": cohort_id,
            "window_days": window_days,
            "members_marked_paid": updated,
            "generated_at": ISO()}


# ───── Lift Calculator (matemática pura) ─────
def _wilson_ci(k: int, n: int, z: float = 1.96
               ) -> Tuple[float, float]:
    """Intervalo de confiança Wilson para proporção (~95% com z=1.96)."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    spread = (z * math.sqrt(p * (1 - p) / n
                             + z * z / (4 * n * n)) / denom)
    return max(0.0, centre - spread), min(1.0, centre + spread)


async def compute_lift(cohort_id: str) -> Dict[str, Any]:
    """Calcula lift = rate_treatment / rate_control. Sem IA."""
    t_total = await db.motor_ia_cohort_members.count_documents(
        {"cohort_id": cohort_id, "group": "treatment"})
    c_total = await db.motor_ia_cohort_members.count_documents(
        {"cohort_id": cohort_id, "group": "control"})
    t_paid = await db.motor_ia_cohort_members.count_documents(
        {"cohort_id": cohort_id, "group": "treatment",
         "paid_within_window": True})
    c_paid = await db.motor_ia_cohort_members.count_documents(
        {"cohort_id": cohort_id, "group": "control",
         "paid_within_window": True})
    rate_t = t_paid / max(t_total, 1)
    rate_c = c_paid / max(c_total, 1)
    abs_lift = rate_t - rate_c
    pct_lift = ((rate_t - rate_c) / rate_c * 100) if rate_c > 0 \
        else (100.0 if rate_t > 0 else 0.0)
    # IC 95% Wilson para cada taxa
    ci_t = _wilson_ci(t_paid, t_total)
    ci_c = _wilson_ci(c_paid, c_total)
    # Confiança simples: ICs não se sobrepõem ⇒ "high",
    # tangenciam ⇒ "medium", overlap forte ⇒ "low"
    overlap = max(0.0, min(ci_t[1], ci_c[1])
                  - max(ci_t[0], ci_c[0]))
    if overlap == 0 and abs_lift > 0:
        conf = "high"
    elif overlap < 0.05 and abs_lift > 0:
        conf = "medium"
    elif abs_lift > 0:
        conf = "low"
    else:
        conf = "none"
    # Σ BRL realizado pelo treatment vs control
    t_brl_agg = await db.motor_ia_cohort_members.aggregate([
        {"$match": {"cohort_id": cohort_id,
                    "group": "treatment",
                    "paid_within_window": True}},
        {"$group": {"_id": None,
                    "total": {"$sum": "$paid_amount_BRL"}}}
    ]).to_list(1)
    c_brl_agg = await db.motor_ia_cohort_members.aggregate([
        {"$match": {"cohort_id": cohort_id,
                    "group": "control",
                    "paid_within_window": True}},
        {"$group": {"_id": None,
                    "total": {"$sum": "$paid_amount_BRL"}}}
    ]).to_list(1)
    t_brl = float(t_brl_agg[0]["total"]) if t_brl_agg else 0.0
    c_brl = float(c_brl_agg[0]["total"]) if c_brl_agg else 0.0
    return {
        "cohort_id": cohort_id,
        "treatment": {
            "n": t_total, "paid_n": t_paid,
            "payment_rate": round(rate_t, 4),
            "ci95_wilson": [round(ci_t[0], 4),
                            round(ci_t[1], 4)],
            "sum_paid_BRL": round(t_brl, 2),
        },
        "control": {
            "n": c_total, "paid_n": c_paid,
            "payment_rate": round(rate_c, 4),
            "ci95_wilson": [round(ci_c[0], 4),
                            round(ci_c[1], 4)],
            "sum_paid_BRL": round(c_brl, 2),
        },
        "lift_absolute": round(abs_lift, 4),
        "lift_pct": round(pct_lift, 2),
        "ci_overlap": round(overlap, 4),
        "confidence_simple": conf,
        "incremental_revenue_BRL_estimate":
            round(t_brl - c_brl, 2),
        "generated_at": ISO(),
    }


# ═══════════════════════════════════════════════════════════
# FRENTE 3 — DRY RUN PILOTO
# ═══════════════════════════════════════════════════════════
async def run_pilot(
    company_id: str = "co-causality-pilot",
    n_treatment: int = 50, n_control: int = 50,
    treatment_payment_rate: float = 0.58,
    control_payment_rate: float = 0.32,
    avg_amount: float = 95.0,
    window_days: int = 14,
    dry_run: bool = True,
    cleanup: bool = True,
) -> Dict[str, Any]:
    """Valida toda a infra causal com dados sintéticos.

    - Cria N treatment + N control subscribers + invoices simulados
    - Simula taxa de pagamento DIFERENTE entre grupos
    - Calcula lift
    - Retorna trace completo

    `dry_run=True` (default): roda no company_id de pilot dedicado.
    `cleanup=True`: deleta dados sintéticos ao fim.
    """
    label = f"pilot-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    t_subs: List[str] = []
    c_subs: List[str] = []
    inserted_invoices: List[str] = []
    inserted_subs: List[str] = []

    try:
        # Cria subscribers sintéticos
        for i in range(n_treatment + n_control):
            sid = f"sub-causality-{label}-{i:04d}"
            ext = f"CAUSAL-{label}-{i:04d}"
            await db.subscribers.update_one(
                {"id": sid}, {"$setOnInsert": {
                    "id": sid, "company_id": company_id,
                    "external_code": ext, "name":
                    f"SYNTHETIC_{i}",
                    "phone": "5521998176526",  # TEST_PHONE
                    "status": "active",
                    "synthetic_v8_3": True}},
                upsert=True)
            inserted_subs.append(sid)
            if i < n_treatment:
                t_subs.append(sid)
            else:
                c_subs.append(sid)

        # Cria cohort
        cohort = await create_cohort(
            company_id, label, t_subs, c_subs,
            metadata={"pilot": True,
                      "treatment_rate_target":
                          treatment_payment_rate,
                      "control_rate_target": control_payment_rate})
        cohort_id = cohort["id"]

        # Simula pagamentos: cria invoices PAID dentro da janela
        # para uma fração realista
        def _maybe_paid(rate: float) -> bool:
            return random.random() < rate

        # Treatment: rate_t fração paga; restantes ficam open
        for sid in t_subs:
            ext = f"CAUSAL-{label}-{t_subs.index(sid):04d}"
            paid = _maybe_paid(treatment_payment_rate)
            paid_dt = (now + timedelta(
                days=random.randint(1, window_days - 1)))
            inv_id = _id("inv")
            await db.subscriber_invoices.insert_one({
                "id": inv_id, "company_id": company_id,
                "subscriber_external_id": ext,
                "status": "paid" if paid else "open",
                "amount": avg_amount,
                "amount_paid": avg_amount if paid else 0,
                "paid_date": (paid_dt.strftime(
                    "%Y-%m-%d %H:%M:%S") if paid else None),
                "synthetic_v8_3": True})
            inserted_invoices.append(inv_id)
        # Control: rate_c fração paga (geralmente menor)
        for i, sid in enumerate(c_subs):
            ext = f"CAUSAL-{label}-{n_treatment + i:04d}"
            paid = _maybe_paid(control_payment_rate)
            paid_dt = (now + timedelta(
                days=random.randint(1, window_days - 1)))
            inv_id = _id("inv")
            await db.subscriber_invoices.insert_one({
                "id": inv_id, "company_id": company_id,
                "subscriber_external_id": ext,
                "status": "paid" if paid else "open",
                "amount": avg_amount,
                "amount_paid": avg_amount if paid else 0,
                "paid_date": (paid_dt.strftime(
                    "%Y-%m-%d %H:%M:%S") if paid else None),
                "synthetic_v8_3": True})
            inserted_invoices.append(inv_id)

        # Attribution window
        attr = await compute_attribution(
            cohort_id, window_days=window_days)
        # Lift
        lift = await compute_lift(cohort_id)
        return {
            "pilot_label": label,
            "company_id": company_id,
            "dry_run": dry_run,
            "synthetic": True,
            "cohort_id": cohort_id,
            "n_treatment": n_treatment, "n_control": n_control,
            "attribution_window_days": window_days,
            "attribution_result": attr,
            "lift_result": lift,
            "generated_at": ISO(),
        }
    finally:
        if cleanup:
            # Limpa tudo (subscribers, invoices, cohort, members)
            await db.subscribers.delete_many({
                "id": {"$in": inserted_subs}})
            await db.subscriber_invoices.delete_many({
                "id": {"$in": inserted_invoices}})
            await db.motor_ia_cohorts.delete_many({
                "company_id": company_id, "label": label})
            await db.motor_ia_cohort_members.delete_many({
                "company_id": company_id})
