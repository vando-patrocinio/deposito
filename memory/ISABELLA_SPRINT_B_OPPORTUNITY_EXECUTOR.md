# Sprint B — Opportunity Executor (CEO P0 17/02/2026)

## TL;DR
3.338 opps detectadas. **0 executadas em toda a história.** Sprint B
construiu a **ponte arquitetural** entre `commanders_worker` e ação real.

Hoje: pipeline pronto em **DRY_RUN** (cap 20/tick, 10min interval, kill
switch). Aguardando aprovação do CEO pra ir LIVE.

## Passo 0 — Contrato (auditado antes de codar)

14 types únicos, 6 channels, payload já contém `phone`/`subscriber_external_id`/
`template`. Distribuição limpa, sem necessidade de redesenho.

## Entregas

### B.1 — `services/opportunity_executor.py`
- `execute_opportunity(opp)`: idempotente (skip se `executed_at` set)
- `drain_pending(company_id, limit)`: drena `pending` sem approval-required
- Renderer interno de 6 templates: lembrete, aviso bloqueio, negociação,
  upsell, NPS, fallback genérico
- Resolução de `phone` em cascata: action.phone → subscriber_phones →
  atlaz_clients_cache → label extract `(NNNNN)`
- Audit trail completo em `opportunity_executor_audit`

### B.2 — Approval Gate
| Action Type | Política |
|---|---|
| `block_subscriber` | **SEMPRE manual** (override) — dado Sprint A mostrou 6% recovery |
| `schedule_repair` / `_inspection` / `_preventive` / `expand_coverage` | Respeita `requires_approval` (default True) |
| `send_offer` | Respeita flag (mix do commander_worker: 732 T / 95 N) |
| `send_reminder` / `send_warning` / `send_negotiation` / `satisfaction_survey` / `negotiation_offer` | **Auto-execute** |
| `quarantine_release` | Auto (sem cliente envolvido) |
| `shield_review` / `review_module` | Notify-only no `operator_inbox` |

### B.3 — Worker (scheduler)
- Job `opportunity_executor` registrado no APScheduler leader
- **Interval 10min**, `max_instances=1`, `coalesce=True`
- Cap conservador `OPPORTUNITY_EXECUTOR_MAX_PER_TICK=20`
- Kill switches via env:
  - `OPPORTUNITY_EXECUTOR_DRY_RUN=1` → loga + audit mas NÃO age
  - `OPPORTUNITY_EXECUTOR_DISABLED=1` → worker não roda

### B.4 — Pipeline Health endpoints
- `GET /api/isabella/learning-health/pipeline` → snapshot all-time + 24h
  + execution stats + awaiting_approval + dry_run flag
- `POST .../execute?opp_id=X` (1 opp) | `?limit=N` (batch drain manual)
- `POST .../approve?opp_id=X&execute_now=true` (gate manual)

## Validação real

### DRY_RUN funcional (cap 20)
```
GET /pipeline (antes)        : executions_24h=25, success=80%, pending=2386
POST /execute?limit=10       : examined=10, executed=10, dry_run=true
GET /pipeline (depois)       : executions_24h=35, success=85.71%, pending=2386
```

**Comprovado:**
- ✅ Audit trail em `opportunity_executor_audit` populado
- ✅ Templates renderizados corretamente (vi "Olá, Jessica!" / "Olá, Luiz!" — clientes reais)
- ✅ Resolução de phone OK (negotiation_offer pegou phone do cache)
- ✅ Pipeline endpoint mostra `dry_run: true` (transparência)
- ✅ **0 mensagens reais saíram** (validado em `aihub_wa_messages`)
- ✅ `pending` NÃO decrementou em dry-run (preserva fila pra execução real)

## Para ATIVAR LIVE

1. Editar `/app/backend/.env`:
   ```
   OPPORTUNITY_EXECUTOR_DRY_RUN=0
   ```
2. `sudo supervisorctl restart backend`
3. Próximo tick do scheduler (≤10min) drenará 20 opps
4. Monitorar via:
   - `GET /api/isabella/learning-health/pipeline` (executions_24h subindo)
   - `GET /api/whatsapp-baileys/sidecar-watchdog/status` (CH1 connected)
   - `db.aihub_wa_messages` outbound

## Próximas iterações (não Sprint B)

1. **Enriquecer `_classify_dunning`** olhar QUALQUER fatura do cliente,
   não só as referenciadas em `evidence.invoices[]` (Sprint A mostrou 6%
   real, classifier reportou 0%).
2. **UI no Watchtower Executivo**: card com os 5 KPIs + sparkline LLC +
   botão `Approve all` por kind/playbook.
3. **Política de auto-aprovação dinâmica**: weight > 1.5 → autoriza
   sozinho; weight < 0.3 → solicita revisão humana.
4. **Limpar PAMELA NERY TESTE LIGO** no Atlaz (cliente sintético
   poluindo dados).
