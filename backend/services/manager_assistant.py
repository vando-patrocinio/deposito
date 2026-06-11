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


NERVOUS_METADATA = {
    "owner": "platform-team",
    "domain": "infra",
    "criticality": "medium",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

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
    {"id": "pause_agent",
     "desc": "Pausa um agente IA (params.agent_label). Ex: 'pausa o copilot'.",
     "examples": ["pausa o copilot", "desliga isabella", "para o sentinela"]},
    {"id": "resume_agent",
     "desc": "Reativa um agente IA. Ex: 'ativa o copilot'.",
     "examples": ["ativa o copilot", "religa isabella", "volta o sentinela"]},
    {"id": "smartolt_report",
     "desc": "Status atual da rede óptica (panes, ONUs LOS, OLTs).",
     "examples": ["relatório SmartOLT", "status da rede", "como está a rede óptica"]},
    {"id": "system_status",
     "desc": "Status geral: agentes ativos, WhatsApp conectado, alertas abertos.",
     "examples": ["status do sistema", "como está o sistema",
                    "tudo funcionando?"]},
    {"id": "tickets_today",
     "desc": "Quantos tickets foram abertos hoje.",
     "examples": ["quantos tickets hoje", "tickets do dia",
                    "abriram tickets hoje?"]},
]


