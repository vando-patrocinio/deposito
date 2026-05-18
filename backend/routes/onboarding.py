"""Rotas REST para o onboarding seguro de novos clientes.

Endpoints:
  POST /api/onboarding/sessions               (gestor — cria sessão)
  GET  /api/onboarding/public/{token}         (público — valida token + retorna metadata)
  POST /api/onboarding/public/{token}/upload  (público — upload de imagem)
  POST /api/onboarding/public/{token}/submit  (público — finaliza com email/vencimento)
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, require_role
from services.onboarding import (
    create_session, get_session_for_token, liveness_check, save_upload,
    submit_form,
)

logger = logging.getLogger("ponto.onboarding_routes")
router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


# ---------------------------------------------------------------------------
# Gestor — cria sessão (gera URL única)
# ---------------------------------------------------------------------------

class CreateSessionIn(BaseModel):
    phone: str
    plan_name: Optional[str] = None
    suggested_name: Optional[str] = None
    suggested_email: Optional[str] = None


@router.post("/sessions")
async def create_session_route(
    payload: CreateSessionIn,
    user: dict = Depends(require_role("gestor")),
):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    result = await create_session(
        company_id=cid,
        phone=payload.phone,
        plan_name=payload.plan_name,
        suggested_name=payload.suggested_name,
        suggested_email=payload.suggested_email,
    )
    return result


# ---------------------------------------------------------------------------
# Público — valida token + retorna metadata enxuta pra UI
# ---------------------------------------------------------------------------

@router.get("/public/{token}")
async def public_get_session(token: str):
    sess = await get_session_for_token(token)
    if not sess:
        raise HTTPException(404, "Sessão inválida ou expirada")
    # Retorna só metadata segura pra UI (sem files completos / pre_registration)
    return {
        "session_id": sess["id"],
        "status": sess.get("status"),
        "phone": sess.get("phone"),
        "plan_name": sess.get("plan_name"),
        "uploaded": sess.get("uploaded") or {},
        "expires_at": sess.get("expires_at"),
        "ocr_hints": {
            "id_document_name": (
                (sess.get("ocr") or {}).get("id_document") or {}
            ).get("name"),
            "address_city": (
                (sess.get("ocr") or {}).get("address_proof") or {}
            ).get("city"),
        },
    }


# ---------------------------------------------------------------------------
# Público — upload de arquivo
# ---------------------------------------------------------------------------

@router.post("/public/{token}/upload")
async def public_upload(
    token: str,
    file_kind: str = Form(..., description="address_proof | id_document | selfie"),
    file: UploadFile = File(...),
):
    try:
        content = await file.read()
        result = await save_upload(
            token=token,
            file_kind=file_kind,
            file_bytes=content,
            filename=file.filename or "upload.jpg",
            content_type=file.content_type or "image/jpeg",
        )
        return result
    except ValueError as ve:
        raise HTTPException(400, str(ve))
    except Exception as e:
        logger.exception("[onboarding] upload error: %s", e)
        raise HTTPException(500, "Falha no upload")


# ---------------------------------------------------------------------------
# Público — liveness check (3 frames: esquerda, direita, sorriso)
# ---------------------------------------------------------------------------

@router.post("/public/{token}/liveness")
async def public_liveness(
    token: str,
    frame_left: UploadFile = File(...),
    frame_right: UploadFile = File(...),
    frame_smile: UploadFile = File(...),
):
    try:
        left_bytes = await frame_left.read()
        right_bytes = await frame_right.read()
        smile_bytes = await frame_smile.read()
        result = await liveness_check(token=token, frames=[
            ("left", left_bytes),
            ("right", right_bytes),
            ("smile", smile_bytes),
        ])
        return result
    except ValueError as ve:
        raise HTTPException(400, str(ve))
    except Exception as e:
        logger.exception("[onboarding] liveness error: %s", e)
        raise HTTPException(500, "Falha na verificação de vivacidade")


# ---------------------------------------------------------------------------
# Público — submit final
# ---------------------------------------------------------------------------

class SubmitFormIn(BaseModel):
    email: str = Field(..., min_length=5, max_length=200)
    due_day: int = Field(..., description="5, 10 ou 15")


@router.post("/public/{token}/submit")
async def public_submit(token: str, payload: SubmitFormIn):
    try:
        return await submit_form(
            token=token, email=payload.email, due_day=payload.due_day,
        )
    except ValueError as ve:
        raise HTTPException(400, str(ve))
    except Exception as e:
        logger.exception("[onboarding] submit error: %s", e)
        raise HTTPException(500, "Falha ao finalizar")
