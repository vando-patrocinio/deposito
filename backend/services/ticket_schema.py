"""
services/ticket_schema.py — Vocabulário canônico da Lousa (CTO P0 11/06/2026)

Fonte única de verdade para `priority`, `status` e `type` em `db.tickets`.

Toda escrita em tickets deve passar por `normalize_ticket_payload()` (write path)
ou `validate_ticket_payload()` (read/dry-run path).

Para garantir blindagem mesmo quando algum serviço esquece de chamar o
normalizador, `database.py` faz monkey-patch nas operações `insert_*` /
`update_*` da coleção `db.tickets` para aplicar `normalize_ticket_payload`
automaticamente em todo write.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("ticket_schema")

# ─────────── Vocabulários canônicos ─────────────────────────────────────────
PRIORITY_CANONICAL: List[str] = ["normal", "prioridade", "urgente", "horario"]

# Conjunto de status REAIS aceitos pela Lousa (existem mais valores em uso
# legado: aberta, encerrada, finalizada, etc — mantemos para não quebrar dados
# históricos. A ordem reflete o ciclo de vida.)
STATUS_CANONICAL: List[str] = [
    "pendente",                  # criada, ainda não aberta
    "aguardando_atendimento",    # aguardando técnico
    "aberta",                    # técnico iniciou
    "em_execucao",               # campo: chegou e está executando
    "finalizada",                # técnico fechou (espera confirmação gestor)
    "encerrada",                 # gestor confirmou e fechou definitivamente
    "reagendada",                # cliente/operador remarcou
    "cancelada",                 # operador cancelou
]

# `type` é aberto por design (a empresa cria novos tipos sem restart). Aqui
# apenas garantimos que valores em PT-BR uppercase venham normalizados para
# o canônico do código (lowercase, sem acento). Manter snake_case ou kebab.
TYPE_KNOWN: List[str] = [
    "instalacao", "reparo", "retirada", "troca", "preventiva",
    "vistoria", "rompimento", "venda", "manutencao",
    "alerta_geofence", "frota_alerta", "alerta_ia", "signal_callback",
    "auto_retargeting", "outage", "ONU_OFFLINE", "ONU_LOW_SIGNAL",
]

# ─────────── Aliases — convertidos automaticamente em normalize_* ───────────
PRIORITY_ALIASES: Dict[str, str] = {
    # PT-BR uppercase (usados por serviços IA)
    "ALTA": "urgente", "MÉDIA": "prioridade", "MEDIA": "prioridade",
    "BAIXA": "normal", "CRÍTICA": "urgente", "CRITICA": "urgente",
    "BLOCKER": "urgente", "URGENTE": "urgente", "NORMAL": "normal",
    "PRIORIDADE": "prioridade", "HORARIO": "horario", "HORÁRIO": "horario",
    # PT-BR lowercase
    "alta": "urgente", "média": "prioridade", "media": "prioridade",
    "baixa": "normal", "crítica": "urgente", "critica": "urgente",
    # Legacy default values
    "padrao": "normal", "padrão": "normal", "PADRAO": "normal", "PADRÃO": "normal",
    "default": "normal", "DEFAULT": "normal",
    # English
    "HIGH": "urgente", "MEDIUM": "prioridade", "LOW": "normal",
    "high": "urgente", "medium": "prioridade", "low": "normal",
}

STATUS_ALIASES: Dict[str, str] = {
    "aberto": "aberta",
    "agendado": "aguardando_atendimento",
    "AGENDADO": "aguardando_atendimento",
    "em_andamento": "em_execucao",
    "EM_ANDAMENTO": "em_execucao",
    "concluido": "finalizada",
    "concluida": "finalizada",
    "concluído": "finalizada",
    "concluída": "finalizada",
    "CONCLUIDO": "finalizada",
    "CONCLUIDA": "finalizada",
    "CONCLUÍDO": "finalizada",
    "CONCLUÍDA": "finalizada",
    "cancelado": "cancelada",
    "CANCELADO": "cancelada",
    "reagendado": "reagendada",
    "REAGENDADO": "reagendada",
    "PENDENTE": "pendente",
    "ABERTA": "aberta",
    # English legacy
    "open": "aberta", "OPEN": "aberta",
    "closed": "encerrada", "CLOSED": "encerrada",
    "reopened": "aberta", "REOPENED": "aberta",
    "pending": "pendente", "PENDING": "pendente",
    "done": "finalizada", "DONE": "finalizada",
    "finished": "finalizada", "FINISHED": "finalizada",
    "scheduled": "aguardando_atendimento", "SCHEDULED": "aguardando_atendimento",
    "in_progress": "em_execucao", "IN_PROGRESS": "em_execucao",
}

TYPE_ALIASES: Dict[str, str] = {
    # PT-BR uppercase comuns
    "INSTALACAO": "instalacao", "INSTALAÇÃO": "instalacao",
    "instalação": "instalacao", "Instalação": "instalacao",
    "Instalacao": "instalacao",
    "REPARO": "reparo", "Reparo": "reparo",
    "RETIRADA": "retirada", "Retirada": "retirada",
    "TROCA": "troca", "Troca": "troca",
    "PREVENTIVA": "preventiva", "Preventiva": "preventiva",
    "VISTORIA": "vistoria", "Vistoria": "vistoria",
    "ROMPIMENTO": "rompimento", "Rompimento": "rompimento",
    "VENDA": "venda", "Venda": "venda",
    "MANUTENCAO": "manutencao", "MANUTENÇÃO": "manutencao",
    "manutenção": "manutencao", "Manutenção": "manutencao",
    # English
    "install": "instalacao", "repair": "reparo", "removal": "retirada",
}


def _is_known(value: Any, canonical: List[str], aliases: Dict[str, str]) -> bool:
    if value is None:
        return True  # None → default canonical é aceito
    s = str(value).strip()
    if not s:
        return True
    if s in canonical or s in aliases:
        return True
    s_low = s.lower()
    return s_low in canonical or s_low in aliases


def detect_rejections(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Retorna lista de campos com valor fora do vocabulário (e além dos aliases)."""
    rej: List[Dict[str, Any]] = []
    if "priority" in payload and not _is_known(
        payload["priority"], PRIORITY_CANONICAL, PRIORITY_ALIASES,
    ):
        rej.append({"field": "priority", "value": payload["priority"],
                    "coerced_to": "normal"})
    if "status" in payload and not _is_known(
        payload["status"], STATUS_CANONICAL, STATUS_ALIASES,
    ):
        rej.append({"field": "status", "value": payload["status"],
                    "coerced_to": "pendente"})
    return rej


