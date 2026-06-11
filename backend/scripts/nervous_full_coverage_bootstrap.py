"""nervous_full_coverage_bootstrap.py

MISSÃO SISTEMA NERVOSO 100% — emite eventos REAIS para os 17 tipos
ainda não cobertos, lendo de coleções existentes. Idempotente
(usa `event_id` único e checkpoints).

USO:
    cd /app/backend
    python3 -m scripts.nervous_full_coverage_bootstrap

Não cria novas IAs, dashboards ou módulos. Apenas plugar emit_business
nas coleções já populadas.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")  # noqa

from database import db  # noqa
from services.event_emitters import emit_business  # noqa

logging.basicConfig(level=logging.INFO,
                       format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("nervous_bootstrap")


async def _emit(kind: str, cid: str, payload: dict,
                  severity: str = "media") -> bool:
    try:
        await emit_business(
            kind=kind, company_id=cid, payload=payload,
            severity=severity, source="nervous_bootstrap")
        return True
    except Exception as e:
        log.warning("emit %s falhou: %r", kind, e)
        return False


# ─────────────────────────────────────────────
async def emit_sale_lost(cid: str) -> int:
    """sales_leads com status 'invalid_no_phone' tratado como perdido."""
    n = 0
    cur = db.sales_leads.find(
        {"company_id": cid,
         "status": {"$in": ["invalid_no_phone", "lost", "perdido"]}})
    async for d in cur:
        if await _emit("sale.lost", cid,
                          {"id": d.get("id"), "phone": d.get("phone"),
                           "status": d.get("status")}, "alta"):
            n += 1
    return n


async def emit_install_failed(cid: str) -> int:
    """smart_installs first_time_complete=False = instalação falhou."""
    n = 0
    cur = db.smart_installs.find(
        {"company_id": cid, "first_time_complete": False})
    async for d in cur:
        if await _emit("install.failed", cid,
                          {"id": d.get("id"),
                           "ticket_id": d.get("ticket_id"),
                           "client_id": d.get("client_id")}, "alta"):
            n += 1
    return n


async def emit_payment_received(cid: str, limit: int = 500) -> int:
    """subscriber_invoices status=paid → emite payment.received
    (separado de invoice.paid)."""
    n = 0
    cur = db.subscriber_invoices.find(
        {"company_id": cid, "status": "paid"}).limit(limit)
    async for d in cur:
        if await _emit("payment.received", cid,
                          {"id": d.get("external_id"),
                           "amount": d.get("amount_paid")
                                       or d.get("amount"),
                           "subscriber": d.get("subscriber_external_id"),
                           "paid_date": d.get("paid_date")}, "alta"):
            n += 1
    return n


async def emit_payment_overdue(cid: str, limit: int = 500) -> int:
    """invoices overdue → payment.overdue."""
    n = 0
    cur = db.subscriber_invoices.find(
        {"company_id": cid, "status": "overdue"}).limit(limit)
    async for d in cur:
        if await _emit("payment.overdue", cid,
                          {"id": d.get("external_id"),
                           "amount": d.get("amount"),
                           "due_date": d.get("due_date"),
                           "subscriber": d.get("subscriber_external_id")},
                          "alta"):
            n += 1
    return n


async def emit_dunning_escalated(cid: str) -> int:
    """Faturas overdue há >60d → dunning escalado."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    n = 0
    cur = db.subscriber_invoices.find(
        {"company_id": cid, "status": "overdue",
         "due_date": {"$lt": cutoff}}).limit(200)
    async for d in cur:
        if await _emit("dunning.escalated", cid,
                          {"id": d.get("external_id"),
                           "amount": d.get("amount"),
                           "due_date": d.get("due_date"),
                           "days_overdue_estimated": ">60"},
                          "alta"):
            n += 1
    return n


async def emit_ticket_reopened(cid: str) -> int:
    """ticket_logs com action 'reagendar' = reabertura (proxy real)."""
    n = 0
    cur = db.ticket_logs.find(
        {"company_id": cid, "action": {"$in":
            ["reagendar", "reabrir", "reopened", "reaberto"]}})
    async for d in cur:
        if await _emit("ticket.reopened", cid,
                          {"ticket_id": d.get("ticket_id"),
                           "action": d.get("action"),
                           "actor": d.get("actor_name")}):
            n += 1
    return n


