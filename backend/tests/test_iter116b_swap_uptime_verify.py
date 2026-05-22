"""iter116b — Verificação de troca de ONT/ONU via uptime SmartOLT.

Regra: toda troca física implica reboot. Se a ONU está online há > N min
(default 10) sem reboot recente, a declaração de troca é SUSPEITA.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


def _iso_minutes_ago(mins: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=mins)).isoformat()


@pytest.mark.asyncio
async def test_verify_no_smartolt_mapping():
    """Sem ONU mapeada → verified=None, reason='no_smartolt_mapping'."""
    from routes.lousa import _verify_swap_via_uptime

    result = await _verify_swap_via_uptime(None)
    assert result["verified"] is None
    assert result["reason"] == "no_smartolt_mapping"


@pytest.mark.asyncio
async def test_verify_recent_reboot_within_threshold():
    """ONU online há 3min → verificada como troca legítima."""
    from routes.lousa import _verify_swap_via_uptime

    onu = {
        "status": "online",
        "last_status_change": _iso_minutes_ago(3),
    }
    result = await _verify_swap_via_uptime(onu)
    assert result["verified"] is True
    assert result["reason"] == "recent_reboot"
    assert result["uptime_minutes"] <= 3


@pytest.mark.asyncio
async def test_verify_uptime_too_high_marks_suspect():
    """ONU online há 30min sem reboot → troca SUSPEITA."""
    from routes.lousa import _verify_swap_via_uptime

    onu = {
        "status": "online",
        "last_status_change": _iso_minutes_ago(30),
    }
    result = await _verify_swap_via_uptime(onu)
    assert result["verified"] is False
    assert result["reason"] == "uptime_too_high"
    assert result["uptime_minutes"] >= 29


@pytest.mark.asyncio
async def test_verify_offline_status_passes():
    """ONU em LOS no fechamento (em transição) → não rejeita."""
    from routes.lousa import _verify_swap_via_uptime

    onu = {
        "status": "los",
        "last_status_change": _iso_minutes_ago(60),
    }
    result = await _verify_swap_via_uptime(onu)
    assert result["verified"] is True
    assert result["reason"] == "status_los"


@pytest.mark.asyncio
async def test_verify_threshold_boundary():
    """Limite exato (10min) é tratado como legítimo (<=, não <)."""
    from routes.lousa import _verify_swap_via_uptime

    onu = {
        "status": "online",
        "last_status_change": _iso_minutes_ago(10),
    }
    result = await _verify_swap_via_uptime(onu)
    assert result["verified"] is True


@pytest.mark.asyncio
async def test_verify_no_last_status_change():
    """ONU sem timestamp → não rejeita nem confirma, reason claro."""
    from routes.lousa import _verify_swap_via_uptime

    onu = {"status": "online", "last_status_change": None}
    result = await _verify_swap_via_uptime(onu)
    assert result["verified"] is None
    assert result["reason"] == "no_last_status_change"


@pytest.mark.asyncio
async def test_verify_custom_threshold():
    """Threshold customizado (5min) — 7min vira suspect."""
    from routes.lousa import _verify_swap_via_uptime

    onu = {
        "status": "online",
        "last_status_change": _iso_minutes_ago(7),
    }
    result = await _verify_swap_via_uptime(onu, threshold_minutes=5)
    assert result["verified"] is False
    assert result["threshold_minutes"] == 5


def test_parse_smartolt_ts_accepts_common_formats():
    """Parser tolera 'YYYY-MM-DD HH:MM:SS' e ISO."""
    from routes.lousa import _parse_smartolt_ts

    a = _parse_smartolt_ts("2026-02-22 10:30:00")
    b = _parse_smartolt_ts("2026-02-22T10:30:00Z")
    c = _parse_smartolt_ts("2026-02-22T10:30:00+00:00")
    assert a is not None and a.tzinfo is not None
    assert b is not None and b.tzinfo is not None
    assert c is not None and c.tzinfo is not None
    assert _parse_smartolt_ts(None) is None
    assert _parse_smartolt_ts("not-a-date") is None
