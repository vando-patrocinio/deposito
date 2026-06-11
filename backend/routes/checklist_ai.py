"""IA · Análises inteligentes para Checklist Veicular.

4 endpoints (todos gestor+):
- POST  /api/vehicle-checklist/{chk_id}/ai/analyze-damage  → analisa fotos de avaria
- GET   /api/vehicle-checklist/ai/recurrent-insights       → narrativa IA sobre defeitos recorrentes
- POST  /api/vehicle-checklist/ai/ocr-paper                → OCR de checklist em papel (1 foto)
- GET   /api/vehicle-checklist/ai/collaborator-health/{cid} → card de saúde por colaborador

Todos usam EMERGENT_LLM_KEY + emergentintegrations.LlmChat (gpt-4o vision).
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

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from dotenv import load_dotenv
from emergentintegrations.llm.chat import ImageContent, LlmChat, UserMessage
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, require_role
from database import db

load_dotenv()

logger = logging.getLogger("ponto.checklist_ai")
router = APIRouter(prefix="/api/vehicle-checklist/ai", tags=["vehicle_checklist_ai"])

# Modelo padrão vision (sobrescreve com env var se quiser)
VISION_MODEL = os.environ.get("CHECKLIST_AI_MODEL", "gpt-4o")
VISION_PROVIDER = os.environ.get("CHECKLIST_AI_PROVIDER", "openai")


def _llm_key() -> str:
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        raise HTTPException(503, "EMERGENT_LLM_KEY não configurada — IA indisponível.")
    return key


def _new_chat(system: str) -> LlmChat:
    return LlmChat(
        api_key=_llm_key(),
        session_id=f"vchk-ai-{uuid.uuid4().hex[:10]}",
        system_message=system,
    ).with_model(VISION_PROVIDER, VISION_MODEL)


def _parse_json(raw: str) -> dict:
    """Extrai o primeiro objeto JSON da resposta do LLM (tolerante a markdown fences)."""
    raw = (raw or "").strip()
    # Remove fences ```json … ``` se presentes
    raw = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", raw, flags=re.M)
    m = re.search(r"\{.*\}", raw, flags=re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def _data_url_to_image(data_url: str) -> Optional[ImageContent]:
    """Aceita 'data:image/jpeg;base64,...' ou base64 puro. Filtra mime inválido."""
    if not data_url:
        return None
    try:
        if data_url.startswith("data:"):
            head, _, b64 = data_url.partition(",")
            mime = head.split(":", 1)[1].split(";", 1)[0].lower()
            if mime not in ("image/jpeg", "image/png", "image/webp"):
                return None
            return ImageContent(image_base64=b64)
        # base64 puro
        return ImageContent(image_base64=data_url)
    except Exception:
        return None


def _company_for(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


# ---------------------------------------------------------------------------
# 1) Analisar fotos de avaria
# ---------------------------------------------------------------------------
class AnalyzeDamageIn(BaseModel):
    attachment_indices: Optional[List[int]] = None  # None = todas
    extra_context: Optional[str] = None


SYS_DAMAGE = (
    "Você é um perito automotivo brasileiro especializado em avaliação de avarias em veículos "
    "de frota corporativa. Receberá 1 ou mais fotos. Para cada foto, avalie objetivamente a "
    "avaria visível: descrição curta, gravidade (leve|moderada|grave) e ação recomendada "
    "(registrar|monitorar|reparar|trocar|encaminhar à oficina).\n\n"
    "Responda EXCLUSIVAMENTE em JSON válido no formato:\n"
    "{\"items\":[{\"index\":N,\"description\":\"...\",\"severity\":\"leve|moderada|grave\","
    "\"suggested_action\":\"...\",\"location\":\"...\"}],\"overall\":\"resumo em 1 linha\","
    "\"max_severity\":\"leve|moderada|grave\"}\n"
    "Use português do Brasil. Se a foto não mostrar avaria veicular, descreva como 'sem avaria detectada' com severity 'leve'."
)


@router.post("/{chk_id}/analyze-damage")
async def analyze_damage(chk_id: str, payload: AnalyzeDamageIn,
                         user: dict = Depends(require_role("gestor"))):
    cid = _company_for(user)
    doc = await db.vehicle_checklists.find_one({"id": chk_id, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Checklist não encontrado.")
    atts = doc.get("attachments") or []
    # Seleciona índices (default: todas as photos)
    indices = payload.attachment_indices
    if indices is None:
        indices = [i for i, a in enumerate(atts) if a.get("kind") == "photo"]
    if not indices:
        raise HTTPException(400, "Nenhuma foto disponível para análise.")
    images: list[ImageContent] = []
    selected_meta = []
    for i in indices:
        if i < 0 or i >= len(atts):
            continue
        img = _data_url_to_image(atts[i].get("data_url"))
        if img is not None:
            images.append(img)
            selected_meta.append({"index": i, "label": atts[i].get("label")})
    if not images:
        raise HTTPException(400, "Nenhuma foto válida (JPEG/PNG/WEBP) encontrada.")

    prompt = (
        f"Veículo: {doc.get('plate','?')} · "
        f"{doc.get('vehicle_brand') or ''} {doc.get('vehicle_model') or ''}.\n"
        f"Foram enviadas {len(images)} foto(s) em ordem.\n"
    )
    if payload.extra_context:
        prompt += f"\nContexto adicional: {payload.extra_context}\n"
    prompt += "\nAnalise cada foto e retorne o JSON solicitado."

    chat = _new_chat(SYS_DAMAGE)
    try:
        raw = await chat.send_message(UserMessage(text=prompt, file_contents=images))
    except Exception as e:
        logger.warning("analyze_damage llm failed: %s", e)
        raise HTTPException(502, f"IA indisponível no momento ({type(e).__name__}). Tente novamente em instantes.")
    data = _parse_json(raw)
    if not data.get("items"):
        raise HTTPException(502, "IA respondeu em formato inesperado. Tente novamente.")
    # Anexa metadados (label do anexo)
    for item, meta in zip(data["items"], selected_meta):
        item.setdefault("attachment_label", meta.get("label"))

    # Persiste a análise dentro do doc para audit
    analysis_doc = {
        "id": f"ai-{uuid.uuid4().hex[:10]}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "by_user_id": user.get("id"),
        "by_user_email": user.get("email"),
        "model": f"{VISION_PROVIDER}/{VISION_MODEL}",
        "indices": indices,
        "result": data,
    }
    await db.vehicle_checklists.update_one(
        {"id": chk_id},
        {"$push": {"ai_analyses": analysis_doc}},
    )
    return {"analysis": analysis_doc}


# ---------------------------------------------------------------------------
# 2) Insights narrativos sobre defeitos recorrentes
# ---------------------------------------------------------------------------
SYS_INSIGHTS = (
    "Você é um analista de manutenção de frota corporativa brasileira. Receberá uma lista "
    "JSON de defeitos recorrentes (placa, item, contagem, último registro, notas). Produza "
    "uma narrativa concisa em português do Brasil (no máximo 6 bullets) que: "
    "(1) destaca os 3-5 alertas mais críticos por placa, (2) sugere a prioridade de manutenção, "
    "(3) recomenda 1-2 ações imediatas. Use linguagem direta de gestor, sem floreios. "
    "Responda EXCLUSIVAMENTE em JSON: {\"summary\":\"1 linha\",\"bullets\":[\"...\"],"
    "\"top_priority\":{\"plate\":\"...\",\"reason\":\"...\"}}"
)


@router.get("/recurrent-insights")
async def recurrent_insights(days: int = 30, min_count: int = 3,
                             user: dict = Depends(require_role("gestor"))):
    """Pega dados de defeitos recorrentes e passa para a IA gerar narrativa."""
    # Reutiliza a mesma agregação do endpoint existente (sem chamar via HTTP).
    cid = _company_for(user)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cur = db.vehicle_checklists.find(
        {"company_id": cid, "created_at": {"$gte": cutoff}},
        {"_id": 0, "plate": 1, "items": 1, "created_at": 1, "vehicle_brand": 1,
         "vehicle_model": 1, "collaborator_name_snapshot": 1, "id": 1})
    grouped: dict = {}
    async for d in cur:
        plate = d.get("plate") or "?"
        for it in d.get("items") or []:
            if it.get("status") != "defeito":
                continue
            key = (plate, it.get("name") or "—")
            entry = grouped.setdefault(key, {
                "plate": plate, "item": it.get("name") or "—",
                "category": it.get("cat"), "count": 0,
                "last_at": d.get("created_at"), "notes": [],
                "last_driver": d.get("collaborator_name_snapshot"),
            })
            entry["count"] += 1
            if d.get("created_at") and (entry["last_at"] is None or d["created_at"] > entry["last_at"]):
                entry["last_at"] = d["created_at"]
            if it.get("notes"):
                entry["notes"].append(it["notes"])
    alerts = [e for e in grouped.values() if e["count"] >= min_count]
    alerts.sort(key=lambda x: (-x["count"], x["plate"]))
    if not alerts:
        return {"period_days": days, "min_count": min_count, "alerts": [],
                "ai": {"summary": "Nenhum defeito recorrente no período. Frota em ordem.",
                       "bullets": [], "top_priority": None}}

    prompt = (
        f"Período: últimos {days} dias · mínimo {min_count} ocorrências/veículo+item.\n"
        f"Defeitos recorrentes:\n{json.dumps(alerts[:30], ensure_ascii=False)}\n\n"
        "Gere o JSON conforme instruído."
    )
    chat = _new_chat(SYS_INSIGHTS)
    try:
        # Timeout duro de 25s — se LLM travar, devolve sem IA em vez de
        # deixar a UI esperando o gateway derrubar.
        raw = await asyncio.wait_for(
            chat.send_message(UserMessage(text=prompt)), timeout=25.0)
    except asyncio.TimeoutError:
        logger.warning("recurrent_insights llm timeout 25s")
        return {"period_days": days, "min_count": min_count, "alerts": alerts,
                "ai": {"summary": "IA demorou demais para responder (>25s). Listando defeitos crus.",
                       "bullets": [], "top_priority": None, "error": "llm_timeout"}}
    except Exception as e:
        logger.warning("recurrent_insights llm failed: %s", e)
        # Fallback gracioso: devolve sem IA
        return {"period_days": days, "min_count": min_count, "alerts": alerts,
                "ai": {"summary": f"IA indisponível ({type(e).__name__}). Listando defeitos crus.",
                       "bullets": [], "top_priority": None, "error": str(e)[:200]}}
    data = _parse_json(raw)
    return {"period_days": days, "min_count": min_count, "alerts": alerts,
            "ai": data or {"summary": "IA respondeu em formato inesperado.",
                           "bullets": [], "top_priority": None}}


# ---------------------------------------------------------------------------
# 3) OCR de checklist em papel
# ---------------------------------------------------------------------------
class OcrPaperIn(BaseModel):
    image_data_url: str = Field(..., min_length=20)
    template_items: Optional[List[str]] = None  # nomes esperados (do DEFAULT_TEMPLATE)


SYS_OCR = (
    "Você é um sistema OCR especializado em checklists de inspeção veicular brasileiros "
    "preenchidos à mão. Receberá UMA foto de um checklist em papel. Extraia objetivamente: "
    "placa, KM inicial, KM final, data, motorista (se visível), itens marcados como OK / "
    "DEFEITO / NA, e observações gerais. Use a lista de itens esperados (se fornecida) para "
    "mapear nomes aproximados.\n\n"
    "Responda EXCLUSIVAMENTE em JSON válido:\n"
    "{\"plate\":\"...\",\"km_initial\":NUMBER|null,\"km_final\":NUMBER|null,"
    "\"date\":\"YYYY-MM-DD\"|null,\"driver_name\":\"...\"|null,"
    "\"items\":[{\"name\":\"...\",\"status\":\"ok|defeito|na\",\"notes\":\"...\"|null}],"
    "\"general_notes\":\"...\"|null,\"confidence\":0..1}\n"
    "Use português do Brasil. Se não tiver certeza, status=\"na\" e confidence baixa."
)


@router.post("/ocr-paper")
async def ocr_paper(payload: OcrPaperIn,
                    user: dict = Depends(require_role("gestor"))):
    img = _data_url_to_image(payload.image_data_url)
    if img is None:
        raise HTTPException(400, "Foto inválida — envie JPEG, PNG ou WEBP em base64.")

    prompt = "Extraia os dados do checklist em papel da foto."
    if payload.template_items:
        prompt += (
            f"\n\nItens esperados (mapeie nomes próximos):\n"
            + "\n".join(f"- {n}" for n in payload.template_items[:60])
        )
    chat = _new_chat(SYS_OCR)
    try:
        raw = await chat.send_message(UserMessage(text=prompt, file_contents=[img]))
    except Exception as e:
        logger.warning("ocr_paper llm failed: %s", e)
        raise HTTPException(502, f"IA indisponível ({type(e).__name__}). Tente novamente.")
    data = _parse_json(raw)
    if not data:
        raise HTTPException(502, "IA respondeu em formato inesperado.")
    return {"ocr": data, "model": f"{VISION_PROVIDER}/{VISION_MODEL}"}


# ---------------------------------------------------------------------------
# 4) Health card por colaborador
# ---------------------------------------------------------------------------
SYS_HEALTH = (
    "Você é um analista de frota brasileiro. Receberá o histórico (JSON) de checklists "
    "veiculares de UM colaborador. Produza um 'cartão de saúde dos equipamentos' conciso "
    "em português do Brasil, focado em: (1) estado geral, (2) defeitos abertos críticos, "
    "(3) tendência (melhorando/estável/piorando), (4) próxima ação recomendada com prazo "
    "estimado. Use linguagem direta de gestor, sem floreios.\n\n"
    "Responda EXCLUSIVAMENTE em JSON:\n"
    "{\"score\":0..100,\"status\":\"bom|atenção|crítico\","
    "\"summary\":\"frase única de visão geral\","
    "\"trend\":\"melhorando|estável|piorando\","
    "\"open_critical\":[\"...\"],\"next_action\":{\"what\":\"...\",\"when\":\"...\"}}"
)


@router.get("/collaborator-health/{cid}")
async def collaborator_health(cid: str, days: int = 60,
                              user: dict = Depends(require_role("gestor"))):
    company_id = _company_for(user)
    coll = await db.collaborators.find_one(
        {"id": cid, "company_id": company_id}, {"_id": 0, "name": 1, "role": 1})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado.")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = await db.vehicle_checklists.find(
        {"company_id": company_id, "collaborator_id": cid, "created_at": {"$gte": cutoff}},
        {"_id": 0, "plate": 1, "items": 1, "conformity": 1, "created_at": 1,
         "general_notes": 1, "km_initial": 1, "km_final": 1, "damage_marks": 1},
    ).sort("created_at", -1).to_list(100)
    if not rows:
        return {"collaborator": coll, "period_days": days, "history_count": 0,
                "ai": {"score": 100, "status": "bom", "summary": "Sem checklists no período.",
                       "trend": "estável", "open_critical": [],
                       "next_action": {"what": "Nenhuma ação imediata", "when": "—"}}}

    # Resume os dados pra IA (não envia atachments base64)
    summary = []
    for r in rows:
        defects = [
            {"name": it.get("name"), "cat": it.get("cat"), "notes": (it.get("notes") or "")[:140]}
            for it in (r.get("items") or []) if it.get("status") == "defeito"
        ]
        summary.append({
            "date": (r.get("created_at") or "")[:10],
            "plate": r.get("plate"),
            "conformity_pct": (r.get("conformity") or {}).get("pct"),
            "defects": defects[:10],
            "damage_marks_count": len(r.get("damage_marks") or []),
            "general_notes": (r.get("general_notes") or "")[:200],
        })

    prompt = (
        f"Colaborador: {coll.get('name')} · {coll.get('role') or '—'}\n"
        f"Período: últimos {days} dias · {len(rows)} checklist(s).\n\n"
        f"Histórico (mais recente primeiro):\n{json.dumps(summary, ensure_ascii=False)}\n\n"
        "Produza o JSON do health card."
    )
    chat = _new_chat(SYS_HEALTH)
    try:
        raw = await asyncio.wait_for(
            chat.send_message(UserMessage(text=prompt)), timeout=25.0)
    except asyncio.TimeoutError:
        logger.warning("collaborator_health llm timeout 25s")
        return {"collaborator": coll, "period_days": days, "history_count": len(rows),
                "ai": {"score": None, "status": "atenção",
                       "summary": "IA demorou demais (>25s).",
                       "trend": "estável", "open_critical": [],
                       "next_action": {"what": "Revisar checklists manualmente", "when": "agora"},
                       "error": "llm_timeout"}}
    except Exception as e:
        logger.warning("collaborator_health llm failed: %s", e)
        return {"collaborator": coll, "period_days": days, "history_count": len(rows),
                "ai": {"score": None, "status": "atenção",
                       "summary": f"IA indisponível ({type(e).__name__}).",
                       "trend": "estável", "open_critical": [],
                       "next_action": {"what": "Revisar checklists manualmente", "when": "agora"},
                       "error": str(e)[:200]}}
    data = _parse_json(raw)
    return {"collaborator": coll, "period_days": days, "history_count": len(rows),
            "ai": data or {"score": None, "status": "atenção",
                           "summary": "IA respondeu em formato inesperado.",
                           "trend": "estável", "open_critical": [], "next_action": None}}
