"""Onda C P0.3 — Export CSV dos stok_services órfãos (READ-ONLY).

Gera CSV com a lista completa de stok_services em status=`orfa_sem_ticket`
(marcados pela Onda A). Cada linha contém o contexto necessário para
triagem humana FORA do sistema (planilha, reunião operacional).

Saída padrão: /app/memory/STOK_SERVICES_ORFAOS.csv

Colunas:
  service_id, type, technician_id, technician_name, client_id, client_name,
  ticket_id, previous_status, orphan_reason, orphaned_at, created_at,
  is_defective, defective_reason, auto_opened, company_id

ZERO writes. Apenas leitura.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, "/app/backend")
for _ln in open("/app/backend/.env"):
    if "=" in _ln and not _ln.startswith("#"):
        _k, _v = _ln.strip().split("=", 1)
        os.environ.setdefault(_k, _v.strip('"'))

from database import db  # noqa: E402

DEFAULT_OUTPUT = "/app/memory/STOK_SERVICES_ORFAOS.csv"

COLUMNS = [
    "service_id", "company_id", "type", "previous_status",
    "orphan_reason", "orphaned_at", "created_at",
    "technician_id", "technician_name",
    "client_id", "client_name",
    "ticket_id", "ticket_exists", "ticket_status",
    "is_defective", "defective_reason",
    "auto_opened", "reason",
]


async def _load_orfas(company_id: str | None) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"status": "orfa_sem_ticket"}
    if company_id:
        q["company_id"] = company_id
    out: List[Dict[str, Any]] = []
    async for d in db.stok_services.find(q, {"_id": 0}).sort("orphaned_at", 1):
        out.append(d)
    return out


async def _enrich(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Adiciona técnico.nome (se ausente) e ticket_status (se existir)."""
    # Cache de técnicos
    tech_ids = {r.get("technician_id") for r in rows if r.get("technician_id")}
    techs: Dict[str, str] = {}
    if tech_ids:
        async for c in db.collaborators.find(
                {"id": {"$in": list(tech_ids)}},
                {"_id": 0, "id": 1, "name": 1}):
            techs[c["id"]] = c.get("name") or ""

    # Cache de tickets (se existem)
    tkt_ids = {r.get("ticket_id") for r in rows if r.get("ticket_id")}
    tickets: Dict[str, Dict[str, Any]] = {}
    if tkt_ids:
        async for t in db.tickets.find(
                {"id": {"$in": list(tkt_ids)}},
                {"_id": 0, "id": 1, "status": 1}):
            tickets[t["id"]] = t

    out = []
    for r in rows:
        tid = r.get("technician_id") or ""
        kid = r.get("ticket_id") or ""
        tkt = tickets.get(kid)
        out.append({
            "service_id": r.get("id"),
            "company_id": r.get("company_id"),
            "type": r.get("type"),
            "previous_status": r.get("previous_status"),
            "orphan_reason": r.get("orphan_reason"),
            "orphaned_at": r.get("orphaned_at"),
            "created_at": r.get("created_at"),
            "technician_id": tid,
            "technician_name": r.get("technician_name") or techs.get(tid, ""),
            "client_id": r.get("client_id"),
            "client_name": r.get("client_name"),
            "ticket_id": kid,
            "ticket_exists": bool(tkt),
            "ticket_status": (tkt or {}).get("status") or "",
            "is_defective": r.get("is_defective", False),
            "defective_reason": r.get("defective_reason") or "",
            "auto_opened": r.get("auto_opened", False),
            "reason": r.get("reason") or "",
        })
    return out


def _print_summary(rows: List[Dict[str, Any]]):
    from collections import Counter
    print()
    print("=" * 72)
    print("  STOK_SERVICES ÓRFÃOS — EXPORT CSV (READ-ONLY)")
    print("=" * 72)
    print(f"\n  Total: {len(rows)} órfãs")
    print(f"\n  Por tipo:")
    for k, n in Counter(r["type"] for r in rows).most_common():
        print(f"    · {k}: {n}")
    print(f"\n  Por motivo:")
    for k, n in Counter(r["orphan_reason"] for r in rows).most_common():
        print(f"    · {k}: {n}")
    print(f"\n  Por previous_status:")
    for k, n in Counter(r["previous_status"] for r in rows).most_common():
        print(f"    · {k}: {n}")
    print(f"\n  Por técnico (top 5):")
    for k, n in Counter(r["technician_name"] for r in rows).most_common(5):
        print(f"    · {k or '(sem técnico)'}: {n}")
    ticket_exists = sum(1 for r in rows if r["ticket_exists"])
    print(f"\n  Ticket original ainda existe? sim={ticket_exists}, não={len(rows)-ticket_exists}")


async def main():
    ap = argparse.ArgumentParser(description="P0.3 Export órfãs (CSV)")
    ap.add_argument("--company-id", default=None,
                    help="Filtra por uma empresa (default: todas)")
    ap.add_argument("--output", default=DEFAULT_OUTPUT,
                    help="Caminho do CSV")
    ap.add_argument("--print-only", action="store_true",
                    help="Não escreve arquivo, apenas stdout")
    args = ap.parse_args()

    rows = await _load_orfas(args.company_id)
    enriched = await _enrich(rows)

    _print_summary(enriched)

    if args.print_only:
        for r in enriched:
            print(r)
        return

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in enriched:
            writer.writerow(r)
    print(f"\n✅ CSV salvo em: {out_path} ({len(enriched)} linhas)")


if __name__ == "__main__":
    asyncio.run(main())
