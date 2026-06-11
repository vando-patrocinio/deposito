"""
load_test.py — Sprint 22
Teste de carga do Sistema Nervoso. Mede throughput real e identifica
gargalo.

Uso:
    cd /app/backend && python scripts/load_test.py --events 5000 --concurrency 50
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "low",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import argparse
import asyncio
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def emit_burst(count: int, concurrency: int):
    """Emite N eventos com pool de workers."""
    from services.event_bus import emit_event, EventType
    semaphore = asyncio.Semaphore(concurrency)
    company = f"load-test-{uuid.uuid4().hex[:6]}"

    async def one(i):
        async with semaphore:
            await emit_event(
                EventType.CLIENT_OFFLINE,
                company_id=company, source="load_test",
                severity="alta",
                payload={"cto_id": f"CTO-{i % 50}",
                         "subscriber_id": f"sub-{i}"})

    t0 = time.time()
    await asyncio.gather(*[one(i) for i in range(count)])
    elapsed = time.time() - t0
    return {"count": count, "elapsed_s": round(elapsed, 3),
            "throughput_per_sec": round(count / elapsed, 1),
            "company_id": company}


async def measure_decision_cycle(company_id: str):
    from services.decision_engine import run_decision_cycle
    t0 = time.time()
    out = await run_decision_cycle()
    return {"elapsed_ms": int((time.time() - t0) * 1000), **out}


async def measure_action_engine(company_id: str):
    from services.action_engine import execute_pending
    t0 = time.time()
    out = await execute_pending()
    return {"elapsed_ms": int((time.time() - t0) * 1000), **out}


async def cleanup(company_id: str):
    from database import db
    for c in ("motor_ia_events", "motor_ia_decisions",
                "motor_ia_actions", "motor_ia_outcomes",
                "incidents", "loyalty_opportunities"):
        await db[c].delete_many({"company_id": company_id})


async def main(events: int, concurrency: int):
    burst = await emit_burst(events, concurrency)
    print(f"[emit] {events} events em {burst['elapsed_s']}s  "
          f"= {burst['throughput_per_sec']} ev/s")
    dec = await measure_decision_cycle(burst["company_id"])
    print(f"[decision_cycle] {dec['elapsed_ms']}ms "
          f"({dec['events_processed']} processados → "
          f"{dec['decisions_created']} decisões)")
    act = await measure_action_engine(burst["company_id"])
    print(f"[action_engine] {act['elapsed_ms']}ms "
          f"({act['executed']} executadas)")
    total_ms = burst["elapsed_s"] * 1000 + dec["elapsed_ms"] \
        + act["elapsed_ms"]
    print(f"[pipeline_total] {int(total_ms)}ms "
          f"→ throughput ponta-a-ponta = "
          f"{int(events / (total_ms / 1000))} ev/s")
    await cleanup(burst["company_id"])
    print("[cleanup] ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", type=int, default=2000)
    ap.add_argument("--concurrency", type=int, default=50)
    args = ap.parse_args()
    asyncio.run(main(args.events, args.concurrency))
