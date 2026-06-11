"""SmartOLT VLAN sync worker (iter180).

Loop em background que:
1. Periodicamente roda a mesma sync que o botão "Aplicar" do painel
   (ler `service_ports[].vlan` do SmartOLT → `subscribers.current_vlan`).
2. Quando detecta MUDANÇA de VLAN num assinante já mapeado, emite um
   `network_tickets` do tipo `vlan_change_unexpected` (alta prioridade
   se o tipo do assinante for "PJ" ou plano > R$ 200).
3. Mantém histórico em `subscriber_vlan_history` para auditoria.

Roda 1x por hora por padrão (env `SMARTOLT_VLAN_SYNC_INTERVAL_S`, default
3600). Pode ser desligado com `SMARTOLT_VLAN_SYNC_ENABLED=false`.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "infra-team",
    "domain": "rede",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database import db

log = logging.getLogger("smartolt_vlan_sync")


async def _detect_and_apply_for_company(cid: str) -> Dict[str, Any]:
    """Executa a sync para uma empresa. Idêntica ao endpoint, porém
    também emite tickets quando há MUDANÇA real de VLAN (≠ first set)."""
    cursor = db.smartolt_onus.find(
        {"company_id": cid, "status": "Online"},
        {"_id": 0, "service_ports": 1, "pppoe_user": 1, "sn": 1,
         "olt_name": 1, "board": 1, "port": 1, "name": 1},
    )
    summary = {
        "company_id": cid, "scanned": 0, "with_vlan": 0,
        "updated": 0, "unchanged": 0, "no_subscriber": 0,
        "tickets_created": 0, "vlan_changes": [],
    }
    async for o in cursor:
        summary["scanned"] += 1
        sp_list = o.get("service_ports") or []
        vlan_raw: Optional[str] = None
        for sp in sp_list:
            v = (sp or {}).get("vlan")
            if v not in (None, "", "0"):
                vlan_raw = v
                break
        if not vlan_raw:
            continue
        try:
            vlan = int(str(vlan_raw).strip())
        except Exception:
            continue
        summary["with_vlan"] += 1

        sub = None
        match_kind = None
        if o.get("pppoe_user"):
            sub = await db.subscribers.find_one(
                {"company_id": cid, "pppoe_user": o["pppoe_user"]},
                {"_id": 0, "id": 1, "name": 1, "current_vlan": 1,
                 "plan_price": 1, "current_vlan_olt": 1,
                 "current_vlan_pon": 1},
            )
            if sub:
                match_kind = "pppoe"
        if sub is None and o.get("name"):
            sub = await db.subscribers.find_one(
                {"company_id": cid, "pppoe_user": o["name"]},
                {"_id": 0, "id": 1, "name": 1, "current_vlan": 1,
                 "plan_price": 1, "current_vlan_olt": 1,
                 "current_vlan_pon": 1},
            )
            if sub:
                match_kind = "name"
        if sub is None and o.get("sn"):
            sub = await db.subscribers.find_one(
                {"company_id": cid, "metadata.sn": o["sn"]},
                {"_id": 0, "id": 1, "name": 1, "current_vlan": 1,
                 "plan_price": 1, "current_vlan_olt": 1,
                 "current_vlan_pon": 1},
            )
            if sub:
                match_kind = "sn"
        if sub is None:
            summary["no_subscriber"] += 1
            continue

        prev_vlan = sub.get("current_vlan")
        pon = f"{o.get('board')}/{o.get('port')}"
        if prev_vlan == vlan:
            summary["unchanged"] += 1
            continue

        # ---- Atualiza assinante ----------------------------------------
        await db.subscribers.update_one(
            {"id": sub["id"]},
            {"$set": {
                "current_vlan": vlan,
                "current_vlan_synced_at": datetime.now(timezone.utc).isoformat(),
                "current_vlan_source": "smartolt",
                "current_vlan_match": match_kind,
                "current_vlan_olt": o.get("olt_name"),
                "current_vlan_pon": pon,
            }},
        )
        summary["updated"] += 1

        # ---- Histórico -------------------------------------------------
        await db.subscriber_vlan_history.insert_one({
            "id": str(uuid.uuid4()),
            "company_id": cid,
            "subscriber_id": sub["id"],
            "subscriber_name": sub.get("name"),
            "previous_vlan": prev_vlan,
            "new_vlan": vlan,
            "olt": o.get("olt_name"), "pon": pon,
            "match": match_kind,
            "changed_at": datetime.now(timezone.utc).isoformat(),
            "first_set": prev_vlan is None,
        })

        # ---- Ticket SOMENTE em mudança real (não first-set) ------------
        if prev_vlan is not None and prev_vlan != vlan:
            plan_price = float(sub.get("plan_price") or 0)
            priority = "alta" if plan_price > 200 else "media"
            ticket = {
                "id": f"tk-{uuid.uuid4().hex[:10]}",
                "company_id": cid,
                "type": "vlan_change_unexpected",
                "subtype": "vlan_change",
                "priority": priority,
                "title": f"VLAN mudou: {sub.get('name')} ({prev_vlan} → {vlan})",
                "summary": (
                    f"Assinante {sub.get('name')} migrou de VLAN {prev_vlan} "
                    f"para {vlan} sem solicitação registrada. "
                    f"OLT={o.get('olt_name')} PON={pon} match={match_kind}."
                ),
                "status": "open",
                "source": "smartolt_vlan_sync_worker",
                "subscriber_id": sub["id"],
                "previous_vlan": prev_vlan, "new_vlan": vlan,
                "olt": o.get("olt_name"), "pon": pon,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                await db.network_tickets.insert_one(ticket)
                summary["tickets_created"] += 1
            except Exception as e:
                log.warning("[vlan-sync] insert ticket falhou: %s", e)

        if len(summary["vlan_changes"]) < 20:
            summary["vlan_changes"].append({
                "subscriber_name": sub.get("name"),
                "previous_vlan": prev_vlan, "new_vlan": vlan,
                "first_set": prev_vlan is None,
                "olt": o.get("olt_name"), "pon": pon,
            })

    if summary["updated"] or summary["tickets_created"]:
        log.info("[vlan-sync] company=%s scanned=%s updated=%s tickets=%s",
                    cid, summary["scanned"], summary["updated"],
                    summary["tickets_created"])
    return summary


async def _loop():
    interval = int(os.environ.get("SMARTOLT_VLAN_SYNC_INTERVAL_S", "3600"))
    enabled = os.environ.get("SMARTOLT_VLAN_SYNC_ENABLED", "true").lower() != "false"
    if not enabled:
        log.info("[vlan-sync] worker desabilitado via env")
        return
    log.info("[vlan-sync] worker iniciado (interval=%ss)", interval)
    while True:
        try:
            # 1 sync por company que tem credenciais SmartOLT
            async for cfg in db.smartolt_config.find(
                {"api_key": {"$nin": [None, ""]}},
                {"_id": 0, "company_id": 1},
            ):
                cid = cfg.get("company_id")
                if not cid:
                    continue
                try:
                    await _detect_and_apply_for_company(cid)
                except Exception as e:
                    log.warning("[vlan-sync] company=%s falhou: %s", cid, e)
                # iter180 — Enriquece MAC de até 30 ONUs/empresa por ciclo
                # (1h = 30 chamadas → ~720/dia, dentro do budget 1000/h global).
                try:
                    await _backfill_macs_for_company(cid, batch=30)
                except Exception as e:
                    log.warning("[mac-backfill] company=%s falhou: %s", cid, e)
        except Exception as e:  # pragma: no cover
            log.exception("[vlan-sync] loop falhou: %s", e)
        await asyncio.sleep(interval)


async def _backfill_macs_for_company(cid: str, batch: int = 30) -> None:
    """Pega ONUs Online sem MAC e tenta resolver chamando o endpoint
    per-ONU da SmartOLT. Ignora silenciosamente se não houver config.
    """
    from routes.smartolt import refresh_onu_mac  # lazy import
    pending = await db.smartolt_onus.find(
        {"company_id": cid, "status": "Online",
         "$or": [{"mac": None}, {"mac": ""}, {"mac": {"$exists": False}}]},
        {"_id": 0, "unique_external_id": 1},
    ).sort("synced_at", -1).limit(batch).to_list(batch)
    if not pending:
        return
    fake_user = {"company_id": cid, "role": "gestor"}
    resolved = 0
    for o in pending:
        ext = o.get("unique_external_id")
        if not ext:
            continue
        try:
            r = await refresh_onu_mac(ext, fake_user)
            if r.get("ok"):
                resolved += 1
        except Exception:
            # falha em 1 ONU não interrompe o batch
            continue
    if resolved:
        log.info("[mac-backfill] company=%s resolved=%s/%s",
                    cid, resolved, len(pending))


def start_worker():
    """Inicia o worker em background. Idempotente — chamadas adicionais
    são ignoradas."""
    if getattr(start_worker, "_started", False):
        return
    asyncio.create_task(_loop())
    start_worker._started = True  # type: ignore[attr-defined]
