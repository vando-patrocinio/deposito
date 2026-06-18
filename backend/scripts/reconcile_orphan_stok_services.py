"""reconcile_orphan_stok_services — Onda A Bug #2.

Marca stok_services em status="ativo" cujo ticket associado NÃO EXISTE mais
(ticket deletado/migrado/órfão) como status="orfa_sem_ticket".

Política CEO (18/06/2026):
  • PRESERVA histórico — nada é apagado.
  • NÃO conta órfã como OS ativa no painel.
  • Worker pode rodar 1x manualmente OU agendado diário.

Uso:
    # Dry-run (não escreve)
    python3 -m scripts.reconcile_orphan_stok_services --dry-run

    # Execução real
    python3 -m scripts.reconcile_orphan_stok_services

    # Para uma empresa específica (default: todas)
    python3 -m scripts.reconcile_orphan_stok_services --company-id co-demo
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
for ln in open("/app/backend/.env"):
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ.setdefault(k, v.strip('"'))


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def reconcile(*, company_id: str | None = None,
                    dry_run: bool = False) -> dict:
    """Faz a reconciliação. Retorna estatísticas."""
    from database import db

    query: dict = {"status": "ativo", "ticket_id": {"$exists": True,
                                                       "$ne": None}}
    if company_id:
        query["company_id"] = company_id

    stats = {
        "scanned": 0,
        "valid_ticket": 0,
        "orphan_marked": 0,
        "errors": 0,
        "samples_orphan": [],
        "by_company": {},
    }

    cursor = db.stok_services.find(
        query, {"_id": 0, "id": 1, "ticket_id": 1, "company_id": 1,
                 "type": 1, "technician_id": 1, "created_at": 1},
    )

    async for svc in cursor:
        stats["scanned"] += 1
        tid = svc["ticket_id"]
        cid = svc["company_id"]
        stats["by_company"].setdefault(cid, {"orphan": 0, "valid": 0})

        # Procura o ticket
        try:
            t = await db.tickets.find_one(
                {"id": tid, "company_id": cid},
                {"_id": 0, "id": 1, "status": 1},
            )
        except Exception as e:
            stats["errors"] += 1
            print(f"  ERROR consultar ticket {tid}: {e}")
            continue

        if t:
            stats["valid_ticket"] += 1
            stats["by_company"][cid]["valid"] += 1
            continue

        # Órfã: ticket não existe
        stats["orphan_marked"] += 1
        stats["by_company"][cid]["orphan"] += 1
        if len(stats["samples_orphan"]) < 10:
            stats["samples_orphan"].append({
                "id": svc["id"],
                "ticket_id": tid,
                "company_id": cid,
                "type": svc.get("type"),
                "technician_id": svc.get("technician_id"),
                "created_at": svc.get("created_at"),
            })

        if not dry_run:
            await db.stok_services.update_one(
                {"id": svc["id"], "company_id": cid},
                {"$set": {
                    "status": "orfa_sem_ticket",
                    "orphaned_at": _iso_now(),
                    "orphan_reason": "ticket_associado_nao_existe_mais",
                    # preserva o status anterior pra auditoria
                    "previous_status": "ativo",
                }},
            )

    return stats


async def main(args):
    dry = bool(args.dry_run)
    print(f"=== Reconciliação stok_services órfãs ===")
    print(f"Dry-run: {dry} · company: {args.company_id or 'TODAS'}")
    print()
    stats = await reconcile(company_id=args.company_id, dry_run=dry)
    print(f"Scanned (status=ativo + ticket_id presente): {stats['scanned']}")
    print(f"  → Ticket válido (mantém ativo): {stats['valid_ticket']}")
    print(f"  → Órfãs detectadas{' (NÃO marcadas, dry-run)' if dry else ' (marcadas como orfa_sem_ticket)'}: {stats['orphan_marked']}")
    print(f"  → Erros de consulta: {stats['errors']}")

    if stats["by_company"]:
        print(f"\nPor empresa:")
        for cid, d in sorted(stats["by_company"].items()):
            total = d["orphan"] + d["valid"]
            pct = (d["orphan"] / total * 100) if total else 0
            print(f"  {cid}: {d['valid']} válidas + {d['orphan']} órfãs "
                  f"({pct:.1f}% órfã)")

    if stats["samples_orphan"]:
        print(f"\nAmostras de órfãs (até 10):")
        for s in stats["samples_orphan"]:
            print(f"  {s['id']} (svc {s['type']}) · ticket={s['ticket_id']} · tech={s['technician_id']} · criada {s['created_at']}")

    print()
    if dry:
        print("⚠️  DRY-RUN: nenhum documento foi alterado. "
              "Rode sem --dry-run para aplicar.")
    else:
        print(f"✓  {stats['orphan_marked']} stok_services marcadas como 'orfa_sem_ticket'.")
        print("   Histórico preservado em 'previous_status' e 'orphaned_at'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                          help="só mostra o que seria feito, sem alterar")
    parser.add_argument("--company-id", default=None,
                          help="limitar a uma empresa (default: todas)")
    args = parser.parse_args()
    asyncio.run(main(args))
