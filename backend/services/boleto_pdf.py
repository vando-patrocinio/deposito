"""Gerador de PDF de boleto com branding Ligo Fibra.

Usa reportlab (puro Python, sem deps de sistema). Layout inspirado no
timbrado oficial: roxo + verde-teal + ondas decorativas.

Função principal: build_boleto_pdf(invoice) -> bytes
"""
from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("ponto.boleto_pdf")

# Cores da marca (do site/timbrado Ligo Fibra)
LIGO_PURPLE = "#6A1B9A"
LIGO_TEAL = "#00BF9E"
LIGO_DARK = "#1A1A2E"

BASE_DIR = Path(__file__).resolve().parents[1]
LOGO_PATH = BASE_DIR / "static" / "logo-ligo.png"
HEADER_PATH = BASE_DIR / "assets" / "boleto_header.jpg"
FOOTER_PATH = BASE_DIR / "assets" / "boleto_footer.jpg"


async def _resolve_logo(company_id: Optional[str] = None) -> Optional[bytes]:
    """Devolve bytes do logo a usar — DB tem prioridade (custom upload do
    gestor), depois cai no logo padrão `/static/logo-ligo.png`.

    Retorna None se nenhuma das duas fontes tiver imagem válida.
    """
    if company_id:
        try:
            from database import db as _db
            doc = await _db.aihub_settings.find_one(
                {"company_id": company_id, "key": "boleto_pdf_logo"},
                {"_id": 0, "image_data_url": 1},
            )
            if doc and doc.get("image_data_url"):
                import base64
                url = doc["image_data_url"]
                if "," in url:
                    return base64.b64decode(url.split(",", 1)[1])
        except Exception as e:
            logger.info("[boleto_pdf] custom logo skip: %s", e)
    if LOGO_PATH.exists():
        try:
            return LOGO_PATH.read_bytes()
        except Exception:
            pass
    return None


def _format_brl(v: Any) -> str:
    try:
        n = float(v)
    except Exception:
        return "—"
    return f"R$ {n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _format_due(s: Any) -> str:
    if not s:
        return "—"
    text = str(s)[:10]
    if "-" in text and len(text) >= 10:
        y, m, d = text[:4], text[5:7], text[8:10]
        return f"{d}/{m}/{y}"
    return text


def _qr_image(payload: str) -> bytes:
    """Gera QR Code PNG do PIX copia-e-cola."""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M
    img = qrcode.QRCode(
        version=None, error_correction=ERROR_CORRECT_M, box_size=8, border=2,
    )
    img.add_data(payload)
    img.make(fit=True)
    pil = img.make_image(fill_color="#1A1A2E", back_color="white")
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


def _barcode_image(line: str) -> Optional[bytes]:
    """Renderiza código de barras Itf25 (formato bancário brasileiro) PNG.

    `line` deve ser a linha digitável ou o código de barras de 44 dígitos.
    """
    try:
        # Limpa pra só dígitos
        digits = "".join(ch for ch in line if ch.isdigit())
        if len(digits) < 20:
            return None
        # Linha digitável de 47 dígitos → extrair os 44 do código de barras
        if len(digits) == 47:
            digits = (digits[0:4] + digits[32:47]
                      + digits[4:9] + digits[10:20] + digits[21:31])
        # Itf25 exige par; trunca pra 44 se vier maior
        digits = digits[:44]
        if len(digits) % 2 == 1:
            digits = digits[:-1]
        import barcode
        from barcode.writer import ImageWriter
        code_cls = barcode.get_barcode_class("itf")
        buf = io.BytesIO()
        code = code_cls(digits, writer=ImageWriter())
        code.write(buf, options={
            "module_height": 15.0,
            "module_width": 0.3,
            "quiet_zone": 2.0,
            "write_text": False,
            "background": "white",
            "foreground": "black",
        })
        return buf.getvalue()
    except Exception as e:
        logger.info("[boleto_pdf] barcode skip: %s", e)
        return None


