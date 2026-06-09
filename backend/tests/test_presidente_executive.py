"""Smoke test do relatório executivo do Presidente IA V10."""
import pytest
from services.presidente_executive import build_executive_report


@pytest.mark.asyncio
async def test_executive_report_shape():
    r = await build_executive_report("co-demo")
    # Estrutura obrigatória
    assert set(r.keys()) >= {
        "president_score", "riscos_criticos", "oportunidades",
        "previsao_30d", "dinheiro_em_risco", "dinheiro_recuperavel",
        "surpresas", "acoes_presidenciais", "fontes",
        "contexto_financeiro",
    }
    # Score 0..100
    assert 0 <= r["president_score"]["score"] <= 100
    assert r["president_score"]["status"] in (
        "saudavel", "atencao", "alerta", "critico")
    # 8 drivers
    assert len(r["president_score"]["components"]) == 8
    # exatamente 5 ações
    assert len(r["acoes_presidenciais"]) == 5
    for a in r["acoes_presidenciais"]:
        assert a["acao"]
        assert "impacto_brl" in a
        assert a["prioridade"] in ("ALTA", "MÉDIA", "BAIXA")
    # surpresas ≤ 10
    assert len(r["surpresas"]) <= 10
    # dinheiro em risco com breakdown completo
    br = r["dinheiro_em_risco"]["breakdown"]
    for k in ("churn_previsto_30d", "inadimplencia_atual",
                "reajuste_atrasado_mensal",
                "equipamentos_nao_recuperados",
                "outages_30d_propensao_churn"):
        assert k in br
        assert "brl" in br[k]
    # previsão executiva com explicação causal
    assert r["previsao_30d"]["explicacao_causal"]
    assert r["previsao_30d"]["risco_operacional"] in (
        "BAIXO", "MÉDIO", "ALTO")
    # Cada risco com impacto_brl e ação
    for risc in r["riscos_criticos"]:
        assert risc["acao"]
        assert risc["impacto_brl"] >= 0
        assert risc["probabilidade_pct"] >= 0
    # fontes registradas
    assert "usadas" in r["fontes"]
    assert "ausentes" in r["fontes"]
