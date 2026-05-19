import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  X, Bot, Brain, FileText, Plug, Mic, Sparkles, Save, RotateCcw, Play,
  ChevronRight, Plus, Trash2, Star, Building2, DollarSign, User,
  Settings, Smartphone, Loader2, CheckCircle2, AlertTriangle, RefreshCw,
  LogOut, Wand2, ArrowUpCircle, Copy, Power, Cloud, MessageSquare,
  Send, Inbox, Shield, Eye, EyeOff,
} from "lucide-react";
import { api } from "@/api";

/* =============================================================
   AgentConfigModal — Popup "Configurar Robô" estilo Ligo Fibra.

   Estrutura (espelha o PDF):
   - Coluna esquerda: lista de agentes (selecionar, criar, excluir) +
     atalhos para Conectar WhatsApp.
   - Conteúdo principal: 6 seções (nav top-bar):
     1. Personalidade & Expertise  (nome, info, preços, parâmetros, prioridades)
     2. Modelo de IA               (provider, model, temperature, max_tokens)
     3. Conectar WhatsApp          (QR Baileys — não-oficial)
     4. Canal Oficial (Twilio)     (API oficial Meta · sem LID · número real)
     5. Tools                      (checkboxes)
     6. Auto-reply                 (toggle global + escolha do agente ativo)
============================================================= */

