import React, { useEffect, useState } from "react";
import { Card } from "@/ui";
import { api } from "@/api";
import { RefreshCw, CheckCircle2, AlertCircle, XCircle } from "lucide-react";

/**
 * Health-Map estilo Grafana — diagrama em tempo real da arquitetura do chat
 * WhatsApp + IAs + integrações. Polling a cada 8s.
 *
 * Posicionamento dos nós em grid 3×3 + 1 (10 nós). Linhas curvas (Bezier)
 * conectam os nós com indicador animado de fluxo ativo.
 */
export default function ChatTopologyMap() {
  const [topo, setTopo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    try {
      setRefreshing(true);
      const r = await api.integrationsTopology();
      setTopo(r);
    } catch (e) {
      setTopo({ error: e?.response?.data?.detail || e.message });
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 8000);
    return () => clearInterval(id);
  }, []);

  if (loading) {
    return (
      <Card style={{ padding: 24, textAlign: "center", color: "var(--text-muted)" }}>
        <RefreshCw size={20} className="ci-spin" /> Carregando topologia…
        <style>{`@keyframes ci-spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}.ci-spin{animation:ci-spin 1s linear infinite}`}</style>
      </Card>
    );
  }

  if (topo?.error) {
    return (
      <Card style={{ padding: 18, color: "#b91c1c" }}>
        <AlertCircle size={16} /> {topo.error}
      </Card>
    );
  }

  const nodes = topo.nodes || [];
  const edges = topo.edges || [];
  const stats = topo.stats || {};

  // Posicionamento manual otimizado para o fluxo lógico
  const POS = {
    client:       { x: 80,  y: 240, color: "#3b82f6" },
    baileys:      { x: 280, y: 80,  color: "#22c55e" },
    twilio:       { x: 280, y: 240, color: "#ef4444" },
    meta:         { x: 280, y: 400, color: "#0ea5e9" },
    backend:      { x: 500, y: 240, color: "#8b5cf6" },
    mongo:        { x: 720, y: 400, color: "#10b981" },
    orchestrator: { x: 720, y: 130, color: "#f59e0b" },
    isabella:     { x: 920, y: 130, color: "#d946ef" },
    openrouter:   { x: 920, y: 30,  color: "#ec4899" },
    atlaz:        { x: 920, y: 280, color: "#06b6d4" },
  };

  const nodeMap = Object.fromEntries(nodes.map((n) => [n.id, n]));

  return (
    <div style={{ display: "grid", gap: 12 }}>
      {/* KPIs de mensagens 24h */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 8 }}>
        <StatTile label="Inbound 24h" value={stats.inbound_24h || 0} color="#3b82f6" />
        <StatTile label="Outbound 24h" value={stats.outbound_24h || 0} color="#10b981" />
        <StatTile label="IA respondeu" value={stats.ai_replies_24h || 0} color="#8b5cf6" />
        <StatTile label="Humano respondeu" value={stats.human_replies_24h || 0} color="#f59e0b" />
        <StatTile label="% IA autônoma" value={`${stats.ai_share_24h ?? 0}%`} color="#ec4899" />
        <StatTile label="Conversas ativas" value={stats.conversations_active || 0} color="#06b6d4" />
      </div>

      <Card style={{ padding: 14, position: "relative", overflow: "hidden" }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.5 }}>
            Topologia em tempo real · atualiza a cada 8s
          </div>
          {refreshing && <div style={{ fontSize: 10, color: "#10b981" }}>● atualizando</div>}
        </div>

        <svg viewBox="0 0 1040 480" style={{ width: "100%", height: "auto", maxHeight: 480 }}>
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--text-muted)" opacity="0.6" />
            </marker>
            <marker id="arrowActive" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#10b981" />
            </marker>
          </defs>

          {/* Edges */}
          {edges.map((e, i) => {
            const from = POS[e.from];
            const to = POS[e.to];
            if (!from || !to) return null;
            const dx = to.x - from.x;
            const dy = to.y - from.y;
            const midX = from.x + dx / 2;
            const midY = from.y + dy / 2;
            const stroke = e.active ? "#10b981" : "rgba(148,163,184,.4)";
            const marker = e.active ? "url(#arrowActive)" : "url(#arrow)";
            return (
              <g key={`e-${i}`}>
                <path
                  d={`M ${from.x + 32} ${from.y} Q ${midX} ${midY - 30} ${to.x - 32} ${to.y}`}
                  stroke={stroke}
                  strokeWidth={e.active ? 1.8 : 1.2}
                  fill="none"
                  markerEnd={marker}
                  strokeDasharray={e.active ? "0" : "5,3"}
                />
                {e.active && (
                  <circle r="3.5" fill="#10b981">
                    <animateMotion
                      dur="2.5s"
                      repeatCount="indefinite"
                      path={`M ${from.x + 32} ${from.y} Q ${midX} ${midY - 30} ${to.x - 32} ${to.y}`}
                    />
                  </circle>
                )}
              </g>
            );
          })}

          {/* Nodes */}
          {nodes.map((n) => {
            const p = POS[n.id];
            if (!p) return null;
            const fill = n.ok ? p.color : "#94a3b8";
            const ringColor = n.ok ? p.color : "#cbd5e1";
            const StatusIcon = n.ok ? CheckCircle2 : (n.needs_action ? AlertCircle : XCircle);
            return (
              <g key={n.id} transform={`translate(${p.x}, ${p.y})`}>
                {n.ok && (
                  <circle r="28" fill="none" stroke={ringColor} strokeWidth="2" opacity="0.25">
                    <animate attributeName="r" from="28" to="40" dur="2s" repeatCount="indefinite" />
                    <animate attributeName="opacity" from="0.4" to="0" dur="2s" repeatCount="indefinite" />
                  </circle>
                )}
                <circle r="26" fill={fill} opacity="0.15" stroke={ringColor} strokeWidth="1.5" />
                <circle r="20" fill="white" stroke={fill} strokeWidth="2" />
                <text textAnchor="middle" y="5" fontSize="11" fontWeight="700" fill={fill}>
                  {iconForKind(n.kind)}
                </text>
                <text textAnchor="middle" y="46" fontSize="10" fontWeight="700" fill="var(--text-primary)">
                  {n.label}
                </text>
                <text textAnchor="middle" y="60" fontSize="8" fill="var(--text-muted)">
                  {n.status || "—"}
                </text>
              </g>
            );
          })}
        </svg>

        {/* Legend */}
        <div style={{ marginTop: 14, display: "flex", gap: 16, flexWrap: "wrap", fontSize: 10, color: "var(--text-muted)" }}>
          <LegendDot color="#10b981" label="Linha verde animada = fluxo ativo" />
          <LegendDot color="rgba(148,163,184,.6)" label="Linha tracejada cinza = canal inativo / não configurado" />
          <LegendDot color="#3b82f6" label="Anel pulsante = nó saudável" />
        </div>
      </Card>
    </div>
  );
}

function iconForKind(kind) {
  return {
    endpoint: "📱",
    channel: "📡",
    core: "⚙",
    storage: "🗄",
    ai: "🧠",
    agent: "✦",
    data: "📊",
  }[kind] || "•";
}

function StatTile({ label, value, color }) {
  return (
    <Card style={{ padding: 10, borderLeft: `3px solid ${color}` }}>
      <div style={{ fontSize: 9, color: "var(--text-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>
        {label}
      </div>
      <div style={{ fontSize: 18, fontWeight: 700, color: "var(--text-primary)", marginTop: 2 }}>
        {value}
      </div>
    </Card>
  );
}

function LegendDot({ color, label }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: color }} />
      {label}
    </span>
  );
}
