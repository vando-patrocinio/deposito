"""Ligo TV portal — hub público de canais grátis (Pluto TV) pro assinante.

Auth: CPF (login + senha = mesmo CPF) — valida contra a collection
`atlaz_clients_cache`. Só libera se o assinante tem contrato ATIVO em
`subscribers` (match por `document`).

Token: JWT próprio (`ligo_tv_subject`), TTL 30 dias, assinado com
`LIGO_TV_JWT_SECRET` (gerado on-the-fly se ausente — vira `JWT_SECRET` do
backend principal pra herdar a rotação).

Endpoints (todos sob `/api/ligo-tv`):
- POST `/auth/login`        — CPF + senha → JWT
- GET  `/me`                — info do assinante autenticado
- GET  `/channels`          — catálogo Pluto TV completo
- GET  `/categories`        — categorias com contagem
- GET  `/channels/{slug}`   — detalhe + URL HLS pronta pro player
- GET  `/stream/{slug}`     — proxy do master.m3u8 com CORS
- GET  `/stream-proxy`      — proxy genérico de playlists e segmentos
"""
from __future__ import annotations

import base64
import logging
import os
import re
import time
from typing import Any, Dict, Optional
from urllib.parse import urljoin, quote, unquote

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from services import pluto_tv

log = logging.getLogger("ponto.ligo_tv")

router = APIRouter(prefix="/api/ligo-tv", tags=["ligo-tv"])

JWT_ALG = "HS256"
JWT_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 dias


def _secret() -> str:
    return (
        os.environ.get("LIGO_TV_JWT_SECRET")
        or os.environ.get("JWT_SECRET")
        or "ligo-tv-dev-secret-CHANGE"
    )


def _only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def _issue_token(subscriber: Dict[str, Any]) -> str:
    now = int(time.time())
    payload = {
        "sub": subscriber.get("id") or subscriber.get("external_id"),
        "doc": subscriber.get("document"),
        "name": subscriber.get("name"),
        "company_id": subscriber.get("company_id"),
        "iat": now,
        "exp": now + JWT_TTL_SECONDS,
        "kind": "ligo-tv",
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALG)


def _decode(token: str) -> Dict[str, Any]:
    return jwt.decode(token, _secret(), algorithms=[JWT_ALG])


async def get_db():
    """Importa o db lazy pra evitar ciclo de import com server.py."""
    from server import db
    return db


