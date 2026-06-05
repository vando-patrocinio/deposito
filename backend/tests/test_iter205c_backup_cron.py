"""iter205c — Testa o cron de backup automático com rotação."""
from datetime import datetime, timedelta


def test_rotate_keeps_last_n(tmp_path, monkeypatch):
    """Rotation apaga só os arquivos mais antigos, preserva últimos N."""
    from routes import backup as backup_mod
    monkeypatch.setattr(backup_mod, "BACKUP_DIR", tmp_path)

    # Cria 10 backups com mtimes em sequência (mais novo = maior mtime)
    base = datetime.now().timestamp()
    files = []
    for i in range(10):
        name = f"mongo-dump-2026010{i % 10}-{i:02d}0000.tar.gz"
        # nomes válidos: AAAAMMDD-HHMMSS, vamos usar timestamps reais
        ts = (datetime(2026, 1, 1) + timedelta(days=i)).strftime("%Y%m%d-%H%M%S")
        name = f"mongo-dump-{ts}.tar.gz"
        p = tmp_path / name
        p.write_bytes(b"\x1f\x8b" + b"x" * 100)
        # ajusta mtime crescente (mais recente = maior)
        import os
        mt = base + i
        os.utime(p, (mt, mt))
        files.append(p)

    # Roda rotation mantendo 7
    removed = backup_mod._rotate_backups(keep=7)
    assert len(removed) == 3, f"esperava 3 removidos, veio {len(removed)}"

    remaining = sorted(tmp_path.glob("mongo-dump-*.tar.gz"))
    assert len(remaining) == 7

    # Os 3 mais antigos (índices 0, 1, 2) devem ter sumido
    for i in range(3):
        assert not files[i].exists(), f"{files[i].name} deveria ter sumido"
    # Os 7 mais novos (3..9) devem continuar
    for i in range(3, 10):
        assert files[i].exists(), f"{files[i].name} deveria persistir"


def test_rotate_noop_when_fewer_than_keep(tmp_path, monkeypatch):
    """Com menos de 7 backups, rotation não apaga nada."""
    from routes import backup as backup_mod
    monkeypatch.setattr(backup_mod, "BACKUP_DIR", tmp_path)
    for i in range(3):
        ts = (datetime(2026, 1, 1) + timedelta(days=i)).strftime("%Y%m%d-%H%M%S")
        (tmp_path / f"mongo-dump-{ts}.tar.gz").write_bytes(b"\x1f\x8b")

    removed = backup_mod._rotate_backups(keep=7)
    assert removed == []
    assert len(list(tmp_path.glob("mongo-dump-*.tar.gz"))) == 3


def test_rotate_ignores_non_backup_files(tmp_path, monkeypatch):
    """Arquivos que não casam com glob mongo-dump-*.tar.gz são ignorados."""
    from routes import backup as backup_mod
    monkeypatch.setattr(backup_mod, "BACKUP_DIR", tmp_path)
    # 8 backups válidos + 4 outros arquivos não-glob
    for i in range(8):
        ts = (datetime(2026, 1, 1) + timedelta(days=i)).strftime("%Y%m%d-%H%M%S")
        (tmp_path / f"mongo-dump-{ts}.tar.gz").write_bytes(b"\x1f\x8b")
    for name in ["random.txt", "logs.log", "data.json", "test.tar.gz"]:
        (tmp_path / name).write_text("ignore")

    # Apaga 1 (deixa 7)
    removed = backup_mod._rotate_backups(keep=7)
    assert len(removed) == 1
    # Arquivos não-backup continuam
    for name in ["random.txt", "logs.log", "data.json", "test.tar.gz"]:
        assert (tmp_path / name).exists()


def test_daily_backup_job_is_async_and_registered():
    """O job é coroutine e está registado no scheduler do server."""
    import inspect
    from pathlib import Path
    from routes.backup import daily_backup_job, KEEP_LAST_N
    assert inspect.iscoroutinefunction(daily_backup_job)
    assert KEEP_LAST_N == 7

    src = Path("/app/backend/server.py").read_text()
    assert "daily_backup_job" in src
    assert "mongo_daily_backup" in src
    # Confirma cron 03:00
    assert 'CronTrigger(hour=3, minute=0)' in src or \
           'CronTrigger(hour=3,minute=0)' in src
