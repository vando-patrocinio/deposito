import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import {
  Shield, AlertTriangle, Clock, UserX, Repeat, MapPin, ZapOff,
  CheckCircle2, X, Loader2, RefreshCw, Eye,
} from "lucide-react";

/* =============================================================
   Sentinela Lousa AI — painel de alertas autônomos da Kanban.
   Detecta: stuck, sla_warning, sla_breach, field_stuck,
   technician_overload, recurring. Auto-resolve quando condição
   deixa de existir.
============================================================= */

const KIND_META = {
  sla_breach:           { label: "SLA ESTOURADO",       icon: ZapOff,         color: "#dc2626" },
  sla_warning:          { label: "SLA QUASE",           icon: Clock,          color: "#d97706" },
  stuck:                { label: "Ticket parado",       icon: AlertTriangle,  color: "#d97706" },
  field_stuck:          { label: "Em campo travado",    icon: MapPin,         color: "#dc2626" },
  technician_overload:  { label: "Técnico sobrecarregado", icon: UserX,       color: "#d97706" },
  recurring:            { label: "Cliente recorrente",  icon: Repeat,         color: "#dc2626" },
};

const SEVERITY_COLOR = {
  high: "#dc2626",
  medium: "#d97706",
  low: "#94a3b8",
};

export default function SentinelaLousaCard() {
  const [summary, setSummary] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const reload = useCallback(async () => {
    try {
      const [s, a] = await Promise.all([
        api.sentinelaSummary(),
        api.sentinelaAlerts({ limit: 100 }),
      ]);
      setSummary(s);
      setAlerts(a.items || []);
      setErr(null);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  }, []);

  useEffect(() => {
    reload();
    const t = setInterval(reload, 30000);
    return () => clearInterval(t);
  }, [reload]);

  const forceScan = async () => {
    setBusy(true);
    try { await api.sentinelaScan(); await reload(); }
    catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };

  const ack = async (id) => {
    try { await api.sentinelaAcknowledge(id); await reload(); }
    catch (e) { await window.alert(e?.response?.data?.detail || e.message); }
  };
  const dismiss = async (id) => {
    try { await api.sentinelaDismiss(id); await reload(); }
    catch (e) { await window.alert(e?.response?.data?.detail || e.message); }
  };

  const cfg = summary?.config || {};
  const byKind = summary?.by_kind || {};

  return (
    <div data-testid="sentinela-lousa-card" style={{ display: "grid", gap: 14 }}>
      <div style={{
        padding: 18, borderRadius: 14,
        background: "linear-gradient(135deg, rgba(239,68,68,.10), rgba(217,119,6,.05))",
        border: "1px solid var(--border-default)",
      }}>
        <div style={{ display: "flex", alignItems: "flex-start",
                          justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{
              width: 46, height: 46, borderRadius: 12,
              background: "#ef4444", color: "#fff",
              display: "grid", placeItems: "center",
              boxShadow: "0 4px 14px rgba(239,68,68,.35)",
            }}>
              <Shield size={22} strokeWidth={1.75} />
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800,
                              color: "var(--text-primary)",
                              letterSpacing: "-0.02em" }}>
                Sentinela Lousa AI
              </h2>
              <p style={{ margin: "4px 0 0", fontSize: 12,
                            color: "var(--text-secondary)", maxWidth: 700,
                            lineHeight: 1.5 }}>
                Varredura autônoma a cada <strong>{cfg.interval_seconds ?? 120}s</strong>.
                Detecta SLA estourado, tickets parados há ≥{cfg.stuck_hours ?? 6}h,
                técnicos com ≥{cfg.overload_tickets ?? 8} tickets,
                visitas travadas há ≥{cfg.field_stuck_hours ?? 4}h e clientes
                recorrentes em {cfg.recurring_hours ?? 24}h. Cada alerta novo é
                analisado por <strong>Claude</strong> (priorização contextual,
                recomendação e hipótese de causa raiz).
              </p>
            </div>
          </div>
          <button onClick={forceScan} disabled={busy}
                  data-testid="sentinela-scan-btn"
                  style={{
                    padding: "8px 14px", borderRadius: 6,
                    border: "1px solid var(--border-default)",
                    background: "var(--bg-surface)",
                    color: "var(--text-primary)",
                    fontSize: 12, fontWeight: 600,
                    cursor: busy ? "wait" : "pointer",
                    display: "inline-flex", alignItems: "center", gap: 6,
                  }}>
            {busy
              ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} />
              : <RefreshCw size={13} />}
            Forçar varredura
          </button>
        </div>
      </div>

      {err && (
        <div style={{ padding: 10, borderRadius: 6, fontSize: 12,
                         background: "rgba(220,38,38,.08)", color: "#dc2626" }}>
          {err}
        </div>
      )}

      {/* KPIs */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
        gap: 10,
      }}>
        <Kpi label="Alertas ativos"
              value={summary?.active ?? 0}
              color={summary?.active > 0 ? "#dc2626" : "#16a34a"}
              icon={Shield}
              testId="sentinela-kpi-active" />
        <Kpi label="Novos (24h)"
              value={summary?.new_24h ?? 0}
              color="#d97706"
              icon={AlertTriangle}
              testId="sentinela-kpi-new" />
        <Kpi label="Auto-resolvidos (24h)"
              value={summary?.resolved_24h ?? 0}
              color="#16a34a"
              icon={CheckCircle2}
              testId="sentinela-kpi-resolved" />
      </div>

      {/* Distribuição por tipo */}
      {Object.keys(byKind).length > 0 && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
          gap: 8,
        }}>
          {Object.entries(byKind).map(([kind, n]) => {
            const m = KIND_META[kind] || {};
            const Ico = m.icon || AlertTriangle;
            return (
              <div key={kind} style={{
                padding: "8px 10px", borderRadius: 8,
                border: "1px solid var(--border-default)",
                background: "var(--bg-surface)",
                display: "flex", alignItems: "center", gap: 8,
              }}>
                <Ico size={14} style={{ color: m.color || "#64748b" }} />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 9.5, fontWeight: 700,
                                   color: "var(--text-muted)",
                                   textTransform: "uppercase",
                                   letterSpacing: 0.4 }}>
                    {m.label || kind}
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 800,
                                   color: m.color || "var(--text-primary)",
                                   fontFamily: "ui-monospace, monospace" }}>
                    {n}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Lista de alertas */}
      <div>
        <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)",
                          textTransform: "uppercase", letterSpacing: 0.6,
                          marginBottom: 10, paddingBottom: 6,
                          borderBottom: "1px solid var(--border-default)" }}>
          Alertas ativos · {alerts.length}
        </div>
        {alerts.length === 0 ? (
          <div style={{
            padding: 24, textAlign: "center",
            fontSize: 12, color: "var(--text-muted)",
            background: "var(--bg-surface)",
            border: "1px dashed var(--border-default)", borderRadius: 8,
          }}>
            <CheckCircle2 size={20} style={{ color: "#16a34a", marginBottom: 6 }} />
            <div>Nenhum alerta ativo. A Lousa está sob controle.</div>
          </div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {alerts.map((a) => (
              <AlertRow key={a.id} alert={a}
                          onAck={() => ack(a.id)}
                          onDismiss={() => dismiss(a.id)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function AlertRow({ alert, onAck, onDismiss }) {
  const m = KIND_META[alert.kind] || {};
  const Ico = m.icon || AlertTriangle;
  const sevColor = SEVERITY_COLOR[alert.severity] || "#94a3b8";
  const d = alert.details || {};
  const ai = alert.ai_insight;
  const aiPriColor = ai?.priority === "critica" ? "#dc2626"
                      : ai?.priority === "alta" ? "#d97706"
                      : ai?.priority === "media" ? "#0ea5e9"
                      : "#64748b";
  return (
    <div data-testid={`sentinela-alert-${alert.id}`}
          style={{
            padding: 12, borderRadius: 8,
            background: "var(--bg-surface)",
            border: "1px solid var(--border-default)",
            borderLeft: `3px solid ${ai ? aiPriColor : sevColor}`,
            display: "grid", gap: 8,
          }}>
      <div style={{
        display: "grid",
        gridTemplateColumns: "auto 1fr auto", gap: 12,
        alignItems: "center",
      }}>
        <div style={{
          width: 36, height: 36, borderRadius: 8,
          background: `${m.color || "#64748b"}15`,
          color: m.color || "#64748b",
          display: "grid", placeItems: "center",
        }}>
          <Ico size={16} strokeWidth={2} />
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8,
                            flexWrap: "wrap", marginBottom: 3 }}>
            <span style={{
              padding: "1px 7px", borderRadius: 999,
              background: sevColor, color: "#fff",
              fontSize: 9, fontWeight: 800,
              textTransform: "uppercase", letterSpacing: 0.4,
            }}>{alert.severity}</span>
            <strong style={{ fontSize: 13, color: "var(--text-primary)",
                                letterSpacing: "-0.012em" }}>
              {alert.headline}
            </strong>
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)",
                            display: "flex", alignItems: "center", gap: 8,
                            flexWrap: "wrap" }}>
            {d.client_name && <span>👤 {d.client_name}</span>}
            {d.phone && <span style={{ fontFamily: "ui-monospace, monospace" }}>📞 {d.phone}</span>}
            {d.type && <span>⚙️ {d.type}</span>}
            {d.status && <span>📍 {d.status}</span>}
            {d.hours_idle != null && <span>⏱️ {d.hours_idle}h parado</span>}
            {d.hours_in_field != null && <span>🚐 {d.hours_in_field}h em campo</span>}
            {d.minutes_overdue != null && <span>🔥 {d.minutes_overdue}min atrasado</span>}
            {d.remaining_minutes != null && <span>⏰ {d.remaining_minutes}min restantes</span>}
            {d.active_tickets != null && <span>📊 {d.active_tickets} tickets ativos</span>}
            {d.count != null && d.related_tickets && <span>🔁 {d.count} tickets em 24h</span>}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <button onClick={onAck} data-testid={`sentinela-ack-${alert.id}`}
                  style={{
                    padding: "4px 10px", fontSize: 10, fontWeight: 700,
                    border: "1px solid #16a34a40", borderRadius: 5,
                    background: "#16a34a12", color: "#16a34a",
                    cursor: "pointer",
                    display: "inline-flex", alignItems: "center", gap: 3,
                  }}>
            <Eye size={10} /> Vi
          </button>
          <button onClick={onDismiss} data-testid={`sentinela-dismiss-${alert.id}`}
                  style={{
                    padding: "4px 10px", fontSize: 10, fontWeight: 700,
                    border: "1px solid var(--border-default)", borderRadius: 5,
                    background: "var(--bg-surface-2)",
                    color: "var(--text-muted)",
                    cursor: "pointer",
                    display: "inline-flex", alignItems: "center", gap: 3,
                  }}>
            <X size={10} /> Descartar
          </button>
        </div>
      </div>
      {ai && (
        <div data-testid={`sentinela-ai-insight-${alert.id}`}
              style={{
                padding: "8px 10px", borderRadius: 6,
                background: `${aiPriColor}08`,
                border: `1px solid ${aiPriColor}30`,
                display: "grid", gap: 3,
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
          {ai.root_cause && (
            <div style={{ fontSize: 10.5, color: "var(--text-muted)",
                              fontStyle: "italic" }}>
              Hipótese: {ai.root_cause}
            </div>
          )}
        </div>
      )}
    </div>
  );
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
