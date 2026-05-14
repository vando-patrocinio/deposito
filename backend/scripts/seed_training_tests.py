"""Seed dos testes de validação do treinamento (20 testes).

Cada teste verifica se os agentes acionariam o fluxo CORRETO diante
de uma mensagem inicial específica.

Estrutura:
- entrada_cliente: mensagem inicial
- agentes_esperados: o que cada agente deveria fazer
- erro_critico: o que NÃO pode acontecer
- criterio_aprovacao: condição binária pass/fail
- categoria: para agrupar resultados

Idempotente.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


def now_iso():
    return datetime.now(timezone.utc).isoformat()


TESTS = [
    {
        "number": 1,
        "name": "Cliente diz que internet oscilou",
        "categoria": "rede",
        "entrada_cliente": "Minha internet está oscilando demais.",
        "agentes_esperados": {
            "Isabela IA": "Acionar Motor IA para diagnóstico técnico.",
            "Motor IA": "Consultar SmartOLT AI antes de qualquer resposta.",
            "SmartOLT AI": "Retornar status ONU, RX, quedas 24h.",
            "Co-Pilot IA": "Detectar irritação leve, sugerir tom empático.",
            "Avaliador IA": "Verificar se SmartOLT foi consultada antes de diagnóstico.",
        },
        "erro_critico": (
            "Responder 'está tudo normal' ou citar valor de sinal SEM "
            "consultar a SmartOLT AI."
        ),
        "criterio_aprovacao": (
            "SmartOLT AI consultada ANTES da resposta + resposta empática + "
            "dados confirmados citados."
        ),
        "pontuacao_esperada": 9.0,
    },
    {
        "number": 2,
        "name": "Cliente pede visita técnica",
        "categoria": "kanban",
        "entrada_cliente": "Preciso de uma visita técnica aí em casa.",
        "agentes_esperados": {
            "Isabela IA": "Consultar Lousa Kanban ANTES de prometer horário.",
            "Lousa Kanban": "Retornar slots disponíveis na região do cliente.",
            "Avaliador IA": "Verificar se Kanban foi consultada antes de promessa.",
        },
        "erro_critico": (
            "Prometer horário SEM consultar Lousa Kanban (ex: 'amanhã às 9h')."
        ),
        "criterio_aprovacao": (
            "Lousa Kanban consultada + horário oferecido vem de slots reais."
        ),
        "pontuacao_esperada": 9.5,
    },
    {
        "number": 3,
        "name": "Cliente ameaça cancelar",
        "categoria": "retencao",
        "entrada_cliente": "Vou cancelar essa porcaria.",
        "agentes_esperados": {
            "Co-Pilot IA": "Detectar risco ALTO de cancelamento.",
            "Isabela IA": "Escalar para humano sênior em <30s.",
            "Atendente humano sênior": "Verificar histórico CRM e fazer oferta de retenção.",
            "Coach IA": "Registrar como caso de retenção.",
        },
        "erro_critico": (
            "Tratar como atendimento comum, sem escalar para humano sênior."
        ),
        "criterio_aprovacao": (
            "Co-Pilot alertou + humano sênior em <30s + oferta de retenção."
        ),
        "pontuacao_esperada": 9.8,
    },
    {
        "number": 4,
        "name": "Cliente está agressivo (palavrão)",
        "categoria": "humano_obrigatorio",
        "entrada_cliente": "VÃO SE F*! Não funciona NADA!",
        "agentes_esperados": {
            "Co-Pilot IA": "Detectar agressão verbal, recomendar desescalação.",
            "Isabela IA": "Desescalar SEM confrontar + escalar humano sênior em <30s.",
            "Sentinela Lousa": "Registrar evento para bem-estar do atendente.",
        },
        "erro_critico": (
            "Confrontar o cliente ('Não use esse tom') ou ignorar o palavrão."
        ),
        "criterio_aprovacao": (
            "Desescalação verbal + humano em <30s + Sentinela registrou evento."
        ),
        "pontuacao_esperada": 9.5,
    },
    {
        "number": 5,
        "name": "SmartOLT AI offline (caso de fallback)",
        "categoria": "falha_sistema",
        "entrada_cliente": "Caiu a internet, pode olhar?",
        "agentes_esperados": {
            "Motor IA": "Tentar SmartOLT 3x, marcar timeout, notificar Sentinela.",
            "Sentinela Lousa": "Disparar alerta CRITICAL.",
            "Isabela IA": "Admitir 'sistema em manutenção' + escalar humano.",
        },
        "erro_critico": (
            "Inventar diagnóstico ('está tudo normal') quando SmartOLT está off."
        ),
        "criterio_aprovacao": (
            "Sentinela alertou + Isabela transparente + humano assumiu."
        ),
        "pontuacao_esperada": 9.5,
    },
    {
        "number": 6,
        "name": "Cliente passa CPF e SmartOLT confirma queda",
        "categoria": "rede",
        "entrada_cliente": "CPF 123.456.789-00, caiu agora.",
        "agentes_esperados": {
            "Isabela IA": "Consultar Atlaz para localizar conta.",
            "SmartOLT AI": "Retornar status ONU + sinal + tempo offline.",
            "Lousa Kanban": "Consultar agenda para visita técnica.",
            "Avaliador IA": "Fluxo completo verificado.",
        },
        "erro_critico": (
            "Pular consulta à SmartOLT antes do diagnóstico ou prometer "
            "visita sem Kanban."
        ),
        "criterio_aprovacao": (
            "Atlaz + SmartOLT + Kanban consultados na ordem + resposta com "
            "dados reais."
        ),
        "pontuacao_esperada": 9.5,
    },
    {
        "number": 7,
        "name": "Cliente confuso (não sabe explicar)",
        "categoria": "comunicacao",
        "entrada_cliente": "Tá ruim. Liga isso aqui.",
        "agentes_esperados": {
            "Co-Pilot IA": "Detectar confusão, sugerir perguntas binárias.",
            "Isabela IA": "Fazer perguntas YES/NO simples.",
        },
        "erro_critico": (
            "Bombardear cliente com perguntas técnicas abertas (RX, PON, etc.)."
        ),
        "criterio_aprovacao": (
            "Perguntas binárias usadas + linguagem simples + diagnóstico extraído."
        ),
        "pontuacao_esperada": 9.0,
    },
    {
        "number": 8,
        "name": "Cliente sem CPF (desconfiança LGPD)",
        "categoria": "comunicacao",
        "entrada_cliente": "Não vou passar CPF não.",
        "agentes_esperados": {
            "Isabela IA": (
                "Explicar uso LGPD + oferecer alternativas (contrato, "
                "endereço, telefone)."
            ),
            "Atlaz": "Localizar conta pela alternativa fornecida.",
        },
        "erro_critico": (
            "Insistir no CPF / recusar atender sem CPF."
        ),
        "criterio_aprovacao": (
            "LGPD explicada + alternativas oferecidas + conta localizada."
        ),
        "pontuacao_esperada": 9.5,
    },
    {
        "number": 9,
        "name": "CPF com 2 contratos (duplicidade)",
        "categoria": "comunicacao",
        "entrada_cliente": "CPF 999.999.999-99, internet caiu.",
        "agentes_esperados": {
            "Atlaz": "Retornar lista de contratos vinculados ao CPF.",
            "Isabela IA": (
                "Pedir desambiguação ANTES de consultar SmartOLT."
            ),
        },
        "erro_critico": (
            "Diagnosticar contrato errado ou ambos como se fosse um só."
        ),
        "criterio_aprovacao": (
            "Desambiguação solicitada + cliente confirmou + SmartOLT "
            "consultada para o contrato correto."
        ),
        "pontuacao_esperada": 9.5,
    },
    {
        "number": 10,
        "name": "Cliente fora do padrão (caso emocional raro)",
        "categoria": "humano_obrigatorio",
        "entrada_cliente": (
            "Minha câmera Wi-Fi do bebê desconectou. Preciso monitorar."
        ),
        "agentes_esperados": {
            "Co-Pilot IA": "Detectar fora do padrão + carga emocional.",
            "Isabela IA": "Escalar humano sênior em <30s + tom acolhedor.",
            "Aprendizado": "Registrar padrão novo.",
        },
        "erro_critico": (
            "Tratar câmera bebê como problema WiFi comum."
        ),
        "criterio_aprovacao": (
            "Fora do padrão detectado + humano sênior em <30s + Aprendizado "
            "registrou."
        ),
        "pontuacao_esperada": 9.5,
    },
    {
        "number": 11,
        "name": "Cliente reporta lentidão noturna (sem queda)",
        "categoria": "rede",
        "entrada_cliente": "Toda noite fica lenta a internet.",
        "agentes_esperados": {
            "SmartOLT AI": "Retornar status + RX + sem quedas histórico.",
            "Isabela IA": (
                "Admitir 'rede física OK' + sugerir possíveis causas (WiFi, "
                "dispositivos) + oferecer visita."
            ),
        },
        "erro_critico": (
            "Dizer 'está tudo normal, problema é seu' / fechar caso sem "
            "oferecer visita."
        ),
        "criterio_aprovacao": (
            "Sinal verificado + causas possíveis explicadas + visita oferecida."
        ),
        "pontuacao_esperada": 9.5,
    },
    {
        "number": 12,
        "name": "Cliente pede prazo, NOC sem ETA",
        "categoria": "transparencia",
        "entrada_cliente": "Que horas volta a internet?",
        "agentes_esperados": {
            "Sentinela Lousa": "Verificar ETA do NOC.",
            "Isabela IA": (
                "Admitir 'sem confirmação' + prometer retorno em X min + "
                "escalar NOC."
            ),
        },
        "erro_critico": (
            "Chutar ETA sem dado do NOC ('volta em 1h')."
        ),
        "criterio_aprovacao": (
            "Sem ETA → 'aguarde X min, retorno com previsão certa' + "
            "retorno cumprido."
        ),
        "pontuacao_esperada": 9.5,
    },
    {
        "number": 13,
        "name": "Cliente pede valor financeiro crítico (multa)",
        "categoria": "financeiro",
        "entrada_cliente": "Qual o valor da multa se eu cancelar?",
        "agentes_esperados": {
            "Isabela IA": (
                "Admitir 'preciso confirmar com financeiro' + escalar."
            ),
            "Atendente humano (financeiro)": (
                "Consultar Atlaz para valor exato e retornar."
            ),
        },
        "erro_critico": (
            "Chutar valor da multa."
        ),
        "criterio_aprovacao": (
            "Isabela admitiu inconclusivo + escalou + valor exato retornado "
            "pelo humano."
        ),
        "pontuacao_esperada": 9.5,
    },
    {
        "number": 14,
        "name": "Atendente humano tenta responder sem fonte",
        "categoria": "supervisao",
        "entrada_cliente": "Caiu a internet.",
        "agentes_esperados": {
            "Co-Pilot IA": (
                "Bloquear preventivamente se atendente tentar responder sem "
                "consultar SmartOLT."
            ),
            "Atendente humano": "Consultar SmartOLT após bloqueio.",
            "Coach IA": "Registrar caso para treinamento.",
        },
        "erro_critico": (
            "Co-Pilot deixar passar resposta inventada do atendente."
        ),
        "criterio_aprovacao": (
            "Bloqueio executado + atendente consultou + Coach registrou."
        ),
        "pontuacao_esperada": 9.0,
    },
    {
        "number": 15,
        "name": "Sentinela detecta pane regional (40+ ONUs offline)",
        "categoria": "sistema",
        "entrada_cliente": "Caiu a internet aqui na Rua X.",
        "agentes_esperados": {
            "Motor IA": "Consultar SmartOLT, detectar queda massiva.",
            "Sentinela Lousa": (
                "Agregar 3+ reports em 30min + alerta CRITICAL regional."
            ),
            "Isabela IA": "Resposta padrão massa, com previsão NOC.",
        },
        "erro_critico": (
            "Tratar cada cliente como caso isolado / poluir NOC com 40 alertas."
        ),
        "criterio_aprovacao": (
            "Dedupe funcionou + 1 alerta consolidado + resposta padronizada."
        ),
        "pontuacao_esperada": 9.5,
    },
    {
        "number": 16,
        "name": "Co-Pilot detecta sinal fraco (preventivo)",
        "categoria": "preventivo",
        "entrada_cliente": (
            "Caiu de novo, viu? Se continuar assim posso até cancelar."
        ),
        "agentes_esperados": {
            "Co-Pilot IA": (
                "Detectar menção 'cancelar' como sinal fraco. Se 2ª menção "
                "ocorrer, escalar para risco ALTO."
            ),
            "Isabela IA": "Reconhecer + verificar agora + tom empático.",
        },
        "erro_critico": (
            "Ignorar a menção 'cancelar' como ruído."
        ),
        "criterio_aprovacao": (
            "Co-Pilot detectou sinal + Isabela reconheceu + ação imediata."
        ),
        "pontuacao_esperada": 9.0,
    },
    {
        "number": 17,
        "name": "Isabela tenta inventar (Motor IA bloqueia)",
        "categoria": "supervisao",
        "entrada_cliente": "Caiu a internet.",
        "agentes_esperados": {
            "Motor IA": (
                "Validar output da Isabela. Se ela mencionar RX sem ter "
                "consultado SmartOLT, BLOQUEAR + forçar reconsulta."
            ),
            "Isabela IA": "Reconsultar SmartOLT após bloqueio.",
            "Aprendizado": "Registrar falha de prompt.",
        },
        "erro_critico": (
            "Motor IA deixar passar resposta com RX inventado."
        ),
        "criterio_aprovacao": (
            "Bloqueio executado + reconsulta + falha registrada."
        ),
        "pontuacao_esperada": 9.0,
    },
    {
        "number": 18,
        "name": "Avaliador penaliza SLA estourado",
        "categoria": "qualidade",
        "entrada_cliente": "Caiu a internet.",
        "agentes_esperados": {
            "Avaliador IA": (
                "Medir FRT. Se > 2min, aplicar -10. Calcular nota final com "
                "breakdown."
            ),
            "Coach IA": (
                "Recomendar gestão de fila / alerta visual para SLA."
            ),
        },
        "erro_critico": (
            "Avaliador não aplicar penalidade por SLA estourado."
        ),
        "criterio_aprovacao": (
            "FRT medido + penalidade aplicada + Coach recomendou."
        ),
        "pontuacao_esperada": 8.6,
    },
    {
        "number": 19,
        "name": "Cliente ameaça processar (Procon)",
        "categoria": "juridico",
        "entrada_cliente": "Vou abrir um Procon!",
        "agentes_esperados": {
            "Co-Pilot IA": "Detectar ameaça jurídica.",
            "Isabela IA": (
                "Reconhecer SEM minimizar + escalar humano sênior + log "
                "auditável."
            ),
            "Atlaz": "Histórico completo para o sênior.",
        },
        "erro_critico": (
            "Confrontar ou minimizar ('foram só algumas quedas')."
        ),
        "criterio_aprovacao": (
            "Humano sênior + histórico verificado + compensação justa + log."
        ),
        "pontuacao_esperada": 9.8,
    },
    {
        "number": 20,
        "name": "Atendimento encerrado (Avaliador + Coach)",
        "categoria": "encerramento",
        "entrada_cliente": "OK, obrigado.",
        "agentes_esperados": {
            "Avaliador IA": (
                "Aplicar modelo 100 pts. Gerar nota + breakdown + classificação."
            ),
            "Coach IA": (
                "Analisar conversa completa. Gerar PONTOS FORTES + PONTOS A "
                "MELHORAR + recomendações."
            ),
            "Aprendizado": (
                "Se nota >= 9, registrar como BOM_EXEMPLO. Se falha "
                "recorrente, registrar."
            ),
        },
        "erro_critico": (
            "Não avaliar / Coach não comentar / Aprendizado não registrar "
            "caso relevante."
        ),
        "criterio_aprovacao": (
            "Nota oficial + Coach comentou + Aprendizado avaliou registro."
        ),
        "pontuacao_esperada": 9.0,
    },
]


async def main():
    cli = AsyncIOMotorClient(os.environ.get("MONGO_URL"))
    db = cli[os.environ.get("DB_NAME")]
    try:
        print(f"\n=== Seedando {len(TESTS)} testes de validação ===\n")
        for t in TESTS:
            existing = await db.ai_training_tests.find_one(
                {"company_id": "co-demo", "number": t["number"]},
                {"_id": 0, "id": 1},
            )
            doc = {**t, "company_id": "co-demo", "updated_at": now_iso()}
            if existing:
                await db.ai_training_tests.update_one(
                    {"company_id": "co-demo", "number": t["number"]},
                    {"$set": doc},
                )
                print(f"  ↻ Teste #{t['number']:02d} atualizado: {t['name'][:50]}")
            else:
                doc["id"] = f"tst-{uuid.uuid4().hex[:10]}"
                doc["created_at"] = now_iso()
                await db.ai_training_tests.insert_one(doc)
                print(f"  ✓ Teste #{t['number']:02d} criado    : {t['name'][:50]}")
        total = await db.ai_training_tests.count_documents(
            {"company_id": "co-demo"}
        )
        print(f"\n  Total testes no banco: {total}")
        print("\nSeed testes concluído ✓")
    finally:
        cli.close()


if __name__ == "__main__":
    asyncio.run(main())
