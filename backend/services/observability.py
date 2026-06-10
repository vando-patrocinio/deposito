"""OBSERVABILITY METRICS — middleware + persistência.

Captura latência, throughput e erros das requisições HTTP em
`http_metrics`. Reduz cardinalidade via path-normalization.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from database import db

log = logging.getLogger("ponto.observability")

# Normaliza path: substitui IDs por placeholders
_ID_PATTERNS = [
    (re.compile(r"/(opp|out|exp|inc|incnotify|sub|tk|dec|pol|audit|"
                  "rt|ulhist|sal)-[a-z0-9-]+"), r"/\1-{id}"),
    (re.compile(r"/[a-f0-9]{24}"), "/{oid}"),  # ObjectId
    (re.compile(r"/[a-f0-9-]{32,}"), "/{uuid}"),
]


def normalize_path(path: str) -> str:
    for rx, repl in _ID_PATTERNS:
        path = rx.sub(repl, path)
    return path


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        t0 = time.time()
        status = 500
        err = None
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        except Exception as e:
            err = type(e).__name__
            raise
        finally:
            elapsed_ms = round((time.time() - t0) * 1000, 1)
            path = normalize_path(request.url.path)
            # Apenas /api/* + ignora streams
            if path.startswith("/api/") and not path.endswith("/stream"):
                # fire-and-forget (não bloqueia a resposta)
                asyncio.create_task(_persist({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "method": request.method,
                    "path": path,
                    "status": status,
                    "elapsed_ms": elapsed_ms,
                    "error": err,
                }))


async def _persist(doc: Dict[str, Any]) -> None:
    try:
        await db.http_metrics.insert_one(doc)
    except Exception:
        pass


async def ensure_indexes() -> None:
    try:
        await db.http_metrics.create_index([("path", 1), ("ts", -1)])
        await db.http_metrics.create_index([("ts", -1)])
        # TTL 30 dias
        await db.http_metrics.create_index(
            "ts", expireAfterSeconds=30 * 86400,
            name="http_metrics_ttl_raw")
    except Exception as e:
        log.warning("[obs] indexes: %s", e)


async def aggregate_window(minutes: int = 60) -> Dict[str, Any]:
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc)
              - timedelta(minutes=minutes)).isoformat()
    pipe = [
        {"$match": {"ts": {"$gte": cutoff}}},
        {"$group": {
            "_id": "$path",
            "n": {"$sum": 1},
            "avg_ms": {"$avg": "$elapsed_ms"},
            "p95_ms": {"$max": "$elapsed_ms"},  # aproximação
            "errors": {"$sum": {"$cond": [
                {"$gte": ["$status", 500]}, 1, 0]}},
            "client_errors": {"$sum": {"$cond": [
                {"$and": [{"$gte": ["$status", 400]},
                            {"$lt": ["$status", 500]}]}, 1, 0]}},
        }},
        {"$sort": {"n": -1}},
        {"$limit": 100},
    ]
    rows = await db.http_metrics.aggregate(pipe).to_list(100)
    total = sum(r["n"] for r in rows)
    err = sum(r["errors"] for r in rows)
    return {
        "window_minutes": minutes,
        "total_requests": total,
        "error_rate": round(err / max(total, 1), 4),
        "top_paths": [{"path": r["_id"],
                         "n": r["n"],
                         "avg_ms": round(r["avg_ms"], 1),
                         "p95_ms": round(r["p95_ms"], 1),
                         "errors_5xx": r["errors"],
                         "client_errors_4xx": r["client_errors"]}
                        for r in rows],
    }
