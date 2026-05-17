import React, { useEffect, useState } from "react";
import { Card } from "@/ui";
import { api } from "@/api";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import {
  Save, Plus, Trash2, ChevronDown, ChevronRight,
  ShoppingCart, Tag, TrendingUp, Sparkles, Wrench,
  Loader2, CheckCircle2, AlertCircle, Bot, Send, Sparkle, Zap,
} from "lucide-react";

/**
 * Sub-aba "Gestão" da Configuração do Atendimento IA.
 *
 * - Aba "Prompt Principal": editor textarea do system_prompt da Isabella.
 * - Aba "Módulos": fragments categorizados (vendas/promoção/upgrade/novidade)
 *   que se incorporam ao prompt da Isabella em runtime, controláveis com
 *   switch on/off, editáveis inline, criáveis e deletáveis.
 */
const CATEGORY_META = {
  vendas:   { icon: ShoppingCart, label: "Vendas", color: "#16a34a" },
  promocao: { icon: Tag,          label: "Promoção", color: "#f59e0b" },
  upgrade:  { icon: TrendingUp,   label: "Upgrade",  color: "#3b82f6" },
  novidade: { icon: Sparkles,     label: "Novidade", color: "#a855f7" },
  custom:   { icon: Wrench,       label: "Customizado", color: "#64748b" },
};

export default function IsabellaGestaoTab() {
  return (
    <Card style={{ padding: 14 }} data-testid="isabella-gestao-card">
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <div style={{
          width: 36, height: 36, borderRadius: 9,
          background: "linear-gradient(135deg,#a855f7,#ec4899)",
          display: "grid", placeItems: "center",
        }}>
          <Bot size={20} color="white" strokeWidth={1.75} />
        </div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 14, color: "var(--text-primary)" }}>
            Gestão da Isabella IA
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
            Edite o prompt principal e ative módulos de intenção
            (vendas, promoção, upgrade, novidades)
          </div>
        </div>
      </div>

      <Tabs defaultValue="modules">
        <TabsList>
          <TabsTrigger value="modules" data-testid="isabella-tab-modules">
            Módulos de Intenção
          </TabsTrigger>
          <TabsTrigger value="prompt" data-testid="isabella-tab-prompt">
            Prompt Principal
          </TabsTrigger>
          <TabsTrigger value="test" data-testid="isabella-tab-test">
            Testar Resposta
          </TabsTrigger>
        </TabsList>

        <TabsContent value="modules">
          <FragmentsManager />
        </TabsContent>

        <TabsContent value="prompt">
          <PromptEditor />
        </TabsContent>

        <TabsContent value="test">
          <TestSandbox />
        </TabsContent>
      </Tabs>
    </Card>
  );
}

