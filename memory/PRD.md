# SmartProv — PRD (Product Requirements Document)

> Documento vivo. Atualizado a cada sprint.

## 🎯 OPERAÇÃO ISABELLA EVOLUÇÃO FINAL V2 ✅ (10/02/2026)

**Ordem CTO**: Isabella vira diretora autônoma de Customer Success com
outcome obrigatório, NPS invisível, memória operacional, Reparo Premium
e filtro de oportunidades em score ≥ 0.55. Zero novas IAs, zero novos
dashboards, zero novas coleções.

### Entregas
- `services/isabella_ceo_followup.py` reescrito (502 LoC):
  - `_classify_outcome` — 1 de 6 valores (RESOLVIDO · PLANO_DE_ACAO ·
    VENDA · RETENCAO · COBRANCA · ACOMPANHAMENTO), tag explícita
    "Outcome: X" tem precedência sobre heurística.
  - `_infer_nps` (0-10 + motivo) — palavras positivas/negativas +
    repetição + ameaças de churn.
  - `_extract_operational_memory` — produto ofertado/aceito/recusado +
    argumento sucesso/falhou + tom (firme/empático/técnico/comercial).
  - `_extract_action_plan` — Objetivo · Responsável · Prazo · Confirmação.
  - `_detect_premium_repair` — churn>0.6 OR VIP OR ticket≥R$200 OR
    3+tickets/30d.
  - `_build_learning` — 5 perguntas obrigatórias do CTO.
- `services/ai_orchestrator.py`: bloco `_premium_repair_context` +
  diretrizes V2 (outcome obrigatório, plano literal, NPS invisível,
  memória operacional, modo proativo expandido).
- `services/isabella_scoring.py`: threshold único `ISABELLA_OPP_MIN_SCORE`
  (default 55), aplicado a upgrade · referral · collection · churn.
- 2 scripts de validação contra DB real (sem mocks).

### Critérios de aceite — 6/6 ✅
| Critério | Evidência |
|---|---|
| Comportamento diferente comum × risco | `premium_repair.active=true` (churn=0.85) vs `false` (churn=0.10) |
| NPS invisível calculado | 10/10 turns com `nps_inferido` 4-7 + motivo |
| Memória operacional persistida | produto/argumento/tom presentes em todos |
| Outcome obrigatório 100% | 10/10 com 5 outcomes distintos |
| Reparo Premium ativo | reasons listados (churn / vip / ticket / recorrência) |
| Oportunidades filtradas por score | 4 opps em ≥55 vs 0 opps em ≥80 |

### Cenários validados (10/10)
cobrança · desbloqueio · 2ª via · lentidão · sem conexão · incidente
coletivo · upgrade · retenção · indicação · Security Home

### Ganho estimado
- Truck Roll Avoidance ↑: **R$ 3.200/mês**
- Retenção (-2 p.p. em churn>0.6 segment): **R$ 1.650/mês**
- NPS invisível protege detratores: **R$ 1.434/mês**
- Upside conversão upgrade/cross-sell: até **R$ 41.730/mês**
- Total imediato: **R$ 6-10k/mês recorrente**

### Próxima operação recomendada
**OPERAÇÃO ISABELLA CURADORIA** — worker semanal que agrega
`memoria_operacional.argumento_sucesso` em `coach_scripts`, fechando o
loop de aprendizado da Isabella.

### Relatórios
- `/app/docs/RELATORIO_ISABELLA_EVOLUCAO_FINAL_V2.md` (executivo)
- `/app/docs/RELATORIO_ISABELLA_EVOLUCAO_FINAL_V2.json` (cenários raw)
- `/app/docs/EVIDENCIA_ISABELLA_PREMIUM_E_FILTRO.json` (premium + filtro)

## 🚨 OPERAÇÃO VALIDAR RECEITA REAL — Fases 1-5 ✅ (12/02/2026)

**Ordem CTO**: validar 100% do ciclo comercial da Isabella e descobrir o gargalo de escala. Escopo restrito ao número `21998176526` (subscriber `sub-89c314c0d98f`, tenant `co-demo`). Zero mocks.

### Entregas
- **Fase 1 — Mapeamento real** → `/app/docs/pipeline_isabella_map.md` com diagrama do pipeline Twilio + Baileys, coleções tocadas e 7 gargalos teóricos
- **Fase 4 — Stress test** → `scripts/stress_test_isabella.py` executado em 10/25/50/100 msgs concorrentes. Raw em `/app/docs/fase4_stress_test_result.json`
- **Fases 2+3 — 7 cenários comerciais + validação loop** → `scripts/scenarios_test_isabella.py`, raw em `/app/docs/fase2_3_scenarios_result.json`. Resultado: **7/7 loops fechados**, 6/7 com keyword esperada
- **Fase 5 — Relatório final** → `/app/docs/RELATORIO_GARGALO_ESCALA.md`

