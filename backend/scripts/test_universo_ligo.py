"""ZERO MOCK — Universo Ligo + Isabella Experience Commander.

12 testes obrigatórios do contrato CTO 02/2026:

  1. Cliente é reconhecido automaticamente (por phone/external_code/id)
  2. Nome não é repetido excessivamente em mensagens
  3. Nível Universo Ligo é calculado
  4. Mudança de nível funciona (history)
  5. Campanha sem aprovação não executa (PermissionError)
  6. Campanha aprovada executa (fake transport)
  7. Auditoria é criada
  8. Conselho gera parecer
  9. ROI previsto é registrado
 10. Histórias são utilizadas (sem promoção/desconto)
 11. Benefícios exigem aprovação (L2/L3/L4)
 12. Nenhuma campanha financeira executa sem autorização humana
"""
import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SMARTPROV_TRANSPORT_FAKE", "1")

from database import db  # noqa: E402
from services import isabella_experience as exp  # noqa: E402
from services import universo_ligo as ul  # noqa: E402


def _ok(cond: bool, msg: str) -> None:
    icon = "✅" if cond else "❌"
    print(f"  {icon} {msg}")
    if not cond:
        raise AssertionError(msg)


async def _pick_company_and_sub():
    pipe = [{"$group": {"_id": "$company_id", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}}, {"$limit": 1}]
    rows = await db.subscriber_invoices.aggregate(pipe).to_list(1)
    company = rows[0]["_id"] if rows else "co-demo"
    sub = await db.subscribers.find_one(
        {"company_id": company,
         "contract_status": {"$nin": ["CANCELADO"]},
         "phone": {"$nin": [None, ""]}},
        {"_id": 0})
    return company, sub


