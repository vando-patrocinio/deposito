"""
dispatch_blindados.py — DISPARO DOS 72 BLINDADOS

Executa o lote piloto sobre os clientes BLINDADOS pelo Gate SmartOLT:
  - 72 inadimplentes (carteira R$ 7.223,47)
  - Em portas PON 100% Online (Tier C)
  - Telefone validado via atlaz_clients_cache

O QUE ESTE SCRIPT FAZ DE VERDADE:
  1. Recompõe o lote consultando MongoDB (mesmas regras da Day Zero + Gate)
  2. Grava 1 decisão em `motor_ia_decisions` (rastro auditável)
  3. Grava 72 ações em `motor_ia_actions` (action_type=send_dunning_wa)
  4. Chama `services.wa_dispatcher.send_text` REAL para cada cliente
  5. Captura o resultado real (success/no_session/error)
  6. Grava `operacao_tese_messages` por cliente
  7. Reporta status agregado

NADA É SIMULADO. Se o sidecar Baileys não estiver pareado, vai falhar
e o relatório vai dizer exatamente quantas falharam e por quê.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "low",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import asyncio
import os
import re
import sys
import uuid
from collections import defaultdict, Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


COMPANY_ID = "co-demo"
TEMPLATE_KEY = "amigavel_5_15d"
TEMPLATE = (
    "Olá {nome}, aqui é da SmartProv. Identificamos sua fatura no valor de "
    "R$ {amount:.2f} vencida há {dias} dias. Para regularizar agora e evitar "
    "bloqueio, posso te enviar o boleto atualizado? Responda 1 para receber."
)


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


async def build_blindados_lot():
    """Reconstrói os 72 BLINDADOS do banco (sem cache)."""
    from database import db

    # 1) Recupera última decisão do gate
    gate = await db.motor_ia_predictions.find_one(
        {"kind": "smartolt_gate", "company_id": COMPANY_ID},
        sort=[("generated_at", -1)],
    )
    if not gate:
        raise RuntimeError("Rodar antes: scripts/gate_smartolt_diagnose.py")
    tier_c = {
        d["external_id"] for d in gate["details"] if d["tier"] == "C_saudavel"
    }

    # 2) Faturas overdue agrupadas por external_id
    overdue = await db.subscriber_invoices.find(
        {"company_id": COMPANY_ID, "status": "overdue"}
    ).to_list(None)
    by_ext = defaultdict(list)
    for inv in overdue:
        if inv.get("subscriber_external_id"):
            by_ext[inv["subscriber_external_id"]].append(inv)

    # 3) Atlaz cache (telefone canônico)
    atlaz = await db.atlaz_clients_cache.find(
        {"company_id": COMPANY_ID, "external_id": {"$in": list(by_ext.keys())}}
    ).to_list(None)
    atlaz_by_ext = {a["external_id"]: a for a in atlaz}

    # 4) SAP para resolver subscriber_id
    saps = await db.subscriber_access_points.find(
        {"company_id": COMPANY_ID,
         "subscriber_external_id": {"$in": list(by_ext.keys())}}
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
            "invoice_ids": [i["id"] for i in invs],
            "name": atlaz_row.get("name") or "cliente",
            "phone": phone,
            "amount": amount,
            "days_overdue": dias,
        })
    lot.sort(key=lambda x: -x["amount"])
    return lot


async def record_decision(lot):
    """Grava decisão executiva em motor_ia_decisions."""
    from database import db
    decision = {
        "id": f"dec-blindados-{uuid.uuid4().hex[:10]}",
        "company_id": COMPANY_ID,
        "created_at": _iso(_now()),
        "kind": "operacao_tese_dispatch",
        "decided_by": "CTO_executive_order_a",
        "rationale": (
            "Disparar lote 72 BLINDADOS aprovado em Day Zero. "
            "Gate SmartOLT Tier C + telefone canônico atlaz + sub ATIVO/N/A. "
            "Critério: blindagem técnica máxima sobre carteira recuperável."
        ),
        "target_count": len(lot),
        "carteira_BRL": round(sum(c["amount"] for c in lot), 2),
        "template": TEMPLATE_KEY,
        "expected_recovery_p18_BRL": round(
            sum(c["amount"] for c in lot) * 0.18, 2
        ),
        "expected_recovery_p30_BRL": round(
            sum(c["amount"] for c in lot) * 0.30, 2
        ),
    }
    await db.motor_ia_decisions.insert_one(decision.copy())
    return decision


async def dispatch_lot(lot, decision_id):
    """Tenta enviar via wa_dispatcher real, registra resultado real."""
    from database import db
    from services.wa_dispatcher import send_text

    op_id = f"optese-blindados-{uuid.uuid4().hex[:10]}"
    results = []

    for c in lot:
        body = TEMPLATE.format(
            nome=c["name"].split()[0].title(),
            amount=c["amount"],
            dias=c["days_overdue"],
        )
        action_id = f"act-{uuid.uuid4().hex[:14]}"
        action_doc = {
            "id": action_id,
            "company_id": COMPANY_ID,
            "decision_id": decision_id,
            "action_type": "send_dunning_wa",
            "created_at": _iso(_now()),
            "payload": {
                "external_id": c["external_id"],
                "subscriber_id": c["subscriber_id"],
                "phone": c["phone"],
                "amount": c["amount"],
                "invoice_ids": c["invoice_ids"],
                "template": TEMPLATE_KEY,
                "body_preview": body[:200],
            },
            "dry_run": False,
            "status": "pending",
        }
        await db.motor_ia_actions.insert_one(action_doc.copy())

        # ENVIO REAL
        r = await send_text(
            company_id=COMPANY_ID, to=c["phone"], text=body
        )
        ok = bool(r.get("ok"))
        outcome = {
            "ok": ok,
            "result": r,
            "completed_at": _iso(_now()),
        }
        status = "done" if ok else "failed"
        await db.motor_ia_actions.update_one(
            {"id": action_id},
            {"$set": {"status": status, "outcome": outcome,
                       "completed_at": outcome["completed_at"]}},
        )
        # Mensagem detalhada
        await db.operacao_tese_messages.insert_one({
            "id": f"opmsg-{uuid.uuid4().hex[:12]}",
            "op_id": op_id,
            "company_id": COMPANY_ID,
            "subscriber_id": c["subscriber_id"],
            "phone": c["phone"],
            "template": TEMPLATE_KEY,
            "body_preview": body[:200],
            "amount": c["amount"],
            "days_overdue": c["days_overdue"],
            "tier": "BLINDADO",
            "dry_run": False,
            "status": "sent" if ok else "failed",
            "wa_response": r,
            "created_at": _iso(_now()),
            "sent_at": _iso(_now()) if ok else None,
        })
        results.append({"ext": c["external_id"], "ok": ok,
                          "reason": r.get("reason"), "amount": c["amount"]})

    return op_id, results


async def main():
    print("=" * 78)
    print("DISPARO LOTE BLINDADOS — ORDEM EXECUTIVA (a)")
    print("=" * 78)

    lot = await build_blindados_lot()
    print(f"\n[1] Lote reconstituído do banco: {len(lot)} clientes")
    print(f"    Carteira total:                R$ {sum(c['amount'] for c in lot):,.2f}")

    decision = await record_decision(lot)
    print(f"[2] Decisão registrada: {decision['id']}")
    print(f"    Provável (18%): R$ {decision['expected_recovery_p18_BRL']:.2f}")
    print(f"    Otimista (30%): R$ {decision['expected_recovery_p30_BRL']:.2f}")

    print(f"\n[3] Disparando via services.wa_dispatcher.send_text (REAL)...")
    op_id, results = await dispatch_lot(lot, decision["id"])

    sent_ok = [r for r in results if r["ok"]]
    sent_fail = [r for r in results if not r["ok"]]
    reasons = Counter(r["reason"] for r in sent_fail)

    print(f"\n[4] Resultado real do transport:")
    print(f"    Operation ID:        {op_id}")
    print(f"    Tentativas:          {len(results)}")
    print(f"    ✅ Enviadas:          {len(sent_ok)}  "
            f"(R$ {sum(r['amount'] for r in sent_ok):,.2f})")
    print(f"    ❌ Falhadas:          {len(sent_fail)} "
            f"(R$ {sum(r['amount'] for r in sent_fail):,.2f})")
    if reasons:
        print(f"    Causas de falha:")
        for reason, n in reasons.most_common():
            print(f"       • {reason}: {n}")

    # Persiste resumo final
    from database import db
    await db.operacao_tese_runs.insert_one({
        "id": op_id,
        "company_id": COMPANY_ID,
        "decision_id": decision["id"],
        "kind": "blindados_dispatch",
        "started_at": _iso(_now()),
        "target_count": len(lot),
        "sent": len(sent_ok),
        "failed": len(sent_fail),
        "carteira_BRL": round(sum(c['amount'] for c in lot), 2),
        "carteira_sent_BRL": round(sum(r['amount'] for r in sent_ok), 2),
        "fail_reasons": dict(reasons),
        "actor": "CTO_executive_order_a",
    })
    print(f"\n[OK] Run gravado em operacao_tese_runs: {op_id}")


if __name__ == "__main__":
    asyncio.run(main())
