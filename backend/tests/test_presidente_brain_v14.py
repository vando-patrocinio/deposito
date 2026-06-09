"""Teste V12+V13+V14 — cobre causality, twin, autopilot.

Único teste sequencial (motor MongoDB + pytest-asyncio compartilham
event loop)."""
import pytest
from datetime import datetime, timezone, timedelta
from database import db
from services import presidente_brain as br
from services import executor_ia as ex
from services import governador_ia as gov

CID = "co-test-v14"


@pytest.mark.asyncio
async def test_presidente_brain_v12_v13_v14():
    # Clean
    for col in ("motor_ia_actions", "motor_ia_kpis",
                 "motor_ia_corrections", "motor_ia_drift",
                 "pending_executions", "conselho_votes",
                 "subscribers", "smartolt_onus", "tickets",
                 "subscriber_invoices", "smart_repairs",
                 "smart_installs", "wa_conversations",
                 "corporate_goals"):
        await db[col].delete_many({"company_id": CID})

    # Seed mínimo
    sub_id = "sub-test-v14"
    await db.subscribers.insert_one({
        "id": sub_id, "company_id": CID, "name": "Cliente Teste",
        "status": "ATIVO", "plan_name": "100M",
        "plan_price": 99.90,
        "installation_date": (datetime.now(timezone.utc)
                                 - timedelta(days=180)).isoformat(),
    })
    await db.smartolt_onus.insert_one({
        "id": "onu-1", "company_id": CID,
        "subscriber_id": sub_id, "signal_text": "Critical",
        "olt_name": "OLT01", "zone_name": "ZONA-A",
        "status": "Online",
    })
    await db.tickets.insert_one({
        "id": "tk-1", "company_id": CID, "subscriber_id": sub_id,
        "status": "pendente", "title": "sinal ruim",
        "created_at": "2026-06-01T00:00:00+00:00"})
    await db.smart_installs.insert_one({
        "id": "ins-1", "company_id": CID, "subscriber_id": sub_id,
        "technician": "Téc João", "technician_id": "tec-1",
        "installed_at": "2025-12-01T00:00:00+00:00",
        "result": "ok"})

    # ── V13 — Digital Twin: subscriber ──
    twin = await br.digital_twin_subscriber(sub_id)
    assert twin["subscriber"]["name"] == "Cliente Teste"
    assert twin["rede"]["onu"]["signal_text"] == "Critical"
    assert twin["atendimento"]["tickets_em_aberto"] == 1
    assert twin["tecnico_instalador"]["technician"] == "Téc João"
    assert twin["meses_ativo"] >= 5
    assert "Sinal crítico" in twin["motivo_raiz_mais_provavel"]
    assert twin["ltv_estimado_brl"] > 0

    # ── V13 — Twin global ──
    g = await br.digital_twin_global(CID)
    assert g["clientes_ativos"] == 1
    assert g["onus_critical"] == 1
    assert g["mrr_brl"] == 99.90

    # ── V12 — Causality: criar 1 ação completed e atribuir ──
    a = await ex.propose_action(
        company_id=CID, created_by="x",
        categoria="REAJUSTE_IPCA",
        descricao="reajuste teste",
        impacto_estimado_brl=200.0)
    await ex.collect_council_votes(a["id"])
    await ex.approve_action(a["id"], "x")
    await ex.execute_action(a["id"], "x", dry_run=True)

    c = await br.causality_for_action(a["id"])
    assert c["categoria"] == "REAJUSTE_IPCA"
    assert c["field_observado"] == "mrr_brl"
    assert c["valor_antes"] is not None
    assert c["valor_depois"] is not None
    assert 0 <= c["causality_score"] <= 100
    assert c["veredicto"] in (
        "CAUSA_FORTE", "CAUSA_PROVAVEL",
        "CAUSA_FRACA", "INDETERMINADO")
    assert "fatores" in c
    assert set(c["fatores"].keys()) == {
        "sinal", "isolamento",
        "historico_acerto", "temporalidade"}

    summary = await br.causality_summary_30d(CID)
    assert summary["acoes_analisadas"] == 1
    assert summary["por_categoria"][0]["categoria"] == "REAJUSTE_IPCA"

    # ── V14 — Autopilot top10 ──
    # cria 1 meta para gerar entrada de meta_em_risco
    await gov.create_goal(
        company_id=CID, area="RECEITA", metric="mrr_brl",
        target_value=500000.0,
        deadline_iso=(datetime.now(timezone.utc)
                       + timedelta(days=30)).isoformat(),
        owner="ceo", created_by="ceo")
    auto = await br.autopilot_top10(CID)
    assert "top10" in auto
    assert len(auto["top10"]) <= 10
    assert auto["valor_esperado_total_brl"] >= 0
    assert auto["se_autopilot_autorizado"]
    # toda decisão tem 6 campos exigidos
    for d in auto["top10"]:
        for k in ("impacto_financeiro_brl", "risco",
                   "confianca_pct", "esforco", "prazo_dias",
                   "roi_esperado_brl", "valor_esperado_brl"):
            assert k in d
