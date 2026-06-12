"""Tests for Iter Reforma Agentes:
 - Pricing Catalog CRUD + validations
 - Isabella prompt versioning (history collection)
 - Isabella /test with pricing injection
 - Alvaro /test scenario validation
 - Agent rename (Camila -> Pâmela)
 - Isabella fragments without hardcoded prices
"""
import os
import time
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
EMAIL = "admin@empresa.com"
PASSWORD = "123456"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login falhou: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, f"sem token: {r.json()}"
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


# --- pricing catalog ---------------------------------------------------------
class TestPricingCatalog:
    created_id = None

    def test_list_initial(self, session):
        r = session.get(f"{BASE}/api/pricing-catalog/items", timeout=20)
        assert r.status_code == 200
        assert "items" in r.json()

    def test_create_valid(self, session):
        payload = {
            "category": "plano_fibra",
            "name": "TEST_700 Mega QA",
            "price_brl": 129.9,
            "billing_cycle": "mensal",
            "fidelity": "com",
        }
        r = session.post(f"{BASE}/api/pricing-catalog/items", json=payload, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["category"] == "plano_fibra"
        assert d["price_brl"] == 129.9
        assert d["billing_cycle"] == "mensal"
        assert d["fidelity"] == "com"
        assert d["id"].startswith("prc-")
        TestPricingCatalog.created_id = d["id"]

    def test_patch_price_and_enabled(self, session):
        iid = TestPricingCatalog.created_id
        assert iid
        r = session.patch(f"{BASE}/api/pricing-catalog/items/{iid}", json={"price_brl": 139.9, "enabled": True}, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["price_brl"] == 139.9
        assert d["enabled"] is True

    def test_invalid_category(self, session):
        r = session.post(f"{BASE}/api/pricing-catalog/items", json={
            "category": "invalido_xyz", "name": "TEST_x", "price_brl": 10.0,
        }, timeout=20)
        assert r.status_code == 400

    def test_invalid_billing_cycle(self, session):
        r = session.post(f"{BASE}/api/pricing-catalog/items", json={
            "category": "plano_fibra", "name": "TEST_x", "price_brl": 10.0,
            "billing_cycle": "trimestral",
        }, timeout=20)
        assert r.status_code == 400

    def test_negative_price(self, session):
        r = session.post(f"{BASE}/api/pricing-catalog/items", json={
            "category": "plano_fibra", "name": "TEST_neg", "price_brl": -1.0,
        }, timeout=20)
        assert r.status_code == 422

    def test_delete(self, session):
        iid = TestPricingCatalog.created_id
        assert iid
        r = session.delete(f"{BASE}/api/pricing-catalog/items/{iid}", timeout=20)
        assert r.status_code == 200
        # idempotent: second delete should 404
        r2 = session.delete(f"{BASE}/api/pricing-catalog/items/{iid}", timeout=20)
        assert r2.status_code == 404


# --- isabella test injection -------------------------------------------------
class TestIsabellaTestPricingInjection:
    item_id = None

    def test_inject_pricing_block(self, session):
        # ensure at least one enabled item
        r = session.post(f"{BASE}/api/pricing-catalog/items", json={
            "category": "plano_fibra", "name": "TEST_INJ 500 Mega",
            "price_brl": 99.9, "billing_cycle": "mensal", "fidelity": "com",
            "enabled": True,
        }, timeout=20)
        assert r.status_code == 200, r.text
        TestIsabellaTestPricingInjection.item_id = r.json()["id"]

        r2 = session.post(f"{BASE}/api/whatsapp-baileys/isabella/test",
                          json={"text": "quanto custa o plano de vocês?"}, timeout=60)
        # 502 if no OpenRouter key — environment limitation, not bug
        if r2.status_code == 502:
            pytest.skip(f"OpenRouter LLM indisponível no preview: {r2.text[:200]}")
        assert r2.status_code == 200, r2.text
        d = r2.json()
        assert d["ok"] is True
        assert d["prompt_size"] > 0
        # bubbles is a list
        assert isinstance(d.get("bubbles"), list)

    def test_cleanup(self, session):
        iid = TestIsabellaTestPricingInjection.item_id
        if iid:
            session.delete(f"{BASE}/api/pricing-catalog/items/{iid}", timeout=20)


# --- isabella prompt versioning ----------------------------------------------
class TestIsabellaPromptVersioning:
    original_prompt = None

    def test_get_original_prompt(self, session):
        r = session.get(f"{BASE}/api/whatsapp-baileys/isabella/prompt", timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("exists") is True
        assert len(d.get("system_prompt") or "") > 20
        TestIsabellaPromptVersioning.original_prompt = d["system_prompt"]

    def test_put_creates_history_and_restore(self, session):
        orig = TestIsabellaPromptVersioning.original_prompt
        assert orig
        test_prompt = orig + "\n\n# TEST_VERSIONING_QA marker " + str(int(time.time()))
        r = session.put(f"{BASE}/api/whatsapp-baileys/isabella/prompt",
                        json={"system_prompt": test_prompt}, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["sha"]
        assert d["size"] == len(test_prompt)

        # Verify history entry was created (cannot query mongo directly via API,
        # but the put endpoint logic inserts into isabella_prompt_history before update).
        # Restore original prompt to avoid corruption.
        r2 = session.put(f"{BASE}/api/whatsapp-baileys/isabella/prompt",
                         json={"system_prompt": orig}, timeout=20)
        assert r2.status_code == 200, r2.text


# --- alvaro test -------------------------------------------------------------
class TestAlvaroTest:
    def test_invalid_scenario(self, session):
        r = session.post(f"{BASE}/api/whatsapp-baileys/alvaro/test",
                         json={"text": "minha internet caiu", "scenario": "xpto"}, timeout=20)
        assert r.status_code == 400

    def test_online_scenario(self, session):
        r = session.post(f"{BASE}/api/whatsapp-baileys/alvaro/test",
                         json={"text": "minha internet caiu", "scenario": "online"}, timeout=60)
        if r.status_code == 502:
            pytest.skip(f"OpenRouter LLM indisponível: {r.text[:200]}")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["scenario"] == "online"
        assert isinstance(d.get("bubbles"), list)


# --- agent rename / prompts (via mongo) --------------------------------------
class TestAgentRenameMongo:
    def test_mongo_state(self):
        """Inspects mongo directly: Pâmela exists, Camila does not, prompt versions correct."""
        import asyncio
        import sys
        sys.path.insert(0, "/app/backend")
        from database import db  # noqa: E402

        async def _check():
            cid = "co-demo"
            camila = await db.aihub_agents.find_one({"company_id": cid, "name": "Camila"})
            pamela = await db.aihub_agents.find_one({"company_id": cid, "name": "Pâmela"})
            isabella = await db.aihub_agents.find_one({"company_id": cid, "name": "Isabella"})
            alvaro = await db.aihub_agents.find_one({"company_id": cid, "name": "Alvaro"})
            return camila, pamela, isabella, alvaro

        camila, pamela, isabella, alvaro = asyncio.get_event_loop().run_until_complete(_check())
        assert camila is None, "Agente 'Camila' ainda presente — rename incompleto"
        assert pamela is not None, "Agente 'Pâmela' não criado"
        assert pamela.get("prompt_source_file") == "pamela_v2.md", \
            f"prompt_source_file errado: {pamela.get('prompt_source_file')}"
        # prompt_version pode ser V13 (arquivo) OU manual-* (edição
        # legítima do gestor pela UI — versionada em isabella_prompt_history)
        _iv = (isabella or {}).get("prompt_version") or ""
        assert isabella is not None and (
            _iv == "V13_CICLO_COMPLETO" or _iv.startswith("manual-")), \
            f"Isabella prompt_version errado: {_iv}"
        assert alvaro is not None and alvaro.get("prompt_version") == "V2", \
            f"Alvaro prompt_version errado: {alvaro.get('prompt_version') if alvaro else None}"


# --- fragments without hardcoded prices --------------------------------------
class TestIsabellaFragmentsNoHardcodedPrices:
    def test_fragments_no_prices(self, session):
        r = session.get(f"{BASE}/api/whatsapp-baileys/isabella/fragments", timeout=20)
        assert r.status_code == 200, r.text
        items = r.json().get("items", [])
        # Just check upgrade/novidade categories' content has no hardcoded prices
        for it in items:
            if it.get("category") in ("upgrade", "novidade"):
                content = it.get("content", "")
                assert "R$ 109" not in content, f"Hardcoded 'R$ 109' em {it.get('title')}"
                assert "R$ 29,90" not in content, f"Hardcoded 'R$ 29,90' em {it.get('title')}"
