"""treasurer_global_guardrail.py — Guardrail GLOBAL da IA Tesoureira.
ORDEM CTO 2026-02 (Regra Global). Princípio: a IA nasce travada.

7 regras + REGRA DE OURO. Falha em qualquer uma => BLOQUEIA.

REGRA DE OURO: na dúvida, NÃO PAGAR.

CEO Override (super_admin) pode quebrar:
  - Regra 2 (frequência 30d)
  - Regra 3 (janela horária)
  - Valores excepcionais
NUNCA pode quebrar:
  - Regra 1 (fornecedor cadastrado + ia_autorizada)
  - Regra 4 (criar/alterar favorecidos via IA)
  - Regra 6 (auditoria)
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
    BRT = ZoneInfo("America/Sao_Paulo")
except Exception:  # pragma: no cover
    from datetime import timezone, timedelta as _td
    BRT = timezone(_td(hours=-3))

from database import db

log = logging.getLogger("ponto.treasurer_guardrail")

WINDOW_START_HOUR = 8   # 08:00 BRT
WINDOW_END_HOUR = 18    # 18:00 BRT
FREQ_DAYS = 30

OVERRIDABLE = {"regra_2_frequencia", "regra_3_janela", "regra_5_valor_excepcional"}
NON_OVERRIDABLE = {"regra_1_fornecedor_nao_autorizado",
                    "regra_1_pix_nao_validado",
                    "regra_1_conta_nao_validada",
                    "regra_1_fornecedor_bloqueado",
                    "regra_1_fornecedor_inativo",
                    "regra_4_destino_nao_cadastrado",
                    "regra_6_auditoria_incompleta",
                    "regra_7_origem_proibida"}


def _now_brt() -> datetime:
    return datetime.now(BRT)


def _now_iso_brt() -> str:
    return _now_brt().isoformat()


def _hash_audit(payment: Dict, validations: List[Dict]) -> str:
    raw = (f"{payment.get('payment_id')}|{payment.get('payee_id')}|"
           f"{payment.get('amount_brl')}|{payment.get('pix_key')}|"
           f"{_now_iso_brt()}|"
           f"{[v['rule'] + ':' + v['status'] for v in validations]}")
    return hashlib.sha256(raw.encode()).hexdigest()


async def enforce_global_rules(
    payment: Dict[str, Any],
    payee: Optional[Dict[str, Any]],
    *,
    actor: str = "IA_TESOUREIRA",
    origin: str = "scheduler",  # scheduler | api | manual_human | chat | wa | email
    ceo_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Chokepoint. Chamado ANTES de qualquer pagamento sair.

    Args:
      payment: doc scheduled_payments
      payee: doc whitelisted_payees (pode ser None se órfão)
      actor: IA_TESOUREIRA | human:<email>
      origin: de onde veio o pedido — Regra 7 só permite 'scheduler' ou 'api' interno
      ceo_override: {motivo (>=20), confirmed_twice: True, by_email, super_admin: True}

    Returns:
      {allowed: bool, blocked_reasons: [str], validations: [dict],
       audit_hash, audit_id, ceo_override_applied: bool}
    """
    validations: List[Dict[str, str]] = []
    blocked: List[str] = []

    def _check(rule: str, ok: bool, detail: str = "") -> None:
        validations.append({
            "rule": rule, "status": "pass" if ok else "fail",
            "detail": detail,
        })
        if not ok:
            blocked.append(rule)

    cid = payment.get("company_id")
    payment_id = payment.get("payment_id")
    payee_id = payment.get("payee_id")
    amount = float(payment.get("amount_brl") or 0)

    # ─── REGRA 7 — Origem proibida (chat/wa/email/api externa) ─────────────
    ALLOWED_ORIGINS = {"scheduler", "api", "manual_human"}
    _check("regra_7_origem_permitida", origin in ALLOWED_ORIGINS,
            f"origin={origin}")

    # ─── REGRA 1 — Fornecedor cadastrado e ativo ───────────────────────────
    if not payee:
        _check("regra_1_fornecedor_nao_autorizado", False,
                f"payee_id={payee_id} não encontrado")
    else:
        _check("regra_1_fornecedor_existe", True,
                f"payee_id={payee_id}")
        # ATIVO
        _check("regra_1_fornecedor_inativo",
                bool(payee.get("active", True)),
                f"active={payee.get('active')}")
        # ia_autorizada (default false — failsafe)
        _check("regra_1_fornecedor_nao_autorizado",
                bool(payee.get("ia_autorizada", False)),
                f"ia_autorizada={payee.get('ia_autorizada', False)}")
        # PIX validado
        pix_validated = bool(payee.get("validacao_chave_pix", {}).get("validated_at"))
        _check("regra_1_pix_nao_validado", pix_validated,
                f"validacao_chave_pix={payee.get('validacao_chave_pix')}")
        # Conta validada (opcional se for só PIX)
        if (payment.get("method") or "pix") != "pix":
            conta_validated = bool(payee.get("validacao_conta", {}).get("validated_at"))
            _check("regra_1_conta_nao_validada", conta_validated,
                    f"validacao_conta={payee.get('validacao_conta')}")
        # Bloqueado
        _check("regra_1_fornecedor_bloqueado",
                not payee.get("bloqueado", False),
                f"bloqueado={payee.get('bloqueado', False)}")

    # ─── REGRA 4 — Destino tem que ser fornecedor cadastrado ───────────────
    # Se faltar payee_id ou pix_key não bater com cadastro -> destino inválido
    _check("regra_4_destino_nao_cadastrado",
            bool(payee_id) and bool(payee),
            f"payee_id={payee_id}")
    if payee:
        pix_payment = (payment.get("pix_key") or "").strip()
        pix_payee = (payee.get("pix_key") or "").strip()
        if pix_payment and pix_payee:
            _check("regra_4_pix_destino_divergente",
                    pix_payment == pix_payee,
                    f"payment.pix={pix_payment[:8]}... payee.pix={pix_payee[:8]}...")

    # ─── REGRA 2 — Frequência (1 pgto / 30 dias / fornecedor) ──────────────
    if payee_id and cid:
        from_dt = (_now_brt() - timedelta(days=FREQ_DAYS)).isoformat()
        prev = await db.scheduled_payments.find_one({
            "company_id": cid,
            "payee_id": payee_id,
            "status": {"$in": ["paid", "sent_to_bank", "approved"]},
            "payment_id": {"$ne": payment_id},
            "$or": [
                {"paid_at": {"$gte": from_dt}},
                {"sent_at": {"$gte": from_dt}},
                {"approved_at": {"$gte": from_dt}},
            ],
        }, {"_id": 0, "payment_id": 1, "paid_at": 1, "sent_at": 1,
            "approved_at": 1})
        _check("regra_2_frequencia",
                prev is None,
                f"previous_payment={prev}")

    # ─── REGRA 3 — Janela horária BRT (08:00-18:00) ────────────────────────
    now_b = _now_brt()
    in_window = WINDOW_START_HOUR <= now_b.hour < WINDOW_END_HOUR
    _check("regra_3_janela", in_window,
            f"hour_brt={now_b.hour}, allowed={WINDOW_START_HOUR}-{WINDOW_END_HOUR}")

    # ─── REGRA 5 — Validações compostas ────────────────────────────────────
    # max_amount_auto do fornecedor
    if payee and amount > float(payee.get("max_amount_auto") or 0):
        _check("regra_5_valor_excepcional", False,
                f"amount={amount} > max_amount_auto="
                f"{payee.get('max_amount_auto')}")
    else:
        _check("regra_5_valor_excepcional", True, "")

    # ─── REGRA 6 — Auditoria mínima preenchida ─────────────────────────────
    required_fields = ["payment_id", "payee_id", "amount_brl", "company_id"]
    missing = [f for f in required_fields if not payment.get(f)]
    _check("regra_6_auditoria_incompleta", not missing,
            f"missing_fields={missing}")

    # ─── CEO Override (Q4=b) ───────────────────────────────────────────────
    ceo_override_applied = False
    if blocked and ceo_override:
        override_ok = (
            ceo_override.get("super_admin") is True
            and ceo_override.get("confirmed_twice") is True
            and isinstance(ceo_override.get("motivo"), str)
            and len(ceo_override.get("motivo", "").strip()) >= 20
            and ceo_override.get("by_email")
        )
        if override_ok:
            # Override só pode liberar regras OVERRIDABLE
            blocked_overridable = [r for r in blocked if r in OVERRIDABLE]
            blocked_non_overridable = [r for r in blocked if r in NON_OVERRIDABLE]
            if blocked_non_overridable:
                # Override NÃO derruba regras 1/4/6/7
                validations.append({
                    "rule": "ceo_override_rejected",
                    "status": "fail",
                    "detail": f"override tentado mas regras não-overridable "
                                f"falharam: {blocked_non_overridable}",
                })
            elif blocked_overridable:
                # Aplica override só nas overridable
                for r in blocked_overridable:
                    blocked.remove(r)
                    validations.append({
                        "rule": f"{r}_overridden",
                        "status": "override",
                        "detail": f"CEO override por {ceo_override['by_email']} "
                                    f"motivo='{ceo_override['motivo'][:60]}...'",
                    })
                ceo_override_applied = True

    allowed = len(blocked) == 0

    # ─── Auditoria obrigatória (Regra 6) ───────────────────────────────────
    audit_id = f"trgu-{uuid.uuid4().hex[:14]}"
    audit_hash = _hash_audit(payment, validations)
    audit_doc = {
        "id": audit_id,
        "company_id": cid,
        "payment_id": payment_id,
        "payee_id": payee_id,
        "payee_name": (payee or {}).get("name"),
        "amount_brl": amount,
        "pix_key": (payment.get("pix_key") or "")[:50],
        "data_hora_brasilia": _now_iso_brt(),
        "data_hora_utc": datetime.utcnow().isoformat() + "Z",
        "actor": actor,
        "origin": origin,
        "allowed": allowed,
        "blocked_reasons": blocked,
        "validations": validations,
        "ceo_override_applied": ceo_override_applied,
        "ceo_override_by": (ceo_override or {}).get("by_email"),
        "ceo_override_motivo": (ceo_override or {}).get("motivo"),
        "hash_auditoria": audit_hash,
        "competencia": _now_brt().strftime("%Y-%m"),
    }
    try:
        await db.treasury_guardrail_audit.insert_one(dict(audit_doc))
    except Exception as e:
        log.warning("guardrail audit insert failed: %s", e)
        # REGRA 6: sem auditoria => BLOQUEAR
        allowed = False
        blocked.append("regra_6_auditoria_incompleta")

    log.info("[guardrail] payment=%s allowed=%s blocked=%s origin=%s "
              "ceo_override=%s actor=%s",
              payment_id, allowed, blocked, origin, ceo_override_applied,
              actor)

    return {
        "allowed": allowed,
        "blocked_reasons": blocked,
        "validations": validations,
        "audit_id": audit_id,
        "audit_hash": audit_hash,
        "ceo_override_applied": ceo_override_applied,
        "checked_at_brt": _now_iso_brt(),
    }


