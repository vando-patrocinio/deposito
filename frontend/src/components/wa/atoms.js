/**
 * components/wa/atoms.js — Componentes atômicos do WhatsApp Chat
 *
 * Extraído de WhatsAppChatLayout.js em iter106 (refactor):
 *  - avatarColor / Avatar
 *  - ChannelBadge
 *  - IconBtn
 *  - StatusPill / StatCard / Section / FieldRow / TicketHistRow
 *  - _kpiCsatColor / _kpiFmtSecs
 *  - extractErrorFromAxios
 *  - _findPrevUserQuestion
 *
 * Mantém props/API idênticas — sem mudança de comportamento.
 */
import React, { useState } from "react";
import { Bot } from "lucide-react";

// ---------------------------------------------------------------------------
// Avatar
// ---------------------------------------------------------------------------
export function avatarColor(name) {
  let h = 0;
  for (const c of (name || "")) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h}, 55%, 55%)`;
}

export function Avatar({ name, src, size = 38, isAi = false, ring = false }) {
  const initials = (name || "?").split(/\s+/)
    .filter(Boolean).slice(0, 2)
    .map((p) => p[0]).join("").toUpperCase() || "?";
  return (
    <div style={{
      width: size, height: size, borderRadius: "50%",
      background: src ? `url(${src}) center/cover` : avatarColor(name),
      color: "#fff",
      display: "grid", placeItems: "center",
      fontSize: size * 0.36, fontWeight: 700,
      flexShrink: 0,
      border: ring ? "2px solid #16a34a" : "none",
      position: "relative",
    }}>
      {!src && initials}
      {isAi && (
        <span style={{
          position: "absolute", bottom: -2, right: -2,
          background: "#0d9488", color: "#fff",
          width: size * 0.45, height: size * 0.45, borderRadius: "50%",
          display: "grid", placeItems: "center",
          border: "2px solid var(--bg-surface)",
        }}>
          <Bot size={size * 0.22} strokeWidth={2.5} />
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ChannelBadge — pílula com identificação do canal (Baileys/Twilio/Meta/etc)
// ---------------------------------------------------------------------------
export function ChannelBadge({ channel, small }) {
  if (!channel) return null;
  const map = {
    baileys: { label: "Baileys", color: "#15803d", bg: "#f0fdf4", border: "#bbf7d0" },
    twilio: { label: "Twilio", color: "#b91c1c", bg: "#fef2f2", border: "#fecaca" },
    meta_whatsapp_cloud: { label: "Meta Cloud", color: "#0369a1", bg: "#eff6ff", border: "#bfdbfe" },
    meta_messenger: { label: "Messenger", color: "#0369a1", bg: "#eff6ff", border: "#bfdbfe" },
    meta_instagram: { label: "Instagram", color: "#7c3aed", bg: "#faf5ff", border: "#e9d5ff" },
  };
  const info = map[channel] || { label: channel, color: "#64748b", bg: "#f8fafc", border: "#e2e8f0" };
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 3,
      padding: small ? "1px 5px" : "2px 7px",
      borderRadius: 4, fontSize: small ? 8.5 : 10, fontWeight: 700,
      color: info.color, background: info.bg,
      border: `1px solid ${info.border}`,
      letterSpacing: 0.3, textTransform: "uppercase",
      marginBottom: small ? 3 : 0, marginRight: 4,
    }}>
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: info.color }} />
      {info.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Helper: encontra a última mensagem inbound (do cliente) ANTES da bolha
// que está sendo corrigida — essa é a "pergunta" que originou a resposta.
// ---------------------------------------------------------------------------
export function _findPrevUserQuestion(timeline, idx) {
  for (let i = idx - 1; i >= 0; i--) {
    const t = timeline[i];
    if (t._kind === "coaching") continue;
    if (t.direction === "inbound" && t.text) return t.text;
  }
  return "";
}

// ---------------------------------------------------------------------------
// IconBtn — botão circular com tooltip no hover
// ---------------------------------------------------------------------------
export function IconBtn({ icon, tooltip, onClick, disabled, variant = "default",
                                hoverColor, ...rest }) {
  const [hover, setHover] = useState(false);
  const isPrimary = variant === "primary";
  const baseColor = isPrimary ? "var(--bg-surface)" : "var(--text-secondary)";
  const baseBg = isPrimary ? "var(--text-primary)" : "transparent";
  const baseBorder = isPrimary ? "var(--text-primary)" : "var(--border-default)";
  const hoverC = hoverColor || (isPrimary ? baseColor : "var(--text-primary)");
  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button
        onClick={onClick}
        disabled={disabled}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          width: 32, height: 32, borderRadius: 8,
          background: baseBg,
          color: hover && !disabled && !isPrimary ? hoverC : baseColor,
          border: `1px solid ${hover && !disabled && !isPrimary ? hoverC : baseBorder}`,
          cursor: disabled ? "not-allowed" : "pointer",
          opacity: disabled ? 0.5 : 1,
          transition: "color 0.15s, border-color 0.15s, transform 0.15s",
          transform: hover && !disabled ? "translateY(-1px)" : "none",
        }}
        {...rest}
      >
        {icon}
      </button>
      {hover && tooltip && (
        <div role="tooltip"
              style={{
                position: "absolute", top: "calc(100% + 6px)", right: 0,
                background: "rgba(15,23,42,.95)", color: "white",
                padding: "5px 10px", borderRadius: 6,
                fontSize: 11, fontWeight: 500,
                whiteSpace: "nowrap", maxWidth: 280,
                pointerEvents: "none", zIndex: 100,
                boxShadow: "0 6px 18px rgba(0,0,0,.25)",
              }}>
          {tooltip}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// StatusPill / StatCard / Section / FieldRow / TicketHistRow
// ---------------------------------------------------------------------------
export function StatusPill({ status }) {
  const s = String(status || "").toLowerCase();
  const isActive = s === "ativo";
  const isBlocked = s === "bloqueado";
  return (
    <span style={{
      fontSize: 10, fontWeight: 700,
      padding: "2px 8px", borderRadius: 4,
      background: isActive ? "rgba(34,197,94,.15)"
        : isBlocked ? "rgba(220,38,38,.15)"
        : "rgba(148,163,184,.15)",
      color: isActive ? "#16a34a"
        : isBlocked ? "#dc2626"
        : "#64748b",
      textTransform: "uppercase", letterSpacing: 0.5,
    }}>{status || "—"}</span>
  );
}

export function StatCard({ label, value, color, sub }) {
  return (
    <div style={{
      padding: "10px 12px", borderRadius: 8,
      border: "1px solid var(--border-default)",
      background: "var(--bg-surface-2)",
    }}>
      <div style={{ fontSize: 10, color: "var(--text-muted)",
                     fontWeight: 600, textTransform: "uppercase",
                     letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700, marginTop: 4,
                     color: color || "var(--text-primary)",
                     letterSpacing: "-0.01em" }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

export function Section({ title, icon: Ico, children }) {
  return (
    <div>
      <div style={{
        fontSize: 10, fontWeight: 700, color: "var(--text-muted)",
        textTransform: "uppercase", letterSpacing: 0.6,
        display: "flex", alignItems: "center", gap: 6,
        marginBottom: 8,
        paddingBottom: 6,
        borderBottom: "1px solid var(--border-default)",
      }}>
        {Ico && <Ico size={11} strokeWidth={2} />}
        {title}
      </div>
      <div style={{ display: "grid", gap: 4 }}>{children}</div>
    </div>
  );
}

export function FieldRow({ label, value, mono, valueColor }) {
  if (value == null || value === "") return null;
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "140px 1fr", gap: 12,
      fontSize: 12, padding: "3px 0", alignItems: "baseline",
    }}>
      <span style={{ color: "var(--text-muted)", fontWeight: 500 }}>{label}</span>
      <span style={{
        color: valueColor || "var(--text-primary)",
        fontWeight: valueColor && valueColor !== "var(--text-primary)" ? 600 : 500,
        fontFamily: mono ? "ui-monospace, monospace" : "inherit",
        wordBreak: "break-word",
      }}>{value}</span>
    </div>
  );
}

export function TicketHistRow({ ticket }) {
  const d = ticket.created_at
    ? new Date(ticket.created_at).toLocaleDateString("pt-BR",
        { day: "2-digit", month: "2-digit", year: "2-digit" })
    : "—";
  const isOpen = ["pendente", "aberta", "aguardando_atendimento"].includes(ticket.status);
  const closed = ticket.closed_at;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "8px 10px", borderRadius: 6,
      background: "var(--bg-surface-2)",
      border: "1px solid var(--border-default)",
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: "50%",
        background: isOpen ? "#f59e0b" : closed ? "#16a34a" : "#94a3b8",
        flexShrink: 0,
      }} />
      <span style={{ fontSize: 11, color: "var(--text-muted)",
                       fontFamily: "ui-monospace, monospace",
                       width: 64, flexShrink: 0 }}>{d}</span>
      <span style={{ fontSize: 11, fontWeight: 600,
                       color: "var(--text-primary)",
                       textTransform: "uppercase",
                       letterSpacing: 0.3,
                       width: 80, flexShrink: 0 }}>
        {ticket.type || "—"}
      </span>
      <span style={{ flex: 1, fontSize: 12, color: "var(--text-secondary)",
                       overflow: "hidden", textOverflow: "ellipsis",
                       whiteSpace: "nowrap" }}>
        {ticket.client_snapshot?.relato || ticket.outcome || "—"}
      </span>
      <span style={{
        fontSize: 10, fontWeight: 700,
        padding: "2px 7px", borderRadius: 4,
        background: isOpen ? "rgba(245,158,11,.15)" : "rgba(148,163,184,.15)",
        color: isOpen ? "#d97706" : "#64748b",
        textTransform: "uppercase", letterSpacing: 0.4,
        flexShrink: 0,
      }}>{ticket.status || "?"}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// KPI helpers
// ---------------------------------------------------------------------------
export function _kpiCsatColor(v) {
  if (v == null) return "var(--text-muted)";
  if (v >= 4.5) return "#16a34a";
  if (v >= 3.5) return "#ca8a04";
  return "#dc2626";
}

export function _kpiFmtSecs(s) {
  if (s == null) return "—";
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return s < 3600 ? `${m}m ${s % 60}s` : `${Math.floor(m / 60)}h${m % 60}m`;
}

// ---------------------------------------------------------------------------
// extractErrorFromAxios — normaliza erros vindos do axios em string legível
// ---------------------------------------------------------------------------
export function extractErrorFromAxios(e) {
  const d = e?.response?.data?.detail ?? e?.response?.data ?? e?.message;
  if (!d) return "Erro desconhecido.";
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d.map((x) => {
      if (typeof x === "string") return x;
      const loc = Array.isArray(x?.loc) ? x.loc.filter((y) => y !== "body").join(".") : "";
      const msg = x?.msg || x?.message || JSON.stringify(x);
      return loc ? `${loc}: ${msg}` : msg;
    }).filter(Boolean).join(" · ");
  }
  if (typeof d === "object") {
    return d.msg || d.message || d.error || d.detail || JSON.stringify(d);
  }
  return String(d);
}
