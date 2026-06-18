"""isabella_claim_generators — Geradores padronizados de Factual Claims (V15.3).

Princípio (CTO 17/02/2026): toda afirmação factual da Isabella DEVE carregar:
    • evidence_id
    • source (de onde veio o dado)
    • timestamp
    • claim_type (sub-tipo dentro do domain)
    • audit_passed (status da validação)

Este módulo expande os geradores para todos os domínios que a Isabella
realmente toca em produção, fechando o ciclo V15 (memória + evidência +
medição executiva).

Domínios cobertos:
    1. cadastro_claim         → identificação do assinante (nome, plano, endereço)
    2. smartolt_status_claim  → status técnico da ONU (online/LOS/sinal)
    3. ticket_status_claim    → OS/ticket aberto/resolvido
    4. financial_extended_claim → saldo aberto, próximo vencimento, histórico

Cada gerador retorna:
    {
      "evidence_id": str | None,
      "claim_type": str,
      "audit_passed": bool,
      "fallback_required": bool,   # True quando IA DEVE dizer "vou verificar"
      "source": str,
      "timestamp": ISO,
      "evidence": {...},           # dados afirmáveis (só se audit passou)
      "warnings": [str],
    }

A IA usa `fallback_required=True` como sinal duro para responder
"deixa eu verificar e te confirmo" ao invés de afirmar algo não comprovado.
"""

NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db
from services import isabella_factual_claims as _fc

logger = logging.getLogger("isabella.claim_generators")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_result(*, claim_doc: Optional[Dict[str, Any]],
                    claim_type: str, source: str,
                    evidence: Dict[str, Any],
                    warnings: List[str]) -> Dict[str, Any]:
    """Padroniza o retorno dos generators."""
    passed = bool(claim_doc and claim_doc.get("audit_passed"))
    eid = (claim_doc or {}).get("id") if claim_doc else None
    return {
        "evidence_id": eid,
        "claim_type": claim_type,
        "audit_passed": passed,
        "fallback_required": not passed,
        "source": source,
        "timestamp": (claim_doc or {}).get("audited_at") or _iso_now(),
        "evidence": evidence if passed else {},
        "warnings": warnings,
    }


# ── 1. CADASTRO (subscriber_status) ────────────────────────────


