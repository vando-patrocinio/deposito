"""Romaneio de orçamento — PDF imprimível.

Reaproveita o cabeçalho oficial do **romaneio de pertences**
(`routes/collaborator_assets._build_romaneio_pdf`): logo da empresa
(branding.logo_data_url) + nome + CNPJ + endereço + contato.

Layout A4 retrato:
  1. Header com logo + dados da empresa (vindo de `company_branding`)
  2. Título "ORÇAMENTO — Nº xxx" (centrado)
  3. Metadados (nome do orçamento, descrição, criado por, data)
  4. Tabela de itens (Item · Qtde · Unid · Preço unit. · Subtotal · Fonte IA · Confiança)
  5. Totais (base · ganho · mão-de-obra · subtotal · imposto · final)
  6. Nota da IA + assinaturas
"""
from __future__ import annotations

import base64
import io
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

logger = logging.getLogger("ponto.budget_pdf")


def _money_br(v: float) -> str:
    try:
        s = f"{float(v or 0):,.2f}"
        return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "R$ 0,00"


def _build_header_block(branding: dict, styles) -> Table:
    """Replica EXATAMENTE o cabeçalho do romaneio de pertences
    (`collaborator_assets._build_romaneio_pdf`): coluna 1 = logo
    (3.5cm × 3.5cm) ou texto LOGO; coluna 2 = dados da empresa em
    fontSize=10 leading=13.
    """
    logo_url = (branding or {}).get("logo_data_url") or ""
    header_left: Any
    if logo_url and logo_url.startswith("data:image/"):
        try:
            b64 = logo_url.split(",", 1)[1]
            img_bytes = base64.b64decode(b64)
            logo_io = io.BytesIO(img_bytes)
            header_left = Image(logo_io, width=3.5 * cm, height=3.5 * cm,
                                 kind="proportional")
        except Exception as e:
            logger.warning("[budget-pdf] logo decode falhou: %s", e)
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
    company_par = Paragraph(
        "<br/>".join(company_lines),
        ParagraphStyle("c", parent=styles["Normal"], fontSize=10, leading=13),
    )
    header_table = Table([[header_left, company_par]], colWidths=[4 * cm, None])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "LEFT"),
    ]))
    return header_table


