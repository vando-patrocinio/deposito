"""Pré-visualização e configuração do template do PDF de boleto.

Endpoints:
  GET    /api/boleto/preview                — devolve PDF sample (mock) para o gestor ver o branding
  GET    /api/boleto/preview/{subscriber_id} — devolve PDF com a 1ª fatura aberta de um cliente real
  GET    /api/boleto/logo                    — info do logo atual (custom/default)
  PUT    /api/boleto/logo                    — sobe logo customizado (PNG/JPG, ≤2MB)
  DELETE /api/boleto/logo                    — volta pro logo padrão
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

import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, require_role
from database import db
from services.boleto_pdf import _resolve_logo, build_boleto_pdf

logger = logging.getLogger("ponto.boleto_template")
router = APIRouter(prefix="/api/boleto", tags=["boleto-template"])


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


# ---------------------------------------------------------------------------
# PREVIEW PDF
# ---------------------------------------------------------------------------
SAMPLE_INVOICE = {
    "amount": 119.90,
    "pix_copia_cola": (
        "00020126890014BR.GOV.BCB.PIX2563api.itau-pix.com.br/qr/"
        "DEMO-PREVIEW-A1B2-C3D4-E5F6789012345520400005303986540"
        "5119.905802BR5925LIGO FIBRA DEMO PREVIEW6009SAO PAULO"
        "62070503***6304ABCD"
    ),
    "digitable_line": "34191790010104351004791020150008191180000011990",
}


@router.get("/preview")
async def preview_sample(user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    sample = dict(SAMPLE_INVOICE)
    # Vencimento amanhã pra ficar realista
    sample["due_date"] = (datetime.now(timezone.utc).date()
                          + timedelta(days=5)).isoformat()
    logo = await _resolve_logo(cid)
    pdf = build_boleto_pdf(
        sample, customer_name="Cliente Demonstração",
        logo_bytes=logo,
    )
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition":
                 'inline; filename="Boleto Ligo Preview.pdf"'},
    )


def _pdf_to_png(pdf_bytes: bytes) -> bytes:
    """Renderiza primeira página do PDF como PNG via pdftoppm.

    Mais confiável que `<iframe src="...pdf">` que muitos browsers
    bloqueiam ou exigem plugin externo.
    """
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as src:
        src.write(pdf_bytes)
        src_path = src.name
    out_prefix = src_path.replace(".pdf", "")
    try:
        subprocess.run(
            ["pdftoppm", "-r", "110", "-png", "-f", "1", "-l", "1",
             src_path, out_prefix],
            check=True, timeout=15,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        # pdftoppm gera arquivos com sufixo "-1.png"
        from pathlib import Path as _P
        png_file = _P(out_prefix + "-1.png")
        if png_file.exists():
            data = png_file.read_bytes()
            try:
                png_file.unlink()
            except Exception:
                pass
            return data
        raise RuntimeError("PNG não foi gerado pelo pdftoppm")
    finally:
        try:
            from pathlib import Path as _P
            _P(src_path).unlink(missing_ok=True)
        except Exception:
            pass


@router.get("/preview.png")
async def preview_sample_png(user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    sample = dict(SAMPLE_INVOICE)
    sample["due_date"] = (datetime.now(timezone.utc).date()
                          + timedelta(days=5)).isoformat()
    logo = await _resolve_logo(cid)
    pdf = build_boleto_pdf(
        sample, customer_name="Cliente Demonstração",
        logo_bytes=logo,
    )
    try:
        png = _pdf_to_png(pdf)
    except Exception as e:
        logger.warning("[boleto-preview-png] %s", e)
        raise HTTPException(503, f"Falha ao renderizar preview: {e}")
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@router.get("/preview/{subscriber_id}")
async def preview_real(subscriber_id: str,
                         user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    sub = await db.subscribers.find_one(
        {"company_id": cid, "id": subscriber_id}, {"_id": 0}
    )
    if not sub:
        raise HTTPException(404, "Assinante não encontrado.")
    inv = await db.subscriber_invoices.find_one(
        {"company_id": cid, "subscriber_id": subscriber_id,
         "status": {"$in": ["open", "OPEN", "aberto", "pending"]}},
        {"_id": 0}, sort=[("due_date", 1)],
    )
    if not inv:
        # Nenhuma aberta — pega a última como base pra ainda mostrar layout
        inv = await db.subscriber_invoices.find_one(
            {"company_id": cid, "subscriber_id": subscriber_id},
            {"_id": 0}, sort=[("due_date", -1)],
        )
    if not inv:
        raise HTTPException(404, "Sem faturas para este assinante.")
    logo = await _resolve_logo(cid)
    pdf = build_boleto_pdf(
        inv, customer_name=sub.get("name"), logo_bytes=logo,
    )
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition":
                 f'inline; filename="Boleto {sub.get("name","Cliente")}.pdf"'},
    )


# ---------------------------------------------------------------------------
# LOGO CUSTOMIZADO
# ---------------------------------------------------------------------------
class LogoIn(BaseModel):
    image_data_url: str = Field(..., min_length=20)


@router.get("/logo")
async def get_logo(user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    doc = await db.aihub_settings.find_one(
        {"company_id": cid, "key": "boleto_pdf_logo"},
        {"_id": 0},
    )
    return {
        "custom": bool(doc),
        "image_data_url": (doc or {}).get("image_data_url"),
        "updated_at": (doc or {}).get("updated_at"),
        "updated_by": (doc or {}).get("updated_by"),
        "filename": (doc or {}).get("filename"),
        "size_bytes": (doc or {}).get("size_bytes"),
    }


@router.put("/logo")
async def put_logo(payload: LogoIn,
                     user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    url = payload.image_data_url.strip()
    if not url.startswith("data:image/"):
        raise HTTPException(400,
            "Formato inválido. Use data:image/png;base64,... ou data:image/jpeg;base64,...")
    try:
        header, b64 = url.split(",", 1)
        raw = base64.b64decode(b64)
    except Exception:
        raise HTTPException(400, "Base64 inválido.")
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(400,
            f"Arquivo grande demais ({len(raw)} bytes). Máximo: 2 MB.")
    # Aceita PNG/JPG só
    mtype = header.split(";")[0].replace("data:", "").lower()
    if mtype not in ("image/png", "image/jpeg", "image/webp"):
        raise HTTPException(400,
            "Tipo não suportado. Aceitos: PNG, JPEG, WebP.")
    now = datetime.now(timezone.utc).isoformat()
    await db.aihub_settings.update_one(
        {"company_id": cid, "key": "boleto_pdf_logo"},
        {"$set": {
            "company_id": cid,
            "key": "boleto_pdf_logo",
            "image_data_url": url,
            "size_bytes": len(raw),
            "mimetype": mtype,
            "updated_at": now,
            "updated_by": user.get("email") or "gestor",
        }},
        upsert=True,
    )
    return {"ok": True, "size_bytes": len(raw), "mimetype": mtype}


@router.delete("/logo")
async def delete_logo(user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    r = await db.aihub_settings.delete_one(
        {"company_id": cid, "key": "boleto_pdf_logo"}
    )
    return {"ok": True, "deleted": r.deleted_count}
