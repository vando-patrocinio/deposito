import React from "react";

export function Icon({ name }) {
  const icons = {
    phone: "📱", users: "👥", sheet: "📊", api: "🔌", tests: "✅", bell: "🔔",
    map: "📍", camera: "🤳", clock: "🕒", history: "📋", shield: "🛡️", sync: "🔄",
    user: "👤", export: "⬇️", alert: "⚠️", check: "✅", ip: "🌐", block: "🚫",
    network: "📡", gear: "⚙️", plus: "➕", trash: "🗑️", mail: "✉️",
  };
  return <span aria-hidden="true">{icons[name] || "•"}</span>;
}

export function StatusBadge({ children, status }) {
  const key = status || children;
  const map = {
    "Válido": "#dcfce7|#166534|#bbf7d0",
    "Offline sincronizado": "#e0f2fe|#075985|#bae6fd",
    "Offline": "#f1f5f9|#334155|#cbd5e1",
    "Pendente": "#fef3c7|#92400e|#fde68a",
    "Recusado": "#ffe4e6|#9f1239|#fecdd3",
    "Bloqueado": "#fee2e2|#991b1b|#fecaca",
    "Aprovado": "#dcfce7|#166534|#bbf7d0",
    "Extra": "#dcfce7|#166534|#bbf7d0",
    "Débito": "#ffe4e6|#9f1239|#fecdd3",
    "Regular": "#e0f2fe|#075985|#bae6fd",
    "Incompleto": "#fef3c7|#92400e|#fde68a",
    "Dentro da cerca": "#dcfce7|#166534|#bbf7d0",
    "Fora da cerca": "#fef3c7|#92400e|#fde68a",
    "Cerca não exigida": "#f8fafc|#334155|#e2e8f0",
  };
  const [bg, color, border] = (map[key] || "#f8fafc|#334155|#e2e8f0").split("|");
  return (
    <span style={{ background: bg, color, border: `1px solid ${border}`, borderRadius: 999, padding: "4px 10px", fontSize: 12, fontWeight: 800, whiteSpace: "nowrap" }}>
      {children || status}
    </span>
  );
}

// Design tokens compartilhados — uso interno (consistência de espaçamento/tipografia)
export const TOKENS = {
  radius: { sm: 10, md: 12, lg: 16, xl: 20, "2xl": 24 },
  space: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, "2xl": 32 },
  font: { xs: 11, sm: 12, base: 13, md: 14, lg: 16, xl: 18, "2xl": 22, "3xl": 28 },
  shadow: {
    sm: "0 1px 2px rgba(15,23,42,.04)",
    md: "0 4px 12px rgba(15,23,42,.06)",
    lg: "0 12px 28px rgba(15,23,42,.08)",
    xl: "0 24px 60px rgba(15,23,42,.12)",
  },
  color: {
    text: "#0f172a", muted: "#64748b", subtle: "#94a3b8",
    border: "#e2e8f0", borderStrong: "#cbd5e1", surface: "#ffffff", surfaceAlt: "#f8fafc",
    primary: "#0f172a", accent: "#0ea5e9", success: "#16a34a", warn: "#f59e0b", danger: "#e11d48",
  },
};

export function Button({ children, onClick, disabled, variant = "primary", style = {}, type = "button", "data-testid": testId, title }) {
  const styles = {
    primary: { background: "#0f172a", color: "white", border: "1px solid #0f172a" },
    secondary: { background: "white", color: "#0f172a", border: "1px solid #cbd5e1" },
    soft: { background: "#f1f5f9", color: "#0f172a", border: "1px solid #e2e8f0" },
    danger: { background: "#e11d48", color: "white", border: "1px solid #e11d48" },
    success: { background: "#16a34a", color: "white", border: "1px solid #16a34a" },
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      title={title}
      style={{
        ...styles[variant],
        padding: "9px 14px",
        borderRadius: 12,
        opacity: disabled ? 0.45 : 1,
        cursor: disabled ? "not-allowed" : "pointer",
        fontWeight: 700,
        fontSize: 13,
        letterSpacing: "0.01em",
        transition: "transform 120ms ease, box-shadow 120ms ease, opacity 120ms ease",
        display: "inline-flex", alignItems: "center", gap: 6,
        ...style,
      }}
      onMouseEnter={(e) => { if (!disabled) e.currentTarget.style.transform = "translateY(-1px)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.transform = "translateY(0)"; }}
    >
      {children}
    </button>
  );
}

export function Card({ title, children, style = {}, action, "data-testid": testId }) {
  return (
    <section data-testid={testId} style={{
      background: "white", border: "1px solid #e2e8f0", borderRadius: 16,
      padding: 18, boxShadow: "0 4px 12px rgba(15,23,42,.04)",
      marginBottom: 14, ...style,
    }}>
      {(title || action) && (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14, gap: 12, flexWrap: "wrap" }}>
          {title && <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, letterSpacing: "-0.01em", color: "#0f172a" }}>{title}</h3>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function Row({ label, value }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, borderBottom: "1px solid #f1f5f9", padding: "9px 0", alignItems: "center" }}>
      <span style={{ color: "#64748b" }}>{label}</span>
      <strong style={{ textAlign: "right" }}>{value}</strong>
    </div>
  );
}

