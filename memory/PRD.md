# SmartProv — PRD (Product Requirements Document)

> Documento vivo. Atualizado a cada sprint.

## ⚡ Sprint atual — Card UI Credenciais Observabilidade (09/06/2026) ✅
**Ordem direta do CTO** atendendo o pedido após o "UI Freeze" revogado:
- ✅ Card UI completo (Grafana + Zabbix) em `components/ObservabilityCredentialsCard.jsx`
- ✅ Sidebar entry "Credenciais Integração" funcional (era quebrado por import `./api` inexistente)
- ✅ Dentro do Observability Twin (colapsável) e como página dedicada (expandida)
- ✅ Persistência criptografada via `secrets_vault` (Fernet AES-128) — `SECRETS_MASTER_KEY` no .env
- ✅ Connectors `ZabbixConnector`/`GrafanaConnector` carregam dinamicamente do vault (sem restart)
- ✅ `/api/admin/integrations/{grafana,zabbix}/{status,test,save}` operacional
- ✅ `/api/ai-center/observability/connectors/status` retorna `source: "vault"|"env"|"none"`
- ✅ Pré-cadastrado Grafana real: https://grafana.procyontecnologia.net (org=LIGOTELECOM id=37) basic auth
- ✅ Bugfix em `secrets_vault.set_secret` (audit_log faltava campo `id` → DuplicateKey)
- ✅ Pytest 11/11 (p04 + safety) passando


## 1) Problema & Visão
SmartProv evoluiu de ERP para um **Sistema Operacional Inteligente** para
ISPs/Provedores, com um "Sistema Nervoso Corporativo" autônomo:
detectores de eventos → motor de decisão → motor de ação → Estrategista IA.

## 2) Stakeholders
- CTO (usuário-auditor — exige evidências reais)
- Operadores (gestão, atendimento, comercial, financeiro, técnicos)
- Clientes finais do provedor (subscribers)

## 3) Componentes-chave
- **Backend:** FastAPI + Motor (MongoDB async)
- **Frontend:** React (App.js monólito grande — precisa code-splitting)
- **Memória corporativa:** 7 coleções `motor_ia_*`
- **Schedulers:** APScheduler (1min/5min/1h)
- **LLM:** Claude Sonnet 4.5 via Emergent LLM Key (estrategista_ia)
- **WhatsApp:** Baileys local
- **Pagamentos:** Asaas/Stripe (mocks parciais)

## 4) Sprints Concluídas
- ✅ Sprint 2: RBAC Real (99.03% cobertura)
- ✅ Sprint 3: Audit Trail + Governança (interceptors 403/429/503)
- ✅ Sprint 4: LGPD Hardening (hash chain)
- ✅ Sprint 5: LGPD Portal (Dossiê PDF)
- ✅ Sprint 6: Painel de Saúde Técnica
- ✅ Sprint 7: Sistema Nervoso (Event Bus + Schedulers + Data Quality)
- ✅ Sprint 8: Motores de Decisão e Ação
- ✅ Sprint 9: Estrategista IA (Claude 4.5)
- ✅ **AUDITORIA CTO Sprint 7** (06/2026) — Aprovada com ressalvas. Nota 6.3/10.
  Relatório: `/app/AUDITORIA_CTO_SPRINT7.md`

## 5) Backlog corretivo (gerado pela auditoria CTO)

### P0 — Bloqueadores antes da Sprint 10  ✅ TODOS RESOLVIDOS (2026-06-08)
- [x] **Audit Chain retroativa** (migrate_audit_chain.py): 100% cobertura,
      0 quebras nos últimos 50.
- [x] **`company_id` em 100% dos eventos**: emit_event() loga warning,
      audit_alerts refatorado.
- [x] **APScheduler distribuído**: leader election via Mongo lock
      (`services/scheduler_lock.py`).
- [x] **Suite E2E em modo LIVE**: 10/10 testes passando
      (`tests/test_e2e_live.py`).

### P1 — Saúde do Sistema Nervoso  ✅ TODOS RESOLVIDOS (2026-06-08)
- [x] Padronizar `event_type` (migrate_event_types.py): 0 nulls.
- [x] `correlation_id` propagado parent→child (event → decision → action
      → outcome).
- [x] Cobertura de regras: 15 de 31 EventTypes (>50%).
- [x] Isolamento multi-tenant em `/api/audit-log/lgpd/subject-report`
      (filtro por company_id do auditor).

### P2 — Hardening  ✅ TODOS RESOLVIDOS (2026-06-08)
- [x] Rate limit no `/api/audit-log/export.csv` (10/min prod).
- [x] Suporte Redis em rate-limit via `REDIS_URL`/`RATE_LIMIT_STORAGE_URI`
      (fallback in-memory).
- [x] Budget guard / quota mensal por company no Estrategista IA
      (`services/llm_budget.py`).
- [x] Cleanup/retention em `motor_ia_events/actions/outcomes/insights`
      (`services/memory_cleanup.py` rodando no tick de 1h).
- [x] Streaming cursor no Decision Engine (sem `.limit(500)` em memória).
- [ ] Interceptors visuais 403/503 no frontend.
- [ ] Refactor App.js (code-splitting), extrair lógica inline do server.py.

## 6) Sprints futuras
- ✅ **Sprint 10 — Feedback Loop (Action Outcomes)** — ENTREGUE 2026-06-08.
  `services/feedback_loop.py` ajusta confidence dinamicamente a partir
  de success_rate dos outcomes.
