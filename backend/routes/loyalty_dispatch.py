"""Loyalty Dispatch — envio em massa de campanhas WhatsApp pra clientes
desativados (winback), conectando a aba "Desativados" ao módulo
existente de Disparo em Massa.

Endpoints:
  - POST /api/customer/loyalty-dispatch
        body: { campaign_id, channel_id?, agent_id?, clients[] }
        cria recipients + atualiza canal/agente + starta a campanha
  - GET  /api/customer/loyalty-dispatch/agents → lista de atendentes/gestores
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.loyalty_dispatch")
router = APIRouter(prefix="/api/customer/loyalty-dispatch",
                    tags=["loyalty-dispatch"])


class DispatchClient(BaseModel):
    document: str
    name: str = ""
    phone: str
    plan_name: str = ""
    city: str = ""


class DispatchBody(BaseModel):
    campaign_id: str
    channel_id: Optional[str] = Field(
        default=None, pattern=r"^channel-[1-4]$",
        description="Override do canal Baileys (channel-1..4)",
    )
    agent_id: Optional[str] = Field(
        default=None, description="ID do usuário responsável pelo follow-up",
    )
    clients: list[DispatchClient]
    start_now: bool = True


def _normalize_phone(p: str) -> Optional[str]:
    import re
    digits = re.sub(r"\D+", "", str(p or ""))
    if not digits:
        return None
    if not digits.startswith("55") and len(digits) in (10, 11):
        digits = "55" + digits
    if len(digits) < 12 or len(digits) > 15:
        return None
    return digits


@router.post("")
async def dispatch_to_clients(
    body: DispatchBody,
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Adiciona uma lista de clientes selecionados como recipients de uma
    campanha existente, opcionalmente trocando canal/agente, e starta."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if not body.clients:
        raise HTTPException(400, "Nenhum cliente selecionado.")

    # 1) Valida campanha existe e está em status que aceita destinatários
    camp = await db.mass_campaigns.find_one(
        {"id": body.campaign_id, "company_id": cid}, {"_id": 0},
    )
    if not camp:
        raise HTTPException(404, "Campanha não encontrada.")
    if camp.get("status") == "done":
        raise HTTPException(400,
            "Campanha já finalizada. Crie uma nova ou duplique.")

    # 2) Valida agente (se enviado)
    agent = None
    if body.agent_id:
        agent = await db.users.find_one(
            {"id": body.agent_id, "company_id": cid},
            {"_id": 0, "password_hash": 0},
        )
        if not agent:
            raise HTTPException(404, "Agente não encontrado.")

    # 3) Valida canal (se enviado) — só faz sentido pra Baileys
    if body.channel_id:
        ch = await db["whatsapp_channels"].find_one(
            {"id": body.channel_id, "company_id": cid}, {"_id": 0},
        )
        if not ch:
            raise HTTPException(404, "Canal WhatsApp não encontrado.")

    # 4) Insere recipients (dedup por phone na mesma campanha)
    now = now_iso()
    inserted, skipped_invalid, skipped_dup = 0, 0, 0
    bulk: list[dict] = []
    for c in body.clients:
        phone = _normalize_phone(c.phone)
        if not phone:
            skipped_invalid += 1
            continue
        # Dedup
        already = await db.mass_recipients.find_one(
            {"campaign_id": body.campaign_id, "phone": phone},
            {"_id": 0, "id": 1},
        )
        if already:
            skipped_dup += 1
            continue
        bulk.append({
            "id": f"rec-{uuid.uuid4().hex[:10]}",
            "campaign_id": body.campaign_id,
            "company_id": cid,
            "phone": phone,
            "name": c.name or "",
            "vars": {
                "name": c.name or "", "1": c.name or "",
                "plan": c.plan_name or "", "city": c.city or "",
            },
            "status": "queued",
            "message_id": None,
            "error": None,
            "queued_at": now,
            "sent_at": None,
            # iter215q — rastreio do disparo
            "loyalty_source": "deactivated_tab",
            "loyalty_document": c.document,
            "loyalty_agent_id": body.agent_id,
        })
    if bulk:
        await db.mass_recipients.insert_many(bulk)
        inserted = len(bulk)

    # 5) Atualiza campanha com canal + total + agente
    update_set = {
        "total_recipients": (camp.get("total_recipients", 0) + inserted),
        "updated_at": now,
    }
    if body.channel_id:
        update_set["channel_id"] = body.channel_id
    if body.agent_id:
        update_set["loyalty_agent_id"] = body.agent_id
        update_set["loyalty_agent_email"] = (agent or {}).get("email")
        update_set["loyalty_agent_name"] = (agent or {}).get("name")

    # 6) Starta se solicitado
    started = False
    if body.start_now and inserted > 0 and camp.get("status") != "running":
        update_set["status"] = "running"
        update_set["started_at"] = now
        started = True

    await db.mass_campaigns.update_one(
        {"id": body.campaign_id, "company_id": cid},
        {"$set": update_set},
    )

    # 7) Log do dispatch (auditoria)
    await db.loyalty_dispatch_logs.insert_one({
        "company_id": cid,
        "at": now,
        "user": user.get("email") or user.get("id"),
        "campaign_id": body.campaign_id,
        "campaign_name": camp.get("name"),
        "channel_id": body.channel_id,
        "agent_id": body.agent_id,
        "agent_name": (agent or {}).get("name") if agent else None,
        "total_selected": len(body.clients),
        "inserted": inserted,
        "skipped_invalid": skipped_invalid,
        "skipped_dup": skipped_dup,
        "started_now": started,
    })

    return {
        "ok": True,
        "campaign_id": body.campaign_id,
        "campaign_name": camp.get("name"),
        "inserted": inserted,
        "skipped_invalid": skipped_invalid,
        "skipped_dup": skipped_dup,
        "started_now": started,
        "agent": (agent or {}).get("name") if agent else None,
        "channel_id": body.channel_id,
    }


class DispatchFilterBody(BaseModel):
    campaign_id: str
    channel_id: Optional[str] = Field(default=None, pattern=r"^channel-[1-4]$")
    agent_id: Optional[str] = None
    praca: Optional[str] = None
    period_ym: Optional[str] = Field(
        default=None, description="YYYY-MM (mês de cancelamento)",
    )
    only_with_phone: bool = True
    max_limit: int = Field(default=10000, ge=1, le=20000)
    start_now: bool = True


async def _bg_dispatch_by_filter(
    cid: str, body_dict: dict, agent: Optional[dict], camp: dict, job_id: str,
) -> None:
    """Worker em background que processa o disparo por filtro.
    Atualiza loyalty_dispatch_jobs com progresso."""
    now = now_iso()
    inserted, skipped_invalid, skipped_dup, evaluated = 0, 0, 0, 0
    bulk: list[dict] = []
    seen_phones: set[str] = set()
    flt: dict = {"company_id": cid, "status": "Desativado"}
    if body_dict.get("praca"):
        flt["city"] = body_dict["praca"]
    try:
        cursor = db.loyalty_imported_db.find(
            flt,
            {"_id": 0, "name": 1, "document": 1,
             "phone1": 1, "phone2": 1, "phone3": 1,
             "plan_name": 1, "city": 1, "cancellation_date": 1},
        ).limit(body_dict.get("max_limit") or 20000)
        async for r in cursor:
            evaluated += 1
            if body_dict.get("period_ym"):
                if (r.get("cancellation_date") or "")[:7] != body_dict["period_ym"]:
                    continue
            phone = None
            for k in ("phone1", "phone2", "phone3"):
                p = (r.get(k) or "").strip()
                if not p or p == "55":
                    continue
                digits = "".join(c for c in p if c.isdigit())
                if not digits:
                    continue
                if not digits.startswith("55") and len(digits) in (10, 11):
                    digits = "55" + digits
                if len(digits) >= 12:
                    phone = digits
                    break
            if not phone:
                skipped_invalid += 1
                continue
            if phone in seen_phones:
                skipped_dup += 1
                continue
            seen_phones.add(phone)
            existing = await db.mass_recipients.find_one(
                {"campaign_id": body_dict["campaign_id"], "phone": phone},
                {"_id": 0, "id": 1},
            )
            if existing:
                skipped_dup += 1
                continue
            bulk.append({
                "id": f"rec-{uuid.uuid4().hex[:10]}",
                "campaign_id": body_dict["campaign_id"],
                "company_id": cid, "phone": phone,
                "name": r.get("name") or "",
                "vars": {"name": r.get("name") or "", "1": r.get("name") or "",
                          "plan": r.get("plan_name") or "",
                          "city": r.get("city") or ""},
                "status": "queued", "message_id": None, "error": None,
                "queued_at": now, "sent_at": None,
                "loyalty_source": "deactivated_filter",
                "loyalty_document": r.get("document"),
                "loyalty_agent_id": body_dict.get("agent_id"),
            })
            if len(bulk) >= 500:
                await db.mass_recipients.insert_many(bulk)
                inserted += len(bulk)
                bulk = []
                # Atualiza progresso
                await db.loyalty_dispatch_jobs.update_one(
                    {"id": job_id},
                    {"$set": {"inserted": inserted, "evaluated": evaluated,
                                "skipped_dup": skipped_dup,
                                "skipped_invalid": skipped_invalid}},
                )
        if bulk:
            await db.mass_recipients.insert_many(bulk)
            inserted += len(bulk)
        update_set = {
            "total_recipients": (camp.get("total_recipients", 0) + inserted),
            "updated_at": now,
        }
        if body_dict.get("channel_id"):
            update_set["channel_id"] = body_dict["channel_id"]
        if body_dict.get("agent_id"):
            update_set["loyalty_agent_id"] = body_dict["agent_id"]
            update_set["loyalty_agent_email"] = (agent or {}).get("email")
            update_set["loyalty_agent_name"] = (agent or {}).get("name")
        started = False
        if body_dict.get("start_now") and inserted > 0 and camp.get("status") != "running":
            update_set["status"] = "running"
            update_set["started_at"] = now
            started = True
        await db.mass_campaigns.update_one(
            {"id": body_dict["campaign_id"], "company_id": cid},
            {"$set": update_set},
        )
        await db.loyalty_dispatch_jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "done", "completed_at": now,
                          "inserted": inserted, "evaluated": evaluated,
                          "skipped_invalid": skipped_invalid,
                          "skipped_dup": skipped_dup, "started_now": started}},
        )
    except Exception as e:
        logger.exception("[loyalty-dispatch] bg job %s failed", job_id)
        await db.loyalty_dispatch_jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "error", "error": str(e), "completed_at": now}},
        )


@router.post("/by-filter")
async def dispatch_by_filter(
    body: DispatchFilterBody,
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Dispara campanha pra TODA a base filtrada em BACKGROUND.

    iter215v — Retorna instantâneo com job_id; processamento continua
    server-side em asyncio task. Cliente faz polling em GET /jobs/{id}.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    camp = await db.mass_campaigns.find_one(
        {"id": body.campaign_id, "company_id": cid}, {"_id": 0},
    )
    if not camp:
        raise HTTPException(404, "Campanha não encontrada.")
    if camp.get("status") == "done":
        raise HTTPException(400, "Campanha já finalizada.")
    agent = None
    if body.agent_id:
        agent = await db.users.find_one(
            {"id": body.agent_id, "company_id": cid},
            {"_id": 0, "password_hash": 0},
        )
        if not agent:
            raise HTTPException(404, "Agente não encontrado.")
    job_id = f"job-{uuid.uuid4().hex[:10]}"
    now = now_iso()
    await db.loyalty_dispatch_jobs.insert_one({
        "id": job_id, "company_id": cid,
        "created_at": now, "status": "running",
        "campaign_id": body.campaign_id,
        "campaign_name": camp.get("name"),
        "filters": body.model_dump(),
        "user": user.get("email") or user.get("id"),
        "inserted": 0, "evaluated": 0,
        "skipped_invalid": 0, "skipped_dup": 0,
    })
    # Fire-and-forget: cria task de background
    asyncio.create_task(_bg_dispatch_by_filter(
        cid, body.model_dump(), agent, camp, job_id,
    ))
    return {
        "ok": True, "job_id": job_id, "status": "running",
        "message": (
            f"Disparo iniciado em background. Use GET "
            f"/api/customer/loyalty-dispatch/jobs/{job_id} pra acompanhar."
        ),
    }


@router.get("/jobs/{job_id}")
async def get_dispatch_job(
    job_id: str,
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Polling de status do disparo em background."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    j = await db.loyalty_dispatch_jobs.find_one(
        {"id": job_id, "company_id": cid}, {"_id": 0},
    )
    if not j:
        raise HTTPException(404, "Job não encontrado.")
    return j


@router.get("/jobs")
async def list_dispatch_jobs(
    limit: int = 20,
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Histórico recente dos disparos em background."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cursor = db.loyalty_dispatch_jobs.find(
        {"company_id": cid}, {"_id": 0},
    ).sort("created_at", -1).limit(limit)
    return {"items": [j async for j in cursor]}


@router.get("/agents")
async def list_agents(
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Lista usuários elegíveis pra ser responsável pelo follow-up
    (gestores, atendentes, vendedores). Exclui auditor/super_admin."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    excluded = {"auditor", "super_admin"}
    cur = db.users.find(
        {"company_id": cid},
        {"_id": 0, "password_hash": 0},
    ).sort("name", 1)
    items = []
    async for u in cur:
        if u.get("role") in excluded:
            continue
        items.append({
            "id": u.get("id"),
            "name": u.get("name") or u.get("email"),
            "email": u.get("email"),
            "role": u.get("role"),
        })
    return {"items": items}
