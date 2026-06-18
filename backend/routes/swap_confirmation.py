"""Onda C P1 — Solicitação de Confirmação Patrimonial via WhatsApp.

Aprovado CEO 18/06/2026. Fluxo:

  1. Gestor/admin chama POST /api/swap-confirmation/send/{event_id}
     • Valida que evento está em status pending_confirmation OU
       sent_to_technician (idempotente).
     • Gera confirmation_audit_id determinístico (SHA256).
     • Envia WhatsApp ao técnico via Baileys com 3 links clicáveis:
         · CONFIRMO          → /respond/.../confirmed
         · NÃO HOUVE TROCA   → /respond/.../disputed
         · PRECISO REVISAR   → /respond/.../needs_review
     • Atualiza status para sent_to_technician.

  2. Técnico clica → GET /api/swap-confirmation/respond/{event_id}/{token}/{choice}
     • Token HMAC valida autenticidade.
     • Atualiza status do evento (confirmed | disputed | needs_review).
     • Cria doc em `auto_ont_swap_confirmations` com toda a trilha.
     • NÃO TOCA ESTOQUE (regra do CEO — apenas auditoria).

  3. Watchtower Diagnóstico reflete:
     • confirmed → some do contador "pending"
     • disputed | needs_review → permanece pendente para review do gestor

Regra de ouro: confirmação é apenas auditoria. Correção patrimonial real
SEMPRE passa pelo transfer_engine, nunca por este fluxo.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from core import DEMO_COMPANY_ID, require_role
from database import db
from services.wa.sidecar import SIDECAR_BASE, _sidecar_headers

logger = logging.getLogger("swap_confirmation")
router = APIRouter(tags=["swap_confirmation"])

# HMAC secret derivado do MONGO_URL (presente em todo deploy, único por env)
_SECRET = (os.environ.get("MONGO_URL", "fallback-secret-do-not-use") + "|swap-confirm-v1").encode()

# Mapeamento choice → status final
_CHOICE_TO_STATUS = {
    "confirmed": "confirmed",
    "disputed": "disputed",
    "needs_review": "needs_review",
}
_CHOICE_LABELS = {
    "confirmed": "CONFIRMO",
    "disputed": "NÃO HOUVE TROCA",
    "needs_review": "PRECISO REVISAR",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hmac_token(event_id: str, choice: str) -> str:
    msg = f"{event_id}|{choice}".encode()
    return hmac.new(_SECRET, msg, hashlib.sha256).hexdigest()[:24]


def _confirmation_audit_id(event_id: str) -> str:
    base = f"swap-confirm|{event_id}".encode()
    return "swap-conf-" + hashlib.sha256(base).hexdigest()[:14]


async def _get_event(event_id: str) -> Optional[Dict[str, Any]]:
    return await db.auto_ont_swap_events.find_one(
        {"id": event_id}, {"_id": 0})


# ────────────────────────── Pydantic models ──────────────────────────────

class SendRequest(BaseModel):
    pass  # event_id vai pela URL


class RespondBody(BaseModel):
    event_id: str
    token: str
    choice: str  # confirmed | disputed | needs_review
    raw_text: Optional[str] = None  # opcional — quando técnico responde texto livre


# ────────────────────────── Send (admin → WhatsApp) ──────────────────────

@router.post("/api/swap-confirmation/send/{event_id}")
async def send_swap_confirmation(
    event_id: str,
    user: dict = Depends(require_role("gestor", "administrador", "auditor")),
) -> Dict[str, Any]:
    """Gera links e envia WhatsApp ao técnico via Baileys."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    evt = await _get_event(event_id)
    if not evt:
        raise HTTPException(404, "Evento de swap não encontrado")
    if evt.get("company_id") != cid:
        raise HTTPException(403, "Evento de outra empresa")
    if evt.get("status") not in ("pending_confirmation", "sent_to_technician"):
        raise HTTPException(400, {
            "error": "invalid_state",
            "human_reason": (
                f"Evento já está em status '{evt.get('status')}'. "
                "Apenas pending_confirmation ou sent_to_technician aceitam reenvio."
            ),
        })

    technician_id = evt.get("technician_id")
    tech = await db.collaborators.find_one(
        {"id": technician_id},
        {"_id": 0, "id": 1, "name": 1, "phone": 1},
    ) or {}
    phone = (tech.get("phone") or "").strip()
    if not phone:
        raise HTTPException(400, {
            "error": "technician_without_phone",
            "human_reason": (
                f"Técnico {tech.get('name', technician_id)} não tem telefone "
                "cadastrado. Cadastre antes de enviar confirmação."
            ),
        })

    confirmation_audit_id = _confirmation_audit_id(event_id)
    base_url = os.environ.get("REACT_APP_BACKEND_URL") or os.environ.get(
        "BACKEND_PUBLIC_URL", "")
    tokens = {c: _hmac_token(event_id, c) for c in _CHOICE_TO_STATUS}

    def _link(choice: str) -> str:
        return (
            f"{base_url}/api/swap-confirmation/respond/"
            f"{event_id}/{tokens[choice]}/{choice}"
        )

    msg_text = (
        "🔧 *Confirmação Patrimonial — Lousa Mobile*\n\n"
        f"Detectamos uma troca de ONT no ticket *{evt.get('ticket_id')}* "
        f"({evt.get('ticket_type', 'reparo')}):\n\n"
        f"• ONT anterior: `{evt.get('ont_anterior', '?')}`\n"
        f"• ONT nova:     `{evt.get('ont_atual', '?')}`\n\n"
        "Você confirma essa troca? Toque em uma opção:\n\n"
        f"✅ *CONFIRMO*:           {_link('confirmed')}\n"
        f"❌ *NÃO HOUVE TROCA*:    {_link('disputed')}\n"
        f"⚠️ *PRECISO REVISAR*:    {_link('needs_review')}\n\n"
        "_Esta mensagem é parte da trilha patrimonial auditável. "
        "Não altera estoque automaticamente._"
    )

    send_ok = False
    send_error: Optional[str] = None
    try:
        async with httpx.AsyncClient(
                headers=_sidecar_headers(), timeout=15.0) as cli:
            r = await cli.post(
                f"{SIDECAR_BASE}/send",
                json={"phone": phone, "text": msg_text},
            )
            try:
                out = r.json()
            except Exception:
                out = {"raw": r.text}
            if r.status_code < 400 and out.get("ok"):
                send_ok = True
            else:
                send_error = out.get("error") or f"HTTP {r.status_code}"
    except httpx.HTTPError as e:
        send_error = str(e)
        logger.warning("[swap-confirm] sidecar /send falhou: %s", e)

    # Atualiza evento — mesmo se WhatsApp falhar, registramos a tentativa
    now = _now_iso()
    await db.auto_ont_swap_events.update_one(
        {"id": event_id},
        {"$set": {
            "status": "sent_to_technician" if send_ok else evt.get("status"),
            "confirmation_audit_id": confirmation_audit_id,
            "confirmation_sent_at": now if send_ok else None,
            "confirmation_sent_by": user.get("name") or user.get("id"),
            "confirmation_send_error": send_error,
            "confirmation_phone": phone,
        }},
    )

    return {
        "ok": send_ok,
        "event_id": event_id,
        "confirmation_audit_id": confirmation_audit_id,
        "phone": phone,
        "technician_name": tech.get("name"),
        "send_error": send_error,
        "links": {
            "CONFIRMO": _link("confirmed"),
            "NAO_HOUVE_TROCA": _link("disputed"),
            "PRECISO_REVISAR": _link("needs_review"),
        },
    }


