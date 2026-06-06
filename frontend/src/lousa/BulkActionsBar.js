import React, { useState } from "react";
import { api } from "@/api";
import { Button } from "@/ui";

/**
 * Barra flutuante inferior — aparece quando há bolhas selecionadas.
 * Permite executar ações coletivas: reagendar / cancelar / encerrar / IA.
 */
export default function BulkActionsBar({ selectedIds, onClear, onDone }) {
  const [popup, setPopup] = useState(null); // null | "encerrar" | "cancelar" | "reagendar" | "ia"
  const count = selectedIds.length;

  if (count === 0) return null;

  return (
    <>
      <div data-testid="bulk-actions-bar" style={{
        position: "fixed", bottom: 18, left: "50%", transform: "translateX(-50%)",
        background: "linear-gradient(135deg,#0f172a,#1e293b)", color: "white",
        borderRadius: 999, padding: "10px 16px",
        display: "flex", gap: 10, alignItems: "center",
        boxShadow: "0 18px 50px rgba(15,23,42,.45), 0 0 0 1px rgba(255,255,255,.06)",
        zIndex: 90, flexWrap: "wrap", maxWidth: "94vw",
      }}>
        <span data-testid="bulk-count" style={{
          background: "linear-gradient(135deg,#3b82f6,#1d4ed8)",
          padding: "5px 12px", borderRadius: 999, fontSize: 13, fontWeight: 800,
        }}>
          {count} selecionada{count > 1 ? "s" : ""}
        </span>
        <button data-testid="bulk-action-reagendar" onClick={() => setPopup("reagendar")} style={pillBtn("#3b82f6")}>Reagendar</button>
        <button data-testid="bulk-action-encerrar" onClick={() => setPopup("encerrar")} style={pillBtn("#64748b")}>✓ Encerrar</button>
        <button data-testid="bulk-action-cancelar" onClick={() => setPopup("cancelar")} style={pillBtn("#dc2626")}>✗ Cancelar</button>
        <button data-testid="bulk-action-ia" onClick={() => setPopup("ia")} style={pillBtn("#a855f7")}>IA</button>
        <button data-testid="bulk-clear" onClick={onClear} style={{
          background: "transparent", color: "white", border: "1px solid rgba(255,255,255,.25)",
          borderRadius: 999, padding: "5px 12px", cursor: "pointer", fontSize: 12, fontWeight: 700,
        }}>✕ Limpar</button>
      </div>

      {popup && popup !== "ia" && (
        <BulkActionModal
          action={popup}
          ticketIds={selectedIds}
          onClose={() => setPopup(null)}
          onDone={() => { setPopup(null); onDone(); }}
        />
      )}
      {popup === "ia" && (
        <BulkAiModal
          ticketIds={selectedIds}
          onClose={() => setPopup(null)}
        />
      )}
    </>
  );
}

function pillBtn(color) {
  return {
    background: color, color: "white", border: 0, borderRadius: 999,
    padding: "7px 14px", fontWeight: 800, fontSize: 13, cursor: "pointer",
    boxShadow: "0 4px 12px rgba(0,0,0,.18)",
  };
}

const ACTION_TITLES = {
  encerrar: { icon: "✓", title: "Encerrar serviços em lote", color: "#64748b", verb: "encerrar", confirmLabel: "Encerrar" },
  cancelar: { icon: "✗", title: "Cancelar serviços em lote", color: "#dc2626", verb: "cancelar", confirmLabel: "Cancelar serviços" },
  reagendar: { icon: "", title: "Reagendar serviços em lote", color: "#3b82f6", verb: "reagendar", confirmLabel: "Reagendar" },
};

