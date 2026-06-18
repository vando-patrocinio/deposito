/**
 * Watchtower Estoque · Diagnóstico — Onda C P1 (18/06/2026)
 *
 * Sub-aba dentro do Watchtower Estoque. EKG da Lousa Mobile.
 * Backend: GET /api/watchtower/estoque/diagnostico
 *
 * Blocos:
 *   1) Saúde 6-Phase (sucesso/erro/latência)
 *   2) ONT Swap pending_confirmation (alerta operacional Onda C Bug #6)
 *   3) Workers: late_close + reconcile
 *   4) Erros recentes (últimos 20)
 */
import React, { useEffect, useState, useCallback } from "react";
import { client } from "./api";

const PHASE_COLORS = {
  ok: "bg-emerald-500",
  error: "bg-rose-500",
  not_ok: "bg-amber-500",
};

const fmtMs = (v) => {
  if (v == null) return "—";
  if (v < 1000) return `${Math.round(v)} ms`;
  return `${(v / 1000).toFixed(2)} s`;
};
const fmtInt = (v) => (v == null ? "—" : Number(v).toLocaleString("pt-BR"));
const fmtPct = (v) => (v == null ? "—" : `${Number(v).toFixed(1)}%`);
const fmtDate = (iso) => {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  } catch { return iso; }
};

