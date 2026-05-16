"""Iter84 — Liberar bolha presa: endpoint admin + audit + notification."""
import asyncio
import sys
import uuid
from datetime import datetime, timezone

import pytest

sys.path.insert(0, "/app/backend")
from database import db as _module_db  # noqa: E402


CID = "co-demo"


def _iso():
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _seed_ticket(coll_id, status="aberta", opened_at=None):
    tid = f"tkt-iter84-{uuid.uuid4().hex[:6]}"
    return {
        "id": tid,
        "company_id": CID,
        "assigned_collaborator_id": coll_id,
        "status": status,
        "opened_at": opened_at or _iso(),
        "whatsapp_status": "enviado",
        "whatsapp_last_message": "...",
        "client_snapshot": {
            "name": "TEST · Cliente Iter84",
            "address": "Rua Teste, 1",
            "phone": "5599000000000",
        },
        "type": "reparo", "priority": "normal", "position": 1,
        "scheduled_time": _iso(),
        "created_at": _iso(),
    }


def test_release_stuck_endpoint_full_flow(event_loop):
    """Reseta status, gera log + notification, retorna ticket liberado."""
    coll_id = "col-iter84-test"
    ticket = _seed_ticket(coll_id)

    async def main():
        # seed
        await _module_db.tickets.delete_many({"id": ticket["id"]})
        await _module_db.collaborators.delete_many({"id": coll_id})
        await _module_db.tickets.insert_one(ticket)
        await _module_db.collaborators.insert_one({
            "id": coll_id, "company_id": CID, "name": "TÉCNICO TESTE",
            "clock_in_enabled": True,
        })

        # Importa e simula o user admin (require_role middleware bypass)
        from routes.lousa import release_stuck_ticket, ReleaseStuckIn
        admin_user = {
            "id": "user-admin-iter84",
            "name": "Admin Teste",
            "email": "admin@empresa.com",
            "role": "administrador",
            "company_id": CID,
        }

        # Limpa eventuais notifications anteriores
        await _module_db.notifications.delete_many(
            {"type": "bolha_liberada_admin", "ticket_id": ticket["id"]})
        await _module_db.ticket_logs.delete_many({"ticket_id": ticket["id"]})

        # Chama o endpoint diretamente
        result = await release_stuck_ticket(
            ReleaseStuckIn(collaborator_id=coll_id,
                            reason="teste integração iter84"),
            admin_user,
        )

        # Asserts
        assert result["ok"] is True
        assert result["collaborator_id"] == coll_id
        assert result["collaborator_name"] == "TÉCNICO TESTE"
        assert result["freed_ticket"]["status"] == "pendente"
        assert "opened_at" not in result["freed_ticket"]
        assert "whatsapp_status" not in result["freed_ticket"]

        # Verifica log de auditoria
        log = await _module_db.ticket_logs.find_one(
            {"ticket_id": ticket["id"], "action": "liberada_admin"},
            {"_id": 0})
        assert log is not None
        assert log["actor_name"] == "Admin Teste"
        assert log["actor_role"] == "administrador"
        assert "TÉCNICO TESTE" in log["details"]
        assert "teste integração iter84" in log["details"]

        # Verifica notification
        ntf = await _module_db.notifications.find_one(
            {"type": "bolha_liberada_admin", "ticket_id": ticket["id"]},
            {"_id": 0})
        assert ntf is not None
        assert ntf["severity"] == "critical"
        assert ntf["collaborator_id"] == coll_id
        assert "Admin Teste" in ntf["message"]
        assert "TÉCNICO TESTE" in ntf["message"]

        # Cleanup
        await _module_db.tickets.delete_many({"id": ticket["id"]})
        await _module_db.collaborators.delete_many({"id": coll_id})
        await _module_db.notifications.delete_many({"ticket_id": ticket["id"]})
        await _module_db.ticket_logs.delete_many({"ticket_id": ticket["id"]})

    event_loop.run_until_complete(main())


