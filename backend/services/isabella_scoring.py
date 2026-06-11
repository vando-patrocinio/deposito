"""
isabella_scoring.py — FASE 6 da Constituição V4.0
Isabella Revenue Engine: 6 scores comerciais + next_best_action + playbooks.

Dados reais utilizados (sem mocks):
  - subscribers.created_at / plan_price / status / smartolt_onu_status
  - subscriber_invoices (overdue/paid history)
  - tickets (volume e tipos)
  - referrals (já indicou antes?)

Score 0-100. NUNCA usa LLM (heurística estatística).
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

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db


def _now(): return datetime.now(timezone.utc)
def _iso(d=None): return (d or _now()).astimezone(timezone.utc).isoformat()


def _clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))


def _days_since(iso_str: Optional[str]) -> int:
    if not iso_str: return 0
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return (_now() - dt).days
    except Exception:
        return 0


async def _ticket_counts(company_id: str,
                            sub_ids: List[str]) -> Dict[str, int]:
    pipe = [
        {"$match": {"company_id": company_id,
                     "client_id": {"$in": sub_ids}}},
        {"$group": {"_id": "$client_id", "n": {"$sum": 1}}},
    ]
    out: Dict[str, int] = {}
    async for r in db.tickets.aggregate(pipe):
        out[r["_id"]] = r["n"]
    return out


async def _overdue_counts(company_id: str,
                              ext_ids: List[str]) -> Dict[str, int]:
    pipe = [
        {"$match": {"company_id": company_id, "status": "overdue",
                     "subscriber_external_id": {"$in": ext_ids}}},
        {"$group": {"_id": "$subscriber_external_id",
                      "n": {"$sum": 1},
                      "amt": {"$sum": "$amount"}}},
    ]
    out: Dict[str, Dict[str, float]] = {}
    async for r in db.subscriber_invoices.aggregate(pipe):
        out[r["_id"]] = {"n": r["n"], "amt": float(r["amt"] or 0)}
    return out


async def _paid_counts(company_id: str,
                          ext_ids: List[str]) -> Dict[str, int]:
    pipe = [
        {"$match": {"company_id": company_id, "status": "paid",
                     "subscriber_external_id": {"$in": ext_ids}}},
        {"$group": {"_id": "$subscriber_external_id",
                      "n": {"$sum": 1}}},
    ]
    out: Dict[str, int] = {}
    async for r in db.subscriber_invoices.aggregate(pipe):
        out[r["_id"]] = r["n"]
    return out


async def _referred_count(company_id: str,
                              sub_ids: List[str]) -> Dict[str, int]:
    pipe = [
        {"$match": {"company_id": company_id,
                     "owner_subscriber_id": {"$in": sub_ids}}},
        {"$group": {"_id": "$owner_subscriber_id", "n": {"$sum": 1}}},
    ]
    out: Dict[str, int] = {}
    async for r in db.referrals.aggregate(pipe):
        out[r["_id"]] = r["n"]
    return out


def _scores_for_sub(
    sub: Dict[str, Any],
    tickets_n: int,
    overdue_n: int,
    overdue_amt: float,
    paid_n: int,
    referred_n: int,
) -> Dict[str, Any]:
    """Calcula os 6 scores."""
    age_days = _days_since(sub.get("created_at"))
    age_years = age_days / 365.0
    onu_status = (sub.get("smartolt_onu_status") or "").strip().lower()
    plan_price = float(sub.get("plan_price") or 0)
    has_onu_link = bool(sub.get("smartolt_onu_sn"))
    is_ativo = (sub.get("status") or "").upper() == "ATIVO"

    # BUY = chance de comprar algo (cross/upsell)
    # Cliente mais antigo, com poucos tickets, ativo, com sinal OK → mais propenso
    buy = 50
    buy += min(age_years * 5, 20)         # +20 por 4+ anos
    buy -= min(tickets_n * 3, 30)          # -30 se muitos tickets
    buy += 10 if onu_status == "online" else -5
    buy += 5 if is_ativo else -20
    buy_score = _clamp(buy)

    # UPGRADE = chance aceitar upgrade
    # Cliente antigo + plano baixo + sinal saudável + sem ticket grave
    upgrade = 40
    if plan_price > 0:
        if plan_price < 80: upgrade += 25
        elif plan_price < 120: upgrade += 10
        else: upgrade -= 10
    else:
        upgrade += 5  # desconhecido, neutro positivo
    upgrade += min(age_years * 4, 16)
    upgrade -= min(tickets_n * 4, 30)
    upgrade += 10 if onu_status == "online" else -10
    upgrade_score = _clamp(upgrade)

    # CHURN = chance cancelar
    # Tickets recentes + sinal ruim + atrasos + sem vínculo
    churn = 20
    churn += min(tickets_n * 6, 30)
    if onu_status in ("offline", "los", "power fail"):
        churn += 35
    elif onu_status == "warning":
        churn += 15
    churn += min(overdue_n * 8, 30)
    churn += 10 if not has_onu_link else 0
    churn -= 10 if is_ativo else 30  # inativo pesa muito
    churn_score = _clamp(churn)

    # RETENTION = vale a pena reter?
    # Plano alto + tempo de casa + pagamentos
    retention = 30
    retention += min(plan_price / 4, 30)
    retention += min(age_years * 8, 30)
    retention += min(paid_n, 20)
    retention -= 10 if not is_ativo else 0
    retention_score = _clamp(retention)

    # REFERRAL = chance indicar
    # Pagamentos em dia + tempo + poucas reclamações + já indicou antes
    referral = 30
    referral += min(paid_n * 2, 30)
    referral += min(age_years * 5, 20)
    referral -= min(tickets_n * 4, 20)
    referral += 20 if referred_n > 0 else 0
    referral -= min(overdue_n * 5, 25)
    referral_score = _clamp(referral)

    # COLLECTION = chance de pagar após contato
    # Histórico de pagamentos + dias de atraso pequenos + ativo
    collection = 40
    collection += min(paid_n * 3, 30)
    if overdue_n == 1:    collection += 25
    elif overdue_n == 2:  collection += 10
    elif overdue_n >= 3:  collection -= 15
    collection += 5 if is_ativo else -20
    collection += 5 if has_onu_link and onu_status == "online" else 0
    collection_score = _clamp(collection)

    # NEXT BEST ACTION
    # Prioridade: churn ≥ 70 → retention; senão collection ≥ 75; depois upgrade > 80;
    #             depois referral > 85; senão NO_ACTION
    if churn_score >= 70 and retention_score >= 50:
        nba = "RETENTION_PLAYBOOK"
    elif overdue_n >= 1 and collection_score >= 75:
        nba = "COLLECTION_CONTACT"
    elif upgrade_score >= 80:
        nba = "UPGRADE_PLAN"
    elif referral_score >= 85:
        nba = "REFERRAL_CAMPAIGN"
    elif buy_score >= 75:
        nba = "CROSS_SELL"
    else:
        nba = "NO_ACTION"

    # Confidence: maior do top score / 100
    conf = round(max(buy_score, upgrade_score, churn_score,
                      retention_score, referral_score,
                      collection_score) / 100, 2)

    return {
        "buy_score": round(buy_score, 1),
        "upgrade_score": round(upgrade_score, 1),
        "churn_score": round(churn_score, 1),
        "retention_score": round(retention_score, 1),
        "referral_score": round(referral_score, 1),
        "collection_score": round(collection_score, 1),
        "next_best_action": nba,
        "confidence": conf,
        "_features": {
            "age_days": age_days,
            "tickets": tickets_n,
            "overdue": overdue_n,
            "overdue_amt": round(overdue_amt, 2),
            "paid_history": paid_n,
            "onu_status": sub.get("smartolt_onu_status"),
            "plan_price": plan_price,
            "is_ativo": is_ativo,
        },
    }


async def calculate_all(company_id: str,
                            limit: int = 5000) -> Dict[str, Any]:
    """Calcula scores para todos os subscribers de uma empresa. Persiste."""
    subs = await db.subscribers.find(
        {"company_id": company_id}).limit(limit).to_list(None)
    sub_ids = [s["id"] for s in subs]

    # Bridge subscriber_id → subscriber_external_id via SAP
    saps = await db.subscriber_access_points.find(
        {"company_id": company_id,
         "subscriber_id": {"$in": sub_ids}}
    ).to_list(None)
    ext_by_sub: Dict[str, str] = {}
    for sap in saps:
        if sap.get("subscriber_id") and sap.get("subscriber_external_id"):
            ext_by_sub.setdefault(sap["subscriber_id"],
                                       sap["subscriber_external_id"])
    ext_ids = list(ext_by_sub.values())

    tickets = await _ticket_counts(company_id, sub_ids)
    overdues = await _overdue_counts(company_id, ext_ids)
    paid = await _paid_counts(company_id, ext_ids)
    referred = await _referred_count(company_id, sub_ids)

    bulk = []
    nba_counter: Counter = Counter()
    for s in subs:
        ext = ext_by_sub.get(s["id"])
        ov = overdues.get(ext, {"n": 0, "amt": 0}) if ext else {"n": 0, "amt": 0}
        sc = _scores_for_sub(
            s,
            tickets_n=tickets.get(s["id"], 0),
            overdue_n=ov["n"], overdue_amt=ov["amt"],
            paid_n=paid.get(ext, 0) if ext else 0,
            referred_n=referred.get(s["id"], 0),
        )
        nba_counter[sc["next_best_action"]] += 1
        doc = {
            "subscriber_id": s["id"],
            "company_id": company_id,
            "calculated_at": _iso(),
            **sc,
        }
        bulk.append(doc)

    # Upsert por subscriber_id (idempotente)
    if bulk:
        for d in bulk:
            await db.motor_ia_subscriber_scores.update_one(
                {"subscriber_id": d["subscriber_id"],
                 "company_id": d["company_id"]},
                {"$set": d}, upsert=True,
            )

    return {
        "company_id": company_id,
        "scored": len(bulk),
        "calculated_at": _iso(),
        "nba_distribution": dict(nba_counter),
    }


async def top(company_id: str, score_field: str,
                limit: int = 20) -> List[Dict[str, Any]]:
    """Top N por um dos 6 scores."""
    allowed = {"buy_score", "upgrade_score", "churn_score",
                "retention_score", "referral_score", "collection_score"}
    if score_field not in allowed:
        raise ValueError(f"score_field inválido: {score_field}")
    cur = db.motor_ia_subscriber_scores.find(
        {"company_id": company_id}).sort(score_field, -1).limit(limit)
    out = []
    async for d in cur:
        d.pop("_id", None)
        out.append(d)
    return out


async def revenue_potential(company_id: str) -> Dict[str, Any]:
    """Receita potencial agregada (upsell + cobrança)."""
    # Upgrade > 80 → assume +R$ 30/mês de aumento (placeholder honesto)
    upg = await db.motor_ia_subscriber_scores.count_documents(
        {"company_id": company_id, "upgrade_score": {"$gte": 80}})
    # Cross-sell (BUY > 75)
    cs = await db.motor_ia_subscriber_scores.count_documents(
        {"company_id": company_id, "buy_score": {"$gte": 75}})
    # Collection >= 75 → potencial de recuperação na carteira overdue
    coll = await db.motor_ia_subscriber_scores.find(
        {"company_id": company_id, "collection_score": {"$gte": 75}}
    ).to_list(None)
    coll_ids = [c["subscriber_id"] for c in coll]
    saps = await db.subscriber_access_points.find(
        {"company_id": company_id,
         "subscriber_id": {"$in": coll_ids}}
    ).to_list(None)
    ext_ids = [s.get("subscriber_external_id") for s in saps
                 if s.get("subscriber_external_id")]
    overdues = await _overdue_counts(company_id, ext_ids)
    coll_amt = sum(o["amt"] for o in overdues.values())

    return {
        "upgrade_candidates": upg,
        "upgrade_monthly_BRL_estimate": round(upg * 30, 2),
        "cross_sell_candidates": cs,
        "cross_sell_monthly_BRL_estimate": round(cs * 20, 2),
        "collection_candidates": len(coll_ids),
        "collection_recoverable_BRL": round(coll_amt, 2),
        "collection_recoverable_p18": round(coll_amt * 0.18, 2),
    }


async def where_to_sell(company_id: str) -> Dict[str, Any]:
    """Responde à pergunta executiva V4.0:
       'Onde podemos vender mais hoje?'"""
    rp = await revenue_potential(company_id)
    top_upg = await top(company_id, "upgrade_score", 5)
    msg = (
        f"{rp['upgrade_candidates']} clientes têm Upgrade Score ≥ 80.\n"
        f"Receita potencial: R$ {rp['upgrade_monthly_BRL_estimate']:,.2f}/mês.\n"
        f"+ {rp['cross_sell_candidates']} candidatos a cross-sell "
        f"(estimado R$ {rp['cross_sell_monthly_BRL_estimate']:,.2f}/mês)."
    )
    return {
        "headline": msg,
        "potential": rp,
        "top_upgrade_5": [{"sub": t["subscriber_id"],
                              "score": t["upgrade_score"]}
                            for t in top_upg],
        "best_campaign": "Upgrade plano básico → premium (alvo: planos < R$80)",
    }


async def run_playbooks(company_id: str) -> Dict[str, Any]:
    """Gera oportunidades automáticas baseadas nos thresholds.

    Operação Isabella Evolução Final V2 (CTO 02/2026):
      • Threshold único e baixo (>=55 na escala 0-100, equivale a 0.55)
        para coletar mais aprendizado. Mantém quality_tier para priorização.
    """
    import os
    from services.event_emitters import emit_business
    created = Counter()
    # Threshold global Evolução Final V2 (default 55 = "score >= 0.55")
    th = float(os.environ.get("ISABELLA_OPP_MIN_SCORE", "55"))

    cur = db.motor_ia_subscriber_scores.find({"company_id": company_id})
    async for s in cur:
        sid = s["subscriber_id"]
        # upgrade
        if s["upgrade_score"] >= th:
            doc = {
                "id": f"opp-up-{uuid.uuid4().hex[:10]}",
                "company_id": company_id,
                "subscriber_id": sid,
                "kind": "opportunity.upgrade",
                "source": "isabella",
                "score": s["upgrade_score"],
                "created_at": _iso(),
            }
            r = await db.isabella_opportunities.update_one(
                {"subscriber_id": sid, "kind": "opportunity.upgrade",
                 "company_id": company_id},
                {"$setOnInsert": doc}, upsert=True,
            )
            if r.upserted_id:
                created["opportunity.upgrade"] += 1
                await emit_business(
                    kind="sale.created",
                    company_id=company_id,
                    payload={"subscriber_id": sid,
                              "kind": "opportunity.upgrade",
                              "score": s["upgrade_score"]},
                    severity="media",
                    source="isabella_playbook",
                )
        # referral
        if s["referral_score"] >= th:
            doc = {
                "id": f"opp-rf-{uuid.uuid4().hex[:10]}",
                "company_id": company_id,
                "subscriber_id": sid,
                "kind": "campaign.referral",
                "source": "isabella",
                "score": s["referral_score"],
                "created_at": _iso(),
            }
            r = await db.isabella_opportunities.update_one(
                {"subscriber_id": sid, "kind": "campaign.referral",
                 "company_id": company_id},
                {"$setOnInsert": doc}, upsert=True,
            )
            if r.upserted_id:
                created["campaign.referral"] += 1
        # collection
        if s["collection_score"] >= th:
            doc = {
                "id": f"opp-cc-{uuid.uuid4().hex[:10]}",
                "company_id": company_id,
                "subscriber_id": sid,
                "kind": "operacao_tese_candidate",
                "source": "isabella",
                "score": s["collection_score"],
                "created_at": _iso(),
            }
            r = await db.isabella_opportunities.update_one(
                {"subscriber_id": sid, "kind": "operacao_tese_candidate",
                 "company_id": company_id},
                {"$setOnInsert": doc}, upsert=True,
            )
            if r.upserted_id:
                created["operacao_tese_candidate"] += 1
        # churn → retention
        if s["churn_score"] >= th:
            doc = {
                "id": f"opp-rt-{uuid.uuid4().hex[:10]}",
                "company_id": company_id,
                "subscriber_id": sid,
                "kind": "retention.playbook",
                "source": "isabella",
                "score": s["churn_score"],
                "created_at": _iso(),
            }
            r = await db.isabella_opportunities.update_one(
                {"subscriber_id": sid, "kind": "retention.playbook",
                 "company_id": company_id},
                {"$setOnInsert": doc}, upsert=True,
            )
            if r.upserted_id:
                created["retention.playbook"] += 1

    return {"created": dict(created), "executed_at": _iso()}
