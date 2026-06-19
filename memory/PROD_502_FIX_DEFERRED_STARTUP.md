# PRODUÇÃO 502 — FIX: Deferred Startup
**Data:** 2026-06-19
**CTO:** Agent E1 (sessão de manutenção INSTRUMENTED PRODUCTION)
**Severidade:** P0 — Produção offline (universoligo.com)

## Sintoma
Após deploy Preview → Produção, o backend não respondia em `/api/*`:
- Frontend `/` → HTTP 200 (bundle estático servia normal)
- `/api/*` → HTTP 502 "emergent.cloud | 502: Bad gateway"
- Nginx do pod: `connect() failed (111: Connection refused) while connecting to upstream: http://127.0.0.1:8001/api/*`

## Diagnóstico (Root Cause)
O `@app.on_event("startup")` em `backend/server.py` executava ~15 `await` sequenciais BLOQUEANTES **antes** do uvicorn bindar `0.0.0.0:8001`:
- `ensure_indexes()` × 9 collections
- `prompt_loader.sync_all()` (operações git)
- `run_pending_migrations(db)`
- `routes_saas.ensure_demo_company()`
- `seed_default_users(db)`
- `get_or_create_vapid(db)`
- `_seed_demo_if_empty()`, `_seed_demo_tickets()`
- `db.system_settings.update_one(...)`

No Preview (Mongo local, RTT <1ms) total ~5s — OK.
Em Produção (Atlas Mongo, RTT 50-200ms) total >30s — **excede readiness probe do K8s** → pod killed em CrashLoopBackOff → porta 8001 nunca abria → nginx 502.

## Fix (code-only, sem alteração de Dockerfile/supervisor)
Em `backend/server.py` linhas 713-720:

**Antes:**
```python
@app.on_event("startup")
async def _startup() -> None:
    await ensure_indexes()
    await ensure_auth_indexes(db)
    await ensure_push_indexes(db)
    # ... +1000 linhas de awaits bloqueantes
```

**Depois:**
```python
@app.on_event("startup")
async def _startup() -> None:
    # Porta abre imediato; init pesado vai pra background.
    asyncio.create_task(_deferred_startup(), name="deferred-startup")


async def _deferred_startup() -> None:
    await ensure_indexes()
    await ensure_auth_indexes(db)
    await ensure_push_indexes(db)
    # ... (resto do código intocado)
```

## Validação Preview (pós-fix)
- `sudo supervisorctl restart backend` → uvicorn bindou em ~3s (antes >30s)
- `GET /api/server-time` → HTTP 401 (200ms, route ativo + auth funcionando)
- `POST /api/auth/login` → HTTP 200 com JWT (387ms)
- Todos os schedulers/workers/migrations carregaram em background sem erro
- Logs limpos exceto 1 warning conhecido (IndexOptionsConflict — idempotente, não bloqueante)

## Próximo Passo
**Usuário (CEO)** precisa acionar **Redeploy** no dashboard Emergent (Preview → universoligo.com) para subir este fix em Produção.

## Garantias
- **Sem mudança de business logic** (INSTRUMENTED PRODUCTION respeitado)
- **Sem mudança de Dockerfile/supervisor** (conforme regra do deployment_agent)
- Idempotente: re-runs de migrations/seeds não causam duplicação
- Fail-soft: workers que crashem em background são logados como `warning` sem afetar request handling

## Risco residual
Durante os primeiros ~5-10s após o boot em produção, requests que dependam de indexes recém-criados podem fazer collection scan (latência maior). Aceitável dado que evita 100% de downtime.