function BulkActionModal({ action, ticketIds, onClose, onDone }) {
  const cfg = ACTION_TITLES[action];
  const [notes, setNotes] = useState("");
  const [date, setDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    return d.toISOString().slice(0, 10);
  });
  const [time, setTime] = useState("09:00");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");

  const requireNotes = action === "cancelar" || action === "reagendar";
  const requireDate = action === "reagendar";

  async function submit(e) {
    e?.preventDefault();
    setErr("");
    if (requireNotes && !notes.trim()) { setErr("Motivo é obrigatório."); return; }
    if (requireDate && (!date || !time)) { setErr("Data e horário são obrigatórios."); return; }
    setBusy(true);
    try {
      const payload = { ticket_ids: ticketIds, action, notes: notes.trim() || null };
      if (requireDate) { payload.new_date = date; payload.new_time = time; }
      const r = await api.lousaBulkAction(payload);
      setResult(r);
    } catch (e2) {
      setErr(e2?.response?.data?.detail || e2.message || "Erro ao processar lote.");
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    return (
      <Overlay onClose={onDone}>
        <div data-testid="bulk-result-modal" onClick={(e) => e.stopPropagation()} style={modalCss(540)}>
          <h2 style={{ margin: 0, fontSize: 18 }}>{cfg.icon} Resultado do lote</h2>
          <div style={{ display: "flex", gap: 10, margin: "14px 0" }}>
            <Stat color="#10b981" label="Processadas" value={result.processed} testid="bulk-result-success" />
            <Stat color="#dc2626" label="Falhas" value={result.failed} testid="bulk-result-failed" />
          </div>
          {result.errors?.length > 0 && (
            <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 10, padding: 10, fontSize: 12, color: "#7f1d1d", maxHeight: 180, overflowY: "auto" }}>
              <strong>Erros:</strong>
              <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                {result.errors.map((er, i) => (
                  <li key={i}><code style={{ background: "#fee2e2", padding: "1px 4px", borderRadius: 4 }}>{er.id.slice(0, 8)}…</code> {er.error}</li>
                ))}
              </ul>
            </div>
          )}
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14 }}>
            <Button onClick={onDone} data-testid="bulk-result-close">Fechar</Button>
          </div>
        </div>
      </Overlay>
    );
  }

  return (
    <Overlay onClose={onClose}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} data-testid="bulk-action-modal" style={modalCss(460)}>
        <h2 style={{ margin: 0, fontSize: 18, color: cfg.color }}>{cfg.icon} {cfg.title}</h2>
        <p style={{ color: "#64748b", fontSize: 13, margin: "6px 0 14px" }}>
          Aplicando em <strong data-testid="bulk-action-count">{ticketIds.length}</strong> serviço(s).
        </p>

        {requireDate && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
            <div>
              <label style={lblCss}>Nova data *</label>
              <input data-testid="bulk-resched-date" type="date" required min={new Date().toISOString().slice(0, 10)}
                value={date} onChange={(e) => setDate(e.target.value)} style={inputCss} />
            </div>
            <div>
              <label style={lblCss}>Novo horário *</label>
              <input data-testid="bulk-resched-time" type="time" required value={time}
                onChange={(e) => setTime(e.target.value)} style={inputCss} />
            </div>
          </div>
        )}

        <label style={lblCss}>{requireNotes ? `Motivo do ${cfg.verb} *` : "Notas (opcional)"}</label>
        <textarea data-testid="bulk-action-notes" rows={3}
          required={requireNotes}
          placeholder={action === "cancelar" ? "Ex.: cliente desistiu, endereço incorreto..."
            : action === "reagendar" ? "Ex.: cliente solicitou novo horário..."
            : "Notas internas (opcional)"}
          value={notes} onChange={(e) => setNotes(e.target.value)} style={{ ...inputCss, resize: "vertical" }} />

        {err && (
          <div data-testid="bulk-action-error" style={{ background: "#fee2e2", color: "#7f1d1d", padding: 8, borderRadius: 8, fontSize: 12, marginTop: 8 }}>
            {err}
          </div>
        )}

        <div style={{ background: "#f8fafc", padding: 10, borderRadius: 10, fontSize: 12, color: "#475569", margin: "12px 0" }}>
          ℹ️ Notas já encerradas/canceladas/finalizadas serão ignoradas e listadas como falhas.
          {(action === "cancelar" || action === "reagendar") && " O técnico será notificado de cada nota afetada."}
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <Button variant="soft" type="button" onClick={onClose} data-testid="bulk-action-cancel" style={{ flex: 1 }}>Voltar</Button>
          <Button type="submit" disabled={busy} data-testid="bulk-action-confirm" style={{ flex: 1, background: cfg.color, borderColor: cfg.color }}>
            {busy ? "Processando..." : cfg.confirmLabel}
          </Button>
        </div>
      </form>
    </Overlay>
  );
}

