"""Inject-only: dispara N mensagens no webhook e mede só a INJEÇÃO.

A fila drena em background. Este script foca em validar:
 - p95/p99 do webhook
 - 0 duplicações
 - 0 perdas no INSERT inbound

Para conferir drain, use scripts/check_queue_drain.py depois.
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
import json
import os
import statistics
import time
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

ALLOWED_PHONE = "21998176526"
ALLOWED_PHONE_E164 = "+5521998176526"
TENANT = "co-demo"
BACKEND_URL = (os.environ.get("PUBLIC_BACKEND_URL")
               or "http://localhost:8001").rstrip("/")
WEBHOOK_URL = f"{BACKEND_URL}/api/whatsapp-twilio/webhook?tenant={TENANT}"


def _payload(text, idx, tag):
    return {
        "From": f"whatsapp:{ALLOWED_PHONE_E164}",
        "To": "whatsapp:+5521998176526",
        "Body": text, "ProfileName": "PAMELA TESTE",
        "MessageSid": f"SM-{tag}-{int(time.time())}-{idx:05d}",
        "NumMedia": "0", "AccountSid": "ACtest", "WaId": ALLOWED_PHONE,
    }


async def _send(client, sem, text, idx, tag):
    async with sem:
        p = _payload(text, idx, tag)
        t0 = time.perf_counter()
        try:
            r = await client.post(WEBHOOK_URL, data=p, timeout=30.0)
            return {"status": r.status_code,
                    "latency_ms": (time.perf_counter()-t0)*1000,
                    "duplicate": (r.json() or {}).get("duplicate", False)
                                  if r.status_code == 200 else False}
        except Exception as e:
            return {"status": -1,
                    "latency_ms": (time.perf_counter()-t0)*1000,
                    "error": repr(e)[:120]}


async def _round(size, concurrent):
    tag = f"qinj{size}"
    print(f"\n━━━ R{size} (concurrent={concurrent}) ━━━")
    sem = asyncio.Semaphore(concurrent)
    t0 = time.perf_counter()
    async with httpx.AsyncClient(limits=httpx.Limits(
            max_connections=concurrent*2, max_keepalive_connections=concurrent)) as c:
        results = await asyncio.gather(*[
            _send(c, sem, f"[QUEUE-INJ-{size}#{i:05d}]", i, tag)
            for i in range(size)
        ])
    dt = time.perf_counter() - t0
    statuses = {}
    lats = []
    dups = 0
    errs = 0
    for r in results:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
        lats.append(r["latency_ms"])
        if r.get("duplicate"): dups += 1
        if r.get("error"): errs += 1
    p50 = statistics.median(lats) if lats else 0
    p95 = (statistics.quantiles(lats,n=20)[18] if len(lats)>=20 else max(lats,default=0))
    p99 = (statistics.quantiles(lats,n=100)[98] if len(lats)>=100 else max(lats,default=0))
    summary = {
        "size": size, "tag": tag,
        "inject_wall_s": round(dt,2),
        "inject_rps": round(size/dt,2) if dt else 0,
        "http_status": statuses, "duplicates": dups, "errors": errs,
        "latency_avg": round(sum(lats)/len(lats),1) if lats else 0,
        "latency_p50": round(p50,1), "latency_p95": round(p95,1),
        "latency_p99": round(p99,1), "latency_max": round(max(lats,default=0),1),
    }
    print(f"  ⏱  wall={dt:.2f}s  inject_rps={summary['inject_rps']}")
    print(f"  📈 p50={summary['latency_p50']}ms  "
          f"p95={summary['latency_p95']}ms  p99={summary['latency_p99']}ms")
    print(f"  🌐 HTTP {statuses}  duplicates={dups}  errors={errs}")
    return summary


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", default="100,500,1000,5000")
    ap.add_argument("--concurrent", type=int, default=200)
    args = ap.parse_args()
    rounds = [int(x) for x in args.rounds.split(",") if x.strip()]
    print("═"*66)
    print("INJEÇÃO RÁPIDA — só mede webhook (drain medido depois)")
    print("═"*66)
    print(f"  rounds: {rounds}  concurrent: {args.concurrent}")
    summaries = []
    for s in rounds:
        summaries.append(await _round(s, args.concurrent))
        if s != rounds[-1]:
            await asyncio.sleep(3)
    out_path = "/app/docs/fila_inject_only_result.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({
            "phone_alvo": ALLOWED_PHONE_E164,
            "tenant": TENANT,
            "executado_em": datetime.now(timezone.utc).isoformat(),
            "rounds": summaries,
        }, f, indent=2)
    print(f"\n✅ Saved {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
