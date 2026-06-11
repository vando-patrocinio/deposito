"""Score heurístico (e analise IA opcional) para serviços do técnico.

Avalia em tempo real:
- Distância da posição atual do técnico ao endereço do serviço (rota)
- Tempo decorrido vs SLA do tipo (overshoot %)
- Histórico de duração média do técnico para esse tipo
- Gaps muito longos entre serviços
- Geo-fence violations recentes (clock-records fora da cerca nos últimos N records)

Retorna {score: 0-10, label: "Excelente"/"Bom"/"Atenção"/"Crítico", signals: [...]}.
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

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from database import db


def _haversine_m(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    R = 6371000
    p1 = math.radians(a_lat)
    p2 = math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lng - a_lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _ticket_duration_minutes(t: dict) -> Optional[float]:
    """Duração em minutos: closed_at - opened_at (ou now - opened_at se ainda aberta)."""
    opened = t.get("opened_at")
    if not opened:
        return None
    try:
        op = datetime.fromisoformat(opened.replace("Z", "+00:00"))
        if op.tzinfo is None:
            op = op.replace(tzinfo=timezone.utc)
        end_iso = t.get("closed_at")
        if end_iso:
            end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
        else:
            end = datetime.now(timezone.utc)
        return max(0.0, (end - op).total_seconds() / 60.0)
    except Exception:
        return None


async def _avg_history_minutes(cid: str, ttype: str) -> Optional[float]:
    """Média de duração histórica do técnico para esse tipo (últimos 30d, finalizados)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    docs = await db.tickets.find(
        {"assigned_collaborator_id": cid, "type": ttype,
         "status": "finalizada", "closed_at": {"$gte": cutoff},
         "opened_at": {"$ne": None}},
        {"_id": 0, "opened_at": 1, "closed_at": 1},
    ).to_list(50)
    durs = []
    for d in docs:
        m = _ticket_duration_minutes(d)
        if m is not None and m > 0:
            durs.append(m)
    if not durs:
        return None
    return sum(durs) / len(durs)


