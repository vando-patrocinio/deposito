"""ISABELLA DUNNING COMMANDER — régua unificada de inadimplência.

Pipeline autônomo orquestrando lembrete → negociação → desbloqueio →
bloqueio com base em sinais REAIS (`subscriber_invoices`).

Steps determinísticos:
  • D-3   reminder_pre  → lembrete prévio
  • D+1   reminder_late → atraso leve
  • D+5   negotiation   → oferta de parcelamento
  • D+10  unblock_offer → reativação se quitou parcial
  • D+15  warning       → aviso final
  • D+20  block_request → solicita bloqueio (humano aprova)

Cada step vira `isabella_opportunities(kind=dunning)` com `recommended_action`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from database import db
from services.event_bus import EventType, emit_event
from services.isabella_opportunities import upsert_opportunity

log = logging.getLogger("ponto.isabella_dunning")


def _now():
    return datetime.now(timezone.utc)


def _step_for(days_overdue: int) -> Tuple[str, float, str, Dict[str, Any]]:
    """Retorna (subkind, score, msg, action_dict)."""
    if days_overdue < 0 and days_overdue >= -3:
        return ("reminder_pre", 25,
                "Lembrete prévio de vencimento",
                {"type": "send_reminder", "channel": "whatsapp",
                  "template": "lembrete_pre_vencimento"})
    if 0 <= days_overdue <= 2:
        return ("reminder_late", 40,
                "Aviso de atraso leve (D+0~D+2)",
                {"type": "send_reminder", "channel": "whatsapp",
                  "template": "lembrete_atraso_leve"})
    if 3 <= days_overdue <= 8:
        return ("negotiation", 60,
                "Oferta de negociação/parcelamento",
                {"type": "send_negotiation", "channel": "whatsapp",
                  "template": "negociacao_parcelamento"})
    if 9 <= days_overdue <= 14:
        return ("unblock_offer", 65,
                "Reativação condicional (acordo)",
                {"type": "send_offer", "channel": "whatsapp",
                  "template": "reativacao_condicional"})
    if 15 <= days_overdue <= 19:
        return ("warning", 80,
                "Aviso final — bloqueio iminente",
                {"type": "send_warning", "channel": "whatsapp",
                  "template": "aviso_final_bloqueio"})
    if days_overdue >= 20:
        return ("block_request", 95,
                "Solicitar bloqueio (aprovação humana)",
                {"type": "block_subscriber", "channel": "smartolt",
                  "requires_approval": True})
    return ("monitor", 10, "Monitorar", {"type": "noop"})


async def _overdue_invoices(company_id: str) -> List[Dict[str, Any]]:
    """Faturas em open/overdue com due_date <= hoje+3 (inclui lembrete pré)."""
    horizon = (_now() + timedelta(days=3)).date().isoformat()
    cur = db.subscriber_invoices.find(
        {"company_id": company_id,
         "status": {"$in": ["open", "overdue"]},
         "due_date": {"$lte": horizon}},
        {"_id": 0, "subscriber_external_id": 1, "subscriber_name": 1,
         "amount": 1, "due_date": 1, "status": 1, "id": 1,
         "subscriber_document": 1}
    )
    return await cur.to_list(20000)


async def scan_company(company_id: str, *, limit: int = 1000) -> Dict[str, Any]:
    invoices = await _overdue_invoices(company_id)
    if not invoices:
        return {"company_id": company_id, "invoices": 0, "opportunities": 0}

    # agrupa por subscriber_external_id (pior fatura prevalece)
    today = _now().date()
    by_sub: Dict[str, Dict[str, Any]] = {}
    for inv in invoices:
        sid = inv.get("subscriber_external_id")
        if not sid:
            continue
        try:
            due = datetime.strptime(inv["due_date"], "%Y-%m-%d").date()
        except Exception:
            continue
        days_overdue = (today - due).days
        slot = by_sub.setdefault(str(sid), {
            "name": inv.get("subscriber_name"),
            "document": inv.get("subscriber_document"),
            "total": 0.0,
            "invoices": [],
            "max_days_overdue": days_overdue,
        })
        slot["total"] += float(inv.get("amount") or 0)
        slot["invoices"].append({"id": inv.get("id"),
                                    "due": inv["due_date"],
                                    "amount": float(inv.get("amount") or 0),
                                    "status": inv.get("status"),
                                    "days_overdue": days_overdue})
        slot["max_days_overdue"] = max(slot["max_days_overdue"], days_overdue)

    # mapeia para subscribers (pega phone, plan, id)
    ext_ids = list(by_sub.keys())
    expanded = set()
    for k in ext_ids:
        expanded.add(k)
        expanded.add(f"ATLAZ-{k}")
    subs = await db.subscribers.find(
        {"company_id": company_id, "external_code": {"$in": list(expanded)}},
        {"_id": 0, "id": 1, "external_code": 1, "name": 1, "phone": 1,
         "plan_name": 1}
    ).to_list(20000)

    def _norm(c):
        c = (c or "").strip()
        return c.split("-", 1)[1].strip() if c.upper().startswith("ATLAZ-") else c
    sub_map = {_norm(s["external_code"]): s for s in subs}

    created = 0
    for ext, data in by_sub.items():
        sub = sub_map.get(ext)
        if not sub:
            continue
        d = data["max_days_overdue"]
        subkind, score, msg, action = _step_for(d)
        if action["type"] == "noop":
            continue
        action_payload = {**action,
                          "subscriber_id": sub["id"],
                          "subscriber_external_id": ext,
                          "phone": sub.get("phone"),
                          "total_due_brl": round(data["total"], 2),
                          "invoices": data["invoices"][:10]}
        await upsert_opportunity(
            company_id=company_id,
            kind="dunning",
            subkind=subkind,
            target_type="subscriber",
            target_id=sub["id"],
            target_label=f"{sub.get('name') or ext} ({ext})",
            score=score,
            probability=min(0.95, 0.30 + 0.03 * max(d, 0)),
            impact_brl=round(data["total"], 2),
            reason_codes=[msg,
                          f"{len(data['invoices'])} fatura(s) — atraso máximo {d}d"],
            evidence={"max_days_overdue": d,
                      "total_due_brl": round(data["total"], 2),
                      "invoices": data["invoices"][:10],
                      "phone": sub.get("phone"),
                      "plan_name": sub.get("plan_name"),
                      "document": data.get("document")},
            recommended_action=action_payload,
            ttl_hours=48,
            source="isabella_dunning",
        )
        created += 1
        await emit_event(
            EventType.DUNNING_STEP_RECOMMENDED,
            company_id=company_id, source="isabella_dunning",
            severity="critica" if d >= 15 else ("alta" if d >= 5 else "media"),
            payload={"subscriber_id": sub["id"], "subkind": subkind,
                      "days_overdue": d, "total_due_brl": round(data["total"], 2)})
        if created >= limit:
            break

    return {"company_id": company_id,
            "invoices_in_scope": len(invoices),
            "subscribers": len(by_sub),
            "opportunities": created}


async def scan_all() -> List[Dict[str, Any]]:
    out = []
    cids = await db.companies.distinct("id")
    for cid in cids:
        try:
            out.append(await scan_company(cid))
        except Exception as e:
            log.exception("[dunning] %s failed: %s", cid, e)
    return out
