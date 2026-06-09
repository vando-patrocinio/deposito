"""admin_integrations.py — Cadastro seguro de credenciais externas.

P0.4 — Criado por ordem explícita do CTO (sprint Card Grafana/Zabbix).
P0.5 — Estendido em 2026-06-09 para suportar MÚLTIPLOS PERFIS Grafana
       (segundo card com outra conta, alternância via "perfil ativo").

- Credenciais persistidas via secrets_vault (Fernet AES-128 + HMAC).
- Apenas super_admin pode cadastrar.
- Botão "Testar conexão" valida ANTES de salvar.
- GET lista apenas metadados (NUNCA o valor).

Estrutura no vault (multi-perfil):
  integration:grafana:profiles:{name}:url       value=https://...
  integration:grafana:profiles:{name}:user      value=...
  integration:grafana:profiles:{name}:password  value=***
  integration:grafana:profiles:{name}:token     value=***
  integration:grafana:profiles:{name}:org_id    value=...
  integration:grafana:active_profile             value={name}   # ponteiro
  integration:zabbix:url|user|password|api_token            # idem grafana (1 perfil por ora)

Back-compat: se `active_profile` ausente mas existem chaves antigas
(`integration:grafana:url`, etc), elas são migradas como perfil
"default" na primeira chamada de `_ensure_legacy_migrated`.
"""
from __future__ import annotations
import re
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from core import require_role
from services import secrets_vault as vault

router = APIRouter(prefix="/api/admin/integrations",
                    tags=["admin-integrations"])

GRAFANA_FIELDS = ("url", "user", "password", "token", "org_id", "enabled")
ZABBIX_FIELDS = ("url", "user", "password", "api_token")
PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def _actor(user):
    return (user.get("email") or user.get("user", {}).get("email")
            or "unknown_admin")


def _validate_profile(name: str) -> str:
    name = (name or "").strip().lower()
    if not PROFILE_NAME_RE.match(name):
        raise HTTPException(
            400, "Nome de perfil inválido. Use a-z, 0-9, _ ou -, "
                 "até 32 chars.")
    return name


def _gk(profile: str, field: str) -> str:
    return f"integration:grafana:profiles:{profile}:{field}"


async def _ensure_legacy_migrated():
    """Se existirem chaves antigas (sem profile) e nenhum perfil novo,
    migra para perfil 'default'. Idempotente."""
    if not vault.is_available():
        return
    active = await vault.get_secret(
        "integration:grafana:active_profile", scope="global")
    if active:
        return
    # Verifica se existe legado
    legacy_url = await vault.get_secret(
        "integration:grafana:url", scope="global")
    if not legacy_url:
        return
    for f in GRAFANA_FIELDS:
        v = await vault.get_secret(
            f"integration:grafana:{f}", scope="global")
        if v:
            await vault.set_secret(
                name=_gk("default", f), value=v, scope="global",
                updated_by="legacy-migration",
                hint=f"Grafana default {f}")
    await vault.set_secret(
        name="integration:grafana:active_profile", value="default",
        scope="global", updated_by="legacy-migration",
        hint="Perfil Grafana ativo")


async def _list_profiles() -> List[str]:
    """Lista nomes de perfis Grafana no vault.

    Usa db.secrets_vault.find diretamente (sem decifrar; só lê 'name')."""
    from database import db
    profiles = set()
    async for doc in db.secrets_vault.find(
            {"name": {"$regex": "^integration:grafana:profiles:"}},
            {"name": 1}):
        # name = "integration:grafana:profiles:{name}:{field}"
        parts = doc["name"].split(":")
        if len(parts) >= 5:
            profiles.add(parts[3])
    return sorted(profiles)


async def _get_active_profile() -> Optional[str]:
    return await vault.get_secret(
        "integration:grafana:active_profile", scope="global")


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


