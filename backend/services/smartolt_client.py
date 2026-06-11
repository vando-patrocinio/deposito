"""SmartOLT client wrapper — leitura de `smartolt_onus` direto do DB.

Operação Colosso: elimina dependência de serviço externo. Sempre que algum
módulo precisar de status/sinal de ONU pelo PPPOE, lê do banco real.
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "infra-team",
    "domain": "rede",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from typing import Any, Dict, Optional

from database import db


async def find_onu_by_pppoe(company_id: str, pppoe: str) -> Optional[Dict[str, Any]]:
    """Busca a ONU mais recente pelo PPPoE. Retorna `None` se não encontrar."""
    if not pppoe:
        return None
    doc = await db.smartolt_onus.find_one(
        {"company_id": company_id, "pppoe": pppoe},
        {"_id": 0})
    if not doc:
        # Fallback: subscriber → pppoe → tentar variações
        return None
    # Normaliza campos esperados pelos consumidores
    sig = doc.get("rx_power") or doc.get("signal_1310") or doc.get("signal_dbm")
    return {
        "id": doc.get("id"),
        "subscriber_id": doc.get("subscriber_id"),
        "online": doc.get("online", doc.get("status") in ("Online", "ONLINE", "online")),
        "rx_power": sig,
        "signal_dbm": sig,
        "signal_1310": doc.get("signal_1310"),
        "status": doc.get("status"),
        "cto_id": doc.get("cto_id"),
        "olt_name": doc.get("olt_name"),
    }
