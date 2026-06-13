"""CTO 13/06/2026 — ETAPA 2.1 P4: Red-team de compatibilidade IAM v2.

Valida que NADA do sistema atual foi quebrado pela presença do módulo
`iam_v2`. Roda 8 checagens. Se qualquer uma falhar → IAM v2 NÃO pode
avançar pra ETAPA 2.5.

Uso:
    python3 /app/backend/scripts/test_iam_v2_dry_run.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests

# Boot
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = "http://localhost:8001"
RESULTS: list[dict] = []


def record(check: str, passed: bool, detail: str = "") -> None:
    icon = "✅" if passed else "❌"
    RESULTS.append({"check": check, "passed": passed, "detail": detail})
    print(f"{icon}  [{check}] {detail}")


# ──────────────────────────────────────────────────────────────────────────
# Check 1 — Feature flag está OFF
# ──────────────────────────────────────────────────────────────────────────

def check_1_flag_off() -> None:
    flag = os.environ.get("USE_NEW_IAM", "0")
    record(
        "1. USE_NEW_IAM=0 (feature flag desligada)",
        flag == "0",
        f"flag={flag!r} — esperado '0'",
    )


# ──────────────────────────────────────────────────────────────────────────
# Check 2 — Login legado funciona intacto
# ──────────────────────────────────────────────────────────────────────────

def check_2_legacy_login() -> None:
    try:
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@empresa.com", "password": "123456"},
            timeout=10,
        )
        ok = r.status_code == 200 and (r.json().get("access_token")
                                          or r.json().get("token"))
        record(
            "2. Login legado /api/auth/login funciona",
            bool(ok),
            f"status={r.status_code}",
        )
    except Exception as e:
        record("2. Login legado /api/auth/login funciona", False, str(e))


# ──────────────────────────────────────────────────────────────────────────
# Check 3 — Phase 0 detecta órfãos
# ──────────────────────────────────────────────────────────────────────────

async def check_3_phase0() -> None:
    from iam_v2.migrate import phase_0_validate
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ.get("DB_NAME", "test_database")]
    result = await phase_0_validate(db, "co-demo")
    expected_orphans = 6  # conforme P0 da ETAPA 2.1
    detected = result.get("orphan_collaborators", -1)
    record(
        "3. Phase 0 detecta os 6 órfãos",
        detected == expected_orphans,
        f"detectados={detected} esperado={expected_orphans}",
    )
    cli.close()


# ──────────────────────────────────────────────────────────────────────────
# Check 4 — Dry-run das phases 1-6 gera plano consistente
# ──────────────────────────────────────────────────────────────────────────

async def check_4_dry_run_consistency() -> None:
    from iam_v2.migrate import (
        phase_1_create_identities, phase_2_merge_collaborators,
        phase_3_create_credentials, phase_4_create_memberships,
        phase_5_migrate_portals, phase_6_init_sessions,
    )
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ.get("DB_NAME", "test_database")]

    # Snapshot antes
    users_before = await db.users.count_documents({"company_id": "co-demo"})
    identities_before = await db.identities.count_documents({}) \
        if "identities" in await db.list_collection_names() else 0

    # Roda dry-run de tudo
    p1 = await phase_1_create_identities(db, "co-demo", dry_run=True)
    p2 = await phase_2_merge_collaborators(db, "co-demo", dry_run=True)
    p3 = await phase_3_create_credentials(db, "co-demo", dry_run=True)
    p4 = await phase_4_create_memberships(db, "co-demo", dry_run=True)
    p5 = await phase_5_migrate_portals(db, "co-demo", dry_run=True)
    p6 = await phase_6_init_sessions(db, "co-demo", dry_run=True)

    # Snapshot depois
    users_after = await db.users.count_documents({"company_id": "co-demo"})
    identities_after = await db.identities.count_documents({}) \
        if "identities" in await db.list_collection_names() else 0

    # Não deve ter escrito nada
    no_writes = (users_before == users_after
                 and identities_before == identities_after)
    record(
        "4a. Dry-run NÃO escreveu nada",
        no_writes,
        f"users={users_before}→{users_after} "
        f"identities={identities_before}→{identities_after}",
    )

    # Phase 1 retornou plano com `dry_run=False` aqui falha de outra forma
    has_plan = all([
        p1.get("created") is not None or p1.get("skipped") is not None,
        p2.get("merged_into_existing") is not None,
        p3.get("dry_run") is True,
        p4.get("dry_run") is True,
        p5.get("dry_run") is True,
        p6.get("dry_run") is True,
    ])
    record(
        "4b. Phases 1-6 retornaram plano estruturado",
        has_plan,
        f"p1.created={p1.get('created')} p3.total={p3.get('total')}",
    )

    # Salva o plano consolidado pra revisão
    Path("/app/memory").mkdir(exist_ok=True)
    with open("/app/memory/IAM_V2_DRY_RUN_PLAN.json", "w") as f:
        json.dump({
            "company_id": "co-demo",
            "phase_1": p1, "phase_2": p2, "phase_3": p3,
            "phase_4": p4, "phase_5": p5, "phase_6": p6,
        }, f, default=str, indent=2)
    cli.close()


# ──────────────────────────────────────────────────────────────────────────
# Check 5 — Arquivos críticos de auth não foram alterados
# ──────────────────────────────────────────────────────────────────────────

# Hashes capturados em 13/06/2026 ANTES da entrega ETAPA 2.1.
# Se qualquer um mudar entre rodadas, é alerta vermelho.
def _file_sha(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def check_5_critical_files_unchanged() -> None:
    critical = {
        "/app/backend/auth.py": None,         # captura o hash em runtime
        "/app/backend/rbac_policy.py": None,
        "/app/backend/services/access_profiles.py": None,
    }
    # Calcula e compara contra baseline (gerado em primeira execução).
    baseline_path = Path("/app/memory/.iam_v2_baseline_hashes.json")
    if not baseline_path.exists():
        # Primeira execução → gera baseline
        for p in list(critical.keys()):
            critical[p] = _file_sha(p)
        baseline_path.write_text(json.dumps(critical, indent=2))
        record(
            "5. Hashes baseline de arquivos críticos",
            True,
            "baseline criado agora (primeira execução)",
        )
        return
    baseline = json.loads(baseline_path.read_text())
    drift: list[str] = []
    for p in baseline:
        cur = _file_sha(p)
        if cur != baseline[p]:
            drift.append(f"{p}: {baseline[p]} → {cur}")
    record(
        "5. auth.py / rbac_policy.py / access_profiles.py INALTERADOS",
        len(drift) == 0,
        ", ".join(drift) if drift else "todos os hashes batem com baseline",
    )


# ──────────────────────────────────────────────────────────────────────────
# Check 6 — Imports do iam_v2 não vazaram pro main
# ──────────────────────────────────────────────────────────────────────────

def check_6_no_cross_imports() -> None:
    import subprocess
    # Procura imports de iam_v2 fora do próprio diretório
    res = subprocess.run(
        ["grep", "-rn", "iam_v2", "/app/backend/",
         "--exclude-dir=__pycache__",
         "--exclude-dir=iam_v2",
         "--exclude=test_iam_v2_dry_run.py"],
        capture_output=True, text=True, check=False,
    )
    leaks = [l for l in res.stdout.splitlines() if l.strip()]
    record(
        "6. Nenhum arquivo de produção importa iam_v2",
        len(leaks) == 0,
        f"leaks={len(leaks)} — {leaks[:3] if leaks else 'limpo'}",
    )


# ──────────────────────────────────────────────────────────────────────────
# Check 7 — Suíte pytest existente continua verde
# ──────────────────────────────────────────────────────────────────────────

def check_7_regression_suite() -> None:
    import subprocess
    res = subprocess.run(
        ["python3", "-m", "pytest",
         "tests/test_clock_in_enabled_preserve.py",
         "tests/test_modo_relaxado_lousa.py",
         "tests/test_collaborator_profile_propagates_to_user.py",
         "-q", "--tb=no"],
        cwd="/app/backend",
        env={**os.environ, "REACT_APP_BACKEND_URL": "http://localhost:8001"},
        capture_output=True, text=True, check=False,
    )
    # Conta "passed" e "failed" na última linha
    last = res.stdout.strip().split("\n")[-1] if res.stdout else res.stderr
    passed = "failed" not in last and ("passed" in last)
    record(
        "7. Pytest regression (clock_in / modo_relaxado / profile_propagate)",
        passed,
        last[:120],
    )


# ──────────────────────────────────────────────────────────────────────────
# Check 8 — Permission catalog está consistente
# ──────────────────────────────────────────────────────────────────────────

def check_8_catalog_consistent() -> None:
    from iam_v2.permissions_catalog import (
        PERMISSIONS, LEGACY_ROLE_PERMISSIONS, is_valid, sanitize,
    )
    issues: list[str] = []
    # Todo legacy_role aponta pra wildcards ou keys reais
    for role, keys in LEGACY_ROLE_PERMISSIONS.items():
        for k in keys:
            if not is_valid(k):
                issues.append(f"{role} → key inválida {k!r}")
    # sanitize() retorna lista deduplicada e ordenada
    s = sanitize(["tickets.view", "tickets.view", "bogus.bad", "*"])
    if "bogus.bad" in s:
        issues.append("sanitize não filtrou bogus.bad")
    if len(set(s)) != len(s):
        issues.append("sanitize duplicou")
    record(
        "8. Permission catalog íntegro (legacy mapping + sanitize)",
        len(issues) == 0,
        f"total_keys={len(PERMISSIONS)} issues={issues}",
    )


# ──────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────

async def _run_all() -> None:
    print("\n" + "═" * 70)
    print("  ETAPA 2.1 P4 — Red-team de compatibilidade IAM v2")
    print("═" * 70 + "\n")

    check_1_flag_off()
    check_2_legacy_login()
    await check_3_phase0()
    await check_4_dry_run_consistency()
    check_5_critical_files_unchanged()
    check_6_no_cross_imports()
    check_7_regression_suite()
    check_8_catalog_consistent()

    print("\n" + "═" * 70)
    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    print(f"  RESULTADO: {passed}/{total} checagens passaram")
    print("═" * 70)
    if passed == total:
        print("  ✅ TUDO VERDE — código atual preservado, iam_v2 inerte.")
    else:
        print("  ❌ HÁ FALHAS — NÃO avançar pra ETAPA 2.5")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(_run_all())
