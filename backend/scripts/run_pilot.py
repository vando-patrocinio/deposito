"""
run_pilot.py — Script CLI executado pelo OPERADOR HUMANO em produção.

Pré-requisitos (FORA deste script):
  1. Baileys conectado (sessão `wa_baileys_sessions.status="open"`)
  2. .env contém PRESIDENTE_IA_GESTOR_PHONE=+55...
  3. Empresa piloto identificada (company_id real)
  4. Aprovação executiva (Slack/email)

Uso:
  cd /app/backend
  # 1) Confere checklist
  python scripts/run_pilot.py preflight --company COMPANY_ID
  # 2) Inicia piloto LIVE
  python scripts/run_pilot.py start --company COMPANY_ID --max 10
  # 3) Monitora (rodar a cada 6h)
  python scripts/run_pilot.py monitor --op OP_ID
  # 4) Após 72h
  python scripts/run_pilot.py final --op OP_ID
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def cmd_preflight(company_id: str):
    from services.operacao_tese import pre_flight_check
    r = await pre_flight_check(company_id)
    print("═══ PRE-FLIGHT ═══")
    for c in r["checks"]:
        icon = "✅" if c["ok"] else "🔴"
        print(f"  {icon} {c['check']:35s} {c['detail']}")
    print()
    print(f"  Blockers: {r['blocking_count']}")
    print(f"  OK to start: {r['ok_to_start']}")
    return r


async def cmd_start(company_id: str, max_messages: int):
    from services.operacao_tese import start_operation
    print(f"═══ START LIVE — {company_id} (max {max_messages} msgs) ═══")
    r = await start_operation(
        company_id=company_id,
        dry_run=False,
        max_messages=max_messages,
        started_by="cli_pilot")
    if r.get("error"):
        print(f"ABORTADO: {r['error']}")
        if r.get("pre_flight"):
            print(f"Blockers: {r['pre_flight']['blockers']}")
        return r
    print(f"  Operation ID: {r['operation_id']}")
    print(f"  Eligíveis (pós SmartOLT): {r['eligible_after_smartolt']}")
    print(f"  Bloqueados SmartOLT: {r['blocked_by_smartolt']}")
    print(f"  Mensagens enviadas: {r['messages_sent_or_planned']}")
    print(f"  Por tier: {r['summary_by_tier']}")
    print()
    print(f"  ▶ Próximo passo: aguardar 6h, rodar:")
    print(f"     python scripts/run_pilot.py monitor --op {r['operation_id']}")
    return r


async def cmd_monitor(op_id: str):
    from services.operacao_tese import monitor_panel
    r = await monitor_panel(op_id)
    print(f"═══ MONITOR — {op_id} ═══")
    print(json.dumps(r, indent=2, default=str, ensure_ascii=False))
    return r


async def cmd_final(op_id: str):
    from services.operacao_tese import (
        daily_report, success_criteria, stop_operation,
    )
    print(f"═══ RELATÓRIO FINAL — {op_id} ═══")
    rep = await daily_report(op_id)
    print(json.dumps(rep, indent=2, default=str, ensure_ascii=False))
    print()
    print("═══ VEREDITO ═══")
    suc = await success_criteria(op_id)
    recovered = suc["metrics"]["recovered_BRL"] or 0
    print(f"  R$ recuperados: R$ {recovered:.2f}")
    print(f"  Presidente IA recuperou sozinho? "
            f"{suc['presidente_ia_recovered_alone']}")
    print()
    if recovered >= 10000:
        print("  🚀 HIPÓTESE VALIDADA + ESCALAR IMEDIATAMENTE.")
        print("  Próximo: ativar 3-5 empresas em paralelo.")
    elif recovered >= 3000:
        print("  🟢 HIPÓTESE VALIDADA.")
        print("  Próximo: dobrar max_messages, manter monitoramento.")
    elif recovered >= 500:
        print("  🟡 HIPÓTESE PROMISSORA.")
        print("  Próximo: ajustar templates via learn_from_payments.")
    else:
        print("  🔴 HIPÓTESE NÃO VALIDADA NESTA AMOSTRA.")
        print("  Próximo: revisar tom + critério antes de continuar.")
    # opcional: stop
    print()
    print(f"  Para encerrar:")
    print(f"  curl -X POST $API/api/operacao-tese/stop/{op_id} "
            f"-H 'Authorization: Bearer ...'")


async def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("preflight")
    p1.add_argument("--company", required=True)
    p2 = sub.add_parser("start")
    p2.add_argument("--company", required=True)
    p2.add_argument("--max", type=int, default=10)
    p3 = sub.add_parser("monitor")
    p3.add_argument("--op", required=True)
    p4 = sub.add_parser("final")
    p4.add_argument("--op", required=True)
    args = ap.parse_args()
    if args.cmd == "preflight":
        await cmd_preflight(args.company)
    elif args.cmd == "start":
        await cmd_start(args.company, args.max)
    elif args.cmd == "monitor":
        await cmd_monitor(args.op)
    elif args.cmd == "final":
        await cmd_final(args.op)


if __name__ == "__main__":
    asyncio.run(main())
