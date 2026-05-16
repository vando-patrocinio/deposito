import React, { useEffect, useState } from "react";
import { api } from "@/api";

/**
 * LeaderboardMural — visão tela cheia para TV no escritório.
 * Mostra top técnicos do dia com foto e KPIs. Auto-refresh 30s.
 * Acessível via /mural ou /leaderboard sem auth.
 */
export default function LeaderboardMural() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    const load = () => {
      api._client.get("/lousa/public/leaderboard?company_id=co-demo&limit=10")
        .then((r) => { if (alive) { setData(r.data); setErr(""); } })
        .catch((e) => {
          if (alive) setErr(e?.response?.data?.detail || e.message);
        });
    };
    load();
    const i = setInterval(load, 30000);
    const c = setInterval(() => setTick((t) => t + 1), 1000);
    return () => { alive = false; clearInterval(i); clearInterval(c); };
  }, []);

  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  const ss = String(now.getSeconds()).padStart(2, "0");

  if (!data && !err) {
    return (
      <div style={baseBg}>
        <div style={{ color: "#94a3b8", fontSize: 32, textAlign: "center",
                        paddingTop: "30vh" }}>
          Carregando ranking…
        </div>
      </div>
    );
  }

  const list = data?.leaderboard || [];
  const podium = list.slice(0, 3);
  const rest = list.slice(3, 10);

  return (
    <div data-testid="leaderboard-mural" style={baseBg}>
      {/* HEADER */}
      <header style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "28px 56px 14px",
      }}>
        <div>
          <div style={{
            fontSize: 12, color: "#67e8f9", fontWeight: 800,
            textTransform: "uppercase", letterSpacing: 3,
          }}>Mural ao vivo · técnicos</div>
          <h1 style={{
            fontSize: 56, fontWeight: 900, color: "white", margin: "4px 0 0",
            fontFamily: "Space Grotesk, Manrope, sans-serif",
            letterSpacing: -1.5,
          }}>RANKING DO DIA</h1>
        </div>
        <div style={{ textAlign: "right" }}>
          <div data-testid="mural-clock" style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 56, color: "#06b6d4", fontWeight: 800,
            lineHeight: 1,
          }}>{hh}:{mm}<span style={{ color: "#0e7490",
                                      fontSize: 36 }}>:{ss}</span></div>
          <div style={{ fontSize: 13, color: "#64748b", marginTop: 6,
                          fontWeight: 600, textTransform: "uppercase",
                          letterSpacing: 2 }}>
            {now.toLocaleDateString("pt-BR", { weekday: "long",
                                                  day: "2-digit",
                                                  month: "long" })}
          </div>
        </div>
      </header>

      {err && (
        <div style={{ margin: "20px 56px", padding: 16,
                        background: "#7f1d1d", color: "white",
                        borderRadius: 12, fontWeight: 600 }}>
          Falha ao carregar ranking: {err}
        </div>
      )}

      {list.length === 0 && !err && (
        <div style={{ textAlign: "center", padding: "20vh 32px",
                        color: "#94a3b8", fontSize: 28 }}>
          Nenhuma nota finalizada ainda hoje. Bora começar!
        </div>
      )}

      {/* PODIUM */}
      {podium.length > 0 && (
        <section data-testid="mural-podium" style={{
          display: "flex", gap: 28, justifyContent: "center",
          alignItems: "end", padding: "20px 56px 28px",
        }}>
          {podium[1] && <PodiumCard place={2} tech={podium[1]} />}
          {podium[0] && <PodiumCard place={1} tech={podium[0]} />}
          {podium[2] && <PodiumCard place={3} tech={podium[2]} />}
        </section>
      )}

      {/* LISTA 4..10 */}
      {rest.length > 0 && (
        <section style={{ padding: "0 56px 40px" }}>
          <div style={{ color: "#475569", fontSize: 11, fontWeight: 800,
                          letterSpacing: 2, textTransform: "uppercase",
                          marginBottom: 12 }}>
            Demais
          </div>
          <div data-testid="mural-rest" style={{ display: "grid",
                            gridTemplateColumns: "repeat(auto-fill,minmax(360px,1fr))",
                            gap: 14 }}>
            {rest.map((t) => <ListRow key={t.collaborator_id} tech={t} />)}
          </div>
        </section>
      )}

      {/* FOOTER */}
      <footer style={{
        position: "fixed", bottom: 0, left: 0, right: 0,
        padding: "12px 56px",
        background: "rgba(2,6,23,0.85)",
        backdropFilter: "blur(8px)",
        display: "flex", justifyContent: "space-between",
        fontSize: 12, color: "#64748b", letterSpacing: 1,
        borderTop: "1px solid rgba(255,255,255,0.06)",
      }}>
        <span>SmartProv · atualizado a cada 30s</span>
        <span>{data?.total_techs || 0} técnico(s) no ranking</span>
      </footer>
    </div>
  );
}

const baseBg = {
  minHeight: "100vh",
  background: "linear-gradient(135deg,#020617 0%,#0f172a 50%,#1e293b 100%)",
  color: "white",
  fontFamily: "Manrope, system-ui, sans-serif",
};

