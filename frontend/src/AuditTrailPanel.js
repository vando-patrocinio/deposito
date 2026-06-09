/* AuditTrailPanel.js — Sprint 3 / iter222
   Centro de comando de Segurança & Compliance.

   Cards executivos + filtros + tabela + drawer + export CSV.
   Embute alertas de segurança gerados pelos detectores do
   Presidente IA (/api/presidente-ia/security/alerts).
*/
import React, { useEffect, useMemo, useState } from "react";
import { api, API } from "@/api";
import {
  Activity, AlertTriangle, Download, Eye, Filter, RefreshCw,
  ShieldAlert, ShieldCheck, Trash2, UserCog, X, Zap,
} from "lucide-react";

const ORACLE = {
  bg: "#0b1220", panel: "#101a2e", card: "#152238",
  ink: "#e2e8f0", muted: "#94a3b8",
  purple: "#4b1d7a", orange: "#f28c28",
  green: "#22c55e", red: "#ef4444", amber: "#f59e0b",
  blue: "#3b82f6", border: "#1e293b",
};

const CRITICALITY_COLOR = {
  alta: ORACLE.red, critica: ORACLE.red,
  media: ORACLE.amber, baixa: ORACLE.muted,
};

const CATEGORY_LABEL = {
  destructive: "Exclusão",
  export: "Exportação",
  config_change: "Mudança de config",
  ai_config_change: "Config de IA",
  login_admin: "Login admin",
  impersonate: "Impersonate",
  rbac_blocked: "Bloqueio RBAC",
  ai_rate_limited: "Limite IA",
};

const CATEGORY_OPTS = [
  { v: "", label: "Todas categorias" },
  { v: "destructive", label: "Exclusão" },
  { v: "export", label: "Exportação" },
  { v: "config_change", label: "Mudança de config" },
  { v: "ai_config_change", label: "Config de IA" },
  { v: "login_admin", label: "Login admin" },
  { v: "impersonate", label: "Impersonate" },
  { v: "rbac_blocked", label: "Bloqueio RBAC" },
  { v: "ai_rate_limited", label: "Limite IA" },
];

const PERIODS = [
  { v: 1, label: "1h" },
  { v: 24, label: "24h" },
  { v: 168, label: "7d" },
  { v: 720, label: "30d" },
];

const ROLE_OPTS = ["", "administrador", "gestor", "financeiro", "auditor",
  "atendimento", "tecnico", "colaborador"];

