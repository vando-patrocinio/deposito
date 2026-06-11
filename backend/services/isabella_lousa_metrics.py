"""Métricas das OS criadas pela Isabella na Lousa.

Endpoint principal: GET /api/isabella-lousa/metrics?days=7

Sem coleção nova. Lê de:
  • db.tickets (filtro origin=isabella)
  • db.ticket_logs (eventos de reagendamento/cancelamento)
  • db.ai_evaluations (ISABELLA_WINDOW_PROPOSED · NPS · ANTI_CPF_BLOCK · OS_LEARNING)
  • db.truck_roll_decisions

Retorna 18 indicadores conforme spec do CTO.
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "operacoes",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db


# Valor de referência conservador para economia (mesma régua do Presidente Financeiro)
ECON_PREVENTIVA_BRL = 80.0
ECON_VISITA_EVITADA_BRL = 80.0


def _iso_cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


async def _avg_seconds_between(coll, match: Dict[str, Any],
                                  start_field: str, end_field: str
                                  ) -> Optional[float]:
    pipe = [
        {"$match": match},
        {"$project": {
            "delta": {
                "$cond": [
                    {"$and": [{"$ifNull": [f"${start_field}", False]},
                                 {"$ifNull": [f"${end_field}", False]}]},
                    {"$subtract": [
                        {"$dateFromString": {"dateString": f"${end_field}",
                                              "onError": None,
                                              "onNull": None}},
                        {"$dateFromString": {"dateString": f"${start_field}",
                                              "onError": None,
                                              "onNull": None}},
                    ]},
                    None,
                ],
            }
        }},
        {"$match": {"delta": {"$ne": None, "$gt": 0}}},
        {"$group": {"_id": None,
                       "avg_ms": {"$avg": "$delta"},
                       "n": {"$sum": 1}}},
    ]
    cur = coll.aggregate(pipe)
    docs = await cur.to_list(1)
    if not docs:
        return None
    avg_ms = docs[0]["avg_ms"]
    return float(avg_ms) / 1000.0 if avg_ms else None


def _classify_status(passed: int, total: int) -> str:
    """Mapeia ratio em VERDE/AMARELO/VERMELHO."""
    if total == 0:
        return "AMARELO"
    pct = passed / total
    if pct >= 0.7:
        return "VERDE"
    if pct >= 0.4:
        return "AMARELO"
    return "VERMELHO"


async def isabella_lousa_metrics(company_id: str,
                                    days: int = 7) -> Dict[str, Any]:
    cutoff = _iso_cutoff(days)
    base = {"company_id": company_id, "origin": "isabella",
            "created_at": {"$gte": cutoff}}

    # ─── 1-5: contadores básicos ────────────────────────────────────────
    total = await db.tickets.count_documents(base)

    agendadas = await db.tickets.count_documents(
        {**base, "status": {"$in": ["aberta", "pendente",
                                       "aguardando_atendimento"]}})
    finalizadas = await db.tickets.count_documents(
        {**base, "status": {"$in": ["concluida", "fechada", "finalizada"]}})
    canceladas = await db.tickets.count_documents(
        {**base, "status": {"$in": ["cancelada", "cancelado"]}})

    # Reagendamentos via ticket_logs
    reagendadas_ids: set = set()
    async for log in db.ticket_logs.find(
            {"company_id": company_id,
             "action": {"$regex": "reagend", "$options": "i"},
             "created_at": {"$gte": cutoff}},
            {"_id": 0, "ticket_id": 1}):
        reagendadas_ids.add(log.get("ticket_id"))
    os_reagendadas = len(reagendadas_ids)

    # ─── 6-7: tempos médios ─────────────────────────────────────────────
    # Proposta → confirmação via ai_evaluations.kind=ISABELLA_WINDOW_PROPOSED
    proposals = []
    async for p in db.ai_evaluations.find(
            {"company_id": company_id, "kind": "ISABELLA_WINDOW_PROPOSED",
             "created_at": {"$gte": cutoff}},
            {"_id": 0, "phone": 1, "created_at": 1, "subscriber_id": 1}):
        proposals.append(p)
    confirmed_deltas: List[float] = []
    for p in proposals:
        # Busca o ticket criado pelo mesmo phone após a proposta
        tk = await db.tickets.find_one({
            "company_id": company_id, "origin": "isabella",
            "client_snapshot.phone": p.get("phone"),
            "created_at": {"$gte": p.get("created_at")},
        }, {"_id": 0, "created_at": 1})
        if tk and tk.get("created_at"):
            try:
                a = datetime.fromisoformat(p["created_at"].replace("Z", "+00:00"))
                b = datetime.fromisoformat(tk["created_at"].replace("Z", "+00:00"))
                delta = (b - a).total_seconds()
                if 0 <= delta < 86400:
                    confirmed_deltas.append(delta)
            except Exception:
                pass
    tempo_proposta_confirmacao_s = (sum(confirmed_deltas) / len(confirmed_deltas)
                                       if confirmed_deltas else None)

    # Criação → fechamento (smart_repairs.closed_at OU tickets.closed_at)
    tempo_criacao_fechamento_s = await _avg_seconds_between(
        db.tickets, {**base, "closed_at": {"$ne": None}},
        "created_at", "closed_at")

    # ─── 8-9: taxas ─────────────────────────────────────────────────────
    # 1º contato resolvido: ticket cujo OS_LEARNING.resolveu=true E retornou=false
    primeiro_contato_ok = 0
    async for ev in db.ai_evaluations.find(
            {"company_id": company_id, "kind": "OS_LEARNING",
             "resolveu": True, "retornou": False,
             "computed_at": {"$gte": cutoff}},
            {"_id": 0, "ticket_id": 1}):
        # Conta só se for ticket da Isabella
        t = await db.tickets.find_one(
            {"id": ev.get("ticket_id"), "origin": "isabella"},
            {"_id": 0, "id": 1})
        if t:
            primeiro_contato_ok += 1
    taxa_primeiro_contato_resolvido = (primeiro_contato_ok / total * 100.0
                                          if total > 0 else 0.0)

    taxa_reagendamento = (os_reagendadas / total * 100.0) if total > 0 else 0.0

    # ─── 10: NPS médio inferido ─────────────────────────────────────────
    pipe = [
        {"$match": {"company_id": company_id,
                       "kind": {"$in": [None, "ISABELLA_RESPONSE"]},
                       "nps_inferido": {"$exists": True, "$ne": None},
                       "created_at": {"$gte": cutoff}}},
        {"$group": {"_id": None, "avg": {"$avg": "$nps_inferido"},
                       "n": {"$sum": 1}}},
    ]
    nps_doc = await db.ai_evaluations.aggregate(pipe).to_list(1)
    nps_medio = float(nps_doc[0]["avg"]) if nps_doc else None
    nps_n = int(nps_doc[0]["n"]) if nps_doc else 0

    # ─── 11: Premium Repair ─────────────────────────────────────────────
    premium_repair_count = await db.ai_evaluations.count_documents(
        {"company_id": company_id, "premium_repair.active": True,
         "created_at": {"$gte": cutoff}})

    # ─── 12: Truck Roll distribution ────────────────────────────────────
    truck_dist: Dict[str, int] = {
        "DO_NOT_DISPATCH": 0, "DISPATCH": 0, "ESCALATE_COLLECTIVE": 0,
        "INCIDENTE_COLETIVO": 0, "PREVENTIVA": 0,
    }
    pipe = [
        {"$match": {"company_id": company_id, "ts": {"$gte": cutoff}}},
        {"$group": {"_id": "$decision", "n": {"$sum": 1}}},
    ]
    async for r in db.truck_roll_decisions.aggregate(pipe):
        truck_dist[r["_id"] or "?"] = r["n"]
    # Spec original do CTO usa ESCALATE_COLLECTIVE; unificamos
    truck_dist["ESCALATE_COLLECTIVE"] = (truck_dist.get("ESCALATE_COLLECTIVE", 0)
                                            + truck_dist.pop("INCIDENTE_COLETIVO", 0))

    # ─── 13: top 5 motivos das OS Isabella ──────────────────────────────
    pipe = [
        {"$match": base},
        {"$group": {"_id": "$client_snapshot.relato", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 5},
    ]
    top_motivos = []
    async for r in db.tickets.aggregate(pipe):
        if r["_id"]:
            top_motivos.append({"motivo": str(r["_id"])[:100], "count": r["n"]})

    # ─── 14: top 5 técnicos por OS Isabella ─────────────────────────────
    pipe = [
        {"$match": base},
        {"$group": {"_id": "$assigned_collaborator_id", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 5},
    ]
    top_techs = []
    async for r in db.tickets.aggregate(pipe):
        if not r["_id"]:
            continue
        col = await db.collaborators.find_one(
            {"id": r["_id"], "company_id": company_id},
            {"_id": 0, "name": 1})
        top_techs.append({
            "collaborator_id": r["_id"],
            "name": (col or {}).get("name", "—"),
            "count": r["n"],
        })

    # ─── 15: OS sem follow-up Isabella (aberta há > 24h) ────────────────
    h24 = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    os_sem_followup = await db.tickets.count_documents({
        **base,
        "status": {"$in": ["aberta", "pendente",
                              "aguardando_atendimento"]},
        "created_at": {"$lte": h24},
    })

    # ─── 16: duplicadas bloqueadas — usa logs do scheduler ──────────────
    # A função confirm_and_create_os marca {duplicate: true} mas não persiste
    # esse evento. Capturamos pelo log do ticket original e contagem via
    # ai_evaluations.kind=ISABELLA_WINDOW_PROPOSED órfãos (propostas sem ticket
    # subsequente único — proxy razoável).
    os_duplicadas_bloqueadas = 0  # conservador; só conta o que evidencia
    pipe = [
        {"$match": {"company_id": company_id,
                       "kind": "ISABELLA_WINDOW_PROPOSED",
                       "created_at": {"$gte": cutoff}}},
        {"$group": {"_id": "$phone", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
    ]
    async for r in db.ai_evaluations.aggregate(pipe):
        # Se há > 1 propostas para o mesmo phone e só 1 ticket criado, contamos
        n_tickets = await db.tickets.count_documents({
            **base, "client_snapshot.phone": r["_id"]})
        if r["n"] > n_tickets:
            os_duplicadas_bloqueadas += (r["n"] - n_tickets)

    # ─── 17: economia estimada ──────────────────────────────────────────
    visitas_evitadas = (truck_dist.get("DO_NOT_DISPATCH", 0)
                          + truck_dist.get("PREVENTIVA", 0)
                          + truck_dist.get("ESCALATE_COLLECTIVE", 0))
    preventivas_da_isabella = await db.tickets.count_documents({
        **base, "priority": "horario"})
    economia = (visitas_evitadas * ECON_VISITA_EVITADA_BRL
                 + preventivas_da_isabella * ECON_PREVENTIVA_BRL)

    # ─── 18: status geral ───────────────────────────────────────────────
    # Score = média ponderada de 4 sinais
    signals = {
        "first_contact_ok": taxa_primeiro_contato_resolvido / 100.0,  # alvo: alto
        "reschedule_bad": 1.0 - min(taxa_reagendamento / 100.0, 1.0),  # alvo: baixo
        "nps_ok": (nps_medio / 10.0) if nps_medio is not None else 0.7,
        "followup_ok": 1.0 - (os_sem_followup / max(total, 1)),
    }
    health = sum(signals.values()) / len(signals)
    if health >= 0.7:
        status_geral = "VERDE"
    elif health >= 0.45:
        status_geral = "AMARELO"
    else:
        status_geral = "VERMELHO"

    return {
        "company_id": company_id,
        "window_days": days,
        "computed_at": datetime.now(timezone.utc).isoformat(),

        "total_os_isabella": total,
        "os_agendadas": agendadas,
        "os_finalizadas": finalizadas,
        "os_canceladas": canceladas,
        "os_reagendadas": os_reagendadas,

        "tempo_medio_proposta_confirmacao_s": (
            round(tempo_proposta_confirmacao_s, 1)
            if tempo_proposta_confirmacao_s is not None else None),
        "tempo_medio_criacao_fechamento_s": (
            round(tempo_criacao_fechamento_s, 1)
            if tempo_criacao_fechamento_s is not None else None),

        "taxa_primeiro_contato_resolvido_pct": round(taxa_primeiro_contato_resolvido, 1),
        "taxa_reagendamento_pct": round(taxa_reagendamento, 1),

        "nps_medio_inferido": (round(nps_medio, 1)
                                  if nps_medio is not None else None),
        "nps_samples": nps_n,
        "premium_repair_count": premium_repair_count,

        "truck_roll_decisions": {
            "DO_NOT_DISPATCH": truck_dist.get("DO_NOT_DISPATCH", 0),
            "DISPATCH": truck_dist.get("DISPATCH", 0),
            "ESCALATE_COLLECTIVE": truck_dist.get("ESCALATE_COLLECTIVE", 0),
            "PREVENTIVA": truck_dist.get("PREVENTIVA", 0),
        },

        "top_5_motivos_os": top_motivos,
        "top_5_tecnicos_por_os_isabella": top_techs,

        "os_sem_followup": os_sem_followup,
        "os_duplicadas_bloqueadas": os_duplicadas_bloqueadas,

        "economia_estimativa_brl": round(economia, 2),
        "health_signals": {k: round(v, 2) for k, v in signals.items()},
        "status_geral": status_geral,
    }
