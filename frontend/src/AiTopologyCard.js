import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/api";
import {
  Radio, Bot, Award, GraduationCap, Sparkles, Users, User, Lightbulb,
  Loader2, Activity, Shield, ClipboardList, Wand2, Cpu, Headphones,
  X, Move, RotateCcw, ArrowRight, ArrowLeft, Tag, Power, Zap,
} from "lucide-react";
import MotorIaAgentsModal from "@/MotorIaAgentsModal";

const ICONS = { Radio, Bot, Award, GraduationCap, Sparkles, Users, User, Lightbulb,
  Shield, ClipboardList, Wand: Wand2, Cpu, Headphones };

const POSITIONS_KEY = "smartprov.ai_topology.positions.v1";

/* Layout 2026 — Hub-and-spoke:
   - Motor IA no CENTRO (núcleo orquestrador)
   - 6 IAs orbitam em círculo ao redor
   - Sentinela + Lousa AI + Lousa Kanban formam camada operacional
   - Atendentes humanos na faixa inferior
*/
const W = 1200, H = 820;
const CX = W / 2;          // 600
const CY = 340;            // centro do hub

// Distância do raio (orbita)
const R1 = 220;            // IAs internas (Isabella, Co-Pilot, etc)
const R2 = 360;            // IAs externas (Sentinela, Lousa AI, Lousa)

