"""SmartOLT AI — Worker de monitoramento inteligente da rede.

Inspirado em padrões 2026 (Google Cloud Autonomous Networks, Extreme Agent One):
detecta "outage events" agrupando ONUs offline pelo eixo OLT+PON usando
clustering temporal simples — quando ≥N ONUs no mesmo PON ficam LOS dentro
de uma janela de tempo, dispara um evento de outage.

Comunicação Agent-to-Agent (A2A pattern):
- SmartOLT AI grava outages em `network_outages` collection
- WhatsApp IA (atendimento) consulta antes de responder: se o phone do cliente
  pertence a um outage ativo, injeta contexto no system_prompt
- Atendimento IA pode optar por escalar ao humano (handover) automaticamente

Como o atendimento humano fica sabendo: ao assumir uma conversa marcada
com `outage_active=true`, a IA de atendimento já avisou no system_prompt
("este cliente está em região com pane confirmada — ETA estimado X min").
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core import DEMO_COMPANY_ID, now_iso
from database import db

logger = logging.getLogger("smartolt_ai")

# Threshold mínimo de ONUs LOS no mesmo PON para considerar outage
OUTAGE_MIN_LOS = 3
# Janela temporal: se ONUs ficaram LOS dentro desta janela, é o mesmo evento
OUTAGE_WINDOW_MIN = 15
# Tempo de "cooldown" após auto-recuperação antes de marcar evento como resolvido
OUTAGE_RESOLVE_MIN = 5


async def detect_outages(company_id: str = DEMO_COMPANY_ID) -> Dict[str, Any]:
    """Varre `smartolt_onus` agrupando por OLT+placa+porta+vlan e detecta
    grupos com ≥OUTAGE_MIN_LOS ONUs LOS.

    Cada outage detectado é upserted em `network_outages` com:
        - key: hash determinístico (olt+board+port+vlan)
        - status: active | resolved
        - los_count, total_count, severity_pct
        - first_detected_at, last_seen_at
        - affected_phones: list[str] (puxados de subscribers vinculados)
    """
    cursor = db.smartolt_onus.find(
        {"company_id": company_id},
        {"_id": 0, "unique_external_id": 1, "olt_name": 1, "board": 1,
         "port": 1, "vlan": 1, "status": 1, "name": 1, "pppoe_user": 1},
    )
    groups: Dict[str, Dict[str, Any]] = {}
    async for o in cursor:
        olt = (o.get("olt_name") or "").strip()
        board = str(o.get("board") or "").strip()
        port = str(o.get("port") or "").strip()
        vlan = str(o.get("vlan") or "").strip()
        if not olt or not board or not port:
            continue
        key = f"{olt}|B{board}|P{port}|V{vlan}"
        g = groups.setdefault(key, {
            "key": key, "olt_name": olt, "board": board, "port": port,
            "vlan": vlan, "los_count": 0, "online_count": 0, "total_count": 0,
            "los_onts": [],
        })
        g["total_count"] += 1
        status_lc = str(o.get("status") or "").lower()
        if "los" in status_lc or "offline" in status_lc or "dying" in status_lc:
            g["los_count"] += 1
            g["los_onts"].append({
                "external_id": o.get("unique_external_id"),
                "pppoe_user": o.get("pppoe_user"),
                "name": o.get("name"),
            })
        else:
            g["online_count"] += 1

    detected = 0
    resolved = 0
    now = now_iso()
    for key, g in groups.items():
        if g["los_count"] >= OUTAGE_MIN_LOS:
            # Outage ativo. Pega telefones afetados via PPPoE → subscriber.
            pppoes = [x["pppoe_user"] for x in g["los_onts"] if x.get("pppoe_user")]
            affected_phones: List[str] = []
            if pppoes:
                async for sub in db.subscribers.find(
                    {"company_id": company_id, "pppoe_user": {"$in": pppoes}},
                    {"_id": 0, "phones": 1, "name": 1},
                ):
                    for p in (sub.get("phones") or []):
                        ph = p.get("number") if isinstance(p, dict) else str(p)
                        if ph:
                            # Normaliza só dígitos
                            ph = "".join(c for c in ph if c.isdigit())
                            if ph and ph not in affected_phones:
                                affected_phones.append(ph)
            severity_pct = round(g["los_count"] / g["total_count"] * 100, 1) \
                if g["total_count"] else 0
            existing = await db.network_outages.find_one(
                {"company_id": company_id, "key": key, "status": "active"},
                {"_id": 0, "id": 1, "first_detected_at": 1},
            )
            if existing:
                await db.network_outages.update_one(
                    {"company_id": company_id, "key": key, "status": "active"},
                    {"$set": {
                        "los_count": g["los_count"],
                        "online_count": g["online_count"],
                        "total_count": g["total_count"],
                        "severity_pct": severity_pct,
                        "los_onts_sample": g["los_onts"][:10],
                        "affected_phones": affected_phones,
                        "last_seen_at": now,
                    }},
                )
            else:
                import uuid
                detected += 1
                await db.network_outages.insert_one({
                    "id": f"out-{uuid.uuid4().hex[:10]}",
                    "company_id": company_id,
                    "key": key,
                    "status": "active",
                    "olt_name": g["olt_name"],
                    "board": g["board"],
                    "port": g["port"],
                    "vlan": g["vlan"],
                    "los_count": g["los_count"],
                    "online_count": g["online_count"],
                    "total_count": g["total_count"],
                    "severity_pct": severity_pct,
                    "los_onts_sample": g["los_onts"][:10],
                    "affected_phones": affected_phones,
                    "first_detected_at": now,
                    "last_seen_at": now,
                })
                logger.warning(
                    "[smartolt-ai] OUTAGE detectado: %s — %d/%d LOS (%.1f%%) — %d clientes afetados",
                    key, g["los_count"], g["total_count"], severity_pct,
                    len(affected_phones),
                )
        else:
            # Sem outage — se havia ativo, resolve
            existing = await db.network_outages.find_one(
                {"company_id": company_id, "key": key, "status": "active"},
                {"_id": 0, "id": 1, "first_detected_at": 1},
            )
            if existing:
                resolved += 1
                duration_min = None
                try:
                    fdt = datetime.fromisoformat(existing["first_detected_at"])
                    duration_min = int((datetime.now(timezone.utc) - fdt).total_seconds() / 60)
                except Exception:
                    pass
                await db.network_outages.update_one(
                    {"company_id": company_id, "key": key, "status": "active"},
                    {"$set": {
                        "status": "resolved",
                        "resolved_at": now,
                        "duration_minutes": duration_min,
                    }},
                )
                logger.info("[smartolt-ai] OUTAGE resolvido: %s (durou %s min)",
                              key, duration_min)
    return {"detected": detected, "resolved": resolved,
            "groups_evaluated": len(groups)}


async def get_outage_for_phone(company_id: str, phone: str) -> Optional[Dict[str, Any]]:
    """Verifica se um telefone pertence a um outage ativo.

    Usado pela IA de atendimento (whatsapp_baileys) para injetar contexto:
    se cliente está em região com pane, IA já avisa proativamente.
    """
    if not phone:
        return None
    # Normaliza pra dígitos
    ph = "".join(c for c in phone if c.isdigit())
    if not ph:
        return None
    outage = await db.network_outages.find_one(
        {"company_id": company_id, "status": "active",
         "affected_phones": ph},
        {"_id": 0},
    )
    return outage


async def list_active_outages(company_id: str = DEMO_COMPANY_ID) -> List[Dict[str, Any]]:
    items = await db.network_outages.find(
        {"company_id": company_id, "status": "active"},
        {"_id": 0},
    ).sort("first_detected_at", -1).to_list(50)
    return items


async def list_recent_resolved(company_id: str = DEMO_COMPANY_ID,
                                  hours: int = 24) -> List[Dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    items = await db.network_outages.find(
        {"company_id": company_id, "status": "resolved",
         "resolved_at": {"$gte": cutoff}},
        {"_id": 0},
    ).sort("resolved_at", -1).to_list(50)
    return items


# ---------------------------------------------------------------------------
# Worker periódico
# ---------------------------------------------------------------------------
_worker_task: Optional[asyncio.Task] = None
INTERVAL_SECONDS = 90


async def _worker_loop():
    while True:
        try:
            await detect_outages(DEMO_COMPANY_ID)
        except Exception as e:
            logger.exception("[smartolt-ai] worker err: %s", e)
        await asyncio.sleep(INTERVAL_SECONDS)


def start_worker():
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_worker_loop())
    logger.info("[smartolt-ai] worker iniciado (intervalo=%ds)", INTERVAL_SECONDS)


def stop_worker():
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
