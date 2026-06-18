"""Onda C — HTTP REST regression for Lousa Mobile finalize hardening.

Seeds tickets/collaborators via Mongo, then exercises the public endpoint
through the external REACT_APP_BACKEND_URL to ensure the wiring works
through ingress (k8s) → uvicorn → router.

Bug #4 — validação obrigatória de consumíveis (HTTP 400).
Bug #6 — auto-detecção de troca de ONT (auto_ont_swap_events).
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

import pytest
import requests

sys.path.insert(0, "/app/backend")
for ln in open("/app/backend/.env"):
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ.setdefault(k, v.strip('"'))

# Load REACT_APP_BACKEND_URL from frontend/.env (the external preview URL)
for ln in open("/app/frontend/.env"):
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ.setdefault(k, v.strip('"'))

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
CID = "TEST-ONDA-C-AGENT"
CLIENT_ID = "cli-ondac-agent"
COLL_ID = "col-ondac-agent"

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _cleanup():
    from database import db
    await db.tickets.delete_many({"company_id": CID})
    await db.collaborators.delete_many({"company_id": CID})
    await db.clients.delete_many({"company_id": CID})
    await db.stok_services.delete_many({"company_id": CID})
    await db.equipment_swaps.delete_many({"company_id": CID})
    await db.auto_ont_swap_events.delete_many({"company_id": CID})
    await db.lousa_finalize_trace.delete_many({"company_id": CID})
    await db.notifications.delete_many({"company_id": CID})


async def _seed_collaborator():
    from database import db
    cpf = f"88888{uuid.uuid4().hex[:6]}"
    await db.collaborators.update_one(
        {"id": COLL_ID},
        {"$set": {
            "id": COLL_ID, "company_id": CID, "name": "Tec OndaC HTTP",
            "cpf": cpf, "cargo": "tecnico", "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )


async def _seed_ticket(*, ttype: str, current_ont: str = None):
    from database import db
    tid = f"tkt-ondac-http-{uuid.uuid4().hex[:8]}"
    snap = {
        "id": CLIENT_ID, "name": "Cliente HTTP",
        "phone": "11999999999", "address": "Rua Y",
    }
    if current_ont:
        snap["current_ont"] = current_ont
    await db.tickets.insert_one({
        "id": tid, "company_id": CID, "status": "aberta",
        "type": ttype, "client_id": CLIENT_ID,
        "client_snapshot": snap,
        "client_current_ont_at_open": current_ont,
        "assigned_collaborator_id": COLL_ID,
        "assigned_collaborator_name": "Tec OndaC HTTP",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "opened_at": datetime.now(timezone.utc).isoformat(),
    })
    return tid


def _finalize(tid: str, *, outcome="sucesso", ont=None, qtd_drop=0,
              conectores_fast=0, observacoes="", asset_recovered=None,
              new_ont_sn=None, old_ont_sn=None):
    body = {
        "collaborator_id": COLL_ID,
        "outcome": outcome,
        "completion_data": {
            "sinal": -22.5,
            "qtd_drop": qtd_drop,
            "esticadores": 0,
            "conectores_fast": conectores_fast,
            "cabo_rede": 0,
            "conectores_rede": 0,
            "ont": ont,
            "observacoes": observacoes,
            "asset_recovered": asset_recovered,
            "new_ont_sn": new_ont_sn,
            "old_ont_sn": old_ont_sn,
        },
        "latitude": -23.5,
        "longitude": -46.6,
        "signature": None,
    }
    url = f"{BASE_URL}/api/lousa/public/tickets/{tid}/finalize"
    return requests.post(url, json=body, timeout=60)


# ────────────────────────── BUG #4 — Validação HTTP ─────────────────────────

async def test_http_bug4_instalacao_sem_ont():
    await _cleanup()
    await _seed_collaborator()
    tid = await _seed_ticket(ttype="instalacao")
    r = _finalize(tid, ont=None, qtd_drop=50, conectores_fast=2,
                  observacoes="Instalacao completa ok")
    assert r.status_code == 400, f"expected 400 got {r.status_code} {r.text[:300]}"
    body = r.json()
    detail = body.get("detail") if isinstance(body, dict) else body
    # aceita os 2 formatos possíveis (gate Bug#4 ou CTO/foto gate)
    if isinstance(detail, dict):
        if detail.get("error") == "consumiveis_obrigatorios_faltando":
            assert "ONT" in detail.get("missing", [])
        else:
            assert detail.get("code") in (
                "CTO_PORT_REQUIRED", "CONSUMIVEIS_OBRIGATORIOS_FALTANDO",
                "PHOTO_REQUIRED",
            ), detail
    else:
        assert "ONT" in str(detail) or "obrigat" in str(detail).lower()
    await _cleanup()


async def test_http_bug4_instalacao_sem_drop():
    await _cleanup()
    await _seed_collaborator()
    tid = await _seed_ticket(ttype="instalacao")
    r = _finalize(tid, ont="48575443ABCD", qtd_drop=0, conectores_fast=2,
                  observacoes="Instalacao no apto 12")
    assert r.status_code == 400, f"got {r.status_code} {r.text[:300]}"
    detail = r.json().get("detail", {})
    if isinstance(detail, dict) and detail.get("error") == "consumiveis_obrigatorios_faltando":
        missing = detail.get("missing", [])
        assert any("DROP" in m for m in missing), missing
    await _cleanup()


async def test_http_bug4_instalacao_sem_conector_sem_just():
    await _cleanup()
    await _seed_collaborator()
    tid = await _seed_ticket(ttype="instalacao")
    r = _finalize(tid, ont="48575443ABCD", qtd_drop=50, conectores_fast=0,
                  observacoes="ok")
    assert r.status_code == 400, r.text[:300]
    detail = r.json().get("detail", {})
    if isinstance(detail, dict) and detail.get("error") == "consumiveis_obrigatorios_faltando":
        missing = detail.get("missing", [])
        assert any("Conector" in m for m in missing), missing
    await _cleanup()


async def test_http_bug4_instalacao_completa_nao_bloqueia_bug4():
    """Com ONT+DROP+CONECTOR+observação válida, NÃO deve bloquear pelo gate
    Bug #4 (outros gates podem disparar, mas error != consumiveis_…)."""
    await _cleanup()
    await _seed_collaborator()
    tid = await _seed_ticket(ttype="instalacao")
    r = _finalize(tid, ont="48575443ABCD", qtd_drop=80, conectores_fast=2,
                  observacoes="Instalacao apto 12 concluida ok")
    # qualquer status code ok — só validamos que se 400, não é Bug#4
    if r.status_code == 400:
        detail = r.json().get("detail", {})
        if isinstance(detail, dict):
            assert detail.get("error") != "consumiveis_obrigatorios_faltando", detail
    await _cleanup()


