import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Button } from "@/ui";
import { TYPE_LABELS, aiScoreColor } from "./_constants";
import { fmtAddress, fmtPhone, fmtName, fmtPraca, fmtRelato, safeText } from "@/utils/format";

/* =============================================================
   AiDetailModal — exibe avaliação IA de um serviço fechado.
============================================================= */
export function AiDetailModal({ detail, onClose }) {
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.6)", zIndex: 110, display: "grid", placeItems: "center", padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()} data-testid="ai-detail-modal"
           style={{ background: "white", borderRadius: 18, padding: 22, maxWidth: 540, width: "100%", maxHeight: "90vh", overflowY: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>Avaliação IA do Serviço</h2>
          <span style={{ background: aiScoreColor(detail.ai_score), color: "white", padding: "4px 12px", borderRadius: 999, fontWeight: 900, fontSize: 14 }}>
            {detail.ai_score?.toFixed(1)}/10
          </span>
        </div>
        <div style={{ fontSize: 13, color: "#475569", marginBottom: 8 }}>
          <strong>Veredito:</strong> {detail.verdict} · <span style={{ color: "#94a3b8", fontSize: 11 }}>({detail.method})</span>
        </div>
        <p style={{ background: "#f8fafc", padding: 10, borderRadius: 8, fontSize: 13, color: "#0f172a", margin: "8px 0" }}>
          {detail.summary}
        </p>
        {detail.recommendations?.length > 0 && (
          <>
            <h4 style={{ fontSize: 13, margin: "10px 0 4px" }}>Recomendações</h4>
            <ul style={{ paddingLeft: 18, margin: 0, fontSize: 12, color: "#334155" }}>
              {detail.recommendations.map((r, i) => <li key={i} style={{ marginBottom: 4 }}>{r}</li>)}
            </ul>
          </>
        )}
        {detail.heuristic?.signals?.length > 0 && (
          <>
            <h4 style={{ fontSize: 13, margin: "12px 0 4px" }}>Sinais (heurística)</h4>
            <div style={{ fontSize: 11 }}>
              {detail.heuristic.signals.map((s, i) => (
                <div key={i} style={{
                  padding: "4px 8px", marginBottom: 3, borderRadius: 6,
                  background: s.level === "critical" ? "#fee2e2" : s.level === "warning" ? "#fef3c7" : "#dcfce7",
                  color: s.level === "critical" ? "#7f1d1d" : s.level === "warning" ? "#78350f" : "#166534",
                }}>
                  {s.level === "critical" ? "🔴" : s.level === "warning" ? "🟡" : "🟢"} {s.msg}
                </div>
              ))}
            </div>
          </>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14 }}>
          <Button variant="soft" onClick={onClose}>Fechar</Button>
        </div>
      </div>
    </div>
  );
}

/* =============================================================
   Section — wrapper de label + conteúdo (usado em ClosedTicketDetailModal).
============================================================= */
function Section({ label, children }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: "#64748b",
                      textTransform: "uppercase", letterSpacing: 0.5,
                      marginBottom: 4 }}>{label}</div>
      <div>{children}</div>
    </div>
  );
}

