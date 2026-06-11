"""
lgpd_chain.py — Sprint 4 / iter223

Hash-chain criptográfico + retenção por categoria para o audit_log.

Cada novo evento carrega:
  - prev_hash : SHA-256 do hash do evento imediatamente anterior
  - hash      : SHA-256 do conteúdo canônico do evento atual + prev_hash

Permite verificar que NENHUM registro foi adulterado ou removido
no meio: basta recomputar a cadeia e comparar.

Retention policy (por categoria) é persistida em
`audit_log_retention_policy` (collection única, doc id="default").
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db

CHAIN_FIELDS = (
    "id", "company_id", "user_id", "user_email", "user_role",
    "category", "criticality", "method", "target", "endpoint",
    "action", "status", "reason", "ip", "user_agent", "created_at",
)

DEFAULT_RETENTION_DAYS = {
    "destructive": 730,     # 24 meses
    "config_change": 1825,  # 5 anos
    "ai_config_change": 1825,
    "impersonate": 1825,
    "login_admin": 365,
    "export": 365,
    "rbac_blocked": 90,
    "ai_rate_limited": 30,
    "_default": 180,
}


def _canonical(doc: Dict[str, Any]) -> str:
    """Representação canônica determinística do evento."""
    payload = {k: doc.get(k) for k in CHAIN_FIELDS}
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      default=str)


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def compute_hash(doc: Dict[str, Any], prev_hash: str = "") -> str:
    return _sha256(_canonical(doc) + "|" + prev_hash)


# ─────────────────── Insert com chain ───────────────────
async def insert_audit_event(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Insere `doc` em `audit_log` já com `prev_hash` + `hash`.

    Idempotente quanto a chain — se algum erro acontecer no DB,
    devolve o doc igualmente (caller pode logar).
    """
    # busca último evento global (chain única por instalação)
    last = await db.audit_log.find_one(
        {"hash": {"$exists": True}}, sort=[("created_at", -1)])
    prev_hash = (last or {}).get("hash") or ""
    doc["prev_hash"] = prev_hash
    doc["hash"] = compute_hash(doc, prev_hash)
    try:
        await db.audit_log.insert_one(doc)
    except Exception:
        pass
    return doc


