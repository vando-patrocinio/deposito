from __future__ import annotations
"""Iteration 118 — Wi-Fi self-service via SmartOLT TR-069.

Cobre todos os gates pedidos pela review_request: status, link/unlink,
auto-match, change com matriz (no_onu/premium_required/onu_offline/
rate_limited/source=atendente bypass/tr069_failed→502 com log gravado),
logs, reboot-onu, validações de SSID/senha, RBAC colaborador 403,
auditoria (`wifi_change_logs`) e notificação (`notifications`).

Pré-requisito de ambiente:
  - tenant co-demo, subscriber premium sub-91c01c46fc (Maria José Silva)
    vinculado à ONU 4954425332697d69 (Online), plano plan-1b0578d85d
    (Fibra 1 Giga com premium_features=['wifi_self_service']).
"""

import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _test_secrets import TEST_ADMIN_PASSWORD, TEST_AUDITOR_PASSWORD  # noqa: E402
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pathlib import Path
from pymongo import MongoClient


def _load_env_file(path: str) -> dict:
    out: dict = {}
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return out


_fe_env = _load_env_file("/app/frontend/.env")
_be_env = _load_env_file("/app/backend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or _fe_env.get("REACT_APP_BACKEND_URL")).rstrip("/")
MONGO_URL = (os.environ.get("MONGO_URL")
             or _be_env.get("MONGO_URL")
             or "mongodb://localhost:27017")
DB_NAME = (os.environ.get("DB_NAME")
           or _be_env.get("DB_NAME")
           or "test_database")

# Fixos do tenant co-demo (vide review_request)
PREMIUM_SID = "sub-91c01c46fc"
PREMIUM_PLAN_ID = "plan-1b0578d85d"
PREMIUM_ONU_ID = "4954425332697d69"
OTHER_ONU_ID = "HWTC792DFCB1"  # Online
NO_ONU_SID = "sub-c1a6d684e0"  # Vando Patrocinio (sem ONU)
NON_PREMIUM_PLAN_ID = "plan-7e2605ff7d"  # Fibra 300 Mega (sem premium_features)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def mongo():
    return MongoClient(MONGO_URL)[DB_NAME]


def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password},
                      timeout=15)
    if r.status_code != 200:
        pytest.skip(f"Login falhou {email}: {r.status_code} {r.text[:200]}")
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def tok_super():
    return _login("admin@empresa.com", "123456")


@pytest.fixture(scope="session")
def tok_atendente():
    return _login("auditor@example.com", TEST_AUDITOR_PASSWORD)


@pytest.fixture(scope="session")
def tok_colab():
    return _login("colaborador@empresa.com", "123456")


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(autouse=True)
def _reset_circuit_breaker(mongo):
    """Garante SmartOLT sem rate_limited_until antes de cada teste que faz
    chamada real ao TR-069. O 502 esperado dispara o circuit-breaker que
    persistiria entre testes."""
    mongo.smartolt_config.update_one(
        {"company_id": "co-demo"},
        {"$unset": {"rate_limited_until": ""}},
    )
    yield


@pytest.fixture
def clean_wifi_logs(mongo):
    """Remove logs e notifications criadas no teste, garantindo isolamento
    pro rate-limit test."""
    mongo.wifi_change_logs.delete_many({"company_id": "co-demo",
                                        "subscriber_id": PREMIUM_SID})
    mongo.notifications.delete_many({"company_id": "co-demo",
                                     "type": "wifi_change",
                                     "subscriber_id": PREMIUM_SID})
    yield
    mongo.wifi_change_logs.delete_many({"company_id": "co-demo",
                                        "subscriber_id": PREMIUM_SID})
    mongo.notifications.delete_many({"company_id": "co-demo",
                                     "type": "wifi_change",
                                     "subscriber_id": PREMIUM_SID})


