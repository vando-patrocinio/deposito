# SPRINT 5 · LOUSA MOBILE — AUDITORIA POR FLUXO

**Empresa**: `co-demo` · **Gerado**: 2026-06-18 19:17 UTC
**Modo**: READ-ONLY · zero writes

## 1. RESUMO — Cobertura de Trilha por Fluxo

Para cada fluxo, mostra:
- **Finalizadas** = OS com status finalizada/encerrada
- **com ONT** = `completion_data.ont` preenchido
- **com consumíveis** = drop/conectores/cabo declarados
- **com stok_history linkado** = baixa real de estoque vinculada por `ticket_id`
- **com CEH** = entry em `client_equipment_history`

| Fluxo | Finalizadas | Com ONT | Consumíveis | Stok linkado | CEH |
|-------|------------:|--------:|------------:|-------------:|----:|
| instalacao | 2 | 1 (50.0%) | 1 (50.0%) | 0 (0.0%) | 0 (0.0%) |
| reparo | 12 | 0 (0.0%) | 2 (16.7%) | 0 (0.0%) | 0 (0.0%) |
| retirada | 0 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| preventiva | 0 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| rompimento | 4 | 0 (0.0%) | 0 (0.0%) | 3 (75.0%) | 0 (0.0%) |

## 2. RESPOSTAS ÀS PERGUNTAS DO CEO

### 2.1 INSTALAÇÃO — A OS nasce com tudo?

| Pergunta                                | SIM/NÃO/PARCIAL | Métrica |
|-----------------------------------------|----------------|---------|
| Nasce com CTO escolhida?                | PARCIAL — tickets não têm `cto_id` direto; bind vem por subscriber → cto_ports | n/a |
| Nasce com porta escolhida?              | NÃO (mesmo motivo)                | n/a |
| Porta livre validada?                   | PARCIAL — depende do fluxo `cto_provision_requests` (0 docs em co-demo) | 0 reqs |
| Porta reservada?                        | NÃO — `cto_ports.status=reserved` raro | ver § 1 |
| ONU escolhida (`completion_data.ont`)?  | SIM em parte | 50.0% |
| Cliente vinculado (`client_id`)?         | SIM (100% via ticket.client_id)   | 100% |
| SmartOLT atualizado?                    | PARCIAL — depende de cron `smartolt_actions` (1 doc total) | 1 ação |
| Estoque baixou (`stok_history`)?         | **0.0%** | 0/2 |
| Patrimônio movimentou (`stok_history`)?  | **0.0%** | mesmo cálculo |

### 2.2 REPARO — Confirma e atualiza?

| Pergunta                                | SIM/NÃO/PARCIAL | Métrica |
|-----------------------------------------|----------------|---------|
| Técnico confirma CTO atual?             | NÃO — não há campo `cto_confirmed_at` em tickets | 0 |
| Confirma porta atual?                   | NÃO — mesmo                       | 0 |
| Se troca porta, porta antiga liberada?  | NÃO RASTREÁVEL — `cto_port_swaps` total: 0 | 0 |
| Porta nova ocupada?                     | NÃO RASTREÁVEL — mesmo            | 0 |
| Se troca ONU, antiga sai do cliente?    | NÃO — `auto_ont_swap_events`: 0 eventos | 0 |
| ONU nova entra no cliente?              | NÃO RASTREÁVEL                    | 0 histories swap |
| Estoque baixa materiais?                | **0.0%** | 0/12 |
| Patrimônio recebe trilha?               | **0.0%** | mesmo |

### 2.3 TROCA DE ONU — Rastreabilidade

| Item rastreado                    | SIM/NÃO |
|-----------------------------------|---------|
| ONU antiga                        | **NÃO** (`auto_ont_swap_events`: 0 docs) |
| ONU nova                          | **NÃO** mesmo |
| Cliente                           | SIM (via ticket.client_id) |
| Ticket                            | SIM |
| Técnico                           | SIM (assigned_collaborator_id) |
| Estoque                           | **0.0%** |
| Patrimônio                        | mesmo do estoque |
| SmartOLT                          | NÃO atualizado automaticamente |
| CTO/Porta                         | NÃO atualizado automaticamente |

**Veredito**: troca de ONU **NÃO é 100% rastreável** (0 eventos de swap registrados vs 12 reparos finalizados).

### 2.4 RETIRADA — Reversão completa?

| Pergunta                                | SIM/NÃO/PARCIAL |
|-----------------------------------------|----------------|
| ONU retorna ao estoque?                 | **0.0%** (0/0) |
| `field_equipment_returns` registrados?  | 1 no total |
| `collab_returns` registrados?           | 4 no total |
| CTO libera porta?                       | NÃO RASTREÁVEL (sem `cto_release_event`) |
| Cliente perde vínculo (status=INATIVO)? | PARCIAL — depende de atualização manual |
| SmartOLT atualiza (remove/disable)?     | PARCIAL — via `smartolt_pending_removals` (12 docs) |
| Patrimônio registra devolução?          | mesmo cálculo de estoque |

## 3. TRILHA DE FINALIZAÇÃO LOUSA

- `lousa_finalize_trace` total: **33**
- Finalize trace com baixa estoque: **0**
- OS finalizadas total: **18**
- **Gap**: -15 OS finalizadas SEM `lousa_finalize_trace`

## 4. FLUXOS QUE DEVERIAM BAIXAR ESTOQUE E NÃO BAIXAM

| Fluxo       | Finalizadas | Com Stok | Diff (não baixaram) | % falha |
|-------------|------------:|---------:|--------------------:|--------:|
| instalacao | 2 | 0 | **2** | **100.0%** |
| reparo | 12 | 0 | **12** | **100.0%** |
| retirada | 0 | 0 | **0** | **0.0%** |
| rompimento | 4 | 3 | **1** | **25.0%** |

## 5. CONCLUSÃO

**Cobertura de trilha estoque por OS** (instalacao+reparo+retirada+rompimento):
- 3 / 18 = **16.7%** (🔴 CRÍTICO)

**Gates falhando para Sprint 5:**
- ❌ Cobertura trilha estoque < 95% (atual: 16.7%)
- ❌ Troca de ONU sem registro estruturado