// ============================================================================
// Editor do Prompt Principal
// ============================================================================
function PromptEditor() {
  const [meta, setMeta] = useState(null);
  const [text, setText] = useState("");
  const [original, setOriginal] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.isabellaPromptGet();
      setMeta(r);
      setText(r.system_prompt || "");
      setOriginal(r.system_prompt || "");
    } catch (e) {
      setMsg({ kind: "err", text: e?.response?.data?.detail || e.message });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const save = async () => {
    if (!text.trim()) { setMsg({ kind: "err", text: "Prompt não pode ficar vazio" }); return; }
    setSaving(true); setMsg(null);
    try {
      await api.isabellaPromptUpdate(text);
      setOriginal(text);
      setMsg({ kind: "ok", text: `Salvo (${text.length.toLocaleString()} chars)` });
      setTimeout(() => setMsg(null), 3500);
    } catch (e) {
      setMsg({ kind: "err", text: e?.response?.data?.detail || e.message });
    } finally { setSaving(false); }
  };

  const dirty = text !== original;

  if (loading) return <div style={{ padding: 30, textAlign: "center", color: "var(--text-muted)" }}>Carregando…</div>;

  return (
    <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {meta?.size?.toLocaleString() || 0} chars · modelo: <b>{meta?.model_name || "—"}</b>
          {meta?.updated_at && (
            <> · atualizado {new Date(meta.updated_at).toLocaleString("pt-BR")}</>
          )}
          {meta?.updated_by && <> · por <b>{meta.updated_by}</b></>}
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <button
            data-testid="isabella-prompt-save-btn"
            onClick={save}
            disabled={saving || !dirty}
            style={{
              padding: "8px 16px",
              border: 0, borderRadius: 8,
              background: dirty ? "linear-gradient(135deg,#a855f7,#ec4899)" : "var(--bg-elevated)",
              color: dirty ? "white" : "var(--text-muted)",
              fontSize: 12, fontWeight: 700,
              cursor: dirty && !saving ? "pointer" : "default",
              display: "flex", alignItems: "center", gap: 6,
              opacity: saving ? 0.6 : 1,
            }}
          >
            {saving ? <Loader2 size={14} className="spin" /> : <Save size={14} />}
            {saving ? "Salvando…" : dirty ? "Salvar alterações" : "Sem alterações"}
          </button>
        </div>
      </div>

      <textarea
        data-testid="isabella-prompt-textarea"
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
        style={{
          width: "100%",
          minHeight: 520,
          padding: 12,
          border: "1px solid var(--border-default)",
          borderRadius: 10,
          background: "var(--bg-elevated)",
          color: "var(--text-primary)",
          fontFamily: "ui-monospace, 'SF Mono', Menlo, monospace",
          fontSize: 12,
          lineHeight: 1.55,
          resize: "vertical",
        }}
      />
      {msg && (
        <div style={{
          padding: "8px 12px", borderRadius: 8,
          background: msg.kind === "ok" ? "rgba(16,185,129,.12)" : "rgba(220,38,38,.12)",
          color: msg.kind === "ok" ? "#047857" : "#b91c1c",
          fontSize: 12, display: "flex", alignItems: "center", gap: 6,
        }}>
          {msg.kind === "ok" ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
          {msg.text}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Gerenciador de Fragments (Módulos)
// ============================================================================
function FragmentsManager() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [msg, setMsg] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.isabellaFragmentsList();
      setItems(r.items || []);
    } catch (e) {
      setMsg({ kind: "err", text: e?.response?.data?.detail || e.message });
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const toggleEnabled = async (frag, val) => {
    try {
      const updated = await api.isabellaFragmentPatch(frag.id, { enabled: val });
      setItems((prev) => prev.map((x) => (x.id === frag.id ? updated : x)));
    } catch (e) {
      setMsg({ kind: "err", text: e?.response?.data?.detail || e.message });
    }
  };

  const patchFragment = async (id, data) => {
    try {
      const updated = await api.isabellaFragmentPatch(id, data);
      setItems((prev) => prev.map((x) => (x.id === id ? updated : x)));
      setMsg({ kind: "ok", text: "Módulo atualizado" });
      setTimeout(() => setMsg(null), 2500);
    } catch (e) {
      setMsg({ kind: "err", text: e?.response?.data?.detail || e.message });
    }
  };

  const deleteFragment = async (id) => {
    if (!window.confirm("Excluir este módulo? Essa ação não pode ser desfeita.")) return;
    try {
      await api.isabellaFragmentDelete(id);
      setItems((prev) => prev.filter((x) => x.id !== id));
    } catch (e) {
      setMsg({ kind: "err", text: e?.response?.data?.detail || e.message });
    }
  };

  const createFragment = async (data) => {
    try {
      const created = await api.isabellaFragmentCreate(data);
      setItems((prev) => [...prev, created]);
      setCreating(false);
      setMsg({ kind: "ok", text: "Módulo criado" });
      setTimeout(() => setMsg(null), 2500);
    } catch (e) {
      setMsg({ kind: "err", text: e?.response?.data?.detail || e.message });
    }
  };

  if (loading) return <div style={{ padding: 30, textAlign: "center", color: "var(--text-muted)" }}>Carregando…</div>;

  return (
    <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {items.length} módulo(s) · {items.filter((x) => x.enabled).length} ativo(s).
          Módulos ativos são <b>injetados no prompt da Isabella</b> em toda resposta.
        </div>
        <button
          data-testid="isabella-fragment-new-btn"
          onClick={() => setCreating(true)}
          style={{
            marginLeft: "auto",
            padding: "7px 12px",
            border: 0, borderRadius: 8,
            background: "linear-gradient(135deg,#a855f7,#ec4899)",
            color: "white", fontSize: 11, fontWeight: 700,
            cursor: "pointer",
            display: "flex", alignItems: "center", gap: 5,
          }}
        >
          <Plus size={14} /> Novo módulo
        </button>
      </div>

      {creating && (
        <FragmentForm
          onCancel={() => setCreating(false)}
          onSave={createFragment}
        />
      )}

      <div style={{ display: "grid", gap: 8 }}>
        {items.map((f) => (
          <FragmentRow
            key={f.id}
            frag={f}
            onToggle={(v) => toggleEnabled(f, v)}
            onSave={(data) => patchFragment(f.id, data)}
            onDelete={() => deleteFragment(f.id)}
          />
        ))}
        {items.length === 0 && (
          <div style={{ padding: 30, textAlign: "center", color: "var(--text-muted)", fontSize: 12 }}>
            Nenhum módulo cadastrado. Clique em "Novo módulo" pra criar.
          </div>
        )}
      </div>

      {msg && (
        <div style={{
          padding: "8px 12px", borderRadius: 8,
          background: msg.kind === "ok" ? "rgba(16,185,129,.12)" : "rgba(220,38,38,.12)",
          color: msg.kind === "ok" ? "#047857" : "#b91c1c",
          fontSize: 12, display: "flex", alignItems: "center", gap: 6,
        }}>
          {msg.kind === "ok" ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
          {msg.text}
        </div>
      )}
    </div>
  );
}

function FragmentRow({ frag, onToggle, onSave, onDelete }) {
  const [open, setOpen] = useState(false);
  const meta = CATEGORY_META[frag.category] || CATEGORY_META.custom;
  const Icon = meta.icon;

  return (
    <div
      data-testid={`isabella-fragment-${frag.id}`}
      style={{
        border: "1px solid var(--border-default)",
        borderRadius: 10,
        background: "var(--bg-surface)",
        overflow: "hidden",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: 10 }}>
        <button
          onClick={() => setOpen(!open)}
          style={{ background: "transparent", border: 0, cursor: "pointer", color: "var(--text-muted)" }}
        >
          {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
        <div style={{
          width: 32, height: 32, borderRadius: 8,
          background: `${meta.color}18`, color: meta.color,
          display: "grid", placeItems: "center",
        }}>
          <Icon size={16} strokeWidth={1.75} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-primary)" }}>
            {frag.title}
          </div>
          <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
            <b style={{ color: meta.color }}>{meta.label}</b> · {(frag.content || "").length} chars
            {frag.updated_at && (<> · atualizado {new Date(frag.updated_at).toLocaleDateString("pt-BR")}</>)}
          </div>
        </div>
        <Switch
          checked={frag.enabled}
          onCheckedChange={onToggle}
          data-testid={`isabella-fragment-toggle-${frag.id}`}
        />
        <button
          onClick={onDelete}
          data-testid={`isabella-fragment-delete-${frag.id}`}
          style={{
            background: "transparent", border: 0, cursor: "pointer",
            color: "#94a3b8", padding: 6, borderRadius: 6,
          }}
          title="Excluir"
        >
          <Trash2 size={14} />
        </button>
      </div>

      {open && (
        <FragmentForm
          initial={frag}
          onSave={onSave}
          onCancel={() => setOpen(false)}
          inline
        />
      )}
    </div>
  );
}

function FragmentForm({ initial, onSave, onCancel, inline = false }) {
  const [category, setCategory] = useState(initial?.category || "vendas");
  const [title, setTitle] = useState(initial?.title || "");
  const [content, setContent] = useState(initial?.content || "");
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!title.trim() || !content.trim()) return;
    setSaving(true);
    try {
      await onSave({ category, title: title.trim(), content: content.trim(), enabled });
    } finally { setSaving(false); }
  };

  return (
    <div style={{
      padding: inline ? "0 10px 10px 50px" : "12px 12px 12px 12px",
      borderTop: inline ? "1px dashed var(--border-default)" : "none",
      paddingTop: inline ? 10 : 12,
      background: inline ? "transparent" : "var(--bg-elevated)",
      borderRadius: inline ? 0 : 10,
      display: "grid", gap: 8,
    }}>
      <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 8 }}>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          data-testid="isabella-fragment-category-select"
          style={{
            padding: "8px 10px",
            border: "1px solid var(--border-default)",
            borderRadius: 8,
            background: "var(--bg-surface)",
            color: "var(--text-primary)",
            fontSize: 12,
          }}
        >
          <option value="vendas">🛒 Vendas</option>
          <option value="promocao">🎯 Promoção</option>
          <option value="upgrade">📈 Upgrade</option>
          <option value="novidade">✨ Novidade</option>
          <option value="custom">🔧 Customizado</option>
        </select>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Título do módulo"
          data-testid="isabella-fragment-title-input"
          style={{
            padding: "8px 10px",
            border: "1px solid var(--border-default)",
            borderRadius: 8,
            background: "var(--bg-surface)",
            color: "var(--text-primary)",
            fontSize: 12,
          }}
        />
      </div>
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder="Conteúdo do módulo — instruções que serão injetadas no prompt da Isabella quando o módulo estiver ativo."
        spellCheck={false}
        rows={8}
        data-testid="isabella-fragment-content-textarea"
        style={{
          padding: 10,
          border: "1px solid var(--border-default)",
          borderRadius: 8,
          background: "var(--bg-surface)",
          color: "var(--text-primary)",
          fontFamily: "ui-monospace, 'SF Mono', Menlo, monospace",
          fontSize: 12,
          lineHeight: 1.5,
          resize: "vertical",
        }}
      />
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--text-muted)" }}>
          <Switch checked={enabled} onCheckedChange={setEnabled} />
          Ativo
        </label>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          {onCancel && (
            <button
              onClick={onCancel}
              data-testid="isabella-fragment-cancel-btn"
              style={{
                padding: "7px 14px", border: 0, borderRadius: 8,
                background: "var(--bg-surface)", color: "var(--text-muted)",
                fontSize: 11, fontWeight: 600, cursor: "pointer",
              }}
            >
              Cancelar
            </button>
          )}
          <button
            onClick={submit}
            disabled={saving || !title.trim() || !content.trim()}
            data-testid="isabella-fragment-save-btn"
            style={{
              padding: "7px 14px", border: 0, borderRadius: 8,
              background: "linear-gradient(135deg,#a855f7,#ec4899)",
              color: "white", fontSize: 11, fontWeight: 700,
              cursor: saving ? "default" : "pointer",
              display: "flex", alignItems: "center", gap: 5,
              opacity: saving ? 0.6 : 1,
            }}
          >
            {saving ? <Loader2 size={12} className="spin" /> : <Save size={12} />}
            Salvar
          </button>
        </div>
      </div>
    </div>
  );
}


