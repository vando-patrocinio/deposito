"""Pertences/EPIs de cada colaborador — uniforme, ferramental, eletrônicos.

Modelo seguindo prática de RH/Operações:
- Romaneio = lista de itens entregues, assinada pelo colaborador.
- Categorias: uniforme | epi | ferramenta | veiculo | eletronico | outro.
- Status: ativo | devolvido | danificado | perdido.
- Histórico de eventos (entrega, devolução, troca) preservado no `events[]`.

Endpoints públicos (mobile, sem auth) permitem ao colaborador ver seus pertences
e assinar digitalmente o romaneio direto pelo app.
"""
from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db
from routes.branding import get_branding

logger = logging.getLogger("ponto.assets")
router = APIRouter(prefix="/api/collab-assets", tags=["collaborator_assets"])


CATEGORIES = ["uniforme", "epi", "ferramenta", "veiculo", "eletronico", "outro"]
STATUSES = ["ativo", "devolvido", "danificado", "perdido"]


class AssetIn(BaseModel):
    collaborator_id: str
    category: Literal["uniforme", "epi", "ferramenta", "veiculo", "eletronico", "outro"]
    item: str = Field(..., min_length=1, max_length=120)
    marca: Optional[str] = None
    modelo: Optional[str] = None
    tamanho: Optional[str] = None
    serial: Optional[str] = None
    qty: int = Field(default=1, ge=1, le=999)
    unit_value_brl: Optional[float] = Field(default=None, ge=0)
    delivered_at: Optional[str] = None  # ISO; default = agora
    notes: Optional[str] = None


class AssetUpdate(BaseModel):
    category: Optional[Literal["uniforme", "epi", "ferramenta", "veiculo", "eletronico", "outro"]] = None
    item: Optional[str] = Field(default=None, min_length=1, max_length=120)
    marca: Optional[str] = None
    modelo: Optional[str] = None
    tamanho: Optional[str] = None
    serial: Optional[str] = None
    qty: Optional[int] = Field(default=None, ge=1, le=999)
    unit_value_brl: Optional[float] = Field(default=None, ge=0)
    status: Optional[Literal["ativo", "devolvido", "danificado", "perdido"]] = None
    notes: Optional[str] = None


class SignIn(BaseModel):
    collaborator_id: str
    asset_ids: List[str] = Field(..., min_length=1, max_length=200)
    signature_data_url: Optional[str] = None  # data:image/png;base64,... (canvas)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _company_for(coll_id: str) -> str:
    coll = await db.collaborators.find_one({"id": coll_id}, {"_id": 0, "company_id": 1})
    return (coll or {}).get("company_id") or DEMO_COMPANY_ID


def _doc_to_dict(d: dict) -> dict:
    d.pop("_id", None)
    return d


