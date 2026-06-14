"""Lista oficial de tenants sintéticos / QA / órfãos da Ligo.

Resultado da OPERAÇÃO MAPA DA BASE (14/06/2026) — ver
`/app/memory/TENANT_SANITY_CHECK.md` para evidência completa.

REGRA DE OURO:
    Nenhum dashboard executivo, KPI gerencial, briefing CEO, score de IA,
    relatório de receita por agente, NPS, churn ou ranking pode somar
    tenants sintéticos por padrão.

USO:
    from constants.synthetic_tenants import real_tenant_filter

    # Em vez de:
    q = {} if cid is None else {"company_id": cid}

    # Use:
    q = real_tenant_filter(cid)

    # Para incluir sintéticos explicitamente (QA/debug):
    q = real_tenant_filter(cid, include_synthetic=True)
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

# Tenants nominalmente sintéticos / QA — confirmados via auditoria.
SYNTHETIC_TENANTS: list[str] = [
    # SINTÉTICO LOAD (10k/2k seeds)
    "co-colosso",
    "co-fantasma-v4",
    "co-fantasma-v3",
    "co-fantasma-test",
    # QA / CI FIXTURES
    "co-attribution-test",
    "co-id-auto",
    "co-pilot-1",
    "co-mem-test",
    "co-tesoureira-test",
    "co-schema-test",
    "co-homolog-v8",
    "co-nonexistent-xyz",
    "co-test-p1",
    "co-test-v11",
    "co-test-a0bae9",
    "co-test-51a57c42",
    "co-test-5795815d",
    # DIAGNÓSTICOS / BENCHMARKS
    "demo-cto-audit",
    "benchmark",
    "perf-bench",
    "pilot-sim-72h",
    "tst-audit-co",
    "tst-d8",
    "co-prod",  # fixture confusa (4 docs, não é prod real)
    # ÓRFÃOS / WILDCARDS
    "_orphan",
    "*",
]

# Prefixos sintéticos detectados via regex (cobre ~50 tenants hash auto-gerados).
_SYNTHETIC_PREFIX_PATTERNS = [
    r"^test-",
    r"^tst-",
    r"^co-test-",
    r"^test-dq-",
    r"^test-e2e-",
    r"^test-adj-",
    r"^test-pred-",
    r"^test-v\d+$",
]

# UUID/hash truncado: `co-` seguido de 8+ hex chars puros, ou hex puro.
_SYNTHETIC_HASH_RE = re.compile(r"^(co-)?[0-9a-f]{10,}$")

_SYNTHETIC_PREFIX_RE = re.compile("|".join(_SYNTHETIC_PREFIX_PATTERNS))


def is_synthetic_tenant(tenant_id: Optional[str]) -> bool:
    """Retorna True se o tenant é sintético/QA/órfão."""
    if not tenant_id:
        return False
    if tenant_id in SYNTHETIC_TENANTS:
        return True
    if _SYNTHETIC_PREFIX_RE.match(tenant_id):
        return True
    if _SYNTHETIC_HASH_RE.match(tenant_id):
        return True
    return False


def real_tenant_filter(
    cid: Optional[str],
    *,
    field: str = "company_id",
    include_synthetic: bool = False,
) -> Dict[str, Any]:
    """Constrói filtro Mongo padronizado.

    - cid != None        → escopo do tenant pedido (sem $nin).
    - cid == None + !inc → cross-tenant SEM sintéticos (filtro $nin aplicado).
    - cid == None + inc  → cross-tenant SEM filtro (admin override).
    """
    if cid:
        return {field: cid}
    if include_synthetic:
        return {}
    return {field: {"$nin": SYNTHETIC_TENANTS}}


def extend_filter_real(
    base: Dict[str, Any],
    cid: Optional[str],
    *,
    field: str = "company_id",
    include_synthetic: bool = False,
) -> Dict[str, Any]:
    """Mescla `real_tenant_filter` num dict base existente.

    Exemplo:
        q = extend_filter_real({"active": True}, cid)
        # → {"active": True, "company_id": ...}
    """
    out = dict(base or {})
    out.update(real_tenant_filter(cid, field=field,
                                  include_synthetic=include_synthetic))
    return out


__all__ = [
    "SYNTHETIC_TENANTS",
    "is_synthetic_tenant",
    "real_tenant_filter",
    "extend_filter_real",
]