function BulkAiModal({ ticketIds, onClose }) {
  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState([]);
  const [err, setErr] = useState("");

  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await api.lousaBulkAiEvaluate(ticketIds);
        if (alive) setItems(r.items || []);
      } catch (e) {
        if (alive) setErr(e?.response?.data?.detail || e.message || "Erro");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [ticketIds]);

  return (
    <Overlay onClose={onClose}>
      <div data-testid="bulk-ai-modal" onClick={(e) => e.stopPropagation()} style={modalCss(640)}>
        <h2 style={{ margin: 0, fontSize: 18 }}>Avaliação IA — lote de {ticketIds.length}</h2>
        <p style={{ color: "#64748b", fontSize: 12, margin: "6px 0 14px" }}>
          Score heurístico (sinais cumulativos: SLA, distância, histórico, gap, geofence).
        </p>

        {loading && <div style={{ textAlign: "center", padding: 30, color: "#64748b" }}>Avaliando…</div>}
        {err && <div style={{ background: "#fee2e2", color: "#7f1d1d", padding: 10, borderRadius: 8 }}>{err}</div>}

        {!loading && !err && (
          <div style={{ maxHeight: 460, overflowY: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
            {items.map((it) => (
              <div key={it.ticket_id} data-testid={`bulk-ai-item-${it.ticket_id}`} style={{
                border: "1px solid #e2e8f0", borderRadius: 10, padding: 10,
                display: "flex", alignItems: "center", gap: 10,
              }}>
                <span style={{
                  width: 56, height: 36, borderRadius: 8, display: "grid", placeItems: "center",
                  background: aiColor(it.ai_score), color: "white", fontWeight: 900, fontSize: 14, flexShrink: 0,
                }}>{(it.ai_score ?? 0).toFixed(1)}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 700 }}>{it.client_name} <span style={{ color: "#94a3b8", fontWeight: 400, fontSize: 11 }}>· {it.type} · {it.status}</span></div>
                  <div style={{ fontSize: 11, color: "#475569" }}>
                    <strong>{it.verdict}</strong>
                    {it.duration_minutes != null && <> · {Math.round(it.duration_minutes)}min</>}
                    {it.signals?.length > 0 && <> · {it.signals.length} sinal(is)</>}
                  </div>
                  {it.signals?.length > 0 && (
                    <div style={{ fontSize: 10, color: "#64748b", marginTop: 4 }}>
                      {it.signals.slice(0, 2).map((s, i) => (
                        <span key={i} style={{
                          display: "inline-block", marginRight: 6,
                          padding: "1px 6px", borderRadius: 5,
                          background: s.level === "critical" ? "#fee2e2" : s.level === "warning" ? "#fef3c7" : "#dcfce7",
                          color: s.level === "critical" ? "#7f1d1d" : s.level === "warning" ? "#78350f" : "#166534",
                        }}>{s.msg}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {items.length === 0 && <div style={{ textAlign: "center", padding: 24, color: "#94a3b8" }}>Nenhum resultado.</div>}
          </div>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14 }}>
          <Button onClick={onClose} data-testid="bulk-ai-close">Fechar</Button>
        </div>
      </div>
    </Overlay>
  );
}

function Overlay({ children, onClose }) {
  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,.55)", zIndex: 120,
      display: "grid", placeItems: "center", padding: 20,
    }}>{children}</div>
  );
}

function Stat({ color, label, value, testid }) {
  return (
    <div data-testid={testid} style={{
      flex: 1, background: color + "15", border: `1px solid ${color}55`, borderRadius: 12,
      padding: 12, textAlign: "center",
    }}>
      <div style={{ fontSize: 26, fontWeight: 900, color }}>{value}</div>
      <div style={{ fontSize: 11, color: "#475569", fontWeight: 700 }}>{label}</div>
    </div>
  );
}

function aiColor(score) {
  if (score == null) return "#94a3b8";
  if (score >= 8.5) return "#10b981";
  if (score >= 7.0) return "#3b82f6";
  if (score >= 5.0) return "#f59e0b";
  return "#dc2626";
}

const inputCss = { width: "100%", padding: "8px 10px", border: "1px solid #cbd5e1", borderRadius: 10, fontSize: 13, marginBottom: 8, boxSizing: "border-box" };
const lblCss = { fontSize: 12, color: "#64748b", fontWeight: 700, display: "block", marginBottom: 2 };
const modalCss = (max) => ({
  background: "white", borderRadius: 18, padding: 22, maxWidth: max, width: "100%",
  maxHeight: "92vh", overflowY: "auto",
});
