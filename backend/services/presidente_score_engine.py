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
    """RECEITA — subscribers ativos + invoices + ledger de valor IA."""
    bq = {"company_id": cid}
    n_ledger = await _count("executive_ledger", bq)
    n_invoices = await _count("invoices", bq)
    n_subscribers = await _count("subscribers",
        {**bq, "status": {"$in": ["ativo", "active", "ATIVO", "ACTIVE"]}})
    n_subs_total = await _count("subscribers", bq)
    cutoff = (_now() - timedelta(days=30)).isoformat()
    n_novos = await _count("subscribers",
        {**bq, "created_at": {"$gte": cutoff}})
    cobertura_subs = (n_subscribers / n_subs_total * 100) if n_subs_total else 0
    # Score em 3 pilares: base ativa (50%) + crescimento 30d (25%) + valor IA (25%)
    score = 0.0
    score += min(50, cobertura_subs * 0.5)
    score += 25 if n_novos > 0 else 0
    score += 25 if n_ledger > 0 else 0
    return _area("receita",
                  sources=["subscribers", "executive_ledger", "invoices"],
                  queries=[
                      f"subscribers ativos={n_subscribers}/{n_subs_total} ({cobertura_subs:.1f}%)",
                      f"novos_30d={n_novos}, invoices={n_invoices}",
                      f"executive_ledger (eventos de valor IA)={n_ledger}",
                  ],
                  doc_count=n_ledger + n_invoices + n_subscribers,
                  last_ts=await _last_ts("subscribers")
                          or await _last_ts("executive_ledger"),
                  score=score,
                  reason=f"ativos={n_subscribers} novos_30d={n_novos} eventos_IA={n_ledger}")


async def _area_churn(cid: str) -> Dict:
    """CHURN — todos os sinais de proteção de receita disponíveis."""
    bq = {"company_id": cid}
    n_runs = await _count("isabella_churn_runs", bq)
    n_insights = await _count("churn_insights", bq)
    n_followups = await _count("isabella_followups", bq)
    n_outcomes = await _count("isabella_outcomes", bq)
    n_relationship = await _count("isabella_council_minutes", bq)
    n_executive = await _count("isabella_executive_policies", bq)
    last = (await _last_ts("churn_insights")
              or await _last_ts("isabella_outcomes"))
    total = (n_runs + n_insights + n_followups + n_outcomes
              + n_relationship + n_executive)
    # Score por cobertura: cada source com docs vale 16 pts
    sources_alive = sum(1 for n in [n_runs, n_insights, n_followups,
                                       n_outcomes, n_relationship,
                                       n_executive] if n > 0)
    score = min(100.0, sources_alive * 17 + min(20, total * 0.3))
    return _area("churn",
                  sources=["isabella_churn_runs", "churn_insights",
                            "isabella_followups", "isabella_outcomes",
                            "isabella_council_minutes",
                            "isabella_executive_policies"],
                  queries=[
                      f"churn_runs={n_runs}, insights={n_insights}",
                      f"followups={n_followups}, outcomes={n_outcomes}",
                      f"council_minutes={n_relationship}, exec_policies={n_executive}",
                  ],
                  doc_count=total, last_ts=last, score=score,
                  reason=f"cobertura={sources_alive}/6 sources, total={total}")


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
    """ESTOQUE — soma todas as collections de inventário/equipamento reais."""
    bq = {"company_id": cid}
    n_hist = await _count("client_equipment_history", bq)
    n_ret = await _count("field_equipment_returns", bq)
    n_inst = await _count("smart_installs", bq)
    n_serv = await _count("stok_services", bq)
    n_stok_hist = await _count("stok_history", bq)
    n_balanco = await _count("stok_balanco_sessions", bq)
    n_admin = await _count("stok_admin_log", bq)
    n_onts = await _count("stok_onts", {})
    n_stock = await _count("stok_stock", {})
    n_pend = await _count("stok_pending_transfers", bq)
    n_col_assets = await _count("collaborator_assets", bq)
    n_map_assets = await _count("ligo_map_assets", bq)
    last = (await _last_ts("client_equipment_history")
              or await _last_ts("smart_installs")
              or await _last_ts("stok_history"))
    total = (n_hist + n_ret + n_inst + n_serv + n_stok_hist + n_balanco
              + n_admin + n_onts + n_stock + n_pend + n_col_assets
              + n_map_assets)
    # Score: cobertura por collection alimentada (variedade de inputs)
    cols_alive = sum(1 for v in [n_hist, n_inst, n_serv, n_stok_hist,
                                    n_balanco, n_onts, n_col_assets,
                                    n_map_assets, n_stock] if v > 0)
    score = min(100.0, cols_alive * 12 + min(20, total * 0.005))
    return _area("estoque",
                  sources=["client_equipment_history", "smart_installs",
                            "stok_services", "stok_history",
                            "stok_balanco_sessions", "stok_onts",
                            "stok_stock", "stok_pending_transfers",
                            "collaborator_assets", "ligo_map_assets",
                            "field_equipment_returns", "stok_admin_log"],
                  queries=[
                      f"client_equipment_history={n_hist}",
                      f"smart_installs={n_inst} (instalações registradas)",
                      f"stok_services={n_serv}, stok_history={n_stok_hist}",
                      f"stok_onts={n_onts}, stok_stock={n_stock}",
                      f"balanco_sessions={n_balanco}, pending_transfers={n_pend}",
                      f"collaborator_assets={n_col_assets}, ligo_map_assets={n_map_assets}",
                  ],
                  doc_count=total, last_ts=last, score=score,
                  reason=f"cobertura={cols_alive}/9 collections alimentadas")


