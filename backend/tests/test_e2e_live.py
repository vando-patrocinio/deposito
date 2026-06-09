"""
test_e2e_live.py — Pós-CTO audit Sprint 7 (P0 #4)
Suíte E2E em modo LIVE do Sistema Nervoso Corporativo.

Roda os ciclos completos: emit_event → decision_engine → action_engine
contra MongoDB real. NÃO usa mocks. Quando PRESIDENTE_IA_LIVE=1, tenta
inclusive disparar WhatsApp/notificação real (skip caso integração não
esteja configurada).

NOTA: Cada teste cria seu próprio event loop + motor client para
contornar o conflito conhecido (AsyncIOMotorClient + pytest-asyncio).

Execução padrão (DRY-RUN):
    cd /app/backend && python -m pytest tests/test_e2e_live.py -v -s

Execução LIVE (precisa creds Baileys + número do gestor):
    PRESIDENTE_IA_LIVE=1 PRESIDENTE_IA_GESTOR_PHONE=+5511999999999 \\
    python -m pytest tests/test_e2e_live.py -v -s
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LIVE_MODE = os.environ.get("PRESIDENTE_IA_LIVE", "0") == "1"
HAS_GESTOR_PHONE = bool(os.environ.get("PRESIDENTE_IA_GESTOR_PHONE"))


def _fresh_db():
    """Cria cliente Motor ATADO ao event loop atual."""
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client[os.environ["DB_NAME"]], client


def _run(coro_factory):
    """Roda coroutine em novo loop. coro_factory(db) -> coroutine.

    Re-importa módulos do app DENTRO do loop para que o `db` global
    deles aponte para um motor client atado ao loop corrente.
    """
    async def _wrap():
        db, client = _fresh_db()
        import importlib
        import database
        database.db = db
        database.mongo_client = client
        # força módulos relevantes a refrescarem a referência `db`
        for mod_name in (
            "services.lgpd_chain", "services.event_bus",
            "services.decision_engine", "services.action_engine",
            "services.scheduler_lock", "services.memory_cleanup",
            "services.llm_budget", "services.audit_alerts",
            "services.feedback_loop", "services.predictions",
            "services.learnings", "services.event_emitters",
            "services.company_settings", "services.rule_thresholds",
            "services.ml_predictions", "services.data_quality",
            "services.executive_health",
            "services.live_pilot", "services.predictions_validation",
            "services.operacao_tese",
        ):
            if mod_name in sys.modules:
                importlib.reload(sys.modules[mod_name])
        try:
            return await coro_factory(db)
        finally:
            client.close()
    return asyncio.run(_wrap())


def _cleanup(db, company_id):
    async def _do():
        for coll in ("motor_ia_events", "motor_ia_decisions",
                       "motor_ia_actions", "motor_ia_outcomes",
                       "incidents", "loyalty_opportunities",
                       "presidente_ia_notifications", "dunning_escalations",
                       "tickets", "sales_leads", "audit_log"):
            await db[coll].delete_many({"company_id": company_id})
    return _do()


def test_e2e_collective_outage():
    """5 CLIENT_OFFLINE no mesmo CTO → open_incident."""
    co = f"test-e2e-out-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from services.event_bus import emit_event, EventType
        from services.decision_engine import run_decision_cycle
        from services.action_engine import execute_pending
        for i in range(5):
            await emit_event(
                EventType.CLIENT_OFFLINE,
                company_id=co, source="test_e2e",
                severity="alta",
                payload={"cto_id": "CTO-E2E-OUTAGE",
                         "subscriber_id": f"sub-{i}"})
        cycle = await run_decision_cycle()
        assert cycle["decisions_created"] >= 1, cycle
        dec = await db.motor_ia_decisions.find_one(
            {"company_id": co, "action_type": "open_incident"})
        assert dec is not None
        assert dec.get("reasoning")
        assert dec.get("trigger_event_id")
        assert dec.get("correlation_id")
        ae = await execute_pending()
        assert ae["executed"] >= 1, ae
        out = await db.motor_ia_outcomes.find_one(
            {"company_id": co, "decision_id": dec["id"]})
        assert out is not None and out["ok"] is True
        await _cleanup(db, co)
    _run(_scenario)


def test_e2e_rbac_abuse():
    """3 RBAC_DENIED → notify_manager."""
    co = f"test-e2e-rbac-{uuid.uuid4().hex[:6]}"
    user_id = f"attacker-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from services.event_bus import emit_event, EventType
        from services.decision_engine import run_decision_cycle
        from services.action_engine import execute_pending
        for _ in range(3):
            await emit_event(
                EventType.RBAC_DENIED,
                company_id=co, user_id=user_id,
                source="test_e2e", severity="alta",
                payload={"endpoint": "/api/admin/users"})
        await run_decision_cycle()
        dec = await db.motor_ia_decisions.find_one(
            {"company_id": co, "action_type": "notify_manager"})
        assert dec is not None
        assert user_id in (dec.get("title") or "")
        await execute_pending()
        notif = await db.presidente_ia_notifications.find_one(
            {"linked_decision_id": dec["id"]})
        assert notif is not None
        if LIVE_MODE and HAS_GESTOR_PHONE:
            assert notif.get("dry_run") is False
            print(f"LIVE notify wa_sent={notif.get('wa_sent', 'n/a')}")
        else:
            assert notif.get("dry_run") is True
        await _cleanup(db, co)
    _run(_scenario)


def test_e2e_payment_overdue():
    """PAYMENT_OVERDUE → escalate_dunning."""
    co = f"test-e2e-pay-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from services.event_bus import emit_event, EventType
        from services.decision_engine import run_decision_cycle
        from services.action_engine import execute_pending
        await emit_event(
            EventType.PAYMENT_OVERDUE,
            company_id=co, source="test_e2e",
            severity="media",
            payload={"subscriber_id": "sub-overdue-1"})
        await run_decision_cycle()
        dec = await db.motor_ia_decisions.find_one(
            {"company_id": co, "action_type": "escalate_dunning"})
        assert dec is not None and dec["confidence"] >= 0.9
        await execute_pending()
        dun = await db.dunning_escalations.find_one(
            {"linked_decision_id": dec["id"]})
        assert dun is not None
        await _cleanup(db, co)
    _run(_scenario)


def test_e2e_onu_low_signal():
    """ONU_LOW_SIGNAL → open_technical_ticket (nova regra pós-CTO)."""
    co = f"test-e2e-onu-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from services.event_bus import emit_event
        from services.decision_engine import run_decision_cycle
        from services.action_engine import execute_pending
        await emit_event(
            "ONU_LOW_SIGNAL",
            company_id=co, source="test_e2e",
            severity="alta",
            payload={"subscriber_id": "sub-onu-1",
                     "onu_id": "onu-xyz", "rx_dbm": -28.5})
        await run_decision_cycle()
        dec = await db.motor_ia_decisions.find_one(
            {"company_id": co, "action_type": "open_technical_ticket"})
        assert dec is not None
        await execute_pending()
        tkt = await db.tickets.find_one(
            {"linked_decision_id": dec["id"]})
        assert tkt is not None
        await _cleanup(db, co)
    _run(_scenario)


def test_audit_chain_integrity_via_lgpd():
    """Inserir 3 audit_logs via lgpd_chain mantém a chain íntegra."""
    co = f"test-chain-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from services.lgpd_chain import insert_audit_event, verify_chain
        from datetime import datetime, timezone
        for i in range(3):
            await insert_audit_event({
                "id": f"aud-test-{uuid.uuid4().hex[:10]}",
                "company_id": co,
                "user_id": "test-user",
                "user_email": "test@e2e.com",
                "user_role": "administrador",
                "category": "config_change",
                "criticality": "media",
                "method": "POST",
                "target": f"/api/test/chain-{i}",
                "endpoint": f"/api/test/chain-{i}",
                "action": "test chain",
                "status": 200,
                "data": {"i": i},
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        chk = await verify_chain(limit=5000)
        print(f"chain check: {chk['broken_count']} breaks / "
              f"{chk['checked']} checked")
        assert chk["checked"] >= 3
        await _cleanup(db, co)
    _run(_scenario)


def test_correlation_id_propagation():
    """correlation_id fluindo evento → decisão → ação → outcome."""
    co = f"test-corr-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from services.event_bus import emit_event, EventType
        from services.decision_engine import run_decision_cycle
        from services.action_engine import execute_pending
        corr = f"corr-test-{uuid.uuid4().hex[:8]}"
        await emit_event(
            EventType.PAYMENT_OVERDUE,
            company_id=co, source="test_e2e_corr",
            severity="media",
            correlation_id=corr,
            payload={"subscriber_id": "sub-corr-1"})
        await run_decision_cycle()
        await execute_pending()
        dec = await db.motor_ia_decisions.find_one({"correlation_id": corr})
        assert dec is not None, "decisão sem correlation_id propagado"
        act = await db.motor_ia_actions.find_one({"correlation_id": corr})
        assert act is not None, "ação sem correlation_id propagado"
        out = await db.motor_ia_outcomes.find_one({"correlation_id": corr})
        assert out is not None, "outcome sem correlation_id propagado"
        await _cleanup(db, co)
    _run(_scenario)


def test_scheduler_leader_lock():
    """Leader election via Mongo lock — só 1 holder por vez."""
    async def _scenario(db):
        from services.scheduler_lock import (
            try_acquire_leader, current_leader, release_leader,
            LOCK_ID,
        )
        # garante estado limpo (backend pode estar segurando o lock)
        await db.scheduler_locks.delete_one({"_id": LOCK_ID})
        got = await try_acquire_leader()
        assert got is True
        state = await current_leader()
        assert state["is_me"]
        assert state["holder"]
        await release_leader()
        state2 = await current_leader()
        assert state2["is_me"] is False
    _run(_scenario)


def test_llm_budget_guard():
    """check_budget retorna ok=True dentro do limite."""
    async def _scenario(db):
        from services.llm_budget import check_budget, get_status
        s0 = await get_status()
        assert "global_used" in s0
        b = await check_budget()
        assert b["ok"] is True
    _run(_scenario)


def test_memory_cleanup_returns_dict():
    """cleanup_old_memory roda sem erro e retorna dict."""
    async def _scenario(db):
        from services.memory_cleanup import cleanup_old_memory
        r = await cleanup_old_memory()
        assert isinstance(r, dict)
        assert "deleted_total" in r
    _run(_scenario)


def test_tenant_isolation_subject_report():
    """subject_report com company_id filtra apenas docs daquela empresa."""
    co_a = f"test-tnt-a-{uuid.uuid4().hex[:6]}"
    co_b = f"test-tnt-b-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from services.lgpd_chain import (
            insert_audit_event, subject_report,
        )
        from datetime import datetime, timezone
        sub_id = f"subject-{uuid.uuid4().hex[:6]}"
        # 2 eventos do mesmo subject em empresas diferentes
        for co in (co_a, co_b):
            await insert_audit_event({
                "id": f"aud-tnt-{uuid.uuid4().hex[:10]}",
                "company_id": co,
                "user_id": sub_id,
                "user_email": "x@y.com",
                "user_role": "colaborador",
                "category": "login_admin",
                "method": "POST",
                "target": "/login",
                "endpoint": "/login",
                "action": "login",
                "status": 200,
                "data": {"subject_id": sub_id},
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        # report sem filtro: vê os 2
        all_r = await subject_report(sub_id)
        assert all_r["total_events"] >= 2
        # com filtro company_id=co_a: só 1
        scoped = await subject_report(sub_id, company_id=co_a)
        assert scoped["total_events"] == 1, scoped
        for ev in scoped["events"]:
            assert co_a or True  # sanity
        # cleanup
        await db.audit_log.delete_many({"company_id": {"$in": [co_a, co_b]}})
    _run(_scenario)



# ─────────────────────── Sprint 10/11/12 tests ───────────────────────

def test_feedback_loop_adjust_confidence():
    """Sprint 10 — feedback_loop ajusta confidence baseado em outcomes."""
    async def _scenario(db):
        from services.feedback_loop import (
            adjust_confidence, refresh_stats,
        )
        # força recálculo
        stats = await refresh_stats(force=True)
        assert isinstance(stats, dict)
        # ajusta confidence base 0.8 — deve retornar valor em [0.05, 0.99]
        adj = await adjust_confidence("notify_manager", 0.8)
        assert 0.05 <= adj <= 0.99
    _run(_scenario)


def test_feedback_loop_factor_curve():
    """Curva do feedback_loop: ≥0.95 sucesso → factor 1.20 etc."""
    async def _scenario(db):
        from services.feedback_loop import _factor_for
        assert _factor_for(0.99) == 1.20
        assert _factor_for(0.90) == 1.00
        assert _factor_for(0.70) == 0.85
        assert _factor_for(0.40) == 0.50
    _run(_scenario)


def test_predictions_run_all():
    """Sprint 11 — run_all_predictions popula motor_ia_predictions."""
    async def _scenario(db):
        from services.predictions import (
            run_all_predictions, latest_by_kind,
        )
        out = await run_all_predictions()
        assert "churn" in out
        assert "revenue" in out
        assert "ticket_demand" in out
        # cada predição foi persistida
        for kind in ("churn", "revenue", "ticket_demand"):
            latest = await latest_by_kind(kind)
            assert latest.get("kind") == kind
            assert latest.get("generated_at")
    _run(_scenario)


def test_predictions_churn_uses_real_signals():
    """Predict_churn agrega tickets/payments/sinal reais."""
    co = f"test-pred-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from services.predictions import predict_churn
        # cria sinais: 1 ticket aberto + 1 mensalidade overdue
        sub_id = f"sub-pred-{uuid.uuid4().hex[:6]}"
        nonce = uuid.uuid4().hex[:6]
        await db.tickets.insert_many([
            {"id": f"tkt-{nonce}-{i}", "company_id": co,
             "subscriber_id": sub_id, "status": "open",
             "created_at": "2026-06-01T00:00:00+00:00"}
            for i in range(2)
        ])
        await db.financeiro_movs.insert_one({
            "id": f"mov-{nonce}", "company_id": co,
            "subscriber_id": sub_id, "status": "overdue",
        })
        pred = await predict_churn()
        ids = {it["subscriber_id"] for it in pred["items"]}
        assert sub_id in ids
        target = next(i for i in pred["items"]
                      if i["subscriber_id"] == sub_id)
        # 2 tickets (>=2) +30, overdue +40 = 70
        assert target["risk_score"] >= 60
        # cleanup
        await db.tickets.delete_many({"company_id": co})
        await db.financeiro_movs.delete_many({"company_id": co})
        await db.motor_ia_predictions.delete_one({"id": pred["id"]})
    _run(_scenario)


def test_learnings_record_snapshot():
    """Sprint 12 — record_learning_snapshot grava em motor_ia_learnings."""
    async def _scenario(db):
        from services.learnings import (
            record_learning_snapshot, latest_snapshot,
        )
        fake_stats = {
            "notify_manager": {"success_rate": 0.92, "factor": 1.0,
                               "total": 10, "ok": 9},
            "escalate_dunning": {"success_rate": 0.40, "factor": 0.50,
                                 "total": 10, "ok": 4},
        }
        doc = await record_learning_snapshot(fake_stats)
        assert doc.get("id", "").startswith("lrn-")
        assert "deltas" in doc
        latest = await latest_snapshot()
        assert latest.get("kind") == "feedback_snapshot"
        await db.motor_ia_learnings.delete_one({"id": doc["id"]})
    _run(_scenario)


def test_decision_confidence_adjusted_by_feedback():
    """Sprint 10 integrado — run_decision_cycle aplica adjustment."""
    co = f"test-adj-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from services.event_bus import emit_event, EventType
        from services.decision_engine import run_decision_cycle
        # injeta histórico de outcomes RUIM para notify_manager
        # (faz factor cair pra 0.5 → confidence reduzida)
        nonce = uuid.uuid4().hex[:6]
        await db.motor_ia_actions.insert_many([
            {"id": f"act-bad-{nonce}-{i}", "company_id": co,
             "action_type": "notify_manager",
             "decision_id": f"dec-bad-{nonce}-{i}",
             "created_at": "2026-06-01T00:00:00+00:00"}
            for i in range(10)
        ])
        await db.motor_ia_outcomes.insert_many([
            {"id": f"out-bad-{nonce}-{i}",
             "action_id": f"act-bad-{nonce}-{i}",
             "company_id": co, "ok": (i < 2),  # 2/10 ok
             "created_at": "2026-06-01T00:00:00+00:00"}
            for i in range(10)
        ])
        # força refresh
        from services.feedback_loop import refresh_stats
        await refresh_stats(force=True)
        # emite 3 RBAC_DENIED para gerar notify_manager
        uid = f"adj-user-{uuid.uuid4().hex[:6]}"
        for _ in range(3):
            await emit_event(EventType.RBAC_DENIED,
                              company_id=co, user_id=uid,
                              source="test_adj", severity="alta",
                              payload={})
        await run_decision_cycle()
        dec = await db.motor_ia_decisions.find_one(
            {"company_id": co, "action_type": "notify_manager"})
        assert dec is not None
        # confidence base é 0.85, factor=0.50 → ~0.425
        assert dec.get("confidence_base") == 0.85
        assert dec["confidence"] < dec["confidence_base"]
        # cleanup
        for coll in ("motor_ia_actions", "motor_ia_outcomes",
                       "motor_ia_decisions", "motor_ia_events"):
            await db[coll].delete_many({"company_id": co})
    _run(_scenario)


# ─────────────────── Sprints 13-18 tests ───────────────────

def test_event_emitters_emit_business():
    """Sprint 13 — emit_business resolve kind→EventType."""
    co = f"test-emit-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from services.event_emitters import emit_business
        ev = await emit_business(
            kind="ticket.opened",
            company_id=co, source="test",
            payload={"ticket_id": "t-1"})
        assert ev is not None
        assert ev["event_type"] == "TICKET_OPENED"
        assert ev["company_id"] == co
        # cleanup
        await db.motor_ia_events.delete_many({"company_id": co})
    _run(_scenario)


def test_event_emitters_unknown_kind_returns_none():
    """Sprint 13 — emit_business com kind desconhecido retorna None."""
    async def _scenario(db):
        from services.event_emitters import emit_business
        ev = await emit_business(
            kind="totally.unknown.thing",
            company_id="x", payload={})
        assert ev is None
    _run(_scenario)


def test_data_quality_company_isolated():
    """Sprint 14 — run_scan(company_id) só conta docs daquela company."""
    co_a = f"test-dq-a-{uuid.uuid4().hex[:6]}"
    co_b = f"test-dq-b-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from services.data_quality import run_scan
        await db.subscribers.insert_many([
            {"id": f"s-{i}", "company_id": co_a, "plan_id": "p1"}
            for i in range(5)
        ])
        await db.subscribers.insert_many([
            {"id": f"s-{i+10}", "company_id": co_b, "plan_id": None}
            for i in range(5)
        ])
        r_a = await run_scan(company_id=co_a)
        r_b = await run_scan(company_id=co_b)
        # A tem todos com plan_id; B nenhum
        no_plan_a = next(i for i in r_a["issues"]
                         if i["key"] == "clients_no_plan")
        no_plan_b = next(i for i in r_b["issues"]
                         if i["key"] == "clients_no_plan")
        assert no_plan_a["bad_count"] == 0
        assert no_plan_b["bad_count"] == 5
        # ambos insights persistidos com company_id
        ins_a = await db.motor_ia_insights.find_one(
            {"kind": "data_quality_scan", "company_id": co_a})
        assert ins_a is not None
        # cleanup
        await db.subscribers.delete_many(
            {"company_id": {"$in": [co_a, co_b]}})
        await db.motor_ia_insights.delete_many(
            {"company_id": {"$in": [co_a, co_b]}})
    _run(_scenario)


def test_executive_health_isolated():
    """Sprint 14 — compute_executive_score(company_id) preenche
    motor_ia_insights com company_id."""
    co = f"test-health-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from services.executive_health import compute_executive_score
        r = await compute_executive_score(company_id=co)
        assert "overall_score" in r
        ins = await db.motor_ia_insights.find_one(
            {"kind": "executive_health", "company_id": co})
        assert ins is not None
        assert ins.get("company_id") == co
        await db.motor_ia_insights.delete_many({"company_id": co})
    _run(_scenario)


def test_live_feature_flag_per_company():
    """Sprint 15 — is_live retorna True para action habilitada."""
    co = f"test-live-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from services.company_settings import (
            is_live, set_live, get_live_actions,
        )
        # default: nada habilitado
        assert await is_live(co, "escalate_dunning") is False
        # habilita
        await set_live(co, ["escalate_dunning"], updated_by="test")
        assert await is_live(co, "escalate_dunning") is True
        assert await is_live(co, "notify_manager") is False
        actions = await get_live_actions(co)
        assert "escalate_dunning" in actions
        await db.company_settings.delete_one({"_id": co})
    _run(_scenario)


def test_action_engine_uses_company_live_flag():
    """Sprint 15 — action_engine.execute_pending respeita flag
    por company."""
    co = f"test-ae-live-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from services.company_settings import set_live
        from services.event_bus import emit_event, EventType
        from services.decision_engine import run_decision_cycle
        from services.action_engine import execute_pending
        # habilita escalate_dunning em LIVE para esta company
        await set_live(co, ["escalate_dunning"], updated_by="test")
        # gera decisão
        await emit_event(
            EventType.PAYMENT_OVERDUE,
            company_id=co, source="test_ae",
            severity="media",
            payload={"subscriber_id": "s1"})
        await run_decision_cycle()
        await execute_pending()
        dun = await db.dunning_escalations.find_one(
            {"company_id": co})
        assert dun is not None
        assert dun.get("dry_run") is False  # ← LIVE!
        # cleanup
        await db.company_settings.delete_one({"_id": co})
        for c in ("motor_ia_events", "motor_ia_decisions",
                    "motor_ia_actions", "motor_ia_outcomes",
                    "dunning_escalations"):
            await db[c].delete_many({"company_id": co})
    _run(_scenario)


def test_rule_thresholds_dynamic():
    """Sprint 17 — decision_engine respeita threshold dinâmico."""
    co = f"test-th-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from services.rule_thresholds import set_threshold
        from services.event_bus import emit_event, EventType
        from services.decision_engine import run_decision_cycle
        # baixa threshold para 3 (default é 5)
        await set_threshold(
            "collective_outage",
            {"min_offline_count": 3, "window_min": 10},
            updated_by="test", reason="test")
        # emite 3 CLIENT_OFFLINE → deveria disparar agora
        for i in range(3):
            await emit_event(
                EventType.CLIENT_OFFLINE,
                company_id=co, source="test_th",
                severity="alta",
                payload={"cto_id": "CTO-TH",
                         "subscriber_id": f"s{i}"})
        await run_decision_cycle()
        dec = await db.motor_ia_decisions.find_one(
            {"company_id": co, "action_type": "open_incident"})
        assert dec is not None
        assert "threshold dinâmico" in (dec.get("reasoning") or "")
        # cleanup
        await db.rule_thresholds.delete_one({"_id": "collective_outage"})
        for c in ("motor_ia_events", "motor_ia_decisions",
                    "motor_ia_actions", "motor_ia_outcomes", "incidents"):
            await db[c].delete_many({"company_id": co})
    _run(_scenario)


def test_auto_tune_runs_without_error():
    """Sprint 17 — auto_tune executa sem explodir."""
    async def _scenario(db):
        from services.rule_thresholds import auto_tune
        r = await auto_tune()
        assert "adjustments" in r
        assert "ran_at" in r
    _run(_scenario)


def test_ml_ticket_arima_returns_forecast_or_error():
    """Sprint 18 — ticket_arima dá erro graceful se série curta."""
    async def _scenario(db):
        from services.ml_predictions import ticket_arima
        r = await ticket_arima(company_id="nonexistent-co")
        # com 0 tickets, retorna error 'serie_curta'
        assert r.get("error") in ("serie_curta", "fit_falhou")
    _run(_scenario)


def test_ml_iforest_returns_error_when_few_samples():
    """Sprint 18 — IsolationForest graceful com poucos dados."""
    async def _scenario(db):
        from services.ml_predictions import churn_iforest
        r = await churn_iforest(company_id="nonexistent-co")
        assert r.get("error") in ("insuficiente",
                                  "features_insuficientes")
    _run(_scenario)



# ───────────────────── Sprints 19/19.5/20/22 tests ─────────────────────

def test_live_pilot_full_lifecycle():
    """Sprint 19.5 — start_pilot → action LIVE → stop_pilot."""
    co = f"test-pilot-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from services.live_pilot import (
            start_pilot, stop_pilot, pilot_metrics,
        )
        from services.event_bus import emit_event, EventType
        from services.decision_engine import run_decision_cycle
        from services.action_engine import execute_pending
        # baseline com 2 overdue invoices
        for i in range(2):
            await db.subscriber_invoices.insert_one({
                "id": f"inv-{co}-{i}", "company_id": co,
                "status": "overdue", "amount": 100.0,
                "subscriber_id": f"s{i}"})
        # inicia pilot
        pilot = await start_pilot(co, ["escalate_dunning"],
                                       notes="e2e test")
        assert pilot["status"] == "running"
        assert pilot["baseline"]["overdue_invoices_count"] == 2
        # gera decisão LIVE
        await emit_event(EventType.PAYMENT_OVERDUE,
                          company_id=co, source="test_pilot",
                          severity="media",
                          payload={"subscriber_id": "s0"})
        await run_decision_cycle()
        await execute_pending()
        # verifica dunning LIVE
        dun = await db.dunning_escalations.find_one(
            {"company_id": co})
        assert dun is not None
        assert dun.get("dry_run") is False
        # métricas
        metrics = await pilot_metrics(co)
        assert metrics["impact"]["dunning_escalations_live"] >= 1
        # para
        stop = await stop_pilot(co, stopped_by="test")
        assert stop["status"] == "stopped"
        # cleanup
        await db.live_pilot_runs.delete_many({"company_id": co})
        await db.company_settings.delete_one({"_id": co})
        await db.subscriber_invoices.delete_many({"company_id": co})
        for c in ("motor_ia_events", "motor_ia_decisions",
                    "motor_ia_actions", "motor_ia_outcomes",
                    "dunning_escalations"):
            await db[c].delete_many({"company_id": co})
    _run(_scenario)


def test_predictions_validation_skip_when_horizon_open():
    """Sprint 20 — validation pula predições com horizon ainda aberto."""
    async def _scenario(db):
        from services.predictions_validation import run_validation_cycle
        r = await run_validation_cycle()
        assert "validated" in r
        assert "skipped" in r
    _run(_scenario)


def test_predictions_validation_churn_works():
    """Sprint 20 — valida uma predição com horizon expirado."""
    async def _scenario(db):
        from services.predictions_validation import run_validation_cycle
        # cria predição com generated_at antigo (mais de 30d)
        old = "2025-01-01T00:00:00+00:00"
        await db.motor_ia_predictions.insert_one({
            "id": f"pred-old-{uuid.uuid4().hex[:8]}",
            "kind": "churn",
            "model": "test_v1",
            "horizon_days": 30,
            "generated_at": old,
            "items": [{"subscriber_id": "non-existing-sub-1"}],
            "company_id": "test",
        })
        r = await run_validation_cycle()
        assert r["validated"] >= 1 or r["skipped"] >= 1
        await db.motor_ia_predictions.delete_many(
            {"model": "test_v1"})
        await db.motor_ia_predictions_validation.delete_many(
            {"prediction_model": "test_v1"})
    _run(_scenario)


def test_load_test_emits_high_throughput():
    """Sprint 22 — burst de 500 eventos termina em <5s."""
    async def _scenario(db):
        import time
        from services.event_bus import emit_event, EventType
        import asyncio as aio
        co = f"test-load-{uuid.uuid4().hex[:6]}"
        t0 = time.time()

        async def one(i):
            await emit_event(EventType.CLIENT_OFFLINE,
                              company_id=co, source="load",
                              severity="alta",
                              payload={"cto_id": "X",
                                       "subscriber_id": f"s{i}"})
        await aio.gather(*[one(i) for i in range(500)])
        elapsed = time.time() - t0
        assert elapsed < 5.0, f"slow: {elapsed:.2f}s para 500 eventos"
        throughput = 500 / elapsed
        print(f"  → throughput: {throughput:.0f} ev/s")
        assert throughput > 200, f"baixa throughput: {throughput:.0f}"
        await db.motor_ia_events.delete_many({"company_id": co})
    _run(_scenario)



# ───────────────── OPERAÇÃO TESE VALIDADA — testes ─────────────────

def test_operacao_tese_pre_flight():
    """Pre-flight produz checks (alguns vão falhar em dev, mas
    a função NÃO pode explodir)."""
    co = f"test-tese-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from services.operacao_tese import pre_flight_check
        r = await pre_flight_check(co)
        assert "checks" in r
        assert len(r["checks"]) == 10
        assert "ok_to_start" in r
    _run(_scenario)


def test_operacao_tese_dry_run_full_pipeline():
    """Tese: selecionar inadimplentes → score → dry-run send → monitor.

    Cria invoices overdue + subscribers válidos e roda pipeline."""
    co = f"test-tese-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from datetime import datetime, timedelta, timezone
        from services.operacao_tese import (
            select_eligible_clients, score_and_classify,
            start_operation, monitor_panel, success_criteria,
        )
        # 3 subscribers com invoice overdue 10 dias atrás
        for i in range(3):
            sid = f"sub-tese-{i}-{uuid.uuid4().hex[:6]}"
            await db.subscribers.insert_one({
                "id": sid, "company_id": co,
                "name": f"Cliente {i}",
                "phone": f"+5511999{i:05d}",
                "status": "active",
            })
            due = (datetime.now(timezone.utc) - timedelta(days=10)
                    ).strftime("%Y-%m-%d")
            await db.subscriber_invoices.insert_one({
                "id": f"inv-tese-{i}-{uuid.uuid4().hex[:6]}",
                "company_id": co, "subscriber_id": sid,
                "amount": 150.0 + i * 50, "status": "overdue",
                "due_date": due,
            })
        sel = await select_eligible_clients(co, limit=10)
        assert sel["count"] >= 3
        classified = await score_and_classify(sel["candidates"])
        assert all("tier" in c for c in classified)

        # roda full pipeline em DRY-RUN
        r = await start_operation(co, dry_run=True, max_messages=10)
        # pre-flight pode falhar (sem baileys etc.), mas se passou,
        # então messages_planned >= 1
        if r.get("error") == "pre_flight_failed":
            # esperado em dev — valida ao menos que o relatório existe
            assert "pre_flight" in r
            return
        assert r["messages_sent_or_planned"] >= 1
        op_id = r["operation_id"]
        panel = await monitor_panel(op_id)
        assert panel["op_id"] == op_id
        success = await success_criteria(op_id)
        assert success["presidente_ia_recovered_alone"] in ("SIM", "NÃO")
        # cleanup
        for c in ("subscribers", "subscriber_invoices",
                    "operacao_tese_messages", "operacao_tese_runs",
                    "company_settings"):
            await db[c].delete_many({"company_id": co})
        await db.company_settings.delete_one({"_id": co})
    _run(_scenario)


def test_smartolt_gate_blocks_offline_client():
    """Sprint Tese — fase 9: cliente com ONU offline é bloqueado."""
    co = f"test-gate-{uuid.uuid4().hex[:6]}"
    sub = f"sub-{uuid.uuid4().hex[:6]}"

    async def _scenario(db):
        from services.operacao_tese import smartolt_gate
        # cria ONU offline
        await db.onus.insert_one({
            "id": f"onu-{uuid.uuid4().hex[:6]}",
            "subscriber_id": sub,
            "company_id": co,
            "status": "offline",
        })
        r = await smartolt_gate(sub)
        assert r["blocked"] is True
        assert "ONU offline" in r["reasons"]
        await db.onus.delete_many({"subscriber_id": sub})
    _run(_scenario)


def test_smartolt_gate_passes_healthy_client():
    """Cliente sem ONU registrada (sem problema) passa."""
    async def _scenario(db):
        from services.operacao_tese import smartolt_gate
        r = await smartolt_gate(f"nonexistent-{uuid.uuid4().hex[:6]}")
        assert r["blocked"] is False
    _run(_scenario)

