"""
data_quality_v2.py — FASE 2 da Constituição SmartProv V3.0

Score corporativo de qualidade de dados em 6 domínios:
  1. clientes    (subscribers: document, phone, whatsapp, address, status)
  2. rede        (subscribers: pppoe_user, smartolt_onu_sn, current_vlan_olt)
  3. financeiro  (subscriber_invoices: amount, due_date, status, subscriber_external_id)
  4. whatsapp    (subscriber_phones is_whatsapp, normalized_number)
  5. smartolt    (smartolt_onus: sn, status, signal_1310 conhecidos)
  6. consistencia (cross-checks: ONU órfãs, subs sem ONU, duplicidades)

Score por domínio: % de docs que passam TODOS os critérios.
Score geral = média ponderada (peso configurável).

Alerta:
  >= 95: SAUDAVEL
  90-94: AMARELO
  80-89: VERMELHO
  < 80:  INCIDENTE_EXECUTIVO

Revenue Impact:
  R$ "represado" por gaps de dado = soma de overdue invoices em subs
  sem phone/whatsapp (impossível cobrar via canal automático).
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional

from database import db


DOMAIN_WEIGHTS = {
    "clientes":     0.25,
    "rede":         0.20,
    "financeiro":   0.20,
    "whatsapp":     0.15,
    "smartolt":     0.10,
    "consistencia": 0.10,
}


def _level(score: float) -> str:
    if score >= 95:
        return "SAUDAVEL"
    if score >= 90:
        return "AMARELO"
    if score >= 80:
        return "VERMELHO"
    return "INCIDENTE_EXECUTIVO"


def _pct(num: int, den: int) -> float:
    return round(num / den * 100, 2) if den else 0.0


async def score_clientes(company_id: str) -> Dict[str, Any]:
    """Subscribers válidos: document + phone + (whatsapp OR phone) + status."""
    q = {"company_id": company_id, "status": {"$nin": ["INATIVO", "INACTIVE"]}}
    total = await db.subscribers.count_documents(q)
    if total == 0:
        return {"score": 0, "total": 0, "ok": 0, "issues": {}}
    with_doc = await db.subscribers.count_documents({**q, "document": {"$nin": [None, ""]}})
    with_phone = await db.subscribers.count_documents({**q, "phone": {"$nin": [None, ""]}})
    with_wa = await db.subscribers.count_documents({**q, "whatsapp": {"$nin": [None, ""]}})
    with_addr = await db.subscriber_addresses.count_documents({"company_id": company_id})
    # ok = subset com TODOS os 3 críticos (doc + phone + wa)
    ok = await db.subscribers.count_documents({
        **q,
        "document": {"$nin": [None, ""]},
        "phone": {"$nin": [None, ""]},
        "whatsapp": {"$nin": [None, ""]},
    })
    return {
        "score": _pct(ok, total),
        "total": total,
        "ok": ok,
        "indicators": {
            "document_pct": _pct(with_doc, total),
            "phone_pct": _pct(with_phone, total),
            "whatsapp_pct": _pct(with_wa, total),
        },
        "issues": {
            "missing_document": total - with_doc,
            "missing_phone": total - with_phone,
            "missing_whatsapp": total - with_wa,
        },
    }


async def score_rede(company_id: str) -> Dict[str, Any]:
    """Subscribers com vínculo de rede: pppoe + ONU + VLAN."""
    q = {"company_id": company_id, "status": {"$nin": ["INATIVO", "INACTIVE"]}}
    total = await db.subscribers.count_documents(q)
    if total == 0:
        return {"score": 0, "total": 0, "ok": 0, "issues": {}}
    with_pppoe = await db.subscribers.count_documents(
        {**q, "pppoe_user": {"$nin": [None, ""]}})
    with_onu = await db.subscribers.count_documents(
        {**q, "smartolt_onu_sn": {"$nin": [None, ""]}})
    with_vlan = await db.subscribers.count_documents(
        {**q, "current_vlan_olt": {"$nin": [None, ""]}})
    ok = await db.subscribers.count_documents({
        **q,
        "pppoe_user": {"$nin": [None, ""]},
        "smartolt_onu_sn": {"$nin": [None, ""]},
    })
    return {
        "score": _pct(ok, total),
        "total": total,
        "ok": ok,
        "indicators": {
            "pppoe_pct": _pct(with_pppoe, total),
            "smartolt_onu_pct": _pct(with_onu, total),
            "current_vlan_pct": _pct(with_vlan, total),
        },
        "issues": {
            "missing_pppoe": total - with_pppoe,
            "missing_onu_link": total - with_onu,
            "missing_vlan": total - with_vlan,
        },
    }


async def score_financeiro(company_id: str) -> Dict[str, Any]:
    """Invoices com dados completos para cobrança automática."""
    q = {"company_id": company_id}
    total = await db.subscriber_invoices.count_documents(q)
    if total == 0:
        return {"score": 0, "total": 0, "ok": 0, "issues": {}}
    with_amount = await db.subscriber_invoices.count_documents(
        {**q, "amount": {"$gt": 0}})
    with_due = await db.subscriber_invoices.count_documents(
        {**q, "due_date": {"$nin": [None, ""]}})
    with_ext = await db.subscriber_invoices.count_documents(
        {**q, "subscriber_external_id": {"$nin": [None, ""]}})
    with_status = await db.subscriber_invoices.count_documents(
        {**q, "status": {"$in": ["open", "overdue", "paid", "canceled"]}})
    ok = await db.subscriber_invoices.count_documents({
        **q,
        "amount": {"$gt": 0},
        "due_date": {"$nin": [None, ""]},
        "subscriber_external_id": {"$nin": [None, ""]},
        "status": {"$in": ["open", "overdue", "paid", "canceled"]},
    })
    return {
        "score": _pct(ok, total),
        "total": total,
        "ok": ok,
        "indicators": {
            "amount_pct": _pct(with_amount, total),
            "due_date_pct": _pct(with_due, total),
            "external_id_pct": _pct(with_ext, total),
            "status_pct": _pct(with_status, total),
        },
        "issues": {
            "missing_amount": total - with_amount,
            "missing_due_date": total - with_due,
            "missing_external_id": total - with_ext,
        },
    }


async def score_whatsapp(company_id: str) -> Dict[str, Any]:
    """subscriber_phones: precisam estar normalizados e validados."""
    q = {"company_id": company_id}
    total = await db.subscriber_phones.count_documents(q)
    if total == 0:
        return {"score": 0, "total": 0, "ok": 0, "issues": {}}
    with_norm = await db.subscriber_phones.count_documents(
        {**q, "normalized_number": {"$nin": [None, ""]}})
    validated_true = await db.subscriber_phones.count_documents(
        {**q, "is_whatsapp": True})
    not_false = await db.subscriber_phones.count_documents(
        {**q, "is_whatsapp": {"$ne": False}})
    # ok = normalizado + is_whatsapp != False
    ok = await db.subscriber_phones.count_documents({
        **q,
        "normalized_number": {"$nin": [None, ""]},
        "is_whatsapp": {"$ne": False},
    })
    return {
        "score": _pct(ok, total),
        "total": total,
        "ok": ok,
        "indicators": {
            "normalized_pct": _pct(with_norm, total),
            "is_whatsapp_true_pct": _pct(validated_true, total),
            "not_invalidated_pct": _pct(not_false, total),
        },
        "issues": {
            "not_normalized": total - with_norm,
            "validation_pending": total - validated_true,
        },
    }


async def score_smartolt(company_id: str) -> Dict[str, Any]:
    """ONUs com SN + status conhecido."""
    q = {"company_id": company_id}
    total = await db.smartolt_onus.count_documents(q)
    if total == 0:
        return {"score": 0, "total": 0, "ok": 0, "issues": {}}
    with_sn = await db.smartolt_onus.count_documents(
        {**q, "sn": {"$nin": [None, ""]}})
    with_status = await db.smartolt_onus.count_documents(
        {**q, "status": {"$nin": [None, ""]}})
    with_signal = await db.smartolt_onus.count_documents(
        {**q, "signal_1310": {"$nin": [None, ""]}})
    ok = await db.smartolt_onus.count_documents({
        **q,
        "sn": {"$nin": [None, ""]},
        "status": {"$nin": [None, ""]},
    })
    return {
        "score": _pct(ok, total),
        "total": total,
        "ok": ok,
        "indicators": {
            "sn_pct": _pct(with_sn, total),
            "status_pct": _pct(with_status, total),
            "signal_pct": _pct(with_signal, total),
        },
        "issues": {
            "missing_sn": total - with_sn,
            "missing_status": total - with_status,
        },
    }


async def score_consistencia(company_id: str) -> Dict[str, Any]:
    """Cross-checks: ONUs sem sub, subs sem ONU, duplicidades."""
    q = {"company_id": company_id}
    # ONUs sem assinante (orfãs)
    linked_sns = await db.subscribers.distinct(
        "smartolt_onu_sn", {**q, "smartolt_onu_sn": {"$nin": [None, ""]}})
    total_onus = await db.smartolt_onus.count_documents(q)
    orfas = total_onus - len(set(linked_sns).intersection(
        set(await db.smartolt_onus.distinct("sn", q))
    ))
    # Subs sem ONU (entre os ATIVOS)
    active = await db.subscribers.count_documents(
        {**q, "status": {"$in": ["ATIVO", "active"]}})
    sem_onu = await db.subscribers.count_documents(
        {**q, "status": {"$in": ["ATIVO", "active"]},
         "smartolt_onu_sn": {"$in": [None, ""]}})
    # Duplicidades de telefone
    pipe = [
        {"$match": {**q, "normalized_number": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$normalized_number", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$count": "n"},
    ]
    dup_phones = 0
    async for r in db.subscriber_phones.aggregate(pipe):
        dup_phones = r.get("n", 0)

    # Duplicidades de document em subscribers
    pipe2 = [
        {"$match": {**q, "document": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$document", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$count": "n"},
    ]
    dup_docs = 0
    async for r in db.subscribers.aggregate(pipe2):
        dup_docs = r.get("n", 0)

    # Score: 100 - penalidade %
    total_active = max(active, 1)
    penalty_orfas = min(orfas / max(total_onus, 1) * 100, 30)
    penalty_sem_onu = min(sem_onu / total_active * 100 * 0.5, 30)
    penalty_dup_ph = min(dup_phones * 2, 20)
    penalty_dup_doc = min(dup_docs * 5, 20)
    score = max(100 - penalty_orfas - penalty_sem_onu
                - penalty_dup_ph - penalty_dup_doc, 0)
    return {
        "score": round(score, 2),
        "indicators": {
            "onus_orfas": orfas,
            "subs_ativos_sem_onu": sem_onu,
            "duplicate_phones": dup_phones,
            "duplicate_documents": dup_docs,
            "active_subs": active,
            "total_onus": total_onus,
        },
        "issues": {
            "onus_sem_subscriber": orfas,
            "subscribers_sem_onu": sem_onu,
            "phones_duplicados": dup_phones,
            "documentos_duplicados": dup_docs,
        },
    }


async def revenue_impact(company_id: str) -> Dict[str, Any]:
    """Quanto $ está represado por dados ruins (carteira inadimplente
    em clientes que NÃO temos como cobrar automaticamente)."""
    q = {"company_id": company_id, "status": "overdue"}
    overdue = await db.subscriber_invoices.find(q).to_list(None)
    if not overdue:
        return {"locked_BRL": 0, "locked_count": 0, "reasons": {},
                "total_overdue_BRL": 0, "total_overdue_count": 0,
                "actionable_pct": 100.0}

    # Resolve subscriber via SAP
    ext_ids = [i.get("subscriber_external_id") for i in overdue
               if i.get("subscriber_external_id")]
    saps = await db.subscriber_access_points.find(
        {"company_id": company_id,
         "subscriber_external_id": {"$in": ext_ids}}
    ).to_list(None)
    sap_by_ext = {s["subscriber_external_id"]: s for s in saps}
    sub_ids = list({s["subscriber_id"] for s in saps if s.get("subscriber_id")})
    subs = await db.subscribers.find(
        {"company_id": company_id, "id": {"$in": sub_ids}}
    ).to_list(None)
    sub_by_id = {s["id"]: s for s in subs}

    locked = 0.0
    locked_count = 0
    reasons = Counter()
    for inv in overdue:
        ext = inv.get("subscriber_external_id")
        sap = sap_by_ext.get(ext)
        sub = sub_by_id.get(sap["subscriber_id"]) if sap else None
        amt = float(inv.get("amount") or 0)
        # critérios bloqueantes
        if not sub:
            locked += amt
            locked_count += 1
            reasons["sem_subscriber_resolvido"] += 1
            continue
        if not sub.get("phone") and not sub.get("whatsapp"):
            locked += amt
            locked_count += 1
            reasons["sem_telefone_whatsapp"] += 1
            continue
        # Se tem phone mas onu desconhecida (gate vai bloquear cobrança)
        if not sub.get("smartolt_onu_sn"):
            # half-locked: bloqueia parcialmente (~25% risco)
            locked += amt * 0.25
            reasons["sem_onu_link"] += 1

    return {
        "locked_BRL": round(locked, 2),
        "locked_count": locked_count,
        "total_overdue_BRL": round(sum(float(i.get("amount") or 0)
                                         for i in overdue), 2),
        "total_overdue_count": len(overdue),
        "reasons": dict(reasons),
        "actionable_pct": round(
            (1 - locked / max(sum(float(i.get("amount") or 0)
                                  for i in overdue), 1)) * 100, 1),
    }


async def full_report(company_id: str) -> Dict[str, Any]:
    """Score completo: 6 domínios + overall + revenue impact."""
    clientes = await score_clientes(company_id)
    rede = await score_rede(company_id)
    fin = await score_financeiro(company_id)
    wa = await score_whatsapp(company_id)
    olt = await score_smartolt(company_id)
    cons = await score_consistencia(company_id)
    rev = await revenue_impact(company_id)

    overall = round(
        clientes["score"] * DOMAIN_WEIGHTS["clientes"]
        + rede["score"] * DOMAIN_WEIGHTS["rede"]
        + fin["score"] * DOMAIN_WEIGHTS["financeiro"]
        + wa["score"] * DOMAIN_WEIGHTS["whatsapp"]
        + olt["score"] * DOMAIN_WEIGHTS["smartolt"]
        + cons["score"] * DOMAIN_WEIGHTS["consistencia"],
        2,
    )

    domains = {
        "clientes": clientes,
        "rede": rede,
        "financeiro": fin,
        "whatsapp": wa,
        "smartolt": olt,
        "consistencia": cons,
    }
    return {
        "company_id": company_id,
        "overall_score": overall,
        "overall_level": _level(overall),
        "domains": domains,
        "domain_weights": DOMAIN_WEIGHTS,
        "revenue_impact": rev,
        "answers": {
            "qualidade_hoje": f"{overall}% ({_level(overall)})",
            "principal_gap": _principal_gap(domains),
            "impacto_financeiro": (
                f"R$ {rev['locked_BRL']:,.2f} represados em "
                f"{rev['locked_count']} faturas por dados ruins. "
                f"{rev['actionable_pct']}% da carteira está acionável."
            ),
            "corrigir_primeiro": _next_action(domains),
        },
    }


def _principal_gap(domains: Dict[str, Dict[str, Any]]) -> str:
    """Domínio com menor score = onde está o gap."""
    worst = min(domains.items(), key=lambda kv: kv[1]["score"])
    return f"{worst[0]} ({worst[1]['score']}%)"


def _next_action(domains: Dict[str, Dict[str, Any]]) -> str:
    """Sugere ação ofensiva no domínio mais fraco."""
    worst = min(domains.items(), key=lambda kv: kv[1]["score"])
    issues = worst[1].get("issues", {})
    if not issues:
        return f"Investigar {worst[0]} ({worst[1]['score']}%)"
    top_issue = max(issues.items(), key=lambda kv: kv[1])
    return (f"Resolver '{top_issue[0]}' em {worst[0]}: "
            f"{top_issue[1]} casos pendentes.")