/* =============================================================
   ClosedTicketDetailModal — visualização read-only de uma nota
   finalizada/encerrada (cliente, sinal, CTO, insumos, fotos, etc.).
============================================================= */
export function ClosedTicketDetailModal({ ticket, onClose }) {
  const [full, setFull] = useState(ticket);
  const [loading, setLoading] = useState(false);

  // Recarrega o ticket completo (lousa público pode ter completion_data)
  useEffect(() => {
    let alive = true;
    (async () => {
      if (!ticket?.id) return;
      try {
        setLoading(true);
        const r = await api._client.get(`/lousa/tickets/${ticket.id}`);
        if (alive && r.data) setFull({ ...ticket, ...r.data });
      } catch { /* ignore — usa ticket inicial */ }
      finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, [ticket]);

  const cd = full?.completion_data || {};
  const cs = full?.client_snapshot || {};
  const fmt = (iso) => {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString("pt-BR",
        { dateStyle: "short", timeStyle: "short" });
    } catch { return iso; }
  };

  const fotos = (cd.fotos || []).filter(Boolean);
  const fotosObjs = fotos.map((f) => {
    if (typeof f === "string") return { dataUrl: f, kind: "geral" };
    return { dataUrl: f.dataUrl || f.data_url, kind: f.kind || "geral" };
  }).filter((f) => f.dataUrl);

  return (
    <div onClick={onClose}
          data-testid="closed-ticket-detail-modal"
          style={{ position: "fixed", inset: 0, zIndex: 9999,
                    background: "rgba(15,23,42,0.7)",
                    display: "flex", alignItems: "center",
                    justifyContent: "center", padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()}
            style={{ background: "#fff", borderRadius: 12,
                      width: "min(95vw, 720px)", maxHeight: "92vh",
                      display: "flex", flexDirection: "column",
                      overflow: "hidden",
                      boxShadow: "0 20px 60px rgba(0,0,0,0.35)" }}>
        {/* Header */}
        <div style={{ padding: 16, borderBottom: "1px solid #e2e8f0",
                        display: "flex", justifyContent: "space-between",
                        alignItems: "flex-start", gap: 12 }}>
          <div>
            {(() => {
              const isClosed = ["finalizada", "encerrada"].includes(full?.status);
              return (
                <>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#64748b",
                                  textTransform: "uppercase", letterSpacing: 0.5 }}>
                    {isClosed ? "✓ Nota finalizada" : "🟡 Nota em andamento"} ·{" "}
                    {TYPE_LABELS[full.type] || full.type}
                  </div>
                  <div style={{ fontSize: 18, fontWeight: 800, color: "#0f172a",
                                  marginTop: 2 }}>
                    {fmtName(cs.name) || "—"}
                  </div>
                  <div style={{ fontSize: 11, color: "#64748b", marginTop: 4,
                                  lineHeight: 1.4 }}>
                    {isClosed
                      ? <>Fechada em <strong>{fmt(full.closed_at || full.finalized_at)}</strong></>
                      : <>Status: <strong>{full.status}</strong> · Aberta em <strong>{fmt(full.created_at)}</strong></>}
                    {full.outcome && <> · Resultado: <strong>{full.outcome}</strong></>}
                    {full.scheduled_date && (
                      <> · Agendada: <strong>{full.scheduled_date}
                        {full.scheduled_time ? ` ${full.scheduled_time}` : ""}</strong></>
                    )}
                    {full.admin_action === "encerrar" && (
                      <span style={{ marginLeft: 6, padding: "2px 7px",
                                      background: "#fef3c7", color: "#92400e",
                                      borderRadius: 999, fontSize: 9, fontWeight: 800 }}>
                        🛡 Fechado pelo gestor
                      </span>
                    )}
                  </div>
                </>
              );
            })()}
          </div>
          <button onClick={onClose}
                  data-testid="closed-detail-close"
                  style={{ background: "transparent", border: 0, fontSize: 22,
                            cursor: "pointer", color: "#64748b" }}>×</button>
        </div>

        {/* Body */}
        <div style={{ padding: 16, overflowY: "auto", flex: 1, fontSize: 13,
                        color: "#0f172a" }}>
          {loading && (
            <div style={{ color: "#94a3b8", fontSize: 12 }}>Carregando…</div>
          )}

          {/* Endereço */}
          {cs.address && (
            <Section label="📍 Endereço">{fmtAddress(cs.address)}</Section>
          )}
          {cs.phone && (
            <Section label="📞 Telefone">
              <a href={`tel:${fmtPhone(cs.phone)}`} style={{ color: "#0891b2",
                          textDecoration: "none", fontWeight: 700 }}>
                {fmtPhone(cs.phone)}
              </a>
            </Section>
          )}
          {(cs.relato || full.notes) && (
            <Section label="📋 Relato / Notas">
              <div style={{ whiteSpace: "pre-wrap" }}>
                {fmtRelato(cs.relato) || safeText(full.notes)}
              </div>
            </Section>
          )}

          {/* Sinal */}
          {cd.sinal != null && (
            <Section label="📡 Sinal medido">
              <strong>{Number(cd.sinal).toFixed(1)} dBm</strong>
            </Section>
          )}
          {cd.ont && <Section label="🔌 ONT">{cd.ont}</Section>}

          {/* CTO + porta + splitter + VLAN */}
          {(cd.cto_name || cd.cto_port_number) && (
            <Section label="🗺 Vínculo na Rede IA">
              {cd.cto_name}
              {cd.cto_port_number && ` · Porta ${cd.cto_port_number}`}
              {cd.cto_splitter && ` · Splitter ${cd.cto_splitter}`}
              {cd.cto_vlan && ` · VLAN ${cd.cto_vlan}`}
              {cd.cto_network_type && ` · Rede ${cd.cto_network_type}`}
            </Section>
          )}

          {/* Insumos */}
          {(cd.drop || cd.backbone || cd.esticador || cd.conectores) && (
            <Section label="🧰 Insumos utilizados">
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {cd.drop && <li>Drop: <strong>{cd.drop}m</strong></li>}
                {cd.backbone && <li>Backbone: <strong>{cd.backbone}m</strong></li>}
                {cd.esticador && <li>Esticador: <strong>{cd.esticador}</strong></li>}
                {cd.conectores && <li>Conectores: <strong>{cd.conectores}</strong></li>}
              </ul>
            </Section>
          )}

          {/* Ping */}
          {cd.ping_summary && (
            <Section label="📶 Teste de Ping">
              <pre style={{ background: "#f8fafc",
                              padding: 10, borderRadius: 6, fontSize: 11,
                              whiteSpace: "pre-wrap" }}>{cd.ping_summary}</pre>
            </Section>
          )}

          {/* Observações */}
          {cd.observacoes && (
            <Section label="📝 Observações do técnico">
              <div style={{ whiteSpace: "pre-wrap" }}>{cd.observacoes}</div>
            </Section>
          )}

          {/* Fotos */}
          {fotosObjs.length > 0 && (
            <Section label={`📷 Fotos (${fotosObjs.length})`}>
              <div style={{ display: "grid",
                              gridTemplateColumns:
                                "repeat(auto-fill, minmax(120px, 1fr))",
                              gap: 8 }}>
                {fotosObjs.map((f, i) => (
                  <a key={i} href={f.dataUrl} target="_blank"
                      rel="noopener noreferrer">
                    <img src={f.dataUrl} alt={f.kind || ""}
                          style={{ width: "100%", aspectRatio: "1/1",
                                    objectFit: "cover", borderRadius: 8,
                                    border: "1px solid #e2e8f0",
                                    cursor: "zoom-in" }} />
                  </a>
                ))}
              </div>
            </Section>
          )}

          {/* fallback se nada estiver preenchido */}
          {!loading && !cd.sinal && !cd.ont && !cd.cto_name && !cd.drop
            && !cd.observacoes && fotosObjs.length === 0
            && !cs.relato && !full.notes && !cs.phone && !cs.address && (
            <div style={{ padding: 20, textAlign: "center",
                            color: "#94a3b8", fontSize: 12 }}>
              Nenhum dado registrado ainda.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}


/* =============================================================
 * Auto-Reschedule on Degraded Signal — Modal de configuração.
 * Reagenda automaticamente OS com sinal degradado para um técnico
 * de rede, com delay configurável.
 * ============================================================= */
export function AutoReschedConfigModal({ initial, onClose, onSaved }) {
  const [cfg, setCfg] = useState(initial || {
    enabled: false, delay_hours: 24,
    target_collaborator_id: null, rede_candidates: [],
  });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (initial) setCfg(initial);
  }, [initial]);

  const save = async () => {
    setSaving(true);
    try {
      const next = await api.lousaAutoReschedSet({
        enabled: cfg.enabled,
        delay_hours: cfg.delay_hours,
        target_collaborator_id: cfg.target_collaborator_id || null,
      });
      onSaved(next);
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
    } finally { setSaving(false); }
  };

  const candidates = cfg.rede_candidates || [];

  return (
    <div onClick={onClose} data-testid="auto-resched-modal"
          style={{ position: "fixed", inset: 0, zIndex: 1100,
                    background: "rgba(0,0,0,.55)",
                    display: "flex", alignItems: "center",
                    justifyContent: "center", padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()}
            style={{ background: "var(--bg-canvas)", padding: 24,
                      borderRadius: 12, maxWidth: 520, width: "100%",
                      border: "2px solid #0f766e",
                      boxShadow: "0 20px 50px rgba(0,0,0,.3)" }}>
        <h3 style={{ margin: "0 0 6px", fontSize: 17, fontWeight: 800,
                        color: "#0f172a" }}>
          🟢 Auto-reagendar OS com sinal degradado
        </h3>
        <p style={{ fontSize: 12, color: "var(--text-muted)",
                      marginBottom: 16 }}>
          Quando um técnico finaliza uma OS e o sinal piora
          (<strong>|sinal fechamento| &gt; |sinal abertura|</strong>),
          o sistema cria automaticamente uma nova OS de reinspeção
          atribuída a um técnico de rede.
        </p>

        {/* Toggle */}
        <label data-testid="auto-resched-enable-label"
                style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "center", padding: "10px 12px",
                          background: cfg.enabled ? "#ecfdf5" : "#f1f5f9",
                          border: `1px solid ${cfg.enabled ? "#6ee7b7" : "#cbd5e1"}`,
                          borderRadius: 8, marginBottom: 14,
                          cursor: "pointer" }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: 13,
                              color: cfg.enabled ? "#065f46" : "#475569" }}>
              {cfg.enabled ? "🟢 Ligado" : "⚪ Desligado"}
            </div>
            <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
              {cfg.enabled
                ? "Próximas OS com sinal degradado serão reagendadas automaticamente."
                : "Nenhuma ação automática enquanto desligado."}
            </div>
          </div>
          <input type="checkbox"
                    data-testid="auto-resched-toggle-input"
                    checked={!!cfg.enabled}
                    onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })}
                    style={{ width: 36, height: 20, cursor: "pointer" }} />
        </label>

        {/* Delay */}
        <div style={{ marginBottom: 14 }}>
          <label style={{ display: "block", fontSize: 11,
                            fontWeight: 700, color: "var(--text-secondary)",
                            textTransform: "uppercase", letterSpacing: 0.5,
                            marginBottom: 6 }}>
            Reagendar para daqui a quantas horas
          </label>
          <div style={{ display: "flex", gap: 8 }}>
            {[12, 24, 48, 72].map((h) => (
              <button key={h} type="button"
                        data-testid={`auto-resched-delay-${h}`}
                        onClick={() => setCfg({ ...cfg, delay_hours: h })}
                        style={{ flex: 1, padding: "8px 0", borderRadius: 6,
                                  border: `1px solid ${cfg.delay_hours === h ? "#0f766e" : "#cbd5e1"}`,
                                  background: cfg.delay_hours === h ? "#0f766e" : "white",
                                  color: cfg.delay_hours === h ? "white" : "#0f172a",
                                  fontWeight: 700, fontSize: 12, cursor: "pointer" }}>
                {h}h
              </button>
            ))}
          </div>
        </div>

        {/* Target */}
        <div style={{ marginBottom: 18 }}>
          <label style={{ display: "block", fontSize: 11,
                            fontWeight: 700, color: "var(--text-secondary)",
                            textTransform: "uppercase", letterSpacing: 0.5,
                            marginBottom: 6 }}>
            Técnico de rede que receberá a OS
          </label>
          <select value={cfg.target_collaborator_id || ""}
                    data-testid="auto-resched-target-select"
                    onChange={(e) => setCfg({
                      ...cfg,
                      target_collaborator_id: e.target.value || null,
                    })}
                    style={{ width: "100%", padding: "8px 10px",
                              borderRadius: 6, border: "1px solid #cbd5e1",
                              fontSize: 13 }}>
            <option value="">Automático (primeiro disponível)</option>
            {candidates.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          {candidates.length === 0 && (
            <div style={{ fontSize: 10, color: "#92400e",
                            background: "#fffbeb", padding: "5px 8px",
                            borderRadius: 4, marginTop: 6, border: "1px solid #fcd34d" }}>
              ⚠ Nenhum colaborador com cargo/role contendo &quot;rede&quot;.
              Cadastre técnicos de rede no painel de Colaboradores.
            </div>
          )}
        </div>

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose}
                    style={{ padding: "8px 18px", background: "white",
                              border: "1px solid #cbd5e1", borderRadius: 6,
                              fontWeight: 700, fontSize: 12, cursor: "pointer" }}>
            Cancelar
          </button>
          <button onClick={save}
                    data-testid="auto-resched-save"
                    disabled={saving}
                    style={{ padding: "8px 18px", background: "#0f766e",
                              color: "white", border: "none",
                              borderRadius: 6, fontWeight: 700, fontSize: 12,
                              cursor: saving ? "wait" : "pointer",
                              opacity: saving ? 0.7 : 1 }}>
            {saving ? "Salvando..." : "Salvar"}
          </button>
        </div>
      </div>
    </div>
  );
}


