/**
 * V16.1 — Componentes reutilizáveis para mostrar QUE cliente pagou.
 *
 * Usados em:
 *   • FinanceiroAnalyticsChart.js (painel financeiro principal)
 *   • WatchtowerRecebimentos.jsx (Dashboard Executivo — visão CEO)
 *
 * Backend endpoints:
 *   • GET /api/financeiro/analytics → top_payers + unique_payers_count
 *   • GET /api/financeiro/payers    → drill-down detalhado por cliente
 */
import React, { useEffect, useState } from "react";
import { api } from "@/api";

const fmtMoney = (v) =>
  Number(v || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL",
  });


/**
 * Card lateral compacto: top 10 pagadores do período + contagem.
 *
 * Props:
 *   topPayers: array do endpoint /analytics
 *   uniqueCount: int (unique_payers_count)
 *   period: string label (ex: "2026-06-01 → 2026-06-18")
 *   onOpenFullList: callback para abrir o modal
 *   compact: bool — versão menor pra Watchtower
 */
export function TopPayersPanel({ topPayers, uniqueCount, period,
                                  onOpenFullList, compact = false }) {
  const showCount = compact ? 5 : 10;
  return (
    <div data-testid="top-payers-panel" style={{
      marginTop: compact ? 12 : 18, padding: compact ? 12 : 16,
      borderRadius: 10, background: "#fff",
      border: "1px solid #e2e8f0",
    }}>
      <div style={{ display: "flex", alignItems: "center",
                    justifyContent: "space-between", marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>
            Top {showCount} Pagadores — quem pagou no período
          </div>
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
            {uniqueCount} clientes únicos pagaram {period && `entre ${period}`}
          </div>
        </div>
        {onOpenFullList && (
          <button
            data-testid="open-full-payers-list"
            onClick={onOpenFullList}
            style={{
              padding: "6px 12px", borderRadius: 6,
              background: "#0e7490", color: "#fff",
              fontSize: 12, fontWeight: 600,
              border: "none", cursor: "pointer",
            }}>
            Ver lista completa
          </button>
        )}
      </div>
      <div style={{ display: "grid",
                    gridTemplateColumns: "1fr 100px 90px",
                    gap: 6, fontSize: 12 }}>
        <div style={{ fontWeight: 700, color: "#64748b",
                       textTransform: "uppercase", fontSize: 10 }}>Cliente</div>
        <div style={{ fontWeight: 700, color: "#64748b",
                       textTransform: "uppercase", fontSize: 10,
                       textAlign: "right" }}>Valor</div>
        <div style={{ fontWeight: 700, color: "#64748b",
                       textTransform: "uppercase", fontSize: 10,
                       textAlign: "center" }}>Faturas</div>
        {(topPayers || []).slice(0, showCount).map((p, i) => (
          <React.Fragment key={(p.subscriber_external_id || "") + i}>
            <div data-testid={`payer-name-${i}`}
                 style={{ color: "#0f172a", padding: "6px 0",
                          borderTop: i > 0 ? "1px solid #f1f5f9" : "none",
                          whiteSpace: "nowrap", overflow: "hidden",
                          textOverflow: "ellipsis" }}>
              <span style={{ fontWeight: 700, color: "#0e7490",
                              marginRight: 6 }}>{i + 1}º</span>
              {p.subscriber_name}
            </div>
            <div style={{ color: "#16a34a", fontWeight: 600,
                          textAlign: "right", padding: "6px 0",
                          borderTop: i > 0 ? "1px solid #f1f5f9" : "none" }}>
              {fmtMoney(p.total_paid)}
            </div>
            <div style={{ color: "#475569", textAlign: "center",
                          padding: "6px 0",
                          borderTop: i > 0 ? "1px solid #f1f5f9" : "none" }}>
              {p.invoices_count}
            </div>
          </React.Fragment>
        ))}
      </div>
      {!compact && (
        <div style={{ marginTop: 10, padding: 8, background: "#f0fdf4",
                       borderRadius: 6, fontSize: 11, color: "#15803d" }}>
          💡 Dica: clique em qualquer ponto verde do gráfico para ver quem
          pagou exatamente naquele dia.
        </div>
      )}
    </div>
  );
}


/**
 * Modal de drill-down: lista completa de pagadores em um dia OU período.
 *
 * Props:
 *   date: YYYY-MM-DD para um dia específico (null para período inteiro)
 *   fromDate / toDate: usados quando date=null
 *   onClose: callback
 */
export function PayersDrillDownModal({ date, fromDate, toDate, onClose }) {
  const [items, setItems] = useState(null);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  async function reload() {
    setLoading(true);
    try {
      let url = "/financeiro/payers?";
      if (date) {
        url += `target_date=${date}`;
      } else {
        url += `range=custom&from_date=${fromDate}&to_date=${toDate}`;
      }
      url += `&limit=500`;
      if (search) url += `&search=${encodeURIComponent(search)}`;
      const r = await api._client.get(url).then((r) => r.data);
      setItems(r.items || []);
      setTotal(r.total_paid_period || 0);
    } catch (e) {
      setItems([]);
    } finally { setLoading(false); }
  }

  useEffect(() => { reload(); /* eslint-disable-next-line */ }, [date, search]);

  return (
    <div data-testid="payers-drill-modal"
         onClick={onClose}
         style={{
           position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
           display: "flex", alignItems: "center", justifyContent: "center",
           zIndex: 9000, padding: 20,
         }}>
      <div onClick={(e) => e.stopPropagation()}
           style={{
             background: "#fff", borderRadius: 12, padding: 20,
             maxWidth: 900, width: "100%", maxHeight: "85vh",
             overflowY: "auto",
           }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: "#0f172a" }}>
              Pagadores {date ? `em ${date}` : `de ${fromDate} a ${toDate}`}
            </div>
            <div style={{ fontSize: 12, color: "#64748b", marginTop: 4 }}>
              {items?.length || 0} clientes ·{" "}
              <strong style={{ color: "#16a34a" }}>{fmtMoney(total)}</strong>
            </div>
          </div>
          <button onClick={onClose}
                  data-testid="close-payers-modal"
                  style={{
                    padding: "6px 12px", borderRadius: 6,
                    background: "#f1f5f9", border: "1px solid #cbd5e1",
                    fontSize: 13, cursor: "pointer",
                  }}>Fechar ✕</button>
        </div>

        <input
          data-testid="search-payers-input"
          type="text"
          placeholder="Buscar por nome ou documento..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            width: "100%", padding: "8px 12px", borderRadius: 6,
            border: "1px solid #cbd5e1", fontSize: 13, marginBottom: 12,
          }} />

        {loading && <div style={{ padding: 24, textAlign: "center",
                                    color: "#64748b" }}>Carregando…</div>}
        {!loading && items?.length === 0 && (
          <div style={{ padding: 24, textAlign: "center", color: "#64748b" }}>
            Nenhum pagador encontrado.
          </div>
        )}
        {!loading && items?.length > 0 && (
          <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "2px solid #e2e8f0",
                            background: "#f8fafc" }}>
                <th style={{ textAlign: "left", padding: "8px 6px" }}>
                  Cliente
                </th>
                <th style={{ textAlign: "left", padding: "8px 6px" }}>
                  Documento
                </th>
                <th style={{ textAlign: "center", padding: "8px 6px" }}>
                  Faturas
                </th>
                <th style={{ textAlign: "right", padding: "8px 6px" }}>
                  Total Pago
                </th>
                <th style={{ textAlign: "center", padding: "8px 6px" }}>
                  Último Pgto
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={(it.subscriber_external_id || "") + i}
                    data-testid={`drill-payer-row-${i}`}
                    style={{ borderBottom: "1px solid #f1f5f9" }}>
                  <td style={{ padding: "8px 6px", color: "#0f172a" }}>
                    {it.subscriber_name}
                  </td>
                  <td style={{ padding: "8px 6px", color: "#64748b",
                                fontFamily: "monospace", fontSize: 12 }}>
                    {it.subscriber_document || "—"}
                  </td>
                  <td style={{ padding: "8px 6px", textAlign: "center",
                                color: "#475569" }}>
                    {it.invoices_count}
                  </td>
                  <td style={{ padding: "8px 6px", textAlign: "right",
                                color: "#16a34a", fontWeight: 600 }}>
                    {fmtMoney(it.total_paid)}
                  </td>
                  <td style={{ padding: "8px 6px", textAlign: "center",
                                color: "#64748b", fontSize: 11 }}>
                    {it.last_payment_at}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
