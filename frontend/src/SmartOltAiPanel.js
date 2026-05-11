import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import {
  Radio, AlertTriangle, CheckCircle2, RefreshCw, Loader2, Activity, Users, Clock,
} from "lucide-react";

/* =============================================================
   SmartOLT AI — monitoramento autônomo da rede com IA.
   Detecta outages por clustering de ONUs LOS no mesmo PON
   e comunica via Agent-to-Agent com a IA de atendimento.
============================================================= */
export default function SmartOltAiPanel() {
  const [summary, setSummary] = useState(null);
  const [active, setActive] = useState([]);
  const [recent, setRecent] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const reload = useCallback(async () => {
    try {
      const [s, a, r] = await Promise.all([
        api.smartoltAiSummary(),
        api.smartoltAiActiveOutages(),
        api.smartoltAiRecentOutages(24),
      ]);
      setSummary(s); setActive(a.items || []); setRecent(r.items || []);
      setErr(null);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
  }, []);

  useEffect(() => {
    reload();
    const id = setInterval(reload, 60000);
    return () => clearInterval(id);
  }, [reload]);

  const forceDetect = async () => {
    setBusy(true);
    try { await api.smartoltAiForceDetect(); await reload(); }
    catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };

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
                            color: "var(--text-secondary)", maxWidth: 600,
                            lineHeight: 1.5 }}>
                A IA varre as ONTs da rede a cada 90 segundos e detecta panes por
                clustering de LOS no mesmo PON. Quando um cliente afetado abre
                conversa, a IA de Atendimento já avisa antes mesmo dele perguntar
                — sem pedir reset de modem, sem abrir chamado redundante.
              </p>
            </div>
          </div>
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
        <Kpi label="Resolvidos (24h)"
              value={summary?.resolved_24h ?? 0}
              color="#16a34a"
              icon={CheckCircle2}
              testId="smartolt-ai-kpi-resolved" />
      </div>

      {/* Outages ativos */}
      <Section title={`Outages ativos · ${active.length}`}
                icon={AlertTriangle}>
        {active.length === 0 ? (
          <EmptyState text="Nenhum outage ativo detectado no momento. Rede operando normalmente." />
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
  return (
    <div data-testid={`outage-${outage.id}`} style={{
      padding: 12, borderRadius: 8,
      background: "var(--bg-surface)",
      border: "1px solid var(--border-default)",
      borderLeft: `3px solid ${active ? "#dc2626" : "#16a34a"}`,
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
