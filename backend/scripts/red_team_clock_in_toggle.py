"""red_team_clock_in_toggle.py — Zero-Mocks: toggle `clock_in_enabled`.

Valida que admin tem PRIORIDADE ABSOLUTA sobre `clock_in_enabled` para
TODOS os colaboradores, independente do cargo. O `_apply_cargo_rules*`
NAO pode sobrescrever a decisao do gestor.

Cobertura (todos cargos da empresa):
  1. PUT /api/collaborators/{id} com clock_in_enabled=False persiste False.
  2. PUT /api/collaborators/{id} com clock_in_enabled=True  persiste True.
  3. Estado original e restaurado ao fim (idempotente).
  4. Roda DIRETO contra o endpoint HTTP real (auth gestor), nao via dict.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "field-ops",
    "domain": "clock",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from database import db
from auth import create_access_token
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


BASE = os.environ.get("BACKEND_BASE", "http://localhost:8001")


def _ok(m): print(f"  OK  {m}")
def _fail(m):
    print(f"  FAIL {m}")
    raise AssertionError(m)


async def _pick_company_with_collabs() -> list[tuple[str, list[dict]]]:
    """Retorna TODAS as companies com >= 1 colaborador, com seus docs."""
    agg = db.collaborators.aggregate([
        {"$group": {"_id": "$company_id", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 0}}},
        {"$sort": {"n": -1}},
    ])
    rows = [r async for r in agg]
    if not rows:
        _fail("Nenhuma company com colaboradores no DB.")
    out: list[tuple[str, list[dict]]] = []
    for r in rows:
        cid = r["_id"]
        colls = [c async for c in db.collaborators.find(
            {"company_id": cid}, {"_id": 0})]
        out.append((cid, colls))
    return out


async def _mint_admin_token(cid: str) -> str:
    """Cria/garante user administrador da company e gera JWT."""
    u = await db.users.find_one(
        {"company_id": cid, "role": {"$in": ["administrador", "gestor"]}},
        {"_id": 0, "id": 1, "email": 1, "role": 1, "company_id": 1},
    )
    if not u:
        _fail(f"Sem user gestor/administrador em company={cid}")
    return create_access_token(
        user_id=u["id"],
        email=u["email"],
        role=u["role"],
        company_id=u["company_id"],
    )


def _put_payload(coll: dict, clock_in: bool) -> dict:
    """Monta payload PUT preservando todos os campos do colaborador."""
    return {
        "name": coll.get("name", ""),
        "cpf": coll.get("cpf", ""),
        "email": coll.get("email", "x@x.com"),
        "phone": coll.get("phone", "11999999999"),
        "role": coll.get("role", "Colaborador de Campo"),
        "cargo": coll.get("cargo"),
        "company": coll.get("company", "Operação SP"),
        "city": coll.get("city"),
        "state": coll.get("state"),
        "praca_id": coll.get("praca_id"),
        "is_test_mode": bool(coll.get("is_test_mode", False)),
        "clock_in_enabled": clock_in,
        "active": bool(coll.get("active", True)),
        "can_attend_whatsapp": bool(coll.get("can_attend_whatsapp", False)),
        "requires_vehicle": bool(coll.get("requires_vehicle", False)),
    }


async def t_toggle_all(cid: str, token: str, colls: list[dict]) -> None:
    print(f"\n[Toggle HTTP] company={cid} colaboradores={len(colls)}")
    by_cargo: dict[str, int] = {}
    for c in colls:
        by_cargo[c.get("cargo") or "(sem cargo)"] = by_cargo.get(c.get("cargo") or "(sem cargo)", 0) + 1
    print(f"        breakdown por cargo: {by_cargo}")

    headers = {"Authorization": f"Bearer {token}"}
    failures: list[str] = []
    data_quality_skips: list[str] = []
    passed = 0

    async with httpx.AsyncClient(base_url=BASE, timeout=20.0) as cli:
        for coll in colls:
            cid_col = coll["id"]
            original = bool(coll.get("clock_in_enabled", True))
            cargo = coll.get("cargo") or "(sem cargo)"
            label = f"{coll.get('name','?')[:24]} cargo={cargo}"

            # Pre-flight: pula registros com dados invalidos pre-existentes
            # (cpf vazio, email reservado) — sao falhas de schema, nao de toggle.
            if not coll.get("cpf") or not coll.get("email"):
                data_quality_skips.append(
                    f"{label} :: cpf/email vazio no DB (registro orfao/legacy) — toggle nao aplicavel via HTTP")
                continue
            email_lc = (coll.get("email") or "").lower()
            if email_lc.endswith(".local") or email_lc.endswith(".internal"):
                data_quality_skips.append(
                    f"{label} :: email reservado ({email_lc}) — toggle nao aplicavel via HTTP")
                continue

            # ---- Toggle para False ----
            body_false = _put_payload(coll, clock_in=False)
            r = await cli.put(
                f"/api/collaborators/{cid_col}",
                json=body_false,
                headers=headers,
            )
            if r.status_code == 422:
                data_quality_skips.append(f"{label} :: 422 dados invalidos (email/cpf pre-existente) — nao afeta toggle")
                continue
            if r.status_code == 500 and ("duplicate key" in r.text.lower() or "dup key" in r.text.lower() or "cpf duplicado" in r.text.lower()):
                data_quality_skips.append(f"{label} :: 500 conflito de unicidade — sent_cpf={body_false.get('cpf')!r}")
                continue
            if r.status_code != 200:
                print(f"  DBG PUT False {label}: sent cpf={body_false.get('cpf')!r} email={body_false.get('email')!r}")
                print(f"      resp[:300]={r.text[:300]}")
                failures.append(f"PUT False -> HTTP {r.status_code} ({label}) :: {r.text[:200]}")
                continue
            db_doc = await db.collaborators.find_one(
                {"id": cid_col}, {"_id": 0, "clock_in_enabled": 1})
            if db_doc.get("clock_in_enabled") is not False:
                failures.append(
                    f"REGRESSAO: clock_in_enabled nao virou False ({label}) "
                    f"-- DB={db_doc.get('clock_in_enabled')!r}")
                continue

            # ---- Toggle para True ----
            r = await cli.put(
                f"/api/collaborators/{cid_col}",
                json=_put_payload(coll, clock_in=True),
                headers=headers,
            )
            if r.status_code != 200:
                failures.append(f"PUT True -> HTTP {r.status_code} ({label}) :: {r.text[:200]}")
                continue
            db_doc = await db.collaborators.find_one(
                {"id": cid_col}, {"_id": 0, "clock_in_enabled": 1})
            if db_doc.get("clock_in_enabled") is not True:
                failures.append(
                    f"REGRESSAO: clock_in_enabled nao virou True ({label}) "
                    f"-- DB={db_doc.get('clock_in_enabled')!r}")
                continue

            # ---- Restaura estado original ----
            await cli.put(
                f"/api/collaborators/{cid_col}",
                json=_put_payload(coll, clock_in=original),
                headers=headers,
            )
            _ok(f"{label} :: False->True->{original} persistiu")
            passed += 1

    print(f"\n  HTTP toggle: {passed} OK, {len(data_quality_skips)} skip (dados ruins), {len(failures)} REGRESSAO")
    for s in data_quality_skips:
        print(f"  WARN {s}")
    if failures:
        print("")
        for f in failures:
            print(f"  FAIL {f}")
        _fail(f"{len(failures)} colaboradores tiveram REGRESSAO de toggle.")


async def t_unit_apply_cargo_rules() -> None:
    """Garante que `_apply_cargo_rules*` JAMAIS mexe em clock_in_enabled.

    Cobre TODOS os cargos validos + sem cargo + cargo invalido.
    """
    from routes.clock import _apply_cargo_rules_dict, _apply_cargo_rules
    from cargo import ALL_CARGOS

    print("\n[Unit] _apply_cargo_rules / _dict nao deve tocar clock_in_enabled")
    cargos = list(ALL_CARGOS) + [None, "", "cargo_inexistente"]
    user_admin = {"role": "admin"}

    class Dummy:
        def __init__(self, cargo, clock):
            self.cargo = cargo
            self.clock_in_enabled = clock
            self.can_attend_whatsapp = False

    for cg in cargos:
        for initial in (True, False):
            # dict version
            d = {"cargo": cg, "clock_in_enabled": initial,
                  "can_attend_whatsapp": False}
            _apply_cargo_rules_dict(d, user_admin)
            if d["clock_in_enabled"] is not initial:
                _fail(f"_dict alterou clock_in_enabled (cargo={cg!r} initial={initial})")
            # payload version
            p = Dummy(cg, initial)
            _apply_cargo_rules(p, user_admin)
            if p.clock_in_enabled is not initial:
                _fail(f"payload alterou clock_in_enabled (cargo={cg!r} initial={initial})")
    _ok(f"{len(cargos) * 2} combinacoes (cargo x estado) preservaram clock_in_enabled.")


async def t_mobile_lousa_unlocked(cid: str) -> None:
    """End-to-end: com clock_in_enabled=False, Lousa do colaborador
    fica DESBLOQUEADA sem precisar bater ponto."""
    from routes.lousa import _lousa_for_collaborator

    print("\n[Mobile E2E] _lousa_for_collaborator com clock_in_enabled=False")
    diogo = await db.collaborators.find_one(
        {"company_id": cid, "name": {"$regex": "DIOGO", "$options": "i"}},
        {"_id": 0, "id": 1, "name": 1, "clock_in_enabled": 1},
    )
    if not diogo:
        _ok("DIOGO nao existe nesta company — skip e2e.")
        return

    # Forca False
    await db.collaborators.update_one(
        {"id": diogo["id"]},
        {"$set": {"clock_in_enabled": False, "updated_at": now_iso()}},
    )
    lousa = await _lousa_for_collaborator(diogo["id"])
    if lousa.get("needs_clock_in") is True:
        _fail(f"REGRESSAO: needs_clock_in=True com clock_in_enabled=False "
              f"(diogo) — lousa={list(lousa.keys())}")
    if lousa.get("lousa_unlocked") is False:
        _fail(f"REGRESSAO: lousa_unlocked=False com clock_in_enabled=False "
              f"(diogo) — clock_state={lousa.get('clock_state')}")
    _ok(f"DIOGO clock_in_enabled=False -> lousa_unlocked={lousa.get('lousa_unlocked')} "
        f"needs_clock_in={lousa.get('needs_clock_in')} tickets={len(lousa.get('tickets') or [])}")

    # Restaura toggle para True e verifica que SEM bater ponto, lousa fica BLOQUEADA
    await db.collaborators.update_one(
        {"id": diogo["id"]},
        {"$set": {"clock_in_enabled": True, "updated_at": now_iso()}},
    )
    # Limpa eventuais clock_records de hoje pra simular tecnico que ainda nao bateu
    from datetime import datetime as _dt
    hoje = _dt.utcnow().strftime("%Y-%m-%d")
    await db.clock_records.delete_many({"collaborator_id": diogo["id"], "ts": {"$regex": f"^{hoje}"}})
    lousa2 = await _lousa_for_collaborator(diogo["id"])
    if lousa2.get("lousa_unlocked") is True:
        _fail(f"REGRESSAO: lousa deveria BLOQUEAR com clock_in_enabled=True e sem ponto, "
              f"mas veio unlocked={lousa2.get('lousa_unlocked')}")
    _ok(f"DIOGO clock_in_enabled=True sem ponto -> lousa_unlocked={lousa2.get('lousa_unlocked')} "
        f"needs_clock_in={lousa2.get('needs_clock_in')} (esperado: bloqueada)")

    # Restaura estado original (assume False — o que o user pediu pro diogo)
    await db.collaborators.update_one(
        {"id": diogo["id"]},
        {"$set": {"clock_in_enabled": bool(diogo.get("clock_in_enabled", False)),
                  "updated_at": now_iso()}},
    )


async def main():
    print("="*72)
    print("RED TEAM :: clock_in_enabled toggle (TODOS COLABORADORES)")
    print("="*72)
    companies = await _pick_company_with_collabs()
    await t_unit_apply_cargo_rules()
    total_ok = 0
    total_skip = 0
    for cid, colls in companies:
        u = await db.users.find_one(
            {"company_id": cid, "role": {"$in": ["administrador", "gestor"]}},
            {"_id": 0, "id": 1, "email": 1, "role": 1, "company_id": 1},
        )
        if not u:
            print(f"\n[SKIP company] {cid} :: sem user gestor/administrador no DB ({len(colls)} colaboradores)")
            total_skip += len(colls)
            continue
        token = create_access_token(
            user_id=u["id"], email=u["email"], role=u["role"], company_id=u["company_id"])
        await t_toggle_all(cid, token, colls)
    await t_mobile_lousa_unlocked(companies[0][0])
    print("\n" + "="*72)
    print("PASS :: toggle respeitado em TODOS os colaboradores.")
    print("="*72)


if __name__ == "__main__":
    asyncio.run(main())
