# Política de Persistência de Dados — SmartProv

**Versão:** 1.0  •  **Data:** 2026-05-20

Documento que descreve **o que persiste** entre deploys, **como garantimos que
nada é apagado** quando uma nova estrutura é publicada, e **as regras
obrigatórias** que TODO desenvolvedor (humano ou IA) deve seguir.

---

## 1. Storage Layer

| Camada | Persistência | Observação |
|---|---|---|
| **MongoDB** (`MONGO_URL`) | ✅ Externo ao container — dados sobrevivem a redeploys, restarts e crashes | Backup é responsabilidade da infra (snapshots regulares) |
| **`.env` files** | ✅ Versionados na infra (não no Git) | Em produção on-premise, ficam em `/etc/smartprov/.env` |
| **`auth_info` WhatsApp** | ✅ Em Mongo (`wa_auth_state`) — sobrevive a restart do sidecar | NÃO usa filesystem |
| **Logs supervisor** | ⚠️ Locais ao container — perdidos em redeploy | Considerar shipping para syslog/Loki em prod |

---

## 2. Regras OBRIGATÓRIAS (quebrar = bug grave)

### 2.1 Seeds e bootstraps DEVEM ser idempotentes

**Padrão correto:**
```python
async def seed_xxx():
    if await db.collection.count_documents({...}) > 0:
        return  # já tem dado, NÃO sobrescreve
    await db.collection.insert_many([...])
```

**ANTIPADRÃO (proibido):**
```python
await db.collection.delete_many({})    # ❌ NUNCA no startup
await db.collection.drop()             # ❌ NUNCA no startup
await db.collection.replace_one({...}, upsert=True)  # ❌ Em seed automático
```

### 2.2 `delete_many` / `drop` SOMENTE em endpoints explícitos

Todo endpoint que apaga dados precisa:
- Estar atrás de `require_admin()` ou `require_finance()` (depending on scope)
- Logar a ação em `platform_audit` com `user_id` e timestamp
- Idealmente exigir confirmação textual no payload (ex: `confirm_text="DELETAR"`)

### 2.3 Migrations: só ADITIVAS

Quando precisar mudar schema:
- ✅ **Adicionar** novo campo opcional (com default no código)
- ✅ **Backfill** via script em `/app/backend/scripts/migrations/` rodado MANUALMENTE
- ❌ **NUNCA** renomear/remover campo direto em coleção viva
- ❌ **NUNCA** mudar tipo de campo (ex: string → int) sem migration controlada

### 2.4 Cadastros de produção NUNCA podem ser sobrescritos por código

Cadastros são propriedade do cliente:
- `collaborators`, `users`, `fin_suppliers`, `fin_categories`, `fin_cash_accounts`
- `fin_filiais`, `subscribers`, `tickets`, `aihub_agents` (prompts customizados)
- `company_branding`, `settings_by_company`, `bank_import_memory`
- `wa_auth_state`, `wa_conversations`, `isabella_prompt_fragments`

Se precisar atualizar valores default, criar nova coleção `xxx_templates` que
o usuário **opta** por aplicar via UI, **nunca** force-update no startup.

---

## 3. Inventário de seeds atuais (auditado 2026-05-20)

| Função | Localização | Idempotente? | Quando roda |
|---|---|---|---|
| `ensure_indexes` | `core.py` | ✅ Sim (Mongo skip se já existe) | Startup |
| `ensure_auth_indexes` | `auth.py:115` | ✅ Sim | Startup |
| `ensure_demo_company` | `routes/saas.py` | ✅ Sim (find_one+insert) | Startup |
| `seed_default_users` | `auth.py:123` | ✅ Sim (verifica `find_one`) | Startup |
| `_seed_demo_if_empty` | `server.py:228` | ✅ Sim (`count > 0: return`) | Startup |
| `_seed_demo_tickets` | `server.py:253` | ✅ Sim (`count > 0: return`) | Startup |
| `_seed_default_fragments` | `routes/isabella_prompt.py:469` | ✅ Sim (`count > 0: return`) | Sob demanda (endpoint) |
| `update_existing_agents` | `scripts/seed_training_agents.py:530` | ⚠️ **DESTRUTIVO** — sobrescreve `system_prompt` | Sob demanda APENAS (endpoint `/api/ai-training/reset-and-seed`) |
| `seed_br` (feriados) | `routes/feriados.py:181` | ⚠️ Faz `delete_many` antes de inserir | Sob demanda APENAS (endpoint `/api/admin/holidays/seed-br`) |

**Conclusão:** Nenhum seed destrutivo roda automaticamente no startup. ✅

---

## 4. Coleções críticas — proteção dupla

As coleções abaixo carregam **dados do cliente** que nunca podem ser perdidas
em deploy. Adicione novas conforme o produto cresce:

```python
PROTECTED_COLLECTIONS = [
    # Cadastros mestres
    "users", "collaborators", "companies", "company_branding",
    "settings_by_company", "fin_suppliers", "fin_categories",
    "fin_cash_accounts", "fin_filiais", "subscribers", "subscriber_phones",
    "subscriber_addresses", "subscriber_invoices",
    # Operação
    "tickets", "clock_records", "geofences",
    "fin_cash_movements", "fin_bills_payable", "fin_bills_receivable",
    "fin_installments",
    # IA e WhatsApp (custom do cliente)
    "aihub_agents", "isabella_prompt_fragments", "bank_import_memory",
    "ai_agent_switches", "wa_auth_state", "wa_conversations",
    "wa_messages",
    # Auditoria
    "platform_audit", "lousa_logs", "audit_log",
]
```

Qualquer operação `delete_many` / `drop` numa dessas coleções DEVE:
1. Estar atrás de feature flag (env var `ALLOW_DESTRUCTIVE_OPS=true`) ou
2. Estar atrás de `require_admin()` + confirm_text no payload

---

## 5. Backup recomendado (Produção)

Script disponível: `/app/backend/scripts/backup_mongo.sh`

```bash
# Executar via cron (ex: a cada 6h)
0 */6 * * * /app/backend/scripts/backup_mongo.sh
```

O script:
- Usa `mongodump` no DB inteiro
- Comprime para `.tar.gz` com timestamp
- Mantém 30 dias de retenção (rotação automática)
- Pode integrar com S3/rclone para backup off-site

### Restore (caso necessário)

```bash
mongorestore --uri="$MONGO_URL" --gzip --archive=backup-2026-05-20.tar.gz
```

---

## 6. Checklist antes de cada DEPLOY em produção

- [ ] Backup MongoDB executado nas últimas 6h
- [ ] Mudanças de schema têm migration em `/scripts/migrations/`
- [ ] Nenhum `delete_many`/`drop` foi adicionado em código que roda no startup
- [ ] `git diff` revisado por outro humano (ou IA com acesso ao PRD)
- [ ] Variáveis novas em `.env.example` documentadas
- [ ] `seed_*` novos verificados como idempotentes (`count > 0: return`)

---

## 7. Política de migração para on-premise (futuro)

Quando o cliente migrar para rack próprio:
1. **Dump** completo do Mongo do preview/staging atual
2. **Restore** no Mongo on-premise antes de subir o backend
3. Apontar `MONGO_URL` no `.env` on-premise para o Mongo local
4. **NUNCA** rodar `mongo drop` ou similar no servidor on-premise

Referência: `/app/memory/INFRA_LOCAL_DEPLOY.md`
