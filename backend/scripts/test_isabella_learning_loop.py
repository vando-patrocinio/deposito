"""ZERO MOCK — Ciclo de aprendizado da Isabella Nível 6.

Testa o LOOP COMPLETO em base REAL:

  1. Cria oportunidades (via scans dos Commanders)
  2. Aprovação 1-clique → outcome aberto + attempt contado
  3. Forçar resolução do outcome (DB real → success/failure/inconclusive)
  4. Pesos atualizados em isabella_playbook_weights
  5. Conselho com decisões IDed + precision
  6. Memória Executiva: cria policy, valida bloqueio, sugere via dismisses
  7. Execution Score: ROI consolidado calculado contra DB real
  8. Recommend: reordena candidatos por adjusted_score

Uso: python3 /app/backend/scripts/test_isabella_learning_loop.py
"""

NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import db  # noqa: E402
from services import isabella_churn  # noqa: E402
from services import isabella_conselho  # noqa: E402
from services import isabella_execution_score as exec_score  # noqa: E402
from services import isabella_executive_memory as memory_eng  # noqa: E402
from services import isabella_learning as learning_eng  # noqa: E402
from services import isabella_outcome_engine as outcome_eng  # noqa: E402
from services.isabella_opportunities import (  # noqa: E402
    ensure_indexes as opp_indexes, get_opportunity, list_opportunities,
    update_status)


def _ok(cond: bool, msg: str) -> None:
    icon = "✅" if cond else "❌"
    print(f"  {icon} {msg}")
    if not cond:
        raise AssertionError(msg)


async def _pick_company() -> str:
    pipe = [{"$group": {"_id": "$company_id", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}}, {"$limit": 1}]
    rows = await db.subscriber_invoices.aggregate(pipe).to_list(1)
    return rows[0]["_id"] if rows else "co-demo"


