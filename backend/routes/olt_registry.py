"""olt_registry.py — CRUD de OLTs V-SOL com SNMP via secrets_vault.

Cada OLT é um "perfil" no vault sob:
  integration:olt:profiles:{name}:host         IP/hostname
  integration:olt:profiles:{name}:port         (default 161)
  integration:olt:profiles:{name}:version      "v1" | "v2c"
  integration:olt:profiles:{name}:community    SNMP community (secret)
  integration:olt:profiles:{name}:vendor       "vsol" | "huawei" | "zte"
  integration:olt:profiles:{name}:enabled      "true" | "false"
  integration:olt:profiles:{name}:label        human-readable
"""
from __future__ import annotations
import re
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import require_role
from services import secrets_vault as vault
from services.vsol_snmp import VsolSnmpPoller

router = APIRouter(prefix="/api/admin/integrations/olt",
                    tags=["admin-integrations-olt"])

OLT_FIELDS = ("host", "port", "version", "community", "vendor",
               "enabled", "label")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def _actor(user):
    return (user.get("email") or user.get("user", {}).get("email")
            or "unknown_admin")


def _valid_name(name: str) -> str:
    name = (name or "").strip().lower()
    if not NAME_RE.match(name):
        raise HTTPException(400, "Nome inválido (use a-z 0-9 _ -)")
    return name


def _k(profile: str, field: str) -> str:
    return f"integration:olt:profiles:{profile}:{field}"


async def _list_profile_names() -> List[str]:
    from database import db
    out = set()
    async for d in db.secrets_vault.find(
            {"name": {"$regex": "^integration:olt:profiles:"}},
            {"name": 1}):
        parts = d["name"].split(":")
        if len(parts) >= 5:
            out.add(parts[3])
    return sorted(out)


class OltCreds(BaseModel):
    host: str
    port: Optional[int] = 161
    version: Optional[str] = "v2c"
    community: Optional[str] = "public"
    vendor: Optional[str] = "vsol"
    label: Optional[str] = ""


@router.get("/profiles")
async def list_profiles(user=Depends(require_role(
        "administrador", "auditor"))):
    names = await _list_profile_names()
    out = []
    for n in names:
        fields = {}
        for f in OLT_FIELDS:
            v = await vault.get_secret(_k(n, f), scope="global")
            mask = (v[:6] + "***") if v and f == "community" else v
            fields[f] = {"set": bool(v), "value": mask if f != "community"
                          else (mask if v else None)}
        enabled_raw = await vault.get_secret(_k(n, "enabled"),
                                                scope="global")
        out.append({
            "profile": n,
            "enabled": enabled_raw != "false",
            "configured": bool(fields["host"]["set"])
                           and bool(fields["community"]["set"]),
            "fields": fields,
        })
    return {"profiles": out, "enabled_count":
             sum(1 for p in out if p["enabled"])}


@router.post("/profiles/{name}/save")
async def save_profile(name: str, creds: OltCreds,
                        user=Depends(require_role("administrador"))):
    name = _valid_name(name)
    if not vault.is_available():
        raise HTTPException(500, "Vault indisponível")
    actor = _actor(user)
    saved = []
    payload = {
        "host": creds.host,
        "port": str(creds.port or 161),
        "version": creds.version or "v2c",
        "community": creds.community or "public",
        "vendor": (creds.vendor or "vsol").lower(),
        "label": creds.label or "",
    }
    for f, v in payload.items():
        if v != "":
            r = await vault.set_secret(
                name=_k(name, f), value=str(v), scope="global",
                updated_by=actor, hint=f"OLT {name} {f}")
            if r.get("ok"):
                saved.append(f)
    return {"ok": True, "profile": name, "saved_fields": saved}


@router.delete("/profiles/{name}")
async def delete_profile(name: str,
                          user=Depends(require_role("administrador"))):
    name = _valid_name(name)
    from database import db
    r = await db.secrets_vault.delete_many(
        {"name": {"$regex": f"^integration:olt:profiles:{re.escape(name)}:"}})
    return {"ok": True, "deleted_keys": r.deleted_count}


@router.post("/profiles/{name}/enable")
async def enable_profile(name: str,
                          user=Depends(require_role("administrador"))):
    name = _valid_name(name)
    await vault.set_secret(name=_k(name, "enabled"), value="true",
                            scope="global", updated_by=_actor(user),
                            hint=f"OLT {name} enabled")
    return {"ok": True, "enabled": True}


