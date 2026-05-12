import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import {
  Bot, MessageCircle, Phone, Send, Settings, History,
  Plus, Trash2, Edit2, Play, Save, X, RefreshCw, CheckCircle2,
  AlertTriangle, Wifi, WifiOff, Plug,
  Sparkles, Building2, DollarSign, Star, Wand2, ArrowUp, QrCode,
} from "lucide-react";
import WhatsAppQRPanel from "@/WhatsAppQRPanel";
import CentralIaDashboard from "@/CentralIaDashboard";

const BASE_TABS = [
  { id: "whatsapp_qr", label: "WhatsApp", icon: QrCode, dynamic: true },
  { id: "mensagem", label: "Mensagem", icon: MessageCircle },
  { id: "playground", label: "Playground", icon: MessageCircle },
  { id: "dial", label: "Discar (outbound)", icon: Phone },
  { id: "whatsapp", label: "WhatsApp Cloud", icon: Send },
  { id: "history", label: "Histórico", icon: History },
];

export default function AIHubPanel({ initialTab = "whatsapp_qr" }) {
  const [tab, setTab] = useState(initialTab);
  const [instanceName, setInstanceName] = useState("Ligo");
  const [waConnected, setWaConnected] = useState(false);
  useEffect(() => { setTab(initialTab); }, [initialTab]);

  // Carrega nome customizado da instância + status de conexão
  useEffect(() => {
    let alive = true;
    const fetchInfo = async () => {
      try {
        const [inst, qr] = await Promise.all([
          api.waBaileysGetInstance().catch(() => ({})),
          api.waBaileysQR().catch(() => ({})),
        ]);
        if (!alive) return;
        if (inst?.display_name) setInstanceName(inst.display_name);
        setWaConnected((qr?.status || "") === "connected");
      } catch { /* ignore */ }
    };
    fetchInfo();
    const t = setInterval(fetchInfo, 15000);
    const onRenamed = (e) => {
      if (e?.detail?.name) setInstanceName(e.detail.name);
    };
    window.addEventListener("wa-instance-renamed", onRenamed);
    return () => {
      alive = false;
      clearInterval(t);
      window.removeEventListener("wa-instance-renamed", onRenamed);
    };
  }, []);

  const TABS = useMemo(() => BASE_TABS.map((t) => (
    t.dynamic ? { ...t, label: instanceName } : t
  )), [instanceName]);

  // Modo full-screen para a aba WhatsApp (chat ocupa toda a tela)
  const isWaFull = tab === "whatsapp_qr";
  useEffect(() => {
    if (isWaFull) {
      document.body.classList.add("aihub-wa-fullscreen");
    } else {
      document.body.classList.remove("aihub-wa-fullscreen");
    }
    return () => document.body.classList.remove("aihub-wa-fullscreen");
  }, [isWaFull]);

  return (
    <div data-testid="aihub-panel"
          data-fullscreen={isWaFull ? "1" : "0"}
          style={{ padding: "0 4px" }}>
      {!isWaFull && (
        <div style={{ marginBottom: 14 }}>
          <h1 className="page-title" style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Bot size={24} strokeWidth={1.75} /> Atendimento IA
          </h1>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 4 }}>
            Agentes conversacionais usando IA local. Integre com MagnusBilling (SIP)
            e WhatsApp Cloud API para atendimento automatizado por voz e texto.
          </p>
        </div>
      )}

      <div style={{
        display: "flex", gap: 4, padding: 4, background: "var(--bg-surface-2)",
        borderRadius: 12, marginBottom: isWaFull ? 8 : 16,
        overflowX: "auto", flexWrap: "wrap",
      }}>
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = tab === t.id;
          const isLigo = t.dynamic;
          return (
            <button key={t.id} onClick={() => setTab(t.id)}
                    data-testid={`aihub-tab-${t.id}`}
                    style={{
                      position: "relative",
                      padding: "8px 14px", border: "none", borderRadius: 8,
                      background: active ? "var(--bg-surface)" : "transparent",
                      color: active ? "var(--text-primary)" : "var(--text-secondary)",
                      fontWeight: active ? 700 : 500, fontSize: 13, cursor: "pointer",
                      display: "inline-flex", alignItems: "center", gap: 6,
                      whiteSpace: "nowrap",
                      boxShadow: active ? "var(--shadow-sm)" : "none",
                    }}>
              {isLigo ? (
                <span data-testid="ligo-status-indicator"
                      title={waConnected ? "WhatsApp conectado" : "WhatsApp desconectado"}
                      style={{
                        position: "relative", display: "inline-flex",
                        alignItems: "center", justifyContent: "center",
                      }}>
                  <Plug size={14}
                         strokeWidth={2}
                         style={{
                           color: waConnected ? "#16a34a" : "var(--text-muted)",
                           transition: "color .25s",
                         }} />
                  <span style={{
                    position: "absolute",
                    top: -2, right: -3,
                    width: 7, height: 7, borderRadius: "50%",
                    background: waConnected ? "#16a34a" : "#94a3b8",
                    boxShadow: waConnected
                      ? "0 0 0 2px var(--bg-surface-2), 0 0 6px rgba(22,163,74,.7)"
                      : "0 0 0 2px var(--bg-surface-2)",
                    animation: waConnected ? "ligo-pulse 2s ease-in-out infinite" : "none",
                  }} />
                </span>
              ) : (
                <Icon size={14} />
              )}
              {t.label}
            </button>
          );
        })}
      </div>

      {tab === "central_ia" && <CentralIaDashboard />}
      {tab === "whatsapp_qr" && <WhatsAppQRPanel />}
      {tab === "mensagem" && <MensagemTab />}
      {tab === "playground" && <PlaygroundTab />}
      {tab === "dial" && <DialTab />}
      {tab === "whatsapp" && <WhatsappCloudTab />}
      {tab === "history" && <HistoryTab />}
    </div>
  );
}

