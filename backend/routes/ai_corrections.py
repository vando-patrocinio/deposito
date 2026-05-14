"""Correções da Isabella IA — Edit & Teach.

Permite ao gestor abrir QUALQUER bolha de resposta da IA e:
- Corrigir o texto que foi enviado errado
- Opcionalmente reenviar a versão corrigida ao cliente
- A correção fica persistida em `db.ai_corrections` e é injetada
  no system prompt da Isabella nas próximas respostas (memória de aprendizado).

Schema `ai_corrections`:
- id (str)
- company_id (str)
- phone (str)                        ─ telefone da conversa onde aconteceu
- original_msg_id (str | None)       ─ id da mensagem que estava errada
- user_question (str)                ─ última pergunta do cliente
- ai_original_reply (str)            ─ o que a IA respondeu
- correct_reply (str)                ─ o que ela DEVERIA ter respondido
- reason (str)                       ─ por que estava errado
- tags (list[str])
- corrected_by (str)                 ─ user id / email do gestor
- created_at (iso)
- resent_to_client (bool)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.ai_corrections")
router = APIRouter(prefix="/api/ai-corrections", tags=["ai_corrections"])


class CorrectionIn(BaseModel):
    phone: str
    original_msg_id: Optional[str] = None
    user_question: str = ""
    ai_original_reply: str
    correct_reply: str = Field(..., min_length=2, max_length=4000)
    reason: Optional[str] = ""
    tags: List[str] = Field(default_factory=list)
    resend_to_client: bool = False


@router.post("")
async def create_correction(payload: CorrectionIn,
                              user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    doc = {
        "id": f"corr-{uuid.uuid4().hex[:12]}",
        "company_id": cid,
        "phone": payload.phone.strip(),
        "original_msg_id": payload.original_msg_id,
        "user_question": payload.user_question.strip()[:1000],
        "ai_original_reply": payload.ai_original_reply.strip()[:2000],
        "correct_reply": payload.correct_reply.strip()[:4000],
        "reason": (payload.reason or "").strip()[:500],
        "tags": [t.strip() for t in (payload.tags or []) if t and t.strip()][:10],
        "corrected_by": user.get("email") or user.get("name") or user.get("id"),
        "corrected_by_id": user.get("id"),
        "created_at": now_iso(),
        "resent_to_client": False,
    }
    await db.ai_corrections.insert_one(doc)
    doc.pop("_id", None)

    # Reenvia a versão corrigida ao cliente (se solicitado) usando o mesmo
    # canal preferencial (Baileys → Twilio → Meta).
    if payload.resend_to_client:
        try:
            sent = await _resend_corrected(cid, payload.phone, payload.correct_reply,
                                            correction_id=doc["id"])
            doc["resent_to_client"] = sent
            if sent:
                await db.ai_corrections.update_one(
                    {"id": doc["id"]}, {"$set": {"resent_to_client": True}}
                )
        except Exception as e:
            logger.warning("[ai_corrections] resend falhou: %s", e)
            doc["resend_error"] = str(e)
    return doc


@router.get("")
async def list_corrections(limit: int = 50,
                            user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    items = await db.ai_corrections.find(
        {"company_id": cid}, {"_id": 0}
    ).sort("created_at", -1).limit(min(max(limit, 1), 200)).to_list(200)
    return {"items": items, "count": len(items)}


@router.delete("/{corr_id}")
async def delete_correction(corr_id: str,
                              user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    res = await db.ai_corrections.delete_one({"id": corr_id, "company_id": cid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Correção não encontrada.")
    return {"ok": True}


async def fetch_recent_for_prompt(company_id: str, limit: int = 12) -> list[dict]:
    """Retorna as N correções mais recentes do tenant — usado pelo builder de
    prompt da Isabella para injetar memória de aprendizado.
    """
    items = await db.ai_corrections.find(
        {"company_id": company_id},
        {"_id": 0, "user_question": 1, "ai_original_reply": 1,
         "correct_reply": 1, "reason": 1, "tags": 1, "created_at": 1},
    ).sort("created_at", -1).limit(min(max(limit, 1), 30)).to_list(30)
    return items


def format_corrections_for_prompt(items: list[dict]) -> str:
    """Formata as correções como bloco de "memória de aprendizado" para
    injetar no system prompt da Isabella.
    """
    if not items:
        return ""
    lines = [
        "=== MEMÓRIA DE CORREÇÕES (não repita estes erros) ===",
        "Sua gestora já te corrigiu nas situações abaixo. Aprenda o padrão "
        "correto e NÃO volte a errar do mesmo jeito:",
    ]
    for i, it in enumerate(items[:10], 1):
        q = (it.get("user_question") or "").strip()
        wrong = (it.get("ai_original_reply") or "").strip()
        right = (it.get("correct_reply") or "").strip()
        reason = (it.get("reason") or "").strip()
        lines.append(f"\n— Correção {i}:")
        if q:
            lines.append(f"  • Cliente disse: {q[:200]}")
        lines.append(f"  • Você respondeu ERRADO: {wrong[:240]}")
        lines.append(f"  • Resposta CORRETA: {right[:280]}")
        if reason:
            lines.append(f"  • Motivo: {reason[:180]}")
    return "\n".join(lines)


async def _resend_corrected(cid: str, phone: str, text: str,
                              correction_id: str) -> bool:
    """Envia a versão corrigida ao cliente via canal Baileys (sidecar local).
    Persiste a mensagem no histórico `aihub_wa_messages` para o gestor ver
    no chat com flag `is_correction=True`.
    """
    import httpx
    import os
    sidecar_base = os.environ.get("WA_SIDECAR_URL", "http://localhost:8002")
    sent = False
    send_error = None
    out: dict = {}
    try:
        async with httpx.AsyncClient(timeout=20.0) as cli:
            r = await cli.post(f"{sidecar_base}/send",
                                json={"phone": phone, "text": text})
            try:
                out = r.json()
            except Exception:
                out = {"raw": r.text}
            if r.status_code < 400 and out.get("ok"):
                sent = True
            else:
                send_error = out.get("error") or f"HTTP {r.status_code}"
    except Exception as e:
        send_error = str(e)
        logger.info("[ai_corrections] sidecar send falhou: %s", e)

    # Persiste no histórico SEMPRE — gestor precisa ver mesmo se falhou
    await db.aihub_wa_messages.insert_one({
        "id": f"wam-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "phone": phone,
        "direction": "outbound",
        "text": text,
        "message_id": out.get("message_id"),
        "auto_reply": True,
        "is_correction": True,
        "correction_id": correction_id,
        "delivery_status": "sent" if sent else "failed",
        "delivery_error": send_error,
        "created_at": now_iso(),
    })
    return sent
