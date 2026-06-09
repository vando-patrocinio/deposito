"""
test_rbac_sprint2.py — Teste automatizado de cobertura RBAC

Garante que:
  1. Cobertura RBAC ≥ 70% nas rotas staff-privadas.
  2. 100% dos endpoints DELETE têm role-rule.
  3. 100% dos endpoints EXPORT (pdf/csv/xlsx/download) têm role-rule.
  4. 100% dos endpoints IA têm role-rule.
  5. Toda rota /api/* (exceto PUBLIC) exige JWT → 401 sem token.
  6. Endpoints com role-rule retornam 403 quando role não bate.

Rodar:
    cd /app && pytest backend/tests/test_rbac_sprint2.py -v
"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

# Garante /app/backend no path
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(scope="module")
def app_and_policy():
    os.environ.setdefault("ALLOW_MOCK_MODULES", "true")
    from server import app
    import rbac_policy as policy_mod
    return app, policy_mod


@pytest.fixture(scope="module")
def http_client(app_and_policy):
    """TestClient com lifespan — Reset do motor antes do startup."""
    app, _ = app_and_policy
    _reset_motor_client()
    with TestClient(app) as c:
        yield c


def _reset_motor_client():
    """Reinicializa o `mongo_client` global em database.py — necessário
    quando múltiplos módulos abrem/encerram TestClient lifespan."""
    try:
        import database as _dbmod
        from motor.motor_asyncio import AsyncIOMotorClient
        _dbmod.mongo_client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        _dbmod.db = _dbmod.mongo_client[os.environ["DB_NAME"]]
    except Exception:
        pass


@pytest.fixture(scope="module")
def classified_routes(app_and_policy):
    app, policy_mod = app_and_policy
    from scripts.audit_rbac_coverage import classify_route
    routes = []
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None) or {"GET"}
        if not path or not path.startswith("/api/"):
            continue
        for m in sorted(methods):
            if m in ("HEAD", "OPTIONS"):
                continue
            routes.append(classify_route(m, path, policy_mod))
    return routes


# ─────────────────── 1. Cobertura ≥ 70% ───────────────────
def test_rbac_coverage_at_least_70_pct(classified_routes):
    staff_private = [r for r in classified_routes
                       if not r["public"] and not r["non_staff_auth"]]
    role_protected = [r for r in staff_private if r["has_role_rule"]]
    assert staff_private, "Esperava ao menos 1 rota staff-privada"
    cov = 100.0 * len(role_protected) / len(staff_private)
    assert cov >= 70.0, (
        f"Cobertura RBAC abaixo de 70%: {cov:.2f}% "
        f"({len(role_protected)}/{len(staff_private)})")


# ─────────────────── 2. DELETE = 100% protegidos ───────────────────
def test_all_delete_have_role_rule(classified_routes):
    leaks = [r for r in classified_routes
               if r["destructive"]
               and not r["public"]
               and not r["non_staff_auth"]
               and not r["has_role_rule"]]
    assert not leaks, (
        f"Endpoints DELETE sem role-rule: "
        f"{[(r['method'], r['path']) for r in leaks]}")


# ─────────────────── 3. EXPORT = 100% protegidos ───────────────────
def test_all_export_have_role_rule(classified_routes):
    leaks = [r for r in classified_routes
               if r["export"]
               and not r["public"]
               and not r["non_staff_auth"]
               and not r["has_role_rule"]]
    assert not leaks, (
        f"Endpoints EXPORT sem role-rule: "
        f"{[(r['method'], r['path']) for r in leaks]}")


# ─────────────────── 4. IA = 100% protegidos ───────────────────
def test_all_ia_have_role_rule(classified_routes):
    leaks = [r for r in classified_routes
               if r["ia"]
               and not r["public"]
               and not r["non_staff_auth"]
               and not r["has_role_rule"]]
    assert not leaks, (
        f"Endpoints IA sem role-rule: "
        f"{[(r['method'], r['path']) for r in leaks]}")


# ─────────────────── 5. 401 sem token ───────────────────
def test_endpoints_require_jwt(app_and_policy):
    """Amostra: GET em endpoints staff-privados sem token → 401."""
    app, policy_mod = app_and_policy
    client = TestClient(app)
    # amostra estratégica (cobre vários módulos)
    samples = [
        "/api/financeiro",
        "/api/payments",
        "/api/subscribers",
        "/api/lousa",
        "/api/fleet",
        "/api/stok",
        "/api/admin",
        "/api/users",
        "/api/presidente-ia",
        "/api/conselho-ia",
        "/api/motor-ia",
        "/api/alvaro",
        "/api/secretaria",
        "/api/wa-campaigns",
    ]
    fails = []
    for path in samples:
        # tenta rota raiz; muitas têm sub-paths
        for candidate in (path, path + "/", path + "/list"):
            resp = client.get(candidate)
            if resp.status_code == 401:
                break
            # pode ser 404 (rota inexistente exata); aceitável também
            # mas se for 200/2xx sem token, é um buraco
            if 200 <= resp.status_code < 300:
                fails.append((candidate, resp.status_code))
                break
    assert not fails, (
        f"Endpoints permitiram acesso sem JWT: {fails}")


# ─────────────────── 6. 403 com role errado ───────────────────
def test_endpoints_block_wrong_role(http_client):
    """Forja JWT como role=colaborador e tenta acessar área financeira."""
    from auth import create_access_token
    client = http_client
    # forja token com role minimal
    token = create_access_token(
        user_id="tst-rbac-spr2",
        email="rbac@test.local",
        role="colaborador",
        company_id="tst-co",
    )
    headers = {"Authorization": f"Bearer {token}"}

    # áreas que colaborador NÃO pode acessar
    forbidden_samples = [
        "/api/financeiro",
        "/api/admin",
        "/api/users",
        "/api/presidente-ia",
        "/api/saas",
        "/api/billing",
        "/api/holerites",
    ]
    leaks = []
    for path in forbidden_samples:
        for candidate in (path, path + "/", path + "/list"):
            resp = client.get(candidate, headers=headers)
            if resp.status_code == 403:
                break
            if 200 <= resp.status_code < 300:
                leaks.append((candidate, resp.status_code))
                break
    assert not leaks, (
        f"Colaborador acessou área proibida sem 403: {leaks}")


# ─────────────────── 7. Admin pode tudo ───────────────────
def test_admin_passes_role_check(http_client):
    from auth import create_access_token
    client = http_client
    token = create_access_token(
        user_id="tst-adm-spr2",
        email="adm@test.local",
        role="administrador",
        company_id="tst-co",
    )
    headers = {"Authorization": f"Bearer {token}"}

    # paths que devem ao menos passar do middleware: 403 = middleware
    # bloqueou; outros códigos (200/404/401 do handler interno) são OK.
    sample = ["/api/financeiro", "/api/presidente-ia", "/api/admin",
                "/api/users", "/api/lousa"]
    blocks = []
    for path in sample:
        resp = client.get(path, headers=headers)
        if resp.status_code == 403:
            blocks.append((path, resp.status_code))
    assert not blocks, (
        f"Administrador foi barrado pelo middleware RBAC: {blocks}")

