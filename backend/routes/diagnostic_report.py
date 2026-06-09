"""
diagnostic_report.py — Relatório de Diagnóstico Completo do SmartProv
(16 seções, dados brutos, sem LLM)

Camada de inspeção que percorre todo o banco e devolve um snapshot
estruturado da plataforma. NÃO executa correções, NÃO chama LLM,
apenas LÊ e CONSOLIDA contagens/listas das principais collections.

Endpoints:
    GET /api/conselho-ia/diagnostic-report
    GET /api/conselho-ia/diagnostic-report.pdf  → download PDF
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from core import DEMO_COMPANY_ID, get_current_user
from database import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/conselho-ia", tags=["conselho-ia"])


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


def _base_q(cid: str) -> Dict[str, Any]:
    if cid and cid != DEMO_COMPANY_ID:
        return {"company_id": cid}
    return {}


async def _count(col: str, cols: List[str],
                  q: Dict[str, Any] | None = None) -> int:
    """Conta documentos respeitando se a collection existe."""
    if col not in cols:
        return 0
    try:
        return await db[col].count_documents(q or {})
    except Exception:
        return 0


# ─────────────────── 1. Executive Summary ───────────────────
async def _section_executive_summary(cid: str, cols: List[str],
                                       days: int) -> Dict[str, Any]:
    bq = _base_q(cid)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    total = await _count("subscribers", cols, bq)
    ativos = await _count("subscribers", cols,
                            {**bq, "status": {"$in": ["ATIVO", "ATIVA"]}})
    inadimplentes = await _count("subscribers", cols, {
        **bq, "financial_status":
            {"$regex": "inadimp|atrasad", "$options": "i"}})
    cancelados = await _count("subscribers", cols, {
        **bq, "status": {"$regex": "CANCEL", "$options": "i"}})
    novos_periodo = await _count("subscribers", cols, {
        **bq, "installation_date": {"$gte": cutoff}})

    mrr = 0.0
    try:
        agg = await db.subscribers.aggregate([
            {"$match": {**bq, "status": {"$in": ["ATIVO", "ATIVA"]}}},
            {"$group": {"_id": None,
                          "mrr": {"$sum": {"$ifNull": [
                              "$plan_price_brl", 0]}}}},
        ]).to_list(1)
        mrr = round(float((agg[0] if agg else {}).get("mrr", 0)), 2)
    except Exception:
        pass

    churn_pct = round(100 * cancelados / total, 2) if total else 0.0
    inad_pct = round(100 * inadimplentes / max(ativos, 1), 2)
    ticket = round(mrr / ativos, 2) if ativos else 0.0

    return {
        "total_clientes": total,
        "clientes_ativos": ativos,
        "clientes_inadimplentes": inadimplentes,
        "clientes_cancelados": cancelados,
        "novos_no_periodo": novos_periodo,
        "mrr_brl": mrr,
        "ticket_medio_brl": ticket,
        "churn_pct": churn_pct,
        "inadimplencia_pct": inad_pct,
        "total_collections": len(cols),
        "periodo_dias": days,
    }


# ─────────────────── 2. Module Map ───────────────────
def _section_module_map(cols: List[str]) -> Dict[str, Any]:
    """Mapa de módulos do SmartProv com presença/ausência das collections."""
    catalog = {
        "BSS — Billing": [
            "subscribers", "plans", "invoices", "subscriber_invoices",
            "billing_runs", "billing_dunning_events", "billing_dunning_rules",
            "payment_transactions", "contracts",
        ],
        "OSS — Rede": [
            "ctos", "cto_ports", "smartolt_onus", "smartolt_config",
            "smartolt_actions", "radius_nas", "radius_sessions",
            "radius_logs", "network_cables", "network_ces",
            "network_outages", "ligo_map_assets", "ligo_map_cables",
        ],
        "OSS — Operação": [
            "tickets", "ticket_logs", "preventive_os_runs",
            "appointments", "lousa_logs", "lousa_alerts",
        ],
        "IA — Conselho": [
            "conselho_ia_reports", "conselho_ia_audit_log",
            "conselho_ia_agent_actions", "conselho_ia_settings",
            "motor_ia_config", "motor_ia_usage",
            "ai_corrections", "ai_insights",
        ],
        "IA — Assistentes": [
            "isabella_config", "isabella_prompt_fragments",
            "alvaro_analyses", "alvaro_reports",
            "aihub_agents", "aihub_messages", "aihub_calls",
            "neo_chat_messages", "neo_sessions",
        ],
        "IA — Rede": [
            "rede_ia_analyses", "rede_ia_history", "rede_ia_settings",
            "cto_audits", "cto_photo_analyses", "cto_validations",
        ],
        "Fleet / GPS": [
            "fleet_vehicles", "fleet_positions", "fleet_events",
            "fleet_geofences", "fleet_geofence_state", "fleet_commands",
            "fleet_inspections", "fleet_fuel_entries",
            "fleet_portal_users",
        ],
        "Security Home": [
            "security_sites", "security_sensors", "security_alarms",
            "security_arm_states", "security_panel_commands",
            "security_portal_users", "security_tenants",
        ],
        "Clube Ligo / Indicações": [
            "referrals", "referral_payouts", "referral_rewards",
            "referral_streak_bonuses", "referral_goal_bonuses",
            "indicacao_credits", "indicacao_leads",
        ],
        "Parcerias QR": [
            "parcerias_partners", "parcerias_promotions",
            "parcerias_redemptions", "parcerias_scan_log",
            "parcerias_partner_users", "parcerias_partner_applications",
        ],
        "WhatsApp / Mensageria": [
            "wa_conversations", "wa_auth_state", "wa_autoreply_config",
            "whatsapp_channels", "whatsapp_log",
            "whatsapp_meta_creds", "whatsapp_twilio_creds",
            "mass_campaigns", "mass_messages_jobs", "mass_recipients",
            "bulk_reply_campaigns", "bulk_reply_recipients",
        ],
        "WiFi / Hotspot": [
            "wifi_venues", "wifi_campaigns", "wifi_sessions",
            "wifi_visitors", "wifi_change_logs", "wifi_read_logs",
        ],
        "Financeiro Interno": [
            "fin_bills_payable", "fin_cash_accounts", "fin_cash_movements",
            "fin_categories", "fin_filiais", "fin_payment_methods",
            "fin_suppliers",
        ],
        "Stok — Almoxarifado": [
            "stok_stock", "stok_history", "stok_onts", "stok_services",
            "stok_batch_log", "stok_balanco_sessions",
            "stok_pending_transfers",
        ],
        "Vendas / CRM": [
            "sales_leads", "site_leads", "sales_funnel_log",
            "pre_subscribers",
        ],
        "Auth / Usuários": [
            "users", "client_portal_users", "companies",
            "collaborators", "collaborator_sessions",
            "auth_recovery_log", "login_attempts", "impersonation_log",
        ],
    }
    modules = []
    for name, expected in catalog.items():
        present = [c for c in expected if c in cols]
        missing = [c for c in expected if c not in cols]
        modules.append({
            "modulo": name,
            "collections_esperadas": len(expected),
            "collections_presentes": len(present),
            "ativo": len(present) > 0,
            "saude_pct": round(100 * len(present) / len(expected), 1),
            "ausentes": missing,
        })
    return {
        "total_modulos_mapeados": len(modules),
        "modulos_ativos": sum(1 for m in modules if m["ativo"]),
        "modulos": modules,
    }


# ─────────────────── 3. AI Engine ───────────────────
async def _section_ai_engine(cid: str, cols: List[str],
                               days: int) -> Dict[str, Any]:
    bq = _base_q(cid)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    cfg = await db.motor_ia_config.find_one(
        {**bq}, {"_id": 0}) if "motor_ia_config" in cols else None

    # Uso por agente nos últimos N dias
    usage_by_agent = []
    try:
        if "motor_ia_usage" in cols:
            agg = await db.motor_ia_usage.aggregate([
                {"$match": {**bq, "created_at": {"$gte": cutoff}}},
                {"$group": {
                    "_id": "$agent",
                    "qtd": {"$sum": 1},
                    "tokens_in": {"$sum": {"$ifNull": [
                        "$tokens_in", 0]}},
                    "tokens_out": {"$sum": {"$ifNull": [
                        "$tokens_out", 0]}},
                    "cost_usd": {"$sum": {"$ifNull": [
                        "$cost_usd", 0]}},
                }},
                {"$sort": {"qtd": -1}},
                {"$limit": 30},
            ]).to_list(30)
            usage_by_agent = [{
                "agente": r["_id"] or "—",
                "requisicoes": r["qtd"],
                "tokens_in": int(r.get("tokens_in") or 0),
                "tokens_out": int(r.get("tokens_out") or 0),
                "custo_usd": round(float(r.get("cost_usd") or 0), 4),
            } for r in agg]
    except Exception:
        pass

    # Total mensagens / sessões agentes
    isabella_msgs = await _count("isabella_sessions", cols,
                                   {**bq,
                                    "created_at": {"$gte": cutoff}})
    alvaro_an = await _count("alvaro_analyses", cols,
                               {**bq, "created_at": {"$gte": cutoff}})
    neo_msgs = await _count("neo_chat_messages", cols,
                              {**bq, "created_at": {"$gte": cutoff}})
    rede_analyses = await _count("rede_ia_analyses", cols,
                                   {**bq, "created_at": {"$gte": cutoff}})

    return {
        "configuracao": {
            "provider": (cfg or {}).get("provider"),
            "model": (cfg or {}).get("model"),
            "fallback_provider": (cfg or {}).get("fallback_provider"),
            "fallback_model": (cfg or {}).get("fallback_model"),
        } if cfg else {"configurado": False},
        "uso_por_agente": usage_by_agent,
        "total_requisicoes_periodo": sum(
            u["requisicoes"] for u in usage_by_agent),
        "custo_total_usd": round(sum(
            u["custo_usd"] for u in usage_by_agent), 4),
        "isabella_sessoes": isabella_msgs,
        "alvaro_analises": alvaro_an,
        "neo_chat_msgs": neo_msgs,
        "rede_ia_analises": rede_analyses,
    }


# ─────────────────── 4. Database ───────────────────
async def _section_database(cid: str, cols: List[str]) -> Dict[str, Any]:
    """Lista todas as collections com contagem global e contagem do cid."""
    bq = _base_q(cid)
    summary = []
    for c in sorted(cols):
        try:
            total = await db[c].count_documents({})
            cid_count = None
            if bq:
                try:
                    cid_count = await db[c].count_documents(bq)
                except Exception:
                    cid_count = None
            summary.append({
                "collection": c,
                "total_geral": total,
                "total_empresa": cid_count,
            })
        except Exception:
            continue
    top = sorted(summary, key=lambda x: x["total_geral"] or 0,
                  reverse=True)[:20]
    return {
        "total_collections": len(cols),
        "top_20_volume": top,
        "todas_collections": summary,
    }


# ─────────────────── 5. Operations ───────────────────
async def _section_operations(cid: str, cols: List[str],
                                days: int) -> Dict[str, Any]:
    bq = _base_q(cid)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    tickets_total = await _count("tickets", cols, bq)
    tickets_periodo = await _count("tickets", cols,
                                     {**bq, "created_at": {"$gte": cutoff}})
    tickets_abertos = await _count("tickets", cols,
                                     {**bq, "status":
                                        {"$nin": ["closed", "resolved",
                                                    "FECHADO", "RESOLVIDO"]}})
    preventive = await _count("preventive_os_runs", cols, bq)
    appts = await _count("appointments", cols,
                           {**bq, "created_at": {"$gte": cutoff}})

    # por status
    by_status = []
    try:
        if "tickets" in cols:
            agg = await db.tickets.aggregate([
                {"$match": bq},
                {"$group": {"_id": "$status", "qtd": {"$sum": 1}}},
                {"$sort": {"qtd": -1}}, {"$limit": 20},
            ]).to_list(20)
            by_status = [{"status": r["_id"] or "—",
                            "qtd": r["qtd"]} for r in agg]
    except Exception:
        pass

    return {
        "tickets_total": tickets_total,
        "tickets_periodo": tickets_periodo,
        "tickets_abertos": tickets_abertos,
        "preventive_os_runs": preventive,
        "agendamentos_periodo": appts,
        "tickets_por_status": by_status,
    }


# ─────────────────── 6. Network ───────────────────
async def _section_network(cid: str, cols: List[str]) -> Dict[str, Any]:
    bq = _base_q(cid)
    ctos = await _count("ctos", cols, bq)
    smartolt_onus = await _count("smartolt_onus", cols, bq)
    radius_sessions = await _count("radius_sessions", cols, bq)
    cables = await _count("network_cables", cols, bq)
    ligo_assets = await _count("ligo_map_assets", cols, bq)
    outages = await _count("network_outages", cols, bq)

    onus_offline = await _count("subscribers", cols, {
        **bq, "olt_id": {"$exists": True, "$ne": None},
        "$or": [
            {"signal_dbm": {"$lte": -28}},
            {"status_onu": {"$regex": "offline|los|lof",
                                "$options": "i"}},
        ]})

    avg_signal = None
    try:
        agg = await db.subscribers.aggregate([
            {"$match": {**bq,
                          "signal_dbm": {"$exists": True, "$ne": None,
                                            "$gte": -40, "$lte": -1}}},
            {"$group": {"_id": None,
                           "avg": {"$avg": "$signal_dbm"}}},
        ]).to_list(1)
        avg_signal = round(float(
            (agg[0] if agg else {}).get("avg", 0) or 0), 2)
    except Exception:
        pass

    # CTOs com saturação >85%
    saturadas = []
    try:
        agg = await db.subscribers.aggregate([
            {"$match": {**bq, "cto_id": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": "$cto_id", "qtd": {"$sum": 1}}},
            {"$sort": {"qtd": -1}}, {"$limit": 30},
        ]).to_list(30)
        cto_ids = [r["_id"] for r in agg]
        cto_meta = {c["id"]: c async for c in db.ctos.find(
            {"id": {"$in": cto_ids}},
            {"_id": 0, "id": 1, "label": 1, "capacity": 1})}
        for r in agg:
            meta = cto_meta.get(r["_id"], {})
            cap = meta.get("capacity") or 16
            pct = round(100 * r["qtd"] / cap, 1) if cap else 0
            if pct >= 85:
                saturadas.append({
                    "cto_id": r["_id"],
                    "label": meta.get("label", r["_id"]),
                    "clientes": r["qtd"],
                    "capacidade": cap,
                    "saturacao_pct": pct,
                })
    except Exception:
        pass

    return {
        "ctos": ctos,
        "smartolt_onus": smartolt_onus,
        "radius_sessions": radius_sessions,
        "network_cables": cables,
        "ligo_map_assets": ligo_assets,
        "network_outages": outages,
        "onus_potencia_baixa": onus_offline,
        "potencia_media_dbm": avg_signal,
        "ctos_saturadas": saturadas,
    }


# ─────────────────── 7. GPS / Fleet ───────────────────
async def _section_gps_fleet(cid: str, cols: List[str],
                                days: int) -> Dict[str, Any]:
    bq = _base_q(cid)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    vehicles = await _count("fleet_vehicles", cols, bq)
    events_periodo = await _count("fleet_events", cols,
                                    {**bq, "created_at": {"$gte": cutoff}})
    geofences = await _count("fleet_geofences", cols, bq)
    fuel = await _count("fleet_fuel_entries", cols, bq)
    inspections = await _count("fleet_inspections", cols, bq)
    commands = await _count("fleet_commands", cols,
                              {**bq, "created_at": {"$gte": cutoff}})
    positions = await _count("fleet_positions", cols, bq)

    return {
        "veiculos": vehicles,
        "eventos_periodo": events_periodo,
        "geofences": geofences,
        "abastecimentos": fuel,
        "checklists_inspecao": inspections,
        "comandos_periodo": commands,
        "posicoes_armazenadas": positions,
    }


# ─────────────────── 8. Security ───────────────────
async def _section_security(cid: str, cols: List[str],
                              days: int) -> Dict[str, Any]:
    bq = _base_q(cid)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    sites = await _count("security_sites", cols, bq)
    sensors = await _count("security_sensors", cols, bq)
    alarms_total = await _count("security_alarms", cols, bq)
    alarms_periodo = await _count("security_alarms", cols,
                                    {**bq, "created_at": {"$gte": cutoff}})
    armed = await _count("security_arm_states", cols, bq)
    commands = await _count("security_panel_commands", cols,
                              {**bq, "created_at": {"$gte": cutoff}})

    return {
        "sites": sites,
        "sensores": sensors,
        "alarmes_total": alarms_total,
        "alarmes_periodo": alarms_periodo,
        "arm_states": armed,
        "comandos_painel_periodo": commands,
    }


# ─────────────────── 9. Financials ───────────────────
async def _section_financials(cid: str, cols: List[str],
                                 days: int) -> Dict[str, Any]:
    bq = _base_q(cid)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    invoices = await _count("invoices", cols, bq)
    sub_invoices = await _count("subscriber_invoices", cols, bq)
    invoices_open = await _count("subscriber_invoices", cols,
                                   {**bq, "status":
                                      {"$regex": "open|pend|aberta|emit",
                                       "$options": "i"}})
    invoices_paid_periodo = await _count("payment_transactions", cols,
                                            {**bq,
                                              "created_at":
                                                {"$gte": cutoff}})
    bills_payable = await _count("fin_bills_payable", cols, bq)
    bills_open = await _count("fin_bills_payable", cols,
                                 {**bq, "status":
                                    {"$regex": "open|pend|aberta",
                                       "$options": "i"}})
    cash_movs = await _count("fin_cash_movements", cols,
                                {**bq, "created_at": {"$gte": cutoff}})

    # Receita do período (paid)
    receita_periodo = 0.0
    try:
        if "payment_transactions" in cols:
            agg = await db.payment_transactions.aggregate([
                {"$match": {**bq,
                              "created_at": {"$gte": cutoff},
                              "status": {"$regex": "paid|confirm|conclu",
                                             "$options": "i"}}},
                {"$group": {"_id": None,
                               "v": {"$sum": {"$ifNull":
                                                ["$amount_brl", 0]}}}},
            ]).to_list(1)
            receita_periodo = round(float(
                (agg[0] if agg else {}).get("v", 0) or 0), 2)
    except Exception:
        pass

    return {
        "invoices_total": invoices,
        "subscriber_invoices_total": sub_invoices,
        "subscriber_invoices_em_aberto": invoices_open,
        "transacoes_pagamento_periodo": invoices_paid_periodo,
        "receita_periodo_brl": receita_periodo,
        "contas_pagar_total": bills_payable,
        "contas_pagar_abertas": bills_open,
        "movimentos_caixa_periodo": cash_movs,
    }


# ─────────────────── 10. KPIs ───────────────────
async def _section_kpis(cid: str, cols: List[str],
                          days: int) -> Dict[str, Any]:
    bq = _base_q(cid)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    total = await _count("subscribers", cols, bq)
    ativos = await _count("subscribers", cols,
                            {**bq, "status": {"$in": ["ATIVO", "ATIVA"]}})
    cancel_periodo = await _count("subscribers", cols, {
        **bq, "status": {"$regex": "CANCEL", "$options": "i"},
        "updated_at": {"$gte": cutoff}})
    novos = await _count("subscribers", cols,
                            {**bq, "installation_date": {"$gte": cutoff}})
    inad = await _count("subscribers", cols, {
        **bq, "financial_status":
            {"$regex": "inadimp|atrasad", "$options": "i"}})

    # Leads
    leads = await _count("sales_leads", cols,
                            {**bq, "created_at": {"$gte": cutoff}})
    site_leads = await _count("site_leads", cols,
                                  {**bq, "created_at": {"$gte": cutoff}})
    indic_leads = await _count("indicacao_leads", cols,
                                 {**bq,
                                    "created_at": {"$gte": cutoff}})
    leads_total = leads + site_leads + indic_leads
    conv = round(100 * novos / leads_total, 1) if leads_total else 0.0

    churn_periodo_pct = round(100 * cancel_periodo / max(total, 1), 2)
    inad_pct = round(100 * inad / max(ativos, 1), 2)

    return {
        "churn_periodo_pct": churn_periodo_pct,
        "inadimplencia_pct": inad_pct,
        "novos_clientes_periodo": novos,
        "cancelamentos_periodo": cancel_periodo,
        "leads_total_periodo": leads_total,
        "leads_breakdown": {"sales": leads, "site": site_leads,
                              "indicacao": indic_leads},
        "taxa_conversao_pct": conv,
    }


# ─────────────────── 11. Automations ───────────────────
async def _section_automations(cid: str, cols: List[str]) -> Dict[str, Any]:
    """Status dos crons/schedulers conhecidos."""
    bq = _base_q(cid)

    conselho_settings = await db.conselho_ia_settings.find_one(
        {**bq}, {"_id": 0}) if "conselho_ia_settings" in cols else None

    crons = [
        {"nome": "Conselho IA (relatório diário)",
         "ativo": bool((conselho_settings or {}).get("cron_enabled")),
         "hora_utc": (conselho_settings or {}).get("cron_hour_utc"),
         "fonte": "conselho_ia_settings"},
        {"nome": "Disparo de boletos",
         "ativo": "disparo_boleto_runs" in cols,
         "fonte": "disparo_boleto_runs"},
        {"nome": "Régua de cobrança (dunning)",
         "ativo": "billing_dunning_events" in cols,
         "fonte": "billing_dunning_events"},
        {"nome": "Reajustes automáticos",
         "ativo": "plan_adjustments_scheduled" in cols,
         "fonte": "plan_adjustments_scheduled"},
        {"nome": "Briefing churn IA",
         "ativo": "churn_briefing_schedule" in cols,
         "fonte": "churn_briefing_schedule"},
        {"nome": "Backups Google Drive",
         "ativo": "drive_backups" in cols,
         "fonte": "drive_backups"},
        {"nome": "Preventiva de rede (OS)",
         "ativo": "preventive_os_runs" in cols,
         "fonte": "preventive_os_runs"},
    ]

    # Últimas execuções relevantes
    last_runs = {}
    try:
        if "billing_runs" in cols:
            last = await db.billing_runs.find_one(
                {**bq}, {"_id": 0}, sort=[("created_at", -1)])
            if last:
                last_runs["billing_runs"] = last.get("created_at")
        if "drive_backups" in cols:
            last = await db.drive_backups.find_one(
                {**bq}, {"_id": 0}, sort=[("created_at", -1)])
            if last:
                last_runs["drive_backups"] = last.get("created_at")
        if "conselho_ia_reports" in cols:
            last = await db.conselho_ia_reports.find_one(
                {**bq}, {"_id": 0}, sort=[("generated_at", -1)])
            if last:
                last_runs["conselho_ia_reports"] = last.get("generated_at")
    except Exception:
        pass

    return {
        "automacoes_conhecidas": crons,
        "automacoes_ativas": sum(1 for c in crons if c["ativo"]),
        "ultimas_execucoes": last_runs,
    }


# ─────────────────── 12. Integrations ───────────────────
async def _section_integrations(cid: str, cols: List[str]) -> Dict[str, Any]:
    """Status best-effort das integrações externas."""
    bq = _base_q(cid)

    async def has(col: str, q: Dict[str, Any] | None = None) -> bool:
        if col not in cols:
            return False
        try:
            return (await db[col].count_documents(q or {})) > 0
        except Exception:
            return False

    integrations = [
        {"nome": "OpenRouter / Motor IA (LLM)",
         "ativo": await has("motor_ia_config", bq),
         "evidencia": "motor_ia_config"},
        {"nome": "WhatsApp Baileys (Channels)",
         "ativo": await has("whatsapp_channels", bq),
         "evidencia": "whatsapp_channels"},
        {"nome": "WhatsApp Cloud (Meta)",
         "ativo": await has("whatsapp_meta_creds", bq),
         "evidencia": "whatsapp_meta_creds"},
        {"nome": "Twilio WhatsApp",
         "ativo": await has("whatsapp_twilio_creds", bq),
         "evidencia": "whatsapp_twilio_creds"},
        {"nome": "Atlaz (legado)",
         "ativo": await has("atlaz_config", bq),
         "evidencia": "atlaz_config"},
        {"nome": "SmartOLT",
         "ativo": await has("smartolt_config", bq),
         "evidencia": "smartolt_config"},
        {"nome": "Sicoob (imports bancários)",
         "ativo": await has("bank_import_history", bq),
         "evidencia": "bank_import_history"},
        {"nome": "Google Drive (backups)",
         "ativo": await has("drive_credentials", bq),
         "evidencia": "drive_credentials"},
        {"nome": "Asaas — Contas a Pagar",
         "ativo": False, "evidencia": "(não configurado — mocked)"},
        {"nome": "NFCom (Anatel)",
         "ativo": False, "evidencia": "(módulo P2 do roadmap)"},
    ]
    return {
        "integracoes": integrations,
        "ativas": sum(1 for i in integrations if i["ativo"]),
        "inativas": sum(1 for i in integrations if not i["ativo"]),
    }


# ─────────────────── 13. Roadmap / Pending ───────────────────
async def _section_roadmap(cid: str, cols: List[str]) -> Dict[str, Any]:
    bq = _base_q(cid)
    audit_pending = await _count("conselho_ia_audit_log", cols,
                                    {**bq, "status": "pending"})
    audit_applied = await _count("conselho_ia_audit_log", cols,
                                    {**bq, "status": "applied"})
    audit_rejected = await _count("conselho_ia_audit_log", cols,
                                     {**bq, "status": "rejected"})

    agent_executed = await _count("conselho_ia_agent_actions", cols,
                                     {**bq, "status": "executed"})
    agent_pending = await _count("conselho_ia_agent_actions", cols,
                                    {**bq, "status": "pending"})
    agent_failed = await _count("conselho_ia_agent_actions", cols,
                                   {**bq, "status": "failed"})

    pending_unblock = await _count("subscriber_unblock_requests", cols,
                                      {**bq, "status":
                                         {"$in": ["pending", "PENDENTE"]}})

    # últimas ações pendentes (até 10)
    last_pending = []
    try:
        if "conselho_ia_audit_log" in cols:
            cur = db.conselho_ia_audit_log.find(
                {**bq, "status": "pending"},
                {"_id": 0, "id": 1, "action": 1, "notes": 1,
                 "created_at": 1}
            ).sort("created_at", -1).limit(10)
            last_pending = await cur.to_list(10)
    except Exception:
        pass

    return {
        "auditor_pendentes": audit_pending,
        "auditor_aplicadas": audit_applied,
        "auditor_rejeitadas": audit_rejected,
        "agente_executadas": agent_executed,
        "agente_pendentes": agent_pending,
        "agente_falhas": agent_failed,
        "solicitacoes_desbloqueio_pendentes": pending_unblock,
        "ultimas_acoes_pendentes": last_pending,
    }


# ─────────────────── 14. AI Auto-analysis ───────────────────
async def _section_ai_auto_analysis(cid: str, cols: List[str],
                                       days: int) -> Dict[str, Any]:
    bq = _base_q(cid)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    audit_periodo = await _count("conselho_ia_audit_log", cols,
                                    {**bq, "created_at": {"$gte": cutoff}})
    agent_periodo = await _count("conselho_ia_agent_actions", cols,
                                    {**bq, "created_at": {"$gte": cutoff}})

    # Agrupa auditor por action
    by_action = []
    try:
        if "conselho_ia_audit_log" in cols:
            agg = await db.conselho_ia_audit_log.aggregate([
                {"$match": {**bq, "created_at": {"$gte": cutoff}}},
                {"$group": {"_id": "$action",
                              "qtd": {"$sum": 1},
                              "applied": {"$sum": {"$ifNull": [
                                  "$applied", 0]}}}},
                {"$sort": {"qtd": -1}}, {"$limit": 30},
            ]).to_list(30)
            by_action = [{"acao": r["_id"] or "—",
                            "execucoes": r["qtd"],
                            "registros_corrigidos": int(r.get("applied") or 0)}
                          for r in agg]
    except Exception:
        pass

    # Agrupa agente por tool
    by_tool = []
    try:
        if "conselho_ia_agent_actions" in cols:
            agg = await db.conselho_ia_agent_actions.aggregate([
                {"$match": {**bq, "created_at": {"$gte": cutoff}}},
                {"$group": {"_id": "$tool",
                              "qtd": {"$sum": 1}}},
                {"$sort": {"qtd": -1}}, {"$limit": 30},
            ]).to_list(30)
            by_tool = [{"tool": r["_id"] or "—", "qtd": r["qtd"]}
                        for r in agg]
    except Exception:
        pass

    # Último relatório do Conselho
    last_report = None
    try:
        if "conselho_ia_reports" in cols:
            last_report = await db.conselho_ia_reports.find_one(
                {**bq}, {"_id": 0, "id": 1, "period": 1, "day": 1,
                         "generated_at": 1},
                sort=[("generated_at", -1)])
    except Exception:
        pass

    return {
        "auditor_execucoes_periodo": audit_periodo,
        "agente_execucoes_periodo": agent_periodo,
        "auditor_por_acao": by_action,
        "agente_por_ferramenta": by_tool,
        "ultimo_relatorio_conselho": last_report,
    }


# ─────────────────── 15. Executive Review ───────────────────
def _section_executive_review(summary: Dict[str, Any],
                                ops: Dict[str, Any],
                                net: Dict[str, Any],
                                fin: Dict[str, Any],
                                roadmap: Dict[str, Any],
                                integrations: Dict[str, Any]
                                ) -> Dict[str, Any]:
    """Composição mecânica do estado executivo (sem LLM)."""
    riscos: List[Dict[str, str]] = []
    if (summary.get("churn_pct") or 0) > 5:
        riscos.append({"area": "Retenção",
                         "descricao": f"Churn em "
                            f"{summary['churn_pct']}% (>5%)",
                         "nivel": "alto"})
    if (summary.get("inadimplencia_pct") or 0) > 10:
        riscos.append({"area": "Financeiro",
                         "descricao": f"Inadimplência em "
                            f"{summary['inadimplencia_pct']}% (>10%)",
                         "nivel": "alto"})
    if (net.get("ctos_saturadas") or []):
        riscos.append({"area": "Rede",
                         "descricao": f"{len(net['ctos_saturadas'])} "
                            f"CTOs com saturação ≥85%",
                         "nivel": "medio"})
    if (ops.get("tickets_abertos") or 0) > 50:
        riscos.append({"area": "Operação",
                         "descricao": f"{ops['tickets_abertos']} "
                            f"tickets abertos",
                         "nivel": "medio"})
    if (roadmap.get("auditor_pendentes") or 0) > 0:
        riscos.append({"area": "Governança",
                         "descricao":
                            f"{roadmap['auditor_pendentes']} ações "
                            f"do Auditor IA pendentes de revisão",
                         "nivel": "baixo"})

    pontos_fortes: List[str] = []
    if (summary.get("mrr_brl") or 0) > 0:
        pontos_fortes.append(f"MRR consolidado de "
                              f"R$ {summary['mrr_brl']:,.2f}")
    if (summary.get("clientes_ativos") or 0) > 0:
        pontos_fortes.append(f"{summary['clientes_ativos']} clientes ativos")
    if integrations.get("ativas", 0) >= 5:
        pontos_fortes.append(f"{integrations['ativas']} integrações ativas")
    if (fin.get("receita_periodo_brl") or 0) > 0:
        pontos_fortes.append(f"Receita do período de "
                              f"R$ {fin['receita_periodo_brl']:,.2f}")

    nivel_geral = "saudavel"
    if any(r["nivel"] == "alto" for r in riscos):
        nivel_geral = "critico"
    elif any(r["nivel"] == "medio" for r in riscos):
        nivel_geral = "atencao"

    return {
        "estado_geral": nivel_geral,
        "riscos": riscos,
        "pontos_fortes": pontos_fortes,
        "totais_referencia": {
            "clientes": summary.get("total_clientes"),
            "ativos": summary.get("clientes_ativos"),
            "mrr_brl": summary.get("mrr_brl"),
            "ticket_medio": summary.get("ticket_medio_brl"),
            "churn_pct": summary.get("churn_pct"),
            "inadimplencia_pct": summary.get("inadimplencia_pct"),
        },
    }


# ─────────────────── 16. Anomalies ───────────────────
async def _section_anomalies(cid: str, cols: List[str]) -> Dict[str, Any]:
    bq = _base_q(cid)
    sub_no_plan = await _count("subscribers", cols, {
        **bq,
        "$or": [
            {"plan_id": {"$in": [None, ""]}},
            {"plan_id": {"$exists": False}},
        ]})
    sub_no_price = await _count("subscribers", cols, {
        **bq,
        "$or": [
            {"plan_price_brl": {"$in": [None, 0, "0", ""]}},
            {"plan_price_brl": {"$exists": False}},
        ]})
    sub_no_cpf = await _count("subscribers", cols, {
        **bq,
        "$or": [
            {"cpf": {"$in": [None, ""]}},
            {"cpf": {"$exists": False}},
        ]})
    sub_no_address = await _count("subscribers", cols, {
        **bq,
        "$or": [
            {"address": {"$in": [None, ""]}},
            {"address": {"$exists": False}},
        ]})
    sub_no_cto = await _count("subscribers", cols, {
        **bq, "status": {"$in": ["ATIVO", "ATIVA"]},
        "$or": [
            {"cto_id": {"$in": [None, ""]}},
            {"cto_id": {"$exists": False}},
        ]})
    sub_low_signal = await _count("subscribers", cols, {
        **bq, "signal_dbm": {"$lte": -28, "$gte": -40}})
    sub_status_var = await _count("subscribers", cols, {
        **bq, "status": {"$nin": [
            "ATIVO", "ATIVA", "SUSPENSO", "BLOQUEADO",
            "CANCELADO", "INATIVO"]}})

    duplicated_emails = []
    try:
        agg = await db.subscribers.aggregate([
            {"$match": {**bq,
                          "email": {"$exists": True, "$ne": None,
                                       "$nin": [""]}}},
            {"$group": {"_id": {"$toLower": "$email"},
                           "qtd": {"$sum": 1}}},
            {"$match": {"qtd": {"$gt": 1}}},
            {"$sort": {"qtd": -1}}, {"$limit": 10},
        ]).to_list(10)
        duplicated_emails = [{"email": r["_id"], "qtd": r["qtd"]}
                              for r in agg]
    except Exception:
        pass

    return {
        "subscribers_sem_plano": sub_no_plan,
        "subscribers_sem_preco": sub_no_price,
        "subscribers_sem_cpf": sub_no_cpf,
        "subscribers_sem_endereco": sub_no_address,
        "ativos_sem_cto": sub_no_cto,
        "ativos_com_sinal_baixo": sub_low_signal,
        "status_fora_do_padrao": sub_status_var,
        "emails_duplicados": duplicated_emails,
    }


# ─────────────────── ENDPOINT ───────────────────
async def _build_report(cid: str, days: int,
                          user_email: str = "") -> Dict[str, Any]:
    """Constrói o payload completo do relatório (16 seções)."""
    started_at = datetime.now(timezone.utc)
    cols = await db.list_collection_names()

    summary = await _section_executive_summary(cid, cols, days)
    module_map = _section_module_map(cols)
    ai_engine = await _section_ai_engine(cid, cols, days)
    database_sec = await _section_database(cid, cols)
    operations = await _section_operations(cid, cols, days)
    network = await _section_network(cid, cols)
    gps_fleet = await _section_gps_fleet(cid, cols, days)
    security = await _section_security(cid, cols, days)
    financials = await _section_financials(cid, cols, days)
    kpis = await _section_kpis(cid, cols, days)
    automations = await _section_automations(cid, cols)
    integrations = await _section_integrations(cid, cols)
    roadmap = await _section_roadmap(cid, cols)
    ai_auto = await _section_ai_auto_analysis(cid, cols, days)
    review = _section_executive_review(summary, operations, network,
                                          financials, roadmap, integrations)
    anomalies = await _section_anomalies(cid, cols)

    finished_at = datetime.now(timezone.utc)
    elapsed_ms = int((finished_at - started_at).total_seconds() * 1000)

    return {
        "id": f"diag-{uuid.uuid4().hex[:14]}",
        "company_id": cid,
        "generated_at": finished_at.isoformat(),
        "generated_by": user_email,
        "period_days": days,
        "elapsed_ms": elapsed_ms,
        "sections": {
            "01_executive_summary": {"title": "1. Resumo Executivo",
                                       "data": summary},
            "02_module_map": {"title": "2. Mapa de Módulos",
                                "data": module_map},
            "03_ai_engine": {"title": "3. Motor IA", "data": ai_engine},
            "04_database": {"title": "4. Banco de Dados",
                              "data": database_sec},
            "05_operations": {"title": "5. Operação", "data": operations},
            "06_network": {"title": "6. Rede", "data": network},
            "07_gps_fleet": {"title": "7. GPS / Frota", "data": gps_fleet},
            "08_security": {"title": "8. SecurityHome", "data": security},
            "09_financials": {"title": "9. Financeiro", "data": financials},
            "10_kpis": {"title": "10. KPIs", "data": kpis},
            "11_automations": {"title": "11. Automações",
                                 "data": automations},
            "12_integrations": {"title": "12. Integrações",
                                  "data": integrations},
            "13_roadmap": {"title": "13. Roadmap / Pendências",
                             "data": roadmap},
            "14_ai_auto_analysis": {"title": "14. Análise Automática IA",
                                       "data": ai_auto},
            "15_executive_review": {"title": "15. Revisão Executiva",
                                       "data": review},
            "16_anomalies": {"title": "16. Anomalias", "data": anomalies},
        },
    }


@router.get("/diagnostic-report")
async def diagnostic_report(
    days: int = Query(30, ge=1, le=365,
                        description="Janela do período (dias)"),
    user: dict = Depends(get_current_user),
):
    """Relatório de Diagnóstico Completo (16 seções, dados brutos)."""
    return await _build_report(_cid(user), days, user.get("email", ""))


@router.get("/diagnostic-report.pdf")
async def diagnostic_report_pdf(
    days: int = Query(30, ge=1, le=365),
    user: dict = Depends(get_current_user),
):
    """Renderiza o mesmo relatório como PDF (download direto)."""
    payload = await _build_report(_cid(user), days, user.get("email", ""))
    pdf_bytes = _render_pdf(payload)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"diagnostico-smartprov-{stamp}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


# ─────────────────── PDF RENDERER ───────────────────
def _render_pdf(payload: Dict[str, Any]) -> bytes:
    """Renderiza o relatório como PDF A4 usando ReportLab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    )

    PURPLE = colors.HexColor("#4b1d7a")
    ORANGE = colors.HexColor("#f28c28")
    GREEN = colors.HexColor("#237a4b")
    RED = colors.HexColor("#b42318")
    GRAY = colors.HexColor("#475569")
    LIGHT = colors.HexColor("#f1f5f9")
    BORDER = colors.HexColor("#cbd5e1")

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title="Diagnóstico Completo do SmartProv",
        author="SmartProv Conselho IA",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18,
                          textColor=PURPLE, spaceAfter=6, leading=22)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12,
                          textColor=PURPLE, spaceBefore=8, spaceAfter=4,
                          leading=15)
    meta = ParagraphStyle("meta", parent=styles["Normal"], fontSize=8,
                            textColor=GRAY, leading=10)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=8.5,
                            leading=11)

    story: List[Any] = []

    # Capa / cabeçalho
    story.append(Paragraph("Diagnóstico Completo do SmartProv", h1))
    gen_at = payload.get("generated_at", "")
    try:
        dt = datetime.fromisoformat(gen_at.replace("Z", "+00:00"))
        gen_at_fmt = dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        gen_at_fmt = gen_at
    story.append(Paragraph(
        f"16 seções · dados brutos · sem síntese LLM<br/>"
        f"Gerado em <b>{gen_at_fmt}</b> por "
        f"<b>{payload.get('generated_by', '—')}</b> · "
        f"Período: <b>{payload.get('period_days')} dias</b> · "
        f"Tempo de coleta: {payload.get('elapsed_ms')} ms",
        meta))
    story.append(Spacer(1, 6))

    # Sumário
    sections = payload.get("sections", {})
    keys_sorted = sorted(sections.keys())
    toc_rows = [[Paragraph(f"<b>{sections[k]['title']}</b>", body)]
                 for k in keys_sorted]
    toc = Table(toc_rows, colWidths=[170 * mm])
    toc.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(toc)
    story.append(PageBreak())

    color_map = {
        "01_executive_summary": PURPLE, "02_module_map": PURPLE,
        "03_ai_engine": PURPLE, "04_database": GRAY,
        "05_operations": PURPLE, "06_network": PURPLE,
        "07_gps_fleet": ORANGE, "08_security": GREEN,
        "09_financials": GREEN, "10_kpis": PURPLE,
        "11_automations": PURPLE, "12_integrations": PURPLE,
        "13_roadmap": ORANGE, "14_ai_auto_analysis": PURPLE,
        "15_executive_review": PURPLE, "16_anomalies": RED,
    }

    for i, key in enumerate(keys_sorted):
        sec = sections[key]
        sec_color = color_map.get(key, PURPLE)
        sec_h = ParagraphStyle(
            f"h_{key}", parent=h2, textColor=sec_color)
        story.append(Paragraph(sec["title"], sec_h))
        _render_section_body(story, sec.get("data") or {}, body,
                              colors, BORDER, LIGHT, GRAY, sec_color)
        story.append(Spacer(1, 8))
        if i < len(keys_sorted) - 1:
            story.append(PageBreak())

    def _footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(GRAY)
        page_num = canvas.getPageNumber()
        canvas.drawRightString(
            A4[0] - 14 * mm, 8 * mm,
            f"SmartProv · Diagnóstico {gen_at_fmt} · pág. {page_num}")
        canvas.drawString(14 * mm, 8 * mm, payload.get("id", ""))
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def _fmt_value(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "Sim" if v else "Não"
    if isinstance(v, (int, float)):
        try:
            if isinstance(v, float):
                return f"{v:,.2f}".replace(",", "X").replace(".", ",") \
                    .replace("X", ".")
            return f"{v:,}".replace(",", ".")
        except Exception:
            return str(v)
    if isinstance(v, list):
        if not v:
            return "—"
        return f"[{len(v)} itens]"
    if isinstance(v, dict):
        return f"{{{len(v)} chaves}}"
    s = str(v)
    return s if len(s) <= 90 else s[:87] + "…"


def _render_section_body(story, data: Dict[str, Any], body_style,
                            colors_mod, border, light, gray, accent):
    """Renderiza o `data` de uma seção como tabelas KV +
    sub-tabelas para listas."""
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    if not data:
        story.append(Paragraph("Sem dados.", body_style))
        return

    # Separa escalares de listas/dicionários complexos
    scalars: List[tuple] = []
    complex_items: List[tuple] = []
    for k, v in data.items():
        if isinstance(v, (list, dict)) and v:
            complex_items.append((k, v))
        else:
            scalars.append((k, v))

    # Tabela KV de escalares
    if scalars:
        kv_rows = [["Campo", "Valor"]]
        for k, v in scalars:
            kv_rows.append([
                Paragraph(str(k).replace("_", " "), body_style),
                Paragraph(_fmt_value(v), body_style),
            ])
        t = Table(kv_rows, colWidths=[70 * mm, 100 * mm], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), accent),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors_mod.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BOX", (0, 0), (-1, -1), 0.4, border),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, border),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors_mod.white, light]),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(t)
        story.append(Spacer(1, 4))

    # Sub-tabelas para listas
    from reportlab.lib.styles import ParagraphStyle as _PS
    for k, v in complex_items:
        sub_h = _PS("sub_h", parent=body_style, fontSize=9,
                      textColor=accent, spaceBefore=4, spaceAfter=2,
                      fontName="Helvetica-Bold")
        story.append(Paragraph(f"<b>{str(k).replace('_', ' ')}</b>",
                                sub_h))
        if isinstance(v, list):
            _render_list_table(story, v, body_style, colors_mod, border,
                                  light, gray, accent)
        elif isinstance(v, dict):
            sub_rows = [["Campo", "Valor"]]
            for k2, v2 in v.items():
                sub_rows.append([
                    Paragraph(str(k2).replace("_", " "), body_style),
                    Paragraph(_fmt_value(v2), body_style),
                ])
            t = Table(sub_rows, colWidths=[70 * mm, 100 * mm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), accent),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors_mod.white),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("BOX", (0, 0), (-1, -1), 0.4, border),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, border),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            story.append(t)
        story.append(Spacer(1, 4))


