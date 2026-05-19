import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import {
  Radio, AlertTriangle, CheckCircle2, RefreshCw, Loader2, Activity, Users,
  Clock, MailCheck, MailX, Send, Inbox, Settings2, FileText, Eye, EyeOff,
} from "lucide-react";

/* =============================================================
   SmartOLT AI — monitoramento autônomo da rede com IA (2026).
   Threshold dinâmico: ≥10 ONUs em LOS  OU  ≥50% do PON (o que vier 1º).
   Auto-refresh a cada 30s.
   Modo ATIVO: rascunhos aprovados pelo humano antes de enviar.
   Co-piloto: notas internas no chat (cliente nunca vê).
============================================================= */
export default function SmartOltAiPanel() {
  const [summary, setSummary] = useState(null);
  const [active, setActive] = useState([]);
  const [recent, setRecent] = useState([]);
  const [drafts, setDrafts] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [showTemplates, setShowTemplates] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [s, a, r, d] = await Promise.all([
        api.smartoltAiSummary(),
        api.smartoltAiActiveOutages(),
        api.smartoltAiRecentOutages(24),
        api.smartoltAiDrafts({ status: "pending" }),
      ]);
      setSummary(s);
      setActive(a.items || []);
      setRecent(r.items || []);
      setDrafts(d.items || []);
      setErr(null);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  }, []);

  useEffect(() => {
    reload();
    const id = setInterval(reload, 30000);   // ← 30s conforme regra do gestor
    return () => clearInterval(id);
  }, [reload]);

  const forceDetect = async () => {
    setBusy(true);
    try { await api.smartoltAiForceDetect(); await reload(); }
    catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };

  const cfg = summary?.config || {};

  return (
    <div data-testid="smartolt-ai-panel" style={{ display: "grid", gap: 16 }}>
      {/* Header explicativo */}
      <div style={{
        padding: 18, borderRadius: 14,
        background: "linear-gradient(135deg, rgba(13,148,136,.10), rgba(99,102,241,.06))",
        border: "1px solid var(--border-default)",
      }}>
        <div style={{ display: "flex", alignItems: "flex-start",
                         justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{
              width: 46, height: 46, borderRadius: 12,
              background: "#0d9488", color: "#fff",
              display: "grid", placeItems: "center",
              boxShadow: "0 4px 14px rgba(13,148,136,.35)",
            }}>
              <Radio size={22} strokeWidth={1.75} />
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800,
                              color: "var(--text-primary)",
                              letterSpacing: "-0.02em" }}>
                SmartOLT AI · Monitoramento Autônomo
              </h2>
              <p style={{ margin: "4px 0 0", fontSize: 12,
                            color: "var(--text-secondary)", maxWidth: 700,
                            lineHeight: 1.5 }}>
                Varredura a cada{" "}
                <strong>{cfg.interval_seconds ?? 30}s</strong> · gatilho
                <strong> ≥{cfg.min_los ?? 10} ONUs em LOS</strong> ou
                <strong> ≥{cfg.min_pct ?? 50}% do PON</strong>. Cada pane nova
                é analisada por <strong>Claude</strong> (priorização +
                recomendação técnica). Atendente humano aprova rascunhos com 1 clique
                e cliente nunca vê notas internas.
              </p>
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button onClick={() => setShowTemplates((v) => !v)}
                    data-testid="smartolt-ai-templates-btn"
                    style={{
                      padding: "8px 14px", borderRadius: 6,
                      border: "1px solid var(--border-default)",
                      background: showTemplates ? "var(--accent-soft)" : "var(--bg-surface)",
                      color: "var(--text-primary)",
                      fontSize: 12, fontWeight: 600, cursor: "pointer",
                      display: "inline-flex", alignItems: "center", gap: 6,
                    }}>
              <Settings2 size={13} />
              Templates
            </button>
            <button onClick={forceDetect} disabled={busy}
                    data-testid="smartolt-ai-detect-btn"
                    style={{
                      padding: "8px 14px", borderRadius: 6,
                      border: "1px solid var(--border-default)",
                      background: "var(--bg-surface)",
                      color: "var(--text-primary)",
                      fontSize: 12, fontWeight: 600, cursor: busy ? "wait" : "pointer",
                      display: "inline-flex", alignItems: "center", gap: 6,
                    }}>
              {busy
                ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} />
                : <RefreshCw size={13} />}
              Forçar varredura
            </button>
          </div>
        </div>
      </div>

      {err && (
        <div style={{
          padding: 12, borderRadius: 8, fontSize: 12,
          background: "rgba(220,38,38,.08)",
          border: "1px solid rgba(220,38,38,.25)",
          color: "#dc2626",
        }}>
          {err}
        </div>
      )}

      {showTemplates && <TemplatesEditor onClose={() => setShowTemplates(false)} />}

      {/* KPIs */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: 10,
      }}>
        <Kpi label="Outages ativos"
              value={summary?.active_count ?? 0}
              color={summary?.active_count > 0 ? "#dc2626" : "#16a34a"}
              icon={AlertTriangle}
              testId="smartolt-ai-kpi-active" />
        <Kpi label="Clientes afetados (atual)"
              value={summary?.total_affected_clients ?? 0}
              color="var(--text-primary)"
              icon={Users}
              testId="smartolt-ai-kpi-affected" />
        <Kpi label="Rascunhos pendentes"
              value={summary?.pending_drafts ?? 0}
              color={summary?.pending_drafts > 0 ? "#d97706" : "var(--text-muted)"}
              icon={Inbox}
              testId="smartolt-ai-kpi-drafts" />
        <Kpi label="Resolvidos (24h)"
              value={summary?.resolved_24h ?? 0}
              color="#16a34a"
              icon={CheckCircle2}
              testId="smartolt-ai-kpi-resolved" />
      </div>

      {/* Rascunhos pendentes — modo ATIVO */}
      <DraftsSection drafts={drafts} reload={reload} />

      {/* Outages ativos */}
      <Section title={`Outages ativos · ${active.length}`}
                icon={AlertTriangle}>
        {active.length === 0 ? (
          <EmptyState text="Nenhum outage ativo detectado. Rede operando normalmente." />
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {active.map((o) => <OutageRow key={o.id} outage={o} active />)}
          </div>
        )}
      </Section>

      {/* Histórico resolvido */}
      <Section title="Resolvidos nas últimas 24h" icon={Activity}>
        {recent.length === 0 ? (
          <EmptyState text="Nenhum outage resolvido nas últimas 24h." />
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {recent.map((o) => <OutageRow key={o.id} outage={o} />)}
          </div>
        )}
      </Section>
    </div>
  );
}