/* =============================================================
   Mensagem — sub-aba com canais de mensageria (Google, etc)
============================================================= */
function MensagemTab() {
  return (
    <div data-testid="mensagem-tab" style={{ display: "grid", gap: 14 }}>
      <div>
        <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)",
                       letterSpacing: "-0.012em", margin: 0 }}>
          Canais de mensagem
        </h2>
        <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 4 }}>
          Configure os canais de mensageria que sua operação utiliza para
          atendimento ao cliente.
        </p>
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
        gap: 12,
      }}>
        <MessageChannelCard
          name="Mensagem Google"
          subtitle="Google Business Messages"
          description="Receba mensagens via Google Search e Google Maps. Integração oficial Google Business Messages para empresas verificadas."
          status="not_configured"
          testId="mensagem-google-card"
        />
      </div>
    </div>
  );
}

function MessageChannelCard({ name, subtitle, description, status, testId }) {
  const statusInfo = {
    not_configured: { label: "Não configurado", color: "var(--text-muted)",
                        bg: "var(--bg-surface-2)" },
    active: { label: "Ativo", color: "#16a34a",
                bg: "rgba(34,197,94,.10)" },
    error: { label: "Com erro", color: "#dc2626",
               bg: "rgba(220,38,38,.10)" },
  }[status] || { label: status, color: "var(--text-muted)",
                  bg: "var(--bg-surface-2)" };

  return (
    <div data-testid={testId} style={{
      padding: 16, borderRadius: 10,
      border: "1px solid var(--border-default)",
      background: "var(--bg-surface)",
      display: "flex", flexDirection: "column", gap: 10,
    }}>
      <div style={{ display: "flex", alignItems: "flex-start",
                     justifyContent: "space-between", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 8,
            background: "var(--bg-surface-2)",
            border: "1px solid var(--border-default)",
            display: "grid", placeItems: "center",
            color: "var(--text-primary)",
          }}>
            <MessageCircle size={18} strokeWidth={1.75} />
          </div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600,
                             color: "var(--text-primary)" }}>{name}</div>
            <div style={{ fontSize: 11, color: "var(--text-muted)",
                             marginTop: 2 }}>{subtitle}</div>
          </div>
        </div>
        <span style={{
          fontSize: 10, fontWeight: 700, padding: "3px 8px", borderRadius: 4,
          color: statusInfo.color, background: statusInfo.bg,
          textTransform: "uppercase", letterSpacing: 0.4,
          whiteSpace: "nowrap",
        }}>{statusInfo.label}</span>
      </div>
      <p style={{ fontSize: 12, color: "var(--text-secondary)",
                    margin: 0, lineHeight: 1.5 }}>{description}</p>
      <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
        <button data-testid={`${testId}-configure`}
                onClick={() => alert("Integração Google Business Messages — em breve.\n\nPara habilitar, sua empresa precisa estar verificada no Google Business Profile e ter um agente aprovado pelo Google.")}
                style={{
                  padding: "6px 12px", borderRadius: 6,
                  border: "1px solid var(--border-default)",
                  background: "transparent",
                  color: "var(--text-primary)",
                  fontSize: 11, fontWeight: 600, cursor: "pointer",
                }}>
          Configurar
        </button>
      </div>
    </div>
  );
}



