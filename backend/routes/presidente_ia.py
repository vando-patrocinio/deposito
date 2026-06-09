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
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

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


# ─────────────────── EXECUTIVO V10 — Cérebro Presidencial ───────────────────
@router.get("/executive")
async def executive_report(user: dict = Depends(require_ai_access()),
                              _: bool = Depends(rate_limit(
                                  30, 600, "presidente_executive"))):
    """Relatório executivo monetizado. Substitui /dashboard como
    fonte primária do Presidente IA V10. Nada é exibido em contagem;
    tudo é traduzido em R$, ação e impacto."""
    from services.presidente_executive import build_executive_report
    cid = _cid(user)
    await _audit(user, "ia", "presidente_executive_view", target=cid)
    return await build_executive_report(cid)


# ─────────────────── EXECUTOR P1 — BRAÇOS DO PRESIDENTE ───────────────────
# Ciclo: PROPOR → CONSELHO VOTAR → APROVAR → EXECUTAR → ROI → APRENDER

@router.post("/actions/propose")
async def actions_propose(
    body: Dict[str, Any] = Body(...),
    user: dict = Depends(require_ai_access()),
    _: bool = Depends(rate_limit(20, 600, "exec_propose")),
):
    """Presidente IA propõe uma ação executável. Consulta memória
    antes de criar — proibido recomendar sem consultar histórico."""
    from services import executor_ia as ex
    cid = _cid(user)
    categoria = body.get("categoria")
    if categoria not in ex.CATEGORIAS_EXECUTAVEIS:
        raise HTTPException(400, f"categoria inválida. Use: "
                                  f"{list(ex.CATEGORIAS_EXECUTAVEIS)}")
    # Memória obrigatória antes da recomendação
    memoria = await ex.consult_memory(cid, categoria)
    action = await ex.propose_action(
        company_id=cid,
        created_by=user.get("email") or "system",
        categoria=categoria,
        descricao=body.get("descricao") or
                   ex.CATEGORIAS_EXECUTAVEIS[categoria],
        impacto_estimado_brl=float(body.get("impacto_estimado_brl") or 0),
        prioridade=body.get("prioridade") or "MÉDIA",
        source="presidente_ia",
        payload=body.get("payload") or {},
        decision_id=body.get("decision_id"),
    )
    await _audit(user, "ia", "action_proposed",
                    target=action["id"], data={"cat": categoria})
    return {"action": action, "memoria_consultada": memoria}


@router.post("/actions/{action_id}/council-vote")
async def actions_council_vote(
    action_id: str,
    user: dict = Depends(require_ai_access()),
    _: bool = Depends(rate_limit(20, 600, "exec_vote")),
):
    """Conselho IA (6 cadeiras) vota formalmente."""
    from services import executor_ia as ex
    result = await ex.collect_council_votes(action_id)
    await _audit(user, "ia", "council_voted", target=action_id,
                    data={"consensus": result["consensus"]["ratio"]})
    return result


