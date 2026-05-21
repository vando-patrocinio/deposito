"""CTO ↔ SmartOLT Audit — conciliação de clientes.

Cruza:
- ONUs (clientes) ativos no SmartOLT (`smartolt_onus`)
- Portas de CTO ocupadas (`ctos.ports[].client_subscriber_id` / `client_pppoe`)

Gera 3 listas:
1. ORPHAN_ONUS — ONU ativa no SmartOLT mas SEM vínculo em nenhuma CTO
2. GHOST_PORTS — Porta de CTO marcada como "used" mas ONU não existe/desativada no SmartOLT
3. SUMMARY     — Totais por company_id
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db

log = logging.getLogger("cto_audit")


async def run_audit_for_company(company_id: str) -> Dict[str, Any]:
    """Executa conciliação para uma empresa. Retorna o resumo e salva
    o resultado em `cto_audits` (1 doc por execução).
    """
    # 1. Pega todas portas usadas de todas CTOs da company
    used_pppoes: Dict[str, Dict[str, Any]] = {}  # pppoe → {cto_id, cto_name, port}
    used_subs: Dict[str, Dict[str, Any]] = {}    # subscriber_id → {cto_id, cto_name, port}
    cto_count = 0
    ctos = db.ctos.find({"company_id": company_id},
                            {"_id": 0, "id": 1, "name": 1, "ports": 1})
    async for c in ctos:
        cto_count += 1
        for p in (c.get("ports") or []):
            if (p.get("status") or "") != "used":
                continue
            entry = {"cto_id": c["id"], "cto_name": c.get("name"),
                       "port_number": p.get("number")}
            pp = (p.get("client_pppoe") or "").strip().lower()
            sid = (p.get("client_subscriber_id") or "")
            if pp:
                used_pppoes[pp] = entry
            if sid:
                used_subs[str(sid)] = entry

    # 2. Pega ONUs ativas do SmartOLT
    onus = db.smartolt_onus.find(
        {"company_id": company_id,
         "$or": [{"status": "online"}, {"status": "Online"},
                  {"status": {"$exists": False}}]},
        {"_id": 0, "olt_name": 1, "board": 1, "port": 1, "onu": 1,
          "sn": 1, "name": 1, "signal_text": 1, "status": 1,
          "subscriber_id": 1, "pppoe_user": 1, "zone_name": 1,
          "address": 1, "phone": 1},
    )

    orphans: List[Dict[str, Any]] = []
    matched = 0
    async for o in onus:
        sid = o.get("subscriber_id")
        pp = (o.get("pppoe_user") or "").strip().lower()
        # Match?
        in_cto = (sid and str(sid) in used_subs) or (pp and pp in used_pppoes)
        if in_cto:
            matched += 1
            continue
        orphans.append({
            "name": o.get("name") or "—",
            "subscriber_id": sid,
            "pppoe_user": o.get("pppoe_user"),
            "sn": o.get("sn"),
            "olt_name": o.get("olt_name"),
            "board": o.get("board"),
            "port": o.get("port"),
            "onu": o.get("onu"),
            "zone_name": o.get("zone_name"),
            "address": o.get("address"),
            "phone": o.get("phone"),
            "signal_text": o.get("signal_text"),
            "status": o.get("status"),
        })

    # 3. Ghost ports: portas marcadas como used mas sem ONU correspondente
    all_seen_pppoes = set()
    all_seen_subs = set()
    onus2 = db.smartolt_onus.find({"company_id": company_id},
                                       {"_id": 0, "subscriber_id": 1, "pppoe_user": 1})
    async for o in onus2:
        if o.get("subscriber_id"):
            all_seen_subs.add(str(o["subscriber_id"]))
        if o.get("pppoe_user"):
            all_seen_pppoes.add(str(o["pppoe_user"]).strip().lower())

    ghosts: List[Dict[str, Any]] = []
    ctos2 = db.ctos.find({"company_id": company_id},
                              {"_id": 0, "id": 1, "name": 1, "ports": 1})
    async for c in ctos2:
        for p in (c.get("ports") or []):
            if (p.get("status") or "") != "used":
                continue
            pp = (p.get("client_pppoe") or "").strip().lower()
            sid = (p.get("client_subscriber_id") or "")
            found = (pp and pp in all_seen_pppoes) or \
                    (sid and str(sid) in all_seen_subs)
            if not found:
                ghosts.append({
                    "cto_id": c["id"], "cto_name": c.get("name"),
                    "port_number": p.get("number"),
                    "client_name": p.get("client_name"),
                    "client_pppoe": p.get("client_pppoe"),
                    "client_subscriber_id": p.get("client_subscriber_id"),
                    "connected_at": p.get("connected_at"),
                })

    summary = {
        "company_id": company_id,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "cto_count": cto_count,
        "ports_used_total": len(used_pppoes) + len(used_subs),
        "onus_matched": matched,
        "orphan_count": len(orphans),
        "ghost_count": len(ghosts),
    }

    # Salva
    try:
        await db.cto_audits.insert_one({
            **summary,
            "orphans_sample": orphans[:50],
            "ghosts_sample": ghosts[:50],
        })
        # Limita histórico — mantém últimos 30
        cnt = await db.cto_audits.count_documents({"company_id": company_id})
        if cnt > 30:
            old = db.cto_audits.find({"company_id": company_id}) \
                                  .sort("executed_at", 1).limit(cnt - 30)
            old_ids = [doc.get("_id") async for doc in old]
            if old_ids:
                await db.cto_audits.delete_many({"_id": {"$in": old_ids}})
    except Exception as e:
        log.warning("Salvar audit falhou: %s", e)

    return {
        "summary": summary,
        "orphans": orphans,
        "ghosts": ghosts,
    }


async def nightly_audit_job() -> None:
    """Job 3h da manhã: roda auditoria para TODAS as companies ativas."""
    log.info("[cto_audit] nightly start")
    try:
        companies = await db.companies.find({}, {"_id": 0, "id": 1}).to_list(200)
    except Exception:
        companies = [{"id": "co-demo"}]
    for c in companies:
        cid = c.get("id")
        if not cid:
            continue
        try:
            r = await run_audit_for_company(cid)
            s = r["summary"]
            log.info("[cto_audit] %s · orphans=%s · ghosts=%s · matched=%s",
                       cid, s["orphan_count"], s["ghost_count"], s["onus_matched"])
        except Exception as e:
            log.warning("[cto_audit] company=%s falhou: %s", cid, e)
    log.info("[cto_audit] nightly done")
