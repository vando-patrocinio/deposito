"""Cargos (job functions) — definições centrais.

Diferente de `role` (permissões de painel: administrador/gestor/financeiro/...),
`cargo` indica a FUNÇÃO OPERACIONAL do colaborador e determina automaticamente:
  - se aparece na Lousa de agendamento
  - se bate ponto
  - se acessa o módulo Atendimento (WhatsApp tickets)

Espelho de `frontend/src/cargo.js`. Mantenha os 2 sincronizados.
"""
from __future__ import annotations

TECNICO = "tecnico"
REPARADOR = "reparador"
INSTALADOR = "instalador"
ASSOCIADO = "associado"
AUX_ADMIN = "auxiliar_administrativo"
ATENDENTE = "atendente"

ALL_CARGOS: set[str] = {
    TECNICO, REPARADOR, INSTALADOR, ASSOCIADO, AUX_ADMIN, ATENDENTE,
}

# Cargos que aparecem na Lousa de Serviços
LOUSA_CARGOS: set[str] = {TECNICO, REPARADOR, INSTALADOR, ASSOCIADO}

# Cargos que NÃO batem ponto (todos os outros batem)
NO_CLOCK_CARGOS: set[str] = {ASSOCIADO}

# Cargos que acessam Atendimento (WhatsApp)
ATENDIMENTO_CARGOS: set[str] = {AUX_ADMIN, ATENDENTE}


def is_lousa_cargo(cargo: str | None) -> bool:
    return (cargo or "") in LOUSA_CARGOS


def clock_in_enabled_for(cargo: str | None) -> bool:
    """Retorna True se o cargo bate ponto. Associado é o único que não bate."""
    return (cargo or "") not in NO_CLOCK_CARGOS


def is_atendimento_cargo(cargo: str | None) -> bool:
    return (cargo or "") in ATENDIMENTO_CARGOS


def infer_cargo_from_legacy(role: str | None) -> str:
    """Migration helper: deriva cargo a partir do campo `role` legado."""
    r = (role or "").lower()
    if "atendente" in r:
        return ATENDENTE
    if "admin" in r and "administra" not in r:
        return AUX_ADMIN
    if "reparador" in r:
        return REPARADOR
    if "instalador" in r:
        return INSTALADOR
    if "associado" in r:
        return ASSOCIADO
    return TECNICO  # default seguro: Técnico de campo
