/* BackendHealthPanel.js — Sprint 6 / iter225
   Centro de comando técnico (CTO/SRE). */
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import {
  Activity, AlertTriangle, CheckCircle2, Database, Gauge,
  RefreshCw, Server, XCircle, Zap,
} from "lucide-react";

const ORACLE = {
  bg: "#0b1220", panel: "#101a2e", card: "#152238",
  ink: "#e2e8f0", muted: "#94a3b8",
  purple: "#4b1d7a", orange: "#f28c28",
  green: "#22c55e", red: "#ef4444", amber: "#f59e0b",
  blue: "#3b82f6", border: "#1e293b",
};

const WINDOWS = [
  { v: 300, label: "5 min" },
  { v: 3600, label: "1h" },
  { v: 21600, label: "6h" },
  { v: 86400, label: "24h" },
];

const STATUS_COLOR = {
  saudavel: ORACLE.green, atencao: ORACLE.amber,
  critico: ORACLE.red,
};

export default function BackendHealthPanel() {
  const [data, setData] = useState(null);
  const [windowS, setWindowS] = useState(3600);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [err, setErr] = useState("");

  const fetchData = async () => {
    setLoading(true); setErr("");
    try {
      const r = await api._client.get(
        `/health-panel/deep?window_seconds=${windowS}`);
      setData(r.data);
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Erro");
    } finally { setLoading(false); }
  };

  useEffect(() => { fetchData(); /* eslint-disable-next-line */ },
    [windowS]);
  useEffect(() => {
    if (!autoRefresh) return undefined;
    const i = setInterval(fetchData, 15000);
    return () => clearInterval(i);
    // eslint-disable-next-line
  }, [autoRefresh, windowS]);

  const status = data?.status || "—";
  const statusColor = STATUS_COLOR[status] || ORACLE.muted;
  const lat = data?.latency || {};
  const cards = {
    total: lat.total_requests ?? 0,
    err5xx: lat.err_5xx ?? 0,
    err4xx: lat.err_4xx ?? 0,
    rate: lat.err_rate_pct ?? 0,
  };

  return (
    <div data-testid="backend-health-panel" style={{
      background: ORACLE.bg, color: ORACLE.ink, minHeight: "100vh",
      padding: 24,
    }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 16, flexWrap: "wrap", gap: 12,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Gauge size={28} color={statusColor} />
          <div>
            <h1 style={{
              margin: 0, fontSize: 22, fontWeight: 800,
              letterSpacing: -0.5,
            }} data-testid="health-title">
              Saúde Técnica — Centro de Comando SRE
            </h1>
            <div style={{
              fontSize: 12, color: ORACLE.muted, marginTop: 4,
              display: "flex", alignItems: "center", gap: 8,
            }}>
              <span style={{
                width: 8, height: 8, borderRadius: "50%",
                background: statusColor, display: "inline-block",
              }} />
              <span data-testid="health-status">
                Status global: <b style={{ color: statusColor }}>
                  {status.toUpperCase()}</b>
              </span>
              {data && <span>· atualizado {fmtDate(data.generated_at)}</span>}
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {WINDOWS.map((w) => (
            <button key={w.v} onClick={() => setWindowS(w.v)}
              data-testid={`win-${w.v}`}
              style={{
                background: windowS === w.v ? ORACLE.purple : "transparent",
                color: ORACLE.ink, border: `1px solid ${ORACLE.border}`,
                padding: "6px 12px", borderRadius: 6, cursor: "pointer",
                fontSize: 12, fontWeight: 700,
              }}>{w.label}</button>
          ))}
          <label style={{
            fontSize: 11, color: ORACLE.muted, display: "flex",
            alignItems: "center", gap: 4, cursor: "pointer",
          }}>
            <input type="checkbox" checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              data-testid="autorefresh-toggle" />
            auto-refresh
          </label>
          <button onClick={fetchData} disabled={loading}
            data-testid="health-refresh" style={btnStyle(ORACLE.blue)}>
            <RefreshCw size={14} style={{
              animation: loading ? "spin 1s linear infinite" : "none",
            }} /> Atualizar
          </button>
        </div>
      </div>

      {err && (
        <div data-testid="health-error" style={{
          background: "#7f1d1d", color: "#fee", padding: 12,
          borderRadius: 8, marginBottom: 16, fontSize: 13,
        }}>⚠ {err}</div>
      )}

      {/* Cards */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
        gap: 12, marginBottom: 18,
      }}>
        <Card icon={<Activity size={18} />} label="Requisições"
          value={cards.total} color={ORACLE.blue} testid="card-total" />
        <Card icon={<XCircle size={18} />} label="Erros 5xx"
          value={cards.err5xx}
          color={cards.err5xx ? ORACLE.red : ORACLE.green}
          testid="card-5xx" />
        <Card icon={<AlertTriangle size={18} />} label="Erros 4xx"
          value={cards.err4xx} color={ORACLE.amber} testid="card-4xx" />
        <Card icon={<Zap size={18} />} label="Taxa de erro"
          value={`${cards.rate}%`}
          color={cards.rate > 5 ? ORACLE.red : ORACLE.green}
          testid="card-rate" />
        <Card icon={<Database size={18} />} label="Ring buffer"
          value={`${data?.ring_used ?? 0}/${data?.ring_capacity ?? "?"}`}
          color={ORACLE.purple} testid="card-ring" />
      </div>

      {/* Services + index hints */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
        gap: 12, marginBottom: 18,
      }}>
        <div data-testid="services-card" style={panelStyle}>
          <SectionTitle icon={<Server size={16} />}>
            Serviços externos
          </SectionTitle>
          {(data?.services || []).map((s, i) => (
            <ServiceRow key={i} svc={s} />
          ))}
        </div>
        <div data-testid="indexes-card" style={panelStyle}>
          <SectionTitle icon={<Database size={16} />}>
            Sugestões de índice (coleções quentes)
          </SectionTitle>
          {(data?.index_hints || []).length === 0 && (
            <div style={{
              fontSize: 12, color: ORACLE.green, marginTop: 8,
            }} data-testid="indexes-ok">
              ✓ todas as coleções quentes têm índices recomendados.
            </div>
          )}
          {(data?.index_hints || []).map((h, i) => (
            <div key={i} style={{
              padding: "6px 0", fontSize: 12,
              borderBottom: `1px solid ${ORACLE.border}`,
            }}>
              <code style={{ color: ORACLE.amber }}>
                {h.collection}
              </code>
              <span style={{ color: ORACLE.muted, marginLeft: 6 }}>
                falta índice em: {h.missing_index_on.join(", ")}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Top slowest endpoints */}
      <div data-testid="slow-routes-card" style={{
        ...panelStyle, marginBottom: 18,
      }}>
        <SectionTitle icon={<Zap size={16} />}>
          Top 10 endpoints mais lentos
        </SectionTitle>
        <table style={{
          width: "100%", borderCollapse: "collapse", fontSize: 12,
          marginTop: 8,
        }}>
          <thead>
            <tr style={{ color: ORACLE.muted }}>
              <Th>Rota</Th>
              <Th align="right">Reqs</Th>
              <Th align="right">avg</Th>
              <Th align="right">p50</Th>
              <Th align="right">p95</Th>
              <Th align="right">max</Th>
            </tr>
          </thead>
          <tbody>
            {(lat.top_slowest || []).length === 0 && (
              <tr><td colSpan={6} style={{
                padding: 18, textAlign: "center", color: ORACLE.muted,
              }} data-testid="slow-empty">
                Sem dados na janela.
              </td></tr>
            )}
            {(lat.top_slowest || []).map((r, i) => (
              <tr key={i} data-testid={`slow-row-${i}`} style={{
                borderTop: `1px solid ${ORACLE.border}`,
              }}>
                <Td><code style={{ fontSize: 11 }}>{r.route}</code></Td>
                <Td align="right">{r.count}</Td>
                <Td align="right">{r.avg_ms}ms</Td>
                <Td align="right">{r.p50_ms}ms</Td>
                <Td align="right">
                  <b style={{
                    color: r.p95_ms > 1000 ? ORACLE.red
                      : r.p95_ms > 300 ? ORACLE.amber : ORACLE.green,
                  }}>{r.p95_ms}ms</b>
                </Td>
                <Td align="right">{r.max_ms}ms</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Tamanho de coleções */}
      <div data-testid="sizes-card" style={panelStyle}>
        <SectionTitle icon={<Database size={16} />}>
          Coleções que crescem (TTL recomendado)
        </SectionTitle>
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 10, marginTop: 8,
        }}>
          {(data?.collection_sizes || []).map((c, i) => (
            <div key={i} style={{
              background: ORACLE.card, padding: 10, borderRadius: 6,
            }} data-testid={`size-${c.collection}`}>
              <div style={{
                fontSize: 10, color: ORACLE.muted, textTransform: "uppercase",
              }}>{c.collection}</div>
              <div style={{ fontSize: 18, fontWeight: 800, marginTop: 4 }}>
                {c.docs.toLocaleString("pt-BR")}
              </div>
            </div>
          ))}
        </div>
      </div>

      <style>{`@keyframes spin {
        from { transform: rotate(0); } to { transform: rotate(360deg); }
      }`}</style>
    </div>
  );
}

function ServiceRow({ svc }) {
  const ok = svc.ok;
  return (
    <div data-testid={`svc-${svc.name}`} style={{
      padding: "8px 0", fontSize: 12,
      borderBottom: `1px solid ${ORACLE.border}`,
      display: "flex", justifyContent: "space-between",
      alignItems: "center",
    }}>
      <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {ok ? <CheckCircle2 size={14} color={ORACLE.green} />
            : <XCircle size={14} color={ORACLE.red} />}
        {svc.name}
      </span>
      <span style={{
        color: ok ? ORACLE.green : ORACLE.red, fontWeight: 700,
        fontSize: 11,
      }}>
        {ok ? (svc.latency_ms ? `${svc.latency_ms}ms` : "OK")
            : (svc.error || svc.hint || "down")}
      </span>
    </div>
  );
}

function SectionTitle({ icon, children }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      fontSize: 12, fontWeight: 700, color: ORACLE.muted,
      textTransform: "uppercase", letterSpacing: 0.5,
    }}>{icon}{children}</div>
  );
}

