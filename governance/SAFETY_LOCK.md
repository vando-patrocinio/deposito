# 🛟 SmartProv — SAFETY LOCK (V1.0)

> Subordinado a `SYSTEM_CONSTITUTION.md`.
> Documenta as 3 medidas P0 contra cenários que quebram um ERP de provedor:
> **Backup + Disaster Recovery** · **Secrets Vault** · **Kill Switch Global + WhatsApp**.

---

## 1. Kill Switch (P0)

### 1.1 — Componentes controlados

| Componente | Efeito quando OFF |
|-----------|-------------------|
| `global` | Derruba todos os outros simultaneamente (master) |
| `whatsapp` | `safe_send_whatsapp` retorna `blocked_killswitch` sem enviar |
| `ai_actions` | Ações autônomas pulam execução (best-effort, depende do executor) |
| `scheduler` | Workers de schedulers pulam tick (best-effort) |

### 1.2 — Persistência

- Collection: `system_killswitch`
- Auditoria: cada toggle gera entrada em `audit_log` (kind=`killswitch_toggle`)

### 1.3 — Como acionar

**Via API (super_admin obrigatório):**

```bash
# Ler estado de todos os componentes
curl -X GET "$API/api/admin/safety/killswitch/status" \
  -H "Authorization: Bearer <jwt>"

# Desligar WhatsApp globalmente
curl -X POST "$API/api/admin/safety/killswitch/whatsapp" \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{"off": true, "reason": "incidente XYZ"}'

# Religar
curl -X POST "$API/api/admin/safety/killswitch/whatsapp" \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{"off": false, "reason": "incidente resolvido"}'

# Desligar tudo (PÂNICO)
curl -X POST "$API/api/admin/safety/killswitch/global" \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{"off": true, "reason": "panic"}'
```

### 1.4 — Hot-path (cobertura atual)

| Caminho | Verifica killswitch? |
|---------|---------------------|
| `safe_send_whatsapp()` em `services/homologation.py` | ✅ checa `whatsapp` antes de enviar |
| `motor_ia` schedulers | ⚠️ **falta integrar** (planejado próximo ciclo) |
| `ai_actions` autonomous executor | ⚠️ **falta integrar** (planejado próximo ciclo) |

> **Princípio:** kill switch é **best-effort**. Se a verificação falha (Mongo down), o sistema NÃO bloqueia (failopen) — mas registra o erro. Isso é intencional: kill switch deve PREVENIR envios, não introduzir novo SPOF.

---

## 2. Backup + Disaster Recovery (P0)

### 2.1 — Snapshot binário

- Comando: `mongodump --gzip` para diretório local (`/app/backups` por default).
- Wrapper Python: `services/mongo_backup.py::snapshot_now()`.
- Wrapper shell: `/app/ops/backup/mongo_backup.sh`.
- Retenção: `BACKUP_RETENTION_DAYS` (default `14` dias).

### 2.2 — Via API

```bash
# Listar snapshots existentes
curl -X GET "$API/api/admin/safety/backup/list" \
  -H "Authorization: Bearer <jwt>"

# Disparar snapshot manual
curl -X POST "$API/api/admin/safety/backup/snapshot" \
  -H "Authorization: Bearer <jwt>"

# Purgar antigos manualmente
curl -X POST "$API/api/admin/safety/backup/purge-old" \
  -H "Authorization: Bearer <jwt>"
```

### 2.3 — Via cron host (recomendado para produção)

```cron
# Snapshot diário 03h UTC
0 3 * * * /app/ops/backup/mongo_backup.sh >> /var/log/smartprov_backup.log 2>&1
```

### 2.4 — Restauração

```bash
# Listar snapshots
ls /app/backups/

# Restaurar
/app/ops/backup/mongo_restore.sh mongo-test_database-20260609-013000Z
# (vai pedir confirmação "RESTAURAR")
```

⚠️ **WARNING:** `--drop` é aplicado por collection — sobrescreve dados atuais.

### 2.5 — Variáveis de ambiente

| Variável | Default | Função |
|----------|---------|--------|
| `BACKUP_DIR` | `/app/backups` | Onde salvar snapshots |
| `BACKUP_RETENTION_DAYS` | `14` | Quantos dias manter |

### 2.6 — Dependência

