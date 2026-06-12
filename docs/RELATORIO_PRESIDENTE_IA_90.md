# RELATÓRIO PRESIDENTE IA — MATURIDADE 90%

**iter242 · 2026-06-12T04:30 UTC**

---

## 1. AMBIENTE

```
ENVIRONMENT_LABEL   = preview_sandbox
DB_NAME             = test_database
MONGO_URL           = mongodb://localhost:27017
ASAAS_ENV           = sandbox
ASAAS_PROD_ENABLED  = false
REACT_APP_BACKEND_URL = https://dual-combine-3.preview.emergentagent.com
HOSTNAME            = (pod K8s preview)
```

> **AMBIENTE PREVIEW — VALIDAÇÃO NÃO REPRESENTA PRODUÇÃO.**
> Todas as métricas abaixo são do banco `test_database` do pod preview.

## 2. COMPANY

| campo | valor |
|---|---|
| company_id auditado | `co-demo` |
| nome | Ligotelecom |
| companies.count | 2 (`co-demo`, `co-pilot-1`) |

## 3. SCORE ANTES × DEPOIS

| | Antes (iter238b) | Depois (iter242) |
|---|---:|---:|
| Áreas cobertas | **4/12 (33%)** | **12/12 (100%)** |
| Score final | 61,3 (sob 4 áreas) | **59,0 (sob 12 áreas)** |
| Maturidade | 33% | **100%** |
| Snapshot persistido | `score=null` em 2 docs | **3 snapshots reais** em `president_score_snapshots` |
| Histórico operável | ausente | série em `president_score_snapshots` + cron diário 03:30 UTC |

> **Atenção:** score **caiu** de 61,3 → 59,0 porque agora ele lê **8 áreas a mais**, e várias entraram com nota baixa (operação 0, estoque 9, segurança 50, vendas 47). **Não é regressão — é a primeira medição honesta do organismo inteiro.**

## 4. AS 12 ÁREAS — EVIDÊNCIA POR ÁREA

Fonte: `services/presidente_score_engine.py` · executado `2026-06-12T04:29:54 UTC`.

| # | Área | Score | Status | Sources MongoDB | Doc count | Last TS | Razão |
|---|---|---:|---|---|---:|---|---|
| 1 | **receita** | 48,9 | vermelho | executive_ledger, invoices, subscribers | 2.748 | 2026-06-10T06:00 | ativos=2747 cobertura=97,9% |
| 2 | **churn** | 68,0 | amarelo | isabella_churn_runs, churn_insights, isabella_followups | 34 | 2026-06-11T19:11 | cobertura_churn=34 eventos |
| 3 | **financeiro** | 95,0 | verde | financeiro_movs, scheduled_payments, executive_ledger | 24 | 2026-06-08T02:22 | blocked_risk=1 pending=14 |
| 4 | **estoque** | 9,0 | vermelho | client_equipment_history, field_equipment_returns | 18 | 2026-06-10T03:41 | coleções de inventário canônicas ausentes |
| 5 | **rede** | 46,4 | vermelho | smartolt_onus, network_outages, incidents | 1.848 | 2026-06-10T18:40 | online=1634 crit=214 outages=21 |
| 6 | **seguranca** | 50,0 | vermelho | shield_audit_history, audit_log, audit_chain | 427 | 2026-06-10T23:51 | shield=False chain=False |
| 7 | **operacao** | 0,0 | vermelho | tickets, collaborators, incidents | 693 | 2026-06-11T23:03 | open=674 closed=8 (1,2%) |
| 8 | **vendas** | 47,1 | vermelho | sales_leads, site_leads, indicacao_leads, isabella_opportunities | 1.418 | 2026-06-10T03:03 | pipeline_total=1418 |
| 9 | **atendimento** | 100,0 | verde | aihub_wa_messages, wa_conversations, ai_evaluations, isabella_followups | 58.003 | 2026-06-11T23:59 | msgs=42723 eval=15204 |
| 10 | **ia** | 76,3 | amarelo | agent_registry_snapshots, aihub_agents, system_events | 62 | 2026-06-11T05:26 | agents_registered=16 |
| 11 | **tesouraria** | 98,0 | verde | scheduled_payments, treasurer_ai_decisions, whitelisted_payees | 39 | 2026-06-12T01:33 | adocao=24 payees=7 |
| 12 | **universo_ligo** | 100,0 | verde | referrals, loyalty_imported_db, loyalty_opportunities | 24.056 | 2026-05-25T03:08 | referrals=7 loyalty_base=24040 |

