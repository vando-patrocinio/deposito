import React, { useEffect, useState } from "react";
import { Card } from "@/ui";
import { api } from "@/api";
import {
  RefreshCw, CheckCircle2, AlertCircle, XCircle, Settings, X,
  Cpu, Database, Cloud, MessageSquare, Network,
} from "lucide-react";
import AgentConfigModal from "@/AgentConfigModal";

/**
 * Health-Map estilo Grafana — diagrama em tempo real da arquitetura do chat.
 * Nós CLICÁVEIS:
 *  - IA (isabella, orchestrator, evaluator, motor_ia) → abre AgentConfigModal
 *    pré-populado com o agente daquele nó (filter via topology_node).
 *  - Integrações externas (atlaz, openrouter, smartolt, mongo) → abre popover
 *    com card resumo de configuração atual + status.
 */
export default function ChatTopologyMap() {
  const [topo, setTopo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [openedNode, setOpenedNode] = useState(null);  // {id, label, kind}
  const [agentForNode, setAgentForNode] = useState(null);
  const [configOpen, setConfigOpen] = useState(false);

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

  async function handleNodeClick(node) {
    if (IA_NODE_IDS.has(node.id)) {
      // Procura agente vinculado ao topology_node
      try {
        const list = await api.aihubAgentsList();
        const agent = (list.items || []).find(
          (a) => a.topology_node === node.id
        ) || (list.items || []).find(
          (a) => a.name.toLowerCase() === node.label.toLowerCase()
        );
        setAgentForNode(agent);
        setConfigOpen(true);
      } catch {
        setOpenedNode(node);
      }
    } else {
      setOpenedNode(node);
    }
  }

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

  /* === Layout consolidado ===
     Antes: 10 nós, alguns canais espalhados (baileys, twilio, meta separados).
     Agora: 1 bolha por integração externa, descrita por dentro. */
  const POS = {
    client:       { x: 80,   y: 240, color: "#3b82f6" },
    channels:     { x: 280,  y: 240, color: "#22c55e" },  // Consolidado: WA/Meta/Twilio
    backend:      { x: 500,  y: 240, color: "#8b5cf6" },
    orchestrator: { x: 720,  y: 130, color: "#f59e0b" },
    motor_ia:     { x: 720,  y: 340, color: "#ef4444" },
    isabella:     { x: 920,  y: 130, color: "#d946ef" },
    evaluator:    { x: 920,  y: 240, color: "#a855f7" },
    openrouter:   { x: 920,  y: 30,  color: "#ec4899" },
    atlaz:        { x: 920,  y: 340, color: "#06b6d4" },
    mongo:        { x: 920,  y: 450, color: "#10b981" },
  };

  // Mapeia o backend topology (que vem com nós separados) para o layout
  // consolidado. Se algum nó vier solto (ex: baileys/twilio/meta), agrupa
  // em "channels". Status do channels = melhor entre os 3 originais.
  const consolidated = consolidateNodes(nodes, edges);

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
        gap: 8,
      }}>
        <StatTile label="Inbound 24h" value={stats.inbound_24h || 0} color="#3b82f6" />
        <StatTile label="Outbound 24h" value={stats.outbound_24h || 0} color="#10b981" />
        <StatTile label="IA respondeu" value={stats.ai_replies_24h || 0} color="#8b5cf6" />
        <StatTile label="Humano respondeu" value={stats.human_replies_24h || 0} color="#f59e0b" />
        <StatTile label="% IA autônoma" value={`${stats.ai_share_24h ?? 0}%`} color="#ec4899" />
        <StatTile label="Conversas ativas" value={stats.conversations_active || 0} color="#06b6d4" />
      </div>

      <Card style={{ padding: 14, position: "relative", overflow: "visible" }}>
        <div style={{
          display: "flex", justifyContent: "space-between", marginBottom: 8,
        }}>
          <div style={{
            fontSize: 11, fontWeight: 700, color: "var(--text-muted)",
            textTransform: "uppercase", letterSpacing: 0.5,
          }}>
            Topologia em tempo real · clique nos nós para configurar
          </div>
          {refreshing && <div style={{ fontSize: 10, color: "#10b981" }}>● atualizando</div>}
        </div>

        <svg viewBox="0 0 1040 530" style={{ width: "100%", height: "auto", maxHeight: 530 }}>
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5"
                     markerWidth="6" markerHeight="6" orient="auto">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--text-muted)" opacity="0.6" />
            </marker>
            <marker id="arrowActive" viewBox="0 0 10 10" refX="9" refY="5"
                     markerWidth="6" markerHeight="6" orient="auto">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#10b981" />
            </marker>
          </defs>

          {/* Edges */}
          {consolidated.edges.map((e, i) => {
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
                    <animateMotion dur="2.5s" repeatCount="indefinite"
                                    path={`M ${from.x + 32} ${from.y} Q ${midX} ${midY - 30} ${to.x - 32} ${to.y}`} />
                  </circle>
                )}
              </g>
            );
          })}

          {/* Nodes — clicáveis */}
          {consolidated.nodes.map((n) => {
            const p = POS[n.id];
            if (!p) return null;
            const fill = n.ok ? p.color : "#94a3b8";
            const ringColor = n.ok ? p.color : "#cbd5e1";
            return (
              <g key={n.id} transform={`translate(${p.x}, ${p.y})`}
                  style={{ cursor: "pointer" }}
                  onClick={() => handleNodeClick(n)}
                  data-testid={`topology-node-${n.id}`}>
                {n.ok && (
                  <circle r="28" fill="none" stroke={ringColor}
                          strokeWidth="2" opacity="0.25">
                    <animate attributeName="r" from="28" to="40"
                              dur="2s" repeatCount="indefinite" />
                    <animate attributeName="opacity" from="0.4" to="0"
                              dur="2s" repeatCount="indefinite" />
                  </circle>
                )}
                <circle r="26" fill={fill} opacity="0.15"
                         stroke={ringColor} strokeWidth="1.5" />
                <circle r="20" fill="white" stroke={fill} strokeWidth="2" />
                <text textAnchor="middle" y="5" fontSize="11"
                       fontWeight="700" fill={fill}>
                  {iconForKind(n.kind)}
                </text>
                <text textAnchor="middle" y="46" fontSize="10"
                       fontWeight="700" fill="var(--text-primary)">
                  {n.label}
                </text>
                <text textAnchor="middle" y="60" fontSize="8" fill="var(--text-muted)">
                  {n.status || "—"}
                </text>
                {IA_NODE_IDS.has(n.id) && (
                  <g transform="translate(15, -18)">
                    <circle r="8" fill="white" stroke={fill} strokeWidth="1.5" />
                    <text textAnchor="middle" y="3" fontSize="9" fill={fill}>⚙</text>
                  </g>
                )}
              </g>
            );
          })}
        </svg>

        <div style={{
          marginTop: 14, display: "flex", gap: 16, flexWrap: "wrap",
          fontSize: 10, color: "var(--text-muted)",
        }}>
          <LegendDot color="#10b981" label="Linha verde animada = fluxo ativo" />
          <LegendDot color="rgba(148,163,184,.6)"
                       label="Linha tracejada cinza = canal inativo / não configurado" />
          <LegendDot color="#3b82f6" label="Anel pulsante = nó saudável" />
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <Settings size={11} /> Clique nos nós para configurar
          </span>
        </div>
      </Card>

      {/* Popover para nó externo */}
      {openedNode && (
        <ExternalNodePopover node={openedNode}
                                onClose={() => setOpenedNode(null)} />
      )}
      {/* Modal de config da IA */}
      <AgentConfigModal open={configOpen}
                          onClose={() => { setConfigOpen(false); setAgentForNode(null); }}
                          initialAgentId={agentForNode?.id} />
    </div>
  );
}

