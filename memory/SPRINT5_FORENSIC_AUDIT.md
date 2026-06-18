# SPRINT 5 · AUDITORIA FORENSE — RESUMO EXECUTIVO

**Empresa**: `co-demo` · **Gerado**: 2026-06-18 19:17 UTC
**Modo**: READ-ONLY (zero writes) · Mandato CEO 18/06/2026

## 1. NOTA GERAL (0-10)

### **1.4 / 10**

| Domínio    | Nota |
|------------|-----:|
| CTO/Porta | 0 |
| Lousa | 1.7 |
| SmartOLT | 0.1 |
| Patrimônio | 3.9 |

## 2. DASHBOARD GERAL

| Métrica                                  | Valor | Tier |
|------------------------------------------|------:|------|
| CTOs cadastradas                        | 40 | — |
| Portas (cto_ports)                       | 259 | — |
| Subscribers ativos                       | 2.768 | — |
| Ativos sem porta                         | 2.767 (100.0%) | 🔴 CRÍTICO |
| Schema mismatch ctos vs cto_ports        | 0 | — |
| Subs fantasma em portas                  | 2 | — |
| Cobertura trilha estoque (Lousa)         | 16.7% | 🔴 CRÍTICO |
| Swap events (auto_ont_swap_events)       | 0 | — |
| Cobertura SmartOLT × Estoque             | 0.65% | 🔴 CRÍTICO (Sprint 5 Fundacional) |
| Score rastreabilidade patrimônio (5/5)   | 39.4% | 🟠 GRAVE |
| ONTs órfãs (0/5)                         | 0 | — |
| ONTs sintéticas (backfill)               | 31 | — |

## 3. MAIOR RISCO

**Cobertura SmartOLT × Estoque em 0.65%** — 98% do parque operacional está invisível ao patrimônio contábil. Qualquer balanço, depreciação, ou venda baseada no estado atual é estatisticamente inválido.

## 4. MAIOR BLOQUEADOR

**Pipeline `smartolt_pull_to_stok` nunca foi criado**. Não há job, worker, rota ou script de import bidirecional. Estado atual = lacuna arquitetural, não bug. Diagnóstico fechado em `RCA_DELTA_98_SMARTOLT_VS_ESTOQUE.md`.

## 5. MAIOR GANHO RÁPIDO

**Vincular `stok_history` aos `ticket.id`** (campo `ticket_id`). Hoje a baixa automática pela Lousa registra OS-XXX só no `description`, gerando 149 events órfãos. Fix de baixo esforço (1 linha no `auto_finalize_lousa`) que recupera trilha de 100% dos fechamentos futuros.

## 6. A SPRINT 5 PODE COMEÇAR?

### ❌ **NÃO** — gates falhando:

- ❌ Cobertura SmartOLT × Estoque ≥ 95% (atual 0.65%)
- ❌ Integridade CTO/Porta ≥ 95% (atual 0.0%)
- ❌ Cobertura trilha estoque Lousa ≥ 95% (atual 16.7%)
- ❌ Score rastreabilidade patrimônio ≥ 80% (atual 39.4%)
- ❌ Subscribers fantasma em portas = 0 (atual 2)
- ❌ Swap de ONU rastreável (atual 0 eventos)

### ✅ Gates atendidos:

- ✅ Schema canônico portas definido (atual 0 divergentes)

## 7. RELATÓRIOS COMPLEMENTARES

- `SPRINT5_CTO_PORTA_AUDIT.md` — CTO + porta + cliente
- `SPRINT5_LOUSA_MOBILE_AUDIT.md` — 8 perguntas por fluxo
- `SPRINT5_SMARTOLT_ESTOQUE_AUDIT.md` — Cobertura patrimonial
- `SPRINT5_RISK_MATRIX.md` — Matriz P0/P1/P2
- `SPRINT5_EXECUTION_PLAN.md` — Ondas 1-6 com gates

**Suporte**:
- `SMARTOLT_RECONCILIATION_2026-06-18.md` (Ajuste 1)
- `RCA_DELTA_98_SMARTOLT_VS_ESTOQUE.md` (RCA Cenário A)
- `SPRINT_5_FASE_0_PLAN.md` (blueprint não-executado)


---

## ANEXO · MÓDULO PATRIMÔNIO (detalhe)

# SPRINT 5 · PATRIMÔNIO — 5 PERGUNTAS POR ATIVO

**Empresa**: `co-demo` · **Gerado**: 2026-06-18 19:17 UTC
**Modo**: READ-ONLY · zero writes

## 1. RASTREABILIDADE POR ATIVO (5 perguntas)

Para cada ONT em `stok_onts`, verificamos:
1. **De onde veio?** (`valuation_genesis_via` ou `import_source`)
2. **Onde está?** (`location_type` + `location_id`)
3. **Quem movimentou?** (events em `stok_history.ont_id`)
4. **Quando movimentou?** (`updated_at != created_at`)
5. **Qual ticket?** (`last_ticket_id`)

| Critério                | Atendido | % |
|-------------------------|---------:|--:|
| 1. De onde veio        | 31 | 96.9% |
| 2. Onde está           | 32 | 100.0% |
| 3. Quem movimentou     | 0 | 0.0% |
| 4. Quando movimentou   | 0 | 0.0% |
| 5. Qual ticket         | 0 | 0.0% |
| **Score médio (5/5)**  |  | **39.4%** |

## 2. PATRIMÔNIO POR CATEGORIA

| Categoria              |   Qtd |
|------------------------|------:|
| Total de ONTs          | 32 |
| Confiável (5/5 OK)     | 0 |
| Sintético (backfill)   | 31 |
| Precisa revisão humana | 22 |
| **Órfão** (0/5 OK)     | **0** |
| Com valor calculado    | 0 |

## 3. TIER: 🟠 GRAVE

**Gates falhando:**
- ❌ Score de rastreabilidade < 80% (atual: 39.4%)
- ❌ Mais da metade das ONTs sem ticket de origem
- ❌ Mais da metade vem de backfill sintético (31/32)