// ============================================================================
// Sandbox de Teste — simula resposta da Isabella sem mandar pelo WhatsApp
// ============================================================================
const PRESET_PROMPTS = [
  { label: "Vendas — cliente novo", text: "oi, quero contratar internet, somos 3 pessoas em casa, moro no bairro Penha no Rio de Janeiro" },
  { label: "Vendas — bairro sem cobertura", text: "tem internet em Copacabana?" },
  { label: "Manutenção — sem internet", text: "minha internet caiu, já reiniciei e nada" },
  { label: "Financeiro — 2ª via", text: "preciso da segunda via do meu boleto" },
  { label: "Agendamento — visita técnica", text: "quero agendar uma visita técnica para amanhã" },
  { label: "Cancelamento — retenção", text: "estou pensando em cancelar a internet" },
  { label: "Plano sem fidelidade", text: "vocês têm algum plano sem fidelidade?" },
];

function TestSandbox() {
  const [text, setText] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  const run = async (msg) => {
    const t = (msg ?? text).trim();
    if (!t) return;
    setLoading(true);
    setErr(null);
    setResult(null);
    try {
      const r = await api.isabellaTest(t);
      setResult(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Erro ao testar");
    } finally { setLoading(false); }
  };

  return (
    <div style={{ display: "grid", gap: 12, marginTop: 10 }}>
      <div style={{
        padding: 12, borderRadius: 10,
        background: "linear-gradient(135deg, rgba(168,85,247,.05), rgba(236,72,153,.05))",
        border: "1px solid rgba(168,85,247,.2)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <Zap size={14} color="#a855f7" />
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-primary)" }}>
            Sandbox de Teste — Resposta da Isabella
          </div>
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 10 }}>
          Digite uma mensagem como se fosse o cliente. A Isabella vai responder usando o prompt principal + módulos ativos + agenda da lousa (quando aplicável).
          Nada é persistido nem enviado pelo WhatsApp — só simulação.
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
          {PRESET_PROMPTS.map((p) => (
            <button
              key={p.label}
              onClick={() => { setText(p.text); run(p.text); }}
              disabled={loading}
              data-testid={`isabella-preset-${p.label.replace(/\s/g, "-")}`}
              style={{
                padding: "5px 10px", borderRadius: 16,
                border: "1px solid var(--border-default)",
                background: "var(--bg-surface)",
                color: "var(--text-primary)",
                fontSize: 10.5, fontWeight: 600,
                cursor: loading ? "default" : "pointer",
                opacity: loading ? 0.5 : 1,
              }}
            >
              {p.label}
            </button>
          ))}
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Digite uma mensagem teste do cliente..."
            rows={2}
            data-testid="isabella-test-input"
            style={{
              flex: 1, padding: 10,
              border: "1px solid var(--border-default)",
              borderRadius: 8,
              background: "var(--bg-surface)",
              color: "var(--text-primary)",
              fontSize: 12,
              resize: "vertical",
              minHeight: 50,
            }}
          />
          <button
            onClick={() => run()}
            disabled={loading || !text.trim()}
            data-testid="isabella-test-run-btn"
            style={{
              padding: "10px 18px", border: 0, borderRadius: 8,
              background: loading || !text.trim() ? "var(--bg-elevated)" : "linear-gradient(135deg,#a855f7,#ec4899)",
              color: loading || !text.trim() ? "var(--text-muted)" : "white",
              fontSize: 12, fontWeight: 700,
              cursor: loading || !text.trim() ? "default" : "pointer",
              display: "flex", alignItems: "center", gap: 6,
              alignSelf: "stretch",
            }}
          >
            {loading ? <Loader2 size={14} className="spin" /> : <Send size={14} />}
            {loading ? "Pensando…" : "Testar"}
          </button>
        </div>
      </div>

      {err && (
        <div style={{
          padding: "8px 12px", borderRadius: 8,
          background: "rgba(220,38,38,.12)", color: "#b91c1c",
          fontSize: 12, display: "flex", alignItems: "center", gap: 6,
        }}>
          <AlertCircle size={14} /> {err}
        </div>
      )}

      {result && <TestResult result={result} />}
    </div>
  );
}

