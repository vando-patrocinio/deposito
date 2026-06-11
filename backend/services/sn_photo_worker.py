"""
iter215am — Worker assíncrono: analisa fotos de equipamento (ONT) de OS
de retirada/troca cujo SN não estava no SmartOLT.

Modelo: Claude Sonnet 4.6 (claude-sonnet-4-6-20250929) via OpenRouter.

Fluxo:
  1. A cada 30s, busca tickets com ai_sn_photo_review_pending=True
  2. Pega a 1ª foto de completion_data.fotos (data URL)
  3. Manda pro Claude com prompt estruturado pedindo SN/MAC/modelo/condição
  4. Atualiza o ticket com ai_sn_photo_review_result e remove o flag
  5. Caso a IA identifique SN/MAC, grava no client_equipment_history pra
     manter rastreabilidade

Custo aproximado: ~$0.003 por foto (Claude Sonnet 4.5 a $3/Mtok input).
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
import re
from datetime import datetime, timezone

from database import db
from services.motor_ia import chat_completion

logger = logging.getLogger("sn_photo_worker")

CLAUDE_MODEL = "claude-sonnet-4-6-20250929"
POLL_INTERVAL_SEC = 30

PROMPT = """Você é um especialista em equipamentos de fibra óptica (ONT, ONU,
modems, ROTEADORES).

Analise a foto e responda EM JSON. Schema obrigatório:
{
  "is_equipment": true|false,        // foto mostra equipamento de telecom?
  "equipment_type": "ont"|"roteador"|"modem"|"switch"|"desconhecido",
  "brand": "Intelbras"|"Huawei"|"ZTE"|"VSol"|"Fiberhome"|"Phyhome"|"...",
  "model": "string ou null",
  "serial_number": "string ou null",  // SN visível na etiqueta
  "mac_address": "string ou null",    // MAC no formato AA:BB:CC:DD:EE:FF
  "condition": "novo"|"usado_ok"|"danificado"|"sem_etiqueta",
  "quality_score": 0..100,           // qualidade da foto
  "reasoning": "frase curta máx 140 chars"
}

Regras:
- is_equipment=false se for paisagem, pessoa, ou outro objeto.
- Se etiqueta ilegível, deixe serial_number/mac_address como null e baixe
  quality_score.