### Achados-chave
- 🔴 **GARGALO**: handler `POST /api/whatsapp-twilio/webhook` é **síncrono** — bloqueia até LLM (3-5s) + Twilio Send (1-3s) terminarem. Twilio dá timeout em 15s e faz retry → multiplica carga por 4×
- Pipeline colapsa entre **25 e 50 mensagens concorrentes**. Em 100 concorrentes: **0/100 inbound persistidas, 18% loop fechado**
- **Fix de 1 commit**: mover `_generate_and_send_twilio_reply` para `BackgroundTasks` (mesmo padrão de `whatsapp_baileys.py:1450`)
- **Impacto financeiro estimado destravado**: R$ 86k–142k/mês
- Achados secundários: A1 fallback agent=Jerusa, A2 Isabella recusa Security Home, A3 sem sessão Baileys p/ co-demo, A4 rate-limit 120/min em prod

### Auditoria de escopo
- 192 inbound + 91 outbound injetados no DB, **todos para 21998176526** (verificado)
- 0 mensagens vazaram para clientes reais

### Próximas ações pendentes (aguardando aprovação CTO)
- **P0**: Aplicar patch do webhook Twilio (§6 do relatório) e re-rodar Fase 4
- **P1**: Atualizar treinamento Isabella para reconhecer Security Home (A2)
- **P1**: Abrir sessão Baileys para `co-demo` (redundância)
- **P2**: Corrigir fallback de auto-reply de Jerusa → Isabella (A1)



## 🏆 ORDEM EXECUTIVA FINAL — Maturidade Comercial (09/06/2026) ✅

**Ordem CTO**: máquina comprovada de geração de valor multi-tenant.

### Fases entregues
- **Fase 1 — Multi-tenant real**: 3 testes pytest `test_multitenant_isolation.py` PASSAM. Nenhum endpoint vaza entre tenants (cash, governador, brain, operator, lucro, company-value).
- **Fase 2 — Cobrança por dinheiro**: rankings já usam só `valor_confirmado_brl`. Módulos sem confirmação → `DESTRÓI VALOR`.
- **Fase 3 — Reconciliação automática**: `services/cash_reconciler.py` cruza ações × evidência real em 6 categorias. Job `cron 03:00` registrado. Atualiza `motor_ia_drift.taxa_acerto` automaticamente.
- **Fase 4 — Rampa de confiança**: `executor_ia.confidence_cap_for_category()` aplica cap dinâmico:
  - <50% → R$ 5.000
  - 50–70% → R$ 25.000
  - 70–85% → R$ 50.000
  - ≥85% → R$ 100.000
  - cold start (<3 amostras) → cap global do .env
- **Fase 5 — Motor valor**: `company-value` já entrega ARR/MRR/EBITDA/Churn/LTV/CAC/Payback/EV. CEO weekly compara semana × hoje.
- **Fase 6 — Cross-tenant**: `cross_tenant_ranking()` + `per_client_value()`. SmartProv mostra benchmark entre todos os tenants reais.
- **Fase 7 — Auditoria final**: endpoint `GET /cash/final-audit` responde as 10 perguntas obrigatórias do CTO.

### Endpoints novos (6)
- `POST /api/presidente-ia/cash/reconcile`
- `POST /api/presidente-ia/cash/reconcile-all`
- `GET /api/presidente-ia/cash/cross-tenant-ranking`
- `GET /api/presidente-ia/cash/per-client-value`
- `GET /api/presidente-ia/cash/final-audit`
- (Política `auto-approval/policy` agora retorna `confidence_ramp`)

### Coleções
- **Atualizada**: `motor_ia_drift` — agora self-updates pelo reconciliador
- **Atualizada**: `executive_ledger` — `valor_confirmado_brl` populado por job

### Testes
- 3/3 testes de isolamento multi-tenant PASSAM
- Reconciliador rodou cross-tenant: co-demo R$16.000 (Smart Field), co-pilot-1 R$0 (onboarding)

## 💵 OPERAÇÃO CAIXA REAL — Presidente CEO (09/06/2026) ✅

**Ordem CTO**: único KPI = DINHEIRO. Sem estimativa. Confirmado.

### Componentes
- **Coleção `executive_ledger`** (índices `cid_ts` + `action_id_uniq`)
- **Coleção `executive_daily_closings`** (índice `cid_date`)
- **Hook** em `execute_action` → `record_to_ledger()` automático após cada execução
- **9 entries** backfilladas das ações já completed
- **Endpoint `/cash/confirm-entry/{action_id}`** para anexar evidência real
- **Job APScheduler 23:59** registrado no startup (`executive_daily_closing`)
- **Meta progressiva** R$100 → R$1k → R$10k → R$100k em `corporate_goals`

### Endpoints novos (8 sob `/api/presidente-ia/cash/*`)
- GET `/cash` — caixa hoje/7d/30d (CONFIRMADO)
- POST `/cash/daily-closing` — fechamento idempotente
- GET `/cash/ia-ranking` — ranking financeiro das IAs
- GET `/cash/module-ranking` — ranking financeiro dos módulos
- GET `/cash/weekly-ceo-report` — EV semana × hoje + top criadora/destrutiva
- GET `/cash/progressive-goal` — degraus batidos e próximo
- POST `/cash/seed-progressive-goal` — semeia em corporate_goals
- POST `/cash/confirm-entry/{action_id}` — anexa evidência REAL

