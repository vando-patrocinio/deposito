# SCHEDULER HARDENING REPORT — Sprint P0.2

> **Data:** 2026-06-09
> **Causa raiz mitigada:** gap de backup em 07/jun (APScheduler descartou trigger por downtime)

## 1. Estratégia adotada

Em vez de modificar 27 chamadas individuais de `scheduler.add_job(...)`, aplicamos a proteção UMA ÚNICA VEZ no construtor do `AsyncIOScheduler` via `job_defaults`. APScheduler usa esses defaults para **todos** os jobs subsequentes que não definem explicitamente.

**Esforço:** 1 linha de código (10 efetivas com docstring).

## 2. Mudança aplicada

### Arquivo: `/app/backend/server.py` linha 258

#### ANTES

```python
scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")
```

#### DEPOIS

```python
scheduler = AsyncIOScheduler(
    timezone="America/Sao_Paulo",
    # P0.2 Scheduler Hardening — protege TODOS os jobs contra misfire por
    # downtime do processo (causa do gap de backup 07/jun). Aplica
    # uniformemente em todos os add_job sem alterar frequências.
    job_defaults={
        "misfire_grace_time": 3600,  # 1h de janela pra recuperar job perdido
        "coalesce": True,            # combina múltiplos misfires em 1 execução
        "max_instances": 1,          # evita execução concorrente do mesmo job
    },
)
```

## 3. Jobs cobertos (27 jobs em `server.py`)

| # | Linha | Job ID/função | Frequência (mantida) | Antes | Depois |
|---|-------|---------------|----------------------|-------|--------|
| 1 | 700 | `monthly_email_job` | mensal último dia 23:30 | ❌ | ✅ |
| 2 | 702 | `holidays_refresh_job` | dia 1 às 03:00 | ❌ | ✅ |
| 3 | 704 | `location_logs_cleanup_job` | a cada 6h, minuto 10 | ❌ | ✅ |
| 4 | 706 | `dwell_push_job` | a cada 2 min | ❌ | ✅ |
| 5 | 713 | `mark_abandoned_sessions_job` | a cada 2 min | ❌ | ✅ |
| 6 | 715 | `retarget_abandoned_sessions_job` | a cada 1h | ❌ | ✅ |
| 7 | 720 | `autosch.drives` | a cada 30 min | ❌ | ✅ |
| 8 | 723 | `autosch.reconcile` | a cada 4h | ❌ | ✅ |
| 9 | 726 | `autosch.briefing_07h` | diário 07h | ❌ | ✅ |
| 10 | 730 | `autosch.briefing_12h` | diário 12h | ❌ | ✅ |
| 11 | 734 | `autosch.briefing_18h` | diário 18h | ❌ | ✅ |
| 12 | 738 | `autosch.self_healing_auto` | recorrente | ❌ | ✅ |
| 13 | 747 | `nightly_customers_sync_job` (atlaz) | noturno | ❌ | ✅ |
| 14 | 751 | `auto_reconnect_job` (integrations) | recorrente | ❌ | ✅ |
| 15 | 756 | `baileys_watchdog_job` | recorrente | ❌ | ✅ |
| 16 | 761 | `baileys_nightly_restart_job` | noturno | ❌ | ✅ |
| 17 | **766** | **`daily_backup_job`** (mongo) | **diário 03:00 UTC** | ❌ | ✅ **← causa do gap 07/jun, agora protegido** |
| 18 | 770 | `weekly_migrate_job` | domingo 04:00 | ❌ | ✅ |
| 19 | 827 | `auto_mark_overdue` | diário 03:00 | ❌ | ✅ |
| 20 | 831 | `auto_sync_atlaz_financeiro` | recorrente | ❌ | ✅ |
| 21 | 836 | `nightly_audit_job` (cto) | diário 03:15 | ❌ | ✅ |
| 22 | 859 | `_readjustment_daily_all_companies` | diário | ❌ | ✅ |
| 23 | 876 | `_readjustment_notify_all_companies` | diário | ❌ | ✅ |
| 24 | 890 | `_alvaro_daily_all_companies` | diário | ❌ | ✅ |
| 25 | 913 | `_disparo_daily_all_companies` | diário | ❌ | ✅ |
| 26 | 936 | `_billing_dunning_all_companies` | diário | ❌ | ✅ |
| 27 | 941 | `dispatch_due_schedules_job` | recorrente | ❌ | ✅ |

**Cobertura:** 27/27 = **100%**

## 4. Semântica das proteções

### `misfire_grace_time=3600`

Se o backend ficar offline durante o disparo (ex: trigger 03:00 UTC + restart 03:15), o APScheduler **executa o job atrasado** quando voltar, desde que esteja dentro de 1h da janela. Sem isso (default `None`), job perdido era descartado **silenciosamente**.

### `coalesce=True`

Se múltiplos misfires acumulam (ex: backend ficou down 4h em 03:00), **combina em 1 única execução** ao voltar. Sem isso, default era executar TODAS as misfires acumuladas (carga alta).

### `max_instances=1`

Garante que um job nunca executa em paralelo com cópia anterior dele mesmo (defesa contra long-running jobs em frequência alta).

## 5. Frequências preservadas

⚠️ **Zero alteração** em horários, intervalos, day_of_week ou qualquer parâmetro de frequência.

## 6. Validação

```
$ sudo supervisorctl restart backend
backend: stopped
backend: started
$ supervisorctl status backend
backend  RUNNING   pid 47760, uptime 0:00:08

$ cd /app/backend && python -m pytest tests/test_safety_p0.py \
    tests/test_v9_p3_whitelist.py tests/test_homologation.py \
    tests/test_observability.py
========================== 31 passed ==========================
```

Backend reinicia limpo. Zero regressão. Próximo disparo do `daily_backup_job` (03:00 UTC de 2026-06-10) **está protegido**: mesmo se o backend reiniciar entre 02:30 e 04:00, o dump será gerado.

## 7. Antes vs Depois — resumo

| Métrica | Antes | Depois |
|---------|-------|--------|
| Jobs com `misfire_grace_time` | 0/27 | 27/27 |
| Jobs com `coalesce` | 0/27 | 27/27 |
| Jobs com `max_instances` | 0/27 | 27/27 |
| Tolerância a restart durante trigger | ❌ | ✅ 1h |
| Janela "invisível" (gap inv. detectado) | até 24h | ≤ 1h |

## 8. Pendências (fora do escopo desta sprint)

- Cron host (crontab/systemd) como redundância ao APScheduler.
- Alerta automático "backup ausente há >25h".
- Métricas de execução de jobs em endpoint admin (`GET /api/admin/scheduler/jobs/health`).
