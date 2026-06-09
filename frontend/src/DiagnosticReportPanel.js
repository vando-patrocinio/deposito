/* DiagnosticReportPanel.js — Relatório de Diagnóstico Completo SmartProv
   Consome GET /api/conselho-ia/diagnostic-report e renderiza 16 seções
   em tela com dados brutos estruturados. Design Oracle.
*/
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import {
  Activity, AlertTriangle, Bot, CheckCircle2, ChevronDown, ChevronRight,
  Database, FileSearch, Layers, LineChart, Network, RefreshCw,
  Shield, Truck, Wallet, Workflow, Plug, ListTodo, Gauge, Scale,
  Printer, Link2, Check,
} from "lucide-react";

const ORACLE = {
  purple: "#4b1d7a", orange: "#f28c28",
  green: "#237a4b", red: "#b42318",
  bg: "#f8fafc", border: "#e2e8f0",
};

// Mapa de ícones e cor por seção
const SECTION_META = {
  "01_executive_summary": { icon: FileSearch, color: ORACLE.purple },
  "02_module_map":        { icon: Layers,     color: "#1e40af" },
  "03_ai_engine":         { icon: Bot,        color: ORACLE.purple },
  "04_database":          { icon: Database,   color: "#475569" },
  "05_operations":        { icon: Workflow,   color: "#0891b2" },
  "06_network":           { icon: Network,    color: "#1e40af" },
  "07_gps_fleet":         { icon: Truck,      color: ORACLE.orange },
  "08_security":          { icon: Shield,     color: ORACLE.green },
  "09_financials":        { icon: Wallet,     color: ORACLE.green },
  "10_kpis":              { icon: LineChart,  color: ORACLE.purple },
  "11_automations":       { icon: Activity,   color: "#7c3aed" },
  "12_integrations":      { icon: Plug,       color: "#0891b2" },
  "13_roadmap":           { icon: ListTodo,   color: ORACLE.orange },
  "14_ai_auto_analysis":  { icon: Gauge,      color: ORACLE.purple },
  "15_executive_review":  { icon: Scale,      color: ORACLE.purple },
  "16_anomalies":         { icon: AlertTriangle, color: ORACLE.red },
};

const STATE_LABEL = {
  saudavel: { label: "Saudável", color: ORACLE.green },
  atencao:  { label: "Atenção",  color: ORACLE.orange },
  critico:  { label: "Crítico",  color: ORACLE.red },
};

