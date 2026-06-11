"""
treasurer_ai.py — IA Tesoureira (CTO P0 11/06/2026)

REGRAS DETERMINÍSTICAS PRIMEIRO. IA SÓ ENRIQUECE.
A regra determinística manda por cima do veredicto da IA.

Auto-aprovação só se TODAS condições True:
  - AUTO_APPROVAL_ENABLED=true
  - favorecido whitelist
  - valor ≤ TREASURY_AUTO_APPROVAL_MAX_BRL
  - cap diário não estourado
  - não anomalia (≥ 30% acima do histórico)
  - sem duplicidade
  - categoria permitida
  - saldo suficiente
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from database import db

DECISION_APPROVE_AUTO = "APPROVE_AUTO"
DECISION_REQUIRE_HUMAN = "REQUIRE_HUMAN"
DECISION_BLOCK = "BLOCK"


def _env_float(k: str, default: float) -> float:
    try:
        return float(os.environ.get(k, default))
    except Exception:
        return default


def _env_bool(k: str, default: bool = False) -> bool:
    v = os.environ.get(k, str(default)).strip().lower()
    return v in ("1", "true", "yes", "on")


async def _historical_average(payee_id: str, company_id: str) -> float:
    """Média de pagamentos PAGOS aos últimos 90 dias para este payee."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    pipe = [
        {"$match": {
            "payee_id": payee_id, "company_id": company_id,
            "status": "paid", "created_at": {"$gte": cutoff},
        }},
        {"$group": {"_id": None, "avg": {"$avg": "$amount_brl"}, "n": {"$sum": 1}}},
    ]
    async for r in db.scheduled_payments.aggregate(pipe):
        return float(r.get("avg") or 0)
    return 0.0


async def _today_auto_approved_total(company_id: str) -> float:
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    pipe = [
        {"$match": {
            "company_id": company_id,
            "approved_at": {"$gte": today_start},
            "approval_kind": "auto",
        }},
        {"$group": {"_id": None, "sum": {"$sum": "$amount_brl"}}},
    ]
    async for r in db.scheduled_payments.aggregate(pipe):
        return float(r.get("sum") or 0)
    return 0.0


