"""
presidente_score_engine.py — iter242

Engine único do PRESIDENT_SCORE.
Lê 12 áreas em paralelo a partir de collections REAIS do MongoDB.
Persiste em `president_score_snapshots`.

Filosofia:
  - Toda área retorna: {source, query, last_ts, doc_count, score, status, reason, weight}
  - Áreas sem dados não somem — viram score=0 status=sem_dados motivo explícito.
  - Score final = soma ponderada.
  - Maturidade = % de áreas com status != sem_dados.

Sem mocks. Sem ROI inventado. Tudo evidência rastreável.
"""
import logging
import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

logger = logging.getLogger("presidente_score_engine")

_client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = _client[os.environ["DB_NAME"]]

# Pesos das 12 áreas. Soma = 1.0
WEIGHTS = {
    "receita":        0.13,
    "churn":          0.10,
    "financeiro":     0.10,
    "estoque":        0.06,
    "rede":           0.10,
    "seguranca":      0.06,
    "operacao":       0.10,
    "vendas":         0.10,
    "atendimento":    0.08,
    "ia":             0.06,
    "tesouraria":     0.06,
    "universo_ligo":  0.05,
}

SOURCE_VERSION = "score_engine_v1.0_iter242"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: Optional[datetime]) -> Optional[str]:
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return d.isoformat()


def _environment_label() -> str:
    """Retorna 'production' | 'preview' | 'sandbox' baseado nos sinais reais."""
    if (os.environ.get("ASAAS_PROD_ENABLED") or "").lower() in ("true", "1"):
        return "production"
    asaas = (os.environ.get("ASAAS_ENV") or "").lower()
    rab = os.environ.get("REACT_APP_BACKEND_URL", "")
    if "preview.emergentagent.com" in rab:
        return "preview"
    if asaas in ("sandbox", "homologation", "hmlg"):
        return "preview_sandbox"
    return "ambiente_nao_confirmado"


# ──────────────────────────────────────────────────────────────────────────
# Utilities — leitura segura e cálculo de score por área
# ──────────────────────────────────────────────────────────────────────────
async def _count(col: str, q: Optional[Dict] = None) -> int:
    if col not in await db.list_collection_names():
        return 0
    return await db[col].count_documents(q or {})


async def _exists(col: str) -> bool:
    return col in await db.list_collection_names()


async def _last_ts(col: str) -> Optional[str]:
    """Tenta achar o timestamp mais recente em uma collection (best-effort)."""
    if not await _exists(col):
        return None
    fields_priority = ["created_at", "updated_at", "ts", "timestamp",
                        "snapshot_at", "executed_at", "occurred_at", "event_at"]
    for f in fields_priority:
        try:
            d = await db[col].find_one({f: {"$exists": True}},
                                          sort=[(f, -1)],
                                          projection={f: 1})
            if d and d.get(f):
                return _iso(d[f])
        except Exception:
            continue
    # fallback: _id-based (ObjectId timestamp)
    try:
        d = await db[col].find_one({}, sort=[("_id", -1)])
        if d and "_id" in d:
            from bson import ObjectId
            if isinstance(d["_id"], ObjectId):
                return _iso(d["_id"].generation_time)
    except Exception:
        pass
    return None


def _area(name: str, *, sources: List[str], queries: List[str],
           score: float, doc_count: int = 0,
           last_ts: Optional[str] = None, reason: str = "",
           status: Optional[str] = None) -> Dict[str, Any]:
    score = max(0.0, min(100.0, float(score)))
    if status is None:
        if doc_count == 0:
            status = "sem_dados"
            score = 0.0
        elif score >= 80:
            status = "verde"
        elif score >= 60:
            status = "amarelo"
        else:
            status = "vermelho"
    return {
        "name": name,
        "sources": sources,
        "queries": queries,
        "doc_count": doc_count,
        "last_ts": last_ts,
        "score": round(score, 1),
        "status": status,
        "reason": reason or "",
        "weight": WEIGHTS.get(name, 0.0),
    }