def test_release_stuck_returns_404_when_no_stuck(event_loop):
    async def main():
        from fastapi import HTTPException
        from routes.lousa import release_stuck_ticket, ReleaseStuckIn
        admin_user = {
            "id": "u", "name": "A", "role": "administrador", "company_id": CID,
        }
        with pytest.raises(HTTPException) as exc:
            await release_stuck_ticket(
                ReleaseStuckIn(collaborator_id="col-does-not-exist-iter84"),
                admin_user,
            )
        assert exc.value.status_code == 404
        assert "Nenhuma bolha presa" in exc.value.detail

    event_loop.run_until_complete(main())


def test_release_stuck_picks_oldest_when_multiple(event_loop):
    """Se colab tem 2 bolhas 'aberta', libera a mais antiga (sort opened_at:1)."""
    coll_id = "col-iter84-multi"
    older_iso = "2026-05-01T10:00:00+00:00"
    newer_iso = "2026-05-15T10:00:00+00:00"
    t_old = _seed_ticket(coll_id, opened_at=older_iso)
    t_new = _seed_ticket(coll_id, opened_at=newer_iso)

    async def main():
        await _module_db.tickets.delete_many(
            {"id": {"$in": [t_old["id"], t_new["id"]]}})
        await _module_db.collaborators.delete_many({"id": coll_id})
        await _module_db.tickets.insert_many([t_old, t_new])
        await _module_db.collaborators.insert_one({
            "id": coll_id, "company_id": CID, "name": "MULTI",
            "clock_in_enabled": True,
        })

        from routes.lousa import release_stuck_ticket, ReleaseStuckIn
        result = await release_stuck_ticket(
            ReleaseStuckIn(collaborator_id=coll_id),
            {"id": "u", "name": "A", "role": "administrador", "company_id": CID},
        )
        # A mais antiga foi liberada
        assert result["freed_ticket"]["id"] == t_old["id"]
        assert result["freed_ticket"]["status"] == "pendente"

        # A mais nova continua aberta
        new_state = await _module_db.tickets.find_one(
            {"id": t_new["id"]}, {"_id": 0})
        assert new_state["status"] == "aberta"

        # Cleanup
        await _module_db.tickets.delete_many(
            {"id": {"$in": [t_old["id"], t_new["id"]]}})
        await _module_db.collaborators.delete_many({"id": coll_id})
        await _module_db.notifications.delete_many(
            {"ticket_id": {"$in": [t_old["id"], t_new["id"]]}})
        await _module_db.ticket_logs.delete_many(
            {"ticket_id": {"$in": [t_old["id"], t_new["id"]]}})

    event_loop.run_until_complete(main())


def test_stuck_tickets_listing_endpoint(event_loop):
    """O endpoint GET lista colaboradores com bolha aberta + minutos presa."""
    coll_id = "col-iter84-listing"
    ticket = _seed_ticket(coll_id)

    async def main():
        await _module_db.tickets.delete_many({"id": ticket["id"]})
        await _module_db.collaborators.delete_many({"id": coll_id})
        await _module_db.tickets.insert_one(ticket)
        await _module_db.collaborators.insert_one({
            "id": coll_id, "company_id": CID, "name": "TÉCNICO LIST",
            "clock_in_enabled": True,
        })

        from routes.lousa import list_stuck_tickets
        result = await list_stuck_tickets(
            {"id": "u", "name": "A", "role": "administrador",
             "company_id": CID},
        )
        items = result.get("items", [])
        ours = [i for i in items if i["collaborator_id"] == coll_id]
        assert len(ours) == 1
        assert ours[0]["collaborator_name"] == "TÉCNICO LIST"
        assert ours[0]["client_name"] == "TEST · Cliente Iter84"
        assert ours[0]["minutes_stuck"] is not None
        assert ours[0]["minutes_stuck"] >= 0

        # Cleanup
        await _module_db.tickets.delete_many({"id": ticket["id"]})
        await _module_db.collaborators.delete_many({"id": coll_id})

    event_loop.run_until_complete(main())
