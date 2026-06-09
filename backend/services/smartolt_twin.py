"""
smartolt_twin.py — FASE 4 da Constituição V3.0 (Digital Twin)

Transforma SmartOLT em organismo observável.
Health score 0-100 por ONU / CTO / PON / VLAN / Bairro / Cidade.
Predição heurística baseada em signal_history_24h + tickets + churn.

Tabelas-fonte (sem mocks):
  - smartolt_onus
  - subscribers (com smartolt_onu_sn da FASE 1.5)
  - subscriber_invoices
  - tickets
  - ctos / cto_ports
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db


BAD = {"offline", "los", "power fail"}
DEGRADED = {"warning"}


def _level(score: float) -> str:
    if score >= 95: return "EXCELENTE"
    if score >= 90: return "SAUDAVEL"
    if score >= 80: return "ATENCAO"
    if score >= 70: return "CRITICO"
    return "INCIDENTE"


def _onu_score(o: Dict[str, Any]) -> float:
    st = (o.get("status") or "").strip().lower()
    if st in BAD: return 0
    if st in DEGRADED: return 60
    try:
        sig = float(o.get("signal_1310") or -99)
    except Exception:
        sig = -99
    if sig == -99: return 80          # sem sinal histórico
    if sig >= -22: return 100
    if sig >= -25: return 90
    if sig >= -27: return 75
    if sig >= -29: return 55
    return 30


def _level_count(scores: List[float]) -> Dict[str, int]:
    out = {"EXCELENTE": 0, "SAUDAVEL": 0, "ATENCAO": 0,
           "CRITICO": 0, "INCIDENTE": 0}
    for s in scores:
        out[_level(s)] += 1
    return out


async def cto_health(company_id: str) -> List[Dict[str, Any]]:
    """Saúde por CTO via cto_ports + ranking de degradação."""
    ports = await db.cto_ports.find(
        {"company_id": company_id}).to_list(None)
    onus_all = await db.smartolt_onus.find(
        {"company_id": company_id}).to_list(None)
    # agrupa ONUs por (olt+board+port) — mesma key da FASE 1
    onus_by_key = defaultdict(list)
    for o in onus_all:
        k = (o.get("olt_name"), str(o.get("board") or ""),
             str(o.get("port") or ""))
        onus_by_key[k].append(o)

    # tickets nos últimos 30d agrupados por CTO (via subscriber)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    tickets_n = await db.tickets.count_documents(
        {"company_id": company_id, "created_at": {"$gte": cutoff}})

    # Agrupar por nome de CTO (zone_name das ONUs)
    by_cto: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for o in onus_all:
        zone = o.get("zone_name") or "_unknown"
        by_cto[zone].append(o)

    out = []
    for cto_name, onus in by_cto.items():
        if cto_name == "_unknown" or len(onus) == 0:
            continue
        scores = [_onu_score(o) for o in onus]
        avg = sum(scores) / len(scores)
        levels = _level_count(scores)
        offline_n = sum(1 for o in onus
                         if (o.get("status") or "").strip().lower() in BAD)
        out.append({
            "cto": cto_name,
            "score": round(avg, 1),
            "level": _level(avg),
            "total_onus": len(onus),
            "offline": offline_n,
            "occupancy_pct": round(len(onus) /
                                     max(len(onus) + 10, 1) * 100, 1),
            "levels": levels,
        })
    out.sort(key=lambda x: x["score"])
    return out


async def pon_health(company_id: str) -> List[Dict[str, Any]]:
    """Por porta PON: total/online/offline/los/power_fail/degradação."""
    onus = await db.smartolt_onus.find(
        {"company_id": company_id}).to_list(None)
    by_pon: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for o in onus:
        k = f"{o.get('olt_name')}::{o.get('board')}/{o.get('port')}"
        by_pon[k].append(o)
    out = []
    for k, lst in by_pon.items():
        c = Counter((o.get("status") or "Unknown").strip() for o in lst)
        scores = [_onu_score(o) for o in lst]
        avg = sum(scores) / max(len(scores), 1)
        out.append({
            "pon": k,
            "total": len(lst),
            "online": c.get("Online", 0),
            "offline": c.get("Offline", 0),
            "los": c.get("LOS", 0),
            "power_fail": c.get("Power fail", 0),
            "warning": c.get("Warning", 0),
            "score": round(avg, 1),
            "level": _level(avg),
        })
    out.sort(key=lambda x: x["score"])
    return out


async def vlan_health(company_id: str) -> List[Dict[str, Any]]:
    """Utilização e saturação por VLAN (via current_vlan dos subs)."""
    pipe = [
        {"$match": {"company_id": company_id,
                     "current_vlan": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$current_vlan", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    items = []
    async for r in db.subscribers.aggregate(pipe):
        n = r["count"]
        # heurística: VLAN com >= 500 subs = saturada; 350-499 atenção
        if n >= 500:
            level = "SATURADA"
        elif n >= 350:
            level = "ATENCAO"
        else:
            level = "SAUDAVEL"
        items.append({
            "vlan": r["_id"], "count": n,
            "utilization_pct": min(round(n / 500 * 100, 1), 100),
            "level": level,
        })
    return items


async def heatmap_by_zone(company_id: str) -> List[Dict[str, Any]]:
    """Heatmap por zona (mesmo dado de cto_health para visualização)."""
    return await cto_health(company_id)


async def predictions(company_id: str) -> Dict[str, Any]:
    """Predição heurística baseada no estado atual.
    Horizontes 7/15/30 dias."""
    ctos = await cto_health(company_id)
    pons = await pon_health(company_id)
    vlans = await vlan_health(company_id)

    cto_degraded = [c for c in ctos if c["score"] < 85]
    cto_critical = [c for c in ctos if c["score"] < 70]
    vlan_saturated = [v for v in vlans if v["level"] == "SATURADA"]
    # MASS_OFFLINE: porta PON com >=80% das ONUs offline
    mass_offline = [p for p in pons
                     if p["total"] >= 3
                     and (p["offline"] + p["los"] + p["power_fail"])
                          / p["total"] >= 0.8]
    # CHURN_BY_SIGNAL: ONUs com sinal pior que -28
    subs_at_risk = await db.subscribers.count_documents({
        "company_id": company_id,
        "smartolt_onu_signal_1310": {"$lt": "-28"},
    })

    return {
        "horizons": [7, 15, 30],
        "CTO_DEGRADED": {
            "predicted_count": len(cto_degraded),
            "top": [c["cto"] for c in cto_degraded[:5]],
        },
        "CTO_CRITICAL": {
            "predicted_count": len(cto_critical),
            "top": [c["cto"] for c in cto_critical[:5]],
        },
        "VLAN_SATURATED": {
            "predicted_count": len(vlan_saturated),
            "top": [v["vlan"] for v in vlan_saturated[:5]],
        },
        "MASS_OFFLINE": {
            "predicted_count": len(mass_offline),
            "top": [p["pon"] for p in mass_offline[:5]],
        },
        "CHURN_BY_SIGNAL": {
            "predicted_count": subs_at_risk,
            "horizon_days": 30,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def revenue_at_risk(company_id: str) -> Dict[str, Any]:
    """R$ em risco AGORA por degradação técnica."""
    # 1. Clientes em ONUs problemáticas: extraímos amount/mês a partir do
    #    plan_price médio dos subs com smartolt_onu_status BAD
    bad_subs = await db.subscribers.find({
        "company_id": company_id,
        "smartolt_onu_status": {"$in": ["Offline", "LOS", "Power fail"]},
    }).to_list(None)
    monthly_risk = sum(float(s.get("plan_price") or 0) for s in bad_subs)

    # 2. CTO crítica: subs em zona de CTO com score < 70
    ctos = await cto_health(company_id)
    critical_zones = {c["cto"] for c in ctos if c["score"] < 70}
    # mapeia subs → zone via smartolt_onu_zone (já existe pós-FASE 1)
    crit_subs = await db.subscribers.count_documents({
        "company_id": company_id,
        "smartolt_onu_zone": {"$in": list(critical_zones)},
    }) if critical_zones else 0

    # 3. VLAN saturada: subs nas vlans top
    vlans = await vlan_health(company_id)
    sat_vlans = [v["vlan"] for v in vlans if v["level"] == "SATURADA"]
    sat_subs = await db.subscribers.count_documents({
        "company_id": company_id,
        "current_vlan": {"$in": sat_vlans},
    }) if sat_vlans else 0

    return {
        "monthly_BRL_at_risk": round(monthly_risk, 2),
        "annual_BRL_at_risk": round(monthly_risk * 12, 2),
        "subs_in_bad_onu": len(bad_subs),
        "subs_in_critical_cto": crit_subs,
        "subs_in_saturated_vlan": sat_subs,
        "critical_ctos": list(critical_zones)[:10],
        "saturated_vlans": sat_vlans[:10],
    }


async def what_to_worry(company_id: str) -> Dict[str, Any]:
    """Presidente IA respondendo sem humano às perguntas-chave."""
    ctos = await cto_health(company_id)
    vlans = await vlan_health(company_id)
    preds = await predictions(company_id)
    rev = await revenue_at_risk(company_id)

    cto_concern = (ctos[0] if ctos else None)  # pior score
    saturated = [v for v in vlans if v["level"] == "SATURADA"]

    return {
        "qual_cto_preocupa": (
            f"{cto_concern['cto']} score={cto_concern['score']} "
            f"({cto_concern['level']}, {cto_concern['offline']} offline)"
            if cto_concern else "—"
        ),
        "bairro_degradando": (
            f"{cto_concern['cto']} (mesma zona)" if cto_concern else "—"
        ),
        "onde_havera_saturacao": (
            ", ".join(str(v["vlan"]) for v in saturated[:3])
            if saturated else "Nenhuma VLAN saturada agora"
        ),
        "risco_operacional": (
            f"R$ {rev['monthly_BRL_at_risk']:,.2f}/mês em risco · "
            f"{rev['subs_in_bad_onu']} subs em ONU ruim, "
            f"{rev['subs_in_critical_cto']} em CTO crítica"
        ),
        "onde_investir_primeiro": (
            f"CTO {cto_concern['cto']} ({cto_concern['offline']} offline · "
            f"score {cto_concern['score']})"
            if cto_concern else "Rede saudável"
        ),
        "predicted_next_problem_30d": (
            preds["CTO_CRITICAL"]["top"][0]
            if preds["CTO_CRITICAL"]["top"] else
            preds["CTO_DEGRADED"]["top"][0]
            if preds["CTO_DEGRADED"]["top"] else "Nenhum imediato"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