function TestResult({ result }) {
  return (
    <div style={{ display: "grid", gap: 10 }}>
      <div style={{
        display: "flex", gap: 12, alignItems: "center",
        fontSize: 11, color: "var(--text-muted)",
        flexWrap: "wrap",
      }}>
        <span><b style={{ color: "var(--text-primary)" }}>{result.bubbles?.length || 0}</b> bolhas</span>
        <span>·</span>
        <span><b style={{ color: "var(--text-primary)" }}>{result.elapsed_ms}</b> ms</span>
        <span>·</span>
        <span>modelo <b>{result.model}</b></span>
        <span>·</span>
        <span>prompt <b>{result.prompt_size?.toLocaleString()}</b> chars</span>
        <span>·</span>
        <span><b style={{ color: "#a855f7" }}>{result.fragments_injected}</b> bloco(s) extra(s) injetado(s)</span>
      </div>

      {/* Bolhas estilo WhatsApp */}
      <div style={{
        padding: 14, borderRadius: 12,
        background: "linear-gradient(135deg, #075E54 0%, #128C7E 100%)",
        boxShadow: "inset 0 0 40px rgba(0,0,0,0.15)",
      }}>
        <div style={{ fontSize: 10, color: "rgba(255,255,255,0.7)", marginBottom: 8, textAlign: "center" }}>
          Pré-visualização — como o cliente verá
        </div>
        <div style={{ display: "grid", gap: 6 }}>
          {(result.bubbles || []).map((b, i) => (
            <div
              key={i}
              data-testid={`isabella-test-bubble-${i}`}
              style={{
                maxWidth: "78%",
                padding: "8px 11px",
                borderRadius: "10px 10px 10px 2px",
                background: "white",
                color: "#111",
                fontSize: 13,
                lineHeight: 1.4,
                whiteSpace: "pre-wrap",
                boxShadow: "0 1px 1px rgba(0,0,0,0.13)",
                position: "relative",
              }}
            >
              {b}
              <div style={{ fontSize: 9, color: "#999", textAlign: "right", marginTop: 2 }}>
                {new Date(Date.now() + i * 1500).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })} ✓✓
              </div>
            </div>
          ))}
        </div>
      </div>

      <details style={{ fontSize: 11 }}>
        <summary style={{ cursor: "pointer", color: "var(--text-muted)" }}>
          Ver resposta crua do LLM (antes do _split_ai_reply)
        </summary>
        <pre style={{
          marginTop: 6, padding: 10,
          background: "var(--bg-elevated)",
          border: "1px solid var(--border-default)",
          borderRadius: 8,
          color: "var(--text-secondary)",
          fontSize: 11, lineHeight: 1.45,
          whiteSpace: "pre-wrap", wordBreak: "break-word",
          maxHeight: 250, overflow: "auto",
        }}>{result.raw}</pre>
      </details>
    </div>
  );
}