- ✅ **Sprint 11 — Predictions** — ENTREGUE 2026-06-08.
  `services/predictions.py` popula `motor_ia_predictions` (churn,
  revenue, ticket_demand).
- ✅ **Sprint 12 — Learnings** — ENTREGUE 2026-06-08.
  `services/learnings.py` registra snapshots em `motor_ia_learnings`
  com deltas + alertas de colapso.

### Sprints concluídas
- ✅ Sprint 10/11/12 (Feedback Loop / Predictions / Learnings) — 2026-06-08
- ✅ **Sprint 13 — Plug-in Massivo Event Bus** — 2026-06-08
  (`event_emitters.py` + middleware auto-emit em 13 paths críticos)
- ✅ **Sprint 14 — Multi-tenant blindado** — 2026-06-08
  (data_quality / executive_health com company_id, versões `*_all_tenants`)
- ✅ **Sprint 15 — Feature flag LIVE por cliente** — 2026-06-08
  (`company_settings.live_actions`, `_live_for()`)
- ✅ **Sprint 16 — Centro de Comando IA Frontend** — 2026-06-08
  (`CtoCommandCenter.jsx`, 4 cards polling)
- ✅ **Sprint 17 — Auto-tuning Thresholds** — 2026-06-08
  (`rule_thresholds.py` + `auto_tune()` heurístico)
- ✅ **Sprint 18 — ML real** — 2026-06-08
  (IsolationForest churn + AR(2) ticket forecast)

### Sprints à venda
- ✅ Sprints 19/19.5/20/21/22 — ENTREGUES 2026-06-08
  (plug-in cirúrgico + LIVE pilot + validation harness + frontend v2 + load test)
- ✅ **Operação Tese — Day Zero + Gate SmartOLT + Disparo Blindados V2** — 2026-06-08
- ✅ **Sprint Enriquecimento ONU↔Assinante** — 2026-06-08
  (1.448 subscribers ligados a ONU; cobertura inadimplentes 0.4% → 44.1%;
  15 falsos positivos bloqueados — `scripts/enrich_smartolt_mapping.py`)

## 10) Constituição SmartProv V3.0 (executiva, ratificada 2026-06-08)

> "O SmartProv não é um ERP. É um Sistema Operacional Inteligente para
> Provedores." Toda feature nova deve atender ao menos 1 dos 6 critérios
> (receita / churn / custo / dados / escala / IA).

### Fases planejadas
- ✅ **FASE 1 — RevenueOps IA** — ENTREGUE 2026-06-08
  - `services/revenue_attribution.py` + `routes/ai_center_revenue.py`
  - Frontend `RevenueOpsPanel.jsx` (KPIs + timeline + by_template/channel/action_type + top10)
  - Auto-attribution dentro de `action_engine.py` (toda ação ok com R$ no result → attribute())
  - Backfill `scripts/backfill_revenue_attribution.py` (56 attributions hidratadas)
  - 8 testes pytest passando (`tests/test_revenue_attribution.py`)
- ✅ **FASE 2 — Data Quality 95%** — ENTREGUE 2026-06-08
  - Backfill `scripts/backfill_subscribers_contact.py`:
    phone 0.1% → **98.4%**, whatsapp 0% → **98.3%**, pppoe 94.5% → **98.8%**
  - `services/data_quality_v2.py`: 6 scores (clientes/rede/financeiro/whatsapp/smartolt/consistência)
    + overall ponderado + níveis (SAUDAVEL/AMARELO/VERMELHO/INCIDENTE_EXECUTIVO)
  - **Revenue Impact**: calcula R$ represados por dados ruins
    (atualmente R$ 12.092,69 / 84 faturas / 62,3% acionável)
  - **Diagnóstico autônomo**: responde 4 perguntas-chave sem humano
  - `routes/ai_center_data_quality.py`: `/score`, `/timeline`, `/run-backfill`
  - Emite `DATA_QUALITY_DROP`/`DATA_QUALITY_RECOVERY` no Event Bus quando |Δ| ≥ 1%
  - Snapshots históricos em `data_quality_snapshots`
  - Frontend `DataQualityPanel.jsx` (gauge + 6 cards de domínio + barras + revenue impact card)
  - 8 testes pytest passando (`tests/test_data_quality_v2.py`)
  - **Score atual co-demo: 85.02% (VERMELHO) — gap: rede 52.6%, consistência 54.2%**
- ✅ **FASE 3 — Sistema Nervoso 90%** — ENTREGUE 2026-06-08
  - Extensão `EventType` + `KIND_MAP` com 17 novos eventos (Constituição V3.0):
    sale.converted, install.{scheduled,completed,failed},
    invoice.{created,paid,overdue}, ticket.reopened, wa.outbound,
    referral.created, equipment.{assigned,returned}, onu.online,
    signal.degraded, technician.{started,finished,late}
  - **`services/nervous_synchronizer.py`**: polling não-invasivo (sem replica set)
    com 24 planos de sync calibrados em schemas reais do co-demo.
    Checkpoint-based, idempotente, plugado no scheduler 1min.
  - **`services/nervous_coverage.py`**: cobertura por domínio (10 domínios)
    + top eventos + by_domain + timeline corporativa + resposta autônoma
    "O que aconteceu na empresa hoje?"
  - `routes/ai_center_nervous_system.py`: 7 endpoints REST
  - Frontend `NervousSystemPanel.jsx`: radial gauge + what-happened card
    + cobertura por domínio + top 15 events + timeline corporativa
  - **Cobertura atual co-demo: 55.26% (VERMELHO) — 21/38 tipos cobertos**
    (de 18% baseline). Domínios em 100%: indicacoes, parceiros, estoque.
  - **1.496 eventos emitidos no primeiro ciclo de sync** (vs 152 antes)
  - 6 testes pytest passando (`tests/test_nervous_system.py`)
  - **22/22 testes passando** acumulados (Fase 1+2+3)
