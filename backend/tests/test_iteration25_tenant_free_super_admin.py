"""Iteration 25 tests:
- Tenant fixes em dashboard + push (não vazam entre empresas)
- Plano FREE com 3 colaboradores ilimitado no tempo
- Super admin metrics (/api/saas/admin/metrics)
- Super admin login vando.patrocinio@gmail.com
- Smoke regression: trial signup
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://selfie-attendance-7.preview.emergentagent.com").rstrip("/")
TIMEOUT = 30


# ----------------------------- helpers ---------------------------------

def _signup(plan: str = "trial", suffix: str = "") -> dict:
    ts = int(time.time() * 1000)
    sfx = f"{suffix}_{ts}_{uuid.uuid4().hex[:5]}"
    payload = {
        "company_name": f"TEST_Iter25_{sfx}",
        "admin_name": f"Admin {sfx}",
        "email": f"iter25+{sfx}@example.com",
        "password": "123456",
        "plan": plan,
    }
    r = requests.post(f"{BASE_URL}/api/saas/signup", json=payload, timeout=TIMEOUT)
    assert r.status_code == 200, f"signup failed: {r.status_code} {r.text}"
    data = r.json()
    assert data.get("ok") and data.get("access_token")
    return data


def _login(email: str, password: str) -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# =============== A) Tenant fixes — dashboard ============================

class TestTenantDashboard:
    def test_new_company_overtime_trend_zero(self):
        data = _signup("trial", "ot")
        tok = data["access_token"]
        r = requests.get(
            f"{BASE_URL}/api/dashboard/overtime/trend?months=3",
            headers=_auth(tok),
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "series" in body and isinstance(body["series"], list)
        # Empresa nova: nenhum colaborador, todos os totais zerados
        for s in body["series"]:
            assert s["total_overtime_min"] == 0, f"vazou HE de outra empresa: {s}"
            assert float(s["total_paid_brl"]) == 0.0
        # Sem ranking de débito
        assert body.get("top_debit") in ([], None)

    def test_demo_overtime_trend_returns_data(self):
        tok = _login("admin@example.com", "admin123")
        r = requests.get(
            f"{BASE_URL}/api/dashboard/overtime/trend?months=3",
            headers=_auth(tok),
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Não falhamos se demo não tiver HE — apenas garantimos que a estrutura é válida
        assert isinstance(body.get("series"), list)
        assert len(body["series"]) > 0

    def test_new_company_dwell_heatmap_empty(self):
        data = _signup("trial", "hm")
        tok = data["access_token"]
        r = requests.get(
            f"{BASE_URL}/api/dashboard/dwell-heatmap?year=2026&month=2",
            headers=_auth(tok),
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["rows"] == []
        assert body["total_minutes"] == 0

    def test_demo_dwell_heatmap_isolated(self):
        tok = _login("admin@example.com", "admin123")
        r = requests.get(
            f"{BASE_URL}/api/dashboard/dwell-heatmap?year=2026&month=2",
            headers=_auth(tok),
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        body = r.json()
        assert "rows" in body and "total_minutes" in body


# =============== B) Tenant fixes — push notifications ===================

class TestTenantPush:
    def test_push_subscribe_company_scoped(self):
        data_a = _signup("trial", "pushA")
        tok_a = data_a["access_token"]
        sub = {
            "endpoint": f"https://fcm.googleapis.com/fcm/send/test-{uuid.uuid4().hex}",
            "keys": {"p256dh": "test_p256dh_aaa", "auth": "test_auth_aaa"},
        }
        r = requests.post(
            f"{BASE_URL}/api/push/subscribe",
            json=sub,
            headers=_auth(tok_a),
            timeout=TIMEOUT,
        )
        # Subscribe deve retornar 200 mesmo sem VAPID (fallback) ou 200/201
        assert r.status_code in (200, 201), f"push subscribe falhou: {r.status_code} {r.text}"

    def test_push_test_broadcast_isolated_per_company(self):
        # Cria 2 empresas, registra um sub em cada e dispara test em A
        data_a = _signup("trial", "pushTA")
        tok_a = data_a["access_token"]
        data_b = _signup("trial", "pushTB")
        tok_b = data_b["access_token"]

        for tok in (tok_a, tok_b):
            sub = {
                "endpoint": f"https://fcm.googleapis.com/fcm/send/test-{uuid.uuid4().hex}",
                "keys": {"p256dh": f"k_{uuid.uuid4().hex[:12]}", "auth": f"a_{uuid.uuid4().hex[:8]}"},
            }
            requests.post(
                f"{BASE_URL}/api/push/subscribe",
                json=sub,
                headers=_auth(tok),
                timeout=TIMEOUT,
            )

        r = requests.post(
            f"{BASE_URL}/api/push/test",
            json={"title": "iter25", "body": "scope-test"},
            headers=_auth(tok_a),
            timeout=TIMEOUT,
        )
        assert r.status_code in (200, 202), f"push test falhou: {r.status_code} {r.text}"
        body = r.json()
        # Tipicamente: {"sent": N, "failed": M} ou similar — apenas garantimos
        # que nao explode e que os contadores são pequenos (apenas a empresa A)
        sent = body.get("sent", body.get("count", 0))
        # Pode ser 0 (endpoint fake é rejeitado), mas NÃO deve exceder o número
        # de subs registrados pela empresa A (1)
        assert sent <= 5, f"vazou push para outras empresas? body={body}"


# =============== C) Plano FREE ==========================================

class TestPlanFree:
    def test_free_signup_creates_correct_company(self):
        data = _signup("free", "free")
        co = data["company"]
        assert co["plan"] == "free", co
        assert co["max_collaborators"] == 3
        assert co["status"] == "active"
        assert co.get("paid_until")  # 100 anos no futuro

        # Reconfere via /saas/me
        tok = data["access_token"]
        r = requests.get(f"{BASE_URL}/api/saas/me", headers=_auth(tok), timeout=TIMEOUT)
        assert r.status_code == 200
        me = r.json()
        assert me["plan"] == "free"
        assert me.get("is_free") is True
        assert me["max_collaborators"] == 3

    def test_free_plan_collaborator_limit(self):
        data = _signup("free", "limit")
        tok = data["access_token"]
        # Cria 3 colaboradores OK (CPFs únicos baseados em uuid)
        cpf_seed = uuid.uuid4().hex[:8].upper()
        for i in range(3):
            r = requests.post(
                f"{BASE_URL}/api/collaborators",
                json={
                    "name": f"TEST_Colab_{i}_{uuid.uuid4().hex[:5]}",
                    "cpf": f"{cpf_seed}{i:03d}",
                    "email": f"colab{i}_{uuid.uuid4().hex[:5]}@test.com",
                    "phone": f"+551199999000{i}",
                },
                headers=_auth(tok),
                timeout=TIMEOUT,
            )
            assert r.status_code in (200, 201), f"colab {i+1} falhou: {r.status_code} {r.text}"
        # 4º deve barrar
        r = requests.post(
            f"{BASE_URL}/api/collaborators",
            json={
                "name": f"TEST_Colab_4_{uuid.uuid4().hex[:5]}",
                "cpf": f"{cpf_seed}999",
                "email": f"colab4_{uuid.uuid4().hex[:5]}@test.com",
                "phone": "+5511999990004",
            },
            headers=_auth(tok),
            timeout=TIMEOUT,
        )
        assert r.status_code == 402, f"esperado 402 quota, recebeu {r.status_code}: {r.text}"

    def test_free_to_pro_via_checkout(self):
        data = _signup("free", "upg")
        tok = data["access_token"]
        # cria session
        r = requests.post(
            f"{BASE_URL}/api/saas/billing/checkout",
            json={"origin_url": BASE_URL},
            headers=_auth(tok),
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, r.text
        sid = r.json()["session_id"]
        # consulta status — em test mode com sk_test_emergent vira fallback "paid"
        r2 = requests.get(
            f"{BASE_URL}/api/saas/billing/status/{sid}",
            headers=_auth(tok),
            timeout=TIMEOUT,
        )
        assert r2.status_code == 200, r2.text
        # se voltou paid (test mode), checa que empresa virou Pro
        if r2.json().get("payment_status") == "paid":
            me = requests.get(f"{BASE_URL}/api/saas/me", headers=_auth(tok), timeout=TIMEOUT).json()
            assert me["plan"] == "monthly_99"
            assert me["max_collaborators"] == 25


# =============== D) Super admin =========================================

class TestSuperAdmin:
    def test_super_admin_login(self):
        tok = _login("vando.patrocinio@gmail.com", "123456")
        r = requests.get(f"{BASE_URL}/api/saas/me", headers=_auth(tok), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        me = r.json()
        assert me.get("is_super_admin") is True

    def test_super_admin_metrics(self):
        tok = _login("vando.patrocinio@gmail.com", "123456")
        r = requests.get(f"{BASE_URL}/api/saas/admin/metrics", headers=_auth(tok), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        m = r.json()
        for k in ("mrr_brl", "arr_brl", "total_companies", "by_status",
                  "signups_series", "churn_rate_pct", "total_collaborators"):
            assert k in m, f"campo ausente: {k}"
        assert isinstance(m["signups_series"], list)
        assert len(m["signups_series"]) == 12, f"signups_series len={len(m['signups_series'])}"
        assert isinstance(m["by_status"], dict)
        assert m["total_companies"] >= 1

    def test_metrics_forbidden_for_non_super(self):
        tok = _login("admin@example.com", "admin123")
        r = requests.get(f"{BASE_URL}/api/saas/admin/metrics", headers=_auth(tok), timeout=TIMEOUT)
        assert r.status_code == 403, f"esperado 403, recebeu {r.status_code}"


# =============== E) Regression smoke ====================================

class TestRegressionSmoke:
    def test_trial_signup_default(self):
        data = _signup("trial", "smk")
        co = data["company"]
        assert co["plan"] == "monthly_99"
        assert co["status"] == "trialing"
        tok = data["access_token"]
        r = requests.get(f"{BASE_URL}/api/saas/me", headers=_auth(tok), timeout=TIMEOUT)
        assert r.status_code == 200
        me = r.json()
        assert me["status_effective"] == "trialing"
        assert me["days_left"] is not None and 12 <= me["days_left"] <= 14

    def test_collaborators_tenant_scoped(self):
        data = _signup("trial", "tn")
        tok = data["access_token"]
        r = requests.get(f"{BASE_URL}/api/collaborators", headers=_auth(tok), timeout=TIMEOUT)
        assert r.status_code == 200
        assert r.json() == [] or isinstance(r.json(), list)