function Card({ icon, label, value, color, testid }) {
  return (
    <div data-testid={testid} style={{
      background: ORACLE.panel, padding: 14, borderRadius: 10,
      borderTop: `3px solid ${color}`,
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        color: ORACLE.muted, fontSize: 11, fontWeight: 700,
        textTransform: "uppercase", letterSpacing: 0.5,
      }}><span style={{ color }}>{icon}</span>{label}</div>
      <div style={{
        marginTop: 8, fontSize: 26, fontWeight: 800,
      }}>{value ?? "—"}</div>
    </div>
  );
}

function Th({ children, align }) {
  return <th style={{
    padding: "8px 10px", textAlign: align || "left",
    fontWeight: 700, fontSize: 10, textTransform: "uppercase",
    letterSpacing: 0.5,
  }}>{children}</th>;
}

function Td({ children, align }) {
  return <td style={{
    padding: "8px 10px", textAlign: align || "left",
    color: ORACLE.ink,
  }}>{children}</td>;
}

const panelStyle = {
  background: ORACLE.panel, padding: 14, borderRadius: 10,
};

const btnStyle = (bg) => ({
  background: bg, color: "#fff", border: 0,
  padding: "6px 12px", borderRadius: 6, cursor: "pointer",
  fontSize: 12, fontWeight: 700, display: "inline-flex",
  alignItems: "center", gap: 6,
});

function fmtDate(s) {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleTimeString("pt-BR");
  } catch { return s; }
}
