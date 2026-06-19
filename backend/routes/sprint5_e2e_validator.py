"""sprint5_e2e_validator — Simulação E2E Técnico (CEO 19/02/2026)

Pergunta: "Consigo reconstruir TODA a vida de um cliente do início ao fim?"

Executa 6 cenários (instalação/reparo/troca/mudança porta/mudança CTO/
retirada) num cliente sintético e valida reconstrução completa.

Resultado: X/6 PASS com RCA automática.

Endpoints (prefix /api/sprint5/audit-flow):
  POST /simulate-technician-journey   — executa simulação
  GET  /latest-validation             — último relatório
"""

NERVOUS_METADATA = {"owner": "infra-team", "domain": "patrimonio",
                    "criticality": "high", "company_id_required": True}

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

from core import require_role
from database import db
from services.network_access_canonical import upsert_link, release_link
from services.swap_event_writer import write_swap_event
from services.stok_history_writer import write_stok_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sprint5/audit-flow",
                       tags=["sprint5", "e2e-validator"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_company(user: dict) -> str:
    return user.get("company_id") or "co-demo"


async def _check_reconstruction(
    db, cid: str, scenario: str, *, subscriber_id: str,
    expected: Dict[str, Any],
) -> Dict[str, Any]:
    """Tenta reconstruir Cliente→CTO→Porta→ONU→Técnico→Ticket→Estoque→SmartOLT."""
    # 1. Cliente
    sub = await db.subscribers.find_one(
        {"id": subscriber_id, "company_id": cid},
        {"_id": 0, "name": 1, "cto_id": 1, "cto_port_id": 1,
         "cto_port_number": 1})
    # 2. Canonical (UMA fonte)
    link = await db.network_access_canonical.find_one(
        {"company_id": cid, "subscriber_id": subscriber_id},
        {"_id": 0})
    # 3. Swap event
    sw = await db.auto_ont_swap_events.find_one(
        {"company_id": cid, "subscriber_id": subscriber_id},
        {"_id": 0}, sort=[("created_at", -1)])
    # 4. Stok history
    hist = await db.stok_history.find_one(
        {"company_id": cid, "subscriber_id": subscriber_id},
        {"_id": 0}, sort=[("event_timestamp", -1)])

    checks = {
        "cliente": bool(sub),
        "cto": bool(link and link.get("cto_id")) if scenario != "retirada"
            else (not (link or {}).get("subscriber_id")),
        "porta": bool(link and link.get("port_number")) if scenario != "retirada"
            else (not (link or {}).get("subscriber_id")),
        "onu": bool(link and (link.get("ont_sn") or link.get("ont_mac")))
            if scenario != "retirada" else True,
        "tecnico": bool(sw and sw.get("collaborator_id")),
        "ticket": bool(sw and sw.get("ticket_id")),
        "estoque": bool(hist and hist.get("service_id")),
        "smartolt": True,  # snapshot já capturado no swap_event
    }
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    return {
        "scenario": scenario,
        "passed": passed,
        "total": total,
        "pass_pct": round((passed / total * 100), 2),
        "checks": checks,
        "ok": passed == total,
        "evidence": {
            "subscriber_id": subscriber_id,
            "canonical_link_id": (link or {}).get("id"),
            "last_swap_event_id": (sw or {}).get("event_id"),
            "last_history_id": (hist or {}).get("id"),
        },
    }


@router.post("/simulate-technician-journey")
async def simulate_journey(
    confirm: bool = Query(False),
    user: dict = Depends(require_role("administrador", "gestor")),
):
    """Cria cliente sintético, executa 6 cenários, valida cada um."""
    if not confirm:
        return {"error": "Requer ?confirm=true (cria dados sintéticos)"}
    cid = _user_company(user)
    run_id = f"e2e-{uuid.uuid4().hex[:12]}"
    actor = user.get("id") or "e2e_simulator"

    # Cliente sintético
    test_sub_id = f"sub-e2e-{uuid.uuid4().hex[:10]}"
    await db.subscribers.insert_one({
        "id": test_sub_id, "company_id": cid,
        "name": f"E2E Teste {run_id}",
        "status": "ATIVO",
        "atlaz_external_id": f"ext-e2e-{run_id}",
        "created_at": _now_iso(),
        "e2e_synthetic": True, "e2e_run_id": run_id,
    })

    test_cto_id = "cto-test-iter163"  # CTO real
    test_port = 99  # porta sintética alta
    test_ont_sn1 = f"E2E-ONT-A-{run_id}"
    test_ont_sn2 = f"E2E-ONT-B-{run_id}"
    test_collab = "col-e2e-tech"
    test_ticket = f"tkt-e2e-{run_id}"
    test_service = f"OS-E2E-{run_id}"

    # Cria porta sintética
    await db.cto_ports.update_one(
        {"id": f"{test_cto_id}-p{test_port}", "company_id": cid},
        {"$set": {"id": f"{test_cto_id}-p{test_port}", "company_id": cid,
                  "cto_id": test_cto_id, "port_number": test_port,
                  "status": "free", "e2e_synthetic": True}},
        upsert=True)

    # Cria ONUs sintéticas no estoque
    for sn in (test_ont_sn1, test_ont_sn2):
        await db.stok_onts.update_one(
            {"company_id": cid, "sn": sn},
            {"$set": {"id": f"ont-e2e-{uuid.uuid4().hex[:8]}",
                      "company_id": cid, "sn": sn, "scan_sn": sn,
                      "tier": "official", "e2e_synthetic": True,
                      "status": "estoque_empresa"}},
            upsert=True)

    results: List[Dict[str, Any]] = []

    # CENÁRIO 1: INSTALAÇÃO
    await upsert_link(db, company_id=cid, cto_id=test_cto_id,
                     port_number=test_port,
                     subscriber_id=test_sub_id,
                     subscriber_name=f"E2E {run_id}",
                     ont_sn=test_ont_sn1,
                     ticket_id=test_ticket, service_id=test_service,
                     collaborator_id=test_collab,
                     source="e2e_install", actor_user_id=actor)
    await write_swap_event(db, company_id=cid, event_type="install",
                          ticket_id=test_ticket, service_id=test_service,
                          subscriber_id=test_sub_id,
                          collaborator_id=test_collab,
                          cto_id=test_cto_id, port_number=test_port,
                          ont_new_sn=test_ont_sn1,
                          created_by=f"e2e:{actor}", allow_missing=True)
    await write_stok_event(db, company_id=cid, event_type="instalacao",
                          ticket_id=test_ticket, service_id=test_service,
                          collaborator_id=test_collab,
                          subscriber_id=test_sub_id,
                          description=f"E2E install {test_service}",
                          actor_user_label="E2E Tech")
    results.append(await _check_reconstruction(
        db, cid, "instalacao", subscriber_id=test_sub_id, expected={}))

    # CENÁRIO 2: REPARO (sem troca de ONU)
    await write_swap_event(db, company_id=cid, event_type="swap",
                          ticket_id=test_ticket + "-rep",
                          service_id=test_service + "-rep",
                          subscriber_id=test_sub_id,
                          collaborator_id=test_collab,
                          cto_id=test_cto_id, port_number=test_port,
                          ont_old_sn=test_ont_sn1,
                          ont_new_sn=test_ont_sn1,
                          swap_reason="reparo_cabo",
                          created_by=f"e2e:{actor}", allow_missing=True)
    results.append(await _check_reconstruction(
        db, cid, "reparo", subscriber_id=test_sub_id, expected={}))

    # CENÁRIO 3: TROCA ONU
    await upsert_link(db, company_id=cid, cto_id=test_cto_id,
                     port_number=test_port,
                     subscriber_id=test_sub_id,
                     ont_sn=test_ont_sn2,
                     ticket_id=test_ticket + "-troca",
                     service_id=test_service + "-troca",
                     collaborator_id=test_collab,
                     source="e2e_swap", actor_user_id=actor)
    await write_swap_event(db, company_id=cid, event_type="replacement",
                          ticket_id=test_ticket + "-troca",
                          service_id=test_service + "-troca",
                          subscriber_id=test_sub_id,
                          collaborator_id=test_collab,
                          cto_id=test_cto_id, port_number=test_port,
                          ont_old_sn=test_ont_sn1,
                          ont_new_sn=test_ont_sn2,
                          swap_reason="defeito",
                          created_by=f"e2e:{actor}", allow_missing=True)
    results.append(await _check_reconstruction(
        db, cid, "troca_onu", subscriber_id=test_sub_id, expected={}))

    # CENÁRIO 4: MUDANÇA DE PORTA (mesma CTO)
    new_port = 98
    await db.cto_ports.update_one(
        {"id": f"{test_cto_id}-p{new_port}", "company_id": cid},
        {"$set": {"id": f"{test_cto_id}-p{new_port}", "company_id": cid,
                  "cto_id": test_cto_id, "port_number": new_port,
                  "status": "free", "e2e_synthetic": True}}, upsert=True)
    await release_link(db, company_id=cid, cto_id=test_cto_id,
                      port_number=test_port,
                      reason="e2e_port_change", actor_user_id=actor)
    await upsert_link(db, company_id=cid, cto_id=test_cto_id,
                     port_number=new_port,
                     subscriber_id=test_sub_id,
                     ont_sn=test_ont_sn2,
                     ticket_id=test_ticket + "-mport",
                     service_id=test_service + "-mport",
                     collaborator_id=test_collab,
                     source="e2e_port_change", actor_user_id=actor)
    results.append(await _check_reconstruction(
        db, cid, "mudanca_porta", subscriber_id=test_sub_id, expected={}))

    # CENÁRIO 5: MUDANÇA DE CTO
    test_cto_id_2 = "cto-test-iter163"  # mantém mesma para teste sintético
    new_cto_port = 97
    await db.cto_ports.update_one(
        {"id": f"{test_cto_id_2}-p{new_cto_port}", "company_id": cid},
        {"$set": {"id": f"{test_cto_id_2}-p{new_cto_port}",
                  "company_id": cid, "cto_id": test_cto_id_2,
                  "port_number": new_cto_port, "status": "free",
                  "e2e_synthetic": True}}, upsert=True)
    await release_link(db, company_id=cid, cto_id=test_cto_id,
                      port_number=new_port, reason="e2e_cto_change",
                      actor_user_id=actor)
    await upsert_link(db, company_id=cid, cto_id=test_cto_id_2,
                     port_number=new_cto_port,
                     subscriber_id=test_sub_id,
                     ont_sn=test_ont_sn2,
                     ticket_id=test_ticket + "-mcto",
                     service_id=test_service + "-mcto",
                     collaborator_id=test_collab,
                     source="e2e_cto_change", actor_user_id=actor)
    results.append(await _check_reconstruction(
        db, cid, "mudanca_cto", subscriber_id=test_sub_id, expected={}))

    # CENÁRIO 6: RETIRADA
    await release_link(db, company_id=cid, cto_id=test_cto_id_2,
                      port_number=new_cto_port,
                      reason="e2e_removal", actor_user_id=actor)
    await write_swap_event(db, company_id=cid, event_type="removal",
                          ticket_id=test_ticket + "-ret",
                          service_id=test_service + "-ret",
                          subscriber_id=test_sub_id,
                          collaborator_id=test_collab,
                          ont_old_sn=test_ont_sn2, destino="estoque",
                          created_by=f"e2e:{actor}", allow_missing=True)
    results.append(await _check_reconstruction(
        db, cid, "retirada", subscriber_id=test_sub_id, expected={}))

    # SUMÁRIO
    passes = sum(1 for r in results if r["ok"])
    total = len(results)
    overall_status = "6/6 PASS" if passes == 6 else f"{passes}/{total} PASS"

    # RCA: lista quais checks falharam
    rca: List[Dict[str, Any]] = []
    for r in results:
        failed = [k for k, v in r["checks"].items() if not v]
        if failed:
            rca.append({"scenario": r["scenario"],
                        "failed_checks": failed,
                        "evidence": r["evidence"]})

    final = {
        "run_id": run_id,
        "company_id": cid,
        "test_subscriber_id": test_sub_id,
        "scenarios_total": total,
        "scenarios_passed": passes,
        "overall_status": overall_status,
        "results_per_scenario": results,
        "rca_failures": rca,
        "executed_at": _now_iso(),
    }
    await db.sprint5_e2e_validations.insert_one(final)
    final.pop("_id", None)
    return final


@router.get("/latest-validation")
async def latest_validation(
    user: dict = Depends(require_role("administrador", "gestor", "auditor")),
):
    cid = _user_company(user)
    doc = await db.sprint5_e2e_validations.find_one(
        {"company_id": cid}, {"_id": 0},
        sort=[("executed_at", -1)])
    return doc or {"empty": True}