# ──────────────────────────────────────────────────────────────────────────
# 12 áreas
# ──────────────────────────────────────────────────────────────────────────
async def _area_receita(cid: str) -> Dict:
    """RECEITA — executive_ledger + invoices + subscribers."""
    q_ledger = {"company_id": cid,
                  "kind": {"$in": ["revenue", "receita", "income"]}}
    n_ledger = await _count("executive_ledger", q_ledger)
    n_invoices = await _count("invoices", {"company_id": cid})
    n_subscribers = await _count("subscribers", {"company_id": cid,
                                                    "status": {"$in": ["ativo", "active", "ATIVO"]}})
    n_subs_total = await _count("subscribers", {"company_id": cid})
    cobertura_subs = (n_subscribers / n_subs_total * 100) if n_subs_total else 0
    score = min(100.0, cobertura_subs * 0.5 + (50 if n_ledger > 0 else 0))
    return _area("receita",
                  sources=["executive_ledger", "invoices", "subscribers"],
                  queries=[
                      f"executive_ledger {{kind:revenue}} → {n_ledger}",
                      f"invoices → {n_invoices}",
                      f"subscribers ativos → {n_subscribers}/{n_subs_total}",
                  ],
                  doc_count=n_ledger + n_invoices + n_subscribers,
                  last_ts=await _last_ts("executive_ledger"),
                  score=score,
                  reason=f"ativos={n_subscribers} cobertura={cobertura_subs:.1f}%")


async def _area_churn(cid: str) -> Dict:
    """CHURN — isabella_churn_runs + churn_insights + isabella_followups."""
    n_runs = await _count("isabella_churn_runs", {"company_id": cid})
    n_insights = await _count("churn_insights", {"company_id": cid})
    n_followups = await _count("isabella_followups", {"company_id": cid})
    last = await _last_ts("isabella_churn_runs") or await _last_ts("churn_insights")
    total = n_runs + n_insights + n_followups
    # Quanto mais runs/insights, melhor (cobertura ativa)
    score = min(100.0, total * 2)
    return _area("churn",
                  sources=["isabella_churn_runs", "churn_insights",
                            "isabella_followups"],
                  queries=[f"runs={n_runs}, insights={n_insights}, followups={n_followups}"],
                  doc_count=total, last_ts=last, score=score,
                  reason=f"cobertura_churn={total} eventos")


async def _area_financeiro(cid: str) -> Dict:
    """FINANCEIRO — financeiro_movs + scheduled_payments + executive_ledger."""
    n_movs = await _count("financeiro_movs", {"company_id": cid})
    n_sched = await _count("scheduled_payments", {"company_id": cid})
    sched_pending = await _count("scheduled_payments",
        {"company_id": cid, "status": {"$in": ["draft", "pending_human_approval", "approved"]}})
    sched_blocked = await _count("scheduled_payments",
        {"company_id": cid, "status": "blocked_risk"})
    last = await _last_ts("financeiro_movs") or await _last_ts("scheduled_payments")
    total = n_movs + n_sched
    score = 100.0 - min(80, sched_blocked * 5)
    if total < 5:
        score = min(score, 50.0)
    return _area("financeiro",
                  sources=["financeiro_movs", "scheduled_payments",
                            "executive_ledger"],
                  queries=[
                      f"financeiro_movs={n_movs}",
                      f"scheduled_payments={n_sched} (pending={sched_pending}, blocked={sched_blocked})",
                  ],
                  doc_count=total, last_ts=last, score=score,
                  reason=f"blocked_risk={sched_blocked} pending={sched_pending}")


async def _area_estoque(cid: str) -> Dict:
    """ESTOQUE — client_equipment_history + field_equipment_returns."""
    n_hist = await _count("client_equipment_history", {"company_id": cid})
    n_ret = await _count("field_equipment_returns", {"company_id": cid})
    last = await _last_ts("client_equipment_history") or await _last_ts("field_equipment_returns")
    total = n_hist + n_ret
    score = min(100.0, total * 0.5)
    return _area("estoque",
                  sources=["client_equipment_history",
                            "field_equipment_returns"],
                  queries=[f"history={n_hist}, returns={n_ret}"],
                  doc_count=total, last_ts=last, score=score,
                  reason="medição parcial — coleções de inventário canônicas ausentes")