async def test_http_bug4_retirada_sem_ont():
    await _cleanup()
    await _seed_collaborator()
    tid = await _seed_ticket(ttype="retirada")
    r = _finalize(tid, ont=None, asset_recovered=True,
                  observacoes="cliente pagou a multa")
    assert r.status_code == 400, r.text[:300]
    detail = r.json().get("detail", {})
    if isinstance(detail, dict):
        missing = detail.get("missing", [])
        assert any("ONT recolhida" in m for m in missing), missing
    await _cleanup()


async def test_http_bug4_reparo_sem_material_sem_just():
    await _cleanup()
    await _seed_collaborator()
    tid = await _seed_ticket(ttype="reparo")
    r = _finalize(tid, qtd_drop=0, conectores_fast=0, observacoes="ok")
    assert r.status_code == 400, r.text[:300]
    detail = r.json().get("detail", {})
    assert isinstance(detail, dict)
    assert detail.get("error") == "consumiveis_obrigatorios_faltando", detail
    await _cleanup()


async def test_http_bug4_reparo_com_justificativa_libera():
    await _cleanup()
    await _seed_collaborator()
    tid = await _seed_ticket(ttype="reparo")
    r = _finalize(tid, qtd_drop=0, conectores_fast=0,
                  observacoes="problema logico no roteador do cliente, reset feito")
    if r.status_code == 400:
        detail = r.json().get("detail", {})
        if isinstance(detail, dict):
            assert detail.get("error") != "consumiveis_obrigatorios_faltando", detail
    await _cleanup()


# ────────────────────────── BUG #6 — Auto-detect ONT swap ───────────────────

async def test_http_bug6_swap_detectado_gera_evento():
    await _cleanup()
    await _seed_collaborator()
    tid = await _seed_ticket(ttype="reparo", current_ont="ALCL11112222")
    r = _finalize(tid, ont="ALCL99998888", qtd_drop=10, conectores_fast=1,
                  observacoes="troca ONT por defeito do cliente")
    # downstream pode 4xx, mas o evento já é registrado ANTES do raise
    assert r.status_code in (200, 400, 422, 500), r.status_code
    from database import db
    evt = await db.auto_ont_swap_events.find_one(
        {"company_id": CID, "ticket_id": tid}, {"_id": 0})
    assert evt is not None, "auto_ont_swap_events não registrou o swap"
    assert evt["ont_anterior"] == "ALCL11112222"
    assert evt["ont_atual"] == "ALCL99998888"
    assert evt["status"] == "pending_confirmation"
    assert evt["detected_by"] == "auto_detect_v1"
    await _cleanup()


async def test_http_bug6_sem_swap_quando_ont_igual():
    await _cleanup()
    await _seed_collaborator()
    tid = await _seed_ticket(ttype="reparo", current_ont="ALCL11112222")
    _finalize(tid, ont="ALCL11112222", qtd_drop=10, conectores_fast=1,
              observacoes="trocada drop danificada apenas")
    from database import db
    evt = await db.auto_ont_swap_events.find_one(
        {"company_id": CID, "ticket_id": tid})
    assert evt is None, "evento criado indevidamente"
    await _cleanup()


async def test_http_bug6_idempotente_double_finalize():
    await _cleanup()
    await _seed_collaborator()
    tid = await _seed_ticket(ttype="reparo", current_ont="ALCL11112222")
    for _ in range(2):
        _finalize(tid, ont="ALCL99998888", qtd_drop=10, conectores_fast=1,
                  observacoes="troca ont defeituosa")
    from database import db
    cnt = await db.auto_ont_swap_events.count_documents(
        {"company_id": CID, "ticket_id": tid})
    assert cnt == 1, f"esperado 1, achei {cnt}"
    await _cleanup()


if __name__ == "__main__":
    async def _main():
        await test_http_bug4_instalacao_sem_ont()
        await test_http_bug4_instalacao_sem_drop()
        await test_http_bug4_instalacao_sem_conector_sem_just()
        await test_http_bug4_instalacao_completa_nao_bloqueia_bug4()
        await test_http_bug4_retirada_sem_ont()
        await test_http_bug4_reparo_sem_material_sem_just()
        await test_http_bug4_reparo_com_justificativa_libera()
        await test_http_bug6_swap_detectado_gera_evento()
        await test_http_bug6_sem_swap_quando_ont_igual()
        await test_http_bug6_idempotente_double_finalize()
        print("✅ ONDA C HTTP — todos os testes passaram")

    asyncio.run(_main())
