import React, { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/api";

const ACCENT = "#10b981";

function fmtBRL(v) {
  return Number(v || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function StatusBadge({ status }) {
  const map = {
    trialing: { bg: "#fef3c7", fg: "#92400e", label: "Trial" },
    active: { bg: "#d1fae5", fg: "#065f46", label: "Ativo" },
    past_due: { bg: "#fee2e2", fg: "#991b1b", label: "Inadimplente" },
    cancelled: { bg: "#e2e8f0", fg: "#475569", label: "Cancelado" },
  };
  const m = map[status] || { bg: "#e2e8f0", fg: "#475569", label: status };
  return (
    <span style={{
      background: m.bg, color: m.fg, padding: "3px 10px",
      borderRadius: 999, fontSize: 11, fontWeight: 700,
    }}>{m.label}</span>
  );
}

function KpiCard({ label, value, sub, accent = false }) {
  return (
    <div style={{
      background: "white", padding: 18, borderRadius: 14,
      border: accent ? "1px solid #10b981" : "1px solid #e2e8f0",
      boxShadow: accent ? "0 8px 24px rgba(16,185,129,.12)" : "0 1px 2px rgba(15,23,42,.04)",
    }}>
      <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 700 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 900, color: accent ? "#10b981" : "#0f172a", marginTop: 4, letterSpacing: "-0.02em" }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

export default function PlatformAdminPanel() {
  const [m, setM] = useState(null);
  const [companies, setCompanies] = useState([]);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [err, setErr] = useState("");
  const [editing, setEditing] = useState(null);

  function reload() {
    return Promise.all([api.saasAdminMetrics(), api.saasListCompanies()])
      .then(([metrics, list]) => { setM(metrics); setCompanies(list); })
      .catch((e) => setErr(e?.response?.data?.detail || e.message));
  }

  useEffect(() => {
    let alive = true;
    Promise.all([api.saasAdminMetrics(), api.saasListCompanies()])
      .then(([metrics, list]) => { if (alive) { setM(metrics); setCompanies(list); } })
      .catch((e) => { if (alive) setErr(e?.response?.data?.detail || e.message); });
    return () => { alive = false; };
  }, []);

  if (err) return <div style={{ padding: 22, color: "#991b1b" }}>{err}</div>;
  if (!m) return <div style={{ padding: 22, color: "#64748b" }}>Carregando métricas...</div>;

  const filtered = companies.filter((c) => {
    if (filter !== "all" && c.status_effective !== filter && !(filter === "free" && c.plan === "free")) return false;
    if (search && !c.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div data-testid="platform-admin-panel" style={{ background: "white", borderRadius: 16, border: "1px solid #e2e8f0", padding: 24 }}>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em", color: "#0f172a" }}>
          🛡️ Painel da Plataforma <span style={{ fontSize: 12, color: "#64748b", fontWeight: 500 }}>· super admin</span>
        </h2>
        <p style={{ margin: "4px 0 0", fontSize: 13, color: "#64748b" }}>Visão consolidada de todas as empresas, MRR, churn e crescimento.</p>
      </div>

      {/* KPIs */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12, marginBottom: 24 }}>
        <KpiCard label="MRR" value={fmtBRL(m.mrr_brl)} sub={`ARR ${fmtBRL(m.arr_brl)}`} accent />
        <KpiCard label="Empresas total" value={m.total_companies} sub={`${m.by_status.active || 0} ativas · ${m.by_status.trialing || 0} trial`} />
        <KpiCard label="Free" value={m.by_status.free || 0} sub="contas gratuitas" />
        <KpiCard label="Inadimplentes" value={m.by_status.past_due || 0} sub={`Churn 30d: ${m.churn_rate_pct}%`} />
        <KpiCard label="Colaboradores" value={m.total_collaborators} sub="cross-tenant" />
      </div>

      {/* Signups chart */}
      <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 14, padding: 18, marginBottom: 24 }} data-testid="platform-signups-chart">
        <div style={{ marginBottom: 10, fontSize: 13, fontWeight: 700, color: "#0f172a" }}>Signups por mês (últimos 12)</div>
        <div style={{ width: "100%", height: 220 }}>
          <ResponsiveContainer>
            <BarChart data={m.signups_series}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="month" tickFormatter={(v) => v.slice(5)} stroke="#64748b" fontSize={11} />
              <YAxis stroke="#64748b" fontSize={11} allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="count" fill={ACCENT} radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Filtros */}
      <div style={{ display: "flex", gap: 10, marginBottom: 14, flexWrap: "wrap", alignItems: "center" }}>
        <input
          type="text" placeholder="Buscar empresa..."
          value={search} onChange={(e) => setSearch(e.target.value)}
          data-testid="platform-search"
          style={{
            padding: "9px 14px", borderRadius: 10, border: "1px solid #cbd5e1",
            fontSize: 13, outline: "none", flex: "1 1 240px",
          }}
        />
        {[
          { id: "all", label: `Todas (${companies.length})` },
          { id: "active", label: `Ativas (${m.by_status.active || 0})` },
          { id: "trialing", label: `Trial (${m.by_status.trialing || 0})` },
          { id: "free", label: `Free (${m.by_status.free || 0})` },
          { id: "past_due", label: `Inadimplentes (${m.by_status.past_due || 0})` },
        ].map((f) => (
          <button
            key={f.id} onClick={() => setFilter(f.id)}
            data-testid={`platform-filter-${f.id}`}
            style={{
              padding: "9px 14px", borderRadius: 999, border: 0, cursor: "pointer",
              background: filter === f.id ? "#0f172a" : "#f1f5f9",
              color: filter === f.id ? "white" : "#475569",
              fontSize: 12, fontWeight: 700,
            }}
          >{f.label}</button>
        ))}
      </div>

      {/* Tabela */}
      <div style={{ overflowX: "auto", border: "1px solid #e2e8f0", borderRadius: 12 }}>
        <table data-testid="platform-companies-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f8fafc", color: "#475569", textAlign: "left" }}>
              <th style={{ padding: "11px 14px", fontWeight: 700 }}>Empresa</th>
              <th style={{ padding: "11px 14px", fontWeight: 700 }}>Plano</th>
              <th style={{ padding: "11px 14px", fontWeight: 700 }}>Status</th>
              <th style={{ padding: "11px 14px", fontWeight: 700 }}>Colabs</th>
              <th style={{ padding: "11px 14px", fontWeight: 700 }}>Owner</th>
              <th style={{ padding: "11px 14px", fontWeight: 700 }}>Criada</th>
              <th style={{ padding: "11px 14px", fontWeight: 700, width: 80 }}></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((c) => (
              <tr key={c.id} style={{ borderTop: "1px solid #e2e8f0" }}>
                <td style={{ padding: "11px 14px", fontWeight: 600, color: "#0f172a" }}>{c.name}{c.is_demo && <span style={{ marginLeft: 6, fontSize: 10, background: "#fef3c7", color: "#92400e", padding: "1px 6px", borderRadius: 4 }}>DEMO</span>}</td>
                <td style={{ padding: "11px 14px", color: "#475569" }}>
                  {c.plan === "free" ? "Free"
                    : c.plan === "enterprise" ? <span style={{ background: "#ddd6fe", color: "#5b21b6", padding: "2px 8px", borderRadius: 6, fontSize: 11, fontWeight: 800 }}>⭐ Enterprise</span>
                    : "Pro · R$ " + (c.plan_price_brl || 99)}
                </td>
                <td style={{ padding: "11px 14px" }}>
                  {c.plan === "free" ? <span style={{ background: "#e0e7ff", color: "#3730a3", padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 700 }}>Free</span> : <StatusBadge status={c.status_effective} />}
                </td>
                <td style={{ padding: "11px 14px", color: "#475569" }}>{c.collaborators_count}/{c.max_collaborators}</td>
                <td style={{ padding: "11px 14px", color: "#475569", fontSize: 12 }}>{c.owner_email}</td>
                <td style={{ padding: "11px 14px", color: "#94a3b8", fontSize: 12 }}>{(c.created_at || "").slice(0, 10)}</td>
                <td style={{ padding: "11px 14px" }}>
                  <button
                    onClick={() => setEditing(c)}
                    data-testid={`edit-company-${c.id}`}
                    style={{
                      background: "transparent", color: "#0f172a",
                      border: "1px solid #cbd5e1", padding: "4px 10px",
                      borderRadius: 6, fontSize: 11, fontWeight: 700, cursor: "pointer",
                    }}
                  >Editar</button>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={7} style={{ padding: 24, textAlign: "center", color: "#94a3b8" }}>Nenhuma empresa encontrada.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {editing && <EditCompanyModal company={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload(); }} />}
    </div>
  );
}


function EditCompanyModal({ company, onClose, onSaved }) {
  const [plan, setPlan] = useState(company.plan || "monthly_99");
  const [maxColab, setMaxColab] = useState(company.max_collaborators || 25);
  const [price, setPrice] = useState(company.plan_price_brl || 99);
  const [status, setStatus] = useState(company.status || "active");
  const [paidUntil, setPaidUntil] = useState((company.paid_until || "").slice(0, 10));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    setBusy(true); setErr("");
    try {
      const data = {
        plan, max_collaborators: Number(maxColab),
        plan_price_brl: Number(price), status,
      };
      if (paidUntil) data.paid_until = `${paidUntil}T23:59:59+00:00`;
      await api.saasUpdateCompany(company.id, data);
      onSaved?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  }

  const inputStyle = { width: "100%", padding: "10px 12px", borderRadius: 10, border: "1px solid #cbd5e1", fontSize: 14, outline: "none", boxSizing: "border-box" };
  const lbl = { display: "block", color: "#475569", fontSize: 11, fontWeight: 700, marginBottom: 5, letterSpacing: "0.04em", textTransform: "uppercase" };

  return (
    <div data-testid="edit-company-modal" onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,.5)",
      display: "grid", placeItems: "center", zIndex: 100, padding: 20,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 18, padding: 28, maxWidth: 480, width: "100%",
        boxShadow: "0 30px 60px rgba(15,23,42,.3)",
      }}>
        <h3 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: "#0f172a" }}>Editar empresa</h3>
        <p style={{ margin: "4px 0 18px", fontSize: 13, color: "#64748b" }}>{company.name} · ID: <code style={{ fontSize: 11 }}>{company.id}</code></p>

        {err && <div style={{ background: "#fee2e2", color: "#991b1b", padding: 10, borderRadius: 8, fontSize: 13, marginBottom: 14 }}>{err}</div>}

        <div style={{ marginBottom: 14 }}>
          <label style={lbl}>Plano</label>
          <select data-testid="edit-plan" value={plan} onChange={(e) => setPlan(e.target.value)} style={inputStyle}>
            <option value="free">Free (R$ 0)</option>
            <option value="monthly_99">Pro (R$ 99/mês)</option>
            <option value="enterprise">⭐ Enterprise (customizado)</option>
          </select>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 14 }}>
          <div>
            <label style={lbl}>Máx. colaboradores</label>
            <input data-testid="edit-max-colabs" type="number" min={1} value={maxColab} onChange={(e) => setMaxColab(e.target.value)} style={inputStyle} />
          </div>
          <div>
            <label style={lbl}>Preço (R$/mês)</label>
            <input data-testid="edit-price" type="number" step="0.01" value={price} onChange={(e) => setPrice(e.target.value)} style={inputStyle} />
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 22 }}>
          <div>
            <label style={lbl}>Status</label>
            <select data-testid="edit-status" value={status} onChange={(e) => setStatus(e.target.value)} style={inputStyle}>
              <option value="active">Ativo</option>
              <option value="trialing">Trial</option>
              <option value="past_due">Inadimplente</option>
              <option value="cancelled">Cancelado</option>
            </select>
          </div>
          <div>
            <label style={lbl}>Pago até</label>
            <input data-testid="edit-paid-until" type="date" value={paidUntil} onChange={(e) => setPaidUntil(e.target.value)} style={inputStyle} />
          </div>
        </div>

        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={onClose} disabled={busy} style={{ flex: 1, padding: "11px 16px", borderRadius: 10, border: "1px solid #cbd5e1", background: "white", color: "#475569", fontSize: 13, fontWeight: 700, cursor: "pointer" }}>Cancelar</button>
          <button onClick={save} disabled={busy} data-testid="edit-save-btn" style={{ flex: 1, padding: "11px 16px", borderRadius: 10, border: 0, background: "#10b981", color: "white", fontSize: 13, fontWeight: 800, cursor: busy ? "wait" : "pointer", opacity: busy ? 0.7 : 1 }}>{busy ? "Salvando..." : "Salvar"}</button>
        </div>
      </div>
    </div>
  );
}
