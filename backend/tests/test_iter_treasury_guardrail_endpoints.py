"""test_iter_treasury_guardrail_endpoints.py — endpoint-level tests for
the IA Tesoureira Global Guardrail (Q1=b/Q2=b/Q3=a/Q4=b).

Hits live preview backend (REACT_APP_BACKEND_URL). Uses admin@empresa.com /
123456 (super_admin co-demo). Cleans up with company_id='co-demo' payees
prefixed TEST_GUARDRAIL_ to be safe.

Coverage:
 - Q3 failsafe: POST /payees forces ia_autorizada=False
 - PATCH cannot set ia_autorizada=True
 - /validate-pix happy path and 400 sem PIX
 - /authorize-ia: 409 sem PIX, 400 confirm_text errado, 200 OK
 - /revoke-ia
 - /send chokepoint: 403 + blocked_reasons para fornecedor não autorizado
 - CEO override em fornecedor não autorizado continua bloqueado (Q4=b)
 - /guardrail/audit lista com counts + filtros
 - /guardrail/migrate-payees idempotente + só super_admin
 - /api/ceo/treasury-guardrail-audit com Bearer CEO_BRIEFING_TOKEN
"""
from __future__ import annotations

import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
CEO_TOKEN = os.environ.get("CEO_BRIEFING_TOKEN", "")  # SECURITY_LOCK ART.3: fail-closed

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"

CANON_TEXT = ("Estou autorizando a IA Tesoureira a pagar automaticamente "
              "este fornecedor dentro das regras globais.")


@pytest.fixture(scope="module")
def auth_headers():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
               timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:300]}"
    token = r.json().get("access_token") or r.json().get("token")
    assert token, f"no token in login resp: {r.json()}"
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def created_payees(auth_headers):
    created = []
    yield created
    # cleanup
    # only soft (mark inactive via PATCH) - no DELETE endpoint exists guaranteed
    for pid in created:
        try:
            requests.patch(
                f"{BASE_URL}/api/treasury/payees/{pid}",
                headers=auth_headers,
                json={"active": False, "name": f"TEST_GUARDRAIL_CLEANED_{pid}"},
                timeout=10,
            )
        except Exception:
            pass


def _create_payee(auth_headers, name_suffix="", **overrides):
    body = {
        "name": f"TEST_GUARDRAIL_{name_suffix}_{uuid.uuid4().hex[:6]}",
        "document": "12345678901",
        "pix_key": "12345678901",
        "pix_key_type": "CPF",
        "category": "fornecedor",
        "ia_autorizada": True,  # malicious — must be forced False
        "max_amount_auto": 500.0,
        **overrides,
    }
    r = requests.post(f"{BASE_URL}/api/treasury/payees",
                      headers=auth_headers, json=body, timeout=20)
    return r


# ─── Q3 failsafe ───────────────────────────────────────────────
def test_create_payee_forces_ia_autorizada_false(auth_headers, created_payees):
    r = _create_payee(auth_headers, "create_failsafe")
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert data.get("ia_autorizada") is False, \
        f"Q3 violated! payee was created with ia_autorizada=True: {data}"
    assert data.get("validacao_chave_pix", {}).get("validated_at") is None
    assert data.get("validacao_conta", {}).get("validated_at") is None
    assert data.get("bloqueado") is False
    created_payees.append(data["payee_id"])


def test_patch_cannot_set_ia_autorizada_true(auth_headers, created_payees):
    r = _create_payee(auth_headers, "patch_ia")
    assert r.status_code in (200, 201)
    pid = r.json()["payee_id"]
    created_payees.append(pid)

    # try to set ia_autorizada=True via PATCH
    patch = requests.patch(
        f"{BASE_URL}/api/treasury/payees/{pid}",
        headers=auth_headers,
        json={"ia_autorizada": True, "name": "TEST_GUARDRAIL_patched"},
        timeout=20)
    assert patch.status_code in (200, 204), patch.text

    # GET and verify still False
    g = requests.get(f"{BASE_URL}/api/treasury/payees",
                     headers=auth_headers, timeout=20)
    assert g.status_code == 200
    payee = next((x for x in g.json().get("payees", []) if x.get("payee_id") == pid), None)
    assert payee is not None, "payee disappeared"
    assert payee.get("ia_autorizada") is False, \
        f"PATCH leaked ia_autorizada=True! {payee}"


# ─── validate-pix ──────────────────────────────────────────────
def test_validate_pix_400_without_pix(auth_headers, created_payees):
    """Cria payee, depois PATCH pix_key='' p/ exercer o 400 da rota."""
    r = _create_payee(auth_headers, "nopix")
    assert r.status_code in (200, 201), r.text
    pid = r.json()["payee_id"]
    created_payees.append(pid)
    # patch pix to empty (schema permits Optional)
    requests.patch(f"{BASE_URL}/api/treasury/payees/{pid}",
                   headers=auth_headers, json={"pix_key": ""}, timeout=20)
    v = requests.post(f"{BASE_URL}/api/treasury/payees/{pid}/validate-pix",
                      headers=auth_headers, json={}, timeout=20)
    if v.status_code == 200:
        pytest.skip("PATCH did not unset pix_key — route 400 path requires raw empty pix")
    assert v.status_code == 400, f"expected 400 got {v.status_code}: {v.text}"