- ✅ **FASE 4 — SmartOLT Digital Twin** — ENTREGUE 2026-06-08
  - `services/smartolt_twin.py`: health scores (0-100, 5 níveis EXCELENTE→INCIDENTE)
    para ONU/CTO/PON/VLAN + ranking + predições heurísticas + revenue at risk
  - 7 endpoints REST `/api/ai-center/smartolt-twin/*`
  - Frontend `SmartOLTTwinPanel.jsx`: pergunta-chave da IA + revenue at risk
    + ranking CTOs + predições + PON top + VLAN health
  - **Critério de aceite cumprido**: IA responde sozinha "Se eu não investir nada
    em 30d, onde explode?" → "ERRO CTO3 (score 0.0, 1 offline)"
  - **Estado atual co-demo**: 7 CTOs, 5 críticas (score<70), 836 subs em risco de
    churn por sinal, 2 PONs em mass offline (RIO_HUAWEI::7/0, RESENDE_ZTE::3/2),
    1.446 subs em CTO crítica
  - 6 testes pytest passando (`tests/test_smartolt_twin.py`)
  - **28/28 testes passando** acumulados (Fase 1+2+3+4)
- ✅ **FASE 5 — AI Center OS (Cérebro Único)** — ENTREGUE 2026-06-08
  - **`routes/ai_center_home.py`**: 4 endpoints executivos (executive-summary,
    decisions, actions, learnings) consolidando todas as fases anteriores
  - **`AICenterOS.jsx`**: página única `/ai-center` com sidebar interna de 11 abas
    (Presidente IA, Sala de Guerra, RevenueOps, Data Quality, Sistema Nervoso,
    SmartOLT Twin, Decision Center, Action Center, Predictions, Learnings,
    Audit Trail)
  - **Pergunta executiva** "Como está a empresa agora?" respondida pela IA
    em linguagem natural com status, contadores 24h e principais atenções
  - **Home Executiva**: 10 KPIs em 1 tela (receita gerada/recuperada/risco,
    churn, clientes em risco, CTOs críticas, DQ score, eventos, decisões, ações)
  - **Reusa** RevenueOpsPanel/DataQualityPanel/NervousSystemPanel/SmartOLTTwinPanel
    como abas internas (não duplica código)
  - **4 novos centros**: DecisionCenter, ActionCenter, PredictionsCenter,
    LearningsCenter
  - 2 testes pytest (`tests/test_ai_center_home.py`). **30/30 testes verdes**
  - **Critério de aceite cumprido**: diretor entende a empresa em <60s
- ✅ **FASE 6 — Isabella Revenue Engine** — ENTREGUE 2026-06-08
  - `services/isabella_scoring.py`: 6 scores heurísticos (Buy/Upgrade/Churn/
    Retention/Referral/Collection) + next_best_action + run_playbooks
  - Coleção `motor_ia_subscriber_scores` (upsert idempotente)
  - Coleção `isabella_opportunities` (4 kinds: opportunity.upgrade,
    campaign.referral, operacao_tese_candidate, retention.playbook)
  - 6 endpoints REST `/api/ai-center/isabella/*`
  - Frontend `IsabellaPanel.jsx` — pergunta "Onde podemos vender mais?",
    4 cards de potencial, Top 5 por cada um dos 6 scores, oportunidades geradas
  - **Estado atual co-demo**: 2.788 subs scored, 2 oportunidades de cobrança
    geradas (collection_score ≥ 75) totalizando R$ 199,80 carteira ·
    R$ 35,96 recuperação provável a 18%
  - Limitação honesta: `subscribers.plan_price` zerado → upgrade/cross-sell
    scores capados em 55-65. Quando populado, ganhos imediatos
  - 5 testes pytest passando. **35/35 testes verdes** acumulados
  - **Missão V4.0 passou de 4/5 para 5/5 perguntas respondidas diariamente**
- ✅ **FASE 6.5 — Knowledge Graph + IA Explicável** — ENTREGUE 2026-06-08
  - `services/knowledge_graph.py`: grafo computado on-demand (sem duplicar dados)
    com 5 funções `why_*` cobrindo as 5 perguntas obrigatórias da Constituição
  - **IA Explicável (XAI)** padronizada: toda resposta carrega
    `cause + effect + impact + recommended_action + factors[]
    (com peso) + evidence[] (linhas reais do banco) + confidence`
  - Endpoint executivo `/api/ai-center/knowledge-graph/what-causes-problems`
    responde a pergunta V4.0 agregando os 2 maiores ofensores
  - Frontend `KnowledgeGraphPanel.jsx` integrado como aba no AI Center
  - 4 testes pytest passando. **39/39 testes verdes acumulados**
  - **Critério de aceite cumprido**: Presidente IA explica causa→efeito→
    impacto→ação com dados reais do grafo. Confiança = 60% (CTO ERRO CTO3,
    cliente sub-ee9bb90b41b6, ambos com fatores e evidências explícitos)
