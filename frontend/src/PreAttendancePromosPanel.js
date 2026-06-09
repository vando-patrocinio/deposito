/* PreAttendancePromosPanel.js — Propaganda Pré-Atendimento (iter217a)
   CRUD + upload imagem + filtros de alvo + IA on/off + estatísticas.
   Design Oracle.
*/
import React, { useEffect, useRef, useState } from "react";
import { api } from "@/api";
import {
  Megaphone, Plus, Trash2, Edit3, ImageIcon, BarChart3, Power,
  X, Sparkles, RefreshCw, Send, Check,
} from "lucide-react";

const ORACLE = {
  purple: "#4b1d7a", orange: "#f28c28",
  green: "#237a4b", red: "#b42318",
  border: "#e2e8f0",
};

const FILTER_LABELS = {
  all: "Todos os clientes",
  active: "Apenas ativos",
  inactive: "Apenas inativos",
  inadimplentes: "Apenas inadimplentes",
  by_plan: "Por plano específico",
};

export default function PreAttendancePromosPanel() {
  const [items, setItems] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(null);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [r1, r2] = await Promise.all([
        api._client.get("/pre-attendance/promos"),
        api._client.get("/pre-attendance/stats"),
      ]);
      setItems(r1.data.items || []);
      setStats(r2.data);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchAll();
  }, []);

  const toggle = async (id) => {
    await api._client.post(`/pre-attendance/promos/${id}/toggle`);
    fetchAll();
  };
  const remove = async (id) => {
    if (!window.confirm("Remover esta propaganda?")) return;
    await api._client.delete(`/pre-attendance/promos/${id}`);
    fetchAll();
  };

  return (
    <div data-testid="pre-attendance-panel" style={{
      display: "flex", flexDirection: "column", gap: 16, padding: "0 4px",
    }}>
      <Header onCreate={() => setEditing({})} onRefresh={fetchAll}
                loading={loading} />

      {stats && <StatsBar stats={stats} />}

      <div data-testid="promos-grid" style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
        gap: 14,
      }}>
        {items.map((p) => (
          <PromoCard key={p.id} promo={p}
                      onEdit={() => setEditing(p)}
                      onToggle={() => toggle(p.id)}
                      onDelete={() => remove(p.id)} />
        ))}
        {items.length === 0 && !loading && (
          <EmptyState onCreate={() => setEditing({})} />
        )}
      </div>

      {editing !== null && (
        <PromoModal initial={editing}
                     onClose={() => setEditing(null)}
                     onSaved={() => { setEditing(null); fetchAll(); }} />
      )}
    </div>
  );
}

// ─────────────────── Header ───────────────────
function Header({ onCreate, onRefresh, loading }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      flexWrap: "wrap", gap: 12,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{
          width: 42, height: 42, borderRadius: 10,
          background: `linear-gradient(135deg, ${ORACLE.purple}, #6d28d9)`,
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: "0 4px 12px rgba(75, 29, 122, .3)",
        }}>
          <Megaphone size={22} color="white" />
        </div>
        <div>
          <h1 style={{
            fontSize: 22, fontWeight: 800, margin: 0,
            color: "var(--text-primary)", letterSpacing: "-0.02em",
          }}>Propaganda Pré-Atendimento</h1>
          <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
            Mensagem inicial automática · IA escolhe a melhor por perfil ·
            Cooldown 24h por cliente
          </div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={onRefresh} disabled={loading}
                 data-testid="prop-refresh" style={{
                   padding: "8px 14px", fontSize: 12, fontWeight: 700,
                   border: `1px solid ${ORACLE.border}`, borderRadius: 8,
                   cursor: "pointer", background: "white",
                   color: "#64748b", display: "flex",
                   alignItems: "center", gap: 6,
                 }}>
          <RefreshCw size={13}
            style={{
              animation: loading ? "spin 1s linear infinite" : "none",
            }} />
          Atualizar
        </button>
        <button onClick={onCreate} data-testid="prop-create-btn"
                 style={{
                   padding: "8px 16px", fontSize: 12, fontWeight: 700,
                   border: "none", borderRadius: 8, cursor: "pointer",
                   background: ORACLE.purple, color: "white",
                   display: "flex", alignItems: "center", gap: 6,
                 }}>
          <Plus size={14} /> Nova Propaganda
        </button>
      </div>
      <style>{`@keyframes spin { from {transform:rotate(0)} to {transform:rotate(360deg)} }`}</style>
    </div>
  );
}

