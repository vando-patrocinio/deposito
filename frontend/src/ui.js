import React from "react";
import {
  Smartphone, Users, BarChart3, Plug, CheckCircle2, Bell,
  MapPin, Camera, Clock, History, Shield, RefreshCcw,
  User, Download, AlertTriangle, Globe, Ban, Network,
  Settings, Plus, Trash2, Mail, Map, FileText, Activity,
  Boxes, Bot, ClipboardList, ScanFace, Building2, Cog, LogOut,
  Search, ChevronRight,
} from "lucide-react";

/* ------------------------------------------------------------
   Lucide-based Icon kit (replaces all emoji icons)
------------------------------------------------------------ */
const ICON_MAP = {
  phone: Smartphone, users: Users, sheet: BarChart3, api: Plug, tests: CheckCircle2,
  bell: Bell, map: MapPin, camera: Camera, clock: Clock, history: History,
  shield: Shield, sync: RefreshCcw, user: User, export: Download, alert: AlertTriangle,
  check: CheckCircle2, ip: Globe, block: Ban, network: Network, gear: Settings,
  plus: Plus, trash: Trash2, mail: Mail, leaflet: Map, file: FileText, activity: Activity,
  boxes: Boxes, bot: Bot, clipboard: ClipboardList, face: ScanFace, building: Building2,
  cog: Cog, logout: LogOut, search: Search, chevron: ChevronRight,
};

export function Icon({ name, size = 16, className = "", style = {} }) {
  const C = ICON_MAP[name];
  if (!C) return <span aria-hidden="true" style={{ width: size, height: size, display: "inline-block" }} />;
  return <C size={size} strokeWidth={1.75} className={className} style={style} aria-hidden="true" />;
}

/* ------------------------------------------------------------
   StatusBadge — pill style mapped to status semantics
------------------------------------------------------------ */
const STATUS_MAP = {
  "Válido": "success", "Aprovado": "success", "Extra": "success",
  "Dentro da cerca": "success",
  "Offline sincronizado": "info", "Regular": "info",
  "Offline": "neutral", "Cerca não exigida": "neutral",
  "Pendente": "warning", "Incompleto": "warning", "Fora da cerca": "warning",
  "Recusado": "danger", "Bloqueado": "danger", "Débito": "danger",
};

export function StatusBadge({ children, status }) {
  const key = status || children;
  const variant = STATUS_MAP[key] || "neutral";
  return <span className={`pill pill--${variant}`}>{children || status}</span>;
}

/* ------------------------------------------------------------
   Design tokens (kept for backwards compat; use CSS vars when possible)
------------------------------------------------------------ */
export const TOKENS = {
  radius: { sm: 6, md: 8, lg: 12, xl: 16, "2xl": 20 },
  space: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, "2xl": 32 },
  font: { xs: 11, sm: 12, base: 13, md: 14, lg: 16, xl: 18, "2xl": 22, "3xl": 28 },
  shadow: {
    xs: "0 1px 2px rgba(11,18,32,.04)",
    sm: "0 1px 3px rgba(11,18,32,.06), 0 1px 2px rgba(11,18,32,.04)",
    md: "0 4px 12px rgba(11,18,32,.06)",
    lg: "0 12px 28px rgba(11,18,32,.08)",
  },
  color: {
    text: "#0b1220", muted: "#475569", subtle: "#94a3b8",
    border: "#e6e8ee", borderStrong: "#d4d7df",
    surface: "#ffffff", surfaceAlt: "#f6f7f9", surfaceMuted: "#f1f5f9",
    primary: "#0b1220", accent: "#0d9488", accentHover: "#0f766e",
    success: "#16a34a", warn: "#d97706", danger: "#dc2626", info: "#0369a1",
  },
};

/* ------------------------------------------------------------
   Button — uses .btn classes from index.css
------------------------------------------------------------ */
export function Button({
  children, onClick, disabled, variant = "primary", size = "md",
  style = {}, type = "button", "data-testid": testId, title, className = "",
}) {
  const variantClass = {
    primary: "btn-primary",
    accent: "btn-accent",
    secondary: "btn-secondary",
    soft: "btn-secondary",
    ghost: "btn-ghost",
    danger: "btn-danger",
    success: "btn-accent",
  }[variant] || "btn-secondary";
  const sizeClass = size === "sm" ? "btn-sm" : size === "lg" ? "btn-lg" : "";
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      title={title}
      className={`btn ${variantClass} ${sizeClass} ${className}`.trim()}
      style={style}
    >
      {children}
    </button>
  );
}

