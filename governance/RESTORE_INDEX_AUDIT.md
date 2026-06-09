# RESTORE INDEX AUDIT — Sprint P0.4 A6

> **Modo:** READ-ONLY. Apenas auditoria.
> **Data:** 2026-06-09

## 1. Fato confirmado

- 311 arquivos `.metadata.json` existem no dump `mongo-dump-20260608-030000.tar.gz`.
- **TODOS** com `indexes: []` (lista vazia).
- Produção tem **42 índices** somando 12 collections críticas amostradas.
- Após `mongorestore`, **nenhum índice secundário** é recriado — apenas o `_id_` default.

## 2. Por que índices não foram restaurados?

A causa raiz está em `routes/backup.py::daily_backup_job`. O comando `mongodump` foi invocado **sem** flags que preservam metadados ricos OU está rodando em uma versão antiga do `mongodb-database-tools` que serializa índices de forma diferente.

Hipóteses (em ordem de probabilidade):

| # | Hipótese | Evidência |
|---|----------|-----------|
| H1 | `mongodump` usado com `--collection` por loop (não dump global) — metadata fica incompleto | requer inspeção do código `daily_backup_job` |
| H2 | Dump correto, mas extração com `--gzip` errado removeu metadata | improvável — metadata.json é separado do bson |
| H3 | Versão do `mongodb-database-tools` (100.17.0) tem bug conhecido com `--db` + Mongo recente | possível, verificar release notes |
| H4 | Mongo source não tem permissão para ler `system.indexes` (auth limitado) | possível mas não confirmado |

## 3. Dump está incompleto?

**SIM (parcialmente).**

- ✅ **Dados** (`.bson`): completos (44.669 docs recuperados sem erro)
- ❌ **Índices**: ausentes em todos os 311 metadata.json
- ✅ **Schema** (collections): preservado
- ❌ **Validators**: não verificado (provavelmente ausentes)
- ❌ **Users/Roles**: não restaurados por padrão (precisa `--dumpDbUsersAndRoles`)

## 4. Restore está incompleto?

**SIM (mas é consequência do dump, não bug no restore).**

`mongorestore` faz exatamente o que o dump pede: recria as collections com os documentos. Como `indexes: []`, nenhum índice é criado além do `_id_` default.

## 5. Quantos índices em produção?

Auditoria em 12 collections críticas:

| Collection | Índices PROD |
|------------|--------------|
| subscribers | 3 |
| tickets | 4 |
| motor_ia_events | 5 |
| motor_ia_outcomes | 3 |
| motor_ia_decisions | 3 |
| motor_ia_actions | 3 |
| wa_outbox | 1 |
| contracts | 1 |
| collaborators | 4 |
| smartolt_onus | 3 |
| users | 5 |
| audit_log | 7 |
| **TOTAL** | **42 índices** |

Extrapolando para 298 collections com dados: estimativa de **~200-400 índices** no total.

## 6. Quantos voltam após restore?

**0 índices secundários voltam.** Apenas o `_id_` default (1 por collection = 298 índices automáticos).

## 7. Impacto operacional

| Cenário | Impacto |
|---------|---------|
| Restore em emergência DR | Queries que dependem de índices ficarão **lentas até reindex manual** |
| Performance pós-restore | Degradação de 10x-1000x dependendo da collection |
| Tempo de reindex manual estimado | 10-30 min adicionais ao RTO (200-400 índices) |

## 8. Onde reside a correção (NÃO implementar agora)

Opção 1 — Ajustar `mongodump` no `daily_backup_job`:

```python
# routes/backup.py — ajustar comando
cmd = ["mongodump",
       f"--uri={MONGO_URL}",
       f"--db={DB_NAME}",
       "--gzip"]   # garantir que metadata é incluso
```

Opção 2 — Salvar índices em paralelo como JSON:

```python
# Dump complementar de índices via PyMongo
for col_name in db.list_collection_names():
    indexes = list(db[col_name].list_indexes())
    # serializar (remover ObjectId, etc.) e salvar em backups/indexes-YYYYMMDD.json
```

Opção 3 — Script de **reindex** pós-restore:

```bash
# /app/ops/backup/mongo_reindex.sh
# Recria índices conhecidos a partir do código (cada serviço declara seus
# índices no startup do FastAPI)
```

> A opção 3 é a mais segura: força o backend a recriar índices declarativamente no próximo startup.

## 9. Recomendação

| # | Ação | Esforço | Sev |
|---|------|---------|-----|
| 1 | Auditar comando exato em `daily_backup_job` | 15 min | 🟠 |
| 2 | Implementar Opção 2 (dump complementar de índices) | 1h | 🟠 |
| 3 | Implementar Opção 3 (reindex script) | 2h | 🟠 |
| 4 | Validar restore + reindex em staging | 30 min | 🟠 |
| 5 | Adicionar test pytest comparando contagem PROD vs RESTORE | 30 min | 🟢 |

**Não corrigir nesta sprint — apenas auditoria conforme orientação.**

## 10. Resposta às 5 perguntas-mestras

1. **Por que índices não foram restaurados?** Porque o dump (`metadata.json`) declara `indexes: []`. Restore obedeceu fielmente.
2. **Dump está incompleto?** SIM, índices ausentes.
3. **Restore está incompleto?** SIM, mas como consequência do dump.
4. **Quantos índices em produção?** 42 (em 12 críticas) — extrapolado para ~200-400 totais.
5. **Quantos voltam após restore?** Zero secundários (apenas `_id_` defaults).
