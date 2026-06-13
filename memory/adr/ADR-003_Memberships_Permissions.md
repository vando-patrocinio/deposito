# ADR-003 — Memberships + Permissões Granulares

**Status:** Proposed
**Date:** 2026-06-13

## Context

Hoje, `users.role` é string ("gestor", "tecnico", etc.) e 937 `require_role()` espalhados pelo código. Profiles novos (`prof-XXXX`) são invisíveis pro RBAC. Sem permissões granulares — só "módulos" inteiros.

Decisões executivas:
- **(b)** Hierarquia `module.action` (ex: `tickets.close`)
- **(c)** Identity única → membership decide papel **por empresa**

## Decision

### Coleção `memberships`

```python
class Membership(BaseDocument):
    id: PyObjectId                                # "mem-XXXX"
    identity_id: PyObjectId                        # FK
    company_id: str                                # tenant
    profile_id: PyObjectId                         # FK → access_profiles

    # Override granular por usuário (ALÉM do profile)
    # Tipo: [{permission: "tickets.delete", effect: "allow"|"deny"}]
    permission_overrides: list[PermissionOverride] = []

    # Status DA pessoa NESSA empresa
    status: Literal["active", "suspended", "terminated"]
    suspended_until: Optional[datetime]
    suspended_reason: Optional[str]
    terminated_at: Optional[datetime]
    terminated_reason: Optional[str]

    # Hierarquia opcional (gestor → subordinados)
    supervisor_membership_id: Optional[PyObjectId]
    cost_center_id: Optional[str]                  # contabilidade

    # Vínculo trabalhista (puxa dados de collaborator legacy)
    employment_data: Optional[EmploymentData]      # cargo, schedule, cpf cadastrado nessa empresa

    # Auditoria
    created_at: datetime
    created_by: Optional[str]
    updated_at: datetime
```

### Coleção `access_profiles` (renovada)

```python
class AccessProfile(BaseDocument):
    id: PyObjectId                                # "prof-XXXX"
    company_id: str
    name: str                                       # "Gestor Comercial"
    description: Optional[str]
    color: str = "#3b82f6"                          # UI hint
    icon: Optional[str]

    # Lista granular de permissões (módulo.ação)
    permissions: list[str]                          # ["tickets.view", "tickets.close", ...]

    is_seed: bool = False                            # perfis seed não podem ser deletados
    is_admin_level: bool = False                     # marca "pode editar permissões"
    legacy_role_mapping: Optional[str]               # shim p/ require_role legado (ADR-004)

    created_at: datetime
    updated_at: datetime
    user_count_cache: int = 0
```

### Permission keys (catálogo formal)

Arquivo: `/app/backend/iam_v2/permissions_catalog.py`

Convenção: `<module>.<action>[.<scope>]`

| Módulo | Actions disponíveis |
|---|---|
| `tickets` | view, create, edit, close, reopen, delete, assign, bulk_edit |
| `clients` | view, create, edit, suspend, reactivate, delete, view_blocked, view_overdue, view_pii |
| `estoque` | view, adjust, transfer, audit, low_stock_alerts |
| `financeiro` | view.aging, view.dre, view.daily, charge.dispatch, refund, payment.confirm, payment.reverse |
| `colaboradores` | view, create, edit, deactivate, terminate, assign_profile, view_face_data, view_clock_records |
| `lousa` | view, finalize, reopen, override_geofence, override_photo |
| `dashboard` | executive, operational, financial, technical |
| `frota` | view, edit_vehicle, assign_driver, view_tracking, view_costs |
| `whatsapp` | send, view_conversations, manage_channels, manage_campaigns, mass_dispatch |
| `system` | manage_users, manage_profiles, manage_integrations, view_logs, manage_secrets, kill_switch |
| `audit` | view_all, export, restore_deleted |

**Lista completa em `permissions_catalog.py`** (~80–100 keys iniciais).

### Authorization function (substitui require_role)

```python
def has_permission(
    user: AuthedUser,
    permission: str,           # "tickets.close"
    company_id: Optional[str] = None,
) -> bool:
    """Única função autorizadora. Substitui require_role/require_tag/is_super_admin."""
    membership = user.active_membership  # já populado no login
    if company_id and membership.company_id != company_id:
        return False
    if membership.status != "active":
        return False

    # 1. Permission overrides explícitos (precedência máxima)
    for ovr in membership.permission_overrides:
        if ovr.permission == permission:
            return ovr.effect == "allow"

    # 2. Profile permissions
    profile = user.profile  # já populado
    if permission in profile.permissions:
        return True

    # 3. Wildcards: "tickets.*" libera tudo de tickets
    module = permission.split(".")[0]
    if f"{module}.*" in profile.permissions:
        return True
    if "*" in profile.permissions:  # super admin
        return True

    return False


# FastAPI dependency
def require_permission(*permissions: str):
    async def _dep(user: AuthedUser = Depends(get_current_user)) -> AuthedUser:
        if not any(has_permission(user, p) for p in permissions):
            raise HTTPException(403, {
                "code": "missing_permission",
                "required": list(permissions),
                "user_permissions_count": len(user.profile.permissions),
            })
        return user
    return _dep
```

## Indexes

```python
db.memberships.create_index([("identity_id", 1), ("company_id", 1)], unique=True)
db.memberships.create_index([("company_id", 1), ("status", 1)])
db.memberships.create_index("profile_id")
db.access_profiles.create_index([("company_id", 1), ("name", 1)], unique=True)
```

## Compat shim com `require_role` legado

Para os 937 callers existentes não quebrarem:

```python
# /app/backend/auth_compat.py
LEGACY_ROLE_TO_PERMISSIONS = {
    "administrador": ["*"],  # tudo
    "auditor":       ["*"],  # tudo (leitura por convenção, mas tem todas as keys)
    "gestor":        ["tickets.*", "clients.*", "estoque.*", ...],
    "atendimento":   ["tickets.view", "tickets.create", "clients.view", ...],
    "tecnico":       ["lousa.*", "tickets.view", "tickets.close", ...],
    "financeiro":    ["financeiro.*", "clients.view"],
    "colaborador":   ["lousa.view", "lousa.finalize"],
}

def require_role(*roles: str):
    """SHIM — converte require_role legado em require_permission.

    Calcula a intersecção das permissions de todos os roles aceitos.
    Marca a chamada com warning pra migração futura.
    """
    async def _dep(user: AuthedUser = Depends(get_current_user)):
        if has_any_role_permission(user, roles):
            return user
        raise HTTPException(403, {"code": "missing_role", "required": list(roles)})
    return _dep
```

**Vence shim em 30 dias.** Depois disso, `require_role` lança `DeprecationWarning` ruidoso e force-migration.

## Decision Status

✅ Aprovado.
