/* OntBatchHistoryPanel.js — Histórico de retiradas em lote (Scan IA).
 *
 * Tela admin com filtros (técnico, período) + listagem paginada +
 * botão "Exportar PDF" para auditoria.
 *
 * Endpoint: GET /api/stok/retirada/batch-history
 *           GET /api/stok/retirada/batch-history/pdf
 */
import React, { useEffect, useState, useCallback } from "react";
import {
  Calendar, Download, Filter, RefreshCw, Users, Package, Layers,
} from "lucide-react";
import { api } from "@/api";

const card = {
  padding: 16, borderRadius: 12, border: "1px solid var(--border-default)",
  background: "var(--bg-surface)",
};
const input = {
  width: "100%", padding: "8px 10px", borderRadius: 8,
  border: "1px solid var(--border-default)", background: "var(--bg-surface)",
  color: "var(--text-primary)", fontSize: 13,
};
const btnPrimary = {
  padding: "8px 14px", borderRadius: 8, border: 0,
  background: "linear-gradient(135deg,#0d9488,#06b6d4)",
  color: "#fff", fontWeight: 700, fontSize: 13, cursor: "pointer",
};
const btnGhost = {
  padding: "6px 10px", borderRadius: 8,
  border: "1px solid var(--border-default)",
  background: "transparent", color: "var(--text-primary)",
  fontSize: 12, cursor: "pointer",
};

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  } catch { return iso; }
}

