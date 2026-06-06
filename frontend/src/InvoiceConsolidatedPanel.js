/* InvoiceConsolidatedPanel — iter203 — Visão consolidada por Nota Fiscal.
 *
 * Agrupa compras pelo par (fornecedor, número da NF) em cards expansíveis.
 * Cada card mostra:
 *   - Header: fornecedor · NF · data · total consolidado · N lançamentos
 *   - Breakdown por tipo: 5 ONTs + 5 insumos + 2 ferramentas (badges coloridas)
 *   - Lista de purchases ao expandir (clicar abre detalhes individuais)
 *
 * Útil para conciliação fiscal e disputas: 1 NF que virou 3 compras
 * (iter202 multi-tipo) reaparece aqui como UMA NF.
 */
import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { Loader2, ChevronDown, ChevronRight, Receipt, Wrench, Package2, Cable, Boxes } from "lucide-react";

const TYPE_META = {
  ont: { color: "#1d4ed8", bg: "#dbeafe", label: "ONTs", icon: Receipt },
  insumo: { color: "#15803d", bg: "#dcfce7", label: "Insumos", icon: Cable },
  ferramenta: { color: "#92400e", bg: "#fef3c7", label: "Ferramentas", icon: Wrench },
  equipamento: { color: "#7c3aed", bg: "#ede9fe", label: "Equipamentos", icon: Package2 },
  outros: { color: "#475569", bg: "#f1f5f9", label: "Outros", icon: Boxes },
};

const STATUS_META = {
  confirmed: { color: "#15803d", bg: "#dcfce7", label: "Confirmada" },
  received: { color: "#1d4ed8", bg: "#dbeafe", label: "Recebida" },
  pending: { color: "#92400e", bg: "#fef3c7", label: "Pendente" },
};

function fmtBRL(v) {
  if (v == null) return "—";
  return Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function fmtDate(s) {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleDateString("pt-BR");
  } catch { return s; }
}

