/* WhatsAppCampaignsPanel.js — Aprovação de campanhas (iter217b)
   Lista drafts pendentes (criados pelo Agente IA ou manuais), permite
   editar/aprovar/rejeitar. Aprovar dispara envio em fila anti-ban.
*/
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import {
  Megaphone, RefreshCw, Send, X, Check, Edit3, AlertCircle,
  Clock, ListChecks, Pause, Sparkles, Trash2,
} from "lucide-react";

const ORACLE = {
  purple: "#4b1d7a", orange: "#f28c28",
  green: "#237a4b", red: "#b42318",
  border: "#e2e8f0",
};

const STATUS_META = {
  pending_approval: { label: "Aguardando aprovação", color: ORACLE.orange,
    icon: Clock },
  dispatching:      { label: "Enviando…", color: "#0891b2",
    icon: Send },
  completed:        { label: "Concluída", color: ORACLE.green,
    icon: Check },
  completed_partial:{ label: "Concluída (parcial)", color: ORACLE.orange,
    icon: AlertCircle },
  rejected:         { label: "Rejeitada", color: ORACLE.red,
    icon: X },
  failed:           { label: "Falhou", color: ORACLE.red,
    icon: AlertCircle },
};

export default function WhatsAppCampaignsPanel() {
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState("pending_approval");
  const [loading, setLoading] = useState(false);
  const [openDetail, setOpenDetail] = useState(null);

  const fetchList = async () => {
    setLoading(true);
    try {
      const params = filter ? `?status=${filter}` : "";
      const r = await api._client.get(`/wa-campaigns/drafts${params}`);
      setItems(r.data.items || []);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  useEffect(() => {
    fetchList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  // Auto-refresh quando algo está disparando
  useEffect(() => {
    const hasDispatching = items.some((i) => i.status === "dispatching");
    if (!hasDispatching) return;
    const t = setInterval(fetchList, 4000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items]);

  return (
    <div data-testid="wa-campaigns-panel" style={{
      display: "flex", flexDirection: "column", gap: 16, padding: "0 4px",
    }}>
      <Header onRefresh={fetchList} loading={loading}
                filter={filter} onFilterChange={setFilter} />

      <div data-testid="campaigns-list" style={{
        display: "flex", flexDirection: "column", gap: 10,
      }}>
        {items.map((c) => (
          <CampaignRow key={c.id} c={c}
                          onOpen={() => setOpenDetail(c)} />
        ))}
        {items.length === 0 && !loading && (
          <EmptyState filter={filter} />
        )}
      </div>

      {openDetail && (
        <DetailModal initial={openDetail}
                       onClose={() => setOpenDetail(null)}
                       onChange={fetchList} />
      )}
    </div>
  );
}

function Header({ onRefresh, loading, filter, onFilterChange }) {
  const tabs = [
    { key: "pending_approval", label: "Aguardando",
      icon: Clock, color: ORACLE.orange },
    { key: "dispatching", label: "Em envio",
      icon: Send, color: "#0891b2" },
    { key: "completed", label: "Concluídas",
      icon: Check, color: ORACLE.green },
    { key: "rejected", label: "Rejeitadas",
      icon: X, color: ORACLE.red },
    { key: "", label: "Todas",
      icon: ListChecks, color: "#64748b" },
  ];
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", flexWrap: "wrap",
      gap: 12, alignItems: "center",
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
            letterSpacing: "-0.02em", color: "var(--text-primary)",
          }}>Campanhas em Massa WhatsApp</h1>
          <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
            Drafts criados pelo Agente IA ou manualmente · Envio em fila
            anti-ban (2-5s entre mensagens)
          </div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {tabs.map((t) => {
          const Icon = t.icon;
          const active = filter === t.key;
          return (
            <button key={t.key || "all"} onClick={() => onFilterChange(t.key)}
                     data-testid={`camp-filter-${t.key || "all"}`}
                     style={{
                       padding: "6px 12px", fontSize: 11, fontWeight: 700,
                       border: `1px solid ${active ? t.color : ORACLE.border}`,
                       borderRadius: 8, cursor: "pointer",
                       background: active ? `${t.color}15` : "white",
                       color: active ? t.color : "#64748b",
                       display: "flex", alignItems: "center", gap: 4,
                     }}>
              <Icon size={11} /> {t.label}
            </button>
          );
        })}
        <button onClick={onRefresh} disabled={loading}
                 data-testid="camp-refresh"
                 style={{
                   padding: "6px 12px", fontSize: 11, fontWeight: 700,
                   border: "none", borderRadius: 8, cursor: "pointer",
                   background: ORACLE.purple, color: "white",
                   display: "flex", alignItems: "center", gap: 4,
                 }}>
            <RefreshCw size={11}
              style={{
                animation: loading ? "spin 1s linear infinite" : "none",
              }} />
            Atualizar
          </button>
      </div>
      <style>{`@keyframes spin { from {transform:rotate(0)} to {transform:rotate(360deg)} }`}</style>
    </div>
  );
}

function CampaignRow({ c, onOpen }) {
  const meta = STATUS_META[c.status]
    || { label: c.status, color: "#64748b", icon: ListChecks };
  const Icon = meta.icon;
  const total = c.recipients_total || (c.subscriber_ids || []).length || 0;
  const sent = c.sent_count || 0;
  const failed = c.failed_count || 0;
  const pct = total ? Math.min(100, Math.round(100 * (sent + failed) / total)) : 0;
  const fromAI = c.created_by === "agent_ia";
  return (
    <div onClick={onOpen} data-testid={`campaign-row-${c.id}`} style={{
      background: "white", border: `1px solid ${ORACLE.border}`,
      borderLeft: `4px solid ${meta.color}`, borderRadius: 10,
      padding: 14, cursor: "pointer", display: "flex",
      flexDirection: "column", gap: 8,
      transition: "background .15s ease",
    }}
    onMouseEnter={(e) => e.currentTarget.style.background = "#fafbfc"}
    onMouseLeave={(e) => e.currentTarget.style.background = "white"}>
      <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "flex-start", gap: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8,
                          flexWrap: "wrap" }}>
            <span style={{ fontSize: 14, fontWeight: 800, color: "#0f172a" }}>
              {c.segment_name}
            </span>
            {fromAI && (
              <span style={{
                background: `${ORACLE.purple}15`, color: ORACLE.purple,
                padding: "2px 7px", borderRadius: 8, fontSize: 9,
                fontWeight: 800, display: "inline-flex",
                alignItems: "center", gap: 3,
              }}>
                <Sparkles size={9} /> Agente IA
              </span>
            )}
            <span style={{
              background: `${meta.color}15`, color: meta.color,
              padding: "2px 8px", borderRadius: 8, fontSize: 9,
              fontWeight: 800, display: "inline-flex",
              alignItems: "center", gap: 3, textTransform: "uppercase",
              letterSpacing: .5,
            }}>
              <Icon size={9} /> {meta.label}
            </span>
          </div>
          <div style={{
            fontSize: 11, color: "#64748b", marginTop: 4,
            display: "-webkit-box", WebkitLineClamp: 1,
            WebkitBoxOrient: "vertical", overflow: "hidden",
          }}>{c.template?.slice(0, 120) || "—"}</div>
        </div>
        <div style={{ textAlign: "right", flexShrink: 0 }}>
          <div style={{ fontSize: 18, fontWeight: 800, color: meta.color }}>
            {total}
          </div>
          <div style={{ fontSize: 9, color: "#64748b", fontWeight: 700,
                          textTransform: "uppercase" }}>destinatários</div>
        </div>
      </div>

      {(c.status === "dispatching" || sent > 0 || failed > 0) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{
            background: "#f1f5f9", borderRadius: 99, height: 6,
            overflow: "hidden",
          }}>
            <div style={{
              width: `${pct}%`, height: "100%", background: meta.color,
              transition: "width .5s ease",
            }} />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between",
                          fontSize: 10, color: "#64748b", fontWeight: 600 }}>
            <span>{pct}% concluído</span>
            <span>
              <span style={{ color: ORACLE.green }}>{sent} enviadas</span>
              {failed > 0 && (
                <span style={{ color: ORACLE.red,
                                  marginLeft: 6 }}>· {failed} falhas</span>
              )}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function EmptyState({ filter }) {
  return (
    <div style={{
      padding: 40, textAlign: "center", background: "white",
      border: `1px dashed ${ORACLE.border}`, borderRadius: 10,
    }}>
      <Megaphone size={36} color="#cbd5e1" style={{ margin: "0 auto" }} />
      <div style={{ fontSize: 14, fontWeight: 700, color: "#475569",
                     marginTop: 12 }}>
        {filter === "pending_approval"
          ? "Nenhuma campanha aguardando aprovação"
          : "Nenhuma campanha nesse filtro"}
      </div>
      <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 6 }}>
        O Agente IA cria drafts automaticamente quando identifica
        oportunidades (cross-sell, retenção, NPS).
      </div>
    </div>
  );
}

