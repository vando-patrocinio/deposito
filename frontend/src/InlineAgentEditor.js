import React, { useCallback, useEffect, useState } from "react";
import {
  Brain, Sparkles, Save, Loader2, ChevronDown, CheckCircle2,
  AlertTriangle, Bot,
} from "lucide-react";
import { api } from "@/api";
import {
  PersonalitySection, ModelSection, BLANK_AGENT, extractErrorMessage,
} from "@/AgentConfigModal";

/* =============================================================
   Editor inline de Agente IA — embed na aba Atendimento IA →
   Configuração. Replica somente as 2 seções principais do popup
   "Configurar Robô": Personalidade & Expertise + Modelo de IA.
   Para tools/auto-reply/canal, o usuário abre o popup completo.
============================================================= */

const TABS = [
  { id: "personality", label: "Personalidade & Expertise", icon: Brain,
    color: "#8b5cf6" },
  { id: "model",       label: "Modelo de IA",              icon: Sparkles,
    color: "#0ea5e9" },
];

export default function InlineAgentEditor() {
  const [agents, setAgents] = useState([]);
  const [models, setModels] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [draft, setDraft] = useState(BLANK_AGENT);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("personality");
  const [flash, setFlash] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [a, m] = await Promise.all([
        api.aihubAgentsList(),
        api.aihubModels().catch(() => ({ models: [] })),
      ]);
      setAgents(a.items || []);
      setModels(m.models || []);
      setAuthError(false);
    } catch (e) {
      const status = e?.response?.status;
      if (status === 401 || status === 403) {
        // Sessão expirou — NÃO mostre "Nenhum agente cadastrado"
        // (assusta o usuário fazendo pensar que perdeu os dados).
        // Mostra mensagem clara de reauth.
        setAuthError(true);
      } else {
        setError(extractErrorMessage(e));
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  // Auto-seleciona o primeiro agente quando a lista carrega
  useEffect(() => {
    if (agents.length > 0 && !selectedId) {
      pickAgent(agents[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents]);

  function pickAgent(a) {
    setSelectedId(a.id);
    setDraft({
      name: a.name || "",
      description: a.description || "",
      initial_message: a.initial_message || "",
      system_prompt: a.system_prompt || "",
      model_provider: a.model_provider || "gemini",
      model_name: a.model_name || "gemini-2.5-flash",
      temperature: a.temperature ?? 0.6,
      max_tokens: a.max_tokens ?? 700,
      form_fields: a.form_fields || [],
      tools_enabled: a.tools_enabled || [],
      active: a.active !== false,
      company_info: a.company_info || "",
      pricing_info: a.pricing_info || "",
      priority_situations: a.priority_situations || "",
      routing_intent: a.routing_intent || "",
    });
    setDirty(false);
    setError("");
  }

  function patch(field, value) {
    setDraft((d) => ({ ...d, [field]: value }));
    setDirty(true);
  }

  async function save() {
    if (!draft.name.trim()) {
      setError("Nome do agente é obrigatório.");
      return;
    }
    if (!draft.system_prompt || draft.system_prompt.length < 10) {
      setError("Parâmetros (system_prompt) precisam de pelo menos 10 caracteres.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const saved = selectedId
        ? await api.aihubAgentUpdate(selectedId, draft)
        : await api.aihubAgentCreate(draft);
      setFlash(`Agente "${saved.name}" salvo com sucesso.`);
      setDirty(false);
      setSelectedId(saved.id);
      await reload();
      setTimeout(() => setFlash(""), 3500);
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="inline-agent-editor" style={{
      background: "var(--bg-surface)",
      border: "1px solid var(--border-default)",
      borderRadius: 14,
      overflow: "hidden",
    }}>
      {/* ---------- Header com seletor de agente + tabs + save ---------- */}
      <div style={{
        display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
        padding: "14px 18px",
        borderBottom: "1px solid var(--border-default)",
        background: "linear-gradient(135deg, rgba(139,92,246,.06), transparent 60%)",
      }}>
        <div style={{
          width: 40, height: 40, borderRadius: 11,
          background: "linear-gradient(135deg, #8b5cf6, #6366f1)",
          color: "white", display: "grid", placeItems: "center",
          boxShadow: "0 4px 14px rgba(139,92,246,.28)",
        }}>
          <Bot size={20} strokeWidth={1.75} />
        </div>
        <div style={{ flex: 1, minWidth: 200 }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 800,
                          letterSpacing: "-0.012em", color: "var(--text-primary)" }}>
            Agente IA · Personalidade & Modelo
          </h3>
          <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 1 }}>
            Edite identidade, expertise e modelo do robô — alterações afetam o WhatsApp em tempo real.
          </div>
        </div>

        {/* Seletor de agente — caixa estilo dropdown nativo se existir 2+ */}
        {agents.length > 1 && (
          <div style={{ position: "relative" }}>
            <select data-testid="inline-agent-selector"
                    value={selectedId || ""}
                    onChange={(e) => {
                      const ag = agents.find((x) => x.id === e.target.value);
                      if (ag) pickAgent(ag);
                    }}
                    style={{
                      appearance: "none",
                      padding: "8px 34px 8px 12px",
                      borderRadius: 9,
                      border: "1px solid var(--border-default)",
                      background: "var(--bg-surface-2)",
                      fontSize: 12, fontWeight: 700,
                      color: "var(--text-primary)",
                      cursor: "pointer",
                    }}>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
            <ChevronDown size={13}
                          style={{ position: "absolute", right: 10, top: "50%",
                                     transform: "translateY(-50%)", pointerEvents: "none",
                                     color: "var(--text-muted)" }} />
          </div>
        )}

        <button onClick={save} disabled={busy || !dirty}
                data-testid="inline-agent-save"
                style={{
                  padding: "9px 18px",
                  borderRadius: 9,
                  border: "none",
                  background: dirty ? "#16a34a" : "var(--bg-surface-2)",
                  color: dirty ? "white" : "var(--text-muted)",
                  fontSize: 12, fontWeight: 800,
                  cursor: (busy || !dirty) ? "not-allowed" : "pointer",
                  display: "inline-flex", alignItems: "center", gap: 6,
                  boxShadow: dirty ? "0 4px 14px rgba(22,163,74,.25)" : "none",
                  transition: "all .15s",
                }}>
          {busy
            ? <Loader2 size={13} className="spin" />
            : <Save size={13} />}
          {busy ? "Salvando…" : dirty ? "Salvar alterações" : "Sem alterações"}
        </button>
      </div>

      {/* ---------- Banner flash/erro ---------- */}
      {flash && (
        <div data-testid="inline-agent-flash" style={{
          padding: "10px 18px",
          background: "rgba(22,163,74,.10)",
          color: "#15803d",
          fontSize: 12.5, fontWeight: 700,
          borderBottom: "1px solid rgba(22,163,74,.25)",
          display: "flex", alignItems: "center", gap: 8,
        }}>
          <CheckCircle2 size={14} /> {flash}
        </div>
      )}
      {error && (
        <div data-testid="inline-agent-error" style={{
          padding: "10px 18px",
          background: "rgba(220,38,38,.08)",
          color: "#b91c1c",
          fontSize: 12.5, fontWeight: 600,
          borderBottom: "1px solid rgba(220,38,38,.25)",
          display: "flex", alignItems: "flex-start", gap: 8,
        }}>
          <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{error}</span>
        </div>
      )}

      {/* ---------- Tabs ---------- */}
      <div style={{
        display: "flex", gap: 4, padding: "10px 14px 0",
        borderBottom: "1px solid var(--border-default)",
        background: "var(--bg-surface-2)",
      }}>
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = tab === t.id;
          return (
            <button key={t.id} onClick={() => setTab(t.id)}
                    data-testid={`inline-agent-tab-${t.id}`}
                    style={{
                      padding: "8px 14px",
                      border: "none",
                      background: active ? "var(--bg-surface)" : "transparent",
                      color: active ? t.color : "var(--text-muted)",
                      fontSize: 12.5, fontWeight: 800,
                      cursor: "pointer",
                      borderBottom: active
                        ? `2px solid ${t.color}`
                        : "2px solid transparent",
                      marginBottom: -1,
                      borderRadius: "8px 8px 0 0",
                      display: "inline-flex", alignItems: "center", gap: 7,
                      transition: "all .15s",
                    }}>
              <Icon size={13} /> {t.label}
            </button>
          );
        })}
      </div>

      {/* ---------- Conteúdo da tab selecionada ---------- */}
      <div style={{ padding: "18px 18px 22px" }}>
        {loading ? (
          <div style={{ padding: 30, textAlign: "center",
                          color: "var(--text-muted)", fontSize: 12 }}
               data-testid="inline-agent-loading">
            <Loader2 size={20} className="spin" />
            <div style={{ marginTop: 8 }}>Carregando agentes…</div>
          </div>
        ) : authError ? (
          <div style={{ padding: 30, textAlign: "center" }}
               data-testid="inline-agent-auth-error">
            <AlertTriangle size={28}
                            style={{ color: "#f59e0b", margin: "0 auto" }} />
            <p style={{ marginTop: 10, fontSize: 13.5, color: "var(--text-primary)",
                          fontWeight: 600 }}>
              Sessão expirada
            </p>
            <p style={{ fontSize: 12, color: "var(--text-muted)",
                          marginTop: 4, maxWidth: 380, margin: "4px auto 0",
                          lineHeight: 1.5 }}>
              Seu agente <strong>NÃO foi apagado</strong> — está seguro no banco.
              Faça login novamente para continuar editando.
            </p>
            <button onClick={() => {
              try { localStorage.removeItem("ponto_token"); } catch { /* ignore */ }
              window.location.reload();
            }}
                    data-testid="inline-agent-relogin-btn"
                    style={{
                      marginTop: 12,
                      padding: "8px 16px", borderRadius: 8,
                      background: "#0f172a", color: "white",
                      border: "none", fontSize: 12, fontWeight: 700,
                      cursor: "pointer",
                    }}>
              Fazer login
            </button>
          </div>
        ) : agents.length === 0 ? (
          <div style={{ padding: 30, textAlign: "center" }}
               data-testid="inline-agent-empty">
            <Bot size={30} style={{ color: "var(--text-muted)", margin: "0 auto" }} />
            <p style={{ marginTop: 10, fontSize: 13, color: "var(--text-secondary)" }}>
              Nenhum agente cadastrado ainda.
            </p>
            <button onClick={() => {
              setSelectedId(null);
              setDraft({ ...BLANK_AGENT });
              setDirty(true);
            }}
                    data-testid="inline-agent-create-new"
                    style={{
                      marginTop: 10,
                      padding: "8px 14px", borderRadius: 8,
                      background: "#8b5cf6", color: "white",
                      border: "none", fontSize: 12, fontWeight: 700,
                      cursor: "pointer",
                    }}>
              + Criar agente
            </button>
          </div>
        ) : tab === "personality" ? (
          <PersonalitySection draft={draft} patch={patch} />
        ) : (
          <ModelSection draft={draft} patch={patch} models={models} />
        )}
      </div>
    </div>
  );
}
