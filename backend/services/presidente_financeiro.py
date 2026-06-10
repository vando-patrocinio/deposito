"""OPERAÇÃO PRESIDENTE FINANCEIRO — sequência COLOSSO.

Atribui R$ confirmado ao `executive_ledger` para cada ação operacional
autônoma:

  • PREVENTIVA criada → R$ 80 (visita corretiva evitada por preventiva)
  • REAPROVEITAMENTO (estágio TESTE→REAPROVEITAMENTO) → R$ 120/ONU
  • INCIDENTE escalado pelo Álvaro → clientes_afetados × ticket × 30%
  • OS sem retorno em 30d → ticket_mensal × meses_protegidos
  • DO_NOT_DISPATCH (Truck Roll) → R$ 80 (visita evitada)

Sem novas coleções. Tudo em `executive_ledger` (mesma estrutura que já
recebe ações do Presidente IA).
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db


# Valores de referência (configuráveis via env quando preciso)
VAL_PREVENTIVA_BRL = 80.0       # custo médio visita corretiva evitada
VAL_REAPROVEITAMENTO_BRL = 120.0  # ONU média recuperada
VAL_TRUCK_ROLL_AVOIDED_BRL = 80.0
PCT_INCIDENT_REVENUE_PROTECTION = 0.30


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _record_ledger(*, company_id: str, action_id: str, kind: str,
                            expected_brl: float, actual_brl: float,
                            evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Idempotente por (company_id, action_id, kind). Persiste no
    executive_ledger reutilizando o schema existente.
    """
    doc = {
        "id": f"led-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "action_id": action_id,
        "kind": kind,
        "category": "PRESIDENTE_FINANCEIRO",
        "source": "lousa_coo",
        "expected_brl": round(expected_brl, 2),
        "valor_confirmado_brl": round(actual_brl, 2),
        "actual_BRL": round(actual_brl, 2),
        "evidence": evidence,
        "ts": _now_iso(),
        "created_at": _now_iso(),
    }
    try:
        # Idempotência: upsert por action_id + kind + company
        await db.executive_ledger.update_one(
            {"company_id": company_id, "action_id": action_id, "kind": kind},
            {"$setOnInsert": doc},
            upsert=True)
    except Exception:
        pass
    return doc


async def attribute_preventive(company_id: str, ticket_id: str,
                                  *, value_brl: float = VAL_PREVENTIVA_BRL,
                                  meta: Optional[Dict[str, Any]] = None
                                  ) -> Dict[str, Any]:
    """Cada preventiva criada → registra R$ visita corretiva evitada."""
    return await _record_ledger(
        company_id=company_id,
        action_id=f"preventive::{ticket_id}",
        kind="PREVENTIVE_AVOIDED_VISIT",
        expected_brl=value_brl, actual_brl=value_brl,
        evidence={"ticket_id": ticket_id, "rule": "1 preventiva = 1 visita evitada",
                  **(meta or {})})


async def attribute_reuse(company_id: str, equipment_id: str,
                            *, value_brl: float = VAL_REAPROVEITAMENTO_BRL,
                            meta: Optional[Dict[str, Any]] = None
                            ) -> Dict[str, Any]:
    """Cada equipamento que entra em REAPROVEITAMENTO → R$ patrimônio."""
    return await _record_ledger(
        company_id=company_id,
        action_id=f"reuse::{equipment_id}",
        kind="EQUIPMENT_REUSED",
        expected_brl=value_brl, actual_brl=value_brl,
        evidence={"equipment_id": equipment_id,
                  "rule": "1 reaproveitamento = 1 ONU resgatada",
                  **(meta or {})})


async def attribute_truck_roll_avoided(company_id: str, subscriber_id: str,
                                           *, value_brl: float = VAL_TRUCK_ROLL_AVOIDED_BRL
                                           ) -> Dict[str, Any]:
    """Truck Roll Guard = DO_NOT_DISPATCH → visita evitada."""
    return await _record_ledger(
        company_id=company_id,
        action_id=f"trg::{subscriber_id}::{datetime.now(timezone.utc).date().isoformat()}",
        kind="TRUCK_ROLL_AVOIDED",
        expected_brl=value_brl, actual_brl=value_brl,
        evidence={"subscriber_id": subscriber_id,
                  "rule": "DO_NOT_DISPATCH (Truck Roll Guard)"})


async def attribute_incident_protection(company_id: str, incident_id: str,
                                            *, clients_affected: int,
                                            ticket_avg_brl: float,
                                            ) -> Dict[str, Any]:
    """Incidente escalado → protege 30% da receita dos clientes afetados."""
    revenue = round(clients_affected * ticket_avg_brl * PCT_INCIDENT_REVENUE_PROTECTION, 2)
    return await _record_ledger(
        company_id=company_id,
        action_id=f"incident::{incident_id}",
        kind="INCIDENT_REVENUE_PROTECTED",
        expected_brl=revenue, actual_brl=revenue,
        evidence={"incident_id": incident_id,
                  "clients_affected": clients_affected,
                  "ticket_avg_brl": ticket_avg_brl,
                  "rule": f"{int(PCT_INCIDENT_REVENUE_PROTECTION*100)}% × clientes × ticket"})


async def attribute_os_no_return_30d(company_id: str, ticket_id: str,
                                          *, subscriber_id: str,
                                          ticket_brl: float,
                                          months_protected: int = 1
                                          ) -> Dict[str, Any]:
    """OS fechada que NÃO retornou em 30d → ticket × meses protegidos."""
    value = round(ticket_brl * months_protected, 2)
    return await _record_ledger(
        company_id=company_id,
        action_id=f"os_noret::{ticket_id}",
        kind="OS_NO_RETURN_30D",
        expected_brl=value, actual_brl=value,
        evidence={"ticket_id": ticket_id, "subscriber_id": subscriber_id,
                  "rule": "ticket × meses sem retorno"})


