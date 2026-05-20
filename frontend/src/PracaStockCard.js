/**
 * PracaStockCard — Estoque por Praça (saldo de ONTs e insumos por filial).
 *
 * Mostra:
 *  - Praça
 *  - Almoxarifes/responsáveis
 *  - Total de ONTs disponíveis
 *  - Lista de insumos (Drop, Cabo, etc) com quantidades
 */
import React, { useEffect, useState } from "react";
import { api } from "@/api";

export default function PracaStockCard() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.stokPracaSummary().then(setData).catch((e) =>
      setErr(e?.response?.data?.detail || e.message));
  }, []);

  if (err) {
    return <div style={{ padding: 14, color: "#991b1b", fontSize: 12 }}>{err}</div>;
  }
  if (!data) return null;

  return (
    <div data-testid="praca-stock-card"
          style={{
            background: "white", border: "1px solid #e2e8f0",
            borderRadius: 14, padding: 18, marginBottom: 22,
          }}>
      <div style={{
        display: "flex", justifyContent: "space-between",
        alignItems: "baseline", marginBottom: 14,
      }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 800,
                          color: "#0f172a" }}>
            🏢 Estoque por Praça
          </h3>
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
            Saldo de ONTs e insumos em cada filial · {data.items.length} praça(s)
          </div>
        </div>
        {data.orphan_onts > 0 && (
          <div title="ONTs sem praça vinculada (compra antiga). Faça transferência ou edição manual."
                style={{
                  fontSize: 11, fontWeight: 700,
                  padding: "4px 10px", borderRadius: 999,
                  background: "#fef3c7", color: "#92400e",
                }}>
            ⚠️ {data.orphan_onts} ONT(s) sem praça
          </div>
        )}
      </div>

      {data.items.length === 0 ? (
        <div style={{ padding: 20, textAlign: "center", color: "#94a3b8",
                       fontSize: 12 }}>
          Nenhuma praça cadastrada. Vá em Financeiro → Filiais.
        </div>
      ) : (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
          gap: 10,
        }}>
          {data.items.map((p) => (
            <div key={p.praca_id}
                  data-testid={`praca-stock-${p.praca_id}`}
                  style={{
                    border: "1px solid #e2e8f0",
                    borderRadius: 10, padding: 12,
                    background: "#f8fafc",
                  }}>
              <div style={{
                display: "flex", justifyContent: "space-between",
                alignItems: "baseline", marginBottom: 6,
              }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 800,
                                  color: "#0f172a", whiteSpace: "nowrap",
                                  overflow: "hidden", textOverflow: "ellipsis" }}>
                    📦 {p.praca_name}
                  </div>
                  {p.keepers.length > 0 ? (
                    <div style={{ fontSize: 10, color: "#475569",
                                    marginTop: 2 }}>
                      👤 {p.keepers.map((k) => k.name).join(", ")}
                    </div>
                  ) : (
                    <div style={{ fontSize: 10, color: "#94a3b8",
                                    marginTop: 2, fontStyle: "italic" }}>
                      Sem almoxarife vinculado
                    </div>
                  )}
                </div>
                <div style={{
                  fontSize: 22, fontWeight: 900,
                  color: p.ont_count > 0 ? "#065f46" : "#94a3b8",
                  lineHeight: 1,
                }}>
                  {p.ont_count}
                  <span style={{ fontSize: 9, fontWeight: 700,
                                  display: "block", color: "#64748b" }}>
                    ONTs
                  </span>
                </div>
              </div>

              {/* Insumos da praça */}
              {p.consumables.length > 0 ? (
                <div style={{ marginTop: 8, paddingTop: 8,
                                borderTop: "1px solid #e2e8f0",
                                display: "grid",
                                gridTemplateColumns: "repeat(auto-fit, minmax(85px, 1fr))",
                                gap: 4 }}>
                  {p.consumables.slice(0, 12).map((c) => (
                    <div key={c.key} style={{
                      padding: "3px 6px",
                      background: c.qty > 0 ? "#ecfdf5" : "#f1f5f9",
                      border: c.qty > 0 ? "1px solid #6ee7b7"
                                            : "1px dashed #cbd5e1",
                      borderRadius: 5,
                      fontSize: 10,
                      display: "flex", justifyContent: "space-between",
                      alignItems: "center",
                      color: c.qty > 0 ? "#065f46" : "#94a3b8",
                    }} title={c.label || c.key}>
                      <span style={{
                        whiteSpace: "nowrap",
                        overflow: "hidden", textOverflow: "ellipsis",
                        maxWidth: 60, fontWeight: 600,
                      }}>{(c.label || c.key).slice(0, 9)}</span>
                      <strong>{c.qty}</strong>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ marginTop: 8, paddingTop: 8,
                                borderTop: "1px dashed #e2e8f0",
                                fontSize: 10, color: "#94a3b8",
                                fontStyle: "italic", textAlign: "center" }}>
                  Sem insumos lançados nesta praça
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
