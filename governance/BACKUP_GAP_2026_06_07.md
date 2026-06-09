# BACKUP GAP — 2026-06-07 — CAUSA RAIZ

> **Modo:** READ-ONLY (apenas leitura de logs).
> **Data da auditoria:** 2026-06-09

## 1. Fato

O dump diário do MongoDB com prefixo `mongo-dump-20260607-030000.tar.gz` **não existe** em `/app/backups/`. A sequência observada:

```
mongo-dump-20260606-030000.tar.gz   ✅
   ↓
   ❌ GAP 24h
   ↓
mongo-dump-20260608-030000.tar.gz   ✅
```

## 2. Sistema responsável

`backend/server.py` linhas 765-768 registra:

```python
from routes.backup import daily_backup_job, weekly_migrate_job
scheduler.add_job(daily_backup_job,
                  CronTrigger(hour=3, minute=0),
                  id="mongo_daily_backup", replace_existing=True)
```

APScheduler com `CronTrigger(hour=3, minute=0)` UTC.
**Sem `misfire_grace_time` configurado.**

## 3. Evidência — execuções normais (06/jun e 08/jun)

```
2026-06-06 03:00:06,012 INFO ponto.backup — [backup-cron] mongo-dump-20260606-030000.tar.gz (18.6 MB)
2026-06-08 03:00:06,920 INFO ponto.backup — [backup-cron] mongo-dump-20260608-030000.tar.gz (20.7 MB)
```

## 4. Evidência — 07/jun na janela 02:55 → 03:10

**Comando executado:**
```
awk '/^2026-06-07 02:55/,/^2026-06-07 03:10/' /var/log/supervisor/backend.err.log
```

**Resultado: NENHUMA linha.** Zero atividade nesse intervalo.

## 5. Última atividade ANTES do gap

```
2026-06-07 02:04:00,865 WARNING ponto.whatsapp_meta — [meta] assinatura inválida company=co-demo
```

(última entrada de 02:04 — depois disso, silêncio total)

## 6. Primeira atividade DEPOIS do gap

```
2026-06-07 03:29:40,958 INFO drive_backup — [drive-scheduler] worker iniciado
2026-06-07 03:36:22,780 INFO drive_backup — [drive-scheduler] worker iniciado
2026-06-07 03:37:03,677 INFO drive_backup — [drive-scheduler] worker iniciado
... (vários restarts sucessivos do backend)
```

## 7. Diagnóstico

O backend estava **DOWN entre 02:04 e 03:29 UTC** em 07/jun (≈ 85 minutos), exatamente cobrindo a janela do cron job 03:00 UTC.

**Múltiplas mensagens `[drive-scheduler] worker iniciado` em 03:29-03:46** confirmam que o backend reiniciou várias vezes nesse intervalo.

### Por que o backup não foi recuperado?

`APScheduler`, sem o parâmetro `misfire_grace_time`, **descarta jobs com gatilho perdido** durante downtime do processo. Quando o backend voltou em 03:29, o trigger das 03:00 já tinha passado e foi descartado.

## 8. Causa raiz (RCA)

| Camada | Causa |
|--------|-------|
| **Imediata** | Backend offline às 03:00 UTC de 2026-06-07 |
| **Contribuinte** | APScheduler sem `misfire_grace_time` ⇒ job perdido não recupera |
| **Sistêmica** | Cluster Kubernetes/Emergent reiniciou o pod múltiplas vezes em sequência (≥10 restarts em 30 min vistos em 06/jun 00:21-01:12) |
| **Operacional** | Sem alerta automático quando 24h sem dump novo. Gap passou despercebido por 48h+. |

## 9. Por que houve restart? (Hipótese)

Os restarts repetidos (`worker iniciado` em loop) sugerem:

1. **Kubernetes health check failure** — pod sendo reiniciado pela orquestração.
2. **OOM (Out of Memory) kill** — não confirmado nesta auditoria (precisa olhar `dmesg` / `kubectl describe pod`, que estão fora do escopo READ-ONLY no container).
3. **Push de código com reload** — possível.

> Não é possível afirmar com 100% de certeza qual dos 3 sem acesso ao orquestrador.

## 10. Impactos

- **RPO degradado:** janela de 48h entre 06/jun 03:00 e 08/jun 03:00 sem backup.
- **Dados ativos no período:** todo o tráfego operacional de 07/jun (chamados, OS, WA inbound, schedulers de IA) ficou sem cópia de segurança.
- **Detecção:** o gap só foi descoberto nesta auditoria, 48h depois.

## 11. Mitigações recomendadas (NÃO executar sem aprovação)

| Ação | Esforço | Risco eliminado |
|------|---------|----------------|
| Adicionar `misfire_grace_time=3600` no `add_job` (1 linha) | 5 min | Job perdido por restart curto |
| Adicionar `coalesce=True` | 1 min | Multiple misfires combinados |
| Substituir CronTrigger por dual: 03:00 **E** 03:30 (redundância) | 5 min | Mitiga downtime de até 30 min |
| Cron host (systemd timer ou crontab) como redundância | 30 min | Independência do backend Python |
| Alerta quando 24h sem novo `.tar.gz` em `/app/backups/` | 30 min | Detecção rápida de gaps futuros |
| Mover backups para volume separado (PVC dedicado) | 1h | Sobrevive a pod restart com `/app` volátil |

## 12. Resposta à pergunta-mestra

> **"O que causou o gap de 07/jun?"**

**RESPOSTA:** O backend ficou offline durante a janela exata do cron job (03:00 UTC), e o APScheduler — sem `misfire_grace_time` — descartou silenciosamente o job. Quando o backend voltou às 03:29, o gatilho do dia já tinha sido perdido. Sem alerta automático, o gap ficou invisível por 48h até esta auditoria.

**Não foi falha de disco, permissão, mongodump nem código de backup.** Foi falha de **resiliência do scheduler**.
