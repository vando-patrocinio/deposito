"""Integração com SmartOLT — leitura de ONU/sinal por nome PPPoE.

Autenticação: header `X-Token` na URL `https://{subdomain}.smartolt.com/api/...`
Estratégia:
- Sync periódico de TODAS as ONUs para `db.smartolt_onus` (cache local).
- Lookup de bolha (Lousa) → casa pelo PPPoE (preferencial) ou nome do cliente
  (case-insensitive, sem acento, sem espaço).
- Endpoint live `signal/{external_id}` revalida em SmartOLT com TTL configurável.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "infra-team",
    "domain": "rede",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import logging
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, get_current_user, now_iso, require_role
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
    sync_interval_minutes: int = Field(default=15, ge=15, le=1440)  # iter182 — 15min default; mín 15min
    signal_cache_seconds: int = Field(default=60, ge=10, le=3600)
    timeout_seconds: int = Field(default=20, ge=5, le=120)
    last_sync_at: Optional[str] = None
    last_sync_total: int = 0


class SmartoltConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    subdomain: Optional[str] = None
    api_key: Optional[str] = None
    sync_interval_minutes: Optional[int] = Field(default=None, ge=15, le=1440)
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


async def _mark_rate_limited(company_id: str, seconds: int = 900) -> None:
    """Marca a empresa como bloqueada por `seconds` segundos (default 15min).

    iter183 — reduzido de 1h → 15min. SmartOLT trial geralmente desbloqueia
    a cada 5-10min; 1h era muito punitivo. Se ainda bater, o circuit
    reabre automaticamente após 15min.
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
        # 403 do SmartOLT: pode ser RENEW (assinatura vencida) ou rate-limit.
        # iter183 — Detecta "renew" no body → erro específico + pausa 24h
        # (não enche o log). Caso contrário, mantém comportamento de
        # rate-limit (pausa 15min).
        if r.status_code == 403:
            body = (r.text or "").lower()
            is_renew = "renew" in body or "subscription" in body \
                          or "expired" in body or "must renew" in body
            if cfg.company_id:
                await _mark_rate_limited(cfg.company_id,
                                            86400 if is_renew else 900)
            if is_renew:
                raise HTTPException(
                    429,
                    "Assinatura SmartOLT vencida — renove em smartolt.com. "
                    "Sync pausado por 24h.")
            raise HTTPException(
                429, "SmartOLT recusou conexão (403). Provavelmente "
                "rate-limit horário, token inválido ou IP bloqueado. "
                "Sync pausado por 15min.")
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
            body = (r.text or "").lower()
            is_renew = "renew" in body or "subscription" in body \
                          or "expired" in body or "must renew" in body
            if cfg.company_id:
                await _mark_rate_limited(cfg.company_id,
                                            86400 if is_renew else 900)
            if is_renew:
                raise HTTPException(
                    429,
                    "Assinatura SmartOLT vencida — renove em smartolt.com. "
                    "Sync pausado por 24h.")
            raise HTTPException(429, "SmartOLT 403 — sync pausado por 15min.")
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
        # iter180 — MAC vem do endpoint per-ONU (não do bulk).
        # Aqui só seto MAC se vier no payload (Huawei às vezes traz),
        # senão NÃO sobrescrevo o valor já cacheado.
        payload_mac = (o.get("ont_mac") or o.get("mac")
                       or o.get("mac_address") or "").strip().upper() or None
        if payload_mac:
            doc["mac"] = payload_mac
        # iter182 — Histórico de sinal (rolling window últimas 24h)
        # para o detector de degradação. Só guarda se signal_1490 mudou.
        s1490 = doc.get("signal_1490")
        try:
            new_rx = float(s1490) if s1490 is not None else None
        except (TypeError, ValueError):
            new_rx = None
        if new_rx is not None:
            update_payload = {"$set": doc, "$push": {
                "signal_history_24h": {
                    "$each": [{"t": bulk_ts, "rx": new_rx}],
                    # Limita a 24 entradas (1 a cada hora aprox.)
                    "$slice": -24,
                },
            }}
            res = await db.smartolt_onus.update_one(
                {"company_id": company_id, "unique_external_id": ext_id},
                update_payload, upsert=True,
            )
        else:
            res = await db.smartolt_onus.update_one(
                {"company_id": company_id, "unique_external_id": ext_id},
                {"$set": doc}, upsert=True,
            )
        if res.upserted_id:
            inserted += 1
        elif res.modified_count:
            updated += 1
    # iter182 — Após o sync, roda o detector de degradação
    await _detect_signal_degradation(company_id, bulk_ts)
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
    # iter162 — também tenta pppoe_user (campo legado de alguns tickets)
    pppoe = cs.get("pppoe") or cs.get("login") or cs.get("pppoe_user") or ""
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
# iter160 — VALIDAÇÃO DE RETIRADA POR SN (foto + OCR contra SmartOLT)
# ---------------------------------------------------------------------------
@router.get("/public/validate-withdraw-sn/{ticket_id}")
async def public_validate_withdraw_sn(ticket_id: str, sn: str):
    """Valida se o SN escaneado coincide com o equipamento cadastrado no
    SmartOLT para o cliente do ticket.

    Regra (pedido user 28/05/2026):
    - Foto da Retirada lê o SN via OCR (Claude 4.6)
    - Aqui comparamos `sn` informado com o `sn_expected` do SmartOLT
    - Só libera a retirada quando coincidir; caso contrário, técnico
      precisa confirmar divergência manualmente (bypass = `force=true`
      no submit).

    Resposta:
    {
      "ok": true/false,
      "match": true/false,
      "sn_scanned": "ALCLFC...",
      "sn_expected": "ALCLFC...",
      "client_found": bool,
      "client_name": str,
      "reason": "match" | "mismatch" | "not_in_smartolt" | "no_sn_scanned",
      "olt_name": str | null
    }
    """
    if not sn or not sn.strip():
        return {"ok": False, "match": False, "reason": "no_sn_scanned"}
    sn_n = sn.strip().upper().replace(":", "").replace("-", "").replace(" ", "")

    t = await db.tickets.find_one({"id": ticket_id}, {"_id": 0})
    if not t:
        return {"ok": False, "match": False, "reason": "ticket_not_found"}

    # Reaproveita lookup do public_client_by_ticket
    cid = t.get("company_id") or DEMO_COMPANY_ID
    cs = t.get("client_snapshot") or {}
    name = cs.get("name") or ""
    pppoe = cs.get("pppoe") or cs.get("login") or cs.get("pppoe_user") or ""
    norm_pppoe = _norm(pppoe)
    norm_name = _norm(name)
    onu = None
    if norm_pppoe:
        onu = await db.smartolt_onus.find_one(
            {"company_id": cid, "name_norm": norm_pppoe}, {"_id": 0})
    if not onu and norm_name:
        onu = await db.smartolt_onus.find_one(
            {"company_id": cid, "name_norm": norm_name}, {"_id": 0})
    if not onu and norm_name and len(norm_name) >= 4:
        onu = await db.smartolt_onus.find_one(
            {"company_id": cid, "name_norm": {"$regex": norm_name}},
            {"_id": 0})

    if not onu:
        # iter161 — auditoria: registra a tentativa também quando o cliente
        # não está no SmartOLT (sem `sn_expected`)
        try:
            await db.withdraw_sn_audit.insert_one({
                "company_id": cid,
                "ticket_id": ticket_id,
                "client_name": name,
                "sn_scanned": sn_n,
                "sn_expected": None,
                "match": False,
                "reason": "not_in_smartolt",
                "olt_name": None,
                "technician_id": t.get("assigned_to_id"),
                "technician_name": t.get("assigned_to_name"),
                "created_at": now_iso(),
            })
        except Exception as e:  # noqa: BLE001
            logger.warning("[smartolt] audit log not_in_smartolt falhou: %s", e)
        return {
            "ok": True, "match": False, "client_found": False,
            "client_name": name, "sn_scanned": sn_n, "sn_expected": None,
            "reason": "not_in_smartolt",
            "olt_name": None,
        }

    sn_expected = (onu.get("sn") or "").strip().upper().replace(":", "").replace("-", "")
    is_match = bool(sn_expected) and (sn_expected == sn_n)
    response = {
        "ok": True, "match": is_match,
        "client_found": True, "client_name": name,
        "sn_scanned": sn_n,
        "sn_expected": sn_expected or None,
        "reason": "match" if is_match else (
            "mismatch" if sn_expected else "not_in_smartolt"),
        "olt_name": onu.get("olt_name"),
        "signal_text": onu.get("signal_text") or onu.get("signal_1490"),
    }
    # iter161 — auditoria: registra toda tentativa de validação para o gestor
    try:
        await db.withdraw_sn_audit.insert_one({
            "company_id": cid,
            "ticket_id": ticket_id,
            "client_name": name,
            "sn_scanned": sn_n,
            "sn_expected": sn_expected or None,
            "match": is_match,
            "reason": response["reason"],
            "olt_name": onu.get("olt_name"),
            "technician_id": t.get("assigned_to_id"),
            "technician_name": t.get("assigned_to_name"),
            "created_at": now_iso(),
        })
    except Exception as e:  # noqa: BLE001
        logger.warning("[smartolt] audit log falhou: %s", e)
    return response


