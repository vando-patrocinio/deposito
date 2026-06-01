/* LousaStepIndicator — iter182. Sticky top bar do fluxo da OS.
   Mostra "Etapa X de N · [Nome]" + barra de progresso, conforme
   blueprint do design agent (Archetype "Swiss & High-Contrast").
   Aplica best practices 2026: thumb-zone friendly, progressive
   disclosure, large tap targets, high contrast outdoor.
*/
import React from "react";

const STEP_LABELS_FULL = {
  1: "Equipamento",
  2: "Localização CTO",
  3: "Porta CTO",
  4: "Finalização",
};

const STEP_LABELS_WITHDRAW = {
  1: "Retirada",
};

export default function LousaStepIndicator({
  step = 1,
  totalSteps = 4,
  variant = "full", // "full" | "withdraw"
  onStepBack = null,
  customLabel = null,
}) {
  const labels = variant === "withdraw"
    ? STEP_LABELS_WITHDRAW : STEP_LABELS_FULL;
  const label = customLabel || labels[step] || `Etapa ${step}`;
  const pct = Math.max(0, Math.min(100,
    Math.round((step / totalSteps) * 100)));

  return (
    <div data-testid="lousa-step-indicator" style={{
      position: "sticky", top: 0, zIndex: 40,
      background: "rgba(255,255,255,0.96)",
      backdropFilter: "blur(8px)",
      WebkitBackdropFilter: "blur(8px)",
      borderBottom: "1px solid #e2e8f0",
      padding: "10px 14px",
      marginBottom: 12,
      marginLeft: -12, marginRight: -12, marginTop: -8,
    }}>
      <div style={{ display: "flex", alignItems: "center",
                      justifyContent: "space-between", gap: 12,
                      marginBottom: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8,
                        minWidth: 0 }}>
          {onStepBack && step > 1 && (
            <button data-testid="step-indicator-back"
              onClick={onStepBack}
              aria-label="Voltar etapa"
              style={{ flex: "0 0 32px", width: 32, height: 32,
                         borderRadius: 999, border: "1px solid #e2e8f0",
                         background: "#f8fafc", color: "#475569",
                         fontSize: 16, cursor: "pointer",
                         display: "flex", alignItems: "center",
                         justifyContent: "center" }}>
              ←
            </button>
          )}
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 10.5, fontWeight: 700,
                            color: "#64748b", letterSpacing: 0.5,
                            textTransform: "uppercase" }}>
              Etapa {step} de {totalSteps}
            </div>
            <div data-testid="lousa-step-label" style={{
              fontSize: 14, fontWeight: 700, color: "#0f172a",
              lineHeight: 1.2, overflow: "hidden",
              textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>{label}</div>
          </div>
        </div>
        <div style={{ flexShrink: 0, fontSize: 11, fontWeight: 700,
                        color: "#0284c7" }}>
          {pct}%
        </div>
      </div>
      {/* Barra de progresso compacta */}
      <div style={{ height: 4, width: "100%", background: "#f1f5f9",
                      borderRadius: 999, overflow: "hidden" }}>
        <div data-testid="lousa-step-progress-bar" style={{
          height: "100%", width: `${pct}%`,
          background: "linear-gradient(90deg, #0284c7, #0ea5e9)",
          borderRadius: 999, transition: "width 300ms ease-out",
        }} />
      </div>
    </div>
  );
}
