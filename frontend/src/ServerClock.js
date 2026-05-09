import React from "react";
import { useServerNow } from "@/serverTime";

/**
 * Relógio sincronizado com o servidor — usa o singleton serverTime.js.
 * NUNCA exibe relógio do dispositivo (anti-tampering).
 */
export default function ServerClock({ compact = false }) {
  const { date, tz, synced } = useServerNow(1000);

  let label = "--:--";
  let datePart = "";
  try {
    label = date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: compact ? undefined : "2-digit", timeZone: tz });
    datePart = date.toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit", timeZone: tz });
  } catch { /* ignore */ }

  return (
    <div
      data-testid="server-clock"
      title={synced ? `Hora do servidor (${tz})` : "Sincronizando com servidor..."}
      style={{
        display: "inline-flex", alignItems: "center", gap: 8,
        padding: compact ? "4px 10px" : "6px 12px",
        background: synced ? "linear-gradient(135deg,#0f172a,#1e293b)" : "#94a3b8",
        color: "white", borderRadius: 999,
        boxShadow: "0 2px 8px rgba(15,23,42,.18)",
        fontVariantNumeric: "tabular-nums",
      }}
    >
      <span style={{
        width: 8, height: 8, borderRadius: "50%",
        background: synced ? "#10b981" : "#f59e0b",
        boxShadow: synced ? "0 0 0 3px rgba(16,185,129,.25)" : "0 0 0 3px rgba(245,158,11,.25)",
        animation: synced ? "pulse 2.5s ease-in-out infinite" : "none",
      }} />
      <strong style={{ fontSize: compact ? 13 : 15, letterSpacing: 0.4 }}>{label}</strong>
      {!compact && datePart && (
        <span style={{ fontSize: 10, color: "#cbd5e1", textTransform: "capitalize" }}>{datePart}</span>
      )}
    </div>
  );
}
