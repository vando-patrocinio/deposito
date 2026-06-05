# 📦 Sistema de Backup MongoDB — Guia Completo

> 5 features integradas no painel **Sistema → Backup DB** (super-admin).

---

## 🔧 Endpoints Disponíveis (`/api/admin/backup/`)

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/list` | Lista backups locais |
| POST | `/create` | Gera novo dump (mongodump + tar.gz) |
| GET | `/download/{filename}` | Stream do .tar.gz |
| DELETE | `/{filename}` | Remove backup do disco |
| GET | `/drive-status` | Status conexão Google Drive |
| POST | `/upload-drive/{filename}` | Sobe backup específico pro Drive |
| POST | `/restore` (multipart) | Restaura DB de um .tar.gz |
| POST | `/migrate-from-remote` | Pega dump de OUTRO ambiente Emergent |
| GET | `/migrate-config` | Lê config da migração agendada |
| POST | `/migrate-config` | Salva config (URL + token + drop) |

---

## 🔐 Segurança

| Camada | Proteção |
|---|---|
| Auth | Todas as rotas requerem `is_super_admin: true` no JWT |
| Path traversal | Regex `^mongo-dump-\d{8}-\d{6}\.tar\.gz$` |
| SSRF (migrate) | Whitelist: `.emergent.host`, `.emergentagent.com`, `.cluster-7.deploy.emergentcf.cloud` |
| Restore | Triple-confirm: super-admin + `confirm="RESTORE"` + window.confirm |
| Upload | Max 2GB, timeout 30min |
| Drive | `_is_invalid_grant` marca `needs_reconnect` automaticamente |
| Token storage | `db.backup_config` (coleção dedicada) com token preview mascarado |

---

## ⏰ Cron Jobs

| ID | Schedule | Função |
|---|---|---|
| `mongo_daily_backup` | Todo dia **03:00 UTC** | Dump + rotação 7 últimos + upload Drive |
| `mongo_weekly_migrate` | Todo **domingo 04:00 UTC** | Migra PROD → este (se enabled) |

---

## 🧪 Testes Pytest (18/18 verdes)

| Arquivo | Testes |
|---|---|
| `test_iter205_backup_endpoints.py` | 7 — regex SAFE_FILENAME, list, auth, dir |
| `test_iter205c_backup_cron.py` | 4 — rotation 10→7, noop <7, ignores non-globs, async |
| `test_iter205f_migrate_remote.py` | 3 — anti-SSRF (5 OK + 12 blocked), MigratePayload |
| `test_iter205g_migrate_cron.py` | 4 — coleção dedicada, cron registrado, defaults |

---

## 🚀 Fluxos de Uso

### A) Backup manual + download
1. Sistema → Backup DB
2. Clica **"Gerar Novo Backup"** (~1 min)
3. Clica **"Baixar"** na linha do backup

### B) Restore (recuperação de desastre)
1. Backup DB → **Zona perigosa**
2. Seleciona o .tar.gz
3. Marca/desmarca **--drop** (apagar antes ou só adicionar)
4. Digita **RESTAURAR**
5. Clica **"Restaurar MongoDB"**

### C) Migrar PROD → PREVIEW em 1 clique
1. Login no PROD com super-admin → DevTools → copia `access_token`
2. PREVIEW → Backup DB → card azul "Migrar de outro ambiente"
3. Cola URL e token, marca drop
4. Clica **"Migrar agora"** (~2-5 min)

### D) Migrar automaticamente todo domingo
1. Mesmo card azul → sub-card "Migração automática semanal"
2. Cola token + clica **"Ativar agendamento"**
3. Pronto. Cron roda toda semana, status fica visível no card.

---

## 💡 Boas Práticas

- **Antes de qualquer rollback ou deploy importante**, gera backup manual + faz download
- **Reconecte o Google Drive a cada ~6 meses** (refresh_token do Google expira)
- Mantenha pelo menos **1 backup baixado off-line** na sua VPS (caso pod do Emergent caia)
- **Não compartilhe seu JWT** — ele dá acesso super-admin. Se vazar, mude a senha imediatamente.

---

Criado pelos iter205a-g em 01-02/06/2026.
