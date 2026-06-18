"""Onda C P1 — Solicitação de Confirmação Patrimonial via WhatsApp.

Testa:
  - Validação de status (só pending_confirmation ou sent_to_technician).
  - HMAC token (rejeita forjado).
  - 3 caminhos: CONFIRMO / NÃO HOUVE TROCA / PRECISO REVISAR.
  - Auditoria completa em auto_ont_swap_confirmations.
  - Idempotência (clicar 2x no mesmo link não duplica status mudança).
  - REGRA DE OURO: NÃO altera stok_stock, stok_history, stok_services.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

sys.path.insert(0, "/app/backend")
for ln in open("/app/backend/.env"):
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ.setdefault(k, v.strip('"'))

pytestmark = pytest.mark.asyncio(loop_scope="session")
CID = "TEST-SWAP-CONFIRM"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


async def _cleanup():
    from database import db
    await db.auto_ont_swap_events.delete_many({"company_id": CID})
    await db.auto_ont_swap_confirmations.delete_many({"company_id": CID})
    await db.collaborators.delete_many({"company_id": CID})


async def _seed_tech(phone="11999998888"):
    from database import db
    tid = f"col-test-{uuid.uuid4().hex[:8]}"
    cpf = f"99999{uuid.uuid4().hex[:6]}"
    await db.collaborators.update_one(
        {"id": tid},
        {"$set": {
            "id": tid, "company_id": CID, "name": "TEC TEST SWAP",
            "phone": phone, "cpf": cpf, "cargo": "tecnico", "active": True,
            "created_at": _now_iso(),
        }},
        upsert=True,
    )
    return tid


async def _seed_event(tid, status="pending_confirmation"):
    from database import db
    eid = f"auto-swap-{uuid.uuid4().hex[:12]}"
    await db.auto_ont_swap_events.insert_one({
        "id": eid, "company_id": CID,
        "ticket_id": f"tkt-{uuid.uuid4().hex[:8]}",
        "ticket_type": "reparo",
        "ont_anterior": "ALCL11112222",
        "ont_atual": "HWTC99998888",
        "technician_id": tid,
        "status": status,
        "detected_at": _now_iso(),
        "detected_by": "auto_detect_v1",
    })
    return eid


# ─────────────────────── 1) HMAC token correctness ───────────────────────

async def test_hmac_token_round_trip():
    from routes.swap_confirmation import _hmac_token
    t1 = _hmac_token("evt1", "confirmed")
    t2 = _hmac_token("evt1", "confirmed")
    t3 = _hmac_token("evt1", "disputed")
    assert t1 == t2  # determinístico
    assert t1 != t3  # depende da choice
    assert len(t1) == 24


# ─────────────────────── 2) Estados inválidos rejeitam ───────────────────

async def test_send_rejects_already_confirmed():
    from routes.swap_confirmation import send_swap_confirmation
    await _cleanup()
    tid = await _seed_tech()
    eid = await _seed_event(tid, status="confirmed")
    user = {"company_id": CID, "name": "test-admin", "role": "gestor"}
    with pytest.raises(HTTPException) as exc:
        await send_swap_confirmation(eid, user=user)
    assert exc.value.status_code == 400
    detail = exc.value.detail
    assert detail.get("error") == "invalid_state"
    await _cleanup()


async def test_send_rejects_event_from_other_company():
    from routes.swap_confirmation import send_swap_confirmation
    await _cleanup()
    tid = await _seed_tech()
    eid = await _seed_event(tid)
    user = {"company_id": "OTHER-COMPANY", "name": "x", "role": "gestor"}
    with pytest.raises(HTTPException) as exc:
        await send_swap_confirmation(eid, user=user)
    assert exc.value.status_code == 403
    await _cleanup()


async def test_send_rejects_technician_without_phone():
    from routes.swap_confirmation import send_swap_confirmation
    await _cleanup()
    tid = await _seed_tech(phone="")
    eid = await _seed_event(tid)
    user = {"company_id": CID, "name": "test-admin", "role": "gestor"}
    with pytest.raises(HTTPException) as exc:
        await send_swap_confirmation(eid, user=user)
    assert exc.value.detail.get("error") == "technician_without_phone"
    await _cleanup()


# ─────────────────────── 3) Respond — 3 caminhos ─────────────────────────

async def _respond_for(eid, choice):
    from routes.swap_confirmation import (
        _hmac_token, respond_swap_confirmation_post, RespondBody,
    )
    tok = _hmac_token(eid, choice)
    return await respond_swap_confirmation_post(
        RespondBody(event_id=eid, token=tok, choice=choice,
                    raw_text=f"raw input: {choice}"),
    )


async def test_respond_confirmo_marks_confirmed():
    from database import db
    await _cleanup()
    tid = await _seed_tech()
    eid = await _seed_event(tid)
    res = await _respond_for(eid, "confirmed")
    assert res["ok"] is True
    assert res["new_status"] == "confirmed"
    assert res["response"] == "CONFIRMO"
    # evento atualizado
    evt = await db.auto_ont_swap_events.find_one({"id": eid}, {"_id": 0})
    assert evt["status"] == "confirmed"
    assert evt.get("confirmation_response") == "CONFIRMO"
    # audit gravado
    conf = await db.auto_ont_swap_confirmations.find_one(
        {"swap_event_id": eid}, {"_id": 0})
    assert conf is not None
    assert conf["response"] == "CONFIRMO"
    assert conf["origin"] == "whatsapp_patrimonial_confirmation"
    assert conf["technician_id"] == tid
    assert conf["ont_anterior"] == "ALCL11112222"
    assert conf["ont_atual"] == "HWTC99998888"
    assert "confirmation_audit_id" in conf
    await _cleanup()


async def test_respond_disputed_keeps_pendency():
    from database import db
    await _cleanup()
    tid = await _seed_tech()
    eid = await _seed_event(tid)
    res = await _respond_for(eid, "disputed")
    assert res["new_status"] == "disputed"
    assert res["response"] == "NÃO HOUVE TROCA"
    # evento marcado como disputado (continua pendência para gestor)
    evt = await db.auto_ont_swap_events.find_one({"id": eid}, {"_id": 0})
    assert evt["status"] == "disputed"
    await _cleanup()


async def test_respond_needs_review_keeps_pendency():
    from database import db
    await _cleanup()
    tid = await _seed_tech()
    eid = await _seed_event(tid)
    res = await _respond_for(eid, "needs_review")
    assert res["new_status"] == "needs_review"
    assert res["response"] == "PRECISO REVISAR"
    evt = await db.auto_ont_swap_events.find_one({"id": eid}, {"_id": 0})
    assert evt["status"] == "needs_review"
    await _cleanup()


# ─────────────────────── 4) Token forjado rejeita ────────────────────────

async def test_respond_with_invalid_token_403():
    from routes.swap_confirmation import (
        respond_swap_confirmation_post, RespondBody,
    )
    await _cleanup()
    tid = await _seed_tech()
    eid = await _seed_event(tid)
    with pytest.raises(HTTPException) as exc:
        await respond_swap_confirmation_post(RespondBody(
            event_id=eid, token="forjado-1234", choice="confirmed",
        ))
    assert exc.value.status_code == 403
    await _cleanup()


async def test_respond_with_invalid_choice_400():
    from routes.swap_confirmation import (
        respond_swap_confirmation_post, RespondBody, _hmac_token,
    )
    await _cleanup()
    tid = await _seed_tech()
    eid = await _seed_event(tid)
    tok = _hmac_token(eid, "confirmed")
    with pytest.raises(HTTPException) as exc:
        await respond_swap_confirmation_post(RespondBody(
            event_id=eid, token=tok, choice="lololo",
        ))
    assert exc.value.status_code == 400
    await _cleanup()


# ─────────────────────── 5) Idempotência (clique duplo) ──────────────────

async def test_respond_idempotent_double_click():
    from database import db
    await _cleanup()
    tid = await _seed_tech()
    eid = await _seed_event(tid)
    res1 = await _respond_for(eid, "confirmed")
    res2 = await _respond_for(eid, "confirmed")
    assert res1["idempotent_skip"] is False
    assert res2["idempotent_skip"] is True
    # 2 audits criados (append-only), mas status do evento mudou só uma vez
    n_audits = await db.auto_ont_swap_confirmations.count_documents(
        {"swap_event_id": eid})
    assert n_audits == 2
    evt = await db.auto_ont_swap_events.find_one({"id": eid}, {"_id": 0})
    assert evt["status"] == "confirmed"
    await _cleanup()


# ─────────────────────── 6) Regra de ouro: ZERO STOCK ────────────────────

async def test_no_stock_collection_touched():
    """REGRA CEO: este fluxo é apenas auditoria. NUNCA altera estoque."""
    from database import db
    await _cleanup()
    tid = await _seed_tech()
    eid = await _seed_event(tid)

    # Snapshot pré
    stock_before = await db.stok_stock.count_documents({})
    history_before = await db.stok_history.count_documents({})
    services_before = await db.stok_services.count_documents({})

    # Roda os 3 caminhos
    eid2 = await _seed_event(tid)
    eid3 = await _seed_event(tid)
    await _respond_for(eid, "confirmed")
    await _respond_for(eid2, "disputed")
    await _respond_for(eid3, "needs_review")

    # Snapshot pós
    stock_after = await db.stok_stock.count_documents({})
    history_after = await db.stok_history.count_documents({})
    services_after = await db.stok_services.count_documents({})

    assert stock_after == stock_before, "stok_stock foi modificado — violação da regra de ouro"
    assert history_after == history_before, "stok_history foi modificado — violação"
    assert services_after == services_before, "stok_services foi modificado — violação"
    await _cleanup()


# ─────────────────────── 7) Watchtower reflete breakdown ─────────────────

async def test_watchtower_shows_breakdown():
    """Watchtower diagnostico mostra by_status com os 3 caminhos."""
    from database import db
    from routes.watchtower_estoque_diagnostico import (
        watchtower_estoque_diagnostico,
    )
    await _cleanup()
    tid = await _seed_tech()
    e1 = await _seed_event(tid)
    e2 = await _seed_event(tid)
    e3 = await _seed_event(tid)
    e4 = await _seed_event(tid)  # fica pending
    await _respond_for(e1, "confirmed")
    await _respond_for(e2, "disputed")
    await _respond_for(e3, "needs_review")

    res = await watchtower_estoque_diagnostico(
        user={"company_id": CID, "role": "gestor"}, window_hours=24,
    )
    bd = res["swap_pending"]["breakdown"]
    assert bd["confirmed"] == 1
    assert bd["disputed"] == 1
    assert bd["needs_review"] == 1
    assert bd["pending_confirmation"] == 1
    # total_pending = pending+sent+disputed+needs_review = 3 (não conta confirmed)
    assert res["swap_pending"]["total_pending"] == 3
    await _cleanup()


# ─────────────────────── 8) List endpoint ────────────────────────────────

async def test_list_endpoint_returns_counts():
    from routes.swap_confirmation import list_swap_confirmations
    await _cleanup()
    tid = await _seed_tech()
    e1 = await _seed_event(tid)
    await _seed_event(tid)
    await _respond_for(e1, "confirmed")
    user = {"company_id": CID, "name": "test", "role": "gestor"}
    res = await list_swap_confirmations(user=user)
    assert res["total"] == 2
    assert res["counts_by_status"].get("confirmed", 0) == 1
    assert res["counts_by_status"].get("pending_confirmation", 0) == 1
    await _cleanup()


if __name__ == "__main__":
    async def _main():
        await test_hmac_token_round_trip()
        await test_send_rejects_already_confirmed()
        await test_send_rejects_event_from_other_company()
        await test_send_rejects_technician_without_phone()
        await test_respond_confirmo_marks_confirmed()
        await test_respond_disputed_keeps_pendency()
        await test_respond_needs_review_keeps_pendency()
        await test_respond_with_invalid_token_403()
        await test_respond_with_invalid_choice_400()
        await test_respond_idempotent_double_click()
        await test_no_stock_collection_touched()
        await test_watchtower_shows_breakdown()
        await test_list_endpoint_returns_counts()
        print("✅ Swap Confirmation — 13/13 tests PASS")
    asyncio.run(_main())