async def main() -> int:
    failed = 0
    await ul.ensure_indexes()
    await exp.ensure_indexes()
    company, sub = await _pick_company_and_sub()
    print(f"== Empresa: {company} | Assinante alvo: {sub.get('name')} ({sub['id']})")

    # [1] Reconhecimento automático
    print("\n[1] Identificação automática")
    r_by_id = await ul.identify(company_id=company, subscriber_id=sub["id"])
    _ok(r_by_id is not None and r_by_id["id"] == sub["id"],
        "identify por subscriber_id OK")
    r_by_phone = await ul.identify(company_id=company,
                                       phone=sub["phone"])
    _ok(r_by_phone is not None and r_by_phone["id"] == sub["id"],
        f"identify por phone OK ({sub['phone']})")
    if sub.get("external_code"):
        r_by_ext = await ul.identify(
            company_id=company,
            external_code=sub["external_code"].replace("ATLAZ-", ""))
        _ok(r_by_ext is not None and r_by_ext["id"] == sub["id"],
            "identify por external_code OK")
    # identify devolve universo_ligo embutido
    _ok("universo_ligo" in r_by_id and "level_name" in r_by_id["universo_ligo"],
        f"identify retorna nível embutido ({r_by_id['universo_ligo']['level_name']})")

    # [2] Regra do nome
    print("\n[2] Regra conversacional do nome")
    sample_sub = {"name": "Joao Carlos da Silva", "id": "x"}
    msg = exp.compose_message(
        exp.TEMPLATES["anniversary_install_1y"], subscriber=sample_sub)
    _ok(msg["name_occurrences"] <= 2,
        f"template 1y usa nome {msg['name_occurrences']}x (≤2)")
    bad_template = ("Olá {nome}. {nome} sabia que {nome} é especial? "
                      "Continue, {nome}. Obrigado {nome}.")
    bad = exp.compose_message(bad_template, subscriber=sample_sub)
    _ok(not bad["ok"] and bad["name_occurrences"] > 2,
        f"template 5x nome reprovado pela regra ({bad['name_occurrences']}x)")

    # [3] Nível calculado
    print("\n[3] Score & nível calculados")
    score = await ul.compute(company, sub["id"])
    _ok(0 <= score["score"] <= 10000, f"score numérico {score['score']}")
    _ok(score["level_id"] in (1, 2, 3, 4, 5, 6),
        f"nível {score['level_name']} ({score['level_id']})")
    _ok("components" in score and "factors" in score,
        "componentes + fatores presentes")

    # [4] Mudança de nível
    print("\n[4] Mudança de nível persiste em history")
    # força um upsert para gravar level inicial
    cached_pre = await ul.get_or_compute(company, sub["id"], force=True)
    # injeta cache antigo com level diferente para forçar mudança
    fake_prev = cached_pre["level_id"] + 1 if cached_pre["level_id"] < 6 else 1
    await db.universo_ligo_scores.update_one(
        {"company_id": company, "subscriber_id": sub["id"]},
        {"$set": {"level_id": fake_prev}})
    after = await ul.get_or_compute(company, sub["id"], force=True)
    _ok(after["level_id"] == cached_pre["level_id"],
        f"recomputado para {after['level_name']}")
    hist = await db.universo_ligo_history.find_one(
        {"subscriber_id": sub["id"]}, {"_id": 0},
        sort=[("changed_at", -1)])
    _ok(hist is not None, "evento de mudança gravado em universo_ligo_history")

    # [5] Campanha sem aprovação não executa
    print("\n[5] Bloqueio de execução sem aprovação")
    # cria uma campanha L3 (gerencial) artificial
    draft = await exp._draft_campaign(
        company_id=company, event_key="vip_pizza_test",
        subscriber=sub, template_id="vip_pizza",
        approval_level=3,
        estimated_cost_brl=45.0, expected_roi_brl=200.0,
        context={"empresa": "Ligo"})
    _ok(draft is not None, f"draft criado {draft and draft.get('id')}")
    blocked = False
    try:
        await exp.execute_campaign(campaign_id=draft["id"],
                                      company_id=company,
                                      actor="tester")
    except PermissionError:
        blocked = True
    _ok(blocked, "execução BLOQUEADA antes da aprovação (PermissionError)")

    # [6] Campanha aprovada executa
    print("\n[6] Execução após aprovação")
    try:
        appr = await exp.approve_campaign(
            campaign_id=draft["id"], company_id=company,
            actor="cto@ligo.system", actor_role="cto",
            notes="aprovado para validação")
        _ok(appr["status"] == "APPROVED",
            f"campanha aprovada (status={appr['status']})")
    except Exception as e:
        failed += 1
        print(f"  ❌ approve falhou: {e}")
    executed = await exp.execute_campaign(
        campaign_id=draft["id"], company_id=company,
        actor="cto@ligo.system")
    _ok(executed["status"] == "EXECUTED",
        f"execução OK (status={executed['status']})")
    _ok(bool(executed.get("send_result")), "send_result registrado")

    # [7] Auditoria
    print("\n[7] Auditoria registrada")
    audit = await db.experience_campaigns_audit.find(
        {"campaign_id": draft["id"]}, {"_id": 0}).to_list(20)
    actions = [a["action"] for a in audit]
    for required in ("created", "approved", "executed"):
        _ok(required in actions, f"audit.{required} presente")

    # [8] Conselho gera parecer
    print("\n[8] Conselho Executivo IA")
    parecer = await exp.council_review(draft["id"], company)
    for k in ("isabella", "presidente_ia", "alvaro_ia",
                "risco", "recomendacao"):
        _ok(k in parecer, f"parecer.{k} presente")

    # [9] ROI previsto registrado
    print("\n[9] ROI previsto persistido")
    refetch = await db.experience_campaigns.find_one(
        {"id": draft["id"]}, {"_id": 0})
    _ok(refetch["expected_roi_brl"] == 200.0,
        f"expected_roi_brl={refetch['expected_roi_brl']}")
    _ok(refetch["estimated_cost_brl"] == 45.0,
        f"estimated_cost_brl={refetch['estimated_cost_brl']}")

    # [10] Histórias (não promocionais)
    print("\n[10] Templates sem promoção/desconto")
    BAD_WORDS = ["desconto", "promoção", "promocao", "%", "ganhe",
                  "grátis", "gratis", "pagar menos"]
    for k, t in exp.TEMPLATES.items():
        bad = [w for w in BAD_WORDS if w.lower() in t.lower()]
        _ok(len(bad) == 0,
            f"template '{k}' livre de palavras promocionais")

    # [11] Benefícios exigem aprovação
    print("\n[11] L2/L3/L4 exigem aprovação humana")
    for lvl in (2, 3, 4):
        d2 = await exp._draft_campaign(
            company_id=company,
            event_key=f"vip_pizza_lvl{lvl}",
            subscriber={**sub, "id": f"{sub['id']}-lvl{lvl}-mock"},
            template_id="vip_pizza", approval_level=lvl,
            estimated_cost_brl=20.0 * lvl)
        if d2 is None:
            # dedup hit — limpa e tenta de novo
            await db.experience_campaigns.delete_many(
                {"event_key": f"vip_pizza_lvl{lvl}"})
            d2 = await exp._draft_campaign(
                company_id=company,
                event_key=f"vip_pizza_lvl{lvl}",
                subscriber={**sub, "id": f"{sub['id']}-lvl{lvl}-mock"},
                template_id="vip_pizza", approval_level=lvl,
                estimated_cost_brl=20.0 * lvl)
        _ok(d2 is not None and d2["status"] == "AWAITING_APPROVAL"
            and d2["auto_execute"] is False,
            f"L{lvl} status=AWAITING_APPROVAL auto_execute=False")

    # [12] Nenhuma campanha financeira executa sem humano
    print("\n[12] L2/L3/L4 não executam direto (mesmo via execute)")
    free_draft = await exp._draft_campaign(
        company_id=company, event_key="welcome_test",
        subscriber={**sub, "id": f"{sub['id']}-welcome"},
        template_id="welcome", approval_level=1)
    if free_draft is None:
        await db.experience_campaigns.delete_many(
            {"event_key": "welcome_test"})
        free_draft = await exp._draft_campaign(
            company_id=company, event_key="welcome_test",
            subscriber={**sub, "id": f"{sub['id']}-welcome"},
            template_id="welcome", approval_level=1)
    _ok(free_draft["auto_execute"] is True
        and free_draft["status"] == "READY",
        "L1 (sem custo) → status=READY auto_execute=True")
    fin_draft = await exp._draft_campaign(
        company_id=company, event_key="pizza_test_fin",
        subscriber={**sub, "id": f"{sub['id']}-fin"},
        template_id="vip_pizza", approval_level=3,
        estimated_cost_brl=45.0)
    _ok(fin_draft["auto_execute"] is False,
        "L3 (financeira) → auto_execute=False")
    blocked_fin = False
    try:
        await exp.execute_campaign(
            campaign_id=fin_draft["id"], company_id=company,
            actor="auditor_anonimo")
    except PermissionError:
        blocked_fin = True
    _ok(blocked_fin, "execução de L3 bloqueada sem aprovação")

    # Limpeza
    await db.experience_campaigns.delete_many(
        {"event_key": {"$regex": "^(vip_pizza_test|welcome_test|"
                                   "pizza_test_fin|vip_pizza_lvl).*"}})
    await db.experience_campaigns_audit.delete_many(
        {"campaign_id": draft["id"]})

    print("\n" + ("OK" if failed == 0 else f"FAILED {failed}"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
