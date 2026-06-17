"""Pluto TV catalog adapter.

Pluto TV (ViacomCBS) publica catálogo de canais grátis com URL HLS direta.
Endpoint usado: `https://api.pluto.tv/v2/channels.json` — sem auth, JSON
público, 400+ canais agrupados por categoria.

Este serviço:
- Faz cache em memória (1h TTL) pra não martelar Pluto TV em cada request.
- Normaliza payload pra forma simples (id, name, number, category, logo,
  hls_url, summary).
- Filtra canais "diretos" / "dev only" (visibility hidden, plutoOfficeOnly).
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger("ponto.pluto_tv")

PLUTO_CHANNELS_URL = "https://api.pluto.tv/v2/channels.json"
PLUTO_BOOT_URL = "https://boot.pluto.tv/v4/start"
PLUTO_BASE_LOGO = "https:"  # logos vêm com URL relativa começando em //
CACHE_TTL_SECONDS = 3600
SESSION_TTL_SECONDS = 1800  # 30min — boot renova ~refreshInSec do response

_cache: Dict[str, Any] = {"ts": 0.0, "channels": []}
_session: Dict[str, Any] = {"ts": 0.0, "data": None}
_lock = asyncio.Lock()
_session_lock = asyncio.Lock()

_BOOT_PARAMS_STATIC = {
    "appName": "web",
    "appVersion": "5.106.0",
    "deviceVersion": "120.0",
    "deviceModel": "web",
    "deviceMake": "Chrome",
    "deviceType": "web",
    "serverSideAds": "false",
    "clientModelNumber": "1.0.0",
}


async def get_session(force: bool = False) -> Dict[str, Any]:
    """Faz boot na Pluto TV e devolve session dict com servers + stitcherParams + jwt.

    Pluto TV exige sessão válida pra autorizar o stitcher; sem isso,
    qualquer master.m3u8 devolve 400 Bad Request. Cacheamos 30min.
    """
    now = time.time()
    if not force and _session["data"] and now - _session["ts"] < SESSION_TTL_SECONDS:
        return _session["data"]
    async with _session_lock:
        now = time.time()
        if not force and _session["data"] and now - _session["ts"] < SESSION_TTL_SECONDS:
            return _session["data"]
        params = dict(_BOOT_PARAMS_STATIC)
        params["clientID"] = str(uuid.uuid4())
        try:
            async with httpx.AsyncClient(timeout=15.0, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://pluto.tv/",
                "Origin": "https://pluto.tv",
            }) as cli:
                r = await cli.get(PLUTO_BOOT_URL, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:
            log.warning("[pluto_tv] boot failed: %s", exc)
            if _session["data"]:
                return _session["data"]
            raise
        out = {
            "servers": data.get("servers", {}),
            "stitcher_params": data.get("stitcherParams", ""),
            "jwt": data.get("sessionToken", ""),
        }
        _session["data"] = out
        _session["ts"] = now
        log.info("[pluto_tv] session refreshed (stitcher=%s)",
                 out["servers"].get("stitcher", "?"))
        return out


async def build_stream_url(channel_id: str) -> Optional[str]:
    """Constrói a URL HLS válida pro canal (com sessão Pluto TV ativa)."""
    sess = await get_session()
    stitcher = (sess.get("servers") or {}).get("stitcher")
    if not stitcher:
        return None
    sp = sess.get("stitcher_params") or ""
    jwt = sess.get("jwt") or ""
    url = f"{stitcher}/stitch/hls/channel/{channel_id}/master.m3u8?{sp}"
    if jwt:
        url += f"&jwt={jwt}"
    return url


def _logo_url(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    if raw.startswith("//"):
        return PLUTO_BASE_LOGO + raw
    return raw


def _normalize_channel(c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if (c.get("visibility") or "everyone") != "everyone":
        return None
    # `plutoOfficeOnly` = canal interno só pro dev/staff da Pluto. Esses sim
    # filtramos. `directOnly` é só uma flag de afiliado — não bloqueia uso
    # do stream direto.
    if c.get("plutoOfficeOnly"):
        return None
    stitched = (c.get("stitched") or {}).get("urls") or []
    hls = next((u.get("url") for u in stitched if u.get("type") == "hls"), None)
    if not hls:
        return None
    return {
        "id": c.get("_id") or c.get("slug"),
        "slug": c.get("slug"),
        "name": c.get("name"),
        "number": c.get("number"),
        "category": c.get("category") or "Outros",
        "summary": c.get("summary") or "",
        "logo": _logo_url(((c.get("logo") or {}).get("path"))
                            or ((c.get("colorLogoPNG") or {}).get("path"))),
        "thumbnail": _logo_url(((c.get("thumbnail") or {}).get("path"))),
        "tile": _logo_url(((c.get("tile") or {}).get("path"))),
        "hls_url": hls,
    }


async def fetch_channels(force: bool = False) -> List[Dict[str, Any]]:
    """Retorna lista normalizada de canais Pluto TV (cache de 1h)."""
    now = time.time()
    if (not force) and _cache["channels"] and (now - _cache["ts"] < CACHE_TTL_SECONDS):
        return _cache["channels"]

    async with _lock:
        # double-check após adquirir o lock
        now = time.time()
        if (not force) and _cache["channels"] and (now - _cache["ts"] < CACHE_TTL_SECONDS):
            return _cache["channels"]
        try:
            async with httpx.AsyncClient(timeout=15.0, headers={
                "User-Agent": "Mozilla/5.0 LigoTV/1.0",
                "Accept": "application/json",
            }) as cli:
                r = await cli.get(PLUTO_CHANNELS_URL)
                r.raise_for_status()
                raw = r.json()
        except Exception as exc:
            log.warning("[pluto_tv] fetch failed: %s — devolvendo cache antigo", exc)
            return _cache["channels"]
        out: List[Dict[str, Any]] = []
        for c in raw if isinstance(raw, list) else []:
            n = _normalize_channel(c)
            if n:
                out.append(n)
        out.sort(key=lambda x: (x["category"], x["number"] or 9999))
        _cache["channels"] = out
        _cache["ts"] = now
        log.info("[pluto_tv] catalog refreshed: %d channels", len(out))
        return out


def categories(channels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Conta canais por categoria (pra menu lateral)."""
    counts: Dict[str, int] = {}
    for c in channels:
        cat = c["category"]
        counts[cat] = counts.get(cat, 0) + 1
    return sorted(
        [{"name": k, "count": v} for k, v in counts.items()],
        key=lambda x: (-x["count"], x["name"]),
    )


async def find_channel(slug_or_id: str) -> Optional[Dict[str, Any]]:
    chans = await fetch_channels()
    for c in chans:
        if c["slug"] == slug_or_id or c["id"] == slug_or_id:
            return c
    return None
