/*
 * VersionBadge — iter209
 * Banner discreto no canto inferior direito mostrando a versão atualmente
 * deployada. Ajuda o usuário a confirmar que um deploy realmente entrou no
 * preview/produção (PWA Service Worker às vezes serve JS antigo).
 *
 * Como ler a versão: definida em /app/frontend/src/version.js (constante).
 * Para atualizar a versão, basta editar version.js. Em produção, ao clicar
 * no badge é feito Hard Reload (que limpa o cache do SW).
 */
import React from "react";
import { APP_VERSION, APP_BUILD_DATE } from "@/version";

// iter211ah — expõe a versão globalmente pra ErrorBoundary incluir no
// diagnóstico copiado pelo usuário.
if (typeof window !== "undefined") {
  window.__APP_VERSION__ = `${APP_VERSION} (${APP_BUILD_DATE})`;
}

export default function VersionBadge() {
  const [hidden, setHidden] = React.useState(false);
  if (hidden) return null;

  const onClick = () => {
    // Hard-reload contornando PWA cache
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
      title="Clique para forçar atualização (limpa cache PWA)"
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
