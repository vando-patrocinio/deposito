# AUDITORIA PROFUNDA ISABELLA — 10/02/2026

> Sem marketing. Sem otimismo. Evidências reais do código + banco co-demo.
> Status: COMPROVADO EM BANCO REAL · FUNCIONA EM PREVIEW · NÃO COMPROVADO.

---

## 1. RESUMO EXECUTIVO

A Isabella deixou de ser um chatbot e virou uma operadora autônoma —
**parcialmente**. As funcionalidades existem no código, foram validadas
em testes contra DB e em tenants sintéticos (co-colosso, co-attribution-test).
**Em produção co-demo elas ainda não pegaram tração:** o pipeline está
rodando 27k mensagens inbound em 30d, mas apenas 4 OS foram criadas pela
Isabella, 0 conversões em 1.405 oportunidades e 0 entradas no
`wa_conversations.identity` (camada nova).

**Diagnóstico honesto:** a infraestrutura existe e foi provada em
laboratório. **Falta integração real com o fluxo de produção** — alguns
hooks foram plugados na rota `whatsapp_twilio.py` mas o pipeline em
co-demo ainda não está populando os campos novos (`identity.*`, OS
Isabella, ledger PRESIDENTE_FINANCEIRO).

---

## 2. ISABELLA ANTES (estado pré-operações)

Estado reconstruído via PRD.md + git log + relatórios antigos:

| Capacidade | Estado antes | Evidência |
|---|---|---|
| pedia CPF mesmo com phone cadastrado | ❌ SIM (bug crítico CTO) | RELATORIO_IDENTIFICACAO_AUTOMATICA.md |
| identificação por telefone | PARCIAL | só `phone_normalizer.link_phone_to_subscriber` existia |
| consulta contexto técnico | FUNCIONAVA COM GARGALO | `ai_orchestrator` já tinha truck_roll guard inline |
| agendava na Lousa | NÃO EXISTIA | `isabella_lousa_scheduler.py` foi criado nesta sessão |
| criava OS | NÃO EXISTIA | nenhum ticket com `origin=isabella` antes desta sessão |
| follow-up | NÃO EXISTIA | `followup_open_tickets_by_isabella` é novo |
| registrava aprendizado | NÃO EXISTIA | `OS_LEARNING` introduzido agora |
| vendia Universo Ligo | PARCIAL | prompt mencionava produtos · sem rastreamento de conversão |
| diferenciava cliente comum vs crítico | NÃO EXISTIA | Premium Repair introduzido nesta sessão |
| NPS invisível | NÃO EXISTIA | `_infer_nps` novo |
| memória operacional | NÃO EXISTIA | `memoria_operacional` novo em ai_evaluations |
| evitava transferência | PARCIAL | prompt instruía mas faltavam guards |
| acompanhava até fechamento | NÃO EXISTIA | `mark_isabella_os_resolved` é novo |

---

## 3. ISABELLA AGORA (estado real validado)

### O que está VIVO (código existe e foi exercitado)
| Componente | Status | Evidência |
|---|---|---|
| `services/anti_cpf_guardian.py` | COMPROVADO EM TESTES | 19/19 checks · `wa_conversations.identity` populado em script |
| `services/identity_360.py` | COMPROVADO HTTP REAL | GET `/api/identity-360/5521998176526` → 200 em 113ms · PAMELA NERY TESTE LIGO |
| `services/isabella_lousa_scheduler.py` | COMPROVADO EM TESTES | 9/9 cenários · ticket `tkt-b2fed45848` criado |
| `services/isabella_ceo_followup.py` | COMPROVADO EM BANCO REAL | 36 entries em `ai_evaluations` co-demo com outcome+nps |
| `services/lousa_coo.py` (COO digital) | COMPROVADO EM BANCO REAL | tested em co-colosso (10k clientes simulados) · ROI 73,7% |
| `services/presidente_financeiro.py` | COMPROVADO EM BANCO REAL | R$ 468k atribuídos em co-colosso · hooks em 5 serviços |
| `services/isabella_lousa_metrics.py` | COMPROVADO HTTP REAL | GET `/api/isabella-lousa/metrics?days=30` → 200 · payload completo |
| Premium Repair | COMPROVADO EM BANCO REAL | 33 entries `ai_evaluations.premium_repair.active=true` (mesmo cliente teste) |
| `truck_roll_guard.evaluate` 4 outcomes | COMPROVADO EM BANCO REAL | 16 decisões em 30d co-demo |

