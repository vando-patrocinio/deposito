"""
presidente_ia.py — Sistema Nervoso Corporativo do SmartProv (iter218)

Núcleo do "Presidente IA V2.0". Substitui o conceito anterior de
"Conselho IA Hub" por uma inteligência central que:
  OBSERVA → ENTENDE → CORRELACIONA → PREVÊ → DECIDE → AGE → APRENDE

Esta camada NÃO chama LLM diretamente — só agrega dados e mantém a
memória corporativa. Os pareceres especializados (CEO/COO/CTO/CFO/CPO
+ Estrategista) ficam em `presidente_ia_conselho.py`.

Collections:
  motor_ia_events        Stream de eventos (insert-only)
  motor_ia_memory        Memória de longo prazo (insights consolidados)
  motor_ia_insights      Insights gerados na varredura
  motor_ia_predictions   Predições com score 0-100
  motor_ia_decisions     Decisões tomadas (com contexto)
  motor_ia_actions       Ações executadas (rastreabilidade)
  motor_ia_learnings     Aprendizados (feedback loop)
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
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


# ─────────────────── Catálogo de Agentes (orbital) ───────────────────
AGENT_ORBIT: List[Dict[str, str]] = [
    {"id": "alvaro",      "label": "Álvaro IA",
     "group": "Insights",       "color": "#7c3aed"},
    {"id": "isabella",    "label": "Isabella IA",
     "group": "Atendimento",    "color": "#0891b2"},
    {"id": "sentinela",   "label": "Sentinela IA",
     "group": "Risco",          "color": "#b42318"},
    {"id": "coach",       "label": "Coach IA",
     "group": "Qualidade",      "color": "#237a4b"},
    {"id": "avaliador",   "label": "Avaliador IA",
     "group": "Qualidade",      "color": "#237a4b"},
    {"id": "copilot",     "label": "CoPilot IA",
     "group": "Suporte",        "color": "#0891b2"},
    {"id": "secretaria",  "label": "Secretaria IA",
     "group": "Executivo",      "color": "#4b1d7a"},
    {"id": "rede",        "label": "Rede IA",
     "group": "Infra",          "color": "#1e40af"},
    {"id": "smartolt",    "label": "SmartOLT IA",
     "group": "Infra",          "color": "#1e40af"},
    {"id": "financeiro",  "label": "Financeiro IA",
     "group": "Financeiro",     "color": "#237a4b"},
    {"id": "parceiros",   "label": "Parceiros IA",
     "group": "Receita",        "color": "#f28c28"},
    {"id": "clube_ligo",  "label": "Clube Ligo IA",
     "group": "Engajamento",    "color": "#f28c28"},
    {"id": "gps",         "label": "GPS IA",
     "group": "Frota",          "color": "#f28c28"},
    {"id": "seguranca",   "label": "Segurança IA",
     "group": "Segurança",      "color": "#b42318"},
]


# ─────────────────── Helpers ───────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _cutoff_iso(days: int) -> str:
    return (_now() - timedelta(days=days)).isoformat()


# ─────────────────── Memória — Recorders ───────────────────
async def record_event(cid: str, event_type: str, source: str,
                          severity: str = "info",
                          data: Optional[Dict[str, Any]] = None,
                          subscriber_id: Optional[str] = None,
                          ) -> str:
    """Registra um evento corporativo. Severity: info|warn|alert|critical."""
    eid = f"ev-{uuid.uuid4().hex[:14]}"
    await db.motor_ia_events.insert_one({
        "id": eid, "company_id": cid,
        "event_type": event_type, "source": source,
        "severity": severity, "data": data or {},
        "subscriber_id": subscriber_id,
        "created_at": _now_iso(),
    })
    return eid


async def record_prediction(cid: str, subject_type: str,
                                subject_id: str, kind: str,
                                score: float,
                                rationale: str = "",
                                horizon_days: int = 30) -> str:
    """Registra uma predição (churn, inadimplência, saturação, etc).
    score: 0-100. subject_type: 'subscriber'|'cto'|'vlan'|'olt'..."""
    pid = f"pred-{uuid.uuid4().hex[:14]}"
    await db.motor_ia_predictions.insert_one({
        "id": pid, "company_id": cid,
        "subject_type": subject_type, "subject_id": subject_id,
        "kind": kind, "score": round(float(score), 1),
        "rationale": rationale, "horizon_days": horizon_days,
        "created_at": _now_iso(),
    })
    return pid


async def record_insight(cid: str, title: str, severity: str,
                            category: str, summary: str,
                            evidence: Optional[Dict[str, Any]] = None,
                            recommended_action: str = "") -> str:
    """Registra um insight gerado pelo Presidente."""
    iid = f"ins-{uuid.uuid4().hex[:14]}"
    await db.motor_ia_insights.insert_one({
        "id": iid, "company_id": cid,
        "title": title, "severity": severity, "category": category,
        "summary": summary, "evidence": evidence or {},
        "recommended_action": recommended_action,
        "status": "open",
        "created_at": _now_iso(),
    })
    return iid


async def record_decision(cid: str, decision: str, rationale: str,
                              taken_by: str = "presidente_ia",
                              insight_id: Optional[str] = None) -> str:
    did = f"dec-{uuid.uuid4().hex[:14]}"
    await db.motor_ia_decisions.insert_one({
        "id": did, "company_id": cid,
        "decision": decision, "rationale": rationale,
        "taken_by": taken_by, "insight_id": insight_id,
        "created_at": _now_iso(),
    })
    return did


async def record_action(cid: str, action_type: str, target: str,
                            status: str, decision_id: Optional[str] = None,
                            result: Optional[Dict[str, Any]] = None) -> str:
    aid = f"act-{uuid.uuid4().hex[:14]}"
    await db.motor_ia_actions.insert_one({
        "id": aid, "company_id": cid,
        "action_type": action_type, "target": target,
        "status": status, "decision_id": decision_id,
        "result": result or {},
        "created_at": _now_iso(),
    })
    return aid


async def record_learning(cid: str, lesson: str, category: str,
                              evidence: Optional[Dict[str, Any]] = None,
                              ) -> str:
    lid = f"lrn-{uuid.uuid4().hex[:14]}"
    await db.motor_ia_learnings.insert_one({
        "id": lid, "company_id": cid,
        "lesson": lesson, "category": category,
        "evidence": evidence or {},
        "created_at": _now_iso(),
    })
    return lid


# ─────────────────── Helpers de queries seguras ───────────────────
async def _safe_count(col: str, q: Dict[str, Any]) -> int:
    try:
        return await db[col].count_documents(q)
    except Exception:
        return 0


async def _safe_one(col: str, q: Dict[str, Any]):
    try:
        return await db[col].find_one(q, {"_id": 0})
    except Exception:
        return None


def _base_q(cid: str) -> Dict[str, Any]:
    return {"company_id": cid} if cid else {}


# ─────────────────── Health Score ───────────────────
async def compute_corporate_health(cid: str) -> Dict[str, Any]:
    """Score 0-100 da saúde corporativa. Penalidades:
        churn, inadimplência, tickets abertos, ONUs offline, CTOs
        saturadas, automações inativas."""
    bq = _base_q(cid)
    total = await _safe_count("subscribers", bq)
    ativos = await _safe_count("subscribers",
        {**bq, "status": {"$in": ["ATIVO", "ATIVA"]}})
    cancel_30d = await _safe_count("subscribers", {
        **bq, "status": {"$regex": "CANCEL", "$options": "i"},
        "updated_at": {"$gte": _cutoff_iso(30)}})
    inad = await _safe_count("subscribers", {
        **bq, "financial_status":
            {"$regex": "inadimp|atrasad", "$options": "i"}})
    tickets_open = await _safe_count("tickets",
        {**bq, "status": {"$nin": ["closed", "resolved",
                                          "FECHADO", "RESOLVIDO"]}})
    onu_offline = await _safe_count("subscribers", {
        **bq, "status": {"$in": ["ATIVO", "ATIVA"]},
        "signal_dbm": {"$lte": -28}})

    churn_pct = round(100 * cancel_30d / max(total, 1), 2)
    inad_pct = round(100 * inad / max(ativos, 1), 2)
    onu_off_pct = round(100 * onu_offline / max(ativos, 1), 2)
    tickets_per_1k = round(1000 * tickets_open / max(ativos, 1), 1)

    # Score base 100, deduz por área
    score = 100.0
    # Churn: cada 1% deduz 4 pts (até -20)
    score -= min(churn_pct * 4, 20)
    # Inadimplência: cada 1% deduz 2 pts (até -25)
    score -= min(inad_pct * 2, 25)
    # ONU offline: cada 1% deduz 3 pts (até -15)
    score -= min(onu_off_pct * 3, 15)
    # Tickets por 1k: cada 1 deduz 0.5 pts (até -15)
    score -= min(tickets_per_1k * 0.5, 15)
    score = max(0.0, min(100.0, score))

    if score >= 80:
        status = "saudavel"
    elif score >= 60:
        status = "atencao"
    elif score >= 40:
        status = "alerta"
    else:
        status = "critico"

    return {
        "score": round(score, 1),
        "status": status,
        "components": {
            "total_clientes": total,
            "ativos": ativos,
            "cancelamentos_30d": cancel_30d,
            "inadimplentes": inad,
            "tickets_abertos": tickets_open,
            "onus_offline": onu_offline,
            "churn_pct": churn_pct,
            "inadimplencia_pct": inad_pct,
            "onu_offline_pct": onu_off_pct,
            "tickets_por_1k": tickets_per_1k,
        },
    }


# ─────────────────── Risks ───────────────────
async def compute_risks(cid: str,
                            health: Dict[str, Any]) -> Dict[str, Any]:
    """Gera lista de riscos por nível."""
    c = health.get("components", {})
    riscos: List[Dict[str, Any]] = []
    bq = _base_q(cid)

    def add(level: str, area: str, descricao: str,
              evidencia: Any = None):
        riscos.append({"level": level, "area": area,
                          "descricao": descricao,
                          "evidencia": evidencia})

    if c.get("churn_pct", 0) > 5:
        add("critico", "Retenção",
              f"Churn em {c['churn_pct']}% (>5%)",
              c['cancelamentos_30d'])
    elif c.get("churn_pct", 0) > 3:
        add("alto", "Retenção",
              f"Churn em {c['churn_pct']}% (>3%)",
              c['cancelamentos_30d'])

    if c.get("inadimplencia_pct", 0) > 15:
        add("critico", "Financeiro",
              f"Inadimplência em {c['inadimplencia_pct']}% (>15%)",
              c['inadimplentes'])
    elif c.get("inadimplencia_pct", 0) > 10:
        add("alto", "Financeiro",
              f"Inadimplência em {c['inadimplencia_pct']}% (>10%)",
              c['inadimplentes'])
    elif c.get("inadimplencia_pct", 0) > 5:
        add("medio", "Financeiro",
              f"Inadimplência em {c['inadimplencia_pct']}% (>5%)",
              c['inadimplentes'])

    if c.get("onu_offline_pct", 0) > 5:
        add("critico", "Rede",
              f"{c['onus_offline']} ONUs com sinal crítico",
              c['onu_offline_pct'])
    elif c.get("onu_offline_pct", 0) > 2:
        add("alto", "Rede",
              f"{c['onus_offline']} ONUs com sinal degradado")

    if c.get("tickets_abertos", 0) > 100:
        add("alto", "Operação",
              f"{c['tickets_abertos']} tickets abertos",
              c['tickets_por_1k'])
    elif c.get("tickets_abertos", 0) > 50:
        add("medio", "Operação",
              f"{c['tickets_abertos']} tickets abertos")

    # CTOs saturadas
    saturadas = 0
    try:
        agg = await db.subscribers.aggregate([
            {"$match": {**bq, "cto_id":
                            {"$exists": True, "$ne": None}}},
            {"$group": {"_id": "$cto_id", "qtd": {"$sum": 1}}},
        ]).to_list(2000)
        for r in agg:
            if r.get("qtd", 0) >= 15:
                saturadas += 1
    except Exception:
        pass
    if saturadas > 0:
        add("medio" if saturadas < 5 else "alto", "Capacidade",
              f"{saturadas} CTO(s) próximas da saturação",
              saturadas)

    # Solicitações de desbloqueio pendentes
    unblock = await _safe_count("subscriber_unblock_requests",
        {**bq, "status": {"$in": ["pending", "PENDENTE"]}})
    if unblock > 5:
        add("medio", "Atendimento",
              f"{unblock} solicitações de desbloqueio pendentes",
              unblock)

    return {
        "total": len(riscos),
        "criticos": [r for r in riscos if r["level"] == "critico"],
        "altos":    [r for r in riscos if r["level"] == "alto"],
        "medios":   [r for r in riscos if r["level"] == "medio"],
        "baixos":   [r for r in riscos if r["level"] == "baixo"],
    }


# ─────────────────── Opportunities ───────────────────
async def compute_opportunities(cid: str) -> Dict[str, Any]:
    """Identifica oportunidades de receita / engajamento."""
    bq = _base_q(cid)
    opps: List[Dict[str, Any]] = []
    receita_potencial = 0.0

    # Upsell — clientes com plano antigo de baixo ticket
    try:
        agg = await db.subscribers.aggregate([
            {"$match": {**bq, "status": {"$in": ["ATIVO", "ATIVA"]},
                           "plan_price_brl": {"$gt": 0, "$lt": 80}}},
            {"$count": "n"},
        ]).to_list(1)
        n_upsell = (agg[0] if agg else {}).get("n", 0)
        if n_upsell > 0:
            potencial = n_upsell * 30  # +R$30 média de upgrade
            receita_potencial += potencial
            opps.append({
                "tipo": "upsell", "titulo": "Upsell de plano",
                "descricao":
                    f"{n_upsell} clientes em planos de baixo ticket",
                "qtd": n_upsell,
                "receita_potencial_brl": potencial,
                "agente_recomendado": "isabella",
            })
    except Exception:
        pass

    # Cross-sell SecurityHome
    sec_clients = await _safe_count("security_sites", bq)
    total_active = await _safe_count("subscribers",
        {**bq, "status": {"$in": ["ATIVO", "ATIVA"]}})
    if total_active > 0:
        no_sec = total_active - sec_clients
        if no_sec > 50:
            potencial = no_sec * 0.05 * 49.90  # 5% adoção * 49,90
            receita_potencial += potencial
            opps.append({
                "tipo": "crosssell", "titulo": "SecurityHome",
                "descricao":
                    f"{no_sec} clientes ativos sem SecurityHome",
                "qtd": no_sec,
                "receita_potencial_brl": round(potencial, 2),
                "agente_recomendado": "isabella",
            })

    # Indicações
    leads_aguardando = await _safe_count("indicacao_leads",
        {**bq, "status": {"$in": ["pending", "PENDENTE"]}})
    if leads_aguardando > 0:
        opps.append({
            "tipo": "indicacao", "titulo": "Leads de indicação",
            "descricao":
                f"{leads_aguardando} leads parados na esteira",
            "qtd": leads_aguardando,
            "receita_potencial_brl": leads_aguardando * 99.90,
            "agente_recomendado": "secretaria",
        })
        receita_potencial += leads_aguardando * 99.90

    # Parcerias com promo zerada
    inactive_promos = await _safe_count("parcerias_promotions",
        {**bq, "active": True, "total_redemptions": {"$lte": 0}})
    if inactive_promos > 0:
        opps.append({
            "tipo": "parcerias", "titulo": "Promoções sem engajamento",
            "descricao":
                f"{inactive_promos} promoções ativas com zero resgates",
            "qtd": inactive_promos,
            "receita_potencial_brl": 0,
            "agente_recomendado": "parceiros",
        })

    return {
        "total": len(opps),
        "receita_potencial_brl": round(receita_potencial, 2),
        "items": opps,
    }


# ─────────────────── Clientes em risco ───────────────────
async def compute_clients_at_risk(cid: str,
                                       limit: int = 20) -> List[Dict[str, Any]]:
    """Lista top N clientes em risco de churn — scoring simples."""
    bq = _base_q(cid)
    cur = db.subscribers.find({
        **bq, "status": {"$in": ["ATIVO", "ATIVA"]},
    }, {"_id": 0, "id": 1, "name": 1, "phone": 1, "plan_name": 1,
        "plan_price_brl": 1, "financial_status": 1, "signal_dbm": 1,
        "last_payment_at": 1})
    out: List[Dict[str, Any]] = []
    async for s in cur:
        score = 0
        reasons: List[str] = []
        fin = (s.get("financial_status") or "").lower()
        if "inadimp" in fin or "atrasad" in fin:
            score += 40
            reasons.append("inadimplente")
        sig = s.get("signal_dbm")
        if isinstance(sig, (int, float)) and sig <= -28:
            score += 25
            reasons.append(f"sinal {sig} dBm")
        # ticket alto
        if (s.get("plan_price_brl") or 0) >= 150:
            score += 10
            reasons.append("ticket alto")
        if score >= 30:
            out.append({
                "subscriber_id": s["id"],
                "name": s.get("name"),
                "phone": s.get("phone"),
                "plan": s.get("plan_name"),
                "score": min(score, 100),
                "reasons": reasons,
            })
        if len(out) >= limit * 4:
            break
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:limit]


# ─────────────────── Status seções dashboard ───────────────────
async def get_network_status(cid: str) -> Dict[str, Any]:
    bq = _base_q(cid)
    ctos = await _safe_count("ctos", bq)
    onus_offline = await _safe_count("subscribers",
        {**bq, "status": {"$in": ["ATIVO", "ATIVA"]},
         "signal_dbm": {"$lte": -28}})
    outages = await _safe_count("network_outages", bq)
    olts_count = await _safe_count("smartolt_config", bq)
    # CTOs críticas (>= 15 clientes)
    ctos_critical = 0
    try:
        agg = await db.subscribers.aggregate([
            {"$match": {**bq, "cto_id":
                            {"$exists": True, "$ne": None}}},
            {"$group": {"_id": "$cto_id", "qtd": {"$sum": 1}}},
            {"$match": {"qtd": {"$gte": 15}}},
            {"$count": "n"},
        ]).to_list(1)
        ctos_critical = (agg[0] if agg else {}).get("n", 0)
    except Exception:
        pass
    return {
        "ctos": ctos, "ctos_criticas": ctos_critical,
        "onus_offline": onus_offline,
        "olts": olts_count,
        "outages": outages,
    }


async def get_attendance_status(cid: str) -> Dict[str, Any]:
    bq = _base_q(cid)
    open_t = await _safe_count("tickets",
        {**bq, "status": {"$nin": ["closed", "resolved",
                                          "FECHADO", "RESOLVIDO"]}})
    last_csat = None
    try:
        # melhor estimativa: avg CSAT últimas 30d
        agg = await db.central_ia_evaluations.aggregate([
            {"$match": {**bq, "created_at": {"$gte": _cutoff_iso(30)}}},
            {"$group": {"_id": None,
                           "csat": {"$avg": "$csat"}}},
        ]).to_list(1)
        last_csat = round(float((agg[0] if agg else {})
                                       .get("csat") or 0), 1)
    except Exception:
        pass
    # Tempo médio de resposta WhatsApp (placeholder)
    return {
        "tickets_abertos": open_t,
        "csat_30d": last_csat or 0,
        "tempo_medio_min": None,  # TODO próxima fase
    }


async def get_commercial_status(cid: str) -> Dict[str, Any]:
    bq = _base_q(cid)
    cutoff = _cutoff_iso(30)
    leads = await _safe_count("sales_leads",
        {**bq, "created_at": {"$gte": cutoff}})
    site_leads = await _safe_count("site_leads",
        {**bq, "created_at": {"$gte": cutoff}})
    novos = await _safe_count("subscribers",
        {**bq, "installation_date": {"$gte": cutoff}})
    total_l = leads + site_leads
    conv = round(100 * novos / total_l, 1) if total_l else 0.0
    return {
        "leads_30d": total_l,
        "conversoes_30d": novos,
        "taxa_conversao_pct": conv,
    }


async def get_universo_ligo(cid: str) -> Dict[str, Any]:
    bq = _base_q(cid)
    fibra = await _safe_count("subscribers",
        {**bq, "status": {"$in": ["ATIVO", "ATIVA"]}})
    ligo_casa = await _safe_count("security_sites", bq)
    parceiros = await _safe_count("parcerias_partners",
        {**bq, "active": True})
    promos = await _safe_count("parcerias_promotions",
        {**bq, "active": True})
    redemptions_30d = await _safe_count("parcerias_redemptions",
        {**bq, "created_at": {"$gte": _cutoff_iso(30)}})
    referrals = await _safe_count("referrals", bq)
    return {
        "clientes_fibra": fibra,
        "ligo_de_casa": ligo_casa,
        "parceiros_ativos": parceiros,
        "promocoes_ativas": promos,
        "resgates_30d": redemptions_30d,
        "indicacoes_total": referrals,
    }


# ─────────────────── Predições — Engine ───────────────────
async def run_prediction_engine(cid: str,
                                  limit: int = 50) -> Dict[str, int]:
    """Calcula scores de churn pros top clientes em risco e
    persiste em motor_ia_predictions."""
    risk = await compute_clients_at_risk(cid, limit=limit)
    n = 0
    for r in risk:
        await record_prediction(
            cid, "subscriber", r["subscriber_id"], "churn",
            r["score"], rationale=", ".join(r["reasons"]),
            horizon_days=30)
        n += 1
    return {"predicted": n}


# ─────────────────── Correlação ───────────────────
async def run_correlation_engine(cid: str) -> List[Dict[str, Any]]:
    """Heurística: correlaciona ONU offline + tickets recentes
    por CTO/bairro pra detectar incidentes coletivos."""
    bq = _base_q(cid)
    found: List[Dict[str, Any]] = []
    try:
        # agrupa subscribers ativos com sinal degradado por cto_id
        agg = await db.subscribers.aggregate([
            {"$match": {**bq, "status": {"$in": ["ATIVO", "ATIVA"]},
                           "signal_dbm": {"$lte": -28},
                           "cto_id": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": "$cto_id",
                           "qtd": {"$sum": 1},
                           "neighborhood": {"$first": "$neighborhood"}}},
            {"$match": {"qtd": {"$gte": 3}}},
            {"$sort": {"qtd": -1}}, {"$limit": 10},
        ]).to_list(10)
        for r in agg:
            await record_insight(
                cid,
                title=f"Possível incidente coletivo na CTO {r['_id']}",
                severity="alto", category="rede",
                summary=(f"{r['qtd']} ONUs com sinal degradado na "
                            f"mesma CTO ({r.get('neighborhood') or '—'})"),
                evidence=r,
                recommended_action="Abrir incidente e despachar técnico")
            found.append({"type": "cto_collective", **r})
    except Exception as e:
        logger.warning("[presidente-ia] correlation falhou: %s", e)
    return found


# ─────────────────── Scan proativo ───────────────────
async def proactive_scan(cid: str) -> Dict[str, Any]:
    """Roda todos os motores: health → riscos → predições →
    correlação. Idempotente — pode ser chamado por cron ou
    manualmente."""
    started = _now()
    health = await compute_corporate_health(cid)
    risks = await compute_risks(cid, health)
    opps = await compute_opportunities(cid)
    pred = await run_prediction_engine(cid, limit=30)
    corr = await run_correlation_engine(cid)

    # Loga evento de scan
    await record_event(cid, "presidente_scan",
                          source="presidente_ia",
                          severity="info",
                          data={"health_score": health["score"],
                                  "risks": risks["total"],
                                  "opportunities": opps["total"],
                                  "predictions": pred["predicted"],
                                  "correlations": len(corr)})

    # iter219d — Leo Proativo: notifica gestor por iniciativa própria
    proactive: Dict[str, Any] = {"sent": 0}
    try:
        from services.leo_proactive import try_proactive_notifications
        proactive = await try_proactive_notifications(cid)
    except Exception as e:
        logger.warning("[presidente-ia] leo proactive falhou: %s", e)

    elapsed = int((_now() - started).total_seconds() * 1000)
    return {
        "ok": True, "elapsed_ms": elapsed,
        "health": health, "risks": risks,
        "opportunities": opps,
        "predictions": pred,
        "correlations": corr,
        "leo_proactive": proactive,
    }
