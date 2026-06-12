"""NEO • Relatórios Agendados — Schedule recurring PDF reports.

Funcionalidades:
- CRUD de agendamentos (`neo_report_schedules`)
- Tipos de relatório suportados: `ctos_occupancy`, `closed_tickets`, `dre`
- Frequência: `daily` (HH:MM), `weekly` (dow + HH:MM), `monthly` (DoM + HH:MM)
- Entrega: WhatsApp (Baileys) com PDF anexo
- Histórico de execuções (`neo_report_runs`)

Dispatcher: `dispatch_due_schedules_job` é chamado pelo APScheduler a cada
5 minutos e processa todos os agendamentos onde `next_run_at <= now`.
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

import base64
import io
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, EMERGENT_LLM_KEY, get_current_user, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.neo_reports")
router = APIRouter(prefix="/api/neo-reports", tags=["neo-reports"])

REPORT_TYPES = {"ctos_occupancy", "closed_tickets", "dre",
                "isabella_kpis", "alvaro_tickets", "camila_billing",
                "secretaria_intents", "executive_briefing"}
FREQUENCIES = {"daily", "weekly", "monthly"}

# America/Sao_Paulo (BRT) sem DST atualmente. Usamos UTC-3 fixo.
BRT_OFFSET = timezone(timedelta(hours=-3))


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ScheduleIn(BaseModel):
    name: str
    report_type: str
    frequency: str
    hour: int = Field(..., ge=0, le=23)
    minute: int = Field(0, ge=0, le=59)
    day_of_week: Optional[int] = Field(None, ge=0, le=6)   # 0=Mon
    day_of_month: Optional[int] = Field(None, ge=1, le=28)
    whatsapp_phone: Optional[str] = None      # E.164 sem '+'
    active: bool = True
    # Filtros específicos por tipo (opcional)
    params: Optional[Dict[str, Any]] = None


class SchedulePatch(BaseModel):
    name: Optional[str] = None
    report_type: Optional[str] = None
    frequency: Optional[str] = None
    hour: Optional[int] = Field(None, ge=0, le=23)
    minute: Optional[int] = Field(None, ge=0, le=59)
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    day_of_month: Optional[int] = Field(None, ge=1, le=28)
    whatsapp_phone: Optional[str] = None
    active: Optional[bool] = None
    params: Optional[Dict[str, Any]] = None


class BriefingActivateIn(BaseModel):
    phones: List[str] = []          # E.164 sem '+', múltiplos destinatários
    hour: int = 7
    minute: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


def _now_brt() -> datetime:
    return datetime.now(BRT_OFFSET)


def _compute_next_run(schedule: Dict[str, Any], ref: Optional[datetime] = None) -> datetime:
    """Calcula próximo run a partir de `ref` (default = agora BRT).

    Daily: próximo HH:MM hoje ou amanhã.
    Weekly: próximo `day_of_week` no HH:MM.
    Monthly: próximo `day_of_month` no HH:MM.
    """
    ref = (ref or _now_brt()).astimezone(BRT_OFFSET)
    h, m = int(schedule.get("hour", 8)), int(schedule.get("minute", 0))
    freq = schedule.get("frequency", "daily")

    if freq == "daily":
        candidate = ref.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate <= ref:
            candidate += timedelta(days=1)
        return candidate

    if freq == "weekly":
        target_dow = int(schedule.get("day_of_week") or 0)  # 0=Mon
        # Python: Mon=0..Sun=6, mesmo padrão
        candidate = ref.replace(hour=h, minute=m, second=0, microsecond=0)
        delta_days = (target_dow - candidate.weekday()) % 7
        candidate += timedelta(days=delta_days)
        if candidate <= ref:
            candidate += timedelta(days=7)
        return candidate

    if freq == "monthly":
        target_dom = int(schedule.get("day_of_month") or 1)
        candidate = ref.replace(day=min(target_dom, 28), hour=h, minute=m,
                                  second=0, microsecond=0)
        if candidate <= ref:
            # próximo mês
            y, mo = candidate.year, candidate.month + 1
            if mo > 12:
                mo, y = 1, y + 1
            candidate = candidate.replace(year=y, month=mo)
        return candidate

    # fallback: 1h depois
    return ref + timedelta(hours=1)


def _validate(schedule: Dict[str, Any]) -> None:
    if schedule.get("report_type") not in REPORT_TYPES:
        raise HTTPException(400, f"report_type inválido: use {sorted(REPORT_TYPES)}")
    if schedule.get("frequency") not in FREQUENCIES:
        raise HTTPException(400, f"frequency inválida: use {sorted(FREQUENCIES)}")
    if schedule["frequency"] == "weekly" and schedule.get("day_of_week") is None:
        raise HTTPException(400, "day_of_week é obrigatório para frequência semanal")
    if schedule["frequency"] == "monthly" and schedule.get("day_of_month") is None:
        raise HTTPException(400, "day_of_month é obrigatório para frequência mensal")


# ---------------------------------------------------------------------------
# CRUD Endpoints
# ---------------------------------------------------------------------------
@router.get("/schedules")
async def list_schedules(user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    items = await db.neo_report_schedules.find(
        {"company_id": cid}, {"_id": 0},
    ).sort("created_at", -1).to_list(200)
    return {"items": items, "total": len(items)}


@router.post("/schedules")
async def create_schedule(payload: ScheduleIn,
                            user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    data = payload.model_dump()
    _validate(data)
    now = now_iso()
    next_run = _compute_next_run(data)
    doc = {
        "id": f"nrs-{uuid.uuid4().hex[:12]}",
        "company_id": cid,
        **data,
        "created_at": now,
        "updated_at": now,
        "created_by": user.get("id"),
        "last_run_at": None,
        "next_run_at": next_run.isoformat(),
        "run_count": 0,
    }
    await db.neo_report_schedules.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/schedules/{sid}")
async def update_schedule(sid: str, payload: SchedulePatch,
                            user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    existing = await db.neo_report_schedules.find_one(
        {"id": sid, "company_id": cid}, {"_id": 0},
    )
    if not existing:
        raise HTTPException(404, "Agendamento não encontrado")
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if updates:
        merged = {**existing, **updates}
        _validate(merged)
        # se mudaram horários/frequência, recalcula next_run_at
        if any(k in updates for k in ("hour", "minute", "frequency",
                                          "day_of_week", "day_of_month", "active")):
            updates["next_run_at"] = _compute_next_run(merged).isoformat()
        updates["updated_at"] = now_iso()
        await db.neo_report_schedules.update_one(
            {"id": sid, "company_id": cid}, {"$set": updates},
        )
    out = await db.neo_report_schedules.find_one(
        {"id": sid, "company_id": cid}, {"_id": 0},
    )
    return out


@router.delete("/schedules/{sid}")
async def delete_schedule(sid: str,
                            user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    r = await db.neo_report_schedules.delete_one(
        {"id": sid, "company_id": cid},
    )
    if r.deleted_count == 0:
        raise HTTPException(404, "Agendamento não encontrado")
    return {"ok": True}


@router.post("/schedules/{sid}/run")
async def run_schedule_now(sid: str,
                              user: dict = Depends(require_role("gestor"))):
    """Dispara o relatório imediatamente (independente do horário)."""
    cid = _cid(user)
    sch = await db.neo_report_schedules.find_one(
        {"id": sid, "company_id": cid}, {"_id": 0},
    )
    if not sch:
        raise HTTPException(404, "Agendamento não encontrado")
    run = await _execute_schedule(sch, trigger="manual")
    return run


@router.get("/history")
async def history(limit: int = Query(50, ge=1, le=500),
                    user: dict = Depends(require_role("gestor"))):
    cid = _cid(user)
    items = await db.neo_report_runs.find(
        {"company_id": cid}, {"_id": 0},
    ).sort("at", -1).limit(limit).to_list(limit)
    return {"items": items, "total": len(items)}


@router.get("/report-types")
async def list_report_types(user: dict = Depends(require_role("gestor"))):
    return {
        "items": [
            {"key": "ctos_occupancy", "label": "Ocupação de CTOs",
             "description": "PDF com saturação de portas por CTO"},
            {"key": "closed_tickets", "label": "Notas Fechadas",
             "description": "Relatório consolidado de tickets fechados"},
            {"key": "dre", "label": "DRE Mensal",
             "description": "Demonstração de Resultados (Financeiro)"},
            {"key": "isabella_kpis", "label": "KPIs Isabella (Vendas)",
             "description": "Conversão/vendas via WhatsApp IA"},
            {"key": "alvaro_tickets", "label": "Suporte Álvaro",
             "description": "Tickets criados/fechados, taxa de resolução"},
            {"key": "camila_billing", "label": "Cobranças Pâmela",
             "description": "Recebimentos e mensagens de cobrança"},
            {"key": "secretaria_intents", "label": "Secretaria — Intents",
             "description": "Interações da Secretaria + top intents"},
            {"key": "executive_briefing", "label": "📋 Briefing Executivo NEO",
             "description": "Resumo diário consolidado: KPIs dos 4 agentes + alertas + sumário IA"},
        ],
    }


# ---------------------------------------------------------------------------
# Execução / dispatch
# ---------------------------------------------------------------------------
async def _build_pdf_bytes(report_type: str, cid: str,
                              params: Optional[Dict[str, Any]] = None) -> tuple[bytes, str]:
    """Gera PDF do relatório. Retorna (bytes, filename).

    Estratégia: reutilizamos a lógica dos endpoints existentes em
    `pdf_reports.py` e `financeiro_reports.py` chamando-as como funções.
    Mas como eles dependem do user injetado, vamos chamar funções helper
    diretas (ou simular o user).
    """
    from datetime import datetime as _dt
    params = params or {}

    if report_type == "ctos_occupancy":
        # Reutiliza a lógica do endpoint occupancy_pdf
        from routes.pdf_reports import occupancy_pdf  # type: ignore
        fake_user = {"company_id": cid}
        resp = await occupancy_pdf(  # retorna StreamingResponse
            threshold=float(params.get("threshold", 0.8)),
            user=fake_user,
        )
        # StreamingResponse.body_iterator pode ser drenado
        chunks = []
        async for c in resp.body_iterator:
            chunks.append(c if isinstance(c, (bytes, bytearray)) else c.encode())
        body = b"".join(chunks)
        fname = f"ocupacao_ctos_{_dt.now().strftime('%Y%m%d_%H%M')}.pdf"
        return body, fname

    if report_type == "closed_tickets":
        from routes.pdf_reports import closed_tickets_pdf  # type: ignore
        fake_user = {"company_id": cid}
        resp = await closed_tickets_pdf(
            period=params.get("period", "week"),
            start=params.get("start"),
            end=params.get("end"),
            user=fake_user,
        )
        chunks = []
        async for c in resp.body_iterator:
            chunks.append(c if isinstance(c, (bytes, bytearray)) else c.encode())
        body = b"".join(chunks)
        fname = f"notas_fechadas_{_dt.now().strftime('%Y%m%d_%H%M')}.pdf"
        return body, fname

    if report_type == "dre":
        # DRE retorna JSON, vamos gerar PDF simples com reportlab
        from routes.financeiro_reports import dre as dre_endpoint  # type: ignore
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet

        fake_user = {"company_id": cid, "role": "admin"}
        data = await dre_endpoint(
            month=params.get("month"),
            year=params.get("year"),
            user=fake_user,
        )
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4,
                                  leftMargin=18*mm, rightMargin=18*mm,
                                  topMargin=14*mm, bottomMargin=12*mm)
        styles = getSampleStyleSheet()
        story = [
            Paragraph(f"<b>DRE — {data.get('period') or ''}</b>", styles["Title"]),
            Spacer(1, 8),
        ]
        rows = [["Categoria", "Valor (R$)"]]
        for k in ("receita_bruta", "deducoes", "receita_liquida", "custos",
                  "despesas_operacionais", "ebitda", "resultado_liquido"):
            v = data.get(k)
            if v is not None:
                rows.append([k.replace("_", " ").title(),
                              f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")])
        t = Table(rows, colWidths=[100*mm, 60*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0f172a")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#e2e8f0")),
            ("ALIGN", (-1,0), (-1,-1), "RIGHT"),
        ]))
        story.append(t)
        doc.build(story)
        buf.seek(0)
        body = buf.read()
        fname = f"dre_{_dt.now().strftime('%Y%m%d_%H%M')}.pdf"
        return body, fname

    # ---- Relatórios baseados em ferramentas do NEO Chat ----
    if report_type in ("isabella_kpis", "alvaro_tickets",
                       "camila_billing", "secretaria_intents"):
        from routes.neo_chat import (
            _tool_isabella_kpis, _tool_alvaro_tickets,
            _tool_camila_billing, _tool_secretaria_intents,
        )
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet

        days = int((params or {}).get("days", 7))
        tool_map = {
            "isabella_kpis": (_tool_isabella_kpis, "KPIs Isabella · Vendas WhatsApp IA"),
            "alvaro_tickets": (_tool_alvaro_tickets, "Suporte Álvaro · Tickets"),
            "camila_billing": (_tool_camila_billing, "Cobranças Pâmela · Recebimentos"),
            "secretaria_intents": (_tool_secretaria_intents, "Secretaria · Interações"),
        }
        fn, title = tool_map[report_type]
        data = await fn(cid, days=days)

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4,
                                  leftMargin=18*mm, rightMargin=18*mm,
                                  topMargin=14*mm, bottomMargin=12*mm)
        styles = getSampleStyleSheet()
        story = [
            Paragraph(f"<b>{title}</b>", styles["Title"]),
            Paragraph(f"Período: últimos <b>{days}</b> dias · Gerado em {_dt.now().strftime('%d/%m/%Y %H:%M')}",
                       styles["BodyText"]),
            Spacer(1, 10),
        ]
        # Renderiza data como linhas chave/valor
        rows = [["Métrica", "Valor"]]
        for k, v in data.items():
            if k == "agent":
                continue
            if isinstance(v, list):
                # top_intents etc — sublista
                if v and isinstance(v[0], dict):
                    sub = ", ".join(
                        f"{x.get('intent') or x.get('source') or '?'}: {x.get('count') or x.get('total') or '?'}"
                        for x in v[:5]
                    )
                    rows.append([k.replace("_", " ").title(), sub or "—"])
                else:
                    rows.append([k.replace("_", " ").title(), ", ".join(map(str, v[:10])) or "—"])
            else:
                rows.append([k.replace("_", " ").title(), str(v)])
        t = Table(rows, colWidths=[80*mm, 90*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0d9488")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE", (0,0), (-1,-1), 10),
            ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#e2e8f0")),
            ("ROWBACKGROUNDS", (0,1), (-1,-1),
                [colors.white, colors.HexColor("#f8fafc")]),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ]))
        story.append(t)
        doc.build(story)
        buf.seek(0)
        body = buf.read()
        fname = f"{report_type}_{_dt.now().strftime('%Y%m%d_%H%M')}.pdf"
        return body, fname

    # ---- Briefing Executivo NEO (consolida 4 agentes + alertas + LLM summary) ----
    if report_type == "executive_briefing":
        from routes.neo_chat import (
            _tool_isabella_kpis, _tool_alvaro_tickets,
            _tool_camila_billing, _tool_secretaria_intents,
        )
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet

        days = int((params or {}).get("days", 1))
        # Coleta dados dos 4 agentes em paralelo (best-effort)
        import asyncio as _asyncio
        isb, alv, cam, sec = await _asyncio.gather(
            _tool_isabella_kpis(cid, days=days),
            _tool_alvaro_tickets(cid, days=days),
            _tool_camila_billing(cid, days=days),
            _tool_secretaria_intents(cid, days=days),
            return_exceptions=True,
        )
        def _ok(x): return x if isinstance(x, dict) else {"error": str(x)}
        isb, alv, cam, sec = _ok(isb), _ok(alv), _ok(cam), _ok(sec)

        # Alertas do sistema abertos
        alerts_open = await db.system_alerts.count_documents(
            {"company_id": cid, "resolved": {"$ne": True}})

        # Próximos agendamentos (lousa)
        from datetime import datetime as _dt2
        today_iso = _dt2.now().strftime("%Y-%m-%d")
        appt_today = await db.tickets.count_documents({
            "company_id": cid, "scheduled_for": {"$regex": f"^{today_iso}"},
        }) if True else 0

        # LLM sumariza tudo
        ai_summary = "(IA indisponível)"
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            chat = LlmChat(
                api_key=EMERGENT_LLM_KEY,
                session_id=f"brief-{cid}-{_dt.now().strftime('%Y%m%d')}",
                system_message="Você é o NEO. Resuma o briefing executivo de um provedor de internet em 4-6 linhas, PT-BR, com insight principal e 1 recomendação. Sem markdown.",
            ).with_model("openai", "gpt-4o-mini")
            ctx = (
                f"Período: últimos {days} dia(s)\n"
                f"Isabella: {isb}\nÁlvaro: {alv}\n"
                f"Pâmela: {cam}\nSecretaria: {sec}\n"
                f"Alertas abertos: {alerts_open} · Agendamentos hoje: {appt_today}"
            )
            ai_summary = await chat.send_message(UserMessage(text=ctx))
        except Exception as e:
            logger.warning("[neo-reports] briefing LLM fail: %s", e)

        # Monta PDF
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4,
                                  leftMargin=18*mm, rightMargin=18*mm,
                                  topMargin=14*mm, bottomMargin=12*mm)
        styles = getSampleStyleSheet()
        story = [
            Paragraph("<b>📋 Briefing Executivo NEO</b>", styles["Title"]),
            Paragraph(
                f"Gerado em <b>{_dt.now().strftime('%d/%m/%Y %H:%M')}</b> · "
                f"Período: últimos <b>{days}</b> dia(s)",
                styles["BodyText"],
            ),
            Spacer(1, 10),
            Paragraph("<b>🤖 Resumo da IA</b>", styles["Heading3"]),
            Paragraph(ai_summary.replace("\n", "<br/>"), styles["BodyText"]),
            Spacer(1, 12),
        ]
        # Tabela consolidada
        rows = [["Agente / Métrica", "Valor"]]
        def _row(label, value):
            rows.append([label, str(value)])
        _row("Isabella · Mensagens IA enviadas", isb.get("messages_outbound_ai", "—"))
        _row("Isabella · % IA", f"{isb.get('ai_share_pct', 0)}%")
        _row("Isabella · Intenções de venda", isb.get("sales_intent_count", "—"))
        _row("Álvaro · Tickets totais", alv.get("tickets_total", "—"))
        _row("Álvaro · Resolvidos", alv.get("tickets_closed", "—"))
        _row("Álvaro · Taxa resolução", f"{alv.get('resolution_rate_pct', 0)}%")
        _row("Pâmela · Mensagens cobrança", cam.get("billing_messages", "—"))
        _row("Pâmela · Recebido (R$)",
             f"R$ {cam.get('received_amount_brl', 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        _row("Secretaria · Interações", sec.get("total_interactions", "—"))
        top_intents = sec.get("top_intents") or []
        if top_intents:
            top_str = ", ".join(
                f"{x.get('intent', '?')}({x.get('count', 0)})" for x in top_intents[:3]
            )
            _row("Secretaria · Top intents", top_str)
        _row("⚠️ Alertas abertos", alerts_open)
        _row("📅 Agendamentos hoje", appt_today)
        t = Table(rows, colWidths=[100*mm, 70*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0d9488")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE", (0,0), (-1,-1), 10),
            ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#e2e8f0")),
            ("ROWBACKGROUNDS", (0,1), (-1,-1),
                [colors.white, colors.HexColor("#f8fafc")]),
        ]))
        story.append(t)
        doc.build(story)
        buf.seek(0)
        body = buf.read()
        fname = f"briefing_neo_{_dt.now().strftime('%Y%m%d_%H%M')}.pdf"
        return body, fname

    raise HTTPException(400, f"report_type não suportado: {report_type}")


async def _deliver_via_whatsapp(phone: str, pdf_bytes: bytes, fname: str,
                                     caption: str) -> Dict[str, Any]:
    """Envia PDF via Baileys sidecar."""
    try:
        from routes.whatsapp_baileys import _sidecar_post_silent
    except Exception as e:
        return {"ok": False, "error": f"sidecar import: {e}"}
    b64 = base64.b64encode(pdf_bytes).decode("ascii")
    # Texto antes do anexo
    await _sidecar_post_silent("/send", {"phone": phone, "text": caption})
    res = await _sidecar_post_silent("/send-document", {
        "phone": phone,
        "document_b64": b64,
        "filename": fname,
        "mimetype": "application/pdf",
    })
    return res or {"ok": False, "error": "no response"}


async def _execute_schedule(schedule: Dict[str, Any],
                                trigger: str = "scheduler") -> Dict[str, Any]:
    """Gera PDF + entrega + grava histórico + atualiza next_run_at."""
    cid = schedule.get("company_id")
    sid = schedule.get("id")
    run_id = f"nrr-{uuid.uuid4().hex[:12]}"
    started = now_iso()
    log: Dict[str, Any] = {
        "id": run_id,
        "company_id": cid,
        "schedule_id": sid,
        "schedule_name": schedule.get("name"),
        "report_type": schedule.get("report_type"),
        "trigger": trigger,
        "at": started,
        "status": "running",
    }
    await db.neo_report_runs.insert_one(dict(log))

    try:
        pdf_bytes, fname = await _build_pdf_bytes(
            schedule["report_type"], cid, schedule.get("params"),
        )
        log["pdf_size_bytes"] = len(pdf_bytes)
        log["filename"] = fname

        delivery = {"ok": False}
        phone = schedule.get("whatsapp_phone")
        if phone:
            caption = (
                f"📊 *{schedule.get('name') or 'Relatório Agendado'}*\n"
                f"Tipo: {schedule.get('report_type')}\n"
                f"Gerado: {datetime.now(BRT_OFFSET).strftime('%d/%m/%Y %H:%M')}"
            )
            delivery = await _deliver_via_whatsapp(phone, pdf_bytes, fname, caption)
            log["delivery_whatsapp"] = delivery

        log["status"] = "success" if (not phone or delivery.get("ok")) else "delivery_failed"
        log["error"] = delivery.get("error") if not delivery.get("ok") else None
    except Exception as e:
        logger.exception("[neo-reports] execute failed: %s", e)
        log["status"] = "error"
        log["error"] = str(e)

    log["finished_at"] = now_iso()
    await db.neo_report_runs.update_one(
        {"id": run_id}, {"$set": {k: v for k, v in log.items() if k != "id"}},
    )

    # Atualiza next_run_at (apenas no dispatcher; em run-manual mantém o agendamento)
    if trigger == "scheduler":
        next_run = _compute_next_run(schedule)
        await db.neo_report_schedules.update_one(
            {"id": sid},
            {"$set": {
                "last_run_at": started,
                "next_run_at": next_run.isoformat(),
            }, "$inc": {"run_count": 1}},
        )

    return log


@router.post("/briefing/activate")
async def activate_daily_briefing(payload: BriefingActivateIn,
                                     user: dict = Depends(require_role("gestor"))):
    """1-click: ativa Briefing Diário NEO às HH:MM para 1+ telefones.

    Cria um schedule por telefone (cada um recebe seu PDF) marcando-os
    com `metadata.is_briefing=true` para fácil identificação.
    """
    cid = _cid(user)
    if not payload.phones:
        raise HTTPException(400, "Informe ao menos 1 telefone (E.164 sem '+')")

    # Remove qualquer briefing antigo da empresa (idempotente — re-ativa)
    await db.neo_report_schedules.delete_many({
        "company_id": cid,
        "report_type": "executive_briefing",
        "metadata.is_briefing": True,
    })

    created: List[Dict[str, Any]] = []
    now = now_iso()
    for phone in payload.phones:
        clean = "".join(c for c in str(phone) if c.isdigit())
        if not clean:
            continue
        data = {
            "name": f"📋 Briefing Diário NEO ({clean[-4:]})",
            "report_type": "executive_briefing",
            "frequency": "daily",
            "hour": payload.hour,
            "minute": payload.minute,
            "whatsapp_phone": clean,
            "active": True,
            "params": {"days": 1},
        }
        next_run = _compute_next_run(data)
        doc = {
            "id": f"nrs-{uuid.uuid4().hex[:12]}",
            "company_id": cid,
            **data,
            "created_at": now,
            "updated_at": now,
            "created_by": user.get("id"),
            "last_run_at": None,
            "next_run_at": next_run.isoformat(),
            "run_count": 0,
            "metadata": {"is_briefing": True, "source": "1click_activate"},
        }
        await db.neo_report_schedules.insert_one(doc)
        doc.pop("_id", None)
        created.append(doc)
    return {"activated": True, "count": len(created), "schedules": created}


@router.get("/briefing/status")
async def briefing_status(user: dict = Depends(require_role("gestor"))):
    """Verifica se o briefing diário está ativo e mostra os telefones."""
    cid = _cid(user)
    items = await db.neo_report_schedules.find({
        "company_id": cid,
        "report_type": "executive_briefing",
        "metadata.is_briefing": True,
    }, {"_id": 0}).to_list(50)
    return {
        "active": any(s.get("active") for s in items),
        "count": len(items),
        "schedules": items,
    }


@router.post("/briefing/deactivate")
async def deactivate_briefing(user: dict = Depends(require_role("gestor"))):
    """Remove o briefing diário."""
    cid = _cid(user)
    r = await db.neo_report_schedules.delete_many({
        "company_id": cid,
        "report_type": "executive_briefing",
        "metadata.is_briefing": True,
    })
    return {"deactivated": True, "removed": r.deleted_count}


async def dispatch_due_schedules_job() -> None:
    """Job APScheduler — roda a cada 5 minutos.

    Pega todos os agendamentos ativos com next_run_at <= agora e executa.
    """
    now = _now_brt().isoformat()
    try:
        cursor = db.neo_report_schedules.find({
            "active": True,
            "next_run_at": {"$lte": now},
        })
        async for sch in cursor:
            sch.pop("_id", None)
            try:
                await _execute_schedule(sch, trigger="scheduler")
            except Exception as e:
                logger.warning("[neo-reports] schedule %s failed: %s",
                                sch.get("id"), e)
    except Exception as e:
        logger.exception("[neo-reports] dispatcher fatal: %s", e)