# ---------------------------------------------------------------------------
# Gestor — CRUD
# ---------------------------------------------------------------------------
@router.get("/by-collaborator/{cid}")
async def list_by_collaborator(cid: str,
                                user: dict = Depends(require_role("gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    cur = db.collaborator_assets.find(
        {"company_id": company_id, "collaborator_id": cid}, {"_id": 0},
    ).sort("created_at", -1)
    rows = await cur.to_list(500)
    summary = {"total": len(rows), "ativo": 0, "devolvido": 0,
               "danificado": 0, "perdido": 0,
               "pending_signature": 0}
    for r in rows:
        st = r.get("status", "ativo")
        summary[st] = summary.get(st, 0) + 1
        if not r.get("signed_at"):
            summary["pending_signature"] += 1
    return {"items": rows, "summary": summary}


@router.post("")
async def create_asset(payload: AssetIn,
                       user: dict = Depends(require_role("gestor"))):
    company_id = await _company_for(payload.collaborator_id)
    if user.get("company_id") and user["company_id"] != company_id:
        raise HTTPException(403, "Colaborador não pertence à sua empresa.")
    delivered = payload.delivered_at or now_iso()
    doc = {
        "id": f"asset-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "collaborator_id": payload.collaborator_id,
        "category": payload.category,
        "item": payload.item.strip(),
        "marca": (payload.marca or "").strip() or None,
        "modelo": (payload.modelo or "").strip() or None,
        "tamanho": (payload.tamanho or "").strip() or None,
        "serial": (payload.serial or "").strip() or None,
        "qty": payload.qty,
        "unit_value_brl": payload.unit_value_brl,
        "status": "ativo",
        "delivered_at": delivered,
        "delivered_by": user.get("name") or user.get("email"),
        "returned_at": None,
        "signed_at": None,
        "signature_data_url": None,
        "notes": payload.notes,
        "events": [{
            "at": delivered, "type": "entrega",
            "by": user.get("name") or user.get("email"),
            "notes": payload.notes,
        }],
        "created_at": now_iso(),
    }
    await db.collaborator_assets.insert_one(doc)
    return _doc_to_dict(doc)


@router.patch("/{asset_id}")
async def update_asset(asset_id: str, payload: AssetUpdate,
                       user: dict = Depends(require_role("gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    cur = await db.collaborator_assets.find_one(
        {"id": asset_id, "company_id": company_id}, {"_id": 0})
    if not cur:
        raise HTTPException(404, "Pertence não encontrado.")
    update = payload.model_dump(exclude_unset=True)
    update["updated_at"] = now_iso()
    events = list(cur.get("events") or [])
    new_status = update.get("status")
    if new_status and new_status != cur.get("status"):
        events.append({
            "at": now_iso(), "type": f"status_{new_status}",
            "by": user.get("name") or user.get("email"),
            "from": cur.get("status"), "to": new_status,
        })
        if new_status == "devolvido":
            update["returned_at"] = now_iso()
    update["events"] = events
    await db.collaborator_assets.update_one(
        {"id": asset_id, "company_id": company_id}, {"$set": update})
    out = await db.collaborator_assets.find_one(
        {"id": asset_id, "company_id": company_id}, {"_id": 0})
    return out


@router.delete("/{asset_id}")
async def delete_asset(asset_id: str,
                       user: dict = Depends(require_role("gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    res = await db.collaborator_assets.delete_one(
        {"id": asset_id, "company_id": company_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Pertence não encontrado.")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Mobile (público) — colaborador vê seus pertences e assina
# ---------------------------------------------------------------------------
@router.get("/public/by-collaborator/{cid}")
async def public_list(cid: str):
    company_id = await _company_for(cid)
    cur = db.collaborator_assets.find(
        {"company_id": company_id, "collaborator_id": cid}, {"_id": 0},
    ).sort("created_at", -1)
    rows = await cur.to_list(500)
    coll = await db.collaborators.find_one({"id": cid},
                                           {"_id": 0, "name": 1, "role": 1})
    return {"collaborator": coll or {}, "items": rows}


@router.post("/public/sign")
async def public_sign(payload: SignIn):
    """Colaborador assina o romaneio (digital — base64 PNG do canvas).
    Marca todos os assets indicados como assinados.
    """
    coll = await db.collaborators.find_one(
        {"id": payload.collaborator_id}, {"_id": 0, "company_id": 1})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado.")
    company_id = coll.get("company_id") or DEMO_COMPANY_ID
    sig = payload.signature_data_url
    if sig and not sig.startswith("data:image/"):
        raise HTTPException(400, "signature_data_url inválida.")
    if sig and len(sig) > 800_000:
        raise HTTPException(400, "Assinatura muito grande (max ~600 KB).")
    now = now_iso()
    res = await db.collaborator_assets.update_many(
        {"company_id": company_id, "collaborator_id": payload.collaborator_id,
         "id": {"$in": payload.asset_ids}},
        {"$set": {"signed_at": now,
                  "signature_data_url": sig,
                  "updated_at": now},
         "$push": {"events": {"at": now, "type": "assinado",
                              "by": "colaborador (mobile)"}}})
    if res.modified_count == 0:
        raise HTTPException(404,
            "Nenhum dos asset_ids enviados pertence a este colaborador.")
    return {"ok": True, "signed_count": res.modified_count, "signed_at": now}


# ---------------------------------------------------------------------------
# PDF Romaneio
# ---------------------------------------------------------------------------
def _pt_br_date(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return iso[:10]


def _build_romaneio_pdf(branding: dict, collaborator: dict,
                         assets: List[dict]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                     Table, TableStyle)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.2 * cm,
                            title="Romaneio de Entrega")
    styles = getSampleStyleSheet()
    story: list = []

    # ---- Header: logo + company info ----
    logo_url = (branding or {}).get("logo_data_url") or ""
    header_left = ""
    if logo_url and logo_url.startswith("data:image/"):
        try:
            import base64
            b64 = logo_url.split(",", 1)[1]
            img_bytes = base64.b64decode(b64)
            logo_io = io.BytesIO(img_bytes)
            header_left = Image(logo_io, width=3.5 * cm, height=3.5 * cm,
                                kind="proportional")
        except Exception as e:
            logger.warning("[romaneio] erro decodificando logo: %s", e)
            header_left = Paragraph("<b>LOGO</b>", styles["Normal"])
    else:
        header_left = Paragraph("<b>LOGO</b>", styles["Normal"])

    company_lines = [f"<b>{branding.get('company_name') or 'Empresa'}</b>"]
    if branding.get("cnpj"):
        company_lines.append(f"CNPJ: {branding['cnpj']}")
    addr_parts = [branding.get("address"), branding.get("city"),
                  branding.get("state"), branding.get("zip_code")]
    addr_line = " · ".join([p for p in addr_parts if p])
    if addr_line:
        company_lines.append(addr_line)
    contact = " · ".join([p for p in [branding.get("phone"),
                                       branding.get("email"),
                                       branding.get("website")] if p])
    if contact:
        company_lines.append(contact)
    company_par = Paragraph("<br/>".join(company_lines),
                            ParagraphStyle("c", parent=styles["Normal"],
                                           fontSize=10, leading=13))
    header_table = Table([[header_left, company_par]],
                         colWidths=[4 * cm, None])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "LEFT"),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.4 * cm))

    # ---- Title ----
    story.append(Paragraph(
        "<b>CHECKLIST DE CUSTÓDIA — TERMO DE RESPONSABILIDADE</b>",
        ParagraphStyle("title", parent=styles["Normal"], fontSize=13,
                       alignment=1, leading=16, spaceAfter=4,
                       textColor=colors.HexColor("#0b1220"))))
    story.append(Paragraph(
        "<font color='#0d9488'>Equipamentos · Uniforme · EPIs · Ferramental</font>",
        ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=9,
                       alignment=1, leading=12, spaceAfter=10)))
    story.append(Spacer(1, 0.2 * cm))

    # ---- Collaborator block ----
    issued_at = _pt_br_date(now_iso())
    coll_html = (
        f"<b>Colaborador:</b> {collaborator.get('name', '—')}<br/>"
        f"<b>Cargo:</b> {collaborator.get('role') or '—'} &nbsp;&nbsp; "
        f"<b>CPF:</b> {collaborator.get('cpf') or '—'}<br/>"
        f"<b>Data de emissão:</b> {issued_at}"
    )
    story.append(Paragraph(coll_html,
                           ParagraphStyle("c", parent=styles["Normal"],
                                          fontSize=10, leading=14)))
    story.append(Spacer(1, 0.3 * cm))

    # ---- Items table ----
    head = ["#", "Categoria", "Item", "Marca / Modelo", "Tam.", "Qtd",
            "Série", "Entrega", "Status"]
    data = [head]
    if not assets:
        data.append(["—", "—", "Nenhum item em custódia para este colaborador.",
                     "—", "—", "—", "—", "—", "—"])
    for i, a in enumerate(assets, 1):
        marca_modelo = " / ".join([p for p in [a.get("marca"), a.get("modelo")] if p]) or "—"
        data.append([
            str(i),
            (a.get("category") or "—").upper(),
            a.get("item") or "—",
            marca_modelo,
            a.get("tamanho") or "—",
            str(a.get("qty") or 1),
            a.get("serial") or "—",
            _pt_br_date(a.get("delivered_at")),
            (a.get("status") or "ativo").upper(),
        ])
    items_t = Table(data, repeatRows=1, colWidths=[
        0.8 * cm, 2 * cm, 4.6 * cm, 3 * cm, 1.2 * cm, 1 * cm,
        2 * cm, 2.4 * cm, 1.6 * cm,
    ])
    items_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(items_t)
    story.append(Spacer(1, 0.5 * cm))

    # ---- Footer / Termo de responsabilidade ----
    footer_text = branding.get("romaneio_footer") or (
        "Declaro ter recebido os itens listados acima em perfeito estado e "
        "me responsabilizo por sua guarda, conservação e devolução em caso "
        "de desligamento, sob pena das medidas cabíveis.")
    story.append(Paragraph(
        f"<b>TERMO DE RESPONSABILIDADE:</b> {footer_text}",
        ParagraphStyle("foot", parent=styles["Normal"], fontSize=9,
                       leading=13, alignment=4)))  # 4 = justify
    story.append(Spacer(1, 1.4 * cm))

    # ---- Signature line(s) ----
    # Se algum asset tem assinatura digital, embute. Caso contrário,
    # imprime linha pra assinatura manual.
    sig_url = next((a.get("signature_data_url")
                    for a in assets if a.get("signature_data_url")), None)
    if sig_url:
        try:
            import base64
            b64 = sig_url.split(",", 1)[1]
            sig_io = io.BytesIO(base64.b64decode(b64))
            sig_img = Image(sig_io, width=6 * cm, height=2 * cm,
                            kind="proportional")
            sig_table = Table([[sig_img], ["_" * 50],
                                [f"{collaborator.get('name', '—')} (assinado em "
                                 f"{_pt_br_date(next((a.get('signed_at') for a in assets if a.get('signed_at')), None))})"]],
                              colWidths=[10 * cm])
            sig_table.setStyle(TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]))
            story.append(sig_table)
        except Exception as e:
            logger.warning("[romaneio] falha ao embutir assinatura: %s", e)
            story.append(Paragraph("_" * 60,
                                   ParagraphStyle("s", parent=styles["Normal"],
                                                  alignment=1)))
            story.append(Paragraph(f"{collaborator.get('name', '—')} — Assinatura",
                                   ParagraphStyle("s2", parent=styles["Normal"],
                                                  fontSize=9, alignment=1)))
    else:
        story.append(Paragraph("_" * 60,
                               ParagraphStyle("s", parent=styles["Normal"],
                                              alignment=1)))
        story.append(Paragraph(f"{collaborator.get('name', '—')} — Assinatura",
                               ParagraphStyle("s2", parent=styles["Normal"],
                                              fontSize=9, alignment=1,
                                              spaceBefore=2)))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()


@router.get("/romaneio/{cid}")
async def romaneio_pdf(cid: str,
                       only_active: bool = Query(default=False),
                       user: dict = Depends(require_role("gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado.")
    q = {"company_id": company_id, "collaborator_id": cid}
    if only_active:
        q["status"] = "ativo"
    assets = await db.collaborator_assets.find(q, {"_id": 0}).sort(
        "delivered_at", 1).to_list(500)
    branding = (await get_branding(company_id)).model_dump()
    pdf = _build_romaneio_pdf(branding, coll, assets)
    fname = f"romaneio_{(coll.get('name') or cid).replace(' ', '_').lower()}.pdf"
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf",
                             headers={"Content-Disposition": f'inline; filename="{fname}"'})


@router.get("/public/romaneio/{cid}")
async def public_romaneio_pdf(cid: str, only_active: bool = Query(default=False)):
    """Versão pública (sem auth) pro app do colaborador baixar/imprimir."""
    company_id = await _company_for(cid)
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado.")
    q = {"company_id": company_id, "collaborator_id": cid}
    if only_active:
        q["status"] = "ativo"
    assets = await db.collaborator_assets.find(q, {"_id": 0}).sort(
        "delivered_at", 1).to_list(500)
    branding = (await get_branding(company_id)).model_dump()
    pdf = _build_romaneio_pdf(branding, coll, assets)
    fname = f"romaneio_{(coll.get('name') or cid).replace(' ', '_').lower()}.pdf"
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf",
                             headers={"Content-Disposition": f'inline; filename="{fname}"'})
