"""Manager WhatsApp Assistant — gestor envia comando por WhatsApp, IA interpreta
e executa ação via APIs internas.

Whitelist: lista de telefones permitidos (campo `notify_phone` no
`churn_briefing_schedule` é considerado automaticamente; admin pode adicionar
outros em `manager_assistant_phones`).

Comandos suportados (extensível):
  - "briefing" / "relatório de churn" → gera/envia briefing atual
  - "lista de churn" / "últimos cancelamentos" → lista os 5 mais recentes
  - "abre alerta retenção" / "alerta para X" → cria alerta retenção (Lousa)
  - "ajuda" / "menu" → lista comandos
  - free-form → Claude decide entre os comandos disponíveis

Toda execução é registrada em `manager_assistant_log` (auditoria).
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core import DEMO_COMPANY_ID, now_iso
from database import db
from services.motor_ia import chat_completion, AgentDisabledError

logger = logging.getLogger("manager_assistant")


# ---------------------------------------------------------------------------
# Catálogo de comandos
# ---------------------------------------------------------------------------
COMMANDS: List[Dict[str, str]] = [
    {"id": "help",
     "desc": "Lista esses comandos.",
     "examples": ["ajuda", "menu", "comandos"]},
    {"id": "briefing",
     "desc": "Envia o último briefing de churn (gera novo se vencido).",
     "examples": ["briefing", "relatório de churn", "como está o churn"]},
    {"id": "list_churn",
     "desc": "Lista os últimos 5 cancelamentos finalizados.",
     "examples": ["lista de churn", "últimos cancelamentos", "quem cancelou"]},
    {"id": "create_retention_alert",
     "desc": "Cria alertas de retenção na Lousa para o pipeline pendente.",
     "examples": ["abre alerta retenção", "alerta para equipe",
                    "cria retenção para os pendentes"]},
]


# ---------------------------------------------------------------------------
# Whitelist
# ---------------------------------------------------------------------------
async def _is_manager_phone(company_id: str, phone: str) -> bool:
    """Phone pertence ao gestor cadastrado?

    Considera duas fontes:
      1. `churn_briefing_schedule.notify_phone` (admin já configurou)
      2. `manager_assistant_phones` (lista adicional opcional)
    """
    if not phone:
        return False
    p = re.sub(r"\D", "", phone)
    if not p:
        return False
    # 1) churn schedule
    sched = await db.churn_briefing_schedule.find_one(
        {"company_id": company_id}, {"_id": 0, "notify_phone": 1})
    if sched and re.sub(r"\D", "", sched.get("notify_phone") or "") == p:
        return True
    # 2) lista manual
    doc = await db.manager_assistant_phones.find_one(
        {"company_id": company_id, "phone": p}, {"_id": 0})
    return bool(doc and doc.get("enabled", True))


# ---------------------------------------------------------------------------
# Intent recognition
# ---------------------------------------------------------------------------
def _quick_intent(text: str) -> Optional[str]:
    """Heurística rápida (sem chamar LLM) para comandos óbvios."""
    s = (text or "").strip().lower()
    if not s:
        return None
    if re.search(r"\b(ajuda|menu|comandos?|help)\b", s):
        return "help"
    if re.search(r"\b(briefing|relat[óo]rio).*\b(churn|cancelament)", s) \
            or s.startswith("briefing"):
        return "briefing"
    if re.search(r"\b(lista|últimos?|quem).*\b(churn|cancelament)", s) \
            or "lista de churn" in s:
        return "list_churn"
    if re.search(r"\b(alerta|reten[çc][ãa]o)\b", s):
        return "create_retention_alert"
    return None


async def _claude_intent(text: str, company_id: str) -> Dict[str, Any]:
    """Pede pro Claude classificar a intenção. Retorna `{"intent":..., "params":{}}`.
    Se Claude falhar ou agente desligado, retorna intent="unknown"."""
    cmds_md = "\n".join(f"- `{c['id']}`: {c['desc']}" for c in COMMANDS)
    prompt = (
        "Você é o assistente operacional via WhatsApp de um provedor de internet. "
        "O GESTOR (admin) acaba de escrever uma mensagem. Classifique a INTENÇÃO "
        "em UM dos comandos abaixo e responda APENAS com JSON válido (sem texto extra).\n\n"
        f"Comandos disponíveis:\n{cmds_md}\n\n"
        "Mensagem do gestor: " + json.dumps(text, ensure_ascii=False) + "\n\n"
        'Responda no formato: {"intent": "<id>", "params": {}}.\n'
        'Se a mensagem não corresponder a nenhum comando, use intent="unknown".'
    )
    try:
        result = await chat_completion(
            company_id,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200, temperature=0.0, json_mode=True,
            agent="churn_insight",
        )
    except (AgentDisabledError, Exception) as e:
        logger.info("[manager-assistant] claude intent skip: %s", e)
        return {"intent": "unknown", "params": {}}
    try:
        parsed = json.loads((result.get("content") or "").strip())
        intent = parsed.get("intent") or "unknown"
        if intent not in [c["id"] for c in COMMANDS] + ["unknown"]:
            intent = "unknown"
        return {"intent": intent, "params": parsed.get("params") or {}}
    except Exception:
        return {"intent": "unknown", "params": {}}


# ---------------------------------------------------------------------------
# Handlers de comando
# ---------------------------------------------------------------------------
async def _cmd_help(_cid: str) -> str:
    lines = ["📋 *Comandos disponíveis:*", ""]
    for c in COMMANDS:
        ex = c["examples"][0]
        lines.append(f"• *{c['id']}* — {c['desc']}\n   _ex: \"{ex}\"_")
    lines.append("\nQualquer outra mensagem é interpretada com IA.")
    return "\n".join(lines)


async def _cmd_briefing(cid: str) -> str:
    """Pega o briefing mais recente OU gera um novo se >24h."""
    from services.churn_scheduler import _build_whatsapp_summary, _generate_and_save
    today = datetime.now(timezone.utc).date().isoformat()
    doc = await db.churn_insights.find_one(
        {"company_id": cid}, {"_id": 0},
        sort=[("generated_at", -1)],
    )
    if not doc or (doc.get("date") != today):
        doc = await _generate_and_save(cid, 30)
        if not doc:
            return "⚠️ Não consegui gerar o briefing agora. Tente em alguns minutos."
    return _build_whatsapp_summary(doc)


async def _cmd_list_churn(cid: str) -> str:
    """5 cancelamentos finalizados mais recentes."""
    cur = db.tickets.find(
        {"company_id": cid, "type": "retirada",
         "status": {"$in": ["finalizada", "concluida", "concluído"]}},
        {"_id": 0, "id": 1, "client_snapshot": 1, "closed_at": 1,
         "atlaz_assunto": 1},
    ).sort("closed_at", -1).limit(5)
    items = await cur.to_list(5)
    if not items:
        return "✅ Nenhum cancelamento finalizado registrado nos últimos dias."
    lines = ["📃 *Últimos cancelamentos:*", ""]
    for t in items:
        cs = t.get("client_snapshot") or {}
        name = cs.get("name") or "Cliente"
        nb = cs.get("neighborhood") or "—"
        when = (t.get("closed_at") or "")[:10] or "—"
        lines.append(f"• {name} ({nb}) — {when}")
    return "\n".join(lines)


async def _cmd_create_retention_alert(cid: str) -> str:
    """Cria alertas tipo `retention` na Lousa para todos os tickets pendentes
    de retirada. Idempotente: usa upsert por ticket_id."""
    cur = db.tickets.find(
        {"company_id": cid, "type": "retirada",
         "status": {"$in": ["pendente", "em_andamento", "agendada"]}},
        {"_id": 0, "id": 1, "client_snapshot": 1, "created_at": 1},
    ).sort("created_at", -1).limit(50)
    created = 0
    items = await cur.to_list(50)
    for t in items:
        cs = t.get("client_snapshot") or {}
        name = cs.get("name") or "Cliente"
        res = await db.lousa_alerts.update_one(
            {"company_id": cid, "kind": "retention", "ticket_id": t.get("id")},
            {"$set": {
                "id": f"alr-{uuid.uuid4().hex[:10]}",
                "company_id": cid,
                "kind": "retention",
                "severity": "alta",
                "ticket_id": t.get("id"),
                "headline": f"Cliente {name} pediu cancelamento — tentar reverter",
                "status": "active",
                "last_seen_at": now_iso(),
            },
             "$setOnInsert": {"first_detected_at": now_iso(),
                               "created_by": "manager_assistant"}},
            upsert=True,
        )
        if res.upserted_id:
            created += 1
    if not items:
        return "✅ Não há pedidos de cancelamento pendentes no momento."
    return (f"🚨 *Alertas de retenção criados:* {created} novo(s) "
              f"(total {len(items)} ticket(s) pendentes).\n\n"
              "A equipe de retenção verá na Lousa AI → Alertas.")


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------
async def handle_manager_message(company_id: str, phone: str,
                                    text: str) -> Optional[str]:
    """Recebe a mensagem do gestor, executa comando, retorna texto de resposta
    (ou None se a mensagem não for de gestor).

    O caller (whatsapp_baileys.inbound_webhook) é responsável por enviar
    o `reply` de volta via sidecar Baileys."""
    if not await _is_manager_phone(company_id, phone):
        return None

    text = (text or "").strip()
    if not text:
        return None

    # 1) Heurística rápida
    intent = _quick_intent(text)
    params: Dict[str, Any] = {}
    # 2) Se não bateu, pergunta pro Claude
    if not intent:
        cls = await _claude_intent(text, company_id)
        intent = cls["intent"]
        params = cls["params"]

    # 3) Dispatch
    reply: str
    if intent == "help":
        reply = await _cmd_help(company_id)
    elif intent == "briefing":
        reply = await _cmd_briefing(company_id)
    elif intent == "list_churn":
        reply = await _cmd_list_churn(company_id)
    elif intent == "create_retention_alert":
        reply = await _cmd_create_retention_alert(company_id)
    else:
        reply = (
            "Não reconheci esse comando. Envie *ajuda* para ver as opções "
            "disponíveis."
        )

    # 4) Audit log (best-effort)
    try:
        await db.manager_assistant_log.insert_one({
            "id": f"mal-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "phone": phone,
            "input_text": text[:500],
            "intent": intent,
            "params": params,
            "reply_text": reply[:600],
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.info("[manager-assistant] log skip: %s", e)

    return reply
