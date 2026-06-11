"""
scripts/lint_ticket_schema.py — Linter de schema de tickets (CTO P1 11/06/2026)

Verifica TODOS os tickets no MongoDB real contra o vocabulário canônico
definido em services/ticket_schema.py.

Uso:
  python scripts/lint_ticket_schema.py --check
  python scripts/lint_ticket_schema.py --fix
  python scripts/lint_ticket_schema.py --check --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from typing import Any, Dict, List

sys.path.insert(0, "/app/backend")

from database import db  # type: ignore  # noqa: E402
from services.ticket_schema import (  # type: ignore  # noqa: E402
    PRIORITY_ALIASES,
    PRIORITY_CANONICAL,
    STATUS_ALIASES,
    STATUS_CANONICAL,
    TYPE_ALIASES,
    normalize_priority,
    normalize_status,
    normalize_type,
)


def _classify(t: Dict[str, Any]) -> Dict[str, Any]:
    """Retorna dict { issue_field: detail } com problemas detectados."""
    issues: Dict[str, Any] = {}
    p = t.get("priority")
    if p not in PRIORITY_CANONICAL:
        issues["priority"] = {"value": p, "fixable": p in PRIORITY_ALIASES,
                              "would_become": normalize_priority(p)}
    s = t.get("status")
    if s not in STATUS_CANONICAL:
        issues["status"] = {"value": s, "fixable": s in STATUS_ALIASES,
                            "would_become": normalize_status(s)}
    ty = t.get("type")
    if ty in TYPE_ALIASES:
        issues["type"] = {"value": ty, "fixable": True,
                          "would_become": normalize_type(ty)}
    cs = t.get("client_snapshot")
    if cs is None:
        issues["client_snapshot"] = {"value": None, "fixable": False,
                                     "detail": "ausente"}
    elif not isinstance(cs, dict) or not cs.get("name"):
        issues["client_snapshot_name"] = {"value": cs, "fixable": False,
                                          "detail": "name ausente/vazio"}
    if not t.get("company_id"):
        issues["company_id"] = {"value": t.get("company_id"), "fixable": False,
                                "detail": "ausente"}
    if not t.get("assigned_collaborator_id"):
        # Pode ser inbox/sala, não é erro crítico mas conta como warning
        issues["assigned_collaborator_id"] = {"value": None, "fixable": False,
                                              "detail": "ausente (warning)",
                                              "severity": "warning"}
    sched = t.get("scheduled_time")
    if sched is not None:
        if not isinstance(sched, str) or len(sched) < 10:
            issues["scheduled_time"] = {"value": sched, "fixable": False,
                                        "detail": "formato inválido"}
    return issues


async def run_check(json_out: bool = False) -> int:
    total = 0
    invalid_total = 0
    fixable_total = 0
    by_field: Counter = Counter()
    fixable_by_field: Counter = Counter()
    samples: List[Dict[str, Any]] = []
    severity_warnings = 0

    cursor = db.tickets.find({}, {
        "_id": 0, "id": 1, "priority": 1, "status": 1, "type": 1,
        "client_snapshot": 1, "company_id": 1,
        "assigned_collaborator_id": 1, "scheduled_time": 1,
    })
    async for t in cursor:
        total += 1
        issues = _classify(t)
        if not issues:
            continue
        # warnings não contam como inválido principal
        critical_issues = {k: v for k, v in issues.items()
                           if not (isinstance(v, dict) and v.get("severity") == "warning")}
        warnings = {k: v for k, v in issues.items()
                    if isinstance(v, dict) and v.get("severity") == "warning"}
        severity_warnings += len(warnings)
        if not critical_issues:
            continue
        invalid_total += 1
        all_fixable = all((v.get("fixable") for v in critical_issues.values()))
        if all_fixable:
            fixable_total += 1
        for field, det in critical_issues.items():
            by_field[field] += 1
            if det.get("fixable"):
                fixable_by_field[field] += 1
        if len(samples) < 10:
            samples.append({"id": t.get("id"), "issues": critical_issues})

    report = {
        "total_tickets": total,
        "invalid_total": invalid_total,
        "fixable_total": fixable_total,
        "by_field": dict(by_field),
        "fixable_by_field": dict(fixable_by_field),
        "warnings_total": severity_warnings,
        "samples": samples,
        "vocab": {
            "priority": PRIORITY_CANONICAL,
            "status": STATUS_CANONICAL,
        },
    }
    if json_out:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("─" * 70)
        print(f"📋 LINT TICKETS — {total} analisados")
        print(f"❌ Inválidos:  {invalid_total}")
        print(f"🔧 Fixáveis:   {fixable_total}")
        print(f"⚠️  Warnings:  {severity_warnings} (sem assigned_collaborator_id)")
        print("─" * 70)
        if by_field:
            print("Breakdown por campo (críticos):")
            for f, c in by_field.most_common():
                print(f"  {f:35s} {c:6d}  (fixáveis: {fixable_by_field.get(f,0)})")
        if samples:
            print("\nExemplos (até 10):")
            for s in samples:
                print(f"  · {s['id']}: {s['issues']}")
        print("─" * 70)

    return invalid_total


async def run_fix(json_out: bool = False) -> int:
    fixed = 0
    untouched = 0
    cursor = db.tickets.find({}, {"_id": 0, "id": 1, "priority": 1,
                                   "status": 1, "type": 1})
    async for t in cursor:
        new_p = normalize_priority(t.get("priority"))
        new_s = normalize_status(t.get("status"))
        new_t = normalize_type(t.get("type"))
        set_doc = {}
        if new_p != t.get("priority"):
            set_doc["priority"] = new_p
        if new_s != t.get("status"):
            set_doc["status"] = new_s
        if new_t != t.get("type"):
            set_doc["type"] = new_t
        if not set_doc:
            untouched += 1
            continue
        # IMPORTANTE: chamando o método "cru" (sem interceptor) seria
        # redundante — o interceptor de database.py irá re-normalizar,
        # mas o resultado é idempotente, então é seguro.
        await db.tickets.update_one({"id": t["id"]}, {"$set": set_doc})
        fixed += 1

    report = {"fixed": fixed, "untouched": untouched}
    if json_out:
        print(json.dumps(report, indent=2))
    else:
        print(f"✅ Corrigidos: {fixed}")
        print(f"   Inalterados: {untouched}")
    return 0


async def main():
    ap = argparse.ArgumentParser(description="Linter de schema de tickets")
    ap.add_argument("--check", action="store_true", help="Apenas relatório")
    ap.add_argument("--fix", action="store_true",
                    help="Normaliza priority/status/type para canônico")
    ap.add_argument("--json", action="store_true", help="Saída JSON")
    args = ap.parse_args()

    if not (args.check or args.fix):
        ap.error("Use --check ou --fix")

    if args.fix:
        return await run_fix(args.json)
    return await run_check(args.json)


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(0 if code == 0 else 1)
