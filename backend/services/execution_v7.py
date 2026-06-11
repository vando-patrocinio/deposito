"""
execution_v7.py — CONSTITUIÇÃO V7.0 — EXECUÇÃO REAL & PROVA DE VALOR

Sem novos módulos/scores/IAs/telas. Apenas:
  - Fase 1: pré-OS + pós-OS (predict_install / predict_repair /
    score_withdrawal) — reusa SmartOLT existente + heurística
  - Fase 2: backfill tickets.category INSTALL/REPAIR/WITHDRAW
    e assigned_to default por regra (não cria classifier novo)
  - Fase 3: webhook financeiro genérico → mark_received → cash real
  - Fase 4: operação_tese_run_batch (homolog-aware) com auditoria
  - Fase 6: proof_of_value_30d (9 KPIs canônicos)

Toda função responde SIM a ≥1: aumenta receita · reduz churn · reduz
custo · reduz truck roll · melhora produtividade · sem intervenção.
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

import re
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from database import db

logger = logging.getLogger("execution_v7")
ISO = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731
CUTOFF = lambda d: (datetime.now(timezone.utc)  # noqa: E731
                    - timedelta(days=d)).isoformat()


# ═══════════════════════════════════════════════════════════
# FASE 2 — Backfill tickets.category + assigned_to
# ═══════════════════════════════════════════════════════════
_RX_INSTALL = re.compile(
    r"\b(instal(a(ç|c)?ão|acao|ar)?|ativa(ç|c)ao|nov[ao]\s+cliente)\b",
    re.I)
_RX_REPAIR = re.compile(
    r"\b(repar|manuten|sem\s+sinal|len(t|tid)|wifi|conex|los|"
    r"power\s*fail|offline)\b",
    re.I)
_RX_WITHDRAW = re.compile(
    r"\b(retir(ada|ar)|withdraw|desinstal|cancelamento\s+ativo)\b",
    re.I)


def classify_ticket(t: Dict[str, Any]) -> Optional[str]:
    """Classifica em INSTALL/REPAIR/WITHDRAW por regex no
    subject+description+category. Conservador: só retorna se há
    evidência clara."""
    blob = " ".join([
        str(t.get("category") or ""),
        str(t.get("subject") or ""),
        str(t.get("description") or ""),
    ])
    if _RX_INSTALL.search(blob):
        return "INSTALL"
    if _RX_WITHDRAW.search(blob):
        return "WITHDRAW"
    if _RX_REPAIR.search(blob):
        return "REPAIR"
    return None


async def backfill_tickets(
    company_id: str, window_days: int = 90,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Popula tickets.category nos vazios usando regex. Idempotente."""
    cutoff = CUTOFF(window_days)
    q = {"company_id": company_id,
         "opened_at": {"$gte": cutoff},
         "$or": [{"category": {"$exists": False}},
                 {"category": None}, {"category": ""},
                 {"category": {"$nin": ["INSTALL", "REPAIR",
                                         "WITHDRAW"]}}]}
    counts = {"INSTALL": 0, "REPAIR": 0, "WITHDRAW": 0, "skipped": 0}
    examined = 0
    async for t in db.tickets.find(q).limit(5000):
        examined += 1
        kind = classify_ticket(t)
        if not kind:
            counts["skipped"] += 1
            continue
        counts[kind] += 1
        if not dry_run:
            await db.tickets.update_one(
                {"id": t["id"]},
                {"$set": {"category": kind,
                          "category_source": "v7_backfill",
                          "category_backfilled_at": ISO()}})
    return {"company_id": company_id, "window_days": window_days,
            "dry_run": dry_run, "examined": examined,
            "classified": counts, "generated_at": ISO()}


