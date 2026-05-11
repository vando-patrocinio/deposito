import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import {
  Radio, Bot, Award, GraduationCap, Sparkles, Users, User, Lightbulb,
  Loader2, Activity, Shield, ClipboardList,
} from "lucide-react";

const ICONS = { Radio, Bot, Award, GraduationCap, Sparkles, Users, User, Lightbulb,
  Shield, ClipboardList };

/* Layout dinâmico:
   - IAs ficam no topo/centro do canvas em posições fixas
   - Atendentes humanos (N variável) ficam dispostos na faixa inferior,
     distribuídos uniformemente da esquerda pra direita.
*/
const W = 1100, H = 700;
const AI_LAYOUT = {
  smartolt:    { x: 120, y: 90 },
  atendimento: { x: 380, y: 250 },
  copilot:     { x: 720, y: 250 },
  evaluator:   { x: 960, y: 90 },
  coach:       { x: 960, y: 410 },
  learning:    { x: 120, y: 250 },
  sentinela:   { x: 380, y: 410 },   // Sentinela — abaixo de Isabella
  lousa:       { x: 720, y: 410 },   // Lousa — ao lado da Sentinela
};

function humanLayout(humanNodes) {
  // Linha inferior — distribuída uniformemente
  const n = humanNodes.length;
  const yLine = 630;
  if (n === 0) return {};
  const positions = {};
  const margin = 110;
  const span = W - margin * 2;
  humanNodes.forEach((node, i) => {
    const x = n === 1 ? W / 2 : margin + (span * i) / (n - 1);
    positions[node.id] = { x, y: yLine };
  });
  return positions;
}

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

  const layout = useMemo(() => {
    if (!data) return {};
    const humans = data.nodes.filter((n) => n.kind === "human");
    return { ...AI_LAYOUT, ...humanLayout(humans) };
  }, [data]);

  const maxEdgeValue = data
    ? Math.max(1, ...data.edges.map((e) => e.value || 0))
    : 1;

  const totals = data?.totals || {};

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
        justifyContent: "space-between", gap: 12, marginBottom: 12, flexWrap: "wrap",
      }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)",
                          textTransform: "uppercase", letterSpacing: 0.6 }}>
            Topologia · Agent-to-Agent · Agent-to-Human
          </div>
          <h3 style={{ fontSize: 16, fontWeight: 700, margin: "4px 0 0",
                          color: "var(--text-primary)", letterSpacing: "-0.012em" }}>
            Fluxo de dados entre IAs e atendentes humanos (últimas 24h)
          </h3>
          <p style={{ fontSize: 12, color: "var(--text-secondary)",
                        margin: "4px 0 0", maxWidth: 720, lineHeight: 1.5 }}>
            Co-Pilot IA monitora cada conversa atribuída a humano e envia dicas
            internas (cliente nunca vê). Espessura das linhas e velocidade
            das partículas refletem o volume real trafegado.
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

      {/* Banner Motor IA — modelos em uso */}
      {data?.motor && (
        <div data-testid="motor-banner" style={{
          marginBottom: 14, padding: "8px 12px", borderRadius: 8,
          border: "1px solid var(--border-default)",
          background: "linear-gradient(90deg, rgba(13,148,136,.06), transparent)",
          display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
          fontSize: 11,
        }}>
          <span style={{ fontWeight: 800, color: "var(--text-secondary)",
                            textTransform: "uppercase", letterSpacing: 0.4,
                            display: "inline-flex", alignItems: "center", gap: 4 }}>
            <span style={{
              width: 7, height: 7, borderRadius: "50%",
              background: data.motor.enabled ? "#16a34a" : "#dc2626",
            }} />
            Motor IA
          </span>
          <ModelTag label="Atendimento" model={data.motor.atendimento_model} />
          <ModelTag label="Geral" model={data.motor.default_text_model} />
          <ModelTag label="Voz (TTS)" model={data.motor.tts_voice} kind="audio" />
        </div>
      )}

      {/* KPI strip */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
        gap: 8, marginBottom: 14,
      }}>
        <KpiPill label="Recebidas (24h)"  value={totals.wa_inbound_24h ?? 0} color="#0ea5e9" />
        <KpiPill label="IA respondeu"      value={totals.wa_ai_24h ?? 0}     color="#16a34a" />
        <KpiPill label="Humano respondeu"  value={totals.wa_human_24h ?? 0}  color="#475569" />
        <KpiPill label="Dicas Co-Pilot"    value={totals.copilot_hints_24h ?? 0} color="#d97706" />
        <KpiPill label="Avaliações IA"     value={totals.evaluations_24h ?? 0}   color="#0ea5e9" />
        <KpiPill label="Alertas Sentinela" value={totals.sentinela_active_alerts ?? 0} color="#ef4444" />
        <KpiPill label="Atendentes ativos" value={totals.human_attendants ?? 0}  color="#475569" />
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
        <svg viewBox={`0 0 ${W} ${H}`}
              style={{ width: "100%", height: "auto", display: "block" }}
              data-testid="ai-topology-svg">
          {/* Faixa de fundo separando IAs e Humanos */}
          <rect x="0" y={H - 130} width={W} height="130"
                fill="rgba(71,85,105,.04)" />
          <text x="14" y={H - 110} fontSize="10" fontWeight="700"
                fill="var(--text-muted)"
                style={{ textTransform: "uppercase", letterSpacing: "1px" }}>
            Atendentes humanos
          </text>

          {data?.edges.map((e, i) => {
            const a = layout[e.from], b = layout[e.to];
            if (!a || !b) return null;
            const v = e.value || 0;
            const ratio = v / maxEdgeValue;
            const stroke = Math.max(1.3, 1.3 + ratio * 4.5);
            const opacity = v === 0 ? 0.12 : 0.40 + ratio * 0.5;
            // Cor especial pro Co-Pilot
            const isCopilot = e.from === "copilot" || e.to === "copilot";
            const strokeColor = isCopilot ? "#d97706" : "var(--text-muted)";
            const dotColor = isCopilot ? "#d97706" : "#16a34a";
            const mx = (a.x + b.x) / 2;
            const my = (a.y + b.y) / 2;
            const offsetY = ((i % 2) === 0 ? -1 : 1) * 32;
            const pathD = `M ${a.x},${a.y} Q ${mx},${my + offsetY} ${b.x},${b.y}`;
            const dotCount = v === 0 ? 0 : Math.min(5, Math.ceil(ratio * 5));
            const dur = Math.max(2.2, 6 - ratio * 4);
            return (
              <g key={i} data-testid={`flow-edge-${e.from}-${e.to}`}>
                <path d={pathD} fill="none"
                      stroke={strokeColor}
                      strokeWidth={stroke}
                      strokeLinecap="round"
                      opacity={opacity} />
                {Array.from({ length: dotCount }).map((_, di) => (
                  <circle key={di} r="3.5" fill={dotColor}
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
            const pos = layout[n.id];
            if (!pos) return null;
            const Ico = ICONS[n.icon] || Bot;
            const isHuman = n.kind === "human";
            const nodeW = isHuman ? 130 : 180;
            const nodeH = isHuman ? 62 : 92;
            return (
              <g key={n.id}
                  transform={`translate(${pos.x - nodeW / 2} ${pos.y - nodeH / 2})`}
                  data-testid={`flow-node-${n.id}`}>
                <rect width={nodeW} height={nodeH} rx="10"
                      fill="var(--bg-surface)"
                      stroke={n.color}
                      strokeWidth={isHuman ? "1.2" : "1.5"}
                      strokeDasharray={isHuman ? "0" : "0"} />
                <foreignObject x="0" y="0" width={nodeW} height={nodeH}>
                  <div xmlns="http://www.w3.org/1999/xhtml"
                        style={{
                          padding: isHuman ? "6px 8px" : "8px 10px",
                          fontFamily: "inherit",
                          height: "100%",
                          display: "flex", flexDirection: "column",
                          justifyContent: "center",
                          gap: 2,
                        }}>
                    <div style={{ display: "flex", alignItems: "center",
                                     gap: 6 }}>
                      <div style={{
                        width: isHuman ? 18 : 22,
                        height: isHuman ? 18 : 22, borderRadius: 5,
                        background: n.color, color: "#fff",
                        display: "grid", placeItems: "center", flexShrink: 0,
                      }}>
                        <Ico size={isHuman ? 11 : 13} strokeWidth={1.8} />
                      </div>
                      <div style={{ fontSize: isHuman ? 11 : 12, fontWeight: 700,
                                       color: "var(--text-primary)",
                                       lineHeight: 1.1, letterSpacing: "-0.01em",
                                       overflow: "hidden",
                                       textOverflow: "ellipsis",
                                       whiteSpace: "nowrap" }}>
                        {n.label}
                      </div>
                    </div>
                    <div style={{ fontSize: 9, color: "var(--text-muted)",
                                     textTransform: "uppercase",
                                     letterSpacing: 0.4, fontWeight: 600,
                                     overflow: "hidden",
                                     textOverflow: "ellipsis",
                                     whiteSpace: "nowrap" }}>
                      {n.subtitle}
                    </div>
                    {!isHuman && n.model && (
                      <ModelChip model={n.model} kind={n.model_kind} />
                    )}
                    <div style={{ fontSize: 10.5, fontWeight: 700,
                                     color: n.color,
                                     fontFamily: "ui-monospace, monospace" }}>
                      {n.metric}
                    </div>
                    {isHuman && n.hints_received > 0 && (
                      <div style={{ fontSize: 9, color: "#d97706",
                                       fontWeight: 700,
                                       display: "flex", alignItems: "center", gap: 3 }}>
                        <Lightbulb size={9} strokeWidth={2.2} />
                        {n.hints_received} dica{n.hints_received === 1 ? "" : "s"}
                      </div>
                    )}
                  </div>
                </foreignObject>
              </g>
            );
          })}
        </svg>
      </div>

      {/* Legenda — agrupa arestas por tipo */}
      {data?.edges && (
        <div style={{
          marginTop: 14, display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: 8,
        }}>
          {data.edges
            .filter((e) => e.value > 0)
            .map((e, i) => (
              <div key={i} style={{
                padding: "8px 10px", borderRadius: 6,
                border: "1px solid var(--border-default)",
                background: "var(--bg-surface)",
                fontSize: 11,
              }} data-testid={`flow-legend-${e.from}-${e.to}`}>
                <div style={{ display: "flex", justifyContent: "space-between",
                                 alignItems: "baseline", gap: 6 }}>
                  <span style={{ color: "var(--text-secondary)" }}>{e.label}</span>
                  <strong style={{ color: "#16a34a",
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

function ModelTag({ label, model, kind }) {
  if (!model) return null;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{ color: "var(--text-muted)", fontSize: 10,
                        textTransform: "uppercase", letterSpacing: 0.4,
                        fontWeight: 700 }}>
        {label}
      </span>
      <span title={model} style={{
        padding: "2px 8px", borderRadius: 4,
        background: kind === "audio" ? "#fce7f3" : "var(--bg-surface)",
        color: kind === "audio" ? "#9d174d" : "var(--text-primary)",
        fontFamily: "ui-monospace, monospace", fontSize: 10.5, fontWeight: 700,
        border: "1px solid var(--border-default)",
      }}>
        {simplify(model)}
      </span>
    </span>
  );
}

function ModelChip({ model, kind }) {
  // Cores por tipo de modelo
  let bg, color, label;
  const m = (model || "").toLowerCase();
  if (kind === "rule") {
    bg = "#e2e8f0"; color = "#475569"; label = model;
  } else if (kind === "retrieval") {
    bg = "#fef3c7"; color = "#92400e"; label = model;
  } else if (m.includes("deepseek")) {
    bg = "#e0f2fe"; color = "#075985"; label = simplify(model);
  } else if (m.includes("claude") || m.includes("anthropic")) {
    bg = "#fae8ff"; color = "#86198f"; label = simplify(model);
  } else if (m.includes("gpt") || m.includes("openai")) {
    bg = "#dcfce7"; color = "#166534"; label = simplify(model);
  } else if (m.includes("gemini") || m.includes("google")) {
    bg = "#dbeafe"; color = "#1e40af"; label = simplify(model);
  } else {
    bg = "#f1f5f9"; color = "#334155"; label = simplify(model);
  }
  return (
    <div title={model} style={{
      display: "inline-flex", alignItems: "center", gap: 3,
      padding: "1px 6px", borderRadius: 4,
      background: bg, color,
      fontSize: 9, fontWeight: 700,
      fontFamily: "ui-monospace, monospace",
      letterSpacing: 0,
      maxWidth: "100%",
      overflow: "hidden",
      textOverflow: "ellipsis",
      whiteSpace: "nowrap",
      alignSelf: "flex-start",
    }}>
      {kind === "llm" && <span style={{ fontSize: 7 }}>●</span>}
      {label}
    </div>
  );
}

function simplify(modelId) {
  // "anthropic/claude-3.5-sonnet" → "claude-3.5-sonnet"
  // "deepseek/deepseek-v4-flash" → "deepseek-v4-flash"
  if (!modelId) return "—";
  const parts = String(modelId).split("/");
  return parts[parts.length - 1];
}

function KpiPill({ label, value, color }) {
  return (
    <div style={{
      padding: "8px 10px", borderRadius: 8,
      border: "1px solid var(--border-default)",
      background: "var(--bg-surface)",
      display: "flex", alignItems: "center", gap: 8,
    }}>
      <div style={{ width: 5, height: 24, borderRadius: 3, background: color }} />
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 9, fontWeight: 700, color: "var(--text-muted)",
                         textTransform: "uppercase", letterSpacing: 0.4 }}>
          {label}
        </div>
        <div style={{ fontSize: 17, fontWeight: 800, color: "var(--text-primary)",
                         fontFamily: "ui-monospace, monospace",
                         letterSpacing: "-0.02em", lineHeight: 1 }}>
          {value}
        </div>
      </div>
    </div>
  );
}
