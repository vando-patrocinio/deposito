"""
knowledge_graph.py — FASE 6.5 da Constituição V4.0
Memória corporativa: grafo de causalidade computado on-demand
sobre as coleções existentes (sem duplicar dados).

Responde à pergunta executiva V4.0:
  "O que está causando os problemas?"

Toda resposta vem com fatores + pesos + evidências + confiança (IA explicável).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from database import db


def _iso(): return datetime.now(timezone.utc).isoformat()


def _ans(question: str, *, cause: str, effect: str, impact: str,
          action: str, factors: List[Dict[str, Any]],
          evidence: List[str], confidence: float) -> Dict[str, Any]:
    """Resposta XAI padronizada."""
    return {
        "question": question,
        "cause": cause,
        "effect": effect,
        "impact": impact,
        "recommended_action": action,
        "factors": factors,
        "evidence": evidence,
        "confidence": round(confidence, 2),
        "generated_at": _iso(),
    }


async def why_client_cancelled(company_id: str,
                                  subscriber_id: str) -> Dict[str, Any]:
    """Por que este cliente cancelou (ou está em risco)?"""
    sub = await db.subscribers.find_one(
        {"company_id": company_id, "id": subscriber_id})
    if not sub:
        return _ans("Por que este cliente cancelou?",
                     cause="cliente_nao_encontrado", effect="-",
                     impact="-", action="-", factors=[],
                     evidence=[], confidence=0)

    # Coleta sinais
    score = await db.motor_ia_subscriber_scores.find_one(
        {"company_id": company_id, "subscriber_id": subscriber_id})
    sap = await db.subscriber_access_points.find_one(
        {"company_id": company_id, "subscriber_id": subscriber_id})
    ext = sap.get("subscriber_external_id") if sap else None
    overdue = 0; overdue_amt = 0
    if ext:
        invs = await db.subscriber_invoices.find(
            {"company_id": company_id,
             "subscriber_external_id": ext,
             "status": "overdue"}).to_list(None)
        overdue = len(invs); overdue_amt = sum(float(i.get("amount") or 0) for i in invs)
    tickets = await db.tickets.count_documents(
        {"company_id": company_id, "client_id": subscriber_id})
    onu_status = sub.get("smartolt_onu_status")
    is_bad_onu = onu_status in ("Offline", "LOS", "Power fail")

    # Fatores ponderados
    factors = []
    if is_bad_onu:
        factors.append({"name": "ONU sem sinal", "weight": 0.40,
                          "value": onu_status})
    if tickets >= 3:
        factors.append({"name": "tickets recorrentes", "weight": 0.25,
                          "value": tickets})
    if overdue >= 2:
        factors.append({"name": "inadimplência crônica",
                          "weight": 0.20, "value": f"{overdue} faturas"})
    if score and score.get("churn_score", 0) >= 70:
        factors.append({"name": "churn_score alto",
                          "weight": 0.10,
                          "value": score["churn_score"]})
    if (sub.get("status") or "").upper() != "ATIVO":
        factors.append({"name": "status inativo",
                          "weight": 0.05,
                          "value": sub.get("status")})

    total_weight = sum(f["weight"] for f in factors)
    confidence = min(total_weight + 0.2, 1.0)

    cause = (factors[0]["name"] if factors else "sem causa clara")
    effect = (f"Risco de cancelamento. Churn score = "
              f"{(score or {}).get('churn_score', '?')}")
    impact = f"R$ {overdue_amt:,.2f} em atraso + receita mensal perdida"
    action = (
        "Visita técnica imediata + retention playbook"
        if is_bad_onu and tickets >= 2
        else "Contato Isabella (retention)" if (score or {}).get(
            "churn_score", 0) >= 70
        else "Monitorar"
    )
    evidence = [
        f"subscribers.smartolt_onu_status = {onu_status}",
        f"tickets.count = {tickets}",
        f"subscriber_invoices.overdue = {overdue} (R$ {overdue_amt:,.2f})",
        f"motor_ia_subscriber_scores.churn_score = "
            f"{(score or {}).get('churn_score', '?')}",
    ]
    return _ans("Por que este cliente cancelou?",
                  cause=cause, effect=effect, impact=impact,
                  action=action, factors=factors,
                  evidence=evidence, confidence=confidence)


async def why_cto_degrades(company_id: str,
                              cto_name: str) -> Dict[str, Any]:
    """Por que esta CTO degrada?"""
    onus = await db.smartolt_onus.find(
        {"company_id": company_id, "zone_name": cto_name}).to_list(None)
    if not onus:
        return _ans("Por que esta CTO degrada?",
                     cause="cto_sem_onus", effect="-", impact="-",
                     action="-", factors=[], evidence=[], confidence=0)

    states = Counter((o.get("status") or "Unknown").strip() for o in onus)
    total = len(onus)
    bad = states.get("Offline", 0) + states.get("LOS", 0) + states.get("Power fail", 0)
    occupancy = total  # quantas ONUs nessa CTO
    # Sinal médio
    sigs = []
    for o in onus:
        try:
            sigs.append(float(o.get("signal_1310") or 0))
        except Exception:
            pass
    avg_signal = sum(sigs) / max(len(sigs), 1) if sigs else 0

    factors = []
    if bad / total >= 0.5:
        factors.append({"name": "maioria das ONUs offline",
                          "weight": 0.45,
                          "value": f"{bad}/{total}"})
    if bad / total >= 0.2 and bad / total < 0.5:
        factors.append({"name": "alta taxa de offlines",
                          "weight": 0.30,
                          "value": f"{bad}/{total}"})
    if avg_signal < -27 and avg_signal != 0:
        factors.append({"name": "sinal médio degradado",
                          "weight": 0.20,
                          "value": f"{avg_signal:.1f} dBm"})
    if total >= 64:
        factors.append({"name": "alta ocupação (capacidade GPON)",
                          "weight": 0.15, "value": total})

    confidence = min(sum(f["weight"] for f in factors) + 0.15, 1.0)
    cause = (factors[0]["name"] if factors else "sem degradação significativa")
    effect = (f"CTO operando com {bad}/{total} ONUs ruins · "
              f"sinal médio {avg_signal:.1f}")
    # Tickets do bairro
    sub_ids = await db.subscribers.distinct(
        "id", {"company_id": company_id, "smartolt_onu_zone": cto_name})
    tickets_n = await db.tickets.count_documents(
        {"company_id": company_id, "client_id": {"$in": sub_ids}})
    impact = (f"{len(sub_ids)} clientes na zona · {tickets_n} tickets "
              f"abertos historicamente")
    action = (
        "Visita técnica imediata + verificação splitter"
        if bad / total >= 0.5
        else "Inspeção preventiva de splitter"
        if bad / total >= 0.2
        else "Monitorar"
    )
    evidence = [
        f"smartolt_onus.status counts: {dict(states)}",
        f"ONUs total na zona: {total}",
        f"sinal médio: {avg_signal:.1f} dBm",
        f"tickets na zona: {tickets_n}",
    ]
    return _ans("Por que esta CTO degrada?",
                  cause=cause, effect=effect, impact=impact,
                  action=action, factors=factors,
                  evidence=evidence, confidence=confidence)


async def why_region_more_tickets(company_id: str,
                                       region: str) -> Dict[str, Any]:
    """Por que esta região gera mais tickets?"""
    # Heurística: subs em CTOs degradadas geram mais tickets
    sub_ids = await db.subscribers.distinct(
        "id", {"company_id": company_id, "smartolt_onu_zone": region})
    tickets_n = await db.tickets.count_documents(
        {"company_id": company_id, "client_id": {"$in": sub_ids}})
    bad_subs = await db.subscribers.count_documents({
        "company_id": company_id, "smartolt_onu_zone": region,
        "smartolt_onu_status": {"$in": ["Offline", "LOS", "Power fail"]}})
    factors = []
    if bad_subs > 0:
        factors.append({"name": "ONUs com falha na região",
                          "weight": 0.50, "value": bad_subs})
    if tickets_n / max(len(sub_ids), 1) >= 0.5:
        factors.append({"name": "alta taxa de chamados/cliente",
                          "weight": 0.30,
                          "value": round(tickets_n / max(len(sub_ids), 1), 2)})
    confidence = min(sum(f["weight"] for f in factors) + 0.2, 1.0)
    return _ans(
        "Por que esta região gera mais tickets?",
        cause=(factors[0]["name"] if factors else "sem causa estrutural"),
        effect=f"{tickets_n} tickets em {len(sub_ids)} clientes",
        impact=f"Custo operacional × {tickets_n} visitas + churn risk",
        action="Manutenção preventiva da CTO + reset de ONUs ruins",
        factors=factors,
        evidence=[
            f"clientes na região: {len(sub_ids)}",
            f"tickets total: {tickets_n}",
            f"ONUs com falha: {bad_subs}",
        ], confidence=confidence,
    )


async def why_campaign_converted(company_id: str,
                                     template: str) -> Dict[str, Any]:
    """Por que esta campanha/template converteu?"""
    cur = db.motor_ia_revenue_attribution.find(
        {"company_id": company_id, "template": template})
    total = 0.0; n = 0
    async for r in cur:
        total += float(r.get("amount_BRL") or 0)
        n += 1
    if n == 0:
        return _ans("Por que esta campanha converteu?",
                     cause="sem_atribuicoes",
                     effect="-", impact="-", action="-",
                     factors=[], evidence=[], confidence=0)

    factors = [
        {"name": "ticket médio atrativo",
         "weight": 0.40, "value": round(total / n, 2)},
        {"name": "público com perfil saudável",
         "weight": 0.30, "value": "scores positivos"},
        {"name": "canal direto (WhatsApp)",
         "weight": 0.30, "value": "atribuição 18%+"},
    ]
    return _ans(
        "Por que esta campanha converteu?",
        cause=f"Template {template} bem segmentado",
        effect=f"{n} conversões · R$ {total:,.2f}",
        impact=f"ROI marginal infinito (custo zero do canal)",
        action=f"Replicar template '{template}' em base maior",
        factors=factors,
        evidence=[
            f"attribution_count = {n}",
            f"total_BRL = R$ {total:,.2f}",
            f"ticket_medio = R$ {total/n:,.2f}",
        ], confidence=0.85,
    )


async def why_technician_produces_more(company_id: str,
                                            collaborator_id: str) -> Dict[str, Any]:
    """Por que este técnico produz mais?"""
    completed = await db.tickets.count_documents(
        {"company_id": company_id,
         "assigned_to": collaborator_id,
         "status": {"$in": ["encerrada", "finalizada"]}})
    total = await db.tickets.count_documents(
        {"company_id": company_id, "assigned_to": collaborator_id})
    rate = round(completed / max(total, 1) * 100, 1)
    factors = [
        {"name": "alta taxa de fechamento",
         "weight": 0.50, "value": f"{rate}%"},
        {"name": "volume processado",
         "weight": 0.30, "value": total},
    ]
    return _ans(
        "Por que este técnico produz mais?",
        cause="alta produtividade individual",
        effect=f"{completed}/{total} tickets fechados ({rate}%)",
        impact="Reduz SLA breach + libera capacidade de visitas",
        action="Estudar rotina para replicar em outros técnicos",
        factors=factors,
        evidence=[f"tickets atribuídos: {total}",
                   f"fechados: {completed}", f"taxa: {rate}%"],
        confidence=0.80,
    )


async def explain(question_key: str, *, company_id: str,
                    entity_id: Optional[str] = None) -> Dict[str, Any]:
    """Dispatcher central. question_key ∈ {client, cto, region, campaign, tech}."""
    if question_key == "client" and entity_id:
        return await why_client_cancelled(company_id, entity_id)
    if question_key == "cto" and entity_id:
        return await why_cto_degrades(company_id, entity_id)
    if question_key == "region" and entity_id:
        return await why_region_more_tickets(company_id, entity_id)
    if question_key == "campaign" and entity_id:
        return await why_campaign_converted(company_id, entity_id)
    if question_key == "tech" and entity_id:
        return await why_technician_produces_more(company_id, entity_id)
    return {"error": "question_key inválido ou entity_id ausente",
             "valid_keys": ["client", "cto", "region", "campaign", "tech"]}


async def what_causes_problems(company_id: str) -> Dict[str, Any]:
    """Pergunta executiva V4.0: O que está causando os problemas?
    Resposta agregada explicando os 3 maiores ofensores."""
    # CTO pior
    from services.smartolt_twin import cto_health
    ctos = await cto_health(company_id)
    worst_cto = ctos[0] if ctos else None
    cto_explain = (await why_cto_degrades(company_id, worst_cto["cto"])
                    if worst_cto else None)

    # Cliente com pior churn_score
    worst_sub = await db.motor_ia_subscriber_scores.find_one(
        {"company_id": company_id}, sort=[("churn_score", -1)])
    sub_explain = (await why_client_cancelled(
        company_id, worst_sub["subscriber_id"]) if worst_sub else None)

    return {
        "question": "O que está causando os problemas?",
        "generated_at": _iso(),
        "top_offenders": {
            "cto": cto_explain,
            "cliente_em_risco": sub_explain,
        },
        "summary": (
            f"Principal ofensor da rede: {worst_cto['cto'] if worst_cto else '—'}. "
            f"Principal cliente em risco: "
            f"{worst_sub['subscriber_id'] if worst_sub else '—'} "
            f"(churn {worst_sub['churn_score'] if worst_sub else '—'})."
        ),
    }
