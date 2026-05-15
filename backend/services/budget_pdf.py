"""Romaneio de orçamento — PDF imprimível.

Layout A4 retrato com header da empresa, tabela de itens (Nome · Qtde · Unid ·
Preço unit. · Subtotal · Fonte IA · Confiança), totais (base · ganho · mão-de-
obra · subtotal · imposto · final) e rodapé com IA usada + assinatura.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Dict

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table,
    TableStyle,
)


def _money_br(v: float) -> str:
    try:
        s = f"{float(v or 0):,.2f}"
        return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "R$ 0,00"


def _header(c: canvas.Canvas, doc) -> None:
    w, h = A4
    # Faixa preta no topo com nome da empresa
    c.setFillColorRGB(0.06, 0.07, 0.1)
    c.rect(0, h - 24 * mm, w, 24 * mm, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(15 * mm, h - 12 * mm, "SmartProv · Orçamento")
    c.setFont("Helvetica", 8)
    c.drawString(15 * mm, h - 19 * mm,
                  f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} "
                  f"· Orçamento_IA via Emergent LLM Key")
    # Página X/Y
    c.setFont("Helvetica", 8)
    c.drawRightString(w - 15 * mm, h - 19 * mm,
                       f"Página {doc.page}")


def build_budget_pdf(budget: Dict[str, Any], generated_by: str = "") -> bytes:
    """Gera PDF do orçamento como bytes."""
    buf = BytesIO()
    pdf = BaseDocTemplate(
        buf, pagesize=A4,
        topMargin=30 * mm, bottomMargin=18 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm,
        title=f"Orçamento {budget.get('name','')}",
    )
    frame = Frame(pdf.leftMargin, pdf.bottomMargin,
                   pdf.width, pdf.height, id="body")
    pdf.addPageTemplates([PageTemplate(id="main", frames=frame, onPage=_header)])

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=16,
                          textColor=colors.HexColor("#0f172a"), spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11,
                          textColor=colors.HexColor("#475569"), spaceAfter=8)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9,
                            leading=11)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=7.5,
                              leading=9, textColor=colors.HexColor("#64748b"))

    story = []
    story.append(Paragraph(budget.get("name", "Sem nome"), h1))
    if budget.get("description"):
        story.append(Paragraph(budget["description"], h2))
    status = budget.get("status", "draft").upper()
    story.append(Paragraph(
        f"Status: <b>{status}</b> · Criado por {budget.get('created_by_name','—')} "
        f"em {budget.get('created_at','')[:10]}", body))
    story.append(Spacer(1, 8))

    # Tabela de itens
    items = budget.get("items") or []
    head = ["#", "Item", "Qtde", "Unid", "Preço unit.", "Subtotal",
             "Fonte / Confiança"]
    data = [head]
    for i, it in enumerate(items, start=1):
        unit_price = (float(it.get("manual_override"))
                       if it.get("manual_override") not in (None, "")
                       else float(it.get("avg_price") or 0))
        subtotal = unit_price * float(it.get("qty") or 0)
        # Texto Fonte
        sources = it.get("sources") or []
        conf = it.get("confidence") or "—"
        src_text = ", ".join(sources[:2]) if sources else "Estim. IA"
        if it.get("manual_override") not in (None, ""):
            src_text = "Manual"
        src_paragraph = Paragraph(f"{src_text}<br/><font color='#64748b' size='6.5'>"
                                       f"confiança: {conf}</font>", small)
        name_paragraph = Paragraph(
            f"<b>{it.get('name','')}</b>" +
            (f"<br/><font color='#64748b' size='6.5'>{it.get('spec','')}</font>"
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
    story.append(Spacer(1, 14))

    # Totais
    t = budget.get("totals") or {}
    totals_data = [
        ["Base (soma dos subtotais)", _money_br(t.get("base", 0))],
        [f"Margem de ganho ({budget.get('margin_pct', 0):.1f}%)",
         _money_br(t.get("margin_val", 0))],
        [f"Mão de obra ({budget.get('labor_pct', 0):.1f}%)",
         _money_br(t.get("labor_val", 0))],
        ["Subtotal", _money_br(t.get("subtotal", 0))],
        [f"Imposto ({budget.get('tax_pct', 0):.1f}%)",
         _money_br(t.get("tax_val", 0))],
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
        ("LINEABOVE", (0, 3), (-1, 3), 0.6, colors.HexColor("#94a3b8")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(totals_tbl)
    story.append(Spacer(1, 18))

    # Rodapé
    ai_meta = budget.get("ai_model", "")
    story.append(Paragraph(
        f"<font color='#64748b'>Preços estimados pela <b>Orçamento_IA</b> "
        f"({ai_meta or 'Claude Sonnet 4.5'}) com base em conhecimento de mercado "
        f"(Mercado Livre · Amazon · Furukawa · FiberHome · Intelbras). Valores "
        f"sujeitos a confirmação com fornecedor antes do fechamento.</font>",
        small))
    story.append(Spacer(1, 20))
    story.append(Paragraph(
        f"Emitido por: <b>{generated_by or budget.get('created_by_name','')}</b> "
        f"· Validade: 7 dias a partir da emissão.", body))
    story.append(Spacer(1, 30))
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

    pdf.build(story)
    return buf.getvalue()
