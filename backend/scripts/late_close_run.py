"""CLI wrapper para late_close_worker."""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, "/app/backend")
for ln in open("/app/backend/.env"):
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ.setdefault(k, v.strip('"'))


async def main(args):
    from services.late_close_worker import run_late_close
    print(f"=== Late close worker ===")
    print(f"Dry-run: {args.dry_run} · grace={args.grace}s · "
          f"company={args.company_id or 'TODAS'}")
    stats = await run_late_close(
        company_id=args.company_id,
        grace_seconds=args.grace,
        dry_run=args.dry_run,
        limit=args.limit,
    )
    print()
    print(f"Candidatos: {stats['candidates_found']}")
    print(f"Fechados OK: {stats['closed_ok']}")
    print(f"Falhas: {stats['closed_failed']}")
    print(f"Duração: {stats['duration_ms']}ms")
    if stats["samples_closed"]:
        print(f"\nAmostras fechadas:")
        for s in stats["samples_closed"][:10]:
            print(f"  {s.get('stok_service_id')} · ticket={s.get('ticket_id')} · "
                  f"used={s.get('used_items', '—')}")
    if stats["failures"]:
        print(f"\nFalhas:")
        for f in stats["failures"][:5]:
            print(f"  {f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--company-id", default=None)
    p.add_argument("--grace", type=int, default=60,
                    help="grace_seconds (default 60)")
    p.add_argument("--limit", type=int, default=500)
    args = p.parse_args()
    asyncio.run(main(args))
