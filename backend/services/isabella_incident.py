"""ISABELLA INCIDENT COMMANDER — detecção PREDITIVA de incidentes coletivos.

A Isabella não espera o cliente reclamar: varre continuamente os dados REAIS
(tickets, cto_ports, smartolt_onus, histórico de causas-raiz) e detecta
padrões de falha coletiva ANTES da próxima reclamação.

REGRAS DE DETECÇÃO (todas sobre dados reais, zero mock):
  1. cto_cluster        — ≥3 reparos na mesma CTO em 48h
  2. neighborhood_cluster — ≥5 reparos no mesmo bairro em 48h
  3. onu_offline        — ≥3 ONUs offline na mesma CTO (≥40% das vinculadas)
  4. optical_loss       — ≥3 ONUs com sinal 1490 < -27 dBm na mesma CTO
  5. slow_cluster       — ≥3 reparos com relato de lentidão no mesmo bairro/48h
  6. reincidence        — taxa de reincidência da CTO ≥ 2× a média da empresa
  7. cto_chronic        — ≥6 reparos na mesma CTO em 30 dias
  8. region_trend       — reparos no bairro em 7d ≥ 4 e ≥ 2× a semana anterior

AO DETECTAR (incident em `isabella_incidents`):
  • score de criticidade + probabilidade + clientes afetados (portas reais)
  • risco de churn + impacto financeiro (ARPU configurável por empresa)
  • bolha CRÍTICA na Lousa (OS coletiva, atribuída ao técnico com mais
    chamados na evidência) com análise Isabella rank #1
  • notificação a gestor/administrador
  • eventos auditáveis: incident.predicted / confirmed / cto.cluster /
    neighborhood.cluster / churn.risk / mass.repair → Presidente IA
  • feed para a Rede IA (CTOs/regiões/ONUs suspeitas + tendência)
  • trava de novos reparos individuais da mesma causa (clientes agrupados
    no incidente — toggle incident_block_individual_repairs)
"""

NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db
from services.event_bus import EventType, emit_event

logger = logging.getLogger("ponto.isabella_incident")

OPEN_STATUSES = ("predicted", "confirmed")
INCIDENT_TTL_H = 72          # dedup: incidente aberto há <72h é atualizado
SCAN_INTERVAL_SEC = 15 * 60  # varredura automática a cada 15 min
SLOW_RE = re.compile(r"lent[oa]|lentid[ãa]o|travand|oscilando|intermitente",
                     re.IGNORECASE)

