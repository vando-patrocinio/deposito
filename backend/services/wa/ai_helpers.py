"""Helpers do pipeline IA do WhatsApp Baileys.

Funções extraídas de routes/whatsapp_baileys.py em iter106:
  - fetch_human_few_shots: busca exemplos de atendentes humanos com CSAT
    alto pra usar como few-shot examples no prompt da IA.
  - persist_ai_failure: persiste falha de auto-reply com `delivery_status=failed_*`
    e dispara system_event quando acumulam >=3 falhas em 24h.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core import now_iso
from database import db

logger = logging.getLogger("ponto.wa_baileys")


async def fetch_human_few_shots(cid: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Busca pares (cliente perguntou → atendente humano respondeu) das conversas
    avaliadas com CSAT alto (>=8). Usado como few-shot examples no system_prompt
    da IA pra ela aprender padrões que conquistaram clientes.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    top_evals = await db.aihub_evaluations.find(
        {"company_id": cid, "csat_score": {"$gte": 8},
         "evaluated_at": {"$gte": cutoff}},
        {"_id": 0, "phone": 1, "csat_score": 1, "evaluated_at": 1},
    ).sort("evaluated_at", -1).limit(20).to_list(20)
    examples: List[Dict[str, Any]] = []
    seen_phones = set()
    for ev in top_evals:
        ph = ev.get("phone")
        if not ph or ph in seen_phones:
            continue
        msgs = await db.aihub_wa_messages.find(
            {"company_id": cid, "phone": ph,
             "$or": [{"direction": "inbound"},
                       {"direction": "outbound", "auto_reply": {"$ne": True},
                        "sent_by_user_id": {"$nin": [None, ""]}}]},
            {"_id": 0, "direction": 1, "text": 1, "created_at": 1,
             "auto_reply": 1},
        ).sort("created_at", 1).to_list(60)
        # Pega o primeiro par inbound→outbound(human) coerente
        for i, m in enumerate(msgs[:-1]):
            if m.get("direction") == "inbound":
                nxt = msgs[i + 1]
                if nxt.get("direction") == "outbound" and not nxt.get("auto_reply"):
                    q = (m.get("text") or "").strip()
                    a = (nxt.get("text") or "").strip()
                    if 5 <= len(q) <= 280 and 5 <= len(a) <= 600:
                        examples.append({"q": q, "a": a,
                                            "csat": ev.get("csat_score")})
                        seen_phones.add(ph)
                        break
        if len(examples) >= limit:
            break
    return examples


async def persist_ai_failure(cid: str, phone: str, subscriber_id: Optional[str],
                                reason_code: str, reason_msg: str,
                                user_text: str = "",
                                agent: Optional[dict] = None) -> None:
    """Persiste uma falha do auto-reply IA. Substitui o antigo `return None`
    silencioso. Cada falha vira um registro outbound com `delivery_status`
    iniciado por 'failed_' para que o frontend possa destacar."""
    doc = {
        "id": f"wam-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "direction": "outbound",
        "phone": phone,
        "text": "",  # nada foi enviado
        "channel": "baileys",
        "subscriber_id": subscriber_id,
        "session_id": f"wa-{phone}",
        "auto_reply": True,
        "delivery_status": f"failed_{reason_code}",
        "delivery_error": reason_msg[:300],
        "user_text_snapshot": (user_text or "")[:240],
        "created_at": now_iso(),
    }
    if agent:
        doc["agent_id"] = agent.get("id")
        doc["agent_name"] = agent.get("name")
    try:
        await db.aihub_wa_messages.insert_one(doc)
    except Exception as e:
        logger.warning("[wa-baileys] falha ao persistir failure: %s", e)
    # Dispara system_event se acumular ≥3 falhas em 24h (recurso já existente)
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        n = await db.aihub_wa_messages.count_documents({
            "company_id": cid, "direction": "outbound",
            "auto_reply": True,
            "delivery_status": {"$regex": "^failed_"},
            "created_at": {"$gte": cutoff},
        })
        if n >= 3:
            await db.wa_system_events.insert_one({
                "id": f"sys-{uuid.uuid4().hex[:10]}",
                "company_id": cid,
                "kind": "ai_attendant_unhealthy",
                "text": f"IA com {n} falha(s) nas últimas 24h · {reason_code}",
                "data": {"reason_code": reason_code, "failures_24h": n,
                         "last_reason": reason_msg[:120]},
                "created_at": now_iso(),
            })
    except Exception as e:
        logger.info("[wa-baileys] system_event ai_unhealthy skip: %s", e)