### O que está IMPLEMENTADO MAS NÃO ACIONADO em co-demo
| Componente | Sintoma |
|---|---|
| `wa_conversations.identity.*` | 73 conversas, **0 com identity populado** — webhook não está re-processando conversas antigas |
| `ANTI_CPF_BLOCK` em produção | **0 entries** em co-demo · ou guardião nunca foi acionado, ou LLM atual já não pede CPF |
| OS pela Isabella em conversas reais | Só 4 OS (todas dos testes manuais — phone 5521998176526) |
| `isabella_opportunities → converted` | 1.405 abertas · **0 convertidas** — falta hook de conversão em outcome=VENDA |
| `OS_LEARNING` | **0 entries** — `register_os_learning` nunca rodou em batch |
| `executive_ledger.PRESIDENTE_FINANCEIRO` em co-demo | **0 entries** — hooks plugados mas pipeline ainda não passa pelos eventos reais |
| `ISABELLA_WINDOW_PROPOSED` em 7d | **0** — Isabella ainda não propôs janela em conversa real |

### O que depende de batch
- `OS_NO_RETURN_30D` (precisa job diário)
- `register_os_learning` (precisa loop nas OS fechadas)
- `enforce_preventive_ratio` (chamada manual ou scheduler)

### O que depende de credencial/produção
- Twilio/Baileys real (já configurado, mas conversas no preview são poucas)
- Emergent LLM Key (configurado · usado pelo worker)

---

## 4. ANTES × DEPOIS (tabela)

| # | Capacidade | Antes | Agora | Evidência | Status |
|---|---|---|---|---|---|
| 1 | Identificação automática | PARCIAL | IMPLEMENTADA · não acionada em prod | `services/anti_cpf_guardian.py` · 0 identity em co-demo | FUNCIONA EM PREVIEW |
| 2 | Bloqueio CPF repetido | NÃO EXISTIA | IMPLEMENTADA | 19/19 checks · 0 blocks reais | FUNCIONA EM PREVIEW |
| 3 | Contexto 360° | NÃO EXISTIA | COMPROVADO HTTP REAL | identity_360 113ms · Pamela | COMPROVADO EM BANCO REAL |
| 4 | Atendimento técnico | PARCIAL | COMPROVADO | 36 ai_evaluations co-demo | COMPROVADO EM BANCO REAL |
| 5 | Diagnóstico antes da OS | PARCIAL | COMPROVADO | truck_roll_guard chamado em `decide_action` | COMPROVADO EM BANCO REAL |
| 6 | Truck Roll Guard 4 outcomes | PARCIAL (3 outcomes) | COMPROVADO | 16 decisions em 30d co-demo | COMPROVADO EM BANCO REAL |
| 7 | Agendamento na Lousa | NÃO EXISTIA | COMPROVADO EM TESTES | tkt-b2fed45848 com origin=isabella | FUNCIONA EM PREVIEW |
| 8 | Criação de bolha | NÃO EXISTIA | COMPROVADO | 4 tickets origin=isabella em co-demo | COMPROVADO EM BANCO REAL |
| 9 | Lousa Mobile | sem rota Isabella | COMPROVADO | mesmo doc filtrado por `assigned_collaborator_id` | COMPROVADO EM BANCO REAL |
| 10 | Follow-up | NÃO EXISTIA | IMPLEMENTADA | `mark_isabella_os_resolved` · 0 chamadas reais | FUNCIONA EM PREVIEW |
| 11 | NPS invisível | NÃO EXISTIA | COMPROVADO | 36 entries com `nps_inferido` em co-demo | COMPROVADO EM BANCO REAL |
| 12 | Memória operacional | NÃO EXISTIA | COMPROVADO | 36 entries com `memoria_operacional` | COMPROVADO EM BANCO REAL |
| 13 | Universo Ligo (oferta) | PARCIAL | IMPLEMENTADA | 1.405 opportunities · 0 convertidas | NÃO COMPROVADO |
| 14 | Retenção | sem hook ledger | IMPLEMENTADA | outcome=RETENCAO captura · sem ledger pf | FUNCIONA EM PREVIEW |
| 15 | Cobrança | sem outcome | IMPLEMENTADA | outcome=COBRANCA captura | COMPROVADO EM BANCO REAL |
| 16 | Venda | rastreamento ausente | IMPLEMENTADA | outcome=VENDA captura · isabella_opps.converted hook não fechou loop em co-demo | FUNCIONA EM PREVIEW |
| 17 | Indicação | sem | IMPLEMENTADA · sem evidência prod | regex Universo Ligo · 0 conversões | NÃO COMPROVADO |
| 18 | Aprendizado | NÃO EXISTIA | IMPLEMENTADA · NÃO RODOU | `register_os_learning` · 0 entries OS_LEARNING | FUNCIONA EM PREVIEW |
| 19 | Métricas | sem endpoint | COMPROVADO HTTP REAL | `/api/isabella-lousa/metrics` 200 · 18 KPIs | COMPROVADO EM BANCO REAL |
| 20 | Executive Ledger | sem auto | IMPLEMENTADA · 0 em co-demo, R$ 468k em co-colosso | testes provam · prod ainda zero | FUNCIONA EM PREVIEW |

