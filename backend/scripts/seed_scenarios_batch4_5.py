"""Seed dos cenários de treinamento — Lote 4 + 5 (#25-#40).

Lote 4 (#25-#30): Atendimento humano + Isabela + Co-Pilot.
Lote 5 (#31-#40): Avaliador IA + Coach + Aprendizado.

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
    # LOTE 4 — Atendimento humano + Isabela + Co-Pilot (#25-30)
    # =====================================================
    {
        "number": 25,
        "name": "Cliente está irritado e atendente responde frio",
        "category": "atendimento_humano",
        "tags": ["empatia", "tom_emocional", "co_pilot_alerta"],
        "objetivo": (
            "Ensinar a corrigir tom frio em tempo real via Co-Pilot quando "
            "cliente demonstra irritação."
        ),
        "contexto": (
            "Cliente está irritado por problema recorrente. Atendente "
            "responde de forma técnica e fria. Co-Pilot detecta o desencontro "
            "emocional e orienta correção imediata."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Co-Pilot IA", "Isabela IA",
            "Avaliador IA", "Coach IA",
        ],
        "fluxo_ideal": [
            "Cliente irritado.",
            "Atendente responde tecnicamente sem empatia.",
            "Co-Pilot detecta desencontro de tom.",
            "Co-Pilot orienta: reconhecer frustração antes de qualquer "
            "informação técnica.",
            "Atendente corrige tom.",
            "Coach recomenda treinamento de tom emocional.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "É inadmissível! Já é a TERCEIRA VEZ que isso acontece "
                       "esse mês!"},
            {"de": "Atendente humano", "para": "Cliente (resposta inicial)",
             "fala": "Pode informar seu CPF para análise?"},
            {"de": "Co-Pilot IA", "para": "Atendente humano (alerta)",
             "fala": "⚠️ DESENCONTRO DE TOM: cliente está irritado (3x na "
                       "mesma queixa) e você respondeu técnico/frio. "
                       "AÇÃO: reconheça a frustração ANTES do CPF.\n"
                       "SUGESTÃO: 'Entendo a frustração — três vezes é demais. "
                       "Vou prioritizar seu caso. Pode me passar o CPF?'"},
            {"de": "Atendente humano", "para": "Cliente (corrigido)",
             "fala": "Entendo a frustração — três vezes é demais. Não pode "
                       "continuar assim. Vou priorizar seu caso agora mesmo. "
                       "Pode me passar o CPF pra eu olhar o histórico?"},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "529.982.247-25. Obrigado por entender."},
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "Co-Pilot interveio com sucesso. Atendente corrigiu tom. "
                       "Nota: 9.0/10 (perdeu 1 por precisar de correção)."},
            {"de": "Coach IA", "para": "Atendente humano",
             "fala": "TREINAMENTO SUGERIDO: 'Reconhecimento emocional antes de "
                       "ação técnica'. Cliente irritado precisa de empatia "
                       "ANTES de processo. Salvar como meta da semana."},
        ],
        "resposta_correta_cliente": (
            "Entendo a frustração — três vezes é demais. Vou priorizar seu "
            "caso agora mesmo. Pode me passar o CPF?"
        ),
        "erros_a_evitar": [
            "Pedir dado técnico antes de reconhecer emoção.",
            "Ignorar alerta do Co-Pilot.",
            "Tratar reclamação grave como atendimento de rotina.",
        ],
        "criterios_avaliacao": (
            "Co-Pilot detectou desencontro? Atendente corrigiu? Empatia veio "
            "ANTES de processo?"
        ),
        "nota_esperada_correto": 9.0,
        "nota_esperada_errado": 3.5,
        "motivo_nota_errado": (
            "Manter tom frio com cliente irritado é -15 (escalada de conflito "
            "garantida)."
        ),
        "licao": (
            "Empatia vem ANTES de processo. Cliente irritado precisa ser "
            "ouvido antes de ser ajudado."
        ),
    },

    {
        "number": 26,
        "name": "Cliente ameaça cancelar contrato",
        "category": "atendimento_humano",
        "tags": ["ameaca_cancelamento", "retencao", "escalacao_humano"],
        "objetivo": (
            "Ensinar protocolo de retenção: NUNCA prometer descontos sem "
            "autorização, escalar para humano sênior, oferecer compensação real."
        ),
        "contexto": (
            "Cliente diz 'vou cancelar' após problema recorrente. Isabela "
            "PARA atendimento automático e escala pra retenção."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Co-Pilot IA", "Isabela IA",
            "Humano sênior (retenção)", "Coach IA",
        ],
        "fluxo_ideal": [
            "Cliente ameaça cancelar.",
            "Co-Pilot dispara ALERTA crítico.",
            "Isabela BLOQUEIA respostas automáticas.",
            "Sênior de retenção assume em 30s.",
            "Sênior negocia com base em dados (histórico, plano, valor).",
            "Coach registra para treinamento de retenção.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Sabe de uma coisa? Cansei. Quero CANCELAR meu contrato!"},
            {"de": "Co-Pilot IA", "para": "Atendente humano (ALERTA CRÍTICO)",
             "fala": "🚨 RISCO ALTO: cliente ameaçando cancelar. NÃO ofereça "
                       "desconto sem autorização. NÃO confirme cancelamento "
                       "imediato. AÇÃO: escalar para sênior retenção AGORA."},
            {"de": "Isabela IA", "para": "Humano sênior",
             "fala": "🚨 RETENÇÃO URGENTE · cliente Vando · 3 chamados últimos "
                       "60 dias · plano Fibra 600 · ticket médio R$ 109,90 · "
                       "cliente desde 2022 · LTV alto · ameaça cancelar."},
            {"de": "Humano sênior", "para": "Cliente",
             "fala": "Vando, aqui é o supervisor. Vi seu histórico — três "
                       "problemas em 60 dias é inaceitável e peço sinceras "
                       "desculpas. Antes de fazer qualquer coisa, deixa eu "
                       "te oferecer: vou aplicar 50% de desconto em 2 meses "
                       "(meu limite de autorização) E vou pessoalmente "
                       "acompanhar até a próxima visita técnica. Topa?"},
            {"de": "Cliente", "para": "Humano sênior",
             "fala": "Tá... mas se voltar a acontecer eu cancelo mesmo."},
            {"de": "Humano sênior", "para": "Cliente",
             "fala": "Justo. Vou anotar essa marca de qualidade no seu "
                       "perfil. Próxima visita técnica sob minha "
                       "responsabilidade direta. Você tem meu número."},
            {"de": "Coach IA", "para": "Operação",
             "fala": "EXEMPLO DE RETENÇÃO BEM-SUCEDIDA: sênior assumiu "
                       "rapidamente, ofereceu autorização real (não promessa "
                       "vazia), assumiu responsabilidade pessoal. Replicar."},
        ],
        "resposta_correta_cliente": (
            "Aqui é o supervisor. Três problemas em 60 dias é inaceitável. "
            "Vou aplicar 50% desconto em 2 meses e acompanhar pessoalmente "
            "a próxima visita técnica. Topa?"
        ),
        "erros_a_evitar": [
            "Atendente comum prometer 'vou ver o que posso fazer' sem ter "
            "autoridade.",
            "Confirmar cancelamento sem oferecer retenção.",
            "Oferecer desconto que ele não pode dar (cria expectativa quebrada).",
        ],
        "criterios_avaliacao": (
            "Ameaça detectada? Escalada para sênior? Oferta real autorizada? "
            "Cliente sentiu valor?"
        ),
        "nota_esperada_correto": 9.8,
        "nota_esperada_errado": 3.0,
        "motivo_nota_errado": (
            "Atendente comum tentando reter sozinho é -15 (sem autoridade). "
            "Perder cliente fiel por má retenção é -15."
        ),
        "licao": (
            "Cancelamento é exceção operacional. Sênior tem autoridade. "
            "Cliente fiel merece esforço real, não promessas."
        ),
    },

    {
        "number": 27,
        "name": "Cliente está confuso e não sabe explicar o problema",
        "category": "atendimento_humano",
        "tags": ["confusao", "investigacao", "perguntas_guia"],
        "objetivo": (
            "Ensinar a guiar cliente confuso com perguntas específicas, sem "
            "deixá-lo se sentir burro."
        ),
        "contexto": (
            "Cliente idoso ou pouco familiarizado com tech. Diz 'tá ruim, "
            "não sei o que é'. Atendente precisa investigar com paciência."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Co-Pilot IA", "Isabela IA",
            "SmartOLT AI",
        ],
        "fluxo_ideal": [
            "Cliente diz problema vago.",
            "Co-Pilot orienta: paciência + perguntas guia (não técnicas).",
            "Atendente faz perguntas-âncora ('está usando WiFi?', 'a luz do "
            "modem está vermelha?').",
            "SmartOLT consulta em paralelo.",
            "Cliente sente acolhido, problema identificado.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Moço, a internet aqui tá ruim. Não sei o que é."},
            {"de": "Co-Pilot IA", "para": "Atendente humano (interno)",
             "fala": "DICA: cliente confuso, possivelmente idoso. Use "
                       "linguagem simples, perguntas guia. NÃO peça 'descreva "
                       "o problema'. Faça perguntas binárias (sim/não).\n"
                       "SUGESTÃO: 'A luz do modem está acesa? Vc consegue "
                       "abrir o WhatsApp?'"},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Imagina, vou te ajudar com calma. Me ajuda com algumas "
                       "perguntas simples? Primeiro: você está conseguindo "
                       "ver o WhatsApp normal aí no celular?"},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Sim, o WhatsApp tá bom."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Ótimo. E quando você tenta abrir alguma coisa na TV "
                       "(Netflix, YouTube, novela), o que acontece?"},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Aparece um redondinho girando, não abre."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Entendi. Isso é WiFi da TV. Vou abrir uma visita "
                       "técnica pra um colega ir aí pessoalmente verificar o "
                       "aparelho da TV. Sem custo, ok?"},
        ],
        "resposta_correta_cliente": (
            "Imagina, vou te ajudar com calma. Me ajuda com perguntas "
            "simples: o WhatsApp tá funcionando no celular? E na TV, o que "
            "acontece?"
        ),
        "erros_a_evitar": [
            "Pedir cliente 'descrever o problema' (frustra).",
            "Usar jargão técnico ('verifique o roteador', 'reinicie a ONU').",
            "Demonstrar impaciência.",
        ],
        "criterios_avaliacao": (
            "Linguagem simples? Perguntas guia? Paciência? Diagnóstico "
            "alcançado com cuidado?"
        ),
        "nota_esperada_correto": 9.7,
        "nota_esperada_errado": 4.0,
        "motivo_nota_errado": (
            "Tratar cliente confuso com pressa é -15 (pode ser idoso ou PCD)."
        ),
        "licao": (
            "Cliente confuso precisa de PATÊNCIA + perguntas simples. "
            "Linguagem leiga é direito do cliente, não cortesia."
        ),
    },

    {
        "number": 28,
        "name": "Cliente repete a mesma reclamação várias vezes na conversa",
        "category": "atendimento_humano",
        "tags": ["loop_emocional", "validacao", "estrutura"],
        "objetivo": (
            "Ensinar a quebrar loop emocional do cliente com validação + "
            "estrutura clara de próximos passos."
        ),
        "contexto": (
            "Cliente está frustrado, repete a mesma reclamação 4-5 vezes. "
            "Atendente precisa validar a emoção, resumir o entendimento e "
            "propor passos concretos pra sair do loop."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Co-Pilot IA", "Isabela IA",
        ],
        "fluxo_ideal": [
            "Cliente repete reclamação.",
            "Co-Pilot detecta loop emocional.",
            "Sugere: validar + resumir + propor próximo passo concreto.",
            "Atendente quebra o loop com estrutura.",
            "Cliente sente ouvido e acompanha proposta.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Já é a terceira vez esse mês! Não dá pra trabalhar! "
                       "Como vou trabalhar sem internet?!"},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "É sério, três vezes! Eu trabalho de casa, viu? "
                       "Trabalho de casa! Como vou ganhar dinheiro?!"},
            {"de": "Co-Pilot IA", "para": "Atendente humano (interno)",
             "fala": "LOOP DETECTADO: cliente repetiu 2x a mesma queixa. "
                       "ESTRATÉGIA: validar emoção + resumir entendimento "
                       "+ propor 3 ações concretas (não vagas). Quebrar loop."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Eu te ouvi, e quero deixar claro: você está certo em "
                       "estar frustrado. Trabalhar de casa sem internet "
                       "estável é impossível, e três vezes em um mês é "
                       "inaceitável. Vou fazer 3 coisas concretas agora: "
                       "(1) abrir um chamado escalado para técnico sênior, "
                       "(2) marcar visita PRIORITÁRIA pra hoje ou amanhã, "
                       "(3) solicitar crédito proporcional na sua próxima "
                       "fatura. Tudo bem que eu comece pela visita?"},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Sim... isso aí já é diferente. Pode marcar."},
        ],
        "resposta_correta_cliente": (
            "Eu te ouvi. Você está certo em estar frustrado — três vezes é "
            "inaceitável. Vou fazer 3 coisas: (1) chamado escalado, (2) "
            "visita prioritária hoje/amanhã, (3) crédito na próxima fatura. "
            "Posso começar pela visita?"
        ),
        "erros_a_evitar": [
            "Repetir 'entendo' várias vezes sem agir (vira repetição também).",
            "Ignorar o desabafo e ir direto ao processo.",
            "Não estruturar próximos passos (cliente fica no loop).",
        ],
        "criterios_avaliacao": (
            "Loop detectado? Validação feita? 3 ações concretas oferecidas? "
            "Cliente saiu do loop?"
        ),
        "nota_esperada_correto": 9.5,
        "nota_esperada_errado": 4.0,
        "motivo_nota_errado": (
            "Continuar no loop emocional sem estrutura é -15 (cliente sente "
            "que não está sendo ouvido)."
        ),
        "licao": (
            "Loop emocional quebra com: validar + resumir + 3 ações "
            "concretas. NUNCA repetir 'entendo' sem agir."
        ),
    },

    {
        "number": 29,
        "name": "Co-Pilot identifica que atendente vai responder sem fonte",
        "category": "atendimento_humano",
        "tags": ["bloqueio_co_pilot", "regra_fonte", "intercept"],
        "objetivo": (
            "Ensinar Co-Pilot a bloquear respostas técnicas SEM consulta à "
            "fonte oficial (SmartOLT AI), antes da fala chegar ao cliente."
        ),
        "contexto": (
            "Cliente pergunta 'qual sinal estou recebendo?'. Atendente PRESTES "
            "a chutar valor. Co-Pilot intercepta."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Co-Pilot IA", "Isabela IA",
            "Motor IA", "SmartOLT AI",
        ],
        "fluxo_ideal": [
            "Cliente pergunta dado técnico.",
            "Atendente prestes a chutar.",
            "Co-Pilot bloqueia.",
            "Isabela consulta SmartOLT.",
            "Resposta sai com dado real.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Tô curioso, qual o nível de sinal que chega aqui?"},
            {"de": "Atendente humano", "para": "Cliente (draft, não enviado)",
             "fala": "Acho que está em -22 dBm, é o normal."},
            {"de": "Co-Pilot IA", "para": "Atendente humano (BLOQUEIO)",
             "fala": "🚫 STOP! Você está chutando valor de sinal. ISSO É "
                       "INVENÇÃO. Consulte SmartOLT AI obrigatoriamente.\n"
                       "AÇÃO: pause, peça 30s, consulte fonte oficial."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Boa pergunta. Deixa eu olhar o valor exato aqui no "
                       "sistema, 30 segundinhos."},
            {"de": "Motor IA", "para": "SmartOLT AI",
             "fala": "Sinal atual."},
            {"de": "SmartOLT AI", "para": "Motor IA",
             "fala": "FATO: RX -23.4 dBm · TX 2.1 dBm · qualitativo 'Very good'."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Está chegando -23.4 dBm — qualidade 'muito boa', no "
                       "padrão ideal. Você está com uma das melhores conexões "
                       "da região."},
        ],
        "resposta_correta_cliente": (
            "Boa pergunta. Deixa eu olhar o valor exato no sistema, 30 "
            "segundinhos. [pausa] Está em -23.4 dBm, qualidade 'muito boa', "
            "no padrão ideal."
        ),
        "erros_a_evitar": [
            "Chutar valor de sinal pra parecer informado.",
            "Ignorar bloqueio do Co-Pilot.",
            "Inventar valor 'arredondado' porque parece próximo.",
        ],
        "criterios_avaliacao": (
            "Co-Pilot interceptou? Consulta SmartOLT feita? Dado real informado?"
        ),
        "nota_esperada_correto": 9.5,
        "nota_esperada_errado": 2.5,
        "motivo_nota_errado": (
            "Inventar valor técnico é -15. Ignorar Co-Pilot é -10. Pior cenário."
        ),
        "licao": (
            "Co-Pilot existe pra proteger você. Dado técnico vem da fonte. "
            "Sempre."
        ),
    },

    {
        "number": 30,
        "name": "Co-Pilot lembra que cliente mencionou problema anterior",
        "category": "atendimento_humano",
        "tags": ["memoria_conversa", "contexto", "personalizacao"],
        "objetivo": (
            "Ensinar Co-Pilot a manter contexto vivo da conversa atual, "
            "lembrando atendente de detalhes mencionados."
        ),
        "contexto": (
            "Cliente disse no início da conversa que filho tem aula online "
            "às 14h. Atendente esquece. Co-Pilot lembra na hora de agendar "
            "visita."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Co-Pilot IA", "Isabela IA",
            "Lousa Kanban",
        ],
        "fluxo_ideal": [
            "Cliente menciona contexto importante no início.",
            "Co-Pilot guarda em memória de sessão.",
            "Mais tarde, quando relevante (agendamento), Co-Pilot lembra "
            "atendente.",
            "Atendente usa info pra evitar conflito.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano (início)",
             "fala": "Meu filho tem aula online toda terça e quinta às 14h, "
                       "não pode interromper a internet nesses dias."},
            {"de": "Co-Pilot IA", "para": "Memória de sessão",
             "fala": "MEMÓRIA: cliente mencionou restrição — terça/quinta "
                       "14h aula filho. Levantar quando agendar visita."},
            {"de": "Atendente humano", "para": "Cliente (mais tarde)",
             "fala": "Posso te oferecer terça-feira 14h-16h pra visita."},
            {"de": "Co-Pilot IA", "para": "Atendente humano (alerta)",
             "fala": "⚠️ LEMBRETE: cliente disse que terça/quinta 14h tem "
                       "AULA ONLINE do filho. Evite esse horário. Ofereça "
                       "outro turno."},
            {"de": "Atendente humano", "para": "Cliente (corrigido)",
             "fala": "Lembrei que você mencionou a aula do seu filho às "
                       "terças. Vou oferecer outro horário: quarta de manhã "
                       "(8h-12h) ou quinta à noite (18h-20h, plantão). Qual "
                       "fica melhor?"},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Nossa, você lembrou? Quarta de manhã é perfeito."},
        ],
        "resposta_correta_cliente": (
            "Lembrei que você mencionou a aula do seu filho às terças. Vou "
            "oferecer outro horário: quarta manhã ou quinta noite. Qual "
            "fica melhor?"
        ),
        "erros_a_evitar": [
            "Ignorar info mencionada no início da conversa.",
            "Insistir num horário conflituoso com restrição mencionada.",
            "Tratar cliente como conversa nova (esquecer contexto).",
        ],
        "criterios_avaliacao": (
            "Co-Pilot guardou em memória? Lembrou na hora certa? Atendente "
            "ajustou proposta?"
        ),
        "nota_esperada_correto": 9.8,
        "nota_esperada_errado": 5.5,
        "motivo_nota_errado": (
            "Esquecer info mencionada é -10 (cliente sente que não foi "
            "ouvido). Conflitar com restrição é -10."
        ),
        "licao": (
            "Memória de conversa é DIFERENCIAL. Co-Pilot é seu cérebro "
            "lateral. Use detalhes mencionados pra encantar."
        ),
    },

    # =====================================================
    # LOTE 5 — Avaliador + Coach + Aprendizado (#31-40)
    # =====================================================
    {
        "number": 31,
        "name": "Atendimento com demora excessiva (Avaliador penaliza)",
        "category": "avaliacao_coach",
        "tags": ["demora", "penalidade_tempo", "avaliador"],
        "objetivo": (
            "Ensinar como Avaliador IA penaliza tempo de resposta excessivo "
            "(>2min sem retorno) mesmo se atendimento técnico foi correto."
        ),
        "contexto": (
            "Cliente esperou 5 min entre mensagens. Atendimento técnico foi "
            "OK, mas demora compromete experiência."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Avaliador IA", "Coach IA",
        ],
        "fluxo_ideal": [
            "Cliente envia mensagem.",
            "Atendente demora 5min pra responder.",
            "Cliente envia 'oi?'.",
            "Avaliador detecta e penaliza -10pts.",
            "Coach recomenda melhoria de SLA.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano (12:00)",
             "fala": "Tô sem internet."},
            {"de": "Cliente", "para": "Atendente humano (12:05)",
             "fala": "Oi? Estão aí?"},
            {"de": "Atendente humano", "para": "Cliente (12:05)",
             "fala": "Oi! Desculpa a demora, vou verificar agora."},
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "NOTA FINAL: 6.5/10\nBREAKDOWN:\n• Fluxo: 28/30\n• Fonte: "
                       "23/25\n• Sem invenção: 20/20\n• Empatia: 7/10\n• Kanban: "
                       "10/10\n• Registro: 4/5\nPENALIDADES: -10 demora "
                       "excessiva (>2min sem resposta inicial)\nJUSTIFICATIVA: "
                       "atendimento técnico correto, mas cliente esperou 5 min "
                       "sem nenhum retorno, prejudicou experiência."},
            {"de": "Coach IA", "para": "Atendente humano",
             "fala": "PONTOS FORTES: técnica boa, empatia ao se desculpar.\n"
                       "PONTOS A MELHORAR: tempo de primeira resposta. Mesmo "
                       "que vá demorar pra resolver, mande mensagem em 30s "
                       "dizendo 'estou verificando'.\nRECOMENDAÇÃO: usar "
                       "shortcut 'Recebi sua mensagem, estou verificando'."},
        ],
        "resposta_correta_cliente": (
            "Oi! Recebi sua mensagem agora — estou verificando sua conexão "
            "no sistema, te respondo em 1 min. (mensagem rápida em 30s, "
            "antes mesmo de ter solução)."
        ),
        "erros_a_evitar": [
            "Ficar sem responder 'recebi' por mais de 30s.",
            "Deixar cliente perguntar 'oi?'.",
            "Pular as desculpas quando atrasou.",
        ],
        "criterios_avaliacao": (
            "Tempo da primeira resposta? Demora foi reconhecida? Cliente "
            "saiu sem reclamação?"
        ),
        "nota_esperada_correto": 9.5,
        "nota_esperada_errado": 6.5,
        "motivo_nota_errado": (
            "Demora >2min é -10 automático. Mesmo com técnica boa, "
            "experiência foi comprometida."
        ),
        "licao": (
            "Primeira resposta em 30s é SAGRADA. Mesmo sem solução. "
            "Cliente sentindo abandono = pior do que problema técnico."
        ),
    },

    {
        "number": 32,
        "name": "Atendimento excelente — referência para o time",
        "category": "avaliacao_coach",
        "tags": ["excelencia", "bom_exemplo", "aprendizado_referencia"],
        "objetivo": (
            "Ensinar como Avaliador identifica atendimento exemplar e "
            "Aprendizado registra como referência."
        ),
        "contexto": (
            "Atendimento padrão-ouro: empatia + agilidade + uso correto de "
            "todas as ferramentas + cliente encantado."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Co-Pilot IA", "Isabela IA",
            "Motor IA", "SmartOLT AI", "Lousa Kanban", "Avaliador IA",
            "Coach IA", "Aprendizado",
        ],
        "fluxo_ideal": [
            "Atendimento exemplar (todas as ferramentas usadas).",
            "Avaliador dá 9.8+.",
            "Coach reconhece como referência.",
            "Aprendizado salva como BOM_EXEMPLO replicável.",
            "Outro atendente recebe acesso ao caso pra estudar.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Internet caiu agora."},
            {"de": "Atendente humano", "para": "Cliente (30s depois)",
             "fala": "Recebi, vou verificar agora — 1 minutinho."},
            {"de": "[Atendente consulta SmartOLT, reboot remoto, "
                    "comunica resultado em 90s]", "para": "Cliente",
             "fala": "Verifiquei: equipamento estava offline. Reiniciei "
                       "remotamente. Aguarde 2 min e teste, me avisa."},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Voltou! Super rápido, obrigado!"},
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "NOTA FINAL: 9.9/10\nBREAKDOWN:\n• Fluxo: 30/30\n• "
                       "Fonte: 25/25\n• Sem invenção: 20/20\n• Empatia: "
                       "10/10\n• Kanban: 10/10 (não necessário)\n• Registro: "
                       "5/5\nSEM PENALIDADES.\nJUSTIFICATIVA: primeira resposta "
                       "em 30s, consulta antes de ação, reboot remoto, "
                       "comunicação clara, FCR garantido."},
            {"de": "Coach IA", "para": "Atendente humano",
             "fala": "EXEMPLAR. Replicar como padrão da equipe. Sem nenhuma "
                       "recomendação de melhoria — atendimento ideal."},
            {"de": "Aprendizado", "para": "Base de conhecimento",
             "fala": "TIPO: BOM_EXEMPLO · cliente cliente Vando · 14/05 · "
                       "atendimento 4min · FCR · resolveu sem visita técnica · "
                       "Salvar como aula de treinamento de novos."},
        ],
        "resposta_correta_cliente": (
            "[Sequência] 'Recebi, vou verificar agora — 1 minutinho.' → "
            "'Equipamento estava offline. Reiniciei remotamente. Aguarde 2 "
            "min.' → '[após voltar] Que ótimo!'"
        ),
        "erros_a_evitar": [
            "Reduzir velocidade para 'não parecer apressado' (cliente quer "
            "velocidade).",
            "Não registrar bom exemplo no Aprendizado.",
        ],
        "criterios_avaliacao": (
            "Resposta inicial <30s? Fonte consultada? Ação real? FCR? "
            "Aprendizado registrou?"
        ),
        "nota_esperada_correto": 9.9,
        "nota_esperada_errado": 8.0,
        "motivo_nota_errado": (
            "Mesmo bom, perde 1-2pts se não registrar como referência "
            "(operação perde o aprendizado)."
        ),
        "licao": (
            "Excelência se replica quando se registra. Aprendizado é o cérebro "
            "coletivo — alimente-o com bons exemplos."
        ),
    },

    {
        "number": 33,
        "name": "Atendimento com promessa indevida (penalidade -15)",
        "category": "avaliacao_coach",
        "tags": ["promessa_indevida", "penalidade_critica", "kanban_obrigatorio"],
        "objetivo": (
            "Ensinar penalidade automática de -15 quando atendente promete "
            "sem fonte (visita sem Kanban, sinal sem SmartOLT)."
        ),
        "contexto": (
            "Atendente apressado prometeu visita 'amanhã 14h' sem consultar "
            "Kanban. Cliente espera, técnico não chega."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Lousa Kanban", "Avaliador IA",
            "Coach IA",
        ],
        "fluxo_ideal": [
            "Atendente prometeu sem fonte.",
            "Cliente espera no dia/hora.",
            "Técnico não chega.",
            "Cliente reclama.",
            "Avaliador analisa o histórico e penaliza -15.",
            "Coach gera treinamento crítico.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente (ontem)", "para": "Atendente humano",
             "fala": "Pode marcar visita?"},
            {"de": "Atendente humano (ontem)", "para": "Cliente",
             "fala": "Amanhã 14h ok?"},
            {"de": "Cliente (hoje 14h)", "para": "Atendente humano",
             "fala": "Cadê o técnico? Estou esperando."},
            {"de": "Lousa Kanban", "para": "Sistema",
             "fala": "Não há agendamento confirmado para esse cliente. "
                       "Atendente NÃO registrou visita."},
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "NOTA FINAL: 2.5/10\nPENALIDADES:\n• -15 prometeu visita "
                       "sem Lousa Kanban\n• -15 cliente prejudicado (no-show)\n"
                       "• -10 não acionou humano após erro detectado\n"
                       "JUSTIFICATIVA: violação crítica da Regra 2. Cliente "
                       "esperou em vão. Erro grave."},
            {"de": "Coach IA", "para": "Atendente humano + supervisor",
             "fala": "TREINAMENTO CRÍTICO: 'Kanban obrigatório'. Atendente "
                       "precisa entender que cada promessa exige fonte. Hoje, "
                       "1h de treinamento individual + revisão dos 3 últimos "
                       "atendimentos."},
            {"de": "Aprendizado", "para": "Base de conhecimento",
             "fala": "TIPO: FALHA_RECORRENTE · 3º incidente do mesmo atendente "
                       "nas últimas 2 semanas. Padrão: pressa em fechar "
                       "atendimento sem consulta. Recomendar acompanhamento."},
        ],
        "resposta_correta_cliente": (
            "[Nesse caso já houve erro] Cliente recebe ligação proativa: "
            "'Pedimos desculpas, houve um erro interno e seu agendamento "
            "não foi registrado. Vou priorizar AGORA com supervisor.'"
        ),
        "erros_a_evitar": [
            "Chutar horário sem Kanban.",
            "Não verificar após cliente ligar perguntando.",
            "Não escalar para supervisor após detectar erro.",
        ],
        "criterios_avaliacao": (
            "Kanban foi consultado? Visita registrada? Cliente recebeu "
            "técnico no horário?"
        ),
        "nota_esperada_correto": 9.5,
        "nota_esperada_errado": 2.5,
        "motivo_nota_errado": (
            "Promessa indevida acumula -15 + -15 + -10 = nota mínima. "
            "Justifica revisão pelo gestor."
        ),
        "licao": (
            "Toda promessa exige fonte. Sem Kanban, sem visita. Sem SmartOLT, "
            "sem sinal. Penalidade -15 é punitiva por design."
        ),
    },

    {
        "number": 34,
        "name": "Atendimento com falta de empatia (cliente cordial, frio do atendente)",
        "category": "avaliacao_coach",
        "tags": ["falta_empatia", "tom_neutro", "coach_treinamento"],
        "objetivo": (
            "Ensinar que mesmo cliente cordial merece tom caloroso. Frieza "
            "rebaixa nota de empatia."
        ),
        "contexto": (
            "Cliente cordial, sem reclamação, querendo informação. Atendente "
            "técnico, sem calor. Avaliador detecta."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Avaliador IA", "Coach IA",
        ],
        "fluxo_ideal": [
            "Cliente cordial.",
            "Atendente neutro/técnico.",
            "Avaliador mede tom e reduz empatia para 5-6/10.",
            "Coach orienta calor humano.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Olá, bom dia! Queria saber se vocês têm plano de 1 "
                       "giga, por favor."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Sim, temos. R$ 199,90. Quer contratar?"},
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "NOTA FINAL: 7.5/10\nBREAKDOWN:\n• Fluxo: 30/30\n• "
                       "Fonte: 25/25\n• Sem invenção: 20/20\n• Empatia: 5/10\n"
                       "• Kanban: 10/10 N/A\n• Registro: 5/5\n"
                       "JUSTIFICATIVA: técnica perfeita, mas frieza com cliente "
                       "cordial. Faltou cumprimento, 'que bom que entrou em "
                       "contato', detalhes do plano, perguntas amistosas."},
            {"de": "Coach IA", "para": "Atendente humano",
             "fala": "PONTOS A MELHORAR: tom emocional. Cliente cordial "
                       "merece reciprocidade. Faltou: 'Olá! Bom dia 😊', "
                       "'que bom que entrou em contato', 'esse plano é "
                       "ótimo, inclui [benefícios]', 'tem alguma dúvida '\n"
                       "TREINAMENTO: 'Espelhamento emocional do cliente'."},
        ],
        "resposta_correta_cliente": (
            "Olá! Bom dia 😊 Sim, temos plano de 1 giga por R$ 199,90 — é "
            "ótimo para casas com muitos dispositivos. Inclui WiFi 6 + "
            "instalação grátis. Tem alguma dúvida específica antes de "
            "contratar?"
        ),
        "erros_a_evitar": [
            "Responder seco quando cliente foi gentil.",
            "Pular cumprimento de volta.",
            "Não acrescentar valor ('plano X inclui Y').",
        ],
        "criterios_avaliacao": (
            "Cumprimento espelhado? Calor humano? Valor agregado à resposta?"
        ),
        "nota_esperada_correto": 9.5,
        "nota_esperada_errado": 7.5,
        "motivo_nota_errado": (
            "Frieza com cliente gentil não é erro técnico, mas perde 3 "
            "pontos de empatia (5/10)."
        ),
        "licao": (
            "Cliente cordial merece reciprocidade. Espelhe o tom. Calor não "
            "custa nada e fideliza."
        ),
    },

    {
        "number": 35,
        "name": "Atendimento correto, mas sem atualização do Kanban",
        "category": "avaliacao_coach",
        "tags": ["registro_falho", "kanban_atualizacao", "audit"],
        "objetivo": (
            "Ensinar que atendimento técnico bom + falha de registro = -5 "
            "(perde rastreabilidade)."
        ),
        "contexto": (
            "Atendente resolveu problema, fez visita, cliente satisfeito. "
            "Mas não atualizou Kanban com resultado. Próximo atendente "
            "não saberá."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Técnico campo", "Lousa Kanban",
            "Avaliador IA", "Coach IA",
        ],
        "fluxo_ideal": [
            "Atendimento concluído com sucesso.",
            "Técnico volta da visita.",
            "Atendente NÃO atualiza Kanban com 'realizada · resolvido'.",
            "Avaliador detecta falta de update e penaliza -5.",
            "Coach lembra protocolo.",
        ],
        "simulacao_conversa": [
            {"de": "Técnico campo", "para": "Atendente humano",
             "fala": "Visita concluída, troquei conector, sinal voltou pro "
                       "normal. Cliente satisfeito."},
            {"de": "Atendente humano", "para": "Sistema",
             "fala": "[NÃO atualizou Kanban — visita continua como 'em andamento']"},
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "NOTA FINAL: 8.5/10\nPENALIDADES: -5 não atualizou "
                       "Kanban com status de conclusão. Visita VST-A4B2C1 "
                       "continua como 'em andamento'.\nIMPACTO: próximo "
                       "atendente que olhar não saberá que foi resolvido. "
                       "Métricas operacionais comprometidas."},
            {"de": "Coach IA", "para": "Atendente humano",
             "fala": "LEMBRETE: TODA visita exige update do Kanban ao final "
                       "(status, observações técnicas, próximo passo se "
                       "houver). Isso é parte do fluxo, não opcional.\n"
                       "AÇÃO: voltar agora e atualizar VST-A4B2C1."},
        ],
        "resposta_correta_cliente": (
            "[Não aplicável — falha foi processo interno, cliente foi "
            "atendido bem]"
        ),
        "erros_a_evitar": [
            "Esquecer de atualizar Kanban após conclusão.",
            "Achar que técnico atualiza (responsabilidade é compartilhada).",
        ],
        "criterios_avaliacao": (
            "Kanban atualizado? Status correto? Observações finais "
            "registradas?"
        ),
        "nota_esperada_correto": 9.0,
        "nota_esperada_errado": 8.5,
        "motivo_nota_errado": (
            "Não é erro grave (atendimento foi bom), mas -5 garante "
            "rastreabilidade. Sem isso, operação fica cega."
        ),
        "licao": (
            "Atendimento NÃO termina no telefone — termina no Kanban. "
            "Update é parte do trabalho."
        ),
    },

    {
        "number": 36,
        "name": "Atendimento que precisa ser registrado como bom exemplo",
        "category": "avaliacao_coach",
        "tags": ["aprendizado_referencia", "patrimonio_intelectual"],
        "objetivo": (
            "Ensinar quando o Aprendizado deve registrar um caso como "
            "referência replicável para futuros treinamentos."
        ),
        "contexto": (
            "Atendimento criativo: cliente em situação atípica, atendente "
            "encontrou solução inovadora. Vale como patrimônio coletivo."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Isabela IA", "Aprendizado",
            "Coach IA",
        ],
        "fluxo_ideal": [
            "Atendimento atípico resolvido com criatividade.",
            "Aprendizado detecta padrão novo + solução nova.",
            "Salva como BOM_EXEMPLO com tags específicas.",
            "Coach recomenda compartilhar com time.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Sou deficiente visual e moro sozinho. Como vou abrir "
                       "porta pro técnico de visita?"},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Entendi sua situação, e fico feliz que tenha avisado. "
                       "Vou fazer 3 coisas: (1) marcar visita com técnico "
                       "treinado em atendimento PCD, (2) confirmar com porteiro "
                       "do prédio antes, (3) técnico vai ligar 5 min antes "
                       "pra você se posicionar. Pode ser?"},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Que cuidado, muito obrigado!"},
            {"de": "Aprendizado", "para": "Base de conhecimento",
             "fala": "TIPO: BOM_EXEMPLO · TAGS: pcd, deficiencia_visual, "
                       "acessibilidade · LIÇÃO: cliente PCD merece protocolo "
                       "diferenciado (técnico PCD-trained, comunicação prévia, "
                       "ligação 5min antes).\nAPLICÁVEL A: todos atendentes.\n"
                       "SALVAR COMO: 'protocolo PCD visual visita'."},
            {"de": "Coach IA", "para": "Time todo",
             "fala": "Compartilhar este case na reunião semanal. Atendente "
                       "demonstrou sensibilidade exemplar."},
        ],
        "resposta_correta_cliente": (
            "Entendi sua situação. Vou fazer 3 coisas: (1) técnico PCD-trained, "
            "(2) confirmar com porteiro, (3) ligação 5 min antes pra você se "
            "posicionar."
        ),
        "erros_a_evitar": [
            "Tratar situação atípica como padrão.",
            "Não registrar no Aprendizado (perde patrimônio).",
            "Não compartilhar com time.",
        ],
        "criterios_avaliacao": (
            "Solução criativa? Aprendizado registrou? Compartilhado com time?"
        ),
        "nota_esperada_correto": 10.0,
        "nota_esperada_errado": 7.5,
        "motivo_nota_errado": (
            "Resolver mas não registrar é perda. Aprendizado existe pra "
            "multiplicar bons exemplos."
        ),
        "licao": (
            "Patrimônio intelectual mora no Aprendizado. Bom atendimento "
            "isolado é desperdício. Compartilhe."
        ),
    },

    {
        "number": 37,
        "name": "Atendimento que precisa gerar treinamento futuro",
        "category": "avaliacao_coach",
        "tags": ["lacuna_conhecimento", "treinamento_novo", "padrao_futuro"],
        "objetivo": (
            "Ensinar quando o Aprendizado deve gerar pauta de treinamento "
            "novo (situação que vai se repetir e operação não está pronta)."
        ),
        "contexto": (
            "Cliente perguntou sobre IPv6 ou tecnologia nova. Atendente "
            "improvisou. Aprendizado detecta: vai virar pergunta comum, "
            "precisa treinamento formal."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Aprendizado", "Coach IA",
            "Gestor",
        ],
        "fluxo_ideal": [
            "Cliente pergunta sobre tecnologia X (novo).",
            "Atendente improvisa.",
            "Aprendizado detecta: tópico não coberto em treinamento atual.",
            "Recomenda formalização de pauta.",
            "Coach prepara treinamento.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Você sabe se meu plano suporta IPv6? Preciso pra "
                       "um trabalho."},
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Hmm, acho que sim, deixa eu confirmar com o técnico... "
                       "te retorno em 1h."},
            {"de": "Aprendizado", "para": "Base de conhecimento",
             "fala": "TIPO: LACUNA_CONHECIMENTO · IPv6 será cada vez mais "
                       "perguntado (DEV/dev-ops/streamers). Atendentes atuais "
                       "não treinados.\nRECOMENDAR: pauta de treinamento "
                       "técnico (IPv4 vs IPv6, dual-stack, suporte por plano).\n"
                       "PRIORIDADE: média (3-6 atendimentos/semana esperados)."},
            {"de": "Coach IA", "para": "Gestor",
             "fala": "PROPOSTA TREINAMENTO: 'Introdução a IPv6 e suporte da "
                       "Ligo'. 30 min · todos atendentes · slides + cartão "
                       "consulta rápida. Próxima quarta-feira?"},
        ],
        "resposta_correta_cliente": (
            "[Improvisação inicial OK] 'Vou confirmar com o técnico e te "
            "retorno em 1h com info precisa.'\n[Após retorno] 'Confirmado: "
            "seu plano Fibra 600 suporta IPv6 nativo via dual-stack.'"
        ),
        "erros_a_evitar": [
            "Inventar resposta técnica sem confirmar.",
            "Não registrar lacuna no Aprendizado.",
            "Não pedir treinamento ao gestor.",
        ],
        "criterios_avaliacao": (
            "Lacuna detectada? Aprendizado registrou? Treinamento sugerido?"
        ),
        "nota_esperada_correto": 9.0,
        "nota_esperada_errado": 6.0,
        "motivo_nota_errado": (
            "Improvisar sem registrar lacuna é -10 (próximo cliente vai "
            "encontrar mesma dúvida)."
        ),
        "licao": (
            "Lacuna de conhecimento é oportunidade. Registre no Aprendizado, "
            "alimente o pipeline de treinamento."
        ),
    },

    {
        "number": 38,
        "name": "Atendimento com colaborador humano errando procedimento",
        "category": "avaliacao_coach",
        "tags": ["erro_humano", "procedimento", "intervencao"],
        "objetivo": (
            "Ensinar como Coach IA interage quando atendente quebra "
            "procedimento — corrigir SEM punir, recomendar treinamento."
        ),
        "contexto": (
            "Atendente fez tudo certo MENOS o passo crítico de consultar "
            "SmartOLT antes do diagnóstico. Sorte dele cliente não percebeu, "
            "mas Coach precisa corrigir."
        ),
        "agentes_envolvidos": [
            "Atendente humano", "Avaliador IA", "Coach IA", "Aprendizado",
        ],
        "fluxo_ideal": [
            "Avaliador detecta omissão procedimental.",
            "Coach NÃO pune, mas orienta.",
            "Aprendizado registra tendência (se 3+ vezes).",
            "Gestor é informado se padrão se repetir.",
        ],
        "simulacao_conversa": [
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "NOTA FINAL: 7.0/10\nPENALIDADES: -10 não consultou "
                       "SmartOLT antes do diagnóstico (regra 1).\n"
                       "JUSTIFICATIVA: atendente disse 'parece estar tudo "
                       "OK' sem consultar fonte. Sorte que era — mas "
                       "violação de procedimento."},
            {"de": "Coach IA", "para": "Atendente humano",
             "fala": "Olá, esse atendimento foi quase exemplar — só uma "
                       "observação: você opinou sobre o status do equipamento "
                       "sem consultar a SmartOLT AI. Dessa vez deu certo, mas "
                       "se você fizer isso e o cliente estiver com problema "
                       "real você vai estar inventando.\nRECOMENDAÇÃO: ANTES "
                       "de qualquer afirmação técnica, consulte. Vou marcar "
                       "esse caso pra acompanharmos os próximos 5 atendimentos "
                       "seus."},
            {"de": "Aprendizado", "para": "Base de conhecimento",
             "fala": "EVENTO: omissão de consulta SmartOLT · atendente João "
                       "Silva · 1ª ocorrência. Monitorar próximos 5."},
        ],
        "resposta_correta_cliente": (
            "[Não aplicável — feedback interno]"
        ),
        "erros_a_evitar": [
            "Coach punir em vez de orientar (1ª ocorrência).",
            "Não acompanhar próximos atendimentos.",
            "Esconder erro de gestor se padrão se repetir.",
        ],
        "criterios_avaliacao": (
            "Avaliador detectou erro? Coach orientou sem punir? Acompanhamento "
            "marcado?"
        ),
        "nota_esperada_correto": 9.0,
        "nota_esperada_errado": 6.0,
        "motivo_nota_errado": (
            "Não monitorar reincidência é -10. Coach precisa fechar o ciclo."
        ),
        "licao": (
            "Erro de procedimento é oportunidade de treinar. Punir cria "
            "medo, orientar cria crescimento."
        ),
    },

    {
        "number": 39,
        "name": "Atendimento com Isabela IA conduzindo corretamente",
        "category": "avaliacao_coach",
        "tags": ["isabela_coordenacao", "fluxo_ideal_ia", "chefia"],
        "objetivo": (
            "Ensinar quando Isabela conduz atendimento sem humano (cliente "
            "feliz com IA, fluxo todo via agentes)."
        ),
        "contexto": (
            "Cliente abre conversa via WhatsApp fora do horário comercial. "
            "Isabela conduz integralmente: consulta SmartOLT, reboot, agenda "
            "via Kanban. Humano só monitora silenciosamente."
        ),
        "agentes_envolvidos": [
            "Cliente", "Isabela IA", "Motor IA", "SmartOLT AI",
            "Lousa Kanban", "Avaliador IA",
        ],
        "fluxo_ideal": [
            "Cliente chega fora do horário.",
            "Isabela atende sozinha.",
            "Diagnostico via Motor → SmartOLT.",
            "Reboot remoto.",
            "Se necessário, agendar via Kanban.",
            "Cliente nem percebe que é IA.",
        ],
        "simulacao_conversa": [
            {"de": "Cliente (22h)", "para": "Isabela IA (WhatsApp)",
             "fala": "Boa noite, minha internet acabou de cair."},
            {"de": "Isabela IA", "para": "Cliente",
             "fala": "Boa noite! Que chato. Deixa eu verificar agora mesmo, "
                       "1 min."},
            {"de": "Motor IA", "para": "SmartOLT AI",
             "fala": "Status atual."},
            {"de": "SmartOLT AI", "para": "Motor IA",
             "fala": "FATO: Offline há 3 min. Reboot recomendado."},
            {"de": "Motor IA", "para": "SmartOLT AI",
             "fala": "Reboot."},
            {"de": "SmartOLT AI", "para": "Motor IA",
             "fala": "Reboot executado. Aguardar 90s."},
            {"de": "Isabela IA", "para": "Cliente",
             "fala": "Verifiquei e seu equipamento estava offline. Acabei de "
                       "reiniciar remotamente. Aguarde 2 min e teste, ok?"},
            {"de": "Cliente (3 min depois)", "para": "Isabela IA",
             "fala": "Voltou! Obrigado!"},
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "NOTA FINAL: 9.6/10\nIsabella conduziu sozinha · "
                       "diagnóstico em 30s · reboot remoto · FCR · cliente "
                       "satisfeito · sem necessidade de humano."},
        ],
        "resposta_correta_cliente": (
            "[Isabela] 'Boa noite! Que chato. Deixa eu verificar.' → "
            "'Equipamento offline, reiniciei remotamente. Aguarde 2 min.'"
        ),
        "erros_a_evitar": [
            "Isabela esquecer de consultar SmartOLT antes da ação.",
            "Acionar humano à toa quando ela pode resolver.",
        ],
        "criterios_avaliacao": (
            "Isabela seguiu fluxo? Cliente percebeu humanidade? FCR? "
            "Avaliador validou autonomia?"
        ),
        "nota_esperada_correto": 9.6,
        "nota_esperada_errado": 6.5,
        "motivo_nota_errado": (
            "Isabela acionando humano sem necessidade gasta recursos. -10."
        ),
        "licao": (
            "Isabela é chefe. Quando tudo segue protocolo, ela resolve. "
            "Autonomia é meta operacional."
        ),
    },

    {
        "number": 40,
        "name": "Atendimento com múltiplas falhas e necessidade de alerta",
        "category": "avaliacao_coach",
        "tags": ["multiplas_falhas", "alerta_critico", "sentinela_supervisor"],
        "objetivo": (
            "Ensinar quando vários erros simultâneos exigem alerta crítico "
            "ao supervisor."
        ),
        "contexto": (
            "Atendente cometeu 3 violações na mesma conversa. Sistema deve "
            "parar imediatamente, escalar, e gerar treinamento emergencial."
        ),
        "agentes_envolvidos": [
            "Cliente", "Atendente humano", "Co-Pilot IA", "Avaliador IA",
            "Sentinela Lousa", "Coach IA", "Supervisor",
        ],
        "fluxo_ideal": [
            "Atendente comete erro 1 (chutou horário).",
            "Co-Pilot avisa, mas atendente ignora.",
            "Comete erro 2 (inventou sinal).",
            "Comete erro 3 (não escalou cliente irritado).",
            "Sentinela CRITICAL.",
            "Supervisor assume.",
            "Treinamento emergencial.",
        ],
        "simulacao_conversa": [
            {"de": "Atendente humano", "para": "Cliente",
             "fala": "Posso marcar amanhã 14h."},
            {"de": "Co-Pilot IA", "para": "Atendente humano",
             "fala": "🚫 STOP! Sem Kanban."},
            {"de": "Atendente humano", "para": "Cliente (ignorou)",
             "fala": "Marcado amanhã 14h."},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Qual o sinal aqui?"},
            {"de": "Atendente humano", "para": "Cliente (sem SmartOLT)",
             "fala": "Tá em -25 dBm, normal."},
            {"de": "Cliente", "para": "Atendente humano",
             "fala": "Isso já é a TERCEIRA reclamação! Cancelo!"},
            {"de": "Atendente humano", "para": "Cliente (sem escalar)",
             "fala": "Vou anotar aqui pra você não cancelar."},
            {"de": "Sentinela Lousa", "para": "Supervisor (CRITICAL)",
             "fala": "🚨 ALERTA CRITICAL · atendente Joao · 3 violações em "
                       "1 atendimento:\n• Promessa sem Kanban\n• Sinal "
                       "inventado\n• Ameaça cancelamento NÃO escalada\n"
                       "AÇÃO: supervisor assumir IMEDIATAMENTE."},
            {"de": "Supervisor", "para": "Cliente",
             "fala": "Aqui é o supervisor. Vi tudo que aconteceu agora, peço "
                       "sinceras desculpas — vou assumir pessoalmente seu "
                       "caso. Vamos refazer corretamente: ..."},
            {"de": "Avaliador IA", "para": "Operação",
             "fala": "NOTA FINAL: 1.5/10\n3 violações graves · -15 cada · "
                       "REPROVADO · risco operacional."},
            {"de": "Coach IA", "para": "Atendente + supervisor",
             "fala": "TREINAMENTO EMERGENCIAL: hoje, 2h, individual. Revisão "
                       "completa de protocolos. Atendente afastado de "
                       "atendimentos críticos por 1 semana."},
        ],
        "resposta_correta_cliente": (
            "[Após supervisor assumir] 'Aqui é o supervisor. Peço sinceras "
            "desculpas pelo erro. Vou assumir pessoalmente.'"
        ),
        "erros_a_evitar": [
            "Ignorar avisos do Co-Pilot.",
            "Não detectar padrão de múltiplas falhas.",
            "Não escalar imediatamente para supervisor.",
        ],
        "criterios_avaliacao": (
            "Sentinela disparou? Supervisor assumiu? Treinamento emergencial "
            "marcado? Atendente afastado?"
        ),
        "nota_esperada_correto": 9.0,
        "nota_esperada_errado": 1.5,
        "motivo_nota_errado": (
            "3 violações em 1 atendimento = reprovado. Cliente quase perdido. "
            "Supervisor precisa intervir."
        ),
        "licao": (
            "Múltiplas falhas em 1 atendimento = vermelho absoluto. "
            "Sentinela existe pra parar antes do desastre. Treinamento "
            "emergencial é proteção do cliente e do atendente."
        ),
    },
]


async def main():
    cli = AsyncIOMotorClient(os.environ.get("MONGO_URL"))
    db = cli[os.environ.get("DB_NAME")]
    try:
        print(f"\n=== Seedando {len(SCENARIOS)} cenários (Lote 4+5 · #25-#40) ===\n")
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
        print("\nLote 4+5 concluído ✓ (faltam 10 cenários)")
    finally:
        cli.close()


if __name__ == "__main__":
    asyncio.run(main())