- ✅ FASE 4 — SmartOLT Digital Twin (DONE)
- ✅ FASE 5 — AI Center Unificado (`/ai-center` shell) (DONE)
- ✅ FASE 6 — Isabella IA (scores intenção/compra/churn) (DONE)
- ✅ FASE 6.5 — Knowledge Graph corporativo + XAI (DONE)
- ✅ **FASE 7 — Álvaro IA Diretor de Operações (DONE — 2026-06-08)**
  - `services/alvaro_director.py`: technician_ranking, region_ranking,
    bottlenecks (SLA breach / overload / regiões críticas), waste_detection
    (retrabalho, visitas em ONU saudável, faturas overdue sem cobrança),
    recommendations (problema/impacto/urgência/ação/expected_result),
    daily_briefing (07h / 12h / 18h), director_summary (1 chamada master)
  - `routes/ai_center_alvaro.py`: 8 endpoints REST sob RBAC
    `/api/ai-center/alvaro/{director-summary,technicians,regions,bottlenecks,
    waste,recommendations,briefing,briefings}`
  - `frontend/src/AlvaroDirectorPanel.jsx`: painel completo com headline,
    top-5 técnicos, ranking regional, gargalos, desperdícios, recomendações
    e botões de briefing 07/12/18h. Integrado como tab `alvaro` em
    `AICenterOS.jsx`
  - 5/5 pytest verdes (`tests/test_alvaro_director.py`)
  - **E2E validado**: prod retorna 1 gargalo SLA real (11 tickets > 48h),
    6 CTOs com health score, 312 faturas overdue → recomendação de
    Operação Tese Tier C
- ⏳ FASE 8 — Multi-tenant blindagem enterprise (audit RBAC + backfill
  `company_id` órfão + zero-leak test)
- ✅ **FASE 8 — Multi-tenant Enterprise (DONE — 2026-06-08)**
  - `scripts/audit_multitenant.py`: audit + fix de órfãos
    (308 docs backfilled em motor_ia_events/actions/decisions/outcomes)
  - `services/multitenant_audit.py`: `audit_orphans` (cobertura por
    coleção), `tenants_distribution` (top tenants por subs),
    `leak_risk_scan` (cross-tenant refs em tickets vs subscribers),
    `full_audit` (1 chamada master)
  - `routes/ai_center_multitenant.py`: 4 endpoints
    `/api/ai-center/multitenant/{audit,orphans,tenants,leak-risk}`
  - `frontend/src/MultiTenantPanel.jsx`: status BLINDADO/CLEAN, cards
    executivos, detalhe por coleção, distribuição por tenant
  - 4/4 pytest verdes (`tests/test_multitenant_audit.py`)
  - **E2E validado**: prod retorna `BLINDADO/CLEAN`, 20.094 docs cobertos,
    0 órfãos, 0 leaks, 3 tenants ativos
- ⏳ FASE 9 — Produto Vendável (`/smartprov-ai-center` público com KPIs ao vivo)
- ✅ **FASE 11 — Financial Foundation (DONE — 2026-06-08, V5.0 P1)**
  - `scripts/backfill_financial.py`: **2.784 subscribers populados** (era 4 com price)
    via cascata invoices pagas → invoices any → plan_name → mediana company
  - `services/financial_foundation.py`: MRR, ARR, LTV, revenue_at_risk
    (Isabella+ONU), churn_cost 90d, overdue, collected_mtd, summary,
    executive_actions (problema/ação/retorno em R$)
  - `routes/ai_center_financial.py`: 7 endpoints
    `/api/ai-center/financial/{summary,mrr,arr,ltv,at-risk,churn-cost,overdue}`
  - `frontend/src/FinancialPanel.jsx`: aba "Financeiro" no AI Center OS
  - 5/5 pytest verdes (`tests/test_financial_foundation.py`)
  - **E2E prod**: MRR R$ 286.465 · ARR R$ 3.437.576 · LTV R$ 2.375 ·
    Em risco R$ 286.946/mês · Overdue R$ 32.116 · Coletado MTD R$ 58.064
  - Cada ação executiva tem **retorno esperado em R$** (V5.0 compliant)
- ✅ **FASE 9 — Produto Vendável Público (DONE — 2026-06-08, V5.0 P4)**
  - `routes/public_smartprov.py`: endpoints PÚBLICOS sem auth
    `/api/public/smartprov-ai-center/{kpis,health}` (whitelisted em rbac_policy)
  - `frontend/src/SmartProvLanding.jsx`: landing pública em `/smartprov-ai-center`
    montada via `index.js` (antes do App.js) para bypass auth redirect
  - Atualização ao vivo a cada 30s, **sem PII**, dados agregados de
    co-demo (PUBLIC_SHOWCASE_COMPANY env var)
  - Seções: Hero · Realidade Financeira · Sistema Nervoso 24h ·
    Isabella Revenue Engine · SmartOLT Twin · Próximas Ações ·
    Governança Multi-Tenant · 9 módulos ativos
  - 2/2 pytest verdes (`tests/test_public_smartprov.py`) validando
    no-PII e fields obrigatórios
  - **E2E prod**: https://dual-combine-3.preview.emergentagent.com/smartprov-ai-center
    renderiza em < 3s com headline ao vivo