def explain_block(reasons: List[str]) -> str:
    """Texto humano pra mostrar ao usuário/log."""
    if not reasons:
        return "OK"
    mapping = {
        "regra_1_fornecedor_nao_autorizado": "Fornecedor sem flag ia_autorizada=TRUE",
        "regra_1_pix_nao_validado": "Chave PIX do fornecedor não validada",
        "regra_1_conta_nao_validada": "Conta bancária do fornecedor não validada",
        "regra_1_fornecedor_inativo": "Fornecedor inativo",
        "regra_1_fornecedor_bloqueado": "Fornecedor bloqueado",
        "regra_1_fornecedor_existe": "Fornecedor inexistente",
        "regra_2_frequencia": "Já houve pagamento a este fornecedor nos últimos 30 dias",
        "regra_3_janela": "Fora da janela 08:00-18:00 BRT",
        "regra_4_destino_nao_cadastrado": "Destino não é fornecedor cadastrado",
        "regra_4_pix_destino_divergente": "PIX do pagamento difere do cadastro",
        "regra_5_valor_excepcional": "Valor acima do limite max_amount_auto",
        "regra_6_auditoria_incompleta": "Falha na auditoria obrigatória",
        "regra_7_origem_permitida": "Origem proibida (chat/wa/email/api externa)",
    }
    return " | ".join(mapping.get(r, r) for r in reasons)