/* =============================================================
   Agents
============================================================= */
export function AgentsTab() {
  const [agents, setAgents] = useState([]);
  const [editing, setEditing] = useState(null);  // {id?, ...}
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const r = await api.aihubAgentsList();
    setAgents(r.items || []);
  };
  useEffect(() => { load(); }, []);

  const newAgent = () => setEditing({
    name: "", description: "", initial_message: "Olá! Como posso ajudar?",
    system_prompt: "Você é um atendente comercial brasileiro. Seja cordial, objetivo e natural. Faça uma pergunta por vez. Mantenha respostas curtas.",
    model_provider: "gemini", model_name: "gemini-2.5-flash",
    temperature: 0.6, max_tokens: 700,
    form_fields: [], tools_enabled: [], webhook_url: "", active: true,
    company_info: "", pricing_info: "", priority_situations: "",
  });

  const save = async () => {
    if (!editing.name || editing.name.length < 2) {
      alert("Informe um nome com pelo menos 2 caracteres."); return;
    }
    if (!editing.system_prompt || editing.system_prompt.length < 10) {
      alert("System prompt precisa ter pelo menos 10 caracteres."); return;
    }
    setBusy(true);
    try {
      if (editing.id) {
        await api.aihubAgentUpdate(editing.id, editing);
      } else {
        await api.aihubAgentCreate(editing);
      }
      setEditing(null);
      await load();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  const del = async (id) => {
    if (!window.confirm("Excluir este agente? Conversas e histórico serão removidos também.")) return;
    setBusy(true);
    try {
      await api.aihubAgentDelete(id);
      await load();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  if (editing) return <AgentEditor agent={editing} setAgent={setEditing}
                                    busy={busy} onSave={save}
                                    onCancel={() => setEditing(null)} />;

  return (
    <div className="surface" style={{ padding: 18, borderRadius: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Agentes IA cadastrados</h3>
          <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>
            {agents.length} agente{agents.length !== 1 ? "s" : ""} · use o playground para testar.
          </div>
        </div>
        <button onClick={newAgent} className="btn btn-primary btn-sm"
                data-testid="aihub-new-agent-btn">
          <Plus size={14} /> Novo agente
        </button>
      </div>

      {agents.length === 0 ? (
        <EmptyState icon={Bot} title="Nenhum agente ainda"
          description='Crie um agente IA com prompt customizado para começar.' />
      ) : (
        <div style={{ display: "grid", gap: 10 }}>
          {agents.map((a) => (
            <div key={a.id} data-testid={`aihub-agent-${a.id}`}
                 style={{
                   padding: "14px 16px", border: "1px solid var(--border-default)",
                   borderRadius: 12, background: "var(--bg-surface)",
                   display: "flex", justifyContent: "space-between", gap: 12,
                   alignItems: "flex-start",
                 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <span style={{ fontSize: 15, fontWeight: 700, color: "var(--text-primary)" }}>
                    {a.name}
                  </span>
                  <span className={`pill pill--${a.active ? "success" : "neutral"}`}>
                    {a.active ? "Ativo" : "Inativo"}
                  </span>
                </div>
                {a.description && (
                  <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 6 }}>
                    {a.description}
                  </div>
                )}
                <div style={{ fontSize: 11, color: "var(--text-muted)", display: "flex", gap: 12, flexWrap: "wrap" }}>
                  <span><strong>Modelo:</strong> {a.model_provider}/{a.model_name}</span>
                  <span><strong>Temp:</strong> {a.temperature}</span>
                  <span><strong>Tokens:</strong> {a.max_tokens}</span>
                  {a.form_fields?.length > 0 && <span><strong>Campos:</strong> {a.form_fields.length}</span>}
                  {a.tools_enabled?.length > 0 && <span><strong>Tools:</strong> {a.tools_enabled.length}</span>}
                </div>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button onClick={() => setEditing({ ...a })}
                        data-testid={`aihub-edit-${a.id}`}
                        className="btn btn-ghost btn-sm">
                  <Edit2 size={13} /> Editar
                </button>
                <button onClick={() => del(a.id)}
                        data-testid={`aihub-delete-${a.id}`}
                        className="btn btn-ghost btn-sm" style={{ color: "var(--danger)" }}>
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AgentEditor({ agent, setAgent, busy, onSave, onCancel }) {
  const [models, setModels] = useState([]);
  const [tools, setTools] = useState([]);

  useEffect(() => {
    api.aihubModels().then((r) => setModels(r.models || []));
    api.aihubTools().then((r) => setTools(r.tools || []));
  }, []);

  const set = (k, v) => setAgent((p) => ({ ...p, [k]: v }));

  const addField = () => set("form_fields", [
    ...(agent.form_fields || []),
    { key: "", description: "", question: "", required: true },
  ]);
  const updField = (i, k, v) => {
    const next = [...(agent.form_fields || [])];
    next[i] = { ...next[i], [k]: v };
    set("form_fields", next);
  };
  const delField = (i) => set("form_fields",
    agent.form_fields.filter((_, idx) => idx !== i));

  const toggleTool = (id) => {
    const en = agent.tools_enabled || [];
    set("tools_enabled", en.includes(id) ? en.filter((t) => t !== id) : [...en, id]);
  };

  return (
    <div className="surface" style={{ padding: 22, borderRadius: 14 }}
         data-testid="aihub-agent-editor">
      <h3 style={{ margin: "0 0 16px", fontSize: 17, fontWeight: 700 }}>
        {agent.id ? `Editar agente: ${agent.name}` : "Novo agente IA"}
      </h3>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12 }}>
        <Field label="Nome">
          <input className="input" value={agent.name} onChange={(e) => set("name", e.target.value)}
                 data-testid="aihub-name-input" placeholder="Ex.: Jerusa Comercial" />
        </Field>
        <Field label="Descrição">
          <input className="input" value={agent.description || ""} onChange={(e) => set("description", e.target.value)}
                 placeholder="Atendente comercial principal" />
        </Field>
      </div>

      <Field label="Mensagem inicial">
        <input className="input" value={agent.initial_message || ""} onChange={(e) => set("initial_message", e.target.value)}
               placeholder="Olá, sou a Jerusa! Como posso ajudar?" />
      </Field>

      <Field label="System prompt (instruções para a IA)">
        <textarea className="input" value={agent.system_prompt}
                  onChange={(e) => set("system_prompt", e.target.value)}
                  data-testid="aihub-prompt-input"
                  rows={8} style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 12 }} />
      </Field>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 12 }}>
        <Field label="Modelo">
          <select className="input" value={`${agent.model_provider}/${agent.model_name}`}
                  data-testid="aihub-model-select"
                  onChange={(e) => {
                    const [p, m] = e.target.value.split("/");
                    set("model_provider", p);
                    set("model_name", m);
                  }}>
            {models.map((m) => (
              <option key={`${m.provider}/${m.model}`} value={`${m.provider}/${m.model}`}>
                {m.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label={`Temperatura: ${agent.temperature}`}>
          <input type="range" min="0" max="2" step="0.1" value={agent.temperature}
                 onChange={(e) => set("temperature", parseFloat(e.target.value))}
                 style={{ width: "100%" }} />
        </Field>
        <Field label="Max tokens">
          <input className="input" type="number" min="50" max="8000" value={agent.max_tokens}
                 onChange={(e) => set("max_tokens", parseInt(e.target.value, 10) || 700)} />
        </Field>
      </div>

      {/* Form fields */}
      <Field label="Formulário inteligente (campos a capturar durante a conversa)">
        <div style={{ display: "grid", gap: 8 }}>
          {(agent.form_fields || []).map((f, i) => (
            <div key={i} style={{
              padding: 10, border: "1px solid var(--border-default)", borderRadius: 8,
              display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 8,
            }}>
              <input className="input" placeholder="Chave (ex.: nome)"
                     value={f.key} onChange={(e) => updField(i, "key", e.target.value)} />
              <input className="input" placeholder="Descrição"
                     value={f.description} onChange={(e) => updField(i, "description", e.target.value)} />
              <input className="input" placeholder="Pergunta para o cliente"
                     value={f.question} onChange={(e) => updField(i, "question", e.target.value)} />
              <button onClick={() => delField(i)} className="btn btn-ghost btn-sm"
                      style={{ color: "var(--danger)" }}>
                <Trash2 size={13} />
              </button>
            </div>
          ))}
          <button onClick={addField} className="btn btn-secondary btn-sm" type="button"
                  data-testid="aihub-add-field-btn">
            <Plus size={13} /> Adicionar campo
          </button>
        </div>
      </Field>

      {/* Personalidade & Expertise — estilo Configurar Robô (PDF Ligo Fibra) */}
      <PersonalityExpertiseSection agent={agent} setAgent={setAgent} set={set} />

      {/* Tools */}
      <Field label="Ferramentas disponíveis ao agente">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8 }}>
          {tools.map((t) => {
            const enabled = agent.tools_enabled?.includes(t.id);
            return (
              <label key={t.id} style={{
                padding: 10, border: `1px solid ${enabled ? "var(--accent)" : "var(--border-default)"}`,
                borderRadius: 8, cursor: "pointer",
                background: enabled ? "var(--accent-soft)" : "var(--bg-surface)",
                display: "flex", alignItems: "flex-start", gap: 8,
              }}>
                <input type="checkbox" checked={!!enabled} onChange={() => toggleTool(t.id)}
                       data-testid={`aihub-tool-${t.id}`}
                       style={{ accentColor: "var(--accent)", marginTop: 2 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, fontWeight: 700 }}>{t.label}</div>
                  <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 2 }}>
                    {t.description}
                  </div>
                </div>
              </label>
            );
          })}
        </div>
      </Field>

      <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 12, alignItems: "end" }}>
        <Field label="Webhook URL (POST após conversa terminar) — opcional">
          <input className="input" value={agent.webhook_url || ""} onChange={(e) => set("webhook_url", e.target.value)}
                 placeholder="https://seu-crm.com/webhook" />
        </Field>
        <label style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px",
                          background: "var(--bg-surface-2)", borderRadius: 8 }}>
          <input type="checkbox" checked={agent.active} onChange={(e) => set("active", e.target.checked)}
                 style={{ accentColor: "var(--accent)" }} />
          <span style={{ fontSize: 13, fontWeight: 600 }}>Ativo</span>
        </label>
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 18, justifyContent: "flex-end" }}>
        <button className="btn btn-ghost" onClick={onCancel} data-testid="aihub-cancel-btn">
          <X size={14} /> Cancelar
        </button>
        <button className="btn btn-primary" onClick={onSave} disabled={busy}
                data-testid="aihub-save-btn">
          <Save size={14} /> {busy ? "Salvando…" : "Salvar agente"}
        </button>
      </div>
    </div>
  );
}

