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
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse

from database import db
from services import executive_memory as em
from services import corporate_goals as cg
from services import executive_decisions as exd

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
            worst = kpi
            break
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
            "/api/ceo/cto/message": {
                "post": {
                    "operationId": "ctoSendMessage",
                    "summary": "CEO envia mensagem direta para o CTO (Claude)",
                    "description": (
                        "Use quando o CEO quiser deixar uma ordem, pergunta tecnica, "
                        "feedback ou tarefa para o CTO/Claude. A mensagem fica em "
                        "cto_inbox aguardando resposta. Sempre confirme ao CEO que "
                        "registrou o recado e diga o message_id."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["text"],
                                    "properties": {
                                        "text": {"type": "string", "description": "Texto integral do CEO"},
                                        "priority": {"type": "string", "enum": ["p0","p1","p2","p3"], "default": "p2"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "Recado registrado",
                                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CtoMessageResult"}}}}},
                }
            },
            "/api/ceo/cto/inbox": {
                "get": {
                    "operationId": "ctoInbox",
                    "summary": "Lista mensagens trocadas com o CTO",
                    "description": (
                        "Retorna o historico de mensagens entre CEO e CTO. Use "
                        "unread_only=true para ver apenas as nao respondidas."
                    ),
                    "parameters": [
                        {"name": "unread_only", "in": "query", "required": False,
                         "schema": {"type": "boolean", "default": False}},
                        {"name": "limit", "in": "query", "required": False,
                         "schema": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100}},
                    ],
                    "responses": {"200": {"description": "Mensagens",
                                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CtoInbox"}}}}},
                }
            },
            "/api/ceo/decisions": {
                "get": {
                    "operationId": "decisionsList",
                    "summary": "Lista decisoes executivas (IA propoe -> CEO aprova)",
                    "description": (
                        "Retorna o historico de decisoes executivas. Pode filtrar "
                        "por status (proposed, approved, in_progress, done, cancelled)."
                    ),
                    "parameters": [
                        {"name": "status", "in": "query", "required": False,
                         "schema": {"type": "string"}},
                        {"name": "limit", "in": "query", "required": False,
                         "schema": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}},
                    ],
                    "responses": {"200": {"description": "Decisoes",
                                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/DecisionsList"}}}}},
                },
                "post": {
                    "operationId": "decisionsCreate",
                    "summary": "CEO ou IA cria nova decisao executiva",
                    "description": (
                        "Use quando o CEO quiser registrar uma decisao com owner e "
                        "deadline auditaveis, ou quando a IA propor uma acao para "
                        "aprovacao posterior. Status inicial default = 'proposed'."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["decision"],
                                    "properties": {
                                        "decision": {"type": "string"},
                                        "context": {"type": "string"},
                                        "related_kpi": {"type": "string"},
                                        "priority": {"type": "string", "enum": ["p0","p1","p2","p3"]},
                                        "proposed_by": {"type": "string", "enum": ["isabella","presidente_ia","cto","ceo"]},
                                        "owner": {"type": "string"},
                                        "deadline": {"type": "string", "description": "YYYY-MM-DD"},
                                        "status": {"type": "string", "enum": ["proposed","approved","in_progress","done","cancelled"]},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "Decisao criada",
                                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/DecisionResult"}}}}},
                }
            },
            "/api/ceo/decisions/{decision_id}": {
                "patch": {
                    "operationId": "decisionsUpdate",
                    "summary": "Atualiza status/owner/deadline de uma decisao",
                    "description": (
                        "Permite ao CEO mover a decisao para approved/in_progress/done/cancelled "
                        "e ajustar owner/deadline/context/priority."
                    ),
                    "parameters": [
                        {"name": "decision_id", "in": "path", "required": True,
                         "schema": {"type": "string"}},
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "status": {"type": "string", "enum": ["proposed","approved","in_progress","done","cancelled"]},
                                        "approved_by": {"type": "string"},
                                        "owner": {"type": "string"},
                                        "deadline": {"type": "string"},
                                        "context": {"type": "string"},
                                        "priority": {"type": "string", "enum": ["p0","p1","p2","p3"]},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "Decisao atualizada",
                                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/DecisionResult"}}}}},
                }
            },
            "/api/ceo/goals": {
                "get": {
                    "operationId": "goalsList",
                    "summary": "Lista metas corporativas vigentes",
                    "description": (
                        "Retorna metas armazenadas em corporate_goals (KPI, baseline, "
                        "target, direction, owner, deadline, status)."
                    ),
                    "responses": {"200": {"description": "Metas",
                                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/GoalsList"}}}}},
                }
            },
            "/api/ceo/cto/digest": {
                "get": {
                    "operationId": "ctoDigest",
                    "summary": "Primeira tela CTO-style: tudo que o CEO precisa em uma única chamada",
                    "description": (
                        "Combina em um único payload as mensagens pendentes do CTO, "
                        "as decisões aguardando aprovação do CEO, os KPIs do dia, o "
                        "course_correction e o top_focus (pior KPI). Use isto como "
                        "primeira chamada de cada conversa para economizar tokens."
                    ),
                    "responses": {"200": {"description": "Digest executivo",
                                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CtoDigest"}}}}},
                }
            },
        },
        "components": {
            "schemas": {
                "Briefing": BriefingSchema,
                "Memory": MemorySchema,
                "Metas": MetasSchema,
                "CtoMessageResult": {
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "message_id": {"type": "string"},
                        "created_at": {"type": "string"},
                    },
                },
                "CtoInbox": {
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer"},
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "from": {"type": "string"},
                                    "to": {"type": "string"},
                                    "text": {"type": "string"},
                                    "priority": {"type": "string"},
                                    "status": {"type": "string"},
                                    "in_reply_to": {"type": "string"},
                                    "action_taken": {"type": "string"},
                                    "created_at": {"type": "string"},
                                    "replied_at": {"type": "string"},
                                },
                            },
                        },
                    },
                },
                "DecisionItem": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "decision": {"type": "string"},
                        "context": {"type": "string"},
                        "related_kpi": {"type": "string"},
                        "priority": {"type": "string"},
                        "proposed_by": {"type": "string"},
                        "approved_by": {"type": "string"},
                        "owner": {"type": "string"},
                        "deadline": {"type": "string"},
                        "status": {"type": "string"},
                        "created_at": {"type": "string"},
                        "updated_at": {"type": "string"},
                        "completed_at": {"type": "string"},
                    },
                },
                "DecisionsList": {
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer"},
                        "items": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/DecisionItem"},
                        },
                    },
                },
                "DecisionResult": {
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "decision": {"$ref": "#/components/schemas/DecisionItem"},
                    },
                },
                "GoalItem": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "kpi_key": {"type": "string"},
                        "baseline": {"type": "number"},
                        "target": {"type": "number"},
                        "direction": {"type": "string"},
                        "baseline_date": {"type": "string"},
                        "owner": {"type": "string"},
                        "deadline": {"type": "string"},
                        "status": {"type": "string"},
                        "source": {"type": "string"},
                        "created_at": {"type": "string"},
                        "updated_at": {"type": "string"},
                    },
                },
                "GoalsList": {
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer"},
                        "items": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/GoalItem"},
                        },
                    },
                },
                "CtoDigest": {
                    "type": "object",
                    "properties": {
                        "generated_at": {"type": "string"},
                        "company_id": {"type": "string"},
                        "snapshot_date": {"type": "string"},
                        "counts": {
                            "type": "object",
                            "properties": {
                                "pending_messages": {"type": "integer"},
                                "cto_replies_unread": {"type": "integer"},
                                "decisions_awaiting_approval": {"type": "integer"},
                            },
                        },
                        "pending_messages": {
                            "type": "array",
                            "items": {"type": "object", "additionalProperties": True},
                        },
                        "cto_replies_unread": {
                            "type": "array",
                            "items": {"type": "object", "additionalProperties": True},
                        },
                        "decisions_awaiting_approval": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/DecisionItem"},
                        },
                        "course_summary": {"type": "string"},
                        "kpis": {"type": "object", "additionalProperties": True},
                        "course_status": {"type": "object", "additionalProperties": True},
                        "top_focus": {"type": "object", "additionalProperties": True},
                    },
                },
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
    """Lê metas do MongoDB (corporate_goals). Auto-seed na primeira chamada."""
    m = await cg.get_metas(CO)
    return {"metas_2026": m, "baseline_date": cg.BASELINE_DATE,
            "source": "corporate_goals"}


