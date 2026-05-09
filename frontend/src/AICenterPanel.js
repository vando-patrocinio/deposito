import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Card, Button, Metric } from "@/ui";
import { api } from "@/api";
import { Circle, MapContainer, Marker, Popup, TileLayer } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import AIPreventivePanel from "@/AIPreventivePanel";

// Fix marker icons (compat with react-leaflet)
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
});

const SUB_TABS = [
  { id: "overview", label: "📊 Overview" },
  { id: "preventive", label: "🤖 Preventivas" },
  { id: "tech_spending", label: "💰 Gastos/Técnico" },
  { id: "repair_map", label: "🗺️ Mapa de defeitos" },
  { id: "defective", label: "🔧 Equipamentos" },
  { id: "common_issues", label: "📞 Reclamações" },
  { id: "recurring", label: "🔁 Reincidência" },
  { id: "insights", label: "💡 Insights LLM" },
];

const css = {
  th: { padding: 10, textAlign: "left", background: "#f8fafc", fontSize: 11, fontWeight: 800, color: "#475569", textTransform: "uppercase", letterSpacing: 0.4 },
  td: { padding: 10, fontSize: 13, borderBottom: "1px solid #f1f5f9", verticalAlign: "top" },
  pill: (bg, color) => ({ background: bg, color, padding: "2px 8px", borderRadius: 999, fontSize: 11, fontWeight: 700, display: "inline-block" }),
};

function fmtBRL(v) { return (Number(v) || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }); }

// ============================================================
// Section: Overview
// ============================================================
function OverviewSection({ days, setDays }) {
  const [d, setD] = useState(null);
  useEffect(() => { let a = true; api.aiDashOverview(days).then((r) => a && setD(r)); return () => { a = false; }; }, [days]);
  if (!d) return <Card>Carregando…</Card>;
  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))", gap: 14, marginBottom: 18 }}>
        <Metric label="Tickets (período)" value={d.tickets.total} data-testid="kpi-tickets-total" />
        <Metric label="Finalizadas" value={d.tickets.finalizadas} />
        <Metric label="Taxa de fechamento" value={`${d.tickets.fechamento_pct}%`} />
        <Metric label="Bolhas abertas" value={d.tickets.abertas} />
        <Metric label="ONUs críticas" value={`${d.smartolt.onus_critical} (${d.smartolt.critical_pct}%)`} />
        <Metric label="Preventivas pendentes" value={d.ai_preventive.pending} />
        <Metric label="Técnicos ativos" value={d.technicians.ativos} />
        <Metric label="Erros de estoque" value={d.alerts.stok_errors} />
      </div>
      <Card title="Resumo do período">
        <div style={{ fontSize: 13, lineHeight: 1.7 }}>
          <strong>{d.tickets.total}</strong> bolhas criadas nos últimos {d.period_days} dias.
          Taxa de fechamento: <strong>{d.tickets.fechamento_pct}%</strong>.
          Da base SmartOLT (<strong>{d.smartolt.onus_total} ONUs</strong>),
          {' '}<strong>{d.smartolt.critical_pct}%</strong> estão em estado crítico.
          IA Preventiva: <strong>{d.ai_preventive.accepted_period}</strong> aceitas / <strong>{d.ai_preventive.pending}</strong> pendentes.
          Notificações não lidas: <strong>{d.alerts.notif_unread}</strong>.
        </div>
      </Card>
    </>
  );
}

