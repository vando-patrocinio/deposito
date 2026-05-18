"""Endpoints de Reajuste Anual de Planos (subaba do Financeiro).

UI: lista clientes com reajuste devido/próximo, permite aplicar individual ou em lote.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core import require_role
from database import db
from services.inflation import (
    SGS_CODES, get_index, refresh_index_cache,
)
from services.readjustment import (
    apply_all_due, apply_readjustment, calculate_readjustment_preview,
    list_due_subscribers,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/financeiro/reajuste", tags=["reajuste"])


@router.get("/indices")
async def list_indices(user: dict = Depends(require_role("gestor"))):
    """Lista todos os índices oficiais disponíveis com seus valores atuais."""
    out = []
    for name in SGS_CODES.keys():
        doc = await get_index(name, auto_refresh=False)
        out.append({
            "name": name,
            "accumulated_12m": (doc or {}).get("accumulated_12m"),
            "last_period": (doc or {}).get("last_period"),
            "updated_at": (doc or {}).get("updated_at"),
        })
    return {"items": out}


@router.post("/indices/{name}/refresh")
async def refresh_index(name: str,
                        user: dict = Depends(require_role("gestor"))):
    """Força atualização de um índice da API do BCB."""
    name = name.upper()
    if name not in SGS_CODES:
        raise HTTPException(404, f"Índice desconhecido: {name}")
    doc = await refresh_index_cache(name)
    return {
        "ok": True, "name": name,
        "accumulated_12m": doc.get("accumulated_12m"),
        "last_period": doc.get("last_period"),
    }


@router.get("/due")
async def list_due(
    horizon_days: int = Query(30, ge=0, le=365),
    user: dict = Depends(require_role("gestor")),
):
    """Lista clientes com reajuste devido ou que vence em N dias."""
    cid = user.get("company_id") or "co-demo"
    items = await list_due_subscribers(cid, horizon_days=horizon_days)
    # Separa vencidos vs futuros
    due_now = [i for i in items if i.get("is_due")]
    upcoming = [i for i in items if not i.get("is_due")]
    return {
        "total": len(items),
        "due_now": due_now,
        "upcoming": upcoming,
        "horizon_days": horizon_days,
    }


@router.get("/preview/{subscriber_id}")
async def preview_for_subscriber(
    subscriber_id: str,
    index_name: Optional[str] = None,
    user: dict = Depends(require_role("gestor")),
):
    """Mostra projeção de reajuste pra UM cliente (sem aplicar)."""
    cid = user.get("company_id") or "co-demo"
    sub = await db.subscribers.find_one(
        {"id": subscriber_id, "company_id": cid}, {"_id": 0},
    )
    if not sub:
        raise HTTPException(404, "Assinante não encontrado")
    preview = await calculate_readjustment_preview(sub, index_name)
    if not preview:
        raise HTTPException(400, "Sem dados suficientes "
                                  "(installation_date ou plan_price ausentes)")
    return preview


@router.post("/apply/{subscriber_id}")
async def apply_single(
    subscriber_id: str,
    force: bool = False,
    user: dict = Depends(require_role("administrador")),
):
    """Aplica reajuste em UM cliente. `force=true` ignora regra de 12 meses."""
    cid = user.get("company_id") or "co-demo"
    sub = await db.subscribers.find_one(
        {"id": subscriber_id, "company_id": cid}, {"_id": 0},
    )
    if not sub:
        raise HTTPException(404, "Assinante não encontrado")
    result = await apply_readjustment(sub, actor=user.get("email", "admin"),
                                       force=force)
    return result


@router.post("/apply-all-due")
async def apply_all(user: dict = Depends(require_role("administrador"))):
    """Aplica reajuste em TODOS os clientes vencidos (ação de lote)."""
    cid = user.get("company_id") or "co-demo"
    summary = await apply_all_due(cid, actor=user.get("email", "admin-batch"))
    return summary


@router.get("/history/{subscriber_id}")
async def history(
    subscriber_id: str,
    user: dict = Depends(require_role("gestor")),
):
    """Histórico de reajustes de um cliente."""
    cid = user.get("company_id") or "co-demo"
    items = await db.subscriber_readjustments.find(
        {"subscriber_id": subscriber_id, "company_id": cid},
        {"_id": 0},
    ).sort("applied_at", -1).to_list(50)
    return {"items": items}


@router.get("/cohort")
async def tenure_cohort(
    user: dict = Depends(require_role("gestor")),
):
    """🎯 Trilha de Clientes por Aniversário — quantos clientes completaram 1..20 anos.

    Usa `installation_date` pra calcular tenure. Agrupa em buckets de 1 ano.
    Identifica também quantos já aniversariaram este mês (gatilho de reajuste).
    """
    from datetime import datetime, timezone
    cid = user.get("company_id") or "co-demo"
    now = datetime.now(timezone.utc)

    # Buckets: 1 a 20 anos
    cohort = {y: {"year": y, "total": 0, "due_this_month": 0,
                   "active_value": 0.0, "names": []}
              for y in range(1, 21)}
    untracked = {"no_install_date": 0, "less_than_1_year": 0}

    async for sub in db.subscribers.find(
        {"company_id": cid, "status": {"$in": ["ATIVO", "ativo"]}},
        {"_id": 0, "id": 1, "name": 1, "installation_date": 1,
         "plan_price": 1, "plan_name": 1},
    ):
        inst = sub.get("installation_date")
        if not inst:
            untracked["no_install_date"] += 1
            continue
        try:
            d = datetime.fromisoformat(inst.replace("Z", "+00:00")) if isinstance(inst, str) else inst
            if not d.tzinfo:
                d = d.replace(tzinfo=timezone.utc)
        except Exception:
            untracked["no_install_date"] += 1
            continue
        years = (now - d).days // 365
        if years < 1:
            untracked["less_than_1_year"] += 1
            continue
        if years > 20:
            years = 20
        cohort[years]["total"] += 1
        cohort[years]["active_value"] += float(sub.get("plan_price") or 0)
        if len(cohort[years]["names"]) < 8:
            cohort[years]["names"].append(sub.get("name"))
        # Aniversariou neste mês (mesmo dia/mês da instalação no mês atual)
        next_anniv = d.replace(year=d.year + years + 1) if years < 20 else None
        if next_anniv and (next_anniv - now).days <= 30 and (next_anniv - now).days >= 0:
            cohort[years]["due_this_month"] += 1

    return {
        "as_of": now.isoformat(),
        "cohort": list(cohort.values()),
        "untracked": untracked,
        "total_tracked": sum(c["total"] for c in cohort.values()),
    }


@router.get("/retention-curve")
async def retention_curve(
    user: dict = Depends(require_role("gestor")),
):
    """📉 Curva de Retenção — % de clientes ativos por anos de casa.

    Mostra onde os clientes mais cancelam (ponto de virada do churn).
    Inclui base ATIVO + INATIVO/CANCELADO para calcular % corretamente.
    """
    from datetime import datetime, timezone
    cid = user.get("company_id") or "co-demo"
    now = datetime.now(timezone.utc)

    # Total instalados em cada ano (anos de casa) e quantos seguem ativos
    by_year = {y: {"installed": 0, "active": 0, "active_value": 0.0}
               for y in range(0, 21)}

    async for sub in db.subscribers.find(
        {"company_id": cid,
         "installation_date": {"$exists": True, "$ne": None}},
        {"_id": 0, "installation_date": 1, "status": 1, "plan_price": 1},
    ):
        inst = sub.get("installation_date")
        try:
            d = datetime.fromisoformat(inst.replace("Z", "+00:00")) if isinstance(inst, str) else inst
            if not d.tzinfo:
                d = d.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        years = min((now - d).days // 365, 20)
        is_active = (sub.get("status") or "").lower() in ("ativo", "active")
        # Counting: o assinante atravessou cada ano de 0 até `years`
        for y in range(0, years + 1):
            by_year[y]["installed"] += 1
            if is_active and y <= years:
                by_year[y]["active"] += 1
                if y == years:
                    by_year[y]["active_value"] += float(sub.get("plan_price") or 0)

    base = by_year[0]["installed"] or 1
    curve = []
    for y in range(0, 21):
        installed = by_year[y]["installed"]
        active = by_year[y]["active"]
        # Retenção relativa à base (ano 0)
        retention_pct = round((active / base) * 100, 2) if base else 0
        # Churn marginal (perda do ano anterior pra este)
        if y == 0:
            churn_pct = 0
        else:
            prev_active = by_year[y - 1]["active"]
            churn_pct = round(((prev_active - active) / prev_active) * 100, 2) \
                if prev_active > 0 else 0
        curve.append({
            "year": y,
            "active": active,
            "installed_at_some_point": installed,
            "retention_pct": retention_pct,
            "churn_pct_from_prev": churn_pct,
        })

    return {
        "as_of": now.isoformat(),
        "base_year_0": base,
        "curve": curve,
    }
