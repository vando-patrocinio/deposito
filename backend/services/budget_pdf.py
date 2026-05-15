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
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=7.5,
                              leading=9, textColor=colors.HexColor("#64748b"))

    story = []

    # ---- 1. Header (logo + dados da empresa) — mesmo do romaneio ----
    story.append(_build_header_block(branding, styles))
    story.append(Spacer(1, 0.4 * cm))

    # ---- 2. Bloco título + metadata num "card" coeso ----
    # Linha divisora elegante separando o header da empresa do conteúdo
    divider = Table([[""]], colWidths=[None], rowHeights=[2])
    divider.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0f172a")),
    ]))
    story.append(divider)
    story.append(Spacer(1, 0.5 * cm))

    # Título grande à esquerda + Data + Validade à direita (mesma linha)
    title_par = Paragraph(
        "<b>ORÇAMENTO DE MATERIAIS</b>",
        ParagraphStyle("title", parent=styles["Normal"], fontSize=16,
                          leading=20, textColor=colors.HexColor("#0b1220")),
    )
    issue_date = datetime.now().strftime("%d/%m/%Y")
    meta_right = Paragraph(
        f"<font color='#64748b' size='8'>EMISSÃO</font><br/>"
        f"<font size='10'><b>{issue_date}</b></font><br/>"
        f"<font color='#64748b' size='8'>VALIDADE</font><br/>"
        f"<font size='10'><b>7 dias</b></font>",
        ParagraphStyle("meta_right", parent=styles["Normal"], fontSize=9,
                          leading=13, alignment=2),
    )
    title_tbl = Table([[title_par, meta_right]], colWidths=[None, 4.5 * cm])
    title_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    story.append(title_tbl)
    story.append(Spacer(1, 0.3 * cm))

    # Nome do projeto em destaque (caixa com fundo bege claro)
    project_name = budget.get("name", "—")
    project_par = Paragraph(
        f"<b>Projeto:</b> {project_name}",
        ParagraphStyle("project", parent=styles["Normal"], fontSize=11,
                          leading=14, textColor=colors.HexColor("#0b1220")),
    )
    project_box = Table([[project_par]], colWidths=[None])
    project_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5f9")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(project_box)

    # Descrição (se houver) em parágrafo discreto
    if budget.get("description"):
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph(
            f"<font color='#475569'>{budget['description']}</font>",
            ParagraphStyle("desc", parent=styles["Normal"], fontSize=9,
                              leading=12),
        ))
    story.append(Spacer(1, 0.6 * cm))

    # ---- 3. Header da tabela: "Itens do orçamento" ----
    story.append(Paragraph(
        "<b>ITENS DO ORÇAMENTO</b>",
        ParagraphStyle("sec", parent=styles["Normal"], fontSize=9,
                          leading=12, textColor=colors.HexColor("#64748b"),
                          spaceAfter=4),
    ))

    # ---- 4. Tabela de itens ----
    items = budget.get("items") or []
    head = ["#", "Item", "Qtde", "Unid", "Preço unit.", "Subtotal"]
    data = [head]
    for i, it in enumerate(items, start=1):
        unit_price = (float(it.get("manual_override"))
                       if it.get("manual_override") not in (None, "")
                       else float(it.get("avg_price") or 0))
        subtotal = unit_price * float(it.get("qty") or 0)
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
        ])

    tbl = Table(data, colWidths=[12 * mm, 80 * mm, 18 * mm, 16 * mm,
                                   28 * mm, 32 * mm], repeatRows=1)
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

    # ---- 5. Totais — caixa enxuta à direita, TOTAL FINAL em destaque ----
    t = budget.get("totals") or {}
    labor_val = t.get("labor_val", 0)
    final_val = t.get("final", 0)
    totals_rows = []
    if labor_val:
        totals_rows.append(["Mão de obra", _money_br(labor_val)])
    totals_rows.append(["TOTAL FINAL", _money_br(final_val)])
    totals_tbl = Table(totals_rows, colWidths=[55 * mm, 40 * mm], hAlign="RIGHT")
    totals_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -2), "Helvetica"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -2), 10),
        ("FONTSIZE", (0, -1), (-1, -1), 14),
        ("TEXTCOLOR", (0, 0), (-1, -2), colors.HexColor("#475569")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
        ("LINEABOVE", (0, -1), (-1, -1), 0.6, colors.HexColor("#94a3b8")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ALIGN", (0, -1), (0, -1), "LEFT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(totals_tbl)
    story.append(Spacer(1, 1.0 * cm))

    # ---- 6. Rodapé — info do emissor à esquerda, assinaturas embaixo ----
    issuer_name = generated_by or budget.get("created_by_name", "")
    if issuer_name:
        story.append(Paragraph(
            f"<font color='#64748b' size='8'>EMITIDO POR</font><br/>"
            f"<font size='10'><b>{issuer_name}</b></font>",
            ParagraphStyle("issuer", parent=styles["Normal"], fontSize=9,
                              leading=13),
        ))
    story.append(Spacer(1, 1.4 * cm))
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
