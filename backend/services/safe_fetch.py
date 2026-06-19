"""safe_fetch — guard contra SSRF (ART.6 SECURITY_LOCK).

Uso:
    from services.safe_fetch import safe_fetch
    data = safe_fetch(url, timeout=5)

Bloqueia:
- Schemes que não sejam http/https
- Loopback (127.0.0.0/8, ::1)
- Link-local (169.254.0.0/16) — inclui AWS/GCP metadata
- RFC1918 privados (10/8, 172.16/12, 192.168/16)
- Reserved/multicast/broadcast
- IPv6 ULA (fc00::/7) e link-local (fe80::/10)
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Optional
from urllib.parse import urlparse

import requests


class SSRFBlocked(Exception):
    """Levantada quando o URL/host viola a política anti-SSRF."""


def _is_private_addr(host: str) -> bool:
    try:
        # Resolve todos os endereços possíveis (A/AAAA).
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # Host não resolve → bloqueia por precaução
        return True
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return True
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            return True
        # Metadata services
        if str(ip) in {"169.254.169.254", "100.100.100.200", "fd00:ec2::254"}:
            return True
    return False


def safe_fetch(url: str, *, timeout: float = 5.0,
               allow_http: bool = False,
               max_bytes: int = 5_000_000) -> bytes:
    """Faz GET com guardas anti-SSRF. Retorna bytes do body.

    - Só `https://` (ou `http://` se allow_http=True explicitamente).
    - Host não pode resolver para IP privado/loopback/link-local/metadata.
    - Limita body a max_bytes.
    """
    if not isinstance(url, str) or not url:
        raise SSRFBlocked("empty url")
    parsed = urlparse(url)
    if parsed.scheme not in ("https",) and not (
            allow_http and parsed.scheme == "http"):
        raise SSRFBlocked(f"scheme not allowed: {parsed.scheme}")
    host = parsed.hostname or ""
    if not host:
        raise SSRFBlocked("no host in url")
    if _is_private_addr(host):
        raise SSRFBlocked(f"host resolves to private/blocked range: {host}")

    resp = requests.get(url, timeout=timeout, stream=True,
                        allow_redirects=False)
    # Bloqueia redirect — força revalidação se o caller quiser seguir.
    if resp.status_code in (301, 302, 303, 307, 308):
        raise SSRFBlocked(f"redirect not followed: {resp.headers.get('Location')}")
    chunks = []
    total = 0
    for chunk in resp.iter_content(chunk_size=64_000):
        total += len(chunk)
        if total > max_bytes:
            raise SSRFBlocked("response too large")
        chunks.append(chunk)
    return b"".join(chunks)


def safe_fetch_text(url: str, **kw) -> str:
    return safe_fetch(url, **kw).decode("utf-8", errors="replace")
