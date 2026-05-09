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
    sync_interval_minutes: int = Field(default=240, ge=15, le=1440)  # 4h default
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


async def _http_get(cfg: SmartoltConfig, path: str) -> Dict[str, Any]:
    url = f"{_base_url(cfg)}{path}"
    async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
        r = await client.get(url, headers={"X-Token": cfg.api_key})
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Settings endpoints
# ---------------------------------------------------------------------------
@router.get("/settings")
async def get_settings(user: dict = Depends(require_role("gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cfg = await _get_config(cid)
    return _public(cfg)


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
# Lookup + signal
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Resolver para Lousa (chamado pelo lousa.py)
# ---------------------------------------------------------------------------
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
    return {
        "external_id": onu.get("unique_external_id"),
        "name": onu.get("name"),
        "rx_dbm": rxf,
        "signal_text": onu.get("signal_text"),
        "status": onu.get("status"),
        "quality": quality,
        "olt_name": onu.get("olt_name"),
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
                interval = cfg.sync_interval_minutes * 60
                if cid in last_run and (now - last_run[cid]) < interval:
                    continue
                last_run[cid] = now
                try:
                    res = await _do_sync(cid, cfg)
                    logger.info("[smartolt] worker sync %s — %s", cid, res)
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