async def _area_rede(cid: str) -> Dict:
    """REDE — smartolt_onus + network_outages + incidents (só abertos)."""
    bq = {"company_id": cid} if cid else {}
    total_onu = await _count("smartolt_onus", bq)
    online = await _count("smartolt_onus", {**bq, "status": "Online"})
    los = await _count("smartolt_onus", {**bq, "status": "LOS"})
    pfail = await _count("smartolt_onus", {**bq, "status": "Power fail"})
    offl = await _count("smartolt_onus", {**bq, "status": "Offline"})
    null_status = await _count("smartolt_onus", {**bq, "status": None})
    n_outages_total = await _count("network_outages", bq)
    n_outages_open = await _count("network_outages",
        {**bq, "resolved_at": {"$exists": False}})
    n_inc = await _count("incidents", bq)
    n_inc_open = await _count("incidents",
        {**bq, "status": {"$nin": ["resolved", "closed", "fechado"]}})
    crit = los + pfail + offl
    last = await _last_ts("smartolt_onus") or await _last_ts("incidents")
    if online == 0:
        score = 0.0
        reason = f"sem ONUs Online — total={total_onu} null={null_status}"
    else:
        denom = max(1, total_onu - null_status)
        pct_online = online / denom * 100
        # Penaliza APENAS incidents/outages que estão ABERTOS
        score = max(0.0, pct_online - n_outages_open * 3 - n_inc_open * 1)
        reason = (f"online={online} crit={crit} null={null_status} "
                   f"outages_open={n_outages_open}/{n_outages_total} "
                   f"inc_open={n_inc_open}/{n_inc}")
    return _area("rede",
                  sources=["smartolt_onus", "network_outages", "incidents"],
                  queries=[
                      f"smartolt_onus total={total_onu} online={online} crit={crit} null={null_status}",
                      f"network_outages total={n_outages_total} open={n_outages_open}",
                      f"incidents total={n_inc} open={n_inc_open}",
                  ],
                  doc_count=total_onu, last_ts=last, score=score,
                  reason=reason)