const IA_NODE_IDS = new Set(["isabella", "orchestrator", "evaluator", "motor_ia"]);

function consolidateNodes(nodes, edges) {
  // Agrupa channels (baileys/twilio/meta) em 1 nó "channels"
  const channelIds = new Set(["baileys", "twilio", "meta", "meta_messenger", "meta_instagram"]);
  const channelNodes = nodes.filter((n) => channelIds.has(n.id));
  const anyChannelOk = channelNodes.some((n) => n.ok);
  const channelStatuses = channelNodes
    .map((n) => `${n.label || n.id}: ${n.status || "—"}`)
    .join(" · ");
  const consolidatedNodes = nodes.filter((n) => !channelIds.has(n.id));
  if (channelNodes.length > 0) {
    consolidatedNodes.push({
      id: "channels",
      label: "Canais Mensagens",
      kind: "channel",
      ok: anyChannelOk,
      status: channelStatuses || "—",
      _sub_nodes: channelNodes,
    });
  }
  // Adiciona Motor IA + Evaluator (mesmo se backend não mandar)
  const hasMotor = consolidatedNodes.some((n) => n.id === "motor_ia");
  if (!hasMotor) {
    consolidatedNodes.push({
      id: "motor_ia", label: "Motor IA", kind: "ai",
      ok: true, status: "active",
    });
  }
  const hasEval = consolidatedNodes.some((n) => n.id === "evaluator");
  if (!hasEval) {
    consolidatedNodes.push({
      id: "evaluator", label: "Avaliador", kind: "ai",
      ok: true, status: "active",
    });
  }
  // Mapeia edges: tudo que ia pra baileys/twilio/meta agora vai pra channels
  const consolidatedEdges = edges.map((e) => ({
    ...e,
    from: channelIds.has(e.from) ? "channels" : e.from,
    to: channelIds.has(e.to) ? "channels" : e.to,
  }));
  // Adiciona edges Backend→Motor IA, Motor IA→OpenRouter, Backend→Evaluator
  consolidatedEdges.push(
    { from: "backend", to: "motor_ia", active: true },
    { from: "motor_ia", to: "openrouter", active: true },
    { from: "backend", to: "evaluator", active: true },
  );
  return { nodes: consolidatedNodes, edges: consolidatedEdges };
}