/* =============================================================
   Personalidade & Expertise (estilo PDF Ligo Fibra)
============================================================= */
function PersonalityExpertiseSection({ agent, setAgent, set }) {
  const [busyField, setBusyField] = useState(null);    // "company_info" | "pricing_info" | ...
  const [busyMode, setBusyMode] = useState(null);       // "aprimorar" | "gerar"
  const [genAllBusy, setGenAllBusy] = useState(false);
  const [genAllContext, setGenAllContext] = useState("");
  const [showGenAll, setShowGenAll] = useState(false);

  const callTextGen = async (field, mode, currentText, context) => {
    setBusyField(field); setBusyMode(mode);
    try {
      const r = await api.aihubAgentTextGen({
        field, mode, current_text: currentText || "", context: context || null,
      });
      set(field, r.text);
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusyField(null); setBusyMode(null); }
  };

  const generateAll = async () => {
    if (!genAllContext.trim() || genAllContext.length < 20) {
      alert("Descreva o negócio com pelo menos 20 caracteres."); return;
    }
    setGenAllBusy(true);
    try {
      // Gera 4 campos em paralelo — usa allSettled p/ não perder tudo se 1 falhar
      const fields = ["company_info", "pricing_info", "system_prompt", "priority_situations"];
      const results = await Promise.allSettled(fields.map((f) =>
        api.aihubAgentTextGen({ field: f, mode: "gerar", current_text: "", context: genAllContext })
      ));
      const next = { ...agent };
      const failed = [];
      results.forEach((r, i) => {
        if (r.status === "fulfilled") next[fields[i]] = r.value.text;
        else failed.push(fields[i]);
      });
      setAgent(next);
      if (failed.length === 4) {
        alert("Nenhum campo foi gerado — todos falharam. Tente novamente.");
      } else if (failed.length > 0) {
        alert(`${4 - failed.length} de 4 campos gerados. Falharam: ${failed.join(", ")}. Use "Gerar Novo" individual para tentar de novo.`);
        setShowGenAll(false); setGenAllContext("");
      } else {
        setShowGenAll(false); setGenAllContext("");
      }
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setGenAllBusy(false); }
  };

  const ActionBtn = ({ field, mode, label, Icon }) => {
    const active = busyField === field && busyMode === mode;
    const disabled = busyField !== null;
    return (
      <button onClick={() => callTextGen(field, mode, agent[field] || "")}
              disabled={disabled}
              data-testid={`aihub-${mode}-${field}`}
              className="btn btn-ghost btn-sm"
              style={{ fontSize: 11, padding: "4px 9px", gap: 4 }}>
        <Icon size={11} strokeWidth={2} />
        {active ? "..." : label}
      </button>
    );
  };

  const SectionHeader = ({ Icon, title, field }) => (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      marginBottom: 6, marginTop: 14,
    }}>
      <Icon size={14} strokeWidth={1.75} style={{ color: "var(--accent)" }} />
      <span style={{ fontSize: 13, fontWeight: 700, flex: 1 }}>{title}</span>
      <ActionBtn field={field} mode="aprimorar" label="Aprimorar" Icon={ArrowUp} />
      <ActionBtn field={field} mode="gerar" label="Gerar Novo" Icon={Plus} />
    </div>
  );

  return (
    <div data-testid="aihub-personality-section" style={{
      marginTop: 18, padding: 18, borderRadius: 14,
      border: "1px solid var(--border-default)",
      background: "var(--bg-surface-2)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <Sparkles size={18} strokeWidth={1.75} style={{ color: "var(--accent)" }} />
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 800 }}>
          Personalidade & Expertise
        </h3>
      </div>
      <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 14 }}>
        Configure a identidade, especialização e conhecimento específico do seu
        assistente inteligente.
      </div>

      {/* Gerador Inteligente de Prompts */}
      <div style={{
        padding: 12, borderRadius: 10,
        background: "linear-gradient(135deg, var(--accent-soft) 0%, var(--bg-surface) 100%)",
        border: "1px dashed var(--accent)",
        marginBottom: 14,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <Wand2 size={14} strokeWidth={1.75} style={{ color: "var(--accent)" }} />
          <strong style={{ fontSize: 13 }}>Gerador Inteligente de Prompts</strong>
        </div>
        <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 10 }}>
          Descreva seu negócio em uma frase e a IA gera os 4 campos abaixo
          (empresa, preços, prompt, situações).
        </div>
        {!showGenAll ? (
          <button onClick={() => setShowGenAll(true)}
                  className="btn btn-primary btn-sm"
                  data-testid="aihub-gen-all-btn">
            <Sparkles size={13} /> Gerar Prompt Completo
          </button>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            <textarea className="input" rows={3}
                      value={genAllContext}
                      onChange={(e) => setGenAllContext(e.target.value)}
                      data-testid="aihub-gen-all-context"
                      placeholder="Ex.: Provedor de internet Ligo Fibra no RJ, planos de 400MB a 1GB, atende residencial e comercial, foco em vendas e suporte técnico." />
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={generateAll} disabled={genAllBusy}
                      className="btn btn-primary btn-sm"
                      data-testid="aihub-gen-all-confirm">
                <Sparkles size={13} /> {genAllBusy ? "Gerando 4 campos..." : "Gerar"}
              </button>
              <button onClick={() => { setShowGenAll(false); setGenAllContext(""); }}
                      className="btn btn-ghost btn-sm" disabled={genAllBusy}>
                <X size={13} /> Cancelar
              </button>
            </div>
          </div>
        )}
      </div>

      <SectionHeader Icon={Building2} title="Informações da Empresa" field="company_info" />
      <textarea className="input" rows={5}
                value={agent.company_info || ""}
                onChange={(e) => set("company_info", e.target.value)}
                data-testid="aihub-input-company-info"
                placeholder="Nome fantasia, CNPJ, endereço, número Anatel/Fistel, áreas de cobertura..." />
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
        Informações básicas sobre sua empresa que a IA deve conhecer.
      </div>

      <SectionHeader Icon={DollarSign} title="Preços e Valores" field="pricing_info" />
      <textarea className="input" rows={5}
                value={agent.pricing_info || ""}
                onChange={(e) => set("pricing_info", e.target.value)}
                data-testid="aihub-input-pricing-info"
                placeholder="Lista dos planos disponíveis, valores mensais, condições..." />
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
        Tabela de preços e informações sobre produtos/serviços.
      </div>

      <SectionHeader Icon={Star} title="Situações Prioritárias" field="priority_situations" />
      <textarea className="input" rows={4}
                value={agent.priority_situations || ""}
                onChange={(e) => set("priority_situations", e.target.value)}
                data-testid="aihub-input-priority-situations"
                placeholder="Cenários de negócio que merecem atenção (ex.: ex-cliente querendo voltar)..." />
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
        Configure situações que merecem atenção prioritária da IA (não emergências, mas prioridades de negócio).
      </div>
    </div>
  );
}

