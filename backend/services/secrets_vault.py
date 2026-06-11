"""secrets_vault.py — Vault simétrico para segredos (Fernet).

Resolve o gap de "segredos em texto plano" via cofre criptografado.
NÃO substitui o .env (mantido por compatibilidade); ADICIONA uma camada
para segredos NOVOS (CAUSALITY_PILOT_PHONES sensíveis, tokens de provedor
do piloto, chaves de revenda, etc.).

Operação:
  - MASTER_KEY (env var) = chave Fernet base64 (44 chars).
  - Segredos guardados criptografados em collection `secrets_vault`.
  - get(name) → descriptografa em runtime.
  - set(name, value, scope) → criptografa e persiste.

Geração da MASTER_KEY (uma vez, em setup):
  python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  → copiar para /app/backend/.env como SECRETS_MASTER_KEY=...
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "shield",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import os
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database import db

logger = logging.getLogger("secrets_vault")

COLLECTION = "secrets_vault"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_fernet():
    """Carrega Fernet com MASTER_KEY. Lazy import (cryptography é dep transitiva)."""
    key = os.environ.get("SECRETS_MASTER_KEY")
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:  # noqa: BLE001
        logger.error("[vault] falha ao inicializar Fernet: %r", e)
        return None


def is_available() -> bool:
    return _get_fernet() is not None


async def set_secret(name: str, value: str,
                     scope: str = "global",
                     updated_by: str = "system",
                     hint: str = "") -> Dict[str, Any]:
    """Criptografa e persiste segredo. Retorna metadados (sem o valor)."""
    f = _get_fernet()
    if not f:
        return {"ok": False, "error": "SECRETS_MASTER_KEY ausente"}
    if not name or not value:
        return {"ok": False, "error": "name e value obrigatórios"}
    enc = f.encrypt(value.encode()).decode()
    doc = {
        "name": name,
        "scope": scope,
        "ciphertext": enc,
        "hint": hint[:200],
        "updated_at": _now(),
        "updated_by": updated_by,
    }
    await db[COLLECTION].update_one(
        {"name": name, "scope": scope},
        {"$set": doc, "$inc": {"version": 1}},
        upsert=True)
    await db.audit_log.insert_one({
        "id": f"audit-{uuid.uuid4().hex[:12]}",
        "ts": _now(), "kind": "secret_set",
        "name": name, "scope": scope, "actor": updated_by})
    return {"ok": True, "name": name, "scope": scope,
            "updated_at": doc["updated_at"]}


async def get_secret(name: str, scope: str = "global",
                       *, accessed_by: str = "system",
                       purpose: Optional[str] = None) -> Optional[str]:
    """Descriptografa segredo. Retorna None se não existe ou Fernet ausente.
    Registra auditoria do acesso em `secrets_access_log`."""
    f = _get_fernet()
    if not f:
        return None
    doc = await db[COLLECTION].find_one({"name": name, "scope": scope})
    if not doc or not doc.get("ciphertext"):
        await db.secrets_access_log.insert_one({
            "id": f"sal-{uuid.uuid4().hex[:12]}",
            "ts": _now(), "name": name, "scope": scope,
            "accessed_by": accessed_by, "purpose": purpose,
            "result": "not_found"})
        return None
    try:
        plain = f.decrypt(doc["ciphertext"].encode()).decode()
        await db.secrets_access_log.insert_one({
            "id": f"sal-{uuid.uuid4().hex[:12]}",
            "ts": _now(), "name": name, "scope": scope,
            "accessed_by": accessed_by, "purpose": purpose,
            "version": doc.get("version", 1), "result": "ok"})
        return plain
    except Exception as e:  # noqa: BLE001
        logger.error("[vault] decrypt fail name=%s: %r", name, e)
        await db.secrets_access_log.insert_one({
            "id": f"sal-{uuid.uuid4().hex[:12]}",
            "ts": _now(), "name": name, "scope": scope,
            "accessed_by": accessed_by, "purpose": purpose,
            "result": "decrypt_error"})
        return None


async def access_log(name: Optional[str] = None, *,
                       limit: int = 100) -> Dict[str, Any]:
    q: Dict[str, Any] = {}
    if name:
        q["name"] = name
    items = await db.secrets_access_log.find(q, {"_id": 0}) \
        .sort("ts", -1).limit(min(limit, 500)) \
        .to_list(min(limit, 500))
    return {"count": len(items), "items": items}


async def rotate_secret(name: str, *, new_value: str,
                          scope: str = "global",
                          rotated_by: str = "system") -> Dict[str, Any]:
    """Rotaciona um segredo bumpando a versão e registrando audit."""
    f = _get_fernet()
    if not f:
        return {"ok": False, "reason": "vault_unavailable"}
    prev = await db[COLLECTION].find_one({"name": name, "scope": scope})
    old_version = (prev or {}).get("version", 0)
    ct = f.encrypt(new_value.encode()).decode()
    await db[COLLECTION].update_one(
        {"name": name, "scope": scope},
        {"$set": {"ciphertext": ct,
                   "version": old_version + 1,
                   "updated_at": _now(),
                   "updated_by": rotated_by}},
        upsert=True)
    await db.secrets_access_log.insert_one({
        "id": f"sal-{uuid.uuid4().hex[:12]}",
        "ts": _now(), "name": name, "scope": scope,
        "accessed_by": rotated_by, "purpose": "rotation",
        "result": "rotated",
        "from_version": old_version, "to_version": old_version + 1})
    return {"ok": True, "version": old_version + 1}


async def list_secrets(scope: Optional[str] = None) -> Dict[str, Any]:
    """Lista segredos (apenas metadados, NUNCA o valor)."""
    q: Dict[str, Any] = {}
    if scope:
        q["scope"] = scope
    items = []
    async for d in db[COLLECTION].find(q):
        items.append({
            "name": d.get("name"),
            "scope": d.get("scope"),
            "hint": d.get("hint"),
            "version": d.get("version", 1),
            "updated_at": d.get("updated_at"),
            "updated_by": d.get("updated_by"),
        })
    return {"count": len(items), "items": items, "vault_available": is_available()}


async def delete_secret(name: str, scope: str = "global",
                        deleted_by: str = "system") -> Dict[str, Any]:
    res = await db[COLLECTION].delete_one({"name": name, "scope": scope})
    await db.audit_log.insert_one({
        "id": f"audit-{uuid.uuid4().hex[:12]}",
        "ts": _now(), "kind": "secret_delete",
        "name": name, "scope": scope, "actor": deleted_by})
    return {"ok": res.deleted_count > 0, "name": name, "scope": scope}
