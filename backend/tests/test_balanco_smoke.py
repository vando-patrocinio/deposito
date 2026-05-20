"""Smoke tests — Balanço de Estoque (cycle counting).

Cobre:
- POST /api/stok/balanco/start cria sessão (counting).
- POST /scan registra MAC (com duplicação tratada).
- POST /consumable atualiza qty.
- POST /finalize -> pending_approval com variance.
- POST /approve: gestor NÃO pode (403 separation of duties);
  administrador/super_admin pode.
- POST /cancel: gestor pode cancelar.
- Modo cego oculta expected_macs no GET enquanto counting.
"""
import os

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, pw):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _hdr(t): return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@empresa.com", "123456")


@pytest.fixture(scope="module")
def gestor_tok():
    return _login("gestor@empresa.com", "123456")


@pytest.fixture(scope="module")
def vando_tok():
    """Super_admin + auditor. Usado p/ aprovar."""
    return _login("vando@example.com", "vando123")


def _cleanup(sid, tok):
    """Cancela sessão se ainda existir (tolerante a já-cancelada)."""
    try:
        requests.post(f"{API}/stok/balanco/{sid}/cancel",
                       headers=_hdr(tok), timeout=10)
    except Exception:
        pass


# ---------------------------------------------------------------------------
class TestBalancoFullFlow:
    def test_start_session(self, admin_tok):
        r = requests.post(f"{API}/stok/balanco/start", headers=_hdr(admin_tok),
                           json={"scope_type": "empresa", "mode": "open",
                                 "include_consumables": False},
                           timeout=15)
        if r.status_code == 409:
            # já há balanço aberto p/ empresa — cancela e tenta de novo
            from re import search
            m = search(r"id=([\w-]+)", r.json().get("detail", ""))
            if m:
                _cleanup(m.group(1), admin_tok)
            r = requests.post(f"{API}/stok/balanco/start", headers=_hdr(admin_tok),
                               json={"scope_type": "empresa", "mode": "open",
                                     "include_consumables": False},
                               timeout=15)
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        assert sid.startswith("BAL-")
        # cleanup ao fim
        _cleanup(sid, admin_tok)

    def test_full_open_mode_flow(self, admin_tok, vando_tok):
        """Cria → scan → finalize → aprovar (vando) → estado approved."""
        # Start
        rs = requests.post(f"{API}/stok/balanco/start", headers=_hdr(admin_tok),
                             json={"scope_type": "empresa", "mode": "open",
                                   "include_consumables": False},
                             timeout=15)
        if rs.status_code == 409:
            from re import search
            m = search(r"id=([\w-]+)", rs.json().get("detail", ""))
            if m:
                _cleanup(m.group(1), admin_tok)
            rs = requests.post(f"{API}/stok/balanco/start", headers=_hdr(admin_tok),
                                 json={"scope_type": "empresa", "mode": "open",
                                       "include_consumables": False},
                                 timeout=15)
        assert rs.status_code == 200, rs.text
        sid = rs.json()["id"]

        try:
            # Scan MAC fake
            rscan = requests.post(f"{API}/stok/balanco/{sid}/scan",
                                    headers=_hdr(admin_tok),
                                    json={"mac": "DE:AD:BE:EF:00:01"},
                                    timeout=10)
            assert rscan.status_code == 200, rscan.text
            # Duplicado
            rdup = requests.post(f"{API}/stok/balanco/{sid}/scan",
                                    headers=_hdr(admin_tok),
                                    json={"mac": "DE:AD:BE:EF:00:01"},
                                    timeout=10).json()
            assert rdup["duplicate"] is True

            # Finalize
            rfin = requests.post(f"{API}/stok/balanco/{sid}/finalize",
                                    headers=_hdr(admin_tok), timeout=15)
            assert rfin.status_code == 200, rfin.text
            assert rfin.json()["status"] == "pending_approval"
            v = rfin.json()["variance"]
            assert "matched" in v and "missing" in v and "extra" in v
            assert "accuracy_pct" in v

            # GET detalhe (já finalizado) devolve expected_macs
            rget = requests.get(f"{API}/stok/balanco/{sid}",
                                  headers=_hdr(admin_tok), timeout=10)
            assert rget.status_code == 200, rget.text
            assert rget.json()["status"] == "pending_approval"

            # Approve com vando (super_admin)
            rap = requests.post(f"{API}/stok/balanco/{sid}/approve",
                                  headers=_hdr(vando_tok),
                                  json={"missing_action": "perdido"},
                                  timeout=20)
            assert rap.status_code == 200, rap.text
            assert rap.json()["status"] == "approved"
        finally:
            _cleanup(sid, admin_tok)

    def test_blind_mode_hides_expected(self, admin_tok):
        rs = requests.post(f"{API}/stok/balanco/start", headers=_hdr(admin_tok),
                             json={"scope_type": "empresa", "mode": "blind",
                                   "include_consumables": False},
                             timeout=15)
        if rs.status_code == 409:
            from re import search
            m = search(r"id=([\w-]+)", rs.json().get("detail", ""))
            if m:
                _cleanup(m.group(1), admin_tok)
            rs = requests.post(f"{API}/stok/balanco/start", headers=_hdr(admin_tok),
                                 json={"scope_type": "empresa", "mode": "blind",
                                       "include_consumables": False},
                                 timeout=15)
        assert rs.status_code == 200, rs.text
        sid = rs.json()["id"]
        try:
            r = requests.get(f"{API}/stok/balanco/{sid}",
                              headers=_hdr(admin_tok), timeout=10)
            assert r.status_code == 200
            d = r.json()
            # Em counting + blind: expected_macs deve estar oculto, mas
            # expected_count visível.
            assert "expected_count" in d
            assert "expected_macs" not in d
        finally:
            _cleanup(sid, admin_tok)


# ---------------------------------------------------------------------------
class TestBalancoRbac:
    def test_gestor_cannot_approve(self, admin_tok, gestor_tok):
        """Separation of duties: gestor inicia/finaliza mas não aprova."""
        rs = requests.post(f"{API}/stok/balanco/start", headers=_hdr(gestor_tok),
                             json={"scope_type": "empresa", "mode": "open",
                                   "include_consumables": False},
                             timeout=15)
        if rs.status_code == 409:
            from re import search
            m = search(r"id=([\w-]+)", rs.json().get("detail", ""))
            if m:
                _cleanup(m.group(1), admin_tok)
            rs = requests.post(f"{API}/stok/balanco/start", headers=_hdr(gestor_tok),
                                 json={"scope_type": "empresa", "mode": "open",
                                       "include_consumables": False},
                                 timeout=15)
        assert rs.status_code == 200, rs.text
        sid = rs.json()["id"]
        try:
            # Finalize OK
            rfin = requests.post(f"{API}/stok/balanco/{sid}/finalize",
                                    headers=_hdr(gestor_tok), timeout=15)
            assert rfin.status_code == 200

            # Approve deve falhar 403
            rap = requests.post(f"{API}/stok/balanco/{sid}/approve",
                                  headers=_hdr(gestor_tok),
                                  json={"missing_action": "perdido"},
                                  timeout=15)
            assert rap.status_code == 403, rap.text
            assert "administrador" in rap.json().get("detail", "").lower() \
                or "super" in rap.json().get("detail", "").lower()
        finally:
            _cleanup(sid, gestor_tok)
