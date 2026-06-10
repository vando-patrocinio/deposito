"""Evidências complementares — Evolução Final V2.

A) Premium vs Comum: roda o mesmo cenário em 2 subscribers (1 com churn>0.6,
   outro com churn=0.0) e prova que `premium_repair.active` difere.

B) Filtro oportunidades: conta isabella_opportunities geradas por threshold 55
   vs threshold 80 (baseline antigo).
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")

from database import db  # noqa: E402
from services.isabella_ceo_followup import register_followup  # noqa: E402


COMPANY_ID = os.environ.get("DEMO_COMPANY_ID", "co-demo")


async def _seed_sub(churn: float, suffix: str) -> str:
    sid = f"sub-evol2-{suffix}-{uuid.uuid4().hex[:6]}"
    await db.subscribers.insert_one({
        "id": sid,
        "company_id": COMPANY_ID,
        "name": f"Teste-{suffix}",
        "phones": [f"55119900000{suffix}"],
        "plan_name": "Fibra 300MB",
        "monthly_value": 99.90,
        "plan_value": 99.90,
        "plan_price": 99.90,
        "status": "ACTIVE",
        "activated_at": "2025-01-01T00:00:00+00:00",
        "created_at": "2025-01-01T00:00:00+00:00",
        "churn_score": churn,
    })
    return sid


async def main() -> None:
    user_text = "minha internet caiu, não está funcionando"
    reply = ("Identifiquei o problema. Equipe técnica acionada. "
             "Objetivo: restaurar. Responsável: equipe técnica. "
             "Prazo: hoje 18h. Confirmação: te aviso. Outcome: PLANO_DE_ACAO")

    # A) Premium vs Comum
    sid_premium = await _seed_sub(0.85, "VIP")
    sid_comum = await _seed_sub(0.10, "OK")

    doc_premium = await register_followup(
        company_id=COMPANY_ID, subscriber_id=sid_premium,
        phone="5511990000001", user_text=user_text,
        isabella_reply=reply, context_used="")
    doc_comum = await register_followup(
        company_id=COMPANY_ID, subscriber_id=sid_comum,
        phone="5511990000002", user_text=user_text,
        isabella_reply=reply, context_used="")

    diff_premium = {
        "subscriber_premium": sid_premium,
        "premium_repair_active": doc_premium["premium_repair"]["active"],
        "reasons": doc_premium["premium_repair"]["reasons"],
        "outcome": doc_premium["outcome"],
        "nps": doc_premium["nps_inferido"],
    }
    diff_comum = {
        "subscriber_comum": sid_comum,
        "premium_repair_active": doc_comum["premium_repair"]["active"],
        "reasons": doc_comum["premium_repair"]["reasons"],
        "outcome": doc_comum["outcome"],
        "nps": doc_comum["nps_inferido"],
    }
    a_pass = (diff_premium["premium_repair_active"] is True
              and diff_comum["premium_repair_active"] is False)

    # B) Filtro de oportunidades — usa 2 subs únicos com upgrade_score=65
    #    (entre 55 e 80) para evidenciar diferença
    sid_for_55 = f"sub-th55-{uuid.uuid4().hex[:6]}"
    sid_for_80 = f"sub-th80-{uuid.uuid4().hex[:6]}"
    for sid in (sid_for_55, sid_for_80):
        await db.subscribers.insert_one({
            "id": sid, "company_id": COMPANY_ID,
            "name": sid, "phones": [],
            "status": "ACTIVE", "monthly_value": 99.90,
        })
        await db.motor_ia_subscriber_scores.update_one(
            {"company_id": COMPANY_ID, "subscriber_id": sid},
            {"$set": {
                "company_id": COMPANY_ID,
                "subscriber_id": sid,
                "buy_score": 65, "churn_score": 65,
                "referral_score": 65, "retention_score": 65,
                "upgrade_score": 65, "collection_score": 65,
            }}, upsert=True)

    # Limpa opps prévias destes 2 subs
    await db.isabella_opportunities.delete_many(
        {"company_id": COMPANY_ID, "subscriber_id": {"$in": [sid_for_55, sid_for_80]}})

    from services.isabella_scoring import run_playbooks

    # Roda com threshold 80 → não deve criar
    os.environ["ISABELLA_OPP_MIN_SCORE"] = "80"
    await run_playbooks(COMPANY_ID)
    opps_80 = await db.isabella_opportunities.count_documents(
        {"company_id": COMPANY_ID, "subscriber_id": sid_for_80})

    # Roda com threshold 55 → DEVE criar (4 tipos: upgrade/referral/collection/retention)
    os.environ["ISABELLA_OPP_MIN_SCORE"] = "55"
    await run_playbooks(COMPANY_ID)
    opps_55 = await db.isabella_opportunities.count_documents(
        {"company_id": COMPANY_ID, "subscriber_id": sid_for_55})

    b_pass = opps_55 > 0 and opps_80 == 0

    out = {
        "premium_vs_comum": {
            "premium_doc": diff_premium,
            "comum_doc": diff_comum,
            "pass": a_pass,
        },
        "filtro_oportunidades": {
            "subscriber_score_65": True,
            "opps_geradas_threshold_55": opps_55,
            "opps_geradas_threshold_80": opps_80,
            "pass": b_pass,
        },
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    out_path = "/app/docs/EVIDENCIA_ISABELLA_PREMIUM_E_FILTRO.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\n[ok] gravado em {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
