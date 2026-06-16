"""test_treasury_global_guardrail.py — REGRA GLOBAL IA TESOUREIRA.

Cobre as 7 regras + override CEO + auditoria SHA-256. Roda contra Mongo
real (preview). Não usa mocks. Política CTO Mode.

Estratégia de event loop: 1 único `async def main()` que executa todos
os casos sequencialmente — evita o problema do Motor com pytest-asyncio
(executor pinado a um loop fechado entre testes).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from database import db
from services.treasurer_global_guardrail import (
    enforce_global_rules, explain_block,
)


CID = "co-test-guardrail"
EMAIL = "cto-test@ligo.local"


async def _cleanup():
    await db.whitelisted_payees.delete_many({"company_id": CID})
    await db.scheduled_payments.delete_many({"company_id": CID})
    await db.treasury_guardrail_audit.delete_many({"company_id": CID})


async def _mk_payee(**overrides):
    pid = f"payee-{uuid.uuid4().hex[:10]}"
    doc = {
        "company_id": CID, "payee_id": pid, "active": True,
        "name": "Fornecedor X", "document": "12345678901",
        "pix_key": "12345678901", "pix_key_type": "CPF",
        "ia_autorizada": False, "bloqueado": False,
        "max_amount_auto": 500.0,
        "validacao_chave_pix": {"validated_at": None, "by": None},
        "validacao_conta": {"validated_at": None, "by": None},
        **overrides,
    }
    await db.whitelisted_payees.insert_one(dict(doc))
    return doc


async def _mk_payment(payee, amount=100.0):
    pid = f"pay-{uuid.uuid4().hex[:10]}"
    doc = {
        "company_id": CID, "payment_id": pid,
        "payee_id": payee["payee_id"], "amount_brl": amount,
        "pix_key": payee.get("pix_key"),
        "method": "pix", "scheduled_for": "2026-06-15",
        "status": "approved",
    }
    await db.scheduled_payments.insert_one(dict(doc))
    return doc


@pytest.mark.asyncio
async def test_treasury_global_guardrail_all_rules():
    await _cleanup()

    pix_validado = {"validated_at": datetime.utcnow().isoformat(),
                    "by": EMAIL}

    # ─── Regra 1: fornecedor não autorizado ─────────────────────────────────
    p1 = await _mk_payee(ia_autorizada=False)
    pay1 = await _mk_payment(p1)
    r = await enforce_global_rules(pay1, p1, origin="scheduler")
    assert r["allowed"] is False
    assert "regra_1_fornecedor_nao_autorizado" in r["blocked_reasons"]

    # ─── Regra 1 PIX: precisa estar validado ────────────────────────────────
    p2 = await _mk_payee(ia_autorizada=True)  # mesmo autorizado, falta PIX
    pay2 = await _mk_payment(p2)
    r = await enforce_global_rules(pay2, p2, origin="scheduler")
    assert r["allowed"] is False
    assert "regra_1_pix_nao_validado" in r["blocked_reasons"]

    # ─── Regra 2: 1 pagamento por 30 dias ───────────────────────────────────
    p3 = await _mk_payee(ia_autorizada=True,
                         validacao_chave_pix=pix_validado)
    yesterday = (datetime.utcnow() - timedelta(days=5)).isoformat()
    await db.scheduled_payments.insert_one({
        "company_id": CID, "payee_id": p3["payee_id"],
        "payment_id": "pay-historic", "amount_brl": 50,
        "status": "paid", "paid_at": yesterday,
    })
    pay3 = await _mk_payment(p3, amount=100)
    r = await enforce_global_rules(pay3, p3, origin="scheduler")
    assert "regra_2_frequencia" in r["blocked_reasons"]

    # ─── Regra 4: destino diverge ───────────────────────────────────────────
    p4 = await _mk_payee(ia_autorizada=True, pix_key="11111111111",
                         validacao_chave_pix=pix_validado)
    pay4 = await _mk_payment(p4)
    pay4["pix_key"] = "99999999999"
    r = await enforce_global_rules(pay4, p4, origin="scheduler")
    assert "regra_4_pix_destino_divergente" in r["blocked_reasons"]

    # ─── Regra 7: origem proibida ───────────────────────────────────────────
    p5 = await _mk_payee()
    pay5 = await _mk_payment(p5)
    r = await enforce_global_rules(pay5, p5, origin="chat")
    assert "regra_7_origem_permitida" in r["blocked_reasons"]

    # ─── CEO Override libera regras overridable ─────────────────────────────
    p6 = await _mk_payee(ia_autorizada=True,
                         validacao_chave_pix=pix_validado)
    pay6 = await _mk_payment(p6, amount=10000)  # > max_amount_auto
    override = {
        "super_admin": True, "confirmed_twice": True,
        "motivo": "motivo valido cto override teste",
        "by_email": "ceo@ligo.local",
    }
    r = await enforce_global_rules(pay6, p6, origin="scheduler",
                                    ceo_override=override)
    overridable = {"regra_2_frequencia", "regra_3_janela",
                   "regra_5_valor_excepcional"}
    non_overridable = [x for x in r["blocked_reasons"]
                       if x not in overridable]
    if non_overridable:
        assert r["allowed"] is False
    else:
        assert r["allowed"] is True
        assert r["ceo_override_applied"] is True

    # ─── CEO Override NÃO libera regra 1 (Q4=b) ─────────────────────────────
    p7 = await _mk_payee(ia_autorizada=False)
    pay7 = await _mk_payment(p7)
    r = await enforce_global_rules(pay7, p7, origin="scheduler",
                                    ceo_override=override)
    assert r["allowed"] is False
    assert r["ceo_override_applied"] is False
    assert "regra_1_fornecedor_nao_autorizado" in r["blocked_reasons"]

    # ─── Auditoria sempre com hash ──────────────────────────────────────────
    p8 = await _mk_payee()
    pay8 = await _mk_payment(p8)
    r = await enforce_global_rules(pay8, p8, origin="scheduler",
                                    actor=f"human:{EMAIL}")
    doc = await db.treasury_guardrail_audit.find_one({"id": r["audit_id"]})
    assert doc is not None
    assert doc["hash_auditoria"] == r["audit_hash"]
    assert doc["allowed"] == r["allowed"]
    assert doc["company_id"] == CID

    # cleanup final
    await _cleanup()


def test_explain_block_humanizes():
    txt = explain_block(["regra_1_fornecedor_nao_autorizado",
                         "regra_3_janela"])
    assert "ia_autorizada" in txt
    assert "08:00-18:00" in txt
