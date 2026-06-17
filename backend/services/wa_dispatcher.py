"""
wa_dispatcher.py — Ponto único de envio de WhatsApp do Presidente IA.
Centraliza para que mocks/feature-flags fiquem aqui (e não espalhados).

CTO 2026-02 (CEO ordem):
    - Dual-provider — Baileys E Evolution API coexistem como rotas
      válidas. O canal ativo (`whatsapp_channels.active=True`) define
      o provider primário; o outro vira FALLBACK automático.
    - Se primário falha (no_session / sidecar offline / 5xx), tenta o
      secundário antes de devolver erro.
    - Selecção do canal: por `company_id` em `whatsapp_channels`.
      Suporta ambos providers em paralelo.

Hardening Fase B (Operação 90%):
    - Circuit breaker em memória por (company_id, provider).
    - Métricas em wa_dispatch_metrics (latência + sucesso/falha + provider).
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
from typing import Any, Dict, Optional

import httpx

from database import db

log = logging.getLogger("wa_dispatcher")


def _baileys_url() -> str:
    """Resolve a URL do sidecar Baileys.

    Ordem (P0 CEO 17/02/2026 — alinhamento com .env real):
      1. BAILEYS_SIDECAR_URL (legacy)
      2. WA_SIDECAR_URL_CH1  (channel-1 default outbound — atual padrão)
      3. WA_SIDECAR_URL      (genérico)
    """
    return (os.environ.get("BAILEYS_SIDECAR_URL")
             or os.environ.get("WA_SIDECAR_URL_CH1")
             or os.environ.get("WA_SIDECAR_URL")
             or "")


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
async def _resolve_channels(company_id: str):
    """Lista canais ativos em ordem de preferência:
    primário (active=True) + secundário do outro provider (active=True).
    Retorna [{provider, channel_doc}, ...]."""
    chans = await db.whatsapp_channels.find(
        {"company_id": company_id, "active": True}, {"_id": 0}
    ).to_list(20)
    if not chans:
        return []
    # Ordena: primário primeiro (preferred=True ou só active=True), depois outros.
    chans.sort(key=lambda c: (
        0 if c.get("preferred") else 1,
        0 if c.get("provider") == "baileys" else 1,
    ))
    out = []
    seen_providers = set()
    for c in chans:
        prov = (c.get("provider") or "baileys").lower()
        if prov in seen_providers:
            continue
        seen_providers.add(prov)
        out.append({"provider": prov, "channel": c})
    return out


async def _send_via_baileys(*, company_id: str, to: str, text: str,
                              start: float, msg_id: str) -> Dict[str, Any]:
    """Caminho Baileys — sidecar local.

    P0 CEO 17/02/2026: gate prioritário é HEALTH do sidecar (state=connected),
    com fallback opcional pra `wa_baileys_sessions` legado.
    """
    url = _baileys_url()
    if not url:
        return {"ok": False, "reason": "BAILEYS_SIDECAR_URL_missing"}
    # Health-check rápido — confirma sidecar `state=connected`
    try:
        async with httpx.AsyncClient(timeout=3.0) as cli:
            h = await cli.get(f"{url}/health")
            health = h.json() if h.status_code == 200 else {}
    except Exception as e:
        return {"ok": False, "reason": f"baileys_health_fail:{str(e)[:80]}"}
    sidecar_state = (health.get("state") or "").lower()
    if sidecar_state != "connected":
        # Fallback de compat — verifica collection legacy de sessões
        sess = await db.wa_baileys_sessions.find_one(
            {"company_id": company_id, "status": "open"})
        if not sess:
            return {"ok": False,
                    "reason": f"baileys_sidecar_state:{sidecar_state or 'unknown'}"}
    try:
        # Inclui token no header (sidecar exige Bearer)
        token = os.environ.get("WA_SIDECAR_TOKEN", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=_timeout_s()) as cli:
            r = await cli.post(
                f"{url}/send",
                json={"company_id": company_id, "to": to,
                       "phone": to,  # alias aceito pelo sidecar
                       "text": text, "id": msg_id},
                headers=headers)
            r.raise_for_status()
            return {"ok": True, "id": msg_id, "provider": "baileys",
                    "latency_ms": int((time.time() - start) * 1000),
                    "response": r.json()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"baileys:{str(e)[:120]}",
                  "provider": "baileys"}


async def _send_via_evolution(*, channel: Dict[str, Any],
                                 to: str, text: str,
                                 start: float, msg_id: str) -> Dict[str, Any]:
    """Caminho Evolution API. Lê config do doc do canal."""
    base_url = channel.get("evolution_url") or os.environ.get("EVOLUTION_URL")
    api_key = (channel.get("evolution_api_key")
                 or os.environ.get("EVOLUTION_API_KEY"))
    instance = (channel.get("evolution_instance")
                  or channel.get("instance_name") or "default")
    basic_auth = (channel.get("evolution_basic_auth")
                    or os.environ.get("EVOLUTION_BASIC_AUTH") or "").strip()
    if not base_url or not api_key:
        return {"ok": False, "reason": "evolution_config_missing",
                  "provider": "evolution"}
    # Normaliza destinatário (digits-only, BR default)
    digits = "".join(c for c in to if c.isdigit())
    if not digits:
        return {"ok": False, "reason": "evolution_invalid_to",
                  "provider": "evolution"}
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    if basic_auth:
        import base64
        token = base64.b64encode(basic_auth.encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    try:
        async with httpx.AsyncClient(timeout=_timeout_s()) as cli:
            r = await cli.post(
                f"{base_url.rstrip('/')}/message/sendText/{instance}",
                headers=headers,
                json={"number": digits, "text": text})
            if r.status_code == 401 and basic_auth:
                return {"ok": False, "provider": "evolution",
                          "reason": "evolution_basic_auth_invalid"}
            if r.status_code == 401:
                return {"ok": False, "provider": "evolution",
                          "reason": "evolution_basic_auth_required"}
            r.raise_for_status()
            return {"ok": True, "id": msg_id, "provider": "evolution",
                    "latency_ms": int((time.time() - start) * 1000),
                    "response": r.json() if r.content else {}}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"evolution:{str(e)[:120]}",
                  "provider": "evolution"}


async def _get_channel_strict(company_id: str, channel: str) -> Optional[Dict[str, Any]]:
    """P0 (CEO 17/02/2026): retorna UM canal específico, ativo.

    Sem fallback, sem lista, sem ranking. Se o canal pedido não existe
    OU está `active=False`, retorna None → caller decide o erro.
    """
    doc = await db.whatsapp_channels.find_one(
        {"company_id": company_id, "provider": channel, "active": True},
        {"_id": 0})
    return doc


async def _resolve_channel_from_conversation(
    company_id: str, to: str,
) -> Optional[str]:
    """Herda canal da última INBOUND do telefone (channel está persistido lá).

    Retorna o nome do provider ("baileys" / "evolution" / "twilio") ou None.
    """
    phone = "".join(c for c in (to or "") if c.isdigit())
    if not phone:
        return None
    inbound = await db.aihub_wa_messages.find_one(
        {"company_id": company_id, "phone": phone, "direction": "inbound",
         "channel": {"$exists": True, "$nin": [None, ""]}},
        {"_id": 0, "channel": 1},
        sort=[("created_at", -1)])
    if not inbound:
        return None
    return (inbound.get("channel") or "").strip().lower() or None


async def send_text(*, company_id: str, to: str, text: str,
                       channel: Optional[str] = None,
                       conversation_id: Optional[str] = None,
                       strict: bool = False) -> Dict[str, Any]:
    """Envia texto.

    P0 — CEO 17/02/2026: roteamento ESTRITO por canal, sem fallback cruzado.

    Ordem de resolução do canal a usar:
      1. `channel` explícito (informado pelo caller) — preferencial.
      2. Herda da última inbound do mesmo telefone (`aihub_wa_messages.channel`).
      3. Se `strict=True` → fail-fast `channel_required`.
      4. Se `strict=False` (default deprecado) → cai em legado `_resolve_channels`
         (preserva compat durante migração; emite log de alerta).

    `conversation_id` reservado para futura evolução (`aihub_conversations`).
    """
    start = time.time()

    # OPERAÇÃO 110% — modo fake: grava em wa_fake_outbox.
    if os.environ.get("SMARTPROV_TRANSPORT_FAKE") == "1":
        msg_id = f"fake-{uuid.uuid4().hex[:12]}"
        try:
            await db.wa_fake_outbox.insert_one({
                "id": msg_id, "company_id": company_id,
                "to": to, "text": text,
                "channel": (channel or "fake"),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass
        await _record_metric(company_id, True,
                              int((time.time() - start) * 1000), "fake_ok")
        return {"ok": True, "id": msg_id, "fake": True,
                "used_provider": channel or "fake"}

    if is_breaker_open(company_id):
        await _record_metric(company_id, False, 0, "breaker_open")
        return {"ok": False, "reason": "breaker_open"}

    msg_id = f"wa-{uuid.uuid4().hex[:12]}"

    # 1. Tenta resolver canal (estritamente)
    resolved_channel = (channel or "").strip().lower() or None
    resolved_source = "explicit" if resolved_channel else None
    if not resolved_channel:
        resolved_channel = await _resolve_channel_from_conversation(
            company_id, to)
        if resolved_channel:
            resolved_source = "inbound_history"

    if resolved_channel:
        # ROTEAMENTO ESTRITO — sem fallback cruzado
        ch_doc = await _get_channel_strict(company_id, resolved_channel)
        if not ch_doc:
            await _record_metric(company_id, False,
                                  int((time.time() - start) * 1000),
                                  f"channel_not_active:{resolved_channel}")
            return {
                "ok": False,
                "reason": f"channel_not_active:{resolved_channel}",
                "requested_channel": resolved_channel,
                "channel_source": resolved_source,
            }
        if resolved_channel == "baileys":
            result = await _send_via_baileys(
                company_id=company_id, to=to, text=text,
                start=start, msg_id=msg_id)
        elif resolved_channel == "evolution":
            result = await _send_via_evolution(
                channel=ch_doc, to=to, text=text,
                start=start, msg_id=msg_id)
        else:
            return {"ok": False,
                    "reason": f"channel_unsupported:{resolved_channel}"}
        if result.get("ok"):
            _record_success(company_id)
        else:
            _record_failure(company_id)
        await _record_metric(company_id, bool(result.get("ok")),
                              int((time.time() - start) * 1000),
                              result.get("reason", f"ok:{resolved_channel}"))
        result["used_provider"] = resolved_channel
        result["channel_source"] = resolved_source
        return result

    # 2. Sem canal resolvido — modo strict explode aqui
    if strict:
        await _record_metric(company_id, False,
                              int((time.time() - start) * 1000),
                              "channel_required_strict")
        return {"ok": False,
                "reason": "channel_required",
                "hint": ("informe channel=... ou garanta que existe inbound "
                          "prévia com channel persistido")}

    # 3. LEGADO — caller antigo sem channel. Loga e usa _resolve_channels.
    # Mantém compat por 1 sprint enquanto callers migram.
    log.warning(
        "[wa_dispatcher] LEGACY_PATH cid=%s to=%s — caller não informou "
        "channel e não há inbound prévia. Migrar para passar channel "
        "explícito (P0 CEO 17/02/2026).", company_id, to)
    routes = await _resolve_channels(company_id)

    # Compat — se não há canal configurado mas há sessão Baileys + env URL,
    # usa caminho legado (não quebra clientes antigos)
    if not routes:
        legacy = await _send_via_baileys(company_id=company_id, to=to,
                                          text=text, start=start,
                                          msg_id=msg_id)
        if legacy["ok"]:
            _record_success(company_id)
        else:
            _record_failure(company_id)
        await _record_metric(company_id, legacy["ok"],
                              int((time.time() - start) * 1000),
                              legacy.get("reason", ""))
        legacy["legacy_path"] = True
        return legacy

    last_error: Dict[str, Any] = {}
    for route in routes:
        if route["provider"] == "evolution":
            result = await _send_via_evolution(
                channel=route["channel"], to=to, text=text,
                start=start, msg_id=msg_id)
        else:
            result = await _send_via_baileys(
                company_id=company_id, to=to, text=text,
                start=start, msg_id=msg_id)
        if result["ok"]:
            _record_success(company_id)
            await _record_metric(company_id, True,
                                  int((time.time() - start) * 1000),
                                  f"ok:{route['provider']}")
            result["used_provider"] = route["provider"]
            result["legacy_path"] = True
            return result
        last_error = result
        log.info("[wa_dispatcher] %s falhou (%s), tentando próximo",
                  route["provider"], result.get("reason"))

    _record_failure(company_id)
    latency = int((time.time() - start) * 1000)
    await _record_metric(company_id, False, latency,
                          last_error.get("reason", "all_routes_failed"))
    last_error["latency_ms"] = latency
    last_error["routes_tried"] = [r["provider"] for r in routes]
    last_error["legacy_path"] = True
    return last_error


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
