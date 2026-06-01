"""Projetos · Propostas Comerciais — IA Claude 4.6 + PDF.

Endpoints:
- POST   /api/propostas              — cria/salva proposta (com IA opcional)
- GET    /api/propostas              — lista (com filtros)
- GET    /api/propostas/{id}         — detalhe
- POST   /api/propostas/{id}/regenerate-ai — re-roda o Claude pra novas variações
- GET    /api/propostas/{id}/pdf     — gera o PDF
- DELETE /api/propostas/{id}         — remove

Identidade visual fixa (cores LIGO roxo+laranja). A IA varia o texto
informativo (header descritivo, diferencial, benefício, fechamento).
"""
from __future__ import annotations

import io
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, EMERGENT_LLM_KEY, get_current_user, now_iso
from database import db

logger = logging.getLogger("ponto.propostas")
router = APIRouter(prefix="/api/propostas", tags=["projetos-propostas"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class PropostaIn(BaseModel):
    client_name: str = Field(..., min_length=2, max_length=200)
    address: str = Field(..., min_length=4, max_length=400)
    plan_description: str = Field(..., min_length=3, max_length=400,
                                       description="Ex.: 'Link Dedicado 1 Giga + Instalação'")
    monthly_value: float = Field(..., gt=0)
    fidelity_months: int = Field(12, ge=1, le=60)
    exemption_months_count: int = Field(0, ge=0, le=12)
    exemption_pattern: str = Field("alternados",
                                       description="alternados | primeiros | ultimos | custom")
    differential_text: Optional[str] = None
    additional_benefit_text: Optional[str] = None
    run_ai: bool = True  # se False, salva exatamente o que veio
    ai_tone: str = Field("profissional", description="profissional | caloroso | direto")


class PropostaRegenIn(BaseModel):
    ai_tone: str = "profissional"
    focus_hint: Optional[str] = None


# ---------------------------------------------------------------------------
# AI helpers
# ---------------------------------------------------------------------------
_AI_SYSTEM = """Você é um copywriter sênior de uma empresa de telecom (provedor
de internet via fibra óptica). Sua função é gerar TEXTO COMERCIAL para
PROPOSTAS, mantendo identidade visual fixa, mas variando o informativo de
forma criativa, persuasiva e profissional, em português brasileiro.

Recebe os dados do cliente em JSON. Devolve APENAS um JSON válido (sem
markdown, sem ```), no formato exato:

{
  "header_intro": "string até 180 chars",
  "service_bullets": ["bullet1", "bullet2", "bullet3?"],
  "differential": "1-2 frases (até 280 chars)",
  "additional_benefit": "1-2 frases (até 280 chars)",
  "closing": "frase final cordial até 160 chars",
  "title": "PROPOSTA COMERCIAL" 
}

Regras:
- Mantenha o "title" exatamente como 'PROPOSTA COMERCIAL'.
- "header_intro" começa com 'Segue abaixo a proposta' (ou variação) e
  termina com ':'.
- "service_bullets" descreve o plano contratado em 2-3 bullets curtos.
- "differential" foca em qualidade técnica/suporte (varie palavras).
- "additional_benefit" é o bônus exclusivo desse cliente.
- "closing" agradece e encaminha contrato formal.
- NUNCA invente preço, fidelidade ou endereço — receba via input.
- Use tom solicitado (profissional / caloroso / direto).
- NÃO use emojis. NÃO use markdown. Texto plano.
"""


def _strip_json(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", s, flags=re.M)
    m = re.search(r"\{.*\}", s, flags=re.S)
    return m.group(0) if m else s


async def _ai_generate(payload: PropostaIn,
                          focus_hint: Optional[str] = None) -> Dict[str, Any]:
    """Chama Claude 4.6 para gerar a copy. Em caso de falha devolve fallback."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage  # noqa: PLC0415

    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"proposta-{uuid.uuid4().hex[:10]}",
            system_message=_AI_SYSTEM,
        ).with_model("anthropic", "claude-sonnet-4-6")

        user_data = {
            "cliente": payload.client_name,
            "endereco": payload.address,
            "plano": payload.plan_description,
            "valor_mensal_brl": payload.monthly_value,
            "fidelidade_meses": payload.fidelity_months,
            "isencao_meses_qtd": payload.exemption_months_count,
            "padrao_isencao": payload.exemption_pattern,
            "tom": payload.ai_tone,
        }
        if focus_hint:
            user_data["foco_adicional"] = focus_hint[:200]
        if payload.differential_text:
            user_data["diferencial_seed"] = payload.differential_text[:200]
        if payload.additional_benefit_text:
            user_data["beneficio_seed"] = payload.additional_benefit_text[:200]

        prompt = ("Gere a copy variando criativamente o informativo. "
                  "Dados: " + json.dumps(user_data, ensure_ascii=False))
        raw = await chat.send_message(UserMessage(text=prompt))
        data = json.loads(_strip_json(raw))
        # sanitização leve
        out = {
            "title": (data.get("title") or "PROPOSTA COMERCIAL")[:60],
            "header_intro": (data.get("header_intro") or "Segue abaixo a proposta comercial:")[:200],
            "service_bullets": [str(x)[:140] for x in (data.get("service_bullets") or [])][:4],
            "differential": (data.get("differential") or "")[:320],
            "additional_benefit": (data.get("additional_benefit") or "")[:320],
            "closing": (data.get("closing") or "Agradecemos pela confiança e permanecemos à disposição.")[:200],
            "_raw": raw[:600] if isinstance(raw, str) else None,
        }
        if not out["service_bullets"]:
            out["service_bullets"] = [payload.plan_description, "Instalação completa inclusa"]
        return out
    except Exception as e:
        logger.warning("[propostas] IA fallback: %s", e)
        return {
            "title": "PROPOSTA COMERCIAL",
            "header_intro": "Segue abaixo a proposta comercial:",
            "service_bullets": [payload.plan_description, "Instalação completa inclusa"],
            "differential": (payload.differential_text
                              or "Suporte técnico prioritário e imediato, garantindo "
                                  "estabilidade e agilidade sempre que necessário."),
            "additional_benefit": (payload.additional_benefit_text
                                     or "Aumento temporário da capacidade do link "
                                         "em eventos especiais, sem custo adicional."),
            "closing": ("Após a aprovação desta proposta, encaminharemos o "
                         "contrato formal para assinatura."),
            "_fallback": True,
        }


def _build_payment_schedule(fidelity: int, exemption_count: int,
                              pattern: str) -> List[Dict[str, str]]:
    """Retorna até 4 'primeiros meses' para mostrar tabela Pagamento/Isenção."""
    months: List[Dict[str, str]] = []
    visible = min(4, fidelity)
    if pattern == "primeiros":
        for i in range(visible):
            months.append({"label": f"{i+1}º MÊS",
                             "type": "Isenção" if i < exemption_count else "Pagamento"})
    elif pattern == "ultimos":
        for i in range(visible):
            months.append({"label": f"{i+1}º MÊS", "type": "Pagamento"})
    else:  # alternados (default)
        e_left = exemption_count
        is_exempt_next = False
        for i in range(visible):
            label = f"{i+1}º MÊS"
            if e_left > 0 and is_exempt_next:
                months.append({"label": label, "type": "Isenção"})
                e_left -= 1
                is_exempt_next = False
            else:
                months.append({"label": label, "type": "Pagamento"})
                if e_left > 0:
                    is_exempt_next = True
    return months


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.post("")
async def create_proposta(payload: PropostaIn,
                              user: dict = Depends(get_current_user)):
    cid = _cid(user)
    ai = await _ai_generate(payload) if payload.run_ai else {
        "title": "PROPOSTA COMERCIAL",
        "header_intro": "Segue abaixo a proposta comercial:",
        "service_bullets": [payload.plan_description, "Instalação completa inclusa"],
        "differential": payload.differential_text or "",
        "additional_benefit": payload.additional_benefit_text or "",
        "closing": "Após a aprovação desta proposta, encaminharemos o contrato formal para assinatura.",
    }
    schedule = _build_payment_schedule(payload.fidelity_months,
                                            payload.exemption_months_count,
                                            payload.exemption_pattern)
    doc = {
        "id": f"prop-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "client_name": payload.client_name,
        "address": payload.address,
        "plan_description": payload.plan_description,
        "monthly_value": float(payload.monthly_value),
        "fidelity_months": payload.fidelity_months,
        "exemption_months_count": payload.exemption_months_count,
        "exemption_pattern": payload.exemption_pattern,
        "ai_tone": payload.ai_tone,
        "ai_copy": ai,
        "payment_schedule": schedule,
        "created_by_email": user.get("email"),
        "created_by_name": user.get("name") or user.get("email"),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "pdf_download_count": 0,
    }
    await db.projetos_propostas.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("")
async def list_propostas(q: Optional[str] = None,
                           author_email: Optional[str] = None,
                           limit: int = 100,
                           user: dict = Depends(get_current_user)):
    cid = _cid(user)
    flt: Dict[str, Any] = {"company_id": cid}
    if author_email:
        flt["created_by_email"] = author_email
    if q:
        rx = re.escape(q.strip())
        flt["$or"] = [
            {"client_name": {"$regex": rx, "$options": "i"}},
            {"address": {"$regex": rx, "$options": "i"}},
        ]
    items = await db.projetos_propostas.find(flt, {"_id": 0,
                                                       "ai_copy._raw": 0}) \
        .sort("created_at", -1).limit(int(limit)).to_list(int(limit))
    return {"items": items, "total": len(items)}


@router.get("/{prop_id}")
async def get_proposta(prop_id: str,
                          user: dict = Depends(get_current_user)):
    cid = _cid(user)
    doc = await db.projetos_propostas.find_one(
        {"id": prop_id, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Proposta não encontrada")
    return doc


@router.post("/{prop_id}/regenerate-ai")
async def regenerate_ai(prop_id: str, body: PropostaRegenIn,
                              user: dict = Depends(get_current_user)):
    cid = _cid(user)
    doc = await db.projetos_propostas.find_one(
        {"id": prop_id, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Proposta não encontrada")
    payload = PropostaIn(
        client_name=doc["client_name"], address=doc["address"],
        plan_description=doc["plan_description"],
        monthly_value=doc["monthly_value"],
        fidelity_months=doc["fidelity_months"],
        exemption_months_count=doc["exemption_months_count"],
        exemption_pattern=doc["exemption_pattern"],
        differential_text=(doc.get("ai_copy") or {}).get("differential"),
        additional_benefit_text=(doc.get("ai_copy") or {}).get("additional_benefit"),
        run_ai=True,
        ai_tone=body.ai_tone or doc.get("ai_tone") or "profissional",
    )
    ai = await _ai_generate(payload, focus_hint=body.focus_hint)
    await db.projetos_propostas.update_one(
        {"id": prop_id, "company_id": cid},
        {"$set": {"ai_copy": ai, "ai_tone": payload.ai_tone,
                   "updated_at": now_iso()}},
    )
    doc["ai_copy"] = ai
    doc["ai_tone"] = payload.ai_tone
    return doc


@router.delete("/{prop_id}")
async def delete_proposta(prop_id: str,
                              user: dict = Depends(get_current_user)):
    cid = _cid(user)
    r = await db.projetos_propostas.delete_one(
        {"id": prop_id, "company_id": cid})
    if not r.deleted_count:
        raise HTTPException(404, "Proposta não encontrada")
    return {"ok": True}


# ---------------------------------------------------------------------------
# PDF — layout LIGO (roxo #5b21b6 + laranja #f59e0b)
# ---------------------------------------------------------------------------
def _build_pdf(doc: Dict[str, Any]) -> bytes:
    from reportlab.lib import colors  # noqa: PLC0415
    from reportlab.lib.pagesizes import A4  # noqa: PLC0415
    from reportlab.lib.styles import ParagraphStyle  # noqa: PLC0415
    from reportlab.lib.units import mm  # noqa: PLC0415
    from reportlab.pdfgen import canvas  # noqa: PLC0415
    from reportlab.platypus import Paragraph  # noqa: PLC0415

    PURPLE = colors.HexColor("#5b21b6")
    PURPLE_LIGHT = colors.HexColor("#ede9fe")
    PURPLE_DARK = colors.HexColor("#4c1d95")
    ORANGE = colors.HexColor("#f59e0b")
    DARK = colors.HexColor("#0f172a")
    GREY = colors.HexColor("#64748b")

    ai = doc.get("ai_copy") or {}
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    # ---- Top-left logo bloc (roxo) ----
    # Faixa lateral roxa arredondada
    c.setFillColor(ORANGE)
    c.rect(W - 50*mm, 0, 50*mm, H, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.rect(W - 50*mm, 30*mm, 50*mm, H - 30*mm, fill=1, stroke=0)
    # Detalhe laranja superior-direito (canto)
    p = c.beginPath()
    p.moveTo(W, H)
    p.lineTo(W - 50*mm, H)
    p.lineTo(W, H - 50*mm)
    p.close()
    c.setFillColor(ORANGE)
    c.drawPath(p, fill=1, stroke=0)

    # Logo "LIGO" estilizado (roxo + sorriso laranja)
    c.setFillColor(PURPLE_DARK)
    c.setFont("Helvetica-Bold", 56)
    c.drawString(18*mm, H - 35*mm, "LIGO")
    # "sorriso" laranja embaixo do logo
    c.setStrokeColor(ORANGE)
    c.setLineWidth(3)
    c.line(20*mm, H - 39*mm, 55*mm, H - 39*mm)
    c.setLineWidth(2)
    c.line(50*mm, H - 39*mm, 60*mm, H - 45*mm)
    c.setLineWidth(1)

    # Título
    y = H - 60*mm
    c.setFillColor(PURPLE_DARK)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(18*mm, y, (ai.get("title") or "PROPOSTA COMERCIAL"))
    c.setStrokeColor(PURPLE)
    c.setLineWidth(0.8)
    c.line(18*mm, y - 2*mm, W - 60*mm, y - 2*mm)

    y -= 10*mm
    c.setFillColor(DARK)
    c.setFont("Helvetica", 10)
    c.drawString(18*mm, y, (ai.get("header_intro") or "Segue abaixo a proposta comercial:"))

    # ---- Card cliente (roxo claro) ----
    y -= 12*mm
    card_h = 18*mm
    c.setFillColor(PURPLE_LIGHT)
    c.roundRect(18*mm, y - card_h, W - 78*mm, card_h, 4*mm, fill=1, stroke=0)
    # Ícone circular
    c.setFillColor(PURPLE_DARK)
    c.circle(28*mm, y - card_h/2, 6*mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(28*mm, y - card_h/2 - 1.5*mm, "L")
    # Texto cliente
    c.setFillColor(PURPLE_DARK)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40*mm, y - 6*mm, "Cliente:")
    c.setFont("Helvetica", 10)
    c.setFillColor(DARK)
    c.drawString(58*mm, y - 6*mm, doc.get("client_name", "")[:60])
    c.setFillColor(PURPLE_DARK)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40*mm, y - 12*mm, "Endereço:")
    c.setFont("Helvetica", 10)
    c.setFillColor(DARK)
    c.drawString(62*mm, y - 12*mm, doc.get("address", "")[:70])

    y -= card_h + 8*mm

    # ---- Seção: SERVIÇO CONTRATADO ----
    def _section(label: str, yy: float) -> float:
        c.setFillColor(PURPLE_DARK)
        c.circle(22*mm, yy - 2*mm, 4.2*mm, fill=1, stroke=0)
        c.setFillColor(PURPLE_DARK)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(32*mm, yy - 1*mm, label)
        c.setStrokeColor(PURPLE)
        c.setLineWidth(0.5)
        c.line(32*mm, yy - 4*mm, W - 60*mm, yy - 4*mm)
        return yy - 9*mm

    y = _section("SERVIÇO CONTRATADO", y)
    c.setFillColor(DARK)
    c.setFont("Helvetica", 10)
    for b in (ai.get("service_bullets") or [])[:4]:
        c.drawString(32*mm, y, "• " + str(b)[:110])
        y -= 5*mm

    # INVESTIMENTO
    y -= 4*mm
    y = _section("INVESTIMENTO", y)
    c.setFillColor(DARK)
    c.setFont("Helvetica", 10)
    c.drawString(32*mm, y, "Valor mensal:")
    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(PURPLE_DARK)
    c.drawString(64*mm, y, f"R$ {doc.get('monthly_value', 0):,.2f}"
                  .replace(",", "X").replace(".", ",").replace("X", "."))

    # CONDIÇÃO ESPECIAL
    y -= 9*mm
    y = _section("CONDIÇÃO ESPECIAL", y)
    c.setFillColor(DARK)
    c.setFont("Helvetica", 10)
    c.drawString(32*mm, y, f"• Contrato com fidelidade de {doc.get('fidelity_months', 12)} meses")
    y -= 5*mm
    exc = doc.get("exemption_months_count", 0) or 0
    if exc:
        c.drawString(32*mm, y, f"• Benefício de {exc} mese(s) de isenção, da seguinte forma:")
        y -= 7*mm
        # Tabela
        sched = doc.get("payment_schedule") or []
        col_w = (W - 60*mm - 32*mm) / max(1, len(sched))
        x = 32*mm
        for col in sched:
            c.setStrokeColor(PURPLE)
            c.setLineWidth(0.6)
            c.rect(x, y - 12*mm, col_w, 12*mm, fill=0, stroke=1)
            c.setFillColor(PURPLE_DARK)
            c.setFont("Helvetica-Bold", 9)
            c.drawCentredString(x + col_w/2, y - 4*mm, col["label"])
            c.setStrokeColor(PURPLE)
            c.line(x, y - 6*mm, x + col_w, y - 6*mm)
            c.setFont("Helvetica", 9)
            c.setFillColor(PURPLE_DARK if col["type"] == "Isenção" else DARK)
            c.drawCentredString(x + col_w/2, y - 10*mm, col["type"])
            x += col_w
        y -= 16*mm

    # DIFERENCIAL
    y -= 4*mm
    y = _section("DIFERENCIAL DO SERVIÇO", y)
    diff = ai.get("differential") or ""
    style = ParagraphStyle("body", fontName="Helvetica", fontSize=10,
                                textColor=DARK, leading=13)
    p1 = Paragraph(diff, style)
    pw, ph = p1.wrap(W - 60*mm - 32*mm, 50*mm)
    p1.drawOn(c, 32*mm, y - ph)
    y -= ph + 6*mm

    # BENEFÍCIO
    y = _section("BENEFÍCIO ADICIONAL", y)
    ben = ai.get("additional_benefit") or ""
    p2 = Paragraph(ben, style)
    pw2, ph2 = p2.wrap(W - 60*mm - 32*mm, 50*mm)
    p2.drawOn(c, 32*mm, y - ph2)
    y -= ph2 + 8*mm

    # Closing
    c.setStrokeColor(PURPLE)
    c.setLineWidth(0.5)
    c.line(18*mm, y, W - 60*mm, y)
    y -= 6*mm
    c.setFillColor(DARK)
    c.setFont("Helvetica", 9)
    closing = ai.get("closing") or ""
    pc = Paragraph(closing, style)
    pwc, phc = pc.wrap(W - 60*mm - 18*mm, 30*mm)
    pc.drawOn(c, 18*mm, y - phc)
    y -= phc + 4*mm
    c.setFont("Helvetica", 9)
    c.setFillColor(GREY)
    c.drawString(18*mm, y, "Atenciosamente,")
    y -= 5*mm
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(PURPLE_DARK)
    c.drawString(18*mm, y, "Ligo.")

    # Footer
    c.setFillColor(PURPLE_DARK)
    c.rect(0, 0, W, 12*mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica", 8)
    c.drawString(8*mm, 5*mm, "https://www.ligofibra.com.br/")
    c.drawCentredString(W/2, 5*mm, "+55 (21) 4042-9393")
    c.drawRightString(W - 8*mm, 5*mm, "sac@ligofibra.com.br")

    # Metadata na base
    c.setFillColor(colors.white)
    c.setFont("Helvetica", 6)
    c.drawString(8*mm, 1.5*mm,
                  f"#{doc.get('id', '')[:20]} · {doc.get('created_by_name', '')[:30]} · {doc.get('created_at', '')[:19]}")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()


@router.get("/{prop_id}/pdf")
async def proposta_pdf(prop_id: str,
                          user: dict = Depends(get_current_user)):
    cid = _cid(user)
    doc = await db.projetos_propostas.find_one(
        {"id": prop_id, "company_id": cid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Proposta não encontrada")
    try:
        pdf_bytes = _build_pdf(doc)
    except Exception as e:
        logger.exception("[propostas] PDF render failed: %s", e)
        raise HTTPException(500, f"Falha ao gerar PDF: {e}")
    await db.projetos_propostas.update_one(
        {"id": prop_id, "company_id": cid},
        {"$inc": {"pdf_download_count": 1}},
    )
    safe = re.sub(r"[^A-Za-z0-9]+", "_", doc.get("client_name", "proposta"))[:40]
    fname = f"proposta_{safe}_{prop_id}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
