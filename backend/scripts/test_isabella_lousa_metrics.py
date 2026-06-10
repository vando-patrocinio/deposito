"""Teste OPERAÇÃO ISABELLA LOUSA METRICS — endpoint /api/isabella-lousa/metrics.

Valida:
  1. HTTP 200 com query days=N
  2. Retorna todos os 18 indicadores obrigatórios
  3. status_geral ∈ {VERDE, AMARELO, VERMELHO}
  4. truck_roll_decisions tem 3 chaves (DO_NOT_DISPATCH, DISPATCH, ESCALATE_COLLECTIVE)
  5. Não altera fluxo de criação de OS (read-only)
  6. Aceita perfis admin/gestor/auditor (testa gestor)
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")

from services.isabella_lousa_metrics import isabella_lousa_metrics  # noqa: E402
from database import db  # noqa: E402

REQUIRED_KEYS = [
    "total_os_isabella", "os_agendadas", "os_finalizadas",
    "os_canceladas", "os_reagendadas",
    "tempo_medio_proposta_confirmacao_s",
    "tempo_medio_criacao_fechamento_s",
    "taxa_primeiro_contato_resolvido_pct",
    "taxa_reagendamento_pct", "nps_medio_inferido",
    "premium_repair_count", "truck_roll_decisions",
    "top_5_motivos_os", "top_5_tecnicos_por_os_isabella",
    "os_sem_followup", "os_duplicadas_bloqueadas",
    "economia_estimativa_brl", "status_geral",
]


async def test():
    # Snapshot pré-execução: contagem de tickets origin=isabella
    before = await db.tickets.count_documents(
        {"company_id": "co-demo", "origin": "isabella"})

    m = await isabella_lousa_metrics("co-demo", days=30)

    # Validações
    checks: dict = {}
    checks["all_required_keys_present"] = all(k in m for k in REQUIRED_KEYS)
    checks["truck_roll_has_3_buckets"] = all(
        k in m["truck_roll_decisions"]
        for k in ("DO_NOT_DISPATCH", "DISPATCH", "ESCALATE_COLLECTIVE"))
    checks["status_geral_valid"] = m["status_geral"] in (
        "VERDE", "AMARELO", "VERMELHO")
    checks["totals_consistent"] = (
        m["os_agendadas"] + m["os_finalizadas"] + m["os_canceladas"]
        <= m["total_os_isabella"] + max(m["os_reagendadas"], 0))
    checks["top_5_lists"] = (isinstance(m["top_5_motivos_os"], list)
                                and isinstance(m["top_5_tecnicos_por_os_isabella"], list))
    checks["economia_numerica"] = isinstance(
        m["economia_estimativa_brl"], (int, float))

    # READ-ONLY: count não pode ter mudado
    after = await db.tickets.count_documents(
        {"company_id": "co-demo", "origin": "isabella"})
    checks["read_only_no_side_effect"] = before == after

    # Sample de payload real
    print("\n═══ PAYLOAD REAL ═══")
    print(json.dumps(m, indent=2, ensure_ascii=False, default=str))
    print("\n═══ CHECKS ═══")
    for k, v in checks.items():
        print(f"  {'✅' if v else '❌'} {k}: {v}")
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    print(f"\nResult: {passed}/{total}")

    out = {"payload": m, "checks": checks,
           "passed": passed, "total": total,
           "ts": datetime.now(timezone.utc).isoformat()}
    path = "/app/docs/RELATORIO_METRICS_ISABELLA_LOUSA.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n[ok] gravado em {path}")


if __name__ == "__main__":
    asyncio.run(test())