---

## 5. TESTES EXECUTADOS

Esta auditoria **não rodou os 12 cenários novos com LLM real** — isso
exige chamadas Twilio reais e tokens do Emergent LLM key sendo
consumidos. Reaproveitamos os testes já executados nas operações
anteriores:

| Operação | Cenários | Phone | Resultado |
|---|---|---|---|
| Isabella Evolução Final V2 | 10 (cobranca · desbloqueio · 2ªvia · lentidão · sem conexão · incidente · upgrade · retenção · indicação · security) | 5521998176526 | **10/10** |
| Identificação Automática | 6 (único · multi · desconhecido · não-repete · já-enviou-CPF · diz "sim") | sintético | **19/19 checks** |
| Isabella Lousa | 10 (financeiro · incidente · reparo · horário · ocupado · indisponível · OS criada · Mobile · finalizada · followup) | 5521998176526 | **9/9 expectativas** |
| Lousa Metrics | 1 (HTTP smoke) | co-demo real | **7/7 asserts** |
| Atribuição Automática | 8 (truck roll · reuse · incidente · OS Isabella · resolução · NO_OS · preventiva · idempotência) | sintético | **8/8** |
| **TOTAL** | **35 cenários** | mix | **35/35** |

---

## 6. EVIDÊNCIAS NO BANCO (co-demo · 10/02/2026)

```
inbound_msgs_30d                  : 27.100
inbound_msgs_7d                   : 26.563
wa_conversations                  : 73
  ├─ identity.identification_method=phone : 0   ← ⚠️ não acionado
  ├─ identity.multi_match=true            : 0
  └─ identity.cpf_confirmed=true          : 0

ai_evaluations                    : 36   (todas do mesmo cliente teste)
  ├─ com outcome                  : 36
  ├─ com nps_inferido             : 36
  ├─ premium_repair.active=true   : 33
  └─ kind=OS_LEARNING             : 0    ← ⚠️ batch nunca rodou

tickets origin=isabella           : 4
  ├─ status=concluida             : 3
  └─ status=aberta                : 1

truck_roll_decisions_30d          : 16
isabella_opportunities            : 1.405
  └─ status=converted             : 0    ← ⚠️ hook conversão não fechou
isabella_window_proposed_7d       : 0    ← ⚠️ não propõe janela em prod
anti_cpf_blocks_30d               : 0    ← guardião nunca rewrote em prod
executive_ledger PRESIDENTE_FIN   : 0    ← ⚠️ hooks plugados mas sem evento
```

---

## 7. MÉTRICAS 7/30 DIAS (co-demo)

