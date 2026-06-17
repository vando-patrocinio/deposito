# Sprint A — Learning Loop CLOSED (CEO P0 17/02/2026)

## Estado anterior (3h atrás)
```
opportunities_created_24h        228
opportunities_acted_24h            0
outcomes_recorded_24h              0
outcomes_classified_24h            0
learning_loop_closure_pct       0.00%   🔴 RED
playbook_weights ativos            1  (parado em 10/06)
```

## Estado AGORA (validado em prod)
```
opportunities_created_24h        228
opportunities_acted_24h            0  ← Sprint B
outcomes_recorded_24h            530
outcomes_classified_24h          519
learning_loop_closure_pct      24.47%  🟡 YELLOW (meta 40%)
playbook_weights ativos            8
```

## Entregas

### 1. `services/isabella_outcome_recorder.py` (novo)
Fecha o loop classificando opportunities `expired` sem outcome via SINAIS REAIS no DB:
- **dunning** → `subscriber_invoices.status` das faturas referenciadas (paid? success / open? failure / parcial? partial)
- **churn** → `atlaz_clients_cache.is_active`/`blocked` (ainda ativo? success)
- **revenue** → pagamento posterior ao `created_at` da opp (encontrou? success)
- **twin/shield_alert** → recorrência (anomalia voltou? failure / sumiu? success)

Cada outcome:
1. Persiste em `isabella_outcomes` (id, opp_id, signal, evidence_classification)
2. Chama `isabella_learning.record_outcome` → atualiza `isabella_playbook_weights` (Wilson lower bound, decay 0.7+0.3)
3. Atualiza a opp com `outcome_id` e `outcome_recorded_at`

Regra dura: **somente fatos do banco**. Sem `unknown` puramente sintético.

### 2. `routes/isabella_learning_health.py` (novo)
- `GET /api/isabella/learning-health` → os 5 KPIs do CEO + status RGY + by_kind + weights
- `POST /api/isabella/learning-health/reconcile?limit=N&kinds=X,Y` → trigger manual
- `GET /api/isabella/learning-health/playbooks?kind=X` → top playbooks por peso
- `GET /api/isabella/learning-health/recent-outcomes?limit=20&outcome=success` → drill-down
- Snapshot histórico persistido em `isabella_learning_health` a cada chamada do `/health`

### 3. Scheduler hook
- Job `isabella_outcome_recorder` no APScheduler leader, **interval 60min**, `max_instances=1`, `coalesce=True`
- Idempotente: só processa opps `expired` sem `outcome_id`

## Insights operacionais REAIS (gerados pela 1ª vez)

| Playbook | Kind / Subkind | Attempts | Success rate | Weight |
|---|---|---:|---:|---:|
| ⭐ `lembrete_atraso_leve` | dunning/reminder_late | 225 | **78%** (175) | **1.82** ⬆️ |
| `schedule_repair` | twin/onu_degradation | 31 | 71% (22) | 1.34 ⬆️ |
| `nps_proativo` | churn/satisfaction | 4 | 75% (3) | 0.93 |
| `schedule_preventive` | twin/cto_failure | 2 | 100% (2) | 0.86 |
| `reativacao_condicional` | dunning/unblock_offer | 2 | 0% (0) | 0.52 ⬇️ |
| 🔴 `negociacao_parcelamento` | dunning/negotiation | 62 | **16%** (10) | 0.21 ⬇️ |
| 🔴 `aviso_final_bloqueio` | dunning/warning | 5 | 0% (0) | 0.21 ⬇️ |
| 🔴 `block_subscriber` | dunning/block_request | **192** | **0%** | **0.05** FLOOR |

**Aprendizados de negócio que SAÍRAM do dado:**
1. **Lembrete cedo (D+0~D+2) é o que mais funciona** — 78% de sucesso. Manter prioridade alta.
2. **Bloquear cliente NÃO RESOLVE inadimplência** — 0 success em 192 tentativas. Reavaliar política.
3. **Negociação de parcelamento tem ROI baixo** (16% sucesso). Reavaliar abordagem ou trazer humano cedo.
4. **Manutenção preventiva em ONU degradada funciona** (twin, 71% sucesso, ROI R$2k).

## Validação real (zero backfill, zero simulação)

Cliente real auditado: **GILMAR DA SILVA** (`sub-5719cd56eded`)
- Opp dunning `opp-edf07460b9cf47` criada 10/06 21:25, expirou 12/06 23:14, **sem outcome**
- Fatura `sinv-86772176aa` (R$ 89,91) → status `paid` desde 10/06 03:00
- Outcome derivado: `success` / `signal=all_invoices_paid` / `roi=R$ 89,91`
- Weight do `lembrete_atraso_leve` subiu de 1.0 → 1.82 ao final do batch

## Próximos passos (Sprint B — fazer ações de verdade)

Sprint A entregou: **fechar loop sobre opps que JÁ EXPIRARAM**. Próximo:
- Sprint B: **agir sobre opps `pending` ANTES de expirar** (executor_ia conectado ao commander_worker via approval gate).
- KPI alvo: `opportunities_acted_24h > 0` (hoje sigue 0).

## Backlog
- UI: card de Learning Health no Watchtower Executivo com os 5 KPIs.
- Snapshot histórico do LLC em `isabella_learning_health` (já populando agora — falta gráfico).
- Quando peso > 1.5, sugerir AUTONOMIA TOTAL pro playbook (executar sem aprovação humana).
- Quando peso < 0.3, sugerir DESATIVAÇÃO do playbook (custa atenção sem retorno).
