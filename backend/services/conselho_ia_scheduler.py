"""
conselho_ia_scheduler.py — Cron do Conselho Estratégico IA (iter215bx)

Roda automaticamente uma vez por dia (default 11:00 UTC = 08:00 BRT).
Para cada empresa com `conselho_ia_settings.cron_enabled=true`, gera
um relatório do tipo "daily", o que dispara em cadeia:
  1. Auditor IA (whitelist auto-corrige inconsistências)
  2. Agente IA decide e executa tools (flag_dunning, etc.)
  3. Se notify_on_action=true, envia WhatsApp pra cada ação.

Idempotente: o endpoint /report já tem cache por (company, period, dia),
então rodar 2× no mesmo dia não duplica.
"""

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from database import db

logger = logging.getLogger("conselho_ia_scheduler")

CHECK_INTERVAL_SECONDS = 60 * 60  # 1h
DEFAULT_HOUR_UTC = 11             # 08:00 BRT (UTC-3)
_worker_task: Optional[asyncio.Task] = None
_last_run_per_company: dict = {}


async def _list_active_companies() -> list:
    """Empresas com cron habilitado nos settings, OU que têm subscribers."""
    cids = set()
    async for s in db.conselho_ia_settings.find(
            {"cron_enabled": True}, {"_id": 0, "company_id": 1}):
        if s.get("company_id"):
            cids.add(s["company_id"])
    return list(cids)


async def _run_for_company(cid: str) -> None:
    """Executa a geração do relatório sem precisar de user/token."""
    from routes.conselho_ia import (
        _collect_overview, _collect_network, _collect_technicians,
        _collect_atendimento, _collect_sales, _collect_universo_ligo,
        _collect_protege, _run_auditor_ia, _agent_plan_and_execute,
        _ai_brief, PERIOD_DAYS, PERIOD_LABEL,
    )
    import uuid

    period = "daily"
    days = PERIOD_DAYS[period]
    overview = await _collect_overview(cid, days)
    network = await _collect_network(cid, days)
    technicians = await _collect_technicians(cid, days)
    atendimento = await _collect_atendimento(cid, days)
    sales = await _collect_sales(cid, days)
    universo = await _collect_universo_ligo(cid, days)
    protege = await _collect_protege(cid, days)

    auditor_result = await _run_auditor_ia(cid, sales)
    if auditor_result.get("total_records_fixed", 0) > 0:
        overview = await _collect_overview(cid, days)
        sales = await _collect_sales(cid, days)
        universo = await _collect_universo_ligo(cid, days)

    agent_result = await _agent_plan_and_execute(
        cid, overview, network, sales)

    ai_brief = await _ai_brief(cid, period, overview, network,
                                 technicians, atendimento, sales,
                                 universo, protege)

    report = {
        "id": f"crp-{uuid.uuid4().hex[:14]}",
        "company_id": cid,
        "period": period,
        "period_label": PERIOD_LABEL[period],
        "day": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "cron_scheduler",
        "modules": {
            "overview": {"title": "Visão Geral", "data": overview,
                          "insight": ai_brief.get("overview_insight") or {}},
            "network": {"title": "Rede", "data": network,
                          "insight": ai_brief.get("network_insight") or {}},
            "technicians": {"title": "Técnicos", "data": technicians,
                              "insight": ai_brief.get("technicians_insight") or {}},
            "atendimento": {"title": "Atendimento", "data": atendimento,
                              "insight": ai_brief.get("atendimento_insight") or {}},
            "sales": {"title": "Vendas", "data": sales,
                        "insight": ai_brief.get("sales_insight") or {}},
            "universo": {"title": "Universo Ligo", "data": universo,
                          "insight": ai_brief.get("universo_insight") or {}},
            "protege": {"title": "Ligo Protege", "data": protege,
                          "insight": ai_brief.get("protege_insight") or {}},
        },
        "parecer_executivo": ai_brief.get("parecer_executivo") or {},
        "auditor": auditor_result,
        "agent": agent_result,
        "from_cache": False,
    }
    await db.conselho_ia_reports.update_one(
        {"company_id": cid, "period": period, "day": report["day"]},
        {"$set": report}, upsert=True)

    # iter215bx — envia resumo executivo no WA (se habilitado)
    await _send_morning_digest(cid, report)
    logger.info("[conselho-ia-cron] OK company=%s fixed=%s actions=%s",
                  cid, auditor_result.get("total_records_fixed", 0),
                  len(agent_result.get("executions") or []))


