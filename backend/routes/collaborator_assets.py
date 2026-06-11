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


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import io
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role, fmt_br_dt
from database import db
from routes.branding import get_branding

logger = logging.getLogger("ponto.assets")
router = APIRouter(prefix="/api/collab-assets", tags=["collaborator_assets"])


async def _branding_with_praca(company_id: str, coll: dict) -> dict:
    """Mescla o branding global com os dados da praça (filial) do colaborador.
    A praça TEM PRIORIDADE sempre que tiver o campo cadastrado — assim o romaneio
    sai com a razão social/CNPJ/logo da filial e não da matriz.
    """
    branding = (await get_branding(company_id)).model_dump()
    praca_id = (coll or {}).get("praca_id")
    if not praca_id:
        return branding
    praca = await db.pracas.find_one({"id": praca_id}, {"_id": 0})
    if not praca:
        return branding
    if praca.get("name_business") or praca.get("name"):
        branding["company_name"] = praca.get("name_business") or praca.get("name")
    for k in ("cnpj", "inscricao_estadual", "phone", "email", "city", "state",
              "postal_code", "address", "full_address"):
        if praca.get(k):
            branding[k] = praca[k]
    # Compatibilidade: branding usa "zip_code"; praça usa "postal_code"
    if praca.get("postal_code"):
        branding["zip_code"] = praca["postal_code"]
    # Praça usa "full_address" para o endereço; substitui o da matriz quando existe
    if praca.get("full_address"):
        branding["address"] = praca["full_address"]
    # Site da praça (campo "site") → branding usa "website"
    if praca.get("site"):
        branding["website"] = praca["site"]
    # Logo: praça primeiro
    if praca.get("logo_url"):
        branding["logo_data_url"] = praca["logo_url"]
    return branding


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


class ReturnConfirmIn(BaseModel):
    """Pacote de devolução de itens — assinado pelo recebedor da empresa."""
    receiver_name: str = Field(..., min_length=2, max_length=120)
    receiver_role: Optional[str] = Field(default=None, max_length=80)
    signature_data_url: str = Field(..., min_length=30)  # data:image/png;base64,...
    notes: Optional[str] = Field(default=None, max_length=500)
    # Lista das chaves dos itens conferidos (origem `asset|ont|insumo` + id/serial).
    # Persistida no histórico para auditoria — não obrigatória para gerar PDF.
    confirmed_item_keys: Optional[List[str]] = None


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


@router.get("/custody-full/{cid}")
async def custody_full(cid: str,
                       user: dict = Depends(require_role("gestor"))):
    """Retorna TUDO em posse do colaborador (pertences ATIVOS + ONTs +
    insumos), normalizado para o modal de desativação. Usado para gerar
    a lista que vai virar o romaneio de devolução."""
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    coll = await db.collaborators.find_one(
        {"id": cid}, {"_id": 0, "name": 1, "role": 1})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado.")
    assets = await db.collaborator_assets.find(
        {"company_id": company_id, "collaborator_id": cid, "status": "ativo"},
        {"_id": 0},
    ).sort("delivered_at", 1).to_list(500)
    extras = await _collect_extra_custody(company_id, cid)
    total_value = sum(
        (a.get("unit_value_brl") or 0) * (a.get("qty") or 1)
        for a in assets if a.get("unit_value_brl") is not None
    )
    return {
        "collaborator": coll,
        "assets": assets,
        "extras": extras,
        "totals": {
            "assets_count": len(assets),
            "extras_count": len(extras),
            "value_brl": round(total_value, 2),
        },
    }


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
    """iter183 — BUG FIX: estava convertendo para UTC (mostrava 3h adiantado).
    Delega para `fmt_br_dt` global do core que converte para America/Sao_Paulo.
    """
    return fmt_br_dt(iso, "%d/%m/%Y %H:%M") if iso else "—"