/* ------------------------------------------------------------
   Card — content surface
------------------------------------------------------------ */
export function Card({ title, subtitle, children, style = {}, action, "data-testid": testId, padding = 18, className = "" }) {
  return (
    <section
      data-testid={testId}
      className={`surface ${className}`.trim()}
      style={{ padding, marginBottom: 14, ...style }}
    >
      {(title || action || subtitle) && (
        <div style={{
          display: "flex", justifyContent: "space-between",
          alignItems: subtitle ? "flex-start" : "center",
          gap: 12, flexWrap: "wrap",
          marginBottom: children ? 14 : 0,
        }}>
          <div>
            {title && (
              <h3 className="sp-display" style={{ margin: 0, fontSize: 16, fontWeight: 600, letterSpacing: "-0.018em", color: "var(--text-primary)" }}>{title} </h3>
            )}
            {subtitle && (
              <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--text-secondary)" }}>{subtitle}</p>
            )}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function Row({ label, value }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", gap: 12,
      borderBottom: "1px solid var(--border-default)", padding: "10px 0",
      alignItems: "center",
    }}>
      <span style={{ color: "var(--text-secondary)", fontSize: 13 }}>{label}</span>
      <strong style={{ textAlign: "right", fontSize: 13, color: "var(--text-primary)" }}>{value}</strong>
    </div>
  );
}

/* ------------------------------------------------------------
   Metric — KPI / stat card
------------------------------------------------------------ */
export function Metric({ label, value, hint, mono = false }) {
  return (
    <div className="stat-card">
      <div className="stat-card__label">{label}</div>
      <div className="stat-card__value" style={{ fontFamily: mono ? "JetBrains Mono, monospace" : undefined }}>{value}</div>
      {hint && <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>{hint}</div>}
    </div>
  );
}

export function Field({ label, children, hint }) {
  return (
    <label style={{ display: "block", marginBottom: 14 }}>
      <span className="field-label">{label}</span>
      {children}
      {hint && <span style={{ display: "block", marginTop: 4, fontSize: 11, color: "var(--text-muted)" }}>{hint}</span>}
    </label>
  );
}

export const inputStyle = {
  width: "100%",
  padding: "0 12px",
  height: 36,
  borderRadius: 8,
  border: "1px solid var(--border-strong)",
  background: "var(--bg-surface)",
  color: "var(--text-primary)",
  fontSize: 13,
  fontFamily: "inherit",
  boxSizing: "border-box",
  outline: "none",
  transition: "border-color 140ms ease, box-shadow 140ms ease",
};

export function PhoneFrame({ children }) {
  return (
    <div style={{
      width: "100%", maxWidth: 410, margin: "0 auto",
      background: "#0b1220", borderRadius: 38, padding: 12,
      boxShadow: "0 28px 60px rgba(11,18,32,.28)",
    }}>
      <div style={{ background: "var(--bg-app)", minHeight: 760, borderRadius: 30, overflow: "hidden" }}>
        <div style={{ height: 26, background: "#0b1220", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ width: 92, height: 5, background: "#334155", borderRadius: 99 }} />
        </div>
        {children}
      </div>
    </div>
  );
}

export function softButtonStyle() {
  return {
    background: "var(--bg-surface)", color: "var(--text-primary)",
    border: "1px solid var(--border-default)", borderRadius: 22,
    boxShadow: "var(--shadow-sm)", cursor: "pointer", fontWeight: 700,
  };
}

export function fmtMin(min) {
  if (min == null || isNaN(min)) return "—";
  const sign = min < 0 ? "-" : "";
  const a = Math.abs(min);
  return `${sign}${Math.floor(a / 60)}h${String(a % 60).padStart(2, "0")}`;
}

export function AvatarZoomModal({ src, alt = "Foto do colaborador", onClose, caption }) {
  const [imgError, setImgError] = React.useState(false);
  React.useEffect(() => { setImgError(false); }, [src]);
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
        {imgError ? (
          <div
            data-testid="avatar-zoom-fallback"
            style={{
              width: "min(80vw, 360px)", height: "min(80vw, 360px)",
              borderRadius: 18, border: "4px solid white",
              background: "#0f172a", color: "white",
              display: "grid", placeItems: "center", textAlign: "center",
              padding: 24, fontSize: 14, lineHeight: 1.5,
              boxShadow: "0 30px 80px rgba(0,0,0,.55)",
            }}
          >
            Foto indisponível.<br/>
            Peça ao colaborador uma nova selfie para atualizar a foto do crachá.
          </div>
        ) : (
          <img
            src={src}
            alt={alt}
            data-testid="avatar-zoom-img"
            onError={() => setImgError(true)}
            style={{
              maxWidth: "min(92vw, 480px)", maxHeight: "80vh",
              width: "auto", height: "auto",
              objectFit: "cover", objectPosition: "center 28%",
              borderRadius: 18, border: "4px solid white",
              boxShadow: "0 30px 80px rgba(0,0,0,.55)",
              background: "#0f172a",
            }}
          />
        )}
        {caption && <div style={{ color: "white", fontWeight: 600, fontSize: 13 }}>{caption}</div>}
        <button
          onClick={onClose}
          data-testid="avatar-zoom-close"
          aria-label="Fechar"
          style={{
            position: "absolute", top: -10, right: -10,
            width: 40, height: 40, borderRadius: "50%",
            background: "white", color: "#0b1220", border: "none",
            fontSize: 22, fontWeight: 800, cursor: "pointer",
            boxShadow: "0 8px 18px rgba(0,0,0,.4)",
          }}
        >×</button>
      </div>
    </div>
  );
}