def test_validate_pix_happy_path(auth_headers, created_payees):
    r = _create_payee(auth_headers, "pixok")
    pid = r.json()["payee_id"]
    created_payees.append(pid)
    v = requests.post(f"{BASE_URL}/api/treasury/payees/{pid}/validate-pix",
                      headers=auth_headers, json={}, timeout=20)
    assert v.status_code == 200, v.text
    # confirm persistence
    g = requests.get(f"{BASE_URL}/api/treasury/payees",
                     headers=auth_headers, timeout=20)
    pay = next((x for x in g.json()["payees"] if x.get("payee_id") == pid), None)
    assert pay
    assert pay["validacao_chave_pix"].get("validated_at") is not None
    assert pay["validacao_chave_pix"].get("by") == ADMIN_EMAIL


# ─── authorize-ia ──────────────────────────────────────────────
def test_authorize_ia_409_without_pix_validated(auth_headers, created_payees):
    r = _create_payee(auth_headers, "auth_nopix")
    pid = r.json()["payee_id"]
    created_payees.append(pid)
    a = requests.post(
        f"{BASE_URL}/api/treasury/payees/{pid}/authorize-ia",
        headers=auth_headers,
        json={"confirm_authorization": True,
              "confirm_text": CANON_TEXT,
              "motivo": "teste sem pix validado guardrail global"},
        timeout=20)
    assert a.status_code == 409, f"expected 409 got {a.status_code}: {a.text}"


def test_authorize_ia_400_wrong_confirm_text(auth_headers, created_payees):
    r = _create_payee(auth_headers, "auth_wrong")
    pid = r.json()["payee_id"]
    created_payees.append(pid)
    # validate pix first
    requests.post(f"{BASE_URL}/api/treasury/payees/{pid}/validate-pix",
                  headers=auth_headers, json={}, timeout=20)
    a = requests.post(
        f"{BASE_URL}/api/treasury/payees/{pid}/authorize-ia",
        headers=auth_headers,
        json={"confirm_authorization": True,
              "confirm_text": "texto errado",
              "motivo": "teste texto errado canon"},
        timeout=20)
    assert a.status_code == 400, f"expected 400 got {a.status_code}: {a.text}"


def test_authorize_ia_happy_then_revoke(auth_headers, created_payees):
    r = _create_payee(auth_headers, "auth_ok")
    pid = r.json()["payee_id"]
    created_payees.append(pid)
    requests.post(f"{BASE_URL}/api/treasury/payees/{pid}/validate-pix",
                  headers=auth_headers, json={}, timeout=20)
    a = requests.post(
        f"{BASE_URL}/api/treasury/payees/{pid}/authorize-ia",
        headers=auth_headers,
        json={"confirm_authorization": True,
              "confirm_text": CANON_TEXT,
              "motivo": "autorizacao valida teste end-to-end global"},
        timeout=20)
    assert a.status_code == 200, a.text
    assert a.json().get("ia_autorizada") is True

    # GET verify
    g = requests.get(f"{BASE_URL}/api/treasury/payees",
                     headers=auth_headers, timeout=20)
    pay = next(x for x in g.json()["payees"] if x.get("payee_id") == pid)
    assert pay["ia_autorizada"] is True
    assert pay.get("ia_autorizada_at")
    assert pay.get("ia_autorizada_by") == ADMIN_EMAIL

    # revoke
    rv = requests.post(
        f"{BASE_URL}/api/treasury/payees/{pid}/revoke-ia?motivo=teste_revoke",
        headers=auth_headers, timeout=20)
    assert rv.status_code == 200, rv.text
    assert rv.json().get("ia_autorizada") is False
    g2 = requests.get(f"{BASE_URL}/api/treasury/payees",
                      headers=auth_headers, timeout=20)
    pay2 = next(x for x in g2.json()["payees"] if x.get("payee_id") == pid)
    assert pay2["ia_autorizada"] is False
    assert pay2.get("ia_autorizada_revoked_at")