async def cadastro_claim(
    *,
    company_id: str,
    phone: str,
    subscriber: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Gera claim quando a Isabella identifica o assinante a partir do
    phone. Cobre: nome, plano, endereço, código externo, branch.

    audit_passed = True sse subscriber foi encontrado E tem nome E tem
    plano (campos mínimos pra afirmar algo factual ao cliente).
    """
    warnings: List[str] = []
    checks: List[Dict[str, Any]] = []
    evidence: Dict[str, Any] = {}

    if not subscriber or not subscriber.get("id"):
        warnings.append("subscriber_not_found")
        checks.append({"name": "found", "ok": False, "phone": phone})
        claim_doc = await _fc.claim(
            domain=_fc.ClaimDomain.CADASTRO,
            entity_type="subscriber",
            entity_id=None,
            company_id=company_id,
            checks=checks,
            warnings=warnings,
            evidence={"phone": phone},
        )
        return _build_result(
            claim_doc=claim_doc, claim_type="subscriber_status",
            source="db.subscribers", evidence={}, warnings=warnings,
        )

    name = (subscriber.get("name") or "").strip()
    plan = (subscriber.get("plan_name") or "").strip()
    checks = [
        {"name": "found", "ok": True, "sub_id": subscriber.get("id")},
        {"name": "has_name", "ok": bool(name), "value": name or "—"},
        {"name": "has_plan", "ok": bool(plan), "value": plan or "—"},
    ]
    if not name:
        warnings.append("subscriber_without_name")
    if not plan:
        warnings.append("subscriber_without_plan")

    evidence = {
        "subscriber_id": subscriber.get("id"),
        "name": name,
        "nickname": subscriber.get("nickname"),
        "plan_name": plan,
        "plan_speed": subscriber.get("plan_speed"),
        "plan_price": subscriber.get("plan_price"),
        "branch": subscriber.get("branch"),
        "external_code": subscriber.get("external_code"),
        "billing_method": subscriber.get("billing_method"),
        "due_day": subscriber.get("due_day"),
    }
    claim_doc = await _fc.claim(
        domain=_fc.ClaimDomain.CADASTRO,
        entity_type="subscriber",
        entity_id=subscriber.get("id"),
        company_id=company_id,
        checks=checks,
        warnings=warnings,
        evidence=evidence,
    )
    return _build_result(
        claim_doc=claim_doc, claim_type="subscriber_status",
        source="db.subscribers", evidence=evidence, warnings=warnings,
    )


# ── 2. SMARTOLT (technical) ─────────────────────────────────────


async def smartolt_status_claim(
    *,
    company_id: str,
    subscriber_id: Optional[str],
    onu: Optional[Dict[str, Any]],
    max_stale_minutes: int = 60,
) -> Dict[str, Any]:
    """Gera claim do status da ONU/ONT do cliente baseado em SmartOLT.

    audit_passed = True sse: ONU encontrada E status != desconhecido E
    last_status_change dentro de `max_stale_minutes`.
    """
    warnings: List[str] = []
    checks: List[Dict[str, Any]] = []
    if not onu:
        warnings.append("onu_not_found_for_subscriber")
        checks.append({"name": "onu_found", "ok": False})
        claim_doc = await _fc.claim(
            domain=_fc.ClaimDomain.TECHNICAL,
            entity_type="onu",
            entity_id=None,
            company_id=company_id,
            checks=checks,
            warnings=warnings,
            evidence={"subscriber_id": subscriber_id},
        )
        return _build_result(
            claim_doc=claim_doc, claim_type="smartolt_status",
            source="smartolt.api", evidence={}, warnings=warnings,
        )

    status_raw = (onu.get("status") or "").strip().lower()
    signal_text = onu.get("signal_text") or ""
    last_change = onu.get("last_status_change")
    minutes_since = onu.get("minutes_since_change")
    if isinstance(minutes_since, (int, float)) and minutes_since is not None:
        stale_ok = float(minutes_since) <= max_stale_minutes
    else:
        stale_ok = False
        warnings.append("no_last_status_change_timestamp")

    checks = [
        {"name": "onu_found", "ok": True,
          "onu_id": onu.get("id"), "sn": onu.get("sn")},
        {"name": "status_known", "ok": bool(status_raw),
          "status": status_raw or "desconhecido"},
        {"name": "freshness",
          "ok": stale_ok, "minutes_since": minutes_since,
          "max_stale_minutes": max_stale_minutes},
    ]
    if not status_raw:
        warnings.append("unknown_onu_status")

    evidence = {
        "onu_id": onu.get("id"),
        "sn": onu.get("sn"),
        "model": onu.get("model"),
        "status": status_raw,
        "signal_text": signal_text,
        "signal_1310": onu.get("signal_1310"),
        "signal_1490": onu.get("signal_1490"),
        "olt_name": onu.get("olt_name"),
        "board": onu.get("board"),
        "port": onu.get("port"),
        "last_status_change": last_change,
        "minutes_since_change": minutes_since,
    }
    claim_doc = await _fc.claim(
        domain=_fc.ClaimDomain.TECHNICAL,
        entity_type="onu",
        entity_id=onu.get("sn") or onu.get("id"),
        company_id=company_id,
        checks=checks,
        warnings=warnings,
        evidence=evidence,
    )
    return _build_result(
        claim_doc=claim_doc, claim_type="smartolt_status",
        source="smartolt.api", evidence=evidence, warnings=warnings,
    )


# ── 3. TICKET / OS ──────────────────────────────────────────────


async def ticket_status_claim(
    *,
    company_id: str,
    subscriber_id: Optional[str],
    ticket: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Gera claim sobre status de um ticket/OS específico.

    audit_passed = True sse ticket existe E tem status válido E tem
    `updated_at` (não pode afirmar status sem saber se está atualizado).
    """
    warnings: List[str] = []
    checks: List[Dict[str, Any]] = []
    if not ticket:
        warnings.append("ticket_not_found")
        checks.append({"name": "found", "ok": False})
        claim_doc = await _fc.claim(
            domain=_fc.ClaimDomain.OTHER,
            entity_type="ticket",
            entity_id=None,
            company_id=company_id,
            checks=checks,
            warnings=warnings,
            evidence={"subscriber_id": subscriber_id},
        )
        return _build_result(
            claim_doc=claim_doc, claim_type="ticket_status",
            source="db.tickets", evidence={}, warnings=warnings,
        )

    status = (ticket.get("status") or "").strip().lower()
    updated_at = ticket.get("updated_at")
    has_status = bool(status)
    checks = [
        {"name": "found", "ok": True, "ticket_id": ticket.get("_id")},
        {"name": "has_status", "ok": has_status,
          "status": status or "—"},
        {"name": "has_updated_at", "ok": bool(updated_at),
          "updated_at": str(updated_at) if updated_at else None},
    ]
    if not has_status:
        warnings.append("ticket_without_status")
    if not updated_at:
        warnings.append("ticket_without_updated_at")

    evidence = {
        "ticket_id": ticket.get("_id"),
        "ticket_code": ticket.get("code") or ticket.get("ticket_code"),
        "status": status,
        "title": ticket.get("title") or ticket.get("description"),
        "created_at": str(ticket.get("created_at"))
            if ticket.get("created_at") else None,
        "updated_at": str(updated_at) if updated_at else None,
        "assigned_to": ticket.get("assigned_to")
                          or ticket.get("technician"),
    }
    claim_doc = await _fc.claim(
        domain=_fc.ClaimDomain.OTHER,
        entity_type="ticket",
        entity_id=ticket.get("_id"),
        company_id=company_id,
        checks=checks,
        warnings=warnings,
        evidence=evidence,
    )
    return _build_result(
        claim_doc=claim_doc, claim_type="ticket_status",
        source="db.tickets", evidence=evidence, warnings=warnings,
    )


# ── 4. FINANCIAL EXTENDED ───────────────────────────────────────


async def financial_extended_claim(
    *,
    company_id: str,
    subscriber_id: Optional[str],
    open_invoices: List[Dict[str, Any]],
    next_due_date: Optional[str] = None,
    sync_freshness_hours: Optional[float] = None,
    max_stale_hours: float = 24.0,
) -> Dict[str, Any]:
    """Gera claim sobre saldo + próximo vencimento (afirmações além do
    boleto-em-aberto-específico). audit_passed sse:
      • todas as faturas têm valor, due_date e status
      • sync_freshness_hours <= max_stale_hours (ou None → ignorado)
    """
    warnings: List[str] = []
    checks: List[Dict[str, Any]] = []

    n_invoices = len(open_invoices)
    invoices_ok = True
    for i, inv in enumerate(open_invoices):
        if not (inv.get("amount") and inv.get("due_date")
                  and inv.get("status")):
            invoices_ok = False
            warnings.append(f"invoice_{i}_missing_field")
    checks.append({"name": "invoices_complete", "ok": invoices_ok,
                    "count": n_invoices})

    if sync_freshness_hours is not None:
        fresh = sync_freshness_hours <= max_stale_hours
        if not fresh:
            warnings.append("financial_sync_stale")
        checks.append({"name": "sync_freshness", "ok": fresh,
                        "stale_h": sync_freshness_hours,
                        "max_h": max_stale_hours})

    if next_due_date is not None:
        checks.append({"name": "next_due_known", "ok": bool(next_due_date),
                        "value": next_due_date})

    total_open = sum(float(inv.get("amount") or 0)
                      for inv in open_invoices)
    evidence = {
        "subscriber_id": subscriber_id,
        "open_count": n_invoices,
        "open_total": round(total_open, 2),
        "next_due_date": next_due_date,
        "invoices": [
            {"amount": inv.get("amount"),
              "due_date": inv.get("due_date"),
              "status": inv.get("status")}
            for inv in open_invoices[:5]
        ],
    }
    claim_doc = await _fc.claim(
        domain=_fc.ClaimDomain.FINANCIAL,
        entity_type="subscriber",
        entity_id=subscriber_id,
        company_id=company_id,
        checks=checks,
        warnings=warnings,
        evidence=evidence,
    )
    return _build_result(
        claim_doc=claim_doc, claim_type="financial_extended",
        source="atlaz_financeiro", evidence=evidence,
        warnings=warnings,
    )


# ── 5. FALLBACK TRACKING ────────────────────────────────────────


async def log_fallback_used(
    *,
    company_id: str,
    phone: str,
    claim_type: str,
    evidence_id: Optional[str],
    reason: str,
) -> None:
    """Registra quando a Isabella usou corretamente o fallback
    'deixa eu confirmar' por ter claim audit_passed=False.

    Este é o sinal positivo: a IA NÃO inventou. Vai pra
    `isabella_fallback_events` e aparece no Watchtower como
    "fallback usado corretamente".
    """
    try:
        await db.isabella_fallback_events.insert_one({
            "company_id": company_id,
            "phone": phone,
            "claim_type": claim_type,
            "evidence_id": evidence_id,
            "reason": reason,
            "ts": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.warning("[claim_generators] fallback log falhou: %s", e)


async def fallback_stats(
    *,
    company_id: str,
    hours: int = 24,
) -> Dict[str, Any]:
    """Estatísticas de uso correto do fallback no Watchtower."""
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    total = await db.isabella_fallback_events.count_documents(
        {"company_id": company_id, "ts": {"$gte": since}},
    )
    by_type: Dict[str, int] = {}
    async for r in db.isabella_fallback_events.aggregate([
        {"$match": {"company_id": company_id, "ts": {"$gte": since}}},
        {"$group": {"_id": "$claim_type", "n": {"$sum": 1}}},
    ]):
        by_type[r["_id"] or "?"] = r["n"]
    samples = await db.isabella_fallback_events.find(
        {"company_id": company_id, "ts": {"$gte": since}},
        {"_id": 0, "phone": 1, "claim_type": 1, "reason": 1, "ts": 1},
    ).sort("ts", -1).limit(5).to_list(5)
    for s in samples:
        if hasattr(s.get("ts"), "isoformat"):
            s["ts"] = s["ts"].isoformat()
    return {"total": total, "by_type": by_type, "samples": samples}
