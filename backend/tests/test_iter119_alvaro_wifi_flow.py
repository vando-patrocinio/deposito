"""Iter119 — Álvaro IA WhatsApp Wi-Fi self-service flow (público + helpers).

Cobre:
  • Endpoints públicos /api/wifi/public/* (status, change-by-phone,
    upgrade-lead) — sem JWT, com RBAC por telefone.
  • Helpers em services/alvaro_tools.py:
      - looks_like_wifi_change
      - fetch_wifi_status_for_alvaro
      - WIFI_MARKER_RE / UPGRADE_MARKER_RE
      - process_alvaro_actions (TROCAR_WIFI + OFFER_UPGRADE)
  • Auditoria em wifi_change_logs (com source='whatsapp_alvaro')
  • Lead em sales_leads com source='whatsapp_alvaro_wifi_request'

Pré-requisitos preparados fora do teste:
  • sub-91c01c46fc (Maria José) plan premium + ONU 4954425332697d69
  • sub-TEST-iter119np (non-premium, mesma ONU temporária)
  • subscriber_phones: 5521911112222 (Maria) e 5521900000119 (TEST)
  • smartolt_config.rate_limited_until limpo
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

# inserir backend no path pra importar services
sys.path.insert(0, "/app/backend")

from services import alvaro_tools  # noqa: E402

def _load_base_url() -> str:
    val = os.environ.get("REACT_APP_BACKEND_URL", "").strip()
    if not val:
        env_path = "/app/frontend/.env"
        if os.path.exists(env_path):
            with open(env_path) as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        val = line.split("=", 1)[1].strip().strip('"\'')
                        break
    return (val or "").rstrip("/")


BASE_URL = _load_base_url()
assert BASE_URL, "REACT_APP_BACKEND_URL não setado no frontend/.env"


def _load_mongo_url() -> tuple[str, str]:
    """Carrega MONGO_URL e DB_NAME do backend/.env (não usar default)."""
    url = os.environ.get("MONGO_URL", "").strip()
    name = os.environ.get("DB_NAME", "").strip()
    env_path = "/app/backend/.env"
    if (not url or not name) and os.path.exists(env_path):
        with open(env_path) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("MONGO_URL=") and not url:
                    url = line.split("=", 1)[1].strip().strip('"\'')
                elif line.startswith("DB_NAME=") and not name:
                    name = line.split("=", 1)[1].strip().strip('"\'')
    return url, name


_MONGO_URL, _DB_NAME = _load_mongo_url()
assert _MONGO_URL and _DB_NAME, "MONGO_URL/DB_NAME não encontrados"
_mongo = MongoClient(_MONGO_URL)
db = _mongo[_DB_NAME]

CID = "co-demo"
SID_PREMIUM = "sub-91c01c46fc"
PHONE_PREMIUM = "+5521911112222"            # pertence ao Maria José
PHONE_OUTSIDE = "+5511999999999"             # não pertence ao Maria José
SID_NONPREM = "sub-TEST-iter119np"
PHONE_NONPREM = "+5521900000119"


# ---------------------------------------------------------------- fixtures
@pytest.fixture(autouse=True)
def _reset_state():
    """Limpa circuit breaker e logs de troca do subscriber de teste."""
    db.smartolt_config.update_one(
        {"company_id": CID}, {"$unset": {"rate_limited_until": ""}})
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    db.wifi_change_logs.delete_many({
        "company_id": CID,
        "subscriber_id": {"$in": [SID_PREMIUM, SID_NONPREM]},
        "ts": {"$gte": cutoff},
    })
    yield


@pytest.fixture(scope="session", autouse=True)
def _final_cleanup():
    yield
    db.wifi_change_logs.delete_many({"company_id": CID,
        "subscriber_id": {"$in": [SID_PREMIUM, SID_NONPREM]}})
    db.sales_leads.delete_many({"company_id": CID,
        "source": "whatsapp_alvaro_wifi_request"})


# ======================================================================
# 1) GET /api/wifi/public/subscriber/{sid}/status
# ======================================================================
class TestPublicStatus:
    def test_status_premium_ready(self):
        r = requests.get(
            f"{BASE_URL}/api/wifi/public/subscriber/{SID_PREMIUM}/status",
            params={"company_id": CID}, timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["subscriber_id"] == SID_PREMIUM
        assert data["plan_premium"] is True
        assert data["smartolt_onu_id"] == "4954425332697d69"
        assert data["state"] in ("ready", "rate_limited"), data
        assert "onu" in data

    def test_status_non_premium(self):
        r = requests.get(
            f"{BASE_URL}/api/wifi/public/subscriber/{SID_NONPREM}/status",
            params={"company_id": CID}, timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["plan_premium"] is False
        assert data["state"] == "premium_required"

    def test_status_unknown_sub_404(self):
        r = requests.get(
            f"{BASE_URL}/api/wifi/public/subscriber/sub-NOPE/status",
            params={"company_id": CID}, timeout=10)
        assert r.status_code == 404


# ======================================================================
# 2) POST /api/wifi/public/subscriber/{sid}/change-by-phone (segurança)
# ======================================================================
class TestChangeByPhoneSecurity:
    def test_reject_phone_does_not_belong_403(self):
        r = requests.post(
            f"{BASE_URL}/api/wifi/public/subscriber/{SID_PREMIUM}/change-by-phone",
            json={"phone": PHONE_OUTSIDE, "company_id": CID,
                  "ssid": "TestSec", "password": "minhasenha123",
                  "apply_to_both": True, "source": "whatsapp_alvaro"},
            timeout=15)
        assert r.status_code == 403, r.text
        body = r.json()
        # FastAPI usa {"detail": "..."}
        msg = body.get("detail") or body
        assert "não autorizado" in str(msg).lower() \
            or "telefone" in str(msg).lower()

    def test_unknown_subscriber_404(self):
        r = requests.post(
            f"{BASE_URL}/api/wifi/public/subscriber/sub-NOPE/change-by-phone",
            json={"phone": PHONE_PREMIUM, "company_id": CID,
                  "ssid": "X", "password": "minhasenha123"},
            timeout=10)
        assert r.status_code == 404


# ======================================================================
# 3) Change-by-phone autorizado → tenta TR-069 (espera 502, log gravado)
# ======================================================================
class TestChangeByPhoneAuthorizedAudit:
    def test_correct_phone_passes_gates_audit_logged(self):
        before = db.wifi_change_logs.count_documents({
            "company_id": CID, "subscriber_id": SID_PREMIUM,
            "source": "whatsapp_alvaro"})

        r = requests.post(
            f"{BASE_URL}/api/wifi/public/subscriber/{SID_PREMIUM}/change-by-phone",
            json={"phone": PHONE_PREMIUM, "company_id": CID,
                  "ssid": "CasaMariaJose", "password": "minhasenha123",
                  "apply_to_both": True, "source": "whatsapp_alvaro"},
            timeout=40)
        assert r.status_code in (200, 502), r.text
        if r.status_code == 502:
            body = r.json()
            detail = body.get("detail") or {}
            assert detail.get("code") == "TR069_FAILED", body

        after = db.wifi_change_logs.count_documents({
            "company_id": CID, "subscriber_id": SID_PREMIUM,
            "source": "whatsapp_alvaro"})
        assert after == before + 1, (
            f"log de auditoria não foi gravado: before={before} after={after}")

        log = db.wifi_change_logs.find_one(
            {"company_id": CID, "subscriber_id": SID_PREMIUM,
             "source": "whatsapp_alvaro"},
            {"_id": 0}, sort=[("ts", -1)])
        assert log is not None
        assert log.get("subscriber_id") == SID_PREMIUM
        assert log.get("source") == "whatsapp_alvaro"
        actor_email = (log.get("actor_email") or log.get("actor")
                        or log.get("actor_user") or "")
        assert actor_email.startswith("whatsapp:"), log


# ======================================================================
# 4) Non-premium → 402 PREMIUM_REQUIRED
# ======================================================================
class TestChangeByPhoneNonPremium:
    def test_non_premium_returns_402(self):
        r = requests.post(
            f"{BASE_URL}/api/wifi/public/subscriber/{SID_NONPREM}/change-by-phone",
            json={"phone": PHONE_NONPREM, "company_id": CID,
                  "ssid": "TestNonPrem", "password": "minhasenha123",
                  "apply_to_both": True, "source": "whatsapp_alvaro"},
            timeout=15)
        assert r.status_code == 402, r.text
        body = r.json()
        detail = body.get("detail") or {}
        assert detail.get("code") == "PREMIUM_REQUIRED", body


# ======================================================================
# 5) Rate-limit whatsapp_alvaro: 2ª chamada em <24h → 429
# ======================================================================
class TestChangeByPhoneRateLimit:
    def test_second_call_in_24h_returns_429(self):
        """
        Como TR-069 sempre falha neste ambiente (502 TR069_FAILED) e o
        rate-limit conta apenas logs com success=True, simulamos um log
        de sucesso prévio inserindo direto no DB e validamos que a próxima
        tentativa whatsapp_alvaro é bloqueada com 429 RATE_LIMITED.
        """
        # remove logs prévios
        db.wifi_change_logs.delete_many({
            "company_id": CID, "subscriber_id": SID_PREMIUM})
        # injeta log de sucesso recente
        db.wifi_change_logs.insert_one({
            "id": "wfl-TEST-iter119rl",
            "company_id": CID,
            "subscriber_id": SID_PREMIUM,
            "subscriber_name": "Maria José Silva",
            "smartolt_onu_id": "4954425332697d69",
            "ts": datetime.now(timezone.utc).isoformat(),
            "success": True,
            "source": "whatsapp_alvaro",
            "actor_email": "whatsapp:5521911112222",
            "ssid_before": {},
            "ssid_after": {"2.4": "PrevChange", "5": "PrevChange"},
        })
        # Próxima chamada via whatsapp_alvaro deve bater 429
        r = requests.post(
            f"{BASE_URL}/api/wifi/public/subscriber/{SID_PREMIUM}/change-by-phone",
            json={"phone": PHONE_PREMIUM, "company_id": CID,
                  "ssid": "TryAgain", "password": "minhasenha123",
                  "source": "whatsapp_alvaro"},
            timeout=15)
        assert r.status_code == 429, r.text
        body = r.json()
        detail = body.get("detail") or {}
        assert detail.get("code") == "RATE_LIMITED", body
        assert detail.get("recent_changes_24h") == 1


# ======================================================================
# 6) POST /api/wifi/public/upgrade-lead — cria sales_leads
# ======================================================================
class TestUpgradeLead:
    def test_creates_lead(self):
        r = requests.post(
            f"{BASE_URL}/api/wifi/public/upgrade-lead",
            json={"phone": PHONE_PREMIUM, "company_id": CID,
                  "subscriber_id": SID_PREMIUM,
                  "source": "whatsapp_alvaro_wifi_request"},
            timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True
        lead_id = data.get("lead_id")
        assert lead_id and lead_id.startswith("lead-")

        # confirma persistência
        lead = db.sales_leads.find_one({"id": lead_id}, {"_id": 0})
        assert lead is not None
        assert lead["source"] == "whatsapp_alvaro_wifi_request"
        assert lead["status"] == "new"
        assert lead["subscriber_id"] == SID_PREMIUM

    def test_lead_by_phone_only_resolves_sub(self):
        """Sem subscriber_id, resolve pelo phone via subscriber_phones."""
        r = requests.post(
            f"{BASE_URL}/api/wifi/public/upgrade-lead",
            json={"phone": PHONE_PREMIUM, "company_id": CID,
                  "source": "whatsapp_alvaro_wifi_request"},
            timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("subscriber_id") == SID_PREMIUM


# ======================================================================
# 7) Helper looks_like_wifi_change
# ======================================================================
class TestLooksLikeWifiChange:
    @pytest.mark.parametrize("text", [
        "quero trocar a senha do wifi",
        "trocar wifi",
        pytest.param("mudar nome do wifi",
                     marks=pytest.mark.xfail(
                         reason="Keyword list em alvaro_tools.py tem "
                         "'mudar nome wifi' mas não 'mudar nome do wifi'. "
                         "Bug a ser corrigido pelo main agent.")),
        "nova senha wifi",
        "alterar senha do wifi",
        "renomear wifi",
    ])
    def test_true_cases(self, text):
        assert alvaro_tools.looks_like_wifi_change(text) is True

    @pytest.mark.parametrize("text", [
        "wifi não funciona",
        "internet caiu",
        "tô sem net",
        "",
    ])
    def test_false_cases(self, text):
        assert alvaro_tools.looks_like_wifi_change(text) is False


# ======================================================================
# 8) fetch_wifi_status_for_alvaro chama o status público
# ======================================================================
class TestFetchWifiStatus:
    def test_returns_dict_with_state(self):
        out = asyncio.run(alvaro_tools.fetch_wifi_status_for_alvaro(
            SID_PREMIUM, CID, base_url=BASE_URL))
        assert out is not None
        assert "state" in out
        assert out["subscriber_id"] == SID_PREMIUM

    def test_no_sid_returns_none(self):
        out = asyncio.run(alvaro_tools.fetch_wifi_status_for_alvaro(
            None, CID, base_url=BASE_URL))
        assert out is None


# ======================================================================
# 9) Regexes WIFI_MARKER_RE / UPGRADE_MARKER_RE
# ======================================================================
class TestMarkerRegex:
    def test_wifi_marker_extracts(self):
        m = alvaro_tools.WIFI_MARKER_RE.search(
            "vou trocar agora [TROCAR_WIFI:ssid=CasaJoao,senha=minhasenha123] ok?")
        assert m is not None
        assert m.group(1) == "CasaJoao"
        assert m.group(2) == "minhasenha123"

    def test_wifi_marker_no_match(self):
        assert alvaro_tools.WIFI_MARKER_RE.search("nada de marker aqui") is None

    def test_upgrade_marker_basic(self):
        m = alvaro_tools.UPGRADE_MARKER_RE.search(
            "vamos fazer upgrade [OFFER_UPGRADE]")
        assert m is not None
        # group(1) é None quando não tem plan
        assert m.group(1) is None

    def test_upgrade_marker_with_plan(self):
        m = alvaro_tools.UPGRADE_MARKER_RE.search(
            "upgrade [OFFER_UPGRADE:plan=plan-1giga] hoje")
        assert m is not None
        assert m.group(1) == "plan-1giga"


# ======================================================================
# 10) process_alvaro_actions: TROCAR_WIFI
# ======================================================================
class TestProcessActionsWifi:
    def test_wifi_marker_triggers_http_and_strips(self):
        text_in = ("Beleza! Aplicando agora 🔧 "
                   "[TROCAR_WIFI:ssid=CasaMaria,senha=minhasenha999] "
                   "Em 30s a rede volta.")
        wifi_ctx = {"state": "ready", "subscriber_id": SID_PREMIUM}
        diag = {"company_id": CID}
        # garantir limpo
        db.wifi_change_logs.delete_many({
            "company_id": CID, "subscriber_id": SID_PREMIUM})

        out = asyncio.run(alvaro_tools.process_alvaro_actions(
            text_in, PHONE_PREMIUM, diag,
            base_url=BASE_URL, wifi_ctx=wifi_ctx))
        # marker removido
        assert "[TROCAR_WIFI" not in out
        # texto de contexto preservado
        assert "Aplicando agora" in out

        # log foi gravado (mesmo que com falha TR-069)
        time.sleep(0.4)
        cnt = db.wifi_change_logs.count_documents({
            "company_id": CID, "subscriber_id": SID_PREMIUM,
            "source": "whatsapp_alvaro"})
        assert cnt >= 1, cnt

    def test_wifi_marker_state_not_ready_skips_http(self):
        text_in = "[TROCAR_WIFI:ssid=X,senha=12345678] feito"
        wifi_ctx = {"state": "premium_required",
                     "subscriber_id": SID_NONPREM}
        before = db.wifi_change_logs.count_documents({
            "company_id": CID, "subscriber_id": SID_NONPREM,
            "source": "whatsapp_alvaro"})
        out = asyncio.run(alvaro_tools.process_alvaro_actions(
            text_in, PHONE_NONPREM, {"company_id": CID},
            base_url=BASE_URL, wifi_ctx=wifi_ctx))
        # marker é removido mesmo quando não dispara
        assert "[TROCAR_WIFI" not in out
        # mas nenhum log adicional deve ter sido criado
        after = db.wifi_change_logs.count_documents({
            "company_id": CID, "subscriber_id": SID_NONPREM,
            "source": "whatsapp_alvaro"})
        assert after == before, (before, after)


# ======================================================================
# 11) process_alvaro_actions: OFFER_UPGRADE → lead + ROTEAR_VENDAS
# ======================================================================
class TestProcessActionsUpgrade:
    def test_offer_upgrade_creates_lead_and_injects_handoff(self):
        text_in = ("Entendo, posso te oferecer upgrade hoje. "
                   "[OFFER_UPGRADE] aceita?")
        wifi_ctx = {"state": "premium_required",
                     "subscriber_id": SID_NONPREM}
        before = db.sales_leads.count_documents({
            "company_id": CID,
            "source": "whatsapp_alvaro_wifi_request"})

        out = asyncio.run(alvaro_tools.process_alvaro_actions(
            text_in, PHONE_NONPREM, {"company_id": CID},
            base_url=BASE_URL, wifi_ctx=wifi_ctx))

        # marker removido, handoff injetado
        assert "[OFFER_UPGRADE" not in out
        assert "[ROTEAR_VENDAS]" in out

        # lead criado
        time.sleep(0.3)
        after = db.sales_leads.count_documents({
            "company_id": CID,
            "source": "whatsapp_alvaro_wifi_request"})
        assert after == before + 1, (before, after)

        # detalhe do lead
        lead = db.sales_leads.find_one(
            {"company_id": CID,
             "source": "whatsapp_alvaro_wifi_request"},
            {"_id": 0}, sort=[("ts", -1)])
        assert lead is not None
        assert lead["status"] == "new"
        assert lead["subscriber_id"] == SID_NONPREM


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