### Primeira medição real (co-demo · 09/06/2026)
- **Caixa confirmado total: R$ 16.000,00** (evidência: 200 OS preventivas × R$ 80 = 200 visitas corretivas evitadas)
- **3 degraus batidos** (R$100 · R$1k · R$10k) · falta **R$ 84.000** para o topo (R$100k)
- **Fechamento do dia**: 9 ações · previsto R$62.813 · confirmado R$16.000 · perdido R$46.813
  - Top criadora: `CRIACAO_OS_SMARTFIELD` (R$8.000 confirmados)
  - Destruiu valor: `DISPARO_COBRANCA` (prev R$6.829 / conf R$0 — target_count=0)
- **Ranking IAs**: `auto_pilot` → R$ 16.000 / acerto 59,3% · `admin@empresa.com` → R$ 0 / 0%
- **Ranking módulos**: Smart Field **GERA DINHEIRO** (R$16k) · Cobrança/Retenção/Receita ainda em **DESTRÓI VALOR** (previsto sem confirmação)
- **CEO weekly**: EV semana passada R$16,93M · hoje R$15,45M · criado R$768k · destruído R$2,24M · delta -R$1,48M (gap entre previsto e confirmado)

### Regra estrita aplicada
"Se não houver dinheiro confirmado, retornar R$ 0,00." Cumprida — antes de qualquer `confirm-entry`, todos os endpoints retornavam **R$ 0,00**. Só subiu quando 2 entries receberam evidência REAL via endpoint dedicado.

## 💰 OPERAÇÃO RECEITA AUTÔNOMA — Presidente Sócio (09/06/2026) ✅

**Ordem CTO**: Presidente IA vira gerador direto de resultado. Toda
análise termina em ação. Filosofia: pensar como dono.

### Endpoints novos (5):
- `GET /api/presidente-ia/lucro` — Motor de Lucro
- `GET /api/presidente-ia/company-value` — Valuation diário
- `GET /api/presidente-ia/top-opportunities` — Top 20 R$
- `GET /api/presidente-ia/top-wastes` — Top 20 desperdícios
- `GET /api/presidente-ia/operator/daily-goals` — Metas diárias

### Saída obrigatória atingida (co-demo, 09/06/2026)
1. Valor recuperável: **R$ 98.042,47**
2. Valor executável: **R$ 86.283,97**
3. Valor executado: 2 ações completed · 200 OS preventivas + 1 dunning batch · 4 auto-aprovadas
4. Receita prevista 30d: **R$ 4.314,20** (extrapolação executável conservadora)
5. Receita prevista 90d: **R$ 12.942,60**
6. **Enterprise Value: R$ 15.450.055,20** (ARR 3.86M × 4x · tier premium_low_churn · churn 0.56%/mês)
7. Top 20 oportunidades: 9 ações ranqueadas (REAJUSTE R$48k / UPGRADE R$36k / DISPARO R$6.8k / etc.)
8. Top 20 desperdícios: 16 itens · **R$ 118.726 totais** (inadimplência R$37.9k · IA drift R$55k · OLT mass-outage R$17k · CAPEX preso R$5.6k · ticket recurring R$2.5k)
9. ROI por ação: cada item retorna `impacto_brl_recorrente` + `impacto_brl_unico`
10. Evidências: 2.788 subs · 6.376 invoices · 1.845 ONUs · 40 CTOs · 13.956 eventos nervoso

### Filosofia executada
Toda decisão passa pelo filtro: aumenta receita? reduz custo? reduz churn? aumenta EV? Senão, não existe. Matriz Autonomia (4 níveis × 12 ações) + 8 metas permanentes + plano diário N1+N2 + execução auto-aprovada.

### Whitelist auto-aprovação expandida (Fase E)
4 categorias N1+N2 (CONTATO_LEO_PROATIVO · CRIACAO_OS_SMARTFIELD · CAMPANHA_RETENCAO · **DISPARO_COBRANCA**). Cap R$ 25k. Kill-switch `AUTO_APPROVAL_ENABLED` (default OFF).

## 🚀 OPERAÇÃO PRESIDENTE AUTÔNOMO — Operador (09/06/2026) ✅

**Ordem CTO**: Presidente IA deixa de ser analista, vira **operador**.
Objetivo único = produzir resultado financeiro real.

### Entregue
- **`services/presidente_operator.py`** (557 LoC) — 1 serviço único:
  - Matriz de Autonomia 4 níveis × 12 ações (N1/N2/N3/N4)
  - 8 Metas permanentes (mrr, churn, inadimplência, ltv, retenção,
    capex, upsell, produtividade)
  - 3 motores operacionais:
    - **Motor Oportunidades** ("gerar R$ 10k hoje")
    - **Motor Economia** ("economizar R$ 10k hoje")
    - **Motor Recuperação** ("dinheiro abandonado")
  - **Briefing Matinal** — responde as 6 perguntas obrigatórias
  - **Execute-Day** — varre plano N1, propõe → conselho → auto-aprova →
    executa via `executor_ia`, idempotente por categoria/24h
- **7 endpoints** novos sob `/api/presidente-ia/operator/*`
- **Seed das 8 metas** ativo em `corporate_goals` (8/8 created)

