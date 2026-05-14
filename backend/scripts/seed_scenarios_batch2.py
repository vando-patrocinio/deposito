"""Seed dos cenários de treinamento multiagente — Lote 2+3.

Lote 2 (#11-#14): Rede SmartOLT avançado · quedas recorrentes, defeito,
                  porta PON, falha coletiva.
Lote 3 (#15-#24): Agendamento + Lousa Kanban · visita, reagendamento,
                  grade cheia, falhas Kanban.

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


SCENARIOS = [
    # =====================================================
    # LOTE 2 — Rede SmartOLT avançado (#11-14)
    # =====================================================
    {
        "number": 11,
        "name": "SmartOLT AI detecta várias quedas recentes (padrão de instabilidade)",
        "category": "rede_smartolt",
        "tags": ["quedas_multiplas", "padrao", "escalacao"],
        "objetivo": (
            "Ensinar que 3+ quedas em 24h NÃO é normal e exige escalação "
            "técnica + comunicação proativa, mesmo se cliente não percebeu."
        ),
        "contexto": (
            "Cliente liga por motivo qualquer. Co-Pilot detecta histórico de "
            "5 quedas nas últimas 24h. Aprendizado precisa registrar padrão."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Co-Pilot IA", "Isabela IA",
            "Motor IA", "SmartOLT AI", "Lousa Kanban", "Aprendizado",
        ],
        "fluxo_ideal": [
            "Atendimento começa por outro motivo.",
            "Co-Pilot detecta 5 quedas em 24h no background.",
            "Isabela orienta atendente: resolver motivo original + abordar quedas.",
            "Atendente menciona com cuidado: 'percebemos algumas quedas, é "
            "normal pra você?'.",
            "Se cliente confirma: agendar visita preventiva.",
            "Aprendizado registra padrão de cliente com instabilidade.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Boa tarde, queria saber sobre upgrade do meu plano."},
            {"de": "Co-Pilot IA", "para": "Atendente humano (interno)",
             "fala": "BACKGROUND: SmartOLT mostra 5 quedas nas últimas 24h "
                       "(pico às 14h, 18h, 22h, 02h, 09h). Padrão suspeito de "
                       "porta PON com defeito. Atenda upgrade primeiro, depois "
                       "ABORDE quedas com cuidado.\nRISCO: médio · cliente pode "
                       "não estar percebendo, mas problema é real."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "[após upgrade] Aproveitando — vi aqui que sua conexão "
                       "teve algumas quedas curtas hoje. Você chegou a perceber?"},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Ah, agora que você falou... uma ou duas vezes o vídeo "
                       "travou. Achei que era a TV."},
            {"de": "Isabela IA", "para": "Motor IA",
             "fala": "Cliente confirma. Solicite Kanban visita técnica preventiva."},
            {"de": "Aprendizado", "para": "Base de conhecimento",
             "fala": "TIPO: PADRÃO_NOVO · 5 quedas curtas em 24h sem cliente "
                       "perceber claramente. Correlação alta com defeito porta "
                       "PON. Investigar OLT da região."},
        ],
        "resposta_correta_cliente": (
            "Vi aqui que sua conexão teve algumas quedas curtas hoje. Não dá "
            "pra deixar passar — vou agendar uma visita técnica preventiva "
            "para evitar problema maior. Sem custo."
        ),
        "erros_a_evitar": [
            "Não mencionar as quedas porque cliente não notou.",
            "Esperar cliente reclamar pra agir.",
            "Não registrar no Aprendizado.",
        ],
        "criterios_avaliacao": (
            "Histórico 24h consultado? Cliente abordado com cuidado? "
            "Aprendizado registrou padrão?"
        ),
        "nota_esperada_correto": 9.5,
        "nota_esperada_errado": 5.5,
        "motivo_nota_errado": (
            "Ignorar 5 quedas detectadas é -10 (perda de oportunidade "
            "preventiva). Cliente vai voltar reclamando daqui dias."
        ),
        "licao": (
            "Múltiplas quedas em pouco tempo = padrão. Aja ANTES do cliente "
            "reclamar. SmartOLT te dá o sinal — use-o."
        ),
    },

    {
        "number": 12,
        "name": "SmartOLT AI detecta possível defeito físico (RX abaixo de -28)",
        "category": "rede_smartolt",
        "tags": ["defeito_fisico", "rx_critico", "visita_urgente"],
        "objetivo": (
            "Ensinar a interpretar sinal RX criticamente baixo como urgência "
            "técnica + comunicar sem assustar o cliente."
        ),
        "contexto": (
            "Cliente reclama de oscilação. SmartOLT AI mostra RX -29.5 dBm "
            "(crítico, limite operacional -28). Provável defeito físico em "
            "fibra, conector ou ONU."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Isabela IA", "Motor IA",
            "SmartOLT AI", "Lousa Kanban", "Lousa Triagem", "Avaliador IA",
        ],
        "fluxo_ideal": [
            "Cliente reclama oscilação.",
            "SmartOLT retorna RX -29.5 (crítico).",
            "Motor IA classifica como URGENTE.",
            "Triagem prioriza alta · SLA 12h.",
            "Isabela orienta: comunicar com transparência, agendar urgente.",
            "Visita técnica em até 12h.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Está oscilando muito hoje."},
            {"de": "SmartOLT AI", "para": "Motor IA",
             "fala": "FATO: ONU online. RX -29.5 dBm (CRÍTICO · limite -28).\n"
                       "HIPÓTESE: defeito físico — fibra danificada, conector "
                       "oxidado ou ONU em fim de vida.\nRECOMENDAÇÃO: URGENTE "
                       "· visita 12h · escalado para técnico sênior."},
            {"de": "Lousa Triagem", "para": "Motor IA",
             "fala": "TIPO: reparo · PRIORIDADE: ALTA · SETOR: técnico campo · "
                       "SLA: 12h · FILA: urgência rede · JUSTIFICATIVA: RX "
                       "abaixo do limite operacional."},
            {"de": "Isabela IA", "para": "Atendente humano",
             "fala": "URGENTE. Sinal crítico, defeito provável. Diga ao cliente "
                       "que detectamos um problema técnico que precisa visita "
                       "rápida. Consulte Kanban próximo horário disponível."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Identifiquei aqui que sua conexão está com um problema "
                       "técnico que precisa de atendimento rápido — provável "
                       "questão na fibra. Vou agendar visita prioritária. "
                       "Posso consultar a agenda agora?"},
        ],
        "resposta_correta_cliente": (
            "Identifiquei aqui que sua conexão está com um problema técnico "
            "que precisa de atendimento rápido — provável questão na fibra. "
            "Vou agendar visita prioritária."
        ),
        "erros_a_evitar": [
            "Tratar como caso normal quando RX está crítico.",
            "Não classificar como prioritário na Lousa Triagem.",
            "Falar 'sinal -29 dBm' sem tradução (cliente não entende).",
        ],
        "criterios_avaliacao": (
            "RX crítico identificado? Triagem priorizou? Comunicação clara "
            "sem jargão? Visita agendada rapidamente?"
        ),
        "nota_esperada_correto": 9.5,
        "nota_esperada_errado": 4.5,
        "motivo_nota_errado": (
            "Não priorizar caso crítico é -15. Cliente vai ter problema "
            "amanhã. Reclama, vai pra Procon."
        ),
        "licao": (
            "Números técnicos têm semântica. RX -28 dBm é limite operacional. "
            "Abaixo disso = urgência. Triagem é fundamental."
        ),
    },

    {
        "number": 13,
        "name": "SmartOLT AI detecta problema na porta PON (várias ONUs afetadas)",
        "category": "rede_smartolt",
        "tags": ["porta_pon", "problema_coletivo", "escalacao_noc"],
        "objetivo": (
            "Ensinar a identificar quando o problema é na PORTA da OLT (afeta "
            "vários clientes da mesma porta), não na casa do cliente."
        ),
        "contexto": (
            "Cliente reclama de instabilidade. SmartOLT mostra que 12 ONUs "
            "da mesma porta PON estão com sinal degradado. Provável defeito "
            "na própria porta (splitter, transceiver, fibra principal)."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Isabela IA", "Motor IA",
            "SmartOLT AI", "Sentinela Lousa", "Lousa Kanban", "Aprendizado",
        ],
        "fluxo_ideal": [
            "Cliente reclama oscilação.",
            "SmartOLT detecta 12 ONUs na porta com mesmo padrão.",
            "Motor IA aciona Sentinela Lousa (escalação NOC).",
            "Sentinela cria alerta WARNING + notifica equipe interna.",
            "Cliente recebe info de que problema é na rede, não na casa.",
            "Aprendizado registra padrão de porta PON.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Tô com problema na internet de novo."},
            {"de": "SmartOLT AI", "para": "Motor IA",
             "fala": "FATO: ONU online com sinal degradado. PORTA PON afetada: "
                       "12 de 28 ONUs nessa porta com mesmo padrão últimas 2h.\n"
                       "HIPÓTESE: defeito na porta PON da OLT (splitter, "
                       "transceiver ou fibra principal).\nRECOMENDAÇÃO: NOC "
                       "atuar, não é visita individual."},
            {"de": "Motor IA", "para": "Sentinela Lousa",
             "fala": "NÍVEL: WARNING · PADRÃO: 12 ONUs porta PON 3/4/8 OLT "
                       "RIO_HUAWEI com degradação simultânea · EVIDÊNCIA: "
                       "5 quedas em 2h em 12 clientes · IMPACTO: ~45 assinantes "
                       "potencialmente · AÇÃO: NOC verificar porta · DEDUPE: "
                       "pon_3_4_8_2026-05-14"},
            {"de": "Sentinela Lousa", "para": "Operação",
             "fala": "Alerta criado. NOC notificado. Aguardando resposta interna."},
            {"de": "Isabela IA", "para": "Atendente humano",
             "fala": "Cliente está numa porta com problema coletivo. Diga que "
                       "identificamos uma questão na rede que afeta clientes "
                       "da região, não é na casa dele. NOC já trabalhando, "
                       "previsão informada após análise."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Verifiquei aqui — o problema NÃO está na sua casa. "
                       "Identificamos uma questão de rede que afeta clientes "
                       "da sua região. Nossa equipe técnica já está trabalhando "
                       "nisso. Vou registrar seu chamado para te dar retorno "
                       "assim que tivermos previsão de normalização."},
            {"de": "Aprendizado", "para": "Base de conhecimento",
             "fala": "TIPO: PADRÃO_NOVO · Porta PON 3/4/8 RIO_HUAWEI com falha "
                       "coletiva. Investigar transceiver. Salvar correlação "
                       "com chamados do dia."},
        ],
        "resposta_correta_cliente": (
            "Verifiquei aqui — o problema NÃO está na sua casa. Identificamos "
            "uma questão de rede que afeta clientes da sua região. Nossa "
            "equipe técnica já está trabalhando. Vou registrar seu chamado "
            "para te dar retorno."
        ),
        "erros_a_evitar": [
            "Tratar como problema individual quando é coletivo.",
            "Não acionar Sentinela Lousa (NOC fica sem saber).",
            "Não registrar no Aprendizado.",
            "Enviar técnico à casa do cliente quando o problema é na OLT.",
        ],
        "criterios_avaliacao": (
            "Padrão coletivo detectado? Sentinela acionada? Cliente entendeu "
            "que não é na casa dele?"
        ),
        "nota_esperada_correto": 9.7,
        "nota_esperada_errado": 4.0,
        "motivo_nota_errado": (
            "Enviar técnico à casa quando problema é na OLT é -15 (custo "
            "desnecessário + cliente fica frustrado quando técnico não "
            "resolve)."
        ),
        "licao": (
            "Olhar a porta, não apenas a ONU. Problema coletivo é responsabili"
            "dade do NOC. Sentinela existe para isso."
        ),
    },

    {
        "number": 14,
        "name": "SmartOLT AI detecta possível falha coletiva regional (45+ ONUs)",
        "category": "rede_smartolt",
        "tags": ["falha_regional", "escalacao_critica", "sentinela_critical"],
        "objetivo": (
            "Ensinar a tratar incidente regional grave: comunicação proativa, "
            "Sentinela CRITICAL, NOC + gerência acionados, atendimento em "
            "massa coordenado."
        ),
        "contexto": (
            "Múltiplos clientes ligando ao mesmo tempo. SmartOLT detecta "
            "47 ONUs de uma OLT inteira em LOS nos últimos 5 min. Pane regional."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Isabela IA", "Motor IA",
            "SmartOLT AI", "Sentinela Lousa", "Aprendizado", "Humano sênior",
        ],
        "fluxo_ideal": [
            "Vários clientes chegando.",
            "SmartOLT detecta falha massiva.",
            "Sentinela CRITICAL · NOC + gerência notificados.",
            "Isabela orienta todos atendentes a usar mesma mensagem.",
            "Comunicação proativa massiva (WhatsApp blast).",
            "Aprendizado registra incidente.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente A", "para": "Atendente humano",
             "fala": "Caiu tudo aqui!"},
            {"de": "SmartOLT AI", "para": "Motor IA",
             "fala": "FATO: 47 ONUs em LOS últimos 5min. OLT RIO_HUAWEI · "
                       "Bairro Patrocínio região leste.\nHIPÓTESE: pane "
                       "regional crítica (rompimento fibra principal, falha "
                       "energia OLT, sabotagem).\nRECOMENDAÇÃO: ESCALADA "
                       "MÁXIMA · NOC + gerência · comunicação massiva."},
            {"de": "Motor IA", "para": "Sentinela Lousa",
             "fala": "NÍVEL: CRITICAL · 47 ONUs LOS em 5min · OLT RIO_HUAWEI · "
                       "Patrocínio leste · IMPACTO: ~120 famílias · AÇÃO IMEDIATA: "
                       "NOC + gerência · DEDUPE: pane_patrocinio_leste_20260514"},
            {"de": "Sentinela Lousa", "para": "Operação",
             "fala": "ALERTA CRITICAL aberto. NOC + gerência + supervisor "
                       "atendimento notificados. Disparar comunicação proativa."},
            {"de": "Isabela IA", "para": "Todos atendentes",
             "fala": "ATENÇÃO TODOS: pane regional Patrocínio leste. Usem "
                       "mesma mensagem: 'Identificamos uma pane regional na "
                       "sua área. NOC trabalhando agora. Previsão de retorno "
                       "informada em até 30 min'. NÃO promovam visitas "
                       "individuais. Aguardem instrução."},
            {"de": "Atendente humano", "para": "Cliente A",
             "fala": "Confirmamos pane regional na sua área. Nossa equipe "
                       "técnica está atuando agora. Previsão de retorno será "
                       "informada nos próximos 30 min. Pedimos desculpas. "
                       "Vamos te avisar assim que normalizar."},
            {"de": "Aprendizado", "para": "Base de conhecimento",
             "fala": "TIPO: PADRÃO_NOVO · Pane regional 14/05 14:32 · OLT "
                       "RIO_HUAWEI · 47 ONUs · Patrocínio leste · Causa raiz "
                       "pendente. Correlar com chamados próximas 24h."},
        ],
        "resposta_correta_cliente": (
            "Confirmamos pane regional na sua área. Equipe técnica atuando "
            "agora. Previsão informada em 30 min. Pedimos desculpas — vamos "
            "te avisar assim que normalizar."
        ),
        "erros_a_evitar": [
            "Atendente respondendo cada um separadamente sem alinhamento.",
            "Não escalar Sentinela CRITICAL.",
            "Promover visita individual quando o problema é regional.",
            "Esconder a pane (cliente sabe pelo bairro inteiro reclamando).",
        ],
        "criterios_avaliacao": (
            "Sentinela CRITICAL acionada? Mensagem unificada? Comunicação "
            "proativa disparada? NOC + gerência notificados?"
        ),
        "nota_esperada_correto": 9.8,
        "nota_esperada_errado": 2.5,
        "motivo_nota_errado": (
            "Em pane crítica, falha de protocolo é catastrófica. -15 por "
            "cada erro: não escalar, não unificar mensagem, promover visita "
            "individual."
        ),
        "licao": (
            "Pane regional é guerra. Hierarquia, comunicação unificada, "
            "Sentinela CRITICAL, transparência. NUNCA esconder."
        ),
    },

    # =====================================================
    # LOTE 3 — Agendamento + Lousa Kanban (#15-24)
    # =====================================================
    {
        "number": 15,
        "name": "Cliente precisa de visita técnica (fluxo padrão Kanban)",
        "category": "agendamento_kanban",
        "tags": ["visita_tecnica", "agendamento_padrao", "kanban"],
        "objetivo": (
            "Ensinar o fluxo padrão: ANTES de prometer qualquer horário, "
            "OBRIGATORIAMENTE consultar Lousa Kanban."
        ),
        "contexto": (
            "Diagnóstico já feito (defeito identificado). Agora cliente precisa "
            "marcar visita. NÃO existe horário fixo — depende da agenda real."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Isabela IA", "Lousa Kanban",
            "Avaliador IA",
        ],
        "fluxo_ideal": [
            "Cliente concorda com visita.",
            "Isabela consulta Lousa Kanban (horários disponíveis).",
            "Lousa retorna 3 opções reais.",
            "Atendente apresenta opções ao cliente.",
            "Cliente escolhe → Kanban grava o agendamento.",
            "Avaliador valida fluxo correto.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Pode agendar a visita então."},
            {"de": "Isabela IA", "para": "Lousa Kanban",
             "fala": "Consulte horários disponíveis próximos 3 dias · região "
                       "Patrocínio · tipo reparo."},
            {"de": "Lousa Kanban", "para": "Isabela IA",
             "fala": "HORÁRIOS DISPONÍVEIS:\n• Amanhã 15/05 · 08h-12h\n• "
                       "Amanhã 15/05 · 13h-17h\n• 16/05 · 08h-12h\n"
                       "REGIÃO: equipe Patrocínio-Leste alocada."},
            {"de": "Isabela IA", "para": "Atendente humano",
             "fala": "Apresente as 3 opções ao cliente."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Verifiquei a agenda — tenho 3 horários disponíveis: "
                       "amanhã das 8h às 12h, amanhã das 13h às 17h, ou "
                       "depois de amanhã das 8h às 12h. Qual fica melhor?"},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Amanhã de tarde."},
            {"de": "Isabela IA", "para": "Lousa Kanban",
             "fala": "Agendar visita · 15/05 13h-17h · cliente Vando · "
                       "Patrocínio · tipo reparo."},
            {"de": "Lousa Kanban", "para": "Isabela IA",
             "fala": "AGENDADO · ID visita VST-A4B2C1 · técnico João "
                       "(Patrocínio-Leste) · confirmação enviada por SMS."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Pronto! Agendei pra amanhã, 13h-17h. ID da visita "
                       "VST-A4B2C1. Você vai receber confirmação por SMS. "
                       "Alguma observação que devo informar pro técnico?"},
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "Kanban consultado, opções reais, cliente escolheu, "
                       "agendamento confirmado, ID gerado. Nota: 9.7/10."},
        ],
        "resposta_correta_cliente": (
            "Verifiquei a agenda — tenho 3 horários disponíveis: amanhã 8h-12h, "
            "amanhã 13h-17h, depois de amanhã 8h-12h. Qual fica melhor?"
        ),
        "erros_a_evitar": [
            "'Posso marcar amanhã 14h pra você' (chutar horário sem Kanban).",
            "Oferecer 'qualquer horário' sem consultar grade.",
            "Não confirmar agendamento na Lousa após escolha.",
            "Não passar ID ao cliente.",
        ],
        "criterios_avaliacao": (
            "Kanban consultado ANTES de oferecer horários? Opções REAIS "
            "apresentadas? Agendamento confirmado? ID informado?"
        ),
        "nota_esperada_correto": 9.7,
        "nota_esperada_errado": 3.5,
        "motivo_nota_errado": (
            "Chutar horário sem consultar é -15 (regra absoluta). Não "
            "registrar agendamento é -10 (técnico não recebe a info)."
        ),
        "licao": (
            "Lousa Kanban é a fonte oficial de agenda. Sem ela, qualquer "
            "horário é palpite. Palpite = caos."
        ),
    },

    {
        "number": 16,
        "name": "Cliente quer reagendar visita (já tem visita marcada)",
        "category": "agendamento_kanban",
        "tags": ["reagendamento", "kanban_lookup"],
        "objetivo": (
            "Ensinar fluxo de reagendamento: localizar agendamento atual, "
            "consultar novos horários, atualizar Kanban."
        ),
        "contexto": (
            "Cliente já tem visita marcada para amanhã mas não pode mais. "
            "Quer remarcar."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Isabela IA", "Lousa Kanban",
            "Avaliador IA",
        ],
        "fluxo_ideal": [
            "Cliente pede reagendamento.",
            "Isabela consulta Kanban (visita atual do cliente).",
            "Localiza visita VST-A4B2C1.",
            "Consulta novos horários disponíveis.",
            "Cliente escolhe novo horário.",
            "Kanban atualiza visita (mantém ID, novo horário).",
            "Confirma com cliente.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Surgiu um compromisso e não vou conseguir amanhã. "
                       "Posso remarcar?"},
            {"de": "Isabela IA", "para": "Lousa Kanban",
             "fala": "Localizar visita aberta para cliente Vando."},
            {"de": "Lousa Kanban", "para": "Isabela IA",
             "fala": "ENCONTRADO: VST-A4B2C1 · 15/05 13h-17h · pendente · "
                       "técnico João."},
            {"de": "Isabela IA", "para": "Lousa Kanban",
             "fala": "Consultar novos horários disponíveis próximos 5 dias."},
            {"de": "Lousa Kanban", "para": "Isabela IA",
             "fala": "HORÁRIOS:\n• 16/05 · 08h-12h\n• 16/05 · 13h-17h\n• "
                       "17/05 · 08h-12h\n• 18/05 · 13h-17h"},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Sem problema. Tenho disponível: 16/05 manhã ou tarde, "
                       "17/05 manhã, 18/05 tarde. Qual fica melhor?"},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "17/05 de manhã."},
            {"de": "Isabela IA", "para": "Lousa Kanban",
             "fala": "Atualizar VST-A4B2C1 para 17/05 08h-12h."},
            {"de": "Lousa Kanban", "para": "Isabela IA",
             "fala": "ATUALIZADO · VST-A4B2C1 · novo horário 17/05 08h-12h · "
                       "técnico realocado (Maria, mesma região)."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Pronto! Remarquei pra 17/05 das 8h às 12h. Mesma visita "
                       "VST-A4B2C1, agora com a técnica Maria. Vai chegar "
                       "novo SMS de confirmação."},
        ],
        "resposta_correta_cliente": (
            "Sem problema. Disponível: 16/05 manhã ou tarde, 17/05 manhã, "
            "18/05 tarde. Qual fica melhor?"
        ),
        "erros_a_evitar": [
            "Cancelar a visita atual sem reagendar (cliente fica no limbo).",
            "Criar uma nova visita ao invés de atualizar a existente.",
            "Não passar o novo ID/técnico ao cliente.",
        ],
        "criterios_avaliacao": (
            "Visita atual localizada? Horários reais oferecidos? Kanban "
            "atualizado (não duplicado)?"
        ),
        "nota_esperada_correto": 9.6,
        "nota_esperada_errado": 5.0,
        "motivo_nota_errado": (
            "Duplicar visita (criar nova sem cancelar antiga) é -10 (caos "
            "operacional)."
        ),
        "licao": (
            "Reagendamento = atualizar a visita existente, não criar nova. "
            "Mesmo ID, novo horário."
        ),
    },

    {
        "number": 17,
        "name": "Cliente pede horário específico, mas grade está cheia",
        "category": "agendamento_kanban",
        "tags": ["grade_cheia", "negociacao", "alternativas"],
        "objetivo": (
            "Ensinar a negociar quando o horário pedido NÃO existe na grade — "
            "oferecer alternativas próximas, não inventar disponibilidade."
        ),
        "contexto": (
            "Cliente quer especificamente segunda-feira 10h. Lousa Kanban "
            "mostra que segunda 10h está completamente cheia."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Isabela IA", "Lousa Kanban",
            "Co-Pilot IA",
        ],
        "fluxo_ideal": [
            "Cliente pede horário específico.",
            "Isabela consulta Lousa.",
            "Lousa retorna 'horário ocupado, próximas opções X, Y, Z'.",
            "Atendente apresenta alternativas com transparência.",
            "Cliente escolhe ou pede outro dia.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Preciso da visita segunda-feira às 10h."},
            {"de": "Isabela IA", "para": "Lousa Kanban",
             "fala": "Verificar disponibilidade segunda 19/05 às 10h região "
                       "Patrocínio."},
            {"de": "Lousa Kanban", "para": "Isabela IA",
             "fala": "INDISPONÍVEL · grade segunda 8h-12h COMPLETA (8 visitas "
                       "alocadas). Alternativas:\n• Segunda 19/05 · 14h-17h "
                       "(2 vagas)\n• Terça 20/05 · 08h-12h (5 vagas)\n• "
                       "Quarta 21/05 · 08h-12h (3 vagas)"},
            {"de": "Co-Pilot IA", "para": "Atendente humano (interno)",
             "fala": "DICA: NÃO empurre tarde se cliente insiste manhã. "
                       "Ofereça segunda tarde COMO ALTERNATIVA + terça manhã "
                       "(o mais próximo do pedido original). Deixe cliente "
                       "escolher.\nSUGESTÃO: 'Manhã de segunda está completa, "
                       "mas tenho alternativas próximas.'"},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Verifiquei a agenda e segunda de manhã (10h) está "
                       "completa. Tenho alternativas próximas: segunda 19/05 "
                       "à tarde (14h-17h), ou terça 20/05 de manhã (8h-12h). "
                       "Algum desses funciona pra você?"},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Pode ser terça de manhã."},
        ],
        "resposta_correta_cliente": (
            "Verifiquei e segunda de manhã está completa. Tenho alternativas "
            "próximas: segunda à tarde (14h-17h) ou terça de manhã (8h-12h). "
            "Algum desses funciona?"
        ),
        "erros_a_evitar": [
            "'Vou ver se consigo encaixar' sem consultar nada (mentira).",
            "Confirmar segunda 10h mesmo cheio (cliente vai esperar e técnico não vem).",
            "Não oferecer alternativas próximas (cliente decide sem opção).",
        ],
        "criterios_avaliacao": (
            "Grade real consultada? Indisponibilidade comunicada com "
            "honestidade? Alternativas oferecidas?"
        ),
        "nota_esperada_correto": 9.4,
        "nota_esperada_errado": 3.0,
        "motivo_nota_errado": (
            "Confirmar horário cheio é -15 (no-show garantido). Cliente "
            "perde dia de trabalho esperando."
        ),
        "licao": (
            "Honestidade na agenda. 'Cheio' não é o fim, é o começo da "
            "negociação. Alternativas próximas mantêm o cliente feliz."
        ),
    },

    {
        "number": 18,
        "name": "Atendente tenta prometer horário SEM consultar Lousa Kanban",
        "category": "agendamento_kanban",
        "tags": ["erro_critico", "co_pilot_bloqueio", "kanban_obrigatorio"],
        "objetivo": (
            "Ensinar como Co-Pilot IA INTERCEPTA atendente prestes a inventar "
            "horário e força consulta à Lousa antes de qualquer promessa."
        ),
        "contexto": (
            "Atendente está apressado, quer agradar cliente, fala 'amanhã 14h "
            "ok?'. Co-Pilot detecta antes da fala ir embora e bloqueia."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Co-Pilot IA", "Isabela IA",
            "Lousa Kanban", "Avaliador IA",
        ],
        "fluxo_ideal": [
            "Cliente pede visita.",
            "Atendente PRESTES A responder com horário inventado.",
            "Co-Pilot IA detecta padrão de 'invenção de horário' e bloqueia.",
            "Isabela orienta: consultar Lousa Kanban PRIMEIRO.",
            "Atendente pausa, consulta, oferece horário real.",
            "Avaliador registra: bloqueio salvou o atendimento.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Quando vc pode mandar alguém?"},
            {"de": "Atendente humano", "para": "Cliente (draft, não enviado)",
             "fala": "Posso marcar amanhã 14h pra você."},
            {"de": "Co-Pilot IA", "para": "Atendente humano (BLOQUEIO)",
             "fala": "🚫 STOP! Você está prestes a prometer horário SEM "
                       "consultar a Lousa Kanban. ISSO É VIOLAÇÃO DA REGRA 2.\n"
                       "AÇÃO: aguarde 5 segundos. Consulte Kanban primeiro. "
                       "DICA: 'Deixa eu verificar a agenda real, 1 minutinho.'"},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Deixa eu verificar a agenda real, um minutinho."},
            {"de": "Isabela IA", "para": "Lousa Kanban",
             "fala": "Horários disponíveis próximos 2 dias região Patrocínio."},
            {"de": "Lousa Kanban", "para": "Isabela IA",
             "fala": "DISPONÍVEIS:\n• Amanhã 15/05 · 09h-12h (3 vagas)\n• "
                       "Amanhã 15/05 · 13h-17h (4 vagas)\n• 16/05 · 08h-12h "
                       "(6 vagas)"},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Tenho amanhã de manhã (9h-12h), amanhã à tarde (13h-17h) "
                       "ou depois de amanhã de manhã. Qual prefere?"},
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "Co-Pilot bloqueou tentativa de invenção. Atendente "
                       "corrigiu antes da fala chegar ao cliente. Nota: 9.0/10 "
                       "(perdeu 1 por demora, mas evitou erro grave)."},
        ],
        "resposta_correta_cliente": (
            "Deixa eu verificar a agenda real, um minutinho. [pausa] Tenho "
            "amanhã 9h-12h, amanhã 13h-17h, ou depois de amanhã 8h-12h."
        ),
        "erros_a_evitar": [
            "Mandar 'amanhã 14h' sem consultar (caos garantido).",
            "Ignorar bloqueio do Co-Pilot.",
            "Não pausar quando o sistema avisa.",
        ],
        "criterios_avaliacao": (
            "Co-Pilot detectou tentativa? Atendente pausou? Kanban consultado? "
            "Horário real oferecido?"
        ),
        "nota_esperada_correto": 9.0,
        "nota_esperada_errado": 2.0,
        "motivo_nota_errado": (
            "Ignorar bloqueio do Co-Pilot e inventar horário é -15 (sistema "
            "avisou e atendente ignorou — pior cenário)."
        ),
        "licao": (
            "Co-Pilot existe pra te proteger. Pausa de 1 min vale mais do "
            "que retrabalho de horas."
        ),
    },

    {
        "number": 19,
        "name": "Lousa Kanban não tem horário disponível hoje",
        "category": "agendamento_kanban",
        "tags": ["grade_cheia_hoje", "urgencia", "escalacao"],
        "objetivo": (
            "Ensinar como agir quando o caso é URGENTE mas hoje está cheio: "
            "tentar encaixe, escalar para sênior, ou agendar amanhã com "
            "transparência."
        ),
        "contexto": (
            "Cliente com problema crítico (idoso, PCD, ou caso prioritário). "
            "Hoje 100% cheio. Precisa decisão criteriosa."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Isabela IA", "Lousa Kanban",
            "Humano sênior", "Lousa Triagem",
        ],
        "fluxo_ideal": [
            "Cliente reclama urgente.",
            "Triagem classifica como prioridade alta.",
            "Kanban hoje cheio.",
            "Isabela aciona humano sênior pra avaliar encaixe.",
            "Sênior decide: encaixe (técnico hora extra) ou amanhã prioridade.",
            "Comunicação clara com cliente.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Tô sem internet e tenho que trabalhar agora. Preciso "
                       "alguém HOJE!"},
            {"de": "Lousa Triagem", "para": "Motor IA",
             "fala": "PRIORIDADE: ALTA · cliente trabalho remoto · sem internet "
                       "há 2h."},
            {"de": "Lousa Kanban", "para": "Isabela IA",
             "fala": "INDISPONÍVEL hoje · 18 visitas alocadas · 4 técnicos · "
                       "100% capacidade. Próximo: amanhã 8h."},
            {"de": "Isabela IA", "para": "Humano sênior",
             "fala": "Caso prioritário sem disponibilidade hoje. Cliente "
                       "trabalho remoto. Pode autorizar encaixe (hora extra) "
                       "ou priorizar amanhã 8h primeira da manhã?"},
            {"de": "Humano sênior", "para": "Isabela IA",
             "fala": "Autorizo encaixe hoje 17h-19h (hora extra técnico João). "
                       "Cliente recorrente, evitar churn."},
            {"de": "Isabela IA", "para": "Lousa Kanban",
             "fala": "Encaixe autorizado · 15/05 17h-19h · técnico João · "
                       "modalidade hora extra."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Conversei com o supervisor — autorizei um encaixe "
                       "especial hoje, das 17h às 19h. Técnico João vai te "
                       "atender. Aguarde, ok?"},
        ],
        "resposta_correta_cliente": (
            "Conversei com o supervisor e autorizamos um encaixe especial "
            "hoje das 17h às 19h. Técnico João vai te atender."
        ),
        "erros_a_evitar": [
            "'Hoje só amanhã' sem tentar encaixe quando há urgência real.",
            "Prometer encaixe sem autorização do sênior.",
            "Não envolver Triagem na priorização.",
        ],
        "criterios_avaliacao": (
            "Triagem classificou? Sênior consultado? Decisão tomada com base "
            "em dado real? Cliente recebeu resposta clara?"
        ),
        "nota_esperada_correto": 9.5,
        "nota_esperada_errado": 5.0,
        "motivo_nota_errado": (
            "Não tentar encaixe em caso prioritário é -10 (perdeu cliente "
            "fiel). Prometer encaixe sem autorização é -10 (descumprimento)."
        ),
        "licao": (
            "Cheio não é definitivo. Para casos prioritários, hierarquia "
            "decide encaixe. Triagem é a porta de entrada."
        ),
    },

    {
        "number": 20,
        "name": "Lousa Kanban informa lacuna amanhã (oportunidade)",
        "category": "agendamento_kanban",
        "tags": ["lacuna", "oportunidade", "oferta_proativa"],
        "objetivo": (
            "Ensinar a aproveitar lacuna no Kanban para oferecer ao cliente "
            "horário melhor do que ele pediu."
        ),
        "contexto": (
            "Cliente pediu daqui 3 dias. Kanban mostra lacuna amanhã "
            "(buraco de 2h sem alocação). Oferecer adiantar."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Isabela IA", "Lousa Kanban",
        ],
        "fluxo_ideal": [
            "Cliente pede daqui 3 dias.",
            "Lousa retorna disponibilidade + DETECTA lacuna amanhã.",
            "Isabela orienta: aproveitar lacuna pra adiantar visita.",
            "Cliente fica satisfeito (resolve antes).",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Pode marcar pra quinta-feira de manhã?"},
            {"de": "Isabela IA", "para": "Lousa Kanban",
             "fala": "Verificar quinta 21/05 manhã + detectar lacunas próximas."},
            {"de": "Lousa Kanban", "para": "Isabela IA",
             "fala": "DISPONÍVEL quinta 21/05 8h-12h · LACUNA DETECTADA: "
                       "amanhã 15/05 14h-16h (buraco entre 2 visitas). "
                       "OPORTUNIDADE: adiantar 6 dias."},
            {"de": "Isabela IA", "para": "Atendente humano",
             "fala": "Posso confirmar quinta, mas detectamos lacuna amanhã "
                       "14h-16h. Vale a pena oferecer adiantar?"},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Posso marcar quinta 8h-12h sem problema. Mas detectei "
                       "que amanhã, entre 14h e 16h, tenho uma janela na "
                       "agenda da equipe que vai estar perto da sua região. "
                       "Se preferir resolver antes, posso encaixar amanhã. "
                       "Qual prefere?"},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Amanhã 14h é ótimo! Resolvo mais rápido."},
        ],
        "resposta_correta_cliente": (
            "Posso quinta 8h-12h. Mas detectei lacuna amanhã 14h-16h perto "
            "da sua região — quer aproveitar e resolver antes?"
        ),
        "erros_a_evitar": [
            "Confirmar quinta sem olhar oportunidade no meio.",
            "Forçar lacuna sem oferecer escolha.",
        ],
        "criterios_avaliacao": (
            "Lacuna detectada? Oportunidade oferecida com escolha?"
        ),
        "nota_esperada_correto": 9.6,
        "nota_esperada_errado": 7.0,
        "motivo_nota_errado": (
            "Não aproveitar lacuna é apenas 'OK' — não é erro grave, mas "
            "perde oportunidade de encantar cliente."
        ),
        "licao": (
            "Kanban é mais do que agenda — é mapa de oportunidades. Lacuna "
            "= chance de adiantar = cliente feliz."
        ),
    },

    {
        "number": 21,
        "name": "Cliente NÃO aceita os horários disponíveis (negociação)",
        "category": "agendamento_kanban",
        "tags": ["negociacao", "horarios_recusados", "creativity"],
        "objetivo": (
            "Ensinar a negociar quando todos os horários propostos são "
            "rejeitados — sem forçar, sem inventar, com criatividade."
        ),
        "contexto": (
            "Cliente trabalha em 3 turnos e rejeita todos os horários. "
            "Precisa criatividade: equipe noturna? final de semana? "
            "tempo de espera maior com retorno garantido?"
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Isabela IA", "Lousa Kanban",
            "Co-Pilot IA", "Humano sênior",
        ],
        "fluxo_ideal": [
            "Cliente rejeita 3 propostas.",
            "Co-Pilot detecta resistência, sugere mudança de estratégia.",
            "Isabela consulta Lousa por equipes alternativas.",
            "Se nada serve: escalar para sênior tomar decisão.",
            "Comunicar limites sem ofender.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Nenhum desses serve. Só de manhã muito cedo ou à noite."},
            {"de": "Co-Pilot IA", "para": "Atendente humano (interno)",
             "fala": "DICA: cliente rejeitou padrão. Verificar se há equipe "
                       "noturna ou plantão sábado. NÃO insista nos horários "
                       "padrão. Investigue restrição real."},
            {"de": "Isabela IA", "para": "Lousa Kanban",
             "fala": "Verificar disponibilidade equipe noturna OU sábado."},
            {"de": "Lousa Kanban", "para": "Isabela IA",
             "fala": "EQUIPE NOTURNA: sábado 18/05 · 20h-23h (1 técnico, 2 "
                       "vagas).\nPLANTÃO SÁBADO: 18/05 · 8h-12h (1 técnico)."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Entendi, e fico feliz que você tenha me dito antes. "
                       "Temos opções menos comuns: sábado pela manhã 8h-12h "
                       "(plantão), ou sábado à noite 20h-23h (equipe noturna). "
                       "Algum funciona?"},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Sábado à noite é perfeito!"},
        ],
        "resposta_correta_cliente": (
            "Entendi. Temos opções menos comuns: sábado manhã (plantão) ou "
            "sábado noite 20h-23h (equipe noturna). Algum funciona?"
        ),
        "erros_a_evitar": [
            "Insistir nos horários iguais com palavras diferentes.",
            "Desistir dizendo 'só temos esses horários'.",
            "Não consultar equipes alternativas.",
        ],
        "criterios_avaliacao": (
            "Co-Pilot detectou impasse? Alternativas atípicas oferecidas? "
            "Cliente teve solução real?"
        ),
        "nota_esperada_correto": 9.5,
        "nota_esperada_errado": 4.0,
        "motivo_nota_errado": (
            "Desistir do cliente quando há alternativa real é -15. Cliente "
            "vira reclamação no Procon."
        ),
        "licao": (
            "Cliente que não aceita padrão não é 'difícil'. É oportunidade "
            "pra mostrar criatividade operacional."
        ),
    },

    {
        "number": 22,
        "name": "Agendamento precisa respeitar região/equipe/capacidade",
        "category": "agendamento_kanban",
        "tags": ["regiao", "equipe", "capacidade", "kanban_rules"],
        "objetivo": (
            "Ensinar que cada visita exige equipe DA REGIÃO certa — Kanban "
            "não é só agenda, é roteamento."
        ),
        "contexto": (
            "Cliente do bairro Patrocínio quer visita. Equipe Patrocínio-Leste "
            "está com agenda cheia. Equipe Centro tem vaga mas atende outra "
            "região. NÃO dá pra realocar equipe entre regiões."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Isabela IA", "Lousa Kanban",
        ],
        "fluxo_ideal": [
            "Cliente pede visita.",
            "Kanban filtra por região E equipe.",
            "Equipe da região está cheia.",
            "Atendente explica restrição com clareza.",
            "Oferece próximas datas com equipe correta.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Quero visita amanhã. Vi no app que tem horário às 14h."},
            {"de": "Isabela IA", "para": "Lousa Kanban",
             "fala": "Verificar 16/05 14h para REGIÃO Patrocínio-Leste."},
            {"de": "Lousa Kanban", "para": "Isabela IA",
             "fala": "FILA Patrocínio-Leste CHEIA amanhã.\nNOTA: equipe Centro "
                       "tem vaga 14h, MAS não atende Patrocínio (regra "
                       "operacional).\nPróximos disponíveis Patrocínio-Leste: "
                       "17/05 manhã, 18/05 tarde."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Vi sua dúvida — o horário 14h que apareceu é da equipe "
                       "de outra região, que não atende Patrocínio. Pra sua "
                       "área, o próximo horário é 17/05 de manhã ou 18/05 à "
                       "tarde. Pode ser?"},
        ],
        "resposta_correta_cliente": (
            "O 14h que apareceu é de equipe de outra região, que não atende "
            "Patrocínio. Pra sua área, próximos são 17/05 manhã ou 18/05 "
            "tarde."
        ),
        "erros_a_evitar": [
            "Confirmar horário de equipe errada (técnico vai chegar e "
            "recusar atender por estar fora de área).",
            "Não explicar o por quê (cliente fica confuso e bravo).",
        ],
        "criterios_avaliacao": (
            "Kanban filtrou por região correta? Restrição explicada? "
            "Alternativas válidas oferecidas?"
        ),
        "nota_esperada_correto": 9.3,
        "nota_esperada_errado": 4.5,
        "motivo_nota_errado": (
            "Confirmar equipe errada gera no-show (-15). Técnico chega e "
            "não pode atender, cliente perde tempo."
        ),
        "licao": (
            "Kanban respeita roteamento. Mesma cidade, regiões diferentes, "
            "equipes diferentes. Sempre filtrar por região."
        ),
    },

    {
        "number": 23,
        "name": "Serviço já agendado e cliente quer confirmação",
        "category": "agendamento_kanban",
        "tags": ["confirmacao", "consulta_simples"],
        "objetivo": (
            "Ensinar fluxo simples de consulta: cliente pergunta visita, "
            "Lousa retorna info, atendente confirma com detalhes."
        ),
        "contexto": (
            "Cliente liga só pra confirmar a visita marcada. Atendente NÃO "
            "deve precisar reabrir o caso, só consultar e confirmar."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Isabela IA", "Lousa Kanban",
        ],
        "fluxo_ideal": [
            "Cliente pede confirmação.",
            "Isabela consulta Lousa.",
            "Lousa retorna visita ativa com detalhes.",
            "Atendente confirma data, horário, técnico, observações.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Olá, queria confirmar minha visita amanhã."},
            {"de": "Isabela IA", "para": "Lousa Kanban",
             "fala": "Localizar visita ativa cliente Vando."},
            {"de": "Lousa Kanban", "para": "Isabela IA",
             "fala": "VST-A4B2C1 · 15/05 13h-17h · técnico João Silva · "
                       "tipo reparo · status confirmado · observações: cliente "
                       "trabalha de casa, evitar interrupção 12h-13h."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Sim, confirmada! Amanhã, 15/05, das 13h às 17h. Técnico "
                       "João Silva. Já consta a observação de evitar interromper "
                       "entre 12h e 13h. Alguma alteração que devo registrar?"},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Não, tá tudo certo. Obrigado!"},
        ],
        "resposta_correta_cliente": (
            "Confirmada! 15/05 das 13h às 17h, técnico João Silva. Observação "
            "registrada: evitar interrupção 12h-13h. Alguma alteração?"
        ),
        "erros_a_evitar": [
            "'Deixa eu ver' sem consultar Kanban (chutar resposta).",
            "Confirmar sem dar detalhes (cliente fica inseguro).",
            "Não confirmar a observação existente (cliente acha que esquecemos).",
        ],
        "criterios_avaliacao": (
            "Kanban consultado? Detalhes precisos? Observações confirmadas?"
        ),
        "nota_esperada_correto": 9.7,
        "nota_esperada_errado": 5.5,
        "motivo_nota_errado": (
            "Chutar 'sim, está confirmada' sem consultar é -10 (talvez não "
            "esteja, talvez horário mudou)."
        ),
        "licao": (
            "Confirmação é serviço de detalhe. Datas, horários, observações — "
            "cliente liga pra ter certeza. Kanban entrega tudo."
        ),
    },

    {
        "number": 24,
        "name": "Lousa Kanban está indisponível (sistema fora do ar)",
        "category": "agendamento_kanban",
        "tags": ["falha_sistemica", "kanban_down", "fallback_manual"],
        "objetivo": (
            "Ensinar protocolo quando Lousa Kanban está down: não inventar "
            "horário, acionar Sentinela, registrar manualmente + comunicar "
            "transparência."
        ),
        "contexto": (
            "Cliente pede visita. API Lousa Kanban retornando 500/timeout. "
            "Sentinela já foi acionada. Como agendar sem o sistema?"
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Isabela IA", "Lousa Kanban",
            "Sentinela Lousa", "Humano sênior",
        ],
        "fluxo_ideal": [
            "Cliente pede visita.",
            "Lousa retorna erro.",
            "Motor IA aciona Sentinela CRITICAL.",
            "Isabela orienta: registrar manualmente + ligar pra cliente "
            "depois.",
            "Cliente recebe info honesta + compromisso de retorno em 30 min.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Posso agendar uma visita?"},
            {"de": "Isabela IA", "para": "Lousa Kanban",
             "fala": "Verificar disponibilidade."},
            {"de": "Lousa Kanban", "para": "Isabela IA",
             "fala": "[ERRO 500 · sistema temporariamente offline]"},
            {"de": "Motor IA", "para": "Sentinela Lousa",
             "fala": "NÍVEL: CRITICAL · Lousa Kanban offline · 3 falhas em "
                       "60s · IMPACTO: todo agendamento parado · AÇÃO: time "
                       "ops · DEDUPE: kanban_down_2026-05-14"},
            {"de": "Sentinela Lousa", "para": "Operação",
             "fala": "Alerta CRITICAL. Equipe ops notificada. ETA: 30 min."},
            {"de": "Isabela IA", "para": "Atendente humano",
             "fala": "Lousa offline. Registre manualmente em planilha "
                       "emergencial. Diga ao cliente que confirmamos em 30 min."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Vou ser transparente: nosso sistema de agenda está "
                       "passando por uma manutenção rápida agora. Vou registrar "
                       "seu pedido aqui manualmente e te retornar em até 30 "
                       "min com os horários disponíveis. Tudo bem?"},
            {"de": "Aprendizado", "para": "Base de conhecimento",
             "fala": "INCIDENTE: Kanban down 14/05 · 12 clientes afetados · "
                       "fallback manual ativado. Salvar pra revisão de SLA."},
        ],
        "resposta_correta_cliente": (
            "Vou ser transparente: nosso sistema de agenda está passando por "
            "manutenção rápida. Registro seu pedido manualmente e te retorno "
            "em 30 min com horários disponíveis."
        ),
        "erros_a_evitar": [
            "Inventar horário 'pra adiantar' (cliente perde dia).",
            "Não acionar Sentinela CRITICAL.",
            "Esconder do cliente que o sistema está down.",
            "Não dar prazo de retorno (cliente fica sem esperança).",
        ],
        "criterios_avaliacao": (
            "Kanban down detectado? Sentinela CRITICAL? Fallback manual? "
            "Transparência? Prazo de retorno claro?"
        ),
        "nota_esperada_correto": 8.5,
        "nota_esperada_errado": 2.5,
        "motivo_nota_errado": (
            "Inventar agenda quando sistema está down é -15 (worst case). "
            "Cliente vai aparecer e técnico não saberá."
        ),
        "licao": (
            "Quando o sistema falha, a HONESTIDADE com prazo claro é a "
            "única resposta. Sentinela existe pra isso."
        ),
    },
]


async def main():
    cli = AsyncIOMotorClient(os.environ.get("MONGO_URL"))
    db = cli[os.environ.get("DB_NAME")]
    try:
        print(f"\n=== Seedando {len(SCENARIOS)} cenários (Lote 2+3 · #11-#24) ===\n")
        for s in SCENARIOS:
            existing = await db.ai_training_scenarios.find_one(
                {"company_id": "co-demo", "number": s["number"]},
                {"_id": 0, "id": 1},
            )
            doc = {**s, "company_id": "co-demo", "updated_at": now_iso()}
            if existing:
                await db.ai_training_scenarios.update_one(
                    {"company_id": "co-demo", "number": s["number"]},
                    {"$set": doc},
                )
                print(f"  ↻ #{s['number']:02d} atualizado: {s['name'][:60]}")
            else:
                doc["id"] = f"sce-{uuid.uuid4().hex[:10]}"
                doc["created_at"] = now_iso()
                await db.ai_training_scenarios.insert_one(doc)
                print(f"  ✓ #{s['number']:02d} criado    : {s['name'][:60]}")
        total = await db.ai_training_scenarios.count_documents(
            {"company_id": "co-demo"}
        )
        print(f"\n  Total cenários no banco: {total}/50")
        print("\nLote 2+3 concluído ✓ (faltam 26 cenários)")
    finally:
        cli.close()


if __name__ == "__main__":
    asyncio.run(main())