function Avatar({ src, name, size = 90, ring }) {
  const initials = (name || "?")
    .split(" ").filter(Boolean).slice(0, 2).map((s) => s[0]).join("");
  if (src) {
    return (
      <img alt={name} src={src} style={{
        width: size, height: size, borderRadius: "50%",
        objectFit: "cover", border: `${size > 80 ? 4 : 2}px solid ${ring || "rgba(255,255,255,0.18)"}`,
        boxShadow: "0 8px 24px -8px rgba(0,0,0,.6)",
      }} />
    );
  }
  return (
    <div style={{
      width: size, height: size, borderRadius: "50%",
      background: "linear-gradient(135deg,#0891b2,#0e7490)",
      display: "grid", placeItems: "center",
      fontSize: size * 0.32, fontWeight: 800,
      border: `${size > 80 ? 4 : 2}px solid ${ring || "rgba(255,255,255,0.18)"}`,
      boxShadow: "0 8px 24px -8px rgba(0,0,0,.6)",
    }}>{initials.toUpperCase()}</div>
  );
}

function PodiumCard({ place, tech }) {
  const config = {
    1: { color: "#f59e0b", h: 280, scale: 1.08, label: "1º · Líder",
          glow: "0 0 40px rgba(245,158,11,0.55)" },
    2: { color: "#94a3b8", h: 230, scale: 1, label: "2º",
          glow: "0 0 22px rgba(148,163,184,0.4)" },
    3: { color: "#ea580c", h: 200, scale: 0.94, label: "3º",
          glow: "0 0 22px rgba(234,88,12,0.4)" },
  }[place];

  return (
    <div data-testid={`mural-podium-${place}`} style={{
      width: 260, textAlign: "center", transform: `scale(${config.scale})`,
    }}>
      <div style={{ fontSize: 11, color: config.color, fontWeight: 800,
                      letterSpacing: 3, textTransform: "uppercase",
                      marginBottom: 14 }}>{config.label}</div>
      <div style={{ display: "flex", justifyContent: "center",
                      marginBottom: 14, filter: `drop-shadow(${config.glow})` }}>
        <Avatar src={tech.photo_url} name={tech.name}
                  size={place === 1 ? 130 : 110} ring={config.color} />
      </div>
      <div style={{ fontSize: 22, fontWeight: 900, color: "white",
                      letterSpacing: -0.3, lineHeight: 1.1,
                      marginBottom: 4,
                      textShadow: "0 2px 12px rgba(0,0,0,.4)" }}>
        {tech.name}
      </div>
      {tech.badge && (
        <div style={{ display: "inline-block", padding: "4px 12px",
                        borderRadius: 999, background: config.color,
                        color: "white", fontSize: 11, fontWeight: 800,
                        marginBottom: 12 }}>
          {tech.badge}
        </div>
      )}
      <div style={{
        background: `linear-gradient(180deg, ${config.color}33, ${config.color}11)`,
        border: `1px solid ${config.color}55`,
        borderRadius: 16, padding: "16px 18px",
        minHeight: config.h * 0.4,
      }}>
        <div style={{ display: "flex", justifyContent: "space-around" }}>
          <Stat label="Fechadas" value={tech.closed_today} big />
          <Stat label="% Sucesso" value={`${tech.success_rate}%`} big />
        </div>
        <div style={{ marginTop: 10, fontSize: 12, color: "#cbd5e1" }}>
          {tech.avg_minutes
            ? `${tech.avg_minutes} min por nota`
            : "—"}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, big }) {
  return (
    <div>
      <div style={{ fontSize: big ? 36 : 22, fontWeight: 900,
                      color: "white", lineHeight: 1,
                      fontFamily: "Space Grotesk, sans-serif" }}>{value}</div>
      <div style={{ fontSize: 9, color: "rgba(255,255,255,0.7)",
                      textTransform: "uppercase", letterSpacing: 1,
                      fontWeight: 700, marginTop: 4 }}>{label}</div>
    </div>
  );
}

function ListRow({ tech }) {
  return (
    <div data-testid={`mural-row-${tech.collaborator_id}`} style={{
      display: "flex", alignItems: "center", gap: 14,
      padding: "12px 16px", borderRadius: 14,
      background: "rgba(15,23,42,0.6)",
      border: "1px solid rgba(255,255,255,0.06)",
    }}>
      <div style={{
        width: 34, height: 34, borderRadius: "50%",
        background: "rgba(6,182,212,0.15)",
        color: "#67e8f9", fontWeight: 900, fontSize: 14,
        display: "grid", placeItems: "center", flexShrink: 0,
      }}>{tech.rank}º</div>
      <Avatar src={tech.photo_url} name={tech.name} size={44} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 15, fontWeight: 800, color: "white",
                        whiteSpace: "nowrap", overflow: "hidden",
                        textOverflow: "ellipsis" }}>{tech.name}</div>
        <div style={{ fontSize: 11, color: "#94a3b8",
                        textTransform: "lowercase" }}>{tech.role}</div>
      </div>
      <div style={{ textAlign: "right", flexShrink: 0 }}>
        <div style={{ fontSize: 22, fontWeight: 900, color: "white",
                        lineHeight: 1,
                        fontFamily: "Space Grotesk, sans-serif" }}>
          {tech.closed_today}
        </div>
        <div style={{ fontSize: 10, color: "#94a3b8",
                        textTransform: "uppercase", letterSpacing: 1 }}>
          {tech.success_rate}% sucesso
        </div>
      </div>
    </div>
  );
}
