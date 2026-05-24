"""Tests iter139 — Drive Backup robustness + Provisionamento 1-clique.

Cobertura:
- Detecção de invalid_grant e flag needs_reconnect
- Endpoint /api/drive/restore-upload aceita arquivo JSON
- Validação de payload inválido (não-JSON, MB demais, empresa diferente)
"""
import io
import json
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL",
                          "http://localhost:8001").rstrip("/")
COMPANY_ID = "co-demo"


@pytest.fixture(scope="session")
def db():
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    return MongoClient(mongo_url)[db_name]


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "admin@empresa.com",
                            "password": "123456"}, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# ======================================================================
# Status retorna needs_reconnect quando token foi marcado como revogado
# ======================================================================
def test_status_includes_needs_reconnect_field(admin_token):
    r = requests.get(f"{BASE_URL}/api/drive/status",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert "connected" in data
    if data["connected"]:
        assert "needs_reconnect" in data
        assert isinstance(data["needs_reconnect"], bool)


def test_backup_endpoint_returns_401_when_token_revoked(admin_token, db):
    """Marca manualmente token_revoked=True e verifica que o endpoint retorna 401."""
    # Garante registro do co-demo
    db.drive_credentials.update_one(
        {"company_id": COMPANY_ID},
        {"$set": {"token_revoked": True}},
        upsert=False,  # NÃO cria se não existir
    )
    r = requests.post(f"{BASE_URL}/api/drive/backup",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      json={"include_secrets": False}, timeout=15)
    # 401 se realmente está marcado revogado, ou 400 se a empresa não tem doc
    assert r.status_code in (400, 401)
    if r.status_code == 401:
        assert "reconect" in r.text.lower() or "token" in r.text.lower()


# ======================================================================
# Provisionamento 1-clique — restore-upload
# ======================================================================
def test_restore_upload_rejects_non_json(admin_token):
    files = {"file": ("malicious.exe", b"\x00\x01\x02PE\x00", "application/octet-stream")}
    r = requests.post(f"{BASE_URL}/api/drive/restore-upload",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      files=files, data={"mode": "merge"}, timeout=20)
    assert r.status_code == 400
    assert ".json" in r.text


def test_restore_upload_rejects_invalid_json(admin_token):
    files = {"file": ("bkp.json", b"NOT A JSON {{{", "application/json")}
    r = requests.post(f"{BASE_URL}/api/drive/restore-upload",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      files=files, data={"mode": "merge"}, timeout=20)
    assert r.status_code == 400


def test_restore_upload_rejects_different_company(admin_token):
    """Backup com _meta.company_id diferente do user → erro."""
    payload = {
        "_meta": {"company_id": "co-OTHER-XYZ", "exported_at": "2026-01-01",
                  "include_secrets": False, "version": "1.0"},
        "settings": [],
    }
    files = {"file": ("bkp.json",
                       json.dumps(payload).encode("utf-8"),
                       "application/json")}
    r = requests.post(f"{BASE_URL}/api/drive/restore-upload",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      files=files, data={"mode": "merge"}, timeout=20)
    assert r.status_code == 400
    assert "outra empresa" in r.text.lower() or "empresa" in r.text.lower()


def test_restore_upload_succeeds_with_valid_json(admin_token, db):
    """Upload válido — cria/atualiza um doc de teste e verifica que aparece no banco."""
    test_id = f"test-iter139-{uuid.uuid4().hex[:8]}"
    payload = {
        "_meta": {"company_id": COMPANY_ID, "exported_at": "2026-01-01",
                  "include_secrets": False, "version": "1.0"},
        "plans": [{
            "id": test_id,
            "name": "TEST iter139 Restore Upload",
            "monthly_price": 1.0,
            "speed_down_mbps": 10,
            "active": True,
        }],
    }
    files = {"file": ("bkp.json",
                       json.dumps(payload).encode("utf-8"),
                       "application/json")}
    try:
        r = requests.post(f"{BASE_URL}/api/drive/restore-upload",
                          headers={"Authorization": f"Bearer {admin_token}"},
                          files=files, data={"mode": "merge"}, timeout=30)
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["restored"].get("plans") == 1
        # Confirma no DB
        doc = db.plans.find_one({"company_id": COMPANY_ID, "id": test_id}, {"_id": 0})
        assert doc is not None
        assert doc["name"] == "TEST iter139 Restore Upload"
    finally:
        db.plans.delete_one({"id": test_id})


def test_restore_upload_rejects_bad_mode(admin_token):
    payload = {"_meta": {"company_id": COMPANY_ID}, "plans": []}
    files = {"file": ("bkp.json", json.dumps(payload).encode("utf-8"), "application/json")}
    r = requests.post(f"{BASE_URL}/api/drive/restore-upload",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      files=files, data={"mode": "DROP_TABLE"}, timeout=20)
    assert r.status_code == 400


def test_unauthorized_no_token():
    r = requests.get(f"{BASE_URL}/api/drive/status", timeout=10)
    assert r.status_code in (401, 403)


# ======================================================================
# Snapshot info & filesystem assets
# ======================================================================
def test_snapshot_info_includes_filesystem_assets(admin_token):
    r = requests.get(f"{BASE_URL}/api/drive/snapshot-info",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    # Verify the new structure
    assert "filesystem_assets" in data
    fa = data["filesystem_assets"]
    assert "paths" in fa
    assert "total_files" in fa
    assert "total_size_bytes" in fa
    assert "total_size_mb" in fa
    assert isinstance(fa["paths"], list)
    assert len(fa["paths"]) >= 4  # onboarding, holerites, wa_quickimages, wa_transcripts
    # Each path has required fields
    for p in fa["paths"]:
        assert "disk_path" in p
        assert "tar_name" in p
        assert "files" in p
        assert "included_by_default" in p
        assert "will_be_included" in p


def test_snapshot_info_collections_count_82(admin_token):
    """Garante que estamos cobrindo o catálogo completo (>= 80 coleções)."""
    r = requests.get(f"{BASE_URL}/api/drive/snapshot-info",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    data = r.json()
    assert data["collections_in_schema"] >= 80


def test_restore_upload_accepts_tarball_field(admin_token, db):
    """Endpoint aceita um files_tarball opcional + JSON principal."""
    import tarfile, io
    test_id = f"test-iter140-{uuid.uuid4().hex[:8]}"
    payload = {
        "_meta": {"company_id": COMPANY_ID, "exported_at": "2026-01-01",
                  "include_secrets": False, "version": "1.0"},
        "plans": [{"id": test_id, "name": "TEST iter140",
                   "monthly_price": 1.0, "active": True}],
    }
    # Builds a minimal tarball with one fake holerite
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w:gz") as tar:
        content = b"fake PDF holerite for test"
        info = tarfile.TarInfo(name="holerites/co-demo/test_iter140.pdf")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    tar_bytes = tar_buf.getvalue()
    files = {
        "file": ("bkp.json",
                  json.dumps(payload).encode("utf-8"),
                  "application/json"),
        "files_tarball": ("bkp.files.tar.gz", tar_bytes, "application/gzip"),
    }
    try:
        r = requests.post(f"{BASE_URL}/api/drive/restore-upload",
                          headers={"Authorization": f"Bearer {admin_token}"},
                          files=files, data={"mode": "merge"}, timeout=60)
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["restored"].get("plans") == 1
        # Files extracted
        assert "files_extracted" in result
        assert result["files_extracted"]["extracted"] >= 1
        # Confirma que o arquivo foi escrito no disco
        from pathlib import Path
        target = Path("/app/data/holerites/co-demo/test_iter140.pdf")
        assert target.exists()
        assert target.read_bytes() == b"fake PDF holerite for test"
        target.unlink()  # cleanup
    finally:
        db.plans.delete_one({"id": test_id})


def test_restore_upload_rejects_bad_tarball(admin_token):
    """Tarball com nome inválido deve falhar."""
    payload = {"_meta": {"company_id": COMPANY_ID}, "plans": []}
    files = {
        "file": ("bkp.json", json.dumps(payload).encode("utf-8"), "application/json"),
        "files_tarball": ("evil.zip", b"PK\x03\x04fake", "application/zip"),
    }
    r = requests.post(f"{BASE_URL}/api/drive/restore-upload",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      files=files, data={"mode": "merge"}, timeout=20)
    assert r.status_code == 400
    assert "tar.gz" in r.text.lower()


# ======================================================================
# Backup local (download direto, sem precisar de Drive conectado)
# ======================================================================
def test_backup_local_returns_zip(admin_token):
    """POST /api/drive/backup-local devolve um ZIP válido com snapshot+files."""
    import io
    import zipfile
    r = requests.post(f"{BASE_URL}/api/drive/backup-local?include_files=true",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      timeout=180, stream=True)
    assert r.status_code == 200, r.text[:300]
    assert r.headers["content-type"] == "application/zip"
    assert "smartprov-backup" in r.headers.get("content-disposition", "")
    # X-headers presentes
    assert int(r.headers["X-Snapshot-Bytes"]) > 1000
    assert int(r.headers["X-Total-Bytes"]) > 1000
    # ZIP válido com 3 arquivos
    buf = io.BytesIO(r.content)
    with zipfile.ZipFile(buf, "r") as zf:
        names = zf.namelist()
        assert "snapshot.json" in names
        assert "README.txt" in names
        # snapshot é JSON parseável
        snap = json.loads(zf.read("snapshot.json"))
        assert "_meta" in snap or "settings" in snap or "plans" in snap


def test_backup_local_can_run_multiple_times(admin_token):
    """Deve permitir backups consecutivos sem rate limit."""
    for _ in range(3):
        r = requests.post(f"{BASE_URL}/api/drive/backup-local?include_files=false",
                          headers={"Authorization": f"Bearer {admin_token}"}, timeout=120)
        assert r.status_code == 200


def test_backup_local_get_method_also_works(admin_token):
    """Endpoint aceita GET (pra usar em <a href>)."""
    r = requests.get(f"{BASE_URL}/api/drive/backup-local?include_files=false",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=120)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"


def test_backup_local_requires_auth():
    r = requests.post(f"{BASE_URL}/api/drive/backup-local", timeout=10)
    assert r.status_code in (401, 403)
