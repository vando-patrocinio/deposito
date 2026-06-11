"""
v8_4_cohort.py — V8.4 MOTOR DE COORTE COM PAREAMENTO REAL

Sem novas IAs/dashboards/twins. Apenas:
  - create_control_group / create_treatment_group: persistência
    em motor_ia_cohorts + motor_ia_cohort_members
  - pair_match: pareamento estatístico por (branch, plan_price band,
    days_overdue band, invoice_amount band)
  - attribution_window: marca paid_within_window após envio
  - calculate_lift: matemática pura (Wilson CI + lift)
  - Persistência final em motor_ia_causality

Reaproveita v8_3_causality (compute_attribution, compute_lift,
Wilson CI). Adiciona pareamento que V8.3 não tinha.

PROIBIÇÃO ABSOLUTA: NÃO envia mensagem sozinho. Quem envia é o
`dispatch_treatment_group()` e SÓ se `authorize_real_send=True`.
Por default authorize_real_send=False → toda mensagem segue
homologation.safe_send_whatsapp (que redireciona para TEST_PHONE).
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
import re
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from database import db

logger = logging.getLogger("v8_4_cohort")
ISO = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731

_PHONE_RX = re.compile(r"\D")


def _norm_phone(p: Any) -> Optional[str]:
    if not p:
        return None
    d = _PHONE_RX.sub("", str(p))
    if len(d) == 11 and not d.startswith("55"):
        d = "55" + d
    if len(d) == 10:
        d = "55" + d
    if 12 <= len(d) <= 13 and d.startswith("55"):
        return d
    return None


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


def _band(value: float, bands: List[float]) -> int:
    """Retorna índice da banda. Ex: bands=[50,100,200] → 4 buckets."""
    for i, b in enumerate(bands):
        if value <= b:
            return i
    return len(bands)


# ═══════════════════════════════════════════════════════════
# Candidato elegível
# ═══════════════════════════════════════════════════════════
async def list_eligible_candidates(
    company_id: str, limit: int = 1000,
) -> List[Dict[str, Any]]:
    """Lista subscribers overdue + phone + histórico de pagamento.

    Devolve dict com chaves de pareamento já calculadas.
    """
    from services.v7_2_revenue import _ext_candidates

    overdue_exts = await db.subscriber_invoices.distinct(
        "subscriber_external_id",
        {"company_id": company_id, "status": "overdue"})

    elig: List[Dict[str, Any]] = []
    for ext in overdue_exts[:limit * 3]:
        sub = await db.subscribers.find_one({
            "company_id": company_id,
            "external_code": {"$in": _ext_candidates(ext)}})
        if not sub:
            continue
        phone = _norm_phone(sub.get("phone"))
        if not phone:
            continue
        n_paid = await db.subscriber_invoices.count_documents({
            "company_id": company_id,
            "subscriber_external_id": ext, "status": "paid"})
        if n_paid < 1:
            continue
        # Pega a fatura overdue mais recente como referência
        inv = await db.subscriber_invoices.find_one({
            "company_id": company_id,
            "subscriber_external_id": ext,
            "status": "overdue"}, sort=[("due_date", -1)])
        if not inv:
            continue
        due_dt = _parse_dt(inv.get("due_date"))
        days_overdue = (
            (datetime.now(timezone.utc) - due_dt).days
            if due_dt else 0)
        plan_price = float(sub.get("plan_price") or 0)
        inv_amount = float(inv.get("amount") or 0)
        elig.append({
            "subscriber_id": sub.get("id"),
            "external_code": sub.get("external_code"),
            "phone": phone,
            "branch": sub.get("branch") or "sem_filial",
            "plan_price": plan_price,
            "plan_price_band":
                _band(plan_price, [50, 100, 150, 250]),
            "invoice_id": inv.get("id"),
            "invoice_amount": inv_amount,
            "invoice_amount_band":
                _band(inv_amount, [50, 100, 150, 250]),
            "days_overdue": days_overdue,
            "days_overdue_band":
                _band(days_overdue, [3, 7, 15, 30]),
            "n_paid_history": n_paid,
        })
        if len(elig) >= limit:
            break
    return elig


# ═══════════════════════════════════════════════════════════
# Pareamento estatístico
# ═══════════════════════════════════════════════════════════
def _strata_key(c: Dict[str, Any]) -> Tuple:
    return (c["branch"], c["plan_price_band"],
            c["invoice_amount_band"], c["days_overdue_band"])


def pair_match(
    candidates: List[Dict[str, Any]],
    n_per_group: int = 50,
    seed: int = 42,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Pareamento por strata (branch+price_band+amount_band+
    overdue_band). Para cada strata, embaralha e divide em
    pares treatment/control. Strata muito pequenas vão para
    pool de reserva e são pareadas no fim.

    Retorna (treatment_list, control_list) já balanceados.
    """
    rnd = random.Random(seed)
    # Agrupa por strata
    by_strata: Dict[Tuple, List[Dict[str, Any]]] = {}
    for c in candidates:
        by_strata.setdefault(_strata_key(c), []).append(c)
    treatment: List[Dict[str, Any]] = []
    control: List[Dict[str, Any]] = []
    leftover: List[Dict[str, Any]] = []
    # Para cada strata, pares alternados
    for k, members in by_strata.items():
        rnd.shuffle(members)
        # pares completos
        pairs = len(members) // 2
        for i in range(pairs):
            treatment.append({**members[2 * i],
                              "strata": str(k)})
            control.append({**members[2 * i + 1],
                            "strata": str(k)})
        if len(members) % 2 == 1:
            leftover.append(members[-1])
    # Pareia o leftover (estratos com 1 só)
    rnd.shuffle(leftover)
    for i in range(0, len(leftover) - 1, 2):
        treatment.append({**leftover[i], "strata": "leftover"})
        control.append({**leftover[i + 1], "strata": "leftover"})
    # Trunca para n_per_group
    return treatment[:n_per_group], control[:n_per_group]