/* ─────────────────────── Sub-componentes ─────────────────────── */

function DraftsSection({ drafts, reload }) {
  const [sendingId, setSendingId] = useState(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editText, setEditText] = useState("");

  // Agrupa rascunhos por outage_id para UX de aprovação em lote
  const groups = drafts.reduce((acc, d) => {
    const k = d.outage_id || "_";
    acc[k] = acc[k] || { outage_id: k, items: [],
                          olt_name: d.olt_name, board: d.board, port: d.port };
    acc[k].items.push(d);
    return acc;
  }, {});
  const groupList = Object.values(groups);

  const sendOne = async (id) => {
    setSendingId(id);
    try { await api.smartoltAiDraftSend(id); await reload(); }
    catch (e) { await window.alert(e?.response?.data?.detail || e.message); }
    finally { setSendingId(null); }
  };
  const discardOne = async (id) => {
    setSendingId(id);
    try { await api.smartoltAiDraftDiscard(id); await reload(); }
    catch (e) { await window.alert(e?.response?.data?.detail || e.message); }
    finally { setSendingId(null); }
  };
  const sendAll = async (outage_id, kind) => {
    if (!await window.confirm("Aprovar e enviar TODOS os rascunhos deste outage?")) return;
    setBulkBusy(true);
    try {
      const res = await api.smartoltAiDraftsSendBulk({ outage_id, kind });
      await reload();
      await window.alert(`Enviadas: ${res.sent} · Falhas: ${res.failed} · Total: ${res.total}`);
    } catch (e) { await window.alert(e?.response?.data?.detail || e.message); }
    finally { setBulkBusy(false); }
  };
  const saveEdit = async (id) => {
    try { await api.smartoltAiDraftEdit(id, editText); }
    catch (e) { await window.alert(e?.response?.data?.detail || e.message); return; }
    setEditingId(null); setEditText(""); await reload();
  };

  return (
    <Section title={`Rascunhos aguardando aprovação · ${drafts.length}`} icon={Inbox}>
      {drafts.length === 0 ? (
        <EmptyState text="Nenhum rascunho pendente. Quando o SmartOLT AI detectar uma pane, os avisos aparecerão aqui para sua aprovação." />
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          {groupList.map((g) => (
            <div key={g.outage_id} data-testid={`drafts-group-${g.outage_id}`}
                  style={{
                    border: "1px solid var(--border-default)",
                    borderRadius: 10,
                    background: "var(--bg-surface)",
                    overflow: "hidden",
                  }}>
              <div style={{
                padding: "10px 12px",
                background: "linear-gradient(90deg, rgba(217,119,6,.08), transparent)",
                borderBottom: "1px solid var(--border-default)",
                display: "flex", alignItems: "center",
                justifyContent: "space-between", gap: 8, flexWrap: "wrap",
              }}>
                <div style={{ fontSize: 12, fontWeight: 700,
                                 color: "var(--text-primary)",
                                 fontFamily: "ui-monospace, monospace" }}>
                  {g.olt_name} · Placa {g.board} · Porta {g.port}
                  <span style={{ marginLeft: 8, color: "var(--text-muted)",
                                    fontFamily: "inherit", fontWeight: 500 }}>
                    ({g.items.length} rascunho{g.items.length === 1 ? "" : "s"})
                  </span>
                </div>
                <button onClick={() => sendAll(g.outage_id)} disabled={bulkBusy}
                        data-testid={`drafts-bulk-send-${g.outage_id}`}
                        style={{
                          padding: "6px 12px", fontSize: 11, fontWeight: 700,
                          background: "#0d9488", color: "#fff",
                          border: "none", borderRadius: 6,
                          cursor: bulkBusy ? "wait" : "pointer",
                          display: "inline-flex", alignItems: "center", gap: 5,
                        }}>
                  {bulkBusy
                    ? <Loader2 size={11} style={{ animation: "spin 1s linear infinite" }} />
                    : <Send size={11} />}
                  Aprovar todos
                </button>
              </div>
              <div style={{ display: "grid", gap: 0 }}>
                {g.items.map((d) => (
                  <DraftRow key={d.id} draft={d}
                              editing={editingId === d.id}
                              editText={editText}
                              setEditText={setEditText}
                              onEdit={() => { setEditingId(d.id); setEditText(d.text); }}
                              onSaveEdit={() => saveEdit(d.id)}
                              onCancelEdit={() => { setEditingId(null); setEditText(""); }}
                              onSend={() => sendOne(d.id)}
                              onDiscard={() => discardOne(d.id)}
                              busy={sendingId === d.id} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

function DraftRow({ draft, editing, editText, setEditText, onEdit, onSaveEdit,
                     onCancelEdit, onSend, onDiscard, busy }) {
  const kindLabel = draft.kind === "outage_resolved"
    ? { text: "Aviso de normalização", color: "#16a34a", bg: "#f0fdf4" }
    : { text: "Aviso de pane",         color: "#d97706", bg: "#fffbeb" };
  return (
    <div data-testid={`draft-${draft.id}`}
          style={{
            padding: 12, borderTop: "1px solid var(--border-default)",
            display: "grid", gridTemplateColumns: "1fr auto", gap: 10,
            alignItems: "flex-start",
          }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8,
                          flexWrap: "wrap", marginBottom: 6 }}>
          <span style={{
            padding: "2px 8px", borderRadius: 999,
            background: kindLabel.bg, color: kindLabel.color,
            fontSize: 10, fontWeight: 800,
          }}>{kindLabel.text}</span>
          <span style={{ fontSize: 12, fontWeight: 700,
                            color: "var(--text-primary)" }}>
            {draft.subscriber_name || "Cliente não identificado"}
          </span>
          <span style={{ fontSize: 11, color: "var(--text-muted)",
                            fontFamily: "ui-monospace, monospace" }}>
            {formatPhone(draft.phone)}
          </span>
          {draft.subscriber_external_code && (
            <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
              · Cód {draft.subscriber_external_code}
            </span>
          )}
        </div>
        {editing ? (
          <textarea value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      data-testid={`draft-edit-textarea-${draft.id}`}
                      style={{
                        width: "100%", minHeight: 80, padding: 8,
                        fontSize: 12, fontFamily: "inherit",
                        border: "1px solid var(--border-default)",
                        borderRadius: 6, resize: "vertical",
                        background: "var(--bg-surface)",
                        color: "var(--text-primary)",
                      }} />
        ) : (
          <div style={{
            fontSize: 12.5, lineHeight: 1.5, whiteSpace: "pre-wrap",
            color: "var(--text-secondary)",
            padding: "6px 10px", borderRadius: 6,
            background: "var(--bg-surface-2)",
            border: "1px dashed var(--border-default)",
          }}>{draft.text}</div>
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {editing ? (
          <>
            <SmallBtn onClick={onSaveEdit} color="#0d9488"
                       testId={`draft-save-${draft.id}`}>
              <CheckCircle2 size={12} /> Salvar
            </SmallBtn>
            <SmallBtn onClick={onCancelEdit} color="#64748b"
                       testId={`draft-cancel-${draft.id}`}>
              Cancelar
            </SmallBtn>
          </>
        ) : (
          <>
            <SmallBtn onClick={onSend} color="#0d9488" disabled={busy}
                       testId={`draft-send-${draft.id}`}>
              {busy
                ? <Loader2 size={12} style={{ animation: "spin 1s linear infinite" }} />
                : <MailCheck size={12} />}
              Enviar
            </SmallBtn>
            <SmallBtn onClick={onEdit} color="#0ea5e9"
                       testId={`draft-edit-${draft.id}`}>
              <FileText size={12} /> Editar
            </SmallBtn>
            <SmallBtn onClick={onDiscard} color="#dc2626" disabled={busy}
                       testId={`draft-discard-${draft.id}`}>
              <MailX size={12} /> Descartar
            </SmallBtn>
          </>
        )}
      </div>
    </div>
  );
}

function SmallBtn({ children, onClick, color, disabled, testId }) {
  return (
    <button onClick={onClick} disabled={disabled} data-testid={testId}
            style={{
              padding: "5px 10px", fontSize: 11, fontWeight: 700,
              border: `1px solid ${color}40`, borderRadius: 5,
              background: `${color}12`, color,
              cursor: disabled ? "wait" : "pointer",
              display: "inline-flex", alignItems: "center", gap: 4,
              minWidth: 84, justifyContent: "center",
            }}>
      {children}
    </button>
  );
}

function TemplatesEditor({ onClose }) {
  const [cfg, setCfg] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => { api.smartoltAiTemplates().then(setCfg); }, []);

  const save = async () => {
    setSaving(true);
    try {
      await api.smartoltAiSaveTemplates({
        proactive: cfg.templates.proactive,
        resolved: cfg.templates.resolved,
        internal_assist: cfg.templates.internal_assist,
        internal_resolved: cfg.templates.internal_resolved,
      });
      onClose();
    } catch (e) { await window.alert(e?.response?.data?.detail || e.message); }
    finally { setSaving(false); }
  };

  if (!cfg) {
    return (
      <div style={{
        padding: 16, borderRadius: 10,
        background: "var(--bg-surface)",
        border: "1px solid var(--border-default)",
        textAlign: "center", fontSize: 12, color: "var(--text-muted)",
      }}>
        <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} />
        {" "}Carregando templates...
      </div>
    );
  }

  const set = (k, v) => setCfg({ ...cfg, templates: { ...cfg.templates, [k]: v } });

  return (
    <div data-testid="smartolt-ai-templates-editor"
          style={{
            padding: 16, borderRadius: 10,
            background: "var(--bg-surface)",
            border: "1px solid var(--border-default)",
            display: "grid", gap: 14,
          }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Settings2 size={15} />
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 800,
                        color: "var(--text-primary)" }}>
          Templates de mensagem
        </h3>
        <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
          Placeholders: {cfg.placeholders.join(" ")}
        </span>
      </div>
      <TplField label="ATIVO · Aviso de pane (cliente vê — após aprovação)"
                  icon={Eye}
                  value={cfg.templates.proactive}
                  onChange={(v) => set("proactive", v)} />
      <TplField label="ATIVO · Aviso de normalização (cliente vê — após aprovação)"
                  icon={Eye}
                  value={cfg.templates.resolved}
                  onChange={(v) => set("resolved", v)} />
      <TplField label="CO-PILOTO · Nota interna durante pane (só atendente vê)"
                  icon={EyeOff}
                  value={cfg.templates.internal_assist}
                  onChange={(v) => set("internal_assist", v)} />
      <TplField label="CO-PILOTO · Nota interna após resolução (só atendente vê)"
                  icon={EyeOff}
                  value={cfg.templates.internal_resolved}
                  onChange={(v) => set("internal_resolved", v)} />
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button onClick={onClose}
                data-testid="templates-cancel-btn"
                style={{
                  padding: "8px 16px", fontSize: 12, fontWeight: 600,
                  background: "var(--bg-surface-2)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border-default)",
                  borderRadius: 6, cursor: "pointer",
                }}>Cancelar</button>
        <button onClick={save} disabled={saving}
                data-testid="templates-save-btn"
                style={{
                  padding: "8px 16px", fontSize: 12, fontWeight: 700,
                  background: "#0d9488", color: "#fff",
                  border: "none", borderRadius: 6,
                  cursor: saving ? "wait" : "pointer",
                  display: "inline-flex", alignItems: "center", gap: 5,
                }}>
          {saving
            ? <Loader2 size={12} style={{ animation: "spin 1s linear infinite" }} />
            : <CheckCircle2 size={12} />}
          Salvar templates
        </button>
      </div>
    </div>
  );
}

function TplField({ label, icon: Ico, value, onChange }) {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 5,
                       fontSize: 10.5, fontWeight: 700,
                       color: "var(--text-secondary)",
                       textTransform: "uppercase", letterSpacing: 0.4,
                       marginBottom: 5 }}>
        <Ico size={11} />
        {label}
      </div>
      <textarea value={value || ""}
                  onChange={(e) => onChange(e.target.value)}
                  style={{
                    width: "100%", minHeight: 64, padding: 10,
                    fontSize: 12, fontFamily: "inherit",
                    border: "1px solid var(--border-default)",
                    borderRadius: 6, resize: "vertical",
                    background: "var(--bg-surface-2)",
                    color: "var(--text-primary)",
                  }} />
    </div>
  );
}

function formatPhone(p) {
  if (!p) return "—";
  const d = String(p).replace(/\D/g, "");
  if (d.length === 13) return `+${d.slice(0, 2)} (${d.slice(2, 4)}) ${d.slice(4, 9)}-${d.slice(9)}`;
  if (d.length === 12) return `+${d.slice(0, 2)} (${d.slice(2, 4)}) ${d.slice(4, 8)}-${d.slice(8)}`;
  if (d.length === 11) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  return p;
}

function Kpi({ label, value, color, icon: Ico, testId }) {
  return (
    <div data-testid={testId} style={{
      padding: 14, borderRadius: 10,
      border: "1px solid var(--border-default)",
      background: "var(--bg-surface)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6,
                       fontSize: 10, color: "var(--text-muted)",
                       textTransform: "uppercase", letterSpacing: 0.5,
                       fontWeight: 700 }}>
        <Ico size={11} strokeWidth={2} />
        {label}
      </div>
      <div style={{ fontSize: 28, fontWeight: 800, color,
                       letterSpacing: "-0.02em", marginTop: 4 }}>
        {value}
      </div>
    </div>
  );
}

function Section({ title, icon: Ico, children }) {
  return (
    <div>
      <div style={{
        fontSize: 11, fontWeight: 700, color: "var(--text-muted)",
        textTransform: "uppercase", letterSpacing: 0.6,
        marginBottom: 10, paddingBottom: 6,
        borderBottom: "1px solid var(--border-default)",
        display: "flex", alignItems: "center", gap: 6,
      }}>
        <Ico size={11} strokeWidth={2} />
        {title}
      </div>
      {children}
    </div>
  );
}

function OutageRow({ outage, active }) {
  const duration = (() => {
    try {
      const start = new Date(outage.first_detected_at);
      const end = outage.resolved_at ? new Date(outage.resolved_at) : new Date();
      const min = Math.floor((end - start) / 60000);
      if (min < 60) return `${min}min`;
      return `${Math.floor(min / 60)}h${(min % 60).toString().padStart(2, "0")}`;
    } catch { return "—"; }
  })();
  const severityColor = outage.severity_pct >= 50 ? "#dc2626"
                          : outage.severity_pct >= 20 ? "#d97706" : "#0ea5e9";
  const ai = outage.ai_insight;
  const aiPriColor = ai?.priority === "critica" ? "#dc2626"
                      : ai?.priority === "alta" ? "#d97706"
                      : ai?.priority === "media" ? "#0ea5e9" : "#64748b";
  return (
    <div data-testid={`outage-${outage.id}`} style={{
      padding: 12, borderRadius: 8,
      background: "var(--bg-surface)",
      border: "1px solid var(--border-default)",
      borderLeft: `3px solid ${active ? "#dc2626" : "#16a34a"}`,
      display: "grid", gap: 8,
    }}>
      <div style={{
        display: "grid", gridTemplateColumns: "auto 1fr auto auto", gap: 12,
        alignItems: "center",
      }}>
        <span style={{
          width: 8, height: 8, borderRadius: "50%",
          background: active ? "#dc2626" : "#16a34a",
          boxShadow: active ? "0 0 0 3px rgba(220,38,38,.20)" : "none",
          animation: active ? "wa-pulse 1.6s ease-in-out infinite" : "none",
        }} />
        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: "ui-monospace, monospace", fontSize: 13,
                          fontWeight: 700, color: "var(--text-primary)" }}>
            {outage.olt_name} · Placa {outage.board} · Porta {outage.port}
            {outage.vlan ? ` · VLAN ${outage.vlan}` : ""}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
            {outage.los_count}/{outage.total_count} ONTs em LOS ·{" "}
            {(outage.affected_phones?.length || 0)} clientes c/ telefone cadastrado
            {outage.trigger_rule && (
              <span style={{ marginLeft: 6, padding: "1px 6px",
                                background: "var(--bg-surface-2)",
                                borderRadius: 4, fontSize: 10,
                                fontFamily: "ui-monospace, monospace" }}>
                regra: {outage.trigger_rule}
              </span>
            )}
          </div>
        </div>
        <div style={{
          padding: "3px 9px", borderRadius: 999,
          background: `${severityColor}15`, color: severityColor,
          fontSize: 11, fontWeight: 700,
        }}>
          {outage.severity_pct}%
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4,
                         fontSize: 11, color: "var(--text-muted)",
                         fontFamily: "ui-monospace, monospace" }}>
          <Clock size={11} /> {duration}
        </div>
      </div>
      {ai && (
        <div data-testid={`outage-ai-insight-${outage.id}`}
              style={{
                padding: "8px 10px", borderRadius: 6,
                background: `${aiPriColor}08`,
                border: `1px solid ${aiPriColor}30`,
                display: "grid", gap: 4,
              }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6,
                            flexWrap: "wrap" }}>
            <span style={{
              padding: "1px 7px", borderRadius: 999,
              background: aiPriColor, color: "#fff",
              fontSize: 9, fontWeight: 800,
              textTransform: "uppercase", letterSpacing: 0.4,
            }}>IA · {ai.priority}</span>
            <span style={{ fontSize: 12, fontWeight: 700,
                              color: "var(--text-primary)" }}>
              {ai.headline}
            </span>
          </div>
          <div style={{ fontSize: 11.5, color: "var(--text-secondary)",
                            lineHeight: 1.5 }}>
            {ai.recommendation}
          </div>
          {ai.model && (
            <div style={{ fontSize: 9, color: "var(--text-muted)",
                              fontFamily: "ui-monospace, monospace" }}>
              {ai.model}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function EmptyState({ text }) {
  return (
    <div style={{
      padding: 24, textAlign: "center",
      fontSize: 12, color: "var(--text-muted)",
      background: "var(--bg-surface)",
      border: "1px dashed var(--border-default)",
      borderRadius: 8,
    }}>
      {text}
    </div>
  );
}
