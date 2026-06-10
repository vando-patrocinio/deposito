"""ISABELLA DIGITAL TWIN — previsão de falha em ativos REAIS.

Não é dashboard. Não é monitor. PREVÊ:
  • CTO que vai falhar (tendência crescente de reparos)
  • ONU/cliente que vai cair (sinal piorando + reparos repetidos)
  • Região que vai degradar (tickets ascendentes por bairro)
  • Veículo que vai quebrar (sem inspeção há > N dias, km alto, multas)
  • Estoque que vai zerar (saídas recentes > saldo / consumo médio)
  • Técnico que vai atrasar (% atraso semanal subindo)

Gera `isabella_opportunities(kind=twin)` com janela de previsão em dias.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from database import db
from services.event_bus import EventType, emit_event
from services.isabella_opportunities import upsert_opportunity

log = logging.getLogger("ponto.isabella_twin")

REPAIR_TYPES = ("reparo", "lentidao", "lentidão", "wifi_ruim",
                  "sem internet", "ONU_LOW_SIGNAL", "ONU_OFFLINE")


def _now():
    return datetime.now(timezone.utc)


async def _cto_failure_risk(company_id: str) -> int:
    """CTO com reparos crescentes 14d vs 14d anteriores ≥ 2× ou ≥ 6 totais."""
    now = _now()
    w1_start = (now - timedelta(days=14)).isoformat()
    w2_start = (now - timedelta(days=28)).isoformat()
    pipe = [
        {"$match": {"company_id": company_id,
                      "type": {"$in": list(REPAIR_TYPES)},
                      "opened_at": {"$gte": w2_start}}},
        {"$group": {
            "_id": "$atlaz_id_ponto",
            "n_recent": {"$sum": {"$cond": [
                {"$gte": ["$opened_at", w1_start]}, 1, 0]}},
            "n_prev": {"$sum": {"$cond": [
                {"$lt": ["$opened_at", w1_start]}, 1, 0]}},
        }},
    ]
    created = 0
    async for r in db.tickets.aggregate(pipe):
        cto_key = r.get("_id")
        if not cto_key:
            continue
        n_rec = int(r["n_recent"] or 0)
        n_prev = int(r["n_prev"] or 0)
        trend = n_rec >= 6 or (n_rec >= 3 and n_rec >= 2 * max(n_prev, 1))
        if not trend:
            continue
        score = min(100.0, 50 + (n_rec * 5) + (n_rec - n_prev) * 4)
        prob = min(0.9, 0.35 + n_rec * 0.04)
        # Tenta enriquecer com cto_ports
        cto = await db.cto_ports.find_one(
            {"company_id": company_id, "cto_id": cto_key},
            {"_id": 0, "cto_id": 1, "cto_name": 1, "neighborhood": 1,
             "olt_name": 1, "lat": 1, "lng": 1})
        label = (cto and cto.get("cto_name")) or str(cto_key)
        await upsert_opportunity(
            company_id=company_id,
            kind="twin",
            subkind="cto_failure_risk",
            target_type="cto",
            target_id=str(cto_key),
            target_label=label,
            score=score,
            probability=prob,
            impact_brl=n_rec * 250.0,
            reason_codes=[f"{n_rec} reparos em 14d vs {n_prev} no período anterior"],
            evidence={"n_recent_14d": n_rec, "n_prev_14d": n_prev,
                        "cto": cto, "olt_name": (cto or {}).get("olt_name"),
                        "neighborhood": (cto or {}).get("neighborhood")},
            recommended_action={"type": "schedule_preventive",
                                  "channel": "field_ops",
                                  "playbook": "preventiva_cto",
                                  "cto_id": cto_key,
                                  "requires_approval": True},
            ttl_hours=72,
            source="isabella_twin",
        )
        created += 1
        await emit_event(
            EventType.TWIN_FAILURE_PREDICTED,
            company_id=company_id, source="isabella_twin",
            severity="alta",
            payload={"asset": "cto", "cto_id": cto_key,
                      "n_recent": n_rec, "n_prev": n_prev, "score": score})
    return created


async def _onu_signal_degradation(company_id: str) -> int:
    """ONU com signal_1490 piorando ou abaixo de -27 dBm."""
    cur = db.smartolt_onus.find(
        {"company_id": company_id,
         "signal_1490": {"$exists": True, "$ne": None}},
        {"_id": 0, "id": 1, "sn": 1, "name": 1, "olt_name": 1,
         "signal_1490": 1, "signal_history_24h": 1, "address": 1,
         "unique_external_id": 1}
    ).limit(2000)
    created = 0
    async for o in cur:
        try:
            sig_now = float(o.get("signal_1490"))
        except Exception:
            continue
        hist = o.get("signal_history_24h") or []
        worsening = False
        baseline = None
        if isinstance(hist, list) and len(hist) >= 3:
            try:
                values = [float(h.get("signal_1490")) for h in hist
                            if h and h.get("signal_1490") is not None]
                if values:
                    baseline = sum(values) / len(values)
                    worsening = sig_now < baseline - 1.5
            except Exception:
                pass
        critical = sig_now <= -27.0
        if not (worsening or critical):
            continue
        score = 60 + (abs(sig_now + 25) * 2) + (10 if critical else 0)
        score = min(100.0, score)
        prob = min(0.9, 0.4 + (abs(sig_now + 25) * 0.03))
        await upsert_opportunity(
            company_id=company_id,
            kind="twin",
            subkind="onu_degradation",
            target_type="onu",
            target_id=o.get("sn") or o.get("id") or "",
            target_label=o.get("name") or o.get("sn") or "ONU",
            score=score,
            probability=prob,
            impact_brl=200.0,
            reason_codes=[
                f"Sinal 1490 atual {sig_now:.1f} dBm" +
                (f" (média 24h {baseline:.1f})" if baseline else "")
            ],
            evidence={"signal_1490": sig_now,
                        "baseline_24h": baseline,
                        "olt_name": o.get("olt_name"),
                        "sn": o.get("sn"),
                        "address": o.get("address")},
            recommended_action={"type": "schedule_repair",
                                  "channel": "field_ops",
                                  "playbook": "reparo_optico_proativo",
                                  "sn": o.get("sn"),
                                  "requires_approval": True},
            ttl_hours=48,
            source="isabella_twin",
        )
        created += 1
    return created


async def _vehicle_breakdown_risk(company_id: str) -> int:
    """Veículos sem inspeção há > N dias ou km elevado."""
    fleet = await db.fleet_vehicles.find(
        {"company_id": company_id, "status": {"$ne": "inativo"}},
        {"_id": 0, "id": 1, "placa": 1, "modelo": 1, "km_atual": 1,
         "history": 1, "weekly_inspection_required": 1}
    ).to_list(5000)
    created = 0
    cutoff_iso = (_now() - timedelta(days=14)).isoformat()
    for v in fleet:
        history = v.get("history") or []
        last_insp = None
        for h in reversed(history):
            if (h or {}).get("type") in ("inspection", "vehicle_inspection",
                                            "checklist"):
                last_insp = h.get("at") or h.get("created_at")
                break
        no_insp = (not last_insp) or (last_insp < cutoff_iso)
        km_high = (v.get("km_atual") or 0) >= 80000
        if not (no_insp or km_high):
            continue
        score = 40 + (25 if no_insp else 0) + (20 if km_high else 0)
        await upsert_opportunity(
            company_id=company_id,
            kind="twin",
            subkind="vehicle_breakdown_risk",
            target_type="vehicle",
            target_id=v["id"],
            target_label=v.get("placa") or v.get("modelo") or v["id"],
            score=min(100.0, score),
            probability=0.55,
            impact_brl=1500.0,  # custo médio de pane mecânica
            reason_codes=[
                "Sem inspeção semanal recente" if no_insp else "",
                f"KM atual {v.get('km_atual')}" if km_high else ""
            ],
            evidence={"placa": v.get("placa"), "modelo": v.get("modelo"),
                        "km_atual": v.get("km_atual"),
                        "last_inspection_at": last_insp},
            recommended_action={"type": "schedule_inspection",
                                  "channel": "fleet",
                                  "vehicle_id": v["id"],
                                  "requires_approval": True},
            ttl_hours=168,
            source="isabella_twin",
        )
        created += 1
    return created


async def scan_company(company_id: str) -> Dict[str, Any]:
    cto = await _cto_failure_risk(company_id)
    onu = await _onu_signal_degradation(company_id)
    veh = await _vehicle_breakdown_risk(company_id)
    return {"company_id": company_id,
            "predictions": {"cto": cto, "onu": onu, "vehicle": veh},
            "total": cto + onu + veh}


async def scan_all() -> List[Dict[str, Any]]:
    out = []
    cids = await db.companies.distinct("id")
    for cid in cids:
        try:
            out.append(await scan_company(cid))
        except Exception as e:
            log.exception("[twin] %s failed: %s", cid, e)
    return out