KIND_LABEL = {
    "cto_cluster": "Cluster de reparos na CTO",
    "neighborhood_cluster": "Cluster de reparos no bairro",
    "onu_offline": "ONUs offline em massa na CTO",
    "optical_loss": "Perda óptica anormal na CTO",
    "slow_cluster": "Cluster de lentidão no bairro",
    "reincidence": "Reincidência acima da média na CTO",
    "cto_chronic": "CTO com histórico crítico (30d)",
    "region_trend": "Tendência de falha na região",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _emit(event_type: str, company: str, payload: Dict[str, Any],
                severity: str = "alta") -> None:
    try:
        await emit_event(event_type, company_id=company,
                         source="isabella_incident", severity=severity,
                         payload=payload)
    except Exception as e:
        logger.warning("[isabella_incident] emit %s: %s", event_type, e)


async def _arpu(company: str) -> float:
    doc = await db.aihub_settings.find_one(
        {"company_id": company, "key": "field_ops_toggles"},
        {"_id": 0, "value": 1})
    return float(((doc or {}).get("value") or {}).get("arpu_brl") or 99.90)


async def _toggle_block(company: str) -> bool:
    doc = await db.aihub_settings.find_one(
        {"company_id": company, "key": "field_ops_toggles"},
        {"_id": 0, "value": 1})
    val = ((doc or {}).get("value") or {}).get("incident_block_individual_repairs")
    return True if val is None else bool(val)


# ---------------------------------------------------------------------------
# Coleta de evidências reais
# ---------------------------------------------------------------------------
async def _repairs_window(company: str, hours: int) -> List[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    return await db.tickets.find(
        {"company_id": company, "type": "reparo",
         "created_at": {"$gte": cutoff},
         "is_collective": {"$ne": True}},
        {"_id": 0, "id": 1, "client_id": 1, "created_at": 1, "status": 1,
         "client_snapshot.name": 1, "client_snapshot.neighborhood": 1,
         "client_snapshot.relato": 1, "assigned_collaborator_id": 1}
    ).to_list(2000)


async def _ports_by_clients(company: str, client_ids: List[str]) -> Dict[str, dict]:
    rows = await db.cto_ports.find(
        {"company_id": company, "subscriber_id": {"$in": client_ids},
         "status": "occupied"},
        {"_id": 0, "subscriber_id": 1, "cto_id": 1, "cto_name": 1, "sn": 1}
    ).to_list(5000)
    return {r["subscriber_id"]: r for r in rows}


async def _affected_clients_cto(company: str, cto_id: str) -> int:
    return await db.cto_ports.count_documents(
        {"company_id": company, "cto_id": cto_id, "status": "occupied"})


async def _affected_clients_neighborhood(company: str, neigh: str) -> int:
    n = await db.subscribers.count_documents(
        {"company_id": company,
         "neighborhood": {"$regex": f"^{re.escape(neigh)}$", "$options": "i"}})
    if n:
        return n
    return await db.cto_ports.count_documents(
        {"company_id": company, "status": "occupied",
         "neighborhood": {"$regex": f"^{re.escape(neigh)}$", "$options": "i"}})


# ---------------------------------------------------------------------------
# Núcleo: candidatos por regra
# ---------------------------------------------------------------------------
async def _rule_candidates(company: str) -> List[dict]:
    """Retorna candidatos {kind, scope_id, scope, evidence} de TODAS as regras."""
    cands: List[dict] = []
    rep48 = await _repairs_window(company, 48)
    client_ids = list({r.get("client_id") for r in rep48 if r.get("client_id")})
    ports = await _ports_by_clients(company, client_ids)

    # Regra 1 — cluster por CTO (48h)
    by_cto: Dict[str, List[dict]] = defaultdict(list)
    for r in rep48:
        p = ports.get(r.get("client_id"))
        if p:
            by_cto[p["cto_id"]].append(r)
    for cto_id, rows in by_cto.items():
        if len(rows) >= 3:
            cands.append({"kind": "cto_cluster", "scope_id": cto_id,
                          "scope": {"cto_id": cto_id,
                                    "cto_name": ports[rows[0]["client_id"]].get("cto_name")},
                          "evidence": rows, "window_h": 48, "threshold": 3})

    # Regra 2 — cluster por bairro (48h)
    by_neigh: Dict[str, List[dict]] = defaultdict(list)
    for r in rep48:
        nb = ((r.get("client_snapshot") or {}).get("neighborhood") or "").strip()
        if nb:
            by_neigh[nb.lower()].append(r)
    for nb, rows in by_neigh.items():
        if len(rows) >= 5:
            cands.append({"kind": "neighborhood_cluster", "scope_id": nb,
                          "scope": {"neighborhood": (rows[0]["client_snapshot"] or {}).get("neighborhood")},
                          "evidence": rows, "window_h": 48, "threshold": 5})

    # Regra 5 — lentidão por bairro (48h)
    for nb, rows in by_neigh.items():
        slow = [r for r in rows
                if SLOW_RE.search((r.get("client_snapshot") or {}).get("relato") or "")]
        if len(slow) >= 3:
            cands.append({"kind": "slow_cluster", "scope_id": nb,
                          "scope": {"neighborhood": (slow[0]["client_snapshot"] or {}).get("neighborhood")},
                          "evidence": slow, "window_h": 48, "threshold": 3})

    # Regras 6/7 — reincidência e CTO crônica (30d)
    rep30 = await _repairs_window(company, 30 * 24)
    ids30 = list({r.get("client_id") for r in rep30 if r.get("client_id")})
    ports30 = await _ports_by_clients(company, ids30)
    by_cto30: Dict[str, List[dict]] = defaultdict(list)
    for r in rep30:
        p = ports30.get(r.get("client_id"))
        if p:
            by_cto30[p["cto_id"]].append(r)
    # média da empresa: reparos repetidos por cliente / total
    by_client30: Dict[str, int] = defaultdict(int)
    for r in rep30:
        if r.get("client_id"):
            by_client30[r["client_id"]] += 1
    total_clients = len(by_client30) or 1
    company_reinc_rate = (sum(1 for n in by_client30.values() if n >= 2)
                          / total_clients)
    for cto_id, rows in by_cto30.items():
        if len(rows) >= 6:
            cands.append({"kind": "cto_chronic", "scope_id": cto_id,
                          "scope": {"cto_id": cto_id,
                                    "cto_name": ports30[rows[0]["client_id"]].get("cto_name")},
                          "evidence": rows, "window_h": 720, "threshold": 6})
        # reincidência da CTO
        cto_clients: Dict[str, int] = defaultdict(int)
        for r in rows:
            cto_clients[r["client_id"]] += 1
        if len(cto_clients) >= 3 and company_reinc_rate > 0:
            cto_rate = (sum(1 for n in cto_clients.values() if n >= 2)
                        / len(cto_clients))
            if cto_rate >= 2 * company_reinc_rate and cto_rate >= 0.3:
                cands.append({"kind": "reincidence", "scope_id": cto_id,
                              "scope": {"cto_id": cto_id,
                                        "cto_name": ports30[rows[0]["client_id"]].get("cto_name"),
                                        "cto_rate": round(cto_rate, 2),
                                        "company_rate": round(company_reinc_rate, 2)},
                              "evidence": rows, "window_h": 720, "threshold": 3})

    # Regra 8 — tendência da região (7d vs 7d anteriores)
    cutoff7 = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    by_neigh_recent: Dict[str, List[dict]] = defaultdict(list)
    by_neigh_prev: Dict[str, int] = defaultdict(int)
    for r in rep30:
        nb = ((r.get("client_snapshot") or {}).get("neighborhood") or "").strip().lower()
        if not nb:
            continue
        if (r.get("created_at") or "") >= cutoff7:
            by_neigh_recent[nb].append(r)
        elif (r.get("created_at") or "") >= (datetime.now(timezone.utc)
                                             - timedelta(days=14)).isoformat():
            by_neigh_prev[nb] += 1
    for nb, rows in by_neigh_recent.items():
        prev = by_neigh_prev.get(nb, 0)
        if len(rows) >= 4 and len(rows) >= 2 * max(prev, 1):
            cands.append({"kind": "region_trend", "scope_id": nb,
                          "scope": {"neighborhood": (rows[0]["client_snapshot"] or {}).get("neighborhood"),
                                    "repairs_7d": len(rows),
                                    "repairs_prev_7d": prev},
                          "evidence": rows, "window_h": 168, "threshold": 4})

    # Regras 3/4 — ONUs offline / perda óptica por CTO (via SN real)
    sn_ports = await db.cto_ports.find(
        {"company_id": company, "status": "occupied",
         "sn": {"$nin": [None, "", "None"]}},
        {"_id": 0, "cto_id": 1, "cto_name": 1, "sn": 1, "subscriber_id": 1}
    ).to_list(20000)
    if sn_ports:
        sns = [p["sn"] for p in sn_ports]
        onus = await db.smartolt_onus.find(
            {"company_id": company, "sn": {"$in": sns}},
            {"_id": 0, "sn": 1, "status": 1, "signal_1490": 1}).to_list(20000)
        onu_by_sn = {o["sn"]: o for o in onus}
        cto_onus: Dict[str, List[dict]] = defaultdict(list)
        cto_names: Dict[str, str] = {}
        for p in sn_ports:
            o = onu_by_sn.get(p["sn"])
            if o:
                cto_onus[p["cto_id"]].append(o)
                cto_names[p["cto_id"]] = p.get("cto_name")
        for cto_id, rows in cto_onus.items():
            offline = [o for o in rows if (o.get("status") or "") != "Online"]
            if len(offline) >= 3 and len(offline) / len(rows) >= 0.4:
                cands.append({"kind": "onu_offline", "scope_id": cto_id,
                              "scope": {"cto_id": cto_id,
                                        "cto_name": cto_names.get(cto_id),
                                        "offline": len(offline),
                                        "linked": len(rows)},
                              "evidence": [{"sn": o["sn"], "status": o.get("status")}
                                           for o in offline[:20]],
                              "window_h": 0, "threshold": 3})
            bad_sig = []
            for o in rows:
                try:
                    if float(o.get("signal_1490")) < -27:
                        bad_sig.append(o)
                except (TypeError, ValueError):
                    pass
            if len(bad_sig) >= 3:
                cands.append({"kind": "optical_loss", "scope_id": cto_id,
                              "scope": {"cto_id": cto_id,
                                        "cto_name": cto_names.get(cto_id),
                                        "bad_signal": len(bad_sig),
                                        "linked": len(rows)},
                              "evidence": [{"sn": o["sn"],
                                            "signal_1490": o.get("signal_1490")}
                                           for o in bad_sig[:20]],
                              "window_h": 0, "threshold": 3})
    return cands


def _probability(kind: str, n: int, threshold: int) -> int:
    base = {"cto_cluster": 60, "neighborhood_cluster": 55, "onu_offline": 72,
            "optical_loss": 65, "slow_cluster": 55, "reincidence": 58,
            "cto_chronic": 62, "region_trend": 55}.get(kind, 55)
    return min(96, base + 8 * max(0, n - threshold))


# ---------------------------------------------------------------------------
# Criação/atualização do incidente + ações automáticas
# ---------------------------------------------------------------------------
async def _create_collective_ticket(company: str, inc: dict) -> Optional[str]:
    """Cria a bolha CRÍTICA (OS coletiva) na Lousa, atribuída ao técnico
    com mais chamados na evidência (escolha por dado real)."""
    ev = inc.get("evidence") or []
    tech_count: Dict[str, int] = defaultdict(int)
    for e in ev:
        if e.get("assigned_collaborator_id"):
            tech_count[e["assigned_collaborator_id"]] += 1
    tech_id = max(tech_count, key=tech_count.get) if tech_count else None
    if not tech_id:
        c = await db.collaborators.find_one(
            {"company_id": company, "role": {"$regex": "tec", "$options": "i"}},
            {"_id": 0, "id": 1})
        tech_id = (c or {}).get("id")
    scope = inc["scope"]
    where = scope.get("cto_name") or scope.get("cto_id") or scope.get("neighborhood") or "região"
    relato = (f"INCIDENTE COLETIVO detectado pela Isabella — "
              f"{KIND_LABEL.get(inc['kind'], inc['kind'])}. "
              f"{inc['evidence_count']} ocorrência(s) | "
              f"~{inc['affected_clients_estimated']} cliente(s) na área | "
              f"criticidade {inc['criticality_score']}/100 | "
              f"probabilidade {inc['probability']}%. "
              f"Recomendação: {inc['recommendation']}")
    tid = f"tkt-{uuid.uuid4().hex[:10]}"
    sched = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": tid, "company_id": company,
        "client_id": f"inc-{inc['id']}",
        "client_snapshot": {
            "id": f"inc-{inc['id']}",
            "name": f"INCIDENTE COLETIVO · {where}",
            "address": where,
            "neighborhood": scope.get("neighborhood") or "",
            "phone": "", "relato": relato,
        },
        "type": "reparo", "priority": "alta",
        "is_collective": True, "incident_id": inc["id"],
        "category": "INCIDENTE",
        "scheduled_time": sched, "position": -1,
        "status": "pendente",
        "assigned_collaborator_id": tech_id,
        "company": company,
        "opened_at": None, "closed_at": None,
        "whatsapp_status": "nao_enviado",
        "needs_manager_action": False,
        "isabella": {
            "priority_rank": 1, "score": 100.0, "risk": "alto",
            "analysis": relato,
            "prediction": f"Resolver na origem evita ~{inc['affected_clients_estimated']} chamados",
            "updated_at": _now_iso(), "by": "isabella_incident",
        },
        "created_at": _now_iso(), "created_by": "isabella_incident",
    }
    await db.tickets.insert_one(doc)
    return tid


async def _upsert_incident(company: str, cand: dict, arpu: float) -> dict:
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=INCIDENT_TTL_H)).isoformat()
    existing = await db.isabella_incidents.find_one(
        {"company_id": company, "kind": cand["kind"],
         "scope_id": cand["scope_id"], "status": {"$in": list(OPEN_STATUSES)},
         "created_at": {"$gte": cutoff}}, {"_id": 0})

    ev = cand["evidence"]
    n = len(ev)
    prob = _probability(cand["kind"], n, cand["threshold"])
    scope = cand["scope"]
    if scope.get("cto_id"):
        affected = await _affected_clients_cto(company, scope["cto_id"])
    else:
        affected = await _affected_clients_neighborhood(
            company, scope.get("neighborhood") or cand["scope_id"])
    affected = max(affected, n)
    criticality = min(100, round(prob * 0.6 + min(affected, 60) * 0.4 + n * 2))
    churn_factor = 0.15 if criticality >= 80 else 0.08
    clients_at_risk = max(1, round(affected * churn_factor))
    revenue_at_risk = round(affected * arpu, 2)
    churn_brl = round(clients_at_risk * arpu * 12, 2)  # 12 meses de receita
    where = (scope.get("cto_name") or scope.get("cto_id")
             or scope.get("neighborhood") or cand["scope_id"])
    recommendation = (
        f"Despachar equipe para {where} e tratar a CAUSA na origem "
        f"(1 OS coletiva em vez de {affected} chamados individuais). "
        f"Validar fonte/splitter/tronco antes de atender porta a porta.")
    client_ids = sorted({e.get("client_id") for e in ev if e.get("client_id")})
    ticket_ids = sorted({e.get("id") for e in ev if e.get("id")})
    status = "confirmed" if (prob >= 85 or n >= cand["threshold"] + 2) else "predicted"

    if existing:
        merged_clients = sorted(set(existing.get("affected_client_ids") or [])
                                | set(client_ids))
        await db.isabella_incidents.update_one(
            {"id": existing["id"]},
            {"$set": {"evidence": ev[:50], "evidence_count": n,
                      "probability": prob, "criticality_score": criticality,
                      "affected_clients_estimated": affected,
                      "churn_risk": {"clients_at_risk": clients_at_risk,
                                     "annual_revenue_at_risk_brl": churn_brl},
                      "financial_impact": {"monthly_revenue_at_risk_brl": revenue_at_risk,
                                           "arpu_brl": arpu},
                      "affected_client_ids": merged_clients,
                      "evidence_ticket_ids": ticket_ids,
                      "updated_at": _now_iso()}})
        updated = await db.isabella_incidents.find_one(
            {"id": existing["id"]}, {"_id": 0})
        if status == "confirmed" and existing.get("status") == "predicted":
            await db.isabella_incidents.update_one(
                {"id": existing["id"]}, {"$set": {"status": "confirmed"}})
            updated["status"] = "confirmed"
            await _emit(EventType.INCIDENT_CONFIRMED, company, {
                "incident_id": existing["id"], "kind": cand["kind"],
                "scope": scope, "evidence_count": n, "probability": prob})
        updated["_is_new"] = False
        return updated

    inc_id = f"inc-{uuid.uuid4().hex[:10]}"
    inc = {
        "id": inc_id, "company_id": company,
        "kind": cand["kind"], "kind_label": KIND_LABEL.get(cand["kind"]),
        "scope_id": cand["scope_id"], "scope": scope,
        "window_h": cand["window_h"],
        "evidence": ev[:50], "evidence_count": n,
        "evidence_ticket_ids": ticket_ids,
        "affected_client_ids": client_ids,
        "probability": prob, "criticality_score": criticality,
        "affected_clients_estimated": affected,
        "churn_risk": {"clients_at_risk": clients_at_risk,
                       "annual_revenue_at_risk_brl": churn_brl},
        "financial_impact": {"monthly_revenue_at_risk_brl": revenue_at_risk,
                             "arpu_brl": arpu},
        "recommendation": recommendation,
        "status": status,
        "collective_ticket_id": None,
        "created_at": _now_iso(), "updated_at": _now_iso(),
        "detected_by": "isabella_incident",
    }
    # Bolha coletiva na Lousa
    try:
        inc["collective_ticket_id"] = await _create_collective_ticket(company, inc)
    except Exception as e:
        logger.warning("[isabella_incident] bolha coletiva fail: %s", e)
    await db.isabella_incidents.insert_one(dict(inc))
    inc.pop("_id", None)

    # Eventos auditáveis → Presidente IA / Rede IA
    base_payload = {"incident_id": inc_id, "kind": cand["kind"],
                    "scope": scope, "evidence_count": n,
                    "probability": prob, "criticality": criticality,
                    "affected_clients_estimated": affected,
                    "collective_ticket_id": inc["collective_ticket_id"]}
    await _emit(EventType.INCIDENT_PREDICTED, company, base_payload)
    if scope.get("cto_id"):
        await _emit(EventType.INCIDENT_CTO_CLUSTER, company, base_payload)
    if scope.get("neighborhood"):
        await _emit(EventType.INCIDENT_NEIGHBORHOOD_CLUSTER, company,
                    base_payload)
    if status == "confirmed":
        await _emit(EventType.INCIDENT_CONFIRMED, company, base_payload)
    if criticality >= 80 or clients_at_risk >= 5:
        await _emit(EventType.INCIDENT_CHURN_RISK, company, {
            **base_payload, "clients_at_risk": clients_at_risk,
            "annual_revenue_at_risk_brl": churn_brl})
    if affected >= 8:
        await _emit(EventType.INCIDENT_MASS_REPAIR, company, base_payload)

    # Notificação ao gestor
    try:
        await db.notifications.insert_one({
            "id": f"notif-{uuid.uuid4().hex[:10]}", "company_id": company,
            "type": "isabella_incident", "severity": "critical",
            "title": f"Isabella: incidente coletivo {status} — {where}",
            "body": (f"{KIND_LABEL.get(cand['kind'])}: {n} ocorrência(s), "
                     f"~{affected} clientes na área, criticidade "
                     f"{criticality}/100, probabilidade {prob}%. "
                     f"Receita mensal em risco: R$ {revenue_at_risk:.2f}. "
                     f"OS coletiva criada na Lousa."),
            "incident_id": inc_id,
            "ticket_id": inc["collective_ticket_id"],
            "target_roles": ["gestor", "administrador"], "read_by": [],
            "created_at": _now_iso(),
        })
    except Exception:
        pass
    inc["_is_new"] = True
    return inc


