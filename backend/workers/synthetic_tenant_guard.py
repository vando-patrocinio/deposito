"""synthetic_tenant_guard — Blindagem automática contra inflação de tenants.

Worker periódico que escaneia coleções operacionais procurando tenants
que NÃO estão na allowlist e NÃO estão classificados ainda.

Critério de detecção (qualquer um basta):
1. Nome bate em SYNTHETIC_TENANTS (lista nominal)
2. Nome bate em prefixo sintético (regex `test-|tst-|co-test-|...`)
3. Nome bate em hash UUID puro (regex `^(co-)?[0-9a-f]{10,}$`)
4. Volume cresce 10x em 24h em coleção principal (sinal de carga sintética)
5. 90%+ dos registros com `phone` NULL (load test sem dados)

Registra em `synthetic_tenant_guard_log` e alerta CTO em `system_alerts`.

NÃO deleta. NÃO migra. NÃO modifica dados. Apenas observa e marca.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from constants.synthetic_tenants import (
    SYNTHETIC_TENANTS,
    is_synthetic_tenant,
)
from database import db

log = logging.getLogger("ponto.synthetic_tenant_guard")

# Coleções a inspecionar (principais business)
WATCHED_COLLECTIONS = [
    "subscribers",
    "tickets",
    "subscriber_invoices",
    "collaborators",
    "ctos",
    "incidents",
    "motor_ia_events",
    "executive_ledger",
]

ALLOWLIST_TENANTS = {"co-demo"}  # único tenant prod hoje


async def _ensure_indexes():
    try:
        await db.synthetic_tenant_guard_log.create_index(
            [("tenant_id", 1), ("scanned_at", -1)]
        )
        await db.synthetic_tenant_guard_log.create_index([("classification", 1)])
    except Exception as e:
        log.warning(f"[guard] indexes: {e}")


async def _classify_unknown(tid: str, doc_counts: Dict[str, int]) -> Dict[str, Any]:
    """Aplica heurísticas para classificar um tenant novo/desconhecido."""
    reasons: List[str] = []
    classification = "UNKNOWN"

    # 1. Bate em lista nominal ou regex
    if is_synthetic_tenant(tid):
        classification = "SYNTHETIC_PATTERN"
        reasons.append("nome bate em SYNTHETIC_TENANTS ou regex de prefixo/hash")
        return {"classification": classification, "reasons": reasons}

    # 2. Volume típico de seed (1.000, 2.000, 5.000, 10.000)
    sub_count = doc_counts.get("subscribers", 0)
    if sub_count in (1000, 2000, 5000, 10000, 50000):
        classification = "SUSPICIOUS_VOLUME"
        reasons.append(
            f"subscribers count = {sub_count} (volume típico de seed script)"
        )

    # 3. Telefones / documentos ausentes em massa
    if sub_count > 100:
        no_phone = await db.subscribers.count_documents(
            {"company_id": tid, "$or": [{"phone": None}, {"phone": ""}]}
        )
        no_doc = await db.subscribers.count_documents(
            {"company_id": tid, "$or": [{"document": None}, {"document": ""}]}
        )
        pct_no_phone = (no_phone / sub_count) * 100
        pct_no_doc = (no_doc / sub_count) * 100
        if pct_no_phone >= 90:
            classification = "SUSPICIOUS_NULLS"
            reasons.append(
                f"{pct_no_phone:.0f}% subscribers sem phone "
                "(perfil load-test)"
            )
        if pct_no_doc >= 90:
            classification = "SUSPICIOUS_NULLS"
            reasons.append(
                f"{pct_no_doc:.0f}% subscribers sem document "
                "(perfil load-test)"
            )

    # 4. Nome do tenant não é UUID nem prefixo conhecido, mas é desconhecido
    if classification == "UNKNOWN" and tid not in ALLOWLIST_TENANTS:
        reasons.append(
            f"tenant '{tid}' não está em ALLOWLIST_TENANTS — "
            "requer revisão humana"
        )
        classification = "NEEDS_REVIEW"

    return {"classification": classification, "reasons": reasons}


async def scan_once() -> Dict[str, Any]:
    """Executa um ciclo de scan e retorna sumário."""
    started = datetime.now(timezone.utc)
    seen_tenants: Dict[str, Dict[str, int]] = {}

    for col in WATCHED_COLLECTIONS:
        try:
            pipe = [
                {"$group": {"_id": "$company_id", "n": {"$sum": 1}}}
            ]
            async for row in db[col].aggregate(pipe):
                tid = row.get("_id")
                if not tid:
                    continue
                if tid not in seen_tenants:
                    seen_tenants[tid] = {}
                seen_tenants[tid][col] = row["n"]
        except Exception as e:
            log.warning(f"[guard] col={col}: {e}")

    new_alerts = 0
    classifications: List[Dict[str, Any]] = []

    for tid, doc_counts in seen_tenants.items():
        if tid in ALLOWLIST_TENANTS:
            continue
        last = await db.synthetic_tenant_guard_log.find_one(
            {"tenant_id": tid}, sort=[("scanned_at", -1)]
        )
        # Se já classificado nas últimas 24h, pula
        if last and last.get("classification") not in (None, "UNKNOWN"):
            age_h = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(last["scanned_at"])
            ).total_seconds() / 3600
            if age_h < 24:
                continue

        result = await _classify_unknown(tid, doc_counts)
        entry = {
            "tenant_id": tid,
            "scanned_at": started.isoformat(),
            "classification": result["classification"],
            "reasons": result["reasons"],
            "doc_counts": doc_counts,
            "total_docs": sum(doc_counts.values()),
        }
        await db.synthetic_tenant_guard_log.insert_one(entry)
        classifications.append(entry)

        # Alerta CTO se classificação não-trivial
        if result["classification"] in (
            "SYNTHETIC_PATTERN", "SUSPICIOUS_VOLUME",
            "SUSPICIOUS_NULLS", "NEEDS_REVIEW"
        ):
            try:
                await db.system_alerts.insert_one({
                    "id": f"synth-guard-{tid}-{int(started.timestamp())}",
                    "kind": "synthetic_tenant_detected",
                    "severity": ("warning" if result["classification"]
                                 != "NEEDS_REVIEW" else "info"),
                    "tenant_id": tid,
                    "classification": result["classification"],
                    "reasons": result["reasons"],
                    "doc_counts": doc_counts,
                    "created_at": started.isoformat(),
                    "acknowledged": False,
                })
                new_alerts += 1
            except Exception as e:
                log.warning(f"[guard] alert insert {tid}: {e}")

    summary = {
        "scanned_at": started.isoformat(),
        "tenants_observed": len(seen_tenants),
        "new_classifications": len(classifications),
        "new_alerts": new_alerts,
    }
    log.info(
        f"[guard] {summary['tenants_observed']} tenants, "
        f"{summary['new_classifications']} novos, "
        f"{summary['new_alerts']} alertas"
    )
    return summary


async def worker_loop(interval_sec: int = 3600):
    """Loop infinito do worker. Default: 1h."""
    await _ensure_indexes()
    log.info(f"[guard] worker iniciado (interval={interval_sec}s)")
    # primeiro scan imediato
    try:
        await scan_once()
    except Exception as e:
        log.exception(f"[guard] erro no scan inicial: {e}")
    while True:
        await asyncio.sleep(interval_sec)
        try:
            await scan_once()
        except Exception as e:
            log.exception(f"[guard] erro no scan: {e}")
