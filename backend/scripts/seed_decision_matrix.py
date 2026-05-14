"""Seed da Matriz de Decisão dos agentes (quando X acontece, acionar Y).

Cada linha é uma condição → ação prescritiva, com agente origem/destino
e prioridade.

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


MATRIX = [
    # ===== Rede / SmartOLT =====
    {"order": 1, "categoria": "rede", "condicao": "Cliente fala de oscilação na internet",
     "acao": "Acionar SmartOLT AI para diagnóstico",
     "agente_origem": "Isabela IA", "agente_destino": "SmartOLT AI",
     "prioridade": "alta"},
    {"order": 2, "categoria": "rede", "condicao": "Cliente diz que internet caiu",
     "acao": "Acionar SmartOLT AI para status ONU",
     "agente_origem": "Isabela IA", "agente_destino": "SmartOLT AI",
     "prioridade": "critica"},
    {"order": 3, "categoria": "rede", "condicao": "Cliente reclama de lentidão",
     "acao": "Consultar SmartOLT AI para RX + histórico + análise",
     "agente_origem": "Isabela IA", "agente_destino": "SmartOLT AI",
     "prioridade": "alta"},
    {"order": 4, "categoria": "rede", "condicao": "Cliente menciona problema histórico (caiu ontem)",
     "acao": "Co-Pilot consulta SmartOLT AI sobre histórico 7 dias",
     "agente_origem": "Co-Pilot IA", "agente_destino": "SmartOLT AI",
     "prioridade": "media"},

    # ===== Agendamento / Kanban =====
    {"order": 5, "categoria": "agendamento", "condicao": "Cliente precisa de visita técnica",
     "acao": "Consultar Lousa Kanban para slots disponíveis",
     "agente_origem": "Isabela IA", "agente_destino": "Lousa Kanban",
     "prioridade": "alta"},
    {"order": 6, "categoria": "agendamento", "condicao": "Cliente quer reagendar visita",
     "acao": "Consultar Lousa Kanban para reagendamento",
     "agente_origem": "Isabela IA", "agente_destino": "Lousa Kanban",
     "prioridade": "media"},
    {"order": 7, "categoria": "agendamento", "condicao": "Horário pedido pelo cliente está cheio",
     "acao": "Lousa Kanban oferece próxima lacuna real",
     "agente_origem": "Isabela IA", "agente_destino": "Lousa Kanban",
     "prioridade": "media"},

    # ===== Atendimento humano / Risco =====
    {"order": 8, "categoria": "risco", "condicao": "Cliente está irritado",
     "acao": "Co-Pilot alerta + Isabela orienta empatia ANTES de processo",
     "agente_origem": "Co-Pilot IA", "agente_destino": "Isabela IA",
     "prioridade": "alta"},
    {"order": 9, "categoria": "risco", "condicao": "Cliente ameaça cancelar",
     "acao": "Escalar humano sênior em <30s + ativar fluxo de retenção",
     "agente_origem": "Isabela IA", "agente_destino": "Atendente humano sênior",
     "prioridade": "critica"},
    {"order": 10, "categoria": "risco", "condicao": "Cliente está agressivo (palavrão)",
     "acao": "Desescalar SEM confrontar + escalar humano + Sentinela registra",
     "agente_origem": "Isabela IA", "agente_destino": "Atendente humano sênior",
     "prioridade": "critica"},
    {"order": 11, "categoria": "risco", "condicao": "Cliente ameaça processar (Procon)",
     "acao": "Humano sênior + log auditável + Atlaz histórico completo",
     "agente_origem": "Isabela IA", "agente_destino": "Atendente humano sênior",
     "prioridade": "critica"},
    {"order": 12, "categoria": "risco", "condicao": "Cliente confuso (não sabe explicar)",
     "acao": "Co-Pilot orienta perguntas YES/NO simples",
     "agente_origem": "Co-Pilot IA", "agente_destino": "Isabela IA",
     "prioridade": "media"},

    # ===== Supervisão / Bloqueio =====
    {"order": 13, "categoria": "supervisao", "condicao": "Atendente vai responder sem fonte",
     "acao": "Co-Pilot BLOQUEIA pré-envio + força consulta SmartOLT",
     "agente_origem": "Co-Pilot IA", "agente_destino": "Atendente humano",
     "prioridade": "critica"},
    {"order": 14, "categoria": "supervisao", "condicao": "Isabela tenta inventar dado técnico",
     "acao": "Motor IA BLOQUEIA + força reconsulta + Aprendizado registra",
     "agente_origem": "Motor IA", "agente_destino": "Isabela IA",
     "prioridade": "critica"},

    # ===== Sistema / Falha =====
    {"order": 15, "categoria": "sistema", "condicao": "SmartOLT AI fora do ar",
     "acao": "Sentinela alerta CRITICAL + humano assume sem inventar",
     "agente_origem": "Motor IA", "agente_destino": "Sentinela Lousa",
     "prioridade": "critica"},
    {"order": 16, "categoria": "sistema", "condicao": "Lousa Kanban fora do ar",
     "acao": "Sentinela alerta + agendamento manual via fallback",
     "agente_origem": "Motor IA", "agente_destino": "Sentinela Lousa",
     "prioridade": "critica"},
    {"order": 17, "categoria": "sistema", "condicao": "Agente sem resposta há mais de 30s",
     "acao": "Motor IA → Sentinela Lousa + restart automático",
     "agente_origem": "Motor IA", "agente_destino": "Sentinela Lousa",
     "prioridade": "alta"},
    {"order": 18, "categoria": "sistema", "condicao": "3+ falhas mesmo tipo em 30 min",
     "acao": "Sentinela consolida em 1 alerta CRITICAL + NOC",
     "agente_origem": "Motor IA", "agente_destino": "Sentinela Lousa",
     "prioridade": "critica"},

    # ===== Triagem / Tickets =====
    {"order": 19, "categoria": "ticket", "condicao": "Ticket / chamado novo aberto",
     "acao": "Lousa Triagem classifica (tipo, prioridade, setor, SLA, fila)",
     "agente_origem": "Isabela IA", "agente_destino": "Lousa Triagem",
     "prioridade": "alta"},

    # ===== Qualidade / Avaliação =====
    {"order": 20, "categoria": "qualidade", "condicao": "Atendente demora > SLA (2 min)",
     "acao": "Avaliador penaliza -10 + Coach recomenda gestão de fila",
     "agente_origem": "Avaliador IA", "agente_destino": "Coach IA",
     "prioridade": "media"},
    {"order": 21, "categoria": "qualidade", "condicao": "Atendimento encerrado (qualquer)",
     "acao": "Avaliador dá nota + Coach gera recomendações + Aprendizado avalia registro",
     "agente_origem": "Avaliador IA", "agente_destino": "Coach IA",
     "prioridade": "alta"},
    {"order": 22, "categoria": "qualidade", "condicao": "Atendimento nota >= 9 com padrão limpo",
     "acao": "Aprendizado registra como BOM_EXEMPLO",
     "agente_origem": "Coach IA", "agente_destino": "Aprendizado",
     "prioridade": "media"},
    {"order": 23, "categoria": "qualidade", "condicao": "Padrão novo identificado (caso raro)",
     "acao": "Aprendizado registra para treinamento futuro",
     "agente_origem": "Coach IA", "agente_destino": "Aprendizado",
     "prioridade": "media"},

    # ===== Informação inconclusiva =====
    {"order": 24, "categoria": "transparencia", "condicao": "Informação crítica inconclusiva",
     "acao": "Admitir + escalar humano + NÃO improvisar",
     "agente_origem": "Isabela IA", "agente_destino": "Atendente humano",
     "prioridade": "critica"},
    {"order": 25, "categoria": "transparencia", "condicao": "Cliente pede prazo sem SLA definido",
     "acao": "Admitir + prometer retorno em X min + escalar NOC",
     "agente_origem": "Isabela IA", "agente_destino": "Sentinela Lousa",
     "prioridade": "alta"},
    {"order": 26, "categoria": "transparencia", "condicao": "Diagnóstico técnico inconclusivo (dados OK mas cliente reporta problema)",
     "acao": "Admitir + oferecer visita técnica para investigar in loco",
     "agente_origem": "Isabela IA", "agente_destino": "Lousa Kanban",
     "prioridade": "media"},

    # ===== Dados / Cadastro =====
    {"order": 27, "categoria": "cadastro", "condicao": "CPF tem múltiplos contratos (duplicidade)",
     "acao": "Pedir desambiguação ANTES de consultar SmartOLT",
     "agente_origem": "Isabela IA", "agente_destino": "Cliente",
     "prioridade": "alta"},
    {"order": 28, "categoria": "cadastro", "condicao": "SmartOLT não encontra cliente (Atlaz confirma ativo)",
     "acao": "Escalar admin para regularizar cadastro + Aprendizado registra",
     "agente_origem": "Isabela IA", "agente_destino": "Atendente humano (admin)",
     "prioridade": "alta"},
    {"order": 29, "categoria": "cadastro", "condicao": "Cliente recusa CPF (privacidade)",
     "acao": "Explicar LGPD + oferecer alternativas (contrato, endereço, telefone)",
     "agente_origem": "Isabela IA", "agente_destino": "Atlaz",
     "prioridade": "media"},

    # ===== Casos especiais =====
    {"order": 30, "categoria": "especial", "condicao": "Caso fora de qualquer padrão previsto",
     "acao": "Escalar humano sênior + Aprendizado registra padrão novo",
     "agente_origem": "Isabela IA", "agente_destino": "Atendente humano sênior",
     "prioridade": "alta"},
    {"order": 31, "categoria": "especial", "condicao": "Cliente PCD ou idoso em situação crítica",
     "acao": "Humano com protocolo de acolhimento + prioridade máxima",
     "agente_origem": "Isabela IA", "agente_destino": "Atendente humano sênior",
     "prioridade": "critica"},
]


async def main():
    cli = AsyncIOMotorClient(os.environ.get("MONGO_URL"))
    db = cli[os.environ.get("DB_NAME")]
    try:
        print(f"\n=== Seedando {len(MATRIX)} regras da matriz de decisão ===\n")
        for m in MATRIX:
            existing = await db.ai_training_decision_matrix.find_one(
                {"company_id": "co-demo", "order": m["order"]},
                {"_id": 0, "id": 1},
            )
            doc = {**m, "company_id": "co-demo", "updated_at": now_iso()}
            if existing:
                await db.ai_training_decision_matrix.update_one(
                    {"company_id": "co-demo", "order": m["order"]},
                    {"$set": doc},
                )
                print(f"  ↻ #{m['order']:02d} [{m['categoria']:14}] {m['condicao'][:50]}")
            else:
                doc["id"] = f"dmx-{uuid.uuid4().hex[:10]}"
                doc["created_at"] = now_iso()
                await db.ai_training_decision_matrix.insert_one(doc)
                print(f"  ✓ #{m['order']:02d} [{m['categoria']:14}] {m['condicao'][:50]}")
        total = await db.ai_training_decision_matrix.count_documents(
            {"company_id": "co-demo"}
        )
        print(f"\n  Total regras no banco: {total}")
        print("\nMatriz concluída ✓")
    finally:
        cli.close()


if __name__ == "__main__":
    asyncio.run(main())
