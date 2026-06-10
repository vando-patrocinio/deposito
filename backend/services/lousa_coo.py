"""LOUSA COO — Diretor de Operações Autônomo do SmartProv.

OPERAÇÃO COLOSSO (10/02/2026):

Transforma a Lousa em COO digital. Reutiliza Álvaro · Isabella · Truck Roll
Guard · Sistema Nervoso · SmartOLT · Smart Field Ops · Estoque · `ai_evaluations`
· `executive_ledger`.

Nada de coleções/IAs/dashboards novos. Cada operação termina em side-effect
auditável no banco real.

API pública:
  • daily_directive(company_id)        — plano do dia (prioriza/distribui)
  • enforce_preventive_ratio(...)      — garante 3 preventivas por 12 OS
  • plan_field_day(...)                — sequência ideal de OS por técnico
  • compute_technician_scores(...)     — score 0-100 por técnico
  • operational_council_weekly(...)    — 8 TOP-10 (Conselho Operacional)
  • register_os_learning(ticket_id)    — aprendizado pós-OS em ai_evaluations
  • alvaro_command_loop(company_id)    — Álvaro toma ação ao invés de só
                                          observar (cria OS preventiva,
                                          escala incidente, etc).
"""
from __future__ import annotations

import math
import os
import re
import statistics
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from database import db