/* =============================================================
   Playground
============================================================= */
function PlaygroundTab() {
  const [agents, setAgents] = useState([]);
  const [agentId, setAgentId] = useState("");
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.aihubAgentsList().then((r) => {
      setAgents(r.items || []);
      if (r.items?.length && !agentId) setAgentId(r.items[0].id);
    });
  }, []);

  const reset = () => {
    setSessionId(null);
    setMessages([]);
    const a = agents.find((x) => x.id === agentId);
    if (a?.initial_message) {
      setMessages([{ role: "assistant", content: a.initial_message }]);
    }
  };

  useEffect(() => { reset(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [agentId]);

  const send = async () => {
    if (!input.trim() || !agentId || busy) return;
    const userMsg = { role: "user", content: input.trim() };
    setMessages((m) => [...m, userMsg]);
    setInput("");
    setBusy(true);
    try {
      const r = await api.aihubPlayground(agentId, {
        session_id: sessionId, message: userMsg.content,
      });
      setSessionId(r.session_id);
      setMessages((m) => [...m, { role: "assistant", content: r.reply }]);
    } catch (e) {
      setMessages((m) => [...m, {
        role: "system",
        content: "Erro: " + (e?.response?.data?.detail || e.message),
      }]);
    } finally { setBusy(false); }
  };

  if (!agents.length) {
    return (
      <div className="surface" style={{ padding: 30, borderRadius: 14 }}>
        <EmptyState icon={Bot} title="Crie um agente primeiro"
          description="Vá na aba 'Agentes' e crie um agente para testar." />
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 12 }}>
      <div className="surface" style={{ padding: 14, borderRadius: 12, display: "flex", gap: 10, alignItems: "center" }}>
        <select value={agentId} onChange={(e) => setAgentId(e.target.value)}
                className="input" data-testid="aihub-pg-agent-select"
                style={{ flex: 1, maxWidth: 320 }}>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
        <button className="btn btn-ghost btn-sm" onClick={reset} data-testid="aihub-pg-reset">
          <RefreshCw size={13} /> Reiniciar conversa
        </button>
        {sessionId && (
          <span className="mono" style={{ fontSize: 11, color: "var(--text-muted)" }}>
            session: {sessionId.slice(-12)}
          </span>
        )}
      </div>

      <div className="surface" style={{ padding: 0, borderRadius: 12, overflow: "hidden",
                                         display: "flex", flexDirection: "column",
                                         height: "60vh", minHeight: 380 }}>
        <div style={{ flex: 1, overflowY: "auto", padding: 16, background: "var(--bg-surface-2)" }}
             data-testid="aihub-pg-messages">
          {messages.length === 0 && (
            <div style={{ textAlign: "center", color: "var(--text-muted)", fontSize: 13, padding: 20 }}>
              Envie uma mensagem para começar a conversa.
            </div>
          )}
          {messages.map((m, i) => (
            <ChatBubble key={i} role={m.role} content={m.content} />
          ))}
          {busy && <ChatBubble role="assistant" content="…" pending />}
        </div>
        <div style={{ padding: 12, borderTop: "1px solid var(--border-default)",
                       display: "flex", gap: 8, background: "var(--bg-surface)" }}>
          <input value={input} onChange={(e) => setInput(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), send())}
                 className="input" placeholder="Digite sua mensagem como cliente..."
                 data-testid="aihub-pg-input" disabled={busy} style={{ flex: 1 }} />
          <button onClick={send} className="btn btn-primary"
                  disabled={!input.trim() || busy} data-testid="aihub-pg-send">
            <Send size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}