async def _area_seguranca(cid: str) -> Dict:
    """SEGURANÇA — soma todos os audit/security/governance trails."""
    bq = {"company_id": cid}
    audit_cols = [
        "audit_log", "audit_chain", "shield_audit_history",
        "platform_audit", "cto_audits", "payment_audit_logs",
        "conselho_ia_audit_log", "isabella_precision_audits",
        "experience_campaigns_audit", "connection_audit",
        "smartolt_zone_audit", "print_audit", "withdraw_sn_audit",
        "red_team_audits",
    ]
    sec_cols = ["security_alarms", "security_arm_states",
                 "security_panel_commands", "security_sites",
                 "security_sensors", "security_tenants"]
    audit_counts: Dict[str, int] = {}
    audit_total = 0
    for c in audit_cols:
        n = await _count(c, bq if c in (
            "audit_log", "platform_audit", "cto_audits",
            "payment_audit_logs", "conselho_ia_audit_log",
            "isabella_precision_audits", "experience_campaigns_audit",
            "connection_audit", "smartolt_zone_audit", "print_audit",
            "withdraw_sn_audit") else {})
        audit_counts[c] = n
        audit_total += n
    sec_total = 0
    for c in sec_cols:
        sec_total += await _count(c, bq if c.startswith("security_") else {})
    last = (await _last_ts("audit_log")
              or await _last_ts("platform_audit"))
    cols_alive = sum(1 for n in audit_counts.values() if n > 0)
    # Score: cobertura por trail + volume
    score = 0.0
    score += min(50, cols_alive * 5)  # cobertura de tipos de audit
    score += min(30, audit_total * 0.05)  # volume
    score += 20 if sec_total > 0 else 0
    return _area("seguranca",
                  sources=audit_cols + sec_cols,
                  queries=[
                      f"audit_log={audit_counts['audit_log']}, platform_audit={audit_counts['platform_audit']}",
                      f"cto_audits={audit_counts['cto_audits']}, conselho_audit={audit_counts['conselho_ia_audit_log']}",
                      f"payment_audit={audit_counts['payment_audit_logs']}, shield={audit_counts['shield_audit_history']}",
                      f"chain={audit_counts['audit_chain']}, red_team={audit_counts['red_team_audits']}",
                      f"isabella_precision={audit_counts['isabella_precision_audits']}",
                      f"security_module={sec_total}",
                  ],
                  doc_count=audit_total + sec_total, last_ts=last,
                  score=score,
                  reason=f"trails_ativos={cols_alive}/{len(audit_cols)} security_volume={sec_total}")


async def _area_operacao(cid: str) -> Dict:
    """OPERAÇÃO — tickets + collaborators + incidents."""
    bq = {"company_id": cid} if cid else {}
    total_t = await _count("tickets", bq)
    open_t = await _count("tickets", {**bq, "status": {"$in": ["aberta", "pendente", "open"]}})
    closed_t = await _count("tickets", {**bq, "status": {"$in":
        ["encerrada", "finalizada", "resolved", "closed", "auto_arquivado", "fechada"]}})
    n_col = await _count("collaborators", bq)
    last = await _last_ts("tickets")
    if total_t == 0:
        score = 0
        reason = "sem tickets"
    else:
        pct_closed = closed_t / total_t * 100
        # Penaliza só backlog excessivo (acima de 200 abertos)
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
    """VENDAS — funil completo: leads → opportunities → instalações → ativos."""
    bq = {"company_id": cid}
    n_sales = await _count("sales_leads", bq)
    n_site = await _count("site_leads", bq)
    n_ind = await _count("indicacao_leads", bq)
    n_opp = await _count("isabella_opportunities", bq)
    n_cmd_opp = await _count("isabella_commander_opportunities", bq)
    n_props = await _count("projetos_propostas", bq)
    n_installs = await _count("smart_installs", bq)
    # Ativações reais nos últimos 30d
    cutoff = (_now() - timedelta(days=30)).isoformat()
    n_ativos = await _count("subscribers",
        {**bq, "status": {"$in": ["ATIVO", "ativo", "active", "ACTIVE"]}})
    n_novos_30d = await _count("subscribers",
        {**bq, "created_at": {"$gte": cutoff}})
    last = (await _last_ts("isabella_commander_opportunities")
              or await _last_ts("smart_installs"))
    total = (n_sales + n_site + n_ind + n_opp + n_cmd_opp + n_props
              + n_installs + n_novos_30d)
    # Score: tem leads (20) + tem opportunities (20) + tem propostas (20)
    # + tem instalações (20) + tem novos ativos 30d (20)
    score = 0.0
    score += 20 if (n_sales + n_site + n_ind) > 0 else 0
    score += 20 if (n_opp + n_cmd_opp) > 0 else 0
    score += 20 if n_props > 0 else 0
    score += 20 if n_installs > 0 else 0
    score += 20 if n_novos_30d > 0 else 0
    return _area("vendas",
                  sources=["sales_leads", "site_leads", "indicacao_leads",
                            "isabella_opportunities",
                            "isabella_commander_opportunities",
                            "projetos_propostas", "smart_installs",
                            "subscribers"],
                  queries=[
                      f"leads (sales={n_sales}, site={n_site}, indic={n_ind})",
                      f"opportunities (isabella={n_opp}, commander={n_cmd_opp})",
                      f"propostas={n_props}, instalações_registradas={n_installs}",
                      f"novos_30d={n_novos_30d}, ativos_totais={n_ativos}",
                  ],
                  doc_count=total, last_ts=last, score=score,
                  reason="funil 5-etapas: leads/opp/proposta/install/ativo")


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