// ============================================================
// Section: Tech Spending
// ============================================================
function TechSpendingSection({ days }) {
  const [d, setD] = useState(null);
  useEffect(() => { let a = true; api.aiDashTechSpending(days).then((r) => a && setD(r)); return () => { a = false; }; }, [days]);
  if (!d) return <Card>Carregando…</Card>;
  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))", gap: 14, marginBottom: 14 }}>
        <Metric label="Custo total (período)" value={fmtBRL(d.totals.custo_brl)} data-testid="kpi-tech-cost" />
        <Metric label="Notas com baixa" value={d.totals.notas} />
        <Metric label="Custo médio/nota" value={fmtBRL(d.totals.custo_medio_por_nota)} />
      </div>
      <Card title="💰 Gastos por técnico (insumos baixados)">
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>
            <th style={css.th}>Técnico</th>
            <th style={css.th}>Notas</th>
            <th style={css.th}>Insumos</th>
            <th style={css.th}>Custo total</th>
            <th style={css.th}>Custo médio/nota</th>
          </tr></thead>
          <tbody>
            {d.rows.length === 0
              ? <tr><td colSpan={5} style={{ padding: 24, color: "#64748b", textAlign: "center" }}>Nenhuma baixa de estoque registrada no período.</td></tr>
              : d.rows.map((r) => (
                <tr key={r.tech_name}>
                  <td style={css.td}><strong>{r.tech_name}</strong></td>
                  <td style={css.td}>{r.notas_baixadas_estoque} (lousa: {r.notas_finalizadas_lousa})</td>
                  <td style={css.td}>
                    {Object.entries(r.insumos_totais).map(([k, v]) => (
                      <span key={k} style={{ marginRight: 6, fontSize: 11, color: "#475569" }}>{k}:<strong>{v}</strong></span>
                    ))}
                  </td>
                  <td style={{ ...css.td, fontWeight: 800, color: "#0f172a" }}>{fmtBRL(r.custo_estimado_brl)}</td>
                  <td style={css.td}>{fmtBRL(r.custo_medio_por_nota)}</td>
                </tr>
              ))}
          </tbody>
        </table>
        <div style={{ fontSize: 11, color: "#64748b", marginTop: 8 }}>
          Tabela de preços: {Object.entries(d.price_table_brl).map(([k, v]) => `${k}=${fmtBRL(v)}`).join(" · ")}
        </div>
      </Card>
    </>
  );
}

// ============================================================
// Section: Repair Map
// ============================================================
function RepairMapSection({ days }) {
  const [d, setD] = useState(null);
  const [filter, setFilter] = useState("all");
  useEffect(() => { let a = true; api.aiDashRepairMap(days).then((r) => a && setD(r)); return () => { a = false; }; }, [days]);
  const points = useMemo(() => {
    if (!d) return [];
    return filter === "all" ? d.points : d.points.filter((p) => p.type === filter);
  }, [d, filter]);
  const center = useMemo(() => {
    if (points.length === 0) return [-22.9, -43.2];
    const lat = points.reduce((s, p) => s + p.latitude, 0) / points.length;
    const lng = points.reduce((s, p) => s + p.longitude, 0) / points.length;
    return [lat, lng];
  }, [points]);
  if (!d) return <Card>Carregando mapa…</Card>;
  const COLORS = { reparo: "#dc2626", instalacao: "#16a34a", retirada: "#a16207", preventiva: "#7c3aed", troca_endereco: "#2563eb" };
  return (
    <>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ fontSize: 13 }}>📍 {points.length} pontos</strong>
        <select value={filter} onChange={(e) => setFilter(e.target.value)}
          style={{ padding: "6px 10px", borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 12 }} data-testid="map-filter">
          <option value="all">Todos os tipos ({d.count})</option>
          {Object.entries(d.by_type).map(([k, v]) => <option key={k} value={k}>{k} ({v})</option>)}
        </select>
      </div>
      <Card data-testid="repair-map-card">
        <div style={{ height: 540, borderRadius: 12, overflow: "hidden" }}>
          <MapContainer center={center} zoom={11} style={{ height: "100%", width: "100%" }} scrollWheelZoom>
            <TileLayer attribution='&copy; OpenStreetMap' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            {points.map((p) => (
              <Circle key={p.id} center={[p.latitude, p.longitude]} radius={120}
                pathOptions={{ color: COLORS[p.type] || "#64748b", fillColor: COLORS[p.type] || "#94a3b8", fillOpacity: 0.5, weight: 2 }}>
                <Popup>
                  <div style={{ fontSize: 12, minWidth: 200 }}>
                    <strong>{p.client_name}</strong><br />
                    <span style={{ color: "#64748b" }}>{p.address}</span><br />
                    <span style={{ ...css.pill("#f1f5f9", "#475569") }}>{p.type}</span>
                    {p.priority && <span style={{ ...css.pill("#fef3c7", "#92400e"), marginLeft: 4 }}>{p.priority}</span>}
                    {p.rx_dbm != null && (
                      <div style={{ marginTop: 4 }}>📶 {p.rx_dbm.toFixed(1)} dBm</div>
                    )}
                    <div style={{ marginTop: 4, fontSize: 11 }}>{p.relato || ""}</div>
                  </div>
                </Popup>
              </Circle>
            ))}
          </MapContainer>
        </div>
      </Card>
    </>
  );
}