async def detect_company(company: str) -> Dict[str, Any]:
    """Varredura completa das 8 regras. Retorna incidentes novos/atualizados."""
    arpu = await _arpu(company)
    cands = await _rule_candidates(company)
    new, updated = [], []
    for cand in cands:
        inc = await _upsert_incident(company, cand, arpu)
        (new if inc.pop("_is_new", False) else updated).append(
            {k: inc[k] for k in ("id", "kind", "scope", "status",
                                 "evidence_count", "probability",
                                 "criticality_score",
                                 "affected_clients_estimated",
                                 "collective_ticket_id")})
    return {"company_id": company, "candidates": len(cands),
            "new_incidents": new, "updated_incidents": updated,
            "scanned_at": _now_iso()}


# ---------------------------------------------------------------------------
# Trava de reparos individuais da mesma causa (agrupamento no incidente)
# ---------------------------------------------------------------------------
async def incident_block_for_new_repair(company: str, client_name: str,
                                        pppoe_user: str,
                                        neighborhood: str) -> Optional[dict]:
    """Se há incidente coletivo ABERTO cobrindo a CTO/bairro do cliente,
    agrupa o cliente no incidente e retorna o incidente (criação bloqueada)."""
    if not await _toggle_block(company):
        return None
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=INCIDENT_TTL_H)).isoformat()
    sub = None
    if pppoe_user:
        sub = await db.subscribers.find_one(
            {"company_id": company, "pppoe_user": pppoe_user},
            {"_id": 0, "id": 1, "name": 1})
    if not sub and client_name:
        sub = await db.subscribers.find_one(
            {"company_id": company,
             "name": {"$regex": f"^{re.escape(client_name.strip())}$",
                      "$options": "i"}},
            {"_id": 0, "id": 1, "name": 1})
    inc = None
    if sub:
        port = await db.cto_ports.find_one(
            {"company_id": company, "subscriber_id": sub["id"],
             "status": "occupied"}, {"_id": 0, "cto_id": 1})
        if port:
            inc = await db.isabella_incidents.find_one(
                {"company_id": company, "scope.cto_id": port["cto_id"],
                 "status": {"$in": list(OPEN_STATUSES)},
                 "created_at": {"$gte": cutoff}}, {"_id": 0})
    if not inc and neighborhood:
        inc = await db.isabella_incidents.find_one(
            {"company_id": company,
             "scope.neighborhood": {"$regex": f"^{re.escape(neighborhood.strip())}$",
                                    "$options": "i"},
             "status": {"$in": list(OPEN_STATUSES)},
             "created_at": {"$gte": cutoff}}, {"_id": 0})
    if not inc:
        return None
    # Agrupa o cliente no incidente
    grouped = {"name": client_name, "pppoe_user": pppoe_user,
               "client_id": (sub or {}).get("id"), "grouped_at": _now_iso()}
    await db.isabella_incidents.update_one(
        {"id": inc["id"]},
        {"$push": {"grouped_clients": grouped},
         "$set": {"updated_at": _now_iso()},
         **({"$addToSet": {"affected_client_ids": sub["id"]}} if sub else {})})
    n_grouped = len(inc.get("grouped_clients") or []) + 1
    if n_grouped >= 3:
        await _emit(EventType.INCIDENT_MASS_REPAIR, company, {
            "incident_id": inc["id"], "kind": inc["kind"],
            "scope": inc["scope"], "grouped_clients": n_grouped})
    return inc


