"""Guardião Anti-CPF Repetido — Operação Identificação Automática.

Quando o subscriber_id JÁ foi resolvido pelo telefone, a Isabella NUNCA
pode pedir CPF, titular, cadastro ou "vou localizar seu cadastro".

Funções:
  - inject_identification_block(sys_prompt, link, history)  → string a ser
    apendada ao system prompt da Isabella reforçando regras com base no
    estado real de identificação.
  - rewrite_if_violates(reply, link)                        → se a reply
    violar as proibições enquanto subscriber_id existe, reescreve para
    eliminar a frase proibida (substitui pela versão segura).
  - update_conversation_identity(...)                       → persiste em
    `wa_conversations` os campos de memória de identificação.
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

import re
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

from database import db

# Padrões PROIBIDOS quando subscriber_id já identificado
FORBIDDEN_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("pede_cpf", re.compile(
        r"\b(me\s+(passa|informe|diz)|qual\s+o|preciso\s+do|"
        r"poderia\s+(me\s+)?(passar|informar)|"
        r"me\s+(envie|envia)|"
        r"informa(r|m)?)\s+(o\s+)?cpf\b", re.IGNORECASE)),
    ("pede_cpf_simples", re.compile(r"\bcpf\s+(do\s+)?titular\b", re.IGNORECASE)),
    ("nao_encontrei_cadastro", re.compile(
        r"\b(n[ãa]o\s+(consigo|encontrei|localizei|achei)\s+(o\s+)?(seu\s+)?(cadastro|contrato|titular))\b",
        re.IGNORECASE)),
    ("localizar_cadastro", re.compile(
        r"\b(precisamos|preciso|vou)\s+localizar\s+(seu\s+)?(cadastro|contrato)\b",
        re.IGNORECASE)),
    ("qual_titular", re.compile(
        r"\bqual\s+(o\s+)?(nome\s+do\s+)?titular\b", re.IGNORECASE)),
]


def detect_violations(reply: str) -> List[str]:
    """Lista todos os padrões proibidos que aparecem na reply."""
    out = []
    for name, pat in FORBIDDEN_PATTERNS:
        if pat.search(reply or ""):
            out.append(name)
    return out


def rewrite_if_violates(reply: str, link: Optional[Dict[str, Any]]) -> str:
    """Se há subscriber_id e a reply viola, reescreve eliminando a frase
    proibida. Idempotente.
    """
    if not reply or not link or not link.get("subscriber_id"):
        return reply
    violations = detect_violations(reply)
    if not violations:
        return reply
    name = (link.get("subscriber_name") or "").split(" ")[0] or "cliente"
    # Substitui sentenças inteiras que contenham qualquer padrão por uma
    # nota de identificação confirmada
    out_lines: List[str] = []
    for sentence in re.split(r"(?<=[\.\!\?])\s+", reply.strip()):
        if any(pat.search(sentence) for _, pat in FORBIDDEN_PATTERNS):
            # Pula a sentença ofensora completamente
            continue
        out_lines.append(sentence)
    safe = " ".join(out_lines).strip()
    if not safe:
        safe = (f"{name}, já localizei seu cadastro aqui pelo WhatsApp. "
                "Pode me contar com mais detalhes o que está acontecendo "
                "que eu já cuido pra você.")
    elif name and name.lower() not in safe.lower():
        safe = f"{name}, {safe[0].lower()}{safe[1:]}" if safe else safe
    return safe


def inject_identification_block(link: Optional[Dict[str, Any]],
                                  history_inbound: Optional[List[str]] = None
                                  ) -> str:
    """Bloco a ser apendado ao system prompt da Isabella reforçando
    a regra anti-CPF quando o cliente já foi identificado pelo telefone.
    """
    history_inbound = history_inbound or []
    # Caso 1: identificado com 1 match
    if link and link.get("subscriber_id") and not link.get("conflict"):
        name = link.get("subscriber_name") or "cliente"
        plan = link.get("plan_name") or ""
        return (
            "=== IDENTIFICAÇÃO AUTOMÁTICA — REGRA ABSOLUTA ===\n"
            f"O cliente JÁ FOI IDENTIFICADO automaticamente pelo telefone:\n"
            f"  • Nome: {name}\n"
            f"  • Plano: {plan or 'consulte os dados do cliente acima'}\n"
            f"  • subscriber_id: {link.get('subscriber_id')}\n"
            "\n"
            "PROIBIDO:\n"
            "  • Pedir CPF · titular · cadastro · contrato\n"
            "  • Dizer 'preciso localizar seu cadastro' ou 'não encontrei seu cadastro'\n"
            "  • Reiniciar a conversa após o cliente confirmar com 'sim', 'ok',\n"
            "    'obrigado' ou 'entendi'\n"
            "\n"
            "OBRIGATÓRIO:\n"
            "  • Trate o cliente pelo nome desde a primeira resposta\n"
            "  • Use os dados acima — você já sabe o plano, status, contrato\n"
            "  • Quando o cliente disser apenas 'sim' ou 'ok', interprete como\n"
            "    CONFIRMAÇÃO do último ponto e CONTINUE o fluxo (não reinicie)\n"
        )
    # Caso 2: conflito multi-match
    if link and link.get("conflict"):
        cands = link.get("candidates") or []
        n = link.get("conflict_count") or len(cands)
        nicks = ", ".join((c.get("name") or "—") for c in cands[:3])
        return (
            "=== IDENTIFICAÇÃO AUTOMÁTICA — MULTI-MATCH ===\n"
            f"Este telefone está em {n} cadastros: {nicks}.\n"
            "PROIBIDO: pedir CPF de imediato.\n"
            "OBRIGATÓRIO: pergunte sobre QUAL ENDEREÇO/PONTO o cliente fala.\n"
            "Exemplo: 'Encontrei mais de um cadastro nesse telefone. Você "
            "fala sobre qual endereço/ponto?'\n"
        )
    # Caso 3: sem identificação ainda — verifica se cliente já enviou CPF
    if history_inbound:
        cpf_re = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
        for h in history_inbound:
            if cpf_re.search(h or ""):
                return (
                    "=== CPF JÁ INFORMADO PELO CLIENTE ===\n"
                    "O cliente já enviou um CPF em alguma mensagem anterior\n"
                    "desta conversa. PROIBIDO pedir o CPF novamente. Use o\n"
                    "que ele já enviou. Se não localizou, peça apenas o\n"
                    "endereço/ponto.\n"
                )
    # Caso 4: sem identificação e sem histórico — Isabella pode pedir
    return (
        "=== IDENTIFICAÇÃO PENDENTE ===\n"
        "Este telefone NÃO está em nenhum cadastro. Você pode pedir CPF ou\n"
        "nome do titular UMA ÚNICA VEZ. Depois NÃO repita.\n"
    )


async def update_conversation_identity(*, company_id: str, phone: str,
                                          link: Optional[Dict[str, Any]],
                                          normalized: str,
                                          history_inbound: Optional[List[str]] = None
                                          ) -> Dict[str, Any]:
    """Persiste em wa_conversations os campos de memória de identificação.

    Campos atualizados:
      • phone · normalized_phone
      • subscriber_id · subscriber_name
      • identification_method = 'phone' | 'cpf' | 'pending'
      • identification_confidence = 0.0..1.0
      • multi_match = bool
      • cpf_confirmed = bool (true se cliente enviou CPF em algum momento)
    """
    history_inbound = history_inbound or []
    cpf_confirmed = False
    cpf_re = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
    for h in history_inbound:
        if cpf_re.search(h or ""):
            cpf_confirmed = True
            break

    method = "pending"
    confidence = 0.0
    multi_match = False
    subscriber_id = None
    subscriber_name = None
    if link and link.get("subscriber_id"):
        method = "phone"
        confidence = 1.0
        subscriber_id = link["subscriber_id"]
        subscriber_name = link.get("subscriber_name")
    elif link and link.get("conflict"):
        method = "phone_multi"
        confidence = 0.5
        multi_match = True
    elif cpf_confirmed:
        method = "cpf"
        confidence = 0.7

    identity_doc = {
        "phone": phone,
        "normalized_phone": normalized,
        "subscriber_id": subscriber_id,
        "subscriber_name": subscriber_name,
        "identification_method": method,
        "identification_confidence": confidence,
        "multi_match": multi_match,
        "cpf_confirmed": cpf_confirmed,
        "identity_updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await db.wa_conversations.update_one(
            {"company_id": company_id, "phone": phone},
            {"$set": {f"identity.{k}": v for k, v in identity_doc.items()}},
            upsert=True)
    except Exception:
        pass
    return identity_doc