@router.get("/clients-stock")
async def smartolt_clients_stock(search: Optional[str] = None,
                                       limit: int = 200,
                                       user: dict = Depends(get_current_user)):
    """iter163 — View consolidada "1 cliente = 1 equipamento".

    Lista todos os clientes do SmartOLT (cache local) com o SN atual,
    porta da CTO, sinal, último ticket de instalação e retirada conhecidos,
    e histórico de trocas de porta.

    Esta é a aba "👤 Clientes (SmartOLT)" do Estoque.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if search:
        q["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"sn": {"$regex": search, "$options": "i"}},
            {"address": {"$regex": search, "$options": "i"}},
        ]
    onus = await db.smartolt_onus.find(
        q,
        {"_id": 0, "name": 1, "name_norm": 1, "sn": 1, "olt_name": 1,
         "board": 1, "port": 1, "onu": 1, "signal_text": 1,
         "signal_1490": 1, "status": 1, "zone_name": 1, "address": 1,
         "synced_at": 1, "authorization_date": 1},
    ).limit(limit).to_list(limit)
    # Resolve histórico em batch: tickets finalizados de instalacao/retirada
    # + port swaps (db.cto_port_swaps).
    name_norms = [o.get("name_norm") for o in onus if o.get("name_norm")]
    tickets_by_norm: Dict[str, List[Dict[str, Any]]] = {}
    if name_norms:
        async for t in db.tickets.find(
                {"company_id": cid,
                 "type": {"$in": ["instalacao", "retirada", "reparo"]},
                 "status": "fechado",
                 "client_snapshot.name_norm": {"$in": name_norms}},
                {"_id": 0, "id": 1, "type": 1, "closed_at": 1,
                 "client_snapshot": 1, "closed_by_email": 1,
                 "assigned_to_name": 1, "completion_data": 1}):
            n = (t.get("client_snapshot") or {}).get("name_norm") or ""
            tickets_by_norm.setdefault(n, []).append(t)
    # port swaps por SN (mais confiável que name_norm)
    sns = [o.get("sn") for o in onus if o.get("sn")]
    swaps_by_sn: Dict[str, List[Dict[str, Any]]] = {}
    if sns:
        async for sw in db.cto_port_swaps.find(
                {"company_id": cid,
                 "$or": [{"new_mac": {"$in": sns}},
                          {"old_mac": {"$in": sns}}]},
                {"_id": 0}):
            for k in ("new_mac", "old_mac"):
                if sw.get(k) in sns:
                    swaps_by_sn.setdefault(sw[k], []).append(sw)
    items: List[Dict[str, Any]] = []
    for o in onus:
        norm = o.get("name_norm") or ""
        tlist = sorted(tickets_by_norm.get(norm, []),
                          key=lambda x: x.get("closed_at") or "", reverse=True)
        last_install = next((t for t in tlist if t.get("type") == "instalacao"), None)
        last_withdraw = next((t for t in tlist if t.get("type") == "retirada"), None)
        swap_list = swaps_by_sn.get(o.get("sn") or "", [])
        items.append({
            "name": o.get("name"),
            "sn": o.get("sn"),
            "olt_name": o.get("olt_name"),
            "board": o.get("board"),
            "port": o.get("port"),
            "onu": o.get("onu"),
            "cto_port": f"{o.get('board')}/{o.get('port')}/{o.get('onu')}"
                          if o.get("board") else None,
            "signal": o.get("signal_text") or o.get("signal_1490"),
            "status": o.get("status"),
            "zone_name": o.get("zone_name"),
            "address": o.get("address"),
            "synced_at": o.get("synced_at"),
            "authorization_date": o.get("authorization_date"),
            "installed_by": (last_install or {}).get("assigned_to_name")
                              or (last_install or {}).get("closed_by_email"),
            "installed_at": (last_install or {}).get("closed_at"),
            "withdrawn_by": (last_withdraw or {}).get("assigned_to_name")
                              or (last_withdraw or {}).get("closed_by_email"),
            "withdrawn_at": (last_withdraw or {}).get("closed_at"),
            "port_swap_count": len(swap_list),
            "last_port_swap": (swap_list[0] if swap_list else None),
        })
    items.sort(key=lambda x: (x.get("status") != "online",
                                 (x.get("name") or "").lower()))
    return {"items": items, "total": len(items)}


@router.get("/withdraw-sn-audit")
async def withdraw_sn_audit(
        days: int = 30,
        only_mismatch: bool = False,
        technician_id: Optional[str] = None,
        user: dict = Depends(get_current_user)):
    """iter161 — Histórico auditável das validações SN da Retirada.

    Cada tentativa de validação durante uma Retirada é registrada em
    `withdraw_sn_audit`. Este endpoint permite ao gestor:
    - Ver todos os registros dos últimos N dias
    - Filtrar apenas mismatches (tentativas de retirada com SN errado)
    - Filtrar por técnico

    Resposta inclui agregação por técnico para detectar "forçadores"
    (técnicos com taxa de mismatch acima da média).
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))
    q: Dict[str, Any] = {"company_id": cid,
                              "created_at": {"$gte": cutoff.isoformat()}}
    if only_mismatch:
        q["reason"] = "mismatch"
    if technician_id:
        q["technician_id"] = technician_id

    items = await db.withdraw_sn_audit.find(q, {"_id": 0}).sort(
        "created_at", -1).limit(500).to_list(500)

    # Agregação por técnico
    by_tech: Dict[str, Dict[str, Any]] = {}
    for it in items:
        tid = it.get("technician_id") or "—"
        tname = it.get("technician_name") or "Sem nome"
        if tid not in by_tech:
            by_tech[tid] = {"technician_id": tid, "technician_name": tname,
                              "total": 0, "match": 0, "mismatch": 0,
                              "not_in_smartolt": 0}
        bt = by_tech[tid]
        bt["total"] += 1
        if it.get("match"):
            bt["match"] += 1
        elif it.get("reason") == "mismatch":
            bt["mismatch"] += 1
        elif it.get("reason") == "not_in_smartolt":
            bt["not_in_smartolt"] += 1
    # Calcula taxa de mismatch e ordena
    for bt in by_tech.values():
        bt["mismatch_rate"] = round(bt["mismatch"] / bt["total"] * 100, 1) \
            if bt["total"] else 0
    tech_summary = sorted(by_tech.values(),
                              key=lambda x: -x["mismatch_rate"])

    return {
        "items": items,
        "total": len(items),
        "days": days,
        "by_technician": tech_summary,
        "total_match": sum(1 for it in items if it.get("match")),
        "total_mismatch": sum(1 for it in items
                                  if it.get("reason") == "mismatch"),
        "total_not_in_smartolt": sum(1 for it in items
                                          if it.get("reason") == "not_in_smartolt"),
    }



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
    try:
        from phone_normalizer import get_phone_lookup_variants
        variants = get_phone_lookup_variants(phone) or [phone]
    except Exception:
        variants = [phone]
    sub_phone = await db.subscriber_phones.find_one(
        {"normalized_number": {"$in": variants}},
        {"_id": 0, "subscriber_id": 1, "company_id": 1},
    )
    if not sub_phone:
        return {"found": False, "diagnosis":
                "Cliente não encontrado no SmartOLT. Vou abrir um atendimento "
                "técnico pra investigar do zero."}
    cid = sub_phone.get("company_id")
    sub_id = sub_phone.get("subscriber_id")
    sub = await db.subscribers.find_one(
        {"id": sub_id}, {"_id": 0, "name": 1, "pppoe": 1, "pppoe_user": 1,
                          "external_code": 1},
    )
    if not sub:
        return {"found": False, "diagnosis":
                "Cadastro do cliente não encontrado."}
    norm_name = _norm(sub.get("name") or "")
    norm_pppoe = _norm(sub.get("pppoe") or sub.get("pppoe_user") or
                          sub.get("external_code") or "")
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
@router.post("/onus/{external_id}/refresh-mac")
async def refresh_onu_mac(external_id: str,
                              user: dict = Depends(require_role("gestor", "tecnico",
                                                                  "auditor"))):
    """Busca o MAC de uma ONU específica via SmartOLT (consulta per-ONU).

    A API bulk (`/onu/get_all_onus_details`) NÃO retorna o MAC — só o SN.
    Aqui usamos `/onu/get_onu_running_config/{external_id}` (que retorna
    config completa, incluindo MAC) e persistimos o resultado no cache
    local. Idempotente — chamadas seguintes só rotear o doc atualizado.

    Custo: 1 chamada da API SmartOLT (limite global 1000/h por empresa).
    Use de forma esparsa — geralmente uma vez por ONU é suficiente.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    if not cfg.enabled or not cfg.subdomain or not cfg.api_key:
        raise HTTPException(400, "SmartOLT desabilitado ou não configurado.")
    # Tenta primeiro o endpoint mais leve (running_config) e cai pra
    # full_status_info se o servidor não responder.
    endpoints = [
        f"/onu/get_onu_running_config/{external_id}",
        f"/onu/get_onu_full_status_info/{external_id}",
        f"/onu/get_onu_details/{external_id}",
    ]
    raw = None
    last_err = None
    for ep in endpoints:
        try:
            data = await _http_get(cfg, ep)
            if data.get("status"):
                raw = data
                break
        except HTTPException:
            raise
        except Exception as e:
            last_err = str(e)
    if raw is None:
        raise HTTPException(502, f"SmartOLT não retornou ONU. Último erro: {last_err}")
    # Extração heurística do MAC em vários formatos comuns
    blob = raw.get("response") or raw.get("config") or raw.get("onu") or raw
    mac = None
    if isinstance(blob, dict):
        mac = (blob.get("ont_mac") or blob.get("mac")
                 or blob.get("mac_address") or blob.get("device_mac"))
        # ZTE às vezes aninha em `lan_info` ou similar
        if not mac:
            for key in ("device", "info", "status", "wan", "lan"):
                sub = blob.get(key)
                if isinstance(sub, dict):
                    mac = (sub.get("mac") or sub.get("ont_mac")
                            or sub.get("mac_address"))
                    if mac:
                        break
    elif isinstance(blob, list):
        # algumas APIs retornam linhas de tabela
        for line in blob:
            if not isinstance(line, str):
                continue
            m = re.search(r"\b([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\b", line)
            if m:
                mac = m.group(1)
                break
    if not mac:
        # Procura em qualquer texto livre na resposta
        import json as _json  # noqa: PLC0415
        txt = _json.dumps(raw, default=str)
        m = re.search(
            r"\b([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\b", txt)
        if m:
            mac = m.group(1)
    if not mac:
        return {"ok": False, "external_id": external_id,
                "msg": "MAC não encontrado na resposta da SmartOLT.",
                "raw_keys": list(raw.keys()) if isinstance(raw, dict) else None}
    mac_norm = mac.upper().strip()
    await db.smartolt_onus.update_one(
        {"company_id": cid, "unique_external_id": external_id},
        {"$set": {"mac": mac_norm, "mac_fetched_at": now_iso()}},
    )
    return {"ok": True, "external_id": external_id, "mac": mac_norm}


@router.post("/onus/refresh-mac-batch")
async def refresh_macs_batch(
    limit: int = Query(50, ge=1, le=100,
        description="Quantas ONUs sem MAC processar nesta chamada"),
    user: dict = Depends(require_role("gestor", "auditor")),
):
    """Pega N ONUs sem MAC e tenta resolver. Cada doc = 1 chamada SmartOLT.

    Útil para preencher o cache aos poucos respeitando o budget.
    Chame periodicamente (1x por hora idealmente) até cobrir o parque.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    if not cfg.enabled or not cfg.subdomain or not cfg.api_key:
        raise HTTPException(400, "SmartOLT desabilitado ou não configurado.")
    pending = await db.smartolt_onus.find(
        {"company_id": cid, "status": "Online",
         "$or": [{"mac": None}, {"mac": ""}, {"mac": {"$exists": False}}]},
        {"_id": 0, "unique_external_id": 1, "name": 1},
    ).sort("synced_at", -1).limit(limit).to_list(limit)
    if not pending:
        return {"ok": True, "scanned": 0, "resolved": 0, "missing": 0}
    resolved = 0
    missing = 0
    errors: List[str] = []
    for o in pending:
        ext = o.get("unique_external_id")
        if not ext:
            continue
        try:
            r = await refresh_onu_mac(ext, user)
            if r.get("ok"):
                resolved += 1
            else:
                missing += 1
        except HTTPException as e:
            # 429 = rate-limit → para o batch
            if e.status_code == 429:
                errors.append("rate-limit")
                break
            missing += 1
            errors.append(str(e.detail)[:60])
        except Exception as e:
            missing += 1
            errors.append(str(e)[:60])
    return {"ok": True, "scanned": len(pending),
            "resolved": resolved, "missing": missing,
            "errors": errors[:5]}


