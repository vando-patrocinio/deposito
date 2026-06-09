"""
presidente_cash.py — OPERAÇÃO CAIXA REAL.

Único KPI a partir daqui: DINHEIRO. Não estimativa. Confirmado.

Componentes:

  - executive_ledger     : 1 registro por execução de ação presidencial
  - record_to_ledger()   : escreve a entrada no ledger
  - confirm_entry()      : atualiza valor_confirmado quando há evidência real
  - cash_summary()       : agrega caixa hoje / 7d / 30d (CONFIRMADO)
  - daily_closing()      : fecha o dia (idempotente, persiste em
                              executive_daily_closings)
  - ia_ranking()         : ranking financeiro das IAs (created_by)
  - module_ranking()     : ranking financeiro dos módulos (mapeado por
                              categoria)
  - weekly_ceo_report()  : valor da empresa hoje vs. 7d atrás +
                              ação top criadora/destrutiva
  - seed_progressive_goal(): meta progressiva R$100 → R$1k → R$10k → R$100k
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from database import db

log = logging.getLogger("presidente_cash")


def _now() -> datetime: return datetime.now(timezone.utc)
def _iso(d): return d.isoformat()


# ─────────────────────────────────────────────
# MAPA categoria → módulo financeiro
# ─────────────────────────────────────────────
CATEGORY_TO_MODULE = {
    "REAJUSTE_IPCA":           "Receita",
    "UPGRADE_PLANO_OFERTA":    "Receita",
    "DISPARO_COBRANCA":        "Cobrança",
    "REATIVACAO_CANCELADO":    "Retenção",
    "CAMPANHA_RETENCAO":       "Retenção",
    "CONTATO_LEO_PROATIVO":    "Retenção",
    "CRIACAO_OS_SMARTFIELD":   "Smart Field",
    "PREVENTIVE_MAINT_OLT":    "Smart Field",
    "RECUPERACAO_EQUIPAMENTO": "CAPEX",
    "INDICACAO_PROACTIVE":     "Indicação",
    "CROSS_SELL_SECURITY":     "Security Home",
    "CROSS_SELL_FLEET":        "Fleet",
    "CROSS_SELL_LIGO_MOVEL":   "Ligo Móvel",
    "CROSS_SELL_PLAYHUB":      "PlayHub",
    "TICKET_RECURRING_TRIAGEM": "Atendimento",
}


# ─────────────────────────────────────────────
# LEDGER — gravação
# ─────────────────────────────────────────────
async def ensure_indexes() -> None:
    await db.executive_ledger.create_index(
        [("company_id", 1), ("executed_at", -1)],
        name="cid_ts")
    await db.executive_ledger.create_index(
        "action_id", unique=True, name="action_id_uniq")
    await db.executive_daily_closings.create_index(
        [("company_id", 1), ("date", -1)],
        name="cid_date")


async def record_to_ledger(action: Dict[str, Any]) -> Dict[str, Any]:
    """Insere entry no ledger toda vez que uma ação é completed.
    Idempotente: action_id é UNIQUE."""
    cat = action.get("categoria")
    entry = {
        "company_id": action.get("company_id"),
        "action_id": action.get("id"),
        "executed_at": action.get("completed_at") or _iso(_now()),
        "categoria": cat,
        "modulo": CATEGORY_TO_MODULE.get(cat, "Outros"),
        "responsavel": (action.get("approved_by")
                          or action.get("created_by") or "?"),
        "auto_approved": bool(action.get("auto_approved", False)),
        "valor_previsto_brl":
            float(action.get("impacto_estimado_brl") or 0),
        "valor_executado_brl": float(action.get("roi_brl") or 0),
        "valor_confirmado_brl": 0.0,   # só sobe quando há evidência real
        "roi_pct_previsto":
            float(action.get("roi_pct") or 0),
        "roi_pct_confirmado": 0.0,
        "outcome": action.get("executor_outcome") or {},
        "descricao": action.get("descricao") or "",
        "status": "PENDING_CONFIRMATION",
        "created_at": _iso(_now()),
    }
    try:
        await db.executive_ledger.update_one(
            {"action_id": entry["action_id"]},
            {"$setOnInsert": entry}, upsert=True)
    except Exception as e:   # noqa: BLE001
        log.warning("[ledger] insert err: %r", e)
    return entry


async def confirm_entry(action_id: str, valor_confirmado_brl: float,
                              evidence: Dict[str, Any] = None
                              ) -> Dict[str, Any]:
    """Atualiza o valor_confirmado quando há evidência real."""
    upd = {
        "valor_confirmado_brl": float(valor_confirmado_brl),
        "status": "CONFIRMED" if valor_confirmado_brl > 0 else "ZERO",
        "confirmed_at": _iso(_now()),
    }
    if evidence:
        upd["evidence"] = evidence
    await db.executive_ledger.update_one(
        {"action_id": action_id}, {"$set": upd})
    return upd


# ─────────────────────────────────────────────
# CASH endpoint — confirmado, sem estimativa
# ─────────────────────────────────────────────
async def cash_summary(company_id: str) -> Dict[str, Any]:
    """Agrega valor CONFIRMADO em janelas hoje/7d/30d."""
    now = _now()
    today_start = _iso(now.replace(hour=0, minute=0, second=0,
                                       microsecond=0))
    d7 = _iso(now - timedelta(days=7))
    d30 = _iso(now - timedelta(days=30))

    async def _sum(filter_q):
        pipe = [{"$match": filter_q},
                 {"$group": {"_id": None,
                                "n": {"$sum": 1},
                                "confirmado": {
                                    "$sum": "$valor_confirmado_brl"},
                                "executado": {
                                    "$sum": "$valor_executado_brl"},
                                "previsto": {
                                    "$sum": "$valor_previsto_brl"}}}]
        async for r in db.executive_ledger.aggregate(pipe):
            return {"n": r["n"],
                      "confirmado_brl": round(r["confirmado"], 2),
                      "executado_brl": round(r["executado"], 2),
                      "previsto_brl": round(r["previsto"], 2)}
        return {"n": 0, "confirmado_brl": 0.0,
                  "executado_brl": 0.0, "previsto_brl": 0.0}

    base = {"company_id": company_id}
    hoje = await _sum({**base, "executed_at": {"$gte": today_start}})
    s7d = await _sum({**base, "executed_at": {"$gte": d7}})
    s30d = await _sum({**base, "executed_at": {"$gte": d30}})

    # Decomposição por tipo de impacto (Receita vs Cobrança vs Smart Field)
    pipe = [{"$match": {**base, "executed_at": {"$gte": d30}}},
             {"$group": {"_id": "$modulo",
                            "confirmado": {
                                "$sum": "$valor_confirmado_brl"},
                            "n": {"$sum": 1}}}]
    por_modulo = []
    async for r in db.executive_ledger.aggregate(pipe):
        por_modulo.append({"modulo": r["_id"],
                              "confirmado_brl": round(r["confirmado"], 2),
                              "acoes": r["n"]})

    return {
        "company_id": company_id,
        "regra": "Apenas valores CONFIRMADOS. Sem estimativa.",
        "caixa_gerado_hoje_brl": hoje["confirmado_brl"],
        "caixa_gerado_7d_brl": s7d["confirmado_brl"],
        "caixa_gerado_30d_brl": s30d["confirmado_brl"],
        "caixa_recuperado_30d_brl":
            round(sum(m["confirmado_brl"] for m in por_modulo
                      if m["modulo"] in
                          ("Cobrança", "Retenção")), 2),
        "economia_gerada_30d_brl":
            round(sum(m["confirmado_brl"] for m in por_modulo
                      if m["modulo"] in
                          ("Smart Field", "CAPEX")), 2),
        "roi_real_30d_brl": s30d["confirmado_brl"],
        "acoes_hoje": hoje["n"],
        "acoes_30d": s30d["n"],
        "modulos_30d": sorted(por_modulo,
                                key=lambda x: x["confirmado_brl"],
                                reverse=True),
        "generated_at": _iso(now),
    }


# ─────────────────────────────────────────────
# FECHAMENTO DIÁRIO
# ─────────────────────────────────────────────
async def daily_closing(company_id: str,
                              date_iso: Optional[str] = None
                              ) -> Dict[str, Any]:
    """Fechamento idempotente do dia. Persiste em
    executive_daily_closings."""
    now = _now()
    if date_iso:
        date_str = date_iso[:10]
    else:
        date_str = now.strftime("%Y-%m-%d")
    day_start = f"{date_str}T00:00:00+00:00"
    day_end = f"{date_str}T23:59:59+00:00"

    base = {"company_id": company_id,
              "executed_at": {"$gte": day_start, "$lte": day_end}}

    pipe = [{"$match": base},
             {"$group": {"_id": None,
                            "n": {"$sum": 1},
                            "confirmado": {
                                "$sum": "$valor_confirmado_brl"},
                            "executado": {
                                "$sum": "$valor_executado_brl"},
                            "previsto": {
                                "$sum": "$valor_previsto_brl"}}}]
    tot = {"n": 0, "confirmado": 0.0, "executado": 0.0, "previsto": 0.0}
    async for r in db.executive_ledger.aggregate(pipe):
        tot = {"n": r["n"], "confirmado": round(r["confirmado"], 2),
                 "executado": round(r["executado"], 2),
                 "previsto": round(r["previsto"], 2)}

    # Top criadora / destrutiva do dia
    top_create = None
    async for r in db.executive_ledger.find(
        base, {"_id": 0}).sort("valor_confirmado_brl", -1).limit(1):
        top_create = r
    top_destroy = None
    async for r in db.executive_ledger.find(
        base, {"_id": 0}).sort("valor_confirmado_brl", 1).limit(1):
        if r.get("valor_confirmado_brl", 0) < 0 or (
                r.get("valor_previsto_brl", 0) > 0
                and r.get("valor_confirmado_brl", 0) == 0):
            top_destroy = r

    # Cobrança / recuperação por módulo no dia
    pipe = [{"$match": base},
             {"$group": {"_id": "$modulo",
                            "confirmado": {
                                "$sum": "$valor_confirmado_brl"}}}]
    por_modulo = {}
    async for r in db.executive_ledger.aggregate(pipe):
        por_modulo[r["_id"]] = round(r["confirmado"], 2)

    closing = {
        "company_id": company_id,
        "date": date_str,
        "fechado_em": _iso(now),
        "perguntas": {
            "1_quanto_entrou_brl":
                round(por_modulo.get("Receita", 0)
                       + por_modulo.get("Indicação", 0)
                       + por_modulo.get("PlayHub", 0)
                       + por_modulo.get("Ligo Móvel", 0)
                       + por_modulo.get("Security Home", 0)
                       + por_modulo.get("Fleet", 0), 2),
            "2_quanto_recuperado_brl":
                round(por_modulo.get("Cobrança", 0)
                       + por_modulo.get("Retenção", 0), 2),
            "3_quanto_perdido_brl":
                round(max(0, tot["previsto"] - tot["confirmado"]), 2),
            "4_acao_top_criadora": (
                {"action_id": top_create["action_id"],
                  "categoria": top_create["categoria"],
                  "modulo": top_create["modulo"],
                  "valor_confirmado_brl":
                      top_create["valor_confirmado_brl"]}
                if top_create else None),
            "5_acao_destruiu_valor": (
                {"action_id": top_destroy["action_id"],
                  "categoria": top_destroy["categoria"],
                  "modulo": top_destroy["modulo"],
                  "previsto_brl": top_destroy["valor_previsto_brl"],
                  "confirmado_brl": top_destroy["valor_confirmado_brl"],
                  "diff_brl": (top_destroy["valor_confirmado_brl"]
                                 - top_destroy["valor_previsto_brl"])}
                if top_destroy else None),
            "6_roi_real_dia_brl": tot["confirmado"],
        },
        "totais": tot,
        "por_modulo": por_modulo,
    }

    # persiste
    await db.executive_daily_closings.update_one(
        {"company_id": company_id, "date": date_str},
        {"$set": closing}, upsert=True)
    return closing


# ─────────────────────────────────────────────
# RANKINGS FINANCEIROS
# ─────────────────────────────────────────────
async def ia_ranking(company_id: str,
                          days: int = 30) -> List[Dict[str, Any]]:
    """Ranking das IAs (responsavel) por valor CONFIRMADO."""
    cutoff = _iso(_now() - timedelta(days=days))
    pipe = [{"$match": {"company_id": company_id,
                            "executed_at": {"$gte": cutoff}}},
             {"$group": {"_id": "$responsavel",
                            "acoes": {"$sum": 1},
                            "receita_gerada":
                                {"$sum": {"$cond": [
                                    {"$in": ["$modulo",
                                             ["Receita", "Indicação",
                                              "PlayHub", "Ligo Móvel",
                                              "Security Home", "Fleet"]]},
                                    "$valor_confirmado_brl", 0]}},
                            "receita_recuperada":
                                {"$sum": {"$cond": [
                                    {"$in": ["$modulo",
                                             ["Cobrança", "Retenção"]]},
                                    "$valor_confirmado_brl", 0]}},
                            "custo_evitado":
                                {"$sum": {"$cond": [
                                    {"$in": ["$modulo",
                                             ["Smart Field", "CAPEX"]]},
                                    "$valor_confirmado_brl", 0]}},
                            "previsto":
                                {"$sum": "$valor_previsto_brl"},
                            "confirmado":
                                {"$sum": "$valor_confirmado_brl"}}}]
    rows = []
    async for r in db.executive_ledger.aggregate(pipe):
        rows.append({
            "ia": r["_id"],
            "acoes": r["acoes"],
            "receita_gerada_brl": round(r["receita_gerada"], 2),
            "receita_recuperada_brl": round(r["receita_recuperada"], 2),
            "custo_evitado_brl": round(r["custo_evitado"], 2),
            "roi_real_brl": round(r["confirmado"], 2),
            "previsto_brl": round(r["previsto"], 2),
            "taxa_acerto_pct": (round(r["confirmado"] / r["previsto"]
                                       * 100, 1)
                                 if r["previsto"] > 0 else 0.0),
        })
    rows.sort(key=lambda x: x["roi_real_brl"], reverse=True)
    return rows


async def module_ranking(company_id: str,
                              days: int = 30) -> List[Dict[str, Any]]:
    """Ranking dos módulos (por modulo) por valor CONFIRMADO."""
    cutoff = _iso(_now() - timedelta(days=days))
    pipe = [{"$match": {"company_id": company_id,
                            "executed_at": {"$gte": cutoff}}},
             {"$group": {"_id": "$modulo",
                            "acoes": {"$sum": 1},
                            "confirmado":
                                {"$sum": "$valor_confirmado_brl"},
                            "previsto":
                                {"$sum": "$valor_previsto_brl"}}}]
    rows = []
    async for r in db.executive_ledger.aggregate(pipe):
        c = round(r["confirmado"], 2)
        p = round(r["previsto"], 2)
        rows.append({
            "modulo": r["_id"],
            "acoes": r["acoes"],
            "confirmado_brl": c,
            "previsto_brl": p,
            "veredito": ("GERA DINHEIRO" if c > 0
                          else ("NEUTRO" if p == 0
                                else "DESTRÓI VALOR")),
        })
    rows.sort(key=lambda x: x["confirmado_brl"], reverse=True)
    return rows


# ─────────────────────────────────────────────
# CEO WEEKLY REPORT
# ─────────────────────────────────────────────
async def weekly_ceo_report(company_id: str) -> Dict[str, Any]:
    """Snapshot company_value de 7d atrás vs hoje + top criadora/
    destrutiva da semana."""
    from services.presidente_operator import company_value

    cv_now = await company_value(company_id)

    # 7d atrás: usa motor_ia_kpis snapshot mais antigo da última semana,
    # ou recalcula com os dados atuais menos os deltas de execução
    # (heurística: EV de 7d atrás = EV atual - confirmed_7d × multiplier
    # de receita).
    cutoff7 = _iso(_now() - timedelta(days=7))
    pipe = [{"$match": {"company_id": company_id,
                            "executed_at": {"$gte": cutoff7}}},
             {"$group": {"_id": None,
                            "confirmado":
                                {"$sum": "$valor_confirmado_brl"}}}]
    confirmed_7d = 0.0
    async for r in db.executive_ledger.aggregate(pipe):
        confirmed_7d = round(r["confirmado"], 2)

    # EV impact = receita confirmada × valuation_multiplier × 12
    valor_criado = round(confirmed_7d
                          * cv_now["valuation_multiplier"] * 12, 2)

    # destruído = previsto - confirmado (gap de eficiência)
    pipe = [{"$match": {"company_id": company_id,
                            "executed_at": {"$gte": cutoff7}}},
             {"$group": {"_id": None,
                            "previsto":
                                {"$sum": "$valor_previsto_brl"},
                            "confirmado":
                                {"$sum": "$valor_confirmado_brl"}}}]
    gap = 0.0
    async for r in db.executive_ledger.aggregate(pipe):
        gap = round(r["previsto"] - r["confirmado"], 2)
    valor_destruido = round(gap * cv_now["valuation_multiplier"] * 12, 2)

    ev_hoje = cv_now["enterprise_value_brl"]
    ev_semana_passada = round(ev_hoje - valor_criado + valor_destruido, 2)

    # Top criadora/destrutiva da semana
    top_create = None
    async for r in db.executive_ledger.find(
        {"company_id": company_id,
         "executed_at": {"$gte": cutoff7}},
        {"_id": 0}).sort("valor_confirmado_brl", -1).limit(1):
        top_create = r
    top_destroy = None
    async for r in db.executive_ledger.find(
        {"company_id": company_id,
         "executed_at": {"$gte": cutoff7}},
        {"_id": 0}).sort([("valor_previsto_brl", -1)]).limit(1):
        # destrói = previsto alto mas confirmado baixo
        if (r.get("valor_previsto_brl", 0) > 0
                and r.get("valor_confirmado_brl", 0)
                    < r.get("valor_previsto_brl", 0)):
            top_destroy = r

    return {
        "company_id": company_id,
        "generated_at": _iso(_now()),
        "ev_semana_passada_brl": ev_semana_passada,
        "ev_hoje_brl": ev_hoje,
        "valor_criado_semana_brl": valor_criado,
        "valor_destruido_semana_brl": valor_destruido,
        "delta_ev_brl": round(ev_hoje - ev_semana_passada, 2),
        "acao_top_criadora": top_create,
        "acao_destruiu_valor": top_destroy,
        "caixa_confirmado_semana_brl": confirmed_7d,
        "valuation_atual": {
            "mrr_brl": cv_now["mrr_brl"],
            "arr_brl": cv_now["arr_brl"],
            "churn_mensal_pct": cv_now["churn_mensal_pct"],
            "ltv_brl": cv_now["ltv_brl"],
            "tier": cv_now["valuation_tier"],
            "mult": cv_now["valuation_multiplier"],
        },
    }


# ─────────────────────────────────────────────
# META PROGRESSIVA R$100 → R$1k → R$10k → R$100k
# ─────────────────────────────────────────────
PROGRESSIVE_LADDER = [100.0, 1_000.0, 10_000.0, 100_000.0]


async def current_progressive_goal(company_id: str
                                          ) -> Dict[str, Any]:
    """Calcula em qual degrau da escada estamos."""
    # Caixa confirmado total
    pipe = [{"$match": {"company_id": company_id}},
             {"$group": {"_id": None,
                            "tot": {"$sum": "$valor_confirmado_brl"}}}]
    tot = 0.0
    async for r in db.executive_ledger.aggregate(pipe):
        tot = round(r["tot"], 2)

    proximo = next((lvl for lvl in PROGRESSIVE_LADDER if tot < lvl),
                     PROGRESSIVE_LADDER[-1])
    completados = [lvl for lvl in PROGRESSIVE_LADDER if tot >= lvl]
    return {
        "company_id": company_id,
        "caixa_confirmado_total_brl": tot,
        "proxima_meta_brl": proximo,
        "faltam_brl": round(max(0, proximo - tot), 2),
        "degraus_completados_brl": completados,
        "progresso_pct":
            round(min(100, tot / proximo * 100), 2) if proximo else 0,
        "escada_completa_brl": PROGRESSIVE_LADDER,
    }


async def seed_progressive_goals(company_id: str) -> Dict[str, Any]:
    """Cria a meta progressiva em corporate_goals."""
    state = await current_progressive_goal(company_id)
    doc = {
        "company_id": company_id,
        "goal_id": "cash_progressive_ladder",
        "name": "Meta progressiva de caixa real",
        "metric": "valor_confirmado_brl_total",
        "direction": "up",
        "ladder_brl": PROGRESSIVE_LADDER,
        "atual_brl": state["caixa_confirmado_total_brl"],
        "proxima_meta_brl": state["proxima_meta_brl"],
        "permanent": True,
        "updated_at": _iso(_now()),
    }
    await db.corporate_goals.update_one(
        {"company_id": company_id, "goal_id": "cash_progressive_ladder"},
        {"$set": doc,
         "$setOnInsert": {"created_at": _iso(_now())}},
        upsert=True)
    return {"goal": doc, "state": state}


# ─────────────────────────────────────────────
# JOB 23:59 — fechamento diário automático
# ─────────────────────────────────────────────
async def daily_closing_job() -> Dict[str, Any]:
    """Fecha o dia para todos os tenants reais."""
    tenants = await db.companies.distinct("id")
    out: Dict[str, Any] = {}
    for cid in tenants:
        if not cid:
            continue
        try:
            c = await daily_closing(cid)
            out[cid] = {
                "n": c["totais"]["n"],
                "confirmado_brl": c["totais"]["confirmado"],
                "roi_real_dia_brl":
                    c["perguntas"]["6_roi_real_dia_brl"],
            }
        except Exception as e:  # noqa: BLE001
            out[cid] = {"error": repr(e)[:200]}
    log.info("[daily_closing_job] %d tenants fechados", len(out))
    return {"closed": len(out), "by_tenant": out}


def register_scheduler(scheduler) -> None:
    """Registra o job diário 23:59."""
    job_id = "executive_daily_closing"
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    scheduler.add_job(
        daily_closing_job, "cron",
        hour=23, minute=59,
        id=job_id, max_instances=1,
        coalesce=True, replace_existing=True)
    log.info("[presidente_cash] daily_closing_job registered (23:59)")


# ─────────────────────────────────────────────
# FASE 6 — CROSS-TENANT BENCHMARK
# ─────────────────────────────────────────────
async def cross_tenant_ranking() -> Dict[str, Any]:
    """Ranking de empresas por dinheiro confirmado.
    Mostra Empresa A +R$X, Empresa B +R$Y, total +R$N."""
    tenants = await db.companies.find(
        {}, {"_id": 0, "id": 1, "name": 1}).to_list(200)
    pipe = [{"$group": {"_id": "$company_id",
                             "n": {"$sum": 1},
                             "confirmado":
                                 {"$sum": "$valor_confirmado_brl"},
                             "previsto":
                                 {"$sum": "$valor_previsto_brl"}}}]
    by_cid: Dict[str, Any] = {}
    async for r in db.executive_ledger.aggregate(pipe):
        by_cid[r["_id"]] = r

    rows = []
    for t in tenants:
        cid = t.get("id")
        if not cid:
            continue
        info = by_cid.get(cid, {"n": 0, "confirmado": 0, "previsto": 0})
        # ARR estimado por empresa (para benchmark)
        async for arr in db.subscribers.aggregate(
            [{"$match": {"company_id": cid,
                              "status": {"$in": ["ATIVO", "ATIVA"]},
                              "plan_price": {"$gt": 0}}},
             {"$group": {"_id": None,
                              "mrr": {"$sum": "$plan_price"},
                              "n": {"$sum": 1}}}]):
            mrr = arr["mrr"]
            n_subs = arr["n"]
            break
        else:
            mrr = 0
            n_subs = 0
        rows.append({
            "company_id": cid,
            "name": t.get("name") or cid,
            "subscribers_ativos": n_subs,
            "mrr_brl": round(mrr, 2),
            "acoes_executadas": info["n"],
            "caixa_confirmado_brl": round(info["confirmado"], 2),
            "caixa_previsto_brl": round(info["previsto"], 2),
            "taxa_acerto_pct":
                (round(info["confirmado"] / info["previsto"] * 100, 1)
                 if info["previsto"] else 0.0),
        })
    rows.sort(key=lambda x: x["caixa_confirmado_brl"], reverse=True)
    total = round(sum(r["caixa_confirmado_brl"] for r in rows), 2)
    return {
        "tenants": rows,
        "total_caixa_confirmado_brl": total,
        "n_tenants": len(rows),
        "generated_at": _iso(_now()),
    }


async def per_client_value(company_id: str,
                                limit: int = 50) -> List[Dict[str, Any]]:
    """Score por cliente = LTV − tickets_extra_cost.
    Cliente que dá dinheiro vs cliente que custa."""
    # Top recurring (custam mais)
    pipe = [{"$match": {"company_id": company_id,
                            "client_id": {"$ne": None}}},
             {"$group": {"_id": "$client_id",
                            "n_tickets": {"$sum": 1}}},
             {"$sort": {"n_tickets": -1}}, {"$limit": limit}]
    rows = []
    async for r in db.tickets.aggregate(pipe):
        sub = await db.subscribers.find_one(
            {"company_id": company_id, "id": r["_id"]},
            {"_id": 0, "id": 1, "name": 1, "plan_price": 1,
             "status": 1})
        if not sub:
            continue
        plan = sub.get("plan_price") or 0
        ltv = plan * 24  # 24 meses heurística
        custo_extra = (r["n_tickets"] - 1) * 40
        score = round(ltv - custo_extra, 2)
        rows.append({
            "client_id": r["_id"],
            "plan_price_brl": plan,
            "tickets": r["n_tickets"],
            "ltv_brl": ltv,
            "custo_extra_brl": custo_extra,
            "score_brl": score,
            "status": sub.get("status"),
        })
    return rows


# ─────────────────────────────────────────────
# FASE 7 — AUDITORIA FINAL (10 perguntas)
# ─────────────────────────────────────────────
async def final_audit() -> Dict[str, Any]:
    """Responde as 10 perguntas obrigatórias do CTO."""
    cross = await cross_tenant_ranking()
    total_confirmado = cross["total_caixa_confirmado_brl"]

    # Soma por módulo agregada cross-tenant
    pipe = [{"$group": {"_id": "$modulo",
                             "confirmado":
                                 {"$sum": "$valor_confirmado_brl"},
                             "n": {"$sum": 1}}}]
    modulos = []
    async for r in db.executive_ledger.aggregate(pipe):
        modulos.append({"modulo": r["_id"],
                          "confirmado_brl": round(r["confirmado"], 2),
                          "acoes": r["n"]})
    modulos.sort(key=lambda x: x["confirmado_brl"], reverse=True)

    # Ranking IAs cross-tenant
    pipe = [{"$group": {"_id": "$responsavel",
                             "confirmado":
                                 {"$sum": "$valor_confirmado_brl"},
                             "n": {"$sum": 1}}}]
    ias = []
    async for r in db.executive_ledger.aggregate(pipe):
        ias.append({"ia": r["_id"],
                     "confirmado_brl": round(r["confirmado"], 2),
                     "acoes": r["n"]})
    ias.sort(key=lambda x: x["confirmado_brl"], reverse=True)

    # Top action cross-tenant
    top_action = None
    async for r in db.executive_ledger.find(
        {}, {"_id": 0}).sort("valor_confirmado_brl", -1).limit(1):
        top_action = r

    # Recuperado (Cobrança + Retenção)
    recuperado = sum(m["confirmado_brl"] for m in modulos
                       if m["modulo"] in ("Cobrança", "Retenção"))
    # Evitado (Smart Field + CAPEX)
    evitado = sum(m["confirmado_brl"] for m in modulos
                    if m["modulo"] in ("Smart Field", "CAPEX"))
    # Gerado (Receita + Indicação + cross-sell)
    gerado = sum(m["confirmado_brl"] for m in modulos
                   if m["modulo"] in
                       ("Receita", "Indicação", "PlayHub",
                        "Ligo Móvel", "Security Home", "Fleet"))

    # Top empresa
    top_empresa = cross["tenants"][0] if cross["tenants"] else None

    # Per-client top
    clientes_top = await per_client_value(
        top_empresa["company_id"] if top_empresa else "co-demo",
        limit=10) if top_empresa else []

    # Valor SmartProv (sum dos EVs dos tenants)
    valor_smartprov = 0.0
    from services.presidente_operator import company_value
    evs = []
    for t in cross["tenants"]:
        try:
            cv = await company_value(t["company_id"])
            evs.append({"company_id": t["company_id"],
                          "name": t["name"],
                          "ev_brl": cv["enterprise_value_brl"]})
            valor_smartprov += cv["enterprise_value_brl"]
        except Exception:
            pass

    return {
        "generated_at": _iso(_now()),
        "perguntas": {
            "1_quanto_smartprov_gerou_brl": round(gerado, 2),
            "2_quanto_recuperou_brl": round(recuperado, 2),
            "3_quanto_evitou_perder_brl": round(evitado, 2),
            "4_acao_que_gerou_mais_caixa": top_action,
            "5_ia_que_gerou_mais_caixa": ias[0] if ias else None,
            "6_modulo_que_gerou_mais_caixa":
                modulos[0] if modulos else None,
            "7_empresa_que_gerou_mais_caixa": top_empresa,
            "8_top_10_clientes_valor": clientes_top,
            "9_valor_por_empresa": evs,
            "10_valor_total_smartprov_brl": round(valor_smartprov, 2),
        },
        "total_caixa_confirmado_cross_tenant_brl": total_confirmado,
        "modulos_cross_tenant": modulos,
        "ias_cross_tenant": ias,
    }