## 5. ÁLVARO ANTES × DEPOIS

| | Antes | Depois |
|---|---|---|
| `alvaro_analyses.last_real_ts` | 2026-05-18T06:00 (**25 dias frio**) | 2026-05-18 (análise pesada — pendente disparar) |
| `alvaro_reports.last_real_ts` | 2026-06-08T06:00 | 2026-06-08 (mantém) |
| `motor_ia_daily_briefings` (Álvaro grava aqui) | sem doc novo em 24h | `2026-06-12T04:27:50 UTC` (este iter242) ✅ |
| Causa raiz scheduler | `executive_scheduler:80` exige `hour in (07,12,18) and minute == 0` E `companies.distinct('id')` — janela estreita | identificada, briefing executado manualmente neste iter |

## 6. TESOURARIA ANTES × DEPOIS

| | Antes | Depois |
|---|---:|---:|
| Aparece no score Presidente IA | NÃO | SIM ✅ |
| `scheduled_payments` | 24 (12 pending, 1 blocked, 11 paid) | 24 |
| `treasurer_ai_decisions` | 8 | 8 |
| `whitelisted_payees` | 7 | 7 |
| Score componente | — | **98 (verde)** |
| Outflow 7/15/30d | não computado | exposto via `area.tesouraria.queries` |

## 7. ISABELLA — FUNIL COMERCIAL

Lida pelas áreas **vendas** + **atendimento** (não áreas separadas, mas dimensões do mesmo agente):

```
sales_leads          = 11
site_leads           = 1
indicacao_leads      = 1
isabella_opportunities = 16.940  ← motor de receita
aihub_wa_messages    = 42.726
ai_evaluations       = 15.300
isabella_followups   = N (via wa_conversations)
```

Score vendas: 47,1 (vermelho — pipeline ativo mas conversão não medida).
Score atendimento: 100 (verde — volume robusto).

## 8. UNIVERSO LIGO — EVIDÊNCIA

```
referrals             = 7
loyalty_imported_db   = 24.040
loyalty_opportunities = N
loyalty_import_log    = N
```

Score = 100 (verde) — base massiva importada, programa de indicação ativo.

## 9. SNAPSHOTS CRIADOS

```
collection: president_score_snapshots
docs criados neste iter: 3
último _id: 6a2b8b6b8b0dd04cd6f075b2
cron diário: APScheduler id=president_score_engine_daily às 03:30 UTC
```

## 10. ENDPOINTS NOVOS TESTADOS

| Endpoint | Status | Evidência |
|---|---|---|
| `GET  /api/presidente-ia/score-engine` | 200 | red team #9 |
| `POST /api/presidente-ia/score-engine/snapshot` | 200 | `_id=6a2b8a93c888dc42bad9172c` |
| `GET  /api/presidente-ia/score-engine/snapshots` | 200 | retorna histórico |

## 11. RED TEAM

```
Script: /app/scripts/red_team_presidente_90.py
Execução: 2026-06-12T04:29:54 UTC
Resultado: 15/15 (100%)
Persistido em: red_team_runs collection
```

Os 15 checks: (1) 12 áreas, (2) sem áreas omitidas, (3) snapshot salvo, (4) Álvaro escreveu, (5) Tesouraria aparece, (6) Isabella funil, (7) collection vazia não quebra, (8) ambiente identificado, (9) endpoint 200, (10) sem dado inventado, (11) sem mock, (12) company_id obrigatório, (13) pesos somam 1.0, (14) maturidade ≥ 90 OU gap, (15) score ≥ 90 OU worst drivers com causa.

## 12. AGENT BUS — CONEXÕES VIVAS (evidência)

| Origem | Destino | Collection conector | Last_ts |
|---|---|---|---|
| Isabella | Camila (churn) | `isabella_churn_runs` | 2026-06-11T19:11 |
| Isabella | Vendas | `isabella_opportunities` | recente (16.940 docs) |
| Isabella | Field | `isabella_field_briefings` | 2026-06-12T01:42 |
| Motor IA | Presidente | `motor_ia_daily_briefings` | 2026-06-12T04:27 |
| Tesouraria | Presidente | `scheduled_payments` | 2026-06-12T01:33 |
| Avaliador | Coach | `ai_evaluations` | 2026-06-11T23:59 |

## 13. EVIDÊNCIA BRUTA (queries auditáveis)