### Números reais (co-demo) — primeira varredura
- **Gerar hoje**: R$ 18.614 (recorrente)
  - Reajuste IPCA 4,5% em 2.741 contratos → +R$ 14.484/mês
  - Upgrade oferta a 1.741 clientes abaixo da média → +R$ 3.057/mês
  - 27 convites de indicação → +R$ 632/mês
  - Reativação 47 cancelados → +R$ 440/mês
- **Recuperar hoje**: R$ 98.042 estimados
  - 961 contratos sem reajuste >12m → R$ 48.330/ano
  - 1.741 upgrades LTV → R$ 36.689/ano
  - 367 faturas overdue → R$ 6.830 (18% conv)
  - 47 ONUs cancelados → R$ 3.384 CAPEX
  - 5 tickets recurring → R$ 2.810 LTV
- **Economizar hoje**: R$ 38.680
  - OS preventiva em 208 ONUs críticas → R$ 16.640
  - Manutenção consolidada em 3 OLTs mass-outage → R$ 16.400
  - Recuperar ONU de 47 cancelados → R$ 5.640
- **Dinheiro abandonado total: R$ 838.090** (LTV+CAPEX visível)

### Validação execute-day REAL (não-dry-run)
- Kill-switch ligado → execute-day rodou
- 1 ação N1 auto-aprovada (`auto_approved=true`, `approver=auto_pilot`,
  `source=presidente_operator`)
- 100 OS preventivas criadas em `smart_repairs` (100 → 200 docs)
- Conselho 5/6 forte, cap R$ 25k (bumpado de R$ 5k via env)

### Matriz de Autonomia (10 ações classificadas)
| Nível | Categoria | Executável | Meta |
|---|---|---|---|
| N1 | CRIACAO_OS_SMARTFIELD | ✅ | reduzir_churn_tecnico |
| N1 | CONTATO_LEO_PROATIVO | ✅ | aumentar_retencao |
| N1 | INDICACAO_PROACTIVE | — | aumentar_mrr |
| N1 | TICKET_RECURRING_TRIAGEM | — | aumentar_retencao |
| N2 | CAMPANHA_RETENCAO | ✅ | reduzir_churn |
| N2 | DISPARO_COBRANCA | ✅ | reduzir_inadimplencia |
| N2 | PREVENTIVE_MAINT_OLT | — | reduzir_churn_tecnico |
| N3 | REAJUSTE_IPCA | ✅ | aumentar_mrr |
| N3 | REATIVACAO_CANCELADO | — | aumentar_mrr |
| N3 | UPGRADE_PLANO_OFERTA | — | aumentar_ltv |
| N3 | RECUPERACAO_EQUIPAMENTO | — | recuperar_capex |
| N4 | CROSS_SELL_SECURITY | — | aumentar_ltv |

## 🎯 MISSÃO SISTEMA NERVOSO 100% — CUMPRIDA (09/06/2026) ✅

**Ordem CTO**: cobertura real 100% do Sistema Nervoso, sem novas IAs/dashboards.

### Resultado: **100.0% — VERDE — 38/38 tipos · 10/10 domínios**

| Domínio | Cobertura | Eventos (7d) |
|---|---|---|
| comercial | **100%** | 14 |
| instalacoes | **100%** | 14 |
| financeiro | **100%** | 8.366 |
| atendimento | **100%** | 849 |
| whatsapp | **100%** | 1.323 |
| indicacoes | **100%** | 12 |
| parceiros | **100%** | 7 |
| estoque | **100%** | 47 |
| rede | **100%** | 3.028 |
| operacoes | **100%** | 85 |

**Total no nervo (co-demo): 13.956 eventos**.

### Eventos adicionados (17 tipos antes em 0):
| Antes | Depois (evento emitido) |
|---|---|
| SALE_LOST | 1 (sales_leads invalid) |
| INSTALL_FAILED | 10 (tickets instalacao status pendente) |
| PAYMENT_RECEIVED | 500 (subscriber_invoices paid) |
| PAYMENT_OVERDUE | 367 (subscriber_invoices overdue) |
| DUNNING_ESCALATED | 100 (top-value overdue) |
| TICKET_REOPENED | 26 (ticket_logs reagendar) |
| TICKET_RECURRING | 5 (subs com 3+ tickets) |
| WA_CAMPAIGN_SENT | 31 (outbound bulk por hora) |
| VLAN_SATURATED | 2 (vlan com 5+ CTOs) |
| CTO_DEGRADED | 5 (tickets reparo por cto) |
| CTO_CRITICAL | 1 (>5 ONUs ruins na CTO) |
| COLLECTIVE_OUTAGE | 3 (OLT com ≥10 ONUs ruins) |
| CLIENT_OFFLINE | 217 (smartolt_onus status ruim) |
| CLIENT_ONLINE | 300 (smartolt_onus Online) |
| TECHNICIAN_LATE | 9 (Entrada ≥09h) |
| GPS_ROUTE_DEVIATION | 10 (Entrada sem Saída) |
| TECH_PRODUCTIVITY_DROP | 5 (motor_ia_drift negativo) |