# ─────────── GRAFANA · MULTI-PERFIL ───────────
@router.get("/grafana/profiles")
async def grafana_profiles(user=Depends(require_role(
        "administrador", "auditor"))):
    """Lista todos os perfis Grafana cadastrados.
    Após P0.6: TODOS os perfis com `enabled=true` (default) rodam em
    paralelo. `active` (legado) ainda indica qual era o "principal".
    """
    await _ensure_legacy_migrated()
    profiles = await _list_profiles()
    active = await _get_active_profile()
    out: List[Dict[str, Any]] = []
    for p in profiles:
        fields = {}
        for f in ("url", "user", "password", "token", "org_id"):
            v = await vault.get_secret(_gk(p, f), scope="global")
            fields[f] = {
                "set": bool(v),
                "preview": (v[:18] + "...") if v and f == "url" else None,
            }
        # Enabled default = True; só False se explicitamente desabilitado
        enabled_raw = await vault.get_secret(
            _gk(p, "enabled"), scope="global")
        enabled = enabled_raw != "false"
        configured = bool(fields["url"]["set"]) and (
            bool(fields["token"]["set"])
            or (bool(fields["user"]["set"])
                and bool(fields["password"]["set"])))
        out.append({
            "profile": p,
            "active": (p == active),
            "enabled": enabled,
            "configured": configured,
            "fields": fields,
        })
    return {"profiles": out, "active": active,
             "enabled_count": sum(1 for x in out if x["enabled"]),
             "vault_available": vault.is_available()}


@router.post("/grafana/profiles/{profile}/save")
async def grafana_profile_save(profile: str, creds: GrafanaCreds,
                                user=Depends(require_role("administrador"))):
    """Cria ou atualiza um perfil. Se for o primeiro perfil cadastrado,
    vira ativo automaticamente."""
    if not vault.is_available():
        raise HTTPException(500,
            "Vault indisponível — SECRETS_MASTER_KEY ausente no .env")
    profile = _validate_profile(profile)
    actor = _actor(user)
    # Normaliza URL: remove sufixos /login, /admin, /sa que usuários
    # colam por engano (a URL canônica do Grafana é o domain root).
    if creds.url:
        u = creds.url.rstrip("/")
        for trail in ("/login", "/sa", "/admin", "/dashboards"):
            if u.lower().endswith(trail):
                u = u[:-len(trail)]
        creds.url = u.rstrip("/")
    saved = []
    for f in GRAFANA_FIELDS:
        v = getattr(creds, f, "") or ""
        if v:
            r = await vault.set_secret(
                name=_gk(profile, f), value=v, scope="global",
                updated_by=actor, hint=f"Grafana {profile} {f}")
            if r.get("ok"):
                saved.append(f)
    # Auto-ativa se for o primeiro
    if not await _get_active_profile():
        await vault.set_secret(
            name="integration:grafana:active_profile", value=profile,
            scope="global", updated_by=actor,
            hint="Perfil Grafana ativo")
    return {"ok": True, "profile": profile, "saved_fields": saved}


@router.post("/grafana/profiles/{profile}/enable")
async def grafana_profile_enable(profile: str,
                                  user=Depends(require_role("administrador"))):
    """Marca perfil como ativo no pool (será consultado em paralelo)."""
    profile = _validate_profile(profile)
    profiles = await _list_profiles()
    if profile not in profiles:
        raise HTTPException(404, f"Perfil '{profile}' não existe")
    await vault.set_secret(
        name=_gk(profile, "enabled"), value="true", scope="global",
        updated_by=_actor(user), hint=f"Grafana {profile} enabled")
    return {"ok": True, "profile": profile, "enabled": True}


@router.post("/grafana/profiles/{profile}/disable")
async def grafana_profile_disable(profile: str,
                                   user=Depends(require_role(
                                       "administrador"))):
    """Remove perfil do pool de consultas paralelas (mantém credenciais)."""
    profile = _validate_profile(profile)
    profiles = await _list_profiles()
    if profile not in profiles:
        raise HTTPException(404, f"Perfil '{profile}' não existe")
    await vault.set_secret(
        name=_gk(profile, "enabled"), value="false", scope="global",
        updated_by=_actor(user), hint=f"Grafana {profile} disabled")
    return {"ok": True, "profile": profile, "enabled": False}


@router.post("/grafana/profiles/{profile}/activate")
async def grafana_profile_activate(profile: str,
                                    user=Depends(require_role(
                                        "administrador"))):
    """Marca um perfil como ativo (é o que o GrafanaConnector usa)."""
    profile = _validate_profile(profile)
    profiles = await _list_profiles()
    if profile not in profiles:
        raise HTTPException(404, f"Perfil '{profile}' não existe")
    # Verifica se tem credenciais mínimas
    url = await vault.get_secret(_gk(profile, "url"), scope="global")
    if not url:
        raise HTTPException(400,
            f"Perfil '{profile}' não tem URL configurada")
    await vault.set_secret(
        name="integration:grafana:active_profile", value=profile,
        scope="global", updated_by=_actor(user),
        hint="Perfil Grafana ativo")
    return {"ok": True, "active": profile}


