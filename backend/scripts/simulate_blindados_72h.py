"""
simulate_blindados_72h.py — PROVA DE PIPELINE sobre os 72 BLINDADOS REAIS

NÃO ALTERA dados de produção (subscriber_invoices, motor_ia_actions).
Grava em coleção isolada: pilot_simulations.

O que é REAL:
  - Identidade dos 72 clientes (extraída do Mongo, gate SmartOLT aplicado)
  - Telefone canônico (atlaz_clients_cache)
  - Valor da dívida por cliente (soma das overdue invoices)
  - Dias de atraso por cliente

O que é SIMULADO:
  - Resposta do transport WhatsApp (todas "entregues")
  - Conversão de pagamento (curva ISP real por mercado):
      • Atraso 5-15d:  35% conversão  (cliente lembra, paga rápido)
      • Atraso 16-30d: 22% conversão  (resistência média)
      • Atraso 31-60d: 12% conversão  (problemas reais)
      • Atraso >60d:    5% conversão  (alta probabilidade de churn)
  - Latência média até pagamento: amostra de exponencial com média 18h
"""
from __future__ import annotations

import asyncio
import os
import random
import re
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

COMPANY_ID = "co-demo"
SIM_ID = f"sim-blindados-{uuid.uuid4().hex[:10]}"
SEED = 20260608

random.seed(SEED)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


def normalize_phone(raw):
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None
    if len(digits) in (10, 11):
        digits = "55" + digits
    if len(digits) < 12 or len(digits) > 13:
        return None
    return digits


def conversion_rate(days_overdue: int) -> float:
    """Curva de conversão por dias de atraso (referência mercado ISP Brasil)."""
    if days_overdue <= 15:
        return 0.35
    elif days_overdue <= 30:
        return 0.22
    elif days_overdue <= 60:
        return 0.12
    return 0.05


def tier_from_days(days: int) -> str:
    if days <= 15:
        return "ALTO"
    if days <= 30:
        return "MEDIO"
    if days <= 60:
        return "BAIXO"
    return "FRIO"


async def build_blindados_lot():
    from database import db
    gate = await db.motor_ia_predictions.find_one(
        {"kind": "smartolt_gate", "company_id": COMPANY_ID},
        sort=[("generated_at", -1)],
    )
    if not gate:
        raise RuntimeError("rodar gate_smartolt_diagnose.py antes")
    tier_c = {d["external_id"] for d in gate["details"] if d["tier"] == "C_saudavel"}

    overdue = await db.subscriber_invoices.find(
        {"company_id": COMPANY_ID, "status": "overdue"}
    ).to_list(None)
    by_ext = defaultdict(list)
    for inv in overdue:
        if inv.get("subscriber_external_id"):
            by_ext[inv["subscriber_external_id"]].append(inv)

    atlaz = await db.atlaz_clients_cache.find(
        {"company_id": COMPANY_ID, "external_id": {"$in": list(by_ext.keys())}}
    ).to_list(None)
    atlaz_by_ext = {a["external_id"]: a for a in atlaz}

    saps = await db.subscriber_access_points.find(
        {"company_id": COMPANY_ID, "subscriber_external_id": {"$in": list(by_ext.keys())}}
    ).to_list(None)
    sap_by_ext = {s["subscriber_external_id"]: s for s in saps}

    lot = []
    for ext_id in tier_c:
        invs = by_ext.get(ext_id) or []
        atlaz_row = atlaz_by_ext.get(ext_id)
        sap = sap_by_ext.get(ext_id)
        if not invs or not atlaz_row or not sap:
            continue
        phone = normalize_phone(atlaz_row.get("phone"))
        if not phone:
            continue
        amount = sum(float(i.get("amount") or 0) for i in invs)
        oldest = min((i.get("due_date") or "") for i in invs)
        try:
            dias = (
                _now().date() - datetime.strptime(oldest, "%Y-%m-%d").date()
            ).days
        except Exception:
            dias = 0
        lot.append({
            "external_id": ext_id,
            "subscriber_id": sap["subscriber_id"],
            "name": atlaz_row.get("name") or "cliente",
            "phone": phone,
            "amount": round(amount, 2),
            "days_overdue": dias,
            "tier": tier_from_days(dias),
        })
    lot.sort(key=lambda x: -x["amount"])
    return lot


def simulate_message_delivery(lot):
    """Simula entrega: WA real entrega 98% em <30s, 1.5% bounce, 0.5% fail."""
    out = []
    for c in lot:
        r = random.random()
        if r < 0.98:
            status = "delivered"
        elif r < 0.995:
            status = "bounced"
        else:
            status = "failed"
        out.append({**c, "delivery_status": status})
    return out


def simulate_read_and_payment(messages):
    """Para cada delivered: read=85%, payment conforme curva."""
    paid = []
    not_paid = []
    for m in messages:
        if m["delivery_status"] != "delivered":
            not_paid.append({**m, "outcome": "no_delivery"})
            continue
        read = random.random() < 0.85
        if not read:
            not_paid.append({**m, "outcome": "read_no", "read": False})
            continue
        rate = conversion_rate(m["days_overdue"])
        if random.random() < rate:
            latency_h = max(1, int(random.expovariate(1 / 18)))  # exp média 18h
            paid.append({
                **m,
                "outcome": "paid",
                "read": True,
                "paid_in_hours": latency_h,
                "paid_amount": m["amount"],
            })
        else:
            not_paid.append({**m, "outcome": "no_pay", "read": True})
    return paid, not_paid


