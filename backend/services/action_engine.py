"""
action_engine.py — Sprint 8 / iter227
Motor de Ação do Presidente IA. Executa decisões pendentes.

Por segurança, executa em DRY-RUN por default. Para enviar WhatsApp
real / criar tickets / etc, defina env `PRESIDENTE_IA_LIVE=1`.

Toda ação grava `motor_ia_actions` (registro) + `motor_ia_outcomes`
(resultado medido) para feedback loop e aprendizado futuro.
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
from datetime import datetime, timezone
from typing import Any, Dict

from database import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _live() -> bool:
    return os.environ.get("PRESIDENTE_IA_LIVE", "0") == "1"


async def _live_for(company_id, action_type: str) -> bool:
    """Sprint 15 — feature flag por empresa.
    Se global PRESIDENTE_IA_LIVE=1 → tudo LIVE.
    Senão, consulta company_settings.live_actions.
    """
    if _live():
        return True
    try:
        from services.company_settings import is_live
        return await is_live(company_id, action_type)
    except Exception:
        return False


# ─────────────────── Action handlers ───────────────────
async def _exec_open_incident(dec: Dict[str, Any]) -> Dict[str, Any]:
    """Abre incidente coletivo de rede."""
    p = dec.get("action_payload") or {}
    incident = {
        "id": f"inc-{uuid.uuid4().hex[:12]}",
        "company_id": dec.get("company_id"),
        "cto_id": p.get("cto_id"),
        "affected_count": p.get("affected_count"),
        "client_ids": p.get("client_ids") or [],
        "status": "open",
        "opened_by": "presidente_ia",
        "opened_at": _now(),
        "linked_decision_id": dec["id"],
    }
    try:
        await db.incidents.insert_one(incident)
    except Exception:
        pass
    return {"ok": True, "incident_id": incident["id"]}


async def _exec_create_retention_opportunity(dec: Dict[str, Any]
                                                  ) -> Dict[str, Any]:
    """Cria oportunidade de retenção para Isabella IA."""
    p = dec.get("action_payload") or {}
    opp = {
        "id": f"opp-{uuid.uuid4().hex[:12]}",
        "company_id": dec.get("company_id"),
        "subscriber_id": p.get("subscriber_id"),
        "kind": "retention",
        "channel": p.get("channel") or "whatsapp",
        "agent": p.get("agent") or "isabella",
        "status": "pending",
        "created_by": "presidente_ia",
        "created_at": _now(),
        "linked_decision_id": dec["id"],
    }
    try:
        await db.loyalty_opportunities.insert_one(opp)
    except Exception:
        pass
    return {"ok": True, "opportunity_id": opp["id"]}


async def _exec_notify_manager(dec: Dict[str, Any]) -> Dict[str, Any]:
    """Notifica gestor (DRY_RUN grava sem enviar; LIVE envia WA)."""
    p = dec.get("action_payload") or {}
    live = await _live_for(dec.get("company_id"), "notify_manager")
    notif = {
        "id": f"nti-{uuid.uuid4().hex[:12]}",
        "company_id": dec.get("company_id"),
        "title": dec.get("title"),
        "message": p.get("message") or dec.get("reasoning"),
        "level": "warning",
        "created_by": "presidente_ia",
        "created_at": _now(),
        "linked_decision_id": dec["id"],
        "dry_run": not live,
    }
    sent = False
    try:
        await db.presidente_ia_notifications.insert_one(notif)
        if live and dec.get("company_id"):
            try:
                gestor_phone = os.environ.get("PRESIDENTE_IA_GESTOR_PHONE")
                if gestor_phone:
                    from services.wa_dispatcher import send_text
                    await send_text(
                        company_id=dec["company_id"],
                        to=gestor_phone,
                        text=(f"🤖 *Presidente IA*\n\n"
                               f"*{notif['title']}*\n\n"
                               f"{notif['message']}"),
                    )
                    sent = True
            except Exception:
                pass
    except Exception:
        pass
    return {"ok": True, "notification_id": notif["id"],
            "dry_run": not live, "wa_sent": sent}


async def _exec_escalate_dunning(dec: Dict[str, Any]) -> Dict[str, Any]:
    """Aciona régua de cobrança (DRY_RUN grava sem enviar WA)."""
    p = dec.get("action_payload") or {}
    live = await _live_for(dec.get("company_id"), "escalate_dunning")
    record = {
        "id": f"dun-{uuid.uuid4().hex[:12]}",
        "company_id": dec.get("company_id"),
        "subscriber_id": p.get("subscriber_id"),
        "stage": "presidente_ia_auto_escalation",
        "created_by": "presidente_ia",
        "created_at": _now(),
        "linked_decision_id": dec["id"],
        "dry_run": not live,
    }
    try:
        await db.dunning_escalations.insert_one(record)
    except Exception:
        pass
    return {"ok": True, "dunning_id": record["id"],
            "dry_run": not live}


async def _exec_open_technical_ticket(dec: Dict[str, Any]
                                          ) -> Dict[str, Any]:
    """Abre ticket técnico no pipeline de atendimento."""
    p = dec.get("action_payload") or {}
    ticket = {
        "id": f"tkt-{uuid.uuid4().hex[:12]}",
        "company_id": dec.get("company_id"),
        "subscriber_id": p.get("subscriber_id"),
        "category": "technical",
        "issue": p.get("issue") or "auto_detected",
        "data": p,
        "status": "open",
        "opened_by": "presidente_ia",
        "opened_at": _now(),
        "linked_decision_id": dec["id"],
    }
    try:
        await db.tickets.insert_one(ticket)
    except Exception:
        pass
    return {"ok": True, "ticket_id": ticket["id"]}


async def _exec_create_sales_lead(dec: Dict[str, Any]) -> Dict[str, Any]:
    """Cria lead no funil comercial."""
    p = dec.get("action_payload") or {}
    lead = {
        "id": f"lead-{uuid.uuid4().hex[:12]}",
        "company_id": dec.get("company_id"),
        "source": "presidente_ia",
        "data": p,
        "status": "new",
        "created_at": _now(),
        "linked_decision_id": dec["id"],
    }
    try:
        await db.sales_leads.insert_one(lead)
    except Exception:
        pass
    return {"ok": True, "lead_id": lead["id"]}


HANDLERS = {
    "open_incident": _exec_open_incident,
    "create_retention_opportunity": _exec_create_retention_opportunity,
    "notify_manager": _exec_notify_manager,
    "escalate_dunning": _exec_escalate_dunning,
    "open_technical_ticket": _exec_open_technical_ticket,
    "create_sales_lead": _exec_create_sales_lead,
}


# ─────────────────── Dispatcher ───────────────────
async def execute_pending(limit: int = 100) -> Dict[str, Any]:
    """Pega decisões não executadas, despacha, grava action+outcome."""
    cur = db.motor_ia_decisions.find(
        {"executed": False}).sort("created_at", 1).limit(limit)
    decisions = []
    async for d in cur:
        decisions.append(d)

    executed = 0
    skipped = 0
    failures = 0

    for dec in decisions:
        action_type = dec.get("action_type")
        handler = HANDLERS.get(action_type)
        if not handler:
            skipped += 1
            continue
        live_for_this = await _live_for(dec.get("company_id"),
                                              action_type)
        action_doc = {
            "id": f"act-{uuid.uuid4().hex[:14]}",
            "created_at": _now(),
            "company_id": dec.get("company_id"),
            "decision_id": dec["id"],
            "correlation_id": dec.get("correlation_id"),
            "action_type": action_type,
            "payload": dec.get("action_payload") or {},
            "dry_run": not live_for_this,
            "status": "running",
        }
        try:
            await db.motor_ia_actions.insert_one(action_doc)
        except Exception:
            pass

        try:
            result = await handler(dec)
            outcome = {"ok": bool(result.get("ok")),
                          "result": result, "error": None}
            executed += 1
        except Exception as e:
            outcome = {"ok": False, "result": None,
                          "error": str(e)[:200]}
            failures += 1

        # outcome + atualiza action
        try:
            await db.motor_ia_actions.update_one(
                {"id": action_doc["id"]},
                {"$set": {"status": "done" if outcome["ok"]
                            else "failed",
                            "completed_at": _now(),
                            "outcome": outcome}})
            await db.motor_ia_outcomes.insert_one({
                "id": f"out-{uuid.uuid4().hex[:14]}",
                "created_at": _now(),
                "action_id": action_doc["id"],
                "decision_id": dec["id"],
                "company_id": dec.get("company_id"),
                "correlation_id": dec.get("correlation_id"),
                "ok": outcome["ok"],
                "result": outcome["result"],
                "error": outcome["error"],
            })
            # Fase 1 Constituição V3.0 — RevenueOps IA: atribui R$ se houver
            if outcome["ok"] and isinstance(outcome["result"], dict):
                result_obj = outcome["result"]
                amt = (result_obj.get("recovered_BRL")
                       or result_obj.get("amount_paid")
                       or result_obj.get("revenue_BRL")
                       or result_obj.get("cost_saved_BRL")
                       or 0)
                if amt and float(amt) > 0 and dec.get("company_id"):
                    try:
                        from services.revenue_attribution import attribute
                        action_type = action_doc.get("action_type", "")
                        if "cost_saved_BRL" in result_obj:
                            kind = "cost_saved"
                        elif "upsell" in action_type or "cross" in action_type:
                            kind = "generated"
                        elif "retencao" in action_type or "churn" in action_type:
                            kind = "churn_prevented"
                        else:
                            kind = "recovered"
                        await attribute(
                            company_id=dec["company_id"],
                            kind=kind,
                            amount_BRL=float(amt),
                            action_id=action_doc["id"],
                            decision_id=dec["id"],
                            subscriber_id=result_obj.get("subscriber_id"),
                            channel=result_obj.get("channel"),
                            template=result_obj.get("template"),
                            metadata={"source": "action_engine_auto",
                                       "action_type": action_type},
                        )
                    except Exception:
                        pass
            await db.motor_ia_decisions.update_one(
                {"id": dec["id"]},
                {"$set": {"executed": True,
                            "executed_at": _now()}})
        except Exception:
            pass

    return {
        "decisions_processed": len(decisions),
        "executed": executed,
        "skipped": skipped,
        "failures": failures,
        "live_mode": _live(),
        "generated_at": _now(),
    }
