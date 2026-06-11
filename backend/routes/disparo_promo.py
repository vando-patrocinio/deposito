"""Disparo de Promoção/Informação — envio em massa de mensagens livres.

Diferente do `disparo_boleto` (que dispara boletos específicos), este endpoint
permite enviar uma mensagem livre (com texto e/ou imagem) para um conjunto
filtrado de assinantes. Casos de uso típicos:
- Anúncio de manutenção programada
- Campanha promocional (ex: 50% off na fibra de 1Gb)
- Aviso de feriado / mudança de horário
- Newsletter mensal

A mensagem é template — suporta variáveis tipo {nome}, {plano}, {valor}.
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

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/disparo-promo", tags=["disparo-promo"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class PromoFilterIn(BaseModel):
    """Filtros do público-alvo."""
    status: Optional[List[str]] = Field(default=None,
        description="active | suspended | canceled — sem filtro = todos")
    plan_ids: Optional[List[str]] = Field(default=None,
        description="Lista de plan_ids específicos (vazio = todos)")
    city: Optional[str] = Field(default=None, max_length=80)
    tenure_min_months: Optional[int] = Field(default=None, ge=0, le=600)
    tenure_max_months: Optional[int] = Field(default=None, ge=0, le=600)
    only_with_phone: bool = Field(default=True,
        description="Se True, ignora clientes sem celular")
    # Filtros baseados em CONTRATO/RADIUS
    radius_states: Optional[List[str]] = Field(default=None,
        description="ATIVO | GRACE | REDUZIDO | WALLED_GARDEN | SUSPENSO | CANCELADO")
    overdue_min_days: Optional[int] = Field(default=None, ge=0, le=365,
        description="Atraso mínimo da fatura mais antiga em aberto")
    overdue_max_days: Optional[int] = Field(default=None, ge=0, le=365,
        description="Atraso máximo (ex: 0-3 para clientes ainda em grace)")


class PromoPreviewIn(PromoFilterIn):
    """Preview do público + preview da mensagem renderizada para 1º cliente."""
    template: str = Field(..., min_length=2, max_length=4000)


class PromoSendIn(PromoPreviewIn):
    """Envia o disparo de promoção em background."""
    media_b64: Optional[str] = Field(default=None,
        description="Imagem opcional em base64 (será anexada à mensagem)")
    media_mimetype: Optional[str] = Field(default=None,
        description="Ex: image/jpeg")
    throttle_seconds: float = Field(default=2.0, ge=0.5, le=30)
    dry_run: bool = Field(default=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _user_company(user: dict) -> str:
    return user.get("company_id") or DEMO_COMPANY_ID


def _render_template(template: str, sub: Dict[str, Any]) -> str:
    """Substitui {nome}, {plano}, {valor}, {cidade} pelo dado real do assinante."""
    name = (sub.get("name") or "Cliente").strip()
    first_name = name.split()[0] if name else "Cliente"
    plan = sub.get("plan_name") or sub.get("plan_id") or ""
    city = sub.get("city") or sub.get("address_city") or ""
    valor = sub.get("monthly_value") or sub.get("plan_value") or ""
    try:
        if isinstance(valor, (int, float)):
            valor = f"R$ {float(valor):.2f}".replace(".", ",")
    except Exception:
        pass
    return (template
        .replace("{nome}", first_name)
        .replace("{nome_completo}", name)
        .replace("{plano}", str(plan))
        .replace("{valor}", str(valor))
        .replace("{cidade}", str(city))
        .replace("{dias_atraso}", str(sub.get("_overdue_days") or 0))
    )


async def _build_audience(cid: str, body: PromoFilterIn) -> List[Dict[str, Any]]:
    """Aplica os filtros e retorna lista de assinantes com telefone."""
    match: Dict[str, Any] = {"company_id": cid}
    if body.status:
        match["status"] = {"$in": body.status}
    if body.plan_ids:
        match["plan_id"] = {"$in": body.plan_ids}
    if body.city:
        match["address_city"] = {"$regex": re.escape(body.city), "$options": "i"}

    # Resolve filtros de RADIUS state — busca contratos primeiro
    sub_ids_filter = None
    if body.radius_states:
        rs_match = {"company_id": cid,
                     "radius_state": {"$in": body.radius_states}}
        contracts = await db.contracts.find(
            rs_match, {"_id": 0, "subscriber_id": 1}).to_list(20000)
        sub_ids_filter = {c["subscriber_id"] for c in contracts
                          if c.get("subscriber_id")}
        if not sub_ids_filter:
            return []
        match["id"] = {"$in": list(sub_ids_filter)}

    subs = await db.subscribers.find(match, {"_id": 0}).limit(10000).to_list(10000)

    # Filtros por overdue (atraso de fatura) ou se template usa {dias_atraso}
    inadimp_states = {"GRACE", "REDUZIDO", "WALLED_GARDEN", "SUSPENSO"}
    template_uses_dias_atraso = "{dias_atraso}" in (
        getattr(body, "template", "") or "")
    radius_has_inadimp = bool(body.radius_states
        and any(s in inadimp_states for s in body.radius_states))
    overdue_filter = (body.overdue_min_days is not None
                       or body.overdue_max_days is not None)
    need_overdue = (overdue_filter or template_uses_dias_atraso
                     or radius_has_inadimp)
    overdue_map: Dict[str, int] = {}
    if need_overdue:
        today = datetime.now(timezone.utc).date()
        sub_ids = [s["id"] for s in subs if s.get("id")]
        for coll_name in ("invoices", "billing_invoices", "faturas"):
            try:
                coll = db[coll_name]
                async for inv in coll.find({
                    "company_id": cid,
                    "subscriber_id": {"$in": sub_ids},
                    "status": {"$in": ["open", "pending", "vencida",
                                         "em_aberto", "atrasada", "OVERDUE"]},
                }, {"_id": 0, "subscriber_id": 1, "due_date": 1}):
                    sid = inv.get("subscriber_id")
                    due = inv.get("due_date")
                    if not sid or not due:
                        continue
                    try:
                        ddate = (datetime.fromisoformat(
                            due.replace("Z", "+00:00")).date()
                                  if isinstance(due, str) else due.date())
                        if ddate >= today:
                            continue
                        days = (today - ddate).days
                        if days > overdue_map.get(sid, 0):
                            overdue_map[sid] = days
                    except (ValueError, TypeError, AttributeError):
                        continue
            except Exception:
                continue

    out: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for s in subs:
        phone = (s.get("phone") or s.get("cellphone") or "").strip()
        phone_digits = re.sub(r"\D", "", phone)
        if body.only_with_phone and len(phone_digits) < 10:
            continue
        # Filtro de tenure
        if body.tenure_min_months or body.tenure_max_months:
            inst = s.get("installation_date") or s.get("created_at") or ""
            try:
                inst_dt = datetime.fromisoformat(str(inst).replace("Z", "+00:00"))
                months = int((now - inst_dt).days / 30.44)
                if body.tenure_min_months and months < body.tenure_min_months:
                    continue
                if body.tenure_max_months and months > body.tenure_max_months:
                    continue
            except Exception:
                continue
        # Filtro de overdue
        if overdue_filter:
            od = overdue_map.get(s.get("id"), 0)
            if body.overdue_min_days is not None and od < body.overdue_min_days:
                continue
            if body.overdue_max_days is not None and od > body.overdue_max_days:
                continue
        # Sempre seta _overdue_days quando computado (pra render do template)
        if need_overdue:
            s["_overdue_days"] = overdue_map.get(s.get("id"), 0)
        # Normaliza para formato internacional (55)
        if len(phone_digits) >= 11 and not phone_digits.startswith("55"):
            phone_digits = "55" + phone_digits
        s["_phone_normalized"] = phone_digits
        out.append(s)
    return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/preview")
async def preview(body: PromoPreviewIn,
                     user: dict = Depends(require_role("administrador", "gestor"))):
    cid = _user_company(user)
    aud = await _build_audience(cid, body)
    sample_rendered = None
    if aud:
        sample_rendered = _render_template(body.template, aud[0])
    return {
        "ok": True,
        "audience_count": len(aud),
        "sample_rendered_message": sample_rendered,
        "sample_recipient_name": aud[0].get("name") if aud else None,
        "estimated_seconds_at_2s_throttle": int(len(aud) * 2),
    }


@router.post("/send")
async def send(body: PromoSendIn,
                  user: dict = Depends(require_role("administrador"))):
    cid = _user_company(user)
    aud = await _build_audience(cid, body)
    if not aud:
        return {"ok": True, "total": 0, "msg": "Nenhum destinatário elegível."}

    run_id = f"promorun-{uuid.uuid4().hex[:10]}"
    run_doc = {
        "id": run_id,
        "company_id": cid,
        "kind": "disparo_promo",
        "template": body.template,
        "has_media": bool(body.media_b64),
        "filters": body.model_dump(exclude={"media_b64"}),
        "started_at": now_iso(),
        "started_by": user.get("email"),
        "total_candidates": len(aud),
        "sent": 0, "failed": 0,
        "dry_run": body.dry_run,
        "status": "running",
    }
    await db.disparo_promo_runs.insert_one(run_doc)
    asyncio.create_task(_dispatch(cid, run_id, aud, body))
    return {
        "ok": True,
        "run_id": run_id,
        "total_candidates": len(aud),
        "estimated_seconds": int(len(aud) * body.throttle_seconds),
        "dry_run": body.dry_run,
    }


async def _dispatch(cid: str, run_id: str,
                       aud: List[Dict[str, Any]],
                       body: PromoSendIn) -> None:
    from routes.whatsapp_baileys import _sidecar_post
    sent = 0
    failed = 0
    for s in aud:
        phone = s.get("_phone_normalized") or ""
        text = _render_template(body.template, s)
        try:
            if body.dry_run:
                sent += 1
            else:
                payload: Dict[str, Any] = {"phone": phone, "text": text}
                if body.media_b64:
                    payload["media_b64"] = body.media_b64
                    payload["media_mimetype"] = body.media_mimetype or "image/jpeg"
                    payload["media_caption"] = text
                resp = await _sidecar_post("/send", payload)
                if resp.get("ok"):
                    sent += 1
                    await db.aihub_wa_messages.insert_one({
                        "company_id": cid, "phone": phone,
                        "jid": f"{phone}@s.whatsapp.net",
                        "direction": "outbound", "text": text,
                        "agent": "disparo_promo",
                        "delivery_status": "sent",
                        "external_id": resp.get("message_id"),
                        "disparo_run_id": run_id,
                        "created_at": now_iso(),
                    })
                else:
                    failed += 1
        except Exception as e:
            logger.warning("[disparo_promo] %s falhou: %s", phone, e)
            failed += 1
        if (sent + failed) % 5 == 0:
            await db.disparo_promo_runs.update_one(
                {"id": run_id},
                {"$set": {"sent": sent, "failed": failed}},
            )
        if body.throttle_seconds > 0:
            await asyncio.sleep(body.throttle_seconds)

    await db.disparo_promo_runs.update_one(
        {"id": run_id},
        {"$set": {"sent": sent, "failed": failed,
                  "finished_at": now_iso(), "status": "completed"}},
    )
    logger.info("[disparo_promo] run=%s done sent=%d failed=%d",
                  run_id, sent, failed)


@router.get("/runs/{run_id}")
async def get_run(run_id: str,
                     user: dict = Depends(require_role("administrador", "gestor"))):
    doc = await db.disparo_promo_runs.find_one(
        {"id": run_id, "company_id": _user_company(user)}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Run não encontrada")
    return doc


@router.get("/history")
async def history(limit: int = 50,
                     user: dict = Depends(require_role("administrador", "gestor"))):
    cid = _user_company(user)
    rows = await db.disparo_promo_runs.find(
        {"company_id": cid}, {"_id": 0},
    ).sort("started_at", -1).limit(min(limit, 200)).to_list(200)
    return {"runs": rows, "total": len(rows)}