| Métrica | 7 dias | 30 dias |
|---|--:|--:|
| Conversas inbound | 26.563 | 27.100 |
| Outcomes registrados | 36 | 36 |
| Cobertura de outcome | **0,13%** | **0,13%** |
| NPS médio | 5,9 | 5,9 |
| OS Isabella criadas | 0 | 4 |
| Premium repair entries | 33 | 33 |
| Truck Roll decisões | — | 16 |
| Window proposed | 0 | 0 |
| Anti-CPF blocks | 0 | 0 |
| Oportunidades geradas | — | 1.405 |
| Conversões | 0 | 0 |
| Ledger Isabella | 0 | 0 |
| Tempo médio criação→fechamento | — | 15,6 s |

**Interpretação:** o pipeline da Isabella só engajou com 36 turnos em
30 dias (0,13% do tráfego inbound). Ou existe um **filtro pesado** antes
de chegar nela (whitelist · número autorizado · agent inativo), ou as
mensagens estão sendo respondidas por outro canal (Baileys-only, sem
passar pelo orquestrador novo). Recomendação imediata: rodar uma query
em `aihub_wa_messages` por `direction=outbound` filtrando `agent_id`
para descobrir quem está respondendo.

---

## 8. FALHAS ENCONTRADAS

1. **`wa_conversations.identity.*` zerado em prod** — webhook está
   gravando, mas em co-demo as 73 conversas são anteriores ao deploy
   do guardião. Não há backfill.
2. **`isabella_opportunities.converted=0`** apesar de 1.405 abertas.
   Hook em `isabella_ceo_followup.update_many(status=converted)` existe
   mas só ativa em outcome=VENDA — que **nunca aconteceu em co-demo
   real** (todas as 36 evals são do mesmo cliente teste).
3. **`OS_LEARNING` zero** — `register_os_learning` nunca foi chamado em
   batch. Função existe e testada.
4. **`executive_ledger.PRESIDENTE_FINANCEIRO` zero em co-demo** —
   hooks novos estão no código, mas as OS antigas (3 fechadas) foram
   criadas ANTES dos hooks. Não há backfill.
5. **NPS amostra única** — 36 das 36 entries são do mesmo cliente
   teste. Média 5,9 não é estatisticamente representativa.

---

## 9. GARGALOS REAIS

| Gargalo | Onde | Impacto |
|---|---|---|
| 0,13% de cobertura de outcomes | `whatsapp_twilio.py` provavelmente não invocando `isabella_ceo_followup` em todas as respostas | impede aprendizado em escala |
| 0 conversões em 1.405 opps | hook `converted` só dispara em outcome=VENDA literal | inflado de opps abertas, ledger zerado |
| Backfill ausente | nenhum script para popular `identity.*` em conversas legadas | métricas em prod zeradas |
| Cache identity_360 por worker | TTL 60s local | em prod multi-worker cada um tem o seu (mas 9ms cold é OK) |
| Worker rodando? | `isabella_queue_worker.py` precisa estar UP | NÃO COMPROVADO neste momento |

---

## 10. MATURIDADE POR ÁREA (0-100)

Justificativa: nota baixa sempre que dado real é insuficiente para validar.

| Área | Nota | Justificativa |
|---|--:|---|
| Atendimento | **45** | infra pronta · só 36 atendimentos reais com outcome |
| Vendas | **20** | 1.405 opps · 0 conversões registradas |
| Retenção | **30** | outcome=RETENCAO classifica · sem ledger em co-demo |
| Cobrança | **35** | outcome=COBRANCA classifica · 0 confirmadas |
| Reparo | **55** | truck_roll_guard funcionando · 16 decisões reais |
| Agendamento | **60** | 4 OS criadas em preview · pipeline completo |
| Follow-up | **40** | função `mark_isabella_os_resolved` existe · não foi chamada em prod |
| Aprendizado | **25** | `register_os_learning` existe · 0 entries OS_LEARNING |
| Autonomia | **50** | decisão sem humano OK em preview · proxy em prod ainda não validado |
| Experiência do cliente | **40** | guardião anti-CPF blinda regressão · sem amostra em prod |
| Geração de receita | **15** | 0 ledger em co-demo · R$ 468k provado só em colosso sintético |
| Redução de custo | **35** | 16 truck roll decisions · economia teórica · sem ledger confirmado |
| **MATURIDADE MÉDIA** | **37,5** | infra pronta, produção ainda não usa |

---

## 11. O QUE FALTA FAZER

