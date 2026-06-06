/*
 * SecurityHomePage.js — Painel admin de Segurança Residencial.
 * MVP: lista de sites (imóveis) + arm/disarm + alarmes ativos.
 * Estilo espelha o Fleet Tracking.
 */
import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";

const ARM_LABEL = {
  armed_away: { icon: "", label: "Armado total", color: "#dc2626" },
  armed_stay: { icon: "", label: "Armado parcial", color: "#f59e0b" },
  disarmed: { icon: "", label: "Desarmado", color: "#10b981" },
  panic: { icon: "", label: "PÂNICO", color: "#dc2626" },
};

const SEVERITY_COLOR = {
  critical: "#dc2626", high: "#ef4444", medium: "#f59e0b",
  low: "#3b82f6", info: "#10b981",
};

export default function SecurityHomePage() {
  const [tab, setTab] = useState("sites");
  const [sites, setSites] = useState([]);
  const [alarms, setAlarms] = useState([]);
  const [showForm, setShowForm] = useState(null);
  const [showSensorsFor, setShowSensorsFor] = useState(null);

  const refresh = async () => {
    try {
      const [s, a] = await Promise.all([
        api._client.get("/security-home/sites").then((x) => x.data),
        api._client.get("/security-home/alarms?acked=false&limit=100")
          .then((x) => x.data),
      ]);
      setSites(s); setAlarms(a);
    } catch { /* */ }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 8000);
    return () => clearInterval(id);
  }, []);

  const kpis = useMemo(() => ({
    total: sites.length,
    armed: sites.filter((s) => s.arm_state?.startsWith("armed")).length,
    disarmed: sites.filter((s) => s.arm_state === "disarmed").length,
    alarms: alarms.length,
  }), [sites, alarms]);

  const arm = async (sid, mode) => {
    await api._client.post(`/security-home/sites/${sid}/arm?mode=${mode}`);
    refresh();
  };
  const disarm = async (sid) => {
    await api._client.post(`/security-home/sites/${sid}/disarm`);
    refresh();
  };
  const ackAlarm = async (aid) => {
    await api._client.post(`/security-home/alarms/${aid}/ack?resolution=verificado`);
    refresh();
  };

  return (
    <div data-testid="security-home-page" style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                     alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>
            Segurança Residencial
          </h1>
          <p style={{ color: "#64748b", fontSize: 12, margin: "2px 0 0" }}>
            Monitoramento de centrais de alarme (estilo Verisure).
          </p>
        </div>
        <button onClick={() => setShowForm({})}
                 data-testid="sh-add-site"
                 style={primaryBtn}>
          + Cadastrar imóvel
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)",
                     gap: 8 }}>
        <Kpi label="Imóveis" value={kpis.total} color="#0f172a" />
        <Kpi label="Armados" value={kpis.armed} color="#dc2626" />
        <Kpi label="Desarmados" value={kpis.disarmed} color="#10b981" />
        <Kpi label="Alarmes ativos" value={kpis.alarms} color="#ef4444"
              pulse={kpis.alarms > 0} />
      </div>

      <div style={tabBar}>
        {[["sites", "Imóveis"], ["alarms", "Alarmes"]].map(([k, v]) => (
          <button key={k} onClick={() => setTab(k)}
                   style={tab === k ? tabActive : tabIdle}
                   data-testid={`sh-tab-${k}`}>{v}</button>
        ))}
      </div>

      {tab === "sites" && (
        <div style={card}>
          {!sites.length ? (
            <div style={empty}>Nenhum imóvel cadastrado.</div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse",
                              fontSize: 13 }}>
              <thead>
                <tr style={{ background: "#f8fafc" }}>
                  <th style={th}>Nome</th>
                  <th style={th}>Painel</th>
                  <th style={th}>Estado</th>
                  <th style={th}>Endereço</th>
                  <th style={th}>Ações</th>
                </tr>
              </thead>
              <tbody>
                {sites.map((s) => {
                  const armInfo = ARM_LABEL[s.arm_state || "disarmed"]
                    || ARM_LABEL.disarmed;
                  return (
                    <tr key={s.id} data-testid={`sh-site-${s.id}`}>
                      <td style={td}><b>{s.name}</b></td>
                      <td style={td}><code>{s.panel_id}</code></td>
                      <td style={td}>
                        <span style={{ color: armInfo.color,
                                         fontWeight: 700 }}>
                          {armInfo.icon} {armInfo.label}
                        </span>
                      </td>
                      <td style={td}>
                        <span style={{ fontSize: 11, color: "#64748b" }}>
                          {s.address || "—"}
                        </span>
                      </td>
                      <td style={td}>
                        <button onClick={() => arm(s.id, "away")}
                                 style={miniBtn("#dc2626")}
                                 data-testid={`sh-arm-away-${s.id}`}>
                          Armar
                        </button>
                        <button onClick={() => arm(s.id, "stay")}
                                 style={miniBtn("#f59e0b")}>
                          Parcial
                        </button>
                        <button onClick={() => disarm(s.id)}
                                 style={miniBtn("#10b981")}
                                 data-testid={`sh-disarm-${s.id}`}>
                          Desarmar
                        </button>
                        <button onClick={() => setShowSensorsFor(s)}
                                 style={miniBtn("#3b82f6")}>
                          ️ Sensores
                        </button>
                        <button onClick={() => setShowForm(s)}
                                 style={miniBtn("#64748b")}>
                          ✏️
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "alarms" && (
        <div style={card}>
          {!alarms.length ? (
            <div style={empty}>
              <span style={{ fontSize: 32 }}></span>
              <div>Nenhum alarme ativo.</div>
            </div>
          ) : alarms.map((a) => {
            const site = sites.find((x) => x.id === a.site_id);
            return (
              <div key={a.id} data-testid={`sh-alarm-${a.id}`}
                    style={{ ...alarmRow,
                              borderLeftColor: SEVERITY_COLOR[a.severity]
                                || "#64748b" }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 700, fontSize: 14 }}>
                    {a.label}
                  </div>
                  <div style={{ fontSize: 11, color: "#64748b",
                                  marginTop: 2 }}>
                    {site?.name || a.site_id}
                    {a.contact_zone > 0 && ` · Zona ${a.contact_zone}`}
                    {" · "}
                    {new Date(a.ts).toLocaleString("pt-BR")}
                  </div>
                </div>
                <span style={{ ...severityChip,
                                 background: SEVERITY_COLOR[a.severity] }}>
                  {a.severity.toUpperCase()}
                </span>
                <button onClick={() => ackAlarm(a.id)}
                         style={primaryBtn}
                         data-testid={`sh-ack-${a.id}`}>
                  ✓ Atender
                </button>
              </div>
            );
          })}
        </div>
      )}

      {showForm && (
        <SiteForm initial={showForm.id ? showForm : null}
                   onClose={() => setShowForm(null)}
                   onSaved={() => { setShowForm(null); refresh(); }} />
      )}
      {showSensorsFor && (
        <SensorsModal site={showSensorsFor}
                        onClose={() => setShowSensorsFor(null)} />
      )}
    </div>
  );
}

function Kpi({ label, value, color, pulse }) {
  return (
    <div style={{ background: "white", border: "1px solid #e2e8f0",
                    borderRadius: 10, padding: 14,
                    borderTop: `3px solid ${color}`,
                    animation: pulse ? "shAlarmPulse 1.5s ease infinite"
                      : "none" }}>
      <div style={{ fontSize: 24, fontWeight: 800, color }}>{value}</div>
      <div style={{ fontSize: 11, color: "#64748b",
                      textTransform: "uppercase", letterSpacing: 0.5 }}>
        {label}
      </div>
    </div>
  );
}

function SiteForm({ initial, onClose, onSaved }) {
  const [f, setF] = useState({
    name: initial?.name || "", address: initial?.address || "",
    panel_id: initial?.panel_id || "",
    panel_model: initial?.panel_model || "Intelbras AMT 8000",
    panel_password: initial?.panel_password || "1234",
    security_tenant_id: initial?.security_tenant_id || "",
    notes: initial?.notes || "",
    active: initial?.active ?? true,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const save = async () => {
    setBusy(true); setErr("");
    try {
      if (initial?.id) {
        await api._client.put(`/security-home/sites/${initial.id}`, f);
      } else {
        await api._client.post("/security-home/sites", f);
      }
      onSaved?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  };
  return (
    <div style={overlay} data-testid="sh-site-form">
      <div style={modal}>
        <h3 style={{ margin: "0 0 12px" }}>
          {initial?.id ? `Editar ${initial.name}` : "Cadastrar imóvel"}
        </h3>
        {[
          ["name", "Nome do imóvel *"],
          ["address", "Endereço"],
          ["panel_id", "ID do painel (conta Contact ID) *"],
          ["panel_model", "Modelo da central"],
          ["panel_password", "Senha do painel"],
          ["security_tenant_id", "Cliente (tenant) — opcional"],
        ].map(([k, lbl]) => (
          <label key={k} style={{ fontSize: 11, color: "#475569",
                                   display: "block", marginBottom: 8 }}>
            {lbl}
            <input value={f[k]} onChange={(e) =>
              setF({ ...f, [k]: e.target.value })}
                    style={inp}
                    data-testid={`sh-vform-${k}`} />
          </label>
        ))}
        <textarea value={f.notes}
                    onChange={(e) => setF({ ...f, notes: e.target.value })}
                    placeholder="Observações"
                    style={{ ...inp, minHeight: 60 }} />
        {err && <div style={errBox}>{err}</div>}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end",
                       marginTop: 12 }}>
          <button onClick={onClose} style={secBtn}>Cancelar</button>
          <button onClick={save} disabled={busy} style={primaryBtn}
                   data-testid="sh-vform-save">
            {busy ? "Salvando…" : "Salvar"}
          </button>
        </div>
      </div>
    </div>
  );
}

function SensorsModal({ site, onClose }) {
  const [sensors, setSensors] = useState([]);
  const [form, setForm] = useState({
    label: "", kind: "magnetic", contact_zone: 1,
    plant_x: 0.5, plant_y: 0.5,
  });
  const reload = () => api._client.get(`/security-home/sites/${site.id}/sensors`)
    .then((r) => setSensors(r.data));
  useEffect(() => { reload(); /* eslint-disable-next-line */ }, []);
  const create = async () => {
    if (!form.label) return;
    try {
      await api._client.post(`/security-home/sites/${site.id}/sensors`, form);
      setForm({ label: "", kind: "magnetic", contact_zone: 1,
                 plant_x: 0.5, plant_y: 0.5 });
      reload();
    } catch (e) { alert(e?.response?.data?.detail || e.message); }
  };
  const del = async (id) => {
    if (!window.confirm("Remover sensor?")) return;
    await api._client.delete(`/security-home/sensors/${id}`);
    reload();
  };
  return (
    <div style={overlay} data-testid="sh-sensors-modal">
      <div style={{ ...modal, maxWidth: 700 }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>Sensores · {site.name}</h3>
          <button onClick={onClose} style={closeBtn}>✕</button>
        </div>
        <div style={{ display: "grid",
                       gridTemplateColumns: "2fr 1fr 1fr auto",
                       gap: 8, alignItems: "end", marginTop: 12 }}>
          <input value={form.label} placeholder="Nome (ex: Porta sala)"
                  onChange={(e) => setForm({ ...form, label: e.target.value })}
                  style={inp} />
          <select value={form.kind}
                   onChange={(e) => setForm({ ...form, kind: e.target.value })}
                   style={inp}>
            <option value="magnetic">Magnético</option>
            <option value="pir">PIR (movimento)</option>
            <option value="active_ir">IVA (barreira)</option>
            <option value="glass_break">Quebra de vidro</option>
            <option value="panic">Botão de pânico</option>
            <option value="smoke">Fumaça</option>
            <option value="co">CO (gás)</option>
            <option value="flood">Inundação</option>
            <option value="camera">Câmera</option>
          </select>
          <input type="number" value={form.contact_zone}
                  min="1" max="999"
                  placeholder="Zona Contact ID"
                  onChange={(e) => setForm({ ...form,
                    contact_zone: Number(e.target.value) })}
                  style={inp} />
          <button onClick={create} style={primaryBtn}
                   data-testid="sh-sensor-create">+ Add</button>
        </div>
        <div style={{ marginTop: 16, maxHeight: 380, overflowY: "auto" }}>
          {!sensors.length ? (
            <div style={empty}>Nenhum sensor.</div>
          ) : sensors.map((s) => (
            <div key={s.id} style={alarmRow}>
              <div style={{ flex: 1 }}>
                <b>{s.label}</b>
                <span style={{ marginLeft: 8, fontSize: 11,
                                 color: "#64748b" }}>
                  {s.kind} · Zona {s.contact_zone}
                </span>
              </div>
              <span style={{ ...severityChip,
                               background: s.state === "triggered" ? "#dc2626"
                                 : s.state === "trouble" ? "#f59e0b"
                                   : "#10b981" }}>
                {s.state || "ok"}
              </span>
              <button onClick={() => del(s.id)}
                       style={miniBtn("#dc2626")}>Excluir</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── estilos ──────────────────────────────────────────
const card = { background: "white", border: "1px solid #e2e8f0",
                 borderRadius: 12, padding: 12 };
const tabBar = { display: "flex", gap: 4,
                   borderBottom: "1px solid #e2e8f0" };
const tabIdle = { padding: "8px 14px", background: "transparent",
                    border: 0, fontSize: 13, fontWeight: 600,
                    color: "#64748b", cursor: "pointer",
                    borderBottom: "2px solid transparent" };
const tabActive = { ...tabIdle, color: "#0f172a",
                     borderBottom: "2px solid #0f172a" };
const th = { textAlign: "left", padding: "8px 10px",
              borderBottom: "1px solid #e2e8f0", fontSize: 11,
              color: "#475569", textTransform: "uppercase" };
const td = { padding: "8px 10px", borderBottom: "1px solid #f1f5f9" };
const empty = { padding: 32, textAlign: "center", color: "#94a3b8",
                 fontSize: 13 };
const primaryBtn = { padding: "7px 14px", background: "#0f172a",
                      color: "white", border: 0, borderRadius: 6,
                      fontWeight: 700, fontSize: 12, cursor: "pointer" };
const secBtn = { ...primaryBtn, background: "white", color: "#475569",
                  border: "1px solid #cbd5e1", fontWeight: 600 };
const miniBtn = (bg) => ({ padding: "4px 8px", background: bg,
                            color: "white", border: 0, borderRadius: 4,
                            fontSize: 11, cursor: "pointer",
                            marginRight: 4 });
const overlay = { position: "fixed", inset: 0,
                    background: "rgba(0,0,0,.5)", display: "flex",
                    alignItems: "center", justifyContent: "center",
                    zIndex: 1000, padding: 16 };
const modal = { background: "white", borderRadius: 12, padding: 18,
                 maxWidth: 520, width: "100%", maxHeight: "90vh",
                 overflow: "auto" };
const closeBtn = { background: "transparent", border: 0, fontSize: 18,
                    cursor: "pointer", color: "#94a3b8" };
const inp = { width: "100%", padding: "6px 10px", borderRadius: 6,
                border: "1px solid #cbd5e1", fontSize: 13, marginTop: 4,
                boxSizing: "border-box" };
const errBox = { padding: 10, background: "#fee2e2", color: "#991b1b",
                  borderRadius: 6, fontSize: 12, marginTop: 8 };
const alarmRow = { display: "flex", gap: 10, alignItems: "center",
                     padding: "10px 12px", borderLeft: "4px solid #ef4444",
                     background: "#fff7ed", borderRadius: 6,
                     marginBottom: 8 };
const severityChip = { padding: "2px 8px", color: "white",
                         borderRadius: 4, fontSize: 10, fontWeight: 700,
                         letterSpacing: 0.5 };

// Inject keyframes
if (typeof document !== "undefined"
    && !document.getElementById("sh-keyframes")) {
  const style = document.createElement("style");
  style.id = "sh-keyframes";
  style.textContent = `@keyframes shAlarmPulse { 0%,100% { box-shadow: 0 0 0 0 rgba(239,68,68,.5); } 50% { box-shadow: 0 0 0 8px rgba(239,68,68,0); } }`;
  document.head.appendChild(style);
}
