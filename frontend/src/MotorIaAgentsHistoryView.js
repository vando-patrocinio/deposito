import React, { useEffect, useState, useCallback, useMemo } from "react";
import { api } from "@/api";
import { Loader2, History, Power, PowerOff } from "lucide-react";

const PERIODS = [
  { label: "24h", days: 1 },
  { label: "7 dias", days: 7 },
  { label: "30 dias", days: 30 },
  { label: "90 dias", days: 90 },
];

function fmtDuration(secs) {
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.round(secs / 60)}min`;
  if (secs < 86400) return `${(secs / 3600).toFixed(1)}h`;
  return `${(secs / 86400).toFixed(1)}d`;
}

function fmtDate(iso) {
  return new Date(iso).toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

/**
 * Timeline horizontal: para cada agente, exibe segmentos verde (ON) /
 * vermelho (OFF) ao longo do período. Hover mostra detalhes.
 */
export default function MotorIaAgentsHistoryView() {
  const [data, setData] = useState(null);
  const [days, setDays] = useState(7);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [hover, setHover] = useState(null);

  const load = useCallback(async (d) => {
    setLoading(true); setErr("");
    try {
      const r = await api.motorIaAgentsHistory(d);
      setData(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(days); }, [load, days]);

  const range = useMemo(() => {
    if (!data) return { start: 0, end: 1 };
    const s = new Date(data.window_start).getTime();
    const e = new Date(data.window_end).getTime();
    return { start: s, end: e, span: e - s };
  }, [data]);

  if (loading) {
    return (
      <div style={{ padding: 30, textAlign: "center",
                      color: "var(--text-muted, #64748b)", fontSize: 13,
                      display: "flex", justifyContent: "center", alignItems: "center", gap: 8 }}>
        <Loader2 size={14} className="animate-spin" /> Carregando histórico...
      </div>
    );
  }
  if (err) {
    return <div style={{ margin: 16, padding: 10, background: "#fef2f2",
                            color: "#be123c", borderRadius: 8, fontSize: 12 }}>{err}</div>;
  }
  if (!data) return null;

  return (
    <div style={{ padding: "12px 22px 20px" }}>
      {/* Seletor período */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14,
                      justifyContent: "space-between", flexWrap: "wrap" }}>
        <div style={{ fontSize: 11, color: "var(--text-muted, #64748b)" }}>
          {data.events.length} mudança(s) registrada(s)
        </div>
        <div style={{ display: "flex", gap: 4, background: "var(--surface-2, #f1f5f9)",
                        padding: 3, borderRadius: 8 }}>
          {PERIODS.map((p) => (
            <button key={p.days}
                      onClick={() => setDays(p.days)}
                      data-testid={`history-period-${p.days}`}
                      style={{
                        padding: "5px 10px", border: 0, borderRadius: 6,
                        cursor: "pointer", fontSize: 11, fontWeight: 600,
                        background: days === p.days ? "var(--bg-surface, #fff)" : "transparent",
                        color: days === p.days ? "var(--text-primary, #0f172a)" : "var(--text-muted, #64748b)",
                        boxShadow: days === p.days ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
                      }}>{p.label}</button>
          ))}
        </div>
      </div>

      {/* Timeline por agente */}
      <div style={{ position: "relative" }}>
        {data.agents_catalog.map((cat) => {
          const intervals = data.intervals_by_agent[cat.id] || [];
          const downtime = data.downtime_by_agent[cat.id] || {};
          const hasOff = intervals.some((it) => !it.enabled);
          return (
            <div key={cat.id} data-testid={`history-row-${cat.id}`}
                 style={{ display: "grid",
                            gridTemplateColumns: "160px 1fr 80px",
                            gap: 10, alignItems: "center",
                            padding: "6px 0",
                            borderBottom: "1px solid var(--border-default, #f1f5f9)" }}>
              <div style={{ fontSize: 12, fontWeight: 600,
                              color: hasOff ? "var(--text-primary, #0f172a)" : "var(--text-muted, #64748b)",
                              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
                   title={cat.label}>
                {cat.label}
              </div>
              <div style={{ position: "relative", height: 18,
                              background: "var(--surface-2, #f1f5f9)",
                              borderRadius: 4 }}>
                {intervals.map((it, idx) => {
                  const s = new Date(it.start).getTime();
                  const e = new Date(it.end).getTime();
                  const leftPct = ((s - range.start) / range.span) * 100;
                  const widthPct = ((e - s) / range.span) * 100;
                  return (
                    <div key={idx}
                         onMouseEnter={() => setHover({
                           agent: cat.label, ...it,
                           durSec: Math.round((e - s) / 1000),
                         })}
                         onMouseLeave={() => setHover(null)}
                         style={{
                           position: "absolute", top: 0, height: "100%",
                           left: `${leftPct}%`, width: `${widthPct}%`,
                           background: it.enabled ? "#10b981" : "#dc2626",
                           opacity: it.enabled ? 0.7 : 0.85,
                           cursor: "pointer",
                           transition: "opacity 0.15s",
                         }} />
                  );
                })}
                {/* Sobreposição de incidentes que afetam este agente */}
                {(data.incidents || [])
                  .filter((inc) => (inc.affects || []).includes(cat.id))
                  .map((inc, idx) => {
                    const s = new Date(inc.start).getTime();
                    const e = new Date(inc.end).getTime();
                    const leftPct = Math.max(0, ((s - range.start) / range.span) * 100);
                    const widthPct = Math.min(100 - leftPct,
                                                  ((e - s) / range.span) * 100);
                    if (widthPct < 0.1) return null;
                    return (
                      <div key={`inc-${idx}`}
                           onMouseEnter={() => setHover({
                             agent: cat.label,
                             isIncident: true,
                             ...inc,
                             durSec: Math.round((e - s) / 1000),
                           })}
                           onMouseLeave={() => setHover(null)}
                           title={inc.title}
                           style={{
                             position: "absolute",
                             top: -3, height: 24,
                             left: `${leftPct}%`, width: `${widthPct}%`,
                             borderTop: `2px solid ${inc.kind === "outage" ? "#f59e0b" : "#8b5cf6"}`,
                             borderBottom: `2px solid ${inc.kind === "outage" ? "#f59e0b" : "#8b5cf6"}`,
                             background: inc.kind === "outage"
                               ? "repeating-linear-gradient(135deg, transparent 0 4px, rgba(245,158,11,0.45) 4px 5px)"
                               : "repeating-linear-gradient(135deg, transparent 0 4px, rgba(139,92,246,0.5) 4px 5px)",
                             cursor: "pointer",
                             pointerEvents: "auto",
                           }} />
                    );
                  })}
              </div>
              <div style={{ textAlign: "right", fontSize: 11,
                              color: downtime.off_pct > 0 ? "#dc2626" : "var(--text-muted, #94a3b8)",
                              fontWeight: downtime.off_pct > 0 ? 700 : 500 }}>
                {downtime.off_pct > 0
                  ? `${downtime.off_pct}% off`
                  : "100% on"}
              </div>
            </div>
          );
        })}
      </div>

      {/* Tooltip flutuante */}
      {hover && !hover.isIncident && (
        <div style={{
          marginTop: 12, padding: 10,
          background: hover.enabled ? "#ecfdf5" : "#fef2f2",
          border: `1px solid ${hover.enabled ? "#a7f3d0" : "#fecaca"}`,
          borderRadius: 8, fontSize: 12,
          color: hover.enabled ? "#047857" : "#be123c",
          display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
        }} data-testid="history-tooltip">
          {hover.enabled ? <Power size={14} /> : <PowerOff size={14} />}
          <strong>{hover.agent}</strong>
          <span>{hover.enabled ? "ATIVO" : "PAUSADO"}</span>
          <span style={{ opacity: 0.7 }}>·</span>
          <span>de {fmtDate(hover.start)}</span>
          <span style={{ opacity: 0.7 }}>até {fmtDate(hover.end)}</span>
          <span style={{ opacity: 0.7 }}>·</span>
          <span>{fmtDuration(hover.durSec)}</span>
        </div>
      )}
      {hover && hover.isIncident && (
        <div style={{
          marginTop: 12, padding: 10,
          background: hover.kind === "outage" ? "#fffbeb" : "#f5f3ff",
          border: `1px solid ${hover.kind === "outage" ? "#fde68a" : "#ddd6fe"}`,
          borderRadius: 8, fontSize: 12,
          color: hover.kind === "outage" ? "#b45309" : "#6d28d9",
          display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
        }} data-testid="history-tooltip-incident">
          <strong>{hover.kind === "outage" ? "🟡 PANE" : "🟣 ALERTA"}</strong>
          <strong>{hover.title}</strong>
          <span style={{ opacity: 0.8 }}>· {hover.detail}</span>
          <span style={{ opacity: 0.7 }}>·</span>
          <span>{fmtDate(hover.start)} → {fmtDate(hover.end)}</span>
          <span style={{ opacity: 0.7 }}>·</span>
          <span>{fmtDuration(hover.durSec)}</span>
        </div>
      )}

      {/* Legenda */}
      <div style={{ marginTop: 14, display: "flex", gap: 16, fontSize: 11,
                      color: "var(--text-muted, #64748b)", flexWrap: "wrap" }}>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 12, height: 12, background: "#10b981",
                            opacity: 0.7, borderRadius: 2 }} /> Ativo
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 12, height: 12, background: "#dc2626",
                            opacity: 0.85, borderRadius: 2 }} /> Pausado
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 14, height: 10, borderRadius: 2,
                            background: "repeating-linear-gradient(135deg, transparent 0 3px, rgba(245,158,11,0.6) 3px 4px)",
                            border: "1px solid #f59e0b" }} />
          Pane de rede
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 14, height: 10, borderRadius: 2,
                            background: "repeating-linear-gradient(135deg, transparent 0 3px, rgba(139,92,246,0.6) 3px 4px)",
                            border: "1px solid #8b5cf6" }} />
          Alerta Sentinela
        </span>
        <span style={{ opacity: 0.7 }}>
          Passe o mouse para detalhes.
        </span>
      </div>

      {/* Log textual de eventos */}
      {data.events.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8,
                          color: "var(--text-primary, #0f172a)",
                          display: "flex", alignItems: "center", gap: 6 }}>
            <History size={13} /> Eventos recentes
          </div>
          <div style={{ display: "grid", gap: 4, maxHeight: 200, overflow: "auto" }}
               data-testid="history-events-list">
            {data.events.slice(0, 50).map((ev, i) => {
              const cat = data.agents_catalog.find((c) => c.id === ev.agent_id);
              return (
                <div key={i} style={{
                  display: "grid", gridTemplateColumns: "130px 1fr 80px 100px",
                  gap: 8, padding: "5px 8px", fontSize: 11,
                  background: "var(--surface-2, #f8fafc)", borderRadius: 4,
                  alignItems: "center",
                }}>
                  <span style={{ color: "var(--text-muted, #64748b)",
                                    fontFamily: "ui-monospace, monospace" }}>
                    {fmtDate(ev.changed_at)}
                  </span>
                  <span style={{ fontWeight: 600 }}>{cat?.label || ev.agent_id}</span>
                  <span style={{
                    fontSize: 10, fontWeight: 700, textAlign: "center",
                    padding: "2px 6px", borderRadius: 4,
                    background: ev.enabled ? "#dcfce7" : "#fee2e2",
                    color: ev.enabled ? "#16a34a" : "#dc2626",
                  }}>
                    {ev.previous_enabled ? "ON" : "OFF"} → {ev.enabled ? "ON" : "OFF"}
                  </span>
                  <span style={{ color: "var(--text-muted, #64748b)",
                                    fontSize: 10, textAlign: "right" }}>
                    {ev.changed_by}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
