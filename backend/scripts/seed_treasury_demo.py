"""
seed_treasury_demo.py — Popula dados-demo da IA Tesoureira no co-demo
para o CTO validar via UI. Idempotente (limpa antes de criar).
Run: cd /app/backend && python3 scripts/seed_treasury_demo.py
"""
import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app/backend")

from database import db

CID = "co-demo"
NOW = datetime.now(timezone.utc)


def iso(d=None):
    return (d or NOW).isoformat()


def date_str(offset_days=0):
    return (NOW + timedelta(days=offset_days)).date().isoformat()


async def main():
    print(f"[seed] target company_id={CID}")
    # Limpeza
    for col in ("whitelisted_payees", "scheduled_payments",
                "treasurer_ai_decisions", "payment_audit_logs"):
        n = await db[col].delete_many({"company_id": CID})
        print(f"  cleaned {col}: {n.deleted_count}")

    # ── Favorecidos ─────────────────────────────
    payees = [
        {
            "payee_id": "payee-fornec-fibras",
            "name": "Fornecedora Fibras Ópticas LTDA",
            "document": "12.345.678/0001-90",
            "pix_key": "12345678000190",
            "pix_key_type": "CNPJ",
            "category": "infraestrutura",
            "max_amount_auto": 1500,
            "risk_level": "low",
        },
        {
            "payee_id": "payee-energia-light",
            "name": "Light Energia S.A.",
            "document": "60.444.437/0001-46",
            "pix_key": "energia@light.com.br",
            "pix_key_type": "EMAIL",
            "category": "utilities",
            "max_amount_auto": 800,
            "risk_level": "low",
        },
        {
            "payee_id": "payee-colab-joao",
            "name": "João Técnico de Campo",
            "document": "123.456.789-00",
            "pix_key": "12345678900",
            "pix_key_type": "CPF",
            "category": "salario",
            "max_amount_auto": 500,
            "risk_level": "low",
        },
    ]
    for p in payees:
        await db.whitelisted_payees.insert_one({
            "company_id": CID, "active": True, "allowed_methods": ["PIX"],
            "allowed_categories": [p["category"]],
            "created_at": iso(NOW - timedelta(days=30)),
            "created_by": "seed",
            **p,
        })
    print(f"  + {len(payees)} payees")

    # ── Pagamentos ────────────────────────────────
    payments = [
        # 1) Aprovado e PAGO hoje (histórico)
        dict(
            payee=payees[1], amount=580.00, scheduled=date_str(-1),
            status="paid", category="utilities",
            description="Conta de luz POP Central — Nov/2025",
            ai_decision="APPROVE_AUTO", ai_risk=15, approval_kind="auto",
            paid=True,
        ),
        # 2) PENDING_HUMAN_APPROVAL — valor > limite auto
        dict(
            payee=payees[0], amount=1850.00, scheduled=date_str(2),
            status="pending_human_approval", category="infraestrutura",
            description="Compra de 500m cabo fibra drop CFOA-SM",
            ai_decision="REQUIRE_HUMAN", ai_risk=45,
        ),
        # 3) APPROVED aguardando envio
        dict(
            payee=payees[2], amount=480.00, scheduled=date_str(1),
            status="approved", category="salario",
            description="Ajuda de custo deslocamento — João",
            ai_decision="APPROVE_AUTO", ai_risk=20, approval_kind="auto",
        ),
        # 4) BLOCKED — payee fora whitelist (simulado: forçamos bloqueio)
        dict(
            payee={"payee_id": "payee-suspeito-xyz",
                   "name": "Empresa Desconhecida ME",
                   "document": "00.000.000/0001-00",
                   "pix_key": "suspeito@x.com", "pix_key_type": "EMAIL",
                   "category": "outros"},
            amount=2400.00, scheduled=date_str(3),
            status="blocked_risk", category="outros",
            description="Fatura sem nota — favorecido não whitelist",
            ai_decision="BLOCK", ai_risk=92,
            risk_reasons=["payee_not_whitelisted", "amount_above_avg_30pct"],
        ),
        # 5) PENDING — anomalia >30% do histórico
        dict(
            payee=payees[1], amount=1100.00, scheduled=date_str(4),
            status="pending_human_approval", category="utilities",
            description="Conta de luz POP Central — Dez/2025 (alta)",
            ai_decision="REQUIRE_HUMAN", ai_risk=58,
            risk_reasons=["amount_above_avg_30pct"],
        ),
        # 6) DRAFT — aguarda AI Review
        dict(
            payee=payees[0], amount=320.00, scheduled=date_str(7),
            status="draft", category="infraestrutura",
            description="Conectores SC/UPC + protetor de emenda",
        ),
        # 7) FAILED — envio Asaas falhou
        dict(
            payee=payees[2], amount=150.00, scheduled=date_str(-2),
            status="failed", category="salario",
            description="Ajuda combustível",
            ai_decision="APPROVE_AUTO", ai_risk=10, approval_kind="auto",
            last_error={"ok": False, "error": "asaas_auth_error",
                        "message": "API Key inválida (sandbox sem chave configurada)"},
        ),
        # 8) APPROVED valor alto — exige super_admin (>R$3000)
        dict(
            payee=payees[0], amount=4200.00, scheduled=date_str(5),
            status="pending_human_approval", category="infraestrutura",
            description="OLT Huawei MA5800 — entrada (parcial)",
            ai_decision="REQUIRE_HUMAN", ai_risk=70,
            risk_reasons=["amount_above_human_required_threshold"],
        ),
    ]

    for i, pay in enumerate(payments):
        pid = f"pay-demo-{uuid.uuid4().hex[:10]}"
        payee = pay["payee"]
        created_at = iso(NOW - timedelta(hours=24 - i))
        doc = {
            "company_id": CID, "payment_id": pid,
            "payee_id": payee["payee_id"], "payee_name": payee["name"],
            "payee_document": payee["document"],
            "pix_key": payee["pix_key"], "pix_key_type": payee["pix_key_type"],
            "amount_brl": pay["amount"], "scheduled_for": pay["scheduled"],
            "category": pay["category"], "description": pay["description"],
            "provider": "asaas", "provider_transfer_id": None,
            "status": pay["status"],
            "created_by": "seed", "created_at": created_at,
            "updated_at": iso(NOW - timedelta(hours=23 - i)),
        }
        if pay.get("ai_decision"):
            doc["ai_decision"] = pay["ai_decision"]
            doc["ai_risk_score"] = pay["ai_risk"]
        if pay.get("approval_kind"):
            doc["approval_kind"] = pay["approval_kind"]
            doc["approved_at"] = iso(NOW - timedelta(hours=22 - i))
            doc["approved_by"] = "treasurer-ai" if pay["approval_kind"] == "auto" else "admin@empresa.com"
        if pay.get("paid"):
            doc["sent_at"] = iso(NOW - timedelta(hours=12))
            doc["paid_at"] = iso(NOW - timedelta(hours=4))
            doc["provider_transfer_id"] = f"asaas-trf-{uuid.uuid4().hex[:10]}"
        if pay.get("last_error"):
            doc["last_error"] = pay["last_error"]
        await db.scheduled_payments.insert_one(doc)

        # AI decision row
        if pay.get("ai_decision"):
            await db.treasurer_ai_decisions.insert_one({
                "id": f"aidec-{uuid.uuid4().hex[:12]}",
                "company_id": CID, "payment_id": pid,
                "decision": pay["ai_decision"],
                "risk_score": pay["ai_risk"],
                "risk_reasons": pay.get("risk_reasons", []),
                "saldo_before": 12450.00,
                "historical_average": 620.00 if payee["category"] == "utilities" else 1240.00,
                "anomaly_flags": pay.get("risk_reasons", []),
                "recommended_action": pay["ai_decision"],
                "explanation": {
                    "APPROVE_AUTO": "Favorecido whitelist, valor dentro do limite, sem anomalia.",
                    "REQUIRE_HUMAN": "Valor acima do limite de auto-aprovação OU anomalia detectada — exige aprovação humana.",
                    "BLOCK": "Risco crítico: favorecido fora da whitelist e valor acima de R$ 2000.",
                }[pay["ai_decision"]],
                "created_at": iso(NOW - timedelta(hours=23 - i)),
            })

        # Audit timeline
        await db.payment_audit_logs.insert_one({
            "id": f"aud-{uuid.uuid4().hex[:14]}", "company_id": CID,
            "payment_id": pid, "action": "payment_created",
            "actor": "seed", "created_at": created_at,
            "amount_brl": pay["amount"],
        })
        if pay.get("ai_decision"):
            await db.payment_audit_logs.insert_one({
                "id": f"aud-{uuid.uuid4().hex[:14]}", "company_id": CID,
                "payment_id": pid, "action": f"ai_review:{pay['ai_decision']}",
                "actor": "treasurer-ai",
                "created_at": iso(NOW - timedelta(hours=23 - i)),
                "risk_score": pay["ai_risk"],
            })
        if pay.get("approval_kind"):
            await db.payment_audit_logs.insert_one({
                "id": f"aud-{uuid.uuid4().hex[:14]}", "company_id": CID,
                "payment_id": pid,
                "action": f"payment_approved_{pay['approval_kind']}",
                "actor": doc["approved_by"],
                "created_at": doc["approved_at"],
            })
        if pay.get("paid"):
            await db.payment_audit_logs.insert_one({
                "id": f"aud-{uuid.uuid4().hex[:14]}", "company_id": CID,
                "payment_id": pid, "action": "payment_sent",
                "actor": "admin@empresa.com", "created_at": doc["sent_at"],
                "transfer_id": doc["provider_transfer_id"],
            })
            await db.payment_audit_logs.insert_one({
                "id": f"aud-{uuid.uuid4().hex[:14]}", "company_id": CID,
                "payment_id": pid, "action": "webhook:TRANSFER_DONE",
                "actor": "asaas-webhook", "created_at": doc["paid_at"],
            })
        if pay.get("last_error"):
            await db.payment_audit_logs.insert_one({
                "id": f"aud-{uuid.uuid4().hex[:14]}", "company_id": CID,
                "payment_id": pid, "action": "payment_send_failed",
                "actor": "admin@empresa.com",
                "created_at": iso(NOW - timedelta(hours=10)),
                "error": pay["last_error"],
            })

    print(f"  + {len(payments)} payments + audit + decisions seeded")
    print("[seed] DONE")


if __name__ == "__main__":
    asyncio.run(main())