/* =============================================================
 * AdminFinalizeModal — gestor finaliza OS no lugar do técnico,
 * com mesmas regras (drop, esticadores, sinal, observações).
 * Aplica os mesmos hooks no backend (signal snapshot, auto-resched).
 * ============================================================= */
export function AdminFinalizeModal({ ticket, onClose, onSubmit }) {
  const [form, setForm] = useState({ sinal: "", observacoes: "" });
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const setF = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const cname = ticket?.client_snapshot?.name || ticket?.id;

  const submit = async () => {
    if (form.sinal === "" || Number.isNaN(Number(form.sinal))) {
      window.alert("Informe o sinal óptico final (dBm).");
      return;
    }
    setBusy(true);
    try {
      // Fechamento interno (gestor/auditor): NÃO consome insumos nem ONT.
      // Apenas registra sinal final do cliente + observações + justificativa.
      const cd = {
        sinal: Number(form.sinal),
        qtd_drop: 0,
        esticadores: 0,
        conectores_fast: 0,
        cabo_rede: 0,
        conectores_rede: 0,
        ont: null,
        observacoes: form.observacoes || null,
        closed_by_admin: true,
        internal_close: true,
      };
      await onSubmit(cd, notes);
    } catch (e) {
      window.alert(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div onClick={onClose} data-testid="admin-finalize-modal"
          style={{ position: "fixed", inset: 0, zIndex: 1200,
                    background: "rgba(0,0,0,.55)",
                    display: "flex", alignItems: "center",
                    justifyContent: "center", padding: 16,
                    overflowY: "auto" }}>
      <div onClick={(e) => e.stopPropagation()}
            style={{ background: "var(--bg-canvas, white)", padding: 22,
                      borderRadius: 12, maxWidth: 560, width: "100%",
                      border: "2px solid #0f766e",
                      boxShadow: "0 20px 50px rgba(0,0,0,.3)",
                      maxHeight: "90vh", overflowY: "auto" }}>
        <h3 style={{ margin: "0 0 4px", fontSize: 17, fontWeight: 800,
                        color: "#0f172a" }}>
          🏁 Finalizar OS no lugar do técnico
        </h3>
        <p style={{ fontSize: 11, color: "#64748b", marginBottom: 12 }}>
          Cliente: <strong>{cname}</strong>
          {ticket.assigned_collaborator_id && (
            <span> · técnico: {ticket.collaborator_name || ticket.assigned_collaborator_id}</span>
          )}
          <br/>Fechamento <strong>interno</strong>: registra apenas o sinal
          final do cliente e a descrição. <strong>Não consome insumos nem
          ONT</strong> (técnico não esteve no local).
        </p>

        <div style={{ marginBottom: 10 }}>
          <FieldNum label="Sinal final (dBm) *" testid="adm-fin-sinal"
                      step="0.1" value={form.sinal}
                      onChange={(v) => setF("sinal", v)} required />
        </div>

        <label style={{ display: "block", fontSize: 11, fontWeight: 700,
                          color: "#475569", textTransform: "uppercase",
                          letterSpacing: 0.5, marginBottom: 4 }}>
          Observações do serviço
        </label>
        <textarea data-testid="adm-fin-obs"
                    value={form.observacoes}
                    onChange={(e) => setF("observacoes", e.target.value)}
                    placeholder="Ex: substituído drop, ajustada emenda no CTO, etc."
                    style={{ width: "100%", padding: 8, fontSize: 12,
                              minHeight: 60, borderRadius: 6,
                              border: "1px solid #cbd5e1", marginBottom: 10,
                              fontFamily: "inherit" }} />

        <label style={{ display: "block", fontSize: 11, fontWeight: 700,
                          color: "#7c2d12", textTransform: "uppercase",
                          letterSpacing: 0.5, marginBottom: 4 }}>
          Justificativa (auditoria — por que o gestor está fechando)
        </label>
        <textarea data-testid="adm-fin-notes"
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Ex: técnico não conseguiu finalizar via app, registrei manualmente."
                    style={{ width: "100%", padding: 8, fontSize: 12,
                              minHeight: 50, borderRadius: 6,
                              border: "1px solid #fcd34d",
                              background: "#fffbeb",
                              marginBottom: 16, fontFamily: "inherit" }} />

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose}
                    style={{ padding: "8px 18px", background: "white",
                              border: "1px solid #cbd5e1", borderRadius: 6,
                              fontWeight: 700, fontSize: 12, cursor: "pointer" }}>
            Cancelar
          </button>
          <button onClick={submit}
                    data-testid="adm-fin-submit"
                    disabled={busy}
                    style={{ padding: "8px 18px", background: "#0f766e",
                              color: "white", border: "none",
                              borderRadius: 6, fontWeight: 700, fontSize: 12,
                              cursor: busy ? "wait" : "pointer",
                              opacity: busy ? 0.7 : 1 }}>
            {busy ? "Finalizando..." : "✓ Finalizar OS"}
          </button>
        </div>
      </div>
    </div>
  );
}

function FieldNum({ label, value, onChange, step = "1", required, testid }) {
  return (
    <label style={{ display: "block" }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: "#475569",
                       textTransform: "uppercase", letterSpacing: 0.4,
                       marginBottom: 3 }}>
        {label}{required && <span style={{ color: "#dc2626" }}> *</span>}
      </div>
      <input type="number" step={step} value={value}
                data-testid={testid}
                onChange={(e) => onChange(e.target.value)}
                style={{ width: "100%", padding: "6px 8px",
                          border: "1px solid #cbd5e1", borderRadius: 6,
                          fontSize: 13, fontWeight: 600 }} />
    </label>
  );
}