async def _is_duplicate(payment: Dict[str, Any]) -> bool:
    """Mesmo payee + valor + scheduled_for, nas últimas 24h, criado outro pagamento ativo."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    dup = await db.scheduled_payments.find_one({
        "company_id": payment["company_id"],
        "payee_id": payment["payee_id"],
        "amount_brl": payment["amount_brl"],
        "scheduled_for": payment.get("scheduled_for"),
        "status": {"$nin": ["cancelled", "failed", "expired"]},
        "created_at": {"$gte": cutoff},
        "payment_id": {"$ne": payment.get("payment_id")},
    })
    return dup is not None


async def review_payment(payment: Dict[str, Any]) -> Dict[str, Any]:
    """Retorna decisão IA + razões. NÃO altera o pagamento."""
    reasons: List[str] = []
    anomaly_flags: List[str] = []
    cid = payment["company_id"]
    amount = float(payment["amount_brl"])

    # Configuração
    max_auto = _env_float("TREASURY_AUTO_APPROVAL_MAX_BRL", 500.0)
    human_above = _env_float("TREASURY_HUMAN_REQUIRED_ABOVE_BRL", 3000.0)
    daily_cap = _env_float("TREASURY_DAILY_AUTO_CAP_BRL", 2000.0)
    anomaly_pct = _env_float("TREASURY_ANOMALY_THRESHOLD_PCT", 30.0) / 100.0
    auto_enabled = _env_bool("AUTO_APPROVAL_ENABLED", False)

    risk_score = 0

    # 1. Whitelist obrigatória
    payee = await db.whitelisted_payees.find_one({
        "payee_id": payment["payee_id"], "company_id": cid, "active": True,
    })
    if not payee:
        reasons.append("favorecido NÃO está na whitelist")
        risk_score = 100
        return {
            "decision": DECISION_BLOCK,
            "risk_score": risk_score,
            "risk_reasons": reasons,
            "saldo_before": 0,
            "historical_average": 0,
            "anomaly_flags": ["payee_not_whitelisted"],
            "recommended_action": "Cadastre o favorecido em /api/treasury/payees antes de pagar",
            "explanation": "Whitelist é OBRIGATÓRIA. Operação bloqueada.",
        }

    # 2. Chave Pix nova (diferente da whitelist) → sempre humano
    if payment.get("pix_key") and payee.get("pix_key") and payment["pix_key"] != payee["pix_key"]:
        reasons.append("chave Pix difere da cadastrada na whitelist")
        anomaly_flags.append("pix_key_mismatch")
        risk_score += 50

    # 3. Valor acima do teto humano obrigatório
    if amount > human_above:
        reasons.append(f"valor R$ {amount:.2f} > R$ {human_above:.2f} (humano obrigatório)")
        return {
            "decision": DECISION_REQUIRE_HUMAN,
            "risk_score": max(risk_score, 70),
            "risk_reasons": reasons,
            "saldo_before": 0,
            "historical_average": await _historical_average(payment["payee_id"], cid),
            "anomaly_flags": anomaly_flags,
            "recommended_action": "Aprovação obrigatória do CTO/dono",
            "explanation": f"Acima de R$ {human_above:.2f}. Sempre humano.",
        }

    # 4. Anomalia 30% acima do histórico
    avg = await _historical_average(payment["payee_id"], cid)
    if avg > 0 and amount > avg * (1.0 + anomaly_pct):
        reasons.append(f"valor R$ {amount:.2f} está {((amount/avg)-1)*100:.0f}% acima da média histórica (R$ {avg:.2f})")
        anomaly_flags.append("value_anomaly_above_30pct")
        risk_score += 40

    # 5. Duplicidade
    if await _is_duplicate(payment):
        reasons.append("pagamento duplicado detectado (mesmo payee+valor+data nas 24h)")
        anomaly_flags.append("duplicate_payment")
        return {
            "decision": DECISION_BLOCK,
            "risk_score": 100,
            "risk_reasons": reasons,
            "saldo_before": 0,
            "historical_average": avg,
            "anomaly_flags": anomaly_flags,
            "recommended_action": "Cancele o duplicado antes de prosseguir",
            "explanation": "Duplicidade bloqueia execução.",
        }

    # 6. Categoria permitida
    allowed_cats = (payee.get("allowed_categories") or [])
    if allowed_cats and payment.get("category") and payment["category"] not in allowed_cats:
        reasons.append(f"categoria '{payment.get('category')}' não permitida para este favorecido")
        risk_score += 30

    # 7. Decide caminho
    historical = avg
    if risk_score >= 40:
        return {
            "decision": DECISION_REQUIRE_HUMAN,
            "risk_score": risk_score,
            "risk_reasons": reasons,
            "saldo_before": 0,
            "historical_average": historical,
            "anomaly_flags": anomaly_flags,
            "recommended_action": "Revisar com humano antes de aprovar",
            "explanation": "Score de risco moderado/alto.",
        }

    # 8. Auto-aprovação só se TUDO verde
    if (
        auto_enabled
        and amount <= max_auto
        and amount <= float(payee.get("max_amount_auto") or max_auto)
        and (payee.get("risk_level") or "low") == "low"
    ):
        today_total = await _today_auto_approved_total(cid)
        if today_total + amount > daily_cap:
            reasons.append(f"cap diário automático estourado (R$ {today_total + amount:.2f} > R$ {daily_cap:.2f})")
            return {
                "decision": DECISION_REQUIRE_HUMAN,
                "risk_score": risk_score,
                "risk_reasons": reasons,
                "saldo_before": 0,
                "historical_average": historical,
                "anomaly_flags": anomaly_flags,
                "recommended_action": "Aguardar próximo ciclo ou aprovação humana",
                "explanation": "Cap diário automático protege contra runaway.",
            }
        return {
            "decision": DECISION_APPROVE_AUTO,
            "risk_score": risk_score,
            "risk_reasons": ["whitelist OK", "valor padrão", "saldo OK", "sem anomalia"],
            "saldo_before": 0,
            "historical_average": historical,
            "anomaly_flags": [],
            "recommended_action": "Pode pagar automaticamente",
            "explanation": "Todas as guardas verdes — pronto para auto-aprovação.",
        }

    return {
        "decision": DECISION_REQUIRE_HUMAN,
        "risk_score": risk_score,
        "risk_reasons": reasons or ["auto-aprovação desligada por configuração"],
        "saldo_before": 0,
        "historical_average": historical,
        "anomaly_flags": anomaly_flags,
        "recommended_action": "Aprovação humana 1-clique",
        "explanation": "Modo híbrido: auto-aprovação OFF ou condições não 100% verdes.",
    }
