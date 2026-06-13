# ADR-004 — Sessions, Migration Strategy & Audit

**Status:** Proposed
**Date:** 2026-06-13

## Part 1 — Sessions

### Context

Hoje JWT vive 30 dias, sem revogação real (logout client-side). Não é possível "encerrar sessões em outros dispositivos".

### Decision

Coleção `sessions` rastreando cada login efetivo.

```python
class Session(BaseDocument):
    id: PyObjectId                                # "ses-XXXX"
    identity_id: PyObjectId                        # FK
    membership_id: PyObjectId                      # qual papel está ativo
    company_id: str                                # cache da membership

    # JWT binding
    jwt_jti: str                                    # unique ID do token (claim "jti")
    issued_at: datetime
    expires_at: datetime                            # 30d default
    revoked_at: Optional[datetime]
    revoked_by: Optional[str]
    revoked_reason: Optional[str]

    # Device
    device_fingerprint: str                         # SHA-256(ua + ip + accept-lang + screen)
    device_label: Optional[str]                     # "Chrome / macOS"
    ip_first: str
    ip_last: str
    user_agent: str

    # Last seen
    last_seen_at: datetime
    last_action: Optional[str]                      # "GET /api/tickets"
    action_count: int = 0

    # Impersonation (admin assumindo identity de outro)
    impersonator_identity_id: Optional[str]
```

### Authorization check (per request)

```python
async def authorize_request(jwt_payload: dict) -> AuthedUser:
    jti = jwt_payload["jti"]
    session = await db.sessions.find_one({"jwt_jti": jti, "revoked_at": None})
    if not session:
        raise AuthError("session_revoked")
    if session.expires_at < now():
        raise AuthError("session_expired")

    # Atualiza last_seen async (fire-and-forget)
    db.sessions.update_one(
        {"id": session.id},
        {"$set": {"last_seen_at": now(), "ip_last": request.ip},
         "$inc": {"action_count": 1}},
    )

    identity = await db.identities.find_one({"id": session.identity_id})
    if identity.status != "ativo":
        raise AuthError("identity_disabled")

    membership = await db.memberships.find_one({"id": session.membership_id})
    if membership.status != "active":
        raise AuthError("membership_inactive")

    return AuthedUser(identity, membership, session, ...)
```

### Logout real

```python
@router.post("/auth/logout")
async def logout(user: AuthedUser = Depends(get_current_user)):
    await db.sessions.update_one(
        {"id": user.session.id},
        {"$set": {"revoked_at": now(), "revoked_reason": "user_logout"}},
    )
    return {"ok": True}


@router.post("/auth/logout-all")
async def logout_all_devices(user: AuthedUser = Depends(get_current_user)):
    """Encerra TODAS as sessões dessa Identity."""
    r = await db.sessions.update_many(
        {"identity_id": user.identity.id, "revoked_at": None},
        {"$set": {"revoked_at": now(), "revoked_reason": "logout_all"}},
    )
    return {"revoked_count": r.modified_count}
```

---

## Part 2 — Migration Strategy

### Feature flag

```python
# /app/backend/.env
USE_NEW_IAM=0   # 0 = sistema legado / 1 = IAM v2

# /app/backend/iam_v2/__init__.py
import os
NEW_IAM_ENABLED = os.environ.get("USE_NEW_IAM", "0") == "1"
```

### Coexistência (30 dias)

Durante o shim, o backend **lê e escreve nas duas estruturas simultaneamente** para garantir rollback instantâneo:

```python
async def update_user_legacy(user_id, fields):
    if NEW_IAM_ENABLED:
        # Caminho novo
        await update_identity(user_id, fields)
    else:
        # Caminho legado (atual)
        await db.users.update_one({"id": user_id}, {"$set": fields})

    # SEMPRE espelha pro outro lado (dual-write durante migration)
    if NEW_IAM_ENABLED:
        await db.users.update_one({"id": user_id}, {"$set": legacy_format(fields)})
    else:
        await db.identities.update_one(...)
```

### Migration script

Arquivo: `/app/backend/iam_v2/migrate.py` (criado no scaffold, **NÃO EXECUTADO** automaticamente).

Fases:

1. **Backup completo** (`mongodump` + S3 export) — feito MANUALMENTE pelo CTO antes.
2. **Phase 1: criar Identities** a partir de `users` (1:1).
3. **Phase 2: merge Collaborators** em Identities (por CPF/email).
4. **Phase 3: criar Credentials** (password do users.password_hash, magic_links de user_magic_links).
5. **Phase 4: criar Memberships** (1 por user.company_id, profile_id derivado de users.role + users.profile_id).
6. **Phase 5: migrate portal users** (client/fleet/parcerias/security) — cada um vira Identity (sem colab data).
7. **Phase 6: criar Sessions** vazias (os JWTs existentes continuam válidos via shim até expirarem em 30 dias).
8. **Phase 7: verify** — script de validação que conta paridade, detecta órfãos, valida unicidade.

**Rollback:** flag pra 0. Coleções novas ficam paradas, sistema volta a usar legacy.

### Cutover

Quando `USE_NEW_IAM=1` ficar estável por 7 dias em PROD:
- Marcar `users` como **frozen** (read-only via Mongo role).
- Remover `auth_compat.LEGACY_ROLE_TO_PERMISSIONS`.
- Forçar todos os endpoints a usar `require_permission(...)`.
- Deletar `users`, `collaborators` legacy (mantém em backup S3).

---

## Part 3 — Audit (append-only)

### Coleções

```python
audit_authn    # login.success, login.fail, logout, session.revoked, mfa.challenge
audit_authz    # permission.granted, permission.denied (sample 1%)
audit_identity # identity.created, identity.email_changed, identity.status_changed
audit_member   # membership.created, membership.profile_changed, membership.terminated
audit_profile  # profile.created, profile.permission_added, profile.permission_removed, profile.deleted
audit_creden   # credential.issued, credential.revoked, credential.rotated, magic_link.used
```

### Schema unificado

```python
class AuditEvent(BaseDocument):
    id: PyObjectId
    at: datetime                                    # indexed desc
    actor_identity_id: Optional[str]                # quem executou (None = sistema)
    actor_session_id: Optional[str]
    actor_ip: Optional[str]
    actor_ua: Optional[str]

    target_identity_id: Optional[str]               # alvo (pode ser o próprio actor)
    target_type: str                                # "identity", "membership", "profile", "credential", "session"
    target_id: str

    action: str                                     # "login.success", "membership.profile_changed", etc.
    before: Optional[dict]                          # diff antes
    after: Optional[dict]                           # diff depois
    metadata: Optional[dict]                        # ip, ua, reason, etc.

    severity: Literal["info", "warn", "alert", "critical"]
```

### Indexes (TTL 365 dias para auth, infinito para identity/member/profile)

```python
db.audit_authn.create_index("at", expireAfterSeconds=365*86400)
db.audit_authz.create_index("at", expireAfterSeconds=90*86400)  # alto volume
db.audit_identity.create_index("at")  # sem TTL
db.audit_member.create_index("at")    # sem TTL
db.audit_profile.create_index("at")   # sem TTL
db.audit_creden.create_index("at", expireAfterSeconds=365*86400)
```

### Export diário para S3

Cron 03:00 UTC:
1. Export `audit_*` do dia anterior em JSONL.gz.
2. Upload pra S3 `s3://smartprov-audit/YYYY/MM/DD/audit_*.jsonl.gz`.
3. Object Lock (Governance, 7 anos) — imutável.
4. Notifica Slack com link + checksum.

### Decision Status

✅ Aprovado (decisão `e`: MongoDB + S3 daily export).
