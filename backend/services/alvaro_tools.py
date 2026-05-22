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


# Marker que o Álvaro escreve quando o cliente escolhe um slot:
#   [AGENDAR_REPARO:date=2026-05-22,time=10:00]
SCHEDULE_MARKER_RE = re.compile(
    r"\[AGENDAR_REPARO:date=(\d{4}-\d{2}-\d{2}),time=(\d{2}:\d{2})\]",
    re.IGNORECASE,
)
# Marker que o Álvaro escreve pra disparar o reboot:
#   [REBOOT_ONU]
REBOOT_MARKER_RE = re.compile(r"\[REBOOT_ONU\]", re.IGNORECASE)


async def process_alvaro_actions(text: str, phone: str,
                                       diag: Optional[Dict[str, Any]],
                                       base_url: str = "http://localhost:8001",
                                       ) -> str:
    """Processa markers de ação do Álvaro e retorna texto limpo (sem markers).

    Markers tratados:
      [REBOOT_ONU]   → chama POST /smartolt/public/reboot-onu
      [AGENDAR_REPARO:date=...,time=...]
                     → chama POST /lousa/public/create-repair-from-ai
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

    # limpa espaços em branco excessivos
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).rstrip()
    return cleaned
