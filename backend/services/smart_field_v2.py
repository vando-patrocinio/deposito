"""Smart Field Ops V2 + Estoque Autônomo + OS Context.

OPERAÇÃO COLOSSO — Missão 6 (Lousa Mobile V2) + Missão 7 (Estoque Vivo).

Sem coleções novas — reusa:
  • smart_repairs / smart_installs (OS)
  • client_equipment_history (movimentações de equipamento)
  • smartolt_onus (sinal/ONU)
  • subscribers (cliente)
  • tickets (histórico)
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def os_context_for_technician(company_id: str,
                                       ticket_id: str) -> Dict[str, Any]:
    """Entrega TUDO que o técnico precisa antes de sair da garagem:
      • Diagnóstico (truck roll decision + signals)
      • Causa provável
      • Histórico (últimos 5 tickets do cliente)
      • Equipamentos atribuídos (client_equipment_history)
      • Potência / ONU
      • Materiais previstos (heurística por causa)
    """
    ticket = await db.smart_repairs.find_one(
        {"id": ticket_id, "company_id": company_id}, {"_id": 0}) or \
             await db.smart_installs.find_one(
                 {"id": ticket_id, "company_id": company_id}, {"_id": 0})
    if not ticket:
        return {"error": "ticket não encontrado"}

    sub_id = ticket.get("subscriber_id")
    sub = await db.subscribers.find_one(
        {"id": sub_id, "company_id": company_id},
        {"_id": 0, "id": 1, "name": 1, "address": 1, "phones": 1,
         "pppoe": 1, "plan_name": 1, "cto_id": 1, "olt_name": 1}) if sub_id else None

    # Truck roll decision
    trd = await db.truck_roll_decisions.find_one(
        {"company_id": company_id, "subscriber_id": sub_id},
        {"_id": 0}, sort=[("ts", -1)]) if sub_id else None

    # Histórico (últimos 5 tickets fechados)
    history: List[Dict[str, Any]] = []
    if sub_id:
        async for h in db.smart_repairs.find(
                {"company_id": company_id, "subscriber_id": sub_id,
                 "id": {"$ne": ticket_id}},
                {"_id": 0, "id": 1, "type": 1, "reason": 1, "status": 1,
                 "created_at": 1, "closed_at": 1, "material_used": 1}
        ).sort("created_at", -1).limit(5):
            history.append(h)

    # Equipamentos
    equipment: List[Dict[str, Any]] = []
    if sub_id:
        async for e in db.client_equipment_history.find(
                {"company_id": company_id, "subscriber_id": sub_id},
                {"_id": 0, "id": 1, "kind": 1, "serial": 1, "model": 1,
                 "ts": 1, "action": 1}
        ).sort("ts", -1).limit(10):
            equipment.append(e)

    # Sinal/ONU
    onu = None
    if sub and sub.get("pppoe"):
        try:
            from services.smartolt_client import find_onu_by_pppoe
            onu = await find_onu_by_pppoe(company_id, sub["pppoe"])
        except Exception:
            onu = None

    # Causa provável (heurística do reason + signals)
    reason = (ticket.get("reason") or "").lower()
    causa: List[str] = []
    if "sinal" in reason or "dbm" in reason or (onu and onu.get("rx_power") and float(onu["rx_power"]) < -27):
        causa.append("cabo/conector da fibra (sinal degradado)")
    if "offline" in reason or (onu and onu.get("online") is False):
        causa.append("ONU offline (verificar fonte 12V e conector óptico)")
    if any(h.get("reason") == ticket.get("reason") for h in history):
        causa.append("recorrência: revisar causa-raiz da CTO/splitter")
    if not causa:
        causa.append("verificar sintomas reportados pelo cliente")

    # Materiais previstos (heurística por causa)
    materials_predicted: List[str] = []
    if "fibra" in " ".join(causa) or "cabo" in " ".join(causa):
        materials_predicted += ["conector SC/APC", "fusão (1 emenda)",
                                  "cordão óptico 3m"]
    if "ONU offline" in " ".join(causa):
        materials_predicted += ["fonte 12V/0.5A", "ONU reserva (sob avaliação)"]
    if ticket.get("type") == "install" or ticket.get("kind") == "install":
        materials_predicted += ["roteador WiFi", "drop fiber 80m",
                                  "abraçadeira/fixador"]

    # Fotos exigidas
    photos_required = ["foto do modem/ONU ligada",
                       "foto do conector da fibra no modem",
                       "foto do display/sinal da OLT (após teste)"]
    if ticket.get("kind") == "install" or ticket.get("type") == "install":
        photos_required += ["foto da fachada/casa", "foto do roteador instalado"]

    return {
        "ticket_id": ticket_id,
        "ticket": {
            "id": ticket.get("id"),
            "type": ticket.get("type"),
            "kind": ticket.get("kind"),
            "priority": ticket.get("priority"),
            "origin": ticket.get("origin"),
            "status": ticket.get("status"),
            "reason": ticket.get("reason"),
            "created_at": ticket.get("created_at"),
        },
        "client": sub,
        "diagnostic": {
            "truck_roll_decision": (trd or {}).get("decision"),
            "truck_roll_confidence": (trd or {}).get("confidence"),
            "rationale": (trd or {}).get("rationale"),
            "signals": (trd or {}).get("signals"),
        },
        "probable_cause": causa,
        "history": history,
        "equipment_assigned": equipment,
        "onu": onu,
        "materials_predicted": materials_predicted,
        "photos_required": photos_required,
        "ts": _now_iso(),
    }


# ---------------------------------------------------------------------------
# ESTOQUE AUTÔNOMO — cadeia COMPRA → CLIENTE → REAPROVEITAMENTO
# Reuso 100% de client_equipment_history (registramos cada transição).
# ---------------------------------------------------------------------------

STAGES = ["COMPRA", "RECEBIMENTO", "ESTOQUE_CENTRAL", "ESTOQUE_TECNICO",
          "CLIENTE", "RETIRADA", "TESTE", "REAPROVEITAMENTO"]


async def track_equipment_stage(*, company_id: str, equipment_id: str,
                                  serial: Optional[str], stage: str,
                                  technician_id: Optional[str] = None,
                                  subscriber_id: Optional[str] = None,
                                  cost_brl: Optional[float] = None,
                                  notes: Optional[str] = None
                                  ) -> Dict[str, Any]:
    """Registra 1 transição na cadeia de estoque (auditável)."""
    assert stage in STAGES, f"stage inválido: {stage}"
    doc = {
        "id": f"eqp-stage-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "equipment_id": equipment_id,
        "serial": serial,
        "stage": stage,
        "technician_id": technician_id,
        "subscriber_id": subscriber_id,
        "cost_brl": cost_brl,
        "notes": notes,
        "ts": _now_iso(),
        "action": "STAGE_TRANSITION",
    }
    try:
        await db.client_equipment_history.insert_one(doc)
    except Exception:
        pass
    # Atualiza estado atual do equipamento (upsert em equipment_state — usa
    # client_equipment_history.kind=current pra não criar coleção nova)
    try:
        await db.client_equipment_history.update_one(
            {"company_id": company_id, "equipment_id": equipment_id,
             "kind": "current_state"},
            {"$set": {"company_id": company_id,
                      "equipment_id": equipment_id,
                      "serial": serial,
                      "kind": "current_state",
                      "current_stage": stage,
                      "current_holder": technician_id or subscriber_id or "central",
                      "updated_at": _now_iso()}}, upsert=True)
    except Exception:
        pass
    # Hook financeiro: REAPROVEITAMENTO → R$ 120 patrimônio recuperado
    if stage == "REAPROVEITAMENTO":
        try:
            from services.presidente_financeiro import attribute_reuse
            await attribute_reuse(
                company_id, equipment_id,
                subscriber_id=subscriber_id,
                meta={"serial": serial, "technician_id": technician_id})
        except Exception:
            pass
    return doc


async def stock_health(company_id: str) -> Dict[str, Any]:
    """Métricas da cadeia. Conta itens por estágio e fluxos críticos."""
    counts: Dict[str, int] = {}
    for stg in STAGES:
        counts[stg] = await db.client_equipment_history.count_documents(
            {"company_id": company_id, "kind": "current_state",
             "current_stage": stg})

    # Itens parados em "TESTE" há mais de 7 dias = oportunidade de reaproveitamento
    cutoff = (datetime.now(timezone.utc).timestamp() - 7 * 86400)
    stuck_in_test: List[Dict[str, Any]] = []
    async for doc in db.client_equipment_history.find(
            {"company_id": company_id, "kind": "current_state",
             "current_stage": "TESTE"},
            {"_id": 0, "equipment_id": 1, "serial": 1, "updated_at": 1}).limit(100):
        try:
            t = datetime.fromisoformat(doc["updated_at"].replace("Z", "+00:00"))
            if t.timestamp() < cutoff:
                stuck_in_test.append(doc)
        except Exception:
            pass

    # Equipamentos em RETIRADA aguardando reaproveitamento
    pending_recovery = counts.get("RETIRADA", 0)

    return {
        "company_id": company_id,
        "by_stage": counts,
        "stuck_in_test_7d_plus": len(stuck_in_test),
        "pending_recovery": pending_recovery,
        "ts": _now_iso(),
    }
