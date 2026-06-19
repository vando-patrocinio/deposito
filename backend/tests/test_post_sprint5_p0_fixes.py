"""Testes P0 — Fechamento de bypass Onda 3 (CTO 19/06/2026).

Cobre:
1. Validator: rompimento — sem ONT/CTO/Porta passa quando tem ticket+collab+praca+report
2. Validator: rompimento sem praca/report → BLOQUEIA
3. Validator: outcome non_operational sem motivo ≥20 → BLOQUEIA
4. Validator: outcome non_operational com motivo válido → passa com audit
5. Validator: sucesso normal sem ONT → BLOQUEIA
"""
import asyncio
import os

import pytest
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")


@pytest.fixture
async def db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    yield client[os.environ["DB_NAME"]]
    client.close()


@pytest.mark.asyncio
async def test_rompimento_passes_with_praca_report(db):
    from services.os_finalization_validator import validate_finalization
    ok, diag = await validate_finalization(
        db, company_id="co-demo", service_type="rompimento",
        ticket_id="tkt-test-romp-1", service_id=None, subscriber_id=None,
        collaborator_id="col-test-1",
        completion_data={
            "praca_id": "prc-test", "report_text": "Substituí 80m de drop",
        },
    )
    assert ok, f"Rompimento válido bloqueado: {diag}"
    assert diag["service_type_status"] == "rompimento_specific"
    assert diag["reason"] == "rompimento_validated"


@pytest.mark.asyncio
async def test_rompimento_blocked_without_report(db):
    from services.os_finalization_validator import validate_finalization
    ok, diag = await validate_finalization(
        db, company_id="co-demo", service_type="rompimento",
        ticket_id="tkt-test-romp-2", service_id=None, subscriber_id=None,
        collaborator_id="col-test-1",
        completion_data={"praca_id": "prc-test"},
    )
    assert not ok, f"Rompimento sem report passou: {diag}"
    assert "report_text" in diag["missing"]


@pytest.mark.asyncio
async def test_rompimento_blocked_without_praca(db):
    from services.os_finalization_validator import validate_finalization
    ok, diag = await validate_finalization(
        db, company_id="co-demo", service_type="rompimento",
        ticket_id="tkt-test-romp-3", service_id=None, subscriber_id=None,
        collaborator_id="col-test-1",
        completion_data={"report_text": "Resolvi"},
    )
    assert not ok
    assert "praca_id" in diag["missing"]


@pytest.mark.asyncio
async def test_rompimento_blocked_without_collab(db):
    from services.os_finalization_validator import validate_finalization
    ok, diag = await validate_finalization(
        db, company_id="co-demo", service_type="rompimento",
        ticket_id="tkt-test-romp-4", service_id=None, subscriber_id=None,
        collaborator_id=None,
        completion_data={"praca_id": "p", "report_text": "Resolvido"},
    )
    assert not ok
    assert "collaborator_id" in diag["missing"]


@pytest.mark.asyncio
async def test_rompimento_with_override(db):
    from services.os_finalization_validator import validate_finalization
    ok, diag = await validate_finalization(
        db, company_id="co-demo", service_type="rompimento",
        ticket_id="tkt-test-romp-5", service_id=None, subscriber_id=None,
        collaborator_id="col-test-1",
        completion_data={
            "onda3_override_reason": (
                "Justificativa de gestor: emergencial, sem praca cadastrada."
            ),
        },
    )
    assert ok
    assert diag["override_used"] is True


@pytest.mark.asyncio
async def test_non_operational_informada_blocked_short_reason(db):
    from services.os_finalization_validator import validate_finalization
    ok, diag = await validate_finalization(
        db, company_id="co-demo", service_type="reparo",
        ticket_id="tkt-test-nop-1", service_id=None,
        subscriber_id="sub-x", collaborator_id="mgr-1",
        completion_data={
            "outcome": "informada", "manager_close_reason": "ok",
        },
    )
    assert not ok
    assert "manager_close_reason_min20" in diag["missing"]


@pytest.mark.asyncio
async def test_non_operational_informada_passes(db):
    from services.os_finalization_validator import validate_finalization
    ok, diag = await validate_finalization(
        db, company_id="co-demo", service_type="reparo",
        ticket_id="tkt-test-nop-2", service_id=None,
        subscriber_id="sub-x", collaborator_id="mgr-1",
        completion_data={
            "outcome": "informada",
            "manager_close_reason": (
                "Cliente confirmou retorno do sinal apos restart remoto"
            ),
        },
    )
    assert ok
    assert diag["service_type_status"] == "non_operational"
    assert diag["outcome"] == "informada"


@pytest.mark.asyncio
async def test_non_operational_cancelada_passes(db):
    from services.os_finalization_validator import validate_finalization
    ok, diag = await validate_finalization(
        db, company_id="co-demo", service_type="instalacao",
        ticket_id="tkt-test-nop-3", service_id=None,
        subscriber_id="sub-x", collaborator_id="mgr-1",
        completion_data={
            "outcome": "cancelada",
            "manager_close_reason": (
                "Cliente desistiu da contratacao; agendamento cancelado"
            ),
        },
    )
    assert ok
    assert diag["outcome"] == "cancelada"


@pytest.mark.asyncio
async def test_sucesso_normal_still_enforces_ont(db):
    """Garante que outcome=sucesso ainda exige ONT/CTO/Porta."""
    from services.os_finalization_validator import validate_finalization
    ok, diag = await validate_finalization(
        db, company_id="co-demo", service_type="instalacao",
        ticket_id="tkt-test-suc-1", service_id="sv-1",
        subscriber_id="sub-x", collaborator_id="col-1",
        completion_data={"outcome": "sucesso"},
    )
    assert not ok, f"Sucesso sem ONT passou: {diag}"
    assert "ont_identifier" in diag["missing"]


@pytest.mark.asyncio
async def test_rompimento_not_in_enforced_types():
    """Confirma que rompimento foi removido da lista de enforced."""
    from services.os_finalization_validator import (
        ENFORCED_SERVICE_TYPES, ROMPIMENTO_TYPES,
    )
    assert "rompimento" not in ENFORCED_SERVICE_TYPES
    assert "rompimento" in ROMPIMENTO_TYPES