// ============================================================
// Section: Defective Equipment
// ============================================================
function DefectiveSection({ days }) {
  const [d, setD] = useState(null);
  useEffect(() => { let a = true; api.aiDashDefective(days).then((r) => a && setD(r)); return () => { a = false; }; }, [days]);
  if (!d) return <Card>Carregando…</Card>;
  return (
    <>
      <Card title={`🔧 Modelos com mais ocorrências (últimos ${days}d)`}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr><th style={css.th}>Modelo</th><th style={css.th}>Ocorrências</th><th style={css.th}>Equipamentos distintos</th></tr></thead>
          <tbody>
            {d.models.map((m) => (
              <tr key={m.model}>
                <td style={css.td}><strong>{m.model}</strong></td>
                <td style={css.td}>{m.ocorrencias}</td>
                <td style={css.td}>{m.equipamentos_distintos}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card title="🏆 Top ONTs com mais reclamações">
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>
            <th style={css.th}>Cliente · External ID</th>
            <th style={css.th}>Modelo</th>
            <th style={css.th}>OLT/Board/Port</th>
            <th style={css.th}>Sinal atual</th>
            <th style={css.th}>Ocorrências</th>
            <th style={css.th}>Top categoria</th>
          </tr></thead>
          <tbody>
            {d.top_onts.map((o) => (
              <tr key={o.external_id}>
                <td style={css.td}>
                  <strong>{o.name}</strong>
                  <div style={{ fontSize: 10, color: "#64748b", fontFamily: "monospace" }}>{o.external_id}</div>
                </td>
                <td style={css.td}>{o.model}</td>
                <td style={css.td}>{o.olt} · B{o.board} / P{o.port}</td>
                <td style={css.td}>
                  {o.current_signal != null ? `${o.current_signal} dBm` : "—"}
                  <div style={{ fontSize: 10, color: "#64748b" }}>{o.current_status}</div>
                </td>
                <td style={css.td}><strong>{o.ocorrencias}</strong></td>
                <td style={css.td}><span style={css.pill("#fef3c7", "#92400e")}>{o.top_categoria || "?"}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}

// ============================================================
// Section: Common Issues
// ============================================================
function CommonIssuesSection({ days }) {
  const [d, setD] = useState(null);
  useEffect(() => { let a = true; api.aiDashCommonIssues(days).then((r) => a && setD(r)); return () => { a = false; }; }, [days]);
  if (!d) return <Card>Carregando…</Card>;
  const total = d.by_category.reduce((s, x) => s + x.count, 0);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
      <Card title="📞 Categorias de reclamação">
        {d.by_category.map((c) => (
          <div key={c.category} style={{ marginBottom: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 3 }}>
              <span>{c.category}</span><strong>{c.count}</strong>
            </div>
            <div style={{ background: "#e2e8f0", borderRadius: 4, height: 6, overflow: "hidden" }}>
              <div style={{ background: "#0ea5e9", height: "100%", width: `${(c.count / Math.max(1, total)) * 100}%` }} />
            </div>
          </div>
        ))}
      </Card>
      <Card title="📡 Reclamações por OLT">
        {d.by_olt.length === 0 ? <div style={{ color: "#64748b" }}>Sem dados.</div>
          : d.by_olt.map((o) => (
            <div key={o.olt} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid #f1f5f9" }}>
              <span style={{ fontWeight: 600 }}>{o.olt}</span><strong>{o.count}</strong>
            </div>
          ))}
      </Card>
      <Card title="🔌 Reclamações por porta (Top 20)" style={{ gridColumn: "span 2" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr><th style={css.th}>OLT · Board / Port</th><th style={css.th}>Reclamações</th></tr></thead>
          <tbody>
            {d.by_port.map((p) => (
              <tr key={p.location}><td style={css.td}>{p.location}</td><td style={css.td}><strong>{p.count}</strong></td></tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

// ============================================================
// Section: Recurring
// ============================================================
function RecurringSection({ days }) {
  const [d, setD] = useState(null);
  useEffect(() => { let a = true; api.aiDashRecurring(days).then((r) => a && setD(r)); return () => { a = false; }; }, [days]);
  if (!d) return <Card>Carregando…</Card>;
  return (
    <>
      <Card title="🔁 Técnicos que mais retornam ao mesmo cliente">
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr><th style={css.th}>Técnico</th><th style={css.th}>Revisits</th><th style={css.th}>Top clientes recorrentes</th></tr></thead>
          <tbody>
            {d.techs_revisits.length === 0
              ? <tr><td colSpan={3} style={{ padding: 24, color: "#64748b", textAlign: "center" }}>Nenhuma reincidência detectada.</td></tr>
              : d.techs_revisits.map((t) => (
                <tr key={t.tech_name}>
                  <td style={css.td}><strong>{t.tech_name}</strong></td>
                  <td style={css.td}><span style={css.pill("#fee2e2", "#991b1b")}>{t.revisits_count} revisits</span></td>
                  <td style={css.td}>
                    {(t.top_clients || []).map((c, i) => (
                      <div key={i} style={{ fontSize: 12 }}>{c.client} · <strong>{c.count}x</strong></div>
                    ))}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </Card>
      <Card title="🥇 Clientes com mais reclamações">
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr><th style={css.th}>#</th><th style={css.th}>Cliente</th><th style={css.th}>Endereço</th><th style={css.th}>Tickets</th><th style={css.th}>Tipos</th></tr></thead>
          <tbody>
            {d.top_recurring_clients.map((c, i) => (
              <tr key={i}>
                <td style={css.td}>{i + 1}</td>
                <td style={css.td}>
                  <strong>{c.client_name}</strong>
                  <div style={{ fontSize: 10, color: "#64748b", fontFamily: "monospace" }}>{c.pppoe_user}</div>
                </td>
                <td style={css.td}>{c.address}</td>
                <td style={css.td}><span style={css.pill("#dbeafe", "#1e40af")}>{c.total_tickets}</span></td>
                <td style={css.td}>
                  {Object.entries(c.tipos).map(([k, v]) => `${k}:${v}`).join(" · ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}

// ============================================================
// Section: Insights LLM
// ============================================================
function InsightsSection({ days }) {
  const [generating, setGenerating] = useState(false);
  const [history, setHistory] = useState([]);
  const [err, setErr] = useState("");

  const loadHistory = useCallback(async () => {
    try { setHistory(await api.aiInsightsHistory()); } catch { /* ignore */ }
  }, []);
  useEffect(() => { loadHistory(); }, [loadHistory]);

  const generate = async (dashboard) => {
    setGenerating(true); setErr("");
    try {
      await api.aiInsight(dashboard, days);
      loadHistory();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setGenerating(false); }
  };

  return (
    <>
      <Card title="💡 Gerar insight com IA (Gemini Flash via Universal Key)">
        <p style={{ fontSize: 13, color: "#475569", marginTop: 0 }}>
          A IA analisa o dashboard escolhido e devolve insights acionáveis em PT-BR (3-5 bullets + 1 ação prioritária).
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {["overview", "tech_spending", "common_issues", "recurring", "defective"].map((k) => (
            <Button key={k} variant="soft" disabled={generating} onClick={() => generate(k)} data-testid={`insight-gen-${k}`}>
              {generating ? "🤖 Gerando…" : `Analisar ${k.replace("_", " ")}`}
            </Button>
          ))}
        </div>
        {err && <div style={{ marginTop: 10, padding: 10, background: "#fee2e2", color: "#7f1d1d", borderRadius: 8 }}>⚠ {err}</div>}
      </Card>

      <Card title={`🗒 Histórico de insights (${history.length})`}>
        {history.length === 0 ? (
          <div style={{ color: "#64748b", padding: 12 }}>Sem insights ainda. Clique acima pra gerar.</div>
        ) : history.map((h) => (
          <div key={h.id} style={{ marginBottom: 14, padding: 12, background: "#f8fafc", borderRadius: 10, borderLeft: "3px solid #7c3aed" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
              <span style={css.pill("#ede9fe", "#5b21b6")}>{h.dashboard}</span>
              <span style={{ fontSize: 11, color: "#64748b" }}>
                {new Date(h.generated_at).toLocaleString("pt-BR")} · {h.generated_by}
              </span>
            </div>
            <pre style={{ whiteSpace: "pre-wrap", fontSize: 13, fontFamily: "inherit", margin: 0 }}>{h.text}</pre>
          </div>
        ))}
      </Card>
    </>
  );
}

// ============================================================
// Main panel
// ============================================================
export default function AICenterPanel({ onClose }) {
  const [tab, setTab] = useState("overview");
  const [days, setDays] = useState(30);

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.55)", zIndex: 100, padding: 20, overflowY: "auto" }}>
      <div onClick={(e) => e.stopPropagation()} data-testid="ai-center-panel"
           style={{ background: "#f8fafc", maxWidth: 1280, margin: "0 auto", borderRadius: 18, padding: 22, minHeight: "92vh" }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14, flexWrap: "wrap", gap: 8 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: "#0f172a" }}>
              🧠 Central de IA
            </h2>
            <p style={{ margin: "4px 0 0", fontSize: 13, color: "#64748b" }}>
              Dashboards, insights e automações de IA — tudo em um lugar.
            </p>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <select value={days} onChange={(e) => setDays(Number(e.target.value))}
                    style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 13 }} data-testid="ai-days-select">
              <option value={7}>Últimos 7 dias</option>
              <option value={30}>Últimos 30 dias</option>
              <option value={90}>Últimos 90 dias</option>
            </select>
            <Button onClick={onClose}>Fechar</Button>
          </div>
        </div>

        {/* Sub-tabs */}
        <div style={{ display: "flex", gap: 4, padding: 4, background: "#e2e8f0", borderRadius: 12, marginBottom: 14, overflowX: "auto", flexWrap: "wrap" }}>
          {SUB_TABS.map((s) => (
            <button key={s.id} onClick={() => setTab(s.id)}
                    data-testid={`ai-tab-${s.id}`}
                    style={{
                      padding: "8px 14px", border: "none", borderRadius: 8,
                      background: tab === s.id ? "white" : "transparent",
                      color: tab === s.id ? "#0f172a" : "#475569",
                      fontWeight: 700, fontSize: 13, cursor: "pointer", whiteSpace: "nowrap",
                      boxShadow: tab === s.id ? "0 1px 3px rgba(0,0,0,.08)" : "none",
                    }}>
              {s.label}
            </button>
          ))}
        </div>

        {tab === "overview" && <OverviewSection days={days} setDays={setDays} />}
        {tab === "preventive" && <AIPreventivePanel onClose={() => setTab("overview")} embedded />}
        {tab === "tech_spending" && <TechSpendingSection days={days} />}
        {tab === "repair_map" && <RepairMapSection days={days} />}
        {tab === "defective" && <DefectiveSection days={days} />}
        {tab === "common_issues" && <CommonIssuesSection days={days} />}
        {tab === "recurring" && <RecurringSection days={days} />}
        {tab === "insights" && <InsightsSection days={days} />}
      </div>
    </div>
  );
}