- Se modelo não estiver visível, deixe null.
- Seja conservador. Em dúvida use condition="sem_etiqueta".
- Responda APENAS o JSON. Sem markdown, sem ```."""


def _extract_first_image(fotos):
    """Recebe lista de fotos do completion_data e devolve a 1ª como data URL."""
    if not fotos:
        return None
    for f in fotos:
        if isinstance(f, str) and f.startswith("data:image"):
            return f
        if isinstance(f, dict):
            url = f.get("url") or f.get("data") or ""
            if url.startswith("data:image"):
                return url
    return None


def _parse_json_safe(text: str) -> dict | None:
    """Tenta parsear JSON do retorno. Aceita variantes com ```json ... ```."""
    if not text:
        return None
    # Remove fences se vier markdown
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except Exception:
        # Tenta extrair primeiro objeto JSON
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
        return None


async def _analyze_ticket(ticket: dict) -> dict:
    """Roda Claude na foto do ticket. Retorna o resultado IA."""
    cid = ticket.get("company_id") or "co-demo"
    fotos = ((ticket.get("completion_data") or {}).get("fotos")) or []
    image = _extract_first_image(fotos)
    if not image:
        return {"ok": False, "error": "no_image"}

    # Monta mensagem multimodal pro Claude
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": image}},
        ]},
    ]
    try:
        resp = await chat_completion(
            cid, messages, model=CLAUDE_MODEL,
            temperature=0.1, max_tokens=400,
            json_mode=True,
            purpose="general", agent="sn_photo_review",
        )
    except Exception as e:
        logger.warning("[sn-photo] chat_completion falhou: %s", e)
        return {"ok": False, "error": f"llm_error: {e!s}"[:120]}

    content = resp.get("content") or ""
    parsed = _parse_json_safe(content)
    if not parsed:
        return {"ok": False, "error": "parse_failed", "raw": content[:200]}

    return {
        "ok": True,
        "result": parsed,
        "model": resp.get("model"),
        "provider": resp.get("provider"),
    }


async def _process_one(ticket: dict):
    ticket_id = ticket.get("id")
    cid = ticket.get("company_id")
    out = await _analyze_ticket(ticket)
    # Atualiza ticket
    update_doc = {
        "ai_sn_photo_review_pending": False,
        "ai_sn_photo_reviewed_at": datetime.now(timezone.utc).isoformat(),
        "ai_sn_photo_review_result": out,
    }
    await db.tickets.update_one({"id": ticket_id}, {"$set": update_doc})
    logger.info(
        "[sn-photo] ticket=%s analisado ok=%s sn=%s mac=%s cond=%s",
        ticket_id, out.get("ok"),
        ((out.get("result") or {}).get("serial_number")),
        ((out.get("result") or {}).get("mac_address")),
        ((out.get("result") or {}).get("condition")),
    )

    # iter215am — Atualiza ONT pendente no estoque do técnico (criada em
    # lousa.public_finalize_ticket) com SN/MAC/modelo extraídos da foto.
    pending_ont = await db.stok_onts.find_one(
        {"ticket_id": ticket_id, "company_id": cid,
         "ai_review_pending": True},
        {"_id": 0, "id": 1, "is_defective": 1, "status": 1},
    )
    if out.get("ok"):
        r = out.get("result") or {}
        sn = (r.get("serial_number") or "").strip().upper() or None
        mac = (r.get("mac_address") or "").strip().upper() or None
        model = (r.get("model") or "").strip() or None
        condition = (r.get("condition") or "").strip().lower() or None
        brand = (r.get("brand") or "").strip() or None
        if pending_ont:
            is_def_existing = bool(pending_ont.get("is_defective"))
            # Se IA detectou "danificado", também marca como defeito
            ia_defect = condition == "danificado"
            final_defective = is_def_existing or ia_defect
            if final_defective:
                next_status = "bloqueado_defeito"
            else:
                # Se IA leu SN/MAC, vira "retirada_com_tecnico" pronto pra
                # reaproveitar. Caso contrário, permanece pendente de revisão
                # humana (sem etiqueta legível).
                next_status = ("retirada_com_tecnico"
                                if (sn or mac)
                                else "pending_human_review")
            update_set = {
                "ai_review_pending": False,
                "ai_reviewed_at": datetime.now(timezone.utc).isoformat(),
                "ai_review_result": r,
                "status": next_status,
            }
            if sn:
                update_set["sn"] = sn
            if mac:
                update_set["mac"] = mac
            if model:
                update_set["model"] = model
            if brand:
                update_set["brand"] = brand
            if ia_defect and not is_def_existing:
                update_set["is_defective"] = True
                update_set["defective_reason"] = (
                    "IA detectou equipamento danificado na foto."
                )
            try:
                await db.stok_onts.update_one(
                    {"id": pending_ont["id"], "company_id": cid},
                    {"$set": update_set},
                )
                logger.info(
                    "[sn-photo] stok_onts %s atualizada: sn=%s mac=%s "
                    "status=%s defeito=%s",
                    pending_ont["id"], sn, mac, next_status, final_defective,
                )
            except Exception as _ue:
                logger.warning(
                    "[sn-photo] update stok_onts falhou id=%s: %s",
                    pending_ont["id"], _ue,
                )
        if sn or mac:
            try:
                from services import client_equipment_history as _ceh
                cs = ticket.get("client_snapshot") or {}
                await _ceh.log_event(
                    company_id=cid,
                    client_id=cs.get("id"),
                    client_name=cs.get("name"),
                    action=("withdraw" if ticket.get("type") == "retirada"
                            else "swap"),
                    ont_sn=sn, ont_mac=mac,
                    actor_id="ai-sn-photo-worker",
                    actor_name="IA SN Photo (Claude 4.6)",
                    ticket_id=ticket_id,
                    notes=(f"SN/MAC extraídos da foto pela IA. "
                           f"Modelo: {r.get('model') or '?'}, "
                           f"Condição: {r.get('condition') or '?'}."),
                )
            except Exception as e:
                logger.warning(
                    "[sn-photo] CEH log falhou ticket=%s: %s", ticket_id, e)
    else:
        # IA falhou: deixa a ONT como pending_human_review pra triagem
        if pending_ont:
            try:
                await db.stok_onts.update_one(
                    {"id": pending_ont["id"], "company_id": cid},
                    {"$set": {
                        "ai_review_pending": False,
                        "ai_reviewed_at":
                            datetime.now(timezone.utc).isoformat(),
                        "ai_review_error": out.get("error"),
                        "status": ("bloqueado_defeito"
                                    if pending_ont.get("is_defective")
                                    else "pending_human_review"),
                    }},
                )
            except Exception as _ue:
                logger.warning(
                    "[sn-photo] update fallback falhou id=%s: %s",
                    pending_ont["id"], _ue,
                )


async def sn_photo_worker():
    """Loop principal — varre tickets com flag pendente."""
    logger.info("[sn-photo] worker iniciado (Claude %s)", CLAUDE_MODEL)
    while True:
        try:
            cursor = db.tickets.find(
                {"ai_sn_photo_review_pending": True},
                {"_id": 0, "id": 1, "company_id": 1, "type": 1,
                 "completion_data": 1, "client_snapshot": 1},
            ).limit(5)
            async for t in cursor:
                try:
                    await _process_one(t)
                except Exception as e:
                    logger.exception(
                        "[sn-photo] erro ticket %s: %s", t.get("id"), e)
        except Exception as e:
            logger.exception("[sn-photo] loop error: %s", e)
        await asyncio.sleep(POLL_INTERVAL_SEC)
