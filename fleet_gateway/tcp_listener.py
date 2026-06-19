"""
tcp_listener.py — Listener TCP para rastreadores TK103.

Aceita conexões TCP simultâneas (asyncio), parseia frames com tk103_parser,
e repassa para o backend SmartProv via HTTPS POST.

Também consulta periodicamente o backend por comandos pendentes para cada
IMEI conectado e envia ao tracker via a mesma conexão TCP.

Env vars:
  BACKEND_URL          (default: http://localhost:8001)
  FLEET_INGEST_TOKEN   (default: vazio = sem auth, só dev)
  GATEWAY_TCP_PORT     (default: 5023)
  GATEWAY_HOST         (default: 0.0.0.0)
  COMMAND_POLL_SEC     (default: 60)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from typing import Dict

import urllib.request
import urllib.error

from tk103_parser import parse_frame, build_command


BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8001").rstrip("/")
INGEST_TOKEN = os.environ.get("FLEET_INGEST_TOKEN", "")
TCP_PORT = int(os.environ.get("GATEWAY_TCP_PORT", "5023"))
TCP_HOST = os.environ.get("GATEWAY_HOST", "0.0.0.0")
COMMAND_POLL_SEC = int(os.environ.get("COMMAND_POLL_SEC", "60"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fleet-gateway")

# Mapa IMEI → writer (StreamWriter) para envio de comandos.
_CONNECTIONS: Dict[str, asyncio.StreamWriter] = {}


def _http_post(path: str, data: dict, timeout: int = 10) -> dict:
    url = f"{BACKEND_URL}{path}"
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json",
                  **({"Authorization": f"Bearer {INGEST_TOKEN}"}
                     if INGEST_TOKEN else {})},
    )
    try:
        # SECURITY_LOCK ART.6: URL é construída a partir de BACKEND_URL (env interna,
        # trusted). Não há user input no path. Tratado como safe_fetch interno.
        with urllib.request.urlopen(req, timeout=timeout) as r:  # safe_fetch: internal-only
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        log.warning("POST %s falhou %s: %s", path, e.code, e.read()[:200])
    except Exception as e:
        log.warning("POST %s erro: %s", path, e)
    return {}


def _http_get(path: str, timeout: int = 10) -> dict | list:
    url = f"{BACKEND_URL}{path}"
    req = urllib.request.Request(
        url, method="GET",
        headers={"Authorization": f"Bearer {INGEST_TOKEN}"}
        if INGEST_TOKEN else {},
    )
    try:
        # SECURITY_LOCK ART.6: URL interna apenas (BACKEND_URL). safe_fetch internal-only.
        with urllib.request.urlopen(req, timeout=timeout) as r:  # safe_fetch: internal-only
            return json.loads(r.read().decode("utf-8") or "[]")
    except Exception as e:
        log.warning("GET %s erro: %s", path, e)
    return []


async def handle_client(reader: asyncio.StreamReader,
                        writer: asyncio.StreamWriter):
    peer = writer.get_extra_info("peername")
    log.info("[conn] %s conectou", peer)
    imei_seen = None
    try:
        while True:
            data = await asyncio.wait_for(reader.read(2048), timeout=300)
            if not data:
                break
            # TK103 pode mandar múltiplos frames juntos
            for line in data.decode("ascii", errors="ignore").splitlines():
                line = line.strip()
                if not line:
                    continue
                pos = parse_frame(line)
                if not pos:
                    log.debug("[skip] frame inválido: %s", line[:80])
                    continue
                # Registra conexão pelo IMEI para envio futuro de comandos
                imei_seen = pos["imei"]
                _CONNECTIONS[imei_seen] = writer
                # Envia para o backend
                result = _http_post("/api/fleet-tracking/ingest", pos)
                log.info("[pos] %s lat=%.6f lng=%.6f speed=%.1f → %s",
                         pos["imei"], pos["lat"], pos["lng"],
                         pos["speed_kmh"], result.get("ok"))
    except asyncio.TimeoutError:
        log.info("[conn] %s timeout (sem dados 5min)", peer)
    except Exception as e:
        log.warning("[conn] %s erro: %s", peer, e)
    finally:
        if imei_seen and _CONNECTIONS.get(imei_seen) is writer:
            _CONNECTIONS.pop(imei_seen, None)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        log.info("[conn] %s desconectou", peer)


async def command_poller():
    """A cada COMMAND_POLL_SEC, varre conexões ativas e busca comandos."""
    while True:
        try:
            for imei, writer in list(_CONNECTIONS.items()):
                if writer.is_closing():
                    _CONNECTIONS.pop(imei, None)
                    continue
                cmds = _http_get(f"/api/fleet-tracking/commands/{imei}") or []
                if not isinstance(cmds, list):
                    continue
                for c in cmds:
                    pwd = c.get("tracker_password") or "123456"
                    payload = c.get("payload") or {}
                    text = build_command(c["kind"], pwd, payload)
                    if not text:
                        continue
                    try:
                        writer.write((text + "\r\n").encode("ascii"))
                        await writer.drain()
                        ok = True
                        log.info("[cmd] %s → %s", imei, text)
                    except Exception as e:
                        ok = False
                        log.warning("[cmd] %s falhou %s: %s", imei, text, e)
                    _http_post(f"/api/fleet-tracking/commands/{c['id']}/ack",
                                {"ok": ok})
        except Exception as e:
            log.warning("[poll] erro: %s", e)
        await asyncio.sleep(COMMAND_POLL_SEC)


async def main():
    server = await asyncio.start_server(handle_client, TCP_HOST, TCP_PORT)
    log.info("Gateway escutando em %s:%d → backend %s",
             TCP_HOST, TCP_PORT, BACKEND_URL)
    asyncio.create_task(command_poller())
    async with server:
        await server.serve_forever()


def _shutdown(*_):
    log.info("Encerrando…")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
