"""
conselho_ia.py — Conselho Estratégico IA (iter215bq, Fase 1)
Camada executiva acima do Motor IA: consolida dados operacionais
em relatórios estratégicos com interpretação e recomendações.

Fase 1 entrega:
  - 3 módulos: Visão Geral, Rede & Operação, Parecer Executivo
  - 5 períodos: daily / weekly / monthly / quarterly / yearly
  - Cache em Mongo (`conselho_ia_reports`) — não regenera sem pedir

Endpoints:
  POST /api/conselho-ia/report     gera (ou retorna cached) relatório
  GET  /api/conselho-ia/reports    lista os últimos 20
  GET  /api/conselho-ia/reports/{id}
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

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, get_current_user
from database import db
from services.motor_ia import chat_completion
from services.agent_tools import (
    TOOL_CATALOG, llm_tool_catalog_prompt, execute_tool_call,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/conselho-ia", tags=["conselho-ia"])

PERIODS = ("daily", "weekly", "monthly", "quarterly", "yearly")
PERIOD_DAYS = {
    "daily": 1, "weekly": 7, "monthly": 30,
    "quarterly": 90, "yearly": 365,
}
PERIOD_LABEL = {
    "daily": "Diário", "weekly": "Semanal", "monthly": "Mensal",
    "quarterly": "Trimestral", "yearly": "Anual",
}


# ─────────────────── data collection ───────────────────
async def _collect_overview(cid: str, days: int) -> Dict[str, Any]:
    """Módulo 1 — Visão Geral. Consulta `subscribers`."""
    base_q: Dict[str, Any] = {}
    if cid and cid != DEMO_COMPANY_ID:
        base_q["company_id"] = cid

    total = await db.subscribers.count_documents(base_q)
    ativos = await db.subscribers.count_documents(
        {**base_q, "status": {"$in": ["ATIVO", "ATIVA"]}})
    suspensos = await db.subscribers.count_documents(
        {**base_q, "status": {"$regex": "SUSPENS", "$options": "i"}})
    bloqueados = await db.subscribers.count_documents(
        {**base_q, "status": {"$regex": "BLOQUE", "$options": "i"}})
    cancelados = await db.subscribers.count_documents(
        {**base_q, "status": {"$regex": "CANCEL", "$options": "i"}})
    inadimplentes = await db.subscribers.count_documents({
        **base_q,
        "financial_status": {"$regex": "inadimp|atrasad", "$options": "i"},
    })

    # Novos no período
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    novos = await db.subscribers.count_documents({
        **base_q,
        "installation_date": {"$gte": cutoff},
    })

    # MRR aproximado: soma de plan_price_brl dos ativos
    mrr_cur = db.subscribers.aggregate([
        {"$match": {**base_q, "status": {"$in": ["ATIVO", "ATIVA"]}}},
        {"$group": {"_id": None,
                       "mrr": {"$sum": {"$ifNull": ["$plan_price_brl", 0]}}}},
    ])
    mrr_list = await mrr_cur.to_list(1)
    mrr = round(float((mrr_list[0] if mrr_list else {}).get("mrr", 0)), 2)
    ticket = round(mrr / ativos, 2) if ativos else 0.0

    # Top 5 cidades/bairros/planos por receita
    by_city = await db.subscribers.aggregate([
        {"$match": {**base_q, "status": {"$in": ["ATIVO", "ATIVA"]}}},
        {"$group": {"_id": "$city",
                       "qtd": {"$sum": 1},
                       "mrr": {"$sum": {"$ifNull": ["$plan_price_brl", 0]}}}},
        {"$sort": {"mrr": -1}}, {"$limit": 5},
    ]).to_list(5)
    by_plan = await db.subscribers.aggregate([
        {"$match": {**base_q, "status": {"$in": ["ATIVO", "ATIVA"]}}},
        {"$group": {"_id": "$plan_name",
                       "qtd": {"$sum": 1},
                       "mrr": {"$sum": {"$ifNull": ["$plan_price_brl", 0]}}}},
        {"$sort": {"qtd": -1}}, {"$limit": 5},
    ]).to_list(5)

    churn_pct = round(
        100 * cancelados / total, 2) if total else 0.0
    inad_pct = round(
        100 * inadimplentes / max(ativos, 1), 2)

    return {
        "total_clientes": total,
        "ativos": ativos,
        "suspensos": suspensos,
        "bloqueados": bloqueados,
        "cancelados": cancelados,
        "inadimplentes": inadimplentes,
        "novos_no_periodo": novos,
        "mrr_brl": mrr,
        "ticket_medio_brl": ticket,
        "churn_pct": churn_pct,
        "inadimplencia_pct": inad_pct,
        "top_cidades": [
            {"cidade": c["_id"] or "—", "qtd": c["qtd"],
             "mrr": round(c["mrr"], 2)} for c in by_city
        ],
        "top_planos": [
            {"plano": p["_id"] or "—", "qtd": p["qtd"],
             "mrr": round(p["mrr"], 2)} for p in by_plan
        ],
    }


async def _collect_network(cid: str, days: int) -> Dict[str, Any]:
    """Módulo 2 — Rede & Operação. Consulta `ctos`, `subscribers`."""
    base_q: Dict[str, Any] = {}
    if cid and cid != DEMO_COMPANY_ID:
        base_q["company_id"] = cid

    total_ctos = await db.ctos.count_documents(base_q)
    total_olts = await db.olts.count_documents(base_q) \
        if "olts" in await db.list_collection_names() else 0

    # ONUs online/offline (best-effort por status)
    onus_total = await db.subscribers.count_documents({
        **base_q, "olt_id": {"$exists": True, "$ne": None}})
    onus_offline = await db.subscribers.count_documents({
        **base_q, "olt_id": {"$exists": True, "$ne": None},
        "$or": [
            {"signal_dbm": {"$lte": -28}},
            {"status_onu": {"$regex": "offline|los|lof", "$options": "i"}},
        ],
    })
    onus_online = max(onus_total - onus_offline, 0)

    # Potência média
    pot_cur = db.subscribers.aggregate([
        {"$match": {**base_q,
                      "signal_dbm": {"$exists": True, "$ne": None,
                                       "$gte": -40, "$lte": -1}}},
        {"$group": {"_id": None,
                       "avg": {"$avg": "$signal_dbm"}}},
    ])
    pot_list = await pot_cur.to_list(1)
    pot_media = round(float(
        (pot_list[0] if pot_list else {}).get("avg", 0)), 2)

    # Clientes por CTO (top 10 mais saturadas)
    top_ctos = await db.subscribers.aggregate([
        {"$match": {**base_q, "cto_id": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$cto_id", "qtd": {"$sum": 1}}},
        {"$sort": {"qtd": -1}}, {"$limit": 10},
    ]).to_list(10)
    # Enriquece com nome e capacidade
    cto_ids = [c["_id"] for c in top_ctos]
    cto_meta = {c["id"]: c async for c in db.ctos.find(
        {"id": {"$in": cto_ids}}, {"_id": 0, "id": 1, "label": 1,
                                     "capacity": 1, "neighborhood": 1})}
    ctos_saturadas = []
    for c in top_ctos:
        meta = cto_meta.get(c["_id"], {})
        cap = meta.get("capacity", 16) or 16
        pct = round(100 * c["qtd"] / cap, 1) if cap else 0
        ctos_saturadas.append({
            "cto_id": c["_id"],
            "label": meta.get("label", c["_id"]),
            "bairro": meta.get("neighborhood", "—"),
            "clientes": c["qtd"],
            "capacidade": cap,
            "saturacao_pct": pct,
        })

    # Incidentes coletivos por bairro (chamados últimos N dias)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    bairros_critic = []
    try:
        bairros_critic = await db.support_tickets.aggregate([
            {"$match": {**base_q,
                          "created_at": {"$gte": cutoff}}},
            {"$group": {"_id": "$neighborhood",
                           "qtd": {"$sum": 1}}},
            {"$sort": {"qtd": -1}}, {"$limit": 5},
        ]).to_list(5)
    except Exception:
        pass

    return {
        "olts": total_olts,
        "ctos": total_ctos,
        "onus_online": onus_online,
        "onus_offline": onus_offline,
        "potencia_media_dbm": pot_media,
        "ctos_saturadas": ctos_saturadas,
        "bairros_com_mais_chamados": [
            {"bairro": b["_id"] or "—", "qtd": b["qtd"]}
            for b in bairros_critic
        ],
    }


# iter215br — Fase 2: Módulos 3-7 (Técnicos, Atendimento, Vendas,
# Universo Ligo, Ligo Protege)
async def _collect_technicians(cid: str, days: int) -> Dict[str, Any]:
    """Módulo 3 — Técnicos. Tickets/tasks por técnico no período."""
    base_q: Dict[str, Any] = {}
    if cid and cid != DEMO_COMPANY_ID:
        base_q["company_id"] = cid
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    q = {**base_q, "created_at": {"$gte": cutoff}}

    # Por tipo de tarefa
    by_type = await db.tickets.aggregate([
        {"$match": q},
        {"$group": {"_id": "$type", "qtd": {"$sum": 1}}},
    ]).to_list(20)
    type_counts = {t["_id"] or "outros": t["qtd"] for t in by_type}

    total = sum(type_counts.values())
    instalacoes = sum(v for k, v in type_counts.items()
                       if "instal" in (k or "").lower())
    reparos = sum(v for k, v in type_counts.items()
                   if "repar" in (k or "").lower() or "manut" in (k or "").lower())

    # Top 10 técnicos por volume + nota média
    top_tech = await db.tickets.aggregate([
        {"$match": {**q, "technician_id": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$technician_id",
                       "qtd": {"$sum": 1},
                       "avg_rating": {"$avg": {"$ifNull": ["$rating", 0]}}}},
        {"$sort": {"qtd": -1}}, {"$limit": 10},
    ]).to_list(10)
    tech_ids = [t["_id"] for t in top_tech]
    tech_meta = {t["id"]: t async for t in db.technicians.find(
        {"id": {"$in": tech_ids}},
        {"_id": 0, "id": 1, "name": 1})} \
        if "technicians" in await db.list_collection_names() else {}
    ranking = []
    for t in top_tech:
        meta = tech_meta.get(t["_id"]) or {}
        ranking.append({
            "tecnico": meta.get("name") or t["_id"],
            "tarefas": t["qtd"],
            "nota_media": round(float(t.get("avg_rating") or 0), 2),
        })

    # Tempo médio (horas) de resolução
    pipeline = [
        {"$match": {**q, "closed_at": {"$exists": True, "$ne": None}}},
        {"$project": {
            "duracao_h": {
                "$divide": [
                    {"$subtract": [
                        {"$dateFromString": {
                            "dateString": "$closed_at",
                            "onError": None}},
                        {"$dateFromString": {
                            "dateString": "$created_at",
                            "onError": None}},
                    ]}, 3600000,
                ]},
        }},
        {"$group": {"_id": None,
                       "avg": {"$avg": "$duracao_h"}}},
    ]
    avg_list = []
    try:
        avg_list = await db.tickets.aggregate(pipeline).to_list(1)
    except Exception:
        pass
    tempo_medio = round(float(
        (avg_list[0] if avg_list else {}).get("avg", 0) or 0), 1)

    return {
        "total_tarefas": total,
        "instalacoes": instalacoes,
        "reparos": reparos,
        "tempo_medio_horas": tempo_medio,
        "por_tipo": [{"tipo": k, "qtd": v}
                       for k, v in sorted(type_counts.items(),
                                            key=lambda x: -x[1])[:8]],
        "top_tecnicos": ranking,
    }


async def _collect_atendimento(cid: str, days: int) -> Dict[str, Any]:
    """Módulo 4 — Atendimento (Isabella + Álvaro + humano)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    base_q: Dict[str, Any] = {}
    if cid and cid != DEMO_COMPANY_ID:
        base_q["company_id"] = cid

    # Conversas Isabella (neo_chat_messages é o canal humano,
    # isabella usa session_id em outra collection)
    cols = await db.list_collection_names()
    isabella_conv = 0
    if "isabella_sessions" in cols:
        isabella_conv = await db.isabella_sessions.count_documents(
            {**base_q, "created_at": {"$gte": cutoff}})

    # Atendimento humano (neo_chat_messages)
    chat_msgs = await db.neo_chat_messages.count_documents(
        {**base_q, "created_at": {"$gte": cutoff}})

    # Álvaro analyses (motor de análise de chamadas)
    alvaro = await db.alvaro_analyses.count_documents(
        {**base_q, "created_at": {"$gte": cutoff}}) \
        if "alvaro_analyses" in cols else 0

    # Customer support requests (formulários)
    csr = await db.customer_support_requests.count_documents(
        {**base_q, "created_at": {"$gte": cutoff}}) \
        if "customer_support_requests" in cols else 0

    # Sentimento (das análises do Álvaro)
    sentiment = {"positivo": 0, "neutro": 0, "negativo": 0}
    if "alvaro_analyses" in cols:
        async for doc in db.alvaro_analyses.find(
                {**base_q, "created_at": {"$gte": cutoff}},
                {"_id": 0, "sentiment": 1, "score": 1}):
            s = (doc.get("sentiment") or "").lower()
            if "pos" in s or "feliz" in s:
                sentiment["positivo"] += 1
            elif "neg" in s or "irrit" in s or "raiva" in s:
                sentiment["negativo"] += 1
            else:
                sentiment["neutro"] += 1

    # Principais assuntos: best-effort a partir do `subject`
    top_assuntos = []
    if "tickets" in cols:
        rows = await db.tickets.aggregate([
            {"$match": {**base_q, "created_at": {"$gte": cutoff}}},
            {"$group": {"_id": "$subject", "qtd": {"$sum": 1}}},
            {"$sort": {"qtd": -1}}, {"$limit": 5},
        ]).to_list(5)
        top_assuntos = [{"assunto": r["_id"] or "—", "qtd": r["qtd"]}
                        for r in rows if r["_id"]]

    return {
        "isabella_conversas": isabella_conv,
        "alvaro_analises": alvaro,
        "atendimento_humano_msgs": chat_msgs,
        "solicitacoes_suporte": csr,
        "sentimento": sentiment,
        "top_assuntos": top_assuntos,
    }


