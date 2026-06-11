"""
data_quality.py — Sprint 7 / iter226
Agente DATA_QUALITY_IA permanente. Roda checagens, calcula score
0-100 e emite eventos quando score cai.
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

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from database import db


CHECKS = [
    ("clients_no_plan", "Clientes sem plano",
        {"collection": "subscribers", "filter": {
            "$or": [{"plan_id": None}, {"plan_id": ""}]}}),
    ("clients_no_price", "Clientes sem preço",
        {"collection": "subscribers", "filter": {
            "$or": [{"plan_price": None}, {"plan_price": 0}]}}),
    ("clients_no_cto", "Clientes sem CTO",
        {"collection": "subscribers", "filter": {
            "$or": [{"cto_id": None}, {"cto_id": ""}]}}),
    ("clients_no_address", "Clientes sem endereço",
        {"collection": "subscribers", "filter": {
            "$or": [{"address": None}, {"address": ""}]}}),
    ("clients_no_cpf", "Clientes sem CPF",
        {"collection": "subscribers", "filter": {
            "$or": [{"cpf": None}, {"cpf": ""}]}}),
    ("onu_no_cto", "ONUs sem CTO",
        {"collection": "onus", "filter": {
            "$or": [{"cto_id": None}, {"cto_id": ""}]}}),
    ("cto_no_vlan", "CTOs sem VLAN",
        {"collection": "ctos", "filter": {
            "$or": [{"vlan": None}, {"vlan": 0}]}}),
    ("contracts_incomplete", "Contratos incompletos",
        {"collection": "contracts", "filter": {
            "$or": [{"signed_at": None}, {"plan_id": None}]}}),
]


async def _check_one(spec: Dict[str, Any],
                        company_id: str = None) -> int:
    try:
        flt = dict(spec["filter"])
        if company_id:
            flt = {"$and": [flt, {"company_id": company_id}]}
        return await db[spec["collection"]].count_documents(flt)
    except Exception:
        return 0


async def _total(coll: str, company_id: str = None) -> int:
    try:
        if company_id:
            return await db[coll].count_documents(
                {"company_id": company_id})
        return await db[coll].estimated_document_count()
    except Exception:
        return 0


async def run_scan(company_id: str = None) -> Dict[str, Any]:
    """Roda todas as checagens; retorna score + issues.

    Sprint 14: aceita company_id para isolamento multi-tenant.
    """
    total_clients = await _total("subscribers", company_id)
    total_onus = await _total("onus", company_id)
    total_ctos = await _total("ctos", company_id)
    total_contracts = await _total("contracts", company_id)
    denominators = {
        "subscribers": total_clients,
        "onus": total_onus,
        "ctos": total_ctos,
        "contracts": total_contracts,
    }

    issues: List[Dict[str, Any]] = []
    score_components: List[float] = []
    for key, label, spec in CHECKS:
        bad = await _check_one(spec, company_id)
        denom = denominators.get(spec["collection"], 1) or 1
        pct_bad = 100.0 * bad / denom if denom else 0.0
        good_pct = max(0.0, 100.0 - pct_bad)
        score_components.append(good_pct)
        issues.append({
            "key": key,
            "label": label,
            "collection": spec["collection"],
            "bad_count": bad,
            "total_count": denom,
            "pct_clean": round(good_pct, 1),
        })

    # duplicados (emails)
    try:
        match_stage = {"email": {"$nin": [None, ""]}}
        if company_id:
            match_stage["company_id"] = company_id
        pipe = [
            {"$match": match_stage},
            {"$group": {"_id": "$email", "n": {"$sum": 1}}},
            {"$match": {"n": {"$gt": 1}}},
            {"$count": "dups"},
        ]
        dups = 0
        async for r in db.subscribers.aggregate(pipe):
            dups = r["dups"]
        issues.append({
            "key": "dup_emails",
            "label": "E-mails duplicados",
            "collection": "subscribers",
            "bad_count": dups,
            "total_count": total_clients,
            "pct_clean": round(100.0 - (100.0 * dups
                                           / max(total_clients, 1)), 1),
        })
        score_components.append(100.0 - (100.0 * dups
                                            / max(total_clients, 1)))
    except Exception:
        pass

    score = round(sum(score_components) / len(score_components), 1) \
        if score_components else 100.0

    # status
    if score >= 90:
        status = "saudavel"
    elif score >= 70:
        status = "atencao"
    else:
        status = "critico"

    result = {
        "id": f"dq-{uuid.uuid4().hex[:12]}",
        "score": score,
        "status": status,
        "issues": issues,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "company_id": company_id,
    }
    # grava em motor_ia_insights
    try:
        await db.motor_ia_insights.insert_one({
            **result,
            "kind": "data_quality_scan",
            "created_at": result["generated_at"],
        })
    except Exception:
        pass
    # emite evento se score caiu abaixo de 70
    if score < 70:
        try:
            from services.event_bus import emit_event, EventType
            await emit_event(EventType.DATA_QUALITY_DROP,
                                company_id=company_id,
                                source="data_quality_ia",
                                severity="alta",
                                payload={"score": score,
                                            "top_issues":
                                                [i for i in issues
                                                   if i["pct_clean"] < 70]})
        except Exception:
            pass
    return result


async def run_scan_all_tenants() -> Dict[str, Any]:
    """Sprint 14 — roda um data quality scan POR company_id ativo.

    Garante que `motor_ia_insights` tenha 1 doc por empresa (e
    company_id preenchido em todos), eliminando o vazamento entre
    tenants reportado pela auditoria CTO.
    """
    companies = []
    try:
        companies = await db.subscribers.distinct("company_id")
    except Exception:
        companies = []
    companies = [c for c in companies if c]
    if not companies:
        return await run_scan(company_id=None)
    out = {"companies": [], "total": 0}
    for co in companies:
        try:
            r = await run_scan(company_id=co)
            out["companies"].append({
                "company_id": co,
                "score": r.get("score"),
                "status": r.get("status"),
            })
            out["total"] += 1
        except Exception:
            pass
    return out