function ChatBubble({ role, content, pending }) {
  const isUser = role === "user";
  const isSys = role === "system";
  return (
    <div style={{
      display: "flex", justifyContent: isUser ? "flex-end" : "flex-start",
      marginBottom: 8,
    }}>
      <div style={{
        maxWidth: "78%", padding: "8px 12px", borderRadius: 12,
        background: isUser ? "#0d9488" : isSys ? "var(--danger-soft)" : "var(--bg-surface)",
        color: isUser ? "#ffffff" : isSys ? "var(--danger-soft-fg)" : "var(--text-primary)",
        fontSize: 13, lineHeight: 1.5, whiteSpace: "pre-wrap",
        border: isUser ? "1px solid #0d9488" : (!isSys ? "1px solid var(--border-default)" : "none"),
        boxShadow: isUser ? "0 1px 4px rgba(13,148,136,0.25)" : "none",
        opacity: pending ? 0.7 : 1,
      }}>{content}</div>
    </div>
  );
}

/* =============================================================
   Discar (outbound call)
============================================================= */
function DialTab() {
  const [phone, setPhone] = useState("");
  const [contactName, setContactName] = useState("");
  const [agents, setAgents] = useState([]);
  const [agentId, setAgentId] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [recent, setRecent] = useState([]);

  const loadAgents = () => {
    api.aihubAgentsList().then((r) => {
      const active = (r.items || []).filter((a) => a.active);
      setAgents(active);
      if (active.length && !agentId) setAgentId(active[0].id);
    });
  };
  const loadRecent = () => {
    api.aihubCalls(20).then((r) => {
      const out = (r.items || []).filter((c) => c.direction === "outbound");
      setRecent(out);
    });
  };
  useEffect(() => { loadAgents(); loadRecent(); /* eslint-disable-next-line */ }, []);

  const fire = async () => {
    if (!phone || phone.length < 8) {
      setResult({ ok: false, msg: "Telefone inválido (mínimo 8 dígitos)." });
      return;
    }
    if (!agentId) {
      setResult({ ok: false, msg: "Selecione um agente IA." });
      return;
    }
    setBusy(true); setResult(null);
    try {
      const r = await api.aihubOutboundCall({
        agent_id: agentId,
        phone,
        contact_name: contactName || undefined,
        notes: notes || undefined,
      });
      setResult({ ok: true, msg: `Chamada iniciada — call_id ${r.call_id}` });
      setPhone(""); setContactName(""); setNotes("");
      loadRecent();
    } catch (e) {
      setResult({
        ok: false,
        msg: e?.response?.data?.detail || e.message || "Falha ao iniciar chamada",
      });
    } finally { setBusy(false); }
  };

  if (!agents.length) {
    return (
      <div className="surface" style={{ padding: 30, borderRadius: 14 }}>
        <EmptyState icon={Bot} title="Nenhum agente IA ativo"
          description="Crie e ative um agente IA na aba 'Agentes' para discar." />
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div className="surface" style={{ padding: 22, borderRadius: 14 }}>
        <h3 style={{ margin: "0 0 4px", fontSize: 16, fontWeight: 700 }}>
          Discar com IA
        </h3>
        <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 14 }}>
          Origina chamada via MagnusBilling vinculada a um agente IA. A IA
          inicia a conversa quando o cliente atender.
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Field label="Telefone do destinatário">
            <input className="input" value={phone}
                   onChange={(e) => setPhone(e.target.value)}
                   placeholder="Ex.: 11999998888 ou 5511999998888"
                   data-testid="aihub-dial-phone" />
          </Field>
          <Field label="Nome (opcional)">
            <input className="input" value={contactName}
                   onChange={(e) => setContactName(e.target.value)}
                   placeholder="Ex.: João Silva"
                   data-testid="aihub-dial-name" />
          </Field>
        </div>

        <Field label="Agente IA">
          <select className="input" value={agentId}
                  onChange={(e) => setAgentId(e.target.value)}
                  data-testid="aihub-dial-agent">
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} · {a.model_provider}/{a.model_name}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Observações da chamada (opcional)">
          <input className="input" value={notes}
                 onChange={(e) => setNotes(e.target.value)}
                 placeholder="Ex.: cobrança fatura 03/2026 / lembrete agendamento"
                 data-testid="aihub-dial-notes" />
        </Field>

        {result && (
          <div style={{
            marginTop: 12, padding: 10,
            background: result.ok ? "var(--success-soft)" : "var(--danger-soft)",
            color: result.ok ? "var(--success-soft-fg)" : "var(--danger-soft-fg)",
            borderRadius: 8, fontSize: 12, display: "flex", alignItems: "center", gap: 8,
          }}>
            {result.ok ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
            {result.msg}
          </div>
        )}

        <button onClick={fire} disabled={busy}
                data-testid="aihub-dial-fire"
                className="btn btn-primary"
                style={{ marginTop: 14, gap: 8 }}>
          <Phone size={14} />
          {busy ? "Iniciando…" : "Iniciar chamada"}
        </button>
      </div>

      <div className="surface" style={{ padding: 18, borderRadius: 12 }}>
        <h4 style={{ margin: "0 0 10px", fontSize: 14, fontWeight: 700 }}>
          Chamadas recentes (outbound)
        </h4>
        {recent.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--text-muted)", padding: 10 }}>
            Nenhuma chamada outbound ainda.
          </div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {recent.map((c) => (
              <div key={c.id} data-testid={`aihub-dial-recent-${c.id}`}
                   style={{
                     padding: 10, border: "1px solid var(--border-default)",
                     borderRadius: 8, display: "flex", justifyContent: "space-between",
                     alignItems: "center", gap: 10,
                   }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 13 }} className="mono">
                    {c.callee} {c.contact_name && `· ${c.contact_name}`}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    {c.started_at} · agente: {c.agent_name || "—"}
                    {c.notes && ` · ${c.notes}`}
                  </div>
                </div>
                <span className={`pill pill--${c.status === "originated" ? "success" : c.status === "failed" ? "danger" : "neutral"}`}>
                  {c.status}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* =============================================================
   WhatsApp Cloud
============================================================= */
function WhatsappCloudTab() {
  return <IntegrationCard
    type="whatsapp_cloud"
    title="WhatsApp Cloud API (Meta)"
    description="Configure credenciais oficiais do WhatsApp Business Platform. O webhook receiver já está pronto em /api/aihub/webhooks/call-event."
    fields={[
      { key: "phone_number_id", label: "Phone Number ID", placeholder: "Ex.: 1234567890", type: "text" },
      { key: "access_token", label: "Access Token", placeholder: "EAAxxxxxxxxxxxx", type: "password" },
      { key: "verify_token", label: "Verify Token (escolha um)", placeholder: "string aleatória sua", type: "password" },
      { key: "graph_version", label: "Graph API version", placeholder: "v23.0", type: "text" },
    ]}
    testApi={api.aihubWhatsappTest}
    extraSection={<WhatsappWebhookHint />}
  />;
}

function WhatsappWebhookHint() {
  const base = process.env.REACT_APP_BACKEND_URL?.replace(/\/$/, "") || "";
  const webhookUrl = `${base}/api/aihub/webhooks/call-event`;
  return (
    <div style={{
      marginTop: 14, padding: 12, background: "var(--info-soft)",
      color: "var(--info-soft-fg)", borderRadius: 10, fontSize: 12,
    }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>📌 Webhook URL para colar no Meta:</div>
      <code className="mono" style={{ fontSize: 11 }}>{webhookUrl}</code>
    </div>
  );
}

/* =============================================================
   Histórico
============================================================= */
function HistoryTab() {
  const [calls, setCalls] = useState([]);
  const [dash, setDash] = useState(null);

  useEffect(() => {
    api.aihubCalls(100).then((r) => setCalls(r.items || []));
    api.aihubDashboard().then(setDash);
  }, []);

  return (
    <div style={{ display: "grid", gap: 14 }}>
      {dash && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
          <Stat label="Agentes" value={`${dash.agents?.active || 0} / ${dash.agents?.total || 0}`} subtitle="Ativos / Total" />
          <Stat label="Sessões testadas" value={dash.sessions?.total || 0} />
          <Stat label="Chamadas" value={dash.calls?.total || 0} />
          <Stat label="MagnusBilling" value={dash.integrations?.magnusbilling || "—"}
                color={dash.integrations?.magnusbilling === "online" ? "success" : "neutral"} />
          <Stat label="WhatsApp Cloud" value={dash.integrations?.whatsapp_cloud || "—"}
                color={dash.integrations?.whatsapp_cloud === "online" ? "success" : "neutral"} />
        </div>
      )}

      <div className="surface" style={{ padding: 16, borderRadius: 12 }}>
        <h3 style={{ margin: "0 0 10px", fontSize: 15, fontWeight: 700 }}>Chamadas recebidas via webhook</h3>
        {calls.length === 0 ? (
          <EmptyState icon={Phone} title="Nenhuma chamada ainda"
            description="Configure o webhook no MagnusBilling/AGI apontando para /api/aihub/webhooks/call-event para começar a registrar." />
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {calls.map((c) => (
              <div key={c.id} style={{
                padding: 12, border: "1px solid var(--border-default)",
                borderRadius: 10, background: "var(--bg-surface)",
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                  <span style={{ fontWeight: 700, fontSize: 13 }} className="mono">
                    {c.caller || "—"} → {c.callee || "—"}
                  </span>
                  <span className={`pill pill--${c.status === "answered" ? "success" : "neutral"}`}>
                    {c.status || "—"}
                  </span>
                </div>
                <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                  {c.started_at} {c.duration_sec && `· ${c.duration_sec}s`}
                </div>
                {c.summary && (
                  <div style={{ fontSize: 12, marginTop: 6, color: "var(--text-primary)" }}>
                    {c.summary}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* =============================================================
   Reusable
============================================================= */
function IntegrationCard({ type, title, description, fields, testApi, extraSection }) {
  const [config, setConfig] = useState({});
  const [meta, setMeta] = useState(null);
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const load = async () => {
    const r = await api.aihubIntegrations();
    const it = (r.items || []).find((x) => x.type === type);
    if (it) {
      setConfig(it.config || {});
      setMeta({ status: it.status, last_test_at: it.last_test_at, error: it.last_test_error });
    } else {
      setConfig({});
      setMeta(null);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [type]);

  const save = async () => {
    setBusy(true);
    try {
      await api.aihubIntegrationSave(type, config);
      await load();
      setTestResult({ ok: true, msg: "Configuração salva." });
    } catch (e) {
      setTestResult({ ok: false, msg: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  const test = async () => {
    setBusy(true);
    try {
      const r = await testApi();
      setTestResult({ ok: r.ok, msg: r.ok ? "Conectividade OK!" : (r.error || "Erro desconhecido") });
      await load();
    } catch (e) {
      setTestResult({ ok: false, msg: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  const remove = async () => {
    if (!window.confirm("Remover configuração?")) return;
    await api.aihubIntegrationDelete(type);
    setConfig({}); setMeta(null); setTestResult(null);
  };

  return (
    <div className="surface" style={{ padding: 22, borderRadius: 14 }}
         data-testid={`aihub-int-${type}`}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
        <div style={{ flex: 1 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>{title}</h3>
          <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 4 }}>
            {description}
          </div>
        </div>
        {meta?.status && (
          <span className={`pill pill--${meta.status === "online" ? "success" : meta.status === "error" ? "danger" : "neutral"}`}
                style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            {meta.status === "online" ? <Wifi size={12} /> : <WifiOff size={12} />}
            {meta.status}
          </span>
        )}
      </div>

      <div style={{ display: "grid", gap: 10 }}>
        {fields.map((f) => (
          <Field key={f.key} label={f.label}>
            <input type={f.type || "text"} className="input"
                   value={config[f.key] || ""}
                   onChange={(e) => setConfig({ ...config, [f.key]: e.target.value })}
                   placeholder={f.placeholder}
                   data-testid={`aihub-int-${type}-${f.key}`} />
          </Field>
        ))}
      </div>

      {testResult && (
        <div style={{
          marginTop: 12, padding: 10,
          background: testResult.ok ? "var(--success-soft)" : "var(--danger-soft)",
          color: testResult.ok ? "var(--success-soft-fg)" : "var(--danger-soft-fg)",
          borderRadius: 8, fontSize: 12, display: "flex", alignItems: "center", gap: 8,
        }}>
          {testResult.ok ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
          {testResult.msg}
        </div>
      )}

      {meta?.last_test_at && (
        <div style={{ marginTop: 8, fontSize: 11, color: "var(--text-muted)" }}>
          Último teste: {meta.last_test_at}
          {meta.error && <span style={{ color: "var(--danger)" }}> · {meta.error}</span>}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <button className="btn btn-primary" onClick={save} disabled={busy}
                data-testid={`aihub-int-${type}-save`}>
          <Save size={14} /> {busy ? "Salvando…" : "Salvar"}
        </button>
        <button className="btn btn-secondary" onClick={test} disabled={busy}
                data-testid={`aihub-int-${type}-test`}>
          <Play size={14} /> Testar conexão
        </button>
        {meta && (
          <button className="btn btn-ghost" onClick={remove} disabled={busy}
                  style={{ color: "var(--danger)", marginLeft: "auto" }}>
            <Trash2 size={13} /> Remover
          </button>
        )}
      </div>

      {extraSection}
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label style={{ display: "block", marginTop: 10 }}>
      <div style={{
        fontSize: 11, fontWeight: 700, color: "var(--text-secondary)",
        textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4,
      }}>{label}</div>
      {children}
    </label>
  );
}

function Stat({ label, value, subtitle, color }) {
  return (
    <div className="surface" style={{ padding: 14, borderRadius: 10 }}>
      <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700 }}>
        {label}
      </div>
      <div style={{
        fontSize: 22, fontWeight: 800, marginTop: 4,
        color: color === "success" ? "var(--success)" : "var(--text-primary)",
      }}>{value}</div>
      {subtitle && <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{subtitle}</div>}
    </div>
  );
}

function EmptyState({ icon: Icon, title, description }) {
  return (
    <div style={{
      padding: 30, textAlign: "center", color: "var(--text-secondary)",
      display: "flex", flexDirection: "column", alignItems: "center", gap: 8,
    }}>
      <Icon size={36} strokeWidth={1.25} style={{ opacity: 0.5 }} />
      <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)" }}>{title}</div>
      <div style={{ fontSize: 12 }}>{description}</div>
    </div>
  );
}

const preStyle = {
  padding: 12, background: "var(--bg-surface-2)", borderRadius: 8,
  fontSize: 11, fontFamily: "var(--font-mono, monospace)",
  maxHeight: 300, overflow: "auto", margin: 0,
};
