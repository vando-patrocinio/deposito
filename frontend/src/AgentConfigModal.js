import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  X, Bot, Brain, FileText, Plug, Mic, Sparkles, Save, RotateCcw, Play,
  ChevronRight, Plus, Trash2, Star, Building2, DollarSign, User,
  Settings, Smartphone, Loader2, CheckCircle2, AlertTriangle, RefreshCw,
  LogOut, Wand2, ArrowUpCircle, Copy, Power,
} from "lucide-react";
import { api } from "@/api";

/* =============================================================
   AgentConfigModal — Popup "Configurar Robô" estilo Ligo Fibra.

   Estrutura (espelha o PDF):
   - Coluna esquerda: lista de agentes (selecionar, criar, excluir) +
     atalhos para Conectar WhatsApp.
   - Conteúdo principal: 5 seções (nav top-bar):
     1. Personalidade & Expertise  (nome, info, preços, parâmetros, prioridades)
     2. Modelo de IA               (provider, model, temperature, max_tokens)
     3. Conectar WhatsApp          (QR, status, logout)
     4. Tools                      (checkboxes)
     5. Auto-reply                 (toggle global + escolha do agente ativo)
============================================================= */

const SECTIONS = [
  { id: "personality", label: "Personalidade & Expertise", icon: Brain },
  { id: "model",       label: "Modelo de IA",              icon: Sparkles },
  { id: "whatsapp",    label: "Conectar WhatsApp",         icon: Smartphone },
  { id: "tools",       label: "Tools",                     icon: Plug },
  { id: "autoreply",   label: "Auto-reply / Ativação",     icon: Power },
];

/**
 * Extrai uma mensagem legível de um erro Axios/Fetch/runtime.
 * Lida com 3 formatos comuns:
 *  - string simples: "Não autorizado"
 *  - 422 Pydantic: array de {type, loc, msg, input, ctx, url}
 *  - objeto solto: {detail: "..."} ou {msg: "..."} ou {error: "..."}
 * NUNCA retorna objeto — sempre string segura para JSX.
 */
function extractErrorMessage(e) {
  const detail = e?.response?.data?.detail ?? e?.response?.data ?? e?.message;
  if (!detail) return "Erro desconhecido.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // Pydantic validation errors
    return detail.map((d) => {
      if (typeof d === "string") return d;
      const loc = Array.isArray(d?.loc) ? d.loc.filter((x) => x !== "body").join(".") : "";
      const msg = d?.msg || d?.message || JSON.stringify(d);
      return loc ? `${loc}: ${msg}` : msg;
    }).filter(Boolean).join(" · ");
  }
  if (typeof detail === "object") {
    return detail.msg || detail.message || detail.error || detail.detail || JSON.stringify(detail);
  }
  return String(detail);
}

const BLANK_AGENT = {
  name: "",
  description: "",
  initial_message: "Olá! Como posso te ajudar hoje? 😊",
  system_prompt: "Você é uma assistente virtual cordial e objetiva. Use português do Brasil, no máximo 4 frases curtas, com emojis sutis quando fizer sentido.",
  model_provider: "gemini",
  model_name: "gemini-2.5-flash",
  temperature: 0.6,
  max_tokens: 700,
  form_fields: [],
  tools_enabled: [],
  active: true,
  company_info: "",
  pricing_info: "",
  priority_situations: "",
  routing_intent: "",
};

