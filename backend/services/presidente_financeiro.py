"""OPERAÇÃO PRESIDENTE FINANCEIRO — sequência COLOSSO.

Atribui R$ confirmado ao `executive_ledger` para cada ação operacional
autônoma. Existem dois modos de atribuição:

  • TEMPO REAL — chamada por hook no fluxo operacional (idempotente).
  • BATCH — `run_attribution_cycle` reconcilia o que escapou (varredura).

CATEGORIAS:
  • PREVENTIVE_AVOIDED_VISIT       → preventiva criada (pending → confirmed
                                     quando OS fecha sem retorno em 30d)
  • EQUIPMENT_REUSED               → ONU/equipamento em REAPROVEITAMENTO
  • TRUCK_ROLL_AVOIDED             → DO_NOT_DISPATCH / PREVENTIVA
  • INCIDENT_REVENUE_PROTECTED     → incidente coletivo escalado
  • OS_NO_RETURN_30D               → reparo resolvido sem retorno 30d
  • ISABELLA_OS_CREATED            → OS criada pela Isabella (pending)
  • ISABELLA_OS_RESOLVED           → OS Isabella resolvida (confirmed)
  • ISABELLA_TRUCK_ROLL_BLOCKED    → Isabella decidiu não despachar
  • ALVARO_INCIDENT_DETECTED       → Álvaro detectou incidente coletivo
  • ALVARO_CLIENTS_PROTECTED       → clientes protegidos por ação Álvaro

IDEMPOTÊNCIA:
  Chave única upsert = (company_id, action_id, kind).
  Reexecução não duplica.

FÓRMULAS:
  • visita evitada              = R$ 80
  • equipamento reaproveitado   = R$ 120
  • incidente protegido         = clientes × ticket médio × 30%
  • OS sem retorno 30d          = ticket mensal × meses_protegidos
  • TRG bloqueado               = R$ 80
  • cliente protegido (Álvaro)  = ticket médio × 30%

STATUS:
  • pending_confirmation        — valor estimado, falta confirmação operacional
  • confirmed                   — valor confirmado por evento factual
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db

logger = logging.getLogger("presidente_financeiro")


# Valores de referência (configuráveis via env quando preciso)
VAL_PREVENTIVA_BRL = 80.0       # custo médio visita corretiva evitada
VAL_REAPROVEITAMENTO_BRL = 120.0  # ONU média recuperada
VAL_TRUCK_ROLL_AVOIDED_BRL = 80.0
PCT_INCIDENT_REVENUE_PROTECTION = 0.30


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _record_ledger(*, company_id: str, action_id: str, kind: str,
                            expected_brl: float, actual_brl: float,
                            evidence: Dict[str, Any],
                            status: str = "confirmed",
                            subscriber_id: Optional[str] = None
                            ) -> Dict[str, Any]:
    """Idempotente por (company_id, action_id, kind). Persiste no
    executive_ledger reutilizando o schema existente.

    Status:
      • "pending_confirmation" — valor estimado (será confirmado por evento)
      • "confirmed"            — valor factual confirmado por evento
    """
    doc = {
        "id": f"led-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "action_id": action_id,
        "kind": kind,
        "status": status,
        "category": "PRESIDENTE_FINANCEIRO",
        "source": "lousa_coo",
        "subscriber_id": subscriber_id,
        "expected_brl": round(expected_brl, 2),
        "valor_confirmado_brl": round(actual_brl, 2),
        "actual_BRL": round(actual_brl, 2),
        "evidence": evidence,
        "ts": _now_iso(),
        "created_at": _now_iso(),
    }
    try:
        await db.executive_ledger.update_one(
            {"company_id": company_id, "action_id": action_id, "kind": kind},
            {"$setOnInsert": doc},
            upsert=True)
    except Exception as e:
        logger.warning("[ledger] persist falhou (%s): %s", action_id, e)
    return doc


async def confirm_ledger_entry(company_id: str, action_id: str,
                                  kind: str, *, actual_brl: Optional[float] = None,
                                  extra_evidence: Optional[Dict[str, Any]] = None
                                  ) -> bool:
    """Promove um pending → confirmed (idempotente: nunca degrada
    confirmed → pending)."""
    update_set: Dict[str, Any] = {"status": "confirmed",
                                     "confirmed_at": _now_iso()}
    if actual_brl is not None:
        update_set["valor_confirmado_brl"] = round(actual_brl, 2)
        update_set["actual_BRL"] = round(actual_brl, 2)
    if extra_evidence:
        for k, v in extra_evidence.items():
            update_set[f"evidence.{k}"] = v
    try:
        r = await db.executive_ledger.update_one(
            {"company_id": company_id, "action_id": action_id, "kind": kind,
             "status": {"$ne": "confirmed"}},
            {"$set": update_set})
        return r.modified_count > 0
    except Exception:
        return False


async def attribute_preventive(company_id: str, ticket_id: str,
                                  *, value_brl: float = VAL_PREVENTIVA_BRL,
                                  subscriber_id: Optional[str] = None,
                                  status: str = "pending_confirmation",
                                  meta: Optional[Dict[str, Any]] = None
                                  ) -> Dict[str, Any]:
    """Preventiva criada → R$ visita corretiva evitada (PENDING).
    Confirma quando OS preventiva fechar sem retorno em 30d.
    """
    return await _record_ledger(
        company_id=company_id,
        action_id=f"preventive::{ticket_id}",
        kind="PREVENTIVE_AVOIDED_VISIT",
        status=status,
        subscriber_id=subscriber_id,
        expected_brl=value_brl, actual_brl=value_brl,
        evidence={"ticket_id": ticket_id,
                  "formula": "R$ 80 por visita corretiva evitada",
                  **(meta or {})})


async def attribute_reuse(company_id: str, equipment_id: str,
                            *, value_brl: float = VAL_REAPROVEITAMENTO_BRL,
                            subscriber_id: Optional[str] = None,
                            meta: Optional[Dict[str, Any]] = None
                            ) -> Dict[str, Any]:
    """Equipamento em REAPROVEITAMENTO → R$ patrimônio (CONFIRMED)."""
    return await _record_ledger(
        company_id=company_id,
        action_id=f"reuse::{equipment_id}",
        kind="EQUIPMENT_REUSED",
        status="confirmed",
        subscriber_id=subscriber_id,
        expected_brl=value_brl, actual_brl=value_brl,
        evidence={"equipment_id": equipment_id,
                  "formula": "R$ 120 por ONU/equipamento reaproveitado",
                  **(meta or {})})


async def attribute_truck_roll_avoided(company_id: str, subscriber_id: str,
                                           *, value_brl: float = VAL_TRUCK_ROLL_AVOIDED_BRL,
                                           decision: str = "DO_NOT_DISPATCH",
                                           source: str = "truck_roll_guard"
                                           ) -> Dict[str, Any]:
    """Truck Roll Guard = DO_NOT_DISPATCH / PREVENTIVA → visita evitada.

    Kind:
      • TRUCK_ROLL_AVOIDED         — origem truck_roll_guard
      • ISABELLA_TRUCK_ROLL_BLOCKED — origem isabella_lousa_scheduler (NO_OS)
    """
    kind = ("ISABELLA_TRUCK_ROLL_BLOCKED"
            if source == "isabella" else "TRUCK_ROLL_AVOIDED")
    today = datetime.now(timezone.utc).date().isoformat()
    return await _record_ledger(
        company_id=company_id,
        action_id=f"{kind.lower()}::{subscriber_id}::{today}",
        kind=kind,
        status="confirmed",
        subscriber_id=subscriber_id,
        expected_brl=value_brl, actual_brl=value_brl,
        evidence={"subscriber_id": subscriber_id,
                  "decision": decision,
                  "formula": "R$ 80 por visita evitada"})


async def attribute_incident_protection(company_id: str, incident_id: str,
                                            *, clients_affected: int,
                                            ticket_avg_brl: float,
                                            source: str = "alvaro"
                                            ) -> Dict[str, Any]:
    """Incidente escalado → protege 30% da receita dos clientes afetados.

    Kind:
      • INCIDENT_REVENUE_PROTECTED  — receita protegida
      • ALVARO_INCIDENT_DETECTED    — detecção autônoma (Álvaro)
      • ALVARO_CLIENTS_PROTECTED    — agregado clientes
    """
    revenue = round(clients_affected * ticket_avg_brl * PCT_INCIDENT_REVENUE_PROTECTION, 2)
    rec_inc = await _record_ledger(
        company_id=company_id,
        action_id=f"incident::{incident_id}",
        kind="INCIDENT_REVENUE_PROTECTED",
        status="confirmed",
        expected_brl=revenue, actual_brl=revenue,
        evidence={"incident_id": incident_id,
                  "clients_affected": clients_affected,
                  "ticket_avg_brl": ticket_avg_brl,
                  "formula": f"clientes × ticket × {int(PCT_INCIDENT_REVENUE_PROTECTION*100)}%"})
    if source == "alvaro":
        await _record_ledger(
            company_id=company_id,
            action_id=f"alvaro_incident::{incident_id}",
            kind="ALVARO_INCIDENT_DETECTED",
            status="confirmed",
            expected_brl=0.0, actual_brl=0.0,
            evidence={"incident_id": incident_id,
                      "formula": "evento puro, valor financeiro em INCIDENT_REVENUE_PROTECTED"})
        await _record_ledger(
            company_id=company_id,
            action_id=f"alvaro_clients::{incident_id}",
            kind="ALVARO_CLIENTS_PROTECTED",
            status="confirmed",
            expected_brl=revenue, actual_brl=revenue,
            evidence={"incident_id": incident_id,
                      "clients_affected": clients_affected,
                      "formula": f"ticket médio × {int(PCT_INCIDENT_REVENUE_PROTECTION*100)}% × n clientes"})
    return rec_inc


async def attribute_isabella_os(company_id: str, ticket_id: str,
                                    *, subscriber_id: str,
                                    status: str = "pending_confirmation",
                                    value_brl: float = VAL_TRUCK_ROLL_AVOIDED_BRL,
                                    extra: Optional[Dict[str, Any]] = None
                                    ) -> Dict[str, Any]:
    """OS criada pela Isabella → ISABELLA_OS_CREATED (pending).
    Confirma como ISABELLA_OS_RESOLVED quando OS fechar com sucesso.
    """
    return await _record_ledger(
        company_id=company_id,
        action_id=f"isabella_os::{ticket_id}",
        kind="ISABELLA_OS_CREATED",
        status=status,
        subscriber_id=subscriber_id,
        expected_brl=value_brl, actual_brl=value_brl,
        evidence={"ticket_id": ticket_id,
                  "formula": "estimativa R$ 80 por OS Isabella validada",
                  **(extra or {})})


async def attribute_isabella_os_resolved(company_id: str, ticket_id: str,
                                              *, subscriber_id: str,
                                              value_brl: float = VAL_TRUCK_ROLL_AVOIDED_BRL
                                              ) -> Dict[str, Any]:
    """Conclui o ciclo da Isabella: registra ISABELLA_OS_RESOLVED +
    confirma o ISABELLA_OS_CREATED correspondente."""
    rec = await _record_ledger(
        company_id=company_id,
        action_id=f"isabella_os_resolved::{ticket_id}",
        kind="ISABELLA_OS_RESOLVED",
        status="confirmed",
        subscriber_id=subscriber_id,
        expected_brl=value_brl, actual_brl=value_brl,
        evidence={"ticket_id": ticket_id,
                  "formula": "R$ 80 por OS Isabella resolvida sem retrabalho"})
    await confirm_ledger_entry(company_id, f"isabella_os::{ticket_id}",
                                 "ISABELLA_OS_CREATED",
                                 actual_brl=value_brl,
                                 extra_evidence={"resolved_ticket_id": ticket_id})
    return rec


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
        status="confirmed",
        subscriber_id=subscriber_id,
        expected_brl=value, actual_brl=value,
        evidence={"ticket_id": ticket_id, "subscriber_id": subscriber_id,
                  "formula": "ticket × meses sem retorno"})


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
