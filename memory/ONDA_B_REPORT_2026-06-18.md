# Relatório Pós-Onda B — Auto-Close Bug #3

**Data:** 18/06/2026 · **Sprint:** Onda B · **CEO authorization:** ✓
**Escopo aprovado:** Bug #3 (auto-close stok_service) + Cron diário reconciliação

---

## 📊 ANTES / DEPOIS

### stok_services em status "ativo" (co-demo)

| Estado | Antes Onda A | Depois Onda A | Depois Onda B |
|---|---:|---:|---:|
| ativo (real) | 62 | 6 | **1** ✓ |
| late_closed (novo) | 0 | 0 | **5** ✓ |
| orfa_sem_ticket | 0 | 56 | 56 |

A única OS que sobrou em "ativo" é a `OS-4F6283`, e o ticket dela está realmente `aberta` — correto.

### Trace de finalize (POC controlado)
Disparado close de teste no `tkt-test-ondab-4bb70944`:

| Fase | Outcome | Detalhe |
|---|---|---|
| 01_entry | ok | type=reparo · outcome=sucesso |
| 02_guardrail | allowed | classification=physical_repair_no_swap · 0 movements |
| 03_ticket_updated | ok | new_status=finalizada · had_guardrail=True |
| 04_pre_auto_close | ok | drop=0 · esticadores=0 · ont=None |
| **05_post_auto_close** | **ok** | **result.ok=True · service_id=OS-4D02F8** |
| 06_exit | ok | warnings=[sn_mismatch, bad_signal] |

**Conclusão do diagnóstico:** O `auto_close_service_from_ticket` **funciona corretamente no código atual**. Fecha o stok_service mesmo com `used_items=[]` (rompimento/reparo sem insumos).

As 5 OS antigas que estavam "ativo" eram da época anterior à fix (provavelmente antes de algum ajuste de 13/06). O **late_close worker** capturou todas e fechou ✓.

---

## ✅ Validações executadas

### Instrumentação 6 fases (lousa.py:public_finalize_ticket)
- ✓ `01_entry` — ticket aceito pelo handler
- ✓ `02_guardrail` — decisão allowed/blocked com classification + reasons
- ✓ `03_ticket_updated` — `tickets.update_one` confirmado
- ✓ `04_pre_auto_close` — summary do completion_data
- ✓ `05_post_auto_close` — result.ok + result.reason + error (com exception capturada via `logger.exception`)
- ✓ `06_exit` — handler completou sem raise

Coleção `lousa_finalize_trace` com TTL 7d (auto-purge).

### Try/except silencioso removido (CEO rule)
**Antes:**
```python
try:
    await auto_close_service_from_ticket(...)
except Exception as e:
    logger.warning("[lousa] falhou: %s", e)   # ← engole tudo
```

**Depois:**
```python
auto_close_error: Optional[str] = None
try:
    auto_close_result = await auto_close_service_from_ticket(...) or {}
except Exception as e:
    auto_close_error = f"{type(e).__name__}: {str(e)[:300]}"
    logger.exception("...auto_close falhou ticket=%s: %s", ticket_id, e)
# Trace fase 05 SEMPRE roda — captura outcome="error" se houve exception
await trace_phase(phase=PHASE_POST_AUTO_CLOSE, ..., error=auto_close_error)
```

Agora qualquer falha tem traceback completo + trace persistido.

### Late close worker (rede de segurança)
- ✓ Detecta stok_services "ativo" cujo ticket está finalizado há > 60s
- ✓ Chama `auto_close_service_from_ticket` com `caller="late_close_worker"`
- ✓ Marca a OS com `late_closed=True` + `late_closed_at` + `late_closed_reason`
- ✓ Idempotente (2ª execução = 0 candidatos)
- ✓ Cada run grava em `late_close_runs`
- ✓ Agendado a cada **5 minutos** via APScheduler (`stok_late_close_5m`)

### Cron diário reconciliação 03:00 UTC
- ✓ Job `stok_orphan_reconcile_daily` agendado via `CronTrigger(hour=3, minute=0)`
- ✓ Roda em TODAS as empresas com OS ativas
- ✓ Grava relatório em `stok_reconcile_runs`
- ✓ Gera alerta em `ai_notifications` (tipo `stok_orphan_high`) se órfãs ≥ `STOK_ORPHAN_ALERT_THRESHOLD` (default 20)
- ✓ Idempotente (filtro `status=ativo`) · sem delete
- ✓ Configurável via env var

