"""Tests for iter117 - Acompanhamento (Kanban Trello-style) module.

Covers /api/projects endpoints: CRUD, checklist, file upload, activity feed,
RBAC (auditor allowed, colaborador 403), tenant scoping, edge cases.
"""
import base64
import io
import os
import requests
import pytest

# Use REACT_APP_BACKEND_URL from frontend/.env (public preview URL)
BASE_URL = os.environ.get("PUBLIC_BACKEND_URL") or "https://dual-combine-3.preview.emergentagent.com"
BASE_URL = BASE_URL.rstrip("/")

AUDITOR = {"email": "auditor@example.com", "password": "auditor123"}
COLAB = {"email": "colaborador@empresa.com", "password": "123456"}
SUPER = {"email": "admin@empresa.com", "password": "123456"}


def _login(creds: dict) -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    body = r.json()
    tok = body.get("access_token") or body.get("token")
    assert tok, f"no access_token in login response: {body}"
    return tok


@pytest.fixture(scope="module")
def auditor_token():
    return _login(AUDITOR)


@pytest.fixture(scope="module")
def colab_token():
    try:
        return _login(COLAB)
    except AssertionError:
        pytest.skip("colaborador credential unavailable")


@pytest.fixture(scope="module")
def auditor_headers(auditor_token):
    return {"Authorization": f"Bearer {auditor_token}"}


