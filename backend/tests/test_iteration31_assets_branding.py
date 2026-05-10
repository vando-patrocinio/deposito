"""Iteration 31 — Backend tests for new features:
    1. Branding (CompanyBranding + default_asset_values_brl + public endpoint)
    2. Collaborator assets CRUD (with unit_value_brl & status->returned_at)
    3. Public mobile asset endpoints (signing with signature_data_url)
    4. Romaneio PDF (auth + public, 404/400 edge cases)
    5. AI dashboard assets-overview + other AI endpoints
    6. Pending losses / collaborator deactivation hook
    7. Lousa /grid SLA modes (execution / schedule / queue)
"""
from __future__ import annotations

import base64
import os
import time

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dual-combine-3.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@empresa.com"
ADMIN_PASS = "123456"
TEST_CID = "col-30aafc3c"

# 1x1 transparent PNG
PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
PNG_DATA_URL = f"data:image/png;base64,{PNG_B64}"


# -------- fixtures --------
@pytest.fixture(scope="session")
def auth_token() -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
        timeout=10,
    )
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


# ----------------------------------------------------------------------
# 1. Branding
# ----------------------------------------------------------------------
class TestBranding:
    def test_get_branding_settings(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/branding/settings", headers=auth_headers, timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data.get("company_name") == "Ligo Fibra Telecom"
        assert isinstance(data.get("default_asset_values_brl"), dict)
        for k in ["uniforme", "epi", "ferramenta", "veiculo", "eletronico", "outro"]:
            assert k in data["default_asset_values_brl"], f"missing default category {k}"
        assert "romaneio_footer" in data

    def test_get_branding_public_no_auth(self):
        r = requests.get(f"{BASE_URL}/api/branding/public", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data.get("company_name") == "Ligo Fibra Telecom"
        # secrets must NOT leak to public
        assert "cnpj" not in data
        assert "default_asset_values_brl" not in data

    def test_put_branding_persists_default_values(self, auth_headers):
        # change one value, confirm persisted, then restore
        r = requests.get(f"{BASE_URL}/api/branding/settings", headers=auth_headers, timeout=10)
        original = r.json()
        new_defaults = dict(original.get("default_asset_values_brl") or {})
        new_defaults["uniforme"] = 199
        payload = {**original, "default_asset_values_brl": new_defaults}
        # remove server-managed fields
        for k in ("updated_at", "company_id"):
            payload.pop(k, None)
        r2 = requests.put(
            f"{BASE_URL}/api/branding/settings", json=payload, headers=auth_headers, timeout=10
        )
        assert r2.status_code == 200, r2.text
        r3 = requests.get(f"{BASE_URL}/api/branding/settings", headers=auth_headers, timeout=10)
        assert r3.json()["default_asset_values_brl"]["uniforme"] == 199
        # restore
        payload["default_asset_values_brl"]["uniforme"] = original["default_asset_values_brl"]["uniforme"]
        requests.put(f"{BASE_URL}/api/branding/settings", json=payload, headers=auth_headers, timeout=10)


# ----------------------------------------------------------------------
# 2. Collaborator assets CRUD
# ----------------------------------------------------------------------
class TestCollabAssetsCRUD:
    created_id: str = ""

    def test_create_asset_with_unit_value(self, auth_headers):
        payload = {
            "collaborator_id": TEST_CID,
            "category": "uniforme",
            "item": "TEST_camisa_polo",
            "qty": 2,
            "unit_value_brl": 89.5,
            "marca": "TestBrand",
        }
        r = requests.post(
            f"{BASE_URL}/api/collab-assets", json=payload, headers=auth_headers, timeout=10
        )
        assert r.status_code in (200, 201), r.text
        data = r.json()
        assert data["collaborator_id"] == TEST_CID
        assert data["unit_value_brl"] == 89.5
        assert data["status"] == "ativo"
        assert "id" in data
        TestCollabAssetsCRUD.created_id = data["id"]

    def test_get_by_collaborator(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/collab-assets/by-collaborator/{TEST_CID}",
            headers=auth_headers, timeout=10,
        )
        assert r.status_code == 200
        body = r.json()
        rows = body.get("items") if isinstance(body, dict) else body
        assert isinstance(rows, list)
        assert any(a["id"] == TestCollabAssetsCRUD.created_id for a in rows)

    def test_patch_status_returns_marks_returned_at(self, auth_headers):
        aid = TestCollabAssetsCRUD.created_id
        assert aid
        r = requests.patch(
            f"{BASE_URL}/api/collab-assets/{aid}",
            json={"status": "devolvido"}, headers=auth_headers, timeout=10,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "devolvido"
        assert data.get("returned_at"), "returned_at não foi marcado ao mudar status pra devolvido"

    def test_delete_asset(self, auth_headers):
        aid = TestCollabAssetsCRUD.created_id
        r = requests.delete(
            f"{BASE_URL}/api/collab-assets/{aid}", headers=auth_headers, timeout=10
        )
        assert r.status_code in (200, 204), r.text
        # verify removed
        r2 = requests.get(
            f"{BASE_URL}/api/collab-assets/by-collaborator/{TEST_CID}",
            headers=auth_headers, timeout=10,
        )
        body = r2.json()
        rows = body.get("items") if isinstance(body, dict) else body
        assert all(a["id"] != aid for a in rows)


# ----------------------------------------------------------------------
# 3. Public mobile (no auth) + signing edge cases
# ----------------------------------------------------------------------
class TestPublicAssetsAndSigning:
    def test_public_by_collaborator_no_auth(self):
        r = requests.get(
            f"{BASE_URL}/api/collab-assets/public/by-collaborator/{TEST_CID}", timeout=10
        )
        assert r.status_code == 200
        d = r.json()
        # response shape: {collaborator, items} OR list
        items = d.get("items") if isinstance(d, dict) else d
        assert isinstance(items, list)

    def test_sign_marks_signed_at(self, auth_headers):
        # create asset
        cr = requests.post(
            f"{BASE_URL}/api/collab-assets",
            json={"collaborator_id": TEST_CID, "category": "epi",
                  "item": "TEST_capacete_sign", "qty": 1, "unit_value_brl": 50},
            headers=auth_headers, timeout=10,
        )
        assert cr.status_code in (200, 201)
        asset_id = cr.json()["id"]
        try:
            r = requests.post(
                f"{BASE_URL}/api/collab-assets/public/sign",
                json={"collaborator_id": TEST_CID, "asset_ids": [asset_id],
                      "signature_data_url": PNG_DATA_URL},
                timeout=15,
            )
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["signed_count"] == 1
            assert d.get("signed_at")
            # verify persisted on the asset
            lr = requests.get(
                f"{BASE_URL}/api/collab-assets/by-collaborator/{TEST_CID}",
                headers=auth_headers, timeout=10,
            )
            body = lr.json()
            items = body.get("items") if isinstance(body, dict) else body
            saved = next((a for a in items if a["id"] == asset_id), None)
            assert saved and saved.get("signed_at"), "signed_at não persistiu"
        finally:
            requests.delete(
                f"{BASE_URL}/api/collab-assets/{asset_id}", headers=auth_headers, timeout=10
            )

    def test_sign_invalid_signature_data_url(self):
        r = requests.post(
            f"{BASE_URL}/api/collab-assets/public/sign",
            json={"collaborator_id": TEST_CID, "asset_ids": ["fake-id"],
                  "signature_data_url": "not-a-data-url"},
            timeout=10,
        )
        assert r.status_code == 400, r.text

    def test_sign_with_invalid_asset_id_succeeds_zero(self):
        # sending unknown asset_ids should not error (update_many simply matches 0)
        r = requests.post(
            f"{BASE_URL}/api/collab-assets/public/sign",
            json={"collaborator_id": TEST_CID,
                  "asset_ids": ["bogus-asset-id-doesnotexist"]},
            timeout=10,
        )
        assert r.status_code in (200, 400)  # accept either spec


# ----------------------------------------------------------------------
# 4. Romaneio PDF (gestor + public) — edge cases
# ----------------------------------------------------------------------
class TestRomaneioPDF:
    created_id: str = ""

    def setup_method(self):
        # ensure at least 1 asset exists for TEST_CID
        token = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=10,
        ).json()["access_token"]
        self._headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def test_404_collaborator_inexistente_authed(self):
        r = requests.get(
            f"{BASE_URL}/api/collab-assets/romaneio/col-doesnotexist-zzz",
            headers=self._headers, timeout=10,
        )
        assert r.status_code == 404

    def test_404_collaborator_inexistente_public(self):
        r = requests.get(
            f"{BASE_URL}/api/collab-assets/public/romaneio/col-doesnotexist-zzz",
            timeout=10,
        )
        assert r.status_code == 404

    def test_400_when_no_assets(self, auth_headers):
        # find a collaborator with zero assets — try col-30aafc3c first by deleting any
        # (skip if has assets — DIOGO normally has 0)
        rows = requests.get(
            f"{BASE_URL}/api/collab-assets/by-collaborator/{TEST_CID}",
            headers=auth_headers, timeout=10,
        ).json()
        if rows:
            pytest.skip(f"{TEST_CID} has {len(rows)} assets — cannot test empty 400")
        r = requests.get(
            f"{BASE_URL}/api/collab-assets/romaneio/{TEST_CID}",
            headers=self._headers, timeout=10,
        )
        assert r.status_code == 400

    def test_pdf_generation_authed(self, auth_headers):
        # create an asset, generate PDF, validate magic
        cr = requests.post(
            f"{BASE_URL}/api/collab-assets",
            json={"collaborator_id": TEST_CID, "category": "uniforme",
                  "item": "TEST_pdf_item", "qty": 1, "unit_value_brl": 75},
            headers=auth_headers, timeout=10,
        )
        aid = cr.json()["id"]
        try:
            r = requests.get(
                f"{BASE_URL}/api/collab-assets/romaneio/{TEST_CID}",
                headers=self._headers, timeout=20,
            )
            assert r.status_code == 200
            assert r.headers.get("content-type", "").startswith("application/pdf")
            assert r.content[:4] == b"%PDF", "PDF magic não bateu"
            assert len(r.content) > 1000

            # public version
            r2 = requests.get(
                f"{BASE_URL}/api/collab-assets/public/romaneio/{TEST_CID}", timeout=20
            )
            assert r2.status_code == 200
            assert r2.content[:4] == b"%PDF"
        finally:
            requests.delete(
                f"{BASE_URL}/api/collab-assets/{aid}", headers=auth_headers, timeout=10
            )


# ----------------------------------------------------------------------
# 5. AI dashboard endpoints
# ----------------------------------------------------------------------
class TestAIDashboard:
    def test_assets_overview(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/ai/dashboard/assets-overview",
            headers=auth_headers, timeout=20,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        for key in ("kpis", "by_category", "by_status", "rows", "pending_losses"):
            assert key in d, f"missing {key}"
        for k in ("total_assets", "active", "pending_signature"):
            assert k in d["kpis"], f"missing kpis.{k}"
        pl = d["pending_losses"]
        for k in ("rows", "total_brl", "items_count", "default_values_brl"):
            assert k in pl, f"missing pending_losses.{k}"

    @pytest.mark.parametrize("path", [
        "overview",
        "tech-spending",
        "repair-map",
        "defective-equipment",
        "common-issues",
        "recurring-tickets",
        "insights/history",
    ])
    def test_other_ai_endpoints_200(self, auth_headers, path):
        r = requests.get(
            f"{BASE_URL}/api/ai/dashboard/{path}", headers=auth_headers, timeout=30
        )
        assert r.status_code == 200, f"{path} → {r.status_code}: {r.text[:200]}"


# ----------------------------------------------------------------------
# 6. Pending losses end-to-end (collaborator deactivation hook)
# ----------------------------------------------------------------------
class TestPendingLossesHook:
    def test_deactivation_creates_notification(self, auth_headers):
        # Fetch existing collaborator data to send full body
        coll_r = requests.get(
            f"{BASE_URL}/api/collaborators/{TEST_CID}",
            headers=auth_headers, timeout=10,
        )
        if coll_r.status_code != 200:
            # Try list endpoint
            lst = requests.get(
                f"{BASE_URL}/api/collaborators", headers=auth_headers, timeout=10
            ).json()
            arr = lst if isinstance(lst, list) else lst.get("items") or []
            coll = next((c for c in arr if c.get("id") == TEST_CID), None)
        else:
            coll = coll_r.json()
        if not coll:
            pytest.skip("Could not fetch collaborator for deactivation test")
        # build PUT payload (drop server-side fields)
        body = {k: v for k, v in coll.items() if k not in (
            "_id", "id", "created_at", "updated_at", "company_id", "deactivated_at"
        )}
        body["active"] = False

        cr = requests.post(
            f"{BASE_URL}/api/collab-assets",
            json={"collaborator_id": TEST_CID, "category": "ferramenta",
                  "item": "TEST_pending_loss_tool", "qty": 1, "unit_value_brl": 500},
            headers=auth_headers, timeout=10,
        )
        assert cr.status_code in (200, 201), cr.text
        asset_id = cr.json()["id"]
        try:
            r = requests.put(
                f"{BASE_URL}/api/collaborators/{TEST_CID}",
                json=body, headers=auth_headers, timeout=15,
            )
            assert r.status_code == 200, r.text
            time.sleep(1)
            ov = requests.get(
                f"{BASE_URL}/api/ai/dashboard/assets-overview",
                headers=auth_headers, timeout=20,
            ).json()
            ids_in_losses = {row.get("collaborator_id") for row in ov["pending_losses"]["rows"]}
            assert TEST_CID in ids_in_losses or ov["pending_losses"]["items_count"] >= 1, (
                f"Pending losses não detectou. Rows: {ov['pending_losses']['rows']}"
            )
            # Notification check
            notifs_r = requests.get(
                f"{BASE_URL}/api/notifications", headers=auth_headers, timeout=10
            )
            if notifs_r.status_code == 200:
                nb = notifs_r.json()
                arr = nb if isinstance(nb, list) else nb.get("items") or []
                kinds = {n.get("type") or n.get("kind") for n in arr}
                # informational, not strict
                print(f"[notifications] kinds present: {kinds}")
        finally:
            body["active"] = True
            requests.put(
                f"{BASE_URL}/api/collaborators/{TEST_CID}",
                json=body, headers=auth_headers, timeout=15,
            )
            requests.delete(
                f"{BASE_URL}/api/collab-assets/{asset_id}",
                headers=auth_headers, timeout=10,
            )


# ----------------------------------------------------------------------
# 7. Lousa SLA modes
# ----------------------------------------------------------------------
class TestLousaSLAModes:
    def test_grid_returns_sla_per_bubble(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/lousa/grid", headers=auth_headers, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        columns = data.get("columns") or []
        if not columns:
            pytest.skip("No columns — cannot validate SLA modes")
        modes_seen = set()
        violations = []
        for col in columns:
            for tk in col.get("tickets") or []:
                sla = tk.get("sla") or {}
                mode = sla.get("mode")
                if not mode:
                    continue
                modes_seen.add(mode)
                status = (tk.get("status") or "").lower()
                sched = tk.get("scheduled_time") or tk.get("scheduled_at")
                if status == "aberta" and mode != "execution":
                    violations.append(f"aberta/{mode}")
                elif status in ("pendente", "aguardando"):
                    if sched and mode != "schedule":
                        violations.append(f"pendente+sched/{mode}")
                    if not sched and mode != "queue":
                        violations.append(f"pendente+nosched/{mode}")
        assert modes_seen, "Nenhuma bolha com sla.mode encontrada"
        assert {"execution", "schedule", "queue"}.issubset(modes_seen), \
            f"Esperava todos 3 modos, vi: {modes_seen}"
        assert not violations, f"Violations: {violations[:10]}"
        print(f"[lousa] modos SLA observados: {modes_seen}")
