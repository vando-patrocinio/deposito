/*
 * VersionBadge — iter215
 * Pílula compacta no canto inferior direito que mostra a versão atual do
 * build. Visível APENAS para super_admin. Mantém `window.__APP_VERSION__`
 * acessível pra todos (usado pelo ErrorBoundary nos diagnósticos).
 *
 * Clicar no badge dá hard-reload (limpa cache PWA) — útil pra forçar
 * atualização quando o service worker grudou no JS antigo.
 */
import React from "react";
import { APP_VERSION, APP_BUILD_DATE } from "@/version";
import { useAuth } from "@/AuthContext";

// Expõe a versão globalmente para diagnóstico interno
if (typeof window !== "undefined") {
  window.__APP_VERSION__ = `${APP_VERSION} (${APP_BUILD_DATE})`;
}

export default function VersionBadge() {
  const auth = useAuth?.();
  const user = auth?.user;
  const [hidden, setHidden] = React.useState(false);

  // Só renderiza pra super_admin (ou se rota é portal público sem auth,
  // não mostra). is_super_admin é a flag canônica (vide App.js).
  if (hidden) return null;
  if (!user?.is_super_admin) return null;

  const onClick = () => {
    try {
      if ("serviceWorker" in navigator) {
        navigator.serviceWorker.getRegistrations().then((regs) => {
          regs.forEach((r) => r.unregister());
        });
      }
      if (typeof window !== "undefined" && window.caches) {
        window.caches.keys().then((ks) => ks.forEach((k) => window.caches.delete(k)));
      }
    } catch (_) { /* noop */ }
    setTimeout(() => window.location.reload(), 200);
  };

  return (
    <div
      data-testid="version-badge"
      onClick={onClick}
      title="Clique para forçar atualização (limpa cache PWA). Visível só para super_admin."
      style={{
        position: "fixed",
        right: 180,
        bottom: 10,
        zIndex: 9999,
        padding: "5px 9px",
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: 0.3,
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        background: "rgba(15, 23, 42, 0.72)",
        color: "#e2e8f0",
        border: "1px solid rgba(148, 163, 184, 0.25)",
        backdropFilter: "blur(6px)",
        WebkitBackdropFilter: "blur(6px)",
        cursor: "pointer",
        userSelect: "none",
        boxShadow: "0 2px 8px rgba(0,0,0,0.18)",
      }}
    >
      <span style={{ color: "#22c55e", marginRight: 5 }}>●</span>
      v {APP_VERSION} · {APP_BUILD_DATE}
      <span
        data-testid="version-badge-close"
        onClick={(e) => { e.stopPropagation(); setHidden(true); }}
        style={{
          marginLeft: 8,
          color: "#94a3b8",
          fontWeight: 400,
        }}
      >×</span>
    </div>
  );
}