`mongodump` deve estar instalado (mongodb-database-tools). Verificar:

```bash
which mongodump || apt-get install -y mongodb-database-tools
```

---

## 3. Secrets Vault (P0)

### 3.1 — Quando usar

Para **segredos NOVOS** que entram em produção (tokens de provedor piloto, chaves de revenda, credenciais de cliente). **NÃO substitui** o `.env` existente — adiciona camada.

### 3.2 — Setup inicial

```bash
# 1. Gerar master key (UMA ÚNICA VEZ)
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Output: ex.: "QkX9...44chars=="

# 2. Adicionar ao /app/backend/.env
SECRETS_MASTER_KEY=QkX9...44chars==

# 3. Restart
sudo supervisorctl restart backend
```

### 3.3 — Operação

```bash
# Set
curl -X POST "$API/api/admin/safety/secrets/PILOT_PROVIDER_TOKEN" \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{"value": "abc123...", "scope": "pilot-co-1", "hint": "Token do provedor X"}'

# List (NUNCA retorna valor — apenas metadados)
curl -X GET "$API/api/admin/safety/secrets/list?scope=pilot-co-1" \
  -H "Authorization: Bearer <jwt>"

# Delete
curl -X DELETE "$API/api/admin/safety/secrets/PILOT_PROVIDER_TOKEN?scope=pilot-co-1" \
  -H "Authorization: Bearer <jwt>"
```

### 3.4 — Uso em código

```python
from services.secrets_vault import get_secret

token = await get_secret("PILOT_PROVIDER_TOKEN", scope="pilot-co-1")
if not token:
    raise RuntimeError("token ausente — verificar vault")
```

### 3.5 — Princípios

- Master key NUNCA persistida em código ou Mongo.
- Valores **sempre** criptografados em repouso (Fernet AES-128 + HMAC).
- Listagem retorna apenas metadados (nome, scope, version, updated_at, hint).
- Toda alteração registrada em `audit_log` (kind=`secret_set` / `secret_delete`).

---

## 4. Auditoria de Cobertura

| Cenário (top 80% de incidentes ERP-ISP) | Mitigado por |
|----------------------------------------|--------------|
| Bug envia mensagem WhatsApp em massa indevida | Kill Switch `whatsapp` + `HOMOLOG_MODE` |
| Mongo corrompido / queda da partição | Backup diário + restore script |
| Vazamento de `.env` em PR/print | Secrets Vault (segredos novos) |
| Provider externo (Stripe/Asaas) mudou chave | `set_secret` rotaciona sem deploy |
| IA gerou loop de ações erradas | Kill Switch `ai_actions` |
| Scheduler enlouquecido | Kill Switch `scheduler` |
| Pane geral / ataque | Kill Switch `global` (mata tudo) |

---

## 5. Gaps Conhecidos (mitigar em ciclos futuros)

| # | Gap | Severidade |
|---|-----|-----------|
| G1 | Schedulers de IA ainda NÃO checam killswitch (best-effort) | 🟡 MÉDIA |
| G2 | `ai_actions` executor ainda NÃO checa killswitch | 🟡 MÉDIA |
| G3 | Backups armazenados localmente (sem off-site) | 🔴 ALTA |
| G4 | Sem teste automático de "restore funciona" | 🟡 MÉDIA |
| G5 | Master key do vault em `.env` (não em HSM) | 🟢 BAIXA (provisório) |

---

## 6. Comandos rápidos (panic playbook)

```bash
# 🚨 PÂNICO — DERRUBA TUDO
curl -X POST "$API/api/admin/safety/killswitch/global" \
  -H "Authorization: Bearer <jwt>" -H "Content-Type: application/json" \
  -d '{"off": true, "reason": "panic"}'

# 💾 BACKUP IMEDIATO
curl -X POST "$API/api/admin/safety/backup/snapshot" \
  -H "Authorization: Bearer <jwt>"

# ✅ RELIGA
curl -X POST "$API/api/admin/safety/killswitch/global" \
  -H "Authorization: Bearer <jwt>" -H "Content-Type: application/json" \
  -d '{"off": false, "reason": "incidente resolvido"}'
```

---

**Versão:** V1.0 — 2026-06-09
**Cobertura estimada de incidentes:** ~80% dos cenários ERP-ISP críticos.
