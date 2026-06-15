/**
 * SubscriberInteractionsDrawer.jsx — Drawer 360° por subscriber (P0 CTO 2026-02).
 *
 * Timeline unificada de todos os contatos com o cliente: WhatsApp, tickets,
 * Lousa, Isabella, handoffs, notas manuais. Resolve fragmentação histórica.
 */
import React, { useEffect, useState } from "react";
import {
  X, MessageCircle, Ticket, Wrench, Bot, Phone, Mail, UserCheck,
  StickyNote, ShieldAlert, Send, Clock, Filter, History,
} from "lucide-react";
import { api } from "@/api";

const CHANNEL_META = {
  whatsapp: { icon: MessageCircle, color: "#22c55e", label: "WhatsApp" },
  ticket: { icon: Ticket, color: "#3b82f6", label: "Ticket" },
  lousa: { icon: Wrench, color: "#a855f7", label: "Lousa" },
  isabella: { icon: Bot, color: "#ec4899", label: "Isabella" },
  phone: { icon: Phone, color: "#f59e0b", label: "Telefone" },
  email: { icon: Mail, color: "#0ea5e9", label: "Email" },
  handoff: { icon: ShieldAlert, color: "#ef4444", label: "Handoff" },
  cto: { icon: UserCheck, color: "#0f172a", label: "CTO" },
  note: { icon: StickyNote, color: "#64748b", label: "Nota" },
};

const DateBR = (iso) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", {
      dateStyle: "short", timeStyle: "short",
    });
  } catch { return iso; }
};

