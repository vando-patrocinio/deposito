# IAM v2 — Plano de Backup & Rollback (ETAPA 2.1 P1)

**Data:** 13/06/2026
**Status:** Procedimento aprovado pelo CTO. NÃO executado.
**Pré-requisito obrigatório antes de qualquer Phase ≥1 escrever em produção.**

---

## 1. Collections afetadas pela migração

### Read-only durante todo o ciclo (não sofrem escrita pelo IAM v2)
- `tickets`, `subscribers`, `clients`, `lousa_*` etc. — não são tocadas.

### Lidas e potencialmente reescritas pelas phases
| Collection | Phase que escreve | Tipo de mudança |
|---|---:|---|
| `users` | shim (dual-write) | Adiciona `_legacy_user_id` ref no Identity |
| `collaborators` | shim (dual-write) | Adiciona `_legacy_collaborator_id` ref |
| `access_profiles` | 3, 4 | Adiciona `legacy_role_mapping` |
| `user_magic_links` | 3 | Lê e converte em `credentials` |
| `client_portal_users`, `fleet_portal_users`, `parcerias_partner_users`, `security_portal_users` | 5 | Lê e converte em `credentials(type=portal_X)` |
| `public_access_tokens` | 5 | Lê e converte em `credentials(type=api_key)` |

### Criadas do zero (não existem ainda)
- `identities` (alvo Phase 1+2)
- `credentials` (alvo Phase 3+5)
- `memberships` (alvo Phase 4)
- `sessions` (alvo Phase 6)
- `audit_authn`, `audit_authz`, `audit_identity`, `audit_member`, `audit_profile`, `audit_creden` (alvo ETAPA 7)
- `iam_migration_log` (log das phases — já criado quando Phase 0 rodou)

---

## 2. Procedimento de backup (passo a passo)

### 2.1 — Cenário ENTERPRISE (preferencial)

**Pré-requisito não atendido hoje:** Bucket S3 com Object Lock (Governance, 7 anos).

```bash
# Em SHELL do operador (não automatizado)
TS=$(date -u +%Y%m%d_%H%M%S)
BACKUP_DIR=/tmp/iam_backup_${TS}
mkdir -p ${BACKUP_DIR}

# 1. Dump completo de TODAS as collections IAM
mongodump \
  --uri="${MONGO_URL}" \
  --db="${DB_NAME}" \
  --collection=users \
  --out=${BACKUP_DIR}/

mongodump --uri="${MONGO_URL}" --db="${DB_NAME}" --collection=collaborators        --out=${BACKUP_DIR}/
mongodump --uri="${MONGO_URL}" --db="${DB_NAME}" --collection=access_profiles      --out=${BACKUP_DIR}/
mongodump --uri="${MONGO_URL}" --db="${DB_NAME}" --collection=user_magic_links     --out=${BACKUP_DIR}/
mongodump --uri="${MONGO_URL}" --db="${DB_NAME}" --collection=client_portal_users  --out=${BACKUP_DIR}/
mongodump --uri="${MONGO_URL}" --db="${DB_NAME}" --collection=fleet_portal_users   --out=${BACKUP_DIR}/
mongodump --uri="${MONGO_URL}" --db="${DB_NAME}" --collection=parcerias_partner_users --out=${BACKUP_DIR}/
mongodump --uri="${MONGO_URL}" --db="${DB_NAME}" --collection=security_portal_users --out=${BACKUP_DIR}/
mongodump --uri="${MONGO_URL}" --db="${DB_NAME}" --collection=public_access_tokens --out=${BACKUP_DIR}/

# 2. SHA-256 de cada arquivo (proof-of-integrity)
( cd ${BACKUP_DIR} && find . -type f -exec sha256sum {} \; > MANIFEST.sha256 )

# 3. Tar+gzip
tar -czf ${BACKUP_DIR}.tar.gz -C /tmp $(basename ${BACKUP_DIR})

# 4. Upload S3 com Object Lock (Governance, retain 2557 days = 7 years)
aws s3 cp ${BACKUP_DIR}.tar.gz s3://smartprov-backups/iam_pre_migration/${TS}.tar.gz \
  --object-lock-mode GOVERNANCE \
  --object-lock-retain-until-date $(date -u -d "+7 years" +%Y-%m-%dT%H:%M:%SZ)

# 5. Verificar upload
aws s3 ls s3://smartprov-backups/iam_pre_migration/${TS}.tar.gz
```

**Estimativa de tempo:** 8–15 minutos (com ~20MB de dados IAM em co-demo).

### 2.2 — Cenário FALLBACK (não-enterprise, **NÃO RECOMENDADO**)

