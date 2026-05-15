"""Geração de relatório PDF de CTOs aprovadas.

Layout do PDF:
- Cabeçalho com logo SmartProv + nome da CTO
- Tabela com dados (Bairro, VLAN, Endereço, GPS, Capacidade, Tipo de rede, Splitter)
- QR Code criptografado (mesmo token usado no app)
- Foto da CTO (se houver)
- Footer com técnico, gestor que aprovou, data
"""
import base64
import io
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle,
    PageBreak,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER

logger = logging.getLogger(__name__)


def _decode_data_url(data_url: str) -> Optional[bytes]:
    """Decodifica data URL `data:image/jpeg;base64,...` → bytes."""
    if not data_url or "," not in data_url:
        return None
    try:
        return base64.b64decode(data_url.split(",", 1)[1])
    except Exception:
        return None


def build_cto_pdf(cto: Dict[str, Any], qr_token: str,
                    approved_by_name: Optional[str] = None) -> bytes:
    """Gera o PDF da CTO em memória e devolve bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        title=f"CTO {cto.get('name')}",
        author="SmartProv",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"],
                         fontSize=20, textColor=colors.HexColor("#5b21b6"),
                         spaceAfter=4, alignment=TA_LEFT)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"],
                         fontSize=11, textColor=colors.HexColor("#64748b"),
                         spaceAfter=12, alignment=TA_LEFT)
    section = ParagraphStyle("Section", parent=styles["Heading3"],
                                fontSize=12, textColor=colors.HexColor("#0f172a"),
                                spaceBefore=12, spaceAfter=6)
    small = ParagraphStyle("Small", parent=styles["Normal"],
                            fontSize=9, textColor=colors.HexColor("#64748b"))

    story = []

    # Header
    story.append(Paragraph("SmartProv · Rede IA", h2))
    story.append(Paragraph(cto.get("name") or "CTO", h1))

    addr = cto.get("address") or {}
    story.append(Paragraph(
        f"{addr.get('rua','')}, {addr.get('numero','')} · "
        f"{addr.get('bairro','')} · {addr.get('cidade','')}/{addr.get('estado','')}",
        h2,
    ))

    # Tabela de dados
    story.append(Paragraph("Dados técnicos", section))
    gps = cto.get("gps") or {}
    rows = [
        ["Bairro", addr.get("bairro") or "—"],
        ["Sigla", cto.get("sigla") or "—"],
        ["VLAN", str(cto.get("vlan") or "—")],
        ["Endereço", f"{addr.get('rua','')}, {addr.get('numero','')}"],
        ["Referência", addr.get("referencia") or "—"],
        ["Posição GPS",
            f"{gps.get('lat'):.6f}, {gps.get('lng'):.6f}"
            if gps and gps.get("lat") is not None else "—"],
        ["Capacidade", f"{cto.get('capacity')} portas"],
        ["Tipo de rede",
            "Rede balanceada" if cto.get("network_type") == "balanceada"
            else "Rede desbalanceada"],
    ]
    if cto.get("splitter"):
        rows.append(["Splitter", cto.get("splitter")])
    used = [p for p in (cto.get("ports") or []) if p.get("status") == "used"]
    free = [p for p in (cto.get("ports") or []) if p.get("status") == "free"]
    rows.append(["Portas ocupadas", f"{len(used)} de {cto.get('capacity')}"])
    rows.append(["Portas livres", str(len(free))])

    t = Table(rows, colWidths=[4.5 * cm, 11.5 * cm])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#64748b")),
        ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#0f172a")),
        ("FONT", (1, 0), (1, -1), "Helvetica-Bold", 10),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1),
            [colors.HexColor("#f8fafc"), colors.white]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(t)

    # QR Code + (foto se houver)
    story.append(Paragraph("QR Code da CTO", section))
    qr_img = qrcode.make(qr_token, box_size=6, border=2)
    qr_buf = io.BytesIO()
    qr_img.save(qr_buf, format="PNG")
    qr_buf.seek(0)
    qr_image = Image(qr_buf, width=5 * cm, height=5 * cm)

    photo_image = None
    photo_bytes = _decode_data_url(cto.get("photo_data_url") or "")
    if photo_bytes:
        try:
            photo_image = Image(io.BytesIO(photo_bytes), width=8.5 * cm,
                                  height=6 * cm, kind="proportional")
        except Exception as e:
            logger.warning("[rede-ia pdf] foto inválida: %s", e)
            photo_image = None

    if photo_image:
        side_by_side = Table(
            [[qr_image, photo_image]],
            colWidths=[5.5 * cm, 9.5 * cm],
        )
        side_by_side.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(side_by_side)
        story.append(Paragraph(
            "Cole este QR Code na CTO física. Apenas o app SmartProv consegue ler.",
            small,
        ))
    else:
        story.append(qr_image)
        story.append(Paragraph(
            "Cole este QR Code na CTO física. Apenas o app SmartProv consegue ler.",
            small,
        ))

    # Footer
    story.append(Spacer(1, 12 * mm))
    story.append(Paragraph("Validação", section))
    tech_name = cto.get("technician_name") or "—"
    approved_at = cto.get("approved_at")
    when = ""
    if approved_at:
        try:
            when = datetime.fromisoformat(approved_at.replace("Z", "+00:00")).strftime("%d/%m/%Y às %H:%M")
        except Exception:
            when = approved_at
    footer_rows = [
        ["Cadastrado por", tech_name],
        ["Aprovado por", approved_by_name or cto.get("approved_by_name") or "—"],
        ["Data da aprovação", when or "—"],
    ]
    ft = Table(footer_rows, colWidths=[4.5 * cm, 11.5 * cm])
    ft.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#64748b")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(ft)

    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        f"Gerado automaticamente pela rede_IA em {datetime.now().strftime('%d/%m/%Y %H:%M')}.",
        small,
    ))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()