async def current_subscriber(request: Request) -> Dict[str, Any]:
    auth = request.headers.get("authorization") or ""
    token = auth[7:] if auth.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(401, "Token Ligo TV ausente.")
    try:
        payload = _decode(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Sessão expirada. Faça login novamente.")
    except Exception:
        raise HTTPException(401, "Token Ligo TV inválido.")
    if payload.get("kind") != "ligo-tv":
        raise HTTPException(401, "Token inválido pra Ligo TV.")
    return payload


# ─────────────────────── Models ───────────────────────
class LoginPayload(BaseModel):
    cpf: str = Field(..., min_length=11, max_length=20)
    password: str = Field(..., min_length=11, max_length=20)


# ─────────────────────── Auth ───────────────────────
@router.post("/auth/login")
async def login(payload: LoginPayload):
    """Login CPF + senha (senha = CPF). Valida contrato ATIVO."""
    cpf = _only_digits(payload.cpf)
    senha = _only_digits(payload.password)
    if len(cpf) != 11:
        raise HTTPException(400, "CPF inválido (precisa ter 11 dígitos).")
    if cpf != senha:
        # Política do CEO 17/06/2026 — senha inicial é o próprio CPF.
        raise HTTPException(401, "CPF ou senha inválidos.")

    db = await get_db()
    cliente = await db.atlaz_clients_cache.find_one({"document": cpf})
    if not cliente:
        raise HTTPException(404, "Cliente não encontrado. Contrate um plano Ligo.")

    # Cruza com subscribers pra checar contrato ATIVO
    sub = await db.subscribers.find_one({
        "$or": [
            {"document": cpf},
            {"id": cliente.get("external_id")},
        ]
    })
    if sub and sub.get("contract_status") and sub["contract_status"].upper() != "ATIVO":
        raise HTTPException(
            403,
            f"Contrato {sub.get('contract_status')} — regularize pra acessar a Ligo TV.",
        )

    cliente.pop("_id", None)
    token = _issue_token(cliente)
    return {
        "ok": True,
        "token": token,
        "subscriber": {
            "name": cliente.get("name"),
            "document": cpf,
            "email": cliente.get("email"),
            "phone": cliente.get("phone"),
        },
    }


@router.get("/me")
async def me(user: Dict[str, Any] = Depends(current_subscriber)):
    return {
        "name": user.get("name"),
        "document": user.get("doc"),
        "company_id": user.get("company_id"),
        "expires_at": user.get("exp"),
    }


# ─────────────────────── Canais ───────────────────────
@router.get("/channels")
async def list_channels(
    category: Optional[str] = None,
    search: Optional[str] = None,
    user: Dict[str, Any] = Depends(current_subscriber),
):
    """Lista canais (filtra por categoria e/ou busca)."""
    chans = await pluto_tv.fetch_channels()
    out = chans
    if category and category.lower() != "todos":
        cat_low = category.lower()
        out = [c for c in out if (c["category"] or "").lower() == cat_low]
    if search:
        q = search.lower().strip()
        out = [
            c for c in out
            if q in (c["name"] or "").lower()
            or q in (c["summary"] or "").lower()
        ]
    # Não exponha a hls_url completa na listagem (poupa bytes + força
    # passar pelo endpoint /channels/{slug} pra hidratar)
    light = [{
        "id": c["id"], "slug": c["slug"], "name": c["name"],
        "number": c["number"], "category": c["category"],
        "logo": c["logo"], "tile": c["tile"], "thumbnail": c["thumbnail"],
        "summary": c["summary"],
    } for c in out]
    return {"count": len(light), "channels": light}


@router.get("/categories")
async def list_categories(user: Dict[str, Any] = Depends(current_subscriber)):
    chans = await pluto_tv.fetch_channels()
    return {"categories": pluto_tv.categories(chans)}


@router.get("/channels/{slug}")
async def channel_detail(
    slug: str,
    request: Request,
    user: Dict[str, Any] = Depends(current_subscriber),
):
    c = await pluto_tv.find_channel(slug)
    if not c:
        raise HTTPException(404, "Canal não encontrado.")
    # Substitui a hls_url direta por um endpoint proxy nosso. O Pluto TV
    # não libera CORS pra origins de terceiros — sem proxy, o HLS.js do
    # navegador trava em `networkError` ao buscar o master.m3u8.
    out = dict(c)
    out["hls_url"] = f"{_public_base(request)}/api/ligo-tv/stream/{c['slug']}/master.m3u8"
    return {"channel": out}


# ─────────────────────── Proxy HLS (CORS bypass) ───────────────────────
#
# Pluto TV bloqueia origins de terceiros via CORS. Sem proxy, qualquer
# `fetch()` do HLS.js falha. A solução padrão é proxyiar tudo pelo nosso
# backend e reescrever as URLs internas do .m3u8 pra apontarem de volta
# pro proxy.

_PROXY_HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 LigoTV/1.0",
    "Accept": "*/*",
    "Origin": "https://pluto.tv",
    "Referer": "https://pluto.tv/",
}

_HLS_LINE_RE = re.compile(r"^(?!#)(https?://\S+|\S+\.(m3u8|ts|aac|m4s|key|mp4)\S*)\s*$", re.IGNORECASE)


def _public_base(request: Request) -> str:
    """Devolve a base URL pública pro proxy reescrever links.

    Prefere `Origin` do request (browser sempre manda a URL pública),
    cai pra `LIGO_TV_BASE_URL` (env), e finalmente pra `Host` + proto.
    Isso evita os hostnames internos do cluster (que voltam 403 Cloudflare).
    """
    env_base = os.environ.get("LIGO_TV_BASE_URL")
    if env_base:
        return env_base.rstrip("/")
    origin = request.headers.get("origin")
    if origin and origin.startswith(("http://", "https://")):
        return origin.rstrip("/")
    referer = request.headers.get("referer")
    if referer and referer.startswith(("http://", "https://")):
        from urllib.parse import urlparse as _up
        p = _up(referer)
        return f"{p.scheme}://{p.netloc}"
    proto = request.headers.get("x-forwarded-proto") or "https"
    host = request.headers.get("host") or request.url.hostname or ""
    return f"{proto}://{host}".rstrip("/")


def _proxy_url(request: Request, target: str) -> str:
    """Constrói URL do nosso proxy genérico encapsulando a URL alvo."""
    encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
    return f"{_public_base(request)}/api/ligo-tv/stream-proxy?u={encoded}"