function ExternalNodePopover({ node, onClose }) {
  const info = EXTERNAL_NODE_INFO[node.id] || {};
  const Icon = info.icon || Cloud;
  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, zIndex: 9999,
      background: "rgba(2,6,23,.4)", backdropFilter: "blur(4px)",
      display: "grid", placeItems: "center",
    }} data-testid="external-node-popover">
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "var(--bg-surface)", borderRadius: 14,
        padding: 22, maxWidth: 520, width: "92vw",
        maxHeight: "82vh", overflowY: "auto",
        boxShadow: "0 24px 60px rgba(0,0,0,.3)",
        border: "1px solid var(--border-default)",
      }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 12, marginBottom: 16,
        }}>
          <div style={{
            width: 44, height: 44, borderRadius: 12,
            background: info.color || "#64748b", color: "white",
            display: "grid", placeItems: "center",
          }}>
            <Icon size={22} strokeWidth={1.75} />
          </div>
          <div style={{ flex: 1 }}>
            <h3 style={{
              margin: 0, fontSize: 16, fontWeight: 800,
              letterSpacing: "-0.012em", color: "var(--text-primary)",
            }}>{info.title || node.label}</h3>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
              {info.subtitle || (node.status || "Integração externa")}
            </div>
          </div>
          <button onClick={onClose} data-testid="close-external-popover"
                  style={{
                    background: "var(--bg-surface-2)", border: "none",
                    width: 32, height: 32, borderRadius: 8,
                    cursor: "pointer", display: "grid", placeItems: "center",
                    color: "var(--text-muted)",
                  }}><X size={16} /></button>
        </div>
        <div style={{
          fontSize: 13, color: "var(--text-primary)", lineHeight: 1.65,
          whiteSpace: "pre-wrap",
        }}>{info.description || "Nenhuma descrição disponível."}</div>

        {info.config && (
          <div style={{ marginTop: 18 }}>
            <div style={{
              fontSize: 10, fontWeight: 800, color: "var(--text-muted)",
              textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 8,
            }}>Configuração atual</div>
            <div style={{
              padding: 12, borderRadius: 10,
              background: "var(--bg-surface-2)",
              border: "1px solid var(--border-default)",
              fontFamily: "JetBrains Mono, monospace", fontSize: 12,
              lineHeight: 1.7, color: "var(--text-primary)",
              whiteSpace: "pre-wrap", wordBreak: "break-word",
            }}>{info.config}</div>
          </div>
        )}
      </div>
    </div>
  );
}

