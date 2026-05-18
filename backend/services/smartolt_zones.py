"""Sync inverso Rede_IA → SmartOLT — gerenciamento de Zones.

A API SmartOLT permite apenas:
  GET  /system/get_zones   → listar
  POST /system/add_zone    → criar (multipart form: zone=NOME)

Não há PUT/PATCH/DELETE público para zones na coleção oficial.

Estratégia:
- Idempotência por nome (case-insensitive + trim)
- Cache local em `smartolt_zones_cache` com TTL curto
- Log de operações em `smartolt_zone_audit`
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from database import db
from core import now_iso

logger = logging.getLogger(__name__)

_ZONES_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL_SEC = 60  # 1 minuto


async def _get_cfg(company_id: str) -> Optional[Dict[str, Any]]:
    return await db.smartolt_config.find_one({"company_id": company_id}, {"_id": 0})


def _base_url(cfg: Dict[str, Any]) -> str:
    return f"https://{(cfg.get('subdomain') or '').strip().lower()}.smartolt.com/api"


def _normalize_zone(name: str) -> str:
    """Normaliza nome para comparação (case-insensitive, sem espaços extras)."""
    return " ".join((name or "").strip().split()).upper()


async def list_zones(company_id: str, force_refresh: bool = False) -> List[Dict[str, Any]]:
    """GET /system/get_zones — com cache de 60s."""
    now = time.time()
    cached = _ZONES_CACHE.get(company_id)
    if not force_refresh and cached and (now - cached["ts"] < _CACHE_TTL_SEC):
        return cached["items"]

    cfg = await _get_cfg(company_id)
    if not cfg or not cfg.get("api_key") or not cfg.get("subdomain"):
        raise RuntimeError("SmartOLT não configurado")

    url = f"{_base_url(cfg)}/system/get_zones"
    timeout = cfg.get("timeout_seconds", 20)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url, headers={"X-Token": cfg["api_key"]})
        r.raise_for_status()
        data = r.json()

    items = data.get("response") or data.get("zones") or data.get("data") or []
    if not isinstance(items, list):
        items = []
    _ZONES_CACHE[company_id] = {"ts": now, "items": items}
    return items


async def reboot_onu(company_id: str, onu_sn: str) -> Dict[str, Any]:
    """Reinicia uma ONU via SmartOLT API (`POST /onu/reboot/{sn}`).

    Esse é o endpoint oficial da SmartOLT v2 — corresponde ao "Push" usado
    pelos técnicos de campo pra resolver lentidão sem precisar ir presencial.
    """
    cfg = await _get_cfg(company_id)
    if not cfg or not cfg.get("api_key") or not cfg.get("subdomain"):
        raise RuntimeError("SmartOLT não configurado")
    url = f"{_base_url(cfg)}/onu/reboot/{onu_sn}"
    timeout = cfg.get("timeout_seconds", 20)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, headers={"X-Token": cfg["api_key"]})
        r.raise_for_status()
        return r.json()


async def add_onu(company_id: str, *, board: str, port: str, sn: str,
                   zone_name: str, onu_type_id: Optional[str] = None,
                   pppoe_user: Optional[str] = None,
                   pppoe_password: Optional[str] = None,
                   vlan: Optional[int] = None) -> Dict[str, Any]:
    """Provisiona ONU nova no SmartOLT (`POST /onu/add_onu`).

    Campos obrigatórios SmartOLT v2:
      • board, port (da OLT) · sn (serial) · zone (= CTO)
      • onu_type_id (modelo — usa default "1" se não informado)
    """
    cfg = await _get_cfg(company_id)
    if not cfg or not cfg.get("api_key") or not cfg.get("subdomain"):
        raise RuntimeError("SmartOLT não configurado")
    payload: Dict[str, Any] = {
        "board": str(board),
        "port": str(port),
        "sn": sn,
        "zone": zone_name,
        "onu_type_id": str(onu_type_id or "1"),
    }
    if pppoe_user:
        payload["pppoe_user"] = pppoe_user
        payload["pppoe_password"] = pppoe_password or ""
    if vlan:
        payload["vlan"] = str(vlan)
    url = f"{_base_url(cfg)}/onu/add_onu"
    timeout = cfg.get("timeout_seconds", 20)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            url, headers={"X-Token": cfg["api_key"]}, data=payload,
        )
        r.raise_for_status()
        return r.json()


async def list_onu_types(company_id: str) -> List[Dict[str, Any]]:
    """GET /system/get_onu_types — usado pra autocomplete no form de cadastro."""
    cfg = await _get_cfg(company_id)
    if not cfg or not cfg.get("api_key") or not cfg.get("subdomain"):
        raise RuntimeError("SmartOLT não configurado")
    url = f"{_base_url(cfg)}/system/get_onu_types"
    timeout = cfg.get("timeout_seconds", 20)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url, headers={"X-Token": cfg["api_key"]})
        r.raise_for_status()
        data = r.json()
    items = data.get("response") or data.get("data") or data.get("types") or []
    return items if isinstance(items, list) else []


async def add_zone(company_id: str, zone_name: str) -> Dict[str, Any]:
    """POST /system/add_zone (multipart/form-data)."""
    cfg = await _get_cfg(company_id)
    if not cfg or not cfg.get("api_key") or not cfg.get("subdomain"):
        raise RuntimeError("SmartOLT não configurado")
    url = f"{_base_url(cfg)}/system/add_zone"
    timeout = cfg.get("timeout_seconds", 20)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            url,
            headers={"X-Token": cfg["api_key"]},
            data={"zone": zone_name},  # httpx converte automaticamente em form-urlencoded
        )
        r.raise_for_status()
        return r.json()


def _zone_exists(name: str, zones: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Busca case-insensitive no array de zones."""
    target = _normalize_zone(name)
    for z in zones:
        # SmartOLT pode devolver objetos {id, name} ou apenas strings
        zname = z if isinstance(z, str) else (
            z.get("name") or z.get("zone") or z.get("zone_name") or "")
        if _normalize_zone(zname) == target:
            return z if isinstance(z, dict) else {"name": z}
    return None


