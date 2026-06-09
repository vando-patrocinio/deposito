"""Teste V11 do Governador IA — único teste sequencial cobrindo
as 10 capacidades (mesma estratégia de loop único do P1)."""
import pytest
from datetime import datetime, timedelta, timezone
from database import db
from services import governador_ia as gov

CID = "co-test-v11"


@pytest.mark.asyncio
async def test_governador_ia_10_capacidades():
    # Clean
    for col in ("corporate_goals", "president_daily",
                 "motor_ia_actions", "motor_ia_kpis",
                 "motor_ia_corrections", "motor_ia_drift"):
        await db[col].delete_many({"company_id": CID})

    # --- 1) METAS — area/metric inválida recusa ---
    with pytest.raises(ValueError):
        await gov.create_goal(
            company_id=CID, area="FANTASIA", metric="mrr_brl",
            target_value=1, deadline_iso="2030-01-01",
            owner="x", created_by="x")
    with pytest.raises(ValueError):
        await gov.create_goal(
            company_id=CID, area="RECEITA", metric="MAGICA",
            target_value=1, deadline_iso="2030-01-01",
            owner="x", created_by="x")

    deadline = (datetime.now(timezone.utc)
                 + timedelta(days=30)).isoformat()
    g = await gov.create_goal(
        company_id=CID, area="RECEITA", metric="mrr_brl",
        target_value=400000, deadline_iso=deadline,
        owner="diretor.comercial", created_by="ceo@test",
        ia_responsavel="isabella")
    assert g["id"].startswith("goal-")
    assert g["baseline_value"] is not None
    assert g["target_value"] == 400000
    assert g["status"] == "active"

    # --- 1b) listagem + refresh ---
    goals = await gov.list_goals(CID)
    assert len(goals) == 1
    refresh = await gov.refresh_all_goals(CID)
    assert refresh["total"] == 1

    # --- 2) SCORE DAS IAs ---
    cards = await gov.scorecard_ias(CID, period_days=30)
    assert isinstance(cards, list)
    # Para tenant novo sem ações, lista pode estar vazia — ok
    for c in cards:
        assert "agente" in c and "score" in c

    # --- 3) ROI POR IA ---
    roi = await gov.roi_por_ia(CID, period_days=30)
    assert "total_brl" in roi and "por_agente" in roi

    # --- 4) COBRANÇA ---
    cob = await gov.cobranca_resultado(CID)
    assert len(cob) == 1
    assert cob[0]["ia_responsavel"] == "isabella"
    assert cob[0]["diagnostico"] in (
        "no_prazo", "em_risco", "entregue", "atrasada")

    # --- 5) PRIORIDADES (reuso V10) ---
    prio = await gov.prioridades_executivas(CID)
    assert len(prio) == 5    # regra do V10 — sempre 5

    # --- 6) SAÚDE ---
    saude = await gov.saude_corporativa(CID)
    assert 0 <= saude["score"] <= 100
    assert saude["status"] in (
        "saudavel", "atencao", "alerta", "critico")
    assert len(saude["components"]) == 8

    # --- 7) SISTEMA NERVOSO ---
    nervoso = await gov.sistema_nervoso(CID, hours=24)
    assert "coverage" in nervoso
    assert "events_by_domain" in nervoso

    # --- 8) MAPA EXECUTIVO ---
    mapa = await gov.mapa_executivo(CID)
    assert len(mapa["areas"]) == 6   # 6 áreas hardcoded
    areas_names = [a["area"] for a in mapa["areas"]]
    assert "RECEITA" in areas_names
    receita = next(a for a in mapa["areas"]
                    if a["area"] == "RECEITA")
    assert receita["metas_total"] == 1   # a meta criada

    # --- 9) RANKING ---
    rank = await gov.ranking_eficiencia(CID, period_days=30)
    # pode estar vazio em tenant novo — só validar estrutura
    for r in rank:
        assert r["posicao"] >= 1

    # --- 10) RELATÓRIO DIÁRIO ---
    daily = await gov.relatorio_presidencial_diario(
        CID, force=True)
    assert daily["date_key"]
    assert "saude" in daily and "metas" in daily
    assert "prioridades_hoje" in daily
    assert "ranking_top" in daily and "ranking_flop" in daily
    assert "roi_30d" in daily and "mapa_executivo" in daily
    assert "sistema_nervoso_24h" in daily
    assert daily["narrativa"]
    assert daily["metas"]["total_ativas"] == 1

    # Cache funciona: segunda chamada sem force devolve o mesmo doc
    cached = await gov.relatorio_presidencial_diario(CID, force=False)
    assert cached["id"] == daily["id"]
