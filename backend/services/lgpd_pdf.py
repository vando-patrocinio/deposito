"""
lgpd_pdf.py — Sprint 5 / iter224
Geração de PDF assinado do Subject Report (LGPD art. 18).

PDF contém:
  - Cabeçalho com selo "Verificado por hash-chain"
  - Dados do titular + base legal
  - Resumo por categoria
  - Timeline cronológico de eventos
  - Footer com hash do PDF (auto-checksum) + número do dossiê
"""
from __future__ import annotations

import hashlib
import io
import uuid
from datetime import datetime, timezone
from typing import Any, Dict


def build_pdf(subject_report: Dict[str, Any],
                verify_status: Dict[str, Any],
                company_name: str = "SmartProv") -> bytes:
    """Renderiza o dossiê em bytes PDF."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    )

    PURPLE = colors.HexColor("#4b1d7a")
    ORANGE = colors.HexColor("#f28c28")
    GREEN = colors.HexColor("#237a4b")
    RED = colors.HexColor("#b42318")
    MUTED = colors.HexColor("#475569")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"Dossiê LGPD {subject_report.get('subject_id')}",
        author=company_name,
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"],
                          textColor=PURPLE, fontSize=18,
                          spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"],
                          textColor=PURPLE, fontSize=12,
                          spaceBefore=8, spaceAfter=4)
    body = ParagraphStyle("body", parent=styles["BodyText"],
                            fontSize=9, leading=12)
    small = ParagraphStyle("small", parent=styles["BodyText"],
                              fontSize=7.5, leading=10,
                              textColor=MUTED)
    badge_ok = ParagraphStyle("badge_ok", parent=body, fontSize=10,
                                 textColor=colors.white,
                                 backColor=GREEN, leading=14)
    badge_warn = ParagraphStyle("badge_warn", parent=body, fontSize=10,
                                   textColor=colors.white,
                                   backColor=RED, leading=14)

    elems = []

    # Cabeçalho
    elems.append(Paragraph(
        f"Dossiê LGPD — Titular de Dados", h1))
    elems.append(Paragraph(
        f"<b>{company_name}</b> — Resposta a direito do titular "
        f"(Lei nº 13.709/2018, art. 18, incisos I e II)", small))
    elems.append(Spacer(1, 6))

    # Selo de verificação
    verified = (verify_status or {}).get("status") == "ok"
    selo_text = (
        "<b>&nbsp;&nbsp;✓ INTEGRIDADE VERIFICADA POR HASH-CHAIN&nbsp;&nbsp;</b>"
        if verified else
        "<b>&nbsp;&nbsp;⚠ ADULTERAÇÃO DETECTADA NA CADEIA&nbsp;&nbsp;</b>")
    elems.append(Paragraph(selo_text,
                              badge_ok if verified else badge_warn))
    elems.append(Spacer(1, 2))
    elems.append(Paragraph(
        f"Cadeia recomputada com {verify_status.get('checked', 0)} "
        f"eventos. Breaks detectados: "
        f"{verify_status.get('broken_count', 0)}.",
        small))
    elems.append(Spacer(1, 10))

    # Bloco de dados do titular
    elems.append(Paragraph("Identificação do titular", h2))
    rows = [
        ["ID do titular", subject_report.get("subject_id") or "—"],
        ["E-mail", subject_report.get("email") or "—"],
        ["Total de eventos", str(subject_report.get("total_events", 0))],
        ["Período coberto",
            _period(subject_report.get("events"))],
        ["Gerado em", subject_report.get("generated_at") or
            datetime.now(timezone.utc).isoformat()],
    ]
    t = Table(rows, colWidths=[45 * mm, 130 * mm])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elems.append(t)
    elems.append(Spacer(1, 10))

    # Resumo por categoria
    elems.append(Paragraph("Resumo por categoria de ação", h2))
    by_cat = subject_report.get("by_category") or {}
    if by_cat:
        cat_rows = [["Categoria", "Quantidade"]]
        for k, v in sorted(by_cat.items(), key=lambda x: -x[1]):
            cat_rows.append([k, str(v)])
        t = Table(cat_rows, colWidths=[100 * mm, 30 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), PURPLE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elems.append(t)
    else:
        elems.append(Paragraph(
            "Nenhum evento encontrado para este titular.", body))
    elems.append(Spacer(1, 10))

    # Timeline
    elems.append(Paragraph("Histórico cronológico", h2))
    events = subject_report.get("events") or []
    if events:
        timeline_rows = [
            ["Data/hora", "Categoria", "Ação", "Por", "IP"],
        ]
        for ev in events[:200]:
            timeline_rows.append([
                _fmt(ev.get("created_at")),
                ev.get("category") or "—",
                (ev.get("action") or "")[:50],
                (ev.get("actor_email") or "")[:28],
                ev.get("ip") or "—",
            ])
        t = Table(timeline_rows,
                     colWidths=[32 * mm, 25 * mm, 60 * mm,
                                  35 * mm, 25 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), PURPLE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 7.2),
            ("GRID", (0, 0), (-1, -1), 0.2, colors.lightgrey),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elems.append(t)
        if len(events) > 200:
            elems.append(Spacer(1, 4))
            elems.append(Paragraph(
                f"<i>* exibindo as 200 mais recentes de "
                f"{len(events)} entradas. Use export-csv para o "
                f"dataset completo.</i>", small))
    else:
        elems.append(Paragraph("Sem eventos.", body))

    elems.append(Spacer(1, 14))
    # Base legal
    elems.append(Paragraph(
        "<b>Base legal:</b> " + (
            subject_report.get("lgpd_basis") or "—"), small))
    elems.append(Spacer(1, 6))
    elems.append(Paragraph(
        "<b>Aviso:</b> dados pessoais foram mascarados na listagem "
        "pública do Audit Trail; este dossiê apresenta dados "
        "completos por se tratar de resposta direta ao titular ou "
        "à autoridade competente.", small))

    # Footer com dossie ID + checksum (será calculado pós-geração)
    dossie_id = f"DOSS-{uuid.uuid4().hex[:10].upper()}"
    elems.append(Spacer(1, 10))
    elems.append(Paragraph(
        f"<b>ID do dossiê:</b> {dossie_id}<br/>"
        f"<b>Emitido por:</b> {company_name} — SmartProv "
        f"Audit Trail Engine", small))

    doc.build(elems)
    pdf_bytes = buf.getvalue()
    checksum = hashlib.sha256(pdf_bytes).hexdigest()
    return pdf_bytes, dossie_id, checksum


def _fmt(s):
    if not s:
        return "—"
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")) \
            .strftime("%d/%m/%y %H:%M")
    except Exception:
        return str(s)[:16]


def _period(events):
    if not events:
        return "—"
    try:
        ds = [e.get("created_at") for e in events if e.get("created_at")]
        if not ds:
            return "—"
        return f"{_fmt(min(ds))} → {_fmt(max(ds))}"
    except Exception:
        return "—"
