"""Integração com SmartOLT — leitura de ONU/sinal por nome PPPoE.

Autenticação: header `X-Token` na URL `https://{subdomain}.smartolt.com/api/...`
Estratégia:
- Sync periódico de TODAS as ONUs para `db.smartolt_onus` (cache local).
- Lookup de bolha (Lousa) → casa pelo PPPoE (preferencial) ou nome do cliente
  (case-insensitive, sem acento, sem espaço).
- Endpoint live `signal/{external_id}` revalida em SmartOLT com TTL configurável.
"""
from __future__ import annotations

import asyncio
import logging
import time
import unicodedata
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger("ponto.smartolt")
router = APIRouter(prefix="/api/smartolt", tags=["smartolt"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class SmartoltConfig(BaseModel):
    company_id: str = DEMO_COMPANY_ID
    enabled: bool = False
    subdomain: str = ""           # ex.: "ligofibra"
    api_key: str = ""             # X-Token
    sync_interval_minutes: int = Field(default=360, ge=60, le=1440)  # 6h default, mín 1h
    signal_cache_seconds: int = Field(default=60, ge=10, le=3600)
    timeout_seconds: int = Field(default=20, ge=5, le=120)
    last_sync_at: Optional[str] = None
    last_sync_total: int = 0


class SmartoltConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    subdomain: Optional[str] = None
    api_key: Optional[str] = None
    sync_interval_minutes: Optional[int] = Field(default=None, ge=60, le=1440)
    signal_cache_seconds: Optional[int] = Field(default=None, ge=10, le=3600)
    timeout_seconds: Optional[int] = Field(default=None, ge=5, le=120)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _strip_accent(s: str) -> str:
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _norm(s: Any) -> str:
    """Normaliza para comparação: lower, sem acento, sem espaço/_/-."""
    if s is None:
        return ""
    out = _strip_accent(str(s)).lower()
    return "".join(ch for ch in out if ch.isalnum())


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}…{key[-4:]}"


async def _get_config(company_id: str) -> SmartoltConfig:
    raw = await db.smartolt_config.find_one({"company_id": company_id}, {"_id": 0})
    if not raw:
        cfg = SmartoltConfig(company_id=company_id)
        await db.smartolt_config.insert_one(cfg.model_dump())
        return cfg
    # Sanitiza campos fora de range (auto-heal)
    try:
        return SmartoltConfig(**raw)
    except Exception as e:
        logger.warning("[smartolt] config corrompida, recriando: %s", e)
        cfg = SmartoltConfig(company_id=company_id)
        await db.smartolt_config.update_one(
            {"company_id": company_id}, {"$set": cfg.model_dump()}, upsert=True,
        )
        return cfg


def _public(cfg: SmartoltConfig) -> dict:
    d = cfg.model_dump()
    d["api_key"] = _mask(d.get("api_key", ""))
    return d


def _base_url(cfg: SmartoltConfig) -> str:
    sub = (cfg.subdomain or "").strip().lower()
    return f"https://{sub}.smartolt.com/api"


async def _is_rate_limited(company_id: str) -> Optional[str]:
    """Retorna a string ISO `rate_limited_until` se a empresa ainda está
    bloqueada por rate-limit no SmartOLT. Caso contrário retorna None.
    """
    cfg = await db.smartolt_config.find_one({"company_id": company_id},
                                                  {"_id": 0, "rate_limited_until": 1})
    if not cfg:
        return None
    until = cfg.get("rate_limited_until")
    if not until:
        return None
    try:
        from datetime import datetime as _dt
        dt = _dt.fromisoformat(str(until).replace("Z", "+00:00"))
        if dt.timestamp() > time.time():
            return until
    except Exception:
        return None
    # Expirou — limpa
    await db.smartolt_config.update_one(
        {"company_id": company_id},
        {"$unset": {"rate_limited_until": 1}},
    )
    return None


async def _mark_rate_limited(company_id: str, seconds: int = 3600) -> None:
    """Marca a empresa como bloqueada por `seconds` segundos (default 1h).
    Usado quando SmartOLT responde 403 com rate_limit_exceeded.
    """
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    until = _dt.now(_tz.utc) + _td(seconds=seconds)
    await db.smartolt_config.update_one(
        {"company_id": company_id},
        {"$set": {"rate_limited_until": until.isoformat()}},
    )
    logger.warning("[smartolt] company=%s pausada por %ds (rate_limit_exceeded)",
                     company_id, seconds)


async def _http_get(cfg: SmartoltConfig, path: str) -> Dict[str, Any]:
    # Circuit-breaker: respeita rate limit anterior
    if cfg.company_id:
        rl = await _is_rate_limited(cfg.company_id)
        if rl:
            raise HTTPException(
                429, f"SmartOLT em pausa por rate-limit até {rl}. "
                "Aguarde o desbloqueio ou ajuste o intervalo de sync.")
    url = f"{_base_url(cfg)}{path}"
    async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
        r = await client.get(url, headers={"X-Token": cfg.api_key})
        # 403 do SmartOLT (rate-limit, token inválido ou IP bloqueado) →
        # ativa circuit-breaker. Como o body pode vir vazio, qualquer 403
        # já é tratado como motivo pra pausar 1h.
        if r.status_code == 403:
            if cfg.company_id:
                await _mark_rate_limited(cfg.company_id, 3600)
            raise HTTPException(
                429, "SmartOLT recusou conexão (403). Provavelmente "
                "rate-limit horário, token inválido ou IP bloqueado. "
                "Sync pausado por 1h.")
        r.raise_for_status()
        return r.json()


async def _http_post(cfg: SmartoltConfig, path: str,
                      payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if cfg.company_id:
        rl = await _is_rate_limited(cfg.company_id)
        if rl:
            raise HTTPException(
                429, f"SmartOLT em pausa por rate-limit até {rl}.")
    url = f"{_base_url(cfg)}{path}"
    async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
        r = await client.post(url, headers={"X-Token": cfg.api_key},
                                json=payload or {})
        if r.status_code == 403:
            if cfg.company_id:
                await _mark_rate_limited(cfg.company_id, 3600)
            raise HTTPException(429, "SmartOLT 403 — sync pausado por 1h.")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Settings endpoints
# ---------------------------------------------------------------------------
@router.get("/settings")
async def get_settings(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    out = _public(cfg)
    # Inclui status do rate-limit
    rl_doc = await db.smartolt_config.find_one(
        {"company_id": cid}, {"_id": 0, "rate_limited_until": 1})
    out["rate_limited_until"] = (rl_doc or {}).get("rate_limited_until")
    return out


@router.post("/clear-rate-limit")
async def clear_rate_limit(user: dict = Depends(require_role("gestor"))):
    """Limpa o circuit-breaker de rate-limit manualmente (útil para testes
    ou se o admin sabe que o limite foi reposto)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    await db.smartolt_config.update_one(
        {"company_id": cid},
        {"$unset": {"rate_limited_until": 1}},
    )
    return {"cleared": True}


@router.put("/settings")
async def put_settings(payload: SmartoltConfigUpdate,
                        user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    update = payload.model_dump(exclude_unset=True)
    # api_key vazio NÃO sobrescreve a chave existente
    if "api_key" in update and not update["api_key"]:
        update.pop("api_key")
    new_data = {**cfg.model_dump(), **update}
    new_cfg = SmartoltConfig(**new_data)  # re-valida ranges
    await db.smartolt_config.update_one(
        {"company_id": cid}, {"$set": new_cfg.model_dump()}, upsert=True,
    )
    return _public(new_cfg)


@router.post("/test-connection")
async def test_connection(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    if not cfg.subdomain or not cfg.api_key:
        raise HTTPException(400, "Configure subdomain e api_key antes de testar.")
    try:
        data = await _http_get(cfg, "/system/get_olts")
    except httpx.HTTPStatusError as e:
        return {"ok": False, "http_status": e.response.status_code, "error": e.response.text[:300]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    if not data.get("status"):
        return {"ok": False, "error": data.get("error", "API retornou status=false")}
    olts = data.get("response") or []
    return {"ok": True, "olts_count": len(olts), "olts": olts[:10]}


# ---------------------------------------------------------------------------
# Sync (cache local de ONUs)
# ---------------------------------------------------------------------------
async def _do_sync(company_id: str, cfg: SmartoltConfig) -> dict:
    if not cfg.enabled or not cfg.subdomain or not cfg.api_key:
        raise HTTPException(400, "SmartOLT desabilitado ou não configurado.")
    data = await _http_get(cfg, "/onu/get_all_onus_details")
    if not data.get("status"):
        raise HTTPException(502, f"SmartOLT: {data.get('error', 'sem status')}")
    onus = data.get("onus") or []
    inserted = updated = 0
    bulk_ts = now_iso()
    for o in onus:
        ext_id = str(o.get("unique_external_id") or "")
        if not ext_id:
            continue
        doc = {
            "company_id": company_id,
            "unique_external_id": ext_id,
            "name": o.get("name") or "",
            "name_norm": _norm(o.get("name")),
            "sn": o.get("sn") or "",
            "olt_id": str(o.get("olt_id") or ""),
            "olt_name": o.get("olt_name") or "",
            "board": str(o.get("board") or ""),
            "port": str(o.get("port") or ""),
            "onu": str(o.get("onu") or ""),
            "zone_name": o.get("zone_name") or "",
            "address": o.get("address") or "",
            "onu_type_name": o.get("onu_type_name") or "",
            "status": o.get("status") or "",
            "signal_text": o.get("signal") or "",
            "signal_1310": o.get("signal_1310"),
            "signal_1490": o.get("signal_1490"),
            "last_status_change": o.get("last_status_change"),
            "administrative_status": o.get("administrative_status"),
            "authorization_date": o.get("authorization_date"),
            "service_ports": o.get("service_ports") or [],
            "synced_at": bulk_ts,
        }
        res = await db.smartolt_onus.update_one(
            {"company_id": company_id, "unique_external_id": ext_id},
            {"$set": doc}, upsert=True,
        )
        if res.upserted_id:
            inserted += 1
        elif res.modified_count:
            updated += 1
    # Atualiza config com timestamps
    await db.smartolt_config.update_one(
        {"company_id": company_id},
        {"$set": {"last_sync_at": bulk_ts, "last_sync_total": len(onus)}},
    )
    return {"total": len(onus), "inserted": inserted, "updated": updated}


@router.post("/sync-onus")
async def sync_onus(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    started = time.time()
    result = await _do_sync(cid, cfg)
    result["elapsed_seconds"] = round(time.time() - started, 2)
    return result


# ---------------------------------------------------------------------------
# Endpoint PÚBLICO (mobile) — valida MAC contra cache SmartOLT
# ---------------------------------------------------------------------------
@router.get("/public/validate-mac/{mac_or_sn}")
async def public_validate_mac(mac_or_sn: str, collaborator_id: Optional[str] = None):
    """Valida MAC/SN no cache SmartOLT.

    Modo "instalação/troca": confere se a ONT está NO ESTOQUE DO TÉCNICO (`stok_onts`).
    Modo "retirada": confere se a ONT está INSTALADA EM CLIENTE (location=cliente).

    Resposta:
    {
      "found_smartolt": true,        # SN/MAC existe no cache SmartOLT
      "smartolt": { name, olt, board, port, status, signal },
      "in_tech_stock": true,         # está no estoque do técnico (instalação)
      "ont_record": { mac, model, location_type, client_name }
    }
    """
    key = mac_or_sn.strip()
    out: Dict[str, Any] = {
        "input": key, "found_smartolt": False, "smartolt": None,
        "in_tech_stock": False, "in_client": False, "ont_record": None,
    }
    if not key:
        raise HTTPException(400, "MAC vazio.")
    # Lookup SmartOLT
    company_id = DEMO_COMPANY_ID
    if collaborator_id:
        coll = await db.collaborators.find_one(
            {"id": collaborator_id}, {"_id": 0, "company_id": 1},
        )
        if coll:
            company_id = coll.get("company_id") or DEMO_COMPANY_ID
    onu = await db.smartolt_onus.find_one(
        {"company_id": company_id,
         "$or": [{"unique_external_id": key}, {"sn": key}]},
        {"_id": 0},
    )
    if onu:
        out["found_smartolt"] = True
        out["smartolt"] = {
            "external_id": onu.get("unique_external_id"),
            "sn": onu.get("sn"),
            "name": onu.get("name"),
            "olt_name": onu.get("olt_name"),
            "board": onu.get("board"),
            "port": onu.get("port"),
            "onu": onu.get("onu"),
            "status": onu.get("status"),
            "signal_text": onu.get("signal_text"),
            "signal_1490": onu.get("signal_1490"),
        }
    # Lookup estoque local (stok_onts)
    rec = await db.stok_onts.find_one(
        {"company_id": company_id, "mac": key}, {"_id": 0},
    )
    if rec:
        out["ont_record"] = {
            "mac": rec.get("mac"), "model": rec.get("model"),
            "location_type": rec.get("location_type"),
            "location_id": rec.get("location_id"),
            "client_name": rec.get("client_name"),
            "status": rec.get("status"),
        }
        if rec.get("location_type") == "tecnico" and rec.get("location_id") == collaborator_id:
            out["in_tech_stock"] = True
        if rec.get("location_type") == "cliente":
            out["in_client"] = True
    return out


# ---------------------------------------------------------------------------
# Endpoint PÚBLICO (mobile) — cliente do ticket está no SmartOLT?
# ---------------------------------------------------------------------------
@router.get("/public/client-by-ticket/{ticket_id}")
async def public_client_by_ticket(ticket_id: str):
    """Dado um ticket, descobre se o cliente está cadastrado no SmartOLT.

    Regras de negócio (pedido do usuário, 21/05/2026):
    - Em fluxo de retirada/reparo, se o cliente ESTIVER no SmartOLT, o
      MAC retirado precisa BATER com o MAC registrado lá (cobrança).
    - Se o cliente NÃO estiver no SmartOLT, o MAC vira opcional —
      não há referência para conferir.

    Resposta:
    {
      "found": bool,
      "mac_expected": str|null,    # MAC/SN registrado no SmartOLT
      "sn_expected": str|null,
      "client_name": str|null,
      "olt_name": str|null, "signal_text": str|null
    }
    """
    t = await db.tickets.find_one(
        {"id": ticket_id},
        {"_id": 0, "client_snapshot": 1, "company_id": 1},
    )
    if not t:
        raise HTTPException(404, "Ticket não encontrado")
    cid = t.get("company_id") or DEMO_COMPANY_ID
    cs = t.get("client_snapshot") or {}
    name = cs.get("name") or ""
    pppoe = cs.get("pppoe") or cs.get("login") or ""
    out: Dict[str, Any] = {
        "found": False, "mac_expected": None, "sn_expected": None,
        "client_name": name, "olt_name": None, "signal_text": None,
    }
    norm_pppoe = _norm(pppoe)
    norm_name = _norm(name)
    if not norm_pppoe and not norm_name:
        return out
    onu = None
    if norm_pppoe:
        onu = await db.smartolt_onus.find_one(
            {"company_id": cid, "name_norm": norm_pppoe}, {"_id": 0},
        )
    if not onu and norm_name:
        onu = await db.smartolt_onus.find_one(
            {"company_id": cid, "name_norm": norm_name}, {"_id": 0},
        )
    if not onu and norm_name and len(norm_name) >= 4:
        onu = await db.smartolt_onus.find_one(
            {"company_id": cid, "name_norm": {"$regex": norm_name}}, {"_id": 0},
        )
    if onu:
        # MAC pode estar em "mac", "ont_mac" ou no SN; SmartOLT geralmente
        # usa o SN (ex: ALCLFC090E99) como identificador
        out["found"] = True
        out["mac_expected"] = (onu.get("mac") or onu.get("ont_mac") or "").strip() or None
        out["sn_expected"] = (onu.get("sn") or "").strip().upper() or None
        out["olt_name"] = onu.get("olt_name")
        out["signal_text"] = onu.get("signal_text") or onu.get("signal_1490")
    return out


# ---------------------------------------------------------------------------
# DIAGNÓSTICO PÚBLICO PARA O ÁLVARO (suporte técnico no WhatsApp)
# ---------------------------------------------------------------------------
@router.get("/public/onu-diagnose/{phone}")
async def public_onu_diagnose(phone: str):
    """Diagnóstico técnico da ONU do cliente identificado pelo telefone.

    Usado pelo agente Álvaro durante atendimento de reparo no WhatsApp.

    Retorna:
    {
      "found": bool,
      "external_id": str|null,    # ID pra reboot
      "client_name": str|null,
      "status": "online"|"los"|"power_off"|"offline"|"unknown",
      "uptime_minutes": int|null, # quanto tempo está online (se status=online)
      "uptime_human": str|null,   # "2h 15min" formatado
      "last_status_change": str|null,  # ISO timestamp da última mudança
      "signal_text": str|null,
      "olt_name": str|null,
      "diagnosis": str,           # explicação pro cliente em PT-BR
    }
    """
    # Procura o subscriber pelo phone (em qualquer empresa que tenha esse nº)
    norm = _norm(phone)
    sub_phone = await db.subscriber_phones.find_one(
        {"variants": norm}, {"_id": 0, "subscriber_id": 1, "company_id": 1},
    )
    if not sub_phone:
        return {"found": False, "diagnosis":
                "Cliente não encontrado no SmartOLT. Vou abrir um atendimento "
                "técnico pra investigar do zero."}
    cid = sub_phone.get("company_id")
    sub_id = sub_phone.get("subscriber_id")
    sub = await db.subscribers.find_one(
        {"id": sub_id}, {"_id": 0, "name": 1, "pppoe": 1, "external_code": 1},
    )
    if not sub:
        return {"found": False, "diagnosis":
                "Cadastro do cliente não encontrado."}
    norm_name = _norm(sub.get("name") or "")
    norm_pppoe = _norm(sub.get("pppoe") or sub.get("external_code") or "")
    onu = None
    if norm_pppoe:
        onu = await db.smartolt_onus.find_one(
            {"company_id": cid, "name_norm": norm_pppoe}, {"_id": 0},
        )
    if not onu and norm_name:
        onu = await db.smartolt_onus.find_one(
            {"company_id": cid, "name_norm": norm_name}, {"_id": 0},
        )
    if not onu:
        return {"found": False, "client_name": sub.get("name"),
                  "diagnosis": "Cliente está cadastrado mas a ONU não foi "
                               "localizada no SmartOLT. Vou abrir atendimento."}

    status_raw = (onu.get("status") or "").lower()
    # Normaliza status para 4 categorias
    if "online" in status_raw or "up" in status_raw:
        status = "online"
    elif "los" in status_raw or "loss" in status_raw:
        status = "los"
    elif "power" in status_raw and "off" in status_raw:
        status = "power_off"
    elif "off" in status_raw or "down" in status_raw:
        status = "offline"
    else:
        status = status_raw or "unknown"

    # Calcula uptime
    uptime_minutes = None
    uptime_human = None
    last_change = onu.get("last_status_change")
    if status == "online" and last_change:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(str(last_change).replace("Z", "+00:00"))
            delta = datetime.now(timezone.utc) - dt
            uptime_minutes = int(delta.total_seconds() // 60)
            d = delta.days
            h = (delta.seconds // 3600)
            m = (delta.seconds // 60) % 60
            parts = []
            if d:
                parts.append(f"{d}d")
            if h:
                parts.append(f"{h}h")
            if m and d == 0:
                parts.append(f"{m}min")
            uptime_human = " ".join(parts) or "<1min"
        except Exception:
            pass

    # Diagnóstico em PT-BR pro cliente
    diag_map = {
        "online": (
            f"Equipamento ONLINE há {uptime_human or '? tempo'}. "
            "Sinal estável. Vou reiniciar a ONU remotamente — pode ser "
            "uma instabilidade momentânea. Você também pode desligar o "
            "equipamento da tomada por 30s e religar."
        ),
        "los": (
            "Status LOS (Loss of Signal): a fibra que chega na sua casa "
            "não está recebendo luz da nossa rede. Causas comuns: cabo "
            "rompido na rua (caminhão, manutenção elétrica), conector "
            "solto na caixa externa, ou problema na CTO do seu bairro. "
            "Não é coisa que você resolve aí — preciso enviar técnico."
        ),
        "power_off": (
            "Status POWER OFF: o equipamento não está recebendo energia. "
            "Provavelmente é algo dentro da sua casa: a tomada onde o "
            "aparelho está ligado, o cabo de força ou a fonte do roteador. "
            "Verifique se a tomada tem energia (pode testar com um "
            "carregador, por exemplo)."
        ),
        "offline": (
            "Equipamento OFFLINE. Pode ser falta de energia, equipamento "
            "desligado ou problema na fibra. Vou pedir pra você verificar "
            "se ele está aceso primeiro."
        ),
        "unknown": (
            "Não consegui identificar o status agora. Vou abrir "
            "atendimento técnico pra investigar."
        ),
    }
    return {
        "found": True,
        "external_id": onu.get("unique_external_id"),
        "client_name": sub.get("name"),
        "subscriber_id": sub_id,
        "company_id": cid,
        "status": status,
        "uptime_minutes": uptime_minutes,
        "uptime_human": uptime_human,
        "last_status_change": last_change,
        "signal_text": onu.get("signal_text"),
        "olt_name": onu.get("olt_name"),
        "diagnosis": diag_map.get(status, diag_map["unknown"]),
    }


class PublicRebootIn(BaseModel):
    """Reboot ONU disparado pelo agente IA durante atendimento WhatsApp."""
    external_id: str
    phone: str  # pra auditoria — quem pediu o reboot


@router.post("/public/reboot-onu")
async def public_reboot_onu(payload: PublicRebootIn):
    """Reinicia ONU via SmartOLT a pedido do agente IA.

    Sem auth — usado pelo Álvaro (suporte técnico). Audita em
    `smartolt_actions` quem disparou.

    Rate-limit: max 1 reboot por external_id a cada 5 minutos.
    """
    from datetime import datetime, timezone, timedelta
    ext = (payload.external_id or "").strip()
    if not ext:
        raise HTTPException(400, "external_id obrigatório")
    onu = await db.smartolt_onus.find_one(
        {"unique_external_id": ext},
        {"_id": 0, "company_id": 1, "name": 1, "olt_name": 1},
    )
    if not onu:
        raise HTTPException(404, "ONU não encontrada")
    cid = onu.get("company_id")
    # Rate-limit: olha últimos 5 minutos
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    recent = await db.smartolt_actions.find_one({
        "company_id": cid, "external_id": ext,
        "action": "reboot", "created_at": {"$gte": cutoff},
    }, {"_id": 0, "id": 1})
    if recent:
        return {"ok": False, "skipped": True,
                "reason": "reboot_recente",
                "message": "Já reiniciei seu equipamento há poucos minutos. "
                             "Aguarde mais 1-2 min antes de tentar de novo."}
    cfg = await _get_config(cid)
    if not cfg.enabled or not cfg.subdomain or not cfg.api_key:
        raise HTTPException(503, "SmartOLT desabilitado")
    try:
        resp = await _http_post(cfg, f"/onu/reboot/{ext}")
    except Exception as e:
        raise HTTPException(502, f"SmartOLT erro: {e}") from e
    ok = bool(resp.get("status"))
    await db.smartolt_actions.insert_one({
        "id": f"sma-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "action": "reboot",
        "external_id": ext,
        "onu_name": onu.get("name"),
        "olt_name": onu.get("olt_name"),
        "actor_user": "alvaro_ai",
        "actor_phone": payload.phone,
        "result_ok": ok,
        "result_raw": resp,
        "created_at": now_iso(),
    })
    return {"ok": ok, "external_id": ext,
             "message": ("Pronto, mandei o reboot. Em ~60-90 segundos seu "
                          "equipamento reconecta. Tenta agora aí.") if ok
                          else "Não consegui reiniciar agora — vou abrir "
                                "atendimento técnico."}





# ---------------------------------------------------------------------------
# Lookup + signal
# ---------------------------------------------------------------------------
@router.get("/onus/by-vlan/{vlan}")
async def list_onus_by_vlan(
    vlan: int,
    user: dict = Depends(require_role("gestor")),
):
    """Lista ONUs/ONTs cuja VLAN dos service_ports == {vlan}.

    A SmartOLT API NÃO tem endpoint nativo `get_by_vlan`. Estratégia:
      1. Chama /onu/get_all_onus_details (mesmo endpoint usado no sync).
      2. Filtra ONUs cujo service_ports[*].vlan == vlan (em string ou int).
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    if not cfg.enabled or not cfg.subdomain or not cfg.api_key:
        raise HTTPException(400, "SmartOLT desabilitado ou não configurado.")
    try:
        data = await _http_get(cfg, "/onu/get_all_onus_details")
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"SmartOLT HTTP {e.response.status_code}")
    except Exception as e:
        raise HTTPException(502, f"SmartOLT erro: {type(e).__name__}: {e}")

    onus_raw = data.get("onus") or []
    target = str(vlan)
    onus_norm = []
    for o in onus_raw:
        sps = o.get("service_ports") or []
        # Match se QUALQUER service_port estiver na VLAN procurada
        # (vlan/cvlan/svlan — formatos diferentes por instalação)
        matched_vlan = None
        for sp in sps:
            v = str(sp.get("vlan") or "")
            cv = str(sp.get("cvlan") or "")
            sv = str(sp.get("svlan") or "")
            if v == target or cv == target or sv == target:
                matched_vlan = v or cv or sv
                break
        if not matched_vlan:
            continue
        onus_norm.append({
            "unique_external_id": str(o.get("unique_external_id") or ""),
            "name": o.get("name") or "",
            "sn": o.get("sn") or "",
            "olt_name": o.get("olt_name") or "",
            "board": str(o.get("board") or ""),
            "port": str(o.get("port") or ""),
            "onu": str(o.get("onu") or ""),
            "zone_name": o.get("zone_name") or "",
            "address": o.get("address") or "",
            "status": o.get("status") or "",
            "signal_text": o.get("signal") or "",
            "vlan": matched_vlan,
        })
    return {
        "vlan": vlan,
        "count": len(onus_norm),
        "total_scanned": len(onus_raw),
        "source": "smartolt_live",
        "onus": onus_norm,
    }



@router.get("/onu/lookup")
async def lookup_onu(
    pppoe: Optional[str] = Query(default=None),
    name: Optional[str] = Query(default=None),
    user: dict = Depends(require_role("gestor")),
):
    """Busca ONU(s) no cache local pelo PPPoE/nome. Retorna lista ordenada por relevância."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    norm_pppoe = _norm(pppoe)
    norm_name = _norm(name)
    if not norm_pppoe and not norm_name:
        raise HTTPException(400, "Informe pppoe ou name.")
    # Match exato no PPPoE (preferido), depois exato no name, depois substring
    candidates: List[dict] = []
    if norm_pppoe:
        exact = await db.smartolt_onus.find(
            {"company_id": cid, "name_norm": norm_pppoe}, {"_id": 0},
        ).to_list(20)
        candidates.extend(exact)
    if not candidates and norm_name:
        exact_n = await db.smartolt_onus.find(
            {"company_id": cid, "name_norm": norm_name}, {"_id": 0},
        ).to_list(20)
        candidates.extend(exact_n)
    if not candidates:
        # Substring (regex) — fallback
        substr = norm_pppoe or norm_name
        if len(substr) >= 4:
            cur = db.smartolt_onus.find(
                {"company_id": cid, "name_norm": {"$regex": substr}}, {"_id": 0},
            ).limit(20)
            candidates = await cur.to_list(20)
    return {"count": len(candidates), "matches": candidates}


@router.get("/onu/{external_id}/signal")
async def get_onu_signal_live(external_id: str,
                                user: dict = Depends(require_role("gestor"))):
    """Retorna sinal vivo da ONU. Usa cache local com TTL configurado.

    Se cache estiver fresco (< signal_cache_seconds), retorna direto. Caso
    contrário, consulta a SmartOLT, atualiza o cache e retorna.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    onu = await db.smartolt_onus.find_one(
        {"company_id": cid, "unique_external_id": external_id}, {"_id": 0},
    )
    if not onu:
        raise HTTPException(404, "ONU não encontrada no cache. Rode sync.")
    # Calcula idade do cache em segundos
    fresh = False
    last = onu.get("signal_synced_at") or onu.get("synced_at")
    if last:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - dt).total_seconds()
            fresh = age < cfg.signal_cache_seconds
        except Exception:
            fresh = False
    if fresh:
        return {"cached": True, "onu": onu}
    # Busca live
    if not cfg.enabled or not cfg.subdomain or not cfg.api_key:
        return {"cached": True, "onu": onu, "warning": "smartolt_disabled"}
    try:
        sig = await _http_get(cfg, f"/onu/get_onu_signal/{external_id}")
        st = await _http_get(cfg, f"/onu/get_onu_status/{external_id}")
    except Exception as e:
        return {"cached": True, "onu": onu, "warning": f"live_fetch_failed: {e}"}
    sig_resp = sig.get("response") or {}
    st_resp = st.get("response") or {}
    update = {
        "signal_text": sig_resp.get("signal") or onu.get("signal_text"),
        "signal_1310": sig_resp.get("signal_1310", onu.get("signal_1310")),
        "signal_1490": sig_resp.get("signal_1490", onu.get("signal_1490")),
        "status": st_resp.get("status") or onu.get("status"),
        "last_status_change": st_resp.get("last_status_change") or onu.get("last_status_change"),
        "signal_synced_at": now_iso(),
    }
    await db.smartolt_onus.update_one(
        {"company_id": cid, "unique_external_id": external_id}, {"$set": update},
    )
    onu.update(update)
    return {"cached": False, "onu": onu}


@router.get("/onu/{external_id}/actions")
async def get_onu_actions_history(external_id: str, limit: int = 20,
                                     user: dict = Depends(require_role("gestor"))):
    """Retorna histórico de ações (reboot, etc.) executadas nesta ONU.

    Útil pra técnico ver na UI quantos reboots já foram feitos no equipamento.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    items = await db.smartolt_actions.find(
        {"company_id": cid, "external_id": external_id},
        {"_id": 0, "result_raw": 0},
    ).sort("created_at", -1).limit(max(1, min(limit, 100))).to_list(limit)
    return {"count": len(items), "items": items}


@router.post("/onu/{external_id}/reboot")
async def reboot_onu(external_id: str,
                       user: dict = Depends(require_role("gestor"))):
    """Reinicia a ONT/ONU via SmartOLT API.

    Usa POST /onu/reboot/{external_id} no SmartOLT (equivalente ao endpoint
    público `reboot-onu-by-onu-unique-external-id`). Best-effort: registra
    a ação na coleção `smartolt_actions` para auditoria.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    if not cfg.enabled or not cfg.subdomain or not cfg.api_key:
        raise HTTPException(400, "SmartOLT desabilitado ou não configurado.")
    onu = await db.smartolt_onus.find_one(
        {"company_id": cid, "unique_external_id": external_id},
        {"_id": 0, "name": 1, "olt_name": 1, "sn": 1},
    )
    if not onu:
        raise HTTPException(404, "ONU não encontrada no cache.")
    try:
        resp = await _http_post(cfg, f"/onu/reboot/{external_id}")
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            502,
            f"SmartOLT HTTP {e.response.status_code}: {e.response.text[:200]}",
        ) from e
    except Exception as e:
        raise HTTPException(502, f"SmartOLT erro: {e}") from e
    ok = bool(resp.get("status"))
    await db.smartolt_actions.insert_one({
        "id": f"sma-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "action": "reboot",
        "external_id": external_id,
        "onu_name": onu.get("name"),
        "olt_name": onu.get("olt_name"),
        "actor_user": user.get("email") or user.get("id"),
        "actor_user_id": user.get("id"),
        "result_ok": ok,
        "result_raw": resp,
        "created_at": now_iso(),
    })
    if not ok:
        raise HTTPException(502, f"SmartOLT recusou reboot: {resp.get('error') or resp}")
    return {"ok": True, "external_id": external_id, "smartolt": resp}



