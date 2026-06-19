"""Phase C.2 — Genesis Quarentena V2 (CEO 19/06/2026)

Estratégia:
- SmartOLT NÃO tem pppoe_user populado em massa (1/1833). 
- Mas a `quarantine` tem `client_name` (GTW/OLT) que casa com 
  `subscribers.pppoe_user` ou `subscribers.name` (normalizados).
- Match exato + 1:1 → confidence 0.95 → promove para `tier=official`.
- Match substring 1:1 → confidence 0.90 → também promove.

Zero delete. Audit log SHA-256 em `genesis_quarantine_promotion_runs`.
"""
import asyncio
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")


def _norm(s):
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]", "", s.lower())


async def run(company_id: str = "co-demo", dry_run: bool = False,
              min_confidence: float = 0.90):
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    now = datetime.now(timezone.utc).isoformat()
    run_id = f"genv2-{uuid.uuid4().hex[:8]}"

    # 1) Build subscriber index
    subs_by_norm: dict[str, list[dict]] = {}
    cur = db.subscribers.find({"company_id": company_id},
        {"_id": 0, "id": 1, "name": 1, "full_name": 1, "pppoe_user": 1,
         "pppoe": 1, "status": 1, "cto_id": 1, "cto_port_number": 1,
         "current_ont": 1, "ont_sn": 1})
    async for s in cur:
        names = [s.get("name"), s.get("full_name"),
                 s.get("pppoe_user"), s.get("pppoe")]
        for n in names:
            nn = _norm(n)
            if nn and len(nn) >= 5:
                subs_by_norm.setdefault(nn, []).append(s)

    # 2) Classify quarantine
    cur = db.stok_onts.find({"company_id": company_id,
        "asset_status": "pending_validation"},
        {"_id": 0, "id": 1, "client_name": 1, "sn": 1, "mac": 1,
         "olt_name": 1, "port_olt": 1})

    to_promote = []  # (ont_doc, sub_doc, confidence, path)
    skipped = []
    async for q in cur:
        cn = _norm(q.get("client_name"))
        if not cn or len(cn) < 5:
            skipped.append((q["id"], "client_name_too_short"))
            continue
        if cn in subs_by_norm and len(subs_by_norm[cn]) == 1:
            to_promote.append((q, subs_by_norm[cn][0], 0.95, "exact_1to1"))
            continue
        # substring
        hits = [k for k in subs_by_norm if cn in k or k in cn]
        unique_subs = []
        for h in hits:
            if len(subs_by_norm[h]) == 1:
                unique_subs.append(subs_by_norm[h][0])
        # dedupe by sub id
        unique_ids = list({s["id"] for s in unique_subs})
        if len(unique_ids) == 1:
            to_promote.append((q, unique_subs[0], 0.90, "substring_1to1"))
        elif len(unique_ids) > 1:
            skipped.append((q["id"], "ambiguous"))
        else:
            skipped.append((q["id"], "no_match"))

    promoted_count = 0
    promotion_ids = []
    if not dry_run:
        for q, s, conf, path in to_promote:
            if conf < min_confidence:
                continue
            await db.stok_onts.update_one(
                {"id": q["id"]},
                {"$set": {
                    "tier": "official",
                    "asset_status": "validado",
                    "exclude_from_balance": False,
                    "subscriber_id": s["id"],
                    "data_confidence": conf,
                    "data_confidence_path": path,
                    "promoted_at": now,
                    "promoted_by": "phase_c2_genesis_v2",
                    "phase_c2_run_id": run_id,
                    "promotion_evidence": {
                        "matched_subscriber_id": s["id"],
                        "matched_subscriber_name": s.get("name"),
                        "matched_via": path,
                        "client_name_quarantine": q.get("client_name"),
                    },
                }},
            )
            promotion_ids.append({"ont_id": q["id"], "subscriber_id": s["id"],
                "confidence": conf, "path": path})
            promoted_count += 1

    # 3) Final state + audit
    after_official = await db.stok_onts.count_documents(
        {"company_id": company_id, "tier": "official"})
    after_quar = await db.stok_onts.count_documents(
        {"company_id": company_id, "tier": "quarantine"})
    smartolt = await db.smartolt_onus.count_documents(
        {"company_id": company_id})
    cobertura = round(after_official / smartolt * 100, 2) if smartolt else 0
    compliance = round(after_official / (after_official + after_quar) * 100, 2) \
        if after_official else 0

    audit = {
        "run_id": run_id,
        "company_id": company_id,
        "executed_at": now,
        "executed_by": "phase_c2_genesis_quarantine_v2",
        "dry_run": dry_run,
        "min_confidence": min_confidence,
        "candidates_to_promote": len(to_promote),
        "promoted": promoted_count,
        "skipped_ambiguous_or_no_match": len(skipped),
        "skip_breakdown": {r: sum(1 for x in skipped if x[1] == r)
                           for r in {"ambiguous", "no_match",
                                     "client_name_too_short"}},
        "kpis_after": {
            "tier_official": after_official,
            "tier_quarantine": after_quar,
            "smartolt_total": smartolt,
            "cobertura_operacional_pct": cobertura,
            "compliance_pct": compliance,
        },
        "ceo_authorization": "Phase C.2 — 19/06/2026",
    }
    audit["hash_sha256"] = hashlib.sha256(
        json.dumps(audit, sort_keys=True, default=str).encode()
    ).hexdigest()
    if not dry_run:
        await db.genesis_quarantine_promotion_runs.insert_one(dict(audit))

    print("=" * 64)
    print("PHASE C.2 — GENESIS QUARENTENA V2")
    print("=" * 64)
    print(f"run_id={run_id}  dry_run={dry_run}")
    print(f"  Candidates to promote (conf>={min_confidence}): "
          f"{len(to_promote)}")
    print(f"  Actually promoted:                {promoted_count}")
    print(f"  Skipped:                          {len(skipped)}")
    print(f"     ambiguous:     {audit['skip_breakdown'].get('ambiguous', 0)}")
    print(f"     no_match:      {audit['skip_breakdown'].get('no_match', 0)}")
    print(f"     short_client:  "
          f"{audit['skip_breakdown'].get('client_name_too_short', 0)}")
    print(f"  KPIs after:")
    print(f"     official:                     {after_official}")
    print(f"     quarantine:                   {after_quar}")
    print(f"     cobertura_operacional_pct:    {cobertura} %")
    print(f"     compliance_pct:               {compliance} %")
    print(f"  hash_sha256: {audit['hash_sha256']}")
    print("=" * 64)
    return audit


if __name__ == "__main__":
    import sys
    asyncio.run(run(dry_run="--dry" in sys.argv))