Se o bucket S3 ainda não estiver provisionado:

```bash
TS=$(date -u +%Y%m%d_%H%M%S)
BACKUP_DIR=/app/backups/iam_${TS}
mkdir -p ${BACKUP_DIR}

# Igual ao passo 2.1, mas sem upload S3
# Manifesto guarda hash + local
( cd ${BACKUP_DIR} && find . -type f -exec sha256sum {} \; > MANIFEST.sha256 )

# Cópia secundária pra disco diferente (mínimo redundância)
cp -r ${BACKUP_DIR} /var/iam_backup_${TS}
```

**⚠️ Marcado como NÃO ENTERPRISE.** Riscos:
- Backup vive no mesmo container (cofre+chave juntos).
- Sem Object Lock → operador com root pode deletar.
- Pode ser perdido em restart de container Kubernetes.

**Critério de uso:** apenas PREVIEW. PROD exige cenário 2.1.

---

## 3. Validação do backup

Antes de qualquer Phase ≥1, executar:

```bash
# Validate manifest
cd ${BACKUP_DIR}
sha256sum -c MANIFEST.sha256 || { echo "❌ MANIFEST CORROMPIDO"; exit 1; }

# Validate restore-readiness (dry restore numa DB temporária)
mongorestore \
  --uri="${MONGO_URL}" \
  --db="${DB_NAME}_validate_restore_${TS}" \
  --dir=${BACKUP_DIR}/${DB_NAME}/

# Validate counts batem
ORIGINAL_USERS=$(mongo --quiet "${MONGO_URL}" --eval "db.getSiblingDB('${DB_NAME}').users.countDocuments({})")
RESTORED_USERS=$(mongo --quiet "${MONGO_URL}" --eval "db.getSiblingDB('${DB_NAME}_validate_restore_${TS}').users.countDocuments({})")
[[ "$ORIGINAL_USERS" == "$RESTORED_USERS" ]] || { echo "❌ COUNT MISMATCH"; exit 1; }

# Drop DB temporária após validação
mongo "${MONGO_URL}" --eval "db.getSiblingDB('${DB_NAME}_validate_restore_${TS}').dropDatabase()"

echo "✅ Backup validado: $(stat -c %s ${BACKUP_DIR}.tar.gz) bytes"
```

---

## 4. Procedimento de Rollback

### 4.1 — Trigger
Rollback é **imediato** quando qualquer um destes acontecer:
- Login geral cai (taxa 5xx > 10% em 5min).
- Phase de migração falha no meio (exception levantada).
- Aparece `identity` órfã (sem `Membership` ativa) em mais de 5% do total.
- `Session.identity_id` aponta pra Identity inexistente.
- CTO/Founder digita "ROLLBACK NOW" no canal.

### 4.2 — Comando exato (5 minutos de SLA)

```bash
# Em SHELL do operador
set -e

# 1. Flip feature flag (efeito imediato, sem deploy)
kubectl set env deployment/smartprov-backend USE_NEW_IAM=0

# Ou via Emergent Segredos → editar USE_NEW_IAM=0 → Reimplantar

# 2. Drop das collections novas (NÃO destrutivo pro legado)
mongo "${MONGO_URL}" --eval '
  db = db.getSiblingDB("'${DB_NAME}'");
  ["identities", "credentials", "memberships", "sessions",
   "audit_authn", "audit_authz", "audit_identity",
   "audit_member", "audit_profile", "audit_creden"].forEach(c => {
      print("Dropping " + c + " ... " + db[c].drop());
   });
'

# 3. Limpa refs `_legacy_*` adicionadas pelo dual-write
mongo "${MONGO_URL}" --eval '
  db = db.getSiblingDB("'${DB_NAME}'");
  db.users.updateMany({}, {$unset: {_iam_v2_identity_id: ""}});
  db.collaborators.updateMany({}, {$unset: {_iam_v2_identity_id: ""}});
  db.access_profiles.updateMany({}, {$unset: {legacy_role_mapping: ""}});
'

# 4. Reset migration log
mongo "${MONGO_URL}" --eval '
  db = db.getSiblingDB("'${DB_NAME}'");
  db.iam_migration_log.updateMany(
    {phase: {$ne: "0"}},
    {$set: {rolled_back: true, rolled_back_at: new Date().toISOString()}}
  );
'

# 5. Smoke test login legado
curl -fsS -X POST "${BASE_URL}/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@empresa.com","password":"123456"}' > /dev/null \
  && echo "✅ Rollback OK — login legacy funcional"
```

### 4.3 — Restore COMPLETO (se rollback acima não bastou)