// ─────────────────── Stats Bar ───────────────────
function StatsBar({ stats }) {
  const cards = [
    { label: "Propagandas", value: stats.total_promos, color: ORACLE.purple },
    { label: "Ativas", value: stats.active_promos, color: ORACLE.green },
    { label: "Disparos totais", value: stats.total_sent,
      color: ORACLE.orange },
    { label: "Respostas", value: stats.total_replied, color: "#1e40af" },
    { label: "Taxa de resposta", value: `${stats.reply_rate_pct}%`,
      color: ORACLE.green },
    { label: "Escolhas pela IA", value: stats.ai_picks,
      color: "#7c3aed" },
  ];
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
      gap: 10,
    }}>
      {cards.map((c) => (
        <div key={c.label} style={{
          background: "#fafbfc", border: `1px solid ${ORACLE.border}`,
          borderTop: `3px solid ${c.color}`, borderRadius: 8, padding: 10,
        }}>
          <div style={{ fontSize: 18, fontWeight: 800, color: c.color }}>
            {c.value ?? "—"}
          </div>
          <div style={{
            fontSize: 9, color: "#64748b", textTransform: "uppercase",
            letterSpacing: .5, fontWeight: 700, marginTop: 2,
          }}>{c.label}</div>
        </div>
      ))}
    </div>
  );
}

// ─────────────────── Promo Card ───────────────────
function PromoCard({ promo, onEdit, onToggle, onDelete }) {
  const active = !!promo.active;
  const reply = promo.stats_sent
    ? ((promo.stats_replied || 0) / promo.stats_sent * 100).toFixed(1)
    : "0.0";
  return (
    <div data-testid={`promo-card-${promo.id}`} style={{
      background: "white", border: `1px solid ${ORACLE.border}`,
      borderLeft: `4px solid ${active ? ORACLE.green : "#94a3b8"}`,
      borderRadius: 10, padding: 14, display: "flex",
      flexDirection: "column", gap: 10,
      opacity: active ? 1 : 0.7,
    }}>
      <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
        {promo.image_url ? (
          <img src={promo.image_url} alt=""
                style={{
                  width: 56, height: 56, objectFit: "cover",
                  borderRadius: 6, border: `1px solid ${ORACLE.border}`,
                }} />
        ) : (
          <div style={{
            width: 56, height: 56, borderRadius: 6,
            background: "#f1f5f9", display: "flex",
            alignItems: "center", justifyContent: "center",
          }}>
            <ImageIcon size={20} color="#94a3b8" />
          </div>
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 14, fontWeight: 800, color: "#0f172a",
            whiteSpace: "nowrap", overflow: "hidden",
            textOverflow: "ellipsis",
          }}>{promo.title}</div>
          <div style={{
            fontSize: 11, color: "#64748b", marginTop: 2,
            display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center",
          }}>
            <span>{FILTER_LABELS[promo.target_filter]
                     || promo.target_filter}</span>
            <span>·</span>
            <span>peso {promo.weight}</span>
            {promo.ai_enabled && (
              <span style={{
                background: `${ORACLE.purple}15`, color: ORACLE.purple,
                padding: "1px 6px", borderRadius: 6,
                fontSize: 9, fontWeight: 800,
                display: "flex", alignItems: "center", gap: 3,
              }}>
                <Sparkles size={9} /> IA
              </span>
            )}
          </div>
        </div>
      </div>

      <div style={{
        fontSize: 12, color: "#334155", lineHeight: 1.5,
        background: "#fafbfc", borderRadius: 6, padding: "8px 10px",
        border: `1px solid ${ORACLE.border}`, maxHeight: 70,
        overflow: "hidden", display: "-webkit-box",
        WebkitLineClamp: 3, WebkitBoxOrient: "vertical",
      }}>{promo.message_text}</div>

      <div style={{
        display: "flex", gap: 6, fontSize: 10, fontWeight: 700,
        color: "#64748b", borderTop: `1px dashed ${ORACLE.border}`,
        paddingTop: 8,
      }}>
        <span><Send size={9} style={{ marginRight: 3 }} />
          {promo.stats_sent || 0} envios</span>
        <span>·</span>
        <span style={{
          color: parseFloat(reply) > 20 ? ORACLE.green : "#64748b",
        }}>↩ {reply}% resposta</span>
      </div>

      <div style={{ display: "flex", gap: 6 }}>
        <button onClick={onToggle}
                 data-testid={`promo-toggle-${promo.id}`}
                 style={{
                   flex: 1, padding: "6px 10px", fontSize: 11,
                   fontWeight: 700, border: "none", borderRadius: 6,
                   cursor: "pointer", display: "flex",
                   alignItems: "center", justifyContent: "center", gap: 4,
                   background: active ? `${ORACLE.green}15` : "#fafbfc",
                   color: active ? ORACLE.green : "#64748b",
                 }}>
          <Power size={11} /> {active ? "Ativa" : "Pausada"}
        </button>
        <button onClick={onEdit}
                 data-testid={`promo-edit-${promo.id}`}
                 style={{
                   padding: "6px 10px", fontSize: 11, fontWeight: 700,
                   border: `1px solid ${ORACLE.border}`, borderRadius: 6,
                   cursor: "pointer", background: "white",
                   color: ORACLE.purple, display: "flex",
                   alignItems: "center", gap: 4,
                 }}>
          <Edit3 size={11} /> Editar
        </button>
        <button onClick={onDelete}
                 data-testid={`promo-delete-${promo.id}`}
                 style={{
                   padding: "6px 10px", fontSize: 11, fontWeight: 700,
                   border: `1px solid ${ORACLE.border}`, borderRadius: 6,
                   cursor: "pointer", background: "white",
                   color: ORACLE.red, display: "flex",
                   alignItems: "center", gap: 4,
                 }}>
          <Trash2 size={11} />
        </button>
      </div>
    </div>
  );
}

