/* SmartoltHistoryPanel — iter215au
 * Painel global de histórico das ONTs/ONUs no SmartOLT, com KPIs
 * profissionais FTTH/GPON (TM Forum + FTTH Council best practices 2026):
 *   • Inventário (total / online / LOS / power-off) + Health Score
 *   • Ciclo de vida (trocas 30d / novos 30d / MTBF estimado)
 *   • Saúde óptica (sinal médio downstream 1490nm)
 *   • Reliability ranking por fornecedor (Huawei / Nokia / ZTE / etc.)
 *   • Time-series de trocas/dia (chart)
 *   • Tabela de trocas recentes com fornecedor antigo → novo
 */
import React, { useCallback, useEffect, useState } from "react";
import { Activity, Cpu, AlertTriangle, ArrowRightLeft, RefreshCw,
         TrendingUp, Zap, Heart } from "lucide-react";
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis,
         Tooltip, CartesianGrid } from "recharts";

import { api } from "@/api";

const HEALTH_COLOR = (h) => {
  if (h >= 90) return { c: "#15803d", bg: "#dcfce7", label: "Excelente" };
  if (h >= 75) return { c: "#a16207", bg: "#fef9c3", label: "Boa" };
  if (h >= 50) return { c: "#c2410c", bg: "#fed7aa", label: "Atenção" };
  return { c: "#b91c1c", bg: "#fee2e2", label: "Crítica" };
};

