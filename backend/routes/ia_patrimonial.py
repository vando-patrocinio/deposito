"""IA Patrimonial · Onda 1 — endpoints READ-ONLY (shadow mode)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from database import db
from core import get_current_user  # type: ignore
from services.ia_patrimonial_extractor import (
    extract_from_narrative, compare_ia_vs_form,
)

router = APIRouter(prefix="/api/lousa", tags=["ia-patrimonial"])


class ExtractRequest(BaseModel):
    narrative: Optional[str] = None  # opcional: se vazio, usa completion_data.descricao
    use_llm: bool = True


@router.post("/tickets/{ticket_id}/ai-extract-materials")
async def ai_extract_materials(ticket_id: str, payload: ExtractRequest,
                                  user: dict = Depends(get_current_user)):
    """Lê narrativa (do payload OU do ticket) e devolve interpretação IA.

    SHADOW MODE: zero writes em stok_history / movimentação patrimonial.
    Apenas extração + comparação com o formulário, se existir.
    """
    cid = user.get("company_id")
    t = await db.tickets.find_one({"id": ticket_id, "company_id": cid},
                                     {"_id": 0})
    if not t:
        raise HTTPException(404, "Ticket não encontrado")
    cd = t.get("completion_data") or {}
    narrative = (payload.narrative or cd.get("descricao")
                  or cd.get("observacao") or t.get("description") or "")
    if not narrative.strip():
        return {
            "ok": False,
            "reason": "narrative_empty",
            "ticket_id": ticket_id,
        }
    ia = await extract_from_narrative(
        narrative,
        ticket_type_hint=t.get("type"),
        use_llm=payload.use_llm,
    )
    cmp = compare_ia_vs_form(ia, cd)
    return {
        "ok": True,
        "ticket_id": ticket_id,
        "ticket_type": t.get("type"),
        "narrative_used": narrative[:300],
        "ia": ia,
        "comparison_vs_form": cmp,
        "mode": "shadow_read_only",
    }