async def _collect_extra_custody(company_id: str, collaborator_id: str) -> List[dict]:
    """Coleta TUDO em posse do técnico além dos collaborator_assets:
    - ONTs no estoque do técnico (`stok_onts` location_type=tecnico)
    - Insumos no estoque do técnico (`stok_stock` location=collaborator_id)

    Retorna lista de pseudo-assets normalizados (mesmas chaves que
    collaborator_assets) para alimentar o PDF de devolução.
    """
    items: List[dict] = []

    # ONTs em poder do técnico
    onts_cur = db.stok_onts.find(
        {"company_id": company_id,
         "location_type": "tecnico",
         "location_id": collaborator_id},
        {"_id": 0, "mac": 1, "model": 1, "status": 1, "created_at": 1,
         "source": 1, "scan_confidence": 1, "scan_sn": 1,
         "withdrawn_from_client_id": 1, "withdrawn_from_client_name": 1,
         "withdrawn_by_email": 1, "withdrawn_at": 1},
    )
    async for o in onts_cur:
        items.append({
            "category": "ont",
            "item": f"ONT {o.get('model') or 'GPON'}",
            "marca": o.get("model"),
            "modelo": None,
            "tamanho": None,
            "qty": 1,
            "serial": o.get("mac"),  # MAC = identificação única
            "mac": o.get("mac"),
            "source": o.get("source"),
            "scan_sn": o.get("scan_sn"),
            "scan_confidence": o.get("scan_confidence"),
            "withdrawn_from_client_id": o.get("withdrawn_from_client_id"),
            "withdrawn_from_client_name": o.get("withdrawn_from_client_name"),
            "withdrawn_by_email": o.get("withdrawn_by_email"),
            "withdrawn_at": o.get("withdrawn_at"),
            "delivered_at": o.get("created_at"),
            "status": o.get("status") or "ativo",
        })

    # Insumos no estoque do técnico
    stock_doc = await db.stok_stock.find_one(
        {"company_id": company_id, "location": collaborator_id},
        {"_id": 0},
    )
    if stock_doc:
        # Catálogo interno (mantido em rota stok); usamos labels resumidos
        consumable_labels = {
            "drop": ("Drop (cabo óptico)", "m"),
            "cabo_rede": ("Cabo de rede", "m"),
            "conector_fast": ("Conector fast", "un"),
            "conector_fibra": ("Conector de fibra", "un"),
            "esticador": ("Esticador", "un"),
            "conector_rede": ("Conector de rede", "un"),
        }
        for cid_key, (label, unit) in consumable_labels.items():
            qty = int(stock_doc.get(cid_key) or 0)
            if qty > 0:
                items.append({
                    "category": "insumo",
                    "item": f"{label}",
                    "marca": None,
                    "modelo": None,
                    "tamanho": unit,
                    "qty": qty,
                    "serial": None,
                    "delivered_at": None,
                    "status": "ativo",
                })

    return items


def _checkbox_drawing():
    """Retorna um Drawing flowable de checkbox vazio (square 14x14 px)."""
    from reportlab.graphics.shapes import Drawing, Rect
    from reportlab.lib import colors as _colors
    d = Drawing(14, 14)
    d.add(Rect(1, 1, 12, 12, strokeColor=_colors.HexColor("#0f172a"),
               fillColor=_colors.white, strokeWidth=1.2))
    return d


