"""Provider health snapshot — dashboard de comparação Baileys vs Evolution.

CTO 15/06/2026: agrega telemetria dos últimos 7d (wa_dispatch_metrics +
wa_sidecar_restart_log + wa_system_events) e devolve em um payload pronto
pra renderização em card no painel WhatsApp Channels.

Por enquanto a telemetria é GLOBAL (não por canal/provider — coleta atual
não discrimina). Mostramos como métricas "do tenant" enquanto não migramos
o logging pra incluir provider/channel_id. Já preparamos os campos pra
quando Evolution for usado e os docs tiverem `transport=evolution`.
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "whatsapp",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from datetime import datetime, timezone, timedelta
from typing import Optional


def _percentile(values: list[float], p: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    idx = int(round((p / 100.0) * (len(s) - 1)))
    return s[max(0, min(idx, len(s) - 1))]


async def collect(db, company_id: str, channel: dict, days: int = 7) -> dict:
    """Coleta métricas dos últimos `days` dias pra um canal específico.

    Retorna shape:
      {
        current_provider, alternative_provider, window_days,
        current: { total_sent, success_rate, latency_p50_ms, latency_p95_ms,
                    crash_count_7d, last_crash_at, last_status, connected_now,
                    last_event },
        alternative: { configured: bool, ... métricas se já houver dados ... },
        recommendation: { action: 'stay'|'configure_alt'|'consider_migrate',
                            reason: str, severity: 'low'|'medium'|'high' }
      }
    """
    days = max(1, min(int(days), 90))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.isoformat()

    current_provider = channel.get("provider") or "baileys"
    alternative_provider = "evolution" if current_provider == "baileys" else "baileys"

    # ── métricas de dispatch (global do tenant) ──
    cur_dispatch = db.wa_dispatch_metrics.find(
        {"company_id": company_id, "ts": {"$gte": since_iso}},
        {"_id": 0, "ok": 1, "latency_ms": 1, "reason": 1, "ts": 1},
    )
    total = 0
    ok_count = 0
    latencies: list[float] = []
    async for d in cur_dispatch:
        total += 1
        if d.get("ok"):
            ok_count += 1
        lat = d.get("latency_ms")
        if isinstance(lat, (int, float)):
            latencies.append(float(lat))
    success_rate = round((ok_count / total) * 100, 1) if total else None

    # ── crashes do sidecar Baileys (último 7d) ──
    crash_count = 0
    last_crash_at = None
    if current_provider == "baileys":
        async for r in db.wa_sidecar_restart_log.find(
            {"started_at": {"$gte": since_iso}}, {"_id": 0, "started_at": 1},
        ):
            crash_count += 1
            sa = r.get("started_at")
            if sa and (not last_crash_at or sa > last_crash_at):
                last_crash_at = sa

    # ── último evento de sistema (pra texto descritivo) ──
    last_evt = await db.wa_system_events.find_one(
        {"company_id": company_id},
        {"_id": 0, "kind": 1, "text": 1, "created_at": 1},
        sort=[("created_at", -1)],
    )

    current_metrics = {
        "total_sent": total,
        "success_rate": success_rate,
        "latency_p50_ms": _percentile(latencies, 50),
        "latency_p95_ms": _percentile(latencies, 95),
        "crash_count_7d": crash_count,
        "last_crash_at": last_crash_at,
        "last_status": channel.get("last_status"),
        "connected_now": channel.get("last_status") == "open"
                          or channel.get("last_status") == "connected",
        "last_event": last_evt,
    }

    alt_configured = bool(channel.get("evolution_url")
                            and channel.get("evolution_api_key")
                            and channel.get("evolution_instance_name"))
    alternative_block = {
        "configured": alt_configured,
        "provider": alternative_provider,
        "note": (
            "Pronto pra migrar com 1 clique." if alt_configured else
            "Configure o provider alternativo (botão Provedor) antes de migrar."
        ),
    }

    # ── Recomendação ──
    reco_action = "stay"
    reco_reason = "Sem sinais negativos relevantes."
    reco_severity = "low"

    # se Baileys com >2 crashes na semana → considere migrar
    if current_provider == "baileys" and crash_count >= 2:
        reco_action = "consider_migrate"
        reco_reason = (
            f"{crash_count} restart(s) do sidecar Baileys nos últimos {days}d. "
            f"Evolution API tem maior estabilidade em produção."
        )
        reco_severity = "high" if crash_count >= 5 else "medium"
    elif success_rate is not None and success_rate < 90:
        reco_action = "consider_migrate"
        reco_reason = (
            f"Taxa de sucesso de envio = {success_rate}% nos últimos {days}d. "
            f"Investigar perdas ou trocar provider."
        )
        reco_severity = "high" if success_rate < 70 else "medium"
    elif not alt_configured:
        reco_action = "configure_alt"
        reco_reason = (
            f"Provider alternativo ({alternative_provider}) ainda não configurado. "
            f"Configure-o pra ter um fallback pronto."
        )
        reco_severity = "low"

    return {
        "channel_id": channel.get("id"),
        "current_provider": current_provider,
        "alternative_provider": alternative_provider,
        "window_days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "current": current_metrics,
        "alternative": alternative_block,
        "recommendation": {
            "action": reco_action,
            "reason": reco_reason,
            "severity": reco_severity,
        },
    }
