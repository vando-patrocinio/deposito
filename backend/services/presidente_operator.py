"""
presidente_operator.py — Presidente IA vira OPERADOR (não analista).

Implementa 3 motores operacionais sobre dados reais já no banco:

  1. Motor de Oportunidades  ("se eu tivesse que gerar R$10k hoje...")
  2. Motor de Economia        ("se eu tivesse que economizar R$10k hoje...")
  3. Motor de Recuperação     ("qual dinheiro está abandonado?")

E expõe:
  - Matriz de Autonomia (4 níveis) das 12 ações operacionais
  - Briefing matinal (6 perguntas obrigatórias)
  - Execução do dia (varre N1+N2, dispara executor_ia)
  - Seed das 8 metas corporativas permanentes (idempotente)

Nada novo na arquitetura cognitiva. Apenas operação sobre o que já
existe: motor_ia_actions, corporate_goals, subscribers, invoices,
smartolt_onus, motor_ia_subscriber_scores.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from database import db
from services import executor_ia as ex

log = logging.getLogger("presidente_operator")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


# ─────────────────────────────────────────────
#  MATRIZ DE AUTONOMIA (4 níveis)
# ─────────────────────────────────────────────
#   N1: autônoma                — sem aprovação
#   N2: autônoma c/ auditoria   — N1 + log obrigatório, revisão posterior
#   N3: necessita aprovação     — humano OK antes de executar
#   N4: somente humano          — IA propõe, humano executa fora do executor
AUTONOMY_MATRIX: Dict[str, Dict[str, Any]] = {
    # ────── Já existentes em executor_ia ──────
    "CRIACAO_OS_SMARTFIELD": {
        "nivel": "N1",
        "objetivo": "OS preventiva para ONUs em estado crítico",
        "meta": "reduzir_churn_tecnico",
        "categoria_executavel": True,
    },
    "CONTATO_LEO_PROATIVO": {
        "nivel": "N1",
        "objetivo": "Mensagem proativa Leo para clientes em risco técnico",
        "meta": "aumentar_retencao",
        "categoria_executavel": True,
    },
    "CAMPANHA_RETENCAO": {
        "nivel": "N2",
        "objetivo": "Campanha em massa para clientes em risco de churn",
        "meta": "reduzir_churn",
        "categoria_executavel": True,
    },
    "DISPARO_COBRANCA": {
        "nivel": "N2",
        "objetivo": "Régua de cobrança em inadimplentes",
        "meta": "reduzir_inadimplencia",
        "categoria_executavel": True,
    },
    "REAJUSTE_IPCA": {
        "nivel": "N3",
        "objetivo": "Reajuste IPCA em contratos >12m sem reajuste",
        "meta": "aumentar_mrr",
        "categoria_executavel": True,
    },
    # ────── Operacionais novos (alvos de expansão) ──────
    "REATIVACAO_CANCELADO": {
        "nivel": "N3",
        "objetivo": "Reativar contratos cancelados recentemente (<90d)",
        "meta": "aumentar_mrr",
        "categoria_executavel": False,  # ainda sem handler — usa LEO
    },
    "UPGRADE_PLANO_OFERTA": {
        "nivel": "N3",
        "objetivo": "Oferecer upgrade a clientes em plano abaixo da média",
        "meta": "aumentar_ltv",
        "categoria_executavel": False,
    },
    "CROSS_SELL_SECURITY": {
        "nivel": "N4",
        "objetivo": "Venda Security Home para subs ativos elegíveis",
        "meta": "aumentar_ltv",
        "categoria_executavel": False,
    },
    "RECUPERACAO_EQUIPAMENTO": {
        "nivel": "N3",
        "objetivo": "Retirar ONU/equipamento de contratos cancelados",
        "meta": "recuperar_capex",
        "categoria_executavel": False,
    },
    "INDICACAO_PROACTIVE": {
        "nivel": "N1",
        "objetivo": "Convite a clientes happy para indicar amigos",
        "meta": "aumentar_mrr",
        "categoria_executavel": False,
    },
    "PREVENTIVE_MAINT_OLT": {
        "nivel": "N2",
        "objetivo": "Manutenção preventiva por OLT com mass-outage",
        "meta": "reduzir_churn_tecnico",
        "categoria_executavel": False,
    },
    "TICKET_RECURRING_TRIAGEM": {
        "nivel": "N1",
        "objetivo": "Triagem automática de clientes 3+ tickets",
        "meta": "aumentar_retencao",
        "categoria_executavel": False,
    },
}


# ─────────────────────────────────────────────
#  METAS PERMANENTES (8 metas corporativas)
# ─────────────────────────────────────────────
PERMANENT_GOALS: List[Dict[str, Any]] = [
    {"goal_id": "aumentar_mrr",
      "name": "Aumentar MRR",
      "metric": "mrr_brl", "direction": "up",
      "delta_target_pct": 5.0},
    {"goal_id": "reduzir_churn",
      "name": "Reduzir Churn",
      "metric": "churn_previsto_30d_brl", "direction": "down",
      "delta_target_pct": 10.0},
    {"goal_id": "reduzir_inadimplencia",
      "name": "Reduzir Inadimplência",
      "metric": "dinheiro_em_risco_brl", "direction": "down",
      "delta_target_pct": 15.0},
    {"goal_id": "aumentar_ltv",
      "name": "Aumentar LTV",
      "metric": "ticket_medio_brl", "direction": "up",
      "delta_target_pct": 3.0},
    {"goal_id": "aumentar_retencao",
      "name": "Aumentar Retenção",
      "metric": "clientes_ativos", "direction": "up",
      "delta_target_pct": 2.0},
    {"goal_id": "recuperar_capex",
      "name": "Recuperar CAPEX (equipamentos)",
      "metric": "equipment_recovered_brl", "direction": "up",
      "delta_target_pct": 100.0},
    {"goal_id": "aumentar_upsell",
      "name": "Aumentar Upsell",
      "metric": "upsell_count", "direction": "up",
      "delta_target_pct": 100.0},
    {"goal_id": "aumentar_produtividade_tecnica",
      "name": "Aumentar Produtividade Técnica",
      "metric": "score_operacao", "direction": "up",
      "delta_target_pct": 5.0},
]


async def seed_permanent_goals(company_id: str) -> Dict[str, Any]:
    """Cria/atualiza as 8 metas permanentes. Idempotente."""
    created, updated = 0, 0
    now_iso = _iso(_now())
    for g in PERMANENT_GOALS:
        doc = {"company_id": company_id,
                 **g, "permanent": True,
                 "updated_at": now_iso}
        r = await db.corporate_goals.update_one(
            {"company_id": company_id, "goal_id": g["goal_id"]},
            {"$set": doc, "$setOnInsert": {"created_at": now_iso}},
            upsert=True)
        if r.upserted_id:
            created += 1
        else:
            updated += 1
    return {"created": created, "updated": updated,
              "total": len(PERMANENT_GOALS)}


async def list_goals(company_id: str) -> List[Dict[str, Any]]:
    return await db.corporate_goals.find(
        {"company_id": company_id, "permanent": True},
        {"_id": 0}).to_list(20)


# ─────────────────────────────────────────────
#  MOTOR 1 — OPORTUNIDADES ("gerar R$10k hoje")
# ─────────────────────────────────────────────
async def opportunities_today(company_id: str,
                                   target_brl: float = 10_000.0
                                   ) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []

    # OP1 — Reajuste IPCA 4,5%
    pipe = [{"$match": {"company_id": company_id,
                            "status": {"$in": ["ATIVO", "ATIVA"]},
                            "plan_price": {"$gt": 0}}},
             {"$group": {"_id": None,
                            "mrr": {"$sum": "$plan_price"},
                            "n": {"$sum": 1}}}]
    async for r in db.subscribers.aggregate(pipe):
        ganho = round(r["mrr"] * 0.045, 2)
        items.append({
            "id": "OP_REAJUSTE_IPCA",
            "categoria": "REAJUSTE_IPCA",
            "headline": f"Reajuste IPCA 4,5% em {r['n']} contratos",
            "impacto_brl_recorrente": ganho,
            "impacto_brl_unico": 0.0,
            "esforco": "BAIXO",
            "nivel_autonomia": AUTONOMY_MATRIX["REAJUSTE_IPCA"]["nivel"],
            "executavel": True,
            "evidencia": {"contratos": r["n"], "mrr_base": r["mrr"]},
        })

    # OP2 — Upgrade de plano
    avg = 0.0
    async for r in db.subscribers.aggregate(
        [{"$match": {"company_id": company_id,
                       "plan_price": {"$gt": 0}}},
         {"$group": {"_id": None, "avg": {"$avg": "$plan_price"}}}]):
        avg = r["avg"]
    below = await db.subscribers.count_documents(
        {"company_id": company_id, "status": {"$in":
            ["ATIVO", "ATIVA"]}, "plan_price": {"$gt": 0, "$lt": avg}})
    if below > 0 and avg > 0:
        # Estimativa conservadora: 5% aceita, ganho = 30% do delta médio
        delta_pct = 0.30
        accept_rate = 0.05
        ganho = round(below * accept_rate * avg * delta_pct, 2)
        items.append({
            "id": "OP_UPGRADE_PLANO",
            "categoria": "UPGRADE_PLANO_OFERTA",
            "headline": f"Oferta upgrade a {below} clientes abaixo da média",
            "impacto_brl_recorrente": ganho,
            "impacto_brl_unico": 0.0,
            "esforco": "MÉDIO",
            "nivel_autonomia":
                AUTONOMY_MATRIX["UPGRADE_PLANO_OFERTA"]["nivel"],
            "executavel": False,
            "evidencia": {"candidatos": below, "plan_avg": round(avg, 2),
                            "accept_rate_assumido": accept_rate},
        })

    # OP3 — Reativação cancelados
    n_canc = await db.subscribers.count_documents(
        {"company_id": company_id, "status": {"$in":
            ["CANCELADO", "INATIVO", "Cancelado", "cancelado"]}})
    if n_canc > 0 and avg > 0:
        # 8% reativam, primeira fatura mensal
        accept_rate = 0.08
        ganho = round(n_canc * accept_rate * avg, 2)
        items.append({
            "id": "OP_REATIVACAO",
            "categoria": "REATIVACAO_CANCELADO",
            "headline": f"Reativar {n_canc} cancelados (taxa 8%)",
            "impacto_brl_recorrente": ganho,
            "impacto_brl_unico": 0.0,
            "esforco": "MÉDIO",
            "nivel_autonomia":
                AUTONOMY_MATRIX["REATIVACAO_CANCELADO"]["nivel"],
            "executavel": False,
            "evidencia": {"cancelados": n_canc,
                            "accept_rate_assumido": accept_rate},
        })

    # OP4 — Indicações ativas
    n_subs_ativos = await db.subscribers.count_documents(
        {"company_id": company_id, "status": {"$in":
            ["ATIVO", "ATIVA"]}})
    n_existing_refs = await db.referrals.count_documents(
        {"company_id": company_id})
    # Cada indicação convertida assume ticket médio
    target_refs = min(50, max(0, n_subs_ativos // 100))
    if target_refs > 0 and avg > 0:
        accept_rate = 0.20
        ganho = round(target_refs * accept_rate * avg, 2)
        items.append({
            "id": "OP_INDICACAO",
            "categoria": "INDICACAO_PROACTIVE",
            "headline": (f"Convidar {target_refs} clientes happy a "
                          "indicar (20% conv.)"),
            "impacto_brl_recorrente": ganho,
            "impacto_brl_unico": 0.0,
            "esforco": "BAIXO",
            "nivel_autonomia":
                AUTONOMY_MATRIX["INDICACAO_PROACTIVE"]["nivel"],
            "executavel": False,
            "evidencia": {"subs_ativos": n_subs_ativos,
                            "indicacoes_existentes": n_existing_refs,
                            "alvo": target_refs},
        })

    items.sort(key=lambda x: x["impacto_brl_recorrente"]
                + x["impacto_brl_unico"], reverse=True)
    sum_total = sum(x["impacto_brl_recorrente"] + x["impacto_brl_unico"]
                     for x in items)
    return {
        "pergunta": f"Se eu tivesse que gerar R$ {target_brl:.0f} hoje, "
                     "o que eu faria?",
        "target_brl": target_brl,
        "potencial_total_brl": round(sum_total, 2),
        "atinge_meta": sum_total >= target_brl,
        "acoes": items,
        "generated_at": _iso(_now()),
    }


# ─────────────────────────────────────────────
#  MOTOR 2 — ECONOMIA ("economizar R$10k hoje")
# ─────────────────────────────────────────────
async def savings_today(company_id: str,
                              target_brl: float = 10_000.0
                              ) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []

    # SAV1 — OS preventivas em ONUs Critical (evita visita corretiva)
    n_critical = await db.smartolt_onus.count_documents(
        {"company_id": company_id,
         "status": {"$in": ["LOS", "Power fail"]}})
    if n_critical > 0:
        # Custo médio de visita corretiva R$ 80 (conservador)
        custo_evitado = round(n_critical * 80, 2)
        items.append({
            "id": "SAV_OS_PREVENTIVA",
            "categoria": "CRIACAO_OS_SMARTFIELD",
            "headline": f"OS preventiva em {n_critical} ONUs críticas "
                          "antes do cliente reclamar",
            "impacto_brl_unico": custo_evitado,
            "impacto_brl_recorrente": 0.0,
            "esforco": "BAIXO",
            "nivel_autonomia":
                AUTONOMY_MATRIX["CRIACAO_OS_SMARTFIELD"]["nivel"],
            "executavel": True,
            "evidencia": {"onus_criticas": n_critical,
                            "custo_visita_unitario": 80},
        })

    # SAV2 — Recuperação de equipamentos em cancelados
    n_canc = await db.subscribers.count_documents(
        {"company_id": company_id, "status": {"$in":
            ["CANCELADO", "INATIVO", "Cancelado", "cancelado"]}})
    if n_canc > 0:
        # ONU custa ~R$ 120 cada
        custo_recup = round(n_canc * 120, 2)
        items.append({
            "id": "SAV_RECUP_EQUIP",
            "categoria": "RECUPERACAO_EQUIPAMENTO",
            "headline": f"Retirar ONU de {n_canc} cancelados (CAPEX)",
            "impacto_brl_unico": custo_recup,
            "impacto_brl_recorrente": 0.0,
            "esforco": "MÉDIO",
            "nivel_autonomia":
                AUTONOMY_MATRIX["RECUPERACAO_EQUIPAMENTO"]["nivel"],
            "executavel": False,
            "evidencia": {"cancelados": n_canc,
                            "onu_unitario": 120},
        })

    # SAV3 — Manutenção preventiva por OLT em mass-outage (evita
    # múltiplas visitas individuais)
    pipe = [
        {"$match": {"company_id": company_id,
                       "status": {"$in":
                                     ["Offline", "LOS", "Power fail"]}}},
        {"$group": {"_id": "$olt_name", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gte": 10}}},
    ]
    mass_olts = []
    async for r in db.smartolt_onus.aggregate(pipe):
        mass_olts.append({"olt": r["_id"], "onus_ruins": r["n"]})
    if mass_olts:
        # Cada OLT consolidada economiza ~10 visitas × R$80 = R$800
        custo_evitado = sum(80 * (x["onus_ruins"] - 1)
                              for x in mass_olts)
        items.append({
            "id": "SAV_PREVENT_OLT",
            "categoria": "PREVENTIVE_MAINT_OLT",
            "headline": (f"Consolidar manutenção em {len(mass_olts)} "
                          "OLTs em mass-outage"),
            "impacto_brl_unico": round(custo_evitado, 2),
            "impacto_brl_recorrente": 0.0,
            "esforco": "BAIXO",
            "nivel_autonomia":
                AUTONOMY_MATRIX["PREVENTIVE_MAINT_OLT"]["nivel"],
            "executavel": False,
            "evidencia": {"olts": mass_olts},
        })

    items.sort(key=lambda x: x["impacto_brl_unico"]
                + x["impacto_brl_recorrente"], reverse=True)
    sum_total = sum(x["impacto_brl_unico"] + x["impacto_brl_recorrente"]
                     for x in items)
    return {
        "pergunta": f"Se eu tivesse que economizar R$ {target_brl:.0f} "
                     "hoje, o que eu faria?",
        "target_brl": target_brl,
        "potencial_total_brl": round(sum_total, 2),
        "atinge_meta": sum_total >= target_brl,
        "acoes": items,
        "generated_at": _iso(_now()),
    }


# ─────────────────────────────────────────────
#  MOTOR 3 — RECUPERAÇÃO ("dinheiro abandonado")
# ─────────────────────────────────────────────
async def recovery_today(company_id: str) -> Dict[str, Any]:
    buckets: List[Dict[str, Any]] = []

    # REC1 — Inadimplência total
    pipe = [{"$match": {"company_id": company_id, "status": "overdue"}},
             {"$group": {"_id": None,
                            "n": {"$sum": 1},
                            "total": {"$sum": "$amount"}}}]
    async for r in db.subscriber_invoices.aggregate(pipe):
        buckets.append({
            "id": "REC_INADIMPLENCIA",
            "categoria": "DISPARO_COBRANCA",
            "headline": f"{r['n']} faturas overdue · R$ "
                          f"{r['total']:.2f} em risco",
            "valor_abandonado_brl": round(r["total"], 2),
            "valor_recuperavel_brl_estimado":
                round(r["total"] * 0.18, 2),   # 18% conservador
            "executavel": True,
            "nivel_autonomia":
                AUTONOMY_MATRIX["DISPARO_COBRANCA"]["nivel"],
            "evidencia": {"faturas": r["n"]},
        })

    # REC2 — Contratos sem reajuste há > 12m
    cutoff = _iso(_now() - timedelta(days=365))
    pipe = [{"$match": {"company_id": company_id,
                            "status": {"$in": ["ATIVO", "ATIVA"]},
                            "plan_price": {"$gt": 0},
                            "$or": [
                                {"last_readjustment_at": None},
                                {"last_readjustment_at":
                                     {"$exists": False}},
                                {"last_readjustment_at":
                                     {"$lt": cutoff}}]}},
             {"$group": {"_id": None,
                            "n": {"$sum": 1},
                            "mrr": {"$sum": "$plan_price"}}}]
    async for r in db.subscribers.aggregate(pipe):
        ganho_anual = round(r["mrr"] * 0.045 * 12, 2)
        buckets.append({
            "id": "REC_REAJUSTE_ATRASADO",
            "categoria": "REAJUSTE_IPCA",
            "headline": (f"{r['n']} contratos sem reajuste há >12m · "
                          f"+R$ {ganho_anual:.2f}/ano possíveis"),
            "valor_abandonado_brl": ganho_anual,
            "valor_recuperavel_brl_estimado":
                round(ganho_anual * 0.9, 2),   # 90% se reajustar
            "executavel": True,
            "nivel_autonomia": AUTONOMY_MATRIX["REAJUSTE_IPCA"]["nivel"],
            "evidencia": {"contratos": r["n"], "mrr_base": r["mrr"]},
        })

    # REC3 — Clientes potencial upgrade (LTV abandonado)
    avg = 0.0
    async for r in db.subscribers.aggregate(
        [{"$match": {"company_id": company_id,
                       "plan_price": {"$gt": 0}}},
         {"$group": {"_id": None, "avg": {"$avg": "$plan_price"}}}]):
        avg = r["avg"]
    below = await db.subscribers.count_documents(
        {"company_id": company_id,
         "status": {"$in": ["ATIVO", "ATIVA"]},
         "plan_price": {"$gt": 0, "$lt": avg}})
    if below > 0 and avg > 0:
        ltv_gap = round(below * (avg * 0.3) * 12, 2)  # 30% delta × 12 m
        buckets.append({
            "id": "REC_UPGRADE_LTV",
            "categoria": "UPGRADE_PLANO_OFERTA",
            "headline": (f"{below} clientes podem aumentar plano · "
                          f"R$ {ltv_gap:.2f} LTV/ano abandonado"),
            "valor_abandonado_brl": ltv_gap,
            "valor_recuperavel_brl_estimado":
                round(ltv_gap * 0.05, 2),  # 5% conversion
            "executavel": False,
            "nivel_autonomia":
                AUTONOMY_MATRIX["UPGRADE_PLANO_OFERTA"]["nivel"],
            "evidencia": {"candidatos": below,
                            "plan_avg": round(avg, 2)},
        })

    # REC4 — Equipamentos não recuperados
    n_canc = await db.subscribers.count_documents(
        {"company_id": company_id, "status": {"$in":
            ["CANCELADO", "INATIVO", "Cancelado", "cancelado"]}})
    if n_canc > 0:
        capex = round(n_canc * 120, 2)
        buckets.append({
            "id": "REC_EQUIPAMENTOS",
            "categoria": "RECUPERACAO_EQUIPAMENTO",
            "headline": (f"{n_canc} ONUs em cancelados · "
                          f"R$ {capex:.2f} CAPEX a recuperar"),
            "valor_abandonado_brl": capex,
            "valor_recuperavel_brl_estimado":
                round(capex * 0.6, 2),     # 60% recuperáveis
            "executavel": False,
            "nivel_autonomia":
                AUTONOMY_MATRIX["RECUPERACAO_EQUIPAMENTO"]["nivel"],
            "evidencia": {"cancelados": n_canc,
                            "onu_unitario": 120},
        })

    # REC5 — Tickets reincidentes (risco de churn = receita futura)
    pipe = [{"$match": {"company_id": company_id,
                            "client_id": {"$ne": None}}},
             {"$group": {"_id": "$client_id", "n": {"$sum": 1}}},
             {"$match": {"n": {"$gte": 3}}},
             {"$count": "recurring"}]
    rec_count = 0
    async for r in db.tickets.aggregate(pipe):
        rec_count = r["recurring"]
    if rec_count > 0 and avg > 0:
        risco_ltv = round(rec_count * avg * 12, 2)  # LTV anual em risco
        buckets.append({
            "id": "REC_TICKETS_RECURRING",
            "categoria": "TICKET_RECURRING_TRIAGEM",
            "headline": (f"{rec_count} clientes recurring · "
                          f"R$ {risco_ltv:.2f} LTV anual em risco"),
            "valor_abandonado_brl": risco_ltv,
            "valor_recuperavel_brl_estimado":
                round(risco_ltv * 0.4, 2),  # 40% se atendido bem
            "executavel": False,
            "nivel_autonomia":
                AUTONOMY_MATRIX["TICKET_RECURRING_TRIAGEM"]["nivel"],
            "evidencia": {"recurring": rec_count, "ticket_medio": avg},
        })

    total_abandoned = sum(x["valor_abandonado_brl"] for x in buckets)
    total_recoverable = sum(
        x["valor_recuperavel_brl_estimado"] for x in buckets)
    return {
        "pergunta": "Qual dinheiro está abandonado dentro da empresa?",
        "valor_abandonado_total_brl": round(total_abandoned, 2),
        "valor_recuperavel_estimado_brl": round(total_recoverable, 2),
        "buckets": sorted(buckets,
                            key=lambda x: x["valor_recuperavel_brl_estimado"],
                            reverse=True),
        "generated_at": _iso(_now()),
    }


# ─────────────────────────────────────────────
#  BRIEFING MATINAL (6 perguntas obrigatórias)
# ─────────────────────────────────────────────
async def morning_briefing(company_id: str) -> Dict[str, Any]:
    opp = await opportunities_today(company_id)
    sav = await savings_today(company_id)
    rec = await recovery_today(company_id)

    posso_recuperar = rec["valor_recuperavel_estimado_brl"]
    posso_economizar = sav["potencial_total_brl"]

    # ROI realizado ontem (motor_ia_actions completadas nas últimas 24h)
    cutoff = _iso(_now() - timedelta(hours=24))
    pipe = [{"$match": {"company_id": company_id,
                            "kind": "presidential",
                            "status": "completed",
                            "completed_at": {"$gte": cutoff}}},
             {"$group": {"_id": None,
                            "n": {"$sum": 1},
                            "roi": {"$sum": "$roi_brl"}}}]
    roi_ontem = {"n": 0, "roi_brl": 0.0}
    async for r in db.motor_ia_actions.aggregate(pipe):
        roi_ontem = {"n": r["n"], "roi_brl": round(r["roi"] or 0, 2)}

    # Ações que vou executar HOJE: as auto-aprovaveis + N1
    plano_dia = []
    for op in opp["acoes"] + sav["acoes"]:
        cat = op.get("categoria")
        if (cat and AUTONOMY_MATRIX.get(cat, {}).get("nivel") == "N1"
                and op.get("executavel")):
            roi = float(op.get("impacto_brl_recorrente") or 0) + \
                  float(op.get("impacto_brl_unico") or 0)
            plano_dia.append({
                "categoria": cat,
                "headline": op["headline"],
                "roi_esperado_brl": roi,
                "nivel": "N1",
            })

    roi_esperado_hoje = sum(p["roi_esperado_brl"] for p in plano_dia)

    return {
        "company_id": company_id,
        "generated_at": _iso(_now()),
        "perguntas": {
            "1_quanto_gero_hoje_brl":
                round(opp["potencial_total_brl"], 2),
            "2_quanto_recupero_hoje_brl":
                round(posso_recuperar, 2),
            "3_quanto_economizo_hoje_brl":
                round(posso_economizar, 2),
            "4_acoes_a_executar_hoje": plano_dia,
            "5_roi_esperado_hoje_brl": round(roi_esperado_hoje, 2),
            "6_roi_realizado_ontem":
                {"acoes": roi_ontem["n"],
                  "roi_brl": roi_ontem["roi_brl"]},
        },
        "headline": (f"Hoje: posso GERAR R$ {opp['potencial_total_brl']:.0f} · "
                       f"RECUPERAR R$ {posso_recuperar:.0f} · "
                       f"ECONOMIZAR R$ {posso_economizar:.0f}. "
                       f"Plano N1: {len(plano_dia)} ações."),
        "totais": {
            "oportunidades_brl": opp["potencial_total_brl"],
            "recuperavel_brl": posso_recuperar,
            "economia_brl": posso_economizar,
            "valor_abandonado_brl": rec["valor_abandonado_total_brl"],
        },
    }


# ─────────────────────────────────────────────
#  EXECUTAR O DIA (varre N1, dispara executor_ia)
# ─────────────────────────────────────────────
async def execute_day(company_id: str,
                          dry_run: bool = True) -> Dict[str, Any]:
    """Para cada ação executável N1, propõe + conselho + auto-aprova +
    executa. Idempotente por hora (evita duplicar)."""
    briefing = await morning_briefing(company_id)
    plano = briefing["perguntas"]["4_acoes_a_executar_hoje"]

    executed: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for plan in plano:
        cat = plan["categoria"]
        info = AUTONOMY_MATRIX.get(cat, {})
        if not info.get("categoria_executavel"):
            skipped.append({"categoria": cat,
                              "reason": "sem handler em executor_ia"})
            continue
        if info.get("nivel") not in ("N1", "N2"):
            skipped.append({"categoria": cat,
                              "reason": f"nivel {info.get('nivel')} "
                                          "exige humano"})
            continue
        # Verifica se já houve ação COMPLETADA dessa categoria nas
        # últimas 24h (ações pending/cancelled não contam — permitem
        # retentativa após bump de cap ou correção).
        cutoff = _iso(_now() - timedelta(hours=24))
        recent = await db.motor_ia_actions.count_documents(
            {"company_id": company_id, "categoria": cat,
             "kind": "presidential",
             "source": "presidente_operator",
             "status": {"$in": ["completed", "executing", "approved"]},
             "created_at": {"$gte": cutoff}})
        if recent:
            skipped.append({"categoria": cat,
                              "reason":
                                  "já executada nas últimas 24h"})
            continue
        try:
            act = await ex.propose_action(
                company_id=company_id,
                created_by="presidente_operator",
                categoria=cat,
                descricao=plan["headline"],
                impacto_estimado_brl=plan["roi_esperado_brl"],
                prioridade="ALTA",
                source="presidente_operator",
                payload={"plan_origin": "morning_briefing"})
            action_id = act["id"]
            # Conselho vota
            await ex.collect_council_votes(action_id)
            # Tentativa de auto-approve
            try:
                await ex.auto_approve_action(
                    action_id,
                    justification="Plano do dia N1 do operador")
                auto = True
            except ValueError as e:
                auto = False
                skipped.append({"categoria": cat,
                                  "reason":
                                      f"auto-approve negada: {e}"})
                continue
            # Executa
            res = await ex.execute_action(
                action_id, executor="presidente_operator",
                dry_run=dry_run)
            executed.append({
                "categoria": cat, "action_id": action_id,
                "status": res.get("status"),
                "outcome": res.get("executor_outcome"),
                "roi_brl": res.get("roi_brl"),
                "auto_approved": auto, "dry_run": dry_run,
            })
        except Exception as e:  # noqa: BLE001
            log.exception("execute_day fail cat=%s", cat)
            skipped.append({"categoria": cat, "reason": repr(e)[:300]})

    return {
        "company_id": company_id,
        "executed_at": _iso(_now()),
        "executed": executed,
        "skipped": skipped,
        "roi_total_brl": round(sum(
            (x.get("roi_brl") or 0) for x in executed), 2),
        "briefing_headline": briefing["headline"],
    }
