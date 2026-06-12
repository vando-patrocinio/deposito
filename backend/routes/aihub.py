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


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import base64
import logging
import re
import uuid
from typing import Any, Dict, List, Literal, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, EMERGENT_LLM_KEY, now_iso, require_role
from database import db
from routes.subscribers import (
    find_subscriber_by_phone, build_subscriber_context,
)

logger = logging.getLogger("ponto.aihub")
router = APIRouter(prefix="/api/aihub", tags=["aihub"])


# ---------------------------------------------------------------------------
# Modelos suportados (via Emergent LLM Key)
# ---------------------------------------------------------------------------
SUPPORTED_MODELS = [
    {"provider": "deepseek", "model": "deepseek-v3.1-terminus", "label": "DeepSeek V3.1 Terminus (recomendado, estável)"},
    {"provider": "deepseek", "model": "deepseek-chat-v3-0324", "label": "DeepSeek Chat V3 (estável, custo baixo)"},
    {"provider": "deepseek", "model": "deepseek-chat-v3.1", "label": "DeepSeek Chat V3.1"},
    {"provider": "deepseek", "model": "deepseek-v3.2-exp", "label": "DeepSeek V3.2 Exp (experimental)"},
    {"provider": "deepseek", "model": "deepseek-v4-flash", "label": "DeepSeek V4 Flash (1M ctx)"},
    {"provider": "deepseek", "model": "deepseek-r1", "label": "DeepSeek R1 (raciocínio profundo)"},
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
    {"id": "schedule_lousa_ticket", "label": "Agendar visita técnica (Lousa)",
     "description": "Cria uma bolha na Lousa de serviços com tipo/endereço/cliente — exatamente como o gestor faria manualmente."},
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
    initial_message: str = Field(default="", max_length=2000)
    system_prompt: str = Field(..., min_length=10, max_length=200000)
    model_provider: Literal["deepseek", "gemini", "anthropic", "openai"] = "deepseek"
    model_name: str = Field(default="deepseek-v3.1-terminus", max_length=80)
    temperature: float = Field(default=0.6, ge=0.0, le=2.0)
    max_tokens: int = Field(default=700, ge=50, le=32000)
    form_fields: List[FormField] = Field(default_factory=list)
    tools_enabled: List[str] = Field(default_factory=list)
    webhook_url: Optional[str] = Field(default=None, max_length=400)
    active: bool = True
    # Personalidade & Expertise (estilo PDF Ligo Fibra)
    company_info: str = Field(default="", max_length=200000)
    pricing_info: str = Field(default="", max_length=200000)
    priority_situations: str = Field(default="", max_length=200000)
    # Roteamento inteligente (multi-agente)
    routing_intent: str = Field(default="", max_length=400)


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=80)
    description: Optional[str] = Field(default=None, max_length=300)
    initial_message: Optional[str] = Field(default=None, max_length=2000)
    system_prompt: Optional[str] = Field(default=None, min_length=10, max_length=200000)
    model_provider: Optional[Literal["deepseek", "gemini", "anthropic", "openai"]] = None
    model_name: Optional[str] = Field(default=None, max_length=80)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=50, le=32000)
    form_fields: Optional[List[FormField]] = None
    tools_enabled: Optional[List[str]] = None
    webhook_url: Optional[str] = Field(default=None, max_length=400)
    active: Optional[bool] = None
    company_info: Optional[str] = Field(default=None, max_length=200000)
    pricing_info: Optional[str] = Field(default=None, max_length=200000)
    priority_situations: Optional[str] = Field(default=None, max_length=200000)
    routing_intent: Optional[str] = Field(default=None, max_length=400)


class PlaygroundIn(BaseModel):
    session_id: Optional[str] = None  # se vazio, gera novo
    message: str = Field(..., min_length=1, max_length=4000)
    subscriber_id: Optional[str] = None  # se preenchido, injeta contexto no prompt


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


