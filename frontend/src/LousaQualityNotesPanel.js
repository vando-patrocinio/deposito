/*
LousaQualityNotesPanel.js — Aba "Notas" do Lousa Admin.

Lista chamados finalizados com sinal SmartOLT capturado automaticamente
na abertura e no fechamento, e classificação automática:
  • 🟢 BOM     — sinal estável/melhorou
  • 🟡 REGULAR — piorou < 3 dB (tolerável)
  • 🔴 RUIM    — piorou ≥ 3 dB ou pós-reparo em LOS

Inclui toggle global ON/OFF da feature e ajuste de thresholds.
*/
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { Card } from "@/ui";
import {
  Activity, AlertTriangle, CheckCircle2, Clock,
  Settings as SettingsIcon, Loader2,
} from "lucide-react";

const GRADE_STYLE = {
  bom:     { color: "#16a34a", bg: "#dcfce7", icon: "🟢", label: "BOM" },
  regular: { color: "#ca8a04", bg: "#fef3c7", icon: "🟡", label: "REGULAR" },
  ruim:    { color: "#dc2626", bg: "#fee2e2", icon: "🔴", label: "RUIM" },
};

function fmtDbm(v) {
  if (v == null) return "—";
  return `${Number(v).toFixed(1)} dBm`;
}
function fmtDt(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR",
      { dateStyle: "short", timeStyle: "short" });
  } catch { return iso.slice(0, 16); }
}

