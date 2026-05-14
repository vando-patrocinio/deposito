"""AI Training routes — endpoints para gerenciar o treinamento multiagente.

Inclui:
- GET /api/ai-training/status  → status de cada agente + KB
- POST /api/ai-training/reload → re-executa o seed (idempotente, admin only)
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from core import require_role
from database import db
from scripts.seed_training_agents import (
    seed_new_agents, seed_training_kb, update_existing_agents,
)


router = APIRouter(prefix="/api/ai-training", tags=["ai-training"])


@router.get("/status")
async def training_status(user: dict = Depends(require_role("gestor"))):
    """Lista os 10 agentes + status do treinamento (KB + último reload)."""
    cid = user.get("company_id", "co-demo")
    agents = await db.aihub_agents.find(
        {"company_id": cid},
        {"_id": 0, "id": 1, "name": 1, "topology_node": 1,
         "model_provider": 1, "model_name": 1, "temperature": 1,
         "max_tokens": 1, "active": 1, "training_loaded_at": 1,
         "updated_at": 1},
    ).to_list(50)
    kb = await db.ai_training_kb.find(
        {"company_id": cid},
        {"_id": 0, "id": 1, "key": 1, "title": 1, "updated_at": 1},
    ).to_list(20)
    last_reload = None
    for a in agents:
        ts = a.get("training_loaded_at")
        if ts and (last_reload is None or ts > last_reload):
            last_reload = ts
    return {
        "ok": True,
        "company_id": cid,
        "agents_count": len(agents),
        "agents_with_training": sum(1 for a in agents if a.get("training_loaded_at")),
        "kb_documents": len(kb),
        "last_reload_at": last_reload,
        "agents": sorted(agents, key=lambda x: x.get("topology_node") or ""),
        "kb": sorted(kb, key=lambda x: x.get("key") or ""),
    }


@router.post("/reload")
async def training_reload(user: dict = Depends(require_role("gestor"))):
    """Re-executa o seed do treinamento. Apenas admin/gestor."""
    cid = user.get("company_id", "co-demo")
    try:
        await seed_training_kb(db, company_id=cid)
        await seed_new_agents(db, company_id=cid)
        await update_existing_agents(db, company_id=cid)
    except Exception as e:
        raise HTTPException(500, f"Falha no reload: {e}")
    agents = await db.aihub_agents.find(
        {"company_id": cid},
        {"_id": 0, "name": 1, "topology_node": 1,
         "training_loaded_at": 1, "model_provider": 1, "model_name": 1},
    ).to_list(50)
    kb_count = await db.ai_training_kb.count_documents({"company_id": cid})
    return {
        "ok": True,
        "reloaded_at": datetime.now(timezone.utc).isoformat(),
        "agents_count": len(agents),
        "kb_documents": kb_count,
        "agents": sorted(agents, key=lambda x: x.get("topology_node") or ""),
    }


@router.get("/scenarios")
async def scenarios_list(user: dict = Depends(require_role("gestor")),
                          category: str | None = None,
                          tag: str | None = None,
                          q: str | None = None):
    """Lista cenários de treinamento. Filtros opcionais: category, tag, q."""
    cid = user.get("company_id", "co-demo")
    filt = {"company_id": cid}
    if category:
        filt["category"] = category
    if tag:
        filt["tags"] = tag
    if q:
        filt["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"objetivo": {"$regex": q, "$options": "i"}},
            {"licao": {"$regex": q, "$options": "i"}},
        ]
    items = await db.ai_training_scenarios.find(
        filt, {"_id": 0}
    ).sort("number", 1).to_list(200)
    total = await db.ai_training_scenarios.count_documents({"company_id": cid})
    return {"ok": True, "count": len(items), "total": total, "items": items}


@router.get("/scenarios/{number}")
async def scenario_get(number: int, user: dict = Depends(require_role("gestor"))):
    """Pega um cenário específico pelo número."""
    cid = user.get("company_id", "co-demo")
    s = await db.ai_training_scenarios.find_one(
        {"company_id": cid, "number": number}, {"_id": 0}
    )
    if not s:
        raise HTTPException(404, f"Cenário #{number} não encontrado")
    return s