async def _area_rede(cid: str) -> Dict:
    """REDE — smartolt_onus + network_outages + incidents."""
    bq = {"company_id": cid} if cid else {}
    total_onu = await _count("smartolt_onus", bq)
    online = await _count("smartolt_onus", {**bq, "status": "Online"})
    los = await _count("smartolt_onus", {**bq, "status": "LOS"})
    pfail = await _count("smartolt_onus", {**bq, "status": "Power fail"})
    offl = await _count("smartolt_onus", {**bq, "status": "Offline"})
    null_status = await _count("smartolt_onus", {**bq, "status": None})
    n_outages = await _count("network_outages", bq)
    n_inc = await _count("incidents", bq)
    crit = los + pfail + offl
    last = await _last_ts("smartolt_onus") or await _last_ts("incidents")
    if online == 0:
        score = 0.0
        reason = f"sem ONUs Online — total={total_onu} null={null_status} crit={crit}"
    else:
        # Score baseado em % de Online sobre o total (excluindo null)
        denom = max(1, total_onu - null_status)
        pct_online = online / denom * 100
        score = max(0.0, pct_online - n_outages * 2)
        reason = f"online={online} crit={crit} null={null_status} outages={n_outages}"
    return _area("rede",
                  sources=["smartolt_onus", "network_outages", "incidents"],
                  queries=[
                      f"smartolt_onus total={total_onu} online={online} LOS={los} pfail={pfail} offline={offl} null={null_status}",
                      f"network_outages={n_outages}, incidents={n_inc}",
                  ],
                  doc_count=total_onu, last_ts=last, score=score,
                  reason=reason)


async def _area_seguranca(cid: str) -> Dict:
    """SEGURANÇA — shield_audit_history + audit_log + system_events."""
    n_shield = await _count("shield_audit_history", {"company_id": cid})
    n_audit = await _count("audit_log", {"company_id": cid})
    n_chain = await _count("audit_chain", {"company_id": cid})
    last = await _last_ts("shield_audit_history") or await _last_ts("audit_log")
    total = n_shield + n_audit + n_chain
    # Coverage proxy: ter audit chain ativo + shield rodando = green
    score = 50 + (25 if n_shield > 0 else 0) + (25 if n_chain > 0 else 0)
    return _area("seguranca",
                  sources=["shield_audit_history", "audit_log", "audit_chain"],
                  queries=[f"shield={n_shield}, audit_log={n_audit}, audit_chain={n_chain}"],
                  doc_count=total, last_ts=last, score=score,
                  reason=f"shield={n_shield > 0} chain={n_chain > 0}")


async def _area_operacao(cid: str) -> Dict:
    """OPERAÇÃO — tickets + collaborators + incidents."""
    bq = {"company_id": cid} if cid else {}
    total_t = await _count("tickets", bq)
    open_t = await _count("tickets", {**bq, "status": {"$in": ["aberta", "pendente", "open"]}})
    closed_t = await _count("tickets", {**bq, "status": {"$in": ["encerrada", "resolved", "closed", "auto_arquivado"]}})
    n_col = await _count("collaborators", bq)
    last = await _last_ts("tickets")
    if total_t == 0:
        score = 0
        reason = "sem tickets"
    else:
        pct_closed = closed_t / total_t * 100
        score = max(0.0, pct_closed - max(0, open_t - 200) * 0.05)
        reason = f"open={open_t} closed={closed_t} closed_pct={pct_closed:.1f}%"
    return _area("operacao",
                  sources=["tickets", "collaborators", "incidents"],
                  queries=[
                      f"tickets total={total_t} open={open_t} closed={closed_t}",
                      f"collaborators={n_col}",
                  ],
                  doc_count=total_t, last_ts=last, score=score,
                  reason=reason)


async def _area_vendas(cid: str) -> Dict:
    """VENDAS — sales_leads + site_leads + indicacao_leads + isabella_opportunities."""
    n_s = await _count("sales_leads", {"company_id": cid})
    n_site = await _count("site_leads", {"company_id": cid})
    n_ind = await _count("indicacao_leads", {"company_id": cid})
    n_opp = await _count("isabella_opportunities", {"company_id": cid})
    last = await _last_ts("isabella_opportunities") or await _last_ts("sales_leads")
    total = n_s + n_site + n_ind + n_opp
    score = min(100.0, total * 0.005 + (40 if n_opp > 0 else 0))
    return _area("vendas",
                  sources=["sales_leads", "site_leads", "indicacao_leads",
                            "isabella_opportunities"],
                  queries=[
                      f"sales_leads={n_s}, site_leads={n_site}, indicacao={n_ind}",
                      f"isabella_opportunities={n_opp}",
                  ],
                  doc_count=total, last_ts=last, score=score,
                  reason=f"pipeline_total={total}")