async def resolve_signal_for_ticket(ticket: dict) -> Optional[dict]:
    """Resolve sinal SmartOLT para uma bolha. Best-effort, nunca lança."""
    try:
        cid = ticket.get("company_id") or DEMO_COMPANY_ID
        snap = ticket.get("client_snapshot") or {}
        pppoe = (ticket.get("atlaz_pppoe_user") or snap.get("pppoe_user") or "").strip()
        name = (snap.get("name") or "").strip()
        if not pppoe and not name:
            return None
        norm_pppoe = _norm(pppoe)
        norm_name = _norm(name)
        candidate = None
        if norm_pppoe:
            candidate = await db.smartolt_onus.find_one(
                {"company_id": cid, "name_norm": norm_pppoe}, {"_id": 0},
            )
        if not candidate and norm_name:
            candidate = await db.smartolt_onus.find_one(
                {"company_id": cid, "name_norm": norm_name}, {"_id": 0},
            )
        return candidate
    except Exception as e:
        logger.warning("[smartolt] resolve_signal_for_ticket falhou: %s", e)
        return None


def _live_signal_summary(onu: dict) -> dict:
    """Resumo compacto pro pill/UI da Lousa (não expõe campos pesados)."""
    rx = onu.get("signal_1490") or onu.get("signal_1310")
    rxf = None
    try:
        rxf = float(rx) if rx is not None else None
    except (TypeError, ValueError):
        rxf = None
    quality = "unknown"
    if rxf is not None:
        if rxf >= -23:
            quality = "good"
        elif rxf >= -27:
            quality = "warn"
        else:
            quality = "bad"
    # Parse CTO + CTO-port a partir do `zone_name` (formato típico
    # "CTO - 1 - 10 - 01" → CTO_BOX = "CTO 1 10" + CTO_PORT = "01")
    cto_box = None
    cto_port = None
    zone = (onu.get("zone_name") or "").strip()
    if zone:
        parts = [p.strip() for p in zone.replace("-", "·").split("·") if p.strip()]
        if len(parts) >= 2:
            cto_box = " ".join(parts[:-1])
            cto_port = parts[-1]
        else:
            cto_box = zone
    # PORTA OLT = board/port (e.g. "1/10")
    board = onu.get("board") or ""
    port = onu.get("port") or ""
    onu_id = onu.get("onu") or ""
    olt_port = "/".join([s for s in [board, port] if s]) or None
    # VLAN: tenta service_ports[*].vlan (se a sync salvou)
    vlan = None
    for sp in (onu.get("service_ports") or []):
        if isinstance(sp, dict):
            v = sp.get("vlan") or sp.get("cvlan") or sp.get("svlan")
            if v:
                vlan = str(v)
                break
    # Uptime online — calcula tempo desde last_status_change (quando ONU
    # ficou Online). Formatos comuns SmartOLT: ISO-8601 ou "YYYY-MM-DD HH:MM:SS".
    uptime_human = None
    uptime_seconds = None
    last_change = onu.get("last_status_change")
    status_str = (onu.get("status") or "").lower()
    if last_change and status_str == "online":
        try:
            from datetime import datetime, timezone
            ts = str(last_change).strip().replace("Z", "+00:00")
            # Normaliza "YYYY-MM-DD HH:MM:SS" -> "YYYY-MM-DDTHH:MM:SS"
            if " " in ts and "T" not in ts:
                ts = ts.replace(" ", "T", 1)
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - dt
            secs = int(delta.total_seconds())
            if secs >= 0:
                uptime_seconds = secs
                d, rem = divmod(secs, 86400)
                h, rem = divmod(rem, 3600)
                m, _ = divmod(rem, 60)
                if d > 0:
                    uptime_human = f"{d}d {h}h"
                elif h > 0:
                    uptime_human = f"{h}h {m}m"
                else:
                    uptime_human = f"{m}m"
        except (ValueError, TypeError):
            pass
    return {
        "external_id": onu.get("unique_external_id"),
        "name": onu.get("name"),
        "rx_dbm": rxf,
        "signal_text": onu.get("signal_text"),
        "status": onu.get("status"),
        "quality": quality,
        "olt_name": onu.get("olt_name"),
        "olt_port": olt_port,         # "1/10"
        "board": board, "port": port, "onu": onu_id,
        "sn": onu.get("sn"),
        "cto_box": cto_box,            # "CTO 1 10"
        "cto_port": cto_port,          # "01"
        "vlan": vlan,
        "uptime_human": uptime_human,  # "2d 14h" / "5h 32m" / "12m"
        "uptime_seconds": uptime_seconds,
        "last_status_change": last_change,
        "synced_at": onu.get("synced_at"),
    }


