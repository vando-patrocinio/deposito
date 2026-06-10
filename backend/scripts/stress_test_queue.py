"""Stress test enterprise — usa isabella_queue para medir capacidade real.

Mede em cada rodada:
  - Latência do webhook (deve ser <100ms p95, <250ms p99)
  - Tempo para processar TODA a fila
  - Mensagens persistidas, perdidas, duplicadas
  - Throughput de injeção e de processamento

Uso: python3 scripts/stress_test_queue.py --rounds 100,500,1000,5000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

ALLOWED_PHONE = "21998176526"
ALLOWED_PHONE_E164 = "+5521998176526"
TENANT = "co-demo"
SUBSCRIBER_ID = "sub-89c314c0d98f"

BACKEND_URL = (os.environ.get("PUBLIC_BACKEND_URL")
               or "http://localhost:8001").rstrip("/")
WEBHOOK_URL = f"{BACKEND_URL}/api/whatsapp-twilio/webhook?tenant={TENANT}"


def _payload(text: str, idx: int, round_tag: str) -> Dict[str, str]:
    return {
        "From": f"whatsapp:{ALLOWED_PHONE_E164}",
        "To": "whatsapp:+5521998176526",
        "Body": text,
        "ProfileName": "PAMELA TESTE",
        "MessageSid": f"SM-{round_tag}-{int(time.time())}-{idx:05d}",
        "NumMedia": "0", "AccountSid": "ACtest", "WaId": ALLOWED_PHONE,
    }


async def _send(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                text: str, idx: int, round_tag: str) -> Dict[str, Any]:
    async with sem:
        payload = _payload(text, idx, round_tag)
        t0 = time.perf_counter()
        try:
            r = await client.post(WEBHOOK_URL, data=payload, timeout=30.0)
            dt = (time.perf_counter() - t0) * 1000
            return {"idx": idx, "status": r.status_code,
                    "latency_ms": round(dt, 1),
                    "sid": payload["MessageSid"],
                    "duplicate": (r.json() or {}).get("duplicate", False) if r.status_code == 200 else False}
        except Exception as e:  # noqa: BLE001
            dt = (time.perf_counter() - t0) * 1000
            return {"idx": idx, "status": -1, "latency_ms": round(dt, 1),
                    "sid": payload["MessageSid"], "error": repr(e)[:160]}


async def _wait_queue_drain(db, round_tag: str, expected: int,
                            timeout_s: float = 600.0) -> Dict[str, Any]:
    """Aguarda até a fila terminar todos os jobs deste round (status=done|failed)."""
    deadline = time.time() + timeout_s
    last_progress = time.time()
    last_done = -1
    while time.time() < deadline:
        agg = await db.isabella_queue.aggregate([
            {"$match": {"message_sid": {"$regex": f"^SM-{round_tag}-"}}},
            {"$group": {"_id": "$status", "n": {"$sum": 1}}},
        ]).to_list(20)
        counts = {r["_id"]: r["n"] for r in agg}
        done = counts.get("done", 0) + counts.get("failed", 0)
        if done > last_done:
            last_progress = time.time()
            last_done = done
        if done >= expected:
            return counts
        # 180s sem progresso → considera stuck
        if time.time() - last_progress > 180:
            print(f"  ⚠️ fila sem progresso há 180s — done={done}/{expected}")
            return counts
        await asyncio.sleep(2.0)
    return {"timeout": True}


async def _count_db(db, round_tag: str) -> Dict[str, int]:
    base = {"phone": {"$regex": f"{ALLOWED_PHONE}$"}}
    inb = await db.aihub_wa_messages.count_documents(
        {**base, "direction": "inbound", "message_id": {"$regex": f"^SM-{round_tag}-"}})
    return {"inbound_persisted": inb}


async def _run_round(round_size: int, db, max_concurrent: int = 200) -> Dict[str, Any]:
    round_tag = f"qstress{round_size}"
    print(f"\n━━━ Round {round_size} (concurrent={max_concurrent}) ━━━")

    # Limpar tudo da round anterior pra ter contagem limpa
    # (não apagamos mensagens pq são reais; apenas usamos round_tag único por size)
    texts = [
        f"[QUEUE-STRESS-{round_size}#{i:05d}] mensagem {i+1}/{round_size}"
        for i in range(round_size)
    ]

    sem = asyncio.Semaphore(max_concurrent)
    t_start = time.perf_counter()
    async with httpx.AsyncClient(limits=httpx.Limits(
            max_connections=max_concurrent * 2,
            max_keepalive_connections=max_concurrent)) as client:
        results = await asyncio.gather(*[
            _send(client, sem, txt, i, round_tag) for i, txt in enumerate(texts)
        ])
    t_inject = time.perf_counter() - t_start

    statuses: Dict[int, int] = {}
    latencies: List[float] = []
    duplicates = 0
    for r in results:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
        latencies.append(r["latency_ms"])
        if r.get("duplicate"):
            duplicates += 1

    # Wait queue drain
    print(f"  💉 injeção: {round_size} msgs em {t_inject:.2f}s "
          f"({round_size/t_inject:.1f} rps). aguardando fila…")
    t_q_start = time.perf_counter()
    drain = await _wait_queue_drain(
        db, round_tag, expected=round_size,
        timeout_s=max(300.0, round_size * 4.0))
    t_drain = time.perf_counter() - t_q_start

    # DB counts
    db_state = await _count_db(db, round_tag)

    # Stats
    p50 = statistics.median(latencies) if latencies else 0
    p95 = (statistics.quantiles(latencies, n=20)[18]
           if len(latencies) >= 20 else max(latencies, default=0))
    p99 = (statistics.quantiles(latencies, n=100)[98]
           if len(latencies) >= 100 else max(latencies, default=0))

    inj_inbound_persisted = db_state["inbound_persisted"]
    inbound_loss = round_size - inj_inbound_persisted

    q_done = drain.get("done", 0)
    q_failed = drain.get("failed", 0)
    q_queued = drain.get("queued", 0)
    q_processing = drain.get("processing", 0)
    processed = q_done + q_failed

    summary = {
        "size": round_size,
        "round_tag": round_tag,
        "inject_wall_s": round(t_inject, 2),
        "inject_throughput_rps": round(round_size / t_inject, 2) if t_inject else 0,
        "drain_wall_s": round(t_drain, 2),
        "drain_throughput_rps": (round(processed / t_drain, 2)
                                 if t_drain and processed else 0),
        "http_status": statuses,
        "duplicates_returned": duplicates,
        "latency_ms_avg": round(sum(latencies)/len(latencies), 1) if latencies else 0,
        "latency_ms_p50": round(p50, 1),
        "latency_ms_p95": round(p95, 1),
        "latency_ms_p99": round(p99, 1),
        "latency_ms_max": round(max(latencies, default=0), 1),
        "inbound_persisted": inj_inbound_persisted,
        "inbound_loss": inbound_loss,
        "queue_done": q_done, "queue_failed": q_failed,
        "queue_queued_remaining": q_queued, "queue_processing_remaining": q_processing,
        "processed_pct": round(q_done * 100 / round_size, 1) if round_size else 0,
    }
    print(f"  ⏱  webhook p50={summary['latency_ms_p50']}ms  "
          f"p95={summary['latency_ms_p95']}ms  "
          f"p99={summary['latency_ms_p99']}ms")
    print(f"  🌐 HTTP {summary['http_status']}  duplicates={duplicates}")
    print(f"  💾 inbound persistidas: {inj_inbound_persisted}/{round_size}  "
          f"(loss={inbound_loss})")
    print(f"  🏭 queue drain: done={q_done} failed={q_failed} "
          f"queued={q_queued} processing={q_processing}  em {t_drain:.1f}s  "
          f"= {summary['drain_throughput_rps']} jobs/s")
    print(f"  ✅ processadas: {summary['processed_pct']}%")
    return summary


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", default="100,500,1000,5000")
    ap.add_argument("--concurrent", type=int, default=200,
                    help="máximo de requests httpx concorrentes (semaphore)")
    args = ap.parse_args()
    rounds = [int(x) for x in args.rounds.split(",") if x.strip()]

    print("═" * 66)
    print("OPERAÇÃO FILA EMPRESARIAL — Stress Test (queue-based)")
    print("═" * 66)
    print(f"  Phone alvo (ÚNICO):  {ALLOWED_PHONE_E164}")
    print(f"  Tenant:              {TENANT}")
    print(f"  Endpoint:            {WEBHOOK_URL}")
    print(f"  Rodadas:             {rounds}")
    print(f"  Concorrência httpx:  {args.concurrent}")
    print("═" * 66)

    mc = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = mc[os.environ["DB_NAME"]]

    summaries: List[Dict[str, Any]] = []
    for size in rounds:
        s = await _run_round(size, db, max_concurrent=args.concurrent)
        summaries.append(s)
        # cool-down entre rodadas
        if size != rounds[-1]:
            print(f"  💤 cool-down 5s…")
            await asyncio.sleep(5)

    print("\n" + "═" * 66)
    print("RESUMO OPERAÇÃO FILA EMPRESARIAL")
    print("═" * 66)
    for s in summaries:
        print(
            f"  size={s['size']:>5}  "
            f"inject_rps={s['inject_throughput_rps']:>6.1f}  "
            f"p95={s['latency_ms_p95']:>6.1f}ms  "
            f"p99={s['latency_ms_p99']:>6.1f}ms  "
            f"loss={s['inbound_loss']:>3}  "
            f"dup={s['duplicates_returned']}  "
            f"processed={s['processed_pct']:>5}%  "
            f"drain_rps={s['drain_throughput_rps']:>5.1f}"
        )

    out_path = "/app/docs/fila_empresarial_stress_result.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({
            "phone_alvo": ALLOWED_PHONE_E164, "tenant": TENANT,
            "executado_em": datetime.now(timezone.utc).isoformat(),
            "rounds": summaries,
        }, f, indent=2)
    print(f"\n✅ Resultado salvo em {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
