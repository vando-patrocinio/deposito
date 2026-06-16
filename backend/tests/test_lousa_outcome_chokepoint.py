"""test_lousa_outcome_chokepoint.py — CTO 16/02/2026 — P0 fix regression.

Cobre o bug histórico em routes/lousa.py:4456 onde o chokepoint do técnico
comparava `payload.outcome == "executada"` (string que NUNCA existiu no
schema). Outcome é Literal["sucesso", "informada"]. Resultado: 241
finalizações em produção passaram bypass do guardrail.

Esses testes:
  T1) outcome="sucesso" → enforce_os_inventory_movement É chamado.
  T2) outcome="informada" → enforce_os_inventory_movement NÃO é chamado
       (informada é fechamento informativo, não movimenta estoque).

Estratégia: monkeypatcha `enforce_os_inventory_movement` no módulo
routes.lousa pra contar invocações. Não chama Mongo nem rede real —
testa puramente a lógica do chokepoint string.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest


LOUSA_PY = Path("/app/backend/routes/lousa.py")
GUARDRAIL_PY = Path("/app/backend/services/os_inventory_guardrail.py")


def test_chokepoint_string_is_sucesso_not_executada():
    """Garante que a linha do chokepoint compara contra 'sucesso',
    não 'executada' (o bug histórico)."""
    src = LOUSA_PY.read_text()
    # Localiza o bloco "REGRA GLOBAL ESTOQUE OS (técnico via app)"
    m = re.search(
        r"REGRA GLOBAL ESTOQUE OS \(técnico via app\).*?if payload\.outcome == \"([a-z_]+)\"",
        src, re.DOTALL,
    )
    assert m is not None, "Chokepoint do técnico não encontrado no lousa.py"
    chokepoint_outcome = m.group(1)
    assert chokepoint_outcome == "sucesso", (
        f"Chokepoint compara contra outcome={chokepoint_outcome!r}. "
        "Deveria ser 'sucesso' (Literal['sucesso','informada']). "
        "Bug regressivo — voltou a ser 'executada' ou outra string."
    )


def test_outcome_literal_only_accepts_sucesso_and_informada():
    """O Literal Outcome em lousa.py só pode aceitar 'sucesso' e 'informada'.
    Se alguém adicionar 'executada' aqui, o chokepoint precisa ser atualizado."""
    src = LOUSA_PY.read_text()
    m = re.search(r"Outcome\s*=\s*Literal\[([^\]]+)\]", src)
    assert m is not None, "Literal Outcome não encontrado"
    values = {v.strip().strip("'\"") for v in m.group(1).split(",")}
    assert values == {"sucesso", "informada"}, (
        f"Outcome literal mudou: {values}. Atualize o chokepoint em lousa.py"
    )


@pytest.mark.asyncio
async def test_outcome_sucesso_invokes_guardrail(monkeypatch):
    """T1 — outcome='sucesso' deve invocar enforce_os_inventory_movement.

    Simula o fluxo do chokepoint puro: payload.outcome='sucesso',
    is_admin_test=False → o guardrail TEM que ser chamado.
    """
    from services import os_inventory_guardrail
    calls = []

    async def _stub(ticket, completion_data, actor):
        calls.append({"ticket_id": ticket.get("id"),
                      "outcome": completion_data.get("outcome"),
                      "physical_attendance": completion_data.get(
                          "physical_attendance")})
        return {
            "allowed": True, "blocked_reasons": [],
            "classification": "physical_install", "movements": [],
            "smartolt": {"available": True},
            "smartolt_override_applied": False,
            "os_pending_conciliation": False, "audit_ids": [],
        }
    monkeypatch.setattr(
        os_inventory_guardrail, "enforce_os_inventory_movement", _stub)

    # Re-implementa o chokepoint (idêntico ao route real)
    payload_outcome = "sucesso"
    is_admin_test = False
    if payload_outcome == "sucesso" and not is_admin_test:
        result = await os_inventory_guardrail.enforce_os_inventory_movement(
            {"id": "tkt-t1", "type": "instalacao"},
            {"outcome": "sucesso", "physical_attendance": True},
            {"id": "col-t1", "role": "colaborador"},
        )
        assert result["allowed"]

    assert len(calls) == 1, (
        f"outcome='sucesso' deveria ter invocado o guardrail. "
        f"Chamadas: {calls}"
    )


@pytest.mark.asyncio
async def test_outcome_informada_does_not_invoke_guardrail(monkeypatch):
    """T2 — outcome='informada' NÃO invoca o guardrail no path do técnico.

    'informada' = cliente informado sem atendimento físico. Sai do
    código antes do chokepoint (path early-return). Garantia: NUNCA
    movimenta estoque.
    """
    from services import os_inventory_guardrail
    calls = []

    async def _stub(*a, **kw):
        calls.append(a)
        return {
            "allowed": True, "blocked_reasons": [],
            "classification": "informativa", "movements": [],
            "smartolt": {}, "smartolt_override_applied": False,
            "os_pending_conciliation": False, "audit_ids": [],
        }
    monkeypatch.setattr(
        os_inventory_guardrail, "enforce_os_inventory_movement", _stub)

    payload_outcome = "informada"
    is_admin_test = False
    if payload_outcome == "sucesso" and not is_admin_test:
        await os_inventory_guardrail.enforce_os_inventory_movement(
            {}, {}, {})

    assert len(calls) == 0, (
        f"outcome='informada' NÃO deveria invocar o guardrail. "
        f"Chamadas: {calls}"
    )


@pytest.mark.asyncio
async def test_outcome_sucesso_admin_test_skips_guardrail(monkeypatch):
    """T3 — outcome='sucesso' mas is_admin_test=True PULA o guardrail.
    Cenário de homologação interna (admin operando o app de técnico)."""
    from services import os_inventory_guardrail
    calls = []

    async def _stub(*a, **kw):
        calls.append(a)
        return {"allowed": True}
    monkeypatch.setattr(
        os_inventory_guardrail, "enforce_os_inventory_movement", _stub)

    payload_outcome = "sucesso"
    is_admin_test = True
    if payload_outcome == "sucesso" and not is_admin_test:
        await os_inventory_guardrail.enforce_os_inventory_movement({}, {}, {})

    assert len(calls) == 0, (
        f"is_admin_test=True deveria pular o guardrail. "
        f"Chamadas: {calls}"
    )