def build_budget_pdf(budget: Dict[str, Any], generated_by: str = "",
                       branding: Optional[Dict[str, Any]] = None) -> bytes:
    """Gera PDF do orçamento como bytes.

    Args:
        budget: doc do orçamento já hidratado com totals.
        generated_by: nome do usuário que solicitou o PDF.
        branding: company_branding (logo, nome, CNPJ, endereço, contato).
                    Se None, usa placeholder "LOGO" + nome "Empresa".
    """
    branding = branding or {}
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.2 * cm, bottomMargin=1.2 * cm,
        title=f"SmartProv — Orçamento {budget.get('name', '')}",
        author="SmartProv", creator="SmartProv",
        subject="Orçamento de Materiais",
    )

    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9, leading=11)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=7.5,
                              leading=9, textColor=colors.HexColor("#64748b"))

    story = []

    # ---- 1. Header (logo + dados da empresa) — mesmo do romaneio ----
    story.append(_build_header_block(branding, styles))
    story.append(Spacer(1, 0.4 * cm))

    # ---- 2. Título centralizado ----
    title_text = "ORÇAMENTO DE MATERIAIS"
    story.append(Paragraph(
        f"<b>{title_text}</b>",
        ParagraphStyle("title", parent=styles["Normal"], fontSize=13,
                          alignment=1, leading=16, spaceAfter=4,
                          textColor=colors.HexColor("#0b1220")),
    ))
    # Subtítulo com nome do orçamento
    story.append(Paragraph(
        f"<b>{budget.get('name', '—')}</b>",
        ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=11,
                          alignment=1, leading=14, spaceAfter=8,
                          textColor=colors.HexColor("#475569")),
    ))

    # ---- 3. Metadados (apenas o essencial: descrição + data) ----
    meta_data = []
    if budget.get("description"):
        meta_data.append(["Descrição", budget["description"]])
    meta_data.append(["Data de emissão", datetime.now().strftime("%d/%m/%Y %H:%M")])
    meta_tbl = Table(meta_data, colWidths=[4 * cm, None])
    meta_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#475569")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 0.5 * cm))

    # ---- 4. Tabela de itens ----
    items = budget.get("items") or []
    head = ["#", "Item", "Qtde", "Unid", "Preço unit.", "Subtotal",
             "Fonte / Confiança"]
    data = [head]
    for i, it in enumerate(items, start=1):
        unit_price = (float(it.get("manual_override"))
                       if it.get("manual_override") not in (None, "")
                       else float(it.get("avg_price") or 0))
        subtotal = unit_price * float(it.get("qty") or 0)
        sources = it.get("sources") or []
        conf = it.get("confidence") or "—"
        src_text = ", ".join(sources[:2]) if sources else "Estim. IA"
        if it.get("manual_override") not in (None, ""):
            src_text = "Manual"
        src_paragraph = Paragraph(
            f"{src_text}<br/><font color='#64748b' size='6.5'>"
            f"confiança: {conf}</font>", small)
        name_paragraph = Paragraph(
            f"<b>{it.get('name', '')}</b>" +
            (f"<br/><font color='#64748b' size='6.5'>{it.get('spec', '')}</font>"
              if it.get("spec") else ""), small)
        data.append([
            str(i),
            name_paragraph,
            f"{it.get('qty', 0):g}",
            it.get("unit", "un"),
            _money_br(unit_price),
            _money_br(subtotal),
            src_paragraph,
        ])

    tbl = Table(data, colWidths=[10 * mm, 60 * mm, 14 * mm, 12 * mm,
                                   23 * mm, 25 * mm, 36 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("ALIGN", (2, 1), (5, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f8fafc")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 0.5 * cm))

    # ---- 5. Totais (mostra apenas Base · Mão de obra · TOTAL FINAL) ----
    t = budget.get("totals") or {}
    totals_data = [
        ["Base (soma dos subtotais)", _money_br(t.get("base", 0))],
        ["Mão de obra", _money_br(t.get("labor_val", 0))],
        ["TOTAL FINAL", _money_br(t.get("final", 0))],
    ]
    totals_tbl = Table(totals_data, colWidths=[90 * mm, 40 * mm], hAlign="RIGHT")
    totals_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -2), "Helvetica"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTSIZE", (0, -1), (-1, -1), 12),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
        ("LINEABOVE", (0, -1), (-1, -1), 0.6, colors.HexColor("#94a3b8")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(totals_tbl)
    story.append(Spacer(1, 0.6 * cm))

    # ---- 6. Rodapé + assinaturas ----
    ai_meta = budget.get("ai_model", "")
    story.append(Paragraph(
        f"<font color='#64748b'>Preços estimados pela <b>Orçamento_IA</b> "
        f"({ai_meta or 'Claude Sonnet 4.5'}) com base em conhecimento de mercado "
        f"(Mercado Livre · Amazon · Furukawa · FiberHome · Intelbras). Valores "
        f"sujeitos a confirmação com fornecedor antes do fechamento.</font>",
        small))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(
        f"Emitido por: <b>{generated_by or budget.get('created_by_name', '')}</b> "
        f"· Validade: 7 dias a partir da emissão.", body))
    story.append(Spacer(1, 1.0 * cm))
    sign = Table([["__________________________________",
                     "__________________________________"],
                    ["Responsável Técnico", "Cliente"]],
                   colWidths=[70 * mm, 70 * mm])
    sign.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 1), (-1, 1), 8),
        ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#64748b")),
    ]))
    story.append(sign)

    doc.build(story)
    return buf.getvalue()
