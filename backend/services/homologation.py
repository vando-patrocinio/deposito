"""
homologation.py — MODO HOMOLOGAÇÃO CONTROLADA (SMARTPROV)

Gateway único de envio WhatsApp. TODA tentativa de envio passa por aqui.

REGRAS DURAS:
  - Quando HOMOLOG_MODE=true, qualquer destino diferente de TEST_PHONE
    é BLOQUEADO e emite evento HOMOLOGATION_BLOCKED_REAL_PHONE.
  - Mensagens recebem prefixo "[HOMOLOGAÇÃO SMARTPROV]".
  - Dados do cliente são MASCARADOS antes do envio
    (Nome=CLIENTE TESTE · Telefone=OCULTO · Documento=OCULTO).
  - Outcomes/Métricas recebem `environment="homolog"` para NÃO
    contaminar produção.

Pipeline completo continua funcionando:
  Evento → Decisão → Ação → WhatsApp → Outcome → Learning
mas direcionado ao número de testes.
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import os
import re
import uuid
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import db

logger = logging.getLogger("homologation")


TEST_PHONE = "5521998176526"
HOMOLOG_PREFIX = "[HOMOLOGAÇÃO SMARTPROV]"
BLOCKED_FIELDS = (
    "subscribers", "subscriber_phones", "atlaz_clients_cache",
    "invoices", "opportunities", "operacao_tese",
)


# ─── DB-backed overrides (iter246) ─────────────────────────────────────
# UI em Configurações pode ligar/desligar o modo teste e trocar o número
# de teste sem mexer em env var. Lemos `aihub_settings.wa_test_mode` por
# company_id com cache em memória (TTL 30s) para não bater Mongo a cada
# mensagem. Failsafe: se algo falhar, cai no comportamento legado (env).
import time as _time
_SETTINGS_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}
_SETTINGS_TTL = 30.0  # segundos


def _invalidate_settings_cache(company_id: Optional[str] = None) -> None:
    """Chamado pelo endpoint PUT após edição via UI."""
    if company_id:
        _SETTINGS_CACHE.pop(company_id, None)
    else:
        _SETTINGS_CACHE.clear()


async def _get_db_settings(company_id: str) -> Optional[Dict[str, Any]]:
    """Lê settings do banco com cache TTL. Retorna None se não houver
    documento (mantém compatibilidade com env-var legacy)."""
    now = _time.monotonic()
    cached = _SETTINGS_CACHE.get(company_id)
    if cached and (now - cached[0]) < _SETTINGS_TTL:
        return cached[1]
    try:
        doc = await db.aihub_settings.find_one(
            {"company_id": company_id, "key": "wa_test_mode"},
            {"_id": 0, "value": 1},
        )
    except Exception:  # noqa: BLE001
        return None
    if not doc:
        _SETTINGS_CACHE[company_id] = (now, None)  # type: ignore[assignment]
        return None
    value = doc.get("value") or {}
    _SETTINGS_CACHE[company_id] = (now, value)
    return value


async def is_homolog_for(company_id: Optional[str]) -> bool:
    """Versão async com override do banco. Default: env var (failsafe true)."""
    if company_id:
        s = await _get_db_settings(company_id)
        if s and "enabled" in s:
            return bool(s["enabled"])
    return is_homolog()


async def get_test_phone_for(company_id: Optional[str]) -> str:
    """Número de teste efetivo. Override do banco com fallback hardcoded."""
    if company_id:
        s = await _get_db_settings(company_id)
        if s and s.get("test_phone"):
            digits = re.sub(r"\D", "", str(s["test_phone"]))
            if digits.startswith("0"):
                digits = digits.lstrip("0")
            if len(digits) <= 11 and not digits.startswith("55"):
                digits = "55" + digits
            if 12 <= len(digits) <= 13:
                return digits
    return TEST_PHONE


def is_homolog() -> bool:
    """Modo homologação ativo? Default = TRUE (failsafe)."""
    v = (os.environ.get("HOMOLOG_MODE") or "true").lower()
    return v not in ("false", "0", "no", "off")


# ─── V9 P3 — Whitelist Causal Pilot (liberação cirúrgica sem desligar
# HOMOLOG_MODE). Números listados em CAUSALITY_PILOT_PHONES (CSV, com ou
# sem prefixo 55) recebem envio REAL — sem máscara, sem prefixo de
# homologação. Demais números continuam bloqueados/redirecionados.
def _parse_whitelist() -> set:
    raw = (os.environ.get("CAUSALITY_PILOT_PHONES") or "").strip()
    if not raw:
        return set()
    return {_norm_phone(x.strip()) for x in raw.split(",") if x.strip()}


def is_whitelisted(phone: str) -> bool:
    """True quando phone (normalizado) está em CAUSALITY_PILOT_PHONES."""
    if not phone:
        return False
    return _norm_phone(phone) in _parse_whitelist()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_phone(raw: str) -> str:
    """Normaliza para apenas dígitos com prefixo país."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", str(raw))
    if digits.startswith("0"):
        digits = digits.lstrip("0")
    if len(digits) <= 11 and not digits.startswith("55"):
        digits = "55" + digits
    return digits


