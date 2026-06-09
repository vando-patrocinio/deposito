"""iter215an — Validação UNITÁRIA do serviço `atendente_duty`.

Tudo em UMA função de teste pra evitar o problema de event loop fechado
do Motor entre tests (Motor reusa o loop global).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")

import pymongo  # noqa: E402

_sync = pymongo.MongoClient(os.environ["MONGO_URL"])
_db = _sync[os.environ["DB_NAME"]]


def _today_brt_str() -> str:
    from datetime import timedelta
    now = datetime.now(timezone.utc) - timedelta(hours=3)
    return now.strftime("%Y-%m-%d")


def _seed(company_id: str = "co-demo", role: str = "gestor") -> dict:
    suf = uuid.uuid4().hex[:6]
    uid = f"usr-{suf}"
    cid = f"col-{suf}"
    email = f"gestor-{suf}@duty-test.com"
    _db.users.insert_one({
        "id": uid, "email": email, "name": f"Gestor {suf}",
        "role": role, "password_hash": "x",
        "company_id": company_id, "active": True,
    })
    _db.collaborators.insert_one({
        "id": cid, "company_id": company_id,
        "name": f"Gestor {suf}", "email": email,
        "cpf": f"99{uuid.uuid4().hex[:8]}",
        "cargo": "Administrativo",
        "clock_in_enabled": True, "can_attend_whatsapp": True,
    })
    return {"user_id": uid, "collaborator_id": cid, "email": email,
            "company_id": company_id, "name": f"Gestor {suf}", "role": role}


def _clock_in(collaborator_id, company_id, event_type, time="08:00"):
    _db.clock_records.insert_one({
        "id": f"rec-{uuid.uuid4().hex[:8]}",
        "collaborator_id": collaborator_id,
        "type": event_type, "company_id": company_id,
        "date": _today_brt_str(), "time": time, "status": "Válido",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


def _open_conv(company_id, user_id, phone):
    _db.wa_conversations.insert_one({
        "company_id": company_id, "phone": phone,
        "assignee_user_id": user_id, "assignee_role": "human",
        "status": "open",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


def _cleanup(users, colls):
    _db.users.delete_many({"id": {"$in": users}})
    _db.collaborators.delete_many({"id": {"$in": colls}})
    _db.clock_records.delete_many({"collaborator_id": {"$in": colls}})
    for u in users:
        _db.wa_conversations.delete_many({"assignee_user_id": u})


async def _run_all():
    from services.atendente_duty import (
        is_user_on_duty, enforce_offduty_clock_event,
    )

    # 1) Gestor sem ponto → off_duty
    u = _seed()
    try:
        on, reason, last = await is_user_on_duty(
            u["company_id"],
            {"id": u["user_id"], "email": u["email"], "role": "gestor"},
        )
        assert on is False, reason
        assert last is None
        assert "Entrada" in reason

        # 2) Após Entrada → on_duty
        _clock_in(u["collaborator_id"], u["company_id"], "Entrada")
        on, _, last = await is_user_on_duty(
            u["company_id"],
            {"id": u["user_id"], "email": u["email"], "role": "gestor"},
        )
        assert on is True
        assert last["type"] == "Entrada"

        # 3) Após Início intervalo → off_duty
        _clock_in(u["collaborator_id"], u["company_id"],
                   "Início intervalo", "12:00")
        on, reason, last = await is_user_on_duty(
            u["company_id"],
            {"id": u["user_id"], "email": u["email"], "role": "gestor"},
        )
        assert on is False
        assert last["type"] == "Início intervalo"

        # 4) Bloqueia ponto sem outro online
        _clock_in(u["collaborator_id"], u["company_id"],
                   "Fim intervalo", "13:00")  # volta on duty
        _open_conv(u["company_id"], u["user_id"],
                    "+5511" + uuid.uuid4().hex[:8])
        coll = _db.collaborators.find_one(
            {"id": u["collaborator_id"]}, {"_id": 0})
        allowed, reason, target, n = await enforce_offduty_clock_event(
            u["company_id"], coll, "Início intervalo")
        assert allowed is False, reason
        assert "BLOQUEADO" in reason
        assert n == 0
    finally:
        _cleanup([u["user_id"]], [u["collaborator_id"]])

    # 5) Com outro gestor online → transfere
    u1 = _seed()
    u2 = _seed()
    try:
        _clock_in(u1["collaborator_id"], u1["company_id"], "Entrada")
        _clock_in(u2["collaborator_id"], u2["company_id"], "Entrada")
        ph_a = "+5511" + uuid.uuid4().hex[:8]
        ph_b = "+5511" + uuid.uuid4().hex[:8]
        _open_conv(u1["company_id"], u1["user_id"], ph_a)
        _open_conv(u1["company_id"], u1["user_id"], ph_b)
        coll1 = _db.collaborators.find_one(
            {"id": u1["collaborator_id"]}, {"_id": 0})
        allowed, reason, target, n = await enforce_offduty_clock_event(
            u1["company_id"], coll1, "Saída")
        assert allowed is True
        assert n == 2
        assert target["id"] == u2["user_id"]
        for ph in (ph_a, ph_b):
            cv = _db.wa_conversations.find_one({"phone": ph}, {"_id": 0})
            assert cv["assignee_user_id"] == u2["user_id"], cv
    finally:
        _cleanup(
            [u1["user_id"], u2["user_id"]],
            [u1["collaborator_id"], u2["collaborator_id"]],
        )

    # 6) Role não afetada (tecnico) → passa direto
    u_tec = _seed(role="tecnico")
    try:
        _open_conv(u_tec["company_id"], u_tec["user_id"],
                    "+5511" + uuid.uuid4().hex[:8])
        coll = _db.collaborators.find_one(
            {"id": u_tec["collaborator_id"]}, {"_id": 0})
        allowed, reason, target, n = await enforce_offduty_clock_event(
            u_tec["company_id"], coll, "Saída")
        assert allowed is True
        assert n == 0
    finally:
        _cleanup([u_tec["user_id"]], [u_tec["collaborator_id"]])


def test_atendente_duty_full_flow():
    asyncio.run(_run_all())
    print("[duty] all flows OK")
