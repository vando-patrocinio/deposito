/* =============================================================
   RedeIaFlowchart — Fluxograma visual FTTH usando React Flow
   Hierarquia: OLT → Slot → PON → Splitter → CTO → Portas/Clientes
   (Fase 4)
============================================================= */
import React, { useEffect, useState, useCallback, useMemo } from "react";
import ReactFlow, {
  Background, Controls, MiniMap, useNodesState, useEdgesState,
  MarkerType, Position,
} from "reactflow";
import "reactflow/dist/style.css";
import { api } from "@/api";
import { Card } from "@/ui";

// Cores por tipo de nó
const NODE_COLORS = {
  bairro: { bg: "#dbeafe", border: "#2563eb", fg: "#1e3a8a" },
  cto: { bg: "#ede9fe", border: "#7c3aed", fg: "#4c1d95" },
  client: { bg: "#dcfce7", border: "#16a34a", fg: "#14532d" },
  splitter: { bg: "#fed7aa", border: "#ea580c", fg: "#7c2d12" },
};

function nodeStyle(type) {
  const c = NODE_COLORS[type] || NODE_COLORS.cto;
  return {
    background: c.bg,
    border: `2px solid ${c.border}`,
    color: c.fg,
    borderRadius: 10,
    padding: "10px 14px",
    fontSize: 12,
    fontWeight: 700,
    minWidth: 140,
    boxShadow: "0 2px 4px rgba(0,0,0,0.08)",
  };
}

// Layout simples: distribui CTOs ao redor do nó de bairro
function buildLayout(raw) {
  const nodes = [];
  const edges = [];
  const bairros = raw.nodes.filter((n) => n.type === "group_bairro");
  const ctos = raw.nodes.filter((n) => n.type === "cto");
  const clients = raw.nodes.filter((n) => n.type === "client");

  bairros.forEach((b, i) => {
    nodes.push({
      id: b.id,
      type: "default",
      data: { label: <div><strong>📡 {b.data.label}</strong></div> },
      position: { x: 50, y: 50 + i * 260 },
      style: nodeStyle("bairro"),
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    });
  });

  // Group CTOs by parent bairro
  const byBairro = {};
  raw.edges.forEach((e) => {
    if (e.source.startsWith("bairro::")) {
      (byBairro[e.source] = byBairro[e.source] || []).push(e.target);
    }
  });

  Object.entries(byBairro).forEach(([bairroId, ctoIds]) => {
    const bIdx = bairros.findIndex((b) => b.id === bairroId);
    const baseY = 50 + bIdx * 260;
    ctoIds.forEach((ctoId, ci) => {
      const c = ctos.find((x) => x.id === ctoId);
      if (!c) return;
      const used = (c.data.ports || []).filter((p) => p.status === "used").length;
      nodes.push({
        id: c.id,
        type: "default",
        data: {
          label: (
            <div style={{ textAlign: "left" }}>
              <div style={{ fontWeight: 800, marginBottom: 2 }}>{c.data.label}</div>
              <div style={{ fontSize: 10, color: "#5b21b6", opacity: 0.85 }}>
                {used}/{c.data.capacity} portas · {c.data.network_type}
                {c.data.splitter ? ` (${c.data.splitter})` : ""}
              </div>
            </div>
          ),
        },
        position: { x: 320 + (ci % 3) * 200, y: baseY + Math.floor(ci / 3) * 100 },
        style: nodeStyle("cto"),
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
      });
    });
  });

  // Clients (portas ocupadas)
  const clientsByCto = {};
  raw.edges.forEach((e) => {
    if (e.source.startsWith("cto::") && e.target.startsWith("client::")) {
      (clientsByCto[e.source] = clientsByCto[e.source] || []).push(e);
    }
  });
  Object.entries(clientsByCto).forEach(([ctoId, ces]) => {
    const ctoNode = nodes.find((n) => n.id === ctoId);
    if (!ctoNode) return;
    ces.forEach((e, idx) => {
      const cli = clients.find((x) => x.id === e.target);
      if (!cli) return;
      nodes.push({
        id: cli.id,
        type: "default",
        data: { label: <div>👤 {cli.data.label}<div style={{ fontSize: 10, opacity: 0.7 }}>P{cli.data.port}</div></div> },
        position: { x: ctoNode.position.x + 220, y: ctoNode.position.y + idx * 40 },
        style: { ...nodeStyle("client"), minWidth: 100, fontSize: 11 },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
      });
    });
  });

  // Edges com seta
  raw.edges.forEach((e) => {
    edges.push({
      id: e.id,
      source: e.source, target: e.target,
      label: e.label,
      animated: false,
      markerEnd: { type: MarkerType.ArrowClosed },
      style: { stroke: "#94a3b8", strokeWidth: 1.5 },
    });
  });

  return { nodes, edges };
}