export default function DiagnosticReportPanel() {
  const [days, setDays] = useState(30);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [isPrinting, setIsPrinting] = useState(false);
  const [linkCopied, setLinkCopied] = useState(false);

  const fetchReport = async () => {
    setLoading(true); setErr("");
    try {
      const r = await api._client.get(
        `/conselho-ia/diagnostic-report?days=${days}`);
      setReport(r.data);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchReport();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Restaura estado após impressão (legado — botão agora baixa PDF)
  useEffect(() => {
    const onAfterPrint = () => setIsPrinting(false);
    window.addEventListener("afterprint", onAfterPrint);
    return () => window.removeEventListener("afterprint", onAfterPrint);
  }, []);

  const buildPdfUrl = () => {
    const base = (process.env.REACT_APP_BACKEND_URL || "").replace(
      /\/$/, "");
    return `${base}/api/conselho-ia/diagnostic-report.pdf?days=${days}`;
  };

  const handleDownloadPdf = async () => {
    setIsPrinting(true);
    try {
      const url = buildPdfUrl();
      const token = localStorage.getItem("ponto_token")
        || localStorage.getItem("token");
      const resp = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const blobUrl = URL.createObjectURL(blob);
      const stamp = new Date().toISOString().slice(0, 16)
        .replace(/[:T]/g, "-");
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = `diagnostico-smartprov-${stamp}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 1500);
    } catch (e) {
      setErr(`Falha ao baixar PDF: ${e.message}`);
    }
    setIsPrinting(false);
  };

  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(buildPdfUrl());
      setErr("");
      // feedback rápido
      setLinkCopied(true);
      setTimeout(() => setLinkCopied(false), 2000);
    } catch (e) {
      setErr(`Falha ao copiar link: ${e.message}`);
    }
  };

  return (
    <div data-testid="diagnostic-report-panel" style={{
      display: "flex", flexDirection: "column", gap: 16, padding: "0 4px",
    }}>
      {/* Cabeçalho */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        flexWrap: "wrap", gap: 12,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{
            width: 42, height: 42, borderRadius: 10,
            background: `linear-gradient(135deg, ${ORACLE.purple}, #6d28d9)`,
            display: "flex", alignItems: "center", justifyContent: "center",
            boxShadow: "0 4px 12px rgba(75, 29, 122, .3)",
          }}>
            <FileSearch size={22} color="white" />
          </div>
          <div>
            <h1 style={{
              fontSize: 22, fontWeight: 800, margin: 0,
              color: "var(--text-primary)", letterSpacing: "-0.02em",
            }}>Diagnóstico Completo do SmartProv</h1>
            <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
              16 seções · dados brutos · sem síntese LLM
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select value={days}
                   onChange={(e) => setDays(Number(e.target.value))}
                   data-testid="diag-period-select"
                   style={{
                     padding: "8px 12px", fontSize: 13, fontWeight: 600,
                     border: `1px solid ${ORACLE.border}`, borderRadius: 8,
                     background: "white", color: ORACLE.purple,
                     cursor: "pointer",
                   }}>
            <option value={7}>Últimos 7 dias</option>
            <option value={30}>Últimos 30 dias</option>
            <option value={90}>Últimos 90 dias</option>
            <option value={180}>Últimos 180 dias</option>
            <option value={365}>Último ano</option>
          </select>
          <button onClick={handleDownloadPdf} disabled={loading || isPrinting}
                   data-testid="diag-export-pdf"
                   style={{
                     padding: "8px 14px", fontSize: 12, fontWeight: 700,
                     border: `1px solid ${ORACLE.purple}`, borderRadius: 8,
                     cursor: "pointer",
                     background: "white", color: ORACLE.purple,
                     display: "flex", alignItems: "center", gap: 6,
                     opacity: (loading || isPrinting) ? .6 : 1,
                   }}>
            <Printer size={13} />
            {isPrinting ? "Gerando…" : "Baixar PDF"}
          </button>
          <button onClick={handleCopyLink}
                   data-testid="diag-copy-link"
                   style={{
                     padding: "8px 14px", fontSize: 12, fontWeight: 700,
                     border: `1px solid ${ORACLE.border}`, borderRadius: 8,
                     cursor: "pointer",
                     background: "white",
                     color: linkCopied ? ORACLE.green : "#64748b",
                     display: "flex", alignItems: "center", gap: 6,
                   }}>
            {linkCopied ? <Check size={13} /> : <Link2 size={13} />}
            {linkCopied ? "Copiado!" : "Copiar link"}
          </button>
          <button onClick={fetchReport} disabled={loading}
                   data-testid="diag-refresh"
                   style={{
                     padding: "8px 14px", fontSize: 12, fontWeight: 700,
                     border: "none", borderRadius: 8, cursor: "pointer",
                     background: ORACLE.purple, color: "white",
                     display: "flex", alignItems: "center", gap: 6,
                     opacity: loading ? .6 : 1,
                   }}>
            <RefreshCw size={13}
              style={{
                animation: loading ? "spin 1s linear infinite" : "none",
              }} />
            {loading ? "Coletando…" : "Atualizar"}
          </button>
        </div>
      </div>

      {err && (
        <div data-testid="diag-error" style={{
          background: "#fef2f2", border: `1px solid ${ORACLE.red}`,
          color: ORACLE.red, padding: "10px 14px", borderRadius: 8,
          fontSize: 13, fontWeight: 600,
        }}>Erro: {err}</div>
      )}

      {!report && !err && (
        <div style={{
          background: "white", padding: 40, textAlign: "center",
          color: "#64748b", border: `1px solid ${ORACLE.border}`,
          borderRadius: 10, fontSize: 13,
        }}>Coletando dados das 16 seções…</div>
      )}

      {report && (
        <div style={{
          fontSize: 11, color: "#64748b", textAlign: "right",
        }}>
          Coletado em {new Date(report.generated_at).toLocaleString("pt-BR")}
          {" · "} {report.elapsed_ms} ms
          {" · "} período: {report.period_days} dias
        </div>
      )}

      {report?.sections && Object.keys(report.sections)
        .sort()
        .map((key) => (
          <SectionCard key={key} sectionKey={key}
                        section={report.sections[key]}
                        forceOpen={isPrinting} />
        ))}

      <style>{`@keyframes spin {
        from { transform: rotate(0deg); } to { transform: rotate(360deg); }
      }
      @media print {
        /* Esconde chrome do app (sidebar, topbar, ações flutuantes) */
        .app-sidebar, .app-topbar,
        [data-testid="cia-view-tabs"],
        button[data-testid="diag-export-pdf"],
        button[data-testid="diag-refresh"],
        select[data-testid="diag-period-select"] { display: none !important; }
        .app-shell, .app-main, .app-content {
          display: block !important; padding: 0 !important;
          margin: 0 !important; background: white !important;
        }
        body, html { background: white !important; }
        [data-testid="diagnostic-report-panel"] {
          padding: 0 !important; gap: 8px !important;
        }
        /* Cada seção em página separada se necessário */
        [data-testid^="diag-section-"] {
          break-inside: avoid; page-break-inside: avoid;
          box-shadow: none !important;
          border: 1px solid #cbd5e1 !important;
        }
        /* Evita cortar tabelas/KPI no meio */
        table, tr, .kpi-card { break-inside: avoid; page-break-inside: avoid; }
      }`}</style>
    </div>
  );
}

// ───────────────── Sub-components ─────────────────
function SectionCard({ sectionKey, section, forceOpen = false }) {
  const [open, setOpen] = useState(true);
  const meta = SECTION_META[sectionKey] || {
    icon: FileSearch, color: ORACLE.purple,
  };
  const Icon = meta.icon;
  const isOpen = forceOpen || open;
  return (
    <section data-testid={`diag-section-${sectionKey}`}
              style={{
                background: "white", border: `1px solid ${ORACLE.border}`,
                borderRadius: 12, overflow: "hidden",
                boxShadow: "0 1px 3px rgba(15, 23, 42, .04)",
              }}>
      <header
        onClick={() => !forceOpen && setOpen((v) => !v)}
        style={{
          padding: "14px 18px", display: "flex", alignItems: "center",
          gap: 10, cursor: forceOpen ? "default" : "pointer",
          background: `${meta.color}10`,
          borderBottom: isOpen ? `1px solid ${meta.color}25` : "none",
        }}>
        <Icon size={18} color={meta.color} />
        <h2 style={{
          margin: 0, fontSize: 14, fontWeight: 800, color: meta.color,
          letterSpacing: "-0.01em", flex: 1,
        }}>{section.title}</h2>
        {!forceOpen && (isOpen
          ? <ChevronDown size={16} color={meta.color} />
          : <ChevronRight size={16} color={meta.color} />)}
      </header>
      {isOpen && (
        <div style={{ padding: 18 }}>
          <SectionRenderer sectionKey={sectionKey} data={section.data} />
        </div>
      )}
    </section>
  );
}

// Roteia o data pra renderizador específico (ou genérico)
function SectionRenderer({ sectionKey, data }) {
  if (!data) return <Empty />;
  switch (sectionKey) {
    case "01_executive_summary": return <ExecutiveSummaryView d={data} />;
    case "02_module_map":        return <ModuleMapView d={data} />;
    case "03_ai_engine":         return <AIEngineView d={data} />;
    case "04_database":          return <DatabaseView d={data} />;
    case "05_operations":        return <OperationsView d={data} />;
    case "06_network":           return <NetworkView d={data} />;
    case "07_gps_fleet":         return <KvGrid d={data} />;
    case "08_security":          return <KvGrid d={data} />;
    case "09_financials":        return <FinancialsView d={data} />;
    case "10_kpis":              return <KpisView d={data} />;
    case "11_automations":       return <AutomationsView d={data} />;
    case "12_integrations":      return <IntegrationsView d={data} />;
    case "13_roadmap":           return <RoadmapView d={data} />;
    case "14_ai_auto_analysis":  return <AIAutoView d={data} />;
    case "15_executive_review":  return <ExecutiveReviewView d={data} />;
    case "16_anomalies":         return <AnomaliesView d={data} />;
    default:                       return <JsonView d={data} />;
  }
}

function Empty() {
  return <div style={{ fontSize: 13, color: "#94a3b8" }}>
    Sem dados.</div>;
}

function JsonView({ d }) {
  return (
    <pre style={{
      background: "#fafbfc", border: `1px solid ${ORACLE.border}`,
      borderRadius: 6, padding: 12, fontSize: 11, lineHeight: 1.5,
      overflowX: "auto", color: "#334155", margin: 0,
    }}>{JSON.stringify(d, null, 2)}</pre>
  );
}

function Kpi({ label, value, color = ORACLE.purple,
                 prefix = "", suffix = "" }) {
  const display = typeof value === "number"
    ? value.toLocaleString("pt-BR")
    : (value ?? "—");
  return (
    <div style={{
      background: "#fafbfc", border: `1px solid ${ORACLE.border}`,
      borderTop: `3px solid ${color}`, borderRadius: 8,
      padding: 12, textAlign: "left", minWidth: 0,
    }}>
      <div style={{
        fontSize: 18, fontWeight: 800, color,
        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
      }}>{prefix}{display}{suffix}</div>
      <div style={{
        fontSize: 9, color: "#64748b", textTransform: "uppercase",
        letterSpacing: .5, fontWeight: 700, marginTop: 2,
      }}>{label}</div>
    </div>
  );
}

function KpiGrid({ children, min = 130 }) {
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: `repeat(auto-fit, minmax(${min}px, 1fr))`,
      gap: 10,
    }}>{children}</div>
  );
}

