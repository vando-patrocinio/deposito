"""Subscriber Connection Status — verifica o status da ONU/ONT do cliente.

Fluxo:
    phone → subscriber_phones → subscribers → pppoe_user (ou nome)
                                          → smartolt_onus → status/signal

Resposta padronizada para ser injetada no system_prompt da Isabella quando
detectarmos intent de "problema/defeito/internet caiu". Permite que a IA
diga ao cliente "Já verifiquei aqui, sua conexão está [Online/Offline/LOS]
com sinal [Very good / Weak]" antes de seguir o protocolo.

Casos de retorno:
    - {found: True, connected: True/False, status, signal, olt, port,
       last_change, board}
    - {found: False, reason: <motivo amigável>}

AÇÃO REAL — Quando detectarmos LOS/Offline/Power fail num cliente
identificado, criamos AUTOMATICAMENTE um ticket de reparo no Kanban (em
`db.tickets`), com anti-duplicado de 6h. A IA é informada do ID do ticket
e usa isso na resposta ("Já abri o chamado #TKT-XYZ pra você").
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from core import now_iso
from database import db

logger = logging.getLogger("subscriber_connection")

# Palavras-chave (PT-BR + LIGO domain) que disparam o check automático.
PROBLEM_INTENT_REGEX = re.compile(
    r"\b("
    r"caiu|caindo|caída|cair|"
    r"sem\s+(internet|sinal|conex|wi-?fi)|"
    r"n(ã|a)o\s+(funciona|tem|liga|conect|carreg)|"
    r"defeito|problema|panic|panou|panhei|"
    r"lent[oa]|len(ti|tí)ssim[oa]|trav(a|an|am|ar|ou|ando)|"
    r"oscila|instab|intermitente|"
    r"off(\s*line)?|offline|"
    r"sem\s+navegar|n(ã|a)o\s+navega|"
    r"reset(ei|ou)?|reiniciei|"
    r"net\s+ruim|internet\s+ruim|"
    r"luz\s+(vermelha|piscando|apagada)|"
    r"modem|roteador|onu|ont"
    r")\b",
    re.IGNORECASE,
)


def is_problem_intent(text: str) -> bool:
    """True se a mensagem do cliente sugere problema na conexão."""
    if not text:
        return False
    return bool(PROBLEM_INTENT_REGEX.search(text))


async def check_connection_for_phone(
    company_id: str, phone: str, subscriber_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Consulta o status atual da ONU vinculada ao telefone.

    Retorna um dict pronto pra serializar e injetar no prompt da IA.
    NUNCA levanta exceção — sempre retorna {found: bool, ...}.

    Se `subscriber_id` for passado, pula o lookup phone→subscriber e usa
    direto — útil quando o cliente acabou de ser identificado por CPF e
    ainda não foi indexado em `subscriber_phones`.
    """
    if not company_id or (not phone and not subscriber_id):
        return {"found": False, "reason": "parâmetros vazios"}

    sub = None
    if subscriber_id:
        # Caminho direto — cliente identificado por CPF nesta inbound
        sub = await db.subscribers.find_one(
            {"company_id": company_id, "id": subscriber_id},
            {"_id": 0, "name": 1, "pppoe_user": 1, "plan_name": 1,
             "external_code": 1, "branch": 1, "document": 1, "status": 1},
        )

    if not sub:
        # 1. phone → subscriber (tenta múltiplos formatos)
        digits = re.sub(r"\D", "", phone or "")
        candidates = {digits}
        if digits.startswith("55") and len(digits) >= 12:
            candidates.add(digits[2:])  # sem DDI
        if len(digits) >= 11:
            candidates.add(digits[-11:])  # últimos 11 (DDD + número)

        sub_phone_doc = None
        for cand in candidates:
            sub_phone_doc = await db.subscriber_phones.find_one(
                {"company_id": company_id,
                 "$or": [{"normalized_number": cand},
                         {"phone": cand}, {"raw_number": cand}]},
                {"_id": 0, "subscriber_id": 1},
            )
            if sub_phone_doc:
                break
        if not sub_phone_doc:
            return {"found": False,
                    "reason": "telefone não vinculado a nenhum assinante"}
        sub = await db.subscribers.find_one(
            {"company_id": company_id, "id": sub_phone_doc["subscriber_id"]},
            {"_id": 0, "name": 1, "pppoe_user": 1, "plan_name": 1,
             "external_code": 1, "branch": 1, "document": 1, "status": 1},
        )
        if not sub:
            return {"found": False, "reason": "assinante não encontrado"}

    # 2. Acha a ONU — prioridade: pppoe_user > external_code > nome
    onu = None
    pppoe = (sub.get("pppoe_user") or "").strip()
    if pppoe:
        onu = await db.smartolt_onus.find_one(
            {"company_id": company_id, "pppoe_user": pppoe},
            {"_id": 0, "name": 1, "pppoe_user": 1, "status": 1,
             "signal_text": 1, "signal_1310": 1, "signal_1490": 1,
             "olt_name": 1, "board": 1, "port": 1,
             "last_status_change": 1, "unique_external_id": 1},
        )
    if not onu:
        # Fallback fuzzy: tenta achar ONU pelo nome do cliente
        # (algumas bases batizam a ONU com o nome do assinante)
        name = (sub.get("name") or "").strip()
        if name and len(name) >= 5:
            # Tenta primeiro nome + algum sobrenome
            first_token = name.split()[0]
            if len(first_token) >= 3:
                onu = await db.smartolt_onus.find_one(
                    {"company_id": company_id,
                     "name": {"$regex": re.escape(name[:25]), "$options": "i"}},
                    {"_id": 0, "name": 1, "pppoe_user": 1, "status": 1,
                     "signal_text": 1, "signal_1310": 1, "signal_1490": 1,
                     "olt_name": 1, "board": 1, "port": 1,
                     "last_status_change": 1, "unique_external_id": 1},
                )

    if not onu:
        return {
            "found": False,
            "subscriber_name": sub.get("name"),
            "plan_name": sub.get("plan_name"),
            "reason": ("assinante encontrado mas equipamento (ONU) não está "
                       "vinculado no cache SmartOLT"),
        }

    status_raw = (onu.get("status") or "").strip()
    # Normaliza:
    #   "Online" → connected=True (conexão saudável)
    #   "Offline" / "LOS" / "Power fail" → connected=False
    connected = status_raw.lower() == "online"

    # Calcula tempo desde o último mudança de status
    last_change = onu.get("last_status_change")
    minutes_since = None
    try:
        if last_change:
            dt = datetime.fromisoformat(str(last_change).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            minutes_since = int((datetime.now(timezone.utc) - dt).total_seconds() / 60)
    except Exception:
        minutes_since = None

    return {
        "found": True,
        "subscriber_name": sub.get("name"),
        "plan_name": sub.get("plan_name"),
        "branch": sub.get("branch"),
        "external_code": sub.get("external_code"),
        "connected": connected,
        "status": status_raw or "desconhecido",
        "signal_text": onu.get("signal_text"),
        "signal_1310": onu.get("signal_1310"),
        "signal_1490": onu.get("signal_1490"),
        "olt_name": onu.get("olt_name"),
        "board": onu.get("board"),
        "port": onu.get("port"),
        "last_status_change": last_change,
        "minutes_since_change": minutes_since,
        "onu_name": onu.get("name"),
        "onu_id": onu.get("unique_external_id"),
    }


def format_for_prompt(info: Dict[str, Any]) -> str:
    """Formata o resultado de check_connection_for_phone() em texto pronto
    pra ser anexado ao system_prompt da Isabella.
    """
    if not info.get("found"):
        reason = info.get("reason", "não foi possível verificar")
        sub_name = info.get("subscriber_name")
        if sub_name:
            return (
                "=== VERIFICAÇÃO DA CONEXÃO DO CLIENTE (Motor IA · SmartOLT) ===\n"
                f"Cliente: {sub_name}\n"
                f"Status: ❓ NÃO LOCALIZADO ({reason})\n"
                "AÇÃO: Diga ao cliente que você consultou o sistema mas o "
                "equipamento dele NÃO está vinculado ao cadastro técnico. "
                "Peça gentilmente que ele informe o CPF do titular pra você "
                "abrir um chamado especializado e localizar manualmente."
            )
        return (
            "=== VERIFICAÇÃO DA CONEXÃO DO CLIENTE (Motor IA · SmartOLT) ===\n"
            f"Status: ❓ TELEFONE NÃO IDENTIFICADO ({reason})\n"
            "AÇÃO: Você não conseguiu vincular este telefone a nenhum cliente. "
            "Peça o CPF do titular antes de prosseguir."
        )

    sub_name = info.get("subscriber_name", "Cliente")
    plan = info.get("plan_name") or "—"
    branch = info.get("branch") or "—"
    status = info.get("status", "desconhecido")
    signal = info.get("signal_text") or "—"
    olt = info.get("olt_name") or "—"
    port = info.get("port") or "—"
    minutes = info.get("minutes_since_change")

    if info.get("connected"):
        emoji = "🟢"
        action = (
            "AÇÃO: o equipamento do cliente está ONLINE e com sinal aceitável. "
            "Informe isso de forma natural ('Já verifiquei aqui no nosso sistema "
            "e seu equipamento está online, com sinal {signal}.'). "
            "Depois pergunte o que mais ele observou — pode ser problema no "
            "WiFi (não no link), no roteador secundário, ou em um aparelho "
            "específico. Conduza o troubleshooting começando pelo mais simples."
        ).format(signal=signal.lower())
    elif status.lower() in {"los"}:
        emoji = "🔴"
        action = (
            "AÇÃO: o equipamento está em LOS (Loss of Signal — fibra rompida "
            "ou desconectada). Diga ao cliente que você verificou e identificou "
            "uma INTERRUPÇÃO no sinal de fibra. NÃO peça reset do modem — não "
            "resolve LOS. Abra chamado técnico imediato e informe SLA (24h úteis "
            "residencial)."
        )
    elif status.lower() == "power fail":
        emoji = "🟡"
        action = (
            "AÇÃO: o equipamento está em POWER FAIL (sem energia). Pergunte "
            "gentilmente se houve queda de energia na casa do cliente ou se "
            "o roteador está desligado da tomada. Oriente a verificar se as "
            "luzes do equipamento estão acesas. Se sim, peça pra desligar e "
            "religar na tomada."
        )
    else:  # Offline
        emoji = "🔴"
        action = (
            "AÇÃO: o equipamento está OFFLINE. Pergunte se houve queda de "
            "energia, oriente a verificar as luzes do modem (PON deve estar "
            "verde fixo). Se as luzes estão OK e mesmo assim offline, abra "
            "chamado técnico imediato."
        )

    last_info = ""
    if minutes is not None:
        if minutes < 60:
            last_info = f"Mudança de status há ~{minutes}min."
        elif minutes < 60 * 24:
            last_info = f"Mudança de status há ~{minutes // 60}h."
        else:
            last_info = f"Mudança de status há ~{minutes // (60 * 24)}d."

    return (
        "=== VERIFICAÇÃO DA CONEXÃO DO CLIENTE (Motor IA · SmartOLT) ===\n"
        f"Cliente: {sub_name} · Plano: {plan} · Filial: {branch}\n"
        f"Equipamento: {emoji} **{status}** · Sinal: {signal}\n"
        f"OLT: {olt} · Porta: {port}\n"
        f"{last_info}\n\n"
        f"{action}\n"
        "IMPORTANTE: NÃO recite estes dados técnicos crus pro cliente. "
        "Use linguagem leiga (ex: 'verifiquei aqui no sistema e seu equipamento "
        "está online com sinal bom'). Apenas mencione 'OLT', 'porta', 'LOS', "
        "'sinal -28dBm' se o cliente perguntar especificamente."
    )



# Status técnicos que justificam abrir ticket de reparo automaticamente.
TICKET_TRIGGER_STATUSES = {"los", "offline", "power fail", "powerfail"}

# Status que primeiro tentam reboot remoto antes de abrir ticket (somente
# quando faz sentido — Power fail por exemplo NÃO adianta rebootar).
REBOOT_FIRST_STATUSES = {"los", "offline"}

# Janela de dedupe — não cria ticket novo se já tem um aberto pro mesmo cliente.
TICKET_DEDUPE_HOURS = 6

# Janela de dedupe pro reboot — se já fez reboot recente, não tenta de novo
# (evita ficar em loop reiniciando a ONU toda hora se cliente reclamar).
REBOOT_DEDUPE_MINUTES = 30


async def try_reboot_onu(
    company_id: str, conn_info: Dict[str, Any], phone: str,
) -> Dict[str, Any]:
    """Tenta reiniciar a ONU remotamente via SmartOLT API.

    Retorna:
      - {ok: True, action: "rebooted", was_recent: False}  → reboot disparado agora
      - {ok: True, action: "skipped_recent", was_recent: True}  → já houve reboot recente
      - {ok: False, action: "disabled"|"no_onu_id"|"http_error", error: ...}
    """
    onu_id = conn_info.get("onu_id")
    if not onu_id:
        return {"ok": False, "action": "no_onu_id"}

    # Dedupe — se reboot foi feito nos últimos 30 min, NÃO tenta de novo.
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=REBOOT_DEDUPE_MINUTES)
              ).isoformat()
    recent = await db.smartolt_actions.find_one(
        {"company_id": company_id, "action": "reboot",
         "external_id": onu_id,
         "result_ok": True,
         "created_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "created_at": 1},
    )
    if recent:
        logger.info(
            "[subscriber_connection] reboot SKIP (já feito recentemente): "
            "onu=%s last=%s", onu_id, recent.get("created_at"),
        )
        return {"ok": True, "action": "skipped_recent", "was_recent": True,
                 "last_reboot_at": recent.get("created_at")}

    # Chama SmartOLT API
    try:
        from routes.smartolt import _get_config, _http_post
    except ImportError as e:
        return {"ok": False, "action": "import_error", "error": str(e)}
    cfg = await _get_config(company_id)
    if not cfg.enabled or not cfg.subdomain or not cfg.api_key:
        return {"ok": False, "action": "disabled",
                 "error": "SmartOLT não configurado/desabilitado"}
    try:
        resp = await _http_post(cfg, f"/onu/reboot/{onu_id}")
    except Exception as e:
        logger.warning(
            "[subscriber_connection] reboot FALHOU onu=%s err=%s", onu_id, e
        )
        # Registra a tentativa falha pra auditoria.
        await db.smartolt_actions.insert_one({
            "id": f"sma-{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "action": "reboot",
            "external_id": onu_id,
            "onu_name": conn_info.get("onu_name"),
            "olt_name": conn_info.get("olt_name"),
            "actor_user": "isabella_ai",
            "actor_user_id": "isabella_ai",
            "result_ok": False,
            "result_raw": {"error": str(e)},
            "phone": phone,
            "trigger_status": conn_info.get("status"),
            "created_at": now_iso(),
        })
        return {"ok": False, "action": "http_error", "error": str(e)}

    ok = bool(resp.get("status"))
    await db.smartolt_actions.insert_one({
        "id": f"sma-{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "action": "reboot",
        "external_id": onu_id,
        "onu_name": conn_info.get("onu_name"),
        "olt_name": conn_info.get("olt_name"),
        "actor_user": "isabella_ai",
        "actor_user_id": "isabella_ai",
        "result_ok": ok,
        "result_raw": resp,
        "phone": phone,
        "trigger_status": conn_info.get("status"),
        "created_at": now_iso(),
    })
    if ok:
        logger.info(
            "[subscriber_connection] REBOOT REMOTO ok onu=%s phone=%s",
            onu_id, phone,
        )
        return {"ok": True, "action": "rebooted", "was_recent": False,
                 "raw": resp}
    return {"ok": False, "action": "smartolt_refused",
             "error": resp.get("error") or str(resp)}


def format_reboot_for_prompt(reboot_info: Dict[str, Any]) -> str:
    """Bloco pra IA dizer ao cliente que reiniciou remotamente."""
    if not reboot_info:
        return ""
    action = reboot_info.get("action")
    if action == "rebooted":
        return (
            "=== AÇÃO EXECUTADA: ONU REINICIADA REMOTAMENTE ===\n"
            "ACABEI DE REINICIAR a ONT/ONU do cliente remotamente, agora "
            "neste exato momento. Ele NÃO precisa fazer nada — só esperar "
            "1-2 minutos.\n\n"
            "AÇÃO PRO CLIENTE: informe que você reiniciou o equipamento dele "
            "remotamente (sem precisar dele desligar/religar a tomada), e "
            "peça pra ele AGUARDAR 2 minutos e testar novamente. Diga que "
            "se em 2 minutos não voltar, é só responder aqui que aí você "
            "abre o chamado técnico imediatamente. Tom: confiante, mas sem "
            "garantir 100%."
        )
    if action == "skipped_recent":
        last = reboot_info.get("last_reboot_at", "")
        return (
            "=== INFO: ONU JÁ FOI REINICIADA RECENTEMENTE ===\n"
            f"A ONU deste cliente já foi reiniciada remotamente em {last[:16]}. "
            "Reiniciar de novo NÃO vai ajudar (problema real exige técnico). "
            "PROSSIGA direto pra abertura do chamado técnico — não tente "
            "reset de novo. NÃO mencione a tentativa anterior pro cliente "
            "(seria confuso)."
        )
    return ""  # erro técnico — não polui o prompt; ticket vai abrir mesmo


def format_power_fail_offer_for_prompt() -> str:
    """Pra Power fail, IA oferece agendamento em vez de só abrir chamado."""
    return (
        "=== ESTRATÉGIA — POWER FAIL ===\n"
        "O equipamento está sem energia (provavelmente queda de luz na casa "
        "do cliente ou tomada desligada). NÃO abra chamado técnico imediato "
        "— problema NÃO é nosso. AÇÃO:\n"
        "1. Pergunte: 'A energia da sua casa está OK?' / 'O modem está "
        "   ligado na tomada?'\n"
        "2. Se for queda de energia local: oriente a aguardar voltar.\n"
        "3. Se for problema persistente (cliente diz que ligou tudo e ainda "
        "   nada): OFEREÇA AGENDAR VISITA TÉCNICA: 'Quer que eu agende uma "
        "   visita pra amanhã (manhã 8h-12h ou tarde 13h-17h)?' Quando o "
        "   cliente confirmar o turno, agradeça e diga que vai abrir o "
        "   chamado já com o horário marcado."
    )


async def ensure_repair_ticket(
    company_id: str, conn_info: Dict[str, Any], phone: str,
    triggered_by_text: str,
) -> Optional[Dict[str, Any]]:
    """Cria (se já não existe) um ticket de reparo no Kanban a partir do
    diagnóstico técnico.

    Regras:
    - Só dispara se `conn_info.found == True` e `status` está em
      TICKET_TRIGGER_STATUSES (LOS / Offline / Power fail).
    - Dedup: se cliente já tem ticket "pendente" / "em_andamento" criado
      nas últimas 6h, retorna o existente sem criar duplicado.
    - O ticket é criado com `created_by: "isabella_ai"` para auditoria.

    Retorna o dict do ticket criado/encontrado, ou None se não aplicável.
    """
    if not conn_info or not conn_info.get("found"):
        return None
    status = (conn_info.get("status") or "").strip().lower()
    if status not in TICKET_TRIGGER_STATUSES:
        return None

    subscriber_id = conn_info.get("subscriber_id") or conn_info.get("onu_id")
    sub_name = conn_info.get("subscriber_name") or "Cliente"

    # 1. Dedupe — procura ticket recente aberto pro mesmo cliente
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=TICKET_DEDUPE_HOURS)
              ).isoformat()
    existing = await db.tickets.find_one(
        {"company_id": company_id,
         "status": {"$in": ["pendente", "em_andamento", "aceito"]},
         "type": {"$in": ["reparo", "visita"]},
         "created_by": "isabella_ai",
         "client_snapshot.name": sub_name,
         "created_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "status": 1, "created_at": 1, "priority": 1},
        sort=[("created_at", -1)],
    )
    if existing:
        logger.info(
            "[subscriber_connection] ticket DUPLICADO ignorado pro %s "
            "(já existe %s · status=%s)",
            sub_name, existing.get("id"), existing.get("status")
        )
        return existing

    # 2. Cria o ticket novo
    ticket_id = f"tkt-{uuid.uuid4().hex[:10]}"
    # LOS → prioridade (fibra rompida · rede)
    # Offline → prioridade (sem conexão · rede)
    # Power fail → padrao (cliente sem energia local · não é nosso problema)
    if status == "los" or status == "offline":
        priority = "prioridade"
    else:
        priority = "padrao"
    ticket_type = "reparo" if status != "power fail" else "visita"
    description = (
        f"Cliente {sub_name} reportou: \"{(triggered_by_text or '')[:120]}\"\n"
        f"\n"
        f"Diagnóstico SmartOLT (automático):\n"
        f"  Status: {conn_info.get('status')}\n"
        f"  Sinal RX (1490nm): {conn_info.get('signal_1490', '—')} dBm\n"
        f"  Sinal TX (1310nm): {conn_info.get('signal_1310', '—')} dBm\n"
        f"  Sinal qualitativo: {conn_info.get('signal_text', '—')}\n"
        f"  OLT: {conn_info.get('olt_name')} · "
        f"Placa {conn_info.get('board')} · Porta {conn_info.get('port')}\n"
        f"  ONU: {conn_info.get('onu_name')} (ID {conn_info.get('onu_id')})\n"
        f"  Tempo desde mudança de status: "
        f"{conn_info.get('minutes_since_change', '?')} min\n"
        f"\n"
        f"⚠️ Aberto automaticamente pela Isabella IA via WhatsApp ({phone})."
    )
    ticket = {
        "id": ticket_id,
        "company_id": company_id,
        "client_id": subscriber_id,
        "client_snapshot": {
            "name": sub_name,
            "plan": conn_info.get("plan_name"),
            "branch": conn_info.get("branch"),
            "external_code": conn_info.get("external_code"),
            "phone": phone,
            "address": None,
        },
        "type": ticket_type,
        "priority": priority,
        "scheduled_time": None,
        "position": 0,
        "status": "pendente",
        "assigned_collaborator_id": None,
        "opened_at": now_iso(),
        "closed_at": None,
        "closed_by": None,
        "outcome": None,
        "whatsapp_status": "nao_enviado",
        "whatsapp_last_message": None,
        "admin_action": None,
        "admin_notes": None,
        "created_by": "isabella_ai",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "source": "whatsapp_ai_auto",
        "ai_diagnosis": {
            "trigger_text": triggered_by_text,
            "status": conn_info.get("status"),
            "olt_name": conn_info.get("olt_name"),
            "port": conn_info.get("port"),
            "signal_1490": conn_info.get("signal_1490"),
            "minutes_since_change": conn_info.get("minutes_since_change"),
            "onu_id": conn_info.get("onu_id"),
            "phone": phone,
        },
        "description": description,
    }
    await db.tickets.insert_one(ticket)
    logger.info(
        "[subscriber_connection] TICKET CRIADO id=%s priority=%s status=%s "
        "client=%s phone=%s",
        ticket_id, priority, status, sub_name, phone,
    )
    return {"id": ticket_id, "status": "pendente", "priority": priority,
             "created_at": ticket["created_at"], "isNew": True}


def format_ticket_for_prompt(ticket_info: Dict[str, Any]) -> str:
    """Adiciona ao prompt uma seção explicando que o chamado foi aberto."""
    if not ticket_info:
        return ""
    is_new = ticket_info.get("isNew", False)
    ticket_id = ticket_info.get("id")
    priority = ticket_info.get("priority", "padrao")
    priority_label = "PRIORITÁRIO" if priority == "prioridade" else "padrão"
    if is_new:
        return (
            "=== AÇÃO EXECUTADA: CHAMADO TÉCNICO ABERTO AUTOMATICAMENTE ===\n"
            f"Ticket #{ticket_id} criado agora ({priority_label}). Status: pendente.\n"
            "A equipe técnica já recebeu o chamado e vai entrar em contato em "
            "até 24h úteis (residencial) ou 12h úteis (empresarial).\n\n"
            "AÇÃO: informe o cliente que VOCÊ JÁ ABRIU o chamado (use o número "
            f"#{ticket_id}, sem o prefixo 'tkt-'). Diga o prazo de SLA. "
            "Pergunte se ele tem alguma observação adicional (ex: melhor "
            "horário de visita, se a luz vai estar disponível, telefone "
            "alternativo). NÃO peça pra ele abrir o chamado — ele JÁ ESTÁ "
            "ABERTO."
        )
    return (
        "=== INFO: JÁ EXISTE CHAMADO EM ANDAMENTO ===\n"
        f"Cliente já tem um chamado de reparo aberto pela Isabella nas "
        f"últimas {TICKET_DEDUPE_HOURS}h (#{ticket_id}, status: "
        f"{ticket_info.get('status')}). NÃO crie outro chamado — informe ao "
        "cliente que o chamado dele JÁ ESTÁ EM ANDAMENTO. Pergunte se ele "
        "precisa de mais alguma coisa enquanto a equipe técnica não chega."
    )