@router.get("/onus/by-vlan/{vlan}")
async def list_onus_by_vlan(
    vlan: int,
    user: dict = Depends(require_role("gestor")),
):
    """Lista ONUs/ONTs cuja VLAN dos service_ports == {vlan}.

    A SmartOLT API NÃO tem endpoint nativo `get_by_vlan`. Estratégia:
      1. Chama /onu/get_all_onus_details (mesmo endpoint usado no sync).
      2. Filtra ONUs cujo service_ports[*].vlan == vlan (em string ou int).

    iter183 — Fallback CACHE: se SmartOLT estiver indisponível (rate-limit
    429, timeout, 5xx), retornamos a última lista sincronizada (collection
    `smartolt_onus` populada pelo sync a cada 15min). Marca `source` no
    payload pra UI mostrar badge "CACHE" em vez de "LIVE".
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    if not cfg.enabled or not cfg.subdomain or not cfg.api_key:
        raise HTTPException(400, "SmartOLT desabilitado ou não configurado.")
    target = str(vlan)
    live_error: Optional[str] = None
    try:
        data = await _http_get(cfg, "/onu/get_all_onus_details")
    except HTTPException as he:
        # Rate-limit ou config issue → cair pro cache
        if he.status_code == 429:
            live_error = str(he.detail)[:120]
            data = None
        else:
            raise
    except httpx.HTTPStatusError as e:
        live_error = f"HTTP {e.response.status_code}"
        data = None
    except Exception as e:
        live_error = f"{type(e).__name__}: {e}"[:120]
        data = None

    if data is None:
        # === FALLBACK CACHE ===
        cached = await db.smartolt_onus.find(
            {"company_id": cid, "vlan": target},
            {"_id": 0},
        ).to_list(2000)
        if not cached:
            # Tenta busca permissiva no campo service_ports
            cached = await db.smartolt_onus.find(
                {"company_id": cid,
                 "$or": [{"vlan": vlan}, {"vlan": target}]},
                {"_id": 0},
            ).to_list(2000)
        onus_norm = []
        for o in cached:
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
                "signal_text": o.get("signal_text") or o.get("signal") or "",
                "vlan": str(o.get("vlan") or vlan),
            })
        return {
            "vlan": vlan,
            "count": len(onus_norm),
            "total_scanned": len(onus_norm),
            "source": "smartolt_cache",
            "onus": onus_norm,
            "live_error": live_error,
            "cache_warning": "Dados do último sync (até 15min atrás). "
                                "SmartOLT temporariamente indisponível.",
        }

    onus_raw = data.get("onus") or []
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
                                force: bool = False,
                                user: dict = Depends(require_role("gestor"))):
    """Retorna sinal vivo da ONU. Usa cache local com TTL configurado.

    Se cache estiver fresco (< signal_cache_seconds), retorna direto. Caso
    contrário, consulta a SmartOLT, atualiza o cache e retorna.

    `force=true` (iter215): bypassa o cache TTL E o circuit-breaker local de
    rate-limit. Usado pelo botão "Live" quando o usuário pede atualização
    explícita do sinal. Se SmartOLT responder 403/429, marca rate-limit
    novamente — sem prejuízo.
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
    if fresh and not force:
        return {"cached": True, "onu": onu}
    # Busca live
    if not cfg.enabled or not cfg.subdomain or not cfg.api_key:
        return {"cached": True, "onu": onu, "warning": "smartolt_disabled"}
    # iter215: force=True limpa o circuit-breaker local pra dar uma nova chance.
    if force:
        await db.smartolt_config.update_one(
            {"company_id": cid}, {"$unset": {"rate_limited_until": 1}},
        )
        # iter215ap — Botão Live agora ZERA o cache da OLT/ONU antes de
        # buscar de novo. Se a SmartOLT responder com sinal válido, os
        # campos voltam preenchidos. Se vier LOS/400, ficam None pra UI
        # mostrar "sem leitura" honesto (sem valor velho enganoso).
        await db.smartolt_onus.update_one(
            {"company_id": cid, "unique_external_id": external_id},
            {"$set": {
                "signal_text": None,
                "signal_1310": None,
                "signal_1490": None,
                "status": None,
                "last_status_change": None,
                "signal_synced_at": None,
                "live_cleared_at": now_iso(),
            }},
        )
        # Atualiza o dict local também pra resposta refletir o estado limpo
        for k in ("signal_text", "signal_1310", "signal_1490", "status",
                   "last_status_change", "signal_synced_at"):
            onu[k] = None
    recovered = False
    try:
        sig = await _http_get(cfg, f"/onu/get_onu_signal/{external_id}")
        st = await _http_get(cfg, f"/onu/get_onu_status/{external_id}")
    except Exception as e:
        emsg = str(e)
        is_400 = ("400" in emsg) or ("Bad Request" in emsg)
        # iter215as — Cache pode estar com external_id/SN ANTIGOS (cliente
        # trocou de ONU fisicamente). Em 400 + force, fazemos bulk lookup
        # pelo `name` (PPPoE) e atualizamos o cache local com o ONU atual.
        if is_400 and force and onu.get("name"):
            try:
                bulk = await _http_get(cfg, "/onu/get_all_onus_details")
                items = (bulk or {}).get("response") or []
                target_name_norm = _norm(onu.get("name"))
                new = None
                for it in items:
                    if _norm(it.get("name")) == target_name_norm:
                        new = it
                        break
                if new and new.get("unique_external_id") != external_id:
                    new_ext = str(new.get("unique_external_id") or "")
                    new_sn = str(new.get("sn") or "")
                    logger.info(
                        "[smartolt] cache stale: name=%s old_ext=%s "
                        "new_ext=%s old_sn=%s new_sn=%s — atualizando",
                        onu.get("name"), external_id, new_ext,
                        onu.get("sn"), new_sn,
                    )
                    await db.smartolt_onus.update_one(
                        {"company_id": cid,
                         "unique_external_id": external_id},
                        {"$set": {
                            "unique_external_id": new_ext,
                            "sn": new_sn,
                            "olt_id": new.get("olt_id"),
                            "olt_name": new.get("olt_name"),
                            "board": new.get("board"),
                            "port": new.get("port"),
                            "onu": new.get("onu"),
                            "onu_type": new.get("onu_type"),
                            "status": new.get("status"),
                            "cache_recovered_at": now_iso(),
                            "previous_external_id": external_id,
                            "previous_sn": onu.get("sn"),
                        }},
                    )
                    try:
                        sig = await _http_get(
                            cfg, f"/onu/get_onu_signal/{new_ext}")
                        st = await _http_get(
                            cfg, f"/onu/get_onu_status/{new_ext}")
                        onu["unique_external_id"] = new_ext
                        onu["sn"] = new_sn
                        external_id = new_ext
                        recovered = True
                    except Exception as _re:
                        logger.warning(
                            "[smartolt] retry após recovery falhou: %s",
                            _re)
            except Exception as _be:
                logger.warning(
                    "[smartolt] bulk recovery falhou: %s", _be)
        if not recovered:
            current_status = (onu.get("status") or "").upper()
            is_los = ("LOS" in current_status
                       or "OFFLINE" in current_status
                       or "DYINGGASP" in current_status)
            if is_400 and force:
                friendly = (
                    "Sem leitura: SmartOLT recusou o request. Cache foi "
                    "limpo e tentamos resolver pelo nome — mas não "
                    "encontramos esse ONU no SmartOLT agora. Pode ser "
                    "LOS/offline ou foi removido da OLT."
                )
            elif is_400 and is_los:
                friendly = (
                    "ONU em LOS/offline — SmartOLT não consegue ler "
                    "sinal ao vivo. Sem leitura disponível."
                )
            elif is_400:
                friendly = (
                    "SmartOLT recusou o request (400). Provavelmente a "
                    "ONU está em LOS ou ainda não foi ativada."
                )
            else:
                friendly = f"live_fetch_failed: {emsg.splitlines()[0][:160]}"
            return {"cached": True, "onu": onu, "warning": friendly,
                    "live_error": {"is_los": is_los, "is_400": is_400,
                                      "cleared": bool(force),
                                      "recovered": False,
                                      "message": emsg[:300]}}
    sig_resp = sig.get("response") or {}
    st_resp = st.get("response") or {}
    update = {
        "signal_text": sig_resp.get("signal"),
        "signal_1310": sig_resp.get("signal_1310"),
        "signal_1490": sig_resp.get("signal_1490"),
        "status": st_resp.get("status"),
        "last_status_change": st_resp.get("last_status_change"),
        "signal_synced_at": now_iso(),
    }
    await db.smartolt_onus.update_one(
        {"company_id": cid, "unique_external_id": external_id}, {"$set": update},
    )
    onu.update(update)
    resp = {"cached": False, "onu": onu}
    # iter215as — sinaliza pro frontend se o cache foi recuperado (SN/ext
    # mudaram porque a ONU foi trocada fisicamente).
    if recovered:
        resp["cache_recovered"] = True
        resp["recovery_note"] = (
            f"ONU foi trocada — cache atualizado para SN {onu.get('sn')}"
        )
    return resp