async def _area_atendimento(cid: str) -> Dict:
    """ATENDIMENTO — aihub_wa_messages + wa_conversations + ai_evaluations + isabella_followups."""
    n_msg = await _count("aihub_wa_messages", {"company_id": cid})
    n_conv = await _count("wa_conversations", {"company_id": cid})
    n_eval = await _count("ai_evaluations", {"company_id": cid})
    n_fol = await _count("isabella_followups", {"company_id": cid})
    last = await _last_ts("aihub_wa_messages") or await _last_ts("ai_evaluations")
    total = n_msg + n_conv + n_eval + n_fol
    score = min(100.0, (n_msg * 0.001) + (n_eval * 0.01) + 50)
    return _area("atendimento",
                  sources=["aihub_wa_messages", "wa_conversations",
                            "ai_evaluations", "isabella_followups"],
                  queries=[
                      f"wa_messages={n_msg}, conversations={n_conv}",
                      f"ai_evaluations={n_eval}, followups={n_fol}",
                  ],
                  doc_count=total, last_ts=last, score=score,
                  reason=f"msgs={n_msg} eval={n_eval}")


async def _area_ia(cid: str) -> Dict:
    """IA — agent_registry_snapshots + aihub_agents + ai_evaluations + system_events."""
    n_snap = await _count("agent_registry_snapshots", {"company_id": cid})
    n_agents = await _count("aihub_agents", {"company_id": cid})
    n_events = await _count("system_events", {"company_id": cid})
    last = await _last_ts("agent_registry_snapshots") or await _last_ts("system_events")
    # Score: tem snapshots + agentes registrados + eventos correntes
    score = 0.0
    score += 40 if n_agents >= 5 else (n_agents * 8)
    score += 30 if n_snap >= 5 else (n_snap * 6)
    score += 30 if n_events >= 100 else (n_events * 0.3)
    return _area("ia",
                  sources=["agent_registry_snapshots", "aihub_agents",
                            "system_events"],
                  queries=[
                      f"agents={n_agents}, snapshots={n_snap}, system_events={n_events}",
                  ],
                  doc_count=n_snap + n_agents + n_events, last_ts=last,
                  score=score,
                  reason=f"agents_registered={n_agents}")


async def _area_tesouraria(cid: str) -> Dict:
    """TESOURARIA — scheduled_payments + treasurer_ai_decisions + whitelisted_payees."""
    n_sched = await _count("scheduled_payments", {"company_id": cid})
    paid = await _count("scheduled_payments", {"company_id": cid, "status": "paid"})
    pending = await _count("scheduled_payments", {"company_id": cid, "status": {"$in": ["draft", "pending_human_approval", "approved"]}})
    blocked = await _count("scheduled_payments", {"company_id": cid, "status": "blocked_risk"})
    n_dec = await _count("treasurer_ai_decisions", {"company_id": cid})
    n_payees = await _count("whitelisted_payees", {"company_id": cid})
    last = await _last_ts("scheduled_payments") or await _last_ts("treasurer_ai_decisions")
    total = n_sched + n_dec + n_payees
    # Score: ter pagamentos operacionais + decisões IA + payees cadastrados
    score = 0.0
    score += min(40, n_sched * 4)
    score += min(30, n_payees * 4)
    score += min(30, n_dec * 5)
    return _area("tesouraria",
                  sources=["scheduled_payments", "treasurer_ai_decisions",
                            "whitelisted_payees"],
                  queries=[
                      f"scheduled={n_sched} paid={paid} pending={pending} blocked={blocked}",
                      f"treasurer_decisions={n_dec}, payees={n_payees}",
                  ],
                  doc_count=total, last_ts=last, score=score,
                  reason=f"adocao_pagamentos={n_sched} payees={n_payees}")


async def _area_universo_ligo(cid: str) -> Dict:
    """UNIVERSO LIGO — referrals + loyalty_imported_db + loyalty_opportunities."""
    n_ref = await _count("referrals", {"company_id": cid})
    n_loy = await _count("loyalty_imported_db", {"company_id": cid})
    n_opp = await _count("loyalty_opportunities", {"company_id": cid})
    n_imp_log = await _count("loyalty_import_log", {"company_id": cid})
    last = await _last_ts("referrals") or await _last_ts("loyalty_imported_db")
    total = n_ref + n_loy + n_opp + n_imp_log
    score = min(100.0, n_loy * 0.005 + n_opp * 1.0 + (20 if n_ref > 0 else 0))
    return _area("universo_ligo",
                  sources=["referrals", "loyalty_imported_db",
                            "loyalty_opportunities", "loyalty_import_log"],
                  queries=[
                      f"referrals={n_ref}, loyalty_db={n_loy}, opportunities={n_opp}",
                  ],
                  doc_count=total, last_ts=last, score=score,
                  reason=f"referrals={n_ref} loyalty_base={n_loy}")