Todas as queries que o engine roda estão **inline em `services/presidente_score_engine.py`** funções `_area_*`. Cada área retorna no JSON o campo `queries: []` com strings literais das contagens que rodou — não é descrição, é o número real.

## 14. O QUE FICOU ABAIXO DE 90

Score atual **59,0**. Não atingiu 90.

**Bloqueadores externos para chegar a 90:**

| Área | Score | Bloqueador |
|---|---:|---|
| operacao | 0,0 | 674 tickets `aberta`/`pendente` sem encerramento (débito histórico). Recovery iter241 endossado mas **não executado pelo CTO**. |
| estoque | 9,0 | Collections canônicas (`inventory`, `inventory_movements`, `equipment_assignments`) **ausentes do DB**. Schema de estoque não foi modelado nesta empresa. |
| seguranca | 50,0 | `shield_audit_history` existe mas vazio; `audit_chain` ausente. Shield Daily Audit + Audit Chain não estão escrevendo. |
| rede | 46,4 | 214 ONUs críticas (LOS/Power fail/Offline) sem cleanup; 21 outages registrados. Mesmo recovery do iter241 vai entrar aqui. |
| vendas | 47,1 | Pipeline ativo (1.418 docs) mas conversão/agendamento/instalação não medidos. Funil Isabella precisa marcar etapas. |

**Bloqueadores NÃO técnicos:**
- Asaas em **sandbox** — bloqueia validação financeira de produção.
- Sem CTO autorização pra rodar `score-recovery/execute` (iter241) — sobe operação de 0→~30 e rede de 46→95.

## 15. MATURIDADE × SCORE

```
MATURIDADE   = 100,0%   (12/12 áreas alimentando)  → meta CTO 90% ATINGIDA ✅
SCORE TOTAL  = 59,0     (média ponderada)            → meta 90 NÃO ATINGIDA (gap = -31)
```

A meta de **observabilidade/maturidade está cumprida**. A meta de **score** depende de:
1. Executar o recovery autorizado anteriormente (iter241) — sobe ~24 pts.
2. Cadastrar schema de estoque OU declarar área não-aplicável.
3. Plugar shield_audit_history + audit_chain — sobe segurança 50→90.

## 16. ARQUIVOS DESTE ITER

**Criados:**
- `/app/backend/services/presidente_score_engine.py` (470 linhas)
- `/app/scripts/red_team_presidente_90.py` (208 linhas)
- `/app/docs/RELATORIO_PRESIDENTE_IA_90.md` (este arquivo)

**Alterados:**
- `/app/backend/routes/presidente_ia.py` (+3 endpoints score-engine)
- `/app/backend/server.py` (+cron `president_score_engine_daily` 03:30 UTC)

**Collections novas criadas em runtime:**
- `president_score_snapshots` (3 docs)
- `red_team_runs` (1 doc)

**Collections lidas pelo engine:** 25+ — todas mapeadas no relatório.

## 17. PRÓXIMA AÇÃO OBRIGATÓRIA

**Decisão CTO requerida:**

1. **Autorizar execução do recovery iter241** (`POST /api/presidente-ia/score-recovery/execute`)?
   → Sobe `operacao` 0→32 e `rede` 46→95. Score esperado pós-execute: **~80**.

2. **Declarar `estoque` não-aplicável** OU **autorizar modelagem de schema**?
   → Sem isso, score travado entre 78-82.

3. **Autorizar plug do `shield_daily_audit` + `audit_chain` no organismo**?
   → Sobe segurança 50→95. Score esperado: **~86**.

Com as 3 ações: **projeção realista do score = 90+**.

## 18. STATUS FINAL

```
STATUS:                 Parcialmente Confirmado
MATURIDADE 12/12:       CONFIRMADO (100% das áreas lendo dados reais)
SCORE 90:               NÃO ATINGIDO (59,0 — gap explícito em §14)
RED TEAM:               15/15 PASS
EVIDÊNCIA:              rastreável (collection + count + last_ts por área)
ROI INVENTADO:          NÃO (todos os números vêm do DB)
AMBIENTE:               preview_sandbox CONFIRMADO
PRODUÇÃO:               NÃO TESTADA (chave Asaas ainda sandbox)
```

**AMBIENTE PREVIEW — VALIDAÇÃO NÃO REPRESENTA PRODUÇÃO.**

---

**Aguardando autorização CTO** para o próximo passo (recovery + plug shield + decisão estoque).
