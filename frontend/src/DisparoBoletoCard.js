/* ============================================================================
 * Disparo Manual de Boletos — Card no Disparo IA
 *
 * Permite ao gestor:
 *   1. Pré-visualizar quantos clientes recebem o disparo (com filtros)
 *   2. Confirmar e disparar (Baileys → WhatsApp Railway)
 *   3. Acompanhar progresso em tempo real
 *   4. Ver histórico de runs anteriores
 *
 * UI minimalista, sem dependências extras. Usa só os endpoints
 * /api/disparo-ia/boletos/{preview,send,runs,history}.
 * ========================================================================== */
import React, { useCallback, useEffect, useState } from "react";
import { Send, AlertCircle, CheckCircle2, Clock, FileText } from "lucide-react";
import { api } from "@/api";
import BoletoPdfPreviewCard from "@/BoletoPdfPreviewCard";

const Card = ({ children, style = {}, ...rest }) => (
  <div
    {...rest}
    style={{
      background: "var(--bg-surface, #fff)",
      border: "1px solid var(--border-default, #e2e8f0)",
      borderRadius: 14,
      ...style,
    }}>
    {children}
  </div>
);

function fmtBRL(v) {
  if (v == null) return "—";
  return Number(v).toLocaleString("pt-BR",
    { style: "currency", currency: "BRL" });
}

