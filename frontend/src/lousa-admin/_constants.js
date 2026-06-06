/* =============================================================
   Constantes e helpers compartilhados pelo LousaAdminPanel.
   Extraídos pra serem reusados pelos sub-componentes em /lousa-admin/.
============================================================= */

export const TYPE_LABELS = {
  reparo: "Reparo",
  instalacao: "Instalação",
  retirada: "Retirada",
  prioridade: "Prioridade",
  preventiva: "️ Preventiva",
  venda: "Venda",
  alerta_geofence: "️ ALERTA GEOFENCE",
  frota_alerta: "ALERTA FROTA",
};

export const ACTION_LABEL = {
  criada: { icon: "➕", color: "#3b82f6", label: "Criada" },
  aberta: { icon: "▶", color: "#10b981", label: "Iniciada" },
  finalizada: { icon: "✓", color: "#10b981", label: "Finalizada" },
  encerrar: { icon: "✕", color: "#94a3b8", label: "Encerrada (gestor)" },
  reagendar: { icon: "", color: "#3b82f6", label: "Reagendada" },
  cancelar: { icon: "", color: "#dc2626", label: "Cancelada" },
  transferida: { icon: "↔", color: "#0d9488", label: "Transferida" },
};

export function aiScoreColor(score) {
  if (score == null) return "#94a3b8";
  if (score >= 8.5) return "#10b981";
  if (score >= 7.0) return "#3b82f6";
  if (score >= 5.0) return "#f59e0b";
  return "#dc2626";
}

export function fmtDuration(min) {
  if (min == null) return "—";
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h > 0 ? `${h}h${String(m).padStart(2, "0")}` : `${m}min`;
}

export function fmtGap(min) {
  if (min == null) return "—";
  if (min < 60) return `${Math.round(min)}min`;
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return `${h}h${String(m).padStart(2, "0")}`;
}

export function todayLocalISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function formatBR(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

export function btnSm(color) {
  return { fontSize: 10, padding: "3px 7px", border: 0, borderRadius: 6, background: color, color: "white", fontWeight: 800, cursor: "pointer" };
}

/* Estilos pra tabelas printáveis */
export const thStyle = {
  padding: "5px 6px", textAlign: "left", fontWeight: 700,
  fontSize: 9.5, border: "1px solid #1e293b",
};
export const tdStyle = {
  padding: "5px 6px", border: "1px solid #e2e8f0",
  verticalAlign: "top", fontSize: 9.5, wordBreak: "break-word",
};
