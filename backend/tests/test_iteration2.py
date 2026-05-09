"""Iteration 2 backend tests.

Covers the new additions:
- POST /api/email/test (Resend key vazia -> 400)
- POST /api/timesheets/send/{cid} agora com PDF em memória (não pode quebrar)
- reportlab import OK no startup (verificado via health)
- Regressão básica: admin-login, settings, collaborators CRUD rápido, health.
"""
import uuid
from datetime import datetime, timezone


# ---------- Regressão: health / reportlab startup ----------
class TestStartupAndHealth:
    def test_root_health_still_200(self, api, base_url):
        r = api.get(f"{base_url}/api/")
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is True
        assert data.get("service") == "Ponto do Colaborador"

    def test_reportlab_import_ok_indirect(self, api, base_url):
        """Se reportlab falhasse no import, o backend não subiria.
        Como /api/ responde 200, o import está OK."""
        r = api.get(f"{base_url}/api/")
        assert r.status_code == 200


# ---------- Regressão: admin-login ----------
class TestAdminAuthRegression:
    def test_admin_login_success(self, api, base_url):
        r = api.post(f"{base_url}/api/auth/admin-login", json={"password": "admin123"})
        assert r.status_code == 200
        assert r.json().get("ok") is True
        assert r.json().get("role") == "admin"

    def test_admin_login_wrong(self, api, base_url):
        r = api.post(f"{base_url}/api/auth/admin-login", json={"password": "wrong-xyz"})
        assert r.status_code == 401


# ---------- Regressão: settings (key vazia) ----------
class TestSettingsRegression:
    def test_settings_emergent_and_resend(self, api, base_url):
        # garante que a key está vazia (sobrescreve qualquer estado de testes anteriores)
        api.put(f"{base_url}/api/settings", json={"resend_api_key": ""})
        r = api.get(f"{base_url}/api/settings")
        assert r.status_code == 200
        d = r.json()
        assert d.get("emergent_key_available") is True
        assert d.get("resend_api_key_set") is False


# ---------- Nova rota: POST /api/email/test ----------
class TestEmailTestEndpoint:
    def test_email_test_rejects_without_key(self, api, base_url):
        # Garante a key vazia
        api.put(f"{base_url}/api/settings", json={"resend_api_key": ""})
        r = api.post(
            f"{base_url}/api/email/test",
            json={"to": "teste@example.com", "subject": "Ping"},
        )
        assert r.status_code == 400, r.text
        body = r.json()
        detail = body.get("detail") or body.get("message") or ""
        assert "Configure a API Key Resend antes de testar." in detail

    def test_email_test_validates_email_format(self, api, base_url):
        # Pydantic EmailStr -> 422 para email inválido
        r = api.post(
            f"{base_url}/api/email/test",
            json={"to": "not-an-email"},
        )
        assert r.status_code == 422

    def test_email_test_default_subject_accepted(self, api, base_url):
        # Sem subject (usa default do model). Ainda deve falhar 400 por key vazia,
        # confirmando que payload é aceito com apenas 'to'.
        api.put(f"{base_url}/api/settings", json={"resend_api_key": ""})
        r = api.post(f"{base_url}/api/email/test", json={"to": "ok@example.com"})
        assert r.status_code == 400
        assert "Resend" in (r.json().get("detail") or "")


# ---------- Timesheets send + PDF in-memory (key vazia) ----------
class TestTimesheetSendWithPDF:
    """Quando Resend key está vazia, endpoint deve retornar sent=false
    sem lançar 500 mesmo com nova lógica de construção de PDF."""

    def test_send_timesheet_no_key_with_demo(self, api, base_url):
        api.put(f"{base_url}/api/settings", json={"resend_api_key": ""})
        now = datetime.now(timezone.utc)
        r = api.post(
            f"{base_url}/api/timesheets/send/col-demo-001",
            params={"year": now.year, "month": now.month},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("sent") is False
        reason = (d.get("reason") or "").lower()
        assert "resend" in reason or "key" in reason

    def test_send_timesheet_pdf_path_with_fake_key(self, api, base_url):
        """Com key fake, o código DEVE construir o PDF em memória e só falhar
        no envio (reportlab deve funcionar sem exception)."""
        api.put(f"{base_url}/api/settings", json={"resend_api_key": "re_FAKE_KEY_FOR_PDF_TEST_123"})
        try:
            now = datetime.now(timezone.utc)
            r = api.post(
                f"{base_url}/api/timesheets/send/col-demo-001",
                params={"year": now.year, "month": now.month},
                timeout=30,
            )
            assert r.status_code == 200, r.text
            d = r.json()
            # deve ter tentado enviar e falhado no Resend (sent=false) mas
            # NÃO deve ter lançado 500 (prova que PDF foi gerado OK)
            assert d.get("sent") is False
            reason = (d.get("reason") or "").lower()
            # O erro deve vir do Resend (API key invalida / http), NÃO de reportlab
            assert "reportlab" not in reason
            assert "importerror" not in reason
        finally:
            # cleanup - restaura key vazia
            api.put(f"{base_url}/api/settings", json={"resend_api_key": ""})

    def test_send_timesheet_not_found(self, api, base_url):
        now = datetime.now(timezone.utc)
        r = api.post(
            f"{base_url}/api/timesheets/send/does-not-exist",
            params={"year": now.year, "month": now.month},
        )
        assert r.status_code == 404


# ---------- Regressão rápida: collaborators CRUD ----------
class TestCollaboratorsRegression:
    def test_list_collaborators_has_demo(self, api, base_url):
        r = api.get(f"{base_url}/api/collaborators")
        assert r.status_code == 200
        ids = [c.get("id") for c in r.json()]
        assert "col-demo-001" in ids

    def test_create_and_delete_collaborator(self, api, base_url):
        cpf = f"TESTIT2-{uuid.uuid4().hex[:6]}"
        payload = {
            "name": "TEST_Iter2 User",
            "cpf": cpf,
            "email": f"iter2_{uuid.uuid4().hex[:6]}@example.com",
            "phone": "+55 11 90000-0000",
        }
        r = api.post(f"{base_url}/api/collaborators", json=payload)
        assert r.status_code == 200, r.text
        coll = r.json()
        assert coll["id"].startswith("col-")
        assert coll["name"] == "TEST_Iter2 User"
        assert coll["cpf"] == cpf
        # GET para confirmar persistência
        r2 = api.get(f"{base_url}/api/collaborators/{coll['id']}")
        assert r2.status_code == 200
        assert r2.json()["cpf"] == cpf
        # DELETE
        rd = api.delete(f"{base_url}/api/collaborators/{coll['id']}")
        assert rd.status_code == 200
        assert rd.json().get("ok") is True
        # Confirma remoção
        r3 = api.get(f"{base_url}/api/collaborators/{coll['id']}")
        assert r3.status_code == 404
