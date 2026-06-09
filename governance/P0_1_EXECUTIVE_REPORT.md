# P0.1 — RELATÓRIO EXECUTIVO FINAL

> **Sprint:** P0.1 Remediação de Segurança e Blindagem Real
> **Modo desta auditoria:** READ-ONLY estrito
> **Data:** 2026-06-09
> **Auditor:** Agente E1
> **Documentos correlatos:** `WHATSAPP_BYPASS_REPORT.md`, `BACKUP_RESTORE_AUDIT.md`, `VAULT_READINESS_REPORT.md`, `BACKUP_GAP_2026_06_07.md`

---

## RESUMO EXECUTIVO

### ✅ O que estava correto

1. **Inventário & Governança documental** — 18 docs em `/app/governance/` e `/app/releases/`, listas brutas auditáveis. Auditável.
2. **Stash safety net** — 10 stashes git preservados, recuperação real testada (incidente 06/jun).
3. **Backup local funciona** — 7 dumps `.tar.gz`, 311 collections, sistema antigo `routes/backup.py` rodando via APScheduler.
4. **Gateway oficial existe** — `safe_send_whatsapp` faz tudo certo (HOMOLOG_MODE + Kill Switch + Whitelist).
5. **Sidecar Baileys controlado** — porta 3002 local, configurado para `TEST_PHONE`. Hoje protegido **por configuração**.

### ❌ O que estava incorreto

1. **Score informado anteriormente (85%) era inflado.** Real ≈ 58%.
2. **Gateway WhatsApp não é único** — 12 arquivos com bypass, ≈ 51 chamadas diretas ao sidecar.
3. **Kill Switch cobre só 1 hot-path** (1 ponto em `homologation.py`).
4. **Vault inerte** — sem `SECRETS_MASTER_KEY`, 0 segredos migrados, 0 consumidores.
5. **Off-site backup (Google Drive) quebrado há 4 dias** (token revogado 06/jun 06:01).
6. **APScheduler sem `misfire_grace_time`** — gap de 07/jun foi consequência direta.
7. **Sem alerta de backup faltante** — gap só descoberto em auditoria humana.
8. **18 segredos sensíveis em `.env` texto plano**.

### 🔴 O que representa risco REAL (não teórico)

1. **Off-site backup caído** — único backup é local, no mesmo disco do app (75% usado).
2. **75-85% do tráfego WA bypassa o gateway** — se `HOMOLOG_MODE` for desligado por engano, mensagens reais saem imediatamente.
3. **Restore nunca testado em produção** — RTO real é desconhecido.
4. **Backend instável em 06-07/jun** (múltiplos restarts) — causa raiz do gap ainda não tratada.
5. **Token Google Drive revogado sem alerta** — descoberto só nesta auditoria.

### 🟡 O que é apenas risco TEÓRICO

1. Vault inerte: hoje **não há nada para vazar do vault** (está vazio). O risco é a aparência de proteção que ele dá.
2. Kill Switch parcial: hoje **não foi acionado em emergência**, então a baixa cobertura ainda não causou dano.
3. Backup local no mesmo disco: hoje o disco está saudável e há espaço.

---

## MATRIZ DE RISCO

| # | Risco | Severidade | Categoria | Evidência |
|---|-------|-----------|-----------|-----------|
| R1 | 12 arquivos WhatsApp com bypass (~51 chamadas) | 🔴 **CRÍTICO** | Arquitetura | `WHATSAPP_BYPASS_REPORT.md` §2 |
| R2 | Off-site backup quebrado (Drive token revogado) | 🔴 **CRÍTICO** | Operacional | `drive_backup` logs 06-08/jun |
| R3 | APScheduler sem `misfire_grace_time` | 🔴 **CRÍTICO** | Resiliência | `BACKUP_GAP_2026_06_07.md` §8 |
| R4 | Restore completo nunca validado | 🟠 ALTO | DR | `BACKUP_RESTORE_AUDIT.md` §3 |
| R5 | Sem alerta de backup faltante | 🟠 ALTO | Detecção | descoberto só em auditoria |
| R6 | Kill Switch cobre 1/N hot-paths | 🟠 ALTO | Arquitetura | grep no código |
| R7 | 18 segredos em `.env` texto plano | 🟠 ALTO | Segurança | inventário .env |
| R8 | `WA_SIDECAR_TOKEN` e `ASAAS_API_KEY` vazios | 🟡 MÉDIO | Config | `len≈0` no `.env` |
| R9 | Backups locais no mesmo disco do app (75% usado) | 🟡 MÉDIO | Resiliência | `df -h` |
| R10 | Vault inerte (cofre sem chave) | 🟡 MÉDIO | Aparência de segurança | grep + Mongo count |
| R11 | Ticket_quality.py órfão sem `include_router` | 🟢 BAIXO | Higiene | `routes_orphans.txt` |
| R12 | Múltiplos restarts de backend em 06/jun | 🟢 BAIXO | Estabilidade | logs supervisor |

