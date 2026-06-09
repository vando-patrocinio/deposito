"""admin_integrations.py — Cadastro seguro de credenciais externas.

P0.4 — Criado por ordem explícita do CTO (sprint Card Grafana/Zabbix).
- Credenciais persistidas via secrets_vault (Fernet AES-128 + HMAC).
- Apenas super_admin pode cadastrar.
- Botão "Testar conexão" valida ANTES de salvar.
- GET lista apenas metadados (NUNCA o valor).

Estrutura no vault:
  name="integration:grafana:url"       value=https://...
  name="integration:grafana:user"      value=ligotelecom
  name="integration:grafana:password"  value=***
  name="integration:grafana:org_id"    value=37
  name="integration:zabbix:url"        value=...
  name="integration:zabbix:user"       value=...
  name="integration:zabbix:password"   value=...
  name="integration:zabbix:api_token"  value=...
"""
from __future__ import annotations
import httpx
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from typing import Optional

from core import require_role
from services import secrets_vault as vault

router = APIRouter(prefix="/api/admin/integrations", tags=["admin-integrations"])

GRAFANA_FIELDS = ("url", "user", "password", "token", "org_id")
ZABBIX_FIELDS = ("url", "user", "password", "api_token")


def _actor(user):
    return (user.get("email") or user.get("user", {}).get("email")
            or "unknown_admin")


class GrafanaCreds(BaseModel):
    url: str
    user: Optional[str] = ""
    password: Optional[str] = ""
    token: Optional[str] = ""
    org_id: Optional[str] = ""


class ZabbixCreds(BaseModel):
    url: str
    user: Optional[str] = ""
    password: Optional[str] = ""
    api_token: Optional[str] = ""


# ─────────── GRAFANA ───────────
@router.get("/grafana/status")
async def grafana_status(user=Depends(require_role("administrador", "auditor"))):
    """Retorna metadados (presença) sem expor valores."""
    out = {"configured": False, "fields": {}, "vault_available": vault.is_available()}
    for f in GRAFANA_FIELDS:
        v = await vault.get_secret(f"integration:grafana:{f}", scope="global")
        out["fields"][f] = {"set": bool(v), "preview": (v[:6] + "...") if v and f == "url" else None}
    out["configured"] = bool(out["fields"]["url"]["set"]) and (
        bool(out["fields"]["token"]["set"]) or
        (bool(out["fields"]["user"]["set"]) and bool(out["fields"]["password"]["set"]))
    )
    return out


@router.post("/grafana/test")
async def grafana_test(creds: GrafanaCreds,
                       user=Depends(require_role("administrador"))):
    """Tenta conectar com as credenciais SEM persistir."""
    if not creds.url:
        raise HTTPException(400, "url obrigatório")
    headers = {"Accept": "application/json"}
    auth = None
    if creds.token:
        headers["Authorization"] = f"Bearer {creds.token}"
    elif creds.user and creds.password:
        auth = (creds.user, creds.password)
    else:
        raise HTTPException(400, "informe token OU user+password")
    if creds.org_id:
        headers["X-Grafana-Org-Id"] = creds.org_id
    url = creds.url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{url}/api/org", headers=headers, auth=auth)
            if r.status_code >= 400:
                return {"ok": False, "status": r.status_code,
                        "error": r.text[:200]}
            org = r.json()
            return {"ok": True, "org_name": org.get("name"),
                    "org_id": org.get("id"),
                    "auth_mode": "token" if creds.token else "basic"}
    except Exception as e:
        return {"ok": False, "error": repr(e)[:200]}


@router.post("/grafana/save")
async def grafana_save(creds: GrafanaCreds,
                       user=Depends(require_role("administrador"))):
    """Persiste no vault (criptografado). NÃO altera .env."""
    if not vault.is_available():
        raise HTTPException(500, "Vault indisponível — SECRETS_MASTER_KEY ausente no .env")
    actor = _actor(user)
    saved = []
    for f in GRAFANA_FIELDS:
        v = getattr(creds, f, "") or ""
        if v:
            r = await vault.set_secret(
                name=f"integration:grafana:{f}", value=v,
                scope="global", updated_by=actor,
                hint=f"Grafana {f}")
            if r.get("ok"):
                saved.append(f)
    return {"ok": True, "saved_fields": saved,
            "note": "Credenciais aplicadas imediatamente (vault tem prioridade sobre .env). Sem restart necessário."}


# ─────────── ZABBIX ───────────
@router.get("/zabbix/status")
async def zabbix_status(user=Depends(require_role("administrador", "auditor"))):
    out = {"configured": False, "fields": {}, "vault_available": vault.is_available()}
    for f in ZABBIX_FIELDS:
        v = await vault.get_secret(f"integration:zabbix:{f}", scope="global")
        out["fields"][f] = {"set": bool(v), "preview": (v[:6] + "...") if v and f == "url" else None}
    out["configured"] = bool(out["fields"]["url"]["set"]) and (
        bool(out["fields"]["api_token"]["set"]) or
        (bool(out["fields"]["user"]["set"]) and bool(out["fields"]["password"]["set"]))
    )
    return out


@router.post("/zabbix/test")
async def zabbix_test(creds: ZabbixCreds,
                      user=Depends(require_role("administrador"))):
    if not creds.url:
        raise HTTPException(400, "url obrigatório")
    url = creds.url.rstrip("/") + "/api_jsonrpc.php"
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            if creds.api_token:
                r = await cli.post(url, json={
                    "jsonrpc": "2.0", "method": "host.get",
                    "params": {"countOutput": True}, "id": 1,
                    "auth": creds.api_token})
            else:
                r = await cli.post(url, json={
                    "jsonrpc": "2.0", "method": "user.login",
                    "params": {"username": creds.user,
                               "password": creds.password},
                    "id": 1})
            d = r.json()
            if "error" in d:
                return {"ok": False, "error": d["error"]}
            return {"ok": True, "result": str(d.get("result"))[:50],
                    "auth_mode": "token" if creds.api_token else "basic"}
    except Exception as e:
        return {"ok": False, "error": repr(e)[:200]}


@router.post("/zabbix/save")
async def zabbix_save(creds: ZabbixCreds,
                      user=Depends(require_role("administrador"))):
    if not vault.is_available():
        raise HTTPException(500, "Vault indisponível — SECRETS_MASTER_KEY ausente no .env")
    actor = _actor(user)
    saved = []
    for f in ZABBIX_FIELDS:
        v = getattr(creds, f, "") or ""
        if v:
            r = await vault.set_secret(
                name=f"integration:zabbix:{f}", value=v,
                scope="global", updated_by=actor,
                hint=f"Zabbix {f}")
            if r.get("ok"):
                saved.append(f)
    return {"ok": True, "saved_fields": saved,
            "note": "Credenciais aplicadas imediatamente (vault tem prioridade sobre .env). Sem restart necessário."}