export default function SubscriberInteractionsDrawer({ subscriberId, onClose }) {
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [showNoteForm, setShowNoteForm] = useState(false);
  const [showHandoffForm, setShowHandoffForm] = useState(false);
  const [noteText, setNoteText] = useState("");
  const [handoffReason, setHandoffReason] = useState("");
  const [handoffUrgency, setHandoffUrgency] = useState("normal");

  const load = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api.interactions360(subscriberId,
        filter ? { channel: filter } : {});
      setData(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };
  useEffect(() => { if (subscriberId) load(); }, [subscriberId, filter]);  // eslint-disable-line

  const addNote = async () => {
    if (!noteText.trim() || noteText.trim().length < 3) return;
    try {
      await api.interactionsCreate({
        subscriber_id: subscriberId, channel: "note",
        direction: "internal", content_text: noteText.trim(),
        tags: ["manual"],
      });
      setNoteText(""); setShowNoteForm(false);
      load();
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
  };

  const triggerHandoff = async () => {
    if (!handoffReason.trim() || handoffReason.trim().length < 3) return;
    try {
      await api.interactionsHandoff({
        subscriber_id: subscriberId,
        reason: handoffReason.trim(),
        urgency: handoffUrgency,
      });
      setHandoffReason(""); setShowHandoffForm(false);
      load();
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
  };

  return (
    <div data-testid="interactions-drawer-overlay" style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,.55)",
      zIndex: 9500, display: "flex", justifyContent: "flex-end",
    }} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div data-testid="interactions-drawer" style={{
        width: 560, maxWidth: "100vw", height: "100vh", background: "white",
        boxShadow: "-6px 0 24px rgba(0,0,0,.15)", display: "flex",
        flexDirection: "column", overflow: "hidden",
      }}>
        {/* Header */}
        <div style={{ padding: 16, borderBottom: "1px solid #e2e8f0",
          background: "#f8fafc" }}>
          <div style={{ display: "flex", justifyContent: "space-between",
            alignItems: "flex-start", gap: 10 }}>
            <div>
              <div style={{ display: "inline-flex", alignItems: "center",
                gap: 8, color: "#0f172a", fontWeight: 700, fontSize: 16 }}>
                <History size={18} /> Histórico 360°
              </div>
              <div data-testid="drawer-sub-name" style={{
                color: "#475569", fontSize: 13, marginTop: 2 }}>
                {data?.subscriber?.name || "—"}
                <span style={{ color: "#94a3b8", marginLeft: 6 }}>
                  · {data?.subscriber?.plan_name || ""}
                </span>
              </div>
            </div>
            <button data-testid="drawer-close" onClick={onClose}
              style={{ background: "transparent", border: 0, cursor: "pointer",
                color: "#64748b", fontSize: 22 }}><X size={20} /></button>
          </div>

          {/* Counts by channel */}
          {data?.counts_by_channel && (
            <div data-testid="drawer-channel-counts" style={{
              display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10,
            }}>
              <button onClick={() => setFilter(null)}
                data-testid="drawer-filter-all"
                style={{
                  padding: "4px 10px", borderRadius: 999, fontSize: 11,
                  fontWeight: 600, cursor: "pointer",
                  border: `1px solid ${filter ? "#cbd5e1" : "#ff6b1a"}`,
                  background: filter ? "white" : "#fff5ed",
                  color: filter ? "#475569" : "#ff6b1a",
                }}>
                <Filter size={10} style={{ verticalAlign: "middle" }}/> Todos ({data.count})
              </button>
              {Object.entries(data.counts_by_channel).map(([ch, n]) => {
                const m = CHANNEL_META[ch] || CHANNEL_META.note;
                const Icon = m.icon;
                const active = filter === ch;
                return (
                  <button key={ch} data-testid={`drawer-filter-${ch}`}
                    onClick={() => setFilter(active ? null : ch)}
                    style={{
                      padding: "4px 10px", borderRadius: 999, fontSize: 11,
                      fontWeight: 600, cursor: "pointer",
                      border: `1px solid ${active ? m.color : "#cbd5e1"}`,
                      background: active ? `${m.color}15` : "white",
                      color: active ? m.color : "#475569",
                      display: "inline-flex", alignItems: "center", gap: 4,
                    }}>
                    <Icon size={10} /> {m.label} ({n})
                  </button>
                );
              })}
            </div>
          )}

          {/* Actions */}
          <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
            <button data-testid="drawer-add-note-btn"
              onClick={() => { setShowNoteForm((s) => !s); setShowHandoffForm(false); }}
              style={btnSm}>
              <StickyNote size={12} /> Adicionar nota
            </button>
            <button data-testid="drawer-handoff-btn"
              onClick={() => { setShowHandoffForm((s) => !s); setShowNoteForm(false); }}
              style={{ ...btnSm, color: "#ef4444", borderColor: "#fecaca" }}>
              <ShieldAlert size={12} /> Disparar handoff
            </button>
          </div>

          {showNoteForm && (
            <div data-testid="drawer-note-form"
              style={{ marginTop: 10, padding: 10,
                border: "1px solid #cbd5e1", borderRadius: 8 }}>
              <textarea
                data-testid="drawer-note-text" value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                placeholder="Escreva uma nota interna sobre este cliente…"
                rows={3}
                style={{ width: "100%", padding: 8, fontSize: 12,
                  borderRadius: 6, border: "1px solid #e2e8f0",
                  resize: "vertical" }} />
              <button data-testid="drawer-note-save" onClick={addNote}
                style={{ ...btnSm, marginTop: 6,
                  background: "#0f172a", color: "white",
                  borderColor: "#0f172a" }}>
                <Send size={11} /> Salvar
              </button>
            </div>
          )}
          {showHandoffForm && (
            <div data-testid="drawer-handoff-form"
              style={{ marginTop: 10, padding: 10,
                border: "1px solid #fecaca", borderRadius: 8,
                background: "#fef2f2" }}>
              <input data-testid="drawer-handoff-reason"
                value={handoffReason}
                onChange={(e) => setHandoffReason(e.target.value)}
                placeholder="Motivo (ex: cliente irritado, pedido fora de regra)"
                style={{ width: "100%", padding: 8, fontSize: 12,
                  borderRadius: 6, border: "1px solid #fecaca",
                  marginBottom: 6 }} />
              <select data-testid="drawer-handoff-urgency"
                value={handoffUrgency}
                onChange={(e) => setHandoffUrgency(e.target.value)}
                style={{ padding: 6, fontSize: 12, borderRadius: 6,
                  border: "1px solid #fecaca", marginRight: 6 }}>
                <option value="low">Baixa</option>
                <option value="normal">Normal</option>
                <option value="high">Alta</option>
              </select>
              <button data-testid="drawer-handoff-confirm"
                onClick={triggerHandoff}
                style={{ ...btnSm,
                  background: "#ef4444", color: "white",
                  borderColor: "#ef4444" }}>
                <ShieldAlert size={11} /> Disparar
              </button>
            </div>
          )}
        </div>

        {/* Timeline */}
        <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
          {err && <div style={{
            background: "#fee2e2", color: "#991b1b", padding: 10,
            borderRadius: 8, fontSize: 12, marginBottom: 10,
          }}>{err}</div>}
          {busy && <div style={{ color: "#64748b", fontSize: 12 }}>Carregando…</div>}
          {!busy && data && data.timeline.length === 0 && (
            <div data-testid="drawer-empty" style={{
              textAlign: "center", color: "#94a3b8", padding: 40,
              fontSize: 13,
            }}>
              Nenhuma interação registrada ainda.<br/>
              Toda nova conversa, ticket ou handoff aparecerá aqui.
            </div>
          )}
          {!busy && data && data.timeline.map((it) => {
            const m = CHANNEL_META[it.channel] || CHANNEL_META.note;
            const Icon = m.icon;
            const isOutbound = it.direction === "out";
            return (
              <div key={it.id} data-testid={`timeline-item-${it.id}`}
                style={{ display: "flex", gap: 10, marginBottom: 14 }}>
                <div style={{
                  width: 32, height: 32, borderRadius: 8,
                  background: `${m.color}20`,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  flexShrink: 0,
                }}>
                  <Icon size={16} color={m.color} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "baseline", gap: 6, flexWrap: "wrap" }}>
                    <strong style={{ fontSize: 12, color: m.color }}>
                      {m.label}
                      {it.direction && it.direction !== "internal" && (
                        <span style={{ marginLeft: 6, fontSize: 10,
                          color: isOutbound ? "#3b82f6" : "#22c55e",
                          fontWeight: 600 }}>
                          · {isOutbound ? "→ saiu" : "← entrou"}
                        </span>
                      )}
                    </strong>
                    <span style={{ fontSize: 10, color: "#94a3b8",
                      display: "inline-flex", alignItems: "center", gap: 3 }}>
                      <Clock size={9} /> {DateBR(it.occurred_at)}
                    </span>
                  </div>
                  {it.content_text && (
                    <div style={{ fontSize: 13, color: "#0f172a",
                      marginTop: 3, whiteSpace: "pre-wrap",
                      wordBreak: "break-word" }}>
                      {it.content_text}
                    </div>
                  )}
                  <div style={{ fontSize: 10, color: "#94a3b8",
                    marginTop: 4 }}>
                    {it.actor}
                    {it.tags && it.tags.length > 0 && (
                      <span style={{ marginLeft: 6 }}>
                        {it.tags.map((t) => (
                          <span key={t} style={{
                            background: "#f1f5f9", color: "#475569",
                            padding: "1px 6px", borderRadius: 4,
                            fontSize: 9, marginLeft: 3,
                          }}>{t}</span>
                        ))}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

const btnSm = {
  padding: "5px 10px", fontSize: 11, fontWeight: 600,
  borderRadius: 6, cursor: "pointer",
  background: "white", color: "#475569",
  border: "1px solid #cbd5e1",
  display: "inline-flex", alignItems: "center", gap: 4,
};