export default function InvoiceConsolidatedPanel() {
  const [data, setData] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [expanded, setExpanded] = useState(new Set());

  async function load() {
    setLoading(true);
    try {
      const r = await api.purchasesByInvoice({ limit: 120 });
      setData(r || { items: [], total: 0 });
    } finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => {
    const q = filter.toLowerCase().trim();
    if (!q) return data.items;
    return data.items.filter((it) =>
      (it.supplier_name || "").toLowerCase().includes(q)
      || (it.invoice_number || "").toLowerCase().includes(q),
    );
  }, [data.items, filter]);

  const toggle = (key) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: "#64748b" }}>
        <Loader2 size={20} className="animate-spin" style={{ display: "inline" }} />
        <div style={{ marginTop: 8, fontSize: 13 }}>Carregando notas fiscais consolidadas…</div>
      </div>
    );
  }

  return (
    <div data-testid="invoice-consolidated-panel"
          style={{ background: "white", borderRadius: 14,
                    border: "1px solid #e2e8f0", padding: 20 }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between",
                     alignItems: "center", marginBottom: 14, gap: 12 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 17, fontWeight: 800, color: "#0f172a" }}>
            Notas Fiscais (visão consolidada)
          </h3>
          <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
            {data.total} nota(s) — cada NF agrupa todos os lançamentos relacionados.
            Útil para conciliação fiscal e disputas com fornecedor.
          </div>
        </div>
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          data-testid="invoice-filter"
          placeholder="Buscar fornecedor ou nº NF…"
          style={{ padding: "8px 12px", border: "1px solid #cbd5e1",
                    borderRadius: 8, fontSize: 13, width: 280 }} />
      </div>

      {filtered.length === 0 ? (
        <div style={{ padding: 28, textAlign: "center", color: "#94a3b8",
                       background: "#f8fafc", border: "1px dashed #cbd5e1",
                       borderRadius: 10 }}>
          {filter ? "Nenhuma NF encontrada." : "Nenhuma NF cadastrada ainda."}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {filtered.map((nf) => {
            const key = `${nf.supplier_name}::${nf.invoice_number}`;
            const isOpen = expanded.has(key);
            const statusMeta = STATUS_META[nf.global_status] || STATUS_META.confirmed;
            const totalItems = Object.values(nf.types_summary || {})
              .reduce((s, n) => s + n, 0);
            return (
              <div key={key} data-testid={`nf-card-${nf.invoice_number}`}
                    style={{ border: "1px solid #e2e8f0", borderRadius: 10,
                              background: isOpen ? "#f8fafc" : "white",
                              overflow: "hidden",
                              transition: "background .15s" }}>
                {/* Card header (clickable) */}
                <div onClick={() => toggle(key)}
                      style={{ padding: 14, cursor: "pointer",
                                display: "grid",
                                gridTemplateColumns: "auto 1fr auto auto",
                                gap: 14, alignItems: "center" }}>
                  {isOpen
                    ? <ChevronDown size={18} color="#64748b" />
                    : <ChevronRight size={18} color="#64748b" />}
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 14, fontWeight: 800, color: "#0f172a" }}>
                      {nf.supplier_name}
                    </div>
                    <div style={{ fontSize: 12, color: "#475569", marginTop: 2,
                                    fontFamily: "monospace" }}>
                      NF {nf.invoice_number} · {fmtDate(nf.invoice_date)}
                    </div>
                    {/* Badges por tipo */}
                    <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
                      {Object.entries(nf.types_summary || {}).map(([t, n]) => {
                        const meta = TYPE_META[t] || TYPE_META.outros;
                        const Icon = meta.icon;
                        return (
                          <span key={t}
                                style={{ display: "inline-flex", alignItems: "center",
                                          gap: 4, padding: "2px 8px", borderRadius: 999,
                                          background: meta.bg, color: meta.color,
                                          fontSize: 11, fontWeight: 700 }}>
                            <Icon size={11} /> {n} {meta.label}
                          </span>
                        );
                      })}
                    </div>
                  </div>
                  <div style={{ textAlign: "right", minWidth: 80 }}>
                    <div style={{ fontSize: 9, color: "#94a3b8", fontWeight: 700,
                                    textTransform: "uppercase", letterSpacing: 0.4 }}>
                      Total
                    </div>
                    <div style={{ fontSize: 16, fontWeight: 900, color: "#0f172a" }}>
                      {fmtBRL(nf.total_value)}
                    </div>
                  </div>
                  <div style={{ textAlign: "right", display: "flex",
                                  flexDirection: "column", gap: 4, alignItems: "flex-end" }}>
                    <span style={{ padding: "3px 10px", borderRadius: 999,
                                    background: statusMeta.bg, color: statusMeta.color,
                                    fontSize: 10, fontWeight: 800 }}>
                      {statusMeta.label}
                    </span>
                    <span style={{ fontSize: 11, color: "#64748b", fontWeight: 600 }}>
                      {nf.count} lançamento{nf.count !== 1 ? "s" : ""} · {totalItems} item{totalItems !== 1 ? "s" : ""}
                    </span>
                  </div>
                </div>

                {/* Expanded body */}
                {isOpen && (
                  <div style={{ background: "white",
                                  borderTop: "1px solid #e2e8f0", padding: 12 }}>
                    <table style={{ width: "100%", fontSize: 12 }}>
                      <thead>
                        <tr style={{ textAlign: "left", color: "#64748b",
                                      fontSize: 10, textTransform: "uppercase",
                                      letterSpacing: 0.4 }}>
                          <th style={{ padding: 6 }}>#</th>
                          <th style={{ padding: 6 }}>Tipo</th>
                          <th style={{ padding: 6 }}>Items</th>
                          <th style={{ padding: 6 }}>Valor</th>
                          <th style={{ padding: 6 }}>Praça</th>
                          <th style={{ padding: 6 }}>Status</th>
                          <th style={{ padding: 6 }}>Confirmada</th>
                        </tr>
                      </thead>
                      <tbody>
                        {nf.purchases.map((p, i) => {
                          const tMeta = TYPE_META[p.type] || TYPE_META.outros;
                          const sMeta = STATUS_META[p.status] || STATUS_META.confirmed;
                          return (
                            <tr key={p.id}
                                style={{ borderBottom: "1px solid #f1f5f9" }}>
                              <td style={{ padding: 6, color: "#94a3b8",
                                            fontFamily: "monospace" }}>{i + 1}</td>
                              <td style={{ padding: 6 }}>
                                <span style={{ padding: "2px 8px", borderRadius: 4,
                                                background: tMeta.bg, color: tMeta.color,
                                                fontSize: 10, fontWeight: 700 }}>
                                  {tMeta.label}
                                </span>
                              </td>
                              <td style={{ padding: 6, color: "#475569" }}>
                                {p.items_count}
                              </td>
                              <td style={{ padding: 6, fontWeight: 700, color: "#0f172a" }}>
                                {fmtBRL(p.total_value)}
                              </td>
                              <td style={{ padding: 6, color: "#475569" }}>
                                {p.praca_name || "—"}
                              </td>
                              <td style={{ padding: 6 }}>
                                <span style={{ padding: "2px 8px", borderRadius: 4,
                                                background: sMeta.bg, color: sMeta.color,
                                                fontSize: 10, fontWeight: 700 }}>
                                  {sMeta.label}
                                </span>
                              </td>
                              <td style={{ padding: 6, color: "#64748b", fontSize: 11 }}>
                                {p.confirmed_at ? fmtDate(p.confirmed_at) : "—"}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                    {nf.purchases[0]?.file_name && (
                      <div style={{ marginTop: 10, padding: 8,
                                      background: "#f8fafc", borderRadius: 6,
                                      fontSize: 11, color: "#475569" }}>
                        Arquivo original: <strong>{nf.purchases[0].file_name}</strong>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
