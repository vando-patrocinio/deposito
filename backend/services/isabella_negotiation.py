"""isabella_negotiation.py — Guardrails de negociação Isabella (P0 CTO 2026-02).

PROBLEMA: sem trava, qualquer cliente que pedir "desconto", "promessa de pagamento"
ou "parcelamento" via WhatsApp pode receber resposta inventada pela IA. Risco
financeiro direto (descontos não aprovados) + risco regulatório (BACEN/PROCON).

POLÍTICA (failsafe por design):
  - Toda regra default = DESLIGADA. Só com toggle explícito do gestor a IA
    pode prometer algo. Caso contrário, sempre `handoff_to_human`.
  - Tudo registrado em `negotiation_attempts` (audit log append-only).
  - Limites enforced em código (não dá pra burlar via prompt).

Coleções:
  - `negotiation_rules` (1 doc por tenant)
  - `negotiation_attempts` (audit log de cada decisão `can_offer`)
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["negotiation.allowed", "negotiation.blocked",
                    "negotiation.handoff"],
    "company_id_required": True,
}

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database import db

log = logging.getLogger("ponto.isabella_negotiation")

# Ações negociáveis canônicas
ACTION_PROMISE = "promise_payment"
ACTION_DISCOUNT = "discount"
ACTION_SECOND_INVOICE = "second_invoice"
ACTION_INSTALLMENT = "installment"

CANONICAL_ACTIONS = {
    ACTION_PROMISE, ACTION_DISCOUNT, ACTION_SECOND_INVOICE, ACTION_INSTALLMENT,
}

# Default failsafe — tudo OFF. Gestor liga manualmente no painel.
DEFAULT_RULES: Dict[str, Any] = {
    "promise_payment": {
        "enabled": False,
        "max_dias_extensao": 7,
        "max_promessas_por_ano": 2,
        "requer_status_ativo": True,
    },
    "discount": {
        "enabled": False,
        "max_pct": 15.0,
        "max_brl": 100.0,
        "requer_aprovacao_humana_acima_de_brl": 100.0,
    },
    "second_invoice": {
        "enabled": False,
        "canal_default": "whatsapp",  # whatsapp | email | pix_inline
        "max_por_mes": 3,
    },
    "installment": {
        "enabled": False,
        "max_parcelas": 3,
        "juros_pct": 0.0,
        "requer_aprovacao_humana": True,
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_rules(company_id: str) -> Dict[str, Any]:
    """Retorna regras do tenant. Cria default OFF se não existir."""
    doc = await db.negotiation_rules.find_one(
        {"company_id": company_id}, {"_id": 0})
    if doc:
        # Garante todas as chaves presentes (compat ao adicionar novas regras)
        for k, default in DEFAULT_RULES.items():
            if k not in doc.get("rules", {}):
                doc.setdefault("rules", {})[k] = default
        return doc
    doc = {
        "id": f"negr-{uuid.uuid4().hex[:12]}",
        "company_id": company_id,
        "rules": dict(DEFAULT_RULES),
        "created_at": _now(),
        "updated_at": _now(),
        "updated_by": "system_seed",
    }
    await db.negotiation_rules.insert_one(dict(doc))
    return {k: v for k, v in doc.items() if k != "_id"}


async def update_rules(company_id: str, rules: Dict[str, Any],
                        actor: str) -> Dict[str, Any]:
    """Atualiza regras do tenant. Faz merge profundo por ação."""
    current = await get_rules(company_id)
    merged = dict(current.get("rules") or {})
    for action, cfg in (rules or {}).items():
        if action not in CANONICAL_ACTIONS:
            continue
        merged[action] = {**merged.get(action, {}), **(cfg or {})}
    await db.negotiation_rules.update_one(
        {"company_id": company_id},
        {"$set": {"rules": merged, "updated_at": _now(),
                  "updated_by": actor}},
        upsert=True,
    )
    log.info("[negotiation] rules updated cid=%s actor=%s", company_id, actor)
    return await get_rules(company_id)


async def can_offer(action: str, company_id: str,
                     subscriber_id: Optional[str] = None,
                     params: Optional[Dict[str, Any]] = None,
                     actor: str = "isabella") -> Dict[str, Any]:
    """ChokePoint: Isabella DEVE chamar antes de prometer qualquer coisa.

    Retorna {allowed: bool, reason: str, rule_snapshot: dict, attempt_id: str}.
    SEMPRE persiste em `negotiation_attempts` para auditoria.

    Se `allowed=False`, a IA deve responder neutra e disparar
    `handoff_to_human(subscriber_id, reason=...)`.
    """
    params = params or {}
    attempt_id = f"nat-{uuid.uuid4().hex[:12]}"

    if action not in CANONICAL_ACTIONS:
        result = {
            "allowed": False,
            "reason": f"action_unknown:{action}",
            "rule_snapshot": None,
            "attempt_id": attempt_id,
        }
        await _persist_attempt(attempt_id, company_id, subscriber_id,
                                action, params, result, actor)
        return result

    rules_doc = await get_rules(company_id)
    rule = (rules_doc.get("rules") or {}).get(action) or {}

    # Trava 1: regra desligada
    if not rule.get("enabled"):
        result = {
            "allowed": False,
            "reason": f"rule_disabled:{action}",
            "rule_snapshot": rule,
            "attempt_id": attempt_id,
        }
        await _persist_attempt(attempt_id, company_id, subscriber_id,
                                action, params, result, actor)
        return result

    # Trava 2: regras específicas por ação
    if action == ACTION_DISCOUNT:
        pct = float(params.get("pct") or 0)
        brl = float(params.get("brl") or 0)
        max_pct = float(rule.get("max_pct") or 0)
        max_brl = float(rule.get("max_brl") or 0)
        threshold = float(rule.get("requer_aprovacao_humana_acima_de_brl") or 0)
        if pct > max_pct:
            return await _block(attempt_id, company_id, subscriber_id, action,
                                 params, rule, actor,
                                 f"discount_pct_exceeds:{pct}>{max_pct}")
        if max_brl and brl > max_brl:
            return await _block(attempt_id, company_id, subscriber_id, action,
                                 params, rule, actor,
                                 f"discount_brl_exceeds:{brl}>{max_brl}")
        if threshold and brl > threshold:
            return await _block(attempt_id, company_id, subscriber_id, action,
                                 params, rule, actor,
                                 f"discount_above_human_threshold:{brl}>{threshold}")

    elif action == ACTION_PROMISE:
        dias = int(params.get("dias_extensao") or 0)
        max_dias = int(rule.get("max_dias_extensao") or 0)
        if dias > max_dias:
            return await _block(attempt_id, company_id, subscriber_id, action,
                                 params, rule, actor,
                                 f"promise_dias_exceeds:{dias}>{max_dias}")
        if subscriber_id:
            year_start = datetime.now(timezone.utc).replace(
                month=1, day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
            count = await db.negotiation_attempts.count_documents({
                "company_id": company_id, "subscriber_id": subscriber_id,
                "action": ACTION_PROMISE, "result.allowed": True,
                "created_at": {"$gte": year_start},
            })
            max_year = int(rule.get("max_promessas_por_ano") or 0)
            if max_year and count >= max_year:
                return await _block(attempt_id, company_id, subscriber_id,
                                     action, params, rule, actor,
                                     f"promise_yearly_cap:{count}>={max_year}")

    elif action == ACTION_SECOND_INVOICE:
        if subscriber_id:
            month_start = datetime.now(timezone.utc).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
            count = await db.negotiation_attempts.count_documents({
                "company_id": company_id, "subscriber_id": subscriber_id,
                "action": ACTION_SECOND_INVOICE, "result.allowed": True,
                "created_at": {"$gte": month_start},
            })
            max_month = int(rule.get("max_por_mes") or 0)
            if max_month and count >= max_month:
                return await _block(attempt_id, company_id, subscriber_id,
                                     action, params, rule, actor,
                                     f"second_invoice_monthly_cap:{count}>={max_month}")

    elif action == ACTION_INSTALLMENT:
        if rule.get("requer_aprovacao_humana"):
            return await _block(attempt_id, company_id, subscriber_id, action,
                                 params, rule, actor,
                                 "installment_requires_human")
        parcelas = int(params.get("parcelas") or 0)
        max_p = int(rule.get("max_parcelas") or 0)
        if parcelas > max_p:
            return await _block(attempt_id, company_id, subscriber_id, action,
                                 params, rule, actor,
                                 f"installment_parcelas_exceeds:{parcelas}>{max_p}")

    # Allowed
    result = {
        "allowed": True,
        "reason": "ok",
        "rule_snapshot": rule,
        "attempt_id": attempt_id,
    }
    await _persist_attempt(attempt_id, company_id, subscriber_id, action,
                            params, result, actor)
    return result


async def _block(attempt_id, cid, sub_id, action, params, rule, actor, reason):
    result = {
        "allowed": False, "reason": reason,
        "rule_snapshot": rule, "attempt_id": attempt_id,
    }
    await _persist_attempt(attempt_id, cid, sub_id, action, params,
                            result, actor)
    return result


async def _persist_attempt(attempt_id, cid, sub_id, action, params,
                            result, actor):
    try:
        await db.negotiation_attempts.insert_one({
            "id": attempt_id,
            "company_id": cid,
            "subscriber_id": sub_id,
            "action": action,
            "params": params or {},
            "result": result,
            "actor": actor,
            "created_at": _now(),
        })
    except Exception as e:
        log.warning("negotiation_attempts insert failed: %s", e)
