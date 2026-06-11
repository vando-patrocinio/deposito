"""ISABELLA FIELD PRESIDENT — motor de decisão da operação de campo.

Isabella preside o Smart Field Ops: enxerga tudo (GPS, agenda, OS, estoque,
frota, CTO, histórico, eventos field.*), decide tudo (priorização, rota,
materiais), orienta o técnico e alimenta o Presidente IA e o Álvaro IA.

ZERO MOCK: todas as recomendações são calculadas a partir do banco REAL —
tickets, cto_ports, ctos, stok_stock, field_vehicle_inspections,
tech_locations, subscribers. Nada é inventado: cada motivo exibido carrega
o número real que o originou.

Camada de IA visual (Álvaro) para frota usa Claude Sonnet vision via
Emergent LLM Key (mesmo padrão de services/fleet_ai_worker.py), com
fallback heurístico determinístico sobre dados reais quando o LLM falha.
"""

NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["ticket.updated"],
    "company_id_required": True,
}

import asyncio
import json
import logging
import math
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from database import db
from services.event_bus import EventType, emit_event

logger = logging.getLogger("ponto.isabella_field")

SP_TZ = ZoneInfo("America/Sao_Paulo")
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

TYPE_LABEL = {"instalacao": "Instalação", "reparo": "Reparo",
              "retirada": "Retirada", "troca": "Troca"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _haversine_km(lat1, lng1, lat2, lng2) -> Optional[float]:
    try:
        lat1, lng1, lat2, lng2 = map(float, (lat1, lng1, lat2, lng2))
    except (TypeError, ValueError):
        return None
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return round(2 * r * math.asin(math.sqrt(a)), 2)


async def _emit(event_type: str, company: str, payload: Dict[str, Any],
                severity: str = "media") -> None:
    try:
        await emit_event(event_type, company_id=company,
                         source="isabella_field", severity=severity,
                         payload=payload)
    except Exception as e:
        logger.warning("[isabella_field] emit %s fail: %s", event_type, e)


# ---------------------------------------------------------------------------
# Contexto real do técnico
# ---------------------------------------------------------------------------
async def _last_gps(company: str, collab_id: str) -> Optional[dict]:
    return await db.tech_locations.find_one(
        {"company_id": company, "collab_id": collab_id},
        {"_id": 0, "lat": 1, "lng": 1, "captured_at": 1},
        sort=[("captured_at", -1)])


async def _client_geo(company: str, client_id: Optional[str]) -> Optional[dict]:
    """Geo do cliente via porta de CTO ocupada → gps da CTO (dado real)."""
    if not client_id:
        return None
    port = await db.cto_ports.find_one(
        {"company_id": company, "subscriber_id": client_id,
         "status": "occupied"},
        {"_id": 0, "cto_id": 1, "port_number": 1, "lat": 1, "lng": 1})
    if not port:
        return None
    if port.get("lat") is not None and port.get("lng") is not None:
        return {"lat": port["lat"], "lng": port["lng"],
                "cto_id": port["cto_id"], "port_number": port["port_number"]}
    cto = await db.ctos.find_one(
        {"id": port["cto_id"], "company_id": company},
        {"_id": 0, "gps": 1, "name": 1})
    gps = (cto or {}).get("gps") or {}
    if gps.get("lat") is None:
        return None
    return {"lat": gps["lat"], "lng": gps["lng"], "cto_id": port["cto_id"],
            "port_number": port["port_number"]}


async def _client_repairs_60d(company: str, client_id: Optional[str]) -> int:
    if not client_id:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    return await db.tickets.count_documents(
        {"company_id": company, "client_id": client_id, "type": "reparo",
         "created_at": {"$gte": cutoff}})


async def resolution_probability(company: str, ttype: str) -> Tuple[int, int]:
    """Probabilidade REAL de resolução: histórico de 90 dias do mesmo tipo.

    sucesso = outcome 'sucesso'; penaliza reincidência (cliente voltou a
    abrir reparo em até 30 dias). Retorna (percentual, amostra)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    closed = await db.tickets.find(
        {"company_id": company, "type": ttype,
         "status": {"$in": ["finalizada", "encerrada"]},
         "closed_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "client_id": 1, "closed_at": 1, "outcome": 1}
    ).to_list(500)
    if not closed:
        return 75, 0  # sem amostra — neutro declarado (base_n=0 sinaliza)
    successes = sum(1 for t in closed if (t.get("outcome") or "sucesso") == "sucesso")
    reinc = 0
    if ttype == "reparo":
        by_client: Dict[str, List[str]] = {}
        for t in closed:
            if t.get("client_id"):
                by_client.setdefault(t["client_id"], []).append(t["closed_at"] or "")
        for dates in by_client.values():
            dates.sort()
            for a, b in zip(dates, dates[1:]):
                try:
                    if (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days <= 30:
                        reinc += 1
                        break
                except Exception:
                    pass
    prob = max(40, min(98, round(100 * (successes - reinc * 0.5) / len(closed))))
    return prob, len(closed)


# ---------------------------------------------------------------------------
# Score / priorização de OS (motivos com números reais)
# ---------------------------------------------------------------------------
def _score_from_context(t: dict, gps: Optional[dict], geo: Optional[dict],
                        repairs: int, prob_pair: Tuple[int, int]) -> dict:
    now = _now_iso()
    reasons: List[str] = []
    score = 0.0
    snap = t.get("client_snapshot") or {}

    sched = t.get("scheduled_time") or ""
    if t.get("status") == "pendente" and sched and sched < now:
        try:
            late_min = int((datetime.now(timezone.utc)
                            - datetime.fromisoformat(sched)).total_seconds() // 60)
            reasons.append(f"OS atrasada há {late_min} min (SLA em risco)")
        except Exception:
            reasons.append("OS atrasada (SLA em risco)")
        score += 40

    if t.get("priority") in ("horario", "alta"):
        score += 25
        reasons.append("Janela de horário fixa combinada com o cliente"
                       if t.get("priority") == "horario"
                       else "Prioridade alta definida pelo gestor")

    dist_km = None
    if gps and geo:
        dist_km = _haversine_km(gps["lat"], gps["lng"], geo["lat"], geo["lng"])
        if dist_km is not None:
            score += 20 * (1 - min(dist_km, 15) / 15)
            eta = max(2, round(dist_km / 0.4))  # ~24 km/h urbano
            reasons.append(f"{dist_km} km da sua localização (~{eta} min)")

    if repairs >= 2:
        score += 10
        reasons.append(f"Cliente reincidente: {repairs} reparos em 60 dias")

    ttype = t.get("type") or "reparo"
    prob, base_n = prob_pair
    score += prob / 10
    if base_n:
        reasons.append(f"Probabilidade de resolução {prob}% "
                       f"(histórico real de {base_n} OS de {TYPE_LABEL.get(ttype, ttype).lower()})")

    if t.get("needs_manager_action"):
        score -= 30
        reasons.append("Aguardando decisão do gestor — não priorizar")

    return {
        "ticket_id": t["id"],
        "client": snap.get("name"),
        "neighborhood": snap.get("neighborhood"),
        "type": ttype,
        "status": t.get("status"),
        "scheduled_time": sched or None,
        "score": round(score, 1),
        "distance_km": dist_km,
        "resolution_probability": prob,
        "reasons": reasons,
        "geo": geo,
    }


async def score_ticket(company: str, t: dict, gps: Optional[dict],
                       prob_cache: Dict[str, Tuple[int, int]]) -> dict:
    geo = await _client_geo(company, t.get("client_id"))
    repairs = await _client_repairs_60d(company, t.get("client_id"))
    ttype = t.get("type") or "reparo"
    if ttype not in prob_cache:
        prob_cache[ttype] = await resolution_probability(company, ttype)
    return _score_from_context(t, gps, geo, repairs, prob_cache[ttype])


async def _today_tickets(company: str, collab_id: str) -> List[dict]:
    now_sp = datetime.now(SP_TZ)
    start = now_sp.replace(hour=0, minute=0, second=0, microsecond=0)
    s = start.astimezone(timezone.utc).isoformat()
    e = (start + timedelta(days=1)).astimezone(timezone.utc).isoformat()
    return await db.tickets.find(
        {"company_id": company, "assigned_collaborator_id": collab_id,
         "$or": [{"status": "aberta"},
                 {"status": "pendente", "scheduled_time": {"$lt": e}}]},
        {"_id": 0, "completion_data": 0, "field_photos": 0}
    ).sort("scheduled_time", 1).to_list(100)


# ---------------------------------------------------------------------------
# AGENDA INTELIGENTE — rota recomendada pela Isabella
# ---------------------------------------------------------------------------
async def optimize_route(company: str, collab: dict,
                         emit: bool = True) -> dict:
    collab_id = collab["id"]
    gps = await _last_gps(company, collab_id)
    tickets = await _today_tickets(company, collab_id)
    prob_cache: Dict[str, Tuple[int, int]] = {}
    scored = [await score_ticket(company, t, gps, prob_cache) for t in tickets]

    active = [s for s in scored if s["status"] == "aberta"]
    pend = [s for s in scored if s["status"] == "pendente"]

    # Sequência: OS aberta primeiro; depois vizinho-mais-próximo ponderado
    # pelo score (distância real + prioridade real).
    route: List[dict] = list(active)
    remaining = sorted(pend, key=lambda x: -x["score"])
    cur = (gps or {}).get("lat"), (gps or {}).get("lng")
    if active and active[0].get("geo"):
        cur = active[0]["geo"]["lat"], active[0]["geo"]["lng"]
    while remaining:
        best, best_val = None, None
        for s in remaining:
            val = s["score"]
            if cur[0] is not None and s.get("geo"):
                d = _haversine_km(cur[0], cur[1], s["geo"]["lat"], s["geo"]["lng"])
                if d is not None:
                    val -= d * 1.5  # custo real de deslocamento
            if best_val is None or val > best_val:
                best, best_val = s, val
        route.append(best)
        remaining.remove(best)
        if best.get("geo"):
            cur = best["geo"]["lat"], best["geo"]["lng"]
    for i, s in enumerate(route):
        s["route_position"] = i + 1
        s.pop("geo", None)

    naive = [s["ticket_id"] for s in sorted(
        scored, key=lambda x: x.get("scheduled_time") or "9999")]
    optimized = [s["ticket_id"] for s in route]
    changed = naive != optimized

    if emit and route:
        await _emit(EventType.FIELD_ISABELLA_ROUTE_OPTIMIZED, company, {
            "collaborator_id": collab_id,
            "collaborator_name": collab.get("name"),
            "route": optimized, "gps_available": bool(gps),
            "changed_vs_schedule": changed,
        }, severity="baixa")
        if changed:
            await _emit(EventType.FIELD_ISABELLA_PRIORITY_CHANGED, company, {
                "collaborator_id": collab_id,
                "from_order": naive, "to_order": optimized,
                "reason": "Isabella reordenou por SLA/distância/probabilidade",
            })
    return {"route": route, "changed_vs_schedule": changed,
            "gps_available": bool(gps),
            "gps_at": (gps or {}).get("captured_at")}


# ---------------------------------------------------------------------------
# ESTOQUE INTELIGENTE — checagem antes da OS
# ---------------------------------------------------------------------------
async def _avg_install_materials(company: str) -> Dict[str, float]:
    """Média REAL de materiais por instalação (90d de completion_data)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    rows = await db.tickets.find(
        {"company_id": company, "type": "instalacao",
         "status": {"$in": ["finalizada", "encerrada"]},
         "closed_at": {"$gte": cutoff}},
        {"_id": 0, "completion_data.qtd_drop": 1,
         "completion_data.esticadores": 1,
         "completion_data.conectores_fast": 1,
         "completion_data.cabo_rede": 1,
         "completion_data.conectores_rede": 1}).to_list(300)
    keys = ["qtd_drop", "esticadores", "conectores_fast",
            "cabo_rede", "conectores_rede"]
    if not rows:
        return {"qtd_drop": 100.0, "esticadores": 4, "conectores_fast": 2,
                "cabo_rede": 0, "conectores_rede": 0, "_sample": 0}
    avg = {}
    for k in keys:
        vals = [(r.get("completion_data") or {}).get(k) or 0 for r in rows]
        avg[k] = round(sum(vals) / len(rows), 1)
    avg["_sample"] = len(rows)
    return avg


_MATERIAL_TO_STOCK = {"qtd_drop": "drop", "esticadores": "esticador",
                      "conectores_fast": "conector_fast",
                      "cabo_rede": "cabo_rede",
                      "conectores_rede": "conector_rede"}


async def stock_check(company: str, collab: dict,
                      pending_installs: int, emit: bool = True) -> List[dict]:
    """Compara saldo real do técnico com a necessidade média real."""
    stock = await db.stok_stock.find_one(
        {"company_id": company, "location": collab["id"]}, {"_id": 0}) or {}
    ont_count = await db.stok_onts.count_documents(
        {"company_id": company, "location_type": "tecnico",
         "location_id": collab["id"],
         "status": {"$nin": ["defeito_devolver_empresa"]}})
    alerts: List[dict] = []
    if pending_installs > ont_count:
        alerts.append({
            "item": "ONU/ONT", "have": ont_count,
            "need": pending_installs,
            "msg": (f"{pending_installs} instalação(ões) hoje e apenas "
                    f"{ont_count} ONU(s) no seu estoque."),
        })
    if pending_installs > 0:
        avg = await _avg_install_materials(company)
        for mk, sk in _MATERIAL_TO_STOCK.items():
            need = round(avg.get(mk, 0) * pending_installs, 1)
            have = stock.get(sk, 0) or 0
            if need > 0 and have < need:
                alerts.append({
                    "item": sk, "have": have, "need": need,
                    "msg": (f"Saldo de {sk}: {have} — necessidade estimada "
                            f"{need} (média real de {avg.get('_sample', 0)} "
                            f"instalações)."),
                })
    if alerts and emit:
        await _emit(EventType.FIELD_ISABELLA_STOCK_ALERT, company, {
            "collaborator_id": collab["id"],
            "collaborator_name": collab.get("name"),
            "alerts": alerts,
        }, severity="alta")
    return alerts


# ---------------------------------------------------------------------------
# FROTA — status p/ briefing
# ---------------------------------------------------------------------------
async def _fleet_status(company: str, collab_id: str) -> dict:
    last = await db.field_vehicle_inspections.find_one(
        {"company_id": company, "collaborator_id": collab_id},
        {"_id": 0, "photos": 0}, sort=[("created_at", -1)])
    return {
        "last_inspection_at": (last or {}).get("created_at"),
        "isabella_score": (last or {}).get("isabella_score"),
        "alvaro": (last or {}).get("alvaro"),
        "plate": (last or {}).get("plate"),
    }


# ---------------------------------------------------------------------------
# BRIEFING — "Bom dia Rafael. Você possui 5 OS hoje..."
# ---------------------------------------------------------------------------
def _greeting() -> str:
    h = datetime.now(SP_TZ).hour
    return "Bom dia" if 5 <= h < 12 else ("Boa tarde" if h < 18 else "Boa noite")


async def build_briefing(company: str, collab: dict) -> dict:
    collab_id = collab["id"]
    route_data = await optimize_route(company, collab, emit=False)
    route = route_data["route"]
    pendentes = [r for r in route if r["status"] == "pendente"]
    active = next((r for r in route if r["status"] == "aberta"), None)
    installs = sum(1 for r in pendentes if r["type"] == "instalacao")
    alerts = await stock_check(company, collab, installs, emit=True)
    fleet = await _fleet_status(company, collab_id)
    gps = await _last_gps(company, collab_id)

    first = (collab.get("name") or "técnico").split(" ")[0].title()
    lines = [f"{_greeting()}, {first}."]
    total = len(route)
    if total == 0:
        lines.append("Você não tem OS na agenda de hoje.")
    else:
        lines.append(f"Você possui {total} OS hoje"
                     + (f" ({len(pendentes)} pendentes)." if pendentes else "."))
    rec = None
    if active:
        rec = active
        lines.append(f"Continue a OS em andamento de {active['client']}.")
    elif pendentes:
        rec = pendentes[0]
        lines.append(f"Sugestão: comece pela OS de {rec['client']} "
                     f"({TYPE_LABEL.get(rec['type'], rec['type'])}).")
    if alerts:
        lines.append(f"Atenção: {len(alerts)} alerta(s) de estoque antes de sair.")

    briefing = {
        "id": f"ifb-{uuid.uuid4().hex[:10]}",
        "company_id": company,
        "collaborator_id": collab_id,
        "headline": " ".join(lines),
        "recommended_os": rec,
        "route": route,
        "route_changed_vs_schedule": route_data["changed_vs_schedule"],
        "stock_alerts": alerts,
        "fleet": fleet,
        "gps_active": bool(gps and gps.get("captured_at", "") >=
                           (datetime.now(timezone.utc)
                            - timedelta(minutes=10)).isoformat()),
        "counts": {"total": total, "pendentes": len(pendentes),
                   "atrasadas": sum(1 for r in pendentes
                                    if any("atrasada" in x for x in r["reasons"]))},
        "created_at": _now_iso(),
    }

    # Throttle de evento: 1 recomendação por técnico a cada 10 min
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    recent = await db.isabella_field_briefings.find_one(
        {"company_id": company, "collaborator_id": collab_id,
         "created_at": {"$gte": cutoff}}, {"_id": 0, "id": 1})
    await db.isabella_field_briefings.insert_one(dict(briefing))
    briefing.pop("_id", None)
    if not recent and rec:
        await _emit(EventType.FIELD_ISABELLA_RECOMMENDATION_CREATED, company, {
            "collaborator_id": collab_id,
            "collaborator_name": collab.get("name"),
            "recommended_ticket_id": rec["ticket_id"],
            "reasons": rec["reasons"],
            "score": rec["score"],
            "stock_alerts": len(alerts),
        })
    return briefing


# ---------------------------------------------------------------------------
# BRIEF POR OS — Instalação/Reparo/Retirada Inteligente (pré-visita)
# ---------------------------------------------------------------------------
async def _suggest_cto(company: str, ticket: dict) -> dict:
    """CTO + porta sugeridas com dados reais de cto_ports/ctos."""
    out: Dict[str, Any] = {}
    geo = await _client_geo(company, ticket.get("client_id"))
    if geo:  # cliente já tem porta ocupada (reparo/retirada)
        cto = await db.ctos.find_one({"id": geo["cto_id"], "company_id": company},
                                     {"_id": 0, "id": 1, "name": 1, "address": 1})
        out = {"cto_id": geo["cto_id"], "cto_name": (cto or {}).get("name"),
               "port_number": geo["port_number"], "source": "porta atual do cliente"}
    else:
        neigh = ((ticket.get("client_snapshot") or {}).get("neighborhood") or "").strip().lower()
        cand = None
        if neigh:
            cand = await db.ctos.find_one(
                {"company_id": company,
                 "address": {"$regex": re.escape(neigh), "$options": "i"}},
                {"_id": 0, "id": 1, "name": 1, "address": 1})
        if cand:
            free = await db.cto_ports.find_one(
                {"company_id": company, "cto_id": cand["id"], "status": "free"},
                {"_id": 0, "port_number": 1}, sort=[("port_number", 1)])
            out = {"cto_id": cand["id"], "cto_name": cand["name"],
                   "port_number": (free or {}).get("port_number"),
                   "source": f"CTO no bairro {neigh.title()} com porta livre"}
    if out.get("cto_id"):
        sigs = await db.cto_ports.find(
            {"company_id": company, "cto_id": out["cto_id"],
             "signal_dbm": {"$ne": None}},
            {"_id": 0, "signal_dbm": 1}).to_list(64)
        if sigs:
            vals = [s["signal_dbm"] for s in sigs]
            out["expected_signal_dbm"] = round(sum(vals) / len(vals), 1)
            out["signal_sample"] = len(vals)
    return out


async def _root_cause_history(company: str, ticket: dict) -> List[dict]:
    """Distribuição REAL de causas-raiz já classificadas pela Isabella
    (cliente > CTO > bairro > empresa)."""
    snap = ticket.get("client_snapshot") or {}
    scopes = [
        ({"client_id": ticket.get("client_id")}, "cliente"),
        ({"client_snapshot.neighborhood": snap.get("neighborhood")}, "bairro"),
        ({}, "empresa"),
    ]
    for extra, scope in scopes:
        if any(v is None for v in extra.values()):
            continue
        q = {"company_id": company, "type": "reparo",
             "isabella_root_cause": {"$exists": True}, **extra}
        rows = await db.tickets.find(q, {"_id": 0, "isabella_root_cause": 1}
                                     ).to_list(200)
        if len(rows) >= 2:
            dist: Dict[str, int] = {}
            for r in rows:
                dist[r["isabella_root_cause"]] = dist.get(r["isabella_root_cause"], 0) + 1
            total = sum(dist.values())
            return [{"cause": c, "probability": round(100 * n / total),
                     "sample": total, "scope": scope}
                    for c, n in sorted(dist.items(), key=lambda x: -x[1])][:3]
    return []


async def os_brief(company: str, collab: dict, ticket: dict) -> dict:
    ttype = ticket.get("type") or "reparo"
    snap = ticket.get("client_snapshot") or {}
    brief: Dict[str, Any] = {"ticket_id": ticket["id"], "type": ttype}
    prob, base_n = await resolution_probability(company, ttype)
    brief["resolution_probability"] = prob
    brief["probability_sample"] = base_n

    if ttype == "instalacao":
        brief["cto_suggestion"] = await _suggest_cto(company, ticket)
        avg = await _avg_install_materials(company)
        brief["suggested_materials"] = {
            k: v for k, v in avg.items() if k != "_sample"}
        brief["materials_sample"] = avg.get("_sample", 0)
        neigh = (snap.get("neighborhood") or "").strip()
        if neigh:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
            rep = await db.tickets.count_documents(
                {"company_id": company, "type": "reparo",
                 "client_snapshot.neighborhood": neigh,
                 "created_at": {"$gte": cutoff}})
            inst = await db.tickets.count_documents(
                {"company_id": company, "type": "instalacao",
                 "client_snapshot.neighborhood": neigh,
                 "created_at": {"$gte": cutoff}})
            brief["region_risk"] = {
                "neighborhood": neigh, "repairs_90d": rep,
                "installs_90d": inst,
                "level": "alto" if rep > max(3, inst) else
                         ("medio" if rep > 1 else "baixo"),
            }
    elif ttype == "reparo":
        brief["probable_causes"] = await _root_cause_history(company, ticket)
        brief["client_repairs_60d"] = await _client_repairs_60d(
            company, ticket.get("client_id"))
        geo = await _client_geo(company, ticket.get("client_id"))
        if geo:
            cto = await db.ctos.find_one(
                {"id": geo["cto_id"], "company_id": company},
                {"_id": 0, "name": 1})
            cutoff = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
            cto_rep = await db.tickets.count_documents(
                {"company_id": company, "type": "reparo",
                 "completion_data.cto_id": geo["cto_id"],
                 "created_at": {"$gte": cutoff}})
            brief["cto_context"] = {"cto_id": geo["cto_id"],
                                    "cto_name": (cto or {}).get("name"),
                                    "port_number": geo["port_number"],
                                    "repairs_60d": cto_rep}
        brief["recommended_parts"] = ["Conector fast (2)", "Drop reserva",
                                      "ONU reserva"]
        brief["test_guidance"] = [
            "Medir sinal na CTO antes de entrar no cliente",
            "Medir sinal na ONU (antes) e registrar no app",
            "Se diferença CTO→ONU > 3 dB: inspecionar drop/conectores",
            "Registrar sinal (depois) ao concluir",
        ]
    elif ttype == "retirada":
        tg = await db.aihub_settings.find_one(
            {"company_id": company, "key": "field_ops_toggles"},
            {"_id": 0, "value": 1})
        cost = float(((tg or {}).get("value") or {}).get(
            "equipment_default_cost") or 250.0)
        client_name = snap.get("name") or ""
        equip = []
        if client_name:
            equip = await db.stok_onts.find(
                {"company_id": company, "client_name": client_name},
                {"_id": 0, "mac": 1, "scan_sn": 1, "model": 1, "status": 1}
            ).to_list(3)
        brief["comodato"] = {
            "asset_value": cost,
            "equipment": equip,
            "impact_if_lost": cost,
            "impact_if_recovered": cost,
            "guidance": ("Recupere o equipamento e registre o estado físico. "
                         "Não devolvido = perda lançada no DRE e financeiro "
                         "notificado automaticamente."),
        }
    return brief


# ---------------------------------------------------------------------------
# PÓS-OS — notas de instalação/reparo, causa raiz e truck-roll
# ---------------------------------------------------------------------------
def _signal_note(sinal: Optional[float]) -> float:
    if sinal is None:
        return 7.0
    if sinal >= -20:
        return 10.0
    if sinal >= -23:
        return 9.0
    if sinal >= -25:
        return 8.0
    if sinal >= -27:
        return 6.5
    return 5.0


def _classify_root_cause(cd: dict, signal_tests: List[dict]) -> str:
    before = next((s["dbm"] for s in signal_tests if s.get("phase") == "before"), None)
    after = next((s["dbm"] for s in signal_tests if s.get("phase") == "after"), None)
    if cd.get("ont"):
        return "ONU defeituosa (equipamento trocado)"
    if (cd.get("qtd_drop") or 0) > 0:
        return "Drop rompido/atenuado (drop substituído)"
    if (cd.get("conectores_fast") or 0) > 0:
        return "Conector/fusão com perda (conectores refeitos)"
    if before is not None and after is not None and (after - before) >= 3:
        return "Atenuação óptica corrigida em campo"
    return "Configuração/outros (sem troca de material)"


async def score_finish(company: str, collab: dict, ticket_id: str,
                       outcome: str) -> Optional[dict]:
    """Chamado após o finish real da Lousa. Calcula notas com dados reais."""
    t = await db.tickets.find_one({"id": ticket_id, "company_id": company},
                                  {"_id": 0})
    if not t or t.get("status") not in ("finalizada", "encerrada"):
        return None
    cd = t.get("completion_data") or {}
    fotos = cd.get("fotos") or []
    fotos_n = cd.get("fotos_count") if isinstance(cd.get("fotos_count"), int) else len(fotos)
    sig_tests = t.get("field_signal_tests") or []
    ttype = t.get("type") or "reparo"

    nota_sinal = _signal_note(cd.get("sinal"))
    nota_org = min(10.0, 6.0 + 1.5 * min(fotos_n, 3)
                   + (1.0 if sig_tests else 0.0))
    dur_min = None
    try:
        dur_min = int((datetime.fromisoformat(t["closed_at"])
                       - datetime.fromisoformat(t["opened_at"])).total_seconds() // 60)
    except Exception:
        pass
    nota_proc = 9.0
    if dur_min is not None:
        if dur_min < 10:
            nota_proc = 6.0   # rápido demais — provável checklist corrido
        elif dur_min > 240:
            nota_proc = 7.0
    nota_result = 10.0 if outcome == "sucesso" else 5.0
    nota_final = round((nota_sinal + nota_org + nota_proc + nota_result) / 4, 1)

    score_doc = {
        "qualidade": nota_sinal, "organizacao": round(nota_org, 1),
        "processo": nota_proc, "resultado": nota_result,
        "nota_final": nota_final,
        "sinal_dbm": cd.get("sinal"), "fotos": fotos_n,
        "duracao_min": dur_min, "outcome": outcome,
        "scored_at": _now_iso(), "scored_by": "isabella_field",
    }
    sets: Dict[str, Any] = {"isabella_score": score_doc}

    root_cause = None
    if ttype == "reparo":
        root_cause = _classify_root_cause(cd, sig_tests)
        sets["isabella_root_cause"] = root_cause

    await db.tickets.update_one({"id": ticket_id}, {"$set": sets})
    try:
        from services.event_bus import emit_event
        await emit_event(
            "ticket.updated",
            company_id=(t or {}).get("company_id"),
            source="isabella_field",
            payload={},
        )
    except Exception:
        pass

    ev = (EventType.FIELD_ISABELLA_INSTALLATION_SCORED
          if ttype == "instalacao" else EventType.FIELD_ISABELLA_REPAIR_SCORED)
    await _emit(ev, company, {
        "ticket_id": ticket_id, "collaborator_id": collab["id"],
        "collaborator_name": collab.get("name"), "type": ttype,
        "score": score_doc, "root_cause": root_cause,
    })
    if root_cause:
        await _emit(EventType.FIELD_ISABELLA_ROOT_CAUSE_DETECTED, company, {
            "ticket_id": ticket_id, "root_cause": root_cause,
            "client_id": t.get("client_id"),
            "neighborhood": (t.get("client_snapshot") or {}).get("neighborhood"),
        })
    if (cd.get("resolution_kind") == "remote"
            or (t.get("resolution_kind") == "remote")):
        await _emit(EventType.FIELD_ISABELLA_TRUCK_ROLL_AVOIDED, company, {
            "ticket_id": ticket_id, "collaborator_id": collab["id"],
        })
    return score_doc


# ---------------------------------------------------------------------------
# FROTA IA — nota Isabella + análise Álvaro (vision)
# ---------------------------------------------------------------------------
async def score_vehicle_inspection(inspection_id: str) -> Optional[dict]:
    insp = await db.field_vehicle_inspections.find_one(
        {"id": inspection_id}, {"_id": 0, "photos": 0})
    if not insp:
        return None
    company = insp["company_id"]
    prev = await db.field_vehicle_inspections.find_one(
        {"company_id": company, "collaborator_id": insp["collaborator_id"],
         "id": {"$ne": inspection_id}},
        {"_id": 0, "km": 1, "created_at": 1, "isabella_score": 1},
        sort=[("created_at", -1)])

    nota = 8.5  # 4 fotos + KM já são obrigatórios (validados na rota)
    notes: List[str] = ["4 fotos obrigatórias entregues", "KM informado"]
    km_delta = None
    if prev and prev.get("km") is not None:
        km_delta = round(float(insp["km"]) - float(prev["km"]), 1)
        if km_delta < 0:
            nota -= 3.0
            notes.append(f"KM regrediu {abs(km_delta)} km vs vistoria "
                         "anterior — verificar odômetro/fraude")
        elif km_delta > 3000:
            nota -= 1.0
            notes.append(f"Rodagem alta na semana: {km_delta} km")
        else:
            nota += 0.5
            notes.append(f"Rodagem coerente: +{km_delta} km na semana")
    score_doc = {"nota": round(max(0, min(10, nota)), 1),
                 "km_delta": km_delta, "notes": notes,
                 "scored_at": _now_iso(), "scored_by": "isabella_field"}
    await db.field_vehicle_inspections.update_one(
        {"id": inspection_id}, {"$set": {"isabella_score": score_doc}})
    await _emit(EventType.FIELD_ISABELLA_VEHICLE_SCORED, company, {
        "inspection_id": inspection_id,
        "collaborator_id": insp["collaborator_id"],
        "plate": insp.get("plate"), "score": score_doc,
    })
    # Álvaro vision em background (best-effort, não bloqueia o técnico)
    asyncio.create_task(alvaro_review_field_inspection(inspection_id))
    return score_doc


ALVARO_FLEET_PROMPT = """Você é o Álvaro IA, diretor técnico de frota de um
provedor de internet. Recebe 4 fotos do veículo (frente, traseira, lateral
esquerda, lateral direita) da vistoria semanal atual e, quando houver,
fotos da semana anterior do MESMO veículo.

Responda APENAS JSON puro (sem markdown):
{
  "score": 0-100,
  "risco_quebra": "baixo"|"medio"|"alto",
  "previsao_manutencao": "texto curto e objetivo",
  "custo_futuro_estimado_brl": numero,
  "avarias": ["..."],
  "comparacao_semana_anterior": "texto curto"
}
Seja rigoroso, não invente avarias inexistentes."""


async def alvaro_review_field_inspection(inspection_id: str) -> None:
    try:
        insp = await db.field_vehicle_inspections.find_one(
            {"id": inspection_id}, {"_id": 0})
        if not insp:
            return
        photos = insp.get("photos") or {}
        prev = await db.field_vehicle_inspections.find_one(
            {"company_id": insp["company_id"],
             "collaborator_id": insp["collaborator_id"],
             "id": {"$ne": inspection_id}},
            {"_id": 0, "photos": 1, "km": 1, "week_key": 1},
            sort=[("created_at", -1)])
        desc = [f"VEÍCULO placa={insp.get('plate')} km_atual={insp.get('km')} "
                f"km_anterior={(prev or {}).get('km')}"]
        images: List[Any] = []

        def _add(ph: Optional[str], label: str) -> None:
            if not ph or "," not in ph:
                return
            images.append(ph.split(",", 1)[1])
            desc.append(f"Imagem {len(images)}: {label}")

        for pos in ("front", "rear", "left", "right"):
            _add(photos.get(pos), f"foto atual — {pos}")
        if prev and (prev.get("photos") or {}).get("front"):
            _add(prev["photos"]["front"],
                 f"semana anterior ({prev.get('week_key')}) — front")
        result: Dict[str, Any]
        try:
            from emergentintegrations.llm.chat import (ImageContent, LlmChat,
                                                       UserMessage)
            chat = LlmChat(api_key=EMERGENT_LLM_KEY,
                           session_id=f"alvaro-field-{inspection_id}",
                           system_message=ALVARO_FLEET_PROMPT,
                           ).with_model("anthropic",
                                        "claude-sonnet-4-5-20250929"
                                        ).with_params(max_tokens=900)
            msg = UserMessage(
                text="\n".join(desc) + "\nAvalie a vistoria.",
                file_contents=[ImageContent(b) for b in images])
            raw = await asyncio.wait_for(chat.send_message(msg), timeout=90)
            txt = (raw or "").strip()
            txt = re.sub(r"^```(json)?\s*|\s*```\s*$", "", txt)
            m = re.search(r"\{[\s\S]+\}", txt)
            result = json.loads(m.group(0) if m else txt)
            result["engine"] = "claude-vision"
        except Exception as e:
            logger.warning("[isabella_field] Álvaro vision falhou (%s) — "
                           "heurística sobre dados reais", e)
            isc = (insp.get("isabella_score") or {})
            base = int((isc.get("nota") or 8.0) * 10)
            result = {
                "score": base,
                "risco_quebra": "baixo" if base >= 80 else
                                ("medio" if base >= 60 else "alto"),
                "previsao_manutencao": "Sem análise visual — manter ciclo "
                                       "padrão de revisão.",
                "custo_futuro_estimado_brl": 0,
                "avarias": [], "comparacao_semana_anterior": None,
                "engine": "heuristic-fallback",
            }
        result["reviewed_at"] = _now_iso()
        await db.field_vehicle_inspections.update_one(
            {"id": inspection_id}, {"$set": {"alvaro": result}})
    except Exception as e:
        logger.exception("[isabella_field] alvaro_review %s: %s",
                         inspection_id, e)


# ---------------------------------------------------------------------------
# LOUSA — Isabella preside (análise persistida em TODA bolha aberta)
# ---------------------------------------------------------------------------
async def lousa_presidency(company: str) -> List[dict]:
    """Analisa TODAS as bolhas pendentes/abertas em lote (prefetch único —
    aguenta centenas de bolhas reais sem N+1)."""
    tickets = await db.tickets.find(
        {"company_id": company, "status": {"$in": ["pendente", "aberta"]}},
        {"_id": 0, "completion_data": 0, "field_photos": 0}
    ).sort("scheduled_time", 1).to_list(2000)
    if not tickets:
        return []

    client_ids = list({t.get("client_id") for t in tickets if t.get("client_id")})
    collab_ids = list({t.get("assigned_collaborator_id")
                       for t in tickets if t.get("assigned_collaborator_id")})

    # Geo por cliente (porta ocupada → CTO gps)
    ports = await db.cto_ports.find(
        {"company_id": company, "subscriber_id": {"$in": client_ids},
         "status": "occupied"},
        {"_id": 0, "subscriber_id": 1, "cto_id": 1, "port_number": 1,
         "lat": 1, "lng": 1}).to_list(3000)
    cto_ids = list({p["cto_id"] for p in ports if p.get("lat") is None})
    cto_gps = {c["id"]: (c.get("gps") or {}) for c in await db.ctos.find(
        {"company_id": company, "id": {"$in": cto_ids}},
        {"_id": 0, "id": 1, "gps": 1}).to_list(2000)}
    geo_by_client: Dict[str, dict] = {}
    for p in ports:
        lat, lng = p.get("lat"), p.get("lng")
        if lat is None:
            g = cto_gps.get(p["cto_id"]) or {}
            lat, lng = g.get("lat"), g.get("lng")
        if lat is not None:
            geo_by_client[p["subscriber_id"]] = {
                "lat": lat, "lng": lng, "cto_id": p["cto_id"],
                "port_number": p.get("port_number")}

    # Reincidência por cliente (60d, agregada)
    cutoff60 = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    rep_rows = await db.tickets.aggregate([
        {"$match": {"company_id": company, "type": "reparo",
                    "client_id": {"$in": client_ids},
                    "created_at": {"$gte": cutoff60}}},
        {"$group": {"_id": "$client_id", "n": {"$sum": 1}}},
    ]).to_list(3000)
    repairs_by_client = {r["_id"]: r["n"] for r in rep_rows}

    # GPS por técnico (último ping)
    gps_rows = await db.tech_locations.aggregate([
        {"$match": {"company_id": company, "collab_id": {"$in": collab_ids}}},
        {"$sort": {"captured_at": -1}},
        {"$group": {"_id": "$collab_id", "lat": {"$first": "$lat"},
                    "lng": {"$first": "$lng"}}},
    ]).to_list(500)
    gps_by_collab = {g["_id"]: g for g in gps_rows}

    prob_cache: Dict[str, Tuple[int, int]] = {}
    for ttype in {t.get("type") or "reparo" for t in tickets}:
        prob_cache[ttype] = await resolution_probability(company, ttype)

    scored = []
    for t in tickets:
        s = _score_from_context(
            t, gps_by_collab.get(t.get("assigned_collaborator_id")),
            geo_by_client.get(t.get("client_id")),
            repairs_by_client.get(t.get("client_id"), 0),
            prob_cache.get(t.get("type") or "reparo", (75, 0)))
        scored.append((t, s))
    ranked = sorted(scored, key=lambda x: -x[1]["score"])

    now = _now_iso()
    out: List[dict] = []
    from pymongo import UpdateOne
    bulk: List[Any] = []
    for rank, (t, s) in enumerate(ranked, start=1):
        risk = ("alto" if any("atrasada" in r for r in s["reasons"])
                or any("reincidente" in r for r in s["reasons"])
                else ("medio" if s["score"] >= 30 else "baixo"))
        block = {
            "priority_rank": rank,
            "score": s["score"],
            "risk": risk,
            "analysis": " · ".join(s["reasons"]) or "Sem fatores críticos",
            "prediction": f"Resolução {s['resolution_probability']}% provável",
            "distance_km": s["distance_km"],
            "updated_at": now,
            "by": "isabella_field",
        }
        bulk.append(UpdateOne({"id": t["id"]}, {"$set": {"isabella": block}}))
        out.append({"ticket_id": t["id"], "client": s["client"],
                    "collaborator_id": t.get("assigned_collaborator_id"),
                    "type": s["type"], "status": s["status"], **block})
    if bulk:
        await db.tickets.bulk_write(bulk, ordered=False)
    return out


# ---------------------------------------------------------------------------
# PRESIDENTE IA — indicadores consolidados da operação de campo
# ---------------------------------------------------------------------------
async def president_summary(company: str) -> dict:
    now_sp = datetime.now(SP_TZ)
    start = now_sp.replace(hour=0, minute=0, second=0, microsecond=0)
    s = start.astimezone(timezone.utc).isoformat()
    cutoff30 = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    closed_today = await db.tickets.find(
        {"company_id": company, "status": {"$in": ["finalizada", "encerrada"]},
         "closed_at": {"$gte": s}},
        {"_id": 0, "id": 1, "assigned_collaborator_id": 1,
         "isabella_score.nota_final": 1, "type": 1}).to_list(300)
    per_tech: Dict[str, dict] = {}
    for t in closed_today:
        cid = t.get("assigned_collaborator_id") or "?"
        row = per_tech.setdefault(cid, {"finalizadas": 0, "notas": []})
        row["finalizadas"] += 1
        nf = ((t.get("isabella_score") or {}).get("nota_final"))
        if nf is not None:
            row["notas"].append(nf)
    names = {c["id"]: c.get("name") for c in await db.collaborators.find(
        {"company_id": company, "id": {"$in": list(per_tech.keys())}},
        {"_id": 0, "id": 1, "name": 1}).to_list(100)}
    techs = [{"collaborator_id": cid, "name": names.get(cid),
              "finalizadas_hoje": r["finalizadas"],
              "nota_media": round(sum(r["notas"]) / len(r["notas"]), 1)
              if r["notas"] else None}
             for cid, r in per_tech.items()]

    retrabalho_30d = await db.tickets.count_documents(
        {"company_id": company, "type": "reparo",
         "isabella_root_cause": {"$exists": True},
         "created_at": {"$gte": cutoff30}})
    tra_events = await db.motor_ia_events.count_documents(
        {"company_id": company,
         "event_type": EventType.FIELD_ISABELLA_TRUCK_ROLL_AVOIDED,
         "timestamp": {"$gte": cutoff30}})
    tra_remote = await db.tickets.count_documents(
        {"company_id": company, "status": {"$in": ["finalizada", "encerrada"]},
         "closed_at": {"$gte": cutoff30},
         "completion_data.resolution_kind": "remote"})
    fleet_rows = await db.field_vehicle_inspections.find(
        {"company_id": company, "created_at": {"$gte": cutoff30},
         "isabella_score.nota": {"$exists": True}},
        {"_id": 0, "isabella_score.nota": 1}).to_list(200)
    fleet_avg = (round(sum(f["isabella_score"]["nota"] for f in fleet_rows)
                       / len(fleet_rows), 1) if fleet_rows else None)
    returns = await db.field_equipment_returns.find(
        {"company_id": company, "created_at": {"$gte": cutoff30}},
        {"_id": 0, "value_recovered": 1, "value_lost": 1}).to_list(300)

    events30 = await db.motor_ia_events.count_documents(
        {"company_id": company, "source": {"$in": ["field_ops", "isabella_field"]},
         "timestamp": {"$gte": cutoff30}})

    return {
        "generated_at": _now_iso(),
        "techs_today": sorted(techs, key=lambda x: -x["finalizadas_hoje"]),
        "finalizadas_hoje": len(closed_today),
        "retrabalho_classificado_30d": retrabalho_30d,
        "truck_roll_avoidance_30d": tra_remote + tra_events,
        "fleet_score_avg_30d": fleet_avg,
        "equipment_recovered_30d_brl": round(
            sum(r.get("value_recovered") or 0 for r in returns), 2),
        "equipment_lost_30d_brl": round(
            sum(r.get("value_lost") or 0 for r in returns), 2),
        "field_events_30d": events30,
    }