# ─────────── Normalizers — sempre retornam (valor_canonico, was_changed) ────
def normalize_priority(value: Any) -> str:
    """Retorna o valor canônico ou 'normal' como fallback seguro."""
    if value is None:
        return "normal"
    s = str(value).strip()
    if not s:
        return "normal"
    if s in PRIORITY_CANONICAL:
        return s
    if s in PRIORITY_ALIASES:
        return PRIORITY_ALIASES[s]
    # case-insensitive last try
    s_low = s.lower()
    if s_low in PRIORITY_CANONICAL:
        return s_low
    if s_low in PRIORITY_ALIASES:
        return PRIORITY_ALIASES[s_low]
    log.warning("[ticket_schema] priority desconhecido '%s' → 'normal'", value)
    return "normal"


def normalize_status(value: Any) -> str:
    if value is None:
        return "pendente"
    s = str(value).strip()
    if not s:
        return "pendente"
    if s in STATUS_CANONICAL:
        return s
    if s in STATUS_ALIASES:
        return STATUS_ALIASES[s]
    s_low = s.lower()
    if s_low in STATUS_CANONICAL:
        return s_low
    if s_low in STATUS_ALIASES:
        return STATUS_ALIASES[s_low]
    log.warning("[ticket_schema] status desconhecido '%s' → 'pendente'", value)
    return "pendente"


def normalize_type(value: Any) -> str:
    """`type` é mais permissivo — só converte aliases conhecidos.
    Se desconhecido, mantém o valor original (lowercase) — não joga fora.
    """
    if value is None:
        return "reparo"
    s = str(value).strip()
    if not s:
        return "reparo"
    if s in TYPE_ALIASES:
        return TYPE_ALIASES[s]
    if s in TYPE_KNOWN:
        return s
    # mantém valor original — type é open vocabulary
    return s


# ─────────── Payload normalization ──────────────────────────────────────────
CRITICAL_FIELDS = ("priority", "status", "type")


def normalize_ticket_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza in-place os campos críticos. Idempotente. Não muda outros campos."""
    if not isinstance(payload, dict):
        return payload
    if "priority" in payload:
        payload["priority"] = normalize_priority(payload["priority"])
    if "status" in payload:
        payload["status"] = normalize_status(payload["status"])
    if "type" in payload:
        payload["type"] = normalize_type(payload["type"])
    return payload


def normalize_update_doc(update: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza um update doc Mongo: aplica em `$set`, `$setOnInsert`, top-level."""
    if not isinstance(update, dict):
        return update
    for op in ("$set", "$setOnInsert"):
        if op in update and isinstance(update[op], dict):
            normalize_ticket_payload(update[op])
    # update doc direto (replace_one ou update doc sem operators)
    if not any(k.startswith("$") for k in update.keys()):
        normalize_ticket_payload(update)
    return update


def validate_ticket_payload(
    payload: Dict[str, Any], *, strict: bool = False,
) -> Tuple[bool, List[str]]:
    """Verifica se um payload está dentro do vocabulário canônico.
    Retorna (ok, errors). Se strict=True, exige normalização exata; senão,
    aceita aliases (que serão convertidos no insert).
    """
    errors: List[str] = []
    p = payload.get("priority")
    if p is not None:
        if p not in PRIORITY_CANONICAL and (strict or p not in PRIORITY_ALIASES):
            errors.append(f"priority='{p}' fora do vocabulário canônico")
    s = payload.get("status")
    if s is not None:
        if s not in STATUS_CANONICAL and (strict or s not in STATUS_ALIASES):
            errors.append(f"status='{s}' fora do vocabulário canônico")
    # client_snapshot obrigatório?
    cs = payload.get("client_snapshot")
    if "client_snapshot" in payload and cs is not None:
        if not isinstance(cs, dict) or not cs.get("name"):
            errors.append("client_snapshot.name ausente")
    return (len(errors) == 0, errors)


# ─────────── Audit/event hook (chamado pelo interceptor) ────────────────────
async def _emit_rejected_event(
    db, *, reason: str, payload_summary: Dict[str, Any]
):
    """Best-effort: emite evento `TICKET_SCHEMA_REJECTED` para auditoria."""
    try:
        from datetime import datetime, timezone
        await db.system_events.insert_one({
            "id": f"evt-tsr-{datetime.now(timezone.utc).timestamp()}",
            "event_type": "TICKET_SCHEMA_REJECTED",
            "company_id": payload_summary.get("company_id"),
            "reason": reason,
            "payload": payload_summary,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        log.debug("schema_rejected emit falhou: %s", e)


def get_canonical_vocab() -> Dict[str, List[str]]:
    """Para o linter e dashboard."""
    return {
        "priority": list(PRIORITY_CANONICAL),
        "status": list(STATUS_CANONICAL),
        "type_known": list(TYPE_KNOWN),
    }
