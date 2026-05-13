"""Endpoints de Praças (locais de trabalho com feriados estaduais/municipais)."""
import logging
import uuid
from typing import Optional

from emergentintegrations.llm.chat import UserMessage
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth import decode_token
from core import (
    DEMO_COMPANY_ID,
    is_super_admin,
    llm_chat,
    now_iso,
    parse_json_response,
    require_role,
    tenant_filter,
)
from database import db

logger = logging.getLogger("ponto")
router = APIRouter(prefix="/api", tags=["pracas"])


async def get_current_user_optional(request: Request) -> Optional[dict]:
    """Retorna user autenticado SE o token estiver presente; senão None.
    Usado em endpoints que aceitam chamada pública (PWA mobile)."""
    auth = (request.headers.get("Authorization") or "")
    if not auth.startswith("Bearer "):
        return None
    try:
        payload = decode_token(auth[7:])
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
        if not user:
            return None
        user["company_id"] = payload.get("company_id") or user.get("company_id") or DEMO_COMPANY_ID
        return user
    except Exception:
        return None


class HolidayExtra(BaseModel):
    date: str
    name: str
    scope: str = "municipal"
    source: str = "manual"


class PracaIn(BaseModel):
    name: str
    city: str
    state: str
    full_address: Optional[str] = None
    street: Optional[str] = None
    number: Optional[str] = None
    neighborhood: Optional[str] = None
    postal_code: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    holidays_extra: list[HolidayExtra] = Field(default_factory=list)
    # Identificação fiscal & branding (aparece no cabeçalho do espelho/romaneio)
    logo_url: Optional[str] = None
    cnpj: Optional[str] = None
    inscricao_estadual: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    site: Optional[str] = None


@router.get("/pracas")
async def list_pracas(user: dict = Depends(get_current_user_optional)):
    """Lista praças do tenant. Endpoint pode ser chamado sem auth (uso público em
    PWA mobile para popular dropdown). Sem auth → todas (legacy)."""
    q = tenant_filter(user) if user else {}
    return await db.pracas.find(q, {"_id": 0}).sort("name", 1).to_list(500)


