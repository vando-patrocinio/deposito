"""
autonomous_engine.py — FASE 10 V5.0 (Ordem Executiva)
Núcleo do SmartProv Autônomo.
Loop:   Evento → Análise → Decisão → Ação → Resultado → Aprendizado → Melhoria
Sem intervenção humana. Cada etapa é PERSISTIDA e AUDITÁVEL.
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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db

# ---------- helpers ---------- #
def _now(): return datetime.now(timezone.utc)
def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat()
def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ---------- Step 1: ANALYSIS ---------- #
async def _analyze_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Recolhe contexto: subscriber, Isabella score, network state, plan_price."""
    co = event.get("company_id")
    sid = event.get("subscriber_id") or event.get("payload", {}).get(
        "subscriber_id")

    ctx: Dict[str, Any] = {
        "analysis_id": _uid("ana"),
        "event_id": event["event_id"],
        "company_id": co,
        "subscriber_id": sid,
        "created_at": _iso(),
    }

    if sid:
        sub = await db.subscribers.find_one(
            {"id": sid, "company_id": co},
            {"plan_price": 1, "status": 1, "smartolt_onu_status": 1,
             "smartolt_onu_zone": 1, "activation_date": 1})
        if sub:
            ctx["plan_price_BRL"] = float(sub.get("plan_price") or 0)
            ctx["subscriber_status"] = sub.get("status")
            ctx["onu_status"] = sub.get("smartolt_onu_status")
            ctx["onu_zone"] = sub.get("smartolt_onu_zone")
        score = await db.motor_ia_subscriber_scores.find_one(
            {"subscriber_id": sid, "company_id": co})
        if score:
            ctx["churn_score"] = score.get("churn_score")
            ctx["upgrade_score"] = score.get("upgrade_score")
            ctx["buy_score"] = score.get("buy_score")
            ctx["nba"] = score.get("next_best_action")

    # invoices overdue ?
    if sid:
        ctx["overdue_count"] = await db.subscriber_invoices.count_documents(
            {"company_id": co, "subscriber_document":
             (await db.subscribers.find_one({"id": sid},
                                              {"document": 1}) or {}
              ).get("document"),
             "status": "overdue"})

    await db.motor_ia_analysis.insert_one(dict(ctx))
    return ctx


async def _kg_lookup(company_id: str,
                      cause_hint: str) -> Dict[str, Any]:
    """Consulta o Knowledge Graph: busca padrões similares.
    Retorna confidence_boost baseado em sucessos passados."""
    if not cause_hint:
        return {"matches": 0, "confidence_boost": 0.0,
                "kg_evidence": []}
    import re as _re
    pattern = _re.escape(cause_hint[:30])
    rows = await db.motor_ia_knowledge_graph.find(
        {"company_id": company_id,
          "cause": {"$regex": pattern, "$options": "i"}}
    ).limit(10).to_list(10)
    if not rows:
        return {"matches": 0, "confidence_boost": 0.0,
                "kg_evidence": []}
    success = sum(1 for r in rows
                  if (r.get("outcome") or "").startswith("success"))
    boost = min(success / len(rows) * 0.15, 0.15)
    evidence = [{"type": "kg_pattern", "value": r.get("pattern_id")}
                  for r in rows[:3]]
    return {"matches": len(rows), "confidence_boost": boost,
              "kg_evidence": evidence}