def build_boleto_pdf(invoice: Dict[str, Any], *,
                       customer_name: Optional[str] = None,
                       logo_bytes: Optional[bytes] = None) -> bytes:
    """Gera PDF do boleto com branding Ligo Fibra.

    invoice dict pode conter:
      - amount, due_date
      - pix_copia_cola (ou pix_payload / pix)
      - digitable_line (ou linha_digitavel / codigo_barras)
      - boleto_url (link do PDF oficial — vai como fallback no rodapé)
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    # ---------- HEADER: imagem oficial Ligo Fibra (testeira) ----------
    # A imagem `assets/boleto_header.jpg` substitui o desenho com onda+logo.
    # Se não existir, faz fallback pra desenho antigo.
    header_drew = False
    if HEADER_PATH.exists():
        try:
            c.drawImage(
                ImageReader(str(HEADER_PATH)),
                0, H - 35 * mm,
                width=W, height=35 * mm,
                preserveAspectRatio=False, mask="auto",
            )
            header_drew = True
        except Exception as e:
            logger.info("[boleto_pdf] header img skip: %s", e)

    if not header_drew:
        # Fallback: desenho original com onda + logo
        c.setFillColorRGB(0x6A / 255, 0x1B / 255, 0x9A / 255)
        c.rect(0, H - 35 * mm, W, 35 * mm, fill=1, stroke=0)
        p = c.beginPath()
        p.moveTo(0, H - 33 * mm)
        p.curveTo(W * 0.3, H - 20 * mm, W * 0.7, H - 50 * mm, W, H - 30 * mm)
        p.lineTo(W, H - 35 * mm)
        p.lineTo(0, H - 35 * mm)
        p.close()
        c.setFillColorRGB(0x00 / 255, 0xBF / 255, 0x9E / 255)
        c.drawPath(p, fill=1, stroke=0)
        # Logo (canto superior direito)
        logo_data = logo_bytes
        if logo_data is None and LOGO_PATH.exists():
            try:
                logo_data = LOGO_PATH.read_bytes()
            except Exception:
                logo_data = None
        if logo_data:
            try:
                c.drawImage(
                    ImageReader(io.BytesIO(logo_data)),
                    W - 60 * mm, H - 28 * mm,
                    width=50 * mm, height=18 * mm,
                    preserveAspectRatio=True, mask="auto",
                )
            except Exception as e:
                logger.info("[boleto_pdf] logo skip: %s", e)
        else:
            c.setFillColorRGB(1, 1, 1)
            c.setFont("Helvetica-Bold", 22)
            c.drawRightString(W - 15 * mm, H - 22 * mm, "Ligo Fibra")
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica", 9)
        c.drawString(15 * mm, H - 14 * mm, "www.ligofibra.com.br")
        c.setFont("Helvetica-Bold", 18)
        c.drawString(15 * mm, H - 25 * mm, "FATURA / BOLETO")

    # ---------- CORPO ----------
    y = H - 50 * mm
    c.setFillColorRGB(0.10, 0.10, 0.18)
    c.setFont("Helvetica", 11)
    if customer_name:
        c.drawString(15 * mm, y, "Cliente:")
        c.setFont("Helvetica-Bold", 12)
        c.drawString(35 * mm, y, customer_name[:60])
        y -= 8 * mm

    # Caixa de valor + vencimento
    c.setFillColorRGB(0.97, 0.97, 1.0)
    c.roundRect(15 * mm, y - 26 * mm, W - 30 * mm, 26 * mm, 4 * mm,
                fill=1, stroke=0)

    c.setFillColorRGB(0x6A / 255, 0x1B / 255, 0x9A / 255)
    c.setFont("Helvetica", 9)
    c.drawString(22 * mm, y - 7 * mm, "VALOR A PAGAR")
    c.setFillColorRGB(0.05, 0.05, 0.1)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(22 * mm, y - 19 * mm, _format_brl(invoice.get("amount")))

    c.setFillColorRGB(0x6A / 255, 0x1B / 255, 0x9A / 255)
    c.setFont("Helvetica", 9)
    c.drawString(W / 2 + 10 * mm, y - 7 * mm, "VENCIMENTO")
    c.setFillColorRGB(0.05, 0.05, 0.1)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(W / 2 + 10 * mm, y - 19 * mm,
                 _format_due(invoice.get("due_date")))
    y -= 36 * mm

    # ---------- DISCRIMINATIVO: mensalidade + reajuste + serviços ----------
    line_items = invoice.get("line_items") or []
    if line_items:
        c.setFillColorRGB(0.97, 0.97, 1.0)
        # Calcula altura do bloco baseada em quantidade de linhas + cabeçalho
        block_h = max(20, 6 + len(line_items) * 5 + 6)
        c.roundRect(15 * mm, y - block_h * mm, W - 30 * mm, block_h * mm,
                    3 * mm, fill=1, stroke=0)
        # Cabeçalho
        c.setFillColorRGB(0x6A / 255, 0x1B / 255, 0x9A / 255)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(20 * mm, y - 5 * mm, "DISCRIMINATIVO DA FATURA")
        # Linhas
        c.setFillColorRGB(0.10, 0.10, 0.18)
        c.setFont("Helvetica", 9)
        row_y = y - 10 * mm
        for li in line_items:
            label = (li.get("label") or "Item")[:50]
            val = _format_brl(li.get("amount") or 0)
            c.drawString(22 * mm, row_y, label)
            c.drawRightString(W - 22 * mm, row_y, val)
            row_y -= 5 * mm
        # Linha separadora + total
        c.setStrokeColorRGB(0.7, 0.7, 0.8)
        c.line(22 * mm, row_y + 1 * mm, W - 22 * mm, row_y + 1 * mm)
        c.setFillColorRGB(0x6A / 255, 0x1B / 255, 0x9A / 255)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(22 * mm, row_y - 4 * mm, "TOTAL")
        c.drawRightString(W - 22 * mm, row_y - 4 * mm,
                          _format_brl(invoice.get("amount")))
        y -= (block_h + 4) * mm

    # ---------- PIX ----------
    pix = (invoice.get("pix_copia_cola") or invoice.get("pix_payload")
           or invoice.get("pix"))
    if pix:
        c.setFillColorRGB(0x00 / 255, 0xBF / 255, 0x9E / 255)
        c.rect(15 * mm, y - 5 * mm, W - 30 * mm, 5 * mm, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20 * mm, y - 3.5 * mm, "PAGUE COM PIX (mais rápido)")
        y -= 7 * mm

        # QR Code
        try:
            qr_bytes = _qr_image(pix)
            c.drawImage(
                ImageReader(io.BytesIO(qr_bytes)),
                15 * mm, y - 42 * mm,
                width=40 * mm, height=40 * mm, mask="auto",
            )
        except Exception as e:
            logger.warning("[boleto_pdf] qr falhou: %s", e)

        # PIX copia-e-cola ao lado do QR
        c.setFillColorRGB(0.10, 0.10, 0.18)
        c.setFont("Helvetica", 9)
        c.drawString(60 * mm, y - 6 * mm,
                     "1. Abra seu banco · 2. Pix · 3. Pix Copia e Cola")
        c.drawString(60 * mm, y - 12 * mm, "Copie o código abaixo:")

        # Caixa do código (truncado)
        c.setFillColorRGB(0.95, 0.96, 0.97)
        c.roundRect(60 * mm, y - 36 * mm, W - 75 * mm, 22 * mm, 2 * mm,
                    fill=1, stroke=0)
        c.setFillColorRGB(0.10, 0.10, 0.18)
        c.setFont("Courier", 7)
        chunk_size = 60
        line_y = y - 18 * mm
        for i in range(0, min(len(pix), chunk_size * 3), chunk_size):
            c.drawString(63 * mm, line_y, pix[i:i + chunk_size])
            line_y -= 4 * mm
        y -= 46 * mm

    # ---------- CÓDIGO DE BARRAS ----------
    bar_line = (invoice.get("digitable_line") or invoice.get("linha_digitavel")
                or invoice.get("codigo_barras") or invoice.get("barcode"))
    if bar_line:
        c.setFillColorRGB(0x6A / 255, 0x1B / 255, 0x9A / 255)
        c.rect(15 * mm, y - 5 * mm, W - 30 * mm, 5 * mm, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20 * mm, y - 3.5 * mm,
                     "OU PAGUE EM QUALQUER BANCO COM O CÓDIGO DE BARRAS")
        y -= 9 * mm

        bar_bytes = _barcode_image(bar_line)
        if bar_bytes:
            c.drawImage(
                ImageReader(io.BytesIO(bar_bytes)),
                15 * mm, y - 18 * mm,
                width=W - 30 * mm, height=18 * mm, mask="auto",
                preserveAspectRatio=True, anchor="c",
            )
            y -= 22 * mm

        # Linha digitável
        c.setFillColorRGB(0.10, 0.10, 0.18)
        c.setFont("Courier-Bold", 11)
        c.drawCentredString(W / 2, y - 4 * mm, str(bar_line))
        y -= 10 * mm

    # ---------- FOOTER: imagem oficial Ligo Fibra (rodapé) ----------
    footer_drew = False
    if FOOTER_PATH.exists():
        try:
            c.drawImage(
                ImageReader(str(FOOTER_PATH)),
                0, 0,
                width=W, height=30 * mm,
                preserveAspectRatio=False, mask="auto",
            )
            footer_drew = True
        except Exception as e:
            logger.info("[boleto_pdf] footer img skip: %s", e)

    if not footer_drew:
        # Fallback: ondas + texto desenhado
        c.setFillColorRGB(0x6A / 255, 0x1B / 255, 0x9A / 255)
        fp = c.beginPath()
        fp.moveTo(0, 0)
        fp.lineTo(0, 25 * mm)
        fp.curveTo(W * 0.3, 35 * mm, W * 0.7, 15 * mm, W, 25 * mm)
        fp.lineTo(W, 0)
        fp.close()
        c.drawPath(fp, fill=1, stroke=0)
        c.setFillColorRGB(0x00 / 255, 0xBF / 255, 0x9E / 255)
        fp2 = c.beginPath()
        fp2.moveTo(0, 0)
        fp2.lineTo(0, 10 * mm)
        fp2.curveTo(W * 0.4, 18 * mm, W * 0.6, 6 * mm, W, 12 * mm)
        fp2.lineTo(W, 0)
        fp2.close()
        c.drawPath(fp2, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(15 * mm, 21 * mm,
                     "Ligo Fibra · A Internet que te faz feliz")
        c.setFont("Helvetica", 7.5)
        c.drawString(15 * mm, 17 * mm,
                     "V S DO PATROCINIO PROVEDOR DE INTERNET ME · "
                     "CNPJ 13.302.883/0001-36")
        c.drawString(15 * mm, 13.5 * mm,
                     "ANATEL Fistel 50418215421 · SEI 53500.025630/2019-3")
        c.setFont("Helvetica-Bold", 8)
        c.drawRightString(W - 15 * mm, 21 * mm, "Central do Assinante:")
        c.setFont("Helvetica", 8)
        c.drawRightString(W - 15 * mm, 17 * mm,
                            "www.ligofibra.com.br/central")
        c.drawRightString(W - 15 * mm, 13.5 * mm, "0800 021 21 11")

    c.showPage()
    c.save()
    return buf.getvalue()
