"""
ops_v51.py — Constituição V5.1 — EXECUÇÃO OPERACIONAL E MONETIZAÇÃO

Reúne:
  - Fase 1: go_live_checklist (WA audit + status bloqueadores +
    plano automático destravar)
  - Fase 4: technician_score (SLA / Tempo médio / Reabertura / Retorno /
    NPS / Geolocalização / Fotos / Qualidade)
  - Fase 5: KPIs Operacionais (First Time Fix Rate, Return Rate,
    Installation Quality, Asset Recovery, Preventive Success,
    Truck Roll Avoidance)
  - Fase 6: Rankings consolidados (técnico / equipe / CTO / bairro /
    região / VLAN)
  - Fase 7: command_center_summary (1 chamada → 10 cards do CC)
  - Fase 8: Smart Field Ops models (schemas Mongo apenas — sem rotas)
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

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from collections import defaultdict
from database import db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# ═══════════════════════════════════════════════════════════
# FASE 1 — GO LIVE CHECKLIST (auditoria automática)
# ═══════════════════════════════════════════════════════════
async def go_live_checklist(company_id: str = "co-demo") -> Dict[str, Any]:
    """Diagnóstico automático WA + plano para destravar receita real."""
    checks: List[Dict[str, Any]] = []

    wa_token = os.environ.get("WA_SIDECAR_TOKEN") or ""
    baileys_url = os.environ.get("BAILEYS_SIDECAR_URL") or ""
    wa_sidecar_url = os.environ.get("WA_SIDECAR_URL") or ""
    gestor_phone = os.environ.get("PRESIDENTE_IA_GESTOR_PHONE") or ""
    checks.append({"id": "wa_token", "name": "WA_SIDECAR_TOKEN",
                   "ok": bool(wa_token), "value_len": len(wa_token),
                   "action": ("Preencher token no .env"
                              if not wa_token else "OK")})
    checks.append({"id": "baileys_url", "name": "BAILEYS_SIDECAR_URL",
                   "ok": bool(baileys_url),
                   "action": ("Configurar URL do sidecar Baileys"
                              if not baileys_url else "OK")})
    checks.append({"id": "wa_sidecar_url", "name": "WA_SIDECAR_URL",
                   "ok": bool(wa_sidecar_url),
                   "action": ("Configurar URL"
                              if not wa_sidecar_url else "OK")})
    checks.append({"id": "gestor_phone",
                   "name": "PRESIDENTE_IA_GESTOR_PHONE",
                   "ok": bool(gestor_phone),
                   "action": ("Definir número do gestor"
                              if not gestor_phone else "OK")})

    # Sessão Baileys ativa?
    sess = await db.wa_baileys_sessions.find_one(
        {}, sort=[("updated_at", -1)])
    sess_state = (sess or {}).get("state") or "NONE"
    checks.append({"id": "baileys_session",
                   "name": "Sessão Baileys ativa",
                   "ok": sess_state.upper() in ("OPEN", "READY"),
                   "value": sess_state,
                   "action": ("Escanear QR code no sidecar"
                              if sess_state.upper() not in
                              ("OPEN", "READY") else "OK")})

    # Ações represadas
    blocked = await db.motor_ia_actions.count_documents(
        {"status": "blocked_transport"})
    queued = await db.motor_ia_actions.count_documents(
        {"status": "queued_no_credentials"})
    checks.append({"id": "blocked_actions",
                   "name": "Ações represadas (blocked_transport)",
                   "ok": blocked == 0, "value": blocked,
                   "action": (f"Destravar com QR scan + "
                              f"{4-sum(1 for c in checks[:4] if c['ok'])} "
                              f"env vars" if blocked > 0 else "OK")})

    # Receita real recebida pela IA
    rev = await db.motor_ia_outcomes.aggregate([
        {"$match": {"actual_BRL": {"$gt": 0}}},
        {"$group": {"_id": None, "n": {"$sum": 1},
                    "total": {"$sum": "$actual_BRL"}}}
    ]).to_list(1)
    real_revenue = (rev[0]["total"] if rev else 0.0)
    real_count = (rev[0]["n"] if rev else 0)
    checks.append({"id": "real_revenue",
                   "name": "Receita real recebida pela IA",
                   "ok": real_revenue > 0,
                   "value": f"R$ {real_revenue:,.2f} ({real_count} outcomes)",
                   "action": ("APROVADO" if real_revenue > 0
                              else "Disparar 1 ciclo end-to-end real")})

    failed = sum(1 for c in checks if not c["ok"])
    return {
        "company_id": company_id,
        "ready_to_go_live": failed == 0,
        "blockers_count": failed,
        "checks": checks,
        "real_revenue_BRL": round(real_revenue, 2),
        "blocked_actions_count": blocked + queued,
        "next_action": (
            "Preencher .env + escanear QR + restart backend"
            if failed > 0 else
            "APROVADO — sistema pronto para receita real"),
        "generated_at": _now_iso(),
    }


# ═══════════════════════════════════════════════════════════
# FASE 4 — TECHNICIAN SCORE
# ═══════════════════════════════════════════════════════════
TECH_WEIGHTS = {
    "sla_compliance": 25,
    "avg_resolution_time": 15,
    "reopen_rate": 20,
    "return_rate": 15,
    "rating": 15,
    "photos": 5,
    "geo": 5,
}


def _classify_tech(score: float) -> str:
    if score >= 90:
        return "ELITE"
    if score >= 75:
        return "EXCELENTE"
    if score >= 60:
        return "BOM"
    if score >= 40:
        return "ATENCAO"
    return "CRITICO"


async def technician_score(company_id: str, tech_id: str,
                           window_days: int = 30) -> Dict[str, Any]:
    """Score 0-100 para 1 técnico. Reaproveita `tickets.assigned_to`
    + extrações de subject/notes para FOTOS, e tabela `os_ratings` se
    existir."""
    cutoff = _cutoff(window_days)
    base_q = {"company_id": company_id, "assigned_to": tech_id,
              "opened_at": {"$gte": cutoff}}
    total = await db.tickets.count_documents(base_q)
    if total == 0:
        return {"tech_id": tech_id, "company_id": company_id,
                "score": 0, "classification": "CRITICO",
                "total_tickets": 0, "window_days": window_days,
                "breakdown": {}, "computed_at": _now_iso()}
    closed = await db.tickets.count_documents({
        **base_q, "status": {"$in":
                             ["closed", "finalizada",
                              "encerrada", "completed"]}})
    sla_compliance = (closed / total) * 100

    # Reaberturas
    reopened = await db.tickets.count_documents({
        **base_q, "reopened": True})
    reopen_rate = (reopened / total) if total else 0

    # Returns (mesmo client_id mais de 1 ticket em 14d)
    client_pipe = [
        {"$match": base_q},
        {"$group": {"_id": "$client_id", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gte": 2}}},
    ]
    returns = 0
    async for r in db.tickets.aggregate(client_pipe):
        returns += r["n"] - 1
    return_rate = (returns / total) if total else 0

    # Avg resolution time (em horas, dos closed)
    closed_docs = await db.tickets.find(
        {**base_q, "status": {"$in":
                              ["closed", "finalizada",
                               "encerrada", "completed"]}},
        {"opened_at": 1, "closed_at": 1}
    ).limit(500).to_list(500)
    durations = []
    for d in closed_docs:
        try:
            o = datetime.fromisoformat(d["opened_at"])
            cl = datetime.fromisoformat(d.get("closed_at") or "")
            durations.append((cl - o).total_seconds() / 3600.0)
        except Exception:
            continue
    avg_h = sum(durations) / len(durations) if durations else 999
    # SLA goal: 24h → 100 pts; >72h → 0 pts
    time_pts = max(0, min(100 - (avg_h - 24) * (100 / 48), 100))

    # Rating (NPS proxy via collection os_ratings se existir)
    rating_avg = 0.0
    rating_n = 0
    if "os_ratings" in await db.list_collection_names():
        agg = await db.os_ratings.aggregate([
            {"$match": {"company_id": company_id, "tech_id": tech_id,
                        "created_at": {"$gte": cutoff}}},
            {"$group": {"_id": None, "avg": {"$avg": "$rating"},
                        "n": {"$sum": 1}}}
        ]).to_list(1)
        if agg:
            rating_avg = float(agg[0].get("avg") or 0)
            rating_n = int(agg[0].get("n") or 0)
    rating_pts = (rating_avg / 5.0) * 100 if rating_avg else 50

    # Fotos: tickets com `photos_count` > 0
    with_photos = await db.tickets.count_documents({
        **base_q, "photos_count": {"$gt": 0}})
    photos_rate = (with_photos / total) if total else 0

    # Geo: tickets com geo_check_in
    with_geo = await db.tickets.count_documents({
        **base_q, "geo_check_in": {"$exists": True}})
    geo_rate = (with_geo / total) if total else 0

    breakdown = {
        "sla_compliance_pct": round(sla_compliance, 1),
        "sla_pts": round(sla_compliance / 100 * TECH_WEIGHTS["sla_compliance"], 2),
        "avg_hours": round(avg_h, 1),
        "time_pts": round(time_pts / 100 * TECH_WEIGHTS["avg_resolution_time"], 2),
        "reopen_rate": round(reopen_rate, 3),
        "reopen_pts": round((1 - reopen_rate) * TECH_WEIGHTS["reopen_rate"], 2),
        "return_rate": round(return_rate, 3),
        "return_pts": round((1 - return_rate) * TECH_WEIGHTS["return_rate"], 2),
        "rating_avg": round(rating_avg, 2),
        "rating_n": rating_n,
        "rating_pts": round(rating_pts / 100 * TECH_WEIGHTS["rating"], 2),
        "photos_rate": round(photos_rate, 3),
        "photos_pts": round(photos_rate * TECH_WEIGHTS["photos"], 2),
        "geo_rate": round(geo_rate, 3),
        "geo_pts": round(geo_rate * TECH_WEIGHTS["geo"], 2),
    }
    score = round(min(sum(v for k, v in breakdown.items()
                          if k.endswith("_pts")), 100), 1)
    cls = _classify_tech(score)
    return {
        "tech_id": tech_id, "company_id": company_id,
        "window_days": window_days, "total_tickets": total,
        "closed_tickets": closed,
        "score": score, "classification": cls,
        "breakdown": breakdown, "computed_at": _now_iso(),
    }


async def technician_ranking(company_id: str,
                             window_days: int = 30,
                             limit: int = 50) -> List[Dict[str, Any]]:
    """Ranking de TODOS técnicos com tickets no período."""
    pipe = [
        {"$match": {"company_id": company_id,
                    "assigned_to": {"$nin": [None, ""]},
                    "opened_at": {"$gte": _cutoff(window_days)}}},
        {"$group": {"_id": "$assigned_to", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": limit},
    ]
    techs = await db.tickets.aggregate(pipe).to_list(limit)
    out = []
    for t in techs:
        s = await technician_score(company_id, t["_id"],
                                   window_days=window_days)
        out.append(s)
    out.sort(key=lambda x: -x["score"])
    return out


# ═══════════════════════════════════════════════════════════
# FASE 5 — KPIs OPERACIONAIS AVANÇADOS
# ═══════════════════════════════════════════════════════════
async def ops_kpis(company_id: str,
                   window_days: int = 30) -> Dict[str, Any]:
    cutoff = _cutoff(window_days)
    base = {"company_id": company_id,
            "opened_at": {"$gte": cutoff}}

    total = await db.tickets.count_documents(base)
    closed = await db.tickets.count_documents({
        **base, "status": {"$in":
                           ["closed", "finalizada",
                            "encerrada", "completed"]}})
    # First Time Fix: ticket fechado sem reabertura
    ftf = await db.tickets.count_documents({
        **base, "reopened": {"$ne": True},
        "status": {"$in": ["closed", "finalizada",
                           "encerrada", "completed"]}})
    ftf_rate = (ftf / max(closed, 1)) * 100

    # Return Rate: mesmo cliente >1 ticket em 14d
    return_pipe = [
        {"$match": base},
        {"$group": {"_id": "$client_id", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gte": 2}}},
    ]
    return_clients = 0
    async for r in db.tickets.aggregate(return_pipe):
        return_clients += 1
    return_rate = (return_clients / max(total, 1)) * 100

    # Installation Quality Score (via tickets de instalação)
    inst_total = await db.tickets.count_documents({
        **base, "category": {"$in": ["instalação", "instalacao",
                                     "install"]}})
    inst_clean = await db.tickets.count_documents({
        **base, "category": {"$in": ["instalação", "instalacao",
                                     "install"]},
        "reopened": {"$ne": True},
        "status": {"$in": ["closed", "finalizada",
                           "encerrada", "completed"]}})
    inst_quality = (inst_clean / max(inst_total, 1)) * 100

    # Asset Recovery (tickets de retirada com material recuperado)
    asset_total = await db.tickets.count_documents({
        **base, "category": {"$in": ["retirada", "withdraw"]}})
    asset_rec = await db.tickets.count_documents({
        **base, "category": {"$in": ["retirada", "withdraw"]},
        "asset_recovered": True})
    asset_score = (asset_rec / max(asset_total, 1)) * 100

    # Preventive Success Rate
    prev_total = await db.tickets.count_documents({
        **base, "origin": "autonomous_engine"})
    prev_closed = await db.tickets.count_documents({
        **base, "origin": "autonomous_engine",
        "status": {"$in": ["closed", "finalizada",
                           "encerrada", "completed"]}})
    prev_success = (prev_closed / max(prev_total, 1)) * 100

    # Truck Roll Avoidance — % de chamados resolvidos remotamente
    remote_resolved = await db.tickets.count_documents({
        **base, "resolution_kind": "remote"})
    truck_avoid = (remote_resolved / max(total, 1)) * 100

    return {
        "company_id": company_id, "window_days": window_days,
        "total_tickets": total, "closed_tickets": closed,
        "first_time_fix_rate_pct": round(ftf_rate, 1),
        "return_rate_pct": round(return_rate, 1),
        "installation_quality_score_pct": round(inst_quality, 1),
        "installation_total": inst_total,
        "asset_recovery_score_pct": round(asset_score, 1),
        "asset_recovery_total": asset_total,
        "preventive_success_rate_pct": round(prev_success, 1),
        "preventive_total": prev_total,
        "truck_roll_avoidance_pct": round(truck_avoid, 1),
        "generated_at": _now_iso(),
    }


# ═══════════════════════════════════════════════════════════
# FASE 6 — RANKING OPERACIONAL CONSOLIDADO
# ═══════════════════════════════════════════════════════════
async def cto_ranking(company_id: str,
                      window_days: int = 30) -> List[Dict[str, Any]]:
    """CTOs ordenadas por nº de tickets (proxy para manutenção)."""
    pipe = [
        {"$match": {"company_id": company_id,
                    "smartolt_onu_zone": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$smartolt_onu_zone",
                    "subs": {"$sum": 1}}},
        {"$sort": {"subs": -1}}, {"$limit": 30},
    ]
    rows = await db.subscribers.aggregate(pipe).to_list(30)
    out = []
    for r in rows:
        zone = r["_id"]
        sids = await db.subscribers.distinct(
            "id", {"company_id": company_id,
                   "smartolt_onu_zone": zone})
        tk = await db.tickets.count_documents({
            "company_id": company_id, "client_id": {"$in": sids},
            "opened_at": {"$gte": _cutoff(window_days)}})
        out.append({"cto": zone, "subscribers": r["subs"],
                    "tickets": tk,
                    "tickets_per_sub": round(tk / max(r["subs"], 1), 3)})
    out.sort(key=lambda x: -x["tickets_per_sub"])
    return out


async def region_ranking(company_id: str,
                         window_days: int = 30) -> List[Dict[str, Any]]:
    """Bairros/regiões via campo subscribers.neighborhood ou city."""
    field_candidates = ["neighborhood", "bairro", "city", "cidade"]
    field = None
    for f in field_candidates:
        c = await db.subscribers.count_documents(
            {"company_id": company_id, f: {"$nin": [None, ""]}})
        if c > 0:
            field = f
            break
    if not field:
        return []
    pipe = [
        {"$match": {"company_id": company_id,
                    field: {"$nin": [None, ""]}}},
        {"$group": {"_id": f"${field}", "subs": {"$sum": 1},
                    "mrr": {"$sum": "$plan_price"}}},
        {"$sort": {"subs": -1}}, {"$limit": 30},
    ]
    rows = await db.subscribers.aggregate(pipe).to_list(30)
    out = []
    for r in rows:
        region = r["_id"]
        sids = await db.subscribers.distinct(
            "id", {"company_id": company_id, field: region})
        tk = await db.tickets.count_documents({
            "company_id": company_id, "client_id": {"$in": sids},
            "opened_at": {"$gte": _cutoff(window_days)}})
        out.append({"region": region, "field": field,
                    "subscribers": r["subs"],
                    "monthly_mrr_BRL": round(r.get("mrr", 0) or 0, 2),
                    "tickets": tk,
                    "tickets_per_sub": round(
                        tk / max(r["subs"], 1), 3)})
    return out


async def vlan_ranking(company_id: str) -> List[Dict[str, Any]]:
    pipe = [
        {"$match": {"company_id": company_id,
                    "current_vlan": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$current_vlan", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 30},
    ]
    out = []
    async for r in db.subscribers.aggregate(pipe):
        n = r["n"]
        out.append({"vlan": r["_id"], "count": n,
                    "utilization_pct": min(round(n / 500 * 100, 1), 100),
                    "level": ("SATURADA" if n >= 500
                              else "ATENCAO" if n >= 350
                              else "SAUDAVEL")})
    return out


# ═══════════════════════════════════════════════════════════
# FASE 7 — ALVARO COMMAND CENTER SUMMARY
# ═══════════════════════════════════════════════════════════
async def command_center_summary(
    company_id: str, window_days: int = 30
) -> Dict[str, Any]:
    """1 chamada → 10 cards no padrão Problema/Causa/Impacto/Ação/
    Confiança/Evidência."""
    from services import failure_risk as fr

    # Card 1: Clientes em risco (do failure_risk_score)
    crit = await db.motor_ia_failure_risk_scores.find(
        {"company_id": company_id, "score": {"$gte": 81}}
    ).sort("score", -1).limit(50).to_list(50)
    total_rev_risk = sum(
        c.get("expected_revenue_at_risk_BRL", 0) for c in crit)
    card_clients = {
        "title": "Clientes em Risco",
        "problem": f"{len(crit)} cliente(s) em estado CRITICO",
        "cause": "failure_risk_score > 80 — ONU/sinal/tickets/churn",
        "impact": f"R$ {total_rev_risk:,.2f}/mês em receita em risco",
        "action": "Disparar drive_from_failure_risk → OS preventivas",
        "confidence": 0.90 if crit else 0.50,
        "evidence": [
            {"type": "critical_count", "value": len(crit),
             "source": "motor_ia_failure_risk_scores"},
            {"type": "revenue_at_risk", "value": total_rev_risk,
             "source": "expected_revenue_at_risk_BRL"},
        ],
        "items": [{"sid": c["subscriber_id"], "score": c["score"],
                   "revenue": c["expected_revenue_at_risk_BRL"]}
                  for c in crit[:10]],
    }

    # Card 2: CTOs críticas
    ctos = await cto_ranking(company_id, window_days)
    crit_ctos = [c for c in ctos if c["tickets_per_sub"] >= 0.5][:10]
    card_ctos = {
        "title": "CTOs Críticas",
        "problem": f"{len(crit_ctos)} CTO(s) com tickets/sub ≥ 0.5",
        "cause": "Concentração de tickets em zonas específicas",
        "impact": "Custo operacional + churn regional",
        "action": "Visita técnica preventiva por CTO",
        "confidence": 0.85,
        "evidence": [{"type": "critical_ctos", "value": len(crit_ctos),
                      "source": "tickets+subscribers.smartolt_onu_zone"}],
        "items": crit_ctos,
    }

    # Card 3: PONs críticas (via smartolt_twin se disponível)
    pons: List[Dict[str, Any]] = []
    try:
        from services.smartolt_twin import pon_health
        pons = await pon_health(company_id)
        pons = [p for p in pons if p.get("score", 100) < 70][:10]
    except ModuleNotFoundError:
        pons = []
    except Exception:
        pons = []
    card_pons = {
        "title": "PONs Críticas",
        "problem": f"{len(pons)} PON(s) com score < 70",
        "cause": "Degradação na porta da OLT",
        "impact": "Múltiplos clientes afetados simultaneamente",
        "action": "Inspeção física da porta + reset OLT",
        "confidence": 0.80, "evidence": pons[:3], "items": pons,
    }

    # Card 4: VLANs críticas
    vlans = await vlan_ranking(company_id)
    sat_vlans = [v for v in vlans if v["level"] == "SATURADA"]
    card_vlans = {
        "title": "VLANs Críticas",
        "problem": f"{len(sat_vlans)} VLAN(s) saturada(s)",
        "cause": "Utilização >= 500 subs por VLAN",
        "impact": "Risco de degradação de performance",
        "action": "Migrar subs para nova VLAN",
        "confidence": 0.75,
        "evidence": [{"type": "saturated_count", "value": len(sat_vlans),
                      "source": "subscribers.current_vlan"}],
        "items": sat_vlans,
    }

    # Card 5: Técnicos
    techs = await technician_ranking(company_id, window_days, limit=10)
    crit_techs = [t for t in techs if t["classification"] in (
        "ATENCAO", "CRITICO")]
    card_techs = {
        "title": "Técnicos",
        "problem": (f"{len(crit_techs)} técnico(s) abaixo da média "
                    f"(BOM ou melhor)"),
        "cause": "SLA/reabertura/retorno acima do esperado",
        "impact": "Retrabalho + insatisfação do cliente",
        "action": "Coaching + reatribuição de carga",
        "confidence": 0.85,
        "evidence": [{"type": "total_techs", "value": len(techs),
                      "source": "tickets.assigned_to"}],
        "items": techs,
    }

    # Card 6: SLA
    kpis = await ops_kpis(company_id, window_days)
    card_sla = {
        "title": "SLA Operacional",
        "problem": (f"First Time Fix: "
                    f"{kpis['first_time_fix_rate_pct']:.1f}% · "
                    f"Return Rate: {kpis['return_rate_pct']:.1f}%"),
        "cause": "Combinação de fechamento + recorrência",
        "impact": ("Cada 1% a mais de FTF poupa visitas adicionais"),
        "action": "Coaching técnicos com pior FTF + diagnóstico remoto",
        "confidence": 0.88,
        "evidence": [{"type": "ftf",
                      "value": kpis["first_time_fix_rate_pct"],
                      "source": "tickets"},
                     {"type": "return_rate",
                      "value": kpis["return_rate_pct"],
                      "source": "tickets"}],
        "items": [kpis],
    }

    # Card 7: OS Preventivas (Fase H metrics)
    fh = await fr.phase_h_metrics(company_id, window_days)
    card_prev = {
        "title": "OS Preventivas",
        "problem": (f"{fh['preventive_count']} preventivas vs "
                    f"{fh['corrective_count']} corretivas"),
        "cause": "Motor failure_risk disparou ciclo automático",
        "impact": f"R$ {fh['prevented_churn_BRL']:,.2f} de churn evitado",
        "action": ("Manter scheduler ativo · ajustar threshold se "
                   ">70% críticos"),
        "confidence": 0.92,
        "evidence": [{"type": "preventive_ratio",
                      "value": fh["preventive_ratio"],
                      "source": "motor_ia_autonomous_cycles"}],
        "items": [fh],
    }

    # Card 8: Predições (distribuição failure_risk)
    dist = await fr.distribution(company_id)
    card_pred = {
        "title": "Predições",
        "problem": ("Distribuição de failure_risk em "
                    f"{dist['total']} clientes"),
        "cause": "Modelo composto de 7 sinais",
        "impact": dist["note"],
        "action": (dist["note"] if not dist["is_calibrated"]
                   else "Modelo calibrado — continuar operando"),
        "confidence": 0.90 if dist["is_calibrated"] else 0.55,
        "evidence": [{"type": "is_calibrated",
                      "value": dist["is_calibrated"],
                      "source": "motor_ia_failure_risk_scores"}],
        "items": dist["buckets"],
    }

    # Card 9: Patrimônio (Asset Recovery)
    card_asset = {
        "title": "Patrimônio (Asset Recovery)",
        "problem": (f"Asset Recovery: "
                    f"{kpis['asset_recovery_score_pct']:.1f}% em "
                    f"{kpis['asset_recovery_total']} retiradas"),
        "cause": "Retiradas sem registro de equipamento recuperado",
        "impact": "Perda de patrimônio + custo de reposição",
        "action": "Forçar campo asset_recovered=True nas OS de retirada",
        "confidence": 0.80,
        "evidence": [{"type": "asset_recovery_pct",
                      "value": kpis["asset_recovery_score_pct"],
                      "source": "tickets.category=retirada"}],
        "items": [kpis],
    }

    # Card 10: IA Explicável (Go Live status)
    gl = await go_live_checklist(company_id)
    card_xai = {
        "title": "IA Explicável (Go Live)",
        "problem": (f"{gl['blockers_count']} bloqueador(es) para "
                    f"receita real"),
        "cause": "Credenciais WA / sessão Baileys não configuradas",
        "impact": f"Receita real atual: R$ {gl['real_revenue_BRL']:,.2f}",
        "action": gl["next_action"],
        "confidence": 0.99,
        "evidence": [{"type": c["name"], "value": c.get("ok"),
                      "source": "env/db"} for c in gl["checks"]],
        "items": gl["checks"],
    }

    return {
        "company_id": company_id, "window_days": window_days,
        "cards": [card_clients, card_ctos, card_pons, card_vlans,
                  card_techs, card_sla, card_prev, card_pred,
                  card_asset, card_xai],
        "generated_at": _now_iso(),
    }


# ═══════════════════════════════════════════════════════════
# FASE 8 — SMART FIELD OPS (apenas modelos de dados — sem rotas)
# ═══════════════════════════════════════════════════════════
SMART_FIELD_OPS_SCHEMAS = {
    "smart_installs": {
        "id": "str (sfi-XXXX)", "company_id": "str", "client_id": "str",
        "tech_id": "str", "scheduled_at": "iso", "started_at": "iso",
        "finished_at": "iso",
        "checklist_completed": "bool",
        "photos_count": "int", "geo_check_in": "{lat,lng}",
        "installation_quality_score": "float 0-100",
        "first_time_complete": "bool",
        "ont_sn": "str", "ont_mac": "str",
        "signal_after_install_dbm": "float",
        "created_at": "iso", "updated_at": "iso",
    },
    "smart_repairs": {
        "id": "str (sfr-XXXX)", "company_id": "str", "client_id": "str",
        "tech_id": "str", "ticket_id": "str",
        "remote_attempt_first": "bool",
        "remote_resolved": "bool", "truck_roll_avoided": "bool",
        "root_cause": "str", "fix_applied": "str",
        "reopened_within_7d": "bool", "created_at": "iso",
    },
    "smart_withdrawals": {
        "id": "str (sfw-XXXX)", "company_id": "str", "client_id": "str",
        "tech_id": "str",
        "asset_recovered": "bool", "asset_condition": "str",
        "photos_count": "int", "signed_receipt": "bool",
        "ont_sn": "str", "ont_mac": "str",
        "asset_recovery_score": "float 0-100",
        "created_at": "iso",
    },
}


async def smart_field_ops_status(
    company_id: str,
) -> Dict[str, Any]:
    """Sinaliza se schemas estão prontos. NÃO implementa workflow."""
    cols_existing = await db.list_collection_names()
    return {
        "company_id": company_id,
        "ready": True,
        "schemas_defined": list(SMART_FIELD_OPS_SCHEMAS.keys()),
        "collections_present": {
            k: (k in cols_existing) for k in
            SMART_FIELD_OPS_SCHEMAS.keys()
        },
        "note": ("Modelos de dados definidos. Implementação completa "
                 "ficará para Sprint Smart Field Ops."),
        "schemas": SMART_FIELD_OPS_SCHEMAS,
    }