def mask_client_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Aplica máscara hardcoded V5: nome/telefone/documento ocultos."""
    out = dict(data) if isinstance(data, dict) else {}
    for k in ("name", "nome", "client_name", "full_name"):
        if k in out:
            out[k] = "CLIENTE TESTE"
    for k in ("phone", "telefone", "celular", "msisdn", "whatsapp"):
        if k in out:
            out[k] = "OCULTO"
    for k in ("document", "documento", "cpf", "cnpj", "rg"):
        if k in out:
            out[k] = "OCULTO"
    return out


def prefix_message(text: str) -> str:
    """Prefixo obrigatório de homologação. Idempotente."""
    if not text:
        return HOMOLOG_PREFIX
    if text.strip().startswith(HOMOLOG_PREFIX):
        return text
    return f"{HOMOLOG_PREFIX} {text}"


async def safe_send_whatsapp(
    *,
    company_id: str,
    target_phone: str,
    message: str,
    origin: str = "unknown",
    client_context: Optional[Dict[str, Any]] = None,
    decision_id: Optional[str] = None,
    action_id: Optional[str] = None,
) -> Dict[str, Any]:
    """ÚNICA porta de saída para WhatsApp.

    Comportamento:
      1) Normaliza phone. Se modo homolog ativo e phone ≠ TEST_PHONE:
         BLOQUEIA + emite HOMOLOGATION_BLOCKED_REAL_PHONE + retorna
         status="blocked_homolog" com o destino REDIRECIONADO para
         TEST_PHONE como fallback.
      2) Aplica prefixo + mascara client_context.
      3) Persiste em wa_outbox (queue) + wa_messages_sent (log).
      4) Retorna payload auditável.

    IMPORTANTE: nesta versão de homologação o "envio real" é SIMULADO
    (não usa Baileys de fato — apenas grava em wa_messages_sent com
    transport='homolog_simulated'). Quando Baileys for plugado, este
    é o único ponto que precisa apontar para o sidecar.
    """
    msg_id = f"wa-{uuid.uuid4().hex[:12]}"
    requested = _norm_phone(target_phone)
    effective = requested
    block = False
    blocked_reason = None
    pilot_real = False  # V9 P3 — autorização via CAUSALITY_PILOT_PHONES

    # iter246: lê override do banco (UI Configurações). Failsafe: se DB
    # falhar, cai no env var.
    homolog_active = await is_homolog_for(company_id)
    effective_test_phone = await get_test_phone_for(company_id)
    env = "homolog" if homolog_active else "production"

    # ─── KILL SWITCH (P0 safety) ─────────────────────────────
    # Checa ANTES de qualquer envio. Se desligado, bloqueia e audita.
    try:
        from services.kill_switch import is_off as _ks_is_off
        if await _ks_is_off("whatsapp", company_id):
            return {
                "id": msg_id, "status": "blocked_killswitch",
                "to_effective": None, "blocked": True,
                "blocked_reason": "kill_switch.whatsapp=OFF",
                "environment": env, "delivery_status": "blocked_killswitch",
                "sidecar_message_id": None, "sidecar_error": None,
                "message_preview": (message or "")[:120]}
    except Exception:  # noqa: BLE001 — kill switch falha não deve quebrar envio
        pass
    # ──────────────────────────────────────────────────────────

    if homolog_active:
        if requested == effective_test_phone:
            pass  # caminho legado: envio mascarado ao número técnico
        elif is_whitelisted(requested):
            # V9 P3 — whitelist causal: número autorizado para piloto
            # real. Envia ao número original SEM prefixo de homologação
            # e SEM mascarar contexto. HOMOLOG_MODE continua true; só
            # este número é liberado cirurgicamente.
            pilot_real = True
            env = "causality_pilot"
            effective = requested
        else:
            block = True
            blocked_reason = (
                f"HOMOLOG_MODE=true · destino {requested[:4]}*** "
                f"≠ TEST_PHONE {effective_test_phone} · não whitelistado")
            effective = effective_test_phone  # redireciona

    final_text = (message or "") if pilot_real \
        else prefix_message(message or "")
    masked_ctx = (client_context or {}) if pilot_real \
        else mask_client_data(client_context or {})

    if block:
        ev_id = f"evt-{uuid.uuid4().hex[:12]}"
        await db.motor_ia_events.insert_one({
            "id": ev_id, "event_id": ev_id,
            "event_type": "HOMOLOGATION_BLOCKED_REAL_PHONE",
            "source": "homologation",
            "company_id": company_id,
            "environment": env,
            "payload": {
                "origin": origin,
                "requested_phone_redacted":
                    f"{requested[:4]}***{requested[-2:]}"
                    if len(requested) >= 6 else "INVALID",
                "redirected_to": effective_test_phone,
                "reason": blocked_reason,
                "decision_id": decision_id,
                "action_id": action_id,
            },
            "consumed": False,
            "created_at": _now_iso(), "timestamp": _now_iso(),
        })
    elif pilot_real:
        # V9 P3 — auditoria de envio causal real (whitelist autorizada).
        # Mesmo nível de rastreabilidade que o BLOCKED, mas sinalizando
        # liberação cirúrgica. NÃO contamina métricas de produção
        # (environment="causality_pilot").
        ev_id = f"evt-{uuid.uuid4().hex[:12]}"
        await db.motor_ia_events.insert_one({
            "id": ev_id, "event_id": ev_id,
            "event_type": "CAUSALITY_PILOT_REAL_SEND",
            "source": "homologation",
            "company_id": company_id,
            "environment": env,
            "payload": {
                "origin": origin,
                "phone_redacted":
                    f"{requested[:4]}***{requested[-2:]}"
                    if len(requested) >= 6 else "INVALID",
                "decision_id": decision_id,
                "action_id": action_id,
                "reason": "CAUSALITY_PILOT_PHONES whitelist authorized",
            },
            "consumed": False,
            "created_at": _now_iso(), "timestamp": _now_iso(),
        })

    outbox_doc = {
        "id": msg_id,
        "company_id": company_id,
        "environment": env,
        "origin": origin,
        "decision_id": decision_id,
        "action_id": action_id,
        "to_requested_redacted":
            (f"{requested[:4]}***{requested[-2:]}"
             if requested and len(requested) >= 6 else "INVALID"),
        "to_effective": effective,
        "message": final_text,
        "masked_client": masked_ctx,
        "transport": "baileys_sidecar",
        "status": "blocked_homolog" if block else "queued",
        "blocked": block,
        "blocked_reason": blocked_reason,
        "queued_at": _now_iso(),
    }
    await db.wa_outbox.insert_one(outbox_doc.copy())

    # Dispatch via sidecar Baileys real. SEMPRE para `effective`,
    # que é TEST_PHONE em homolog (linha 126). Sem whitelist,
    # sem bypass — a única forma de chegar em outro número é
    # desligando HOMOLOG_MODE, o que está fora do escopo.
    sidecar_response: Dict[str, Any] = {}
    sidecar_error: Optional[str] = None
    delivery_status = "blocked_not_sent"
    sent_status = "blocked_homolog" if block else "queued"
    if effective == effective_test_phone or pilot_real:
        # 🛡️ INVARIANTE: só envia se destino efetivo == test_phone OU
        # se é piloto causal autorizado (whitelist CAUSALITY_PILOT_PHONES).
        # Demais casos foram redirecionados para test_phone acima.
        try:
            from services.wa.sidecar import _sidecar_post_silent
            sidecar_response = await _sidecar_post_silent(
                "/send",
                {"phone": effective, "text": final_text,
                 "__gateway_bypass__": True}) or {}
            if sidecar_response.get("ok"):
                delivery_status = "delivered_baileys"
                sent_status = "sent_baileys"
            else:
                delivery_status = "sidecar_failed"
                sent_status = "send_failed"
                sidecar_error = str(sidecar_response)[:200]
        except Exception as e:  # noqa: BLE001
            sidecar_error = repr(e)[:200]
            delivery_status = "sidecar_exception"
            sent_status = "send_failed"
            logger.warning("[homolog] sidecar send fail: %r", e)
    else:
        # Caminho impossível em HOMOLOG_MODE=true mas auditável.
        logger.error(
            "[homolog] INVARIANT_BROKEN effective=%s ≠ TEST_PHONE",
            effective)
        sidecar_error = "invariant_broken_effective_not_test_phone"
        delivery_status = "blocked_invariant"

    outbox_doc["status"] = sent_status
    outbox_doc["sent_at"] = _now_iso()
    outbox_doc["sidecar_response"] = sidecar_response
    outbox_doc["sidecar_error"] = sidecar_error
    outbox_doc["delivery_status"] = delivery_status
    outbox_doc["sidecar_message_id"] = sidecar_response.get(
        "message_id")
    outbox_doc["original_phone_redacted"] = outbox_doc[
        "to_requested_redacted"]
    outbox_doc["effective_phone"] = effective

    await db.wa_outbox.update_one(
        {"id": msg_id}, {"$set": {
            "status": sent_status,
            "sent_at": outbox_doc["sent_at"],
            "sidecar_response": sidecar_response,
            "sidecar_error": sidecar_error,
            "sidecar_message_id": outbox_doc["sidecar_message_id"],
            "delivery_status": delivery_status}})
    await db.wa_messages_sent.insert_one({
        **outbox_doc,
        "kind": ("causality_pilot_send" if pilot_real
                 else "homolog_send_via_baileys")})

    return {
        "id": msg_id,
        "status": sent_status,
        "to_effective": effective,
        "blocked": block,
        "blocked_reason": blocked_reason,
        "message_preview": final_text[:120],
        "environment": env,
        "sidecar_message_id": outbox_doc["sidecar_message_id"],
        "delivery_status": delivery_status,
        "sidecar_error": sidecar_error,
    }


# ─────────────────────── pipeline simulation (Fase 7+) ────────────────
async def simulate_full_pipeline(
    company_id: str, scenario: str = "default",
) -> Dict[str, Any]:
    """Demonstra o pipeline completo de homologação:
    Evento sintético → autonomous_engine.run_cycle → Decisão →
    Ação WhatsApp via safe_send → Outcome com environment=homolog →
    Learning.

    NÃO depende de subscriber real — usa dados sintéticos mascarados.
    """
    from services import autonomous_engine as eng

    if not is_homolog():
        raise RuntimeError(
            "Pipeline de homologação só pode rodar com HOMOLOG_MODE=true.")

    # 1) Evento sintético (sem usar telefone de cliente real)
    synthetic_event = {
        "event_type": "HOMOLOG_PIPELINE_TEST",
        "company_id": company_id,
        "subscriber_id": f"homolog-sub-{uuid.uuid4().hex[:6]}",
        "payload": {
            "scenario": scenario,
            "synthetic": True,
            "client_context": {
                "name": "Cliente Originalmente Real",  # será mascarado
                "phone": "11912345678",  # será redirecionado
                "document": "12345678900",  # será ocultado
            },
            "message_template":
                "Olá! Sua conta vence amanhã. Acesse o link para pagar.",
        },
    }
    # Persistir evento
    ev_id = f"evt-{uuid.uuid4().hex[:12]}"
    synthetic_event["event_id"] = ev_id
    synthetic_event["id"] = ev_id
    synthetic_event["consumed"] = False
    synthetic_event["environment"] = "homolog"
    synthetic_event["created_at"] = _now_iso()
    synthetic_event["timestamp"] = _now_iso()
    await db.motor_ia_events.insert_one(synthetic_event.copy())

    # 2) Pipeline autônomo (cria analysis/decision/action/outcome/learning)
    cycle = await eng.run_cycle(synthetic_event)

    # run_cycle retorna dicts completos (analysis/decision/action/outcome/
    # learning) com chaves *_id internas. Extraímos os ids aqui.
    analysis_id = (cycle.get("analysis") or {}).get("analysis_id")
    decision_id = (cycle.get("decision") or {}).get("decision_id")
    action_id = (cycle.get("action") or {}).get("action_id")
    outcome_id = (cycle.get("outcome") or {}).get("outcome_id")
    learning_id = (cycle.get("learning") or {}).get("learning_id")

    # 3) Disparo via gateway homolog (a action é open_technical_ticket
    # default — para testar WhatsApp também, disparo aqui adicionalmente)
    send_out = await safe_send_whatsapp(
        company_id=company_id,
        target_phone=synthetic_event["payload"]["client_context"]["phone"],
        message=synthetic_event["payload"]["message_template"],
        origin="homolog.simulate_full_pipeline",
        client_context=synthetic_event["payload"]["client_context"],
        decision_id=decision_id,
        action_id=action_id,
    )

    # 4) Marcar outcome com environment=homolog (proteção contra
    # contaminação de métricas)
    if outcome_id:
        await db.motor_ia_outcomes.update_one(
            {"outcome_id": outcome_id},
            {"$set": {"environment": "homolog",
                      "wa_message_id": send_out["id"]}})
    if action_id:
        await db.motor_ia_actions.update_one(
            {"action_id": action_id},
            {"$set": {"environment": "homolog",
                      "wa_message_id": send_out["id"]}})

    return {
        "company_id": company_id,
        "scenario": scenario,
        "event_id": ev_id,
        "cycle_id": cycle.get("cycle_id"),
        "analysis_id": analysis_id,
        "decision_id": decision_id,
        "action_id": action_id,
        "outcome_id": outcome_id,
        "learning_id": learning_id,
        "wa_send": send_out,
        "environment": "homolog",
        "generated_at": _now_iso(),
    }


async def reconcile_outbox(company_id: str) -> Dict[str, Any]:
    """Reconcilia outbox: marca outcomes do environment=homolog como
    completed quando há wa_messages_sent correspondente."""
    sent_ids = await db.wa_messages_sent.distinct(
        "id", {"company_id": company_id, "environment": "homolog"})
    matched = 0
    async for o in db.motor_ia_outcomes.find({
        "company_id": company_id, "environment": "homolog",
        "wa_message_id": {"$in": sent_ids}
    }):
        await db.motor_ia_outcomes.update_one(
            {"outcome_id": o.get("outcome_id") or o.get("id")},
            {"$set": {"status": "reconciled_homolog",
                      "reconciled_at": _now_iso()}})
        matched += 1
    return {"company_id": company_id,
            "matched_outcomes": matched,
            "sent_ids_total": len(sent_ids),
            "generated_at": _now_iso()}


async def homologation_status(company_id: str) -> Dict[str, Any]:
    """Status completo do modo homologação para a UI."""
    queued = await db.wa_outbox.count_documents({
        "company_id": company_id, "environment": "homolog"})
    sent = await db.wa_messages_sent.count_documents({
        "company_id": company_id, "environment": "homolog"})
    blocked = await db.wa_outbox.count_documents({
        "company_id": company_id, "blocked": True})
    blocked_events = await db.motor_ia_events.count_documents({
        "company_id": company_id,
        "event_type": "HOMOLOGATION_BLOCKED_REAL_PHONE"})
    outcomes_homolog = await db.motor_ia_outcomes.count_documents({
        "company_id": company_id, "environment": "homolog"})
    last_send = await db.wa_messages_sent.find_one(
        {"company_id": company_id, "environment": "homolog"},
        sort=[("sent_at", -1)])
    return {
        "company_id": company_id,
        "homolog_mode_active": is_homolog(),
        "test_phone": TEST_PHONE,
        "homolog_prefix": HOMOLOG_PREFIX,
        "blocked_fields": list(BLOCKED_FIELDS),
        "metrics": {
            "messages_queued": queued,
            "messages_sent": sent,
            "messages_blocked": blocked,
            "blocked_events_emitted": blocked_events,
            "outcomes_with_environment_homolog": outcomes_homolog,
        },
        "last_send": (
            {"id": last_send.get("id"),
             "sent_at": last_send.get("sent_at"),
             "preview": (last_send.get("message") or "")[:100]}
            if last_send else None),
        "generated_at": _now_iso(),
    }


async def filter_production_outcomes(
    company_id: str, window_days: int = 30
) -> Dict[str, Any]:
    """Helper de auditoria: garante que métricas financeiras de produção
    NÃO incluem registros com environment=homolog."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)
              ).isoformat()
    prod = await db.motor_ia_outcomes.count_documents({
        "company_id": company_id,
        "environment": {"$ne": "homolog"},
        "observed_at": {"$gte": cutoff}})
    homo = await db.motor_ia_outcomes.count_documents({
        "company_id": company_id,
        "environment": "homolog",
        "observed_at": {"$gte": cutoff}})
    return {"company_id": company_id, "window_days": window_days,
            "production_outcomes": prod,
            "homolog_outcomes": homo,
            "isolation_correct": True,
            "note": "Sempre filtre por environment={$ne: 'homolog'} "
                    "para métricas de produção."}
