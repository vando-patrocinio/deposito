/* =============================================================
   CentralOntPanel — sub-aba do Chamados (LousaAdminPanel).
   - Toggle "Bloquear fechamento com sinal ruim" + threshold
   - Relatório N dias: total, bad, % por técnico, lista de notas ruins
   - Solicitações pendentes de autorização (Aprovar/Rejeitar)
============================================================= */
import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import { fmtAddress } from "@/utils/format";
import { Card } from "@/ui";
import {
  AlertTriangle, ShieldCheck, ShieldOff, Check, X,
  Radio, Loader2, RefreshCw,
} from "lucide-react";

export default function CentralOntPanel() {
  const [tab, setTab] = useState("report");
  const [settings, setSettings] = useState(null);
  const [report, setReport] = useState(null);
  const [authReqs, setAuthReqs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [savingSettings, setSavingSettings] = useState(false);
  const [days, setDays] = useState(30);
  // iter223 — geofence radius configurável
  const [geo, setGeo] = useState(null);
  const [savingGeo, setSavingGeo] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, r, ar, geo] = await Promise.all([
        api._client.get("/lousa/central-ont/settings").then((x) => x.data),
        api._client.get(`/lousa/central-ont/report?days=${days}`)
                    .then((x) => x.data),
        api._client.get("/lousa/central-ont/auth-requests?status=pending")
                    .then((x) => x.data),
        api._client.get("/lousa/geofence/settings").then((x) => x.data),
      ]);
      setSettings(s);
      setReport(r);
      setAuthReqs(ar.items || []);
      setGeo(geo);
    } catch (e) {
      console.error("[CentralOnt] load", e);
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { load(); }, [load]);
  // Poll auth requests a cada 8s
  useEffect(() => {
    const t = setInterval(async () => {
      try {
        const ar = await api._client.get(
          "/lousa/central-ont/auth-requests?status=pending",
        ).then((x) => x.data);
        setAuthReqs(ar.items || []);
      } catch { /* silent */ }
    }, 8000);
    return () => clearInterval(t);
  }, []);

  const saveSettings = async (patch) => {
    setSavingSettings(true);
    try {
      const next = { ...settings, ...patch };
      await api._client.put("/lousa/central-ont/settings", {
        block_bad_signal_close: next.block_bad_signal_close,
        bad_signal_threshold: next.bad_signal_threshold,
      });
      setSettings(next);
    } catch (e) {
      await window.alert("Falha ao salvar: " + (e?.response?.data?.detail || e.message));
    } finally {
      setSavingSettings(false);
    }
  };

  const saveGeoRadius = async (radius_m) => {
    const val = Math.max(20, Math.min(5000, parseInt(radius_m, 10) || 100));
    setSavingGeo(true);
    try {
      await api._client.put("/lousa/geofence/settings", {
        geofence_radius_m: val,
      });
      setGeo((g) => ({ ...g, geofence_radius_m: val }));
    } catch (e) {
      await window.alert("Falha ao salvar raio: " +
        (e?.response?.data?.detail || e.message));
    } finally {
      setSavingGeo(false);
    }
  };

  const decide = async (id, action) => {
    try {
      await api._client.post(
        `/lousa/central-ont/auth-requests/${id}/${action}`);
      await load();
    } catch (e) {
      await window.alert("Falha: " + (e?.response?.data?.detail || e.message));
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: "#94a3b8" }}>
        <Loader2 size={28} className="wa-spin" />
        <div style={{ marginTop: 8, fontSize: 12 }}>Carregando CENTRAL_ONT...</div>
      </div>
    );
  }

  return (
    <div data-testid="central-ont-panel" style={{ display: "grid", gap: 14 }}>
      {/* HEADER */}
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "center", flexWrap: "wrap", gap: 10 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700,
                        color: "#0f172a",
                        display: "flex", alignItems: "center", gap: 8 }}>
            <Radio size={18} color="#0ea5e9" /> CENTRAL_ONT
          </h2>
          <p style={{ margin: "2px 0 0", fontSize: 11, color: "#64748b" }}>
            Controle de fechamento por qualidade de sinal · auditoria de notas
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}
                   data-testid="central-ont-days"
                   style={{ padding: "5px 8px", borderRadius: 6,
                             border: "1px solid #cbd5e1", fontSize: 12 }}>
            <option value={7}>7 dias</option>
            <option value={30}>30 dias</option>
            <option value={90}>90 dias</option>
            <option value={365}>1 ano</option>
          </select>
          <button onClick={load} title="Atualizar"
                   style={{ padding: 6, borderRadius: 6,
                             border: "1px solid #cbd5e1", background: "white",
                             cursor: "pointer" }}>
            <RefreshCw size={14} color="#475569" />
          </button>
        </div>
      </div>

      {/* SETTINGS */}
      <Card>
        <div style={{ padding: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "center", flexWrap: "wrap", gap: 12 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a",
                              display: "inline-flex", alignItems: "center",
                              gap: 6 }}>
                {settings?.block_bad_signal_close
                  ? <ShieldCheck size={16} color="#dc2626" />
                  : <ShieldOff size={16} color="#94a3b8" />}
                Bloquear fechamento com sinal ruim
              </div>
              <p style={{ margin: "3px 0 0", fontSize: 11, color: "#64748b" }}>
                Quando ativo, técnicos não podem fechar bolha com sinal
                abaixo do limite — precisam de autorização do gestor.
              </p>
            </div>
            <ToggleSwitch checked={settings?.block_bad_signal_close || false}
                            onChange={(v) => saveSettings({ block_bad_signal_close: v })}
                            disabled={savingSettings}
                            testid="central-ont-block-toggle" />
          </div>
          <div style={{ marginTop: 14, display: "flex", gap: 10,
                          alignItems: "center", flexWrap: "wrap" }}>
            <label style={{ fontSize: 12, color: "#475569", fontWeight: 600 }}>
              Limite (dBm):
            </label>
            <input type="number" step="0.5"
                    value={settings?.bad_signal_threshold ?? -27}
                    data-testid="central-ont-threshold"
                    onChange={(e) => setSettings({
                      ...settings,
                      bad_signal_threshold: Number(e.target.value),
                    })}
                    onBlur={(e) => saveSettings({
                      bad_signal_threshold: Number(e.target.value),
                    })}
                    style={{ padding: "6px 10px", borderRadius: 6,
                              border: "1px solid #cbd5e1", fontSize: 13,
                              width: 90, fontFamily: "monospace" }} />
            <span style={{ fontSize: 11, color: "#94a3b8" }}>
              Acima desse valor (mais negativo = pior) considera-se sinal ruim.
              Padrão -27 dBm.
            </span>
          </div>
        </div>
      </Card>

      {/* iter223 — GEOFENCE RADIUS */}
      <Card>
        <div style={{ padding: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "center", flexWrap: "wrap", gap: 12 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a",
                              display: "inline-flex", alignItems: "center",
                              gap: 6 }}>
                <Radio size={16} color="#7c3aed" />
                Raio de geofence (finalização da OS)
              </div>
              <p style={{ margin: "3px 0 0", fontSize: 11, color: "#64748b" }}>
                O técnico só pode finalizar a OS quando estiver dentro
                desse raio do endereço cadastrado do cliente. Aumente se
                houver imprecisão de geocoding ou serviços executados em
                pontos próximos. Aceita 20m – 5000m.
              </p>
            </div>
            <div style={{ display: "inline-flex", alignItems: "center",
                            gap: 8 }}>
              <input type="number" min={20} max={5000} step={10}
                      data-testid="geofence-radius-input"
                      value={geo?.geofence_radius_m ?? 100}
                      disabled={savingGeo}
                      onChange={(e) => setGeo((g) => ({
                        ...g,
                        geofence_radius_m: parseInt(e.target.value, 10) || 0,
                      }))}
                      onBlur={(e) => saveGeoRadius(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") saveGeoRadius(e.target.value);
                      }}
                      style={{ padding: "8px 12px", borderRadius: 8,
                                border: "1px solid #cbd5e1", fontSize: 14,
                                width: 110, fontFamily: "monospace",
                                fontWeight: 800, textAlign: "right" }} />
              <span style={{ fontSize: 13, color: "#475569", fontWeight: 700 }}>
                metros
              </span>
            </div>
          </div>
          <div style={{ marginTop: 12, display: "flex", gap: 8,
                          flexWrap: "wrap" }}>
            {[100, 200, 500, 1000].map((preset) => (
              <button key={preset} type="button"
                  data-testid={`geofence-preset-${preset}`}
                  onClick={() => saveGeoRadius(preset)}
                  disabled={savingGeo}
                  style={{
                    padding: "6px 14px", borderRadius: 999,
                    border: `1.5px solid ${geo?.geofence_radius_m === preset
                      ? "#7c3aed" : "#cbd5e1"}`,
                    background: geo?.geofence_radius_m === preset
                      ? "#ede9fe" : "white",
                    color: geo?.geofence_radius_m === preset
                      ? "#5b21b6" : "#475569",
                    fontSize: 12, fontWeight: 800,
                    cursor: savingGeo ? "wait" : "pointer",
                  }}>{preset}m</button>
            ))}
            {geo?.updated_at && (
              <span style={{ marginLeft: "auto", fontSize: 10.5,
                              color: "#94a3b8", alignSelf: "center" }}>
                atualizado por {geo.updated_by} ·{" "}
                {new Date(geo.updated_at).toLocaleString("pt-BR")}
              </span>
            )}
          </div>
        </div>
      </Card>

      {/* AUTH REQUESTS pending */}
      {authReqs.length > 0 && (
        <Card>
          <div style={{ padding: 14, borderBottom: "1px solid #e2e8f0",
                          display: "flex", justifyContent: "space-between",
                          alignItems: "center" }}>
            <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700,
                          color: "#0f172a",
                          display: "inline-flex", gap: 6, alignItems: "center" }}>
              <AlertTriangle size={15} color="#f59e0b" />
              Solicitações de autorização
              <span style={{ padding: "1px 8px", borderRadius: 999,
                              background: "#f59e0b", color: "white",
                              fontSize: 10, fontWeight: 800 }}>
                {authReqs.length}
              </span>
            </h3>
          </div>
          {authReqs.map((r) => (
            <AuthReqRow key={r.id} req={r}
                          onApprove={() => decide(r.id, "approve")}
                          onReject={() => decide(r.id, "reject")} />
          ))}
        </Card>
      )}

      {/* TABS report / list */}
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid #e2e8f0" }}>
        {[
          { id: "report", label: "Por técnico" },
          { id: "list", label: `Notas com sinal ruim (${report?.bad_signal_closes ?? 0})` },
        ].map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
                   data-testid={`central-ont-tab-${t.id}`}
                   style={{
                     padding: "10px 16px", border: "none",
                     background: "transparent", cursor: "pointer",
                     fontSize: 12, fontWeight: tab === t.id ? 700 : 500,
                     color: tab === t.id ? "#0ea5e9" : "#64748b",
                     borderBottom: "2px solid " + (tab === t.id ? "#0ea5e9" : "transparent"),
                     marginBottom: -1,
                   }}>{t.label}</button>
        ))}
      </div>

      {/* KPI cards */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
        gap: 8,
      }}>
        <KpiCard label="Notas fechadas" value={report?.total_closes ?? 0} />
        <KpiCard label="Sinal ruim"
                   value={report?.bad_signal_closes ?? 0}
                   color="#dc2626" />
        <KpiCard label="% sinal ruim"
                   value={`${report?.overall_ratio_pct ?? 0}%`}
                   color={(report?.overall_ratio_pct ?? 0) > 10 ? "#dc2626" : "#16a34a"} />
        <KpiCard label="Limite"
                   value={`${report?.threshold ?? -27} dBm`}
                   mono color="#64748b" />
      </div>

      {tab === "report" ? (
        <Card>
          <table style={{ width: "100%", fontSize: 12,
                            borderCollapse: "collapse" }}>
            <thead style={{ background: "#f8fafc" }}>
              <tr style={{ textAlign: "left" }}>
                <Th>Técnico</Th>
                <Th align="right">Total</Th>
                <Th align="right">Sinal ruim</Th>
                <Th align="right">%</Th>
                <Th>Barra</Th>
              </tr>
            </thead>
            <tbody>
              {(report?.per_collaborator || []).map((c) => (
                <tr key={c.collaborator_id}
                     data-testid={`central-ont-row-${c.collaborator_id}`}
                     style={{ borderTop: "1px solid #f1f5f9" }}>
                  <td style={{ padding: "8px 12px", fontWeight: 600,
                                color: "#0f172a" }}>{c.collaborator_name}</td>
                  <td style={tdR}>{c.total_closes}</td>
                  <td style={{ ...tdR,
                                 color: c.bad_signal_closes > 0 ? "#dc2626" : "#16a34a",
                                 fontWeight: 700 }}>
                    {c.bad_signal_closes}
                  </td>
                  <td style={{ ...tdR, fontWeight: 700,
                                 color: c.ratio_pct >= 20 ? "#dc2626"
                                       : c.ratio_pct >= 10 ? "#ca8a04" : "#16a34a" }}>
                    {c.ratio_pct}%
                  </td>
                  <td style={{ padding: "8px 12px", width: 200 }}>
                    <div style={{ height: 8, background: "#f1f5f9",
                                    borderRadius: 4, overflow: "hidden" }}>
                      <div style={{
                        height: "100%",
                        width: `${Math.min(c.ratio_pct, 100)}%`,
                        background: c.ratio_pct >= 20 ? "#dc2626"
                                    : c.ratio_pct >= 10 ? "#f59e0b" : "#16a34a",
                        transition: "width 300ms",
                      }} />
                    </div>
                  </td>
                </tr>
              ))}
              {(report?.per_collaborator || []).length === 0 && (
                <tr><td colSpan={5} style={{
                  padding: 24, textAlign: "center", color: "#94a3b8",
                  fontSize: 12,
                }}>Nenhuma finalização no período.</td></tr>
              )}
            </tbody>
          </table>
        </Card>
      ) : (
        <Card>
          <div style={{ padding: 4 }}>
            {(report?.items || []).map((it) => (
              <div key={it.ticket_id} style={{
                padding: "10px 14px", borderBottom: "1px solid #f1f5f9",
                display: "flex", justifyContent: "space-between",
                alignItems: "center", flexWrap: "wrap", gap: 8,
              }}>
                <div style={{ flex: 1, minWidth: 220 }}>
                  <div style={{ fontSize: 13, fontWeight: 700,
                                 color: "#0f172a" }}>
                    {it.client_name}
                    {it.auth_used && (
                      <span style={{
                        marginLeft: 6, padding: "1px 6px", borderRadius: 4,
                        background: "#dcfce7", color: "#166534",
                        fontSize: 9, fontWeight: 800, letterSpacing: 0.3,
                      }}>AUTORIZADO</span>
                    )}
                  </div>
                  <div style={{ fontSize: 11, color: "#64748b" }}>
                    {fmtAddress(it.address)} · ONT {it.ont || "—"}
                  </div>
                  <div style={{ fontSize: 10, color: "#94a3b8" }}>
                    {it.collaborator_name} · {new Date(it.closed_at)
                      .toLocaleString("pt-BR")}
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div style={{
                    fontSize: 14, fontWeight: 800, color: "#dc2626",
                    fontFamily: "monospace",
                  }}>{it.sinal?.toFixed(1)} dBm</div>
                  <div style={{ fontSize: 10, color: "#94a3b8" }}>
                    Limite {report?.threshold}
                  </div>
                </div>
              </div>
            ))}
            {(report?.items || []).length === 0 && (
              <div style={{ padding: 24, textAlign: "center", color: "#16a34a",
                              fontSize: 12 }}>
                ✓ Nenhuma nota com sinal ruim no período.
              </div>
            )}
          </div>
        </Card>
      )}
      <style>{`
        .wa-spin { animation: wa-spin 1s linear infinite; }
        @keyframes wa-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}

const Th = ({ children, align = "left" }) => (
  <th style={{ padding: "10px 12px", fontSize: 10, fontWeight: 700,
                color: "#64748b", textTransform: "uppercase",
                letterSpacing: 0.5, textAlign: align }}>{children}</th>
);
const tdR = { padding: "8px 12px", textAlign: "right",
                 fontFamily: "monospace", color: "#0f172a" };

function KpiCard({ label, value, color, mono }) {
  return (
    <div style={{
      padding: 12, borderRadius: 10, background: "white",
      border: "1px solid #e2e8f0",
    }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8",
                     textTransform: "uppercase", letterSpacing: 0.5,
                     marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 19, fontWeight: 700,
                     color: color || "#0f172a",
                     fontFamily: mono ? "monospace" : "inherit" }}>{value}</div>
    </div>
  );
}

function ToggleSwitch({ checked, onChange, disabled, testid }) {
  return (
    <button
      type="button"
      data-testid={testid}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      style={{
        width: 48, height: 26, borderRadius: 999, border: "none",
        background: checked ? "#dc2626" : "#cbd5e1",
        position: "relative", cursor: disabled ? "wait" : "pointer",
        transition: "background 180ms", padding: 0,
      }}>
      <span style={{
        position: "absolute", top: 3, left: checked ? 25 : 3,
        width: 20, height: 20, borderRadius: "50%", background: "white",
        transition: "left 180ms",
        boxShadow: "0 1px 3px rgba(0,0,0,0.25)",
      }} />
    </button>
  );
}

function AuthReqRow({ req, onApprove, onReject }) {
  return (
    <div data-testid={`auth-req-${req.id}`}
          style={{ padding: "12px 14px", borderTop: "1px solid #f1f5f9",
                    display: "flex", gap: 10, alignItems: "center",
                    flexWrap: "wrap" }}>
      <div style={{ flex: 1, minWidth: 220 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a" }}>
          {req.collaborator_name} → {req.client_name}
        </div>
        <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
          Quer fechar com <strong style={{ color: "#dc2626" }}>
            {req.sinal?.toFixed(1)} dBm
          </strong> (limite {req.threshold}). Pedido às{" "}
          {new Date(req.requested_at).toLocaleString("pt-BR")}.
        </div>
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        <button onClick={onReject}
                 data-testid={`auth-req-${req.id}-reject`}
                 style={{
                   padding: "6px 12px", borderRadius: 6, fontSize: 12,
                   fontWeight: 700, border: "1px solid #fecaca",
                   background: "white", color: "#dc2626", cursor: "pointer",
                   display: "inline-flex", alignItems: "center", gap: 4,
                 }}>
          <X size={12} /> Rejeitar
        </button>
        <button onClick={onApprove}
                 data-testid={`auth-req-${req.id}-approve`}
                 style={{
                   padding: "6px 12px", borderRadius: 6, fontSize: 12,
                   fontWeight: 700, border: "none",
                   background: "#16a34a", color: "white", cursor: "pointer",
                   display: "inline-flex", alignItems: "center", gap: 4,
                 }}>
          <Check size={12} /> Aprovar
        </button>
      </div>
    </div>
  );
}
