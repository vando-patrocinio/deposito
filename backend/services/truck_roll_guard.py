"""Truck Roll Guard — decide se um chamado precisa de visita técnica.

Reutiliza:
  - services.smartolt_client.find_onu_by_pppoe (status ONU + sinal)
  - db.subscribers (CTO do cliente + vizinhos)
  - db.tickets (recorrência)
  - db.incidents (incidente coletivo na região)
  - db.client_equipment_history (histórico de equipamento — modem trocado etc)

NÃO recria nenhum dado. Apenas correlaciona.

API pública:
  evaluate(company_id, subscriber_id) -> dict
    {
      "decision": "DO_NOT_DISPATCH" | "DISPATCH" | "ESCALATE_COLLECTIVE",
      "confidence": 0..1,
      "signals": {...},
      "rationale": "...",
    }
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

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from database import db

logger = logging.getLogger("truck_roll_guard")


async def _signal_onu(company_id: str, sub: Dict[str, Any]) -> Dict[str, Any]:
    pppoe = sub.get("pppoe") or sub.get("pppoe_user") or sub.get("login")
    if not pppoe:
        return {"online": None, "rx_power": None}
    try:
        from services.smartolt_client import find_onu_by_pppoe
        onu = await find_onu_by_pppoe(company_id, pppoe)
        if not onu:
            return {"online": None, "rx_power": None}
        sig = onu.get("rx_power") or onu.get("signal_dbm")
        try:
            sig_n = float(sig) if sig is not None else None
        except Exception:
            sig_n = None
        return {"online": bool(onu.get("online")),
                "rx_power": sig_n}
    except Exception:
        return {"online": None, "rx_power": None}


async def _signal_cto(company_id: str, sub: Dict[str, Any]) -> Dict[str, Any]:
    cto_id = sub.get("cto_id") or sub.get("ctoId")
    if not cto_id:
        return {"cto_id": None, "off_pct": None}
    off = await db.subscribers.count_documents({
        "company_id": company_id, "cto_id": cto_id, "status": "OFFLINE"})
    tot = await db.subscribers.count_documents({
        "company_id": company_id, "cto_id": cto_id})
    off_pct = (off * 100 / tot) if tot else None
    return {"cto_id": cto_id, "off_pct": off_pct, "off": off, "total": tot}


async def _signal_tickets(company_id: str, sub_id: str) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    try:
        n = await db.tickets.count_documents({
            "company_id": company_id,
            "$or": [
                {"subscriber_id": sub_id},
                {"client_id": sub_id},
                {"client_snapshot.id": sub_id},
            ],
            "created_at": {"$gte": cutoff},
        })
        return n
    except Exception:
        return 0


async def _signal_collective(company_id: str, sub: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    inc = await db.incidents.find_one({
        "company_id": company_id,
        "status": {"$in": ["open", "OPEN", "active"]},
        "$or": [
            {"olt_name": sub.get("olt_name")},
            {"cto_id": sub.get("cto_id")},
        ],
    }, {"_id": 0, "type": 1, "severity": 1, "title": 1})
    return inc


async def evaluate(company_id: str, subscriber_id: str) -> Dict[str, Any]:
    """Avalia se vale despachar técnico. Persiste decisão em
    `truck_roll_decisions` para auditoria/KPI."""
    sub = await db.subscribers.find_one({"id": subscriber_id, "company_id": company_id},
                                          {"_id": 0})
    if not sub:
        return {"decision": "UNKNOWN", "confidence": 0,
                "rationale": "subscriber não encontrado"}

    s_onu = await _signal_onu(company_id, sub)
    s_cto = await _signal_cto(company_id, sub)
    s_tic = await _signal_tickets(company_id, subscriber_id)
    s_inc = await _signal_collective(company_id, sub)

    decision = "DISPATCH"
    confidence = 0.6
    rationale: list[str] = []

    if s_inc:
        decision = "INCIDENTE_COLETIVO"
        confidence = 0.9
        rationale.append(f"incidente coletivo ativo: {s_inc.get('type')} / {s_inc.get('severity')}")
    elif s_cto.get("off_pct") and s_cto["off_pct"] > 30:
        decision = "INCIDENTE_COLETIVO"
        confidence = 0.85
        rationale.append(f"{s_cto['off']}/{s_cto['total']} vizinhos da CTO offline "
                          f"({s_cto['off_pct']:.0f}%)")
    elif s_onu["online"] is True and (s_onu["rx_power"] is None or s_onu["rx_power"] >= -25):
        # Online + sinal OK → 3+ tickets crônicos = PREVENTIVA, senão DO_NOT_DISPATCH
        if s_tic >= 3:
            decision = "PREVENTIVA"
            confidence = 0.85
            rationale.append(f"ONU online + {s_tic} tickets em 30d → preventiva técnica de causa-raiz")
        else:
            decision = "DO_NOT_DISPATCH"
            confidence = 0.8
            rationale.append(
                f"ONU online, sinal {s_onu['rx_power']:.1f} dBm" if s_onu["rx_power"] is not None
                else "ONU online, sinal OK")
            rationale.append("tente reset remoto ou orientação de reinício de modem")
    elif s_onu["online"] is False:
        decision = "DISPATCH"
        confidence = 0.7
        rationale.append("ONU offline e CTO saudável — provável problema individual")
    elif s_onu["rx_power"] is not None and s_onu["rx_power"] < -27:
        # Sinal degradado mas ONU pode estar online → PREVENTIVA antes do cliente reclamar
        if s_tic >= 2 or (s_onu["rx_power"] < -28):
            decision = "PREVENTIVA"
            confidence = 0.8
            rationale.append(f"sinal {s_onu['rx_power']:.1f} dBm — preventiva antes da pane")
        else:
            decision = "DISPATCH"
            confidence = 0.75
            rationale.append(f"sinal baixo: {s_onu['rx_power']:.1f} dBm — visita necessária")

    if s_tic >= 3:
        rationale.append(f"⚠️ {s_tic} tickets em 30 dias → problema crônico")
        if decision == "DISPATCH":
            confidence = min(0.95, confidence + 0.1)

    result = {
        "decision": decision,
        "confidence": round(confidence, 2),
        "signals": {
            "onu": s_onu, "cto": s_cto,
            "tickets_30d": s_tic,
            "collective_incident": bool(s_inc),
        },
        "rationale": " · ".join(rationale) if rationale else "—",
        "ts": datetime.now(timezone.utc).isoformat(),
        "subscriber_id": subscriber_id,
        "company_id": company_id,
    }
    # Persiste para KPI (truck_roll_avoidance_pct em company_v6)
    try:
        await db.truck_roll_decisions.insert_one(result.copy())
    except Exception as e:
        logger.warning("[truck_roll_guard] persist falhou: %s", e)
    # Hook financeiro automático: R$ no executive_ledger quando a decisão
    # evita visita (DO_NOT_DISPATCH ou PREVENTIVA).
    if decision in ("DO_NOT_DISPATCH", "PREVENTIVA"):
        try:
            from services.presidente_financeiro import attribute_truck_roll_avoided
            await attribute_truck_roll_avoided(
                company_id, subscriber_id,
                decision=decision, source="truck_roll_guard")
        except Exception as e:
            logger.info("[truck_roll_guard] ledger hook skip: %s", e)
    return result