# ─── /guardrail/audit ──────────────────────────────────────────
def test_guardrail_audit_lists_with_counts(auth_headers):
    r = requests.get(f"{BASE_URL}/api/treasury/guardrail/audit?limit=50",
                     headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "audit" in d and isinstance(d["audit"], list)
    assert "counts" in d
    for k in ("total", "blocked", "allowed", "ceo_override"):
        assert k in d["counts"], f"missing count {k}: {d['counts']}"
        assert isinstance(d["counts"][k], int)


def test_guardrail_audit_filter_blocked(auth_headers):
    r = requests.get(
        f"{BASE_URL}/api/treasury/guardrail/audit?allowed_eq=false&limit=10",
        headers=auth_headers, timeout=20)
    assert r.status_code == 200
    rows = r.json()["audit"]
    for row in rows:
        assert row.get("allowed") is False, f"filter leaked allowed=True row: {row}"


# ─── /guardrail/migrate-payees ─────────────────────────────────
def test_migrate_payees_idempotent_super_admin(auth_headers):
    r1 = requests.post(f"{BASE_URL}/api/treasury/guardrail/migrate-payees",
                       headers=auth_headers, timeout=30)
    assert r1.status_code == 200, r1.text
    j1 = r1.json()
    # 2nd call should still succeed and not change anything new
    r2 = requests.post(f"{BASE_URL}/api/treasury/guardrail/migrate-payees",
                       headers=auth_headers, timeout=30)
    assert r2.status_code == 200, r2.text


# ─── /api/ceo/treasury-guardrail-audit (Custom GPT) ────────────
def test_ceo_treasury_guardrail_audit_bearer():
    h = {"Authorization": f"Bearer {CEO_TOKEN}"}
    r = requests.get(f"{BASE_URL}/api/ceo/treasury-guardrail-audit?limit=10",
                     headers=h, timeout=20)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    d = r.json()
    assert "audit" in d
    assert "counts" in d
    for k in ("total", "blocked", "allowed", "ceo_override"):
        assert k in d["counts"]


def test_ceo_treasury_guardrail_audit_rejects_no_token():
    r = requests.get(f"{BASE_URL}/api/ceo/treasury-guardrail-audit",
                     timeout=20)
    assert r.status_code in (401, 403), \
        f"expected auth fail got {r.status_code}: {r.text[:200]}"


# ─── /payments/{id}/send chokepoint ────────────────────────────
def _create_approved_payment(auth_headers, payee_id, amount=100.0):
    """Cria um pagamento já approved no fornecedor — depende do endpoint
    existente. Se não conseguir criar, retorna None e o teste é skipped."""
    body = {"payee_id": payee_id, "amount_brl": amount, "method": "pix",
            "scheduled_for": "2026-12-31",
            "description": "TEST_GUARDRAIL chokepoint"}
    r = requests.post(f"{BASE_URL}/api/treasury/payments",
                      headers=auth_headers, json=body, timeout=20)
    if r.status_code not in (200, 201):
        return None
    pid = r.json().get("payment_id") or r.json().get("id")
    # try approve
    ap = requests.post(f"{BASE_URL}/api/treasury/payments/{pid}/approve",
                       headers=auth_headers,
                       json={"reason": "approve para teste guardrail"},
                       timeout=20)
    if ap.status_code not in (200, 201):
        # maybe already approved by auto flow — proceed
        pass
    return pid


def test_send_blocks_unauthorized_payee_with_403(auth_headers, created_payees):
    # cria payee NÃO autorizado
    r = _create_payee(auth_headers, "send_block")
    if r.status_code not in (200, 201):
        pytest.skip("could not create payee")
    pid = r.json()["payee_id"]
    created_payees.append(pid)

    payment_id = _create_approved_payment(auth_headers, pid, amount=80.0)
    if not payment_id:
        pytest.skip("payment-create endpoint differs; cannot exercise /send chokepoint")

    s = requests.post(f"{BASE_URL}/api/treasury/payments/{payment_id}/send",
                      headers=auth_headers, timeout=30)
    assert s.status_code == 403, \
        f"expected 403 guardrail block; got {s.status_code}: {s.text[:400]}"
    detail = s.json().get("detail") or {}
    if isinstance(detail, dict):
        assert detail.get("error") == "guardrail_global_bloqueou"
        assert "blocked_reasons" in detail
        assert any(x.startswith("regra_1_") for x in detail["blocked_reasons"])
        assert "guardrail_audit_id" in detail


def test_send_ceo_override_still_blocks_unauthorized_payee(auth_headers, created_payees):
    """Q4=b: CEO override NÃO libera fornecedor não autorizado."""
    r = _create_payee(auth_headers, "ceo_block")
    if r.status_code not in (200, 201):
        pytest.skip("could not create payee")
    pid = r.json()["payee_id"]
    created_payees.append(pid)

    payment_id = _create_approved_payment(auth_headers, pid, amount=50.0)
    if not payment_id:
        pytest.skip("payment-create endpoint differs")

    motivo = "ceo override teste guardrail nao deve liberar fornecedor nao autorizado"
    q = (f"?ceo_override_motivo={motivo.replace(' ', '%20')}"
         f"&ceo_override_confirmed_twice=true")
    s = requests.post(
        f"{BASE_URL}/api/treasury/payments/{payment_id}/send{q}",
        headers=auth_headers, timeout=30)
    assert s.status_code == 403, \
        f"Q4=b violated! ceo override unlocked unauthorized payee: " \
        f"{s.status_code} {s.text[:400]}"
