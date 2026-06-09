"""
diagnostic.py — Diagnóstico Completo do SmartProv (iter215by)
Endpoint único que devolve todas as 16 seções pra renderizar
em página imprimível (PDF).
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends

from core import DEMO_COMPANY_ID, get_current_user
from database import db
from services.motor_ia import chat_completion
from routes.conselho_ia import (
    _collect_overview, _collect_network, _collect_technicians,
    _collect_atendimento, _collect_sales, _collect_universo_ligo,
    _collect_protege,
)

router = APIRouter(prefix="/api/diagnostic", tags=["diagnostic"])


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


# Catálogo estático de módulos do sistema (verdade declarada)
MODULOS = [
    {"nome": "Painel · Atlaz Import", "status": "Produção",
     "objetivo": "Importação de assinantes do Atlaz",
     "funcionalidades": ["Sincronização", "Auditoria"]},
    {"nome": "SmartOLT", "status": "Produção",
     "objetivo": "Gestão de OLTs/ONUs/CTOs"},
    {"nome": "Rede IA", "status": "Produção",
     "objetivo": "Topologia + Mapa interativo + Ligo Maps GIS"},
    {"nome": "Motor IA", "status": "Produção",
     "objetivo": "Camada de IA (Isabella, Álvaro, Avaliador, etc.)"},
    {"nome": "Conselho Estratégico IA", "status": "Produção",
     "objetivo": "Camada executiva acima do Motor IA"},
    {"nome": "Auditoria · Histórico", "status": "Produção",
     "objetivo": "Trilha de eventos completa"},
    {"nome": "Estoque", "status": "Produção",
     "objetivo": "Itens, técnicos, NFs"},
    {"nome": "Orçamento", "status": "Produção",
     "objetivo": "Leads + Propostas comerciais"},
    {"nome": "Parcerias (Clube Ligo)", "status": "Produção",
     "objetivo": "Promoções de parceiros + QR + Redenções"},
    {"nome": "Indique e Ganhe", "status": "Produção",
     "objetivo": "Indicações + cashback"},
    {"nome": "Clientes Fidelidade", "status": "Produção"},
    {"nome": "WiFi Hotspot", "status": "Desenvolvimento"},
    {"nome": "Ponto · Holerite · Férias", "status": "Produção"},
    {"nome": "Financeiro · Faturamento", "status": "Produção"},
    {"nome": "Fleet/GPS Tracker", "status": "Produção"},
    {"nome": "Ligo Protege (SecurityHome)", "status": "Desenvolvimento"},
    {"nome": "Drive Backup", "status": "Produção"},
    {"nome": "NFCom", "status": "Planejado"},
    {"nome": "Asaas Contas a Pagar", "status": "Planejado"},
]

AGENTES_IA = [
    {"nome": "Isabella",
      "objetivo": "Atendente virtual no WhatsApp",
      "entradas": "Mensagens dos clientes",
      "saidas": "Respostas + escalonamento humano",
      "ferramentas": "Claude Sonnet, OpenRouter, Baileys"},
    {"nome": "Álvaro",
      "objetivo": "Analisa chamados/conversas e detecta sentimento",
      "entradas": "Tickets + transcrições",
      "saidas": "Score, sentimento, próximas ações",
      "ferramentas": "Claude 4.5"},
    {"nome": "Router IA",
      "objetivo": "Decide qual modelo LLM usar por tarefa",
      "entradas": "Tipo de tarefa + custo",
      "saidas": "Modelo selecionado"},
    {"nome": "Avaliador IA",
      "objetivo": "Pontua respostas de agentes",
      "entradas": "Histórico de conversas",
      "saidas": "Score 0-100"},
    {"nome": "Sentinela",
      "objetivo": "Monitora anomalias de rede e operação",
      "entradas": "Dados de tickets + ONUs offline",
      "saidas": "Alertas executivos"},
    {"nome": "Auditor IA",
      "objetivo": "Corrige inconsistências em massa (whitelist)",
      "entradas": "Subscribers/Plans",
      "saidas": "Updates no banco + log",
      "ferramentas": "Deterministic Python"},
    {"nome": "Agente IA Conselho",
      "objetivo": "Decide e executa ações concretas",
      "entradas": "Contexto de KPIs + histórico",
      "saidas": "Tool calls (flag_dunning, criar tickets)",
      "ferramentas": "Anthropic Claude via OpenRouter"},
]

INTEGRACOES = [
    {"nome": "SmartOLT API V2", "status": "Ativo"},
    {"nome": "Atlaz Import", "status": "Ativo"},
    {"nome": "Sicoob (Boletos/PIX)", "status": "Ativo"},
    {"nome": "WhatsApp Baileys (sidecars)", "status": "Ativo"},
    {"nome": "WhatsApp Evolution (legado)", "status": "Inativo"},
    {"nome": "OpenRouter (Anthropic Claude)", "status": "Ativo"},
    {"nome": "Emergent LLM Key", "status": "Ativo"},
    {"nome": "Google Drive (Backup)", "status": "Ativo"},
    {"nome": "OpenStreetMap / Leaflet", "status": "Ativo"},
    {"nome": "TR-069 SmartOLT", "status": "Ativo"},
    {"nome": "Asaas (Contas a Pagar)", "status": "Planejado"},
    {"nome": "NFCom", "status": "Planejado"},
]


async def _section_counts(cid: str) -> Dict[str, Any]:
    base = {} if cid == DEMO_COMPANY_ID else {"company_id": cid}
    cols = await db.list_collection_names()
    async def c(name, q=None):
        if name not in cols:
            return 0
        return await db[name].count_documents(q if q else base)
    return {
        "subscribers": await c("subscribers"),
        "users": await c("users"),
        "technicians": await c("technicians"),
        "tickets": await c("tickets"),
        "plans": await c("plans"),
        "ctos": await c("ctos"),
        "olts": await c("olts"),
        "vlans": await c("vlans"),
        "partners": await c("parcerias_partners"),
        "promotions": await c("parcerias_promotions"),
        "redemptions": await c("parcerias_redemptions"),
        "referrals": await c("referrals"),
        "fleet_vehicles": await c("fleet_vehicles"),
        "stock_items": await c("stock_items"),
        "automations": await c("automations"),
    }


@router.get("/full")
async def diagnostic_full(user: dict = Depends(get_current_user)):
    cid = _cid(user)
    days = 30

    # Reusa coletores existentes do conselho_ia
    overview = await _collect_overview(cid, days)
    network = await _collect_network(cid, days)
    techs = await _collect_technicians(cid, days)
    aten = await _collect_atendimento(cid, days)
    sales = await _collect_sales(cid, days)
    universo = await _collect_universo_ligo(cid, days)
    protege = await _collect_protege(cid, days)
    counts = await _section_counts(cid)

    # LLM — autoanálise + parecer CTO/COO/CPO/CEO
    ai_text: Dict[str, Any] = {}
    try:
        prompt = f"""Você é CTO, COO, CPO e CEO em uma só voz analisando
