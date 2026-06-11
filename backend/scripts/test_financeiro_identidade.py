"""Validação cruzada: PRESIDENTE FINANCEIRO + IDENTIDADE 360°."""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "billing-team",
    "domain": "financeiro",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio, json, os, sys, time, uuid
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")

from database import db  # noqa: E402
from services import presidente_financeiro as pf  # noqa: E402
from services import identity_360 as id360  # noqa: E402


TENANT_FIN = "co-colosso"   # tenant Colosso já populado
PHONE_360 = "5521998176526"
COMPANY_360 = "co-demo"


async def main():
    out = {"ts": datetime.now(timezone.utc).isoformat()}

    # ===== PRESIDENTE FINANCEIRO =====
    print("[1] Presidente Financeiro — rodando atribuição cycle...")
    res = await pf.run_attribution_cycle(TENANT_FIN, window_days=90)
    out["presidente_financeiro"] = res

    # ===== IDENTIDADE 360° =====
    print("[2] Identidade 360° — cold call")
    t0 = time.time()
    ident_cold = await id360.identity_360(COMPANY_360, PHONE_360)
    cold_ms = int((time.time() - t0) * 1000)
    print(f"  cold: {cold_ms}ms")

    print("[3] Identidade 360° — hot call (cache)")
    t0 = time.time()
    ident_hot = await id360.identity_360(COMPANY_360, PHONE_360)
    hot_ms = int((time.time() - t0) * 1000)
    print(f"  hot: {hot_ms}ms (cached={ident_hot.get('cached')})")

    block = id360.format_for_isabella(ident_cold)

    out["identity_360"] = {
        "phone": PHONE_360,
        "company": COMPANY_360,
        "cold_ms": cold_ms,
        "hot_ms": hot_ms,
        "subscriber_id": (ident_cold.get("subscriber") or {}).get("id"),
        "subscriber_name": (ident_cold.get("subscriber") or {}).get("name"),
        "addresses_count": len(ident_cold.get("addresses") or []),
        "equipment_count": len(ident_cold.get("equipment") or []),
        "has_invoice": bool(ident_cold.get("last_invoice")),
        "tickets_count": len(ident_cold.get("recent_tickets") or []),
        "block_excerpt": block[:500],
        "cached_on_second_call": ident_hot.get("cached"),
    }

    # Critérios de aceite
    out["expectations"] = {
        "attribution_persisted": res.get("total_brl_attributed", 0) > 0,
        "ledger_has_kinds": len(res.get("ledger_breakdown") or []) > 0,
        "identity_under_200ms_hot": hot_ms < 200,
        "identity_under_500ms_cold": cold_ms < 500,
        "identity_cached_second_call": ident_hot.get("cached") is True,
        "block_has_content": len(block) > 0,
    }
    out["passed"] = sum(1 for v in out["expectations"].values() if v)
    out["total"] = len(out["expectations"])

    path = "/app/docs/RELATORIO_PRESIDENTE_FINANCEIRO_E_IDENTIDADE.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nSummary: {out['passed']}/{out['total']}")
    print(json.dumps(out["expectations"], indent=2))
    print(f"\n[ok] {path}")


if __name__ == "__main__":
    asyncio.run(main())