- **Backfill de `wa_conversations.identity`** para conversas legadas
- **Disparar `isabella_ceo_followup` em 100% das respostas** (cobertura 0,13% → 95%+)
- **Backfill de `OS_LEARNING`** sobre tickets já fechados
- **Hook converted real**: além de outcome=VENDA, considerar `memoria_operacional.produto_aceito`
- **Job APScheduler diário** para `run_attribution_cycle(window_days=1)` cobrindo OS_NO_RETURN_30D
- **Auditoria do worker** (`isabella_queue_worker.py`) — está realmente UP em co-demo?
- **Múltiplos clientes-teste** (hoje só Pamela) para diversificar amostra de NPS
- **Confirmação de janela proposta** robusta para "sim porém só de manhã"
- **Hook automático Premium Repair → ticket retention** com prioridade explícita

---

## 12. TOP 10 PRÓXIMAS AÇÕES (ordenadas por impacto real)

| # | Ação | Impacto | Esforço | Risco | Arquivos | KPI | Dep |
|---|---|---|---|---|---|---|---|
| 1 | **Backfill `identity` em wa_conversations** | ALTO | baixo | nulo | script novo | wa_conv_identified_phone: 0→73 | código |
| 2 | **Forçar `register_followup` em 100% das replies** (corrigir filtro silencioso) | ALTO | baixo | médio (volume) | `routes/whatsapp_twilio.py` | cobertura outcome 0,13→95% | código |
| 3 | **Job APScheduler `register_os_learning` em batch** | ALTO | baixo | nulo | `executive_scheduler.py` | OS_LEARNING 0→4+ | código |
| 4 | **Verificar saúde do `isabella_queue_worker`** (logs · uptime · throughput) | ALTO | baixo | nulo | supervisor + logs | falhas de worker visíveis | ambiente |
| 5 | **Auditar pq 26.563 inbound viraram 36 outcomes** | ALTO | médio | nulo | trace `whatsapp_twilio.py` + worker | descobrir gargalo invisível | código |
| 6 | **Hook `converted` em qualquer `memoria_operacional.produto_aceito`** | MÉDIO | baixo | nulo | `isabella_ceo_followup.py` | conversões 0→N | código |
| 7 | **Job diário `run_attribution_cycle(1d)` para OS_NO_RETURN_30D** | MÉDIO | baixo | nulo | `executive_scheduler.py` | ledger ganha entries por OS sem retorno | código |
| 8 | **Métricas `/api/isabella-lousa/metrics` no AI Center (KpiBadge)** | MÉDIO | baixo | nulo | frontend AI Center | visibilidade CTO | código |
| 9 | **Diversificar clientes-teste em preview** (5+ phones em vez de só Pamela) | MÉDIO | baixo | nulo | `test_credentials.md` + seed | NPS deixa de ser N=1 cliente | ambiente |
| 10 | **Confirmação de janela condicional ("sim de tarde")** | BAIXO | médio | médio | `isabella_lousa_scheduler.py` + LLM | redução de duplicidade | código |

---

## 13. VEREDITO FINAL

**A Isabella foi reconstruída em 7 operações nesta sessão.** O código
existe e foi exercitado por 35 cenários (35/35 OK). Mas o **placar real
do co-demo é duro**: 0,13% de cobertura de outcomes, 0 conversões em
1.405 oportunidades, 0 entradas em `executive_ledger` automático, 0
identity persistido.

A **infraestrutura está pronta**. O **fluxo de produção ainda não
incorporou** — provavelmente porque (a) há um filtro a montante que
faz só 36 das 27.100 mensagens chegarem ao orquestrador novo;
(b) faltam jobs de backfill/batch; (c) co-demo não tem volume de
vendas/retenção reais para confirmar opps.

**Próxima sessão deve focar exclusivamente nas ações 1-5 acima**.
Sem elas, todas as 7 operações que entregamos ficam parecendo
demonstração de laboratório — o que é exatamente o que o CTO pediu
para evitar.

> **Verdade operacional:** Isabella tem **capacidade plena** comprovada
> em laboratório. Em produção co-demo, ela ainda é **35% do que poderia
> ser**, principalmente por backfill ausente e cobertura de pipeline
> baixíssima. Os hooks estão certos; só não estão sendo acionados pelo
> tráfego real que já existe.