async def enrich_tickets_with_live_signal(tickets: List[dict], company_id: str) -> None:
    """Anexa `live_signal` em cada ticket (best-effort, em batch — 1 query)."""
    if not tickets:
        return
    try:
        # Coleta TODOS os name_norm candidatos (pppoe + name)
        wanted: set[str] = set()
        per_ticket: List[tuple] = []  # (idx, norm_pppoe, norm_name)
        for i, t in enumerate(tickets):
            snap = t.get("client_snapshot") or {}
            np_ = _norm(snap.get("pppoe_user") or t.get("atlaz_pppoe_user") or "")
            nn_ = _norm(snap.get("name") or "")
            if np_:
                wanted.add(np_)
            if nn_:
                wanted.add(nn_)
            per_ticket.append((i, np_, nn_))
        if not wanted:
            return
        cur = db.smartolt_onus.find(
            {"company_id": company_id, "name_norm": {"$in": list(wanted)}},
            {"_id": 0},
        )
        idx: Dict[str, dict] = {}
        async for doc in cur:
            # Se houver duplicatas pelo mesmo name_norm, mantém a mais recentemente sincronizada
            existing = idx.get(doc["name_norm"])
            if not existing or (doc.get("synced_at") or "") > (existing.get("synced_at") or ""):
                idx[doc["name_norm"]] = doc
        for i, np_, nn_ in per_ticket:
            onu = (idx.get(np_) if np_ else None) or (idx.get(nn_) if nn_ else None)
            if onu:
                tickets[i]["live_signal"] = _live_signal_summary(onu)
    except Exception as e:
        logger.warning("[smartolt] enrich_tickets_with_live_signal falhou: %s", e)