export default function DisparoBoletoCard() {
  // Filtros
  const [daysMin, setDaysMin] = useState(0);
  const [daysMax, setDaysMax] = useState(3);
  const [onlyOverdue, setOnlyOverdue] = useState(false);
  const [throttleSec, setThrottleSec] = useState(2);
  const [customIntro, setCustomIntro] = useState("");

  // Estado
  const [preview, setPreview] = useState(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [sending, setSending] = useState(false);
  const [activeRun, setActiveRun] = useState(null);
  const [history, setHistory] = useState([]);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [dryRun, setDryRun] = useState(false);

  const buildFilters = useCallback(() => ({
    days_until_due_min: Number(daysMin),
    days_until_due_max: Number(daysMax),
    only_overdue: onlyOverdue,
  }), [daysMin, daysMax, onlyOverdue]);

  const doPreview = useCallback(async () => {
    setLoadingPreview(true);
    try {
      const r = await api._client.post(
        "/disparo-ia/boletos/preview", buildFilters(),
      ).then((x) => x.data);
      setPreview(r);
    } catch (e) {
      alert("Falha no preview: " + (e?.response?.data?.detail || e.message));
    } finally {
      setLoadingPreview(false);
    }
  }, [buildFilters]);

  const loadHistory = useCallback(async () => {
    try {
      const r = await api._client.get(
        "/disparo-ia/boletos/history?limit=10",
      ).then((x) => x.data);
      setHistory(r.items || []);
    } catch { /* silencioso */ }
  }, []);

  useEffect(() => { loadHistory(); }, [loadHistory]);
  useEffect(() => { doPreview(); }, [doPreview]);

  // Polling do run ativo
  useEffect(() => {
    if (!activeRun?.run_id || activeRun.status === "completed") return;
    const interval = setInterval(async () => {
      try {
        const r = await api._client.get(
          `/disparo-ia/boletos/runs/${activeRun.run_id}`,
        ).then((x) => x.data);
        setActiveRun(r);
        if (r.status === "completed") {
          clearInterval(interval);
          loadHistory();
        }
      } catch { /* nada */ }
    }, 3000);
    return () => clearInterval(interval);
  }, [activeRun?.run_id, activeRun?.status, loadHistory]);

  const doSend = async () => {
    setConfirmOpen(false);
    setSending(true);
    try {
      const r = await api._client.post(
        "/disparo-ia/boletos/send",
        {
          ...buildFilters(),
          throttle_seconds: Number(throttleSec),
          custom_intro: customIntro || null,
          dry_run: dryRun,
        },
      ).then((x) => x.data);
      setActiveRun({ ...r, status: "running", sent: 0, failed: 0,
                       total_candidates: r.total_candidates });
    } catch (e) {
      alert("Falha ao disparar: " + (e?.response?.data?.detail || e.message));
    } finally {
      setSending(false);
    }
  };

  const progress = activeRun
    ? Math.round(
        ((activeRun.sent || 0) + (activeRun.failed || 0))
        / Math.max(1, activeRun.total_candidates) * 100,
      )
    : 0;

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <BoletoPdfPreviewCard />
      <Card data-testid="disparo-boleto-card" style={{ padding: 18 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                       marginBottom: 14 }}>
        <FileText size={18} color="#0ea5e9" />
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>
          Disparo Manual de Boletos
        </h3>
        <span style={{
          marginLeft: "auto", fontSize: 11, fontWeight: 700,
          padding: "3px 8px", borderRadius: 999,
          background: "linear-gradient(135deg,#0ea5e9,#6366f1)",
          color: "white",
        }}>
          BAILEYS
        </span>
      </div>

      {/* Filtros */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px,1fr))",
        gap: 10, marginBottom: 14,
      }}>
        <Field label="Dias até vencer (de)">
          <input type="number" value={daysMin}
                   data-testid="dispboleto-days-min"
                   onChange={(e) => setDaysMin(e.target.value)}
                   disabled={onlyOverdue}
                   style={inputStyle} />
        </Field>
        <Field label="Até">
          <input type="number" value={daysMax}
                   data-testid="dispboleto-days-max"
                   onChange={(e) => setDaysMax(e.target.value)}
                   disabled={onlyOverdue}
                   style={inputStyle} />
        </Field>
        <Field label="Intervalo entre envios (s)">
          <input type="number" value={throttleSec} min={1} max={30}
                   data-testid="dispboleto-throttle"
                   onChange={(e) => setThrottleSec(e.target.value)}
                   style={inputStyle} />
        </Field>
        <Field label="Modo">
          <label style={{
            display: "flex", alignItems: "center", gap: 6, fontSize: 12,
            padding: "8px 10px",
          }}>
            <input type="checkbox" checked={onlyOverdue}
                     data-testid="dispboleto-only-overdue"
                     onChange={(e) => setOnlyOverdue(e.target.checked)} />
            Só vencidas
          </label>
        </Field>
      </div>

      <Field label="Texto antes da mensagem (opcional)">
        <textarea value={customIntro}
                    data-testid="dispboleto-custom-intro"
                    onChange={(e) => setCustomIntro(e.target.value)}
                    placeholder="Ex: Oi! Lembrando que seu boleto está próximo do vencimento..."
                    rows={2}
                    style={{ ...inputStyle, fontFamily: "inherit",
                              resize: "vertical" }} />
      </Field>

      {/* Botão preview */}
      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        <button onClick={doPreview} disabled={loadingPreview}
                 data-testid="dispboleto-preview-btn"
                 style={btnSecondary}>
          {loadingPreview ? "Calculando..." : "🔍 Recalcular Preview"}
        </button>
        <button onClick={() => { setDryRun(true); setConfirmOpen(true); }}
                 disabled={!preview?.total_clientes || sending}
                 data-testid="dispboleto-dryrun-btn"
                 style={btnGhost}>
          🧪 Simular (sem enviar)
        </button>
        <button onClick={() => { setDryRun(false); setConfirmOpen(true); }}
                 disabled={!preview?.total_clientes || sending}
                 data-testid="dispboleto-send-btn"
                 style={btnPrimary}>
          <Send size={14} /> Disparar AGORA
        </button>
      </div>

      {/* Preview Card */}
      {preview && (
        <div data-testid="dispboleto-preview-result"
              style={{ marginTop: 14, padding: 12, borderRadius: 10,
                        background: "rgba(99,102,241,0.06)",
                        border: "1px dashed #6366f1" }}>
          <div style={{ display: "grid",
                          gridTemplateColumns: "repeat(auto-fit, minmax(120px,1fr))",
                          gap: 10, fontSize: 12 }}>
            <Kpi label="Clientes" value={preview.total_clientes} />
            <Kpi label="Faturas" value={preview.total_faturas} />
            <Kpi label="Valor Total" value={preview.valor_total_fmt} mono />
          </div>
          {preview.candidates && preview.candidates.length > 0 && (
            <details style={{ marginTop: 10, fontSize: 11 }}>
              <summary style={{ cursor: "pointer", fontWeight: 700 }}>
                Ver primeiros {Math.min(5, preview.candidates.length)} candidatos
              </summary>
              <div style={{ marginTop: 6, display: "grid", gap: 4,
                              maxHeight: 200, overflow: "auto" }}>
                {preview.candidates.slice(0, 20).map((c) => (
                  <div key={c.external_id} style={{
                    display: "grid",
                    gridTemplateColumns: "1fr auto auto",
                    gap: 8, padding: "5px 8px",
                    background: "var(--bg-surface-2,#f8fafc)",
                    borderRadius: 6,
                  }}>
                    <span title={c.phone}>
                      {c.name.split(" ")[0]} <span style={{
                        color: "var(--text-muted)" }}>· {c.phone.slice(-9)}</span>
                    </span>
                    <span style={{ color: "var(--text-muted)" }}>
                      {c.invoices_count}× · {c.earliest_due_fmt}
                    </span>
                    <strong>{c.total_amount_fmt}</strong>
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}

      {/* Active Run Progress */}
      {activeRun && (
        <div data-testid="dispboleto-active-run"
              style={{ marginTop: 14, padding: 12, borderRadius: 10,
                        background: activeRun.status === "completed"
                          ? "rgba(34,197,94,0.08)"
                          : "rgba(245,158,11,0.08)",
                        border: `1px solid ${activeRun.status === "completed"
                          ? "#22c55e" : "#f59e0b"}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8,
                          marginBottom: 8 }}>
            {activeRun.status === "completed" ? (
              <CheckCircle2 size={16} color="#15803d" />
            ) : (
              <Clock size={16} color="#d97706" />
            )}
            <strong style={{ fontSize: 13 }}>
              Run #{activeRun.run_id?.slice(-6)} —
              {activeRun.status === "completed"
                ? " Concluído"
                : ` Enviando ${activeRun.sent || 0}/${activeRun.total_candidates}`}
              {activeRun.dry_run && " (Simulação)"}
            </strong>
          </div>
          <div style={{ height: 8, background: "rgba(99,102,241,0.15)",
                          borderRadius: 4, overflow: "hidden" }}>
            <div style={{
              width: `${progress}%`, height: "100%",
              background: activeRun.status === "completed"
                ? "linear-gradient(90deg,#15803d,#22c55e)"
                : "linear-gradient(90deg,#f59e0b,#ef4444)",
              transition: "width .35s",
            }} />
          </div>
          <div style={{ marginTop: 6, fontSize: 11,
                          color: "var(--text-muted)" }}>
            ✅ {activeRun.sent || 0} enviadas · ❌ {activeRun.failed || 0} falhas
          </div>
        </div>
      )}

      {/* Histórico */}
      {history.length > 0 && (
        <details style={{ marginTop: 14 }}>
          <summary style={{ fontSize: 12, fontWeight: 700, cursor: "pointer",
                              color: "var(--text-secondary)" }}>
            📜 Histórico de disparos ({history.length})
          </summary>
          <div style={{ marginTop: 8, display: "grid", gap: 6 }}>
            {history.map((h) => (
              <div key={h.id} data-testid={`dispboleto-history-${h.id}`}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 80px 80px",
                      gap: 8, padding: "6px 10px", fontSize: 11,
                      background: "var(--bg-surface-2,#f8fafc)",
                      borderRadius: 6,
                    }}>
                <span title={h.id}>
                  {new Date(h.started_at).toLocaleString("pt-BR")}
                  {h.dry_run && " 🧪"}
                </span>
                <span style={{ color: "#15803d", fontWeight: 700 }}>
                  ✓ {h.sent || 0}
                </span>
                <span style={{ color: h.failed > 0 ? "#dc2626" : "#94a3b8" }}>
                  ✗ {h.failed || 0}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Modal de confirmação */}
      {confirmOpen && (
        <div data-testid="dispboleto-confirm-modal"
              style={{
                position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
                display: "flex", alignItems: "center", justifyContent: "center",
                zIndex: 9999,
              }}
              onClick={() => setConfirmOpen(false)}>
          <Card style={{ padding: 24, maxWidth: 460, width: "92%" }}
                 onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
              <AlertCircle size={28}
                            color={dryRun ? "#0ea5e9" : "#f59e0b"} />
              <div>
                <h3 style={{ margin: "0 0 6px", fontSize: 16 }}>
                  {dryRun ? "Simular disparo?" : "Confirmar disparo real?"}
                </h3>
                <p style={{ margin: 0, fontSize: 13,
                              color: "var(--text-secondary)" }}>
                  Vou{" "}
                  {dryRun ? <strong>simular sem enviar</strong>
                              : <strong>enviar mensagens reais</strong>}{" "}
                  para <strong>{preview?.total_clientes || 0}</strong>{" "}
                  cliente(s) totalizando{" "}
                  <strong>{preview?.valor_total_fmt}</strong>.
                  <br />
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    Tempo estimado: ~{Math.ceil(
                      (preview?.total_clientes || 0) * throttleSec / 60
                    )} min
                  </span>
                </p>
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 18,
                            justifyContent: "flex-end" }}>
              <button onClick={() => setConfirmOpen(false)}
                       data-testid="dispboleto-confirm-cancel"
                       style={btnGhost}>
                Cancelar
              </button>
              <button onClick={doSend}
                       data-testid="dispboleto-confirm-go"
                       style={dryRun ? btnSecondary : btnPrimary}>
                {dryRun ? "Simular" : "Sim, disparar"}
              </button>
            </div>
          </Card>
        </div>
      )}
    </Card>
    </div>
  );
}

/* ---------- ui helpers ---------- */
const Field = ({ label, children }) => (
  <label style={{ display: "grid", gap: 4 }}>
    <span style={{ fontSize: 11, fontWeight: 700,
                     color: "var(--text-muted)",
                     textTransform: "uppercase", letterSpacing: 0.4 }}>
      {label}
    </span>
    {children}
  </label>
);

const Kpi = ({ label, value, mono = false }) => (
  <div style={{ textAlign: "center" }}>
    <div style={{ fontSize: 10, color: "var(--text-muted)",
                    fontWeight: 700, textTransform: "uppercase" }}>
      {label}
    </div>
    <div style={{ fontSize: 18, fontWeight: 800,
                    fontFamily: mono ? "ui-monospace,monospace" : "inherit",
                    color: "var(--text-primary)" }}>
      {value}
    </div>
  </div>
);

const inputStyle = {
  padding: "8px 10px", borderRadius: 8,
  border: "1px solid var(--border-default,#cbd5e1)",
  background: "var(--bg-surface, #fff)",
  color: "var(--text-primary)", fontSize: 13, width: "100%",
};

const btnPrimary = {
  display: "inline-flex", alignItems: "center", gap: 6,
  padding: "10px 16px", borderRadius: 10, border: "none",
  background: "linear-gradient(135deg,#0ea5e9,#6366f1)",
  color: "white", fontWeight: 700, fontSize: 13, cursor: "pointer",
};

const btnSecondary = {
  padding: "10px 16px", borderRadius: 10,
  border: "1px solid var(--border-default,#cbd5e1)",
  background: "var(--bg-surface, #fff)",
  color: "var(--text-primary)", fontWeight: 600, fontSize: 13, cursor: "pointer",
};

const btnGhost = {
  padding: "10px 16px", borderRadius: 10,
  border: "1px solid transparent",
  background: "transparent",
  color: "var(--text-muted)", fontWeight: 600, fontSize: 13, cursor: "pointer",
};
