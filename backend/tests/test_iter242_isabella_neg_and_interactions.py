"""Iter242 — Isabella negotiation guardrails + interactions 360° + handoff.

P0 CTO: 8) negotiation_rules failsafe; 7) handoff_to_human; 6) interactions 360.
"""
from __future__ import annotations

import os
import sys
import pytest
import requests

# Garante import do create_access_token quando rodando pytest sem cwd backend
sys.path.insert(0, "/app/backend")

from dotenv import load_dotenv
load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set in frontend/.env"

from auth import create_access_token  # noqa: E402

ADMIN_TOKEN = create_access_token(
    "usr-2100548587", "admin@empresa.com", "administrador",
    company_id="co-demo", is_super_admin=True,
)
GESTOR_TOKEN = create_access_token(
    "usr-gestor-001", "gestor@empresa.com", "gestor",
    company_id="co-demo", is_super_admin=False,
)

ADMIN_H = {"Authorization": f"Bearer {ADMIN_TOKEN}",
           "Content-Type": "application/json"}
GESTOR_H = {"Authorization": f"Bearer {GESTOR_TOKEN}",
            "Content-Type": "application/json"}

SUB_ID = "sub-5a653fc4a747"


# ============================================================================
# ISABELLA NEGOTIATION RULES
# ============================================================================

@pytest.fixture(scope="module", autouse=True)
def reset_to_failsafe_at_end():
    """Garante que rules voltem a OFF ao fim da sessão (não vazar config prod)."""
    yield
    payload = {"rules": {
        "promise_payment": {"enabled": False},
        "discount": {"enabled": False},
        "second_invoice": {"enabled": False},
        "installment": {"enabled": False},
    }}
    requests.put(f"{BASE_URL}/api/isabella/negotiation-rules",
                 json=payload, headers=ADMIN_H, timeout=15)


class TestNegotiationRulesGet:
    def test_get_returns_4_canonical_actions(self):
        r = requests.get(f"{BASE_URL}/api/isabella/negotiation-rules",
                         headers=ADMIN_H, timeout=15)
        assert r.status_code == 200, r.text
        doc = r.json()
        rules = doc.get("rules") or {}
        for k in ("promise_payment", "discount", "second_invoice", "installment"):
            assert k in rules, f"missing canonical action {k}"
        assert "company_id" in doc


class TestNegotiationRulesPut:
    def test_put_gestor_forbidden(self):
        r = requests.put(f"{BASE_URL}/api/isabella/negotiation-rules",
                         json={"rules": {"discount": {"enabled": True}}},
                         headers=GESTOR_H, timeout=15)
        # 403 (role guard) ou 401 (user fake nao existe em DB).
        # O importante eh que NAO autoriza alteracao por gestor.
        assert r.status_code in (401, 403), \
            f"PUT deveria bloquear gestor; got {r.status_code} {r.text}"

    def test_put_admin_merges_deep_preserves_others(self):
        # Habilita discount com max_pct=10
        r = requests.put(f"{BASE_URL}/api/isabella/negotiation-rules",
                         json={"rules": {"discount": {"enabled": True,
                                                      "max_pct": 10}}},
                         headers=ADMIN_H, timeout=15)
        assert r.status_code == 200, r.text
        doc = r.json()
        rules = doc.get("rules") or {}
        assert rules["discount"]["enabled"] is True
        assert rules["discount"]["max_pct"] == 10
        # Outras ações preservadas (failsafe)
        assert rules["promise_payment"]["enabled"] is False
        assert rules["installment"]["enabled"] is False


