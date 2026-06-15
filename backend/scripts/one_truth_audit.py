"""ONE_TRUTH_AUDIT — coleta multi-fonte por KPI.

Roda direto contra o Mongo de co-demo (sem sintéticos).
Saída: JSON imprimível pronto para o relatório.
"""
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app/backend")
from database import db  # noqa: E402
from constants.synthetic_tenants import SYNTHETIC_TENANTS  # noqa: E402

CO = "co-demo"


def pct(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return abs(a - b) / max(abs(b), 1e-9) * 100.0


async def kpi_clients():
    # Fonte oficial (ONE_TRUTH_MATRIX): subscribers.status == "active"
    a = await db.subscribers.count_documents({"company_id": CO, "status": "active"})
    # Fonte secundária: loyalty_imported_db.status == "Ativo"
    b = await db.loyalty_imported_db.count_documents({"company_id": CO, "status": "Ativo"})
    # Sanidade extra: subscribers ativos com document válido
    c = await db.subscribers.count_documents({"company_id": CO, "status": "active",
                                              "document": {"$nin": ["", None]}})
    return {
        "kpi": "Clientes Ativos",
        "official_label": "subscribers.count({status:'active'})",
        "official_value": a,
        "secondary_label": "loyalty_imported_db.count({status:'Ativo'})",
        "secondary_value": b,
        "extra_label": "subscribers ativos com document válido",
        "extra_value": c,
        "divergence_pct": pct(a, b),
        "class": "PRIMÁRIA (0%)",
    }


async def kpi_revenue():
    # Fonte oficial (atual): MRR snapshot calculado de subscribers ativos com plan_price
    # Pipeline 1: subscribers.status=active × plan_price
    pipe1 = [
        {"$match": {"company_id": CO, "status": "active"}},
        {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$plan_price", 0]}}}},
    ]
    cur = db.subscribers.aggregate(pipe1)
    r1 = await cur.to_list(1)
    mrr_subs = float(r1[0]["total"]) if r1 else 0.0

    # Fonte secundária: loyalty_imported_db.status=Ativo × monthly_fee
    pipe2 = [
        {"$match": {"company_id": CO, "status": "Ativo"}},
        {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$monthly_fee", 0]}}}},
    ]
    cur = db.loyalty_imported_db.aggregate(pipe2)
    r2 = await cur.to_list(1)
    mrr_loyalty = float(r2[0]["total"]) if r2 else 0.0

    # Fonte terciária: invoices pagas no mês corrente
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc).isoformat()
    invoice_collections = []
    for name in ["subscriber_invoices", "invoices", "payments_in",
                 "scheduled_payments", "asaas_payments"]:
        exists = await db[name].count_documents({"company_id": CO}, limit=1)
        if exists:
            invoice_collections.append(name)

    paid_total = None
    paid_source = None
    for col in invoice_collections:
        pipe3 = [
            {"$match": {"company_id": CO,
                        "$or": [
                            {"status": {"$in": ["paid", "RECEIVED", "CONFIRMED",
                                                 "RECEIVED_IN_CASH", "Pago"]}},
                            {"paid_at": {"$gte": month_start}},
                        ]}},
            {"$group": {"_id": None,
                        "total": {"$sum": {"$ifNull": ["$amount",
                                                       {"$ifNull": ["$value",
                                                                    {"$ifNull": ["$paid_amount", 0]}]}]}}}},
        ]
        try:
            cur = db[col].aggregate(pipe3)
            r = await cur.to_list(1)
            val = float(r[0]["total"]) if r else 0.0
            if val > 0:
                paid_total = val
                paid_source = col
                break
        except Exception:
            pass

    return {
        "kpi": "Receita (MRR mensal)",
        "official_label": "Σ(subscribers.plan_price WHERE status='active')",
        "official_value": round(mrr_subs, 2),
        "secondary_label": "Σ(loyalty_imported_db.monthly_fee WHERE status='Ativo')",
        "secondary_value": round(mrr_loyalty, 2),
        "extra_label": f"Σ(invoices pagas no mês via {paid_source or 'N/A'})",
        "extra_value": round(paid_total or 0.0, 2),
        "divergence_pct": pct(mrr_subs, mrr_loyalty),
        "class": "PRIMÁRIA (0%)",
        "extra_meta": {
            "invoice_collections_present": invoice_collections,
            "month_start": month_start,
        },
    }


async def kpi_tickets():
    # Tickets abertos hoje em co-demo
    a = await db.tickets.count_documents({"company_id": CO, "status": "open"})
    # Secundária: tickets com state="open" (vocabulário alternativo)
    b = await db.tickets.count_documents({"company_id": CO, "state": "open"})
    # Total de tickets reais em co-demo
    total = await db.tickets.count_documents({"company_id": CO})
    # Tickets em sintéticos (deve ser ≠0 — comparar polução)
    syn = await db.tickets.count_documents({"company_id": {"$in": SYNTHETIC_TENANTS}})
    return {
        "kpi": "Tickets Abertos",
        "official_label": "tickets.count({status:'open', company_id:'co-demo'})",
        "official_value": a,
        "secondary_label": "tickets.count({state:'open', company_id:'co-demo'})",
        "secondary_value": b,
        "extra_label": "tickets totais em co-demo",
        "extra_value": total,
        "divergence_pct": pct(a, b),
        "class": "PRIMÁRIA (0%)",
        "extra_meta": {"tickets_em_tenants_sinteticos": syn},
    }


async def kpi_inadimplencia():
    # Fonte oficial proposta: loyalty.invoices_overdue agregado
    pipe = [
        {"$match": {"company_id": CO, "status": "Ativo", "invoices_overdue": {"$gt": 0}}},
        {"$group": {"_id": None,
                    "total_overdue_invoices": {"$sum": "$invoices_overdue"},
                    "customers": {"$sum": 1},
                    "monthly_at_risk": {"$sum": {"$multiply": ["$monthly_fee", "$invoices_overdue"]}}}}
    ]
    cur = db.loyalty_imported_db.aggregate(pipe)
    r = await cur.to_list(1)
    a_inv = int(r[0]["total_overdue_invoices"]) if r else 0
    a_customers = int(r[0]["customers"]) if r else 0
    a_brl = float(r[0]["monthly_at_risk"]) if r else 0.0

    # Fonte secundária: subscriber_invoices.status=overdue (se existir)
    coll_present = await db.subscriber_invoices.count_documents({"company_id": CO}, limit=1)
    b_count = 0
    b_brl = 0.0
    if coll_present:
        pipe2 = [
            {"$match": {"company_id": CO,
                        "$or": [{"status": "overdue"}, {"status": "OVERDUE"},
                                {"status": "PENDING"}, {"status": "atrasado"}]}},
            {"$group": {"_id": None,
                        "n": {"$sum": 1},
                        "total": {"$sum": {"$ifNull": ["$amount",
                                                       {"$ifNull": ["$value", 0]}]}}}}
        ]
        cur = db.subscriber_invoices.aggregate(pipe2)
        r2 = await cur.to_list(1)
        if r2:
            b_count = int(r2[0]["n"])
            b_brl = float(r2[0]["total"])

    return {
        "kpi": "Inadimplência (R$)",
        "official_label": "Σ(loyalty.monthly_fee × invoices_overdue) WHERE invoices_overdue>0",
        "official_value": round(a_brl, 2),
        "official_meta": {"customers_in_default": a_customers,
                          "total_overdue_invoices": a_inv},
        "secondary_label": "Σ(subscriber_invoices.amount WHERE status='overdue/pending')",
        "secondary_value": round(b_brl, 2),
        "secondary_meta": {"n_invoices": b_count, "collection_present": bool(coll_present)},
        "divergence_pct": pct(a_brl, b_brl) if b_brl > 0 else None,
        "class": "PRIMÁRIA (0%)",
    }


async def kpi_fundadores():
    # Critério estrito do CLIENTE_FUNDADOR_REPORT.md:
    # status Ativo + reg < 2020 + invoices_paid >= 50 + invoices_overdue = 0
    # E (no histórico do documento) nenhum status Desativado.

    # Step 1: candidatos com critério solo
    candidates = await db.loyalty_imported_db.find({
        "company_id": CO,
        "status": "Ativo",
        "invoices_overdue": 0,
        "invoices_paid": {"$gte": 50},
        "registration_date": {"$lt": "2020-01-01"},
        "document": {"$nin": ["", None]},
    }).to_list(5000)

    # Step 2: descarta candidatos cujo documento tem qualquer Desativado no histórico
    confirmed = 0
    documents_seen = set()
    for c in candidates:
        doc = c.get("document")
        if not doc or doc in documents_seen:
            continue
        documents_seen.add(doc)
        cancels = await db.loyalty_imported_db.count_documents({
            "company_id": CO, "document": doc, "status": "Desativado"
        })
        if cancels == 0:
            confirmed += 1

    # Fonte secundária: convites com invite_source='fundador' aceitos
    invites_founder = await db.universo_ligo_invites.count_documents({
        "company_id": CO,
        "invite_source": "fundador",
        "decision": "APTO",
        "status": {"$in": ["accepted", "invited_pending"]},
    })

    # Fonte terciária: relatório histórico — 130 documentos declarados em
    # CLIENTE_FUNDADOR_REPORT.md
    declared_in_doc = 130

    return {
        "kpi": "Fundadores",
        "official_label": "loyalty: status=Ativo · reg<2020 · paid≥50 · overdue=0 · sem cancel",
        "official_value": confirmed,
        "official_meta": {"candidates_pre_cancel_check": len(candidates),
                          "unique_documents_validated": len(documents_seen)},
        "secondary_label": "universo_ligo_invites.invite_source='fundador' aceitos",
        "secondary_value": invites_founder,
        "extra_label": "CLIENTE_FUNDADOR_REPORT.md (declarado)",
        "extra_value": declared_in_doc,
        "divergence_pct": pct(confirmed, declared_in_doc),
        "class": "DERIVADA (1%)",
    }


async def kpi_embaixadores():
    # Fonte oficial: universo_ligo_invites com decision=APTO + status accepted
    a = await db.universo_ligo_invites.count_documents({
        "company_id": CO,
        "decision": "APTO",
        "status": "accepted",
        "do_not_contact_universo_ligo": {"$ne": True},
    })
    # Pending (aceitos por convite mas ainda em espera)
    a_pending = await db.universo_ligo_invites.count_documents({
        "company_id": CO,
        "decision": "APTO",
        "status": "invited_pending",
        "do_not_contact_universo_ligo": {"$ne": True},
    })
    # Secundária: universo_ligo_levels (se existir) com level=embaixador
    coll_exists = "universo_ligo_levels" in await db.list_collection_names()
    b = 0
    if coll_exists:
        b = await db.universo_ligo_levels.count_documents({
            "company_id": CO, "level_key": "embaixador"
        })
    # Naturais (candidatos NÃO confirmados): EMBAIXADORES_NATURAIS.md = 113 + 17
    declared_natural = 130

    return {
        "kpi": "Embaixadores",
        "official_label": "universo_ligo_invites: APTO + accepted + sem DNC",
        "official_value": a,
        "official_meta": {"pending_invites_aptos": a_pending},
        "secondary_label": "universo_ligo_levels.level_key='embaixador'"
                           if coll_exists else "universo_ligo_levels NÃO existe",
        "secondary_value": b,
        "extra_label": "EMBAIXADORES_NATURAIS.md (candidatos NÃO confirmados)",
        "extra_value": declared_natural,
        "divergence_pct": pct(a, b) if b > 0 else 0.0,
        "class": "PRIMÁRIA (0%) — convite humano",
    }


async def main():
    print("=" * 70)
    print(f"ONE_TRUTH_AUDIT · tenant={CO} · {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)
    out = {}
    out["clientes"] = await kpi_clients()
    out["receita"] = await kpi_revenue()
    out["tickets"] = await kpi_tickets()
    out["inadimplencia"] = await kpi_inadimplencia()
    out["fundadores"] = await kpi_fundadores()
    out["embaixadores"] = await kpi_embaixadores()
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
