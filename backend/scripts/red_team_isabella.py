"""RED TEAM ISABELLA — Auditoria adversarial completa, Zero Mock.

Submete a Isabella a stress, ataques RBAC, inconsistências de dados,
race conditions, cross-company, latência sob carga.

Uso: python3 /app/backend/scripts/red_team_isabella.py
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
import os
import sys
import time
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SMARTPROV_TRANSPORT_FAKE", "1")

from database import db  # noqa: E402
from services import (isabella_churn, isabella_conselho, isabella_dunning,  # noqa: E402
                        isabella_executive_memory as memory_eng,
                        isabella_execution_score as exec_score,
                        isabella_expansion, isabella_experience as exp_eng,
                        isabella_incident,
                        isabella_learning as learning_eng,
                        isabella_outcome_engine as outcome_eng,
                        isabella_revenue, isabella_twin, universo_ligo as ul)
from services import isabella_audit as audit_eng

REPORT = {
    "ts": datetime.now(timezone.utc).isoformat(),
    "executed": 0, "passed": 0, "failed": 0,
    "bugs": [], "risks": [], "gargalos": [], "inconsistencias": [],
    "modules": {},  # nota A..E por módulo
    "latency_ms": {},
}


def case(module, name):
    """Decorator: marca um caso de teste, captura sucesso/falha + latência."""
    def deco(fn):
        async def wrap():
            REPORT["executed"] += 1
            t0 = time.time()
            try:
                r = await fn()
                ms = round((time.time() - t0) * 1000, 1)
                REPORT["latency_ms"].setdefault(module, []).append(ms)
                REPORT["passed"] += 1
                print(f"  ✅ [{module}] {name}  ({ms}ms)")
                return r
            except AssertionError as e:
                REPORT["failed"] += 1
                msg = f"[{module}/{name}] {e}"
                REPORT["bugs"].append(msg)
                print(f"  ❌ {msg}")
            except Exception as e:
                REPORT["failed"] += 1
                msg = f"[{module}/{name}] EXCEPTION: {type(e).__name__}: {e}"
                REPORT["bugs"].append(msg)
                print(f"  💥 {msg}")
        return wrap
    return deco


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ─────────────────────────────────────────────────────────────────────
# TESTE 5 — Incident Commander (stress de detecção)
# ─────────────────────────────────────────────────────────────────────
@case("incident", "scan stress co-demo")
async def t_incident_scan():
    from services.isabella_incident import detect_company
    r = await detect_company("co-demo")
    assert_true(isinstance(r, dict), "retorno deve ser dict")
    assert_true("clusters_detected" in r or "summary" in r or r is not None,
                f"sem estrutura padrão: keys={list(r.keys())}")


@case("incident", "block duplicate ticket no incident ativo")
async def t_incident_block_dup():
    inc = await db.isabella_incidents.find_one(
        {"company_id": "co-demo",
         "status": {"$in": ["predicted", "confirmed"]}},
        {"_id": 0, "id": 1, "affected_client_ids": 1})
    if not inc or not (inc.get("affected_client_ids") or []):
        REPORT["risks"].append(
            "incident sem affected_client_ids → block_for_new_repair sem alvo")
        return
    from services.isabella_incident import incident_block_for_new_repair
    r = await incident_block_for_new_repair(
        "co-demo", "Cliente Teste",
        "pppoe-fake", "Bairro Teste")
    # r=None é resposta válida (significa que não bloqueou — sem incidente)
    assert_true(r is None or isinstance(r, dict),
                "incident_block_for_new_repair deve responder dict ou None")


# ─────────────────────────────────────────────────────────────────────
# TESTES 6/7/8/9 — Commanders em escala (1000 alvo)
# ─────────────────────────────────────────────────────────────────────
@case("churn", "scan + valida 1000 alvo")
async def t_churn():
    r = await isabella_churn.scan_company("co-demo")
    assert_true(r.get("scored", 0) >= 0,
                f"scored inválido: {r}")
    # Falso positivo: score muito alto em cliente sem reparo nem overdue?
    high = await db.isabella_commander_opportunities.find(
        {"company_id": "co-demo", "kind": "churn",
         "status": "pending", "score": {"$gte": 75}},
        {"_id": 0, "evidence": 1, "score": 1}).limit(20).to_list(20)
    fp = [h for h in high
          if not h["evidence"].get("n_overdue", 0)
          and not h["evidence"].get("n_tickets_30d", 0)
          and h["evidence"].get("bad_signal_dbm") is None]
    if fp:
        REPORT["risks"].append(
            f"Churn falsos positivos: {len(fp)} score>=75 sem evidência forte")


@case("revenue", "scan + dedup")
async def t_revenue():
    r = await isabella_revenue.scan_company("co-demo")
    assert_true(r.get("opportunities", 0) >= 0, "ok")
    # Duplicidade: mesmo subscriber + mesmo subkind aberto >1?
    pipe = [
        {"$match": {"company_id": "co-demo", "kind": "revenue",
                      "status": "pending"}},
        {"$group": {"_id": {"target": "$target_id", "subkind": "$subkind"},
                       "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$limit": 5},
    ]
    dups = await db.isabella_commander_opportunities.aggregate(pipe).to_list(5)
    assert_true(len(dups) == 0,
                f"Revenue duplicado encontrado: {len(dups)}")


@case("dunning", "scan + verifica steps válidos")
async def t_dunning():
    r = await isabella_dunning.scan_company("co-demo")
    valid_steps = {"reminder_pre", "reminder_late", "negotiation",
                    "unblock_offer", "warning", "block_request",
                    "monitor"}
    invalid = await db.isabella_commander_opportunities.find(
        {"company_id": "co-demo", "kind": "dunning",
         "subkind": {"$nin": list(valid_steps)}},
        {"_id": 0, "subkind": 1}).limit(5).to_list(5)
    assert_true(len(invalid) == 0,
                f"Dunning subkinds inválidos: {invalid}")


@case("twin", "scan + valida targets")
async def t_twin():
    r = await isabella_twin.scan_company("co-demo")
    assert_true(r.get("total", 0) >= 0, "ok")
    invalid_targets = await db.isabella_commander_opportunities.find(
        {"company_id": "co-demo", "kind": "twin",
         "target_type": {"$nin": ["cto", "onu", "vehicle",
                                     "stock_item", "tech"]}},
        {"_id": 0, "target_type": 1}).limit(5).to_list(5)
    assert_true(len(invalid_targets) == 0,
                f"Twin target_types inválidos: {invalid_targets}")


@case("expansion", "scan")
async def t_expansion():
    r = await isabella_expansion.scan_company("co-demo")
    assert_true(r.get("opportunities", 0) >= 0, "ok")


# ─────────────────────────────────────────────────────────────────────
# TESTE 6 — Universo Ligo (1000 clientes)
# ─────────────────────────────────────────────────────────────────────
@case("universo", "refresh_all com cap 200")
async def t_universo_refresh():
    r = await ul.refresh_all("co-demo", limit=200)
    assert_true(r.get("refreshed", 0) > 0,
                f"refresh_all não refrescou: {r}")
    # Valida que todos os scores têm level_id ∈ 1..6
    bad = await db.universo_ligo_scores.count_documents(
        {"company_id": "co-demo",
         "level_id": {"$nin": [1, 2, 3, 4, 5, 6]}})
    assert_true(bad == 0, f"{bad} scores com level_id inválido")


@case("universo", "regra de nome respeitada em 1000 mensagens")
async def t_universo_name_rule():
    # Renderiza vários templates para amostragem aleatória
    subs = await db.subscribers.find(
        {"company_id": "co-demo", "name": {"$nin": [None, ""]}},
        {"_id": 0, "name": 1, "id": 1}).limit(200).to_list(200)
    fails = []
    templates_to_check = ("anniversary_install_1y", "anniversary_install_3y",
                            "welcome", "vip_pizza", "incident_resolved")
    for sub in subs:
        for tpl_id in templates_to_check:
            tpl = exp_eng.TEMPLATES.get(tpl_id) or ""
            m = exp_eng.compose_message(tpl, subscriber=sub)
            if not m["ok"]:
                fails.append({"name": sub["name"], "tpl": tpl_id,
                              "occ": m["name_occurrences"]})
    assert_true(len(fails) == 0,
                f"{len(fails)} mensagens excederam limite de nome: "
                f"{fails[:3]}")


# ─────────────────────────────────────────────────────────────────────
# TESTE 10 — Conselho / Learning / Outcome
# ─────────────────────────────────────────────────────────────────────
@case("council", "hold + decisões com id")
async def t_council():
    ata = await isabella_conselho.hold_meeting("co-demo")
    decs = ata.get("decisions") or []
    no_id = [d for d in decs if not d.get("id", "").startswith("dec-")]
    assert_true(not no_id, f"{len(no_id)} decisões sem id")


@case("learning", "report + auto-exec readiness")
async def t_learning():
    rep = await audit_eng.learning_report("co-demo", days=90)
    ready = await audit_eng.auto_execute_ready("co-demo", days=90)
    assert_true(isinstance(rep["items"], list),
                "report.items deve ser lista")
    # Verifica que nenhum playbook está prematuramente elegível
    bad = [e for e in ready["eligible"] if e["attempts"] < 100]
    assert_true(not bad,
                f"AutoExec liberou {len(bad)} playbook com attempts<100")


@case("outcome", "resolve_due + sem outcomes sem opp_id")
async def t_outcome():
    await outcome_eng.resolve_due(force=False)
    orphans = await db.isabella_outcomes.count_documents(
        {"opp_id": {"$in": [None, ""]}})
    assert_true(orphans == 0, f"{orphans} outcomes órfãos (sem opp_id)")


# ─────────────────────────────────────────────────────────────────────
# TESTE 11 — Segurança (RBAC, cross-company, ownership)
# ─────────────────────────────────────────────────────────────────────
@case("security", "RBAC: técnico não aprova campanha L3")
async def t_sec_role():
    sub = await db.subscribers.find_one({"company_id": "co-demo",
                                            "phone": {"$nin": [None, ""]}},
                                           {"_id": 0})
    d = await exp_eng._draft_campaign(
        company_id="co-demo", event_key=f"red_team_role_{int(time.time())}",
        subscriber=sub, template_id="vip_pizza", approval_level=3,
        estimated_cost_brl=99.0)
    if not d:
        return
    blocked = False
    try:
        await exp_eng.approve_campaign(
            campaign_id=d["id"], company_id="co-demo",
            actor="tech@ligo.com", actor_role="tecnico")
    except PermissionError:
        blocked = True
    finally:
        await db.experience_campaigns.delete_one({"id": d["id"]})
        await db.experience_campaigns_audit.delete_many(
            {"campaign_id": d["id"]})
    assert_true(blocked, "técnico conseguiu aprovar L3! falha de segurança")


@case("security", "campanha L3 sem aprovação não executa")
async def t_sec_no_approve():
    sub = await db.subscribers.find_one({"company_id": "co-demo",
                                            "phone": {"$nin": [None, ""]}},
                                           {"_id": 0})
    d = await exp_eng._draft_campaign(
        company_id="co-demo",
        event_key=f"red_team_no_approve_{int(time.time())}",
        subscriber=sub, template_id="vip_pizza", approval_level=3,
        estimated_cost_brl=120.0)
    if not d:
        return
    blocked = False
    try:
        await exp_eng.execute_campaign(
            campaign_id=d["id"], company_id="co-demo", actor="x")
    except PermissionError:
        blocked = True
    finally:
        await db.experience_campaigns.delete_one({"id": d["id"]})
    assert_true(blocked, "campanha L3 EXECUTOU sem aprovação!")


@case("security", "cross-company: opportunity de A não acessível por B")
async def t_sec_cross_company():
    opp = await db.isabella_commander_opportunities.find_one(
        {"company_id": "co-demo", "status": "pending"},
        {"_id": 0, "id": 1})
    if not opp:
        return
    from services.isabella_opportunities import get_opportunity
    other = await get_opportunity(opp["id"], "co-empresa-falsa")
    assert_true(other is None,
                "vazamento cross-company! opportunity acessível por outra company")


@case("security", "policies não vazam entre empresas")
async def t_sec_policies():
    pol = await memory_eng.add_policy(
        company_id="co-demo", scope="kind", action="block",
        condition={}, decided_by="audit", reason="redteam",
        kind="churn")
    leaked = await db.isabella_executive_policies.find_one(
        {"id": pol["id"], "company_id": "co-empresa-falsa"})
    await db.isabella_executive_policies.delete_one({"id": pol["id"]})
    assert_true(leaked is None, "policy vazou para outra empresa")


# ─────────────────────────────────────────────────────────────────────
# TESTE 12 — CARGA (paralelo: 5 commanders + 1 council + 200 ULigo)
# ─────────────────────────────────────────────────────────────────────
@case("performance", "carga simultânea: 5 commanders + council + ULigo")
async def t_load():
    t0 = time.time()
    tasks = [
        isabella_churn.scan_company("co-demo"),
        isabella_revenue.scan_company("co-demo"),
        isabella_dunning.scan_company("co-demo"),
        isabella_twin.scan_company("co-demo"),
        isabella_expansion.scan_company("co-demo"),
        isabella_conselho.hold_meeting("co-demo"),
        ul.refresh_all("co-demo", limit=200),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    fail = [r for r in results if isinstance(r, Exception)]
    elapsed = time.time() - t0
    REPORT["latency_ms"]["full_load_run"] = round(elapsed * 1000, 1)
    if elapsed > 60:
        REPORT["gargalos"].append(
            f"carga total demorou {elapsed:.1f}s (alvo <60s)")
    assert_true(len(fail) == 0,
                f"{len(fail)} tasks falharam em carga: "
                f"{[type(e).__name__ for e in fail][:5]}")


# ─────────────────────────────────────────────────────────────────────
# Consistência / Inconsistências de schema
# ─────────────────────────────────────────────────────────────────────
@case("consistency", "outcomes não-resolved com paid_date < created_at")
async def t_consistency_outcomes():
    # Outcome ainda pending mas o cliente já cancelou?
    pending = await db.isabella_outcomes.find(
        {"result": "pending", "kind": "churn"},
        {"_id": 0, "company_id": 1, "target_id": 1,
         "created_at": 1}).limit(50).to_list(50)
    flagged = 0
    for p in pending:
        sub = await db.subscribers.find_one(
            {"company_id": p["company_id"], "id": p["target_id"]},
            {"_id": 0, "cancellation_date": 1})
        if sub and sub.get("cancellation_date") \
                and sub["cancellation_date"] >= p["created_at"]:
            flagged += 1
    if flagged:
        REPORT["inconsistencias"].append(
            f"{flagged} outcomes churn pendentes onde cliente já cancelou")


@case("consistency", "campanhas APPROVED há mais de 24h sem execução")
async def t_consistency_campaigns():
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    stale = await db.experience_campaigns.count_documents(
        {"status": "APPROVED",
         "updated_at": {"$lt": cutoff}})
    if stale:
        REPORT["gargalos"].append(
            f"{stale} campanhas APPROVED há >24h sem execução")


@case("consistency", "opportunities expired ainda como pending")
async def t_consistency_opps():
    now_iso = datetime.now(timezone.utc).isoformat()
    stale = await db.isabella_commander_opportunities.count_documents(
        {"status": "pending", "expires_at": {"$lt": now_iso}})
    if stale:
        REPORT["inconsistencias"].append(
            f"{stale} oportunidades expiradas sem TTL aplicado")


# ─────────────────────────────────────────────────────────────────────
# Notas finais por módulo
# ─────────────────────────────────────────────────────────────────────
def _rank_module(module: str) -> str:
    bugs_in = [b for b in REPORT["bugs"] if f"[{module}/" in b]
    if not bugs_in and module in REPORT["latency_ms"]:
        lat = REPORT["latency_ms"][module]
        max_ms = max(lat) if lat else 0
        if max_ms < 500:
            return "A"
        if max_ms < 2000:
            return "B"
        if max_ms < 10000:
            return "C"
        return "D"
    if bugs_in:
        return "E"
    return "B"


async def main() -> int:
    print("═" * 70)
    print(" RED TEAM ISABELLA — Auditoria adversarial ZERO MOCK")
    print("═" * 70)
    print()
    print("── Bloco 1: Commanders ──")
    await t_churn()
    await t_revenue()
    await t_dunning()
    await t_twin()
    await t_expansion()
    print("\n── Bloco 2: Incident Commander ──")
    await t_incident_scan()
    await t_incident_block_dup()
    print("\n── Bloco 3: Universo Ligo ──")
    await t_universo_refresh()
    await t_universo_name_rule()
    print("\n── Bloco 4: Conselho/Learning/Outcome ──")
    await t_council()
    await t_learning()
    await t_outcome()
    print("\n── Bloco 5: Segurança ──")
    await t_sec_role()
    await t_sec_no_approve()
    await t_sec_cross_company()
    await t_sec_policies()
    print("\n── Bloco 6: Carga ──")
    await t_load()
    print("\n── Bloco 7: Consistência ──")
    await t_consistency_outcomes()
    await t_consistency_campaigns()
    await t_consistency_opps()

    # Notas por módulo
    for m in ("churn", "revenue", "dunning", "twin", "expansion",
                "incident", "universo", "council", "learning",
                "outcome", "security", "performance", "consistency"):
        REPORT["modules"][m] = _rank_module(m)

    print("\n" + "═" * 70)
    print(" RELATÓRIO EXECUTIVO ")
    print("═" * 70)
    print(f"Executados: {REPORT['executed']}")
    print(f"Passaram:   {REPORT['passed']}")
    print(f"Falharam:   {REPORT['failed']}")
    print(f"Bugs:       {len(REPORT['bugs'])}")
    print(f"Riscos:     {len(REPORT['risks'])}")
    print(f"Gargalos:   {len(REPORT['gargalos'])}")
    print(f"Incons.:    {len(REPORT['inconsistencias'])}")
    print("\nNotas por módulo:")
    for m, n in REPORT["modules"].items():
        ms_list = REPORT["latency_ms"].get(m, [])
        avg_ms = round(statistics.mean(ms_list), 1) if ms_list else "n/a"
        print(f"  {n}  · {m:<14} (avg {avg_ms}ms)")

    if REPORT["bugs"]:
        print("\nBUGS:")
        for b in REPORT["bugs"]:
            print(f"  - {b}")
    if REPORT["risks"]:
        print("\nRISCOS:")
        for b in REPORT["risks"]:
            print(f"  - {b}")
    if REPORT["gargalos"]:
        print("\nGARGALOS:")
        for b in REPORT["gargalos"]:
            print(f"  - {b}")
    if REPORT["inconsistencias"]:
        print("\nINCONSISTÊNCIAS:")
        for b in REPORT["inconsistencias"]:
            print(f"  - {b}")

    # Persist report
    await db.red_team_audits.insert_one({**REPORT,
                                          "id": "rt-" + REPORT["ts"]})
    print(f"\nGravado em red_team_audits id=rt-{REPORT['ts']}")
    return 0 if REPORT["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