@pytest.fixture
def ensure_premium_link(mongo):
    """Garante que o subscriber premium continua vinculado à ONU correta."""
    mongo.subscribers.update_one(
        {"id": PREMIUM_SID, "company_id": "co-demo"},
        {"$set": {"smartolt_onu_id": PREMIUM_ONU_ID,
                  "plan_id": PREMIUM_PLAN_ID}},
    )
    yield
    mongo.subscribers.update_one(
        {"id": PREMIUM_SID, "company_id": "co-demo"},
        {"$set": {"smartolt_onu_id": PREMIUM_ONU_ID,
                  "plan_id": PREMIUM_PLAN_ID}},
    )


# ---------------------------------------------------------------------------
# 1) STATUS — vários estados
# ---------------------------------------------------------------------------
class TestStatus:
    def test_status_ready(self, tok_atendente, ensure_premium_link, clean_wifi_logs):
        r = requests.get(f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/status",
                         headers=_h(tok_atendente), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["plan_premium"] is True
        assert d["smartolt_onu_id"] == PREMIUM_ONU_ID
        assert d["onu"]["is_online"] is True
        assert d["state"] == "ready"

    def test_status_no_onu(self, tok_atendente):
        r = requests.get(f"{BASE_URL}/api/wifi/subscriber/{NO_ONU_SID}/status",
                         headers=_h(tok_atendente), timeout=15)
        assert r.status_code == 200
        assert r.json()["state"] == "no_onu"

    def test_status_premium_required(self, tok_atendente, mongo,
                                     ensure_premium_link):
        # Temporariamente troca o plano para não-premium
        mongo.subscribers.update_one(
            {"id": PREMIUM_SID, "company_id": "co-demo"},
            {"$set": {"plan_id": NON_PREMIUM_PLAN_ID}})
        try:
            r = requests.get(
                f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/status",
                headers=_h(tok_atendente), timeout=15)
            assert r.status_code == 200
            assert r.json()["state"] == "premium_required"
        finally:
            mongo.subscribers.update_one(
                {"id": PREMIUM_SID, "company_id": "co-demo"},
                {"$set": {"plan_id": PREMIUM_PLAN_ID}})

    def test_status_subscriber_not_found(self, tok_atendente):
        r = requests.get(f"{BASE_URL}/api/wifi/subscriber/sub-nope-xxx/status",
                         headers=_h(tok_atendente), timeout=15)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 2) LINK / UNLINK / AUTO-MATCH