@router.get("/history/kpis")
async def smartolt_history_kpis(
    user: dict = Depends(get_current_user),
):
    """iter215au — KPIs profissionais do histórico SmartOLT.

    Segue boas práticas FTTH/GPON (TM Forum + FTTH Council):
      • Inventário (total, online, LOS, power-off)
      • Crescimento líquido (criadas - removidas) últimos 30d
      • Trocas detectadas no mês (via swap_detected_at)
      • MTBF estimado (dias entre authorization_date e swap_detected_at)
      • Sinal médio downstream (1490nm) — saúde da rede
      • % em LOS — indicador de degradação
      • Top fornecedores por SN prefix (reliability ranking)
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    cutoff_30d = (now - timedelta(days=30)).isoformat()
    # Inventário básico
    total = await db.smartolt_onus.count_documents({"company_id": cid})
    online = await db.smartolt_onus.count_documents(
        {"company_id": cid, "status": {"$regex": "online", "$options": "i"}})
    los_count = await db.smartolt_onus.count_documents(
        {"company_id": cid,
         "status": {"$regex": "LOS|DyingGasp|offline", "$options": "i"}})
    poweroff = await db.smartolt_onus.count_documents(
        {"company_id": cid,
         "status": {"$regex": "power", "$options": "i"}})
    # Trocas (swap_detected_at presente)
    swaps_total = await db.smartolt_onus.count_documents(
        {"company_id": cid, "swap_detected_at": {"$exists": True}})
    swaps_30d = await db.smartolt_onus.count_documents(
        {"company_id": cid, "swap_detected_at": {"$gte": cutoff_30d}})
    # Novos cadastros via reconcile últimos 30d
    new_30d = await db.smartolt_onus.count_documents(
        {"company_id": cid, "created_via_reconcile_at": {"$gte": cutoff_30d}})
    # Sinal médio (downstream 1490nm) — só ONUs online com sinal numérico
    pipeline = [
        {"$match": {"company_id": cid, "signal_1490": {"$ne": None}}},
        {"$project": {"signal_num": {
            "$convert": {"input": "$signal_1490", "to": "double",
                          "onError": None, "onNull": None}}}},
        {"$match": {"signal_num": {"$ne": None}}},
        {"$group": {"_id": None,
                    "avg": {"$avg": "$signal_num"},
                    "min": {"$min": "$signal_num"},
                    "max": {"$max": "$signal_num"}}},
    ]
    agg = await db.smartolt_onus.aggregate(pipeline).to_list(1)
    signal_stats = agg[0] if agg else {"avg": None, "min": None, "max": None}
    # MTBF — avg dias entre authorization_date e swap_detected_at
    swaps_with_dates = await db.smartolt_onus.find(
        {"company_id": cid,
         "swap_detected_at": {"$exists": True},
         "authorization_date": {"$exists": True, "$ne": None}},
        {"_id": 0, "authorization_date": 1, "swap_detected_at": 1},
    ).to_list(2000)
    mtbf_days = None
    if swaps_with_dates:
        deltas: List[float] = []
        for s in swaps_with_dates:
            try:
                auth_str = s["authorization_date"]
                # Pode vir "06-Jun-2026 11:56:22" do SmartOLT — tentamos
                # vários formatos
                ad: Optional[datetime] = None
                for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
                             "%Y-%m-%dT%H:%M:%S"):
                    try:
                        ad = datetime.strptime(str(auth_str)[:25], fmt)
                        break
                    except Exception:
                        continue
                if not ad:
                    continue
                sd_str = s["swap_detected_at"]
                sd = datetime.fromisoformat(
                    sd_str.replace("Z", "+00:00"))
                if sd.tzinfo is None:
                    sd = sd.replace(tzinfo=timezone.utc)
                if ad.tzinfo is None:
                    ad = ad.replace(tzinfo=timezone.utc)
                deltas.append((sd - ad).total_seconds() / 86400.0)
            except Exception:
                continue
        if deltas:
            mtbf_days = round(sum(deltas) / len(deltas), 1)
    # Top fornecedores (prefixo do SN — 4 chars)
    vendor_map = {
        "ALCL": "Nokia/Alcatel",
        "HWTC": "Huawei",
        "ZTEG": "ZTE",
        "CMSZ": "ZTE (rebrand)",
        "FHTT": "Fiberhome",
        "ITBS": "Intelbras",
        "GPON": "Genérico",
    }
    pipeline_v = [
        {"$match": {"company_id": cid, "sn": {"$ne": None,
                                                "$type": "string"}}},
        {"$project": {"prefix": {"$toUpper": {"$substr": ["$sn", 0, 4]}},
                       "status": 1}},
        {"$group": {"_id": "$prefix", "count": {"$sum": 1},
                    "los": {"$sum": {"$cond": [
                        {"$regexMatch": {"input": {"$ifNull": ["$status", ""]},
                                            "regex": "LOS|offline|DyingGasp",
                                            "options": "i"}},
                        1, 0]}}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    vendors_raw = await db.smartolt_onus.aggregate(pipeline_v).to_list(10)
    vendors = []
    for v in vendors_raw:
        c = v.get("count") or 0
        los = v.get("los") or 0
        vendors.append({
            "prefix": v["_id"],
            "vendor": vendor_map.get((v["_id"] or "").upper(),
                                       "Desconhecido"),
            "count": c,
            "los": los,
            "los_pct": round((los / c) * 100, 1) if c else 0,
        })
    # Saúde geral (health score 0-100)
    health_score = 100
    if total > 0:
        los_pct = (los_count / total) * 100
        health_score = max(0, round(100 - los_pct * 1.5, 0))
    return {
        "inventory": {
            "total": total,
            "online": online,
            "los": los_count,
            "poweroff": poweroff,
            "online_pct": round((online / total) * 100, 1) if total else 0,
            "los_pct": round((los_count / total) * 100, 1) if total else 0,
        },
        "lifecycle": {
            "swaps_total": swaps_total,
            "swaps_30d": swaps_30d,
            "new_30d": new_30d,
            "net_growth_30d": new_30d - swaps_30d,
            "mtbf_days": mtbf_days,
            "swap_rate_monthly_pct": (
                round((swaps_30d / total) * 100, 2) if total else 0),
        },
        "signal": {
            "avg_1490_dbm": (round(signal_stats["avg"], 2)
                              if signal_stats.get("avg") else None),
            "min_1490_dbm": (round(signal_stats["min"], 2)
                              if signal_stats.get("min") else None),
            "max_1490_dbm": (round(signal_stats["max"], 2)
                              if signal_stats.get("max") else None),
        },
        "vendors": vendors,
        "health_score": health_score,
        "as_of": now.isoformat(),
    }


@router.get("/history/swaps")
async def smartolt_history_swaps(
    days: int = 30, limit: int = 200,
    user: dict = Depends(get_current_user),
):
    """iter215au — Lista de trocas detectadas (swap_detected_at) com
    cliente, ONU antiga e nova, fornecedor inferido."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    items = await db.smartolt_onus.find(
        {"company_id": cid,
         "swap_detected_at": {"$gte": cutoff}},
        {"_id": 0, "name": 1, "sn": 1, "previous_sn": 1,
         "unique_external_id": 1, "previous_external_id": 1,
         "olt_name": 1, "board": 1, "port": 1, "onu": 1,
         "swap_detected_at": 1, "status": 1, "authorization_date": 1,
         "onu_type": 1, "zone_name": 1},
    ).sort("swap_detected_at", -1).limit(limit).to_list(limit)

    def _vendor(sn: str | None) -> str:
        if not sn or len(sn) < 4:
            return "?"
        p = sn[:4].upper()
        return {"ALCL": "Nokia/Alcatel", "HWTC": "Huawei",
                 "ZTEG": "ZTE", "CMSZ": "ZTE", "FHTT": "Fiberhome",
                 "ITBS": "Intelbras"}.get(p, p)

    for it in items:
        it["vendor_new"] = _vendor(it.get("sn"))
        it["vendor_old"] = _vendor(it.get("previous_sn"))
        it["vendor_changed"] = it["vendor_new"] != it["vendor_old"]
    return {"items": items, "count": len(items), "days": days}


