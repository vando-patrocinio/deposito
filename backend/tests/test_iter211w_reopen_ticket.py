"""
test_iter211w_reopen_ticket.py
==============================
Garante que POST /api/lousa/tickets/{id}/reopen:
  - Devolve o status para 'pendente'
  - Arquiva fechamento anterior em previous_completions[] (com revert_summary)
  - Limpa closed_at / completion_data / signal_at_close / opened_at / etc
  - Incrementa reopen_count
  - DESFAZ os efeitos colaterais (iter211w++ 02/06/2026):
      • Re-credita consumíveis (drop/esticadores/conectores)
      • Reativa stok_service (status volta para 'ativo')
      • Libera porta da CTO (status='free')
      • Devolve ONT instalada para o estoque do técnico
  - Rejeita reabertura de nota não-fechada (409) / inexistente (404)
  - Rejeita motivo < 3 chars (422 via pydantic)
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_iter211w_reopen")

from database import db  # noqa: E402
from routes.lousa import reopen_ticket, ReopenIn  # noqa: E402


@pytest.mark.asyncio
async def test_reopen_full_flow_with_revert():
    """Único teste async que cobre: sucesso + revert de estoque/porta/ONT,
    409 (já pendente), 404. Combinado em uma só função para reusar o event
    loop (evita conflitos com motor client global)."""
    from fastapi import HTTPException
    tid = f"tkt-test-{uuid.uuid4().hex[:8]}"
    sid = f"sv-test-{uuid.uuid4().hex[:8]}"
    company_id = "co-test-iter211w"
    tech_id = "tech-revert-1"
    client_id = "cli-revert-1"
    cto_id = f"cto-test-{uuid.uuid4().hex[:6]}"
    mac = "AA:BB:CC:DD:EE:01"

    # Setup: cria ticket fechado com vínculos a stok_services + stok_onts + cto
    await db.tickets.insert_one({
        "id": tid, "company_id": company_id,
        "status": "finalizada", "type": "instalacao",
        "client_snapshot": {"id": client_id, "name": "Cliente Revert"},
        "assigned_collaborator_id": tech_id, "collaborator_name": "Téc Revert",
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "closed_by": tech_id,
        "completion_data": {
            "sinal": -22.5, "ont": mac, "ont_sn": "HWTC00000001",
            "cto_id": cto_id, "cto_port_number": 3,
            "fotos": [{"dataUrl": "data:image/jpeg;base64,xyz"}],
        },
        "signal_at_open": -20.0, "signal_at_close": -22.5,
        "opened_at": "2026-05-15T10:00:00+00:00",
        "created_at": "2026-05-15T09:00:00+00:00",
    })
    await db.stok_services.insert_one({
        "id": sid, "company_id": company_id, "ticket_id": tid,
        "type": "instalacao", "technician_id": tech_id,
        "client_id": client_id, "client_name": "Cliente Revert",
        "status": "fechado",
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "auto_closed": True,
        "auto_closed_used_items": [
            {"consumable_id": "drop", "quantity": 35},
            {"consumable_id": "fast", "quantity": 2},
        ],
    })
    # ONT já no cliente (efeito do fechamento)
    await db.stok_onts.insert_one({
        "company_id": company_id, "mac": mac, "scan_sn": "HWTC00000001",
        "location_type": "cliente", "location_id": client_id,
        "client_name": "Cliente Revert", "status": "instalada",
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "installed_by_id": tech_id, "installed_via_ticket": tid,
        "installed_via_service": sid,
    })
    # CTO com porta 3 ocupada pelo ticket
    await db.ctos.insert_one({
        "id": cto_id, "company_id": company_id, "name": "CTO-TEST",
        "ports": [
            {"number": 1, "status": "free"},
            {"number": 2, "status": "free"},
            {"number": 3, "status": "used",
             "client_subscriber_id": client_id,
             "client_name": "Cliente Revert",
             "connected_via_ticket": tid,
             "connected_at": datetime.now(timezone.utc).isoformat()},
            {"number": 4, "status": "free"},
        ],
    })
    # Estoque do técnico com saldo negativo após decremento da finalize
    await db.stok_stock.insert_one({
        "company_id": company_id, "location": tech_id,
        "drop": 65,   # tinha 100, gastou 35
        "fast": 8,    # tinha 10, gastou 2
    })

    try:
        user = {"role": "gestor", "company_id": company_id,
                "email": "gestor@test", "name": "Gestor",
                "id": "u-revert-1"}

        # 1) Reopen com revert
        out = await reopen_ticket(tid, ReopenIn(reason="cliente reclamou"), user)
        assert out["status"] == "pendente"
        assert out["reopen_count"] == 1
        assert out.get("reopened_by") == "gestor@test"
        assert out.get("closed_at") is None
        assert out.get("completion_data") is None
        assert out.get("opened_at") is None
        assert out.get("signal_at_close") is None

        # 2) Validar revert_summary
        rs = out.get("revert_summary") or {}
        assert rs.get("ont_reverted", {}).get("mac") == mac
        assert rs.get("ont_reverted", {}).get("back_to_tech") == tech_id
        assert rs.get("cto_port_freed", {}).get("cto_id") == cto_id
        assert rs.get("cto_port_freed", {}).get("port") == 3
        assert rs.get("consumables_recredited", {}) == {"drop": 35, "fast": 2}
        assert rs.get("stok_service_reactivated") == sid

        # 3) Validar no banco — ONT voltou para o técnico, status disponivel
        ont = await db.stok_onts.find_one({"company_id": company_id, "mac": mac},
                                            {"_id": 0})
        assert ont["location_type"] == "tecnico"
        assert ont["location_id"] == tech_id
        assert ont["status"] == "disponivel"
        assert "installed_via_ticket" not in ont

        # 4) Porta da CTO livre
        cto = await db.ctos.find_one({"id": cto_id}, {"_id": 0})
        port3 = next(p for p in cto["ports"] if p["number"] == 3)
        assert port3["status"] == "free"
        assert "client_subscriber_id" not in port3 or port3.get("client_subscriber_id") is None
        assert "connected_via_ticket" not in port3 or port3.get("connected_via_ticket") is None

        # 5) Consumíveis recreditados
        stk = await db.stok_stock.find_one({"company_id": company_id,
                                              "location": tech_id}, {"_id": 0})
        assert stk["drop"] == 100  # 65 + 35
        assert stk["fast"] == 10   # 8 + 2

        # 6) stok_service reativado
        svc = await db.stok_services.find_one({"id": sid}, {"_id": 0})
        assert svc["status"] == "ativo"
        assert "closed_at" not in svc
        assert "auto_closed_used_items" not in svc

        # 7) Fechamento arquivado em previous_completions[]
        archived = out["previous_completions"][0]
        assert archived["previous_status"] == "finalizada"
        assert archived["reason"] == "cliente reclamou"
        assert archived["previous_completion_data"]["sinal"] == -22.5
        assert "revert_summary" in archived

        # 8) Segunda tentativa → 409 (já pendente)
        with pytest.raises(HTTPException) as exc:
            await reopen_ticket(tid, ReopenIn(reason="segundo"), user)
        assert exc.value.status_code == 409

        # 9) Ticket inexistente → 404
        with pytest.raises(HTTPException) as exc:
            await reopen_ticket("tkt-doesnt-exist-xyz",
                                 ReopenIn(reason="qualquer motivo"), user)
        assert exc.value.status_code == 404
    finally:
        await db.tickets.delete_one({"id": tid})
        await db.stok_services.delete_one({"id": sid})
        await db.stok_onts.delete_one({"company_id": company_id, "mac": mac})
        await db.ctos.delete_one({"id": cto_id})
        await db.stok_stock.delete_one({"company_id": company_id,
                                          "location": tech_id})


def test_reopen_payload_rejects_short_reason():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ReopenIn(reason="x")
    # Ok com >= 3 chars
    ok = ReopenIn(reason="abc", keep_technician=False)
    assert ok.keep_technician is False