async def _collect_sales(cid: str, days: int) -> Dict[str, Any]:
    """Módulo 5 — Vendas. Leads + novos contratos no período."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    base_q: Dict[str, Any] = {}
    if cid and cid != DEMO_COMPANY_ID:
        base_q["company_id"] = cid

    cols = await db.list_collection_names()
    leads = 0
    if "sales_leads" in cols:
        leads = await db.sales_leads.count_documents(
            {**base_q, "created_at": {"$gte": cutoff}})
    site_leads = 0
    if "site_leads" in cols:
        site_leads = await db.site_leads.count_documents(
            {**base_q, "created_at": {"$gte": cutoff}})
    indic_leads = 0
    if "indicacao_leads" in cols:
        indic_leads = await db.indicacao_leads.count_documents(
            {**base_q, "created_at": {"$gte": cutoff}})

    # Vendas concretizadas: subscribers novos com installation_date
    vendas = await db.subscribers.count_documents({
        **base_q, "installation_date": {"$gte": cutoff},
    })
    total_leads = leads + site_leads + indic_leads
    conversao = round(100 * vendas / total_leads, 1) if total_leads else 0

    # Top bairros de novos contratos
    by_bairro = await db.subscribers.aggregate([
        {"$match": {**base_q,
                      "installation_date": {"$gte": cutoff}}},
        {"$group": {"_id": "$neighborhood",
                       "qtd": {"$sum": 1}}},
        {"$sort": {"qtd": -1}}, {"$limit": 5},
    ]).to_list(5)

    # Planos mais vendidos no período
    by_plan = await db.subscribers.aggregate([
        {"$match": {**base_q,
                      "installation_date": {"$gte": cutoff}}},
        {"$group": {"_id": "$plan_name", "qtd": {"$sum": 1}}},
        {"$sort": {"qtd": -1}}, {"$limit": 5},
    ]).to_list(5)

    return {
        "leads_total": total_leads,
        "leads_breakdown": {"sales": leads, "site": site_leads,
                              "indicacao": indic_leads},
        "vendas_concluidas": vendas,
        "taxa_conversao_pct": conversao,
        "top_bairros_vendas": [
            {"bairro": b["_id"] or "—", "qtd": b["qtd"]}
            for b in by_bairro],
        "top_planos_vendidos": [
            {"plano": p["_id"] or "—", "qtd": p["qtd"]}
            for p in by_plan],
    }


async def _collect_universo_ligo(cid: str, days: int) -> Dict[str, Any]:
    """Módulo 6 — Universo Ligo (ecosystem).
    Ligo Fibra + Clube Ligo (referrals) + Parceiros QR (parcerias)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    base_q: Dict[str, Any] = {}
    if cid and cid != DEMO_COMPANY_ID:
        base_q["company_id"] = cid

    cols = await db.list_collection_names()

    fibra_total = await db.subscribers.count_documents({
        **base_q, "status": {"$in": ["ATIVO", "ATIVA"]}})
    fibra_novos = await db.subscribers.count_documents({
        **base_q, "installation_date": {"$gte": cutoff},
        "status": {"$in": ["ATIVO", "ATIVA"]}})

    # Clube Ligo (referrals)
    indicacoes = 0
    indicacoes_conv = 0
    if "referrals" in cols:
        indicacoes = await db.referrals.count_documents(
            {**base_q, "created_at": {"$gte": cutoff}})
        indicacoes_conv = await db.referrals.count_documents(
            {**base_q, "status": "converted",
             "created_at": {"$gte": cutoff}})

    # Parceiros (parcerias_redemptions)
    resgates = await db.parcerias_redemptions.count_documents(
        {**base_q, "redeemed_at": {"$gte": cutoff}}) \
        if "parcerias_redemptions" in cols else 0

    # Top 5 parceiros mais acessados
    top_parceiros = []
    if "parcerias_redemptions" in cols:
        rows = await db.parcerias_redemptions.aggregate([
            {"$match": {**base_q,
                          "redeemed_at": {"$gte": cutoff}}},
            {"$group": {"_id": "$partner_name", "qtd": {"$sum": 1}}},
            {"$sort": {"qtd": -1}}, {"$limit": 5},
        ]).to_list(5)
        top_parceiros = [{"parceiro": r["_id"] or "—", "qtd": r["qtd"]}
                          for r in rows]

    # Ligo de Casa / Ligo Conteúdos: marcadores ao subscriber
    ligo_casa = await db.subscribers.count_documents({
        **base_q, "ligo_casa": True})
    ligo_conteudos = await db.subscribers.count_documents({
        **base_q, "ligo_conteudos": True})

    return {
        "ligo_fibra": {"base_ativa": fibra_total, "novos_periodo": fibra_novos},
        "ligo_de_casa": {"ativos": ligo_casa},
        "ligo_conteudos": {"assinantes": ligo_conteudos},
        "clube_ligo": {"indicacoes": indicacoes,
                         "conversoes": indicacoes_conv},
        "parceiros_qr": {"resgates": resgates,
                           "top_parceiros": top_parceiros},
    }