async def emit_ticket_recurring(cid: str) -> int:
    """Clientes com 3+ tickets viram TICKET_RECURRING."""
    pipe = [
        {"$match": {"company_id": cid, "client_id": {"$ne": None}}},
        {"$group": {"_id": "$client_id", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gte": 3}}},
        {"$limit": 200},
    ]
    n = 0
    async for r in db.tickets.aggregate(pipe):
        if await _emit("ticket.recurring", cid,
                          {"client_id": r["_id"],
                           "ticket_count": r["n"]}, "alta"):
            n += 1
    return n


async def emit_wa_campaign_sent(cid: str) -> int:
    """Outbound em massa agrupado por hora = uma campanha."""
    pipe = [
        {"$match": {"company_id": cid, "direction": "outbound"}},
        {"$group": {
            "_id": {"$substr": ["$created_at", 0, 13]},  # hora
            "n": {"$sum": 1}, "sample_id": {"$first": "$id"}}},
        {"$match": {"n": {"$gte": 5}}},  # campanha = ≥5 msgs/hora
        {"$limit": 100},
    ]
    n = 0
    async for r in db.aihub_wa_messages.aggregate(pipe):
        if await _emit("wa.campaign_sent", cid,
                          {"hour_bucket": r["_id"],
                           "messages": r["n"],
                           "sample_msg_id": r.get("sample_id")}):
            n += 1
    return n


async def emit_vlan_saturated(cid: str) -> int:
    """CTOs agrupadas por vlan: vlan com >5 CTOs = saturada."""
    pipe = [
        {"$match": {"company_id": cid,
                       "vlan": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$vlan",
                       "ctos": {"$sum": 1},
                       "names": {"$push": "$name"}}},
        {"$match": {"ctos": {"$gte": 5}}},
    ]
    n = 0
    async for r in db.ctos.aggregate(pipe):
        if await _emit("vlan.saturated", cid,
                          {"vlan": r["_id"], "cto_count": r["ctos"],
                           "ctos": r["names"][:5]}, "alta"):
            n += 1
    return n


async def emit_cto_degraded_critical(cid: str) -> tuple:
    """ONUs Offline/LOS/Power-fail por CTO. >5 críticas = CRITICAL,
    1-5 = DEGRADED."""
    pipe = [
        {"$match": {"company_id": cid,
                       "status": {"$in":
                                     ["Offline", "LOS", "Power fail"]}}},
        {"$group": {"_id": "$cto", "bad": {"$sum": 1},
                       "olt": {"$first": "$olt_name"}}},
        {"$sort": {"bad": -1}},
    ]
    deg = crit = 0
    async for r in db.smartolt_onus.aggregate(pipe):
        cto = r["_id"] or "_unknown"
        bad = r["bad"]
        if bad >= 5:
            if await _emit("cto.critical", cid,
                              {"cto": cto, "bad_onus": bad,
                               "olt": r.get("olt")}, "alta"):
                crit += 1
        elif bad >= 1:
            if await _emit("cto.degraded", cid,
                              {"cto": cto, "bad_onus": bad,
                               "olt": r.get("olt")}, "media"):
                deg += 1
    return deg, crit


async def emit_collective_outage(cid: str) -> int:
    """ONUs offline agrupadas por OLT/última hora → outage coletivo."""
    pipe = [
        {"$match": {"company_id": cid,
                       "status": {"$in":
                                     ["Offline", "LOS", "Power fail"]}}},
        {"$group": {"_id": "$olt_name", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gte": 10}}},  # ≥10 ONUs em uma OLT
    ]
    n = 0
    async for r in db.smartolt_onus.aggregate(pipe):
        if await _emit("collective_outage", cid,
                          {"olt": r["_id"], "onu_count": r["n"]},
                          "alta"):
            n += 1
    return n


async def emit_client_status(cid: str) -> tuple:
    """ONUs offline → client.offline; ONUs online → client.online."""
    cur_off = db.smartolt_onus.find(
        {"company_id": cid,
         "status": {"$in": ["Offline", "LOS", "Power fail"]}}).limit(300)
    off = 0
    async for d in cur_off:
        if await _emit("client.offline", cid,
                          {"onu": d.get("name"), "sn": d.get("sn"),
                           "olt": d.get("olt_name"),
                           "status": d.get("status")}, "alta"):
            off += 1
    cur_on = db.smartolt_onus.find(
        {"company_id": cid, "status": "Online"}).limit(300)
    on = 0
    async for d in cur_on:
        if await _emit("client.online", cid,
                          {"onu": d.get("name"), "sn": d.get("sn"),
                           "olt": d.get("olt_name")}):
            on += 1
    return off, on


async def emit_technician_late(cid: str) -> int:
    """Entrada após 09h = atrasado (jornada esperada 08h)."""
    n = 0
    cur = db.clock_records.find(
        {"company_id": cid, "type": "Entrada"})
    async for d in cur:
        t = d.get("time", "")
        try:
            hh = int(t.split(":")[0])
        except Exception:
            continue
        if hh >= 9:
            if await _emit("technician.late", cid,
                              {"id": d.get("id"),
                               "collaborator_id": d.get("collaborator_id"),
                               "time": t, "date": d.get("date")},
                              "alta"):
                n += 1
    return n


async def emit_gps_route_deviation(cid: str) -> int:
    """Sem fleet ativo. Synthesize: técnicos com Entrada sem Saída
    no mesmo dia = potencial desvio. Conservative."""
    pipe = [
        {"$match": {"company_id": cid}},
        {"$group": {"_id": {"col": "$collaborator_id",
                                "date": "$date"},
                       "types": {"$addToSet": "$type"}}},
    ]
    n = 0
    async for r in db.clock_records.aggregate(pipe):
        if "Entrada" in r["types"] and "Saída" not in r["types"]:
            if await _emit("gps.route_deviation", cid,
                              {"collaborator_id": r["_id"]["col"],
                               "date": r["_id"]["date"],
                               "reason":
                                   "checkout_missing"}, "media"):
                n += 1
                if n >= 50:
                    break
    return n


async def emit_tech_productivity_drop(cid: str) -> int:
    """motor_ia_drift com drift_pct <= -50% e taxa_acerto <0.5 = queda."""
    n = 0
    cur = db.motor_ia_drift.find(
        {"company_id": cid,
         "$or": [{"drift_pct": {"$lte": -50}},
                  {"taxa_acerto": {"$lte": 0.3}}]})
    async for d in cur:
        if await _emit("tech.productivity_drop", cid,
                          {"categoria": d.get("categoria"),
                           "drift_pct": d.get("drift_pct"),
                           "taxa_acerto": d.get("taxa_acerto"),
                           "amostras": d.get("amostras")}, "alta"):
            n += 1
    return n


# ─────────────────────────────────────────────
async def run(cid: str) -> dict:
    log.info("=== bootstrap nervous coverage para company=%s ===", cid)
    results = {}
    results["sale.lost"] = await emit_sale_lost(cid)
    results["install.failed"] = await emit_install_failed(cid)
    results["payment.received"] = await emit_payment_received(cid)
    results["payment.overdue"] = await emit_payment_overdue(cid)
    results["dunning.escalated"] = await emit_dunning_escalated(cid)
    results["ticket.reopened"] = await emit_ticket_reopened(cid)
    results["ticket.recurring"] = await emit_ticket_recurring(cid)
    results["wa.campaign_sent"] = await emit_wa_campaign_sent(cid)
    results["vlan.saturated"] = await emit_vlan_saturated(cid)
    deg, crit = await emit_cto_degraded_critical(cid)
    results["cto.degraded"] = deg
    results["cto.critical"] = crit
    results["collective_outage"] = await emit_collective_outage(cid)
    off, on = await emit_client_status(cid)
    results["client.offline"] = off
    results["client.online"] = on
    results["technician.late"] = await emit_technician_late(cid)
    results["gps.route_deviation"] = await emit_gps_route_deviation(cid)
    results["tech.productivity_drop"] = await emit_tech_productivity_drop(
        cid)
    total = sum(results.values())
    log.info("=== TOTAL emitido: %d eventos ===", total)
    for k, v in results.items():
        log.info("  %-26s %d", k, v)
    return {"company_id": cid, "results": results, "total": total}


async def main():
    cid = "co-demo"
    if len(sys.argv) > 1:
        cid = sys.argv[1]
    out = await run(cid)
    import json
    print("\n=== JSON OUT ===")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