async def main() -> int:
    failed = 0
    await opp_indexes()
    await outcome_eng.ensure_indexes()
    await learning_eng.ensure_indexes()
    await memory_eng.ensure_indexes()
    company = await _pick_company()
    print(f"== Empresa: {company}")

    # ---------------------------------------------------------------
    # [1] Garante oportunidades pendentes (gera se vazias)
    # ---------------------------------------------------------------
    print("\n[1] Garantir oportunidades para o teste")
    pend = await list_opportunities(company_id=company, kind="churn",
                                       limit=5)
    if not pend:
        await isabella_churn.scan_company(company)
        pend = await list_opportunities(company_id=company,
                                          kind="churn", limit=5)
    if not pend:
        # fallback dunning
        pend = await list_opportunities(company_id=company,
                                          kind="dunning", limit=5)
    _ok(len(pend) > 0, f"existem oportunidades pendentes (n={len(pend)})")

    # ---------------------------------------------------------------
    # [2] Aprovação → abre outcome + record_attempt
    # ---------------------------------------------------------------
    print("\n[2] Aprovação dispara outcome+attempt")
    opp = pend[0]
    await update_status(opp["id"], company, status="approved",
                          actor="test_loop@ligo.system")
    refetched = await get_opportunity(opp["id"], company)
    _ok(refetched["status"] == "approved", "status approved persistido")
    outc = await outcome_eng.open_outcome(opp, actor="test_loop")
    _ok(outc.get("id", "").startswith("out-"), f"outcome aberto: {outc.get('id')}")
    await learning_eng.record_attempt(
        company_id=company, kind=opp["kind"],
        subkind=opp.get("subkind") or "",
        playbook=(opp.get("recommended_action") or {}).get("playbook")
                  or (opp.get("recommended_action") or {}).get("type") or "")
    w_doc = await db.isabella_playbook_weights.find_one(
        {"company_id": company, "kind": opp["kind"]}, {"_id": 0})
    _ok(w_doc is not None, "weight registry criado")

    # ---------------------------------------------------------------
    # [3] Forçar resolução de outcomes pending
    # ---------------------------------------------------------------
    print("\n[3] Resolver outcomes")
    r = await outcome_eng.resolve_due(force=True, limit=50)
    print(f"  resolved={r.get('resolved')} success={r.get('success')} failure={r.get('failure')} incon={r.get('inconclusive')}")
    _ok(r.get("resolved", 0) >= 1, "ao menos 1 outcome resolvido")

    # ---------------------------------------------------------------
    # [4] Pesos atualizados
    # ---------------------------------------------------------------
    print("\n[4] Learning weights")
    weights = await learning_eng.top_playbooks(company, limit=10)
    _ok(len(weights) >= 1, f"{len(weights)} entrada(s) de peso registradas")
    for w in weights[:3]:
        print(f"  · {w.get('kind')}/{w.get('subkind')}/{w.get('playbook')} "
                f"weight={w.get('weight')} conf={w.get('confidence')} "
                f"S={w.get('successes')} F={w.get('failures')}")
    # Recommend reorder
    cands = [
        {"subkind": "schedule_repair", "playbook": "visita_tecnica_priorizada",
         "score": 60},
        {"subkind": "retention_offer", "playbook": "diretor_call_back",
         "score": 60},
        {"subkind": "satisfaction_survey", "playbook": "nps_proativo",
         "score": 60},
    ]
    ordered = await learning_eng.recommend(company_id=company,
                                              kind="churn",
                                              candidates=cands)
    _ok(len(ordered) == 3 and "adjusted_score" in ordered[0],
        f"recommend reordenou: top={ordered[0].get('playbook')}")

    # ---------------------------------------------------------------
    # [5] Conselho com decisões IDed + precision endpoint
    # ---------------------------------------------------------------
    print("\n[5] Conselho — decisões com ID")
    ata = await isabella_conselho.hold_meeting(company)
    decs = ata.get("decisions") or []
    _ok(all(("id" in d and d["id"].startswith("dec-")) for d in decs),
        f"todas as {len(decs)} decisões têm id único")
    _ok(all("predicted_outcome_brl" in d for d in decs),
        "todas as decisões trazem predicted_outcome_brl")

    # ---------------------------------------------------------------
    # [6] Executive memory
    # ---------------------------------------------------------------
    print("\n[6] Executive Memory")
    pol = await memory_eng.add_policy(
        company_id=company,
        scope="subkind",
        action="block",
        condition={"discount_pct": {"$gt": 50}},
        decided_by="cto@ligo.system",
        reason="CTO: descontos acima de 50% nunca mais sem aprovação",
        kind="churn", subkind="retention_offer")
    _ok(pol["id"].startswith("pol-"), f"policy criada {pol['id']}")
    pols = await memory_eng.list_policies(company)
    _ok(any(p["id"] == pol["id"] for p in pols),
        "policy listada e ativa")
    # Suppressão
    fake_opp = [{
        "id": "opp-test-block",
        "kind": "churn", "subkind": "retention_offer",
        "score": 90,
        "evidence": {"discount_pct": 70},
        "recommended_action": {"playbook": "diretor_call_back"},
    }]
    fil = await memory_eng.filter_opportunities(company, fake_opp)
    _ok(len(fil["blocked"]) == 1,
        f"policy bloqueou oportunidade com discount>50% "
        f"(blocked={len(fil['blocked'])})")
    # Suggestions
    sug = await memory_eng.learn_from_dismissals(company, days=60,
                                                    threshold=1)
    print(f"  sugestões detectadas: {len(sug)}")
    _ok(isinstance(sug, list), "endpoint de sugestões responde lista")
    # Cleanup policy
    await memory_eng.deactivate(company, pol["id"], "test_loop")

    # ---------------------------------------------------------------
    # [7] Execution Score
    # ---------------------------------------------------------------
    print("\n[7] Execution Score")
    es = await exec_score.compute(company, days=90)
    for k in ("components", "opportunities", "outcomes",
                "roi_real_brl_total", "precision_rate"):
        _ok(k in es, f"execution_score.{k} presente")
    print(f"  ROI total: R$ {es['roi_real_brl_total']:.2f} "
          f"| precision={es['precision_rate']} "
          f"| engagement={es['opportunities']['engagement_rate']}")

    # ---------------------------------------------------------------
    # [8] Outcomes stats endpoint-grade
    # ---------------------------------------------------------------
    print("\n[8] Outcome stats")
    stats = await outcome_eng.stats(company, days=120)
    _ok("totals" in stats and "by_playbook" in stats,
        "stats retorna totals + by_playbook")
    print(f"  totals: {stats['totals']}")

    print("\n" + ("OK" if failed == 0 else f"FAILED {failed}"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
