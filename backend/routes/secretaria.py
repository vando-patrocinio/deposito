"""Rotas da Secretária IA "Ligo".

- POST /api/secretaria/ask          → chat interno (auth)
- GET  /api/secretaria/config       → token webhook (gestor)
- POST /api/secretaria/regenerate-token  → rotaciona token
- POST /api/secretaria/webhook/chatgpt   → para GPT customizado (bearer)
- GET  /api/secretaria/openapi.json      → spec OpenAPI 3.1 para GPT Actions
- GET  /api/secretaria/logs              → histórico de perguntas
"""
from __future__ import annotations

import logging
import os
import secrets as _secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, get_current_user, require_role
from database import db
from services.secretaria_ia import ask as secretaria_ask

logger = logging.getLogger("routes.secretaria")
router = APIRouter(prefix="/api/secretaria", tags=["secretaria"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class AskIn(BaseModel):
    question: str
    channel: Optional[str] = "internal"


class WebhookAskIn(BaseModel):
    question: str
    asker: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _get_or_create_config(company_id: str) -> dict:
    """Lê (ou cria) a config da Secretária. Inclui o webhook_token."""
    doc = await db.secretaria_config.find_one({"company_id": company_id}, {"_id": 0})
    if not doc:
        doc = {
            "company_id": company_id,
            "webhook_token": _secrets.token_urlsafe(32),
            "enabled": True,
        }
        await db.secretaria_config.insert_one(dict(doc))
    return doc


async def _company_by_token(token: str) -> Optional[str]:
    """Resolve company_id a partir do bearer token do webhook."""
    if not token:
        return None
    doc = await db.secretaria_config.find_one(
        {"webhook_token": token}, {"_id": 0, "company_id": 1, "enabled": 1}
    )
    if not doc or not doc.get("enabled"):
        return None
    return doc.get("company_id")


# ---------------------------------------------------------------------------
# Internal (autenticado)
# ---------------------------------------------------------------------------
@router.post("/ask")
async def api_ask(payload: AskIn, user: dict = Depends(get_current_user)):
    """Chat interno — usado pela UI do sistema."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    return await secretaria_ask(cid, payload.question,
                                  channel=payload.channel or "internal",
                                  who=user.get("email") or user.get("name"))


@router.get("/config")
async def get_config(user: dict = Depends(require_role("gestor"))):
    """Devolve a configuração da Secretária (token webhook etc.) — apenas gestor."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_or_create_config(cid)
    backend_url = os.environ.get("PUBLIC_BACKEND_URL") or ""

    # Status do GPT customizado: última chamada via webhook
    from datetime import datetime, timezone, timedelta
    last_call = await db.secretaria_log.find_one(
        {"company_id": cid, "channel": "chatgpt"},
        {"_id": 0, "created_at": 1, "question": 1, "who": 1},
        sort=[("created_at", -1)],
    )
    total_calls_24h = await db.secretaria_log.count_documents({
        "company_id": cid, "channel": "chatgpt",
        "created_at": {"$gte": (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()},
    })
    chatgpt_online = False
    last_seen_iso = None
    last_question = None
    if last_call:
        last_seen_iso = last_call.get("created_at")
        last_question = last_call.get("question")
        try:
            ts = datetime.fromisoformat(str(last_seen_iso).replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            chatgpt_online = age_min <= 30  # online se chamou nos últimos 30 min
        except Exception:
            pass

    return {
        "enabled": bool(cfg.get("enabled", True)),
        "webhook_token": cfg.get("webhook_token"),
        "webhook_url": f"{backend_url}/api/secretaria/webhook/chatgpt" if backend_url else "/api/secretaria/webhook/chatgpt",
        "openapi_url": f"{backend_url}/api/secretaria/openapi.json" if backend_url else "/api/secretaria/openapi.json",
        "chatgpt_status": {
            "online": chatgpt_online,
            "last_seen": last_seen_iso,
            "last_question": (last_question or "")[:120] if last_question else None,
            "calls_24h": total_calls_24h,
        },
    }


@router.post("/regenerate-token")
async def regenerate_token(user: dict = Depends(require_role("gestor"))):
    """Rotaciona o token (invalida o GPT customizado antigo)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    new_token = _secrets.token_urlsafe(32)
    await db.secretaria_config.update_one(
        {"company_id": cid},
        {"$set": {"webhook_token": new_token}},
        upsert=True,
    )
    return {"webhook_token": new_token}


@router.get("/logs")
async def list_logs(user: dict = Depends(require_role("gestor")), limit: int = 50):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cur = db.secretaria_log.find(
        {"company_id": cid},
        {"_id": 0, "id": 1, "channel": 1, "who": 1, "question": 1, "answer": 1,
         "iterations": 1, "elapsed_ms": 1, "created_at": 1},
    ).sort("created_at", -1).limit(min(limit, 200))
    return {"items": await cur.to_list(min(limit, 200))}


# ---------------------------------------------------------------------------
# Webhook público (bearer) — usado pelo GPT customizado do ChatGPT
# ---------------------------------------------------------------------------
@router.post("/webhook/chatgpt")
async def webhook_chatgpt(
    payload: WebhookAskIn,
    authorization: Optional[str] = Header(None),
    key: Optional[str] = Query(None, description="Token alternativo via query string (fallback)"),
):
    """Endpoint chamado pelo "GPT customizado" via Actions.

    Auth aceita duas formas (qualquer uma serve):
      1. Header `Authorization: Bearer <webhook_token>` (recomendado)
      2. Query string `?key=<webhook_token>` (fallback — mais simples no GPT Builder)
    """
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif key:
        token = key.strip()
    if not token:
        raise HTTPException(401, "Missing token (use Bearer header or ?key= query param)")
    cid = await _company_by_token(token)
    if not cid:
        raise HTTPException(403, "Invalid or revoked token")
    return await secretaria_ask(cid, payload.question or "",
                                  channel="chatgpt",
                                  who=payload.asker or "chatgpt")


# ---------------------------------------------------------------------------
# OpenAPI 3.1 spec — usado para criar Actions no GPT Builder
# ---------------------------------------------------------------------------
@router.get("/openapi.json")
async def openapi_for_gpt(request: Request, key: Optional[str] = Query(None)):
    """Devolve uma spec OpenAPI 3.1 mínima para o GPT customizado.

    Se ?key=<webhook_token> for passado, gera uma spec SEM Authentication
    com a query string `?key=` embutida na URL — bypass do Bearer setup.
    """
    base = os.environ.get("PUBLIC_BACKEND_URL") or str(request.base_url).rstrip("/")

    # Versão simplificada — token na query, sem Authentication
    if key:
        return {
            "openapi": "3.1.0",
            "info": {
                "title": "Secretária IA - Ligo",
                "description": "Pergunte à Ligo qualquer coisa sobre clientes, lousa, OLT, técnicos, churn ou agentes IA.",
                "version": "1.0.0",
            },
            "servers": [{"url": base}],
            "paths": {
                "/api/secretaria/webhook/chatgpt": {
                    "post": {
                        "operationId": "askLigo",
                        "summary": "Pergunte à Ligo",
                        "description": "Envia uma pergunta em linguagem natural e recebe a resposta da Ligo (em pt-BR).",
                        "parameters": [
                            {
                                "name": "key",
                                "in": "query",
                                "required": True,
                                "schema": {"type": "string", "default": key},
                                "description": "Token de acesso (já preenchido)",
                            }
                        ],
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "question": {"type": "string"}
                                        },
                                        "required": ["question"],
                                    }
                                }
                            },
                        },
                        "responses": {
                            "200": {
                                "description": "Resposta",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "answer": {"type": "string"}
                                            },
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }

    # Versão original com Bearer (mantida)
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Secretária IA - Ligo",
            "description": "Assistente executiva da operação ISP. Pergunte qualquer coisa sobre clientes, lousa, OLT, técnicos, churn, agentes IA.",
            "version": "1.0.0",
        },
        "servers": [{"url": base}],
        "paths": {
            "/api/secretaria/webhook/chatgpt": {
                "post": {
                    "operationId": "askLigo",
                    "summary": "Pergunte à Secretária IA",
                    "description": "Envia uma pergunta em linguagem natural e recebe a resposta da Ligo (em pt-BR).",
                    "security": [{"bearerAuth": []}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "question": {"type": "string", "description": "Pergunta do gestor."},
                                        "asker": {"type": "string", "description": "Nome de quem está perguntando (opcional)."},
                                    },
                                    "required": ["question"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Resposta da Ligo",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "answer": {"type": "string"},
                                            "iterations": {"type": "integer"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer"}
            }
        },
    }
