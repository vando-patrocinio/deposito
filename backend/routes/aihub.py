"""Atendimento IA Hub — agentes IA conversacionais usando Emergent LLM Key.

Funcionalidades:
- CRUD de agentes (prompt, modelo, temperatura, formulário inteligente, tools)
- Playground multi-turn com memória de sessão
- Integração com MagnusBilling (URL/Key/Secret) — listar DIDs, CDR, originar chamadas
- Integração WhatsApp Cloud API (Meta) — campos prontos para o usuário plugar credenciais
- Histórico de conversas/chamadas

Tudo usa o EMERGENT_LLM_KEY já configurado no app (sem chaves externas).
"""
from __future__ import annotations

import base64
import logging
import re
import uuid
from typing import Any, Dict, List, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, EMERGENT_LLM_KEY, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.aihub")
router = APIRouter(prefix="/api/aihub", tags=["aihub"])


# ---------------------------------------------------------------------------
# Modelos suportados (via Emergent LLM Key)
# ---------------------------------------------------------------------------
SUPPORTED_MODELS = [
    {"provider": "gemini", "model": "gemini-2.5-flash", "label": "Gemini 2.5 Flash (rápido, barato)"},
    {"provider": "gemini", "model": "gemini-2.5-pro", "label": "Gemini 2.5 Pro (raciocínio profundo)"},
    {"provider": "anthropic", "model": "claude-sonnet-4-5-20250929", "label": "Claude Sonnet 4.5 (equilibrado)"},
    {"provider": "anthropic", "model": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5 (ultra rápido)"},
    {"provider": "openai", "model": "gpt-5", "label": "GPT-5 (qualidade máxima)"},
    {"provider": "openai", "model": "gpt-5-mini", "label": "GPT-5 mini (econômico)"},
]

DEFAULT_TOOLS = [
    {"id": "send_whatsapp", "label": "Enviar WhatsApp",
     "description": "Envia mensagem WhatsApp ao cliente durante/após a conversa."},
    {"id": "transfer_to_human", "label": "Transferir para humano",
     "description": "Encerra IA e cria notificação para um gestor assumir."},
    {"id": "create_lead", "label": "Criar lead",
     "description": "Salva contato qualificado no CRM."},
    {"id": "schedule_appointment", "label": "Agendar (Google Calendar)",
     "description": "Cria evento no Google Calendar (placeholder)."},
    {"id": "get_current_date", "label": "Data/hora atual",
     "description": "Retorna a data e hora atual do servidor."},
    {"id": "hangup", "label": "Encerrar chamada",
     "description": "Encerra a chamada ao final do atendimento."},
]


# ---------------------------------------------------------------------------
# Models (pydantic)
# ---------------------------------------------------------------------------
class FormField(BaseModel):
    key: str = Field(..., min_length=1, max_length=40)
    description: str = Field(..., min_length=1, max_length=200)
    question: str = Field(..., min_length=1, max_length=300)
    required: bool = True


class AgentIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    description: Optional[str] = Field(default=None, max_length=300)
    initial_message: str = Field(default="", max_length=500)
    system_prompt: str = Field(..., min_length=10, max_length=8000)
    model_provider: Literal["gemini", "anthropic", "openai"] = "gemini"
    model_name: str = Field(default="gemini-2.5-flash", max_length=80)
    temperature: float = Field(default=0.6, ge=0.0, le=2.0)
    max_tokens: int = Field(default=700, ge=50, le=8000)
    form_fields: List[FormField] = Field(default_factory=list)
    tools_enabled: List[str] = Field(default_factory=list)
    webhook_url: Optional[str] = Field(default=None, max_length=400)
    active: bool = True


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=80)
    description: Optional[str] = Field(default=None, max_length=300)
    initial_message: Optional[str] = Field(default=None, max_length=500)
    system_prompt: Optional[str] = Field(default=None, min_length=10, max_length=8000)
    model_provider: Optional[Literal["gemini", "anthropic", "openai"]] = None
    model_name: Optional[str] = Field(default=None, max_length=80)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=50, le=8000)
    form_fields: Optional[List[FormField]] = None
    tools_enabled: Optional[List[str]] = None
    webhook_url: Optional[str] = Field(default=None, max_length=400)
    active: Optional[bool] = None


class PlaygroundIn(BaseModel):
    session_id: Optional[str] = None  # se vazio, gera novo
    message: str = Field(..., min_length=1, max_length=4000)