---

## SCORE DE PROTEÇÃO RECALCULADO — baseado em evidências reais

| Componente | Peso | Score real | Pts | Fonte de evidência |
|-----------|------|-----------|-----|---------------------|
| Inventário e governança documental | 12% | 100% | 12,0 | 18 docs concretos em disco |
| Git history + stash safety net | 10% | 100% | 10,0 | recuperação real 06/jun |
| Backup binário existe e roda | 12% | **75%** | 9,0 | 6/7 dias OK · gap 07/jun · sem off-site |
| Restore validado empiricamente | 8% | **0%** | 0,0 | nunca executado em prod |
| Kill Switch cobertura real (1 hot-path) | 10% | **15%** | 1,5 | 1/N chamadas WA cobertas |
| Gateway WhatsApp unificado | 12% | **20%** | 2,4 | 3 oficiais vs 12 bypass |
| Vault em uso operacional | 6% | **0%** | 0,0 | MASTER_KEY ausente · 0 consumidores |
| Testes automatizados críticos | 5% | 80% | 4,0 | 31/31 do escopo P0 PASS |
| Backup off-site funcional | 5% | **0%** | 0,0 | Drive token revogado há 4 dias |
| Alertas/detecção de falha | 5% | **0%** | 0,0 | gap 07/jun passou despercebido |
| CI/CD enforcement | 5% | 0% | 0,0 | sem hooks ativos |
| Drift monitoring | 5% | 0% | 0,0 | inventário estático |
| Resiliência scheduler (misfire) | 5% | 0% | 0,0 | causa raiz do gap |

```
Score = 12.0 + 10.0 + 9.0 + 0.0
      + 1.5 + 2.4 + 0.0 + 4.0
      + 0.0 + 0.0 + 0.0 + 0.0 + 0.0
      = 38.9 — arredondando, ≈ 39%
```

⚠️ **A descoberta do off-site quebrado + restore nunca testado + bypasses WA + scheduler frágil revelou que o sistema está significativamente menos protegido do que reportado anteriormente (85% → 58% → agora 39% real).**

---

## PLANO DE REMEDIAÇÃO

### 🔴 Prioridade P0 (esta sprint, em ordem)

| # | Ação | Esforço | Pts ganhos |
|---|------|---------|-----------|
| P0.1 | Reconectar Google Drive (`co-demo`) — apenas re-autenticar, sem código | 15 min | +5 pp |
| P0.2 | Adicionar `misfire_grace_time=3600` e `coalesce=True` no `add_job` do `daily_backup_job` (1 linha em `server.py`) | 5 min | +5 pp |
| P0.3 | Executar 1 restore completo em staging e cronometrar RTO real | 30 min | +8 pp |
| P0.4 | Gerar e popular `SECRETS_MASTER_KEY` no `.env` + migrar 3 segredos críticos (`STRIPE_API_KEY`, `EMERGENT_LLM_KEY`, `GOOGLE_CLIENT_SECRET`) | 2 h | +6 pp |
| P0.5 | Refatorar 4 endpoints públicos de WhatsApp (whatsapp_baileys `/send`, disparo_boleto, disparo_promo, whatsapp_campaigns) para passarem por `safe_send_whatsapp` | 6-8 h | +12 pp |

**Score esperado após P0:** ≈ **75%**

### 🟠 Prioridade P1 (próxima sprint)

| # | Ação | Esforço |
|---|------|---------|
| P1.1 | Refatorar 8 bypasses restantes (workers + referrals/wifi/neo_reports) | 8 h |
| P1.2 | Alerta automático de backup ausente (>24h) | 1 h |
| P1.3 | Pre-commit hook que enforce locks de governança | 3 h |
| P1.4 | Cron host (crontab) como redundância ao APScheduler | 1 h |
| P1.5 | Volume PVC dedicado para `/app/backups` | infra |

**Score esperado após P1:** ≈ **88%**

### 🟡 Prioridade P2 (backlog)

| # | Ação | Esforço |
|---|------|---------|
| P2.1 | Migrar 15 segredos restantes ao vault | 4 h |
| P2.2 | Drift detection automática (inventário snapshot diário) | 4 h |
| P2.3 | Testes E2E de restore via pytest | 2 h |
| P2.4 | Investigar OOM/restarts repetidos do backend em 06/jun | infra |

**Score esperado após P2:** ≈ **94%**

---

## CRONOGRAMA SUGERIDO

| Janela | Ações |
|--------|-------|
| **Hoje + 1h** | P0.1 + P0.2 (re-conectar Drive + misfire) |
| **Próximas 24h** | P0.3 + P0.4 (RTO real + vault funcional) |
| **Próximos 7 dias** | P0.5 (4 endpoints públicos refatorados) |
| **Sprint seguinte** | P1.1 a P1.5 |

---

**Decisão pendente do CTO:** autorizar execução de P0.1 a P0.5 conforme escopo acima, ou ajustar priorização.

**Nada será implementado sem aprovação explícita.**
