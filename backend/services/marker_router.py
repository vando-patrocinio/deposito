"""Marker Router — interpreta markers invisíveis emitidos pela Isabella e
toma ações automáticas no sistema (alerta humano, roteamento, log).

Markers reconhecidos:
  [HOT_LEAD]          → marca conversa como prioritária + alerta vendedor
  [VENDA_AGENDADA]    → score=100, próxima conversa entra como cliente novo
  [ROTEAR_HUMANO]     → tira IA do modo automático, fila humana
  [ROTEAR_SUPORTE]    → cria ticket técnico aberto na Lousa
  [ROTEAR_FINANCEIRO] → notifica Alvaro (financeiro)
  [CHURN_RISK]        → alerta retenção + log destacado

Uso (no whatsapp_baileys.py após gerar resposta da IA):
    from services.marker_router import process_markers
    cleaned_text = await process_markers(text, phone, company_id, conv_id)
    # cleaned_text NÃO tem mais os markers — pode ser enviado ao cliente
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from database import db

log = logging.getLogger("ponto.marker_router")

MARKER_PATTERN = re.compile(
    r"\[(HOT_LEAD|VENDA_AGENDADA|ROTEAR_HUMANO|ROTEAR_SUPORTE|"
    r"ROTEAR_FINANCEIRO|CHURN_RISK)\]",
    re.IGNORECASE,
)


def extract_markers(text: str) -> Tuple[str, List[str]]:
    """Retorna (texto limpo, lista de markers encontrados em UPPERCASE)."""
    if not text:
        return text, []
    found = [m.group(1).upper() for m in MARKER_PATTERN.finditer(text)]
    cleaned = MARKER_PATTERN.sub("", text).strip()
    # remove espaços múltiplos / linhas em branco no fim que sobraram
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).rstrip()
    return cleaned, list(dict.fromkeys(found))  # mantém ordem, sem duplicar


async def process_markers(text: str, phone: str, company_id: str,
                              conv_id: str = None) -> str:
    """Processa markers e retorna texto limpo (sem markers) pra enviar.

    Cada marker dispara ação(ões) específicas em paralelo. Se nenhuma ação
    falhar, o cliente recebe a mensagem normalmente sem ver os colchetes.
    """
    cleaned, markers = extract_markers(text)
    if not markers:
        return cleaned

    now = datetime.now(timezone.utc).isoformat()

    # Log unificado da ação
    audit = {
        "id": f"mrk-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "phone": phone,
        "conv_id": conv_id,
        "markers": markers,
        "raw_text_preview": (text or "")[:300],
        "at": now,
    }
    try:
        await db.marker_router_log.insert_one(audit)
    except Exception as e:
        log.warning("marker log insert failed: %s", e)

    for m in markers:
        try:
            if m == "HOT_LEAD":
                await _on_hot_lead(phone, company_id, now)
            elif m == "VENDA_AGENDADA":
                await _on_sale_agreed(phone, company_id, now)
            elif m == "ROTEAR_HUMANO":
                await _route_human(phone, company_id, now)
            elif m == "ROTEAR_SUPORTE":
                await _route_support(phone, company_id, now)
            elif m == "ROTEAR_FINANCEIRO":
                await _route_finance(phone, company_id, now)
            elif m == "CHURN_RISK":
                await _on_churn_risk(phone, company_id, now)
        except Exception as e:
            log.warning("[marker_router] %s falhou: %s", m, e)

    return cleaned


# ---------------------------------------------------------------------------
# Ações
# ---------------------------------------------------------------------------
async def _set_conv_flags(phone: str, cid: str, flags: Dict) -> None:
    """Helper para marcar flags na conversa WA."""
    await db.wa_conversations.update_one(
        {"company_id": cid, "phone": phone},
        {"$set": flags},
    )


async def _on_hot_lead(phone, cid, now):
    """Marca conversa como hot lead → vai aparecer destacada no Funil."""
    await _set_conv_flags(phone, cid, {
        "is_hot_lead": True, "hot_lead_at": now,
        "priority_until": now,
    })
    log.info("[hot_lead] phone=%s", phone)


async def _on_sale_agreed(phone, cid, now):
    """Venda agendada — marca conversa pra revisão humana de fechamento."""
    await _set_conv_flags(phone, cid, {
        "sale_agreed": True, "sale_agreed_at": now,
        "needs_human_review": True,
    })
    log.info("[sale_agreed] phone=%s — humano precisa confirmar instalação",
              phone)


async def _route_human(phone, cid, now):
    """Tira IA do modo automático e coloca conversa na fila humana."""
    await _set_conv_flags(phone, cid, {
        "ai_paused": True, "ai_paused_at": now,
        "ai_pause_reason": "marker_route_human",
        "routed_to": "humano",
    })
    log.info("[route_human] phone=%s — IA pausada", phone)


async def _route_support(phone, cid, now):
    """Cria ticket de suporte técnico abertinho na Lousa."""
    # Busca subscriber_id da conversa pra anexar
    conv = await db.wa_conversations.find_one(
        {"company_id": cid, "phone": phone},
        {"_id": 0, "subscriber_id": 1, "push_name": 1},
    )
    sub_id = (conv or {}).get("subscriber_id")
    push_name = (conv or {}).get("push_name") or "Cliente WhatsApp"

    # Snapshot básico do cliente
    snap = {"name": push_name, "phone": phone}
    if sub_id:
        sub = await db.subscribers.find_one(
            {"id": sub_id}, {"_id": 0, "name": 1, "address": 1,
                              "neighborhood": 1, "city": 1, "plan_name": 1},
        )
        if sub:
            snap.update({
                "name": sub.get("name") or push_name,
                "address": sub.get("address"),
                "neighborhood": sub.get("neighborhood"),
                "city": sub.get("city"),
                "plan_name": sub.get("plan_name"),
            })

    ticket = {
        "id": f"tkt-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "type": "reparo",
        "status": "aberto",
        "priority": "alta",
        "client_snapshot": snap,
        "subscriber_id": sub_id,
        "origin_source": "isabella_route_support",
        "origin_phone": phone,
        "notes": "Roteado por marker [ROTEAR_SUPORTE] — verificar última "
                   "conversa no WhatsApp pra contexto.",
        "created_at": now,
    }
    await db.tickets.insert_one(dict(ticket))
    await _set_conv_flags(phone, cid, {
        "support_ticket_id": ticket["id"], "support_ticket_at": now,
        "routed_to": "suporte_lousa",
    })
    log.info("[route_support] phone=%s → ticket=%s", phone, ticket["id"])


async def _route_finance(phone, cid, now):
    """Alerta Alvaro (financeiro) para falar com cliente."""
    await _set_conv_flags(phone, cid, {
        "needs_finance_review": True, "finance_alert_at": now,
        "routed_to": "alvaro_financeiro",
    })
    # Cria notificação no painel financeiro
    await db.financeiro_alerts.insert_one({
        "id": f"alf-{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "type": "isabella_route",
        "phone": phone,
        "reason": "Isabella roteou para financeiro (renegociação/preço)",
        "status": "open",
        "created_at": now,
    })
    log.info("[route_finance] phone=%s", phone)


async def _on_churn_risk(phone, cid, now):
    """Cliente em risco de churn — marca + log destacado."""
    await _set_conv_flags(phone, cid, {
        "churn_risk": True, "churn_risk_at": now,
    })
    log.warning("[CHURN_RISK] phone=%s — retenção precisa agir", phone)