# Razão preventiva — Operação Colosso pediu 3:12 (= 1:4)
PREVENTIVE_RATIO_NUM = int(os.environ.get("LOUSA_PREVENTIVE_RATIO_NUM", "3"))
PREVENTIVE_RATIO_DEN = int(os.environ.get("LOUSA_PREVENTIVE_RATIO_DEN", "12"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: Optional[datetime] = None) -> str:
    return (d or _now()).astimezone(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 1) DAILY DIRECTIVE — o COO acorda e organiza o dia
# ---------------------------------------------------------------------------
async def daily_directive(company_id: str) -> Dict[str, Any]:
    """Plano operacional diário. Lê estado real do banco e devolve
    decisões executáveis (priorização, distribuição, alertas).
    """
    today = _now().date().isoformat()
    cutoff_24h = (_now() - timedelta(hours=24)).isoformat()

    # OS abertas
    open_repairs = await db.smart_repairs.count_documents({
        "company_id": company_id,
        "status": {"$in": ["pending", "open", "scheduled", "agendada", "aberta"]}})
    open_installs = await db.smart_installs.count_documents({
        "company_id": company_id,
        "status": {"$in": ["pending", "open", "scheduled", "agendada"]}})

    # OS criadas últimas 24h por tipo
    last_repairs = await db.smart_repairs.count_documents({
        "company_id": company_id, "created_at": {"$gte": cutoff_24h}})
    preventive_24h = await db.smart_repairs.count_documents({
        "company_id": company_id, "created_at": {"$gte": cutoff_24h},
        "origin": "preventive"})

    # Razão preventiva atual
    ratio_target = PREVENTIVE_RATIO_NUM / PREVENTIVE_RATIO_DEN
    ratio_actual = (preventive_24h / max(1, last_repairs))
    preventive_deficit = max(0, math.ceil(last_repairs * ratio_target) - preventive_24h)

    # Incidentes coletivos abertos
    open_incidents = await db.incidents.count_documents({
        "company_id": company_id, "status": {"$in": ["open", "OPEN", "active"]}})

    # CTOs críticas (via predictive)
    ctos_critical: List[Dict[str, Any]] = []
    try:
        from services.smartolt_predictive import predict_cto_failures
        cf = await predict_cto_failures(company_id, limit=10)
        # Aceita ambos: dict {results:[...]} OU list[dict] direto
        if isinstance(cf, dict):
            ctos_critical = cf.get("results", [])[:10]
        elif isinstance(cf, list):
            ctos_critical = cf[:10]
    except Exception:
        pass

    # ONUs recorrentes
    onus_recurrent: List[Dict[str, Any]] = []
    try:
        from services.smartolt_predictive import predict_recurrent_onu_failures
        r = await predict_recurrent_onu_failures(company_id, limit=10)
        if isinstance(r, dict):
            onus_recurrent = r.get("results", [])[:10]
        elif isinstance(r, list):
            onus_recurrent = r[:10]
    except Exception:
        pass

    # Diretrizes — 1 por gargalo
    directives: List[Dict[str, Any]] = []
    if preventive_deficit > 0:
        directives.append({
            "kind": "ENFORCE_PREVENTIVE_RATIO",
            "missing_preventive": preventive_deficit,
            "current_ratio": round(ratio_actual, 2),
            "target_ratio": round(ratio_target, 2),
            "action": f"criar {preventive_deficit} preventivas a partir de CTOs/ONUs degradadas",
        })
    if open_incidents > 0:
        directives.append({
            "kind": "ATTACK_INCIDENTS",
            "open_incidents": open_incidents,
            "action": "concentrar técnicos em incidentes coletivos abertos antes de chamados individuais",
        })
    if ctos_critical:
        directives.append({
            "kind": "FREEZE_CTO_DEGRADED",
            "ctos": [c.get("cto_id") or c.get("id") for c in ctos_critical[:5]],
            "action": "congelar instalações nas CTOs críticas até reparo de causa-raiz",
        })
    if not directives:
        directives.append({"kind": "STEADY_STATE",
                            "action": "operação dentro dos limites — manter ritmo"})

    # Persiste a diretiva como ação executiva (reuso executive_ledger)
    directive_doc = {
        "id": f"directive-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "date": today,
        "created_at": _iso(),
        "kind": "LOUSA_DAILY_DIRECTIVE",
        "directives": directives,
        "kpis": {
            "open_repairs": open_repairs,
            "open_installs": open_installs,
            "preventive_24h": preventive_24h,
            "repairs_24h": last_repairs,
            "preventive_ratio_actual": round(ratio_actual, 3),
            "preventive_ratio_target": round(ratio_target, 3),
            "preventive_deficit": preventive_deficit,
            "open_incidents": open_incidents,
            "ctos_critical": len(ctos_critical),
            "onus_recurrent": len(onus_recurrent),
        },
    }
    try:
        await db.executive_ledger.update_one(
            {"company_id": company_id, "kind": "LOUSA_DAILY_DIRECTIVE", "date": today},
            {"$set": directive_doc}, upsert=True)
    except Exception:
        pass
    return directive_doc


# ---------------------------------------------------------------------------
# 2) PREVENTIVA AUTOMÁTICA — 3 preventivas por 12 OS operacionais
# ---------------------------------------------------------------------------
async def enforce_preventive_ratio(company_id: str,
                                     dry_run: bool = False) -> Dict[str, Any]:
    """Garante que a razão de preventivas atinja o alvo (3:12). Quando
    abaixo, cria preventivas a partir de CTOs/ONUs degradadas (reusa
    smartolt_predictive.auto_create_preventive_tickets).
    """
    cutoff_24h = (_now() - timedelta(hours=24)).isoformat()
    repairs_24h = await db.smart_repairs.count_documents({
        "company_id": company_id, "created_at": {"$gte": cutoff_24h}})
    preventive_24h = await db.smart_repairs.count_documents({
        "company_id": company_id, "created_at": {"$gte": cutoff_24h},
        "origin": "preventive"})

    target = math.ceil(repairs_24h * (PREVENTIVE_RATIO_NUM / PREVENTIVE_RATIO_DEN))
    deficit = max(0, target - preventive_24h)
    created = 0
    sample: List[Dict[str, Any]] = []
    if deficit > 0 and not dry_run:
        try:
            from services.smartolt_predictive import auto_create_preventive_tickets
            r = await auto_create_preventive_tickets(company_id, max_tickets=deficit)
            created = (r or {}).get("created", 0)
            sample = (r or {}).get("tickets", [])[:5]
        except Exception:
            created = 0
        # Sempre completa o déficit com preventivas baseadas em sinal degradado
        if created < deficit:
            need = deficit - created
            cur = db.smartolt_onus.find(
                {"company_id": company_id,
                 "signal_1310": {"$lt": -27}},
                {"_id": 0, "id": 1, "subscriber_id": 1,
                 "cto_id": 1, "signal_1310": 1, "olt_name": 1}
            ).sort("signal_1310", 1).limit(need)
            async for onu in cur:
                tid = f"prev-{uuid.uuid4().hex[:10]}"
                doc = {
                    "id": tid, "company_id": company_id,
                    "subscriber_id": onu.get("subscriber_id"),
                    "type": "preventive", "origin": "preventive",
                    "status": "pending",
                    "priority": "medium",
                    "reason": f"sinal degradado {onu.get('signal_1310')} dBm",
                    "cto_id": onu.get("cto_id"),
                    "olt_name": onu.get("olt_name"),
                    "created_by": "lousa_coo",
                    "created_at": _iso(),
                }
                try:
                    await db.smart_repairs.insert_one(doc)
                    created += 1
                    sample.append({"id": tid, "reason": doc["reason"]})
                except Exception:
                    pass
    return {
        "repairs_24h": repairs_24h,
        "preventive_24h_before": preventive_24h,
        "target": target,
        "deficit": deficit,
        "created": created,
        "preventive_24h_after": preventive_24h + created,
        "sample": sample,
        "ratio_after": round((preventive_24h + created) / max(1, repairs_24h), 3),
        "ts": _iso(),
    }


# ---------------------------------------------------------------------------
# 3) PLAN FIELD DAY — sequência ideal de OS por técnico
# ---------------------------------------------------------------------------
async def plan_field_day(company_id: str) -> Dict[str, Any]:
    """Distribui OS pendentes por técnico considerando bairro, SLA, prioridade.

    Estratégia (sem ML pesado, regras + agrupamento por bairro/CTO):
      1. Pega smart_repairs e smart_installs com status pending.
      2. Agrupa por bairro/CTO.
      3. Atribui a técnico com menor carga + score alto na cidade.
      4. Ordena por prioridade (incidente > preventiva > rotina).
    """
    # Técnicos disponíveis (usa client_equipment_history / lousa_tickets como proxy
    # se não houver tabela `technicians`).
    techs_set = set()
    cursor = db.lousa_tickets.find({"company_id": company_id},
                                     {"_id": 0, "collaborator_id": 1,
                                      "collaborator_name": 1}).limit(500)
    async for t in cursor:
        if t.get("collaborator_id"):
            techs_set.add((t["collaborator_id"], t.get("collaborator_name", "")))
    techs = [{"id": tid, "name": name} for tid, name in list(techs_set)[:200]]
    # Se não há técnicos no lousa, usa tabela `users` com role tecnico
    if not techs:
        cursor = db.users.find({"company_id": company_id,
                                  "role": {"$in": ["tecnico", "field_tech"]}},
                                 {"_id": 0, "id": 1, "name": 1}).limit(200)
        async for u in cursor:
            techs.append({"id": u.get("id"), "name": u.get("name")})

    # OS pendentes
    pending: List[Dict[str, Any]] = []
    async for r in db.smart_repairs.find(
            {"company_id": company_id,
             "status": {"$in": ["pending", "open", "scheduled"]}},
            {"_id": 0, "id": 1, "subscriber_id": 1, "cto_id": 1,
             "type": 1, "priority": 1, "origin": 1,
             "neighborhood": 1, "created_at": 1}).limit(500):
        pending.append({**r, "kind": "repair"})
    async for r in db.smart_installs.find(
            {"company_id": company_id,
             "status": {"$in": ["pending", "open", "scheduled"]}},
            {"_id": 0, "id": 1, "subscriber_id": 1, "cto_id": 1,
             "type": 1, "priority": 1, "neighborhood": 1,
             "created_at": 1}).limit(500):
        pending.append({**r, "kind": "install"})

    # Score técnico carregado uma vez
    tech_scores = {ts["technician_id"]: ts["score"]
                   async for ts in db.ai_evaluations.find(
                       {"company_id": company_id, "kind": "TECHNICIAN_SCORE"},
                       {"_id": 0, "technician_id": 1, "score": 1})}

    # Agrupa por CTO/bairro
    by_cluster: Dict[str, List[Dict[str, Any]]] = {}
    for o in pending:
        cluster = o.get("cto_id") or o.get("neighborhood") or "_outros"
        by_cluster.setdefault(cluster, []).append(o)

    # Round-robin: técnico ↔ cluster ordenado por score
    techs_sorted = sorted(techs, key=lambda t: -tech_scores.get(t["id"], 50))
    if not techs_sorted:
        techs_sorted = [{"id": "tech-unassigned", "name": "Sem técnico"}]

    plan_by_tech: Dict[str, Dict[str, Any]] = {}
    for i, (cluster, jobs) in enumerate(by_cluster.items()):
        tech = techs_sorted[i % len(techs_sorted)]
        slot = plan_by_tech.setdefault(tech["id"], {
            "technician_id": tech["id"], "technician_name": tech.get("name"),
            "score": tech_scores.get(tech["id"], 50),
            "clusters": [], "jobs": [], "estimated_drive_savings_min": 0,
        })
        # Ordena por prioridade
        prio_order = {"incidente": 0, "incident": 0, "high": 1,
                       "alta": 1, "preventive": 2, "medium": 2,
                       "media": 2, "rotina": 3, "low": 3, "baixa": 3, None: 4}
        jobs_sorted = sorted(jobs, key=lambda j: prio_order.get(j.get("priority"), 4))
        slot["clusters"].append(cluster)
        slot["jobs"].extend([{"id": j.get("id"),
                                "kind": j.get("kind"),
                                "subscriber_id": j.get("subscriber_id"),
                                "priority": j.get("priority"),
                                "origin": j.get("origin"),
                                "cluster": cluster} for j in jobs_sorted])
        # Heurística: agrupamento por CTO economiza 15 min/job extra
        if len(jobs_sorted) > 1:
            slot["estimated_drive_savings_min"] += 15 * (len(jobs_sorted) - 1)

    summary = {
        "company_id": company_id,
        "technicians_used": len(plan_by_tech),
        "total_jobs_planned": sum(len(p["jobs"]) for p in plan_by_tech.values()),
        "total_clusters": sum(len(p["clusters"]) for p in plan_by_tech.values()),
        "estimated_drive_savings_min": sum(p["estimated_drive_savings_min"]
                                              for p in plan_by_tech.values()),
        "plan": list(plan_by_tech.values()),
        "ts": _iso(),
    }

    # Persiste em executive_ledger
    try:
        await db.executive_ledger.update_one(
            {"company_id": company_id, "kind": "LOUSA_FIELD_PLAN",
             "date": _now().date().isoformat()},
            {"$set": {"company_id": company_id,
                      "kind": "LOUSA_FIELD_PLAN",
                      "date": _now().date().isoformat(),
                      "summary": {k: v for k, v in summary.items()
                                   if k != "plan"},
                      "created_at": _iso()}}, upsert=True)
    except Exception:
        pass
    return summary


# ---------------------------------------------------------------------------
# 4) TECHNICIAN SCORE — 0-100 por técnico, persistido em ai_evaluations
# ---------------------------------------------------------------------------
async def compute_technician_scores(company_id: str,
                                      window_days: int = 30
                                      ) -> Dict[str, Any]:
    """Calcula score 0-100 por técnico considerando produtividade,
    retrabalho, tempo médio, retornos. Persiste em `ai_evaluations`
    com `kind=TECHNICIAN_SCORE` (coleção existente).
    """
    cutoff = (_now() - timedelta(days=window_days)).isoformat()
    # Agrega smart_repairs + smart_installs
    techs: Dict[str, Dict[str, Any]] = {}

    async for r in db.smart_repairs.find(
            {"company_id": company_id, "created_at": {"$gte": cutoff}},
            {"_id": 0, "technician_id": 1, "status": 1,
             "subscriber_id": 1, "created_at": 1, "closed_at": 1,
             "reopened": 1, "origin": 1}):
        tid = r.get("technician_id") or "_no_tech"
        t = techs.setdefault(tid, {"completed": 0, "reopened": 0,
                                     "preventive": 0, "duration_h": [],
                                     "installs": 0, "repairs": 0,
                                     "subs": set()})
        t["repairs"] += 1
        if r.get("status") in ("done", "closed", "concluido", "finalizado"):
            t["completed"] += 1
        if r.get("reopened"):
            t["reopened"] += 1
        if r.get("origin") == "preventive":
            t["preventive"] += 1
        if r.get("subscriber_id"):
            t["subs"].add(r["subscriber_id"])
        try:
            if r.get("closed_at") and r.get("created_at"):
                start = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(r["closed_at"].replace("Z", "+00:00"))
                t["duration_h"].append(max(0.5, (end - start).total_seconds() / 3600.0))
        except Exception:
            pass

    async for r in db.smart_installs.find(
            {"company_id": company_id, "created_at": {"$gte": cutoff}},
            {"_id": 0, "technician_id": 1, "status": 1,
             "subscriber_id": 1, "created_at": 1, "closed_at": 1}):
        tid = r.get("technician_id") or "_no_tech"
        t = techs.setdefault(tid, {"completed": 0, "reopened": 0,
                                     "preventive": 0, "duration_h": [],
                                     "installs": 0, "repairs": 0,
                                     "subs": set()})
        t["installs"] += 1
        if r.get("status") in ("done", "closed", "concluido", "finalizado"):
            t["completed"] += 1

    # Retrabalho: subscribers com 2+ repairs no período
    repeats: Dict[str, int] = {}
    for tid, t in techs.items():
        for sid in list(t["subs"]):
            n = await db.smart_repairs.count_documents({
                "company_id": company_id,
                "subscriber_id": sid,
                "created_at": {"$gte": cutoff}})
            if n >= 2:
                repeats[tid] = repeats.get(tid, 0) + 1

    results: List[Dict[str, Any]] = []
    for tid, t in techs.items():
        completed = t["completed"]
        total = t["repairs"] + t["installs"]
        reopened = t["reopened"] + repeats.get(tid, 0)
        avg_h = statistics.mean(t["duration_h"]) if t["duration_h"] else None
        # Pontuação 0-100
        score = 50
        # Produtividade
        score += min(20, total // 2)
        # Conclusão
        if total:
            score += int((completed / total) * 15)
        # Retrabalho penaliza
        if total:
            rework_pct = reopened / total
            score -= int(rework_pct * 30)
        # Preventiva aumenta
        score += min(10, t["preventive"])
        # Tempo médio (<= 4h ganha bonus, >= 24h perde)
        if avg_h is not None:
            if avg_h <= 4:
                score += 5
            elif avg_h >= 24:
                score -= 5
        score = max(0, min(100, score))

        result = {
            "id": f"tech-score-{uuid.uuid4().hex[:8]}",
            "company_id": company_id,
            "kind": "TECHNICIAN_SCORE",
            "technician_id": tid,
            "window_days": window_days,
            "score": score,
            "metrics": {
                "total_jobs": total,
                "completed": completed,
                "reopened_or_repeat": reopened,
                "preventive": t["preventive"],
                "avg_duration_h": round(avg_h, 1) if avg_h else None,
                "unique_subscribers": len(t["subs"]),
            },
            "computed_at": _iso(),
        }
        results.append(result)
        try:
            await db.ai_evaluations.update_one(
                {"company_id": company_id, "kind": "TECHNICIAN_SCORE",
                 "technician_id": tid},
                {"$set": result}, upsert=True)
        except Exception:
            pass

    return {
        "company_id": company_id,
        "window_days": window_days,
        "scored": len(results),
        "results": sorted(results, key=lambda r: -r["score"])[:50],
        "ts": _iso(),
    }


# ---------------------------------------------------------------------------
# 5) CONSELHO OPERACIONAL — 8 TOP-10 semanais
# ---------------------------------------------------------------------------
async def operational_council_weekly(company_id: str) -> Dict[str, Any]:
    """Gera 8 rankings TOP-10 e persiste em executive_ledger."""
    cutoff = (_now() - timedelta(days=7)).isoformat()
    base = {"company_id": company_id, "created_at": {"$gte": cutoff}}

    async def _top_agg(coll, field, label, extra: Optional[Dict] = None,
                         limit: int = 10) -> List[Dict[str, Any]]:
        match = {**base, **(extra or {})}
        pipe = [
            {"$match": match},
            {"$group": {"_id": f"${field}", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}},
            {"$limit": limit},
        ]
        out: List[Dict[str, Any]] = []
        async for r in coll.aggregate(pipe):
            if not r["_id"]:
                continue
            out.append({label: r["_id"], "count": r["n"]})
        return out

    top_causes = await _top_agg(db.smart_repairs, "reason", "cause")
    top_ctos = await _top_agg(db.smart_repairs, "cto_id", "cto")
    top_onus = await _top_agg(db.smart_repairs, "subscriber_id", "subscriber")
    top_neighborhoods = await _top_agg(db.smart_repairs, "neighborhood", "neighborhood")
    top_materials = await _top_agg(db.smart_repairs, "material_used", "material")
    top_returns = await _top_agg(db.smart_repairs, "subscriber_id", "subscriber",
                                  extra={"reopened": True})

    # TOP técnicos eficientes (score desc)
    tech_scores = []
    async for s in db.ai_evaluations.find(
            {"company_id": company_id, "kind": "TECHNICIAN_SCORE"},
            {"_id": 0, "technician_id": 1, "score": 1, "metrics": 1}
    ).sort("score", -1).limit(10):
        tech_scores.append({"technician": s["technician_id"],
                              "score": s["score"],
                              "metrics": s.get("metrics")})
    # TOP retrabalho
    top_rework = []
    async for s in db.ai_evaluations.find(
            {"company_id": company_id, "kind": "TECHNICIAN_SCORE",
             "metrics.reopened_or_repeat": {"$gt": 0}},
            {"_id": 0, "technician_id": 1, "metrics": 1}
    ).sort("metrics.reopened_or_repeat", -1).limit(10):
        top_rework.append({"technician": s["technician_id"],
                              "rework": s["metrics"]["reopened_or_repeat"]})

    council = {
        "id": f"council-{uuid.uuid4().hex[:8]}",
        "company_id": company_id,
        "kind": "OPERATIONAL_COUNCIL_WEEKLY",
        "window_days": 7,
        "computed_at": _iso(),
        "top_10_causes": top_causes,
        "top_10_ctos": top_ctos,
        "top_10_onus": top_onus,
        "top_10_neighborhoods": top_neighborhoods,
        "top_10_materials": top_materials,
        "top_10_returns": top_returns,
        "top_10_efficient_technicians": tech_scores,
        "top_10_rework_technicians": top_rework,
    }
    try:
        await db.executive_ledger.update_one(
            {"company_id": company_id, "kind": "OPERATIONAL_COUNCIL_WEEKLY",
             "computed_at": council["computed_at"][:10]},
            {"$set": council}, upsert=True)
    except Exception:
        pass
    return council


# ---------------------------------------------------------------------------
# 6) OS LEARNING — aprendizado pós-OS em ai_evaluations
# ---------------------------------------------------------------------------
async def register_os_learning(ticket_id: str,
                                 company_id: str) -> Dict[str, Any]:
    """Lê a OS (repair ou install) já fechada e registra aprendizado em
    ai_evaluations. Responde as 6 perguntas obrigatórias do CTO:
      • resolveu?  • retornou?  • cliente satisfeito?  • material correto?
      • visita evitável?  • tempo correto?
    """
    ticket = await db.smart_repairs.find_one({"id": ticket_id, "company_id": company_id},
                                               {"_id": 0}) or \
             await db.smart_installs.find_one({"id": ticket_id, "company_id": company_id},
                                                {"_id": 0})
    if not ticket:
        return {"error": "ticket não encontrado", "ticket_id": ticket_id}

    sub_id = ticket.get("subscriber_id")
    # Resolveu?
    resolveu = ticket.get("status") in ("done", "closed", "concluido", "finalizado")
    # Retornou? (mesmo subscriber gerou outro repair em 7d depois desta OS)
    retornou = False
    if sub_id and ticket.get("closed_at"):
        try:
            after = ticket["closed_at"]
            n = await db.smart_repairs.count_documents({
                "company_id": company_id,
                "subscriber_id": sub_id,
                "created_at": {"$gt": after}})
            retornou = n > 0
        except Exception:
            pass
    # Cliente satisfeito? Reusa NPS invisível mais recente do mesmo subscriber
    cliente_satisfeito = None
    try:
        eval_isabella = await db.ai_evaluations.find_one(
            {"company_id": company_id,
             "subscriber_id": sub_id,
             "nps_inferido": {"$exists": True}},
            {"_id": 0, "nps_inferido": 1},
            sort=[("created_at", -1)])
        if eval_isabella:
            cliente_satisfeito = int(eval_isabella["nps_inferido"]) >= 7
    except Exception:
        pass
    # Material correto? (heurística: material_used preenchido)
    material_correto = bool(ticket.get("material_used"))
    # Visita evitável? (truck_roll_decision == DO_NOT_DISPATCH para o sub)
    visita_evitavel = False
    try:
        trd = await db.truck_roll_decisions.find_one(
            {"company_id": company_id, "subscriber_id": sub_id},
            {"_id": 0, "decision": 1},
            sort=[("ts", -1)])
        if trd and trd.get("decision") in ("DO_NOT_DISPATCH", "PREVENTIVA"):
            visita_evitavel = True
    except Exception:
        pass
    # Tempo correto? (duração entre created/closed <= 8h)
    tempo_correto = None
    try:
        if ticket.get("closed_at") and ticket.get("created_at"):
            start = datetime.fromisoformat(ticket["created_at"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(ticket["closed_at"].replace("Z", "+00:00"))
            duration_h = (end - start).total_seconds() / 3600.0
            tempo_correto = duration_h <= 8
    except Exception:
        pass

    doc = {
        "id": f"os-eval-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "kind": "OS_LEARNING",
        "ticket_id": ticket_id,
        "subscriber_id": sub_id,
        "technician_id": ticket.get("technician_id"),
        "resolveu": resolveu,
        "retornou": retornou,
        "cliente_satisfeito": cliente_satisfeito,
        "material_correto": material_correto,
        "visita_evitavel": visita_evitavel,
        "tempo_correto": tempo_correto,
        "computed_at": _iso(),
    }
    try:
        await db.ai_evaluations.update_one(
            {"company_id": company_id, "kind": "OS_LEARNING",
             "ticket_id": ticket_id},
            {"$set": doc}, upsert=True)
    except Exception:
        pass
    return doc


# ---------------------------------------------------------------------------
# 7) ÁLVARO COMANDANTE — vê degradação e TOMA AÇÃO
# ---------------------------------------------------------------------------
async def alvaro_command_loop(company_id: str,
                                max_actions: int = 20) -> Dict[str, Any]:
    """Faz Álvaro deixar de observar e começar a comandar:
      • CTO degradada → cria 1 ticket preventivo na CTO
      • ONU recorrente → cria smart_repair preventivo
      • Incidente coletivo detectado → upgrade do incidente status=escalated

    Reusa smartolt_predictive + truck_roll_guard + smartolt_twin.
    """
    actions: List[Dict[str, Any]] = []
    # 1) CTOs degradadas → preventiva
    try:
        from services.smartolt_predictive import predict_cto_failures
        cf = await predict_cto_failures(company_id, limit=max_actions // 2)
        cto_list = cf.get("results") if isinstance(cf, dict) else cf
        for c in (cto_list or []):
            if not isinstance(c, dict):
                continue
            cto_id = c.get("cto_id") or c.get("id") or c.get("zone")
            if not cto_id:
                continue
            tid = f"prev-cto-{uuid.uuid4().hex[:10]}"
            doc = {
                "id": tid, "company_id": company_id,
                "type": "preventive_cto", "origin": "preventive",
                "status": "pending", "priority": "high",
                "cto_id": cto_id,
                "reason": f"CTO degradada (Álvaro) — {c.get('rationale', 'health<70')}",
                "created_by": "alvaro_commander",
                "created_at": _iso(),
            }
            r = await db.smart_repairs.update_one(
                {"company_id": company_id, "cto_id": cto_id,
                 "origin": "preventive", "status": "pending"},
                {"$setOnInsert": doc}, upsert=True)
            if r.upserted_id:
                actions.append({"kind": "PREVENTIVE_CTO", "cto_id": cto_id, "ticket_id": tid})
    except Exception as e:
        actions.append({"kind": "PREVENTIVE_CTO_ERROR", "error": str(e)})

    # 2) ONUs recorrentes → preventiva subscriber-specific
    try:
        from services.smartolt_predictive import predict_recurrent_onu_failures
        rr = await predict_recurrent_onu_failures(company_id, limit=max_actions // 2)
        onu_list = rr.get("results") if isinstance(rr, dict) else rr
        for onu in (onu_list or []):
            if not isinstance(onu, dict):
                continue
            sid = onu.get("subscriber_id")
            if not sid:
                continue
            tid = f"prev-onu-{uuid.uuid4().hex[:10]}"
            doc = {
                "id": tid, "company_id": company_id,
                "subscriber_id": sid,
                "type": "preventive_onu", "origin": "preventive",
                "status": "pending", "priority": "medium",
                "reason": f"ONU recorrente (Álvaro): {onu.get('tickets_30d', '?')} tickets/30d",
                "created_by": "alvaro_commander",
                "created_at": _iso(),
            }
            r = await db.smart_repairs.update_one(
                {"company_id": company_id, "subscriber_id": sid,
                 "origin": "preventive", "status": "pending"},
                {"$setOnInsert": doc}, upsert=True)
            if r.upserted_id:
                actions.append({"kind": "PREVENTIVE_ONU",
                                "subscriber_id": sid, "ticket_id": tid})
    except Exception as e:
        actions.append({"kind": "PREVENTIVE_ONU_ERROR", "error": str(e)})

    # 3) Incidentes coletivos detectados pelo Álvaro escalam status
    try:
        async for inc in db.incidents.find(
                {"company_id": company_id,
                 "status": {"$in": ["open", "OPEN"]},
                 "severity": {"$in": ["high", "alta", "critical"]}},
                {"_id": 0, "id": 1, "type": 1, "title": 1}).limit(max_actions // 4):
            await db.incidents.update_one(
                {"id": inc["id"], "company_id": company_id},
                {"$set": {"status": "escalated", "escalated_by": "alvaro_commander",
                          "escalated_at": _iso()}})
            actions.append({"kind": "ESCALATE_INCIDENT", "incident_id": inc["id"]})
    except Exception:
        pass

    return {
        "company_id": company_id,
        "actions_taken": len(actions),
        "actions": actions[:50],
        "ts": _iso(),
    }