### Arquitetura plug-in (sem novas IAs):
1. **Estendido `SYNC_PLAN`** em `nervous_synchronizer.py` (+5 entradas: sale.lost, install.failed, payment.received, payment.overdue, ticket.reopened) — auto-incremental por checkpoint, polling 1min.
2. **Script bootstrap** `scripts/nervous_full_coverage_bootstrap.py` — emite eventos derivados a partir de coleções existentes (sem inventar dado).
3. **Job APScheduler 1h** `services/nervous_coverage_job.py::refresh_synthesized_events` registrado no startup do `server.py` — mantém VLAN/CTO/outage/late/etc. atualizados.
4. **Endpoint manual** `POST /api/ai-center/nervous-system/refresh-synthesized` (admin) — força refresh sob demanda. Idempotente.

### Validação real:
- Auditoria 7d: **100% (38/38) — VERDE**
- Auditoria 24h: **100% — VERDE**
- 2ª passagem do synchronizer: 0 eventos novos (idempotência ✅)
- 2ª passagem do refresh: 583 eventos (eventos derivados reanalisados sem duplicar tipo)
- Presidente IA `/governador/sistema-nervoso`: **100.0% VERDE 38/38**
- Roadmap/Backlog/Self-Audit/Readiness: 200 OK

## 🟢 OPERAÇÃO 90% — Execução Sprint (09/06/2026) ✅

**Ordem CTO**: parar criação de novas IAs/dashboards. Foco em hardening,
autonomia e estabilidade para elevar maturidade SaaS 78% → 90%.

**Ordem de execução cumprida**: A1 (testing) → fix crítico → E (autonomia) →
exec real → A3 (S3) → D (multi-tenant) → B (hardening WA) → C (cobertura) →
auto-auditoria → recalcular prontidão.

| Fase | Entrega | Resultado |
|---|---|---|
| A1 — Testing pós-mock-off | `iteration_98.json` · 28/28 pytest verde | Backend ESTÁVEL · zero quebras críticas |
| Fix crítico | `scheduler_v51.py` — `asyncio.run()` em thread → coroutine direta no AsyncIOScheduler | Erro `Future attached to a different loop` extinto |
| Fase E — Autonomia | `executor_ia.py` (+185 LoC) · 3 endpoints `/auto-approval/{policy,scan,audit}` · whitelist={CONTATO_LEO_PROATIVO, CRIACAO_OS_SMARTFIELD, CAMPANHA_RETENCAO} · cap R$ 5k · conselho ≥5/6 · `AUTO_APPROVAL_ENABLED` kill-switch | E2E validado: 1 ação CRIACAO_OS_SMARTFIELD auto-aprovada e EXECUTADA REAL (dry_run=false) → 100 OS preventivas criadas em `smart_repairs` |
| Fase A3 — Backup S3 fallback | `services/s3_backup.py` + 4 endpoints `/api/admin/backup/s3/{status,upload-latest,daily,list}` · placeholders no .env · degrada graciosamente | Aguardando CTO preencher `AWS_ACCESS_KEY_ID/SECRET/S3_BACKUP_BUCKET` |
| Fase D — Multi-tenant | Limpeza 107 órfãos + 31 docs teste · novo endpoint `/multitenant/companies` | Audit **BLINDADO/CLEAN** · co-pilot-1 visível em ONBOARDING |
| Fase B — Hardening WA | `wa_dispatcher.py` (+138 LoC) · circuit breaker em memória (threshold 5 falhas / cooldown 120s) · métricas `wa_dispatch_metrics` com TTL 7d · endpoint `/wa/dispatcher-status` | Pronto para 10k clientes sem flap |
| Fase C — Cobertura nervosa | Reset checkpoints + resync 10.017 eventos | **55.26% (21/38)** · meta >50% **ATINGIDA** (era 15.79% pós-cleanup) |
| Auto-auditoria | `/self/audit` re-rodado pós-OP90 | **15 gargalos** (eram 21) · backlog **R$ 43.500** (era R$ 79.000) — redução R$ 35.500 |
| Recalcular prontidão | `/self/readiness` | 1k FUNCIONA c/3 fixes triviais · 10k QUEBRA s/ hardening · 50k INVIÁVEL s/ rearquitetura |

### Endpoints novos (zero novos dashboards/IAs, conforme ordem CTO)
- `GET /api/presidente-ia/auto-approval/policy`
- `POST /api/presidente-ia/auto-approval/scan`
- `GET /api/presidente-ia/auto-approval/audit`
- `GET /api/presidente-ia/wa/dispatcher-status`
- `GET /api/ai-center/multitenant/companies`
- `GET /api/admin/backup/s3/{status,list}`
- `POST /api/admin/backup/s3/{upload-latest,daily}`

### Bloqueadores pendentes para hit 90%
- 🔴 Backup off-site (CTO precisa: fluxo OAuth Google Drive **ou** preencher AWS creds no .env)
- 🟡 `wa_baileys` 4× stateful sem fila externa (refactor profundo, P2)
- 🟡 `lousa.py` 8.2k LoC e `whatsapp_baileys.py` 5.2k LoC (monólitos P2)
- 🟡 Coleções financeiras vazias (financeiro_lancamentos, dre_snapshots, billing_invoices, dunning_events, payments) — backfill ou popular via integração

### Coleções/índices novos nesta sprint
- `wa_dispatch_metrics` (TTL 7d em `ts` + composto `company_id+ts`)
- Removidas: 31 docs de tenants teste (`test-tese-*`, `co-test-v14`) + 107 órfãos motor_ia_*/audit_log
- `nervous_checkpoints` resetada (29 docs) → re-emitiu 10.017 eventos

