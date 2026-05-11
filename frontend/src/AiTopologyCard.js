import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import {
  Radio, Bot, Award, GraduationCap, Sparkles, Users, Loader2, Activity,
} from "lucide-react";

const ICONS = { Radio, Bot, Award, GraduationCap, Sparkles, Users };

/* Posições fixas no grid 1000x500 — fluxo da esquerda pra direita.
   smartolt (alto-esq) → atendimento (centro) ↔ human (baixo)
   atendimento → evaluator → coach + learning → atendimento (loop)
*/
const LAYOUT = {
  smartolt:    { x: 120, y: 90 },
  atendimento: { x: 500, y: 250 },
  evaluator:   { x: 880, y: 90 },
  coach:       { x: 880, y: 260 },
  learning:    { x: 880, y: 410 },
  human:       { x: 120, y: 410 },
};

export default function AiTopologyCard() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  const reload = useCallback(async () => {
    setRefreshing(true);
    try {
      const r = await api.aiTopologyFlow();
      setData(r); setErr(null);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setRefreshing(false); }
  }, []);

  useEffect(() => {
    reload();
    const id = setInterval(reload, 30000);
    return () => clearInterval(id);
  }, [reload]);

  const maxEdgeValue = data
    ? Math.max(1, ...data.edges.map((e) => e.value || 0))
    : 1;

  return (
    <div data-testid="ai-topology-card" style={{
      padding: 20, borderRadius: 12,
      border: "1px solid var(--border-default)",
      background: "var(--bg-surface)",
    }}>
      <style>{`
        @keyframes flow-dot {
          from { offset-distance: 0%; opacity: 0; }
          10% { opacity: 1; }
          90% { opacity: 1; }
          to { offset-distance: 100%; opacity: 0; }
        }
        .flow-dot { animation: flow-dot var(--dur, 4s) linear infinite; }
      `}</style>

      <div style={{
        display: "flex", alignItems: "flex-start",
        justifyContent: "space-between", gap: 12, marginBottom: 16, flexWrap: "wrap",
      }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)",
                          textTransform: "uppercase", letterSpacing: 0.6 }}>
            Topologia · Agent-to-Agent
          </div>
          <h3 style={{ fontSize: 16, fontWeight: 700, margin: "4px 0 0",
                          color: "var(--text-primary)", letterSpacing: "-0.012em" }}>
            Fluxo de dados entre as IAs (últimas 24h)
          </h3>
          <p style={{ fontSize: 12, color: "var(--text-secondary)",
                        margin: "4px 0 0", maxWidth: 580, lineHeight: 1.5 }}>
            As IAs trocam contexto em tempo real. Espessura das linhas e
            velocidade das partículas são proporcionais ao volume real de
            dados trafegado.
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8,
                         fontSize: 11, color: "var(--text-muted)" }}>
          {refreshing
            ? <Loader2 size={12} style={{ animation: "spin 1s linear infinite" }} />
            : <Activity size={12} style={{ color: "#16a34a" }} />}
          <span>auto-refresh 30s</span>
        </div>
      </div>

      {err && (
        <div style={{ padding: 10, borderRadius: 6, fontSize: 12,
                         background: "rgba(220,38,38,.08)", color: "#dc2626",
                         marginBottom: 12 }}>
          {err}
        </div>
      )}

      <div style={{
        position: "relative", width: "100%",
        background: "var(--bg-surface-2)", borderRadius: 10,
        border: "1px solid var(--border-default)",
        overflow: "hidden",
      }}>
        <svg viewBox="0 0 1000 500"
              style={{ width: "100%", height: "auto", display: "block" }}
              data-testid="ai-topology-svg">
          {data?.edges.map((e, i) => {
            const a = LAYOUT[e.from], b = LAYOUT[e.to];
            if (!a || !b) return null;
            const v = e.value || 0;
            const ratio = v / maxEdgeValue;
            const stroke = Math.max(1.5, 1.5 + ratio * 5);
            const opacity = v === 0 ? 0.18 : 0.45 + ratio * 0.5;
            // Curva quadrática suave
            const mx = (a.x + b.x) / 2;
            const my = (a.y + b.y) / 2;
            // Desloca o controle pra criar curvas que não se sobreponham
            const offsetY = ((i % 2) === 0 ? -1 : 1) * 30;
            const cx = mx + (b.x === a.x ? 0 : 0);
            const cy = my + offsetY;
            const pathD = `M ${a.x},${a.y} Q ${cx},${cy} ${b.x},${b.y}`;
            const dotCount = v === 0 ? 0 : Math.min(6, Math.ceil(ratio * 6));
            const dur = Math.max(2, 6 - ratio * 4);  // mais volume = mais rápido
            return (
              <g key={i} data-testid={`flow-edge-${e.from}-${e.to}`}>
                <path d={pathD} fill="none"
                      stroke="var(--text-muted)"
                      strokeWidth={stroke}
                      strokeLinecap="round"
                      opacity={opacity} />
                {Array.from({ length: dotCount }).map((_, di) => (
                  <circle key={di} r="4" fill="#16a34a"
                          className="flow-dot"
                          style={{
                            offsetPath: `path('${pathD}')`,
                            animationDelay: `${(di * dur / dotCount).toFixed(2)}s`,
                            "--dur": `${dur}s`,
                          }} />
                ))}
              </g>
            );
          })}
          {data?.nodes.map((n) => {
            const pos = LAYOUT[n.id];
            if (!pos) return null;
            const Ico = ICONS[n.icon] || Bot;
            return (
              <g key={n.id} transform={`translate(${pos.x - 80} ${pos.y - 36})`}
                  data-testid={`flow-node-${n.id}`}>
                <rect width="160" height="72" rx="10"
                      fill="var(--bg-surface)"
                      stroke={n.color}
                      strokeWidth="1.5" />
                <foreignObject x="0" y="0" width="160" height="72">
                  <div xmlns="http://www.w3.org/1999/xhtml"
                        style={{
                          padding: "8px 10px",
                          fontFamily: "inherit",
                          height: "100%",
                          display: "flex", flexDirection: "column",
                          justifyContent: "center",
                        }}>
                    <div style={{ display: "flex", alignItems: "center",
                                     gap: 6, marginBottom: 4 }}>
                      <div style={{
                        width: 22, height: 22, borderRadius: 5,
                        background: n.color, color: "#fff",
                        display: "grid", placeItems: "center",
                      }}>
                        <Ico size={13} strokeWidth={1.8} />
                      </div>
                      <div style={{ fontSize: 12, fontWeight: 700,
                                       color: "var(--text-primary)",
                                       lineHeight: 1.1, letterSpacing: "-0.01em" }}>
                        {n.label}
                      </div>
                    </div>
                    <div style={{ fontSize: 9, color: "var(--text-muted)",
                                     textTransform: "uppercase",
                                     letterSpacing: 0.4, fontWeight: 600 }}>
                      {n.subtitle}
                    </div>
                    <div style={{ fontSize: 11, fontWeight: 700,
                                     color: n.color, marginTop: 3,
                                     fontFamily: "ui-monospace, monospace" }}>
                      {n.metric}
                    </div>
                  </div>
                </foreignObject>
              </g>
            );
          })}
        </svg>
      </div>

      {/* Legenda */}
      {data?.edges && (
        <div style={{
          marginTop: 14, display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: 8,
        }}>
          {data.edges.map((e, i) => (
            <div key={i} style={{
              padding: "8px 10px", borderRadius: 6,
              border: "1px solid var(--border-default)",
              background: "var(--bg-surface)",
              fontSize: 11,
            }} data-testid={`flow-legend-${e.from}-${e.to}`}>
              <div style={{ display: "flex", justifyContent: "space-between",
                               alignItems: "baseline", gap: 6 }}>
                <span style={{ color: "var(--text-secondary)" }}>{e.label}</span>
                <strong style={{ color: e.value > 0 ? "#16a34a" : "var(--text-muted)",
                                    fontFamily: "ui-monospace, monospace" }}>
                  {e.value}
                </strong>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