export function Metric({ label, value }) {
  return (
    <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 14, padding: 14 }}>
      <div style={{ color: "#64748b", fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 800, marginTop: 6, color: "#0f172a", letterSpacing: "-0.01em" }}>{value}</div>
    </div>
  );
}

export function Field({ label, children }) {
  return (
    <label style={{ display: "block", marginBottom: 14 }}>
      <span style={{ display: "block", color: "#475569", fontSize: 12, fontWeight: 600, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.04em" }}>{label}</span>
      {children}
    </label>
  );
}

export const inputStyle = {
  width: "100%",
  padding: "9px 12px",
  borderRadius: 10,
  border: "1px solid #cbd5e1",
  fontSize: 14,
  fontFamily: "inherit",
  boxSizing: "border-box",
  transition: "border-color 120ms ease, box-shadow 120ms ease",
  outline: "none",
};

export function PhoneFrame({ children }) {
  return (
    <div style={{ width: "100%", maxWidth: 410, margin: "0 auto", background: "#020617", borderRadius: 38, padding: 12, boxShadow: "0 28px 60px rgba(15,23,42,.28)" }}>
      <div style={{ background: "#f8fafc", minHeight: 760, borderRadius: 30, overflow: "hidden" }}>
        <div style={{ height: 26, background: "#020617", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ width: 92, height: 5, background: "#334155", borderRadius: 99 }} />
        </div>
        {children}
      </div>
    </div>
  );
}

export function softButtonStyle() {
  return { background: "white", color: "#0f172a", border: "1px solid #e2e8f0", borderRadius: 22, boxShadow: "0 10px 22px rgba(15,23,42,.06)", cursor: "pointer", fontWeight: 900 };
}

export function fmtMin(min) {
  if (min == null || isNaN(min)) return "—";
  const sign = min < 0 ? "-" : "";
  const a = Math.abs(min);
  return `${sign}${Math.floor(a / 60)}h${String(a % 60).padStart(2, "0")}`;
}

export function AvatarZoomModal({ src, alt = "Foto do colaborador", onClose, caption }) {
  if (!src) return null;
  return (
    <div
      role="dialog"
      data-testid="avatar-zoom-modal"
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(2,6,23,.85)", zIndex: 10000,
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 20, cursor: "zoom-out",
      }}
    >
      <div onClick={(e) => e.stopPropagation()} style={{ maxWidth: "92vw", maxHeight: "92vh", position: "relative", display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
        <img
          src={src}
          alt={alt}
          data-testid="avatar-zoom-img"
          style={{
            maxWidth: "100%", maxHeight: "80vh", objectFit: "contain",
            borderRadius: 18, border: "4px solid white",
            boxShadow: "0 30px 80px rgba(0,0,0,.55)",
          }}
        />
        {caption && <div style={{ color: "white", fontWeight: 700, fontSize: 14 }}>{caption}</div>}
        <button
          onClick={onClose}
          data-testid="avatar-zoom-close"
          aria-label="Fechar"
          style={{
            position: "absolute", top: -10, right: -10,
            width: 40, height: 40, borderRadius: "50%",
            background: "white", color: "#0f172a", border: "none",
            fontSize: 22, fontWeight: 900, cursor: "pointer",
            boxShadow: "0 8px 18px rgba(0,0,0,.4)",
          }}
        >×</button>
      </div>
    </div>
  );
}