# ---------------------------------------------------------------------------
# Feed para a Rede IA + worker periódico
# ---------------------------------------------------------------------------
async def network_feed(company: str) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    incs = await db.isabella_incidents.find(
        {"company_id": company, "created_at": {"$gte": cutoff}},
        {"_id": 0, "evidence": 0}).sort("criticality_score", -1).to_list(100)
    suspect_ctos, suspect_regions, suspect_onus = [], [], []
    for i in incs:
        sc = i.get("scope") or {}
        if sc.get("cto_id"):
            suspect_ctos.append({"cto_id": sc["cto_id"],
                                 "cto_name": sc.get("cto_name"),
                                 "kind": i["kind"], "status": i["status"],
                                 "criticality": i["criticality_score"]})
        if sc.get("neighborhood"):
            suspect_regions.append({"neighborhood": sc["neighborhood"],
                                    "kind": i["kind"], "status": i["status"],
                                    "criticality": i["criticality_score"]})
        for tid in (i.get("evidence_ticket_ids") or [])[:5]:
            pass
    # ONUs suspeitas reais: offline ou sinal ruim vinculadas a CTOs suspeitas
    cto_ids = [c["cto_id"] for c in suspect_ctos]
    if cto_ids:
        sn_rows = await db.cto_ports.find(
            {"company_id": company, "cto_id": {"$in": cto_ids},
             "sn": {"$nin": [None, "", "None"]}},
            {"_id": 0, "sn": 1, "cto_id": 1}).to_list(2000)
        sns = [r["sn"] for r in sn_rows]
        if sns:
            bad = await db.smartolt_onus.find(
                {"company_id": company, "sn": {"$in": sns},
                 "$or": [{"status": {"$ne": "Online"}},
                         {"signal_text": {"$in": ["Warning", "Critical"]}}]},
                {"_id": 0, "sn": 1, "status": 1, "signal_1490": 1,
                 "signal_text": 1}).to_list(500)
            suspect_onus = bad[:100]
    trend = {
        "open_incidents": sum(1 for i in incs if i["status"] in OPEN_STATUSES),
        "confirmed": sum(1 for i in incs if i["status"] == "confirmed"),
        "degradation": ("alta" if any(i["criticality_score"] >= 80 for i in incs)
                        else ("media" if incs else "baixa")),
    }
    return {"suspect_ctos": suspect_ctos, "suspect_regions": suspect_regions,
            "suspect_onus": suspect_onus, "trend": trend,
            "incidents": incs[:30], "generated_at": _now_iso()}


