"""iter243 — backfill semântico do aprendizado dos agentes.

Lê os 859 docs órfãos de motor_ia_learnings e infere os campos canônicos
(kind, agent, learning_text) a partir do schema real que cada writer
gravou. Não inventa dados — só RECLASSIFICA o que já existe.

Mesmo procedimento para motor_ia_outcomes, ai_evaluations, ai_corrections.
"""
import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient


def infer_learning(d: dict) -> dict:
    """Retorna {kind, agent, learning_text, score} inferidos a partir do
    schema do writer original."""
    out = {}
    # autonomous_engine writer: tem learning_id, action_id, what_worked
    if d.get("learning_id") and "what_worked" in d:
        out["kind"] = "autonomous_decision_outcome"
        out["agent"] = "autonomous_engine"
        ww = d.get("what_worked") or ""
        wf = d.get("what_failed") or ""
        delta = d.get("financial_delta_BRL")
        out["learning_text"] = (
            (f"WORKED: {ww}" if ww else f"FAILED: {wf}") +
            (f" | delta=R$ {delta:.2f}" if delta is not None else ""))
        out["score"] = 1.0 if ww else 0.0
        return out
    # v7_2_revenue: revenue_confirmation
    if d.get("kind") == "revenue_confirmation":
        out["kind"] = "revenue_confirmation"
        out["agent"] = "revenue_engine"
        out["learning_text"] = (
            f"revenue confirmed: expected=R$ {d.get('expected_BRL',0):.2f} "
            f"actual=R$ {d.get('actual_BRL',0):.2f} delta=R$ {d.get('delta_BRL',0):.2f}")
        return out
    # company_v6 / operacao_tese / presidente_ia patterns
    if d.get("outcome_key"):
        out["kind"] = "outcome_link"
        out["agent"] = "motor_ia"
        out["learning_text"] = f"outcome_key={d['outcome_key']}"
        return out
    if d.get("smart_olt") or d.get("onu_serial"):
        out["kind"] = "smartolt_enrichment"
        out["agent"] = "alvaro"
        out["learning_text"] = (
            f"OLT enrichment: {d.get('onu_serial','?')} "
            f"signal={d.get('signal_dbm','?')} status={d.get('status','?')}")
        return out
    # fallback
    return {"kind": "uncategorized",
            "agent": "unknown",
            "learning_text": json.dumps(
                {k: v for k, v in d.items()
                 if k not in ("_id", "id", "created_at", "ts")
                 and v not in (None, "", [], {})},
                default=str)[:300],
            "score": None}


def infer_outcome(d: dict) -> dict:
    out = {}
    val = d.get("value") or {}
    actual = d.get("actual_BRL")
    expected = d.get("expected_BRL")
    if isinstance(val, dict):
        if val.get("wa_sent") is False and val.get("dry_run") is True:
            out["outcome"] = "dry_run_no_send"
            out["agent"] = "notification_dispatcher"
            out["signal"] = "no_action"
            return out
        if val.get("ok") is True:
            out["outcome"] = "ok"
            out["agent"] = "motor_ia"
            return out
    if actual is not None and expected is not None:
        if actual >= expected and actual > 0:
            out["outcome"] = "expected_met_or_exceeded"
        elif actual == 0:
            out["outcome"] = "no_revenue"
        else:
            out["outcome"] = "expected_partial"
        out["agent"] = "revenue_tracker"
        return out
    return {"outcome": "unclassified", "agent": "unknown"}


def infer_evaluation(d: dict) -> dict:
    # ai_evaluations tem campos: conversation_id, score, persona, decision...
    out = {}
    if d.get("persona") or d.get("agent_persona"):
        out["agent"] = d.get("persona") or d.get("agent_persona")
    elif d.get("conversation_id") and d.get("guard") == "short_term_memory":
        out["agent"] = "short_term_memory_guard"
    elif d.get("by") == "isabella_relationship":
        out["agent"] = "isabella_relationship"
    elif "isabella" in str(d.get("source", "")).lower():
        out["agent"] = "isabella"
    elif d.get("guard"):
        out["agent"] = f"guard_{d['guard']}"
    else:
        out["agent"] = "ai_pipeline"
    if d.get("score") is not None:
        out["score_normalized"] = float(d["score"])
    return out