function Kpi({ icon: Icon, label, value, sub, color = "#4b1d7a",
                 testid }) {
  return (
    <div data-testid={testid}
          style={{ flex: "1 1 180px", minWidth: 180,
                    padding: 14, background: "white",
                    border: "1px solid #e2e8f0", borderRadius: 12,
                    boxShadow: "0 1px 2px rgba(15,23,42,.04)" }}>
      <div style={{ display: "flex", alignItems: "center",
                     gap: 8, color: "#64748b", fontSize: 11,
                     fontWeight: 700, textTransform: "uppercase",
                     letterSpacing: 0.4, marginBottom: 8 }}>
        <Icon size={13} color={color} />
        {label}
      </div>
      <div style={{ fontSize: 26, fontWeight: 800, color: "#0f172a",
                     letterSpacing: -0.5, lineHeight: 1 }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 11, color: "#64748b", marginTop: 6,
                        lineHeight: 1.4 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

export default function SmartoltHistoryPanel() {
  const [kpis, setKpis] = useState(null);
  const [swaps, setSwaps] = useState([]);
  const [ts, setTs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [period, setPeriod] = useState(30);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const [k, s, t] = await Promise.all([
        api.smartoltHistoryKpis(),
        api.smartoltHistorySwaps(period, 200),
        api.smartoltHistoryTimeseries(period),
      ]);
      setKpis(k); setSwaps(s.items || []); setTs(t.items || []);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha");
    } finally { setLoading(false); }
  }, [period]);

  useEffect(() => { load(); }, [load]);

  async function runReconcile() {
    const ok = window.confirm(
      "Rodar reconciliação SmartOLT?\n\n"
      + "Vai buscar TODAS as ONUs e detectar trocas. Pode demorar 10-30s."
    );
    if (!ok) return;
    setBusy(true);
    try {
      await api.smartoltReconcileOnus();
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha");
    } finally { setBusy(false); }
  }

  const inv = (kpis && kpis.inventory) || {};
  const lc = (kpis && kpis.lifecycle) || {};
  const sig = (kpis && kpis.signal) || {};
  const health = HEALTH_COLOR((kpis && kpis.health_score) || 0);

  return (
    <div data-testid="smartolt-history-panel"
          style={{ fontFamily: "Inter, sans-serif" }}>
      {loading && !kpis ? (
        <div style={{ padding: 30, textAlign: "center", color: "#64748b" }}>
          Carregando KPIs…
        </div>
      ) : err && !kpis ? (
        <div style={{ padding: 14, background: "#fee2e2",
                        color: "#7f1d1d", borderRadius: 10 }}>
          {err}
        </div>
      ) : kpis ? (
        <>
          <div style={{ display: "flex", alignItems: "center",
                         justifyContent: "space-between", marginBottom: 18,
                         gap: 12, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 800, margin: 0,
                         color: "#0f172a", letterSpacing: -0.4 }}>
            Histórico SmartOLT
          </h2>
          <p style={{ fontSize: 12, color: "#64748b", marginTop: 4,
                       lineHeight: 1.5, maxWidth: 720 }}>
            Inventário e ciclo de vida das ONTs/ONUs conectadas ao
            SmartOLT. KPIs profissionais (TM Forum + FTTH Council).
            Atualizado em {new Date(kpis.as_of).toLocaleString("pt-BR")}.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <select data-testid="period-select" value={period}
                   onChange={(e) => setPeriod(Number(e.target.value))}
                   style={{ padding: "8px 10px", borderRadius: 8,
                             border: "1px solid #cbd5e1", fontSize: 13,
                             background: "white", fontWeight: 600 }}>
            <option value={7}>Últimos 7 dias</option>
            <option value={30}>Últimos 30 dias</option>
            <option value={90}>Últimos 90 dias</option>
            <option value={365}>Últimos 12 meses</option>
          </select>
          <button data-testid="reconcile-btn"
                   onClick={runReconcile}
                   disabled={busy}
                   style={{ display: "inline-flex", alignItems: "center",
                             gap: 6, padding: "8px 14px", border: "none",
                             borderRadius: 8,
                             background: "var(--primary, #4b1d7a)",
                             color: "white", fontWeight: 700, fontSize: 12.5,
                             cursor: busy ? "wait" : "pointer",
                             opacity: busy ? 0.6 : 1 }}>
            <RefreshCw size={13} />
            {busy ? "Reconciliando…" : "Reconciliar agora"}
          </button>
        </div>
      </div>

      {/* HEALTH SCORE — destaque */}
      <div data-testid="health-score-card"
            style={{ marginBottom: 16, padding: 16, borderRadius: 14,
                      background: `linear-gradient(135deg, ${health.bg}, white)`,
                      border: `2px solid ${health.c}`,
                      display: "flex", alignItems: "center", gap: 18 }}>
        <div style={{ width: 70, height: 70, borderRadius: "50%",
                        background: health.c, color: "white",
                        display: "flex", alignItems: "center",
                        justifyContent: "center", fontSize: 24,
                        fontWeight: 900 }}>
          {kpis.health_score}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, color: "#64748b", fontWeight: 700,
                          textTransform: "uppercase", letterSpacing: 0.5 }}>
            Network Health Score
          </div>
          <div style={{ fontSize: 22, fontWeight: 800, color: health.c,
                          marginTop: 2 }}>
            Saúde {health.label}
          </div>
          <div style={{ fontSize: 12, color: "#475569", marginTop: 4 }}>
            {inv.online_pct}% das ONUs online · {inv.los_pct}% em LOS
          </div>
        </div>
        <Heart size={36} color={health.c} fill={health.c} opacity={0.2} />
      </div>

      {/* KPIs HERO */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16,
                     flexWrap: "wrap" }}>
        <Kpi testid="kpi-total" icon={Cpu} label="ONUs totais"
              value={inv.total ?? 0}
              sub={`${inv.online ?? 0} online · ${inv.poweroff ?? 0} desligadas`} />
        <Kpi testid="kpi-online" icon={Activity}
              label="Online"
              value={`${inv.online_pct ?? 0}%`} color="#15803d"
              sub={`${inv.online ?? 0} de ${inv.total ?? 0} ativas`} />
        <Kpi testid="kpi-los" icon={AlertTriangle} label="LOS / Offline"
              value={inv.los ?? 0} color="#b91c1c"
              sub={`${inv.los_pct ?? 0}% do parque · investigar`} />
        <Kpi testid="kpi-swaps" icon={ArrowRightLeft}
              label={`Trocas (${period}d)`}
              value={lc.swaps_30d ?? 0} color="#c2410c"
              sub={`taxa mensal: ${lc.swap_rate_monthly_pct ?? 0}%`} />
        <Kpi testid="kpi-new" icon={TrendingUp} label={`Novas (${period}d)`}
              value={lc.new_30d ?? 0} color="#0369a1"
              sub={`crescimento líquido: ${lc.net_growth_30d > 0 ? "+" : ""}${lc.net_growth_30d ?? 0}`} />
        <Kpi testid="kpi-mtbf" icon={Heart}
              label="MTBF estimado"
              value={lc.mtbf_days ? `${lc.mtbf_days} d` : "—"}
              color="#6d28d9"
              sub={lc.mtbf_days
                ? `Tempo médio até troca`
                : "Sem dados suficientes"} />
        <Kpi testid="kpi-signal" icon={Zap}
              label="Sinal médio (1490nm)"
              value={sig.avg_1490_dbm
                ? `${sig.avg_1490_dbm} dBm` : "—"}
              color={sig.avg_1490_dbm && sig.avg_1490_dbm > -25
                ? "#15803d" : "#a16207"}
              sub={sig.min_1490_dbm
                ? `Faixa: ${sig.min_1490_dbm} a ${sig.max_1490_dbm} dBm`
                : "Sem leituras"} />
      </div>

      {/* TIME-SERIES — trocas/dia */}
      {ts.length > 0 && (
        <div data-testid="swaps-timeseries-card"
              style={{ background: "white", border: "1px solid #e2e8f0",
                        borderRadius: 12, padding: 14, marginBottom: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 800, color: "#0f172a",
                          marginBottom: 10 }}>
            Trocas detectadas por dia ({period}d)
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={ts}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
              <Tooltip />
              <Line type="monotone" dataKey="swaps"
                     stroke="var(--primary, #4b1d7a)"
                     strokeWidth={2.5}
                     dot={{ r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* RELIABILITY RANKING — vendors */}
      {kpis.vendors && kpis.vendors.length > 0 && (
        <div data-testid="vendor-table-card"
              style={{ background: "white", border: "1px solid #e2e8f0",
                        borderRadius: 12, padding: 14, marginBottom: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 800, color: "#0f172a",
                          marginBottom: 10 }}>
            Reliability ranking por fornecedor (top 10 por volume)
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse",
                            fontSize: 12.5 }}>
            <thead>
              <tr style={{ background: "#f8fafc", color: "#475569",
                            textTransform: "uppercase", fontSize: 10.5,
                            fontWeight: 700, letterSpacing: 0.4 }}>
                <th style={{ textAlign: "left", padding: "8px 10px" }}>
                  Fornecedor</th>
                <th style={{ textAlign: "left", padding: "8px 10px" }}>
                  Prefix SN</th>
                <th style={{ textAlign: "right", padding: "8px 10px" }}>
                  Qtd</th>
                <th style={{ textAlign: "right", padding: "8px 10px" }}>
                  LOS</th>
                <th style={{ textAlign: "right", padding: "8px 10px" }}>
                  % LOS</th>
              </tr>
            </thead>
            <tbody>
              {kpis.vendors.map((v) => (
                <tr key={v.prefix}
                     style={{ borderTop: "1px solid #f1f5f9" }}>
                  <td style={{ padding: "8px 10px", fontWeight: 700 }}>
                    {v.vendor}
                  </td>
                  <td style={{ padding: "8px 10px",
                                  fontFamily: "monospace", color: "#64748b" }}>
                    {v.prefix}
                  </td>
                  <td style={{ padding: "8px 10px", textAlign: "right",
                                  fontVariantNumeric: "tabular-nums" }}>
                    {v.count}
                  </td>
                  <td style={{ padding: "8px 10px", textAlign: "right",
                                  fontVariantNumeric: "tabular-nums" }}>
                    {v.los}
                  </td>
                  <td style={{ padding: "8px 10px", textAlign: "right",
                                  fontWeight: 700,
                                  color: v.los_pct > 15 ? "#b91c1c"
                                    : v.los_pct > 5 ? "#a16207" : "#15803d" }}>
                    {v.los_pct}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* TROCAS RECENTES */}
      <div data-testid="swaps-table-card"
            style={{ background: "white", border: "1px solid #e2e8f0",
                      borderRadius: 12, padding: 14 }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: "#0f172a",
                        marginBottom: 10 }}>
          Trocas detectadas ({swaps.length}) · últimos {period}d
        </div>
        {swaps.length === 0 ? (
          <div style={{ padding: 18, textAlign: "center",
                          color: "#94a3b8", fontSize: 13 }}>
            Nenhuma troca detectada nesse período. Rode &quot;Reconciliar
            agora&quot; pra forçar uma varredura.
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse",
                              fontSize: 12 }}>
              <thead>
                <tr style={{ background: "#f8fafc", color: "#475569",
                              textTransform: "uppercase", fontSize: 10.5,
                              fontWeight: 700, letterSpacing: 0.4 }}>
                  <th style={{ textAlign: "left", padding: "8px 10px" }}>
                    Cliente / Nome</th>
                  <th style={{ textAlign: "left", padding: "8px 10px" }}>
                    OLT · CTO</th>
                  <th style={{ textAlign: "left", padding: "8px 10px" }}>
                    SN antigo</th>
                  <th style={{ textAlign: "left", padding: "8px 10px" }}>
                    SN atual</th>
                  <th style={{ textAlign: "left", padding: "8px 10px" }}>
                    Fornecedor</th>
                  <th style={{ textAlign: "left", padding: "8px 10px" }}>
                    Detectado em</th>
                </tr>
              </thead>
              <tbody>
                {swaps.map((s) => (
                  <tr key={s.unique_external_id}
                       data-testid={`swap-row-${s.unique_external_id}`}
                       style={{ borderTop: "1px solid #f1f5f9" }}>
                    <td style={{ padding: "8px 10px", fontWeight: 600 }}>
                      {s.name || "—"}
                    </td>
                    <td style={{ padding: "8px 10px", color: "#64748b" }}>
                      {[s.olt_name, s.zone_name].filter(Boolean).join(" · ")
                        || "—"}
                    </td>
                    <td style={{ padding: "8px 10px",
                                    fontFamily: "monospace",
                                    color: "#b91c1c",
                                    textDecoration: "line-through" }}>
                      {s.previous_sn || "—"}
                    </td>
                    <td style={{ padding: "8px 10px",
                                    fontFamily: "monospace",
                                    color: "#15803d", fontWeight: 700 }}>
                      {s.sn || "—"}
                    </td>
                    <td style={{ padding: "8px 10px" }}>
                      <span style={{ color: "#94a3b8",
                                       textDecoration:
                                         s.vendor_changed
                                           ? "line-through" : "none" }}>
                        {s.vendor_old}
                      </span>
                      {s.vendor_changed && (
                        <>
                          {" → "}
                          <b style={{ color: "#0f172a" }}>
                            {s.vendor_new}
                          </b>
                        </>
                      )}
                    </td>
                    <td style={{ padding: "8px 10px", color: "#64748b" }}>
                      {(s.swap_detected_at || "").replace("T", " ")
                        .slice(0, 16)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
        </>
      ) : null}
    </div>
  );
}
