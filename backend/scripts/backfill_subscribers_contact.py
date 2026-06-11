"""
backfill_subscribers_contact.py — FASE 2 da Constituição V3.0

Popula campos críticos para qualidade de dados em `subscribers`:
  - phone           ← subscriber_phones.normalized_number (primary first)
  - whatsapp        ← phone normalizado + is_whatsapp não-false
  - pppoe_user      ← subscriber_access_points.pppoe_user (primary first)
  - atlaz_phone     ← atlaz_clients_cache.phone (fallback)

Idempotente. Reporta delta antes/depois.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "vendas-team",
    "domain": "comercial",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


COMPANY_ID = "co-demo"


def normalize_phone(raw):
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None
    if len(digits) in (10, 11):
        digits = "55" + digits
    if len(digits) < 12 or len(digits) > 13:
        return None
    return digits


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def main():
    from database import db

    print("=" * 78)
    print("BACKFILL — subscribers.phone / whatsapp / pppoe_user")
    print("=" * 78)

    # ---- Métricas antes ----
    total = await db.subscribers.count_documents({"company_id": COMPANY_ID})
    before = {
        "phone": await db.subscribers.count_documents(
            {"company_id": COMPANY_ID, "phone": {"$nin": [None, ""]}}),
        "whatsapp": await db.subscribers.count_documents(
            {"company_id": COMPANY_ID, "whatsapp": {"$nin": [None, ""]}}),
        "pppoe_user": await db.subscribers.count_documents(
            {"company_id": COMPANY_ID, "pppoe_user": {"$nin": [None, ""]}}),
    }
    print(f"\n[antes] Total subs: {total}")
    for k, v in before.items():
        print(f"   {k}: {v} ({v/total*100:.1f}%)")

    # ---- 1. PHONE / WHATSAPP via subscriber_phones ----
    phones = await db.subscriber_phones.find(
        {"company_id": COMPANY_ID}
    ).to_list(None)
    phones_by_sub: dict[str, list] = defaultdict(list)
    for p in phones:
        phones_by_sub[p["subscriber_id"]].append(p)

    updated_phone = 0
    updated_wa = 0
    for sub_id, plist in phones_by_sub.items():
        # ordenação: primary primeiro, depois is_whatsapp=True
        plist.sort(key=lambda p: (
            not bool(p.get("is_primary")),
            p.get("is_whatsapp") is not True,
        ))
        canonical = None
        wa = None
        for p in plist:
            norm = normalize_phone(
                p.get("normalized_number") or p.get("raw_number"))
            if not norm:
                continue
            if not canonical:
                canonical = norm
            if p.get("is_whatsapp") is not False:
                # is_whatsapp=True ou None → consideramos WhatsApp-capaz
                if not wa:
                    wa = norm
        # fallback: atlaz cache
        update = {}
        if canonical:
            update["phone"] = canonical
            updated_phone += 1
        if wa:
            update["whatsapp"] = wa
            updated_wa += 1
        if update:
            await db.subscribers.update_one(
                {"id": sub_id, "company_id": COMPANY_ID},
                {"$set": {**update, "phone_backfilled_at": _iso()}},
            )

    # ---- 1b. Fallback PHONE via atlaz_clients_cache ----
    # Para subs sem phone após sub_phones, tenta external_code → atlaz
    no_phone_subs = await db.subscribers.find(
        {"company_id": COMPANY_ID,
         "phone": {"$in": [None, ""]},
         "external_code": {"$ne": None}},
    ).to_list(None)
    if no_phone_subs:
        ext_codes = [s.get("external_code") for s in no_phone_subs]
        atlaz = await db.atlaz_clients_cache.find(
            {"company_id": COMPANY_ID, "external_id": {"$in": ext_codes}}
        ).to_list(None)
        atlaz_by_ext = {a["external_id"]: a for a in atlaz}
        atlaz_fallback = 0
        for s in no_phone_subs:
            a = atlaz_by_ext.get(s.get("external_code"))
            if not a:
                continue
            ph = normalize_phone(a.get("phone"))
            if not ph:
                continue
            await db.subscribers.update_one(
                {"id": s["id"], "company_id": COMPANY_ID},
                {"$set": {"phone": ph, "whatsapp": ph,
                           "phone_backfilled_at": _iso(),
                           "phone_source": "atlaz_cache"}},
            )
            atlaz_fallback += 1
        print(f"\n[atlaz fallback] +{atlaz_fallback} phones recuperados via cache.")

    # ---- 2. PPPOE_USER via subscriber_access_points ----
    saps = await db.subscriber_access_points.find(
        {"company_id": COMPANY_ID, "pppoe_user": {"$ne": None}}
    ).to_list(None)
    saps_by_sub: dict[str, list] = defaultdict(list)
    for s in saps:
        saps_by_sub[s["subscriber_id"]].append(s)

    updated_pppoe = 0
    for sub_id, slist in saps_by_sub.items():
        # primeira pppoe (poderia priorizar status="Ativo")
        slist.sort(key=lambda s: 0 if (s.get("status") or "").lower() == "ativo" else 1)
        pppoe = slist[0].get("pppoe_user")
        if not pppoe:
            continue
        await db.subscribers.update_one(
            {"id": sub_id, "company_id": COMPANY_ID,
             "pppoe_user": {"$in": [None, ""]}},
            {"$set": {"pppoe_user": pppoe,
                       "pppoe_backfilled_at": _iso()}},
        )
        updated_pppoe += 1

    # ---- Métricas depois ----
    after = {
        "phone": await db.subscribers.count_documents(
            {"company_id": COMPANY_ID, "phone": {"$nin": [None, ""]}}),
        "whatsapp": await db.subscribers.count_documents(
            {"company_id": COMPANY_ID, "whatsapp": {"$nin": [None, ""]}}),
        "pppoe_user": await db.subscribers.count_documents(
            {"company_id": COMPANY_ID, "pppoe_user": {"$nin": [None, ""]}}),
    }
    print(f"\n[depois] subs totais: {total}")
    for k in ["phone", "whatsapp", "pppoe_user"]:
        delta = after[k] - before[k]
        pct_b = before[k]/total*100
        pct_a = after[k]/total*100
        print(f"   {k}: {after[k]:>5} ({pct_a:>5.1f}%) "
              f"[antes {before[k]} ({pct_b:.1f}%), Δ +{delta}]")


if __name__ == "__main__":
    asyncio.run(main())
