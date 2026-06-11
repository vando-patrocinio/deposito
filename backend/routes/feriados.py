"""Módulo Feriados — calendário de feriados (nacional/estadual/municipal/empresa).

Usado pela folha de ponto e por relatórios pra:
- Marcar dias não trabalhados
- Calcular horas extras em feriados
- Bloquear escalas em datas específicas

Endpoints:
- GET    /api/feriados            lista (filtro por ano)
- POST   /api/feriados            cria 1 feriado
- PUT    /api/feriados/{id}       atualiza
- DELETE /api/feriados/{id}       remove
- POST   /api/feriados/seed-br    popula feriados nacionais BR (ano)
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

import logging
import uuid
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.feriados")
router = APIRouter(prefix="/api/feriados", tags=["feriados"])

TIPOS = {"nacional", "estadual", "municipal", "empresa"}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class FeriadoIn(BaseModel):
    data: str = Field(..., min_length=10, max_length=10,
                          description="YYYY-MM-DD")
    nome: str = Field(..., min_length=2, max_length=120)
    tipo: str = Field("nacional")
    uf: Optional[str] = Field(None, max_length=2)
    municipio: Optional[str] = Field(None, max_length=80)
    recorrente: bool = True
    observacao: Optional[str] = Field(None, max_length=400)
    # IDs das praças onde este feriado se aplica. Lista vazia/None → vale
    # para TODOS os colaboradores da empresa (típico de feriado nacional).
    # Quando tem IDs, só vale para colaboradores cuja praca_id (ou
    # praca_ids_extra) esteja na lista.
    praca_ids: list[str] = Field(default_factory=list)

    @field_validator("tipo")
    @classmethod
    def _v_tipo(cls, v: str) -> str:
        v = (v or "").lower().strip()
        if v not in TIPOS:
            raise ValueError(f"tipo deve ser um de: {', '.join(sorted(TIPOS))}")
        return v

    @field_validator("data")
    @classmethod
    def _v_data(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except Exception as exc:
            raise ValueError("data inválida — use YYYY-MM-DD") from exc
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _easter(year: int) -> date:
    """Algoritmo de Gauss/Anonymous Gregorian para Páscoa."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    L = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * L) // 451
    month = (h + L - 7 * m + 114) // 31
    day = ((h + L - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _br_national_holidays(year: int) -> list[dict]:
    """Lista oficial de feriados nacionais brasileiros pro ano."""
    easter = _easter(year)
    items = [
        # Fixos
        (date(year, 1, 1),  "Confraternização Universal"),
        (date(year, 4, 21), "Tiradentes"),
        (date(year, 5, 1),  "Dia do Trabalho"),
        (date(year, 9, 7),  "Independência do Brasil"),
        (date(year, 10, 12), "Nossa Senhora Aparecida"),
        (date(year, 11, 2),  "Finados"),
        (date(year, 11, 15), "Proclamação da República"),
        (date(year, 11, 20), "Consciência Negra"),
        (date(year, 12, 25), "Natal"),
        # Móveis (baseados na Páscoa)
        (easter - timedelta(days=48), "Carnaval (segunda)"),
        (easter - timedelta(days=47), "Carnaval (terça)"),
        (easter - timedelta(days=2),  "Sexta-feira Santa"),
        (easter,                      "Páscoa"),
        (easter + timedelta(days=60), "Corpus Christi"),
    ]
    return [{"data": d.isoformat(), "nome": n,
                 "tipo": "nacional", "recorrente": True} for d, n in items]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("")
async def list_feriados(year: Optional[int] = None,
                            tipo: Optional[str] = None,
                            user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    filt: dict = {"company_id": cid}
    if year:
        filt["data"] = {"$regex": f"^{int(year)}-"}
    if tipo and tipo in TIPOS:
        filt["tipo"] = tipo
    docs = await db.feriados.find(filt, {"_id": 0}) \
        .sort("data", 1).limit(500).to_list(500)
    return {"items": docs, "count": len(docs)}


@router.post("")
async def create_feriado(payload: FeriadoIn,
                              user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # Evita duplicata (mesma empresa + data + nome)
    existing = await db.feriados.find_one(
        {"company_id": cid, "data": payload.data, "nome": payload.nome},
        {"_id": 0, "id": 1},
    )
    if existing:
        raise HTTPException(409, "Já existe feriado com essa data e nome.")
    doc = {
        "id": f"fer-{uuid.uuid4().hex[:14]}",
        "company_id": cid,
        **payload.model_dump(),
        "created_at": now_iso(),
        "created_by": user.get("id"),
    }
    await db.feriados.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


@router.put("/{fid}")
async def update_feriado(fid: str, payload: FeriadoIn,
                              user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    r = await db.feriados.update_one(
        {"id": fid, "company_id": cid},
        {"$set": {**payload.model_dump(), "updated_at": now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Feriado não encontrado.")
    return {"ok": True}


@router.delete("/{fid}")
async def delete_feriado(fid: str,
                              user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    r = await db.feriados.delete_one({"id": fid, "company_id": cid})
    if r.deleted_count == 0:
        raise HTTPException(404, "Feriado não encontrado.")
    return {"ok": True}


@router.post("/seed-br")
async def seed_br(year: int,
                       user: dict = Depends(require_role("gestor"))):
    """Popula feriados nacionais brasileiros para o ano informado.

    Não duplica: faz upsert por (company_id, data, nome).
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if year < 2000 or year > 2100:
        raise HTTPException(400, "Ano inválido.")
    inserted = 0
    skipped = 0
    for item in _br_national_holidays(year):
        r = await db.feriados.update_one(
            {"company_id": cid, "data": item["data"], "nome": item["nome"]},
            {
                "$setOnInsert": {
                    "id": f"fer-{uuid.uuid4().hex[:14]}",
                    "company_id": cid,
                    "tipo": "nacional",
                    "recorrente": True,
                    "created_at": now_iso(),
                    "created_by": user.get("id"),
                    **item,
                },
            },
            upsert=True,
        )
        if r.upserted_id:
            inserted += 1
        else:
            skipped += 1
    return {"ok": True, "year": year, "inserted": inserted, "skipped": skipped}
