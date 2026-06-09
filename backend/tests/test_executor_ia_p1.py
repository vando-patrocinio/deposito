"""Teste P1 do Executor IA — único teste sequencial que cobre todo
o ciclo: PROPOSE → COUNCIL → APPROVE → EXECUTE → ROI → CORRECTION
+ memória + state-of-presidency + transições.

Motor MongoDB compartilha event loop entre testes → consolidar tudo
em 1 função evita o erro 'Event loop is closed'.
"""
import pytest
from database import db
from services import executor_ia as ex

CID = "co-test-p1"


@pytest.mark.asyncio
async def test_executor_ia_ciclo_completo():
    # ── Limpa ──
    for col in ("motor_ia_actions", "motor_ia_kpis",
                 "pending_executions", "conselho_votes",
                 "motor_ia_corrections", "motor_ia_drift"):
        await db[col].delete_many({"company_id": CID})

    # ── 1) Categoria inválida é recusada ──
    with pytest.raises(ValueError):
        await ex.propose_action(
            company_id=CID, created_by="x",
            categoria="MAGIA_NEGRA",
            descricao="x", impacto_estimado_brl=10)

    # ── 2) Não executa sem aprovação ──
    a0 = await ex.propose_action(
        company_id=CID, created_by="x",
        categoria="DISPARO_COBRANCA",
        descricao="...", impacto_estimado_brl=100)
    with pytest.raises(ValueError):
        await ex.execute_action(a0["id"], "x", dry_run=True)
    await ex.cancel_action(a0["id"], "x", "teste cleanup")
    # cancelado não pode ser reaprovado
    with pytest.raises(ValueError):
        await ex.approve_action(a0["id"], "x")

    # ── 3) Memória vazia ──
    mem0 = await ex.consult_memory(CID, "REAJUSTE_IPCA")
    assert mem0["historico_n"] == 0

    # ── 4) Ciclo completo REAJUSTE_IPCA ──
    a = await ex.propose_action(
        company_id=CID, created_by="ceo@test",
        categoria="REAJUSTE_IPCA",
        descricao="Reajustar contratos vencidos",
        impacto_estimado_brl=423.19, prioridade="ALTA",
        payload={"ipca_pct": 0.045})
    assert a["status"] == "pending"
    assert a["snapshot_before_id"]
    assert len(a["history"]) == 1

    vote = await ex.collect_council_votes(a["id"])
    assert len(vote["votes"]) == 6
    assert "/" in vote["consensus"]["ratio"]
    assert vote["consensus"]["approved_count"] >= 1

    appr = await ex.approve_action(a["id"], "approver@test", "OK")
    assert appr["status"] == "approved"
    assert appr["approved_by"] == "approver@test"

    queue = await ex.list_queue(CID)
    assert any(x["action_id"] == a["id"] for x in queue)

    final = await ex.execute_action(a["id"], "executor@test",
                                          dry_run=True)
    assert final["status"] == "completed"
    assert final["executor_outcome"]["dry_run"] is True
    assert final["snapshot_after_id"]
    assert final["roi_brl"] == 0.0  # dry_run sem mudança

    # ── 5) Correção e drift registrados ──
    corr = await db.motor_ia_corrections.find_one(
        {"action_id": a["id"]}, {"_id": 0})
    assert corr is not None
    assert corr["valor_previsto_brl"] == 423.19
    assert corr["valor_real_brl"] == 0.0

    drift = await db.motor_ia_drift.find_one(
        {"company_id": CID, "categoria": "REAJUSTE_IPCA"},
        {"_id": 0})
    assert drift is not None
    assert drift["amostras"] == 1

    # ── 6) Ledger completo ──
    led = await ex.get_action_ledger(a["id"])
    assert led["quem_decidiu"] == "ceo@test"
    assert led["quem_aprovou"] == "approver@test"
    assert led["quem_executou"] == "executor@test"
    assert led["custo_estimado_brl"] == 423.19
    assert led["roi_pct"] == 0.0
    assert len(led["council_votes"]) == 6
    assert led["correction"] is not None
    assert len(led["history"]) >= 3

    # ── 7) Memória pós-execução ──
    mem1 = await ex.consult_memory(CID, "REAJUSTE_IPCA")
    assert mem1["historico_n"] == 1
    assert len(mem1["ultimas_acoes"]) == 1

    # ── 8) Mais 1 ação de outra categoria ──
    b = await ex.propose_action(
        company_id=CID, created_by="x",
        categoria="DISPARO_COBRANCA", descricao="...",
        impacto_estimado_brl=200)
    await ex.collect_council_votes(b["id"])
    await ex.approve_action(b["id"], "x")
    await ex.execute_action(b["id"], "x", dry_run=True)

    # ── 9) State of presidency: 9 perguntas obrigatórias ──
    state = await ex.state_of_presidency(CID, period_days=1)
    p = state["perguntas"]
    for chave in ("1_recomendei", "2_aprovado", "3_executado",
                    "4_gerou_resultado", "5_dinheiro_entrou_brl",
                    "6_dinheiro_salvo_brl", "7_deu_errado",
                    "8_aprendi", "9_farei_diferente"):
        assert chave in p
    assert p["1_recomendei"] == 3        # a0 + a + b
    assert p["2_aprovado"] == 2           # a + b (a0 foi cancelada)
    assert p["3_executado"] == 2
    assert p["4_gerou_resultado"] == 2
    assert state["totais"]["taxa_sucesso_pct"] == 100.0
