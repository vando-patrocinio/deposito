# BACKUP & RESTORE AUDIT — Sprint P0.1

> **Modo:** READ-ONLY estrito. Nenhum restore destrutivo executado.
> **Data:** 2026-06-09

## 1. Inventário de backups locais

Diretório: `/app/backups/` (default não configurado em `.env` — usa hardcode em `routes/backup.py`).

| Arquivo | Tamanho | Data | Status |
|---------|---------|------|--------|
| mongo-dump-20260602-003006.tar.gz | 16,3 MB | 2026-06-02 00:30 | ✅ |
| mongo-dump-20260602-030000.tar.gz | 16,3 MB | 2026-06-02 03:00 | ✅ |
| mongo-dump-20260603-030000.tar.gz | 16,5 MB | 2026-06-03 03:00 | ✅ |
| mongo-dump-20260604-030000.tar.gz | 16,6 MB | 2026-06-04 03:00 | ✅ |
| mongo-dump-20260605-030000.tar.gz | 16,7 MB | 2026-06-05 03:00 | ✅ |
| mongo-dump-20260606-030000.tar.gz | 18,6 MB | 2026-06-06 03:00 | ✅ |
| **2026-06-07** | — | — | 🔴 **AUSENTE (ver BACKUP_GAP_2026_06_07.md)** |
| mongo-dump-20260608-030000.tar.gz | 20,7 MB | 2026-06-08 03:00 | ✅ |

- **Mais recente:** `mongo-dump-20260608-030000.tar.gz` (≈ 22h atrás no momento desta auditoria).
- **Cobertura por collections:** 311 arquivos `.bson` no dump mais recente (cobertura ampla — todas as coleções principais).

## 2. Sistema executor

| Componente | Função | Origem |
|-----------|--------|--------|
| `routes/backup.py::daily_backup_job` | gera tarball local | APScheduler `CronTrigger(hour=3, minute=0)` UTC |
| `routes/backup.py::weekly_migrate_job` | migração entre ambientes | APScheduler `CronTrigger(day_of_week="sun", hour=4, minute=0)` |
| `services/drive_backup.py::_upload_to_drive` | upload paralelo Google Drive | **🔴 FALHANDO desde 06/jun** (token revogado) |

## 3. Procedimento de restore disponível

### Caminhos identificados

| Caminho | Tipo | Status |
|---------|------|--------|
| `POST /api/admin/backup/restore` | endpoint REST (recebe upload tar.gz, extrai com tarfile nativo, mongorestore por collection) | ✅ implementado em `routes/backup.py:175` |
| `/app/ops/backup/mongo_restore.sh` | script shell (mongorestore --drop --gzip) | ✅ criado em V9.4 |
| `services/drive_backup.py` restore | restore a partir do Google Drive | ✅ existe — `drive_restore_log` tem 13 docs |

### Cobertura de teste

| Teste | Status |
|-------|--------|
| pytest cobre `daily_backup_job`? | ✅ existe `tests/test_iter205_backup_endpoints.py` e `test_iter205c_backup_cron.py` |
| pytest cobre restore de tarball completo? | ❌ **NENHUM** |
| Já houve restore completo executado em produção? | ❌ NUNCA. 13 restores em `drive_restore_log` foram apenas de coleção `plans` em modo merge |

## 4. RPO real (Recovery Point Objective)

| Condição | RPO |
|----------|-----|
| Cenário normal | ≤ 24h |
| Cenário com gap (como 07/jun) | até **48h** |
| Janela máxima observada na história recente | 48h (06/jun 03:00 → 08/jun 03:00) |

## 5. RTO estimado (Recovery Time Objective)

| Etapa | Tempo estimado |
|-------|---------------|
| Identificar tarball correto | 2 min |
| Download/cópia para nó destino | 1 min (local, 22 MB) |
| `tar -xzf` + `mongorestore --drop --gzip` | 3–8 min (311 collections, ~22 MB comprimidos → ~150 MB descomprimidos estimado) |
| Reinício do backend + validação smoke | 5 min |
| **Total estimado** | **≈ 15 min** |

> ⚠️ **Estimativa NÃO validada empiricamente.** Restore completo nunca foi cronometrado.

## 6. Gaps encontrados

| # | Gap | Severidade |
|---|-----|-----------|
| G1 | Sem teste pytest cobrindo restore completo de tarball | 🟠 ALTO |
| G2 | RTO nunca medido em ambiente real | 🟠 ALTO |
| G3 | Upload para Google Drive FALHANDO há ≥ 4 dias (token revogado) — backups locais isolados | 🔴 CRÍTICO |
| G4 | Sem off-site backup operacional (Drive quebrado) | 🔴 CRÍTICO |
| G5 | Backups locais no mesmo disco que `/app` (75% usado, 2,6 GB livres) | 🟡 MÉDIO |
| G6 | Sem alerta automático quando job falha (gap de 07/jun passou despercebido) | 🟠 ALTO |
| G7 | `BACKUP_DIR` hardcoded em `routes/backup.py` (default `/app/backups`) — `.env` não controla | 🟡 MÉDIO |
| G8 | APScheduler sem `misfire_grace_time` — job perdido NÃO recupera (causa raiz do gap 07/jun) | 🔴 CRÍTICO |

## 7. Dependências externas

- `mongodump` ✅ instalado (versão 100.17.0)
- `mongorestore` ✅ instalado
- `cryptography` ✅ 47.0.0
- Google Drive token de `co-demo` ❌ **REVOGADO** desde 2026-06-06 06:01

## 8. Resposta à pergunta-mestra

> **"O restore é confiável ou não?"**

**RESPOSTA:** **PARCIALMENTE.**

- ✅ Backups locais existem e estão íntegros (7 dumps, formato `.tar.gz` válido).
- ✅ Procedimento de restore existe e está documentado.
- ❌ Restore completo **nunca foi validado empiricamente** — RTO é estimativa.
- ❌ Off-site (Google Drive) **está quebrado há 4 dias** — único backup é o local.
- ❌ Sem alertas: o gap de 07/jun **passou despercebido** até esta auditoria.

**Veredito honesto:** confiança **baixa-média**. Há infraestrutura, mas faltam testes empíricos e a redundância off-site está caída.

---

**Próximos passos sugeridos (fora desta auditoria):**
1. Reconectar token Google Drive (`co-demo`).
2. Executar 1 restore completo em ambiente staging e cronometrar RTO real.
3. Adicionar `misfire_grace_time=3600` no `add_job` do `daily_backup_job`.
4. Criar alerta quando 24h sem dump novo em `/app/backups/`.