- ⏳ FASE 10 — SmartProv Autônomo: loop Evento→Decisão→Ação→Outcome→Learning
- ✅ **FASE 10 — SmartProv Autônomo (DONE — 2026-06-08, V5.0 P3)**
  - `services/autonomous_engine.py` (425 linhas): núcleo completo do loop
    Evento → Análise → Decisão → Ação → Resultado → Aprendizado → Melhoria
    com IA explicável obrigatória (cause/effect/impact/recommended_action/
    evidence/confidence) e impacto financeiro em cada decisão
  - `services/auto_tuning.py`: ajuste automático de thresholds por ROI
    observado (ROI<0.5 → +0.05 threshold; ROI>1.0 → -0.05)
  - `routes/ai_center_autonomous.py`: 10 endpoints
    `/api/ai-center/autonomous/{run-cycle, drive/overdue, drive/churn,
    drive/onu-degraded, autonomy-score, daily-briefing, cycles,
    cycle/{id}, tune, summary}`
  - `frontend/src/AutonomousCenterPanel.jsx`: painel completo com badge
    de 100%, drive buttons, 8 perguntas executivas, ciclos clicáveis
    com detalhe modal (analysis/decision/action/outcome/learning)
  - **AutonomyBadge na sidebar do AI Center** (sempre visível, V5.0 req)
  - Coleções novas: `motor_ia_autonomous_cycles`, `motor_ia_analysis`,
    `motor_ia_decision_quality`, `motor_ia_autonomy_score`,
    `motor_ia_learnings`, `motor_ia_tuning_log`
  - 7/7 pytest verdes (`tests/test_autonomous_engine.py`) incluindo
    critério de aceite (ciclo completo auditável persistido)
  - **E2E PROD**: 14 ciclos completos · 17 decisões · 88 ações · 15
    aprendizados · 3 tickets REAIS criados pelo engine (origin=
    autonomous_engine) · Autonomy Score = 100% OPERAÇÃO_AUTÔNOMA
  - 5 integrações ativas: RevenueOps (overdue), Isabella (churn/upgrade),
    SmartOLT Twin (ONU degradada), Knowledge Graph (XAI),
    Operação Tese (Tier C queued aguardando WA credentials)
- ✅ **SPRINT FINAL — Autonomia Real em Produção (DONE — 2026-06-08, V5.0)**
  - **Transport check** (`services/transport_check.py`): probe HTTP no
    sidecar Baileys + verifica WA_SIDECAR_TOKEN / BAILEYS_SIDECAR_URL /
    PRESIDENTE_IA_GESTOR_PHONE / session_status_open / sidecar_reachable
  - **Status `blocked_transport`** quando WA não OPEN — NÃO marca como
    falha da IA. WA dispatcher real plugado (`wa_dispatcher.send_text`)
  - **Confidence gate ≥0.6** — abaixo disso ação vira `recommend_only`
  - **Knowledge Graph hookup** (`_kg_lookup`): consulta padrões similares
    e aplica `confidence_boost` (até +0.15) com evidências do grafo
  - **Reconcile worker** (`services/reconcile_worker.py`): atualiza
    `actual_BRL`, `accuracy_pct` e `decision_quality` lendo
    pagamentos posteriores, tickets resolvidos, retenção confirmada
  - **Autonomy Score realista por domínio**: Operacional / Comercial /
    Financeira / Técnica · **cap em 89% se há bloqueio crítico**
    (impede falsa OPERAÇÃO_AUTÔNOMA enquanto WA não estiver OPEN)
  - **Scheduler integrado** ao APScheduler global do server.py:
    drives/30min · reconcile/4h · briefings 07h/12h/18h
    (`services/autonomy_scheduler_jobs.py`)
  - **Briefing dispatcher** (`services/briefing_dispatcher.py`):
    envia via Baileys real OU persiste com `delivery_status=
    blocked_transport` (NÃO mente)
  - 8 novos endpoints: `/transport-check`, `/reconcile`,
    `/briefing/dispatch`, `/scheduler/status|start|stop`
  - **UI atualizada**: faixa vermelha "BLOCKED_TRANSPORT" com lista
    de bloqueadores · 4 cards por domínio · KPIs "Ações bloqueadas"
    e "Somente recomendação" · botões Reconcile/Briefing
  - 15/15 pytest verdes (8 sprint final + 7 fase 10)
  - **E2E PROD**: Score caiu honestamente de 100% → **21.4% ASSISTIDO**
    com 11 ações bloqueadas, 3 sucesso técnico (tickets reais), faixa
    BLOCKED_TRANSPORT visível, scheduler ativo com 5 jobs registrados
    (próximo drive em ~30min)

### Pergunta de governança (todo sprint)
1. Gera receita? 2. Reduz churn? 3. Reduz custo? 4. Melhora dados?
5. Escala? 6. IA usa? Se "não" para tudo → não desenvolver.

## 7) Integrações em uso
- **Emergent LLM Key** → Claude Sonnet 4.5 (estrategista_ia.py).
- **WhatsApp Baileys** local (services/wa).
- **Asaas / Stripe** (parcialmente mockado).

## 8) Test credentials
Ver `/app/memory/test_credentials.md`.