# ---------------------------------------------------------------------------
# Worker periódico
# ---------------------------------------------------------------------------
_WORKER_TASK: Optional[asyncio.Task] = None
_WORKER_RUN = True


async def _worker_loop() -> None:
    """Loop diário: roda o sync de ONUs respeitando o intervalo de cada empresa."""
    last_run: Dict[str, float] = {}
    while _WORKER_RUN:
        try:
            cfgs = await db.smartolt_config.find({"enabled": True}, {"_id": 0}).to_list(100)
            now = time.time()
            for raw in cfgs:
                try:
                    cfg = SmartoltConfig(**raw)
                except Exception:
                    continue
                cid = cfg.company_id
                # Circuit-breaker: pula se em pausa por rate-limit
                if await _is_rate_limited(cid):
                    continue
                interval = cfg.sync_interval_minutes * 60
                if cid in last_run and (now - last_run[cid]) < interval:
                    continue
                last_run[cid] = now
                try:
                    res = await _do_sync(cid, cfg)
                    logger.info("[smartolt] worker sync %s — %s", cid, res)
                except HTTPException as he:
                    if he.status_code == 429:
                        logger.info("[smartolt] worker %s pausado por rate-limit", cid)
                    else:
                        logger.warning("[smartolt] worker sync falhou %s: %s",
                                          cid, he.detail)
                except Exception as e:
                    logger.warning("[smartolt] worker sync falhou %s: %s", cid, e)
        except Exception as e:
            logger.warning("[smartolt] worker tick falhou: %s", e)
        await asyncio.sleep(60)  # tick rápido, mas só dispara se interval passou


async def start_worker() -> None:
    global _WORKER_TASK
    if _WORKER_TASK and not _WORKER_TASK.done():
        return
    _WORKER_TASK = asyncio.create_task(_worker_loop())
    logger.info("[smartolt] worker started")


async def stop_worker() -> None:
    global _WORKER_RUN
    _WORKER_RUN = False
    if _WORKER_TASK:
        _WORKER_TASK.cancel()
    logger.info("[smartolt] worker stopped")
