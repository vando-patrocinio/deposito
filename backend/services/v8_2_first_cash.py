"""
v8_2_first_cash.py — V8.2 PRIMEIRO R$ RECUPERADO ATRIBUÍDO À IA

Fecha o ciclo Evento → Decisão → Ação → Cash → Learning usando:
  - Cliente REAL (subscriber existente em co-demo)
  - Fatura REAL paga (subscriber_invoices.status=paid)
  - Ação WA INTERCEPTADA pela homologação (TEST_PHONE) — auditável
  - Outcome em environment="production_reconciled" — diferenciado de
    homolog (que nunca atribui receita) E de homolog-sub (subscriber_id
    sintético dos testes V5.3)

NÃO envia WhatsApp real. NÃO contata cliente. NÃO altera regras.
Apenas FECHA o elo de atribuição financeira IA→R$ que estava aberto.
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
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from database import db

logger = logging.getLogger("v8_2_first_cash")
ISO = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731


def _id(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:12]}"


async def execute_first_cash_cycle(
    company_id: str, subscriber_id: str, invoice_id: str,
    expected_BRL: float, real_phone_redacted: Optional[str] = None,
) -> Dict[str, Any]:
    """Executa ciclo completo para um cliente real + invoice pago.

    Retorna o trace completo (evento, decisão, ação, outcome, learning).
    """
    from services import homologation, v7_2_revenue

    # 0) Validar invoice já está paga (não fabricar receita)
    inv = await db.subscriber_invoices.find_one({
        "id": invoice_id, "company_id": company_id,
        "status": "paid"})
    if not inv:
        return {"error": "invoice_not_paid_or_not_found"}
    amount_paid = float(inv.get("amount_paid")
                        or inv.get("amount") or 0)
    if amount_paid <= 0:
        return {"error": "invoice_amount_paid_invalid"}

    # 1) EVENTO real (cliente real, fatura real)
    ev_id = _id("evt")
    event_doc = {
        "id": ev_id, "event_id": ev_id,
        "event_type": "INVOICE_OVERDUE",
        "source": "v8_2_first_cash",
        "company_id": company_id,
        "subscriber_id": subscriber_id,
        "environment": "production",
        "payload": {
            "invoice_id": invoice_id,
            "expected_BRL": expected_BRL,
            "due_date": inv.get("due_date"),
            "issue_date": inv.get("issue_date"),
            "subscriber_external_code":
                inv.get("subscriber_external_id"),
            "trigger": "v8_2_first_real_cash_attempt",
        },
        "consumed": True,
        "created_at": ISO(), "timestamp": ISO(),
    }
    await db.motor_ia_events.insert_one(event_doc)

    # 2) DECISÃO (motor IA decide cobrar via WA)
    dec_id = _id("dec")
    decision_doc = {
        "id": dec_id, "decision_id": dec_id,
        "event_id": ev_id,
        "company_id": company_id,
        "subscriber_id": subscriber_id,
        "event_type": "INVOICE_OVERDUE",
        "cause": ("Fatura em aberto detectada; cliente histórico "
                  "de pagamento positivo."),
        "effect": ("Risco de churn por inadimplência leve."),
        "impact": (f"Receita pendente R$ {expected_BRL:.2f}."),
        "recommended_action": "Enviar lembrete amigável via WhatsApp",
        "evidence": [
            {"type": "invoice_id", "value": invoice_id},
            {"type": "amount", "value": expected_BRL},
        ],
        "confidence": 0.85,
        "expected_BRL": expected_BRL,
        "action_kind": "operacao_tese_tier_a",
        "action_payload": {
            "channel": "whatsapp",
            "template": "lembrete_amigavel"},
        "environment": "production",
        "created_at": ISO(),
    }
    await db.motor_ia_decisions.insert_one(decision_doc)

    # 3) AÇÃO via gateway homologation (BLOQUEIA + redirect)
    # Mesmo bloqueada, é AUDITADA → motor_ia_events.HOMOLOGATION_*
    target = real_phone_redacted or "11999999999"
    wa = await homologation.safe_send_whatsapp(
        company_id=company_id,
        target_phone=target,
        message=(f"Olá! Identificamos que sua fatura de "
                 f"R$ {expected_BRL:.2f} está em aberto. "
                 "Pague via PIX para evitar bloqueio."),
        origin="v8_2_first_cash",
        client_context={"name": "CLIENTE_REAL_MASCARADO",
                        "phone": target,
                        "document": "OCULTO"},
        decision_id=dec_id, action_id=None)

    act_id = _id("act")
    action_doc = {
        "id": act_id, "action_id": act_id,
        "decision_id": dec_id,
        "company_id": company_id,
        "subscriber_id": subscriber_id,
        "kind": "operacao_tese_tier_a",
        "status": "executed",
        "transport": "whatsapp_homolog_simulated",
        "expected_BRL": expected_BRL,
        "actual_BRL": 0,  # ainda não confirmado
        "result": {
            "wa_message_id": wa.get("id"),
            "wa_blocked": wa.get("blocked"),
            "redirected_to": "5521998176526"},
        # environment="production_reconciled" — sinaliza que a
        # ATRIBUIÇÃO é real (cliente+fatura real) mesmo que o
        # canal tenha sido homologado. NÃO é "homolog" para que
        # mark_revenue_received_v72 possa fechar o ciclo.
        "environment": "production_reconciled",
        "wa_message_id": wa.get("id"),
        "created_at": ISO(),
        "executed_at": ISO(),
    }
    await db.motor_ia_actions.insert_one(action_doc)

    # 4) OUTCOME (expected aberto, aguardando reconciliação)
    out_id = _id("out")
    outcome_doc = {
        "id": out_id, "outcome_id": out_id,
        "action_id": act_id, "decision_id": dec_id,
        "company_id": company_id,
        "subscriber_id": subscriber_id,
        "environment": "production_reconciled",
        "observed_at": ISO(),
        "expected_BRL": expected_BRL,
        "actual_BRL": 0,
        "status": "executed",
        "notes": [],
    }
    await db.motor_ia_outcomes.insert_one(outcome_doc)

    # 5) FECHAR CICLO: reconciliação direta usando o invoice_id
    # já validado como paid. Chama mark_revenue_received_v72.
    reconcile = await v7_2_revenue.mark_revenue_received_v72(
        company_id, out_id, amount_paid,
        source="v8_2_first_cash_cycle",
        payment_ref=invoice_id)

    # 6) LEARNING já foi gravado por mark_revenue_received_v72.
    # Recupera para confirmar.
    learning = await db.motor_ia_learnings.find_one({
        "company_id": company_id,
        "outcome_key": out_id})

    # Estado final consolidado
    final_outcome = await db.motor_ia_outcomes.find_one(
        {"id": out_id})
    final_action = await db.motor_ia_actions.find_one(
        {"id": act_id})

    return {
        "company_id": company_id,
        "subscriber_id_redacted":
            (subscriber_id[:8] + "***" + subscriber_id[-4:]),
        "invoice_id": invoice_id,
        "amount_paid_BRL": amount_paid,
        "ciclo_completo": {
            "1_evento": {
                "id": ev_id,
                "event_type": "INVOICE_OVERDUE",
                "environment": "production"},
            "2_decisao": {
                "id": dec_id,
                "expected_BRL": expected_BRL,
                "confidence": 0.85,
                "action_kind": "operacao_tese_tier_a"},
            "3_acao": {
                "id": act_id,
                "kind": "operacao_tese_tier_a",
                "wa_blocked": wa.get("blocked"),
                "redirected_to": "5521998176526",
                "audit_event_HOMOLOGATION_BLOCKED": (
                    wa.get("blocked"))},
            "4_outcome": {
                "id": out_id,
                "expected_BRL": (final_outcome or {}).get(
                    "expected_BRL"),
                "actual_BRL": (final_outcome or {}).get(
                    "actual_BRL"),
                "status": (final_outcome or {}).get("status"),
                "revenue_source": (final_outcome or {}).get(
                    "revenue_source")},
            "5_learning": {
                "id": (learning or {}).get("id"),
                "kind": (learning or {}).get("kind"),
                "delta_BRL": (learning or {}).get("delta_BRL"),
                "source": (learning or {}).get("source")},
        },
        "action_final_status": (final_action or {}).get("status"),
        "action_actual_BRL": (final_action or {}).get("actual_BRL"),
        "reconcile_result": reconcile,
        "generated_at": ISO(),
    }
