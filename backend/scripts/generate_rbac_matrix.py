"""
generate_rbac_matrix.py — Gera RBAC_MATRIX.md (Sprint 2 / iter221)

Lê todas as rotas do FastAPI + `rbac_policy.py` e produz um Markdown:
  - Resumo executivo (cobertura, contagens)
  - Matriz por prefixo: roles permitidos, audit, rate-limit
  - Lista de DELETE (audit obrigatório)
  - Lista de EXPORT (audit obrigatório)
  - Lista de IA (rate-limit obrigatório)
  - Endpoints auth-only legítimos (utilitários self)
  - Public/non-staff portals

Uso:
    cd /app/backend && python -m scripts.generate_rbac_matrix
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
from datetime import datetime, timezone
from typing import Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.audit_rbac_coverage import (
    classify_route, load_app, EXPORT_HINTS,
)


def main() -> int:
    app = load_app()
    import rbac_policy as policy_mod

    routes = []
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None) or {"GET"}
        if not path or not path.startswith("/api/"):
            continue
        for m in sorted(methods):
            if m in ("HEAD", "OPTIONS"):
                continue
            routes.append(classify_route(m, path, policy_mod))

    by_prefix: Dict[str, List[dict]] = defaultdict(list)
    for r in routes:
        parts = r["path"].split("/", 3)
        key = "/" + "/".join(parts[1:3]) if len(parts) >= 3 else r["path"]
        by_prefix[key].append(r)

    total = len(routes)
    pub = sum(1 for r in routes if r["public"])
    nstaff = sum(1 for r in routes if r["non_staff_auth"])
    staff_priv = sum(1 for r in routes
                       if not r["public"] and not r["non_staff_auth"])
    role_prot = sum(1 for r in routes if r["has_role_rule"])
    cov = round(100.0 * role_prot / max(staff_priv, 1), 2)

    delete_routes = [r for r in routes if r["destructive"]]
    export_routes = [r for r in routes if r["export"]]
    ia_routes = [r for r in routes if r["ia"]]
    auth_only = [r for r in routes
                   if not r["public"] and not r["non_staff_auth"]
                   and not r["has_role_rule"]]

    ts = datetime.now(timezone.utc).isoformat()
    lines: List[str] = []
    lines.append("# RBAC Matrix — SmartProv (Sprint 2)")
    lines.append("")
    lines.append(f"> Gerado automaticamente em **{ts}** por"
                  f" `scripts/generate_rbac_matrix.py`.")
    lines.append("> Não edite à mão — a fonte da verdade é"
                  f" `rbac_policy.py`.")
    lines.append("")
    lines.append("## Sumário executivo")
    lines.append("")
    lines.append(f"- **Total de endpoints `/api/*`:** {total}")
    lines.append(f"- **Públicos (sem auth):** {pub}")
    lines.append("- **Endpoints com auth não-staff (portais cliente/"
                  f"parceiro/segurança/frota):** {nstaff}")
    lines.append(f"- **Staff privados (sob RBAC corporativo):** {staff_priv}")
    lines.append(f"- **Com role-rule explícita:** {role_prot}")
    lines.append(f"- **DELETE (audit obrigatório):** {len(delete_routes)}")
    lines.append(f"- **EXPORT (audit obrigatório):** {len(export_routes)}")
    lines.append(f"- **IA (rate-limit obrigatório):** {len(ia_routes)}")
    lines.append("")
    lines.append(f"### 🎯 Cobertura RBAC: **{cov}%** (meta ≥ 70%)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Como funciona")
    lines.append("")
    lines.append("Todo request `/api/*` passa por `_rbac_middleware` em")
    lines.append("`server.py`, que:")
    lines.append("")
    lines.append("1. Libera se o path está em `PUBLIC_PATHS` "
                  "(webhooks, login, health).")
    lines.append("2. Decodifica JWT (401 se ausente/inválido).")
    lines.append("3. Pula role-check em portais não-staff "
                  "(`NON_STAFF_AUTH_PREFIXES`).")
    lines.append("4. Aplica `required_roles_for(path)` (longest-prefix "
                  "match) — **403** se role do user não está no set "
                  "permitido. `administrador` SEMPRE passa.")
    lines.append("5. Em rotas IA aplica `rate_limit` "
                  "(`IA_RATE_LIMIT_PREFIXES`) — **429** se exceder.")
    lines.append("6. Em DELETE/EXPORT grava entrada em `audit_log`.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Matriz de permissões por prefixo")
    lines.append("")
    lines.append("| Prefixo | Roles permitidos | IA rate-limit | "
                  "Endpoints |")
    lines.append("|---------|------------------|---------------|"
                  "-----------|")

    # ordena por prefixo
    for prefix in sorted(by_prefix.keys()):
        rs = by_prefix[prefix]
        sample = rs[0]
        if sample["public"]:
            roles = "PÚBLICO"
        elif sample["non_staff_auth"]:
            roles = "portal próprio"
        elif sample["has_role_rule"]:
            roles = ", ".join(sample["roles"] or [])
            roles = f"admin*, {roles}" if roles else "admin*"
        else:
            roles = "auth-only"
        ia = "✅" if sample["ia"] else ""
        lines.append(f"| `{prefix}/*` | {roles} | {ia} | {len(rs)} |")

    lines.append("")
    lines.append("> `admin*` = `administrador` sempre passa em qualquer "
                  "rota com role-rule (super-role).")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## DELETE — audit_log obrigatório (77 endpoints)")
    lines.append("")
    lines.append("| Método | Path | Roles |")
    lines.append("|--------|------|-------|")
    for r in sorted(delete_routes, key=lambda x: x["path"]):
        roles = ", ".join(r["roles"] or []) if r["roles"] else "—"
        lines.append(f"| {r['method']} | `{r['path']}` | {roles} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"## EXPORT — audit_log obrigatório "
                  f"({len(export_routes)} endpoints)")
    lines.append("")
    lines.append("Considera paths com qualquer um destes hints:")
    lines.append(f"`{', '.join(EXPORT_HINTS)}`.")
    lines.append("")
    lines.append("| Método | Path | Roles |")
    lines.append("|--------|------|-------|")
    for r in sorted(export_routes, key=lambda x: x["path"]):
        roles = ", ".join(r["roles"] or []) if r["roles"] else "—"
        lines.append(f"| {r['method']} | `{r['path']}` | {roles} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"## IA — rate-limit obrigatório "
                  f"({len(ia_routes)} endpoints)")
    lines.append("")
    lines.append("Limite padrão: **30 req/min**, **1000 req/dia** por "
                  "usuário (5x por empresa). Configurável via env "
                  "`IA_RATE_PER_MIN`/`IA_RATE_PER_DAY`.")
    lines.append("")
    ia_prefixes = sorted(set(
        "/" + "/".join(r["path"].split("/", 3)[1:3]) for r in ia_routes
    ))
    for p in ia_prefixes:
        n = sum(1 for r in ia_routes if r["path"].startswith(p + "/")
                  or r["path"] == p)
        lines.append(f"- `{p}/*` — {n} endpoints")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"## Auth-only legítimos ({len(auth_only)} endpoints)")
    lines.append("")
    lines.append("Endpoints onde QUALQUER usuário autenticado pode "
                  "acessar (consulta o próprio dado, utilitários).")
    lines.append("")
    for r in sorted(auth_only, key=lambda x: x["path"]):
        lines.append(f"- `{r['method']} {r['path']}`")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Públicos (sem auth)")
    lines.append("")
    for p in sorted(set(r["path"] for r in routes if r["public"])):
        lines.append(f"- `{p}`")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Roles do sistema")
    lines.append("")
    lines.append("| Role | Descrição |")
    lines.append("|------|-----------|")
    lines.append("| `administrador` | Super-admin. Passa em "
                  "**TODAS** as rotas. |")
    lines.append("| `gestor` | Gerência operacional. Tem acesso a "
                  "financeiro, IA, lousa, frota, clientes. |")
    lines.append("| `financeiro` | Apenas módulos de billing, payments, "
                  "boleto, atlaz, holerites. |")
    lines.append("| `auditor` | Read-only em quase tudo (relatórios, "
                  "diagnóstico, audit-log). |")
    lines.append("| `tecnico` | Operação de campo: lousa, OLT, CTOs, "
                  "checklists, frota. |")
    lines.append("| `atendimento` | Atendimento ao cliente: chat, pré-"
                  "atendimento, agendamentos. |")
    lines.append("| `colaborador` | Mobile / ponto eletrônico (acesso "
                  "mínimo). |")
    lines.append("")
    lines.append("> Roles não-staff (clientes/parceiros/seg. residencial) "
                  "usam JWT próprio com seus próprios endpoints "
                  "(portais `/api/customer`, `/api/cliente-portal`, "
                  "`/api/parceiro-portal`, `/api/security-portal`, "
                  "`/api/fleet-portal`).")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Como adicionar/alterar permissão")
    lines.append("")
    lines.append("1. Edite `/app/backend/rbac_policy.py` e ajuste "
                  "`ROLE_RULES`.")
    lines.append("2. Rode `python -m scripts.audit_rbac_coverage` para "
                  "validar.")
    lines.append("3. Rode `python -m scripts.generate_rbac_matrix` para "
                  "regenerar este arquivo.")
    lines.append("4. Rode `pytest backend/tests/test_rbac_sprint2.py` "
                  "para garantir que cobertura ≥ 70% e nenhum endpoint "
                  "crítico vaza.")
    lines.append("")

    out = "\n".join(lines)
    out_path = os.path.join(ROOT, "RBAC_MATRIX.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"[ok] RBAC_MATRIX.md gerado em {out_path}")
    print(f"[ok] {total} endpoints, cobertura {cov}%, "
          f"DELETE={len(delete_routes)}, EXPORT={len(export_routes)}, "
          f"IA={len(ia_routes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
