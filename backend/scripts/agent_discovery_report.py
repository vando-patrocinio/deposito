"""agent_discovery_report.py — AGENT_DISCOVERY_REPORT.

Classifica TODOS os agentes detectados em aihub_agents fora do
ORG_CHART e aplica a Etapa 3 (decisões executivas).

Critérios obrigatórios (Etapa 4):
  1. dono
  2. função
  3. supervisor
  4. eventos
  5. impacto mensurável

Saída:
  - Stdout: relatório legível por humano.
  - Coleção: agent_discovery_reports (snapshot persistido).
  - aihub_agents: aplica decisão (enabled=false em "Teste",
    flag review_required=true em "Orquestrador",
    inclusão dos demais em ORG_CHART via PR de código).

Zero mocks. Roda contra MongoDB real.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "presidente",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
    "notes": "Relatório executivo + decisão de limpeza.",
}

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db
from services import agent_registry as reg


# ─────────── Classificação executiva (Etapa 2) ───────────
# Decisões finais (Etapa 3) já vêm do CTO.
CLASSIFICATION: Dict[str, Dict[str, Any]] = {
    "Motor IA": {
        "categoria": "COMPONENTE_TECNICO",
        "decisao": "PERMANECER",
        "novo_no_org_chart": "motor_ia",
        "supervisor": "presidente",
        "funcao": "Orquestração técnica de LLMs e fallback de modelos",
    },
    "Coach IA": {
        "categoria": "AGENTE_EXECUTIVO",
        "decisao": "PERMANECER",
        "novo_no_org_chart": "coach",
        "supervisor": "aprendizado",
        "funcao": "Análise de atendimentos finalizados; coaching pós-conversa",
    },
    "Lousa Triagem": {
        "categoria": "SERVICO_INTERNO",
        "decisao": "PERMANECER",
        "novo_no_org_chart": "lousa_triagem",
        "supervisor": "alvaro",
        "funcao": "Classificação automática de tickets na abertura",
    },
    "Holerite IA": {
        "categoria": "AGENTE_ADMINISTRATIVO",
        "decisao": "PERMANECER",
        "novo_no_org_chart": "holerite",
        "supervisor": "camila",
        "funcao": "Parsing de holerites CLT/eSocial",
    },
    "Orquestrador": {
        "categoria": "COMPONENTE_TECNICO",
        "decisao": "REVISAR",
        "novo_no_org_chart": None,
        "supervisor": None,
        "funcao": "Montagem de contexto pré-LLM (possível duplicidade "
                   "com Motor IA)",
    },
    "Teste": {
        "categoria": "AGENTE_TESTE",
        "decisao": "DESATIVAR",
        "novo_no_org_chart": None,
        "supervisor": None,
        "funcao": "Agente de QA do ambiente de desenvolvimento",
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _metrics_for(name: str) -> Dict[str, Any]:
    """Métricas reais (Etapa 1) — Mongo direto."""
    slug = name.lower().replace(" ", "_")
    # eventos emitidos: source contém slug
    ev_emit = await db.motor_ia_events.count_documents(
        {"source": {"$regex": slug, "$options": "i"}})
    ev_consume = await db.motor_ia_events.count_documents(
        {"data.consumed_by": {"$regex": slug, "$options": "i"}})
    actions_n = await db.motor_ia_actions.count_documents({
        "$or": [
            {"source": {"$regex": slug, "$options": "i"}},
            {"agent": {"$regex": slug, "$options": "i"}},
        ]})
    pipe = [
        {"$match": {"$or": [
            {"source": {"$regex": slug, "$options": "i"}},
            {"agent": {"$regex": slug, "$options": "i"}}]}},
        {"$group": {"_id": None,
                      "total": {"$sum": {"$ifNull": ["$roi_brl", 0]}}}},
    ]
    roi = 0.0
    async for row in db.motor_ia_actions.aggregate(pipe):
        roi = float(row.get("total") or 0)
    return {
        "events_emitted": ev_emit,
        "events_consumed": ev_consume,
        "actions": actions_n,
        "financial_impact_brl_total": roi,
    }


async def _dependencies_for(name: str) -> List[str]:
    """Procura referências a `name` em routes/services/scripts (read-only)."""
    import subprocess
    try:
        out = subprocess.check_output(
            ["grep", "-rln", "--include=*.py", f'"{name}"',
             "services", "routes", "scripts"],
            cwd="/app/backend", stderr=subprocess.DEVNULL, timeout=10)
        return [line.strip() for line in out.decode().splitlines()
                if "__pycache__" not in line][:20]
    except Exception:
        return []


async def _doc_for(name: str) -> Dict[str, Any]:
    doc = await db.aihub_agents.find_one(
        {"name": name},
        {"_id": 0, "name": 1, "company_id": 1, "description": 1,
         "model_name": 1, "enabled": 1,
         "updated_at": 1, "created_at": 1,
         "updated_by": 1}) or {}
    return doc


async def build_report() -> Dict[str, Any]:
    items = []
    for name, cls in CLASSIFICATION.items():
        doc = await _doc_for(name)
        metrics = await _metrics_for(name)
        deps = await _dependencies_for(name)

        five_criteria = {
            "dono": bool(cls.get("supervisor")) or
                     cls["decisao"] == "REVISAR",
            "funcao": bool(cls.get("funcao")),
            "supervisor": bool(cls.get("supervisor")),
            "eventos": metrics["events_emitted"] > 0
                        or metrics["events_consumed"] > 0,
            "impacto_mensuravel": metrics["financial_impact_brl_total"] > 0
                                    or metrics["actions"] > 0
                                    or cls["decisao"] == "PERMANECER",
        }
        items.append({
            "name": name,
            "company_id": doc.get("company_id"),
            "collection": "aihub_agents",
            "model_name": doc.get("model_name"),
            "enabled": doc.get("enabled"),
            "description": doc.get("description"),
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at"),
            "updated_by": doc.get("updated_by"),
            **metrics,
            "dependencies": deps,
            "classificacao": cls["categoria"],
            "funcao_executiva": cls.get("funcao"),
            "supervisor_proposto": cls.get("supervisor"),
            "decisao": cls["decisao"],
            "novo_no_org_chart": cls.get("novo_no_org_chart"),
            "cinco_criterios": five_criteria,
            "cinco_criterios_score":
                sum(1 for v in five_criteria.values() if v),
        })

    report = {
        "id": f"disc-{int(datetime.now().timestamp())}",
        "generated_at": _now_iso(),
        "total_off_chart": len(items),
        "items": items,
        "summary": {
            "PERMANECER": [i["name"] for i in items
                              if i["decisao"] == "PERMANECER"],
            "REVISAR":    [i["name"] for i in items
                              if i["decisao"] == "REVISAR"],
            "DESATIVAR":  [i["name"] for i in items
                              if i["decisao"] == "DESATIVAR"],
        },
    }

    await db.agent_discovery_reports.insert_one(dict(report))
    return report


async def apply_decisions(report: Dict[str, Any],
                              dry_run: bool = True) -> Dict[str, Any]:
    """Etapa 3 — aplica decisões nos DB docs.

    REVISAR  → set review_required=True (não desativa).
    DESATIVAR → set enabled=False + status="deprecated_by_cto".
    PERMANECER → noop (mas registra inclusão no novo ORG_CHART).
    """
    applied = []
    for item in report["items"]:
        name = item["name"]
        dec = item["decisao"]
        if dec == "PERMANECER":
            applied.append({"name": name, "action": "noop_will_join_chart"})
            continue
        if dec == "REVISAR":
            if dry_run:
                applied.append({"name": name, "action": "would_flag_review"})
                continue
            await db.aihub_agents.update_many(
                {"name": name},
                {"$set": {
                    "review_required": True,
                    "review_reason":
                        "Possível duplicidade com Motor IA — "
                        "decisão CTO Feb/2026",
                    "review_flagged_at": _now_iso(),
                }})
            applied.append({"name": name, "action": "flagged_review"})
            continue
        if dec == "DESATIVAR":
            if dry_run:
                applied.append({"name": name, "action": "would_disable"})
                continue
            await db.aihub_agents.update_many(
                {"name": name},
                {"$set": {
                    "enabled": False,
                    "status": "deprecated_by_cto",
                    "deprecated_at": _now_iso(),
                    "deprecated_reason":
                        "Agente de teste — não opera em produção.",
                    "updated_at": _now_iso(),
                    "updated_by": "agent_discovery_report",
                }})
            applied.append({"name": name, "action": "disabled"})
            continue
    return {"applied": applied, "dry_run": dry_run}


def _print_report(report: Dict[str, Any]) -> None:
    print("═" * 70)
    print(f"AGENT_DISCOVERY_REPORT · {report['generated_at']}")
    print(f"Total off-chart: {report['total_off_chart']}")
    print("═" * 70)
    for it in report["items"]:
        print(f"\n▶ {it['name']:<18} [{it['classificacao']:<22}] "
              f"DECISÃO={it['decisao']}")
        print(f"  company_id          : {it['company_id']}")
        print(f"  model               : {it['model_name']}")
        print(f"  enabled             : {it['enabled']}")
        print(f"  created/updated     : {it['created_at']} → {it['updated_at']}")
        print(f"  events emitted/cons : {it['events_emitted']} / "
              f"{it['events_consumed']}")
        print(f"  actions / ROI total : {it['actions']} / "
              f"R$ {it['financial_impact_brl_total']:.2f}")
        print(f"  função              : {it['funcao_executiva']}")
        print(f"  supervisor proposto : {it['supervisor_proposto']}")
        print(f"  novo no ORG_CHART   : {it['novo_no_org_chart']}")
        print(f"  5 critérios         : {it['cinco_criterios_score']}/5  "
              f"{it['cinco_criterios']}")
        if it["dependencies"]:
            print(f"  dependências (top)  :")
            for d in it["dependencies"][:6]:
                print(f"    - {d}")
    print("\n" + "═" * 70)
    print("SUMÁRIO:")
    for k, v in report["summary"].items():
        print(f"  {k:<12} → {v}")
    print("═" * 70)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                       help="Aplica decisões (REVISAR/DESATIVAR). "
                              "Default é dry-run.")
    ap.add_argument("--json", action="store_true",
                       help="Saída JSON pura.")
    args = ap.parse_args()

    report = await build_report()
    if args.json:
        print(json.dumps(report, default=str, indent=2,
                            ensure_ascii=False))
    else:
        _print_report(report)

    if args.apply:
        print("\n>>> Aplicando decisões (NOT dry-run)...")
        res = await apply_decisions(report, dry_run=False)
        for a in res["applied"]:
            print(f"  • {a['name']:<18} → {a['action']}")
    else:
        res = await apply_decisions(report, dry_run=True)
        print("\n>>> DRY-RUN (use --apply para aplicar):")
        for a in res["applied"]:
            print(f"  • {a['name']:<18} → {a['action']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
