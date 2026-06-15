"""CUSTOMER IDENTITY AUDIT — read-only (sem writes).

Mede a aderência da identidade do cliente entre as 7 fontes do ecossistema
Ligo. Idempotente, re-executável. Saída em JSON para o relatório.

Fontes auditadas:
- subscribers              (master interno)
- loyalty_imported_db      (Atlaz · ground truth do CRM externo)
- aihub_wa_messages        (WhatsApp)
- tickets                  (operacional)
- subscriber_invoices      (financeiro)
- universo_ligo_invites    (curadoria)
- universo_ligo_score_audit (Customer Intelligence)
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from database import db  # noqa: E402
from constants.synthetic_tenants import SYNTHETIC_TENANTS  # noqa: E402

CO = "co-demo"
SUBS_ACTIVE = {"$in": ["ACTIVE", "ATIVO", "active", "ativo"]}
KPI_FILTER = {"company_id": CO, "status": SUBS_ACTIVE,
              "excluded_from_kpi": {"$ne": True}}


def pct(n: int, d: int) -> float:
    return round((n / d * 100), 2) if d else 0.0


async def audit() -> dict:
    out: dict = {"generated_at": datetime.now(timezone.utc).isoformat(),
                 "tenant": CO}

    # 1. subscribers (universe)
    total_active = await db.subscribers.count_documents(KPI_FILTER)
    with_doc = await db.subscribers.count_documents(
        {**KPI_FILTER, "document": {"$nin": ["", None]}})
    with_phone = await db.subscribers.count_documents(
        {**KPI_FILTER, "$or": [{"phone": {"$nin": ["", None]}},
                                 {"phone1": {"$nin": ["", None]}}]})
    with_email = await db.subscribers.count_documents(
        {**KPI_FILTER, "email": {"$nin": ["", None]}})
    with_external_id = await db.subscribers.count_documents(
        {**KPI_FILTER, "atlaz_external_id": {"$nin": ["", None]}})
    out["subscribers"] = {
        "total_active_real": total_active,
        "with_document": with_doc, "with_document_pct": pct(with_doc, total_active),
        "with_phone": with_phone, "with_phone_pct": pct(with_phone, total_active),
        "with_email": with_email, "with_email_pct": pct(with_email, total_active),
        "with_atlaz_external_id": with_external_id,
        "with_atlaz_external_id_pct": pct(with_external_id, total_active),
    }

    # 2. Atlaz cross — quantos subs têm CPF que casa em loyalty Ativo
    docs_active = set()
    cur = db.subscribers.find(KPI_FILTER, {"document": 1, "_id": 0})
    async for s in cur:
        d = s.get("document")
        if d:
            docs_active.add(d)
    loy_docs_active = set()
    cur = db.loyalty_imported_db.find(
        {"company_id": CO, "status": "Ativo", "document": {"$nin": ["", None]}},
        {"document": 1, "_id": 0})
    async for d in cur:
        loy_docs_active.add(d["document"])
    matched_docs = docs_active & loy_docs_active
    only_in_subs = docs_active - loy_docs_active
    only_in_loy = loy_docs_active - docs_active
    out["atlaz_match"] = {
        "subs_docs_active": len(docs_active),
        "loyalty_docs_active": len(loy_docs_active),
        "matched_documents": len(matched_docs),
        "subs_without_atlaz_match": len(only_in_subs),
        "loyalty_without_sub_match": len(only_in_loy),
        "match_pct": pct(len(matched_docs), len(docs_active)),
        "key_used": "document (CPF/CNPJ)",
    }

    # 3. WhatsApp
    wa_total = await db.aihub_wa_messages.count_documents({"company_id": CO})
    wa_with_sub = await db.aihub_wa_messages.count_documents(
        {"company_id": CO, "subscriber_id": {"$nin": ["", None]}})
    wa_with_phone = await db.aihub_wa_messages.count_documents(
        {"company_id": CO, "phone": {"$nin": ["", None]}})
    wa_unique_phones = len(await db.aihub_wa_messages.distinct(
        "phone", {"company_id": CO}))
    wa_unique_subs = len(await db.aihub_wa_messages.distinct(
        "subscriber_id", {"company_id": CO, "subscriber_id": {"$nin": ["", None]}}))
    out["whatsapp"] = {
        "total_messages": wa_total,
        "with_subscriber_id": wa_with_sub,
        "with_subscriber_id_pct": pct(wa_with_sub, wa_total),
        "with_phone": wa_with_phone,
        "unique_phones": wa_unique_phones,
        "unique_subscribers_linked": wa_unique_subs,
        "key_used": "subscriber_id resolved from phone",
    }

    # 4. Tickets
    t_total = await db.tickets.count_documents({"company_id": CO})
    t_with_sub = await db.tickets.count_documents(
        {"company_id": CO, "subscriber_id": {"$nin": ["", None]}})
    t_with_atlaz_assinante = await db.tickets.count_documents(
        {"company_id": CO, "atlaz_id_assinante": {"$nin": ["", None]}})
    t_with_external = await db.tickets.count_documents(
        {"company_id": CO, "atlaz_external_id": {"$nin": ["", None]}})
    t_unique_subs = len(await db.tickets.distinct(
        "subscriber_id", {"company_id": CO, "subscriber_id": {"$nin": ["", None]}}))
    out["tickets"] = {
        "total": t_total,
        "with_subscriber_id": t_with_sub,
        "with_subscriber_id_pct": pct(t_with_sub, t_total),
        "with_atlaz_id_assinante": t_with_atlaz_assinante,
        "with_atlaz_external_id": t_with_external,
        "unique_subscribers_linked": t_unique_subs,
        "key_used": "subscriber_id (canônico) + atlaz_id_assinante (espelho)",
    }

    # 5. Faturas
    inv_total = await db.subscriber_invoices.count_documents({"company_id": CO})
    inv_with_sub = await db.subscriber_invoices.count_documents(
        {"company_id": CO, "subscriber_id": {"$nin": ["", None]}})
    inv_with_doc = await db.subscriber_invoices.count_documents(
        {"company_id": CO, "subscriber_document": {"$nin": ["", None]}})
    inv_with_external = await db.subscriber_invoices.count_documents(
        {"company_id": CO, "subscriber_external_id": {"$nin": ["", None]}})
    inv_unique_subs = len(await db.subscriber_invoices.distinct(
        "subscriber_id", {"company_id": CO, "subscriber_id": {"$nin": ["", None]}}))
    out["invoices"] = {
        "total": inv_total,
        "with_subscriber_id": inv_with_sub,
        "with_subscriber_id_pct": pct(inv_with_sub, inv_total),
        "with_subscriber_document": inv_with_doc,
        "with_subscriber_external_id": inv_with_external,
        "unique_subscribers_linked": inv_unique_subs,
        "key_used": "subscriber_id (canônico) + subscriber_document (espelho)",
    }

    # 6. Universo Ligo
    ul_inv_total = await db.universo_ligo_invites.count_documents(
        {"company_id": CO})
    ul_inv_with_sub = await db.universo_ligo_invites.count_documents(
        {"company_id": CO, "subscriber_id": {"$nin": ["", None]}})
    ul_audit_total = await db.universo_ligo_score_audit.count_documents(
        {"company_id": CO})
    ul_audit_with_sub = await db.universo_ligo_score_audit.count_documents(
        {"company_id": CO, "subscriber_id": {"$nin": ["", None]}})
    out["universo_ligo"] = {
        "invites_total": ul_inv_total,
        "invites_with_subscriber_id": ul_inv_with_sub,
        "score_audit_total": ul_audit_total,
        "score_audit_with_subscriber_id": ul_audit_with_sub,
        "key_used": "subscriber_id",
    }

    # 7. Customer Intelligence — usa universo_ligo_score_audit (mesma chave).
    out["customer_intelligence"] = {
        "score_audit_total": ul_audit_total,
        "linked_by_subscriber_id": ul_audit_with_sub,
        "key_used": "subscriber_id",
        "feature_flag_enabled": False,
    }

    # 8. Resumo — clientes que conseguem ser UNIFICADOS hoje (tem subscriber_id
    # ativo + casa com loyalty Atlaz por document)
    unifiable_today = len(matched_docs)
    orphans = total_active - unifiable_today
    out["summary"] = {
        "active_real_subscribers": total_active,
        "unifiable_today_doc_match": unifiable_today,
        "unifiable_today_pct": pct(unifiable_today, total_active),
        "orphans_today": orphans,
        "orphans_pct": pct(orphans, total_active),
        "missing_field_priority_order": [
            "subscribers.atlaz_external_id (0% hoje)",
            "tickets.subscriber_id (parcial via atlaz_id_assinante)",
            "subscriber_invoices.subscriber_id (parcial via document/external_id)",
            "aihub_wa_messages.subscriber_id (parcial via phone resolution)",
        ],
    }
    return out


async def main() -> int:
    data = await audit()
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