@router.get("/history/timeseries")
async def smartolt_history_timeseries(
    days: int = 30,
    user: dict = Depends(get_current_user),
):
    """iter215au — Série temporal de trocas detectadas/dia (chart)."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    pipeline = [
        {"$match": {"company_id": cid,
                     "swap_detected_at": {"$gte": cutoff}}},
        {"$project": {"day": {"$substr": ["$swap_detected_at", 0, 10]}}},
        {"$group": {"_id": "$day", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    docs = await db.smartolt_onus.aggregate(pipeline).to_list(days + 5)
    return {"items": [{"date": d["_id"], "swaps": d["count"]}
                       for d in docs],
            "days": days}


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


@router.post("/onus/reconcile")
async def reconcile_onus_swap(
    user: dict = Depends(require_role("gestor")),
):
    """iter215at — Reconciliação de cache pós-troca de ONT.

    Faz bulk `/onu/get_all_onus_details` no SmartOLT, compara com
    `smartolt_onus` local pelo `name` (PPPoE) e detecta ONUs trocadas
    (mesmo nome, SN ou external_id diferente). Atualiza o cache local
    em batch e retorna o resumo: quantas trocadas, novas, removidas.
    """
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    if not cfg.enabled or not cfg.subdomain or not cfg.api_key:
        raise HTTPException(400, "SmartOLT não configurado para a empresa.")
    try:
        bulk = await _http_get(cfg, "/onu/get_all_onus_details")
    except Exception as e:
        raise HTTPException(502, f"Falha ao consultar SmartOLT: {e}")
    items = (bulk or {}).get("response") or []
    if not isinstance(items, list):
        raise HTTPException(502, "Resposta SmartOLT inesperada.")
    # Indexa locais por name_norm
    local = await db.smartolt_onus.find(
        {"company_id": cid}, {"_id": 0},
    ).to_list(20000)
    by_name: Dict[str, Dict[str, Any]] = {}
    for lo in local:
        n = lo.get("name_norm") or _norm(lo.get("name"))
        if n:
            by_name[n] = lo
    swapped: List[Dict[str, Any]] = []
    created = 0
    updated_meta = 0
    seen_ext: set = set()
    for it in items:
        nm = it.get("name")
        nn = _norm(nm)
        new_ext = str(it.get("unique_external_id") or "")
        new_sn = str(it.get("sn") or "")
        seen_ext.add(new_ext)
        loc = by_name.get(nn) if nn else None
        if not loc:
            # ONU nova no SmartOLT — insere
            await db.smartolt_onus.update_one(
                {"company_id": cid, "unique_external_id": new_ext},
                {"$set": {
                    "company_id": cid,
                    "unique_external_id": new_ext,
                    "name": nm, "name_norm": nn,
                    "sn": new_sn,
                    "olt_id": it.get("olt_id"),
                    "olt_name": it.get("olt_name"),
                    "board": it.get("board"),
                    "port": it.get("port"),
                    "onu": it.get("onu"),
                    "onu_type": it.get("onu_type"),
                    "status": it.get("status"),
                    "synced_at": now_iso(),
                    "created_via_reconcile_at": now_iso(),
                }},
                upsert=True,
            )
            created += 1
            continue
        old_ext = str(loc.get("unique_external_id") or "")
        old_sn = str(loc.get("sn") or "")
        if new_ext != old_ext or new_sn != old_sn:
            # ONU TROCADA — atualiza
            await db.smartolt_onus.update_one(
                {"company_id": cid, "unique_external_id": old_ext},
                {"$set": {
                    "unique_external_id": new_ext,
                    "sn": new_sn,
                    "olt_id": it.get("olt_id"),
                    "olt_name": it.get("olt_name"),
                    "board": it.get("board"),
                    "port": it.get("port"),
                    "onu": it.get("onu"),
                    "onu_type": it.get("onu_type"),
                    "status": it.get("status"),
                    "synced_at": now_iso(),
                    "swap_detected_at": now_iso(),
                    "previous_external_id": old_ext,
                    "previous_sn": old_sn,
                    # Zera sinal — força nova leitura na próxima
                    "signal_text": None,
                    "signal_1310": None,
                    "signal_1490": None,
                    "signal_synced_at": None,
                }},
            )
            swapped.append({
                "name": nm,
                "old_external_id": old_ext,
                "new_external_id": new_ext,
                "old_sn": old_sn,
                "new_sn": new_sn,
            })
        else:
            # Mesmo ext_id e SN — só atualiza metadados/status
            await db.smartolt_onus.update_one(
                {"company_id": cid, "unique_external_id": new_ext},
                {"$set": {
                    "olt_id": it.get("olt_id"),
                    "olt_name": it.get("olt_name"),
                    "board": it.get("board"),
                    "port": it.get("port"),
                    "onu": it.get("onu"),
                    "onu_type": it.get("onu_type"),
                    "status": it.get("status"),
                    "synced_at": now_iso(),
                }},
            )
            updated_meta += 1
    # Detecta removidas (existem local, não vieram no bulk)
    local_exts = {str(lo.get("unique_external_id") or "") for lo in local}
    removed_exts = local_exts - seen_ext
    return {
        "ok": True,
        "summary": {
            "swapped": len(swapped),
            "created": created,
            "metadata_updated": updated_meta,
            "removed_count": len(removed_exts),
            "total_remote": len(items),
            "total_local_before": len(local),
        },
        "swapped_details": swapped[:50],
        "removed_external_ids": sorted(removed_exts)[:50],
        "ran_at": now_iso(),
    }


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


def _live_signal_summary(onu: dict, *,
                           ticket_relato: Optional[str] = None) -> dict:
    """Resumo compacto pro pill/UI da Lousa (não expõe campos pesados).

    iter182 — Sensibilidade aumentada:
    - Usa SOMENTE `signal_1490` (downstream OLT → cliente, valor real
      que o cliente experimenta). Não cai pra 1310nm (que é upstream e
      mascara leituras quando 1490 está vazio).
    - 5 faixas de qualidade (excelente / bom / atenção / crítico /
      falha) seguindo best practices FTTH 2026.

    P0-3/P0-4/P0-5 (OPERAÇÃO TICKET ARMADO 2026-02):
    - Calcula `cache_age_seconds` e `cache_label` ("LIVE · agora",
      "CACHE · há Xmin", "SEM LEITURA · última tentativa há Xmin").
    - Auto-classifica `classification` quando há relato:
        - "LOS_FISICO": ONU offline real
        - "ATENUACAO_CRITICA": Online + Rx entre -25 e -28 dBm
        - "SINAL_CRITICO": Online + Rx entre -28 e -30 dBm
        - "PROVAVEL_ROMPIMENTO": Rx < -30 dBm
        - "SAUDAVEL": Online + Rx > -25 dBm
    - Flag `generic_profile_alert` quando ONU usa profile "Generic_X".
    """
    rx = onu.get("signal_1490")  # só 1490nm; sem fallback p/ 1310
    rxf = None
    try:
        rxf = float(rx) if rx is not None else None
    except (TypeError, ValueError):
        rxf = None
    # P0-3: fallback para 1310 SOMENTE para classificar (não para badge UI)
    rx_secondary = None
    try:
        rx_secondary = (float(onu.get("signal_1310"))
                          if onu.get("signal_1310") is not None else None)
    except (TypeError, ValueError):
        rx_secondary = None
    rx_for_class = rxf if rxf is not None else rx_secondary

    quality = "unknown"
    if rxf is not None:
        if rxf >= -20:
            quality = "excellent"
        elif rxf >= -24:
            quality = "good"
        elif rxf >= -27:
            quality = "warn"
        elif rxf >= -28:
            quality = "critical"
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
    # P0-3/P0-5 (OPERAÇÃO TICKET ARMADO): timestamp e idade do cache
    from datetime import datetime, timezone
    sync_ts = onu.get("signal_synced_at") or onu.get("synced_at")
    cache_age_seconds = None
    cache_label = "SEM LEITURA"
    cache_freshness = "unknown"  # live | fresh | stale | very_stale | none
    if sync_ts:
        try:
            ts = str(sync_ts).strip().replace("Z", "+00:00")
            if " " in ts and "T" not in ts:
                ts = ts.replace(" ", "T", 1)
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            cache_age_seconds = int(
                (datetime.now(timezone.utc) - dt).total_seconds())
        except (ValueError, TypeError):
            cache_age_seconds = None
    if cache_age_seconds is not None:
        if cache_age_seconds < 60:
            cache_label = "LIVE · agora"
            cache_freshness = "live"
        elif cache_age_seconds < 300:
            cache_label = f"LIVE · há {cache_age_seconds // 60}min"
            cache_freshness = "live"
        elif cache_age_seconds < 3600:
            cache_label = f"CACHE · há {cache_age_seconds // 60}min"
            cache_freshness = "fresh"
        elif cache_age_seconds < 6 * 3600:
            cache_label = f"CACHE · há {cache_age_seconds // 3600}h"
            cache_freshness = "stale"
        elif cache_age_seconds < 86400:
            cache_label = f"CACHE · há {cache_age_seconds // 3600}h"
            cache_freshness = "very_stale"
        else:
            cache_label = f"CACHE · há {cache_age_seconds // 86400}d"
            cache_freshness = "very_stale"
    elif onu.get("live_cleared_at"):
        # Tentamos Live mas SmartOLT retornou nada
        try:
            ts = str(onu["live_cleared_at"]).replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
            age = int((datetime.now(timezone.utc) - dt).total_seconds())
            cache_label = (f"SEM LEITURA · última tentativa "
                            f"há {age // 60}min" if age >= 60
                            else "SEM LEITURA · acabou de tentar")
            cache_freshness = "none"
        except (ValueError, TypeError):
            pass

    # P0-4 (OPERAÇÃO TICKET ARMADO): auto-classificação de Atenuação Crítica
    classification = None
    classification_reason = None
    status_norm = (onu.get("status") or "").upper()
    relato_los = False
    if ticket_relato:
        import re as _re
        relato_los = bool(_re.search(
            r"\b(LOS|sem\s+conex|sem\s+sinal|sem\s+internet|sem\s+net|caiu|offline)\b",
            ticket_relato, _re.IGNORECASE))
    if status_norm == "LOS" or "OFFLINE" in status_norm or "POWER" in status_norm:
        classification = "LOS_FISICO"
        classification_reason = f"ONU em estado {onu.get('status')} no SmartOLT."
    elif status_norm == "ONLINE" and rx_for_class is not None:
        if rx_for_class < -30:
            classification = "PROVAVEL_ROMPIMENTO"
            classification_reason = (
                f"Rx {rx_for_class:.2f} dBm < -30 dBm. "
                f"Provável rompimento, conector queimado ou alta perda.")
        elif rx_for_class <= -28:
            classification = "SINAL_CRITICO"
            classification_reason = (
                f"Rx {rx_for_class:.2f} dBm entre -28 e -30 dBm "
                f"com ONU online. Sinal crítico.")
        elif rx_for_class <= -25:
            classification = ("ATENUACAO_CRITICA" if relato_los
                              else "ATENUACAO_MARGINAL")
            classification_reason = (
                f"Rx {rx_for_class:.2f} dBm entre -25 e -28 dBm "
                f"com ONU online. "
                + ("Relato menciona LOS — não é LOS físico, é atenuação."
                   if relato_los
                   else "Atenuação marginal — risco de degradação."))
        else:
            classification = "SAUDAVEL"
            classification_reason = (
                f"Rx {rx_for_class:.2f} dBm com ONU online — saudável.")

    # P0-6: flag de profile genérico
    profile_name = (onu.get("onu_type_name") or "")
    generic_profile_alert = False
    if "GENERIC" in profile_name.upper() or "GENÉRICO" in profile_name.upper():
        generic_profile_alert = True

    return {
        "external_id": onu.get("unique_external_id"),
        "name": onu.get("name"),
        "rx_dbm": rxf,
        "rx_secondary_1310": rx_secondary,
        "signal_text": onu.get("signal_text"),
        "status": onu.get("status"),
        "quality": quality,
        "olt_name": onu.get("olt_name"),
        "olt_port": olt_port,         # "1/10"
        "board": board, "port": port, "onu": onu_id,
        "sn": onu.get("sn"),
        "mac": (onu.get("mac") or onu.get("ont_mac") or None),  # iter180
        "cto_box": cto_box,            # "CTO 1 10"
        "cto_port": cto_port,          # "01"
        "vlan": vlan,
        "uptime_human": uptime_human,  # "2d 14h" / "5h 32m" / "12m"
        "uptime_seconds": uptime_seconds,
        "last_status_change": last_change,
        "synced_at": onu.get("synced_at"),
        # P0-3/P0-5 — Operação Ticket Armado
        "cache_age_seconds": cache_age_seconds,
        "cache_label": cache_label,
        "cache_freshness": cache_freshness,  # live|fresh|stale|very_stale|none|unknown
        # P0-4
        "classification": classification,
        "classification_reason": classification_reason,
        # P0-6
        "onu_profile": profile_name or None,
        "generic_profile_alert": generic_profile_alert,
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
                # P0-4: passar relato pra auto-classificar atenuação
                _snap = tickets[i].get("client_snapshot") or {}
                _relato = (_snap.get("relato") or tickets[i].get("relato")
                            or tickets[i].get("admin_notes") or "")
                tickets[i]["live_signal"] = _live_signal_summary(
                    onu, ticket_relato=_relato)
        # iter182 — Fallback via Base de Portas: para os tickets que NÃO
        # casaram com SmartOLT (live_signal == null), busca a porta CTO
        # vinculada ao subscriber e cria um live_signal sintético a
        # partir do que está cacheado no `cto_ports`. Garante que o card
        # SEMPRE mostre alguma info de rede quando o cliente tem porta
        # designada.
        unmatched = [(i, tickets[i]) for i, _, _ in per_ticket
                     if not tickets[i].get("live_signal")]
        sub_ids = [t.get("subscriber_id") or t.get("client_id")
                   for _, t in unmatched if (t.get("subscriber_id")
                                              or t.get("client_id"))]
        if sub_ids:
            port_idx: Dict[str, dict] = {}
            async for p in db.cto_ports.find(
                {"company_id": company_id, "status": "occupied",
                 "subscriber_id": {"$in": sub_ids}},
                {"_id": 0},
            ):
                port_idx[p["subscriber_id"]] = p
            for i, t in unmatched:
                sid = t.get("subscriber_id") or t.get("client_id")
                if not sid or sid not in port_idx:
                    continue
                p = port_idx[sid]
                tickets[i]["live_signal"] = {
                    "rx_dbm": p.get("signal_dbm"),
                    "status": "—",
                    "olt_name": p.get("olt_name"),
                    "vlan": p.get("vlan"),
                    "cto_name": p.get("cto_name"),
                    "cto_port": p.get("port_number"),
                    "mac": p.get("mac"),
                    "sn": p.get("sn"),
                    "quality": "unknown",
                    "source": "cto_ports_fallback",
                }
        # iter180 — adiciona a média de sinal da VLAN do cliente
        # (mesmo OLT, mesma VLAN) para o gestor comparar individual vs rede.
        await _enrich_vlan_avg_for_tickets(tickets, company_id)
        # P0-6 (OPERAÇÃO TICKET ARMADO 2026-02): anexa alertas de
        # degradação ativos para cada ticket que tem live_signal.
        await _enrich_degradation_alerts(tickets, company_id)
    except Exception as e:
        logger.warning("[smartolt] enrich_tickets_with_live_signal falhou: %s", e)


async def _enrich_degradation_alerts(tickets: List[dict],
                                       company_id: str) -> None:
    """P0-6: anexa `degradation_alert` quando há queda detectada nos últimos
    72h para o `unique_external_id` da ONU do ticket.
    """
    from datetime import datetime, timezone, timedelta
    try:
        ext_ids: List[str] = []
        for t in tickets:
            ls = t.get("live_signal") or {}
            if ls.get("external_id"):
                ext_ids.append(ls["external_id"])
        if not ext_ids:
            return
        cutoff_72h = (datetime.now(timezone.utc) - timedelta(hours=72)
                       ).isoformat()
        idx: Dict[str, dict] = {}
        async for a in db.signal_degradation_alerts.find(
                {"company_id": company_id,
                 "unique_external_id": {"$in": ext_ids},
                 "detected_at": {"$gte": cutoff_72h}},
                {"_id": 0}).sort("detected_at", -1):
            ext = a.get("unique_external_id")
            if ext and ext not in idx:
                idx[ext] = a
        for t in tickets:
            ls = t.get("live_signal") or {}
            ext = ls.get("external_id")
            if not ext or ext not in idx:
                continue
            a = idx[ext]
            t["degradation_alert"] = {
                "detected_at": a.get("detected_at"),
                "avg_24h_rx_dbm": a.get("avg_24h_rx_dbm"),
                "current_rx_dbm": a.get("current_rx_dbm"),
                "delta_dbm": a.get("delta_dbm"),
                "samples_count": a.get("samples_count"),
                "status": a.get("status"),
                "resolved_at": a.get("resolved_at"),
                "resolved_delta_dbm": a.get("resolved_delta_dbm"),
            }
    except Exception as e:
        logger.warning("[smartolt] _enrich_degradation_alerts falhou: %s", e)


async def _enrich_vlan_avg_for_tickets(tickets: List[dict],
                                            company_id: str) -> None:
    """Para cada ticket que já tem `live_signal.olt_name` + `vlan`, computa
    a média de sinal de TODAS as ONUs Online dessa mesma combinação
    (olt + vlan) e anexa em `live_signal.vlan_avg_dbm` + `vlan_onu_count`.

    1 query agregada por chamada — eficiente.
    """
    keys: set = set()
    for t in tickets:
        ls = t.get("live_signal") or {}
        olt = ls.get("olt_name")
        vlan = ls.get("vlan")
        if olt and vlan:
            try:
                keys.add((olt, int(str(vlan).strip())))
            except Exception:
                pass
    if not keys:
        return
    olts = list({k[0] for k in keys})
    pipeline = [
        {"$match": {"company_id": company_id, "status": "Online",
                      "olt_name": {"$in": olts},
                      "signal_1490": {"$nin": [None, ""]}}},
        {"$unwind": "$service_ports"},
        {"$match": {"service_ports.vlan": {"$nin": [None, "", "0"]}}},
        {"$addFields": {
            "_vlan_int": {"$convert": {
                "input": "$service_ports.vlan", "to": "int",
                "onError": None, "onNull": None,
            }},
            "_sig_num": {"$convert": {
                "input": "$signal_1490", "to": "double",
                "onError": None, "onNull": None,
            }},
        }},
        {"$match": {"_vlan_int": {"$ne": None},
                      "_sig_num": {"$ne": None}}},
        {"$group": {
            "_id": {"olt": "$olt_name", "vlan": "$_vlan_int"},
            "avg": {"$avg": "$_sig_num"},
            "count": {"$sum": 1},
        }},
    ]
    stats: Dict[tuple, Dict[str, Any]] = {}
    async for row in db.smartolt_onus.aggregate(pipeline):
        k = (row["_id"]["olt"], row["_id"]["vlan"])
        if row.get("avg") is None:
            continue
        stats[k] = {"avg": round(float(row["avg"]), 1),
                     "count": int(row["count"])}
    for t in tickets:
        ls = t.get("live_signal") or {}
        olt = ls.get("olt_name")
        vlan = ls.get("vlan")
        if not (olt and vlan):
            continue
        try:
            k = (olt, int(str(vlan).strip()))
        except Exception:
            continue
        s = stats.get(k)
        if not s:
            continue
        ls["vlan_avg_dbm"] = s["avg"]
        ls["vlan_onu_count"] = s["count"]
        # Diff vs média: positivo = pior que a rede, negativo = melhor
        rx = ls.get("rx_dbm")
        if isinstance(rx, (int, float)):
            ls["vlan_diff_dbm"] = round(rx - s["avg"], 1)


# ---------------------------------------------------------------------------
# iter182 — Endpoint: lista alertas de degradação
# ---------------------------------------------------------------------------
@router.get("/signal-degradation")
async def list_signal_degradation(
    status: str = "active",
    limit: int = 50,
    user: dict = Depends(require_role("administrador", "gestor",
                                          "gestor_rede", "auditor",
                                          "supervisor")),
):
    """Lista alertas de degradação de sinal (piora ≥3 dBm em 24h).
    status: active | resolved | all
    """
    cid = user.get("company_id")
    filt = {"company_id": cid}
    if status != "all":
        filt["status"] = status
    items = []
    cursor = db.signal_degradation_alerts.find(filt, {"_id": 0})\
        .sort("detected_at", -1).limit(min(limit, 200))
    async for it in cursor:
        items.append(it)
    return {"items": items, "count": len(items)}


# ---------------------------------------------------------------------------
# iter182 — Detector de degradação de sinal (alerta -3 dBm em 24h)
# ---------------------------------------------------------------------------
SIGNAL_DEGRADATION_DELTA_DB = 3.0  # alerta se piora ≥ 3 dBm
SIGNAL_DEGRADATION_WINDOW_H = 24   # janela de 24h


async def _detect_signal_degradation(company_id: str, run_ts: str) -> None:
    """Varre ONUs após o sync e detecta degradação de sinal.

    Critério: o valor MAIS RECENTE de signal_1490 piorou em ≥ 3 dBm
    em relação à MÉDIA das amostras das últimas 24h (excluindo o atual).
    Cria/atualiza um doc em `signal_degradation_alerts` por ONU.
    """
    try:
        cursor = db.smartolt_onus.find(
            {"company_id": company_id,
             "signal_history_24h.0": {"$exists": True}},
            {"_id": 0, "unique_external_id": 1, "name": 1, "olt_name": 1,
             "signal_1490": 1, "signal_history_24h": 1, "status": 1},
        )
        new_alerts = 0
        resolved = 0
        async for onu in cursor:
            hist = onu.get("signal_history_24h") or []
            if len(hist) < 3:  # precisa de algumas amostras
                continue
            try:
                current = float(onu.get("signal_1490"))
            except (TypeError, ValueError):
                continue
            # Média das amostras anteriores (exclui a última)
            prev = [h["rx"] for h in hist[:-1]
                    if isinstance(h.get("rx"), (int, float))]
            if len(prev) < 2:
                continue
            avg_prev = sum(prev) / len(prev)
            delta = current - avg_prev  # negativo = pior (mais negativo)
            alert_key = {"company_id": company_id,
                            "unique_external_id": onu["unique_external_id"]}
            if delta <= -SIGNAL_DEGRADATION_DELTA_DB:
                # PIOROU significativamente: cria/atualiza alerta
                doc = {
                    "company_id": company_id,
                    "unique_external_id": onu["unique_external_id"],
                    "name": onu.get("name"),
                    "olt_name": onu.get("olt_name"),
                    "status": "active",
                    "current_rx_dbm": round(current, 2),
                    "avg_24h_rx_dbm": round(avg_prev, 2),
                    "delta_dbm": round(delta, 2),
                    "detected_at": run_ts,
                    "samples_count": len(hist),
                }
                r = await db.signal_degradation_alerts.update_one(
                    alert_key,
                    {"$set": doc, "$setOnInsert": {"created_at": run_ts}},
                    upsert=True,
                )
                if r.upserted_id:
                    new_alerts += 1
            else:
                # Sinal voltou ao normal: resolve alerta anterior se existia
                r = await db.signal_degradation_alerts.update_one(
                    {**alert_key, "status": "active"},
                    {"$set": {"status": "resolved",
                                 "resolved_at": run_ts,
                                 "resolved_rx_dbm": round(current, 2),
                                 "resolved_delta_dbm": round(delta, 2)}},
                )
                if r.modified_count:
                    resolved += 1
        if new_alerts or resolved:
            logger.info(
                "[smartolt] degradation cid=%s new=%s resolved=%s",
                company_id, new_alerts, resolved)
    except Exception as e:
        logger.warning("[smartolt] _detect_signal_degradation falhou: %s", e)


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
