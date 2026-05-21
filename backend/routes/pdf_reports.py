"""
pdf_reports.py — Relatórios em PDF da Rede IA e Lousa.

Endpoints:
  - GET /rede-ia/ctos/occupancy/pdf — relatório de ocupação por CTO
  - GET /lousa/tickets/closed/pdf — fechamento de notas (dia ou período)

Usa reportlab (platypus) já presente em requirements.txt.
"""
from __future__ import annotations
import io
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)

from database import db
from core import get_current_user


router = APIRouter(prefix="/api", tags=["pdf-reports"])


def _company_id(user: dict) -> str:
    return user.get("company_id") or "company_demo"


def _now_brt_str() -> str:
    """Horário BRT (UTC-3) legível para cabeçalho do relatório."""
    return (datetime.now(timezone.utc) - timedelta(hours=3))\
        .strftime("%d/%m/%Y %H:%M (BRT)")


def _header_paragraph(styles, title: str, subtitle: str) -> List:
    return [
        Paragraph(f"<b>{title}</b>", styles["title"]),
        Paragraph(subtitle, styles["subtitle"]),
        Spacer(1, 6),
    ]


def _make_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "T", parent=base["Title"], fontSize=16,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=2, alignment=0,
        ),
        "subtitle": ParagraphStyle(
            "S", parent=base["Normal"], fontSize=9,
            textColor=colors.HexColor("#64748b"),
        ),
        "body": ParagraphStyle(
            "B", parent=base["Normal"], fontSize=9,
            textColor=colors.HexColor("#0f172a"),
        ),
        "muted": ParagraphStyle(
            "M", parent=base["Normal"], fontSize=8,
            textColor=colors.HexColor("#64748b"),
        ),
    }


# ============================================================
# 1) RELATÓRIO DE OCUPAÇÃO POR CTO
# ============================================================
@router.get("/rede-ia/ctos/occupancy/pdf")
async def occupancy_pdf(
    threshold: float = Query(0.8, ge=0.0, le=1.0),
    user: dict = Depends(get_current_user),
):
    cid = _company_id(user)
    items = await db.ctos.find(
        {"company_id": cid, "status": "approved"},
        {"_id": 0, "id": 1, "name": 1, "sigla": 1, "vlan": 1,
         "capacity": 1, "ports": 1, "address": 1},
    ).to_list(2000)

    total_ports, total_used, saturated, full = 0, 0, 0, 0
    rows: List[Dict[str, Any]] = []
    for c in items:
        cap = int(c.get("capacity") or 0)
        used = sum(1 for p in (c.get("ports") or []) if p.get("status") == "used")
        pct = (used / cap) if cap else 0.0
        is_full = used >= cap and cap > 0
        is_sat = pct >= threshold
        total_ports += cap
        total_used += used
        if is_full:
            full += 1
        elif is_sat:
            saturated += 1
        rows.append({
            "name": c.get("name") or c["id"],
            "bairro": (c.get("address") or {}).get("bairro") or "—",
            "vlan": c.get("vlan"),
            "used": used, "capacity": cap,
            "percent": round(pct * 100, 1),
            "status": "LOTADA" if is_full else ("SATURADA" if is_sat else "OK"),
        })
    rows.sort(key=lambda x: x["percent"], reverse=True)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                              leftMargin=18*mm, rightMargin=18*mm,
                              topMargin=14*mm, bottomMargin=12*mm)
    styles = _make_styles()
    story: List = []
    story += _header_paragraph(
        styles,
        "📊 Ocupação por CTO",
        f"Gerado em {_now_brt_str()} · Limiar saturação: "
        f"{int(threshold*100)}% · {len(rows)} CTOs aprovadas",
    )

    # KPIs em tabela 4-col
    global_pct = (total_used / total_ports * 100) if total_ports else 0
    kpi_data = [[
        f"CTOs\n{len(rows)}",
        f"Ocupação Global\n{global_pct:.1f}%\n({total_used}/{total_ports} portas)",
        f"Saturadas\n(≥{int(threshold*100)}%)\n{saturated}",
        f"Lotadas\n(100%)\n{full}",
    ]]
    kpi = Table(kpi_data, colWidths=[44*mm]*4, rowHeights=[22*mm])
    kpi.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#0f172a")),
    ]))
    story += [kpi, Spacer(1, 10)]

    # Tabela detalhada
    header = ["CTO", "Bairro", "VLAN", "Usadas", "Cap.", "%", "Status"]
    body = [header] + [
        [r["name"], r["bairro"], str(r["vlan"] or "—"),
         str(r["used"]), str(r["capacity"]),
         f"{r['percent']:.1f}%", r["status"]]
        for r in rows
    ]
    table = Table(body, colWidths=[44*mm, 36*mm, 14*mm, 16*mm, 14*mm, 14*mm, 24*mm],
                    repeatRows=1)
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("ALIGN", (2, 0), (-2, -1), "CENTER"),
        ("ALIGN", (-1, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
            [colors.white, colors.HexColor("#f8fafc")]),
    ]
    for i, r in enumerate(rows, start=1):
        if r["status"] == "LOTADA":
            ts.append(("BACKGROUND", (-1, i), (-1, i), colors.HexColor("#fee2e2")))
            ts.append(("TEXTCOLOR", (-1, i), (-1, i), colors.HexColor("#991b1b")))
        elif r["status"] == "SATURADA":
            ts.append(("BACKGROUND", (-1, i), (-1, i), colors.HexColor("#fef3c7")))
            ts.append(("TEXTCOLOR", (-1, i), (-1, i), colors.HexColor("#92400e")))
    table.setStyle(TableStyle(ts))
    story.append(table)

    doc.build(story)
    buf.seek(0)
    fname = f"ocupacao_ctos_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ============================================================
