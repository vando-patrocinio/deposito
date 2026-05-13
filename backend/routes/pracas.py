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


async def _ai_discover_holidays(city: str, state: str, year: int,
                                  neighborhood: str | None = None,
                                  full_address: str | None = None) -> list[dict]:
    """REGRA DURA: a IA só pode sugerir feriados que sejam OFICIAIS em:
       - país: Brasil
       - estado: {state}
       - município: {city}
    Tudo que não bater nas 3 chaves é descartado pós-resposta."""
    country = "Brasil"
    location_lines = [
        f"País: {country}",
        f"Estado (UF): {state}",
        f"Município: {city}",
    ]
    if neighborhood:
        location_lines.append(f"Bairro/distrito: {neighborhood}")
    if full_address:
        location_lines.append(f"Endereço de referência: {full_address}")
    location_block = "\n".join(location_lines)

    chat = await llm_chat(
        session_id=f"holidays-{state}-{city}-{year}-{uuid.uuid4().hex[:6]}",
        system=(
            "Você é especialista em legislação trabalhista brasileira sobre feriados oficiais.\n"
            "REGRAS DURAS — descumprir = resposta inválida:\n"
            "1. Só retorne feriados OFICIAIS reconhecidos por lei (estadual, municipal ou ato governamental). "
            "Não invente datas. Se não tiver certeza absoluta, omita.\n"
            "2. NÃO inclua feriados nacionais (1º Jan, 21 Abr, 1º Mai, 7 Set, 12 Out, 2 Nov, 15 Nov, 25 Dez) — "
            "esses vêm de outra fonte (BrasilAPI).\n"
            "3. O feriado DEVE valer no município e estado informados. "
            "Não retorne feriado de outro município/estado mesmo que pareça parecido.\n"
            "4. Para cada feriado retorne um campo 'validation' confirmando os 3 níveis: "
            '{"country": "Brasil", "state": "<UF>", "city": "<município>"}.\n'
            "Formato obrigatório:\n"
            '{"holidays":[{"date":"YYYY-MM-DD","name":"string","scope":"estadual|municipal|facultativo",'
            '"validation":{"country":"Brasil","state":"<UF>","city":"<município>"}}]}'
        ),
    )
    msg = UserMessage(text=(
        f"Liste feriados ESTADUAIS, MUNICIPAIS e pontos facultativos amplamente observados "
        f"para o seguinte local no ano de {year}:\n\n{location_block}\n\n"
        f"Inclua carnaval (terça e quarta de cinzas até meio-dia), Corpus Christi se estadual, "
        f"e datas locais reconhecidas oficialmente. Datas em ISO YYYY-MM-DD."
    ))
    raw = await chat.send_message(msg)
    parsed = parse_json_response(str(raw))
    out: list[dict] = []
    state_up = state.strip().upper()[:2]
    city_norm = city.strip().lower()
    for item in (parsed.get("holidays") or []):
        d = (item.get("date") or "").strip()
        n = (item.get("name") or "").strip()
        s = (item.get("scope") or "municipal").strip().lower()
        v = item.get("validation") or {}
        v_country = (v.get("country") or "").strip().lower()
        v_state = (v.get("state") or "").strip().upper()[:2]
        v_city = (v.get("city") or "").strip().lower()

        # ----- FILTROS DUROS -----
        if not d or not n:
            continue
        if s not in ("estadual", "municipal", "facultativo"):
            s = "municipal"
        if not d.startswith(f"{year:04d}-"):
            continue
        # país obrigatório = Brasil
        if v_country and "bras" not in v_country:
            continue
        # estado obrigatório igual
        if v_state and v_state != state_up:
            continue
        # município obrigatório igual (case insensitive). Se for estadual, aceita
        # qualquer município do mesmo estado.
        if s == "municipal" and v_city and v_city != city_norm:
            continue

        out.append({
            "date": d, "name": n, "scope": s, "source": "ai",
            "validation": {"country": "Brasil", "state": state_up, "city": city.strip()},
        })

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
        suggestions = await _ai_discover_holidays(
            praca["city"], praca["state"], year,
            neighborhood=praca.get("neighborhood"),
            full_address=praca.get("full_address"),
        )
    except Exception as e:
        err_str = str(e)
        logger.exception("[ai_discover_holidays] erro: %s", e)
        await db.system_alerts.insert_one({
            "id": uuid.uuid4().hex[:14], "type": "ai_holidays_failure",
            "message": f"Falha ao buscar feriados via IA para {praca['city']}/{praca['state']} ({year}): {e}",
            "at": now_iso(), "severity": "warning",
        })
        # Mensagem amigável conforme o tipo de erro
        if "402" in err_str or "credits" in err_str.lower() or "afford" in err_str.lower():
            raise HTTPException(
                503,
                "Sem créditos na OpenRouter. Vá em Sistema → Motor IA → recarregar saldo, "
                "ou cadastre os feriados manualmente abaixo.",
            )
        if "401" in err_str or "unauthorized" in err_str.lower() or "api" in err_str.lower() and "key" in err_str.lower():
            raise HTTPException(
                503,
                "Motor IA sem chave configurada. Vá em Sistema → Motor IA para configurar.",
            )
        raise HTTPException(
            502,
            "IA indisponível no momento. Tente em instantes ou cadastre manualmente.",
        )
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