# ---------------------------------------------------------------------------
# Create + list + stats
# ---------------------------------------------------------------------------
class TestProjectCRUD:
    project_id = None

    def test_create_project_as_auditor(self, auditor_headers):
        payload = {
            "title": "TEST_iter117 Vistoria poste 42",
            "description": "Inspeção fotográfica antes da troca de splitter.",
            "status": "backlog",
            "priority": "alta",
            "tags": ["fiber", "poste"],
            "assignees": ["Diogo"],
            "start_date": "2026-01-15",
            "end_date": "2026-01-20",
        }
        r = requests.post(f"{BASE_URL}/api/projects", json=payload, headers=auditor_headers, timeout=30)
        assert r.status_code == 201, f"{r.status_code} {r.text}"
        data = r.json()
        assert data["title"] == payload["title"]
        assert data["status"] == "backlog"
        assert data["priority"] == "alta"
        assert data["company_id"] == "co-demo"
        assert data["id"].startswith("prj-")
        assert "_id" not in data
        assert data["checklist_progress"]["pct"] == 0
        TestProjectCRUD.project_id = data["id"]

    def test_create_project_invalid_status(self, auditor_headers):
        r = requests.post(f"{BASE_URL}/api/projects",
                            json={"title": "TEST_bad", "status": "xxx"},
                            headers=auditor_headers, timeout=30)
        assert r.status_code == 400

    def test_create_project_empty_title(self, auditor_headers):
        r = requests.post(f"{BASE_URL}/api/projects",
                            json={"title": "   "},
                            headers=auditor_headers, timeout=30)
        assert r.status_code == 400

    def test_list_projects(self, auditor_headers):
        r = requests.get(f"{BASE_URL}/api/projects", headers=auditor_headers, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data and "count" in data
        ids = [p["id"] for p in data["items"]]
        assert TestProjectCRUD.project_id in ids
        for p in data["items"]:
            assert p["company_id"] == "co-demo"
            assert "_id" not in p

    def test_list_projects_with_filter(self, auditor_headers):
        r = requests.get(f"{BASE_URL}/api/projects?status=backlog",
                          headers=auditor_headers, timeout=30)
        assert r.status_code == 200
        for p in r.json()["items"]:
            assert p["status"] == "backlog"

    def test_list_projects_invalid_status_filter(self, auditor_headers):
        r = requests.get(f"{BASE_URL}/api/projects?status=invalid",
                          headers=auditor_headers, timeout=30)
        assert r.status_code == 400

    def test_stats(self, auditor_headers):
        r = requests.get(f"{BASE_URL}/api/projects/stats", headers=auditor_headers, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "total" in d and "by_status" in d and "by_priority" in d
        for s in ("backlog", "em_andamento", "em_revisao", "finalizado"):
            assert s in d["by_status"]
        assert d["total"] >= 1

    def test_get_project(self, auditor_headers):
        pid = TestProjectCRUD.project_id
        r = requests.get(f"{BASE_URL}/api/projects/{pid}", headers=auditor_headers, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["id"] == pid
        assert "files" in d

    def test_get_project_404(self, auditor_headers):
        r = requests.get(f"{BASE_URL}/api/projects/prj-not-exists-zz",
                          headers=auditor_headers, timeout=30)
        assert r.status_code == 404

    def test_patch_status_transition_and_activity(self, auditor_headers):
        pid = TestProjectCRUD.project_id
        for new_status in ("em_andamento", "em_revisao", "finalizado"):
            r = requests.patch(f"{BASE_URL}/api/projects/{pid}",
                                  json={"status": new_status},
                                  headers=auditor_headers, timeout=30)
            assert r.status_code == 200, f"transition to {new_status}: {r.text}"
            assert r.json()["status"] == new_status
        # Verify activity feed has status_changed events
        ra = requests.get(f"{BASE_URL}/api/projects/{pid}/activity",
                            headers=auditor_headers, timeout=30)
        assert ra.status_code == 200
        types = [it["type"] for it in ra.json()["items"]]
        assert "created" in types
        assert types.count("status_changed") == 3

    def test_patch_status_invalid(self, auditor_headers):
        pid = TestProjectCRUD.project_id
        r = requests.patch(f"{BASE_URL}/api/projects/{pid}",
                              json={"status": "DONE"},
                              headers=auditor_headers, timeout=30)
        assert r.status_code == 400

    def test_patch_404(self, auditor_headers):
        r = requests.patch(f"{BASE_URL}/api/projects/prj-nope",
                              json={"title": "x"},
                              headers=auditor_headers, timeout=30)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Checklist
# ---------------------------------------------------------------------------
class TestChecklist:
    project_id = None
    item_id = None

    def test_setup_project(self, auditor_headers):
        r = requests.post(f"{BASE_URL}/api/projects",
                            json={"title": "TEST_iter117 checklist proj"},
                            headers=auditor_headers, timeout=30)
        assert r.status_code == 201
        TestChecklist.project_id = r.json()["id"]

    def test_add_checklist_item(self, auditor_headers):
        pid = TestChecklist.project_id
        r = requests.post(f"{BASE_URL}/api/projects/{pid}/checklist",
                            json={"text": "Levar trena a laser"},
                            headers=auditor_headers, timeout=30)
        assert r.status_code == 201, r.text
        item = r.json()
        assert item["text"] == "Levar trena a laser"
        assert item["done"] is False
        assert item["id"].startswith("ck-")
        TestChecklist.item_id = item["id"]

    def test_add_checklist_empty_text(self, auditor_headers):
        pid = TestChecklist.project_id
        r = requests.post(f"{BASE_URL}/api/projects/{pid}/checklist",
                            json={"text": "   "}, headers=auditor_headers, timeout=30)
        assert r.status_code == 400

    def test_add_checklist_proj_404(self, auditor_headers):
        r = requests.post(f"{BASE_URL}/api/projects/prj-zz/checklist",
                            json={"text": "x"}, headers=auditor_headers, timeout=30)
        assert r.status_code == 404

    def test_mark_done_and_undo(self, auditor_headers):
        pid, iid = TestChecklist.project_id, TestChecklist.item_id
        # Mark done
        r = requests.patch(f"{BASE_URL}/api/projects/{pid}/checklist/{iid}",
                              json={"done": True}, headers=auditor_headers, timeout=30)
        assert r.status_code == 200
        # Confirm via GET
        rg = requests.get(f"{BASE_URL}/api/projects/{pid}", headers=auditor_headers, timeout=30)
        cl = rg.json()["checklist"]
        item = next(it for it in cl if it["id"] == iid)
        assert item["done"] is True
        assert item.get("done_at")
        assert item.get("done_by_name")
        assert rg.json()["checklist_progress"]["done"] == 1
        # Undo
        ru = requests.patch(f"{BASE_URL}/api/projects/{pid}/checklist/{iid}",
                              json={"done": False}, headers=auditor_headers, timeout=30)
        assert ru.status_code == 200
        rg2 = requests.get(f"{BASE_URL}/api/projects/{pid}", headers=auditor_headers, timeout=30)
        item2 = next(it for it in rg2.json()["checklist"] if it["id"] == iid)
        assert item2["done"] is False
        assert item2.get("done_at") in (None, "")
        assert item2.get("done_by_name") in (None, "")

    def test_delete_checklist_item(self, auditor_headers):
        pid, iid = TestChecklist.project_id, TestChecklist.item_id
        r = requests.delete(f"{BASE_URL}/api/projects/{pid}/checklist/{iid}",
                              headers=auditor_headers, timeout=30)
        assert r.status_code == 200
        # Verify removed
        rg = requests.get(f"{BASE_URL}/api/projects/{pid}", headers=auditor_headers, timeout=30)
        assert all(it["id"] != iid for it in rg.json()["checklist"])

    def test_checklist_activity_events(self, auditor_headers):
        pid = TestChecklist.project_id
        ra = requests.get(f"{BASE_URL}/api/projects/{pid}/activity",
                            headers=auditor_headers, timeout=30)
        types = [it["type"] for it in ra.json()["items"]]
        assert "checklist_added" in types
        assert "checklist_done" in types
        assert "checklist_undone" in types
        assert "checklist_removed" in types


# ---------------------------------------------------------------------------
# Files (upload/download/delete + mime + 10MB limit)
# ---------------------------------------------------------------------------
class TestFiles:
    project_id = None
    file_id = None

    def test_setup_project(self, auditor_token):
        h = {"Authorization": f"Bearer {auditor_token}"}
        r = requests.post(f"{BASE_URL}/api/projects",
                            json={"title": "TEST_iter117 files proj"},
                            headers=h, timeout=30)
        assert r.status_code == 201
        TestFiles.project_id = r.json()["id"]

    def test_upload_pdf(self, auditor_token):
        # Minimal valid PDF
        pdf_bytes = b"%PDF-1.4\n%fake\n1 0 obj <<>> endobj\ntrailer<<>>\n%%EOF"
        pid = TestFiles.project_id
        files = {"file": ("relatorio.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
        r = requests.post(f"{BASE_URL}/api/projects/{pid}/files",
                            files=files,
                            headers={"Authorization": f"Bearer {auditor_token}"}, timeout=60)
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["filename"] == "relatorio.pdf"
        assert d["mime"].startswith("application/pdf")
        assert d["size"] == len(pdf_bytes)
        assert d["id"].startswith("pfl-")
        TestFiles.file_id = d["id"]

    def test_upload_invalid_mime(self, auditor_token):
        pid = TestFiles.project_id
        files = {"file": ("malicioso.exe", io.BytesIO(b"MZ\x00\x00"), "application/x-msdownload")}
        r = requests.post(f"{BASE_URL}/api/projects/{pid}/files",
                            files=files,
                            headers={"Authorization": f"Bearer {auditor_token}"}, timeout=30)
        assert r.status_code == 400

    def test_upload_size_limit(self, auditor_token):
        # 11 MB jpeg-typed payload
        pid = TestFiles.project_id
        big = b"\xff" * (11 * 1024 * 1024)
        files = {"file": ("big.jpg", io.BytesIO(big), "image/jpeg")}
        r = requests.post(f"{BASE_URL}/api/projects/{pid}/files",
                            files=files,
                            headers={"Authorization": f"Bearer {auditor_token}"}, timeout=120)
        assert r.status_code == 413, f"got {r.status_code} {r.text[:200]}"

    def test_upload_project_404(self, auditor_token):
        files = {"file": ("a.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")}
        r = requests.post(f"{BASE_URL}/api/projects/prj-zz/files",
                            files=files,
                            headers={"Authorization": f"Bearer {auditor_token}"}, timeout=30)
        assert r.status_code == 404

    def test_download_file(self, auditor_token):
        pid, fid = TestFiles.project_id, TestFiles.file_id
        r = requests.get(f"{BASE_URL}/api/projects/{pid}/files/{fid}/download",
                          headers={"Authorization": f"Bearer {auditor_token}"}, timeout=30)
        assert r.status_code == 200
        cd = r.headers.get("Content-Disposition", "")
        assert "relatorio.pdf" in cd
        assert r.content.startswith(b"%PDF")

    def test_download_file_404(self, auditor_token):
        pid = TestFiles.project_id
        r = requests.get(f"{BASE_URL}/api/projects/{pid}/files/pfl-zz/download",
                          headers={"Authorization": f"Bearer {auditor_token}"}, timeout=30)
        assert r.status_code == 404

    def test_get_project_includes_files(self, auditor_token):
        pid, fid = TestFiles.project_id, TestFiles.file_id
        r = requests.get(f"{BASE_URL}/api/projects/{pid}",
                          headers={"Authorization": f"Bearer {auditor_token}"}, timeout=30)
        d = r.json()
        assert d["files_count"] >= 1
        assert any(f["id"] == fid for f in d["files"])

    def test_delete_file(self, auditor_token):
        pid, fid = TestFiles.project_id, TestFiles.file_id
        r = requests.delete(f"{BASE_URL}/api/projects/{pid}/files/{fid}",
                              headers={"Authorization": f"Bearer {auditor_token}"}, timeout=30)
        assert r.status_code == 200
        # confirm removed
        rg = requests.get(f"{BASE_URL}/api/projects/{pid}/files/{fid}/download",
                            headers={"Authorization": f"Bearer {auditor_token}"}, timeout=30)
        assert rg.status_code == 404

    def test_files_activity_events(self, auditor_token):
        pid = TestFiles.project_id
        ra = requests.get(f"{BASE_URL}/api/projects/{pid}/activity",
                            headers={"Authorization": f"Bearer {auditor_token}"}, timeout=30)
        types = [it["type"] for it in ra.json()["items"]]
        assert "file_uploaded" in types
        assert "file_removed" in types


# ---------------------------------------------------------------------------
# RBAC: colaborador 403
# ---------------------------------------------------------------------------
class TestRBAC:
    def test_colaborador_cannot_create(self, colab_token, auditor_headers):
        # create a project as auditor first to ensure list works (not strictly needed)
        h = {"Authorization": f"Bearer {colab_token}"}
        r = requests.post(f"{BASE_URL}/api/projects",
                            json={"title": "TEST_iter117 forbidden"},
                            headers=h, timeout=30)
        assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text}"

    def test_colaborador_can_list(self, colab_token):
        h = {"Authorization": f"Bearer {colab_token}"}
        r = requests.get(f"{BASE_URL}/api/projects", headers=h, timeout=30)
        # collaborator should be able to read (per design); accept 200
        assert r.status_code == 200

    def test_colaborador_cannot_patch(self, colab_token, auditor_headers):
        # Create one as auditor, then try to patch as colab
        ra = requests.post(f"{BASE_URL}/api/projects",
                              json={"title": "TEST_iter117 rbac patch"},
                              headers=auditor_headers, timeout=30)
        assert ra.status_code == 201
        pid = ra.json()["id"]
        rp = requests.patch(f"{BASE_URL}/api/projects/{pid}",
                              json={"status": "em_andamento"},
                              headers={"Authorization": f"Bearer {colab_token}"}, timeout=30)
        assert rp.status_code == 403
        # cleanup
        requests.delete(f"{BASE_URL}/api/projects/{pid}", headers=auditor_headers, timeout=30)


# ---------------------------------------------------------------------------
# Delete project (cascade) — runs LAST via separate class
# ---------------------------------------------------------------------------
class TestCascadeDelete:
    def test_delete_cascade(self, auditor_headers):
        # Create proj + checklist + file, then delete and verify activity/files gone.
        rp = requests.post(f"{BASE_URL}/api/projects",
                              json={"title": "TEST_iter117 cascade"},
                              headers=auditor_headers, timeout=30)
        pid = rp.json()["id"]
        requests.post(f"{BASE_URL}/api/projects/{pid}/checklist",
                       json={"text": "x"}, headers=auditor_headers, timeout=30)
        files = {"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 dummy"), "application/pdf")}
        # multipart, drop Content-Type
        h = {k: v for k, v in auditor_headers.items() if k.lower() != "content-type"}
        requests.post(f"{BASE_URL}/api/projects/{pid}/files",
                       files=files, headers=h, timeout=30)
        # Delete
        rd = requests.delete(f"{BASE_URL}/api/projects/{pid}",
                              headers=auditor_headers, timeout=30)
        assert rd.status_code == 200
        assert rd.json().get("files_removed", 0) >= 1
        # GET 404
        rg = requests.get(f"{BASE_URL}/api/projects/{pid}",
                            headers=auditor_headers, timeout=30)
        assert rg.status_code == 404
        # activity also blocked (project doesn't exist → 404)
        ra = requests.get(f"{BASE_URL}/api/projects/{pid}/activity",
                            headers=auditor_headers, timeout=30)
        assert ra.status_code == 404

    def test_delete_404(self, auditor_headers):
        r = requests.delete(f"{BASE_URL}/api/projects/prj-nope",
                              headers=auditor_headers, timeout=30)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Final cleanup — delete all TEST_iter117 projects
# ---------------------------------------------------------------------------
def test_zz_final_cleanup(auditor_headers):
    r = requests.get(f"{BASE_URL}/api/projects", headers=auditor_headers, timeout=30)
    for p in r.json().get("items", []):
        if p.get("title", "").startswith("TEST_iter117"):
            requests.delete(f"{BASE_URL}/api/projects/{p['id']}",
                              headers=auditor_headers, timeout=30)
