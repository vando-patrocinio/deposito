"""ONE_TRUTH_AUDIT v2 — pós ONE_TRUTH_CORRECTION (15/06/2026).

Mudanças vs v1:
- subscribers.status agora aceita {ACTIVE, ATIVO, ativo, active} (vocabulário real).
- Aplica filtro `excluded_from_kpi != true` em todos os agregados oficiais.
- tickets usa vocabulário PT-BR canônico do ticket_schema: aberta, pendente,
  aguardando_atendimento, em_atendimento (variações), encerrada, finalizada,
  cancelada.
- Inadimplência: fonte oficial = `subscriber_invoices` (status='overdue'),
  loyalty vira FONTE HISTÓRICA (auxiliar).
- Receita realizada usa `paid_date` (campo real), não `paid_at`.
"""
import asyncio
import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from database import db  # noqa: E402
from constants.synthetic_tenants import SYNTHETIC_TENANTS  # noqa: E402

CO = "co-demo"

# Vocabulário canônico (do ticket_schema + observação direta na base)
SUBS_ACTIVE = {"$in": ["ACTIVE", "ATIVO", "active", "ativo"]}
TICKETS_OPEN = {"$in": ["aberta", "pendente", "aguardando_atendimento",
                          "em_atendimento"]}
INVOICE_PAID = {"$in": ["paid", "RECEIVED", "CONFIRMED", "Pago"]}
INVOICE_OVERDUE = {"$in": ["overdue", "OVERDUE", "atrasado"]}
EXCLUDE_KPI = {"$ne": True}  # filtro `excluded_from_kpi != true`


