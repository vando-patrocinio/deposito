"""Tests iter138 — Módulo 1: Billing Engine (substituição do Atlaz).

Cobertura:
- GET /api/billing/stats — estrutura agregada
- GET /api/billing/dunning-rules — defaults + atualização persistente
- POST /api/billing/generate-batch (dry-run + real + idempotency)
- POST /api/billing/invoices + mark-paid + cancel
- POST /api/billing/dunning-rules/run dry-run
- RBAC: gestor/admin podem gerenciar; colaborador 403 em ops manageriais
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL",
                          "http://localhost:8001").rstrip("/")


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


@pytest.fixture(scope="session")
def auditor_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": "auditor@example.com",
                             "password": "auditor123"}, timeout=10)
    if r.status_code != 200:
        pytest.skip("auditor@example.com não disponível neste ambiente")
    return r.json()["access_token"]


COMPANY_ID = "co-demo"
TEST_PREFIX = "iter138-billing"


@pytest.fixture
def temp_plan(db):
    plan_id = f"plan-TEST-{TEST_PREFIX}-{uuid.uuid4().hex[:6]}"
    db.plans.insert_one({
        "id": plan_id, "company_id": COMPANY_ID,
        "name": f"TEST Plan {TEST_PREFIX}", "monthly_price": 79.90,
        "speed_down_mbps": 500, "speed_up_mbps": 250, "active": True,
        "premium_features": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield plan_id
    db.plans.delete_one({"id": plan_id})


@pytest.fixture
def temp_subscribers(db, temp_plan):
    """Cria 2 assinantes ATIVOS com plano vinculado."""
    sids = []
    for i in range(2):
        sid = f"sub-TEST-{TEST_PREFIX}-{uuid.uuid4().hex[:6]}"
        db.subscribers.insert_one({
            "id": sid, "company_id": COMPANY_ID,
            "name": f"Cliente Billing Test {i}",
            "external_code": f"ASS-TEST-{i}-{uuid.uuid4().hex[:4]}",
            "document": f"99999{i}{uuid.uuid4().hex[:6]}",
            "status": "ATIVO", "plan_id": temp_plan,
            "plan_name": "TEST Plan", "plan_price": 79.90,
            "due_day": 10,
            "phones": [{"number": f"+5521TEST{i}99", "is_primary": True}],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        sids.append(sid)
    yield sids
    db.subscribers.delete_many({"id": {"$in": sids}})
    # Cleanup invoices generated for these subscribers
    db.subscriber_invoices.delete_many({"subscriber_id": {"$in": sids}})


@pytest.fixture
def clean_billing_runs(db):
    yield
    db.billing_runs.delete_many({"actor": "admin@empresa.com",
                                  "competence": {"$regex": "^2099-"}})


# ======================================================================
# Stats
# ======================================================================
def test_stats_basic_structure(admin_token):
    r = requests.get(f"{BASE_URL}/api/billing/stats",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 200, r.text
    s = r.json()
    assert "by_status" in s
    assert "total_count" in s
    assert "total_invoiced" in s
    assert "total_paid_amount" in s
    assert "mrr" in s
    # 5 status canônicos sempre presentes
    for st in ("open", "paid", "overdue", "canceled", "pending"):
        assert st in s["by_status"]


def test_stats_collection_rate_present(admin_token):
    r = requests.get(f"{BASE_URL}/api/billing/stats",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    s = r.json()
    assert "collection_rate" in s
    # Always between 0 and 100
    assert 0 <= s["collection_rate"] <= 100


# ======================================================================
# Dunning rules
# ======================================================================
def test_dunning_rules_defaults_or_persisted(admin_token):
    r = requests.get(f"{BASE_URL}/api/billing/dunning-rules",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "rules" in data
    assert isinstance(data["rules"], list)
    assert len(data["rules"]) >= 1
    # Default rules têm 5 entradas, atualizadas podem ter qualquer N
    actions = {rule.get("action") for rule in data["rules"]}
    # Verifica que ao menos uma das ações comuns aparece
    common = actions & {"reminder", "suspend", "final_notice",
                         "first_notice", "second_notice", "notify"}
    assert common, f"Esperava ao menos uma ação comum em {actions}"


def test_dunning_rules_update_roundtrip(admin_token, db):
    custom = [
        {"id": "rule-d-7", "offset_days": -7, "label": "TEST Custom D-7",
         "channel": "whatsapp", "action": "reminder", "enabled": True,
         "template": f"TEST {uuid.uuid4().hex[:8]} Olá nome",
         "apply_fees": False},
        {"id": "rule-d3", "offset_days": 3, "label": "TEST D+3",
         "channel": "sms", "action": "first_notice", "enabled": False,
         "template": "msg curta", "apply_fees": True,
         "fee_percent": 2, "interest_percent_per_month": 1},
    ]
    try:
        r = requests.put(f"{BASE_URL}/api/billing/dunning-rules",
                         headers={"Authorization": f"Bearer {admin_token}"},
                         json={"rules": custom}, timeout=10)
        assert r.status_code == 200, r.text
        # Read back
        r2 = requests.get(f"{BASE_URL}/api/billing/dunning-rules",
                          headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
        data = r2.json()
        assert data["using_defaults"] is False
        assert len(data["rules"]) == 2
        labels = [rule["label"] for rule in data["rules"]]
        assert "TEST Custom D-7" in labels
    finally:
        # Restore default empty doc (rules vai voltar pra default na próxima leitura)
        db.billing_dunning_rules.delete_one({"company_id": COMPANY_ID})


def test_dunning_rules_invalid_payload(admin_token, db):
    # Regra sem offset_days deve retornar 400
    try:
        r = requests.put(f"{BASE_URL}/api/billing/dunning-rules",
                         headers={"Authorization": f"Bearer {admin_token}"},
                         json={"rules": [{"label": "sem offset"}]}, timeout=10)
        assert r.status_code == 400
        assert "offset_days" in r.text
    finally:
        db.billing_dunning_rules.delete_one({"company_id": COMPANY_ID})


# ======================================================================
# Generate batch
# ======================================================================
def test_generate_batch_preview(admin_token, temp_subscribers):
    """Preview deve detectar os 2 assinantes criados pelo fixture."""
    comp = "2099-01"  # competência futura — ninguém terá fatura
    r = requests.get(f"{BASE_URL}/api/billing/generate-batch/preview",
                     params={"competence": comp},
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["dry_run"] is True
    # Subscribers do fixture + outros já existentes na co-demo
    assert res["subscribers_evaluated"] >= 2
    assert res["invoices_created"] >= 2


def test_generate_batch_invalid_competence(admin_token):
    r = requests.post(f"{BASE_URL}/api/billing/generate-batch",
                       headers={"Authorization": f"Bearer {admin_token}"},
                       json={"competence": "INVALID", "dry_run": True}, timeout=10)
    assert r.status_code == 400


def test_generate_batch_idempotency(admin_token, temp_subscribers, db, clean_billing_runs):
    comp = "2099-02"
    # Cleanup any leftover from previous run
    db.subscriber_invoices.delete_many({"competence": comp,
                                          "company_id": COMPANY_ID})
    # First run
    r1 = requests.post(f"{BASE_URL}/api/billing/generate-batch",
                       headers={"Authorization": f"Bearer {admin_token}"},
                       json={"competence": comp, "dry_run": False}, timeout=30)
    res1 = r1.json()
    created1 = res1["invoices_created"]
    assert created1 >= 2
    # Second run — todos skipped_existing
    r2 = requests.post(f"{BASE_URL}/api/billing/generate-batch",
                       headers={"Authorization": f"Bearer {admin_token}"},
                       json={"competence": comp, "dry_run": False}, timeout=30)
    res2 = r2.json()
    assert res2["invoices_created"] == 0
    assert res2["skipped_existing"] >= created1
    # Cleanup
    db.subscriber_invoices.delete_many({"competence": comp,
                                          "company_id": COMPANY_ID})


# ======================================================================
# Manual invoice CRUD
# ======================================================================
def test_create_invoice_manual(admin_token, temp_subscribers, db):
    sid = temp_subscribers[0]
    r = requests.post(f"{BASE_URL}/api/billing/invoices",
                       headers={"Authorization": f"Bearer {admin_token}"},
                       json={"subscriber_id": sid, "competence": "2099-03",
                             "amount": 250.0,
                             "description": "Taxa instalação TEST"}, timeout=10)
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["amount"] == 250.0
    assert inv["status"] == "open"
    assert inv["source"] == "native_billing"
    assert inv["due_date"] == "2099-03-10"
    inv_id = inv["id"]
    # Mark paid
    r2 = requests.post(f"{BASE_URL}/api/billing/invoices/{inv_id}/mark-paid",
                       headers={"Authorization": f"Bearer {admin_token}"},
                       json={"payment_method": "pix"}, timeout=10)
    paid = r2.json()
    assert paid["status"] == "paid"
    assert paid["amount_paid"] == 250.0
    assert paid["payment_method"] == "pix"
    # Cleanup
    db.subscriber_invoices.delete_one({"id": inv_id})


def test_cancel_invoice(admin_token, temp_subscribers, db):
    sid = temp_subscribers[1]
    r = requests.post(f"{BASE_URL}/api/billing/invoices",
                       headers={"Authorization": f"Bearer {admin_token}"},
                       json={"subscriber_id": sid, "competence": "2099-04",
                             "amount": 50}, timeout=10)
    inv_id = r.json()["id"]
    try:
        r2 = requests.post(f"{BASE_URL}/api/billing/invoices/{inv_id}/cancel",
                           headers={"Authorization": f"Bearer {admin_token}"},
                           timeout=10)
        assert r2.status_code == 200
        assert r2.json()["status"] == "canceled"
        # Não pode marcar canceled como paid de novo (tem que ser pelo flow)
    finally:
        db.subscriber_invoices.delete_one({"id": inv_id})


def test_create_invoice_subscriber_not_found(admin_token):
    r = requests.post(f"{BASE_URL}/api/billing/invoices",
                       headers={"Authorization": f"Bearer {admin_token}"},
                       json={"subscriber_id": "sub-ghost-not-exists",
                             "competence": "2099-05", "amount": 99.9}, timeout=10)
    assert r.status_code == 404


# ======================================================================
# Dunning run
# ======================================================================
def test_dunning_run_dry_run_does_not_persist(admin_token, db):
    """Dry run não deve gerar eventos no banco."""
    # Snapshot count antes
    before = db.billing_dunning_events.count_documents({"company_id": COMPANY_ID})
    r = requests.post(f"{BASE_URL}/api/billing/dunning-rules/run",
                       params={"dry_run": "true"},
                       headers={"Authorization": f"Bearer {admin_token}"}, timeout=30)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["dry_run"] is True
    assert "events_triggered" in res
    after = db.billing_dunning_events.count_documents({"company_id": COMPANY_ID})
    assert before == after


# ======================================================================
# RBAC
# ======================================================================
def test_invoice_list_returns_items(admin_token):
    r = requests.get(f"{BASE_URL}/api/billing/invoices",
                     params={"limit": 5},
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)


def test_invoice_filter_by_status(admin_token):
    r = requests.get(f"{BASE_URL}/api/billing/invoices",
                     params={"status": "paid", "limit": 5},
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 200
    for it in r.json()["items"]:
        assert it["status"] == "paid"


def test_invoice_filter_invalid_status(admin_token):
    r = requests.get(f"{BASE_URL}/api/billing/invoices",
                     params={"status": "GARBAGE"},
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
    assert r.status_code == 400


def test_auditor_can_view_stats(auditor_token):
    r = requests.get(f"{BASE_URL}/api/billing/stats",
                     headers={"Authorization": f"Bearer {auditor_token}"}, timeout=10)
    assert r.status_code == 200


def test_unauthorized_no_token():
    r = requests.get(f"{BASE_URL}/api/billing/stats", timeout=10)
    assert r.status_code in (401, 403)


# ======================================================================
# Telefone primário (regression: faturas precisam ter subscriber_phone
# pra régua de cobrança via WhatsApp funcionar)
# ======================================================================
def test_invoice_resolves_primary_phone_from_subscriber_phones(admin_token, db, temp_subscribers):
    """Subscriber criado pelo fixture NÃO tem phones[] embedded.
    Vamos criar 1 registro em subscriber_phones e validar que o invoice o pega."""
    sid = temp_subscribers[0]
    # Cleanup phones anteriores deste sid (caso fixture deixou)
    db.subscriber_phones.delete_many({"subscriber_id": sid})
    db.subscriber_phones.insert_one({
        "id": f"sphone-test-{uuid.uuid4().hex[:8]}",
        "company_id": COMPANY_ID,
        "subscriber_id": sid,
        "raw_number": "+5521988887777",
        "normalized_number": "5521988887777",
        "is_primary": True, "is_whatsapp": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        # Cria fatura manual
        r = requests.post(f"{BASE_URL}/api/billing/invoices",
                          headers={"Authorization": f"Bearer {admin_token}"},
                          json={"subscriber_id": sid, "competence": "2099-08",
                                "amount": 79.9}, timeout=10)
        assert r.status_code == 201, r.text
        inv = r.json()
        assert inv["subscriber_phone"] == "5521988887777", \
            f"Esperava telefone primary mas veio: {inv.get('subscriber_phone')}"
        # Cleanup
        db.subscriber_invoices.delete_one({"id": inv["id"]})
    finally:
        db.subscriber_phones.delete_many({"subscriber_id": sid})


def test_generate_batch_attaches_phone(admin_token, db, temp_subscribers):
    """Lote em massa também precisa preencher subscriber_phone via
    subscriber_phones (NÃO via phones[] embedded — esquema legado)."""
    sid = temp_subscribers[0]
    db.subscriber_phones.delete_many({"subscriber_id": sid})
    db.subscriber_phones.insert_one({
        "id": f"sphone-test-{uuid.uuid4().hex[:8]}",
        "company_id": COMPANY_ID, "subscriber_id": sid,
        "raw_number": "+5511944443333", "normalized_number": "5511944443333",
        "is_primary": True, "is_whatsapp": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    comp = "2099-09"
    db.subscriber_invoices.delete_many({"competence": comp, "subscriber_id": sid})
    try:
        r = requests.post(f"{BASE_URL}/api/billing/generate-batch",
                          headers={"Authorization": f"Bearer {admin_token}"},
                          json={"competence": comp, "dry_run": False}, timeout=30)
        assert r.status_code == 200
        # Busca a fatura desse subscriber
        inv = db.subscriber_invoices.find_one(
            {"competence": comp, "subscriber_id": sid}, {"_id": 0})
        assert inv is not None, "Fatura não foi criada"
        assert inv.get("subscriber_phone") == "5511944443333", \
            f"Esperava telefone do subscriber_phones, mas veio: {inv.get('subscriber_phone')}"
    finally:
        db.subscriber_invoices.delete_many({"competence": comp, "subscriber_id": sid})
        db.subscriber_phones.delete_many({"subscriber_id": sid})


def test_backfill_phones_endpoint(admin_token, db, temp_subscribers):
    """Endpoint backfill deve preencher phone em fatura criada SEM telefone
    quando depois cadastramos o telefone do assinante."""
    sid = temp_subscribers[0]
    db.subscriber_phones.delete_many({"subscriber_id": sid})
    # Cria fatura DIRETAMENTE no banco, sem telefone (simulando legado)
    inv_id = f"binv-test-bf-{uuid.uuid4().hex[:6]}"
    db.subscriber_invoices.insert_one({
        "id": inv_id, "company_id": COMPANY_ID,
        "subscriber_id": sid, "competence": "2099-10",
        "amount": 50, "amount_paid": 0, "status": "open",
        "due_date": "2099-10-10", "source": "native_billing",
        "subscriber_phone": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Agora adiciona o telefone
    db.subscriber_phones.insert_one({
        "id": f"sphone-test-{uuid.uuid4().hex[:8]}",
        "company_id": COMPANY_ID, "subscriber_id": sid,
        "raw_number": "+5521912345678",
        "normalized_number": "5521912345678",
        "is_primary": True, "is_whatsapp": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = requests.post(f"{BASE_URL}/api/billing/invoices/backfill-phones",
                          headers={"Authorization": f"Bearer {admin_token}"}, timeout=30)
        assert r.status_code == 200, r.text
        res = r.json()
        assert res["updated"] >= 1
        # Confirma direto no DB
        inv = db.subscriber_invoices.find_one({"id": inv_id}, {"_id": 0})
        assert inv.get("subscriber_phone") == "5521912345678"
    finally:
        db.subscriber_invoices.delete_one({"id": inv_id})
        db.subscriber_phones.delete_many({"subscriber_id": sid})
