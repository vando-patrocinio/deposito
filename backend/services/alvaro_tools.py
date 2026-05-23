"""Alvaro Tools — funções server-side que enriquecem o contexto do Álvaro.

Quando o WhatsApp recebe uma msg pra um cliente que parece suporte técnico
(palavras como "internet caiu", "sem net", "tá lento"), o `whatsapp_baileys`
chama essas funções ANTES de mandar pro LLM. O resultado entra como
contexto extra no prompt — assim o Álvaro já recebe diagnóstico, uptime,
slots disponíveis sem precisar de tool-calls do LLM.

Idempotente, com timeout duro, gracioso quando SmartOLT está fora.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, Optional

import httpx

from database import db

log = logging.getLogger("ponto.alvaro_tools")

# Palavras-chave que sinalizam "atendimento de reparo" — usadas em decisão
SUPPORT_KEYWORDS = (
    "internet caiu", "sem net", "sem internet", "tá lento", "ta lento",
    "muito lento", "lentidão", "não conecta", "nao conecta",
    "wifi não funciona", "wifi parou", "modem", "roteador apagou",
    "luz vermelha", "luz piscando", "sem sinal", "perdi a internet",
    "off", "sem conexão", "instabilidade", "queda",
)


def looks_like_support(text: str) -> bool:
    """True se a mensagem parece um problema técnico."""
    if not text:
        return False
    t = text.lower()
    return any(k in t for k in SUPPORT_KEYWORDS)


async def diagnose_for_alvaro(phone: str,
                                  base_url: str = "http://localhost:8001",
                                  ) -> Optional[Dict[str, Any]]:
    """Chama /api/smartolt/public/onu-diagnose/{phone} com timeout.

    Retorna None se falhou ou se não encontrou — o Álvaro segue normal.
    """
    try:
        async with httpx.AsyncClient(timeout=6.0) as c:
            r = await c.get(f"{base_url}/api/smartolt/public/onu-diagnose/{phone}")
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        log.debug("[alvaro_tools] diagnose failed: %s", e)
    return None


async def fetch_available_slots(company_id: str,
                                   base_url: str = "http://localhost:8001",
                                   ) -> list:
    """Próximos slots disponíveis na Lousa pra Álvaro propor."""
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.get(
                f"{base_url}/api/lousa/public/available-slots",
                params={"company_id": company_id, "days_ahead": 3,
                          "ticket_type": "reparo"},
            )
            if r.status_code == 200:
                return r.json().get("options", []) or []
    except Exception as e:
        log.debug("[alvaro_tools] slots failed: %s", e)
    return []


def format_diag_context(diag: Dict[str, Any], slots: list) -> str:
    """Formata bloco de contexto pra injetar no prompt do Álvaro."""
    if not diag or not diag.get("found"):
        return ""

    status = diag.get("status") or "unknown"
    parts = [
        "=== DIAGNÓSTICO TÉCNICO ATUAL DO CLIENTE (SmartOLT) ===",
        f"Status: {status.upper()}",
    ]
    if diag.get("uptime_human"):
        parts.append(f"Equipamento ligado há: {diag['uptime_human']}")
    if diag.get("signal_text"):
        parts.append(f"Sinal: {diag['signal_text']}")
    if diag.get("olt_name"):
        parts.append(f"OLT: {diag['olt_name']}")
    parts.append("")
    parts.append("EXPLICAÇÃO TÉCNICA PRA USAR COM O CLIENTE:")
    parts.append(diag.get("diagnosis") or "")
    parts.append("")
    parts.append("FLUXO RECOMENDADO:")
    if status == "online":
        parts.append(
            "1. Avise que vai reiniciar o equipamento remotamente.\n"
            "2. Use a tool [REBOOT_ONU] (sistema executa).\n"
            "3. Peça pro cliente desligar/religar da tomada por 30s.\n"
            "4. Aguarde 1-2 min e pergunte se voltou.\n"
            "5. SE NÃO voltar → agende reparo com os slots abaixo."
        )
    elif status == "los":
        parts.append(
            "1. Explique que é um problema na fibra (cabo/CTO).\n"
            "2. NÃO é coisa que o cliente resolve em casa.\n"
            "3. Já agende reparo com os slots abaixo — alta prioridade."
        )
    elif status == "power_off":
        parts.append(
            "1. Peça pro cliente verificar a tomada e cabo de força.\n"
            "2. SE confirmar que tem energia mas equipamento não liga → "
            "agende reparo com os slots abaixo."
        )
    else:
        parts.append(
            "Status indefinido. Faça perguntas básicas (luz acesa? piscando?) "
            "e agende reparo se necessário."
        )
    parts.append("")
    if slots:
        parts.append("HORÁRIOS DISPONÍVEIS PRA AGENDAMENTO (lousa):")
        for i, s in enumerate(slots[:5], 1):
            parts.append(f"  {i}. {s.get('human', '')}")
        parts.append("Ofereça 2-3 opções ao cliente. Quando ele escolher, "
                        "use marker [AGENDAR_REPARO:date=YYYY-MM-DD,time=HH:MM]")

    parts.append("")
    parts.append("DADOS PRA TICKET (uso interno do sistema):")
    if diag.get("external_id"):
        parts.append(f"  external_id: {diag['external_id']}")
    if diag.get("subscriber_id"):
        parts.append(f"  subscriber_id: {diag['subscriber_id']}")
    if diag.get("company_id"):
        parts.append(f"  company_id: {diag['company_id']}")
    return "\n".join(parts)


async def fetch_wifi_status_for_alvaro(
        subscriber_id: Optional[str],
        company_id: Optional[str],
        base_url: str = "http://localhost:8001",
) -> Optional[Dict[str, Any]]:
    """Busca status Wi-Fi do subscriber (premium + ONU + estado).

    Usado pra alimentar contexto do Álvaro quando cliente pede troca de
    senha do Wi-Fi. Retorna None se subscriber_id não está disponível
    (cliente não vinculado).
    """
    if not subscriber_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.get(
                f"{base_url}/api/wifi/public/subscriber/{subscriber_id}/status",
                params={"company_id": company_id} if company_id else None,
            )
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        log.debug("[alvaro_tools] wifi_status failed: %s", e)
    return None


def format_wifi_context(wifi: Dict[str, Any]) -> str:
    """Contexto Wi-Fi pro prompt do Álvaro (quando cliente pede troca)."""
    if not wifi:
        return (
            "\n=== TROCA DE WI-FI (CONTEXTO) ===\n"
            "Cliente não identificado no cadastro — peça CPF ou nome completo "
            "pra localizar e abra chamado manual se necessário."
        )
    state = wifi.get("state")
    onu = wifi.get("onu") or {}
    parts = ["\n=== TROCA DE WI-FI (CONTEXTO) ==="]
    parts.append(f"Estado: {state}")
    if onu.get("model"):
        parts.append(f"ONU: {onu['model']} ({onu.get('status', '?')})")
    if state == "ready":
        parts.append(
            "Cliente é PREMIUM ⭐ e ONU está online. Você PODE trocar agora.\n"
            "FLUXO:\n"
            "1. Pergunte qual o novo nome (SSID) e nova senha (mínimo 8 chars).\n"
            "2. Confirme com cliente os 2 valores antes de aplicar.\n"
            "3. Use marker [TROCAR_WIFI:ssid=NovoNome,senha=NovaSenha].\n"
            "4. Avise que o roteador reinicia em ~30s e a senha nova vale na hora.\n"
            "5. Após 2 minutos, envie mensagem-resumo com a nova senha pro cliente\n"
            "   anotar (sistema faz isso automaticamente)."
        )
    elif state == "premium_required":
        parts.append(
            "Cliente NÃO é Premium. NÃO troque diretamente.\n"
            "FLUXO DE UPSELL:\n"
            "1. Explique que troca pelo WhatsApp é vantagem exclusiva do Premium.\n"
            "2. Liste 2-3 benefícios (troca Wi-Fi 24/7, speed test, suporte priori).\n"
            "3. Pergunte se quer upgrade. SE SIM, use marker [OFFER_UPGRADE]\n"
            "   pra encaminhar pra equipe de Vendas (Isabella).\n"
            "4. SE NÃO, ofereça abrir chamado pra atendente humano trocar.\n"
            "5. NUNCA trate como erro — é oportunidade comercial."
        )
    elif state == "no_onu":
        parts.append(
            "Cliente não tem ONU vinculada no SmartProv. Não dá pra trocar remoto.\n"
            "Peça pra cliente acessar o painel do roteador (192.168.1.1) "
            "ou abra chamado técnico se cliente não souber fazer."
        )
    elif state == "onu_offline":
        parts.append(
            "ONU offline no momento — não é possível trocar agora. "
            "Diga ao cliente que vamos verificar a conexão primeiro. "
            "Se ele confirmar que está sem internet, abra chamado de reparo."
        )
    elif state == "rate_limited":
        parts.append(
            "Cliente já trocou hoje (limite 1/24h). Avise educadamente que ele "
            "atingiu o limite diário e pode trocar novamente amanhã, OU "
            "abrir chamado pra atendente humano trocar agora."
        )
    return "\n".join(parts)


# Palavras-chave que indicam pedido de troca de Wi-Fi.
WIFI_CHANGE_KEYWORDS = (
    "trocar senha do wifi", "trocar a senha do wifi", "mudar senha wifi",
    "trocar wifi", "mudar wifi", "trocar nome do wifi", "trocar o nome do wifi",
    "mudar nome wifi", "nova senha wifi", "alterar senha do wifi",
    "renomear wifi", "renomear o wifi", "alterar wifi", "troca de wifi",
    "trocar minha senha", "trocar minha senha do wi-fi",
)


def looks_like_wifi_change(text: str) -> bool:
    """True se a mensagem parece pedido de troca de Wi-Fi."""
    if not text:
        return False
    t = text.lower()
    return any(k in t for k in WIFI_CHANGE_KEYWORDS)


# Marker que o Álvaro escreve quando cliente confirma troca:
#   [TROCAR_WIFI:ssid=CasaJoao,senha=minhasenha123]
WIFI_MARKER_RE = re.compile(
    r"\[TROCAR_WIFI:ssid=([^,\]]+),senha=([^\]]+)\]",
    re.IGNORECASE,
)
# Marker pra cliente não-premium que aceitou upgrade:
#   [OFFER_UPGRADE]
UPGRADE_MARKER_RE = re.compile(r"\[OFFER_UPGRADE(?::plan=([^\]]+))?\]",
                                 re.IGNORECASE)


# Marker que o Álvaro escreve pra disparar o reboot:
#   [REBOOT_ONU]
REBOOT_MARKER_RE = re.compile(r"\[REBOOT_ONU\]", re.IGNORECASE)


# Marker que o Álvaro escreve quando o cliente escolhe um slot:
#   [AGENDAR_REPARO:date=2026-05-22,time=10:00]
SCHEDULE_MARKER_RE = re.compile(
    r"\[AGENDAR_REPARO:date=(\d{4}-\d{2}-\d{2}),time=(\d{2}:\d{2})\]",
    re.IGNORECASE,
)


async def process_alvaro_actions(text: str, phone: str,
                                       diag: Optional[Dict[str, Any]],
                                       base_url: str = "http://localhost:8001",
                                       wifi_ctx: Optional[Dict[str, Any]] = None,
                                       ) -> str:
    """Processa markers de ação do Álvaro e retorna texto limpo (sem markers).

    Markers tratados:
      [REBOOT_ONU]   → chama POST /smartolt/public/reboot-onu
      [AGENDAR_REPARO:date=...,time=...]
                     → chama POST /lousa/public/create-repair-from-ai
      [TROCAR_WIFI:ssid=...,senha=...]
                     → chama POST /wifi/public/subscriber/{sid}/change-by-phone
      [OFFER_UPGRADE]
                     → registra lead no funil (Isabella vai puxar) e injeta
                       handoff [ROTEAR_VENDAS] no final do texto pro fluxo
                       de roteamento já existente cuidar do resto.
    """
    cleaned = text
    if not text:
        return text

    # 1. REBOOT
    if REBOOT_MARKER_RE.search(text) and diag and diag.get("external_id"):
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.post(
                    f"{base_url}/api/smartolt/public/reboot-onu",
                    json={"external_id": diag["external_id"], "phone": phone},
                )
                log.info("[alvaro] reboot phone=%s status=%s",
                            phone, r.status_code)
        except Exception as e:
            log.warning("[alvaro] reboot failed: %s", e)
        cleaned = REBOOT_MARKER_RE.sub("", cleaned).strip()

    # 2. AGENDAR_REPARO
    m = SCHEDULE_MARKER_RE.search(cleaned)
    if m and diag:
        date_, time_ = m.group(1), m.group(2)
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.post(
                    f"{base_url}/api/lousa/public/create-repair-from-ai",
                    json={
                        "phone": phone,
                        "subscriber_id": diag.get("subscriber_id"),
                        "company_id": diag.get("company_id"),
                        "scheduled_date": date_, "scheduled_time": time_,
                        "onu_status": diag.get("status") or "unknown",
                        "diagnosis_text": diag.get("diagnosis") or "",
                        "client_name": diag.get("client_name"),
                        "reboot_attempted": diag.get("_reboot_attempted", False),
                    },
                )
                log.info("[alvaro] agendado phone=%s %s %s status=%s",
                            phone, date_, time_, r.status_code)
        except Exception as e:
            log.warning("[alvaro] agendar failed: %s", e)
        cleaned = SCHEDULE_MARKER_RE.sub("", cleaned).strip()

    # 3. TROCAR_WIFI — só executa se wifi_ctx confirmou estado "ready"
    m = WIFI_MARKER_RE.search(cleaned)
    if m:
        ssid = m.group(1).strip()
        senha = m.group(2).strip()
        sid = (wifi_ctx or {}).get("subscriber_id") or (diag or {}).get("subscriber_id")
        cid = (diag or {}).get("company_id")
        if sid and (wifi_ctx or {}).get("state") == "ready":
            try:
                async with httpx.AsyncClient(timeout=35.0) as c:
                    r = await c.post(
                        f"{base_url}/api/wifi/public/subscriber/{sid}/"
                        f"change-by-phone",
                        json={"phone": phone, "company_id": cid,
                                "ssid": ssid, "password": senha,
                                "apply_to_both": True,
                                "source": "whatsapp_alvaro"},
                    )
                    log.info("[alvaro] wifi_change phone=%s status=%s",
                                phone, r.status_code)
            except Exception as e:
                log.warning("[alvaro] wifi_change failed: %s", e)
        else:
            log.info("[alvaro] wifi marker presente mas estado=%s sid=%s — pulou",
                        (wifi_ctx or {}).get("state"), sid)
        cleaned = WIFI_MARKER_RE.sub("", cleaned).strip()

    # 4. OFFER_UPGRADE — registra lead no funil + força roteamento p/ Isabella
    m = UPGRADE_MARKER_RE.search(cleaned)
    if m:
        plan_hint = (m.group(1) or "").strip() or None
        sid = (wifi_ctx or {}).get("subscriber_id") or (diag or {}).get("subscriber_id")
        cid = (diag or {}).get("company_id")
        try:
            async with httpx.AsyncClient(timeout=8.0) as c:
                await c.post(
                    f"{base_url}/api/wifi/public/upgrade-lead",
                    json={"phone": phone, "subscriber_id": sid,
                            "company_id": cid, "plan_hint": plan_hint,
                            "source": "whatsapp_alvaro_wifi_request"},
                )
                log.info("[alvaro] upgrade_lead phone=%s plan=%s",
                            phone, plan_hint)
        except Exception as e:
            log.warning("[alvaro] upgrade_lead failed: %s", e)
        # Strip marker e adiciona [ROTEAR_VENDAS] no final — o pipeline
        # já existente em whatsapp_baileys cuida do handoff pra Isabella.
        cleaned = UPGRADE_MARKER_RE.sub("", cleaned).strip()
        if "[ROTEAR_VENDAS]" not in cleaned:
            cleaned = cleaned + "\n[ROTEAR_VENDAS]"

    # limpa espaços em branco excessivos
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).rstrip()
    return cleaned
