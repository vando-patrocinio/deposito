import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { thStyle, tdStyle } from "./_constants";

/* =============================================================
   ClosedNotesPdfPopover — popover de configuração do relatório
   (período + modo: finalizadas vs abertas). Ao "gerar", renderiza
   <PrintableReport /> (HTML imprimível via diálogo nativo).
============================================================= */
export function ClosedNotesPdfPopover({ onClose }) {
  const [period, setPeriod] = useState("today");
  const [mode, setMode] = useState("closed"); // "closed" | "open"
  const [start, setStart] = useState(() => {
    const d = new Date(); d.setDate(d.getDate() - 7);
    return d.toISOString().slice(0, 10);
  });
  const [end, setEnd] = useState(() => new Date().toISOString().slice(0, 10));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [reportData, setReportData] = useState(null);

  useEffect(() => {
    const onDoc = (e) => {
      if (reportData) return;
      if (!e.target.closest?.("[data-pdf-pop]")) onClose();
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [onClose, reportData]);

  const generate = async () => {
    setErr(""); setBusy(true);
    try {
      const params = new URLSearchParams({ period, mode });
      if (period === "custom") {
        params.set("start", start);
        params.set("end", end);
      }
      const r = await api._client.get(
        `/lousa/tickets/report/data?${params.toString()}`,
      );
      setReportData(r.data);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha ao gerar relatório");
    } finally { setBusy(false); }
  };

  const handlePrint = () => {
    // Aplica classe temporária pra esconder UI ao redor durante impressão
    document.body.classList.add("lousa-printing");
    window.print();
    // Remove logo após — onafterprint não é confiável em todos navegadores
    setTimeout(() => document.body.classList.remove("lousa-printing"), 500);
  };

  // ===== Modal de relatório HTML imprimível =====
  if (reportData) {
    return (
      <PrintableReport data={reportData} onClose={() => { setReportData(null); onClose(); }}
                       onPrint={handlePrint} />
    );
  }

  // ===== Popover de configuração =====
  return (
    <div data-pdf-pop data-testid="lousa-pdf-popover"
          style={{
            position: "absolute", top: "calc(100% + 6px)", right: 0,
            width: 320, background: "white",
            border: "1px solid #e2e8f0", borderRadius: 10,
            boxShadow: "0 12px 32px rgba(15,23,42,.16)",
            zIndex: 1500, padding: 14,
          }}>
      <div style={{ fontSize: 14, fontWeight: 800, color: "#0f172a",
                      marginBottom: 8 }}>
        Relatório
      </div>
      {/* Seletor Modo: Finalizadas vs Abertas */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                      gap: 6, marginBottom: 10 }}>
        <button data-testid="lousa-pdf-mode-closed"
                onClick={() => setMode("closed")}
                style={{ padding: "10px 8px", borderRadius: 8,
                          border: `1.5px solid ${mode === "closed" ? "#0f766e" : "#e2e8f0"}`,
                          background: mode === "closed" ? "#ecfdf5" : "#fff",
                          color: mode === "closed" ? "#065f46" : "#0f172a",
                          fontSize: 12, fontWeight: 700, cursor: "pointer",
                          textAlign: "center" }}>
          ✓ Notas FINALIZADAS
        </button>
        <button data-testid="lousa-pdf-mode-open"
                onClick={() => setMode("open")}
                style={{ padding: "10px 8px", borderRadius: 8,
                          border: `1.5px solid ${mode === "open" ? "#ea580c" : "#e2e8f0"}`,
                          background: mode === "open" ? "#fff7ed" : "#fff",
                          color: mode === "open" ? "#9a3412" : "#0f172a",
                          fontSize: 12, fontWeight: 700, cursor: "pointer",
                          textAlign: "center" }}>
          Bolhas ABERTAS
        </button>
      </div>
      {mode === "open" && (
        <div style={{ fontSize: 10, color: "#9a3412",
                        background: "#fff7ed",
                        border: "1px solid #fed7aa",
                        borderRadius: 6, padding: 8, marginBottom: 8,
                        lineHeight: 1.4 }}>
          Mostra OS pendentes/em execução agrupadas por técnico (ignora o
          período).
        </div>
      )}
      {mode === "closed" && (
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                      gap: 6, marginBottom: 8 }}>
        {[
          { id: "today", label: "Hoje" },
          { id: "yesterday", label: "Ontem" },
          { id: "week", label: "7 dias" },
          { id: "custom", label: "Período…" },
        ].map((p) => (
          <button key={p.id}
                  data-testid={`lousa-pdf-period-${p.id}`}
                  onClick={() => setPeriod(p.id)}
                  style={{
                    padding: "8px 10px", borderRadius: 8,
                    border: `1.5px solid ${period === p.id ? "#0f172a" : "#e2e8f0"}`,
                    background: period === p.id ? "#0f172a" : "#fff",
                    color: period === p.id ? "#fff" : "#0f172a",
                    fontSize: 12, fontWeight: 700, cursor: "pointer",
                  }}>
            {p.label}
          </button>
        ))}
      </div>
      )}
      {period === "custom" && mode === "closed" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                        gap: 6, marginBottom: 8 }}>
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)}
                  data-testid="lousa-pdf-start"
                  style={{ padding: "6px 8px", border: "1px solid #e2e8f0",
                            borderRadius: 7, fontSize: 12 }} />
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)}
                  data-testid="lousa-pdf-end"
                  style={{ padding: "6px 8px", border: "1px solid #e2e8f0",
                            borderRadius: 7, fontSize: 12 }} />
        </div>
      )}
      {err && (
        <div data-testid="lousa-pdf-err"
              style={{ marginBottom: 8, padding: 8, borderRadius: 6,
                        background: "#fef2f2", color: "#991b1b", fontSize: 11 }}>
          {err}
        </div>
      )}
      <button data-testid="lousa-pdf-generate"
              onClick={generate} disabled={busy}
              style={{ width: "100%", padding: "10px 12px", borderRadius: 8,
                        background: busy ? "#94a3b8"
                            : "linear-gradient(135deg,#0f766e,#0891b2)",
                        color: "#fff", border: 0, fontSize: 13, fontWeight: 700,
                        cursor: busy ? "wait" : "pointer" }}>
        {busy ? "Gerando…" : (mode === "open"
            ? "Visualizar Bolhas Abertas"
            : "Visualizar Finalizadas")}
      </button>

      <ViabilityHeatmapSection />
    </div>
  );
}

