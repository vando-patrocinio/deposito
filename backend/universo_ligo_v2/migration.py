"""
Migração FASE A → FASE B do Universo Ligo V2.

REGRAS DESTE SCRIPT:
- Idempotente: rodar 2x produz o mesmo estado final.
- Reversível: toda operação registra em `universo_ligo_migration_log`.
- Dry-run por padrão (DRY_RUN=true). Só persiste quando explicitamente liberado.
- Zero perda de dado: campos legacy são PRESERVADOS (`level_key_legacy`).

USO:
    python -m backend.universo_ligo_v2.migration --dry-run     # default
    python -m backend.universo_ligo_v2.migration --apply       # executa de verdade
    python -m backend.universo_ligo_v2.migration --rollback    # desfaz última corrida
"""
from __future__ import annotations
import asyncio, os, secrets, argparse, json
from typing import Dict, Any, List, Tuple
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

from backend.universo_ligo_v2.levels_seed import (
    build_levels_seed, LEGACY_TO_V2_KEY, V2_TO_LEGACY_KEY, get_level_by_score,
)
from backend.universo_ligo_v2.models import (
    NEW_FIELDS_IN_SCORES, NEW_FIELDS_IN_SUBSCRIBERS, utcnow_iso,
)

# ────────────────────────────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────────────────────────────
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME   = os.environ["DB_NAME"]


def _new_op_id() -> str:
    return f"ulml-{secrets.token_hex(7)}"


def _new_ref_code(name: str | None, sub_id: str) -> str:
    """Gera code curto, idempotente quando possível."""
    base = (name or sub_id).strip().upper().split()[0][:4] if (name or sub_id) else "LIGO"
    base = "".join(c for c in base if c.isalnum()) or "LIGO"
    return f"{base}{secrets.token_hex(2).upper()}"


async def log_op(db, *, op: str, before: dict, after: dict, sub_id: str | None,
                 dry_run: bool) -> str:
    op_id = _new_op_id()
    doc = {
        "id": op_id, "phase": "A", "operation": op,
        "subscriber_id": sub_id,
        "before": before, "after": after,
        "executed_by": "migration_script",
        "executed_at": utcnow_iso(),
        "status": "dry_run" if dry_run else "applied",
        "dry_run": dry_run,
    }
    if not dry_run:
        await db.universo_ligo_migration_log.insert_one(doc)
    return op_id


# ────────────────────────────────────────────────────────────────────────
# ETAPA A.1 — Seed dos 6 níveis (universo_ligo_levels)
# ────────────────────────────────────────────────────────────────────────
async def seed_levels(db, dry_run: bool = True) -> Dict[str, Any]:
    levels = build_levels_seed()
    summary = {"inserted": 0, "updated": 0, "unchanged": 0, "errors": []}
    for lvl in levels:
        key = lvl["key"]
        existing = await db.universo_ligo_levels.find_one({"key": key})
        new_doc = {**lvl, "_seed_version": 1, "_seeded_at": utcnow_iso()}
        if existing is None:
            if not dry_run:
                await db.universo_ligo_levels.insert_one(new_doc)
            await log_op(db, op="seed_level", before={}, after=new_doc,
                         sub_id=None, dry_run=dry_run)
            summary["inserted"] += 1
        else:
            existing_clean = {k: v for k, v in existing.items() if k not in
                              ("_id", "_seed_version", "_seeded_at")}
            new_clean = {k: v for k, v in new_doc.items() if k not in
                         ("_seed_version", "_seeded_at")}
            if existing_clean == new_clean:
                summary["unchanged"] += 1
            else:
                if not dry_run:
                    await db.universo_ligo_levels.update_one(
                        {"key": key}, {"$set": new_doc})
                await log_op(db, op="update_level", before=existing_clean,
                             after=new_clean, sub_id=None, dry_run=dry_run)
                summary["updated"] += 1
    return summary


# ────────────────────────────────────────────────────────────────────────
# ETAPA A.2 — Adicionar índices não-disruptivos
# ────────────────────────────────────────────────────────────────────────
async def ensure_indexes(db, dry_run: bool = True) -> Dict[str, Any]:
    summary = {"created": [], "skipped": []}
    plans = [
        ("universo_ligo_levels", [("key", 1)], {"unique": True}),
        ("universo_ligo_scores", [("subscriber_id", 1)], {"unique": False}),
        ("universo_ligo_scores", [("company_id", 1), ("level_key_v2", 1)], {}),
        ("subscribers", [("referral_code", 1)],
            {"unique": True, "partialFilterExpression":
             {"referral_code": {"$type": "string"}}}),
        ("subscribers", [("universo_level_key", 1)], {"sparse": True}),
        ("universo_ligo_milestones", [("subscriber_id", 1), ("milestone_type", 1)], {}),
        ("universo_ligo_milestones", [("celebrated_at", 1)], {"sparse": True}),
        ("universo_ligo_tree_index", [("subscriber_id", 1)], {"unique": True}),
        ("universo_ligo_benefit_grants", [("subscriber_id", 1), ("status", 1)], {}),
        ("universo_ligo_migration_log", [("executed_at", -1)], {}),
    ]
    for coll, idx, opts in plans:
        try:
            if not dry_run:
                await db[coll].create_index(idx, **opts)
            summary["created"].append(f"{coll}.{idx}")
        except Exception as e:
            summary["skipped"].append(f"{coll}.{idx} (motivo: {e})")
    return summary