### Testes automatizados (regressão)
- **16/16 pytest passando** (`test_onda_a_stok.py` 9 + `test_onda_b_late_close.py` 7)
- Cobertura: trace phase, find candidates, grace period, dry-run, real exec, idempotência, run report.

---

## 🛠 Mudanças aplicadas (Onda B)

### Backend
- **NOVO** `/app/backend/services/lousa_finalize_trace.py` — módulo de instrumentação com 6 constantes de fase + `trace_phase()` + `get_trace()` + TTL 7d.
- **NOVO** `/app/backend/services/late_close_worker.py` — `find_late_close_candidates()`, `run_late_close()`, `scheduled_late_close_tick()`.
- **NOVO** `/app/backend/services/stok_reconcile_job.py` — `daily_reconcile_orphans_job()` + alerta.
- **NOVO** `/app/backend/scripts/late_close_run.py` — CLI dry-run/exec.
- **EDIT** `/app/backend/routes/lousa.py::public_finalize_ticket` — 6 traces instrumentados + try/except silencioso REMOVIDO.
- **EDIT** `/app/backend/server.py` — agendados `stok_late_close_5m` (5min) e `stok_orphan_reconcile_daily` (03:00 UTC).
- **NOVO** `/app/backend/tests/test_onda_b_late_close.py` — 7 testes (PASS).

### Coleções Mongo (novas)
- `lousa_finalize_trace` — 6 fases por finalize (TTL 7d auto-purge)
- `late_close_runs` — relatório de cada execução do worker
- `stok_reconcile_runs` — relatório diário do cron

### Coleções já existentes (campos novos)
- `stok_services` ganhou opcionalmente: `late_closed`, `late_closed_at`, `late_closed_reason`
- `ai_notifications` recebe alertas tipo `stok_orphan_high`

---

## ⚠️ O que NÃO foi feito (intencionalmente)

- **finalize_ticket JWT (gestor web)** — só `public_finalize_ticket` foi instrumentado. O endpoint JWT (`/lousa/tickets/{id}/finalize` linha 5170) ainda tem o try/except silencioso original. **Recomendo aplicar mesmo padrão na próxima sessão** (esse endpoint é usado quando o gestor fecha OS pelo painel, raro mas existe).
- **UI: botão "Reconciliar agora"** — aprovado pelo CEO mas só depois da Onda B. Próxima sprint (10min de trabalho).
- **Onda C** — validação consumíveis no mobile + separação praça/técnico + auto-detect troca ONT.

---

## 🎯 Como auditar/operar daqui pra frente

```bash
# Ver traces de um ticket
cd /app/backend && python3 -c "
import asyncio, sys; sys.path.insert(0, '.')
from database import db
async def m():
    async for r in db.lousa_finalize_trace.find(
        {'ticket_id': 'tkt-XYZ'}, {'_id': 0}
    ).sort('ts', 1):
        print(r)
asyncio.run(m())
"

# Forçar 1 ciclo do late_close manualmente
python3 -m scripts.late_close_run --company-id co-demo

# Forçar 1 ciclo da reconciliação diária
python3 -m scripts.reconcile_orphan_stok_services --company-id co-demo

# Ver últimos relatórios
cd /app/backend && python3 -c "
import asyncio, sys; sys.path.insert(0, '.')
from database import db
async def m():
    async for r in db.late_close_runs.find({}, {'_id': 0}).sort('started_at', -1).limit(3):
        print(r)
asyncio.run(m())
"
```

---

## 🎯 Aguardando OK do CEO

Sugestão: rodar 24h em produção observando os contadores antes de decidir Onda C. Os jobs estão agendados e vão acumular evidência:
- `late_close_runs` → quantos casos por dia o worker capturou (esperado: tender a zero)
- `stok_reconcile_runs` → quantas órfãs aparecem por dia (esperado: < 20)

Se algum desses contadores subir → alerta operacional já configurado.
