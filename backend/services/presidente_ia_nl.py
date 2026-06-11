"""
presidente_ia_nl.py — V6.2 FASE 5
Linguagem natural. Responde em português executivo direto.
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

from datetime import datetime, timezone
from typing import Any, Dict

from database import db
from services import financial_foundation as fin
from services import real_revenue
from services import autonomous_engine as eng
from services import blockers_audit


def _brl(v: float) -> str:
    return f"R$ {(v or 0):,.2f}"


async def daily_natural(company_id: str) -> Dict[str, Any]:
    rev = await real_revenue.revenue_breakdown(company_id, days=1)
    fa = await fin.summary(company_id)
    score = await eng.compute_autonomy_score(company_id, days=1)
    blk = await blockers_audit.full_audit(company_id)
    prio = await real_revenue.roi_priorities(company_id)

    biggest_blocker = (blk["blockers"][0] if blk["blockers"] else None)
    biggest_roi = (prio[0] if prio else None)

    narrative = [
        (f"Hoje a IA gerou {_brl(rev['received']['BRL'])} de receita "
         f"realmente recebida, com {rev['received']['count']} eventos."),
        (f"Confirmamos {_brl(rev['confirmed']['BRL'])} em ações "
         f"executadas e estimamos {_brl(rev['estimated']['BRL'])} em "
         f"pipeline."),
        (f"Autonomy Score: {score['score']}% "
         f"({score['classification'].replace('_', ' ')})."),
        (f"Receita em risco neste momento: "
         f"{_brl(fa['revenue_at_risk']['monthly_BRL_at_risk'])}/mês "
         f"({fa['revenue_at_risk']['subscribers_at_risk']} clientes)."),
    ]

    if biggest_blocker:
        narrative.append(
            f"Maior bloqueador: {biggest_blocker['blocker']} "
            f"({biggest_blocker['priority']}) — "
            f"{biggest_blocker['how_to_resolve']}.")

    if biggest_roi:
        narrative.append(
            f"Maior ROI agora: {biggest_roi['label']} "
            f"({_brl(biggest_roi['roi_BRL'])}). "
            f"Ação: {biggest_roi['action']}.")

    if not biggest_blocker and not biggest_roi:
        narrative.append("Não há bloqueadores nem oportunidades pendentes.")

    # ─── Sistema Nervoso (Fase 5 — Nervous Foundation) ──────────
    nervous_brief = None
    try:
        from services.nervous_autodiscovery import _calc_sustained_coverage
        latest = await db.nervous_coverage_history.find_one(
            {}, {"_id": 0}, sort=[("ts", -1)])
        if latest:
            sustained = await _calc_sustained_coverage()
            cov = latest.get("coverage_pct", 0)
            silent_n = latest.get("silent_critical_count", 0)
            regs = len(latest.get("regressions", []))
            risk = ("VERDE" if (silent_n == 0 and regs == 0 and cov >= 80)
                     else "AMARELO" if (silent_n == 0 and regs == 0)
                     else "VERMELHO")
            nervous_brief = {
                "coverage_pct": cov,
                "sustained_30d_pct": sustained,
                "silent_critical": silent_n,
                "regressions": regs,
                "risk_level": risk,
            }
            line = (f"Sistema Nervoso: {cov}% cobertura · sustained 30d "
                     f"{sustained}% · risco {risk}.")
            if silent_n > 0:
                line += f" 🚨 {silent_n} módulo(s) crítico(s) sem metadata."
            if regs > 0:
                line += f" 🔴 {regs} regressão(ões) detectada(s)."
            narrative.append(line)
    except Exception:
        pass

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "company_id": company_id,
        "narrative": " ".join(narrative),
        "narrative_lines": narrative,
        "revenue_today": rev,
        "blocking_growth": biggest_blocker,
        "highest_roi": biggest_roi,
        "autonomy_score": score["score"],
        "nervous_foundation": nervous_brief,
    }