/* ---------- ViabilityHeatmapSection — bairros com leads sem cobertura ---- */
function ViabilityHeatmapSection() {
  const [days, setDays] = React.useState(30);
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await api._client.get(
        `/whatsapp-baileys/viability-heatmap?days=${days}`,
      );
      setData(r.data);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [days]);

  React.useEffect(() => { load(); }, [load]);

  const total = data?.total_pending || 0;
  const districts = data?.districts || [];
  const maxLeads = Math.max(1, ...districts.map((d) => d.leads));

  return (
    <div data-testid="viability-heatmap-section" style={{
      marginTop: 14, paddingTop: 12, borderTop: "1px dashed #cbd5e1",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                      marginBottom: 8 }}>
        <span style={{ fontSize: 13 }}>️</span>
        <strong style={{ fontSize: 12.5, color: "#0f172a" }}>
          Demanda sem cobertura
        </strong>
        <span style={{ flex: 1 }} />
        <div style={{ display: "inline-flex", borderRadius: 6,
                        background: "#f1f5f9" }}>
          {[7, 30, 90].map((d) => (
            <button key={d} onClick={() => setDays(d)}
                    data-testid={`viab-range-${d}`}
                    style={{
                      padding: "3px 8px", fontSize: 10, fontWeight: 800,
                      border: "none", cursor: "pointer",
                      background: days === d ? "#0f172a" : "transparent",
                      color: days === d ? "#fff" : "#475569",
                      borderRadius: 6,
                    }}>{d}d</button>
          ))}
        </div>
      </div>

      {loading && (
        <div style={{ fontSize: 11, color: "#94a3b8" }}>Carregando…</div>
      )}

      {!loading && total === 0 && (
        <div data-testid="viab-empty" style={{
          padding: 10, borderRadius: 8, background: "#f8fafc",
          fontSize: 11, color: "#64748b", textAlign: "center",
          lineHeight: 1.5,
        }}>
          Nenhum lead aguardando viabilidade nos últimos {days} dias <br />
          Quando Isabella receber endereços fora da cobertura, eles
          aparecem aqui agrupados por bairro.
        </div>
      )}

      {!loading && total > 0 && (
        <div data-testid="viab-list" style={{ display: "grid", gap: 5 }}>
          <div style={{ fontSize: 11, color: "#475569", marginBottom: 4 }}>
            <strong style={{ color: "#7c3aed" }}>{total}</strong> lead(s)
            esperando expansão em <strong>{data.districts_count}</strong>{" "}
            bairro(s).
          </div>
          {districts.slice(0, 5).map((d) => (
            <div key={d.district}
                  data-testid={`viab-district-${d.district.replace(/\s+/g, '-').toLowerCase()}`}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr auto",
                    gap: 8, padding: "6px 8px", borderRadius: 6,
                    background: "white", border: "1px solid #e2e8f0",
                    alignItems: "center", fontSize: 12,
                  }}>
              <div style={{ display: "flex", flexDirection: "column",
                              gap: 2, minWidth: 0 }}>
                <strong style={{ color: "#0f172a",
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                    whiteSpace: "nowrap",
                                  }}>{d.district}</strong>
                <div style={{
                  height: 5, borderRadius: 3, background: "#f1f5f9",
                  overflow: "hidden",
                }}>
                  <div style={{
                    height: "100%",
                    width: `${(d.leads / maxLeads) * 100}%`,
                    background: "linear-gradient(90deg,#fb7185,#7c3aed)",
                  }} />
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: 15, fontWeight: 800,
                                color: "#7c3aed", lineHeight: 1 }}>
                  {d.leads}
                </div>
                <div style={{ fontSize: 9, color: "#94a3b8" }}>
                  {d.unique_phones} pessoa(s)
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


// ============================================================
// PrintableReport — relatório HTML que abre direto na tela com botão
// "Imprimir" que aciona o diálogo nativo do navegador (escolhe impressora
// OU salva como PDF). Substitui o PDF binário (ReportLab) problemático.
// ============================================================
function PrintableReport({ data, onClose, onPrint }) {
  const isOpen = data?.mode === "open";
  const k = data?.kpis || {};
  const techs = data?.by_tech || [];

  return (
    <div data-testid="lousa-report-modal" className="lousa-report-overlay"
          style={{
            position: "fixed", inset: 0, zIndex: 9999,
            background: "rgba(15,23,42,0.7)",
            display: "flex", alignItems: "center", justifyContent: "center",
            padding: 20,
          }}>
      <div style={{
        background: "#fff", borderRadius: 12,
        width: "min(95vw, 1180px)", height: "min(92vh, 860px)",
        display: "flex", flexDirection: "column", overflow: "hidden",
        boxShadow: "0 20px 60px rgba(0,0,0,0.35)",
      }}>
        {/* Cabeçalho com botões (NÃO imprime) */}
        <div className="no-print"
              style={{ display: "flex", alignItems: "center",
                        justifyContent: "space-between", padding: 14,
                        borderBottom: "1px solid #e2e8f0", flexShrink: 0 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 800, color: "#0f172a" }}>
              {isOpen
                ? "Bolhas Abertas — Pré-visualização"
                : "Notas Finalizadas — Pré-visualização"}
            </div>
            <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
              {isOpen ? "Todas as OS pendentes/em execução" :
                  `Período: ${data?.period_label || "—"}`}
              {" · "}Gerado em {data?.generated_at}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button data-testid="lousa-report-print"
                    onClick={onPrint}
                    style={{ padding: "8px 16px", borderRadius: 8,
                              background: "linear-gradient(135deg,#0f766e,#0891b2)",
                              color: "#fff", border: 0, fontSize: 13,
                              fontWeight: 700, cursor: "pointer",
                              display: "inline-flex", alignItems: "center",
                              gap: 6 }}>
              Imprimir / Salvar PDF
            </button>
            <button data-testid="lousa-report-close"
                    onClick={onClose}
                    style={{ padding: "8px 14px", borderRadius: 8,
                              background: "#fff", border: "1px solid #cbd5e1",
                              color: "#475569", fontSize: 12, fontWeight: 700,
                              cursor: "pointer" }}>
              ✕ Fechar
            </button>
          </div>
        </div>

        {/* Área imprimível */}
        <div id="lousa-report-printable" data-testid="lousa-report-content"
              style={{ flex: 1, overflow: "auto", padding: "20px 28px",
                        background: "#fff", color: "#0f172a",
                        fontFamily: "Helvetica, Arial, sans-serif" }}>
          {/* Título grande no topo da impressão */}
          <h1 style={{ fontSize: 20, fontWeight: 800, margin: "0 0 4px",
                          color: "#0f172a" }}>
            {isOpen
              ? "Serviços em ABERTO (bolhas ativas)"
              : "Fechamento de Notas (Lousa)"}
          </h1>
          <div style={{ fontSize: 11, color: "#64748b",
                          marginBottom: 14, borderBottom: "2px solid #0f172a",
                          paddingBottom: 8 }}>
            {isOpen
              ? `Total: ${data.total} bolhas pendentes`
              : `Período: ${data.period_label} · Total: ${data.total} notas`}
            {" · "}Gerado em {data.generated_at}
          </div>

          {/* KPIs */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)",
                          gap: 8, marginBottom: 16 }}>
            {[
              { label: "Total", value: k.total },
              { label: "Fechamento\ninterno (gestor)", value: k.internal_close },
              { label: "Instalações", value: k.instalacao },
              { label: "Reparos", value: k.reparo },
              { label: "Retiradas", value: k.retirada },
            ].map((kpi, i) => (
              <div key={i} style={{
                border: "1px solid #cbd5e1", borderRadius: 6,
                background: "#f8fafc", padding: "12px 8px",
                textAlign: "center", whiteSpace: "pre-line",
              }}>
                <div style={{ fontSize: 10, color: "#475569",
                                fontWeight: 600 }}>{kpi.label}</div>
                <div style={{ fontSize: 22, color: "#0f172a",
                                fontWeight: 800, marginTop: 4 }}>
                  {kpi.value ?? 0}
                </div>
              </div>
            ))}
          </div>

          {/* Por técnico */}
          {techs.map((t) => (
            <PrintableTechBlock key={t.name} tech={t} isOpen={isOpen} />
          ))}
        </div>
      </div>
    </div>
  );
}

