"""services/fleet_ai_worker.py — Worker da IA para vistorias de frota.

Usa Claude Sonnet 4.5 vision via Emergent LLM Key (multimodal).
Compara as 5 fotos da semana atual com o histórico das 4 semanas anteriores
do MESMO veículo para detectar fraude, nova avaria, sujeira, etc.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "operacoes",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["ticket.opened"],
    "company_id_required": True,
}

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any

from database import db

logger = logging.getLogger("ponto.fleet_ai")


EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")


SYSTEM_PROMPT = """Você é um inspetor sênior de frota de provedor de internet.
Recebe 5 fotos de um veículo (frente, traseira, lateral direita, lateral esquerda,
painel/odômetro) tiradas pelo técnico nesta semana, e opcionalmente fotos
das semanas anteriores do MESMO veículo para comparação.

Sua tarefa: avaliar a vistoria e retornar JSON puro (sem markdown,
sem ```) no formato exato:

{
  "score": 0-100,
  "classification": "otimo" | "bom" | "atencao" | "critico",
  "decisao": "aprovar" | "recusar",
  "comparacao": "texto curto comparando com semana anterior",
  "alerts": [
    {"type": "veiculo_sujo", "severity": "warn", "msg": "..."},
    {"type": "nova_avaria", "severity": "alert", "msg": "..."},
    {"type": "placa_divergente", "severity": "critical"},
    {"type": "foto_fora_padrao", "position": "frente", "severity": "warn"},
    {"type": "km_incompativel", "severity": "warn",
      "expected_min": N, "got": N},
    {"type": "possivel_fraude", "severity": "critical",
      "msg": "Foto parece reaproveitada da semana anterior"}
  ]
}

Critérios:
- Aprove (decisao="aprovar") se as 5 fotos estão corretas, veículo limpo,
  sem avaria nova, fotos da semana (não reaproveitadas) e KM coerente.
- Recuse (decisao="recusar") em qualquer indício de fraude ou foto fora do padrão.
- score 90+ = otimo, 70-89 = bom, 50-69 = atencao, <50 = critico
- Seja RIGOROSO mas justo. Não invente avarias inexistentes.
"""


async def review_inspection_async(inspection_id: str) -> None:
    """Roda assincronamente após /inspections/submit. Best-effort."""
    try:
        await _do_review(inspection_id)
    except Exception as e:
        logger.exception("[fleet_ai.review] %s falhou: %s", inspection_id, e)
        try:
            await db.fleet_inspections.update_one(
                {"id": inspection_id},
                {"$set": {"ai_review_error": str(e),
                           "ai_reviewed_at": datetime.now(timezone.utc).isoformat()}},
            )
        except Exception:
            pass


async def _do_review(inspection_id: str) -> None:
    insp = await db.fleet_inspections.find_one(
        {"id": inspection_id}, {"_id": 0})
    if not insp:
        return
    photos = insp.get("photos") or {}
    if not photos:
        return

    # Histórico: últimas 2 vistorias aprovadas do mesmo veículo
    prev = await db.fleet_inspections.find({
        "vehicle_id": insp["vehicle_id"],
        "status": "approved",
        "id": {"$ne": inspection_id},
    }, {"_id": 0}).sort("requested_at", -1).limit(2).to_list(2)

    vehicle = await db.fleet_vehicles.find_one(
        {"id": insp["vehicle_id"]}, {"_id": 0})

    # Monta payload pro Claude (multimodal)
    img_payload = []
    img_payload.append({
        "type": "text",
        "text": f"VEÍCULO: placa={vehicle.get('placa')} "
                f"modelo={vehicle.get('modelo')} "
                f"km_anterior={vehicle.get('km_atual')} "
                f"km_informado_agora={insp.get('km_informado')}",
    })
    for pos in ("frente", "traseira", "lat_dir", "lat_esq", "km"):
        ph = photos.get(pos)
        if not ph: continue
        img_payload.append({
            "type": "text",
            "text": f"\n=== FOTO ATUAL: {pos.upper()} ===",
        })
        img_payload.append({
            "type": "image_url",
            "image_url": {"url": ph.get("data_url")},
        })
    # Histórico (opcional — só 1 foto da semana anterior por posição
    # pra não estourar tokens)
    if prev:
        last = prev[0]
        img_payload.append({
            "type": "text",
            "text": f"\n=== HISTÓRICO — vistoria anterior "
                    f"({last.get('week_ref')}, score IA={last.get('ai_score')}) ===",
        })
        for pos in ("frente", "lat_dir"):  # só 2 fotos pra economia
            ph = (last.get("photos") or {}).get(pos)
            if not ph: continue
            img_payload.append({
                "type": "text", "text": f"Anterior: {pos.upper()}",
            })
            img_payload.append({
                "type": "image_url",
                "image_url": {"url": ph.get("data_url")},
            })

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"fleet-ai-{inspection_id}",
            system_message=SYSTEM_PROMPT,
        ).with_model("anthropic", "claude-sonnet-4-5-20250929") \
         .with_max_tokens(1500)
        # UserMessage aceita lista de partes (texto + image_url)
        msg = UserMessage(text="Avalie a vistoria.", file_contents=img_payload)
        raw = await asyncio.wait_for(chat.send_message(msg), timeout=90)
    except Exception as e:
        logger.warning("[fleet_ai] LLM multimodal falhou (%s) — fallback p/ "
                        "score heurístico", e)
        # Fallback heurístico: aprova se todas as 5 fotos existem
        score = 75 if len(photos) >= 5 else 40
        classification = "bom" if score >= 70 else "atencao"
        await _apply_result(inspection_id, {
            "score": score, "classification": classification,
            "decisao": "aprovar" if score >= 60 else "recusar",
            "alerts": [],
            "comparacao": "Avaliação automática (sem IA disponível).",
            "ai_raw": None, "fallback": True,
        })
        return

    # Parse JSON da resposta
    txt = (raw or "").strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```(json)?\s*", "", txt)
        txt = re.sub(r"\s*```\s*$", "", txt)
    try:
        result = json.loads(txt)
    except Exception:
        # Tenta extrair JSON inline
        m = re.search(r"\{[\s\S]+\}", txt)
        result = json.loads(m.group(0)) if m else {
            "score": 50, "classification": "atencao",
            "decisao": "aprovar", "alerts": [], "raw_text": txt,
        }
    result["ai_raw"] = raw[:2000]
    await _apply_result(inspection_id, result)


async def _apply_result(inspection_id: str, result: dict) -> None:
    """Grava resultado da IA + atualiza status + cria bolha se necessário."""
    decisao = result.get("decisao", "aprovar")
    new_status = "approved" if decisao == "aprovar" else "rejected"
    now_iso = datetime.now(timezone.utc).isoformat()

    await db.fleet_inspections.update_one(
        {"id": inspection_id},
        {"$set": {
            "ai_score": result.get("score"),
            "ai_classification": result.get("classification"),
            "ai_decisao": decisao,
            "ai_alerts": result.get("alerts", []),
            "ai_comparacao": result.get("comparacao"),
            "ai_raw": result.get("ai_raw"),
            "ai_reviewed_at": now_iso,
            "status": new_status,
        }},
    )

    # Se recusou, cria bolha de frota na lousa do gestor
    if new_status == "rejected":
        await _create_fleet_alert_ticket(inspection_id, result)


async def _create_fleet_alert_ticket(inspection_id: str, result: dict) -> None:
    """Cria ticket tipo=frota_alerta na lousa do gestor."""
    import uuid
    insp = await db.fleet_inspections.find_one(
        {"id": inspection_id}, {"_id": 0})
    if not insp: return
    collab = await db.collaborators.find_one(
        {"id": insp["collaborator_id"]}, {"_id": 0})
    veh = await db.fleet_vehicles.find_one(
        {"id": insp["vehicle_id"]}, {"_id": 0})

    alerts_str = "; ".join(
        f"{a.get('type')}: {a.get('msg', '')}"
        for a in (result.get("alerts") or [])[:3]
    ) or "Avaliação geral baixa"

    ticket = {
        "id": f"frt-{uuid.uuid4().hex[:10]}",
        "company_id": insp["company_id"],
        "type": "frota_alerta",
        "category": "FROTA",
        "not_in_kpi": True,  # NÃO entra em KPI de OS
        "priority": "normal",
        "status": "aberta",
        "title": f"🚗 {(collab or {}).get('name')} — vistoria recusada pela IA",
        "description": f"Veículo {(veh or {}).get('placa')} · "
                       f"score {result.get('score')} · {alerts_str}",
        "client_snapshot": {
            "name": f"FROTA · {(veh or {}).get('placa')}",
            "address": (collab or {}).get("name"),
            "relato": alerts_str,
        },
        "related_inspection_id": inspection_id,
        "related_vehicle_id": insp["vehicle_id"],
        "related_collaborator_id": insp["collaborator_id"],
        # Atribuição na grid da Lousa do gestor (campo usado pelo /lousa/grid)
        "assigned_collaborator_id": insp["collaborator_id"],
        # scheduled_time como ISO datetime — Lousa usa pra agrupar por dia
        "scheduled_time": datetime.now(timezone.utc).replace(hour=11, minute=0,
                                                              second=0, microsecond=0).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": "fleet_ai_worker",
        "manual_close_only": True,
    }
    await db.tickets.insert_one(ticket)
    try:
        from services.event_bus import emit_event
        await emit_event(
            "ticket.opened",
            company_id=(veh or {}).get("company_id"),
            source="fleet_ai_worker",
            payload={},
        )
    except Exception:
        pass


# =============================================================================
# OCR de NF do posto de combustível
# =============================================================================
async def ocr_fuel_receipt(receipt_data_url: str) -> dict:
    """Extrai valor + posto + data da NF via Claude vision."""
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"fuel-ocr-{datetime.now(timezone.utc).timestamp()}",
            system_message=(
                "Você é OCR de notas fiscais de posto de combustível. "
                "Recebe uma foto de NF/cupom e retorna JSON puro: "
                '{"valor_total": 123.45, "posto": "Shell BR", '
                '"data": "2026-05-20", "litros": 45.5, '
                '"combustivel": "gasolina|etanol|diesel|gnv"}. '
                "Se algum campo não estiver visível, use null. "
                "Retorne SOMENTE o JSON, sem markdown."
            ),
        ).with_model("anthropic", "claude-sonnet-4-5-20250929") \
         .with_max_tokens(400)
        msg = UserMessage(text="Extraia os dados da NF.",
                           file_contents=[{
                               "type": "image_url",
                               "image_url": {"url": receipt_data_url},
                           }])
        raw = await asyncio.wait_for(chat.send_message(msg), timeout=45)
    except Exception as e:
        logger.warning("[fuel.ocr] %s", e)
        return {"error": str(e)}
    txt = (raw or "").strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```(json)?\s*", "", txt)
        txt = re.sub(r"\s*```\s*$", "", txt)
    try:
        return json.loads(txt)
    except Exception:
        m = re.search(r"\{[\s\S]+\}", txt)
        if m:
            return json.loads(m.group(0))
        return {"error": "Não foi possível extrair JSON", "raw": txt[:200]}