# ---------- Step 2: DECISION ---------- #
def _decide(event: Dict[str, Any],
            analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Engine de regras determinístico → escolhe ação + estima impacto.
    Regras V5.0:
      - overdue >= 1 + plan_price > 0  → run_operacao_tese_tier_c
      - churn_score >= 0.7              → run_retention_campaign
      - onu_status offline + ativo     → create_preventive_ticket
      - upgrade_score >= 0.7           → run_upgrade_offer
    """
    et = event.get("event_type", "")
    price = analysis.get("plan_price_BRL", 0)
    churn = analysis.get("churn_score") or 0
    upgrade = analysis.get("upgrade_score") or 0
    overdue = analysis.get("overdue_count", 0)
    onu = analysis.get("onu_status")

    decision = {
        "decision_id": _uid("dec"),
        "analysis_id": analysis["analysis_id"],
        "event_id": event["event_id"],
        "company_id": event["company_id"],
        "created_at": _iso(),
        "cause": "",
        "effect": "",
        "impact": "",
        "recommended_action": "",
        "evidence": [],
        "confidence": 0.0,
        "expected_BRL": 0.0,
        "action_kind": None,
        "action_payload": {},
    }

    # Priorização por EVENT TYPE primeiro (intencional), depois fallback heurístico
    if et == "FAILURE_RISK_HIGH":
        p = (event.get("payload") or {})
        frs = float(p.get("failure_risk_score") or 0)
        raw = p.get("raw") or {}
        revenue_risk = float(p.get("expected_revenue_at_risk_BRL") or 0)
        cause_parts = []
        if (raw.get("onu_status") or "").lower() in (
                "los", "offline", "power fail", "power_fail"):
            cause_parts.append(f"ONU em {raw['onu_status']}")
        if raw.get("rx_dbm") is not None and raw["rx_dbm"] <= -27:
            cause_parts.append(f"sinal {raw['rx_dbm']}dBm")
        if (raw.get("recurrence_score") or 0) > 60:
            cause_parts.append(
                f"recurrence={raw['recurrence_score']:.0f}")
        if (raw.get("cto_score") or 100) < 70:
            cause_parts.append(
                f"CTO {raw.get('cto', '?')} score={raw['cto_score']:.0f}")
        cause = (
            f"failure_risk_score={frs:.0f} (CRÍTICO) · "
            + " · ".join(cause_parts)
        ).strip(" ·")
        decision.update({
            "cause": cause,
            "effect": (
                "Cliente provavelmente abrirá ticket ou cancelará "
                "nos próximos 7 dias."),
            "impact": (
                f"Receita em risco: R$ {revenue_risk:.2f}/mês. "
                f"Ação preventiva poupa visita reativa + churn."),
            "recommended_action": (
                "Abrir OS preventiva e despachar técnico antes do "
                "cliente reclamar."),
            "evidence": [
                {"type": "failure_risk_score", "value": frs},
                {"type": "onu_status",
                 "value": raw.get("onu_status")},
                {"type": "rx_dbm", "value": raw.get("rx_dbm")},
                {"type": "recurrence_score",
                 "value": raw.get("recurrence_score")},
                {"type": "cto_score", "value": raw.get("cto_score")},
                {"type": "churn_score", "value": raw.get("churn_score")},
            ],
            "confidence": min(0.70 + (frs - 80) / 100, 0.95),
            "expected_BRL": round(revenue_risk * 0.6, 2),
            "action_kind": "preventive_ticket",
            "action_payload": {
                "subscriber_id": analysis["subscriber_id"],
                "priority": "ALTA",
                "origin": "failure_risk_high",
                "failure_risk_score": frs,
            },
        })
    elif et == "ONU_DEGRADED" and price > 0:
        decision.update({
            "cause": f"ONU em estado {onu or 'degradado'}",
            "effect": "Cliente provavelmente sem serviço",
            "impact": "Risco de ticket reativo + degradação NPS + risco churn",
            "recommended_action": "Visita técnica preventiva",
            "evidence": [
                {"type": "onu_status", "value": onu},
                {"type": "onu_zone", "value": analysis.get("onu_zone")},
            ],
            "confidence": 0.80,
            "expected_BRL": round(price * 0.3, 2),
            "action_kind": "preventive_ticket",
            "action_payload": {"subscriber_id": analysis["subscriber_id"],
                                "priority": "ALTA"},
        })
    elif et == "OVERDUE_DETECTED" and price > 0:
        decision.update({
            "cause": f"Fatura(s) vencidas detectada(s) · {overdue}",
            "effect": "Receita represada",
            "impact": f"Risco mensal R$ {price:.2f} sem cobrança",
            "recommended_action": "Operação Tese Tier C (WA blindado)",
            "evidence": [
                {"type": "overdue_count", "value": overdue},
                {"type": "plan_price", "value": price},
            ],
            "confidence": 0.85,
            "expected_BRL": round(price * 0.18, 2),
            "action_kind": "operacao_tese_tier_c",
            "action_payload": {"subscriber_id": analysis["subscriber_id"]},
        })
    elif et == "ISABELLA_HIGH_CHURN" or churn >= 0.7:
        decision.update({
            "cause": f"Isabella detectou churn_score={churn:.2f}",
            "effect": f"Risco real de cancelamento · R$ {price:.2f}/mês",
            "impact": (f"Perda potencial R$ {price * 12:.2f}/ano + LTV restante"),
            "recommended_action": "Retenção proativa (desconto + contato)",
            "evidence": [{"type": "churn_score", "value": churn}],
            "confidence": min(churn or 0.7, 0.95),
            "expected_BRL": round(price * 0.6, 2),
            "action_kind": "retention_campaign",
            "action_payload": {"subscriber_id": analysis["subscriber_id"],
                                "discount_pct": 30},
        })
    elif et == "ISABELLA_RETENTION_OPPORTUNITY":
        rs = (event.get("payload") or {}).get("retention_score", 0.7)
        decision.update({
            "cause": f"Isabella retention_score={rs:.2f}",
            "effect": "Cliente fidelizável com pequeno incentivo",
            "impact": f"Preservar R$ {price * 12:.2f}/ano de LTV",
            "recommended_action": "Programa fidelidade · oferta nicho",
            "evidence": [{"type": "retention_score", "value": rs}],
            "confidence": min(rs, 0.92),
            "expected_BRL": round(price * 0.4, 2),
            "action_kind": "retention_campaign",
            "action_payload": {"subscriber_id": analysis["subscriber_id"],
                                "discount_pct": 15},
        })
    elif et == "ISABELLA_REFERRAL_OPPORTUNITY":
        rs = (event.get("payload") or {}).get("referral_score", 0.7)
        decision.update({
            "cause": f"Isabella referral_score={rs:.2f}",
            "effect": "Cliente promotor potencial",
            "impact": (f"CAC evitado · 1 indicação ≈ R$ {price * 3:.2f}"),
            "recommended_action": "Convite programa Cliente Indica",
            "evidence": [{"type": "referral_score", "value": rs}],
            "confidence": min(rs, 0.92),
            "expected_BRL": round(price * 1.5, 2),
            "action_kind": "referral_invite",
            "action_payload": {"subscriber_id": analysis["subscriber_id"]},
        })
    elif et == "ISABELLA_COLLECTION_OPPORTUNITY":
        rs = (event.get("payload") or {}).get("collection_score", 0.7)
        decision.update({
            "cause": f"Isabella collection_score={rs:.2f}",
            "effect": "Cliente com probabilidade alta de inadimplência",
            "impact": f"Risco de receita represada R$ {price:.2f}",
            "recommended_action": "Lembrete proativo + facilitação",
            "evidence": [{"type": "collection_score", "value": rs}],
            "confidence": min(rs, 0.92),
            "expected_BRL": round(price * 0.85, 2),
            "action_kind": "operacao_tese_tier_c",
            "action_payload": {"subscriber_id": analysis["subscriber_id"]},
        })
    elif overdue >= 1 and price > 0:
        decision.update({
            "cause": "Fatura(s) vencidas detectada(s)",
            "effect": f"Receita represada · {overdue} fatura(s)",
            "impact": f"Risco mensal R$ {price:.2f} sem cobrança",
            "recommended_action": "Operação Tese Tier C (WA blindado)",
            "evidence": [
                {"type": "overdue_count", "value": overdue},
                {"type": "plan_price", "value": price},
            ],
            "confidence": 0.85,
            "expected_BRL": round(price * 0.18, 2),
            "action_kind": "operacao_tese_tier_c",
            "action_payload": {"subscriber_id": analysis["subscriber_id"]},
        })
    elif onu in ("Offline", "LOS", "Power fail") and analysis.get(
            "subscriber_status") == "ATIVO":
        decision.update({
            "cause": f"ONU em estado {onu}",
            "effect": "Cliente provavelmente sem serviço",
            "impact": "Risco de ticket reativo + degradação NPS + risco churn",
            "recommended_action": "Visita técnica preventiva",
            "evidence": [
                {"type": "onu_status", "value": onu},
                {"type": "onu_zone", "value": analysis.get("onu_zone")},
            ],
            "confidence": 0.80,
            "expected_BRL": round(price * 0.3, 2),
            "action_kind": "preventive_ticket",
            "action_payload": {"subscriber_id": analysis["subscriber_id"],
                                "priority": "ALTA"},
        })
    elif upgrade >= 0.7:
        decision.update({
            "cause": f"Isabella detectou upgrade_score={upgrade:.2f}",
            "effect": "Cliente sinalizou potencial para plano superior",
            "impact": f"Upside R$ {price * 0.5:.2f}/mês com upgrade",
            "recommended_action": "Oferta de upgrade automática",
            "evidence": [{"type": "upgrade_score", "value": upgrade}],
            "confidence": min(upgrade, 0.95),
            "expected_BRL": round(price * 0.5, 2),
            "action_kind": "upgrade_offer",
            "action_payload": {"subscriber_id": analysis["subscriber_id"]},
        })
    else:
        decision.update({
            "cause": f"Evento {et} sem ação rentável associada",
            "effect": "Sem ação automática gerada",
            "impact": "Nenhum impacto financeiro",
            "recommended_action": "Aguardar próximo sinal",
            "evidence": [],
            "confidence": 0.20,
            "expected_BRL": 0.0,
            "action_kind": "noop",
        })
    return decision


# ---------- Step 3: ACTION ---------- #
async def _execute_action(decision: Dict[str, Any]) -> Dict[str, Any]:
    """Executa a ação respeitando confidence ≥0.6 e transport_check."""
    action = {
        "action_id": _uid("act"),
        "decision_id": decision["decision_id"],
        "event_id": decision["event_id"],
        "company_id": decision["company_id"],
        "kind": decision["action_kind"],
        "payload": decision.get("action_payload") or {},
        "status": "queued",
        "created_at": _iso(),
        "executed_at": None,
        "result": None,
    }
    kind = decision["action_kind"]
    confidence = decision.get("confidence", 0)

    # Confidence gate (V5.0 sprint final)
    if kind != "noop" and confidence < 0.6:
        action["status"] = "recommend_only"
        action["result"] = {
            "reason": f"confidence={confidence:.2f} < 0.6 → não autônomo",
            "channel": "recommendation",
        }
        await db.motor_ia_actions.insert_one(dict(action))
        return action

    if kind == "preventive_ticket":
        # cria ticket técnico real (não depende de transporte WA)
        sid = decision["action_payload"]["subscriber_id"]
        ticket_id = _uid("tk")
        ticket_doc = {
            "id": ticket_id, "company_id": decision["company_id"],
            "client_id": sid,
            "status": "aberta",
            "priority": decision["action_payload"].get("priority", "MEDIA"),
            "title": "Ticket preventivo · Autonomous Engine",
            "description": (
                f"Gerado autonomamente pelo SmartProv AutonomousEngine. "
                f"Causa: {decision['cause']}. "
                f"Ação: {decision['recommended_action']}."),
            "origin": "autonomous_engine",
            "created_at": _iso(),
        }
        # CTO 11/06/2026: TODOS os tickets sistêmicos vão para a SALA por padrão.
        # Sem isso, o ticket cai com assigned_collaborator_id=None e some da Lousa.
        try:
            from services.sala_router import route_to_sala
            await route_to_sala(ticket_doc, reason="autonomous_engine")
        except Exception as _e:
            import logging
            logging.getLogger("autonomous_engine").warning(
                "route_to_sala falhou: %s", _e
            )
        await db.tickets.insert_one(ticket_doc)
        action["status"] = "executed"
        action["executed_at"] = _iso()
        action["result"] = {"ticket_id": ticket_id}

    elif kind in ("operacao_tese_tier_c", "retention_campaign",
                    "upgrade_offer", "referral_invite"):
        # Ação financeira: depende do transporte WA aberto
        from services.transport_check import wa_status
        tx = await wa_status(decision["company_id"])
        if not tx["can_send"]:
            action["status"] = "blocked_transport"
            action["result"] = {
                "reason": "WhatsApp não está OPEN em produção",
                "blockers": tx["blockers"],
                "transport": tx["status"],
            }
        else:
            # Dispara via wa_dispatcher real
            from services import wa_dispatcher
            sid = (decision.get("action_payload") or {}).get(
                "subscriber_id")
            sub = await db.subscribers.find_one(
                {"id": sid, "company_id": decision["company_id"]},
                {"phone": 1, "name": 1})
            phone = (sub or {}).get("phone") or ""
            text = (f"Olá {(sub or {}).get('name','cliente')}, "
                      f"{decision['recommended_action']}.")
            if phone:
                send = await wa_dispatcher.send_text(
                    company_id=decision["company_id"],
                    to=phone, text=text)
                if send.get("ok"):
                    action["status"] = "dispatched"
                    action["executed_at"] = _iso()
                    action["result"] = {
                        "channel": "whatsapp", "wa_id": send.get("id")}
                else:
                    action["status"] = "blocked_transport"
                    action["result"] = {
                        "reason": send.get("reason"),
                        "transport": "WA_SEND_FAILED"}
            else:
                action["status"] = "blocked_data"
                action["result"] = {"reason": "subscriber sem telefone"}

    elif kind == "noop":
        action["status"] = "noop"
        action["executed_at"] = _iso()

    await db.motor_ia_actions.insert_one(dict(action))
    return action


# ---------- Step 4: OUTCOME ---------- #
async def _observe_outcome(decision: Dict[str, Any],
                            action: Dict[str, Any]) -> Dict[str, Any]:
    """Observa resultado. Para ciclo demo, snapshot inicial; outcome real
    chega via worker assíncrono (reconcile_outcomes) horas/dias depois."""
    co = decision["company_id"]
    sid = (decision.get("action_payload") or {}).get("subscriber_id")
    actual = 0.0
    notes = []
    if sid:
        # 1) overdue diminuiu = pagamento aconteceu (cobrança funcionou)
        sub = await db.subscribers.find_one({"id": sid}, {"document": 1})
        if sub and sub.get("document"):
            paid_after = await db.subscriber_invoices.count_documents({
                "company_id": co, "subscriber_document": sub["document"],
                "status": "paid", "paid_date": {"$gte": action["created_at"]}})
            if paid_after > 0:
                actual_paid = await db.subscriber_invoices.aggregate([
                    {"$match": {"company_id": co,
                                  "subscriber_document": sub["document"],
                                  "status": "paid",
                                  "paid_date": {
                                      "$gte": action["created_at"]}}},
                    {"$group": {"_id": None, "t": {"$sum": "$amount"}}},
                ]).to_list(1)
                actual = float(actual_paid[0]["t"]) if actual_paid else 0
                notes.append(f"Receita coletada após ação: R$ {actual:.2f}")
        # 2) Ticket preventivo encerrado?
        if action["kind"] == "preventive_ticket":
            tkid = (action.get("result") or {}).get("ticket_id")
            if tkid:
                tk = await db.tickets.find_one({"id": tkid}, {"status": 1})
                notes.append(f"Ticket {tkid} status={tk.get('status') if tk else 'n/a'}")
    outcome = {
        "outcome_id": _uid("out"),
        "action_id": action["action_id"],
        "decision_id": decision["decision_id"],
        "company_id": co,
        "observed_at": _iso(),
        "actual_BRL": round(actual, 2),
        "expected_BRL": decision.get("expected_BRL", 0.0),
        "notes": notes,
    }
    await db.motor_ia_outcomes.insert_one(dict(outcome))
    return outcome


# ---------- Step 5: LEARNING ---------- #
async def _learn(decision: Dict[str, Any],
                  action: Dict[str, Any],
                  outcome: Dict[str, Any]) -> Dict[str, Any]:
    expected = decision.get("expected_BRL", 0.0)
    actual = outcome.get("actual_BRL", 0.0)
    delta = actual - expected
    accuracy = (min(actual / expected, 1.0) * 100
                if expected > 0 else (100.0 if actual >= 0 else 0.0))
    worked = action["status"] in ("executed", "dispatched")
    learning_id = _uid("lrn")
    learn = {
        "learning_id": learning_id,
        "decision_id": decision["decision_id"],
        "action_id": action["action_id"],
        "outcome_id": outcome["outcome_id"],
        "company_id": decision["company_id"],
        "what_worked": (decision["recommended_action"] if worked
                          else ""),
        "what_failed": ("" if worked else
                          (action.get("result") or {}).get("reason",
                                                              "execução pendente")),
        "financial_delta_BRL": round(delta, 2),
        "confidence_delta": round(
            (1.0 if actual >= expected else -0.1) * 0.05, 4),
        "recommended_adjustment": (
            "manter parâmetros" if delta >= 0 else
            "reduzir confiança e/ou revisar threshold"),
        "created_at": _iso(),
    }
    await db.motor_ia_learnings.insert_one(dict(learn))
    # decision_quality
    await db.motor_ia_decision_quality.insert_one({
        "decision_id": decision["decision_id"],
        "expected_brl": expected,
        "actual_brl": actual,
        "accuracy_pct": round(accuracy, 2),
        "confidence": decision.get("confidence", 0.0),
        "learned": True,
        "created_at": _iso(),
    })
    return learn


# ---------- Orchestrator ---------- #
async def run_cycle(event: Dict[str, Any]) -> Dict[str, Any]:
    """Executa um ciclo COMPLETO E PERSISTIDO para um evento."""
    started = _iso()
    if "event_id" not in event:
        event["event_id"] = _uid("evt")
        event["created_at"] = started
        event["company_id"] = event.get("company_id") or "co-demo"
        await db.motor_ia_events.insert_one(dict(event))

    cycle_id = _uid("cyc")
    cycle = {
        "cycle_id": cycle_id,
        "company_id": event["company_id"],
        "event_id": event["event_id"],
        "started_at": started,
        "status": "running",
    }
    await db.motor_ia_autonomous_cycles.insert_one(dict(cycle))

    analysis = await _analyze_event(event)
    decision = _decide(event, analysis)
    # Knowledge Graph hookup (V5.0 sprint final)
    kg = await _kg_lookup(decision["company_id"], decision.get("cause", ""))
    decision["confidence"] = min(
        round(decision.get("confidence", 0) + kg["confidence_boost"], 4),
        0.99)
    decision["evidence"] = (decision.get("evidence") or []) + kg["kg_evidence"]
    decision["kg_matches"] = kg["matches"]
    await db.motor_ia_decisions.insert_one(dict(decision))
    action = await _execute_action(decision)
    outcome = await _observe_outcome(decision, action)
    learning = await _learn(decision, action, outcome)

    await db.motor_ia_autonomous_cycles.update_one(
        {"cycle_id": cycle_id},
        {"$set": {
            "analysis_id": analysis["analysis_id"],
            "decision_id": decision["decision_id"],
            "action_id": action["action_id"],
            "outcome_id": outcome["outcome_id"],
            "learning_id": learning["learning_id"],
            "finished_at": _iso(),
            "status": "complete",
            "expected_BRL": decision.get("expected_BRL", 0),
            "actual_BRL": outcome.get("actual_BRL", 0),
            "action_kind": decision.get("action_kind"),
            "human_intervention": False,
        }})

    return {
        "cycle_id": cycle_id, "status": "complete",
        "event": {"id": event["event_id"], "type": event.get("event_type")},
        "analysis": analysis, "decision": decision, "action": action,
        "outcome": outcome, "learning": learning,
    }


# ---------- Bulk drivers ---------- #
async def drive_from_overdue(company_id: str,
                              limit: int = 5) -> List[Dict[str, Any]]:
    """Detecta overdue → executa ciclos autonomamente."""
    pipe = [
        {"$match": {"company_id": company_id, "status": "overdue"}},
        {"$group": {"_id": "$subscriber_document",
                     "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": limit},
    ]
    docs = await db.subscriber_invoices.aggregate(pipe).to_list(limit)
    cycles = []
    for d in docs:
        sub = await db.subscribers.find_one(
            {"document": d["_id"], "company_id": company_id}, {"id": 1})
        if not sub:
            continue
        cycle = await run_cycle({
            "event_type": "OVERDUE_DETECTED",
            "company_id": company_id,
            "subscriber_id": sub["id"],
            "payload": {"overdue_count": d["n"]},
        })
        cycles.append(cycle)
    return cycles


async def drive_from_isabella_churn(company_id: str,
                                     limit: int = 5) -> List[Dict[str, Any]]:
    rows = await db.motor_ia_subscriber_scores.find(
        {"company_id": company_id, "churn_score": {"$gte": 0.7}},
        {"subscriber_id": 1, "churn_score": 1}
    ).sort("churn_score", -1).limit(limit).to_list(limit)
    cycles = []
    for r in rows:
        cycle = await run_cycle({
            "event_type": "ISABELLA_HIGH_CHURN",
            "company_id": company_id,
            "subscriber_id": r["subscriber_id"],
            "payload": {"churn_score": r["churn_score"]},
        })
        cycles.append(cycle)
    return cycles


async def drive_from_onu_degraded(company_id: str,
                                    limit: int = 5) -> List[Dict[str, Any]]:
    cur = db.subscribers.find(
        {"company_id": company_id, "status": "ATIVO",
         "smartolt_onu_status": {"$in": ["Offline", "LOS",
                                            "Power fail"]}},
        {"id": 1, "smartolt_onu_status": 1}).limit(limit)
    cycles = []
    async for s in cur:
        cycle = await run_cycle({
            "event_type": "ONU_DEGRADED",
            "company_id": company_id,
            "subscriber_id": s["id"],
            "payload": {"onu_status": s["smartolt_onu_status"]},
        })
        cycles.append(cycle)
    return cycles


async def drive_from_isabella_retention(
        company_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """V6.2 FASE 4 — Isabella Retention driver."""
    rows = await db.motor_ia_subscriber_scores.find(
        {"company_id": company_id, "retention_score": {"$gte": 0.7}},
        {"subscriber_id": 1, "retention_score": 1}
    ).sort("retention_score", -1).limit(limit).to_list(limit)
    cycles = []
    for r in rows:
        cycle = await run_cycle({
            "event_type": "ISABELLA_RETENTION_OPPORTUNITY",
            "company_id": company_id,
            "subscriber_id": r["subscriber_id"],
            "payload": {"retention_score": r["retention_score"]},
        })
        cycles.append(cycle)
    return cycles


async def drive_from_isabella_referral(
        company_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """V6.2 FASE 4 — Isabella Referral driver."""
    rows = await db.motor_ia_subscriber_scores.find(
        {"company_id": company_id, "referral_score": {"$gte": 0.7}},
        {"subscriber_id": 1, "referral_score": 1}
    ).sort("referral_score", -1).limit(limit).to_list(limit)
    cycles = []
    for r in rows:
        cycle = await run_cycle({
            "event_type": "ISABELLA_REFERRAL_OPPORTUNITY",
            "company_id": company_id,
            "subscriber_id": r["subscriber_id"],
            "payload": {"referral_score": r["referral_score"]},
        })
        cycles.append(cycle)
    return cycles


async def drive_from_isabella_collection(
        company_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """V6.2 FASE 4 — Isabella Collection driver (cobrança proativa)."""
    rows = await db.motor_ia_subscriber_scores.find(
        {"company_id": company_id, "collection_score": {"$gte": 0.7}},
        {"subscriber_id": 1, "collection_score": 1}
    ).sort("collection_score", -1).limit(limit).to_list(limit)
    cycles = []
    for r in rows:
        cycle = await run_cycle({
            "event_type": "ISABELLA_COLLECTION_OPPORTUNITY",
            "company_id": company_id,
            "subscriber_id": r["subscriber_id"],
            "payload": {"collection_score": r["collection_score"]},
        })
        cycles.append(cycle)
    return cycles


# ---------- Autonomy score ---------- #
async def compute_autonomy_score(company_id: str,
                                   days: int = 1) -> Dict[str, Any]:
    """Autonomy score agregado + por domínio (Operacional/Comercial/
    Financeira/Técnica). Penaliza bloqueios reais (blocked_transport)."""
    cutoff = (_now() - timedelta(days=days)).isoformat()
    cycles = await db.motor_ia_autonomous_cycles.find(
        {"company_id": company_id,
         "started_at": {"$gte": cutoff}}).to_list(5000)

    # Mapa kind → domínio
    DOMAIN = {
        "operacao_tese_tier_c":  "financial",
        "retention_campaign":    "commercial",
        "upgrade_offer":         "commercial",
        "preventive_ticket":     "technical",
    }
    # status considerado sucesso real
    SUCCESS = {"executed", "dispatched"}
    # status considerado bloqueio por falta de credencial humana
    BLOCKED = {"blocked_transport", "blocked_data", "queued_no_credentials"}

    # Por domínio: success_real / total_no_dominio
    buckets: Dict[str, Dict[str, int]] = {
        "operational": {"s": 0, "t": 0, "b": 0},
        "commercial":  {"s": 0, "t": 0, "b": 0},
        "financial":   {"s": 0, "t": 0, "b": 0},
        "technical":   {"s": 0, "t": 0, "b": 0},
    }

    total = len(cycles)
    real_success = 0
    blocked_count = 0
    failed = 0
    human_int = 0

    # Para descobrir o status da ação preciso join action_id → motor_ia_actions
    action_ids = [c.get("action_id") for c in cycles if c.get("action_id")]
    action_map: Dict[str, str] = {}
    if action_ids:
        async for a in db.motor_ia_actions.find(
                {"action_id": {"$in": action_ids}},
                {"action_id": 1, "status": 1}):
            action_map[a["action_id"]] = a.get("status")

    for c in cycles:
        kind = c.get("action_kind") or ""
        dom = DOMAIN.get(kind, "operational")
        astatus = action_map.get(c.get("action_id"))
        is_complete = c.get("status") == "complete"
        is_success = astatus in SUCCESS and is_complete
        is_blocked = astatus in BLOCKED
        if c.get("human_intervention"):
            human_int += 1

        if kind == "noop":
            # noop não conta como ciclo "trabalhado"
            continue

        buckets[dom]["t"] += 1
        if is_success:
            buckets[dom]["s"] += 1
            real_success += 1
        elif is_blocked:
            buckets[dom]["b"] += 1
            blocked_count += 1
        elif not is_complete:
            failed += 1

    def _pct(s, t): return round((s / max(t, 1)) * 100, 1)
    domain_scores = {
        k: {
            "score":   _pct(v["s"], v["t"]),
            "success": v["s"],
            "blocked": v["b"],
            "total":   v["t"],
        }
        for k, v in buckets.items()
    }

    # Total = média ponderada por número de ciclos
    total_with_attempts = sum(v["t"] for v in buckets.values())
    score = round(real_success / max(total_with_attempts, 1) * 100, 1)

    # Regra V5.0 sprint final: SE houver ação crítica bloqueada por credencial,
    # cap em 89% (proíbe falsa OPERACAO_AUTONOMA)
    capped_reason = None
    if blocked_count > 0 and score >= 90:
        score = 89.0
        capped_reason = (f"{blocked_count} ação(ões) críticas bloqueadas "
                          f"por credencial humana (não pode reivindicar 100% "
                          f"autônomo)")

    if score <= 25:    cls = "ASSISTIDO"
    elif score <= 50:  cls = "SEMI_AUTONOMO"
    elif score <= 75:  cls = "INTELIGENTE"
    elif score <= 90:  cls = "AUTONOMO"
    else:              cls = "OPERACAO_AUTONOMA"

    payload = {
        "company_id": company_id, "date": _iso(),
        "window_days": days,
        "score": score,
        "classification": cls,
        "capped_reason": capped_reason,
        "successful_actions": real_success,
        "failed_actions": failed,
        "blocked_actions": blocked_count,
        "human_interventions": human_int,
        "total_cycles": total,
        "by_domain": domain_scores,
    }
    await db.motor_ia_autonomy_score.update_one(
        {"company_id": company_id, "date_key": _iso()[:10]},
        {"$set": {**payload, "date_key": _iso()[:10]}},
        upsert=True)
    return payload


# ---------- Daily briefing ---------- #
async def daily_briefing(company_id: str) -> Dict[str, Any]:
    today_start = _now().replace(hour=0, minute=0, second=0,
                                    microsecond=0).isoformat()
    yest_start = (_now() - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0).isoformat()

    async def _sum(col, match, field):
        pipe = [{"$match": match},
                 {"$group": {"_id": None, "t": {"$sum": f"${field}"}}}]
        r = await db[col].aggregate(pipe).to_list(1)
        return float(r[0]["t"]) if r else 0.0

    actual_today = await _sum("motor_ia_outcomes",
                                 {"company_id": company_id,
                                  "observed_at": {"$gte": today_start}},
                                 "actual_BRL")
    actual_yest = await _sum("motor_ia_outcomes",
                                {"company_id": company_id,
                                 "observed_at": {"$gte": yest_start,
                                                  "$lt": today_start}},
                                "actual_BRL")
    expected_today = await _sum("motor_ia_outcomes",
                                   {"company_id": company_id,
                                    "observed_at": {"$gte": today_start}},
                                   "expected_BRL")

    score = await compute_autonomy_score(company_id, days=1)

    # aprendizados de hoje
    learnings_today = await db.motor_ia_learnings.count_documents({
        "company_id": company_id, "created_at": {"$gte": today_start}})

    # ações para amanhã = expected pendente
    pending_expected = await db.motor_ia_actions.aggregate([
        {"$match": {"company_id": company_id,
                     "status": {"$in": ["queued",
                                          "queued_no_credentials"]}}},
        {"$lookup": {"from": "motor_ia_decisions",
                       "localField": "decision_id",
                       "foreignField": "decision_id",
                       "as": "d"}},
        {"$unwind": "$d"},
        {"$group": {"_id": None,
                     "t": {"$sum": "$d.expected_BRL"},
                     "n": {"$sum": 1}}},
    ]).to_list(1)
    pending_BRL = float(pending_expected[0]["t"]) if pending_expected else 0
    pending_n = int(pending_expected[0]["n"]) if pending_expected else 0

    diff_yest = round(actual_today - actual_yest, 2)
    better = diff_yest >= 0
    headline = (
        f"Autonomy {score['score']}% ({score['classification']}) · "
        f"Gerado hoje R$ {actual_today:,.2f} · "
        f"Ontem R$ {actual_yest:,.2f} · "
        f"{'MELHOR' if better else 'PIOR'} em "
        f"R$ {abs(diff_yest):,.2f}"
    )
    return {
        "generated_at": _iso(),
        "headline": headline,
        "questions": {
            "1_generated_today_BRL": round(actual_today, 2),
            "2_recovered_today_BRL": round(actual_today, 2),
            "3_protected_today_BRL": round(expected_today, 2),
            "4_lost_today_BRL": round(max(expected_today
                                              - actual_today, 0), 2),
            "5_learnings_today": learnings_today,
            "6_planned_for_tomorrow_BRL": round(pending_BRL, 2),
            "6_planned_for_tomorrow_actions": pending_n,
            "7_better_than_yesterday": better,
            "8_proof": {
                "today_BRL": round(actual_today, 2),
                "yesterday_BRL": round(actual_yest, 2),
                "diff_BRL": diff_yest,
            },
        },
        "autonomy_score": score,
    }