export default function WatchtowerEstoqueDiagnostico() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [windowH, setWindowH] = useState(24);

  const fetchDiagnostico = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await client.get(
        `/watchtower/estoque/diagnostico?window_hours=${windowH}`
      );
      setData(res.data);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha ao carregar diagnóstico");
    } finally {
      setLoading(false);
    }
  }, [windowH]);

  useEffect(() => {
    const t = setTimeout(fetchDiagnostico, 0);
    return () => clearTimeout(t);
  }, [fetchDiagnostico]);

  if (loading && !data) {
    return (
      <div
        className="min-h-[300px] flex items-center justify-center text-slate-400"
        data-testid="diagnostico-loading"
      >
        <div className="animate-pulse">Carregando diagnóstico Lousa Mobile…</div>
      </div>
    );
  }
  if (err) {
    return (
      <div
        className="min-h-[300px] flex items-center justify-center"
        data-testid="diagnostico-error"
      >
        <div className="bg-rose-950/40 border border-rose-500/30 text-rose-200 px-6 py-4 rounded-lg max-w-md">
          <div className="font-bold mb-1">Erro ao carregar diagnóstico</div>
          <div className="text-sm">{String(err)}</div>
          <button
            onClick={fetchDiagnostico}
            data-testid="diagnostico-retry-btn"
            className="mt-3 px-3 py-1.5 bg-rose-500/20 hover:bg-rose-500/30 rounded text-xs font-semibold"
          >Tentar novamente</button>
        </div>
      </div>
    );
  }

  const phases = data?.phases || [];
  const latency = data?.latency || {};
  const lateClose = data?.late_close || {};
  const reconcile = data?.reconcile || {};
  const swap = data?.swap_pending || {};
  const errors = data?.recent_errors || [];

  return (
    <div className="space-y-6" data-testid="diagnostico-root">
      {/* Window selector */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 text-sm text-slate-400">
          <span>Janela:</span>
          {[1, 6, 24, 72, 168].map((h) => (
            <button
              key={h}
              type="button"
              data-testid={`diagnostico-window-${h}h`}
              onClick={() => setWindowH(h)}
              className={`px-2.5 py-1 rounded text-xs font-mono ${
                windowH === h
                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                  : "bg-slate-800/60 text-slate-300 hover:bg-slate-700"
              }`}
            >
              {h < 24 ? `${h}h` : `${h / 24}d`}
            </button>
          ))}
        </div>
        <button
          type="button"
          data-testid="diagnostico-refresh-btn"
          onClick={fetchDiagnostico}
          disabled={loading}
          className="px-3 py-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 text-emerald-300 rounded text-xs font-semibold disabled:opacity-50"
        >
          {loading ? "…" : "↻ Refresh"}
        </button>
      </div>

      {/* Block 1 — 6-Phase EKG */}
      <div
        className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6"
        data-testid="diagnostico-card-phases"
      >
        <div className="flex items-center justify-between mb-1">
          <div>
            <div className="text-xs uppercase tracking-widest text-slate-400 font-mono">
              Lousa Mobile · 6-Phase EKG
            </div>
            <h2 className="text-lg font-semibold text-white mt-0.5">
              Saúde do fluxo de fechamento de OS
            </h2>
          </div>
          <div className="text-right">
            <div className="text-xs text-slate-400">Latência p50 / p95</div>
            <div
              className="text-sm font-mono text-white"
              data-testid="diagnostico-latency"
            >
              {fmtMs(latency.p50_ms)} · {fmtMs(latency.p95_ms)}
            </div>
            <div className="text-xs text-slate-500">
              {fmtInt(latency.samples)} amostras · {fmtPct(latency.completed_pct)} completas
            </div>
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
          {phases.map((ph) => {
            const successPct = ph.success_rate_pct;
            const hasError = ph.error > 0;
            return (
              <div
                key={ph.phase}
                data-testid={`diagnostico-phase-${ph.phase}`}
                className={`rounded-lg border p-4 ${
                  hasError
                    ? "border-rose-500/40 bg-rose-500/5"
                    : "border-slate-700 bg-slate-900/40"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-white">
                    {ph.label}
                  </span>
                  <span
                    className={`text-xs font-mono ${
                      successPct === null
                        ? "text-slate-500"
                        : successPct >= 99
                        ? "text-emerald-300"
                        : successPct >= 90
                        ? "text-amber-300"
                        : "text-rose-300"
                    }`}
                  >
                    {successPct == null ? "sem dados" : `${successPct}%`}
                  </span>
                </div>
                {/* Stacked bar */}
                <div className="h-2 bg-slate-800 rounded-full mt-2 overflow-hidden flex">
                  {ph.total > 0 ? (
                    <>
                      <div
                        className={PHASE_COLORS.ok}
                        style={{ width: `${(ph.ok / ph.total) * 100}%` }}
                      />
                      <div
                        className={PHASE_COLORS.not_ok}
                        style={{ width: `${(ph.not_ok / ph.total) * 100}%` }}
                      />
                      <div
                        className={PHASE_COLORS.error}
                        style={{ width: `${(ph.error / ph.total) * 100}%` }}
                      />
                    </>
                  ) : null}
                </div>
                <div className="grid grid-cols-3 gap-2 mt-3 text-xs">
                  <div>
                    <div className="text-emerald-400">{fmtInt(ph.ok)}</div>
                    <div className="text-slate-500">ok</div>
                  </div>
                  <div>
                    <div className="text-amber-400">{fmtInt(ph.not_ok)}</div>
                    <div className="text-slate-500">not_ok</div>
                  </div>
                  <div>
                    <div className="text-rose-400">{fmtInt(ph.error)}</div>
                    <div className="text-slate-500">error</div>
                  </div>
                </div>
                {ph.last_error && (
                  <div
                    className="mt-3 text-xs text-rose-200 bg-rose-950/40 rounded p-2 border border-rose-500/20"
                    data-testid={`diagnostico-phase-${ph.phase}-last-error`}
                  >
                    <div className="font-mono text-rose-300/80">
                      último erro · {fmtDate(ph.last_error.ts)}
                    </div>
                    <div className="mt-1 break-all">{ph.last_error.error}</div>
                    <div className="text-slate-500 mt-1 font-mono">
                      ticket: {ph.last_error.ticket_id}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Block 2 — ONT Swap pending (Onda C Bug #6) */}
      <div
        className={`rounded-2xl border p-6 ${
          swap.total_pending > 0
            ? "border-amber-500/40 bg-amber-500/5"
            : "border-slate-800 bg-slate-900/60"
        }`}
        data-testid="diagnostico-card-swap"
      >
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="text-xs uppercase tracking-widest text-amber-400/80 font-mono">
              Onda C · Bug #6 · Auto-detect ONT Swap
            </div>
            <h2 className="text-lg font-semibold text-white mt-0.5">
              Trocas detectadas · aguardando confirmação
            </h2>
          </div>
          <div
            className="text-3xl font-bold text-amber-300 tabular-nums"
            data-testid="diagnostico-swap-total"
          >
            {fmtInt(swap.total_pending)}
          </div>
        </div>
        {swap.total_pending === 0 ? (
          <div className="text-sm text-slate-400">
            ✅ Nenhuma troca pendente de confirmação.
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-2">
            <div>
              <div className="text-xs text-slate-400 mb-2 uppercase tracking-wider">
                Top 5 técnicos
              </div>
              <div className="space-y-1.5">
                {(swap.top_techs || []).map((t) => (
                  <div
                    key={t.technician_id}
                    data-testid={`diagnostico-swap-tech-${t.technician_id}`}
                    className="flex items-center justify-between px-3 py-1.5 bg-slate-800/40 rounded text-sm"
                  >
                    <span className="text-slate-200">{t.technician_name}</span>
                    <span className="text-amber-300 tabular-nums font-mono">
                      {fmtInt(t.pending_count)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-400 mb-2 uppercase tracking-wider">
                Últimos eventos
              </div>
              <div className="space-y-1.5 max-h-64 overflow-auto pr-1">
                {(swap.last_events || []).map((evt) => (
                  <div
                    key={evt.id}
                    data-testid={`diagnostico-swap-event-${evt.id}`}
                    className="px-3 py-2 bg-slate-800/40 rounded text-xs"
                  >
                    <div className="flex justify-between text-slate-400 font-mono">
                      <span>{evt.ticket_type}</span>
                      <span>{fmtDate(evt.detected_at)}</span>
                    </div>
                    <div className="text-slate-200 mt-0.5">
                      <code className="text-rose-300/80">{evt.ont_anterior}</code>
                      {" → "}
                      <code className="text-emerald-300/80">{evt.ont_atual}</code>
                    </div>
                    <div className="text-slate-500 mt-0.5">
                      {evt.technician_name}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Block 3 — Workers */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div
          className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6"
          data-testid="diagnostico-card-late-close"
        >
          <div className="text-xs uppercase tracking-widest text-sky-400/80 font-mono">
            Onda B · Worker
          </div>
          <h2 className="text-lg font-semibold text-white mt-0.5">
            late_close_worker (rede de segurança)
          </h2>
          <div className="grid grid-cols-3 gap-3 mt-4">
            <KPI label="Runs 7d" value={fmtInt(lateClose.runs_7d)} testid="late-close-runs-7d" />
            <KPI label="Fechados ok" value={fmtInt(lateClose.total_closed_ok_7d)} testid="late-close-ok-7d" color="text-emerald-300" />
            <KPI label="Falhas" value={fmtInt(lateClose.total_closed_failed_7d)} testid="late-close-fail-7d" color={lateClose.total_closed_failed_7d > 0 ? "text-rose-300" : "text-slate-300"} />
          </div>
          {lateClose.last_run && (
            <div className="mt-4 text-xs text-slate-400 font-mono space-y-0.5">
              <div>último: {fmtDate(lateClose.last_run.started_at)}</div>
              <div>candidatos: {fmtInt(lateClose.last_run.candidates_found)} · duração: {fmtMs(lateClose.last_run.duration_ms)}</div>
            </div>
          )}
        </div>
        <div
          className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6"
          data-testid="diagnostico-card-reconcile"
        >
          <div className="text-xs uppercase tracking-widest text-violet-400/80 font-mono">
            Onda A · Cron diário
          </div>
          <h2 className="text-lg font-semibold text-white mt-0.5">
            stok_reconcile_job (órfãs)
          </h2>
          <div className="grid grid-cols-3 gap-3 mt-4">
            <KPI label="Runs 7d" value={fmtInt(reconcile.runs_7d)} testid="reconcile-runs-7d" />
            <KPI label="Scanned" value={fmtInt(reconcile.total_scanned_7d)} testid="reconcile-scanned-7d" />
            <KPI label="Marcadas órfãs" value={fmtInt(reconcile.total_orphan_marked_7d)} testid="reconcile-orphans-7d" color={reconcile.total_orphan_marked_7d > 0 ? "text-amber-300" : "text-slate-300"} />
          </div>
          {reconcile.last_run && (
            <div className="mt-4 text-xs text-slate-400 font-mono space-y-0.5">
              <div>último: {fmtDate(reconcile.last_run.started_at)}</div>
              <div>alertas levantados: {fmtInt(reconcile.last_run.alerts_raised_count)}</div>
            </div>
          )}
        </div>
      </div>

      {/* Block 4 — Recent errors */}
      <div
        className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6"
        data-testid="diagnostico-card-errors"
      >
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="text-xs uppercase tracking-widest text-rose-400/80 font-mono">
              Últimos 20 erros · janela {windowH}h
            </div>
            <h2 className="text-lg font-semibold text-white mt-0.5">
              Auto-close errors detalhados
            </h2>
          </div>
          <div className="text-2xl font-bold text-rose-300 tabular-nums" data-testid="diagnostico-errors-count">
            {fmtInt(errors.length)}
          </div>
        </div>
        {errors.length === 0 ? (
          <div className="text-sm text-slate-400">
            ✅ Sem erros recentes nessa janela. Saúde verde.
          </div>
        ) : (
          <div className="space-y-2 max-h-96 overflow-auto pr-1">
            {errors.map((e, i) => (
              <div
                key={`${e.ticket_id}-${e.phase}-${i}`}
                data-testid={`diagnostico-error-row-${i}`}
                className="bg-rose-950/30 border border-rose-500/20 rounded-lg p-3 text-xs"
              >
                <div className="flex justify-between text-rose-300/80 font-mono">
                  <span>{e.phase}</span>
                  <span>{fmtDate(e.ts)}</span>
                </div>
                <div className="text-slate-200 mt-1 break-words">{e.error}</div>
                <div className="text-slate-500 mt-1 font-mono">
                  ticket: {e.ticket_id}
                  {e.result_reason ? ` · reason: ${e.result_reason}` : ""}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function KPI({ label, value, testid, color = "text-white" }) {
  return (
    <div data-testid={testid}>
      <div className="text-xs text-slate-400 uppercase tracking-wider">{label}</div>
      <div className={`text-xl font-bold tabular-nums mt-0.5 ${color}`}>{value}</div>
    </div>
  );
}
