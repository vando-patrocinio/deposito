/**
 * ScoreRecoveryBlock.jsx — iter241
 * Card de ação dentro do Cérebro Executivo V10:
 *   • Simular limpeza (mostra delta projetado)
 *   • Executar (com motivo obrigatório)
 *   • Mini gráfico do histórico de score
 *   • Lista de batches reversíveis (com rollback)
 */
import React, { useEffect, useState } from "react";
import {
  Rocket, ShieldCheck, RotateCcw, Activity, AlertCircle,
  CheckCircle2, TrendingUp, Loader2,
} from "lucide-react";
import { api } from "@/lib/apiClient";

const COLORS = {
  bg: "#0e1015", card: "#1a1d27", cardSoft: "#252836",
  text: "#e5e7eb", muted: "#9ca3af", border: "#2d3142",
  green: "#10b981", red: "#ef4444", amber: "#f59e0b",
  blue: "#3b82f6", purple: "#8b5cf6",
};

export default function ScoreRecoveryBlock() {
  const [sim, setSim] = useState(null);
  const [hist, setHist] = useState([]);
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [executing, setExecuting] = useState(false);
  const [showExec, setShowExec] = useState(false);
  const [reason, setReason] = useState("");
  const [feedback, setFeedback] = useState(null);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [s, h, b] = await Promise.all([
        api.get("/api/presidente-ia/score-recovery/simulate"),
        api.get("/api/presidente-ia/score-history?days=30"),
        api.get("/api/presidente-ia/score-recovery/batches"),
      ]);
      setSim(s); setHist(h.history || []); setBatches(b.batches || []);
    } catch (e) {
      setFeedback({ kind: "err",
        msg: e?.response?.data?.detail || e.message });
    } finally { setLoading(false); }
  };
  useEffect(() => { loadAll(); }, []);

  const snapshot = async () => {
    try {
      await api.post("/api/presidente-ia/score-history/snapshot");
      await loadAll();
    } catch (e) { setFeedback({ kind: "err", msg: e.message }); }
  };

  const execute = async () => {
    if (reason.trim().length < 10) {
      setFeedback({ kind: "err", msg: "Informe motivo com 10+ caracteres." });
      return;
    }
    setExecuting(true); setFeedback(null);
    try {
      const r = await api.post("/api/presidente-ia/score-recovery/execute",
                                  { reason });
      setFeedback({ kind: "ok",
        msg: `Recuperação executada (batch ${r.batch_id}). Score após: ${r.score_after ?? "—"}.` });
      setShowExec(false); setReason("");
      await loadAll();
    } catch (e) {
      setFeedback({ kind: "err",
        msg: e?.response?.data?.detail || e.message });
    } finally { setExecuting(false); }
  };

  const rollback = async (batchId) => {
    if (!window.confirm(`Reverter o batch ${batchId}? Restaura ONUs e reabre tickets fechados.`)) return;
    try {
      await api.post(`/api/presidente-ia/score-recovery/rollback/${batchId}`);
      setFeedback({ kind: "ok", msg: `Batch ${batchId} revertido.` });
      await loadAll();
    } catch (e) {
      setFeedback({ kind: "err",
        msg: e?.response?.data?.detail || e.message });
    }
  };

  if (loading) return (
    <div data-testid="score-recovery-loading" style={{
      ...card, color: COLORS.muted, padding: 14 }}>
      <Loader2 size={14} style={{ verticalAlign: "middle",
        marginRight: 6, animation: "spin 1s linear infinite" }}/>
      Calculando recuperação...
    </div>
  );

  if (!sim) {
    return (
      <div data-testid="score-recovery-error" style={{ ...card,
        color: COLORS.red, padding: 14, fontSize: 13 }}>
        <AlertCircle size={14} style={{ verticalAlign: "middle",
          marginRight: 6 }}/>
        Falha ao carregar recuperação: {feedback?.msg || "verifique se o endpoint /api/presidente-ia/score-recovery/simulate está acessível."}
        <button data-testid="btn-retry-recover" onClick={loadAll}
          style={{ ...btnGhost, marginLeft: 12 }}>Tentar novamente</button>
      </div>
    );
  }
  const cur = sim.current || {};
  const proj = sim.projected || {};
  const act = sim.actions || {};
  const deltaPositive = (proj.delta || 0) > 0;

  return (
    <div data-testid="score-recovery-block" style={card}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Rocket size={18} color={COLORS.purple}/>
          <strong style={{ color: COLORS.text, fontSize: 15 }}>
            Recuperar Score
          </strong>
          <span style={{ background: deltaPositive ? "#10b98122" : "#9ca3af22",
            color: deltaPositive ? COLORS.green : COLORS.muted,
            fontSize: 10, padding: "3px 8px", borderRadius: 999,
            fontWeight: 700, textTransform: "uppercase" }}>
            {deltaPositive ? `+${proj.delta} pts disponível` : "tudo limpo"}
          </span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button data-testid="btn-score-snapshot" onClick={snapshot}
            style={btnGhost}><Activity size={12}/> Snapshot</button>
          <button data-testid="btn-score-reload" onClick={loadAll}
            style={btnGhost}>Recarregar</button>
        </div>
      </div>

      {/* Linha: score atual → projetado */}
      <div style={{ display: "grid",
        gridTemplateColumns: "1fr auto 1fr", gap: 14, alignItems: "center" }}>
        <ScorePill label="Score atual" value={cur.score}
          color={COLORS.red} testid="score-current"/>
        <TrendingUp size={28} color={deltaPositive ? COLORS.green : COLORS.muted}
          style={{ justifySelf: "center" }}/>
        <ScorePill label="Score projetado pós-limpeza" value={proj.score}
          color={proj.score >= 90 ? COLORS.green :
                 proj.score >= 65 ? COLORS.amber : COLORS.red}
          testid="score-projected"/>
      </div>

      {/* Ações que serão executadas */}
      <div style={{ marginTop: 14, padding: 12, background: COLORS.cardSoft,
        borderRadius: 8, border: `1px dashed ${COLORS.border}` }}>
        <div style={{ color: COLORS.muted, fontSize: 11, fontWeight: 700,
          textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 8 }}>
          O que será feito (reversível)
        </div>
        <div style={{ display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: 10, fontSize: 12 }}>
          <ActionStat label="ONUs status=null"
            value={act.onus_status_null_to_archive}
            sub="arquivar" testid="act-onus-null"/>
          <ActionStat label="ONUs LOS/Offline"
            value={act.onus_los_offline_to_archive}
            sub={`arquivar (${sim.params.days_los_archive}d+)`}
            testid="act-onus-los"/>
          <ActionStat label="Tickets stale"
            value={act.tickets_stale_to_autoclose}
            sub={`auto-fechar (${sim.params.days_ticket_autoclose}d+)`}
            testid="act-tickets-stale"/>
          <ActionStat label="ONUs depois"
            value={act.onus_total_after}
            sub={`era ${act.onus_total_before}`} testid="act-onus-after"/>
        </div>
      </div>

      {feedback && (
        <div data-testid={`feedback-${feedback.kind}`} style={{
          ...feedbackBase,
          background: feedback.kind === "ok" ? "#10b98122" : "#ef444422",
          color: feedback.kind === "ok" ? COLORS.green : COLORS.red,
        }}>
          {feedback.kind === "ok" ? <CheckCircle2 size={14}/>
                                  : <AlertCircle size={14}/>}
          {feedback.msg}
        </div>
      )}

      {/* Botão executar */}
      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        {!showExec ? (
          <button data-testid="btn-score-recover"
            onClick={() => setShowExec(true)}
            disabled={!deltaPositive}
            style={{ ...btnPrimary, flex: 1,
              opacity: deltaPositive ? 1 : 0.5,
              cursor: deltaPositive ? "pointer" : "not-allowed" }}>
            <Rocket size={14}/> Executar recuperação
          </button>
        ) : (
          <div style={{ flex: 1, display: "flex", flexDirection: "column",
            gap: 6 }}>
            <input data-testid="input-recovery-reason" autoFocus
              placeholder="Motivo / aprovação CTO (mínimo 10 caracteres)"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              style={input}/>
            <div style={{ display: "flex", gap: 6 }}>
              <button data-testid="btn-confirm-recover" onClick={execute}
                disabled={executing}
                style={{ ...btnPrimary, flex: 1 }}>
                {executing
                  ? <><Loader2 size={14}
                       style={{ animation: "spin 1s linear infinite" }}/>
                     Executando...</>
                  : <><ShieldCheck size={14}/> Confirmar e executar</>}
              </button>
              <button data-testid="btn-cancel-recover"
                onClick={() => { setShowExec(false); setReason(""); }}
                style={btnGhost}>Cancelar</button>
            </div>
          </div>
        )}
      </div>

      {/* Histórico de batches */}
      {batches.length > 0 && (
        <div data-testid="batches-section" style={{ marginTop: 14 }}>
          <div style={{ color: COLORS.muted, fontSize: 11, fontWeight: 700,
            textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 6 }}>
            Histórico de recuperações ({batches.length})
          </div>
          <div style={{ display: "grid", gap: 6 }}>
            {batches.slice(0, 5).map((b) => (
              <div key={b.batch_id} data-testid={`batch-${b.batch_id}`}
                style={{ background: COLORS.cardSoft, padding: 10,
                  borderRadius: 8, fontSize: 11, display: "flex",
                  justifyContent: "space-between", alignItems: "center" }}>
                <div style={{ color: COLORS.text }}>
                  <strong>{b.batch_id}</strong>{" · "}
                  <span style={{ color: COLORS.muted }}>
                    {new Date(b.executed_at).toLocaleString("pt-BR")}{" · "}
                    {b.actions?.onus_archived_null
                      + b.actions?.onus_archived_los} ONUs · {" "}
                    {b.actions?.tickets_autoclosed} tickets
                  </span>
                </div>
                {b.rolled_back_at ? (
                  <span style={{ color: COLORS.amber, fontSize: 10,
                    fontWeight: 700 }}>REVERTIDO</span>
                ) : (
                  <button data-testid={`btn-rollback-${b.batch_id}`}
                    onClick={() => rollback(b.batch_id)}
                    style={{ ...btnGhost, color: COLORS.amber }}>
                    <RotateCcw size={11}/> Reverter
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Mini gráfico de histórico */}
      {hist.length > 0 && (
        <ScoreSparkline points={hist} testid="score-sparkline"/>
      )}
    </div>
  );
}

function ScorePill({ label, value, color, testid }) {
  return (
    <div data-testid={testid} style={{
      padding: 14, borderRadius: 10, background: COLORS.cardSoft,
      borderLeft: `4px solid ${color}` }}>
      <div style={{ color: COLORS.muted, fontSize: 10, fontWeight: 700,
        textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
      <div style={{ color, fontSize: 36, fontWeight: 800,
        marginTop: 4, lineHeight: 1 }}>
        {value != null ? value.toFixed(1) : "—"}
        <span style={{ fontSize: 14, color: COLORS.muted,
          marginLeft: 4 }}>/100</span>
      </div>
    </div>
  );
}

function ActionStat({ label, value, sub, testid }) {
  return (
    <div data-testid={testid} style={{ background: COLORS.bg,
      padding: 10, borderRadius: 6 }}>
      <div style={{ color: COLORS.muted, fontSize: 10, fontWeight: 600,
        textTransform: "uppercase" }}>{label}</div>
      <div style={{ color: COLORS.text, fontSize: 18, fontWeight: 800,
        marginTop: 2 }}>{value ?? 0}</div>
      <div style={{ color: COLORS.muted, fontSize: 10 }}>{sub}</div>
    </div>
  );
}

function ScoreSparkline({ points, testid }) {
  if (!points || points.length < 2) {
    return (
      <div data-testid={testid} style={{ marginTop: 14, padding: 10,
        background: COLORS.cardSoft, borderRadius: 8, fontSize: 11,
        color: COLORS.muted, textAlign: "center" }}>
        Histórico ainda não tem 2+ snapshots — clique em <strong>Snapshot</strong> para
        registrar agora. O cron roda diariamente às 03:15.
      </div>
    );
  }
  const W = 600, H = 80, pad = 8;
  const vals = points.map((p) => p.score || 0);
  const min = Math.min(...vals, 0);
  const max = Math.max(...vals, 100);
  const span = Math.max(1, max - min);
  const path = points.map((p, i) => {
    const x = pad + (i / (points.length - 1)) * (W - pad * 2);
    const y = H - pad - ((p.score - min) / span) * (H - pad * 2);
    return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
  return (
    <div data-testid={testid} style={{ marginTop: 14 }}>
      <div style={{ color: COLORS.muted, fontSize: 11, fontWeight: 700,
        textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 6 }}>
        Histórico do Score ({points.length} snapshots · 30d)
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%",
        background: COLORS.cardSoft, borderRadius: 8 }}>
        <line x1={pad} x2={W - pad} y1={H / 2} y2={H / 2}
          stroke={COLORS.border} strokeDasharray="3 3"/>
        <path d={path} fill="none" stroke={COLORS.green} strokeWidth="2"/>
        {points.map((p, i) => {
          const x = pad + (i / (points.length - 1)) * (W - pad * 2);
          const y = H - pad - ((p.score - min) / span) * (H - pad * 2);
          return <circle key={i} cx={x} cy={y} r="3"
            fill={COLORS.green} stroke={COLORS.cardSoft} strokeWidth="1"/>;
        })}
      </svg>
    </div>
  );
}

const card = { background: COLORS.card, border: `1px solid ${COLORS.border}`,
  borderRadius: 12, padding: 16 };
const btnPrimary = { background: COLORS.purple, color: "white", border: 0,
  borderRadius: 8, padding: "10px 16px", fontWeight: 700, fontSize: 13,
  cursor: "pointer", display: "inline-flex", alignItems: "center",
  justifyContent: "center", gap: 6 };
const btnGhost = { background: "transparent", color: COLORS.text,
  border: `1px solid ${COLORS.border}`, borderRadius: 6, padding: "5px 10px",
  fontSize: 11, cursor: "pointer", display: "inline-flex",
  alignItems: "center", gap: 4 };
const input = { width: "100%", padding: "10px 12px", borderRadius: 8,
  border: `1px solid ${COLORS.border}`, background: COLORS.cardSoft,
  color: COLORS.text, fontSize: 13, fontFamily: "inherit" };
const feedbackBase = { marginTop: 12, padding: 10, borderRadius: 8,
  fontSize: 12, display: "flex", alignItems: "center", gap: 6 };
