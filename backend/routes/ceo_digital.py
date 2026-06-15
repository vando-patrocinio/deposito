"""CEO BRIEFING API — endpoints públicos para ChatGPT Custom GPT.

Auth: Bearer CEO_BRIEFING_TOKEN (env). Sem login/sessão — facilitar Actions.
Tudo READ-ONLY. Tudo restrito a `co-demo`. Tudo lê de ONE TRUTH + executive_memory.

Endpoints:
- GET  /api/ceo/openapi.json          (público · contrato p/ Custom GPT)
- POST /api/ceo/briefing/now          (auth · gera+persiste snapshot + texto)
- GET  /api/ceo/briefing/today        (auth · só leitura do snapshot do dia)
- GET  /api/ceo/memory?days=30        (auth · array 30d compacto)
- GET  /api/ceo/metas                 (auth · METAS_2026)
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "ceo_digital",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse

from database import db
from services import executive_memory as em

router = APIRouter(prefix="/api/ceo", tags=["ceo-digital"])

CO = "co-demo"
TOKEN_ENV = "CEO_BRIEFING_TOKEN"


async def require_token(authorization: Optional[str] = Header(default=None)) -> None:
    expected = os.environ.get(TOKEN_ENV)
    if not expected:
        raise HTTPException(503, "CEO_BRIEFING_TOKEN não configurado no servidor")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer token ausente")
    sent = authorization.split(" ", 1)[1].strip()
    if sent != expected:
        raise HTTPException(401, "token inválido")


# ────────────────────────────── BRIEFING ──────────────────────────────
def _format_brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _build_text(snap: dict) -> str:
    ot = snap.get("one_truth") or {}
    cmp_b = snap.get("compare") or {}
    course = snap.get("course_correction") or {}
    summary = snap.get("course_summary") or ""

    def trend(field: str) -> str:
        d = ((cmp_b.get(field) or {}).get("7d") or {}).get("abs") or 0.0
        if d > 0:
            return f"+{d:g}"
        if d < 0:
            return f"{d:g}"
        return "0"

    lines = [
        f"☕ CEO BRIEFING · {snap.get('date_key')}",
        "",
        "ESTADO DA EMPRESA",
        f"  Clientes ativos: {ot.get('clientes_ativos')} (7d {trend('clientes_ativos')})",
        f"  MRR: {_format_brl(ot.get('mrr') or 0)} "
        f"(7d {trend('mrr')})",
        f"  Inadimplência: {_format_brl(ot.get('inadimplencia_brl') or 0)} "
        f"em {ot.get('inadimplencia_n_faturas')} faturas",
        f"  Tickets abertos: {ot.get('tickets_abertos')}",
        f"  Fundadores aptos: {ot.get('fundadores_aptos')} · "
        f"Embaixadores: {ot.get('embaixadores')}",
        "",
        "COURSE CORRECTION (vs meta anual / projeção 90d)",
    ]
    for kpi, c in course.items():
        emoji = {"adiantado": "🟢", "no_rumo": "🟢",
                 "melhorando": "🟢", "estavel": "🟡",
                 "atrasado": "🟠", "piorando": "🔴",
                 "critico": "🔴"}.get(c.get("status"), "⚪")
        lines.append(f"  {emoji} {kpi}: status={c.get('status')} · "
                     f"30d={c.get('delta_30d_abs'):+g} · "
                     f"meta_mes={c.get('monthly_needed_abs'):+g} · "
                     f"projeção 90d={c.get('projected_90d'):g} "
                     f"(meta {c.get('target')})")
    lines.append("")
    lines.append(f"RESUMO: {summary}")
    lines.append("")
    lines.append("DECISÃO SUGERIDA")
    # heurística mínima: pega o pior KPI (status crítico/atrasado) e aponta foco
    worst = None
    for kpi, c in course.items():
        st = c.get("status")
        if st in ("critico", "piorando"):
            worst = kpi; break
        if st in ("atrasado",) and not worst:
            worst = kpi
    if worst:
        lines.append(f"  Foco da semana: acelerar {worst}. "
                     f"Hoje a projeção 90d fica em "
                     f"{course[worst]['projected_90d']:g} contra meta "
                     f"{course[worst]['target']}.")
    else:
        lines.append("  Manter o ritmo · todos KPIs dentro da rota.")
    return "\n".join(lines)


# ────────────────────────────── OPENAPI ──────────────────────────────
@router.get("/openapi.json", include_in_schema=False)
async def openapi_spec(request_url: str = ""):
    base = os.environ.get("PUBLIC_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL") or ""

    BriefingSchema = {
        "type": "object",
        "properties": {
            "date": {"type": "string"},
            "clientes_ativos": {"type": "integer"},
            "mrr_brl": {"type": "number"},
            "inadimplencia_brl": {"type": "number"},
            "inadimplencia_n_faturas": {"type": "integer"},
            "tickets_abertos": {"type": "integer"},
            "fundadores_aptos": {"type": "integer"},
            "embaixadores": {"type": "integer"},
            "course_summary": {"type": "string"},
            "course_status": {
                "type": "object",
                "properties": {
                    "clientes_ativos": {"type": "string"},
                    "mrr": {"type": "string"},
                    "inadimplencia_brl": {"type": "string"},
                    "embaixadores": {"type": "string"},
                    "fundadores_aptos": {"type": "string"},
                },
            },
            "briefing_text": {"type": "string"},
        },
    }

    MemorySchema = {
        "type": "object",
        "properties": {
            "days_returned": {"type": "integer"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "date_key": {"type": "string"},
                        "kpis": {"type": "object", "additionalProperties": True},
                        "course": {"type": "object", "additionalProperties": True},
                        "summary": {"type": "string"},
                    },
                },
            },
        },
    }

    MetasSchema = {
        "type": "object",
        "properties": {
            "metas_2026": {"type": "object", "additionalProperties": True},
            "baseline_date": {"type": "string"},
        },
    }

    return JSONResponse({
        "openapi": "3.1.0",
        "info": {
            "title": "SmartProv CEO Digital API",
            "description": (
                "Endpoints somente-leitura para o ChatGPT Custom GPT do CEO "
                "da Ligo. Briefing executivo, memoria 30d e metas oficiais. "
                "Lê dados reais do SmartProv: clientes, MRR, inadimplencia, "
                "tickets, fundadores, embaixadores."
            ),
            "version": "1.0.0",
        },
        "servers": [{"url": (base.rstrip("/") if base else "https://EDITAR-AQUI")}],
        "security": [{"BearerAuth": []}],
        "paths": {
            "/api/ceo/briefing/today": {
                "get": {
                    "operationId": "ceoBriefingToday",
                    "summary": "Briefing executivo do dia",
                    "description": (
                        "Retorna snapshot de hoje com KPIs reais, comparacoes "
                        "vs ontem/7d/30d, course_correction por KPI e texto "
                        "pronto do briefing."
                    ),
                    "responses": {
                        "200": {
                            "description": "Briefing executivo completo",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Briefing"}
                                }
                            },
                        }
                    },
                }
            },
            "/api/ceo/briefing/now": {
                "post": {
                    "operationId": "ceoBriefingNow",
                    "summary": "Gera snapshot novo agora",
                    "description": (
                        "Forca recalculo do snapshot do dia e devolve briefing "
                        "atualizado."
                    ),
                    "responses": {
                        "200": {
                            "description": "Snapshot atualizado",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Briefing"}
                                }
                            },
                        }
                    },
                }
            },
            "/api/ceo/memory": {
                "get": {
                    "operationId": "ceoMemory",
                    "summary": "Memoria executiva 30 dias",
                    "description": (
                        "Retorna array compacto dos snapshots dos ultimos N "
                        "dias para analise de tendencia."
                    ),
                    "parameters": [{
                        "name": "days", "in": "query", "required": False,
                        "description": "Numero de dias (default 30, max 365)",
                        "schema": {"type": "integer", "default": 30,
                                     "minimum": 1, "maximum": 365},
                    }],
                    "responses": {
                        "200": {
                            "description": "Array de snapshots",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Memory"}
                                }
                            },
                        }
                    },
                }
            },
            "/api/ceo/metas": {
                "get": {
                    "operationId": "ceoMetas",
                    "summary": "Metas anuais oficiais Ligo 2026",
                    "description": (
                        "Retorna baseline e target de cada KPI estrategico "
                        "(clientes, MRR, inadimplencia, embaixadores, "
                        "fundadores)."
                    ),
                    "responses": {
                        "200": {
                            "description": "Metas oficiais",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Metas"}
                                }
                            },
                        }
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "Briefing": BriefingSchema,
                "Memory": MemorySchema,
                "Metas": MetasSchema,
            },
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer"}
            },
        },
    })


# ────────────────────────────── ENDPOINTS ──────────────────────────────
@router.post("/briefing/now", dependencies=[Depends(require_token)])
async def briefing_now():
    snap = await em.snapshot_today(CO)
    snap["briefing_text"] = _build_text(snap)
    return snap


@router.get("/briefing/today", dependencies=[Depends(require_token)])
async def briefing_today():
    today = datetime.now(timezone.utc).date().isoformat()
    doc = await db.president_daily.find_one(
        {"company_id": CO, "date_key": today, "one_truth": {"$exists": True}},
        {"_id": 0})
    if not doc:
        snap = await em.snapshot_today(CO)
    else:
        snap = {"date_key": today,
                "one_truth": doc.get("one_truth"),
                "compare": doc.get("compare"),
                "course_correction": doc.get("course_correction"),
                "course_summary": doc.get("course_summary")}
    text = _build_text(snap)
    ot = snap.get("one_truth") or {}
    course = snap.get("course_correction") or {}
    # Payload enxuto: só o que o LLM precisa pra narrar.
    return {
        "date": snap.get("date_key"),
        "clientes_ativos": ot.get("clientes_ativos"),
        "mrr_brl": ot.get("mrr"),
        "inadimplencia_brl": ot.get("inadimplencia_brl"),
        "inadimplencia_n_faturas": ot.get("inadimplencia_n_faturas"),
        "tickets_abertos": ot.get("tickets_abertos"),
        "fundadores_aptos": ot.get("fundadores_aptos"),
        "embaixadores": ot.get("embaixadores"),
        "course_summary": snap.get("course_summary"),
        "course_status": {k: v.get("status") for k, v in course.items()},
        "briefing_text": text,
    }


@router.get("/memory", dependencies=[Depends(require_token)])
async def memory(days: int = 30):
    days = max(1, min(days, 365))
    cur = db.president_daily.find(
        {"company_id": CO, "one_truth": {"$exists": True}},
        {"_id": 0, "date_key": 1, "one_truth": 1,
         "course_correction": 1, "course_summary": 1},
        sort=[("date_key", -1)], limit=days)
    items = []
    async for d in cur:
        items.append({
            "date_key": d.get("date_key"),
            "kpis": d.get("one_truth") or {},
            "course": d.get("course_correction") or {},
            "summary": d.get("course_summary"),
        })
    return {"days_returned": len(items), "items": items}


@router.get("/metas", dependencies=[Depends(require_token)])
async def metas():
    return {"metas_2026": em.METAS_2026, "baseline_date": em.BASELINE_DATE}