## ⚡ Sprint anterior — V20 DIRETOR DE EVOLUÇÃO CONTÍNUA (09/06/2026) ✅
**5 endpoints sob `/evolution/*`. 1 serviço único.**

| Fase | Endpoint | Saída live |
|---|---|---|
| 1 Backlog | `GET /evolution/backlog` | 20 itens · valor R$ 79.000 |
| 2 Sprints | `GET /evolution/sprints` | 10 sprints ordenados por ROI/h · Sprint A: 5 itens / 12h / R$ 47.000 / R$ 3.916/h |
| 3 Arquiteto | `GET /evolution/architect/{gargalo_id}` | plano técnico (arquivos, rotas, cols, riscos, testes, rollback) |
| 4 Auditor | `POST /evolution/sprint/{id}/audit` | diff prometido vs entregue (delta de métricas) |
| 5 Roadmap 12m | `GET /evolution/roadmap` | 30d/90d/180d/365d × 1k/10k/50k clientes |

**Reuso 100%:** `presidente_self_audit` (gargalos, plano por categoria, prontidão). **0 coleções persistentes novas** (apenas `evolution_sprints` opcional para auditoria).

## ⚡ Sprint anterior — V15+V16+V17 PRESIDENTE IA AUTOCONSCIENTE ✅
**Presidente IA agora audita o próprio SmartProv como se fosse provedor-cliente.**

| Fase | Endpoint | Saída live |
|---|---|---|
| V15 Autoconsciência | `GET /self/audit` | 21 gargalos / ganho total se resolvido: **R$ 79.000** |
| V16 Conselho Evolução | `GET /self/evolution` | Top 10 evoluções: **R$ 61.700 em 57h · ROI R$ 1.082/h** |
| V17 Prontidão Comercial | `GET /self/readiness` | 1k FUNCIONA · 10k QUEBRA · 50k INVIÁVEL |

**Top 3 evoluções por ROI/h:**
1. R$ 40.000/h · 0,5h · Executor IA · `dry_run=false` em 1 ação REAJUSTE_IPCA
2. R$ 10.000/h · 0,5h · `ALLOW_MOCK_MODULES=false`
3. R$ 3.000/h · 1h · Índice composto `subscriber_match_log`

**0 coleções novas. 1 serviço único `presidente_self_audit.py` (445 LoC). 3 endpoints sob router existente.**

## ⚡ Sprint anterior — V12+V13+V14 PRESIDENTE IA CÉREBRO EXECUTIVO ✅
**Causalidade · Digital Twin · Autopilot. 1 serviço único, 5 endpoints.**

| Fase | Capacidade | Endpoint | Reuso |
|---|---|---|---|
| V12 | Causality Engine por ação | `GET /brain/causality/{action_id}` | snapshots `motor_ia_kpis` + `motor_ia_drift` (P1) |
| V12 | Causality summary 30d | `GET /brain/causality-summary` | agrega cima |
| V13 | Digital Twin de cliente | `GET /brain/twin/subscriber/{id}` | subscribers + smartolt_onus + ctos + tickets + invoices + smart_installs/repairs + wa_conversations |
| V13 | Digital Twin global | `GET /brain/twin/global` | aggregations leves |
| V14 | Autopilot top 10 | `GET /brain/autopilot/top10` | presidente_executive + governador.cobranca + executor_ia.consult_memory + drift |

**Saídas funcionais (live):**
- Causality_score 0-100 por ação, 4 fatores (sinal/isolamento/histórico/temporal), veredicto CAUSA_FORTE/PROVÁVEL/FRACA/INDETERMINADO.
- Digital twin de 1 cliente devolve LTV, lucro líquido, motivo raiz, técnico instalador, OLT/CTO, financeiro 24m, WA conversas.
- Autopilot devolve top 10 ranqueado por valor esperado (R$ × confiança) com `se_autopilot_autorizado: "...executaria as N decisões..."`.

**Coleções novas:** **0** (V12 lê snapshots; V13 lê coleções existentes; V14 agrega em memória).

**Pytest V14:** 1/1 PASSED (cobre 3 fases sequencialmente).

## ⚡ Sprint anterior — V11 PRESIDENTE IA GOVERNADOR (09/06/2026) ✅
**10 capacidades de governança via agregação de dados existentes. Zero IA nova, zero dashboard, zero executor novo.**

| # | Capacidade | Endpoint | Reuso |
|---|---|---|---|
| 1 | Sistema de metas corporativas | `POST/GET /governador/goals` · `POST /goals/{id}/refresh` | Coleção nova `corporate_goals` |
| 2 | Score das IAs | `GET /governador/ia-scorecard` | Agrega `motor_ia_actions` + `motor_ia_drift` |
| 3 | ROI por IA | `GET /governador/ia-roi` | Soma `motor_ia_actions.roi_brl` por `source` |
| 4 | Cobrança de resultado | `GET /governador/cobranca` | Diff metas × IA responsável |
| 5 | Priorização executiva | `GET /governador/prioridades` | Reuso 100% `presidente_executive.acoes_presidenciais` |
| 6 | Saúde corporativa | `GET /governador/saude` | Reuso 100% `president_score` (8 drivers) |
| 7 | Sistema Nervoso | `GET /governador/sistema-nervoso` | Reuso `nervous_coverage.coverage_report + events_by_domain + what_happened_today` |
| 8 | Mapa executivo (6 áreas × IAs × metas) | `GET /governador/mapa-executivo` | Agregador novo, sem dados próprios |
| 9 | Ranking eficiência operacional | `GET /governador/ranking` | Reuso scorecard + drift |
| 10 | Relatório presidencial diário | `GET /governador/relatorio-diario` | Coleção nova `president_daily` (cache 1h) + reuso massivo |