# ────────────────────────────────────────────────────────────────────────
# ETAPA A.3 — Renomear nível em scores existentes (legacy → V2)
# ────────────────────────────────────────────────────────────────────────
async def rename_legacy_levels(db, dry_run: bool = True) -> Dict[str, Any]:
    """Para cada doc em universo_ligo_scores: preserva level_key/level_name legacy
    e popula level_key_v2 / level_name_v2 conforme LEGACY_TO_V2_KEY.
    Idempotente: se já tiver level_key_v2 com mesmo valor esperado, não toca.
    """
    seed = {l["key"]: l for l in build_levels_seed()}
    summary = {"migrated": 0, "already_v2": 0, "errors": [],
               "by_target": {k: 0 for k in seed.keys()}}

    async for doc in db.universo_ligo_scores.find({}):
        legacy_key = doc.get("level_key") or "explorador"
        legacy_name = doc.get("level_name") or "Explorador"
        target_v2_key = LEGACY_TO_V2_KEY.get(legacy_key, legacy_key)
        target_seed = seed.get(target_v2_key)
        if target_seed is None:
            summary["errors"].append(f"sub={doc.get('subscriber_id')} legacy={legacy_key}: sem mapping")
            continue
        target_v2_name = target_seed["name"]
        already_v2 = doc.get("level_key_v2") == target_v2_key
        if already_v2:
            summary["already_v2"] += 1
            summary["by_target"][target_v2_key] += 1
            continue
        update = {
            "level_key_legacy": legacy_key,
            "level_name_legacy": legacy_name,
            "level_key_v2": target_v2_key,
            "level_name_v2": target_v2_name,
            "v2_migrated_at": utcnow_iso(),
            "v2_schema_version": 2,
        }
        if not dry_run:
            await db.universo_ligo_scores.update_one(
                {"_id": doc["_id"]}, {"$set": update})
        await log_op(db, op="rename_legacy_level",
                     before={"level_key": legacy_key, "level_name": legacy_name},
                     after=update, sub_id=doc.get("subscriber_id"),
                     dry_run=dry_run)
        summary["migrated"] += 1
        summary["by_target"][target_v2_key] += 1
    return summary


# ────────────────────────────────────────────────────────────────────────
# ETAPA A.4 — Backfill: campos novos em subscribers (referral_code + null fields)
# ────────────────────────────────────────────────────────────────────────
async def backfill_subscribers(db, dry_run: bool = True,
                                limit: int | None = None) -> Dict[str, Any]:
    """Adiciona campos novos em todos os subscribers ATIVOS.

    Idempotente: só popula campos AINDA não existentes.
    Default: gera apenas referral_code (único). Outros ficam None.
    """
    summary = {"processed": 0, "ref_code_generated": 0, "ref_code_existing": 0,
               "skipped_no_id": 0}
    query = {"$or": [
        {"cancellation_date": None},
        {"cancellation_date": {"$exists": False}},
    ]}
    cursor = db.subscribers.find(query, {"id": 1, "name": 1, "referral_code": 1})
    if limit:
        cursor = cursor.limit(limit)

    used_codes = set()
    # carrega códigos já existentes pra garantir unicidade
    async for d in db.subscribers.find(
            {"referral_code": {"$type": "string"}}, {"referral_code": 1}):
        used_codes.add(d.get("referral_code"))

    async for sub in cursor:
        sid = sub.get("id")
        if not sid:
            summary["skipped_no_id"] += 1
            continue
        update = {}
        if not sub.get("referral_code"):
            for _ in range(5):
                code = _new_ref_code(sub.get("name"), sid)
                if code not in used_codes:
                    used_codes.add(code)
                    update["referral_code"] = code
                    break
            if "referral_code" in update:
                summary["ref_code_generated"] += 1
        else:
            summary["ref_code_existing"] += 1
        for f, default in NEW_FIELDS_IN_SUBSCRIBERS.items():
            if f not in sub and f != "referral_code":
                update[f] = default
        update["universo_v2_backfilled_at"] = utcnow_iso()
        if update and not dry_run:
            await db.subscribers.update_one({"_id": sub["_id"]}, {"$set": update})
        if update:
            await log_op(db, op="backfill_subscriber",
                         before={"referral_code": sub.get("referral_code")},
                         after={"referral_code": update.get("referral_code", sub.get("referral_code"))},
                         sub_id=sid, dry_run=dry_run)
        summary["processed"] += 1
    return summary


