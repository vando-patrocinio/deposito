"""
governador_ia.py — Presidente IA como GOVERNADOR (V11).

10 capacidades, todas baseadas em LEITURA AGREGADA de dados que já
existem em outras superfícies. Apenas 2 coleções novas:
  - corporate_goals      (única tabela criada)
  - president_daily      (cache do relatório diário)

Nenhum executor novo. Nenhuma IA nova. Nenhuma rota paralela.

Capacidades:
   1. metas corporativas        — CRUD + tracking automático
   2. score das IAs             — drift + corrections agregados
   3. ROI por IA                — motor_ia_actions.roi_brl × source
   4. cobrança de resultado     — diff metas vs realizado por IA
   5. priorização executiva     — reuso de presidente_executive
   6. saúde corporativa         — reuso de president_score
   7. sistema nervoso           — reuso de nervous_coverage
   8. mapa executivo            — áreas × IAs × metas (agregação)
   9. ranking eficiência        — score normalizado 0-100 por IA
  10. relatório presidencial    — consolidação 1-9 persistida diariamente
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

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db

logger = logging.getLogger(__name__)


# ───────── Constantes ─────────
AREAS = {
    "RECEITA": {
        "metricas_alvo": ["mrr_brl", "ticket_medio_brl"],
        "ias_responsaveis": ["isabella", "presidente_ia",
                                "reajuste_engine"],
    },
    "OPERACAO": {
        "metricas_alvo": ["tickets_abertos", "score_operacao"],
        "ias_responsaveis": ["alvaro", "lousa_sentinela",
                                "smart_field"],
    },
    "REDE": {
        "metricas_alvo": ["onus_critical", "onus_offline",
                            "score_rede"],
        "ias_responsaveis": ["rede_ia", "smartolt_twin",
                                "observability_twin"],
    },
    "ATENDIMENTO": {
        "metricas_alvo": ["tickets_abertos", "tempo_medio_resolucao"],
        "ias_responsaveis": ["leo", "secretaria", "lousa"],
    },
    "COMERCIAL": {
        "metricas_alvo": ["leads_30d", "novos_ativos_30d"],
        "ias_responsaveis": ["motor_ia_events", "presidente_ia"],
    },
    "FINANCEIRO": {
        "metricas_alvo": ["dinheiro_em_risco_brl",
                            "reajuste_atrasado_clientes"],
        "ias_responsaveis": ["isabella", "cobranca_engine",
                                "presidente_ia"],
    },
}

# Mapeia `source` de motor_ia_actions ao agente IA
SOURCE_TO_AGENT = {
    "presidente_ia": "presidente_ia",
    "alvaro": "alvaro",
    "alvaro_v5": "alvaro",
    "isabella": "isabella",
    "leo": "leo",
    "leo_proactive": "leo",
    "motor_ia": "motor_ia_events",
    "rede_ia": "rede_ia",
    "smartolt_twin": "smartolt_twin",
    "lousa": "lousa",
    "secretaria": "secretaria",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _agent_of(action: Dict[str, Any]) -> str:
    src = (action.get("source") or "").lower()
    return SOURCE_TO_AGENT.get(src, src or "desconhecido")


# ─────────────────────────────────────────────
#  1. METAS CORPORATIVAS
# ─────────────────────────────────────────────
GOAL_METRICS = {
    # métrica → (path no executive_report, sentido)
    "mrr_brl": ("contexto_financeiro.mrr_atual_brl", "max"),
    "ticket_medio_brl": ("contexto_financeiro.ticket_medio_brl", "max"),
    "clientes_ativos": ("contexto_financeiro.clientes_ativos", "max"),
    "president_score": ("president_score.score", "max"),
    "dinheiro_em_risco_brl": ("dinheiro_em_risco.total_brl", "min"),
    "dinheiro_recuperavel_brl":
        ("dinheiro_recuperavel.total_brl", "max"),
    "churn_previsto_30d_brl":
        ("previsao_30d.churn_previsto_brl", "min"),
    "receita_prevista_30d_brl":
        ("previsao_30d.receita_prevista_brl", "max"),
    "score_rede": ("president_score.components.rede", "max"),
    "score_operacao":
        ("president_score.components.operacao", "max"),
    "score_financeiro":
        ("president_score.components.financeiro", "max"),
}


async def create_goal(*, company_id: str, area: str, metric: str,
                          target_value: float,
                          deadline_iso: str,
                          owner: str,
                          created_by: str,
                          ia_responsavel: Optional[str] = None,
                          description: str = "") -> Dict:
    if area not in AREAS:
        raise ValueError(f"area inválida. Use: {list(AREAS)}")
    if metric not in GOAL_METRICS:
        raise ValueError(
            f"metric inválida. Use: {list(GOAL_METRICS)}")
    goal = {
        "id": _new_id("goal"),
        "company_id": company_id,
        "area": area,
        "metric": metric,
        "metric_direction": GOAL_METRICS[metric][1],
        "target_value": float(target_value),
        "deadline": deadline_iso,
        "owner": owner,
        "ia_responsavel": ia_responsavel,
        "description": description,
        "created_by": created_by,
        "created_at": _iso(_now()),
        "status": "active",   # active|completed|missed|cancelled
        "baseline_value": None,
        "baseline_at": None,
        "current_value": None,
        "current_at": None,
        "progress_pct": 0.0,
        "history": [],
    }
    # Captura baseline imediatamente
    baseline = await _read_metric(company_id, metric)
    goal["baseline_value"] = baseline
    goal["baseline_at"] = _iso(_now())
    await db.corporate_goals.insert_one(goal)
    return goal


async def list_goals(company_id: str,
                          status: Optional[str] = None) -> List[Dict]:
    q = {"company_id": company_id}
    if status:
        q["status"] = status
    cur = db.corporate_goals.find(q, {"_id": 0}).sort(
        [("deadline", 1)])
    return await cur.to_list(200)


async def update_goal_progress(goal_id: str) -> Dict:
    g = await db.corporate_goals.find_one({"id": goal_id}, {"_id": 0})
    if not g:
        raise ValueError(f"goal {goal_id} não encontrado")
    if g["status"] != "active":
        return g
    current = await _read_metric(g["company_id"], g["metric"])
    base = g.get("baseline_value") or 0.0
    tgt = g["target_value"]
    direction = g["metric_direction"]
    if direction == "max":
        delta_tgt = max(tgt - base, 1e-9)
        delta_cur = current - base
        progress = max(0.0, min(100.0, delta_cur / delta_tgt * 100.0))
        achieved = current >= tgt
    else:  # min
        delta_tgt = max(base - tgt, 1e-9)
        delta_cur = base - current
        progress = max(0.0, min(100.0, delta_cur / delta_tgt * 100.0))
        achieved = current <= tgt
    now = _now()
    new_status = g["status"]
    if achieved:
        new_status = "completed"
    elif g["deadline"] and now.isoformat() > g["deadline"]:
        new_status = "missed"
    update = {
        "current_value": float(current),
        "current_at": _iso(now),
        "progress_pct": round(progress, 1),
        "status": new_status,
    }
    await db.corporate_goals.update_one(
        {"id": goal_id},
        {"$set": update,
         "$push": {"history": {"at": _iso(now),
                                  "value": current,
                                  "progress_pct": round(progress, 1)}}})
    return {**g, **update}


async def refresh_all_goals(company_id: str) -> Dict[str, int]:
    """Recalcula progresso de todas as metas ativas."""
    cur = db.corporate_goals.find(
        {"company_id": company_id, "status": "active"},
        {"_id": 0, "id": 1})
    items = await cur.to_list(200)
    completed = missed = updated = 0
    for it in items:
        g = await update_goal_progress(it["id"])
        if g["status"] == "completed":
            completed += 1
        elif g["status"] == "missed":
            missed += 1
        else:
            updated += 1
    return {"total": len(items), "active": updated,
            "completed": completed, "missed": missed}


async def _read_metric(company_id: str, metric: str) -> float:
    """Lê uma métrica do relatório executivo atual."""
    from services.presidente_executive import build_executive_report
    rep = await build_executive_report(company_id)
    path, _ = GOAL_METRICS[metric]
    cur: Any = rep
    for k in path.split("."):
        cur = (cur or {}).get(k) if isinstance(cur, dict) else None
    try:
        return float(cur or 0)
    except (TypeError, ValueError):
        return 0.0


# ─────────────────────────────────────────────
#  2. SCORE DAS IAs (drift + corrections + actions)
# ─────────────────────────────────────────────
async def scorecard_ias(company_id: str,
                            period_days: int = 30) -> List[Dict]:
    cutoff = _iso(_now() - timedelta(days=period_days))
    # Agrega actions por source
    pipe = [
        {"$match": {"company_id": company_id,
                       "created_at": {"$gte": cutoff}}},
        {"$group": {
            "_id": "$source",
            "acoes_total": {"$sum": 1},
            "completadas": {"$sum": {"$cond": [
                {"$eq": ["$status", "completed"]}, 1, 0]}},
            "falhadas": {"$sum": {"$cond": [
                {"$eq": ["$status", "failed"]}, 1, 0]}},
            "roi_total": {"$sum": {"$ifNull": ["$roi_brl", 0]}},
        }}
    ]
    rows = await db.motor_ia_actions.aggregate(pipe).to_list(50)
    # Agrega drift por categoria — fallback de "acerto" se houver
    drifts = await db.motor_ia_drift.find(
        {"company_id": company_id}, {"_id": 0}).to_list(50)
    drift_by_cat: Dict[str, Dict] = {
        d["categoria"]: d for d in drifts}

    scorecards = []
    for r in rows:
        agent = SOURCE_TO_AGENT.get((r["_id"] or "").lower(),
                                         r["_id"] or "desconhecido")
        total = r["acoes_total"]
        completed = r["completadas"]
        failed = r["falhadas"]
        roi = round(r["roi_total"], 2)
        taxa_exec = (completed / total * 100.0) if total else 0.0
        taxa_falha = (failed / total * 100.0) if total else 0.0
        # score 0-100
        score = max(0.0, min(100.0,
                                  taxa_exec * 0.5
                                  + min(roi / 100, 50)
                                  - taxa_falha * 0.3))
        scorecards.append({
            "agente": agent,
            "acoes_total": total,
            "completadas": completed,
            "falhadas": failed,
            "taxa_execucao_pct": round(taxa_exec, 1),
            "taxa_falha_pct": round(taxa_falha, 1),
            "roi_total_brl": roi,
            "score": round(score, 1),
        })
    # Junta categorias de drift que não tenham source mapeado
    for cat, d in drift_by_cat.items():
        if not any(s["agente"] == cat for s in scorecards):
            scorecards.append({
                "agente": cat,
                "acoes_total": d["amostras"],
                "completadas": d["amostras"],
                "falhadas": 0,
                "taxa_execucao_pct": 100.0,
                "taxa_falha_pct": 0.0,
                "roi_total_brl": d["media_real_brl"]
                                    * d["amostras"],
                "score": round(d["taxa_acerto"] * 100, 1),
            })
    scorecards.sort(key=lambda s: s["score"], reverse=True)
    return scorecards


# ─────────────────────────────────────────────
#  3. ROI POR IA
# ─────────────────────────────────────────────
async def roi_por_ia(company_id: str,
                          period_days: int = 30) -> Dict[str, Any]:
    cards = await scorecard_ias(company_id, period_days)
    total = sum(c["roi_total_brl"] for c in cards)
    return {
        "periodo_dias": period_days,
        "total_brl": round(total, 2),
        "por_agente": [
            {"agente": c["agente"],
             "roi_brl": c["roi_total_brl"],
             "share_pct": (round(c["roi_total_brl"] / total * 100, 1)
                            if total else 0.0)}
            for c in sorted(cards,
                              key=lambda x: x["roi_total_brl"],
                              reverse=True)
        ],
    }


# ─────────────────────────────────────────────
#  4. COBRANÇA DE RESULTADO (metas × IAs)
# ─────────────────────────────────────────────
async def cobranca_resultado(company_id: str) -> List[Dict]:
    """Para cada meta ativa, cobra o resultado da IA responsável."""
    goals = await list_goals(company_id, status="active")
    out = []
    for g in goals:
        g = await update_goal_progress(g["id"])
        ia = g.get("ia_responsavel")
        # Encontra ROI gerado pela IA específica
        roi_agente_brl = 0.0
        if ia:
            pipe = [
                {"$match": {"company_id": company_id,
                               "source": {"$regex": f"^{ia}",
                                            "$options": "i"}}},
                {"$group": {"_id": None,
                               "roi": {"$sum":
                                          {"$ifNull": ["$roi_brl", 0]}}}}
            ]
            rows = await db.motor_ia_actions.aggregate(
                pipe).to_list(1)
            if rows:
                roi_agente_brl = round(rows[0]["roi"], 2)
        diagnostic = "no_prazo"
        if g["status"] == "completed":
            diagnostic = "entregue"
        elif g["status"] == "missed":
            diagnostic = "atrasada"
        elif g["progress_pct"] < 50.0:
            diagnostic = "em_risco"
        out.append({
            "goal_id": g["id"],
            "area": g["area"],
            "metric": g["metric"],
            "target": g["target_value"],
            "current": g["current_value"],
            "progress_pct": g["progress_pct"],
            "deadline": g["deadline"],
            "owner": g["owner"],
            "ia_responsavel": ia,
            "roi_ia_agente_brl": roi_agente_brl,
            "status": g["status"],
            "diagnostico": diagnostic,
        })
    return out


# ─────────────────────────────────────────────
#  5. PRIORIZAÇÃO EXECUTIVA (reuso V10)
# ─────────────────────────────────────────────
async def prioridades_executivas(company_id: str) -> List[Dict]:
    from services.presidente_executive import build_executive_report
    rep = await build_executive_report(company_id)
    return rep.get("acoes_presidenciais", [])[:5]


# ─────────────────────────────────────────────
#  6. SAÚDE CORPORATIVA (reuso V10)
# ─────────────────────────────────────────────
async def saude_corporativa(company_id: str) -> Dict[str, Any]:
    from services.presidente_executive import build_executive_report
    rep = await build_executive_report(company_id)
    return {
        "score": rep["president_score"]["score"],
        "status": rep["president_score"]["status"],
        "components": rep["president_score"]["components"],
        "piores_drivers": rep["president_score"]["piores_drivers"],
        "melhores_drivers": rep["president_score"]["melhores_drivers"],
        "contexto_financeiro": rep["contexto_financeiro"],
    }


# ─────────────────────────────────────────────
#  7. SISTEMA NERVOSO (reuso nervous_coverage)
# ─────────────────────────────────────────────
async def sistema_nervoso(company_id: str,
                              hours: int = 24) -> Dict[str, Any]:
    from services.nervous_coverage import (
        coverage_report, events_by_domain, what_happened_today)
    window_days = max(1, hours // 24)
    cov = await coverage_report(
        company_id=company_id, window_days=window_days)
    dom = await events_by_domain(
        company_id=company_id, hours=hours)
    today = await what_happened_today(company_id)
    return {
        "coverage": cov, "events_by_domain": dom,
        "what_happened_today": today,
    }


# ─────────────────────────────────────────────
#  8. MAPA EXECUTIVO (áreas × IAs × metas)
# ─────────────────────────────────────────────
async def mapa_executivo(company_id: str) -> Dict[str, Any]:
    goals = await list_goals(company_id)
    cards = await scorecard_ias(company_id, period_days=30)
    by_agent = {c["agente"]: c for c in cards}

    out = {"areas": [], "generated_at": _iso(_now())}
    for area_key, area_def in AREAS.items():
        metas_area = [
            g for g in goals if g["area"] == area_key]
        ias_area = []
        for ia in area_def["ias_responsaveis"]:
            sc = by_agent.get(ia, {
                "agente": ia, "acoes_total": 0,
                "score": 0.0, "roi_total_brl": 0.0})
            ias_area.append({
                "agente": ia,
                "score": sc["score"],
                "acoes_total": sc["acoes_total"],
                "roi_brl": sc["roi_total_brl"],
            })
        completed = sum(1 for g in metas_area
                          if g["status"] == "completed")
        missed = sum(1 for g in metas_area
                       if g["status"] == "missed")
        active = sum(1 for g in metas_area
                       if g["status"] == "active")
        prog_medio = (sum(g["progress_pct"] for g in metas_area)
                       / len(metas_area)) if metas_area else 0.0
        out["areas"].append({
            "area": area_key,
            "ias": ias_area,
            "metas_total": len(metas_area),
            "metas_ativas": active,
            "metas_entregues": completed,
            "metas_atrasadas": missed,
            "progresso_medio_pct": round(prog_medio, 1),
        })
    return out


# ─────────────────────────────────────────────
#  9. RANKING DE EFICIÊNCIA OPERACIONAL
# ─────────────────────────────────────────────
async def ranking_eficiencia(company_id: str,
                                  period_days: int = 30) -> List[Dict]:
    cards = await scorecard_ias(company_id, period_days)
    drifts = await db.motor_ia_drift.find(
        {"company_id": company_id}, {"_id": 0}).to_list(50)
    drift_by_cat = {d["categoria"]: d for d in drifts}

    ranking = []
    for pos, c in enumerate(cards, start=1):
        cat_drift = drift_by_cat.get(c["agente"], {})
        ranking.append({
            "posicao": pos,
            "agente": c["agente"],
            "score": c["score"],
            "acoes_total": c["acoes_total"],
            "taxa_execucao_pct": c["taxa_execucao_pct"],
            "taxa_falha_pct": c["taxa_falha_pct"],
            "roi_total_brl": c["roi_total_brl"],
            "taxa_acerto_pct":
                round(cat_drift.get("taxa_acerto", 0) * 100, 1)
                if cat_drift else None,
            "drift_pct": cat_drift.get("drift_pct"),
        })
    return ranking


# ─────────────────────────────────────────────
#  10. RELATÓRIO PRESIDENCIAL DIÁRIO (persistido)
# ─────────────────────────────────────────────
async def relatorio_presidencial_diario(
        company_id: str, force: bool = False) -> Dict[str, Any]:
    """Compila o consolidado do dia. Cache 1h em president_daily."""
    today_key = _now().strftime("%Y-%m-%d")
    cached = await db.president_daily.find_one(
        {"company_id": company_id, "date_key": today_key},
        {"_id": 0})
    if cached and not force:
        return cached

    saude = await saude_corporativa(company_id)
    metas = await list_goals(company_id, status="active")
    cobranca = await cobranca_resultado(company_id)
    prioridades = await prioridades_executivas(company_id)
    rank = await ranking_eficiencia(company_id, 30)
    roi = await roi_por_ia(company_id, 30)
    mapa = await mapa_executivo(company_id)
    # Reuso do P1 (executor_ia)
    from services.executor_ia import state_of_presidency
    state = await state_of_presidency(company_id, period_days=1)
    # Reuso do Sistema Nervoso
    nervoso = await sistema_nervoso(company_id, hours=24)

    metas_entregues = sum(1 for c in cobranca
                            if c["status"] == "completed")
    metas_atrasadas = sum(1 for c in cobranca
                            if c["status"] == "missed")
    metas_em_risco = sum(1 for c in cobranca
                            if c["diagnostico"] == "em_risco")
    top_ias = [r for r in rank[:3]]
    flop_ias = [r for r in rank[-3:] if r["acoes_total"] > 0]

    doc = {
        "id": _new_id("daily"),
        "company_id": company_id,
        "date_key": today_key,
        "generated_at": _iso(_now()),
        "saude": saude,
        "metas": {
            "total_ativas": len(metas),
            "entregues_hoje": metas_entregues,
            "atrasadas": metas_atrasadas,
            "em_risco": metas_em_risco,
            "cobranca": cobranca[:10],
        },
        "prioridades_hoje": prioridades,
        "estado_presidencia_24h": state,
        "ranking_top": top_ias,
        "ranking_flop": flop_ias,
        "roi_30d": roi,
        "mapa_executivo": mapa,
        "sistema_nervoso_24h": {
            "coverage_pct":
                nervoso["coverage"].get("overall_coverage_pct"),
            "coverage_level":
                nervoso["coverage"].get("level"),
            "domains": (list(nervoso["events_by_domain"].keys())[:8]
                          if isinstance(nervoso["events_by_domain"],
                                          dict)
                          else nervoso["events_by_domain"][:8]),
            "what_happened":
                nervoso["what_happened_today"].get("summary")
                if isinstance(nervoso["what_happened_today"], dict)
                else None,
        },
        "narrativa": _narrativa(saude, metas_em_risco,
                                     metas_atrasadas,
                                     metas_entregues, roi),
    }
    await db.president_daily.replace_one(
        {"company_id": company_id, "date_key": today_key},
        doc, upsert=True)
    return doc


def _narrativa(saude: Dict, em_risco: int, atrasadas: int,
                  entregues: int, roi: Dict) -> str:
    score = saude["score"]
    status = saude["status"]
    n_ias = len(roi["por_agente"])
    total_brl = roi["total_brl"]
    bullets = []
    if status == "saudavel":
        bullets.append(
            f"Saúde corporativa SAUDÁVEL ({score}/100).")
    elif status == "atencao":
        bullets.append(
            f"Saúde em ATENÇÃO ({score}/100).")
    else:
        bullets.append(
            f"Saúde em {status.upper()} ({score}/100). "
            "Ação imediata recomendada.")
    if entregues:
        bullets.append(f"{entregues} metas entregues hoje.")
    if atrasadas:
        bullets.append(
            f"{atrasadas} metas ATRASADAS exigem replanejamento.")
    if em_risco:
        bullets.append(
            f"{em_risco} metas em risco de não cumprir prazo.")
    if total_brl > 0:
        bullets.append(
            f"R$ {total_brl:,.0f} de ROI gerado por "
            f"{n_ias} IAs nos últimos 30 dias.".replace(",", "."))
    else:
        bullets.append(
            "ROI 30d = R$ 0,00 (ações em dry-run aguardando flip).")
    return " ".join(bullets)