function EmptyState({ onCreate }) {
  return (
    <div style={{
      gridColumn: "1 / -1", padding: 40, textAlign: "center",
      background: "white", border: `1px dashed ${ORACLE.border}`,
      borderRadius: 10,
    }}>
      <Megaphone size={36} color="#cbd5e1" style={{ margin: "0 auto" }} />
      <div style={{ fontSize: 14, fontWeight: 700, marginTop: 12,
                     color: "#475569" }}>
        Nenhuma propaganda cadastrada
      </div>
      <div style={{ fontSize: 12, color: "#94a3b8", margin: "6px 0 14px" }}>
        Crie sua primeira propaganda para começar a engajar clientes
        já cadastrados quando eles abrirem conversa.
      </div>
      <button onClick={onCreate} data-testid="prop-empty-create"
               style={{
                 padding: "8px 18px", fontSize: 12, fontWeight: 700,
                 border: "none", borderRadius: 8,
                 background: ORACLE.purple, color: "white",
                 cursor: "pointer", display: "inline-flex",
                 alignItems: "center", gap: 6,
               }}>
        <Plus size={14} /> Criar Propaganda
      </button>
    </div>
  );
}

// ─────────────────── Modal ───────────────────
function PromoModal({ initial, onClose, onSaved }) {
  const isEdit = !!initial?.id;
  const [form, setForm] = useState({
    title: initial?.title || "",
    message_text: initial?.message_text || "",
    image_url: initial?.image_url || "",
    target_filter: initial?.target_filter || "all",
    target_plan_ids: initial?.target_plan_ids || [],
    weight: initial?.weight ?? 1,
    ai_enabled: initial?.ai_enabled ?? true,
    active: initial?.active ?? true,
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const fileRef = useRef(null);

  const handleUpload = async (file) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const b64 = reader.result;
        const r = await api._client.post(
          "/pre-attendance/upload-image",
          { image_b64: b64, filename: file.name });
        setForm((f) => ({ ...f, image_url: r.data.url }));
      } catch (e) {
        setErr(e?.response?.data?.detail || e.message);
      }
    };
    reader.readAsDataURL(file);
  };

  const save = async () => {
    setSaving(true); setErr("");
    try {
      if (isEdit) {
        await api._client.put(`/pre-attendance/promos/${initial.id}`, form);
      } else {
        await api._client.post("/pre-attendance/promos", form);
      }
      onSaved();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setSaving(false);
  };

  return (
    <div onClick={onClose} data-testid="promo-modal-backdrop" style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,0.6)",
      zIndex: 1000, display: "flex", alignItems: "center",
      justifyContent: "center", padding: 20,
    }}>
      <div onClick={(e) => e.stopPropagation()}
            data-testid="promo-modal" style={{
        background: "white", borderRadius: 12, width: "100%",
        maxWidth: 640, maxHeight: "90vh", overflow: "auto",
      }}>
        <div style={{
          padding: "16px 20px", borderBottom: `1px solid ${ORACLE.border}`,
          display: "flex", justifyContent: "space-between",
          alignItems: "center",
        }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 800,
                         color: ORACLE.purple }}>
            {isEdit ? "Editar propaganda" : "Nova propaganda"}
          </h2>
          <button onClick={onClose} data-testid="promo-modal-close"
                   style={{
                     background: "none", border: "none", cursor: "pointer",
                     color: "#64748b", padding: 4,
                   }}>
            <X size={18} />
          </button>
        </div>

        <div style={{ padding: 20, display: "flex",
                       flexDirection: "column", gap: 14 }}>
          <Field label="Título">
            <input value={form.title} data-testid="promo-input-title"
                    onChange={(e) => setForm({ ...form, title: e.target.value })}
                    placeholder="Ex: Upgrade Premium 50% OFF"
                    style={input()} />
          </Field>

          <Field label="Mensagem (use {primeiro_nome}, {nome}, {plano})">
            <textarea value={form.message_text}
                       data-testid="promo-input-message"
                       onChange={(e) => setForm({
                         ...form, message_text: e.target.value })}
                       rows={5}
                       placeholder="Olá {primeiro_nome}! Vimos que você tem o plano {plano}. Que tal turbinar?"
                       style={{ ...input(), resize: "vertical",
                                  fontFamily: "inherit" }} />
          </Field>

          <Field label="Imagem (opcional, anexada à mensagem)">
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              {form.image_url ? (
                <img src={form.image_url} alt=""
                      style={{ width: 70, height: 70, objectFit: "cover",
                                 borderRadius: 6, border: `1px solid ${ORACLE.border}` }} />
              ) : (
                <div style={{
                  width: 70, height: 70, borderRadius: 6, background: "#f1f5f9",
                  display: "flex", alignItems: "center",
                  justifyContent: "center",
                }}><ImageIcon size={22} color="#94a3b8" /></div>
              )}
              <div style={{ display: "flex", flexDirection: "column",
                              gap: 6, flex: 1 }}>
                <input type="file" ref={fileRef} accept="image/*"
                        data-testid="promo-input-image-file"
                        onChange={(e) => handleUpload(e.target.files?.[0])}
                        style={{ fontSize: 12 }} />
                {form.image_url && (
                  <button onClick={() => setForm({ ...form, image_url: "" })}
                           style={{
                             padding: "4px 10px", fontSize: 11,
                             fontWeight: 700, border: "none",
                             borderRadius: 6, background: "#fef2f2",
                             color: ORACLE.red, cursor: "pointer",
                             alignSelf: "flex-start",
                           }}>Remover imagem</button>
                )}
              </div>
            </div>
          </Field>

          <div style={{ display: "grid",
                          gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Field label="Alvo">
              <select value={form.target_filter}
                       data-testid="promo-input-filter"
                       onChange={(e) => setForm({
                         ...form, target_filter: e.target.value })}
                       style={input()}>
                {Object.entries(FILTER_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </Field>
            <Field label="Peso (prioridade no sorteio)">
              <input type="number" min={1} max={100} value={form.weight}
                      data-testid="promo-input-weight"
                      onChange={(e) => setForm({
                        ...form, weight: Number(e.target.value) || 1 })}
                      style={input()} />
            </Field>
          </div>

          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            <Toggle label="Usar IA para escolher" testid="promo-input-ai"
                     value={form.ai_enabled}
                     onChange={(v) => setForm({ ...form, ai_enabled: v })} />
            <Toggle label="Ativa" testid="promo-input-active"
                     value={form.active}
                     onChange={(v) => setForm({ ...form, active: v })} />
          </div>

          {err && (
            <div data-testid="promo-modal-error" style={{
              background: "#fef2f2", color: ORACLE.red,
              padding: "8px 12px", borderRadius: 6, fontSize: 12,
              fontWeight: 600,
            }}>{err}</div>
          )}

          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end",
                          marginTop: 6 }}>
            <button onClick={onClose} data-testid="promo-modal-cancel"
                     style={{
                       padding: "8px 16px", fontSize: 12, fontWeight: 700,
                       border: `1px solid ${ORACLE.border}`, borderRadius: 8,
                       background: "white", color: "#64748b",
                       cursor: "pointer",
                     }}>Cancelar</button>
            <button onClick={save} disabled={saving}
                     data-testid="promo-modal-save"
                     style={{
                       padding: "8px 18px", fontSize: 12, fontWeight: 700,
                       border: "none", borderRadius: 8,
                       background: ORACLE.purple, color: "white",
                       cursor: "pointer", opacity: saving ? 0.6 : 1,
                       display: "flex", alignItems: "center", gap: 6,
                     }}>
              <Check size={13} />
              {saving ? "Salvando…" : (isEdit ? "Salvar" : "Criar")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <label style={{
        fontSize: 11, fontWeight: 700, color: "#475569",
        textTransform: "uppercase", letterSpacing: .4,
      }}>{label}</label>
      {children}
    </div>
  );
}

function input() {
  return {
    padding: "8px 12px", fontSize: 13,
    border: `1px solid ${ORACLE.border}`, borderRadius: 6,
    background: "white", color: "#0f172a", outline: "none",
    fontFamily: "inherit",
  };
}

function Toggle({ label, value, onChange, testid }) {
  return (
    <label data-testid={testid} style={{
      display: "flex", alignItems: "center", gap: 6, cursor: "pointer",
      fontSize: 12, fontWeight: 600, color: "#334155",
    }}>
      <input type="checkbox" checked={!!value}
              onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

// Re-export como ícone usado fora — evita warning unused
export { BarChart3 };
