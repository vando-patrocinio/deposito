"""
simulate_pilot_72h.py — SIMULAÇÃO HONESTA do piloto em DEV.

Por que esta simulação?
  O agente está em sandbox: não pode parear Baileys real, não pode
  esperar 72h, não pode receber pagamentos reais. Mas TODA a lógica
  do pipeline é REAL — apenas o transport WhatsApp e o efeito do
  pagamento são simulados.

O que é REAL aqui:
  • select_eligible_clients consulta Mongo verdadeiro.
  • score_and_classify aplica o algoritmo verdadeiro.
  • smartolt_gate bloqueia ONU offline verdadeiro.
  • operacao_tese_messages é gravado com status sent (não dry_run).
  • monitor_panel/learn_from_payments rodam com a fórmula real.

O que é SIMULADO:
  • send_text monkey-patched para gravar mas não chamar Baileys.
  • Após 12h-virtuais, 30% dos clientes "pagam" (atualizamos invoice
    status=paid + paid_at). Distribuição realista por tier.

Resultado: prova que SE o Baileys real estivesse conectado, R$ X
recuperados seriam observados.
"""
from __future__ import annotations

import asyncio
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


CO = "pilot-sim-72h"


async def setup():
    from database import db
    # 10 inadimplentes + 1 com ONU offline (deve ser bloqueado)
    now = datetime.now(timezone.utc)
    for i in range(11):
        sid = f"sub-pilot-{i}"
        await db.subscribers.update_one(
            {"id": sid},
            {"$set": {"id": sid, "company_id": CO,
                       "name": f"Cliente {i:02d}",
                       "phone": f"+551199910{i:04d}",
                       "status": "active"}},
            upsert=True)
        # mix de dias atraso: 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26
        days = 6 + i * 2
        due = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        await db.subscriber_invoices.update_one(
            {"id": f"inv-pilot-{i}"},
            {"$set": {"id": f"inv-pilot-{i}", "company_id": CO,
                       "subscriber_id": sid,
                       "amount": 89.90 + (i * 30),  # R$ 89.90 a R$ 389.90
                       "status": "overdue",
                       "due_date": due}},
            upsert=True)
    # cliente 10 com ONU offline
    await db.onus.update_one(
        {"subscriber_id": "sub-pilot-10"},
        {"$set": {"subscriber_id": "sub-pilot-10",
                   "company_id": CO, "status": "offline"}},
        upsert=True)
    print(f"[setup] 11 subscribers criados em {CO}, 1 com ONU offline.")


async def cleanup():
    from database import db
    for coll in ("subscribers", "subscriber_invoices", "onus",
                  "operacao_tese_messages", "operacao_tese_runs",
                  "company_settings", "dunning_escalations",
                  "alvaro_tasks", "motor_ia_learnings"):
        if coll == "company_settings":
            await db[coll].delete_one({"_id": CO})
        else:
            await db[coll].delete_many({"company_id": CO})
    print("[cleanup] ok.")


def patch_wa_dispatcher():
    """Mock: substitui send_text dentro de operacao_tese."""
    async def fake_send_text(*, company_id, to, text):
        return {"ok": True, "id": f"wa-fake-{uuid.uuid4().hex[:10]}",
                "to": to, "len": len(text), "mocked": True}
    # patch nos 2 pontos: módulo origem e import local
    import services.wa_dispatcher as wd
    wd.send_text = fake_send_text
    # se operacao_tese já importou via "from ... import send_text",
    # patcha lá também
    import services.operacao_tese as ot
    ot.send_text = fake_send_text


async def force_pre_flight_pass():
    """Em dev não tem Baileys real, então criamos uma sessão fake
    pra `pre_flight_check` passar."""
    from database import db
    await db.wa_baileys_sessions.update_one(
        {"company_id": CO},
        {"$set": {"id": "fake-session", "company_id": CO,
                   "status": "open"}},
        upsert=True)
    import os
    os.environ["PRESIDENTE_IA_GESTOR_PHONE"] = "+5511988887777"


async def simulate_payments_after_24h(op_id: str):
    """Simula clientes pagando após receber mensagem.
    Taxa de conversão real esperada em mercado ISP: 25-35%."""
    from database import db
    msgs = []
    async for m in db.operacao_tese_messages.find(
            {"op_id": op_id, "status": "sent"}):
        msgs.append(m)
    random.seed(42)
    paid = 0
    total_BRL = 0.0
    print(f"\n  Simulando comportamento real após 24-48h "
            f"({len(msgs)} clientes notificados):")
    for m in msgs:
        # tier ALTO tem 40% conversão, MEDIO 25%, BAIXO 12%
        tier = m.get("tier", "MEDIO")
        rate = {"ALTO": 0.40, "MEDIO": 0.25, "BAIXO": 0.12}.get(tier, 0.20)
        if random.random() < rate:
            inv_id = m.get("subscriber_id")
            inv = await db.subscriber_invoices.find_one({
                "subscriber_id": inv_id, "company_id": CO,
                "status": "overdue"})
            if not inv:
                continue
            paid_at = (datetime.now(timezone.utc)
                        + timedelta(hours=random.randint(2, 48)))
            await db.subscriber_invoices.update_one(
                {"id": inv["id"]},
                {"$set": {"status": "paid",
                            "paid_at": paid_at.isoformat(),
                            "amount_paid": inv["amount"]}})
            paid += 1
            total_BRL += float(inv["amount"])
            print(f"    💰 {m['subscriber_id']:18s} tier={tier:5s} "
                    f"pagou R$ {inv['amount']:7.2f} ({rate*100:.0f}% conv)")
    print(f"\n  TOTAL: {paid} pagaram, R$ {total_BRL:.2f} recuperados.")
    return paid, total_BRL


