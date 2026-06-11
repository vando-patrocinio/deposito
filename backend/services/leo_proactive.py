"""
leo_proactive.py — Leo Proativo (iter219d)

Após cada varredura do Presidente IA, este módulo detecta situações
acionáveis (riscos críticos, CTOs saturadas, promos zeradas) e
envia mensagens proativas via WhatsApp para o gestor, JÁ formatadas
como propostas confirmáveis.

Quando o gestor responde "sim" na próxima mensagem, o fluxo normal
da Secretária IA (Leo) executa a ação — porque a proposta foi
gravada no `secretaria_conversation_state` como turno do assistant,
e o LLM tem contexto pra chamar a tool exec_*.

Cooldown 4h por tipo+target para evitar spam.
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

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from database import db

logger = logging.getLogger(__name__)

COOLDOWN_HOURS = 4


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


async def _get_gestor_phone(cid: str) -> Optional[str]:
    cfg = await db.conselho_ia_settings.find_one(
        {"company_id": cid},
        {"_id": 0, "presidente_briefing_phone": 1,
         "notify_phone": 1}) or {}
    phone = cfg.get("presidente_briefing_phone") \
        or cfg.get("notify_phone")
    if not phone:
        return None
    return "".join(c for c in phone if c.isdigit()) or None


async def _is_in_cooldown(cid: str, key: str) -> bool:
    cutoff = (_now() - timedelta(hours=COOLDOWN_HOURS)).isoformat()
    found = await db.motor_ia_proactive_notifications.find_one(
        {"company_id": cid, "key": key,
         "sent_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1})
    return bool(found)


async def _mark_sent(cid: str, key: str,
                        kind: str, text: str) -> None:
    await db.motor_ia_proactive_notifications.insert_one({
        "id": f"prn-{uuid.uuid4().hex[:14]}",
        "company_id": cid, "key": key, "kind": kind,
        "text": text, "sent_at": _now_iso(),
    })


async def _seed_conversation_with_proposal(cid: str, phone: str,
                                                text: str) -> None:
    """Grava o turno do Leo no histórico para que o LLM saiba do que
    se trata quando o gestor responder 'sim'. Limita a últimas 6
    mensagens (FIFO) mantendo a regra do iter219c."""
    state = await db.secretaria_conversation_state.find_one(
        {"company_id": cid, "who": phone},
        {"_id": 0, "messages": 1}) or {}
    msgs = (state.get("messages") or [])
    msgs.append({"role": "assistant", "content": text[:1500]})
    msgs = msgs[-6:]
    await db.secretaria_conversation_state.update_one(
        {"company_id": cid, "who": phone},
        {"$set": {"company_id": cid, "who": phone,
                    "messages": msgs,
                    "updated_at": _now_iso()}},
        upsert=True)


async def _send(phone: str, text: str) -> Dict[str, Any]:
    try:
        from services.wa.sidecar import _sidecar_post_silent
        return await _sidecar_post_silent(
            "/send", {"phone": phone, "text": text})
    except Exception as e:
        logger.warning("[leo-proactive] send falhou: %s", e)
        return {"ok": False, "error": str(e)}


# ─────────────────── Detectores ───────────────────
async def _detect_zero_redemption_promos(
    cid: str,
) -> List[Tuple[str, str, str]]:
    """Promos ativas há > 3 dias com zero resgates.
    Retorna [(key, kind, text)]."""
    cutoff = (_now() - timedelta(days=3)).isoformat()
    out: List[Tuple[str, str, str]] = []
    cur = db.parcerias_promotions.find({
        "company_id": cid, "active": True,
        "total_redemptions": {"$in": [0, None]},
        "$or": [
            {"created_at": {"$lte": cutoff}},
            {"created_at": {"$exists": False}},
        ],
    }, {"_id": 0, "id": 1, "title": 1, "partner_name": 1}).limit(3)
    async for p in cur:
        out.append((
            f"promo:{p['id']}",
            "pause_promo",
            (f"☕ Leo aqui. Detectei que a promo "
              f"\"{p.get('title') or p['id']}\" "
              f"do parceiro {p.get('partner_name') or '—'} "
              f"está há mais de 3 dias com zero resgates. "
              f"Sugiro pausar (ID: {p['id']}).\n\n"
              f"Confirma? (responda sim ou não)"),
        ))
    return out


async def _detect_cto_saturation(
    cid: str,
) -> List[Tuple[str, str, str]]:
    """CTO com 15+ clientes ativos — sugere inspeção preventiva."""
    out: List[Tuple[str, str, str]] = []
    try:
        agg = await db.subscribers.aggregate([
            {"$match": {"company_id": cid,
                           "status": {"$in": ["ATIVO", "ATIVA"]},
                           "cto_id": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": "$cto_id", "qtd": {"$sum": 1},
                           "bairro": {"$first": "$neighborhood"}}},
            {"$match": {"qtd": {"$gte": 15}}},
            {"$sort": {"qtd": -1}}, {"$limit": 2},
        ]).to_list(2)
        for r in agg:
            out.append((
                f"cto_sat:{r['_id']}",
                "create_inspection_ticket",
                (f"☕ Leo aqui. A CTO {r['_id']} "
                  f"({r.get('bairro') or 'bairro —'}) está com "
                  f"{r['qtd']} clientes ativos (próxima da saturação). "
                  f"Sugiro criar uma OS de inspeção preventiva.\n\n"
                  f"Confirma? (responda sim ou não)"),
            ))
    except Exception as e:
        logger.warning("[leo-proactive] cto detect err: %s", e)
    return out


async def _detect_high_churn_risk(
    cid: str,
) -> List[Tuple[str, str, str]]:
    """Top 1-2 clientes com score >= 50 e plano alto."""
    out: List[Tuple[str, str, str]] = []
    try:
        from services.presidente_ia import compute_clients_at_risk
        items = await compute_clients_at_risk(cid, limit=10)
        priority = [c for c in items if c.get("score", 0) >= 50][:2]
        for c in priority:
            sid = c["subscriber_id"]
            reasons = ", ".join(c.get("reasons") or [])
            out.append((
                f"churn:{sid}",
                "flag_dunning",
                (f"☕ Leo aqui. O cliente "
                  f"{c.get('name') or sid} tem score {c['score']}/100 "
                  f"de risco de churn ({reasons}). "
                  f"Sugiro marcar para entrar na régua de cobrança "
                  f"(ID: {sid}).\n\n"
                  f"Confirma? (responda sim ou não)"),
            ))
    except Exception as e:
        logger.warning("[leo-proactive] churn detect err: %s", e)
    return out


# ─────────────────── Entry point ───────────────────
async def try_proactive_notifications(
    cid: str,
    max_per_run: int = 3,
) -> Dict[str, Any]:
    """Roda os detectores, manda WhatsApp + grava conversation_state.
    Retorna estatísticas. Idempotente — cooldown 4h por key."""
    phone = await _get_gestor_phone(cid)
    if not phone:
        return {"ok": False, "reason": "phone não configurado",
                 "sent": 0}

    detectors = [
        _detect_zero_redemption_promos(cid),
        _detect_cto_saturation(cid),
        _detect_high_churn_risk(cid),
    ]
    all_msgs: List[Tuple[str, str, str]] = []
    for d in detectors:
        all_msgs.extend(await d)

    sent = 0
    skipped = 0
    details: List[Dict[str, Any]] = []
    for key, kind, text in all_msgs:
        if sent >= max_per_run:
            break
        if await _is_in_cooldown(cid, key):
            skipped += 1
            continue
        res = await _send(phone, text)
        if res.get("ok"):
            await _seed_conversation_with_proposal(cid, phone, text)
            await _mark_sent(cid, key, kind, text)
            sent += 1
            details.append({"key": key, "kind": kind, "ok": True})
        else:
            details.append({"key": key, "kind": kind,
                              "ok": False, "error": res.get("error")})

    return {
        "ok": True, "phone": phone, "sent": sent,
        "skipped_cooldown": skipped, "details": details,
        "total_candidates": len(all_msgs),
    }