@router.get("/goals", dependencies=[Depends(require_token)])
async def goals_list():
    items = await cg.list_goals(CO)
    return {"count": len(items), "items": items}


@router.post("/goals/{kpi_key}", dependencies=[Depends(require_token)])
async def goals_upsert(kpi_key: str, payload: dict):
    res = await cg.upsert_goal(CO, kpi_key, payload or {})
    return res


@router.put("/goals/{kpi_key}", dependencies=[Depends(require_token)])
async def goals_upsert_put(kpi_key: str, payload: dict):
    """Alias PUT do POST para conformidade com spec REST."""
    res = await cg.upsert_goal(CO, kpi_key, payload or {})
    return res


# ─────────────── EXECUTIVE DECISIONS (IA propõe -> CEO aprova) ───────────────
@router.post("/decisions", dependencies=[Depends(require_token)])
async def decisions_create(payload: dict):
    try:
        doc = await exd.create_decision(CO, payload or {})
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "decision": doc}


@router.get("/decisions", dependencies=[Depends(require_token)])
async def decisions_list(status: Optional[str] = None, limit: int = 50):
    try:
        items = await exd.list_decisions(CO, status=status, limit=limit)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"count": len(items), "items": items}


@router.patch("/decisions/{decision_id}", dependencies=[Depends(require_token)])
async def decisions_update(decision_id: str, payload: dict):
    try:
        doc = await exd.update_status(CO, decision_id, payload or {})
    except ValueError as e:
        raise HTTPException(400, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, "decision": doc}


