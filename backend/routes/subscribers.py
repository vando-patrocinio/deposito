"""Cadastro de Assinantes (clientes do ISP) + vinculação automática por telefone.

Quando uma mensagem WhatsApp ou chamada SIP entra no sistema, o número é
normalizado e cruzado com `subscriber_phones`. Se houver match, a conversa
é vinculada ao assinante e o agente IA recebe contexto enriquecido.

Coleções:
- `subscribers`: ficha do cliente (status, plano, endereço resumido, tags, etc)
- `subscriber_phones`: telefone normalizado (1→N por subscriber)
- `subscriber_addresses`: endereço completo (1→N)
- `subscriber_match_log`: auditoria de tentativas de vinculação
"""
from __future__ import annotations

import csv
import io
import logging
import re
import uuid
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db
from phone_normalizer import normalize_brazilian_phone, get_phone_lookup_variants

logger = logging.getLogger("ponto.subscribers")
router = APIRouter(prefix="/api/subscribers", tags=["subscribers"])


SUBSCRIBER_STATUS = Literal[
    "ATIVO", "BLOQUEADO", "SUSPENSO", "CANCELADO",
    "EM_INSTALACAO", "AGUARDANDO_VIABILIDADE", "SEM_VIABILIDADE",
    "PROSPECT", "INADIMPLENTE",
]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class PhoneIn(BaseModel):
    label: Optional[str] = Field(default=None, max_length=40)
    raw_number: str = Field(..., min_length=8, max_length=30)
    is_whatsapp: bool = False
    is_primary: bool = False


class AddressIn(BaseModel):
    street: Optional[str] = Field(default=None, max_length=200)
    number: Optional[str] = Field(default=None, max_length=20)
    complement: Optional[str] = Field(default=None, max_length=120)
    district: Optional[str] = Field(default=None, max_length=120)
    city: Optional[str] = Field(default=None, max_length=120)
    state: Optional[str] = Field(default=None, max_length=2)
    zip_code: Optional[str] = Field(default=None, max_length=15)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_primary: bool = False


class SubscriberIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=160)
    nickname: Optional[str] = Field(default=None, max_length=120)
    document: Optional[str] = Field(default=None, max_length=30)  # CPF/CNPJ
    rg_ie: Optional[str] = Field(default=None, max_length=30)
    # external_code é AUTO-GERADO pelo sistema (sequencial ASS-XXXXX).
    # Ignoramos qualquer valor enviado pelo cliente. Mantemos no model só
    # para retro-compat de testes/payloads antigos.
    external_code: Optional[str] = Field(default=None, max_length=80)
    email: Optional[str] = Field(default=None, max_length=200)
    status: SUBSCRIBER_STATUS = "ATIVO"
    # Plano referenciado por id. Os campos antigos (plan_name/speed/price)
    # ficam como snapshot read-only no documento (hidratados a partir do plano).
    plan_id: Optional[str] = Field(default=None, max_length=40)
    plan_name: Optional[str] = Field(default=None, max_length=120)
    plan_speed: Optional[str] = Field(default=None, max_length=40)
    plan_price: Optional[float] = Field(default=None, ge=0)
    activation_date: Optional[str] = None
    cancellation_date: Optional[str] = None
    cancellation_reason: Optional[str] = Field(default=None, max_length=300)
    financial_status: Optional[str] = Field(default=None, max_length=40)
    notes: Optional[str] = Field(default=None, max_length=2000)
    tags: List[str] = Field(default_factory=list)
    pppoe_user: Optional[str] = Field(default=None, max_length=80)
    cto_port: Optional[str] = Field(default=None, max_length=80)
    equipment: Optional[str] = Field(default=None, max_length=120)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    phones: List[PhoneIn] = Field(default_factory=list)
    addresses: List[AddressIn] = Field(default_factory=list)
    # Campos estilo Atlaz
    branch: Optional[str] = Field(default=None, max_length=80)  # Filial
    billing_method: Optional[str] = Field(default=None, max_length=40)
    contract_status: Optional[str] = Field(default=None, max_length=40)
    contracts_count: int = Field(default=0, ge=0)
    due_day: Optional[int] = Field(default=None, ge=1, le=31)  # Dia do vencimento


