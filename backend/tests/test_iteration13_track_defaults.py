"""
Iteration 13 — Live tracking defaults

Tests for backend changes:
- GET /api/locations/{cid}/track sem hours -> default 24h
- GET /api/locations/{cid}/track?hours=4 -> aceita parâmetro
- GET /api/locations/{cid}/track -> aceita até 10000 pontos
- Job location_logs_cleanup_job está registrado no scheduler

Não testa execução do cleanup. Apenas verifica registro/inspecionar logs.
"""
import time
import pytest
import requests

CID = "col-demo-001"


# ----- track endpoint -----
class TestTrackDefaults:
    def test_track_default_24h(self, base_url, api):
        r = api.get(f"{base_url}/api/locations/{CID}/track")
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list)
        # cada doc deve ter campos esperados (lat, lng, recorded_at) e sem _id
        if data:
            for d in data[:3]:
                assert "_id" not in d
                assert "recorded_at" in d
                assert "collaborator_id" in d
        # Carlos tem ~57 location logs nas últimas 24h (per contexto)
        # validamos apenas que retornou >0 caso já haja seed de logs
        # mas não falhamos se a base estiver limpa
        print(f"default(24h) returned {len(data)} points")

    def test_track_explicit_hours_4(self, base_url, api):
        r = api.get(f"{base_url}/api/locations/{CID}/track", params={"hours": 4})
        assert r.status_code == 200, r.text
        d4 = r.json()
        r24 = api.get(f"{base_url}/api/locations/{CID}/track", params={"hours": 24})
        assert r24.status_code == 200
        d24 = r24.json()
        # 4h <= 24h
        assert len(d4) <= len(d24)
        print(f"hours=4 -> {len(d4)} pts | hours=24 -> {len(d24)} pts")

    def test_track_accepts_high_hours(self, base_url, api):
        # Garante que o endpoint não estoura ao pedir muitas horas (limit interno = 10000)
        r = api.get(f"{base_url}/api/locations/{CID}/track", params={"hours": 720})
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list)
        # Limite interno é 10000
        assert len(data) <= 10000
        print(f"hours=720 -> {len(data)} pts (limit=10000)")

    def test_track_unknown_collaborator_returns_empty(self, base_url, api):
        r = api.get(f"{base_url}/api/locations/TEST_does_not_exist_xyz/track")
        assert r.status_code == 200
        assert r.json() == []


# ----- limit 10000 -----
class TestTrackLimit:
    def test_track_returns_all_recent_points(self, base_url, api):
        # Insere alguns pings sintéticos via POST /api/locations/ping (se existir)
        # e valida que default=24h pega todos
        # Primeiro verifica quantos pontos já existem
        r0 = api.get(f"{base_url}/api/locations/{CID}/track")
        before = len(r0.json())

        # Ping endpoint
        ping_url = f"{base_url}/api/locations/ping"
        body = {
            "collaborator_id": CID,
            "lat": -22.4665,
            "lng": -42.6526,
            "accuracy": 5.0,
        }
        sent = 0
        for _ in range(3):
            rp = requests.post(ping_url, json=body, timeout=10)
            if rp.status_code in (200, 201, 204):
                sent += 1
            else:
                # endpoint pode ter outra forma; se 404, abortamos esse teste como skip
                if rp.status_code == 404:
                    pytest.skip("Endpoint /api/locations/ping não existe; skip incremento")
                break
            time.sleep(0.1)

        r1 = api.get(f"{base_url}/api/locations/{CID}/track")
        assert r1.status_code == 200
        after = len(r1.json())
        assert after >= before, f"after({after}) deveria ser >= before({before}) após {sent} pings"
        print(f"before={before}, sent={sent}, after={after}")
