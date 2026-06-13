"""IAM v2 — Pydantic models (canônicos).

⚠️  Schemas declarativos. Nada é persistido ainda — a migração (ETAPA 2.5)
vai popular as collections a partir do legado.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


# ──────────────────────────────────────────────────────────────────────────
# Common
# ──────────────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


IdentityStatus = Literal["ativo", "bloqueado", "desligado", "aguardando_ativacao"]
MembershipStatus = Literal["active", "suspended", "terminated"]
ContactType = Literal["email", "phone", "whatsapp"]
CredentialType = Literal[
    "password", "magic_link", "google_oauth",
    "api_key", "device_link", "sms_otp",
]


# ──────────────────────────────────────────────────────────────────────────
# Identity (ADR-001)
# ──────────────────────────────────────────────────────────────────────────

class Contact(BaseModel):
    type: ContactType
    value: str
    verified: bool = False
    verified_at: Optional[datetime] = None
    label: Optional[str] = None

    @field_validator("value")
    @classmethod
    def _normalize(cls, v: str, info) -> str:  # noqa: ARG002
        return (v or "").strip().lower()


class Identity(BaseModel):
    id: str = Field(..., description="idt-XXXXXXXXXX")
    full_name: str
    cpf: Optional[str] = None
    primary_email: EmailStr
    primary_phone: Optional[str] = None
    avatar_url: Optional[str] = None
    status: IdentityStatus = "aguardando_ativacao"

    contacts: list[Contact] = Field(default_factory=list, max_length=5)
    membership_count: int = 0

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    last_login_at: Optional[datetime] = None
    created_by: Optional[str] = None  # identity_id

    @field_validator("cpf")
    @classmethod
    def _normalize_cpf(cls, v):
        if not v:
            return None
        digits = "".join(c for c in v if c.isdigit())
        return digits if len(digits) == 11 else None

    @field_validator("primary_phone")
    @classmethod
    def _normalize_phone(cls, v):
        if not v:
            return None
        digits = "".join(c for c in v if c.isdigit())
        return f"+{digits}" if digits else None


# ──────────────────────────────────────────────────────────────────────────
# Credential (ADR-002)
# ──────────────────────────────────────────────────────────────────────────

class Credential(BaseModel):
    id: str = Field(..., description="cred-XXXXXXXX")
    identity_id: str
    type: CredentialType
    value_hash: str

    created_at: datetime = Field(default_factory=_now)
    created_by: Optional[str] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[str] = None
    revoked_reason: Optional[str] = None
    last_used_at: Optional[datetime] = None
    use_count: int = 0

    bound_device_fingerprint: Optional[str] = None
    bound_device_label: Optional[str] = None

    scope: Optional[list[str]] = None

    def is_active(self) -> bool:
        if self.revoked_at:
            return False
        if self.expires_at and self.expires_at < _now():
            return False
        return True


# ──────────────────────────────────────────────────────────────────────────
# Access Profile (ADR-003)
# ──────────────────────────────────────────────────────────────────────────

class AccessProfile(BaseModel):
    id: str = Field(..., description="prof-XXXXXXXX")
    company_id: str
    name: str
    description: Optional[str] = None
    color: str = "#3b82f6"
    icon: Optional[str] = None

    permissions: list[str] = Field(default_factory=list)

    is_seed: bool = False
    is_admin_level: bool = False
    legacy_role_mapping: Optional[str] = None  # shim p/ require_role legado

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    user_count_cache: int = 0


# ──────────────────────────────────────────────────────────────────────────
# Membership (ADR-003)
# ──────────────────────────────────────────────────────────────────────────

class PermissionOverride(BaseModel):
    permission: str  # "tickets.delete"
    effect: Literal["allow", "deny"]
    reason: Optional[str] = None
    granted_by: Optional[str] = None
    granted_at: datetime = Field(default_factory=_now)


class EmploymentData(BaseModel):
    """Dados trabalhistas — antes em `collaborators`."""
    cargo: Optional[str] = None  # tecnico, atendente, gestor, ...
    role_label: Optional[str] = None  # "Técnico (Atlaz)" — descritivo livre
    schedule: Optional[dict[str, str]] = None  # {entrada:..., saida:...}
    clock_in_enabled: bool = True
    can_attend_whatsapp: bool = False
    matricula: Optional[str] = None
    cost_center: Optional[str] = None
    overtime_policy: Optional[dict[str, Any]] = None


class Membership(BaseModel):
    id: str = Field(..., description="mem-XXXXXXXX")
    identity_id: str
    company_id: str
    profile_id: str

    permission_overrides: list[PermissionOverride] = Field(default_factory=list)

    status: MembershipStatus = "active"
    suspended_until: Optional[datetime] = None
    suspended_reason: Optional[str] = None
    terminated_at: Optional[datetime] = None
    terminated_reason: Optional[str] = None

    supervisor_membership_id: Optional[str] = None
    cost_center_id: Optional[str] = None

    employment_data: Optional[EmploymentData] = None

    created_at: datetime = Field(default_factory=_now)
    created_by: Optional[str] = None
    updated_at: datetime = Field(default_factory=_now)


# ──────────────────────────────────────────────────────────────────────────
# Session (ADR-004)
# ──────────────────────────────────────────────────────────────────────────

class Session(BaseModel):
    id: str = Field(..., description="ses-XXXXXXXX")
    identity_id: str
    membership_id: str
    company_id: str

    jwt_jti: str
    issued_at: datetime = Field(default_factory=_now)
    expires_at: datetime
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[str] = None
    revoked_reason: Optional[str] = None

    device_fingerprint: str
    device_label: Optional[str] = None
    ip_first: str
    ip_last: str
    user_agent: str

    last_seen_at: datetime = Field(default_factory=_now)
    last_action: Optional[str] = None
    action_count: int = 0

    impersonator_identity_id: Optional[str] = None

    def is_valid(self) -> bool:
        if self.revoked_at:
            return False
        if self.expires_at < _now():
            return False
        return True


# ──────────────────────────────────────────────────────────────────────────
# Audit (ADR-004 part 3)
# ──────────────────────────────────────────────────────────────────────────

AuditSeverity = Literal["info", "warn", "alert", "critical"]


class AuditEvent(BaseModel):
    id: str
    at: datetime = Field(default_factory=_now)

    actor_identity_id: Optional[str] = None
    actor_session_id: Optional[str] = None
    actor_ip: Optional[str] = None
    actor_ua: Optional[str] = None

    target_identity_id: Optional[str] = None
    target_type: str  # "identity"|"membership"|"profile"|"credential"|"session"
    target_id: str

    action: str  # "login.success", "membership.profile_changed", ...
    before: Optional[dict[str, Any]] = None
    after: Optional[dict[str, Any]] = None
    metadata: Optional[dict[str, Any]] = None

    severity: AuditSeverity = "info"


# ──────────────────────────────────────────────────────────────────────────
# Composed: AuthedUser (request context)
# ──────────────────────────────────────────────────────────────────────────

class AuthedUser(BaseModel):
    """Objeto injetado pelo middleware após autorizar a request.

    Substitui o `dict` legado que circula por toda a base. Sempre tem
    identity + active_membership + active_session + profile carregados
    (1 round-trip no Mongo no login, depois cache em memória da request).
    """
    identity: Identity
    membership: Membership
    session: Session
    profile: AccessProfile

    # Conveniência: views legadas precisam de role/role_label
    @property
    def legacy_role(self) -> str:
        return self.profile.legacy_role_mapping or "colaborador"

    @property
    def is_super_admin(self) -> bool:
        return "*" in self.profile.permissions
