"""CTO 13/06/2026 — Regression test pro bug do Jefferson.

Bug PROD: gestor muda profile_id do colaborador pra "Administrador" no
Cadastro, mas o User vinculado (por email, sem collaborator_id) continua
com role=colaborador e profile_id antigo. RBAC bate em /api/propostas
exigindo role∈{gestor,atendimento} → 403 mesmo o admin "tendo dado acesso
total".

Fix: filtro de sync agora considera `email`/`mobile_access_email` além de
`collaborator_id`. E sync também atualiza o legacy `role` quando o perfil
tiver is_super_admin=true ou nome canônico (Administrador/Gestor/etc).
"""
import os
import uuid
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://dual-combine-3.preview.emergentagent.com",
).rstrip("/")
ADMIN = {"email": "admin@empresa.com", "password": "123456"}


@pytest.fixture(scope="module")
def admin_headers():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=20)
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token") or r.json().get("token")
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def mongo():
    cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    yield cli[os.environ.get("DB_NAME", "test_database")]
    cli.close()


@pytest.fixture()
def admin_profile_id(mongo):
    """Acha o profile_id do perfil 'Administrador' em co-demo."""
    p = mongo.access_profiles.find_one(
        {"company_id": "co-demo",
         "$or": [{"is_super_admin": True}, {"name": "Administrador"}]},
        {"id": 1},
    )
    assert p, "Profile 'Administrador' não existe em co-demo"
    return p.get("id")


def test_profile_change_propagates_role_to_user_linked_by_email(
    admin_headers, admin_profile_id, mongo,
):
    """Cenário PROD: collaborator vinculado a user por EMAIL (não por
    collaborator_id). Mudar profile_id do colab pra 'Administrador' tem
    que atualizar role do user para 'administrador'."""
    suffix = uuid.uuid4().hex[:6]
    email = f"jeff_test_{suffix}@example.com"

    # 1) Cria colab SEM passar pelo flow padrão de criação de user
    cpf_raw = uuid.uuid4().int % 10**11
    cpf = str(cpf_raw).zfill(11)
    payload = {
        "name": f"JEFF_TEST_{suffix}",
        "cpf": cpf,
        "email": email,
        "phone": "11999990001",
        "role": "Técnico (Atlaz)",  # esse é o campo legado de exibição do colab
        "cargo": "tecnico",
        "company": "Operação SP",
        "mobile_access_email": email,
    }
    r = requests.post(
        f"{BASE_URL}/api/collaborators", json=payload,
        headers=admin_headers, timeout=20,
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]

    # 2) Cria User vinculado APENAS por email (collaborator_id=null) —
    # simula um user pré-existente que veio antes do colab ser cadastrado.
    user_id = f"usr-test-{suffix}"
    mongo.users.insert_one({
        "id": user_id,
        "email": email,
        "name": f"JEFF_TEST_{suffix}",
        "role": "colaborador",
        "profile_id": None,
        "collaborator_id": None,  # <-- NULL de propósito (bug PROD)
        "company_id": "co-demo",
        "active": True,
        "password_hash": "$2b$12$dummy",
        "created_at": "2026-06-13T00:00:00+00:00",
        "updated_at": "2026-06-13T00:00:00+00:00",
    })

    try:
        # 3) Confirma estado inicial
        u = mongo.users.find_one({"id": user_id}, {"_id": 0, "role": 1, "profile_id": 1})
        assert u["role"] == "colaborador", "setup falhou"
        assert u["profile_id"] is None, "setup falhou"

        # 4) Gestor muda profile_id do colab pra 'Administrador'
        body = {**payload, "profile_id": admin_profile_id}
        r = requests.put(
            f"{BASE_URL}/api/collaborators/{cid}", json=body,
            headers=admin_headers, timeout=20,
        )
        assert r.status_code == 200, r.text

        # 5) User vinculado por email DEVE ter pegado o novo profile_id E role
        u2 = mongo.users.find_one(
            {"id": user_id},
            {"_id": 0, "role": 1, "profile_id": 1, "access_tags": 1},
        )
        assert u2["profile_id"] == admin_profile_id, (
            f"profile_id NÃO foi propagado: user.profile_id={u2.get('profile_id')}"
        )
        assert u2["role"] == "administrador", (
            f"role legado NÃO foi atualizado: user.role={u2.get('role')} "
            "(esperado 'administrador' porque profile=Administrador)"
        )
        assert "propostas" in (u2.get("access_tags") or []), (
            "access_tags NÃO foi propagado"
        )
    finally:
        mongo.users.delete_one({"id": user_id})
        requests.delete(
            f"{BASE_URL}/api/collaborators/{cid}",
            headers=admin_headers, timeout=20,
        )


def test_profile_change_propagates_to_user_linked_by_collaborator_id(
    admin_headers, admin_profile_id, mongo,
):
    """Caminho feliz não regrediu: user com collaborator_id explícito
    continua sendo sincronizado normalmente."""
    suffix = uuid.uuid4().hex[:6]
    email = f"jeff_link_{suffix}@example.com"
    cpf_raw = uuid.uuid4().int % 10**11
    cpf = str(cpf_raw).zfill(11)
    payload = {
        "name": f"JEFFLINK_{suffix}", "cpf": cpf, "email": email,
        "phone": "11999990002", "role": "Técnico (Atlaz)",
        "cargo": "tecnico", "company": "Operação SP",
    }
    r = requests.post(
        f"{BASE_URL}/api/collaborators", json=payload,
        headers=admin_headers, timeout=20,
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]

    user_id = f"usr-link-{suffix}"
    mongo.users.insert_one({
        "id": user_id, "email": f"other_{suffix}@example.com",
        "name": f"JEFFLINK_{suffix}", "role": "colaborador",
        "profile_id": None, "collaborator_id": cid,  # vínculo EXPLÍCITO
        "company_id": "co-demo", "active": True,
        "password_hash": "$2b$12$dummy",
        "created_at": "2026-06-13T00:00:00+00:00",
        "updated_at": "2026-06-13T00:00:00+00:00",
    })

    try:
        body = {**payload, "profile_id": admin_profile_id}
        r = requests.put(
            f"{BASE_URL}/api/collaborators/{cid}", json=body,
            headers=admin_headers, timeout=20,
        )
        assert r.status_code == 200, r.text

        u = mongo.users.find_one(
            {"id": user_id},
            {"_id": 0, "role": 1, "profile_id": 1},
        )
        assert u["profile_id"] == admin_profile_id
        assert u["role"] == "administrador"
    finally:
        mongo.users.delete_one({"id": user_id})
        requests.delete(
            f"{BASE_URL}/api/collaborators/{cid}",
            headers=admin_headers, timeout=20,
        )