async def _recent_fence_violations(cid: str) -> int:
    """Número de clock-records fora da cerca nas últimas 24h."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    return await db.clock_records.count_documents({
        "collaborator_id": cid,
        "created_at": {"$gte": cutoff},
        "inside_fence": False,
    })


async def heuristic_score_for_ticket(
    ticket: dict,
    *,
    sla_minutes: int,
    current_position: Optional[dict] = None,  # {lat, lng}
    long_gap_threshold_min: int = 90,
) -> dict:
    """Score determinístico de 0 a 10 baseado em sinais combinados.

    Pontuação inicial: 10. Penalidades por sinal (cumulativas, mín 0).
    Bônus por sinais positivos.
    """
    signals: list[dict] = []
    score = 10.0
    cid = ticket.get("assigned_collaborator_id")
    ttype = ticket.get("type", "reparo")

    # --- 1) Distância à origem do serviço (se posição atual disponível) ---
    snap = ticket.get("client_snapshot") or {}
    t_lat = snap.get("latitude")
    t_lng = snap.get("longitude")
    if current_position and t_lat is not None and t_lng is not None:
        try:
            d_m = _haversine_m(float(current_position["lat"]), float(current_position["lng"]),
                               float(t_lat), float(t_lng))
            if d_m < 200:
                signals.append({"type": "rota", "level": "ok",
                                "msg": f"No local do serviço (~{int(d_m)}m)", "weight": 0})
            elif d_m < 1500:
                score -= 1.0
                signals.append({"type": "rota", "level": "warning",
                                "msg": f"A {int(d_m)}m do endereço — verifique rota", "weight": -1})
            else:
                score -= 2.5
                signals.append({"type": "rota", "level": "critical",
                                "msg": f"Distante {(d_m/1000):.1f}km do endereço — rota incorreta?",
                                "weight": -2.5})
        except Exception:
            pass

    # --- 2) Tempo decorrido vs SLA ---
    if ticket.get("status") == "aberta":
        elapsed = _ticket_duration_minutes(ticket)
        if elapsed is not None and sla_minutes > 0:
            pct = (elapsed / sla_minutes) * 100
            if pct >= 150:
                score -= 3.0
                signals.append({"type": "sla", "level": "critical",
                                "msg": f"SLA estourado em {pct - 100:.0f}% (durou {elapsed:.0f}min de {sla_minutes}min)",
                                "weight": -3})
            elif pct >= 100:
                score -= 1.5
                signals.append({"type": "sla", "level": "warning",
                                "msg": f"SLA estourado ({elapsed:.0f}/{sla_minutes}min)",
                                "weight": -1.5})
            elif pct >= 80:
                score -= 0.5
                signals.append({"type": "sla", "level": "warning",
                                "msg": f"Próximo do SLA ({pct:.0f}%)", "weight": -0.5})
            else:
                signals.append({"type": "sla", "level": "ok",
                                "msg": f"Dentro do SLA ({pct:.0f}%)", "weight": 0})

    # --- 3) Histórico vs SLA ---
    if cid:
        avg_hist = await _avg_history_minutes(cid, ttype)
        if avg_hist is not None and sla_minutes > 0:
            ratio = avg_hist / sla_minutes
            if ratio < 0.7:
                score += 0.5
                signals.append({"type": "historico", "level": "ok",
                                "msg": f"Média histórica {avg_hist:.0f}min — rápido para {ttype}",
                                "weight": +0.5})
            elif ratio > 1.3:
                score -= 1.0
                signals.append({"type": "historico", "level": "warning",
                                "msg": f"Média histórica {avg_hist:.0f}min — lento para {ttype}",
                                "weight": -1})

    # --- 4) Gap longo desde o último serviço encerrado ---
    if cid:
        last_closed = await db.tickets.find_one(
            {"assigned_collaborator_id": cid,
             "status": {"$in": ["finalizada", "encerrada"]},
             "closed_at": {"$ne": None}},
            {"_id": 0, "closed_at": 1},
            sort=[("closed_at", -1)],
        )
        if last_closed and ticket.get("opened_at"):
            try:
                lc = datetime.fromisoformat(last_closed["closed_at"].replace("Z", "+00:00"))
                op = datetime.fromisoformat(ticket["opened_at"].replace("Z", "+00:00"))
                if lc.tzinfo is None:
                    lc = lc.replace(tzinfo=timezone.utc)
                if op.tzinfo is None:
                    op = op.replace(tzinfo=timezone.utc)
                gap_min = (op - lc).total_seconds() / 60.0
                if gap_min > long_gap_threshold_min:
                    score -= 1.0
                    signals.append({"type": "gap", "level": "warning",
                                    "msg": f"Gap de {gap_min:.0f}min desde último serviço",
                                    "weight": -1})
            except Exception:
                pass

    # --- 5) Geo-fence violations recentes ---
    if cid:
        viols = await _recent_fence_violations(cid)
        if viols >= 3:
            score -= 1.5
            signals.append({"type": "cerca", "level": "critical",
                            "msg": f"{viols} pontos batidos fora da cerca em 24h",
                            "weight": -1.5})
        elif viols >= 1:
            score -= 0.5
            signals.append({"type": "cerca", "level": "warning",
                            "msg": f"{viols} ponto(s) fora da cerca em 24h",
                            "weight": -0.5})

    score = max(0.0, min(10.0, score))
    if score >= 8.5:
        label = "Excelente"
    elif score >= 7.0:
        label = "Bom"
    elif score >= 5.0:
        label = "Atenção"
    else:
        label = "Crítico"

    return {
        "score": round(score, 1),
        "label": label,
        "signals": signals,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "method": "heuristic",
    }


def compute_duration_minutes(t: dict) -> Optional[float]:
    """Wrapper público — duração de um serviço em minutos (None se nunca aberto)."""
    return _ticket_duration_minutes(t)