@router.delete("/grafana/profiles/{profile}")
async def grafana_profile_delete(profile: str,
                                  user=Depends(require_role("administrador"))):
    """Remove um perfil completo. Bloqueia se for o ativo (precisa ativar
    outro antes)."""
    profile = _validate_profile(profile)
    active = await _get_active_profile()
    if profile == active:
        raise HTTPException(
            400, "Não é possível excluir o perfil ativo. "
                 "Ative outro perfil antes.")
    from database import db
    n = await db.secrets_vault.delete_many({
        "name": {"$regex": f"^integration:grafana:profiles:{re.escape(profile)}:"}})
    return {"ok": True, "deleted_keys": n.deleted_count}


@router.post("/grafana/profiles/{profile}/test")
async def grafana_profile_test(profile: str, creds: GrafanaCreds,
                                user=Depends(require_role("administrador"))):
    """Testa credenciais antes de salvar (não persiste).
    Aceita {profile} mas só usa as credenciais do body."""
    _validate_profile(profile)
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


# ─────────── GRAFANA · LEGADO (back-compat com UI antiga) ───────────
@router.get("/grafana/status")
async def grafana_status(user=Depends(require_role(
        "administrador", "auditor"))):
    """Atalho — status do perfil ativo (legado)."""
    await _ensure_legacy_migrated()
    active = await _get_active_profile()
    out = {"configured": False, "fields": {},
           "vault_available": vault.is_available(),
           "active_profile": active}
    if not active:
        return out
    for f in GRAFANA_FIELDS:
        v = await vault.get_secret(_gk(active, f), scope="global")
        out["fields"][f] = {
            "set": bool(v),
            "preview": (v[:18] + "...") if v and f == "url" else None,
        }
    out["configured"] = bool(out["fields"]["url"]["set"]) and (
        bool(out["fields"]["token"]["set"])
        or (bool(out["fields"]["user"]["set"])
            and bool(out["fields"]["password"]["set"])))
    return out


@router.post("/grafana/test")
async def grafana_test(creds: GrafanaCreds,
                       user=Depends(require_role("administrador"))):
    """Atalho legado — equivalente a /grafana/profiles/default/test."""
    return await grafana_profile_test("default", creds, user)


@router.post("/grafana/save")
async def grafana_save(creds: GrafanaCreds,
                       user=Depends(require_role("administrador"))):
    """Atalho legado — salva no perfil 'default' E o torna ativo."""
    res = await grafana_profile_save("default", creds, user)
    # Garante que default fica ativo (compat sessão antiga)
    await vault.set_secret(
        name="integration:grafana:active_profile", value="default",
        scope="global", updated_by=_actor(user),
        hint="Perfil Grafana ativo")
    return {**res, "note": "Salvo no perfil 'default' (ativo)."}


# ─────────── ZABBIX ───────────
@router.get("/zabbix/status")
async def zabbix_status(user=Depends(require_role(
        "administrador", "auditor"))):
    out = {"configured": False, "fields": {},
           "vault_available": vault.is_available()}
    for f in ZABBIX_FIELDS:
        v = await vault.get_secret(
            f"integration:zabbix:{f}", scope="global")
        out["fields"][f] = {
            "set": bool(v),
            "preview": (v[:18] + "...") if v and f == "url" else None,
        }
    out["configured"] = bool(out["fields"]["url"]["set"]) and (
        bool(out["fields"]["api_token"]["set"])
        or (bool(out["fields"]["user"]["set"])
            and bool(out["fields"]["password"]["set"])))
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
        raise HTTPException(500,
            "Vault indisponível — SECRETS_MASTER_KEY ausente no .env")
    actor = _actor(user)
    saved = []
    for f in ZABBIX_FIELDS:
        v = getattr(creds, f, "") or ""
        if v:
            r = await vault.set_secret(
                name=f"integration:zabbix:{f}", value=v, scope="global",
                updated_by=actor, hint=f"Zabbix {f}")
            if r.get("ok"):
                saved.append(f)
    return {"ok": True, "saved_fields": saved,
            "note": "Credenciais aplicadas imediatamente."}
