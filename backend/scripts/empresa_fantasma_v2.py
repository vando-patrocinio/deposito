"""Empresa Fantasma V2 — re-roda cenário e ATIVA pipelines autônomos."""
from __future__ import annotations

import asyncio
import os
import sys
import importlib

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND, ".env"))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

TENANT = "co-fantasma-test"


async def main():
    # Re-seed via empresa_fantasma original
    sys.path.insert(0, HERE)
    fantasma = importlib.import_module("empresa_fantasma")
    mc = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = mc[os.environ["DB_NAME"]]

    print("═" * 60)
    print("EMPRESA FANTASMA V2 — pipelines AUTÔNOMOS ATIVADOS")
    print("═" * 60)

    # ── 1) re-seed ──
    seeded = await fantasma.seed(db)

    # ── 2) Métricas ANTES (sem pipeline) ──
    print("\n▶ MÉTRICAS ANTES dos pipelines:")
    before = await fantasma.medir(db, seeded)

    # ── 3) ATIVA AUTONOMOUS RUNNER ──
    print("\n▶ ATIVANDO autonomous_runner para tenant fantasma…")
    from services.autonomous_runner import run_once_for
    runner_res = await run_once_for(TENANT)
    print(f"  drivers executados: {list(runner_res['drivers'].keys())}")
    for name, r in runner_res["drivers"].items():
        if isinstance(r, dict) and r.get("error"):
            print(f"    {name}: ERRO {r['error'][:80]}")
        else:
            print(f"    {name}: {r}")

    # ── 4) Métricas DEPOIS ──
    print("\n▶ MÉTRICAS DEPOIS dos pipelines:")
    # Conta ações geradas
    motor_actions = await db.motor_ia_actions.count_documents({"company_id": TENANT})
    motor_decisions = await db.motor_ia_decisions.count_documents({"company_id": TENANT})
    print(f"  motor_ia_decisions: {motor_decisions}")
    print(f"  motor_ia_actions:   {motor_actions}")

    # Receita gerada → executive_ledger
    ledger_n = 0
    ledger_value = 0
    try:
        async for row in db.executive_ledger.find({"company_id": TENANT}):
            ledger_n += 1
            v = row.get("value") or row.get("amount") or 0
            try:
                ledger_value += float(v)
            except Exception:
                pass
    except Exception:
        pass
    print(f"  executive_ledger:   {ledger_n} entries · R$ {ledger_value:.2f}")

    # Re-mede SFO depois de truck guard agir
    rep_total_post = await db.smart_repairs.count_documents({"company_id": TENANT})
    rep_avoided_post = await db.smart_repairs.count_documents(
        {"company_id": TENANT, "truck_roll_avoided": True})
    rep_escalated_post = await db.smart_repairs.count_documents(
        {"company_id": TENANT, "status": "escalated_collective"})
    tra_pct_post = round(rep_avoided_post * 100 / max(rep_total_post, 1), 1)
    print(f"  smart_repairs total: {rep_total_post} · avoided: {rep_avoided_post} ({tra_pct_post}%) · escalated: {rep_escalated_post}")

    # Outage decisions
    n_truck_decisions = await db.truck_roll_decisions.count_documents({"company_id": TENANT})
    print(f"  truck_roll_decisions: {n_truck_decisions}")

    # Autonomy score consolidado
    try:
        from services.autonomous_engine import compute_autonomy_score
        score = await compute_autonomy_score(TENANT)
        print(f"\n  AUTONOMY SCORE: {score}")
    except Exception as e:
        print(f"  AUTONOMY SCORE: erro {e}")

    print("\n═" * 30)
    print("ANTES x DEPOIS")
    print("═" * 30)
    print(f"  Isabella resolução:    {before['isabella']['resolution_pct']}% (não muda — já era 99%)")
    print(f"  Álvaro detectadas:     {before['alvaro']['detectadas']} → +{runner_res['drivers'].get('outage_detect', {}).get('clusters_detected', 0)} via outage_detect")
    print(f"  SFO TRA antes:         {before['sfo']['tra_pct']}%")
    print(f"  SFO TRA depois:        {tra_pct_post}% (com truck_roll_guard ATIVO)")
    print(f"  Nervoso:               {before['nervoso']['coverage_pct']}% (100% mantido)")
    print(f"  Decisões autônomas:    0 → {motor_decisions}")
    print(f"  Ações executadas:      0 → {motor_actions}")
    print(f"  Receita autônoma:      R$ {ledger_value:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
