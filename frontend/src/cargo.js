/**
 * Cargo (Job Function) — definições centrais.
 *
 * Diferente de `role` (que controla permissões de painel: administrador/
 * gestor/financeiro/etc), `cargo` indica a função operacional do colaborador
 * e determina automaticamente:
 *   - se aparece na Lousa de agendamento
 *   - se bate ponto
 *   - se acessa o módulo de Atendimento (WhatsApp tickets)
 *
 * Este módulo é a fonte da verdade — backend e frontend importam daqui
 * (via `cargo.js` o frontend; backend espelha em `core.py`).
 */

export const CARGO = {
  TECNICO: "tecnico",
  REPARADOR: "reparador",
  INSTALADOR: "instalador",
  ASSOCIADO: "associado",
  AUX_ADMIN: "auxiliar_administrativo",
  ATENDENTE: "atendente",
};

export const CARGO_META = {
  [CARGO.TECNICO]:     { label: "Técnico",                  emoji: "🔧", grupo: "campo" },
  [CARGO.REPARADOR]:   { label: "Reparador",                emoji: "🔧", grupo: "campo" },
  [CARGO.INSTALADOR]:  { label: "Instalador",               emoji: "📡", grupo: "campo" },
  [CARGO.ASSOCIADO]:   { label: "Associado",                emoji: "🤝", grupo: "campo" },
  [CARGO.AUX_ADMIN]:   { label: "Auxiliar Administrativo",  emoji: "📋", grupo: "admin" },
  [CARGO.ATENDENTE]:   { label: "Atendente",                emoji: "💬", grupo: "admin" },
};

// Cargos que aparecem na Lousa de Serviços
export const LOUSA_CARGOS = new Set([
  CARGO.TECNICO, CARGO.REPARADOR, CARGO.INSTALADOR, CARGO.ASSOCIADO,
]);

// Cargos que NÃO batem ponto (todos os outros batem)
export const NO_CLOCK_CARGOS = new Set([CARGO.ASSOCIADO]);

// Cargos que acessam o módulo Atendimento (WhatsApp tickets, multi-agente IA)
export const ATENDIMENTO_CARGOS = new Set([CARGO.AUX_ADMIN, CARGO.ATENDENTE]);

export function cargoLabel(cargo) {
  return CARGO_META[cargo]?.label || cargo || "—";
}
export function cargoEmoji(cargo) { return CARGO_META[cargo]?.emoji || "👤"; }
export function isLousaCargo(cargo) { return LOUSA_CARGOS.has(cargo); }
export function clockInEnabledFor(cargo) { return !NO_CLOCK_CARGOS.has(cargo); }
export function isAtendimentoCargo(cargo) { return ATENDIMENTO_CARGOS.has(cargo); }

// Migration heurística: converte `role` legado em `cargo` quando ainda vazio
export function inferCargoFromLegacy(role) {
  const r = (role || "").toLowerCase();
  if (r.includes("atendente")) return CARGO.ATENDENTE;
  if (r.includes("admin") && !r.includes("administra")) return CARGO.AUX_ADMIN;
  if (r.includes("reparador")) return CARGO.REPARADOR;
  if (r.includes("instalador")) return CARGO.INSTALADOR;
  if (r.includes("associado")) return CARGO.ASSOCIADO;
  // default seguro: Técnico de campo
  return CARGO.TECNICO;
}

export const CARGO_OPTIONS_GROUPED = [
  {
    label: "🛠 Campo (Lousa de Agendamento)",
    options: [CARGO.TECNICO, CARGO.REPARADOR, CARGO.INSTALADOR, CARGO.ASSOCIADO],
  },
  {
    label: "💼 Administrativo (Atendimento)",
    options: [CARGO.AUX_ADMIN, CARGO.ATENDENTE],
  },
];
