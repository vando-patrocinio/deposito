"""
presidente_ia_nl.py — V6.2 FASE 5
Linguagem natural. Responde em português executivo direto.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict

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

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "company_id": company_id,
        "narrative": " ".join(narrative),
        "narrative_lines": narrative,
        "revenue_today": rev,
        "blocking_growth": biggest_blocker,
        "highest_roi": biggest_roi,
        "autonomy_score": score["score"],
    }