export default function AgentConfigModal({ open, onClose }) {
  const [agents, setAgents] = useState([]);
  const [models, setModels] = useState([]);
  const [tools, setTools] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [draft, setDraft] = useState(BLANK_AGENT);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [section, setSection] = useState("personality");
  const [flash, setFlash] = useState("");
  const [error, setError] = useState("");
  const [autoReply, setAutoReply] = useState({ enabled: false, agent_name: "" });
  const [creatingNew, setCreatingNew] = useState(false);

  const isNew = !selectedId;

  const reload = useCallback(async () => {
    try {
      const [a, m, t, ar] = await Promise.all([
        api.aihubAgentsList(),
        api.aihubModels().catch(() => ({ models: [] })),
        api.aihubTools().catch(() => ({ tools: [] })),
        api.waBaileysGetAutoReply().catch(() => ({ enabled: false, agent_name: "" })),
      ]);
      setAgents(a.items || []);
      setModels(m.models || []);
      setTools(t.tools || []);
      setAutoReply({ enabled: !!ar.enabled, agent_name: ar.agent_name || "" });
    } catch (e) {
      setError(extractErrorMessage(e));
    }
  }, []);

  useEffect(() => {
    if (open) {
      reload();
      setSection("personality");
      setError("");
      setFlash("");
    }
  }, [open, reload]);

  /* Quando a lista chega, seleciona o primeiro agente (ou abre form novo). */
  useEffect(() => {
    if (!open) return;
    if (agents.length > 0 && !selectedId && !creatingNew) {
      pickAgent(agents[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents, open]);

  function pickAgent(a) {
    setCreatingNew(false);
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
  }

  function startNew() {
    setCreatingNew(true);
    setSelectedId(null);
    setDraft({ ...BLANK_AGENT, name: "" });
    setDirty(true);
    setSection("personality");
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
      let saved;
      if (isNew) {
        saved = await api.aihubAgentCreate(draft);
      } else {
        saved = await api.aihubAgentUpdate(selectedId, draft);
      }
      setFlash(`✅ ${saved.name} salvo com sucesso.`);
      setDirty(false);
      setCreatingNew(false);
      setSelectedId(saved.id);
      await reload();
      setTimeout(() => setFlash(""), 3500);
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!selectedId) return;
    if (!window.confirm(`Excluir agente "${draft.name}"? Esta ação não pode ser desfeita.`)) return;
    setBusy(true);
    try {
      await api.aihubAgentDelete(selectedId);
      setSelectedId(null);
      setDraft(BLANK_AGENT);
      await reload();
      setFlash("✅ Agente excluído.");
      setTimeout(() => setFlash(""), 3000);
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function clone() {
    if (!selectedId) return;
    setBusy(true);
    try {
      const cloned = await api.aihubAgentCreate({
        ...draft, name: `${draft.name} (cópia)`,
      });
      await reload();
      setSelectedId(cloned.id);
      setDirty(false);
      setFlash(`✅ Agente clonado: ${cloned.name}`);
      setTimeout(() => setFlash(""), 3000);
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function toggleAutoReply() {
    setBusy(true);
    try {
      const target = !autoReply.enabled;
      const agentName = draft.name || autoReply.agent_name || "Jerusa";
      await api.waBaileysSetAutoReply(target, agentName);
      setAutoReply({ enabled: target, agent_name: agentName });
      setFlash(target ? "✅ Auto-reply ATIVADO" : "✅ Auto-reply DESLIGADO");
      setTimeout(() => setFlash(""), 3000);
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;

  return (
    <div data-testid="agent-config-modal" onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,.6)",
      display: "grid", placeItems: "center", zIndex: 9999, padding: 16,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "var(--bg-surface)",
        borderRadius: 16, overflow: "hidden",
        width: "min(1280px, 96vw)", height: "min(820px, 92vh)",
        display: "grid", gridTemplateRows: "auto 1fr auto",
        boxShadow: "0 24px 80px rgba(0,0,0,.4)",
      }}>
        {/* Header */}
        <header style={{
          padding: "14px 22px", borderBottom: "1px solid var(--border-default)",
          background: "linear-gradient(135deg, #7c3aed12, var(--bg-surface) 70%)",
          display: "flex", alignItems: "center", gap: 12,
        }}>
          <div style={{
            width: 38, height: 38, borderRadius: 10,
            background: "linear-gradient(135deg, #7c3aed, #6366f1)", color: "white",
            display: "grid", placeItems: "center",
          }}><Bot size={20} strokeWidth={1.75} /></div>
          <div style={{ flex: 1 }}>
            <h2 style={{ margin: 0, fontSize: 17, fontWeight: 800, letterSpacing: "-0.02em" }}>
              Configurar Robô
            </h2>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
              Personalidade · Modelo · WhatsApp · Auto-reply · Múltiplos agentes
            </div>
          </div>
          {flash && (
            <span data-testid="agent-config-flash" style={{
              padding: "5px 12px", borderRadius: 8,
              background: "#dcfce7", color: "#166534",
              fontSize: 12, fontWeight: 700,
            }}>{flash}</span>
          )}
          <button data-testid="agent-config-close" onClick={onClose} style={{
            padding: 6, borderRadius: 8, border: "1px solid var(--border-default)",
            background: "var(--bg-surface)", cursor: "pointer", color: "var(--text-secondary)",
          }}><X size={18} /></button>
        </header>

        {/* Body */}
        <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", minHeight: 0 }}>
          {/* Sidebar lista de agentes */}
          <aside style={{
            borderRight: "1px solid var(--border-default)",
            background: "var(--bg-surface-2)",
            display: "flex", flexDirection: "column",
          }}>
            <div style={{ padding: "12px 14px 8px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ fontSize: 11, fontWeight: 800, color: "var(--text-muted)", letterSpacing: ".06em" }}>
                AGENTES ({agents.length})
              </div>
              <button onClick={startNew}
                      data-testid="agent-config-new-btn"
                      style={{
                        padding: "4px 10px", borderRadius: 6, border: "1px solid #7c3aed",
                        background: "#7c3aed", color: "white",
                        fontSize: 11, fontWeight: 800, cursor: "pointer",
                        display: "inline-flex", alignItems: "center", gap: 4,
                      }}>
                <Plus size={11} /> Novo
              </button>
            </div>
            <div style={{ flex: 1, overflow: "auto", padding: "0 6px 12px" }}>
              {agents.length === 0 && !creatingNew && (
                <p style={{ padding: "10px 14px", fontSize: 12, color: "var(--text-muted)" }}>
                  Nenhum agente cadastrado. Clique <strong>Novo</strong> para criar.
                </p>
              )}
              {creatingNew && (
                <AgentRow
                  agent={{ name: draft.name || "(novo agente)", active: true }}
                  selected={true}
                  pill="NOVO"
                  onClick={() => {}}
                />
              )}
              {agents.map((a) => {
                const isAutoReplyAgent = autoReply.enabled && autoReply.agent_name === a.name;
                return (
                  <AgentRow
                    key={a.id}
                    agent={a}
                    selected={a.id === selectedId && !creatingNew}
                    pill={isAutoReplyAgent ? "AUTO-REPLY" : null}
                    onClick={() => pickAgent(a)}
                  />
                );
              })}
            </div>
            <div style={{ borderTop: "1px solid var(--border-default)", padding: 10 }}>
              <button onClick={() => setSection("whatsapp")}
                      data-testid="agent-config-shortcut-whatsapp"
                      style={{
                        width: "100%", padding: "8px 10px", borderRadius: 8,
                        border: "1px solid var(--border-default)",
                        background: "var(--bg-surface)", cursor: "pointer",
                        fontSize: 12, fontWeight: 700, color: "var(--text-secondary)",
                        display: "inline-flex", alignItems: "center", gap: 8,
                      }}>
                <Smartphone size={14} /> Conectar WhatsApp
              </button>
            </div>
          </aside>

          {/* Main content */}
          <main style={{ display: "grid", gridTemplateRows: "auto 1fr", minHeight: 0 }}>
            <nav style={{
              display: "flex", gap: 4, padding: "10px 14px",
              borderBottom: "1px solid var(--border-default)",
              background: "var(--bg-surface)", overflowX: "auto",
            }}>
              {SECTIONS.map((s) => (
                <button key={s.id}
                        data-testid={`agent-config-section-${s.id}`}
                        onClick={() => setSection(s.id)}
                        style={{
                          padding: "7px 14px", borderRadius: 8,
                          border: "1px solid",
                          borderColor: section === s.id ? "#7c3aed" : "var(--border-default)",
                          background: section === s.id ? "#7c3aed12" : "transparent",
                          color: section === s.id ? "#7c3aed" : "var(--text-secondary)",
                          fontSize: 12, fontWeight: 700, cursor: "pointer",
                          display: "inline-flex", alignItems: "center", gap: 6,
                          whiteSpace: "nowrap",
                        }}>
                  <s.icon size={13} strokeWidth={2} />
                  {s.label}
                </button>
              ))}
            </nav>

            <div style={{ overflow: "auto", padding: 18 }}>
              {error && (
                <div data-testid="agent-config-error" style={{
                  background: "var(--danger-soft)", color: "var(--danger-soft-fg)",
                  padding: 10, borderRadius: 10, marginBottom: 12, fontSize: 13, fontWeight: 600,
                }}>{error}</div>
              )}

              {section === "personality" && (
                <PersonalitySection draft={draft} patch={patch} />
              )}
              {section === "model" && (
                <ModelSection draft={draft} patch={patch} models={models} />
              )}
              {section === "whatsapp" && (
                <WhatsAppSection autoReply={autoReply} reload={reload} />
              )}
              {section === "tools" && (
                <ToolsSection draft={draft} patch={patch} tools={tools} />
              )}
              {section === "autoreply" && (
                <AutoReplySection draft={draft} patch={patch}
                                    autoReply={autoReply} onToggle={toggleAutoReply}
                                    busy={busy} isNew={isNew} />
              )}
            </div>
          </main>
        </div>

        {/* Footer */}
        <footer style={{
          padding: "12px 22px", borderTop: "1px solid var(--border-default)",
          display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap",
          background: "var(--bg-surface-2)",
        }}>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {isNew ? "Novo agente — clique em Salvar para persistir." :
             dirty ? "Você tem alterações não salvas." : "Tudo salvo."}
          </span>
          <span style={{ flex: 1 }} />
          {!isNew && (
            <>
              <button onClick={clone} disabled={busy}
                      data-testid="agent-config-clone"
                      style={btnStyle("ghost")}>
                <Copy size={13} /> Clonar
              </button>
              <button onClick={remove} disabled={busy}
                      data-testid="agent-config-delete"
                      style={btnStyle("danger")}>
                <Trash2 size={13} /> Excluir
              </button>
            </>
          )}
          <button onClick={save} disabled={busy || !dirty}
                  data-testid="agent-config-save"
                  style={btnStyle("primary", busy || !dirty)}>
            <Save size={13} /> {busy ? "Salvando..." : isNew ? "Criar agente" : "Salvar"}
          </button>
        </footer>
      </div>
    </div>
  );
}

function AgentRow({ agent, selected, onClick, pill }) {
  return (
    <button data-testid={`agent-config-row-${agent.id || "new"}`} onClick={onClick} style={{
      width: "100%", padding: "10px 12px", textAlign: "left",
      borderRadius: 8, marginBottom: 3,
      border: "1px solid",
      borderColor: selected ? "#7c3aed" : "transparent",
      background: selected ? "#7c3aed12" : "transparent",
      cursor: "pointer", display: "flex", gap: 8, alignItems: "center",
    }}>
      <div style={{
        width: 30, height: 30, borderRadius: 8,
        background: agent.active === false ? "#cbd5e1" : "#a78bfa",
        color: "white", display: "grid", placeItems: "center",
        fontSize: 11, fontWeight: 800, flexShrink: 0,
      }}>{(agent.name || "?").slice(0, 1).toUpperCase()}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)",
                       overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {agent.name || "(sem nome)"}
        </div>
        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 1,
                       display: "flex", gap: 6 }}>
          {agent.model_name && <span>{agent.model_name}</span>}
          {agent.active === false && <span style={{ color: "#dc2626" }}>· inativo</span>}
        </div>
      </div>
      {pill && (
        <span style={{
          fontSize: 9, fontWeight: 800, padding: "2px 6px", borderRadius: 999,
          background: pill === "AUTO-REPLY" ? "#16a34a" : "#7c3aed",
          color: "white", letterSpacing: ".04em",
        }}>{pill}</span>
      )}
    </button>
  );
}

function PersonalitySection({ draft, patch }) {
  return (
    <div style={{ display: "grid", gap: 14 }}>
      <SectionTitle icon={Brain} title="Personalidade & Expertise"
                     subtitle="Configure a identidade, especialização e conhecimento específico do seu assistente." />

      <Field icon={User} label="Nome do Assistente" required
              hint="O nome que o assistente usará para se apresentar.">
        <input data-testid="agent-config-field-name"
               value={draft.name} onChange={(e) => patch("name", e.target.value)}
               placeholder="Isabella" style={inputStyle()} />
      </Field>

      <Field icon={Bot} label="Mensagem inicial"
              hint="Primeira mensagem enviada quando alguém inicia conversa com este agente.">
        <input data-testid="agent-config-field-initial"
               value={draft.initial_message}
               onChange={(e) => patch("initial_message", e.target.value)}
               placeholder="Olá! Como posso te ajudar hoje? 😊"
               style={inputStyle()} />
      </Field>

      <Field icon={Building2} label="Informações e Regras"
              hint="Informações básicas sobre sua empresa que a IA deve conhecer (SLA, horários, políticas).">
        <textarea data-testid="agent-config-field-company"
                   rows={4} value={draft.company_info}
                   onChange={(e) => patch("company_info", e.target.value)}
                   placeholder="SLA, tempo de atendimento para reparo: 24h.\nHorário comercial: seg-sex 08-18h."
                   style={textareaStyle()} />
      </Field>

      <Field icon={DollarSign} label="Preços e Valores"
              hint="Tabela de preços e informações sobre produtos/serviços.">
        <textarea data-testid="agent-config-field-pricing"
                   rows={5} value={draft.pricing_info}
                   onChange={(e) => patch("pricing_info", e.target.value)}
                   placeholder="PLANOS E VALORES\n- 400 MEGA Fibra: R$ 109,90/mês\n- 600 MEGA Fibra: R$ 139,90/mês"
                   style={textareaStyle()} />
      </Field>

      <Field icon={Settings} label="Parâmetros (system prompt)" required
              hint="Configure parâmetros específicos e diretrizes de comportamento para a IA.">
        <textarea data-testid="agent-config-field-prompt"
                   rows={8} value={draft.system_prompt}
                   onChange={(e) => patch("system_prompt", e.target.value)}
                   placeholder="# PROMPT_AGENTE_V1\n\nObjetivo & Persona\n..."
                   style={textareaStyle()} />
      </Field>

      <Field icon={Star} label="Situações Prioritárias"
              hint="Situações de negócio que merecem atenção prioritária (não emergências, mas prioridades).">
        <textarea data-testid="agent-config-field-priority"
                   rows={5} value={draft.priority_situations}
                   onChange={(e) => patch("priority_situations", e.target.value)}
                   placeholder="Reconquista de ex-cliente: tom acolhedor e oferta exclusiva..."
                   style={textareaStyle()} />
      </Field>
    </div>
  );
}

function ModelSection({ draft, patch, models }) {
  return (
    <div style={{ display: "grid", gap: 14 }}>
      <SectionTitle icon={Sparkles} title="Modelo de IA"
                     subtitle="Provedor, modelo e parâmetros de geração. Tudo via Emergent LLM Key (não precisa de chave externa)." />

      <Field label="Provedor / Modelo" required>
        <select data-testid="agent-config-field-model"
                value={`${draft.model_provider}::${draft.model_name}`}
                onChange={(e) => {
                  const [p, m] = e.target.value.split("::");
                  patch("model_provider", p);
                  patch("model_name", m);
                }}
                style={inputStyle()}>
          {models.length === 0 && <option>Carregando modelos…</option>}
          {models.map((m) => (
            <option key={`${m.provider}::${m.model}`} value={`${m.provider}::${m.model}`}>
              {m.label}
            </option>
          ))}
        </select>
      </Field>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <Field label="Temperatura" hint="0 = determinístico · 2 = muito criativo">
          <input data-testid="agent-config-field-temp" type="number"
                 min={0} max={2} step={0.1} value={draft.temperature}
                 onChange={(e) => patch("temperature", parseFloat(e.target.value) || 0)}
                 style={inputStyle()} />
        </Field>
        <Field label="Max tokens" hint="Tamanho máximo da resposta">
          <input data-testid="agent-config-field-maxtok" type="number"
                 min={50} max={8000} step={50} value={draft.max_tokens}
                 onChange={(e) => patch("max_tokens", parseInt(e.target.value, 10) || 50)}
                 style={inputStyle()} />
        </Field>
      </div>
    </div>
  );
}

function WhatsAppSection({ autoReply, reload }) {
  const [status, setStatus] = useState("connecting");
  const [qr, setQr] = useState(null);
  const [me, setMe] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const pollRef = useRef(null);

  const fetchState = useCallback(async () => {
    try {
      const r = await api.waBaileysQR();
      setStatus(r.status || "disconnected");
      setQr(r.qr || null);
      setMe(r.me || null);
      setErr(null);
    } catch (e) {
      setErr(extractErrorMessage(e));
      setStatus("disconnected");
    }
  }, []);

  useEffect(() => {
    fetchState();
    pollRef.current = setInterval(fetchState, status === "connected" ? 8000 : 3000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [fetchState, status]);

  async function logout() {
    if (!window.confirm("Desconectar este número do WhatsApp?")) return;
    setBusy(true);
    try { await api.waBaileysLogout(); await fetchState(); }
    catch (e) { setErr(extractErrorMessage(e)); }
    finally { setBusy(false); }
  }

  const phoneNumber = me?.id ? me.id.split(":")[0].split("@")[0] : null;

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <SectionTitle icon={Smartphone} title="Conectar WhatsApp"
                     subtitle="Escaneie o QR Code com seu WhatsApp (Aparelhos conectados) para vincular o número." />

      <div data-testid="wa-instance-mini" className="surface" style={{
        padding: 18, borderRadius: 12,
        background: "linear-gradient(135deg, #25d36622, var(--bg-surface) 70%)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div style={{
            width: 44, height: 44, borderRadius: 12, background: "#25d366", color: "white",
            display: "grid", placeItems: "center",
          }}>
            <Smartphone size={22} strokeWidth={1.75} />
          </div>
          <div style={{ flex: 1, minWidth: 200 }}>
            <strong style={{ fontSize: 14 }}>
              {status === "connected" ? `Conectado` : "Aguardando QR"}
            </strong>
            {phoneNumber && (
              <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                Número: <strong>+{phoneNumber}</strong>
              </div>
            )}
          </div>
          <span data-testid="agent-config-wa-status" style={{
            padding: "5px 11px", borderRadius: 999, fontSize: 11, fontWeight: 800,
            background: status === "connected" ? "#dcfce7" : "#fef3c7",
            color: status === "connected" ? "#166534" : "#92400e",
            border: `1px solid ${status === "connected" ? "#86efac" : "#fde68a"}`,
            textTransform: "uppercase", letterSpacing: ".05em",
          }}>
            {status === "connected" ? <><CheckCircle2 size={12} /> Conectado</>
              : status === "connecting" ? <><Loader2 size={12} className="spin" /> Conectando</>
              : <><AlertTriangle size={12} /> Desconectado</>}
          </span>
        </div>
      </div>

      {err && (
        <div style={{
          background: "var(--danger-soft)", color: "var(--danger-soft-fg)",
          padding: 10, borderRadius: 10, fontSize: 13,
        }}>{err}</div>
      )}

      {status === "connected" ? (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <div style={{ padding: 14, background: "#dcfce7", color: "#166534",
                          borderRadius: 10, fontSize: 13, fontWeight: 700, flex: 1, minWidth: 250 }}>
            ✅ WhatsApp conectado. Configure ou ative o auto-reply em <strong>"Auto-reply / Ativação"</strong>.
          </div>
          <button onClick={logout} disabled={busy}
                  data-testid="agent-config-wa-logout"
                  style={btnStyle("danger")}>
            <LogOut size={13} /> Desconectar
          </button>
        </div>
      ) : (
        <div data-testid="agent-config-wa-qr" style={{
          display: "grid", gridTemplateColumns: "auto 1fr", gap: 18,
          padding: 18, background: "var(--bg-surface-2)", borderRadius: 12,
          alignItems: "center",
        }}>
          <div style={{
            width: 240, height: 240, background: "white", borderRadius: 10,
            display: "grid", placeItems: "center",
            border: "1px solid var(--border-default)",
          }}>
            {qr ? (
              <img src={qr} alt="QR" data-testid="agent-config-wa-qr-image"
                   style={{ width: "100%", height: "100%", padding: 8 }} />
            ) : (
              <Loader2 size={32} className="spin" style={{ color: "var(--text-muted)" }} />
            )}
          </div>
          <div>
            <strong style={{ fontSize: 14 }}>Como conectar</strong>
            <ol style={{ margin: "8px 0", paddingLeft: 22, fontSize: 13,
                          color: "var(--text-secondary)", lineHeight: 1.6 }}>
              <li>Abra o WhatsApp no celular.</li>
              <li>Vá em <strong>Configurações → Aparelhos conectados</strong>.</li>
              <li>Toque em <strong>Conectar um aparelho</strong>.</li>
              <li>Escaneie o código QR ao lado.</li>
            </ol>
            <button onClick={fetchState} disabled={busy}
                    data-testid="agent-config-wa-refresh"
                    style={btnStyle("ghost")}>
              <RefreshCw size={13} /> Atualizar QR
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function ToolsSection({ draft, patch, tools }) {
  function toggle(id) {
    const set = new Set(draft.tools_enabled || []);
    if (set.has(id)) set.delete(id); else set.add(id);
    patch("tools_enabled", [...set]);
  }
  return (
    <div style={{ display: "grid", gap: 12 }}>
      <SectionTitle icon={Plug} title="Tools (capacidades especiais)"
                     subtitle="Marque as ações que o agente pode executar automaticamente durante a conversa." />
      {tools.length === 0 && (
        <p style={{ color: "var(--text-muted)", fontSize: 13 }}>Nenhuma tool disponível.</p>
      )}
      {tools.map((t) => {
        const checked = (draft.tools_enabled || []).includes(t.id);
        return (
          <label key={t.id} data-testid={`agent-config-tool-${t.id}`} style={{
            display: "flex", gap: 10, padding: 12,
            border: `1px solid ${checked ? "#7c3aed" : "var(--border-default)"}`,
            background: checked ? "#7c3aed08" : "var(--bg-surface)",
            borderRadius: 10, cursor: "pointer",
          }}>
            <input type="checkbox" checked={checked} onChange={() => toggle(t.id)}
                   style={{ marginTop: 3, accentColor: "#7c3aed" }} />
            <div>
              <strong style={{ fontSize: 13 }}>{t.label}</strong>
              <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>
                {t.description}
              </div>
            </div>
          </label>
        );
      })}
    </div>
  );
}

function AutoReplySection({ draft, patch, autoReply, onToggle, busy, isNew }) {
  const thisAgentActive = autoReply.enabled && autoReply.agent_name === draft.name;
  return (
    <div style={{ display: "grid", gap: 14 }}>
      <SectionTitle icon={Power} title="Auto-reply / Ativação"
                     subtitle="Controla se este agente vai responder automaticamente as mensagens recebidas no WhatsApp." />

      <Field label="Status do agente" hint="Agentes inativos não recebem mensagens nem aparecem no auto-reply.">
        <label style={{ display: "inline-flex", alignItems: "center", gap: 8,
                         padding: "10px 14px",
                         background: draft.active ? "#dcfce7" : "#fee2e2",
                         border: `1px solid ${draft.active ? "#86efac" : "#fecaca"}`,
                         borderRadius: 8, cursor: "pointer", fontWeight: 700,
                         color: draft.active ? "#166534" : "#991b1b", fontSize: 13 }}>
          <input type="checkbox" checked={draft.active}
                  onChange={(e) => patch("active", e.target.checked)}
                  data-testid="agent-config-field-active" />
          {draft.active ? "Agente ATIVO" : "Agente INATIVO"}
        </label>
      </Field>

      <Field icon={Bot} label="Especialidade / Roteamento IA"
              hint="Descreva quando este agente deve ser escolhido em uma conversa nova. Com 2+ agentes ativos, o roteador lê a 1ª msg do cliente e escolhe automaticamente. Ex: 'vendas e novos planos · preço · contratação' / 'suporte técnico · sem sinal · lentidão' / 'financeiro · 2ª via · cobranças'.">
        <textarea data-testid="agent-config-field-routing"
                   rows={3} value={draft.routing_intent}
                   onChange={(e) => patch("routing_intent", e.target.value)}
                   placeholder="Ex: vendas e novos planos, contratação, preço, oferta, cobertura"
                   style={textareaStyle()} />
      </Field>

      <div data-testid="agent-config-autoreply-card" style={{
        padding: 16, borderRadius: 12, background: "var(--bg-surface-2)",
        border: `1px solid ${thisAgentActive ? "#16a34a" : "var(--border-default)"}`,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <strong style={{ fontSize: 14 }}>Auto-reply WhatsApp global</strong>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 4, lineHeight: 1.55 }}>
              Quando ativo, qualquer mensagem recebida no WhatsApp é respondida automaticamente
              pelo agente <strong>{autoReply.agent_name || "(nenhum)"}</strong>.
              {" "}Se você tem múltiplos agentes ATIVOS com <em>Especialidade</em> preenchida,
              o <strong>Roteador IA</strong> escolhe o melhor agente por conversa
              (mantendo a escolha consistente nas mensagens seguintes).
              {isNew && " · Salve este agente primeiro para poder ativá-lo aqui."}
            </div>
          </div>
          <span data-testid="agent-config-autoreply-status" style={{
            padding: "5px 11px", borderRadius: 999, fontSize: 11, fontWeight: 800,
            background: autoReply.enabled ? "#dcfce7" : "#fee2e2",
            color: autoReply.enabled ? "#166534" : "#991b1b",
            border: `1px solid ${autoReply.enabled ? "#86efac" : "#fecaca"}`,
            textTransform: "uppercase", letterSpacing: ".05em",
          }}>{autoReply.enabled ? "ATIVADO" : "DESLIGADO"}</span>
        </div>
        {!isNew && (
          <button onClick={onToggle} disabled={busy}
                  data-testid="agent-config-autoreply-toggle"
                  style={{
                    marginTop: 14, padding: "9px 16px", borderRadius: 8,
                    border: `1px solid ${autoReply.enabled ? "#dc2626" : "#16a34a"}`,
                    background: autoReply.enabled ? "#dc2626" : "#16a34a",
                    color: "white", fontSize: 12, fontWeight: 800,
                    cursor: busy ? "wait" : "pointer",
                    display: "inline-flex", alignItems: "center", gap: 6,
                  }}>
            <Power size={13} />
            {busy ? "..." : autoReply.enabled
              ? "Desligar auto-reply"
              : `Ativar ${draft.name || "este agente"} no auto-reply`}
          </button>
        )}
      </div>

      {thisAgentActive && (
        <div data-testid="agent-config-autoreply-flag" style={{
          padding: 10, background: "#dcfce7", color: "#166534",
          borderRadius: 10, fontSize: 13, fontWeight: 700,
        }}>
          ✅ <strong>{draft.name}</strong> é o agente que responde automaticamente o WhatsApp agora.
        </div>
      )}
    </div>
  );
}

/* ---------- helpers ---------- */
function SectionTitle({ icon: Icon, title, subtitle }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
      <Icon size={18} strokeWidth={1.75} color="#7c3aed" />
      <div>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 800, letterSpacing: "-0.01em" }}>{title}</h3>
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 1 }}>{subtitle}</div>
      </div>
    </div>
  );
}

function Field({ icon: Icon, label, required, hint, children }) {
  return (
    <div>
      <label style={{
        display: "flex", alignItems: "center", gap: 6,
        fontSize: 12, fontWeight: 800, color: "var(--text-primary)",
        marginBottom: 5, letterSpacing: ".01em",
      }}>
        {Icon && <Icon size={13} strokeWidth={1.75} color="#7c3aed" />}
        {label}
        {required && <span style={{ color: "#dc2626" }}>*</span>}
      </label>
      {children}
      {hint && <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>{hint}</div>}
    </div>
  );
}

function inputStyle() {
  return {
    width: "100%", padding: "9px 12px",
    border: "1px solid var(--border-default)", borderRadius: 8,
    fontSize: 13, background: "var(--bg-surface)",
    color: "var(--text-primary)", outline: "none",
  };
}
function textareaStyle() {
  return { ...inputStyle(), resize: "vertical", fontFamily: "ui-monospace, monospace", fontSize: 12 };
}

function btnStyle(variant = "primary", disabled = false) {
  const base = {
    padding: "8px 14px", borderRadius: 8,
    fontSize: 12, fontWeight: 800,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.6 : 1,
    display: "inline-flex", alignItems: "center", gap: 6,
  };
  if (variant === "primary") return { ...base, border: "1px solid #7c3aed", background: "#7c3aed", color: "white" };
  if (variant === "danger")  return { ...base, border: "1px solid #fecaca", background: "#fef2f2", color: "#991b1b" };
  return { ...base, border: "1px solid var(--border-default)", background: "var(--bg-surface)", color: "var(--text-secondary)" };
}