@router.post("/profiles/{name}/disable")
async def disable_profile(name: str,
                           user=Depends(require_role("administrador"))):
    name = _valid_name(name)
    await vault.set_secret(name=_k(name, "enabled"), value="false",
                            scope="global", updated_by=_actor(user),
                            hint=f"OLT {name} disabled")
    return {"ok": True, "enabled": False}


@router.get("/cached")
async def cached_discovery(user=Depends(require_role(
        "administrador", "auditor", "gestor"))):
    """Retorna último snapshot cacheado das OLTs (sem latência SNMP).

    Atualizado pelo scheduler a cada 5 minutos. Use este endpoint para
    UIs e dashboards que precisam de resposta instantânea."""
    from database import db
    all_onus = []
    summary = []
    async for doc in db.olt_snmp_cache.find({}):
        if doc.get("error"):
            summary.append({"profile": doc.get("profile"),
                             "error": doc.get("error"),
                             "polled_at": doc.get("polled_at")})
            continue
        for o in (doc.get("onus") or []):
            o2 = dict(o)
            o2["_olt"] = doc.get("profile")
            o2["_source"] = "olt_snmp_cache"
            all_onus.append(o2)
        summary.append({
            "profile": doc.get("profile"),
            "onu_count": doc.get("onu_count", 0),
            "polled_at": doc.get("polled_at"),
            "errors": doc.get("errors"),
        })
    return {"onu_count": len(all_onus), "onus": all_onus,
             "per_olt": summary,
             "source": "cache (atualizado a cada 5min)"}


@router.post("/poll-now")
async def force_poll(user=Depends(require_role("administrador",
                                                  "auditor"))):
    """Força polling imediato de todas OLTs habilitadas + atualiza cache."""
    from services.olt_polling_scheduler import poll_all_and_cache
    return await poll_all_and_cache()


async def _load_poller(profile: str) -> VsolSnmpPoller:
    host = await vault.get_secret(_k(profile, "host"), scope="global")
    port = await vault.get_secret(_k(profile, "port"), scope="global")
    version = await vault.get_secret(_k(profile, "version"), scope="global")
    comm = await vault.get_secret(_k(profile, "community"), scope="global")
    vendor = await vault.get_secret(_k(profile, "vendor"), scope="global")
    if not host or not comm:
        raise HTTPException(400,
            f"Perfil '{profile}' incompleto (host/community)")
    return VsolSnmpPoller(
        host=host, community=comm,
        port=int(port or 161),
        version=version or "v2c",
        vendor=vendor or "vsol",
    )


@router.post("/profiles/{name}/ping")
async def ping_profile(name: str,
                        user=Depends(require_role("administrador",
                                                    "auditor"))):
    name = _valid_name(name)
    poller = await _load_poller(name)
    return await poller.ping()


@router.post("/profiles/{name}/discover")
async def discover_profile(name: str,
                            user=Depends(require_role("administrador",
                                                        "auditor",
                                                        "gestor"))):
    """Discovery REAL via SNMP direto na OLT V-SOL."""
    name = _valid_name(name)
    poller = await _load_poller(name)
    res = await poller.discover_onus()
    res["profile"] = name
    return res


@router.post("/discover-all")
async def discover_all(user=Depends(require_role(
        "administrador", "auditor", "gestor"))):
    """Discovery em todas OLTs habilitadas em paralelo."""
    import asyncio as _asyncio
    names = await _list_profile_names()
    enabled = []
    for n in names:
        en = await vault.get_secret(_k(n, "enabled"), scope="global")
        if en != "false":
            enabled.append(n)
    if not enabled:
        return {"olts": 0, "onus": [], "onu_count": 0,
                "note": "Nenhuma OLT cadastrada"}

    async def _one(n):
        try:
            poller = await _load_poller(n)
            r = await poller.discover_onus()
            for o in (r.get("onus") or []):
                o["_olt"] = n
                o["_host"] = poller.host
            return r
        except Exception as e:
            return {"_error": repr(e)[:200], "profile": n}

    results = await _asyncio.gather(*[_one(n) for n in enabled],
                                       return_exceptions=True)
    all_onus: List[Dict[str, Any]] = []
    summary = []
    for n, r in zip(enabled, results):
        if isinstance(r, dict) and "_error" not in r:
            all_onus.extend(r.get("onus") or [])
            summary.append({"olt": n, "host": r.get("host"),
                            "onu_count": r.get("onu_count"),
                            "errors": r.get("errors")})
        else:
            summary.append({"olt": n,
                            "error": (r.get("_error")
                                       if isinstance(r, dict)
                                       else repr(r)[:200])})
    return {"olts": len(enabled), "onu_count": len(all_onus),
             "onus": all_onus, "per_olt": summary}
