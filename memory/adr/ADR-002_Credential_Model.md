# ADR-002 — Credentials (formas de autenticar separadas da identidade)

**Status:** Proposed
**Date:** 2026-06-13

## Context

Hoje, hash bcrypt fica em `users.password_hash`. Magic-links em `user_magic_links`. Google OAuth em `users.google_id`. Tokens públicos em `public_access_tokens`. **Cada portal tem seu próprio mecanismo.** Não há como dizer "essa pessoa pode logar com senha OU magic-link OU google".

## Decision

Coleção `credentials` separada — N credenciais por `Identity`.

## Schema

```python
class Credential(BaseDocument):
    id: PyObjectId                                # "cred-XXXX"
    identity_id: PyObjectId                        # FK → identities

    type: Literal["password", "magic_link", "google_oauth",
                  "api_key", "device_link", "sms_otp"]

    # Conteúdo específico por type (one-of, validado no service)
    # password: bcrypt hash
    # magic_link: token único + scope + expires_at
    # google_oauth: google_sub (id estável)
    # api_key: hash do token
    # device_link: device_fingerprint + nonce
    # sms_otp: hash do OTP de 6 dígitos
    value_hash: str                                # nunca o valor cru

    # Lifecycle
    created_at: datetime
    created_by: Optional[str]                       # identity_id quem emitiu
    expires_at: Optional[datetime]                  # None = não expira
    revoked_at: Optional[datetime]
    revoked_by: Optional[str]
    revoked_reason: Optional[str]
    last_used_at: Optional[datetime]
    use_count: int = 0

    # Device binding (decisão (d): magic-link com fingerprint)
    bound_device_fingerprint: Optional[str]         # SHA-256(ua + ip + accept-lang + screen)
    bound_device_label: Optional[str]               # "iPhone do Jefferson"

    # Scope (futuro: API keys com escopo limitado)
    scope: Optional[list[str]] = None
```

## Regras invariantes

1. **`identity_id` é FK forte.** Deletar Identity cascateia delete em todas as credentials.
2. **Múltiplas credenciais do mesmo `type` são permitidas** (ex: 2 senhas para rotação) mas apenas a mais recente sem `revoked_at` é ativa.
3. **Magic-link** (`type=magic_link`):
   - `expires_at` obrigatório (max 7 dias)
   - `bound_device_fingerprint` setado **na primeira utilização** (1 link = 1 device)
   - `use_count == 0` aceita; `use_count >= 1` exige fingerprint match
4. **Password** (`type=password`):
   - Bcrypt cost ≥12
   - Mínimo 6 chars (deprecated; aspirar a 8+)
   - Rotacionar sem perder histórico: cria nova, marca antiga `revoked_at=now`
5. **API key** (`type=api_key`):
   - `scope` obrigatório (lista de permission keys)
   - `expires_at` recomendado mas não obrigatório

## Indexes

```python
db.credentials.create_index([("identity_id", 1), ("type", 1)])
db.credentials.create_index([("type", 1), ("value_hash", 1)])  # busca de magic-link
db.credentials.create_index("expires_at", expireAfterSeconds=0, sparse=True)  # TTL auto-delete
```

## Login flow (novo, normalizado)

```python
async def login(email, secret, secret_type, device_fingerprint):
    # 1. Identity lookup
    identity = await find_identity_by_email(email)
    if not identity or identity.status != "ativo":
        raise AuthError("identity_unavailable")  # 401 genérico (segurança)

    # 2. Credential lookup
    cred = await find_active_credential(identity.id, type=secret_type)
    if not cred:
        raise AuthError("no_credential_of_type")

    # 3. Verify
    if not verify(secret, cred.value_hash):
        await record_failed_attempt(identity.id, secret_type)
        raise AuthError("invalid_secret")

    # 4. Device binding (magic_link only)
    if cred.type == "magic_link":
        if cred.use_count >= 1 and cred.bound_device_fingerprint != device_fingerprint:
            raise AuthError("device_mismatch")
        if cred.use_count == 0:
            await db.credentials.update_one(
                {"id": cred.id},
                {"$set": {"bound_device_fingerprint": device_fingerprint}},
            )

    # 5. Bump usage
    await db.credentials.update_one(
        {"id": cred.id},
        {"$set": {"last_used_at": now()}, "$inc": {"use_count": 1}},
    )

    # 6. Create session (ADR-004)
    session = await create_session(identity.id, device_fingerprint)
    audit_log("login.success", identity.id, {"cred_type": cred.type})
    return session
```

## Migration path

- `users.password_hash` → `credentials(identity_id=X, type="password", value_hash=H)`
- `user_magic_links` → `credentials(type="magic_link", ...)`
- `users.google_id` → `credentials(type="google_oauth", value_hash=google_sub)`
- `public_access_tokens` → ❌ **DEPRECATED**, será substituído por `credentials(type="api_key", scope=...)` com auditoria real
- Portal users (client/fleet/parcerias/security) → cada um vira Identity + Credential

## Decision Status

✅ Aprovado.
