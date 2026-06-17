"""wa_sidecar_watchdog.py — Watchdog dos sidecars Baileys.

P0 (CEO 17/02/2026):
    Monitora estado dos sidecars Baileys (CH1..CH4) a cada 30s.
    Detecta transição `disconnected/connecting/banned → connected` e,
    quando um sidecar volta online, dispara reenvio automático das
    mensagens `delivery_status in [failed_send, failed_timeout]` das
    últimas N horas — **somente pelo próprio Baileys**, jamais via
    Evolution. Regra dura: sem fallback cruzado.

Persistência:
    - `wa_sidecar_watchdog_state` (1 doc por sidecar URL):
        { sidecar, url, last_state, last_state_at, last_check_at,
          last_recovery_at, last_recovery_retried, last_recovery_succeeded,
          last_health_payload }
    - `wa_sidecar_watchdog_events` (append-only log de transições).

Integração:
    `register_scheduler(scheduler)` adiciona job `wa_sidecar_watchdog`
    com intervalo `WA_WATCHDOG_INTERVAL_S` (default 30s).

Bypass: nunca usa `wa_dispatcher` para evitar herdar lógica de circuit
breaker durante recuperação. Vai direto no sidecar (Baileys puro).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from database import db

logger = logging.getLogger("wa.sidecar_watchdog")

# ── Config ────────────────────────────────────────────────────


def _interval_s() -> int:
    try:
        return max(10, int(os.environ.get("WA_WATCHDOG_INTERVAL_S") or 30))
    except (TypeError, ValueError):
        return 30


def _retry_window_hours() -> int:
    try:
        return max(1, min(72, int(
            os.environ.get("WA_WATCHDOG_RETRY_WINDOW_H") or 12)))
    except (TypeError, ValueError):
        return 12


def _max_retry_per_tick() -> int:
    try:
        return max(1, min(500, int(
            os.environ.get("WA_WATCHDOG_MAX_RETRY_PER_TICK") or 50)))
    except (TypeError, ValueError):
        return 50


def _sidecars() -> List[Dict[str, str]]:
    """Lista de sidecars configurados via env (CH1..CH4)."""
    out: List[Dict[str, str]] = []
    for n in (1, 2, 3, 4):
        url = os.environ.get(f"WA_SIDECAR_URL_CH{n}")
        if url:
            out.append({"id": f"ch{n}", "url": url.rstrip("/")})
    if not out:
        legacy = (os.environ.get("WA_SIDECAR_URL")
                  or os.environ.get("BAILEYS_SIDECAR_URL"))
        if legacy:
            out.append({"id": "default", "url": legacy.rstrip("/")})
    return out


def _token_header() -> Dict[str, str]:
    tok = os.environ.get("WA_SIDECAR_TOKEN", "")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


# ── Health probe ──────────────────────────────────────────────


async def _probe(url: str) -> Dict[str, Any]:
    """Faz health-check do sidecar. Retorna payload normalizado."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as cli:
            r = await cli.get(f"{url}/health")
            if r.status_code != 200:
                return {"reachable": True, "state": "unreachable",
                        "http_status": r.status_code}
            payload = r.json() if r.content else {}
            state = (payload.get("state") or "").lower() or "unknown"
            return {"reachable": True, "state": state, "payload": payload}
    except httpx.TimeoutException:
        return {"reachable": False, "state": "timeout"}
    except Exception as e:  # noqa: BLE001
        return {"reachable": False, "state": "error",
                "error": str(e)[:160]}


# ── Retry quando sidecar volta ────────────────────────────────


