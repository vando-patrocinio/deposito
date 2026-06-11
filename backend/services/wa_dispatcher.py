"""
wa_dispatcher.py — Ponto único de envio de WhatsApp do Presidente IA.
Centraliza para que mocks/feature-flags fiquem aqui (e não espalhados).

Hardening Fase B (Operação 90%):
    - Circuit breaker em memória por (company_id) — trava após N falhas
      consecutivas, libera após cooldown.
    - Métricas em wa_dispatch_metrics (latência + sucesso/falha).
    - Timeout configurável via env (default 10s).
    - Backoff exponencial com jitter implícito via tentativa única
      (workers externos podem reagendar).

Em produção:
    - Procura sessão Baileys ativa em `wa_baileys_sessions` (company_id).
    - Chama o sidecar HTTP do Baileys (BAILEYS_SIDECAR_URL) com payload
      JSON {to, text}.
    - Em ausência da sessão, retorna {ok:false, reason:"no_session"}.
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
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import httpx

from database import db

log = logging.getLogger("wa_dispatcher")


def _baileys_url() -> str:
    return os.environ.get("BAILEYS_SIDECAR_URL", "")


def _timeout_s() -> float:
    try:
        return float(os.environ.get("WA_SEND_TIMEOUT_S") or 10.0)
    except (TypeError, ValueError):
        return 10.0


def _breaker_threshold() -> int:
    try:
        return int(os.environ.get("WA_BREAKER_THRESHOLD") or 5)
    except (TypeError, ValueError):
        return 5


def _breaker_cooldown_s() -> float:
    try:
        return float(os.environ.get("WA_BREAKER_COOLDOWN_S") or 120.0)
    except (TypeError, ValueError):
        return 120.0


# ── Circuit breaker em memória ────────────────────────────────
# {company_id: {"fails": int, "open_until": epoch_seconds|None}}
_breaker: Dict[str, Dict[str, Any]] = {}


def _breaker_state(company_id: str) -> Dict[str, Any]:
    st = _breaker.setdefault(company_id, {"fails": 0, "open_until": None})
    if st["open_until"] and time.time() >= st["open_until"]:
        # cooldown expirou — meio-aberto
        st["open_until"] = None
        st["fails"] = 0
    return st


def _record_failure(company_id: str) -> None:
    st = _breaker_state(company_id)
    st["fails"] += 1
    if st["fails"] >= _breaker_threshold():
        st["open_until"] = time.time() + _breaker_cooldown_s()
        log.warning("[wa_dispatcher] BREAKER ABERTO co=%s por %.0fs",
                     company_id, _breaker_cooldown_s())


def _record_success(company_id: str) -> None:
    st = _breaker_state(company_id)
    st["fails"] = 0
    st["open_until"] = None


def is_breaker_open(company_id: str) -> bool:
    st = _breaker_state(company_id)
    return st["open_until"] is not None


def breaker_status() -> Dict[str, Any]:
    """Para painel/diagnóstico."""
    now = time.time()
    out = []
    for cid, st in _breaker.items():
        out.append({
            "company_id": cid,
            "fails": st["fails"],
            "open": st["open_until"] is not None,
            "reopens_in_s": (max(0, int(st["open_until"] - now))
                              if st["open_until"] else 0),
        })
    return {"threshold": _breaker_threshold(),
              "cooldown_s": _breaker_cooldown_s(),
              "tenants": out}


# ── Métrica persistida ────────────────────────────────────────
async def _record_metric(company_id: str, ok: bool, latency_ms: int,
                              reason: str = "") -> None:
    try:
        await db.wa_dispatch_metrics.insert_one({
            "company_id": company_id,
            "ok": ok,
            "latency_ms": latency_ms,
            "reason": reason,
            "ts": datetime.now(timezone.utc),
        })
    except Exception:  # noqa: BLE001
        pass  # métrica nunca trava envio


# ── Envio ─────────────────────────────────────────────────────
async def send_text(*, company_id: str, to: str,
                       text: str) -> Dict[str, Any]:
    """Envia texto via Baileys. Retorna {ok, id|reason}."""
    start = time.time()

    # OPERAÇÃO 110% — modo fake: grava em wa_fake_outbox.
    if os.environ.get("SMARTPROV_TRANSPORT_FAKE") == "1":
        msg_id = f"fake-{uuid.uuid4().hex[:12]}"
        try:
            await db.wa_fake_outbox.insert_one({
                "id": msg_id, "company_id": company_id,
                "to": to, "text": text,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass
        await _record_metric(company_id, True,
                              int((time.time() - start) * 1000), "fake_ok")
        return {"ok": True, "id": msg_id, "fake": True}

    if is_breaker_open(company_id):
        await _record_metric(company_id, False, 0, "breaker_open")
        return {"ok": False, "reason": "breaker_open"}

    sess = await db.wa_baileys_sessions.find_one(
        {"company_id": company_id, "status": "open"})
    if not sess:
        await _record_metric(company_id, False, 0, "no_session")
        return {"ok": False, "reason": "no_session"}

    url = _baileys_url()
    if not url:
        await _record_metric(company_id, False, 0,
                                "BAILEYS_SIDECAR_URL_missing")
        return {"ok": False, "reason": "BAILEYS_SIDECAR_URL_missing"}

    msg_id = f"wa-{uuid.uuid4().hex[:12]}"
    try:
        async with httpx.AsyncClient(timeout=_timeout_s()) as cli:
            r = await cli.post(
                f"{url}/send",
                json={"company_id": company_id, "to": to,
                       "text": text, "id": msg_id})
            r.raise_for_status()
            latency = int((time.time() - start) * 1000)
            _record_success(company_id)
            await _record_metric(company_id, True, latency)
            return {"ok": True, "id": msg_id,
                      "latency_ms": latency,
                      "response": r.json()}
    except Exception as e:  # noqa: BLE001
        latency = int((time.time() - start) * 1000)
        _record_failure(company_id)
        await _record_metric(company_id, False, latency, repr(e)[:200])
        log.warning("[wa_dispatcher] falha co=%s: %s", company_id, e)
        return {"ok": False, "reason": str(e),
                  "latency_ms": latency}


async def metrics_summary(company_id: str = None,
                                hours: int = 24) -> Dict[str, Any]:
    """Agregado das últimas N horas para painel."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    match: Dict[str, Any] = {"ts": {"$gte": cutoff}}
    if company_id:
        match["company_id"] = company_id
    pipe = [
        {"$match": match},
        {"$group": {"_id": "$ok",
                       "n": {"$sum": 1},
                       "lat_avg": {"$avg": "$latency_ms"},
                       "lat_max": {"$max": "$latency_ms"}}},
    ]
    rows = await db.wa_dispatch_metrics.aggregate(pipe).to_list(10)
    total = sum(r["n"] for r in rows)
    ok = sum(r["n"] for r in rows if r["_id"])
    lat_rows = [r for r in rows if r["_id"]]
    return {
        "hours": hours,
        "company_id": company_id,
        "total": total,
        "ok": ok,
        "fail": total - ok,
        "success_pct": round(ok / total * 100, 1) if total else 0.0,
        "latency_ms_avg": (round(lat_rows[0]["lat_avg"], 1)
                            if lat_rows else 0),
        "latency_ms_max": lat_rows[0]["lat_max"] if lat_rows else 0,
        "breaker": breaker_status(),
    }
