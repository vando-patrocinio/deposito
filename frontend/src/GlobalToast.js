/*
GlobalToast.js — iter211bg

Toaster minimal pra mensagens disparadas via:
  window.dispatchEvent(new CustomEvent("smartprov:toast", {
    detail: { kind: "info"|"success"|"warn"|"error",
               icon, title, message, durationMs? }
  }));

Ativado em qualquer parte do app sem precisar prop-drilling.
*/
import React, { useEffect, useState, useCallback } from "react";

export default function GlobalToast() {
  const [items, setItems] = useState([]);

  const push = useCallback((d) => {
    const id = Math.random().toString(36).slice(2, 10);
    // CTO 13/06/2026 — dedupe por título: se o último toast tiver mesmo
    // título e não tiver fechado ainda, não empilha. Resolve o spam de
    // "Acesso negado" em widgets de background.
    setItems((arr) => {
      const last = arr[arr.length - 1];
      if (last && last.title === d.title && last.message === d.message) {
        return arr; // já existe um igual, ignora
      }
      return [...arr, { id, ...d }];
    });
    const dur = Math.max(2000, Math.min(d?.durationMs || 5000, 20000));
    setTimeout(() => {
      setItems((arr) => arr.filter((x) => x.id !== id));
    }, dur);
  }, []);

  useEffect(() => {
    const h = (e) => push(e?.detail || {});
    window.addEventListener("smartprov:toast", h);
    // Sprint 3 — bridge interceptor http-error → toast
    const h2 = (e) => {
      const d = e?.detail || {};
      const titleMap = {
        forbidden: "Acesso negado",
        "rate-limited": "Limite atingido",
        unavailable: "Indisponível",
      };
      push({
        kind: d.status === 503 ? "warn" : "error",
        title: titleMap[d.kind] || `Erro ${d.status}`,
        message: d.message,
        durationMs: 5000,
      });
    };
    window.addEventListener("smartprov-http-error", h2);
    return () => {
      window.removeEventListener("smartprov:toast", h);
      window.removeEventListener("smartprov-http-error", h2);
    };
  }, [push]);

  return (
    <div data-testid="global-toast-container"
          style={{
            position: "fixed", bottom: 16, right: 16, zIndex: 99999,
            display: "flex", flexDirection: "column", gap: 8,
            maxWidth: "calc(100vw - 32px)",
          }}>
      {items.map((t) => (
        <div key={t.id} style={style(t.kind)}
              data-testid={`toast-${t.id}`}>
          <span style={{ fontSize: 20, lineHeight: 1, flexShrink: 0 }}>
            {t.icon || iconFor(t.kind)}
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            {t.title && (
              <div style={{ fontSize: 13, fontWeight: 800, marginBottom: 2 }}>
                {t.title}
              </div>
            )}
            <div style={{ fontSize: 12, lineHeight: 1.4, opacity: 0.9 }}>
              {t.message || ""}
            </div>
          </div>
          <button onClick={() => setItems((arr) => arr.filter((x) => x.id !== t.id))}
                  style={{ background: "transparent", border: 0, color: "inherit",
                            fontSize: 18, opacity: 0.7, cursor: "pointer", lineHeight: 1 }}>
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}

const palette = {
  info:    { bg: "#dbeafe", fg: "#1e3a8a", border: "#93c5fd" },
  success: { bg: "#dcfce7", fg: "#166534", border: "#86efac" },
  warn:    { bg: "#fef3c7", fg: "#78350f", border: "#fcd34d" },
  error:   { bg: "#fee2e2", fg: "#991b1b", border: "#fca5a5" },
};
const style = (kind) => {
  const p = palette[kind] || palette.info;
  return {
    background: p.bg, color: p.fg, border: `1px solid ${p.border}`,
    borderRadius: 12, padding: "10px 12px",
    display: "flex", alignItems: "flex-start", gap: 10,
    minWidth: 280, maxWidth: 420,
    boxShadow: "0 8px 24px rgba(15,23,42,.12)",
    animation: "smartprov-toast-in .25s ease",
  };
};
const iconFor = (k) => ({
  info: "ℹ️", success: "✅", warn: "️", error: "❌",
}[k] || "ℹ️");
