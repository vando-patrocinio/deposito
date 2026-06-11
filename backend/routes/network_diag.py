"""Endpoints de diagnóstico de rede para o app do colaborador.

POST /api/network/ping  → testa conectividade contra um host (IP ou hostname).
                          Como o container nem sempre tem `iputils-ping` (ICMP
                          também exige CAP_NET_RAW), usamos abordagem dupla:
                          1. Tenta socket TCP (porta 80 ou customizada)
                          2. Mede RTT via socket.gettimeofday em cada conexão
                          Protegido por auth + whitelist regex.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import logging
import re
import shutil
import socket
import statistics
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, db, get_current_user, now_iso  # noqa: F401

router = APIRouter(prefix="/api", tags=["network"])
logger = logging.getLogger(__name__)


async def _resolve_actor(authorization: str | None = None,
                            cid_param: str | None = None) -> dict:
    """Resolve quem está chamando: ou user JWT (admin/gestor) OU collaborator
    via link único (?cid=). Mantém auth pro app mobile sem JWT."""
    # 1. JWT (Bearer) — admin/gestor/colaborador logado
    if authorization and authorization.lower().startswith("bearer "):
        try:
            from auth import decode_token
            tok = authorization.split(" ", 1)[1].strip()
            payload = decode_token(tok)
            uid = payload.get("sub") or payload.get("user_id")
            if uid:
                u = await db.users.find_one(
                    {"id": uid}, {"_id": 0, "password_hash": 0},
                )
                if u:
                    return u
        except Exception:
            pass
    # 2. Collaborator link (?cid=col-xxx) — app mobile sem login
    if cid_param:
        c = await db.collaborators.find_one(
            {"id": cid_param, "active": True},
            {"_id": 0, "id": 1, "name": 1, "company_id": 1, "role": 1},
        )
        if c:
            return {
                "id": f"collab:{c['id']}",
                "name": c.get("name"),
                "company_id": c.get("company_id"),
                "role": "colaborador",
                "_collab_id": c["id"],
            }
    raise HTTPException(401, "Acesso negado — faça login ou use link próprio")

# Aceita IPv4, IPv6 e hostnames
_HOST_RE = re.compile(
    r"^(?:"
    r"(?:\d{1,3}\.){3}\d{1,3}"
    r"|"
    r"[0-9a-fA-F:]+"
    r"|"
    r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}"
    r"|"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"  # hostname sem TLD (LAN)
    r")$"
)


class PingIn(BaseModel):
    host: str = Field(..., min_length=1, max_length=253,
                       description="IP ou hostname (ex: 8.8.8.8 / google.com / 192.168.1.1)")
    count: int = Field(4, ge=1, le=10,
                        description="Número de pacotes (1-10)")
    port: int = Field(80, ge=1, le=65535,
                       description="Porta TCP para teste (default 80)")
    ticket_id: str | None = Field(
        None,
        description="ID da bolha sendo trabalhada. Quando preenchido, o "
                    "ping é vinculado a essa nota e o resumo é anexado "
                    "automaticamente no fechamento.",
    )


async def _tcp_probe(host: str, port: int, timeout: float = 3.0) -> float:
    """Retorna RTT em ms se TCP-connect ao host:port funcionar, senão -1."""
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return (loop.time() - t0) * 1000.0
    except Exception:
        return -1.0


async def _icmp_via_ping_cmd(host: str, count: int) -> dict | None:
    """Se `ping` estiver disponível, usa ICMP real (mais informativo).
    Retorna dict com stats ou None se ping não existir.
    """
    ping_bin = shutil.which("ping")
    if not ping_bin:
        return None
    args = [ping_bin, "-n", "-c", str(count), "-W", "2", host]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, _ = await asyncio.wait_for(
                proc.communicate(), timeout=15.0,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return {"method": "icmp", "alive": False, "timeout": True}
    except Exception:
        return None
    output = (stdout_b or b"").decode("utf-8", errors="ignore")
    m = re.search(
        r"(\d+) packets transmitted,\s*(\d+) (?:packets )?received,?\s*"
        r"(?:[\+\d]+ errors,?\s*)?([\d.]+)% packet loss",
        output,
    )
    m2 = re.search(
        r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/[\d.]+ ms",
        output,
    )
    sent = int(m.group(1)) if m else None
    received = int(m.group(2)) if m else None
    loss = float(m.group(3)) if m else None
    return {
        "method": "icmp",
        "alive": (received or 0) > 0,
        "sent": sent,
        "received": received,
        "loss_pct": loss,
        "min_ms": float(m2.group(1)) if m2 else None,
        "avg_ms": float(m2.group(2)) if m2 else None,
        "max_ms": float(m2.group(3)) if m2 else None,
        "raw_output": output[-2000:],
    }


@router.post("/network/ping")
async def network_ping(payload: PingIn,
                         authorization: str | None = Header(None),
                         cid: str | None = Query(None,
                            description="Collaborator ID quando vier do app mobile sem JWT")):
    """Testa conectividade contra um host. Usa ICMP se disponível, senão TCP.

    Autenticação dupla:
      - JWT (admin/gestor) OU
      - ?cid=col-xxx (collaborator via link único do app mobile)
    """
    user = await _resolve_actor(authorization, cid)
    host = payload.host.strip()
    if not _HOST_RE.match(host):
        raise HTTPException(
            400,
            "Host inválido. Use IP (ex 192.168.1.1), hostname (ex google.com) "
            "ou nome de máquina LAN (ex ont).",
        )
    if host.lower() in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        raise HTTPException(400, "Não é permitido ping em endereços locais")

    started_at = datetime.now(timezone.utc)
    started_iso = started_at.isoformat()

    # Tenta ICMP primeiro (mais informativo: packet loss real)
    icmp = await _icmp_via_ping_cmd(host, payload.count)
    if icmp:
        finished_iso = datetime.now(timezone.utc).isoformat()
        await _log_audit(user, host, payload.count, icmp,
                          started_iso, finished_iso, payload.ticket_id)
        return {
            "ok": True,
            "host": host,
            "method": "icmp",
            **{k: v for k, v in icmp.items() if k != "method"},
            "started_at": started_iso,
            "finished_at": finished_iso,
        }

    # Fallback: TCP-connect (funciona em container sem CAP_NET_RAW).
    # Envia N tentativas e calcula min/avg/max.
    samples: list[float] = []
    failed = 0
    for _ in range(payload.count):
        rtt = await _tcp_probe(host, payload.port, timeout=3.0)
        if rtt < 0:
            failed += 1
        else:
            samples.append(rtt)
        await asyncio.sleep(0.2)  # pausa curta entre tentativas

    received = len(samples)
    sent = payload.count
    loss_pct = round(100.0 * failed / sent, 1) if sent else None
    alive = received > 0
    avg_ms = round(statistics.mean(samples), 2) if samples else None
    min_ms = round(min(samples), 2) if samples else None
    max_ms = round(max(samples), 2) if samples else None

    finished_iso = datetime.now(timezone.utc).isoformat()
    stats = {
        "method": "tcp",
        "alive": alive,
        "sent": sent,
        "received": received,
        "loss_pct": loss_pct,
        "min_ms": min_ms,
        "avg_ms": avg_ms,
        "max_ms": max_ms,
        "port": payload.port,
    }
    await _log_audit(user, host, payload.count, stats,
                      started_iso, finished_iso, payload.ticket_id)

    return {
        "ok": True,
        "host": host,
        **stats,
        "started_at": started_iso,
        "finished_at": finished_iso,
    }


async def _log_audit(user: dict, host: str, count: int,
                      stats: dict, started: str, finished: str,
                      ticket_id: str | None = None) -> None:
    try:
        cid = user.get("company_id") or DEMO_COMPANY_ID
        await db.network_ping_log.insert_one({
            "company_id": cid,
            "user_id": user.get("id"),
            "user_name": user.get("name") or user.get("email"),
            "collaborator_id": user.get("_collab_id"),
            "ticket_id": ticket_id,
            "host": host,
            "count": count,
            "port": stats.get("port"),
            "alive": stats.get("alive"),
            "received": stats.get("received"),
            "sent": stats.get("sent"),
            "loss_pct": stats.get("loss_pct"),
            "avg_ms": stats.get("avg_ms"),
            "min_ms": stats.get("min_ms"),
            "max_ms": stats.get("max_ms"),
            "method": stats.get("method"),
            "started_at": started,
            "finished_at": finished,
        })
    except Exception as e:
        logger.info("[ping] audit log skip: %s", e)


def summarize_ping_log(p: dict) -> str:
    """Formata 1 log de ping em linha curta para anexar em laudo."""
    host = p.get("host", "?")
    if p.get("alive"):
        rtt = p.get("avg_ms")
        rtt_str = f"{rtt:.1f}ms" if isinstance(rtt, (int, float)) else "?"
        loss = p.get("loss_pct")
        loss_str = (f" | {loss:.0f}% loss"
                    if isinstance(loss, (int, float)) and loss > 0 else "")
        return f"✓ {host} respondeu — RTT {rtt_str}{loss_str}"
    return f"✗ {host} NÃO respondeu — host offline ou bloqueado"


async def build_close_ping_summary(ticket_id: str,
                                     opened_at: str | None = None) -> str:
    """Monta o texto que será anexado ao fechamento de uma bolha.

    - Busca todos os pings feitos PARA essa ticket_id (campo direto)
    - Se nada → retorna "Teste de ping NÃO FOI REALIZADO"
    - Se algum → retorna lista resumida em texto multilinha
    """
    q: dict = {"ticket_id": ticket_id}
    if opened_at:
        # Considera pings desde a abertura (pra evitar logs de bolha antiga)
        q["started_at"] = {"$gte": opened_at}
    logs = await db.network_ping_log.find(
        q, {"_id": 0}, sort=[("started_at", -1)],
    ).to_list(20)
    if not logs:
        return "🛰 Teste de ping: NÃO FOI REALIZADO durante o atendimento."
    lines = ["🛰 Teste de ping realizado:"]
    for p in logs[:10]:  # max 10 entradas pra não inchar
        lines.append(f"  · {summarize_ping_log(p)}")
    if len(logs) > 10:
        lines.append(f"  · (+ {len(logs) - 10} testes anteriores omitidos)")
    return "\n".join(lines)


@router.get("/network/ping/history")
async def network_ping_history(authorization: str | None = Header(None),
                                  cid: str | None = Query(None),
                                  limit: int = 20):
    """Últimos pings feitos pelo usuário logado (ou colaborador via link)."""
    user = await _resolve_actor(authorization, cid)
    cid_company = user.get("company_id") or DEMO_COMPANY_ID
    limit = max(1, min(limit, 100))
    docs = await db.network_ping_log.find(
        {"company_id": cid_company, "user_id": user.get("id")},
        {"_id": 0},
    ).sort("started_at", -1).limit(limit).to_list(limit)
    return {"items": docs, "count": len(docs)}


@router.post("/network/resolve")
async def network_resolve(payload: PingIn,
                            authorization: str | None = Header(None),
                            cid: str | None = Query(None)):
    """Resolve um hostname para IPs (DNS lookup)."""
    await _resolve_actor(authorization, cid)
    host = payload.host.strip()
    if not _HOST_RE.match(host):
        raise HTTPException(400, "Host inválido")
    try:
        loop = asyncio.get_event_loop()
        infos = await loop.run_in_executor(
            None, lambda: socket.getaddrinfo(host, None),
        )
        ips = sorted({i[4][0] for i in infos})
        return {"ok": True, "host": host, "ips": ips}
    except Exception as e:
        return {"ok": False, "host": host, "error": str(e)}
