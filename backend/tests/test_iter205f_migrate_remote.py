"""iter205f — Anti-SSRF do endpoint /migrate-from-remote.

A função `_is_safe_remote` é a barreira que impede um atacante de fazer
o servidor baixar de URLs maliciosas e restaurar dump arbitrário.
"""


def test_safe_remote_accepts_emergent_domains():
    from routes.backup import _is_safe_remote
    good = [
        "https://dual-combine-3.emergent.host",
        "https://dual-combine-3.preview.emergentagent.com",
        "https://abc.cluster-7.deploy.emergentcf.cloud",
        "https://meu-app.emergent.host/api",
        "https://meu-app.preview.emergentagent.com/api/admin/backup/list",
    ]
    for u in good:
        assert _is_safe_remote(u), f"{u} deveria ser aceito"


def test_safe_remote_rejects_other_domains():
    from routes.backup import _is_safe_remote
    bad = [
        "https://evil.com",
        "https://emergent.host.evil.com",         # subdomain spoofing
        "https://emergent.host",                   # bare domain, sem subdomínio
        "https://attacker.org/api",
        "https://localhost:8001",
        "https://127.0.0.1",
        "https://169.254.169.254",                 # AWS metadata
        "https://emergent.host.attacker.io",
        "ftp://emergent.host",                     # scheme errado
        "file:///etc/passwd",
        "",
        "not-a-url",
        "https://emergentagent.com.evil.io",
    ]
    for u in bad:
        assert not _is_safe_remote(u), f"{u} deveria ser BLOQUEADO"


def test_migrate_payload_model_validation():
    """O modelo Pydantic rejeita campos faltantes."""
    from pydantic import ValidationError
    import pytest
    from routes.backup import MigratePayload

    # OK
    p = MigratePayload(
        source_url="https://x.emergent.host",
        source_token="abc123" * 10,  # 60 chars
        drop_existing=True,
    )
    assert p.drop_existing is True

    # drop_existing default = False
    p2 = MigratePayload(source_url="https://x.emergent.host",
                        source_token="abc123" * 10)
    assert p2.drop_existing is False

    # Faltando obrigatórios
    with pytest.raises(ValidationError):
        MigratePayload(source_url="https://x.emergent.host")
    with pytest.raises(ValidationError):
        MigratePayload(source_token="abc" * 30)
