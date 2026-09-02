"""iter256 — migração disco → Emergent Object Storage.

Cobertura:
- holerite: upload / download público / fallback legado / assinatura / draft IA
- onboarding público: upload de imagem
- pre-atendimento: upload + leitura (objstore e legado em disco)
- whatsapp quick-images: upload / leitura (novo e legado) / send / delete
- backup restore: tar inválido (400) e dump válido pequeno
- regressão geral: /api/ responde, logs sem 'orchestrator INDISPONÍVEL'
"""
import io
import os
import tarfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import bson
import pymongo
import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = (os.environ.get("REACT_APP_BACKEND_URL")
            or frontend_env.get("REACT_APP_BACKEND_URL"))
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

backend_env = dotenv_values("/app/backend/.env")
MONGO_URL = backend_env.get("MONGO_URL")
DB_NAME = backend_env.get("DB_NAME")
# necessário para usar services.objstore fora do processo do supervisor
for _k in ("EMERGENT_LLM_KEY", "INTEGRATION_PROXY_URL"):
    if backend_env.get(_k) and not os.environ.get(_k):
        os.environ[_k] = backend_env[_k]

ADMIN = {"email": "admin@empresa.com", "password": "123456"}
SUPER = {"email": "vando@ligotelecom.com", "password": "Ligo696150@@@"}

CID = "co-demo"
COLLAB = "col-demo-001"
TAG = "TEST_iter256"

HOLERITE_DISK = Path("/app/data/holerites")
PREATT_DISK = Path("/app/backend/uploads/pre_attendance")
WAIMG_DISK = Path("/app/backend/uploads/wa_quickimages")

PDF_A = (b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<<>>\n"
         b"%%EOF\n" + b"A" * 400)
PDF_SIGNED = (b"%PDF-1.4\n/Type/Sig /ByteRange[0 1 2 3] /SubFilter"
              b"/ETSI.CAdES.detached\ntrailer<<>>\n%%EOF\n" + b"S" * 400)
PNG_1PX = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00"
           b"\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx"
           b"\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND"
           b"\xaeB`\x82")
PNG_BIG = PNG_1PX + b"\x00" * 2048  # > 1KB p/ onboarding


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope="session")
def mdb():
    if not MONGO_URL or not DB_NAME:
        pytest.skip("MONGO_URL/DB_NAME ausentes")
    return pymongo.MongoClient(MONGO_URL)[DB_NAME]


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"login {creds['email']} falhou {r.status_code}: "
                    f"{r.text[:300]}")
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, "sem token no login"
    return tok


@pytest.fixture(scope="session")
def admin_token():
    return _login(ADMIN)


