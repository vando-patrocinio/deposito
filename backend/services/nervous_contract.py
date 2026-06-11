"""NERVOUS CONTRACT — Fase 1.

Toda módulo Python sob /app/backend/{routes,services,scripts} deve
declarar NERVOUS_METADATA no topo do arquivo. Sem isso, falha no
linter (Fase 2) e bloqueia deploy (Fase 3).

Uso (em qualquer módulo novo):

    NERVOUS_METADATA = {
        "owner": "isabella-team",
        "domain": "atendimento",
        "criticality": "critical",  # low|medium|high|critical
        "emits_events": True,
        "event_types": ["WA_INBOUND_RECEIVED", "WA_OUTBOUND_SENT"],
        "consumes_events": ["TICKET_OPENED"],
        "company_id_required": True,
    }

Domínios válidos (Constituição V3.1):
    comercial / instalacoes / financeiro / atendimento / whatsapp /
    indicacoes / parceiros / estoque / rede / operacoes / isabella /
    presidente / lousa / shield / infra

Criticality:
    critical  → emits_events OBRIGATÓRIO; CI gate bloqueia se faltar.
    high      → emits_events FORTEMENTE recomendado; warning hard.
    medium    → metadata obrigatório, eventos opcionais.
    low       → metadata obrigatório, eventos não exigidos.

NÃO é convenção. É CONTRATO. Validado por linter + CI + autodiscovery.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional, Set


VALID_DOMAINS: Set[str] = {
    "comercial", "instalacoes", "financeiro", "atendimento",
    "whatsapp", "indicacoes", "parceiros", "estoque", "rede",
    "operacoes", "isabella", "presidente", "lousa", "shield", "infra",
}

VALID_CRITICALITY: Set[str] = {"low", "medium", "high", "critical"}

# Pasta → criticality default (autodiscovery aplica se faltar declaração)
# Crítico = emite OU bloqueia. Alto = importante. Médio = utilitário.
DEFAULT_CRITICALITY_BY_PATH = {
    "routes/subscribers": "critical",
    "routes/tickets": "critical",
    "routes/invoices": "critical",
    "routes/payments": "critical",
    "routes/sales": "critical",
    "routes/whatsapp_": "critical",
    "routes/lousa": "high",
    "routes/isabella_": "high",
    "routes/shield": "critical",
    "routes/presidente": "high",
    "services/isabella_": "high",
    "services/lousa_": "high",
    "services/event_": "critical",
    "services/financial_": "critical",
    "services/dunning": "critical",
    "scripts/": "low",
}


@dataclass
class NervousMetadata:
    owner: str
    domain: str
    criticality: Literal["low", "medium", "high", "critical"]
    emits_events: bool = False
    event_types: List[str] = field(default_factory=list)
    consumes_events: List[str] = field(default_factory=list)
    company_id_required: bool = True
    notes: Optional[str] = None


def validate_dict(md: dict) -> List[str]:
    """Retorna lista de erros (vazia = válido). API simétrica à dataclass."""
    errors: List[str] = []
    if not isinstance(md, dict):
        return ["NERVOUS_METADATA não é dict"]
    required = {"owner", "domain", "criticality"}
    for k in required:
        if not md.get(k):
            errors.append(f"campo obrigatório ausente: {k}")
    domain = md.get("domain")
    if domain and domain not in VALID_DOMAINS:
        errors.append(f"domain '{domain}' inválido. "
                        f"válidos: {sorted(VALID_DOMAINS)}")
    crit = md.get("criticality")
    if crit and crit not in VALID_CRITICALITY:
        errors.append(f"criticality '{crit}' inválido. "
                        f"válidos: {sorted(VALID_CRITICALITY)}")
    if md.get("emits_events"):
        ets = md.get("event_types") or []
        if not isinstance(ets, list) or not ets:
            errors.append(
                "emits_events=True exige event_types: List[str] não vazio")
    if crit == "critical" and not md.get("emits_events"):
        errors.append(
            "criticality=critical EXIGE emits_events=True (regra Fase 6)")
    return errors


def infer_criticality(file_path: str) -> str:
    """Inferência baseada em path quando metadata está ausente.
    Usada pelo autodiscovery pra criar registro inicial.
    """
    p = (file_path or "").lower().replace("/app/backend/", "")
    for prefix, crit in DEFAULT_CRITICALITY_BY_PATH.items():
        if prefix in p:
            return crit
    return "medium"