// Posições calculadas em ângulo (em graus)
function polar(cx, cy, r, deg) {
  const rad = (deg - 90) * Math.PI / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

const AI_LAYOUT = {
  // núcleo
  motor:       { x: CX, y: CY },

  // anel 1 — agentes de conversa (em volta do motor)
  atendimento: polar(CX, CY, R1, 270),   // esquerda do motor
  copilot:     polar(CX, CY, R1, 90),    // direita do motor
  smartolt:    polar(CX, CY, R1, 330),   // alto-esquerda
  evaluator:   polar(CX, CY, R1, 30),    // alto-direita
  learning:    polar(CX, CY, R1, 210),   // baixo-esquerda
  coach:       polar(CX, CY, R1, 150),   // baixo-direita

  // anel 2 — agentes da Lousa (camada operacional inferior)
  sentinela:   { x: 140, y: 600 },
  lousa_ai:    { x: 460, y: 600 },
  lousa:       { x: 780, y: 600 },
  secretaria:  { x: 1100, y: 600 },
};

function humanLayout(humanNodes) {
  const n = humanNodes.length;
  const yLine = 760;
  if (n === 0) return {};
  const positions = {};
  const margin = 120;
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
  const [agentsOpen, setAgentsOpen] = useState(false);

  // Detail popup do nó clicado
  const [selectedNode, setSelectedNode] = useState(null);

  // Posições customizadas (drag) — persistidas em localStorage
  const [overrides, setOverrides] = useState(() => {
    try {
      const raw = localStorage.getItem(POSITIONS_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch { return {}; }
  });

  // Drag state em ref para não disparar re-render no movimento
  const svgRef = useRef(null);
  const dragRef = useRef(null);
  const [dragId, setDragId] = useState(null);

  const persistOverrides = useCallback((next) => {
    setOverrides(next);
    try { localStorage.setItem(POSITIONS_KEY, JSON.stringify(next)); } catch {}
  }, []);

  const resetPositions = useCallback(() => {
    if (!window.confirm("Restaurar posições padrão de todos os cards?")) return;
    persistOverrides({});
  }, [persistOverrides]);

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
    const base = { ...AI_LAYOUT, ...humanLayout(humans) };
    // aplica overrides do usuário
    for (const [id, pos] of Object.entries(overrides)) {
      if (pos && typeof pos.x === "number" && typeof pos.y === "number") {
        base[id] = pos;
      }
    }
    return base;
  }, [data, overrides]);

  // Drag handlers
  const justDraggedRef = useRef(false);
  function nodeMouseDown(e, nodeId) {
    if (!svgRef.current) return;
    e.stopPropagation();
    const svg = svgRef.current;
    const pt = svg.createSVGPoint();
    const startCTM = svg.getScreenCTM().inverse();
    pt.x = e.clientX; pt.y = e.clientY;
    const start = pt.matrixTransform(startCTM);
    const nodePos = layout[nodeId];
    if (!nodePos) return;
    dragRef.current = {
      nodeId,
      offsetX: start.x - nodePos.x,
      offsetY: start.y - nodePos.y,
      moved: false,
    };
    setDragId(nodeId);
  }

  useEffect(() => {
    function onMove(ev) {
      const d = dragRef.current;
      if (!d || !svgRef.current) return;
      const svg = svgRef.current;
      const pt = svg.createSVGPoint();
      pt.x = ev.clientX; pt.y = ev.clientY;
      const ctm = svg.getScreenCTM();
      if (!ctm) return;
      const loc = pt.matrixTransform(ctm.inverse());
      const x = Math.max(60, Math.min(W - 60, loc.x - d.offsetX));
      const y = Math.max(40, Math.min(H - 40, loc.y - d.offsetY));
      d.moved = true;
      setOverrides((prev) => ({ ...prev, [d.nodeId]: { x, y } }));
    }
    function onUp() {
      const d = dragRef.current;
      if (!d) return;
      if (d.moved) {
        justDraggedRef.current = true;
        setTimeout(() => { justDraggedRef.current = false; }, 50);
        setOverrides((curr) => {
          try { localStorage.setItem(POSITIONS_KEY, JSON.stringify(curr)); } catch {}
          return curr;
        });
      }
      dragRef.current = null;
      setDragId(null);
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  function handleNodeClick(e, node) {
    e.stopPropagation();
    setSelectedNode(node);
  }

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
        @keyframes core-pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(1.4); }
        }
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
          {Object.keys(overrides).length > 0 && (
            <button
              onClick={resetPositions}
              data-testid="ai-topology-reset-positions"
              title="Restaurar layout original"
              style={{
                padding: "3px 10px", borderRadius: 6, fontSize: 10.5, fontWeight: 700,
                border: "1px solid var(--border-default)",
                background: "var(--bg-surface)", color: "var(--text-secondary)",
                cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 4,
              }}>
              <RotateCcw size={11} /> Resetar posições
            </button>
          )}
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
        <KpiPill label="Triados Lousa AI"  value={totals.lousa_ai_triaged_24h ?? 0}  color="#2563eb" />
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
        <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`}
              style={{ width: "100%", height: "auto", display: "block",
                          userSelect: dragId ? "none" : "auto",
                          cursor: dragId ? "grabbing" : "default" }}
              data-testid="ai-topology-svg">
          <defs>
            <radialGradient id="motor-glow">
              <stop offset="0%" stopColor="#fbbf24" stopOpacity="1" />
              <stop offset="60%" stopColor="#fbbf24" stopOpacity="0.4" />
              <stop offset="100%" stopColor="#fbbf24" stopOpacity="0" />
            </radialGradient>
          </defs>
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
            const isMotor = e.kind === "motor" || e.from === "motor";
            const isCopilot = !isMotor && (e.from === "copilot" || e.to === "copilot");
            const stroke = isMotor
              ? Math.max(0.8, 0.8 + ratio * 2.0)
              : Math.max(1.3, 1.3 + ratio * 4.5);
            const opacity = v === 0
              ? (isMotor ? 0.18 : 0.12)
              : (isMotor ? 0.45 + ratio * 0.35 : 0.40 + ratio * 0.5);
            const strokeColor = isMotor
              ? "#0f172a"
              : (isCopilot ? "#d97706" : "var(--text-muted)");
            const dotColor = isMotor ? "#0f172a"
              : (isCopilot ? "#d97706" : "#16a34a");
            const dash = isMotor ? "4 4" : undefined;
            const mx = (a.x + b.x) / 2;
            const my = (a.y + b.y) / 2;
            const offsetY = ((i % 2) === 0 ? -1 : 1) * (isMotor ? 8 : 32);
            const pathD = `M ${a.x},${a.y} Q ${mx},${my + offsetY} ${b.x},${b.y}`;
            const dotCount = v === 0 ? 0 : Math.min(isMotor ? 2 : 5,
                                                       Math.ceil(ratio * (isMotor ? 2 : 5)));
            const dur = Math.max(2.2, 6 - ratio * 4);
            return (
              <g key={i} data-testid={`flow-edge-${e.from}-${e.to}`}>
                <path d={pathD} fill="none"
                      stroke={strokeColor}
                      strokeWidth={stroke}
                      strokeLinecap="round"
                      strokeDasharray={dash}
                      opacity={opacity} />
                {Array.from({ length: dotCount }).map((_, di) => (
                  <circle key={di} r={isMotor ? 2.5 : 3.5} fill={dotColor}
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
            const isCore = n.kind === "core";   // Motor IA
            const nodeW = isCore ? 200 : (isHuman ? 130 : 180);
            const nodeH = isCore ? 110 : (isHuman ? 62 : 92);
            return (
              <g key={n.id}
                  transform={`translate(${pos.x - nodeW / 2} ${pos.y - nodeH / 2})`}
                  data-testid={`flow-node-${n.id}`}
                  onMouseDown={(e) => nodeMouseDown(e, n.id)}
                  onClick={(e) => {
                    if (justDraggedRef.current) return; // suprime click após drag
                    if (isCore) {
                      // Motor IA mantém comportamento legado (abre modal de agentes)
                      setAgentsOpen(true);
                      return;
                    }
                    handleNodeClick(e, n);
                  }}
                  style={{
                    cursor: dragId === n.id ? "grabbing" : "grab",
                    opacity: dragId && dragId !== n.id ? 0.55 : 1,
                    transition: dragId === n.id ? "none" : "opacity 0.15s ease",
                  }}>
                {isCore && (
                  <>
                    <circle cx={nodeW/2} cy={nodeH/2} r={nodeW * 0.85}
                            fill="url(#motor-glow)" opacity="0.18" />
                    <rect x="-3" y="-3" width={nodeW + 6} height={nodeH + 6}
                          rx="14" fill="none" stroke={n.color} strokeWidth="1.2"
                          strokeDasharray="3 3" opacity="0.45" />
                  </>
                )}
                <rect width={nodeW} height={nodeH} rx={isCore ? 12 : 10}
                      fill={isCore ? "#0f172a" : "var(--bg-surface)"}
                      stroke={isCore ? "#fbbf24" : n.color}
                      strokeWidth={isCore ? "2" : (isHuman ? "1.2" : "1.5")} />
                <foreignObject x="0" y="0" width={nodeW} height={nodeH}>
                  <div xmlns="http://www.w3.org/1999/xhtml"
                        style={{
                          padding: isCore ? "12px 14px" :
                                   (isHuman ? "6px 8px" : "8px 10px"),
                          fontFamily: "inherit",
                          height: "100%",
                          display: "flex", flexDirection: "column",
                          justifyContent: "center",
                          gap: isCore ? 4 : 2,
                          color: isCore ? "#fff" : undefined,
                        }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <div style={{
                        width: isCore ? 32 : (isHuman ? 18 : 22),
                        height: isCore ? 32 : (isHuman ? 18 : 22),
                        borderRadius: isCore ? 8 : 5,
                        background: isCore ? "#fbbf24" : n.color,
                        color: isCore ? "#0f172a" : "#fff",
                        display: "grid", placeItems: "center", flexShrink: 0,
                      }}>
                        <Ico size={isCore ? 18 : (isHuman ? 11 : 13)} strokeWidth={1.9} />
                      </div>
                      <div style={{
                        fontSize: isCore ? 15 : (isHuman ? 11 : 12),
                        fontWeight: 800,
                        color: isCore ? "#fff" : "var(--text-primary)",
                        lineHeight: 1.1, letterSpacing: "-0.012em",
                        overflow: "hidden", textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}>
                        {n.label}
                      </div>
                    </div>
                    <div style={{
                      fontSize: isCore ? 10 : 9,
                      color: isCore ? "#cbd5e1" : "var(--text-muted)",
                      textTransform: "uppercase", letterSpacing: 0.4,
                      fontWeight: 600,
                      overflow: "hidden", textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}>
                      {n.subtitle}
                    </div>
                    {!isHuman && n.model && !isCore && (
                      <ModelChip model={n.model} kind={n.model_kind} />
                    )}
                    <div style={{
                      fontSize: isCore ? 12 : 10.5,
                      fontWeight: 800,
                      color: isCore ? "#fbbf24" : n.color,
                      fontFamily: "ui-monospace, monospace",
                    }}>
                      {n.metric}
                    </div>
                    {isCore && (
                      <div style={{
                        fontSize: 9.5, color: "#cbd5e1",
                        fontFamily: "ui-monospace, monospace",
                        overflow: "hidden", textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}>
                        {n.metric_sub}
                      </div>
                    )}
                    {isCore && (
                      <div style={{
                        fontSize: 9, marginTop: 2,
                        color: "#fbbf24", fontWeight: 700,
                        textTransform: "uppercase", letterSpacing: 0.5,
                        display: "flex", alignItems: "center", gap: 4,
                      }}>
                        <span style={{
                          width: 6, height: 6, borderRadius: "50%",
                          background: "#fbbf24",
                          animation: "core-pulse 1.8s ease-in-out infinite",
                        }} />
                        Clique para gerenciar agentes
                      </div>
                    )}
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
      {agentsOpen && <MotorIaAgentsModal onClose={() => setAgentsOpen(false)} />}
      {selectedNode && (
        <NodeDetailModal
          node={selectedNode}
          edges={data?.edges || []}
          allNodes={data?.nodes || []}
          onClose={() => setSelectedNode(null)}
        />
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

/* =============================================================
   ACTIONS_MAP — descreve as ações que cada IA executa.
   Editar aqui é a forma mais simples de manter o painel atualizado.
============================================================= */
const ACTIONS_MAP = {
  motor: {
    description: "Orquestrador central — roteia todas as chamadas LLM para o provider correto e enforce rate limits/budget.",
    actions: [
      "Multiplexa OpenAI, Anthropic, Gemini via Emergent LLM Key",
      "Aplica purpose-based throttling (atendimento, evaluator, coach, etc)",
      "Persiste cada chamada em motor_ia_calls para audit + custos",
      "Distribui modelos por agente (atendimento vs default)",
    ],
    connections: [
      "Recebe TODA chamada LLM das IAs filhas",
      "Retorna texto/JSON sem expor a key",
      "Bloqueia se budget mensal for excedido",
    ],
  },
  smartolt: {
    description: "Detecta quedas de rede analisando logs OLT + correlaciona com clientes afetados.",
    actions: [
      "Polling do SmartOLT a cada 60s",
      "Identifica ONU offline em massa (≥5 simultâneas)",
      "Pede a Claude analisar a causa raiz (cabo, energia, splitter)",
      "Cria network_outage e injeta contexto no Atendimento IA",
    ],
    connections: [
      "→ Atendimento IA: avisa cliente afetado proativamente",
      "→ Sentinela Lousa: dispara alerta para gestores",
      "→ Lousa AI: pré-classifica tickets relacionados como 'rede regional'",
    ],
  },
  atendimento: {
    description: "Isabella — atende cliente final no WhatsApp 24/7 com personalidade configurável.",
    actions: [
      "Lê mensagem inbound + recupera contexto subscriber",
      "Roteia para Isabella/Bruno/Jerusa conforme intent (multi-agente)",
      "Gera resposta cordial em PT-BR + envia via Baileys ou Twilio",
      "Detecta intenção de cancelamento/upsell → marca tags",
      "Transfere pra humano se confidence < threshold ou pedido explícito",
    ],
    connections: [
      "← Motor IA (LLM)",
      "← SmartOLT (contexto de queda)",
      "← Aprendizado (few-shot CSAT≥8)",
      "→ Coach IA (avalia cada conversa)",
      "→ Avaliador IA (CSAT/sentimento)",
      "→ Humanos (handover quando precisar)",
    ],
  },
  copilot: {
    description: "Co-Pilot — gera sugestão de resposta para o atendente humano em tempo real (cliente NÃO vê).",
    actions: [
      "Trigga quando humano abre uma conversa",
      "Analisa últimas 5 mensagens + dados do subscriber",
      "Sugere resposta + escalas alternativas",
      "Loga aceitação/rejeição do atendente para fine-tune",
    ],
    connections: [
      "← Motor IA",
      "→ Cada atendente humano (overlay no chat)",
      "→ Coach IA (mede aceitação por atendente)",
    ],
  },
  evaluator: {
    description: "Avaliador — pontua cada conversa fechada com CSAT, sentimento e flag de FCR (resolveu em 1 contato?).",
    actions: [
      "Roda a cada 10min em conversas com status=closed",
      "Gera score 0-10 + classificação (positivo/neutro/negativo)",
      "Detecta tópicos não resolvidos para retomar",
      "Alimenta o pipeline de Aprendizado com casos CSAT≥8",
    ],
    connections: [
      "← Atendimento IA + Humanos",
      "→ Central IA (dashboard)",
      "→ Aprendizado (few-shot)",
      "→ Coach IA (recomenda treino)",
    ],
  },
  coach: {
    description: "Coach — gera recomendações pós-conversa para o atendente humano evoluir tecnicamente.",
    actions: [
      "Analisa conversa fechada vs benchmark da equipe",
      "Identifica gap específico (tempo médio, empatia, resolução)",
      "Gera 1-3 dicas inline no chat",
      "Envia push semanal de Top 3 áreas de melhoria",
    ],
    connections: [
      "← Avaliador IA",
      "→ Cada atendente humano (recomendações personalizadas)",
      "→ Central IA (ranking de evolução)",
    ],
  },
  learning: {
    description: "Aprendizado — coleta as melhores conversas (CSAT≥8) e injeta como few-shot no prompt do Atendimento.",
    actions: [
      "Filtra conversas com CSAT≥8 nos últimos 30 dias",
      "Indexa por intent (cancelamento, suporte, vendas, etc)",
      "Reescreve para anonimizar (LGPD)",
      "Injeta top-3 exemplos relevantes a cada nova conversa",
    ],
    connections: [
      "← Avaliador IA (filtra os bons)",
      "→ Atendimento IA (few-shot)",
    ],
  },
  sentinela: {
    description: "Sentinela Lousa — monitora chamados parados e padrões anormais; alerta gestores.",
    actions: [
      "Roda a cada 5min nos tickets ativos",
      "Detecta SLA estourado, chamados sem update >24h",
      "Identifica clusters geográficos suspeitos (várias OS na mesma rua)",
      "Envia push pro gestor + chip vermelho na Lousa",
    ],
    connections: [
      "← SmartOLT (correlação rede)",
      "← Lousa (tickets em tempo real)",
      "→ Gestor (alertas push/WhatsApp)",
    ],
  },
  lousa_ai: {
    description: "Lousa AI Triagem — classifica tickets novos por categoria, urgência e técnico sugerido.",
    actions: [
      "Lê descrição livre do chamado",
      "Classifica: categoria, urgência (P0-P3), tipo (visita/remoto)",
      "Sugere técnico baseado em geo + carga + skill",
      "Pre-preenche checklist veicular e EPIs do serviço",
    ],
    connections: [
      "← Lousa (tickets novos)",
      "← SmartOLT (contexto rede)",
      "→ Kanban (move pra coluna correta)",
      "→ Sentinela (se P0 dispara alerta)",
    ],
  },
  secretaria: {
    description: "Secretária IA Ligo — atende ligação telefônica, transcreve áudio, responde com TTS.",
    actions: [
      "Recebe webhook SIP da chamada entrante",
      "Transcreve áudio (Whisper) em tempo real",
      "Gera resposta (Claude) + voz natural (ElevenLabs)",
      "Salva resumo da ligação no CRM",
    ],
    connections: [
      "← Cliente final (voz)",
      "← Motor IA",
      "→ Drive backup (áudio relevante)",
    ],
  },
};

function NodeDetailModal({ node, edges, allNodes, onClose }) {
  const info = ACTIONS_MAP[node.id] || {
    description: node.subtitle || "Componente do fluxo de IA.",
    actions: [],
    connections: [],
  };
  // Calcula edges reais que tocam esse nó
  const incoming = edges.filter((e) => e.to === node.id);
  const outgoing = edges.filter((e) => e.from === node.id);
  const nodeMap = Object.fromEntries(allNodes.map((n) => [n.id, n]));
  const Icon = ICONS[node.icon] || Bot;
  return (
    <div onClick={onClose}
         data-testid="ai-node-modal"
         style={{
           position: "fixed", inset: 0, background: "rgba(15,23,42,.6)",
           display: "grid", placeItems: "center", zIndex: 9999, padding: 16,
         }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{
             background: "var(--bg-surface)", borderRadius: 16,
             width: "min(720px, 96vw)", maxHeight: "90vh",
             overflow: "hidden", display: "grid", gridTemplateRows: "auto 1fr",
             boxShadow: "0 24px 80px rgba(0,0,0,.4)",
           }}>
        {/* Header */}
        <header style={{
          padding: "16px 22px", display: "flex", alignItems: "center", gap: 12,
          background: `linear-gradient(135deg, ${node.color}22, var(--bg-surface) 70%)`,
          borderBottom: "1px solid var(--border-default)",
        }}>
          <div style={{
            width: 44, height: 44, borderRadius: 12, background: node.color,
            color: "white", display: "grid", placeItems: "center", flexShrink: 0,
          }}>
            <Icon size={22} strokeWidth={1.75} />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h2 data-testid="ai-node-modal-title"
                style={{ margin: 0, fontSize: 18, fontWeight: 800, letterSpacing: "-0.01em" }}>
              {node.label}
            </h2>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>
              {node.subtitle} · <strong>{node.metric}</strong>
            </div>
          </div>
          <button onClick={onClose} data-testid="ai-node-modal-close"
                  style={{
                    padding: 6, borderRadius: 8, border: "1px solid var(--border-default)",
                    background: "var(--bg-surface)", color: "var(--text-secondary)",
                    cursor: "pointer",
                  }}>
            <X size={18} />
          </button>
        </header>

        {/* Body */}
        <div style={{ overflow: "auto", padding: 18, display: "grid", gap: 18 }}>
          {info.description && (
            <p style={{ margin: 0, fontSize: 14, lineHeight: 1.55, color: "var(--text-primary)" }}>
              {info.description}
            </p>
          )}

          {/* Chips de modelo/kind */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {node.model && (
              <span style={{
                padding: "4px 10px", borderRadius: 999, fontSize: 11, fontWeight: 700,
                background: "var(--bg-surface-2)", color: "var(--text-secondary)",
                border: "1px solid var(--border-default)",
              }}>
                <Tag size={10} style={{ marginRight: 4 }} />
                {node.model}
              </span>
            )}
            <span style={{
              padding: "4px 10px", borderRadius: 999, fontSize: 11, fontWeight: 700,
              background: "#7c3aed12", color: "#7c3aed",
              border: "1px solid #7c3aed44",
            }}>
              <Power size={10} style={{ marginRight: 4 }} />
              {node.kind === "core" ? "Núcleo orquestrador"
                : node.kind === "ai" ? "Agente IA"
                : node.kind === "human" ? "Atendente humano"
                : node.kind}
            </span>
            <span style={{
              padding: "4px 10px", borderRadius: 999, fontSize: 11, fontWeight: 700,
              background: "#10b98112", color: "#047857",
              border: "1px solid #10b98144",
            }}>
              <Zap size={10} style={{ marginRight: 4 }} /> {node.metric_sub || "—"}
            </span>
          </div>

          {/* Ações */}
          {info.actions.length > 0 && (
            <section data-testid="ai-node-actions">
              <h3 style={{
                margin: "0 0 8px", fontSize: 11, color: "var(--text-muted)",
                fontWeight: 800, letterSpacing: ".06em",
              }}>O QUE ESTA IA FAZ</h3>
              <ul style={{ margin: 0, paddingLeft: 20, fontSize: 13.5, lineHeight: 1.6 }}>
                {info.actions.map((a, i) => (
                  <li key={i} style={{ marginBottom: 4 }}>{a}</li>
                ))}
              </ul>
            </section>
          )}

          {/* Conexões reais detectadas */}
          {(incoming.length > 0 || outgoing.length > 0) && (
            <section data-testid="ai-node-connections">
              <h3 style={{
                margin: "0 0 8px", fontSize: 11, color: "var(--text-muted)",
                fontWeight: 800, letterSpacing: ".06em",
              }}>CONEXÕES ATIVAS (24h)</h3>
              <div style={{ display: "grid", gap: 6 }}>
                {incoming.map((e, i) => {
                  const src = nodeMap[e.from];
                  return (
                    <div key={`in-${i}`} style={{
                      display: "flex", gap: 8, alignItems: "center",
                      padding: 8, background: "var(--bg-surface-2)", borderRadius: 8,
                      fontSize: 12,
                    }}>
                      <ArrowLeft size={14} color="#0ea5e9" strokeWidth={2.5} />
                      <strong>{src?.label || e.from}</strong>
                      <span style={{ color: "var(--text-muted)" }}>{e.label || "fluxo"}</span>
                      <span style={{ marginLeft: "auto", fontWeight: 700, color: "#0ea5e9" }}>
                        {e.value ?? "—"}
                      </span>
                    </div>
                  );
                })}
                {outgoing.map((e, i) => {
                  const tgt = nodeMap[e.to];
                  return (
                    <div key={`out-${i}`} style={{
                      display: "flex", gap: 8, alignItems: "center",
                      padding: 8, background: "var(--bg-surface-2)", borderRadius: 8,
                      fontSize: 12,
                    }}>
                      <ArrowRight size={14} color="#16a34a" strokeWidth={2.5} />
                      <strong>{tgt?.label || e.to}</strong>
                      <span style={{ color: "var(--text-muted)" }}>{e.label || "fluxo"}</span>
                      <span style={{ marginLeft: "auto", fontWeight: 700, color: "#16a34a" }}>
                        {e.value ?? "—"}
                      </span>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Conexões documentadas (do ACTIONS_MAP) */}
          {info.connections.length > 0 && (
            <section data-testid="ai-node-docs-connections">
              <h3 style={{
                margin: "0 0 8px", fontSize: 11, color: "var(--text-muted)",
                fontWeight: 800, letterSpacing: ".06em",
              }}>FLUXOS DOCUMENTADOS</h3>
              <ul style={{ margin: 0, paddingLeft: 20, fontSize: 12.5, lineHeight: 1.6,
                            color: "var(--text-secondary)" }}>
                {info.connections.map((c, i) => (
                  <li key={i} style={{ marginBottom: 3 }}>{c}</li>
                ))}
              </ul>
            </section>
          )}

          {/* Dica de drag */}
          <div style={{
            padding: 10, background: "#f0f9ff",
            border: "1px solid #bae6fd", borderRadius: 8,
            fontSize: 11.5, color: "#075985",
            display: "flex", alignItems: "center", gap: 6,
          }}>
            <Move size={14} />
            <span>
              <strong>Dica:</strong> arraste qualquer card no fluxograma para reorganizar.
              As posições são salvas automaticamente.
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

