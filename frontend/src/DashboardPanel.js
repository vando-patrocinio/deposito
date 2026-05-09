import React, { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/api";
import { Card, fmtMin } from "@/ui";

function brl(v) { return `R$ ${(v || 0).toFixed(2).replace(".", ",")}`; }
function hours(min) { return ((min || 0) / 60).toFixed(1); }

const NOW = new Date();
const CUR_Y = NOW.getFullYear();
const CUR_M = NOW.getMonth() + 1;
const MONTH_LABEL = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

export default function DashboardPanel() {
  const [trend, setTrend] = useState(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  // view modes
  // 'trend': últimos N meses (3/6/12)
  // 'month': mês específico
  // 'ytd':   acumulado no ano até o mês selecionado
  const [view, setView] = useState("trend");
  const [months, setMonths] = useState(6);
  const [pickY, setPickY] = useState(CUR_Y);
  const [pickM, setPickM] = useState(CUR_M);

  useEffect(() => {
    let alive = true;
    setTrend(null); setErr(""); setLoading(true);
    let p;
    if (view === "trend") {
      p = api.overtimeTrend(months);
    } else if (view === "month") {
      p = api.overtimeRange(pickY, pickM, pickY, pickM, "monthly");
    } else {
      p = api.overtimeRange(pickY, 1, pickY, pickM, "accumulated");
    }
    p.then((d) => { if (alive) setTrend(d); })
     .catch((e) => { if (alive) setErr(e?.response?.data?.detail || e.message); })
     .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [view, months, pickY, pickM]);

  const chartData = useMemo(
    () => (trend?.series || []).map((s) => ({
      label: s.label,
      "HE (h)": Number(hours(s.total_overtime_min)),
      "Realizado (R$)": s.total_paid_brl,
      "Projetado (R$)": s.projected_paid_brl,
      isCurrent: s.is_current,
    })),
    [trend],
  );

  const totals = useMemo(() => {
    if (!trend) return null;
    return trend.series.reduce((acc, s) => ({
      ot: acc.ot + s.total_overtime_min,
      paid: acc.paid + s.total_paid_brl,
      projected: acc.projected + s.projected_paid_brl,
    }), { ot: 0, paid: 0, projected: 0 });
  }, [trend]);

  const cur = trend?.series?.find?.((s) => s.is_current);

  const headerTitle = view === "trend"
    ? `Últimos ${months} meses (consolidado)`
    : view === "month"
      ? `Mês de ${MONTH_LABEL[pickM - 1]}/${pickY}`
      : `Acumulado de ${pickY} (jan → ${MONTH_LABEL[pickM - 1]})`;

  const chartTitle = view === "month"
    ? `HE — ${MONTH_LABEL[pickM - 1]}/${pickY}`
    : `HE acumulada — ${headerTitle}`;

  const yearOptions = useMemo(() => {
    const arr = [];
    for (let y = CUR_Y - 4; y <= CUR_Y + 1; y++) arr.push(y);
    return arr;
  }, []);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, flexWrap: "wrap", gap: 12 }}>
        <div>
          <h2 style={{ margin: 0 }}>Painel executivo do Gestor</h2>
          <p style={{ color: "#64748b", margin: "4px 0 0", fontSize: 13 }}>
            {headerTitle} · KPIs e gráficos atualizados em tempo real.
          </p>
        </div>
      </div>

      <ServiceStatsSection />

      {/* Seletor de modo */}
      <Card style={{ marginBottom: 14 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "center" }}>
          <div style={{ display: "flex", gap: 6 }} data-testid="view-mode-selector">
            {[
              { v: "trend", label: "Tendência" },
              { v: "month", label: "Mês a mês" },
              { v: "ytd", label: "Acumulado YTD" },
            ].map((opt) => (
              <button
                key={opt.v}
                data-testid={`view-${opt.v}`}
                onClick={() => setView(opt.v)}
                style={{
                  padding: "8px 14px", borderRadius: 12, fontWeight: 800, fontSize: 13,
                  cursor: "pointer", border: "1px solid #e2e8f0",
                  background: view === opt.v ? "#0f172a" : "white",
                  color: view === opt.v ? "white" : "#0f172a",
                }}
              >{opt.label}</button>
            ))}
          </div>

          {view === "trend" && (
            <div style={{ display: "flex", gap: 6 }}>
              {[3, 6, 12].map((n) => (
                <button
                  key={n}
                  data-testid={`trend-${n}m`}
                  onClick={() => setMonths(n)}
                  style={{
                    padding: "8px 14px", borderRadius: 12, fontWeight: 800, fontSize: 13,
                    cursor: "pointer", border: "1px solid #e2e8f0",
                    background: months === n ? "#0ea5e9" : "white",
                    color: months === n ? "white" : "#0f172a",
                  }}
                >
                  {n}m
                </button>
              ))}
            </div>
          )}

          {(view === "month" || view === "ytd") && (
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <label style={{ fontSize: 13, color: "#64748b" }}>Mês:</label>
              <select data-testid="month-picker" value={pickM} onChange={(e) => setPickM(Number(e.target.value))}
                      style={{ padding: "6px 10px", borderRadius: 8, border: "1px solid #e2e8f0" }}>
                {MONTH_LABEL.map((nm, i) => (<option key={i} value={i + 1}>{nm}</option>))}
              </select>
              <label style={{ fontSize: 13, color: "#64748b" }}>Ano:</label>
              <select data-testid="year-picker" value={pickY} onChange={(e) => setPickY(Number(e.target.value))}
                      style={{ padding: "6px 10px", borderRadius: 8, border: "1px solid #e2e8f0" }}>
                {yearOptions.map((y) => (<option key={y} value={y}>{y}</option>))}
              </select>
              <span style={{ fontSize: 12, color: "#94a3b8" }}>
                {view === "month" ? "(somente o mês selecionado)" : "(consolida de jan até o mês escolhido)"}
              </span>
            </div>
          )}

          {loading && <span style={{ color: "#64748b", fontSize: 12 }}>carregando…</span>}
        </div>
      </Card>

      {err && <Card><div style={{ color: "#be123c" }}>Erro: {err}</div></Card>}

      {(trend?.alerts || []).length > 0 && (
        <div style={{ marginBottom: 16, display: "flex", flexDirection: "column", gap: 10 }} data-testid="dashboard-alerts">
          {trend.alerts.map((a, i) => (
            <div key={a.id || i} data-testid={`alert-${a.id || i}`}
                 style={{
                   background: a.level === "danger" ? "#fee2e2" : "#fef3c7",
                   border: `1px solid ${a.level === "danger" ? "#fecaca" : "#fde68a"}`,
                   color: a.level === "danger" ? "#991b1b" : "#92400e",
                   padding: "12px 14px", borderRadius: 14, display: "flex", gap: 12, alignItems: "flex-start",
                 }}>
              <div style={{ width: 36, height: 36, borderRadius: "50%", background: a.level === "danger" ? "#dc2626" : "#f59e0b",
                            color: "white", display: "grid", placeItems: "center", fontWeight: 900, fontSize: 18, flexShrink: 0 }}>!</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <strong style={{ fontSize: 14 }}>{a.title}</strong>
                <div style={{ fontSize: 13, marginTop: 2 }}>{a.message}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* KPIs */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 14, marginBottom: 16 }}>
        <Card title={`HE total · ${headerTitle}`} style={{ marginBottom: 0 }} data-testid="kpi-ot-total">
          <div style={{ fontSize: 28, fontWeight: 900 }}>{fmtMin(totals?.ot || 0)}</div>
          <div style={{ color: "#64748b", fontSize: 12, marginTop: 4 }}>
            {view === "trend" ? `Acumulado dos últimos ${months} meses` :
             view === "month" ? `Total do mês ${MONTH_LABEL[pickM - 1]}/${pickY}` :
             `Acumulado do ano até ${MONTH_LABEL[pickM - 1]}/${pickY}`}
          </div>
        </Card>
        <Card title="Custo realizado" style={{ marginBottom: 0 }} data-testid="kpi-realizado">
          <div style={{ fontSize: 28, fontWeight: 900, color: "#166534" }}>{brl(totals?.paid || 0)}</div>
          <div style={{ color: "#64748b", fontSize: 12, marginTop: 4 }}>Apenas colaboradores em política <strong>HE paga</strong></div>
        </Card>
        <Card title="Custo projetado" style={{ marginBottom: 0 }} data-testid="kpi-projetado">
          <div style={{ fontSize: 28, fontWeight: 900, color: "#7c2d12" }}>{brl(totals?.projected || 0)}</div>
          <div style={{ color: "#64748b", fontSize: 12, marginTop: 4 }}>
            Mês corrente extrapolado (linear até o último dia)
          </div>
        </Card>
        <Card title="Mês atual" style={{ marginBottom: 0 }} data-testid="kpi-cur">
          <div style={{ fontSize: 28, fontWeight: 900 }}>{cur ? fmtMin(cur.total_overtime_min) : "—"}</div>
          <div style={{ color: "#64748b", fontSize: 12, marginTop: 4 }}>
            HE acumulada {cur ? cur.label : ""} · projeção: {brl(cur?.projected_paid_brl || 0)}
          </div>
        </Card>
      </div>

      {/* Chart 1 */}
      <Card title={chartTitle}>
        <div style={{ width: "100%", height: 280, minWidth: 200 }} data-testid="chart-ot-monthly">
          <ResponsiveContainer width="100%" height="100%" minWidth={200} minHeight={250}>
            <BarChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="label" stroke="#64748b" fontSize={12} />
              <YAxis stroke="#64748b" fontSize={12} />
              <Tooltip formatter={(v) => `${v}h`} />
              <Bar dataKey="HE (h)" radius={[10, 10, 0, 0]}>
                {chartData.map((d, i) => (
                  <Cell key={i} fill={d.isCurrent ? "#f59e0b" : "#0ea5e9"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <p style={{ color: "#94a3b8", fontSize: 11, marginTop: 6, marginBottom: 0 }}>Barra laranja = mês corrente.</p>
      </Card>

      {/* Chart 2 */}
      <Card title="Custo de HE — Realizado vs Projetado (R$)">
        <div style={{ width: "100%", height: 280, minWidth: 200 }} data-testid="chart-paid-vs-projected">
          <ResponsiveContainer width="100%" height="100%" minWidth={200} minHeight={250}>
            <LineChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="label" stroke="#64748b" fontSize={12} />
              <YAxis stroke="#64748b" fontSize={12} />
              <Tooltip formatter={(v) => brl(v)} />
              <Legend />
              <Line type="monotone" dataKey="Realizado (R$)" stroke="#16a34a" strokeWidth={3} dot={{ r: 4 }} />
              <Line type="monotone" dataKey="Projetado (R$)" stroke="#dc2626" strokeWidth={3} strokeDasharray="6 6" dot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {/* Top débito */}
      <Card title={view === "trend" ? "Top 5 — Colaboradores em débito (mês atual)" : `Top 5 — Colaboradores em débito (${MONTH_LABEL[pickM - 1]}/${pickY})`}>
        {(trend?.top_debit || []).length === 0 ? (
          <p style={{ color: "#64748b", margin: 0 }}>Ninguém com saldo negativo este mês 🎉</p>
        ) : (
          <div data-testid="top-debit-list">
            {trend.top_debit.map((r, i) => (
              <div key={r.collaborator_id} data-testid={`debit-${i}`}
                   style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 0", borderBottom: i < trend.top_debit.length - 1 ? "1px solid #f1f5f9" : "none" }}>
                <div style={{ width: 32, height: 32, borderRadius: "50%", background: i === 0 ? "#fee2e2" : "#fef3c7", color: i === 0 ? "#991b1b" : "#92400e", display: "grid", placeItems: "center", fontWeight: 900 }}>
                  {i + 1}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <strong>{r.name}</strong>
                  <div style={{ color: "#94a3b8", fontSize: 12 }}>
                    {r.policy_mode === "pago" ? "HE paga" : "Banco de horas"} · HE: {fmtMin(r.total_overtime_min)}
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div style={{ color: "#dc2626", fontWeight: 900, fontSize: 16 }}>{fmtMin(r.balance_min)}</div>
                  <div style={{ color: "#94a3b8", fontSize: 11 }}>saldo</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <DwellHeatmap year={pickY} month={pickM} />
    </div>
  );
}

function DwellHeatmap({ year, month }) {
  const [data, setData] = React.useState(null);
  const [err, setErr] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [hY, setHY] = React.useState(year || CUR_Y);
  const [hM, setHM] = React.useState(month || CUR_M);
  const [drill, setDrill] = React.useState(null); // {day, loading, data}

  React.useEffect(() => { setHY(year); setHM(month); }, [year, month]);
  React.useEffect(() => {
    let alive = true;
    setLoading(true); setErr("");
    api.dwellHeatmap(hY, hM)
      .then((d) => { if (alive) setData(d); })
      .catch((e) => { if (alive) setErr(e?.response?.data?.detail || e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [hY, hM]);

  async function openDay(day) {
    setDrill({ day, loading: true, data: null });
    try {
      const d = await api.dwellHeatmapDay(hY, hM, day);
      setDrill({ day, loading: false, data: d });
    } catch (e) {
      setDrill({ day, loading: false, error: e?.response?.data?.detail || e.message });
    }
  }

  const max = Math.max(1, ...((data?.by_day || []).map((d) => d.minutes)));
  function dayColor(min) {
    if (!min) return "#f1f5f9";
    const t = Math.min(1, min / max);
    if (t < 0.25) return "#dbeafe";
    if (t < 0.5) return "#93c5fd";
    if (t < 0.75) return "#fbbf24";
    return "#dc2626";
  }

  return (
    <Card
      title={`Heatmap de horas paradas por praça — ${MONTH_LABEL[hM - 1]}/${hY}`}
      action={
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select data-testid="heatmap-month" value={hM} onChange={(e) => setHM(Number(e.target.value))}
                  style={{ padding: "4px 8px", borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }}>
            {MONTH_LABEL.map((nm, i) => (<option key={i} value={i + 1}>{nm}</option>))}
          </select>
          <select data-testid="heatmap-year" value={hY} onChange={(e) => setHY(Number(e.target.value))}
                  style={{ padding: "4px 8px", borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }}>
            {Array.from({ length: 6 }, (_, i) => CUR_Y - 4 + i).map((y) => (<option key={y} value={y}>{y}</option>))}
          </select>
          {loading && <span style={{ color: "#64748b", fontSize: 12 }}>carregando…</span>}
        </div>
      }
    >
      {err && <div style={{ color: "#be123c", fontSize: 13 }}>Erro: {err}</div>}

      <div style={{ marginBottom: 14 }} data-testid="heatmap-by-day">
        <div style={{ fontSize: 12, color: "#64748b", marginBottom: 6 }}>
          Total parado no mês: <strong>{fmtMin(data?.total_minutes || 0)}</strong> · barras = horas paradas/dia
        </div>
        <div style={{ display: "grid", gridTemplateColumns: `repeat(${data?.last_day || 31}, minmax(20px, 1fr))`, gap: 3 }}>
          {(data?.by_day || []).map((d) => (
            <button
              key={d.day}
              data-testid={`heatmap-day-${d.day}`}
              onClick={() => openDay(d.day)}
              title={`Dia ${d.day}: ${fmtMin(d.minutes)} — clique para detalhes`}
              style={{
                background: dayColor(d.minutes),
                borderRadius: 6,
                height: 36,
                position: "relative",
                border: "1px solid #e2e8f0",
                cursor: "pointer",
                padding: 0,
              }}
            >
              <span style={{ position: "absolute", bottom: 2, left: 0, right: 0, textAlign: "center", fontSize: 9, color: d.minutes > max * 0.5 ? "white" : "#475569", fontWeight: 700 }}>
                {d.day}
              </span>
            </button>
          ))}
        </div>
      </div>

      {(data?.rows || []).length === 0 ? (
        <div style={{ color: "#64748b", fontSize: 13 }}>Sem permanências registradas no período.</div>
      ) : (
        <div data-testid="heatmap-rows" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {data.rows.map((r, idx) => {
            const total = data.total_minutes || 1;
            const pct = (r.total_minutes / total) * 100;
            return (
              <div key={r.praca_id} data-testid={`heatmap-row-${idx}`} style={{ background: "white", border: "1px solid #e2e8f0", borderRadius: 12, padding: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <strong style={{ fontSize: 14 }}>{r.praca_name}</strong>
                  <span style={{ fontSize: 13, color: "#0f172a", fontWeight: 800 }}>{fmtMin(r.total_minutes)} · {r.stays} permanência(s)</span>
                </div>
                <div style={{ background: "#f1f5f9", borderRadius: 8, overflow: "hidden", height: 10 }}>
                  <div style={{ width: `${Math.min(100, pct)}%`, height: "100%", background: "linear-gradient(90deg, #0ea5e9, #f59e0b, #dc2626)" }} />
                </div>
                <div style={{ marginTop: 6, fontSize: 12, color: "#64748b" }}>
                  {(r.by_collab || []).slice(0, 4).map((cb, i) => (
                    <span key={cb.collaborator_id} style={{ marginRight: 10 }}>
                      <strong>{cb.name}</strong>: {fmtMin(cb.minutes)}{i < Math.min(3, r.by_collab.length - 1) ? " · " : ""}
                    </span>
                  ))}
                  {(r.by_collab || []).length > 4 && <span>+ {r.by_collab.length - 4} colaborador(es)</span>}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {drill && (
        <DrillModal drill={drill} year={hY} month={hM} onClose={() => setDrill(null)} />
      )}
    </Card>
  );
}

function DrillModal({ drill, year, month, onClose }) {
  const monthLabel = MONTH_LABEL[month - 1];
  return (
    <div
      data-testid="drill-modal"
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(15,23,42,0.6)",
        display: "grid", placeItems: "center", zIndex: 1000, padding: 16,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "white", borderRadius: 18, maxWidth: 760, width: "100%",
          maxHeight: "85vh", overflow: "auto", padding: 20,
          boxShadow: "0 30px 80px rgba(0,0,0,0.4)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>
            Permanências do dia {String(drill.day).padStart(2, "0")}/{String(month).padStart(2, "0")}/{year}
          </h3>
          <button onClick={onClose} data-testid="drill-close"
                  style={{ border: 0, background: "#f1f5f9", padding: "6px 12px", borderRadius: 10, cursor: "pointer", fontWeight: 700 }}>
            Fechar
          </button>
        </div>

        {drill.loading && <p style={{ color: "#64748b" }}>Carregando…</p>}
        {drill.error && <p style={{ color: "#be123c" }}>Erro: {drill.error}</p>}

        {drill.data && (
          <>
            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 12, padding: 10, marginBottom: 12, fontSize: 13, color: "#475569" }}>
              <strong>{drill.data.stays.length}</strong> permanência(s) registrada(s) ·
              total parado: <strong>{fmtMin(drill.data.total_minutes)}</strong>
            </div>
            {drill.data.stays.length === 0 ? (
              <p style={{ color: "#64748b" }}>Nenhuma permanência {">= 30 min"} no dia {drill.day} de {monthLabel}.</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {drill.data.stays.map((s, i) => {
                  const startTime = new Date(s.start).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
                  const endTime = new Date(s.end).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
                  const mapsUrl = `https://www.openstreetmap.org/?mlat=${s.center_lat}&mlon=${s.center_lng}#map=18/${s.center_lat}/${s.center_lng}`;
                  return (
                    <div key={i} data-testid={`drill-stay-${i}`}
                         style={{ background: "white", border: "1px solid #e2e8f0", borderRadius: 12, padding: 12 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                        <strong style={{ fontSize: 14 }}>{s.collaborator_name}</strong>
                        <span style={{ fontSize: 13, fontWeight: 800, color: "#dc2626" }}>{fmtMin(s.duration_min)}</span>
                      </div>
                      <div style={{ fontSize: 12, color: "#64748b" }}>
                        📍 <strong>{s.praca_name}</strong> · {startTime} → {endTime} · {s.points} ping(s)
                      </div>
                      <div style={{ marginTop: 6, fontSize: 11, color: "#94a3b8" }}>
                        Centro: {s.center_lat.toFixed(5)}, {s.center_lng.toFixed(5)} ·{" "}
                        <a href={mapsUrl} target="_blank" rel="noopener noreferrer" data-testid={`drill-map-link-${i}`}
                           style={{ color: "#0ea5e9", fontWeight: 700 }}>
                          Abrir no mapa ↗
                        </a>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}


const TYPE_COLORS_STATS = {
  reparo: "#3b82f6", instalacao: "#10b981", retirada: "#f59e0b",
  prioridade: "#dc2626", preventiva: "#a855f7", venda: "#06b6d4",
};
const TYPE_LABELS_STATS = {
  reparo: "🔧 Reparo", instalacao: "📡 Instalação", retirada: "📦 Retirada",
  prioridade: "🚨 Prioridade", preventiva: "🛡️ Preventiva", venda: "💼 Venda",
};

function ServiceStatsSection() {
  const [stats, setStats] = React.useState(null);
  const [days, setDays] = React.useState(30);
  const [loading, setLoading] = React.useState(false);
  const [err, setErr] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    setLoading(true); setErr("");
    api.lousaStats(days)
      .then((d) => { if (alive) setStats(d); })
      .catch((e) => { if (alive) setErr(e?.response?.data?.detail || e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [days]);

  if (loading) return <Card style={{ marginBottom: 14 }} data-testid="service-stats-loading">Carregando estatísticas...</Card>;
  if (err) return <Card style={{ marginBottom: 14, color: "#dc2626" }}>Erro stats: {err}</Card>;
  if (!stats) return null;

  const ranking = stats.ranking_by_type || [];
  const maxCount = Math.max(1, ...ranking.map((r) => r.count));

  return (
    <Card style={{ marginBottom: 14 }} data-testid="service-stats-section">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
        <h3 style={{ margin: 0, fontSize: 16 }}>📊 Estatísticas de serviços</h3>
        <div style={{ display: "flex", gap: 6 }}>
          {[7, 30, 90].map((n) => (
            <button
              key={n}
              data-testid={`stats-days-${n}`}
              onClick={() => setDays(n)}
              style={{
                padding: "6px 12px", borderRadius: 10, fontSize: 12, fontWeight: 700,
                border: "1px solid #e2e8f0", cursor: "pointer",
                background: days === n ? "#0f172a" : "white",
                color: days === n ? "white" : "#0f172a",
              }}
            >{n}d</button>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10, marginBottom: 14 }}>
        <KpiCard label="Total" value={stats.total} color="#0f172a" testId="kpi-total" />
        <KpiCard label="Executados" value={stats.executed_count} color="#3b82f6" testId="kpi-executed" />
        <KpiCard label="Finalizados" value={stats.finalized_count} color="#10b981" testId="kpi-finalized" />
        <KpiCard label="Cancelados" value={stats.by_status.cancelada || 0} color="#dc2626" testId="kpi-canceled" />
        <KpiCard label="Tempo médio" value={stats.avg_duration_minutes != null ? `${stats.avg_duration_minutes.toFixed(0)}min` : "—"} color="#a855f7" testId="kpi-avg" />
      </div>

      <div style={{ marginBottom: 12 }}>
        <h4 style={{ fontSize: 13, margin: "0 0 8px", color: "#475569" }}>🏆 Ranking de tipos mais executados</h4>
        {ranking.length === 0 && <div style={{ color: "#94a3b8", fontSize: 12 }}>Sem dados no período.</div>}
        {ranking.map((r, idx) => (
          <div key={r.type} data-testid={`ranking-row-${r.type}`} style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
            <span style={{ width: 22, fontWeight: 800, color: idx === 0 ? "#f59e0b" : "#94a3b8", fontSize: 13 }}>
              {idx + 1}º
            </span>
            <span style={{ width: 130, fontSize: 12, fontWeight: 700, color: "#0f172a" }}>
              {TYPE_LABELS_STATS[r.type] || r.type}
            </span>
            <div style={{ flex: 1, height: 18, background: "#f1f5f9", borderRadius: 8, overflow: "hidden", position: "relative" }}>
              <div style={{
                height: "100%", width: `${(r.count / maxCount) * 100}%`,
                background: TYPE_COLORS_STATS[r.type] || "#64748b", borderRadius: 8,
                transition: "width .3s",
              }} />
            </div>
            <span style={{ minWidth: 60, fontSize: 12, fontWeight: 800, color: "#0f172a", textAlign: "right" }}>
              {r.count} {r.avg_duration_minutes != null ? `· ${Math.round(r.avg_duration_minutes)}min` : ""}
            </span>
          </div>
        ))}
      </div>

      {stats.timeline?.length > 0 && (
        <div>
          <h4 style={{ fontSize: 13, margin: "12px 0 8px", color: "#475569" }}>📈 Volume diário</h4>
          <div style={{ height: 110, minHeight: 110 }}>
            <ResponsiveContainer width="100%" height="100%" minHeight={110}>
              <BarChart data={stats.timeline.slice(-14)}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="day" tickFormatter={(d) => d.slice(5)} fontSize={10} />
                <YAxis fontSize={10} />
                <Tooltip />
                <Bar dataKey="created" fill="#3b82f6" name="Criados" />
                <Bar dataKey="finalized" fill="#10b981" name="Finalizados" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </Card>
  );
}

function KpiCard({ label, value, color, testId }) {
  return (
    <div data-testid={testId} style={{
      background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 12,
      padding: 12, textAlign: "center",
    }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: "#64748b", textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 900, color, marginTop: 4 }}>{value}</div>
    </div>
  );
}
