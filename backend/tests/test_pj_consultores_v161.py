"""Testes do CRUD multi-consultores PJ (V16.1).

Segue o padrão de test_pj_v16.py: plain async def sem fixtures, sem
@pytest.mark.asyncio (pytest-asyncio mode=auto resolve).

Cobertura:
  • create/list/update/delete
  • validação (nome vazio, whatsapp curto, sla fora de range)
  • round-robin via _pick_next_consultor
  • pj_flow_is_active: True quando >=1 ativo, False sem consultor
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")

sys.path.insert(0, "/app/backend")
for ln in open("/app/backend/.env"):
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ.setdefault(k, v.strip('"'))

CID = "TEST-PJ-V161-CONS"


async def _cleanup():
    from database import db
    await db.pj_consultores.delete_many({"company_id": CID})
    await db.pj_consultor_config.delete_many({"company_id": CID})


async def test_create_normalizes_phone():
    await _cleanup()
    from services.pj_lead_router import create_consultor
    doc = await create_consultor(company_id=CID, payload={
        "nome": "João", "whatsapp": "+55 (11) 98765-4321",
        "email": "j@x.com", "sla_minutos": 15, "ativo": True,
    })
    assert doc["whatsapp"] == "5511987654321"
    assert doc["ativo"] is True
    assert doc["id"].startswith("pjcon-")
    await _cleanup()
    print("  ✓ create_consultor normaliza phone + retorna id pjcon-...")


async def test_create_validates():
    await _cleanup()
    from services.pj_lead_router import create_consultor
    with pytest.raises(ValueError, match="nome"):
        await create_consultor(company_id=CID, payload={
            "nome": "", "whatsapp": "5511987654321"})
    with pytest.raises(ValueError, match="whatsapp"):
        await create_consultor(company_id=CID, payload={
            "nome": "X", "whatsapp": "123"})
    with pytest.raises(ValueError, match="sla_minutos"):
        await create_consultor(company_id=CID, payload={
            "nome": "X", "whatsapp": "5511987654321", "sla_minutos": 999})
    print("  ✓ validações: nome obrigatório, whatsapp DDI, sla 1-240")


async def test_list_returns_all():
    await _cleanup()
    from services.pj_lead_router import create_consultor, list_consultores
    for i in range(3):
        await create_consultor(company_id=CID, payload={
            "nome": f"C{i}", "whatsapp": f"551198765432{i}",
            "sla_minutos": 15, "ativo": True})
    items = await list_consultores(company_id=CID)
    assert len(items) == 3
    await _cleanup()
    print("  ✓ list_consultores devolve todos os 3 cadastrados")


async def test_update_changes_fields():
    await _cleanup()
    from services.pj_lead_router import create_consultor, update_consultor
    c = await create_consultor(company_id=CID, payload={
        "nome": "Old", "whatsapp": "5511987654321",
        "sla_minutos": 15, "ativo": True})
    out = await update_consultor(
        company_id=CID, consultor_id=c["id"],
        payload={"nome": "New", "whatsapp": "5511999999999",
                  "sla_minutos": 60, "ativo": False},
    )
    assert out["nome"] == "New"
    assert out["sla_minutos"] == 60
    assert out["ativo"] is False
    await _cleanup()
    print("  ✓ update_consultor atualiza campos corretamente")


async def test_update_not_found_returns_none():
    from services.pj_lead_router import update_consultor
    out = await update_consultor(
        company_id=CID, consultor_id="pjcon-doesnt-exist",
        payload={"nome": "X", "whatsapp": "5511987654321",
                  "sla_minutos": 15, "ativo": True},
    )
    assert out is None
    print("  ✓ update inexistente retorna None")


async def test_delete_removes():
    await _cleanup()
    from services.pj_lead_router import create_consultor, delete_consultor
    c = await create_consultor(company_id=CID, payload={
        "nome": "X", "whatsapp": "5511987654321",
        "sla_minutos": 15, "ativo": True})
    ok = await delete_consultor(company_id=CID, consultor_id=c["id"])
    assert ok is True
    ok2 = await delete_consultor(company_id=CID, consultor_id=c["id"])
    assert ok2 is False
    await _cleanup()
    print("  ✓ delete: 1ª True, 2ª False (idempotente)")


async def test_round_robin_picks_inactive_skipped():
    await _cleanup()
    from database import db
    from services.pj_lead_router import (
        create_consultor, _pick_next_consultor,
    )
    await create_consultor(company_id=CID, payload={
        "nome": "A", "whatsapp": "5511111111111",
        "sla_minutos": 15, "ativo": True})
    await create_consultor(company_id=CID, payload={
        "nome": "B", "whatsapp": "5511222222222",
        "sla_minutos": 15, "ativo": True})
    # C inativo NUNCA deve ser escolhido
    await create_consultor(company_id=CID, payload={
        "nome": "C", "whatsapp": "5511333333333",
        "sla_minutos": 15, "ativo": False})

    picks = []
    for _ in range(4):
        p = await _pick_next_consultor(company_id=CID)
        assert p is not None
        picks.append(p["nome"])
        await db.pj_consultores.update_one(
            {"_id": p["_id"]},
            {"$set": {"last_notified_at": datetime.now(timezone.utc)}},
        )
        await asyncio.sleep(0.01)
    assert "C" not in picks, f"consultor inativo escolhido: {picks}"
    assert picks.count("A") == 2
    assert picks.count("B") == 2
    await _cleanup()
    print(f"  ✓ round-robin: {picks} (inativos ignorados)")


async def test_pj_flow_active_via_multi():
    await _cleanup()
    from services.pj_lead_router import (
        create_consultor, pj_flow_is_active,
    )
    assert await pj_flow_is_active(company_id=CID) is False
    await create_consultor(company_id=CID, payload={
        "nome": "X", "whatsapp": "5511111111111",
        "sla_minutos": 15, "ativo": False})
    assert await pj_flow_is_active(company_id=CID) is False
    await create_consultor(company_id=CID, payload={
        "nome": "Y", "whatsapp": "5511222222222",
        "sla_minutos": 15, "ativo": True})
    assert await pj_flow_is_active(company_id=CID) is True
    await _cleanup()
    print("  ✓ pj_flow_is_active reflete consultores ativos")