export default function LousaQualityNotesPanel() {
  const [data, setData] = useState(null);
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [days, setDays] = useState(30);
  const [showSettings, setShowSettings] = useState(false);
  const [savingCfg, setSavingCfg] = useState(false);
  const [filterGrade, setFilterGrade] = useState(null);

  const load = async () => {
    setLoading(true); setErr("");
    try {
      const r = await api.lousaQualityList(days);
      setData(r);
      setConfig(r.config);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [days]);

  const saveConfig = async (patch) => {
    setSavingCfg(true);
    try {
      const newCfg = await api.lousaQualitySaveConfig({ ...config, ...patch });
      setConfig(newCfg);
      if ("enabled" in patch || "degradation_threshold_db" in patch
          || "los_threshold_dbm" in patch) {
        await load();
      }
    } catch (e) {
      alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setSavingCfg(false); }
  };

  const isEnabled = config?.enabled !== false;
  const items = (data?.items || []).filter(
    (r) => !filterGrade || r.quality_grade === filterGrade,
  );

  return (
    <Card
      title={(
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <Activity size={16} /> Notas de Qualidade (sinal antes vs depois)
        </span>
      )}
      subtitle="Snapshot automático do sinal SmartOLT na abertura e fechamento de cada reparo."
      action={(
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}
                    data-testid="quality-days-select"
                    style={selectStyle}>
            <option value={7}>7 dias</option>
            <option value={30}>30 dias</option>
            <option value={90}>90 dias</option>
          </select>
          <button onClick={() => setShowSettings((v) => !v)}
                    data-testid="quality-settings-btn"
                    style={iconBtn}><SettingsIcon size={14} /></button>
          {/* Toggle ON/OFF estilo iOS */}
          <label style={{
            position: "relative", display: "inline-block",
            width: 44, height: 22, marginLeft: 4,
          }} title={isEnabled ? "Serviço ligado — desligar" : "Serviço desligado — ligar"}>
            <input type="checkbox" checked={isEnabled}
                     onChange={(e) => saveConfig({ enabled: e.target.checked })}
                     disabled={savingCfg}
                     data-testid="quality-toggle"
                     style={{ opacity: 0, width: 0, height: 0 }} />
            <span style={{
              position: "absolute", cursor: "pointer", inset: 0,
              background: isEnabled ? "#10b981" : "#cbd5e1",
              borderRadius: 999, transition: "0.2s",
            }} />
            <span style={{
              position: "absolute", top: 3, left: isEnabled ? 25 : 3,
              width: 16, height: 16, borderRadius: "50%",
              background: "#fff", transition: "0.2s",
              boxShadow: "0 2px 4px rgba(0,0,0,0.2)",
            }} />
          </label>
        </div>
      )}
      data-testid="quality-notes-panel"
    >
      {err && (
        <div style={{ padding: 10, background: "#fef2f2", color: "#991b1b",
                        borderRadius: 8, fontSize: 12, marginBottom: 10 }}>
          {err}
        </div>
      )}

      {!isEnabled && (
        <div style={{
          padding: 14, background: "#f1f5f9", borderRadius: 8,
          fontSize: 13, color: "#475569", textAlign: "center",
        }}>
          🔌 Serviço de notas de qualidade está <strong>desligado</strong>.
          Os tickets continuam funcionando normalmente, mas o sinal não é
          capturado automaticamente. Ative o toggle acima pra começar.
        </div>
      )}

      {showSettings && config && (
        <div data-testid="quality-settings-panel"
              style={{
                padding: 12, marginBottom: 12, borderRadius: 8,
                background: "#f8fafc", border: "1px dashed #cbd5e1",
              }}>
          <div style={{ display: "grid",
                          gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <label style={lblStyle}>
              Limite degradação (dB)
              <input type="number" min="0.5" max="20" step="0.5"
                       value={config.degradation_threshold_db}
                       onChange={(e) => saveConfig({
                         degradation_threshold_db: Number(e.target.value),
                       })}
                       data-testid="quality-degradation-input"
                       style={inputStyle} />
              <span style={hintStyle}>
                Acima disso, ticket é classificado como RUIM
              </span>
            </label>
            <label style={lblStyle}>
              Limite LOS (dBm)
              <input type="number" min="-40" max="-15" step="0.5"
                       value={config.los_threshold_dbm}
                       onChange={(e) => saveConfig({
                         los_threshold_dbm: Number(e.target.value),
                       })}
                       data-testid="quality-los-input"
                       style={inputStyle} />
              <span style={hintStyle}>
                Pós-reparo abaixo disso = RUIM automático
              </span>
            </label>
          </div>
        </div>
      )}

      {/* Resumo */}
      {data?.summary && isEnabled && (
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
          gap: 10, marginBottom: 12,
        }}>
          {["bom", "regular", "ruim"].map((g) => {
            const s = GRADE_STYLE[g];
            const active = filterGrade === g;
            return (
              <button key={g}
                        onClick={() => setFilterGrade(active ? null : g)}
                        data-testid={`quality-filter-${g}`}
                        style={{
                          padding: 10, border: active
                            ? `2px solid ${s.color}` : "1px solid #e2e8f0",
                          background: s.bg,
                          borderRadius: 10, cursor: "pointer",
                          textAlign: "left",
                        }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: s.color,
                                textTransform: "uppercase",
                                letterSpacing: 0.3 }}>
                  {s.icon} {s.label}
                </div>
                <div style={{ fontSize: 22, fontWeight: 800, color: s.color }}>
                  {data.summary[g]}
                </div>
              </button>
            );
          })}
        </div>
      )}

      {loading && <div style={{ padding: 12 }}>
        <Loader2 size={14} className="animate-spin" /> Carregando…
      </div>}

      {!loading && items.length === 0 && (
        <div style={{ padding: 24, textAlign: "center", fontSize: 13,
                        color: "#64748b" }}>
          Nenhum chamado com sinal capturado nesse período.
          {isEnabled && (
            <div style={{ marginTop: 6, fontSize: 11, opacity: 0.8 }}>
              O sinal só é capturado quando a ONU está mapeada no SmartOLT.
            </div>
          )}
        </div>
      )}

      <div style={{ display: "grid", gap: 8 }} data-testid="quality-items-list">
        {items.map((r) => {
          const s = GRADE_STYLE[r.quality_grade] || GRADE_STYLE.regular;
          const before = r.signal_at_open?.rx_dbm;
          const after = r.signal_at_close?.rx_dbm;
          const delta = r.quality_delta_db;
          return (
            <div key={r.id}
                   data-testid={`quality-row-${r.id}`}
                   style={{
                     padding: 11, borderRadius: 10,
                     background: "#fff",
                     border: `1px solid ${s.color}33`,
                     borderLeft: `4px solid ${s.color}`,
                     display: "grid",
                     gridTemplateColumns: "auto 1fr auto",
                     gap: 12, alignItems: "center",
                   }}>
              <div style={{ minWidth: 80, textAlign: "center" }}>
                <div style={{ fontSize: 10, fontWeight: 700,
                                color: s.color, textTransform: "uppercase" }}>
                  {s.icon} {s.label}
                </div>
                <div style={{ fontSize: 13, fontWeight: 800, color: s.color,
                                marginTop: 2, fontVariantNumeric: "tabular-nums" }}>
                  {delta > 0 ? `+${delta}` : delta} dB
                </div>
              </div>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>
                  {r.client_snapshot?.name || "—"}
                </div>
                <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
                  {r.type} · {r.outcome || "—"}
                  {r.closed_by_name && ` · Técnico: ${r.closed_by_name}`}
                </div>
                <div style={{ fontSize: 11.5, color: "#475569",
                                marginTop: 4, fontVariantNumeric: "tabular-nums" }}>
                  <span style={{ background: "#f1f5f9", padding: "1px 6px",
                                  borderRadius: 4, marginRight: 4 }}>
                    Antes: <strong>{fmtDbm(before)}</strong>
                  </span>
                  →
                  <span style={{ background: s.bg, padding: "1px 6px",
                                  borderRadius: 4, marginLeft: 4 }}>
                    Depois: <strong style={{ color: s.color }}>
                      {fmtDbm(after)}
                    </strong>
                  </span>
                </div>
                <div style={{ fontSize: 10.5, color: "#94a3b8", marginTop: 3 }}>
                  💡 {r.quality_reason}
                </div>
              </div>
              <div style={{ fontSize: 10, color: "#64748b", textAlign: "right" }}>
                <Clock size={10} style={{ verticalAlign: "middle" }} />
                {" "}{fmtDt(r.closed_at)}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

const selectStyle = {
  padding: "5px 10px", border: "1px solid #cbd5e1",
  borderRadius: 6, fontSize: 12, background: "#fff",
};
const iconBtn = {
  padding: 6, border: "1px solid #cbd5e1", background: "#fff",
  borderRadius: 6, cursor: "pointer",
};
const inputStyle = {
  padding: "6px 10px", border: "1px solid #cbd5e1",
  borderRadius: 6, fontSize: 13, marginTop: 4, width: "100%",
  boxSizing: "border-box",
};
const lblStyle = {
  display: "flex", flexDirection: "column",
  fontSize: 11, color: "#475569", fontWeight: 600,
};
const hintStyle = {
  fontSize: 10, color: "#94a3b8", marginTop: 3, fontWeight: 400,
};
