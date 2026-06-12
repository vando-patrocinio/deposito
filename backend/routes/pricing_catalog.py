"""Tabela de Preços oficial (pricing catalog) — única fonte de valores
injetada nos prompts dos agentes IA como bloco `=== PREÇOS E VALORES ===`.

Endpoints (gestor):
  GET    /api/pricing-catalog/items
  POST   /api/pricing-catalog/items
  PATCH  /api/pricing-catalog/items/{item_id}
  DELETE /api/pricing-catalog/items/{item_id}

Itens em `pricing_catalog`:
  - id (uuid) / company_id
  - category: plano_fibra | adicional | servico | taxa | combo
  - name: "500 Mega", "Wi-Fi 6 ponto adicional", ...
  - price_brl: float (obrigatório)
  - billing_cycle: mensal | unico
  - fidelity: com | sem | na   (só relevante pra plano_fibra)
  - speed_mbps: int opcional (planos)
  - description: opcional (regra/condição visível pra IA)
  - enabled: bool — só itens habilitados entram no prompt

`compose_pricing_block()` é usado pelo fluxo de auto-reply
(whatsapp_baileys / aihub) no lugar do campo livre `pricing_info`.
Se o catálogo estiver vazio, o chamador faz fallback pro `pricing_info`.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, require_role
from database import db

logger = logging.getLogger("ponto.pricing_catalog")
router = APIRouter(prefix="/api/pricing-catalog", tags=["pricing-catalog"])

VALID_CATEGORIES = {"plano_fibra", "adicional", "servico", "taxa", "combo"}
VALID_CYCLES = {"mensal", "unico"}
VALID_FIDELITY = {"com", "sem", "na"}

CATEGORY_LABELS = {
    "plano_fibra": "PLANOS DE FIBRA",
    "adicional": "ADICIONAIS",
    "servico": "SERVIÇOS",
    "taxa": "TAXAS",
    "combo": "COMBOS",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


class ItemIn(BaseModel):
    category: str = Field(..., min_length=3, max_length=30)
    name: str = Field(..., min_length=2, max_length=120)
    price_brl: float = Field(..., ge=0)
    billing_cycle: str = Field(default="mensal")
    fidelity: str = Field(default="na")
    speed_mbps: Optional[int] = Field(default=None, ge=0)
    description: Optional[str] = Field(default=None, max_length=300)
    enabled: bool = True
    sort_order: int = 0


class ItemPatch(BaseModel):
    category: Optional[str] = None
    name: Optional[str] = None
    price_brl: Optional[float] = Field(default=None, ge=0)
    billing_cycle: Optional[str] = None
    fidelity: Optional[str] = None
    speed_mbps: Optional[int] = Field(default=None, ge=0)
    description: Optional[str] = Field(default=None, max_length=300)
    enabled: Optional[bool] = None
    sort_order: Optional[int] = None


def _validate(category: Optional[str] = None, cycle: Optional[str] = None,
                fidelity: Optional[str] = None) -> None:
    if category is not None and category not in VALID_CATEGORIES:
        raise HTTPException(400,
            f"category inválida. Use: {', '.join(sorted(VALID_CATEGORIES))}")
    if cycle is not None and cycle not in VALID_CYCLES:
        raise HTTPException(400, "billing_cycle inválido. Use: mensal | unico")
    if fidelity is not None and fidelity not in VALID_FIDELITY:
        raise HTTPException(400, "fidelity inválida. Use: com | sem | na")


def _serialize(doc: dict) -> dict:
    return {
        "id": doc.get("id"),
        "category": doc.get("category"),
        "name": doc.get("name"),
        "price_brl": doc.get("price_brl"),
        "billing_cycle": doc.get("billing_cycle"),
        "fidelity": doc.get("fidelity"),
        "speed_mbps": doc.get("speed_mbps"),
        "description": doc.get("description"),
        "enabled": bool(doc.get("enabled", True)),
        "sort_order": doc.get("sort_order", 0),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "updated_by": doc.get("updated_by"),
    }


@router.get("/items")
async def list_items(user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    items = await db.pricing_catalog.find(
        {"company_id": cid}, {"_id": 0},
    ).sort([("category", 1), ("sort_order", 1), ("price_brl", 1)]).to_list(300)
    return {"items": [_serialize(x) for x in items]}


@router.post("/items")
async def create_item(payload: ItemIn,
                        user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    cat = payload.category.strip().lower()
    cycle = payload.billing_cycle.strip().lower()
    fid = payload.fidelity.strip().lower()
    _validate(cat, cycle, fid)
    doc = {
        "id": f"prc-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "category": cat,
        "name": payload.name.strip(),
        "price_brl": round(float(payload.price_brl), 2),
        "billing_cycle": cycle,
        "fidelity": fid,
        "speed_mbps": payload.speed_mbps,
        "description": (payload.description or "").strip() or None,
        "enabled": payload.enabled,
        "sort_order": payload.sort_order,
        "created_at": _now(),
        "updated_at": _now(),
        "updated_by": user.get("email") or user.get("id") or "gestor",
    }
    await db.pricing_catalog.insert_one(dict(doc))
    return _serialize(doc)


@router.patch("/items/{item_id}")
async def patch_item(item_id: str, payload: ItemPatch,
                       user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    upd: dict = {"updated_at": _now(),
                 "updated_by": user.get("email") or "gestor"}
    if payload.category is not None:
        cat = payload.category.strip().lower()
        _validate(category=cat)
        upd["category"] = cat
    if payload.billing_cycle is not None:
        cycle = payload.billing_cycle.strip().lower()
        _validate(cycle=cycle)
        upd["billing_cycle"] = cycle
    if payload.fidelity is not None:
        fid = payload.fidelity.strip().lower()
        _validate(fidelity=fid)
        upd["fidelity"] = fid
    if payload.name is not None:
        upd["name"] = payload.name.strip()
    if payload.price_brl is not None:
        upd["price_brl"] = round(float(payload.price_brl), 2)
    if payload.speed_mbps is not None:
        upd["speed_mbps"] = payload.speed_mbps
    if payload.description is not None:
        upd["description"] = payload.description.strip() or None
    if payload.enabled is not None:
        upd["enabled"] = bool(payload.enabled)
    if payload.sort_order is not None:
        upd["sort_order"] = payload.sort_order
    r = await db.pricing_catalog.update_one(
        {"company_id": cid, "id": item_id}, {"$set": upd},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Item não encontrado")
    doc = await db.pricing_catalog.find_one(
        {"company_id": cid, "id": item_id}, {"_id": 0},
    )
    return _serialize(doc)


@router.delete("/items/{item_id}")
async def delete_item(item_id: str,
                        user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    r = await db.pricing_catalog.delete_one(
        {"company_id": cid, "id": item_id},
    )
    if r.deleted_count == 0:
        raise HTTPException(404, "Item não encontrado")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Composer usado pelo fluxo de auto-reply (whatsapp_baileys / aihub)
# ---------------------------------------------------------------------------
def _fmt_price(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_item(it: dict) -> str:
    price = _fmt_price(float(it.get("price_brl") or 0))
    cycle = "/mês" if it.get("billing_cycle") == "mensal" else " (cobrança única)"
    parts = [f"• {it.get('name')} — {price}{cycle}"]
    fid = it.get("fidelity")
    if it.get("category") == "plano_fibra" and fid in ("com", "sem"):
        parts.append(f"({fid} fidelidade)")
    if it.get("description"):
        parts.append(f"— {it['description']}")
    return " ".join(parts)


async def compose_pricing_block(company_id: str) -> str:
    """Retorna o bloco `=== PREÇOS E VALORES ===` montado a partir do
    catálogo. String vazia se não houver item habilitado (caller faz
    fallback pro pricing_info legado)."""
    items = await db.pricing_catalog.find(
        {"company_id": company_id, "enabled": True}, {"_id": 0},
    ).sort([("category", 1), ("sort_order", 1), ("price_brl", 1)]).to_list(300)
    if not items:
        return ""
    by_cat: dict = {}
    for it in items:
        by_cat.setdefault(it.get("category", "servico"), []).append(it)
    parts: List[str] = [
        "=== PREÇOS E VALORES (TABELA OFICIAL) ===",
        "Estes são os ÚNICOS valores autorizados. NUNCA cite preço fora "
        "desta tabela. Item que não está aqui = 'vou confirmar o valor e "
        "te retorno'.",
        "",
    ]
    for cat in ("plano_fibra", "combo", "adicional", "servico", "taxa"):
        frags = by_cat.get(cat)
        if not frags:
            continue
        parts.append(f"## {CATEGORY_LABELS.get(cat, cat.upper())}")
        for it in frags:
            parts.append(_fmt_item(it))
        parts.append("")
    return "\n".join(parts).rstrip()
