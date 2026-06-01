/* Ipv6QualityCard — Dashboard de qualidade IPv6 agregado por Bairro e CTO.
 * Fonte: completion_data.ipv6_test dos tickets finalizados.
 */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";

const fmtScore = (s) =>
  s >= 9 ? { color: "#15803d", bg: "#dcfce7", emoji: "✓" } :
  s >= 7 ? { color: "#16a34a", bg: "#ecfdf5", emoji: "✓" } :
  s >= 4 ? { color: "#b45309", bg: "#fef3c7", emoji: "⚠" } :
  { color: "#991b1b", bg: "#fee2e2", emoji: "✕" };

function MiniTable({ title, rows, keyName }) {
  if (!rows || rows.length === 0) {
    return (
      <div style={{ padding: 16, textAlign: "center", color: "#94a3b8", fontSize: 12 }}>
        Nenhum teste IPv6 registrado neste período.
      </div>
    );
  }
  return (
    <div data-testid={`ipv6q-table-${keyName}`}>
      <div style={{ fontSize: 12, fontWeight: 800, color: "#0f172a",
                      marginBottom: 8, letterSpacing: 0.3 }}>
        {title}
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: "#f8fafc", color: "#64748b", textAlign: "left" }}>
              <th style={{ padding: "8px 10px" }}>{keyName === "bairro" ? "Bairro" : "CTO"}</th>
              <th style={{ padding: "8px 10px", textAlign: "right" }}>Testes</th>
              <th style={{ padding: "8px 10px", textAlign: "right" }}>Score</th>
              <th style={{ padding: "8px 10px", textAlign: "right" }}>Inconsist.</th>
              <th style={{ padding: "8px 10px", textAlign: "right" }}>Sem v6</th>
              <th style={{ padding: "8px 10px", textAlign: "right" }}>MTU ✕</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const c = fmtScore(r.avg_score);
              return (
                <tr key={i} style={{ borderTop: "1px solid #e2e8f0" }}>
                  <td style={{ padding: "8px 10px", fontWeight: 600, color: "#0f172a" }}>
                    {r[keyName === "bairro" ? "bairro" : "cto"]}
                  </td>
                  <td style={{ padding: "8px 10px", textAlign: "right", color: "#475569" }}>
                    {r.count}
                  </td>
                  <td style={{ padding: "8px 10px", textAlign: "right" }}>
                    <span style={{
                      background: c.bg, color: c.color, padding: "2px 8px",
                      borderRadius: 999, fontWeight: 800, fontSize: 11,
                    }}>{c.emoji} {r.avg_score}/10</span>
                  </td>
                  <td style={{ padding: "8px 10px", textAlign: "right",
                                  color: r.inconsistent_pct > 20 ? "#991b1b" : "#475569",
                                  fontWeight: r.inconsistent_pct > 20 ? 700 : 400 }}>
                    {r.inconsistent_pct}%
                  </td>
                  <td style={{ padding: "8px 10px", textAlign: "right", color: "#475569" }}>
                    {r.no_v6}
                  </td>
                  <td style={{ padding: "8px 10px", textAlign: "right", color: "#475569" }}>
                    {r.mtu_fail}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function Ipv6QualityCard() {
  const [data, setData] = useState(null);
  const [period, setPeriod] = useState(30);
  const [loading, setLoading] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.networkIpv6Quality(period);
      setData(r);
    } catch (e) {
      console.warn("ipv6-quality fail", e);
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => { reload(); }, [reload]);

  const overall = data?.overall;
  const sc = fmtScore(overall?.avg_score || 0);

  return (
    <div data-testid="ipv6q-card" style={{
      background: "white", border: "1px solid #e2e8f0", borderRadius: 14,
      padding: 18, boxShadow: "0 2px 8px rgba(15,23,42,.04)", marginTop: 16,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 14, flexWrap: "wrap", gap: 10 }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 800, color: "#1e3a8a",
                          textTransform: "uppercase", letterSpacing: 0.4 }}>
            🌐 Qualidade IPv6 da Rede
          </div>
          <div style={{ fontSize: 18, fontWeight: 800, color: "#0f172a", marginTop: 2 }}>
            Indicadores por Bairro e CTO
          </div>
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
            Baseado nos testes IPv6 obrigatórios das OS finalizadas.
          </div>
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <select data-testid="ipv6q-period"
                    value={period}
                    onChange={(e) => setPeriod(parseInt(e.target.value, 10))}
                    style={{
            padding: "6px 10px", borderRadius: 8, border: "1px solid #cbd5e1",
            fontSize: 12, background: "white",
          }}>
            <option value="7">Últimos 7 dias</option>
            <option value="30">Últimos 30 dias</option>
            <option value="90">Últimos 90 dias</option>
          </select>
          <button data-testid="ipv6q-reload" onClick={reload} disabled={loading}
                    style={{
            padding: "6px 10px", borderRadius: 8, border: "1px solid #cbd5e1",
            background: "white", color: "#0f172a", fontSize: 11, cursor: "pointer",
          }}>
            ↻ Atualizar
          </button>
        </div>
      </div>

      {/* KPIs gerais */}
      <div style={{ display: "grid",
                       gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
                       gap: 10, marginBottom: 16 }}>
        <div style={{ padding: 12, background: "#f8fafc", borderRadius: 10 }}>
          <div style={{ fontSize: 10, color: "#64748b", fontWeight: 700,
                          textTransform: "uppercase" }}>Total testado</div>
          <div data-testid="ipv6q-kpi-total" style={{ fontSize: 22, fontWeight: 800,
                                                           color: "#0f172a", marginTop: 4 }}>
            {overall?.total_tested || 0}
          </div>
        </div>
        <div style={{ padding: 12, background: sc.bg, borderRadius: 10 }}>
          <div style={{ fontSize: 10, color: sc.color, fontWeight: 700,
                          textTransform: "uppercase" }}>Score médio</div>
          <div data-testid="ipv6q-kpi-avg" style={{ fontSize: 22, fontWeight: 800,
                                                          color: sc.color, marginTop: 4 }}>
            {overall?.avg_score || 0}/10
          </div>
        </div>
        <div style={{ padding: 12,
                         background: (overall?.inconsistent_pct || 0) > 20 ? "#fee2e2" : "#f8fafc",
                         borderRadius: 10 }}>
          <div style={{ fontSize: 10, color: "#64748b", fontWeight: 700,
                          textTransform: "uppercase" }}>OS inconsistentes</div>
          <div data-testid="ipv6q-kpi-inc" style={{ fontSize: 22, fontWeight: 800,
                                                          color: (overall?.inconsistent_pct || 0) > 20 ? "#991b1b" : "#0f172a",
                                                          marginTop: 4 }}>
            {overall?.inconsistent_count || 0}{" "}
            <span style={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
              ({overall?.inconsistent_pct || 0}%)
            </span>
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <MiniTable title="🏘 Pior média por bairro" rows={data?.by_bairro} keyName="bairro" />
        <MiniTable title="📡 Pior média por CTO" rows={data?.by_cto} keyName="cto" />
      </div>
    </div>
  );
}
