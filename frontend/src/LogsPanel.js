import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { Button, Card, Icon } from "@/ui";

const TYPE_META = {
  login:        { label: "Login senha", icon: "🔐", color: "#0ea5e9" },
  collab_login: { label: "Login Google (Colab.)", icon: "📱", color: "#16a34a" },
  impersonation:{ label: "Impersonation", icon: "🎭", color: "#7c3aed" },
  system:       { label: "Sistema", icon: "⚙️", color: "#f59e0b" },
  push:         { label: "Push", icon: "🔔", color: "#0284c7" },
  clock:        { label: "Ponto (manual/auditoria)", icon: "🕒", color: "#dc2626" },
};

function fmt(at) {
  if (!at) return "—";
  try {
    const d = new Date(at);
    return d.toLocaleString("pt-BR");
  } catch {
    return at;
  }
}

export default function LogsPanel() {
  const [data, setData] = useState(null);
  const [days, setDays] = useState(7);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [filter, setFilter] = useState(""); // tipo selecionado
  const [search, setSearch] = useState("");

  async function reload() {
    setLoading(true); setErr("");
    try {
      const r = await api.listLogs({ days, limit: 500 });
      setData(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setLoading(false);
  }
  useEffect(() => { reload(); /* eslint-disable-next-line */ }, [days]);

  const filtered = useMemo(() => {
    if (!data?.items) return [];
    const q = search.trim().toLowerCase();
    return data.items.filter((it) => {
      if (filter && it.type !== filter) return false;
      if (!q) return true;
      const blob = `${it.title || ""} ${it.detail || ""} ${it.actor || ""}`.toLowerCase();
      return blob.includes(q);
    });
  }, [data, filter, search]);

  const counts = data?.by_type || {};

  return (
    <div>
      <Card
        title={<><Icon name="history" /> Logs do sistema</>}
        action={
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              data-testid="logs-days"
              style={{ padding: "6px 10px", borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 13 }}
            >
              <option value={1}>Hoje</option>
              <option value={3}>Últimos 3 dias</option>
              <option value={7}>Últimos 7 dias</option>
              <option value={30}>Últimos 30 dias</option>
              <option value={90}>Últimos 90 dias</option>
            </select>
            <Button onClick={reload} variant="soft" data-testid="logs-reload-btn"><Icon name="sync" /> Atualizar</Button>
          </div>
        }
      >
        {err && <div style={{ background: "#fee2e2", color: "#991b1b", padding: 10, borderRadius: 12, marginBottom: 10 }}>{err}</div>}

        {/* Chips de tipo */}
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }} data-testid="logs-filters">
          <button
            onClick={() => setFilter("")}
            data-testid="filter-all"
            style={{
              padding: "6px 12px", borderRadius: 999, border: "1px solid #cbd5e1",
              background: filter === "" ? "#0f172a" : "white", color: filter === "" ? "white" : "#0f172a",
              fontWeight: 700, fontSize: 12, cursor: "pointer",
            }}
          >
            Todos ({data?.total || 0})
          </button>
          {Object.entries(TYPE_META).map(([k, m]) => (
            <button
              key={k}
              data-testid={`filter-${k}`}
              onClick={() => setFilter(filter === k ? "" : k)}
              disabled={!counts[k]}
              style={{
                padding: "6px 12px", borderRadius: 999, border: `1px solid ${m.color}`,
                background: filter === k ? m.color : "white",
                color: filter === k ? "white" : m.color,
                fontWeight: 700, fontSize: 12, cursor: counts[k] ? "pointer" : "not-allowed",
                opacity: counts[k] ? 1 : 0.4,
              }}
            >
              {m.icon} {m.label} ({counts[k] || 0})
            </button>
          ))}
        </div>

        <input
          data-testid="logs-search"
          placeholder="Buscar por usuário, título ou detalhes..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            width: "100%", padding: "9px 12px", borderRadius: 10,
            border: "1px solid #cbd5e1", fontSize: 14, marginBottom: 12,
          }}
        />

        {loading && <div style={{ color: "#64748b", padding: 12 }}>Carregando…</div>}
        {!loading && filtered.length === 0 && (
          <div style={{ background: "#f8fafc", border: "1px dashed #cbd5e1", borderRadius: 12, padding: 24, textAlign: "center", color: "#64748b" }}>
            Nenhum evento encontrado para o período/filtros selecionados.
          </div>
        )}

        <div data-testid="logs-list">
          {filtered.map((it, idx) => {
            const meta = TYPE_META[it.type] || { label: it.type, icon: "•", color: "#64748b" };
            const lvlBg = it.level === "danger" ? "#fee2e2" : it.level === "warning" ? "#fef3c7" : "#eff6ff";
            const lvlBorder = it.level === "danger" ? "#fecaca" : it.level === "warning" ? "#fde68a" : "#bfdbfe";
            return (
              <div
                key={idx}
                data-testid={`log-row-${idx}`}
                style={{
                  display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 12,
                  padding: "12px 14px", borderRadius: 12, marginBottom: 8,
                  background: lvlBg, border: `1px solid ${lvlBorder}`,
                }}
              >
                <div style={{ fontSize: 22 }}>{meta.icon}</div>
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <span style={{
                      fontSize: 10, padding: "2px 8px", borderRadius: 999,
                      background: meta.color, color: "white", fontWeight: 800, letterSpacing: "0.04em",
                      textTransform: "uppercase",
                    }}>{meta.label}</span>
                    <strong style={{ fontSize: 13 }}>{it.title}</strong>
                    {it.actor && <span style={{ fontSize: 11, color: "#64748b" }}>por {it.actor}</span>}
                  </div>
                  <div style={{ color: "#475569", fontSize: 12, marginTop: 2, wordBreak: "break-word" }}>
                    {it.detail}
                  </div>
                </div>
                <div style={{ fontSize: 11, color: "#64748b", whiteSpace: "nowrap", alignSelf: "center" }}>
                  {fmt(it.at)}
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}