# ═══════════════════════════════════════════════════════════
# FASE 1 — Smart Field Ops PRE/POS (reusa SmartOLT existente)
# ═══════════════════════════════════════════════════════════
async def predict_install_resources(
    company_id: str, subscriber_id: str,
) -> Dict[str, Any]:
    """Pré-OS: sugere CTO/porta/splitter/cabo/potência baseado em
    subs vizinhos da zona com mesmo plano. NÃO usa LLM — heurística."""
    sub = await db.subscribers.find_one(
        {"id": subscriber_id, "company_id": company_id})
    if not sub:
        return {"error": "subscriber_not_found",
                "subscriber_id": subscriber_id}
    zone = sub.get("smartolt_onu_zone")
    plan_price = float(sub.get("plan_price") or 0)
    # Vizinhos na mesma zona com ONU online (para mediar potência)
    near_sigs: List[float] = []
    if zone:
        async for n in db.smartolt_onus.find({
            "company_id": company_id, "zone_name": zone,
            "status": "Online",
        }, {"signal_1310": 1}).limit(50):
            try:
                near_sigs.append(float(
                    str(n.get("signal_1310")).replace(",", ".")))
            except (TypeError, ValueError):
                continue
    avg_signal = (sum(near_sigs) / len(near_sigs)) if near_sigs else -25
    # Heurística: cabo (m) ~ função do nº de subs já na zona
    same_zone = await db.subscribers.count_documents({
        "company_id": company_id,
        "smartolt_onu_zone": zone}) if zone else 0
    # Portas ocupadas na CTO atual
    occupied = await db.client_equipment_history.count_documents({
        "company_id": company_id, "action": "install"})
    splitter = "1x8" if same_zone < 8 else "1x16"
    return {
        "subscriber_id": subscriber_id,
        "predicted": {
            "cto_zone": zone or "to_assign_by_field",
            "splitter_recommended": splitter,
            "cable_meters_estimate": min(200,
                                          50 + same_zone * 5),
            "expected_signal_1310_dbm": round(avg_signal, 1),
            "tech_minutes_estimate": 90 if plan_price < 100 else 120,
            "materials": ["ONT", "drop_cable",
                          "connector_sc_apc x2",
                          "fixing_kit"],
            "confidence": 0.65 if near_sigs else 0.4,
        },
        "based_on": {"neighbor_signal_samples": len(near_sigs),
                     "subs_in_zone": same_zone,
                     "occupied_ports_total": occupied},
        "generated_at": ISO(),
    }


async def predict_repair_outcome(
    company_id: str, ticket_id: str,
) -> Dict[str, Any]:
    """Pré-visita: probabilidade de resolução remota vs truck roll."""
    t = await db.tickets.find_one(
        {"id": ticket_id, "company_id": company_id})
    if not t:
        return {"error": "ticket_not_found"}
    cid = t.get("client_id")
    sub = await db.subscribers.find_one({"id": cid}) if cid else None
    onu_status = (sub or {}).get("smartolt_onu_status") or "Unknown"
    bad = onu_status.lower() in (
        "offline", "los", "power fail", "power_fail")
    # Histórico de tickets do mesmo client
    n90 = await db.tickets.count_documents({
        "company_id": company_id, "client_id": cid,
        "opened_at": {"$gte": CUTOFF(90)}}) if cid else 0
    # Heurística:
    # ONU bad → truck roll quase certo
    # ONU online + poucos tickets → remoto provável
    if bad:
        p_remote = 0.10
        recommended = "DESPACHAR_TECNICO"
        cause = (f"ONU em {onu_status} — reboot remoto inútil")
    elif n90 == 0:
        p_remote = 0.75
        recommended = "DIAGNOSTICO_REMOTO_PRIMEIRO"
        cause = "ONU online + cliente sem histórico recente"
    elif n90 >= 3:
        p_remote = 0.30
        recommended = "DESPACHAR_TECNICO"
        cause = (f"{n90} tickets em 90d sugere problema recorrente")
    else:
        p_remote = 0.55
        recommended = "DIAGNOSTICO_REMOTO_PRIMEIRO"
        cause = (f"ONU online + histórico moderado ({n90} tickets/90d)")
    return {
        "ticket_id": ticket_id, "client_id": cid,
        "probable_cause": cause,
        "p_remote_resolution": p_remote,
        "return_risk": round(min(1.0, n90 / 5.0), 2),
        "should_send_tech":
            p_remote < 0.5 or recommended == "DESPACHAR_TECNICO",
        "recommended_action": recommended,
        "confidence": 0.75,
        "evidence": [
            {"type": "onu_status", "value": onu_status},
            {"type": "tickets_90d", "value": n90}],
        "generated_at": ISO(),
    }