# ────────────────────────── CTO INBOX (canal direto CEO ↔ Claude) ──────────────────────────
import uuid

@router.post("/cto/message", dependencies=[Depends(require_token)])
async def cto_message(payload: dict):
    """CEO deixa um recado/pergunta/ordem para o CTO (Claude).
    Body: {"text": "...", "priority": "p0|p1|p2|p3" (opcional)}
    """
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "campo 'text' obrigatório")
    doc = {
        "id": f"cto-{uuid.uuid4().hex[:14]}",
        "from": "ceo",
        "to": "cto",
        "text": text,
        "priority": payload.get("priority", "p2"),
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.cto_inbox.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "message_id": doc["id"], "created_at": doc["created_at"]}


@router.get("/cto/inbox", dependencies=[Depends(require_token)])
async def cto_inbox(unread_only: bool = False, limit: int = 20):
    flt = {"status": "open"} if unread_only else {}
    cur = db.cto_inbox.find(flt, {"_id": 0}).sort("created_at", -1).limit(min(limit, 100))
    items = await cur.to_list(limit)
    return {"count": len(items), "items": items}


@router.post("/cto/reply", dependencies=[Depends(require_token)])
async def cto_reply(payload: dict):
    """CTO (Claude) responde a uma mensagem do CEO.
    Body: {"in_reply_to": "cto-...", "text": "...", "action_taken": "..." (opcional)}
    """
    parent_id = payload.get("in_reply_to")
    text = (payload.get("text") or "").strip()
    if not parent_id or not text:
        raise HTTPException(400, "campos 'in_reply_to' e 'text' obrigatórios")
    reply = {
        "id": f"cto-{uuid.uuid4().hex[:14]}",
        "from": "cto",
        "to": "ceo",
        "in_reply_to": parent_id,
        "text": text,
        "action_taken": payload.get("action_taken"),
        "status": "delivered",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.cto_inbox.insert_one(reply)
    await db.cto_inbox.update_one(
        {"id": parent_id},
        {"$set": {"status": "replied",
                   "replied_at": reply["created_at"]}})
    reply.pop("_id", None)
    return {"ok": True, "reply_id": reply["id"]}



# ────────────────────────── DIGEST (primeira tela CTO-style) ──────────────────────────
@router.get("/cto/digest", dependencies=[Depends(require_token)])
async def cto_digest():
    """Primeira tela CEO: tudo que precisa decidir/saber em uma única chamada.

    Retorna:
      - pending_messages: mensagens do CEO em cto_inbox com status=open (esperando CTO)
      - cto_replies_unread: respostas do CTO/system que o CEO ainda não viu (status=delivered ou open com from!=ceo)
      - decisions_awaiting_approval: executive_decisions com status=proposed
      - course_status: snapshot mais recente (date, KPIs, course_correction)
      - counts: contadores agregados para a barra de topo
    """
    # 1. Mensagens do CEO ainda não respondidas pelo CTO.
    pending_cur = db.cto_inbox.find(
        {"from": "ceo", "to": "cto", "status": "open"},
        {"_id": 0}).sort("created_at", -1).limit(20)
    pending_messages = await pending_cur.to_list(20)

    # 2. Respostas/avisos do CTO+system que o CEO ainda não confirmou leitura
    # (proxy: status=delivered ou open && from!=ceo, últimas 24h).
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    replies_cur = db.cto_inbox.find(
        {"from": {"$in": ["cto", "system"]},
         "status": {"$in": ["delivered", "open"]},
         "created_at": {"$gte": cutoff}},
        {"_id": 0}).sort("created_at", -1).limit(20)
    cto_replies_unread = await replies_cur.to_list(20)

    # 3. Decisões aguardando aprovação do CEO.
    pending_decs = await exd.list_decisions(CO, status="proposed", limit=20)

    # 4. Snapshot mais recente (course_correction + KPIs).
    today_key = datetime.now(timezone.utc).date().isoformat()
    snap = await db.president_daily.find_one(
        {"company_id": CO, "date_key": today_key, "one_truth": {"$exists": True}},
        {"_id": 0})
    if not snap:
        # fallback: pega o último disponível
        snap = await db.president_daily.find_one(
            {"company_id": CO, "one_truth": {"$exists": True}},
            {"_id": 0}, sort=[("date_key", -1)])
    ot = (snap or {}).get("one_truth") or {}
    course = (snap or {}).get("course_correction") or {}
    summary = (snap or {}).get("course_summary") or ""

    # 5. Top decisão recomendada: pior KPI (status critico/piorando).
    top_focus = None
    for kpi, c in course.items():
        st = c.get("status")
        if st in ("critico", "piorando"):
            top_focus = {
                "kpi": kpi, "status": st,
                "projected_90d": c.get("projected_90d"),
                "target": c.get("target"),
            }
            break

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "company_id": CO,
        "snapshot_date": (snap or {}).get("date_key"),
        "counts": {
            "pending_messages": len(pending_messages),
            "cto_replies_unread": len(cto_replies_unread),
            "decisions_awaiting_approval": len(pending_decs),
        },
        "pending_messages": pending_messages,
        "cto_replies_unread": cto_replies_unread,
        "decisions_awaiting_approval": pending_decs,
        "course_summary": summary,
        "kpis": {
            "clientes_ativos": ot.get("clientes_ativos"),
            "mrr_brl": ot.get("mrr"),
            "inadimplencia_brl": ot.get("inadimplencia_brl"),
            "inadimplencia_n_faturas": ot.get("inadimplencia_n_faturas"),
            "tickets_abertos": ot.get("tickets_abertos"),
            "fundadores_aptos": ot.get("fundadores_aptos"),
            "embaixadores": ot.get("embaixadores"),
        },
        "course_status": {k: v.get("status") for k, v in course.items()},
        "top_focus": top_focus,
    }
