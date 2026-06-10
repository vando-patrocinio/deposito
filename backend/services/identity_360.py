"""OPERAÇÃO IDENTIDADE 360° — contexto completo da Isabella em < 200ms.

Reusa coleções existentes:
  • subscribers · subscriber_phones · subscriber_addresses
  • client_equipment_history · smartolt_onus
  • subscriber_invoices · tickets

Sem novas coleções. Cache em memória (TTL 60s por phone).

API:
  - identity_360(company_id, phone) → dict completo
  - format_for_isabella(identity) → string pronta para o system prompt
"""
from __future__ import annotations
import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db
from phone_normalizer import normalize_brazilian_phone


_CACHE: Dict[str, tuple] = {}  # key = (cid, phone) → (ts, data)
_CACHE_TTL_S = 60


def _cache_get(key) -> Optional[Dict[str, Any]]:
    v = _CACHE.get(key)
    if not v:
        return None
    ts, data = v
    if time.time() - ts < _CACHE_TTL_S:
        return data
    _CACHE.pop(key, None)
    return None


def _cache_put(key, data):
    _CACHE[key] = (time.time(), data)


async def identity_360(company_id: str, phone: str,
                          *, ttl_s: int = _CACHE_TTL_S) -> Dict[str, Any]:
    """Devolve perfil completo do cliente identificado por telefone.

    Estrutura:
      { subscriber: {id,name,plan,status,address,neighborhood}
      , addresses: [...]
      , equipment: [...]
      , last_invoice: {...}
      , recent_tickets: [...]
      , timing_ms: int
      , cached: bool }
    """
    started = time.time()
    norm = normalize_brazilian_phone(phone) or phone
    cache_key = (company_id, norm)
    cached = _cache_get(cache_key)
    if cached:
        out = dict(cached)
        out["cached"] = True
        out["timing_ms"] = int((time.time() - started) * 1000)
        return out

    # 1) Identifica subscriber via phone
    from phone_normalizer import link_phone_to_subscriber
    link = await link_phone_to_subscriber(phone, company_id)
    if not link or not link.get("subscriber_id"):
        out = {"subscriber": None, "link": link,
               "addresses": [], "equipment": [],
               "last_invoice": None, "recent_tickets": [],
               "timing_ms": int((time.time() - started) * 1000),
               "cached": False}
        _cache_put(cache_key, out)
        return out

    sid = link["subscriber_id"]
    # 2) Consultas em paralelo (3 queries)
    sub_task = db.subscribers.find_one(
        {"id": sid, "company_id": company_id},
        {"_id": 0, "id": 1, "name": 1, "plan_name": 1, "plan_price": 1,
         "monthly_value": 1, "status": 1, "address": 1, "neighborhood": 1,
         "pppoe": 1, "cto_id": 1, "olt_name": 1, "activated_at": 1,
         "churn_score": 1, "retention_score": 1})

    async def _addresses():
        out = []
        async for a in db.subscriber_addresses.find(
                {"company_id": company_id, "subscriber_id": sid},
                {"_id": 0}).limit(5):
            out.append(a)
        return out

    async def _equipment():
        out = []
        async for e in db.client_equipment_history.find(
                {"company_id": company_id, "subscriber_id": sid,
                 "kind": {"$ne": "current_state"}},
                {"_id": 0, "id": 1, "kind": 1, "stage": 1, "serial": 1,
                 "model": 1, "ts": 1, "action": 1}
        ).sort("ts", -1).limit(5):
            out.append(e)
        return out

    async def _last_invoice():
        return await db.subscriber_invoices.find_one(
            {"company_id": company_id, "subscriber_id": sid},
            {"_id": 0, "id": 1, "status": 1, "amount": 1, "due_date": 1,
             "paid_at": 1, "competence": 1},
            sort=[("due_date", -1)])

    async def _recent_tickets():
        out = []
        async for t in db.tickets.find(
                {"company_id": company_id,
                 "$or": [{"client_id": sid},
                          {"client_snapshot.subscriber_id": sid}]},
                {"_id": 0, "id": 1, "type": 1, "status": 1,
                 "scheduled_time": 1, "created_at": 1, "outcome": 1}
        ).sort("created_at", -1).limit(5):
            out.append(t)
        return out

    sub, addresses, equipment, last_invoice, recent_tickets = await asyncio.gather(
        sub_task, _addresses(), _equipment(), _last_invoice(), _recent_tickets()
    )

    out = {
        "subscriber": sub,
        "link": link,
        "addresses": addresses,
        "equipment": equipment,
        "last_invoice": last_invoice,
        "recent_tickets": recent_tickets,
        "timing_ms": int((time.time() - started) * 1000),
        "cached": False,
    }
    _cache_put(cache_key, out)
    return out


def format_for_isabella(identity: Dict[str, Any]) -> str:
    """Converte identity_360 em bloco curto pronto para o system prompt."""
    sub = identity.get("subscriber") or {}
    if not sub:
        return ""
    lines: List[str] = ["=== IDENTIDADE 360° DO CLIENTE ==="]
    lines.append(f"Nome: {sub.get('name')}")
    plan = sub.get("plan_name") or "?"
    price = sub.get("plan_price") or sub.get("monthly_value")
    if price:
        lines.append(f"Plano: {plan} (R$ {float(price):.2f}/mês)")
    else:
        lines.append(f"Plano: {plan}")
    lines.append(f"Status: {sub.get('status', '—')}")
    if sub.get("address"):
        lines.append(f"Endereço: {sub.get('address')}"
                      + (f" · {sub.get('neighborhood')}"
                         if sub.get("neighborhood") else ""))
    addresses = identity.get("addresses") or []
    if addresses:
        lines.append(f"Endereços cadastrados ({len(addresses)}):")
        for a in addresses[:2]:
            label = a.get("label") or ""
            line = a.get("street") or a.get("address") or ""
            lines.append(f"  • {label} {line}".strip())

    eq = identity.get("equipment") or []
    if eq:
        last = eq[0]
        lines.append(f"Último equipamento: {last.get('model') or last.get('serial') or last.get('kind')} "
                      f"({last.get('stage') or last.get('action')})")

    inv = identity.get("last_invoice")
    if inv:
        st = inv.get("status", "?")
        amt = inv.get("amount")
        due = inv.get("due_date")
        lines.append(f"Última fatura: R$ {float(amt or 0):.2f} · {st} · venc {due}")

    tickets = identity.get("recent_tickets") or []
    if tickets:
        lines.append(f"OS recentes ({len(tickets)}):")
        for t in tickets[:3]:
            lines.append(f"  • {t.get('type', '?')} · {t.get('status', '?')} · {t.get('created_at', '?')[:10]}")

    lines.append(f"(timing: {identity.get('timing_ms', 0)}ms · cached={identity.get('cached', False)})")
    return "\n".join(lines)
