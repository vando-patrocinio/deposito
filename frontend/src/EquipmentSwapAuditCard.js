import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { Card } from "@/ui";

/**
 * Card de auditoria de Trocas de ONT/ONU.
 *
 * Consome `GET /api/lousa/equipment-swaps/monthly-report` e renderiza:
 *  - 4 métricas (total, legítimas, suspeitas, % suspect_rate)
 *  - Série mensal (barra horizontal proporcional)
 *  - Ranking por técnico (ordenado por suspeitas)
 *  - Drill-down de cada troca SUSPEITA (collapsable)
 *
 * Regra exibida ao usuário: troca SUSPEITA = ONU online há > 10 min sem
 * reboot no momento do fechamento (toda troca física implica reboot).
 */
export default function EquipmentSwapAuditCard() {
  const [months, setMonths] = useState(6);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [showSuspects, setShowSuspects] = useState(false);

  async function reload(m = months) {
    setLoading(true);
    setErr("");
    try {
      const r = await api.equipmentSwapsMonthlyReport(m);
      setData(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha ao carregar");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { reload(months); }, [months]);

  const totals = data?.totals || {
    swaps: 0, legit: 0, suspect: 0, unknown: 0, suspect_rate: 0,
    threshold_minutes: 10,
  };
  const maxMonth = useMemo(
    () => Math.max(1, ...(data?.by_month || []).map((m) => m.total || 0)),
    [data?.by_month],
  );
  const suspectPct = Math.round((totals.suspect_rate || 0) * 100);

  return (
    <Card
      title={
        <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
          Auditoria — Trocas de ONT/ONU
          {totals.suspect > 0 && (
            <span data-testid="swap-audit-suspect-badge" style={{
              background: "#fee2e2", color: "#991b1b",
              border: "1px solid #fca5a5",
              fontSize: 11, fontWeight: 800,
              padding: "1px 8px", borderRadius: 999,
            }}>
              {totals.suspect} suspeita{totals.suspect > 1 ? "s" : ""}
            </span>
          )}
        </span>
      }
    >
      <p data-testid="swap-audit-rule"
          style={{ color: "#64748b", fontSize: 12.5, lineHeight: 1.5,
                     marginTop: -4, marginBottom: 12 }}>
        Toda troca física implica reboot. Se a ONU está online há mais que{" "}
        <strong>{totals.threshold_minutes} min</strong> sem mudança de status,
        a troca declarada é marcada como <strong>suspeita</strong>.
      </p>

      {/* Seletor de janela */}
      <div data-testid="swap-audit-window-picker"
            style={{ display: "flex", gap: 6, marginBottom: 12,
                       flexWrap: "wrap" }}>
        {[1, 3, 6, 12].map((m) => (
          <button key={m}
                    data-testid={`swap-audit-window-${m}m`}
                    onClick={() => setMonths(m)}
                    style={{
                      padding: "6px 12px", borderRadius: 8,
                      border: months === m ? "1px solid #0d9488"
                                              : "1px solid #cbd5e1",
                      background: months === m ? "#ccfbf1" : "white",
                      color: months === m ? "#0f766e" : "#475569",
                      fontWeight: 700, fontSize: 12, cursor: "pointer",
                    }}>
            {m === 12 ? "12 meses" : `${m} ${m === 1 ? "mês" : "meses"}`}
          </button>
        ))}
      </div>

      {err && (
        <div data-testid="swap-audit-error"
              style={{ background: "#fee2e2", color: "#991b1b",
                         padding: 10, borderRadius: 10, marginBottom: 10,
                         fontSize: 13 }}>
          {err}
        </div>
      )}

      {loading ? (
        <p style={{ color: "#64748b" }}>Carregando…</p>
      ) : (
        <>
          {/* 4 métricas */}
          <div data-testid="swap-audit-metrics"
                style={{ display: "grid",
                           gridTemplateColumns: "repeat(4, 1fr)",
                           gap: 8, marginBottom: 16 }}>
            <Metric label="Total" value={totals.swaps}
                       color="#0f172a" testid="swap-metric-total" />
            <Metric label="Legítimas" value={totals.legit}
                       color="#15803d" testid="swap-metric-legit" />
            <Metric label="Suspeitas" value={totals.suspect}
                       color="#b91c1c" testid="swap-metric-suspect" />
            <Metric label="% Suspeitas" value={`${suspectPct}%`}
                       color={suspectPct >= 30 ? "#b91c1c" : "#475569"}
                       testid="swap-metric-rate" />
          </div>

          {/* Série mensal */}
          {(data?.by_month || []).length > 0 && (
            <div data-testid="swap-audit-by-month"
                  style={{ marginBottom: 16 }}>
              <h4 style={{ margin: "0 0 8px 0", fontSize: 13,
                              color: "#334155", fontWeight: 700 }}>
                Por mês
              </h4>
              {data.by_month.map((m) => {
                const total = m.total || 0;
                const legitW = (m.legit / maxMonth) * 100;
                const suspectW = (m.suspect / maxMonth) * 100;
                const unknownW = (m.unknown / maxMonth) * 100;
                return (
                  <div key={m.month}
                        data-testid={`swap-month-${m.month}`}
                        style={{ display: "flex", alignItems: "center",
                                   gap: 10, marginBottom: 6 }}>
                    <span style={{ fontFamily: "monospace",
                                      fontSize: 12, color: "#475569",
                                      minWidth: 70 }}>
                      {m.month}
                    </span>
                    <div style={{ flex: 1, display: "flex", height: 18,
                                     borderRadius: 4, overflow: "hidden",
                                     background: "#f1f5f9" }}>
                      {legitW > 0 && (
                        <div style={{ width: `${legitW}%`, background: "#86efac" }}
                                title={`${m.legit} legítimas`} />
                      )}
                      {suspectW > 0 && (
                        <div style={{ width: `${suspectW}%`, background: "#fca5a5" }}
                                title={`${m.suspect} suspeitas`} />
                      )}
                      {unknownW > 0 && (
                        <div style={{ width: `${unknownW}%`, background: "#cbd5e1" }}
                                title={`${m.unknown} sem verificação`} />
                      )}
                    </div>
                    <span style={{ fontSize: 12, fontWeight: 700,
                                      color: "#1e293b", minWidth: 30,
                                      textAlign: "right" }}>
                      {total}
                    </span>
                  </div>
                );
              })}
              <div style={{ display: "flex", gap: 12,
                              fontSize: 11, color: "#64748b",
                              marginTop: 6 }}>
                <LegendDot color="#86efac" label="Legítimas" />
                <LegendDot color="#fca5a5" label="Suspeitas" />
                <LegendDot color="#cbd5e1" label="Sem verificação" />
              </div>
            </div>
          )}

          {/* Ranking por técnico */}
          {(data?.by_technician || []).length > 0 && (
            <div data-testid="swap-audit-by-tech"
                  style={{ marginBottom: 12 }}>
              <h4 style={{ margin: "0 0 8px 0", fontSize: 13,
                              color: "#334155", fontWeight: 700 }}>
                Por técnico (ordenado por suspeitas)
              </h4>
              <div style={{ display: "flex", flexDirection: "column",
                              gap: 4 }}>
                {data.by_technician.slice(0, 10).map((t) => (
                  <div key={t.technician_id}
                        data-testid={`swap-tech-${t.technician_id}`}
                        style={{ display: "flex",
                                   justifyContent: "space-between",
                                   alignItems: "center",
                                   padding: "6px 10px",
                                   background: t.suspect > 0 ? "#fef2f2" : "#f8fafc",
                                   border: `1px solid ${t.suspect > 0 ? "#fecaca" : "#e2e8f0"}`,
                                   borderRadius: 8, fontSize: 12.5 }}>
                    <strong style={{ color: "#0f172a" }}>
                      {t.technician_name}
                    </strong>
                    <div style={{ display: "flex", gap: 10 }}>
                      <span style={{ color: "#15803d", fontWeight: 700 }}>
                        ✓ {t.legit}
                      </span>
                      {t.suspect > 0 && (
                        <span style={{ color: "#b91c1c", fontWeight: 800 }}>
                          {t.suspect}
                        </span>
                      )}
                      <span style={{ color: "#64748b" }}>
                        Total: <strong>{t.total}</strong>
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Drill-down de suspeitas */}
          {(data?.suspects || []).length > 0 && (
            <div data-testid="swap-audit-suspects-section">
              <button
                data-testid="swap-audit-suspects-toggle"
                onClick={() => setShowSuspects((v) => !v)}
                style={{
                  border: "1px solid #fecaca", background: "#fef2f2",
                  color: "#991b1b", padding: "8px 14px", borderRadius: 8,
                  fontSize: 12.5, fontWeight: 700, cursor: "pointer",
                  width: "100%", textAlign: "left",
                }}>
                {showSuspects ? "▾" : "▸"} {data.suspects.length} troca(s)
                suspeita(s) — ver detalhe
              </button>
              {showSuspects && (
                <div data-testid="swap-audit-suspects-list"
                      style={{ marginTop: 8, maxHeight: 280,
                                 overflowY: "auto",
                                 border: "1px solid #fecaca",
                                 borderRadius: 8 }}>
                  {data.suspects.map((s) => (
                    <div key={s.id}
                          data-testid={`swap-suspect-${s.id}`}
                          style={{ padding: "10px 12px",
                                     borderBottom: "1px solid #fecaca",
                                     fontSize: 12, lineHeight: 1.5 }}>
                      <div style={{ display: "flex",
                                       justifyContent: "space-between",
                                       gap: 8, marginBottom: 4 }}>
                        <strong style={{ color: "#0f172a" }}>
                          {s.technician_name}
                        </strong>
                        <span style={{ color: "#64748b", fontSize: 11 }}>
                          {(s.created_at || "").slice(0, 16).replace("T", " ")}
                        </span>
                      </div>
                      <div style={{ color: "#475569", fontFamily: "monospace",
                                       fontSize: 11.5 }}>
                        <div>Retirado:{" "}
                          <strong>{s.old_mac || s.old_sn || "—"}</strong>
                        </div>
                        <div>Instalado:{" "}
                          <strong>{s.new_mac || s.new_sn || "—"}</strong>
                        </div>
                      </div>
                      <div style={{ color: "#991b1b", marginTop: 4,
                                       fontSize: 11.5 }}>
                        ONU online há{" "}
                        <strong>{s.uptime_minutes_at_close ?? "?"} min</strong>{" "}
                        sem reboot (limite {s.threshold_minutes} min) ·{" "}
                        ticket{" "}
                        <code style={{ background: "white",
                                          padding: "0 4px",
                                          borderRadius: 4 }}>
                          {s.ticket_id}
                        </code>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {!loading && totals.swaps === 0 && (
            <p data-testid="swap-audit-empty"
                style={{ color: "#64748b", fontSize: 13 }}>
              Nenhuma troca de ONT/ONU registrada na janela selecionada.
            </p>
          )}
        </>
      )}
    </Card>
  );
}

function Metric({ label, value, color, testid }) {
  return (
    <div data-testid={testid}
          style={{ background: "#f8fafc", border: "1px solid #e2e8f0",
                     borderRadius: 10, padding: "10px 8px",
                     textAlign: "center" }}>
      <div style={{ fontSize: 20, fontWeight: 800, color: color || "#0f172a",
                       lineHeight: 1.1 }}>
        {value}
      </div>
      <div style={{ fontSize: 11, color: "#64748b", fontWeight: 600,
                       marginTop: 2 }}>
        {label}
      </div>
    </div>
  );
}

function LegendDot({ color, label }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <span style={{ width: 10, height: 10, borderRadius: 2,
                        background: color, display: "inline-block" }} />
      {label}
    </span>
  );
}
