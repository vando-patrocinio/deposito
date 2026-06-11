"""ZERO MOCK — testes dos Isabella Commanders (Churn, Dunning, Revenue,
Twin, Expansion, Conselho) executando contra a base REAL.

Validações (sem unittest.mock):
  1. ARPU é resolvido (companies.arpu ou cálculo real ou fallback)
  2. Cada scanner roda, persiste oportunidades em isabella_opportunities
     e marca campos críticos (score, probability, impact_brl)
  3. KPIs agregam corretamente o que foi escrito
  4. Conselho gera ata com decisões + financial_summary
  5. 1-click approval troca status de pending → approved (auditável)

Uso: `python3 /app/backend/scripts/test_isabella_commanders.py`
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
from services import (isabella_churn, isabella_conselho, isabella_dunning,  # noqa: E402
                        isabella_expansion, isabella_revenue, isabella_twin)
from services.isabella_opportunities import (  # noqa: E402
    ensure_indexes, get_arpu, kpis, list_opportunities, update_status)


def _ok(cond: bool, msg: str) -> None:
    icon = "✅" if cond else "❌"
    print(f"  {icon} {msg}")
    if not cond:
        raise AssertionError(msg)


async def _pick_company() -> str:
    """Escolhe empresa com volume real (invoices + tickets)."""
    pipe = [{"$group": {"_id": "$company_id", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}}, {"$limit": 1}]
    rows = await db.subscriber_invoices.aggregate(pipe).to_list(1)
    if rows and rows[0]["_id"]:
        return rows[0]["_id"]
    rows = await db.tickets.aggregate(pipe).to_list(1)
    if rows and rows[0]["_id"]:
        return rows[0]["_id"]
    cid = await db.companies.find_one({}, {"_id": 0, "id": 1})
    return cid["id"]


async def main() -> int:
    failed = 0
    await ensure_indexes()
    company = await _pick_company()
    print(f"== Empresa alvo: {company}")

    # 1) ARPU
    print("\n[1] ARPU resolution")
    try:
        arpu = await get_arpu(company)
        _ok(isinstance(arpu, float) and arpu > 0,
            f"get_arpu retornou valor positivo ({arpu:.2f})")
    except Exception as e:
        failed += 1
        print(f"  ❌ get_arpu falhou: {e}")

    # snapshot inicial
    pre = await db.isabella_commander_opportunities.count_documents(
        {"company_id": company})

    # 2) Scans
    print("\n[2] Scans dos 5 Commanders")
    results = {}
    for name, fn in (("churn", isabella_churn.scan_company),
                       ("dunning", isabella_dunning.scan_company),
                       ("revenue", isabella_revenue.scan_company),
                       ("twin", isabella_twin.scan_company),
                       ("expansion", isabella_expansion.scan_company)):
        try:
            r = await fn(company)
            results[name] = r
            print(f"  ▶ {name}: {r}")
        except Exception as e:
            failed += 1
            print(f"  ❌ scan {name} falhou: {e}")

    # 3) Coleção populada com schema esperado
    print("\n[3] Persistência em isabella_opportunities")
    post = await db.isabella_commander_opportunities.count_documents(
        {"company_id": company})
    print(f"  total antes={pre} depois={post}")
    sample = await db.isabella_commander_opportunities.find_one(
        {"company_id": company}, {"_id": 0},
        sort=[("created_at", -1)])
    if sample:
        for k in ("id", "kind", "subkind", "target_type", "target_id",
                    "score", "probability", "impact_brl", "reason_codes",
                    "evidence", "recommended_action", "status",
                    "created_at", "expires_at"):
            try:
                _ok(k in sample, f"campo `{k}` presente")
            except AssertionError:
                failed += 1
        try:
            _ok(0 <= sample["score"] <= 100, "score em [0,100]")
            _ok(0 <= sample["probability"] <= 1, "probability em [0,1]")
            _ok(sample["status"] in ("pending", "approved",
                                        "dismissed", "executed",
                                        "expired"),
                f"status válido ({sample['status']})")
        except AssertionError:
            failed += 1
    else:
        print("  ⚠ nenhuma oportunidade gerada (DB sem sinais para esta empresa)")

    # 4) KPIs
    print("\n[4] KPIs agregados")
    try:
        k = await kpis(company)
        _ok("by_kind" in k and "totals" in k,
            "kpis retornou chaves by_kind/totals")
    except Exception as e:
        failed += 1
        print(f"  ❌ kpis falhou: {e}")

    # 5) 1-click approval
    print("\n[5] Aprovação 1-clique")
    pending = await list_opportunities(company_id=company,
                                          status="pending", limit=1)
    if pending:
        opp_id = pending[0]["id"]
        try:
            updated = await update_status(opp_id, company,
                                            status="approved",
                                            actor="test_agent@ligo.system")
            _ok(updated["status"] == "approved",
                f"oportunidade {opp_id} → approved")
            _ok(updated.get("approved_by") == "test_agent@ligo.system",
                "approved_by gravado")
            # rollback
            await update_status(opp_id, company, status="dismissed",
                                  actor="test_agent_rollback",
                                  notes="rollback do teste")
        except Exception as e:
            failed += 1
            print(f"  ❌ aprovação falhou: {e}")
    else:
        print("  ⚠ sem oportunidades pendentes para testar aprovação")

    # 6) Conselho
    print("\n[6] Reunião do Conselho Executivo")
    try:
        ata = await isabella_conselho.hold_meeting(company)
        _ok("decisions" in ata and isinstance(ata["decisions"], list),
            f"ata possui {len(ata['decisions'])} decisões")
        _ok("financial_summary" in ata,
            "ata possui financial_summary")
        fs = ata["financial_summary"]
        for k in ("revenue_potential_brl", "loss_at_risk_brl",
                    "net_outlook_brl"):
            _ok(k in fs, f"financial_summary[{k}] presente")
    except Exception as e:
        failed += 1
        print(f"  ❌ Conselho falhou: {e}")

    # 7) Event bus auditável
    print("\n[7] Eventos de auditoria")
    types = ["churn.risk.scored", "dunning.step.recommended",
              "revenue.opportunity.detected", "twin.failure.predicted",
              "expansion.area.recommended", "council.meeting.held",
              "opportunity.created", "opportunity.approved",
              "opportunity.dismissed"]
    found = await db.motor_ia_events.distinct(
        "event_type", {"company_id": company,
                        "event_type": {"$in": types}})
    print(f"  eventos vistos: {sorted(found)}")
    _ok(len(found) >= 1, "ao menos 1 tipo de evento foi emitido")

    # 8) Mass-notify incident
    print("\n[8] Mass-notify de incidente (fake transport)")
    import os
    os.environ["SMARTPROV_TRANSPORT_FAKE"] = "1"
    from services.isabella_incident import mass_notify_incident
    inc = await db.isabella_incidents.find_one(
        {"company_id": company,
         "status": {"$in": ["predicted", "confirmed"]}},
        {"_id": 0, "id": 1})
    if inc:
        r = await mass_notify_incident(company, inc["id"], phase="opened",
                                          actor="test_agent")
        _ok(r.get("ok") is True, f"mass_notify retornou ok=True (sent={r.get('sent')}, skipped={r.get('skipped')})")
        log_doc = await db.isabella_incident_notifications.find_one(
            {"incident_id": inc["id"], "actor": "test_agent"},
            {"_id": 0}, sort=[("created_at", -1)])
        _ok(log_doc is not None, "log de notificação persistido")
    else:
        print("  ⚠ sem incidente aberto para esta empresa")

    print("\n" + ("OK" if failed == 0 else f"FAILED {failed}"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
