"""Network · Teste IPv6 obrigatório na finalização de OS.

Endpoints:
- GET  /api/network/myip       — retorna IP público de quem chamou (v4 ou v6)
- POST /api/network/ipv6-test  — recebe resultados do browser, normaliza score
- POST /api/lousa/tickets/{tid}/ipv6-test — persiste resultado na nota (ticket.completion_data.ipv6_test)

Estratégia:
- O técnico (no celular conectado ao WiFi do cliente) abre a tela de
  finalização. O frontend roda automaticamente <img> tags pingando
  endpoints só-IPv4, só-IPv6, dual-stack e MTU-large.
- Backend só calcula score (0-10) e persiste — toda a detecção de
  conectividade ocorre no browser do técnico.
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

import logging
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, get_current_user, now_iso
from database import db

logger = logging.getLogger("ponto.network_test")
router = APIRouter(prefix="/api/network", tags=["network-ipv6"])


def _detect_family(ip: str) -> int:
    if not ip:
        return 0
    return 6 if ":" in ip else 4


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for") or ""
    if xff:
        # primeiro IP da lista (real client)
        return xff.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return (request.client.host if request.client else "") or ""


@router.get("/myip")
async def myip(request: Request,
                  user: dict = Depends(get_current_user)):
    """Retorna o IP público do cliente que fez a chamada.

    Quando o técnico abre o app conectado no WiFi do cliente, o IP retornado
    é o IP público do cliente — não o do nosso datacenter.
    """
    ip = _client_ip(request)
    fam = _detect_family(ip)
    return {
        "ip": ip,
        "family": fam,
        "is_ipv6": fam == 6,
        "raw_xff": request.headers.get("x-forwarded-for"),
        "tested_at": now_iso(),
    }


class Ipv6TestPayload(BaseModel):
    ipv4_reachable: bool = False
    ipv6_reachable: bool = False
    dual_stack_ok: bool = False
    mtu_ok: bool = False
    dns_ipv6_ok: bool = False
    v4_addr: Optional[str] = None
    v6_addr: Optional[str] = None
    isp: Optional[str] = None
    latency_v4_ms: Optional[float] = None
    latency_v6_ms: Optional[float] = None
    raw_results: Optional[Dict[str, Any]] = None


def _calc_score(p: "Ipv6TestPayload") -> int:
    """Pontuação 0-10 inspirada em test-ipv6.com."""
    if not p.ipv4_reachable:
        return 0  # sem internet, score zero
    score = 0
    if p.ipv6_reachable:
        score += 5
    if p.dual_stack_ok:
        score += 2
    if p.dns_ipv6_ok:
        score += 1
    if p.mtu_ok:
        score += 2
    return min(10, score)


@router.post("/ipv6-test")
async def ipv6_test(payload: Ipv6TestPayload,
                       request: Request,
                       user: dict = Depends(get_current_user)):
    """Recebe resultados do browser, calcula score normalizado.

    Não persiste — apenas calcula. Para persistir na OS, o frontend
    chama em seguida POST /api/lousa/tickets/{tid}/ipv6-test.
    """
    score = _calc_score(payload)
    inconsistent = score < 8
    return {
        "score": score,
        "max_score": 10,
        "passed": not inconsistent,
        "ipv6_inconsistente": inconsistent,
        "verdict": (
            "Excelente · IPv6 perfeito" if score == 10 else
            "Bom · IPv6 funcional" if score >= 8 else
            "Atenção · IPv6 com problemas" if score >= 4 else
            "Crítico · IPv6 inoperante / sem internet"
        ),
        "details": {
            "ipv4_reachable": payload.ipv4_reachable,
            "ipv6_reachable": payload.ipv6_reachable,
            "dual_stack_ok": payload.dual_stack_ok,
            "dns_ipv6_ok": payload.dns_ipv6_ok,
            "mtu_ok": payload.mtu_ok,
        },
        "v4_addr": payload.v4_addr,
        "v6_addr": payload.v6_addr,
        "tested_at": now_iso(),
    }


@router.get("/echo")
async def echo(request: Request):
    """Endpoint mínimo pra medir round-trip real do cliente até o servidor.

    Retorna 200 com payload mínimo para o frontend medir latência real
    via fetch(). Sem CORS overhead, sem auth — é só um marca-passo.
    """
    return {"ok": True, "t": now_iso()}


@router.post("/lousa-mock")
async def _placeholder():
    """Apenas mantém este módulo isolado — endpoint real fica em lousa."""
    raise HTTPException(404, "Use /api/lousa/tickets/{tid}/ipv6-test")


# ---------------------------------------------------------------------------
# Dashboard de Qualidade IPv6 por Bairro e por CTO
# ---------------------------------------------------------------------------
@router.get("/ipv6-quality")
async def ipv6_quality(period_days: int = 30,
                          user: dict = Depends(get_current_user)):
    """Agrega scores IPv6 do `completion_data.ipv6_test` dos últimos N dias.

    Retorna:
    - overall: contagem, média, % consistente
    - by_bairro: top 20 ordenado por pior média
    - by_cto: top 20 ordenado por pior média
    """
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415
    cid = user.get("company_id") or DEMO_COMPANY_ID
    since = (datetime.now(timezone.utc) - timedelta(days=int(period_days))).isoformat()
    cur = db.tickets.find(
        {"company_id": cid,
         "completion_data.ipv6_test.tested_at": {"$gte": since}},
        {"_id": 0, "client_snapshot.neighborhood": 1, "client_snapshot.cto_name": 1,
         "cto_id": 1, "completion_data.ipv6_test": 1, "type": 1, "closed_at": 1},
    )
    bairro_acc: Dict[str, Dict[str, Any]] = {}
    cto_acc: Dict[str, Dict[str, Any]] = {}
    total = 0
    score_sum = 0
    inconsistent = 0
    async for t in cur:
        cd = t.get("completion_data") or {}
        ipv6 = cd.get("ipv6_test") or {}
        score = ipv6.get("score")
        if score is None:
            continue
        total += 1
        score_sum += score
        if ipv6.get("ipv6_inconsistente"):
            inconsistent += 1
        # Bairro
        bairro = (t.get("client_snapshot") or {}).get("neighborhood") or "Sem bairro"
        b = bairro_acc.setdefault(bairro, {"bairro": bairro, "count": 0,
                                             "score_sum": 0, "inconsistent": 0,
                                             "mtu_fail": 0, "no_v6": 0})
        b["count"] += 1
        b["score_sum"] += score
        if ipv6.get("ipv6_inconsistente"):
            b["inconsistent"] += 1
        if not ipv6.get("mtu_ok"):
            b["mtu_fail"] += 1
        if not ipv6.get("ipv6_reachable"):
            b["no_v6"] += 1
        # CTO
        cto_label = ((t.get("client_snapshot") or {}).get("cto_name")
                      or t.get("cto_id") or "Sem CTO")
        c = cto_acc.setdefault(cto_label, {"cto": cto_label, "count": 0,
                                              "score_sum": 0, "inconsistent": 0,
                                              "mtu_fail": 0, "no_v6": 0})
        c["count"] += 1
        c["score_sum"] += score
        if ipv6.get("ipv6_inconsistente"):
            c["inconsistent"] += 1
        if not ipv6.get("mtu_ok"):
            c["mtu_fail"] += 1
        if not ipv6.get("ipv6_reachable"):
            c["no_v6"] += 1

    def _finalize(rows):
        out = []
        for r in rows.values():
            n = r["count"] or 1
            r["avg_score"] = round(r["score_sum"] / n, 1)
            r["inconsistent_pct"] = round(r["inconsistent"] / n * 100, 1)
            del r["score_sum"]
            out.append(r)
        # Pior média primeiro (mais critico no topo)
        out.sort(key=lambda x: (x["avg_score"], -x["count"]))
        return out[:20]

    return {
        "period_days": period_days,
        "overall": {
            "total_tested": total,
            "avg_score": round(score_sum / total, 1) if total else 0,
            "inconsistent_count": inconsistent,
            "inconsistent_pct": round(inconsistent / total * 100, 1) if total else 0,
        },
        "by_bairro": _finalize(bairro_acc),
        "by_cto": _finalize(cto_acc),
    }