const EXTERNAL_NODE_INFO = {
  client: {
    title: "Cliente WhatsApp", icon: MessageSquare, color: "#3b82f6",
    subtitle: "Usuário final no app WhatsApp",
    description:
      "Cliente final (assinante Ligo Fibra) conversando via WhatsApp. " +
      "Pode chegar por 3 canais: Baileys (WA Web não-oficial), Twilio (WhatsApp " +
      "Business API) ou Meta (WhatsApp Cloud + Messenger + Instagram DM).",
    config: "ATIVO\nPolíticas: TTL JWT 30d em localStorage · Reuso de sessão " +
            "sem invalidar.\nFluxo entrada: webhook → /api/whatsapp-baileys/inbound",
  },
  channels: {
    title: "Canais de Mensagens", icon: Network, color: "#22c55e",
    subtitle: "Baileys + Twilio + Meta Cloud (consolidado)",
    description:
      "Camada que recebe/envia mensagens WhatsApp:\n\n" +
      "• Baileys (sidecar Node.js · porta 3002) — WhatsApp Web não-oficial, " +
      "QR Code 512px, reconexão automática a cada 2min via cron.\n\n" +
      "• Twilio WhatsApp Business API — canal oficial, requer chave (Twilio " +
      "Account SID + Token). Suporta templates aprovados pela Meta.\n\n" +
      "• Meta WhatsApp Cloud API — canal direto Meta (sem Twilio), suporta " +
      "Messenger e Instagram DM. Aguardando aprovação App Review.",
    config: "Baileys: localhost:3002 · QR 512px · errorCorrection M\n" +
             "Twilio: requires TWILIO_SID + TWILIO_TOKEN\n" +
             "Meta:   requires META_APP_TOKEN (em pending review)\n" +
             "Health-check: cron 2min POST /api/integrations/health",
  },
  backend: {
    title: "FastAPI Backend", icon: Cpu, color: "#8b5cf6",
    subtitle: "Server Python · 0.0.0.0:8001",
    description:
      "Servidor FastAPI rodando o core da SmartProv. Hot-reload habilitado " +
      "via supervisor. Endpoints principais:\n\n" +
      "• POST /api/whatsapp-baileys/inbound — webhook das msgs\n" +
      "• POST /api/aihub/agents — CRUD de agentes IA\n" +
      "• POST /api/atlaz/sync-customers — sincronização nightly\n" +
      "• GET /api/integrations/health — auto-reconnect cron\n" +
      "• POST /api/auth/login — JWT 30d (sem single-session)\n\n" +
      "Auto-release: humano sem responder >30min → conversa volta pra IA.",
    config: "Hot reload: ON · Supervisor: backend\n" +
             "JWT TTL: 30d · Single-session: DESATIVADO (Slack pattern)\n" +
             "MongoDB: localhost:27017/test_database\n" +
             "CORS: configurável via CORS_ORIGINS",
  },
  mongo: {
    title: "MongoDB", icon: Database, color: "#10b981",
    subtitle: "test_database · localhost:27017",
    description:
      "Banco principal. Coleções principais:\n\n" +
      "• subscribers — 2.727 docs (sync diário 22h Atlaz)\n" +
      "• subscriber_phones — lookup phone→subscriber\n" +
      "• smartolt_onus — 1.754 docs (status ONU em cache)\n" +
      "• aihub_agents — 4 agentes IA (Isabella, Orquestrador, Avaliador, Motor IA)\n" +
      "• aihub_wa_messages — histórico mensagens\n" +
      "• ai_corrections — Edit & Teach (correções aprovadas)\n" +
      "• tickets — Kanban (criados automático pela Isabella em LOS/Offline)\n" +
      "• smartolt_actions — reboot logs (audit Isabella IA)",
    config: "DB_NAME: test_database\nIndices: company_id em todas as " +
             "coleções principais.\nPolíticas: nunca retornar _id em " +
             "endpoints (Pydantic model_dump).",
  },
  openrouter: {
    title: "OpenRouter", icon: Cloud, color: "#ec4899",
    subtitle: "Gateway LLM unificado",
    description:
      "Gateway que abstrai múltiplos modelos LLM (DeepSeek, Claude, GPT-5, " +
      "Gemini). Usado pela Isabella + Motor IA + Avaliador.\n\n" +
      "Modelo padrão atual: deepseek-v3.1-terminus (estabilidade).\n" +
      "Anterior v4-pro abandonado devido a hallucination em coreano.\n\n" +
      "Heurística anti-garbage: motor_ia.py detecta caracteres não-PT no " +
      "output e dispara retry automático com fallback model.",
    config: "Default model: deepseek/deepseek-v3.1-terminus\n" +
             "Fallback: anthropic/claude-sonnet-4-5 / openai/gpt-5\n" +
             "API key: OPENROUTER_API_KEY (.env)\n" +
             "Anti-hallucination: garbage detection + retry once",
  },
  atlaz: {
    title: "Atlaz API", icon: Cloud, color: "#06b6d4",
    subtitle: "ERP externo · dados dos assinantes",
    description:
      "Sistema ERP da operadora Ligo Fibra. Fonte de verdade para:\n\n" +
      "• Cadastro de assinantes (CPF, nome, plano, branch, status)\n" +
      "• Vencimentos e pagamentos\n" +
      "• Histórico contratual\n" +
      "• Validação Volta Amigo (ex-clientes que cancelaram)\n\n" +
      "Sync: cron diário 22h00 (`/api/atlaz/sync-customers`) + on-demand " +
      "via botão no Central IA.",
    config: "Endpoint: ATLAZ_API_URL (.env)\nAuth: ATLAZ_API_KEY (.env)\n" +
             "Sync schedule: 22h00 diário (APScheduler)\n" +
             "Coleção destino: subscribers\nÚltimo sync: ver dashboard Central IA",
  },
};

function iconForKind(kind) {
  return {
    endpoint: "📱", channel: "📡", core: "⚙",
    storage: "🗄", ai: "🧠", agent: "✦", data: "📊",
  }[kind] || "•";
}

function StatTile({ label, value, color }) {
  return (
    <Card style={{ padding: 10, borderLeft: `3px solid ${color}` }}>
      <div style={{
        fontSize: 9, color: "var(--text-muted)", fontWeight: 700,
        textTransform: "uppercase", letterSpacing: 0.5,
      }}>{label}</div>
      <div style={{
        fontSize: 18, fontWeight: 700, color: "var(--text-primary)", marginTop: 2,
      }}>{value}</div>
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
