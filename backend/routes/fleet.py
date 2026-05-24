"""routes/fleet.py — Módulo de Gestão de Frota.

Schema novo:
  fleet_vehicles      — cadastro de veículos
  fleet_inspections   — vistorias semanais (5 fotos + IA review)
  fleet_transfers     — romaneios de transferência
  fleet_fuel_entries  — lançamento de combustível mensal

Endpoints:
  /api/fleet/vehicles            CRUD veículos
  /api/fleet/inspections         Vistorias (start/upload/submit/ai-review)
  /api/fleet/me/can-operate      Verifica se técnico pode operar OS
  /api/fleet/transfers           Romaneios de transferência
  /api/fleet/transfers/{id}/pdf  PDF do romaneio (para assinatura física pelo gestor)
  /api/fleet/fuel                Lançamentos de combustível + OCR
  /api/fleet/kpis                Indicadores agregados
"""
from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, get_current_user, is_super_admin
from database import db

logger = logging.getLogger("ponto.fleet")
router = APIRouter(prefix="/api/fleet", tags=["fleet"])


def _cid(user: dict) -> str:
    if is_super_admin(user):
        return (user.get("_active_company") or user.get("company_id")
                or DEMO_COMPANY_ID)
    return user.get("company_id") or DEMO_COMPANY_ID


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_week(dt: datetime | None = None) -> str:
    """ISO week ref no formato YYYY-WW. Ex: 2026-W21."""
    dt = dt or _now()
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def _require_manager(user: dict):
    role = (user.get("role") or "").lower()
    if role not in ("gestor", "administrador") and not is_super_admin(user):
        raise HTTPException(403, "Apenas gestor/administrador.")


# =============================================================================
# Veículos
# =============================================================================
class VehicleIn(BaseModel):
    placa: str = Field(..., min_length=4, max_length=10)
    modelo: Optional[str] = None
    marca: Optional[str] = None
    cor: Optional[str] = None
    ano: Optional[int] = None
    tipo: Optional[str] = None  # carro | moto | utilitario
    km_atual: Optional[int] = 0
    current_collaborator_id: Optional[str] = None
    status: str = "ativo"  # ativo | inativo | manutencao | transferido
    weekly_inspection_required: bool = True
    ai_validation_required: bool = True
    observacoes: Optional[str] = None
    ownership: str = "empresa"  # empresa | proprio (do técnico)


@router.get("/vehicles")
async def list_vehicles(
    status: Optional[str] = None,
    collaborator_id: Optional[str] = None,
    placa: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    cid = _cid(user)
    q: dict[str, Any] = {"company_id": cid}
    if status: q["status"] = status
    if collaborator_id: q["current_collaborator_id"] = collaborator_id
    if placa: q["placa"] = {"$regex": placa.upper(), "$options": "i"}
    items = await db.fleet_vehicles.find(q, {"_id": 0}).sort(
        "placa", 1).to_list(500)
    # Enriquecer com nome do colaborador
    collab_ids = {v.get("current_collaborator_id")
                   for v in items if v.get("current_collaborator_id")}
    collabs = {}
    if collab_ids:
        async for c in db.collaborators.find(
                {"id": {"$in": list(collab_ids)}}, {"_id": 0, "id": 1, "name": 1}):
            collabs[c["id"]] = c.get("name")
    for v in items:
        v["current_collaborator_name"] = collabs.get(
            v.get("current_collaborator_id"))
    return {"items": items, "count": len(items)}


@router.post("/vehicles")
async def create_vehicle(
    payload: VehicleIn, user: dict = Depends(get_current_user),
):
    _require_manager(user)
    cid = _cid(user)
    placa = payload.placa.upper().replace("-", "").replace(" ", "")
    existing = await db.fleet_vehicles.find_one(
        {"company_id": cid, "placa": placa})
    if existing:
        raise HTTPException(400, f"Veículo com placa {placa} já cadastrado.")
    doc = {
        "id": f"veh-{uuid.uuid4().hex[:12]}",
        "company_id": cid,
        **payload.dict(),
        "placa": placa,
        "created_at": _now().isoformat(),
        "updated_at": _now().isoformat(),
        "created_by": user.get("name") or user.get("email"),
        "history": [],
    }
    await db.fleet_vehicles.insert_one(doc)
    # Se já vinculado, atualiza colaborador
    if doc.get("current_collaborator_id"):
        await db.collaborators.update_one(
            {"id": doc["current_collaborator_id"]},
            {"$set": {"current_vehicle_id": doc["id"]}},
        )
    doc.pop("_id", None)
    return {"ok": True, "vehicle": doc}


@router.put("/vehicles/{vehicle_id}")
async def update_vehicle(
    vehicle_id: str, payload: VehicleIn,
    user: dict = Depends(get_current_user),
):
    _require_manager(user)
    cid = _cid(user)
    update = payload.dict(exclude_unset=True)
    if "placa" in update:
        update["placa"] = update["placa"].upper().replace("-", "").replace(" ", "")
    update["updated_at"] = _now().isoformat()
    r = await db.fleet_vehicles.update_one(
        {"id": vehicle_id, "company_id": cid}, {"$set": update})
    if r.matched_count == 0:
        raise HTTPException(404, "Veículo não encontrado")
    return {"ok": True}


@router.post("/vehicles/{vehicle_id}/assign")
async def assign_vehicle(
    vehicle_id: str, collaborator_id: str,
    user: dict = Depends(get_current_user),
):
    """Vincula veículo a um colaborador. Desvincula do anterior."""
    _require_manager(user)
    cid = _cid(user)
    veh = await db.fleet_vehicles.find_one(
        {"id": vehicle_id, "company_id": cid}, {"_id": 0})
    if not veh:
        raise HTTPException(404, "Veículo não encontrado")

    prev = veh.get("current_collaborator_id")
    if prev and prev != collaborator_id:
        await db.collaborators.update_one(
            {"id": prev}, {"$set": {"current_vehicle_id": None}})

    await db.fleet_vehicles.update_one(
        {"id": vehicle_id},
        {"$set": {"current_collaborator_id": collaborator_id,
                   "updated_at": _now().isoformat()},
         "$push": {"history": {
             "action": "assign", "to": collaborator_id, "from": prev,
             "at": _now().isoformat(),
             "by": user.get("name") or user.get("email"),
         }}},
    )
    if collaborator_id:
        await db.collaborators.update_one(
            {"id": collaborator_id},
            {"$set": {"current_vehicle_id": vehicle_id,
                       "fleet_block_reason": None}},
        )
    return {"ok": True}


@router.get("/vehicles/{vehicle_id}/kpis")
async def vehicle_kpis(
    vehicle_id: str, user: dict = Depends(get_current_user),
):
    """KPIs individuais de um veículo:
    - Vistorias: total, % aprovadas, score IA médio, última vistoria + histórico
    - Combustível: total no ano, total no mês, média/OS, evolução mensal
    - Transferências: total, pendentes, último romaneio
    - KM: km_atual + variação no último mês
    """
    cid = _cid(user)
    veh = await db.fleet_vehicles.find_one(
        {"id": vehicle_id, "company_id": cid}, {"_id": 0})
    if not veh:
        raise HTTPException(404, "Veículo não encontrado")

    now = _now()
    year_start = datetime(now.year, 1, 1, tzinfo=timezone.utc).isoformat()
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc).isoformat()

    # Vistorias
    insps = await db.fleet_inspections.find(
        {"vehicle_id": vehicle_id, "company_id": cid},
        {"_id": 0, "photos": 0},
    ).sort("requested_at", -1).to_list(200)
    insp_total = len(insps)
    insp_approved = sum(1 for i in insps if i.get("status") == "approved")
    insp_rejected = sum(1 for i in insps if i.get("status") == "rejected")
    scores = [i.get("ai_score") for i in insps if i.get("ai_score")]
    avg_ai = round(sum(scores) / len(scores), 1) if scores else None
    last_insp = insps[0] if insps else None
    pct_approved = round((insp_approved / insp_total * 100), 1) if insp_total else 0

    # Combustível
    fuel_year = await db.fleet_fuel_entries.find(
        {"vehicle_id": vehicle_id, "company_id": cid,
          "created_at": {"$gte": year_start}},
        {"_id": 0},
    ).to_list(200)
    fuel_total_year = sum(f.get("valor_total", 0) for f in fuel_year)
    fuel_month = [f for f in fuel_year
                   if f.get("created_at", "") >= month_start]
    fuel_total_month = sum(f.get("valor_total", 0) for f in fuel_month)
    by_month: dict[str, float] = {}
    for f in fuel_year:
        m = (f.get("month_ref")
              or (f.get("created_at", "") or "")[:7]
              or now.strftime("%Y-%m"))
        by_month[m] = by_month.get(m, 0) + float(f.get("valor_total", 0))
    fuel_series = [{"month": m, "valor": round(v, 2)}
                    for m, v in sorted(by_month.items())]
    total_os = sum(f.get("qtd_os_executadas", 0) or 0 for f in fuel_year)
    avg_per_os = round(fuel_total_year / total_os, 2) if total_os else None

    # Transferências
    txs = await db.fleet_transfers.find(
        {"vehicle_id": vehicle_id, "company_id": cid},
        {"_id": 0},
    ).sort("created_at", -1).to_list(100)
    tx_total = len(txs)
    tx_pending = sum(1 for t in txs if t.get("status") == "pending")
    last_tx = txs[0] if txs else None

    # KM delta
    kms = [(i.get("requested_at"), i.get("km_informado")) for i in insps
            if i.get("km_informado")]
    km_delta_month = None
    if kms and len(kms) >= 2:
        recent = kms[0][1]
        old_month_kms = [k for k in kms if k[0] and k[0] < month_start]
        if old_month_kms and recent:
            km_delta_month = recent - old_month_kms[0][1]

    # Colaborador atual
    collab_name = None
    if veh.get("current_collaborator_id"):
        c = await db.collaborators.find_one(
            {"id": veh["current_collaborator_id"]},
            {"_id": 0, "name": 1, "cpf": 1, "phone": 1, "avatar_data_url": 1})
        if c:
            collab_name = c.get("name")
            veh["current_collaborator_phone"] = c.get("phone")
            veh["current_collaborator_avatar"] = c.get("avatar_data_url")
    veh["current_collaborator_name"] = collab_name

    return {
        "vehicle": veh,
        "inspections": {
            "total": insp_total,
            "approved": insp_approved,
            "rejected": insp_rejected,
            "pct_approved": pct_approved,
            "avg_ai_score": avg_ai,
            "last": {
                "id": last_insp["id"], "week_ref": last_insp.get("week_ref"),
                "status": last_insp.get("status"),
                "ai_score": last_insp.get("ai_score"),
                "requested_at": last_insp.get("requested_at"),
            } if last_insp else None,
            "history": [
                {"id": i["id"], "week_ref": i.get("week_ref"),
                  "status": i.get("status"), "ai_score": i.get("ai_score"),
                  "requested_at": i.get("requested_at"),
                  "km_informado": i.get("km_informado")}
                for i in insps[:12]
            ],
        },
        "fuel": {
            "year_total": round(fuel_total_year, 2),
            "month_total": round(fuel_total_month, 2),
            "avg_per_os": avg_per_os,
            "total_os": total_os,
            "by_month": fuel_series,
            "entries_count": len(fuel_year),
        },
        "transfers": {
            "total": tx_total,
            "pending": tx_pending,
            "last": last_tx,
        },
        "km": {
            "current": veh.get("km_atual"),
            "delta_last_month": km_delta_month,
        },
    }



