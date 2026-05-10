import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Card, Button, Metric } from "@/ui";
import { api } from "@/api";
import { Circle, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";
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
  { id: "common_issues", label: "📞 Chamados" },
  { id: "recurring", label: "🔁 Reincidência" },
  { id: "assets", label: "🎒 Checklist" },
  { id: "insights", label: "💡 Insights LLM" },
];

const PERIOD_OPTIONS = [
  { value: 1, label: "Último dia" },
  { value: 15, label: "Últimos 15 dias" },
  { value: 30, label: "Último mês" },
  { value: 365, label: "Último ano" },
];

const TYPE_COLORS = {
  reparo: "#dc2626", instalacao: "#16a34a", retirada: "#a16207",
  preventiva: "#0d9488", troca_endereco: "#2563eb",
};

const css = {
  th: { padding: 10, textAlign: "left", background: "#f8fafc", fontSize: 11, fontWeight: 800, color: "#475569", textTransform: "uppercase", letterSpacing: 0.4 },
  td: { padding: 10, fontSize: 13, borderBottom: "1px solid #f1f5f9", verticalAlign: "top" },
  pill: (bg, color) => ({ background: bg, color, padding: "2px 8px", borderRadius: 999, fontSize: 11, fontWeight: 700, display: "inline-block" }),
  table: { width: "100%", borderCollapse: "collapse" },
  emptyTd: { padding: 24, color: "#64748b", textAlign: "center" },
  kpiGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))", gap: 14, marginBottom: 14 },
};

const fmtBRL = (v) => (Number(v) || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

// Tiny fetch hook to remove `useEffect` boilerplate from every section
function useFetch(loader, deps) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    loader().then((r) => alive && setData(r)).catch(() => alive && setData(null));
    return () => { alive = false; };
    // `deps` is the explicit dep list passed by callers; `loader` is recreated each render
    // and would defeat the purpose of the cache.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return data;
}

// ============================================================
// Sections
// ============================================================
function OverviewSection({ days }) {
  const d = useFetch(() => api.aiDashOverview(days), [days]);
  if (!d) return <Card>Carregando…</Card>;
  return (
    <>
      <div style={{ ...css.kpiGrid, marginBottom: 18 }}>
        <Metric label="Tickets (período)" value={d.tickets.total} />
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
          {' '}Taxa de fechamento: <strong>{d.tickets.fechamento_pct}%</strong>.
          {' '}Da base SmartOLT (<strong>{d.smartolt.onus_total} ONUs</strong>),
          {' '}<strong>{d.smartolt.critical_pct}%</strong> estão em estado crítico.
          {' '}IA Preventiva: <strong>{d.ai_preventive.accepted_period}</strong> aceitas / <strong>{d.ai_preventive.pending}</strong> pendentes.
          {' '}Notificações não lidas: <strong>{d.alerts.notif_unread}</strong>.
        </div>
      </Card>
    </>
  );
}