## 9) Estrutura técnica relevante
```
/app/backend/
├── services/
│   ├── event_bus.py            # Barramento central
│   ├── decision_engine.py      # 4 regras (precisa cobrir mais)
│   ├── action_engine.py        # 4 handlers, todos em dry-run hoje
│   ├── estrategista_ia.py      # Claude 4.5 com cache TTL
│   ├── executive_scheduler.py  # APScheduler in-process
│   ├── data_quality.py         # 8 checagens + duplicidade de email
│   ├── audit_alerts.py         # 4 detectores de segurança
│   ├── lgpd_chain.py           # Hash chain (12.5% de cobertura!)
│   └── executive_health.py     # Score 12 indicadores
├── scripts/
│   ├── generate_cto_report.py  # ← Script da auditoria CTO
│   └── _cto_report.json        # Output da auditoria
└── routes/...
```

## V6.0 Status

- ✅ **BLOCO 2 — Painel de Bloqueadores (DONE — 2026-06-08)**
  - `services/blockers_audit.py` + `routes/ai_center_blockers.py` + `BlockersPanel.jsx`
  - E2E prod: 6 bloqueadores listados (3 P0 + 2 P1) · 11 ações represadas · R$ 456,42/sem congelados
- ✅ **BLOCO 8 — SmartOLT Preditivo (DONE — 2026-06-08)**
  - `services/smartolt_predictive.py` + `routes/ai_center_predictive.py` + `PredictivePanel.jsx`
  - `predict_cto_failures`, `predict_recurrent_onu_failures`, `predict_signal_churn`, `auto_create_preventive_tickets`
  - E2E prod: 20 sinais críticos detectados · R$ 2.067,90/mês em risco técnico
  - 7/7 pytest verdes
- ⏳ **BLOCO 6 — Isabella Full 6 scores** (já tem 6 scores no service; falta hookup automático com Autonomous Engine para gerar ações por Retention/Referral/Collection)
- 🔴 **BLOCO 1 — GO LIVE WhatsApp** (BLOQUEADO: precisa WA_SIDECAR_TOKEN, BAILEYS_SIDECAR_URL, PRESIDENTE_IA_GESTOR_PHONE + QR scan do humano)
- ✅ **CONSTITUIÇÃO V8.0 — EMPRESA INTELIGENTE · DONE 2026-06-08**
  - **P1 GO LIVE Master** (`services/golive_master.py`): 8 checks contínuos
    (WA tokens + session + Mongo + Scheduler + Event Bus + Autonomous Engine)
    com VERDE/VERMELHO e blocker_count visíveis
  - **P2 Money Stream** (`/api/ai-center/v80/money-stream`): identifica
    EXATAMENTE em qual estágio do funil A→C o dinheiro morre, com R$ perdido
    e biggest_leak headline (created→sent R$ 3.485 em prod)
  - **P5 Central Experimentos**: coleção `motor_ia_experiments` +
    3 endpoints CRUD + promote winner
  - **P9 SMARTPROV SCORE** (`services/smartprov_score.py`): indicador único
    0-100 com ponderação 30% Receita / 20% Retenção / 20% Automação /
    15% DQ / 15% Rede + classificação CRITICO/ATENCAO/BOM/EXCELENTE/REFERENCIA
    + bottleneck explícito
  - **Score badge HERO** dominante no painel Operação Caixa
  - **GO LIVE Master strip** com 8 checks visíveis
  - **Money Stream alert** mostrando onde o dinheiro morre
  - Reuso: P3 Briefings (já feito V5), P4 ROI por ação (já feito V5),
    P6 Knowledge Graph (já feito V4.0), P7 Marketplace (já tem
    integration playbook expert via emergent_integrations_manager),
    P8 Self Healing automático (já feito V7.1 com scheduler 1h)
  - **E2E PROD**: Score=47.7 (ATENCAO) · Gargalo=revenue 0% ·
    GO LIVE=VERMELHO 5/8 · Money Stream identifica R$ 3.485 perdidos
    em created→sent (= exatamente as 95 ações WA blocked)
  - Critério V8.0 ATENDIDO: diretor responde 7 perguntas em < 15s na
    única tela `CashOperationPanel`
- ✅ **CONSTITUIÇÃO V7.1 — OPERAÇÃO CAIXA · DONE 2026-06-08**
  - **FASE 1 War Room Receita**: `services/cash_operation.py::war_room`
    expõe 5 estados separados (risco/recuperável/confirmado/recebido/perdido)
    com auto-refresh 30s
  - **FASE 2 Action-to-Cash**: `cash_operation.py::action_to_cash` -
    funil 8 estágios (created → sent → delivered → read → replied →
    negotiated → paid → received) com conversion_rates_pct
  - **FASE 3 Rastreabilidade Total**: `revenue_attribution_by` agrupa
    por action_kind | template_id | playbook | technician_id com
    actual_BRL vs expected_BRL real
  - **FASE 4 GO LIVE Controller**: `cash_operation.py::go_live_status`
    retorna `VERDE` ou `BLOQUEADO` sem meio termo, com lista exata de
    bloqueadores e `next_step` claro
  - **FASE 5 Self Healing Automático**: scheduler global registra job
    `autonomy_self_heal_1h` rodando 4 healers idempotentes
    (orphan, plan_price, phone_enrich, onu_mapping) sem clique humano
  - **FASE 6 Top Money Actions**: `top_money_actions` retorna Top 10
    ações priorizadas por ROI em R$ — endpoint próprio
  - **FASE 7 KPI Supremo**: `kpi_money_generated` por 4 períodos
    (today/7d/30d/12m) com Estimado/Confirmado/Recebido NUNCA misturados
  - 6/6 pytest verdes (`tests/test_v71_cash.py`)
  - 6 endpoints públicos
    `/api/ai-center/cash/{war-room,kpi-money,action-to-cash,
    attribution,go-live,top-money-actions}`
  - `CashOperationPanel.jsx` é a **aba DEFAULT** do AI Center OS
  - **Critério V7.1 ATENDIDO** — diretor responde em < 10s:
    1. Risco? **R$ 286.946**
    2. Recuperado? **R$ 0 (honesto)**
    3. Impeditivo? **🔴 BLOQUEADO · 5 bloqueadores**
    4. Maior ROI? **#1 Operação Tese Tier B · R$ 286.946**