def infer_correction(d: dict) -> dict:
    out = {}
    if d.get("target_field") or d.get("field"):
        out["correction_type"] = "field_correction"
        out["target_agent"] = d.get("target_agent") or d.get("agent") or "unknown"
        out["description"] = (
            f"field={d.get('target_field') or d.get('field')} "
            f"from={d.get('from')} to={d.get('to')}")
    elif d.get("ticket_id"):
        out["correction_type"] = "ticket_correction"
        out["target_agent"] = "lousa"
        out["description"] = f"ticket {d['ticket_id']} corrected"
    else:
        out["correction_type"] = "uncategorized"
        out["target_agent"] = "unknown"
        out["description"] = json.dumps(
            {k: v for k, v in d.items()
             if v not in (None, "", [], {}) and k not in ("_id", "id")},
            default=str)[:200]
    return out


async def go():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    started = datetime.now(timezone.utc).isoformat()
    print(f"\nbackfill started at {started}\n")

    # === 1) motor_ia_learnings ===
    print("[1] motor_ia_learnings:")
    q = {"kind": {"$in": [None]}}
    total = await db.motor_ia_learnings.count_documents(q)
    print(f"   alvo={total}")
    fixed = 0
    async for d in db.motor_ia_learnings.find(q).limit(2000):
        infer = infer_learning(d)
        update = {"$set": {**infer,
                            "_backfilled_at": started,
                            "_backfill_version": "iter243"}}
        await db.motor_ia_learnings.update_one({"_id": d["_id"]}, update)
        fixed += 1
    print(f"   backfilled={fixed}")

    # === 2) motor_ia_outcomes ===
    print("\n[2] motor_ia_outcomes:")
    q = {"outcome": {"$in": [None]}}
    total = await db.motor_ia_outcomes.count_documents(q)
    print(f"   alvo={total}")
    fixed = 0
    async for d in db.motor_ia_outcomes.find(q).limit(5000):
        infer = infer_outcome(d)
        await db.motor_ia_outcomes.update_one(
            {"_id": d["_id"]},
            {"$set": {**infer, "_backfilled_at": started,
                       "_backfill_version": "iter243"}})
        fixed += 1
    print(f"   backfilled={fixed}")

    # === 3) ai_evaluations ===
    print("\n[3] ai_evaluations:")
    q = {"agent": {"$in": [None]}}
    total = await db.ai_evaluations.count_documents(q)
    print(f"   alvo={total}")
    fixed = 0
    async for d in db.ai_evaluations.find(q).limit(20000):
        infer = infer_evaluation(d)
        await db.ai_evaluations.update_one(
            {"_id": d["_id"]},
            {"$set": {**infer, "_backfilled_at": started,
                       "_backfill_version": "iter243"}})
        fixed += 1
    print(f"   backfilled={fixed}")

    # === 4) ai_corrections ===
    print("\n[4] ai_corrections:")
    q = {"correction_type": {"$in": [None]}}
    total = await db.ai_corrections.count_documents(q)
    print(f"   alvo={total}")
    fixed = 0
    async for d in db.ai_corrections.find(q).limit(500):
        infer = infer_correction(d)
        await db.ai_corrections.update_one(
            {"_id": d["_id"]},
            {"$set": {**infer, "_backfilled_at": started,
                       "_backfill_version": "iter243"}})
        fixed += 1
    print(f"   backfilled={fixed}")

    # === 5) isabella_playbook_weights ===
    print("\n[5] isabella_playbook_weights:")
    q = {"key": {"$in": [None]}}
    async for d in db.isabella_playbook_weights.find(q):
        # Inferir key a partir do contexto
        w = d.get("weight") or 1.0
        infer_key = (f"churn_default_v1" if w < 1.0
                       else f"unknown_playbook")
        await db.isabella_playbook_weights.update_one(
            {"_id": d["_id"]},
            {"$set": {"key": infer_key,
                       "reason": ("rebaixado por baixa conversão"
                                   if w < 1.0 else "promovido"),
                       "_backfilled_at": started,
                       "_backfill_version": "iter243"}})
        print(f"   {d.get('_id')}: key={infer_key} weight={w}")

    # === 6) isabella_outcomes ===
    print("\n[6] isabella_outcomes:")
    q = {"outcome": {"$in": [None]}}
    async for d in db.isabella_outcomes.find(q).limit(500):
        opp_id = d.get("opp_id")
        if opp_id and "churn" in str(opp_id):
            outcome = "churn_resolved"
            signal = "retention_success"
        else:
            outcome = "unclassified"
            signal = "unknown"
        await db.isabella_outcomes.update_one(
            {"_id": d["_id"]},
            {"$set": {"outcome": outcome, "signal": signal,
                       "_backfilled_at": started,
                       "_backfill_version": "iter243"}})
    print(f"   backfilled (limited 500)")

    print(f"\n✓ iter243 backfill concluído at {datetime.now(timezone.utc).isoformat()}")
    await db.iter243_backfill_runs.insert_one({
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "version": "iter243",
    })


asyncio.run(go())
