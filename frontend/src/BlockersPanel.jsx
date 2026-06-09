/**
 * BlockersPanel.jsx — V6.0 Bloco 2
 * "POR QUE A IA NÃO ESTÁ AGINDO?"
 */
import React, { useEffect, useState } from "react";
import { client } from "@/api";

const fmtBRL = (n) => (Number(n) || 0).toLocaleString("pt-BR",
  { style: "currency", currency: "BRL", maximumFractionDigits: 2 });
const fmtN = (n) => (Number(n) || 0).toLocaleString("pt-BR");

const PRIO_COLOR = { P0: "#ef4444", P1: "#fbbf24", P2: "#3b82f6" };
const KIND_LABEL = {
  credential: "🔑 Credencial",
  data_quality: "📊 Dados",
  api: "🌐 API",
};

export default function BlockersPanel() {
  const [data, setData] = useState(null);
  const [hs, setHs] = useState(null);
  const [busy, setBusy] = useState(false);
  const [lastHeal, setLastHeal] = useState(null);

  const load = () => {
    Promise.all([
      client.get("/ai-center/blockers/audit"),
      client.get("/ai-center/blockers/healing-score?days=7"),
    ]).then(([a, b]) => { setData(a.data); setHs(b.data); });
  };
  useEffect(() => { load(); }, []);

  const heal = async (key) => {
    if (!window.confirm(`Aplicar correção em ${key}?`)) return;
    setBusy(true);
    try {
      const r = await client.post(
        `/ai-center/blockers/heal?blocker_key=${encodeURIComponent(key)}`);
      setLastHeal(r.data);
      load();
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  if (!data) return <div style={{ color: "#94a3b8" }}>
    Auditando bloqueadores…
  </div>;

  return (
    <div data-testid="blockers-panel">
      <h2 style={{ color: "#f1f5f9", marginTop: 0, fontSize: 22 }}>
        Self Healing Center · V6.2
      </h2>

      {/* Self Healing Score badge */}
      {hs && (
        <div data-testid="self-healing-score-badge" style={{
          background: "linear-gradient(135deg, #064e3b 0%, #020617 100%)",
          border: "1px solid #10b98166",
          borderRadius: 12, padding: 16, marginBottom: 18,
          display: "flex", alignItems: "center", gap: 18,
        }}>
          <div style={{
            width: 90, height: 90, borderRadius: "50%",
            border: "3px solid #10b981",
            display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center",
            background: "#020617",
          }}>
            <div style={{ fontSize: 22, fontWeight: 900,
                            color: "#10b981" }}>{hs.score}%</div>
            <div style={{ fontSize: 8, color: "#94a3b8",
                            letterSpacing: 1.2 }}>SELF HEAL</div>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ color: "#6ee7b7", fontSize: 10,
                            letterSpacing: 1.5, fontWeight: 700,
                            textTransform: "uppercase" }}>
              Self Healing Score · 7 dias
            </div>
            <div style={{ color: "#f1f5f9", fontSize: 20,
                            fontWeight: 800, marginTop: 4 }}>
              {hs.classification?.replace(/_/g, " ")}
            </div>
            <div style={{ color: "#cbd5e1", fontSize: 12,
                            marginTop: 4 }}>
              ✓ {hs.auto_fixed} auto-corrigidos · ⚠ {hs.manual_required} manuais
              {hs.roi_BRL_recovered > 0 && (
                <span> · 💰 {fmtBRL(hs.roi_BRL_recovered)} recuperados</span>
              )}
            </div>
          </div>
        </div>
      )}

      <div style={{ background: "linear-gradient(135deg, #7f1d1d 0%, #020617 100%)",
                    border: "1px solid #ef444466",
                    borderRadius: 12, padding: 18, marginBottom: 18 }}>
        <div style={{ fontSize: 11, color: "#fca5a5",
                      letterSpacing: 1.5, fontWeight: 700,
                      textTransform: "uppercase" }}>
          Diagnóstico executivo
        </div>
        <div style={{ fontSize: 16, fontWeight: 700, color: "#f1f5f9",
                      marginTop: 6 }}>
          {data.headline}
        </div>
      </div>

      {lastHeal && (
        <div data-testid="last-heal-result" style={{
          background: "#064e3b22",
          border: "1px solid #10b98166", borderRadius: 8,
          padding: 14, marginBottom: 14,
        }}>
          <div style={{ color: "#10b981", fontWeight: 700,
                          fontSize: 12, letterSpacing: 1.2,
                          textTransform: "uppercase" }}>
            ✓ Última correção aplicada
          </div>
          <div style={{ color: "#cbd5e1", fontSize: 13,
                          marginTop: 4 }}>
            Status: <b>{lastHeal.status}</b> · Duração:{" "}
            <b>{lastHeal.duration_ms}ms</b>
            {lastHeal.fixed > 0 && <> · Registros corrigidos:{" "}
              <b>{lastHeal.fixed}</b></>}
            {lastHeal.roi_BRL_estimated > 0 && <> · ROI estimado:{" "}
              <b>{fmtBRL(lastHeal.roi_BRL_estimated)}</b></>}
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: 12, marginBottom: 18,
                    flexWrap: "wrap" }}>
        <Card testid="kpi-total" title="Bloqueadores"
              value={fmtN(data.summary.total_blockers)} color="#ef4444" />
        <Card testid="kpi-p0" title="P0 (crítico)"
              value={fmtN(data.summary.p0_count)} color="#ef4444" />
        <Card testid="kpi-p1" title="P1 (alto)"
              value={fmtN(data.summary.p1_count)} color="#fbbf24" />
        <Card testid="kpi-actions" title="Ações represadas (7d)"
              value={fmtN(data.summary.blocked_actions_7d)}
              color="#a78bfa" />
        <Card testid="kpi-blocked-brl" title="Receita congelada (7d)"
              value={fmtBRL(data.summary.blocked_revenue_BRL_7d)}
              color="#fbbf24" />
      </div>

      <div data-testid="blockers-list">
        {data.blockers.length === 0 ? (
          <div style={{ color: "#10b981", fontSize: 14, padding: 20,
                          background: "#064e3b22", borderRadius: 10,
                          border: "1px solid #10b98166" }}>
            ✓ Nenhum bloqueador detectado. A IA está livre para agir.
          </div>
        ) : data.blockers.map((b, i) => (
          <div key={i} data-testid={`blocker-${i}`}
               style={{ background: "#0f172a",
                          border: `1px solid ${PRIO_COLOR[b.priority]}66`,
                          borderRadius: 10, padding: 14, marginBottom: 10,
                          display: "flex", gap: 14,
                          alignItems: "flex-start" }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 11, color: "#94a3b8",
                              fontWeight: 700, letterSpacing: 1.4,
                              textTransform: "uppercase" }}>
                {KIND_LABEL[b.kind]} · {b.category}
              </div>
              <div style={{ fontSize: 16, fontWeight: 800,
                              color: "#f1f5f9", marginTop: 2,
                              fontFamily: "monospace" }}>
                {b.blocker}
              </div>
              <div style={{ fontSize: 13, color: "#cbd5e1",
                              marginTop: 6 }}>
                ↳ {b.how_to_resolve}
              </div>
              {b.impact_BRL_week > 0 && (
                <div style={{ fontSize: 12, color: "#fbbf24",
                                marginTop: 4, fontWeight: 600 }}>
                  💰 Impacto: <b>{fmtBRL(b.impact_BRL_week)}</b> represados
                  {" · "}{fmtN(b.actions_blocked)} ações bloqueadas
                </div>
              )}
              {b.count && (
                <div style={{ fontSize: 12, color: "#94a3b8",
                                marginTop: 2 }}>
                  {fmtN(b.count)} registros afetados
                </div>
              )}
            </div>
            <div style={{ display: "flex", flexDirection: "column",
                            alignItems: "flex-end", gap: 8 }}>
              <span style={{
                background: PRIO_COLOR[b.priority] + "33",
                color: PRIO_COLOR[b.priority],
                border: `1px solid ${PRIO_COLOR[b.priority]}`,
                padding: "4px 12px", borderRadius: 999,
                fontSize: 11, fontWeight: 800, letterSpacing: 1.5,
              }}>{b.priority}</span>
              {b.healing_available ? (
                <button data-testid={`heal-${b.blocker}`}
                        disabled={busy}
                        onClick={() => heal(b.blocker)}
                        style={{
                          background: "#10b981",
                          color: "#020617",
                          border: "none",
                          padding: "8px 14px",
                          borderRadius: 8,
                          cursor: "pointer",
                          fontWeight: 800,
                          fontSize: 12,
                          letterSpacing: 1,
                        }}>
                  🛠️ APLICAR CORREÇÃO
                </button>
              ) : (
                <span style={{ fontSize: 10, color: "#64748b",
                                  fontStyle: "italic" }}>
                  manual
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Card({ title, value, color, testid }) {
  return (
    <div data-testid={testid}
         style={{ background: "#0f172a",
                    border: `1px solid ${color}55`,
                    borderRadius: 12, padding: 14, flex: 1,
                    minWidth: 180 }}>
      <div style={{ fontSize: 10, color: "#94a3b8",
                    fontWeight: 700, letterSpacing: 1.4,
                    textTransform: "uppercase" }}>{title}</div>
      <div style={{ fontSize: 24, fontWeight: 800, color,
                    marginTop: 4 }}>{value}</div>
    </div>
  );
}
