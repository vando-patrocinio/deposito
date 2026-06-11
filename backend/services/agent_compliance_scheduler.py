"""AGENT COMPLIANCE SCHEDULER — auto-sync diário de humanização.

Para cada tenant + agente que requer humanização:
  1. Lê system_prompt atual em aihub_agents.
  2. Verifica blocos canônicos (humanization_blocks.check_compliance).
  3. Se faltam blocos: reinjeta o bundle V1 (idempotente).
  4. Se módulo apareceu novo em aihub_agents (não mapeado em ORG_CHART):
     emite AGENT_COMPLIANCE_BREACH para o Presidente IA.
  5. Snapshot diário persistido em agent_registry_snapshots.

Roda via worker existente (conselho_ia_scheduler) ou manualmente
via POST /api/presidente/equipe/scan.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "presidente",
    "criticality": "critical",
    "emits_events": True,
    "event_types": [
        "AGENT_COMPLIANCE_BREACH",
        "AGENT_COMPLIANCE_FIXED",
        "AGENT_NEW_DISCOVERED",
        "AGENT_REGISTRY_SCAN_DONE",
    ],
    "company_id_required": True,
}

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from database import db
from services import agent_registry as reg
from services import humanization_blocks as hb
from services import presidente_ia as svc

log = logging.getLogger("ponto.agent_compliance")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _enforce_blocks(company_id: str, agent_meta: Dict[str, Any]
                              ) -> Dict[str, Any]:
    """Aplica os blocos canônicos no aihub_agents do tenant para o
    agente dado. Idempotente. Retorna dict com o que aconteceu."""
    name = agent_meta.get("aihub_name")
    if not name:
        return {"id": agent_meta["id"], "action": "skip",
                  "reason": "no aihub_name"}

    doc = await db.aihub_agents.find_one(
        {"company_id": company_id, "name": name},
        {"_id": 0, "system_prompt": 1})
    if not doc:
        return {"id": agent_meta["id"], "action": "missing",
                  "reason": f"aihub_agents '{name}' não existe"}

    prompt = doc.get("system_prompt") or ""
    compliance = hb.check_compliance(prompt)
    needs = not all(compliance.values())
    if not needs:
        return {"id": agent_meta["id"], "action": "noop",
                  "score_before": 100.0, "score_after": 100.0}

    new_prompt = hb.apply(prompt)
    await db.aihub_agents.update_one(
        {"company_id": company_id, "name": name},
        {"$set": {
            "system_prompt": new_prompt,
            "updated_at": _now_iso(),
            "updated_by": "agent_compliance_scheduler",
        }})

    new_compliance = hb.check_compliance(new_prompt)
    return {
        "id": agent_meta["id"],
        "action": "injected",
        "score_before": hb.compliance_score(prompt),
        "score_after": hb.compliance_score(new_prompt),
        "blocks_after": new_compliance,
    }


async def _detect_unmapped_agents(company_id: str) -> List[str]:
    """Detecta agentes em aihub_agents que NÃO estão no ORG_CHART."""
    mapped_names = {a["aihub_name"] for a in reg.ORG_CHART
                    if a.get("aihub_name")}
    found = []
    cur = db.aihub_agents.find(
        {"company_id": company_id},
        {"_id": 0, "name": 1})
    async for d in cur:
        n = d.get("name")
        if n and n not in mapped_names:
            found.append(n)
    return found


async def run_compliance_pass(company_id: str) -> Dict[str, Any]:
    """Roda 1 ciclo de compliance + snapshot para o tenant."""
    enforcements: List[Dict[str, Any]] = []
    alerts = 0

    for agent_meta in reg.ORG_CHART:
        if not agent_meta.get("humanization_required"):
            continue
        result = await _enforce_blocks(company_id, agent_meta)
        enforcements.append(result)

        if result["action"] == "injected":
            alerts += 1
            await svc.record_event(
                company_id,
                "AGENT_COMPLIANCE_FIXED",
                source="agent_compliance_scheduler",
                severity="warn",
                data={"agent_id": result["id"],
                        "score_before": result.get("score_before"),
                        "score_after": result.get("score_after")})
        elif result["action"] == "missing":
            alerts += 1
            await svc.record_event(
                company_id,
                "AGENT_COMPLIANCE_BREACH",
                source="agent_compliance_scheduler",
                severity="alert",
                data={"agent_id": result["id"],
                        "reason": result.get("reason")})

    # Detecta agentes novos não mapeados
    unmapped = await _detect_unmapped_agents(company_id)
    if unmapped:
        await svc.record_event(
            company_id,
            "AGENT_NEW_DISCOVERED",
            source="agent_compliance_scheduler",
            severity="warn",
            data={"unmapped": unmapped,
                    "count": len(unmapped)})
        alerts += 1

    snapshot = await reg.snapshot_all(company_id)
    await svc.record_event(
        company_id,
        "AGENT_REGISTRY_SCAN_DONE",
        source="agent_compliance_scheduler",
        severity="info",
        data={"team_size": snapshot["team_size"],
                "avg_humanization_score": snapshot["avg_humanization_score"],
                "offline": snapshot["offline"],
                "nao_conformes": snapshot["nao_conformes"]})

    return {
        "company_id": company_id,
        "ran_at": _now_iso(),
        "enforcements": enforcements,
        "unmapped_agents": unmapped,
        "alerts_emitted": alerts,
        "snapshot_summary": {
            "team_size": snapshot["team_size"],
            "avg_humanization_score": snapshot["avg_humanization_score"],
            "offline": snapshot["offline"],
            "nao_conformes": snapshot["nao_conformes"],
        },
    }


async def run_compliance_all_tenants() -> Dict[str, Any]:
    """Roda compliance para TODOS os tenants que têm aihub_agents."""
    tenants = await db.aihub_agents.distinct("company_id")
    results = []
    for cid in tenants:
        if not cid:
            continue
        try:
            results.append(await run_compliance_pass(cid))
        except Exception as e:
            log.exception("[agent_compliance] tenant %s falhou: %s",
                            cid, e)
            results.append({"company_id": cid, "error": str(e)})
    return {"ran_at": _now_iso(),
              "tenants": len(results), "results": results}
