"""iter205g — Migrate automation: config persistence + cron registration."""
from pathlib import Path


def test_migrate_config_uses_dedicated_collection():
    """Confirma que usa db.backup_config (não db.settings — para evitar
    o conflito do índice id_1 que já existe em settings)."""
    src = Path("/app/backend/routes/backup.py").read_text()
    assert "db.backup_config" in src
    assert "db.settings.find_one" not in src
    assert "db.settings.update_one" not in src


def test_weekly_migrate_job_is_registered_in_server():
    src = Path("/app/backend/server.py").read_text()
    assert "weekly_migrate_job" in src
    assert "mongo_weekly_migrate" in src
    assert 'day_of_week="sun"' in src
    assert "hour=4" in src


def test_migrate_config_model_defaults():
    from routes.backup import MigrateConfig
    cfg = MigrateConfig()
    assert cfg.enabled is False
    assert cfg.source_url == ""
    assert cfg.source_token == ""
    assert cfg.drop_existing is True


def test_migrate_config_with_explicit_values():
    from routes.backup import MigrateConfig
    cfg = MigrateConfig(
        enabled=True,
        source_url="https://x.emergent.host",
        source_token="abc" * 30,
        drop_existing=False,
    )
    assert cfg.enabled is True
    assert cfg.drop_existing is False