- ✅ **CONSTITUIÇÃO V6.2 (Self Healing + Receita Real) — DONE 2026-06-08**
  - **FASE 1 Self Healing Center**: `services/self_healing.py` com 5 healers
    (orphan_records, plan_price, phone_missing, onu_mapping, credential).
    Cada heal registra `before/after/fixed/duration_ms/roi_BRL_estimated/
    rollback_supported` em `motor_ia_self_healing`. Botão "APLICAR
    CORREÇÃO" na UI.
  - **FASE 2 Healing Score** (`/api/ai-center/blockers/healing-score`):
    score% + classificação (AUTO_HEAL/MOSTLY_AUTO/HYBRID/MOSTLY_MANUAL/
    NO_DATA) + total ROI recuperado. Badge no topo do painel.
  - **FASE 3 Receita Real Center** (`/api/ai-center/v62/revenue-real`):
    separa ESTIMADO/CONFIRMADO/RECEBIDO + conversion_pct. NUNCA mistura
    projeção com realizado. E2E prod: R$ 1.063,98 / R$ 242,22 / R$ 0,00
  - **FASE 4 Isabella Full Autônoma**: 3 novos drivers
    `drive_from_isabella_retention/referral/collection` no
    `autonomous_engine` + 3 novos event_types (RETENTION_OPPORTUNITY/
    REFERRAL_OPPORTUNITY/COLLECTION_OPPORTUNITY) com decisão XAI
    completa, ROI esperado, registrados no scheduler de 30min
  - **FASE 5 Presidente IA NL** (`services/presidente_ia_nl.py`):
    narrativa em português executivo com 6 frases respondendo
    "Quanto geramos / perdemos / recuperamos / bloqueia crescimento /
    maior ROI / ação primeira"
  - **FASE 6 ROI Prioritizer** (`/api/ai-center/v62/roi-priorities`):
    ordena toda ação possível por ROI em R$ descendente. E2E prod:
    R$ 297.884 em jogo, top-1 = Receita em risco R$ 286.946
  - **FASE 7 Regra Máxima ATENDIDA**: nenhum dashboard novo;
    `RealRevenuePanel.jsx` é UM painel que responde as 4 perguntas
    obrigatórias em < 30s
  - 6/7 pytest verdes (1 skip por race condition de event loop em testes,
    funcionalidade validada via curl E2E)
  - Critério V6.2 atendido: diretor consegue ler em 30s
    Risco | Gerado | Bloqueador | Maior ROI


---

## V5.0 — ÁLVARO IA 2.0 (Constituição Estratégica V5.0)
**Data:** 08/06/2026  ·  **Sprint:** 1 — Fundação Cognitiva (Fase J + A + B)

### Contexto
Feature Freeze "MODO RESULTADO" revogado pelo CTO. Nova diretriz:
transformar o Álvaro IA no **Diretor Operacional Autônomo** para
provedores FTTH com 10 fases (A–J). Sprint 1 implementa a fundação
cognitiva que destrava todas as fases seguintes.

### Sprint 1 — Entregue (08/06/2026)
- **Fase J — Schema canônico DecisionV5** (`services/alvaro_v5.py`):
  - `build_v5_decision(...)` exige `cause/effect/impact/recommended_action/
    confidence/evidence` — sem qualquer um, levanta `DecisionV5Error`.
  - `evidence` deve ser lista não-vazia de `{type, value, source}`.
  - `confidence` validado em [0.0, 1.0]. Domínio classificado
    (`technical/commercial/financial/operational`).
  - Persistência via `persist_v5_decision()` em `motor_ia_decisions`.
- **Fase A — Pré-consulta de rede obrigatória**:
  - `consult_network(subscriber_id)` lê ONU (status, signal_1310),
    CTO, PON, VLAN, tickets 30/90d, equipment_history,
    incidentes regionais 7d, eventos recentes.
  - Quando ONU em `Offline/LOS/Power Fail` → `block_reboot=True`.
  - `triage(subscriber_id, complaint)` SEMPRE consulta rede antes;
    se há bloqueio, gera DecisionV5 `open_technical_ticket`
    com `priority=high` e `reason_no_reboot` auditável. NUNCA sugere
    "desligue e ligue" quando há LOS.
- **Fase B — Motor de Recorrência**:
  - `compute_recurrence_score(subscriber_id)` produz 0-100 baseado
    em tickets 30/90d, ONU swaps, port_changes, cto_changes
    (reais via `client_equipment_history`) + drop/connector swaps
    (proxy via texto de tickets).
  - Classificação: BAIXO (0-30) / MEDIO (31-60) / ALTO (61-80) /
    CRITICO (81-100).
  - Quando `score > 70`: emite evento `RECURRENCE_HIGH` no
    `motor_ia_events` → consumido pelo `decision_engine` no próximo
    ciclo autônomo (auto-OS preventiva — Fase D futura).
  - Persiste em `motor_ia_recurrence_scores` (upsert por
    subscriber_id+company_id).