async def persist(lot, messages, paid, not_paid):
    from database import db
    doc = {
        "id": SIM_ID,
        "company_id": COMPANY_ID,
        "created_at": _iso(_now()),
        "kind": "blindados_72h_simulation",
        "seed": SEED,
        "target_count": len(lot),
        "carteira_BRL": round(sum(c["amount"] for c in lot), 2),
        "delivered": sum(1 for m in messages if m["delivery_status"] == "delivered"),
        "bounced": sum(1 for m in messages if m["delivery_status"] == "bounced"),
        "failed": sum(1 for m in messages if m["delivery_status"] == "failed"),
        "read_count": sum(1 for p in (paid + not_paid) if p.get("read")),
        "payments_count": len(paid),
        "recovered_BRL": round(sum(p["paid_amount"] for p in paid), 2),
        "by_tier": {},
        "lot": lot,
        "paid": paid,
    }
    by_tier = defaultdict(lambda: {"sent": 0, "paid": 0, "recovered_BRL": 0.0})
    for c in lot:
        by_tier[c["tier"]]["sent"] += 1
    for p in paid:
        by_tier[p["tier"]]["paid"] += 1
        by_tier[p["tier"]]["recovered_BRL"] += p["paid_amount"]
    for k in by_tier:
        by_tier[k]["recovered_BRL"] = round(by_tier[k]["recovered_BRL"], 2)
        s = by_tier[k]["sent"]
        by_tier[k]["conversion_pct"] = round(
            (by_tier[k]["paid"] / s * 100) if s else 0, 1
        )
    doc["by_tier"] = dict(by_tier)

    await db.pilot_simulations.insert_one(doc.copy())
    return doc


async def main():
    print("=" * 78)
    print(f"SIMULAÇÃO PIPELINE — 72 BLINDADOS REAIS — sim_id={SIM_ID}")
    print("=" * 78)
    lot = await build_blindados_lot()
    print(f"\n[1] Lote real do banco: {len(lot)} clientes • "
            f"R$ {sum(c['amount'] for c in lot):,.2f}")
    tiers = Counter(c["tier"] for c in lot)
    print(f"    Distribuição por tier: {dict(tiers)}")

    messages = simulate_message_delivery(lot)
    delivered = sum(1 for m in messages if m["delivery_status"] == "delivered")
    bounced = sum(1 for m in messages if m["delivery_status"] == "bounced")
    failed = sum(1 for m in messages if m["delivery_status"] == "failed")
    print(f"\n[2] Entrega WhatsApp (modelo: 98% delivered / 1.5% bounce / 0.5% fail):")
    print(f"    ✅ Entregues:   {delivered}")
    print(f"    🟡 Bounce:      {bounced}")
    print(f"    🔴 Falha:       {failed}")

    paid, not_paid = simulate_read_and_payment(messages)
    read_cnt = sum(1 for p in (paid + not_paid) if p.get("read"))
    print(f"\n[3] Comportamento pós-entrega (modelo: 85% lê, conversão por atraso):")
    print(f"    👁  Lidas:       {read_cnt}/{delivered}")
    print(f"    💰 Pagas:       {len(paid)}")
    print(f"    💵 Recuperado:  R$ {sum(p['paid_amount'] for p in paid):,.2f}")

    doc = await persist(lot, messages, paid, not_paid)

    print(f"\n[4] Resultado por TIER (atraso):")
    print(f"    {'TIER':<8}{'ENVIADAS':>10}{'PAGAS':>8}{'CONV%':>8}{'R$':>12}")
    for tier in ("ALTO", "MEDIO", "BAIXO", "FRIO"):
        row = doc["by_tier"].get(tier)
        if not row:
            continue
        print(f"    {tier:<8}{row['sent']:>10}{row['paid']:>8}"
                f"{row['conversion_pct']:>7.1f}%{row['recovered_BRL']:>12,.2f}")

    carteira = doc["carteira_BRL"]
    recuperado = doc["recovered_BRL"]
    conv_global = round((doc["payments_count"] / doc["target_count"]) * 100, 1)
    roi_pct = round((recuperado / carteira) * 100, 1) if carteira else 0
    print(f"\n[5] CONSOLIDADO:")
    print(f"    Carteira atacada:         R$ {carteira:,.2f}")
    print(f"    Receita recuperada:       R$ {recuperado:,.2f}")
    print(f"    Conversão global:         {conv_global}%")
    print(f"    % da carteira recuperada: {roi_pct}%")
    print(f"    Custo do disparo (72 msgs × R$ 0): R$ 0,00 (Baileys session, sem fee/msg)")
    print(f"    ROI marginal:             ∞ (custo zero)")

    print(f"\n[6] CRITÉRIO OPERAÇÃO TESE:")
    if recuperado >= 10000:
        print(f"    🚀 ESCALAR IMEDIATAMENTE (≥ R$ 10k)")
    elif recuperado >= 3000:
        print(f"    🟢 HIPÓTESE VALIDADA (≥ R$ 3k)")
    elif recuperado >= 500:
        print(f"    🟡 HIPÓTESE PROMISSORA (≥ R$ 500 — abaixo do alvo R$ 3k)")
    else:
        print(f"    🔴 HIPÓTESE NÃO VALIDADA (< R$ 500)")

    print(f"\n[7] AMOSTRA DE PAGAMENTOS SIMULADOS (5 primeiros):")
    for p in paid[:5]:
        print(f"    💰 {p['external_id']:<10} {p['name'][:30]:<30} "
                f"R$ {p['paid_amount']:>7,.2f}  tier={p['tier']:<5} "
                f"pagou em {p['paid_in_hours']}h")

    print(f"\n[OK] Persistido em pilot_simulations: {SIM_ID}")
    print(f"     ⚠️  Coleção isolada. Subscriber_invoices NÃO foi alterada.")


if __name__ == "__main__":
    asyncio.run(main())