# ────────────────────────── Respond (técnico) ────────────────────────────

async def _process_response(event_id: str, token: str,
                             choice: str, raw_text: Optional[str],
                             origin_hint: str) -> Dict[str, Any]:
    """Valida token + grava resposta (idempotente por choice)."""
    if choice not in _CHOICE_TO_STATUS:
        raise HTTPException(400, {
            "error": "invalid_choice",
            "human_reason": f"Choice inválido. Use: {list(_CHOICE_TO_STATUS)}",
        })
    expected = _hmac_token(event_id, choice)
    if not hmac.compare_digest(token, expected):
        raise HTTPException(403, "Token inválido")

    evt = await _get_event(event_id)
    if not evt:
        raise HTTPException(404, "Evento não encontrado")

    new_status = _CHOICE_TO_STATUS[choice]
    confirmation_audit_id = evt.get("confirmation_audit_id") or \
        _confirmation_audit_id(event_id)
    now = _now_iso()

    # Idempotência: se o evento já tem o mesmo status final, não duplica.
    already = (evt.get("status") == new_status)

    # Cria audit em auto_ont_swap_confirmations (append-only)
    response_doc = {
        "id": f"swap-resp-{uuid.uuid4().hex[:12]}",
        "company_id": evt.get("company_id"),
        "swap_event_id": event_id,
        "confirmation_audit_id": confirmation_audit_id,
        "technician_id": evt.get("technician_id"),
        "ticket_id": evt.get("ticket_id"),
        "ont_anterior": evt.get("ont_anterior"),
        "ont_atual": evt.get("ont_atual"),
        "response": _CHOICE_LABELS[choice],
        "response_code": choice,
        "status_set": new_status,
        "timestamp": now,
        "origin": "whatsapp_patrimonial_confirmation",
        "origin_hint": origin_hint,
        "raw_text": raw_text,
        "idempotent_skip": already,
    }
    await db.auto_ont_swap_confirmations.insert_one(response_doc)

    # Atualiza evento
    if not already:
        await db.auto_ont_swap_events.update_one(
            {"id": event_id},
            {"$set": {
                "status": new_status,
                "confirmation_response": _CHOICE_LABELS[choice],
                "confirmation_response_at": now,
                "confirmation_response_origin": "whatsapp_patrimonial_confirmation",
            }},
        )

    return {
        "ok": True,
        "event_id": event_id,
        "new_status": new_status,
        "response": _CHOICE_LABELS[choice],
        "confirmation_audit_id": confirmation_audit_id,
        "idempotent_skip": already,
    }


