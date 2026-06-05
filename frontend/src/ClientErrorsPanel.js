/*
ClientErrorsPanel.js — iter211ag

Painel admin pra visualizar crashes de frontend que caíram nos ErrorBoundaries
do React (POST /api/client-errors/log). Inclui:
  • Resumo por boundary (top 50, últimos 7 dias)
  • Lista detalhada (filtros por boundary + busca)
  • Quando o boundary é `bubble-<ticket_id>`, extrai o ID e cria link
    direto pra inspecionar o ticket no DB.

Restrito a gestor/auditor/administrador. Clear total = super admin.
*/
import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";

const TS_FMT = (iso) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch { return iso; }
};

function extractTicketId(boundary) {
  if (typeof boundary !== "string") return null;
  const m = boundary.match(/^bubble-(.+)$/);
  return m ? m[1] : null;
}

export default function ClientErrorsPanel() {
  const [summary, setSummary] = useState(null);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [filterBoundary, setFilterBoundary] = useState("");
  const [search, setSearch] = useState("");
  const [days, setDays] = useState(7);
  const [expanded, setExpanded] = useState(null); // index do item aberto

  const reload = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const params = new URLSearchParams();
      if (filterBoundary) params.set("boundary", filterBoundary);
      if (search) params.set("q", search);
      params.set("limit", "200");
      const [s, l] = await Promise.all([
        api._client.get(`/client-errors/summary?days=${days}`).then((r) => r.data),
        api._client.get(`/client-errors/list?${params.toString()}`).then((r) => r.data),
      ]);
      setSummary(s);
      setItems(l.items || []);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setLoading(false);
  }, [filterBoundary, search, days]);

  useEffect(() => { reload(); }, [reload]);

  const clearAll = async () => {
    if (!window.confirm("Apagar TODOS os logs de crashes? Essa ação não pode ser desfeita.")) return;
    try {
      await api._client.delete("/client-errors/clear");
      reload();
    } catch (e) {
      alert("Falha: " + (e?.response?.data?.detail || e.message));
    }
  };

  const clearBoundary = async (boundary) => {
    if (!window.confirm(`Apagar logs do boundary "${boundary}"?`)) return;
    try {
      await api._client.delete(`/client-errors/clear?boundary=${encodeURIComponent(boundary)}`);
      reload();
    } catch (e) {
      alert("Falha: " + (e?.response?.data?.detail || e.message));
    }
  };

  return (
    <div style={{ padding: "0 4px", display: "grid", gap: 16 }}
          data-testid="client-errors-panel">
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <h1 style={{ fontSize: 24, fontWeight: 700,
                       color: "var(--text-primary)",
                       letterSpacing: "-0.02em", margin: 0 }}>
          ⚠️ Crashes do Frontend
        </h1>
        <span style={{ color: "#64748b", fontSize: 13 }}>
          Erros capturados pelos ErrorBoundaries do React. Útil pra rastrear
          OS com dados estranhos que travam a Lousa Mobile.
        </span>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <label style={{ fontSize: 12, color: "#475569" }}>
          Janela:
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}
                  data-testid="client-errors-days"
                  style={inputStyle}>
            <option value={1}>24 horas</option>
            <option value={7}>7 dias</option>
            <option value={30}>30 dias</option>
            <option value={90}>90 dias</option>
          </select>
        </label>
        <input
          type="text" placeholder="Filtrar por boundary (ex: lousa-mobile, bubble-)"
          value={filterBoundary}
          onChange={(e) => setFilterBoundary(e.target.value.trim())}
          data-testid="client-errors-filter-boundary"
          style={{ ...inputStyle, minWidth: 260 }} />
        <input
          type="text" placeholder="Buscar na mensagem ou URL…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          data-testid="client-errors-search"
          style={{ ...inputStyle, minWidth: 220, flex: 1 }} />
        <button onClick={reload} disabled={loading}
                data-testid="client-errors-reload"
                style={btnPrimary}>
          {loading ? "⏳ Carregando…" : "🔄 Atualizar"}
        </button>
        <button onClick={clearAll}
                data-testid="client-errors-clear-all"
                title="Apaga TODOS os logs (super admin)"
                style={{ ...btnSecondary, color: "#991b1b",
                          borderColor: "#fca5a5", background: "#fee2e2" }}>
          🗑️ Limpar tudo
        </button>
      </div>

      {err && (
        <div style={{ padding: 12, background: "#fee2e2", color: "#991b1b",
                       borderRadius: 8, fontSize: 13 }} data-testid="client-errors-err">
          {err}
        </div>
      )}

      {/* Resumo por boundary */}
      <div style={cardStyle} data-testid="client-errors-summary">
        <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "baseline", marginBottom: 12 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>
            Resumo · últimos {days} {days === 1 ? "dia" : "dias"}
          </h3>
          {summary && (
            <span style={{ fontSize: 13, color: "#64748b" }}>
              {summary.total} crash{summary.total === 1 ? "" : "es"} no total
            </span>
          )}
        </div>
        {summary?.by_boundary?.length ? (
          <div style={{ display: "grid", gap: 6 }}>
            {summary.by_boundary.map((row) => {
              const tid = extractTicketId(row.boundary);
              return (
                <div key={row.boundary}
                      style={{ display: "flex", alignItems: "center", gap: 10,
                                padding: "8px 12px", background: "#f8fafc",
                                borderRadius: 8, fontSize: 13,
                                border: "1px solid #e2e8f0" }}
                      data-testid={`client-errors-summary-row-${row.boundary}`}>
                  <button onClick={() => setFilterBoundary(row.boundary)}
                          title="Filtrar lista abaixo por este boundary"
                          style={pillBtnStyle}>
                    {row.boundary}
                  </button>
                  <span style={{ flexShrink: 0, padding: "2px 8px",
                                    background: row.count > 10 ? "#fee2e2"
                                      : row.count > 3 ? "#fef3c7" : "#dbeafe",
                                    color: row.count > 10 ? "#991b1b"
                                      : row.count > 3 ? "#854d0e" : "#1e40af",
                                    borderRadius: 999, fontWeight: 700,
                                    fontSize: 12 }}>
                    {row.count}×
                  </span>
                  {tid && (
                    <span style={{ fontSize: 11, color: "#7c2d12",
                                      background: "#ffedd5",
                                      padding: "2px 8px", borderRadius: 6,
                                      fontFamily: "monospace" }}
                          title="ID do ticket extraído do nome do boundary">
                      🎯 OS …{tid.slice(-8)}
                    </span>
                  )}
                  <span style={{ flex: 1, color: "#475569",
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                    whiteSpace: "nowrap" }}
                          title={row.last_msg}>
                    {row.last_msg || "—"}
                  </span>
                  <span style={{ fontSize: 11, color: "#94a3b8",
                                    flexShrink: 0 }}>
                    {TS_FMT(row.last_ts)}
                  </span>
                  <button onClick={() => clearBoundary(row.boundary)}
                          title="Apagar logs deste boundary"
                          style={{ ...pillBtnStyle, color: "#991b1b",
                                    borderColor: "#fca5a5" }}>
                    🗑️
                  </button>
                </div>
              );
            })}
          </div>
        ) : (
          <div style={{ padding: 20, textAlign: "center", color: "#94a3b8",
                          fontSize: 13 }}>
            Nenhum crash registrado nos últimos {days} dia(s). 🎉
          </div>
        )}
      </div>

      {/* Lista detalhada */}
      <div style={cardStyle} data-testid="client-errors-list">
        <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "baseline", marginBottom: 12 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>
            Lista detalhada
            {filterBoundary && (
              <span style={{ fontSize: 12, color: "#7c2d12",
                                marginLeft: 8, padding: "2px 8px",
                                background: "#ffedd5", borderRadius: 6 }}>
                filtro: {filterBoundary}
                <button onClick={() => setFilterBoundary("")}
                        style={{ marginLeft: 6, border: "none",
                                  background: "transparent", cursor: "pointer",
                                  color: "#7c2d12" }}>✕</button>
              </span>
            )}
          </h3>
          <span style={{ fontSize: 13, color: "#64748b" }}>
            {items.length} resultado{items.length === 1 ? "" : "s"}
          </span>
        </div>
        {items.length === 0 ? (
          <div style={{ padding: 20, textAlign: "center", color: "#94a3b8",
                          fontSize: 13 }}>
            Nenhum crash encontrado.
          </div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {items.map((it, idx) => {
              const tid = extractTicketId(it.boundary);
              const isOpen = expanded === idx;
              return (
                <div key={`${it.server_ts}-${idx}`}
                      style={{ padding: "10px 12px",
                                background: isOpen ? "#fffbeb" : "#f8fafc",
                                borderRadius: 8, border: "1px solid",
                                borderColor: isOpen ? "#fde68a" : "#e2e8f0",
                                fontSize: 13 }}
                      data-testid={`client-error-item-${idx}`}>
                  <div style={{ display: "flex", gap: 10, alignItems: "center",
                                  cursor: "pointer", flexWrap: "wrap" }}
                        onClick={() => setExpanded(isOpen ? null : idx)}>
                    <span style={{ padding: "2px 8px",
                                      background: "#e0e7ff", color: "#3730a3",
                                      borderRadius: 6, fontSize: 11,
                                      fontWeight: 700,
                                      fontFamily: "monospace" }}>
                      {it.boundary}
                    </span>
                    {tid && (
                      <span style={{ fontSize: 11, color: "#7c2d12",
                                        background: "#ffedd5",
                                        padding: "2px 8px", borderRadius: 6,
                                        fontFamily: "monospace" }}>
                        🎯 OS …{tid.slice(-8)}
                      </span>
                    )}
                    <span style={{ flex: 1, color: "#0f172a",
                                      overflow: "hidden",
                                      textOverflow: "ellipsis",
                                      whiteSpace: "nowrap", minWidth: 0 }}>
                      {it.message || "(sem mensagem)"}
                    </span>
                    <span style={{ fontSize: 11, color: "#94a3b8",
                                      flexShrink: 0 }}>
                      {TS_FMT(it.server_ts)}
                    </span>
                    <span style={{ fontSize: 10, color: "#475569" }}>
                      {isOpen ? "▲" : "▼"}
                    </span>
                  </div>
                  {isOpen && (
                    <div style={{ marginTop: 10, display: "grid", gap: 6,
                                    fontSize: 12 }}>
                      <KV k="URL" v={it.url || "—"} />
                      <KV k="User-Agent" v={it.user_agent || "—"} />
                      <KV k="IP" v={it.ip || "—"} />
                      <KV k="Client TS" v={it.client_ts || "—"} />
                      {it.stack && (
                        <details>
                          <summary style={{ cursor: "pointer", color: "#475569" }}>
                            Stack ({(it.stack || "").length} chars)
                          </summary>
                          <pre style={preStyle}>{it.stack}</pre>
                        </details>
                      )}
                      {it.component_stack && (
                        <details>
                          <summary style={{ cursor: "pointer", color: "#475569" }}>
                            Component Stack
                          </summary>
                          <pre style={preStyle}>{it.component_stack}</pre>
                        </details>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function KV({ k, v }) {
  return (
    <div style={{ display: "flex", gap: 8 }}>
      <span style={{ minWidth: 90, color: "#64748b", fontSize: 11,
                       fontWeight: 700, textTransform: "uppercase",
                       letterSpacing: 0.4 }}>{k}</span>
      <span style={{ flex: 1, color: "#0f172a", wordBreak: "break-all" }}>{v}</span>
    </div>
  );
}

const inputStyle = {
  marginLeft: 6, padding: "6px 10px",
  border: "1px solid #cbd5e1", borderRadius: 6,
  fontSize: 13, background: "white",
};
const btnPrimary = {
  padding: "7px 14px", background: "#0f172a", color: "white",
  border: "none", borderRadius: 6, fontWeight: 700, fontSize: 13,
  cursor: "pointer",
};
const btnSecondary = {
  padding: "7px 14px", background: "white", color: "#475569",
  border: "1px solid #cbd5e1", borderRadius: 6, fontWeight: 600,
  fontSize: 13, cursor: "pointer",
};
const cardStyle = {
  background: "white", border: "1px solid #e2e8f0",
  borderRadius: 12, padding: 16,
  boxShadow: "0 1px 3px rgba(15,23,42,.04)",
};
const pillBtnStyle = {
  padding: "3px 10px", border: "1px solid #c7d2fe",
  background: "white", color: "#3730a3", borderRadius: 999,
  fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "monospace",
};
const preStyle = {
  background: "#1e293b", color: "#fbbf24", padding: 10,
  borderRadius: 6, fontSize: 11, overflow: "auto",
  maxHeight: 240, marginTop: 4, whiteSpace: "pre-wrap",
};