# =============================================================================
# Vistorias Semanais (5 fotos + IA)
# =============================================================================
class InspectionStartIn(BaseModel):
    vehicle_id: Optional[str] = None  # se vazio, usa o veículo do colab


@router.post("/inspections/start")
async def start_inspection(
    payload: InspectionStartIn = InspectionStartIn(),  # noqa: B008
    user: dict = Depends(get_current_user),
):
    """Técnico inicia a vistoria semanal (ou reutiliza a pendente da semana)."""
    cid = _cid(user)
    collab_id = user.get("collaborator_id") or user.get("id")
    if not collab_id:
        raise HTTPException(400, "Usuário sem collaborator_id")

    collab = await db.collaborators.find_one(
        {"id": collab_id, "company_id": cid}, {"_id": 0})
    if not collab:
        raise HTTPException(404, "Colaborador não encontrado")

    vehicle_id = payload.vehicle_id or collab.get("current_vehicle_id")
    if not vehicle_id:
        raise HTTPException(400, "Sem veículo vinculado a você. "
                                   "Fale com o gestor.")

    week = _iso_week()
    existing = await db.fleet_inspections.find_one(
        {"vehicle_id": vehicle_id, "week_ref": week,
          "collaborator_id": collab_id}, {"_id": 0})
    if existing and existing.get("status") in ("approved",):
        return {"ok": True, "inspection": existing, "already_done": True}
    if existing:
        return {"ok": True, "inspection": existing, "resumed": True}

    doc = {
        "id": f"insp-{uuid.uuid4().hex[:12]}",
        "company_id": cid,
        "vehicle_id": vehicle_id,
        "collaborator_id": collab_id,
        "week_ref": week,
        "requested_at": _now().isoformat(),
        "status": "in_progress",  # in_progress | submitted | approved | rejected
        "photos": {},
        "km_informado": None,
        "ai_score": None,
        "ai_classification": None,
        "ai_alerts": [],
    }
    await db.fleet_inspections.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "inspection": doc}


class PhotoUploadIn(BaseModel):
    position: str  # km | frente | traseira | lat_dir | lat_esq
    data_url: str  # base64
    km_value: Optional[int] = None  # somente quando position=km


@router.post("/inspections/{inspection_id}/upload-photo")
async def upload_inspection_photo(
    inspection_id: str, payload: PhotoUploadIn,
    user: dict = Depends(get_current_user),
):
    cid = _cid(user)
    valid_pos = {"km", "frente", "traseira", "lat_dir", "lat_esq"}
    if payload.position not in valid_pos:
        raise HTTPException(400, f"position inválida. Use: {valid_pos}")
    if not payload.data_url.startswith("data:image"):
        raise HTTPException(400, "data_url deve ser data:image/...")

    update = {
        f"photos.{payload.position}": {
            "data_url": payload.data_url,
            "uploaded_at": _now().isoformat(),
        },
        "updated_at": _now().isoformat(),
    }
    if payload.position == "km" and payload.km_value is not None:
        update["km_informado"] = payload.km_value

    r = await db.fleet_inspections.update_one(
        {"id": inspection_id, "company_id": cid}, {"$set": update})
    if r.matched_count == 0:
        raise HTTPException(404, "Vistoria não encontrada")
    return {"ok": True, "position": payload.position}


@router.post("/inspections/{inspection_id}/submit")
async def submit_inspection(
    inspection_id: str, user: dict = Depends(get_current_user),
):
    """Técnico finaliza a vistoria → dispara IA review em background."""
    cid = _cid(user)
    insp = await db.fleet_inspections.find_one(
        {"id": inspection_id, "company_id": cid}, {"_id": 0})
    if not insp:
        raise HTTPException(404, "Vistoria não encontrada")
    photos = insp.get("photos", {}) or {}
    missing = [p for p in ("km", "frente", "traseira", "lat_dir", "lat_esq")
                if not photos.get(p)]
    if missing:
        raise HTTPException(400,
            f"Faltam as fotos: {', '.join(missing)}")

    await db.fleet_inspections.update_one(
        {"id": inspection_id},
        {"$set": {"status": "submitted",
                   "submitted_at": _now().isoformat()}},
    )
    # Dispara IA em background (best-effort)
    import asyncio
    from services.fleet_ai_worker import review_inspection_async
    asyncio.create_task(review_inspection_async(inspection_id))
    return {"ok": True, "status": "submitted",
            "ai_review": "queued"}


