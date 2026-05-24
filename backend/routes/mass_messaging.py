"""Disparo em Massa (WhatsApp Cloud API + Twilio) — Mass Messaging.

Features:
  • Upload CSV com phone + variáveis ({{1}}, {{2}}, etc)
  • Templates aprovados (HSM) ou texto livre
  • Throttling configurável (msgs/min) — respeita limite Meta (default 80/min)
  • Status por destinatário: queued / sending / sent / delivered / failed
  • Worker em background processa fila respeitando throttle
  • Suporte aos canais: meta_cloud, twilio (configurável por campanha)

Coleções:
  • mass_campaigns       — campanhas (id, name, channel, mode, template,
                                       text, csv_headers, total, status, ...)
  • mass_recipients      — destinatários (campaign_id, phone, vars{},
                                          status, message_id, error, sent_at)
"""
import asyncio
import csv
import io
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel, Field

from core import DEMO_COMPANY_ID, now_iso, require_role
from database import db
from services.rate_limit import limiter, get_limit

logger = logging.getLogger("ponto.mass_messaging")
router = APIRouter(prefix="/api/mass-messaging", tags=["mass-messaging"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class CampaignCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    channel: str = Field(..., pattern="^(meta_cloud|twilio|baileys)$")
    mode: str = Field(..., pattern="^(template|free)$")
    text: Optional[str] = None  # Para mode=free; suporta {{1}}, {{2}}, etc.
    template_name: Optional[str] = None  # Para mode=template
    template_language: Optional[str] = "pt_BR"
    template_components: Optional[List[Dict[str, Any]]] = None
    schedule_at: Optional[str] = None  # ISO; None = imediato após start
    throttle_per_min: int = Field(60, ge=1, le=600)
    # Override de canal Baileys (multi-número). None = usa o canal default
    # outbound da empresa. Aceito apenas quando channel=='baileys'.
    channel_id: Optional[str] = Field(
        default=None,
        pattern=r"^channel-[1-4]$",
    )


class CampaignStartPayload(BaseModel):
    force_now: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
PHONE_RE = re.compile(r"\D+")


def _normalize_phone(p: str) -> Optional[str]:
    if not p:
        return None
    digits = PHONE_RE.sub("", str(p))
    if not digits:
        return None
    if not digits.startswith("55") and len(digits) in (10, 11):
        digits = "55" + digits
    if len(digits) < 12 or len(digits) > 15:
        return None
    return digits


def _render_template(text: str, vars_: Dict[str, str]) -> str:
    """Substitui {{1}}, {{2}}, {{name}}, etc."""
    if not text:
        return ""
    out = text
    for k, v in (vars_ or {}).items():
        out = out.replace("{{" + str(k) + "}}", str(v or ""))
    return out


# ---------------------------------------------------------------------------
# Endpoints — Campaign CRUD
# ---------------------------------------------------------------------------
@router.get("/campaigns")
async def list_campaigns(user: dict = Depends(require_role("administrador", "gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    cur = db.mass_campaigns.find({"company_id": cid}, {"_id": 0}).sort([("created_at", -1)])
    return [doc async for doc in cur]


@router.post("/campaigns")
@limiter.limit(get_limit("mass_create"))
async def create_campaign(request: Request,
                          payload: CampaignCreate,
                          user: dict = Depends(require_role("administrador", "gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    if payload.mode == "template" and not payload.template_name:
        raise HTTPException(400, "template_name é obrigatório no modo template")
    if payload.mode == "free" and not payload.text:
        raise HTTPException(400, "text é obrigatório no modo free")
    doc = {
        "id": f"camp-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        **payload.model_dump(),
        "status": "draft",  # draft -> queued -> running -> paused/done
        "total_recipients": 0,
        "sent": 0, "delivered": 0, "failed": 0,
        "created_at": now_iso(),
        "created_by": user.get("email"),
        "started_at": None,
        "finished_at": None,
    }
    await db.mass_campaigns.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/campaigns/{cid_id}")
async def get_campaign(cid_id: str,
                       user: dict = Depends(require_role("administrador", "gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    c = await db.mass_campaigns.find_one(
        {"id": cid_id, "company_id": cid}, {"_id": 0},
    )
    if not c:
        raise HTTPException(404, "Campanha não encontrada")
    return c


@router.delete("/campaigns/{cid_id}")
async def delete_campaign(cid_id: str,
                          user: dict = Depends(require_role("administrador"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    c = await db.mass_campaigns.find_one({"id": cid_id, "company_id": cid})
    if not c:
        raise HTTPException(404, "Campanha não encontrada")
    if c.get("status") == "running":
        raise HTTPException(400, "Pause a campanha antes de excluir")
    await db.mass_campaigns.delete_one({"id": cid_id, "company_id": cid})
    await db.mass_recipients.delete_many({"campaign_id": cid_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# CSV upload + dry-run preview
# ---------------------------------------------------------------------------
@router.post("/campaigns/{cid_id}/recipients/upload")
async def upload_recipients(cid_id: str,
                            file: UploadFile = File(...),
                            user: dict = Depends(require_role("administrador", "gestor"))):
    """CSV com headers: phone, name (opcional), e quaisquer variáveis."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    camp = await db.mass_campaigns.find_one(
        {"id": cid_id, "company_id": cid}, {"_id": 0},
    )
    if not camp:
        raise HTTPException(404, "Campanha não encontrada")
    if camp.get("status") in ("running", "done"):
        raise HTTPException(400, "Campanha já está em execução / concluída")

    raw = await file.read()
    text = raw.decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    if "phone" not in [h.lower() for h in headers]:
        raise HTTPException(400, "CSV precisa ter coluna 'phone'")
    # Limpa destinatários antigos
    await db.mass_recipients.delete_many({"campaign_id": cid_id})
    inserted = 0
    invalid = 0
    bulk = []
    for row in reader:
        # normaliza keys lowercase
        row_lc = {k.lower(): (v or "").strip() for k, v in row.items() if k}
        phone = _normalize_phone(row_lc.get("phone", ""))
        if not phone:
            invalid += 1
            continue
        vars_: Dict[str, str] = {}
        # Variáveis: tudo que não for phone, name vira variável numerada
        # ou pelo próprio header como nome
        for k, v in row_lc.items():
            if k == "phone":
                continue
            vars_[k] = v
        bulk.append({
            "id": f"rec-{uuid.uuid4().hex[:10]}",
            "campaign_id": cid_id,
            "company_id": cid,
            "phone": phone,
            "name": row_lc.get("name", ""),
            "vars": vars_,
            "status": "queued",
            "message_id": None,
            "error": None,
            "queued_at": now_iso(),
            "sent_at": None,
        })
        if len(bulk) >= 500:
            await db.mass_recipients.insert_many(bulk)
            inserted += len(bulk)
            bulk = []
    if bulk:
        await db.mass_recipients.insert_many(bulk)
        inserted += len(bulk)

    await db.mass_campaigns.update_one(
        {"id": cid_id, "company_id": cid},
        {"$set": {
            "csv_headers": headers,
            "total_recipients": inserted,
            "updated_at": now_iso(),
        }},
    )
    return {"inserted": inserted, "invalid": invalid, "headers": headers}


@router.get("/campaigns/{cid_id}/preview")
async def preview_message(cid_id: str,
                          user: dict = Depends(require_role("administrador", "gestor"))):
    """Retorna 3 amostras renderizadas com vars substituídas."""
    cid = user.get("company_id") or DEMO_COMPANY_ID
    camp = await db.mass_campaigns.find_one(
        {"id": cid_id, "company_id": cid}, {"_id": 0},
    )
    if not camp:
        raise HTTPException(404, "Campanha não encontrada")
    cur = db.mass_recipients.find(
        {"campaign_id": cid_id}, {"_id": 0, "phone": 1, "vars": 1, "name": 1},
    ).limit(3)
    samples = []
    text = camp.get("text") or ""
    async for r in cur:
        rendered = _render_template(text, r.get("vars") or {})
        samples.append({
            "phone": r["phone"], "name": r.get("name"),
            "vars": r.get("vars"),
            "rendered_text": rendered,
        })
    return {
        "mode": camp.get("mode"),
        "channel": camp.get("channel"),
        "template_name": camp.get("template_name"),
        "samples": samples,
    }


@router.get("/campaigns/{cid_id}/recipients")
async def list_recipients(cid_id: str,
                          status: Optional[str] = None,
                          limit: int = 500,
                          user: dict = Depends(require_role("administrador", "gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    q: Dict[str, Any] = {"campaign_id": cid_id, "company_id": cid}
    if status:
        q["status"] = status
    cur = db.mass_recipients.find(q, {"_id": 0}).limit(min(limit, 5000))
    return [doc async for doc in cur]


# ---------------------------------------------------------------------------
# Start / Pause / Cancel
# ---------------------------------------------------------------------------
@router.post("/campaigns/{cid_id}/start")
@limiter.limit(get_limit("mass_start"))
async def start_campaign(cid_id: str,
                         request: Request,
                         payload: CampaignStartPayload = Body(default_factory=CampaignStartPayload),
                         user: dict = Depends(require_role("administrador", "gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    camp = await db.mass_campaigns.find_one(
        {"id": cid_id, "company_id": cid}, {"_id": 0},
    )
    if not camp:
        raise HTTPException(404, "Campanha não encontrada")
    if camp.get("total_recipients", 0) == 0:
        raise HTTPException(400, "Faça upload do CSV antes de iniciar")
    if camp.get("status") in ("running",):
        return {"ok": True, "status": "running"}
    new_status = "queued" if (camp.get("schedule_at") and not payload.force_now) else "running"
    await db.mass_campaigns.update_one(
        {"id": cid_id, "company_id": cid},
        {"$set": {
            "status": new_status,
            "started_at": now_iso() if new_status == "running" else None,
            "updated_at": now_iso(),
        }},
    )
    return {"ok": True, "status": new_status}


@router.post("/campaigns/{cid_id}/pause")
async def pause_campaign(cid_id: str,
                         user: dict = Depends(require_role("administrador", "gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    r = await db.mass_campaigns.update_one(
        {"id": cid_id, "company_id": cid, "status": {"$in": ["running", "queued"]}},
        {"$set": {"status": "paused", "updated_at": now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(400, "Campanha não está em execução")
    return {"ok": True}


@router.post("/campaigns/{cid_id}/resume")
async def resume_campaign(cid_id: str,
                          user: dict = Depends(require_role("administrador", "gestor"))):
    cid = user.get("company_id") or DEMO_COMPANY_ID
    r = await db.mass_campaigns.update_one(
        {"id": cid_id, "company_id": cid, "status": "paused"},
        {"$set": {"status": "running", "updated_at": now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(400, "Campanha não está pausada")
    return {"ok": True}


# ===========================================================================
# Worker — processa filas
# ===========================================================================
_worker_task: Optional[asyncio.Task] = None


async def _send_one(camp: Dict[str, Any], rec: Dict[str, Any]) -> Dict[str, Any]:
    """Envia uma mensagem para um destinatário. Retorna dict com ok/error."""
    text = _render_template(camp.get("text") or "", rec.get("vars") or {})
    channel = camp.get("channel")
    try:
        if channel == "twilio":
            from routes.whatsapp_twilio import send_via_twilio
            res = await send_via_twilio(camp["company_id"], rec["phone"], text)
            if res.get("ok"):
                return {"ok": True, "message_id": res.get("message_sid")}
            return {"ok": False, "error": res.get("error") or "twilio_error"}
        if channel == "baileys":
            return await _send_baileys(camp, rec, text)
        # meta_cloud
        return await _send_meta_cloud(camp, rec, text)
    except Exception as e:
        logger.exception("[mass] send falhou")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}


async def _send_baileys(camp: Dict[str, Any], rec: Dict[str, Any],
                          text: str) -> Dict[str, Any]:
    """Envia via sidecar Baileys (WhatsApp Web) — POST sidecar:/send.

    Funciona apenas em modo `free` (texto livre). Templates HSM não se aplicam
    ao Baileys. Após envio com sucesso, persiste no `aihub_wa_messages` para
    a mensagem aparecer no histórico da Isabella (mesma collection).

    Resolve o canal outbound na seguinte ordem de prioridade:
      1. `camp["channel_id"]` — override explícito da campanha (escolha do admin)
      2. `get_default_outbound_channel(cid)` — canal default da empresa
      3. fallback canal-1 (SIDECAR_BASE / port 3002)
    """
    import httpx
    import uuid as _uuid
    from routes.whatsapp_baileys import SIDECAR_BASE  # reuse base URL
    from services.whatsapp_channels import (
        base_url_for, get_default_outbound_channel,
    )
    cid = camp["company_id"]
    phone = rec["phone"]

    # Resolve qual canal vai enviar
    channel_id = camp.get("channel_id")
    try:
        if not channel_id:
            channel_id = await get_default_outbound_channel(db, cid)
        base_url = base_url_for(channel_id)
    except Exception:
        base_url = SIDECAR_BASE
        channel_id = "channel-1"

    try:
        async with httpx.AsyncClient(timeout=25.0) as cli:
            r = await cli.post(
                f"{base_url.rstrip('/')}/send",
                json={"phone": phone, "text": text[:4096]},
            )
            try:
                payload = r.json()
            except Exception:
                payload = {"raw": r.text}
            if r.status_code >= 400 or not payload.get("ok"):
                return {"ok": False,
                        "error": (payload.get("error")
                                  or f"HTTP {r.status_code}")[:300]}
            msg_id = payload.get("message_id")
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"baileys_sidecar: {e}"[:300]}

    # Persiste no histórico (mesma collection usada pelo chat manual)
    try:
        await db.aihub_wa_messages.insert_one({
            "id": f"wam-{_uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "direction": "outbound",
            "phone": phone,
            "text": text,
            "channel": "baileys",
            "channel_id": channel_id,
            "message_id": msg_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "actor_user": "disparo_ia",
            "auto_reply": False,
            "delivery_status": "sent",
            "campaign_id": camp.get("id"),
            "campaign_origin": camp.get("origin"),
        })
    except Exception as e:
        logger.info("[mass] baileys hist persist skip: %s", e)

    return {"ok": True, "message_id": msg_id, "channel_id": channel_id}


async def _send_meta_cloud(camp: Dict[str, Any], rec: Dict[str, Any],
                            text: str) -> Dict[str, Any]:
    """Envia via Meta WhatsApp Cloud API. Suporta template ou texto livre."""
    import httpx
    creds = await db.whatsapp_meta_creds.find_one(
        {"company_id": camp["company_id"]}, {"_id": 0},
    )
    if not creds or not creds.get("wa_access_token"):
        return {"ok": False, "error": "Meta WhatsApp Cloud não configurado"}
    token = creds["wa_access_token"]
    phone_number_id = creds.get("wa_phone_number_id")
    if not phone_number_id:
        return {"ok": False, "error": "wa_phone_number_id ausente"}

    url = f"https://graph.facebook.com/v25.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json"}
    to = rec["phone"]

    if camp.get("mode") == "template":
        body: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": camp.get("template_name"),
                "language": {"code": camp.get("template_language") or "pt_BR"},
            },
        }
        comps = camp.get("template_components")
        if comps:
            body["template"]["components"] = comps
        else:
            # auto-build: variáveis viram parameters body
            vars_ = rec.get("vars") or {}
            params = [{"type": "text", "text": str(v)} for v in vars_.values()]
            if params:
                body["template"]["components"] = [
                    {"type": "body", "parameters": params},
                ]
    else:
        body = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text[:4096]},
        }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(url, headers=headers, json=body)
            if r.status_code >= 400:
                try:
                    err = (r.json().get("error") or {}).get("message") or r.text
                except Exception:
                    err = r.text
                return {"ok": False, "error": str(err)[:300]}
            data = r.json()
            msgs = data.get("messages") or []
            mid = msgs[0].get("id") if msgs else None
            return {"ok": True, "message_id": mid}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


async def _process_campaign(camp: Dict[str, Any]) -> int:
    """Processa 1 campanha — envia um burst respeitando throttle."""
    cid_id = camp["id"]
    cid = camp["company_id"]
    throttle = max(1, int(camp.get("throttle_per_min") or 60))
    # quantos pode mandar em 1 tick (5s)? throttle/60 * 5
    burst = max(1, throttle * 5 // 60)
    cur = db.mass_recipients.find(
        {"campaign_id": cid_id, "status": "queued"}, {"_id": 0},
    ).limit(burst)
    recs = [doc async for doc in cur]
    if not recs:
        # Verifica se todos terminaram
        remaining = await db.mass_recipients.count_documents(
            {"campaign_id": cid_id, "status": {"$in": ["queued", "sending"]}},
        )
        if remaining == 0:
            await db.mass_campaigns.update_one(
                {"id": cid_id},
                {"$set": {"status": "done", "finished_at": now_iso(),
                          "updated_at": now_iso()}},
            )
        return 0

    sent_inc = 0
    failed_inc = 0
    for rec in recs:
        await db.mass_recipients.update_one(
            {"id": rec["id"]}, {"$set": {"status": "sending"}},
        )
        result = await _send_one(camp, rec)
        if result.get("ok"):
            sent_inc += 1
            await db.mass_recipients.update_one(
                {"id": rec["id"]},
                {"$set": {
                    "status": "sent",
                    "message_id": result.get("message_id"),
                    "sent_at": now_iso(), "error": None,
                }},
            )
        else:
            failed_inc += 1
            await db.mass_recipients.update_one(
                {"id": rec["id"]},
                {"$set": {
                    "status": "failed",
                    "error": result.get("error"),
                    "sent_at": now_iso(),
                }},
            )
    await db.mass_campaigns.update_one(
        {"id": cid_id, "company_id": cid},
        {"$inc": {"sent": sent_inc, "failed": failed_inc},
         "$set": {"updated_at": now_iso()}},
    )
    return len(recs)


async def _worker_loop() -> None:
    """Loop principal — tick a cada 5s, processa todas campanhas running."""
    logger.info("[mass-messaging] worker iniciado")
    while True:
        try:
            # Promove campaigns agendadas que já passaram do schedule_at
            now_iso_str = now_iso()
            await db.mass_campaigns.update_many(
                {"status": "queued",
                 "schedule_at": {"$lte": now_iso_str, "$ne": None}},
                {"$set": {"status": "running", "started_at": now_iso_str,
                          "updated_at": now_iso_str}},
            )
            cur = db.mass_campaigns.find({"status": "running"}, {"_id": 0})
            campaigns = [c async for c in cur]
            for camp in campaigns:
                try:
                    await _process_campaign(camp)
                except Exception as e:
                    logger.exception("[mass] process_campaign falhou: %s", e)
        except Exception as e:
            logger.exception("[mass] loop falhou: %s", e)
        await asyncio.sleep(5)


def start_worker() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_worker_loop())


def stop_worker() -> None:
    global _worker_task
    if _worker_task:
        _worker_task.cancel()
        _worker_task = None
