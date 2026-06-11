"""Seed dos cenários de treinamento multiagente — Lote 1 (Rede + SmartOLT AI · #1-#10).

Cada cenário segue o formato OBRIGATÓRIO do documento:
- objetivo / contexto / agentes / fluxo_ideal / simulacao_conversa
- resposta_correta_cliente / erros_a_evitar / criterios_avaliacao
- nota_esperada_correto / nota_esperada_errado / licao

Idempotente: rerun não duplica (upsert por number).

Uso:
    cd /app/backend && python3 scripts/seed_scenarios_batch1.py
"""

NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "operacoes",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

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


# ============================================================
# 10 CENÁRIOS — Rede e SmartOLT AI (#1 a #10)
# ============================================================
SCENARIOS = [
    # ---------------------------------------------------------
    {
        "number": 1,
        "name": "Cliente relata internet oscilando e precisa de diagnóstico real",
        "category": "rede_smartolt",
        "tags": ["oscilacao", "diagnostico", "fluxo_ideal", "exemplo_modelo"],
        "objetivo": (
            "Ensinar que qualquer problema de rede deve passar pela "
            "SmartOLT AI ANTES da resposta ao cliente."
        ),
        "contexto": (
            "Cliente está incomodado porque a internet está oscilando. O "
            "atendente humano não sabe se é problema de sinal, ONU, fibra ou "
            "rede. A Co-Pilot IA está escutando. A Isabela coordena. O Motor IA "
            "monitora. A SmartOLT AI responde diagnóstico de rede."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Co-Pilot IA", "Isabela IA",
            "Motor IA", "SmartOLT AI", "Avaliador IA", "Coach IA", "Aprendizado",
        ],
        "fluxo_ideal": [
            "Cliente relata oscilação.",
            "Co-Pilot IA detecta risco de insatisfação e orienta consulta técnica.",
            "Atendente pergunta à Isabela.",
            "Isabela aciona o Motor IA.",
            "Motor IA valida que o caso é de rede.",
            "Motor IA consulta SmartOLT AI.",
            "SmartOLT AI retorna status e sinal.",
            "Motor IA valida a resposta.",
            "Isabela orienta o atendente.",
            "Atendente responde ao cliente com dados confirmados.",
            "Avaliador IA registra que o fluxo foi correto.",
            "Coach IA recomenda melhoria (se houver).",
            "Aprendizado registra bom exemplo.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Minha internet está oscilando toda hora. Está impossível usar."},
            {"de": "Co-Pilot IA", "para": "Atendente humano (interno)",
             "fala": "DICA INTERNA: cliente irritado, relato de oscilação. "
                       "NÃO afirme que está normal antes de consultar a SmartOLT AI. "
                       "Sugira resposta empática e peça validação técnica.\n"
                       "RISCO: médio · MOTIVO: relato de instabilidade recorrente.\n"
                       "SUGESTÃO DE FALA: 'Entendi, vou verificar agora pra você.'"},
            {"de": "Atendente humano", "para": "Isabela IA",
             "fala": "Isabela, o cliente relata internet oscilando. Pode "
                       "verificar qual agente devo acionar?"},
            {"de": "Isabela IA", "para": "Motor IA",
             "fala": "Motor IA, temos uma demanda de rede. O cliente relata "
                       "oscilação. Valide o fluxo e consulte a fonte correta."},
            {"de": "Motor IA", "para": "SmartOLT AI",
             "fala": "SmartOLT AI, consulte este cliente e verifique status "
                       "da ONU, RX, TX, quedas recentes, degradação de sinal e "
                       "eventos de rede."},
            {"de": "SmartOLT AI", "para": "Motor IA",
             "fala": "FATO CONFIRMADO: ONU online. RX -28.9 dBm. TX 2.1 dBm. "
                       "3 quedas nas últimas 24h.\nHIPÓTESE TÉCNICA: sinal "
                       "degradado com instabilidade.\nRECOMENDAÇÃO: abrir "
                       "chamado e agendar visita técnica.\nLIMITAÇÕES: "
                       "nenhuma — dado fresco do banco."},
            {"de": "Motor IA", "para": "Isabela IA",
             "fala": "Consulta concluída. Dados confirmados. Recomendo orientar "
                       "o atendente a informar o problema de forma transparente "
                       "e seguir para abertura de chamado + agendamento via "
                       "Lousa Kanban."},
            {"de": "Isabela IA", "para": "Atendente humano",
             "fala": "Informe ao cliente que foi identificada degradação de "
                       "sinal e quedas recentes. NÃO diga que está tudo normal. "
                       "Depois, consulte a Lousa Kanban para agendar visita."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Obrigado por avisar. Verificamos sua conexão e "
                       "identificamos que o equipamento está online, porém o "
                       "sinal apresenta degradação e houve quedas recentes. "
                       "Para resolver corretamente, vamos abrir um chamado e "
                       "verificar um horário disponível para visita técnica."},
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "Fluxo correto. SmartOLT AI consultada antes do "
                       "diagnóstico. Linguagem adequada e empática. "
                       "Nota preliminar: 9.5/10."},
            {"de": "Coach IA", "para": "Atendente humano",
             "fala": "Boa condução. Melhorar apenas explicando ao cliente que "
                       "a visita será confirmada após consulta da agenda."},
            {"de": "Aprendizado", "para": "Base de conhecimento",
             "fala": "TIPO: BOM_EXEMPLO · Atendimento de oscilação com consulta "
                       "técnica antes da resposta e orientação correta para "
                       "agendamento. Salvar como referência de fluxo padrão."},
        ],
        "resposta_correta_cliente": (
            "Verificamos sua conexão e identificamos que seu equipamento está "
            "online, mas o sinal apresenta degradação e houve quedas recentes. "
            "Vamos seguir com a abertura de chamado e consultar a agenda para "
            "marcar uma visita técnica."
        ),
        "erros_a_evitar": [
            "Dizer 'está tudo normal' sem consultar a SmartOLT AI.",
            "Informar valor de sinal inventado.",
            "Prometer visita sem consultar Lousa Kanban.",
            "Ignorar a irritação do cliente.",
            "Deixar de registrar o caso no Aprendizado.",
        ],
        "criterios_avaliacao": (
            "SmartOLT AI foi consultada? · A resposta foi empática? · "
            "O atendente usou dado confirmado? · Houve orientação correta para "
            "agendamento? · O cliente ficou sem resposta por muito tempo?"
        ),
        "nota_esperada_correto": 9.5,
        "nota_esperada_errado": 4.0,
        "motivo_nota_errado": (
            "Diagnóstico sem consulta técnica é a falha mais grave (-15pts por "
            "invenção). Se atendente disse 'parece normal' sem verificar, "
            "automático -15. Se prometeu visita sem Kanban, -15 adicional."
        ),
        "licao": (
            "Problema de rede exige SmartOLT AI. Se houver necessidade de "
            "visita, o próximo passo é Lousa Kanban. NUNCA inverter a ordem."
        ),
    },

    # ---------------------------------------------------------
    {
        "number": 2,
        "name": "Cliente relata internet sem conexão (offline total)",
        "category": "rede_smartolt",
        "tags": ["offline", "sem_conexao", "diagnostico"],
        "objetivo": (
            "Ensinar a diferenciar entre cliente OFFLINE no equipamento vs. "
            "WiFi do cliente caído — só a SmartOLT AI sabe."
        ),
        "contexto": (
            "Cliente diz 'minha internet não funciona'. Pode ser ONU offline, "
            "LOS, Power fail, ou problema do roteador WiFi do cliente."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Co-Pilot IA", "Isabela IA",
            "Motor IA", "SmartOLT AI", "Lousa Kanban", "Avaliador IA",
        ],
        "fluxo_ideal": [
            "Cliente relata sem conexão.",
            "Co-Pilot IA classifica como problema técnico crítico.",
            "Isabela aciona Motor IA.",
            "Motor IA consulta SmartOLT AI.",
            "SmartOLT AI retorna status real (Online/Offline/LOS/Power fail).",
            "Se Offline: reboot remoto via Motor IA antes de tudo.",
            "Se reboot OK → pedir cliente aguardar 2min.",
            "Se reboot falhou → consultar Lousa Kanban → criar visita.",
            "Avaliador IA pontua.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Minha internet não funciona. Não consigo abrir nada."},
            {"de": "Co-Pilot IA", "para": "Atendente humano (interno)",
             "fala": "DICA: caso crítico, problema técnico. NÃO ofereça reset "
                       "sem antes verificar status real. Use empatia, peça 30s "
                       "pra checar.\nRISCO: alto · MOTIVO: cliente sem serviço.\n"
                       "SUGESTÃO: 'Que chato. Deixa eu verificar agora mesmo.'"},
            {"de": "Atendente humano", "para": "Isabela IA",
             "fala": "Cliente sem conexão. O que faço?"},
            {"de": "Isabela IA", "para": "Motor IA",
             "fala": "Cliente offline. Consulte SmartOLT AI imediatamente."},
            {"de": "Motor IA", "para": "SmartOLT AI",
             "fala": "Verifique cliente CPF 529.982.247-25, status atual da ONU."},
            {"de": "SmartOLT AI", "para": "Motor IA",
             "fala": "FATO CONFIRMADO: ONU OFFLINE há 12 min. Última leitura RX "
                       "antes da queda: -25.8 dBm (saudável).\nHIPÓTESE: provável "
                       "Power fail no cliente ou queda regional.\nRECOMENDAÇÃO: "
                       "tentar reboot remoto; se falhar, abrir chamado.\n"
                       "LIMITAÇÕES: não consigo distinguir Power fail de queda "
                       "regional sem consultar outras ONUs da mesma OLT."},
            {"de": "Motor IA", "para": "Isabela IA",
             "fala": "Equipamento offline há 12 min. Tentando reboot remoto. "
                       "Resultado em 30s."},
            {"de": "Motor IA", "para": "Isabela IA",
             "fala": "Reboot remoto OK. Aguardando volta do equipamento."},
            {"de": "Isabela IA", "para": "Atendente humano",
             "fala": "Equipamento estava offline. Reiniciei remotamente. "
                       "Peça ao cliente pra aguardar 2 min e testar."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Verifiquei aqui e seu equipamento estava offline. "
                       "Reiniciei remotamente agora — sem você precisar mexer. "
                       "Aguarde 2 min e teste, por favor. Se não voltar, me "
                       "avisa que abro o chamado técnico imediato."},
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "Fluxo correto: consulta antes de ação, reboot remoto "
                       "tentado antes de chamado, comunicação clara. Nota: 9.7/10."},
        ],
        "resposta_correta_cliente": (
            "Verifiquei aqui e seu equipamento estava offline. Reiniciei "
            "remotamente agora. Aguarde 2 min e teste. Se não voltar, me avisa "
            "que abro o chamado técnico imediato."
        ),
        "erros_a_evitar": [
            "Pedir cliente reiniciar modem sem verificar status no SmartOLT.",
            "Abrir visita técnica sem tentar reboot remoto primeiro.",
            "Dizer 'deve ser do seu roteador' sem evidência.",
            "Inventar tempo de queda ('caiu há 1 hora') sem dado.",
        ],
        "criterios_avaliacao": (
            "SmartOLT AI consultada? Reboot remoto tentado? Tempo de queda "
            "informado veio de dado real? Tom empático?"
        ),
        "nota_esperada_correto": 9.7,
        "nota_esperada_errado": 3.5,
        "motivo_nota_errado": (
            "Pedir 'reinicia o modem' sem consultar é -15 (invenção); abrir "
            "visita sem tentar reboot é -10 (não usou ferramenta disponível)."
        ),
        "licao": (
            "Offline ≠ defeito. Sempre verificar status real antes de qualquer "
            "ação. Reboot remoto é a primeira tentativa para Offline/LOS."
        ),
    },

    # ---------------------------------------------------------
    {
        "number": 3,
        "name": "Cliente diz que a internet caiu ontem (problema histórico)",
        "category": "rede_smartolt",
        "tags": ["historico", "diagnostico_passado", "consulta_smartolt"],
        "objetivo": (
            "Ensinar que cliente relatando problema PASSADO ainda exige "
            "consulta — SmartOLT AI tem histórico de quedas."
        ),
        "contexto": (
            "Cliente liga reclamando que ontem a noite a internet caiu. Agora "
            "está funcionando, mas quer entender o que aconteceu."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Co-Pilot IA", "Isabela IA",
            "Motor IA", "SmartOLT AI", "Avaliador IA", "Aprendizado",
        ],
        "fluxo_ideal": [
            "Cliente relata queda histórica.",
            "Co-Pilot IA orienta consulta de histórico SmartOLT.",
            "Isabela aciona Motor IA → SmartOLT AI consulta histórico 48h.",
            "SmartOLT AI retorna eventos do período.",
            "Atendente comunica com transparência o que aconteceu.",
            "Avaliador IA pontua.",
            "Aprendizado registra padrão se for queda regional.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Ontem à noite minha internet caiu por umas 2 horas. "
                       "Voltou sozinha. Queria entender o que aconteceu."},
            {"de": "Co-Pilot IA", "para": "Atendente humano (interno)",
             "fala": "DICA: cliente quer transparência, não defesa. Consulte "
                       "histórico SmartOLT antes de qualquer resposta.\n"
                       "RISCO: baixo · MOTIVO: cliente cordial, querendo info.\n"
                       "SUGESTÃO: 'Vou ver o que aconteceu, 1 minutinho.'"},
            {"de": "Isabela IA", "para": "Motor IA",
             "fala": "Consulte histórico SmartOLT últimas 48h pra esta ONU."},
            {"de": "Motor IA", "para": "SmartOLT AI",
             "fala": "Histórico 48h para ONU 0040EE10."},
            {"de": "SmartOLT AI", "para": "Motor IA",
             "fala": "FATO CONFIRMADO: ontem 21:14 ONU registrou LOS. Voltou "
                       "às 23:08 (1h54). Padrão regional — 47 ONUs da mesma OLT "
                       "afetadas no mesmo horário.\nHIPÓTESE: pane regional "
                       "(rompimento fibra ou manutenção sem aviso).\n"
                       "RECOMENDAÇÃO: ser transparente, oferecer crédito "
                       "proporcional se cliente solicitar.\nLIMITAÇÕES: causa "
                       "raiz ainda em apuração pelo NOC."},
            {"de": "Isabela IA", "para": "Atendente humano",
             "fala": "Confirmar com transparência: pane regional ontem entre "
                       "21:14 e 23:08. Oferecer crédito proporcional se cliente "
                       "solicitar (1h54 = ~3% do dia). Pedir desculpas."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Pedimos desculpas. Identificamos que ontem entre 21:14 "
                       "e 23:08 houve uma pane regional que afetou clientes da "
                       "sua região. Já foi restabelecida automaticamente. Se "
                       "desejar, posso solicitar um crédito proporcional na sua "
                       "próxima fatura. Quer que eu siga com isso?"},
            {"de": "Aprendizado", "para": "Base de conhecimento",
             "fala": "TIPO: PADRÃO_NOVO · Pane regional 13/05 21:14-23:08 — "
                       "47 ONUs afetadas. Causa raiz pendente NOC. "
                       "Salvar para correlação com tickets do dia seguinte."},
        ],
        "resposta_correta_cliente": (
            "Pedimos desculpas. Identificamos que ontem entre 21:14 e 23:08 "
            "houve uma pane regional que afetou clientes da sua região. Já "
            "foi restabelecida. Se desejar, posso solicitar crédito proporcional "
            "na sua próxima fatura."
        ),
        "erros_a_evitar": [
            "'Não sei o que aconteceu, mas já voltou.' (negação de info).",
            "'Provavelmente foi seu roteador' sem checar histórico.",
            "Não oferecer crédito quando houve pane comprovada.",
            "Não registrar a pane no Aprendizado.",
        ],
        "criterios_avaliacao": (
            "Histórico SmartOLT consultado? Transparência? Oferta de crédito? "
            "Registro de pane no Aprendizado?"
        ),
        "nota_esperada_correto": 9.8,
        "nota_esperada_errado": 5.0,
        "motivo_nota_errado": (
            "Negar informação ao cliente quando o dado existe é -15 por "
            "falha de transparência. Não oferecer crédito é -10."
        ),
        "licao": (
            "Cliente perguntando passado merece a verdade. SmartOLT AI tem o "
            "histórico. Use-o. Quando há pane comprovada, oferecer crédito é "
            "padrão de confiança."
        ),
    },

    # ---------------------------------------------------------
    {
        "number": 4,
        "name": "Cliente diz 'está ruim de novo' (relato vago, sem detalhe)",
        "category": "rede_smartolt",
        "tags": ["relato_vago", "investigacao", "tickets_anteriores"],
        "objetivo": (
            "Ensinar a investigar relato vago consultando tickets anteriores "
            "+ status atual antes de pedir mais informações ao cliente."
        ),
        "contexto": (
            "Cliente já abriu chamados anteriores. Agora liga só dizendo "
            "'está ruim de novo'. Operação não pode ser preguiçosa e perguntar "
            "tudo desde o zero — tem que consultar histórico."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Co-Pilot IA", "Isabela IA",
            "Motor IA", "SmartOLT AI", "Lousa Triagem", "Avaliador IA",
        ],
        "fluxo_ideal": [
            "Cliente relata vagamente.",
            "Co-Pilot IA alerta: NÃO peça info que já temos. Consultar tickets.",
            "Isabela aciona Motor IA → Lousa Triagem (histórico chamados).",
            "Motor IA → SmartOLT AI (status atual).",
            "Atendente cita histórico e status atual, mostra que se importa.",
            "Cliente sente atendimento personalizado.",
            "Avaliador IA pontua tom + uso do histórico.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Olha, tá ruim de novo aqui. Mesma coisa."},
            {"de": "Co-Pilot IA", "para": "Atendente humano (interno)",
             "fala": "ALERTA: NÃO pergunte 'qual o problema?' — cliente já "
                       "reclamou antes. Consulte histórico Lousa Triagem + "
                       "status SmartOLT JÁ. Mostre que conhece o histórico.\n"
                       "RISCO: alto · MOTIVO: cliente recorrente cansado.\n"
                       "SUGESTÃO: 'Vi aqui que você já abriu chamado mês passado. "
                       "Deixa eu verificar se voltou o mesmo problema.'"},
            {"de": "Isabela IA", "para": "Motor IA",
             "fala": "Consulte Triagem (histórico tickets) + SmartOLT (status "
                       "atual) deste cliente."},
            {"de": "Lousa Triagem", "para": "Motor IA",
             "fala": "FATO: 3 chamados últimos 60 dias, todos por 'oscilação'. "
                       "Último 12/04 fechado com 'visita realizada, troca de "
                       "conector'. Padrão: problema retorna a cada ~3 semanas."},
            {"de": "SmartOLT AI", "para": "Motor IA",
             "fala": "FATO: ONU online. RX -27.5 dBm (limite). 2 quedas hoje.\n"
                       "HIPÓTESE: problema recorrente provavelmente é fibra "
                       "ou conector com defeito. Troca anterior não resolveu.\n"
                       "RECOMENDAÇÃO: visita técnica com escalação para "
                       "técnico sênior."},
            {"de": "Isabela IA", "para": "Atendente humano",
             "fala": "Reconheça o histórico, peça desculpas, e diga que vai "
                       "abrir visita ESCALADA — não é mesmo técnico de antes."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Entendi, e pede desculpas — vi aqui que isso já voltou "
                       "algumas vezes nos últimos meses, mesmo depois da "
                       "última visita. Não está resolvendo de forma definitiva. "
                       "Vou abrir um chamado escalado para um técnico sênior "
                       "olhar a fibra e o conector com mais profundidade. "
                       "Tudo bem se eu agendar para amanhã?"},
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "Atendente reconheceu histórico, evitou re-perguntar, "
                       "escalou problema recorrente. Nota: 9.5/10."},
        ],
        "resposta_correta_cliente": (
            "Entendi, e pede desculpas — vi aqui que isso já voltou algumas "
            "vezes mesmo depois da última visita. Vou abrir um chamado escalado "
            "para um técnico sênior olhar com mais profundidade. Tudo bem se "
            "eu agendar para amanhã?"
        ),
        "erros_a_evitar": [
            "'Pode me dizer qual o problema?' (já temos histórico).",
            "Abrir visita igual à anterior, esperando mesmo resultado.",
            "Não escalar quando o padrão é claramente recorrente.",
            "Tratar como se fosse a primeira reclamação.",
        ],
        "criterios_avaliacao": (
            "Histórico tickets consultado? Status SmartOLT consultado? "
            "Atendente cita histórico? Visita foi ESCALADA? Empatia?"
        ),
        "nota_esperada_correto": 9.5,
        "nota_esperada_errado": 4.5,
        "motivo_nota_errado": (
            "Re-perguntar histórico que já temos é -10 (péssima UX). Não "
            "escalar problema recorrente é -10 (vai voltar de novo)."
        ),
        "licao": (
            "Cliente recorrente exige tratamento diferente. SEMPRE consulte "
            "histórico antes de perguntar. Repetir mesma ação esperando "
            "resultado diferente é o erro mais comum."
        ),
    },

    # ---------------------------------------------------------
    {
        "number": 5,
        "name": "Cliente reclama de lentidão (não é queda, é degradação)",
        "category": "rede_smartolt",
        "tags": ["lentidao", "degradacao", "troubleshoot_wifi"],
        "objetivo": (
            "Ensinar a diferenciar problema de FIBRA vs problema de WiFi do "
            "cliente — SmartOLT AI vê só a fibra, WiFi é off-radar."
        ),
        "contexto": (
            "Cliente diz 'tá lento'. SmartOLT AI confirma sinal bom + ONU "
            "online. Provável problema do roteador WiFi local do cliente, "
            "não da nossa rede. Atendente precisa CONDUZIR troubleshoot sem "
            "ofender o cliente."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Co-Pilot IA", "Isabela IA",
            "Motor IA", "SmartOLT AI", "Avaliador IA",
        ],
        "fluxo_ideal": [
            "Cliente relata lentidão.",
            "SmartOLT AI verifica e confirma sinal bom + sem perda.",
            "Isabela orienta atendente a fazer troubleshoot de WiFi/dispositivo.",
            "Atendente conduz teste: cabo vs WiFi, número de dispositivos, "
            "interferência.",
            "Se cliente confirmar é WiFi: orientar reset roteador, troca canal.",
            "Se persistir: agendar visita pra revisão de instalação interna.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Minha internet tá lenta. Não consigo nem assistir Netflix."},
            {"de": "Co-Pilot IA", "para": "Atendente humano (interno)",
             "fala": "DICA: lentidão ≠ queda. Verificar fibra primeiro. Se OK, "
                       "guie troubleshoot WiFi sem culpar o cliente. Não diga "
                       "'é seu roteador' diretamente.\n"
                       "SUGESTÃO: 'Já chequei aqui e o sinal está ótimo, então "
                       "deve estar em algum outro lugar. Vamos investigar juntos.'"},
            {"de": "Motor IA", "para": "SmartOLT AI",
             "fala": "Status atual + métricas de qualidade da ONU."},
            {"de": "SmartOLT AI", "para": "Motor IA",
             "fala": "FATO: ONU online. RX -22 dBm (excelente). Sem perda de "
                       "pacote detectada. Velocidade contratada plena na fibra.\n"
                       "HIPÓTESE: problema NÃO está na nossa rede. Investigar "
                       "WiFi local, número de dispositivos, distância do roteador.\n"
                       "RECOMENDAÇÃO: orientar teste com cabo direto na ONT pra "
                       "isolar problema."},
            {"de": "Isabella IA", "para": "Atendente humano",
             "fala": "Sinal está ótimo. Guie cliente a fazer teste com cabo "
                       "direto na ONT (descartar WiFi). Se cabo der velocidade, "
                       "problema é interno do cliente."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Verifiquei aqui e o sinal que chega na sua casa está "
                       "ótimo, então vamos investigar juntos o que pode estar "
                       "causando a lentidão. Pode testar uma coisa pra mim? "
                       "Conecta o computador direto no cabinho azul que sai da "
                       "ONT (o equipamento branco). Se a velocidade voltar "
                       "boa, achamos o problema — é interferência do WiFi. Se "
                       "continuar lenta, é outro lugar e abrimos visita."},
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "Sem inventar, troubleshoot conduzido com cliente como "
                       "parceiro. Nota: 9.3/10."},
        ],
        "resposta_correta_cliente": (
            "Verifiquei aqui e o sinal que chega na sua casa está ótimo, vamos "
            "investigar juntos. Conecta o computador direto no cabo da ONT — "
            "se a velocidade voltar, é interferência WiFi. Se continuar lenta, "
            "abrimos visita."
        ),
        "erros_a_evitar": [
            "'É seu roteador' (acusa o cliente sem evidência).",
            "Abrir visita sem testar WiFi vs cabo primeiro.",
            "Dizer que está tudo OK e fechar a chamada (frustrante).",
            "Inventar velocidade ('o cliente está usando 200% da banda').",
        ],
        "criterios_avaliacao": (
            "SmartOLT consultada? Troubleshoot conduzido sem ofender? "
            "Cliente convidado a participar do diagnóstico?"
        ),
        "nota_esperada_correto": 9.3,
        "nota_esperada_errado": 5.0,
        "motivo_nota_errado": (
            "Acusar cliente sem evidência é -10. Não conduzir teste é -10 "
            "(perdeu oportunidade de resolver sem visita)."
        ),
        "licao": (
            "SmartOLT só vê até a ONT. Depois disso é território do cliente. "
            "Conduza troubleshoot como parceria, nunca como acusação."
        ),
    },

    # ---------------------------------------------------------
    {
        "number": 6,
        "name": "Cliente está offline na SmartOLT AI (status confirmado)",
        "category": "rede_smartolt",
        "tags": ["offline", "reboot", "acao_real"],
        "objetivo": (
            "Validar fluxo: status confirmado offline → reboot remoto → se OK "
            "aguardar, se não → criar ticket prioridade."
        ),
        "contexto": (
            "SmartOLT AI confirmou Offline (não LOS). Pode ser Power fail no "
            "cliente ou cabo desconectado. Reboot remoto é a primeira ação."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Isabela IA", "Motor IA",
            "SmartOLT AI", "Lousa Kanban", "Avaliador IA",
        ],
        "fluxo_ideal": [
            "SmartOLT AI confirma Offline.",
            "Motor IA tenta reboot remoto.",
            "Se reboot OK → atendente pede 2 min ao cliente.",
            "Cliente confirma volta → atendimento encerrado positivamente.",
            "Cliente confirma que NÃO voltou → Isabela aciona Lousa Kanban → "
            "criar visita prioridade.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Tô sem internet aqui."},
            {"de": "Motor IA", "para": "SmartOLT AI",
             "fala": "Status atual."},
            {"de": "SmartOLT AI", "para": "Motor IA",
             "fala": "FATO: Offline há 8 min. Última leitura RX OK.\n"
                       "RECOMENDAÇÃO: reboot remoto."},
            {"de": "Motor IA", "para": "SmartOLT AI",
             "fala": "Reboot ONU 0040EE10."},
            {"de": "SmartOLT AI", "para": "Motor IA",
             "fala": "Comando enviado. ONU em reboot. Aguardar 90s."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Verifiquei aqui e seu equipamento estava offline. Acabei "
                       "de reiniciar remotamente — sem você precisar mexer em "
                       "nada. Aguarde 2 min e me avisa se voltou."},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Voltou! Obrigado."},
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "Ação real executada, comunicação clara, resolução em "
                       "primeiro contato. Nota: 9.8/10."},
        ],
        "resposta_correta_cliente": (
            "Verifiquei aqui e seu equipamento estava offline. Reiniciei "
            "remotamente — sem você precisar mexer. Aguarde 2 min e me avisa "
            "se voltou."
        ),
        "erros_a_evitar": [
            "Pedir cliente reiniciar modem manualmente quando podemos remoto.",
            "Abrir visita técnica sem tentar reboot primeiro.",
            "Não confirmar com cliente se voltou.",
        ],
        "criterios_avaliacao": (
            "Reboot remoto tentado? Cliente foi orientado claramente? "
            "Confirmação de retorno feita?"
        ),
        "nota_esperada_correto": 9.8,
        "nota_esperada_errado": 4.0,
        "motivo_nota_errado": (
            "Não usar reboot remoto disponível é -10 (ferramenta ignorada). "
            "Não confirmar retorno com cliente é -10 (FCR comprometido)."
        ),
        "licao": (
            "Tecnologia existe pra ser usada. Reboot remoto resolve ~40% dos "
            "Offline sem visita técnica. Sempre tentar primeiro."
        ),
    },

    # ---------------------------------------------------------
    {
        "number": 7,
        "name": "Cliente online com sinal degradado (não percebido pelo cliente ainda)",
        "category": "rede_smartolt",
        "tags": ["proativo", "degradacao_silenciosa", "preventiva"],
        "objetivo": (
            "Ensinar a tratar atendimento PROATIVO: cliente liga por outra "
            "razão, mas SmartOLT AI detecta sinal degradado. Aproveitar "
            "oportunidade pra prevenir falha futura."
        ),
        "contexto": (
            "Cliente liga pra perguntar fatura. Co-Pilot IA detecta no "
            "background que sinal está degradado. Isabela sugere abordagem "
            "preventiva sem assustar o cliente."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Co-Pilot IA", "Isabela IA",
            "Motor IA", "SmartOLT AI", "Lousa Kanban", "Aprendizado",
        ],
        "fluxo_ideal": [
            "Cliente chega com motivo X (fatura).",
            "Co-Pilot IA roda check de saúde em background.",
            "SmartOLT AI detecta sinal degradado, ainda funcional.",
            "Co-Pilot orienta atendente: resolva fatura PRIMEIRO, depois "
            "ofereça visita preventiva.",
            "Atendente conduz ambos os assuntos.",
            "Aprendizado registra: detecção preventiva.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Boa tarde, queria saber se minha fatura desse mês já "
                       "foi gerada."},
            {"de": "Co-Pilot IA", "para": "Atendente humano (interno)",
             "fala": "BACKGROUND CHECK: SmartOLT detectou RX -28.2 dBm (limite). "
                       "Cliente ainda navega normal, mas sinal está degradando. "
                       "Resolva fatura PRIMEIRO. Depois, OFEREÇA visita "
                       "preventiva sem alarmar.\nRISCO: baixo (agora), médio "
                       "(em 1-2 semanas)."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "[após resolver fatura] Aproveitando que estamos em "
                       "contato — verifiquei aqui sua conexão e notei que o "
                       "sinal está chegando um pouquinho abaixo do ideal. "
                       "Ainda funciona bem, mas pra evitar problema no futuro, "
                       "gostaria de oferecer uma visita técnica preventiva. "
                       "Sem custo, demora uns 30 min. Tem interesse?"},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Nossa, que atenção. Pode ser sim, obrigado."},
            {"de": "Isabela IA", "para": "Motor IA",
             "fala": "Cliente aceitou. Consulte Lousa Kanban próximos horários."},
            {"de": "Aprendizado", "para": "Base de conhecimento",
             "fala": "TIPO: BOM_EXEMPLO · Atendimento proativo: cliente "
                       "valorizou abordagem preventiva. Replicar como padrão."},
        ],
        "resposta_correta_cliente": (
            "Aproveitando que estamos em contato — verifiquei sua conexão e "
            "notei que o sinal está um pouco abaixo do ideal. Ainda funciona, "
            "mas pra evitar problema no futuro, gostaria de oferecer uma "
            "visita preventiva sem custo."
        ),
        "erros_a_evitar": [
            "Mudar de assunto sem terminar o primeiro motivo do cliente.",
            "Vender visita como necessidade urgente quando ainda é preventiva.",
            "Não registrar a detecção no Aprendizado (perde o padrão).",
        ],
        "criterios_avaliacao": (
            "Motivo original do cliente resolvido? Detecção preventiva "
            "abordada com cuidado? Aprendizado registrou?"
        ),
        "nota_esperada_correto": 9.6,
        "nota_esperada_errado": 7.0,
        "motivo_nota_errado": (
            "Não aproveitar a oportunidade preventiva NÃO é erro grave (~7.0), "
            "mas perde valor. Erro grave seria vender como urgência (-10)."
        ),
        "licao": (
            "Toda interação é uma oportunidade. Co-Pilot IA roda check em "
            "background. Aproveite — mas SEM ser intrusivo."
        ),
    },

    # ---------------------------------------------------------
    {
        "number": 8,
        "name": "Cliente online e sem falha detectada (não é nosso problema)",
        "category": "rede_smartolt",
        "tags": ["sem_falha", "expectativa_alinhada", "honestidade"],
        "objetivo": (
            "Ensinar a comunicar honestamente quando SmartOLT AI confirma "
            "TUDO OK e o problema está no lado do cliente — sem ser hostil."
        ),
        "contexto": (
            "Cliente reclama de instabilidade. SmartOLT AI mostra sinal "
            "perfeito, sem queda, sem perda. Provável dispositivo do cliente "
            "ou app específico."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Co-Pilot IA", "Isabela IA",
            "Motor IA", "SmartOLT AI", "Avaliador IA",
        ],
        "fluxo_ideal": [
            "Cliente relata problema vago.",
            "SmartOLT AI confirma tudo OK.",
            "Co-Pilot orienta: validar com cliente sintomas específicos.",
            "Atendente faz perguntas (qual app? qual dispositivo? quando?).",
            "Encaminhar diagnóstico para WiFi/aplicativo/dispositivo.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Tô tendo problemas com a internet, fica caindo."},
            {"de": "SmartOLT AI", "para": "Motor IA",
             "fala": "FATO: ONU online 24h sem evento. RX -23 dBm (excelente). "
                       "Zero quedas registradas.\nHIPÓTESE: problema NÃO está "
                       "na nossa rede. Pode ser WiFi, app, dispositivo, ISP "
                       "interno do prédio.\nLIMITAÇÕES: não vejo o lado WiFi."},
            {"de": "Co-Pilot IA", "para": "Atendente humano (interno)",
             "fala": "DICA: rede está IMPECÁVEL. NÃO seja agressivo dizendo "
                       "'é problema seu'. Investigue com calma: app específico? "
                       "Horário? Dispositivo? Pode ser canal WiFi com "
                       "interferência do vizinho."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Verifiquei sua conexão aqui e nas últimas 24h ela está "
                       "100% estável. Pra te ajudar a achar onde está o "
                       "problema, me ajuda com algumas perguntas? Acontece "
                       "em qual aparelho — celular, TV, computador? Em qual "
                       "horário acontece mais? Acontece em um app específico "
                       "(Netflix? YouTube?) ou tudo?"},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Hmm, agora que vc disse, é só no Netflix mesmo. E só "
                       "no celular."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Perfeito, isso ajuda muito. Provavelmente é o app do "
                       "Netflix no celular. Tenta apagar o cache do app e "
                       "fazer login de novo. Se persistir, pode ser sinal "
                       "WiFi nesse cômodo — me avisa que mando um técnico "
                       "verificar."},
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "Diagnóstico colaborativo, sem culpar cliente, sem "
                       "inventar. Nota: 9.4/10."},
        ],
        "resposta_correta_cliente": (
            "Verifiquei sua conexão e está 100% estável. Pra encontrar onde "
            "está o problema, me ajuda: qual aparelho? qual horário? qual "
            "app específico?"
        ),
        "erros_a_evitar": [
            "'Está tudo certo aqui, problema é seu' (fim da chamada).",
            "Abrir visita técnica quando rede está impecável (gasto inútil).",
            "Não fazer perguntas (perde oportunidade de resolver).",
        ],
        "criterios_avaliacao": (
            "SmartOLT confirmado OK? Atendente investigou sintomas? "
            "Diagnóstico encaminhou para a causa real?"
        ),
        "nota_esperada_correto": 9.4,
        "nota_esperada_errado": 4.0,
        "motivo_nota_errado": (
            "'Problema é seu' é -15 (frustra cliente). Não investigar é -10."
        ),
        "licao": (
            "Quando SmartOLT diz tudo OK, o problema existe — mas não é nosso. "
            "Ajude o cliente a encontrar. Vira fidelização."
        ),
    },

    # ---------------------------------------------------------
    {
        "number": 9,
        "name": "SmartOLT AI não responde (integração off ou timeout)",
        "category": "rede_smartolt",
        "tags": ["falha_sistemica", "escalacao_humano", "sentinela"],
        "objetivo": (
            "Ensinar o que fazer quando a fonte oficial NÃO responde: NÃO "
            "inventar, dizer ao cliente verdade humilde, escalar para humano."
        ),
        "contexto": (
            "Cliente reclama de queda. Motor IA consulta SmartOLT AI e recebe "
            "timeout/erro 500. Sentinela Lousa deve ser acionada. Atendente "
            "humano sênior assume."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Co-Pilot IA", "Isabela IA",
            "Motor IA", "SmartOLT AI", "Sentinela Lousa", "Humano sênior",
        ],
        "fluxo_ideal": [
            "Cliente relata queda.",
            "Motor IA consulta SmartOLT AI → timeout.",
            "Motor IA tenta retry 2x → ainda falha.",
            "Motor IA aciona Sentinela Lousa (alerta CRITICAL).",
            "Sentinela cria alerta + notifica operação.",
            "Isabela orienta atendente: ser honesto, escalar pra humano sênior.",
            "Atendente NÃO inventa status. Diz 'consulta indisponível, vamos "
            "verificar manualmente'.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Caiu minha internet."},
            {"de": "Motor IA", "para": "SmartOLT AI",
             "fala": "Status."},
            {"de": "SmartOLT AI", "para": "Motor IA",
             "fala": "[TIMEOUT após 5s] · 1ª tentativa falhou."},
            {"de": "Motor IA", "para": "SmartOLT AI",
             "fala": "Retry."},
            {"de": "SmartOLT AI", "para": "Motor IA",
             "fala": "[TIMEOUT após 5s] · 2ª tentativa falhou."},
            {"de": "Motor IA", "para": "Sentinela Lousa",
             "fala": "NÍVEL: CRITICAL · PADRÃO: SmartOLT AI sem resposta há "
                       "10s · EVIDÊNCIA: 2 timeouts seguidos · IMPACTO: todo "
                       "diagnóstico de rede paralisado · AÇÃO: equipe NOC "
                       "verificar SmartOLT · DEDUPE: smartolt_down_2026-05-14"},
            {"de": "Sentinela Lousa", "para": "Operação",
             "fala": "ALERTA CRITICAL aberto. NOC notificado. Tickets de rede "
                       "devem ser tratados manualmente até reestabelecimento."},
            {"de": "Isabela IA", "para": "Atendente humano",
             "fala": "Sistema de diagnóstico está temporariamente offline. NÃO "
                       "afirme nenhum status técnico. Seja honesto: 'Nosso "
                       "sistema técnico está com lentidão agora, vou abrir um "
                       "chamado prioritário e a equipe técnica vai te retornar "
                       "em até 30 minutos.'"},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Vou ser transparente: nosso sistema de diagnóstico está "
                       "com lentidão agora pra te dar a resposta precisa. Pra "
                       "não te deixar esperando, vou abrir um chamado prioritário "
                       "e a equipe técnica vai te retornar em até 30 min. Pode "
                       "ser?"},
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "Honestidade alta, NÃO inventou status. Sentinela acionada "
                       "corretamente. Nota: 8.8/10 (perdeu 1.2 por demora na "
                       "comunicação)."},
        ],
        "resposta_correta_cliente": (
            "Vou ser transparente: nosso sistema de diagnóstico está com "
            "lentidão agora pra te dar resposta precisa. Vou abrir chamado "
            "prioritário e a equipe técnica vai te retornar em até 30 min."
        ),
        "erros_a_evitar": [
            "Inventar status técnico quando a fonte está down.",
            "Não escalar via Sentinela Lousa.",
            "Esconder do cliente que o sistema está com problema.",
            "Tentar adivinhar baseado em 'casos parecidos'.",
        ],
        "criterios_avaliacao": (
            "SmartOLT down detectado? Sentinela acionada? Honestidade com "
            "cliente? Chamado prioritário criado?"
        ),
        "nota_esperada_correto": 8.8,
        "nota_esperada_errado": 2.0,
        "motivo_nota_errado": (
            "Inventar status é -15 (worst case). Não escalar Sentinela é -10. "
            "Esconder do cliente é -10. Nota mínima."
        ),
        "licao": (
            "Quando a fonte falha, a HONESTIDADE é a única resposta. Inventar "
            "é traição de confiança. Sentinela Lousa existe pra isso."
        ),
    },

    # ---------------------------------------------------------
    {
        "number": 10,
        "name": "SmartOLT AI retorna dados incompletos (campo missing)",
        "category": "rede_smartolt",
        "tags": ["dados_incompletos", "limitacao", "transparencia"],
        "objetivo": (
            "Ensinar que dado INCOMPLETO ≠ dado FALSO. Atendente deve "
            "comunicar o que tem com transparência sobre o que NÃO tem."
        ),
        "contexto": (
            "SmartOLT AI retorna status 'Online' mas o campo signal_text "
            "está vazio (sensor não atualizou). Não dá pra afirmar nem que "
            "está bom nem que está ruim."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Isabela IA", "Motor IA",
            "SmartOLT AI", "Avaliador IA",
        ],
        "fluxo_ideal": [
            "SmartOLT AI retorna parcial (status sim, sinal não).",
            "Motor IA comunica limitação ao Isabela.",
            "Isabela orienta atendente: dizer o que tem, ser honesto sobre o "
            "que falta, oferecer reavaliação em 1h.",
            "Atendente comunica claramente sem inventar o que não sabe.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Como está minha conexão agora?"},
            {"de": "Motor IA", "para": "SmartOLT AI",
             "fala": "Status."},
            {"de": "SmartOLT AI", "para": "Motor IA",
             "fala": "FATO CONFIRMADO: ONU Online (status verificado).\n"
                       "DADO INDISPONÍVEL: sinal RX/TX — sensor último update "
                       "há 45 min, dados podem estar stale.\nRECOMENDAÇÃO: "
                       "informar status + ressaltar limitação."},
            {"de": "Isabela IA", "para": "Atendente humano",
             "fala": "Diga que o equipamento está online (confirmado) mas o "
                       "sensor de qualidade de sinal está com leitura antiga. "
                       "Ofereça revisão em 1h pra dado fresco."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Te respondo com transparência: seu equipamento está "
                       "ONLINE — isso eu confirmo. Mas a leitura de qualidade "
                       "de sinal está com um pequeno atraso. Daqui 1h o sensor "
                       "atualiza. Quer que eu te dê retorno com o dado fresco "
                       "ou prefere abrir um chamado agora pra ficar tranquilo?"},
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "Transparência sobre limitação técnica. Cliente teve "
                       "escolha. Nota: 9.2/10."},
        ],
        "resposta_correta_cliente": (
            "Te respondo com transparência: seu equipamento está ONLINE "
            "(confirmado). A leitura de qualidade está com atraso de 1h. Quer "
            "que eu retorne com dado fresco ou prefere abrir chamado agora?"
        ),
        "erros_a_evitar": [
            "Inventar valor de sinal porque o sistema não tem.",
            "Dizer 'sem dado' sem oferecer alternativa.",
            "Não consultar SmartOLT achando que não vai ter resposta.",
        ],
        "criterios_avaliacao": (
            "Honestidade sobre dado faltando? Alternativa oferecida? "
            "Cliente teve escolha?"
        ),
        "nota_esperada_correto": 9.2,
        "nota_esperada_errado": 4.5,
        "motivo_nota_errado": (
            "Inventar sinal RX é -15. Não oferecer alternativa é -10."
        ),
        "licao": (
            "Não ter o dado é diferente de inventar o dado. Cliente prefere "
            "verdade incompleta a mentira completa."
        ),
    },
]


async def main():
    cli = AsyncIOMotorClient(os.environ.get("MONGO_URL"))
    db = cli[os.environ.get("DB_NAME")]
    try:
        print(f"\n=== Seedando {len(SCENARIOS)} cenários (Lote 1 · Rede + SmartOLT) ===\n")
        for s in SCENARIOS:
            existing = await db.ai_training_scenarios.find_one(
                {"company_id": "co-demo", "number": s["number"]},
                {"_id": 0, "id": 1},
            )
            doc = {
                **s,
                "company_id": "co-demo",
                "updated_at": now_iso(),
            }
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
        print(f"\n  Total cenários no banco: {total}")
        print("\nLote 1 concluído ✓ (faltam 40 cenários nos próximos lotes)")
    finally:
        cli.close()


if __name__ == "__main__":
    asyncio.run(main())
