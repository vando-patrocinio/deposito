"""IAM v2 — Migration script (DRAFT, NÃO EXECUTADO automaticamente).

Migra do schema legado (users + collaborators + access_profiles[v1] +
*_portal_users) para o canônico v2 (identities + credentials +
memberships + access_profiles[v2] + sessions).

⚠️  NÃO RODAR EM PRODUÇÃO sem:
  1. Backup completo MongoDB (mongodump → S3 com Object Lock).
  2. USE_NEW_IAM=0 em todos os pods (rollback rápido).
  3. Janela de manutenção formal (15-30min).
  4. Aprovação CTO/Founder por escrito.

Uso (manual):
  python3 -m iam_v2.migrate --phase dry-run --company co-demo
  python3 -m iam_v2.migrate --phase 1 --company co-demo
  ...

Fases (sequenciais, idempotentes):
  Phase 0: validate (lê tudo, não escreve, gera relatório)
  Phase 1: criar Identities a partir de `users`
  Phase 2: merge Collaborators em Identities (por CPF/email)
  Phase 3: criar Credentials (password do users.password_hash + magic_links)
  Phase 4: criar Memberships (1 per user.company_id)
  Phase 5: migrate portal users → Identity isolada (sem colab data)
  Phase 6: criar Sessions vazias (JWTs legados expiram naturalmente em 30d)
  Phase 7: verify (paridade, órfãos, unicidade)

Cada fase grava progresso em `db.iam_migration_log`:
    {phase, started_at, finished_at, stats: {...}, errors: [...]}
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("iam_v2.migrate")


# ──────────────────────────────────────────────────────────────────────────
# Sentinel: refuses to run if USE_NEW_IAM not explicitly set
# ──────────────────────────────────────────────────────────────────────────

def _safety_gate() -> None:
    import os
    if os.environ.get("IAM_MIGRATE_CONFIRMED") != "yes-i-understand-this-rewrites-auth":
        print(
            "\n❌ MIGRATION REFUSED: defina "
            "IAM_MIGRATE_CONFIRMED=yes-i-understand-this-rewrites-auth\n"
            "ANTES disso: faça backup completo MongoDB.\n",
            file=sys.stderr,
        )
        sys.exit(2)


# ──────────────────────────────────────────────────────────────────────────
# Phase 0: validate (dry-run, somente leitura)
# ──────────────────────────────────────────────────────────────────────────

async def phase_0_validate(db, company_id: str) -> dict[str, Any]:
    """Lê o estado atual e retorna relatório. Não escreve nada."""
    users_count = await db.users.count_documents({"company_id": company_id})
    collabs_count = await db.collaborators.count_documents({"company_id": company_id})
    profiles_count = await db.access_profiles.count_documents({"company_id": company_id})

    # Orphans: collab sem User
    orphan_collabs = 0
    async for c in db.collaborators.find(
        {"company_id": company_id},
        {"_id": 0, "id": 1, "email": 1, "mobile_access_email": 1},
    ):
        emails = [
            (c.get("email") or "").lower(),
            (c.get("mobile_access_email") or "").lower(),
        ]
        emails = [e for e in emails if e]
        u = await db.users.find_one({
            "company_id": company_id,
            "$or": [
                {"collaborator_id": c["id"]},
                {"email": {"$in": emails}},
            ],
        })
        if not u and emails:
            orphan_collabs += 1

    # Users com role mas sem profile_id
    no_profile = await db.users.count_documents({
        "company_id": company_id, "profile_id": {"$in": [None, ""]},
    })

    # Duplicates: mesmo email em coleções diferentes
    dup_emails: set[str] = set()
    portal_collections = [
        "client_portal_users", "fleet_portal_users",
        "parcerias_partner_users", "security_portal_users",
    ]
    for coll in portal_collections:
        if coll in await db.list_collection_names():
            async for d in db[coll].find({}, {"_id": 0, "email": 1}):
                e = (d.get("email") or "").lower()
                if e:
                    # checa se também existe em users
                    if await db.users.find_one({"email": e}):
                        dup_emails.add(e)

    return {
        "company_id": company_id,
        "users_count": users_count,
        "collaborators_count": collabs_count,
        "profiles_count": profiles_count,
        "orphan_collaborators": orphan_collabs,
        "users_without_profile": no_profile,
        "duplicated_emails_across_portals": len(dup_emails),
        "estimated_identities_to_create": users_count + orphan_collabs,
        "ready_to_migrate": orphan_collabs == 0 and len(dup_emails) < 5,
    }


# ──────────────────────────────────────────────────────────────────────────
# Phase 1: users → identities (placeholder)
# ──────────────────────────────────────────────────────────────────────────

async def phase_1_create_identities(db, company_id: str, dry_run: bool = False) -> dict:
    """Para cada `users` doc, cria `identities` doc 1:1.

    Idempotente: se já existe identity com mesmo email, pula.
    """
    created = 0
    skipped = 0
    errors: list[dict] = []
    async for u in db.users.find({"company_id": company_id}):
        email = (u.get("email") or "").strip().lower()
        if not email:
            errors.append({"user_id": u.get("id"), "reason": "no_email"})
            continue
        existing = await db.identities.find_one({"primary_email": email})
        if existing:
            skipped += 1
            continue
        doc = {
            "id": f"idt-{uuid.uuid4().hex[:10]}",
            "primary_email": email,
            "full_name": u.get("name") or u.get("email", "").split("@")[0],
            "cpf": None,  # users não tem CPF (vai vir do merge phase 2)
            "primary_phone": u.get("phone"),
            "status": "ativo" if u.get("active", True) else "bloqueado",
            "contacts": [],
            "membership_count": 1,  # vai criar 1 membership na phase 4
            "created_at": u.get("created_at") or datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_login_at": u.get("last_login_at"),
            "created_by": "migration_phase1",
            "_legacy_user_id": u["id"],  # rastreio
        }
        if not dry_run:
            await db.identities.insert_one(doc)
        created += 1

    return {"created": created, "skipped": skipped, "errors": errors[:10]}


# ──────────────────────────────────────────────────────────────────────────
# Phase 2: merge collaborators (CPF/email match)
# ──────────────────────────────────────────────────────────────────────────

async def phase_2_merge_collaborators(db, company_id: str, dry_run: bool = False) -> dict:
    merged = 0
    new_identities = 0
    not_matched = 0
    async for c in db.collaborators.find({"company_id": company_id}):
        emails = [(c.get("email") or "").lower(),
                  (c.get("mobile_access_email") or "").lower()]
        emails = [e for e in emails if e]
        cpf = (c.get("cpf") or "").strip()
        cpf_digits = "".join(ch for ch in cpf if ch.isdigit())
        cpf_digits = cpf_digits if len(cpf_digits) == 11 else None

        # Match strategy: CPF first, depois email
        identity = None
        if cpf_digits:
            identity = await db.identities.find_one({"cpf": cpf_digits})
        if not identity and emails:
            identity = await db.identities.find_one(
                {"primary_email": {"$in": emails}},
            )
        if identity:
            # Update existing identity with collab data (CPF, phone, foto)
            if not dry_run:
                await db.identities.update_one(
                    {"id": identity["id"]},
                    {"$set": {
                        "cpf": cpf_digits or identity.get("cpf"),
                        "full_name": c.get("name") or identity.get("full_name"),
                        "primary_phone": c.get("phone")
                            or identity.get("primary_phone"),
                        "avatar_url": c.get("avatar_data_url")
                            or identity.get("avatar_url"),
                        "_legacy_collaborator_id": c["id"],
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }},
                )
            merged += 1
        else:
            # Colab sem User vinculado → cria Identity nova
            if emails:
                new_doc = {
                    "id": f"idt-{uuid.uuid4().hex[:10]}",
                    "primary_email": emails[0],
                    "full_name": c.get("name") or "Sem nome",
                    "cpf": cpf_digits,
                    "primary_phone": c.get("phone"),
                    "avatar_url": c.get("avatar_data_url"),
                    "status": "ativo" if c.get("active", True) else "desligado",
                    "contacts": [],
                    "membership_count": 1,
                    "created_at": c.get("created_at")
                        or datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "_legacy_collaborator_id": c["id"],
                }
                if not dry_run:
                    await db.identities.insert_one(new_doc)
                new_identities += 1
            else:
                not_matched += 1

    return {
        "merged_into_existing": merged,
        "new_identities_from_collab": new_identities,
        "not_matched": not_matched,
    }


# ──────────────────────────────────────────────────────────────────────────
# Phases 3–7 (placeholders — implementar conforme schema dos ADRs)
# ──────────────────────────────────────────────────────────────────────────

async def phase_3_create_credentials(db, company_id: str, dry_run: bool = False) -> dict:
    """Cria 1 Credential(type=password) por user.password_hash + N por magic-links.

    DRY-RUN: simula contagens, **não escreve**.
    """
    pwd_planned = 0
    mlink_planned = 0
    google_planned = 0
    errors: list[dict] = []

    async for u in db.users.find({"company_id": company_id}):
        if u.get("password_hash"):
            pwd_planned += 1
        if u.get("google_id") or u.get("google_email"):
            google_planned += 1

    # Magic links ativos (não usados)
    mlink_planned = await db.user_magic_links.count_documents({
        "company_id": company_id, "used_at": None,
    })

    if dry_run:
        return {
            "phase": 3, "dry_run": True,
            "credentials_to_create": {
                "password": pwd_planned,
                "magic_link": mlink_planned,
                "google_oauth": google_planned,
            },
            "total": pwd_planned + mlink_planned + google_planned,
            "errors": errors,
            "note": "Nada escrito. Use --no-dry-run após aprovação CTO.",
        }
    return {"phase": 3, "todo": "Implementar escrita em ETAPA 2.5"}


async def phase_4_create_memberships(db, company_id: str, dry_run: bool = False) -> dict:
    """Cria 1 Membership por (Identity, company_id).

    DRY-RUN: simula mapping role legado → profile.
    """
    planned = 0
    profile_distribution: dict[str, int] = {}
    no_profile = 0

    async for u in db.users.find({"company_id": company_id}):
        role = u.get("role") or "colaborador"
        pid = u.get("profile_id")
        if not pid:
            # mapping role → profile (Phase 4 vai resolver)
            no_profile += 1
            target = f"<map de role={role}>"
        else:
            target = pid
        profile_distribution[target] = profile_distribution.get(target, 0) + 1
        planned += 1

    if dry_run:
        return {
            "phase": 4, "dry_run": True,
            "memberships_to_create": planned,
            "users_without_profile_id": no_profile,
            "profile_distribution": profile_distribution,
            "note": "Mapping role->profile aplicado nos sem-profile via LEGACY_ROLE_PERMISSIONS.",
        }
    return {"phase": 4, "todo": "Implementar escrita em ETAPA 2.5"}


async def phase_5_migrate_portals(db, company_id: str, dry_run: bool = False) -> dict:
    """Cada portal user vira Credential(type=portal_X) numa Identity (nova ou existente)."""
    summary: dict[str, dict[str, int]] = {}
    portals = [
        ("client_portal_users", "portal_client"),
        ("fleet_portal_users", "portal_fleet"),
        ("parcerias_partner_users", "portal_partner"),
        ("security_portal_users", "portal_security"),
    ]
    collections = await db.list_collection_names()
    for coll, cred_type in portals:
        if coll not in collections:
            continue
        total = 0
        will_merge = 0
        will_create = 0
        async for d in db[coll].find({}, {"_id": 0, "email": 1}):
            total += 1
            e = (d.get("email") or "").lower()
            if not e:
                continue
            staff = await db.users.find_one({"email": e})
            if staff:
                will_merge += 1
            else:
                will_create += 1
        summary[coll] = {
            "total": total,
            "will_merge_existing_identity": will_merge,
            "will_create_new_identity": will_create,
            "credential_type": cred_type,
        }
    # public_access_tokens → api_key credential
    pat = await db.public_access_tokens.count_documents({"revoked_at": None})
    summary["public_access_tokens_active"] = {
        "total": pat, "credential_type": "api_key",
        "note": "Cada token vira credential(type=api_key, scope=[...]).",
    }

    if dry_run:
        return {
            "phase": 5, "dry_run": True,
            "summary": summary,
            "note": "Decisão pendente: dedup por primary_email entre portais.",
        }
    return {"phase": 5, "todo": "Implementar em ETAPA 2.5"}


async def phase_6_init_sessions(db, company_id: str, dry_run: bool = False) -> dict:
    """Cria coleção `sessions` vazia + índices. JWTs legados expirarão em 30d."""
    indexes_planned = [
        {"key": "jwt_jti", "unique": True},
        {"key": "identity_id"},
        {"key": "expires_at", "expireAfterSeconds": 0},
        {"keys": [("revoked_at", 1), ("expires_at", 1)]},
    ]
    if dry_run:
        return {
            "phase": 6, "dry_run": True,
            "collection_to_create": "sessions",
            "indexes_planned": indexes_planned,
            "legacy_jwt_strategy": (
                "Aceitar JWT legado durante TTL natural (30d). "
                "Após cutover, novas autenticações geram Session + JWT com jti."
            ),
        }
    return {"phase": 6, "todo": "Implementar em ETAPA 2.5"}


async def phase_7_verify(db, company_id: str) -> dict:
    """Verifica paridade/unicidade pós-migração. Read-only."""
    users = await db.users.count_documents({"company_id": company_id})
    collabs = await db.collaborators.count_documents({"company_id": company_id})
    identities = await db.identities.count_documents({"_legacy_user_id": {"$exists": True}})
    creds = await db.credentials.count_documents({}) \
        if "credentials" in await db.list_collection_names() else 0
    memberships = await db.memberships.count_documents({"company_id": company_id}) \
        if "memberships" in await db.list_collection_names() else 0

    # Dupes/órfãos pós
    dup_emails = []
    if "identities" in await db.list_collection_names():
        pipeline = [
            {"$group": {"_id": "$primary_email", "n": {"$sum": 1}}},
            {"$match": {"n": {"$gt": 1}}},
        ]
        async for d in db.identities.aggregate(pipeline):
            dup_emails.append(d["_id"])

    orphan_identities = 0
    if "identities" in await db.list_collection_names():
        async for i in db.identities.find({}, {"id": 1}):
            if "memberships" in await db.list_collection_names():
                m = await db.memberships.find_one(
                    {"identity_id": i["id"], "status": "active"},
                )
                if not m:
                    orphan_identities += 1

    return {
        "phase": 7, "company_id": company_id,
        "counts": {
            "legacy_users": users,
            "legacy_collaborators": collabs,
            "new_identities_from_users": identities,
            "new_credentials": creds,
            "new_memberships": memberships,
        },
        "anomalies": {
            "duplicated_primary_emails": dup_emails,
            "identities_without_active_membership": orphan_identities,
        },
        "parity_ok": users == identities and orphan_identities == 0 and len(dup_emails) == 0,
    }


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────

PHASES = {
    "0": phase_0_validate,
    "1": phase_1_create_identities,
    "2": phase_2_merge_collaborators,
    "3": phase_3_create_credentials,
    "4": phase_4_create_memberships,
    "5": phase_5_migrate_portals,
    "6": phase_6_init_sessions,
    "7": phase_7_verify,
}


async def _main(args):
    from dotenv import load_dotenv
    load_dotenv()
    import os
    from motor.motor_asyncio import AsyncIOMotorClient
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ.get("DB_NAME", "test_database")]

    phase_fn = PHASES.get(args.phase)
    if not phase_fn:
        print(f"❌ Phase desconhecida: {args.phase}", file=sys.stderr)
        sys.exit(2)

    if args.phase != "0":
        _safety_gate()

    started = datetime.now(timezone.utc).isoformat()
    print(f"▶  Phase {args.phase} iniciada (dry-run={args.dry_run})...")
    try:
        if args.phase == "0":
            result = await phase_fn(db, args.company)
        elif args.phase == "7":
            result = await phase_fn(db, args.company)
        else:
            result = await phase_fn(db, args.company, dry_run=args.dry_run)
        finished = datetime.now(timezone.utc).isoformat()
        await db.iam_migration_log.insert_one({
            "id": f"mig-{uuid.uuid4().hex[:10]}",
            "phase": args.phase, "company_id": args.company,
            "dry_run": args.dry_run,
            "started_at": started, "finished_at": finished,
            "result": result,
        })
        print(f"✅ Phase {args.phase} concluída em {args.company}:")
        import json
        print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(f"❌ Phase {args.phase} falhou: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IAM v2 migration")
    parser.add_argument("--phase", required=True, choices=list(PHASES.keys()))
    parser.add_argument("--company", required=True, help="company_id")
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()
    asyncio.run(_main(args))