def _build_romaneio_pdf(branding: dict, collaborator: dict,
                         assets: List[dict],
                         mode: str = "delivery",
                         extra_items: Optional[List[dict]] = None,
                         receiver: Optional[dict] = None) -> bytes:
    """Gera o PDF do romaneio.

    mode="delivery" (padrão): TERMO DE RESPONSABILIDADE — colaborador recebe
    itens, assina como entregue.

    mode="return": TERMO DE DEVOLUÇÃO À EMPRESA — usado em desativação. Lista
    TUDO em posse do colaborador (pertences + ONTs em estoque do técnico +
    insumos). Cada linha tem checkbox `☐` para o recebedor tique conforme
    devolução é validada. Linha de assinatura é da empresa (recebedor), não
    do colaborador.

    `extra_items` — itens adicionais (ONTs/insumos) já normalizados como
    pseudo-assets para entrar na mesma tabela.
    `receiver` — quando preenchido (modo `return`), embute a assinatura
    digital do recebedor: `{name, role, signature_data_url, signed_at}`.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                     Table, TableStyle)

    is_return = mode == "return"
    all_assets = list(assets) + list(extra_items or [])

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.2 * cm,
                            title=("SmartProv — Romaneio de Devolução" if is_return
                                   else "SmartProv — Romaneio de Entrega"),
                            author="SmartProv", creator="SmartProv",
                            subject="Romaneio de Custódia de Bens")
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
    title_text = ("CHECKLIST DE DEVOLUÇÃO À EMPRESA — TERMO DE RECEBIMENTO"
                  if is_return
                  else "CHECKLIST DE CUSTÓDIA — TERMO DE RESPONSABILIDADE")
    title_color = colors.HexColor("#7f1d1d") if is_return else colors.HexColor("#0b1220")
    story.append(Paragraph(
        f"<b>{title_text}</b>",
        ParagraphStyle("title", parent=styles["Normal"], fontSize=13,
                       alignment=1, leading=16, spaceAfter=4,
                       textColor=title_color)))
    subtitle = ("Equipamentos · Uniforme · EPIs · Ferramental · ONTs · Insumos"
                if is_return
                else "Equipamentos · Uniforme · EPIs · Ferramental")
    story.append(Paragraph(
        f"<font color='#0d9488'>{subtitle}</font>",
        ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=9,
                       alignment=1, leading=12, spaceAfter=10)))
    story.append(Spacer(1, 0.2 * cm))

    # ---- Collaborator block ----
    issued_at = _pt_br_date(now_iso())
    label_data = "Data de devolução" if is_return else "Data de emissão"
    coll_html = (
        f"<b>Colaborador (devolvendo):</b> {collaborator.get('name', '—')}<br/>"
        if is_return else
        f"<b>Colaborador:</b> {collaborator.get('name', '—')}<br/>"
    )
    coll_html += (
        f"<b>Cargo:</b> {collaborator.get('role') or '—'} &nbsp;&nbsp; "
        f"<b>CPF:</b> {collaborator.get('cpf') or '—'}<br/>"
        f"<b>{label_data}:</b> {issued_at}"
    )
    story.append(Paragraph(coll_html,
                           ParagraphStyle("c", parent=styles["Normal"],
                                          fontSize=10, leading=14)))
    story.append(Spacer(1, 0.3 * cm))

    # ---- Items table ----
    if is_return:
        # Adiciona coluna de checkbox no modo devolução
        head = ["Devolvido", "#", "Categoria", "Item", "Marca / Modelo", "Tam.",
                "Qtd", "Série", "Entrega"]
        col_widths = [1.6 * cm, 0.7 * cm, 1.8 * cm, 4.2 * cm, 2.6 * cm,
                      1.0 * cm, 0.9 * cm, 2.4 * cm, 2.0 * cm]
    else:
        head = ["#", "Categoria", "Item", "Marca / Modelo", "Tam.", "Qtd",
                "Série", "Entrega", "Status"]
        col_widths = [0.8 * cm, 2 * cm, 4.6 * cm, 3 * cm, 1.2 * cm, 1 * cm,
                      2 * cm, 2.4 * cm, 1.6 * cm]
    data = [head]
    if not all_assets:
        if is_return:
            data.append(["—", "—", "—",
                         "Sem itens em posse — colaborador não tem custódia ativa.",
                         "—", "—", "—", "—", "—"])
        else:
            data.append(["—", "—", "Nenhum item em custódia para este colaborador.",
                         "—", "—", "—", "—", "—", "—"])
    for i, a in enumerate(all_assets, 1):
        marca_modelo = " / ".join([p for p in [a.get("marca"), a.get("modelo")] if p]) or "—"
        if is_return:
            data.append([
                _checkbox_drawing(),
                str(i),
                (a.get("category") or "—").upper(),
                a.get("item") or "—",
                marca_modelo,
                a.get("tamanho") or "—",
                str(a.get("qty") or 1),
                a.get("serial") or "—",
                _pt_br_date(a.get("delivered_at")),
            ])
        else:
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
    items_t = Table(data, repeatRows=1, colWidths=col_widths)
    table_style = [
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
    ]
    if is_return and all_assets:
        # Destaca a coluna de checkbox: drawing centralizado, fundo amarelinho
        table_style += [
            ("ALIGN", (0, 1), (0, -1), "CENTER"),
            ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#fef3c7")),
        ]
    items_t.setStyle(TableStyle(table_style))
    story.append(items_t)
    story.append(Spacer(1, 0.5 * cm))

    # ---- Footer / Termo ----
    if is_return:
        footer_text = (branding.get("romaneio_return_footer") or
                       "Declaro, na qualidade de representante da empresa, ter "
                       "RECEBIDO do colaborador acima identificado todos os "
                       "itens listados, devidamente conferidos e marcados como "
                       "devolvidos. A devolução encerra a responsabilidade do "
                       "colaborador sobre estes bens.")
        story.append(Paragraph(
            f"<b>TERMO DE RECEBIMENTO PELA EMPRESA:</b> {footer_text}",
            ParagraphStyle("foot", parent=styles["Normal"], fontSize=9,
                           leading=13, alignment=4)))  # 4 = justify
    else:
        footer_text = branding.get("romaneio_footer") or (
            "Declaro ter recebido os itens listados acima em perfeito estado e "
            "me responsabilizo por sua guarda, conservação e devolução em caso "
            "de desligamento, sob pena das medidas cabíveis.")
        story.append(Paragraph(
            f"<b>TERMO DE RESPONSABILIDADE:</b> {footer_text}",
            ParagraphStyle("foot", parent=styles["Normal"], fontSize=9,
                           leading=13, alignment=4)))
    story.append(Spacer(1, 1.4 * cm))

    # ---- Signature line(s) ----
    if is_return:
        # Modo devolução: 2 linhas de assinatura — colaborador (entregando)
        # e empresa (recebendo, embutida quando assinada digitalmente).
        from reportlab.platypus import Image as RLImage

        receiver_sig_flow = None
        receiver_name_label = (
            (receiver or {}).get("name") or branding.get("company_name") or "Empresa"
        )
        receiver_role_label = (
            (receiver or {}).get("role") or "Responsável pela empresa (recebendo)"
        )
        receiver_signed_at = _pt_br_date((receiver or {}).get("signed_at")) if receiver else None
        sig_url = (receiver or {}).get("signature_data_url") if receiver else None
        if sig_url and isinstance(sig_url, str) and sig_url.startswith("data:image/"):
            try:
                import base64
                b64 = sig_url.split(",", 1)[1]
                sig_io = io.BytesIO(base64.b64decode(b64))
                receiver_sig_flow = RLImage(sig_io, width=6 * cm, height=2 * cm,
                                            kind="proportional")
            except Exception as e:
                logger.warning("[romaneio] falha embutindo assinatura recebedor: %s", e)
                receiver_sig_flow = None

        sig_line = "_" * 50
        # Lado esquerdo: colaborador (linha em branco — assinatura física no momento da devolução)
        left_top = Paragraph(sig_line,
                             ParagraphStyle("sl", parent=styles["Normal"], alignment=1))
        left_bottom = Paragraph(
            f"<b>{collaborator.get('name', '—')}</b><br/>"
            f"<font size=8>Colaborador (entregando os itens)<br/>"
            f"CPF: {collaborator.get('cpf') or '—'}</font>",
            ParagraphStyle("sn", parent=styles["Normal"], fontSize=9,
                           alignment=1, leading=12))

        # Lado direito: empresa — embute imagem se houver, senão linha em branco
        right_top = receiver_sig_flow if receiver_sig_flow else Paragraph(
            sig_line, ParagraphStyle("sl", parent=styles["Normal"], alignment=1))
        signed_suffix = (
            f" · assinado em {receiver_signed_at}" if receiver_signed_at else ""
        )
        right_bottom = Paragraph(
            f"<b>{receiver_name_label}</b><br/>"
            f"<font size=8>{receiver_role_label}{signed_suffix}<br/>"
            f"{branding.get('company_name') or 'Empresa'}"
            f"{' · CNPJ ' + branding['cnpj'] if branding.get('cnpj') else ''}</font>",
            ParagraphStyle("sn", parent=styles["Normal"], fontSize=9,
                           alignment=1, leading=12))

        sig_table = Table(
            [[left_top, right_top], [left_bottom, right_bottom]],
            colWidths=[8.5 * cm, 8.5 * cm])
        sig_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 1), (-1, 1), 4),
        ]))
        story.append(sig_table)
    else:
        # Modo entrega: assinatura digital se houver, senão linha manual
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


@router.post("/return-confirm/{cid}")
async def return_confirm(cid: str, payload: ReturnConfirmIn,
                          user: dict = Depends(require_role("gestor"))):
    """Confirma a DEVOLUÇÃO do colaborador desativado:
    - Persiste histórico em `db.collab_returns` (auditoria)
    - Marca pertences (collaborator_assets) como `devolvido` com event log
    - Retorna o PDF do romaneio com a assinatura do recebedor embutida

    Não altera ONTs/insumos automaticamente — gestor decide na aba Estoque
    (return-to-company / consumable-transfer) pois envolve revalidação física.
    """
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado.")

    # Carrega snapshot de itens em posse no momento da devolução
    assets = await db.collaborator_assets.find(
        {"company_id": company_id, "collaborator_id": cid, "status": "ativo"},
        {"_id": 0},
    ).sort("delivered_at", 1).to_list(500)
    extras = await _collect_extra_custody(company_id, cid)

    receiver = {
        "name": payload.receiver_name.strip(),
        "role": (payload.receiver_role or "").strip() or "Responsável pela empresa",
        "signature_data_url": payload.signature_data_url,
        "signed_at": now_iso(),
    }

    # Persiste histórico (auditoria)
    return_id = f"return-{uuid.uuid4().hex[:10]}"
    await db.collab_returns.insert_one({
        "id": return_id,
        "company_id": company_id,
        "collaborator_id": cid,
        "collaborator_name": coll.get("name"),
        "receiver_name": receiver["name"],
        "receiver_role": receiver["role"],
        "receiver_signed_at": receiver["signed_at"],
        "signature_data_url": receiver["signature_data_url"],
        "confirmed_item_keys": payload.confirmed_item_keys or [],
        "asset_ids_snapshot": [a.get("id") for a in assets if a.get("id")],
        "extras_snapshot": [
            {"category": e.get("category"), "item": e.get("item"),
             "serial": e.get("serial"), "qty": e.get("qty")}
            for e in extras
        ],
        "notes": payload.notes,
        "issued_by": user.get("name") or user.get("email"),
        "issued_at": now_iso(),
    })

    # Marca pertences como devolvidos (apenas collaborator_assets, não ONTs/insumos)
    if assets:
        asset_ids = [a["id"] for a in assets if a.get("id")]
        if asset_ids:
            await db.collaborator_assets.update_many(
                {"company_id": company_id, "id": {"$in": asset_ids}},
                {"$set": {
                    "status": "devolvido",
                    "returned_at": now_iso(),
                    "returned_to": receiver["name"],
                    "return_id": return_id,
                }, "$push": {"events": {
                    "type": "devolucao",
                    "at": now_iso(),
                    "by": user.get("name") or user.get("email"),
                    "receiver": receiver["name"],
                    "return_id": return_id,
                }}},
            )

    # Gera PDF com assinatura embutida
    branding = await _branding_with_praca(company_id, coll)
    pdf = _build_romaneio_pdf(branding, coll, assets, mode="return",
                              extra_items=extras, receiver=receiver)
    fname = f"devolucao_{(coll.get('name') or cid).replace(' ', '_').lower()}_{return_id[-6:]}.pdf"
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf",
                             headers={
                                 "Content-Disposition": f'inline; filename="{fname}"',
                                 "X-Return-Id": return_id,
                             })


@router.get("/returns/{cid}")
async def list_returns(cid: str,
                        user: dict = Depends(require_role("gestor"))):
    """Lista histórico de devoluções de um colaborador (auditoria)."""
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    rows = await db.collab_returns.find(
        {"company_id": company_id, "collaborator_id": cid},
        {"_id": 0, "signature_data_url": 0},  # exclui blob da assinatura
    ).sort("issued_at", -1).to_list(100)
    return {"items": rows, "count": len(rows)}


@router.get("/romaneio/{cid}")
async def romaneio_pdf(cid: str,
                       only_active: bool = Query(default=False),
                       mode: str = Query(default="delivery", regex="^(delivery|return)$"),
                       user: dict = Depends(require_role("gestor"))):
    company_id = user.get("company_id") or DEMO_COMPANY_ID
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado.")
    q = {"company_id": company_id, "collaborator_id": cid}
    if only_active or mode == "return":
        q["status"] = "ativo"
    assets = await db.collaborator_assets.find(q, {"_id": 0}).sort(
        "delivered_at", 1).to_list(500)
    extra = (await _collect_extra_custody(company_id, cid)) if mode == "return" else None
    branding = await _branding_with_praca(company_id, coll)
    pdf = _build_romaneio_pdf(branding, coll, assets, mode=mode, extra_items=extra)
    suffix = "devolucao" if mode == "return" else "romaneio"
    fname = f"{suffix}_{(coll.get('name') or cid).replace(' ', '_').lower()}.pdf"
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf",
                             headers={"Content-Disposition": f'inline; filename="{fname}"'})


@router.get("/public/romaneio/{cid}")
async def public_romaneio_pdf(cid: str,
                              only_active: bool = Query(default=False),
                              mode: str = Query(default="delivery", regex="^(delivery|return)$")):
    """Versão pública (sem auth) pro app do colaborador baixar/imprimir."""
    company_id = await _company_for(cid)
    coll = await db.collaborators.find_one({"id": cid}, {"_id": 0})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado.")
    q = {"company_id": company_id, "collaborator_id": cid}
    if only_active or mode == "return":
        q["status"] = "ativo"
    assets = await db.collaborator_assets.find(q, {"_id": 0}).sort(
        "delivered_at", 1).to_list(500)
    extra = (await _collect_extra_custody(company_id, cid)) if mode == "return" else None
    branding = await _branding_with_praca(company_id, coll)
    pdf = _build_romaneio_pdf(branding, coll, assets, mode=mode, extra_items=extra)
    suffix = "devolucao" if mode == "return" else "romaneio"
    fname = f"{suffix}_{(coll.get('name') or cid).replace(' ', '_').lower()}.pdf"
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf",
                             headers={"Content-Disposition": f'inline; filename="{fname}"'})