# ═══════════════════════════════════════════════════════════
# Criação de grupos (persistência idempotente)
# ═══════════════════════════════════════════════════════════
async def create_cohort_v84(
    company_id: str, label: str,
    treatment: List[Dict[str, Any]],
    control: List[Dict[str, Any]],
    attribution_window_days: int = 14,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Cria coorte V8.4 com membros pareados. Idempotente por
    (company_id, label)."""
    cohort_id = f"v84-{label}-{uuid.uuid4().hex[:8]}"
    now = ISO()
    cohort_doc = {
        "id": cohort_id, "cohort_id": cohort_id,
        "company_id": company_id, "label": label,
        "version": "v8_4",
        "attribution_window_days": attribution_window_days,
        "size_treatment": len(treatment),
        "size_control": len(control),
        "metadata": metadata or {},
        "status": "open",
        "created_at": now,
    }
    await db.motor_ia_cohorts.update_one(
        {"company_id": company_id, "label": label,
         "version": "v8_4"},
        {"$setOnInsert": cohort_doc}, upsert=True)
    cohort = await db.motor_ia_cohorts.find_one({
        "company_id": company_id, "label": label,
        "version": "v8_4"})
    cid = cohort["id"]

    def _member(c, group):
        return {
            "id": _id("cm"),
            "cohort_id": cid, "company_id": company_id,
            "subscriber_id": c["subscriber_id"],
            "external_code": c.get("external_code"),
            "phone": c.get("phone"),
            "group": group,
            "strata": c.get("strata", ""),
            "branch": c.get("branch"),
            "plan_price": c.get("plan_price"),
            "invoice_id": c.get("invoice_id"),
            "invoice_amount": c.get("invoice_amount"),
            "days_overdue_at_entry": c.get("days_overdue"),
            "entered_at": now,
            "attribution_window_days": attribution_window_days,
            "exited_at": None,
            "wa_message_id": None,
            "wa_sent_at": None,
            "paid_within_window": False,
            "paid_amount_BRL": 0.0,
            "paid_at": None,
            "status": "queued",
        }
    for c in treatment:
        m = _member(c, "treatment")
        await db.motor_ia_cohort_members.update_one(
            {"cohort_id": cid,
             "subscriber_id": m["subscriber_id"]},
            {"$setOnInsert": m}, upsert=True)
    for c in control:
        m = _member(c, "control")
        await db.motor_ia_cohort_members.update_one(
            {"cohort_id": cid,
             "subscriber_id": m["subscriber_id"]},
            {"$setOnInsert": m}, upsert=True)
    return cohort


# Aliases pedidos pela constituição
async def create_treatment_group(
    cohort_id: str, members: List[Dict[str, Any]],
) -> int:
    """Adiciona membros ao grupo treatment de um cohort existente."""
    n = 0
    for m in members:
        await db.motor_ia_cohort_members.update_one(
            {"cohort_id": cohort_id,
             "subscriber_id": m["subscriber_id"]},
            {"$setOnInsert": {**m, "group": "treatment",
                              "cohort_id": cohort_id}},
            upsert=True)
        n += 1
    return n


async def create_control_group(
    cohort_id: str, members: List[Dict[str, Any]],
) -> int:
    n = 0
    for m in members:
        await db.motor_ia_cohort_members.update_one(
            {"cohort_id": cohort_id,
             "subscriber_id": m["subscriber_id"]},
            {"$setOnInsert": {**m, "group": "control",
                              "cohort_id": cohort_id}},
            upsert=True)
        n += 1
    return n


# ═══════════════════════════════════════════════════════════
# Despacho do tratamento (PASSA pelo homologation gateway)
# ═══════════════════════════════════════════════════════════
async def dispatch_treatment_group(
    cohort_id: str,
    template: str = (
        "Olá! Identificamos uma fatura em aberto. "
        "Pague via PIX para evitar bloqueio."),
    authorize_real_send: bool = False,
) -> Dict[str, Any]:
    """Envia mensagem para grupo TREATMENT.

    - `authorize_real_send=False` (default): cada mensagem entra no
      gateway `homologation.safe_send_whatsapp` que (por HOMOLOG_MODE)
      redireciona TODO destino ≠ TEST_PHONE para TEST_PHONE.
    - `authorize_real_send=True`: parâmetro de futuro. Só terá
      efeito quando o flag de "modo piloto causal real" estiver
      ativo no homologation gateway. NÃO está ativo agora.

    Cada send grava wa_message_id no membro do cohort.
    """
    from services import homologation
    cohort = await db.motor_ia_cohorts.find_one({"id": cohort_id})
    if not cohort:
        return {"error": "cohort_not_found"}
    co = cohort["company_id"]
    sent = errors = 0
    async for m in db.motor_ia_cohort_members.find({
        "cohort_id": cohort_id, "group": "treatment",
        "wa_sent_at": None,
    }):
        try:
            r = await homologation.safe_send_whatsapp(
                company_id=co,
                target_phone=m.get("phone") or "00000000000",
                message=template,
                origin="v8_4_pilot",
                client_context={
                    "name": "PILOTO_V8_4",
                    "phone": m.get("phone")})
            await db.motor_ia_cohort_members.update_one(
                {"id": m["id"]},
                {"$set": {
                    "wa_message_id": r.get("sidecar_message_id"),
                    "wa_outbox_id": r.get("id"),
                    "wa_sent_at": ISO(),
                    "wa_blocked": r.get("blocked"),
                    "wa_to_effective": r.get("to_effective"),
                    "status": "dispatched"}})
            sent += 1
        except Exception as e:  # noqa: BLE001
            errors += 1
            logger.warning("[v8_4] dispatch err: %r", e)
    return {
        "cohort_id": cohort_id,
        "sent": sent, "errors": errors,
        "authorize_real_send": authorize_real_send,
        "homolog_redirect_active": True,
        "generated_at": ISO(),
    }


# ═══════════════════════════════════════════════════════════
# Attribution window (reaproveita lógica V8.3 + invoice_id)
# ═══════════════════════════════════════════════════════════
async def attribution_window(
    cohort_id: str,
) -> Dict[str, Any]:
    """Para cada membro, varre invoices PAID do invoice_id do
    cohort entry entre entered_at e entered_at+window_days."""
    cohort = await db.motor_ia_cohorts.find_one({"id": cohort_id})
    if not cohort:
        return {"error": "cohort_not_found"}
    window = int(cohort.get("attribution_window_days") or 14)
    co = cohort["company_id"]
    marked = 0
    async for m in db.motor_ia_cohort_members.find({
        "cohort_id": cohort_id, "paid_within_window": False,
    }):
        entered = _parse_dt(m["entered_at"])
        if not entered:
            continue
        end = entered + timedelta(days=window)
        # Tenta por invoice_id direto (preciso)
        inv = None
        if m.get("invoice_id"):
            x = await db.subscriber_invoices.find_one(
                {"id": m["invoice_id"], "status": "paid"})
            if x:
                paid_dt = _parse_dt(x.get("paid_date"))
                if paid_dt and entered <= paid_dt <= end:
                    inv = x
        # Fallback: qualquer invoice paga do subscriber na janela
        if not inv and m.get("external_code"):
            from services.v7_2_revenue import _ext_candidates
            cands = _ext_candidates(m["external_code"])
            if "-" in str(m["external_code"]):
                cands.append(
                    str(m["external_code"]).split("-", 1)[1])
            async for x in db.subscriber_invoices.find({
                "company_id": co, "status": "paid",
                "subscriber_external_id": {"$in": cands},
            }):
                paid_dt = _parse_dt(x.get("paid_date"))
                if paid_dt and entered <= paid_dt <= end:
                    inv = x
                    break
        if inv:
            amount = float(inv.get("amount_paid") or 0)
            await db.motor_ia_cohort_members.update_one(
                {"id": m["id"]},
                {"$set": {
                    "paid_within_window": True,
                    "paid_amount_BRL": amount,
                    "paid_at": inv.get("paid_date"),
                    "exited_at": ISO(),
                    "paid_invoice_id": inv.get("id"),
                    "status": "paid"}})
            marked += 1
    return {"cohort_id": cohort_id,
            "members_marked_paid": marked,
            "window_days": window,
            "generated_at": ISO()}


# ═══════════════════════════════════════════════════════════
# Lift Calculator (mesma lógica V8.3 + persistência em
# motor_ia_causality)
# ═══════════════════════════════════════════════════════════
def _wilson(k: int, n: int, z: float = 1.96
            ) -> Tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    c = (p + z * z / (2 * n)) / denom
    s = (z * math.sqrt(p * (1 - p) / n
                       + z * z / (4 * n * n)) / denom)
    return max(0.0, c - s), min(1.0, c + s)


def _z_test_two_proportions(
    k1: int, n1: int, k2: int, n2: int,
) -> Tuple[float, float]:
    """Z-test para diferença de duas proporções.
    Retorna (z, p_value_two_sided)."""
    if n1 == 0 or n2 == 0:
        return 0.0, 1.0
    p1, p2 = k1 / n1, k2 / n2
    p_pool = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return 0.0, 1.0
    z = (p1 - p2) / se
    # Aproximação normal: p_value two-sided
    # erf for normal CDF
    p_value = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return z, p_value


async def calculate_lift(
    cohort_id: str,
) -> Dict[str, Any]:
    """Lift completo + z-test + persistência motor_ia_causality."""
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
    ci_t = _wilson(t_paid, t_total)
    ci_c = _wilson(c_paid, c_total)
    z, p_value = _z_test_two_proportions(
        t_paid, t_total, c_paid, c_total)
    significant_95 = p_value < 0.05 and abs_lift > 0

    # Σ BRL realizado
    async def _sum(group):
        agg = await db.motor_ia_cohort_members.aggregate([
            {"$match": {"cohort_id": cohort_id, "group": group,
                        "paid_within_window": True}},
            {"$group": {"_id": None,
                        "total": {"$sum": "$paid_amount_BRL"}}}
        ]).to_list(1)
        return float(agg[0]["total"]) if agg else 0.0
    t_brl = await _sum("treatment")
    c_brl = await _sum("control")
    incremental = t_brl - c_brl

    cohort = await db.motor_ia_cohorts.find_one({"id": cohort_id})
    co = (cohort or {}).get("company_id") or "unknown"

    causality_doc = {
        "id": _id("caus"),
        "cohort_id": cohort_id,
        "company_id": co,
        "treatment_n": t_total,
        "treatment_paid_n": t_paid,
        "treatment_rate": round(rate_t, 4),
        "treatment_ci95": [round(ci_t[0], 4),
                           round(ci_t[1], 4)],
        "treatment_revenue_BRL": round(t_brl, 2),
        "control_n": c_total,
        "control_paid_n": c_paid,
        "control_rate": round(rate_c, 4),
        "control_ci95": [round(ci_c[0], 4),
                         round(ci_c[1], 4)],
        "control_revenue_BRL": round(c_brl, 2),
        "lift_absolute": round(abs_lift, 4),
        "lift_pct": round(pct_lift, 2),
        "z_score": round(z, 4),
        "p_value_two_sided": round(p_value, 6),
        "significant_95": significant_95,
        "incremental_revenue_BRL": round(incremental, 2),
        "roi_projected_per_thousand_BRL":
            round(incremental / max(t_total, 1) * 1000, 2),
        "generated_at": ISO(),
    }
    await db.motor_ia_causality.update_one(
        {"cohort_id": cohort_id},
        {"$set": causality_doc}, upsert=True)
    return causality_doc


# ═══════════════════════════════════════════════════════════
# Orquestrador principal V8.4
# ═══════════════════════════════════════════════════════════
async def run_pilot_v84(
    company_id: str, label: str,
    pilot_size: int = 50, window_days: int = 14,
    authorize_real_send: bool = False,
    dispatch: bool = True,
    seed: int = 42,
) -> Dict[str, Any]:
    """Orquestra todas as fases V8.4:
       1) lista candidatos elegíveis
       2) pareia em treatment/control
       3) cria cohort + members
       4) (opcional) despacha treatment via homologation
       5) NÃO calcula lift (precisa esperar attribution window)
    """
    # 1) Candidatos
    cands = await list_eligible_candidates(
        company_id, limit=pilot_size * 4)
    if len(cands) < pilot_size * 2:
        return {
            "error": "insufficient_candidates",
            "n_eligible": len(cands),
            "required": pilot_size * 2}
    # 2) Pareamento
    t, c = pair_match(cands, n_per_group=pilot_size, seed=seed)
    # 3) Cohort
    cohort = await create_cohort_v84(
        company_id, label, t, c,
        attribution_window_days=window_days,
        metadata={"seed": seed, "pilot_size": pilot_size,
                  "authorize_real_send": authorize_real_send})
    cid = cohort["id"]
    # 4) Dispatch (via gateway homolog → redireciona para TEST_PHONE
    # em HOMOLOG_MODE=true; sem autorização real_send, isso é
    # ZERO clientes reais contatados)
    dispatch_result = None
    if dispatch:
        dispatch_result = await dispatch_treatment_group(
            cid, authorize_real_send=authorize_real_send)
    return {
        "cohort_id": cid,
        "label": label,
        "company_id": company_id,
        "n_treatment": len(t),
        "n_control": len(c),
        "attribution_window_days": window_days,
        "dispatch_result": dispatch_result,
        "next_step": (
            f"Aguardar {window_days} dias, depois rodar "
            f"attribution_window('{cid}') seguido de "
            f"calculate_lift('{cid}')"),
        "generated_at": ISO(),
    }
