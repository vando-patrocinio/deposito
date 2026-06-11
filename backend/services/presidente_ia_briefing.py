"""
presidente_ia_briefing.py — Café com a IA do CEO (iter219)

Briefing executivo diário no WhatsApp: ao acordar, o gestor recebe
2-3 linhas com a saúde da empresa, top risco do dia e top oportunidade.

Hook é chamado pelo `conselho_ia_scheduler._worker_loop()` quando
`conselho_ia_settings.presidente_briefing_enabled = True`.
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

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database import db
from services import presidente_ia as svc

logger = logging.getLogger(__name__)


HEALTH_EMOJI = {
    "saudavel": "🟢",
    "atencao": "🟡",
    "alerta": "🟠",
    "critico": "🔴",
}


def _format_brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",") \
        .replace("X", ".")


async def build_briefing_text(cid: str) -> Dict[str, Any]:
    """Monta o texto curto do briefing executivo."""
    health = await svc.compute_corporate_health(cid)
    risks = await svc.compute_risks(cid, health)
    opps = await svc.compute_opportunities(cid)

    top_risk = None
    for level in ("criticos", "altos", "medios"):
        lst = risks.get(level) or []
        if lst:
            top_risk = lst[0]
            break

    top_opp = None
    items = (opps.get("items") or [])
    if items:
        top_opp = max(items, key=lambda x: x.get(
            "receita_potencial_brl") or 0)

    score = health.get("score")
    emoji = HEALTH_EMOJI.get(health.get("status"), "⚪")
    today = datetime.now(timezone.utc).strftime("%d/%m")

    lines = [
        f"*☕ Café com a IA do CEO* · {today}",
        "",
        f"{emoji} Saúde corporativa: *{score}/100* "
        f"({health.get('status')})",
    ]
    if top_risk:
        lines.append(
            f"⚠ Top risco: *{top_risk['area']}* — {top_risk['descricao']}")
    else:
        lines.append("✓ Nenhum risco crítico hoje.")

    if top_opp and (top_opp.get("receita_potencial_brl") or 0) > 0:
        lines.append(
            f"💡 Top oportunidade: *{top_opp['titulo']}* — "
            f"{_format_brl(top_opp['receita_potencial_brl'])} potenciais")
    elif top_opp:
        lines.append(f"💡 Top oportunidade: {top_opp['titulo']}")

    # ───── EQUIPE IA ─────
    equipe_payload = None
    try:
        from services import agent_registry as reg
        snap = await reg.snapshot_all(cid)
        equipe_payload = {
            "team_size": snap["team_size"],
            "avg_humanization_score": snap["avg_humanization_score"],
            "top_productivity": snap["ranking"]["top_productivity"],
            "low_productivity": snap["ranking"]["low_productivity"],
            "offline": snap["offline"],
            "nao_conformes": snap["nao_conformes"],
        }
        lines.append("")
        lines.append("*👥 EQUIPE IA*")
        lines.append(
            f"• Humanização média: *{snap['avg_humanization_score']}/100*"
        )
        top = snap["ranking"]["top_productivity"][:1]
        low = snap["ranking"]["low_productivity"][:1]
        if top:
            lines.append(
                f"• Produziu +: {top[0]['label']} "
                f"({top[0]['outbound_24h']} msg/24h)")
        if low and (low[0]["outbound_24h"] or 0) == 0:
            lines.append(
                f"• Produziu −: {low[0]['label']} (0 msg/24h)")
        if snap["offline"]:
            lines.append(
                f"• ⛔ Offline: {', '.join(snap['offline'])}")
        if snap["nao_conformes"]:
            lines.append(
                f"• ⚠ Fora de conformidade: "
                f"{', '.join(snap['nao_conformes'])}")
    except Exception as e:
        logger.info("[briefing] equipe ia skip: %s", e)

    lines.append("")
    lines.append("_Veja detalhes em Presidente IA._")

    return {
        "text": "\n".join(lines),
        "health_score": score,
        "health_status": health.get("status"),
        "top_risk": top_risk,
        "top_opportunity": top_opp,
        "equipe_ia": equipe_payload,
    }


async def send_briefing(cid: str,
                            phone: Optional[str] = None) -> Dict[str, Any]:
    """Envia briefing pro phone configurado (ou parâmetro).
    Retorna dict com {ok, text, sent_to}.
    """
    cfg = await db.conselho_ia_settings.find_one(
        {"company_id": cid}, {"_id": 0}) or {}
    target = phone or cfg.get("presidente_briefing_phone") \
        or cfg.get("notify_phone")
    if not target:
        return {"ok": False, "error": "phone não configurado"}

    payload = await build_briefing_text(cid)
    text = payload["text"]

    try:
        from services.wa.sidecar import _sidecar_post_silent
        res = await _sidecar_post_silent(
            "/send", {"phone": target, "text": text})
    except Exception as e:
        logger.exception("[presidente-briefing] send falhou: %s", e)
        res = {"ok": False, "error": str(e)}

    # Loga evento + memória
    await svc.record_event(
        cid, "presidente_briefing_sent",
        source="presidente_ia",
        severity="info",
        data={"phone": target, "ok": bool(res.get("ok")),
                "health_score": payload["health_score"]})

    return {"ok": bool(res.get("ok")),
             "text": text, "sent_to": target,
             "result": res, **payload}