async def _send_direct(url: str, phone: str, text: str,
                       msg_id: Optional[str] = None) -> Dict[str, Any]:
    """Envia direto pro sidecar (Baileys-only). Sem fallback cruzado."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as cli:
            r = await cli.post(
                f"{url}/send",
                json={"phone": phone, "text": text, "id": msg_id},
                headers=_token_header())
            try:
                body = r.json()
            except Exception:
                body = {"raw": (r.text or "")[:200]}
            ok = (r.status_code == 200 and bool(body.get("ok")))
            return {"ok": ok, "status": r.status_code, "body": body}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"send_exc:{str(e)[:160]}"}


async def _retry_failed_for_baileys(url: str) -> Dict[str, int]:
    """Reenvia mensagens `failed_send/failed_timeout` via Baileys.

    Critério de elegibilidade (Baileys-only, sem ambiguidade):
        - `direction == outbound`
        - `delivery_status in [failed_send, failed_timeout]`
        - `created_at >= now - WA_WATCHDOG_RETRY_WINDOW_H`
        - `channel == baileys` **OU** `channel` ausente/vazio (legado
          pré-strict-routing). Mensagens com `channel=evolution` NUNCA
          são reenviadas pelo watchdog do Baileys.
    """
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=_retry_window_hours())).isoformat()
    query: Dict[str, Any] = {
        "direction": "outbound",
        "delivery_status": {"$in": ["failed_send", "failed_timeout"]},
        "created_at": {"$gte": cutoff},
        "$or": [
            {"channel": "baileys"},
            {"channel": {"$exists": False}},
            {"channel": None},
            {"channel": ""},
        ],
    }
    cursor = (db.aihub_wa_messages
              .find(query, {"_id": 0, "id": 1, "message_id": 1,
                            "external_id": 1, "phone": 1, "text": 1,
                            "created_at": 1, "company_id": 1, "channel": 1})
              .sort("created_at", 1)
              .limit(_max_retry_per_tick()))
    docs = [m async for m in cursor]
    retried = 0
    succeeded = 0
    failed = 0
    for m in docs:
        phone = (m.get("phone") or "").strip()
        text = m.get("text") or ""
        if not phone or not text:
            continue
        retried += 1
        mid = m.get("id") or m.get("message_id") or m.get("external_id")
        r = await _send_direct(url, phone=phone, text=text, msg_id=mid)
        if r.get("ok"):
            succeeded += 1
            filt: Dict[str, Any] = {}
            if m.get("external_id"):
                filt = {"external_id": m["external_id"]}
            elif m.get("id"):
                filt = {"id": m["id"]}
            elif m.get("message_id"):
                filt = {"message_id": m["message_id"]}
            else:
                filt = {"phone": phone, "created_at": m.get("created_at")}
            await db.aihub_wa_messages.update_one(filt, {"$set": {
                "delivery_status": "sent",
                "retry_applied_at": datetime.now(timezone.utc).isoformat(),
                "retry_via": "watchdog_baileys",
                "retry_reason": "sidecar_recovered_from_offline",
            }})
            logger.info(
                "[watchdog.retry] sidecar=%s phone=%s mid=%s status=sent",
                url, phone, mid)
        else:
            failed += 1
            logger.warning(
                "[watchdog.retry] sidecar=%s phone=%s mid=%s status=fail "
                "reason=%s", url, phone, mid,
                r.get("reason") or (r.get("body") or {}).get("error"))
    return {"retried": retried, "succeeded": succeeded, "failed": failed}


# ── Tick principal ────────────────────────────────────────────


async def tick() -> Dict[str, Any]:
    """Executa 1 ciclo do watchdog: probe + detect recovery + retry."""
    now = datetime.now(timezone.utc)
    summary: List[Dict[str, Any]] = []

    for sc in _sidecars():
        sid = sc["id"]
        url = sc["url"]
        probe = await _probe(url)
        new_state = probe.get("state") or "unknown"

        prev = await db.wa_sidecar_watchdog_state.find_one(
            {"sidecar": sid}, {"_id": 0, "last_state": 1})
        prev_state = (prev or {}).get("last_state")

        recovered = bool(prev_state and prev_state != "connected"
                         and new_state == "connected")

        retry_result: Dict[str, int] = {"retried": 0, "succeeded": 0,
                                        "failed": 0}
        if recovered:
            logger.info(
                "[watchdog] sidecar=%s RECOVERED %s→connected — disparando "
                "retry de mensagens failed_send", sid, prev_state)
            try:
                retry_result = await _retry_failed_for_baileys(url)
                logger.info(
                    "[watchdog] sidecar=%s retry retried=%d succeeded=%d "
                    "failed=%d", sid, retry_result["retried"],
                    retry_result["succeeded"], retry_result["failed"])
                await db.wa_sidecar_watchdog_events.insert_one({
                    "ts": now,
                    "sidecar": sid,
                    "url": url,
                    "from_state": prev_state,
                    "to_state": new_state,
                    "retried": retry_result["retried"],
                    "succeeded": retry_result["succeeded"],
                    "failed": retry_result["failed"],
                })
            except Exception as e:  # noqa: BLE001
                logger.exception(
                    "[watchdog] sidecar=%s retry exc: %s", sid, e)

        # Atualiza estado persistente
        update: Dict[str, Any] = {
            "sidecar": sid,
            "url": url,
            "last_state": new_state,
            "last_check_at": now,
            "last_health_payload": probe.get("payload") or {},
            "reachable": bool(probe.get("reachable")),
        }
        if prev_state != new_state:
            update["last_state_at"] = now
            update["prev_state"] = prev_state
        if recovered:
            update["last_recovery_at"] = now
            update["last_recovery_retried"] = retry_result["retried"]
            update["last_recovery_succeeded"] = retry_result["succeeded"]
            update["last_recovery_failed"] = retry_result["failed"]

        await db.wa_sidecar_watchdog_state.update_one(
            {"sidecar": sid}, {"$set": update}, upsert=True)

        summary.append({
            "sidecar": sid,
            "url": url,
            "state": new_state,
            "prev_state": prev_state,
            "transition": prev_state != new_state,
            "recovered": recovered,
            **retry_result,
        })

    return {"ok": True, "ts": now.isoformat(), "sidecars": summary}


async def status() -> Dict[str, Any]:
    """Snapshot atual do watchdog para painel/diagnóstico."""
    docs = await db.wa_sidecar_watchdog_state.find(
        {}, {"_id": 0}).to_list(50)
    for d in docs:
        for k in ("last_check_at", "last_state_at", "last_recovery_at"):
            v = d.get(k)
            if isinstance(v, datetime):
                d[k] = v.isoformat()
    events = await (db.wa_sidecar_watchdog_events
                    .find({}, {"_id": 0})
                    .sort("ts", -1).limit(20).to_list(20))
    for ev in events:
        v = ev.get("ts")
        if isinstance(v, datetime):
            ev["ts"] = v.isoformat()
    return {
        "ok": True,
        "interval_s": _interval_s(),
        "retry_window_h": _retry_window_hours(),
        "max_retry_per_tick": _max_retry_per_tick(),
        "sidecars": docs,
        "recent_events": events,
        "configured": _sidecars(),
    }


# ── Scheduler hook ────────────────────────────────────────────


def register_scheduler(scheduler) -> None:
    """Registra o tick periódico no APScheduler (chamado no leader)."""
    interval = _interval_s()
    scheduler.add_job(
        tick, "interval", seconds=interval,
        id="wa_sidecar_watchdog",
        replace_existing=True, max_instances=1,
        coalesce=True)
    logger.info(
        "[watchdog] registered wa_sidecar_watchdog @ every %ds "
        "(window=%dh, max_retry_per_tick=%d, sidecars=%s)",
        interval, _retry_window_hours(), _max_retry_per_tick(),
        [s["id"] for s in _sidecars()])