@router.get("/inspections")
async def list_inspections(
    week_ref: Optional[str] = None,
    status: Optional[str] = None,
    collaborator_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    cid = _cid(user)
    q: dict[str, Any] = {"company_id": cid}
    if week_ref: q["week_ref"] = week_ref
    if status: q["status"] = status
    if collaborator_id: q["collaborator_id"] = collaborator_id
    items = await db.fleet_inspections.find(
        q, {"_id": 0, "photos": 0}  # sem fotos no listing (pesado)
    ).sort("requested_at", -1).limit(200).to_list(200)
    return {"items": items, "count": len(items)}


@router.get("/inspections/{inspection_id}")
async def get_inspection(
    inspection_id: str, user: dict = Depends(get_current_user),
):
    cid = _cid(user)
    insp = await db.fleet_inspections.find_one(
        {"id": inspection_id, "company_id": cid}, {"_id": 0})
    if not insp:
        raise HTTPException(404, "Vistoria não encontrada")
    return insp


@router.post("/inspections/{inspection_id}/manual-approve")
async def manual_approve_inspection(
    inspection_id: str, user: dict = Depends(get_current_user),
):
    """Gestor força aprovação (override da IA)."""
    _require_manager(user)
    cid = _cid(user)
    await db.fleet_inspections.update_one(
        {"id": inspection_id, "company_id": cid},
        {"$set": {"status": "approved",
                   "approved_by": user.get("name"),
                   "approved_at": _now().isoformat(),
                   "manual_override": True}},
    )
    return {"ok": True}


# =============================================================================
# Can-operate (regra mestre — checa se técnico pode operar OS)
# =============================================================================
@router.get("/me/can-operate")
async def me_can_operate(user: dict = Depends(get_current_user)):
    """Retorna se o colaborador atual pode operar OS.

    SEMPRE retorna ok=True (modo "aviso suave" — escolha 2c do usuário).
    Mas inclui `banner`/`warnings` que o frontend mobile exibe.
    """
    cid = _cid(user)
    collab_id = user.get("collaborator_id") or user.get("id")
    if not collab_id:
        return {"ok": True, "fleet_enabled": False}

    collab = await db.collaborators.find_one(
        {"id": collab_id, "company_id": cid}, {"_id": 0})
    if not collab or not collab.get("requires_vehicle"):
        return {"ok": True, "fleet_enabled": False}

    warnings: List[dict] = []
    vehicle_id = collab.get("current_vehicle_id")
    if not vehicle_id:
        warnings.append({
            "code": "no_vehicle", "severity": "alert",
            "msg": "Você não tem veículo registrado. Procure o gestor.",
        })
        return {"ok": True, "fleet_enabled": True, "warnings": warnings,
                "blocked": False}

    week = _iso_week()
    insp = await db.fleet_inspections.find_one(
        {"vehicle_id": vehicle_id, "week_ref": week,
          "collaborator_id": collab_id}, {"_id": 0, "photos": 0})

    if not insp or insp.get("status") not in ("approved", "submitted"):
        warnings.append({
            "code": "inspection_pending", "severity": "warn",
            "msg": "Vistoria semanal do veículo pendente — primeira bolha do dia.",
            "inspection_id": (insp or {}).get("id"),
            "week_ref": week,
        })
    elif insp.get("status") == "rejected":
        warnings.append({
            "code": "inspection_rejected", "severity": "alert",
            "msg": "Vistoria desta semana foi recusada pela IA. Refaça.",
            "inspection_id": insp.get("id"),
            "alerts": insp.get("ai_alerts", []),
        })

    if collab.get("fleet_block_reason"):
        warnings.append({
            "code": collab["fleet_block_reason"], "severity": "alert",
            "msg": "Bloqueio de frota ativo.",
        })

    return {
        "ok": True, "fleet_enabled": True,
        "vehicle_id": vehicle_id, "week_ref": week,
        "warnings": warnings, "blocked": False,
    }


# =============================================================================
# KPIs
# =============================================================================
@router.get("/kpis")
async def fleet_kpis(user: dict = Depends(get_current_user)):
    cid = _cid(user)
    week = _iso_week()

    # Veículos
    veh_total = await db.fleet_vehicles.count_documents({"company_id": cid})
    veh_active = await db.fleet_vehicles.count_documents(
        {"company_id": cid, "status": "ativo"})
    veh_inactive = await db.fleet_vehicles.count_documents(
        {"company_id": cid, "status": "inativo"})
    veh_maintenance = await db.fleet_vehicles.count_documents(
        {"company_id": cid, "status": "manutencao"})

    # Colaboradores
    collab_with_v = await db.collaborators.count_documents(
        {"company_id": cid, "current_vehicle_id": {"$ne": None}})
    collab_required = await db.collaborators.count_documents(
        {"company_id": cid, "requires_vehicle": True})
    collab_missing = await db.collaborators.count_documents(
        {"company_id": cid, "requires_vehicle": True,
          "$or": [{"current_vehicle_id": None},
                   {"current_vehicle_id": {"$exists": False}}]})

    # Vistorias semana atual
    insp_this_week = await db.fleet_inspections.find(
        {"company_id": cid, "week_ref": week},
        {"_id": 0, "status": 1, "ai_score": 1},
    ).to_list(2000)
    insp_done = sum(1 for i in insp_this_week
                     if i.get("status") in ("approved", "submitted"))
    insp_rejected = sum(1 for i in insp_this_week
                         if i.get("status") == "rejected")
    pct_done = round((insp_done / collab_required * 100), 1) \
        if collab_required else 0
    avg_score = None
    scores = [i.get("ai_score") for i in insp_this_week if i.get("ai_score")]
    if scores:
        avg_score = round(sum(scores) / len(scores), 1)

    # Transferências
    transfers_pending = await db.fleet_transfers.count_documents(
        {"company_id": cid, "status": "pending"})
    transfers_month = await db.fleet_transfers.count_documents(
        {"company_id": cid,
          "created_at": {"$gte": (_now() - timedelta(days=30)).isoformat()}})

    # Combustível
    month_ref = _now().strftime("%Y-%m")
    fuel_entries = await db.fleet_fuel_entries.find(
        {"company_id": cid, "month_ref": month_ref}, {"_id": 0},
    ).to_list(500)
    total_fuel = sum(f.get("valor_total", 0) for f in fuel_entries)
    avg_fuel_per_os = None
    if fuel_entries:
        with_os = [f for f in fuel_entries if f.get("qtd_os_executadas")]
        if with_os:
            avg_fuel_per_os = round(
                sum(f["valor_total"] / f["qtd_os_executadas"]
                     for f in with_os) / len(with_os), 2)

    # ── Rankings inteligentes (top 5 problemáticos vs top 5 econômicos) ──
    # Top veículos por custo combustível no mês corrente
    fuel_by_veh: dict[str, dict] = {}
    for f in fuel_entries:
        vid = f.get("vehicle_id")
        if not vid:
            continue
        d = fuel_by_veh.setdefault(vid, {"total": 0.0, "os": 0})
        d["total"] += float(f.get("valor_total", 0))
        d["os"] += int(f.get("qtd_os_executadas") or 0)

    # Buscar placas para enriquecer
    placas: dict[str, str] = {}
    if fuel_by_veh:
        veh_docs = await db.fleet_vehicles.find(
            {"id": {"$in": list(fuel_by_veh.keys())}, "company_id": cid},
            {"_id": 0, "id": 1, "placa": 1, "modelo": 1},
        ).to_list(200)
        placas = {v["id"]: (v.get("placa") or "—") for v in veh_docs}

    fuel_rank = sorted(
        [
            {
                "vehicle_id": vid,
                "placa": placas.get(vid, vid[-6:]),
                "total": round(d["total"], 2),
                "os": d["os"],
                "per_os": round(d["total"] / d["os"], 2) if d["os"] else None,
            }
            for vid, d in fuel_by_veh.items()
        ],
        key=lambda x: x["total"], reverse=True,
    )

    # Top veículos com mais vistorias recusadas (90 dias)
    cutoff_90 = (_now() - timedelta(days=90)).isoformat()
    insp_rej_by_veh: dict[str, int] = {}
    rejected_docs = await db.fleet_inspections.find(
        {"company_id": cid, "status": "rejected",
          "requested_at": {"$gte": cutoff_90}},
        {"_id": 0, "vehicle_id": 1, "ai_score": 1},
    ).to_list(500)
    for r in rejected_docs:
        vid = r.get("vehicle_id")
        if vid:
            insp_rej_by_veh[vid] = insp_rej_by_veh.get(vid, 0) + 1

    # Carregar placas adicionais
    new_ids = [vid for vid in insp_rej_by_veh if vid not in placas]
    if new_ids:
        veh_extra = await db.fleet_vehicles.find(
            {"id": {"$in": new_ids}, "company_id": cid},
            {"_id": 0, "id": 1, "placa": 1},
        ).to_list(200)
        for v in veh_extra:
            placas[v["id"]] = v.get("placa") or "—"

    rejected_rank = sorted(
        [
            {"vehicle_id": vid, "placa": placas.get(vid, vid[-6:]),
             "count": cnt}
            for vid, cnt in insp_rej_by_veh.items()
        ],
        key=lambda x: x["count"], reverse=True,
    )

    return {
        "week_ref": week, "month_ref": month_ref,
        "vehicles": {
            "total": veh_total, "active": veh_active,
            "inactive": veh_inactive, "maintenance": veh_maintenance,
        },
        "collaborators": {
            "with_vehicle": collab_with_v,
            "required": collab_required,
            "missing_vehicle": collab_missing,
        },
        "inspections_week": {
            "expected": collab_required,
            "done": insp_done,
            "rejected": insp_rejected,
            "pct_done": pct_done,
            "avg_ai_score": avg_score,
        },
        "transfers": {
            "pending": transfers_pending,
            "this_month": transfers_month,
        },
        "fuel": {
            "month_total": round(total_fuel, 2),
            "avg_per_os": avg_fuel_per_os,
            "entries_count": len(fuel_entries),
        },
        "rankings": {
            "top_fuel_cost": fuel_rank[:5],
            "top_rejected_inspections": rejected_rank[:5],
        },
    }


# =============================================================================
# Combustível (lançamento manual + OCR)
# =============================================================================
class FuelEntryIn(BaseModel):
    vehicle_id: str
    collaborator_id: Optional[str] = None
    month_ref: str  # YYYY-MM
    valor_total: float = Field(..., gt=0)
    qtd_os_executadas: Optional[int] = None
    observacoes: Optional[str] = None
    receipt_data_url: Optional[str] = None  # foto da NF


@router.get("/fuel")
async def list_fuel(
    month: Optional[str] = None,
    collaborator_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    cid = _cid(user)
    q: dict[str, Any] = {"company_id": cid}
    if month: q["month_ref"] = month
    if collaborator_id: q["collaborator_id"] = collaborator_id
    if vehicle_id: q["vehicle_id"] = vehicle_id
    items = await db.fleet_fuel_entries.find(q, {"_id": 0}).sort(
        "month_ref", -1).limit(200).to_list(200)
    return {"items": items, "count": len(items)}


@router.post("/fuel")
async def create_fuel(
    payload: FuelEntryIn, user: dict = Depends(get_current_user),
):
    _require_manager(user)
    cid = _cid(user)

    # Se qtd_os não informada, calcula auto via tickets fechados no mês
    qtd = payload.qtd_os_executadas
    if qtd is None and payload.collaborator_id:
        y, m = payload.month_ref.split("-")
        start = datetime(int(y), int(m), 1, tzinfo=timezone.utc)
        end_m = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        qtd = await db.tickets.count_documents({
            "company_id": cid,
            "assigned_collaborator_id": payload.collaborator_id,
            "status": "finalizada",
            "closed_at": {"$gte": start.isoformat(),
                            "$lt": end_m.isoformat()},
        })

    media = round(payload.valor_total / qtd, 2) if qtd else None
    doc = {
        "id": f"fuel-{uuid.uuid4().hex[:12]}",
        "company_id": cid,
        **payload.dict(),
        "qtd_os_executadas": qtd or 0,
        "media_por_os": media,
        "created_at": _now().isoformat(),
        "created_by": user.get("name") or user.get("email"),
    }
    await db.fleet_fuel_entries.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "fuel": doc}


# =============================================================================
# Import de CSV TicketLog (Edenred) — bulk fuel entries
# =============================================================================
class TicketLogImportIn(BaseModel):
    csv_content: str
    delimiter: str = ";"
    encoding_hint: str = "utf-8"
    dry_run: bool = True


def _parse_ticketlog_csv(content: str, delimiter: str = ";"):
    """Parser tolerante para extratos TicketLog/Edenred."""
    import csv
    import io as _io
    import re as _re

    rows: list[dict] = []
    errors: list[str] = []

    try:
        reader = csv.reader(_io.StringIO(content), delimiter=delimiter)
        all_rows = list(reader)
    except Exception as e:
        return [], [f"Falha ao ler CSV: {e}"], None

    if not all_rows or len(all_rows) < 2:
        return [], ["CSV vazio ou sem cabeçalho"], None

    # Detecta linha de header
    header_idx = 0
    for i, r in enumerate(all_rows[:5]):
        if len(r) >= 5 and not any(c.replace(".", "").replace(",", "").isdigit()
                                     for c in r if c):
            header_idx = i
            break

    headers = [h.strip().lower() for h in all_rows[header_idx]]
    data_rows = all_rows[header_idx + 1:]

    def find_col(*names):
        """Itera por NOMES (do mais específico ao mais genérico) e retorna
        a primeira coluna que dá match para aquele nome. Isso garante que
        'valor total' tenha prioridade sobre 'valor' (que casaria com
        'Valor Unitario')."""
        for n in names:
            nl = n.lower()
            for i, h in enumerate(headers):
                if nl in h:
                    return i
        return None

    col_placa = find_col("placa")
    col_data = find_col("data trans", "data abast", "data ", "data")
    col_valor = find_col("valor total", "valor", "total")
    col_litros = find_col("quantidade", "litros", "qtd")
    col_combustivel = find_col("combust", "produto")
    col_posto = find_col("estabelecimento", "posto", "razao")
    col_cidade = find_col("cidade", "municip")
    col_km = find_col("hodom", "km ", "km")
    col_motorista = find_col("motorista", "condutor")

    if col_placa is None or col_valor is None:
        return [], [f"Colunas obrigatórias não encontradas. Cabeçalhos: {headers}"], None

    def _num(s):
        if s is None:
            return 0.0
        s = str(s).strip().replace("R$", "").replace(" ", "")
        if not s:
            return 0.0
        if "," in s and ("." in s or len(s.split(",")[-1]) <= 2):
            s = s.replace(".", "").replace(",", ".")
        try:
            return float(s)
        except Exception:
            return 0.0

    def _placa_norm(p):
        if not p:
            return ""
        return _re.sub(r"[^A-Z0-9]", "", p.strip().upper())

    for line_no, r in enumerate(data_rows, start=header_idx + 2):
        if not any(r):
            continue
        if len(r) < len(headers):
            r = r + [""] * (len(headers) - len(r))
        try:
            placa = _placa_norm(r[col_placa])
            valor = _num(r[col_valor])
            if not placa or valor <= 0:
                continue
            entry = {
                "placa": placa,
                "data": (r[col_data] if col_data is not None else "").strip(),
                "valor_total": valor,
                "litros": _num(r[col_litros]) if col_litros is not None else None,
                "combustivel": (r[col_combustivel] or "").strip()
                                if col_combustivel is not None else None,
                "posto": (r[col_posto] or "").strip()
                          if col_posto is not None else None,
                "cidade": (r[col_cidade] or "").strip()
                           if col_cidade is not None else None,
                "km": int(_num(r[col_km])) if col_km is not None and r[col_km] else None,
                "motorista": (r[col_motorista] or "").strip()
                              if col_motorista is not None else None,
                "_line": line_no,
            }
            rows.append(entry)
        except Exception as e:
            errors.append(f"Linha {line_no}: {e}")

    return rows, errors, {
        "header_row": header_idx + 1,
        "cols_found": {
            "placa": col_placa, "data": col_data, "valor": col_valor,
            "litros": col_litros, "combustivel": col_combustivel,
            "posto": col_posto, "cidade": col_cidade, "km": col_km,
            "motorista": col_motorista,
        },
    }


@router.post("/fuel/import-csv")
async def import_fuel_csv(
    payload: TicketLogImportIn, user: dict = Depends(get_current_user),
):
    """Importa extrato CSV da TicketLog/Edenred."""
    _require_manager(user)
    cid = _cid(user)

    rows, errors, meta = _parse_ticketlog_csv(
        payload.csv_content, delimiter=payload.delimiter)

    veh_docs = await db.fleet_vehicles.find(
        {"company_id": cid}, {"_id": 0, "id": 1, "placa": 1},
    ).to_list(500)
    placa_to_id = {(v.get("placa") or "").upper().replace("-", ""): v["id"]
                    for v in veh_docs}

    # ── Detecção de anomalias ────────────────────────────────────────────
    # 1. Calcula média R$/L por combustível (para detectar preço fora)
    price_by_fuel: dict = {}
    for r in rows:
        if r.get("combustivel") and r.get("litros") and r["litros"] > 0:
            fuel = r["combustivel"]
            ppl = r["valor_total"] / r["litros"]
            price_by_fuel.setdefault(fuel, []).append(ppl)
    avg_price_by_fuel = {
        fuel: sum(p) / len(p) for fuel, p in price_by_fuel.items()
    }

    # 2. Agrupa por (placa, data) p/ detectar abastecimento duplicado/dia
    by_placa_day: dict = {}
    for r in rows:
        # Normaliza data → YYYY-MM-DD
        dstr = (r.get("data") or "").split()[0]
        day_key = None
        for sep in ("/", "-"):
            if sep in dstr:
                parts = dstr.split(sep)
                if len(parts) == 3:
                    if len(parts[0]) == 4:
                        day_key = f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
                    elif len(parts[2]) == 4:
                        day_key = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                break
        if day_key:
            by_placa_day.setdefault((r["placa"], day_key), []).append(r)

    # 3. Marca cada row com lista de alertas
    alerts_summary: dict[str, int] = {}
    for r in rows:
        r["_alerts"] = []
        # 3.1 — Preço acima de 30% da média do combustível
        if r.get("combustivel") and r.get("litros") and r["litros"] > 0:
            avg = avg_price_by_fuel.get(r["combustivel"])
            if avg and avg > 0:
                ppl = r["valor_total"] / r["litros"]
                if ppl > avg * 1.30:
                    r["_alerts"].append({
                        "type": "preco_alto",
                        "severity": "high",
                        "msg": (f"R${ppl:.2f}/L · "
                                  f"{((ppl/avg - 1) * 100):.0f}% acima da média "
                                  f"({r['combustivel']} R${avg:.2f}/L)"),
                    })
                    alerts_summary["preco_alto"] = alerts_summary.get("preco_alto", 0) + 1
        # 3.2 — Volume incomum (> 100L numa abastecida = caminhão; >80L carro)
        if r.get("litros") and r["litros"] > 100:
            r["_alerts"].append({
                "type": "volume_alto",
                "severity": "medium",
                "msg": f"{r['litros']:.1f} L numa única abastecida",
            })
            alerts_summary["volume_alto"] = alerts_summary.get("volume_alto", 0) + 1

    # 3.3 — Múltiplos abastecimentos no mesmo dia (mesma placa)
    for (placa, day), grp in by_placa_day.items():
        if len(grp) >= 2:
            # Diferentes postos = mais suspeito
            distinct_postos = len({(g.get("posto") or "") for g in grp})
            for r in grp:
                r["_alerts"].append({
                    "type": "abastecimento_duplo",
                    "severity": "high" if distinct_postos >= 2 else "medium",
                    "msg": (f"{len(grp)} abastecimentos em {day}"
                              + (f" em {distinct_postos} postos diferentes"
                                 if distinct_postos >= 2 else "")),
                })
            alerts_summary["abastecimento_duplo"] = (
                alerts_summary.get("abastecimento_duplo", 0) + 1)

    # 3.4 — Hodômetro retrograde (KM informado menor que anterior do mesmo veículo)
    by_placa = {}
    for r in rows:
        if r.get("km"):
            by_placa.setdefault(r["placa"], []).append(r)
    for placa, lst in by_placa.items():
        lst.sort(key=lambda x: x.get("_line", 0))
        prev_km = None
        for r in lst:
            if prev_km is not None and r["km"] < prev_km - 50:  # tolerância 50km
                r["_alerts"].append({
                    "type": "km_retrograde",
                    "severity": "high",
                    "msg": f"KM {r['km']} < anterior {prev_km} (regressão)",
                })
                alerts_summary["km_retrograde"] = alerts_summary.get("km_retrograde", 0) + 1
            if r["km"] > 0:
                prev_km = r["km"]

    # Lista de transações com alertas (top 20 mais críticas)
    flagged = [r for r in rows if r.get("_alerts")]
    flagged.sort(key=lambda x: (
        -max([{"high": 3, "medium": 2, "low": 1}.get(a["severity"], 0)
              for a in x["_alerts"]] or [0]),
        -x["valor_total"],
    ))
    flagged_preview = [
        {
            "placa": r["placa"], "data": r["data"],
            "valor_total": r["valor_total"], "posto": r.get("posto"),
            "combustivel": r.get("combustivel"), "litros": r.get("litros"),
            "km": r.get("km"), "motorista": r.get("motorista"),
            "alerts": r["_alerts"],
        }
        for r in flagged[:20]
    ]
    # ─────────────────────────────────────────────────────────────────────

    grouped: dict = {}
    unmatched: list = []
    for r in rows:
        veh_id = placa_to_id.get(r["placa"])
        if not veh_id:
            unmatched.append(r)
            continue
        month = None
        dstr = r.get("data") or ""
        for sep in ("/", "-"):
            if sep in dstr:
                parts = dstr.split()[0].split(sep)
                if len(parts) == 3:
                    if len(parts[0]) == 4:
                        month = f"{parts[0]}-{parts[1].zfill(2)}"
                    elif len(parts[2]) == 4:
                        month = f"{parts[2]}-{parts[1].zfill(2)}"
                break
        if not month:
            month = _now().strftime("%Y-%m")

        key = (veh_id, month)
        g = grouped.setdefault(key, {
            "vehicle_id": veh_id, "placa": r["placa"], "month_ref": month,
            "valor_total": 0.0, "litros": 0.0, "transactions": 0,
            "postos": set(), "combustiveis": set(),
        })
        g["valor_total"] += r["valor_total"]
        g["litros"] += (r.get("litros") or 0)
        g["transactions"] += 1
        if r.get("posto"):
            g["postos"].add(r["posto"])
        if r.get("combustivel"):
            g["combustiveis"].add(r["combustivel"])

    preview = [
        {**g, "postos": sorted(g["postos"])[:3],
              "combustiveis": sorted(g["combustiveis"])[:3],
              "valor_total": round(g["valor_total"], 2),
              "litros": round(g["litros"], 2)}
        for g in grouped.values()
    ]
    preview.sort(key=lambda x: (-x["valor_total"], x["placa"]))

    result = {
        "ok": True,
        "dry_run": payload.dry_run,
        "meta": meta,
        "total_rows_parsed": len(rows),
        "total_entries_to_create": len(grouped),
        "preview": preview[:50],
        "unmatched_placas": sorted({u["placa"] for u in unmatched})[:20],
        "unmatched_count": len(unmatched),
        "errors": errors[:10],
        "anomalies": {
            "summary": alerts_summary,
            "total_flagged": len(flagged),
            "transactions": flagged_preview,
        },
    }

    if payload.dry_run:
        return result

    created = 0
    for g in grouped.values():
        veh = await db.fleet_vehicles.find_one(
            {"id": g["vehicle_id"]}, {"_id": 0, "current_collaborator_id": 1})
        qtd_os = 0
        if veh and veh.get("current_collaborator_id"):
            y, m = g["month_ref"].split("-")
            start = datetime(int(y), int(m), 1, tzinfo=timezone.utc)
            end_m = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            qtd_os = await db.tickets.count_documents({
                "company_id": cid,
                "assigned_collaborator_id": veh["current_collaborator_id"],
                "status": "finalizada",
                "closed_at": {"$gte": start.isoformat(),
                                "$lt": end_m.isoformat()},
            })
        media = round(g["valor_total"] / qtd_os, 2) if qtd_os else None
        obs_parts = [f"TicketLog · {g['transactions']} transação(ões)"]
        if g.get("postos"):
            obs_parts.append("Postos: " + ", ".join(sorted(g["postos"])[:2]))
        if g.get("litros"):
            obs_parts.append(f"{round(g['litros'], 2)} L")
        await db.fleet_fuel_entries.insert_one({
            "id": f"fuel-{uuid.uuid4().hex[:12]}",
            "company_id": cid,
            "vehicle_id": g["vehicle_id"],
            "collaborator_id": (veh or {}).get("current_collaborator_id"),
            "month_ref": g["month_ref"],
            "valor_total": round(g["valor_total"], 2),
            "qtd_os_executadas": qtd_os or 0,
            "media_por_os": media,
            "observacoes": " · ".join(obs_parts),
            "source": "ticketlog_csv",
            "import_meta": {
                "litros": round(g["litros"], 2),
                "transactions": g["transactions"],
            },
            "created_at": _now().isoformat(),
            "created_by": user.get("name") or user.get("email"),
        })
        created += 1
    result["created"] = created
    return result



class FuelOcrIn(BaseModel):
    receipt_data_url: str


@router.post("/fuel/ocr")
async def fuel_ocr(
    payload: FuelOcrIn, user: dict = Depends(get_current_user),
):
    """OCR de NF do posto — extrai valor automaticamente via Claude vision."""
    _require_manager(user)
    try:
        from services.fleet_ai_worker import ocr_fuel_receipt
        result = await ocr_fuel_receipt(payload.receipt_data_url)
        return {"ok": True, **result}
    except Exception as e:
        logger.warning("[fleet.fuel.ocr] %s", e)
        return {"ok": False, "error": str(e)}


# =============================================================================
# Transferências (Romaneio)
# =============================================================================
class TransferIn(BaseModel):
    vehicle_id: str
    to_collaborator_id: str
    km_transfer: int
    observacoes: Optional[str] = None


@router.get("/transfers")
async def list_transfers(
    status: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    cid = _cid(user)
    q: dict[str, Any] = {"company_id": cid}
    if status: q["status"] = status
    items = await db.fleet_transfers.find(
        q, {"_id": 0}).sort("created_at", -1).limit(100).to_list(100)
    return {"items": items, "count": len(items)}


@router.post("/transfers")
async def create_transfer(
    payload: TransferIn, user: dict = Depends(get_current_user),
):
    _require_manager(user)
    cid = _cid(user)
    veh = await db.fleet_vehicles.find_one(
        {"id": payload.vehicle_id, "company_id": cid}, {"_id": 0})
    if not veh:
        raise HTTPException(404, "Veículo não encontrado")
    doc = {
        "id": f"tx-{uuid.uuid4().hex[:12]}",
        "company_id": cid,
        "vehicle_id": payload.vehicle_id,
        "vehicle_placa": veh.get("placa"),
        "from_collaborator_id": veh.get("current_collaborator_id"),
        "to_collaborator_id": payload.to_collaborator_id,
        "km_transfer": payload.km_transfer,
        "observacoes": payload.observacoes,
        "photos": [],
        "signature_data_url": None,
        "status": "pending",  # pending | accepted | approved | rejected
        "created_at": _now().isoformat(),
        "created_by": user.get("name") or user.get("email"),
    }
    await db.fleet_transfers.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "transfer": doc}


class TransferSignIn(BaseModel):
    signature_data_url: str  # canvas signature do colaborador


@router.post("/transfers/{tx_id}/sign")
async def sign_transfer(
    tx_id: str, payload: TransferSignIn,
    user: dict = Depends(get_current_user),
):
    """Colaborador receptor assina o aceite via canvas no app."""
    cid = _cid(user)
    tx = await db.fleet_transfers.find_one(
        {"id": tx_id, "company_id": cid}, {"_id": 0})
    if not tx:
        raise HTTPException(404, "Transferência não encontrada")
    collab_id = user.get("collaborator_id") or user.get("id")
    if tx.get("to_collaborator_id") != collab_id and not is_super_admin(user):
        # Permite gestor assinar pelo técnico em casos excepcionais
        role = (user.get("role") or "").lower()
        if role not in ("gestor", "administrador"):
            raise HTTPException(403, "Apenas o colaborador receptor pode assinar.")
    await db.fleet_transfers.update_one(
        {"id": tx_id},
        {"$set": {"signature_data_url": payload.signature_data_url,
                   "signed_at": _now().isoformat(),
                   "signed_by": collab_id,
                   "status": "accepted"}},
    )
    return {"ok": True}


@router.post("/transfers/{tx_id}/approve")
async def approve_transfer(
    tx_id: str, user: dict = Depends(get_current_user),
):
    """Gestor aprova → atualiza vehicle.current_collaborator_id."""
    _require_manager(user)
    cid = _cid(user)
    tx = await db.fleet_transfers.find_one(
        {"id": tx_id, "company_id": cid}, {"_id": 0})
    if not tx:
        raise HTTPException(404, "Transferência não encontrada")
    if tx.get("status") != "accepted":
        raise HTTPException(400,
            "Aguardando assinatura do colaborador receptor.")
    # Desvincula do anterior + vincula no novo
    if tx.get("from_collaborator_id"):
        await db.collaborators.update_one(
            {"id": tx["from_collaborator_id"]},
            {"$set": {"current_vehicle_id": None}})
    await db.collaborators.update_one(
        {"id": tx["to_collaborator_id"]},
        {"$set": {"current_vehicle_id": tx["vehicle_id"]}})
    await db.fleet_vehicles.update_one(
        {"id": tx["vehicle_id"]},
        {"$set": {"current_collaborator_id": tx["to_collaborator_id"],
                   "km_atual": tx.get("km_transfer", 0),
                   "updated_at": _now().isoformat()},
         "$push": {"history": {
             "action": "transfer", "transfer_id": tx_id,
             "from": tx.get("from_collaborator_id"),
             "to": tx["to_collaborator_id"],
             "at": _now().isoformat(),
             "approved_by": user.get("name"),
         }}},
    )
    await db.fleet_transfers.update_one(
        {"id": tx_id},
        {"$set": {"status": "approved",
                   "approved_by": user.get("name"),
                   "approved_at": _now().isoformat()}},
    )
    return {"ok": True}



# =============================================================================
# PDF do romaneio (mesmo padrão visual do collaborator_assets.py)
# =============================================================================
def _pt_br_date(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        if isinstance(iso, datetime):
            dt = iso
        else:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return iso[:10] if isinstance(iso, str) else "—"


def _build_fleet_transfer_pdf(
    branding: dict, vehicle: dict, transfer: dict,
    from_collab: dict | None, to_collab: dict | None,
) -> bytes:
    """PDF do romaneio de transferência de veículo — mesmo padrão visual
    do romaneio de custódia (`collaborator_assets._build_romaneio_pdf`).

    Estrutura:
    - Header com logo + razão social (matriz ou praça)
    - Título "ROMANEIO DE TRANSFERÊNCIA DE VEÍCULO"
    - Bloco com dados do veículo (placa, marca/modelo, ano, cor, km)
    - Bloco origem → destino (colaboradores, CPF, data)
    - Tabela checklist do veículo (5 itens: estepe, macaco, chave de roda,
      documentos, óleo) com checkbox para o gestor marcar fisicamente.
    - Observações da transferência
    - Termo de responsabilidade
    - 3 linhas de assinatura: técnico ENTREGANDO + técnico RECEBENDO
      (embute assinatura digital se houver) + GESTOR (aprovação)
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (Image as RLImage, Paragraph,
                                     SimpleDocTemplate, Spacer, Table, TableStyle)
    from reportlab.graphics.shapes import Drawing, Rect

    def _checkbox():
        d = Drawing(14, 14)
        d.add(Rect(1, 1, 12, 12, strokeColor=colors.HexColor("#0f172a"),
                    fillColor=colors.white, strokeWidth=1.2))
        return d

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.2 * cm, bottomMargin=1.2 * cm,
        title=f"SmartProv — Romaneio Transferência {vehicle.get('placa') or ''}",
        author="SmartProv", creator="SmartProv",
        subject="Romaneio de Transferência de Veículo",
    )
    styles = getSampleStyleSheet()
    story: list = []

    # ---- Header logo + empresa ----
    logo_url = (branding or {}).get("logo_data_url") or ""
    if logo_url and logo_url.startswith("data:image/"):
        try:
            import base64
            b64 = logo_url.split(",", 1)[1]
            logo_io = io.BytesIO(base64.b64decode(b64))
            header_left = RLImage(logo_io, width=3.5 * cm, height=3.5 * cm,
                                   kind="proportional")
        except Exception:
            header_left = Paragraph("<b>LOGO</b>", styles["Normal"])
    else:
        header_left = Paragraph("<b>LOGO</b>", styles["Normal"])

    company_lines = [f"<b>{branding.get('company_name') or 'Empresa'}</b>"]
    if branding.get("cnpj"):
        company_lines.append(f"CNPJ: {branding['cnpj']}")
    addr_parts = [branding.get("address"), branding.get("city"),
                   branding.get("state"), branding.get("zip_code")]
    addr_line = " · ".join([p for p in addr_parts if p])
    if addr_line:
        company_lines.append(addr_line)
    contact = " · ".join([p for p in [branding.get("phone"),
                                        branding.get("email"),
                                        branding.get("website")] if p])
    if contact:
        company_lines.append(contact)
    company_par = Paragraph(
        "<br/>".join(company_lines),
        ParagraphStyle("c", parent=styles["Normal"], fontSize=10, leading=13),
    )
    header_t = Table([[header_left, company_par]], colWidths=[4 * cm, None])
    header_t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "LEFT"),
    ]))
    story.append(header_t)
    story.append(Spacer(1, 0.4 * cm))

    # ---- Title ----
    story.append(Paragraph(
        "<b>ROMANEIO DE TRANSFERÊNCIA DE VEÍCULO</b>",
        ParagraphStyle("title", parent=styles["Normal"], fontSize=13,
                       alignment=1, leading=16, spaceAfter=4,
                       textColor=colors.HexColor("#0b1220"))))
    story.append(Paragraph(
        "<font color='#0d9488'>Frota da empresa · Termo de transferência de custódia</font>",
        ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=9,
                       alignment=1, leading=12, spaceAfter=10)))
    story.append(Spacer(1, 0.2 * cm))

    # ---- Veículo block ----
    vh_html = (
        f"<b>Placa:</b> <font face='Courier-Bold'>{vehicle.get('placa') or '—'}</font> &nbsp;&nbsp; "
        f"<b>Marca/Modelo:</b> {vehicle.get('marca') or '—'} {vehicle.get('modelo') or ''} &nbsp;&nbsp; "
        f"<b>Ano:</b> {vehicle.get('ano') or '—'}<br/>"
        f"<b>Cor:</b> {vehicle.get('cor') or '—'} &nbsp;&nbsp; "
        f"<b>Tipo:</b> {(vehicle.get('tipo') or 'carro').upper()} &nbsp;&nbsp; "
        f"<b>KM no momento:</b> {transfer.get('km_transfer') or 0} km<br/>"
        f"<b>Romaneio nº:</b> <font face='Courier'>{transfer.get('id')}</font> &nbsp;&nbsp; "
        f"<b>Emitido em:</b> {_pt_br_date(transfer.get('created_at'))}"
    )
    story.append(Paragraph(
        vh_html,
        ParagraphStyle("v", parent=styles["Normal"], fontSize=10, leading=14,
                       backColor=colors.HexColor("#f1f5f9"),
                       borderColor=colors.HexColor("#cbd5e1"),
                       borderWidth=0.5, borderPadding=8)))
    story.append(Spacer(1, 0.3 * cm))

    # ---- Colaboradores: De → Para ----
    fr_name = (from_collab or {}).get("name") or "—"
    fr_cpf = (from_collab or {}).get("cpf") or "—"
    to_name = (to_collab or {}).get("name") or "—"
    to_cpf = (to_collab or {}).get("cpf") or "—"
    parties_html = (
        f"<b>DE (entrega):</b> {fr_name} &nbsp;&nbsp; <b>CPF:</b> {fr_cpf}<br/>"
        f"<b>PARA (recebe):</b> {to_name} &nbsp;&nbsp; <b>CPF:</b> {to_cpf}"
    )
    story.append(Paragraph(parties_html,
        ParagraphStyle("p", parent=styles["Normal"], fontSize=10, leading=14)))
    story.append(Spacer(1, 0.3 * cm))

    # ---- Checklist do veículo (gestor marca fisicamente na conferência) ----
    checklist_head = ["Conferido", "#", "Item", "Estado / Observação"]
    checklist_rows = [
        (1, "Estepe", "Presente e em estado de uso"),
        (2, "Macaco + chave de roda", "Acompanha o veículo"),
        (3, "Documentação (CRLV)", "Em dia e dentro do prazo"),
        (4, "Nível de óleo e arrefecimento", "Verificado"),
        (5, "Combustível", f"Marcador no momento da transferência"),
        (6, "Lataria / pintura", "Sem novas avarias além do registrado"),
        (7, "Pneus", "Banda de rodagem aceitável"),
    ]
    data = [checklist_head] + [
        [_checkbox(), str(n), item, obs]
        for n, item, obs in checklist_rows
    ]
    ck = Table(data, repeatRows=1,
                colWidths=[1.8 * cm, 0.8 * cm, 5.5 * cm, None])
    ck.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#fef3c7")),
    ]))
    story.append(ck)
    story.append(Spacer(1, 0.4 * cm))

    # ---- Observações ----
    obs = transfer.get("observacoes") or ""
    if obs:
        story.append(Paragraph(
            f"<b>Observações:</b> {obs}",
            ParagraphStyle("o", parent=styles["Normal"], fontSize=9,
                           leading=12)))
        story.append(Spacer(1, 0.3 * cm))

    # ---- Termo ----
    termo = (branding.get("romaneio_footer")
              or "Declaro ter recebido o veículo acima identificado em "
                  "perfeito estado de uso e conservação, comprometendo-me "
                  "a zelar por sua guarda, manutenção preventiva, "
                  "documentação em dia e devolução em caso de "
                  "desligamento, sob pena das medidas cabíveis.")
    story.append(Paragraph(
        f"<b>TERMO DE RESPONSABILIDADE:</b> {termo}",
        ParagraphStyle("foot", parent=styles["Normal"], fontSize=9,
                       leading=13, alignment=4)))
    story.append(Spacer(1, 1.2 * cm))

    # ---- 3 assinaturas: entregando + recebendo (digital se houver) + gestor ----
    # Receiver: embute imagem se transfer.signature_data_url existir
    sig_url = transfer.get("signature_data_url") or ""
    rec_sig = None
    if sig_url and sig_url.startswith("data:image/"):
        try:
            import base64
            b64 = sig_url.split(",", 1)[1]
            sig_io = io.BytesIO(base64.b64decode(b64))
            rec_sig = RLImage(sig_io, width=5.5 * cm, height=1.8 * cm,
                                kind="proportional")
        except Exception as e:
            logger.warning("[fleet.romaneio] erro embutindo assinatura: %s", e)
            rec_sig = None

    sig_line = "_" * 38
    sl_style = ParagraphStyle("sl", parent=styles["Normal"], alignment=1,
                                fontSize=10)
    sn_style = ParagraphStyle("sn", parent=styles["Normal"], fontSize=8.5,
                                alignment=1, leading=11)

    col_entrega_top = Paragraph(sig_line, sl_style)
    col_entrega_bot = Paragraph(
        f"<b>{fr_name}</b><br/>"
        f"<font size=8>Técnico — entregando</font><br/>"
        f"<font size=8>CPF: {fr_cpf}</font>",
        sn_style)

    col_recebe_top = rec_sig if rec_sig else Paragraph(sig_line, sl_style)
    signed_at_label = _pt_br_date(transfer.get("signed_at")) if transfer.get("signed_at") else None
    col_recebe_bot = Paragraph(
        f"<b>{to_name}</b><br/>"
        f"<font size=8>Técnico — recebendo</font><br/>"
        f"<font size=8>CPF: {to_cpf}"
        f"{' · assinou em ' + signed_at_label if signed_at_label else ''}</font>",
        sn_style)

    approved_by = transfer.get("approved_by") or "—"
    approved_at = _pt_br_date(transfer.get("approved_at")) if transfer.get("approved_at") else None
    col_gestor_top = Paragraph(sig_line, sl_style)
    col_gestor_bot = Paragraph(
        f"<b>{approved_by}</b><br/>"
        f"<font size=8>Gestor — aprovação</font><br/>"
        f"<font size=8>"
        f"{'Aprovado em ' + approved_at if approved_at else 'Pendente de aprovação'}"
        "</font>",
        sn_style)

    sig_t = Table(
        [[col_entrega_top, col_recebe_top, col_gestor_top],
         [col_entrega_bot, col_recebe_bot, col_gestor_bot]],
        colWidths=[6 * cm, 6 * cm, 6 * cm],
    )
    sig_t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 1), (-1, 1), 4),
    ]))
    story.append(sig_t)

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()


@router.get("/transfers/{tx_id}/pdf")
async def transfer_pdf(tx_id: str, user: dict = Depends(get_current_user)):
    """Gera PDF do romaneio de transferência (padrão romaneio da empresa).

    Acessível por gestor/admin para impressão e coleta de assinatura física.
    """
    _require_manager(user)
    cid = _cid(user)
    tx = await db.fleet_transfers.find_one(
        {"id": tx_id, "company_id": cid}, {"_id": 0})
    if not tx:
        raise HTTPException(404, "Romaneio não encontrado.")
    vehicle = await db.fleet_vehicles.find_one(
        {"id": tx["vehicle_id"]}, {"_id": 0}) or {}
    from_collab = None
    to_collab = None
    if tx.get("from_collaborator_id"):
        from_collab = await db.collaborators.find_one(
            {"id": tx["from_collaborator_id"]}, {"_id": 0})
    if tx.get("to_collaborator_id"):
        to_collab = await db.collaborators.find_one(
            {"id": tx["to_collaborator_id"]}, {"_id": 0})

    # Branding com fallback graceful para a praça do receptor, se houver
    try:
        from routes.collaborator_assets import _branding_with_praca
        branding = await _branding_with_praca(cid, to_collab or from_collab or {})
    except Exception:
        try:
            from routes.branding import get_branding
            branding = (await get_branding(cid)).model_dump()
        except Exception:
            branding = {"company_name": "Empresa"}

    pdf = _build_fleet_transfer_pdf(branding, vehicle, tx, from_collab, to_collab)
    fname = f"romaneio_frota_{vehicle.get('placa') or 'veiculo'}_{tx_id[-6:]}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf), media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


# =============================================================================
# DELETE endpoints — gestor/admin podem apagar lançamentos
# =============================================================================
@router.delete("/vehicles/{vehicle_id}")
async def delete_vehicle(vehicle_id: str,
                          user: dict = Depends(get_current_user)):
    """Apaga um veículo. Bloqueia se houver vistorias OU transferências ativas
    OU lançamentos de combustível — orienta o gestor a inativar (status=inativo).
    """
    _require_manager(user)
    cid = _cid(user)
    veh = await db.fleet_vehicles.find_one(
        {"id": vehicle_id, "company_id": cid}, {"_id": 0})
    if not veh:
        raise HTTPException(404, "Veículo não encontrado")

    # Cascata controlada: bloqueia se há histórico
    n_insp = await db.fleet_inspections.count_documents(
        {"vehicle_id": vehicle_id, "company_id": cid})
    n_fuel = await db.fleet_fuel_entries.count_documents(
        {"vehicle_id": vehicle_id, "company_id": cid})
    n_tx = await db.fleet_transfers.count_documents(
        {"vehicle_id": vehicle_id, "company_id": cid})
    if n_insp or n_fuel or n_tx:
        raise HTTPException(
            400,
            f"Veículo tem histórico: {n_insp} vistoria(s), "
            f"{n_fuel} combustível e {n_tx} transferência(s). "
            "Para preservar a auditoria, marque como 'inativo' em vez de apagar.",
        )

    # Desvincula colaborador (se algum estiver com este veículo)
    await db.collaborators.update_many(
        {"current_vehicle_id": vehicle_id},
        {"$set": {"current_vehicle_id": None}},
    )
    await db.fleet_vehicles.delete_one(
        {"id": vehicle_id, "company_id": cid})
    return {"ok": True}


@router.delete("/inspections/{inspection_id}")
async def delete_inspection(inspection_id: str,
                             user: dict = Depends(get_current_user)):
    """Apaga uma vistoria. Também remove a bolha frota_alerta da Lousa, se houver."""
    _require_manager(user)
    cid = _cid(user)
    r = await db.fleet_inspections.delete_one(
        {"id": inspection_id, "company_id": cid})
    if r.deleted_count == 0:
        raise HTTPException(404, "Vistoria não encontrada")
    # Limpa bolha frota_alerta associada
    await db.tickets.delete_many(
        {"company_id": cid, "type": "frota_alerta",
          "related_inspection_id": inspection_id})
    return {"ok": True}


@router.delete("/fuel/{fuel_id}")
async def delete_fuel(fuel_id: str,
                       user: dict = Depends(get_current_user)):
    """Apaga um lançamento de combustível."""
    _require_manager(user)
    cid = _cid(user)
    r = await db.fleet_fuel_entries.delete_one(
        {"id": fuel_id, "company_id": cid})
    if r.deleted_count == 0:
        raise HTTPException(404, "Lançamento de combustível não encontrado")
    return {"ok": True}


@router.delete("/transfers/{tx_id}")
async def delete_transfer(tx_id: str,
                           user: dict = Depends(get_current_user)):
    """Apaga um romaneio de transferência. Bloqueia se já estiver aprovado
    (transferência efetivada — apagar quebraria a auditoria do veículo).
    Gestor pode estornar criando outra transferência reversa.
    """
    _require_manager(user)
    cid = _cid(user)
    tx = await db.fleet_transfers.find_one(
        {"id": tx_id, "company_id": cid}, {"_id": 0})
    if not tx:
        raise HTTPException(404, "Romaneio não encontrado")
    if tx.get("status") == "approved":
        raise HTTPException(
            400,
            "Não é possível apagar um romaneio já aprovado. "
            "Crie uma transferência reversa para estornar.",
        )
    await db.fleet_transfers.delete_one(
        {"id": tx_id, "company_id": cid})
    return {"ok": True}

