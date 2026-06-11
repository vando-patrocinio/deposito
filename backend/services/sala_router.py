"""sala_router.py — Roteamento de notas SISTEMICAS para a SALA.

Regra (11/02/2026, request CTO):
  TODA nota emitida AUTOMATICAMENTE pelo sistema (Isabella, preventivas,
  detecao de degradacao de sinal, outages, predictive, etc.) deve cair
  na grade SALA da Lousa. O gestor triagem manualmente.

Notas com tecnico escolhido por HUMANO (drag-drop, gestor selecionou
no modal, aprovacao manual de sugestao com tech explicito no botao)
continuam indo direto pro tecnico.

Helper unico: `route_to_sala(doc, reason, ...)`.
  - Substitui `assigned_collaborator_id` por `col-sala-<tenant>`
  - Adiciona `system_generated=True`, `sala_route_reason=...`
  - Preserva `original_tech_suggested` (se a IA tinha uma sugestao)
    pra rastreio/coaching
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "sala_routing",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from datetime import datetime, timezone
from typing import Any, Dict, Optional


# Razoes validas — qualquer string que indique a fonte da nota sistemica.
VALID_REASONS = {
    "isabella_agendamento",       # Isabella agendou via atendimento WA
    "isabella_incident",           # Isabella detectou incidente
    "isabella_followup",           # Isabella reabriu por follow-up
    "isabella_action",             # Acao discreta da Isabella
    "ai_preventive_accepted",      # Admin aceitou sugestao preventiva
    "preventive_auto",             # Preventiva auto-gerada (sinal critico)
    "smartolt_predictive",         # Predictive SmartOLT
    "rede_ia_outage",              # Outage detector
    "autonomous_engine",           # Engine autonomo
    "gestao_ai",                   # Gestao AI auto-create
    "action_engine",               # Action engine
    "agent_tools",                 # Tools usados por agentes
    "fleet_ai",                    # Fleet inspecao
    "atlaz_unassigned",            # Atlaz orfao (ja roteado via routes/atlaz.py)
    "sales_funnel",                # Lead virou ticket
    "subscriber_connection",       # Wizard de conexao
    "marker_router",               # Marker -> ticket
    "system_other",                # generico
}


async def route_to_sala(
    doc: Dict[str, Any],
    *,
    reason: str,
    original_tech_suggested: Optional[str] = None,
) -> str:
    """Override do `assigned_collaborator_id` do doc para a SALA do tenant.

    DEVE ser chamado ANTES de `db.tickets.insert_one(doc)`.

    Args:
      doc: dict do ticket que sera inserido (mutado in-place).
      reason: motivo da emissao automatica (use uma das VALID_REASONS).
      original_tech_suggested: se a IA/heuristic sugeriu um tecnico,
        salva como historico (NAO bloqueia — apenas referencia).

    Returns:
      sala_id usado.
    """
    from services.isabella_actions import _ensure_sala
    cid = doc.get("company_id")
    if not cid:
        raise ValueError("route_to_sala: doc precisa de `company_id`")
    if reason not in VALID_REASONS:
        reason = "system_other"
    sala_id = await _ensure_sala(cid)

    # Preserva a sugestao original (quem a IA achava bom mandar)
    if original_tech_suggested is None:
        original_tech_suggested = doc.get("assigned_collaborator_id")

    doc["assigned_collaborator_id"] = sala_id
    doc["system_generated"] = True
    doc["sala_route_reason"] = reason
    if original_tech_suggested and original_tech_suggested != sala_id:
        doc["original_tech_suggested"] = original_tech_suggested
    doc["sala_routed_at"] = datetime.now(timezone.utc).isoformat()
    return sala_id