o SmartProv (sistema de gestão para provedores de internet — Ligo).

DADOS:
- Visão Geral: {json.dumps(overview, ensure_ascii=False)[:800]}
- Rede: {json.dumps(network, ensure_ascii=False)[:600]}
- Técnicos: {json.dumps(techs, ensure_ascii=False)[:400]}
- Vendas: {json.dumps(sales, ensure_ascii=False)[:400]}
- Universo Ligo: {json.dumps(universo, ensure_ascii=False)[:500]}
- Counts: {json.dumps(counts, ensure_ascii=False)}

Responda APENAS em JSON, sem markdown, sem emojis:
{{
  "autoanalise": {{
    "pontos_fortes": "...",
    "gargalos": "...",
    "faltando": "...",
    "duplicado": "...",
    "simplificavel": "...",
    "valor_ligo": "...",
    "valor_cliente": "...",
    "valor_colaborador": "...",
    "valor_parceiros": "...",
    "prioridades_90d": "lista de 5 ações priorizadas"
  }},
  "parecer_executivo": {{
    "onde_estamos": "...",
    "ja_construido": "...",
    "o_que_falta": "...",
    "proximo_passo": "...",
    "risco_atual": "...",
    "maior_oportunidade": "...",
    "visao_12m": "...",
    "visao_36m": "..."
  }}
}}"""
        resp = await chat_completion(
            company_id=cid,
            messages=[{"role": "system",
                         "content": "Responda APENAS com JSON válido."},
                       {"role": "user", "content": prompt}],
            temperature=0.4, max_tokens=2500, json_mode=True,
            agent="diagnostic_full")
        content = resp.get("content", "{}")
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        ai_text = json.loads(content.strip())
    except Exception as e:
        ai_text = {"error": str(e)}

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "versao": "iter215by",
        "executive_summary": {
            "versao": "iter215by",
            "data": datetime.now(timezone.utc).isoformat(),
            "total_modulos": len(MODULOS),
            "modulos_ativos": sum(1 for m in MODULOS
                                    if m["status"] == "Produção"),
            "modulos_dev": sum(1 for m in MODULOS
                                 if m["status"] == "Desenvolvimento"),
            "usuarios": counts["users"],
            "clientes": counts["subscribers"],
            "colaboradores": counts["technicians"],
            "integracoes_ativas": sum(1 for i in INTEGRACOES
                                        if i["status"] == "Ativo"),
        },
        "modulos": MODULOS,
        "motor_ia": {
            "arquitetura": "Multi-agente assíncrono baseado em OpenRouter "
                "+ Emergent LLM Key",
            "modelos": ["claude-sonnet-4-5", "claude-haiku-4-5",
                         "gpt-4o-mini", "gemini-flash"],
            "provedores": ["OpenRouter", "Emergent LLM Key"],
            "agentes": AGENTES_IA,
        },
        "base_dados": counts,
        "operacao": {
            "clientes_ativos": overview.get("ativos"),
            "clientes_suspensos": overview.get("suspensos"),
            "clientes_cancelados": overview.get("cancelados"),
            "novos_no_periodo": overview.get("novos_no_periodo"),
            "instalacoes": techs.get("instalacoes"),
            "reparos": techs.get("reparos"),
            "tempo_medio_h": techs.get("tempo_medio_horas"),
        },
        "rede": network,
        "universo_ligo": universo,
        "gps_monitoramento": protege.get("fleet"),
        "seguranca": protege.get("security"),
        "financeiro": {
            "mrr_brl": overview.get("mrr_brl"),
            "ticket_medio_brl": overview.get("ticket_medio_brl"),
            "inadimplencia_pct": overview.get("inadimplencia_pct"),
        },
        "kpis": [
            {"nome": "MRR", "objetivo": "Receita recorrente",
             "formula": "Σ plan_price_brl ativos",
             "atual": overview.get("mrr_brl"), "meta": None},
            {"nome": "Churn", "objetivo": "Saída de clientes",
             "formula": "cancelados / total",
             "atual": overview.get("churn_pct"), "meta": "< 2%"},
            {"nome": "Inadimplência", "objetivo": "Atrasos",
             "formula": "inadimplentes / ativos",
             "atual": overview.get("inadimplencia_pct"), "meta": "< 5%"},
            {"nome": "Saturação CTOs", "objetivo": "Capacidade",
             "formula": "clientes / portas",
             "atual": max([c.get("saturacao_pct", 0)
                            for c in network.get("ctos_saturadas") or []]
                           or [0]), "meta": "< 80%"},
        ],
        "automacoes": [
            "Reajuste IPCA (cron)", "Churn scheduler",
            "Drive backup", "AI training (offline)",
            "Conselho IA (cron diário)",
            "Auto auditor de dados (whitelist)",
            "WhatsApp auto reconnect",
        ],
        "integracoes": INTEGRACOES,
        "atendimento": aten,
        "vendas": sales,
        "tecnicos": techs,
        "ai_analysis": ai_text,
    }