# iter215bs — Auditor IA com auto-correção (Modelo B: whitelist)
# Roda no fim da geração do relatório. Detecta inconsistências e:
#   - WHITELIST → aplica automaticamente (backfill de campos vazios)
#   - FORA DA WHITELIST → cria ação pendente que precisa aprovação
# Tudo é logado em `conselho_ia_audit_log` com sample do "antes" pra
# permitir auditoria/desfazer.

# Actions seguras pra auto-apply:
AUTO_APPLY_ACTIONS = {
    "backfill_plan_price",
    "backfill_plan_name",
    "normalize_status_case",
}


async def _audit_action(cid: str, action: str, found: int,
                          applied: int, sample: list,
                          status: str = "applied",
                          notes: str = "",
                          executed_by: str = "auditor_ia") -> str:
    """Grava 1 entrada no `conselho_ia_audit_log`."""
    aid = f"cia-aud-{uuid.uuid4().hex[:14]}"
    await db.conselho_ia_audit_log.insert_one({
        "id": aid,
        "company_id": cid,
        "action": action,
        "status": status,         # applied | pending | rejected | failed
        "found": found,
        "applied": applied,
        "sample_before": sample[:5],
        "notes": notes,
        "executed_by": executed_by,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return aid


async def _audit_backfill_plan_price(cid: str) -> Dict[str, Any]:
    """Backfill subscribers.plan_price_brl=null/0 com base em plans.price_brl.
    Whitelist: AUTO-APLICA."""
    base_q: Dict[str, Any] = {}
    if cid and cid != DEMO_COMPANY_ID:
        base_q["company_id"] = cid
    # Encontra subscribers com price nulo/0 e plan_id existente
    q = {**base_q,
         "plan_id": {"$exists": True, "$nin": [None, ""]},
         "$or": [
            {"plan_price_brl": {"$in": [None, 0, "0", ""]}},
            {"plan_price_brl": {"$exists": False}},
         ]}
    affected = await db.subscribers.find(q,
        {"_id": 0, "id": 1, "plan_id": 1, "name": 1}).to_list(5000)
    found = len(affected)
    if not found:
        return {"action": "backfill_plan_price", "found": 0, "applied": 0,
                "status": "ok"}
    # Carrega preços de plans
    plan_ids = list({a["plan_id"] for a in affected if a.get("plan_id")})
    plans = {p["id"]: p async for p in db.plans.find(
        {"id": {"$in": plan_ids}},
        {"_id": 0, "id": 1, "price_brl": 1, "name": 1, "monthly_price": 1})}
    applied = 0
    sample = []
    for a in affected:
        plan = plans.get(a.get("plan_id"))
        if not plan:
            continue
        price = plan.get("price_brl") or plan.get("monthly_price") or 0
        try:
            price = float(price)
        except Exception:
            price = 0
        if price <= 0:
            continue
        await db.subscribers.update_one(
            {"id": a["id"]},
            {"$set": {"plan_price_brl": price}})
        applied += 1
        if len(sample) < 5:
            sample.append({"sub_id": a["id"], "name": a.get("name"),
                            "old": None, "new": price,
                            "plan": plan.get("name")})
    aid = await _audit_action(cid, "backfill_plan_price", found, applied,
                                 sample, status="applied",
                                 notes=f"Backfill automático de "
                                        f"plan_price_brl em {applied} subscribers.")
    return {"action": "backfill_plan_price", "found": found,
             "applied": applied, "id": aid, "sample": sample,
             "status": "applied"}


async def _audit_backfill_plan_name(cid: str) -> Dict[str, Any]:
    """Backfill subscribers.plan_name vazio/—/null com base em plans.name.
    Whitelist: AUTO-APLICA."""
    base_q: Dict[str, Any] = {}
    if cid and cid != DEMO_COMPANY_ID:
        base_q["company_id"] = cid
    q = {**base_q,
         "plan_id": {"$exists": True, "$nin": [None, ""]},
         "$or": [
            {"plan_name": {"$in": [None, "", "—", "-"]}},
            {"plan_name": {"$exists": False}},
         ]}
    affected = await db.subscribers.find(q,
        {"_id": 0, "id": 1, "plan_id": 1, "name": 1}).to_list(5000)
    found = len(affected)
    if not found:
        return {"action": "backfill_plan_name", "found": 0, "applied": 0,
                "status": "ok"}
    plan_ids = list({a["plan_id"] for a in affected if a.get("plan_id")})
    plans = {p["id"]: p async for p in db.plans.find(
        {"id": {"$in": plan_ids}}, {"_id": 0, "id": 1, "name": 1})}
    applied = 0
    sample = []
    for a in affected:
        plan = plans.get(a.get("plan_id"))
        if not plan or not plan.get("name"):
            continue
        await db.subscribers.update_one(
            {"id": a["id"]},
            {"$set": {"plan_name": plan["name"]}})
        applied += 1
        if len(sample) < 5:
            sample.append({"sub_id": a["id"], "name": a.get("name"),
                            "old": None, "new": plan["name"]})
    aid = await _audit_action(cid, "backfill_plan_name", found, applied,
                                 sample, status="applied",
                                 notes=f"Backfill automático de "
                                        f"plan_name em {applied} subscribers.")
    return {"action": "backfill_plan_name", "found": found,
             "applied": applied, "id": aid, "sample": sample,
             "status": "applied"}


async def _audit_normalize_status_case(cid: str) -> Dict[str, Any]:
    """Normaliza variações de status (ATIVA→ATIVO, etc).
    Whitelist: AUTO-APLICA."""
    base_q: Dict[str, Any] = {}
    if cid and cid != DEMO_COMPANY_ID:
        base_q["company_id"] = cid
    rules = {"ATIVA": "ATIVO", "Ativo": "ATIVO", "ativo": "ATIVO",
             "Ativa": "ATIVO", "SUSPENSA": "SUSPENSO", "Suspenso": "SUSPENSO",
             "CANCELADA": "CANCELADO"}
    applied = 0
    sample = []
    for old, new in rules.items():
        cur = db.subscribers.find(
            {**base_q, "status": old},
            {"_id": 0, "id": 1, "name": 1, "status": 1}).limit(5000)
        async for s in cur:
            await db.subscribers.update_one(
                {"id": s["id"]}, {"$set": {"status": new}})
            applied += 1
            if len(sample) < 5:
                sample.append({"sub_id": s["id"], "name": s.get("name"),
                                "old": old, "new": new})
    aid = await _audit_action(cid, "normalize_status_case", applied, applied,
                                 sample, status="applied",
                                 notes=f"Normalização case-insensitive "
                                        f"em {applied} subscribers.")
    return {"action": "normalize_status_case", "found": applied,
             "applied": applied, "id": aid, "sample": sample,
             "status": "applied"}


async def _audit_anomalia_vendas(cid: str,
                                    sales: Dict[str, Any]) -> Dict[str, Any]:
    """Detecta anomalias em vendas (conversão >100% ou vendas sem leads).
    NÃO AUTO-APLICA — só registra como pendente, precisa investigação."""
    conv = sales.get("taxa_conversao_pct", 0)
    leads = sales.get("leads_total", 0)
    vendas = sales.get("vendas_concluidas", 0)
    if conv <= 100 and vendas <= leads * 2:
        return None
    sample = [{"taxa_conv": conv, "leads": leads, "vendas": vendas}]
    notes = (f"Conversão de {conv}% com {vendas} vendas a partir de "
              f"{leads} leads. Provável falha de captura no pipeline de "
              f"leads (formulário do site, indicação). Recomenda-se "
              f"auditar `sales_leads`, `site_leads` e `indicacao_leads`.")
    aid = await _audit_action(cid, "anomalia_vendas", 1, 0,
                                 sample, status="pending",
                                 notes=notes)
    return {"action": "anomalia_vendas", "found": 1, "applied": 0,
             "id": aid, "sample": sample, "notes": notes,
             "status": "pending"}


async def _run_auditor_ia(cid: str,
                           sales: Dict[str, Any]) -> Dict[str, Any]:
    """Roda todas as auditorias na ordem e retorna o resumo.
    Idempotente: rodar 2x não duplica nem causa estrago."""
    results = []
    # Whitelist — auto-apply
    for fn in (_audit_backfill_plan_price,
                _audit_backfill_plan_name,
                _audit_normalize_status_case):
        try:
            r = await fn(cid)
            if r and r.get("applied", 0) > 0:
                results.append(r)
        except Exception as e:
            logger.exception("[auditor-ia] %s falhou: %s",
                              fn.__name__, e)
            results.append({"action": fn.__name__,
                             "status": "failed", "error": str(e)})

    # Detection-only (sem auto-fix)
    pending = []
    try:
        r = await _audit_anomalia_vendas(cid, sales)
        if r:
            pending.append(r)
    except Exception as e:
        logger.exception("[auditor-ia] anomalia_vendas falhou: %s", e)

    total_applied = sum(r.get("applied", 0) for r in results)
    return {
        "applied_actions": results,
        "pending_actions": pending,
        "total_records_fixed": total_applied,
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }


async def _collect_protege(cid: str, days: int) -> Dict[str, Any]:
    """Módulo 7 — Ligo Protege (SecurityHome + Fleet/GPS)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    base_q: Dict[str, Any] = {}
    if cid and cid != DEMO_COMPANY_ID:
        base_q["company_id"] = cid

    cols = await db.list_collection_names()

    alarmes = await db.security_alarms.count_documents(base_q) \
        if "security_alarms" in cols else 0
    alarmes_periodo = 0
    if "security_alarms" in cols:
        alarmes_periodo = await db.security_alarms.count_documents(
            {**base_q, "created_at": {"$gte": cutoff}})

    sites = await db.security_sites.count_documents(base_q) \
        if "security_sites" in cols else 0
    sensores = await db.security_sensors.count_documents(base_q) \
        if "security_sensors" in cols else 0

    # Fleet (GPS)
    rastreadores = 0
    eventos_fleet = 0
    if "fleet_vehicles" in cols:
        rastreadores = await db.fleet_vehicles.count_documents(base_q)
    if "fleet_events" in cols:
        eventos_fleet = await db.fleet_events.count_documents(
            {**base_q, "created_at": {"$gte": cutoff}})

    return {
        "security": {
            "sites": sites, "sensores": sensores,
            "alarmes_totais": alarmes,
            "alarmes_no_periodo": alarmes_periodo,
        },
        "fleet": {
            "rastreadores": rastreadores,
            "eventos_no_periodo": eventos_fleet,
        },
    }


# ─────────────────── LLM synthesis ───────────────────
async def _ai_brief(company_id: str, period: str,
                     overview: Dict[str, Any],
                     network: Dict[str, Any],
                     technicians: Dict[str, Any],
                     atendimento: Dict[str, Any],
                     sales: Dict[str, Any],
                     universo: Dict[str, Any],
                     protege: Dict[str, Any]) -> Dict[str, Any]:
    """Chama o Motor IA pedindo um JSON estruturado com:
       overview_insight, network_insight, technicians_insight,
       atendimento_insight, sales_insight, universo_insight,
       protege_insight, parecer_executivo.

    Cada insight tem `interpretacao` (1-2 frases) + `recomendacao`
    (1-2 ações concretas). O parecer executivo é o texto final.
    """
    period_label = PERIOD_LABEL.get(period, period)
    prompt = f"""Você é o CONSELHEIRO ESTRATÉGICO IA do SmartProv,
sistema de gestão de provedores de internet (Ligo Fibra).
Analise os dados do período {period_label} abaixo e produza um
relatório executivo estruturado.

VISÃO GERAL:
{json.dumps(overview, ensure_ascii=False, indent=2)}

REDE E OPERAÇÃO:
{json.dumps(network, ensure_ascii=False, indent=2)}

TÉCNICOS:
{json.dumps(technicians, ensure_ascii=False, indent=2)}

ATENDIMENTO (Isabella/Álvaro/Humano):
{json.dumps(atendimento, ensure_ascii=False, indent=2)}

VENDAS:
{json.dumps(sales, ensure_ascii=False, indent=2)}

UNIVERSO LIGO (Fibra/De Casa/Conteúdos/Clube/Parceiros):
{json.dumps(universo, ensure_ascii=False, indent=2)}

LIGO PROTEGE (Security + Fleet):
{json.dumps(protege, ensure_ascii=False, indent=2)}

INSTRUÇÕES:
- Seja DIRETO, sem rodeios. Linguagem de conselheiro sênior.
- Use números EXATOS dos dados (não invente).
- Cada "interpretacao" deve ser 1 a 2 frases.
- Cada "recomendacao" deve ser 1 a 2 ações CONCRETAS.
- "parecer_executivo" tem 7 sub-itens fixos.
- NUNCA use emojis. Sem markdown. Tom profissional brasileiro.

Devolva APENAS um JSON válido nesse schema:
{{
  "overview_insight":     {{"interpretacao":"...", "recomendacao":"...",
                              "risco":"verde|amarelo|vermelho|azul"}},
  "network_insight":      {{"interpretacao":"...", "recomendacao":"...",
                              "risco":"verde|amarelo|vermelho|azul"}},
  "technicians_insight":  {{"interpretacao":"...", "recomendacao":"...",
                              "risco":"verde|amarelo|vermelho|azul"}},
  "atendimento_insight":  {{"interpretacao":"...", "recomendacao":"...",
                              "risco":"verde|amarelo|vermelho|azul"}},
  "sales_insight":        {{"interpretacao":"...", "recomendacao":"...",
                              "risco":"verde|amarelo|vermelho|azul"}},
  "universo_insight":     {{"interpretacao":"...", "recomendacao":"...",
                              "risco":"verde|amarelo|vermelho|azul"}},
  "protege_insight":      {{"interpretacao":"...", "recomendacao":"...",
                              "risco":"verde|amarelo|vermelho|azul"}},
  "parecer_executivo": {{
    "o_que_aconteceu": "1-2 parágrafos curtos",
    "o_que_merece_atencao": "1-2 parágrafos curtos",
    "o_que_esta_funcionando": "1-2 parágrafos curtos",
    "o_que_pode_crescer": "1-2 parágrafos curtos",
    "proximos_7_dias": "lista de 3 a 5 ações",
    "proximos_30_dias": "lista de 3 a 5 ações",
    "proximos_90_dias": "lista de 3 a 5 iniciativas"
  }}
}}

Cor de risco: "vermelho" = crítico, "amarelo" = atenção,
"verde" = saudável, "azul" = oportunidade."""
    try:
        resp = await chat_completion(
            company_id=company_id,
            messages=[
                {"role": "system",
                 "content": "Responda APENAS com JSON válido."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=3500,
            json_mode=True,
            agent="conselho_ia",
        )
        content = resp.get("content", "{}")
        # extrai JSON mesmo se vier com fences
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        data = json.loads(content.strip())
        return data
    except Exception as e:
        logger.exception("[conselho-ia] falha LLM: %s", e)
        # Fallback offline (sem LLM) — gera análise mecânica
        return _mechanical_fallback(period_label, overview, network,
                                     technicians, atendimento, sales,
                                     universo, protege)


def _mechanical_fallback(period_label: str,
                          overview: Dict[str, Any],
                          network: Dict[str, Any],
                          technicians: Dict[str, Any],
                          atendimento: Dict[str, Any],
                          sales: Dict[str, Any],
                          universo: Dict[str, Any],
                          protege: Dict[str, Any]) -> Dict[str, Any]:
    """Fallback offline (sem LLM) — gera análise mecânica."""
    churn = overview.get("churn_pct", 0)
    inad = overview.get("inadimplencia_pct", 0)
    novos = overview.get("novos_no_periodo", 0)
    risco_o = "vermelho" if churn > 5 or inad > 10 else \
        ("amarelo" if churn > 2 else "verde")
    sat = max([c.get("saturacao_pct", 0)
                 for c in network.get("ctos_saturadas", [])] or [0])
    risco_n = "vermelho" if sat > 85 else \
        ("amarelo" if sat > 70 else "verde")
    sent = atendimento.get("sentimento") or {}
    neg = sent.get("negativo", 0)
    pos = sent.get("positivo", 0)
    risco_at = "vermelho" if neg > pos * 2 else \
        ("amarelo" if neg > pos else "verde")
    risco_v = "verde" if sales.get("vendas_concluidas", 0) > 0 else "amarelo"
    return {
        "overview_insight": {
            "interpretacao": (
                f"{overview['ativos']} clientes ativos. "
                f"Churn em {churn}%, inadimplência em {inad}%. "
                f"{novos} novos no período {period_label.lower()}."),
            "recomendacao": (
                "Acionar régua de cobrança em inadimplentes."
                if inad > 5 else
                "Manter ações de retenção e prospecção atuais."),
            "risco": risco_o,
        },
        "network_insight": {
            "interpretacao": (
                f"{network['ctos']} CTOs, {network['onus_online']} ONUs "
                f"online, {network['onus_offline']} offline. "
                f"Potência média {network['potencia_media_dbm']} dBm."),
            "recomendacao": (
                "Inspecionar CTOs com >85% de saturação"
                if sat > 85 else
                "Rede dentro do esperado, monitorar saturação."),
            "risco": risco_n,
        },
        "technicians_insight": {
            "interpretacao": (
                f"{technicians.get('total_tarefas', 0)} tarefas "
                f"({technicians.get('instalacoes', 0)} instalações, "
                f"{technicians.get('reparos', 0)} reparos). Tempo médio "
                f"{technicians.get('tempo_medio_horas', 0)}h."),
            "recomendacao": "Acompanhar tempo médio e priorizar "
                "técnicos do top.",
            "risco": "verde",
        },
        "atendimento_insight": {
            "interpretacao": (
                f"{atendimento.get('isabella_conversas', 0)} conv. "
                f"Isabella, {atendimento.get('alvaro_analises', 0)} "
                f"análises Álvaro, {atendimento.get('atendimento_humano_msgs', 0)} "
                f"msgs humanas."),
            "recomendacao": ("Investigar pico de sentimento negativo."
                              if neg > pos else
                              "Manter qualidade atual do atendimento."),
            "risco": risco_at,
        },
        "sales_insight": {
            "interpretacao": (
                f"{sales.get('leads_total', 0)} leads, "
                f"{sales.get('vendas_concluidas', 0)} vendas concluídas, "
                f"conversão {sales.get('taxa_conversao_pct', 0)}%."),
            "recomendacao": ("Reforçar follow-up de leads abertos."
                              if sales.get('taxa_conversao_pct', 0) < 20
                              else "Manter pipeline e ampliar canais."),
            "risco": risco_v,
        },
        "universo_insight": {
            "interpretacao": (
                f"Base Ligo Fibra: "
                f"{universo['ligo_fibra']['base_ativa']} ativos. "
                f"{universo['clube_ligo']['indicacoes']} indicações, "
                f"{universo['parceiros_qr']['resgates']} resgates "
                f"de parceiros."),
            "recomendacao": "Estimular cross-sell entre módulos "
                "do Universo Ligo.",
            "risco": "azul",
        },
        "protege_insight": {
            "interpretacao": (
                f"{protege['security']['sites']} sites monitorados, "
                f"{protege['security']['alarmes_no_periodo']} alarmes no "
                f"período. {protege['fleet']['rastreadores']} "
                f"rastreadores ativos."),
            "recomendacao": "Avaliar oportunidade de upsell "
                "para base Fibra.",
            "risco": "azul",
        },
        "parecer_executivo": {
            "o_que_aconteceu": "Geração offline (LLM indisponível). "
                "Dados consolidados.",
            "o_que_merece_atencao": (
                "Inadimplência acima de 10%" if inad > 10
                else "Operação estável."),
            "o_que_esta_funcionando": "Base de clientes ativa.",
            "o_que_pode_crescer": "Captação em bairros já atendidos.",
            "proximos_7_dias": "1) Régua de cobrança. 2) Pesquisa NPS. "
                "3) Inspeção das CTOs saturadas.",
            "proximos_30_dias": "1) Revisão de planos. "
                "2) Campanha de retenção. 3) Expansão em bairros top.",
            "proximos_90_dias": "1) Plano de investimento em rede. "
                "2) Novos parceiros Clube Ligo. 3) Programa fidelidade.",
        },
    }


# ─────────────────── endpoints ───────────────────
class GenerateReportIn(BaseModel):
    period: str = Field("monthly")
    regenerate: bool = False


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


# iter215bt — Agente IA com Toolkit Executável
async def _agent_plan_and_execute(
        cid: str, overview: Dict[str, Any], network: Dict[str, Any],
        sales: Dict[str, Any]) -> Dict[str, Any]:
    """Pergunta ao LLM 'que ações concretas devo executar agora?'
    O LLM responde com chamadas estruturadas de ferramentas. Backend
    valida + executa (whitelist) e devolve os resultados.

    iter215bu — Memory Loop: agora também envia ao LLM as últimas
    execuções (≤14 dias) pra ele decidir se deve repetir, escalar
    ou pular ações já tomadas.
    """
    # Lista subscribers inadimplentes (até 50) e CTOs saturadas (>85%)
    inad_sample = await db.subscribers.find({
        **({"company_id": cid} if cid and cid != DEMO_COMPANY_ID else {}),
        "financial_status": {"$regex": "inadimp|atrasad",
                              "$options": "i"},
    }, {"_id": 0, "id": 1, "name": 1,
        "dunning_queue": 1, "dunning_flagged_at": 1}).limit(50).to_list(50)
    inad_ids = [s["id"] for s in inad_sample]
    cto_critic = [c for c in network.get("ctos_saturadas") or []
                   if c.get("saturacao_pct", 0) >= 85][:5]

    # iter215bu — Memory: últimas execuções (até 30 dias) AGRUPADAS por tool
    from datetime import timedelta as _td
    cutoff_mem = (datetime.now(timezone.utc) - _td(days=30)).isoformat()
    mem_cursor = db.conselho_ia_agent_actions.find({
        "company_id": cid,
        "created_at": {"$gte": cutoff_mem},
        "status": {"$in": ["executed", "pending"]},
    }, {"_id": 0, "tool": 1, "args": 1, "status": 1,
        "result": 1, "created_at": 1}).sort("created_at", -1).limit(40)
    memory = await mem_cursor.to_list(40)
    mem_summary: Dict[str, Dict[str, Any]] = {}
    for m in memory:
        t = m["tool"]
        if t not in mem_summary:
            mem_summary[t] = {"count": 0, "last_at": m["created_at"],
                                "last_args": m.get("args"),
                                "last_result": m.get("result")}
        mem_summary[t]["count"] += 1

    # Marca quais inadimplentes JÁ foram pra dunning queue recentemente
    already_flagged_ids = [
        s["id"] for s in inad_sample if s.get("dunning_queue") is True]

    catalog = llm_tool_catalog_prompt()
    prompt = f"""Você é o AGENTE IA do Conselho Estratégico.
Decida ações concretas pra executar AGORA com base nos dados E
no histórico recente de execuções.

CONTEXTO ATUAL:
- Inadimplentes detectados: {len(inad_ids)} total
  · Já marcados pra cobrança (NÃO repetir!): {len(already_flagged_ids)} ids
  · AINDA NÃO marcados: {[s['id'] for s in inad_sample if not s.get('dunning_queue')][:10]}
- CTOs com saturação ≥85%: {len(cto_critic)} ({[c.get('cto_id') for c in cto_critic]})
- MRR atual: R$ {overview.get('mrr_brl', 0)}
- Taxa conversão vendas: {sales.get('taxa_conversao_pct', 0)}%

HISTÓRICO DOS ÚLTIMOS 30 DIAS (execuções já tomadas):
{json.dumps(mem_summary, ensure_ascii=False, indent=2,
                default=str) if mem_summary else "  (Nenhuma execução prévia.)"}

{catalog}

REGRAS:
- Use APENAS as ferramentas do catálogo.
- NÃO repita ação se ela JÁ FOI executada recentemente pros
  MESMOS ids/CTOs/etc. Ex.: se um subscriber já tem dunning_queue=true,
  não chame flag_dunning de novo nele.
- Se a ação anterior NÃO RESOLVEU (ex.: subscriber ainda inadimplente
  após X dias com dunning_queue=true), considere ESCALAR — anotando
  isso na justificativa pra que humano possa avaliar.
- Justifique cada chamada citando dados/histórico.
- Máximo 3 ações por execução.
- NÃO invente ids. Só use os do contexto acima.
- Se não houver ação útil pra fazer, retorne lista vazia.

Devolva APENAS um JSON nesse schema:
{{
  "actions": [
    {{
      "tool": "nome_do_tool",
      "args": {{ ... }},
      "justification": "1 frase citando contexto/histórico"
    }}
  ]
}}"""
    try:
        resp = await chat_completion(
            company_id=cid,
            messages=[
                {"role": "system",
                 "content": "Responda APENAS com JSON válido."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2, max_tokens=900, json_mode=True,
            agent="conselho_ia_agent",
        )
        content = resp.get("content", "{}")
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        plan = json.loads(content.strip())
    except Exception as e:
        logger.exception("[agent_ia] LLM plan falhou: %s", e)
        return {"plan": [], "executions": [], "memory": mem_summary,
                 "error": str(e)}

    actions = plan.get("actions") or []
    executions = []
    for call in actions[:3]:
        if not isinstance(call, dict) or not call.get("tool"):
            continue
        res = await execute_tool_call(cid, call)
        res["justification"] = call.get("justification", "")
        res["args"] = call.get("args") or {}
        executions.append(res)

    return {"plan": actions, "executions": executions,
             "memory": mem_summary}


@router.post("/report")
async def generate_report(payload: GenerateReportIn,
                           user: dict = Depends(get_current_user)):
    period = payload.period.lower()
    if period not in PERIODS:
        raise HTTPException(400,
            f"Período inválido. Use um de: {', '.join(PERIODS)}")
    cid = _cid(user)
    days = PERIOD_DAYS[period]

    # Cache: se já existe report do dia/período, devolve sem regerar
    if not payload.regenerate:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cached = await db.conselho_ia_reports.find_one(
            {"company_id": cid, "period": period, "day": today},
            {"_id": 0})
        if cached:
            cached["from_cache"] = True
            return cached

    overview = await _collect_overview(cid, days)
    network = await _collect_network(cid, days)
    technicians = await _collect_technicians(cid, days)
    atendimento = await _collect_atendimento(cid, days)
    sales = await _collect_sales(cid, days)
    universo = await _collect_universo_ligo(cid, days)
    protege = await _collect_protege(cid, days)

    # iter215bs — Auditor IA: detecta e auto-corrige inconsistências
    # (whitelist) ANTES do LLM analisar, pra que o parecer já reflita
    # os dados corrigidos. Ações fora da whitelist viram "pending".
    auditor_result = await _run_auditor_ia(cid, sales)

    # Re-coleta apenas os módulos afetados por correções
    if auditor_result.get("total_records_fixed", 0) > 0:
        overview = await _collect_overview(cid, days)
        sales = await _collect_sales(cid, days)
        universo = await _collect_universo_ligo(cid, days)

    # iter215bt — Agente IA executa ações concretas baseado nos dados
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
        "generated_by": user.get("email", ""),
        "modules": {
            "overview": {
                "title": "Visão Geral da Empresa",
                "data": overview,
                "insight": ai_brief.get("overview_insight") or {},
            },
            "network": {
                "title": "Rede e Operação",
                "data": network,
                "insight": ai_brief.get("network_insight") or {},
            },
            "technicians": {
                "title": "Técnicos",
                "data": technicians,
                "insight": ai_brief.get("technicians_insight") or {},
            },
            "atendimento": {
                "title": "Atendimento",
                "data": atendimento,
                "insight": ai_brief.get("atendimento_insight") or {},
            },
            "sales": {
                "title": "Vendas",
                "data": sales,
                "insight": ai_brief.get("sales_insight") or {},
            },
            "universo": {
                "title": "Universo Ligo",
                "data": universo,
                "insight": ai_brief.get("universo_insight") or {},
            },
            "protege": {
                "title": "Ligo Protege",
                "data": protege,
                "insight": ai_brief.get("protege_insight") or {},
            },
        },
        "parecer_executivo": ai_brief.get("parecer_executivo") or {},
        "auditor": auditor_result,
        "agent": agent_result,
        "from_cache": False,
    }
    # Upsert: 1 relatório por (company, period, dia)
    await db.conselho_ia_reports.update_one(
        {"company_id": cid, "period": period, "day": report["day"]},
        {"$set": report}, upsert=True)
    return report


@router.get("/reports")
async def list_reports(limit: int = Query(20, ge=1, le=100),
                        user: dict = Depends(get_current_user)):
    cid = _cid(user)
    cur = db.conselho_ia_reports.find(
        {"company_id": cid}, {"_id": 0}) \
        .sort("generated_at", -1).limit(limit)
    items = await cur.to_list(limit)
    return {"items": items, "total": len(items)}


@router.get("/reports/{rid}")
async def get_report(rid: str,
                      user: dict = Depends(get_current_user)):
    cid = _cid(user)
    rep = await db.conselho_ia_reports.find_one(
        {"id": rid, "company_id": cid}, {"_id": 0})
    if not rep:
        raise HTTPException(404, "Relatório não encontrado")
    return rep


# iter215bs — Auditor IA: endpoints de gestão das ações
@router.get("/audit-log")
async def audit_log(limit: int = Query(100, ge=1, le=500),
                     status: Optional[str] = None,
                     user: dict = Depends(get_current_user)):
    """Lista o log de ações da auditoria (aplicadas/pendentes/erro)."""
    cid = _cid(user)
    q: Dict[str, Any] = {"company_id": cid}
    if status:
        q["status"] = status
    cur = db.conselho_ia_audit_log.find(q, {"_id": 0}) \
        .sort("created_at", -1).limit(limit)
    items = await cur.to_list(limit)
    return {"items": items, "total": len(items)}


class ResolvePendingIn(BaseModel):
    decision: str = Field(..., pattern="^(approved|rejected)$")
    notes: Optional[str] = ""


@router.post("/audit-log/{aid}/resolve")
async def resolve_pending(aid: str, payload: ResolvePendingIn,
                            user: dict = Depends(get_current_user)):
    """Aprova/rejeita uma ação pendente. Marca como `resolved`
    com decisão e auditor. Não executa ação - só registra decisão."""
    cid = _cid(user)
    rec = await db.conselho_ia_audit_log.find_one(
        {"id": aid, "company_id": cid}, {"_id": 0})
    if not rec:
        raise HTTPException(404, "Ação não encontrada")
    if rec.get("status") != "pending":
        raise HTTPException(409,
            f"Ação já está em status '{rec.get('status')}'")
    new_status = payload.decision  # approved | rejected
    await db.conselho_ia_audit_log.update_one(
        {"id": aid},
        {"$set": {"status": new_status,
                   "resolved_at": datetime.now(timezone.utc).isoformat(),
                   "resolved_by": user.get("email", ""),
                   "resolve_notes": (payload.notes or "").strip()}})
    return {"ok": True, "id": aid, "status": new_status}


# iter215bt — Agente IA
@router.get("/agent-actions")
async def agent_actions(limit: int = Query(100, ge=1, le=500),
                          status: Optional[str] = None,
                          user: dict = Depends(get_current_user)):
    """Lista ações executadas pelo agente IA."""
    cid = _cid(user)
    q: Dict[str, Any] = {"company_id": cid}
    if status:
        q["status"] = status
    cur = db.conselho_ia_agent_actions.find(q, {"_id": 0}) \
        .sort("created_at", -1).limit(limit)
    items = await cur.to_list(limit)
    return {"items": items, "total": len(items)}


@router.get("/agent-tools")
async def agent_tools_catalog(user: dict = Depends(get_current_user)):
    """Lista o catálogo de ferramentas disponíveis pro agente."""
    return {"tools": [
        {"name": name, "auto_apply": spec.get("auto_apply", False),
         "description": spec["description"],
         "args_schema": spec["args_schema"]}
        for name, spec in TOOL_CATALOG.items()
    ]}


# iter215bw — Configurações de notificação proativa
class NotifySettingsIn(BaseModel):
    notify_on_action: bool = False
    notify_phone: Optional[str] = ""
    cron_enabled: bool = False
    cron_hour_utc: Optional[int] = 11   # 08:00 BRT default


@router.get("/settings")
async def get_settings(user: dict = Depends(get_current_user)):
    cid = _cid(user)
    cfg = await db.conselho_ia_settings.find_one(
        {"company_id": cid}, {"_id": 0}) or {
            "company_id": cid, "notify_on_action": False,
            "notify_phone": "", "cron_enabled": False,
            "cron_hour_utc": 11}
    return cfg


@router.put("/settings")
async def update_settings(payload: NotifySettingsIn,
                            user: dict = Depends(get_current_user)):
    cid = _cid(user)
    phone = (payload.notify_phone or "").strip()
    digits = "".join(c for c in phone if c.isdigit())
    if payload.notify_on_action and len(digits) < 10:
        raise HTTPException(400,
            "Telefone inválido (mín. 10 dígitos com DDD).")
    hour = int(payload.cron_hour_utc or 11)
    if hour < 0 or hour > 23:
        raise HTTPException(400, "Hora inválida (0-23 UTC).")
    await db.conselho_ia_settings.update_one(
        {"company_id": cid},
        {"$set": {
            "company_id": cid,
            "notify_on_action": bool(payload.notify_on_action),
            "notify_phone": digits,
            "cron_enabled": bool(payload.cron_enabled),
            "cron_hour_utc": hour,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": user.get("email", ""),
        }}, upsert=True)
    return {"ok": True}