export default function OntBatchHistoryPanel() {
  const [items, setItems] = useState([]);
  const [totals, setTotals] = useState({ total_batches: 0, total_onts: 0, total_pending_with_tech: 0 });
  const [loading, setLoading] = useState(false);
  const [collabs, setCollabs] = useState([]);
  const [filters, setFilters] = useState({
    technician_id: "",
    since: "",
    until: "",
    only_pending: false,  // iter173
  });
  // iter172 — expansão por lote: id -> {loading, data, err}
  const [expanded, setExpanded] = useState({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (filters.technician_id) params.technician_id = filters.technician_id;
      if (filters.since) params.since = filters.since + "T00:00:00";
      if (filters.until) params.until = filters.until + "T23:59:59";
      if (filters.only_pending) params.only_pending = true;
      const r = await api.scanOntBatchHistory(params);
      setItems(r?.items || []);
      setTotals({
        total_batches: r?.total_batches || 0,
        total_onts: r?.total_onts || 0,
        total_pending_with_tech: r?.total_pending_with_tech || 0,
      });
    } catch (e) {
      console.error("[batch-history] load fail", e);
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => { load(); }, [load]);

  // Carrega colaboradores para o dropdown
  useEffect(() => {
    api.stokTechnicians().then((r) => {
      const arr = Array.isArray(r) ? r : (r?.items || []);
      setCollabs(arr);
    }).catch(() => setCollabs([]));
  }, []);

  const downloadPdf = async () => {
    try {
      const params = {};
      if (filters.technician_id) params.technician_id = filters.technician_id;
      if (filters.since) params.since = filters.since + "T00:00:00";
      if (filters.until) params.until = filters.until + "T23:59:59";
      const blob = await api.scanOntBatchHistoryPdf(params);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `retiradas_lote_${new Date().toISOString().slice(0,10)}.pdf`;
      document.body.appendChild(a); a.click();
      setTimeout(() => {
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
      }, 1000);
    } catch (e) {
      alert("Erro ao gerar PDF: " + (e?.response?.data?.detail || e.message));
    }
  };

  // iter172 — expandir/recolher lote e carregar detalhes sob demanda
  const toggleExpand = async (batch) => {
    const id = batch.id;
    if (!id) {
      alert("Este lote é antigo e não tem ID — não há como detalhar as ONTs.");
      return;
    }
    if (expanded[id]?.data || expanded[id]?.loading) {
      setExpanded((p) => ({ ...p, [id]: { ...p[id], open: !p[id].open } }));
      return;
    }
    setExpanded((p) => ({ ...p, [id]: { loading: true, open: true } }));
    try {
      const r = await api._client.get(`/stok/retirada/batch-history/${id}/items`)
                       .then((x) => x.data);
      setExpanded((p) => ({ ...p, [id]: { loading: false, open: true, data: r } }));
    } catch (e) {
      setExpanded((p) => ({ ...p, [id]: {
        loading: false, open: true,
        err: e?.response?.data?.detail || e.message,
      } }));
    }
  };

  return (
    <div data-testid="ont-batch-history" style={{ display: "grid", gap: 16 }}>
      {/* Header */}
      <div style={{
        ...card,
        background: "linear-gradient(135deg, var(--accent-soft) 0%, var(--bg-surface) 60%)",
        display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
      }}>
        <div style={{
          width: 48, height: 48, borderRadius: 12,
          background: "linear-gradient(135deg,#0d9488,#06b6d4)",
          color: "#fff", display: "grid", placeItems: "center", flexShrink: 0,
        }}>
          <Layers size={24} strokeWidth={1.75} />
        </div>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ fontWeight: 800, fontSize: 16 }}>Retiradas em Lote</div>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
            Histórico de ONTs catalogadas via Scan IA Claude 4.6 — auditoria mensal de retiradas em massa.
          </div>
        </div>
        <button data-testid="batch-history-pdf" style={btnPrimary} onClick={downloadPdf}
                disabled={loading || items.length === 0}>
          <Download size={14} style={{ display: "inline", marginRight: 6, verticalAlign: -2 }} />
          Exportar PDF
        </button>
        <button data-testid="batch-history-refresh" style={btnGhost} onClick={load} title="Recarregar">
          <RefreshCw size={14} />
        </button>
      </div>

      {/* Filtros */}
      <div style={card}>
        <div style={{ fontWeight: 800, fontSize: 13, marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
          <Filter size={14} /> Filtros
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
          <div>
            <label style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)" }}>
              <Users size={11} style={{ display: "inline", marginRight: 4, verticalAlign: -1 }} />
              Técnico
            </label>
            <select data-testid="filter-technician" style={input}
                       value={filters.technician_id}
                       onChange={(e) => setFilters((p) => ({ ...p, technician_id: e.target.value }))}>
              <option value="">Todos</option>
              {collabs.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)" }}>
              <Calendar size={11} style={{ display: "inline", marginRight: 4, verticalAlign: -1 }} />
              De
            </label>
            <input data-testid="filter-since" type="date" style={input}
                    value={filters.since}
                    onChange={(e) => setFilters((p) => ({ ...p, since: e.target.value }))} />
          </div>
          <div>
            <label style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)" }}>
              <Calendar size={11} style={{ display: "inline", marginRight: 4, verticalAlign: -1 }} />
              Até
            </label>
            <input data-testid="filter-until" type="date" style={input}
                    value={filters.until}
                    onChange={(e) => setFilters((p) => ({ ...p, until: e.target.value }))} />
          </div>
          {/* iter173 — Toggle: apenas lotes com ONTs ainda no técnico */}
          <div style={{ display: "flex", alignItems: "flex-end" }}>
            <label data-testid="filter-only-pending-label"
                     style={{
                       display: "flex", alignItems: "center", gap: 6,
                       padding: "8px 12px", borderRadius: 8,
                       cursor: "pointer", userSelect: "none",
                       background: filters.only_pending ? "#fff7ed" : "var(--bg-surface)",
                       border: `1.5px solid ${filters.only_pending ? "#fb923c" : "var(--border-default)"}`,
                       fontSize: 12, fontWeight: 700,
                       color: filters.only_pending ? "#9a3412" : "var(--text-primary)",
                     }}>
              <input type="checkbox"
                       data-testid="filter-only-pending"
                       checked={filters.only_pending}
                       onChange={(e) => setFilters((p) => ({ ...p, only_pending: e.target.checked }))} />
              Só com ONTs no técnico
            </label>
          </div>
        </div>
      </div>

      {/* Totais agregados */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
        <div style={{ ...card, textAlign: "center" }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 700 }}>LOTES</div>
          <div data-testid="total-batches" style={{ fontSize: 28, fontWeight: 800, color: "#0d9488" }}>
            {totals.total_batches}
          </div>
        </div>
        <div style={{ ...card, textAlign: "center" }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 700 }}>ONTS CATALOGADAS</div>
          <div data-testid="total-onts" style={{ fontSize: 28, fontWeight: 800, color: "#0e7490" }}>
            {totals.total_onts}
          </div>
        </div>
        <div style={{ ...card, textAlign: "center",
                          borderLeft: "3px solid #fb923c" }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 700 }}>
            NO TÉCNICO (pendente)
          </div>
          <div data-testid="total-pending"
                style={{ fontSize: 28, fontWeight: 800,
                             color: totals.total_pending_with_tech > 0 ? "#c2410c" : "#16a34a" }}>
            {totals.total_pending_with_tech}
          </div>
        </div>
      </div>

      {/* Lista */}
      <div style={card}>
        <div style={{ fontWeight: 800, fontSize: 14, marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
          <Package size={16} /> Lotes ({items.length})
        </div>
        {loading ? (
          <div style={{ padding: 20, textAlign: "center", color: "var(--text-muted)" }}>
            Carregando…
          </div>
        ) : items.length === 0 ? (
          <div data-testid="batch-empty" style={{ padding: 24, textAlign: "center", color: "var(--text-muted)" }}>
            Nenhum lote no filtro selecionado.
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ textAlign: "left", color: "var(--text-muted)", borderBottom: "1px solid var(--border-default)" }}>
                  <th style={{ padding: "8px 6px", width: 30 }}></th>
                  <th style={{ padding: "8px 6px" }}>Data</th>
                  <th style={{ padding: "8px 6px" }}>Retirado por (Técnico)</th>
                  <th style={{ padding: "8px 6px" }}>Agendado por (Operador)</th>
                  <th style={{ padding: "8px 6px", textAlign: "center" }}>Criadas</th>
                  <th style={{ padding: "8px 6px", textAlign: "center" }}>Movidas</th>
                  <th style={{ padding: "8px 6px" }}>Motivo</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it, i) => {
                  const id = it.id;
                  const exp = id ? expanded[id] : null;
                  const isOpen = !!exp?.open;
                  return (
                  <React.Fragment key={i}>
                    <tr data-testid={`batch-row-${i}`}
                          onClick={() => toggleExpand(it)}
                          style={{ borderBottom: "1px solid var(--border-default)",
                                       cursor: "pointer",
                                       background: isOpen ? "var(--bg-surface-2)" : undefined }}>
                      <td style={{ padding: "8px 6px", fontWeight: 700,
                                       color: "#0d9488", fontSize: 14 }}>
                        {isOpen ? "▾" : "▸"}
                      </td>
                      <td style={{ padding: "8px 6px" }}>{fmtDate(it.at)}</td>
                      <td style={{ padding: "8px 6px", fontWeight: 700 }}>
                        {it.technician_name || it.technician_id || "—"}
                      </td>
                      <td style={{ padding: "8px 6px", color: "var(--text-muted)" }}>
                        {it.by_name || it.by_email || "—"}
                      </td>
                      <td style={{ padding: "8px 6px", textAlign: "center" }}>
                        <span style={{
                          padding: "2px 8px", borderRadius: 999,
                          background: "#dcfce7", color: "#15803d", fontWeight: 700,
                        }}>{it.created || 0}</span>
                      </td>
                      <td style={{ padding: "8px 6px", textAlign: "center" }}>
                        <span style={{
                          padding: "2px 8px", borderRadius: 999,
                          background: "#dbeafe", color: "#1e40af", fontWeight: 700,
                        }}>{it.moved || 0}</span>
                      </td>
                      <td style={{ padding: "8px 6px", color: "var(--text-muted)" }}>
                        {it.reason || "—"}
                        {it.pending_with_tech > 0 && (
                          <div style={{ marginTop: 4 }}>
                            <span style={{
                              display: "inline-block",
                              padding: "2px 8px", borderRadius: 999,
                              background: "#fff7ed", color: "#c2410c",
                              border: "1px solid #fdba74",
                              fontSize: 10, fontWeight: 700,
                            }}>{it.pending_with_tech} no técnico</span>
                          </div>
                        )}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr data-testid={`batch-detail-${i}`}>
                        <td colSpan={7} style={{ padding: 0,
                                                       background: "var(--bg-surface-2)",
                                                       borderBottom: "1px solid var(--border-default)" }}>
                          <BatchDetail exp={exp} />
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// iter172 — Detalhes do lote (linha expansível)
const STATUS_META = {
  instalada: { label: "Instalada", bg: "#dcfce7", color: "#15803d" },
  em_estoque: { label: "Em estoque", bg: "#dbeafe", color: "#1e40af" },
  defeito: { label: "Defeito", bg: "#fee2e2", color: "#991b1b" },
  removida_smartolt: { label: "Removida do SmartOLT", bg: "#f3e8ff", color: "#6b21a8" },
  desconhecido: { label: "—", bg: "#f1f5f9", color: "#64748b" },
};

function BatchDetail({ exp }) {
  if (exp?.loading) {
    return <div style={{ padding: 14, color: "var(--text-muted)" }}>Carregando ONTs do lote…</div>;
  }
  if (exp?.err) {
    return <div style={{ padding: 14, color: "#dc2626" }}>Erro: {exp.err}</div>;
  }
  const data = exp?.data;
  if (!data) return null;
  if (data.note) {
    return <div style={{ padding: 14, color: "var(--text-muted)", fontStyle: "italic" }}>{data.note}</div>;
  }
  const s = data.summary || {};
  return (
    <div style={{ padding: 14 }}>
      {/* Mini-resumo do lote */}
      <div style={{
        display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10,
        fontSize: 11, fontWeight: 700,
      }}>
        <Tag bg="#dcfce7" color="#15803d" label={`✅ Instaladas: ${s.instaladas || 0}`} />
        <Tag bg="#dbeafe" color="#1e40af" label={`Em estoque: ${s.em_estoque || 0}`} />
        <Tag bg="#fee2e2" color="#991b1b" label={`Defeito: ${s.defeito || 0}`} />
        <Tag bg="#f3e8ff" color="#6b21a8" label={`Removidas: ${s.removida_smartolt || 0}`} />
      </div>

      <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", color: "var(--text-muted)",
                          borderBottom: "1px solid var(--border-default)" }}>
            <th style={{ padding: "6px 4px" }}>SN</th>
            <th style={{ padding: "6px 4px" }}>MAC</th>
            <th style={{ padding: "6px 4px" }}>Status atual</th>
            <th style={{ padding: "6px 4px" }}>Cliente / PPPoE</th>
            <th style={{ padding: "6px 4px" }}>Instalado por</th>
            <th style={{ padding: "6px 4px" }}>Quando</th>
          </tr>
        </thead>
        <tbody>
          {(data.items || []).map((it, i) => {
            const meta = STATUS_META[it.status_current] || STATUS_META.desconhecido;
            return (
              <tr key={i} data-testid={`batch-ont-${i}`}
                  style={{ borderBottom: "1px solid var(--border-default)" }}>
                <td style={{ padding: "6px 4px", fontFamily: "monospace", fontWeight: 700 }}>
                  {it.sn || "—"}
                </td>
                <td style={{ padding: "6px 4px", fontFamily: "monospace" }}>
                  {it.mac || "—"}
                </td>
                <td style={{ padding: "6px 4px" }}>
                  <Tag bg={meta.bg} color={meta.color} label={meta.label} />
                </td>
                <td style={{ padding: "6px 4px" }}>
                  {it.status_current === "instalada" ? (
                    <>
                      <div style={{ fontWeight: 700 }}>{it.current_client_name || "—"}</div>
                      {it.pppoe_user && (
                        <div style={{ fontFamily: "monospace",
                                          fontSize: 10, color: "#0d9488" }}>
                          PPPoE: {it.pppoe_user}
                        </div>
                      )}
                    </>
                  ) : "—"}
                </td>
                <td style={{ padding: "6px 4px", color: "var(--text-muted)" }}>
                  {it.installed_by || "—"}
                </td>
                <td style={{ padding: "6px 4px", color: "var(--text-muted)" }}>
                  {it.installed_at ? fmtDate(it.installed_at) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Tag({ bg, color, label }) {
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 999,
      background: bg, color, fontWeight: 700, fontSize: 11,
    }}>{label}</span>
  );
}