Cenário catastrófico: alguma phase escreveu lixo nas collections legadas (não deveria — escritas legadas são write-through; mas defensivo).

```bash
# 1. Pausar backend
sudo supervisorctl stop backend

# 2. Restore das collections que sofreram dual-write
mongorestore \
  --uri="${MONGO_URL}" \
  --db="${DB_NAME}" \
  --drop \
  --nsInclude="${DB_NAME}.users" \
  --nsInclude="${DB_NAME}.collaborators" \
  --nsInclude="${DB_NAME}.access_profiles" \
  --nsInclude="${DB_NAME}.user_magic_links" \
  --nsInclude="${DB_NAME}.*_portal_users" \
  --dir=${BACKUP_DIR}/

# 3. Validate counts
mongo "${MONGO_URL}" --eval 'print(db.getSiblingDB("'${DB_NAME}'").users.countDocuments({}))'

# 4. Restart backend (já com flag=0)
sudo supervisorctl start backend
```

**Estimativa de tempo:** 5–10 minutos de restore.

---

## 5. Critério de parada (kill switch)

Durante a migração, **PARAR IMEDIATAMENTE** se:

| Sinal | Limite | Ação |
|---|---|---|
| Login `/api/auth/login` 5xx | > 1% em 1min | rollback automático |
| `identity_id` sem `Membership` | > 5% das identities criadas | rollback automático |
| Duplicate `primary_email` | qualquer 1 ocorrência | abortar phase |
| `credentials.value_hash` vazio | qualquer 1 ocorrência | abortar phase |
| Phase demora > 10min (em co-demo) | timeout duro | abortar |
| User com último login < 5min consegue 401 inesperado | > 3 reports | rollback automático |

Implementação dos triggers: `iam_v2/migrate.py::_kill_switch_check()` (a criar em ETAPA 2.5).

---

## 6. Tempo estimado por operação

| Operação | Co-demo (12 users) | Tenant médio (100 users) | Tenant grande (1000 users) |
|---|---:|---:|---:|
| Backup | 2min | 5min | 15min |
| Validação backup | 1min | 2min | 5min |
| Phase 0 validate | <10s | <30s | <2min |
| Phase 1 identities | <10s | <30s | <3min |
| Phase 2 merge | <30s | <2min | <10min |
| Phase 3 credentials | <30s | <1min | <5min |
| Phase 4 memberships | <30s | <2min | <10min |
| Phase 5 portals | <10s | <30s | <3min |
| Phase 6 sessions | <5s | <5s | <5s |
| Phase 7 verify | <30s | <2min | <10min |
| **Total migração** | **~3min** | **~10min** | **~45min** |
| Rollback | 5min | 5min | 10min |

**Janela de manutenção recomendada PROD:** 60min (3x o tempo estimado pra colchão).

---

## 7. Riscos remanescentes

| # | Risco | Probabilidade | Mitigação |
|---|---|---|---|
| 1 | Backup S3 não disponível em PROD | **alta** | Provisionar bucket ANTES da ETAPA 2.5. Sem isso, freeze indefinido. |
| 2 | Dual-write race (legado escreve enquanto migração lê) | média | Janela de manutenção curta + locks em `iam_migration_log` |
| 3 | `magic_link` ativo no momento do cutover invalidando após | baixa | Pre-warn 24h: notificação banner "links serão renovados" |
| 4 | Portal user duplicar Identity por email igual | baixa | Phase 5 faz dedupe por `primary_email` antes de criar |
| 5 | Profile com permission key fora do catálogo | média | `iam_v2.permissions_catalog.sanitize()` filtra no startup |
| 6 | JWT legado de 30d ainda válido após cutover | **certo** | Shim aceita JWT antigo até expirar naturalmente |

---

## 8. Estado atual de readiness

| Pré-requisito | Status | Bloqueador? |
|---|---|---|
| Bucket S3 `smartprov-backups/` com Object Lock | ❌ **NÃO PROVISIONADO** | **SIM** |
| Acesso AWS IAM `mongodump→s3` configurado | ❌ não testado | sim |
| Dry-run das phases 1-7 implementado | ⏳ ETAPA 2.1 P2 em andamento | sim |
| Tabela de órfãos aprovada (P0) | ⏳ aguardando aprovação por linha | sim |
| Permission matrix aprovada (P3) | ⏳ a entregar | sim |
| Testes red-team passando (P4) | ⏳ a implementar | sim |
| Janela de manutenção marcada PROD | ❌ não agendada | sim |
| Operador on-call pra rollback (15min response) | ❌ não atribuído | sim |

**Score: 0/8** ✅. ETAPA 2.5 BLOQUEADA.