const SECTIONS = [
  { id: "personality", label: "Personalidade & Expertise", icon: Brain },
  { id: "model",       label: "Modelo de IA",              icon: Sparkles },
  { id: "whatsapp",    label: "WhatsApp (QR Baileys)",     icon: Smartphone },
  { id: "twilio",      label: "Canal Oficial (Twilio)",    icon: Cloud },
  { id: "meta_cloud",  label: "Meta Cloud (oficial)",      icon: MessageSquare },
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
export function extractErrorMessage(e) {
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

export const BLANK_AGENT = {
  name: "",
  description: "",
  initial_message: "Olá! Como posso te ajudar hoje? 😊",
  system_prompt: "Você é uma assistente virtual cordial e objetiva. Use português do Brasil, no máximo 4 frases curtas, com emojis sutis quando fizer sentido.",
  model_provider: "deepseek",
  model_name: "deepseek-v3.1-terminus",
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

export default function AgentConfigModal({ open, onClose, initialAgentId }) {
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
    } else {
      // Ao fechar, reseta a seleção pra que próxima abertura honre o
      // initialAgentId (deep-link do TopologyMap).
      setSelectedId(null);
      setCreatingNew(false);
    }
  }, [open, reload]);

  /* Quando a lista chega, prioriza initialAgentId (deep-link do TopologyMap)
     senão seleciona o primeiro agente. */
  useEffect(() => {
    if (!open) return;
    if (agents.length > 0 && !selectedId && !creatingNew) {
      if (initialAgentId) {
        const found = agents.find((a) => a.id === initialAgentId);
        if (found) { pickAgent(found); return; }
      }
      pickAgent(agents[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents, open, initialAgentId]);

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
    if (draft.system_prompt.length > 200000) {
      setError(`Parâmetros (system_prompt) excedeu o limite máximo do banco (${draft.system_prompt.length} chars). Limite técnico: 200.000.`);
      return;
    }
    if ((draft.company_info || "").length > 200000) {
      setError(`Informações e Regras excedeu o limite máximo (${draft.company_info.length} chars). Limite técnico: 200.000.`);
      return;
    }
    if ((draft.pricing_info || "").length > 200000) {
      setError(`Preços e Valores excedeu o limite máximo (${draft.pricing_info.length} chars). Limite técnico: 200.000.`);
      return;
    }
    if ((draft.priority_situations || "").length > 200000) {
      setError(`Situações Prioritárias excedeu o limite máximo (${draft.priority_situations.length} chars). Limite técnico: 200.000.`);
      return;
    }
    if (draft.max_tokens > 32000) {
      setError(`Max tokens fora do limite (${draft.max_tokens}). Use até 32000.`);
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
    if (!await window.confirm(`Excluir agente "${draft.name}"? Esta ação não pode ser desfeita.`)) return;
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
              {section === "twilio" && (
                <TwilioSection />
              )}
              {section === "meta_cloud" && (
                <MetaCloudSection />
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

export function PersonalitySection({ draft, patch }) {
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

export function ModelSection({ draft, patch, models }) {
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
        <Field label="Max tokens" hint="Tamanho máximo da resposta (50-32000)">
          <input data-testid="agent-config-field-maxtok" type="number"
                 min={50} max={32000} step={50} value={draft.max_tokens}
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
    if (!await window.confirm("Desconectar este número do WhatsApp?")) return;
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


function TwilioSection() {
  const [cfg, setCfg] = useState(null);
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [flash, setFlash] = useState("");

  // form
  const [accountSid, setAccountSid] = useState("");
  const [authToken, setAuthToken] = useState("");
  const [fromNumber, setFromNumber] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [sandbox, setSandbox] = useState(false);

  // test
  const [testTo, setTestTo] = useState("");
  const [testText, setTestText] = useState("Teste SmartProv — Twilio OK ✅");

  const reload = useCallback(async () => {
    try {
      const [c, s] = await Promise.all([
        api.twilioConfig(),
        api.twilioStatus().catch(() => null),
      ]);
      setCfg(c);
      setStatus(s);
      if (c?.from_number) setFromNumber(c.from_number);
      setEnabled(!!c?.enabled);
      setSandbox(!!c?.sandbox);
    } catch (e) {
      setErr(extractErrorMessage(e));
    }
  }, []);
  useEffect(() => { reload(); }, [reload]);

  async function save() {
    setErr("");
    if (!accountSid.trim() || !authToken.trim() || !fromNumber.trim()) {
      setErr("Preencha Account SID, Auth Token e From Number.");
      return;
    }
    setBusy(true);
    try {
      await api.twilioSetConfig(accountSid.trim(), authToken.trim(),
                                  fromNumber.trim(), enabled, sandbox);
      setFlash("✅ Credenciais salvas.");
      setAccountSid("");
      setAuthToken("");
      await reload();
      setTimeout(() => setFlash(""), 3000);
    } catch (e) {
      setErr(extractErrorMessage(e));
    } finally { setBusy(false); }
  }

  async function toggleEnabled() {
    if (!cfg?.configured) { setErr("Configure primeiro."); return; }
    setBusy(true);
    try {
      // Reusa as creds atuais (mascaradas no GET, então pegamos do form se
      // o usuário acabou de digitar; senão, ao toggle precisamos re-enviar).
      // Estratégia: PUT com mesmo SID/token mascarado falha — então
      // pedimos pro user digitar de novo se quiser desligar via UI.
      // Atalho: PUT com o objeto atual descrito (account_sid e auth_token vazios → erro).
      // Solução: o backend aceita PUT separado se eu acrescentar; mas mantemos
      // simples — toggle só funciona quando user digita as credenciais
      // (caso comum: ele acabou de configurar).
      setErr("Para alterar o status, digite as credenciais novamente abaixo e marque/desmarque 'Habilitado'.");
    } finally { setBusy(false); }
  }

  async function sendTest() {
    setErr("");
    if (!testTo.trim()) { setErr("Informe o telefone destino."); return; }
    setBusy(true);
    try {
      const r = await api.twilioSendTest(testTo.trim(), testText);
      if (r.ok) {
        setFlash(`✅ Enviada · SID: ${r.message_sid?.slice(-10) || "—"}`);
      } else {
        setErr(`Falha: ${r.error || "desconhecido"}`);
      }
      setTimeout(() => setFlash(""), 4000);
    } catch (e) {
      setErr(extractErrorMessage(e));
    } finally { setBusy(false); }
  }

  function copyWebhook() {
    const url = cfg?.webhook_url;
    if (url) {
      navigator.clipboard?.writeText(url);
      setFlash("📋 URL do webhook copiada.");
      setTimeout(() => setFlash(""), 2500);
    }
  }

  const isHealthy = status?.status === "connected";
  const statusMeta = (() => {
    if (!status) return { color: "#94a3b8", label: "—" };
    if (status.status === "connected") return { color: "#10b981", label: "CONECTADO" };
    if (status.status === "disabled") return { color: "#94a3b8", label: "DESABILITADO" };
    return { color: "#dc2626", label: "ERRO" };
  })();

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <SectionTitle icon={Cloud} title="Canal Oficial — Twilio WhatsApp Business"
                     subtitle="API oficial Meta via Twilio (BSP). Sem LID anônimo. Número real, estável, suporte global." />

      {flash && (
        <div data-testid="twilio-flash"
              style={{ background: "#dcfce7", color: "#166534",
                         padding: 8, borderRadius: 8, fontSize: 12, fontWeight: 700 }}>{flash}</div>
      )}
      {err && (
        <div data-testid="twilio-error"
              style={{ background: "var(--danger-soft)", color: "var(--danger-soft-fg)",
                         padding: 10, borderRadius: 10, fontSize: 13, fontWeight: 600 }}>{err}</div>
      )}

      {/* Status atual */}
      <div data-testid="twilio-status-card" className="surface" style={{
        padding: 14, borderRadius: 12,
        background: `linear-gradient(135deg, ${statusMeta.color}22, var(--bg-surface) 70%)`,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div style={{
            width: 40, height: 40, borderRadius: 12, background: statusMeta.color, color: "white",
            display: "grid", placeItems: "center",
          }}><Cloud size={20} strokeWidth={1.75} /></div>
          <div style={{ flex: 1, minWidth: 200 }}>
            <strong style={{ fontSize: 14 }}>
              {cfg?.configured
                ? `Twilio ${cfg?.from_number || ""}`
                : "Twilio não configurado"}
            </strong>
            <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
              {isHealthy && status?.balance
                ? `Saldo: ${status.balance} ${status.currency || "USD"}`
                : status?.error
                  ? status.error.slice(0, 100)
                  : "Configure abaixo para começar."}
            </div>
          </div>
          <span data-testid="twilio-status-pill" style={{
            padding: "5px 11px", borderRadius: 999, fontSize: 11, fontWeight: 800,
            background: `${statusMeta.color}22`, color: statusMeta.color,
            border: `1px solid ${statusMeta.color}66`, letterSpacing: ".05em",
          }}>{statusMeta.label}</span>
        </div>
      </div>

      {/* Webhook URL */}
      {cfg?.webhook_url && (
        <div data-testid="twilio-webhook-card" style={{
          padding: 12, borderRadius: 10, background: "#fef3c7",
          border: "1px solid #fde68a", fontSize: 12, color: "#92400e",
        }}>
          <strong>⚙️ Configure no Twilio Console</strong>
          <div style={{ marginTop: 4, lineHeight: 1.55 }}>
            No painel da Twilio (Messaging → WhatsApp → Senders → seu número → A message comes in):
            cole essa URL como webhook do WhatsApp (POST):
          </div>
          <div style={{ display: "flex", gap: 6, marginTop: 6, alignItems: "center" }}>
            <code data-testid="twilio-webhook-url" style={{
              flex: 1, padding: 6, background: "white", borderRadius: 4,
              fontSize: 11, fontFamily: "ui-monospace, monospace",
              overflow: "auto", whiteSpace: "nowrap", border: "1px solid #fde68a",
            }}>{cfg.webhook_url}</code>
            <button onClick={copyWebhook}
                    data-testid="twilio-copy-webhook"
                    style={{
                      padding: "5px 10px", borderRadius: 6, fontSize: 11, fontWeight: 700,
                      border: "1px solid #f59e0b", background: "#f59e0b", color: "white",
                      cursor: "pointer",
                    }}>
              <Copy size={11} /> Copiar
            </button>
          </div>
        </div>
      )}

      {/* Form de credenciais */}
      <div className="surface" style={{ padding: 16, borderRadius: 12 }}>
        <h4 style={{ margin: "0 0 10px", fontSize: 13, fontWeight: 800 }}>
          Credenciais Twilio
        </h4>
        <p style={{ margin: "0 0 12px", fontSize: 11.5, color: "var(--text-secondary)", lineHeight: 1.55 }}>
          Obtenha em <strong>https://console.twilio.com</strong> → Account → API keys & tokens.
          Os valores são armazenados criptografados.
        </p>

        <Field label="Account SID" required hint="Começa com 'AC...' (34 chars)">
          <input data-testid="twilio-field-sid" type="text"
                  value={accountSid} onChange={(e) => setAccountSid(e.target.value)}
                  placeholder={cfg?.account_sid || "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}
                  style={inputStyle()} disabled={busy} />
        </Field>

        <Field label="Auth Token" required hint="Token primário da conta (esconda em produção).">
          <input data-testid="twilio-field-token" type="password"
                  value={authToken} onChange={(e) => setAuthToken(e.target.value)}
                  placeholder={cfg?.auth_token || "Auth Token (32 chars)"}
                  style={inputStyle()} disabled={busy} />
        </Field>

        <Field label="From Number (WhatsApp aprovado)" required
                hint="Formato E.164. Sandbox usa +14155238886.">
          <input data-testid="twilio-field-from" type="tel"
                  value={fromNumber} onChange={(e) => setFromNumber(e.target.value)}
                  placeholder="+5521998176526"
                  style={inputStyle()} disabled={busy} />
        </Field>

        <div style={{ display: "flex", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 700 }}>
            <input type="checkbox" checked={enabled}
                    onChange={(e) => setEnabled(e.target.checked)}
                    data-testid="twilio-field-enabled" />
            Habilitar canal
          </label>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 700 }}>
            <input type="checkbox" checked={sandbox}
                    onChange={(e) => setSandbox(e.target.checked)}
                    data-testid="twilio-field-sandbox" />
            Modo Sandbox (teste)
          </label>
        </div>

        <button onClick={save} disabled={busy}
                data-testid="twilio-save"
                style={btnStyle("primary", busy)}>
          <Save size={13} /> {busy ? "Salvando..." : "Salvar credenciais"}
        </button>
      </div>

      {/* Teste de envio */}
      {cfg?.configured && cfg?.enabled && (
        <div className="surface" style={{ padding: 16, borderRadius: 12 }}>
          <h4 style={{ margin: "0 0 10px", fontSize: 13, fontWeight: 800 }}>
            Enviar mensagem de teste
          </h4>
          <Field label="Telefone destino" hint="Use o seu próprio celular pra testar.">
            <input data-testid="twilio-test-to" type="tel"
                    value={testTo} onChange={(e) => setTestTo(e.target.value)}
                    placeholder="+5521988887777"
                    style={inputStyle()} disabled={busy} />
          </Field>
          <Field label="Texto">
            <input data-testid="twilio-test-text" type="text"
                    value={testText} onChange={(e) => setTestText(e.target.value)}
                    style={inputStyle()} disabled={busy} />
          </Field>
          <button onClick={sendTest} disabled={busy}
                  data-testid="twilio-test-send"
                  style={btnStyle("primary", busy)}>
            <Play size={13} /> {busy ? "Enviando..." : "Enviar teste"}
          </button>
        </div>
      )}
    </div>
  );
}

/* =============================================================
   MetaCloudSection — Canal Oficial Meta direto (sem BSP)
   WhatsApp Cloud API + Instagram DM + Facebook Messenger
============================================================= */
function MetaCloudSection() {
  const [cfg, setCfg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState("");
  const [err, setErr] = useState("");

  const [appId, setAppId] = useState("");
  const [appSecret, setAppSecret] = useState("");
  const [businessId, setBusinessId] = useState("");
  const [waPhoneNumberId, setWaPhoneNumberId] = useState("");
  const [waBusinessAccountId, setWaBusinessAccountId] = useState("");
  const [waAccessToken, setWaAccessToken] = useState("");
  const [waDisplayPhone, setWaDisplayPhone] = useState("");
  const [enabledWaCloud, setEnabledWaCloud] = useState(false);
  const [pageId, setPageId] = useState("");
  const [pageAccessToken, setPageAccessToken] = useState("");
  const [igBusinessAccountId, setIgBusinessAccountId] = useState("");
  const [enabledMessenger, setEnabledMessenger] = useState(false);
  const [enabledInstagram, setEnabledInstagram] = useState(false);

  const [testTo, setTestTo] = useState("");
  const [testPlatform, setTestPlatform] = useState("whatsapp_cloud");
  const [testText, setTestText] = useState("🚀 Teste SmartProv via Meta Cloud API");
  const [messages, setMessages] = useState([]);
  const [showSecrets, setShowSecrets] = useState(false);

  const reload = useCallback(async () => {
    try {
      const c = await api.metaConfig();
      setCfg(c);
      setAppId(c?.app_id || "");
      setBusinessId(c?.business_id || "");
      setWaPhoneNumberId(c?.wa_phone_number_id || "");
      setWaBusinessAccountId(c?.wa_business_account_id || "");
      setWaDisplayPhone(c?.wa_display_phone || "");
      setEnabledWaCloud(!!c?.enabled_whatsapp_cloud);
      setPageId(c?.page_id || "");
      setIgBusinessAccountId(c?.ig_business_account_id || "");
      setEnabledMessenger(!!c?.enabled_messenger);
      setEnabledInstagram(!!c?.enabled_instagram);
      try {
        const m = await api.metaMessages(20);
        setMessages(m?.items || []);
      } catch { /* ignore */ }
    } catch (e) {
      setErr(extractErrorMessage(e));
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { reload(); }, [reload]);

  async function save() {
    setErr("");
    setBusy(true);
    try {
      const payload = {};
      if (appId.trim()) payload.app_id = appId.trim();
      if (appSecret.trim()) payload.app_secret = appSecret.trim();
      if (businessId.trim()) payload.business_id = businessId.trim();
      if (waPhoneNumberId.trim()) payload.wa_phone_number_id = waPhoneNumberId.trim();
      if (waBusinessAccountId.trim()) payload.wa_business_account_id = waBusinessAccountId.trim();
      if (waAccessToken.trim()) payload.wa_access_token = waAccessToken.trim();
      if (waDisplayPhone.trim()) payload.wa_display_phone = waDisplayPhone.trim();
      payload.enabled_whatsapp_cloud = enabledWaCloud;
      if (pageId.trim()) payload.page_id = pageId.trim();
      if (pageAccessToken.trim()) payload.page_access_token = pageAccessToken.trim();
      if (igBusinessAccountId.trim()) payload.ig_business_account_id = igBusinessAccountId.trim();
      payload.enabled_messenger = enabledMessenger;
      payload.enabled_instagram = enabledInstagram;

      await api.metaSetConfig(payload);
      setFlash("✅ Credenciais salvas.");
      setAppSecret("");
      setWaAccessToken("");
      setPageAccessToken("");
      await reload();
      setTimeout(() => setFlash(""), 3500);
    } catch (e) {
      setErr(extractErrorMessage(e));
    } finally { setBusy(false); }
  }

  async function sendTest() {
    setErr("");
    if (!testTo.trim()) { setErr("Informe o destinatário."); return; }
    setBusy(true);
    try {
      const r = await api.metaSend({
        platform: testPlatform,
        recipient_id: testTo.trim().replace(/[^\d]/g, ""),
        text: testText,
      });
      if (r.ok) {
        setFlash(`✅ Enviada · ID: ${(r.message_id || "").slice(-16)}`);
        await reload();
      } else {
        setErr("Falha ao enviar.");
      }
      setTimeout(() => setFlash(""), 5000);
    } catch (e) {
      setErr(extractErrorMessage(e));
    } finally { setBusy(false); }
  }

  function copy(text, label = "Copiado") {
    if (text) {
      navigator.clipboard?.writeText(text);
      setFlash(`📋 ${label}`);
      setTimeout(() => setFlash(""), 2000);
    }
  }

  async function rotateVerifyToken() {
    if (!await window.confirm("Rotacionar o Verify Token invalidará o webhook atual no Meta. Confirma?")) return;
    setBusy(true);
    try {
      await api.metaRotateVerifyToken();
      setFlash("🔁 Verify Token rotacionado. Atualize no Meta.");
      await reload();
      setTimeout(() => setFlash(""), 4000);
    } catch (e) {
      setErr(extractErrorMessage(e));
    } finally { setBusy(false); }
  }

  if (loading) return <div style={{ padding: 20, fontSize: 12, color: "var(--text-muted)" }}>Carregando...</div>;

  const isWaConfigured = !!cfg?.wa_phone_number_id && !!cfg?.wa_access_token_masked;
  const isMsgConfigured = !!cfg?.page_id && !!cfg?.page_access_token_masked;
  const isIgConfigured = !!cfg?.ig_business_account_id && !!cfg?.page_access_token_masked;

  return (
    <div style={{ display: "grid", gap: 16 }} data-testid="meta-cloud-section">
      <SectionTitle icon={MessageSquare}
                    title="Canal Oficial — Meta Cloud (direto)"
                    subtitle="WhatsApp Business Cloud + Instagram DM + Messenger via Meta Graph API." />

      {flash && (
        <div data-testid="meta-flash" style={{
          background: "#dcfce7", color: "#166534",
          padding: 8, borderRadius: 8, fontSize: 12, fontWeight: 700,
        }}>{flash}</div>
      )}
      {err && (
        <div data-testid="meta-error" style={{
          background: "#fef2f2", color: "#991b1b",
          padding: 8, borderRadius: 8, fontSize: 12, fontWeight: 700,
        }}>{err}</div>
      )}

      <div style={{ display: "grid",
                       gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
                       gap: 10 }}>
        <MetaStatusCard dt="meta-status-wa" label="WhatsApp Cloud" color="#25D366"
                          ok={isWaConfigured && cfg?.enabled_whatsapp_cloud}
                          configured={isWaConfigured} enabled={cfg?.enabled_whatsapp_cloud}
                          subtitle={cfg?.wa_display_phone || "—"} />
        <MetaStatusCard dt="meta-status-msg" label="Messenger" color="#0084FF"
                          ok={isMsgConfigured && cfg?.enabled_messenger}
                          configured={isMsgConfigured} enabled={cfg?.enabled_messenger}
                          subtitle={cfg?.page_id ? `Page ${cfg.page_id.slice(0,10)}…` : "—"} />
        <MetaStatusCard dt="meta-status-ig" label="Instagram DM" color="#E4405F"
                          ok={isIgConfigured && cfg?.enabled_instagram}
                          configured={isIgConfigured} enabled={cfg?.enabled_instagram}
                          subtitle={cfg?.ig_business_account_id ? `IG ${cfg.ig_business_account_id.slice(0,10)}…` : "—"} />
      </div>

      <div className="surface" data-testid="meta-webhook-card" style={{
        padding: 14, borderRadius: 10,
        border: "1px solid var(--border-default)",
        background: "linear-gradient(135deg, rgba(99,102,241,.06), var(--bg-surface) 70%)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <Shield size={15} color="#6366f1" />
          <strong style={{ fontSize: 13 }}>Webhook (configurar no painel Meta)</strong>
        </div>
        <div style={{ display: "grid", gap: 8 }}>
          <Field icon={Inbox} label="URL de retorno (Callback URL)">
            <div style={{ display: "flex", gap: 6 }}>
              <input readOnly value={cfg?.webhook_url || ""} style={inputStyle()}
                     data-testid="meta-webhook-url" />
              <button onClick={() => copy(cfg?.webhook_url, "URL copiada")}
                      data-testid="meta-copy-webhook"
                      style={btnStyle("ghost")}>
                <Copy size={13} /> Copiar
              </button>
            </div>
          </Field>
          <Field icon={Shield} label="Token de verificação (Verify Token)">
            <div style={{ display: "flex", gap: 6 }}>
              <input readOnly type={showSecrets ? "text" : "password"}
                     value={cfg?.verify_token || ""}
                     style={inputStyle()} data-testid="meta-verify-token" />
              <button onClick={() => setShowSecrets((v) => !v)}
                      style={btnStyle("ghost")}>
                {showSecrets ? <EyeOff size={13} /> : <Eye size={13} />}
              </button>
              <button onClick={() => copy(cfg?.verify_token, "Verify token copiado")}
                      data-testid="meta-copy-verify"
                      style={btnStyle("ghost")}>
                <Copy size={13} /> Copiar
              </button>
              <button onClick={rotateVerifyToken} disabled={busy}
                      data-testid="meta-rotate-verify"
                      style={btnStyle("ghost")}>
                <RotateCcw size={13} /> Rotacionar
              </button>
            </div>
          </Field>
          <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.6 }}>
            No painel Meta, em <strong>WhatsApp → Configuração → Webhook</strong>, cole esta URL e o Verify Token.
            Depois, marque o campo <code>messages</code> e clique em <strong>Verificar e salvar</strong>.
          </div>
        </div>
      </div>

      <div className="surface" style={{
        padding: 14, borderRadius: 10, border: "1px solid var(--border-default)",
        background: "var(--bg-surface)", display: "grid", gap: 10,
      }}>
        <strong style={{ fontSize: 12, color: "var(--text-muted)",
                          textTransform: "uppercase", letterSpacing: ".05em" }}>
          App Meta (raiz)
        </strong>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Field label="App ID">
            <input value={appId} onChange={(e) => setAppId(e.target.value)}
                   data-testid="meta-app-id" style={inputStyle()}
                   placeholder="1771613244212273" />
          </Field>
          <Field label="App Secret"
                 hint={cfg?.app_secret_masked ? `Atual: ${cfg.app_secret_masked}` : "Settings → Basic"}>
            <input value={appSecret} onChange={(e) => setAppSecret(e.target.value)}
                   type="password" data-testid="meta-app-secret"
                   style={inputStyle()}
                   placeholder={cfg?.app_secret_masked ? "•••••••• (vazio p/ manter)" : "32-char hex"} />
          </Field>
          <Field label="Business Manager ID">
            <input value={businessId} onChange={(e) => setBusinessId(e.target.value)}
                   data-testid="meta-business-id" style={inputStyle()}
                   placeholder="278728139433613" />
          </Field>
        </div>
      </div>

      <div className="surface" data-testid="meta-wa-block" style={{
        padding: 14, borderRadius: 10,
        border: `1px solid ${enabledWaCloud ? "#25D366" : "var(--border-default)"}`,
        background: "var(--bg-surface)", display: "grid", gap: 10,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <MessageSquare size={15} color="#25D366" />
          <strong style={{ fontSize: 13 }}>WhatsApp Cloud API</strong>
          <span style={{ flex: 1 }} />
          <label style={{ display: "flex", alignItems: "center", gap: 6,
                              fontSize: 12, cursor: "pointer" }}>
            <input type="checkbox" checked={enabledWaCloud}
                   onChange={(e) => setEnabledWaCloud(e.target.checked)}
                   data-testid="meta-wa-enabled" />
            Habilitado
          </label>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Field label="Phone Number ID">
            <input value={waPhoneNumberId}
                   onChange={(e) => setWaPhoneNumberId(e.target.value)}
                   data-testid="meta-wa-phone-id" style={inputStyle()}
                   placeholder="765733073283397" />
          </Field>
          <Field label="WABA ID">
            <input value={waBusinessAccountId}
                   onChange={(e) => setWaBusinessAccountId(e.target.value)}
                   data-testid="meta-wa-waba-id" style={inputStyle()}
                   placeholder="972303201594461" />
          </Field>
          <Field label="Access Token"
                 hint={cfg?.wa_access_token_masked ? "Atual armazenado (criptografado)" : "Temporário 24h ou permanente"}>
            <input value={waAccessToken} onChange={(e) => setWaAccessToken(e.target.value)}
                   type="password" data-testid="meta-wa-token"
                   style={inputStyle()}
                   placeholder={cfg?.wa_access_token_masked ? "•••••••• (vazio p/ manter)" : "EAANk..."} />
          </Field>
          <Field label="Número exibido (display)">
            <input value={waDisplayPhone}
                   onChange={(e) => setWaDisplayPhone(e.target.value)}
                   data-testid="meta-wa-display" style={inputStyle()}
                   placeholder="+55 800 021 2111" />
          </Field>
        </div>
      </div>

      <div className="surface" style={{
        padding: 14, borderRadius: 10, border: "1px solid var(--border-default)",
        background: "var(--bg-surface)", display: "grid", gap: 10,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <strong style={{ fontSize: 13 }}>Messenger & Instagram (Page-based)</strong>
          <span style={{ flex: 1 }} />
          <label style={{ display: "flex", alignItems: "center", gap: 6,
                              fontSize: 12, cursor: "pointer" }}>
            <input type="checkbox" checked={enabledMessenger}
                   onChange={(e) => setEnabledMessenger(e.target.checked)}
                   data-testid="meta-msg-enabled" />
            Messenger
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6,
                              fontSize: 12, cursor: "pointer" }}>
            <input type="checkbox" checked={enabledInstagram}
                   onChange={(e) => setEnabledInstagram(e.target.checked)}
                   data-testid="meta-ig-enabled" />
            Instagram
          </label>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Field label="Facebook Page ID">
            <input value={pageId} onChange={(e) => setPageId(e.target.value)}
                   data-testid="meta-page-id" style={inputStyle()} />
          </Field>
          <Field label="Instagram Business Account ID">
            <input value={igBusinessAccountId}
                   onChange={(e) => setIgBusinessAccountId(e.target.value)}
                   data-testid="meta-ig-id" style={inputStyle()} />
          </Field>
          <Field label="Page Access Token"
                 hint={cfg?.page_access_token_masked ? "Atual armazenado" : "Gerado via Business Manager"}>
            <input value={pageAccessToken}
                   onChange={(e) => setPageAccessToken(e.target.value)}
                   type="password" data-testid="meta-page-token"
                   style={inputStyle()}
                   placeholder={cfg?.page_access_token_masked ? "•••••••• (vazio p/ manter)" : "EAANk..."} />
          </Field>
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button onClick={save} disabled={busy}
                data-testid="meta-save" style={btnStyle("primary", busy)}>
          <Save size={13} /> {busy ? "Salvando..." : "Salvar credenciais"}
        </button>
      </div>

      <div className="surface" data-testid="meta-test-card" style={{
        padding: 14, borderRadius: 10, border: "1px solid var(--border-default)",
        background: "var(--bg-surface)", display: "grid", gap: 10,
      }}>
        <strong style={{ fontSize: 13 }}>🧪 Enviar mensagem de teste</strong>
        <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: 10 }}>
          <Field label="Plataforma">
            <select value={testPlatform}
                    onChange={(e) => setTestPlatform(e.target.value)}
                    data-testid="meta-test-platform" style={inputStyle()}>
              <option value="whatsapp_cloud">WhatsApp Cloud</option>
              <option value="messenger">Messenger</option>
              <option value="instagram">Instagram</option>
            </select>
          </Field>
          <Field label={testPlatform === "whatsapp_cloud" ? "Número destino" : "ID destinatário"}>
            <input value={testTo} onChange={(e) => setTestTo(e.target.value)}
                   data-testid="meta-test-to" style={inputStyle()}
                   placeholder={testPlatform === "whatsapp_cloud" ? "+5521999999999" : "1234567890"} />
          </Field>
        </div>
        <Field label="Mensagem">
          <textarea value={testText} onChange={(e) => setTestText(e.target.value)}
                    data-testid="meta-test-text" rows={2} style={textareaStyle()} />
        </Field>
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button onClick={sendTest} disabled={busy}
                  data-testid="meta-send-test" style={btnStyle("primary", busy)}>
            <Send size={13} /> {busy ? "Enviando..." : "Enviar teste"}
          </button>
        </div>
      </div>

      <div className="surface" data-testid="meta-messages-list" style={{
        padding: 14, borderRadius: 10, border: "1px solid var(--border-default)",
        background: "var(--bg-surface)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <Inbox size={15} color="#6366f1" />
          <strong style={{ fontSize: 13 }}>Mensagens recentes ({messages.length})</strong>
          <span style={{ flex: 1 }} />
          <button onClick={reload} style={btnStyle("ghost")}>
            <RefreshCw size={13} /> Atualizar
          </button>
        </div>
        {messages.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--text-muted)", fontStyle: "italic",
                          padding: "16px 0", textAlign: "center" }}>
            Sem mensagens ainda. Envie uma de teste ou aguarde clientes responderem.
          </div>
        ) : (
          <div style={{ display: "grid", gap: 6, maxHeight: 280, overflowY: "auto" }}>
            {messages.map((m) => (
              <div key={m.id} style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "6px 8px", borderRadius: 6,
                background: m.direction === "inbound" ? "rgba(99,102,241,.05)" : "rgba(16,185,129,.05)",
                fontSize: 12,
              }}>
                <span style={{
                  padding: "1px 6px", borderRadius: 4, fontSize: 9, fontWeight: 800,
                  background: m.direction === "inbound" ? "#6366f1" : "#10b981",
                  color: "white", textTransform: "uppercase",
                }}>
                  {m.direction === "inbound" ? "RX" : "TX"}
                </span>
                <span style={{ fontWeight: 700, minWidth: 100 }}>{m.phone}</span>
                <span style={{ fontSize: 9, color: "var(--text-muted)",
                                  textTransform: "uppercase", letterSpacing: ".05em" }}>
                  {(m.platform || m.channel || "").replace("meta_", "")}
                </span>
                <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis",
                                  whiteSpace: "nowrap" }}>{m.text}</span>
                <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
                  {new Date(m.created_at).toLocaleTimeString("pt-BR",
                    { hour: "2-digit", minute: "2-digit" })}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function MetaStatusCard({ dt, label, color, ok, configured, subtitle }) {
  const statusColor = ok ? "#10b981" : configured ? "#f59e0b" : "#94a3b8";
  const statusText = ok ? "ONLINE" : configured ? "DESABILITADO" : "NÃO CONFIG";
  return (
    <div data-testid={dt} style={{
      padding: 12, borderRadius: 10,
      border: `1px solid ${ok ? color : "var(--border-default)"}`,
      background: "var(--bg-surface)", display: "flex", gap: 10, alignItems: "center",
    }}>
      <div style={{
        width: 36, height: 36, borderRadius: 8,
        background: ok ? color : "var(--bg-surface-2)",
        color: ok ? "white" : color,
        display: "grid", placeItems: "center",
      }}>
        <MessageSquare size={18} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 800, color: "var(--text-primary)" }}>
          {label}
        </div>
        <div style={{ fontSize: 10, color: statusColor, fontWeight: 800,
                          letterSpacing: ".05em" }}>
          {statusText}
        </div>
        <div style={{ fontSize: 10, color: "var(--text-muted)",
                          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {subtitle}
        </div>
      </div>
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
