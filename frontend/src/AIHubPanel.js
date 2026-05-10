import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import {
  Bot, MessageCircle, Phone, Send, Settings, History,
  Plus, Trash2, Edit2, Play, Save, X, RefreshCw, CheckCircle2,
  AlertTriangle, Wifi, WifiOff, PhoneCall,
} from "lucide-react";

const TABS = [
  { id: "agents", label: "Agentes", icon: Bot },
  { id: "playground", label: "Playground", icon: MessageCircle },
  { id: "dial", label: "Discar", icon: PhoneCall },
  { id: "magnus", label: "MagnusBilling", icon: Phone },
  { id: "whatsapp", label: "WhatsApp Cloud", icon: Send },
  { id: "history", label: "Histórico", icon: History },
];

export default function AIHubPanel() {
  const [tab, setTab] = useState("agents");

  return (
    <div data-testid="aihub-panel" style={{ padding: "0 4px" }}>
      <div style={{ marginBottom: 14 }}>
        <h1 className="page-title" style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Bot size={24} strokeWidth={1.75} /> Atendimento IA
        </h1>
        <p style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 4 }}>
          Agentes conversacionais usando IA local. Integre com MagnusBilling (SIP)
          e WhatsApp Cloud API para atendimento automatizado por voz e texto.
        </p>
      </div>

      <div style={{
        display: "flex", gap: 4, padding: 4, background: "var(--bg-surface-2)",
        borderRadius: 12, marginBottom: 16, overflowX: "auto", flexWrap: "wrap",
      }}>
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = tab === t.id;
          return (
            <button key={t.id} onClick={() => setTab(t.id)}
                    data-testid={`aihub-tab-${t.id}`}
                    style={{
                      padding: "8px 14px", border: "none", borderRadius: 8,
                      background: active ? "var(--bg-surface)" : "transparent",
                      color: active ? "var(--text-primary)" : "var(--text-secondary)",
                      fontWeight: active ? 700 : 500, fontSize: 13, cursor: "pointer",
                      display: "inline-flex", alignItems: "center", gap: 6,
                      whiteSpace: "nowrap",
                      boxShadow: active ? "var(--shadow-sm)" : "none",
                    }}>
              <Icon size={14} /> {t.label}
            </button>
          );
        })}
      </div>

      {tab === "agents" && <AgentsTab />}
      {tab === "playground" && <PlaygroundTab />}
      {tab === "dial" && <DialTab />}
      {tab === "magnus" && <MagnusBillingTab />}
      {tab === "whatsapp" && <WhatsappCloudTab />}
      {tab === "history" && <HistoryTab />}
    </div>
  );
}

/* =============================================================
   Agents
============================================================= */
function AgentsTab() {
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
        <EmptyState icon={PhoneCall} title="Nenhum agente IA ativo"
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
          <PhoneCall size={14} />
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
   MagnusBilling
============================================================= */
function MagnusBillingTab() {
  return <IntegrationCard
    type="magnusbilling"
    title="MagnusBilling (SIP/Asterisk)"
    description="Conecte sua instância MagnusBilling para listar DIDs, CDRs e originar chamadas a partir do PontoIA."
    fields={[
      { key: "url", label: "URL da instância", placeholder: "https://sip.tudovoip.com.br/mbilling", type: "text" },
      { key: "key", label: "Key", placeholder: "API Key do MagnusBilling", type: "password" },
      { key: "secret", label: "Secret", placeholder: "API Secret", type: "password" },
    ]}
    testApi={api.aihubMagnusTest}
    extraSection={<MagnusExtras />}
  />;
}

function MagnusExtras() {
  const [dids, setDids] = useState(null);
  const [cdr, setCdr] = useState(null);
  const [busy, setBusy] = useState(null);

  const loadDids = async () => {
    setBusy("dids");
    try { setDids(await api.aihubMagnusDids()); }
    catch (e) { setDids({ error: e?.response?.data?.detail || e.message }); }
    finally { setBusy(null); }
  };
  const loadCdr = async () => {
    setBusy("cdr");
    try { setCdr(await api.aihubMagnusCdr(50)); }
    catch (e) { setCdr({ error: e?.response?.data?.detail || e.message }); }
    finally { setBusy(null); }
  };

  return (
    <div style={{ marginTop: 18, display: "grid", gap: 12 }}>
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn btn-secondary btn-sm" onClick={loadDids} disabled={busy === "dids"}
                data-testid="aihub-mb-load-dids">
          <Phone size={13} /> {busy === "dids" ? "Carregando…" : "Listar DIDs"}
        </button>
        <button className="btn btn-secondary btn-sm" onClick={loadCdr} disabled={busy === "cdr"}
                data-testid="aihub-mb-load-cdr">
          <History size={13} /> {busy === "cdr" ? "Carregando…" : "Últimas chamadas (CDR)"}
        </button>
      </div>
      {dids && (
        <pre style={preStyle} data-testid="aihub-mb-dids-output">
          {JSON.stringify(dids, null, 2).slice(0, 3000)}
        </pre>
      )}
      {cdr && (
        <pre style={preStyle} data-testid="aihub-mb-cdr-output">
          {JSON.stringify(cdr, null, 2).slice(0, 3000)}
        </pre>
      )}
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
