"""
failure_risk.py — Constituição V5.0 / Sprint 2
Fase C: failure_risk_score composto (0-100) — AGREGADOR.

Regra mestra: NÃO criar predição nova. Compor os 6 sinais que já existem:
  1. SmartOLT (ONU status / signal_1310 / CTO health)
  2. Histórico de tickets (30d / 90d via tickets collection)
  3. Recurrence Score (services.alvaro_v5)
  4. Histórico de sinal (rx_dbm via smartolt_onus + ai_preventive_suggestions)
  5. Saúde da CTO (services.smartolt_twin.cto_health)
  6. Churn técnico (motor_ia_subscriber_scores.churn_score)

Classificação: 0-30 BAIXO · 31-60 MEDIO · 61-80 ALTO · 81-100 CRITICO
Quando > 80: emite evento FAILURE_RISK_HIGH → autonomous_engine roda
ciclo completo Decision V5 → Action(create_preventive_os) → Outcome → Learning.

Persiste em motor_ia_failure_risk_scores (upsert por subscriber_id+company_id).
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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# Pesos auditáveis (soma = 100)
WEIGHTS = {
    "onu_status":        20,   # LOS/Power Fail/Offline pesa muito
    "signal_degraded":   15,   # rx_dbm degradado
    "tickets_recent":    15,   # tickets 30d
    "recurrence":        15,   # recurrence_score do Sprint 1
    "cto_health":        15,   # CTO em estado crítico
    "churn_score":       15,   # churn_score da Isabella
    "incidents_region":   5,   # incidentes na mesma zona 7d
}

BAD_ONU = {"offline", "los", "power fail", "power_fail"}


def _classify(score: float) -> str:
    if score >= 81:
        return "CRITICO"
    if score >= 61:
        return "ALTO"
    if score >= 31:
        return "MEDIO"
    return "BAIXO"


async def _onu_signal_points(sub: Dict[str, Any]) -> Dict[str, Any]:
    """Pontuação combinada ONU status + sinal degradado."""
    status_raw = (sub.get("smartolt_onu_status") or "").strip()
    status = status_raw.lower()
    onu_pts = 0
    if status in BAD_ONU:
        onu_pts = WEIGHTS["onu_status"]
    elif status == "warning":
        onu_pts = WEIGHTS["onu_status"] * 0.6

    # Sinal degradado via smartolt_onus.signal_1310 (dbm string ou número)
    sn = sub.get("smartolt_onu_sn")
    rx = None
    if sn:
        onu = await db.smartolt_onus.find_one(
            {"sn": sn}, {"signal_1310": 1})
        if onu:
            try:
                rx = float(str(onu.get("signal_1310")).replace(",", "."))
            except (TypeError, ValueError):
                rx = None
    signal_pts = 0
    if rx is not None:
        if rx <= -29:
            signal_pts = WEIGHTS["signal_degraded"]
        elif rx <= -27:
            signal_pts = WEIGHTS["signal_degraded"] * 0.7
        elif rx <= -25:
            signal_pts = WEIGHTS["signal_degraded"] * 0.4

    return {
        "onu_status": status_raw or "Unknown",
        "onu_status_pts": round(onu_pts, 2),
        "rx_dbm": rx,
        "signal_pts": round(signal_pts, 2),
    }


async def _tickets_points(
    company_id: str, subscriber_id: str
) -> Dict[str, Any]:
    """Pontuação por tickets recentes (30d)."""
    n30 = await db.tickets.count_documents({
        "company_id": company_id, "client_id": subscriber_id,
        "opened_at": {"$gte": _cutoff(30)},
    })
    # cada ticket = 3pts até cap de WEIGHTS["tickets_recent"]
    pts = min(n30 * 3.0, WEIGHTS["tickets_recent"])
    return {"tickets_30d": n30, "pts": round(pts, 2)}


async def _recurrence_points(
    company_id: str, subscriber_id: str
) -> Dict[str, Any]:
    """Reutiliza recurrence_score do Sprint 1."""
    doc = await db.motor_ia_recurrence_scores.find_one(
        {"subscriber_id": subscriber_id, "company_id": company_id})
    if not doc:
        # Computa on-the-fly se não existir
        from services import alvaro_v5
        doc = await alvaro_v5.compute_recurrence_score(
            subscriber_id, company_id=company_id, persist=True)
    rec_score = float(doc.get("score") or 0)
    pts = (rec_score / 100.0) * WEIGHTS["recurrence"]
    return {
        "recurrence_score": rec_score,
        "classification": doc.get("classification"),
        "pts": round(pts, 2),
    }


async def _cto_points(
    company_id: str, sub: Dict[str, Any]
) -> Dict[str, Any]:
    """Pontuação por saúde da CTO onde o cliente está.
    Sem cache: cto_health é chamado por driver em batch (1x por loop)."""
    cto = sub.get("smartolt_onu_zone")
    if not cto:
        return {"cto": None, "cto_score": None, "pts": 0}
    from services.smartolt_twin import cto_health
    items = await cto_health(company_id)
    cto_doc = next((x for x in items if x.get("cto") == cto), {}) or {}
    raw_score = cto_doc.get("score")
    cto_score = float(raw_score) if raw_score is not None else 100.0
    pts = (1.0 - (cto_score / 100.0)) * WEIGHTS["cto_health"]
    return {
        "cto": cto,
        "cto_score": cto_score,
        "cto_level": cto_doc.get("level"),
        "pts": round(pts, 2),
    }


async def _churn_points(
    company_id: str, subscriber_id: str
) -> Dict[str, Any]:
    """Reutiliza churn_score da Isabella."""
    doc = await db.motor_ia_subscriber_scores.find_one(
        {"subscriber_id": subscriber_id, "company_id": company_id},
        {"churn_score": 1})
    cs = float((doc or {}).get("churn_score") or 0)
    pts = cs * WEIGHTS["churn_score"]
    return {"churn_score": cs, "pts": round(pts, 2)}


async def _region_incidents_points(
    company_id: str, sub: Dict[str, Any]
) -> Dict[str, Any]:
    """Pontuação por incidentes na mesma zona nos últimos 7d."""
    cto = sub.get("smartolt_onu_zone")
    if not cto:
        return {"region_incidents_7d": 0, "pts": 0}
    sub_ids = await db.subscribers.distinct(
        "id", {"company_id": company_id, "smartolt_onu_zone": cto})
    if not sub_ids:
        return {"region_incidents_7d": 0, "pts": 0}
    n = await db.tickets.count_documents({
        "company_id": company_id,
        "client_id": {"$in": sub_ids},
        "opened_at": {"$gte": _cutoff(7)},
    })
    pts = min(n * 0.5, WEIGHTS["incidents_region"])
    return {"region_incidents_7d": n, "pts": round(pts, 2)}


async def compute_failure_risk(
    subscriber_id: str,
    company_id: Optional[str] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    """Compõe os 6 sinais e devolve failure_risk_score 0-100.

    Emite evento FAILURE_RISK_HIGH (consumed=False) quando score > 80.
    """
    sub = await db.subscribers.find_one({"id": subscriber_id})
    if not sub:
        return {
            "subscriber_id": subscriber_id, "found": False,
            "score": 0, "classification": "BAIXO",
        }
    cid = company_id or sub.get("company_id")

    onu = await _onu_signal_points(sub)
    tk = await _tickets_points(cid, subscriber_id)
    rec = await _recurrence_points(cid, subscriber_id)
    cto = await _cto_points(cid, sub)
    churn = await _churn_points(cid, subscriber_id)
    reg = await _region_incidents_points(cid, sub)

    breakdown = {
        "onu_status_pts": onu["onu_status_pts"],
        "signal_pts": onu["signal_pts"],
        "tickets_pts": tk["pts"],
        "recurrence_pts": rec["pts"],
        "cto_pts": cto["pts"],
        "churn_pts": churn["pts"],
        "region_incidents_pts": reg["pts"],
    }
    score = round(min(sum(breakdown.values()), 100.0), 1)
    classification = _classify(score)

    # Evidência auditável (Regra de Ouro)
    evidence: List[Dict[str, Any]] = [
        {"type": "onu_status", "value": onu["onu_status"],
         "source": "subscribers/smartolt_onus"},
        {"type": "rx_dbm", "value": onu["rx_dbm"],
         "source": "smartolt_onus"},
        {"type": "tickets_30d", "value": tk["tickets_30d"],
         "source": "tickets"},
        {"type": "recurrence_score", "value": rec["recurrence_score"],
         "source": "motor_ia_recurrence_scores"},
        {"type": "cto_health_score", "value": cto["cto_score"],
         "source": "smartolt_twin.cto_health"},
        {"type": "churn_score", "value": churn["churn_score"],
         "source": "motor_ia_subscriber_scores"},
        {"type": "region_incidents_7d",
         "value": reg["region_incidents_7d"], "source": "tickets"},
    ]

    plan_price = float(sub.get("plan_price") or 0)
    doc = {
        "id": f"frs-{uuid.uuid4().hex[:10]}",
        "subscriber_id": subscriber_id,
        "company_id": cid,
        "score": score,
        "classification": classification,
        "breakdown": breakdown,
        "evidence": evidence,
        "raw": {
            "onu_status": onu["onu_status"],
            "rx_dbm": onu["rx_dbm"],
            "tickets_30d": tk["tickets_30d"],
            "recurrence_score": rec["recurrence_score"],
            "cto": cto["cto"], "cto_score": cto["cto_score"],
            "churn_score": churn["churn_score"],
            "region_incidents_7d": reg["region_incidents_7d"],
            "plan_price_BRL": plan_price,
        },
        "expected_revenue_at_risk_BRL": round(
            plan_price * (score / 100.0), 2),
        "should_open_preventive_os": score > 80,
        "computed_at": _now_iso(),
    }

    if persist:
        await db.motor_ia_failure_risk_scores.update_one(
            {"subscriber_id": subscriber_id, "company_id": cid},
            {"$set": doc}, upsert=True,
        )
        if score > 80:
            await db.motor_ia_events.insert_one({
                "id": f"evt-{uuid.uuid4().hex[:12]}",
                "event_id": f"evt-{uuid.uuid4().hex[:12]}",
                "event_type": "FAILURE_RISK_HIGH",
                "company_id": cid,
                "subscriber_id": subscriber_id,
                "payload": {
                    "failure_risk_score": score,
                    "classification": classification,
                    "expected_revenue_at_risk_BRL":
                        doc["expected_revenue_at_risk_BRL"],
                    "raw": doc["raw"],
                },
                "consumed": False,
                "created_at": _now_iso(),
                "timestamp": _now_iso(),
            })
    return doc


async def drive_from_failure_risk(
    company_id: str, limit: int = 200,
) -> Dict[str, Any]:
    """Varre assinantes ativos, computa failure_risk_score, dispara ciclo
    autônomo para os que cruzam 80.

    Reutiliza autonomous_engine.run_cycle para Decision V5 → Action
    create_preventive_os → Outcome → Learning. Sem código duplicado.
    """
    # Re-importa db dinamicamente para honrar `database.db` rebinds em
    # testes (test_*.py faz `dm.db = new_client`). Sem isso, o binding
    # do topo do módulo aponta para o cliente antigo após reload.
    from database import db as _db
    subs = await _db.subscribers.find(
        {"company_id": company_id, "status": {"$ne": "inactive"}},
        {"id": 1},
    ).limit(limit).to_list(limit)

    processed = 0
    critical = 0
    cycled = 0
    cycle_ids: List[str] = []

    from services import autonomous_engine as eng

    for s in subs:
        try:
            r = await compute_failure_risk(
                s["id"], company_id=company_id, persist=True)
            processed += 1
            if r["classification"] == "CRITICO":
                critical += 1
            if r["score"] > 80:
                cycle = await eng.run_cycle({
                    "event_type": "FAILURE_RISK_HIGH",
                    "company_id": company_id,
                    "subscriber_id": s["id"],
                    "payload": {
                        "failure_risk_score": r["score"],
                        "classification": r["classification"],
                        "expected_revenue_at_risk_BRL":
                            r["expected_revenue_at_risk_BRL"],
                        "raw": r["raw"],
                    },
                })
                cycle_ids.append(cycle["cycle_id"])
                cycled += 1
        except Exception as e:  # noqa: BLE001
            # Logamos para auditoria. NÃO silenciar bug em testes.
            import logging
            logging.getLogger("failure_risk").warning(
                "drive failed for %s: %r", s.get("id"), e)
            continue

    return {
        "company_id": company_id,
        "processed": processed,
        "critical_count": critical,
        "preventive_cycles_triggered": cycled,
        "cycle_ids": cycle_ids[:50],
        "generated_at": _now_iso(),
    }


async def distribution(company_id: str) -> Dict[str, Any]:
    """Distribuição de failure_risk em buckets (BAIXO/MEDIO/ALTO/CRITICO).

    Usado pelo card "Predições" do Command Center V5.1.
    `is_calibrated=True` quando há ≥ 20 subs scorados (heurística leve).
    """
    from database import db as _db
    buckets = {"BAIXO": 0, "MEDIO": 0, "ALTO": 0, "CRITICO": 0}
    total = 0
    async for s in _db.motor_ia_failure_risk_scores.find(
            {"company_id": company_id}, {"classification": 1, "score": 1}):
        total += 1
        cls = s.get("classification")
        if cls in buckets:
            buckets[cls] += 1
        else:
            sc = s.get("score") or 0
            buckets[_classify(sc)] += 1
    is_calibrated = total >= 20
    if not is_calibrated:
        note = (f"Modelo em calibração ({total} scorados). "
                f"Aguarde scheduler completar próximas rodadas.")
    else:
        critic_pct = round((buckets["CRITICO"] / total) * 100, 1)
        note = (f"{buckets['CRITICO']} críticos · "
                f"{critic_pct}% da base requer ação preventiva")
    bucket_list = [
        {"label": k, "count": v,
         "pct": round((v / total) * 100, 1) if total else 0.0}
        for k, v in buckets.items()
    ]
    return {
        "company_id": company_id,
        "total": total,
        "buckets": bucket_list,
        "is_calibrated": is_calibrated,
        "note": note,
        "generated_at": _now_iso(),
    }




# ─────────────────────── Fase H — Métricas ───────────────────────
async def phase_h_metrics(
    company_id: str, window_days: int = 30,
) -> Dict[str, Any]:
    """Métricas de prevenção: preventive_ratio, prevented_churn_BRL,
    prevented_revenue_loss_BRL.

    - corrective_count: actions com kind 'preventive_ticket' mas vindas
      de eventos REATIVOS (ONU_DEGRADED, OVERDUE_DETECTED, etc.)
    - preventive_count: ciclos disparados por FAILURE_RISK_HIGH
      (proativos).
    - preventive_ratio = preventive / (preventive + corrective)
    - prevented_churn_BRL: soma de `expected_revenue_at_risk_BRL` dos
      scores CRITICO que GERARAM ciclo preventivo no período.
    - prevented_revenue_loss_BRL: soma de `actual_BRL` em outcomes de
      ciclos preventivos (receita realmente recuperada).
    """
    cutoff = _cutoff(window_days)

    # Ciclos preventivos no período (event_type FAILURE_RISK_HIGH)
    preventive_cycles = await db.motor_ia_autonomous_cycles.find({
        "company_id": company_id,
        "started_at": {"$gte": cutoff},
    }).to_list(None)
    preventive_ids = []
    preventive_count = 0
    actual_recovered = 0.0
    expected_recovered = 0.0
    for c in preventive_cycles:
        ev = await db.motor_ia_events.find_one(
            {"event_id": c.get("event_id")},
            {"event_type": 1, "payload": 1})
        if not ev or ev.get("event_type") != "FAILURE_RISK_HIGH":
            continue
        preventive_count += 1
        preventive_ids.append(c.get("cycle_id"))
        actual_recovered += float(c.get("actual_BRL") or 0)
        expected_recovered += float(c.get("expected_BRL") or 0)

    # Ciclos corretivos no período (eventos reativos)
    reactive_types = {"ONU_DEGRADED", "OVERDUE_DETECTED",
                      "ISABELLA_HIGH_CHURN", "TICKET_OPENED"}
    corrective_count = 0
    for c in preventive_cycles:
        ev = await db.motor_ia_events.find_one(
            {"event_id": c.get("event_id")}, {"event_type": 1})
        if ev and ev.get("event_type") in reactive_types:
            corrective_count += 1

    total = preventive_count + corrective_count
    ratio = (preventive_count / total) if total > 0 else 0.0

    # Prevented churn: soma do plan_price dos subs com FRS > 80 que
    # tiveram ciclo no período.
    prevented_churn_BRL = 0.0
    async for s in db.motor_ia_failure_risk_scores.find({
        "company_id": company_id, "score": {"$gt": 80},
        "computed_at": {"$gte": cutoff},
    }):
        prevented_churn_BRL += float(
            s.get("expected_revenue_at_risk_BRL") or 0)

    return {
        "company_id": company_id,
        "window_days": window_days,
        "preventive_count": preventive_count,
        "corrective_count": corrective_count,
        "preventive_ratio": round(ratio, 3),
        "prevented_churn_BRL": round(prevented_churn_BRL, 2),
        "prevented_revenue_loss_BRL": round(actual_recovered, 2),
        "expected_recovered_BRL": round(expected_recovered, 2),
        "generated_at": _now_iso(),
    }
