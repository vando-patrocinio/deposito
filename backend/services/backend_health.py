"""
backend_health.py — Sprint 6 / iter225
Painel de saúde técnica do backend (CTO/SRE).

Coleta métricas em-memória (ring-buffer) via middleware:
  - latência por rota (p50/p95/avg/max)
  - status code distribution
  - 5xx error rate

Health-check de serviços externos:
  - MongoDB ping
  - OpenRouter (emergent llm key) — só checa env
  - WhatsApp Baileys sidecar
  - Asaas (env keys + ping leve)

Detecta índices faltantes em coleções "quentes".
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

# ─────────────────── Ring buffer global ───────────────────
# (path, status, latency_ms, ts_epoch)
_MAX_SAMPLES = int(os.environ.get("HEALTH_RING_SIZE", "5000") or 5000)
_RING: Deque[Tuple[str, int, float, float]] = deque(maxlen=_MAX_SAMPLES)


def record_request(path: str, status: int, latency_ms: float) -> None:
    """Chamado pelo middleware ao final de cada request."""
    try:
        _RING.append((path, status, latency_ms, time.time()))
    except Exception:
        pass


def _bucket_path(path: str) -> str:
    """Agrupa por prefixo de 2 segmentos.  /api/foo/123 -> /api/foo"""
    parts = path.split("/", 3)
    return "/" + "/".join(parts[1:3]) if len(parts) >= 3 else path


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = max(0, min(len(values) - 1, int(round((p / 100) * (len(values) - 1)))))
    return values[k]


# ─────────────────── Snapshot ───────────────────
def latency_snapshot(window_seconds: int = 3600) -> Dict[str, Any]:
    """Devolve estatísticas da janela móvel."""
    cutoff = time.time() - window_seconds
    by_route: Dict[str, List[float]] = {}
    status_dist: Dict[str, int] = {}
    total = 0
    err_5xx = 0
    err_4xx = 0
    for (path, status, latency, ts) in list(_RING):
        if ts < cutoff:
            continue
        total += 1
        if status >= 500:
            err_5xx += 1
        elif status >= 400:
            err_4xx += 1
        bucket = _bucket_path(path)
        by_route.setdefault(bucket, []).append(latency)
        sk = f"{(status // 100)}xx"
        status_dist[sk] = status_dist.get(sk, 0) + 1

    per_route = []
    for r, lats in by_route.items():
        per_route.append({
            "route": r,
            "count": len(lats),
            "avg_ms": round(sum(lats) / len(lats), 1),
            "p50_ms": round(_percentile(lats, 50), 1),
            "p95_ms": round(_percentile(lats, 95), 1),
            "max_ms": round(max(lats), 1),
        })
    # ordena por p95 desc
    per_route.sort(key=lambda x: -x["p95_ms"])

    return {
        "window_seconds": window_seconds,
        "total_requests": total,
        "err_5xx": err_5xx,
        "err_4xx": err_4xx,
        "err_rate_pct": (round(100.0 * (err_5xx + err_4xx) / total, 2)
                            if total else 0.0),
        "status_distribution": status_dist,
        "top_slowest": per_route[:10],
        "per_route_full": per_route,
    }


# ─────────────────── Services check ───────────────────
async def check_mongo() -> Dict[str, Any]:
    t0 = time.time()
    try:
        from database import mongo_client
        await mongo_client.admin.command("ping")
        return {"name": "MongoDB", "ok": True,
                "latency_ms": round((time.time() - t0) * 1000, 1)}
    except Exception as e:
        return {"name": "MongoDB", "ok": False, "error": str(e)[:120]}


def check_openrouter_env() -> Dict[str, Any]:
    key = os.environ.get("EMERGENT_LLM_KEY") or os.environ.get(
        "OPENROUTER_API_KEY")
    return {"name": "OpenRouter (LLM)", "ok": bool(key),
            "hint": "EMERGENT_LLM_KEY ausente" if not key else None}


def check_baileys_env() -> Dict[str, Any]:
    url = os.environ.get("BAILEYS_SIDECAR_URL")
    return {"name": "WhatsApp Baileys", "ok": bool(url),
            "hint": "BAILEYS_SIDECAR_URL ausente" if not url else None}


def check_asaas_env() -> Dict[str, Any]:
    has = bool(os.environ.get("ASAAS_API_KEY"))
    return {"name": "Asaas", "ok": has,
            "hint": "ASAAS_API_KEY ausente — mock mode" if not has else None}


def check_stripe_env() -> Dict[str, Any]:
    has = bool(os.environ.get("STRIPE_API_KEY"))
    return {"name": "Stripe", "ok": has,
            "hint": "STRIPE_API_KEY ausente" if not has else None}


async def all_services() -> List[Dict[str, Any]]:
    mongo = await check_mongo()
    return [
        mongo,
        check_openrouter_env(),
        check_baileys_env(),
        check_asaas_env(),
        check_stripe_env(),
    ]


# ─────────────────── Index hints ───────────────────
HOT_COLLECTIONS = [
    ("subscribers", ["company_id", "phone", "cpf"]),
    ("audit_log", ["created_at", "category", "criticality", "user_id"]),
    ("motor_ia_events", ["created_at", "type", "consumed"]),
    ("tickets", ["company_id", "status", "subscriber_id"]),
    ("financeiro_movs", ["company_id", "due_date", "status"]),
    ("clock_records", ["company_id", "user_id", "date"]),
]


async def index_hints() -> List[Dict[str, Any]]:
    """Lista coleções "quentes" sem índices recomendados."""
    out: List[Dict[str, Any]] = []
    try:
        from database import db
        for col_name, recommended in HOT_COLLECTIONS:
            try:
                idx_info = await db[col_name].index_information()
            except Exception:
                continue
            indexed_fields = set()
            for _, spec in idx_info.items():
                for f, _ in spec.get("key", []):
                    indexed_fields.add(f)
            missing = [f for f in recommended if f not in indexed_fields]
            if missing:
                out.append({
                    "collection": col_name,
                    "missing_index_on": missing,
                    "current_indexes": len(idx_info),
                })
    except Exception:
        pass
    return out


# ─────────────────── Coleções "infláveis" ───────────────────
INFLATABLE_COLLECTIONS = [
    "audit_log", "motor_ia_events", "wa_inbound_log",
    "client_errors", "events_stream",
]


async def collection_sizes() -> List[Dict[str, Any]]:
    """Devolve tamanho das coleções que mais crescem."""
    out: List[Dict[str, Any]] = []
    try:
        from database import db
        for name in INFLATABLE_COLLECTIONS:
            try:
                n = await db[name].estimated_document_count()
                out.append({"collection": name, "docs": n})
            except Exception:
                continue
    except Exception:
        pass
    out.sort(key=lambda x: -x["docs"])
    return out


# ─────────────────── Snapshot completo ───────────────────
async def deep_health(window_seconds: int = 3600) -> Dict[str, Any]:
    lat = latency_snapshot(window_seconds)
    services = await all_services()
    services_ok = all(s.get("ok") for s in services)
    hot_idx = await index_hints()
    coll_sizes = await collection_sizes()

    # Status global
    if lat["err_5xx"] > 10 or not services_ok:
        status = "critico"
    elif lat["err_5xx"] > 0 or lat["err_rate_pct"] > 5 or hot_idx:
        status = "atencao"
    else:
        status = "saudavel"

    return {
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latency": lat,
        "services": services,
        "index_hints": hot_idx,
        "collection_sizes": coll_sizes,
        "ring_capacity": _MAX_SAMPLES,
        "ring_used": len(_RING),
    }
