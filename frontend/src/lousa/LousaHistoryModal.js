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

function todayStr() { return new Date().toISOString().slice(0, 10); }
function fmtDuration(min) {
  if (min == null) return "—";
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h > 0 ? `${h}h${String(m).padStart(2, "0")}` : `${m}min`;
}
function shiftDays(dateStr, days) {
  const d = new Date(dateStr + "T00:00:00");
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}
function startOfWeekStr(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  const dow = d.getDay(); // 0=Sun..6=Sat
  const diff = dow === 0 ? -6 : 1 - dow; // Monday-start
  d.setDate(d.getDate() + diff);
  return d.toISOString().slice(0, 10);
}

const inputCss = { padding: "8px 10px", border: "1px solid #cbd5e1", borderRadius: 10, fontSize: 13 };

export default function LousaHistoryModal({ onClose }) {
  // Default: HOJE
  const today = todayStr();
  const [granularity, setGranularity] = useState("day");
  const [date, setDate] = useState(today);
  const [weekStart, setWeekStart] = useState(startOfWeekStr(today));
  const [month, setMonth] = useState(today.slice(0, 7));
  const [year, setYear] = useState(today.slice(0, 4));
  const [from, setFrom] = useState(today);
  const [to, setTo] = useState(today);
  const [grid, setGrid] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [filter, setFilter] = useState(""); // "" | encerrada | cancelada | ...
  const [search, setSearch] = useState("");

  // Calcula date_from / date_to baseado em granularity
  const range = useMemo(() => {
    if (granularity === "day") return { from: date, to: date, label: date };
    if (granularity === "week") {
      const ws = weekStart;
      const we = shiftDays(ws, 6);
      return { from: ws, to: we, label: `${ws} → ${we}` };
    }
    if (granularity === "month") {
      const [y, m] = month.split("-");
      const start = `${y}-${m}-01`;
      const last = new Date(Number(y), Number(m), 0).getDate();
      return { from: start, to: `${y}-${m}-${String(last).padStart(2, "0")}`, label: month };
    }
    if (granularity === "year") {
      return { from: `${year}-01-01`, to: `${year}-12-31`, label: year };
    }
    return { from, to, label: `${from} → ${to}` };
  }, [granularity, date, weekStart, month, year, from, to]);

  useEffect(() => {
    let alive = true;
    setLoading(true); setErr("");
    api.lousaGrid({ date_from: range.from, date_to: range.to })
      .then((d) => { if (alive) setGrid(d); })
      .catch((e) => { if (alive) setErr(e?.response?.data?.detail || e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [range.from, range.to]);

  // Estatísticas e filtro client-side
  const stats = useMemo(() => {
    if (!grid) return null;
    const allTickets = grid.columns.flatMap((c) => c.tickets || []);
    const counts = { total: allTickets.length, finalizada: 0, encerrada: 0, reagendada: 0, cancelada: 0 };
    let durSum = 0, durN = 0;
    for (const t of allTickets) {
      counts[t.status] = (counts[t.status] || 0) + 1;
      if (t.duration_minutes != null && (t.status === "finalizada" || t.status === "encerrada")) {
        durSum += t.duration_minutes; durN += 1;
      }
    }
    return { ...counts, avg: durN > 0 ? durSum / durN : null, all: allTickets };
  }, [grid]);

  const filteredColumns = useMemo(() => {
    if (!grid) return [];
    const q = search.trim().toLowerCase();
    return grid.columns.map((c) => {
      let arr = c.tickets || [];
      if (filter) arr = arr.filter((t) => t.status === filter);
      if (q) {
        arr = arr.filter((t) => {
          const cs = t.client_snapshot || {};
          const hay = [cs.name, cs.address, cs.neighborhood, cs.relato, t.type, t.status, t.admin_notes].filter(Boolean).join(" ").toLowerCase();
          return hay.includes(q);
        });
      }
      return { ...c, _filteredTickets: arr };
    });
  }, [grid, filter, search]);

  return (
    <div onClick={onClose} data-testid="lousa-history-modal" style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,.65)", zIndex: 110,
      display: "grid", placeItems: "center", padding: 12,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 18, padding: 20,
        maxWidth: 1500, width: "100%", maxHeight: "96vh", display: "flex", flexDirection: "column",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
          <h2 style={{ margin: 0, fontSize: 19 }}>📚 Lousa Histórica · {range.label}</h2>
          <Button variant="soft" onClick={onClose} data-testid="history-close-btn">Fechar</Button>
        </div>

        {/* Filtros temporais */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10, alignItems: "center" }}>
          <div style={{ display: "flex", gap: 4, padding: 4, background: "#f1f5f9", borderRadius: 12 }}>
            {[
              { v: "day", l: "📅 Dia" },
              { v: "week", l: "📆 Semana" },
              { v: "month", l: "🗓️ Mês" },
              { v: "year", l: "🏷️ Ano" },
              { v: "range", l: "↔ Período" },
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
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} max={today} style={inputCss} data-testid="history-date-day" />
          )}
          {granularity === "week" && (
            <input type="date" value={weekStart} onChange={(e) => setWeekStart(startOfWeekStr(e.target.value))} max={today} style={inputCss} data-testid="history-date-week" />
          )}
          {granularity === "month" && (
            <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} max={today.slice(0, 7)} style={inputCss} data-testid="history-date-month" />
          )}
          {granularity === "year" && (
            <input type="number" min="2020" max={today.slice(0, 4)} value={year} onChange={(e) => setYear(e.target.value)} style={{ ...inputCss, width: 100 }} data-testid="history-date-year" />
          )}
          {granularity === "range" && (
            <>
              <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} max={today} style={inputCss} data-testid="history-date-from" />
              <span style={{ color: "#94a3b8" }}>→</span>
              <input type="date" value={to} onChange={(e) => setTo(e.target.value)} max={today} style={inputCss} data-testid="history-date-to" />
            </>
          )}

          <div style={{ position: "relative", flex: 1, minWidth: 220 }}>
            <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "#94a3b8", fontSize: 14, pointerEvents: "none" }}>🔍</span>
            <input
              data-testid="history-search"
              type="text"
              placeholder="Buscar cliente, endereço, bairro, notas, tipo..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ ...inputCss, width: "100%", paddingLeft: 32 }}
            />
            {search && (
              <button data-testid="history-search-clear" onClick={() => setSearch("")} style={{ position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)", background: "transparent", border: 0, color: "#94a3b8", cursor: "pointer", fontSize: 16, padding: 4 }}>✕</button>
            )}
          </div>
        </div>

        {/* KPIs clicáveis */}
        {stats && (
          <div data-testid="history-summary" style={{
            background: "linear-gradient(135deg,#f8fafc,#e2e8f0)", borderRadius: 12, padding: 10, marginBottom: 10,
            display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 6,
          }}>
            <Stat label="Total" value={stats.total} active={filter === ""} onClick={() => setFilter("")} testId="history-stat-total" />
            <Stat label="Finalizadas" value={stats.finalizada || 0} color="#10b981" active={filter === "finalizada"} onClick={() => setFilter(filter === "finalizada" ? "" : "finalizada")} testId="history-stat-finalizada" />
            <Stat label="Encerradas" value={stats.encerrada || 0} color="#475569" active={filter === "encerrada"} onClick={() => setFilter(filter === "encerrada" ? "" : "encerrada")} testId="history-stat-encerrada" />
            <Stat label="Reagendadas" value={stats.reagendada || 0} color="#3b82f6" active={filter === "reagendada"} onClick={() => setFilter(filter === "reagendada" ? "" : "reagendada")} testId="history-stat-reagendada" />
            <Stat label="Canceladas" value={stats.cancelada || 0} color="#dc2626" active={filter === "cancelada"} onClick={() => setFilter(filter === "cancelada" ? "" : "cancelada")} testId="history-stat-cancelada" />
            <Stat label="Tempo médio" value={stats.avg != null ? fmtDuration(stats.avg) : "—"} color="#a855f7" testId="history-stat-avg" />
          </div>
        )}

        {/* Lousa em formato kanban (read-only) */}
        <div style={{ flex: 1, overflow: "auto", border: "1px solid #e2e8f0", borderRadius: 12, padding: 8, background: "#fafafa" }}>
          {loading && <div style={{ padding: 30, textAlign: "center", color: "#64748b" }}>Carregando lousa de {range.label}...</div>}
          {err && <div style={{ padding: 30, color: "#dc2626" }}>Erro: {err}</div>}
          {!loading && grid && (
            <div data-testid="history-grid" style={{ display: "flex", gap: 10, alignItems: "flex-start", overflowX: "auto" }}>
              {filteredColumns.map((col) => (
                <HistTechColumn key={col.collaborator.id} column={col} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function HistTechColumn({ column }) {
  const c = column.collaborator;
  const tickets = column._filteredTickets || column.tickets || [];
  return (
    <div data-testid={`history-col-${c.id}`} style={{
      minWidth: 280, maxWidth: 320, background: "white", border: "1px solid #e2e8f0", borderRadius: 12,
      padding: 10, flex: "0 0 auto",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, paddingBottom: 8, borderBottom: "1px solid #e2e8f0", marginBottom: 8 }}>
        <div style={{
          width: 38, height: 38, borderRadius: "50%",
          background: c.avatar ? `url(${c.avatar}) center/cover` : "linear-gradient(135deg,#0ea5e9,#0284c7)",
          display: "grid", placeItems: "center", color: "white", fontWeight: 800, fontSize: 14,
        }}>
          {!c.avatar && (c.name?.[0] || "?").toUpperCase()}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 800, fontSize: 13, color: "#0f172a", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</div>
          <div style={{ fontSize: 11, color: "#64748b" }}>{tickets.length} nota(s)</div>
        </div>
      </div>

      {tickets.length === 0 && <div style={{ color: "#cbd5e1", fontSize: 12, textAlign: "center", padding: 14 }}>Sem notas no período</div>}
      {tickets.map((t) => <HistBubble key={t.id} ticket={t} />)}
    </div>
  );
}

function HistBubble({ ticket }) {
  const cs = ticket.client_snapshot || {};
  const st = STATUS_LABEL[ticket.status] || { label: ticket.status, color: "#64748b", bg: "#f1f5f9" };
  return (
    <div data-testid={`history-bubble-${ticket.id}`} style={{
      background: st.bg, border: `1px solid ${st.color}`,
      borderRadius: 10, padding: 8, marginBottom: 6, position: "relative",
      opacity: 0.95,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", gap: 4 }}>
        <span style={{ fontSize: 9, fontWeight: 800, color: st.color, background: "white", padding: "1px 6px", borderRadius: 6 }}>{st.label}</span>
        {ticket.duration_minutes != null && (
          <span style={{ fontSize: 10, fontWeight: 800, color: "#0f172a", background: "white", padding: "1px 6px", borderRadius: 6 }}>🕐 {fmtDuration(ticket.duration_minutes)}</span>
        )}
      </div>
      <div style={{ fontSize: 13, fontWeight: 800, marginTop: 4, color: "#0f172a" }}>{cs.name}</div>
      <div style={{ fontSize: 11, color: "#64748b" }}>{TYPE_LABELS[ticket.type] || ticket.type}{cs.neighborhood ? ` · ${cs.neighborhood}` : ""}</div>
      {cs.relato && (
        <div style={{ fontSize: 11, color: "#475569", marginTop: 3 }}>{cs.relato.substring(0, 80)}{cs.relato.length > 80 ? "..." : ""}</div>
      )}
      {ticket.admin_notes && (
        <div style={{ fontSize: 10, color: "#dc2626", marginTop: 4, fontStyle: "italic" }}>📝 {ticket.admin_notes.substring(0, 100)}</div>
      )}
      {(() => {
        const cd = ticket.completion_data || {};
        const sigOpen = ticket.signal_at_open?.rx_dbm;
        // Fechamento: prioridade pro que o técnico digitou; senão usa snapshot SmartOLT
        const sigClose = cd.sinal != null ? cd.sinal
          : ticket.signal_at_close?.rx_dbm;
        const hasOpen = sigOpen != null;
        const hasClose = sigClose != null;
        const hasPing = !!cd.ping_summary;
        if (!hasOpen && !hasClose && !hasPing) return null;

        // Comparação por magnitude (dBm é negativo: |-30| > |-25| → -30 é pior).
        let cmpLabel = null;
        let cmpColor = "#475569";
        let cmpBg = "#f1f5f9";
        if (hasOpen && hasClose) {
          const absOpen = Math.abs(sigOpen);
          const absClose = Math.abs(sigClose);
          if (absClose > absOpen) {
            cmpLabel = "⚠ Sinal Degradado";
            cmpColor = "#991b1b"; cmpBg = "#fef2f2";
          } else if (absClose < absOpen) {
            cmpLabel = "✓ Atualização do Sinal com Sucesso";
            cmpColor = "#065f46"; cmpBg = "#ecfdf5";
          } else {
            cmpLabel = "= Sinal estável";
            cmpColor = "#1e40af"; cmpBg = "#eff6ff";
          }
        }

        const sigColor = (v) => v == null ? "#94a3b8"
          : Math.abs(v) <= 25 ? "#065f46"
          : Math.abs(v) <= 28 ? "#92400e" : "#991b1b";

        return (
          <div style={{ marginTop: 4, display: "flex", gap: 4,
                            flexWrap: "wrap", alignItems: "center" }}>
            {hasOpen && (
              <span data-testid={`ticket-sinal-open-${ticket.id}`}
                      title={`Sinal na abertura: ${sigOpen} dBm`}
                      style={{
                        fontSize: 10, padding: "2px 6px",
                        background: "white", color: sigColor(sigOpen),
                        border: `1px solid ${sigColor(sigOpen)}`,
                        borderRadius: 4, fontWeight: 700,
                        fontFamily: "ui-monospace,monospace",
                      }}>
                📥 {sigOpen} dBm
              </span>
            )}
            {hasClose && (
              <span data-testid={`ticket-sinal-close-${ticket.id}`}
                      title={`Sinal no fechamento: ${sigClose} dBm`}
                      style={{
                        fontSize: 10, padding: "2px 6px",
                        background: "white", color: sigColor(sigClose),
                        border: `1px solid ${sigColor(sigClose)}`,
                        borderRadius: 4, fontWeight: 700,
                        fontFamily: "ui-monospace,monospace",
                      }}>
                📤 {sigClose} dBm
              </span>
            )}
            {cmpLabel && (
              <span data-testid={`ticket-sinal-cmp-${ticket.id}`}
                      style={{
                        fontSize: 9, padding: "2px 6px",
                        background: cmpBg, color: cmpColor,
                        border: `1px solid ${cmpColor}`,
                        borderRadius: 4, fontWeight: 800,
                        textTransform: "uppercase", letterSpacing: 0.3,
                      }}>
                {cmpLabel}
              </span>
            )}
            {hasPing && (
              <span data-testid={`ticket-ping-summary-${ticket.id}`}
                      style={{
                        fontSize: 10, padding: "2px 6px", flex: 1,
                        background: cd.ping_summary.includes("✓") ? "#ecfdf5"
                          : cd.ping_summary.includes("✗") ? "#fef2f2"
                          : "#f1f5f9",
                        color: cd.ping_summary.includes("✓") ? "#065f46"
                          : cd.ping_summary.includes("✗") ? "#991b1b"
                          : "#475569",
                        border: "1px solid", borderColor: "currentColor",
                        borderRadius: 4, fontWeight: 600,
                        whiteSpace: "nowrap", overflow: "hidden",
                        textOverflow: "ellipsis", minWidth: 0,
                      }}
                      title={cd.ping_summary}>
                🛰 {cd.ping_summary.split("\n")[0].substring(0, 50)}
              </span>
            )}
          </div>
        );
      })()}
      {ticket.scheduled_time && (
        <div style={{ fontSize: 10, color: "#3b82f6", marginTop: 3 }}>📅 {new Date(ticket.scheduled_time).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}</div>
      )}
    </div>
  );
}

function Stat({ label, value, color = "#0f172a", active = false, onClick, testId }) {
  const clickable = !!onClick;
  return (
    <button
      type="button" onClick={onClick} disabled={!clickable}
      data-testid={testId} data-active={active ? "true" : "false"}
      style={{
        background: active ? "linear-gradient(135deg,#0f172a,#1e293b)" : "white",
        border: active ? `2px solid ${color}` : "1px solid #e2e8f0",
        borderRadius: 10, padding: 8, textAlign: "center",
        cursor: clickable ? "pointer" : "default",
        boxShadow: active ? `0 4px 14px ${color}33` : "none",
        outline: 0,
      }}
    >
      <div style={{ fontSize: 10, color: active ? "#cbd5e1" : "#64748b", fontWeight: 700, textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 900, color: active ? "white" : color, marginTop: 2 }}>{value}</div>
    </button>
  );
}
