"""iter206 — Auth recovery emergencial via master key.

Garante que o usuário dono NUNCA fique trancado fora do app:
1. Reseed forçado de `vando@ligotelecom.com` no startup do backend
2. Endpoint `POST /api/auth-recovery` que aceita master_key (= JWT_SECRET ou
   AUTH_RECOVERY_KEY do .env) + email + new_password
"""
from pathlib import Path


def test_seed_default_users_force_resets_owner():
    """Seed force-reseta a senha do owner em todo startup (idempotente)."""
    src = Path("/app/backend/auth.py").read_text()
    assert 'OWNER_EMAIL = "vando@ligotelecom.com"' in src
    assert 'OWNER_PASSWORD = os.environ.get("OWNER_PASSWORD")' in src
    # Lock cleanup
    assert "locked_until" in src
    assert "failed_attempts" in src
    # Limpa coleções de brute-force separadas
    assert "auth_failed_attempts" in src
    assert "auth_locks" in src


def test_auth_recovery_endpoint_registered():
    src = Path("/app/backend/routes/admin.py").read_text()
    assert '@router.post("/auth-recovery")' in src
    assert "AuthRecoveryPayload" in src
    assert "hmac.compare_digest" in src  # anti timing-attack
    assert "AUTH_RECOVERY_KEY" in src
    assert "JWT_SECRET" in src  # fallback


def test_payload_model_validates_minimums():
    """Master key e password têm mínimo de tamanho."""
    from pydantic import ValidationError
    import pytest
    from routes.admin import AuthRecoveryPayload

    # OK
    p = AuthRecoveryPayload(
        master_key="x" * 20, email="a@b.com",
        new_password="abc12345")
    assert p.master_key == "x" * 20

    # Master key curta
    with pytest.raises(ValidationError):
        AuthRecoveryPayload(master_key="abc", email="a@b.com",
                             new_password="abc12345")

    # Password curta
    with pytest.raises(ValidationError):
        AuthRecoveryPayload(master_key="x" * 20, email="a@b.com",
                             new_password="123")


def test_constant_time_eq_works():
    """Comparação em tempo constante (anti-timing-attack)."""
    from routes.admin import _constant_time_eq
    assert _constant_time_eq("abc123", "abc123") is True
    assert _constant_time_eq("abc123", "abc124") is False
    assert _constant_time_eq("", "") is True
    assert _constant_time_eq("abc", "abcd") is False