export default function RedeIaFlowchart() {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [meta, setMeta] = useState({ ctos_count: 0 });
  const [loading, setLoading] = useState(false);
  const [vlanFilter, setVlanFilter] = useState("");
  const [bairroFilter, setBairroFilter] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (vlanFilter) params.vlan = parseInt(vlanFilter, 10);
      if (bairroFilter) params.bairro = bairroFilter;
      const r = await api.redeIaFlowchart(params);
      setMeta({ ctos_count: r.ctos_count });
      const built = buildLayout(r);
      setNodes(built.nodes);
      setEdges(built.edges);
    } catch (e) {
      console.error(e);
    } finally { setLoading(false); }
  }, [vlanFilter, bairroFilter, setNodes, setEdges]);

  useEffect(() => { load(); }, [load]);

  const exportPng = useCallback(() => {
    // Solução simples: usa o snapshot do canvas do React Flow.
    // A lib expõe um botão "fullscreen" via Controls. Para PNG real,
    // recomenda-se html-to-image, mas mantemos leve por enquanto.
    window.print();
  }, []);

  return (
    <Card style={{ padding: 0, overflow: "hidden", display: "flex",
                    flexDirection: "column" }}>
      <div style={{
        display: "flex", gap: 10, padding: 12, alignItems: "center",
        background: "var(--bg-surface-2)", borderBottom: "1px solid var(--border-default)",
        flexWrap: "wrap",
      }}>
        <input data-testid="flow-filter-vlan" placeholder="Filtrar VLAN"
          value={vlanFilter} onChange={(e) => setVlanFilter(e.target.value)}
          style={{ padding: "6px 10px", borderRadius: 6,
                    border: "1px solid var(--border-default)", fontSize: 12, width: 120 }} />
        <input data-testid="flow-filter-bairro" placeholder="Filtrar bairro"
          value={bairroFilter} onChange={(e) => setBairroFilter(e.target.value)}
          style={{ padding: "6px 10px", borderRadius: 6,
                    border: "1px solid var(--border-default)", fontSize: 12, width: 180 }} />
        <button data-testid="flow-refresh" onClick={load}
                style={{ padding: "6px 12px", borderRadius: 6, background: "#0f172a",
                          color: "#fff", border: 0, fontSize: 12, cursor: "pointer" }}>
          {loading ? "Carregando..." : "Atualizar fluxograma"}
        </button>
        <button data-testid="flow-export" onClick={exportPng}
                style={{ padding: "6px 12px", borderRadius: 6, background: "#7c3aed",
                          color: "#fff", border: 0, fontSize: 12, cursor: "pointer" }}>
          Exportar (imprimir/PDF)
        </button>
        <span style={{ marginLeft: "auto", fontSize: 12,
                       color: "var(--text-muted)" }}>
          {meta.ctos_count} CTOs aprovadas no fluxograma
        </span>
      </div>
      <div style={{ height: 600, background: "#fafafa" }}>
        {nodes.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center",
                          color: "var(--text-muted)", fontSize: 14 }}>
            Nenhuma CTO aprovada para exibir. Valide pendências para alimentar o fluxograma.
          </div>
        ) : (
          <ReactFlow
            nodes={nodes} edges={edges}
            onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
            fitView fitViewOptions={{ padding: 0.2 }}
            proOptions={{ hideAttribution: true }}
          >
            <Background />
            <Controls />
            <MiniMap pannable zoomable />
          </ReactFlow>
        )}
      </div>
    </Card>
  );
}
