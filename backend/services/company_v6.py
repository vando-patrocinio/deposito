"""
company_v6.py — CONSTITUIÇÃO V6.0 — Diretor Executivo Digital

Reúne (sem criar novos módulos/dashboards/IAs):
  P1 — Smart Field Ops via pipeline interno
       (handle_install / handle_repair / handle_withdrawal a partir
       de tickets do autonomous_engine)
  P2 — Digital Twin Completo (4 painéis: rede + infra + campo +
       financeiro) como agregador de cards V5
  P3 — Autonomous Company Score 0-100
       (composto a partir de scores existentes — failure_risk,
       observability_health, technician_score, preventive_ratio,
       receita recebida)
  P4 — Receita Real: mark_revenue_received + reconcile com
       fin_cash_movements existentes

REGRA DE OURO (6 perguntas):
  Cada função aqui responde SIM a pelo menos uma:
  Aumenta receita · Reduz churn · Reduz truck roll ·
  Melhora campo · Melhora rede · Ajuda Presidente IA decidir.
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

import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from database import db

logger = logging.getLogger("company_v6")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _new(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:12]}"


# ═══════════════════════════════════════════════════════════
# P1 — SMART FIELD OPS (pipeline interno, sem CRUD)
# ═══════════════════════════════════════════════════════════
async def _ensure_smart_record(
    company_id: str, ticket: Dict[str, Any], kind: str,
) -> Dict[str, Any]:
    """Cria/atualiza smart_installs/repairs/withdrawals a partir de
    um ticket. Idempotente (upsert por ticket_id)."""
    col = {"install": "smart_installs",
           "repair": "smart_repairs",
           "withdraw": "smart_withdrawals"}[kind]
    sid = _new({"install": "sfi", "repair": "sfr",
                "withdraw": "sfw"}[kind])
    doc = {
        "id": sid, "company_id": company_id,
        "client_id": ticket.get("client_id"),
        "ticket_id": ticket.get("id"),
        "tech_id": ticket.get("assigned_to"),
        "kind": kind,
        "status": ticket.get("status", "open"),
        "subject": ticket.get("subject"),
        "priority": ticket.get("priority"),
        "scheduled_at": ticket.get("scheduled_at"),
        "started_at": ticket.get("started_at"),
        "finished_at": ticket.get("closed_at"),
        "photos_count": ticket.get("photos_count", 0),
        "geo_check_in": ticket.get("geo_check_in"),
        "reopened": ticket.get("reopened", False),
        "created_at": ticket.get("opened_at") or _now_iso(),
        "updated_at": _now_iso(),
    }
    if kind == "install":
        doc["installation_quality_score"] = (
            0 if ticket.get("reopened") else
            100 if ticket.get("status") in (
                "closed", "completed", "finalizada") else 50)
        doc["first_time_complete"] = not ticket.get("reopened", False)
        doc["ont_sn"] = ticket.get("ont_sn")
    elif kind == "repair":
        doc["remote_attempt_first"] = (
            ticket.get("resolution_kind") == "remote")
        doc["remote_resolved"] = doc["remote_attempt_first"]
        doc["truck_roll_avoided"] = doc["remote_resolved"]
        doc["reopened_within_7d"] = ticket.get("reopened", False)
    elif kind == "withdraw":
        doc["asset_recovered"] = ticket.get("asset_recovered", False)
        doc["asset_recovery_score"] = (
            100 if doc["asset_recovered"] else 0)
        doc["signed_receipt"] = ticket.get("signed_receipt", False)

    await db[col].update_one(
        {"company_id": company_id, "ticket_id": ticket.get("id")},
        {"$set": doc}, upsert=True)
    return doc


def _classify_kind_from_ticket(ticket: Dict[str, Any]) -> Optional[str]:
    cat = (ticket.get("category") or "").strip()
    # Atalho: category já canônica (INSTALL/REPAIR/WITHDRAW)
    cat_upper = cat.upper()
    if cat_upper == "INSTALL":
        return "install"
    if cat_upper == "REPAIR":
        return "repair"
    if cat_upper == "WITHDRAW":
        return "withdraw"
    # Fallback heurístico (texto livre em pt-BR/EN)
    cat_lc = cat.lower()
    subj = (ticket.get("subject") or "").lower()
    if "instal" in cat_lc or "instal" in subj:
        return "install"
    if "retir" in cat_lc or "withdraw" in cat_lc or "retir" in subj:
        return "withdraw"
    if any(k in cat_lc for k in ("repar", "manuten", "tech")) or \
            any(k in subj for k in ("repar", "manuten")):
        return "repair"
    return None


async def sync_smart_field_ops(
    company_id: str, window_days: int = 30,
) -> Dict[str, Any]:
    """Varre tickets do período e classifica em install/repair/withdraw
    persistindo em smart_*. Idempotente."""
    cutoff = _cutoff(window_days)
    cur = db.tickets.find({
        "company_id": company_id,
        "opened_at": {"$gte": cutoff}})
    counts = {"install": 0, "repair": 0, "withdraw": 0,
              "unclassified": 0}
    async for t in cur:
        kind = _classify_kind_from_ticket(t)
        if not kind:
            counts["unclassified"] += 1
            continue
        try:
            await _ensure_smart_record(company_id, t, kind)
            counts[kind] += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("sync_smart err ticket=%s: %r",
                           t.get("id"), e)
    return {"company_id": company_id, "window_days": window_days,
            "synced": counts, "generated_at": _now_iso()}


async def smart_field_ops_kpis(
    company_id: str, window_days: int = 30,
) -> Dict[str, Any]:
    """KPIs Smart Field Ops a partir das collections smart_*."""
    cutoff = _cutoff(window_days)
    inst_total = await db.smart_installs.count_documents({
        "company_id": company_id, "created_at": {"$gte": cutoff}})
    inst_ftc = await db.smart_installs.count_documents({
        "company_id": company_id, "created_at": {"$gte": cutoff},
        "first_time_complete": True})
    inst_quality = (inst_ftc / max(inst_total, 1)) * 100

    rep_total = await db.smart_repairs.count_documents({
        "company_id": company_id, "created_at": {"$gte": cutoff}})
    truck_avoided = await db.smart_repairs.count_documents({
        "company_id": company_id, "created_at": {"$gte": cutoff},
        "truck_roll_avoided": True})
    truck_roll_pct = (truck_avoided / max(rep_total, 1)) * 100

    wd_total = await db.smart_withdrawals.count_documents({
        "company_id": company_id, "created_at": {"$gte": cutoff}})
    wd_rec = await db.smart_withdrawals.count_documents({
        "company_id": company_id, "created_at": {"$gte": cutoff},
        "asset_recovered": True})
    asset_recovery_pct = (wd_rec / max(wd_total, 1)) * 100

    return {
        "company_id": company_id, "window_days": window_days,
        "installs": {
            "total": inst_total, "first_time_complete": inst_ftc,
            "quality_score_pct": round(inst_quality, 1)},
        "repairs": {
            "total": rep_total,
            "truck_roll_avoided": truck_avoided,
            "truck_roll_avoidance_pct": round(truck_roll_pct, 1)},
        "withdrawals": {
            "total": wd_total, "asset_recovered": wd_rec,
            "asset_recovery_score_pct": round(asset_recovery_pct, 1)},
        "generated_at": _now_iso(),
    }


# ═══════════════════════════════════════════════════════════
# P4 — RECEITA REAL: mark_received + reconcile
# ═══════════════════════════════════════════════════════════
async def mark_revenue_received(
    company_id: str, outcome_id: str,
    actual_BRL: float, source: str = "manual_admin",
    payment_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """Fecha o ciclo P4: marca outcome como recebido com valor real.

    NÃO depende de integração externa — admin pode chamar este endpoint
    a partir de uma conciliação manual. Quando Asaas/PIX vier no
    futuro, o webhook chama esta mesma função.
    """
    oc = await db.motor_ia_outcomes.find_one(
        {"id": outcome_id, "company_id": company_id})
    if not oc:
        return {"error": "outcome_not_found",
                "outcome_id": outcome_id}
    # Excluir homolog para não contaminar produção (Sprint V5.3)
    if oc.get("environment") == "homolog":
        return {"error": "homolog_outcome_cannot_be_marked_real",
                "outcome_id": outcome_id}
    actual = max(0.0, float(actual_BRL))
    await db.motor_ia_outcomes.update_one(
        {"id": outcome_id},
        {"$set": {"actual_BRL": actual,
                  "status": "revenue_received",
                  "revenue_source": source,
                  "payment_ref": payment_ref,
                  "received_at": _now_iso()}})
    # Atualiza action.actual_BRL também
    if oc.get("action_id"):
        await db.motor_ia_actions.update_one(
            {"id": oc["action_id"]},
            {"$set": {"actual_BRL": actual,
                      "status": "revenue_confirmed"}})
    # Persiste em learning row para auditoria
    await db.motor_ia_learnings.insert_one({
        "id": _new("lrn"),
        "company_id": company_id,
        "outcome_id": outcome_id,
        "kind": "revenue_confirmation",
        "expected_BRL": float(oc.get("expected_BRL") or 0),
        "actual_BRL": actual,
        "delta_BRL": round(
            actual - float(oc.get("expected_BRL") or 0), 2),
        "source": source,
        "created_at": _now_iso(),
    })
    return {"company_id": company_id, "outcome_id": outcome_id,
            "actual_BRL": actual, "status": "revenue_received",
            "marked_at": _now_iso()}


async def reconcile_with_cash(
    company_id: str, window_days: int = 30,
) -> Dict[str, Any]:
    """Auto-conciliação: outcomes com expected_BRL pendentes vs
    movimentos em fin_cash_movements (se a coleção existir)."""
    cols = await db.list_collection_names()
    if "fin_cash_movements" not in cols:
        return {"company_id": company_id, "matched": 0,
                "reason": "fin_cash_movements_not_present"}
    cutoff = _cutoff(window_days)
    matched = 0
    total_BRL = 0.0
    async for oc in db.motor_ia_outcomes.find({
        "company_id": company_id,
        "environment": {"$ne": "homolog"},
        "status": {"$ne": "revenue_received"},
        "expected_BRL": {"$gt": 0},
        "observed_at": {"$gte": cutoff},
    }):
        subscriber_id = oc.get("subscriber_id")
        if not subscriber_id:
            continue
        mov = await db.fin_cash_movements.find_one({
            "company_id": company_id, "type": "income",
            "client_id": subscriber_id,
            "created_at": {"$gte": cutoff},
        })
        if not mov:
            continue
        await mark_revenue_received(
            company_id, oc["id"],
            float(mov.get("amount") or 0),
            source="auto_reconcile_cash",
            payment_ref=mov.get("id"))
        matched += 1
        total_BRL += float(mov.get("amount") or 0)
    return {"company_id": company_id,
            "matched_outcomes": matched,
            "total_received_BRL": round(total_BRL, 2),
            "generated_at": _now_iso()}


# ═══════════════════════════════════════════════════════════
# P3 — AUTONOMOUS COMPANY SCORE
# ═══════════════════════════════════════════════════════════
async def autonomous_company_score(
    company_id: str, window_days: int = 30,
) -> Dict[str, Any]:
    """Nota única 0-100 + explicação + evolução vs ontem.

    Componentes (pesos somam 100):
       infrastructure_health: 20  (observability_health.score)
       failure_risk_inverse:  20  (100 - %CRITICO em failure_risk)
       preventive_ratio:      15  (motor_ia preventivas/total)
       technician_avg:        15  (média technician_score)
       revenue_realization:   20  (actual_BRL / expected_BRL)
       smart_field_quality:   10  (FTC + truck_roll_avoid + asset_rec)
    """
    # Importa local p/ não criar deps cruzadas duras
    from services import observability_twin, ops_v51
    try:
        from services import failure_risk
    except Exception:
        failure_risk = None

    # 1) Infrastructure health (Observability Twin)
    try:
        oh = await observability_twin.observability_health_score(
            company_id, window_hours=window_days * 24)
        infra = float(oh.get("score") or 0)
    except Exception:
        infra = 50.0

    # 2) Failure risk INVERSO (quanto mais BAIXO → melhor)
    fr_inv = 100.0
    if failure_risk is not None:
        try:
            dist = await failure_risk.distribution(company_id)
            crit_pct = dist.get("critical_pct", 0)
            fr_inv = max(0.0, 100.0 - crit_pct)
        except Exception:
            pass

    # 3) Preventive ratio (Fase H — V5.0)
    prev_ratio_pct = 0.0
    if failure_risk is not None:
        try:
            m = await failure_risk.phase_h_metrics(
                company_id, window_days=window_days)
            prev_ratio_pct = float(
                m.get("preventive_ratio", 0)) * 100
        except Exception:
            pass

    # 4) Technician average score
    try:
        techs = await ops_v51.technician_ranking(
            company_id, window_days=window_days, limit=50)
        tech_avg = (sum(t["score"] for t in techs)
                    / max(len(techs), 1)) if techs else 0
    except Exception:
        tech_avg = 0

    # 5) Revenue realization — V7.2 G1 FIX: usa truth-source
    # (invoices paid) em vez de só motor_ia_outcomes que ignora
    # receita orgânica.
    expected_total = actual_total = 0.0
    realization = 0.0
    try:
        from services import v7_2_revenue
        truth = await v7_2_revenue.revenue_realization_truth(
            company_id, window_days=window_days)
        # actual_total = receita REAL da empresa no período
        actual_total = float(truth.get("revenue_total_BRL") or 0)
        expected_total = float(truth.get("expected_BRL_motor_ia") or 0)
        # realization = corporate (% das faturas que foram pagas)
        # Esse é o KPI que reflete a saúde financeira real.
        realization = float(
            truth.get("corporate_realization_pct") or 0)
        # Fallback: se 0 invoices, usa motor realization
        if realization == 0 and expected_total > 0:
            realization = float(
                truth.get("motor_realization_pct") or 0)
    except Exception as e:  # noqa: BLE001
        logger.warning("revenue_realization_truth fail: %r", e)
        # Fallback legado para não quebrar
        pipe = [
            {"$match": {"company_id": company_id,
                        "environment": {"$ne": "homolog"},
                        "observed_at": {"$gte":
                                        _cutoff(window_days)}}},
            {"$group": {"_id": None,
                        "expected": {"$sum": "$expected_BRL"},
                        "actual": {"$sum": "$actual_BRL"}}}]
        agg = await db.motor_ia_outcomes.aggregate(pipe).to_list(1)
        if agg:
            expected_total = float(agg[0].get("expected") or 0)
            actual_total = float(agg[0].get("actual") or 0)
            realization = min(100.0,
                              (actual_total / expected_total * 100)
                              if expected_total > 0 else 0)

    # 6) Smart Field quality (consolida FTC + truck avoid + asset rec)
    try:
        sk = await smart_field_ops_kpis(company_id,
                                        window_days=window_days)
        sfq = (sk["installs"]["quality_score_pct"]
               + sk["repairs"]["truck_roll_avoidance_pct"]
               + sk["withdrawals"]["asset_recovery_score_pct"]) / 3
    except Exception:
        sfq = 0

    components = {
        "infrastructure_health": round(infra, 1),
        "failure_risk_inverse": round(fr_inv, 1),
        "preventive_ratio_pct": round(prev_ratio_pct, 1),
        "technician_avg": round(tech_avg, 1),
        "revenue_realization_pct": round(realization, 1),
        "smart_field_quality": round(sfq, 1),
    }
    weights = {
        "infrastructure_health": 20, "failure_risk_inverse": 20,
        "preventive_ratio_pct": 15, "technician_avg": 15,
        "revenue_realization_pct": 20, "smart_field_quality": 10,
    }
    score = round(sum(
        components[k] * weights[k] / 100.0
        for k in components), 1)
    cls = ("EXECUTIVO_PLENO" if score >= 90
           else "OPERACIONAL_FORTE" if score >= 75
           else "FUNCIONAL" if score >= 60
           else "ATENCAO" if score >= 40
           else "CRITICO")

    # Persist diário para evolução (upsert por dia)
    today = datetime.now(timezone.utc).date().isoformat()
    doc = {
        "id": f"acs-{today}-{company_id}",
        "company_id": company_id,
        "date": today,
        "score": score, "classification": cls,
        "components": components, "weights": weights,
        "raw": {"expected_BRL_total": round(expected_total, 2),
                "actual_BRL_total": round(actual_total, 2)},
        "computed_at": _now_iso(),
    }
    await db.autonomous_company_scores.update_one(
        {"id": doc["id"]}, {"$set": doc}, upsert=True)

    # Evolução vs dia anterior
    yesterday = (datetime.now(timezone.utc).date()
                 - timedelta(days=1)).isoformat()
    prev = await db.autonomous_company_scores.find_one(
        {"id": f"acs-{yesterday}-{company_id}"})
    delta = (score - prev["score"]) if prev else None

    # Explicação automática (Regra de Ouro V5)
    failing = [k for k, v in components.items() if v < 60]
    winning = [k for k, v in components.items() if v >= 85]
    explanation = {
        "best": winning[:3] or ["Sem componentes em destaque"],
        "worst": failing[:3] or ["Sem componentes críticos"],
        "narrative": (
            f"Score {score} ({cls}). "
            + (f"Forte em: {', '.join(winning[:3])}. " if winning else "")
            + (f"Atenção em: {', '.join(failing[:3])}. " if failing else "")
            + (f"Evolução {('+' if delta and delta>0 else '')}"
               f"{delta} pts vs ontem." if delta is not None else "")
        ),
    }

    return {
        "company_id": company_id,
        "date": today,
        "score": score,
        "classification": cls,
        "delta_vs_yesterday": delta,
        "components": components,
        "weights": weights,
        "explanation": explanation,
        "answers_six_questions": {
            "aumenta_receita":
                components["revenue_realization_pct"] >= 50,
            "reduz_churn":
                components["preventive_ratio_pct"] >= 50,
            "reduz_truck_roll":
                components["smart_field_quality"] >= 50,
            "melhora_campo":
                components["technician_avg"] >= 60,
            "melhora_rede":
                components["infrastructure_health"] >= 80,
            "ajuda_presidente_decidir": True,
        },
        "generated_at": _now_iso(),
    }


# ═══════════════════════════════════════════════════════════
# P2 — DIGITAL TWIN COMPLETO (4 painéis no Command Center)
# ═══════════════════════════════════════════════════════════
async def digital_twin_summary(
    company_id: str, window_days: int = 30,
) -> Dict[str, Any]:
    """4 quadrantes (rede + infra + campo + financeiro) em formato V5
    PROBLEMA/CAUSA/IMPACTO/AÇÃO/CONFIANÇA/EVIDÊNCIA."""
    # Network (SmartOLT — proxy via smartolt_onus)
    bad_onus = await db.smartolt_onus.count_documents({
        "company_id": company_id,
        "status": {"$in": ["LOS", "Offline", "Power fail"]}})
    total_onus = max(await db.smartolt_onus.count_documents(
        {"company_id": company_id}), 1)
    net_health = round(100 - (bad_onus / total_onus * 100), 1)

    # Infrastructure (Observability Twin)
    try:
        from services import observability_twin
        oh = await observability_twin.observability_health_score(
            company_id, window_hours=window_days * 24)
        infra_score = oh.get("score", 0)
    except Exception:
        oh = {"raw": {}}
        infra_score = 0

    # Field (Smart Field Ops)
    sk = await smart_field_ops_kpis(company_id, window_days)

    # Financial (Receita real)
    agg = await db.motor_ia_outcomes.aggregate([
        {"$match": {"company_id": company_id,
                    "environment": {"$ne": "homolog"},
                    "observed_at": {"$gte": _cutoff(window_days)}}},
        {"$group": {"_id": None,
                    "expected": {"$sum": "$expected_BRL"},
                    "actual": {"$sum": "$actual_BRL"}}}
    ]).to_list(1)
    exp_total = float(agg[0]["expected"]) if agg else 0
    act_total = float(agg[0]["actual"]) if agg else 0
    realization = (act_total / exp_total * 100) if exp_total else 0

    return {
        "company_id": company_id,
        "window_days": window_days,
        "quadrants": {
            "network": {
                "title": "Rede (SmartOLT)",
                "problem": (f"{bad_onus} ONU(s) ruins de "
                             f"{total_onus}"),
                "cause": "LOS / Offline / Power Fail",
                "impact": f"Saúde de rede: {net_health}%",
                "action": ("Disparar OS preventivas via "
                           "failure_risk drive"),
                "confidence": 0.90,
                "score": net_health,
                "evidence": [
                    {"type": "bad_onus", "value": bad_onus,
                     "source": "smartolt_onus"}],
            },
            "infrastructure": {
                "title": "Infraestrutura (Observability)",
                "problem": (f"Health score {infra_score} "
                             f"({oh.get('classification', '?')})"),
                "cause": "Zabbix + Grafana convergência",
                "impact": (f"Componentes em falha: "
                           f"{', '.join([k for k,v in oh.get('components',{}).items() if v<80]) or 'nenhum'}"),
                "action": ("Acompanhar incidentes correlacionados"),
                "confidence": 0.90,
                "score": infra_score,
                "evidence": [
                    {"type": "components",
                     "value": oh.get("components", {}),
                     "source": "observability_twin"}],
            },
            "field": {
                "title": "Campo (Smart Field Ops)",
                "problem": (f"FTC={sk['installs']['quality_score_pct']}% · "
                             f"TR Avoid={sk['repairs']['truck_roll_avoidance_pct']}% · "
                             f"Asset={sk['withdrawals']['asset_recovery_score_pct']}%"),
                "cause": "Operação técnica em campo",
                "impact": ("Cada 1% em truck_roll_avoidance = visita "
                           "poupada"),
                "action": ("Coaching dos técnicos com pior FTC + "
                           "diagnóstico remoto primeiro"),
                "confidence": 0.85,
                "score": (sk["installs"]["quality_score_pct"]
                          + sk["repairs"]["truck_roll_avoidance_pct"]
                          + sk["withdrawals"][
                              "asset_recovery_score_pct"]) / 3,
                "evidence": [{"type": "smart_field_kpis",
                              "value": sk,
                              "source": "smart_installs/repairs/"
                                        "withdrawals"}],
            },
            "financial": {
                "title": "Financeiro (Receita Real)",
                "problem": (f"Realização: {realization:.1f}% · "
                             f"R$ {act_total:,.2f} / "
                             f"R$ {exp_total:,.2f}"),
                "cause": "Outcomes ainda não confirmados como pagos",
                "impact": (f"R$ {exp_total - act_total:,.2f} ainda "
                           f"pendentes de conciliação"),
                "action": ("Rodar reconcile_with_cash + manual "
                           "mark_received para outcomes "
                           "confirmados"),
                "confidence": 0.95,
                "score": realization,
                "evidence": [
                    {"type": "expected_BRL_total", "value": exp_total,
                     "source": "motor_ia_outcomes"},
                    {"type": "actual_BRL_total", "value": act_total,
                     "source": "motor_ia_outcomes"}],
            },
        },
        "overall_score": round(
            (net_health + infra_score + (
                (sk["installs"]["quality_score_pct"]
                 + sk["repairs"]["truck_roll_avoidance_pct"]
                 + sk["withdrawals"]["asset_recovery_score_pct"]) / 3)
             + realization) / 4, 1),
        "generated_at": _now_iso(),
    }
