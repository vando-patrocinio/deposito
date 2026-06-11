"""Checklist Veicular Diário — Inspeção Pré-Jornada (CONTRAN/Frota).

Modelo (boas práticas — Resolução CONTRAN 14/98 + ALISAT/Cobli/TOTVS 2026):
- Inspeção realizada pelo motorista ANTES da jornada (5–10 min).
- Status por item: `ok` (conforme), `defeito` (não conforme — descreve), `na` (não aplicável).
- Categorias obrigatórias: Documentação, Pneus/Rodas, Iluminação, Freios/Direção,
  Fluidos/Combustível, Segurança, Externo/Interno, Motorista.
- Salva data, KM inicial/final, placa, motorista (collaborator_id), assinatura.
- Gera PDF profissional com tabela de itens, % de conformidade e assinatura.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "operacoes",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import io
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db
from routes.branding import get_branding

logger = logging.getLogger("ponto.vehicle_checklist")
router = APIRouter(prefix="/api/vehicle-checklist", tags=["vehicle_checklist"])


# ---------------------------------------------------------------------------
# Default items (template) — segue CONTRAN/boas práticas 2026
# ---------------------------------------------------------------------------
DEFAULT_TEMPLATE = [
    # Documentação
    {"cat": "Documentação", "name": "CRLV atualizado (digital ou físico)"},
    {"cat": "Documentação", "name": "CNH válida do motorista"},
    {"cat": "Documentação", "name": "Seguro / DPVAT vigente"},
    {"cat": "Documentação", "name": "IPVA / Licenciamento quitados"},
    # Pneus / Rodas
    {"cat": "Pneus e Rodas", "name": "Pressão dos pneus (conforme manual)"},
    {"cat": "Pneus e Rodas", "name": "Desgaste / sulcos ≥ 1,6 mm"},
    {"cat": "Pneus e Rodas", "name": "Sem cortes, bolhas ou objetos cravados"},
    {"cat": "Pneus e Rodas", "name": "Estepe + chave de roda + macaco"},
    # Iluminação
    {"cat": "Iluminação", "name": "Faróis (alto e baixo)"},
    {"cat": "Iluminação", "name": "Lanternas, luz de freio e ré"},
    {"cat": "Iluminação", "name": "Setas / piscas / pisca-alerta"},
    {"cat": "Iluminação", "name": "Iluminação da placa"},
    # Freios / Direção
    {"cat": "Freios e Direção", "name": "Pedal de freio firme (sem afundamento)"},
    {"cat": "Freios e Direção", "name": "Freio de mão segurando"},
    {"cat": "Freios e Direção", "name": "Volante sem folgas anormais"},
    # Fluidos / Combustível
    {"cat": "Fluidos", "name": "Óleo do motor (nível)"},
    {"cat": "Fluidos", "name": "Água do radiador / arrefecimento"},
    {"cat": "Fluidos", "name": "Fluido de freio"},
    {"cat": "Fluidos", "name": "Reservatório do limpa-vidros"},
    {"cat": "Fluidos", "name": "Combustível suficiente para a rota"},
    # Segurança
    {"cat": "Segurança", "name": "Extintor com validade vigente"},
    {"cat": "Segurança", "name": "Triângulo de sinalização"},
    {"cat": "Segurança", "name": "Cintos de segurança funcionando"},
    {"cat": "Segurança", "name": "Buzina"},
    # Externo / Interno
    {"cat": "Externo/Interno", "name": "Vidros e retrovisores intactos"},
    {"cat": "Externo/Interno", "name": "Lataria / portas sem avarias novas"},
    {"cat": "Externo/Interno", "name": "Bancos e estofados em ordem"},
    {"cat": "Externo/Interno", "name": "Bateria sem vazamentos / sulfatação"},
    # Motorista
    {"cat": "Motorista", "name": "Motorista descansado, sem indícios de fadiga"},
    {"cat": "Motorista", "name": "EPI / colete / vestimenta adequada"},
]

ITEM_STATUSES = ["ok", "defeito", "na"]


class ChecklistItem(BaseModel):
    cat: str
    name: str
    status: Literal["ok", "defeito", "na"] = "ok"
    notes: Optional[str] = None


class DamageMark(BaseModel):
    """Avaria marcada na silhueta do veículo.

    view: front|rear|left|right|top — qual silhueta foi clicada.
    x, y: coordenadas no viewBox 0..200 × 0..110 (frontend usa o mesmo).
    code: D=amassado, S=risco, R=oxidação, F=quebrado, V=vidro, P=pintura.
    ord: número de ordem (visual numbering 1..N) preservado entre frontend/PDF.
    """
    view: Literal["front", "rear", "left", "right", "top"]
    x: float = Field(..., ge=0, le=200)
    y: float = Field(..., ge=0, le=110)
    code: Literal["D", "S", "R", "F", "V", "P"] = "D"
    ord: int = Field(..., ge=1, le=999)
    notes: Optional[str] = None


class Attachment(BaseModel):
    """Anexo (foto/papel scaneado). Armazena base64 inline (limite ~8MB)."""
    kind: Literal["photo", "paper_checklist", "doc"] = "photo"
    label: Optional[str] = None
    data_url: str  # data:image/...;base64,...
    uploaded_at: Optional[str] = None


class ChecklistIn(BaseModel):
    collaborator_id: str = Field(..., min_length=1)
    plate: str = Field(..., min_length=4, max_length=10)
    vehicle_brand: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_year: Optional[int] = None
    km_initial: Optional[float] = Field(default=None, ge=0)
    km_final: Optional[float] = Field(default=None, ge=0)
    route: Optional[str] = None
    items: List[ChecklistItem]
    damage_marks: List[DamageMark] = Field(default_factory=list)
    attachments: List[Attachment] = Field(default_factory=list)
    general_notes: Optional[str] = None
    signature_data_url: Optional[str] = None


class ChecklistUpdate(BaseModel):
    km_final: Optional[float] = Field(default=None, ge=0)
    items: Optional[List[ChecklistItem]] = None
    damage_marks: Optional[List[DamageMark]] = None
    attachments: Optional[List[Attachment]] = None
    general_notes: Optional[str] = None
    signature_data_url: Optional[str] = None


class AttachmentIn(BaseModel):
    """Upload simples de uma única foto/anexo a um checklist existente."""
    kind: Literal["photo", "paper_checklist", "doc"] = "photo"
    label: Optional[str] = None
    data_url: str = Field(..., min_length=20)


def _company_for(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


def _conformity(items: List[dict]) -> dict:
    """Calcula % de conformidade. Itens NA são excluídos do denominador."""
    total = sum(1 for it in items if it.get("status") != "na")
    ok = sum(1 for it in items if it.get("status") == "ok")
    defects = sum(1 for it in items if it.get("status") == "defeito")
    pct = round(100.0 * ok / total, 1) if total > 0 else 100.0
    return {"total": total, "ok": ok, "defeitos": defects, "pct": pct}


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.get("/template")
async def get_template():
    """Devolve o template padrão de itens de inspeção."""
    return {"items": DEFAULT_TEMPLATE}


@router.post("")
async def create_checklist(payload: ChecklistIn,
                           user: dict = Depends(require_role("colaborador"))):
    cid = _company_for(user)
    coll = await db.collaborators.find_one(
        {"id": payload.collaborator_id, "company_id": cid}, {"_id": 0, "name": 1, "cpf": 1, "role": 1})
    if not coll:
        raise HTTPException(404, "Colaborador não encontrado.")

    items = [it.model_dump() for it in payload.items]
    conf = _conformity(items)
    now = now_iso()
    marks = [m.model_dump() for m in payload.damage_marks]
    atts = [{**a.model_dump(), "uploaded_at": a.uploaded_at or now} for a in payload.attachments]
    doc = {
        "id": f"vchk-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "collaborator_id": payload.collaborator_id,
        "collaborator_name_snapshot": coll.get("name"),
        "plate": payload.plate.upper().strip(),
        "vehicle_brand": payload.vehicle_brand,
        "vehicle_model": payload.vehicle_model,
        "vehicle_year": payload.vehicle_year,
        "km_initial": payload.km_initial,
        "km_final": payload.km_final,
        "route": payload.route,
        "items": items,
        "damage_marks": marks,
        "attachments": atts,
        "general_notes": payload.general_notes,
        "signature_data_url": payload.signature_data_url,
        "conformity": conf,
        "created_at": now,
        "created_by": user.get("email"),
    }
    await db.vehicle_checklists.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("")
async def list_checklists(collaborator_id: Optional[str] = None,
                          plate: Optional[str] = None,
                          limit: int = 50,
                          user: dict = Depends(require_role("gestor"))):
    cid = _company_for(user)
    q = {"company_id": cid}
    if collaborator_id:
        q["collaborator_id"] = collaborator_id
    if plate:
        q["plate"] = plate.upper().strip()
    rows = await db.vehicle_checklists.find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(min(max(limit, 1), 500))
    return {"items": rows, "total": len(rows)}


@router.get("/{chk_id}")
async def get_checklist(chk_id: str,
                        user: dict = Depends(require_role("gestor"))):
    cid = _company_for(user)
    doc = await db.vehicle_checklists.find_one(
        {"id": chk_id, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Checklist não encontrado.")
    return doc


@router.patch("/{chk_id}")
async def update_checklist(chk_id: str, payload: ChecklistUpdate,
                           user: dict = Depends(require_role("gestor"))):
    cid = _company_for(user)
    doc = await db.vehicle_checklists.find_one(
        {"id": chk_id, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Checklist não encontrado.")
    upd = {}
    if payload.km_final is not None:
        upd["km_final"] = payload.km_final
    if payload.items is not None:
        upd["items"] = [it.model_dump() for it in payload.items]
        upd["conformity"] = _conformity(upd["items"])
    if payload.damage_marks is not None:
        upd["damage_marks"] = [m.model_dump() for m in payload.damage_marks]
    if payload.attachments is not None:
        upd["attachments"] = [a.model_dump() for a in payload.attachments]
    if payload.general_notes is not None:
        upd["general_notes"] = payload.general_notes
    if payload.signature_data_url is not None:
        upd["signature_data_url"] = payload.signature_data_url
    upd["updated_at"] = now_iso()
    await db.vehicle_checklists.update_one(
        {"id": chk_id, "company_id": cid}, {"$set": upd})
    new = await db.vehicle_checklists.find_one(
        {"id": chk_id, "company_id": cid}, {"_id": 0})
    return new


@router.delete("/{chk_id}")
async def delete_checklist(chk_id: str,
                           user: dict = Depends(require_role("auditor"))):
    cid = _company_for(user)
    res = await db.vehicle_checklists.delete_one(
        {"id": chk_id, "company_id": cid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Checklist não encontrado.")
    return {"ok": True}


@router.post("/{chk_id}/attachment")
async def add_attachment(chk_id: str, payload: AttachmentIn,
                         user: dict = Depends(require_role("colaborador"))):
    """Adiciona um anexo (foto do checklist em papel, foto da avaria, etc)
    a um checklist existente. Append no array `attachments`."""
    cid = _company_for(user)
    doc = await db.vehicle_checklists.find_one(
        {"id": chk_id, "company_id": cid}, {"_id": 0, "id": 1})
    if not doc:
        raise HTTPException(404, "Checklist não encontrado.")
    # Sanity: tamanho razoável (~10MB base64 ≈ 7.5MB raw)
    if len(payload.data_url) > 11_000_000:
        raise HTTPException(413, "Arquivo muito grande (máx ~8MB).")
    att = payload.model_dump()
    att["uploaded_at"] = now_iso()
    att["uploaded_by"] = user.get("email")
    await db.vehicle_checklists.update_one(
        {"id": chk_id, "company_id": cid},
        {"$push": {"attachments": att}})
    return {"ok": True, "attachment": att}


@router.delete("/{chk_id}/attachment/{idx}")
async def remove_attachment(chk_id: str, idx: int,
                            user: dict = Depends(require_role("gestor"))):
    """Remove anexo por índice (ordem do array)."""
    cid = _company_for(user)
    doc = await db.vehicle_checklists.find_one(
        {"id": chk_id, "company_id": cid}, {"_id": 0, "attachments": 1})
    if not doc:
        raise HTTPException(404, "Checklist não encontrado.")
    atts = doc.get("attachments") or []
    if idx < 0 or idx >= len(atts):
        raise HTTPException(404, "Anexo não encontrado.")
    new_atts = [a for i, a in enumerate(atts) if i != idx]
    await db.vehicle_checklists.update_one(
        {"id": chk_id, "company_id": cid},
        {"$set": {"attachments": new_atts}})
    return {"ok": True, "remaining": len(new_atts)}


# ---------------------------------------------------------------------------
# IA Preventiva — Defeitos recorrentes (frota)
# ---------------------------------------------------------------------------
@router.get("/insights/recurrent-defects")
async def recurrent_defects(days: int = 30, min_count: int = 3,
                            user: dict = Depends(require_role("gestor"))):
    """Identifica veículos+itens com defeitos recorrentes nos últimos N dias.

    Aciona o gestor quando um item aparece como `defeito` ≥ `min_count` vezes
    no mesmo veículo em N dias — sinal forte de manutenção pendente.
    """
    cid = _company_for(user)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cur = db.vehicle_checklists.find(
        {"company_id": cid, "created_at": {"$gte": cutoff}},
        {"_id": 0, "plate": 1, "items": 1, "created_at": 1, "vehicle_brand": 1,
         "vehicle_model": 1, "collaborator_name_snapshot": 1, "id": 1})
    grouped: dict = {}  # (plate, item_name) -> {count, last_at, notes[], chk_ids[]}
    plates_seen: dict = {}
    async for d in cur:
        plate = d.get("plate") or "?"
        plates_seen[plate] = {
            "vehicle": " ".join([p for p in [d.get("vehicle_brand"), d.get("vehicle_model")] if p]) or None,
            "last_driver": d.get("collaborator_name_snapshot"),
        }
        for it in d.get("items") or []:
            if it.get("status") != "defeito":
                continue
            key = (plate, it.get("name") or "—")
            entry = grouped.setdefault(key, {
                "plate": plate, "item": it.get("name") or "—",
                "category": it.get("cat"), "count": 0,
                "last_at": d.get("created_at"), "notes": [],
                "chk_ids": [],
            })
            entry["count"] += 1
            if d.get("created_at") and (entry["last_at"] is None or d["created_at"] > entry["last_at"]):
                entry["last_at"] = d["created_at"]
            if it.get("notes"):
                entry["notes"].append(it["notes"])
            entry["chk_ids"].append(d.get("id"))
    alerts = []
    for entry in grouped.values():
        if entry["count"] >= min_count:
            entry["vehicle_info"] = plates_seen.get(entry["plate"], {})
            alerts.append(entry)
    alerts.sort(key=lambda x: (-x["count"], x["plate"]))
    return {"period_days": days, "min_count": min_count,
            "alerts": alerts, "total": len(alerts)}


# ---------------------------------------------------------------------------
# PDF (Romaneio de Inspeção Veicular)
# ---------------------------------------------------------------------------
@router.get("/{chk_id}/pdf")
async def checklist_pdf(chk_id: str,
                        user: dict = Depends(require_role("gestor"))):
    cid = _company_for(user)
    doc = await db.vehicle_checklists.find_one(
        {"id": chk_id, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Checklist não encontrado.")
    coll = await db.collaborators.find_one(
        {"id": doc["collaborator_id"]}, {"_id": 0}) or {}
    branding = (await get_branding(cid)).model_dump()
    pdf = _build_vehicle_pdf(branding, coll, doc)
    fname = f"checklist_veicular_{doc['plate']}_{doc['created_at'][:10]}.pdf"
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf",
                             headers={"Content-Disposition": f'inline; filename="{fname}"'})


def _build_vehicle_pdf(branding: dict, collaborator: dict, doc: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (Image, PageBreak, Paragraph,
                                     SimpleDocTemplate, Spacer, Table,
                                     TableStyle)

    SLATE = colors.HexColor("#0b1220")
    SLATE_SOFT = colors.HexColor("#475569")
    BORDER = colors.HexColor("#d4d7df")
    BG_ROW = colors.HexColor("#f6f7f9")
    TEAL = colors.HexColor("#0d9488")
    OK = colors.HexColor("#15803d")
    DEF = colors.HexColor("#b91c1c")
    NA = colors.HexColor("#94a3b8")

    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=1.4 * cm, rightMargin=1.4 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.2 * cm,
                            title=f"Checklist Veicular {doc.get('plate', '')}")
    styles = getSampleStyleSheet()
    story: list = []

    # ---- Cabeçalho ----
    logo_url = (branding or {}).get("logo_data_url") or ""
    header_left = Paragraph("", styles["Normal"])
    if logo_url and logo_url.startswith("data:image/"):
        try:
            import base64
            b64 = logo_url.split(",", 1)[1]
            header_left = Image(io.BytesIO(base64.b64decode(b64)),
                                width=2.8 * cm, height=2.8 * cm,
                                kind="proportional")
        except Exception:
            pass

    company_lines = [f"<b>{branding.get('company_name') or 'Empresa'}</b>"]
    if branding.get("cnpj"):
        company_lines.append(f"CNPJ: {branding['cnpj']}")
    addr_parts = [branding.get("address"), branding.get("city"),
                  branding.get("state"), branding.get("zip_code")]
    addr = " · ".join([p for p in addr_parts if p])
    if addr:
        company_lines.append(addr)
    company_par = Paragraph("<br/>".join(company_lines),
                            ParagraphStyle("c", parent=styles["Normal"],
                                           fontSize=9, leading=12, textColor=SLATE_SOFT))

    title_par = Paragraph(
        '<font color="#0b1220" size="13"><b>CHECKLIST VEICULAR</b></font>'
        '<br/><font color="#0d9488" size="9"><b>INSPEÇÃO PRÉ-JORNADA · CONTRAN</b></font>',
        ParagraphStyle("t", parent=styles["Normal"], leading=15, alignment=2))

    header_table = Table([[header_left, company_par, title_par]],
                         colWidths=[3 * cm, None, 5 * cm])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.15 * cm))
    story.append(Table([[""]], colWidths=[18 * cm], rowHeights=[2],
                       style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), SLATE)])))
    story.append(Spacer(1, 0.4 * cm))

    # ---- Bloco de identificação ----
    issued = _br_date(doc.get("created_at"))
    plate = doc.get("plate") or "—"
    veh = " ".join([p for p in [doc.get("vehicle_brand"), doc.get("vehicle_model")] if p]) or "—"
    if doc.get("vehicle_year"):
        veh = f"{veh} · {doc['vehicle_year']}"
    km_i = _fmt_km(doc.get("km_initial"))
    km_f = _fmt_km(doc.get("km_final"))
    info_data = [
        ["Motorista", collaborator.get("name", "—"),
         "CPF", collaborator.get("cpf") or "—"],
        ["Placa", plate, "Veículo", veh],
        ["KM inicial", km_i, "KM final", km_f],
        ["Data / hora", issued, "Rota", doc.get("route") or "—"],
    ]
    info_t = Table(info_data, colWidths=[2.6 * cm, 5.4 * cm, 2.6 * cm, 5.4 * cm])
    info_t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (0, -1), BG_ROW),
        ("BACKGROUND", (2, 0), (2, -1), BG_ROW),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), SLATE_SOFT),
        ("TEXTCOLOR", (2, 0), (2, -1), SLATE_SOFT),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
    ]))
    story.append(info_t)
    story.append(Spacer(1, 0.5 * cm))

    # ---- Conformidade ----
    c = doc.get("conformity") or _conformity(doc.get("items") or [])
    pct = c.get("pct", 100.0)
    pct_color = OK if pct >= 95 else (colors.HexColor("#d97706") if pct >= 80 else DEF)
    conf_par = Paragraph(
        f'<font size="11" color="#475569">Conformidade geral:</font> '
        f'<font size="14" color="{pct_color.hexval()}"><b>{pct}%</b></font> '
        f'<font size="9" color="#94a3b8">({c.get("ok",0)} OK / {c.get("defeitos",0)} defeito(s) / '
        f'{c.get("total",0)} aplicáveis)</font>',
        ParagraphStyle("conf", parent=styles["Normal"], leading=18))
    story.append(conf_par)
    story.append(Spacer(1, 0.3 * cm))

    # ---- Tabela de itens (agrupada por categoria) ----
    items = doc.get("items") or []
    cats: dict = {}
    for it in items:
        cats.setdefault(it.get("cat", "—"), []).append(it)

    tbl_data = [["#", "Item", "Status", "Observações"]]
    row_styles = []  # [(row_idx, color)]
    idx = 0
    for cat, lst in cats.items():
        idx += 1
        # cabeçalho de categoria
        tbl_data.append([cat.upper(), "", "", ""])
        cat_row = len(tbl_data) - 1
        row_styles.append((cat_row, "category"))
        for it in lst:
            idx += 1
            stat = (it.get("status") or "ok").upper()
            tbl_data.append([
                str(idx - 1),
                it.get("name") or "—",
                stat,
                (it.get("notes") or "—")[:120],
            ])
            data_row = len(tbl_data) - 1
            row_styles.append((data_row, it.get("status") or "ok"))

    items_t = Table(tbl_data, repeatRows=1,
                    colWidths=[0.9 * cm, 9.5 * cm, 2.2 * cm, 5.4 * cm])
    base_style = [
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), SLATE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (2, 0), (2, 0), "CENTER"),
        # Body defaults
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ALIGN", (2, 1), (2, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, BORDER),
    ]
    for row_idx, kind in row_styles:
        if kind == "category":
            base_style += [
                ("SPAN", (0, row_idx), (-1, row_idx)),
                ("BACKGROUND", (0, row_idx), (-1, row_idx), TEAL),
                ("TEXTCOLOR", (0, row_idx), (-1, row_idx), colors.white),
                ("FONTNAME", (0, row_idx), (-1, row_idx), "Helvetica-Bold"),
                ("FONTSIZE", (0, row_idx), (-1, row_idx), 9),
                ("ALIGN", (0, row_idx), (-1, row_idx), "LEFT"),
                ("LEFTPADDING", (0, row_idx), (-1, row_idx), 8),
                ("TOPPADDING", (0, row_idx), (-1, row_idx), 5),
                ("BOTTOMPADDING", (0, row_idx), (-1, row_idx), 5),
            ]
        else:
            color = OK if kind == "ok" else (DEF if kind == "defeito" else NA)
            base_style += [("TEXTCOLOR", (2, row_idx), (2, row_idx), color),
                           ("FONTNAME", (2, row_idx), (2, row_idx), "Helvetica-Bold")]
    items_t.setStyle(TableStyle(base_style))
    story.append(items_t)
    story.append(Spacer(1, 0.5 * cm))

    # ---- Observações ----
    if doc.get("general_notes"):
        story.append(Paragraph(
            f'<b>Observações:</b> {doc["general_notes"]}',
            ParagraphStyle("notes", parent=styles["Normal"], fontSize=9, leading=12)))
        story.append(Spacer(1, 0.4 * cm))

    # ---- Termo / Assinatura ----
    termo = (
        "Declaro ter realizado a inspeção dos itens listados acima neste veículo, "
        "estando ciente das responsabilidades legais (Resolução CONTRAN 14/98 e "
        "demais normas de trânsito) sobre eventuais omissões. Defeitos identificados "
        "foram comunicados ao gestor de frota para ações corretivas.")
    story.append(Paragraph(
        f'<font color="#475569"><b>TERMO DE RESPONSABILIDADE:</b></font> '
        f'<font color="#475569">{termo}</font>',
        ParagraphStyle("foot", parent=styles["Normal"], fontSize=8.5,
                       leading=12, alignment=4)))
    story.append(Spacer(1, 1.2 * cm))

    # Assinatura
    sig_url = doc.get("signature_data_url")
    if sig_url:
        try:
            import base64
            b64 = sig_url.split(",", 1)[1]
            sig_img = Image(io.BytesIO(base64.b64decode(b64)),
                            width=6 * cm, height=2 * cm, kind="proportional")
            story.append(Table([[sig_img], ["_" * 50],
                                [f"{collaborator.get('name', '—')} — {issued}"]],
                               colWidths=[10 * cm],
                               style=TableStyle([
                                   ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                   ("FONTSIZE", (0, 0), (-1, -1), 9),
                               ])))
        except Exception:
            sig_url = None
    if not sig_url:
        story.append(Paragraph("_" * 60,
                               ParagraphStyle("s", parent=styles["Normal"], alignment=1)))
        story.append(Paragraph(
            f"{collaborator.get('name', '—')} — Motorista (assinatura)",
            ParagraphStyle("s2", parent=styles["Normal"], fontSize=9, alignment=1, spaceBefore=2)))

    # ---- Página de avarias + anexos (se houver)
    _build_damage_pages(story, doc, cm, styles, ParagraphStyle, Paragraph,
                         Spacer, Table, TableStyle, PageBreak, Image)

    pdf.build(story)
    buf.seek(0)
    return buf.getvalue()


def _build_damage_pages(story: list, doc: dict, cm, styles, ParagraphStyle,
                         Paragraph, Spacer, Table, TableStyle, PageBreak,
                         Image_cls):
    """Adiciona página(s) com silhuetas marcadas + anexos."""
    from reportlab.lib import colors
    from routes.vehicle_silhouettes import (DAMAGE_COLORS, VIEW_LABELS,
                                              silhouette_drawing)

    marks = doc.get("damage_marks") or []
    atts = doc.get("attachments") or []
    if not marks and not atts:
        return

    SLATE = colors.HexColor("#0b1220")
    BORDER = colors.HexColor("#d4d7df")

    story.append(PageBreak())
    story.append(Paragraph(
        '<font color="#0b1220" size="13"><b>DIAGRAMA DE AVARIAS</b></font>',
        ParagraphStyle("dt", parent=styles["Normal"], leading=15, spaceAfter=4)))
    story.append(Paragraph(
        '<font color="#0d9488" size="9"><b>Vistas Frente · Traseira · Laterais · Superior</b></font>',
        ParagraphStyle("dst", parent=styles["Normal"], leading=12, spaceAfter=12)))

    if marks:
        # Grid 2x3 (5 vistas + legenda) — silhuetas com 7.5cm × 4cm
        sw, sh = 7.5 * cm, 4.2 * cm

        def cell(view: str):
            d = silhouette_drawing(view, marks, sw - 0.4 * cm, sh - 0.7 * cm)
            label = VIEW_LABELS.get(view, view)
            count = sum(1 for m in marks if m.get("view") == view)
            badge = f' <font color="#dc2626"><b>· {count} avaria(s)</b></font>' if count else ""
            cap = Paragraph(
                f'<font size="9" color="#0b1220"><b>{label}</b></font>{badge}',
                ParagraphStyle("c", parent=styles["Normal"], leading=11,
                               alignment=1, spaceAfter=2))
            inner = Table([[cap], [d]], colWidths=[sw - 0.4 * cm])
            inner.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]))
            return inner

        # Build legend cell (6º slot da grade)
        from reportlab.lib import colors as _c
        legend_data = [
            ["Cód.", "Tipo de avaria"],
            ["D", "Amassado"],
            ["S", "Risco"],
            ["R", "Oxidação"],
            ["F", "Quebrado"],
            ["V", "Vidro"],
            ["P", "Pintura"],
        ]
        legend_t = Table(legend_data, colWidths=[1.5 * cm, 4.5 * cm])
        legend_t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), SLATE),
            ("TEXTCOLOR", (0, 0), (-1, 0), _c.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        legend_wrap = Table([["Legenda"], [legend_t]],
                            colWidths=[sw - 0.4 * cm])
        legend_wrap.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ]))

        grid = Table([
            [cell("front"), cell("rear")],
            [cell("left"), cell("right")],
            [cell("top"), legend_wrap],
        ], colWidths=[sw, sw], rowHeights=[sh, sh, sh])
        grid.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f6f7f9")),
        ]))
        story.append(grid)
        story.append(Spacer(1, 0.4 * cm))

        # Legenda + tabela detalhada
        legend = (
            '<b>D</b>=Amassado &nbsp; <b>S</b>=Risco &nbsp; <b>R</b>=Oxidação '
            '&nbsp; <b>F</b>=Quebrado &nbsp; <b>V</b>=Vidro &nbsp; <b>P</b>=Pintura'
        )
        story.append(Paragraph(
            f'<font size="8.5" color="#475569">{legend}</font>',
            ParagraphStyle("lg", parent=styles["Normal"], leading=11, spaceAfter=8)))

        # Tabela detalhada numerada
        tbl = [["#", "Vista", "Tipo", "Descrição"]]
        for m in sorted(marks, key=lambda x: x.get("ord", 0)):
            from routes.vehicle_silhouettes import VIEW_LABELS as VL
            tbl.append([
                str(m.get("ord", "?")),
                VL.get(m.get("view"), m.get("view") or "—"),
                m.get("code") or "D",
                (m.get("notes") or "—")[:140],
            ])
        det = Table(tbl, repeatRows=1,
                     colWidths=[1 * cm, 4 * cm, 1.6 * cm, 11.4 * cm])
        det.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), SLATE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ALIGN", (0, 0), (2, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(det)

    # ---- Anexos (fotos)
    if atts:
        story.append(Spacer(1, 0.6 * cm))
        story.append(Paragraph(
            '<font color="#0b1220" size="11"><b>ANEXOS</b></font>',
            ParagraphStyle("ah", parent=styles["Normal"], leading=14, spaceAfter=4)))
        story.append(Paragraph(
            f'<font color="#475569" size="9">{len(atts)} arquivo(s) anexado(s) — '
            'fotos do checklist preenchido em papel ou registros de avarias.</font>',
            ParagraphStyle("at", parent=styles["Normal"], leading=12, spaceAfter=8)))

        for i, att in enumerate(atts, 1):
            data_url = att.get("data_url") or ""
            if not data_url.startswith("data:image/"):
                continue
            try:
                import base64
                b64 = data_url.split(",", 1)[1]
                raw = base64.b64decode(b64)
                # Validate image actually decodes before passing to ReportLab
                from PIL import Image as PILImage
                pil = PILImage.open(io.BytesIO(raw))
                pil.verify()
                # Re-open for actual use (verify closes the file)
                buf2 = io.BytesIO(raw)
                img = Image_cls(buf2, width=14 * cm, height=10 * cm, kind="proportional")
                cap = Paragraph(
                    f'<font size="9" color="#475569">Anexo #{i}'
                    f'{" — " + att.get("label", "") if att.get("label") else ""}'
                    f' · {att.get("kind", "photo")}</font>',
                    ParagraphStyle("ac", parent=styles["Normal"], leading=12,
                                   alignment=1, spaceAfter=4))
                story.append(cap)
                story.append(img)
                story.append(Spacer(1, 0.4 * cm))
            except Exception as e:
                logger.warning("[vchk-pdf] anexo %d falhou (ignorado): %s", i, e)
                story.append(Paragraph(
                    f'<font size="9" color="#94a3b8">Anexo #{i}'
                    f'{" — " + att.get("label", "") if att.get("label") else ""}'
                    f' (imagem inválida — não pôde ser renderizada)</font>',
                    ParagraphStyle("ax", parent=styles["Normal"], leading=12,
                                   alignment=1, spaceAfter=4)))


def _br_date(iso: Optional[str]) -> str:
    # iter183 — usa helper global pra converter UTC → America/Sao_Paulo
    from core import fmt_br_dt
    return fmt_br_dt(iso, "%d/%m/%Y %H:%M") if iso else "—"


def _fmt_km(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{int(v):,} km".replace(",", ".")
    except Exception:
        return f"{v} km"
