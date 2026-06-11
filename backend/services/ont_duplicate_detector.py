"""Detector de ONT Duplicada — iter164.

Alerta proativo quando o mesmo equipamento (SN ou MAC) é instalado em
clientes diferentes em curto espaço de tempo SEM uma retirada
correspondente entre as instalações.

Casos típicos detectados:
1. "ONT pirata" — técnico levou o equipamento de outro cliente sem
   passar pelo fluxo de Retirada.
2. Erro de cadastro — SN/MAC digitado errado, batendo em outra ONT.
3. Clonagem física — atacante usou SN/MAC válido em equipamento próprio.

Algoritmo:
  Para cada `install` em {client_A}, procuramos installs anteriores do
  MESMO `ont_mac` (ou `ont_sn`) em {client_B != client_A} dentro do
  `window_days` (padrão 30). Se NÃO houve `withdraw` desse equipamento
  para `client_B` entre o install antigo e agora, dispara alerta.

Persistência: `db.ont_duplicate_alerts`.
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

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from core import now_iso
from database import db

logger = logging.getLogger("ponto.ont_duplicate")

DEFAULT_WINDOW_DAYS = 30


def _iso_minus_days(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


async def detect_and_log(
    *,
    company_id: str,
    client_id: str,
    client_name: Optional[str],
    ont_mac: Optional[str],
    ont_sn: Optional[str],
    actor_name: Optional[str] = None,
    actor_email: Optional[str] = None,
    ticket_id: Optional[str] = None,
    service_id: Optional[str] = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> Optional[Dict[str, Any]]:
    """Verifica se o ONT recém-instalado já aparece em outro cliente
    recentemente sem retirada. Se detectado, persiste o alerta e cria
    notificação para o gestor. Retorna o doc do alerta (ou None).
    """
    if not company_id or not client_id:
        return None
    if not (ont_mac or ont_sn):
        return None
    since = _iso_minus_days(window_days)

    # 1) Busca installs anteriores do mesmo MAC/SN em outro cliente, no janela
    or_match: List[Dict[str, Any]] = []
    if ont_mac:
        or_match.append({"ont_mac": ont_mac})
    if ont_sn:
        or_match.append({"ont_sn": ont_sn})
    if not or_match:
        return None

    try:
        prev_installs = await db.client_equipment_history.find(
            {
                "company_id": company_id,
                "action": "install",
                "client_id": {"$ne": client_id},
                "captured_at": {"$gte": since},
                "$or": or_match,
            },
            {"_id": 0},
        ).sort("captured_at", -1).limit(5).to_list(5)
    except Exception as e:
        logger.warning("[ont_duplicate] busca histórico falhou: %s", e)
        return None

    if not prev_installs:
        return None

    # 2) Para cada install anterior, descarta se já houve withdraw posterior
    conflicts: List[Dict[str, Any]] = []
    for prev in prev_installs:
        prev_client = prev.get("client_id")
        prev_when = prev.get("captured_at")
        # Verifica se existe withdraw posterior em prev_client com mesmo mac/sn
        wd_or: List[Dict[str, Any]] = []
        if ont_mac:
            wd_or.append({"ont_mac": ont_mac})
        if ont_sn:
            wd_or.append({"ont_sn": ont_sn})
        try:
            withdraw_after = await db.client_equipment_history.find_one(
                {
                    "company_id": company_id,
                    "action": "withdraw",
                    "client_id": prev_client,
                    "captured_at": {"$gt": prev_when or ""},
                    "$or": wd_or,
                },
                {"_id": 0, "id": 1, "captured_at": 1},
            )
        except Exception as e:
            logger.warning("[ont_duplicate] busca withdraw falhou: %s", e)
            withdraw_after = None

        if withdraw_after:
            continue  # legítimo: retirou de A antes de instalar em B
        conflicts.append(prev)

    if not conflicts:
        return None

    # 3) Persiste o alerta
    alert_doc = {
        "id": f"odup-{uuid.uuid4().hex[:12]}",
        "company_id": company_id,
        "status": "open",
        "severity": "critical" if len(conflicts) >= 2 else "warning",
        "ont_mac": ont_mac,
        "ont_sn": ont_sn,
        "current_client_id": client_id,
        "current_client_name": client_name,
        "current_ticket_id": ticket_id,
        "current_service_id": service_id,
        "actor_name": actor_name,
        "actor_email": actor_email,
        "conflicts": [
            {
                "client_id": c.get("client_id"),
                "client_name": c.get("client_name"),
                "installed_at": c.get("captured_at"),
                "installed_by": c.get("actor_name") or c.get("actor_email"),
                "ticket_id": c.get("ticket_id"),
                "history_id": c.get("id"),
            }
            for c in conflicts
        ],
        "window_days": window_days,
        "detected_at": now_iso(),
    }
    try:
        await db.ont_duplicate_alerts.insert_one(alert_doc)
    except Exception as e:
        logger.warning("[ont_duplicate] persist alert falhou: %s", e)
        return None

    # 4) Notificação para o gestor
    try:
        conflict_msg = "; ".join(
            f"{c.get('client_name') or c.get('client_id')} "
            f"({(c.get('installed_at') or '')[:10]})"
            for c in conflicts[:3]
        )
        await db.notifications.insert_one({
            "id": f"notif-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "type": "ont_duplicate_alert",
            "title": "🚨 ONT em uso por múltiplos clientes",
            "message": (
                f"O equipamento {ont_sn or ont_mac} foi instalado em "
                f"{client_name or client_id} mas já havia sido instalado "
                f"recentemente em: {conflict_msg}. Verificar se houve "
                f"retirada não registrada ou clonagem."
            ),
            "severity": alert_doc["severity"],
            "created_at": now_iso(),
            "read_by": [],
            "audience_role": "gestor",
            "ticket_id": ticket_id,
            "duplicate_alert_id": alert_doc["id"],
        })
    except Exception as e:
        logger.warning("[ont_duplicate] notification falhou: %s", e)

    logger.info(
        "[ont_duplicate] alerta criado: %s (mac=%s sn=%s conflitos=%d)",
        alert_doc["id"], ont_mac, ont_sn, len(conflicts),
    )
    return alert_doc


async def list_alerts(company_id: str, status: str = "open",
                        limit: int = 100) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"company_id": company_id}
    if status and status != "all":
        q["status"] = status
    return await db.ont_duplicate_alerts.find(q, {"_id": 0}) \
        .sort("detected_at", -1) \
        .limit(min(max(limit, 1), 500)) \
        .to_list(min(max(limit, 1), 500))


async def resolve_alert(company_id: str, alert_id: str,
                          resolution: str,
                          notes: Optional[str] = None,
                          resolved_by: Optional[str] = None) -> bool:
    """resolution ∈ {ok_legitimo, retirada_nao_registrada, clonagem,
    erro_cadastro, outro}"""
    res = await db.ont_duplicate_alerts.update_one(
        {"id": alert_id, "company_id": company_id, "status": "open"},
        {"$set": {
            "status": "resolved",
            "resolution": resolution,
            "resolution_notes": (notes or "").strip()[:500] or None,
            "resolved_at": now_iso(),
            "resolved_by": resolved_by,
        }},
    )
    return res.modified_count > 0