function KvGrid({ d }) {
  // Renderiza genérico key->value como KPIs
  return (
    <KpiGrid>
      {Object.entries(d).map(([k, v]) => (
        <Kpi key={k} label={k.replace(/_/g, " ")}
              value={typeof v === "object" ? JSON.stringify(v) : v} />
      ))}
    </KpiGrid>
  );
}

function MiniTable({ rows, columns }) {
  if (!rows?.length) return <Empty />;
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{
        width: "100%", borderCollapse: "collapse", fontSize: 12,
      }}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} style={{
                textAlign: "left", padding: "8px 10px",
                background: "#f1f5f9", color: "#475569",
                fontSize: 10, fontWeight: 800, textTransform: "uppercase",
                letterSpacing: .5,
                borderBottom: `1px solid ${ORACLE.border}`,
              }}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} style={{
              background: i % 2 === 0 ? "#fff" : "#fafbfc",
            }}>
              {columns.map((c) => (
                <td key={c.key} style={{
                  padding: "8px 10px", color: "#334155",
                  borderBottom: `1px solid ${ORACLE.border}`,
                }}>{c.render ? c.render(r) : (r[c.key] ?? "—")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SubTitle({ children }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 800, color: "#475569",
      textTransform: "uppercase", letterSpacing: .5,
      marginBottom: 8, marginTop: 12,
    }}>{children}</div>
  );
}

function StatusPill({ ok, labelTrue = "Ativo", labelFalse = "Inativo" }) {
  return (
    <span style={{
      background: ok ? `${ORACLE.green}20` : `${ORACLE.red}15`,
      color: ok ? ORACLE.green : ORACLE.red,
      padding: "2px 8px", borderRadius: 10, fontSize: 10,
      fontWeight: 800, textTransform: "uppercase", letterSpacing: .5,
    }}>{ok ? labelTrue : labelFalse}</span>
  );
}

// ─────── Section views ───────

function ExecutiveSummaryView({ d }) {
  const fmt = (n) => `R$ ${Number(n || 0).toLocaleString("pt-BR",
    { minimumFractionDigits: 2 })}`;
  return (
    <KpiGrid>
      <Kpi label="Total clientes" value={d.total_clientes}
            color={ORACLE.purple} />
      <Kpi label="Ativos" value={d.clientes_ativos} color={ORACLE.green} />
      <Kpi label="Inadimplentes" value={d.clientes_inadimplentes}
            color={ORACLE.red} />
      <Kpi label="Cancelados" value={d.clientes_cancelados} color="#64748b" />
      <Kpi label="Novos no período" value={d.novos_no_periodo}
            color="#1e40af" />
      <Kpi label="MRR" value={fmt(d.mrr_brl)} color={ORACLE.green} />
      <Kpi label="Ticket médio" value={fmt(d.ticket_medio_brl)}
            color={ORACLE.purple} />
      <Kpi label="Churn %" value={d.churn_pct}
            color={d.churn_pct > 5 ? ORACLE.red : ORACLE.green}
            suffix="%" />
      <Kpi label="Inadimplência %" value={d.inadimplencia_pct}
            color={d.inadimplencia_pct > 10 ? ORACLE.red : ORACLE.orange}
            suffix="%" />
      <Kpi label="Total collections" value={d.total_collections}
            color="#475569" />
      <Kpi label="Período (dias)" value={d.periodo_dias} color="#475569" />
    </KpiGrid>
  );
}

function ModuleMapView({ d }) {
  return (
    <>
      <KpiGrid>
        <Kpi label="Módulos mapeados" value={d.total_modulos_mapeados}
              color={ORACLE.purple} />
        <Kpi label="Módulos ativos" value={d.modulos_ativos}
              color={ORACLE.green} />
      </KpiGrid>
      <SubTitle>Detalhes por módulo</SubTitle>
      <MiniTable rows={d.modulos} columns={[
        { key: "modulo", label: "Módulo" },
        { key: "ativo", label: "Status",
          render: (r) => <StatusPill ok={r.ativo} /> },
        { key: "collections_presentes", label: "Presentes",
          render: (r) => `${r.collections_presentes}/${r.collections_esperadas}` },
        { key: "saude_pct", label: "Saúde",
          render: (r) => `${r.saude_pct}%` },
        { key: "ausentes", label: "Ausentes",
          render: (r) => (r.ausentes || []).join(", ") || "—" },
      ]} />
    </>
  );
}

function AIEngineView({ d }) {
  return (
    <>
      <KpiGrid>
        <Kpi label="Provider" value={d.configuracao?.provider || "—"}
              color={ORACLE.purple} />
        <Kpi label="Model" value={d.configuracao?.model || "—"}
              color={ORACLE.purple} />
        <Kpi label="Fallback" value={d.configuracao?.fallback_provider || "—"}
              color="#475569" />
        <Kpi label="Requisições totais" value={d.total_requisicoes_periodo}
              color="#1e40af" />
        <Kpi label="Custo total (USD)" value={d.custo_total_usd?.toFixed(4)}
              color={ORACLE.orange} prefix="$" />
        <Kpi label="Isabella sessões" value={d.isabella_sessoes}
              color="#7c3aed" />
        <Kpi label="Álvaro análises" value={d.alvaro_analises}
              color="#7c3aed" />
        <Kpi label="Neo chat msgs" value={d.neo_chat_msgs}
              color="#7c3aed" />
        <Kpi label="Rede IA análises" value={d.rede_ia_analises}
              color="#1e40af" />
      </KpiGrid>
      <SubTitle>Uso por agente (no período)</SubTitle>
      <MiniTable rows={d.uso_por_agente} columns={[
        { key: "agente", label: "Agente" },
        { key: "requisicoes", label: "Requisições" },
        { key: "tokens_in", label: "Tokens in" },
        { key: "tokens_out", label: "Tokens out" },
        { key: "custo_usd", label: "Custo USD",
          render: (r) => `$${Number(r.custo_usd).toFixed(4)}` },
      ]} />
    </>
  );
}

function DatabaseView({ d }) {
  const [showAll, setShowAll] = useState(false);
  const rows = showAll ? d.todas_collections : d.top_20_volume;
  return (
    <>
      <KpiGrid>
        <Kpi label="Total collections" value={d.total_collections}
              color="#475569" />
      </KpiGrid>
      <SubTitle>
        {showAll ? "Todas as collections" : "Top 20 por volume"}
        {" "}
        <button onClick={() => setShowAll((v) => !v)}
                 data-testid="diag-db-toggle-all"
                 style={{
                   marginLeft: 6, padding: "2px 10px", border: "none",
                   borderRadius: 6, fontSize: 10, fontWeight: 700,
                   background: ORACLE.purple, color: "white",
                   cursor: "pointer",
                 }}>
          {showAll ? "Mostrar top 20" : `Mostrar todas (${d.total_collections})`}
        </button>
      </SubTitle>
      <MiniTable rows={rows} columns={[
        { key: "collection", label: "Collection" },
        { key: "total_geral", label: "Total geral" },
        { key: "total_empresa", label: "Total empresa",
          render: (r) => r.total_empresa === null ? "—" : r.total_empresa },
      ]} />
    </>
  );
}

function OperationsView({ d }) {
  return (
    <>
      <KpiGrid>
        <Kpi label="Tickets total" value={d.tickets_total}
              color={ORACLE.purple} />
        <Kpi label="Tickets no período" value={d.tickets_periodo}
              color="#1e40af" />
        <Kpi label="Tickets abertos" value={d.tickets_abertos}
              color={ORACLE.red} />
        <Kpi label="Preventive OS runs" value={d.preventive_os_runs}
              color={ORACLE.green} />
        <Kpi label="Agendamentos período" value={d.agendamentos_periodo}
              color={ORACLE.orange} />
      </KpiGrid>
      <SubTitle>Tickets por status</SubTitle>
      <MiniTable rows={d.tickets_por_status} columns={[
        { key: "status", label: "Status" },
        { key: "qtd", label: "Quantidade" },
      ]} />
    </>
  );
}

function NetworkView({ d }) {
  return (
    <>
      <KpiGrid>
        <Kpi label="CTOs" value={d.ctos} color="#1e40af" />
        <Kpi label="ONUs SmartOLT" value={d.smartolt_onus} color="#1e40af" />
        <Kpi label="RADIUS sessions" value={d.radius_sessions}
              color="#0891b2" />
        <Kpi label="Cables (rede)" value={d.network_cables}
              color="#475569" />
        <Kpi label="Ligo Map assets" value={d.ligo_map_assets}
              color={ORACLE.purple} />
        <Kpi label="Outages" value={d.network_outages}
              color={d.network_outages > 0 ? ORACLE.red : ORACLE.green} />
        <Kpi label="ONUs sinal baixo" value={d.onus_potencia_baixa}
              color={ORACLE.orange} />
        <Kpi label="Sinal médio (dBm)" value={d.potencia_media_dbm ?? "—"}
              color={ORACLE.purple} />
      </KpiGrid>
      <SubTitle>CTOs com saturação ≥85%</SubTitle>
      <MiniTable rows={d.ctos_saturadas} columns={[
        { key: "label", label: "CTO" },
        { key: "clientes", label: "Clientes" },
        { key: "capacidade", label: "Capacidade" },
        { key: "saturacao_pct", label: "Saturação",
          render: (r) => `${r.saturacao_pct}%` },
      ]} />
    </>
  );
}

function FinancialsView({ d }) {
  const fmt = (n) => `R$ ${Number(n || 0).toLocaleString("pt-BR",
    { minimumFractionDigits: 2 })}`;
  return (
    <KpiGrid>
      <Kpi label="Invoices total" value={d.invoices_total}
            color={ORACLE.purple} />
      <Kpi label="Subscriber invoices" value={d.subscriber_invoices_total}
            color={ORACLE.purple} />
      <Kpi label="Invoices em aberto"
            value={d.subscriber_invoices_em_aberto}
            color={ORACLE.orange} />
      <Kpi label="Pagamentos período"
            value={d.transacoes_pagamento_periodo}
            color="#1e40af" />
      <Kpi label="Receita período" value={fmt(d.receita_periodo_brl)}
            color={ORACLE.green} />
      <Kpi label="Contas a pagar" value={d.contas_pagar_total}
            color="#475569" />
      <Kpi label="Contas pagar abertas" value={d.contas_pagar_abertas}
            color={ORACLE.red} />
      <Kpi label="Movs caixa período" value={d.movimentos_caixa_periodo}
            color={ORACLE.green} />
    </KpiGrid>
  );
}

function KpisView({ d }) {
  return (
    <KpiGrid>
      <Kpi label="Churn período %" value={d.churn_periodo_pct}
            color={d.churn_periodo_pct > 5 ? ORACLE.red : ORACLE.green}
            suffix="%" />
      <Kpi label="Inadimplência %" value={d.inadimplencia_pct}
            color={d.inadimplencia_pct > 10 ? ORACLE.red : ORACLE.orange}
            suffix="%" />
      <Kpi label="Novos clientes" value={d.novos_clientes_periodo}
            color="#1e40af" />
      <Kpi label="Cancelamentos" value={d.cancelamentos_periodo}
            color={ORACLE.red} />
      <Kpi label="Leads total" value={d.leads_total_periodo}
            color={ORACLE.orange} />
      <Kpi label="Leads (sales)" value={d.leads_breakdown?.sales}
            color={ORACLE.orange} />
      <Kpi label="Leads (site)" value={d.leads_breakdown?.site}
            color={ORACLE.orange} />
      <Kpi label="Leads (indicação)" value={d.leads_breakdown?.indicacao}
            color={ORACLE.purple} />
      <Kpi label="Conversão %" value={d.taxa_conversao_pct}
            color={ORACLE.green} suffix="%" />
    </KpiGrid>
  );
}

function AutomationsView({ d }) {
  return (
    <>
      <KpiGrid>
        <Kpi label="Automações ativas" value={d.automacoes_ativas}
              color={ORACLE.green} />
        <Kpi label="Total mapeadas"
              value={d.automacoes_conhecidas?.length || 0}
              color="#475569" />
      </KpiGrid>
      <SubTitle>Catálogo de automações</SubTitle>
      <MiniTable rows={d.automacoes_conhecidas} columns={[
        { key: "nome", label: "Automação" },
        { key: "ativo", label: "Status",
          render: (r) => <StatusPill ok={r.ativo} /> },
        { key: "hora_utc", label: "Hora UTC",
          render: (r) => r.hora_utc !== undefined && r.hora_utc !== null
            ? `${r.hora_utc}:00 UTC` : "—" },
        { key: "fonte", label: "Fonte" },
      ]} />
      {d.ultimas_execucoes
        && Object.keys(d.ultimas_execucoes).length > 0 && (
        <>
          <SubTitle>Últimas execuções</SubTitle>
          <MiniTable rows={Object.entries(d.ultimas_execucoes).map(
            ([k, v]) => ({ key: k, value: v }))} columns={[
              { key: "key", label: "Fonte" },
              { key: "value", label: "Quando",
                render: (r) => r.value
                  ? new Date(r.value).toLocaleString("pt-BR") : "—" },
            ]} />
        </>
      )}
    </>
  );
}

function IntegrationsView({ d }) {
  return (
    <>
      <KpiGrid>
        <Kpi label="Integrações ativas" value={d.ativas}
              color={ORACLE.green} />
        <Kpi label="Integrações inativas" value={d.inativas}
              color={ORACLE.red} />
      </KpiGrid>
      <SubTitle>Status das integrações</SubTitle>
      <MiniTable rows={d.integracoes} columns={[
        { key: "nome", label: "Integração" },
        { key: "ativo", label: "Status",
          render: (r) => <StatusPill ok={r.ativo} /> },
        { key: "evidencia", label: "Evidência" },
      ]} />
    </>
  );
}

function RoadmapView({ d }) {
  return (
    <>
      <KpiGrid>
        <Kpi label="Auditor pendentes" value={d.auditor_pendentes}
              color={ORACLE.orange} />
        <Kpi label="Auditor aplicadas" value={d.auditor_aplicadas}
              color={ORACLE.green} />
        <Kpi label="Auditor rejeitadas" value={d.auditor_rejeitadas}
              color="#64748b" />
        <Kpi label="Agente executadas" value={d.agente_executadas}
              color={ORACLE.green} />
        <Kpi label="Agente pendentes" value={d.agente_pendentes}
              color={ORACLE.orange} />
        <Kpi label="Agente falhas" value={d.agente_falhas}
              color={ORACLE.red} />
        <Kpi label="Desbloqueios pendentes"
              value={d.solicitacoes_desbloqueio_pendentes}
              color={ORACLE.orange} />
      </KpiGrid>
      {!!d.ultimas_acoes_pendentes?.length && (
        <>
          <SubTitle>Últimas ações pendentes</SubTitle>
          <MiniTable rows={d.ultimas_acoes_pendentes} columns={[
            { key: "action", label: "Ação" },
            { key: "notes", label: "Observação" },
            { key: "created_at", label: "Criada em",
              render: (r) => r.created_at
                ? new Date(r.created_at).toLocaleString("pt-BR") : "—" },
          ]} />
        </>
      )}
    </>
  );
}

function AIAutoView({ d }) {
  return (
    <>
      <KpiGrid>
        <Kpi label="Auditor execuções (período)"
              value={d.auditor_execucoes_periodo} color={ORACLE.purple} />
        <Kpi label="Agente execuções (período)"
              value={d.agente_execucoes_periodo} color={ORACLE.purple} />
      </KpiGrid>
      <SubTitle>Auditor IA — ações por tipo</SubTitle>
      <MiniTable rows={d.auditor_por_acao} columns={[
        { key: "acao", label: "Ação" },
        { key: "execucoes", label: "Execuções" },
        { key: "registros_corrigidos", label: "Registros corrigidos" },
      ]} />
      <SubTitle>Agente IA — execuções por ferramenta</SubTitle>
      <MiniTable rows={d.agente_por_ferramenta} columns={[
        { key: "tool", label: "Ferramenta" },
        { key: "qtd", label: "Quantidade" },
      ]} />
      {d.ultimo_relatorio_conselho && (
        <>
          <SubTitle>Último relatório do Conselho IA</SubTitle>
          <JsonView d={d.ultimo_relatorio_conselho} />
        </>
      )}
    </>
  );
}

function ExecutiveReviewView({ d }) {
  const state = STATE_LABEL[d.estado_geral]
    || { label: d.estado_geral, color: "#64748b" };
  return (
    <>
      <div style={{
        background: `${state.color}10`, borderLeft: `4px solid ${state.color}`,
        padding: "12px 14px", borderRadius: 8, marginBottom: 12,
        display: "flex", gap: 10, alignItems: "center",
      }}>
        {d.estado_geral === "saudavel"
          ? <CheckCircle2 size={20} color={state.color} />
          : <AlertTriangle size={20} color={state.color} />}
        <div>
          <div style={{
            fontSize: 9, color: state.color, fontWeight: 800,
            textTransform: "uppercase", letterSpacing: .5,
          }}>Estado geral</div>
          <div style={{
            fontSize: 18, fontWeight: 800, color: state.color,
          }}>{state.label}</div>
        </div>
      </div>
      <SubTitle>Pontos fortes</SubTitle>
      {d.pontos_fortes?.length ? (
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13,
                     color: "#334155", lineHeight: 1.7 }}>
          {d.pontos_fortes.map((p, i) => <li key={i}>{p}</li>)}
        </ul>
      ) : <Empty />}
      <SubTitle>Riscos detectados</SubTitle>
      <MiniTable rows={d.riscos} columns={[
        { key: "area", label: "Área" },
        { key: "descricao", label: "Descrição" },
        { key: "nivel", label: "Nível",
          render: (r) => (
            <span style={{
              background: r.nivel === "alto" ? ORACLE.red
                : r.nivel === "medio" ? ORACLE.orange : "#64748b",
              color: "white", padding: "2px 8px", borderRadius: 10,
              fontSize: 10, fontWeight: 800, textTransform: "uppercase",
              letterSpacing: .5,
            }}>{r.nivel}</span>
          ),
        },
      ]} />
    </>
  );
}