async def audit_install(
    company_id: str, install_id: str,
) -> Dict[str, Any]:
    """Pós-OS: valida campos obrigatórios da instalação inteligente."""
    rec = await db.smart_installs.find_one(
        {"id": install_id, "company_id": company_id})
    if not rec:
        return {"error": "install_not_found"}
    required = ("photos_count", "ont_sn",
                "geo_check_in", "tech_id")
    missing = [k for k in required
               if not rec.get(k)]
    signal_ok = (
        rec.get("signal_after_install_dbm") is not None
        and -27 <= float(rec.get("signal_after_install_dbm", 0)) <= -8)
    quality = 100 - len(missing) * 20 - (0 if signal_ok else 15)
    quality = max(0, min(100, quality))
    return {
        "install_id": install_id,
        "missing_fields": missing,
        "signal_ok": signal_ok,
        "installation_quality_audit_score": quality,
        "audit_passed": quality >= 80,
        "generated_at": ISO(),
    }


# ═══════════════════════════════════════════════════════════
# FASE 3 — ACTION TO CASH (webhook genérico + matcher)
# ═══════════════════════════════════════════════════════════
async def payment_received(
    company_id: str, *,
    client_id: Optional[str] = None,
    amount_BRL: float,
    provider: str = "unknown",
    payment_ref: Optional[str] = None,
    paid_at: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Webhook genérico (Asaas/PIX/Pagar.me/etc.) → fecha o ciclo
    Action→Cash. Encontra outcome correspondente e marca como
    revenue_received. Persiste comprovante em wa_payments_received."""
    from services import company_v6 as v6
    amount = max(0.0, float(amount_BRL))
    rec_id = f"pay-{uuid.uuid4().hex[:12]}"
    receipt = {
        "id": rec_id, "company_id": company_id,
        "client_id": client_id, "amount_BRL": amount,
        "provider": provider, "payment_ref": payment_ref,
        "paid_at": paid_at or ISO(),
        "metadata": metadata or {},
        "matched_outcome_id": None,
        "created_at": ISO(),
    }
    matched = None
    if client_id:
        # Busca outcome aberto do mesmo subscriber com expected
        # próximo do amount (±20%)
        async for oc in db.motor_ia_outcomes.find({
            "company_id": company_id, "subscriber_id": client_id,
            "environment": {"$ne": "homolog"},
            "status": {"$ne": "revenue_received"},
            "expected_BRL": {"$gt": 0},
        }).sort("observed_at", -1).limit(20):
            exp = float(oc.get("expected_BRL") or 0)
            if amount > 0 and 0.8 <= (amount / exp) <= 1.2:
                matched = oc
                break
    if matched:
        await v6.mark_revenue_received(
            company_id, matched["id"], amount,
            source=f"payment_webhook:{provider}",
            payment_ref=payment_ref)
        receipt["matched_outcome_id"] = matched["id"]
    await db.payments_received.insert_one(receipt)
    return {"receipt_id": rec_id, "matched_outcome_id":
            receipt["matched_outcome_id"], "amount_BRL": amount,
            "provider": provider, "generated_at": ISO()}


# ═══════════════════════════════════════════════════════════
# FASE 4 — OPERAÇÃO TESE BATCH CONTROLADA
# ═══════════════════════════════════════════════════════════
async def operacao_tese_run_batch(
    company_id: str, batch_size: int = 10,
) -> Dict[str, Any]:
    """Roda lote pequeno em MODO HOMOLOGAÇÃO (V5.3 garantido).
    Para cada outcome com expected_BRL>0 não recebido: dispara
    safe_send_whatsapp via gateway homolog."""
    from services import homologation as homo
    if not homo.is_homolog():
        return {"error": "homolog_required_for_safety"}
    cands = await db.motor_ia_outcomes.find({
        "company_id": company_id,
        "environment": {"$ne": "homolog"},
        "status": {"$ne": "revenue_received"},
        "expected_BRL": {"$gt": 0},
    }).sort("observed_at", -1).limit(batch_size).to_list(batch_size)
    sent = blocked = 0
    audit: List[Dict[str, Any]] = []
    for oc in cands:
        out = await homo.safe_send_whatsapp(
            company_id=company_id,
            target_phone="11999999999",  # será redirecionado
            message=(f"Olá! Sua cobrança de "
                     f"R$ {oc.get('expected_BRL', 0):.2f} está "
                     "disponível para pagamento via PIX."),
            origin="operacao_tese_real_v7",
            client_context={"name": "Cliente Real",
                            "phone": "11999999999",
                            "document": "OCULTO"},
            decision_id=oc.get("decision_id"),
            action_id=oc.get("action_id"))
        sent += 1
        if out["blocked"]:
            blocked += 1
        audit.append({
            "outcome_id": oc.get("id"),
            "wa_id": out["id"],
            "blocked": out["blocked"],
            "expected_BRL": oc.get("expected_BRL"),
        })
    return {
        "company_id": company_id,
        "batch_size": batch_size,
        "candidates_found": len(cands),
        "messages_sent": sent,
        "blocked_redirected": blocked,
        "all_redirected_to_test_phone": blocked == sent,
        "audit": audit,
        "generated_at": ISO(),
    }


# ═══════════════════════════════════════════════════════════
# FASE 6 — 30 DIAS DE PROVA (9 KPIs canônicos)
# ═══════════════════════════════════════════════════════════
async def proof_of_value(
    company_id: str, window_days: int = 30,
) -> Dict[str, Any]:
    """Os 9 KPIs canônicos da Definição de Sucesso V7."""
    cutoff = CUTOFF(window_days)
    # 1) Receita recuperada (actual_BRL real)
    rev_agg = await db.motor_ia_outcomes.aggregate([
        {"$match": {"company_id": company_id,
                    "environment": {"$ne": "homolog"},
                    "status": "revenue_received",
                    "received_at": {"$gte": cutoff}}},
        {"$group": {"_id": None, "total": {"$sum": "$actual_BRL"},
                    "n": {"$sum": 1}}}
    ]).to_list(1)
    recovered_BRL = float(rev_agg[0]["total"]) if rev_agg else 0.0
    recovered_n = int(rev_agg[0]["n"]) if rev_agg else 0
    # 2) Receita protegida (CRITICO)
    prot_agg = await db.motor_ia_failure_risk_scores.aggregate([
        {"$match": {"company_id": company_id,
                    "score": {"$gt": 80},
                    "computed_at": {"$gte": cutoff}}},
        {"$group": {"_id": None,
                    "total": {
                        "$sum": "$expected_revenue_at_risk_BRL"}}}
    ]).to_list(1)
    protected_BRL = float(prot_agg[0]["total"]) if prot_agg else 0.0
    # 3) Churn evitado (proxy: clientes que estavam CRITICO e ainda
    #    estão ativos)
    crit_ids = await db.motor_ia_failure_risk_scores.distinct(
        "subscriber_id",
        {"company_id": company_id, "score": {"$gt": 80},
         "computed_at": {"$gte": cutoff}})
    still_active = 0
    if crit_ids:
        still_active = await db.subscribers.count_documents({
            "company_id": company_id, "id": {"$in": crit_ids},
            "status": {"$ne": "inactive"}})
    # 4) Truck Rolls evitados
    truck_avoided = await db.smart_repairs.count_documents({
        "company_id": company_id,
        "created_at": {"$gte": cutoff},
        "truck_roll_avoided": True})
    # 5) Tempo médio de reparo
    avg_repair_h = 0
    closed_repairs = await db.tickets.find({
        "company_id": company_id, "category": "REPAIR",
        "opened_at": {"$gte": cutoff},
        "closed_at": {"$exists": True}}, {"opened_at": 1,
                                          "closed_at": 1}
    ).to_list(500)
    if closed_repairs:
        dur = []
        for r in closed_repairs:
            try:
                o = datetime.fromisoformat(r["opened_at"])
                c = datetime.fromisoformat(r["closed_at"])
                dur.append((c - o).total_seconds() / 3600.0)
            except Exception:
                continue
        avg_repair_h = (sum(dur) / len(dur)) if dur else 0
    # 6) First Time Fix
    inst_total = await db.smart_installs.count_documents({
        "company_id": company_id, "created_at": {"$gte": cutoff}})
    inst_ftc = await db.smart_installs.count_documents({
        "company_id": company_id, "created_at": {"$gte": cutoff},
        "first_time_complete": True})
    ftc_pct = (inst_ftc / max(inst_total, 1)) * 100
    # 7) Recuperação de ativos
    wd_total = await db.smart_withdrawals.count_documents({
        "company_id": company_id, "created_at": {"$gte": cutoff}})
    wd_rec = await db.smart_withdrawals.count_documents({
        "company_id": company_id, "created_at": {"$gte": cutoff},
        "asset_recovered": True})
    asset_pct = (wd_rec / max(wd_total, 1)) * 100
    # 8) Eficiência técnica (autonomous cycles completos / total)
    cyc_total = await db.motor_ia_autonomous_cycles.count_documents({
        "company_id": company_id, "started_at": {"$gte": cutoff}})
    cyc_done = await db.motor_ia_autonomous_cycles.count_documents({
        "company_id": company_id,
        "started_at": {"$gte": cutoff},
        "status": "complete"})
    cyc_pct = (cyc_done / max(cyc_total, 1)) * 100
    # 9) ROI da IA (recovered + protected * fator)
    roi = recovered_BRL + (protected_BRL * 0.3)

    # Definição de sucesso V7 — 6 critérios
    success_v7 = {
        "gera_receita_real": recovered_BRL > 0,
        "evita_churn_real": still_active > 0,
        "reduz_custo_operacional":
            truck_avoided > 0 or ftc_pct >= 70,
        "reduz_truck_roll_real": truck_avoided > 0,
        "melhora_produtividade_tecnica": cyc_pct >= 80,
        "operacao_continua_sem_intervencao": cyc_pct >= 80,
    }
    success_count = sum(1 for v in success_v7.values() if v)

    return {
        "company_id": company_id, "window_days": window_days,
        "kpis": {
            "receita_recuperada_BRL": round(recovered_BRL, 2),
            "outcomes_pagos": recovered_n,
            "receita_protegida_BRL": round(protected_BRL, 2),
            "churn_evitado_clientes_ainda_ativos": still_active,
            "truck_rolls_evitados": truck_avoided,
            "tempo_medio_reparo_horas": round(avg_repair_h, 1),
            "first_time_fix_pct": round(ftc_pct, 1),
            "recuperacao_ativos_pct": round(asset_pct, 1),
            "eficiencia_tecnica_ciclos_pct": round(cyc_pct, 1),
            "roi_da_ia_BRL": round(roi, 2),
        },
        "success_definition_v7": success_v7,
        "success_score": f"{success_count}/6",
        "ready_for_commercial_product": success_count >= 5,
        "generated_at": ISO(),
    }
