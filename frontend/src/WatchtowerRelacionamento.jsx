/**
 * Watchtower Relacionamento — Painel Executivo do relacionamento da IA
 * com a base de clientes.
 *
 * Mostra:
 *  • Top clientes por Trust Score (proxy: memórias acumuladas + confiança)
 *  • Memórias criadas no período + breakdown por tipo
 *  • Promessas (abertas / vencidas / cumpridas)
 *  • Clientes VIP
 *  • Últimas memórias relevantes (timeline)
 *  • Follow-ups pendentes
 *
 * Endpoint: GET /api/isabella/watchtower/relacionamento?hours=N
 */
import React, { useEffect, useState } from "react";
import {
  Heart, Users, Star, BookOpen, Clock, CheckCircle2, RefreshCw,
  Crown, MessageCircle,
} from "lucide-react";
import { api } from "@/api";

const MEMORY_TYPE_META = {
  PESSOAL: { color: "#7c3aed", label: "Pessoal" },
  COMERCIAL: { color: "#0e7490", label: "Comercial" },
  FINANCEIRA: { color: "#ea580c", label: "Financeira" },
  TECNICA: { color: "#2563eb", label: "Técnica" },
};

const WINDOW_OPTS = [
  { v: 24, l: "24h" }, { v: 168, l: "7d" }, { v: 720, l: "30d" },
];