class OutboundCallIn(BaseModel):
    """Originar chamada outbound via MagnusBilling, vinculada a um agente IA."""
    agent_id: str = Field(..., min_length=4)
    phone: str = Field(..., min_length=8, max_length=20)
    contact_name: Optional[str] = Field(default=None, max_length=120)
    contact_id: Optional[str] = Field(default=None, max_length=80)
    notes: Optional[str] = Field(default=None, max_length=500)


class IntegrationConfigIn(BaseModel):
    """Config genérica — campos variam por tipo (magnusbilling / whatsapp_cloud)."""
    config: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


def _mask_secret(value: str) -> str:
    """Mascara secret mantendo 4 chars iniciais e finais."""
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}{'•' * (len(value) - 8)}{value[-4:]}"


SECRET_KEYS = {"key", "secret", "access_token", "verify_token", "api_secret",
                "magnus_key", "magnus_secret", "password"}


def _mask_config(config: dict) -> dict:
    """Mascara campos sensíveis para resposta de leitura."""
    out: Dict[str, Any] = {}
    for k, v in (config or {}).items():
        if k.lower() in SECRET_KEYS and isinstance(v, str):
            out[k] = _mask_secret(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Catálogos
# ---------------------------------------------------------------------------
@router.get("/catalog/models")
async def list_models(user: dict = Depends(require_role("gestor"))):
    return {"models": SUPPORTED_MODELS}


@router.get("/catalog/tools")
async def list_tools(user: dict = Depends(require_role("gestor"))):
    return {"tools": DEFAULT_TOOLS}


# ---------------------------------------------------------------------------
# Agents CRUD
# ---------------------------------------------------------------------------
@router.get("/agents")
async def list_agents(user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    rows = await db.aihub_agents.find(
        {"company_id": cid}, {"_id": 0},
    ).sort("created_at", -1).to_list(200)
    return {"items": rows, "count": len(rows)}


@router.post("/agents")
async def create_agent(payload: AgentIn,
                        user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    aid = f"agent-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": aid,
        "company_id": cid,
        **payload.model_dump(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user.get("name") or user.get("email"),
    }
    await db.aihub_agents.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.get("/agents/{aid}")
async def get_agent(aid: str, user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    a = await db.aihub_agents.find_one(
        {"id": aid, "company_id": cid}, {"_id": 0})
    if not a:
        raise HTTPException(404, "Agente não encontrado.")
    return a


@router.patch("/agents/{aid}")
async def update_agent(aid: str, payload: AgentUpdate,
                        user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    update_data = {k: v for k, v in payload.model_dump(exclude_unset=True).items()
                   if v is not None}
    if not update_data:
        raise HTTPException(400, "Nada para atualizar.")
    update_data["updated_at"] = now_iso()
    res = await db.aihub_agents.update_one(
        {"id": aid, "company_id": cid}, {"$set": update_data})
    if res.matched_count == 0:
        raise HTTPException(404, "Agente não encontrado.")
    a = await db.aihub_agents.find_one({"id": aid, "company_id": cid}, {"_id": 0})
    return a


@router.delete("/agents/{aid}")
async def delete_agent(aid: str, user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    res = await db.aihub_agents.delete_one({"id": aid, "company_id": cid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Agente não encontrado.")
    # Limpa conversas órfãs
    await db.aihub_conversations.delete_many({"agent_id": aid, "company_id": cid})
    await db.aihub_messages.delete_many({"agent_id": aid, "company_id": cid})
    return {"ok": True, "deleted_id": aid}


# ---------------------------------------------------------------------------
# Playground (multi-turn)
# ---------------------------------------------------------------------------
@router.post("/agents/{aid}/playground")
async def playground(aid: str, payload: PlaygroundIn,
                      user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    agent = await db.aihub_agents.find_one(
        {"id": aid, "company_id": cid}, {"_id": 0})
    if not agent:
        raise HTTPException(404, "Agente não encontrado.")
    if not EMERGENT_LLM_KEY:
        raise HTTPException(503, "EMERGENT_LLM_KEY não configurada no servidor.")

    session_id = payload.session_id or f"playground-{aid}-{uuid.uuid4().hex[:8]}"

    # Persiste mensagem do usuário
    await db.aihub_messages.insert_one({
        "id": f"msg-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "agent_id": aid,
        "session_id": session_id,
        "role": "user",
        "content": payload.message,
        "created_at": now_iso(),
    })

    # Constrói prompt com contexto de formulário inteligente, se houver
    sys_prompt = agent["system_prompt"]
    if agent.get("form_fields"):
        sys_prompt += "\n\nCampos a CAPTURAR durante a conversa (faça perguntas naturais quando apropriado):\n"
        for f in agent["form_fields"]:
            req = " (obrigatório)" if f.get("required") else ""
            sys_prompt += f"- {f['key']}: {f['description']}{req} — pergunte: \"{f['question']}\"\n"
    if agent.get("tools_enabled"):
        sys_prompt += (
            f"\n\nVocê tem acesso a estas ferramentas: {', '.join(agent['tools_enabled'])}. "
            "Quando precisar usar uma, informe ao usuário em linguagem natural "
            "(ex.: 'vou enviar essa informação por WhatsApp')."
        )

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except ImportError as e:
        raise HTTPException(500, f"emergentintegrations indisponível: {e}")

    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=session_id,
            system_message=sys_prompt,
        ).with_model(agent["model_provider"], agent["model_name"])
        # Aplicar temperatura se SDK suportar (graceful)
        try:
            chat = chat.with_temperature(agent.get("temperature", 0.6))  # type: ignore
        except Exception:
            pass
        try:
            chat = chat.with_max_tokens(agent.get("max_tokens", 700))  # type: ignore
        except Exception:
            pass

        resp = await chat.send_message(UserMessage(text=payload.message))
        text = resp if isinstance(resp, str) else getattr(resp, "text", str(resp))
        text = (text or "").strip()
    except Exception as e:
        logger.warning("[aihub] LLM error session=%s: %s", session_id, e)
        raise HTTPException(502, f"Falha ao chamar LLM: {e}")

    # Persiste resposta
    await db.aihub_messages.insert_one({
        "id": f"msg-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "agent_id": aid,
        "session_id": session_id,
        "role": "assistant",
        "content": text,
        "created_at": now_iso(),
    })

    # Conta turnos
    turn_count = await db.aihub_messages.count_documents({"session_id": session_id})

    return {
        "session_id": session_id,
        "reply": text,
        "agent_name": agent["name"],
        "model": f"{agent['model_provider']}/{agent['model_name']}",
        "turn_count": turn_count,
    }


@router.get("/agents/{aid}/sessions")
async def list_sessions(aid: str, user: dict = Depends(require_role("gestor"))):
    """Lista sessões de teste/conversas de um agente."""
    cid = _cid(user)
    pipeline = [
        {"$match": {"company_id": cid, "agent_id": aid}},
        {"$group": {
            "_id": "$session_id",
            "first_at": {"$min": "$created_at"},
            "last_at": {"$max": "$created_at"},
            "msg_count": {"$sum": 1},
        }},
        {"$sort": {"last_at": -1}},
        {"$limit": 50},
    ]
    rows = await db.aihub_messages.aggregate(pipeline).to_list(50)
    return {"sessions": [
        {"session_id": r["_id"], "first_at": r["first_at"],
         "last_at": r["last_at"], "msg_count": r["msg_count"]}
        for r in rows
    ]}


@router.get("/sessions/{session_id}/messages")
async def session_messages(session_id: str,
                            user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    rows = await db.aihub_messages.find(
        {"company_id": cid, "session_id": session_id}, {"_id": 0},
    ).sort("created_at", 1).to_list(500)
    return {"items": rows}


# ---------------------------------------------------------------------------
# Integrations (MagnusBilling, WhatsApp Cloud)
# ---------------------------------------------------------------------------
@router.get("/integrations")
async def list_integrations(user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    rows = await db.aihub_integrations.find(
        {"company_id": cid}, {"_id": 0},
    ).to_list(20)
    # Mascarar secrets
    return {"items": [
        {**r, "config": _mask_config(r.get("config") or {})}
        for r in rows
    ]}


@router.put("/integrations/{itype}")
async def upsert_integration(itype: str, payload: IntegrationConfigIn,
                              user: dict = Depends(require_role("gestor"))):
    if itype not in {"magnusbilling", "whatsapp_cloud", "whatsapp_web"}:
        raise HTTPException(400, "Tipo de integração inválido.")
    cid = _cid(user)
    # Merge com config atual: se um campo sensível vier mascarado (•••), mantém o atual
    current = await db.aihub_integrations.find_one(
        {"company_id": cid, "type": itype}, {"_id": 0})
    new_config = dict(payload.config or {})
    if current and current.get("config"):
        for k, v in new_config.items():
            if k.lower() in SECRET_KEYS and isinstance(v, str) and "•" in v:
                new_config[k] = current["config"].get(k, v)

    await db.aihub_integrations.update_one(
        {"company_id": cid, "type": itype},
        {"$set": {
            "company_id": cid,
            "type": itype,
            "config": new_config,
            "status": "configured",
            "updated_at": now_iso(),
            "updated_by": user.get("name") or user.get("email"),
        }, "$setOnInsert": {
            "id": f"intg-{uuid.uuid4().hex[:10]}",
            "created_at": now_iso(),
        }},
        upsert=True,
    )
    saved = await db.aihub_integrations.find_one(
        {"company_id": cid, "type": itype}, {"_id": 0})
    if saved:
        saved["config"] = _mask_config(saved.get("config") or {})
    return saved


@router.delete("/integrations/{itype}")
async def delete_integration(itype: str,
                              user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    res = await db.aihub_integrations.delete_one(
        {"company_id": cid, "type": itype})
    return {"ok": True, "deleted": res.deleted_count}


@router.post("/integrations/magnusbilling/test")
async def test_magnusbilling(user: dict = Depends(require_role("gestor"))):
    """Testa conectividade com MagnusBilling REST API.

    Faz um GET autenticado em /index.php/api/getInfo (endpoint padrão MB)
    para validar URL/Key/Secret. Salva resultado em status.
    """
    cid = _cid(user)
    intg = await db.aihub_integrations.find_one(
        {"company_id": cid, "type": "magnusbilling"}, {"_id": 0})
    if not intg or not intg.get("config"):
        raise HTTPException(400, "Configure URL/Key/Secret antes de testar.")

    cfg = intg["config"]
    url = (cfg.get("url") or "").rstrip("/")
    key = cfg.get("key") or ""
    secret = cfg.get("secret") or ""
    if not url or not key or not secret:
        raise HTTPException(400, "URL, Key e Secret são obrigatórios.")

    test_endpoint = f"{url}/index.php/api/getInfo"
    error_msg: Optional[str] = None
    ok = False
    sample: Any = None
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=True) as cli:
            r = await cli.get(test_endpoint, params={"key": key, "secret": secret})
            if r.status_code == 200:
                ok = True
                try:
                    sample = r.json()
                except Exception:
                    sample = (r.text or "")[:200]
            else:
                error_msg = f"HTTP {r.status_code}: {(r.text or '')[:200]}"
    except httpx.HTTPError as e:
        error_msg = f"erro de rede: {e}"
    except Exception as e:
        error_msg = f"erro: {e}"

    await db.aihub_integrations.update_one(
        {"company_id": cid, "type": "magnusbilling"},
        {"$set": {
            "status": "online" if ok else "error",
            "last_test_at": now_iso(),
            "last_test_error": error_msg,
        }},
    )
    return {"ok": ok, "endpoint": test_endpoint, "error": error_msg,
            "sample": sample if ok else None}


@router.post("/integrations/whatsapp_cloud/test")
async def test_whatsapp_cloud(user: dict = Depends(require_role("gestor"))):
    """Testa credenciais do WhatsApp Cloud API.

    Faz GET em /v23.0/{phone_number_id} usando Bearer access_token.
    """
    cid = _cid(user)
    intg = await db.aihub_integrations.find_one(
        {"company_id": cid, "type": "whatsapp_cloud"}, {"_id": 0})
    if not intg or not intg.get("config"):
        raise HTTPException(400, "Configure as credenciais antes de testar.")
    cfg = intg["config"]
    pnid = cfg.get("phone_number_id") or ""
    token = cfg.get("access_token") or ""
    graph_ver = cfg.get("graph_version") or "v23.0"
    if not pnid or not token:
        raise HTTPException(400,
                            "phone_number_id e access_token são obrigatórios.")
    endpoint = f"https://graph.facebook.com/{graph_ver}/{pnid}"
    ok = False
    error_msg: Optional[str] = None
    sample: Any = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.get(endpoint,
                              headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 200:
                ok = True
                sample = r.json()
            else:
                error_msg = f"HTTP {r.status_code}: {(r.text or '')[:200]}"
    except Exception as e:
        error_msg = f"erro: {e}"

    await db.aihub_integrations.update_one(
        {"company_id": cid, "type": "whatsapp_cloud"},
        {"$set": {
            "status": "online" if ok else "error",
            "last_test_at": now_iso(),
            "last_test_error": error_msg,
        }},
    )
    return {"ok": ok, "endpoint": endpoint, "error": error_msg, "sample": sample}


# ---------------------------------------------------------------------------
# MagnusBilling proxy endpoints (DIDs, CDR, originate)
# ---------------------------------------------------------------------------
async def _mb_request(cid: str, path: str, params: Optional[dict] = None,
                       method: str = "GET", body: Optional[dict] = None):
    intg = await db.aihub_integrations.find_one(
        {"company_id": cid, "type": "magnusbilling"}, {"_id": 0})
    if not intg or not intg.get("config"):
        raise HTTPException(400, "MagnusBilling não configurado.")
    cfg = intg["config"]
    url = (cfg.get("url") or "").rstrip("/")
    auth = {"key": cfg.get("key", ""), "secret": cfg.get("secret", "")}
    full_url = f"{url}/index.php/api/{path.lstrip('/')}"
    p = {**auth, **(params or {})}
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            if method == "GET":
                r = await cli.get(full_url, params=p)
            else:
                r = await cli.post(full_url, params=p, json=body or {})
        if r.status_code != 200:
            raise HTTPException(502,
                                f"MagnusBilling HTTP {r.status_code}: {(r.text or '')[:200]}")
        try:
            return r.json()
        except Exception:
            return {"raw": r.text}
    except httpx.HTTPError as e:
        raise HTTPException(502, f"MagnusBilling unreachable: {e}") from e


@router.get("/magnusbilling/dids")
async def mb_list_dids(user: dict = Depends(require_role("gestor"))):
    """Lista DIDs (números) cadastrados no MagnusBilling."""
    cid = _cid(user)
    return await _mb_request(cid, "getDid")


@router.get("/magnusbilling/cdr")
async def mb_list_cdr(limit: int = 100,
                      user: dict = Depends(require_role("gestor"))):
    """Lista chamadas (CDR) recentes."""
    cid = _cid(user)
    data = await _mb_request(cid, "getCallReport",
                             params={"limit": min(max(limit, 1), 1000)})
    return data


@router.post("/calls/outbound")
async def outbound_call(payload: OutboundCallIn,
                         user: dict = Depends(require_role("gestor"))):
    """Origina chamada outbound via MagnusBilling, vinculada a um agente IA.

    O endpoint exato do MagnusBilling pode variar por versão — usa o path
    configurado em `magnusbilling.config.originate_path` (default: `originate`).
    Parâmetros adicionais (trunk_id, caller_id, etc) são lidos da config.

    Salva registro em `aihub_calls` com status="originated" + `agent_id`,
    pra correlacionar quando o webhook de evento da chamada chegar.
    """
    cid = _cid(user)
    agent = await db.aihub_agents.find_one(
        {"id": payload.agent_id, "company_id": cid, "active": True},
        {"_id": 0})
    if not agent:
        raise HTTPException(404, "Agente não encontrado ou inativo.")

    intg = await db.aihub_integrations.find_one(
        {"company_id": cid, "type": "magnusbilling"}, {"_id": 0})
    if not intg or not intg.get("config"):
        raise HTTPException(400, "Configure MagnusBilling antes de originar chamadas.")
    cfg = intg["config"]
    url = (cfg.get("url") or "").rstrip("/")
    key = cfg.get("key") or ""
    secret = cfg.get("secret") or ""
    if not url or not key or not secret:
        raise HTTPException(400, "MagnusBilling: URL/Key/Secret incompletos.")

    # Path do MB pode variar — default é "originate". User pode customizar.
    originate_path = cfg.get("originate_path") or "originate"
    full_url = f"{url}/index.php/api/{originate_path.lstrip('/')}"
    # Sanitizar telefone
    phone = re.sub(r"[^0-9+]", "", payload.phone)
    params: Dict[str, Any] = {
        "key": key,
        "secret": secret,
        "calledid": phone,
        "callerid": cfg.get("caller_id") or "",
        "trunk": cfg.get("trunk_id") or "",
    }
    # Permite extra fixed params via config (ex.: context, exten, etc)
    for k, v in (cfg.get("originate_extra") or {}).items():
        params[k] = v

    call_id = f"call-{uuid.uuid4().hex[:10]}"
    error_msg: Optional[str] = None
    mb_response: Any = None
    ok = False
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(full_url, params=params)
            if r.status_code == 200:
                ok = True
                try:
                    mb_response = r.json()
                except Exception:
                    mb_response = (r.text or "")[:200]
            else:
                error_msg = f"HTTP {r.status_code}: {(r.text or '')[:200]}"
    except httpx.HTTPError as e:
        error_msg = f"erro de rede: {e}"

    # Persiste registro pra correlacionar com webhook futuro
    await db.aihub_calls.insert_one({
        "id": call_id,
        "company_id": cid,
        "agent_id": payload.agent_id,
        "agent_name": agent.get("name"),
        "direction": "outbound",
        "callee": phone,
        "contact_name": payload.contact_name,
        "contact_id": payload.contact_id,
        "status": "originated" if ok else "failed",
        "notes": payload.notes,
        "originated_by": user.get("name") or user.get("email"),
        "started_at": now_iso(),
        "mb_response": mb_response if ok else None,
        "error": error_msg,
    })

    if not ok:
        raise HTTPException(502, f"Falha ao originar via MagnusBilling: {error_msg}")
    return {
        "ok": True,
        "call_id": call_id,
        "phone": phone,
        "agent_name": agent.get("name"),
        "mb_response": mb_response,
    }


# ---------------------------------------------------------------------------
# Webhook receiver — chamadas/eventos de IA externos
# ---------------------------------------------------------------------------
@router.post("/webhooks/call-event")
async def webhook_call_event(payload: Dict[str, Any]):
    """Receptor genérico para eventos de chamada (MagnusBilling/Asterisk/AGI).

    Salva tudo em aihub_webhook_events (auditoria) e cria/atualiza chamada em
    aihub_calls quando há `call_id`. Sem auth — proteja com IP allowlist
    no nginx em produção.
    """
    company_id = payload.get("company_id") or DEMO_COMPANY_ID
    await db.aihub_webhook_events.insert_one({
        "id": f"wh-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "received_at": now_iso(),
        "payload": payload,
    })
    call_id = payload.get("call_id") or payload.get("id")
    if call_id:
        await db.aihub_calls.update_one(
            {"company_id": company_id, "external_id": str(call_id)},
            {"$set": {
                "company_id": company_id,
                "external_id": str(call_id),
                "caller": payload.get("caller") or payload.get("from"),
                "callee": payload.get("callee") or payload.get("to"),
                "did": payload.get("did"),
                "status": payload.get("status") or "unknown",
                "transcript": payload.get("transcript"),
                "summary": payload.get("summary"),
                "duration_sec": payload.get("duration"),
                "raw": payload,
                "updated_at": now_iso(),
            }, "$setOnInsert": {
                "id": f"call-{uuid.uuid4().hex[:10]}",
                "started_at": payload.get("started_at") or now_iso(),
            }},
            upsert=True,
        )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Histórico (calls + sessions + leads)
# ---------------------------------------------------------------------------
@router.get("/history/calls")
async def list_calls(limit: int = 100,
                      user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    rows = await db.aihub_calls.find(
        {"company_id": cid}, {"_id": 0, "raw": 0},
    ).sort("started_at", -1).to_list(min(max(limit, 1), 500))
    return {"items": rows, "count": len(rows)}


@router.get("/dashboard")
async def dashboard(user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    agents_total = await db.aihub_agents.count_documents({"company_id": cid})
    agents_active = await db.aihub_agents.count_documents(
        {"company_id": cid, "active": True})
    calls_total = await db.aihub_calls.count_documents({"company_id": cid})
    sessions_total_pipeline = [
        {"$match": {"company_id": cid}},
        {"$group": {"_id": "$session_id"}},
        {"$count": "n"},
    ]
    s = await db.aihub_messages.aggregate(sessions_total_pipeline).to_list(1)
    sessions_total = s[0]["n"] if s else 0
    intgs = await db.aihub_integrations.find(
        {"company_id": cid}, {"_id": 0, "type": 1, "status": 1}).to_list(20)
    return {
        "agents": {"total": agents_total, "active": agents_active},
        "calls": {"total": calls_total},
        "sessions": {"total": sessions_total},
        "integrations": {i["type"]: i.get("status", "unknown") for i in intgs},
    }
