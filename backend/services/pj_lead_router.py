"""PJ Lead Router (Isabella V16) — Fluxo dedicado para Pessoa Jurídica.

REGRA DURA (CTO 18/02/2026):
  Se cliente é PJ, a Isabella NUNCA:
    • pede selfie com CNPJ
    • pede selfie com contrato social
    • pede foto segurando documento
    • pede validação facial
    • continua o fluxo residencial
    • tenta concluir o cadastro sozinha

  Em vez disso:
    1) Reconhece o contexto empresarial
    2) Captura lead mínimo (responsável, telefone, cidade, interesse)
    3) Aciona o Consultor PJ via WhatsApp
    4) Informa o cliente sobre o handoff
    5) ENCERRA a triagem (não pede mais documentos)

COLLECTIONS:
  • `pj_consultor_config`: 1 doc por company_id (ativo, nome, telefone, email)
  • `pj_leads`: 1 doc por lead capturado (status, conversa resumida, sla)
"""
from __future__ import annotations

NERVOUS_METADATA = {
    "owner": "isabella-team",
    "domain": "isabella",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from database import db

logger = logging.getLogger("ponto.pj_router")

CONFIG_COLL = "pj_consultor_config"
LEADS_COLL = "pj_leads"

# ─── PJ detection signals ───────────────────────────────────────
# Regex que afirmam contexto PJ (peso alto)
PJ_SIGNALS = [
    re.compile(r"\b(meu\s+|nossa\s+|da\s+)?(empresa|escrit[óo]rio|loja|"
                r"clinica|consultorio|consult[óo]rio|negocio|neg[óo]cio)\b",
                re.IGNORECASE),
    re.compile(r"\b(s\.?a\.?|ltda|mei|me\.?|epp|eireli)\b", re.IGNORECASE),
    re.compile(r"\b(cnpj|raz[ãa]o\s+social|nome\s+fantasia)\b",
                re.IGNORECASE),
    re.compile(r"\b(internet|link|fibra)\s+(empresarial|para\s+empresa|"
                r"dedicad[oa]|corporativ[oa])\b", re.IGNORECASE),
    re.compile(r"\bs[óo]cio\b", re.IGNORECASE),
    re.compile(r"\bcobran[çc]a\s+(da|para a|na)\s+empresa\b", re.IGNORECASE),
    re.compile(r"\bnota\s+fiscal\b", re.IGNORECASE),
]

# Falsos positivos: "minha empresa" pode aparecer em contexto pessoal
# (ex: "minha empresa de carteira de motorista"). Mas se o contexto
# falar de internet/contratação, vale.


async def detect_pj_signal(*, text: str) -> Dict[str, Any]:
    """Detecta sinais PJ no texto. Devolve dict com `is_pj`,
    `confidence`, `signals`, e (se houver) `cnpj_digits`."""
    if not text:
        return {"is_pj": False, "confidence": 0.0, "signals": []}
    found: List[str] = []
    for pat in PJ_SIGNALS:
        m = pat.search(text)
        if m:
            found.append(m.group(0))

    # CNPJ presente
    from services.cnpj_lookup import extract_cnpj
    cnpj_digits = extract_cnpj(text)

    if cnpj_digits:
        return {
            "is_pj": True, "confidence": 0.98,
            "signals": found + [f"cnpj:{cnpj_digits}"],
            "cnpj_digits": cnpj_digits,
        }
    if len(found) >= 2:
        return {"is_pj": True, "confidence": 0.85, "signals": found}
    if len(found) == 1:
        return {"is_pj": True, "confidence": 0.65, "signals": found}
    return {"is_pj": False, "confidence": 0.0, "signals": []}


# ─── Config do consultor PJ por empresa ────────────────────────
DEFAULT_CONFIG = {
    "ativo": False,
    "consultor_nome": "",
    "consultor_telefone": "",
    "consultor_whatsapp": "",
    "consultor_email": "",
    "sla_minutos": 15,
}


async def get_pj_config(*, company_id: str) -> Dict[str, Any]:
    doc = await db[CONFIG_COLL].find_one(
        {"company_id": company_id}, {"_id": 0},
    )
    if not doc:
        return {**DEFAULT_CONFIG, "company_id": company_id}
    return {**DEFAULT_CONFIG, **doc}


async def upsert_pj_config(*, company_id: str,
                                 updates: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    payload = {**updates, "company_id": company_id, "updated_at": now}
    await db[CONFIG_COLL].update_one(
        {"company_id": company_id},
        {"$set": payload, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return await get_pj_config(company_id=company_id)


# ─── Captura e encaminhamento de Lead ──────────────────────────
async def capture_lead(
    *,
    company_id: str,
    phone: str,
    detection: Dict[str, Any],
    user_text: str,
    conversation_summary: str = "",
    responsavel_nome: Optional[str] = None,
    cidade: Optional[str] = None,
    interesse: Optional[str] = None,
) -> Dict[str, Any]:
    """Persiste lead PJ. Se já existe lead aberto para esse phone+empresa,
    apenas anexa a nova mensagem (não duplica)."""
    cnpj_digits = detection.get("cnpj_digits")
    cnpj_data: Dict[str, Any] = {}
    if cnpj_digits:
        from services.cnpj_lookup import lookup
        cnpj_data = await lookup(cnpj_digits)

    razao = (cnpj_data.get("razao_social")
             or cnpj_data.get("nome_fantasia") or "")
    municipio = cnpj_data.get("municipio") or cidade or ""

    # Dedup: lead aberto do mesmo phone+company nas últimas 24h
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    existing = await db[LEADS_COLL].find_one({
        "company_id": company_id, "phone": phone,
        "status": {"$in": ["new", "consultor_acionado"]},
        "created_at": {"$gte": cutoff},
    })
    if existing:
        await db[LEADS_COLL].update_one(
            {"_id": existing["_id"]},
            {"$push": {"messages": {
                "text": user_text[:600],
                "ts": datetime.now(timezone.utc),
            }}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        )
        return {**existing, "deduped": True}

    lead_id = f"pjlead-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    doc = {
        "_id": lead_id,
        "company_id": company_id,
        "phone": phone,
        "status": "new",
        "razao_social": razao,
        "nome_fantasia": cnpj_data.get("nome_fantasia") or "",
        "cnpj": cnpj_data.get("cnpj") or "",
        "cnpj_digits": cnpj_digits or "",
        "cnpj_situacao": cnpj_data.get("situacao") or "",
        "cnpj_is_active": cnpj_data.get("is_active", False),
        "endereco_cnpj": cnpj_data.get("address_full") or "",
        "municipio": municipio,
        "uf": cnpj_data.get("uf") or "",
        "responsavel_nome": responsavel_nome or "",
        "interesse": interesse or "Internet Empresarial",
        "detection_confidence": detection.get("confidence"),
        "detection_signals": detection.get("signals") or [],
        "messages": [{"text": user_text[:600], "ts": now}],
        "conversation_summary": conversation_summary[:1200],
        "created_at": now,
        "updated_at": now,
        "sla_target_at": now + timedelta(minutes=15),
        "consultor_acionado_at": None,
        "consultor_notify_msg_id": None,
    }
    await db[LEADS_COLL].insert_one(doc)
    return doc


async def notify_consultor(
    *, company_id: str, lead: Dict[str, Any],
) -> Dict[str, Any]:
    """Envia WhatsApp para o Consultor PJ com o briefing do lead.
    Marca o lead como `consultor_acionado` e seta `sla_target_at`."""
    cfg = await get_pj_config(company_id=company_id)
    if not cfg.get("ativo"):
        return {"ok": False, "reason": "consultor_pj_inativo"}
    consultor_phone = (cfg.get("consultor_whatsapp")
                        or cfg.get("consultor_telefone") or "").strip()
    if not consultor_phone:
        return {"ok": False, "reason": "consultor_phone_vazio"}

    razao = lead.get("razao_social") or lead.get("nome_fantasia") or "—"
    cnpj = lead.get("cnpj") or "—"
    msgs = lead.get("messages") or []
    resumo = "\n".join(f"• {m['text'][:120]}" for m in msgs[:5]) or "—"

    msg = (
        "🚨 NOVO LEAD PJ\n\n"
        f"Empresa: {razao}\n"
        f"CNPJ: {cnpj}\n"
        f"Responsável: {lead.get('responsavel_nome') or '—'}\n"
        f"Telefone: {lead.get('phone')}\n"
        f"Origem: WhatsApp Isabella\n"
        f"Interesse: {lead.get('interesse')}\n"
        f"Cidade: {lead.get('municipio') or '—'}\n\n"
        "Resumo da conversa:\n"
        f"{resumo}\n\n"
        f"Tempo alvo de retorno: {cfg.get('sla_minutos', 15)} minutos"
    )

    # Envia via Baileys (default) — reusa wa_dispatcher
    try:
        from services.wa_dispatcher import dispatch_wa
        send = await dispatch_wa(
            company_id=company_id, phone=consultor_phone,
            text=msg, source="pj_lead_consultor",
        )
        notify_id = send.get("message_id") or f"pj-notify-{uuid.uuid4().hex[:8]}"
        await db[LEADS_COLL].update_one(
            {"_id": lead["_id"]},
            {"$set": {"status": "consultor_acionado",
                       "consultor_acionado_at": datetime.now(timezone.utc),
                       "consultor_notify_msg_id": notify_id,
                       "consultor_nome": cfg.get("consultor_nome"),
                       "consultor_telefone": consultor_phone}},
        )
        return {"ok": True, "notify_msg_id": notify_id,
                "consultor_nome": cfg.get("consultor_nome"),
                "consultor_telefone": consultor_phone}
    except Exception as e:
        logger.warning("[pj_router] notify consultor falhou: %s", e)
        return {"ok": False, "reason": "dispatch_error", "error": str(e)[:200]}


def render_client_reply(*, cfg: Dict[str, Any]) -> str:
    """Mensagem que o cliente PJ recebe após ser encaminhado."""
    nome = cfg.get("consultor_nome") or "nossa equipe comercial"
    phone = cfg.get("consultor_telefone") or ""
    # Formata BR: 5521999999999 → (21) 99999-9999
    phone_pretty = phone
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 13 and digits.startswith("55"):
        phone_pretty = f"({digits[2:4]}) {digits[4:9]}-{digits[9:]}"
    elif len(digits) == 11:
        phone_pretty = f"({digits[0:2]}) {digits[2:7]}-{digits[7:]}"

    return (
        "🏢 *Atendimento Empresarial Ligo*\n\n"
        "Perfeito, identifiquei que você está falando em nome de uma empresa. "
        "Já registrei tudo aqui.\n\n"
        f"Seu atendimento foi encaminhado para o nosso consultor PJ:\n\n"
        f"👤 *{nome}*"
        + (f"\n📱 {phone_pretty}" if phone_pretty else "")
        + "\n\nEle vai entrar em contato em até "
          f"{cfg.get('sla_minutos', 15)} minutos para entender sua necessidade "
          "e montar a melhor proposta para a sua empresa.\n\n"
          "Enquanto isso, deixei tudo preparado para agilizar seu atendimento. 😊"
    )


# ─── Ensure indexes ─────────────────────────────────────────────
async def ensure_indexes() -> None:
    try:
        await db[CONFIG_COLL].create_index("company_id", unique=True,
                                            name="cfg_cid_uq")
        await db[LEADS_COLL].create_index(
            [("company_id", 1), ("status", 1), ("created_at", -1)],
            name="leads_st_idx")
        await db[LEADS_COLL].create_index(
            [("company_id", 1), ("phone", 1)], name="leads_phone_idx")
        # TTL: leads ficam 180 dias
        await db[LEADS_COLL].create_index(
            "created_at", expireAfterSeconds=180 * 86400, name="leads_ttl")
    except Exception as e:
        logger.warning("[pj_router] indexes: %s", e)
