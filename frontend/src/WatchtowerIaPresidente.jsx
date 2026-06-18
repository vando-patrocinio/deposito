/**
 * Watchtower IA Presidente — Painel Executivo da saúde da Isabella.
 *
 * Mostra:
 *  • ISABELLA INDEX (composite trust/relationship/resolution/promise)
 *  • AUTONOMY alarms (quedas >5pp)
 *  • Claims sem evidência (failed + orphan)
 *  • Promessas: abertas / vencidas / cumpridas
 *  • Latência média/p95 WhatsApp + taxa de sucesso
 *  • Falhas de envio recentes
 *
 * Endpoint: GET /api/isabella/watchtower/ia-presidente?hours=N
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  Shield, ShieldAlert, ShieldCheck, AlertTriangle, Brain, Clock,
  CheckCircle2, XCircle, Activity, MessageSquare, RefreshCw,
} from "lucide-react";
import { api } from "@/api";

const COLOR_MAP = {
  green: { bg: "#dcfce7", fg: "#166534", border: "#86efac" },
  amber: { bg: "#fef3c7", fg: "#92400e", border: "#fde68a" },
  red: { bg: "#fee2e2", fg: "#991b1b", border: "#fecaca" },
};

const WINDOW_OPTS = [
  { v: 1, l: "1h" }, { v: 6, l: "6h" }, { v: 24, l: "24h" },
  { v: 168, l: "7d" }, { v: 720, l: "30d" },
];

export default function WatchtowerIaPresidente() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [hours, setHours] = useState(24);

  const load = async () => {
    setLoading(true); setErr("");
    try {
      const r = await api.watchtowerIaPresidente(hours);
      setData(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [hours]);

  if (loading && !data) {
    return <div style={{ padding: 32, textAlign: "center", color: "#64748b" }}>
      Carregando IA Presidente…</div>;
  }
  if (err) {
    return <div style={{ padding: 24, color: "#dc2626" }}>Erro: {err}</div>;
  }

  const idx = data.isabella_index || {};
  const alarms = data.autonomy_alarms || { items: [], n: 0 };
  const claims = data.claims || {};
  const promises = data.promises || {};
  const dispatch = data.wa_dispatch || {};
  const color = COLOR_MAP[idx.color] || COLOR_MAP.amber;

  return (
    <div data-testid="watchtower-ia-presidente" style={{ padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12,
        marginBottom: 18, flexWrap: "wrap" }}>
        <div style={{ flex: 1 }}>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: "#0f172a",
            margin: 0, display: "inline-flex", alignItems: "center", gap: 8 }}>
            <Brain size={20} /> Watchtower · IA Presidente
          </h2>
          <p style={{ fontSize: 13, color: "#64748b", marginTop: 4 }}>
            Saúde da Isabella · janela {hours}h · gerado em {fmtDate(data.generated_at)}
          </p>
        </div>
        <WindowPicker hours={hours} onChange={setHours} />
        <button data-testid="wt-iap-refresh-btn"
          onClick={load} disabled={loading}
          style={refreshBtn}>
          <RefreshCw size={13} /> {loading ? "…" : "Atualizar"}
        </button>
      </div>

      {/* HERO: ISABELLA INDEX big */}
      <div data-testid="wt-iap-index-hero" style={{
        background: color.bg, border: `2px solid ${color.border}`,
        borderRadius: 12, padding: 20, marginBottom: 16,
        display: "grid", gridTemplateColumns: "auto 1fr",
        gap: 20, alignItems: "center",
      }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 64, fontWeight: 800, color: color.fg,
            lineHeight: 1 }}>
            {idx.isabella_index ?? "—"}
          </div>
          <div style={{ fontSize: 11, color: color.fg, fontWeight: 700,
            letterSpacing: 0.6, textTransform: "uppercase", marginTop: 4 }}>
            ISABELLA INDEX
          </div>
          <StatusBadge color={idx.color} />
        </div>
        <div style={{ display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
          gap: 10 }}>
          <SubScore label="Trust"
            score={idx.scores?.trust?.score}
            weight={idx.weights?.trust}
            detail={`${idx.scores?.trust?.claims_total || 0} claims · ${idx.scores?.trust?.factual_errors_2h || 0} erros 2h`}
            testId="wt-iap-sub-trust" />
          <SubScore label="Relacionamento"
            score={idx.scores?.relationship?.score}
            weight={idx.weights?.relationship}
            detail={`${idx.scores?.relationship?.memories_used || 0}/${idx.scores?.relationship?.memories_available || 0} usadas`}
            testId="wt-iap-sub-rel" />
          <SubScore label="Resolução"
            score={idx.scores?.resolution?.score}
            weight={idx.weights?.resolution}
            detail={`${idx.scores?.resolution?.resolved || 0} resolvidos`}
            testId="wt-iap-sub-res" />
          <SubScore label="Promessas"
            score={idx.scores?.promise?.score}
            weight={idx.weights?.promise}
            detail={`${idx.scores?.promise?.currently_open || 0} abertas · ${idx.scores?.promise?.overdue || 0} vencidas`}
            testId="wt-iap-sub-prom" />
        </div>
      </div>

      {/* KPIs row */}
      <div style={{ display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
        gap: 12, marginBottom: 16 }}>
        <KpiCard icon={ShieldAlert} color="#dc2626"
          label="Claims sem evidência"
          value={String(claims.failed || 0)}
          subtitle={`+ ${claims.orphan_no_consume || 0} órfãos (audit ok, não consumidos)`}
          testId="wt-iap-kpi-claims" />
        <KpiCard icon={AlertTriangle} color="#ea580c"
          label="Promessas vencidas"
          value={String(promises.overdue || 0)}
          subtitle={`${promises.open || 0} em aberto · ${promises.fulfilled || 0} cumpridas`}
          testId="wt-iap-kpi-promises" />
        <KpiCard icon={Activity} color="#2563eb"
          label="Latência WhatsApp"
          value={`${dispatch.latency_ms_avg || 0}ms`}
          subtitle={`p95 ${dispatch.latency_ms_p95 || 0}ms · taxa ${dispatch.success_rate ?? "—"}%`}
          testId="wt-iap-kpi-latency" />
        <KpiCard icon={XCircle} color="#7c2d12"
          label="Falhas de envio"
          value={String(dispatch.failures || 0)}
          subtitle={`de ${dispatch.total || 0} tentativas`}
          testId="wt-iap-kpi-failures" />
      </div>

      {/* AUTONOMY ALARMS list */}
      <Section title="Alarmes de Autonomia (últimos 7d)"
        icon={ShieldAlert} count={alarms.n}>
        {alarms.n === 0 ? (
          <EmptyLine>Nenhum alarme · autonomia estável.</EmptyLine>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {(alarms.items || []).slice(0, 10).map((a, i) => (
              <div key={i} data-testid={`wt-iap-alarm-${i}`} style={alarmCard}>
                <strong>↓ {a.drop_pp?.toFixed?.(1) ?? a.drop_pp}pp</strong>
                <span style={{ color: "#64748b", marginLeft: 8 }}>
                  {fmtDate(a.triggered_at)}
                </span>
                {a.reason && <div style={{ fontSize: 12, color: "#475569",
                  marginTop: 4 }}>{a.reason}</div>}
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* PROMISE OVERDUE samples */}
      <Section title="Promessas em atraso (top 5)"
        icon={Clock} count={promises.overdue}>
        {(!promises.overdue_samples || promises.overdue_samples.length === 0) ? (
          <EmptyLine>Nenhuma promessa em atraso · IA cumprindo a palavra.</EmptyLine>
        ) : (
          <table style={tableStyle}>
            <thead><tr>
              <th style={th}>Phone</th>
              <th style={th}>Promessa</th>
              <th style={th}>Vence em</th>
            </tr></thead>
            <tbody>
              {promises.overdue_samples.map((p, i) => (
                <tr key={p.id || i} data-testid={`wt-iap-overdue-${i}`}>
                  <td style={td}>{p.phone}</td>
                  <td style={td}>{truncate(p.promise_text, 80)}</td>
                  <td style={{ ...td, color: "#dc2626", fontWeight: 600 }}>
                    {fmtDate(p.due_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* CLAIM FAILURES samples */}
      <Section title="Claims rejeitados (auditoria falhou)"
        icon={ShieldAlert} count={claims.failed}>
        {(!claims.samples || claims.samples.length === 0) ? (
          <EmptyLine>Nenhum claim falhou na auditoria · ✓</EmptyLine>
        ) : (
          <table style={tableStyle}>
            <thead><tr>
              <th style={th}>Tipo</th>
              <th style={th}>Texto</th>
              <th style={th}>Motivo</th>
              <th style={th}>Quando</th>
            </tr></thead>
            <tbody>
              {claims.samples.map((c, i) => (
                <tr key={c.id || i} data-testid={`wt-iap-claim-fail-${i}`}>
                  <td style={td}>{c.claim_type}</td>
                  <td style={td}>{truncate(c.claim_text, 80)}</td>
                  <td style={{ ...td, color: "#dc2626" }}>
                    {truncate(c.audit_reason, 60)}
                  </td>
                  <td style={td}>{fmtDate(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* WA SEND FAILURES */}
      <Section title="Falhas recentes de envio WhatsApp"
        icon={MessageSquare} count={dispatch.failures}>
        {(!dispatch.fail_samples || dispatch.fail_samples.length === 0) ? (
          <EmptyLine>Sem falhas de envio · canal saudável.</EmptyLine>
        ) : (
          <table style={tableStyle}>
            <thead><tr>
              <th style={th}>Motivo</th>
              <th style={th}>Latência</th>
              <th style={th}>Quando</th>
            </tr></thead>
            <tbody>
              {dispatch.fail_samples.map((f, i) => (
                <tr key={i} data-testid={`wt-iap-send-fail-${i}`}>
                  <td style={{ ...td, color: "#7c2d12" }}>
                    {truncate(f.reason, 80)}
                  </td>
                  <td style={td}>{f.latency_ms}ms</td>
                  <td style={td}>{fmtDate(f.ts)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
    </div>
  );
}

// ─── Subcomponentes ──────────────────────────────────────────

function WindowPicker({ hours, onChange }) {
  return (
    <div data-testid="wt-iap-window-picker" style={{
      display: "inline-flex", gap: 4, background: "#f1f5f9",
      borderRadius: 8, padding: 3,
    }}>
      {WINDOW_OPTS.map((opt) => (
        <button key={opt.v}
          data-testid={`wt-window-${opt.v}`}
          onClick={() => onChange(opt.v)}
          style={{
            padding: "5px 10px", fontSize: 11, fontWeight: 700,
            background: hours === opt.v ? "#0f172a" : "transparent",
            color: hours === opt.v ? "white" : "#475569",
            border: "none", borderRadius: 6, cursor: "pointer",
          }}>
          {opt.l}
        </button>
      ))}
    </div>
  );
}

function StatusBadge({ color }) {
  const meta = {
    green: { Icon: ShieldCheck, text: "SAUDÁVEL" },
    amber: { Icon: Shield, text: "ATENÇÃO" },
    red: { Icon: ShieldAlert, text: "CRÍTICO" },
  }[color] || { Icon: Shield, text: "—" };
  const { Icon, text } = meta;
  const c = COLOR_MAP[color] || COLOR_MAP.amber;
  return (
    <div style={{
      marginTop: 6, display: "inline-flex", alignItems: "center", gap: 4,
      fontSize: 10, fontWeight: 800, padding: "3px 8px",
      borderRadius: 999, background: c.fg, color: "white",
      letterSpacing: 0.4,
    }}>
      <Icon size={11} /> {text}
    </div>
  );
}

function SubScore({ label, score, weight, detail, testId }) {
  const s = Number(score || 0);
  return (
    <div data-testid={testId} style={{
      background: "rgba(255,255,255,0.6)", borderRadius: 8, padding: 10,
    }}>
      <div style={{ fontSize: 10, color: "#475569", fontWeight: 700,
        textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label} · peso {(weight * 100).toFixed(0)}%
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: "#0f172a",
        marginTop: 2 }}>{s.toFixed(1)}</div>
      <div style={{ fontSize: 10, color: "#64748b" }}>{detail}</div>
    </div>
  );
}

function KpiCard({ icon: Ico, color, label, value, subtitle, testId }) {
  return (
    <div data-testid={testId} style={{
      padding: 14, borderRadius: 10, background: "#fff",
      border: "1px solid #e2e8f0",
      boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6,
        marginBottom: 6 }}>
        <Ico size={14} color={color} />
        <div style={{ fontSize: 10, color: "#64748b",
          textTransform: "uppercase", fontWeight: 700, letterSpacing: 0.4 }}>
          {label}
        </div>
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color }}>{value}</div>
      <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
        {subtitle}
      </div>
    </div>
  );
}

function Section({ title, icon: Ico, count, children }) {
  return (
    <div style={{ marginBottom: 16, background: "white",
      borderRadius: 10, border: "1px solid #e2e8f0", padding: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
        marginBottom: 10 }}>
        <Ico size={16} color="#475569" />
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700,
          color: "#0f172a" }}>{title}</h3>
        {count !== undefined && count !== null && (
          <span style={{
            background: count > 0 ? "#fef3c7" : "#dcfce7",
            color: count > 0 ? "#92400e" : "#166534",
            padding: "2px 8px", borderRadius: 999, fontSize: 11,
            fontWeight: 700,
          }}>{count}</span>
        )}
      </div>
      {children}
    </div>
  );
}

function EmptyLine({ children }) {
  return <div style={{
    padding: 12, background: "#f8fafc", borderRadius: 8,
    color: "#64748b", fontSize: 13, display: "flex",
    alignItems: "center", gap: 6,
  }}><CheckCircle2 size={14} color="#16a34a" /> {children}</div>;
}

// ─── Estilos ────────────────────────────────────────────────
const refreshBtn = {
  padding: "6px 12px", fontSize: 12, fontWeight: 600,
  border: "1px solid #cbd5e1", background: "white",
  borderRadius: 8, cursor: "pointer", display: "inline-flex",
  alignItems: "center", gap: 4,
};

const tableStyle = {
  width: "100%", borderCollapse: "collapse", fontSize: 13,
};
const th = {
  textAlign: "left", padding: "8px 6px", fontSize: 11,
  color: "#64748b", textTransform: "uppercase", fontWeight: 700,
  letterSpacing: 0.4, borderBottom: "1px solid #e2e8f0",
};
const td = {
  padding: "8px 6px", color: "#0f172a",
  borderBottom: "1px solid #f1f5f9",
};

const alarmCard = {
  padding: 10, background: "#fef3c7", borderRadius: 8,
  border: "1px solid #fde68a", fontSize: 13,
};

function truncate(s, n) {
  if (!s) return "—";
  return s.length > n ? s.slice(0, n) + "…" : s;
}

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", {
      day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
    });
  } catch (e) { return iso; }
}
