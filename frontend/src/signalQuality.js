/* signalQuality.js — iter182. Helper centralizado para mapeamento de
   qualidade de sinal RX (dBm) → cores e label.

   Faixas alinhadas com best practices FTTH 2026 (definidas no backend
   em routes/smartolt.py::_live_signal_summary):
     excellent  rx >= -20
     good       -20 > rx >= -24
     warn       -24 > rx >= -27
     critical   -27 > rx >= -28
     bad        rx < -28
*/

export const QUALITY_STYLES = {
  excellent: {
    bg: "#bbf7d0", fg: "#14532d", border: "#22c55e",
    label: "Excelente",
  },
  good: {
    bg: "#dcfce7", fg: "#15803d", border: "#86efac",
    label: "Bom",
  },
  warn: {
    bg: "#fef3c7", fg: "#a16207", border: "#fde68a",
    label: "Atenção",
  },
  critical: {
    bg: "#ffedd5", fg: "#9a3412", border: "#fdba74",
    label: "Crítico",
  },
  bad: {
    bg: "#fee2e2", fg: "#b91c1c", border: "#fca5a5",
    label: "Falha iminente",
  },
  unknown: {
    bg: "#f1f5f9", fg: "#475569", border: "#cbd5e1",
    label: "—",
  },
};

export function styleForQuality(quality) {
  return QUALITY_STYLES[quality] || QUALITY_STYLES.unknown;
}

/* Para casos sem `quality` setado, calcula a partir do `rx_dbm` puro.
   Usa as mesmas faixas do backend. */
export function qualityFromRx(rx) {
  if (rx == null || isNaN(rx)) return "unknown";
  if (rx >= -20) return "excellent";
  if (rx >= -24) return "good";
  if (rx >= -27) return "warn";
  if (rx >= -28) return "critical";
  return "bad";
}