async def _send_morning_digest(cid: str, report: dict) -> None:
    """Manda o resumo executivo do dia no WhatsApp do operador."""
    cfg = await db.conselho_ia_settings.find_one(
        {"company_id": cid}, {"_id": 0}) or {}
    if not cfg.get("notify_on_action"):
        return
    phone = cfg.get("notify_phone")
    if not phone:
        return
    from services.agent_tools import _send_wa_summary

    overview = (report.get("modules") or {}).get("overview", {})
    ov_data = overview.get("data", {})
    auditor = report.get("auditor") or {}
    agent = report.get("agent") or {}
    parecer = report.get("parecer_executivo") or {}

    fixed = auditor.get("total_records_fixed", 0)
    actions = len(agent.get("executions") or [])
    atencao = (parecer.get("o_que_merece_atencao") or "")[:300]

    text = (
        "*Conselho IA · Resumo da manhã*\n\n"
        f"Clientes ativos: *{ov_data.get('ativos', 0)}*\n"
        f"MRR: *R$ {ov_data.get('mrr_brl', 0):.2f}*\n"
        f"Inadimplência: *{ov_data.get('inadimplencia_pct', 0)}%*\n\n"
        f"Auditor corrigiu: {fixed} registros.\n"
        f"Agente executou: {actions} ações.\n\n"
        f"Merece atenção:\n_{atencao}_\n\n"
        "Veja o relatório completo em Conselho IA."
    )
    # Reusa o sidecar do agent_tools
    await _send_wa_summary(cid, phone, {
        "tool": "morning_digest",
        "status": "executed",
        "justification": text,  # reaproveita o campo
        "result": {},
    })


async def _maybe_send_presidente_briefing(cid: str) -> None:
    """iter219 — Se habilitado nos settings, envia o briefing matinal
    do Presidente IA via WhatsApp."""
    cfg = await db.conselho_ia_settings.find_one(
        {"company_id": cid}, {"_id": 0}) or {}
    if not cfg.get("presidente_briefing_enabled"):
        return
    try:
        from services.presidente_ia_briefing import send_briefing
        await send_briefing(cid)
    except Exception as e:
        logger.exception(
            "[presidente-briefing] cron err %s: %s", cid, e)


async def _worker_loop():
    logger.info("[conselho-ia-cron] worker iniciado")
    # Aguarda 30s no boot pra deixar app subir
    await asyncio.sleep(30)
    while True:
        try:
            now = datetime.now(timezone.utc)
            companies = await _list_active_companies()
            for cid in companies:
                cfg = await db.conselho_ia_settings.find_one(
                    {"company_id": cid}, {"_id": 0}) or {}
                target_hour = int(cfg.get("cron_hour_utc")
                                    or DEFAULT_HOUR_UTC)
                if now.hour != target_hour:
                    continue
                # idempotência: 1× por dia por empresa
                key = f"{cid}:{now.date().isoformat()}"
                if _last_run_per_company.get(cid) == now.date().isoformat():
                    continue
                try:
                    await _run_for_company(cid)
                    # iter219 — Café com a IA do CEO (briefing matinal)
                    await _maybe_send_presidente_briefing(cid)
                    # COMPLIANCE — Auto-sync diário da Equipe IA
                    try:
                        from services.agent_compliance_scheduler import (
                            run_compliance_pass,
                        )
                        await run_compliance_pass(cid)
                    except Exception as e:
                        logger.exception(
                            "[agent-compliance] cron err %s: %s", cid, e)
                    _last_run_per_company[cid] = now.date().isoformat()
                except Exception as e:
                    logger.exception(
                        "[conselho-ia-cron] erro empresa %s: %s", cid, e)
        except Exception as e:
            logger.exception("[conselho-ia-cron] loop err: %s", e)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def start_worker():
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_worker_loop())
    logger.info("[conselho-ia-cron] worker iniciado (check %ds)",
                  CHECK_INTERVAL_SECONDS)


def stop_worker():
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
