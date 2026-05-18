/**
 * Dashboard2026 — componentes compartilhados para painéis no estilo
 * "Summary First → Movement → Detail" usado em Movimento (estoque),
 * Financeiro (Fluxo de Caixa) e Rede IA. Reúne KPI cards contextuais,
 * sparklines SVG inline, alertas semafóricos e legendas.
 */
import React from "react";

const TONE_PALETTE = {
  good: { bar: "#10b981", chip: "#dcfce7", chipC: "#15803d" },
  warn: { bar: "#d97706", chip: "#fef3c7", chipC: "#a16207" },
  bad:  { bar: "#dc2626", chip: "#fee2e2", chipC: "#b91c1c" },
  info: { bar: "#0ea5e9", chip: "#dbeafe", chipC: "#1e40af" },
};

export function KpiCard({
  testId, label, value, unit, tone = "info", delta, deltaSuffix = "%",
  sparkline, sparkColor, progress, hint, icon,
}) {
  const t = TONE_PALETTE[tone] || TONE_PALETTE.info;
  return (
    <div data-testid={testId} style={{
      background: "#fff", borderRadius: 14, padding: 14,
      border: "1px solid #e2e8f0",
      boxShadow: "0 1px 2px rgba(15,23,42,.04)",
      borderTop: `3px solid ${t.bar}`,
      display: "flex", flexDirection: "column", gap: 6,
      minHeight: 110, minWidth: 0,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "flex-start", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6,
                          fontSize: 10.5, fontWeight: 800, color: "#64748b",
                          textTransform: "uppercase", letterSpacing: 0.4 }}>
          {icon && <span>{icon}</span>}
          <span>{label}</span>
        </div>
        {delta != null && (
          <span style={{
            background: delta >= 0 ? "#dcfce7" : "#fee2e2",
            color: delta >= 0 ? "#15803d" : "#b91c1c",
            fontSize: 10.5, fontWeight: 800,
            padding: "2px 6px", borderRadius: 999,
            fontVariantNumeric: "tabular-nums",
          }}>
            {delta >= 0 ? "↑" : "↓"} {Math.abs(delta)}{deltaSuffix}
          </span>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "baseline",
                      gap: 4, marginTop: 2, minWidth: 0 }}>
        <span style={{ fontSize: 26, fontWeight: 800, color: "#0f172a",
                          fontVariantNumeric: "tabular-nums",
                          lineHeight: 1, overflow: "hidden",
                          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {value}
        </span>
        {unit && <span style={{ fontSize: 12, color: "#94a3b8",
                                    fontWeight: 600 }}>{unit}</span>}
      </div>
      {sparkline && sparkline.some && sparkline.some((v) => v > 0) && (
        <Sparkline values={sparkline} color={sparkColor || t.bar} />
      )}
      {progress != null && (
        <div style={{ height: 6, background: "#f1f5f9", borderRadius: 999,
                          overflow: "hidden", marginTop: 4 }}>
          <div style={{ width: `${Math.min(100, Math.max(0, progress))}%`,
                          height: "100%", background: t.bar,
                          transition: "width .35s ease" }} />
        </div>
      )}
      {hint && (
        <div style={{ fontSize: 10.5, color: "#94a3b8", marginTop: "auto",
                          lineHeight: 1.3 }}>{hint}</div>
      )}
    </div>
  );
}

export function Sparkline({ values = [], color = "#0ea5e9", height = 30 }) {
  if (!values || !values.length) return null;
  if (!values.some((v) => v > 0)) return null;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = Math.max(1, max - min);
  const w = 100, h = height;
  const step = w / Math.max(1, values.length - 1);
  const points = values.map((v, i) => {
    const x = i * step;
    const y = h - ((v - min) / range) * (h - 4) - 2;
    return `${x},${y}`;
  }).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none"
         style={{ width: "100%", height, marginTop: 4 }}>
      <polyline points={points} fill="none" stroke={color}
                strokeWidth="1.6" strokeLinejoin="round"
                strokeLinecap="round" />
      <polyline
        points={`0,${h} ${points} ${w},${h}`}
        fill={color} fillOpacity="0.08" stroke="none" />
    </svg>
  );
}

export function AlertCard({ tone = "warn", icon, title, detail, testId }) {
  const tones = {
    bad: { bg: "#fef2f2", border: "#fca5a5", color: "#991b1b" },
    warn: { bg: "#fffbeb", border: "#fcd34d", color: "#92400e" },
    info: { bg: "#eff6ff", border: "#93c5fd", color: "#1e3a8a" },
    good: { bg: "#f0fdf4", border: "#86efac", color: "#15803d" },
  };
  const t = tones[tone] || tones.info;
  return (
    <div data-testid={testId} style={{
      padding: 12, borderRadius: 10, background: t.bg,
      border: `1px solid ${t.border}`, color: t.color,
      display: "flex", gap: 10, alignItems: "flex-start",
    }}>
      <div style={{ fontSize: 18, lineHeight: 1 }}>{icon}</div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 800 }}>{title}</div>
        {detail && (
          <div style={{ fontSize: 11, opacity: 0.85, marginTop: 2,
                          lineHeight: 1.4 }}>{detail}</div>
        )}
      </div>
    </div>
  );
}

export function Legend({ color, label, value }) {
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{ width: 10, height: 10, borderRadius: 3,
                        background: color, display: "inline-block" }} />
      <span style={{ fontWeight: 700, color: "#0f172a" }}>{value}</span>
      <span style={{ opacity: 0.7 }}>{label}</span>
    </div>
  );
}

export function StatRow({ label, value, color = "#0f172a" }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between",
                       padding: "6px 0",
                       borderBottom: "1px dashed #f1f5f9" }}>
      <span style={{ fontSize: 12, color: "#64748b" }}>{label}</span>
      <span style={{ fontSize: 12.5, fontWeight: 800, color,
                       fontVariantNumeric: "tabular-nums" }}>{value}</span>
    </div>
  );
}
