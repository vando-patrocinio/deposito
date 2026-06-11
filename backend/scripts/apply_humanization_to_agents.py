"""apply_humanization_to_agents.py — Bootstrap one-shot.

Injeta os blocos canônicos de humanização (Anti-Slop, Escuta, Conversa
Contínua, Já Identificado, Marcadores Executáveis, Direct-First) em
TODOS os agentes conversacionais (Alvaro, Camila, Vendas, Jerusa) de
TODOS os tenants no aihub_agents.

Zero mocks. Lê e escreve direto no MongoDB real. Idempotente.

Uso:
    cd /app/backend
    python3 scripts/apply_humanization_to_agents.py [--tenant <id>]
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "presidente",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
    "notes": "Bootstrap manual de compliance.",
}

import argparse
import asyncio
import os
import sys

# Adiciona /app/backend ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db
from services import agent_compliance_scheduler as sched
from services import agent_registry as reg
from services import humanization_blocks as hb


async def _apply_for_tenant(cid: str) -> dict:
    print(f"\n━━━━━━━ TENANT: {cid} ━━━━━━━")
    result = await sched.run_compliance_pass(cid)

    for enf in result["enforcements"]:
        flag = {
            "noop": "✓",
            "injected": "↺",
            "missing": "✗",
            "skip": "—",
        }.get(enf["action"], "?")
        score = enf.get("score_after", enf.get("score_before"))
        print(f"  {flag} {enf['id']:<15} action={enf['action']:<10} "
              f"score={score}")

    if result["unmapped_agents"]:
        print(f"\n  ⚠ Agentes NÃO mapeados no ORG_CHART: "
              f"{result['unmapped_agents']}")

    snap = result["snapshot_summary"]
    print(f"\n  TEAM_SIZE={snap['team_size']}  "
          f"AVG_HUM={snap['avg_humanization_score']}/100  "
          f"OFFLINE={snap['offline']}  "
          f"FORA_CONFORMIDADE={snap['nao_conformes']}")
    return result


async def _verify_isabella_unchanged(cid: str) -> None:
    """Sanity: confirma que aplicar 2x não duplica blocos."""
    name = "Isabella"
    doc = await db.aihub_agents.find_one(
        {"company_id": cid, "name": name}, {"_id": 0, "system_prompt": 1})
    if not doc:
        return
    p = doc["system_prompt"] or ""
    count = p.count(hb.BLOCK_START)
    if count > 1:
        print(f"  ⚠ Isabella tem {count} bundles V1. Limpando...")
        clean = hb.apply(p)
        await db.aihub_agents.update_one(
            {"company_id": cid, "name": name},
            {"$set": {"system_prompt": clean}})


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", help="company_id específico")
    args = ap.parse_args()

    if args.tenant:
        tenants = [args.tenant]
    else:
        tenants = [t for t in await db.aihub_agents.distinct("company_id")
                   if t]

    print(f"Total tenants alvo: {len(tenants)}")
    summaries = []
    for cid in tenants:
        try:
            r = await _apply_for_tenant(cid)
            await _verify_isabella_unchanged(cid)
            summaries.append(r)
        except Exception as e:
            print(f"  ✗ tenant {cid} falhou: {e}")

    print("\n══════ CONSOLIDADO ══════")
    total_injected = sum(
        sum(1 for e in r["enforcements"] if e["action"] == "injected")
        for r in summaries)
    total_noop = sum(
        sum(1 for e in r["enforcements"] if e["action"] == "noop")
        for r in summaries)
    total_missing = sum(
        sum(1 for e in r["enforcements"] if e["action"] == "missing")
        for r in summaries)
    print(f"  Injetados (corrigidos):       {total_injected}")
    print(f"  Já em conformidade (noop):    {total_noop}")
    print(f"  Agente faltando em aihub:     {total_missing}")
    print(f"  Tenants processados:          {len(summaries)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
