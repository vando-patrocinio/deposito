"""Stress test do pipeline inbound → Isabella → outbound.

OPERAÇÃO VALIDAR RECEITA REAL — Fase 4
==========================================

Escopo absoluto: APENAS o número 21998176526 (subscriber sub-89c314c0d98f,
PAMELA NERY TESTE LIGO, tenant co-demo). Nenhum outro phone é tocado.

O script bombarda o endpoint Twilio inbound (canal ativo p/ co-demo) com
N mensagens simuladas e mede:
  - Quantas inbound foram persistidas
  - Quantas outbound foram geradas (resposta da Isabella)
  - Latência média / p95 / p99 do handler /api/whatsapp-twilio/webhook
  - Erros HTTP (429 rate-limit, 5xx, timeout)
  - Tempo total da bateria
  - Gaps inbound→outbound (loop fechou?)

Modo: --no-network-out  evita realmente bater na API Twilio externa
(útil pra medir só o pipeline interno). Por padrão, deixa o pipeline
livre — incluindo Twilio real — pra medir o gargalo de ponta a ponta.

Uso:
    cd /app/backend
    python3 scripts/stress_test_isabella.py --rounds 10,25,50,100
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

# ---- Constantes obrigatórias (read-only) ----
ALLOWED_PHONE = "21998176526"
ALLOWED_PHONE_E164 = "+5521998176526"
TENANT = "co-demo"
SUBSCRIBER_ID = "sub-89c314c0d98f"

# URL pública do backend (Twilio simula no ingress, mas internamente
# acertamos localhost pra evitar ida-volta na internet)
BACKEND_URL = (
    os.environ.get("PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
WEBHOOK_URL = f"{BACKEND_URL}/api/whatsapp-twilio/webhook?tenant={TENANT}"


def _payload(text: str, idx: int) -> Dict[str, str]:
    """Payload form-urlencoded igual ao Twilio gera de verdade."""
    return {
        "From": f"whatsapp:{ALLOWED_PHONE_E164}",
        "To": "whatsapp:+5521998176526",
        "Body": text,
        "ProfileName": "PAMELA TESTE",
        "MessageSid": f"SM-stress-{int(time.time())}-{idx:04d}",
        "NumMedia": "0",
        "AccountSid": "ACtest",
        "WaId": ALLOWED_PHONE,
    }


async def _one_request(client: httpx.AsyncClient, text: str,
                       idx: int) -> Dict[str, Any]:
    payload = _payload(text, idx)
    t0 = time.perf_counter()
    try:
        r = await client.post(
            WEBHOOK_URL,
            data=payload,
            timeout=60.0,
        )
        dt = (time.perf_counter() - t0) * 1000
        return {
            "idx": idx,
            "status": r.status_code,
            "latency_ms": round(dt, 1),
            "body": (r.text or "")[:200],
            "message_sid": payload["MessageSid"],
        }
    except Exception as e:  # noqa: BLE001
        dt = (time.perf_counter() - t0) * 1000
        return {
            "idx": idx,
            "status": -1,
            "latency_ms": round(dt, 1),
            "error": repr(e)[:200],
            "message_sid": payload["MessageSid"],
        }


async def _count_db_state(db) -> Dict[str, int]:
    base = {"phone": {"$regex": f"{ALLOWED_PHONE}$"}}
    inb = await db.aihub_wa_messages.count_documents(
        {**base, "direction": "inbound"})
    outb = await db.aihub_wa_messages.count_documents(
        {**base, "direction": "outbound"})
    return {"inbound": inb, "outbound": outb}


async def _run_round(round_size: int, db, prefix: str) -> Dict[str, Any]:
    print(f"\n━━━ Round {prefix}: {round_size} mensagens ━━━")
    before = await _count_db_state(db)
    print(f"  estado inicial DB: inbound={before['inbound']}  "
          f"outbound={before['outbound']}")

    texts = [
        f"[STRESS-TEST {prefix}#{i:03d}] Mensagem de teste {i+1}/{round_size}. "
        f"Por favor confirme."
        for i in range(round_size)
    ]

    t_start = time.perf_counter()
    async with httpx.AsyncClient() as client:
        tasks = [_one_request(client, txt, i) for i, txt in enumerate(texts)]
        results = await asyncio.gather(*tasks)
    t_total = time.perf_counter() - t_start

    # Aguarda processamento do _generate_and_send_twilio_reply concluir
    # (é síncrono dentro do handler — mas LLM + Twilio podem ainda estar
    # voando se algum request travou. Damos 10s de cortesia).
    await asyncio.sleep(10)
    after = await _count_db_state(db)

    statuses: Dict[int, int] = {}
    latencies: List[float] = []
    for r in results:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
        latencies.append(r["latency_ms"])

    delta_in = after["inbound"] - before["inbound"]
    delta_out = after["outbound"] - before["outbound"]
    inbound_loss = round_size - delta_in
    outbound_loss = round_size - delta_out

    p50 = statistics.median(latencies) if latencies else 0
    p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies, default=0)
    p99 = statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies, default=0)

    summary = {
        "round": prefix,
        "size": round_size,
        "wall_clock_s": round(t_total, 2),
        "throughput_rps": round(round_size / t_total, 2) if t_total else 0,
        "http_status": statuses,
        "latency_ms_avg": round(sum(latencies)/len(latencies), 1) if latencies else 0,
        "latency_ms_p50": round(p50, 1),
        "latency_ms_p95": round(p95, 1),
        "latency_ms_p99": round(p99, 1),
        "latency_ms_max": round(max(latencies, default=0), 1),
        "db_delta_inbound": delta_in,
        "db_delta_outbound": delta_out,
        "inbound_loss": inbound_loss,
        "outbound_loss": outbound_loss,
        "loop_closed_pct": (round(delta_out / round_size * 100, 1)
                            if round_size else 0),
        "before": before,
        "after": after,
    }
    print(f"  ⏱  wall_clock={summary['wall_clock_s']}s  "
          f"throughput={summary['throughput_rps']} req/s")
    print(f"  📈 latency  avg={summary['latency_ms_avg']}ms  "
          f"p50={summary['latency_ms_p50']}  "
          f"p95={summary['latency_ms_p95']}  "
          f"p99={summary['latency_ms_p99']}  "
          f"max={summary['latency_ms_max']}")
    print(f"  🌐 HTTP statuses: {summary['http_status']}")
    print(f"  💾 DB Δ inbound={delta_in}  outbound={delta_out}  "
          f"loop_closed={summary['loop_closed_pct']}%")
    if inbound_loss > 0:
        print(f"  🔴 PERDA INBOUND: {inbound_loss} mensagens não foram persistidas!")
    if outbound_loss > 0:
        print(f"  🟡 GAP OUTBOUND: {outbound_loss} respostas Isabella não geradas")
    return summary


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", default="10,25,50,100",
                    help="rodadas separadas por vírgula")
    ap.add_argument("--no-confirm", action="store_true",
                    help="pula confirmação interativa")
    args = ap.parse_args()

    rounds = [int(x) for x in args.rounds.split(",") if x.strip()]
    print("═" * 66)
    print("OPERAÇÃO VALIDAR RECEITA REAL — Fase 4 Stress Test")
    print("═" * 66)
    print(f"  Phone alvo (ÚNICO):  {ALLOWED_PHONE_E164}")
    print(f"  Tenant:              {TENANT}")
    print(f"  Subscriber:          {SUBSCRIBER_ID}")
    print(f"  Endpoint:            {WEBHOOK_URL}")
    print(f"  Rodadas:             {rounds}")
    print("═" * 66)

    mc = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = mc[os.environ["DB_NAME"]]

    # Sanity check: certificar que o subscriber alvo existe
    sub = await db.subscribers.find_one(
        {"id": SUBSCRIBER_ID, "company_id": TENANT}, {"_id": 0, "name": 1, "phone": 1})
    if not sub:
        raise SystemExit(f"❌ Subscriber {SUBSCRIBER_ID} não encontrado!")
    print(f"\n✅ Subscriber alvo: {sub['name']} ({sub['phone']})")

    summaries: List[Dict[str, Any]] = []
    for size in rounds:
        s = await _run_round(size, db, prefix=f"R{size}")
        summaries.append(s)
        # Cool-down entre rodadas
        if size != rounds[-1]:
            print(f"  💤 cool-down 8s antes do próximo round…")
            await asyncio.sleep(8)

    print("\n" + "═" * 66)
    print("RESUMO FASE 4")
    print("═" * 66)
    for s in summaries:
        print(
            f"  {s['round']:>5}  "
            f"size={s['size']:>4}  "
            f"throughput={s['throughput_rps']:>5} rps  "
            f"p95={s['latency_ms_p95']:>7}ms  "
            f"loop={s['loop_closed_pct']:>5}%  "
            f"loss_in={s['inbound_loss']}  "
            f"loss_out={s['outbound_loss']}"
        )

    out_path = "/app/docs/fase4_stress_test_result.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({
            "phone_alvo": ALLOWED_PHONE_E164,
            "tenant": TENANT,
            "executado_em": datetime.now(timezone.utc).isoformat(),
            "rounds": summaries,
        }, f, indent=2)
    print(f"\n✅ Resultado salvo em {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
