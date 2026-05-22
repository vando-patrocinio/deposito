"""iter116 — Detecção de troca de ONT/ONU + regras dependentes de SmartOLT.

Cobre:
  1. Cliente NÃO mapeado no SmartOLT → finalize não exige sinal/SmartOLT.
  2. Cliente MAPEADO + MAC novo igual ao atual → não é swap.
  3. Cliente MAPEADO + MAC novo diferente → swap detectado, salvo em
     `equipment_swaps` e em `tickets.equipment_swap`/`completion_data`.
"""
from __future__ import annotations

import uuid

import pytest


def _make_cd(**overrides):
    base = {
        "sinal": -22.0, "qtd_drop": 1, "esticadores": 1,
        "conectores_fast": 2, "cabo_rede": 5.0, "conectores_rede": 2,
        "ont": None, "fotos": [], "observacoes": "",
    }
    base.update(overrides)
    return base


def _make_ticket(t_type: str = "reparo", **overrides):
    return {
        "id": "tkt-" + uuid.uuid4().hex[:8],
        "company_id": "co-test",
        "type": t_type,
        "status": "aberta",
        "client_snapshot": {"name": "Cliente Teste", "pppoe": "cliente_teste"},
        "assigned_collaborator_id": "coll-1",
        "opened_at": "2026-02-01T10:00:00Z",
        **overrides,
    }


def test_detect_no_swap_same_sn():
    """SN novo igual ao registrado no SmartOLT → não é troca."""
    from routes.lousa import CompletionData, _detect_equipment_swap

    onu = {"sn": "ALCLFC090E99", "mac": ""}
    cd = CompletionData(**_make_cd(ont="ALCL:FC09:0E99"))
    t = _make_ticket("reparo")
    swap = _detect_equipment_swap(t, cd, onu)
    assert swap is None, "Mesmo equipamento (mesmo SN) não deve ser swap"


def test_detect_swap_different_sn():
    """SN novo difere do SmartOLT → swap detectado com old/new."""
    from routes.lousa import CompletionData, _detect_equipment_swap

    onu = {"sn": "ALCLFC090E99", "mac": "AA:BB:CC:11:22:33"}
    cd = CompletionData(**_make_cd(ont="HWTC12345678"))
    t = _make_ticket("reparo")
    swap = _detect_equipment_swap(t, cd, onu)
    assert swap is not None, "SN diferente deve ser detectado como swap"
    assert swap["old_sn"] == "ALCLFC090E99"
    assert swap["old_mac"] == "AA:BB:CC:11:22:33"
    assert swap["new_sn"] == "HWTC12345678"
    assert swap["source"] == "smartolt_cache"


def test_no_swap_when_not_smartolt_client_without_manual():
    """Sem SmartOLT e sem old_ont_mac/sn manual → não detecta swap."""
    from routes.lousa import CompletionData, _detect_equipment_swap

    cd = CompletionData(**_make_cd(ont="HWTC12345678"))
    t = _make_ticket("reparo")
    swap = _detect_equipment_swap(t, cd, None)
    assert swap is None


def test_detect_swap_with_manual_old_mac():
    """Sem SmartOLT mas técnico informou old_ont_mac → swap aceito."""
    from routes.lousa import CompletionData, _detect_equipment_swap

    cd = CompletionData(**_make_cd(
        old_ont_mac="AA:BB:CC:11:22:33",
        new_ont_mac="DD:EE:FF:44:55:66",
    ))
    t = _make_ticket("reparo")
    swap = _detect_equipment_swap(t, cd, None)
    assert swap is not None
    assert swap["old_mac"] == "AA:BB:CC:11:22:33"
    assert swap["new_mac"] == "DD:EE:FF:44:55:66"
    assert swap["source"] == "manual"


def test_no_swap_for_installation_type():
    """Instalação (sem ONT prévia) não é swap — só reparo/troca_endereco."""
    from routes.lousa import CompletionData, _detect_equipment_swap

    cd = CompletionData(**_make_cd(ont="NEW123456"))
    t = _make_ticket("instalacao")
    onu = {"sn": "OLD999999", "mac": ""}
    swap = _detect_equipment_swap(t, cd, onu)
    assert swap is None, "instalacao não deve gerar swap"


def test_norm_hexid_handles_separators():
    """Normalização ignora separadores comuns e diferenças de caixa."""
    from routes.lousa import _norm_hexid

    assert _norm_hexid("AA:BB:CC:11:22:33") == "AABBCC112233"
    assert _norm_hexid("aa-bb-cc-11-22-33") == "AABBCC112233"
    assert _norm_hexid(" ALCLFC09 0E99 ") == "ALCLFC090E99"
    assert _norm_hexid(None) == ""
    assert _norm_hexid("") == ""


def test_swap_detected_when_only_new_mac_provided():
    """Se só houver new_ont_mac (sem SN) e old via SmartOLT → swap ok."""
    from routes.lousa import CompletionData, _detect_equipment_swap

    onu = {"sn": "", "mac": "AA:BB:CC:11:22:33"}
    cd = CompletionData(**_make_cd(new_ont_mac="DD:EE:FF:44:55:66"))
    t = _make_ticket("reparo")
    swap = _detect_equipment_swap(t, cd, onu)
    assert swap is not None
    assert swap["old_mac"] == "AA:BB:CC:11:22:33"
    assert swap["new_mac"] == "DD:EE:FF:44:55:66"