# ---------------------------------------------------------------------------
# CICLO COMPLETO — orquestrador do COLOSSO Financeiro
# ---------------------------------------------------------------------------
async def run_attribution_cycle(company_id: str,
                                  window_days: int = 30) -> Dict[str, Any]:
    """Varre eventos recentes e atribui R$ ao executive_ledger.

    Idempotente — `_record_ledger` usa upsert por (action_id, kind).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    out = {"preventive": 0, "reuse": 0, "truck_roll": 0,
           "incident": 0, "os_no_return": 0,
           "total_brl_attributed": 0.0}

    # 1) PREVENTIVAS criadas no período
    async for r in db.smart_repairs.find(
            {"company_id": company_id, "origin": "preventive",
             "created_at": {"$gte": cutoff}},
            {"_id": 0, "id": 1, "subscriber_id": 1, "cto_id": 1, "reason": 1}):
        rec = await attribute_preventive(
            company_id, r["id"],
            meta={"subscriber_id": r.get("subscriber_id"),
                  "cto_id": r.get("cto_id"),
                  "reason": r.get("reason")})
        out["preventive"] += 1
        out["total_brl_attributed"] += rec["valor_confirmado_brl"]

    # 2) REAPROVEITAMENTOS
    async for e in db.client_equipment_history.find(
            {"company_id": company_id, "kind": "current_state",
             "current_stage": "REAPROVEITAMENTO"},
            {"_id": 0, "equipment_id": 1, "serial": 1}):
        rec = await attribute_reuse(
            company_id, e["equipment_id"], meta={"serial": e.get("serial")})
        out["reuse"] += 1
        out["total_brl_attributed"] += rec["valor_confirmado_brl"]

    # 3) TRUCK ROLL evitadas (DO_NOT_DISPATCH + PREVENTIVA)
    async for d in db.truck_roll_decisions.find(
            {"company_id": company_id,
             "decision": {"$in": ["DO_NOT_DISPATCH", "PREVENTIVA"]},
             "ts": {"$gte": cutoff}},
            {"_id": 0, "subscriber_id": 1, "decision": 1, "ts": 1}):
        sid = d.get("subscriber_id")
        if not sid:
            continue
        rec = await attribute_truck_roll_avoided(company_id, sid)
        out["truck_roll"] += 1
        out["total_brl_attributed"] += rec["valor_confirmado_brl"]

    # 4) INCIDENTES escalados pelo Álvaro
    async for inc in db.incidents.find(
            {"company_id": company_id,
             "status": {"$in": ["escalated", "open"]},
             "created_at": {"$gte": cutoff}},
            {"_id": 0, "id": 1, "cto_id": 1, "olt_name": 1}):
        clients = await db.subscribers.count_documents({
            "company_id": company_id,
            "$or": [{"cto_id": inc.get("cto_id")},
                     {"olt_name": inc.get("olt_name")}]})
        # ticket médio
        pipe = [{"$match": {"company_id": company_id,
                              "plan_price": {"$gt": 0}}},
                {"$group": {"_id": None, "avg": {"$avg": "$plan_price"}}}]
        avg_doc = await db.subscribers.aggregate(pipe).to_list(1)
        avg = float((avg_doc[0]["avg"] if avg_doc else 90.0) or 90.0)
        if clients > 0:
            rec = await attribute_incident_protection(
                company_id, inc["id"],
                clients_affected=clients, ticket_avg_brl=avg)
            out["incident"] += 1
            out["total_brl_attributed"] += rec["valor_confirmado_brl"]

    # 5) OS sem retorno em 30d
    cutoff_close = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    async for t in db.smart_repairs.find(
            {"company_id": company_id,
             "status": {"$in": ["done", "closed", "concluido", "finalizado"]},
             "closed_at": {"$lte": cutoff_close,
                            "$gte": cutoff}},
            {"_id": 0, "id": 1, "subscriber_id": 1, "closed_at": 1}):
        sid = t.get("subscriber_id")
        if not sid:
            continue
        # tem nova OS pós-close?
        n_after = await db.smart_repairs.count_documents({
            "company_id": company_id,
            "subscriber_id": sid,
            "created_at": {"$gt": t["closed_at"]}})
        if n_after > 0:
            continue
        sub = await db.subscribers.find_one(
            {"id": sid, "company_id": company_id},
            {"_id": 0, "plan_price": 1, "monthly_value": 1})
        ticket = float((sub or {}).get("plan_price") or
                         (sub or {}).get("monthly_value") or 90.0)
        rec = await attribute_os_no_return_30d(
            company_id, t["id"], subscriber_id=sid, ticket_brl=ticket)
        out["os_no_return"] += 1
        out["total_brl_attributed"] += rec["valor_confirmado_brl"]

    out["total_brl_attributed"] = round(out["total_brl_attributed"], 2)
    out["ts"] = _now_iso()
    out["company_id"] = company_id

    # Resumo geral do ledger neste período (para auditoria)
    pipe = [
        {"$match": {"company_id": company_id,
                      "category": "PRESIDENTE_FINANCEIRO",
                      "ts": {"$gte": cutoff}}},
        {"$group": {"_id": "$kind",
                      "count": {"$sum": 1},
                      "valor": {"$sum": "$valor_confirmado_brl"}}},
    ]
    breakdown: List[Dict[str, Any]] = []
    async for r in db.executive_ledger.aggregate(pipe):
        breakdown.append({"kind": r["_id"], "count": r["count"],
                           "valor_brl": round(r["valor"], 2)})
    out["ledger_breakdown"] = breakdown
    return out
