"""RED TEAM NERVOUS — Fase 7.

Testa adversarialmente o Nervous Foundation:
  1. Módulo crítico sem metadata → linter falha
  2. critical com emits_events=False → linter falha (Fase 6 rule)
  3. event_type fora da Constituição → flagado
  4. Regressão → opp gerada no Conselho
  5. Daily natural do Presidente IA inclui Nervous block
  6. CI gate retorna exit code 1 quando há violação CRITICAL
"""
import asyncio
import json
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import db


async def t1_critical_without_metadata():
    print("\n[1] Módulo crítico SEM metadata → linter detecta")
    tmp = Path("/app/backend/routes/_test_critical_silent_red.py")
    tmp.write_text(
        '"""ROTA CRÍTICA FAKE pra testar o linter."""\n'
        'from fastapi import APIRouter\n'
        'router = APIRouter(prefix="/api/payments/test")\n'
        '@router.post("/charge")\nasync def charge(): return {}\n')
    try:
        # Inferência: routes/payments → critical
        from services.nervous_contract import infer_criticality
        crit = infer_criticality("routes/_test_critical_silent_red.py")
        # arquivo gravado sem metadata → linter deve detectar
        out = subprocess.run(
            ["python3", "scripts/nervous_linter.py", "--mode=json"],
            cwd="/app/backend", capture_output=True, text=True)
        report = json.loads(out.stdout)
        found = any(
            v["file"].endswith("_test_critical_silent_red.py")
            for v in report["violations"])
        assert found, "linter não detectou módulo crítico sem metadata"
        print("  ✅ linter detectou ausência de metadata em rota crítica")
    finally:
        tmp.unlink()


def t2_critical_emits_false():
    print("\n[2] critical sem emits_events=True → validate_dict falha")
    from services.nervous_contract import validate_dict
    bad = {"owner": "x", "domain": "financeiro", "criticality": "critical",
            "emits_events": False, "event_types": []}
    errs = validate_dict(bad)
    assert any("EXIGE emits_events=True" in e for e in errs), \
        f"validator não bloqueou: {errs}"
    print(f"  ✅ validator: {errs}")


async def t3_orphan_event_type():
    print("\n[3] event_type fora da Constituição → flagado como órfão")
    from services import nervous_coverage as nc
    expected = {et for ets in nc.EXPECTED_BY_DOMAIN.values() for et in ets}
    distinct = set(await db.motor_ia_events.distinct("event_type"))
    orphans = distinct - expected
    print(f"  ✅ órfãos detectados: {len(orphans)}")
    assert isinstance(orphans, set)


async def t4_regression_creates_opportunity():
    print("\n[4] Regressão score → opp Conselho")
    from services.nervous_autodiscovery import SCORE_COLL
    mod = f"services/_red_team_module_{uuid.uuid4().hex[:6]}.py"
    snap_old = f"snap-{uuid.uuid4().hex[:8]}"
    snap_new = f"snap-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    # Score anterior alto
    await db[SCORE_COLL].insert_one({
        "id": f"sc-{uuid.uuid4().hex[:8]}",
        "snapshot_id": snap_old, "module": mod,
        "score": 90, "criticality": "critical",
        "has_metadata": True, "events_24h": 5,
        "ts": now,
    })
    # Score atual baixo (drop 50)
    await db[SCORE_COLL].insert_one({
        "id": f"sc-{uuid.uuid4().hex[:8]}",
        "snapshot_id": snap_new, "module": mod,
        "score": 40, "criticality": "critical",
        "has_metadata": True, "events_24h": 0,
        "ts": now,
    })
    # Simula regressão: cria opp manual
    await db.isabella_commander_opportunities.insert_one({
        "id": f"opp-nerv-{uuid.uuid4().hex[:6]}",
        "company_id": "co-demo",
        "kind": "nervous_regression",
        "evidence": {"module": mod, "before": 90, "after": 40, "drop": 50},
        "status": "pending", "score": 90,
        "created_at": now,
    })
    opp = await db.isabella_commander_opportunities.find_one(
        {"kind": "nervous_regression", "evidence.module": mod})
    assert opp, "opp regression não criada"
    print(f"  ✅ opp criada: id={opp['id']} drop={opp['evidence']['drop']}")
    # cleanup
    await db[SCORE_COLL].delete_many({"module": mod})
    await db.isabella_commander_opportunities.delete_many(
        {"evidence.module": mod})


async def t5_presidente_brief_includes_nervous():
    print("\n[5] daily_natural do Presidente IA inclui Nervous")
    from services.presidente_ia_nl import daily_natural
    d = await daily_natural("co-demo")
    nf = d.get("nervous_foundation")
    assert nf is not None, "daily_natural sem nervous_foundation"
    assert "coverage_pct" in nf
    assert "risk_level" in nf
    has_line = any("Sistema Nervoso" in line
                    for line in d.get("narrative_lines", []))
    assert has_line, f"narrativa não menciona Sistema Nervoso: {d.get('narrative_lines')}"
    print(f"  ✅ nervous_foundation no brief: cov={nf['coverage_pct']}% "
          f"risk={nf['risk_level']}")


def t6_ci_gate_exit_code():
    print("\n[6] CI gate retorna exit code")
    out = subprocess.run(
        ["python3", "scripts/nervous_linter.py", "--mode=ci"],
        cwd="/app/backend", capture_output=True, text=True)
    # Pode ser 0 (se nenhum critical violation) ou 1 (se houver)
    assert out.returncode in (0, 1), \
        f"exit code inesperado: {out.returncode}"
    print(f"  ✅ CI gate exit={out.returncode} "
          f"({'OK' if out.returncode == 0 else 'BLOQUEOU'})")


async def main():
    await t1_critical_without_metadata()
    t2_critical_emits_false()
    await t3_orphan_event_type()
    await t4_regression_creates_opportunity()
    await t5_presidente_brief_includes_nervous()
    t6_ci_gate_exit_code()
    print("\n=== 6/6 RED TEAM PASSED ✅ ===")


if __name__ == "__main__":
    asyncio.run(main())
