"""Proactive Alerts — sistema avisa o gestor por WhatsApp em eventos críticos
e aguarda decisão dele (sim/não/cancela).

Fluxo:
  1. Worker (SmartOLT, Sentinela, etc) chama `notify_outage(cid, outage)`
  2. Mensagem com pergunta é enviada via sidecar Baileys ao gestor da whitelist
  3. Estado é persistido em `manager_assistant_pending` com TTL 30min
  4. Quando o gestor responde, `manager_assistant.py` consulta pending e executa
     a ação correspondente (broadcast, ignore, etc).

Ações suportadas:
  - "outage_broadcast": envia aviso pré-aprovado para todos os clientes da OLT afetada
  - "outage_ignore":    apenas marca como visualizado, sem ação adicional
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from core import now_iso
from database import db

logger = logging.getLogger("proactive_alerts")

SIDECAR_BASE = os.environ.get("WHATSAPP_SIDECAR_BASE", "http://127.0.0.1:3002")
PENDING_TTL_MINUTES = 30
COOLDOWN_OUTAGE_MINUTES = 30   # não reavisar do mesmo outage por 30min


# ---------------------------------------------------------------------------
# Whitelist & envio
# ---------------------------------------------------------------------------
async def _gather_manager_phones(company_id: str) -> List[str]:
    """Mesma lógica que `manager_assistant._is_manager_phone`, mas devolve
    a lista para envio em broadcast aos gestores."""
    phones: List[str] = []
    sched = await db.churn_briefing_schedule.find_one(
        {"company_id": company_id}, {"_id": 0, "notify_phone": 1})
    if sched and sched.get("notify_phone"):
        ph = re.sub(r"\D", "", sched["notify_phone"])
        if ph:
            phones.append(ph)
    async for d in db.manager_assistant_phones.find(
            {"company_id": company_id, "enabled": True},
            {"_id": 0, "phone": 1}):
        ph = re.sub(r"\D", "", d.get("phone") or "")
        if ph and ph not in phones:
            phones.append(ph)
    return phones


async def _send_to_manager(phone: str, text: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(f"{SIDECAR_BASE}/send",
                                 json={"phone": phone, "text": text})
            data = {}
            try:
                data = r.json()
            except Exception:
                pass
            return r.status_code < 400 and bool(data.get("ok"))
    except Exception as e:
        logger.warning("[proactive] WA send falhou: %s", e)
        return False


# ---------------------------------------------------------------------------
# Pending action storage
# ---------------------------------------------------------------------------
async def _save_pending(company_id: str, phone: str, kind: str,
                          payload: Dict[str, Any]) -> str:
    pid = f"pa-{uuid.uuid4().hex[:10]}"
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=PENDING_TTL_MINUTES)).isoformat()
    await db.manager_assistant_pending.insert_one({
        "id": pid,
        "company_id": company_id,
        "phone": phone,
        "kind": kind,
        "payload": payload,
        "created_at": now_iso(),
        "expires_at": expires_at,
        "resolved": False,
    })
    return pid


async def get_active_pending(company_id: str, phone: str) -> Optional[Dict[str, Any]]:
    """Retorna a pending action mais recente ainda válida pra esse telefone."""
    now = datetime.now(timezone.utc).isoformat()
    doc = await db.manager_assistant_pending.find_one(
        {"company_id": company_id, "phone": phone,
         "resolved": False, "expires_at": {"$gt": now}},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    return doc


async def resolve_pending(pending_id: str, decision: str,
                            executed_summary: Optional[str] = None) -> None:
    await db.manager_assistant_pending.update_one(
        {"id": pending_id},
        {"$set": {
            "resolved": True,
            "decision": decision,
            "executed_summary": executed_summary,
            "resolved_at": now_iso(),
        }},
    )


# ---------------------------------------------------------------------------
# Public API — disparado pelos workers
# ---------------------------------------------------------------------------
async def notify_outage(company_id: str, outage: Dict[str, Any]) -> Optional[str]:
    """Avisa o gestor sobre nova pane SmartOLT e pergunta se quer abrir
    aviso em massa. Idempotente: usa `outage_proactive_notified` no doc."""
    # Anti-flood: se já avisamos sobre esse outage em janela COOLDOWN, ignora
    cooldown_cut = (datetime.now(timezone.utc)
                      - timedelta(minutes=COOLDOWN_OUTAGE_MINUTES)).isoformat()
    already = await db.network_outages.find_one(
        {"company_id": company_id, "key": outage.get("key"),
         "proactive_notified_at": {"$gt": cooldown_cut}},
        {"_id": 0, "id": 1},
    )
    if already:
        return None

    phones = await _gather_manager_phones(company_id)
    if not phones:
        return None

    affected = len(outage.get("affected_phones") or [])
    olt = outage.get("olt_name") or "—"
    sev = outage.get("severity_pct") or 0
    los = outage.get("los_count") or 0
    total = outage.get("total_count") or 0
    insight = (outage.get("ai_insight") or {}).get("summary") or ""

    text = (
        f"🚨 *Pane detectada — {olt}*\n"
        f"_(SmartOLT AI · {sev}% das ONUs offline)_\n\n"
        f"• {los}/{total} ONUs em LOS\n"
        f"• {affected} cliente(s) afetado(s) com telefone cadastrado\n"
        + (f"• Análise IA: {insight}\n" if insight else "")
        + "\n*Quer que eu avise os clientes afetados por WhatsApp?*\n"
        "Responda *sim* para enviar aviso em massa, ou *não* para ignorar."
    )

    delivered = []
    pending_ids = []
    for ph in phones:
        ok = await _send_to_manager(ph, text)
        if not ok:
            continue
        pid = await _save_pending(
            company_id, ph,
            kind="outage_broadcast",
            payload={
                "outage_id": outage.get("id"),
                "outage_key": outage.get("key"),
                "olt_name": olt,
                "affected_phones": list(outage.get("affected_phones") or [])[:200],
            },
        )
        pending_ids.append(pid)
        delivered.append(ph)

    if delivered:
        await db.network_outages.update_one(
            {"id": outage.get("id")},
            {"$set": {"proactive_notified_at": now_iso(),
                       "proactive_pending_ids": pending_ids,
                       "proactive_notified_phones": delivered}},
        )
        logger.warning(
            "[proactive] outage %s — gestor(es) notificado(s): %d",
            outage.get("id"), len(delivered))
        return delivered[0]
    return None


# ---------------------------------------------------------------------------
# Execução de pending (chamado pelo manager_assistant ao receber sim/não)
# ---------------------------------------------------------------------------
async def execute_pending(company_id: str, pending: Dict[str, Any],
                            decision_text: str) -> str:
    """Executa a ação pendente baseada na decisão do gestor.

    `decision_text` é a mensagem original (sim/não/etc).
    Retorna texto de confirmação a ser enviado ao gestor."""
    s = (decision_text or "").strip().lower()
    yes = re.search(r"\b(sim|yes|ok|confirma|envia|manda|aprovo|pode|vai)\b", s)
    no = re.search(r"\b(n[ãa]o|nao|nope|cancela|ignora|deixa|abort)", s)

    if no and not yes:
        await resolve_pending(pending["id"], decision="rejected")
        return "👍 Ok, ignorando esse alerta."

    if not yes:
        # Mensagem ambígua — não consumimos o pending
        return ("Para confirmar essa ação, responda exatamente *sim* ou *não*. "
                  "Ela expira em 30 min.")

    # SIM — executa
    kind = pending.get("kind")
    payload = pending.get("payload") or {}
    if kind == "outage_broadcast":
        sent_count = await _execute_outage_broadcast(company_id, payload)
        summary = f"Aviso enviado para {sent_count} cliente(s)"
        await resolve_pending(pending["id"], decision="approved",
                                executed_summary=summary)
        return f"✅ {summary}. Detalhes em Central IA → SmartOLT."
    if kind == "outage_ignore":
        await resolve_pending(pending["id"], decision="approved")
        return "✅ Marcado como visualizado."

    await resolve_pending(pending["id"], decision="approved")
    return "✅ Confirmado."


async def _execute_outage_broadcast(company_id: str,
                                       payload: Dict[str, Any]) -> int:
    """Envia mensagem padrão pra todos os telefones afetados pelo outage."""
    phones = payload.get("affected_phones") or []
    olt = payload.get("olt_name") or "região"
    if not phones:
        return 0
    text = (
        f"⚠️ Olá! Identificamos uma instabilidade na sua região ({olt}) e "
        f"nossa equipe técnica já está atuando para restabelecer o serviço "
        f"o mais rápido possível.\n\nAgradecemos a paciência e pedimos "
        f"desculpas pelo transtorno."
    )
    sent = 0
    # Envia em lote — sidecar tem rate limit interno (1.2s entre envios)
    for ph in phones:
        try:
            async with httpx.AsyncClient(timeout=8.0) as cli:
                r = await cli.post(f"{SIDECAR_BASE}/send",
                                     json={"phone": ph, "text": text})
                if r.status_code < 400:
                    sent += 1
        except Exception:
            pass
    logger.warning(
        "[proactive] outage broadcast enviado: %d/%d clientes — OLT %s",
        sent, len(phones), olt)
    return sent