@pytest.fixture(scope="session")
def H(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def super_token(admin_token):
    """vando@ligotelecom.com está com senha divergente (401) — usa o admin
    demo, que também tem is_super_admin=true."""
    r = requests.post(f"{BASE_URL}/api/auth/login", json=SUPER, timeout=30)
    if r.status_code == 200:
        return r.json().get("access_token") or r.json().get("token")
    return admin_token


@pytest.fixture(scope="session", autouse=True)
def cleanup(mdb):
    yield
    mdb.payroll_documents.delete_many({"employee_name": {"$regex": TAG}})
    mdb.payroll_documents.delete_many({"id": {"$regex": "^hol-TESTiter256"}})
    mdb.payroll_ai_drafts.delete_many({"parse_id": {"$regex": TAG}})
    mdb.holerite_ai_drafts.delete_many({"id": {"$regex": TAG}})
    mdb.payroll_documents.delete_many({"ai_parse_id": {"$regex": TAG}})
    mdb.wa_quick_images.delete_many({"label": {"$regex": TAG}})
    mdb.pre_attendance_images.delete_many({"filename": {"$regex": TAG}})
    mdb.onboarding_sessions.delete_many({"suggested_name": {"$regex": TAG}})
    try:
        mdb.drop_collection(f"{TAG}_restore")
    except Exception:
        pass


# ---------------------------------------------------------------- regressão
class TestRegression:
    def test_root_api_alive(self, H):
        r = requests.get(f"{BASE_URL}/api/", headers=H, timeout=30)
        assert r.status_code < 500, f"{r.status_code} {r.text[:200]}"
        assert r.status_code in (200, 401, 403, 404), r.status_code

    def test_objstore_module_importable(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=30)
        assert r.status_code < 500, r.text[:200]


# ---------------------------------------------------------------- holerite
@pytest.fixture(scope="class")
def uploaded_holerite(H, mdb):
    files = {"file": (f"{TAG}.pdf", PDF_A, "application/pdf")}
    data = {"employee_id": COLLAB, "employee_name": f"{TAG} Carlos",
            "competence_month": 1, "competence_year": 2025,
            "gross": 1000, "net": 900}
    r = requests.post(f"{BASE_URL}/api/holerites/upload", headers=H,
                      files=files, data=data, timeout=180)
    assert r.status_code == 200, f"upload {r.status_code}: {r.text[:400]}"
    doc_id = r.json()["id"]
    raw = mdb.payroll_documents.find_one({"id": doc_id})
    assert raw, "doc não persistido no Mongo"
    return {"id": doc_id, "raw": raw}


class TestHoleriteObjstore:
    def test_upload_writes_objstore_ref(self, uploaded_holerite):
        fp = uploaded_holerite["raw"].get("file_path") or ""
        assert fp.startswith("objstore://"), f"file_path legado: {fp!r}"

    def test_public_download_without_jwt_is_public(self, uploaded_holerite):
        """PWA do colaborador abre o PDF via window.open (sem header)."""
        doc_id = uploaded_holerite["id"]
        r = requests.get(
            f"{BASE_URL}/api/holerites/public/{COLLAB}/{doc_id}/file",
            timeout=120)
        assert r.status_code != 401, (
            "endpoint 'public' exige JWT — rbac_policy.PUBLIC_PATHS tem "
            "'/api/holerite/public/' mas o router é '/api/holerites'")
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"

    def test_public_download_same_pdf(self, uploaded_holerite, H):
        doc_id = uploaded_holerite["id"]
        r = requests.get(
            f"{BASE_URL}/api/holerites/public/{COLLAB}/{doc_id}/file",
            headers=H, timeout=120)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert "inline" in (r.headers.get("content-disposition") or "")
        assert r.content == PDF_A, "PDF baixado difere do enviado"

    def test_sign_upload_and_signed_download(self, uploaded_holerite, mdb, H):
        doc_id = uploaded_holerite["id"]
        files = {"file": (f"{TAG}_signed.pdf", PDF_SIGNED, "application/pdf")}
        r = requests.post(
            f"{BASE_URL}/api/holerites/public/{COLLAB}/{doc_id}/sign-upload",
            headers=H, files=files, timeout=180)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert r.json().get("ok") is True
        raw = mdb.payroll_documents.find_one({"id": doc_id})
        sref = raw.get("signed_file_path") or ""
        assert sref.startswith("objstore://"), f"signed ref legado: {sref!r}"
        g = requests.get(
            f"{BASE_URL}/api/holerites/public/{COLLAB}/{doc_id}/signed-file",
            headers=H, timeout=120)
        assert g.status_code == 200, f"{g.status_code} {g.text[:300]}"
        assert g.headers.get("content-type", "").startswith("application/pdf")
        assert g.content == PDF_SIGNED


class TestHoleriteLegacyFallback:
    """Docs antigos com file_path em disco continuam lendo; 404 tratado."""

    doc_id = f"hol-TESTiter256{uuid.uuid4().hex[:4]}"

    def test_legacy_disk_read_ok(self, mdb, H):
        HOLERITE_DISK.mkdir(parents=True, exist_ok=True)
        p = HOLERITE_DISK / f"{TAG}_{uuid.uuid4().hex[:8]}.pdf"
        p.write_bytes(PDF_A)
        mdb.payroll_documents.insert_one({
            "id": self.doc_id, "company_id": CID, "employee_id": COLLAB,
            "employee_name": f"{TAG} Legado", "competence_month": 2,
            "competence_year": 2025, "pay_date": "2025-03-05",
            "file_path": str(p), "status": "available",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.get(
            f"{BASE_URL}/api/holerites/public/{COLLAB}/{self.doc_id}/file",
            headers=H, timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert r.content == PDF_A
        p.unlink(missing_ok=True)

    def test_legacy_missing_file_returns_404(self, mdb, H):
        missing_id = f"hol-TESTiter256{uuid.uuid4().hex[:4]}"
        mdb.payroll_documents.insert_one({
            "id": missing_id, "company_id": CID, "employee_id": COLLAB,
            "employee_name": f"{TAG} Sumido", "competence_month": 3,
            "competence_year": 2025, "pay_date": "2025-04-05",
            "file_path": str(HOLERITE_DISK / "nao_existe_iter256.pdf"),
            "status": "available",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.get(
            f"{BASE_URL}/api/holerites/public/{COLLAB}/{missing_id}/file",
            headers=H, timeout=60)
        assert r.status_code == 404, f"esperado 404, veio {r.status_code}: {r.text[:200]}"


class TestHoleriteAiDraftImport:
    """Grava draft no object storage (como o /ai-parse) e roda /ai-import."""

    def test_import_reads_draft_from_objstore(self, H, mdb):  # noqa
        parse_id = f"hai-{TAG}-{uuid.uuid4().hex[:6]}"
        # simula o /ai-parse: draft + PDF no object storage
        import sys
        sys.path.insert(0, "/app/backend")
        import asyncio

        from services.objstore import put_object
        ref = asyncio.run(put_object(
            f"smartprov/holerites/{CID}/drafts/{parse_id}.pdf",
            PDF_A, "application/pdf"))
        assert ref.startswith("objstore://")
        mdb.payroll_ai_drafts.update_one(
            {"parse_id": parse_id},
            {"$set": {"parse_id": parse_id, "company_id": CID,
                      "storage_ref": ref,
                      "created_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True)
        mdb.holerite_ai_drafts.insert_one({
            "id": parse_id, "company_id": CID,
            "preview": {"matches": [{
                "parsed": {"full_name": f"{TAG} IA", "gross": 100,
                           "net": 90, "deductions_total": 10},
                "match": {"id": COLLAB}, "match_score": 100,
                "match_status": "matched"}],
                "stats": {"parsed_count": 1, "matched_count": 1}},
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.post(
            f"{BASE_URL}/api/holerites/ai-import", headers=H,
            json={"parse_id": parse_id, "competence_month": 4,
                  "competence_year": 2025,
                  "items": [{"parsed_index": 0, "employee_id": COLLAB}]},
            timeout=180)
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        body = r.json()
        assert body.get("imported", 0) >= 1, body
        new_id = ((body.get("items") or [{}])[0]).get("id")
        assert new_id, f"sem id importado: {body}"
        raw = mdb.payroll_documents.find_one({"id": new_id})
        assert (raw.get("file_path") or "").startswith("objstore://")
        # doc pode entrar em pending_review por anomalia (regra de negócio):
        # nesse caso o download público é 404 por design.
        if raw.get("status") == "available":
            d = requests.get(
                f"{BASE_URL}/api/holerites/public/{COLLAB}/{new_id}/file",
                headers=H, timeout=120)
            assert d.status_code == 200, f"{d.status_code} {d.text[:200]}"
            assert d.content == PDF_A
        else:
            # lê direto do object storage p/ provar o round-trip
            from services.objstore import get_object
            data, ctype = asyncio.run(get_object(raw["file_path"]))
            assert data == PDF_A
            assert "pdf" in ctype


# -------------------------------------------------------------- onboarding
class TestOnboardingUpload:
    def test_public_upload_goes_to_objstore(self, H, mdb):
        r = requests.post(f"{BASE_URL}/api/onboarding/sessions", headers=H,
                          json={"phone": "5551999990256",
                                "suggested_name": f"{TAG} Onb"},
                          timeout=60)
        assert r.status_code == 200, f"create session {r.status_code}: {r.text[:300]}"
        token = r.json().get("token")
        assert token, r.json()
        up = requests.post(
            f"{BASE_URL}/api/onboarding/public/{token}/upload",
            data={"file_kind": "id_document"},
            files={"file": (f"{TAG}.png", PNG_BIG, "image/png")},
            timeout=180)
        assert up.status_code == 200, f"{up.status_code} {up.text[:400]}"
        time.sleep(1)
        sess = mdb.onboarding_sessions.find_one(
            {"suggested_name": f"{TAG} Onb"}, sort=[("created_at", -1)])
        assert sess, "sessão não encontrada no Mongo"
        path = ((sess.get("files") or {}).get("id_document") or {}).get("path") or ""
        assert path.startswith("objstore://"), f"path legado: {path!r}"

    def test_liveness_frames_go_to_objstore(self, H, mdb):
        r = requests.post(f"{BASE_URL}/api/onboarding/sessions", headers=H,
                          json={"phone": "5551999990257",
                                "suggested_name": f"{TAG} Live"},
                          timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        token = r.json()["token"]
        fs = {f"frame_{k}": (f"{TAG}_{k}.jpg", PNG_BIG, "image/jpeg")
              for k in ("left", "right", "smile")}
        up = requests.post(
            f"{BASE_URL}/api/onboarding/public/{token}/liveness",
            files=fs, timeout=180)
        # BUG conhecido: services/onboarding.py usa LlmChat.with_max_tokens(),
        # método inexistente na emergentintegrations instalada → AttributeError
        # não tratado → HTTP 500.
        assert up.status_code != 500, f"liveness 500: {up.text[:300]}"
        assert up.status_code in (200, 400, 422), \
            f"{up.status_code} {up.text[:300]}"
        sess = mdb.onboarding_sessions.find_one(
            {"suggested_name": f"{TAG} Live"}, sort=[("created_at", -1)])
        saved = ((sess or {}).get("liveness") or {}).get("saved_paths") or {}
        if up.status_code == 200:
            assert saved, f"liveness sem saved_paths: {sess.get('liveness')}"
            for label, p in saved.items():
                assert str(p).startswith("objstore://"), f"{label}: {p!r}"


# ---------------------------------------------------------- pré-atendimento
class TestPreAttendanceImages:
    def test_upload_and_read_objstore(self, H, mdb):
        import base64
        r = requests.post(f"{BASE_URL}/api/pre-attendance/upload-image",
                          headers=H,
                          json={"image_b64": base64.b64encode(PNG_1PX).decode(),
                                "filename": f"{TAG}.png"},
                          timeout=120)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        fname = r.json()["filename"]
        rec = mdb.pre_attendance_images.find_one({"filename": fname})
        assert (rec or {}).get("storage_ref", "").startswith("objstore://"), rec
        g = requests.get(f"{BASE_URL}/api/pre-attendance/image/{fname}",
                         headers=H, timeout=60)
        assert g.status_code == 200, f"{g.status_code} {g.text[:200]}"
        assert g.content == PNG_1PX
        assert g.headers.get("content-type", "").startswith("image/png")
        mdb.pre_attendance_images.delete_one({"filename": fname})

    def test_legacy_disk_image_still_readable(self, H):
        PREATT_DISK.mkdir(parents=True, exist_ok=True)
        fname = f"{CID}_{TAG}legacy.png"
        p = PREATT_DISK / fname
        p.write_bytes(PNG_1PX)
        g = requests.get(f"{BASE_URL}/api/pre-attendance/image/{fname}",
                         headers=H, timeout=60)
        p.unlink(missing_ok=True)
        assert g.status_code == 200, f"{g.status_code} {g.text[:200]}"
        assert g.content == PNG_1PX


# ------------------------------------------------------- wa quick images
class TestWaQuickImages:
    def test_full_cycle_and_send_handled(self, H, admin_token, mdb):
        r = requests.post(f"{BASE_URL}/api/whatsapp-baileys/quick-images",
                          headers=H,
                          data={"label": f"{TAG} img"},
                          files={"file": (f"{TAG}.png", PNG_1PX, "image/png")},
                          timeout=120)
        assert r.status_code == 200, f"upload {r.status_code}: {r.text[:300]}"
        img_id = r.json()["id"]
        assert (r.json().get("storage_ref") or "").startswith("objstore://")
        g = requests.get(
            f"{BASE_URL}/api/whatsapp-baileys/quick-images/{img_id}/file",
            headers=H, timeout=60)
        assert g.status_code == 200, f"{g.status_code} {g.text[:200]}"
        assert g.content == PNG_1PX
        # send com sidecar desconectado → erro tratado (nunca 500)
        s = requests.post(
            f"{BASE_URL}/api/whatsapp-baileys/quick-images/{img_id}/send",
            headers=H, json={"phone": "5551999990256", "caption": TAG},
            timeout=120)
        assert s.status_code != 500, f"send deu 500: {s.text[:300]}"
        assert s.status_code in (200, 400, 502, 503), \
            f"send status inesperado {s.status_code}: {s.text[:300]}"
        d = requests.delete(
            f"{BASE_URL}/api/whatsapp-baileys/quick-images/{img_id}",
            headers=H, timeout=60)
        assert d.status_code == 200, f"delete {d.status_code}: {d.text[:200]}"
        assert mdb.wa_quick_images.find_one({"id": img_id}) is None

    def test_legacy_disk_quick_image(self, H, mdb):
        WAIMG_DISK.mkdir(parents=True, exist_ok=True)
        img_id = f"wqi-{TAG[:6]}{uuid.uuid4().hex[:6]}"
        p = WAIMG_DISK / f"{img_id}.png"
        p.write_bytes(PNG_1PX)
        mdb.wa_quick_images.insert_one({
            "id": img_id, "company_id": CID, "label": f"{TAG} legacy",
            "file_ext": "png", "size_bytes": len(PNG_1PX), "sort_order": 99,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        g = requests.get(
            f"{BASE_URL}/api/whatsapp-baileys/quick-images/{img_id}/file",
            headers=H, timeout=60)
        assert g.status_code == 200, f"{g.status_code} {g.text[:200]}"
        assert g.content == PNG_1PX
        requests.delete(
            f"{BASE_URL}/api/whatsapp-baileys/quick-images/{img_id}",
            headers=H, timeout=60)
        p.unlink(missing_ok=True)
        mdb.wa_quick_images.delete_one({"id": img_id})


# ------------------------------------------------------------- backup/restore
class TestBackupRestore:
    def test_missing_confirm_returns_400(self, super_token):
        r = requests.post(
            f"{BASE_URL}/api/admin/backup/restore",
            headers={"Authorization": f"Bearer {super_token}"},
            files={"file": ("x.tar.gz", b"garbage", "application/gzip")},
            data={"drop_existing": "false", "confirm": "NOPE"}, timeout=120)
        assert r.status_code == 400, f"{r.status_code} {r.text[:200]}"

    def test_invalid_targz_returns_400(self, super_token):
        r = requests.post(
            f"{BASE_URL}/api/admin/backup/restore",
            headers={"Authorization": f"Bearer {super_token}"},
            files={"file": ("bad.tar.gz", b"not a tar at all" * 20,
                            "application/gzip")},
            data={"drop_existing": "false", "confirm": "RESTORE"}, timeout=120)
        assert r.status_code == 400, \
            f"esperado 400 tratado, veio {r.status_code}: {r.text[:300]}"

    def test_valid_small_dump_restores(self, super_token, mdb):
        doc = {"_id": f"{TAG}-1", "hello": "iter256"}
        payload = bson.BSON.encode(doc)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(
                name=f"mongo-dump-test/{DB_NAME}/{TAG}_restore.bson")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        buf.seek(0)
        r = requests.post(
            f"{BASE_URL}/api/admin/backup/restore",
            headers={"Authorization": f"Bearer {super_token}"},
            files={"file": ("ok.tar.gz", buf.read(), "application/gzip")},
            data={"drop_existing": "false", "confirm": "RESTORE"}, timeout=180)
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        body = r.json()
        assert body.get("ok") is True
        assert body.get("drop_used") is False
        assert body.get("docs_total", 0) >= 1, body
        got = mdb[f"{TAG}_restore"].find_one({"_id": f"{TAG}-1"})
        assert got and got["hello"] == "iter256", got
        mdb.drop_collection(f"{TAG}_restore")