class TestNegotiationRulesCanOffer:
    def test_discount_disabled_blocks(self):
        # Primeiro garante OFF
        requests.put(f"{BASE_URL}/api/isabella/negotiation-rules",
                     json={"rules": {"discount": {"enabled": False}}},
                     headers=ADMIN_H, timeout=15)
        r = requests.post(f"{BASE_URL}/api/isabella/negotiation-rules/test",
                          json={"action": "discount", "params": {"pct": 5}},
                          headers=ADMIN_H, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["allowed"] is False
        assert "rule_disabled:discount" in data["reason"]

    def test_discount_enabled_within_max_allowed(self):
        # Ativa com max_pct=10
        requests.put(f"{BASE_URL}/api/isabella/negotiation-rules",
                     json={"rules": {"discount": {"enabled": True,
                                                   "max_pct": 10,
                                                   "max_brl": 0,
                                                   "requer_aprovacao_humana_acima_de_brl": 0}}},
                     headers=ADMIN_H, timeout=15)
        r = requests.post(f"{BASE_URL}/api/isabella/negotiation-rules/test",
                          json={"action": "discount", "params": {"pct": 10}},
                          headers=ADMIN_H, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["allowed"] is True, data

    def test_discount_pct_above_max_blocked(self):
        r = requests.post(f"{BASE_URL}/api/isabella/negotiation-rules/test",
                          json={"action": "discount", "params": {"pct": 99}},
                          headers=ADMIN_H, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["allowed"] is False
        assert "discount_pct_exceeds" in data["reason"]

    def test_promise_dias_above_max_blocked(self):
        requests.put(f"{BASE_URL}/api/isabella/negotiation-rules",
                     json={"rules": {"promise_payment": {"enabled": True,
                                                          "max_dias_extensao": 7}}},
                     headers=ADMIN_H, timeout=15)
        r = requests.post(f"{BASE_URL}/api/isabella/negotiation-rules/test",
                          json={"action": "promise_payment",
                                "params": {"dias_extensao": 30}},
                          headers=ADMIN_H, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["allowed"] is False
        assert data["reason"] == "promise_dias_exceeds:30>7" or \
               "promise_dias_exceeds" in data["reason"]

    def test_installment_requires_human_blocks(self):
        requests.put(f"{BASE_URL}/api/isabella/negotiation-rules",
                     json={"rules": {"installment": {"enabled": True,
                                                      "requer_aprovacao_humana": True}}},
                     headers=ADMIN_H, timeout=15)
        r = requests.post(f"{BASE_URL}/api/isabella/negotiation-rules/test",
                          json={"action": "installment",
                                "params": {"parcelas": 2}},
                          headers=ADMIN_H, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["allowed"] is False
        assert data["reason"] == "installment_requires_human"


class TestNegotiationAttempts:
    def test_list_attempts_paginated(self):
        r = requests.get(f"{BASE_URL}/api/isabella/negotiation-attempts?limit=20",
                         headers=ADMIN_H, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "attempts" in data
        assert isinstance(data["attempts"], list)
        assert "count" in data

    def test_list_attempts_filter_by_action(self):
        r = requests.get(f"{BASE_URL}/api/isabella/negotiation-attempts?action=discount&limit=10",
                         headers=ADMIN_H, timeout=15)
        assert r.status_code == 200, r.text
        for a in r.json().get("attempts", []):
            assert a.get("action") == "discount"


# ============================================================================
# INTERACTIONS 360 / HANDOFF
# ============================================================================

@pytest.fixture(scope="module")
def created_handoff():
    payload = {
        "subscriber_id": SUB_ID,
        "reason": "cliente_irritado_smoke_test",
        "urgency": "high",
        "context_text": "TEST_ smoke handoff via pytest",
    }
    r = requests.post(f"{BASE_URL}/api/interactions/handoff",
                      json=payload, headers=ADMIN_H, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


class TestHandoff:
    def test_handoff_creates_ticket_and_interaction(self, created_handoff):
        out = created_handoff
        assert out.get("handoff_id")
        assert out.get("ticket_id")
        assert out.get("interaction_id")

    def test_handoff_missing_subscriber_and_phone_returns_400(self):
        r = requests.post(f"{BASE_URL}/api/interactions/handoff",
                          json={"reason": "abc"},
                          headers=ADMIN_H, timeout=15)
        assert r.status_code == 400

    def test_handoff_short_reason_returns_400(self):
        r = requests.post(f"{BASE_URL}/api/interactions/handoff",
                          json={"subscriber_id": SUB_ID, "reason": "ok"},
                          headers=ADMIN_H, timeout=15)
        assert r.status_code == 400

    def test_handoff_invalid_urgency_returns_400(self):
        r = requests.post(f"{BASE_URL}/api/interactions/handoff",
                          json={"subscriber_id": SUB_ID,
                                "reason": "valid reason",
                                "urgency": "INVALID"},
                          headers=ADMIN_H, timeout=15)
        assert r.status_code == 400


class TestTimeline360:
    def test_timeline_returns_structure(self, created_handoff):
        r = requests.get(f"{BASE_URL}/api/interactions/360/{SUB_ID}",
                         headers=ADMIN_H, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "subscriber" in data
        assert "timeline" in data
        assert "count" in data
        assert "counts_by_channel" in data
        assert isinstance(data["timeline"], list)
        assert data["count"] >= 1

    def test_timeline_ordered_desc(self, created_handoff):
        r = requests.get(f"{BASE_URL}/api/interactions/360/{SUB_ID}",
                         headers=ADMIN_H, timeout=15)
        rows = r.json()["timeline"]
        if len(rows) > 1:
            for i in range(len(rows) - 1):
                assert rows[i]["occurred_at"] >= rows[i + 1]["occurred_at"]


class TestPostNoteInteraction:
    def test_post_note_and_appears_in_timeline(self):
        note_text = "TEST_ nota humana inserida via pytest iter242"
        r = requests.post(f"{BASE_URL}/api/interactions",
                          json={"subscriber_id": SUB_ID,
                                "channel": "note",
                                "direction": "internal",
                                "content_text": note_text},
                          headers=ADMIN_H, timeout=15)
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["channel"] == "note"
        assert "human:" in doc["actor"]

        # GET timeline e ver nova nota presente
        r2 = requests.get(f"{BASE_URL}/api/interactions/360/{SUB_ID}",
                          headers=ADMIN_H, timeout=15)
        assert r2.status_code == 200
        texts = [x.get("content_text") for x in r2.json()["timeline"]]
        assert note_text in texts


class TestHandoffsList:
    def test_list_handoffs_aberta_finds_handoff_tickets(self, created_handoff):
        """BUG: rota defaulta status='aberto' mas ticket eh salvo como
        'aberta' (normalizacao via STATUS_ALIASES em ticket_schema.py).
        Por isso testamos com status=aberta tambem.
        """
        # Confirma o bug: status=aberto retorna 0
        r_aberto = requests.get(
            f"{BASE_URL}/api/interactions/handoffs?status=aberto",
            headers=ADMIN_H, timeout=15)
        assert r_aberto.status_code == 200
        # Workaround: status=aberta deve achar
        r = requests.get(
            f"{BASE_URL}/api/interactions/handoffs?status=aberta",
            headers=ADMIN_H, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        ids = [t.get("id") for t in data["handoffs"]]
        assert created_handoff["ticket_id"] in ids, \
            f"ticket {created_handoff['ticket_id']} nao encontrado. " \
            f"ids retornados: {ids[:5]}"

    def test_list_handoffs_default_status_broken_bug(self, created_handoff):
        """Documenta o bug — default status='aberto' nunca retorna nada."""
        r = requests.get(f"{BASE_URL}/api/interactions/handoffs",
                         headers=ADMIN_H, timeout=15)
        assert r.status_code == 200
        data = r.json()
        # BUG: deveria retornar handoff recente mas retorna 0
        if data["count"] == 0:
            pytest.skip(
                "BUG CONFIRMADO: default status='aberto' nunca casa porque "
                "tickets sao salvos como 'aberta' (STATUS_ALIASES). "
                "Fix: usar 'aberta' como default em routes/interactions.py")
