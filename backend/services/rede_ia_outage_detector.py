"""rede_ia_outage_detector.py — Detecção de outages (rupturas/quedas em massa).

Worker periódico (a cada 10 min) que:
  1. Agrupa ONUs `Critical` por (olt_name, zone_name) — granularidade mais
     fina que temos sem CTOs vinculadas.
  2. Se um cluster tem >= 5 ONUs Critical, abre bolha "🚨 Possível ruptura
     na fibra" no Painel de Chamados com prioridade `urgente`.
  3. Cooldown de 60 min por cluster pra não duplicar.
  4. Quando o cluster volta a < 5 → bolha auto-fecha como `resolvida`
     com observação "Sinal restaurado".
  5. Notifica gestores em tempo real via `notifications`.
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

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from database import db

logger = logging.getLogger("ponto.rede_outage")

# Configurações default — podem virar `settings` no futuro
OUTAGE_THRESHOLD = 5            # >= N ONUs critical no mesmo cluster
OUTAGE_COOLDOWN_MIN = 60        # 1h entre alertas do mesmo cluster
DETECTOR_INTERVAL_SEC = 600     # 10 min
DETECTOR_INITIAL_DELAY_SEC = 120  # 2 min após app subir

_worker_task: asyncio.Task = None


def _cluster_key(olt: str, zone: str) -> str:
    return f"{olt or '?'}::{zone or '?'}"


async def _detect_company(company_id: str) -> Dict[str, Any]:
    """Detecta clusters de ONUs Critical numa empresa e cria/fecha bolhas.

    Returns: estatísticas pra log.
    """
    cur = db.smartolt_onus.find(
        {"company_id": company_id, "signal_text": "Critical"},
        {"_id": 0, "unique_external_id": 1, "name": 1,
         "olt_name": 1, "zone_name": 1, "signal_1490": 1,
         "latitude": 1, "longitude": 1},
    )
    clusters: Dict[str, List[dict]] = {}
    async for o in cur:
        k = _cluster_key(o.get("olt_name") or "", o.get("zone_name") or "")
        clusters.setdefault(k, []).append(o)

    # Bolhas abertas anteriores (pra cooldown e auto-close)
    open_alerts = await db.tickets.find(
        {"company_id": company_id,
         "type": "OUTAGE_AUTO",
         "status": {"$in": ["pendente", "em_execucao", "agendada", "aberta"]}},
        {"_id": 0, "id": 1, "outage_cluster_key": 1,
         "outage_count_open": 1, "created_at": 1},
    ).to_list(200)
    open_by_key = {a.get("outage_cluster_key"): a for a in open_alerts}

    now = datetime.now(timezone.utc)
    created = 0
    resolved = 0
    skipped_cooldown = 0

    # 1) Detecta NOVOS outages
    for ckey, onus in clusters.items():
        if len(onus) < OUTAGE_THRESHOLD:
            continue
        if ckey in open_by_key:
            # Já tem alerta aberto — atualiza contagem
            await db.tickets.update_one(
                {"id": open_by_key[ckey]["id"]},
                {"$set": {
                    "outage_count_current": len(onus),
                    "last_check_at": now.isoformat(),
                }},
            )
            continue

        # Verifica cooldown (último alerta resolvido recentemente)
        recent_resolved = await db.tickets.find_one(
            {
                "company_id": company_id,
                "type": "OUTAGE_AUTO",
                "outage_cluster_key": ckey,
                "status": {"$in": ["resolvida", "executada", "cancelada",
                                    "finalizada"]},
            },
            sort=[("closed_at", -1)],
            projection={"_id": 0, "closed_at": 1},
        )
        if recent_resolved and recent_resolved.get("closed_at"):
            try:
                resolved_dt = datetime.fromisoformat(
                    recent_resolved["closed_at"])
                if (now - resolved_dt).total_seconds() < OUTAGE_COOLDOWN_MIN * 60:
                    skipped_cooldown += 1
                    continue
            except Exception:
                pass

        # Cria bolha automática
        sample = onus[0]
        olt = sample.get("olt_name") or "?"
        zone = sample.get("zone_name") or "?"
        # Média do sinal (quando disponível)
        sigs = [o.get("signal_1490") for o in onus
                if isinstance(o.get("signal_1490"), (int, float))]
        avg_sig = sum(sigs) / len(sigs) if sigs else None

        # Estimativa de centroide (média lat/lng se tiver)
        coords = [(o.get("latitude"), o.get("longitude")) for o in onus
                  if o.get("latitude") and o.get("longitude")]
        center_lat = (sum(c[0] for c in coords) / len(coords)
                      if coords else None)
        center_lng = (sum(c[1] for c in coords) / len(coords)
                      if coords else None)

        alert_id = f"outage-{uuid.uuid4().hex[:12]}"
        sample_list = [o.get("name") or o.get("unique_external_id")
                       for o in onus[:5]]
        outage_doc = {
            "id": alert_id,
            "company_id": company_id,
            "type": "OUTAGE_AUTO",
            "status": "pendente",
            "priority": "urgente",
            "created_at": now.isoformat(),
            "opened_at": now.isoformat(),
            "scheduled_time": now.isoformat(),
            "client_snapshot": {
                "name": f"🚨 OUTAGE — {olt} / {zone}",
                "address": f"OLT: {olt} · Zone: {zone}",
                "neighborhood": zone,
                "phone": "",
            },
            "relato": (
                f"⚠️ Detectado outage em massa: {len(onus)} clientes em "
                f"sinal CRÍTICO simultaneamente na OLT '{olt}' / Zone "
                f"'{zone}'. Possível ruptura de fibra, queda de OLT, "
                f"ou problema de alimentação no rack.\n\n"
                f"📊 Sinal médio Rx 1490nm: "
                f"{f'{avg_sig:.2f} dBm' if avg_sig else 'N/A'}\n"
                f"📍 Coords geocodificadas: {len(coords)}/{len(onus)}\n\n"
                f"🔍 Amostra de clientes afetados:\n"
                + "\n".join(f"  • {n}" for n in sample_list)
                + (f"\n  ... e mais {len(onus) - 5} clientes"
                   if len(onus) > 5 else "")
                + "\n\n"
                "🤖 Bolha gerada automaticamente pelo IA Rede. "
                "Auto-fechará quando o sinal estiver restaurado em todos."
            ),
            "position": int(now.timestamp() * -1000),  # topo da lista
            "outage_cluster_key": ckey,
            "outage_olt": olt,
            "outage_zone": zone,
            "outage_count_open": len(onus),
            "outage_count_current": len(onus),
            "outage_avg_signal": avg_sig,
            "outage_sample_ids": [o.get("unique_external_id") for o in onus[:20]],
            "auto_generated": True,
            "source": "rede_ia_outage_detector",
        }
        if center_lat is not None:
            outage_doc["latitude"] = center_lat
            outage_doc["longitude"] = center_lng
        await db.tickets.insert_one(outage_doc)
        created += 1

        # Notificação tempo real pros gestores
        try:
            notif = {
                "id": f"notif-{uuid.uuid4().hex[:10]}",
                "company_id": company_id,
                "type": "outage_detected",
                "severity": "critical",
                "title": f"🚨 Outage detectado: {olt} / {zone}",
                "body": (f"{len(onus)} clientes em sinal CRÍTICO. "
                         f"Bolha #{alert_id[:12]} criada."),
                "ticket_id": alert_id,
                "target_roles": ["gestor", "administrador", "operador"],
                "read_by": [],
                "created_at": now.isoformat(),
            }
            await db.notifications.insert_one(notif)
        except Exception as e:
            logger.warning("[outage] notif fail: %s", e)
        logger.warning("[outage] CRIOU %s — olt=%s zone=%s onus=%d avg_sig=%s",
                       alert_id, olt, zone, len(onus), avg_sig)

    # 2) Auto-fecha outages cujo cluster voltou a < threshold
    for ckey, alert in open_by_key.items():
        current = clusters.get(ckey, [])
        if len(current) >= OUTAGE_THRESHOLD:
            continue  # Ainda em outage
        # Restaurado — fecha
        await db.tickets.update_one(
            {"id": alert["id"]},
            {"$set": {
                "status": "resolvida",
                "outcome": "auto_resolved",
                "closed_at": now.isoformat(),
                "outage_count_current": len(current),
                "auto_resolved_reason": (
                    f"Sinal restaurado — {len(current)} clientes ainda em "
                    f"Critical (abaixo do limite {OUTAGE_THRESHOLD})"
                ),
            }},
        )
        resolved += 1
        try:
            notif = {
                "id": f"notif-{uuid.uuid4().hex[:10]}",
                "company_id": company_id,
                "type": "outage_resolved",
                "severity": "info",
                "title": "✅ Outage resolvido automaticamente",
                "body": (
                    f"Cluster {ckey.replace('::', ' / ')} restaurado. "
                    f"Bolha #{alert['id'][:12]} foi fechada."
                ),
                "ticket_id": alert["id"],
                "target_roles": ["gestor", "administrador", "operador"],
                "read_by": [],
                "created_at": now.isoformat(),
            }
            await db.notifications.insert_one(notif)
        except Exception:
            pass
        logger.info("[outage] AUTO-RESOLVED %s (cluster=%s now=%d)",
                    alert["id"], ckey, len(current))

    return {
        "company_id": company_id,
        "clusters_total": len(clusters),
        "clusters_above_threshold": sum(
            1 for c in clusters.values() if len(c) >= OUTAGE_THRESHOLD),
        "created": created,
        "resolved": resolved,
        "skipped_cooldown": skipped_cooldown,
    }


async def _worker_loop() -> None:
    """Loop principal: roda a cada 10 min, varre todas as empresas."""
    logger.info("[outage] worker iniciado (interval=%ds, threshold=%d)",
                DETECTOR_INTERVAL_SEC, OUTAGE_THRESHOLD)
    await asyncio.sleep(DETECTOR_INITIAL_DELAY_SEC)
    while True:
        try:
            # Pega todas empresas com pelo menos 1 ONU monitorada
            company_ids = await db.smartolt_onus.distinct("company_id")
            for cid in company_ids:
                if not cid:
                    continue
                try:
                    stats = await _detect_company(cid)
                    if stats["created"] > 0 or stats["resolved"] > 0:
                        logger.info("[outage] %s — %s", cid, stats)
                except Exception as e:
                    logger.exception("[outage] err company=%s: %s", cid, e)
        except Exception as e:
            logger.exception("[outage] loop err: %s", e)
        await asyncio.sleep(DETECTOR_INTERVAL_SEC)


async def start_worker() -> None:
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_loop())


async def stop_worker() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None


async def detect_now(company_id: str) -> Dict[str, Any]:
    """Trigger manual — exposto por endpoint admin."""
    return await _detect_company(company_id)