@router.post("/actions/{action_id}/approve")
async def actions_approve(
    action_id: str,
    body: Dict[str, Any] = Body(default_factory=dict),
    user: dict = Depends(require_ai_access()),
    _: bool = Depends(rate_limit(20, 600, "exec_approve")),
):
    """Aprovação humana. Move pending→approved e enfileira."""
    from services import executor_ia as ex
    try:
        act = await ex.approve_action(
            action_id, user.get("email") or "system",
            body.get("justification", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    await _audit(user, "ia", "action_approved", target=action_id)
    return act


@router.post("/actions/{action_id}/execute")
async def actions_execute(
    action_id: str,
    body: Dict[str, Any] = Body(default_factory=dict),
    user: dict = Depends(require_ai_access()),
    _: bool = Depends(rate_limit(10, 600, "exec_run")),
):
    """Executa a ação. dry_run=True por padrão. Snapshot AFTER + ROI
    + correção de aprendizado registrados automaticamente."""
    from services import executor_ia as ex
    dry_run = bool(body.get("dry_run", True))
    try:
        act = await ex.execute_action(
            action_id, user.get("email") or "system", dry_run=dry_run)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await _audit(user, "ia", "action_executed", target=action_id,
                    data={"dry_run": dry_run,
                            "roi_brl": act.get("roi_brl")})
    return act


@router.post("/actions/{action_id}/cancel")
async def actions_cancel(
    action_id: str,
    body: Dict[str, Any] = Body(default_factory=dict),
    user: dict = Depends(require_ai_access()),
):
    from services import executor_ia as ex
    try:
        act = await ex.cancel_action(
            action_id, user.get("email") or "system",
            body.get("reason", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    await _audit(user, "ia", "action_cancelled", target=action_id)
    return act


@router.get("/actions")
async def actions_list(
    status: Optional[str] = None,
    limit: int = 50,
    user: dict = Depends(require_ai_access()),
):
    from services import executor_ia as ex
    cid = _cid(user)
    items = await ex.list_actions(cid, status=status, limit=limit)
    queue = await ex.list_queue(cid)
    return {"actions": items, "queue": queue}


@router.get("/actions/{action_id}/ledger")
async def actions_ledger(
    action_id: str,
    user: dict = Depends(require_ai_access()),
):
    """Ledger completo: quem decidiu, aprovou, executou, ROI, votos,
    snapshots, correção de aprendizado."""
    from services import executor_ia as ex
    try:
        return await ex.get_action_ledger(action_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/memory/{categoria}")
async def memory_by_category(
    categoria: str,
    user: dict = Depends(require_ai_access()),
):
    """Lê histórico de ROI por categoria (Etapa 7)."""
    from services import executor_ia as ex
    cid = _cid(user)
    return await ex.consult_memory(cid, categoria)


@router.get("/state-of-presidency")
async def state_of_presidency_route(
    period_days: int = 30,
    user: dict = Depends(require_ai_access()),
):
    """Responde as 9 perguntas obrigatórias do P1.

    1.recomendei · 2.aprovado · 3.executado · 4.gerou_resultado
    5.dinheiro_entrou · 6.dinheiro_salvo · 7.deu_errado
    8.aprendi · 9.farei_diferente
    """
    from services import executor_ia as ex
    cid = _cid(user)
    return await ex.state_of_presidency(cid, period_days=period_days)


@router.get("/learning/drift")
async def learning_drift(
    user: dict = Depends(require_ai_access()),
):
    """Tabela de drift por categoria (motor_ia_drift)."""
    cid = _cid(user)
    cursor = db.motor_ia_drift.find(
        {"company_id": cid}, {"_id": 0}).sort(
            [("updated_at", -1)])
    return {"drifts": await cursor.to_list(50)}


# ─────────────── FASE E — AUTONOMIA REAL (auto-aprovação) ──────────
#  3 endpoints. Whitelist explícita + kill-switch via env.

@router.get("/auto-approval/policy")
async def auto_approval_policy(
    user: dict = Depends(require_ai_access()),
):
    """Política atual de auto-aprovação. Inclui whitelist, caps e
    status do kill-switch global AUTO_APPROVAL_ENABLED."""
    from services import executor_ia as ex
    return ex.get_auto_approval_policy()


@router.post("/auto-approval/scan")
async def auto_approval_scan(
    body: Dict[str, Any] = Body(default_factory=dict),
    user: dict = Depends(require_ai_access()),
    _: bool = Depends(rate_limit(10, 600, "auto_approval_scan")),
):
    """Varre ações pending do tenant e auto-aprova as elegíveis.
    Respeita whitelist + cap de impacto + consenso forte do conselho."""
    from services import executor_ia as ex
    cid = _cid(user)
    limit = int(body.get("limit") or 50)
    result = await ex.scan_and_auto_approve(cid, limit=limit)
    await _audit(user, "ia", "auto_approval_scan",
                    target=cid,
                    data={"approved": len(result.get("approved", [])),
                            "skipped": len(result.get("skipped", []))})
    return result


@router.get("/auto-approval/audit")
async def auto_approval_audit(
    limit: int = 100,
    user: dict = Depends(require_ai_access()),
):
    """Lista todas as ações auto-aprovadas para auditoria reversível."""
    from services import executor_ia as ex
    cid = _cid(user)
    items = await ex.list_auto_approved_actions(cid, limit=limit)
    return {"company_id": cid, "count": len(items), "items": items}


# ─────────────── FASE B — Hardening WhatsApp ──────────
#  Status do circuit breaker + métricas agregadas do dispatcher.

@router.get("/wa/dispatcher-status")
async def wa_dispatcher_status(
    hours: int = 24,
    user: dict = Depends(require_ai_access()),
):
    """Diagnóstico do dispatcher WhatsApp: circuit breaker por tenant +
    sucesso/latência das últimas N horas."""
    from services import wa_dispatcher as wa
    cid = _cid(user)
    return await wa.metrics_summary(company_id=cid, hours=hours)


# ─────────────── GOVERNADOR V11 — Presidente como Governador ──────────
#  10 endpoints, todos consolidando dados que já existem.

@router.post("/governador/goals")
async def gov_create_goal(
    body: Dict[str, Any] = Body(...),
    user: dict = Depends(require_ai_access()),
):
    from services import governador_ia as gov
    cid = _cid(user)
    try:
        return await gov.create_goal(
            company_id=cid, area=body["area"], metric=body["metric"],
            target_value=float(body["target_value"]),
            deadline_iso=body["deadline"],
            owner=body["owner"],
            created_by=user.get("email") or "system",
            ia_responsavel=body.get("ia_responsavel"),
            description=body.get("description") or "")
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))


@router.get("/governador/goals")
async def gov_list_goals(
    status: Optional[str] = None,
    refresh: bool = False,
    user: dict = Depends(require_ai_access()),
):
    from services import governador_ia as gov
    cid = _cid(user)
    if refresh:
        await gov.refresh_all_goals(cid)
    return {"goals": await gov.list_goals(cid, status=status)}


@router.post("/governador/goals/{goal_id}/refresh")
async def gov_refresh_goal(
    goal_id: str,
    user: dict = Depends(require_ai_access()),
):
    from services import governador_ia as gov
    try:
        return await gov.update_goal_progress(goal_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/governador/ia-scorecard")
async def gov_scorecard(
    period_days: int = 30,
    user: dict = Depends(require_ai_access()),
):
    from services import governador_ia as gov
    cid = _cid(user)
    return {"scorecard": await gov.scorecard_ias(cid, period_days)}


@router.get("/governador/ia-roi")
async def gov_roi(
    period_days: int = 30,
    user: dict = Depends(require_ai_access()),
):
    from services import governador_ia as gov
    cid = _cid(user)
    return await gov.roi_por_ia(cid, period_days)


@router.get("/governador/cobranca")
async def gov_cobranca(user: dict = Depends(require_ai_access())):
    from services import governador_ia as gov
    cid = _cid(user)
    return {"cobranca": await gov.cobranca_resultado(cid)}


@router.get("/governador/prioridades")
async def gov_prioridades(user: dict = Depends(require_ai_access())):
    from services import governador_ia as gov
    cid = _cid(user)
    return {"prioridades": await gov.prioridades_executivas(cid)}


@router.get("/governador/saude")
async def gov_saude(user: dict = Depends(require_ai_access())):
    from services import governador_ia as gov
    cid = _cid(user)
    return await gov.saude_corporativa(cid)


@router.get("/governador/sistema-nervoso")
async def gov_nervoso(
    hours: int = 24,
    user: dict = Depends(require_ai_access()),
):
    from services import governador_ia as gov
    cid = _cid(user)
    return await gov.sistema_nervoso(cid, hours)


@router.get("/governador/mapa-executivo")
async def gov_mapa(user: dict = Depends(require_ai_access())):
    from services import governador_ia as gov
    cid = _cid(user)
    return await gov.mapa_executivo(cid)


@router.get("/governador/ranking")
async def gov_ranking(
    period_days: int = 30,
    user: dict = Depends(require_ai_access()),
):
    from services import governador_ia as gov
    cid = _cid(user)
    return {"ranking": await gov.ranking_eficiencia(cid, period_days)}


@router.get("/governador/relatorio-diario")
async def gov_relatorio(
    force: bool = False,
    user: dict = Depends(require_ai_access()),
    _: bool = Depends(rate_limit(20, 600, "gov_daily")),
):
    from services import governador_ia as gov
    cid = _cid(user)
    return await gov.relatorio_presidencial_diario(cid, force=force)


# ─────────────── CÉREBRO V12+V13+V14 ───────────────
@router.get("/brain/causality/{action_id}")
async def brain_causality(action_id: str,
                              user: dict = Depends(require_ai_access())):
    from services import presidente_brain as br
    try:
        return await br.causality_for_action(action_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/brain/causality-summary")
async def brain_causality_summary(
        user: dict = Depends(require_ai_access())):
    from services import presidente_brain as br
    cid = _cid(user)
    return await br.causality_summary_30d(cid)


@router.get("/brain/twin/subscriber/{subscriber_id}")
async def brain_twin_subscriber(
        subscriber_id: str,
        user: dict = Depends(require_ai_access())):
    from services import presidente_brain as br
    try:
        return await br.digital_twin_subscriber(subscriber_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/brain/twin/global")
async def brain_twin_global(
        user: dict = Depends(require_ai_access())):
    from services import presidente_brain as br
    cid = _cid(user)
    return await br.digital_twin_global(cid)


@router.get("/brain/autopilot/top10")
async def brain_autopilot(
        user: dict = Depends(require_ai_access()),
        _: bool = Depends(rate_limit(10, 600, "autopilot"))):
    from services import presidente_brain as br
    cid = _cid(user)
    return await br.autopilot_top10(cid)


# ─────────────── V15+V16+V17 — AUTOCONSCIÊNCIA ───────────────
@router.get("/self/audit")
async def self_audit(user: dict = Depends(require_ai_access())):
    from services import presidente_self_audit as sa
    return await sa.autoconsciencia(_cid(user))


@router.get("/self/evolution")
async def self_evolution(user: dict = Depends(require_ai_access())):
    from services import presidente_self_audit as sa
    return await sa.conselho_evolucao(_cid(user))


@router.get("/self/readiness")
async def self_readiness(user: dict = Depends(require_ai_access())):
    from services import presidente_self_audit as sa
    return await sa.prontidao_comercial(_cid(user))


# ─────────────── V20 — DIRETOR DE EVOLUÇÃO ───────────────
@router.get("/evolution/backlog")
async def evo_backlog(user: dict = Depends(require_ai_access())):
    from services import presidente_evolution as ev
    return await ev.backlog_executivo(_cid(user))


@router.get("/evolution/sprints")
async def evo_sprints(sprint_horas: int = 16,
                          user: dict = Depends(require_ai_access())):
    from services import presidente_evolution as ev
    return await ev.gerar_sprints(_cid(user), sprint_horas)


@router.get("/evolution/architect/{gargalo_id}")
async def evo_arch(gargalo_id: str,
                       user: dict = Depends(require_ai_access())):
    from services import presidente_evolution as ev
    return await ev.arquiteto_item(gargalo_id)


@router.get("/evolution/roadmap")
async def evo_roadmap(user: dict = Depends(require_ai_access())):
    from services import presidente_evolution as ev
    return await ev.roadmap_12m(_cid(user))


@router.post("/evolution/sprint/{sprint_id}/audit")
async def evo_audit(sprint_id: str,
                        user: dict = Depends(require_ai_access())):
    from services import presidente_evolution as ev
    return await ev.auditor_execucao_sprint(sprint_id)