// ─────────────────── Detail Modal ───────────────────
function DetailModal({ initial, onClose, onChange }) {
  const [draft, setDraft] = useState(null);
  const [log, setLog] = useState([]);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ template: "", segment_name: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [delayMin, setDelayMin] = useState(2);
  const [delayMax, setDelayMax] = useState(5);

  const load = async () => {
    try {
      const r = await api._client.get(`/wa-campaigns/drafts/${initial.id}`);
      setDraft(r.data);
      setForm({
        template: r.data.template,
        segment_name: r.data.segment_name,
      });
      const lg = await api._client.get(
        `/wa-campaigns/drafts/${initial.id}/log?limit=50`);
      setLog(lg.data.items || []);
    } catch (e) { setErr(e.message); }
  };
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const saveEdit = async () => {
    setBusy(true); setErr("");
    try {
      await api._client.put(`/wa-campaigns/drafts/${initial.id}`, form);
      await load();
      setEditing(false);
      onChange();
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    setBusy(false);
  };

  const approve = async () => {
    if (!window.confirm(
      `Aprovar e enviar para ${draft?.recipients_total} destinatários?`)) {
      return;
    }
    setBusy(true); setErr("");
    try {
      await api._client.post(
        `/wa-campaigns/drafts/${initial.id}/approve`,
        { delay_min_sec: delayMin, delay_max_sec: delayMax });
      onChange();
      onClose();
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    setBusy(false);
  };

  const reject = async () => {
    if (!window.confirm("Rejeitar esta campanha?")) return;
    setBusy(true); setErr("");
    try {
      await api._client.post(
        `/wa-campaigns/drafts/${initial.id}/reject`);
      onChange();
      onClose();
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    setBusy(false);
  };

  if (!draft) {
    return (
      <Backdrop onClose={onClose}>
        <div style={{ padding: 40, color: "#64748b" }}>Carregando…</div>
      </Backdrop>
    );
  }

  const isPending = draft.status === "pending_approval";
  const meta = STATUS_META[draft.status] || { label: draft.status,
    color: "#64748b" };

  return (
    <Backdrop onClose={onClose}>
      <div style={{
        padding: "14px 20px", borderBottom: `1px solid ${ORACLE.border}`,
        display: "flex", justifyContent: "space-between",
        alignItems: "center", gap: 8,
      }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 800,
                         color: ORACLE.purple }}>
            {draft.segment_name}
          </h2>
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 4,
                          display: "flex", gap: 8 }}>
            <span style={{
              background: `${meta.color}15`, color: meta.color,
              padding: "1px 8px", borderRadius: 6, fontWeight: 800,
            }}>{meta.label}</span>
            <span>{draft.recipients_total} destinatários</span>
            {draft.created_by === "agent_ia" && (
              <span>· Criada pelo Agente IA</span>
            )}
          </div>
        </div>
        <button onClick={onClose} data-testid="camp-modal-close" style={{
          background: "none", border: "none", cursor: "pointer",
          color: "#64748b",
        }}>
          <X size={18} />
        </button>
      </div>

      <div style={{ padding: 20, display: "flex",
                      flexDirection: "column", gap: 14 }}>
        {/* Template */}
        <div>
          <div style={{
            display: "flex", justifyContent: "space-between",
            alignItems: "center", marginBottom: 6,
          }}>
            <label style={labelStyle()}>Mensagem (template)</label>
            {isPending && !editing && (
              <button onClick={() => setEditing(true)}
                       data-testid="camp-edit-btn" style={{
                         padding: "4px 10px", fontSize: 10,
                         fontWeight: 700, border: "none",
                         borderRadius: 6, background: `${ORACLE.purple}15`,
                         color: ORACLE.purple, cursor: "pointer",
                         display: "flex", alignItems: "center", gap: 4,
                       }}>
                <Edit3 size={10} /> Editar
              </button>
            )}
          </div>
          {editing ? (
            <>
              <input value={form.segment_name}
                      onChange={(e) => setForm({
                        ...form, segment_name: e.target.value })}
                      data-testid="camp-edit-segment"
                      placeholder="Nome do segmento"
                      style={{ ...input(), marginBottom: 6 }} />
              <textarea value={form.template}
                         onChange={(e) => setForm({
                           ...form, template: e.target.value })}
                         data-testid="camp-edit-template"
                         rows={6}
                         style={{ ...input(), width: "100%",
                                    resize: "vertical",
                                    fontFamily: "inherit" }} />
              <div style={{ display: "flex", gap: 6, marginTop: 6,
                              justifyContent: "flex-end" }}>
                <button onClick={() => setEditing(false)} style={btnSec()}>
                  Cancelar
                </button>
                <button onClick={saveEdit} disabled={busy}
                         data-testid="camp-edit-save" style={btn()}>
                  Salvar
                </button>
              </div>
            </>
          ) : (
            <div style={{
              background: "#fafbfc", border: `1px solid ${ORACLE.border}`,
              borderRadius: 6, padding: "10px 14px", fontSize: 13,
              color: "#334155", lineHeight: 1.5, whiteSpace: "pre-wrap",
            }}>{draft.template}</div>
          )}
        </div>

        {/* Preview destinatários */}
        {draft.recipients_preview?.length > 0 && (
          <div>
            <label style={labelStyle()}>
              Primeiros destinatários (até 30)
            </label>
            <div style={{
              background: "#fafbfc", border: `1px solid ${ORACLE.border}`,
              borderRadius: 6, maxHeight: 160, overflow: "auto",
            }}>
              {draft.recipients_preview.map((s) => (
                <div key={s.id} style={{
                  display: "flex", justifyContent: "space-between",
                  padding: "5px 10px", fontSize: 11,
                  borderBottom: `1px solid ${ORACLE.border}`,
                  color: "#475569",
                }}>
                  <span>{s.name || s.id}</span>
                  <span style={{ color: "#94a3b8" }}>{s.phone || "—"}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Aprovar e enviar */}
        {isPending && (
          <div style={{
            background: `${ORACLE.orange}10`,
            border: `1px solid ${ORACLE.orange}40`,
            borderRadius: 8, padding: 14,
          }}>
            <div style={{ fontSize: 11, fontWeight: 800, color: ORACLE.orange,
                            textTransform: "uppercase", letterSpacing: .5,
                            marginBottom: 8 }}>
              Aprovar e disparar envio em fila
            </div>
            <div style={{ display: "flex", gap: 10, alignItems: "center",
                            flexWrap: "wrap" }}>
              <span style={{ fontSize: 11, color: "#475569" }}>
                Delay anti-ban entre msgs:
              </span>
              <input type="number" min={1} max={30} value={delayMin}
                      data-testid="camp-delay-min"
                      onChange={(e) => setDelayMin(Number(e.target.value))}
                      style={{ ...input(), width: 70, padding: "4px 8px" }} />
              <span style={{ fontSize: 11 }}>a</span>
              <input type="number" min={1} max={60} value={delayMax}
                      data-testid="camp-delay-max"
                      onChange={(e) => setDelayMax(Number(e.target.value))}
                      style={{ ...input(), width: 70, padding: "4px 8px" }} />
              <span style={{ fontSize: 11, color: "#475569" }}>segundos</span>
            </div>
          </div>
        )}

        {/* Logs */}
        {log.length > 0 && (
          <div>
            <label style={labelStyle()}>Últimos envios</label>
            <div style={{
              background: "#fafbfc", border: `1px solid ${ORACLE.border}`,
              borderRadius: 6, maxHeight: 180, overflow: "auto", fontSize: 11,
            }}>
              {log.map((l) => (
                <div key={l.id} style={{
                  padding: "5px 10px", display: "flex",
                  justifyContent: "space-between",
                  borderBottom: `1px solid ${ORACLE.border}`,
                  color: l.ok ? "#475569" : ORACLE.red,
                }}>
                  <span>{l.ok ? "✓" : "✗"} {l.phone || l.subscriber_id}</span>
                  <span style={{ color: "#94a3b8" }}>
                    {l.error || new Date(l.sent_at).toLocaleTimeString("pt-BR")}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {err && (
          <div data-testid="camp-modal-error" style={{
            background: "#fef2f2", color: ORACLE.red, padding: "8px 12px",
            borderRadius: 6, fontSize: 12, fontWeight: 600,
          }}>{err}</div>
        )}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end",
                        flexWrap: "wrap" }}>
          {isPending && (
            <>
              <button onClick={reject} disabled={busy}
                       data-testid="camp-reject-btn"
                       style={{
                         padding: "8px 14px", fontSize: 12, fontWeight: 700,
                         border: `1px solid ${ORACLE.red}`, borderRadius: 8,
                         background: "white", color: ORACLE.red,
                         cursor: "pointer", display: "flex",
                         alignItems: "center", gap: 6,
                       }}>
                <Trash2 size={13} /> Rejeitar
              </button>
              <button onClick={approve} disabled={busy}
                       data-testid="camp-approve-btn"
                       style={{
                         padding: "8px 18px", fontSize: 12, fontWeight: 700,
                         border: "none", borderRadius: 8,
                         background: ORACLE.green, color: "white",
                         cursor: "pointer", opacity: busy ? 0.6 : 1,
                         display: "flex", alignItems: "center", gap: 6,
                       }}>
                <Send size={13} />
                Aprovar e enviar ({draft.recipients_total})
              </button>
            </>
          )}
          {!isPending && (
            <button onClick={onClose} style={btnSec()}>Fechar</button>
          )}
        </div>
      </div>
    </Backdrop>
  );
}

function Backdrop({ onClose, children }) {
  return (
    <div onClick={onClose} data-testid="camp-modal-backdrop" style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,0.6)",
      zIndex: 1000, display: "flex", alignItems: "center",
      justifyContent: "center", padding: 20,
    }}>
      <div onClick={(e) => e.stopPropagation()} data-testid="camp-modal"
            style={{
              background: "white", borderRadius: 12, width: "100%",
              maxWidth: 680, maxHeight: "90vh", overflow: "auto",
            }}>
        {children}
      </div>
    </div>
  );
}

function labelStyle() {
  return {
    fontSize: 11, fontWeight: 700, color: "#475569",
    textTransform: "uppercase", letterSpacing: .4, display: "block",
  };
}
function input() {
  return {
    padding: "8px 12px", fontSize: 13,
    border: `1px solid ${ORACLE.border}`, borderRadius: 6,
    background: "white", color: "#0f172a", outline: "none",
    width: "100%",
  };
}
function btn() {
  return {
    padding: "8px 16px", fontSize: 12, fontWeight: 700, border: "none",
    borderRadius: 8, background: ORACLE.purple, color: "white",
    cursor: "pointer",
  };
}
function btnSec() {
  return {
    padding: "8px 16px", fontSize: 12, fontWeight: 700,
    border: `1px solid ${ORACLE.border}`, borderRadius: 8,
    background: "white", color: "#64748b", cursor: "pointer",
  };
}

export { Pause };
