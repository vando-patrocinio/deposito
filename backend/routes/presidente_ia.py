"""
presidente_ia.py — Rotas do Presidente IA V2.0 (iter218)

Endpoints:
  GET  /api/presidente-ia/dashboard                Snapshot completo
  POST /api/presidente-ia/scan                     Força varredura proativa
  GET  /api/presidente-ia/agents                   Catálogo dos 14 agentes
  GET  /api/presidente-ia/events                   Stream recente
  GET  /api/presidente-ia/predictions              Top predições
  GET  /api/presidente-ia/insights                 Insights abertos
  GET  /api/presidente-ia/decisions                Histórico
  GET  /api/presidente-ia/actions                  Histórico de ações
  GET  /api/presidente-ia/conselho                 Todos pareceres
  POST /api/presidente-ia/conselho/{role}          Gera/atualiza parecer
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from core import DEMO_COMPANY_ID, get_current_user
from database import db
from rbac import (
    audit_log as _audit, mock_guard, rate_limit, require_ai_access,
)
from services import presidente_ia as svc
from services import presidente_ia_conselho as conselho

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/presidente-ia", tags=["presidente-ia"])


def _cid(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


# ─────────────────── Dashboard ───────────────────
@router.get("/dashboard")
async def dashboard(user: dict = Depends(require_ai_access()),
                       _: bool = Depends(rate_limit(60, 2000, "presidente"))):
    cid = _cid(user)
    health = await svc.compute_corporate_health(cid)
    risks = await svc.compute_risks(cid, health)
    opps = await svc.compute_opportunities(cid)
    clients_at_risk = await svc.compute_clients_at_risk(cid, limit=15)
    network = await svc.get_network_status(cid)
    attendance = await svc.get_attendance_status(cid)
    commercial = await svc.get_commercial_status(cid)
    universo = await svc.get_universo_ligo(cid)

    return {
        "company_id": cid,
        "agents": svc.AGENT_ORBIT,
        "health": health,
        "risks": risks,
        "opportunities": opps,
        "clients_at_risk": clients_at_risk,
        "network": network,
        "attendance": attendance,
        "commercial": commercial,
        "universo_ligo": universo,
        "generated_at": svc._now_iso(),
    }


# ─────────────────── Scan proativo ───────────────────
@router.post("/scan")
async def scan(user: dict = Depends(require_ai_access()),
                  _: bool = Depends(rate_limit(5, 100, "presidente_scan"))):
    cid = _cid(user)
    await _audit(user, "ia", "presidente_scan", target=cid)
    return await svc.proactive_scan(cid)


# ─────────────────── Catálogo ───────────────────
@router.get("/agents")
async def agents(user: dict = Depends(get_current_user)):
    return {"items": svc.AGENT_ORBIT, "total": len(svc.AGENT_ORBIT)}


# ─────────────────── Streams ───────────────────
@router.get("/events")
async def events(limit: int = Query(50, ge=1, le=500),
                    severity: str = Query("", description="info|warn|alert|critical"),
                    user: dict = Depends(get_current_user)):
    cid = _cid(user)
    q: Dict[str, Any] = {"company_id": cid}
    if severity:
        q["severity"] = severity
    items = await db.motor_ia_events.find(q, {"_id": 0}) \
        .sort("created_at", -1).to_list(limit)
    return {"items": items, "total": len(items)}


@router.get("/predictions")
async def predictions(limit: int = Query(50, ge=1, le=500),
                          kind: str = Query(""),
                          user: dict = Depends(get_current_user)):
    cid = _cid(user)
    q: Dict[str, Any] = {"company_id": cid}
    if kind:
        q["kind"] = kind
    items = await db.motor_ia_predictions.find(q, {"_id": 0}) \
        .sort([("score", -1), ("created_at", -1)]).to_list(limit)
    return {"items": items, "total": len(items)}


@router.get("/insights")
async def insights(limit: int = Query(50, ge=1, le=500),
                       user: dict = Depends(get_current_user)):
    cid = _cid(user)
    items = await db.motor_ia_insights.find(
        {"company_id": cid, "status": "open"}, {"_id": 0}
    ).sort("created_at", -1).to_list(limit)
    return {"items": items, "total": len(items)}


@router.get("/decisions")
async def decisions(limit: int = Query(50, ge=1, le=500),
                        user: dict = Depends(get_current_user)):
    cid = _cid(user)
    items = await db.motor_ia_decisions.find(
        {"company_id": cid}, {"_id": 0}
    ).sort("created_at", -1).to_list(limit)
    return {"items": items, "total": len(items)}


@router.get("/actions")
async def actions(limit: int = Query(50, ge=1, le=500),
                      user: dict = Depends(get_current_user)):
    cid = _cid(user)
    items = await db.motor_ia_actions.find(
        {"company_id": cid}, {"_id": 0}
    ).sort("created_at", -1).to_list(limit)
    return {"items": items, "total": len(items)}


# ─────────────────── Conselho Executivo ───────────────────
async def _build_snapshot(cid: str) -> Dict[str, Any]:
    """Snapshot leve usado para alimentar os pareceres do Conselho."""
    health = await svc.compute_corporate_health(cid)
    return {
        "health": health,
        "risks": await svc.compute_risks(cid, health),
        "opportunities": await svc.compute_opportunities(cid),
        "network": await svc.get_network_status(cid),
        "attendance": await svc.get_attendance_status(cid),
        "commercial": await svc.get_commercial_status(cid),
        "universo_ligo": await svc.get_universo_ligo(cid),
    }


@router.get("/conselho")
async def conselho_all(force: bool = Query(False),
                          user: dict = Depends(require_ai_access()),
                          _: bool = Depends(rate_limit(10, 200, "conselho_llm"))):
    """Retorna todos os 6 pareceres (CEO/COO/CTO/CFO/CPO + Estrategista).
    Usa cache de 60min por papel. force=true regera todos. Roda em
    paralelo (asyncio.gather) para reduzir latência."""
    import asyncio
    cid = _cid(user)
    await _audit(user, "ia", "conselho_executivo_view", target=cid,
                    data={"force": force})
    snapshot = await _build_snapshot(cid)

    async def _safe(role: str):
        try:
            return await conselho.get_parecer(
                cid, role, snapshot, force=force)
        except Exception as e:
            return {"role": role,
                    "label": conselho.ROLES[role]["label"],
                    "color": conselho.ROLES[role]["color"],
                    "parecer": f"⚠ Erro ao gerar: {e}",
                    "from_cache": False, "error": str(e)}

    out = await asyncio.gather(
        *[_safe(role) for role in conselho.ROLES.keys()])
    return {"items": out,
             "snapshot_health": snapshot["health"]["score"]}


@router.post("/conselho/{role}")
async def conselho_role(role: str,
                            force: bool = Query(True),
                            user: dict = Depends(get_current_user)):
    """Gera/atualiza parecer de um papel específico."""
    cid = _cid(user)
    if role not in conselho.ROLES:
        raise HTTPException(404, f"role desconhecida: {role}")
    snapshot = await _build_snapshot(cid)
    return await conselho.get_parecer(cid, role, snapshot, force=force)


# ─────────────────── Briefing matinal — iter219 ───────────────────
from pydantic import BaseModel  # noqa: E402


class BriefingSettingsIn(BaseModel):
    enabled: bool = True
    phone: str = ""


@router.get("/briefing/settings")
async def briefing_settings_get(user: dict = Depends(get_current_user)):
    cid = _cid(user)
    cfg = await db.conselho_ia_settings.find_one(
        {"company_id": cid}, {"_id": 0}) or {}
    return {
        "enabled": bool(cfg.get("presidente_briefing_enabled")),
        "phone": cfg.get("presidente_briefing_phone")
                  or cfg.get("notify_phone") or "",
        "cron_hour_utc": int(cfg.get("cron_hour_utc") or 11),
    }


@router.put("/briefing/settings")
async def briefing_settings_put(payload: BriefingSettingsIn,
                                    user: dict = Depends(get_current_user)):
    cid = _cid(user)
    phone = "".join(c for c in (payload.phone or "")
                       if c.isdigit())
    await db.conselho_ia_settings.update_one(
        {"company_id": cid},
        {"$set": {
            "company_id": cid,
            "presidente_briefing_enabled": bool(payload.enabled),
            "presidente_briefing_phone": phone,
        }}, upsert=True)
    return {"ok": True, "enabled": bool(payload.enabled),
             "phone": phone}


@router.post("/briefing/test")
async def briefing_test(user: dict = Depends(get_current_user)):
    """Dispara o briefing imediatamente (para teste)."""
    cid = _cid(user)
    from services.presidente_ia_briefing import send_briefing
    return await send_briefing(cid)


@router.post("/leo/proactive")
async def leo_proactive_run(user: dict = Depends(get_current_user)):
    """iter219d — Dispara Leo Proativo manualmente (detectores +
    WhatsApp). Retorna estatísticas do envio."""
    cid = _cid(user)
    from services.leo_proactive import try_proactive_notifications
    return await try_proactive_notifications(cid)


@router.get("/briefing/preview")
async def briefing_preview(user: dict = Depends(get_current_user)):
    """Retorna o texto que seria enviado, sem disparar WhatsApp."""
    cid = _cid(user)
    from services.presidente_ia_briefing import build_briefing_text
    return await build_briefing_text(cid)



# ─────────────────── Sprint 3 — Segurança & Compliance ───────────────────
@router.get("/security/alerts")
async def security_alerts(user: dict = Depends(require_ai_access())):
    """Roda detectores de anomalia sobre o audit_log e retorna alertas
    para o painel do Presidente IA."""
    from services.audit_alerts import scan_security_alerts
    alerts = await scan_security_alerts()
    return {"count": len(alerts), "alerts": alerts}


@router.get("/security/insight")
async def security_insight(user: dict = Depends(require_ai_access())):
    """Resumo executivo de segurança das últimas 24h."""
    from services.audit_alerts import daily_security_insight
    return await daily_security_insight()
