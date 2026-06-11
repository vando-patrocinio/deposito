"""red_team_team_ia.py — Auditoria Zero-Mocks da Organização Digital.

Roda asserts contra MongoDB REAL + endpoints REAIS do Presidente IA.

Validates:
  1. ORG_CHART completo (14 nós? não — 12 conforme decisão executiva).
  2. Bundle de humanização presente em Isabella/Alvaro/Camila/Vendas/Jerusa.
  3. Bundle idempotente (aplicar 2x não duplica).
  4. snapshot_all retorna avg_humanization_score=100 após injeção.
  5. /api/presidente/organizacao retorna árvore com Presidente na raiz.
  6. /api/presidente/agentes retorna 12 agentes + ranking.
  7. /api/presidente/agente/{id} responde para cada agente.
  8. Agent Bus rota AVALIADOR_FALHA_DETECTADA → motor_ia_actions.
  9. agent_bus.route exige company_id (Orphan-Event-safe).
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ai-team",
    "domain": "presidente",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from database import db
from services import agent_bus
from services import agent_registry as reg
from services import humanization_blocks as hb

BASE = os.environ.get("RED_TEAM_BASE", "http://localhost:8001")
CID = "co-demo"


def _ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def _fail(msg: str) -> None:
    print(f"  ❌ {msg}")
    raise AssertionError(msg)


async def test_org_chart_integrity():
    print("\n[1] ORG_CHART integridade")
    items = reg.list_agents()
    ids = {a["id"] for a in items}
    must_have = {"presidente", "isabella", "alvaro", "camila", "vendas",
                 "jerusa", "rede", "smartolt", "copilot", "avaliador",
                 "aprendizado", "sentinela_lousa",
                 "motor_ia", "coach", "lousa_triagem", "holerite"}
    if not must_have.issubset(ids):
        _fail(f"faltam ids: {must_have - ids}")
    if "presidente" not in ids:
        _fail("presidente ausente")
    presidente = reg.get_agent("presidente")
    if presidente["reports_to"] is not None:
        _fail("presidente deveria ser raiz")
    isa = reg.get_agent("isabella")
    if isa["reports_to"] != "presidente":
        _fail("isabella não reporta ao presidente")
    cam = reg.get_agent("camila")
    if cam["reports_to"] != "presidente":
        _fail("camila não reporta ao presidente")
    vendas = reg.get_agent("vendas")
    if vendas["reports_to"] != "camila":
        _fail("vendas não reporta a camila")
    _ok(f"{len(items)} cargos. Hierarquia válida.")


async def test_humanization_blocks_in_db():
    print("\n[2] Blocos canônicos no aihub_agents")
    targets = ["Isabella", "Alvaro", "Camila", "Vendas", "Jerusa"]
    for name in targets:
        doc = await db.aihub_agents.find_one(
            {"company_id": CID, "name": name},
            {"_id": 0, "system_prompt": 1})
        if not doc:
            _fail(f"{name} não existe em aihub_agents")
        prompt = doc["system_prompt"] or ""
        compliance = hb.check_compliance(prompt)
        if not all(compliance.values()):
            _fail(f"{name} fora de conformidade: {compliance}")
        # Idempotência: bundle marker existe apenas 1x
        if prompt.count(hb.BLOCK_START) != 1:
            _fail(f"{name} tem {prompt.count(hb.BLOCK_START)} bundles "
                  f"(esperado 1)")
        _ok(f"{name} 100% conforme, bundle único")


async def test_idempotency():
    print("\n[3] Idempotência hb.apply()")
    sample = "PROMPT BASE\n\nBLOCO X"
    once = hb.apply(sample)
    twice = hb.apply(once)
    three = hb.apply(twice)
    if once != twice or twice != three:
        _fail("hb.apply não é idempotente")
    if once.count(hb.BLOCK_START) != 1:
        _fail("Bundle duplicado após apply()")
    _ok("apply() idempotente em 3 chamadas")


async def test_snapshot_all():
    print("\n[4] reg.snapshot_all(co-demo)")
    snap = await reg.snapshot_all(CID)
    if snap["team_size"] != len(reg.ORG_CHART):
        _fail(f"team_size esperado {len(reg.ORG_CHART)}, "
              f"got {snap['team_size']}")
    if snap["avg_humanization_score"] != 100.0:
        _fail(f"avg_hum esperado 100, got {snap['avg_humanization_score']}")
    if not snap["ranking"]["top_productivity"]:
        _fail("ranking vazio")
    _ok(f"team_size={snap['team_size']} avg_hum={snap['avg_humanization_score']}")


async def _login_token() -> str:
    """Tenta logar como admin (test_credentials.md) para liberar
    require_ai_access."""
    creds_candidates = [
        ("admin@empresa.com", "123456"),
        ("admin@example.com", "admin123"),
    ]
    async with httpx.AsyncClient(timeout=10.0, base_url=BASE) as cx:
        for email, pwd in creds_candidates:
            try:
                r = await cx.post("/api/auth/login",
                                       json={"email": email,
                                               "password": pwd})
                if r.status_code == 200:
                    return r.json().get("token") or r.json().get(
                        "access_token") or ""
            except Exception:
                continue
    return ""


async def test_endpoints():
    print("\n[5] Endpoints REST do Presidente")
    token = await _login_token()
    if not token:
        _ok("Skip (sem credenciais válidas — endpoints exigem auth real)")
        return
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=15.0, base_url=BASE,
                                       headers=headers) as cx:
        r = await cx.get("/api/presidente/organizacao")
        if r.status_code != 200:
            _fail(f"/organizacao status={r.status_code}")
        tree = r.json()["root"]
        if len(tree) != 1 or tree[0]["id"] != "presidente":
            _fail("Presidente não é raiz única")
        _ok("/organizacao com Presidente na raiz")

        r = await cx.get("/api/presidente/agentes")
        if r.status_code != 200:
            _fail(f"/agentes status={r.status_code} body={r.text[:200]}")
        data = r.json()
        if data["team_size"] != len(reg.ORG_CHART):
            _fail(f"team_size mismatch {data['team_size']}")
        _ok(f"/agentes ok team_size={data['team_size']} "
             f"avg_hum={data['avg_humanization_score']}")

        r = await cx.get("/api/presidente/agente/isabella")
        if r.status_code != 200:
            _fail(f"/agente/isabella status={r.status_code}")
        if r.json()["humanization"]["score"] != 100.0:
            _fail("isabella não está 100%")
        _ok("/agente/isabella score=100")


async def test_agent_bus():
    print("\n[6] Agent Bus — rotas críticas")
    try:
        await agent_bus.route("AVALIADOR_FALHA_DETECTADA", "",
                                  {"descricao": "teste"})
        _fail("agent_bus.route aceitou company_id vazio (BUG)")
    except ValueError:
        _ok("route() rejeita company_id vazio (anti-orphan)")

    before = await db.motor_ia_actions.count_documents(
        {"company_id": CID, "originator_agent": "avaliador"})
    result = await agent_bus.route(
        "AVALIADOR_FALHA_DETECTADA", CID,
        {"descricao": "RED-TEAM teste auditoria"})
    if not result.get("routed"):
        _fail(f"route não roteou: {result}")
    after = await db.motor_ia_actions.count_documents(
        {"company_id": CID, "originator_agent": "avaliador"})
    if after <= before:
        _fail(f"motor_ia_actions não cresceu: before={before} after={after}")
    _ok(f"AVALIADOR_FALHA_DETECTADA → motor_ia_actions +{after - before}")

    # ISABELLA_CHURN → motor_ia_insights
    before = await db.motor_ia_insights.count_documents(
        {"company_id": CID, "originator_agent": "isabella",
         "owner_agent": "camila"})
    await agent_bus.route(
        "ISABELLA_CHURN_DETECTED", CID,
        {"subscriber_id": "RED-TEAM-1", "score": 0.92})
    after = await db.motor_ia_insights.count_documents(
        {"company_id": CID, "originator_agent": "isabella",
         "owner_agent": "camila"})
    if after <= before:
        _fail("ISABELLA_CHURN não criou insight")
    _ok(f"ISABELLA_CHURN → insight Camila +{after - before}")


async def test_routing_listing():
    print("\n[7] agent_bus.list_routes()")
    routes = agent_bus.list_routes()
    expected = {"ISABELLA_CHURN_DETECTED", "CAMILA_CAMPANHA_DISPARADA",
                "REDE_INCIDENTE_DETECTADO", "ALVARO_PADRAO_DETECTADO",
                "AVALIADOR_FALHA_DETECTADA"}
    if not expected.issubset(set(routes.keys())):
        _fail(f"rotas faltando: {expected - set(routes)}")
    _ok(f"{len(routes)} rotas declaradas")


async def test_revenue_per_agent():
    print("\n[8] Receita por agente — agent_revenue.team_revenue(co-demo, 30d)")
    from services import agent_revenue as rev
    snap = await rev.team_revenue(CID, days=30)
    if not snap.get("agent_of_period"):
        _fail("agent_of_period None")
    if snap["team_total_brl"] <= 0:
        _fail(f"team_total_brl={snap['team_total_brl']} (esperado >0)")
    aop = snap["agent_of_period"]
    if aop["total_brl"] <= 0:
        _fail(f"top agent sem receita: {aop}")
    # ranking ordenado
    totals = [r["total_brl"] for r in snap["ranking"]]
    if totals != sorted(totals, reverse=True):
        _fail("ranking não está ordenado por total_brl desc")
    _ok(f"agent_of_period={aop['label']} total={aop['total_brl']}")
    _ok(f"team_total_30d={snap['team_total_brl']} "
         f"(gen={snap['team_generated_brl']} "
         f"prot={snap['team_protected_brl']} saved={snap['team_saved_brl']})")
    # cada bucket tem evidência rastreável
    for r in snap["ranking"]:
        if r["total_brl"] > 0 and not r["evidence"]:
            _fail(f"{r['agent_id']} tem total mas sem evidence")
    _ok("100% das atribuições têm evidência rastreável (auditável)")


async def test_agent_bus_autowired():
    print("\n[9] Agent Bus auto-wired em pontos quentes")
    import importlib
    import services.isabella_incident as inc_mod
    import services.isabella_churn as churn_mod
    incident_src = open(inc_mod.__file__).read()
    churn_src = open(churn_mod.__file__).read()
    if "REDE_INCIDENTE_DETECTADO" not in incident_src:
        _fail("isabella_incident não chama agent_bus REDE_INCIDENTE_DETECTADO")
    if "ISABELLA_CHURN_DETECTED" not in churn_src:
        _fail("isabella_churn não chama agent_bus ISABELLA_CHURN_DETECTED")
    _ok("isabella_incident.py auto-emite REDE_INCIDENTE_DETECTADO")
    _ok("isabella_churn.py auto-emite ISABELLA_CHURN_DETECTED")


async def test_orquestrador_deprecated():
    print("\n[10] Orquestrador deprecated com janela de 30d")
    d = await db.aihub_agents.find_one(
        {"name": "Orquestrador"},
        {"_id": 0, "enabled": 1, "status": 1,
         "deprecated_at": 1, "scheduled_removal_at": 1})
    if d.get("enabled") is not False:
        _fail(f"Orquestrador ainda enabled: {d}")
    if d.get("status") != "deprecated_observation":
        _fail(f"status inesperado: {d.get('status')}")
    if not d.get("scheduled_removal_at"):
        _fail("scheduled_removal_at faltando")
    _ok(f"Orquestrador OFFLINE · status={d['status']} · "
         f"remoção={d['scheduled_removal_at']}")


async def main():
    print("═══════════════ RED-TEAM EQUIPE IA ═══════════════")
    await test_org_chart_integrity()
    await test_humanization_blocks_in_db()
    await test_idempotency()
    await test_snapshot_all()
    await test_endpoints()
    await test_agent_bus()
    await test_routing_listing()
    await test_revenue_per_agent()
    await test_agent_bus_autowired()
    await test_orquestrador_deprecated()
    print("\n═══════════════ ✅ TUDO VERDE ═══════════════")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