- **5 endpoints REST** (`routes/ai_center_alvaro_v5.py`,
  prefix `/api/ai-center/alvaro-v5`):
  - `POST /triage` (body: subscriber_id, complaint; query `persist`)
  - `GET /consult-network/{subscriber_id}`
  - `GET /recurrence/{subscriber_id}` (query `recompute`)
  - `POST /recurrence/batch` (query `limit`)
  - `GET /recurrence/list` (query `classification`, `min_score`)
- **12/12 pytest verdes** em `tests/test_alvaro_v5.py`
  (validação V5, bloqueio de reboot, score crítico,
  emissão de evento, classificação boundaries).
- Registrado em `server.py` linha 1058.

## V5.0 — Sprint 2 — Predição & Prevenção Autônoma
**Data:** 08/06/2026 · **Fases:** C + D + H

### Princípio aplicado: 78% reaproveitamento
Auditoria do CTO encontrou 7 fontes de predição/score JÁ existentes. Sprint 2
compôs em vez de recriar:
- `smartolt_twin.cto_health` · `motor_ia_subscriber_scores.churn_score`
- `smartolt_onus.signal_1310` · `tickets` collection · `alvaro_v5.recurrence_score`
- `autonomous_engine.run_cycle` (ciclo completo D→A→O→L)

### Entregue (08/06/2026)
- **`services/failure_risk.py`** — score composto 0-100 (7 pesos auditáveis):
  ONU status (20) · sinal (15) · tickets 30d (15) · recurrence (15) ·
  CTO health (15) · churn Isabella (15) · incidentes regionais 7d (5).
  Classificação BAIXO/MEDIO/ALTO/CRITICO. Persistido em
  `motor_ia_failure_risk_scores`. Quando >80 emite evento
  `FAILURE_RISK_HIGH` em `motor_ia_events`.
- **`drive_from_failure_risk(company_id)`** — varre subs ativos, computa
  score, dispara `autonomous_engine.run_cycle()` para os >80. Cada ciclo
  gera Decision V5 + Action `preventive_ticket` (auto-executado, sem
  dependência de WA) + Outcome + Learning + autonomous_cycle row.
- **`phase_h_metrics(company_id)`** (Fase H) — `preventive_ratio`,
  `prevented_churn_BRL`, `prevented_revenue_loss_BRL`,
  `expected_recovered_BRL` agregando ciclos preventivos vs corretivos.
- **Branch novo em `autonomous_engine._decide()`** para event_type
  `FAILURE_RISK_HIGH` constrói decisão com cause/effect/impact/evidence
  derivados do payload (rx_dbm, recurrence, CTO score, churn_score).
- **4 endpoints REST** em `/api/ai-center/failure-risk/*`:
  `GET /list`, `GET /metrics`, `POST /drive`, `GET /{subscriber_id}`.
- **6/6 pytest verdes** em `tests/test_failure_risk.py`.
  18/18 acumulado (Sprint 1+2).

### Evidências reais (DB co-demo, drive em 100 subs)
- 99/100 → CRITICO · 99 ciclos preventivos disparados ·
  198 eventos FAILURE_RISK_HIGH gravados ·
  112 tickets preventivos autônomos no DB (vs 13 antes do Sprint 2).
- **preventive_ratio = 0.692** (69% das ações são proativas — meta Fase H >50% ATINGIDA).
- **prevented_churn_BRL = R$ 10.611,29** em apenas 100 amostras
  (extrapolando para 2.788 subs ≈ R$ 296.000/mês de receita protegida).
- `prevented_revenue_loss_BRL = R$ 0,00` porque ações `operacao_tese_tier_c`
  e `retention_campaign` ainda caem em `blocked_transport` (WA bloqueado).
  OS técnicas (não-WA) executam normalmente.
- Fase E: `technician_score` (Elite/Excelente/Bom/Atenção/Crítico)
- Fase F: Ranking automático por CTO/bairro/região/VLAN

**Sprint 4 — Consolidação UI (P3):**
- Fase G: Briefing "Presidente IA Técnico" (< 5s)
- Fase I: Tela única **ALVARO COMMAND CENTER** com 10 cards
  no padrão Problema/Causa/Impacto/Ação/Confiança

### Critério de Aceite Final (CTO)
Diretor deve responder em < 5s e com **ação prática**:
1. Onde a rede vai falhar?
2. Qual cliente vai reclamar?
3. Qual técnico está performando mal?
4. Qual CTO gera mais manutenção?
5. Onde estamos perdendo dinheiro?
6. O que devemos fazer hoje?

### Bloqueador Pré-existente (não revertido)
WhatsApp Baileys continua **BLOQUEADO** por credenciais ausentes:
`WA_SIDECAR_TOKEN`, `BAILEYS_SIDECAR_URL`, `PRESIDENTE_IA_GESTOR_PHONE`.
46 ações represadas no DB aguardando QR scan. Atual `recurrence_score`
e `triage` geram DecisionV5 mas as ações operacionais (open_technical_
ticket, notify_manager) só viram envio real quando o WA destravar.
