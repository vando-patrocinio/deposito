"""
operacao_tese.py — OPERAÇÃO TESE VALIDADA (Presidente IA)
Provar que o Sistema recupera receita sozinho. Meta: R$.

Orquestra as 10 fases:
  Fase 1: pre_flight_check  → bloqueia se algo crítico falha
  Fase 2: select_eligible   → clientes inadimplentes elegíveis
  Fase 3: score_and_classify → ALTO/MEDIO/BAIXO
  Fase 4: activate_live     → escalate_dunning ON, resto OFF
  Fase 5: send_dunning_wa   → WhatsApp via Baileys + tracking
  Fase 6: monitor_panel     → métricas em tempo real
  Fase 7: learn_per_template → atualiza pesos por template usado
  Fase 8: daily_report      → relatório diário R$
  Fase 9: smartolt_gate     → BLOQUEIA cobrança se cliente offline/degradado
  Fase 10: success_criteria → SIM/NÃO + valor recuperado
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

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


TEMPLATES = {
    "amigavel_5_15d": (
        "Olá {nome}, tudo bem? 😊\n\nNotamos que sua fatura de "
        "*R$ {amount:.2f}* venceu há {dias} dias. Pode acontecer com "
        "qualquer um — me avisa se já pagou ou se precisa de ajuda "
        "para regularizar? 🙌"),
    "firme_16_30d": (
        "Oi {nome}, é da {empresa}.\n\nSua fatura de *R$ {amount:.2f}* "
        "está atrasada há {dias} dias. Para evitar bloqueio do serviço, "
        "regularize hoje. Posso te enviar o boleto atualizado agora?"),
}


# ─────────────────────── FASE 1 — PRE-FLIGHT ───────────────────────
async def pre_flight_check(company_id: str) -> Dict[str, Any]:
    """Valida 10 condições antes de iniciar piloto."""
    checks: List[Dict[str, Any]] = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": ok, "detail": detail})

    # 1. Baileys conectado (procura sessão ativa)
    try:
        sess = await db.wa_baileys_sessions.find_one(
            {"company_id": company_id, "status": "open"})
        add("baileys_session_open", bool(sess),
              f"session_id={sess.get('id') if sess else 'none'}")
    except Exception as e:
        add("baileys_session_open", False, str(e))
    # 2. WhatsApp gestor configurado (env)
    add("gestor_phone_env",
          bool(os.environ.get("PRESIDENTE_IA_GESTOR_PHONE")),
          os.environ.get("PRESIDENTE_IA_GESTOR_PHONE", "missing"))
    # 3. WhatsApp dispatcher importável
    try:
        from services.wa_dispatcher import send_text  # noqa
        add("wa_dispatcher_importable", True)
    except Exception as e:
        add("wa_dispatcher_importable", False, str(e))
    # 4. Billing operacional (já existe invoice nessa company?)
    n_inv = await db.subscriber_invoices.count_documents(
        {"company_id": company_id})
    add("billing_has_invoices", n_inv > 0, f"invoices={n_inv}")
    # 5. Action Engine handlers presentes
    try:
        from services.action_engine import HANDLERS
        add("action_engine_handlers",
              "escalate_dunning" in HANDLERS,
              f"handlers={list(HANDLERS.keys())}")
    except Exception as e:
        add("action_engine_handlers", False, str(e))
    # 6. Scheduler ativo (insight recente?)
    last = await db.motor_ia_insights.find_one(
        {}, sort=[("created_at", -1)])
    fresh = (last and last.get("created_at", "") >=
              _iso(_now() - timedelta(hours=2)))
    add("scheduler_fresh_insights", fresh,
          f"last={last.get('created_at') if last else 'none'}")
    # 7. Decision Engine RULES presentes
    try:
        from services.decision_engine import RULES
        add("decision_engine_rules",
              len(RULES) >= 10,
              f"rules_count={len(RULES)}")
    except Exception as e:
        add("decision_engine_rules", False, str(e))
    # 8. company_id válido
    n_subs = await db.subscribers.count_documents(
        {"company_id": company_id})
    add("company_id_valid", n_subs > 0,
          f"subscribers={n_subs}")
    # 9. Logs (audit chain íntegra)
    try:
        from services.lgpd_chain import verify_chain
        chk = await verify_chain(limit=100)
        add("audit_chain_integrity",
              chk.get("broken_count", 0) == 0,
              f"broken={chk.get('broken_count')}")
    except Exception as e:
        add("audit_chain_integrity", False, str(e))
    # 10. Cliente piloto NÃO já tem pilot ativo
    existing = await db.live_pilot_runs.find_one(
        {"company_id": company_id, "status": "running"})
    add("no_active_pilot", existing is None,
          f"existing={existing.get('id') if existing else 'none'}")

    blocking = [c for c in checks if not c["ok"]]
    return {
        "checks": checks,
        "blocking_count": len(blocking),
        "blockers": [c["check"] for c in blocking],
        "ok_to_start": len(blocking) == 0,
        "checked_at": _iso(_now()),
    }


# ─────────────────────── FASE 9 — SmartOLT Gate ───────────────────────
async def smartolt_gate(subscriber_id: str) -> Dict[str, Any]:
    """Verifica se cliente pode receber cobrança.
    Bloqueia se: ONU offline, sinal degradado, ou incidente coletivo ativo."""
    reasons: List[str] = []
    # ONU offline
    onu = await db.onus.find_one({"subscriber_id": subscriber_id})
    if onu:
        if onu.get("status") in ("offline", "down"):
            reasons.append("ONU offline")
        rx = onu.get("rx_dbm")
        if rx is not None and float(rx) < -27:
            reasons.append(f"sinal degradado (rx={rx}dBm)")
        # incidente coletivo no mesmo CTO?
        cto_id = onu.get("cto_id")
        if cto_id:
            inc = await db.incidents.find_one({
                "cto_id": cto_id, "status": "open"})
            if inc:
                reasons.append(f"incidente coletivo CTO {cto_id}")
    return {
        "subscriber_id": subscriber_id,
        "blocked": len(reasons) > 0,
        "reasons": reasons,
    }


async def _create_alvaro_task(company_id: str, subscriber_id: str,
                                  reasons: List[str]) -> None:
    """Encaminha pra Álvaro IA quando cobrança é bloqueada."""
    try:
        await db.alvaro_tasks.insert_one({
            "id": f"alv-{uuid.uuid4().hex[:12]}",
            "company_id": company_id,
            "subscriber_id": subscriber_id,
            "kind": "tech_check_before_dunning",
            "reasons": reasons,
            "created_at": _iso(_now()),
            "created_by": "operacao_tese",
            "status": "pending",
        })
    except Exception:
        pass


# ─────────────────────── FASE 2 — Seleção ───────────────────────
async def select_eligible_clients(company_id: str,
                                       limit: int = 100) -> Dict[str, Any]:
    """Inadimplentes 5-30d, com telefone válido, sem ticket de cobrança."""
    today = _now().strftime("%Y-%m-%d")
    cut_5d = (_now() - timedelta(days=30)).strftime("%Y-%m-%d")
    cut_30d = (_now() - timedelta(days=5)).strftime("%Y-%m-%d")

    candidates: List[Dict[str, Any]] = []
    async for inv in db.subscriber_invoices.find({
        "company_id": company_id,
        "status": {"$in": ["open", "overdue"]},
        "due_date": {"$gte": cut_5d, "$lte": cut_30d},
    }).sort("due_date", -1).limit(limit * 5):
        sub_id = inv.get("subscriber_id")
        if not sub_id:
            continue
        # já tem ticket de cobrança aberto?
        has_ticket = await db.tickets.count_documents({
            "company_id": company_id,
            "subscriber_id": sub_id,
            "type": "cobranca",
            "status": {"$nin": ["closed", "completed", "finalizado"]}})
        if has_ticket:
            continue
        sub = await db.subscribers.find_one(
            {"id": sub_id, "company_id": company_id}, {"_id": 0})
        if not sub:
            continue
        phone = sub.get("phone") or inv.get("subscriber_phone")
        if not phone or len(str(phone)) < 10:
            continue
        # status legal
        if sub.get("blocked_judicial") or sub.get("negativado"):
            continue
        # dias atraso
        try:
            dd = datetime.strptime(inv["due_date"], "%Y-%m-%d")
            dias = (datetime.strptime(today, "%Y-%m-%d") - dd).days
        except Exception:
            dias = 0
        candidates.append({
            "subscriber_id": sub_id,
            "name": sub.get("name") or sub.get("nickname"),
            "phone": phone,
            "invoice_id": inv.get("id"),
            "amount": float(inv.get("amount") or 0),
            "days_overdue": dias,
            "due_date": inv.get("due_date"),
        })
        if len(candidates) >= limit:
            break
    return {"count": len(candidates), "candidates": candidates}


# ─────────────────────── FASE 3 — Score ───────────────────────
async def score_and_classify(candidates: List[Dict[str, Any]]
                                  ) -> List[Dict[str, Any]]:
    """Score 0-100 baseado em dias_atraso + valor + sinal técnico OK."""
    out = []
    for c in candidates:
        score = 0
        # dias entre 5-15 = prioridade alta (recupera mais barato)
        d = c.get("days_overdue") or 0
        if 5 <= d <= 15:
            score += 50
        elif 16 <= d <= 30:
            score += 30
        # valor alto pesa
        amt = c.get("amount") or 0
        if amt > 200:
            score += 30
        elif amt > 100:
            score += 20
        else:
            score += 10
        # smartolt gate aplica penalty
        gate = await smartolt_gate(c["subscriber_id"])
        if gate["blocked"]:
            score = -1  # filtra fora
            c["smartolt_blocked"] = True
            c["smartolt_reasons"] = gate["reasons"]
        # tier
        if score < 0:
            tier = "EXCLUIDO"
        elif score >= 70:
            tier = "ALTO"
        elif score >= 40:
            tier = "MEDIO"
        else:
            tier = "BAIXO"
        c["recovery_score"] = score
        c["tier"] = tier
        out.append(c)
    out.sort(key=lambda x: x.get("recovery_score") or 0, reverse=True)
    return out


# ─────────────────────── FASE 4 + 5 — Activate + Send ───────────────────────
async def start_operation(company_id: str, dry_run: bool = True,
                              max_messages: int = 20,
                              started_by: Optional[str] = None
                              ) -> Dict[str, Any]:
    """Roda Fases 1-5: checklist → seleção → score → LIVE → envio.

    Se dry_run=True (default), NÃO envia WhatsApp real — apenas
    registra `messages_planned`. Use dry_run=False só após validação.
    """
    pre = await pre_flight_check(company_id)
    if not pre["ok_to_start"]:
        return {"error": "pre_flight_failed", "pre_flight": pre}

    sel = await select_eligible_clients(company_id, limit=max_messages * 3)
    classified = await score_and_classify(sel["candidates"])
    eligible = [c for c in classified if c.get("recovery_score", -1) >= 0]
    blocked_by_smartolt = [c for c in classified
                              if c.get("smartolt_blocked")]
    # criar tarefas Álvaro para os bloqueados
    for c in blocked_by_smartolt:
        await _create_alvaro_task(company_id, c["subscriber_id"],
                                       c.get("smartolt_reasons", []))

    targets = eligible[:max_messages]
    op_id = f"optese-{uuid.uuid4().hex[:12]}"

    # FASE 4: ativa LIVE só para escalate_dunning (apenas se !dry_run)
    if not dry_run:
        from services.company_settings import set_live
        await set_live(company_id, ["escalate_dunning"],
                          updated_by=started_by or "operacao_tese")

    # FASE 5: envia / planeja
    sent = []
    for c in targets:
        days = c.get("days_overdue", 0)
        tpl_key = "amigavel_5_15d" if days <= 15 else "firme_16_30d"
        body = TEMPLATES[tpl_key].format(
            nome=c.get("name") or "cliente",
            amount=c.get("amount", 0),
            dias=days,
            empresa="SmartProv")
        msg_record = {
            "id": f"opmsg-{uuid.uuid4().hex[:12]}",
            "op_id": op_id,
            "company_id": company_id,
            "subscriber_id": c["subscriber_id"],
            "phone": c["phone"],
            "template": tpl_key,
            "body_preview": body[:200],
            "amount": c["amount"],
            "days_overdue": days,
            "tier": c["tier"],
            "dry_run": dry_run,
            "status": "planned",
            "created_at": _iso(_now()),
        }
        if not dry_run:
            try:
                from services.wa_dispatcher import send_text
                r = await send_text(
                    company_id=company_id, to=c["phone"], text=body,
                    channel="baileys")  # P0 CEO 17/02/2026
                msg_record["status"] = ("sent"
                                         if r and r.get("ok") else "failed")
                msg_record["wa_response"] = r
                msg_record["sent_at"] = _iso(_now())
            except Exception as e:
                msg_record["status"] = "failed"
                msg_record["error"] = str(e)
        try:
            await db.operacao_tese_messages.insert_one(dict(msg_record))
        except Exception:
            pass
        sent.append(msg_record)

    # registra a operação
    op_doc = {
        "id": op_id,
        "company_id": company_id,
        "started_at": _iso(_now()),
        "started_by": started_by,
        "dry_run": dry_run,
        "messages_count": len(sent),
        "eligible_count": len(eligible),
        "blocked_by_smartolt_count": len(blocked_by_smartolt),
        "status": "running",
    }
    await db.operacao_tese_runs.insert_one(dict(op_doc))
    op_doc.pop("_id", None)

    return {
        "operation_id": op_id,
        "pre_flight": pre,
        "eligible_total": len(classified),
        "eligible_after_smartolt": len(eligible),
        "blocked_by_smartolt": len(blocked_by_smartolt),
        "messages_sent_or_planned": len(sent),
        "dry_run": dry_run,
        "sample_targets": targets[:5],
        "sample_messages": sent[:3],
        "summary_by_tier": {
            t: sum(1 for c in targets if c["tier"] == t)
            for t in ("ALTO", "MEDIO", "BAIXO")
        },
    }


# ─────────────────────── FASES 6/7/8/10 — Monitor + Report ───────────────────
async def monitor_panel(op_id: str) -> Dict[str, Any]:
    """Métricas em tempo real da operação."""
    op = await db.operacao_tese_runs.find_one({"id": op_id})
    if not op:
        return {"error": "operation_not_found"}
    op.pop("_id", None)
    started_at = op["started_at"]
    company_id = op["company_id"]

    n_messages = await db.operacao_tese_messages.count_documents(
        {"op_id": op_id})
    n_sent = await db.operacao_tese_messages.count_documents(
        {"op_id": op_id, "status": "sent"})
    n_failed = await db.operacao_tese_messages.count_documents(
        {"op_id": op_id, "status": "failed"})

    # Pagamentos REAIS após started_at, das invoices dos targets
    msgs = []
    async for m in db.operacao_tese_messages.find({"op_id": op_id}):
        msgs.append(m)

    paid_count = 0
    paid_total = 0.0
    paid_subscribers = set()
    if msgs:
        sub_ids = [m["subscriber_id"] for m in msgs]
        async for inv in db.subscriber_invoices.find({
            "company_id": company_id,
            "subscriber_id": {"$in": sub_ids},
            "status": "paid",
            "paid_at": {"$gte": started_at},
        }):
            paid_count += 1
            paid_total += float(inv.get("amount_paid")
                                   or inv.get("amount") or 0)
            paid_subscribers.add(inv.get("subscriber_id"))

    # tempo médio de recuperação
    times = []
    for sub_id in paid_subscribers:
        msg = next((m for m in msgs
                     if m["subscriber_id"] == sub_id), None)
        if msg and msg.get("created_at"):
            try:
                inv = await db.subscriber_invoices.find_one(
                    {"subscriber_id": sub_id, "status": "paid"},
                    sort=[("paid_at", 1)])
                if inv and inv.get("paid_at"):
                    t0 = datetime.fromisoformat(
                        msg["created_at"].replace("Z", "+00:00"))
                    t1 = datetime.fromisoformat(
                        inv["paid_at"].replace("Z", "+00:00"))
                    times.append((t1 - t0).total_seconds() / 3600)
            except Exception:
                pass
    avg_recovery_h = (sum(times) / len(times)) if times else None

    conversion = (100.0 * paid_count / max(n_messages, 1)) \
        if n_messages else 0.0
    # ROI estimado: receita recuperada / custo (assumindo R$0.10 por msg)
    cost = n_messages * 0.10
    roi = ((paid_total - cost) / cost) if cost > 0 else None

    return {
        "op_id": op_id,
        "company_id": company_id,
        "started_at": started_at,
        "dry_run": op.get("dry_run"),
        "messages_planned": n_messages,
        "messages_sent": n_sent,
        "messages_failed": n_failed,
        "payments_received": paid_count,
        "recovered_BRL": round(paid_total, 2),
        "avg_recovery_hours": (round(avg_recovery_h, 1)
                                  if avg_recovery_h else None),
        "conversion_rate_pct": round(conversion, 1),
        "estimated_cost_BRL": round(cost, 2),
        "roi_x": (round(roi, 2) if roi is not None else None),
        "ticker": (f"R$ {paid_total:.2f} recuperados "
                    f"de {paid_count} pagamentos em "
                    f"{n_sent}/{n_messages} mensagens enviadas"),
    }


async def learn_from_payments(op_id: str) -> Dict[str, Any]:
    """FASE 7 — taxa de recuperação POR TEMPLATE."""
    msgs: List[Dict[str, Any]] = []
    async for m in db.operacao_tese_messages.find({"op_id": op_id}):
        m.pop("_id", None)
        msgs.append(m)
    op = await db.operacao_tese_runs.find_one({"id": op_id}) or {}
    company_id = op.get("company_id")
    if not company_id:
        return {"error": "op_not_found"}

    by_tpl: Dict[str, Dict[str, Any]] = {}
    for m in msgs:
        tpl = m.get("template")
        sub_id = m.get("subscriber_id")
        if not tpl:
            continue
        by_tpl.setdefault(tpl, {"sent": 0, "paid": 0,
                                  "total_BRL": 0.0})
        by_tpl[tpl]["sent"] += 1
        inv = await db.subscriber_invoices.find_one({
            "company_id": company_id,
            "subscriber_id": sub_id,
            "status": "paid",
            "paid_at": {"$gte": op["started_at"]}})
        if inv:
            by_tpl[tpl]["paid"] += 1
            by_tpl[tpl]["total_BRL"] += float(
                inv.get("amount_paid") or inv.get("amount") or 0)
    # taxas
    for tpl, v in by_tpl.items():
        v["recovery_rate_pct"] = round(
            100.0 * v["paid"] / max(v["sent"], 1), 1)

    # grava learning
    learning = {
        "id": f"lrn-tese-{uuid.uuid4().hex[:12]}",
        "kind": "operacao_tese_templates",
        "op_id": op_id,
        "company_id": company_id,
        "by_template": by_tpl,
        "generated_at": _iso(_now()),
    }
    try:
        await db.motor_ia_learnings.insert_one(dict(learning))
    except Exception:
        pass
    learning.pop("_id", None)
    return learning


async def daily_report(op_id: str) -> Dict[str, Any]:
    """FASE 8 — relatório agregado focado em R$."""
    panel = await monitor_panel(op_id)
    learning = await learn_from_payments(op_id)
    return {
        "fase": "FASE 8 — Relatório Diário",
        "panel": panel,
        "learning": learning,
        "generated_at": _iso(_now()),
    }


async def success_criteria(op_id: str) -> Dict[str, Any]:
    """FASE 10 — veredito final."""
    panel = await monitor_panel(op_id)
    op = await db.operacao_tese_runs.find_one({"id": op_id}) or {}
    started_at = op.get("started_at")
    elapsed_h = None
    if started_at:
        try:
            t0 = datetime.fromisoformat(
                started_at.replace("Z", "+00:00"))
            elapsed_h = (_now() - t0).total_seconds() / 3600
        except Exception:
            pass
    recovered = panel.get("recovered_BRL") or 0
    recovered_alone = recovered > 0 and not op.get("dry_run")
    return {
        "operation_id": op_id,
        "elapsed_hours": (round(elapsed_h, 1) if elapsed_h else None),
        "dry_run_mode": op.get("dry_run", False),
        "metrics": {
            "messages_sent": panel.get("messages_sent"),
            "payments": panel.get("payments_received"),
            "recovered_BRL": recovered,
            "ROI": panel.get("roi_x"),
            "conversion_pct": panel.get("conversion_rate_pct"),
            "learnings_generated": 1,
        },
        "presidente_ia_recovered_alone": (
            "SIM" if recovered_alone else "NÃO"),
        "amount_recovered_BRL": (recovered if recovered_alone
                                    else 0),
        "tese": (
            "VALIDADA — Presidente IA recuperou receita autonomamente."
            if recovered_alone else
            ("AGUARDANDO — operação rodando em DRY-RUN, ative "
              "LIVE para validar." if op.get("dry_run") else
              "PENDENTE — mensagens enviadas, pagamentos ainda não "
              "creditados.")),
    }


async def stop_operation(op_id: str,
                            stopped_by: Optional[str] = None
                            ) -> Dict[str, Any]:
    """Encerra a operação + desativa LIVE."""
    op = await db.operacao_tese_runs.find_one({"id": op_id})
    if not op:
        return {"error": "not_found"}
    from services.company_settings import set_live
    await set_live(op["company_id"], [], updated_by=stopped_by)
    await db.operacao_tese_runs.update_one(
        {"id": op_id},
        {"$set": {"status": "stopped",
                  "stopped_at": _iso(_now()),
                  "stopped_by": stopped_by}})
    return await success_criteria(op_id)
