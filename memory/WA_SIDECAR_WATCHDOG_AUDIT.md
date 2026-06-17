# WA Sidecar Watchdog — Auditoria CTO

**Data:** 17/02/2026 (linha CEO P0)
**Status:** ✅ ATIVO em produção (leader worker)

## Objetivo
Eliminar a recorrência de mensagens AI com `delivery_status=failed_send` causadas por desconexões transitórias do sidecar Baileys, sem permitir fallback cruzado para Evolution API (regra dura do CEO).

## Componentes

### 1. `services/wa_sidecar_watchdog.py`
- **Probe**: HTTP GET `/health` em cada `WA_SIDECAR_URL_CH{1..4}` a cada 30s (config `WA_WATCHDOG_INTERVAL_S`).
- **Detecção de recovery**: transição `(connecting|disconnected|banned|timeout) → connected` em um sidecar dispara reenvio automático.
- **Retry**: query MongoDB `aihub_wa_messages` por `direction=outbound`, `delivery_status in [failed_send, failed_timeout]`, janela `WA_WATCHDOG_RETRY_WINDOW_H` (default 12h), **filtro estrito `channel ∈ {baileys, null, "", ausente}`** — mensagens com `channel=evolution` JAMAIS são tocadas.
- **Bypass dispatcher**: retry envia direto via `POST /send` no sidecar Baileys que se recuperou, evitando herdar lógica de breaker e garantindo trajeto puro Baileys → Baileys.
- **Limite por tick**: `WA_WATCHDOG_MAX_RETRY_PER_TICK` (default 50) — previne spike de envios após longas indisponibilidades.

### 2. `routes/wa_watchdog.py`
- `GET  /api/whatsapp-baileys/sidecar-watchdog/status` — snapshot do estado dos sidecars + últimos 20 eventos de recovery. RBAC: gestor/admin/auditor.
- `POST /api/whatsapp-baileys/sidecar-watchdog/tick` — disparo manual de 1 ciclo. RBAC: gestor/admin.

### 3. Integração no `server.py`
- Registrado em `_start_leader_jobs()` (somente leader). APScheduler interval=30s, `max_instances=1`, `coalesce=True`.
- Renomeado prefixo de rota para `/sidecar-watchdog` para não colidir com rota legada `/api/whatsapp-baileys/watchdog/status` (zombie watcher antigo em `whatsapp_baileys.py:4560`).

## Persistência (Mongo)

### `wa_sidecar_watchdog_state` (upsert por sidecar)
```
{
  sidecar: "ch1" | "ch2" | "ch3" | "ch4",
  url: "http://127.0.0.1:3002",
  last_state: "connected" | "disconnected" | "connecting" | "banned" | "timeout" | "error" | "unreachable",
  last_state_at: <datetime>,
  prev_state: <last>,
  last_check_at: <datetime>,
  last_health_payload: { ok, state, uptime_s, retry_count, ... },
  reachable: bool,
  last_recovery_at: <datetime>?,
  last_recovery_retried: int?,
  last_recovery_succeeded: int?,
  last_recovery_failed: int?
}
```

### `wa_sidecar_watchdog_events` (append-only log)
```
{ ts, sidecar, url, from_state, to_state, retried, succeeded, failed }
```

## Validação end-to-end (real)

**Disparo automático no startup (17/06 04:19 UTC):**
- CH1 transitou `disconnected → connected`.
- Watchdog identificou 1 mensagem AI elegível: `phone=551147099675`, criada às 03:42 UTC com `delivery_status=failed_send`.
- Reenvio direto via `http://127.0.0.1:3002/send` → `200 OK { ok: true }`.
- Update no DB: `delivery_status=sent`, `retry_via=watchdog_baileys`, `retry_reason=sidecar_recovered_from_offline`, `retry_applied_at=04:19:41Z`.

**Tick manual (POST /sidecar-watchdog/tick):**
- Idempotente: estados estáveis não disparam novo retry.

## Garantias de roteamento (CEO regra dura)

| Cenário | Comportamento |
|---|---|
| Mensagem `channel=baileys` em `failed_send` | Watchdog Baileys reenvia. |
| Mensagem `channel=baileys` permanece em `failed_send` (sidecar offline) | Fica pendente. Watchdog espera próxima recuperação. |
| Mensagem `channel=evolution` em `failed_send` | **NÃO tocada** pelo watchdog Baileys. |
| Sidecar Baileys cai | Mensagens novas continuam falhando (sem fallback cruzado). Watchdog reenvia quando voltar. |

**Zero fallback cruzado entre canais. Confirmado.**

## Env vars

| Var | Default | Descrição |
|---|---|---|
| `WA_WATCHDOG_INTERVAL_S` | 30 | Intervalo do probe (segundos) |
| `WA_WATCHDOG_RETRY_WINDOW_H` | 12 | Janela de elegibilidade do retry (horas) |
| `WA_WATCHDOG_MAX_RETRY_PER_TICK` | 50 | Máx mensagens reenviadas por ciclo |
| `WA_SIDECAR_URL_CH1..CH4` | (env) | URLs dos sidecars monitorados |
| `WA_SIDECAR_TOKEN` | (env) | Bearer token para `/send` |

## Próximos passos (backlog)

1. UI no painel WhatsApp mostrando estado do watchdog + botão "Disparar tick agora" (data-testids: `watchdog-status`, `watchdog-tick-btn`).
2. Métrica em `wa_dispatch_metrics`: contador `watchdog_recoveries_24h`.
3. Notificação Slack/WA admin quando sidecar fica >10min `disconnected` (escalation antes de QR expirar).