# ──────────────────────────────────────────────────────────────────────────
# COMPUTE — orquestração
# ──────────────────────────────────────────────────────────────────────────
async def compute_score(company_id: str) -> Dict[str, Any]:
    """Computa o score completo das 12 áreas."""
    import asyncio
    started = _now()
    cid = company_id or "co-demo"

    # Roda todas as áreas em paralelo
    results = await asyncio.gather(
        _area_receita(cid),
        _area_churn(cid),
        _area_financeiro(cid),
        _area_estoque(cid),
        _area_rede(cid),
        _area_seguranca(cid),
        _area_operacao(cid),
        _area_vendas(cid),
        _area_atendimento(cid),
        _area_ia(cid),
        _area_tesouraria(cid),
        _area_universo_ligo(cid),
        return_exceptions=True,
    )

    components: Dict[str, Dict] = {}
    for r in results:
        if isinstance(r, Exception):
            logger.error("area exception: %r", r)
            continue
        components[r["name"]] = r

    # Score ponderado
    total = 0.0
    for name, comp in components.items():
        total += comp["score"] * comp["weight"]

    # Maturidade = % áreas com dados (status != sem_dados)
    n_total = len(components)
    n_com_dados = sum(1 for c in components.values()
                       if c["status"] != "sem_dados")
    maturity = (n_com_dados / n_total * 100) if n_total else 0.0

    sorted_by_impact = sorted(
        components.values(),
        key=lambda c: c["score"] * c["weight"],
    )
    worst = sorted_by_impact[:3]
    best = sorted_by_impact[-3:][::-1]

    snap = {
        "company_id": cid,
        "environment": _environment_label(),
        "score_total": round(total, 1),
        "maturity_total": round(maturity, 1),
        "components": components,
        "worst_drivers": [{"name": w["name"], "score": w["score"],
                            "weight": w["weight"], "reason": w["reason"]}
                           for w in worst],
        "best_drivers": [{"name": b["name"], "score": b["score"],
                            "weight": b["weight"], "reason": b["reason"]}
                          for b in best],
        "created_at": _now().isoformat(),
        "computed_in_ms": int((_now() - started).total_seconds() * 1000),
        "source_version": SOURCE_VERSION,
        "hostname": socket.gethostname(),
        "areas_count": n_total,
        "areas_with_data": n_com_dados,
        "weights_sum": round(sum(WEIGHTS.values()), 3),
    }
    return snap


async def save_snapshot(snap: Dict) -> str:
    """Persiste em president_score_snapshots e retorna o _id."""
    doc = dict(snap)
    res = await db.president_score_snapshots.insert_one(doc)
    return str(res.inserted_id)


async def compute_and_save(company_id: str) -> Dict:
    snap = await compute_score(company_id)
    snap["_id"] = await save_snapshot(snap)
    return snap


async def history(company_id: str, days: int = 30,
                   limit: int = 1000) -> List[Dict]:
    since = (_now() - timedelta(days=days)).isoformat()
    out: List[Dict] = []
    async for d in db.president_score_snapshots.find(
            {"company_id": company_id, "created_at": {"$gte": since}},
            {"_id": 0, "components": 0}
    ).sort("created_at", 1).limit(limit):
        out.append(d)
    return out


async def daily_snapshot_job():
    """APScheduler job — snapshot diário do score por empresa."""
    cids = ["co-demo"]
    if "companies" in await db.list_collection_names():
        seen = await db.companies.distinct("_id")
        if seen:
            cids = [str(x) for x in seen]
    for cid in cids:
        try:
            snap = await compute_and_save(cid)
            logger.info("daily snapshot %s: score=%s maturity=%s",
                          cid, snap["score_total"], snap["maturity_total"])
        except Exception as e:
            logger.warning("daily snapshot failed for %s: %r", cid, e)
