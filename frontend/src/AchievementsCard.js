import React, { useEffect, useState } from "react";
import { api } from "@/api";

/**
 * AchievementsCard — vitrine de medalhas do técnico.
 * Mostra todas as do catálogo. As conquistadas brilham; bloqueadas ficam
 * cinza com tooltip da descrição.
 */
export default function AchievementsCard({ collaboratorId, compact = false }) {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(!compact);

  useEffect(() => {
    if (!collaboratorId) return undefined;
    let alive = true;
    api._client.get(`/lousa/public/achievements/${collaboratorId}`)
      .then((r) => { if (alive) setData(r.data); })
      .catch(() => {});
    return () => { alive = false; };
  }, [collaboratorId]);

  if (!data) return null;
  const earned = data.earned_count;
  const total = data.total_count;
  const pct = Math.round((earned / total) * 100);

  return (
    <div data-testid="achievements-card" style={{
      marginTop: 12, padding: "12px 14px", borderRadius: 14,
      background: "linear-gradient(135deg,#1e1b4b 0%,#312e81 100%)",
      color: "white",
      boxShadow: "0 6px 16px -8px rgba(15,23,42,.35)",
    }}>
      <div onClick={() => setOpen((o) => !o)}
            style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", cursor: "pointer" }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.5,
                          textTransform: "uppercase",
                          color: "rgba(255,255,255,0.85)" }}>
            🏅 Medalhas
          </div>
          <div style={{ fontSize: 14, fontWeight: 700, marginTop: 2 }}>
            {earned} / {total}
            <span style={{ marginLeft: 8, fontSize: 11, fontWeight: 600,
                              color: "rgba(255,255,255,0.7)" }}>
              ({pct}%)
            </span>
          </div>
        </div>
        <div data-testid="achievements-toggle" style={{
          background: "rgba(255,255,255,0.15)", padding: "6px 10px",
          borderRadius: 999, fontSize: 11, fontWeight: 700,
        }}>{open ? "Recolher" : "Ver todas"}</div>
      </div>

      {/* barra de progresso */}
      <div style={{ marginTop: 10, height: 6, borderRadius: 999,
                      background: "rgba(255,255,255,0.12)",
                      overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${pct}%`,
                        background: "linear-gradient(90deg,#facc15,#f59e0b)",
                        transition: "width 350ms ease" }} />
      </div>

      {open && (
        <div data-testid="achievements-grid" style={{
          marginTop: 14, display: "grid",
          gridTemplateColumns: "repeat(auto-fill,minmax(82px,1fr))",
          gap: 10,
        }}>
          {data.medals.map((m) => (
            <Medal key={m.id} medal={m} />
          ))}
        </div>
      )}
    </div>
  );
}

function Medal({ medal }) {
  const earned = medal.earned;
  return (
    <div data-testid={`medal-${medal.id}${earned ? "-earned" : ""}`}
          title={medal.desc} style={{
      padding: "10px 6px", borderRadius: 12,
      background: earned
        ? "linear-gradient(135deg,#facc15 0%,#f59e0b 100%)"
        : "rgba(255,255,255,0.05)",
      border: earned
        ? "1px solid #fbbf24"
        : "1px dashed rgba(255,255,255,0.12)",
      textAlign: "center",
      opacity: earned ? 1 : 0.5,
      filter: earned ? "drop-shadow(0 0 6px rgba(251,191,36,0.45))" : "none",
    }}>
      <div style={{ fontSize: 26, lineHeight: 1 }}>{medal.icon}</div>
      <div style={{ fontSize: 9, fontWeight: 800, marginTop: 6,
                      color: earned ? "#1c1917" : "#cbd5e1",
                      textTransform: "uppercase", letterSpacing: 0.5,
                      lineHeight: 1.2 }}>{medal.label}</div>
    </div>
  );
}
