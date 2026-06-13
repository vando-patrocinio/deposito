# IAM v2 — Roadmap de Execução

**Status:** ETAPA 2 entregue (modelagem). Aguardando autorização CTO/Founder para ETAPA 2.5+.

## Quadro de etapas

| # | Etapa | Status | Esforço | Risco |
|---|---|---|---:|---|
| 1 | Auditoria do estado atual | ✅ DONE 13/06/2026 | 1d | — |
| 2 | ADRs + Schemas + Scaffold | ✅ DONE 13/06/2026 | 1d | — |
| 2.5 | Migration phases 1–7 implementadas | 🔵 pending | 2–3d | médio |
| 3 | Reconstrução de Perfis (back + UI) | 🔵 pending | 2–3d | baixo |
| 4 | Reconstrução do Cadastro do Colaborador (6 abas) | 🔵 pending | 3–4d | baixo |
| 5 | Login refatorado (3 fluxos validados em cadeia) | 🔵 pending | 3d | **alto** |
| 6 | Mobile (persistência + refresh + logout remoto) | 🔵 pending | 2–3d | médio |
| 7 | Auditoria (4 coleções `audit_*` + S3 export) | 🔵 pending | 1–2d | baixo |
| 8 | Suíte de testes enterprise | 🔵 pending | 3d | médio |
| 9 | Rollout PROD faseado com feature flag | 🔵 pending | 5d | **alto** |

## Estado atual em PREVIEW (Phase 0 validate, 13/06/2026 09:55)

```json
{
  "company_id": "co-demo",
  "users_count": 12,
  "collaborators_count": 13,
  "profiles_count": 5,
  "orphan_collaborators": 6,           // 32%
  "users_without_profile": 7,           // 58%
  "duplicated_emails_across_portals": 2,
  "estimated_identities_to_create": 18,
  "ready_to_migrate": false            // precisa resolver órfãos antes
}
```

## O que está pronto pra usar imediatamente (ETAPA 2)

| Arquivo | Função |
|---|---|
| `/app/memory/AUDIT_IAM_2026_06_13.md` | Auditoria executiva completa |
| `/app/memory/adr/ADR-001_Identity_Model.md` | Schema canônico de Identity |
| `/app/memory/adr/ADR-002_Credential_Model.md` | Modelo de credenciais separado |
| `/app/memory/adr/ADR-003_Memberships_Permissions.md` | Permissões granulares |
| `/app/memory/adr/ADR-004_Sessions_Migration_Audit.md` | Sessions + migration + audit |
| `/app/backend/iam_v2/__init__.py` | Feature flag `USE_NEW_IAM` |
| `/app/backend/iam_v2/models.py` | Pydantic models (Identity, Credential, Membership, Session, AuditEvent) |
| `/app/backend/iam_v2/permissions_catalog.py` | Catálogo de ~80 permission keys + shim legacy_role |
| `/app/backend/iam_v2/authz.py` | `has_permission(user, key)` + `require_permission` dependency |
| `/app/backend/iam_v2/runtime.py` | Placeholder do `get_current_user` (ativa em ETAPA 5) |
| `/app/backend/iam_v2/migrate.py` | Script CLI de migração, Phase 0 rodando, Phases 1-7 esqueleto |

## Freeze ativo (13/06 → 13/07)

Durante este período eu **NÃO devo aplicar patches** em:
- `routes/clock.py` (PUT collaborator sync)
- `auth.py` (login flow)
- `rbac_policy.py` (regras)
- `access_profiles.py` (profile system)
- Qualquer `require_role(...)`, `require_roles(...)`, `user.role == ...` novo

Exceção única: **bug que impeça operação crítica de cliente em PROD** (financial outage, login total bloqueado pra todos). Nesse caso, hotfix curto + nota no PRD.

## Pré-requisitos antes da ETAPA 2.5

Quando o CTO/Founder autorizar:
1. Decidir como tratar os **6 órfãos** detectados (criar Identity nova OU vincular ao User existente pelo email).
2. Resolver os **7 users sem profile_id** (default = profile "Colaborador" do tenant).
3. Investigar os **2 emails duplicados em portais** (decidir merge ou separação).
4. Subir backup completo do MongoDB Atlas pra S3 com Object Lock.
5. Provisionar bucket S3 `smartprov-audit/` (decisão (e) — auditoria diária).

## Critérios de aceite por etapa

### ETAPA 2.5 (Migration phases 1–7)
- Phase 0 validate retorna `ready_to_migrate: true` em todos tenants
- Phases 1–6 idempotentes (rodar 2× não duplica)
- Phase 7 verify: paridade 100%, zero órfãos, unicidade garantida
- Rollback testado (USE_NEW_IAM=0 + drop das coleções v2)

### ETAPA 3 (Perfis)
- UI moderna com módulos colapsáveis, busca, badge contador de users
- CRUD com auditoria (log antes/depois em `audit_profile`)
- Não-deletáveis se vinculados a users

### ETAPA 4 (Cadastro do Colaborador)
- 6 abas: Pessoal · Acesso · Perfil · Permissões+ · Equipe · Auditoria
- Sync automático Identity↔Membership↔Credential
- Status workflow (`ativo`→`bloqueado`→`desligado`) com confirmação

### ETAPA 5 (Login)
- 3 fluxos (password / magic-link / google) validados em cadeia idêntica
- Device fingerprint capturado e validado em magic-link reuse
- Erro genérico em todos os modos de falha (não vaza qual etapa falhou)

### ETAPA 6 (Mobile)
- Refresh automático antes do expire (5min de margem)
- Logout remoto via `/auth/logout-all` revoga sessions de outros devices em <5s
- Sync de permissões a cada 15min OU em mudança detectada via SSE

### ETAPA 7 (Audit)
- 6 coleções `audit_*` com schema unificado
- Export S3 diário em JSONL.gz com Object Lock
- Dashboard básico de auditoria (timeline filtrada por actor/target/action)

### ETAPA 8 (Testes)
- 100% dos 12 cenários listados na ordem executiva passando
- Cobertura ≥85% em `iam_v2/`
- Stress: 1k logins concorrentes sem race em criação de Session

### ETAPA 9 (Rollout PROD)
- Feature flag por tenant (canary: co-demo → tenant pequeno → todos)
- Métricas: taxa de 401/403, latência login p99, erros de migration
- Rollback button (5min, reverte flag + restaura backup users/collabs)

## Documentos gerados

```
/app/memory/
  ├─ AUDIT_IAM_2026_06_13.md          ← auditoria completa
  ├─ IAM_V2_ROADMAP.md                ← este arquivo
  └─ adr/
      ├─ ADR-001_Identity_Model.md
      ├─ ADR-002_Credential_Model.md
      ├─ ADR-003_Memberships_Permissions.md
      └─ ADR-004_Sessions_Migration_Audit.md

/app/backend/iam_v2/
  ├─ __init__.py                       ← feature flag
  ├─ models.py                          ← Pydantic schemas
  ├─ permissions_catalog.py            ← catálogo + legacy shim
  ├─ authz.py                           ← has_permission + require_permission
  ├─ runtime.py                         ← placeholder ETAPA 5
  └─ migrate.py                         ← Phase 0 funcional, 1-7 stubs
```

Última atualização: 13/06/2026 09:55 UTC.