async def _audit(company_id: str, action: str, zone_name: str,
                  result: str, detail: str = "") -> None:
    try:
        await db.smartolt_zone_audit.insert_one({
            "company_id": company_id,
            "action": action,
            "zone_name": zone_name,
            "result": result,
            "detail": detail,
            "timestamp": now_iso(),
        })
    except Exception:
        pass


async def ensure_zone_exists(company_id: str, zone_name: str,
                               actor: str = "rede_IA") -> Dict[str, Any]:
    """Garante que a zone existe no SmartOLT — idempotente.

    Returns: {created: bool, zone: dict, message: str}
    """
    if not zone_name or not zone_name.strip():
        raise ValueError("zone_name é obrigatório")

    normalized = _normalize_zone(zone_name)
    try:
        zones = await list_zones(company_id, force_refresh=False)
        found = _zone_exists(normalized, zones)
        if found:
            await _audit(company_id, "ensure_zone", normalized, "already_exists",
                          f"actor={actor}")
            return {
                "created": False,
                "zone": found,
                "message": f"Zone '{normalized}' já existe no SmartOLT",
            }
        # Não existe → cria
        try:
            response = await add_zone(company_id, normalized)
        except httpx.HTTPStatusError as e:
            # Trata duplicidade race (alguém criou entre list e add)
            txt = (e.response.text or "")[:200]
            if e.response.status_code == 409 or "exist" in txt.lower():
                await _audit(company_id, "ensure_zone", normalized, "race_duplicate", txt)
                return {"created": False, "zone": {"name": normalized},
                        "message": "Já existia (race condition)"}
            raise

        # Invalida cache para próxima leitura ver o item novo
        _ZONES_CACHE.pop(company_id, None)
        await _audit(company_id, "ensure_zone", normalized, "created",
                      f"actor={actor}; smartolt_response={str(response)[:200]}")
        return {
            "created": True,
            "zone": {"name": normalized, "smartolt_response": response},
            "message": f"Zone '{normalized}' criada no SmartOLT",
        }
    except httpx.HTTPStatusError as e:
        await _audit(company_id, "ensure_zone", normalized, "http_error",
                      f"{e.response.status_code}: {e.response.text[:200]}")
        raise RuntimeError(
            f"SmartOLT HTTP {e.response.status_code}: {e.response.text[:120]}"
        )
    except httpx.RequestError as e:
        await _audit(company_id, "ensure_zone", normalized, "network_error", str(e)[:200])
        raise RuntimeError(f"Falha de rede SmartOLT: {str(e)[:120]}")
    except Exception as e:
        await _audit(company_id, "ensure_zone", normalized, "unexpected", str(e)[:200])
        raise