function PrintableTechBlock({ tech, isOpen }) {
  const n = tech.count;
  if (n === 0) {
    return (
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 13, color: "#94a3b8" }}>
          <b>{tech.name}</b> ·{" "}
          <i>{isOpen ? "0 bolhas abertas" : "0 notas finalizadas"} no período</i> 
        </div>
      </div>
    );
  }
  const accent = isOpen ? "#ea580c" : "#0f766e";
  return (
    <div style={{ marginBottom: 18, pageBreakInside: "avoid" }}>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6,
                      color: "#0f172a" }}>
        {tech.name} ·{" "}
        <span style={{ color: accent, fontWeight: 800 }}>
          {n} {isOpen
              ? (n > 1 ? "bolhas abertas" : "bolha aberta")
              : (n > 1 ? "notas finalizadas" : "nota finalizada")}
        </span>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse",
                        fontSize: 10, tableLayout: "fixed" }}>
        <thead>
          <tr style={{ background: "#0f172a", color: "#fff" }}>
            {isOpen
              ? ["#", "Aberta em", "Agendada", "Cliente", "Tipo", "Prio",
                  "Status", "Endereço"].map((h) => (
                <th key={h} style={thStyle}>{h}</th>))
              : ["#", "Fechada em", "Cliente", "Tipo", "Sinal",
                  "CTO · Porta", "O que foi feito", "Origem"].map((h) => (
                <th key={h} style={thStyle}>{h}</th>))
            }
          </tr>
        </thead>
        <tbody>
          {tech.tickets.map((r, i) => (
            <PrintableTicketRow key={r.id || i} row={r} idx={i + 1} isOpen={isOpen} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PrintableTicketRow({ row, idx, isOpen }) {
  const cs = row.client_snapshot || {};
  const cd = row.completion_data || {};
  const isInternal = row.admin_action === "encerrar";
  const stripe = idx % 2 === 0 ? "#f8fafc" : "#fff";

  if (isOpen) {
    const created = (row.created_at || "").slice(0, 16).replace("T", " ");
    const sched = (row.scheduled_date || "") +
                  (row.scheduled_time ? ` ${row.scheduled_time}` : "");
    return (
      <tr style={{ background: stripe }}>
        <td style={{ ...tdStyle, textAlign: "center" }}>{idx}</td>
        <td style={tdStyle}>{created}</td>
        <td style={tdStyle}>{sched || "—"}</td>
        <td style={tdStyle}>{cs.name || "—"}</td>
        <td style={tdStyle}>{row.type || "—"}</td>
        <td style={tdStyle}>{row.priority || "—"}</td>
        <td style={tdStyle}>{row.status || "—"}</td>
        <td style={tdStyle}>{cs.address || "—"}</td>
      </tr>
    );
  }

  // Mostra fechamento no fuso local do navegador (BRT para usuários no
  // Brasil), espelhando a hora do SmartOLT no celular. O backend grava
  // em UTC; aqui convertemos para exibição.
  const closedAt = row.closed_at
    ? (() => {
        try {
          const d = new Date(row.closed_at);
          if (Number.isNaN(d.getTime())) return "";
          return d.toLocaleString("pt-BR", {
            dateStyle: "short", timeStyle: "short",
          });
        } catch { return row.closed_at.slice(0, 16).replace("T", " "); }
      })()
    : "";
  const sinal = cd.sinal;
  const sinalStr = typeof sinal === "number" ? `${sinal.toFixed(1)} dBm` : "—";
  let ctoStr = "—";
  if (cd.cto_name) {
    ctoStr = cd.cto_name;
    if (cd.cto_port_number) ctoStr += ` · P${cd.cto_port_number}`;
    if (cd.cto_splitter) ctoStr += ` · ${cd.cto_splitter}`;
    if (cd.cto_vlan) ctoStr += ` · VLAN ${cd.cto_vlan}`;
  }
  const doneParts = [];
  if (cd.ont) doneParts.push(<><b>ONT:</b> {cd.ont}</>);
  if (cd.drop) doneParts.push(<><b>Drop:</b> {cd.drop}m</>);
  if (cd.esticador) doneParts.push(<><b>Est:</b> {cd.esticador}</>);
  if (cd.conectores) doneParts.push(<><b>Con:</b> {cd.conectores}</>);
  if (cd.backbone) doneParts.push(<><b>Bb:</b> {cd.backbone}m</>);
  const fotos = (cd.fotos || []).filter(Boolean).length;
  if (fotos) doneParts.push(`${fotos} foto${fotos > 1 ? "s" : ""}`);
  if (cd.ping_summary) doneParts.push(<><b>Ping:</b> {String(cd.ping_summary).slice(0, 60)}</>);
  if (cd.observacoes) doneParts.push(<><b>Obs:</b> {String(cd.observacoes).slice(0, 140)}</>);
  if (row.outcome) doneParts.push(<><b>Result:</b> {row.outcome}</>);

  return (
    <tr style={{ background: stripe }}>
      <td style={{ ...tdStyle, textAlign: "center" }}>{idx}</td>
      <td style={tdStyle}>{closedAt}</td>
      <td style={tdStyle}>{cs.name || "—"}</td>
      <td style={tdStyle}>{row.type || "—"}</td>
      <td style={{ ...tdStyle, textAlign: "center" }}>{sinalStr}</td>
      <td style={tdStyle}>{ctoStr}</td>
      <td style={tdStyle}>
        {doneParts.length === 0 ? "—" : doneParts.map((p, i) => (
          <React.Fragment key={i}>{p}{i < doneParts.length - 1 ? " · " : ""}</React.Fragment>
        ))}
      </td>
      <td style={{ ...tdStyle, textAlign: "center",
                    background: isInternal ? "#fef3c7" : undefined,
                    color: isInternal ? "#92400e" : undefined,
                    fontWeight: isInternal ? 700 : 400 }}>
        {isInternal ? "Gestor" : "Técnico"}
      </td>
    </tr>
  );
}