# ---------------------------------------------------------------------------
class TestLinkOnu:
    def test_link_exclusivity_displaces_prior(self, tok_atendente, mongo,
                                              ensure_premium_link):
        """Vincular ONU que pertence a outro subscriber displaça o antigo."""
        # NO_ONU_SID recebe a ONU que estava no PREMIUM_SID
        r = requests.post(
            f"{BASE_URL}/api/wifi/subscriber/{NO_ONU_SID}/link-onu",
            headers=_h(tok_atendente),
            json={"smartolt_onu_id": PREMIUM_ONU_ID},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["smartolt_onu_id"] == PREMIUM_ONU_ID
        # Tem que vir o displaced_prior_subscriber preenchido com PREMIUM_SID
        prior = data.get("displaced_prior_subscriber")
        assert prior is not None and prior.get("id") == PREMIUM_SID
        # E o PREMIUM_SID deve ter ficado sem ONU no DB
        sub = mongo.subscribers.find_one({"id": PREMIUM_SID,
                                          "company_id": "co-demo"})
        assert not sub.get("smartolt_onu_id")
        # Cleanup: restaura
        mongo.subscribers.update_one(
            {"id": NO_ONU_SID, "company_id": "co-demo"},
            {"$unset": {"smartolt_onu_id": ""}})
        mongo.subscribers.update_one(
            {"id": PREMIUM_SID, "company_id": "co-demo"},
            {"$set": {"smartolt_onu_id": PREMIUM_ONU_ID}})

    def test_unlink(self, tok_atendente, mongo, ensure_premium_link):
        r = requests.delete(
            f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/link-onu",
            headers=_h(tok_atendente), timeout=15)
        assert r.status_code == 200
        assert r.json()["previous_onu_id"] == PREMIUM_ONU_ID

    def test_link_nonexistent_onu(self, tok_atendente):
        r = requests.post(
            f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/link-onu",
            headers=_h(tok_atendente),
            json={"smartolt_onu_id": "DOES-NOT-EXIST-9999"},
            timeout=15)
        assert r.status_code == 404


class TestAutoMatch:
    def test_auto_match_no_match(self, tok_atendente, mongo):
        # NO_ONU_SID (Vando) — provavelmente não tem ONU com name_norm
        # equivalente. Aceita {ok:false, reason:no_match}.
        r = requests.post(
            f"{BASE_URL}/api/wifi/subscriber/{NO_ONU_SID}/auto-match",
            headers=_h(tok_atendente), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        # Pode dar match (se houver name colidindo) — só validamos a forma.
        assert "ok" in data
        if not data["ok"]:
            assert data["reason"] == "no_match"
            assert isinstance(data.get("tried_candidates"), list)


# ---------------------------------------------------------------------------
# 3) CHANGE — gates
# ---------------------------------------------------------------------------
class TestChangeGates:
    def test_change_no_onu_409(self, tok_atendente):
        r = requests.post(
            f"{BASE_URL}/api/wifi/subscriber/{NO_ONU_SID}/change",
            headers=_h(tok_atendente),
            json={"ssid_24": "TEST_NoOnu"},
            timeout=15)
        assert r.status_code == 409

    def test_change_non_premium_402(self, tok_atendente, mongo,
                                    ensure_premium_link):
        mongo.subscribers.update_one(
            {"id": PREMIUM_SID, "company_id": "co-demo"},
            {"$set": {"plan_id": NON_PREMIUM_PLAN_ID}})
        try:
            r = requests.post(
                f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/change",
                headers=_h(tok_atendente),
                json={"ssid_24": "TEST_NonPrem", "password_24": "abcd1234"},
                timeout=15)
            assert r.status_code == 402, r.text
            detail = r.json().get("detail")
            assert isinstance(detail, dict)
            assert detail.get("code") == "PREMIUM_REQUIRED"
        finally:
            mongo.subscribers.update_one(
                {"id": PREMIUM_SID, "company_id": "co-demo"},
                {"$set": {"plan_id": PREMIUM_PLAN_ID}})

    def test_change_onu_offline_409(self, tok_atendente, mongo,
                                    ensure_premium_link):
        # Marca ONU como offline temporariamente
        mongo.smartolt_onus.update_one(
            {"company_id": "co-demo", "unique_external_id": PREMIUM_ONU_ID},
            {"$set": {"status": "Offline"}})
        try:
            r = requests.post(
                f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/change",
                headers=_h(tok_atendente),
                json={"ssid_24": "TEST_Offline", "password_24": "abcd1234"},
                timeout=15)
            assert r.status_code == 409, r.text
            detail = r.json().get("detail")
            assert isinstance(detail, dict)
            assert detail.get("code") == "ONU_OFFLINE"
        finally:
            mongo.smartolt_onus.update_one(
                {"company_id": "co-demo",
                 "unique_external_id": PREMIUM_ONU_ID},
                {"$set": {"status": "Online"}})

    def test_change_invalid_ssid_non_ascii(self, tok_atendente,
                                           ensure_premium_link):
        r = requests.post(
            f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/change",
            headers=_h(tok_atendente),
            json={"ssid_24": "Café_Wifi_🚀", "password_24": "abcd1234"},
            timeout=15)
        assert r.status_code == 400

    def test_change_password_too_short_422(self, tok_atendente,
                                           ensure_premium_link):
        r = requests.post(
            f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/change",
            headers=_h(tok_atendente),
            json={"ssid_24": "TEST_OK", "password_24": "short"},
            timeout=15)
        # Pydantic min_length=8 → 422
        assert r.status_code == 422

    def test_change_password_too_long_422(self, tok_atendente,
                                          ensure_premium_link):
        r = requests.post(
            f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/change",
            headers=_h(tok_atendente),
            json={"ssid_24": "TEST_OK",
                  "password_24": "a" * 64},
            timeout=15)
        assert r.status_code == 422


class TestChangeTR069:
    """O SmartOLT real vai retornar 403/405 (TR-069 desabilitado), portanto
    esperamos 502 TR069_FAILED — MAS um log de auditoria DEVE estar gravado
    com success=false + error_reason."""

    def test_change_atendente_502_with_audit_log(self, tok_atendente, mongo,
                                                 ensure_premium_link,
                                                 clean_wifi_logs):
        r = requests.post(
            f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/change",
            headers=_h(tok_atendente),
            json={"ssid_24": "TEST_Atendente", "password_24": "abcd1234",
                  "source": "atendente"},
            timeout=30)
        # Esperado: 502 TR069_FAILED (sem TR-069 hab no SmartOLT real). Caso
        # a infra mude e funcione, aceitamos 200 também.
        assert r.status_code in (200, 502), r.text
        if r.status_code == 502:
            detail = r.json().get("detail")
            assert isinstance(detail, dict)
            assert detail.get("code") == "TR069_FAILED"
            assert detail.get("reason")  # error_reason populado
        # Audit log foi gravado (success match com http)
        logs = list(mongo.wifi_change_logs.find(
            {"subscriber_id": PREMIUM_SID, "company_id": "co-demo"}))
        assert len(logs) >= 1
        log = logs[0]
        assert log["source"] == "atendente"
        assert log["actor_email"] == "auditor@example.com"
        assert log["smartolt_onu_id"] == PREMIUM_ONU_ID
        assert log["password_changed"] is True
        assert "tr069_response_time_ms" in log
        if r.status_code == 502:
            assert log["success"] is False
            assert log.get("error_reason")
        # Notification gravada
        notif = mongo.notifications.find_one(
            {"company_id": "co-demo", "type": "wifi_change",
             "subscriber_id": PREMIUM_SID})
        assert notif is not None
        assert notif["severity"] in ("info", "warning")

    def test_change_force_only_for_atendente(self, tok_atendente,
                                             ensure_premium_link,
                                             clean_wifi_logs):
        """force=True com source != atendente → 403."""
        r = requests.post(
            f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/change",
            headers=_h(tok_atendente),
            json={"ssid_24": "TEST_ForceNo", "password_24": "abcd1234",
                  "source": "whatsapp_alvaro", "force": True},
            timeout=15)
        assert r.status_code == 403

    def test_change_rate_limit_whatsapp(self, tok_atendente, mongo,
                                       ensure_premium_link,
                                       _reset_circuit_breaker=None):
        """Seeda 1 sucesso recente no wifi_change_logs e tenta segunda troca
        via source=whatsapp_alvaro → 429."""
        # Limpa logs antes
        mongo.wifi_change_logs.delete_many(
            {"subscriber_id": PREMIUM_SID, "company_id": "co-demo"})
        # Insere 1 log de sucesso whatsapp_alvaro recente
        mongo.wifi_change_logs.insert_one({
            "id": "wfl-seed-iter118",
            "company_id": "co-demo",
            "subscriber_id": PREMIUM_SID,
            "source": "whatsapp_alvaro",
            "success": True,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        try:
            r = requests.post(
                f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/change",
                headers=_h(tok_atendente),
                json={"ssid_24": "TEST_RL", "password_24": "abcd1234",
                      "source": "whatsapp_alvaro"},
                timeout=15)
            assert r.status_code == 429, r.text
            detail = r.json().get("detail")
            assert isinstance(detail, dict)
            assert detail.get("code") == "RATE_LIMITED"
        finally:
            mongo.wifi_change_logs.delete_many(
                {"subscriber_id": PREMIUM_SID, "company_id": "co-demo"})

    def test_change_atendente_bypasses_rate_limit(self, tok_atendente, mongo,
                                                  ensure_premium_link):
        """Mesmo com log recente, source=atendente NÃO é rate-limited."""
        mongo.wifi_change_logs.delete_many(
            {"subscriber_id": PREMIUM_SID, "company_id": "co-demo"})
        # 2 sucessos recentes — atendente deve passar do gate de rate-limit
        # e cair no 502 do SmartOLT (não no 429).
        mongo.wifi_change_logs.insert_many([{
            "id": f"wfl-seed-{i}",
            "company_id": "co-demo",
            "subscriber_id": PREMIUM_SID,
            "source": "whatsapp_alvaro",
            "success": True,
            "ts": datetime.now(timezone.utc).isoformat(),
        } for i in range(2)])
        try:
            r = requests.post(
                f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/change",
                headers=_h(tok_atendente),
                json={"ssid_24": "TEST_BypassRL", "password_24": "abcd1234",
                      "source": "atendente"},
                timeout=30)
            # NÃO pode ser 429.
            assert r.status_code != 429, f"Atendente deveria bypassar rate-limit, mas voltou 429: {r.text}"
            assert r.status_code in (200, 502)
        finally:
            mongo.wifi_change_logs.delete_many(
                {"subscriber_id": PREMIUM_SID, "company_id": "co-demo"})


# ---------------------------------------------------------------------------
# 4) LOGS
# ---------------------------------------------------------------------------
class TestLogs:
    def test_logs_desc_order(self, tok_atendente, mongo):
        # Seeda 3 logs com ts crescente
        mongo.wifi_change_logs.delete_many(
            {"subscriber_id": PREMIUM_SID, "company_id": "co-demo"})
        now = datetime.now(timezone.utc)
        for i in range(3):
            mongo.wifi_change_logs.insert_one({
                "id": f"wfl-log-{i}",
                "company_id": "co-demo",
                "subscriber_id": PREMIUM_SID,
                "source": "atendente",
                "success": True,
                "ts": (now - timedelta(minutes=10 * (3 - i))).isoformat(),
            })
        try:
            r = requests.get(
                f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/logs",
                headers=_h(tok_atendente), timeout=15)
            assert r.status_code == 200
            items = r.json()["items"]
            assert len(items) >= 3
            # Verifica ordem desc por ts
            ts_seq = [it["ts"] for it in items[:3]]
            assert ts_seq == sorted(ts_seq, reverse=True)
        finally:
            mongo.wifi_change_logs.delete_many(
                {"subscriber_id": PREMIUM_SID, "company_id": "co-demo"})


# ---------------------------------------------------------------------------
# 5) REBOOT-ONU
# ---------------------------------------------------------------------------
class TestReboot:
    def test_reboot_no_link(self, tok_atendente):
        r = requests.post(
            f"{BASE_URL}/api/wifi/subscriber/{NO_ONU_SID}/reboot-onu",
            headers=_h(tok_atendente), timeout=15)
        assert r.status_code == 409


# ---------------------------------------------------------------------------
# 6) RBAC — colaborador deve receber 403 em link/unlink/auto-match/reboot
# ---------------------------------------------------------------------------
class TestRBACColaborador:
    def test_colab_link_onu_403(self, tok_colab):
        r = requests.post(
            f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/link-onu",
            headers=_h(tok_colab),
            json={"smartolt_onu_id": PREMIUM_ONU_ID}, timeout=15)
        assert r.status_code == 403

    def test_colab_unlink_onu_403(self, tok_colab):
        r = requests.delete(
            f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/link-onu",
            headers=_h(tok_colab), timeout=15)
        assert r.status_code == 403

    def test_colab_auto_match_403(self, tok_colab):
        r = requests.post(
            f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/auto-match",
            headers=_h(tok_colab), timeout=15)
        assert r.status_code == 403

    def test_colab_reboot_403(self, tok_colab):
        r = requests.post(
            f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/reboot-onu",
            headers=_h(tok_colab), timeout=15)
        assert r.status_code == 403

    def test_colab_can_call_status(self, tok_colab, ensure_premium_link):
        r = requests.get(
            f"{BASE_URL}/api/wifi/subscriber/{PREMIUM_SID}/status",
            headers=_h(tok_colab), timeout=15)
        assert r.status_code == 200