class SubscriberUpdate(BaseModel):
    name: Optional[str] = None
    nickname: Optional[str] = None
    document: Optional[str] = None
    rg_ie: Optional[str] = None
    # external_code é IMUTÁVEL após criação (gerado pelo sistema).
    # Mantido na model só pra não quebrar payloads antigos — ignorado no update.
    external_code: Optional[str] = None
    email: Optional[str] = None
    status: Optional[SUBSCRIBER_STATUS] = None
    plan_id: Optional[str] = None
    plan_name: Optional[str] = None
    plan_speed: Optional[str] = None
    plan_price: Optional[float] = None
    activation_date: Optional[str] = None
    cancellation_date: Optional[str] = None
    cancellation_reason: Optional[str] = None
    financial_status: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    pppoe_user: Optional[str] = None
    cto_port: Optional[str] = None
    equipment: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    branch: Optional[str] = None
    billing_method: Optional[str] = None
    contract_status: Optional[str] = None
    contracts_count: Optional[int] = None
    due_day: Optional[int] = None


class MatchPhoneIn(BaseModel):
    phone: str = Field(..., min_length=4, max_length=40)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


async def _next_subscriber_seq(company_id: str) -> int:
    """Counter atômico pra gerar external_code sequencial (ASS-XXXXX)."""
    res = await db.counters.find_one_and_update(
        {"_id": f"subscribers-{company_id}"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return int(res.get("seq", 1))


def _derive_nickname(name: str) -> str:
    """REGRA: apelido default = primeiro nome (capitalizado).
    Ex.: 'João Silva da Costa' → 'João'."""
    if not name:
        return ""
    first = name.strip().split()[0]
    return first.title() if first else ""


async def _hydrate_plan(company_id: str, plan_id: Optional[str]) -> dict:
    """Carrega snapshot do plano (name/speed/price) a partir do plan_id."""
    if not plan_id:
        return {}
    p = await db.plans.find_one(
        {"company_id": company_id, "id": plan_id}, {"_id": 0})
    if not p:
        return {}
    return {
        "plan_name": p.get("name"),
        "plan_speed": p.get("speed_label"),
        "plan_price": p.get("monthly_price"),
        "plan_annual_adjustment_pct": p.get("annual_adjustment_pct"),
    }


async def _replace_phones(company_id: str, subscriber_id: str,
                           phones: List[PhoneIn]) -> List[dict]:
    """Substitui telefones do subscriber.

    REGRA: TODO telefone cadastrado é PRINCIPAL e VINCULANTE — ou seja, será
    usado pra match com qualquer chamada/WhatsApp inbound. Não existe mais
    a noção de "1 principal, N secundários": todos vinculam. O frontend não
    pergunta mais isso ao usuário.
    """
    await db.subscriber_phones.delete_many(
        {"company_id": company_id, "subscriber_id": subscriber_id})
    docs = []
    for p in phones:
        normalized = normalize_brazilian_phone(p.raw_number)
        if not normalized:
            continue  # pula telefones inválidos
        docs.append({
            "id": f"sphone-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "subscriber_id": subscriber_id,
            "label": p.label,
            "raw_number": p.raw_number,
            "normalized_number": normalized,
            "is_whatsapp": True,  # todos viáveis pra WA por padrão
            "is_primary": True,    # REGRA: todos vinculam
            "created_at": now_iso(),
        })
    if docs:
        await db.subscriber_phones.insert_many([dict(d) for d in docs])
    return docs


async def _replace_addresses(company_id: str, subscriber_id: str,
                              addresses: List[AddressIn]) -> List[dict]:
    await db.subscriber_addresses.delete_many(
        {"company_id": company_id, "subscriber_id": subscriber_id})
    docs = []
    primary_set = False
    for a in addresses:
        is_primary = a.is_primary and not primary_set
        if is_primary:
            primary_set = True
        d = a.model_dump()
        d.update({
            "id": f"saddr-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "subscriber_id": subscriber_id,
            "is_primary": is_primary,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
        docs.append(d)
    if docs and not primary_set:
        docs[0]["is_primary"] = True
    if docs:
        await db.subscriber_addresses.insert_many([dict(d) for d in docs])
    return docs


async def _hydrate(sub: dict) -> dict:
    """Anexa phones + addresses ao subscriber (sem _id)."""
    if not sub:
        return sub
    sub.pop("_id", None)
    cid = sub["company_id"]
    sid = sub["id"]
    phones = await db.subscriber_phones.find(
        {"company_id": cid, "subscriber_id": sid}, {"_id": 0},
    ).to_list(50)
    addresses = await db.subscriber_addresses.find(
        {"company_id": cid, "subscriber_id": sid}, {"_id": 0},
    ).to_list(20)
    sub["phones"] = phones
    sub["addresses"] = addresses
    return sub


def _mask_doc(document: Optional[str]) -> Optional[str]:
    """Mascara CPF/CNPJ — exibe só os 3 últimos dígitos."""
    if not document:
        return None
    d = "".join(ch for ch in document if ch.isdigit())
    if len(d) < 4:
        return "***"
    return f"***.***.***-{d[-2:]}" if len(d) == 11 else f"**.***.***/****-{d[-2:]}"


# ---------------------------------------------------------------------------
# Match service (usado por aihub.py também)
# ---------------------------------------------------------------------------
async def find_subscriber_by_phone(company_id: str, incoming: str) -> dict:
    """Procura assinante pelo número. Retorna dict:
    - {status: 'matched', subscriber, normalized}
    - {status: 'conflict', matches, normalized}
    - {status: 'not_found', normalized}
    """
    normalized = normalize_brazilian_phone(incoming)
    if not normalized:
        return {"status": "not_found", "normalized": "", "reason": "invalid_phone"}

    variants = get_phone_lookup_variants(incoming)
    cur = db.subscriber_phones.find(
        {"company_id": company_id,
         "normalized_number": {"$in": variants}},
        {"_id": 0, "subscriber_id": 1},
    )
    sids = list({d["subscriber_id"] async for d in cur})

    # Auditoria
    await db.subscriber_match_log.insert_one({
        "id": f"smlog-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "incoming": incoming,
        "normalized": normalized,
        "matched_count": len(sids),
        "subscriber_ids": sids,
        "at": now_iso(),
    })

    if not sids:
        return {"status": "not_found", "normalized": normalized}
    if len(sids) > 1:
        subs = await db.subscribers.find(
            {"company_id": company_id, "id": {"$in": sids}},
            {"_id": 0, "id": 1, "name": 1, "status": 1, "plan_name": 1},
        ).to_list(10)
        return {"status": "conflict", "matches": subs, "normalized": normalized}

    sub = await db.subscribers.find_one(
        {"company_id": company_id, "id": sids[0]}, {"_id": 0})
    return {"status": "matched", "subscriber": sub, "normalized": normalized}


async def build_subscriber_context(company_id: str, subscriber_id: str) -> str:
    """Monta bloco de texto para injetar no system_prompt do agente IA.

    Inclui dados básicos + histórico recente. Dados sensíveis (CPF/endereço
    completo) são suprimidos por padrão.
    """
    sub = await db.subscribers.find_one(
        {"company_id": company_id, "id": subscriber_id}, {"_id": 0})
    if not sub:
        return ""
    parts = [
        "Contexto do assinante identificado:",
        f"Nome: {sub.get('name', '—')}",
        f"Status: {sub.get('status', '—')}",
    ]
    if sub.get("plan_name"):
        parts.append(f"Plano: {sub['plan_name']}")
    addr = await db.subscriber_addresses.find_one(
        {"company_id": company_id, "subscriber_id": subscriber_id, "is_primary": True},
        {"_id": 0, "district": 1, "city": 1})
    if addr:
        loc = " — ".join([p for p in [addr.get("district"), addr.get("city")] if p])
        if loc:
            parts.append(f"Localização: {loc}")
    if sub.get("tags"):
        parts.append(f"Tags: {', '.join(sub['tags'])}")
    if sub.get("notes"):
        parts.append(f"Notas internas: {sub['notes'][:300]}")

    # Últimas 5 interações (chamadas + conversas)
    recent_calls = await db.aihub_calls.find(
        {"company_id": company_id, "subscriber_id": subscriber_id},
        {"_id": 0, "started_at": 1, "status": 1, "summary": 1, "direction": 1},
    ).sort("started_at", -1).to_list(5)
    if recent_calls:
        parts.append("\nÚltimas interações por chamada:")
        for c in recent_calls:
            line = f"- {c.get('started_at', '')[:10]} ({c.get('direction', '?')}, {c.get('status', '?')})"
            if c.get("summary"):
                line += f" — {c['summary'][:120]}"
            parts.append(line)

    parts.append(
        "\nRegras: chame o cliente pelo nome quando apropriado; não exponha "
        "CPF, endereço completo ou dados financeiros sem confirmar identidade; "
        "se for cancelamento, cobrança ou reclamação grave, transfira para humano."
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.get("")
async def list_subscribers(
    q: Optional[str] = None,
    name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    document: Optional[str] = None,
    street: Optional[str] = None,
    number: Optional[str] = None,
    district: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip_code: Optional[str] = None,
    complement: Optional[str] = None,
    branch: Optional[str] = None,
    billing_method: Optional[str] = None,
    contract_status: Optional[str] = None,
    status: Optional[str] = None,
    plan: Optional[str] = None,
    tag: Optional[str] = None,
    external_code: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    user: dict = Depends(require_role("gestor")),
):
    cid = _cid(user)
    flt: Dict[str, Any] = {"company_id": cid}
    if status:
        flt["status"] = status
    if plan:
        flt["plan_name"] = {"$regex": plan, "$options": "i"}
    if tag:
        flt["tags"] = tag
    if branch:
        flt["branch"] = branch
    if billing_method:
        flt["billing_method"] = billing_method
    if contract_status:
        flt["contract_status"] = contract_status
    if external_code:
        flt["external_code"] = external_code
    if name:
        flt["$or"] = [
            {"name": {"$regex": name, "$options": "i"}},
            {"nickname": {"$regex": name, "$options": "i"}},
        ]
    if email:
        flt["email"] = {"$regex": email, "$options": "i"}
    if document:
        flt["$or"] = (flt.get("$or") or []) + [
            {"document": {"$regex": document, "$options": "i"}},
            {"rg_ie": {"$regex": document, "$options": "i"}},
        ]
    if q:
        flt["$or"] = (flt.get("$or") or []) + [
            {"name": {"$regex": q, "$options": "i"}},
            {"nickname": {"$regex": q, "$options": "i"}},
            {"document": {"$regex": q, "$options": "i"}},
            {"external_code": {"$regex": q, "$options": "i"}},
            {"email": {"$regex": q, "$options": "i"}},
        ]

    # Filtros que precisam join via subscriber_phones / addresses
    sids_phone: Optional[set] = None
    sids_address: Optional[set] = None
    if phone:
        # Busca por sufixo dos últimos 8 dígitos (suficiente para casar
        # com qualquer formato — independente de DDI/zero/máscara).
        digits = re.sub(r"\D", "", phone)
        suffix = digits[-8:] if len(digits) >= 8 else digits
        if suffix:
            sids_phone = {p["subscriber_id"] async for p in db.subscriber_phones.find(
                {"company_id": cid,
                 "normalized_number": {"$regex": f"{suffix}$"}},
                {"_id": 0, "subscriber_id": 1})}
        else:
            sids_phone = set()
    if any([street, number, district, city, state, zip_code, complement]):
        addr_flt: Dict[str, Any] = {"company_id": cid}
        if street:
            addr_flt["street"] = {"$regex": street, "$options": "i"}
        if number:
            addr_flt["number"] = number
        if district:
            addr_flt["district"] = {"$regex": district, "$options": "i"}
        if city:
            addr_flt["city"] = {"$regex": city, "$options": "i"}
        if state:
            addr_flt["state"] = state.upper()
        if zip_code:
            addr_flt["zip_code"] = {"$regex": zip_code}
        if complement:
            addr_flt["complement"] = {"$regex": complement, "$options": "i"}
        sids_address = {a["subscriber_id"] async for a in db.subscriber_addresses.find(
            addr_flt, {"_id": 0, "subscriber_id": 1})}
    sids_filter: Optional[List[str]] = None
    if sids_phone is not None and sids_address is not None:
        sids_filter = list(sids_phone & sids_address)
    elif sids_phone is not None:
        sids_filter = list(sids_phone)
    elif sids_address is not None:
        sids_filter = list(sids_address)
    if sids_filter is not None:
        if not sids_filter:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        flt["id"] = {"$in": sids_filter}

    total = await db.subscribers.count_documents(flt)
    skip = max((page - 1) * page_size, 0)
    rows = await db.subscribers.find(flt, {"_id": 0}).sort(
        "name", 1).skip(skip).limit(min(max(page_size, 1), 500)).to_list(500)

    sids = [r["id"] for r in rows]
    primaries: Dict[str, dict] = {}
    addresses_primary: Dict[str, dict] = {}
    if sids:
        async for p in db.subscriber_phones.find(
            {"company_id": cid, "subscriber_id": {"$in": sids}, "is_primary": True},
            {"_id": 0, "subscriber_id": 1, "normalized_number": 1, "raw_number": 1},
        ):
            primaries[p["subscriber_id"]] = p
        async for a in db.subscriber_addresses.find(
            {"company_id": cid, "subscriber_id": {"$in": sids}, "is_primary": True},
            {"_id": 0, "subscriber_id": 1, "street": 1, "number": 1,
             "district": 1, "city": 1, "state": 1},
        ):
            addresses_primary[a["subscriber_id"]] = a

    items = []
    for r in rows:
        prim = primaries.get(r["id"])
        addr = addresses_primary.get(r["id"]) or {}
        addr_str = ""
        if addr:
            addr_str = ", ".join([p for p in [
                f"{addr.get('street', '')} {addr.get('number', '') or ''}".strip(),
                addr.get("district"), addr.get("city"),
            ] if p])
        items.append({
            **r,
            "primary_phone": prim.get("raw_number") if prim else None,
            "primary_phone_normalized": prim.get("normalized_number") if prim else None,
            "primary_address_summary": addr_str,
            "document_masked": _mask_doc(r.get("document")),
            "document": None,  # Não retorna document raw na listagem (privacidade)
        })
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if page_size else 1,
    }


@router.post("")
async def create_subscriber(payload: SubscriberIn,
                             user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    sid = f"sub-{uuid.uuid4().hex[:10]}"

    # REGRA: external_code é AUTO-GERADO. Qualquer valor enviado pelo
    # cliente é ignorado. Formato: ASS-00001 (5 dígitos).
    seq = await _next_subscriber_seq(cid)
    external_code = f"ASS-{seq:05d}"

    doc = payload.model_dump(exclude={"phones", "addresses",
                                        "external_code"})
    # REGRA: nickname default = primeiro nome se vazio
    if not doc.get("nickname"):
        doc["nickname"] = _derive_nickname(payload.name)
    # Snapshot do plano (se plan_id foi enviado)
    plan_snap = await _hydrate_plan(cid, payload.plan_id)
    if plan_snap:
        doc.update(plan_snap)
    doc.update({
        "id": sid,
        "external_code": external_code,
        "company_id": cid,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user.get("name") or user.get("email"),
    })
    await db.subscribers.insert_one(dict(doc))
    await _replace_phones(cid, sid, payload.phones)
    await _replace_addresses(cid, sid, payload.addresses)

    sub = await db.subscribers.find_one({"id": sid, "company_id": cid}, {"_id": 0})
    return await _hydrate(sub)


@router.get("/conflicts")
async def list_conflicts(user: dict = Depends(require_role("gestor"))):
    """Lista telefones normalizados vinculados a >1 assinante."""
    cid = _cid(user)
    pipeline = [
        {"$match": {"company_id": cid}},
        {"$group": {
            "_id": "$normalized_number",
            "count": {"$sum": 1},
            "subscriber_ids": {"$addToSet": "$subscriber_id"},
        }},
        {"$match": {"count": {"$gt": 1}}},
        {"$limit": 100},
    ]
    rows = await db.subscriber_phones.aggregate(pipeline).to_list(100)
    return {"items": [
        {"normalized_number": r["_id"], "count": r["count"],
         "subscriber_ids": r["subscriber_ids"]}
        for r in rows
    ]}


@router.post("/match-phone")
async def match_phone(payload: MatchPhoneIn,
                       user: dict = Depends(require_role("gestor"))):
    """Endpoint diagnóstico: testa normalização + busca."""
    cid = _cid(user)
    return await find_subscriber_by_phone(cid, payload.phone)


@router.get("/search")
async def search_subscribers(q: str,
                                limit: int = 10,
                                user: dict = Depends(require_role("gestor"))):
    """Busca rápida (autocomplete) por nome, CPF ou telefone — usado no modal
    de Agendamento e em outras seleções de cliente no chat.
    """
    cid = _cid(user)
    q = (q or "").strip()
    if len(q) < 2:
        return {"items": []}
    digits = "".join(c for c in q if c.isdigit())
    or_filters = [{"name": {"$regex": q, "$options": "i"}}]
    if digits:
        or_filters.append({"document": {"$regex": digits}})
        # Junta com tabela de telefones
        sphs = await db.subscriber_phones.find(
            {"company_id": cid, "phone": {"$regex": digits}},
            {"_id": 0, "subscriber_id": 1},
        ).limit(50).to_list(50)
        sids = [s["subscriber_id"] for s in sphs]
        if sids:
            or_filters.append({"id": {"$in": sids}})
    items = await db.subscribers.find(
        {"company_id": cid, "$or": or_filters},
        {"_id": 0, "id": 1, "name": 1, "document": 1, "email": 1, "due_day": 1,
         "external_code": 1, "plan_name": 1, "status": 1},
    ).limit(min(max(limit, 1), 30)).to_list(30)
    return {"items": items, "count": len(items)}


@router.get("/by-phone")
async def by_phone(phone: str,
                     user: dict = Depends(require_role("gestor"))):
    """Resolve um telefone para o assinante correspondente (1ª ocorrência)."""
    cid = _cid(user)
    res = await find_subscriber_by_phone(cid, phone)
    sub = res.get("subscriber") if res.get("status") == "matched" else None
    return {"subscriber": sub, "status": res.get("status"), "normalized": res.get("normalized")}


@router.get("/{sid}")
async def get_subscriber(sid: str,
                          user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    sub = await db.subscribers.find_one(
        {"company_id": cid, "id": sid}, {"_id": 0})
    if not sub:
        raise HTTPException(404, "Assinante não encontrado.")
    return await _hydrate(sub)


@router.patch("/{sid}")
async def update_subscriber(sid: str, payload: SubscriberUpdate,
                             user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    upd = {k: v for k, v in payload.model_dump(exclude_unset=True).items()
           if v is not None}
    # REGRA: external_code é imutável — bloqueia tentativa de update silenciosamente
    upd.pop("external_code", None)
    if not upd:
        raise HTTPException(400, "Nada para atualizar.")
    # REGRA: se nome mudou e usuário NÃO setou apelido custom, mantém o atual.
    # Se mudou nome E o nickname atual é o primeiro nome antigo, atualiza.
    if "name" in upd and "nickname" not in upd:
        current = await db.subscribers.find_one(
            {"company_id": cid, "id": sid},
            {"_id": 0, "name": 1, "nickname": 1})
        if current:
            old_default = _derive_nickname(current.get("name") or "")
            if (current.get("nickname") or "") == old_default:
                upd["nickname"] = _derive_nickname(upd["name"])
    # Se plan_id mudou, atualiza snapshot
    if "plan_id" in upd:
        plan_snap = await _hydrate_plan(cid, upd["plan_id"])
        if plan_snap:
            upd.update(plan_snap)
    upd["updated_at"] = now_iso()
    res = await db.subscribers.update_one(
        {"company_id": cid, "id": sid}, {"$set": upd})
    if res.matched_count == 0:
        raise HTTPException(404, "Assinante não encontrado.")
    sub = await db.subscribers.find_one(
        {"company_id": cid, "id": sid}, {"_id": 0})
    return await _hydrate(sub)


@router.delete("/{sid}")
async def delete_subscriber(sid: str,
                             user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    res = await db.subscribers.delete_one({"company_id": cid, "id": sid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Assinante não encontrado.")
    await db.subscriber_phones.delete_many(
        {"company_id": cid, "subscriber_id": sid})
    await db.subscriber_addresses.delete_many(
        {"company_id": cid, "subscriber_id": sid})
    return {"ok": True, "deleted": sid}


@router.post("/{sid}/phones")
async def add_phone(sid: str, payload: PhoneIn,
                     user: dict = Depends(require_role("gestor"))):
    """REGRA: todo telefone adicionado é PRINCIPAL e VINCULANTE."""
    cid = _cid(user)
    if not await db.subscribers.find_one({"company_id": cid, "id": sid}, {"_id": 1}):
        raise HTTPException(404, "Assinante não encontrado.")
    normalized = normalize_brazilian_phone(payload.raw_number)
    if not normalized:
        raise HTTPException(400, "Telefone inválido.")
    doc = {
        "id": f"sphone-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "subscriber_id": sid,
        "label": payload.label,
        "raw_number": payload.raw_number,
        "normalized_number": normalized,
        "is_whatsapp": True,
        "is_primary": True,
        "created_at": now_iso(),
    }
    await db.subscriber_phones.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.delete("/{sid}/phones/{phone_id}")
async def delete_phone(sid: str, phone_id: str,
                        user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    res = await db.subscriber_phones.delete_one(
        {"company_id": cid, "subscriber_id": sid, "id": phone_id})
    return {"ok": True, "deleted": res.deleted_count}


@router.get("/{sid}/history")
async def subscriber_history(sid: str,
                              user: dict = Depends(require_role("gestor"))):
    """Histórico de chamadas/conversas do assinante (últimos 50 de cada)."""
    cid = _cid(user)
    if not await db.subscribers.find_one(
            {"company_id": cid, "id": sid}, {"_id": 1}):
        raise HTTPException(404, "Assinante não encontrado.")
    calls = await db.aihub_calls.find(
        {"company_id": cid, "subscriber_id": sid}, {"_id": 0, "raw": 0},
    ).sort("started_at", -1).to_list(50)
    sessions_pipeline = [
        {"$match": {"company_id": cid, "subscriber_id": sid}},
        {"$group": {
            "_id": "$session_id",
            "first_at": {"$min": "$created_at"},
            "last_at": {"$max": "$created_at"},
            "msg_count": {"$sum": 1},
            "agent_id": {"$first": "$agent_id"},
        }},
        {"$sort": {"last_at": -1}},
        {"$limit": 50},
    ]
    sessions = await db.aihub_messages.aggregate(sessions_pipeline).to_list(50)
    return {
        "calls": calls,
        "sessions": [
            {"session_id": s["_id"], "first_at": s["first_at"],
             "last_at": s["last_at"], "msg_count": s["msg_count"],
             "agent_id": s.get("agent_id")}
            for s in sessions
        ],
    }


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------
CSV_FIELDS_MAP = {
    "nome": "name", "documento": "document", "cpf": "document", "cnpj": "document",
    "codigo_externo": "external_code", "codigo": "external_code",
    "telefone_principal": "phone1", "telefone": "phone1",
    "telefone_2": "phone2", "telefone_3": "phone3",
    "email": "email", "status": "status",
    "plano": "plan_name", "velocidade": "plan_speed", "valor": "plan_price",
    "endereco": "street", "numero": "number", "complemento": "complement",
    "bairro": "district", "cidade": "city", "estado": "state", "cep": "zip_code",
    "observacoes": "notes", "tags": "tags",
}


@router.post("/import")
async def import_csv(file: UploadFile = File(...),
                      user: dict = Depends(require_role("gestor"))):
    """Importa assinantes via CSV. Aceita colunas em PT-BR (acentos opcionais)."""
    cid = _cid(user)
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text), delimiter=",")
    created = 0
    updated = 0
    errors: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []

    for row_num, row in enumerate(reader, start=2):
        try:
            mapped: Dict[str, Any] = {}
            phones_raw: List[str] = []
            for k, v in row.items():
                key = (k or "").strip().lower().replace("ç", "c").replace("ã", "a")
                mk = CSV_FIELDS_MAP.get(key)
                val = (v or "").strip()
                if not val:
                    continue
                if mk in ("phone1", "phone2", "phone3"):
                    phones_raw.append(val)
                elif mk == "tags":
                    mapped["tags"] = [t.strip() for t in val.split("|") if t.strip()]
                elif mk == "plan_price":
                    try:
                        mapped["plan_price"] = float(
                            val.replace(".", "").replace(",", "."))
                    except ValueError:
                        pass
                elif mk:
                    mapped[mk] = val

            if not mapped.get("name"):
                errors.append({"row": row_num, "error": "campo 'nome' ausente"})
                continue

            ext = mapped.get("external_code")
            existing = None
            if ext:
                existing = await db.subscribers.find_one(
                    {"company_id": cid, "external_code": ext}, {"_id": 0, "id": 1})

            phones_in = [
                PhoneIn(raw_number=p, is_primary=(i == 0))
                for i, p in enumerate(phones_raw) if p
            ]
            address_payload = AddressIn(
                street=mapped.get("street"), number=mapped.get("number"),
                complement=mapped.get("complement"), district=mapped.get("district"),
                city=mapped.get("city"), state=(mapped.get("state") or "")[:2],
                zip_code=mapped.get("zip_code"), is_primary=True,
            ) if any(mapped.get(k) for k in ("street", "district", "city")) else None

            sub_payload = {
                k: v for k, v in mapped.items()
                if k in ("name", "document", "external_code", "email", "status",
                         "plan_name", "plan_speed", "plan_price", "notes", "tags")
            }
            if "status" in sub_payload:
                sub_payload["status"] = sub_payload["status"].upper()
                if sub_payload["status"] not in (
                        "ATIVO", "BLOQUEADO", "SUSPENSO", "CANCELADO",
                        "EM_INSTALACAO", "AGUARDANDO_VIABILIDADE",
                        "SEM_VIABILIDADE", "PROSPECT", "INADIMPLENTE"):
                    sub_payload["status"] = "ATIVO"

            if existing:
                # Update
                sub_payload["updated_at"] = now_iso()
                await db.subscribers.update_one(
                    {"company_id": cid, "id": existing["id"]},
                    {"$set": sub_payload})
                if phones_in:
                    await _replace_phones(cid, existing["id"], phones_in)
                if address_payload:
                    await _replace_addresses(cid, existing["id"], [address_payload])
                updated += 1
            else:
                sid = f"sub-{uuid.uuid4().hex[:10]}"
                doc = {
                    **sub_payload,
                    "id": sid, "company_id": cid,
                    "created_at": now_iso(), "updated_at": now_iso(),
                    "created_by": user.get("name") or user.get("email"),
                }
                # Validation com modelo (filtros adicionais)
                try:
                    SubscriberIn(**{**sub_payload, "name": sub_payload.get("name", "")})
                except Exception as ve:
                    errors.append({"row": row_num, "error": f"validação: {ve}"})
                    continue

                await db.subscribers.insert_one(dict(doc))

                # Detecta conflito antes de inserir telefones
                phone_conflicts = []
                for p in phones_in:
                    norm = normalize_brazilian_phone(p.raw_number)
                    if not norm:
                        continue
                    existing_phone = await db.subscriber_phones.find_one(
                        {"company_id": cid, "normalized_number": norm}, {"_id": 0})
                    if existing_phone:
                        phone_conflicts.append({
                            "phone": norm,
                            "owner_subscriber_id": existing_phone["subscriber_id"],
                        })
                if phone_conflicts:
                    conflicts.append({
                        "row": row_num, "subscriber_id": sid,
                        "name": mapped.get("name"), "phone_conflicts": phone_conflicts,
                    })

                await _replace_phones(cid, sid, phones_in)
                if address_payload:
                    await _replace_addresses(cid, sid, [address_payload])
                created += 1
        except Exception as e:
            errors.append({"row": row_num, "error": str(e)[:200]})

    return {
        "created": created, "updated": updated,
        "errors": errors, "conflicts": conflicts,
    }