# ---------------------------------------------------------------------------
# Mass-notify clientes agrupados (CTO 02/2026)
# ---------------------------------------------------------------------------
async def mass_notify_incident(company: str, incident_id: str, *,
                                phase: str = "update",
                                custom_text: Optional[str] = None,
                                actor: Optional[str] = None) -> Dict[str, Any]:
    """Dispara WhatsApp a todos os clientes agrupados em um incidente.

    `phase` controla template:
      • opened    → comunica detecção e ação
      • update    → atualiza status (em atendimento)
      • resolved  → comunica resolução + cortesia/pedido de desculpa
      • custom    → usa `custom_text`
    """
    from services.wa_dispatcher import send_text
    inc = await db.isabella_incidents.find_one(
        {"id": incident_id, "company_id": company}, {"_id": 0})
    if not inc:
        return {"ok": False, "reason": "not_found"}

    affected_ids = set(inc.get("affected_client_ids") or [])
    for g in (inc.get("grouped_clients") or []):
        if g.get("client_id"):
            affected_ids.add(g["client_id"])
    if not affected_ids:
        return {"ok": True, "sent": 0, "skipped": 0,
                "reason": "no_affected_clients"}

    subs = await db.subscribers.find(
        {"company_id": company, "id": {"$in": list(affected_ids)},
         "phone": {"$nin": [None, ""]}},
        {"_id": 0, "id": 1, "name": 1, "phone": 1}).to_list(5000)

    # Reconciliação para IDs legados: alguns incidentes guardaram
    # `affected_client_ids` como `tickets.client_id` (UUID antigo) em vez
    # de `subscribers.id`. Resolvemos via tickets → cto_ports → subscribers.
    found_ids = {s["id"] for s in subs}
    missing = [cid for cid in affected_ids if cid not in found_ids]
    if missing:
        # Tenta resolver via evidence_ticket_ids armazenados no incidente
        ev_ticket_ids = inc.get("evidence_ticket_ids") or []
        if ev_ticket_ids:
            tk = await db.tickets.find(
                {"company_id": company, "id": {"$in": ev_ticket_ids}},
                {"_id": 0, "client_snapshot": 1,
                 "atlaz_id_assinante": 1}).to_list(5000)
            atlaz_ids: List[Any] = []
            phones_in_ticket: List[Dict[str, Any]] = []
            for t in tk:
                if t.get("atlaz_id_assinante"):
                    atlaz_ids.append(t["atlaz_id_assinante"])
                cs = t.get("client_snapshot") or {}
                if cs.get("phone"):
                    phones_in_ticket.append({
                        "id": f"legacy-{uuid.uuid4().hex[:8]}",
                        "name": cs.get("name") or "cliente",
                        "phone": cs["phone"]})
            # Subscribers via atlaz_id_assinante (str/int normalizados)
            if atlaz_ids:
                str_ids = [str(a) for a in atlaz_ids]
                int_ids = []
                for a in atlaz_ids:
                    try:
                        int_ids.append(int(a))
                    except (TypeError, ValueError):
                        pass
                ext_codes = list({s for s in (
                    [str(a) for a in atlaz_ids]
                    + [f"ATLAZ-{a}" for a in atlaz_ids])})
                extra_subs = await db.subscribers.find(
                    {"company_id": company,
                     "external_code": {"$in": ext_codes},
                     "phone": {"$nin": [None, ""]}},
                    {"_id": 0, "id": 1, "name": 1, "phone": 1}
                ).to_list(5000)
                for es in extra_subs:
                    if es["id"] not in found_ids:
                        subs.append(es)
                        found_ids.add(es["id"])
            # Fallback final: telefones recuperados do client_snapshot
            for p in phones_in_ticket:
                if p["id"] not in found_ids:
                    subs.append(p)
                    found_ids.add(p["id"])
    # Deduplica por telefone
    seen_phones = set()
    dedup: List[Dict[str, Any]] = []
    for s in subs:
        ph = s.get("phone")
        if not ph or ph in seen_phones:
            continue
        seen_phones.add(ph)
        dedup.append(s)
    subs = dedup

    where = (inc.get("scope") or {}).get("cto_name") \
            or (inc.get("scope") or {}).get("neighborhood") \
            or inc.get("scope_id") or "sua região"

    base_msgs = {
        "opened": (
            "Olá {nome}, é a {empresa}. Identificamos uma instabilidade na "
            "região de {where} e nossa equipe já está atuando. "
            "Você será atualizado em breve. — Isabella, Atendimento."),
        "update": (
            "Olá {nome}, segue atualização: equipe técnica trabalhando "
            "no incidente que afeta {where}. Previsão de retorno em breve."),
        "resolved": (
            "Olá {nome}, o incidente que afetou {where} foi resolvido. "
            "Caso ainda perceba instabilidade, responda esta mensagem com "
            "‘OFF’ que abrimos visita prioritária. Obrigado pela paciência."),
    }
    template = custom_text or base_msgs.get(phase) or base_msgs["update"]
    company_doc = await db.companies.find_one({"id": company},
                                               {"_id": 0, "name": 1})
    company_name = (company_doc or {}).get("name") or "Ligo"

    sent, skipped = 0, 0
    log_items: List[Dict[str, Any]] = []
    for s in subs:
        phone = s.get("phone")
        if not phone:
            skipped += 1
            continue
        text = template.format(
            nome=(s.get("name") or "cliente").split(" ")[0].title(),
            empresa=company_name, where=where)
        r = await send_text(company_id=company, to=phone, text=text)
        if r.get("ok"):
            sent += 1
        else:
            skipped += 1
        log_items.append({"client_id": s["id"],
                            "phone": phone,
                            "ok": bool(r.get("ok")),
                            "reason": r.get("reason")})

    # registro auditável
    notify_doc = {
        "id": f"incnotify-{uuid.uuid4().hex[:10]}",
        "company_id": company,
        "incident_id": incident_id,
        "phase": phase,
        "sent": sent, "skipped": skipped,
        "actor": actor,
        "items": log_items[:200],
        "created_at": _now_iso(),
    }
    await db.isabella_incident_notifications.insert_one(dict(notify_doc))
    await db.isabella_incidents.update_one(
        {"id": incident_id},
        {"$push": {"mass_notifications": {
            "phase": phase, "sent": sent, "skipped": skipped,
            "actor": actor, "at": _now_iso()}}})
    await _emit(EventType.INCIDENT_MASS_NOTIFY, company, {
        "incident_id": incident_id, "phase": phase,
        "sent": sent, "skipped": skipped})
    notify_doc.pop("_id", None)
    return {"ok": True, **notify_doc}


async def isabella_incident_worker() -> None:
    """Varredura automática a cada 15 min em empresas com reparos recentes."""
    await asyncio.sleep(60)  # deixa o boot terminar
    logger.info("[isabella_incident] worker iniciado (a cada %ss)",
                SCAN_INTERVAL_SEC)
    while True:
        try:
            cutoff = (datetime.now(timezone.utc)
                      - timedelta(hours=48)).isoformat()
            companies = await db.tickets.distinct(
                "company_id", {"type": "reparo",
                               "created_at": {"$gte": cutoff}})
            for company in companies:
                try:
                    res = await detect_company(company)
                    if res["new_incidents"]:
                        logger.info("[isabella_incident] %s: %d novo(s)",
                                    company, len(res["new_incidents"]))
                except Exception as e:
                    logger.warning("[isabella_incident] scan %s: %s",
                                   company, e)
        except Exception as e:
            logger.exception("[isabella_incident] worker loop: %s", e)
        await asyncio.sleep(SCAN_INTERVAL_SEC)