@router.post("/pracas")
async def create_praca(payload: PracaIn, user: dict = Depends(require_role("gestor"))):
    pid = f"prc-{uuid.uuid4().hex[:10]}"
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = {
        "id": pid,
        "company_id": cid,
        "name": payload.name.strip(),
        "city": payload.city.strip(),
        "state": payload.state.strip().upper()[:2],
        "full_address": (payload.full_address or "").strip() or None,
        "street": payload.street, "number": payload.number,
        "neighborhood": payload.neighborhood, "postal_code": payload.postal_code,
        "lat": payload.lat, "lng": payload.lng,
        "holidays_extra": [h.model_dump() for h in payload.holidays_extra],
        "logo_url": (payload.logo_url or "").strip() or None,
        "cnpj": (payload.cnpj or "").strip() or None,
        "inscricao_estadual": (payload.inscricao_estadual or "").strip() or None,
        "phone": (payload.phone or "").strip() or None,
        "email": (payload.email or "").strip() or None,
        "site": (payload.site or "").strip() or None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.pracas.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/pracas/{pid}")
async def update_praca(pid: str, payload: PracaIn, user: dict = Depends(require_role("gestor"))):
    if not is_super_admin(user):
        existing = await db.pracas.find_one({"id": pid}, {"company_id": 1})
        if not existing or existing.get("company_id") != user.get("company_id"):
            raise HTTPException(404, "Praça não encontrada")
    update = {
        "name": payload.name.strip(),
        "city": payload.city.strip(),
        "state": payload.state.strip().upper()[:2],
        "full_address": (payload.full_address or "").strip() or None,
        "street": payload.street, "number": payload.number,
        "neighborhood": payload.neighborhood, "postal_code": payload.postal_code,
        "lat": payload.lat, "lng": payload.lng,
        "holidays_extra": [h.model_dump() for h in payload.holidays_extra],
        "logo_url": (payload.logo_url or "").strip() or None,
        "cnpj": (payload.cnpj or "").strip() or None,
        "inscricao_estadual": (payload.inscricao_estadual or "").strip() or None,
        "phone": (payload.phone or "").strip() or None,
        "email": (payload.email or "").strip() or None,
        "site": (payload.site or "").strip() or None,
        "updated_at": now_iso(),
    }
    res = await db.pracas.update_one({"id": pid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(404, "Praça não encontrada")
    return await db.pracas.find_one({"id": pid}, {"_id": 0})


@router.delete("/pracas/{pid}")
async def delete_praca(pid: str, user: dict = Depends(require_role("gestor"))):
    if not is_super_admin(user):
        existing = await db.pracas.find_one({"id": pid}, {"company_id": 1})
        if not existing or existing.get("company_id") != user.get("company_id"):
            raise HTTPException(404, "Praça não encontrada")
    used = await db.collaborators.count_documents({"praca_id": pid})
    if used > 0:
        raise HTTPException(400, f"Praça em uso por {used} colaborador(es). Reatribua antes de excluir.")
    res = await db.pracas.delete_one({"id": pid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Praça não encontrada")
    return {"ok": True}


async def _ai_discover_holidays(city: str, state: str, year: int) -> list[dict]:
    chat = await llm_chat(
        session_id=f"holidays-{state}-{city}-{year}-{uuid.uuid4().hex[:6]}",
        system=(
            "Você é um especialista em legislação brasileira sobre feriados. "
            "Responda APENAS com um JSON válido no formato: "
            '{"holidays": [{"date": "YYYY-MM-DD", "name": "string", "scope": "estadual|municipal|facultativo"}]}. '
            "Não inclua feriados nacionais (ex.: 1º Janeiro, 7 Setembro, 25 Dezembro) — só estaduais e municipais. "
            "Inclua datas reais e amplamente reconhecidas. Se não tiver certeza absoluta de uma data, omita-a. "
            "Retorne lista vazia se não houver feriados específicos."
        ),
    )
    msg = UserMessage(text=(
        f"Quais são os feriados ESTADUAIS e MUNICIPAIS da cidade de {city} - {state}, Brasil, no ano de {year}? "
        "Inclua também pontos facultativos amplamente observados (carnaval — terça e quarta de cinzas até meio-dia, "
        "Corpus Christi se for estadual). Datas no formato ISO YYYY-MM-DD."
    ))
    raw = await chat.send_message(msg)
    parsed = parse_json_response(str(raw))
    out: list[dict] = []
    for item in (parsed.get("holidays") or []):
        d = (item.get("date") or "").strip()
        n = (item.get("name") or "").strip()
        s = (item.get("scope") or "municipal").strip().lower()
        if not d or not n:
            continue
        if s not in ("estadual", "municipal", "facultativo"):
            s = "municipal"
        if not d.startswith(f"{year:04d}-"):
            continue
        out.append({"date": d, "name": n, "scope": s, "source": "ai"})
    seen: set[str] = set()
    unique: list[dict] = []
    for h in sorted(out, key=lambda x: x["date"]):
        if h["date"] in seen:
            continue
        seen.add(h["date"])
        unique.append(h)
    return unique


@router.post("/pracas/{pid}/discover-holidays")
async def discover_holidays(pid: str, year: int, _user: dict = Depends(require_role("gestor"))):
    praca = await db.pracas.find_one({"id": pid}, {"_id": 0})
    if not praca:
        raise HTTPException(404, "Praça não encontrada")
    if year < 2000 or year > 2100:
        raise HTTPException(400, "Ano inválido")
    try:
        suggestions = await _ai_discover_holidays(praca["city"], praca["state"], year)
    except Exception as e:
        logger.exception("[ai_discover_holidays] erro: %s", e)
        await db.system_alerts.insert_one({
            "id": uuid.uuid4().hex[:14], "type": "ai_holidays_failure",
            "message": f"Falha ao buscar feriados via IA para {praca['city']}/{praca['state']} ({year}): {e}",
            "at": now_iso(), "severity": "warning",
        })
        raise HTTPException(502, "IA indisponível para sugerir feriados. Tente novamente em instantes.")
    return {"year": year, "city": praca["city"], "state": praca["state"], "suggestions": suggestions}


@router.post("/pracas/{pid}/apply-holidays")
async def apply_holidays(pid: str, payload: dict, _user: dict = Depends(require_role("gestor"))):
    praca = await db.pracas.find_one({"id": pid}, {"_id": 0})
    if not praca:
        raise HTTPException(404, "Praça não encontrada")
    new_items = payload.get("holidays") or []
    if not isinstance(new_items, list):
        raise HTTPException(400, "Campo 'holidays' deve ser uma lista")
    existing = praca.get("holidays_extra", []) or []
    by_date = {h["date"]: h for h in existing}
    added = 0
    for h in new_items:
        d = (h.get("date") or "").strip()
        if not d:
            continue
        item = {
            "date": d,
            "name": (h.get("name") or "").strip() or "Feriado",
            "scope": (h.get("scope") or "municipal").strip().lower(),
            "source": (h.get("source") or "manual"),
        }
        if d not in by_date:
            added += 1
            by_date[d] = item
        else:
            if by_date[d].get("source") == "ai" and item.get("source") == "ai":
                by_date[d] = item
    merged = sorted(by_date.values(), key=lambda x: x["date"])
    await db.pracas.update_one({"id": pid}, {"$set": {"holidays_extra": merged, "updated_at": now_iso()}})
    return {"ok": True, "added": added, "total": len(merged), "holidays_extra": merged}
