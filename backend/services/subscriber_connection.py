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
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

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
    company_id: str, phone: str
) -> Dict[str, Any]:
    """Consulta o status atual da ONU vinculada ao telefone.

    Retorna um dict pronto pra serializar e injetar no prompt da IA.
    NUNCA levanta exceção — sempre retorna {found: bool, ...}.
    """
    if not phone or not company_id:
        return {"found": False, "reason": "telefone vazio"}

    # 1. phone → subscriber (tenta múltiplos formatos)
    digits = re.sub(r"\D", "", phone)
    candidates = {digits}
    if digits.startswith("55") and len(digits) >= 12:
        candidates.add(digits[2:])  # sem DDI
    if len(digits) >= 11:
        candidates.add(digits[-11:])  # últimos 11 (DDD + número)

    sub_phone_doc = None
    for cand in candidates:
        sub_phone_doc = await db.subscriber_phones.find_one(
            {"company_id": company_id,
             "$or": [{"normalized_number": cand}, {"phone": cand}, {"raw_number": cand}]},
            {"_id": 0, "subscriber_id": 1},
        )
        if sub_phone_doc:
            break
    if not sub_phone_doc:
        return {"found": False, "reason": "telefone não vinculado a nenhum assinante"}

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
