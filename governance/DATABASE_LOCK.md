# 🔐 SmartProv — DATABASE LOCK (V1.0)

> Subordinado a `SYSTEM_CONSTITUTION.md`.
> **Schema e collections protegidas** contra perda silenciosa.

---

## 1. Cluster Mongo (TRAVADO)

| Item | Valor | Origem |
|------|-------|--------|
| Cliente | `AsyncIOMotorClient` | exclusivamente |
| URL | `os.environ['MONGO_URL']` | `/app/backend/.env` |
| Database | `os.environ['DB_NAME']` | `/app/backend/.env` (atual: `test_database`) |
| Driver name | "Motor" | versão 3.3.1 |

**Proibido:**
- Hardcodar `MONGO_URL` ou `DB_NAME` em qualquer arquivo `.py`.
- Usar `pymongo` síncrono em hot-path (apenas em scripts de migração).
- Criar segundo cliente Mongo (todo acesso passa por `database.py`).

---

## 2. Collections Críticas (não podem desaparecer)

### Tier 1 — Patrimônio operacional (perda = parar empresa)

```
subscribers              tickets                  subscriber_invoices
contracts                appointments             collaborators
users                    plans                    smartolt_onus
ctos                     motor_ia_events          motor_ia_decisions
motor_ia_actions         motor_ia_outcomes        motor_ia_learnings
motor_ia_autonomous_cycles
```

### Tier 2 — Patrimônio analítico (perda = perder histórico)

```
motor_ia_subscriber_scores       motor_ia_revenue_attribution
motor_ia_cohorts                 motor_ia_cohort_members
motor_ia_causality               knowledge_graph_nodes
knowledge_graph_edges            observability_incidents
audit_log                        ai_evaluations
ai_corrections                   ai_training_*
aihub_*                          churn_*
data_quality_*                   nervous_system_*
```

### Tier 3 — Patrimônio integrativo (WhatsApp/atendimento)

```
wa_outbox                wa_messages_sent         wa_messages_inbound
whatsapp_conversations   whatsapp_messages        atlaz_clients_cache
isabella_*               atendimento_*            atlaz_invoices_cache
```

### Tier 4 — Operacional auxiliar

```
fleet_*                  security_*               parceria_*
referrals                loyalty_*                wifi_hotspot_*
notifications            holidays                 conselho_ia_*
preventive_*             smartolt_push_*          radius_*
```

**Total auditado:** 120 collections únicas referenciadas no backend.

---

## 3. Convenções de Schema (TRAVADAS)

### IDs

| Padrão | Uso |
|--------|-----|
| `_id: ObjectId` | gerado pelo Mongo (não serializar bruto) |
| `id: "<prefix>-<uuid12>"` | id de negócio idempotente (ex: `tkt-abc123def456`) |
| `*_id: "<prefix>-..."` | foreign keys de negócio (ex: `subscriber_id`, `cycle_id`) |

### Campos obrigatórios em todo documento de negócio

| Campo | Tipo | Obrigatório |
|-------|------|-------------|
| `id` | str | SIM |
| `company_id` | str | SIM (multi-tenant) |
| `created_at` | ISO 8601 UTC | SIM |
| `environment` | str | SIM em coleções WhatsApp/Outcomes (`homolog` / `production` / `causality_pilot`) |

### Datetime

- **Obrigatório:** `datetime.now(timezone.utc).isoformat()`
- **Proibido:** `datetime.utcnow()` (sem timezone)
- **Proibido:** strings sem timezone (`"2026-06-09T00:00:00"`)

---

## 4. Multi-Tenancy (TRAVADO)

Toda query em collections Tier 1, 2, 3 **DEVE** incluir `company_id` no filtro. Violação é bug crítico.

**Exemplo correto:**
```python
docs = await db.tickets.find({"company_id": cid, "status": "open"}).to_list(100)
```

**Exemplo proibido (vaza dados entre tenants):**
```python
docs = await db.tickets.find({"status": "open"}).to_list(100)  # ❌
```

---

## 5. Environments (TRAVADO)

Toda operação que persiste outcomes financeiros, mensagens WhatsApp ou métricas de causalidade **DEVE** marcar `environment`:

| Valor | Significado |
|-------|-------------|
| `"production"` | Tráfego real, métricas válidas |
| `"homolog"` | Modo homologação, NÃO contar em métricas |
| `"causality_pilot"` | Whitelist `CAUSALITY_PILOT_PHONES`, métricas isoladas |

Filtros de produção **DEVEM** sempre incluir `{"environment": {"$ne": "homolog"}}` (ou `{"$in": ["production"]}` explícito).

---

## 6. Backups e Recuperação

### Backup atual (2026-06-09)

- **Git stash:** 10 stashes preservados (safety net contra `lint-staged`).
- **Git history:** completo via `git log --all`.
- **Mongo:** sem snapshot binário — **GAP CRÍTICO** (ver `RELEASE_LOCK.md` item 7).

### Recuperação testada

| Cenário | Procedimento | Status |
|--------|-------------|--------|
| Perda de working tree | `git stash apply stash@{0}` | ✅ TESTADO 2026-06-09 |
| Perda de commit | `git reflog` + `git cherry-pick` | ✅ testável |
| Perda de stash | `git fsck --unreachable` | ⚠️ requer atenção |
| Perda de Mongo | mongodump/mongorestore | ❌ NÃO IMPLEMENTADO |

---

## 7. Migrações

Migrações de schema **DEVEM**:

1. Ser scriptadas em `/app/backend/services/` com prefixo `migration_*` ou ser idempotentes (re-executáveis).
2. Ter entrada em `/app/releases/DECISIONS.md` como ADR.
3. Ter testes em `/app/backend/tests/test_migration_*.py`.
4. Ter caminho de rollback documentado.

---

## 8. Auditoria (comando)

Listar todas as collections referenciadas no código:

```bash
cd /app && grep -rEho "db\.[a-z_][a-z_0-9]*" backend/ --include="*.py" \
  | sed 's/db\.//' | sort -u | wc -l
```

Resultado esperado: **≥120**. Decréscimo súbito = patrimônio em risco.

---

**Versão:** V1.0 — 2026-06-09
