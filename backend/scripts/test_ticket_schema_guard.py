"""
scripts/test_ticket_schema_guard.py — Red-team CTO P3 11/06/2026
ZERO MOCKS. Testa o guard contra o MongoDB real + endpoint real /api/lousa/grid.

Cenários (10):
 1. priority="ALTA"  vira "urgente" no DB
 2. priority="MEDIA" vira "prioridade"
 3. priority="BAIXA" vira "normal"
 4. status="agendado" vira "aguardando_atendimento"
 5. type="INSTALAÇÃO" vira "instalacao"
 6. client_snapshot ausente não quebra normalizador
 7. update_one com $set normaliza
 8. linter --check detecta inválidos sintéticos
 9. linter --fix corrige seguros (idempotente)
10. /api/lousa/grid HTTP 200 e payload válido
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(0, "/app/backend")

import httpx

from database import db  # noqa: E402
from services.ticket_schema import (  # noqa: E402
    PRIORITY_CANONICAL, STATUS_CANONICAL,
    normalize_priority, normalize_status, normalize_type,
    validate_ticket_payload,
)
from auth import create_access_token  # noqa: E402

API = os.environ.get("REACT_APP_BACKEND_URL") or "https://dual-combine-3.preview.emergentagent.com"
CID = "co-schema-test"
RESULTS = []


def ok(s): print(f"  ✅ {s}"); RESULTS.append((True, s))
def bad(s): print(f"  ❌ {s}"); RESULTS.append((False, s))


async def cleanup():
    await db.tickets.delete_many({"company_id": CID})


def _mk_ticket(priority="ALTA", status="agendado", typ="INSTALAÇÃO",
               with_cs: bool = True) -> dict:
    doc = {
        "id": f"tk-schema-{uuid.uuid4().hex[:10]}",
        "company_id": CID,
        "priority": priority,
        "status": status,
        "type": typ,
        "assigned_collaborator_id": "col-sala",
        "position": 0,
        "scheduled_time": "2026-06-15T10:00:00+00:00",
        "created_at": "2026-06-11T22:00:00+00:00",
    }
    if with_cs:
        doc["client_snapshot"] = {"name": "Cliente Teste",
                                  "address": "Rua X, 100", "neighborhood": "Centro"}
    return doc


async def t1_priority_alta():
    doc = _mk_ticket(priority="ALTA")
    await db.tickets.insert_one(doc)
    found = await db.tickets.find_one({"id": doc["id"]})
    if found and found["priority"] == "urgente":
        ok("1. priority=ALTA → urgente (insert)")
    else:
        bad(f"1. esperado priority=urgente, got {found and found.get('priority')}")


async def t2_priority_media():
    doc = _mk_ticket(priority="MEDIA")
    await db.tickets.insert_one(doc)
    found = await db.tickets.find_one({"id": doc["id"]})
    if found and found["priority"] == "prioridade":
        ok("2. priority=MEDIA → prioridade (insert)")
    else:
        bad(f"2. esperado priority=prioridade, got {found and found.get('priority')}")


async def t3_priority_baixa():
    doc = _mk_ticket(priority="BAIXA")
    await db.tickets.insert_one(doc)
    found = await db.tickets.find_one({"id": doc["id"]})
    if found and found["priority"] == "normal":
        ok("3. priority=BAIXA → normal (insert)")
    else:
        bad(f"3. esperado priority=normal, got {found and found.get('priority')}")


async def t4_status_agendado():
    doc = _mk_ticket(status="agendado")
    await db.tickets.insert_one(doc)
    found = await db.tickets.find_one({"id": doc["id"]})
    if found and found["status"] == "aguardando_atendimento":
        ok("4. status=agendado → aguardando_atendimento")
    else:
        bad(f"4. esperado status=aguardando_atendimento, got {found and found.get('status')}")


async def t5_type_install():
    doc = _mk_ticket(typ="INSTALAÇÃO")
    await db.tickets.insert_one(doc)
    found = await db.tickets.find_one({"id": doc["id"]})
    if found and found["type"] == "instalacao":
        ok("5. type=INSTALAÇÃO → instalacao")
    else:
        bad(f"5. esperado type=instalacao, got {found and found.get('type')}")


async def t6_no_client_snapshot():
    doc = _mk_ticket(with_cs=False)
    try:
        await db.tickets.insert_one(doc)
    except Exception as e:
        bad(f"6. inserção quebrou sem client_snapshot: {e}")
        return
    found = await db.tickets.find_one({"id": doc["id"]})
    if found and found.get("priority") == "urgente":
        ok("6. ticket sem client_snapshot persiste e normaliza priority")
    else:
        bad("6. não persistiu corretamente sem client_snapshot")


async def t7_update_set():
    doc = _mk_ticket(priority="normal", status="pendente")
    await db.tickets.insert_one(doc)
    # update via $set com ALTA — interceptor deve normalizar
    await db.tickets.update_one(
        {"id": doc["id"]},
        {"$set": {"priority": "ALTA", "status": "concluido"}},
    )
    found = await db.tickets.find_one({"id": doc["id"]})
    if found["priority"] == "urgente" and found["status"] == "finalizada":
        ok("7. update_one $set normaliza priority+status")
    else:
        bad(f"7. update não normalizou. got {found.get('priority')}/{found.get('status')}")


async def t8_linter_detects():
    import subprocess
    # Insere via collection RAW (bypass interceptor) para criar lixo proposital
    # Como interceptor está no objeto Python, usar pymongo direto?
    # Mais simples: inserir e o interceptor consertaria. Então
    # bypassar via raw motor command:
    raw = db.command  # noqa: F841
    # Forçar via update direto no driver, depois do insert
    bad_id = f"tk-bad-{uuid.uuid4().hex[:10]}"
    # Insere ok
    await db.tickets.insert_one({
        "id": bad_id, "company_id": CID, "priority": "normal",
        "status": "pendente", "type": "reparo",
        "client_snapshot": {"name": "x"},
    })
    # Bypassa interceptor: usa $set via update direto mas isso será também normalizado.
    # Workaround: usar database.mongo_client direto.
    from database import mongo_client
    raw_db = mongo_client.get_database(os.environ.get("DB_NAME") or db.name)
    await raw_db["tickets"].update_one(
        {"id": bad_id},
        {"$set": {"priority": "ALTA_FAKE", "status": "STATUS_FAKE"}},
    )
    # Roda linter
    res = subprocess.run(
        ["python3", "/app/backend/scripts/lint_ticket_schema.py", "--check", "--json"],
        capture_output=True, text=True, cwd="/app/backend", timeout=60,
    )
    import json as _json
    try:
        data = _json.loads(res.stdout)
    except Exception:
        bad(f"8. linter --check stdout não-JSON: {res.stdout[:200]}")
        return
    if data["invalid_total"] >= 1 and data["by_field"].get("priority", 0) >= 1:
        ok(f"8. linter --check detectou {data['invalid_total']} inválidos (priority={data['by_field'].get('priority',0)})")
    else:
        bad(f"8. linter não detectou. invalid_total={data.get('invalid_total')} by_field={data.get('by_field')}")


async def t9_linter_fix():
    import subprocess
    res = subprocess.run(
        ["python3", "/app/backend/scripts/lint_ticket_schema.py", "--fix"],
        capture_output=True, text=True, cwd="/app/backend", timeout=120,
    )
    if "Corrigidos" in res.stdout or "fixed" in res.stdout.lower():
        # Re-roda check — deve ser 0 fixáveis
        res2 = subprocess.run(
            ["python3", "/app/backend/scripts/lint_ticket_schema.py", "--check", "--json"],
            capture_output=True, text=True, cwd="/app/backend", timeout=60,
        )
        import json as _json
        try:
            data = _json.loads(res2.stdout)
            fix_by_field = data.get("fixable_by_field", {})
            if not any(fix_by_field.values()):
                ok("9. linter --fix zerou os fixáveis (idempotente)")
            else:
                bad(f"9. ainda há fixáveis: {fix_by_field}")
        except Exception:
            bad(f"9. parse pós-fix falhou: {res2.stdout[:200]}")
    else:
        bad(f"9. linter --fix stdout inesperado: {res.stdout[:200]}")


async def t10_lousa_grid_200():
    # Login real para garantir que o user está ativo no DB
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(f"{API}/api/auth/login",
                              json={"email": "admin@empresa.com", "password": "123456"})
        if r.status_code != 200:
            bad(f"10. login admin falhou HTTP {r.status_code}")
            return
        token = r.json().get("access_token") or r.json().get("token")
        r = await client.get(f"{API}/api/lousa/grid",
                             headers={"Authorization": f"Bearer {token}"})
    if r.status_code == 200 and "columns" in r.json():
        ok(f"10. /api/lousa/grid HTTP 200 ({len(r.json().get('columns', []))} colunas)")
    else:
        bad(f"10. /api/lousa/grid HTTP {r.status_code} body={r.text[:120]}")


async def main():
    print("═" * 70)
    print("RED-TEAM TICKET SCHEMA GUARD — CTO P3 11/06/2026")
    print("═" * 70)
    await cleanup()

    # Sanity em funções puras
    assert normalize_priority("ALTA") == "urgente"
    assert normalize_priority(None) == "normal"
    assert normalize_status("AGENDADO") == "aguardando_atendimento"
    assert normalize_type("INSTALAÇÃO") == "instalacao"
    ok_, errs = validate_ticket_payload({"priority": "lixo"}, strict=True)
    assert not ok_ and errs
    print("  ✅ funções puras OK")

    await t1_priority_alta()
    await t2_priority_media()
    await t3_priority_baixa()
    await t4_status_agendado()
    await t5_type_install()
    await t6_no_client_snapshot()
    await t7_update_set()
    await t8_linter_detects()
    await t9_linter_fix()
    await t10_lousa_grid_200()

    passed = sum(1 for ok_, _ in RESULTS if ok_)
    total = len(RESULTS)
    print("═" * 70)
    print(f"RESULTADO: {passed}/{total}")
    print("═" * 70)
    await cleanup()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