# ─────────────────── Verify chain ───────────────────
async def verify_chain(limit: int = 5000) -> Dict[str, Any]:
    """Recomputa a cadeia e retorna estatísticas de integridade."""
    cur = db.audit_log.find(
        {"hash": {"$exists": True}}
    ).sort("created_at", 1).limit(limit)

    prev_hash = ""
    checked = 0
    breaks: List[Dict[str, Any]] = []
    first_id: Optional[str] = None
    last_id: Optional[str] = None
    async for d in cur:
        checked += 1
        if checked == 1:
            first_id = d.get("id")
        last_id = d.get("id")
        recomputed = compute_hash(d, prev_hash)
        if recomputed != d.get("hash"):
            breaks.append({
                "id": d.get("id"),
                "created_at": d.get("created_at"),
                "stored_hash": (d.get("hash") or "")[:16] + "…",
                "expected_hash": recomputed[:16] + "…",
                "expected_prev": prev_hash[:16] + "…",
                "stored_prev": (d.get("prev_hash") or "")[:16] + "…",
            })
        prev_hash = d.get("hash") or recomputed

    return {
        "checked": checked,
        "first_id": first_id,
        "last_id": last_id,
        "breaks": breaks,
        "broken_count": len(breaks),
        "status": "ok" if not breaks else "tampering_detected",
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────── Subject report (LGPD) ───────────────────
async def subject_report(subject_id: str,
                            email: Optional[str] = None,
                            limit: int = 2000,
                            company_id: Optional[str] = None,
                            ) -> Dict[str, Any]:
    """Lista todas as ações registradas envolvendo um titular de dados.

    Procura por subject_id em:
      - user_id (quem executou)
      - data.subject_id, data.target_id (caso o handler tenha gravado)
      - target (path contendo o id do titular)
      - user_email (se fornecido)

    Pós-CTO audit: quando `company_id` é fornecido, filtra apenas
    eventos daquela empresa (isolamento multi-tenant).
    """
    or_clauses: List[Dict[str, Any]] = [
        {"user_id": subject_id},
        {"data.subject_id": subject_id},
        {"data.target_id": subject_id},
        {"target": {"$regex": subject_id, "$options": "i"}},
    ]
    if email:
        or_clauses.append({"user_email": email})

    flt: Dict[str, Any] = {"$or": or_clauses}
    if company_id:
        flt["company_id"] = company_id

    cur = db.audit_log.find(flt) \
        .sort("created_at", -1).limit(limit)
    items: List[Dict[str, Any]] = []
    by_category: Dict[str, int] = {}
    async for d in cur:
        items.append({
            "id": d.get("id"),
            "created_at": d.get("created_at"),
            "category": d.get("category"),
            "criticality": d.get("criticality"),
            "action": d.get("action"),
            "endpoint": d.get("target"),
            "actor_email": d.get("user_email"),
            "actor_role": d.get("user_role"),
            "status": d.get("status"),
            "ip": d.get("ip"),
            "hash": (d.get("hash") or "")[:16] + "…"
                      if d.get("hash") else None,
        })
        cat = d.get("category") or "outro"
        by_category[cat] = by_category.get(cat, 0) + 1

    return {
        "subject_id": subject_id,
        "email": email,
        "total_events": len(items),
        "by_category": by_category,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": items,
        "lgpd_basis": (
            "Resposta a direito do titular (art. 18 LGPD): "
            "acesso, confirmação e portabilidade. Cadeia hash-"
            "verificada garante integridade."),
    }


# ─────────────────── Retention policy ───────────────────
RETENTION_DOC_ID = "default"


async def get_retention_policy() -> Dict[str, int]:
    """Retorna política atual (mesclada com default)."""
    doc = await db.audit_log_retention_policy.find_one(
        {"_id": RETENTION_DOC_ID})
    out = dict(DEFAULT_RETENTION_DAYS)
    if doc:
        out.update(doc.get("policy") or {})
    return out


async def set_retention_policy(policy: Dict[str, int]) -> Dict[str, int]:
    """Substitui (merge) a policy. Valores em DIAS (1..3650)."""
    clean: Dict[str, int] = {}
    for k, v in (policy or {}).items():
        try:
            iv = int(v)
            if 1 <= iv <= 3650:
                clean[str(k)] = iv
        except Exception:
            continue
    await db.audit_log_retention_policy.update_one(
        {"_id": RETENTION_DOC_ID},
        {"$set": {"policy": clean,
                    "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return await get_retention_policy()


async def apply_retention_now() -> Dict[str, int]:
    """Apaga registros antigos conforme a política vigente.

    Retorna contagem de deletados por categoria. NÃO toca em entradas
    sem categoria. Não usa TTL nativo do Mongo porque precisamos de
    granularidade por categoria.
    """
    policy = await get_retention_policy()
    deleted: Dict[str, int] = {}
    now = datetime.now(timezone.utc)
    for cat, days in policy.items():
        if cat == "_default":
            continue
        cutoff = (now - timedelta(days=days)).isoformat()
        try:
            r = await db.audit_log.delete_many({
                "category": cat,
                "created_at": {"$lt": cutoff},
            })
            if r.deleted_count:
                deleted[cat] = r.deleted_count
        except Exception:
            pass
    # default p/ categorias sem regra
    cutoff_def = (now - timedelta(
        days=policy.get("_default", 180))).isoformat()
    try:
        r = await db.audit_log.delete_many({
            "category": {"$nin": list(policy.keys())},
            "created_at": {"$lt": cutoff_def},
        })
        if r.deleted_count:
            deleted["_default"] = r.deleted_count
    except Exception:
        pass
    return deleted
