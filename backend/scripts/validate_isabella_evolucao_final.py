"""Validação OPERAÇÃO ISABELLA EVOLUÇÃO FINAL V2.

Roda 10 cenários reais contra o banco MongoDB (sem mocks):
  1) cobrança          6) incidente coletivo
  2) desbloqueio       7) upgrade
  3) segunda via       8) retenção
  4) lentidão          9) indicação
  5) sem conexão      10) Security Home

Para cada cenário:
  • Persiste mensagem inbound em aihub_wa_messages.
  • Chama register_followup() com user_text + isabella_reply simuladas.
  • Verifica em ai_evaluations:
      - outcome ∈ {RESOLVIDO, PLANO_DE_ACAO, VENDA, RETENCAO, COBRANCA, ACOMPANHAMENTO}
      - nps_inferido em [0,10]
      - memoria_operacional preenchida
      - premium_repair calculado
      - aprendizado completo

Saída: JSON com 10 evidências + comparativo antes/depois.
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")

from database import db  # noqa: E402
from services.isabella_ceo_followup import register_followup  # noqa: E402


COMPANY_ID = os.environ.get("DEMO_COMPANY_ID", "co-demo")
TEST_PHONE = "5521998176526"


SCENARIOS = [
    # (label, user_text, isabella_reply_simulada, outcome_esperado)
    ("cobranca",
     "Oi, minha fatura venceu ontem e não consegui pagar. Posso negociar?",
     "Imagino o aperto. Já liberei seu acesso por 48h e gerei 2ª via no Pix. "
     "Se preferir, parcelo em 2x no boleto. Cobrarei junto na próxima fatura. "
     "Objetivo: regularizar pagamento. Responsável: eu mesma. "
     "Prazo: hoje 18h. Confirmação: vou te enviar o comprovante de geração. "
     "Outcome: COBRANCA",
     "COBRANCA"),

    ("desbloqueio",
     "Estou sem acesso, paguei essa manhã e ainda nao desbloqueou",
     "Entendo. Confirmei seu pagamento de hoje 09:12 e liberei o acesso "
     "manualmente. Em até 5 minutos seu modem reconecta sozinho. Tudo certo! "
     "Outcome: RESOLVIDO",
     "RESOLVIDO"),

    ("segunda_via",
     "Pode me mandar a segunda via do boleto?",
     "Claro! Já enviei a 2ª via no seu WhatsApp e no e-mail cadastrado. "
     "Vence em 3 dias. Outcome: COBRANCA",
     "COBRANCA"),

    ("lentidao",
     "A internet ta muito lenta hoje, não consigo trabalhar.",
     "Imagino a frustração no home office. Vi aqui sua ONU online, sinal "
     "OK, mas detectei congestionamento na sua CTO. Vou agendar a equipe "
     "técnica para passar amanhã 09h reorganizar a fibra. "
     "Objetivo: restaurar velocidade plena. Responsável: equipe técnica. "
     "Prazo: amanhã 09h. Confirmação: técnico ligará 30 min antes. "
     "Outcome: PLANO_DE_ACAO",
     "PLANO_DE_ACAO"),

    ("sem_conexao",
     "minha internet caiu de novo, ja é a terceira vez essa semana",
     "Sei que é cansativo, vou cuidar disso pessoalmente. Identifiquei "
     "padrão de queda na sua CTO RIO_HUAWEI::7/0 - já são 3 vizinhos com "
     "o mesmo sintoma. Equipe técnica já foi acionada e está a caminho. "
     "Objetivo: substituir splitter da CTO. Responsável: equipe técnica. "
     "Prazo: hoje em 4h. Confirmação: te aviso quando normalizar. "
     "Outcome: PLANO_DE_ACAO",
     "PLANO_DE_ACAO"),

    ("incidente_coletivo",
     "Acabou a internet aqui na rua toda",
     "Já estamos resolvendo! Identificamos uma pane regional na sua área "
     "afetando 28 vizinhos. Equipe técnica em deslocamento agora. "
     "Previsão de retorno em 2h. Te aviso assim que normalizar. "
     "Outcome: ACOMPANHAMENTO",
     "ACOMPANHAMENTO"),

    ("upgrade",
     "queria saber se tem plano mais rápido",
     "Sim! Vi que seu plano atual é 300MB. Recomendo upgrade para 1 Giga: "
     "estabilidade premium para home office e jogos sem travar. "
     "Combo com PlayHub fica R$ 30 mais barato que separado. "
     "Pode adicionar? Outcome: PLANO_DE_ACAO",
     "PLANO_DE_ACAO"),

    ("retencao",
     "quero cancelar meu plano, esta caro e nao uso",
     "Entendo. Antes de cancelar, deixa eu te mostrar: você é cliente há "
     "18 meses e tem desconto fidelidade disponível. Posso aplicar R$ 20 "
     "de abatimento agora e ainda incluir o PlayHub sem custo no primeiro "
     "mês. Mantemos seu plano? Outcome: RETENCAO",
     "RETENCAO"),

    ("indicacao",
     "Tem algum programa de indicação?",
     "Temos sim! O Indique e Ganhe te dá R$ 30 de desconto por cada amigo "
     "que assinar. Posso já gerar seu link exclusivo? "
     "Outcome: ACOMPANHAMENTO",
     "ACOMPANHAMENTO"),

    ("security_home",
     "queria saber sobre o alarme de casa que vcs tem",
     "Ótima escolha! O Ligo Security é o alarme residencial integrado "
     "com sua internet — combo família/segurança. Monitoramento 24h e "
     "app de controle. Combo com seu plano fica R$ 49/mês. "
     "Quer que eu adicione? Outcome: PLANO_DE_ACAO",
     "PLANO_DE_ACAO"),
]


async def _seed_subscriber_if_missing() -> str:
    """Garante que existe 1 subscriber-alvo (não cria coleção, só doc)."""
    sub = await db.subscribers.find_one(
        {"company_id": COMPANY_ID, "phones": {"$in": [TEST_PHONE]}},
        {"_id": 0, "id": 1, "churn_score": 1, "monthly_value": 1})
    if sub:
        return sub["id"]
    # Cria um subscriber sintético para teste — alto risco para Premium Repair ativar
    sub_id = f"sub-test-{uuid.uuid4().hex[:8]}"
    await db.subscribers.insert_one({
        "id": sub_id,
        "company_id": COMPANY_ID,
        "name": "Cliente Teste Evolução Final V2",
        "phones": [TEST_PHONE],
        "plan_name": "Fibra 300MB",
        "monthly_value": 99.90,
        "plan_value": 99.90,
        "plan_price": 99.90,
        "status": "ACTIVE",
        "activated_at": "2024-08-01T00:00:00+00:00",
        "created_at": "2024-08-01T00:00:00+00:00",
        "churn_score": 0.72,
        "retention_score": 0.65,
        "referral_score": 0.40,
        "collection_score": 0.55,
    })
    return sub_id


async def _ingest_inbound(phone: str, text: str) -> None:
    await db.aihub_wa_messages.insert_one({
        "id": f"wam-{uuid.uuid4().hex[:10]}",
        "company_id": COMPANY_ID,
        "direction": "inbound",
        "channel": "twilio",
        "phone": phone,
        "text": text,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


async def main() -> None:
    sub_id = await _seed_subscriber_if_missing()
    print(f"[seed] subscriber_id={sub_id}")

    # Baseline: contagens antes
    before_total = await db.ai_evaluations.count_documents({"company_id": COMPANY_ID})
    before_v2 = await db.ai_evaluations.count_documents(
        {"company_id": COMPANY_ID, "outcome": {"$exists": True}})

    results = []
    for label, user_text, reply, expected in SCENARIOS:
        await _ingest_inbound(TEST_PHONE, user_text)
        doc = await register_followup(
            company_id=COMPANY_ID,
            subscriber_id=sub_id,
            phone=TEST_PHONE,
            user_text=user_text,
            isabella_reply=reply,
            context_used="=== TEST ==="
        )
        # Valida estrutura
        checks = {
            "outcome_present": doc.get("outcome") is not None,
            "outcome_match": doc.get("outcome") == expected,
            "nps_in_range": 0 <= int(doc.get("nps_inferido") or -1) <= 10,
            "memoria_present": isinstance(doc.get("memoria_operacional"), dict),
            "premium_calculated": isinstance(doc.get("premium_repair"), dict),
            "aprendizado_complete": all(
                k in (doc.get("aprendizado") or {})
                for k in ("cliente_satisfeito", "houve_venda", "houve_retencao",
                          "o_que_funcionou", "o_que_nao_funcionou")),
        }
        results.append({
            "scenario": label,
            "expected_outcome": expected,
            "got_outcome": doc.get("outcome"),
            "nps_inferido": doc.get("nps_inferido"),
            "nps_motivo": doc.get("nps_motivo"),
            "memoria_operacional": doc.get("memoria_operacional"),
            "premium_repair": doc.get("premium_repair"),
            "plano_acao": doc.get("plano_acao"),
            "aprendizado": doc.get("aprendizado"),
            "eval_id": doc.get("id"),
            "checks": checks,
            "pass": all(checks.values()),
        })

    after_total = await db.ai_evaluations.count_documents({"company_id": COMPANY_ID})
    after_v2 = await db.ai_evaluations.count_documents(
        {"company_id": COMPANY_ID, "outcome": {"$exists": True}})

    total_pass = sum(1 for r in results if r["pass"])
    summary = {
        "company_id": COMPANY_ID,
        "subscriber_id": sub_id,
        "scenarios_run": len(SCENARIOS),
        "scenarios_pass": total_pass,
        "scenarios_fail": len(SCENARIOS) - total_pass,
        "outcomes_observed": sorted({r["got_outcome"] for r in results}),
        "before": {"ai_evaluations_total": before_total,
                   "ai_evaluations_with_outcome": before_v2},
        "after": {"ai_evaluations_total": after_total,
                  "ai_evaluations_with_outcome": after_v2},
        "results": results,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    out_path = "/app/docs/RELATORIO_ISABELLA_EVOLUCAO_FINAL_V2.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str)[:3000])
    print(f"\n[ok] relatório completo gravado em {out_path}")
    print(f"[summary] {total_pass}/{len(SCENARIOS)} cenários OK")


if __name__ == "__main__":
    asyncio.run(main())
