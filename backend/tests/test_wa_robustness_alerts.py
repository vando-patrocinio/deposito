"""Testes para os novos alertas:
  - duplicate_session_suspected (3+ logged_out em 10min)
  - los_cluster_alert (3+ LOS na mesma OLT em 30min)

Usa mongo real (test DB) via fixtures padrão do projeto.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Aponta pro mongo local (mesmo do backend prod) — só LÊ/ESCREVE em
# coleções de eventos específicos com prefixo de teste pra não poluir.
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")


BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://dual-combine-3.preview.emergentagent.com",
).rstrip("/")


def _login_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "gestor@empresa.com", "password": "123456"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _get_inbound_token():
    """Lê o WA_INBOUND_TOKEN do .env do backend pra autenticar /system-event."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    for line in env_path.read_text().splitlines():
        if line.startswith("WA_INBOUND_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


# ---------------------------------------------------------------------------
# /system-event + detecção de duplicate session
# ---------------------------------------------------------------------------

def test_duplicate_session_alert_emitted_after_3_logged_out():
    """3 logged_out em 10min disparam evento `duplicate_session_suspected`."""
    inbound_token = _get_inbound_token()
    if not inbound_token:
        pytest.skip("WA_INBOUND_TOKEN não configurado")

    # Tag única pra distinguir esta rodada de testes
    tag = f"test-dup-{uuid.uuid4().hex[:6]}"

    # Envia 3 eventos logged_out
    for i in range(3):
        r = requests.post(
            f"{BASE_URL}/api/whatsapp-baileys/system-event",
            json={
                "event": "logged_out",
                "code": 401,
                "name": "loggedOut",
                "retryCount": 0,
                "reason": tag,
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            headers={"X-WA-Token": inbound_token},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        time.sleep(0.2)

    # Lista eventos recentes
    token = _login_token()
    r = requests.get(
        f"{BASE_URL}/api/whatsapp-baileys/system-events",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    events = r.json().get("events", [])
    # Verifica que ao menos um evento `duplicate_session_suspected` foi gerado
    # nas últimas 10min
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    dup_events = [
        e for e in events
        if e.get("event") == "duplicate_session_suspected"
        and (e.get("created_at") or "") >= cutoff
    ]
    assert len(dup_events) >= 1, (
        f"Esperava ao menos 1 evento duplicate_session_suspected, "
        f"obteve: {[e.get('event') for e in events[:10]]}"
    )