export default function WatchtowerRelacionamento() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [hours, setHours] = useState(168);

  const load = async () => {
    setLoading(true); setErr("");
    try {
      const r = await api.watchtowerRelacionamento(hours);
      setData(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [hours]);

  if (loading && !data) {
    return <div style={{ padding: 32, textAlign: "center", color: "#64748b" }}>
      Carregando Relacionamento…</div>;
  }
  if (err) {
    return <div style={{ padding: 24, color: "#dc2626" }}>Erro: {err}</div>;
  }

  const memories = data.memories || {};
  const promises = data.promises || {};
  const followUps = data.follow_ups_pending || {};
  const topClients = data.top_clients || [];
  const vips = data.vip_clients || [];

  return (
    <div data-testid="watchtower-relacionamento" style={{ padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12,
        marginBottom: 18, flexWrap: "wrap" }}>
        <div style={{ flex: 1 }}>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: "#0f172a",
            margin: 0, display: "inline-flex", alignItems: "center", gap: 8 }}>
            <Heart size={20} /> Watchtower · Relacionamento
          </h2>
          <p style={{ fontSize: 13, color: "#64748b", marginTop: 4 }}>
            Memórias, promessas e confiança por cliente · janela {hours}h
          </p>
        </div>
        <WindowPicker hours={hours} onChange={setHours} />
        <button data-testid="wt-rel-refresh-btn"
          onClick={load} disabled={loading} style={refreshBtn}>
          <RefreshCw size={13} /> {loading ? "…" : "Atualizar"}
        </button>
      </div>

      {/* KPIs row */}
      <div style={{ display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
        gap: 12, marginBottom: 16 }}>
        <KpiCard icon={BookOpen} color="#7c3aed"
          label="Memórias criadas"
          value={String(memories.total || 0)}
          subtitle={Object.entries(memories.by_type || {})
            .map(([k, v]) => `${v} ${MEMORY_TYPE_META[k]?.label || k}`)
            .join(" · ") || "nenhum tipo no período"}
          testId="wt-rel-kpi-memories" />
        <KpiCard icon={CheckCircle2} color="#16a34a"
          label="Promessas cumpridas"
          value={String(promises.fulfilled || 0)}
          subtitle={`${promises.open || 0} abertas · ${promises.overdue || 0} vencidas`}
          testId="wt-rel-kpi-promises" />
        <KpiCard icon={Clock} color="#ea580c"
          label="Follow-ups pendentes"
          value={String(followUps.count || 0)}
          subtitle="memórias pessoais aguardando retomar"
          testId="wt-rel-kpi-followups" />
        <KpiCard icon={Crown} color="#facc15"
          label="Clientes VIP"
          value={String(vips.length)}
          subtitle="marcados como VIP em memória pessoal"
          testId="wt-rel-kpi-vips" />
      </div>

      {/* TOP CLIENTS by Trust */}
      <Section title="Top clientes por Trust Score" icon={Users}
        count={topClients.length}>
        {topClients.length === 0 ? (
          <EmptyLine>
            Ainda sem memórias acumuladas · base de relacionamento vazia.
          </EmptyLine>
        ) : (
          <table style={tableStyle}>
            <thead><tr>
              <th style={th}>#</th>
              <th style={th}>Phone</th>
              <th style={th}>Trust</th>
              <th style={th}>Memórias</th>
              <th style={th}>Última memória</th>
            </tr></thead>
            <tbody>
              {topClients.map((c, i) => (
                <tr key={c.phone || i} data-testid={`wt-rel-top-${i}`}>
                  <td style={td}>{i + 1}</td>
                  <td style={{ ...td, fontWeight: 600 }}>{c.phone}</td>
                  <td style={td}>
                    <TrustBar score={c.trust_score} />
                  </td>
                  <td style={td}>{c.memory_count}</td>
                  <td style={{ ...td, color: "#64748b", fontSize: 12 }}>
                    {fmtDate(c.last_memory_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* VIP CLIENTS */}
      <Section title="Clientes VIP" icon={Crown} count={vips.length}>
        {vips.length === 0 ? (
          <EmptyLine>
            Nenhum cliente VIP marcado · use memória pessoal com tag/texto &ldquo;VIP&rdquo;.
          </EmptyLine>
        ) : (
          <div style={{ display: "grid", gap: 8,
            gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
            {vips.map((v, i) => (
              <div key={v.id || i} data-testid={`wt-rel-vip-${i}`}
                style={vipCard}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <Crown size={14} color="#facc15" />
                  <strong style={{ fontSize: 13 }}>{v.phone}</strong>
                </div>
                <div style={{ fontSize: 12, color: "#475569", marginTop: 4,
                  fontWeight: 600 }}>{v.title}</div>
                <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
                  {truncate(v.description, 100)}
                </div>
                <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 6 }}>
                  Confiança {(v.confidence * 100).toFixed(0)}% · {fmtDate(v.created_at)}
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* LATEST MEMORIES TIMELINE */}
      <Section title="Últimas memórias relevantes" icon={BookOpen}
        count={memories.samples?.length || 0}>
        {(!memories.samples || memories.samples.length === 0) ? (
          <EmptyLine>Sem memórias novas nesta janela.</EmptyLine>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {memories.samples.map((m, i) => {
              const meta = MEMORY_TYPE_META[m.memory_type] || {
                color: "#64748b", label: m.memory_type };
              return (
                <div key={m.id || i} data-testid={`wt-rel-mem-${i}`}
                  style={{
                    padding: 10, background: "#fafafa",
                    borderRadius: 8, border: "1px solid #f1f5f9",
                    borderLeft: `3px solid ${meta.color}`,
                  }}>
                  <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", marginBottom: 4 }}>
                    <span style={{
                      fontSize: 10, fontWeight: 800, color: meta.color,
                      textTransform: "uppercase", letterSpacing: 0.5,
                    }}>{meta.label}</span>
                    <span style={{ fontSize: 11, color: "#94a3b8" }}>
                      {m.phone} · {fmtDate(m.created_at)}
                    </span>
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 600,
                    color: "#0f172a" }}>{m.title || "—"}</div>
                  <div style={{ fontSize: 12, color: "#475569",
                    marginTop: 2 }}>
                    {truncate(m.description, 160)}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Section>

      {/* FOLLOW-UPS pending */}
      <Section title="Follow-ups pendentes" icon={MessageCircle}
        count={followUps.count}>
        {followUps.count === 0 ? (
          <EmptyLine>
            Sem follow-ups pendentes · IA em dia com as retomadas.
          </EmptyLine>
        ) : (
          <table style={tableStyle}>
            <thead><tr>
              <th style={th}>Phone</th>
              <th style={th}>Memória</th>
              <th style={th}>Confiança</th>
              <th style={th}>Criada</th>
            </tr></thead>
            <tbody>
              {(followUps.samples || []).map((f, i) => (
                <tr key={f.id || i} data-testid={`wt-rel-followup-${i}`}>
                  <td style={td}>{f.phone}</td>
                  <td style={td}>
                    <div style={{ fontWeight: 600 }}>{f.title}</div>
                    <div style={{ fontSize: 11, color: "#64748b" }}>
                      {truncate(f.description, 80)}
                    </div>
                  </td>
                  <td style={td}>{(f.confidence * 100).toFixed(0)}%</td>
                  <td style={td}>{fmtDate(f.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* PROMISES SAMPLES */}
      {promises.overdue > 0 && (
        <Section title="Promessas vencidas com cliente" icon={Clock}
          count={promises.overdue}>
          <table style={tableStyle}>
            <thead><tr>
              <th style={th}>Phone</th>
              <th style={th}>Promessa</th>
              <th style={th}>Venceu</th>
            </tr></thead>
            <tbody>
              {(promises.overdue_samples || []).map((p, i) => (
                <tr key={p.id || i} data-testid={`wt-rel-overdue-${i}`}>
                  <td style={td}>{p.phone}</td>
                  <td style={td}>{truncate(p.promise_text, 100)}</td>
                  <td style={{ ...td, color: "#dc2626", fontWeight: 600 }}>
                    {fmtDate(p.due_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}
    </div>
  );
}

// ─── Subcomponentes ──────────────────────────────────────────

function WindowPicker({ hours, onChange }) {
  return (
    <div style={{
      display: "inline-flex", gap: 4, background: "#f1f5f9",
      borderRadius: 8, padding: 3,
    }}>
      {WINDOW_OPTS.map((opt) => (
        <button key={opt.v}
          data-testid={`wt-rel-window-${opt.v}`}
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

function TrustBar({ score }) {
  const s = Math.min(100, Math.max(0, Number(score || 0)));
  const color = s >= 70 ? "#16a34a" : s >= 40 ? "#ea580c" : "#dc2626";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{
        width: 70, height: 8, background: "#e2e8f0",
        borderRadius: 4, overflow: "hidden",
      }}>
        <div style={{ width: `${s}%`, height: "100%", background: color }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 700, color, minWidth: 38 }}>
        {s.toFixed(1)}
      </span>
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
            background: "#f1f5f9", color: "#475569",
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
  }}><Star size={14} color="#94a3b8" /> {children}</div>;
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

const vipCard = {
  padding: 12, background: "#fefce8",
  border: "1px solid #fde68a", borderRadius: 8,
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