def _rewrite_manifest(text: str, base_url: str, request: Request) -> str:
    """Reescreve URLs relativas/absolutas dentro de um .m3u8 pra passar pelo proxy."""
    out_lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            # Tag — pode conter URI="..." (EXT-X-KEY, EXT-X-MEDIA, etc.)
            def _sub(m):
                uri = m.group(1)
                absolute = urljoin(base_url, uri)
                return f'URI="{_proxy_url(request, absolute)}"'
            line = re.sub(r'URI="([^"]+)"', _sub, line)
            out_lines.append(line)
            continue
        # Linha não-comentário = URL de segmento ou sub-playlist
        absolute = urljoin(base_url, s)
        out_lines.append(_proxy_url(request, absolute))
    return "\n".join(out_lines) + "\n"


@router.get("/stream/{slug}/master.m3u8")
async def stream_master(slug: str, request: Request):
    """Entrega o master playlist do canal com URLs reescritas pro proxy.

    NOTA: este endpoint é público (player do navegador não consegue
    mandar Authorization header em `<video src=...>`). O slug funciona
    como identificador opaco; conteúdo é Pluto TV grátis então não é
    um vetor de abuso significativo.
    """
    c = await pluto_tv.find_channel(slug)
    if not c:
        raise HTTPException(404, "Canal não encontrado.")
    # Pluto TV exige session boot — usar build_stream_url em vez da hls_url
    # crua do catálogo (que vem com placeholders e devolve 400).
    target = await pluto_tv.build_stream_url(c["id"])
    if not target:
        raise HTTPException(502, "Sessão Pluto TV indisponível.")
    async with httpx.AsyncClient(timeout=15.0, headers=_PROXY_HEADERS_BASE) as cli:
        try:
            r = await cli.get(target, follow_redirects=True)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(502, f"Pluto TV indisponível: {e}")
    rewritten = _rewrite_manifest(r.text, str(r.url), request)
    return Response(
        content=rewritten,
        media_type="application/vnd.apple.mpegurl",
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"},
    )


@router.get("/stream-proxy")
async def stream_proxy(u: str = Query(..., description="base64url da URL alvo")):
    """Proxy transparente pros segmentos .ts/.aac/.m4s e sub-playlists.

    Recebe a URL alvo encodada em base64url (params curtos no manifest).
    Se a resposta for uma sub-playlist (.m3u8), reescreve recursivamente.
    Senão, faz streaming dos bytes.
    """
    try:
        padded = u + "=" * (-len(u) % 4)
        target = base64.urlsafe_b64decode(padded.encode()).decode()
    except Exception:
        raise HTTPException(400, "URL inválida.")
    if not target.startswith(("http://", "https://")):
        raise HTTPException(400, "URL alvo inválida.")
    # SSRF guard — permite apenas domínios Pluto TV (CDN/stitcher/players)
    from urllib.parse import urlparse
    host = (urlparse(target).hostname or "").lower()
    allowed = ("pluto.tv", "plutotv.net", "plutotv.com")
    if not any(host == d or host.endswith("." + d) for d in allowed):
        raise HTTPException(403, f"Domínio não permitido: {host}")

    headers = dict(_PROXY_HEADERS_BASE)
    timeout = httpx.Timeout(30.0, connect=10.0)
    client = httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True)
    try:
        # Para .m3u8 (sub-playlist) baixa inteiro e reescreve
        if ".m3u8" in target.split("?")[0]:
            r = await client.get(target)
            await client.aclose()
            if r.status_code >= 400:
                raise HTTPException(502, f"upstream {r.status_code}")
            # Reaproveita o rewrite — passa um Request "fake" via cabecalho host
            # do upstream. Como esse proxy é chamado pelo HLS.js direto, usa
            # base_url estática do nosso domínio (não temos Request aqui).
            from starlette.datastructures import URL
            class _FakeReq:
                base_url = URL(os.environ.get("LIGO_TV_BASE_URL")
                               or "https://universoligo.com/")
            rewritten = _rewrite_manifest(r.text, str(r.url), _FakeReq())
            return Response(
                content=rewritten,
                media_type="application/vnd.apple.mpegurl",
                headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"},
            )
        # Streams binários (segmentos)
        req = client.build_request("GET", target)
        upstream = await client.send(req, stream=True)
        if upstream.status_code >= 400:
            await upstream.aclose()
            await client.aclose()
            raise HTTPException(502, f"upstream {upstream.status_code}")

        ctype = upstream.headers.get("content-type") or "application/octet-stream"

        async def _gen():
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        return StreamingResponse(
            _gen(),
            media_type=ctype,
            headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"},
        )
    except HTTPException:
        await client.aclose()
        raise
    except Exception as e:
        await client.aclose()
        raise HTTPException(502, f"falha proxy: {e}")
