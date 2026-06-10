"""SHIELD DAILY AUDIT — auditoria adversarial diária 04:00.

Executa bateria leve do Red Team Shield (sem reqs HTTP — chamadas
internas), grava snapshot em `shield_audit_history` e, se qualquer
eixo macro cair abaixo de B, registra oportunidade no Conselho IA
(`isabella_commander_opportunities` kind='shield_alert').

Diferente do `scripts/red_team_shield.py` (manual, exige token HTTP),
este job roda no event loop do servidor — sem rede, sem login.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac as _hmac
import json as _j
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from apscheduler.triggers.cron import CronTrigger

from database import db
from services import (audit_chain, backup_service, event_signing,
                        health_center, observability, secrets_vault)

log = logging.getLogger("ponto.shield_daily")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _grade(ratio: float) -> str:
    if ratio >= 0.95: return "A"
    if ratio >= 0.85: return "B"
    if ratio >= 0.70: return "C"
    if ratio >= 0.50: return "D"
    return "E"


async def run_audit() -> Dict[str, Any]:
    """Executa bateria reduzida e retorna dossiê."""
    checks: List[Dict[str, Any]] = []

    def add(name, ok, detail=None):
        checks.append({"name": name, "ok": ok,
                        "detail": detail or {}})

    # 1) Event Signing — sign + verify + forgery + replay + expired
    try:
        env = event_signing.sign({"daily": True},
                                    event_type="shield.daily.probe",
                                    company_id="*")
        v = event_signing.verify_signature(env)
        add("event_signing.verify_clean", v["ok"], v)
        forged = dict(env); forged["payload"] = {"daily": False}
        vf = event_signing.verify_signature(forged)
        add("event_signing.detects_forgery", not vf["ok"], vf)
        c1 = await event_signing.consume(env)
        c2 = await event_signing.consume(env)
        add("event_signing.detects_replay",
             c1["accepted"] and not c2["accepted"],
             {"replay_reason": c2.get("reason")})
        # expired
        old_ts = int(time.time()) - 3600
        old_nonce = uuid.uuid4().hex[:16]
        canonical = (f"x.y|*|{old_ts}|{old_nonce}|"
                      f"{_j.dumps({'x':'y'},sort_keys=True,separators=(',',':'))}")
        from services.event_signing import _secret
        old_sig = _hmac.new(_secret(), canonical.encode(),
                              hashlib.sha256).hexdigest()
        ve = event_signing.verify_signature(
            {"event_type": "x.y", "company_id": "*", "ts": old_ts,
             "nonce": old_nonce, "signature": old_sig, "payload": {"x": "y"}})
        add("event_signing.detects_expired",
             (not ve["ok"]) and ve.get("reason") == "expired_or_future", ve)
    except Exception as e:
        add("event_signing.exception", False, {"error": str(e)[:200]})

    # 2) Audit Chain — append + verify + tamper
    try:
        key = f"daily-{datetime.now(timezone.utc).strftime('%Y%m%d')}"
        for i in range(3):
            await audit_chain.append(
                chain_key=key, actor="shield_daily",
                action="probe", payload={"i": i})
        v = await audit_chain.verify_chain(key)
        add("audit_chain.verify_clean",
             v["ok"] and v["records_verified"] >= 3, v)
        # tamper test on a transient key
        tk = f"daily-tamper-{uuid.uuid4().hex[:8]}"
        await audit_chain.append(chain_key=tk, actor="shield_daily",
                                   action="probe", payload={"a": 1})
        await audit_chain.append(chain_key=tk, actor="shield_daily",
                                   action="probe", payload={"a": 2})
        await db.audit_chain.update_one(
            {"chain_key": tk, "seq": 1},
            {"$set": {"payload.a": 999}})
        v2 = await audit_chain.verify_chain(tk)
        add("audit_chain.detects_tamper", not v2["ok"], v2)
        await db.audit_chain.delete_many({"chain_key": tk})
    except Exception as e:
        add("audit_chain.exception", False, {"error": str(e)[:200]})

    # 3) Vault — set/get/encrypted
    try:
        if not secrets_vault.is_available():
            add("vault.available", False, {"reason": "no master key"})
        else:
            n = f"daily_probe_{uuid.uuid4().hex[:6]}"
            v = "secret-" + uuid.uuid4().hex
            await secrets_vault.set_secret(n, v, updated_by="shield_daily")
            raw = await db.secrets_vault.find_one({"name": n})
            enc_ok = raw and v not in raw.get("ciphertext", "")
            add("vault.encrypted", bool(enc_ok),
                 {"ciphertext_prefix": (raw or {}).get("ciphertext", "")[:20]})
            got = await secrets_vault.get_secret(n,
                                                   accessed_by="shield_daily")
            add("vault.roundtrip", got == v, {})
            await secrets_vault.delete_secret(n, deleted_by="shield_daily")
    except Exception as e:
        add("vault.exception", False, {"error": str(e)[:200]})

    # 4) Backup — mongodump real
    try:
        bk = await backup_service.backup_now()
        add("backup.runs", bk.get("ok"),
             {"elapsed_s": bk.get("elapsed_seconds"),
              "bytes": bk.get("bytes"),
              "files": bk.get("files")})
        ver = await backup_service.verify_last()
        add("backup.verify", ver.get("ok"), ver)
    except Exception as e:
        add("backup.exception", False, {"error": str(e)[:200]})

    # 5) DR drill — restore + counts
    try:
        dr = await backup_service.disaster_recovery_drill()
        add("dr.drill", dr.get("restore_ok"),
             {"rto_s": dr.get("rto_seconds"),
              "rpo_s": dr.get("rpo_seconds"),
              "fidelity_pct": dr.get("restore_fidelity_pct")})
    except Exception as e:
        add("dr.exception", False, {"error": str(e)[:200]})

    # 6) Health snapshot
    try:
        snap = await health_center.snapshot()
        add("health.online", snap["overall"] == "ONLINE",
             {"overall": snap["overall"]})
    except Exception as e:
        add("health.exception", False, {"error": str(e)[:200]})

    # ----- Consolidação por eixo -----
    def section_ratio(prefix_tuple):
        items = [c for c in checks
                  if c["name"].startswith(prefix_tuple)]
        if not items: return 1.0
        return sum(1 for c in items if c["ok"]) / len(items)

    seguranca = _grade(section_ratio(("event_signing.", "audit_chain.",
                                          "vault.")))
    resiliencia = _grade(section_ratio(("backup.", "dr.")))
    observabilidade = _grade(section_ratio(("health.",)))
    # performance é derivada de observabilidade no daily (sem carga http)
    performance = observabilidade

    grades = {"seguranca": seguranca, "resiliencia": resiliencia,
              "performance": performance,
              "observabilidade": observabilidade}
    # overall = pior eixo (a corrente é tão forte quanto o elo mais fraco)
    overall = max(grades.values(), key="ABCDE".index)

    record = {
        "id": f"shield-{uuid.uuid4().hex[:12]}",
        "ts": _now(),
        "kind": "daily_audit",
        "checks": checks,
        "grades": grades,
        "overall_grade": overall,
        "total_checks": len(checks),
        "passed": sum(1 for c in checks if c["ok"]),
    }
    await db.shield_audit_history.insert_one(dict(record))

    # ----- Alerta no Conselho IA -----
    weak = [k for k, g in grades.items() if g >= "C"]  # C, D, E
    if weak:
        try:
            opp = {
                "id": f"opp-shield-{uuid.uuid4().hex[:10]}",
                "company_id": "co-demo",  # global; pode ser sobrescrito
                "kind": "shield_alert",
                "subkind": "_".join(weak),
                "score": 100,  # crítico
                "probability": 1.0,
                "status": "pending",
                "target_label": "Blindagem Total — Eixo abaixo de B",
                "evidence": {"audit_id": record["id"],
                              "grades": grades, "weak_axes": weak},
                "reason_codes": [f"axis_{k}_below_B" for k in weak],
                "recommended_action": {
                    "type": "shield_review",
                    "message": (f"Eixos com nota < B: {', '.join(weak)}. "
                                 "Investigar logs do shield_daily_audit + "
                                 "rodar `python3 scripts/red_team_shield.py` "
                                 "manual."),
                },
                "impact_brl": 0,
                "created_at": _now(),
            }
            await db.isabella_commander_opportunities.insert_one(dict(opp))
            record["alert_opportunity_id"] = opp["id"]
        except Exception as e:
            log.warning("[shield_daily] alert failed: %r", e)

    log.info("[shield_daily] audit_id=%s overall=%s grades=%s passed=%d/%d",
              record["id"], overall, grades,
              record["passed"], record["total_checks"])
    return record


async def daily_job():
    """Wrapper para APScheduler."""
    try:
        await run_audit()
    except Exception as e:
        log.error("[shield_daily] job crashed: %r", e)


def register_scheduler(scheduler) -> None:
    """Registra o job diário 04:00 UTC."""
    scheduler.add_job(
        daily_job,
        CronTrigger(hour=4, minute=0),
        id="shield_daily_audit",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    log.info("[startup] shield_daily_audit registered (04:00 UTC)")


async def ensure_indexes() -> None:
    try:
        await db.shield_audit_history.create_index([("ts", -1)])
        await db.shield_audit_history.create_index([("overall_grade", 1),
                                                       ("ts", -1)])
        # TTL 365 dias
        await db.shield_audit_history.create_index(
            "ts", expireAfterSeconds=365 * 86400,
            name="shield_history_ttl")
    except Exception as e:
        log.warning("[shield_daily] indexes: %s", e)