# ---------------------------------------------------------------------------
# Whitelist
# ---------------------------------------------------------------------------
async def _is_manager_phone(company_id: str, phone: str) -> bool:
    """Phone pertence ao gestor cadastrado?

    Considera múltiplas fontes:
      1. `churn_briefing_schedule.notify_phone` (admin já configurou)
      2. `manager_assistant_phones` (lista adicional opcional)
      3. `conselho_ia_settings.presidente_briefing_phone` (iter219)
      4. `conselho_ia_settings.notify_phone` (Agente IA legado)
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
    if doc and doc.get("enabled", True):
        return True
    # 3+4) settings do Conselho/Presidente IA (iter219)
    cia = await db.conselho_ia_settings.find_one(
        {"company_id": company_id},
        {"_id": 0, "presidente_briefing_phone": 1, "notify_phone": 1})
    if cia:
        for k in ("presidente_briefing_phone", "notify_phone"):
            v = re.sub(r"\D", "", cia.get(k) or "")
            if v and v == p:
                return True
    return False


# ---------------------------------------------------------------------------
# Intent recognition
# ---------------------------------------------------------------------------
def _quick_intent(text: str) -> tuple[Optional[str], Dict[str, Any]]:
    """Heurística rápida (sem chamar LLM) para comandos óbvios.
    Retorna (intent, params)."""
    s = (text or "").strip().lower()
    if not s:
        return None, {}
    if re.search(r"\b(ajuda|menu|comandos?|help)\b", s):
        return "help", {}
    if re.search(r"\b(briefing|relat[óo]rio).*\b(churn|cancelament)", s) \
            or s.startswith("briefing"):
        return "briefing", {}
    if re.search(r"\b(lista|últimos?|quem).*\b(churn|cancelament)", s) \
            or "lista de churn" in s:
        return "list_churn", {}
    if re.search(r"\b(alerta|reten[çc][ãa]o)\b", s):
        return "create_retention_alert", {}
    # pausa / desliga / para AGENTE
    m = re.search(r"\b(pausa|desliga|para|parar)\s+(?:o |a |as |os )?([\w\s]+)$", s)
    if m:
        return "pause_agent", {"agent_label": m.group(2).strip()}
    # ativa / religa / volta AGENTE
    m = re.search(r"\b(ativa|liga|religa|volta|reativa)\s+(?:o |a |as |os )?([\w\s]+)$", s)
    if m:
        return "resume_agent", {"agent_label": m.group(2).strip()}
    if re.search(r"\b(smartolt|rede [óo]ptica|status.*rede|panes?)\b", s):
        return "smartolt_report", {}
    if re.search(r"\b(status.*sistema|sistema.*ok|tudo bem|tudo funcion)", s):
        return "system_status", {}
    if re.search(r"\b(tickets?).*\b(hoje|dia)\b", s) or "tickets do dia" in s:
        return "tickets_today", {}
    return None, {}


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
# Comandos avançados (agentes, SmartOLT, sistema, tickets)
# ---------------------------------------------------------------------------

async def _resolve_agent_id(label: str) -> Optional[Dict[str, str]]:
    """Faz match aproximado de um nome livre contra o catálogo de agentes."""
    from services.motor_ia import AGENT_CATALOG
    if not label:
        return None
    s = re.sub(r"\s+", " ", label.strip().lower())
    # match por ID exato
    for a in AGENT_CATALOG:
        if a["id"].lower() == s:
            return a
    # match por substring no label (ex.: "copilot" → "Co-Pilot IA")
    for a in AGENT_CATALOG:
        if s in a["label"].lower() or s in a["id"].lower():
            return a
    # match invertido: cada palavra do label no nome do agente
    tokens = [t for t in re.split(r"\W+", s) if len(t) >= 3]
    if tokens:
        for a in AGENT_CATALOG:
            if any(t in a["label"].lower() or t in a["id"].lower() for t in tokens):
                return a
    return None


async def _cmd_toggle_agent(cid: str, agent_label: str, enable: bool) -> str:
    """Liga ou desliga agente pelo nome livre."""
    from services.motor_ia import set_agent_state
    agent = await _resolve_agent_id(agent_label)
    if not agent:
        return (f"❓ Não encontrei um agente com nome \"{agent_label}\". "
                  "Use *ajuda* ou tente: copilot, isabella, sentinela, triagem.")
    try:
        result = await set_agent_state(
            cid, agent["id"], enable, user_label="manager_assistant")
    except Exception as e:
        return f"⚠️ Falha ao alterar agente: {e}"
    state = "ativado" if enable else "pausado"
    emoji = "✅" if enable else "⏸️"
    changed_note = "" if result.get("changed") else " (já estava nesse estado)"
    return f"{emoji} *{agent['label']}* foi {state}{changed_note}."


async def _cmd_smartolt_report(cid: str) -> str:
    """Resumo da rede óptica: panes ativas + LOS atuais."""
    active_outages = await db.network_outages.count_documents(
        {"company_id": cid, "status": "active"})
    # Top 3 OLTs com mais ONUs LOS (last_snapshot)
    pipe = [
        {"$match": {"company_id": cid, "status": "active"}},
        {"$group": {"_id": "$olt_name",
                      "los": {"$sum": "$los_count"},
                      "total": {"$max": "$total_count"},
                      "sev": {"$max": "$severity_pct"}}},
        {"$sort": {"los": -1}},
        {"$limit": 3},
    ]
    top_olts: List[Dict[str, Any]] = []
    async for r in db.network_outages.aggregate(pipe):
        top_olts.append(r)
    if active_outages == 0:
        return "🟢 *Rede óptica:* sem panes ativas. Tudo verde."
    lines = [f"🟠 *Rede óptica:* {active_outages} pane(s) ativa(s)."]
    if top_olts:
        lines.append("")
        lines.append("*Top OLTs afetadas:*")
        for o in top_olts:
            lines.append(
                f"• {o['_id']}: {o.get('los')} ONUs LOS de {o.get('total')} "
                f"({o.get('sev')}%)")
    lines.append("\nDetalhes: Central IA → SmartOLT AI")
    return "\n".join(lines)


async def _cmd_system_status(cid: str) -> str:
    """Resumo geral: agentes, WhatsApp, alertas."""
    from services.motor_ia import AGENT_CATALOG
    # Agentes pausados
    paused = await db.ai_agent_switches.find(
        {"company_id": cid, "enabled": False},
        {"_id": 0, "agent_id": 1},
    ).to_list(50)
    paused_ids = {p["agent_id"] for p in paused}
    paused_names = [a["label"] for a in AGENT_CATALOG if a["id"] in paused_ids]
    total = len(AGENT_CATALOG)
    active = total - len(paused_ids)
    # Alertas ativos
    alerts_active = await db.lousa_alerts.count_documents(
        {"company_id": cid, "status": "active"})
    outages_active = await db.network_outages.count_documents(
        {"company_id": cid, "status": "active"})
    # WhatsApp status (best-effort via httpx)
    wa_status = "?"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as cli:
            r = await cli.get("http://127.0.0.1:3002/status")
            d = r.json()
            wa_status = "🟢 conectado" if d.get("connected") else "🔴 desconectado"
    except Exception:
        wa_status = "❓ indisponível"

    lines = ["🩺 *Status do sistema*", ""]
    lines.append(f"• Agentes IA: *{active}/{total}* ativos")
    if paused_names:
        lines.append("  ⏸️ Pausados: " + ", ".join(paused_names[:4]))
    lines.append(f"• WhatsApp: {wa_status}")
    lines.append(f"• Alertas Lousa: *{alerts_active}* ativos")
    lines.append(f"• Panes de rede: *{outages_active}*")
    return "\n".join(lines)


async def _cmd_tickets_today(cid: str) -> str:
    """Total e split por tipo de tickets abertos hoje."""
    today = datetime.now(timezone.utc).date().isoformat()
    cutoff = today + "T00:00:00+00:00"
    pipe = [
        {"$match": {"company_id": cid, "created_at": {"$gte": cutoff}}},
        {"$group": {"_id": "$type", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ]
    by_type: Dict[str, int] = {}
    async for r in db.tickets.aggregate(pipe):
        by_type[r["_id"] or "outros"] = r["n"]
    total = sum(by_type.values())
    if total == 0:
        return f"📋 Nenhum ticket aberto hoje ({today})."
    lines = [f"📋 *Tickets de hoje ({today}):* {total} no total", ""]
    for t, n in by_type.items():
        lines.append(f"• {t}: {n}")
    return "\n".join(lines)




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

    # 0) Verifica se há AÇÃO PENDENTE pra esse telefone (do sistema proativo)
    try:
        from services.proactive_alerts import get_active_pending, execute_pending
        pending = await get_active_pending(company_id, re.sub(r"\D", "", phone))
        if pending:
            reply = await execute_pending(company_id, pending, text)
            # audit log
            try:
                await db.manager_assistant_log.insert_one({
                    "id": f"mal-{uuid.uuid4().hex[:10]}",
                    "company_id": company_id, "phone": phone,
                    "input_text": text[:500],
                    "intent": f"pending:{pending.get('kind')}",
                    "params": {"pending_id": pending.get("id")},
                    "reply_text": reply[:600],
                    "created_at": now_iso(),
                })
            except Exception:
                pass
            return reply
    except Exception as e:
        logger.warning("[manager-assistant] pending check fail: %s", e)

    # 1) Heurística rápida
    intent, params = _quick_intent(text)
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
    elif intent == "pause_agent":
        reply = await _cmd_toggle_agent(company_id, params.get("agent_label", ""), enable=False)
    elif intent == "resume_agent":
        reply = await _cmd_toggle_agent(company_id, params.get("agent_label", ""), enable=True)
    elif intent == "smartolt_report":
        reply = await _cmd_smartolt_report(company_id)
    elif intent == "system_status":
        reply = await _cmd_system_status(company_id)
    elif intent == "tickets_today":
        reply = await _cmd_tickets_today(company_id)
    else:
        # FALLBACK: pergunta livre → Secretária IA "Ligo" responde com tool-use
        try:
            from services.secretaria_ia import ask as secretaria_ask
            sec = await secretaria_ask(company_id, text, channel="whatsapp", who=phone)
            reply = sec.get("answer") or (
                "Não reconheci esse comando. Envie *ajuda* para ver as opções "
                "disponíveis."
            )
            intent = "secretaria_qa"
        except Exception as e:
            logger.warning("[manager-assistant] secretaria fallback fail: %s", e)
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
