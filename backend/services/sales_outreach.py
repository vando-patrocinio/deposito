"""sales_outreach.py — Worker Isabella IA proativa pra leads de Wi-Fi self-service.

Quando o Álvaro IA detecta cliente não-Premium pedindo troca de Wi-Fi, ele
emite o marker [OFFER_UPGRADE] que cria um lead em `sales_leads` com
`source='whatsapp_alvaro_wifi_request'` e `status='new'`.

Este worker (rodando em background no event loop do FastAPI) pega esses
leads NOVOS, dispara uma mensagem-template de upsell via WhatsApp (Isabella
IA) e marca o lead como `contacted`. A partir daí, o handoff conversacional
já existente (`[ROTEAR_VENDAS]`) toma conta da negociação.

Critérios pra disparo:
  - status='new'
  - source='whatsapp_alvaro_wifi_request'
  - age <= 24h (lead fresco — depois disso vira "stale" pra revisão humana)
  - cooldown: 1 disparo por phone a cada 7 dias
  - rate-limit global: 50 disparos/hora (anti-spam reputation)
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "vendas-team",
    "domain": "comercial",
    "criticality": "high",
    "emits_events": True,
    "event_types": ["wa.message.persisted"],
    "company_id_required": True,
}

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from core import now_iso
from database import db

log = logging.getLogger("ponto.sales_outreach")

# Tunables
POLL_INTERVAL_SECONDS = 60        # checa a cada 1min
MAX_LEAD_AGE_HOURS = 24
COOLDOWN_PER_PHONE_DAYS = 7
GLOBAL_RATE_LIMIT_PER_HOUR = 50
ISABELLA_AGENT_NAME = "Isabella"  # Match com o agente de Vendas existente

# Copy do upsell (premium speeds 1G/2G/5G)
ISABELLA_OUTREACH_TEMPLATE = (
    "Oi! Sou a Isabella, da equipe de Vendas. 👋\n\n"
    "Vi que você gostaria de trocar a senha do seu Wi-Fi pelo WhatsApp — "
    "esse é um benefício *exclusivo* dos nossos planos Premium:\n\n"
    "🚀 *1000 Mega* — ideal pra família conectada\n"
    "🚀 *2000 Mega* — pra streaming 4K, gaming e home office\n"
    "🚀 *5000 Mega* — performance máxima, sem limite\n\n"
    "Com qualquer um deles você:\n"
    "✅ Troca a senha do Wi-Fi pelo próprio WhatsApp em segundos\n"
    "✅ Faz speed test direto pelo chat\n"
    "✅ Tem suporte com prioridade\n\n"
    "Posso te ajudar a fazer o upgrade agora? "
    "Me responde com a velocidade que faz mais sentido pra você 😊"
)


async def _global_rate_ok() -> bool:
    """Checa se ultrapassamos 50 disparos/hora."""
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    n = await db.sales_leads.count_documents({
        "outreach_sent_at": {"$gte": since},
    })
    return n < GLOBAL_RATE_LIMIT_PER_HOUR


async def _phone_in_cooldown(phone: str) -> bool:
    """Checa se phone já recebeu outreach nos últimos 7 dias."""
    cutoff = (datetime.now(timezone.utc)
               - timedelta(days=COOLDOWN_PER_PHONE_DAYS)).isoformat()
    n = await db.sales_leads.count_documents({
        "phone": phone,
        "outreach_sent_at": {"$gte": cutoff},
    })
    return n > 0


async def _send_via_sidecar(phone: str, text: str,
                              cid: Optional[str] = None) -> Optional[dict]:
    """Envia mensagem via sidecar Baileys do canal padrão outbound da empresa.

    Resolve o canal via `whatsapp_channels.get_default_outbound_channel(cid)`;
    se cid não for fornecido (compat), cai no canal-1.
    """
    from services.wa.sidecar import _sidecar_headers, SIDECAR_BASE
    from services.whatsapp_channels import (
        base_url_for, get_default_outbound_channel,
    )
    base_url = SIDECAR_BASE
    if cid:
        try:
            from database import db as _db
            ch_id = await get_default_outbound_channel(_db, cid)
            base_url = base_url_for(ch_id)
        except Exception as e:
            log.warning("[sales_outreach] channel resolve failed: %s", e)
    try:
        async with httpx.AsyncClient(headers=_sidecar_headers(),
                                       timeout=20.0) as cli:
            r = await cli.post(f"{base_url.rstrip('/')}/send",
                                 json={"phone": phone, "text": text})
            if r.status_code >= 400:
                log.warning("[sales_outreach] sidecar HTTP %s: %s",
                              r.status_code, r.text[:200])
                return None
            data = r.json()
            if not data.get("ok"):
                log.warning("[sales_outreach] sidecar !ok: %s",
                              data.get("error"))
                return None
            return data
    except Exception as e:
        log.warning("[sales_outreach] sidecar exc: %s", e)
        return None


async def _persist_outbound(cid: str, phone: str, text: str,
                             lead_id: str,
                             subscriber_id: Optional[str],
                             send_resp: dict) -> None:
    """Grava bolha outbound no histórico de chat."""
    import uuid
    try:
        await db.aihub_wa_messages.insert_one({
            "id": f"wam-{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "direction": "outbound",
            "phone": phone,
            "text": text,
            "channel": "baileys",
            "message_id": send_resp.get("message_id"),
            "subscriber_id": subscriber_id,
            "agent_name": ISABELLA_AGENT_NAME,
            "session_id": f"wa-{phone}",
            "auto_reply": True,
            "delivery_status": "sent",
            "metadata": {"source": "sales_outreach_worker",
                          "lead_id": lead_id,
                          "campaign": "wifi_self_service_upsell"},
            "created_at": now_iso(),
        })
        try:
            from services.event_bus import emit_event
            await emit_event(
                "wa.message.persisted",
                company_id=cid,
                source="sales_outreach",
                payload={},
            )
        except Exception:
            pass
    except Exception as e:
        log.warning("[sales_outreach] persist_outbound fail: %s", e)


async def process_pending_leads() -> dict:
    """Processa todos os leads new pendentes. Retorna stats.

    Pode ser chamado em loop (worker) ou manualmente via endpoint admin.
    """
    cutoff_old = (datetime.now(timezone.utc)
                   - timedelta(hours=MAX_LEAD_AGE_HOURS)).isoformat()
    stats = {"checked": 0, "sent": 0, "skipped_cooldown": 0,
              "skipped_rate_limit": 0, "skipped_no_phone": 0,
              "errors": 0, "stale_marked": 0}
    # Marca leads antigos como stale (pra fila humana revisar)
    stale_res = await db.sales_leads.update_many(
        {"status": "new",
         "source": "whatsapp_alvaro_wifi_request",
         "ts": {"$lt": cutoff_old}},
        {"$set": {"status": "stale_needs_human_review",
                   "updated_at": now_iso()}},
    )
    stats["stale_marked"] = stale_res.modified_count
    cur = db.sales_leads.find(
        {"status": "new",
         "source": "whatsapp_alvaro_wifi_request",
         "ts": {"$gte": cutoff_old}},
        {"_id": 0},
    ).sort("ts", 1).limit(GLOBAL_RATE_LIMIT_PER_HOUR)
    async for lead in cur:
        stats["checked"] += 1
        phone = lead.get("phone")
        if not phone:
            stats["skipped_no_phone"] += 1
            await db.sales_leads.update_one(
                {"id": lead["id"]},
                {"$set": {"status": "invalid_no_phone",
                          "updated_at": now_iso()}},
            )
            continue
        if not await _global_rate_ok():
            stats["skipped_rate_limit"] += 1
            break  # já bateu o teto da hora, para o resto pra próxima iteração
        if await _phone_in_cooldown(phone):
            stats["skipped_cooldown"] += 1
            await db.sales_leads.update_one(
                {"id": lead["id"]},
                {"$set": {"status": "deduplicated_cooldown",
                          "updated_at": now_iso()}},
            )
            continue
        # Personaliza com nome do subscriber se tiver
        name = lead.get("subscriber_name")
        text = ISABELLA_OUTREACH_TEMPLATE
        if name:
            first = name.split()[0]
            text = text.replace("Oi!", f"Oi {first}!", 1)
        send_resp = await _send_via_sidecar(phone, text,
                                              cid=lead.get("company_id"))
        if not send_resp:
            stats["errors"] += 1
            await db.sales_leads.update_one(
                {"id": lead["id"]},
                {"$set": {"status": "send_failed",
                          "outreach_attempted_at": now_iso(),
                          "updated_at": now_iso()}},
                upsert=False,
            )
            continue
        # Sucesso — marca contacted + persiste bolha
        await db.sales_leads.update_one(
            {"id": lead["id"]},
            {"$set": {"status": "contacted",
                      "outreach_sent_at": now_iso(),
                      "outreach_message_id": send_resp.get("message_id"),
                      "updated_at": now_iso()}},
        )
        await _persist_outbound(
            lead.get("company_id"), phone, text, lead["id"],
            lead.get("subscriber_id"), send_resp,
        )
        stats["sent"] += 1
    return stats


# ---------------------------------------------------------------------------
# Background worker — roda no event loop do FastAPI
# ---------------------------------------------------------------------------
_worker_task: Optional[asyncio.Task] = None
_worker_running = False


async def _worker_loop() -> None:
    global _worker_running
    _worker_running = True
    log.info("[sales_outreach] worker iniciado (poll=%ss)",
                POLL_INTERVAL_SECONDS)
    while _worker_running:
        try:
            stats = await process_pending_leads()
            if stats["checked"] > 0:
                log.info("[sales_outreach] tick: %s", stats)
        except Exception as e:
            log.exception("[sales_outreach] tick falhou: %s", e)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
    log.info("[sales_outreach] worker parado")


async def start_worker() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_worker_loop())


async def stop_worker() -> None:
    global _worker_running, _worker_task
    _worker_running = False
    if _worker_task:
        try:
            await asyncio.wait_for(_worker_task, timeout=5.0)
        except Exception:
            pass
        _worker_task = None


# ---------------------------------------------------------------------------
# Compromisso conversacional: confirmação 2min após troca de Wi-Fi
# ---------------------------------------------------------------------------
WIFI_CONFIRM_DELAY_SECONDS = 120

WIFI_CONFIRM_TEMPLATE = (
    "✅ *Lembrete da sua nova senha do Wi-Fi*\n\n"
    "Olá {first_name}! Confirmando a troca que fizemos juntos:\n\n"
    "📡 *Nome da rede (SSID):* {ssid}\n"
    "🔑 *Senha:* `{password}`\n\n"
    "*Salve esta mensagem* — assim você sempre tem a senha à mão. "
    "Se algum aparelho não conectar, conecte de novo usando os "
    "dados acima. 😊\n\n"
    "_Qualquer coisa, é só me chamar!_"
)


async def schedule_wifi_confirmation(
        cid: str, phone: str, subscriber_name: Optional[str],
        ssid: str, password: str,
        delay_seconds: int = WIFI_CONFIRM_DELAY_SECONDS) -> asyncio.Task:
    """Agenda mensagem-resumo 2min após troca de Wi-Fi (WhatsApp).

    Cria um asyncio.Task que dorme + envia. Best-effort: se sidecar falhar
    ou o processo reiniciar, a mensagem se perde (aceitável pro use-case;
    pra garantia hard precisaria de Celery/Redis).
    """
    async def _send_later():
        try:
            await asyncio.sleep(delay_seconds)
            first = (subscriber_name or "").split()[0] if subscriber_name \
                else "amigo(a)"
            text = WIFI_CONFIRM_TEMPLATE.format(
                first_name=first, ssid=ssid, password=password)
            send_resp = await _send_via_sidecar(phone, text, cid=cid)
            if not send_resp:
                log.warning(
                    "[sales_outreach] confirm wifi send failed phone=%s",
                    phone)
                return
            # Grava bolha outbound
            import uuid
            try:
                await db.aihub_wa_messages.insert_one({
                    "id": f"wam-{uuid.uuid4().hex[:10]}",
                    "company_id": cid,
                    "direction": "outbound",
                    "phone": phone,
                    "text": text,
                    "channel": "baileys",
                    "message_id": send_resp.get("message_id"),
                    "agent_name": "Alvaro",
                    "session_id": f"wa-{phone}",
                    "auto_reply": True,
                    "delivery_status": "sent",
                    "metadata": {"source": "wifi_confirmation_reminder"},
                    "created_at": now_iso(),
                })
                try:
                    from services.event_bus import emit_event
                    await emit_event(
                        "wa.message.persisted",
                        company_id=cid,
                        source="sales_outreach",
                        payload={},
                    )
                except Exception:
                    pass
            except Exception as e:
                log.warning("[sales_outreach] confirm persist fail: %s", e)
            log.info("[sales_outreach] confirm wifi sent phone=%s ssid=%s",
                        phone, ssid)
        except Exception as e:
            log.warning("[sales_outreach] confirm wifi err: %s", e)
    return asyncio.create_task(_send_later())


# ---------------------------------------------------------------------------
# Conversão automática de leads Wi-Fi self-service
# ---------------------------------------------------------------------------
async def maybe_convert_leads_after_plan_change(
        cid: str, subscriber_id: str, new_plan_id: str,
        old_plan_id: Optional[str] = None) -> int:
    """Marca leads do funil Wi-Fi self-service como `converted` quando o
    subscriber muda pra um plano Premium (premium_features inclui
    wifi_self_service).

    Idempotente — só converte leads em estado `new`, `contacted` ou
    `send_failed` do mesmo subscriber/phone.

    Retorna a quantidade de leads convertidos.
    """
    if not new_plan_id or new_plan_id == old_plan_id:
        return 0
    # Verifica se novo plano é Premium
    plan = await db.plans.find_one(
        {"id": new_plan_id, "company_id": cid},
        {"_id": 0, "premium_features": 1},
    )
    if not plan:
        return 0
    feats = set(plan.get("premium_features") or [])
    if "wifi_self_service" not in feats:
        return 0
    # Encontra leads vinculados a esse subscriber OU aos phones dele
    phones = await db.subscriber_phones.find(
        {"subscriber_id": subscriber_id, "company_id": cid},
        {"_id": 0, "raw_number": 1, "normalized_number": 1},
    ).to_list(20)
    phone_set = set()
    for p in phones:
        for k in ("raw_number", "normalized_number"):
            if p.get(k):
                phone_set.add(p[k])
    # Filtro: leads do funil wifi nos estados pré-conversão
    q = {
        "company_id": cid,
        "source": "whatsapp_alvaro_wifi_request",
        "status": {"$in": ["new", "contacted", "send_failed",
                            "deduplicated_cooldown",
                            "stale_needs_human_review"]},
        "$or": [
            {"subscriber_id": subscriber_id},
        ],
    }
    if phone_set:
        q["$or"].append({"phone": {"$in": list(phone_set)}})
    res = await db.sales_leads.update_many(q, {"$set": {
        "status": "converted",
        "converted_at": now_iso(),
        "converted_to_plan_id": new_plan_id,
        "updated_at": now_iso(),
    }})
    if res.modified_count:
        log.info("[sales_outreach] converted %d leads sid=%s plan=%s",
                    res.modified_count, subscriber_id, new_plan_id)
    return res.modified_count
