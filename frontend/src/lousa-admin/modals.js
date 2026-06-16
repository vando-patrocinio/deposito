import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api";
import { Button } from "@/ui";
import { TYPE_LABELS, aiScoreColor } from "./_constants";
import { fmtAddress, fmtPhone, fmtName, fmtPraca, fmtRelato, safeText, ontLabel, ontSecondary, isPlaceholderMac } from "@/utils/format";

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
                  {s.level === "critical" ? "" : s.level === "warning" ? "" : ""} {s.msg}
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
export function ClosedTicketDetailModal({ ticket, onClose, onReopened }) {
  const [full, setFull] = useState(ticket);
  const [loading, setLoading] = useState(false);
  // iter211w — UI de reabertura
  const [reopenOpen, setReopenOpen] = useState(false);
  const [reopenReason, setReopenReason] = useState("");
  const [reopenKeepTech, setReopenKeepTech] = useState(true);
  const [reopenBusy, setReopenBusy] = useState(false);
  // iter198 — guard contra fechar com o 2º click do dblclick:
  //   1) ignora qualquer click nos primeiros 350ms após abrir (consome o
  //      "afterClick" residual do dblclick que abriu o modal)
  //   2) só fecha pelo backdrop se o MOUSEDOWN também foi no backdrop
  //      (evita fechar quando o usuário arrasta texto pra fora do modal)
  const [openedAt] = useState(() => Date.now());
  const mouseDownOnBackdropRef = useRef(false);

  const tryClose = useCallback(() => {
    if (Date.now() - openedAt < 350) return; // ignora propagação do dblclick
    onClose?.();
  }, [openedAt, onClose]);

  // ESC fecha (UX padrão)
  useEffect(() => {
    const handler = (e) => { if (e.key === "Escape") tryClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [tryClose]);

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
    <div data-testid="closed-ticket-detail-modal"
          onMouseDown={(e) => {
            // Marca se o "press" começou no backdrop (vs dentro do modal)
            mouseDownOnBackdropRef.current = e.target === e.currentTarget;
          }}
          onMouseUp={(e) => {
            // Só fecha se pressionou E soltou no backdrop
            // (evita fechar ao arrastar seleção de texto pra fora)
            if (mouseDownOnBackdropRef.current && e.target === e.currentTarget) {
              tryClose();
            }
            mouseDownOnBackdropRef.current = false;
          }}
          style={{ position: "fixed", inset: 0, zIndex: 9999,
                    background: "rgba(15,23,42,0.7)",
                    display: "flex", alignItems: "center",
                    justifyContent: "center", padding: 20 }}>
      <div onMouseDown={(e) => e.stopPropagation()}
            onMouseUp={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
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
                    {isClosed ? "✓ Nota finalizada" : "Nota em andamento"} ·{" "}
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
                        Fechado pelo gestor
                      </span>
                    )}
                  </div>
                </>
              );
            })()}
          </div>
          <button onClick={tryClose}
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
            <Section label="Endereço">{fmtAddress(cs.address)}</Section>
          )}
          {cs.phone && (
            <Section label="Telefone">
              <a href={`tel:${fmtPhone(cs.phone)}`} style={{ color: "#0891b2",
                          textDecoration: "none", fontWeight: 700 }}>
                {fmtPhone(cs.phone)}
              </a>
            </Section>
          )}
          {(cs.relato || full.notes) && (
            <Section label="Relato / Notas">
              <div style={{ whiteSpace: "pre-wrap" }}>
                {fmtRelato(cs.relato) || safeText(full.notes)}
              </div>
            </Section>
          )}

          {/* Sinal */}
          {cd.sinal != null && (
            <Section label="Sinal medido">
              <strong>{Number(cd.sinal).toFixed(1)} dBm</strong>
            </Section>
          )}
          {cd.ont && <Section label="ONT">{cd.ont}</Section>}

          {/* CTO + porta + splitter + VLAN */}
          {(cd.cto_name || cd.cto_port_number) && (
            <Section label="Vínculo na Rede IA">
              {cd.cto_name}
              {cd.cto_port_number && ` · Porta ${cd.cto_port_number}`}
              {cd.cto_splitter && ` · Splitter ${cd.cto_splitter}`}
              {cd.cto_vlan && ` · VLAN ${cd.cto_vlan}`}
              {cd.cto_network_type && ` · Rede ${cd.cto_network_type}`}
            </Section>
          )}

          {/* Insumos */}
          {(cd.drop || cd.backbone || cd.esticador || cd.conectores) && (
            <Section label="Insumos utilizados">
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
            <Section label="Teste de Ping">
              <pre style={{ background: "#f8fafc",
                              padding: 10, borderRadius: 6, fontSize: 11,
                              whiteSpace: "pre-wrap" }}>{cd.ping_summary}</pre>
            </Section>
          )}

          {/* Observações */}
          {cd.observacoes && (
            <Section label="Observações do técnico">
              <div style={{ whiteSpace: "pre-wrap" }}>{cd.observacoes}</div>
            </Section>
          )}

          {/* Fotos */}
          {fotosObjs.length > 0 && (
            <Section label={`Fotos (${fotosObjs.length})`}>
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

        {/* iter211w — Footer com botão "Reabrir OS" (só se fechada) */}
        {["finalizada", "encerrada", "cancelada", "reagendada"].includes(full?.status) && (
          <div data-testid="closed-detail-footer"
                style={{ borderTop: "1px solid #e2e8f0", padding: 12,
                          background: "#fafbfc" }}>
            {!reopenOpen ? (
              <div style={{ display: "flex", justifyContent: "space-between",
                              alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <div style={{ fontSize: 11, color: "#64748b", flex: 1, minWidth: 0 }}>
                  {full.reopen_count > 0 && (
                    <span style={{ background: "#fef3c7", color: "#92400e",
                                    padding: "2px 8px", borderRadius: 999,
                                    fontWeight: 700, marginRight: 6 }}>
                      ↻ Reaberta {full.reopen_count}× anteriormente
                    </span>
                  )}
                  Reabrir desfaz tudo: ONT, porta da CTO, materiais e fotos voltam ao início.
                </div>
                <button data-testid="reopen-os-btn"
                        onClick={() => setReopenOpen(true)}
                        style={{ padding: "8px 16px",
                                  background: "linear-gradient(135deg,#f59e0b,#d97706)",
                                  color: "white", border: "none", borderRadius: 8,
                                  fontWeight: 800, fontSize: 12, cursor: "pointer",
                                  display: "inline-flex", alignItems: "center",
                                  gap: 6, boxShadow: "0 2px 8px rgba(217,119,6,.3)" }}>
                  ↻ Reabrir OS
                </button>
              </div>
            ) : (
              <div data-testid="reopen-os-form" style={{ display: "grid", gap: 10 }}>
                <div style={{ fontSize: 12, fontWeight: 800, color: "#7c2d12" }}>
                  ️ Reabrir esta OS?
                </div>
                <div style={{ fontSize: 11, color: "#475569", lineHeight: 1.5,
                                background: "#fffbeb", padding: 8, borderRadius: 6,
                                border: "1px solid #fcd34d" }}>
                  A nota volta para <strong>pendente</strong> como se nunca tivesse sido fechada.
                  <br /><strong>Tudo é desfeito automaticamente:</strong>
                  <ul style={{ margin: "4px 0 0 18px", padding: 0 }}>
                    <li>ONT volta para o estoque do técnico (instalação) ou para o cliente (retirada)</li>
                    <li>Porta da CTO volta para <strong>livre</strong></li>
                    <li>Drop, esticadores e conectores são <strong>recreditados</strong> no estoque</li>
                    <li>Fotos, sinal e observações são limpos — técnico tira tudo do zero</li>
                    <li>Fechamento anterior fica arquivado em <code>previous_completions</code> para auditoria</li>
                  </ul>
                </div>
                <label style={{ display: "block" }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "#7c2d12",
                                  textTransform: "uppercase", letterSpacing: 0.4,
                                  marginBottom: 4 }}>
                    Motivo da reabertura (obrigatório) *
                  </div>
                  <textarea data-testid="reopen-os-reason"
                              value={reopenReason}
                              onChange={(e) => setReopenReason(e.target.value)}
                              placeholder="Ex: cliente reclamou que o serviço não foi concluído; técnico abriu chamado errado; sinal ainda está ruim."
                              style={{ width: "100%", minHeight: 60, padding: 8,
                                        fontSize: 12, borderRadius: 6,
                                        border: "1px solid #fcd34d",
                                        background: "#fffbeb",
                                        fontFamily: "inherit" }} />
                </label>
                <label data-testid="reopen-keep-tech-label"
                        style={{ display: "flex", gap: 8, alignItems: "center",
                                  cursor: "pointer", fontSize: 12, color: "#475569" }}>
                  <input type="checkbox" data-testid="reopen-keep-tech"
                          checked={reopenKeepTech}
                          onChange={(e) => setReopenKeepTech(e.target.checked)} />
                  Manter o mesmo técnico atribuído ({full.collaborator_name || "—"})
                </label>
                <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                  <button data-testid="reopen-os-cancel"
                          onClick={() => { setReopenOpen(false); setReopenReason(""); }}
                          disabled={reopenBusy}
                          style={{ padding: "8px 14px", background: "white",
                                    border: "1px solid #cbd5e1", borderRadius: 6,
                                    fontWeight: 700, fontSize: 12, cursor: "pointer" }}>
                    Cancelar
                  </button>
                  <button data-testid="reopen-os-confirm"
                          disabled={reopenBusy || reopenReason.trim().length < 3}
                          onClick={async () => {
                            if (reopenReason.trim().length < 3) return;
                            setReopenBusy(true);
                            try {
                              const updated = await api.lousaReopenTicket(full.id, {
                                reason: reopenReason.trim(),
                                keep_technician: reopenKeepTech,
                              });
                              onReopened?.(updated);
                              onClose?.();
                            } catch (e) {
                              window.alert("Erro ao reabrir: " + (e?.response?.data?.detail || e.message));
                            } finally {
                              setReopenBusy(false);
                            }
                          }}
                          style={{ padding: "8px 16px",
                                    background: reopenReason.trim().length < 3
                                      ? "#cbd5e1"
                                      : "linear-gradient(135deg,#f59e0b,#d97706)",
                                    color: "white", border: "none", borderRadius: 6,
                                    fontWeight: 800, fontSize: 12,
                                    cursor: reopenBusy ? "wait" : "pointer",
                                    opacity: reopenBusy ? 0.7 : 1 }}>
                    {reopenBusy ? "Reabrindo..." : "✓ Confirmar reabertura"}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
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
          Auto-reagendar OS com sinal degradado
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
              {cfg.enabled ? "Ligado" : "Desligado"}
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
              Nenhum colaborador com cargo/role contendo &quot;rede&quot;.
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
 * iter195 — Para tipo=retirada: o equipamento do cliente é
 * transferido para o estoque do técnico automaticamente.
 * ============================================================= */
export function AdminFinalizeModal({ ticket, onClose, onSubmit }) {
  const isRetirada = ticket?.type === "retirada";
  const isInstall = ticket?.type === "instalacao" || ticket?.type === "troca";
  const isGeneric = !isRetirada && !isInstall;
  const [form, setForm] = useState({
    sinal: "", observacoes: "",
    ont: "", ont_sn: "",
    is_defective: false, defective_reason: "",
    cto_id: "", cto_name: "", cto_port_number: "",
    // CTO 2026-02 (REGRA GLOBAL ESTOQUE OS — Q1=c híbrido):
    // físico=true para instalação/retirada/troca (sempre movimenta)
    // físico=false default p/ casos genéricos (sem internet, ONU offline...)
    physical_attendance: !isGeneric,
    admin_reason: "",
  });
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [clientOnt, setClientOnt] = useState(null); // ONT detectada no cliente
  const [ontLoading, setOntLoading] = useState(false);
  const [techStock, setTechStock] = useState([]);  // Estoque do técnico (install)
  const [techStockLoading, setTechStockLoading] = useState(false);
  const [ctos, setCtos] = useState([]);            // Lista de CTOs (install)
  const [ctoSearch, setCtoSearch] = useState("");
  const setF = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const cname = ticket?.client_snapshot?.name || ticket?.id;

  // Para Retirada: tenta detectar a ONT atualmente vinculada ao cliente
  // (lookup em stok_onts via service.client_id) para pré-preencher MAC/SN.
  useEffect(() => {
    if (!isRetirada || !ticket?.id) return;
    let alive = true;
    setOntLoading(true);
    api._client.get(`/lousa/tickets/${ticket.id}/client-current-ont`)
      .then((r) => {
        if (!alive) return;
        const ont = r.data || null;
        setClientOnt(ont);
        if (ont) {
          setForm((f) => ({
            ...f,
            ont: ont.mac && !String(ont.mac).startsWith("AUTOSN_")
                  && !String(ont.mac).startsWith("SN-")
                  ? ont.mac : f.ont,
            ont_sn: ont.scan_sn || f.ont_sn,
          }));
        }
      })
      .catch(() => { /* silent — campo segue editável */ })
      .finally(() => { if (alive) setOntLoading(false); });
    return () => { alive = false; };
  }, [isRetirada, ticket?.id]);

  // iter196 — Para Instalação/Troca: carrega estoque do técnico + lista de CTOs
  useEffect(() => {
    if (!isInstall || !ticket?.id) return;
    let alive = true;
    setTechStockLoading(true);
    api._client.get(`/lousa/tickets/${ticket.id}/tech-stock`)
      .then((r) => { if (alive) setTechStock(r.data?.items || []); })
      .catch(() => { if (alive) setTechStock([]); })
      .finally(() => { if (alive) setTechStockLoading(false); });
    api.redeIaCtosList({ limit: 200 })
      .then((r) => {
        if (!alive) return;
        const list = Array.isArray(r) ? r : (r?.items || []);
        setCtos(list);
      })
      .catch(() => { if (alive) setCtos([]); });
    return () => { alive = false; };
  }, [isInstall, ticket?.id]);

  const submit = async () => {
    if (form.sinal === "" || Number.isNaN(Number(form.sinal))) {
      window.alert("Informe o sinal óptico final (dBm).");
      return;
    }
    // CTO 2026-02 — Q1=c. Fechamento administrativo precisa motivo.
    if (isGeneric && !form.physical_attendance &&
        form.admin_reason.trim().length < 5) {
      window.alert("Informe o motivo administrativo (mínimo 5 caracteres).");
      return;
    }
    if (isRetirada && !form.ont_sn && !form.ont) {
      const proceed = await window.confirm(
        "Nenhum SN/MAC informado.\n\n" +
        "O SN é o identificador principal da ONT. Sem ele, " +
        "o equipamento NÃO será transferido para o estoque do técnico — " +
        "apenas a nota será fechada.\n\n" +
        "Quer prosseguir mesmo assim?");
      if (!proceed) return;
    }
    if (isRetirada && form.is_defective && !form.defective_reason.trim()) {
      window.alert("Informe o motivo do defeito (será gravado no histórico).");
      return;
    }
    if (isInstall) {
      if (!form.ont) {
        window.alert("Escolha a ONT do estoque do técnico para esta instalação (identificada pelo SN).");
        return;
      }
      if (!form.cto_id || !form.cto_port_number) {
        const ok = await window.confirm(
          "CTO ou porta não informadas.\n\n" +
          "Sem CTO+porta, a ONT será baixada do estoque mas a porta da " +
          "CTO NÃO será marcada como ocupada. Confirma assim?");
        if (!ok) return;
      }
    }
    setBusy(true);
    try {
      const cd = {
        sinal: Number(form.sinal),
        qtd_drop: 0,
        esticadores: 0,
        conectores_fast: 0,
        cabo_rede: 0,
        conectores_rede: 0,
        ont: (isRetirada || isInstall) ? (form.ont || null) : null,
        ont_sn: isRetirada ? (form.ont_sn || null) : null,
        is_defective: isRetirada ? form.is_defective : false,
        defective_reason: isRetirada && form.is_defective
          ? form.defective_reason.trim() || null : null,
        cto_id: isInstall ? (form.cto_id || null) : null,
        cto_name: isInstall ? (form.cto_name || null) : null,
        cto_port_number: isInstall && form.cto_port_number
          ? Number(form.cto_port_number) : null,
        observacoes: form.observacoes || null,
        closed_by_admin: true,
        // Quando há transferência real (retirada/instalação) NÃO é fechamento
        // interno puro — o backend faz a baixa de fato no estoque.
        internal_close: !(isRetirada || isInstall),
      };
      // CTO 2026-02 — extras pra o guardrail backend.
      const extras = {
        physical_attendance: isGeneric ? form.physical_attendance : true,
        admin_reason: form.admin_reason || null,
      };
      await onSubmit(cd, notes, extras);
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
          {isRetirada
            ? "Finalizar Retirada no lugar do técnico"
            : isInstall
              ? "Finalizar Instalação no lugar do técnico"
              : "Finalizar OS no lugar do técnico"}
        </h3>
        <p style={{ fontSize: 11, color: "#64748b", marginBottom: 12 }}>
          Cliente: <strong>{cname}</strong>
          {ticket.assigned_collaborator_id && (
            <span> · técnico: {ticket.collaborator_name || ticket.assigned_collaborator_id}</span>
          )}
          {isGeneric && (
            <>
              <br/>Movimentação de estoque depende do tipo de fechamento
              selecionado abaixo.
            </>
          )}
        </p>

        {/* CTO 2026-02 — REGRA GLOBAL ESTOQUE OS (Q1=c) */}
        {isGeneric && (
          <div data-testid="adm-fin-physical-block"
                style={{ background: form.physical_attendance
                          ? "#eff6ff" : "#fff7ed",
                          border: `1.5px solid ${form.physical_attendance
                            ? "#3b82f6" : "#fdba74"}`,
                          borderRadius: 10, padding: 12, marginBottom: 14,
                          fontSize: 12, color: "#1e293b", lineHeight: 1.5 }}>
            <strong style={{ fontSize: 12 }}>Houve atendimento físico do técnico?</strong>
            <div style={{ display: "flex", gap: 16, marginTop: 8 }}>
              <label style={{ display: "flex", alignItems: "center", gap: 6,
                fontWeight: 600, cursor: "pointer" }}>
                <input type="radio" name="phys-attendance"
                  data-testid="adm-fin-phys-no"
                  checked={!form.physical_attendance}
                  onChange={() => setF("physical_attendance", false)}/>
                Não — fechamento administrativo
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 6,
                fontWeight: 600, cursor: "pointer" }}>
                <input type="radio" name="phys-attendance"
                  data-testid="adm-fin-phys-yes"
                  checked={form.physical_attendance}
                  onChange={() => setF("physical_attendance", true)}/>
                Sim — houve visita técnica
              </label>
            </div>
            {!form.physical_attendance && (
              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 11, color: "#92400e",
                  marginBottom: 4, fontWeight: 700 }}>
                  Motivo administrativo (obrigatório, mín. 5 caracteres) *
                </div>
                <textarea data-testid="adm-fin-admin-reason"
                  value={form.admin_reason}
                  onChange={(e) => setF("admin_reason", e.target.value)}
                  placeholder="Ex.: cliente cancelou antes do agendamento. Sem atendimento físico."
                  rows={2} style={{ width: "100%", padding: 8,
                    borderRadius: 6, border: "1px solid #fdba74",
                    background: "white", fontSize: 12,
                    fontFamily: "inherit", boxSizing: "border-box" }}/>
                <div style={{ fontSize: 10, color: "#92400e", marginTop: 4 }}>
                  Nenhum equipamento será movimentado. Esta finalização será
                  auditada como <strong>fechamento administrativo</strong>.
                </div>
              </div>
            )}
            {form.physical_attendance && (
              <div style={{ marginTop: 8, fontSize: 11, color: "#1e3a8a" }}>
                ✓ Caso tenha havido troca de ONT no atendimento, a regra
                global de estoque exigirá <strong>SN/MAC</strong>. Inclua nas
                observações o detalhamento da movimentação.
              </div>
            )}
          </div>
        )}

        {/* iter195 — Banner Retirada com info de transferência automática */}
        {isRetirada && (
          <div data-testid="adm-fin-retirada-banner"
                style={{ background: "linear-gradient(135deg,#ecfdf5,#d1fae5)",
                          border: "1.5px solid #10b981", borderRadius: 10,
                          padding: 12, marginBottom: 14, fontSize: 12,
                          color: "#065f46", lineHeight: 1.5 }}>
            <strong>✅ Transferência automática de equipamento</strong><br/>
            Ao finalizar, a ONT vinculada ao cliente será movida para o
            estoque do <strong>{ticket.collaborator_name || "técnico atribuído"}</strong>,
            como se ele tivesse feito a retirada presencial. Também serão
            enviados o comprovante WhatsApp e a remoção no SmartOLT.
            {clientOnt && (
              <div style={{ marginTop: 8, padding: 8,
                              background: "rgba(255,255,255,.7)",
                              borderRadius: 6, fontSize: 11,
                              fontFamily: "monospace" }}>
                <div><strong>ONT detectada no cliente:</strong></div>
                <div data-testid="adm-fin-retirada-ont-label"
                      style={{ fontSize: 14, fontWeight: 800, color: "#065f46" }}>
                  SN: {ontLabel(clientOnt)}
                </div>
                {ontSecondary(clientOnt) && (
                  <div style={{ fontSize: 10, opacity: 0.7 }}>
                    MAC: {ontSecondary(clientOnt)}
                  </div>
                )}
                {clientOnt.model && (
                  <div style={{ fontSize: 10, opacity: 0.7 }}>
                    Modelo: {clientOnt.model}
                  </div>
                )}
              </div>
            )}
            {ontLoading && (
              <div style={{ marginTop: 6, fontSize: 11, opacity: 0.7 }}>
                Buscando ONT atual do cliente…
              </div>
            )}
            {!ontLoading && !clientOnt && (
              <div style={{ marginTop: 6, fontSize: 11, color: "#92400e" }}>
                ️ Nenhuma ONT registrada no estoque deste cliente. Informe
                MAC/SN manualmente para registrar a retirada.
              </div>
            )}
          </div>
        )}

        {/* iter196 — Banner Instalação com info de baixa+vínculo */}
        {isInstall && (
          <div data-testid="adm-fin-install-banner"
                style={{ background: "linear-gradient(135deg,#eff6ff,#dbeafe)",
                          border: "1.5px solid #3b82f6", borderRadius: 10,
                          padding: 12, marginBottom: 14, fontSize: 12,
                          color: "#1e3a8a", lineHeight: 1.5 }}>
            <strong>Baixa de estoque + vínculo automático</strong><br/>
            Ao finalizar, a ONT escolhida do estoque do <strong>
            {ticket.collaborator_name || "técnico atribuído"}</strong> será
            baixada e <strong>vinculada ao cliente</strong>. A porta da CTO
            informada também será marcada como ocupada.
          </div>
        )}

        <div style={{ marginBottom: 10 }}>
          <FieldNum label="Sinal final (dBm) *" testid="adm-fin-sinal"
                      step="0.1" value={form.sinal}
                      onChange={(v) => setF("sinal", v)} required />
        </div>

        {/* iter197 — SN prevalente: ordem invertida (SN à esquerda, MAC secundário) */}
        {isRetirada && (
          <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr",
                          gap: 10, marginBottom: 10 }}>
            <label style={{ display: "block" }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#065f46",
                              textTransform: "uppercase", letterSpacing: 0.4,
                              marginBottom: 3 }}>
                SN da ONT * <span style={{ color: "#64748b", fontWeight: 500 }}>(identificador principal)</span>
              </div>
              <input data-testid="adm-fin-ont-sn"
                      value={form.ont_sn}
                      onChange={(e) => setF("ont_sn", e.target.value.toUpperCase())}
                      placeholder="HWTC12345678"
                      style={{ width: "100%", padding: "8px 10px",
                                fontFamily: "monospace", fontSize: 14, fontWeight: 700,
                                border: "2px solid #10b981", borderRadius: 6,
                                background: form.ont_sn ? "#ecfdf5" : "white" }} />
            </label>
            <label style={{ display: "block" }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8",
                              textTransform: "uppercase", letterSpacing: 0.4,
                              marginBottom: 3 }}>
                MAC <span style={{ fontWeight: 500 }}>(opcional)</span>
              </div>
              <input data-testid="adm-fin-ont-mac"
                      value={form.ont}
                      onChange={(e) => setF("ont", e.target.value.toUpperCase())}
                      placeholder="AA:BB:CC:DD:EE:FF"
                      style={{ width: "100%", padding: "6px 8px",
                                fontFamily: "monospace", fontSize: 12,
                                border: "1px solid #cbd5e1", borderRadius: 6 }} />
            </label>
          </div>
        )}

        {/* iter195 — Defeituoso? (Retirada) */}
        {isRetirada && (
          <div style={{ marginBottom: 10, padding: 10,
                          background: form.is_defective ? "#fef2f2" : "#f8fafc",
                          border: `1px solid ${form.is_defective ? "#fca5a5" : "#e2e8f0"}`,
                          borderRadius: 8 }}>
            <label style={{ display: "flex", gap: 8, alignItems: "center",
                              cursor: "pointer", fontSize: 12, fontWeight: 700,
                              color: form.is_defective ? "#991b1b" : "#475569" }}>
              <input type="checkbox" data-testid="adm-fin-defective"
                      checked={form.is_defective}
                      onChange={(e) => setF("is_defective", e.target.checked)} />
              ️ Equipamento retirado está DEFEITUOSO (devolver à empresa)
            </label>
            {form.is_defective && (
              <textarea data-testid="adm-fin-defective-reason"
                          value={form.defective_reason}
                          onChange={(e) => setF("defective_reason", e.target.value)}
                          placeholder="Motivo do defeito (ex: porta ETH queimada, não liga, etc.)"
                          style={{ width: "100%", padding: 8, fontSize: 12,
                                    minHeight: 50, borderRadius: 6,
                                    border: "1px solid #fca5a5",
                                    marginTop: 8, fontFamily: "inherit" }} />
            )}
          </div>
        )}

        {/* iter196 — Instalação: seleção da ONT do estoque do técnico (SN prevalente iter197) */}
        {isInstall && (
          <div style={{ marginBottom: 10 }}>
            <label style={{ display: "block", fontSize: 11, fontWeight: 700,
                              color: "#1e40af", textTransform: "uppercase",
                              letterSpacing: 0.5, marginBottom: 4 }}>
              ONT do estoque do técnico * <span style={{ color: "#64748b", fontWeight: 500, textTransform: "none" }}>(identificada por SN)</span>
            </label>
            {techStockLoading ? (
              <div style={{ padding: 10, fontSize: 12, color: "#64748b",
                              background: "#f8fafc", borderRadius: 6 }}>
                Carregando estoque do técnico…
              </div>
            ) : techStock.length === 0 ? (
              <div data-testid="adm-fin-stock-empty"
                    style={{ padding: 10, fontSize: 12, color: "#92400e",
                              background: "#fef3c7", borderRadius: 6,
                              border: "1px solid #fcd34d" }}>
                ️ Nenhuma ONT disponível no estoque deste técnico.
                Cadastre uma transferência antes de instalar.
              </div>
            ) : (
              <select data-testid="adm-fin-ont-select"
                        value={form.ont}
                        onChange={(e) => setF("ont", e.target.value)}
                        style={{ width: "100%", padding: 8, fontSize: 13,
                                  fontWeight: 700,
                                  border: "2px solid #3b82f6", borderRadius: 6,
                                  fontFamily: "monospace",
                                  background: form.ont ? "#eff6ff" : "white" }}>
                <option value="">— Escolher por SN ({techStock.length} disponíveis) —</option>
                {techStock.map((o) => {
                  const sn = (o.scan_sn || o.sn || "").trim();
                  const macReal = !isPlaceholderMac(o.mac) ? o.mac : "";
                  const label = sn || macReal || o.mac;
                  const suffix = [
                    o.model,
                    macReal && sn ? `MAC ${macReal}` : null,
                    o.source === "retirada" && o.withdrawn_from_client_name
                      ? `ex: ${o.withdrawn_from_client_name}` : null,
                  ].filter(Boolean).join(" · ");
                  return (
                    <option key={o.mac} value={o.mac}>
                      SN {label}{suffix ? ` · ${suffix}` : ""}
                    </option>
                  );
                })}
              </select>
            )}
          </div>
        )}

        {/* iter196 — Instalação: seleção da CTO + porta */}
        {isInstall && (
          <div style={{ marginBottom: 10, padding: 10,
                          background: "#f8fafc", borderRadius: 8,
                          border: "1px solid #e2e8f0" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#475569",
                            textTransform: "uppercase", letterSpacing: 0.4,
                            marginBottom: 6 }}>
              CTO + Porta (será marcada como ocupada)
            </div>
            <input data-testid="adm-fin-cto-search"
                    value={ctoSearch}
                    onChange={(e) => setCtoSearch(e.target.value)}
                    placeholder="Filtrar CTO por nome…"
                    style={{ width: "100%", padding: 8, fontSize: 12,
                              border: "1px solid #cbd5e1", borderRadius: 6,
                              marginBottom: 6 }} />
            <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr",
                            gap: 8 }}>
              <select data-testid="adm-fin-cto-select"
                        value={form.cto_id}
                        onChange={(e) => {
                          const c = ctos.find((x) => x.id === e.target.value);
                          setForm((f) => ({ ...f,
                            cto_id: e.target.value,
                            cto_name: c?.name || "" }));
                        }}
                        style={{ width: "100%", padding: 8, fontSize: 12,
                                  border: "1px solid #cbd5e1", borderRadius: 6,
                                  background: form.cto_id ? "#ecfdf5" : "white" }}>
                <option value="">— Escolher CTO —</option>
                {ctos
                  .filter((c) => {
                    if (!ctoSearch) return true;
                    const q = ctoSearch.toLowerCase();
                    return (c.name || "").toLowerCase().includes(q);
                  })
                  .slice(0, 200)
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name || c.id}
                      {c.total_ports ? ` (${c.total_ports}p)` : ""}
                    </option>
                  ))}
              </select>
              <input data-testid="adm-fin-cto-port" type="number"
                      min="1" step="1"
                      value={form.cto_port_number}
                      onChange={(e) => setF("cto_port_number", e.target.value)}
                      placeholder="Nº porta"
                      style={{ width: "100%", padding: 8, fontSize: 12,
                                border: "1px solid #cbd5e1", borderRadius: 6,
                                fontFamily: "monospace",
                                background: form.cto_port_number ? "#ecfdf5" : "white" }} />
            </div>
            {form.cto_id && form.cto_name && (
              <div style={{ marginTop: 6, fontSize: 10, color: "#475569" }}>
                Selecionado: <strong>{form.cto_name}</strong>
                {form.cto_port_number && <> · Porta {form.cto_port_number}</>}
              </div>
            )}
          </div>
        )}

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
                    style={{ padding: "8px 18px",
                              background: isRetirada
                                ? "linear-gradient(135deg,#10b981,#0d9488)"
                                : isInstall
                                  ? "linear-gradient(135deg,#3b82f6,#1d4ed8)"
                                  : "#0f766e",
                              color: "white", border: "none",
                              borderRadius: 6, fontWeight: 700, fontSize: 12,
                              cursor: busy ? "wait" : "pointer",
                              opacity: busy ? 0.7 : 1 }}>
            {busy
              ? "Finalizando..."
              : isRetirada
                ? "✓ Finalizar Retirada e transferir equipamento"
                : isInstall
                  ? "✓ Finalizar Instalação e baixar ONT"
                  : "✓ Finalizar OS"}
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
