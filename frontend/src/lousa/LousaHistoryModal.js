import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { Button } from "@/ui";

const STATUS_LABEL = {
  pendente: { label: "⏳ Pendente", color: "#94a3b8", bg: "#f1f5f9" },
  aberta: { label: "▶ Aberta", color: "#10b981", bg: "#dcfce7" },
  aguardando_atendimento: { label: "⏸ Aguardando", color: "#f59e0b", bg: "#fef3c7" },
  finalizada: { label: "✓ Finalizada", color: "#10b981", bg: "#dcfce7" },
  encerrada: { label: "■ Encerrada", color: "#475569", bg: "#e2e8f0" },
  reagendada: { label: "📅 Reagendada", color: "#3b82f6", bg: "#dbeafe" },
  cancelada: { label: "✗ Cancelada", color: "#dc2626", bg: "#fee2e2" },
};

const TYPE_LABELS = {
  reparo: "🔧 Reparo", instalacao: "📡 Instalação", retirada: "📦 Retirada",
  prioridade: "🚨 Prioridade", preventiva: "🛡️ Preventiva", venda: "💼 Venda",
};

const inputCss = { padding: "8px 10px", border: "1px solid #cbd5e1", borderRadius: 10, fontSize: 13 };

function todayStr() { return new Date().toISOString().slice(0, 10); }
function monthStr() { return new Date().toISOString().slice(0, 7); }

function fmtDuration(min) {
  if (min == null) return "—";
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h > 0 ? `${h}h${String(m).padStart(2, "0")}` : `${m}min`;
}

function fmtDateBR(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  } catch { return iso; }
}