@router.get("/api/swap-confirmation/respond/{event_id}/{token}/{choice}",
            response_class=HTMLResponse)
async def respond_swap_confirmation_get(
    event_id: str, token: str, choice: str,
) -> HTMLResponse:
    """Endpoint clicável a partir do link no WhatsApp. Retorna HTML simples."""
    try:
        result = await _process_response(
            event_id, token, choice, None,
            origin_hint="whatsapp_link_click",
        )
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else str(e.detail)
        return HTMLResponse(
            f"<html><body style='font-family:sans-serif;padding:32px;"
            f"text-align:center'><h2 style='color:#dc2626'>Erro</h2>"
            f"<p>{detail}</p></body></html>",
            status_code=e.status_code,
        )
    label = result["response"]
    color = {
        "CONFIRMO": "#10b981",
        "NÃO HOUVE TROCA": "#f59e0b",
        "PRECISO REVISAR": "#3b82f6",
    }.get(label, "#475569")
    return HTMLResponse(
        f"""<html><body style='font-family:sans-serif;padding:32px;
        text-align:center;background:#0f172a;color:#fff'>
        <h1 style='color:{color}'>{label}</h1>
        <p>Sua resposta foi registrada com sucesso.</p>
        <p style='color:#94a3b8;font-size:14px'>
        Evento: {event_id}<br>
        Audit ID: {result['confirmation_audit_id']}
        </p>
        <p style='color:#64748b;font-size:12px;margin-top:32px'>
        SmartProv Patrimônio Engine · Trilha auditável
        </p></body></html>"""
    )


@router.post("/api/swap-confirmation/respond")
async def respond_swap_confirmation_post(
    body: RespondBody,
) -> Dict[str, Any]:
    """Endpoint REST público (com token HMAC). Útil para integrações."""
    return await _process_response(
        body.event_id, body.token, body.choice, body.raw_text,
        origin_hint="api_post",
    )


# ────────────────────────── List / Status (admin) ────────────────────────

@router.get("/api/swap-confirmation/list")
async def list_swap_confirmations(
    user: dict = Depends(require_role("gestor", "administrador", "auditor")),
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """Lista eventos com seu status atual. Para o Watchtower mostrar
    detalhes inline."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"company_id": cid}
    if status:
        q["status"] = status
    events = await db.auto_ont_swap_events.find(q, {"_id": 0}).sort(
        "detected_at", -1).limit(100).to_list(100)
    # Contagem por status
    pipeline = [
        {"$match": {"company_id": cid}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ]
    counts: Dict[str, int] = {}
    async for r in db.auto_ont_swap_events.aggregate(pipeline):
        counts[r["_id"] or "unknown"] = int(r["n"])
    return {
        "events": events,
        "counts_by_status": counts,
        "total": len(events),
    }