export default function AuditTrailPanel() {
  const [stats, setStats] = useState(null);
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [windowH, setWindowH] = useState(24);
  const [filters, setFilters] = useState({
    user_email: "", role: "", action: "", endpoint: "",
    category: "", criticality: "",
  });
  const [page, setPage] = useState(0);
  const pageSize = 25;
  const [selected, setSelected] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [insight, setInsight] = useState(null);
  const [err, setErr] = useState("");

  const fetchAll = async () => {
    setLoading(true); setErr("");
    try {
      const [s, lst, a, ins] = await Promise.all([
        api._client.get(`/audit-log/stats?window_hours=${windowH}`),
        api._client.get(`/audit-log`, {
          params: {
            limit: pageSize, skip: page * pageSize, ...stripEmpty(filters),
          },
        }),
        api._client.get(`/presidente-ia/security/alerts`)
          .catch(() => ({ data: { alerts: [] } })),
        api._client.get(`/presidente-ia/security/insight`)
          .catch(() => ({ data: null })),
      ]);
      setStats(s.data);
      setItems(lst.data.items || []);
      setTotal(lst.data.total || 0);
      setAlerts(a.data?.alerts || []);
      setInsight(ins.data);
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message
        || "Erro ao carregar audit trail");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAll(); /* eslint-disable-next-line */ },
    [windowH, page]);

  const applyFilters = (e) => {
    e?.preventDefault?.();
    setPage(0);
    fetchAll();
  };

  const exportCsv = () => {
    const token = (typeof window !== "undefined")
      ? window.localStorage.getItem("ponto_token") : "";
    const qs = new URLSearchParams(stripEmpty({
      category: filters.category, criticality: filters.criticality,
    })).toString();
    const url = `${API}/audit-log/export.csv${qs ? "?" + qs : ""}`;
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.blob())
      .then((blob) => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `audit-trail-${Date.now()}.csv`;
        a.click();
      })
      .catch(() => alert("Falha ao exportar"));
  };

  const cards = stats?.cards || {};
  const insightStatusColor = {
    saudavel: ORACLE.green, atencao: ORACLE.amber,
    alerta: ORACLE.red, critico: ORACLE.red,
  }[insight?.status] || ORACLE.muted;

  return (
    <div data-testid="audit-trail-panel" style={{
      background: ORACLE.bg, color: ORACLE.ink, minHeight: "100vh",
      padding: 24,
    }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 24, flexWrap: "wrap", gap: 16,
      }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <ShieldCheck size={28} color={ORACLE.green} />
            <h1 style={{
              margin: 0, fontSize: 22, fontWeight: 800,
              letterSpacing: -0.5,
            }} data-testid="audit-trail-title">
              Audit Trail — Centro de Comando de Compliance
            </h1>
          </div>
          {insight && (
            <div style={{
              marginTop: 10, fontSize: 13, color: ORACLE.muted,
              display: "flex", alignItems: "center", gap: 8,
            }}>
              <span style={{
                display: "inline-block", width: 8, height: 8,
                borderRadius: "50%", background: insightStatusColor,
              }} />
              <span data-testid="audit-trail-insight">
                {insight.title} — {insight.message}
              </span>
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {PERIODS.map((p) => (
            <button key={p.v}
              onClick={() => setWindowH(p.v)}
              data-testid={`audit-period-${p.v}`}
              style={{
                background: windowH === p.v ? ORACLE.purple : "transparent",
                color: ORACLE.ink, border: `1px solid ${ORACLE.border}`,
                padding: "6px 12px", borderRadius: 8, cursor: "pointer",
                fontSize: 12, fontWeight: 700,
              }}>{p.label}</button>
          ))}
          <button onClick={fetchAll} disabled={loading}
            data-testid="audit-refresh"
            style={btnStyle(ORACLE.blue)}>
            <RefreshCw size={14} style={{
              animation: loading ? "spin 1s linear infinite" : "none",
            }} /> Atualizar
          </button>
          <button onClick={exportCsv} data-testid="audit-export-csv"
            style={btnStyle(ORACLE.green)}>
            <Download size={14} /> Exportar CSV
          </button>
        </div>
      </div>

      {err && (
        <div data-testid="audit-error" style={{
          background: "#7f1d1d", color: "#fee", padding: 12,
          borderRadius: 8, marginBottom: 16, fontSize: 13,
        }}>⚠ {err}</div>
      )}

      {/* Cards */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
        gap: 12, marginBottom: 20,
      }}>
        <Card icon={<Activity size={18} />} label="Total no período"
          value={cards.total} color={ORACLE.blue} testid="card-total" />
        <Card icon={<Trash2 size={18} />} label="Deleções"
          value={cards.deletes} color={ORACLE.red} testid="card-deletes" />
        <Card icon={<Download size={18} />} label="Exportações"
          value={cards.exports} color={ORACLE.amber} testid="card-exports" />
        <Card icon={<ShieldAlert size={18} />} label="403 (RBAC bloqueou)"
          value={cards.rbac_blocked} color={ORACLE.orange}
          testid="card-rbac-blocked" />
        <Card icon={<UserCog size={18} />} label="Impersonations"
          value={cards.impersonate} color={ORACLE.purple}
          testid="card-impersonate" />
        <Card icon={<AlertTriangle size={18} />} label="Ações críticas"
          value={cards.criticals} color={ORACLE.red}
          testid="card-criticals" />
      </div>

      {/* Alertas do Presidente IA */}
      {alerts.length > 0 && (
        <div data-testid="security-alerts-row" style={{
          background: ORACLE.panel, border: `1px solid ${ORACLE.red}`,
          borderRadius: 12, padding: 16, marginBottom: 20,
        }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 8, marginBottom: 12,
            fontSize: 14, fontWeight: 800, color: ORACLE.red,
          }}>
            <Zap size={18} /> Alertas do Presidente IA
          </div>
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
            gap: 12,
          }}>
            {alerts.map((a, i) => (
              <div key={i} data-testid={`security-alert-${i}`} style={{
                background: ORACLE.card, padding: 12, borderRadius: 8,
                borderLeft: `4px solid ${CRITICALITY_COLOR[a.severity]
                  || ORACLE.amber}`,
              }}>
                <div style={{
                  fontSize: 12, fontWeight: 800, marginBottom: 4,
                }}>{a.title}</div>
                <div style={{
                  fontSize: 12, color: ORACLE.muted, lineHeight: 1.4,
                }}>{a.message}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Top users + endpoints */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
        gap: 12, marginBottom: 20,
      }}>
        <TopList title="Usuários mais ativos"
          items={(stats?.top_users || []).map((u) => ({
            label: `${u.email || u.user_id || "?"} (${u.role || "?"})`,
            value: u.count,
          }))}
          testid="top-users" />
        <TopList title="Endpoints mais acessados"
          items={(stats?.top_endpoints || []).map((e) => ({
            label: e.endpoint, value: e.count,
          }))}
          testid="top-endpoints" />
      </div>

      {/* Filtros */}
      <form onSubmit={applyFilters} data-testid="audit-filters" style={{
        background: ORACLE.panel, padding: 12, borderRadius: 8,
        marginBottom: 12, display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
        gap: 8, alignItems: "center",
      }}>
        <Filter size={16} color={ORACLE.muted} />
        <input data-testid="filter-user-email" placeholder="usuário (email)"
          value={filters.user_email}
          onChange={(e) => setFilters({ ...filters, user_email: e.target.value })}
          style={inputStyle} />
        <select data-testid="filter-role"
          value={filters.role}
          onChange={(e) => setFilters({ ...filters, role: e.target.value })}
          style={inputStyle}>
          {ROLE_OPTS.map((r) => (
            <option key={r} value={r}>{r || "qualquer role"}</option>
          ))}
        </select>
        <select data-testid="filter-category"
          value={filters.category}
          onChange={(e) => setFilters({ ...filters, category: e.target.value })}
          style={inputStyle}>
          {CATEGORY_OPTS.map((c) => (
            <option key={c.v} value={c.v}>{c.label}</option>
          ))}
        </select>
        <select data-testid="filter-criticality"
          value={filters.criticality}
          onChange={(e) => setFilters({ ...filters, criticality: e.target.value })}
          style={inputStyle}>
          <option value="">qualquer criticidade</option>
          <option value="alta">alta</option>
          <option value="media">média</option>
          <option value="baixa">baixa</option>
        </select>
        <input data-testid="filter-endpoint" placeholder="endpoint (regex)"
          value={filters.endpoint}
          onChange={(e) => setFilters({ ...filters, endpoint: e.target.value })}
          style={inputStyle} />
        <input data-testid="filter-action" placeholder="ação"
          value={filters.action}
          onChange={(e) => setFilters({ ...filters, action: e.target.value })}
          style={inputStyle} />
        <button type="submit" data-testid="filter-apply"
          style={btnStyle(ORACLE.purple)}>Aplicar</button>
      </form>

      {/* Tabela */}
      <div data-testid="audit-table-wrap" style={{
        background: ORACLE.panel, borderRadius: 8, overflow: "auto",
        border: `1px solid ${ORACLE.border}`,
      }}>
        <table data-testid="audit-table" style={{
          width: "100%", borderCollapse: "collapse", fontSize: 12,
          minWidth: 900,
        }}>
          <thead>
            <tr style={{ background: ORACLE.card, color: ORACLE.muted }}>
              <Th>Quando</Th>
              <Th>Usuário</Th>
              <Th>Role</Th>
              <Th>Categoria</Th>
              <Th>Crit.</Th>
              <Th>Endpoint</Th>
              <Th>Status</Th>
              <Th></Th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={8} style={{
                padding: 24, textAlign: "center", color: ORACLE.muted,
              }}>Carregando...</td></tr>
            )}
            {!loading && items.length === 0 && (
              <tr><td colSpan={8} style={{
                padding: 24, textAlign: "center", color: ORACLE.muted,
              }} data-testid="audit-empty">Nenhum evento encontrado.</td></tr>
            )}
            {!loading && items.map((it) => (
              <tr key={it.id} data-testid={`audit-row-${it.id}`} style={{
                borderTop: `1px solid ${ORACLE.border}`,
              }}>
                <Td>{fmtDate(it.created_at)}</Td>
                <Td>{it.user_email || it.user_id || "—"}</Td>
                <Td>
                  <Chip color={ORACLE.blue}>{it.user_role || "?"}</Chip>
                </Td>
                <Td>{CATEGORY_LABEL[it.category] || it.category || "—"}</Td>
                <Td>
                  <Chip color={CRITICALITY_COLOR[it.criticality]
                    || ORACLE.muted}>
                    {it.criticality || "?"}
                  </Chip>
                </Td>
                <Td><code style={{
                  fontSize: 11, color: ORACLE.muted,
                }}>{(it.endpoint || "").slice(0, 50)}</code></Td>
                <Td>{it.status ?? "—"}</Td>
                <Td>
                  <button onClick={() => setSelected(it)}
                    data-testid={`audit-detail-btn-${it.id}`}
                    style={{
                      background: "transparent", border: 0,
                      color: ORACLE.blue, cursor: "pointer",
                    }}><Eye size={14} /></button>
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Paginação */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginTop: 12, fontSize: 12, color: ORACLE.muted,
      }}>
        <span data-testid="audit-total">{total} eventos</span>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0} data-testid="page-prev"
            style={btnStyle(ORACLE.card)}>← Anterior</button>
          <span style={{ alignSelf: "center" }}>Página {page + 1}</span>
          <button onClick={() => setPage((p) => p + 1)}
            disabled={(page + 1) * pageSize >= total}
            data-testid="page-next"
            style={btnStyle(ORACLE.card)}>Próxima →</button>
        </div>
      </div>

      {/* Drawer */}
      {selected && (
        <DetailDrawer event={selected} onClose={() => setSelected(null)} />
      )}

      <style>{`
        @keyframes spin {
          from { transform: rotate(0); } to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}

// ─────────────────── Sub-components ───────────────────

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
      }}>
        <span style={{ color }}>{icon}</span>{label}
      </div>
      <div style={{
        marginTop: 8, fontSize: 28, fontWeight: 800, color: ORACLE.ink,
      }}>{value ?? "—"}</div>
    </div>
  );
}

function TopList({ title, items, testid }) {
  return (
    <div data-testid={testid} style={{
      background: ORACLE.panel, padding: 14, borderRadius: 10,
    }}>
      <div style={{
        fontSize: 12, fontWeight: 700, color: ORACLE.muted,
        textTransform: "uppercase", marginBottom: 10,
      }}>{title}</div>
      {items.length === 0 && (
        <div style={{ fontSize: 13, color: ORACLE.muted }}>—</div>
      )}
      {items.slice(0, 5).map((it, i) => (
        <div key={i} style={{
          display: "flex", justifyContent: "space-between",
          padding: "6px 0", fontSize: 12,
          borderBottom: i < 4 ? `1px solid ${ORACLE.border}` : "none",
        }}>
          <span style={{
            color: ORACLE.ink, overflow: "hidden",
            textOverflow: "ellipsis", whiteSpace: "nowrap",
            maxWidth: 220,
          }}>{it.label}</span>
          <span style={{ color: ORACLE.purple, fontWeight: 700 }}>
            {it.value}
          </span>
        </div>
      ))}
    </div>
  );
}

function Chip({ color, children }) {
  return (
    <span style={{
      background: `${color}33`, color, padding: "2px 8px",
      borderRadius: 999, fontSize: 11, fontWeight: 700,
      border: `1px solid ${color}66`,
    }}>{children}</span>
  );
}

function DetailDrawer({ event, onClose }) {
  const [full, setFull] = useState(null);
  useEffect(() => {
    api._client.get(`/audit-log/${event.id}`)
      .then((r) => setFull(r.data))
      .catch(() => setFull(event));
  }, [event]);
  const e = full || event;
  return (
    <div data-testid="audit-detail-drawer" style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.5)",
      display: "flex", justifyContent: "flex-end", zIndex: 99,
    }} onClick={onClose}>
      <div onClick={(ev) => ev.stopPropagation()} style={{
        width: 480, maxWidth: "100vw", background: ORACLE.panel,
        height: "100%", overflow: "auto", padding: 24,
        color: ORACLE.ink,
      }}>
        <div style={{
          display: "flex", justifyContent: "space-between",
          alignItems: "center", marginBottom: 16,
        }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 800 }}>
            Detalhe do evento
          </h2>
          <button onClick={onClose} data-testid="drawer-close" style={{
            background: "transparent", border: 0, color: ORACLE.ink,
            cursor: "pointer",
          }}><X size={20} /></button>
        </div>
        <Row k="ID" v={e.id} />
        <Row k="Data/hora" v={fmtDate(e.created_at)} />
        <Row k="Usuário" v={e.user_email} />
        <Row k="Role" v={e.user_role} />
        <Row k="Empresa" v={e.company_id} />
        <Row k="IP" v={e.ip} />
        <Row k="User-Agent" v={e.user_agent} />
        <Row k="Método" v={e.method} />
        <Row k="Endpoint" v={<code>{e.endpoint}</code>} />
        <Row k="Ação" v={e.action} />
        <Row k="Categoria" v={CATEGORY_LABEL[e.category] || e.category} />
        <Row k="Criticidade" v={e.criticality} />
        <Row k="Status" v={e.status} />
        <Row k="Motivo" v={e.reason} />
        <div style={{ marginTop: 16 }}>
          <div style={{
            fontSize: 11, color: ORACLE.muted, fontWeight: 700,
            textTransform: "uppercase", marginBottom: 4,
          }}>Dados</div>
          <pre style={{
            background: ORACLE.bg, padding: 10, borderRadius: 6,
            fontSize: 11, overflow: "auto", color: ORACLE.muted,
          }}>{JSON.stringify(e.data, null, 2)}</pre>
        </div>
      </div>
    </div>
  );
}

function Row({ k, v }) {
  return (
    <div style={{
      display: "flex", padding: "6px 0",
      borderBottom: `1px solid ${ORACLE.border}`, fontSize: 12,
    }}>
      <span style={{
        flex: "0 0 130px", color: ORACLE.muted, fontWeight: 600,
      }}>{k}</span>
      <span style={{ flex: 1, color: ORACLE.ink, wordBreak: "break-all" }}>
        {v ?? "—"}
      </span>
    </div>
  );
}

function Th({ children }) {
  return <th style={{
    padding: "10px 12px", textAlign: "left", fontWeight: 700,
    fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5,
  }}>{children}</th>;
}

function Td({ children }) {
  return <td style={{
    padding: "8px 12px", color: ORACLE.ink,
  }}>{children}</td>;
}

const inputStyle = {
  background: ORACLE.card, color: ORACLE.ink,
  border: `1px solid ${ORACLE.border}`, padding: "6px 8px",
  borderRadius: 6, fontSize: 12, outline: "none",
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
    const d = new Date(s);
    return d.toLocaleString("pt-BR", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch { return s; }
}

function stripEmpty(obj) {
  const out = {};
  Object.entries(obj || {}).forEach(([k, v]) => {
    if (v !== "" && v !== null && v !== undefined) out[k] = v;
  });
  return out;
}