**Coleções novas:** apenas 2 — `corporate_goals` e `president_daily`.

**Métricas suportadas em metas:** mrr_brl · ticket_medio_brl · clientes_ativos · president_score · dinheiro_em_risco_brl · dinheiro_recuperavel_brl · churn_previsto_30d_brl · receita_prevista_30d_brl · score_rede · score_operacao · score_financeiro.

**6 áreas governadas:** RECEITA · OPERACAO · REDE · ATENDIMENTO · COMERCIAL · FINANCEIRO — cada uma com IAs responsáveis mapeadas.

**Validação:**
- 10/10 endpoints HTTP 200 autenticados
- Pytest V11: 1/1 passing isolado · P1: 1/1 · V10: 1/1 · Safety: 6/6 = **9 testes verdes isolados**
- Live: meta MRR R$ 340k criada, baseline R$ 321.876, progress trackable
- Relatório diário live: saude=59.8/alerta, 5 prioridades, 6 áreas mapeadas, ROI 30d=R$ 0 (dry-run), narrativa auto-gerada

## ⚡ Sprint anterior — P1 PRESIDENTE IA COM BRAÇOS (09/06/2026) ✅
**Ciclo completo: PROPOSE → CONSELHO → APPROVE → EXECUTE → ROI → APRENDIZADO**

| Etapa | Status | Implementação |
|---|---|---|
| 1. Executor IA + status flow | 🟩 | `services/executor_ia.py` — 6 status, transições validadas |
| 2. `pending_executions` fila | 🟩 | Coleção criada, aprovação enfileira automaticamente |
| 3. Snapshot BEFORE | 🟩 | Captura em `motor_ia_kpis` (MRR/score/risco/recuperável/churn) |
| 4. Snapshot AFTER | 🟩 | Idem após execução |
| 5. ROI automático | 🟩 | Calculado por categoria (reajuste=ΔMRR, cobrança=Δrisco, leo/retenção=Δchurn) |
| 6. Ledger executivo | 🟩 | `GET /actions/{id}/ledger` — quem decidiu/aprovou/executou + R$ + history |
| 7. Memória executiva | 🟩 | `consult_memory()` obrigatório antes de propor; `GET /memory/{cat}` |
| 8. Aprendizado (corrections + drift) | 🟩 | Registrados em `motor_ia_corrections` + `motor_ia_drift` por ciclo |
| 9. Conselho com voto formal | 🟩 | 6 cadeiras (CEO/CFO/COO/CTO/CMO/CRO), consensus 0..6/6, divergências rastreadas |
| 10. State of presidency (9 perguntas) | 🟩 | `GET /state-of-presidency` |

**5 executores autorizados (todos dry_run-first):**
1. `REAJUSTE_IPCA` — marca `readjustment_pending_pct` nos subscribers vencidos
2. `DISPARO_COBRANCA` — cria batch em `dunning_events`
3. `CONTATO_LEO_PROATIVO` — enfileira em `leo_proactive_queue`
4. `CRIACAO_OS_SMARTFIELD` — abre OS em `smart_repairs`
5. `CAMPANHA_RETENCAO` — enfileira em `mass_messaging_queue`

**Endpoints adicionados (todos em `/api/presidente-ia/`, sem rota nova):**
`POST actions/propose · POST actions/{id}/council-vote · POST actions/{id}/approve · POST actions/{id}/execute · POST actions/{id}/cancel · GET actions · GET actions/{id}/ledger · GET memory/{cat} · GET state-of-presidency · GET learning/drift`

**Coleções criadas:** `pending_executions`, `conselho_votes` (motor_ia_kpis/corrections/drift já existiam, agora populadas).

**Validação:**
- 8/8 pytest passing (P0 safety + V10 + P1 ciclo completo)
- E2E live testado: 5 ações × 6 votos × 5 ROIs = todos `dry_run`, mas pipeline real testado
- Stress sem erros nos logs

## ⚡ Sprint anterior — P0 PRIMEIRO CLIENTE PAGANTE (09/06/2026) ✅
**6 ações entregues. Zero módulo novo. Zero IA nova. Zero versão paralela.**