function TechSpendingSection({ days }) {
  const d = useFetch(() => api.aiDashTechSpending(days), [days]);
  if (!d) return <Card>Carregando…</Card>;
  return (
    <>
      <div style={css.kpiGrid}>
        <Metric label="Custo total (período)" value={fmtBRL(d.totals.custo_brl)} />
        <Metric label="Notas com baixa" value={d.totals.notas} />
        <Metric label="Custo médio/nota" value={fmtBRL(d.totals.custo_medio_por_nota)} />
      </div>
      <Card title="Gastos por técnico (insumos baixados)">
        <table style={css.table}>
          <thead><tr>
            <th style={css.th}>Técnico</th>
            <th style={css.th}>Notas</th>
            <th style={css.th}>Insumos</th>
            <th style={css.th}>Custo total</th>
            <th style={css.th}>Custo médio/nota</th>
          </tr></thead>
          <tbody>
            {d.rows.length === 0 ? (
              <tr><td colSpan={5} style={css.emptyTd}>Nenhuma baixa de estoque registrada no período.</td></tr>
            ) : d.rows.map((r) => (
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

function FitBoundsOnUpdate({ points, bbox }) {
  const map = useMap();
  useEffect(() => {
    if (!points || points.length === 0) return;
    if (bbox && bbox[0] && bbox[1]) {
      map.fitBounds([bbox[0], bbox[1]], { padding: [40, 40], maxZoom: 14 });
      return;
    }
    const lats = points.map((p) => p.latitude);
    const lngs = points.map((p) => p.longitude);
    map.fitBounds(
      [[Math.min(...lats), Math.min(...lngs)], [Math.max(...lats), Math.max(...lngs)]],
      { padding: [40, 40], maxZoom: 14 },
    );
  }, [points, bbox, map]);
  return null;
}

function RepairMapSection({ days }) {
  const [reloadKey, setReloadKey] = useState(0);
  const d = useFetch(() => api.aiDashRepairMap(days), [days, reloadKey]);
  const [filter, setFilter] = useState("all");
  const points = useMemo(() => {
    if (!d) return [];
    return filter === "all" ? d.points : d.points.filter((p) => p.type === filter);
  }, [d, filter]);
  const center = useMemo(() => {
    if (!d) return [-14.235, -51.925]; // centro do Brasil — fallback
    if (d.center) return d.center;
    if (points.length === 0) return [-14.235, -51.925];
    const lat = points.reduce((s, p) => s + p.latitude, 0) / points.length;
    const lng = points.reduce((s, p) => s + p.longitude, 0) / points.length;
    return [lat, lng];
  }, [d, points]);
  // Auto-refetch se há pendentes sendo geocodificados em background
  useEffect(() => {
    if (d?.pending_geocode > 0) {
      const t = setTimeout(() => setReloadKey((k) => k + 1), 1500);
      return () => clearTimeout(t);
    }
    return undefined;
  }, [d, reloadKey]);
  if (!d) return <Card>Carregando mapa…</Card>;
  return (
    <>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ fontSize: 13, color: "var(--text-primary)" }}>{points.length} bolhas no mapa</strong>
        <select value={filter} onChange={(e) => setFilter(e.target.value)}
                className="input" style={{ width: 220, height: 30, fontSize: 12 }}
                data-testid="map-filter">
          <option value="all">Todos os tipos ({d.count})</option>
          {Object.entries(d.by_type).map(([k, v]) => <option key={k} value={k}>{k} ({v})</option>)}
        </select>
        {d.geocoded_now > 0 && (
          <span className="pill pill--success" data-testid="repair-map-geocoded-now">
            +{d.geocoded_now} geolocalizadas agora
          </span>
        )}
        {d.pending_geocode > 0 && (
          <span className="pill pill--warning" data-testid="repair-map-pending">
            {d.pending_geocode} pendentes — geolocalizando…
          </span>
        )}
        <span style={{ fontSize: 11, color: "var(--text-muted)", marginLeft: "auto" }}>
          Cada bolha = 1 chamado da Lousa nos últimos {days} dia(s) · clique para detalhes
        </span>
      </div>
      <Card data-testid="repair-map-card" padding={0}>
        <div style={{ height: 540, borderRadius: 12, overflow: "hidden" }}>
          <MapContainer center={center} zoom={6} style={{ height: "100%", width: "100%" }} scrollWheelZoom>
            <TileLayer
              attribution="&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a>"
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              subdomains={["a", "b", "c"]} />
            <FitBoundsOnUpdate points={points} bbox={d.bbox} />
            {points.map((p) => {
              const color = TYPE_COLORS[p.type] || "#64748b";
              return (
                <Circle key={p.id} center={[p.latitude, p.longitude]} radius={120}
                        pathOptions={{ color, fillColor: color, fillOpacity: 0.6, weight: 2 }}>
                  <Popup>
                    <div style={{ fontSize: 12, minWidth: 220 }}>
                      <strong>{p.client_name}</strong>
                      {p.atlaz_external_id && <span className="pill pill--accent" style={{ marginLeft: 6, fontSize: 10 }}>Atlaz</span>}
                      <br />
                      <span style={{ color: "var(--text-secondary)" }}>{p.address || "—"}</span><br />
                      {p.neighborhood && <><span style={{ color: "var(--text-muted)", fontSize: 11 }}>{p.neighborhood}</span><br /></>}
                      <span className="pill pill--neutral" style={{ marginRight: 4 }}>{p.type}</span>
                      {p.priority && p.priority !== "normal" && <span className="pill pill--warning" style={{ marginRight: 4 }}>{p.priority}</span>}
                      {p.status && <span className="pill pill--info">{p.status}</span>}
                      {p.rx_dbm != null && (
                        <div style={{ marginTop: 4, fontWeight: 700 }}>
                          {p.rx_dbm.toFixed(1)} dBm
                          {p.signal_quality && <span style={{ color: "var(--text-secondary)", marginLeft: 4 }}>({p.signal_quality})</span>}
                        </div>
                      )}
                      {p.relato && <div style={{ marginTop: 6, fontSize: 11, color: "var(--text-secondary)" }}>"{p.relato}"</div>}
                      {p.scheduled_time && (
                        <div style={{ marginTop: 4, fontSize: 11, color: "var(--text-muted)" }}>
                          {new Date(p.scheduled_time).toLocaleString("pt-BR")}
                        </div>
                      )}
                    </div>
                  </Popup>
                </Circle>
              );
            })}
          </MapContainer>
        </div>
      </Card>
    </>
  );
}

function DefectiveSection({ days }) {
  const d = useFetch(() => api.aiDashDefective(days), [days]);
  if (!d) return <Card>Carregando…</Card>;
  return (
    <>
      <Card title={`Fabricantes com mais ocorrências (últimos ${days}d)`}>
        <table style={css.table}>
          <thead><tr>
            <th style={css.th}>Fabricante</th>
            <th style={css.th}>Ocorrências</th>
            <th style={css.th}>Equipamentos distintos</th>
          </tr></thead>
          <tbody>
            {(d.manufacturers || []).length === 0 ? (
              <tr><td colSpan={3} style={css.emptyTd}>Sem chamados de reparo no período.</td></tr>
            ) : d.manufacturers.map((m) => (
              <tr key={m.manufacturer}>
                <td style={css.td}><strong>{m.manufacturer}</strong></td>
                <td style={css.td}>{m.ocorrencias}</td>
                <td style={css.td}>{m.equipamentos_distintos}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ fontSize: 10, color: "#64748b", marginTop: 6 }}>
          🤖 Fabricante identificado pela IA a partir do prefixo do número de série (padrão IEEE) — não pelo modelo do SmartOLT.
        </div>
      </Card>
      <Card title="Top ONTs com mais chamados">
        <table style={css.table}>
          <thead><tr>
            <th style={css.th}>Cliente</th>
            <th style={css.th}>SN / External ID</th>
            <th style={css.th}>Fabricante</th>
            <th style={css.th}>OLT/Board/Port</th>
            <th style={css.th}>Sinal atual</th>
            <th style={css.th}>Ocorrências</th>
            <th style={css.th}>Top categoria</th>
          </tr></thead>
          <tbody>
            {(d.top_onts || []).map((o) => (
              <tr key={o.external_id}>
                <td style={css.td}><strong>{o.name}</strong></td>
                <td style={css.td} title={o.sn}>
                  <code style={{ fontSize: 10, fontFamily: "monospace" }}>{o.sn || o.external_id}</code>
                </td>
                <td style={css.td}>
                  <span style={css.pill("#dbeafe", "#1e40af")}>{o.manufacturer || "?"}</span>
                </td>
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

function CommonIssuesSection({ days }) {
  const d = useFetch(() => api.aiDashCommonIssues(days), [days]);
  if (!d) return <Card>Carregando…</Card>;
  const total = d.by_category.reduce((s, x) => s + x.count, 0);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
      <Card title="Categorias de chamado">
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
      <Card title="Chamados por OLT">
        {d.by_olt.length === 0 ? <div style={{ color: "#64748b" }}>Sem dados.</div>
          : d.by_olt.map((o) => (
            <div key={o.olt} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid #f1f5f9" }}>
              <span style={{ fontWeight: 600 }}>{o.olt}</span><strong>{o.count}</strong>
            </div>
          ))}
      </Card>
      <Card title="Chamados por porta (Top 20)" style={{ gridColumn: "span 2" }}>
        <table style={css.table}>
          <thead><tr><th style={css.th}>OLT · Board / Port</th><th style={css.th}>Chamados</th></tr></thead>
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

function RecurringSection({ days }) {
  const d = useFetch(() => api.aiDashRecurring(days), [days]);
  if (!d) return <Card>Carregando…</Card>;
  return (
    <>
      <Card title="Técnicos que mais retornam ao mesmo cliente">
        <table style={css.table}>
          <thead><tr><th style={css.th}>Técnico</th><th style={css.th}>Revisits</th><th style={css.th}>Top clientes recorrentes</th></tr></thead>
          <tbody>
            {d.techs_revisits.length === 0 ? (
              <tr><td colSpan={3} style={css.emptyTd}>Nenhuma reincidência detectada.</td></tr>
            ) : d.techs_revisits.map((t) => (
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
      <Card title="Clientes com mais reclamações">
        <table style={css.table}>
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
                <td style={css.td}>{Object.entries(c.tipos).map(([k, v]) => `${k}:${v}`).join(" · ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}

function AssetsOverviewSection() {
  const d = useFetch(() => api.aiDashAssetsOverview(), []);
  if (!d) return <Card>Carregando…</Card>;
  const k = d.kpis || {};
  return (
    <>
      <div style={css.kpiGrid}>
        <Metric label="Itens cadastrados" value={k.total_assets} />
        <Metric label="Quantidade total" value={k.total_qty} />
        <Metric label="Ativos (em uso)" value={k.active} />
        <Metric label="Pendentes assinatura" value={k.pending_signature} />
        <Metric label="Devolvidos" value={k.returned} />
        <Metric label="Danificados/Perdidos" value={(k.damaged || 0) + (k.lost || 0)} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <Card title="Distribuição por categoria">
          {(d.by_category || []).length === 0
            ? <div style={{ color: "#64748b" }}>Sem itens cadastrados ainda.</div>
            : d.by_category.map((c) => (
              <div key={c.category} style={{ display: "flex", justifyContent: "space-between",
                                              padding: "6px 0", borderBottom: "1px solid #f1f5f9" }}>
                <span style={{ fontWeight: 600, textTransform: "capitalize" }}>{c.category}</span>
                <strong>{c.count}</strong>
              </div>
            ))}
        </Card>
        <Card title="Status">
          {(d.by_status || []).map((c) => (
            <div key={c.status} style={{ display: "flex", justifyContent: "space-between",
                                          padding: "6px 0", borderBottom: "1px solid #f1f5f9" }}>
              <span style={{ fontWeight: 600, textTransform: "capitalize" }}>{c.status}</span>
              <strong>{c.count}</strong>
            </div>
          ))}
        </Card>
      </div>
      <Card title="Checklist por colaborador">
        <table style={css.table}>
          <thead><tr>
            <th style={css.th}>Colaborador</th>
            <th style={css.th}>Total</th>
            <th style={css.th}>Ativos</th>
            <th style={css.th}>Pendentes assin.</th>
            <th style={css.th}>Devolvidos</th>
            <th style={css.th}>Categorias</th>
          </tr></thead>
          <tbody>
            {(d.rows || []).length === 0
              ? <tr><td colSpan={6} style={css.emptyTd}>Nenhum colaborador com itens em custódia.</td></tr>
              : d.rows.map((r) => (
                <tr key={r.collaborator_id}>
                  <td style={css.td}>
                    <strong>{r.name}</strong>
                    {r.role && <div style={{ fontSize: 10, color: "#64748b" }}>{r.role}</div>}
                  </td>
                  <td style={css.td}><strong>{r.total}</strong></td>
                  <td style={css.td}><span style={css.pill("#dcfce7", "#166534")}>{r.ativo}</span></td>
                  <td style={css.td}>
                    {r.pending_signature > 0
                      ? <span style={css.pill("#fef3c7", "#92400e")}>{r.pending_signature}</span>
                      : <span style={{ color: "#94a3b8" }}>0</span>}
                  </td>
                  <td style={css.td}>{r.devolvido}</td>
                  <td style={css.td}>
                    {Object.entries(r.categories || {}).map(([k2, v]) => (
                      <span key={k2} style={{ marginRight: 6, fontSize: 11 }}>
                        {k2}: <strong>{v}</strong>
                      </span>
                    ))}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </Card>
      <PendingLossesCard pl={d.pending_losses} />
    </>
  );
}

function PendingLossesCard({ pl }) {
  if (!pl) return null;
  const empty = !pl.rows || pl.rows.length === 0;
  return (
    <Card title="Perdas pendentes — colaboradores desativados com itens em custódia ativos"
          data-testid="pending-losses-card">
      {empty ? (
        <div style={{ padding: 16, textAlign: "center", color: "#16a34a", fontWeight: 600 }}>
          ✓ Nenhuma perda pendente. Todos os colaboradores desativados devolveram seus itens em custódia.
        </div>
      ) : (
        <>
          <div style={{ ...css.kpiGrid, marginBottom: 12 }}>
            <Metric label="Colaboradores desativados" value={pl.inactive_collaborators} />
            <Metric label="Itens não devolvidos" value={pl.items_count} />
            <Metric label="Prejuízo estimado" value={fmtBRL(pl.total_brl)} />
          </div>
          <table style={css.table}>
            <thead><tr>
              <th style={css.th}>Colaborador</th>
              <th style={css.th}>Desativado em</th>
              <th style={css.th}>Itens</th>
              <th style={css.th}>Valor estimado</th>
              <th style={css.th}>Detalhes</th>
            </tr></thead>
            <tbody>
              {pl.rows.map((r) => (
                <tr key={r.collaborator_id}>
                  <td style={css.td}>
                    <strong>{r.name}</strong>
                    {r.role && <div style={{ fontSize: 10, color: "#64748b" }}>{r.role}</div>}
                  </td>
                  <td style={css.td}>
                    {r.deactivated_at ? r.deactivated_at.slice(0, 10) : "—"}
                  </td>
                  <td style={css.td}>
                    <span style={css.pill("#fee2e2", "#991b1b")}>{r.items.length}</span>
                  </td>
                  <td style={{ ...css.td, fontWeight: 800, color: "#991b1b" }}>
                    {fmtBRL(r.value_brl)}
                  </td>
                  <td style={css.td}>
                    {r.items.slice(0, 5).map((it) => (
                      <div key={it.id} style={{ fontSize: 11, color: "#475569" }}>
                        · {it.item} ({it.qty}× — {fmtBRL(it.value_brl)})
                      </div>
                    ))}
                    {r.items.length > 5 && (
                      <div style={{ fontSize: 11, color: "#94a3b8" }}>
                        … +{r.items.length - 5} item(ns)
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 8 }}>
            Valor padrão por categoria: {Object.entries(pl.default_values_brl || {}).map(([k, v]) => `${k}=${fmtBRL(v)}`).join(" · ")}.
            Use o campo <em>Valor unitário (R$)</em> ao cadastrar para sobrescrever.
          </div>
        </>
      )}
    </Card>
  );
}

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

  const DASHBOARDS = ["overview", "tech_spending", "common_issues", "recurring", "defective"];
  return (
    <>
      <Card title="Gerar insight com IA (Gemini Flash via Universal Key)">
        <p style={{ fontSize: 13, color: "#475569", marginTop: 0 }}>
          A IA analisa o dashboard escolhido e devolve insights acionáveis em PT-BR (3-5 bullets + 1 ação prioritária).
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {DASHBOARDS.map((k) => (
            <Button key={k} variant="soft" disabled={generating} onClick={() => generate(k)} data-testid={`insight-gen-${k}`}>
              {generating ? "🤖 Gerando…" : `Analisar ${k.replace("_", " ")}`}
            </Button>
          ))}
        </div>
        {err && <div style={{ marginTop: 10, padding: 10, background: "#fee2e2", color: "#7f1d1d", borderRadius: 8 }}>⚠ {err}</div>}
      </Card>

      <Card title={`Histórico de insights (${history.length})`}>
        {history.length === 0 ? (
          <div style={{ color: "#64748b", padding: 12 }}>Sem insights ainda. Clique acima pra gerar.</div>
        ) : history.map((h) => (
          <div key={h.id} style={{ marginBottom: 14, padding: 12, background: "#f8fafc", borderRadius: 10, borderLeft: "3px solid #0d9488" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
              <span style={css.pill("#ccfbf1", "#0f766e")}>{h.dashboard}</span>
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
const TAB_COMPONENTS = {
  overview: OverviewSection,
  tech_spending: TechSpendingSection,
  repair_map: RepairMapSection,
  defective: DefectiveSection,
  common_issues: CommonIssuesSection,
  recurring: RecurringSection,
  assets: AssetsOverviewSection,
  insights: InsightsSection,
};

export default function AICenterPanel({ onClose }) {
  const [tab, setTab] = useState("overview");
  const [days, setDays] = useState(30);
  const Section = TAB_COMPONENTS[tab];

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.55)", zIndex: 100, padding: 20, overflowY: "auto" }}>
      <div onClick={(e) => e.stopPropagation()} data-testid="ai-center-panel"
           style={{ background: "#f8fafc", maxWidth: 1280, margin: "0 auto", borderRadius: 18, padding: 22, minHeight: "92vh" }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14, flexWrap: "wrap", gap: 8 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: "#0f172a" }}>Central de IA</h2>
            <p style={{ margin: "4px 0 0", fontSize: 13, color: "#64748b" }}>
              Dashboards, insights e automações de IA — tudo em um lugar.
            </p>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <select value={days} onChange={(e) => setDays(Number(e.target.value))}
                    style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 13 }}
                    data-testid="ai-days-select">
              {PERIOD_OPTIONS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
            <Button onClick={onClose}>Fechar</Button>
          </div>
        </div>

        {/* Sub-tabs */}
        <div style={{ display: "flex", gap: 4, padding: 4, background: "#e2e8f0", borderRadius: 12, marginBottom: 14, overflowX: "auto", flexWrap: "wrap" }}>
          {SUB_TABS.map((s) => (
            <button key={s.id} onClick={() => setTab(s.id)} data-testid={`ai-tab-${s.id}`}
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

        {tab === "preventive"
          ? <AIPreventivePanel onClose={() => setTab("overview")} embedded />
          : Section && <Section days={days} />}
      </div>
    </div>
  );
}