def _render_list_table(story, items: list, body_style, colors_mod,
                          border, light, gray, accent):
    """Renderiza uma lista como tabela. Trabalha com dicts heterogêneos."""
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table, TableStyle

    if not items:
        story.append(Paragraph("Sem itens.", body_style))
        return
    # Limita a 30 linhas pra não explodir o PDF
    limited = items[:30]
    first = limited[0]
    if isinstance(first, dict):
        # Coleta até 6 colunas das chaves mais frequentes
        keys: List[str] = []
        for it in limited:
            if isinstance(it, dict):
                for k in it.keys():
                    if k not in keys:
                        keys.append(k)
                    if len(keys) >= 6:
                        break
            if len(keys) >= 6:
                break
        headers = [Paragraph(f"<b>{k.replace('_', ' ')}</b>", body_style)
                    for k in keys]
        rows = [headers]
        for it in limited:
            if isinstance(it, dict):
                rows.append([Paragraph(_fmt_value(it.get(k)), body_style)
                              for k in keys])
        n_cols = len(keys)
        col_w = (170 / n_cols) * mm if n_cols else 170 * mm
        t = Table(rows, colWidths=[col_w] * n_cols, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), accent),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors_mod.white),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("BOX", (0, 0), (-1, -1), 0.4, border),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, border),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors_mod.white, light]),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t)
    else:
        # Lista simples (strings/numeros)
        rows = [[Paragraph(_fmt_value(it), body_style)] for it in limited]
        t = Table(rows, colWidths=[170 * mm])
        t.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.4, border),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, border),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(t)

    if len(items) > 30:
        story.append(Paragraph(
            f"<i>(+ {len(items) - 30} itens omitidos)</i>", body_style))
