/**
 * PracaStockCard — Estoque por Praça (saldo de ONTs e insumos por filial).
 *
 * - Cards clicáveis: abre modal lateral com lista detalhada de ONTs
 *   daquela praça (MAC, modelo, status).
 */
import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";

function PracaDetailModal({ praca, onClose }) {
  const [allOnts, setAllOnts] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [expandedMac, setExpandedMac] = useState(null);

  useEffect(() => {
    if (!praca) return;
    setLoading(true);
    Promise.all([
      api.stokOntsList(),
      api.stokHistory({ limit: 2000 }).catch(() => []),
    ]).then(([onts, hist]) => {
      setAllOnts(onts || []);
      setHistory(hist || []);
    }).finally(() => setLoading(false));
  }, [praca]);

  // historyByMac: extrai MACs via regex nas descrições (mesmo padrão da
  // aba "Dashboard" do EstoquePanel — popover por técnico).
  const historyByMac = useMemo(() => {
    const m = {};
    (history || []).forEach((h) => {
      const text = `${h.description || ""} ${h.notes || ""}`;
      const matches = text.match(/[0-9A-F]{2}(?::[0-9A-F]{2}){5}/gi);
      (matches || []).forEach((mac) => {
        const k = mac.toUpperCase();
        (m[k] = m[k] || []).push(h);
      });
    });
    Object.keys(m).forEach((k) => m[k].sort((a, b) =>
      (b.created_at || b.date || "").localeCompare(
        a.created_at || a.date || "")));
    return m;
  }, [history]);

  if (!praca) return null;

  const pracaOntsAll = allOnts.filter(
    (o) => o.location_type === "empresa" && o.praca_id === praca.praca_id);
  const q = search.trim().toUpperCase();
  const pracaOnts = q
    ? pracaOntsAll.filter(
        (o) => (o.mac || "").toUpperCase().includes(q)
          || (o.model || "").toUpperCase().includes(q))
    : pracaOntsAll;

  return (
    <div
      onClick={onClose}
      data-testid="praca-detail-modal-overlay"
      style={{
        position: "fixed", inset: 0,
        background: "rgba(15,23,42,.55)", zIndex: 9999,
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 20,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        data-testid="praca-detail-modal"
        style={{
          background: "white", borderRadius: 14, padding: 22,
          width: "100%", maxWidth: 720, maxHeight: "90vh",
          overflow: "auto",
          boxShadow: "0 20px 60px rgba(0,0,0,.3)",
        }}
      >
        <div style={{
          display: "flex", justifyContent: "space-between",
          alignItems: "flex-start", marginBottom: 16,
        }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 800, color: "#0f172a" }}>
              📦 {praca.praca_name}
            </div>
            <div style={{ fontSize: 12, color: "#64748b", marginTop: 4 }}>
              {praca.keepers.length > 0
                ? `Almoxarife(s): ${praca.keepers.map((k) => k.name).join(", ")}`
                : "Sem almoxarife vinculado"}
            </div>
          </div>
          <button
            onClick={onClose}
            data-testid="praca-detail-close"
            style={{
              background: "none", border: "none",
              fontSize: 24, cursor: "pointer", color: "#64748b",
              lineHeight: 1,
            }}
          >×</button>
        </div>

        {/* KPI bar */}
        <div style={{
          display: "grid", gridTemplateColumns: "1fr 1fr",
          gap: 10, marginBottom: 18,
        }}>
          <div style={{ background: "#f0fdf4",
                          border: "1px solid #6ee7b7", borderRadius: 10,
                          padding: 12, textAlign: "center" }}>
            <div style={{ fontSize: 28, fontWeight: 900, color: "#065f46" }}>
              {praca.ont_count}
            </div>
            <div style={{ fontSize: 11, color: "#065f46", fontWeight: 700 }}>
              📡 ONTs disponíveis
            </div>
          </div>
          <div style={{ background: "#eff6ff",
                          border: "1px solid #93c5fd", borderRadius: 10,
                          padding: 12, textAlign: "center" }}>
            <div style={{ fontSize: 28, fontWeight: 900, color: "#1e40af" }}>
              {praca.consumables.length}
            </div>
            <div style={{ fontSize: 11, color: "#1e40af", fontWeight: 700 }}>
              🔌 Tipos de insumo
            </div>
          </div>
        </div>

        {/* ONTs detalhadas */}
        <div style={{ marginBottom: 18 }}>
          <div style={{
            display: "flex", justifyContent: "space-between",
            alignItems: "center", marginBottom: 8, gap: 8,
          }}>
            <div style={{ fontSize: 12, fontWeight: 800, textTransform: "uppercase",
                            letterSpacing: ".04em", color: "#475569" }}>
              ONTs disponíveis ({pracaOnts.length}{q && pracaOnts.length !== pracaOntsAll.length
                ? ` de ${pracaOntsAll.length}` : ""})
            </div>
            {pracaOntsAll.length > 0 && (
              <input
                data-testid="praca-detail-search"
                placeholder="Buscar MAC ou modelo…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{
                  fontSize: 11, padding: "4px 8px",
                  border: "1px solid #cbd5e1", borderRadius: 6,
                  width: 180, fontFamily: "monospace",
                }}
              />
            )}
          </div>
          {loading ? (
            <div style={{ padding: 14, color: "#64748b", fontSize: 13 }}>Carregando…</div>
          ) : pracaOnts.length === 0 ? (
            <div style={{ padding: 14, background: "#f8fafc",
                            border: "1px dashed #cbd5e1", borderRadius: 8,
                            textAlign: "center", color: "#94a3b8",
                            fontSize: 12 }}>
              {q ? "Nenhum MAC corresponde à busca." : "Nenhuma ONT cadastrada nesta praça."}
            </div>
          ) : (
            <div style={{ maxHeight: 320, overflowY: "auto",
                            border: "1px solid #f1f5f9", borderRadius: 8 }}>
              {pracaOnts.map((o) => {
                const macHist = historyByMac[o.mac] || [];
                const isOpen = expandedMac === o.mac;
                return (
                  <div key={o.mac}
                        data-testid={`praca-detail-ont-${o.mac}`}
                        style={{ borderBottom: "1px solid #f1f5f9" }}>
                    <div
                      onClick={() => setExpandedMac(isOpen ? null : o.mac)}
                      style={{
                        padding: "6px 10px",
                        display: "flex", justifyContent: "space-between",
                        alignItems: "center", gap: 8,
                        cursor: "pointer",
                        background: isOpen ? "#f0f9ff" : "transparent",
                      }}>
                      <span style={{ fontFamily: "monospace", fontWeight: 700,
                                        fontSize: 12, color: "#0f172a" }}>
                        {isOpen ? "▾" : "▸"} {o.mac}
                      </span>
                      <div style={{ display: "flex", gap: 4,
                                      alignItems: "center" }}>
                        {macHist.length > 0 && (
                          <span title={`${macHist.length} evento(s) no histórico`}
                                style={{
                                  fontSize: 10, fontWeight: 700,
                                  padding: "2px 6px", borderRadius: 4,
                                  background: "#dbeafe", color: "#1e40af",
                                }}>
                            📜 {macHist.length}
                          </span>
                        )}
                        <span style={{ fontSize: 10, color: "#64748b",
                                          background: "#f1f5f9",
                                          padding: "2px 6px", borderRadius: 4 }}>
                          {o.model || "ONT"}
                        </span>
                      </div>
                    </div>
                    {isOpen && (
                      <div data-testid={`praca-mac-timeline-${o.mac}`}
                            style={{
                              background: "#f8fafc",
                              padding: "8px 10px 8px 22px",
                              borderLeft: "2px solid #3b82f6",
                              marginLeft: 8, marginBottom: 4,
                              borderRadius: 4,
                            }}>
                        <div style={{ fontSize: 9, fontWeight: 800,
                                        textTransform: "uppercase",
                                        color: "#64748b", marginBottom: 4 }}>
                          Histórico ({macHist.length})
                        </div>
                        {macHist.length === 0 && (
                          <div style={{ fontSize: 10, color: "#94a3b8",
                                          fontStyle: "italic" }}>
                            Sem histórico registrado para este MAC.
                          </div>
                        )}
                        {macHist.slice(0, 12).map((h, i) => {
                          const dt = (h.created_at || h.date || "");
                          const dStr = dt
                            ? new Date(dt).toLocaleString("pt-BR", {
                                day: "2-digit", month: "2-digit",
                                hour: "2-digit", minute: "2-digit",
                              })
                            : "—";
                          return (
                            <div key={i} style={{
                              fontSize: 10, color: "#334155",
                              padding: "3px 0",
                              borderBottom: "1px dashed #e2e8f0",
                            }}>
                              <div style={{ fontWeight: 700, color: "#0f172a" }}>
                                {dStr} · <span style={{
                                  textTransform: "uppercase",
                                  color: "#3b82f6",
                                }}>{h.type || "—"}</span>
                              </div>
                              <div style={{ marginTop: 1, color: "#475569" }}>
                                {h.description || h.notes || "(sem descrição)"}
                              </div>
                            </div>
                          );
                        })}
                        {macHist.length > 12 && (
                          <div style={{ fontSize: 9, color: "#94a3b8",
                                          marginTop: 4, fontStyle: "italic" }}>
                            +{macHist.length - 12} eventos antigos…
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

        {/* Insumos */}
        <div>
          <div style={{ fontSize: 12, fontWeight: 800, textTransform: "uppercase",
                          letterSpacing: ".04em", color: "#475569",
                          marginBottom: 8 }}>
            Insumos ({praca.consumables.length})
          </div>
          {praca.consumables.length === 0 ? (
            <div style={{ padding: 14, background: "#f8fafc",
                            border: "1px dashed #cbd5e1", borderRadius: 8,
                            textAlign: "center", color: "#94a3b8",
                            fontSize: 12 }}>
              Sem insumos lançados. Use a Central de Compras para registrar.
            </div>
          ) : (
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
              gap: 6,
            }}>
              {praca.consumables.map((c) => (
                <div key={c.key} style={{
                  padding: "6px 10px",
                  background: c.qty > 0 ? "#ecfdf5" : "#f1f5f9",
                  border: c.qty > 0 ? "1px solid #6ee7b7"
                                        : "1px dashed #cbd5e1",
                  borderRadius: 6, fontSize: 11,
                  display: "flex", justifyContent: "space-between",
                }}>
                  <span style={{ color: c.qty > 0 ? "#065f46" : "#94a3b8",
                                    fontWeight: 600 }}>
                    {c.label || c.key}
                  </span>
                  <strong style={{ color: c.qty > 0 ? "#065f46" : "#94a3b8" }}>
                    {c.qty}
                  </strong>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function PracaStockCard() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [selected, setSelected] = useState(null);

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
            Saldo de ONTs e insumos em cada filial · {data.items.length} praça(s) · clique para detalhar
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
            <button
              type="button"
              key={p.praca_id}
              data-testid={`praca-stock-${p.praca_id}`}
              onClick={() => setSelected(p)}
              style={{
                border: "1px solid #e2e8f0",
                borderRadius: 10, padding: 12,
                background: "#f8fafc",
                textAlign: "left",
                cursor: "pointer",
                transition: "transform .12s, box-shadow .12s",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.transform = "translateY(-2px)";
                e.currentTarget.style.boxShadow = "0 4px 12px rgba(15,23,42,.08)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.transform = "";
                e.currentTarget.style.boxShadow = "";
              }}
            >
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
            </button>
          ))}
        </div>
      )}

      {selected && <PracaDetailModal praca={selected}
                                          onClose={() => setSelected(null)} />}
    </div>
  );
}
