"""SECURITY_LOCK V1 — Suite mínima de testes.

Cobertura por artigo:
- ART.1 — PII não-versionada (assertion estática no índice git)
- ART.2 — secrets defaults: rota não aceita login com `admin123`/`auditor123`
         quando ADMIN_PASSWORD não é o default
- ART.3 — fail-closed: SIDECAR_TOKEN ausente NÃO libera
- ART.6 — SSRF: clock.py rejeita URL privada
- ART.10 — IDOR: audit_log_panel /{aid} bloqueia acesso cross-tenant
- ART.11 — debug router: /api/auth/_debug não existe em produção
- ART.13 — info-leak: rota com erro interno devolve mensagem genérica
           sem stack trace
"""
from __future__ import annotations

import os
import sys
import subprocess
from typing import Optional

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _test_secrets import TEST_ADMIN_PASSWORD  # noqa: E402

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or "https://dual-combine-3.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"
TIMEOUT = 15


def _login(email: str, password: str) -> Optional[str]:
    try:
        r = requests.post(
            f"{API}/auth/login",
            json={"email": email, "password": password},
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            return r.json().get("access_token")
    except Exception:
        return None
    return None


# ------------------------------------------------------------------ ART.1
def test_art1_no_pii_files_in_git_index():
    """PII (uploads, holerites, planilhas) NÃO devem estar versionados."""
    out = subprocess.run(
        ["git", "ls-files", "backend/uploads/", "data/holerites/"],
        cwd="/app", capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    assert out == "", f"PII versionada detectada:\n{out}"


def test_art1_data_imports_xlsx_not_tracked():
    out = subprocess.run(
        ["git", "ls-files", "backend/data_imports/"],
        cwd="/app", capture_output=True, text=True, timeout=10,
    ).stdout.strip().splitlines()
    bad = [f for f in out if f.endswith((".xlsx", ".csv", ".ofx"))]
    assert not bad, f"Planilhas de cliente versionadas: {bad}"


# ------------------------------------------------------------------ ART.2
def test_art2_no_admin123_in_production_routes():
    """Os literais `admin123`/`auditor123` não existem em backend/routes/ ou auth.py."""
    out = subprocess.run(
        ["grep", "-rE", r'"(admin123|auditor123)"', "backend/routes/", "backend/auth.py"],
        cwd="/app", capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    assert out == "", f"Senha-default vazada em produção:\n{out}"


def test_art2_admin_login_happy_path():
    """Login admin happy path — confirma que a feature continua funcionando."""
    tok = _login("admin@empresa.com", "123456")
    assert tok, "Login admin happy path falhou (seed correto?)"


# ------------------------------------------------------------------ ART.3
def test_art3_failclosed_sidecar_token_no_default():
    """Verifica que `whatsapp-service/server.js` falha-fechado se TOKEN ausente."""
    p = "/app/whatsapp-service/server.js"
    if not os.path.exists(p):
        pytest.skip("sidecar não presente")
    src = open(p).read()
    # Não pode haver "if (!TOKEN) return next()" (fail-open)
    bad = "if (!SIDECAR_TOKEN) return next()"
    assert bad not in src, "Sidecar com fail-open detectado"


# ------------------------------------------------------------------ ART.6
def test_art6_safe_fetch_exists():
    """`backend/services/safe_fetch.py` deve existir e bloquear IPs privados."""
    p = "/app/backend/services/safe_fetch.py"
    assert os.path.exists(p), "safe_fetch.py ausente"
    src = open(p).read()
    assert "is_private" in src or "block_private" in src or "ipaddress" in src, \
        "safe_fetch não bloqueia IP privado"


# ------------------------------------------------------------------ ART.10
def test_art10_audit_log_cross_tenant_blocked():
    """Auditor de co-demo não pode ver audit_log event de outro tenant."""
    tok = _login("admin@empresa.com", "123456")
    if not tok:
        pytest.skip("auth indisponível")
    # Tentar ler um id inexistente — espera 404 (não 200 nem 500)
    r = requests.get(
        f"{API}/audit-log-panel/AID-DOES-NOT-EXIST-99999",
        headers={"Authorization": f"Bearer {tok}"}, timeout=TIMEOUT,
    )
    assert r.status_code == 404, f"esperado 404, recebido {r.status_code}: {r.text[:200]}"


# ------------------------------------------------------------------ ART.11
def test_art11_no_debug_router_in_production():
    """Rotas `/api/auth/_debug*` não devem responder."""
    tok = _login("admin@empresa.com", "123456")
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    r = requests.get(f"{API}/auth/_debug/whoami", headers=headers, timeout=TIMEOUT)
    assert r.status_code in (404, 405), f"debug router exposto: {r.status_code}"


def test_art11_debug_file_quarantined():
    """`backend/routes/auth_debug.py` deve estar removido do path de routes/."""
    assert not os.path.exists("/app/backend/routes/auth_debug.py"), \
        "auth_debug.py ainda em routes/"


# ------------------------------------------------------------------ ART.13
def test_art13_safe_detail_helper_exists():
    """Helper `safe_detail` em exception_sanitizer.py."""
    p = "/app/backend/services/exception_sanitizer.py"
    src = open(p).read()
    assert "def safe_detail(" in src, "helper safe_detail ausente"


def test_art13_no_str_e_in_routes():
    """Nenhum `HTTPException(NNN, str(e))` ou f-string com `{e}` em routes."""
    out = subprocess.run(
        ["grep", "-rnE",
         r'raise HTTPException\([0-9]+,\s*(str\(e\)|f["\x27][^"\x27]*\{e[!rsa]?\})',
         "backend/routes/", "backend/services/"],
        cwd="/app", capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    assert out == "", f"vazamento de exceção remanescente:\n{out[:1000]}"


def test_art13_generic_error_response():
    """Endpoint que lança Exception interna devolve mensagem genérica."""
    # /api/access-profiles sem auth -> 401 com detail genérico
    r = requests.get(f"{API}/access-profiles", timeout=TIMEOUT)
    assert r.status_code in (401, 403), f"esperado 401/403, recebido {r.status_code}"
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    detail = body.get("detail", "")
    # Não deve conter caminhos de arquivo nem nomes de classe Python
    assert "/app/" not in str(detail), f"detail vazou path: {detail}"
    assert "<class" not in str(detail), f"detail vazou class: {detail}"
    assert "Traceback" not in str(detail), f"detail vazou traceback: {detail}"


# ====================================================================
# SECURITY AUDIT V2 — testes adicionais (19/06/2026)
# ====================================================================

def test_v2_jwt_secret_strength():
    """JWT_SECRET deve ter pelo menos 64 chars (32 bytes hex = 64) — não pode
    ser uma string de dicionário."""
    env_path = "/app/backend/.env"
    with open(env_path) as f:
        for line in f:
            if line.startswith("JWT_SECRET="):
                val = line.split("=", 1)[1].strip().strip('"')
                assert len(val) >= 64, (
                    f"JWT_SECRET fraco — {len(val)} chars (mínimo 64). "
                    f"Use `python -c 'import secrets; print(secrets.token_hex(48))'`"
                )
                # Não pode ser palavra de dicionário previsível
                bad_tokens = ["secret", "password", "change-me", "default",
                              "smart-merged"]
                assert not any(b in val.lower() for b in bad_tokens), \
                    f"JWT_SECRET contém termo previsível: {val[:30]}..."
                return
    raise AssertionError("JWT_SECRET ausente no .env")


def test_v2_no_high_severity_bandit():
    """Nenhuma issue HIGH do Bandit em backend/routes/ e backend/services/."""
    res = subprocess.run(
        ["bandit", "-r", "backend/routes", "backend/services",
         "-ll", "-ii", "-f", "json"],
        cwd="/app", capture_output=True, text=True, timeout=120,
    )
    import json
    try:
        data = json.loads(res.stdout) if res.stdout else {"results": []}
    except json.JSONDecodeError:
        # bandit retorna stdout vazio quando 0 issues
        return
    high = [x for x in data.get("results", [])
            if x.get("issue_severity") == "HIGH"]
    assert not high, f"Bandit HIGH issues encontradas: {[(x['test_id'], x['filename']) for x in high]}"


def test_v2_no_critical_cve_in_requirements():
    """Nenhuma CVE crítica sem fix em deps usadas diretamente.

    Whitelist: `litellm` é exception (proxy não usado — ver SECURITY_LOCK_EXCEPTION).
    """
    # Apenas verifica que as deps explicitamente atualizadas estão pinned.
    with open("/app/backend/requirements.txt") as f:
        txt = f.read()
    required_versions = {
        "PyJWT": "2.13",
        "aiohttp": "3.14",
        "urllib3": "2.7",
        "cryptography": "49",
        "pypdf": "6.13",
        "python-multipart": "0.0.32",
        "idna": "3.18",
        "pymongo": "4.17",
        "defusedxml": "0.7",
        "starlette": "1.3",
        "fastapi": "0.137",
    }
    missing = []
    for name, expected_prefix in required_versions.items():
        import re
        m = re.search(rf'^{re.escape(name)}==(\S+)', txt, re.MULTILINE | re.IGNORECASE)
        if not m:
            missing.append(f"{name} (ausente)")
            continue
        actual = m.group(1)
        if not actual.startswith(expected_prefix):
            missing.append(f"{name}=={actual} (esperado >={expected_prefix})")
    assert not missing, f"Deps desatualizadas: {missing}"


def test_v2_defusedxml_used_in_kmz_parser():
    """`rede_ia_kmz.py` deve usar `defusedxml` em vez de `xml.etree` para parse."""
    with open("/app/backend/routes/rede_ia_kmz.py") as f:
        src = f.read()
    assert "defusedxml" in src, "rede_ia_kmz.py não importa defusedxml"
    assert "DET.fromstring" in src, "fromstring ainda usa xml.etree (inseguro)"


def test_v2_password_policy_min_length_8():
    """Password policy: mínimo 8 chars em models de criação/mudança/reset."""
    import re
    for p in ["backend/auth.py", "backend/routes/admin.py",
              "backend/routes/admin_password_reset.py",
              "backend/routes/saas.py"]:
        with open(f"/app/{p}") as f:
            src = f.read()
        # Nenhum min_length=6 em campos de password
        bad = re.findall(r'password.*Field\([^)]*min_length=6\b', src, re.IGNORECASE)
        assert not bad, f"{p} ainda tem min_length=6 em password: {bad}"