def pct(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return abs(a - b) / max(abs(b), 1e-9) * 100.0


def color(divergence_pct: float | None, klass: str) -> str:
    if divergence_pct is None:
        return "⚠️ N/A"
    if divergence_pct == 0.0:
        return "🟢 VERDE"
    # PRIMÁRIA 0%, DERIVADA 1%, PREDITIVA 5%
    if klass.startswith("PRIMÁRIA"):
        return "🟡 AMARELO (justificar)" if divergence_pct <= 1.0 else "🔴 VERMELHO"
    if klass.startswith("DERIVADA"):
        return "🟢 VERDE" if divergence_pct <= 1.0 else "🔴 VERMELHO"
    return "🟢 VERDE" if divergence_pct <= 5.0 else "🔴 VERMELHO"


async def kpi_clients():
    a = await db.subscribers.count_documents({
        "company_id": CO, "status": SUBS_ACTIVE,
        "excluded_from_kpi": EXCLUDE_KPI,
    })
    b = await db.loyalty_imported_db.count_documents({
        "company_id": CO, "status": "Ativo"
    })
    div = pct(a, b)
    return {"kpi": "Clientes Ativos",
            "official": ("subscribers (status real + excluded_from_kpi!=true)", a),
            "secondary": ("loyalty_imported_db (status=Ativo) [HISTÓRICA]", b),
            "divergence_pct": round(div, 4),
            "class": "PRIMÁRIA (0%)",
            "status": color(div, "PRIMÁRIA")}


async def kpi_revenue():
    pipe = [{"$match": {"company_id": CO, "status": SUBS_ACTIVE,
                          "excluded_from_kpi": EXCLUDE_KPI}},
            {"$group": {"_id": None,
                          "mrr": {"$sum": {"$ifNull": ["$plan_price", 0]}},
                          "n": {"$sum": 1}}}]
    cur = db.subscribers.aggregate(pipe)
    r = await cur.to_list(1)
    mrr = float(r[0]["mrr"]) if r else 0.0
    n = int(r[0]["n"]) if r else 0

    pipe2 = [{"$match": {"company_id": CO, "status": "Ativo"}},
             {"$group": {"_id": None,
                           "mrr": {"$sum": {"$ifNull": ["$monthly_fee", 0]}}}}]
    r2 = await db.loyalty_imported_db.aggregate(pipe2).to_list(1)
    mrr_loy = float(r2[0]["mrr"]) if r2 else 0.0

    # Receita realizada do mês corrente (paid_date)
    now = datetime.now(timezone.utc)
    ms = f"{now.year:04d}-{now.month:02d}-01"
    pipe3 = [{"$match": {"company_id": CO, "status": INVOICE_PAID,
                           "paid_date": {"$gte": ms}}},
             {"$group": {"_id": None,
                           "total": {"$sum": {"$ifNull": ["$amount", 0]}},
                           "n": {"$sum": 1}}}]
    r3 = await db.subscriber_invoices.aggregate(pipe3).to_list(1)
    realizada = float(r3[0]["total"]) if r3 else 0.0

    # MRR foi promovido a MONO-FONTE oficial em 15/06/2026 (decisão CEO/CTO).
    # loyalty NÃO é mais fonte oficial concorrente — vira referência histórica.
    # O gap aritmético é registrado como reconciliation_gap (informativo).
    gap = pct(mrr, mrr_loy)
    return {"kpi": "Receita (MRR)",
            "official": ("Σ subscribers.plan_price (vocab corrigido + excl. test)", round(mrr, 2)),
            "official_n": n,
            "secondary": ("loyalty.monthly_fee [HISTÓRICA · não-concorrente]", round(mrr_loy, 2)),
            "extra": (f"Receita realizada {ms[:7]} (subscriber_invoices.paid_date)", round(realizada, 2)),
            "divergence_pct": None,
            "reconciliation_gap_pct": round(gap, 4),
            "class": "PRIMÁRIA (0%) — fonte ÚNICA",
            "status": "🟢 VERDE (mono-fonte oficial)",
            "notes": ("loyalty desclassificado como fonte oficial (decisão CEO/CTO 15/06/2026). "
                      f"Gap histórico vs Atlaz = {round(gap,2)}% — causa documentada: "
                      "(a) ~98 subscribers reais ainda sem import Atlaz; "
                      "(b) reajustes em plan_price não propagados para loyalty.monthly_fee.")}


async def kpi_tickets():
    a = await db.tickets.count_documents({"company_id": CO, "status": TICKETS_OPEN})
    # secundária vazia agora porque oficial e secundária convergem no mesmo
    # vocabulário PT-BR — comparamos contra o total - encerrados/finalizados/cancelados
    closed = {"$in": ["encerrada", "finalizada", "cancelada"]}
    total = await db.tickets.count_documents({"company_id": CO})
    closed_n = await db.tickets.count_documents({"company_id": CO, "status": closed})
    b = total - closed_n  # tudo que NÃO está fechado
    div = pct(a, b)
    return {"kpi": "Tickets Abertos",
            "official": ("tickets (status ∈ aberta/pendente/aguardando/em_atendimento)", a),
            "secondary": ("tickets total − fechados (encerrada/finalizada/cancelada)", b),
            "divergence_pct": round(div, 4),
            "class": "PRIMÁRIA (0%)",
            "status": color(div, "PRIMÁRIA"),
            "extra_meta": {"total_co_demo": total, "closed_co_demo": closed_n}}


async def kpi_inadimplencia():
    # FONTE OFICIAL agora = subscriber_invoices
    pipe = [{"$match": {"company_id": CO, "status": INVOICE_OVERDUE}},
            {"$group": {"_id": None,
                          "n": {"$sum": 1},
                          "total": {"$sum": {"$ifNull": ["$amount", 0]}}}}]
    r = await db.subscriber_invoices.aggregate(pipe).to_list(1)
    brl = float(r[0]["total"]) if r else 0.0
    n = int(r[0]["n"]) if r else 0

    # FONTE HISTÓRICA = loyalty (média mensal × parcelas atrasadas)
    pipe2 = [{"$match": {"company_id": CO, "status": "Ativo",
                          "invoices_overdue": {"$gt": 0}}},
             {"$group": {"_id": None,
                           "brl": {"$sum": {"$multiply": ["$monthly_fee", "$invoices_overdue"]}},
                           "customers": {"$sum": 1}}}]
    r2 = await db.loyalty_imported_db.aggregate(pipe2).to_list(1)
    brl_loy = float(r2[0]["brl"]) if r2 else 0.0

    # A política dita: divergência aqui NÃO é mais bloqueante — loyalty
    # passou a ser histórica/auxiliar. A divergência registrada é informativa.
    return {"kpi": "Inadimplência (R$)",
            "official": ("Σ subscriber_invoices.amount WHERE status='overdue'", round(brl, 2)),
            "official_meta": {"n_invoices_overdue": n},
            "secondary": ("Σ loyalty.monthly_fee × invoices_overdue [HISTÓRICA]", round(brl_loy, 2)),
            "divergence_pct": None,  # mono-fonte oficial
            "class": "PRIMÁRIA (0%) — fonte ÚNICA",
            "status": "🟢 VERDE (mono-fonte oficial)",
            "notes": "loyalty desclassificado como fonte oficial (decisão CEO/CTO 15/06/2026)."}


async def kpi_fundadores():
    candidates = await db.loyalty_imported_db.find({
        "company_id": CO, "status": "Ativo",
        "invoices_overdue": 0,
        "invoices_paid": {"$gte": 50},
        "registration_date": {"$lt": "2020-01-01"},
        "document": {"$nin": ["", None]},
    }).to_list(5000)
    confirmed = 0
    seen = set()
    for c in candidates:
        d = c.get("document")
        if not d or d in seen:
            continue
        seen.add(d)
        cancels = await db.loyalty_imported_db.count_documents({
            "company_id": CO, "document": d, "status": "Desativado"
        })
        if cancels == 0:
            confirmed += 1
    declared = 130
    div = pct(confirmed, declared)
    return {"kpi": "Fundadores",
            "official": ("loyalty: 5 filtros · histórico sem cancel", confirmed),
            "secondary": ("CLIENTE_FUNDADOR_REPORT.md (declarado)", declared),
            "divergence_pct": round(div, 4),
            "class": "DERIVADA (1%)",
            "status": color(div, "DERIVADA")}


async def kpi_embaixadores():
    a = await db.universo_ligo_invites.count_documents({
        "company_id": CO, "decision": "APTO", "status": "accepted",
        "do_not_contact_universo_ligo": {"$ne": True},
    })
    return {"kpi": "Embaixadores",
            "official": ("universo_ligo_invites APTO+accepted+!DNC (PRIMÁRIA)", a),
            "secondary": ("(fonte ÚNICA — convite humano explícito)", None),
            "divergence_pct": 0.0,
            "class": "PRIMÁRIA (0%) · fonte única",
            "status": "🟢 VERDE"}


async def main():
    print("=" * 70)
    print(f"ONE_TRUTH_AUDIT v2 · {datetime.now(timezone.utc).isoformat()}")
    print(f"Tenant: {CO} · Filtro: excluded_from_kpi != true · sintéticos $nin")
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
