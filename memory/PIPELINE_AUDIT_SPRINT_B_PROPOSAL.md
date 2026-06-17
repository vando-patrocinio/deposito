# Pipeline Audit · Commanders → Executor — CTO 17/02/2026

**Pergunta CEO:** auditoria simples do pipeline `commanders_worker → opportunities → executor_ia → action → outcome` com contagens das últimas 24h.

## TL;DR

**Pipeline 24h:**
```
228 criadas
  ├── 228 pending (na fila — INATIVAS)
  ├──   0 approved
  ├──   0 executed
  ├──   0 dismissed
  └──   0 expired (ainda)
```

**Histórico TOTAL (desde sempre, desde a criação da coleção):**
```
3.338 opportunities criadas
  ├── 2.370 pending
  ├──   956 expired
  ├──    11 approved (manualmente, em algum momento)
  ├──     7 dismissed
  └──     0 executed   ← ZERO em TODA a história
```

## Diagnóstico técnico

### Existem 2 pipelines paralelos no código

**Pipeline A · Presidencial (existe e tem código pronto):**
```
presidente_brain → conselho_ia → motor_ia_actions →
pending_executions → executor_ia (DRY_RUN_ONLY default)
```
- 5 categorias autorizadas: `REAJUSTE_IPCA`, `DISPARO_COBRANCA`,
  `CONTATO_LEO_PROATIVO`, `CRIACAO_OS_SMARTFIELD`, `CAMPANHA_RETENCAO`
- Toda execução exige `approved_by` preenchido
- Roda em `DRY_RUN_ONLY` até flip manual

**Pipeline B · Commanders/Opportunities (sem executor ligado):**
```
commanders_worker → isabella_commander_opportunities → ??? → ???
```
- Detecta dunning, churn, twin, revenue, shield_alert
- **NÃO HÁ EXECUTOR conectado** — campo `executed_at` nunca foi setado
- O que faltou: traduzir `recommended_action.{type, channel, template}`
  em chamadas reais (`wa_dispatcher`, `smart_olt`, `os_creator`)

### Gap arquitetural identificado
Não é race condition. Não é approval gate quebrado. **É ausência de ponte**
entre os 2 pipelines. As 3.338 opps do Pipeline B nunca passaram pelo
`executor_ia` do Pipeline A porque ninguém ligou os dois.

## Auditoria detalhada · 483 `block_subscriber`

Pergunta CEO: quantos pagaram antes? Depois? Cancelaram? Churn? Ticket?

| Métrica | Valor |
|---|---:|
| Total `block_subscriber` no DB | 483 |
| Com `external_id` identificável | 483 (100%) |
| **Clientes REAIS** (existem em `atlaz_clients_cache`) | **371** (76,8%) |
| Pagaram alguma fatura APÓS criação da opp | **29** (6,0%) |
| Já pagavam antes (histórico de pagamento) | 153 (31,7%) |
| Ainda têm faturas abertas/overdue HOJE | **419** (86,8%) |
| 💰 Total recuperado pós-opp | **R$ 3.176,28** |
| Ticket médio | R$ 107,20 |
| Impact teórico total | R$ 20.581,48 |

**Correção honesta vs Sprint A:**
Meu classifier `_classify_dunning` rotulou 192/192 como `failure` porque
olha SÓ as faturas referenciadas em `evidence.invoices[]`. Mas a auditoria
mostra que **6% pagaram alguma fatura** (não necessariamente a referenciada).
A direção do peso 0.05 está correta — recuperação é baixa — mas a magnitude
exata é **6%, não 0%**. Vou enriquecer o classifier no próximo ciclo (olhar
qualquer fatura do cliente, não só as referenciadas).

**Conclusão executiva:** dos 483 bloqueios sugeridos, 86,8% dos clientes
seguem inadimplentes hoje. **Bloquear de fato não recupera** — corroborado
agora com dado limpo (era a hipótese da Sprint A).

## Proposta Sprint B (escopo claro)

### Objetivo
`opportunities_acted_24h > 100` (hoje = 0). Habilitar a ponte entre
Pipeline B (commanders) e ação real.

### Entregas

**B.1 — Bridge `services/opportunity_executor.py`** (1 dia)
Função `execute_opportunity(opp_id)` que:
- Lê `recommended_action.{type, channel, template, subscriber_external_id}`
- Roteia pra handler por `type`:
  - `send_reminder` (channel=whatsapp) → `wa_dispatcher.send_template(...)`
  - `schedule_repair` → cria OS via `routes/os.py::create_os`
  - `block_subscriber` → SEMPRE `requires_approval=True` (manual gate)
  - `survey` (NPS) → `wa_dispatcher.send_template('nps_survey')`
- Marca `status=executed`, `executed_at=now`, `execution_result={...}`

**B.2 — Approval gate por kind** (½ dia)
- `dunning/reminder_late`, `twin/onu_degradation`: auto-aprovação (weight > 1.0)
- `dunning/block_request`, `dunning/negotiation`: requires_approval=True
- `churn/satisfaction_survey`: auto-aprovação
- Loga em `audit_log` toda ação automática (regra dura)

**B.3 — Worker de drenagem da fila** (½ dia)
- Scheduler 10min: pega N opps `pending` com `requires_approval=False`
  e dispara `execute_opportunity`
- Hard cap de 50 execuções por tick pra evitar spam
- Idempotente: usa `executed_at` como guard

**B.4 — Métrica + dashboard** (¼ dia)
- `opportunities_executed_24h` + `execution_success_rate` adicionados
  ao `/learning-health`
- Endpoint `/learning-health/pipeline` com snapshot pendentes/aprovadas/
  executadas/falhadas/aguardando-aprovação

### Critério de aceite
- ≥30 ações reais executadas em 24h
- Mensagens reais saindo via `wa_dispatcher` (Baileys)
- Pelo menos 1 `outcome=success` derivado de ação automática (e não de
  reconciliação retroativa)

### KPI alvo Sprint B
| KPI | Antes | Alvo |
|---|---:|---:|
| `opportunities_acted_24h` | 0 | **≥100** |
| `opportunities_executed_24h` | 0 | **≥30** |
| `learning_loop_closure_pct` | 24,47% | **≥40%** |

## Backlog (não Sprint B)
- Enriquecer `_classify_dunning` pra olhar qualquer fatura do cliente
  (não só as referenciadas)
- Auditoria periódica do classifier (taxa de `unknown` < 5%)
- Lacuna: muitas opps têm `target_id=sub-xxxx` (id sintético) sem
  bridge pro `subscriber_external_id` Atlaz. Adicionar normalização
  ao criar a opp.
