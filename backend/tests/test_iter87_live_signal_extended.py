"""Iter87 — SmartOLT live_signal estendido + PPPoE click-to-copy."""
import asyncio
import sys

import pytest

sys.path.insert(0, "/app/backend")
from database import db as _module_db  # noqa: E402


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def test_live_signal_parses_olt_port_and_cto(event_loop):
    """_live_signal_summary deve extrair olt_port (board/port), board,
    port, onu, sn, cto_box, cto_port, vlan."""
    from routes.smartolt import _live_signal_summary
    onu = {
        "unique_external_id": "X-001",
        "name": "Cliente Teste",
        "signal_1490": "-22.4",
        "signal_1310": "-24.0",
        "signal_text": "Good",
        "status": "Online",
        "olt_name": "RIO_HUAWEI",
        "board": "1", "port": "10", "onu": "8",
        "sn": "TPLG0CB1B3B8",
        "zone_name": "CTO - 1 - 10 - 01",
        "service_ports": [{"vlan": "301", "cvlan": "", "svlan": ""}],
        "synced_at": "2026-05-16T03:00:00+00:00",
    }
    out = _live_signal_summary(onu)
    assert out["olt_port"] == "1/10"
    assert out["board"] == "1"
    assert out["port"] == "10"
    assert out["onu"] == "8"
    assert out["sn"] == "TPLG0CB1B3B8"
    assert out["vlan"] == "301"
    assert out["cto_box"] == "CTO 1 10"  # primeiros 3 segmentos
    assert out["cto_port"] == "01"
    assert out["rx_dbm"] == pytest.approx(-22.4)
    assert out["quality"] == "good"


def test_live_signal_handles_missing_fields(event_loop):
    """Quando faltar zone_name/board/service_ports, retorna None nos campos sem erro."""
    from routes.smartolt import _live_signal_summary
    out = _live_signal_summary({
        "unique_external_id": "Y",
        "name": "X",
        "signal_1490": None, "signal_1310": None,
        "olt_name": "OLT2",
    })
    assert out["olt_port"] is None
    assert out["vlan"] is None
    assert out["cto_box"] is None
    assert out["cto_port"] is None
    assert out["sn"] is None
    assert out["rx_dbm"] is None
    assert out["quality"] == "unknown"


def test_live_signal_zone_with_only_one_segment(event_loop):
    from routes.smartolt import _live_signal_summary
    out = _live_signal_summary({"zone_name": "CTO_ALPHA",
                                 "board": "2", "port": "3"})
    assert out["cto_box"] == "CTO_ALPHA"
    assert out["cto_port"] is None
    assert out["olt_port"] == "2/3"


def test_live_signal_picks_first_vlan_priority(event_loop):
    """Pega vlan; se não tiver, tenta cvlan; depois svlan."""
    from routes.smartolt import _live_signal_summary

    out = _live_signal_summary({
        "service_ports": [{"vlan": "", "cvlan": "100", "svlan": ""}],
    })
    assert out["vlan"] == "100"

    out2 = _live_signal_summary({
        "service_ports": [{"vlan": "", "cvlan": "", "svlan": "200"}],
    })
    assert out2["vlan"] == "200"


def test_live_signal_quality_thresholds(event_loop):
    """rx >= -23 = good; -27 a -23 = warn; < -27 = bad."""
    from routes.smartolt import _live_signal_summary
    assert _live_signal_summary({"signal_1490": "-22"})["quality"] == "good"
    assert _live_signal_summary({"signal_1490": "-25"})["quality"] == "warn"
    assert _live_signal_summary({"signal_1490": "-30"})["quality"] == "bad"
