"""
audit_rbac_coverage.py — Auditoria de cobertura RBAC (Sprint 2 / iter221)

Carrega o app FastAPI, lista TODAS as rotas /api/*, classifica cada uma
contra `rbac_policy.py` e imprime relatório em JSON com:
  - total de endpoints
  - cobertura por categoria (público / auth-only / role-rule / destructive
    / export / ia)
  - lista de endpoints sem role-rule (potenciais buracos)
  - % de cobertura

Uso:
    cd /app/backend && python -m scripts.audit_rbac_coverage [--json]
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "shield",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import json
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List

# Garante /app/backend no path quando rodado standalone.
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def load_app():
    os.environ.setdefault("ALLOW_MOCK_MODULES", "true")
    # evita inicialização de scheduler/jobs ao importar server
    os.environ.setdefault("SKIP_STARTUP_JOBS", "1")
    from server import app  # noqa: E402
    return app


IA_PREFIXES = (
    "/api/presidente-ia", "/api/conselho-ia", "/api/motor-ia",
    "/api/alvaro", "/api/secretaria", "/api/aihub", "/api/central-ia",
    "/api/rede-ia", "/api/ai-training", "/api/ai/preventive",
    "/api/disparo-ia", "/api/neo-reports", "/api/smartolt-ai",
    "/api/ai-topology", "/api/copilot-ranking", "/api/checklist-ai",
    "/api/lousa-ai", "/api/sentinela-lousa", "/api/loyalty-ai",
    "/api/loyalty-opportunities-ai", "/api/ai-corrections",
    "/api/ai-config", "/api/neo-chat", "/api/voice",
)

EXPORT_HINTS = ("/export", "/download", ".pdf", ".csv", ".xlsx",
                "/pdf-reports")


def classify_route(method: str, path: str, policy_mod) -> Dict[str, Any]:
    is_public = policy_mod.is_public(path)
    is_destructive = (method.upper() == "DELETE")
    is_export = any(h in path for h in EXPORT_HINTS)
    is_ia = any(path.startswith(p) for p in IA_PREFIXES)
    is_non_staff = (not is_public) and policy_mod.is_non_staff_auth(path)
    roles = (None if (is_public or is_non_staff)
             else policy_mod.required_roles_for(path))
    return {
        "method": method,
        "path": path,
        "public": is_public,
        "non_staff_auth": is_non_staff,
        "destructive": is_destructive,
        "export": is_export,
        "ia": is_ia,
        "roles": sorted(list(roles)) if roles else None,
        "has_role_rule": roles is not None,
    }


def main() -> int:
    app = load_app()
    import rbac_policy as policy_mod

    routes: List[Dict[str, Any]] = []
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None) or {"GET"}
        if not path or not path.startswith("/api/"):
            continue
        for m in sorted(methods):
            if m == "HEAD" or m == "OPTIONS":
                continue
            routes.append(classify_route(m, path, policy_mod))

    total = len(routes)
    public = [r for r in routes if r["public"]]
    private = [r for r in routes if not r["public"]]
    non_staff = [r for r in private if r["non_staff_auth"]]
    staff_private = [r for r in private if not r["non_staff_auth"]]
    role_protected = [r for r in staff_private if r["has_role_rule"]]
    auth_only = [r for r in staff_private if not r["has_role_rule"]]
    destructive = [r for r in routes if r["destructive"]]
    export = [r for r in routes if r["export"]]
    ia_routes = [r for r in routes if r["ia"]]
    ia_unprotected = [r for r in ia_routes
                        if not r["public"] and not r["has_role_rule"]
                        and not r["non_staff_auth"]]
    destructive_no_role = [r for r in destructive
                              if not r["public"]
                              and not r["non_staff_auth"]
                              and not r["has_role_rule"]]
    export_no_role = [r for r in export
                         if not r["public"]
                         and not r["non_staff_auth"]
                         and not r["has_role_rule"]]

    # Cobertura: % das rotas staff-privadas que têm role-rule.
    coverage_pct = (
        100.0 * len(role_protected) / max(len(staff_private), 1)
    )

    by_prefix: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"total": 0, "role": 0, "auth_only": 0, "public": 0})
    for r in routes:
        # agrupa por 2º segmento (/api/<seg>/...)
        parts = r["path"].split("/", 3)
        key = "/" + "/".join(parts[1:3]) if len(parts) >= 3 else r["path"]
        by_prefix[key]["total"] += 1
        if r["public"]:
            by_prefix[key]["public"] += 1
        elif r["has_role_rule"]:
            by_prefix[key]["role"] += 1
        else:
            by_prefix[key]["auth_only"] += 1

    report = {
        "summary": {
            "total_endpoints": total,
            "public": len(public),
            "private": len(private),
            "non_staff_auth_protected": len(non_staff),
            "staff_private": len(staff_private),
            "role_protected": len(role_protected),
            "auth_only_no_role": len(auth_only),
            "destructive_DELETE": len(destructive),
            "export_routes": len(export),
            "ia_routes": len(ia_routes),
            "ia_routes_unprotected": len(ia_unprotected),
            "destructive_without_role": len(destructive_no_role),
            "export_without_role": len(export_no_role),
            "coverage_pct": round(coverage_pct, 2),
        },
        "by_prefix": dict(sorted(by_prefix.items())),
        "samples": {
            "auth_only_no_role": [
                f"{r['method']} {r['path']}" for r in auth_only[:60]
            ],
            "destructive_without_role": [
                f"{r['method']} {r['path']}" for r in destructive_no_role
            ],
            "export_without_role": [
                f"{r['method']} {r['path']}" for r in export_no_role
            ],
            "ia_unprotected": [
                f"{r['method']} {r['path']}" for r in ia_unprotected
            ],
        },
    }

    out_json = "--json" in sys.argv
    if out_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        s = report["summary"]
        print("══ RBAC Coverage — Sprint 2 ══")
        print(f"Total endpoints /api/*  : {s['total_endpoints']}")
        print(f"Públicos                : {s['public']}")
        print(f"Não-staff auth (portais): {s['non_staff_auth_protected']}")
        print(f"Staff privados          : {s['staff_private']}")
        print(f"   ✓ Com role-rule      : {s['role_protected']}")
        print(f"   ✗ Só auth (sem role) : {s['auth_only_no_role']}")
        print(f"DELETE total            : {s['destructive_DELETE']}")
        print(f"   sem role-rule        : {s['destructive_without_role']}")
        print(f"Exports (pdf/csv/...)   : {s['export_routes']}")
        print(f"   sem role-rule        : {s['export_without_role']}")
        print(f"IA total                : {s['ia_routes']}")
        print(f"   sem role-rule        : {s['ia_routes_unprotected']}")
        print(f"COBERTURA (role/staff)  : {s['coverage_pct']}%")
        print()
        print("Top auth-only sem role (amostra 30):")
        for line in report["samples"]["auth_only_no_role"][:30]:
            print(f"  {line}")

    # também grava no disco pra automation
    out_path = os.path.join(ROOT, "rbac_coverage_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    sys.stderr.write(f"\n[i] Relatório gravado em {out_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
