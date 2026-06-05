"""iter205 — Testa lógica pura dos endpoints de backup (sem TestClient).

O TestClient quebra por um header não-ASCII (©) injetado por outro
middleware do app, então testamos diretamente:
- O regex SAFE_FILENAME
- A função _list_backups
- A registração do router

Validação de auth/HTTP foi feita via curl real contra o backend rodando
(ver iter205 PR description / commit eaf2e398).
"""
from pathlib import Path


def test_safe_filename_accepts_only_valid_dumps():
    from routes.backup import SAFE_FILENAME
    good = [
        "mongo-dump-20260601-233420.tar.gz",
        "mongo-dump-19990101-000000.tar.gz",
        "mongo-dump-20991231-235959.tar.gz",
    ]
    for n in good:
        assert SAFE_FILENAME.match(n), f"{n} deveria passar"


def test_safe_filename_rejects_dangerous_names():
    from routes.backup import SAFE_FILENAME
    bad = [
        "../../etc/passwd",
        "mongo-dump-abc.tar.gz",      # sem dígitos
        "mongo-dump-2026.tar.gz",     # formato curto
        "mongo-dump-20260601-235959.zip",  # extensão errada
        "mongo-dump-20260601_233420.tar.gz",  # underscore inválido
        "any-other-file.tar.gz",
        "",
        "mongo-dump-20260601-233420.tar.gz/../etc/passwd",
    ]
    for n in bad:
        assert not SAFE_FILENAME.match(n), f"{n} NÃO deveria passar"


def test_list_backups_returns_existing_files(tmp_path, monkeypatch):
    from routes import backup as backup_mod
    monkeypatch.setattr(backup_mod, "BACKUP_DIR", tmp_path)
    # cria 2 arquivos válidos + 1 inválido (deve ser ignorado)
    (tmp_path / "mongo-dump-20260101-000001.tar.gz").write_bytes(b"\x1f\x8b" + b"a" * 100)
    (tmp_path / "mongo-dump-20260601-120000.tar.gz").write_bytes(b"\x1f\x8b" + b"b" * 200)
    (tmp_path / "not-a-backup.txt").write_text("ignore me")

    items = backup_mod._list_backups()
    assert len(items) == 2, f"Esperava 2 backups, veio {len(items)}: {items}"
    # Ordem decrescente (mais recente primeiro)
    assert items[0]["filename"] == "mongo-dump-20260601-120000.tar.gz"
    assert items[1]["filename"] == "mongo-dump-20260101-000001.tar.gz"
    # size_human formato MB
    assert "MB" in items[0]["size_human"]


def test_list_backups_empty_dir(tmp_path, monkeypatch):
    from routes import backup as backup_mod
    monkeypatch.setattr(backup_mod, "BACKUP_DIR", tmp_path)
    assert backup_mod._list_backups() == []


def test_router_registered_in_server():
    """Garante que include_router(routes_backup.router) foi feito em server.py."""
    src = Path("/app/backend/server.py").read_text()
    assert "routes_backup" in src
    assert "app.include_router(routes_backup.router)" in src


def test_require_super_admin_blocks_non_super():
    from fastapi import HTTPException
    import pytest
    from routes.backup import _require_super_admin

    # is_super_admin checa via dict {is_super_admin: bool}
    with pytest.raises(HTTPException) as exc:
        _require_super_admin({"is_super_admin": False, "role": "gestor"})
    assert exc.value.status_code == 403

    # Permite super_admin
    _require_super_admin({"is_super_admin": True, "role": "admin"})


def test_backup_dir_created_on_import():
    """O diretório de backups é criado automaticamente."""
    from routes.backup import BACKUP_DIR
    assert BACKUP_DIR.exists()
    assert BACKUP_DIR.is_dir()
