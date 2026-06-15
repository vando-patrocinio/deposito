"""CLI — Executive Memory snapshot/backfill/rollback.

Uso:
  python3 scripts/executive_memory_snapshot.py                 # snapshot do dia
  python3 scripts/executive_memory_snapshot.py --backfill 30   # popula histórico
  python3 scripts/executive_memory_snapshot.py --rollback      # reverte
"""
import argparse
import asyncio
import json
import sys
import time

sys.path.insert(0, "/app/backend")
from services import executive_memory as em  # noqa: E402


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cid", default="co-demo")
    p.add_argument("--backfill", type=int, default=0,
                   help="Backfill N dias (snapshot do dia replicado).")
    p.add_argument("--rollback", action="store_true")
    args = p.parse_args()

    if args.rollback:
        print(await em.rollback(args.cid))
        return 0

    if args.backfill > 0:
        t = time.time()
        r = await em.backfill_history(args.cid, args.backfill)
        print(f"[BACKFILL] {r} · {(time.time()-t):.2f}s")

    t = time.time()
    snap = await em.snapshot_today(args.cid)
    print(f"[SNAPSHOT] {(time.time()-t):.2f}s")
    print(json.dumps(snap, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
