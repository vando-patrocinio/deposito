# ADR-001 — Identity Model (canônico, unificado)

**Status:** Proposed (aguardando aprovação)
**Date:** 2026-06-13
**Author:** CTO

## Context

Hoje existem 7 coleções com "usuários": `users`, `collaborators`, `client_portal_users`, `fleet_portal_users`, `parcerias_partner_users`, `security_portal_users`, `collaborators.mobile_access_email`. **Mesma pessoa pode existir em 4+ lugares com schemas diferentes.**

Decisão executiva (13/06/2026): **unificar tudo numa única entidade `Identity`**.

## Decision

Criar coleção canônica `identities` que representa **uma pessoa única no ecossistema**, independente de:
- empresa (multi-tenant via `Membership`)
- forma de autenticar (via `Credential`)
- papel funcional (via `Membership.profile_id`)

## Schema

```python
class Identity(BaseDocument):
    id: PyObjectId                            # "idt-XXXXXXXXXX"
    full_name: str
    cpf: Optional[str]                         # único globalmente (sparse index)
    primary_email: EmailStr                    # único globalmente
    primary_phone: Optional[str]
    avatar_url: Optional[str]
    status: Literal["ativo", "bloqueado", "desligado", "aguardando_ativacao"]

    # Contatos secundários (emails extras, telefones extras)
    contacts: list[Contact]                    # max 5

    # Multi-tenant: pessoa pode pertencer a N empresas
    # Cada membership tem seu próprio profile/permissões
    # Memberships ficam em coleção separada (`memberships`)
    # — esse campo aqui é só o cache do count.
    membership_count: int = 0

    # Auditoria mínima
    created_at: datetime
    updated_at: datetime
    last_login_at: Optional[datetime]
    created_by: Optional[str]                  # identity_id de quem criou

class Contact(BaseModel):
    type: Literal["email", "phone", "whatsapp"]
    value: str                                 # sempre normalizado (lowercase, e164)
    verified: bool = False
    verified_at: Optional[datetime]
    label: Optional[str]                       # "trabalho", "pessoal", etc.
```

## Status enum — RAZÃO DE EXISTIR

| status | Significado | Pode logar? |
|---|---|---|
| `ativo` | conta operacional | ✅ |
| `bloqueado` | gestor desativou temporariamente (justificativa obrigatória) | ❌ |
| `desligado` | terminou vínculo com TODAS as empresas | ❌ |
| `aguardando_ativacao` | foi criada mas ainda não confirmou contato (magic-link) | ❌ até verificar |

**Sem outros estados.** Removido: `users.active`, `users.locked_until`, `collaborators.active`, `collaborators.deactivated_at`. **4 → 1.**

## Indexes

```python
db.identities.create_index("id", unique=True)
db.identities.create_index("primary_email", unique=True)
db.identities.create_index("cpf", unique=True, sparse=True)
db.identities.create_index([("status", 1), ("updated_at", -1)])
```

## Garantias

- 1 pessoa = 1 `Identity`. **Hard constraint** via unique index em `primary_email` e `cpf`.
- Mudar email não duplica Identity — só atualiza `primary_email` (com auditoria).
- `cpf` é sparse pois Identity pode ser cliente sem CPF cadastrado.

## Migration path

Veja `MIGRATION_001_users_to_identity.md`.

## Decision Status

✅ Aprovado pelo CTO/Founder (13/06/2026).
