/**
 * CTO 12/06/2026 — Skeleton screens (placeholders animados) substituindo
 * spinners genéricos. Melhora a UX percebida: usuário vê a forma do conteúdo
 * antes de carregar de fato, reduzindo a sensação de "espera vazia".
 *
 * Inspirado em LinkedIn/YouTube/Facebook: blocos cinza com shimmer.
 *
 * Uso:
 *   <Skeleton width="100%" height={20} />
 *   <SkeletonCard />
 *   <SkeletonTable rows={5} cols={4} />
 *   <SkeletonList items={6} />
 */
import React from "react";

// CSS injection (1 vez) — shimmer animation global
if (typeof document !== "undefined" && !document.getElementById("__skeleton_css")) {
  const style = document.createElement("style");
  style.id = "__skeleton_css";
  style.textContent = `
    @keyframes skeleton-shimmer {
      0%   { background-position: -200% 0; }
      100% { background-position:  200% 0; }
    }
    .skeleton-shimmer {
      background: linear-gradient(
        90deg,
        rgba(226, 232, 240, 0.55) 0%,
        rgba(241, 245, 249, 0.85) 50%,
        rgba(226, 232, 240, 0.55) 100%
      );
      background-size: 200% 100%;
      animation: skeleton-shimmer 1.4s ease-in-out infinite;
      border-radius: 6px;
    }
  `;
  document.head.appendChild(style);
}

export function Skeleton({
  width = "100%", height = 16, radius = 6, style = {},
  testid = "skeleton",
}) {
  return (
    <div
      data-testid={testid}
      className="skeleton-shimmer"
      style={{
        width, height, borderRadius: radius, ...style,
      }}
    />
  );
}

export function SkeletonCircle({ size = 40, style = {} }) {
  return <Skeleton width={size} height={size} radius={size} style={style} />;
}

/** Card de Colaborador/Listagem genérica. */
export function SkeletonCard({ height = 80 }) {
  return (
    <div data-testid="skeleton-card" style={{
      display: "flex", gap: 12, padding: 14,
      background: "white", border: "1px solid #e2e8f0",
      borderRadius: 12, marginBottom: 8, alignItems: "center",
    }}>
      <SkeletonCircle size={48} />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
        <Skeleton width="50%" height={14} />
        <Skeleton width="80%" height={11} />
        <Skeleton width="35%" height={10} />
      </div>
      <Skeleton width={70} height={28} radius={8} />
    </div>
  );
}

/** Lista vertical de cards. */
export function SkeletonList({ items = 5 }) {
  return (
    <div data-testid="skeleton-list">
      {Array.from({ length: items }).map((_, i) => <SkeletonCard key={i} />)}
    </div>
  );
}

/** Tabela com header + rows. */
export function SkeletonTable({ rows = 6, cols = 4 }) {
  return (
    <div data-testid="skeleton-table" style={{
      background: "white", border: "1px solid #e2e8f0",
      borderRadius: 12, overflow: "hidden",
    }}>
      <div style={{
        display: "grid", gridTemplateColumns: `repeat(${cols}, 1fr)`,
        gap: 12, padding: 14, background: "#f8fafc",
        borderBottom: "1px solid #e2e8f0",
      }}>
        {Array.from({ length: cols }).map((_, i) => (
          <Skeleton key={i} height={11} width="70%" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} style={{
          display: "grid", gridTemplateColumns: `repeat(${cols}, 1fr)`,
          gap: 12, padding: 14,
          borderBottom: r === rows - 1 ? "none" : "1px solid #f1f5f9",
        }}>
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton key={c} height={13} width={c === 0 ? "60%" : "85%"} />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Header do app (logo + nav placeholder) — usado durante boot. */
export function SkeletonAppShell() {
  return (
    <div data-testid="skeleton-app-shell" style={{
      minHeight: "100vh", background: "#f8fafc",
      display: "flex", flexDirection: "column",
    }}>
      <div style={{
        height: 64, background: "white",
        borderBottom: "1px solid #e2e8f0",
        display: "flex", alignItems: "center", padding: "0 24px", gap: 20,
      }}>
        <Skeleton width={120} height={28} />
        <div style={{ flex: 1 }} />
        <Skeleton width={32} height={32} radius={16} />
        <Skeleton width={120} height={32} radius={8} />
      </div>
      <div style={{ display: "flex", flex: 1 }}>
        <div style={{
          width: 240, background: "white",
          borderRight: "1px solid #e2e8f0", padding: 16,
          display: "flex", flexDirection: "column", gap: 8,
        }}>
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} width="100%" height={32} radius={8} />
          ))}
        </div>
        <div style={{ flex: 1, padding: 24 }}>
          <Skeleton width="40%" height={28} style={{ marginBottom: 16 }} />
          <Skeleton width="60%" height={14} style={{ marginBottom: 24 }} />
          <SkeletonList items={5} />
        </div>
      </div>
    </div>
  );
}

export default Skeleton;
