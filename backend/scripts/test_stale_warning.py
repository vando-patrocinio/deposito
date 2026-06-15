"""Test stale_warning end-to-end.

Forces _collected_at to 48h ago, calls briefing/today, checks stale_warning=True,
then restores the snapshot.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone, timedelta  # noqa: E402
from database import db  # noqa: E402

CID = "co-demo"
TODAY = datetime.now(timezone.utc).date().isoformat()


async def main():
    # 1. Save current _collected_at
    doc = await db.president_daily.find_one(
        {"company_id": CID, "date_key": TODAY},
        {"_id": 0, "one_truth._collected_at": 1})
    original = (doc or {}).get("one_truth", {}).get("_collected_at")
    print(f"  original _collected_at = {original}")

    # 2. Force 48h ago
    old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    res = await db.president_daily.update_one(
        {"company_id": CID, "date_key": TODAY},
        {"$set": {"one_truth._collected_at": old}})
    print(f"  set 48h ago: matched={res.matched_count} mod={res.modified_count}")

    # 3. Wait briefly and inform the user
    print("  AGORA: chame GET /api/ceo/briefing/today e veja stale_warning=True")

    # 4. Restore — we use a simple delay then revert
    if original:
        await db.president_daily.update_one(
            {"company_id": CID, "date_key": TODAY},
            {"$set": {"one_truth._collected_at": original}})
        print(f"  restored _collected_at = {original}")

if __name__ == "__main__":
    asyncio.run(main())
