"""opportunity_executor — Sprint B (P0 CEO 17/02/2026).

Bridge entre `commanders_worker` (que detecta oportunidades) e a ação
real no mundo (WhatsApp, OS field-ops, SmartOLT, etc.).

ATÉ HOJE:
    3.338 opportunities criadas, 0 executed_at em TODA a história.
    `executor_ia.py` legado só processa Pipeline Presidencial.

A PARTIR DE AGORA:
    Pipeline B (commanders) → ESTE módulo → ação real → outcome.

═════ Approval Gate (regras duras) ═════
- `block_subscriber` → SEMPRE manual (override do flag), apesar do dado
  Sprint A mostrar 6% de recuperação.
- `schedule_repair` / `schedule_inspection` / `schedule_preventive`
  / `expand_coverage` → respeita `requires_approval=True`.
- WhatsApp `send_reminder` / `send_warning` / `send_negotiation` /
  `satisfaction_survey` / `negotiation_offer` → auto-execute.
- `send_offer` (upsell) → respeita o flag (vem mix do commander_worker).
- `quarantine_release` → auto-execute (sem cliente envolvido).
- `shield_review` / `review_module` → notify-only (não há ação atômica).

═════ Kill switch ═════
Env `OPPORTUNITY_EXECUTOR_DRY_RUN=1` → executor LOGA mas NÃO age.
Env `OPPORTUNITY_EXECUTOR_DISABLED=1` → worker não roda.

═════ Idempotência ═════
- `executed_at` é guard. Se já está set, não re-executa.
- Hard cap `OPPORTUNITY_EXECUTOR_MAX_PER_TICK` (default 20).
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from database import db
from services import wa_dispatcher

logger = logging.getLogger("ponto.opportunity_executor")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _brl(v: Any) -> str:
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "—"


def _is_dry_run() -> bool:
    return os.environ.get("OPPORTUNITY_EXECUTOR_DRY_RUN", "0") == "1"


def _is_dry_for(action_type: str) -> bool:
    """True se ESTE action_type deve rodar em dry-run.

    Combina kill switch global (`OPPORTUNITY_EXECUTOR_DRY_RUN=1`) com
    a allowlist (`OPPORTUNITY_EXECUTOR_ALLOWED_TYPES`). Se a allowlist
    está setada e o type NÃO está nela → força dry-run pra esse type.
    """
    if _is_dry_run():
        return True
    allowed = _allowed_types()
    if allowed is None:
        return False
    return action_type not in allowed


def _allowed_types() -> Optional[set]:
    """Allowlist Fase 1 / Fase 2 controlada por env.

    `OPPORTUNITY_EXECUTOR_ALLOWED_TYPES` = lista CSV de action.type que
    podem ser EXECUTADOS DE VERDADE. Se vazio: comportamento legado
    (todos os tipos auto_wa + notify_only + os_creation).

    CTO 18/02/2026 — Fase 1 autorizada:
      send_reminder, satisfaction_survey,
      schedule_repair, schedule_inspection, schedule_preventive
    """
    raw = (os.environ.get("OPPORTUNITY_EXECUTOR_ALLOWED_TYPES") or "").strip()
    if not raw:
        return None
    return {x.strip() for x in raw.split(",") if x.strip()}


def _max_per_tick() -> int:
    try:
        return max(1, min(100, int(
            os.environ.get("OPPORTUNITY_EXECUTOR_MAX_PER_TICK") or 20)))
    except (TypeError, ValueError):
        return 20


# ── Approval policy ───────────────────────────────────────────


# Types que SEMPRE exigem aprovação humana (override de flag).
_ALWAYS_MANUAL = {"block_subscriber"}
# Types whatsapp/auto sem necessidade de approval.
_AUTO_WA_TYPES = {
    "send_reminder", "send_warning", "send_negotiation",
    "satisfaction_survey", "negotiation_offer",
}
# Types que só notificam (sem ação atômica).
_NOTIFY_ONLY = {"shield_review", "review_module"}


def _resolve_gate(action: Dict[str, Any]) -> Tuple[bool, str]:
    """Retorna `(needs_approval, reason)`."""
    t = (action.get("type") or "").lower()
    if t in _ALWAYS_MANUAL:
        return True, "policy_override:always_manual"
    if action.get("requires_approval") is True:
        return True, "commander_flag"
    if t in _AUTO_WA_TYPES:
        return False, "auto_wa_type"
    if t == "quarantine_release":
        return False, "auto_no_subscriber"
    if t in _NOTIFY_ONLY:
        return False, "notify_only"
    # default: respeita o flag, fallback manual em desconhecido
    return True, "default_manual"


# ── Template renderers ────────────────────────────────────────


def _fmt_invoice_lines(action: Dict[str, Any]) -> str:
    invs = action.get("invoices") or []
    if not invs:
        return ""
    lines: List[str] = []
    for inv in invs[:3]:
        due = inv.get("due") or inv.get("due_date") or ""
        amt = _brl(inv.get("amount"))
        lines.append(f"📄 {amt} · venc. {str(due)[:10]}")
    return "\n".join(lines)


def _render_template(name: str, action: Dict[str, Any],
                       opp: Dict[str, Any]) -> str:
    """Render simples por nome de template. Conservador, factual,
    sem 'isabella tom' — o splitter+Isabella já cuida do resto se o
    canal Baileys reaproveitar pra resposta humana."""
    name = (name or "").lower()
    total = _brl(action.get("total_due_brl") or 0)
    invs_block = _fmt_invoice_lines(action)
    lbl = opp.get("target_label") or "cliente"
    primeiro_nome = (lbl.split()[0] if lbl else "cliente").title()

    if name in ("lembrete_pre_vencimento", "lembrete_atraso_leve",
                  "lembrete"):
        return (
            f"Oi, {primeiro_nome}! Aqui é da Ligo Fibra 💚\n\n"
            f"Lembrete amigável: sua fatura está disponível.\n\n"
            f"{invs_block}\n\n"
            f"💵 Total: *{total}*\n\n"
            f"Se já pagou, pode ignorar. Qualquer dúvida, é só me chamar!"
        )
    if name in ("aviso_final_bloqueio", "warning_block"):
        return (
            f"Oi, {primeiro_nome}. Aqui é da Ligo Fibra.\n\n"
            f"⚠️ Você tem fatura(s) próxima(s) do limite para "
            f"suspensão automática:\n\n"
            f"{invs_block}\n\n"
            f"💵 Total: *{total}*\n\n"
            f"Para evitar interrupção do serviço, regularize "
            f"hoje mesmo. Posso gerar a 2ª via via PIX agora — "
            f"é só responder *boleto*."
        )
    if name in ("negociacao_parcelamento", "negotiation_offer"):
        return (
            f"Olá, {primeiro_nome}! Sei que momentos apertados acontecem.\n\n"
            f"Vamos resolver isso juntos? Posso te encaminhar para "
            f"o nosso time de negociação com **propostas de parcelamento "
            f"flexíveis** para o seu caso (total em aberto: *{total}*).\n\n"
            f"Quer que eu chame? Responda *negociar* que eu cuido."
        )
    if name in ("upgrade_plan", "send_offer"):
        plan = action.get("target_plan") or {}
        plan_name = plan.get("name") or "plano superior"
        plan_price = _brl(plan.get("price"))
        return (
            f"Oi, {primeiro_nome}! 🚀\n\n"
            f"Reparei que sua casa usa muita internet — você poderia "
            f"estar com *{plan_name}* por *{plan_price}/mês*.\n\n"
            f"Mesma estabilidade, dobro da velocidade. Quer testar?\n"
            f"Responda *sim* que eu já faço a troca."
        )
    if name in ("nps_survey", "satisfaction_survey"):
        return (
            f"Oi, {primeiro_nome}! 💙\n\n"
            f"Em uma escala de 0 a 10, o quanto você recomendaria a "
            f"Ligo Fibra pra um amigo ou familiar?\n\n"
            f"Pode responder só com o número — sua nota nos ajuda a "
            f"melhorar todo dia."
        )
    # Fallback genérico — usa o próprio nome do template
    return (
        f"Oi, {primeiro_nome}! Aqui é da Ligo Fibra.\n"
        f"Tenho uma atualização sobre seu cadastro. Pode me responder "
        f"que eu te ajudo no que precisar."
    )


# ── Handlers por type ─────────────────────────────────────────


async def _resolve_phone(opp: Dict[str, Any]) -> Optional[str]:
    """Resolve phone do destinatário. Order:
       1. `recommended_action.phone` (vem populado em dunning/upsell)
       2. `subscriber_phones` por subscriber_id ou external_id
       3. `atlaz_clients_cache.phone` por external_id
       4. extrai external_id do `target_label` ("NOME (123456)") e tenta cache
    """
    action = opp.get("recommended_action") or {}
    p = action.get("phone")
    if p:
        return str(p)
    sub_id = action.get("subscriber_id") or opp.get("target_id")
    ext_id = action.get("subscriber_external_id")
    if not ext_id:
        import re as _re
        m = _re.search(r"\((\d{4,})\)\s*$",
                        opp.get("target_label") or "")
        if m:
            ext_id = m.group(1)
    # subscriber_phones
    if sub_id:
        sp = await db.subscriber_phones.find_one(
            {"subscriber_id": sub_id}, {"_id": 0, "normalized_number": 1})
        if sp and sp.get("normalized_number"):
            return sp["normalized_number"]
    if ext_id:
        sp = await db.subscriber_phones.find_one(
            {"subscriber_external_id": str(ext_id)},
            {"_id": 0, "normalized_number": 1})
        if sp and sp.get("normalized_number"):
            return sp["normalized_number"]
        # atlaz_clients_cache
        ac = await db.atlaz_clients_cache.find_one(
            {"external_id": str(ext_id)},
            {"_id": 0, "phone": 1, "celular": 1, "telefone": 1})
        if ac:
            return (ac.get("phone") or ac.get("celular")
                    or ac.get("telefone") or None)
    return None


async def _execute_whatsapp(opp: Dict[str, Any]) -> Dict[str, Any]:
    """Envia template via wa_dispatcher (canal estrito Baileys quando
    disponível, senão herda da última inbound)."""
    action = opp.get("recommended_action") or {}
    phone = await _resolve_phone(opp)
    if not phone:
        return {"ok": False, "reason": "missing_phone"}
    template = action.get("template") or action.get("type") or "default"
    text = _render_template(template, action, opp)
    if _is_dry_for(action.get("type") or ""):
        return {"ok": True, "dry_run": True, "phone": phone,
                "template": template, "preview": text[:200]}
    r = await wa_dispatcher.send_text(
        company_id=opp.get("company_id") or "co-demo",
        to=phone, text=text, strict=False)
    return {"ok": bool(r.get("ok")),
            "phone": phone, "template": template,
            "provider": r.get("used_provider"),
            "wa_id": r.get("id"),
            "reason": r.get("reason")}


async def _execute_os_creation(opp: Dict[str, Any], os_type: str
                                 ) -> Dict[str, Any]:
    """Cria registro de OS pendente em `pending_os_requests`. Não chama
    o SmartField direto — fica a cargo do gestor de campo despachar."""
    action = opp.get("recommended_action") or {}
    if _is_dry_for(action.get("type") or f"schedule_{os_type}"):
        return {"ok": True, "dry_run": True, "os_type": os_type,
                "sn": action.get("sn"),
                "subscriber_external_id":
                    action.get("subscriber_external_id")}
    req_id = f"osreq-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": req_id,
        "company_id": opp.get("company_id"),
        "os_type": os_type,
        "opp_id": opp.get("id"),
        "subscriber_id": action.get("subscriber_id"),
        "subscriber_external_id": action.get("subscriber_external_id"),
        "sn": action.get("sn"),
        "channel": action.get("channel") or "field_ops",
        "playbook": action.get("playbook"),
        "evidence": opp.get("evidence") or {},
        "created_at": _iso(_now()),
        "status": "pending",
    }
    await db.pending_os_requests.insert_one(doc)
    return {"ok": True, "request_id": req_id, "os_type": os_type}


async def _execute_block_request(opp: Dict[str, Any]) -> Dict[str, Any]:
    """Cria registro `pending_smartolt_action` para o painel admin
    executar o bloqueio físico via SmartOLT. Audit trail garantido —
    NUNCA bloqueia direto do executor (regra dura)."""
    action = opp.get("recommended_action") or {}
    if _is_dry_for("block_subscriber"):
        return {"ok": True, "dry_run": True,
                "subscriber_id": action.get("subscriber_id")}
    req_id = f"smolt-{uuid.uuid4().hex[:10]}"
    await db.pending_smartolt_actions.insert_one({
        "id": req_id,
        "company_id": opp.get("company_id"),
        "opp_id": opp.get("id"),
        "action_kind": "block_subscriber",
        "subscriber_id": action.get("subscriber_id"),
        "subscriber_external_id": action.get("subscriber_external_id"),
        "phone": action.get("phone"),
        "reason": "dunning_block_approved",
        "evidence": opp.get("evidence") or {},
        "approved_by": opp.get("approved_by"),
        "approved_at": opp.get("approved_at"),
        "created_at": _iso(_now()),
        "status": "pending",
    })
    return {"ok": True, "request_id": req_id,
            "kind": "smartolt_block_queued"}


async def _execute_quarantine_release(opp: Dict[str, Any]
                                         ) -> Dict[str, Any]:
    """Marca evento órfão para release. Cria record em
    `pending_quarantine_releases` para o admin revisar."""
    if _is_dry_for("quarantine_release"):
        return {"ok": True, "dry_run": True}
    req_id = f"qrel-{uuid.uuid4().hex[:10]}"
    await db.pending_quarantine_releases.insert_one({
        "id": req_id, "company_id": opp.get("company_id"),
        "opp_id": opp.get("id"),
        "evidence": opp.get("evidence") or {},
        "created_at": _iso(_now()), "status": "pending",
    })
    return {"ok": True, "request_id": req_id}


async def _notify_operator(opp: Dict[str, Any]) -> Dict[str, Any]:
    """`shield_review` / `review_module`: só registra notificação no
    `operator_inbox`. Não age."""
    if _is_dry_for((opp.get("recommended_action") or {}).get("type") or ""):
        return {"ok": True, "dry_run": True}
    nid = f"opnotif-{uuid.uuid4().hex[:10]}"
    await db.operator_inbox.insert_one({
        "id": nid, "company_id": opp.get("company_id"),
        "opp_id": opp.get("id"),
        "kind": opp.get("kind"), "subkind": opp.get("subkind"),
        "message": ((opp.get("recommended_action") or {})
                     .get("message") or ""),
        "created_at": _iso(_now()), "read": False,
    })
    return {"ok": True, "notification_id": nid}


# ── Dispatcher principal ──────────────────────────────────────


async def execute_opportunity(opp: Dict[str, Any]) -> Dict[str, Any]:
    """Executa 1 oportunidade. Idempotente (skip se `executed_at` set).

    Retorna `{ok, result, action_type, gate, ...}`.
    """
    if opp.get("executed_at"):
        return {"ok": False, "reason": "already_executed",
                "executed_at": opp["executed_at"]}
    action = opp.get("recommended_action") or {}
    t = (action.get("type") or "").lower()
    needs_appr, gate_reason = _resolve_gate(action)

    if needs_appr and opp.get("status") not in ("approved",):
        # Marca como aguardando e devolve.
        await db.isabella_commander_opportunities.update_one(
            {"id": opp.get("id"), "company_id": opp.get("company_id")},
            {"$set": {"awaiting_approval_since": _iso(_now()),
                       "gate_reason": gate_reason}})
        return {"ok": False, "reason": "requires_approval",
                "gate_reason": gate_reason, "action_type": t}

    # FASE GATE (CTO 18/02/2026) — allowlist por env.
    # Se setada, força DRY_RUN para tipos fora da allowlist.
    # Em modo "dry_run global" o allowlist é irrelevante.
    allowed = _allowed_types()
    phase_dry_run = False
    if allowed is not None and t not in allowed and not _is_dry_run():
        phase_dry_run = True  # força dry-run pra esse type específico

    # Roteamento
    handler_result: Dict[str, Any]
    if t in ("send_reminder", "send_warning", "send_negotiation",
              "send_offer", "satisfaction_survey", "negotiation_offer"):
        handler_result = await _execute_whatsapp(opp)
    elif t == "schedule_repair":
        handler_result = await _execute_os_creation(opp, "repair")
    elif t == "schedule_inspection":
        handler_result = await _execute_os_creation(opp, "inspection")
    elif t == "schedule_preventive":
        handler_result = await _execute_os_creation(opp, "preventive")
    elif t == "block_subscriber":
        # FIX P0 18/02/2026: antes retornava `block_requires_human` mesmo
        # após approval, deixando opps `approved` eternamente órfãs.
        # Agora: se status=approved, cria pending_smartolt_action para o
        # painel admin executar (audit trail mantido). Se ainda pending,
        # devolve com gate de approval normal.
        if opp.get("status") != "approved":
            handler_result = {"ok": False, "reason": "block_requires_human"}
        else:
            handler_result = await _execute_block_request(opp)
    elif t == "quarantine_release":
        handler_result = await _execute_quarantine_release(opp)
    elif t in _NOTIFY_ONLY:
        handler_result = await _notify_operator(opp)
    elif t == "expand_coverage":
        # Manual approval esperado, mas roteia como notification se
        # alguém forçar status=approved.
        handler_result = await _notify_operator(opp)
    else:
        handler_result = {"ok": False, "reason": f"unsupported_type:{t}"}

    # Persistência do resultado — em DRY_RUN, NÃO marca executed_at
    # (preserva integridade dos KPIs).
    now = _now()
    dry = _is_dry_run() or phase_dry_run
    update: Dict[str, Any] = {
        "execution_result": handler_result,
        "gate_reason": gate_reason,
        "action_type": t,
    }
    if phase_dry_run:
        update["phase_dry_run"] = True
    if not dry:
        update["executed_at"] = _iso(now)
        if handler_result.get("ok"):
            update["status"] = "executed"
        else:
            update["status"] = "execution_failed"
            update["execution_error"] = handler_result.get("reason")
    else:
        update["dry_run_at"] = _iso(now)

    await db.isabella_commander_opportunities.update_one(
        {"id": opp.get("id"), "company_id": opp.get("company_id")},
        {"$set": update})

    # Audit trail (toda execução automática loga)
    await db.opportunity_executor_audit.insert_one({
        "id": f"oexau-{uuid.uuid4().hex[:10]}",
        "opp_id": opp.get("id"),
        "company_id": opp.get("company_id"),
        "kind": opp.get("kind"),
        "subkind": opp.get("subkind"),
        "action_type": t,
        "channel": action.get("channel"),
        "gate_reason": gate_reason,
        "dry_run": dry,  # reflete o estado REAL (global OR phase OR allowlist)
        "phase_dry_run": phase_dry_run,
        "result_ok": bool(handler_result.get("ok")),
        "result": handler_result,
        "created_at": _iso(now),
    })

    logger.info("[executor] opp=%s type=%s result=%s gate=%s dry=%s",
                opp.get("id"), t, handler_result.get("ok"),
                gate_reason, _is_dry_run())
    return {"ok": handler_result.get("ok"), "action_type": t,
            "gate": gate_reason, "result": handler_result}


# ── Worker (drenagem da fila) ─────────────────────────────────


async def drain_pending(*, company_id: Optional[str] = None,
                          limit: Optional[int] = None) -> Dict[str, Any]:
    """Drena N opps prontas para execução. Cap conservador. Idempotente.

    Inclui DOIS subconjuntos:
      1. `status=pending` com `requires_approval=False` e tipo não-manual
         → executor automático para tipos low/medium risk.
      2. `status=approved` SEM `executed_at` → opps aprovadas
         manualmente (inclusive `block_subscriber`) entram aqui.
         Antes desta fix, ficavam órfãs (FIX P0 18/02/2026).
    """
    if os.environ.get("OPPORTUNITY_EXECUTOR_DISABLED") == "1":
        return {"ok": False, "reason": "disabled_by_env"}
    n = limit if limit is not None else _max_per_tick()
    q: Dict[str, Any] = {
        "executed_at": {"$exists": False},
        "$or": [
            # Caso 1: pending elegível para auto-execução
            {
                "status": "pending",
                "recommended_action.type": {"$nin": list(_ALWAYS_MANUAL)},
                "recommended_action.requires_approval": {"$ne": True},
            },
            # Caso 2: approved (aprovado manualmente) — sempre processa
            {"status": "approved"},
        ],
    }
    if company_id:
        q["company_id"] = company_id
    cursor = (db.isabella_commander_opportunities
              .find(q, {"_id": 0}).sort("created_at", 1).limit(n))
    docs = await cursor.to_list(n)
    summary: Dict[str, int] = {"examined": 0, "executed": 0,
                                 "failed": 0, "skipped": 0,
                                 "from_approved": 0}
    for opp in docs:
        summary["examined"] += 1
        if opp.get("status") == "approved":
            summary["from_approved"] += 1
        try:
            r = await execute_opportunity(opp)
            if r.get("ok"):
                summary["executed"] += 1
            elif r.get("reason") in ("requires_approval", "already_executed"):
                summary["skipped"] += 1
            else:
                summary["failed"] += 1
        except Exception as e:  # noqa: BLE001
            summary["failed"] += 1
            logger.exception("[executor] error opp=%s: %s",
                              opp.get("id"), e)
    return {"ok": True, "summary": summary,
            "dry_run": _is_dry_run(), "limit": n}


# ── Scheduler hook ────────────────────────────────────────────


def register_scheduler(scheduler) -> None:
    async def _tick():
        try:
            r = await drain_pending()
            logger.info("[executor.tick] %s", r)
        except Exception as e:  # noqa: BLE001
            logger.exception("[executor.tick] %s", e)

    scheduler.add_job(
        _tick, "interval", minutes=10,
        id="opportunity_executor",
        replace_existing=True, max_instances=1, coalesce=True)
    logger.info("[executor] registered every 10min (dry_run=%s)",
                _is_dry_run())