# ────────────────────────────────────────────────────────────────────────
# ETAPA A.5 — Simulação de distribuição (somente leitura — SEMPRE roda)
# ────────────────────────────────────────────────────────────────────────
async def simulate_distribution(db) -> Dict[str, Any]:
    """Lê o estado atual e produz a distribuição PREVISTA pós-migração V2."""
    seed_keys = [l["key"] for l in build_levels_seed()]
    distrib_v2 = {k: 0 for k in seed_keys}
    distrib_legacy = {}
    avg_score_by_v2 = {k: [] for k in seed_keys}

    async for doc in db.universo_ligo_scores.find({}):
        legacy = doc.get("level_key") or "explorador"
        distrib_legacy[legacy] = distrib_legacy.get(legacy, 0) + 1
        v2 = LEGACY_TO_V2_KEY.get(legacy, legacy)
        if v2 in distrib_v2:
            distrib_v2[v2] += 1
            avg_score_by_v2[v2].append(doc.get("score", 0))

    avg_score_by_v2_final = {
        k: (sum(v) / len(v) if v else None) for k, v in avg_score_by_v2.items()
    }
    total_scored = sum(distrib_v2.values())
    total_subs = await db.subscribers.count_documents({})
    active_subs = await db.subscribers.count_documents(
        {"$or": [{"cancellation_date": None}, {"cancellation_date": {"$exists": False}}]})
    backfill_pending = active_subs - total_scored

    return {
        "total_subscribers": total_subs,
        "active_subscribers": active_subs,
        "currently_scored": total_scored,
        "currently_scored_pct": round(100.0 * total_scored / max(active_subs, 1), 2),
        "backfill_pending": backfill_pending,
        "distribution_legacy": distrib_legacy,
        "distribution_v2_predicted": distrib_v2,
        "avg_score_by_v2_predicted": avg_score_by_v2_final,
    }


# ────────────────────────────────────────────────────────────────────────
# ROLLBACK
# ────────────────────────────────────────────────────────────────────────
async def rollback_last_run(db, dry_run: bool = True) -> Dict[str, Any]:
    """Reverte a última migração Phase A.

    Estratégia: lê o log, encontra operações `applied` mais recentes, inverte.
    """
    summary = {"reverted": 0, "errors": []}
    cursor = db.universo_ligo_migration_log.find(
        {"phase": "A", "status": "applied"}
    ).sort("executed_at", -1)

    async for op in cursor:
        try:
            sid = op.get("subscriber_id")
            if op["operation"] == "rename_legacy_level":
                before = op.get("before", {})
                if sid:
                    if not dry_run:
                        await db.universo_ligo_scores.update_one(
                            {"subscriber_id": sid},
                            {"$set": before,
                             "$unset": {"level_key_v2": "", "level_name_v2": "",
                                        "level_key_legacy": "", "level_name_legacy": "",
                                        "v2_migrated_at": "", "v2_schema_version": ""}})
                    summary["reverted"] += 1
            elif op["operation"] == "backfill_subscriber":
                if sid:
                    if not dry_run:
                        await db.subscribers.update_one(
                            {"id": sid},
                            {"$unset": {f: "" for f in NEW_FIELDS_IN_SUBSCRIBERS}})
                    summary["reverted"] += 1
            elif op["operation"] in ("seed_level", "update_level"):
                key = (op.get("after") or {}).get("key")
                if key and not dry_run:
                    await db.universo_ligo_levels.delete_one({"key": key})
                summary["reverted"] += 1
            if not dry_run:
                await db.universo_ligo_migration_log.update_one(
                    {"_id": op["_id"]}, {"$set": {"status": "rolled_back"}})
        except Exception as e:
            summary["errors"].append(f"{op.get('id')}: {e}")
    return summary


# ────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────
async def main_async(mode: str, scope: str) -> Dict[str, Any]:
    cli = AsyncIOMotorClient(MONGO_URL)
    db = cli[DB_NAME]
    dry_run = mode == "dry-run"
    report: Dict[str, Any] = {"mode": mode, "scope": scope, "started_at": utcnow_iso()}

    if scope in ("all", "simulate"):
        report["simulation"] = await simulate_distribution(db)
    if scope in ("all", "seed"):
        report["seed_levels"] = await seed_levels(db, dry_run=dry_run)
    if scope in ("all", "indexes"):
        report["ensure_indexes"] = await ensure_indexes(db, dry_run=dry_run)
    if scope in ("all", "rename"):
        report["rename_legacy"] = await rename_legacy_levels(db, dry_run=dry_run)
    if scope in ("all", "backfill"):
        report["backfill_subscribers"] = await backfill_subscribers(
            db, dry_run=dry_run, limit=None)
    if mode == "rollback":
        report["rollback"] = await rollback_last_run(db, dry_run=dry_run)

    report["finished_at"] = utcnow_iso()
    return report


def cli_entry():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--scope", default="all",
                    choices=["all", "simulate", "seed", "indexes", "rename", "backfill"])
    args = ap.parse_args()
    if args.rollback:
        mode = "rollback"
    elif args.apply:
        mode = "apply"
    else:
        mode = "dry-run"
    out = asyncio.run(main_async(mode, args.scope))
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    cli_entry()