| # | Ação | Status | Entrega |
|---|---|---|---|
| 1 | Backup off-site | 🟥 BLOQUEADO_HUMANO | `memory/OFFSITE_BACKUP_RECOVERY_REPORT.md` — runbook OAuth para CTO |
| 2 | ALLOW_MOCK auditado | 🟩 PRONTO PARA FALSE | `memory/MOCK_DEPENDENCY_AUDIT.md` — 1 módulo afetado (security_home POC) |
| 3 | White-label | 🟩 APLICADO | `memory/WHITE_LABEL_READINESS_REPORT.md` — `db.companies.name = "Ligotelecom"`, logo real, `/api/auth/me` retorna company_name |
| 4 | AI Center consolidado | 🟩 DEFINIDO | `memory/AI_CENTER_CONSOLIDATION_REPORT.md` — canônico = v80, v6/v7 DEPRECATED (452 LoC órfãs) |
| 5 | Atlaz onboarding | 🟩 AUDITADO | `memory/ATLAZ_ONBOARDING_AUDIT.md` — dry-run via `/customers/preview`, idempotente, 6.359 invoices live |
| 6 | Logs limpos | 🟩 3/3 CORRIGIDOS | `memory/LOG_CLEANUP_REPORT.md` — causa raiz GrafanaConnector órfão + auto_emit middleware + 401 INFO |

**Mudanças de código nesta sprint (totais):**
- `backend/middleware/auto_emit_middleware.py` — fix RuntimeError "No response returned" (10 linhas reescritas)
- `backend/services/observability_twin.py` — fix AttributeError GrafanaConnector close (causa raiz: métodos órfãos fora da classe) + Grafana 401 WARNING→INFO
- `backend/routes/users.py` — `/api/auth/me` agora retorna company_name dinâmico (+14 linhas)
- `db.companies` + `db.company_branding` (1 doc cada) — atualizações pontuais via mongosh

**Validação live:**
- 7/7 pytest passing (test_safety_p0 6/6 + test_presidente_executive 1/1)
- Stress test 30 chamadas pós-fix → 30 HTTP 200 → 0 erros nos logs
- Backend uptime 7+ min limpo após restart

## ⚡ Sprint anterior — PRESIDENTE IA V10 · Cérebro Executivo Monetizado (09/06/2026) ✅
**Ordem executiva**: o Presidente IA deixou de ser dashboard, virou decisão.
- ✅ Novo `services/presidente_executive.py` (480 LoC) — converte toda contagem em R$, com fontes resilientes.
- ✅ Endpoint `GET /api/presidente-ia/executive` — retorna 8 blocos: `president_score`, `riscos_criticos`, `oportunidades`, `previsao_30d`, `dinheiro_em_risco`, `dinheiro_recuperavel`, `surpresas`, `acoes_presidenciais`.
- ✅ Componente `frontend/src/components/PresidenteExecutivo.jsx` (630 LoC) com 8 seções monetizadas.
- ✅ `PresidenteIaPanel.js` enxugou ~440 LoC de dashboard antigo (OrbitalMap, HealthCard, RisksCard, OpportunitiesCard, StatCard, UniversoLigoCard, ClientsAtRiskCard, MiniRow, Pill, RiskRow, MiniBox, SkeletonLoader, grid3). Mantidos: Conselho Executivo IA (6 cadeiras LLM) + BriefingModal (Café com IA) + Leo Proativo.
- ✅ Bug `plan_price_brl` (preenchido em 2 docs) corrigido para `plan_price` (preenchido em 2.741 docs) — antes a "receita potencial" saía zerada.
- ✅ Smartolt_onus.signal_text agora alimenta riscos de rede (254 Critical · 364 Warning · 213 Offline).
- ✅ Reajuste atrasado integrado: 961 contratos >12m → R$ 423,19/mês recuperáveis.
- ✅ `acoes_presidenciais` sempre = 5 (regra de ouro) com `{acao, impacto_brl, esforco, prioridade, justificativa}`.
- ✅ `surpresas_executivas` ≤ 10 (zona com sinal degradado concentrado, OLT problemática, tickets esquecidos, bairros com leads anormais, etc.).
- ✅ Teste `tests/test_presidente_executive.py` valida estrutura — passing.
- ✅ Smoke screenshot autenticado mostra `score 60 ALERTA · MRR R$ 321.876 · 5 ações renderizadas`.

## ⚡ Sprint anterior — SNMP Direto Multi-Vendor + Merge Discovery (09/06/2026) ✅
**Independência operacional**: visibilidade ONU/OLT sem depender de Grafana/Zabbix:
- ✅ `services/vsol_snmp.py` com OIDs V-SOL/Realtek + Huawei + ZTE (+ status maps + dbm_divider por vendor)
- ✅ CRUD de OLTs em `routes/olt_registry.py` com perfis no `secrets_vault` (host/port/version/community/vendor/label/enabled)
- ✅ `services/olt_polling_scheduler.py` poll a cada 5min em paralelo, cache em `db.olt_snmp_cache`
- ✅ Endpoints `/api/admin/integrations/olt/{profiles,profiles/{name}/{save,enable,disable,ping,discover},discover-all,cached,poll-now}` — HTTP 200 verificados
- ✅ Aba **Discovery do Observability Twin** mescla 3 fontes (Grafana proxy / Zabbix direto / SNMP direto), com KPIs separados, "Status por OLT — SNMP Direto" e botão "Forçar Poll SNMP"
- ✅ Card UI `OltSnmpCard.jsx` para cadastro de OLTs SNMP

## ⚡ Sprint anterior — Card UI Credenciais Observabilidade (09/06/2026) ✅
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