# 2) RELATÓRIO DE FECHAMENTO DE NOTAS (LOUSA)
# ============================================================
@router.get("/lousa/tickets/closed/pdf")
async def closed_tickets_pdf(
    period: str = Query("today", description="today | yesterday | week | custom"),
    start: Optional[str] = Query(None, description="YYYY-MM-DD (período custom)"),
    end: Optional[str] = Query(None, description="YYYY-MM-DD (período custom)"),
    user: dict = Depends(get_current_user),
):
    cid = _company_id(user)
    # Calcula faixa em UTC (assume BRT = UTC-3)
    now_utc = datetime.now(timezone.utc)
    if period == "custom":
        if not start or not end:
            raise HTTPException(400, "Período custom requer start e end (YYYY-MM-DD).")
        try:
            d_start = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
            d_end = (datetime.fromisoformat(end)
                       + timedelta(days=1)).replace(tzinfo=timezone.utc)
        except Exception:
            raise HTTPException(400, "Datas inválidas. Use YYYY-MM-DD.")
    elif period == "yesterday":
        base = now_utc - timedelta(days=1)
        d_start = base.replace(hour=3, minute=0, second=0, microsecond=0)
        d_end = d_start + timedelta(days=1)
    elif period == "week":
        d_end = now_utc
        d_start = d_end - timedelta(days=7)
    else:  # today
        d_start = now_utc.replace(hour=3, minute=0, second=0, microsecond=0)
        if d_start > now_utc:
            d_start -= timedelta(days=1)
        d_end = d_start + timedelta(days=1)

    rows = await db.tickets.find(
        {
            "company_id": cid,
            "status": {"$in": ["finalizada", "encerrada"]},
            "closed_at": {"$gte": d_start.isoformat(), "$lt": d_end.isoformat()},
        },
        {"_id": 0, "id": 1, "client_snapshot": 1, "type": 1, "priority": 1,
         "closed_at": 1, "closed_by": 1, "outcome": 1, "status": 1,
         "completion_data": 1, "admin_action": 1,
         "assigned_collaborator_id": 1, "scheduled_time": 1},
    ).sort("closed_at", 1).to_list(2000)

    # Mapa de nomes dos colaboradores
    coll_ids = {r.get("closed_by") for r in rows if r.get("closed_by")}
    coll_ids |= {r.get("assigned_collaborator_id")
                  for r in rows if r.get("assigned_collaborator_id")}
    coll_ids.discard(None)
    coll_map: Dict[str, str] = {}
    if coll_ids:
        async for c in db.collaborators.find(
            {"id": {"$in": list(coll_ids)}}, {"_id": 0, "id": 1, "name": 1},
        ):
            coll_map[c["id"]] = c.get("name", "—")

    # Agregações
    types_count: Dict[str, int] = {}
    techs_count: Dict[str, int] = {}
    internal_close_count = 0
    for r in rows:
        t = r.get("type") or "—"
        types_count[t] = types_count.get(t, 0) + 1
        tn = coll_map.get(r.get("closed_by")) \
            or coll_map.get(r.get("assigned_collaborator_id")) or "—"
        techs_count[tn] = techs_count.get(tn, 0) + 1
        if r.get("admin_action") == "encerrar":
            internal_close_count += 1

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                              leftMargin=12*mm, rightMargin=12*mm,
                              topMargin=12*mm, bottomMargin=12*mm)
    styles = _make_styles()
    story: List = []

    period_lbl = {
        "today": "Hoje", "yesterday": "Ontem",
        "week": "Últimos 7 dias", "custom": f"{start} → {end}",
    }.get(period, period)
    story += _header_paragraph(
        styles,
        "📋 Fechamento de Notas (Lousa)",
        f"Gerado em {_now_brt_str()} · Período: {period_lbl} · "
        f"Total: {len(rows)} notas",
    )

    # KPIs
    kpi_data = [[
        f"Total\n{len(rows)}",
        f"Fechamento interno\n(gestor)\n{internal_close_count}",
        f"Instalações\n{types_count.get('instalacao', 0)}",
        f"Reparos\n{types_count.get('reparo', 0)}",
        f"Retiradas\n{types_count.get('retirada', 0)}",
    ]]
    kpi = Table(kpi_data, colWidths=[52*mm]*5, rowHeights=[20*mm])
    kpi.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
    ]))
    story += [kpi, Spacer(1, 8)]

    if rows:
        # Agrupa por técnico
        from collections import defaultdict
        by_tech: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in rows:
            tech_name = (coll_map.get(r.get("closed_by"))
                          or coll_map.get(r.get("assigned_collaborator_id"))
                          or "— Sem técnico —")
            by_tech[tech_name].append(r)

        # Ordena técnicos por nome
        for tech_name in sorted(by_tech.keys()):
            tnotes = by_tech[tech_name]
            # Cabeçalho do técnico
            story.append(Paragraph(
                f"<b>👷 {tech_name}</b> &nbsp;·&nbsp; "
                f"<font color='#64748b'>{len(tnotes)} nota{'s' if len(tnotes) > 1 else ''} finalizada{'s' if len(tnotes) > 1 else ''}</font>",
                styles["body"]))
            story.append(Spacer(1, 4))

            # Tabela detalhada das notas deste técnico
            header = ["#", "Fechada em", "Cliente", "Tipo", "Sinal",
                       "CTO · Porta", "O que foi feito", "Origem"]
            body = [header]
            for i, r in enumerate(tnotes, 1):
                cs = r.get("client_snapshot") or {}
                cd = r.get("completion_data") or {}
                closed_at = (r.get("closed_at") or "")[:16].replace("T", " ")

                sinal = cd.get("sinal")
                sinal_str = f"{sinal:.1f} dBm" if isinstance(sinal, (int, float)) else "—"

                cto_str = "—"
                if cd.get("cto_name"):
                    cto_str = f"{cd['cto_name'][:18]}"
                    if cd.get("cto_port_number"):
                        cto_str += f" · P{cd['cto_port_number']}"
                    if cd.get("cto_splitter"):
                        cto_str += f"\n{cd['cto_splitter']}"
                    if cd.get("cto_vlan"):
                        cto_str += f" · VLAN {cd['cto_vlan']}"

                # Monta "o que foi feito" combinando vários campos
                done_parts: List[str] = []
                if cd.get("ont"):
                    done_parts.append(f"<b>ONT:</b> {cd['ont']}")
                if cd.get("drop"):
                    done_parts.append(f"<b>Drop:</b> {cd['drop']}m")
                if cd.get("esticador"):
                    done_parts.append(f"<b>Est:</b> {cd['esticador']}")
                if cd.get("conectores"):
                    done_parts.append(f"<b>Con:</b> {cd['conectores']}")
                if cd.get("backbone"):
                    done_parts.append(f"<b>Bb:</b> {cd['backbone']}m")
                fotos = cd.get("fotos") or []
                fotos_count = len([f for f in fotos if f])
                if fotos_count:
                    done_parts.append(f"📷 {fotos_count} foto{'s' if fotos_count > 1 else ''}")
                ping = (cd.get("ping_summary") or "").strip()
                if ping:
                    done_parts.append(f"<b>Ping:</b> {ping[:60]}")
                obs = (cd.get("observacoes") or "").strip()
                if obs:
                    done_parts.append(f"<b>Obs:</b> {obs[:140]}")
                outcome = r.get("outcome")
                if outcome:
                    done_parts.append(f"<b>Result:</b> {outcome[:30]}")
                if not done_parts:
                    done_parts.append("—")

                origem = "🛡 Gestor" if r.get("admin_action") == "encerrar" else "👷 Técnico"

                body.append([
                    str(i), closed_at, (cs.get("name") or "—")[:30],
                    (r.get("type") or "—")[:14],
                    sinal_str,
                    cto_str,
                    Paragraph(" · ".join(done_parts), styles["body"]),
                    origem,
                ])
            table = Table(
                body,
                colWidths=[7*mm, 24*mm, 38*mm, 18*mm, 16*mm, 28*mm, 100*mm, 20*mm],
                repeatRows=1,
            )
            ts = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (4, 0), (4, -1), "CENTER"),
                ("ALIGN", (7, 0), (7, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                    [colors.white, colors.HexColor("#f8fafc")]),
            ]
            for i, r in enumerate(tnotes, start=1):
                if r.get("admin_action") == "encerrar":
                    ts.append(("BACKGROUND", (-1, i), (-1, i),
                              colors.HexColor("#fef3c7")))
                    ts.append(("TEXTCOLOR", (-1, i), (-1, i),
                              colors.HexColor("#92400e")))
            table.setStyle(TableStyle(ts))
            story.append(table)
            story.append(Spacer(1, 10))
    else:
        story.append(Paragraph("Nenhuma nota fechada no período selecionado.",
                                 styles["body"]))

    doc.build(story)
    buf.seek(0)
    fname = f"fechamento_notas_{period}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