export default function LousaHistoryModal({ onClose }) {
  const [granularity, setGranularity] = useState("day");
  const [date, setDate] = useState(todayStr());
  const [month, setMonth] = useState(monthStr());
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const [dateFrom, setDateFrom] = useState(todayStr());
  const [dateTo, setDateTo] = useState(todayStr());
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");

  const params = useMemo(() => {
    const p = { granularity };
    if (granularity === "day") p.date = date;
    if (granularity === "month") p.month = month;
    if (granularity === "year") p.year = year;
    if (granularity === "range") { p.date_from = dateFrom; p.date_to = dateTo; }
    // status filter NÃO vai pro backend — fazemos client-side para os cards continuarem mostrando contagens reais
    if (typeFilter) p.type = typeFilter;
    return p;
  }, [granularity, date, month, year, dateFrom, dateTo, typeFilter]);

  useEffect(() => {
    let alive = true;
    setLoading(true); setErr("");
    api.lousaHistory(params)
      .then((d) => { if (alive) setData(d); })
      .catch((e) => { if (alive) setErr(e?.response?.data?.detail || e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [params]);

  // Filtro client-side: status (do toggle de cards / dropdown) + busca textual
  const filteredItems = useMemo(() => {
    if (!data?.items) return [];
    let arr = data.items;
    if (statusFilter) arr = arr.filter((it) => it.status === statusFilter);
    const q = search.trim().toLowerCase();
    if (q) {
      arr = arr.filter((it) => {
        const hay = [
          it.client_name, it.address, it.neighborhood, it.admin_notes,
          it.collaborator_name, it.type, it.status,
        ].filter(Boolean).join(" ").toLowerCase();
        return hay.includes(q);
      });
    }
    return arr;
  }, [data, search, statusFilter]);

  function exportCsv() {
    if (!filteredItems.length) return;
    const cols = ["created_at", "closed_at", "client_name", "address", "neighborhood", "type", "priority", "status", "duration_minutes", "collaborator_name", "scheduled_time", "admin_action", "admin_notes"];
    const head = cols.join(";");
    const lines = filteredItems.map((it) =>
      cols.map((c) => {
        const raw = (it[c] ?? "").toString().replace(/[\r\n]+/g, " | ").replace(/"/g, '""');
        return `"${raw}"`;
      }).join(";")
    );
    const blob = new Blob(["\uFEFF" + head + "\n" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `historico_lousa_${data.label || "export"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div onClick={onClose} data-testid="lousa-history-modal" style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.65)", zIndex: 110,
      display: "grid", placeItems: "center", padding: 16,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 18, padding: 22,
        maxWidth: 1100, width: "100%", maxHeight: "94vh", display: "flex", flexDirection: "column",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
          <h2 style={{ margin: 0, fontSize: 20 }}>📚 Histórico da Lousa</h2>
          <div style={{ display: "flex", gap: 6 }}>
            <Button variant="soft" onClick={exportCsv} disabled={!filteredItems.length} data-testid="history-export-csv">📥 Exportar CSV</Button>
            <Button variant="soft" onClick={onClose} data-testid="history-close-btn">Fechar</Button>
          </div>
        </div>

        {/* Filtros */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12, alignItems: "center" }}>
          <div style={{ display: "flex", gap: 4, padding: 4, background: "#f1f5f9", borderRadius: 12 }}>
            {[
              { v: "day", l: "📅 Dia" },
              { v: "month", l: "🗓️ Mês" },
              { v: "year", l: "🏷️ Ano" },
              { v: "range", l: "📆 Período" },
            ].map((opt) => (
              <button key={opt.v}
                data-testid={`history-gran-${opt.v}`}
                onClick={() => setGranularity(opt.v)}
                style={{
                  padding: "6px 12px", borderRadius: 8, border: 0, fontSize: 12, fontWeight: 700,
                  cursor: "pointer",
                  background: granularity === opt.v ? "#0f172a" : "transparent",
                  color: granularity === opt.v ? "white" : "#475569",
                }}
              >{opt.l}</button>
            ))}
          </div>
          {granularity === "day" && (
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} style={inputCss} data-testid="history-date-day" />
          )}
          {granularity === "month" && (
            <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} style={inputCss} data-testid="history-date-month" />
          )}
          {granularity === "year" && (
            <input type="number" min="2020" max="2099" value={year} onChange={(e) => setYear(e.target.value)} style={{ ...inputCss, width: 100 }} data-testid="history-date-year" />
          )}
          {granularity === "range" && (
            <>
              <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} style={inputCss} data-testid="history-date-from" />
              <span style={{ color: "#94a3b8" }}>→</span>
              <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} style={inputCss} data-testid="history-date-to" />
            </>
          )}

          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} style={inputCss} data-testid="history-status-filter">
            <option value="">Todos os status</option>
            {Object.entries(STATUS_LABEL).map(([v, s]) => (
              <option key={v} value={v}>{s.label}</option>
            ))}
          </select>
          <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} style={inputCss} data-testid="history-type-filter">
            <option value="">Todos os tipos</option>
            {Object.entries(TYPE_LABELS).map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>

          <div style={{ position: "relative", flex: 1, minWidth: 220 }}>
            <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "#94a3b8", fontSize: 14, pointerEvents: "none" }}>🔍</span>
            <input
              data-testid="history-search"
              type="text"
              placeholder="Buscar cliente, endereço, bairro, notas, técnico..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ ...inputCss, width: "100%", paddingLeft: 32 }}
            />
            {search && (
              <button
                data-testid="history-search-clear"
                onClick={() => setSearch("")}
                style={{ position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)", background: "transparent", border: 0, color: "#94a3b8", cursor: "pointer", fontSize: 16, padding: 4 }}
                title="Limpar busca"
              >✕</button>
            )}
          </div>
        </div>

        {/* Resumo (cards clicáveis para filtrar por status) */}
        {data && (
          <div data-testid="history-summary" style={{
            background: "linear-gradient(135deg,#f8fafc,#e2e8f0)", borderRadius: 12, padding: 12, marginBottom: 12,
            display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 8,
          }}>
            <Stat label="Total" value={data.summary.total} statusKey="" active={statusFilter === ""} onClick={() => setStatusFilter("")} testId="history-stat-total" />
            <Stat label="Finalizadas" value={data.summary.finalizada} color="#10b981" statusKey="finalizada" active={statusFilter === "finalizada"} onClick={() => setStatusFilter(statusFilter === "finalizada" ? "" : "finalizada")} testId="history-stat-finalizada" />
            <Stat label="Encerradas" value={data.summary.encerrada} color="#475569" statusKey="encerrada" active={statusFilter === "encerrada"} onClick={() => setStatusFilter(statusFilter === "encerrada" ? "" : "encerrada")} testId="history-stat-encerrada" />
            <Stat label="Reagendadas" value={data.summary.reagendada} color="#3b82f6" statusKey="reagendada" active={statusFilter === "reagendada"} onClick={() => setStatusFilter(statusFilter === "reagendada" ? "" : "reagendada")} testId="history-stat-reagendada" />
            <Stat label="Canceladas" value={data.summary.cancelada} color="#dc2626" statusKey="cancelada" active={statusFilter === "cancelada"} onClick={() => setStatusFilter(statusFilter === "cancelada" ? "" : "cancelada")} testId="history-stat-cancelada" />
            <Stat label="Tempo médio" value={data.summary.avg_duration_minutes != null ? fmtDuration(data.summary.avg_duration_minutes) : "—"} color="#a855f7" testId="history-stat-avg" />
            {data.summary.top_collaborator && (
              <Stat label="Top técnico" value={`${data.summary.top_collaborator.name?.split(" ")[0]} (${data.summary.top_collaborator.count})`} color="#f59e0b" testId="history-stat-top" />
            )}
          </div>
        )}

        {/* Tabela */}
        <div style={{ flex: 1, overflow: "auto", border: "1px solid #e2e8f0", borderRadius: 12 }}>
          {loading && <div style={{ padding: 20, textAlign: "center", color: "#64748b" }}>Carregando histórico...</div>}
          {err && <div style={{ padding: 20, color: "#dc2626" }}>Erro: {err}</div>}
          {!loading && data?.items?.length === 0 && <div style={{ padding: 20, textAlign: "center", color: "#94a3b8" }}>Nenhuma nota neste período.</div>}
          {!loading && data?.items?.length > 0 && filteredItems.length === 0 && (
            <div style={{ padding: 20, textAlign: "center", color: "#94a3b8" }}>
              Nenhuma nota corresponde à busca <strong>"{search}"</strong>.
            </div>
          )}
          {!loading && filteredItems.length > 0 && (
            <table data-testid="history-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead style={{ position: "sticky", top: 0, background: "#0f172a", color: "white", zIndex: 1 }}>
                <tr>
                  <Th>Criada</Th><Th>Cliente</Th><Th>Tipo</Th><Th>Técnico</Th>
                  <Th>Status</Th><Th>Duração</Th><Th>Encerrada</Th><Th>Notas</Th>
                </tr>
              </thead>
              <tbody>
                {filteredItems.map((it) => (
                  <tr key={it.id} data-testid={`history-row-${it.id}`} style={{ borderBottom: "1px solid #f1f5f9" }}>
                    <Td>{fmtDateBR(it.created_at)}</Td>
                    <Td><strong>{it.client_name}</strong>{it.neighborhood && <div style={{ color: "#94a3b8", fontSize: 10 }}>{it.neighborhood}</div>}</Td>
                    <Td>{TYPE_LABELS[it.type] || it.type}</Td>
                    <Td>{it.collaborator_name}</Td>
                    <Td>
                      <span style={{
                        padding: "2px 8px", borderRadius: 999, fontWeight: 700, fontSize: 10,
                        background: STATUS_LABEL[it.status]?.bg || "#f1f5f9",
                        color: STATUS_LABEL[it.status]?.color || "#64748b",
                      }}>
                        {STATUS_LABEL[it.status]?.label || it.status}
                      </span>
                    </Td>
                    <Td><strong>{fmtDuration(it.duration_minutes)}</strong></Td>
                    <Td>{fmtDateBR(it.closed_at)}</Td>
                    <Td><span style={{ color: "#475569", fontSize: 11 }}>{it.admin_notes?.substring(0, 80)}</span></Td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {data && (
          <div style={{ marginTop: 8, fontSize: 11, color: "#94a3b8", textAlign: "right" }}>
            {filteredItems.length}{search || statusFilter ? ` de ${data.items.length}` : ""} nota(s)
            {" "}— período: {data.label} ({data.from_iso?.slice(0, 10)} → {data.to_iso?.slice(0, 10)})
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, color = "#0f172a", active = false, onClick, testId }) {
  const clickable = !!onClick;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!clickable}
      data-testid={testId}
      data-active={active ? "true" : "false"}
      style={{
        background: active ? "linear-gradient(135deg,#0f172a,#1e293b)" : "white",
        border: active ? `2px solid ${color}` : "1px solid #e2e8f0",
        borderRadius: 10, padding: 8, textAlign: "center",
        cursor: clickable ? "pointer" : "default",
        transition: "transform .12s, box-shadow .12s",
        boxShadow: active ? `0 4px 14px ${color}33` : "none",
        outline: 0,
      }}
      onMouseEnter={(e) => { if (clickable) e.currentTarget.style.transform = "translateY(-1px)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.transform = "translateY(0)"; }}
    >
      <div style={{ fontSize: 10, color: active ? "#cbd5e1" : "#64748b", fontWeight: 700, textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 900, color: active ? "white" : color, marginTop: 2 }}>{value}</div>
    </button>
  );
}
function Th({ children }) {
  return <th style={{ padding: "8px 10px", textAlign: "left", fontSize: 11, fontWeight: 800, textTransform: "uppercase", letterSpacing: 0.5 }}>{children}</th>;
}
function Td({ children }) {
  return <td style={{ padding: "8px 10px", verticalAlign: "top" }}>{children}</td>;
}