def _is_secret_field(name: str) -> bool:
    """True se o nome do campo representa um valor sensível.

    Cobre tanto match exato (`secret`, `password`) quanto sufixos comuns
    (`sip_password`, `api_secret`, `verify_token`).
    """
    n = (name or "").lower()
    if n in SECRET_KEYS:
        return True
    return any(n.endswith("_" + k) or n.endswith(k) for k in SECRET_KEYS)


def _mask_config(config: dict) -> dict:
    """Mascara campos sensíveis para resposta de leitura."""
    out: Dict[str, Any] = {}
    for k, v in (config or {}).items():
        if _is_secret_field(k) and isinstance(v, str):
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

    session_id = payload.session_id or f"playground-{aid}-{uuid.uuid4().hex[:8]}"

    # Persiste mensagem do usuário
    await db.aihub_messages.insert_one({
        "id": f"msg-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "agent_id": aid,
        "session_id": session_id,
        "subscriber_id": payload.subscriber_id,
        "role": "user",
        "content": payload.message,
        "created_at": now_iso(),
    })

    # Constrói prompt com contexto de formulário inteligente, se houver
    sys_prompt = agent["system_prompt"]
    # Personalidade & Expertise — anexa info da empresa, preços e situações prioritárias
    extra_blocks = []
    if agent.get("company_info"):
        extra_blocks.append(f"=== INFORMAÇÕES DA EMPRESA ===\n{agent['company_info']}")
    # PREÇOS — Tabela oficial (pricing_catalog) tem prioridade sobre o
    # campo livre pricing_info legado.
    _pricing_block = ""
    try:
        from routes.pricing_catalog import compose_pricing_block
        _pricing_block = await compose_pricing_block(cid)
    except Exception:
        _pricing_block = ""
    if _pricing_block:
        extra_blocks.append(_pricing_block)
    elif agent.get("pricing_info"):
        extra_blocks.append(f"=== PREÇOS E VALORES ===\n{agent['pricing_info']}")
    if agent.get("priority_situations"):
        extra_blocks.append(f"=== SITUAÇÕES PRIORITÁRIAS ===\n{agent['priority_situations']}")
    if extra_blocks:
        sys_prompt += "\n\n" + "\n\n".join(extra_blocks)
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
    # Injeta contexto do assinante quando vinculado
    if payload.subscriber_id:
        try:
            ctx = await build_subscriber_context(cid, payload.subscriber_id)
            if ctx:
                sys_prompt += "\n\n" + ctx
        except Exception as e:
            logger.warning("[playground] subscriber context falhou: %s", e)

    try:
        from services.motor_ia import chat_completion
    except ImportError as e:
        raise HTTPException(500, f"motor_ia indisponível: {e}")

    # Histórico curto da sessão (últimas 10 mensagens) para manter contexto
    history = await db.aihub_messages.find(
        {"company_id": cid, "agent_id": aid, "session_id": session_id},
        {"_id": 0, "role": 1, "content": 1},
    ).sort("created_at", 1).to_list(20)
    messages = [{"role": "system", "content": sys_prompt}]
    for h in history[-9:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": payload.message})

    try:
        result = await chat_completion(
            cid, messages=messages,
            temperature=agent.get("temperature", 0.6),
            max_tokens=agent.get("max_tokens", 700),
            purpose="atendimento",
            agent="aihub_chat",
        )
        text = (result.get("content") or "").strip()
    except Exception as e:
        logger.warning("[aihub] LLM error session=%s: %s", session_id, e)
        raise HTTPException(502, f"Falha ao chamar LLM: {e}") from e

    # Persiste resposta
    await db.aihub_messages.insert_one({
        "id": f"msg-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "agent_id": aid,
        "session_id": session_id,
        "subscriber_id": payload.subscriber_id,
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
            if _is_secret_field(k) and isinstance(v, str) and "•" in v:
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

    ok, error_msg, sample, endpoint = await _probe_magnusbilling(url, key, secret)

    await db.aihub_integrations.update_one(
        {"company_id": cid, "type": "magnusbilling"},
        {"$set": {
            "status": "online" if ok else "error",
            "last_test_at": now_iso(),
            "last_test_error": error_msg,
        }},
    )
    return {"ok": ok, "endpoint": endpoint, "error": error_msg,
            "sample": sample if ok else None}


async def _probe_magnusbilling(url: str, key: str, secret: str
                                ) -> Tuple[bool, Optional[str], Any, str]:
    """Probe MagnusBilling — usado tanto pelo botão Testar quanto pelo monitor.

    Detecta erros comuns e devolve mensagem amigável em português:
    - "Access denied to All action in All modules" → instrui o usuário a
      adicionar permissões na API key.
    - HTTP 401/403 → credenciais inválidas.
    - HTTPS errors → URL/SSL.
    """
    test_endpoint = f"{url}/index.php/api/getInfo"
    error_msg: Optional[str] = None
    ok = False
    sample: Any = None
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=True) as cli:
            r = await cli.get(test_endpoint, params={"key": key, "secret": secret})
            if r.status_code == 200:
                # MB devolve 200 mesmo quando a Key não tem permissões — vem como JSON
                # com {"raw": "Access denied..."} ou {"error": "..."}.
                try:
                    body = r.json()
                except Exception:
                    body = {"raw": (r.text or "")[:200]}
                raw_text = (body.get("raw") if isinstance(body, dict) else "") or ""
                err_text = (body.get("error") if isinstance(body, dict) else "") or ""
                if "access denied" in str(raw_text).lower() or "access denied" in str(err_text).lower():
                    error_msg = (
                        "Permissões insuficientes na API Key. "
                        "No painel MagnusBilling → Configurações → API → edite a Key → "
                        "marque as Permissões necessárias (mínimo: getInfo, getDid, getCdr, originate)."
                    )
                else:
                    ok = True
                    sample = body
            elif r.status_code in (401, 403):
                error_msg = (
                    f"HTTP {r.status_code} — Key/Secret incorretos. "
                    "Verifique em Configurações → API no MagnusBilling."
                )
            else:
                error_msg = f"HTTP {r.status_code}: {(r.text or '')[:200]}"
    except httpx.HTTPError as e:
        error_msg = f"erro de rede ({type(e).__name__}): {e}"
    except Exception as e:  # pragma: no cover — defensivo
        error_msg = f"erro: {e}"
    return ok, error_msg, sample, test_endpoint


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
    ok, error_msg, sample, endpoint = await _probe_whatsapp_cloud(pnid, token, graph_ver)

    await db.aihub_integrations.update_one(
        {"company_id": cid, "type": "whatsapp_cloud"},
        {"$set": {
            "status": "online" if ok else "error",
            "last_test_at": now_iso(),
            "last_test_error": error_msg,
        }},
    )
    return {"ok": ok, "endpoint": endpoint, "error": error_msg, "sample": sample}


async def _probe_whatsapp_cloud(pnid: str, token: str, graph_ver: str
                                 ) -> Tuple[bool, Optional[str], Any, str]:
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
    return ok, error_msg, sample, endpoint


# ---------------------------------------------------------------------------
# Status summary — usado pelos cards em Configurações com auto-refresh
# ---------------------------------------------------------------------------
@router.get("/integrations/status-summary")
async def integrations_status_summary(user: dict = Depends(require_role("gestor"))):
    """Resumo leve de todas as integrações (MagnusBilling, WhatsApp Cloud).

    Retorna `configured`, `status` (online/error/never_tested), `last_test_at`,
    `last_test_error`, `monitor_enabled`. Não retorna config/secrets — pode
    ser chamado em loop pelo frontend (ex.: a cada 30s).
    """
    cid = _cid(user)
    rows = await db.aihub_integrations.find(
        {"company_id": cid},
        {"_id": 0, "type": 1, "status": 1, "config": 1,
         "last_test_at": 1, "last_test_error": 1, "monitor_enabled": 1},
    ).to_list(20)
    out: Dict[str, Any] = {}
    for r in rows:
        cfg = r.get("config") or {}
        configured = False
        if r.get("type") == "magnusbilling":
            configured = bool(cfg.get("url") and cfg.get("key") and cfg.get("secret"))
        elif r.get("type") == "whatsapp_cloud":
            configured = bool(cfg.get("phone_number_id") and cfg.get("access_token"))
        out[r["type"]] = {
            "configured": configured,
            "status": r.get("status") or ("never_tested" if configured else "not_configured"),
            "last_test_at": r.get("last_test_at"),
            "last_test_error": r.get("last_test_error"),
            "monitor_enabled": r.get("monitor_enabled", True),
        }
    # Garantir chaves presentes mesmo sem config
    for t in ("magnusbilling", "whatsapp_cloud"):
        out.setdefault(t, {
            "configured": False, "status": "not_configured",
            "last_test_at": None, "last_test_error": None,
            "monitor_enabled": False,
        })
    return out


# ---------------------------------------------------------------------------
# Monitor worker — re-testa integrações periodicamente
# ---------------------------------------------------------------------------
_MONITOR_TASK: Optional[asyncio.Task] = None
_MONITOR_RUN = True
_MONITOR_INTERVAL_SEC = 60  # tick a cada 60s


async def _monitor_one(intg: dict) -> None:
    cid = intg.get("company_id") or DEMO_COMPANY_ID
    itype = intg.get("type")
    cfg = intg.get("config") or {}
    if not cfg:
        return
    prev_status = intg.get("status")
    ok = False
    error_msg: Optional[str] = None
    if itype == "magnusbilling":
        url = (cfg.get("url") or "").rstrip("/")
        key = cfg.get("key") or ""
        secret = cfg.get("secret") or ""
        if not (url and key and secret):
            return  # não configurada por completo — não monitora
        ok, error_msg, _, _ = await _probe_magnusbilling(url, key, secret)
    elif itype == "whatsapp_cloud":
        pnid = cfg.get("phone_number_id") or ""
        token = cfg.get("access_token") or ""
        graph_ver = cfg.get("graph_version") or "v23.0"
        if not (pnid and token):
            return
        ok, error_msg, _, _ = await _probe_whatsapp_cloud(pnid, token, graph_ver)
    else:
        return

    new_status = "online" if ok else "error"
    await db.aihub_integrations.update_one(
        {"company_id": cid, "type": itype},
        {"$set": {
            "status": new_status,
            "last_monitor_at": now_iso(),
            "last_test_at": now_iso(),
            "last_test_error": error_msg,
        }},
    )
    # Loga transições de estado (online → error ou vice-versa)
    if prev_status and prev_status != new_status:
        logger.warning(
            "[aihub.monitor] %s/%s: %s → %s (%s)",
            cid, itype, prev_status, new_status, error_msg or "ok",
        )


async def _monitor_loop() -> None:
    """Loop infinito que re-testa cada integração configurada."""
    while _MONITOR_RUN:
        try:
            cursor = db.aihub_integrations.find(
                {"monitor_enabled": {"$ne": False}},
                {"_id": 0},
            )
            intgs = await cursor.to_list(200)
            # Roda em paralelo para reduzir tempo total
            if intgs:
                await asyncio.gather(
                    *[_monitor_one(i) for i in intgs],
                    return_exceptions=True,
                )
        except Exception as e:
            logger.warning("[aihub.monitor] tick falhou: %s", e)
        await asyncio.sleep(_MONITOR_INTERVAL_SEC)


async def start_worker() -> None:
    global _MONITOR_TASK
    if _MONITOR_TASK and not _MONITOR_TASK.done():
        return
    _MONITOR_TASK = asyncio.create_task(_monitor_loop())
    logger.info("[aihub.monitor] worker started (every %ss)", _MONITOR_INTERVAL_SEC)


def stop_worker() -> None:
    global _MONITOR_RUN
    _MONITOR_RUN = False
    if _MONITOR_TASK:
        _MONITOR_TASK.cancel()
    logger.info("[aihub.monitor] worker stopped")


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

    # Auto-link com assinante
    match = await find_subscriber_by_phone(cid, phone)
    subscriber_id = None
    subscriber_name = None
    if match["status"] == "matched":
        subscriber_id = match["subscriber"]["id"]
        subscriber_name = match["subscriber"].get("name")

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
        "contact_name": payload.contact_name or subscriber_name,
        "contact_id": payload.contact_id,
        "subscriber_id": subscriber_id,
        "subscriber_match_status": match["status"],
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
        "subscriber_id": subscriber_id,
        "subscriber_name": subscriber_name,
        "subscriber_match_status": match["status"],
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
        # Auto-link com assinante via caller (se for inbound) ou callee (outbound)
        phone_for_lookup = (payload.get("caller") or payload.get("from")
                            or payload.get("callee") or payload.get("to") or "")
        subscriber_id = None
        match_status = None
        if phone_for_lookup:
            try:
                match = await find_subscriber_by_phone(company_id, phone_for_lookup)
                match_status = match.get("status")
                if match_status == "matched":
                    subscriber_id = match["subscriber"]["id"]
            except Exception as e:
                logger.warning("[webhook] subscriber lookup falhou: %s", e)

        update_set = {
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
        }
        if subscriber_id:
            update_set["subscriber_id"] = subscriber_id
        if match_status:
            update_set["subscriber_match_status"] = match_status
        await db.aihub_calls.update_one(
            {"company_id": company_id, "external_id": str(call_id)},
            {"$set": update_set, "$setOnInsert": {
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


# ---------------------------------------------------------------------------
# Configurar Robô (estilo PDF Ligo Fibra) — helpers de geração com IA
# ---------------------------------------------------------------------------
class TextGenIn(BaseModel):
    field: Literal[
        "company_info", "pricing_info", "system_prompt",
        "priority_situations", "name", "initial_message",
    ]
    mode: Literal["aprimorar", "gerar"]
    current_text: str = Field(default="", max_length=4000)
    context: Optional[str] = Field(default=None, max_length=2000)


_FIELD_GUIDES = {
    "company_info": (
        "Informações da empresa que a IA deve conhecer. Inclua: nome fantasia, "
        "razão social, CNPJ, endereço, número Anatel/Fistel, áreas de cobertura. "
        "Texto direto e objetivo, em até 8 linhas."
    ),
    "pricing_info": (
        "Tabela de preços e planos. Liste cada plano em uma linha com nome, "
        "velocidade, valor mensal e condição (fidelidade/sem fidelidade). "
        "Formato curto, fácil para a IA ler ao telefone."
    ),
    "system_prompt": (
        "Diretriz de comportamento (system prompt) da atendente IA. "
        "Defina persona, escopo (vendas, manutenção, financeiro, desbloqueio), "
        "tom, regras de transferência para humano e nunca inventar dados."
    ),
    "priority_situations": (
        "Cenários de negócio que merecem atenção especial — não emergências, mas "
        "oportunidades de receita/retenção. Ex.: ex-cliente querendo voltar, "
        "cliente querendo aumentar plano, reclamação repetida em <24h."
    ),
    "name": "Nome próprio feminino brasileiro, simpático, de 1 palavra.",
    "initial_message": (
        "Saudação curta (até 2 frases) que a atendente fala ao atender. "
        "Identifica empresa e oferece ajuda."
    ),
}


@router.post("/agents/text-gen")
async def agent_text_gen(payload: TextGenIn,
                          user: dict = Depends(require_role("gestor"))):
    """Gera ou aprimora um campo de configuração da IA usando LLM.

    `mode=gerar`: cria do zero (descarta `current_text`).
    `mode=aprimorar`: melhora o `current_text` existente preservando intenção.
    """
    try:
        from services.motor_ia import chat_completion
    except ImportError as e:
        raise HTTPException(500, f"motor_ia indisponível: {e}") from e

    guide = _FIELD_GUIDES.get(payload.field, "")
    if payload.mode == "aprimorar" and not payload.current_text.strip():
        raise HTTPException(400, "Texto atual vazio — use mode=gerar para criar do zero.")

    system_msg = (
        "Você é um assistente especializado em configurar atendentes virtuais "
        "para ISPs (provedores de internet) brasileiros. Você escreve em "
        "português brasileiro, claro, direto e profissional. Nunca usa "
        "markdown, listas com bullets ou emojis no resultado final — apenas "
        "texto natural pronto para ser lido por uma IA. Não adicione "
        "explicações, comentários ou frases introdutórias na resposta."
    )

    if payload.mode == "gerar":
        user_msg = (
            f"Gere o conteúdo do campo \"{payload.field}\".\n\n"
            f"Diretriz: {guide}\n\n"
        )
        if payload.context:
            user_msg += f"Contexto adicional do negócio: {payload.context}\n\n"
        user_msg += "Devolva apenas o texto final do campo."
    else:  # aprimorar
        user_msg = (
            f"Aprimore o conteúdo abaixo do campo \"{payload.field}\".\n\n"
            f"Diretriz: {guide}\n\n"
            f"Texto atual:\n---\n{payload.current_text}\n---\n\n"
            "Reescreva mantendo a mesma intenção, mas com escrita mais clara, "
            "natural e sem redundâncias. Devolva apenas o texto final."
        )

    try:
        result = await chat_completion(
            _cid(user),
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.5, max_tokens=900,
            agent="aihub_textgen",
        )
        text = (result.get("content") or "").strip().strip('"\'')
    except Exception as e:
        logger.warning("[aihub.textgen] falhou: %s", e)
        raise HTTPException(502, f"LLM falhou: {e}") from e

    return {"text": text, "field": payload.field, "mode": payload.mode}


# ---------------------------------------------------------------------------
# Tool: schedule_lousa_ticket — IA cria bolha na Lousa (substitui Google Calendar)
# ---------------------------------------------------------------------------
class ScheduleLousaIn(BaseModel):
    """Payload que a IA produz para agendar visita técnica na Lousa.

    Espelha exatamente os campos que o gestor preenche manualmente em
    POST /api/lousa/tickets, exceto `assigned_collaborator_id` que é
    decidido pelo backend (próximo técnico disponível por ordem alfabética).
    """
    client_name: str = Field(..., min_length=2, max_length=120)
    address: str = Field(..., min_length=5, max_length=300)
    neighborhood: str = Field(default="", max_length=120)
    phone: str = Field(default="", max_length=20)
    relato: str = Field(..., min_length=5, max_length=2000)
    pppoe_user: str = Field(default="", max_length=120)
    type: Literal["reparo", "instalacao", "retirada", "preventiva", "venda", "prioridade"] = "reparo"
    priority: Literal["normal", "alta", "urgente"] = "normal"
    scheduled_time: Optional[str] = Field(default=None, max_length=40)
    subscriber_id: Optional[str] = None
    session_id: Optional[str] = None  # vincula ao histórico da chamada IA


@router.post("/tools/schedule-lousa-ticket")
async def schedule_lousa_ticket(payload: ScheduleLousaIn,
                                 user: dict = Depends(require_role("gestor"))):
    """Tool que a IA Jerusa chama para criar uma bolha na Lousa.

    Decide automaticamente o colaborador atribuído (próximo da fila por
    nome alfabético) e escreve o `relato` no mesmo formato das bolhas
    criadas pelos gestores. Retorna o ticket criado.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    # Round-robin: técnico com MENOR carga de bolhas pendentes (justiça +
    # distribuição). Em empate, o de nome alfabético menor (determinístico).
    techs = await db.collaborators.find(
        {"company_id": cid, "active": {"$ne": False}},
        projection={"_id": 0, "id": 1, "name": 1},
    ).to_list(500)
    if not techs:
        raise HTTPException(409, "Nenhum colaborador disponível para atribuir a bolha.")
    # Conta tickets pendentes/abertos por colaborador
    pending_by_tech: Dict[str, int] = {}
    for t in techs:
        n = await db.tickets.count_documents({
            "company_id": cid,
            "assigned_collaborator_id": t["id"],
            "status": {"$in": ["pendente", "aberta", "aguardando_atendimento", "em_andamento"]},
        })
        pending_by_tech[t["id"]] = n
    # ordena por (count, name) ascendente
    techs.sort(key=lambda t: (pending_by_tech.get(t["id"], 0), t.get("name") or ""))
    coll = techs[0]

    # Geocode best-effort
    lat, lng = None, None
    try:
        from routes.lousa import geocode_address  # reuse
        geo = await geocode_address(payload.address)
        lat, lng = geo.lat, geo.lng
    except Exception as e:
        logger.warning("[aihub.schedule] geocode falhou: %s", e)

    # Próxima posição
    last = await db.tickets.find(
        {"assigned_collaborator_id": coll["id"],
         "status": {"$in": ["pendente", "aberta", "aguardando_atendimento"]}},
        {"_id": 0, "position": 1},
    ).sort("position", -1).to_list(1)
    next_pos = (last[0]["position"] + 1) if last else 0

    relato_final = payload.relato.strip()
    # Marca origem na própria nota (transparência pro técnico)
    if "[IA]" not in relato_final:
        relato_final = f"[IA] {relato_final}"

    ticket_id = f"tkt-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": ticket_id,
        "client_id": str(uuid.uuid4()),
        "client_snapshot": {
            "name": payload.client_name,
            "address": payload.address,
            "neighborhood": payload.neighborhood,
            "phone": payload.phone,
            "latitude": lat, "longitude": lng,
            "relato": relato_final,
            "pppoe_user": payload.pppoe_user,
            "test_history": [],
        },
        "type": payload.type,
        "priority": payload.priority,
        "scheduled_time": payload.scheduled_time,
        "position": next_pos,
        "status": "pendente",
        "assigned_collaborator_id": coll["id"],
        "company_id": cid,
        "opened_at": None, "closed_at": None, "closed_by": None,
        "close_location": None, "outcome": None,
        "whatsapp_status": "nao_enviado", "whatsapp_last_message": None,
        "completion_data": None, "admin_action": None, "admin_notes": None,
        "created_at": now_iso(),
        # Metadados IA — quem agendou e em qual sessão
        "created_by_source": "aihub",
        "aihub_session_id": payload.session_id,
        "aihub_subscriber_id": payload.subscriber_id,
    }
    await db.tickets.insert_one(doc)

    # Log auditoria (mesmo padrão das bolhas criadas pelo gestor)
    try:
        from routes.lousa import _log_ticket_action
        await _log_ticket_action(
            ticket_id=ticket_id, action="criada",
            actor_id="aihub:agent", actor_name="IA Jerusa",
            actor_role="aihub",
            details=(f"[IA] Atribuída a {coll.get('name', 'colaborador')} · "
                     f"{payload.client_name} · {payload.type}/{payload.priority}"),
            company_id=cid,
        )
    except Exception as e:
        logger.warning("[aihub.schedule] log falhou: %s", e)

    doc.pop("_id", None)
    return {
        "ok": True,
        "ticket_id": ticket_id,
        "assigned_to": coll.get("name"),
        "ticket": doc,
    }