function AnomaliesView({ d }) {
  return (
    <>
      <KpiGrid>
        <Kpi label="Sem plano" value={d.subscribers_sem_plano}
              color={d.subscribers_sem_plano > 0 ? ORACLE.red : ORACLE.green} />
        <Kpi label="Sem preço" value={d.subscribers_sem_preco}
              color={d.subscribers_sem_preco > 0 ? ORACLE.red : ORACLE.green} />
        <Kpi label="Sem CPF" value={d.subscribers_sem_cpf}
              color={d.subscribers_sem_cpf > 0 ? ORACLE.orange : ORACLE.green} />
        <Kpi label="Sem endereço" value={d.subscribers_sem_endereco}
              color={d.subscribers_sem_endereco > 0
                ? ORACLE.orange : ORACLE.green} />
        <Kpi label="Ativos sem CTO" value={d.ativos_sem_cto}
              color={d.ativos_sem_cto > 0 ? ORACLE.orange : ORACLE.green} />
        <Kpi label="Sinal baixo" value={d.ativos_com_sinal_baixo}
              color={d.ativos_com_sinal_baixo > 0
                ? ORACLE.orange : ORACLE.green} />
        <Kpi label="Status fora padrão" value={d.status_fora_do_padrao}
              color={d.status_fora_do_padrao > 0
                ? ORACLE.red : ORACLE.green} />
      </KpiGrid>
      {!!d.emails_duplicados?.length && (
        <>
          <SubTitle>Emails duplicados</SubTitle>
          <MiniTable rows={d.emails_duplicados} columns={[
            { key: "email", label: "Email" },
            { key: "qtd", label: "Ocorrências" },
          ]} />
        </>
      )}
    </>
  );
}