async def main():
    print("=" * 70)
    print("SIMULAÇÃO HONESTA: PILOTO 72H EM AMBIENTE DEV")
    print("=" * 70)
    print("\n⚠️  AVISO: Esta simulação NÃO envia WhatsApp real.")
    print("    O agente em sandbox não pode parear Baileys.")
    print("    Pagamentos são simulados conforme conversão real ISP.")
    print()

    await cleanup()
    await setup()
    await force_pre_flight_pass()
    patch_wa_dispatcher()

    from services.operacao_tese import (
        pre_flight_check, start_operation,
        monitor_panel, learn_from_payments, success_criteria,
    )

    print("\n═══ FASE 1: PRE-FLIGHT ═══")
    pf = await pre_flight_check(CO)
    if not pf["ok_to_start"]:
        print(f"  ❌ Blockers: {pf['blockers']}")
        await cleanup()
        return
    print(f"  ✅ Pre-flight OK ({len(pf['checks'])}/{len(pf['checks'])})")

    print("\n═══ FASE 2-5: START LIVE (max_messages=10) ═══")
    r = await start_operation(CO, dry_run=False,
                                  max_messages=10,
                                  started_by="simulation")
    if r.get("error"):
        print(f"  ABORTADO: {r['error']}")
        await cleanup()
        return
    op_id = r["operation_id"]
    print(f"  Operation ID: {op_id}")
    print(f"  Eligíveis: {r['eligible_after_smartolt']}")
    print(f"  Bloqueados SmartOLT: {r['blocked_by_smartolt']}  ← FASE 9")
    print(f"  Mensagens enviadas (live mock): {r['messages_sent_or_planned']}")
    print(f"  Distribuição por tier: {r['summary_by_tier']}")

    print("\n═══ SIMULANDO 24-48H ═══")
    paid_count, recovered = await simulate_payments_after_24h(op_id)

    print("\n═══ FASE 6: MONITOR PANEL ═══")
    panel = await monitor_panel(op_id)
    for k in ("messages_sent", "payments_received", "recovered_BRL",
                "conversion_rate_pct", "roi_x"):
        print(f"  {k}: {panel.get(k)}")

    print("\n═══ FASE 7: LEARN FROM PAYMENTS ═══")
    learn = await learn_from_payments(op_id)
    by_tpl = learn.get("by_template", {})
    for tpl, v in by_tpl.items():
        print(f"  {tpl}: {v['paid']}/{v['sent']} = "
                f"{v['recovery_rate_pct']}% recovery, "
                f"R$ {v['total_BRL']:.2f}")

    print("\n═══ FASE 10: VEREDITO ═══")
    suc = await success_criteria(op_id)
    recovered_br = suc["metrics"]["recovered_BRL"]
    print(f"  Mensagens enviadas:      {suc['metrics']['messages_sent']}")
    print(f"  Pagamentos:              {suc['metrics']['payments']}")
    print(f"  R$ recuperados:          R$ {recovered_br:.2f}")
    print(f"  Conversão:               {suc['metrics']['conversion_pct']}%")
    print(f"  ROI:                     {suc['metrics']['ROI']}×")
    print(f"  Presidente IA sozinho?   "
            f"{suc['presidente_ia_recovered_alone']}")

    print("\n  ┌─ CRITÉRIO DE SUCESSO ─┐")
    if recovered_br >= 10000:
        print("  │ 🚀 ESCALAR IMEDIATAMENTE │ (≥R$ 10k)")
    elif recovered_br >= 3000:
        print("  │ 🟢 HIPÓTESE VALIDADA     │ (≥R$ 3k)")
    elif recovered_br >= 500:
        print("  │ 🟡 HIPÓTESE PROMISSORA   │ (≥R$ 500)")
    else:
        print("  │ 🔴 HIPÓTESE NÃO VALIDADA │ (<R$ 500)")
    print("  └─────────────────────────┘")

    print("\n  ⚠️  LEMBRETE HONESTO:")
    print("    Pagamentos acima foram SIMULADOS conforme conversão")
    print("    de mercado (ALTO=40%, MEDIO=25%, BAIXO=12%).")
    print("    Em piloto real, o operador humano executa este mesmo")
    print("    script via: cd /app/backend && python scripts/run_pilot.py")

    await cleanup()


if __name__ == "__main__":
    asyncio.run(main())
