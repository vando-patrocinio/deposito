"""Rotas administrativas para reload de prompts versionados no Git.

POST /api/aihub/agents/{agent_name}/reload-prompt
GET  /api/aihub/agents/prompt-source-status
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "isabella",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from fastapi import APIRouter, Depends, HTTPException

from core import DEMO_COMPANY_ID, require_role
from database import db
from services import prompt_loader


router = APIRouter(prefix="/api/aihub/prompts", tags=["aihub-prompts"])


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


@router.post("/{agent_name}/reload-prompt")
async def reload_one(agent_name: str,
                          user: dict = Depends(require_role("gestor"))):
    """Recarrega o prompt do agente a partir do arquivo `.md`
    versionado em /app/backend/prompts/. Idempotente."""
    cfg = next((c for c in prompt_loader.AGENT_PROMPTS
                 if c["agent_name"] == agent_name), None)
    if not cfg:
        raise HTTPException(404,
                                f"Agente {agent_name} não tem prompt no Git.")
    cid = _cid(user)
    result = await prompt_loader.sync_one(
        cfg["agent_name"], cfg["file"], cfg["version"], cid)
    return result


@router.get("/source-status")
async def status(user: dict = Depends(require_role("gestor"))):
    """Retorna o status de sincronia de TODOS os agentes mapeados."""
    cid = _cid(user)
    rows = []
    for cfg in prompt_loader.AGENT_PROMPTS:
        doc = await db.aihub_agents.find_one(
            {"company_id": cid, "name": cfg["agent_name"]},
            {"_id": 0, "prompt_version": 1, "prompt_source_file": 1,
             "prompt_source_sha": 1, "prompt_applied_at": 1,
             "updated_by": 1})
        rows.append({
            "agent": cfg["agent_name"],
            "expected_file": cfg["file"],
            "expected_version": cfg["version"],
            "current": doc or {},
        })
    return {"company_id": cid, "agents": rows}
