"""Gestão de prompt da Isabella + módulos categorizados (vendas/promoção/upgrade/novidades).

Endpoints:
  GET    /api/whatsapp-baileys/isabella/prompt
  PUT    /api/whatsapp-baileys/isabella/prompt
  GET    /api/whatsapp-baileys/isabella/fragments
  POST   /api/whatsapp-baileys/isabella/fragments
  PATCH  /api/whatsapp-baileys/isabella/fragments/{fragment_id}
  DELETE /api/whatsapp-baileys/isabella/fragments/{fragment_id}

Fragments são guardados em `isabella_prompt_fragments` e injetados no
fluxo de auto-reply via `compose_active_fragments_block()`.
Cada fragment tem:
  - id (uuid)
  - category: vendas | promocao | upgrade | novidade | custom
  - title: nome legível pro gestor
  - content: o trecho de prompt
  - enabled: bool
  - created_at / updated_at / updated_by
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, require_role
from database import db

logger = logging.getLogger("ponto.isabella_prompt")
router = APIRouter(prefix="/api/whatsapp-baileys", tags=["isabella-prompt"])

VALID_CATEGORIES = {"vendas", "promocao", "upgrade", "novidade", "custom"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


# ---------------------------------------------------------------------------
# PROMPT PRINCIPAL
# ---------------------------------------------------------------------------
class PromptIn(BaseModel):
    system_prompt: str = Field(..., min_length=20)


@router.get("/isabella/prompt")
async def get_isabella_prompt(user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    agent = await db.aihub_agents.find_one(
        {"company_id": cid, "name": "Isabella"},
        {"_id": 0, "system_prompt": 1, "updated_at": 1, "updated_by": 1,
         "model_name": 1, "temperature": 1, "max_tokens": 1},
    )
    if not agent:
        return {"system_prompt": "", "exists": False}
    return {
        "system_prompt": agent.get("system_prompt") or "",
        "updated_at": agent.get("updated_at"),
        "updated_by": agent.get("updated_by"),
        "model_name": agent.get("model_name"),
        "temperature": agent.get("temperature"),
        "max_tokens": agent.get("max_tokens"),
        "exists": True,
        "size": len(agent.get("system_prompt") or ""),
    }


@router.put("/isabella/prompt")
async def update_isabella_prompt(payload: PromptIn,
                                    user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    new_prompt = payload.system_prompt.strip()
    r = await db.aihub_agents.update_one(
        {"company_id": cid, "name": "Isabella"},
        {"$set": {
            "system_prompt": new_prompt,
            "updated_at": _now(),
            "updated_by": user.get("email") or user.get("id") or "gestor",
        }},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Agente Isabella não cadastrado nesta empresa.")
    return {"ok": True, "size": len(new_prompt)}


# ---------------------------------------------------------------------------
# FRAGMENTS (módulos)
# ---------------------------------------------------------------------------
class FragmentIn(BaseModel):
    category: str = Field(..., min_length=3, max_length=30)
    title: str = Field(..., min_length=2, max_length=120)
    content: str = Field(..., min_length=4, max_length=4000)
    enabled: bool = True


class FragmentPatch(BaseModel):
    category: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    enabled: Optional[bool] = None


def _serialize_fragment(doc: dict) -> dict:
    return {
        "id": doc.get("id"),
        "category": doc.get("category"),
        "title": doc.get("title"),
        "content": doc.get("content"),
        "enabled": bool(doc.get("enabled", True)),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "updated_by": doc.get("updated_by"),
    }


@router.get("/isabella/fragments")
async def list_fragments(user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    items = await db.isabella_prompt_fragments.find(
        {"company_id": cid}, {"_id": 0},
    ).sort([("category", 1), ("title", 1)]).to_list(200)
    if not items:
        await _seed_default_fragments(cid, user.get("email") or "system")
        items = await db.isabella_prompt_fragments.find(
            {"company_id": cid}, {"_id": 0},
        ).sort([("category", 1), ("title", 1)]).to_list(200)
    return {"items": [_serialize_fragment(x) for x in items]}


@router.post("/isabella/fragments")
async def create_fragment(payload: FragmentIn,
                            user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    cat = payload.category.strip().lower()
    if cat not in VALID_CATEGORIES:
        raise HTTPException(400,
            f"category inválida. Use: {', '.join(sorted(VALID_CATEGORIES))}")
    fid = f"frg-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": fid,
        "company_id": cid,
        "category": cat,
        "title": payload.title.strip(),
        "content": payload.content.strip(),
        "enabled": payload.enabled,
        "created_at": _now(),
        "updated_at": _now(),
        "updated_by": user.get("email") or user.get("id") or "gestor",
    }
    await db.isabella_prompt_fragments.insert_one(dict(doc))
    return _serialize_fragment(doc)


@router.patch("/isabella/fragments/{fragment_id}")
async def patch_fragment(fragment_id: str, payload: FragmentPatch,
                           user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    upd: dict = {"updated_at": _now(),
                 "updated_by": user.get("email") or "gestor"}
    if payload.category is not None:
        cat = payload.category.strip().lower()
        if cat not in VALID_CATEGORIES:
            raise HTTPException(400, "category inválida")
        upd["category"] = cat
    if payload.title is not None:
        upd["title"] = payload.title.strip()
    if payload.content is not None:
        upd["content"] = payload.content.strip()
    if payload.enabled is not None:
        upd["enabled"] = bool(payload.enabled)
    r = await db.isabella_prompt_fragments.update_one(
        {"company_id": cid, "id": fragment_id},
        {"$set": upd},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Fragment não encontrado")
    doc = await db.isabella_prompt_fragments.find_one(
        {"company_id": cid, "id": fragment_id}, {"_id": 0},
    )
    return _serialize_fragment(doc)


@router.delete("/isabella/fragments/{fragment_id}")
async def delete_fragment(fragment_id: str,
                            user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    r = await db.isabella_prompt_fragments.delete_one(
        {"company_id": cid, "id": fragment_id}
    )
    if r.deleted_count == 0:
        raise HTTPException(404, "Fragment não encontrado")
    return {"ok": True}


# ---------------------------------------------------------------------------
# TESTE DE RESPOSTA — usado pelo botão "Testar resposta" da sub-aba Gestão
# ---------------------------------------------------------------------------
class IsabellaTestIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@router.post("/isabella/test")
async def isabella_test(payload: IsabellaTestIn,
                          user: dict = Depends(require_role("gestor"))):
    """Simula a resposta da Isabella SEM persistir nem enviar.

    Monta o mesmo system_prompt usado pelo `_maybe_auto_reply` (prompt
    principal + fragments ativos + lousa availability se intenção de
    agendamento) e chama o LLM via motor_ia (mesma rota do fluxo real,
    DeepSeek via OpenRouter). Retorna:
      - bubbles: lista de bolhas (após _split_ai_reply)
      - raw: resposta crua do LLM
      - prompt_size: tamanho do prompt final injetado
      - elapsed_ms: tempo total
    """
    import time
    cid = _cid(user)
    user_text = payload.text.strip()
    if not user_text:
        raise HTTPException(400, "Texto vazio.")

    # 1. Busca o agente Isabella e seus parâmetros
    agent = await db.aihub_agents.find_one(
        {"company_id": cid, "name": "Isabella"}, {"_id": 0}
    )
    if not agent:
        raise HTTPException(404, "Agente Isabella não cadastrado.")
    sys_prompt = agent.get("system_prompt") or ""
    model_name = agent.get("model_name") or "deepseek-chat"

    # 2. Monta os blocos extras (mesma ordem do fluxo real)
    extras: list = []
    try:
        from services.lousa_availability import (
            detects_scheduling_intent, get_availability_for_prompt,
        )
        if detects_scheduling_intent(user_text):
            blk = await get_availability_for_prompt(cid, days=7)
            if blk:
                extras.append(blk)
    except Exception as e:
        logger.info("[isabella-test] lousa skip: %s", e)
    try:
        frag_block = await compose_active_fragments_block(cid)
        if frag_block:
            extras.append(frag_block)
    except Exception as e:
        logger.info("[isabella-test] fragments skip: %s", e)

    full_prompt = sys_prompt + ("\n\n" + "\n\n".join(extras) if extras else "")
    # Sufixo de teste pra Isabella saber que é simulação (não conta histórico)
    full_prompt += (
        "\n\n# ⚙️ MODO TESTE\n"
        "Esta é uma simulação solicitada pelo gestor. Não há histórico de "
        "conversa anterior, não há cadastro de cliente. Responda como se "
        "fosse a primeira mensagem do cliente, seguindo todas as regras do "
        "prompt e dos módulos ativos."
    )

    # 3. Chama o LLM via motor_ia.chat_completion (mesma rota do fluxo real)
    started = time.monotonic()
    try:
        from services.motor_ia import chat_completion
        result = await chat_completion(
            company_id=cid,
            messages=[
                {"role": "system", "content": full_prompt},
                {"role": "user", "content": user_text},
            ],
            temperature=agent.get("temperature") or 0.4,
            max_tokens=min(agent.get("max_tokens") or 1500, 1500),
            purpose="atendimento",
            agent="isabella_whatsapp",
        )
        raw = (result.get("content") or "").strip()
        used_model = result.get("model") or model_name
    except Exception as e:
        logger.warning("[isabella-test] LLM falhou: %s", e)
        raise HTTPException(502, f"Falha ao chamar IA: {e}")
    elapsed_ms = int((time.monotonic() - started) * 1000)

    # 4. Aplica _split_ai_reply
    try:
        from routes.whatsapp_baileys import _split_ai_reply
        bubbles = _split_ai_reply(raw, max_chunks=10)
    except Exception:
        bubbles = [raw]

    # 5. Stats de injeção (pra debug)
    return {
        "ok": True,
        "user_text": user_text,
        "bubbles": bubbles,
        "raw": raw,
        "elapsed_ms": elapsed_ms,
        "prompt_size": len(full_prompt),
        "model": used_model,
        "fragments_injected": len(extras),
    }


# ---------------------------------------------------------------------------
# Helper usado pelo _maybe_auto_reply
# ---------------------------------------------------------------------------
CATEGORY_HEADERS = {
    "vendas": "🛒 INTENÇÃO DE VENDA — Detecção & Abordagem",
    "promocao": "🎯 INTENÇÃO DE PROMOÇÃO — Quando Oferecer",
    "upgrade": "📈 INTENÇÃO DE UPGRADE — Quando Sugerir",
    "novidade": "✨ INTENÇÃO DE NOVIDADE — Quando Apresentar",
    "custom": "🔧 MÓDULO CUSTOMIZADO",
}


async def compose_active_fragments_block(company_id: str) -> str:
    """Retorna o bloco com TODOS os fragments ativos.

    Usado no fluxo _maybe_auto_reply pra injetar no system prompt da Isabella
    apenas os módulos que o gestor deixou ligados.
    """
    items = await db.isabella_prompt_fragments.find(
        {"company_id": company_id, "enabled": True}, {"_id": 0},
    ).sort([("category", 1), ("title", 1)]).to_list(200)
    if not items:
        return ""
    # Agrupa por categoria
    by_cat: dict = {}
    for it in items:
        by_cat.setdefault(it.get("category", "custom"), []).append(it)

    parts: List[str] = [
        "=== MÓDULOS ATIVOS DE INTENÇÃO (gerenciados pelo gestor) ===",
        "Os blocos abaixo são GATILHOS de intenção. Quando o cliente "
        "demonstrar uma das intenções, siga o módulo correspondente "
        "ANTES de qualquer outra ação.",
        "",
    ]
    for cat, frags in by_cat.items():
        parts.append(f"## {CATEGORY_HEADERS.get(cat, cat.upper())}")
        for f in frags:
            parts.append(f"### {f.get('title')}")
            parts.append(f.get("content", "").strip())
            parts.append("")
    return "\n".join(parts).rstrip()


# ---------------------------------------------------------------------------
# Seed padrão — vendas, promoção, upgrade, novidade
# ---------------------------------------------------------------------------
DEFAULT_FRAGMENTS = [
    {
        "category": "vendas",
        "title": "Detecção de intenção de venda",
        "content": (
            "Sinais de cliente NOVO querendo contratar:\n"
            "- Pergunta valor/plano/promoção, fala de bairro/endereço novo\n"
            "- 'quanto custa', 'tem internet aqui', 'quero contratar'\n"
            "- Mencionou marca concorrente ('saí da Vivo', 'cancelei a Claro')\n\n"
            "AÇÃO:\n"
            "1. Confirme bairro/cidade ANTES de oferecer plano.\n"
            "2. Pergunte quantas pessoas usam a internet.\n"
            "3. Use a tabela 1-2 / 3-4 / 5+ pessoas pra calcular plano.\n"
            "4. Ofereça SEMPRE 1 plano com fidelidade (recomendado) + 1 sem.\n"
            "5. Mencione isenção de taxa de instalação se fechar HOJE."
        ),
        "enabled": True,
    },
    {
        "category": "promocao",
        "title": "Quando oferecer promoção da semana",
        "content": (
            "Quando ativar promoção:\n"
            "- Cliente em retenção (ameaça cancelar) → desconto 20% por 6 meses\n"
            "- Cliente prospect que veio por indicação → isenção total da taxa\n"
            "- Cliente perguntou se 'tem promoção' → use o catálogo ativo\n\n"
            "Regras CRÍTICAS:\n"
            "- NUNCA invente promoção fora do catálogo.\n"
            "- NUNCA prometa 'pode ficar a metade' se não estiver autorizado.\n"
            "- Se cliente pedir promoção e não houver autorizada → diga\n"
            "  'No momento estamos sem promoção ativa, mas posso te enviar\n"
            "  os planos com nosso melhor valor fixo.'"
        ),
        "enabled": True,
    },
    {
        "category": "upgrade",
        "title": "Quando sugerir upgrade de plano",
        "content": (
            "Gatilhos de oferta de upgrade:\n"
            "- Cliente reclama 'internet lenta' MAS o sinal está OK no SmartOLT\n"
            "  → provavelmente plano insuficiente pra qtd de pessoas/dispositivos\n"
            "- Cliente menciona ter MAIS de 5 dispositivos / Smart TVs / jogos\n"
            "- Cliente está no plano de 200 ou 300 Mega há > 12 meses\n"
            "- Cliente reclama de 4K travando\n\n"
            "Frases-modelo (≤180c, separar em bolha própria com \"\"):\n"
            "\"Pelo seu uso, parece que o plano atual está apertado.\"\n"
            "\"Posso te liberar um upgrade pro 500 Mega por R\\$ 109? 🚀\"\n"
            "\"Posso ativar agora ou prefere conhecer outros planos?\""
        ),
        "enabled": True,
    },
    {
        "category": "novidade",
        "title": "Quando apresentar novidades (Wi-Fi 6, IP fixo, IPTV)",
        "content": (
            "Apresente NOVIDADES quando:\n"
            "- Cliente perguntar sobre 'roteador novo', 'Wi-Fi melhor'\n"
            "- Cliente comprou Smart TV / câmera / NAS\n"
            "- Cliente trabalha em home-office, VPN, jogos online\n"
            "- Cliente reclama de Wi-Fi fraco em vários cômodos\n\n"
            "Catálogo de novidades pra ofertar:\n"
            "- Wi-Fi 6 (1 ponto adicional R\\$ 29,90/mês)\n"
            "- IP Público Fixo (R\\$ 9,90/mês) — para câmeras, VPN, jogos\n"
            "- Ponto Wi-Fi Plus (R\\$ 19,90/mês) — mais alcance\n\n"
            "Regra: apresente 1 novidade por conversa, na bolha mais natural."
        ),
        "enabled": True,
    },
]


async def _seed_default_fragments(company_id: str, by: str) -> None:
    """Seed inicial — só roda se a coleção da empresa estiver vazia."""
    n = await db.isabella_prompt_fragments.count_documents(
        {"company_id": company_id}
    )
    if n > 0:
        return
    now = _now()
    docs = []
    for f in DEFAULT_FRAGMENTS:
        docs.append({
            "id": f"frg-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "category": f["category"],
            "title": f["title"],
            "content": f["content"],
            "enabled": f["enabled"],
            "created_at": now,
            "updated_at": now,
            "updated_by": f"seed:{by}",
        })
    if docs:
        await db.isabella_prompt_fragments.insert_many(docs)
        logger.info("[isabella-prompt] seed %d fragments para %s",
                    len(docs), company_id)
