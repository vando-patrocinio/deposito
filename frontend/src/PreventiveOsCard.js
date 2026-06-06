import { useEffect, useState } from "react";
import { Card, Button, Field, inputStyle } from "@/ui";
import { api } from "@/api";

/**
 * iter215ab — OS Preventivas automáticas
 *
 * Rede IA preenche grade ociosa: quando um técnico tem MENOS OS que a meta
 * do dia (ex: 12), o sistema cria até N OS preventivas (ex: 3) pegando os
 * clientes com pior sinal SmartOLT (1310nm) que ainda não tenham OS aberta.
 *
 * Roda 1x/dia (cron 08:30 BRT) e também sob demanda via botão "Gerar agora".
 */
export default function PreventiveOsCard() {
  const [cfg, setCfg] = useState(null);
  const [form, setForm] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(null);
  const [lastRun, setLastRun] = useState(null);
  const [hist, setHist] = useState([]);
  const [msg, setMsg] = useState("");

  async function load() {
    setLoading(true);
    try {
      const r = await api._client.get("/preventive-os/settings");
      setCfg(r.data);
      setForm(r.data);
      const h = await api._client.get("/preventive-os/history?limit=10");
      setHist(h.data?.items || []);
    } catch (e) {
      setMsg(e?.response?.data?.detail || e.message);
    }
    setLoading(false);
  }
  useEffect(() => { load(); }, []);

  async function save() {
    setBusy(true); setMsg("");
    try {
      const r = await api._client.put("/preventive-os/settings", form);
      setCfg(r.data); setForm(r.data);
      setMsg("✓ Configurações salvas");
      setTimeout(() => setMsg(""), 2500);
    } catch (e) {
      setMsg("✗ " + (e?.response?.data?.detail || e.message));
    }
    setBusy(false);
  }

  async function doPreview() {
    setBusy(true); setMsg(""); setPreview(null);
    try {
      const r = await api._client.post("/preventive-os/preview");
      setPreview(r.data);
    } catch (e) {
      setMsg("✗ " + (e?.response?.data?.detail || e.message));
    }
    setBusy(false);
  }

  async function doRun() {
    if (!window.confirm(
      "Vai gerar as OS preventivas AGORA e colocar na grade dos técnicos. "
      + "Tem certeza?")) return;
    setBusy(true); setMsg(""); setLastRun(null);
    try {
      const r = await api._client.post("/preventive-os/run-now");
      setLastRun(r.data);
      await load();
      setMsg(`✓ ${(r.data?.created || []).length} OS criadas`);
      setTimeout(() => setMsg(""), 3500);
    } catch (e) {
      setMsg("✗ " + (e?.response?.data?.detail || e.message));
    }
    setBusy(false);
  }

  if (!cfg || !form) {
    return (
      <Card title="️ OS Preventivas (Rede IA)">
        <p style={{ color: "#64748b" }}>
          {loading ? "Carregando..." : "Erro ao carregar configurações."}
        </p>
      </Card>
    );
  }

  const set = (k, v) => setForm({ ...form, [k]: v });
  const dirty = JSON.stringify(form) !== JSON.stringify(cfg);

  return (
    <Card title="️ OS Preventivas (Rede IA)"
           style={{ gridColumn: "1 / -1" }}>
      <p style={{ color: "#64748b", fontSize: 14, margin: "0 0 14px",
                   lineHeight: 1.55 }}>
        <b>Regra:</b> a meta de cada técnico é <b>{form.target_os_per_day}{" "}
        OS/dia</b>. Quando ele tem MENOS OS na grade do dia, a Rede IA pega{" "}
        os <b>{form.max_preventive_per_run} clientes com sinal mais{" "}
        crítico</b> (pior que <b>{form.signal_threshold_dbm}dBm</b>) que{" "}
        ainda não têm OS aberta e cria bolhas <code style={pillStyle}>
          tipo=preventiva
        </code> na grade dele.
        <br />
        <span style={{ color: "#94a3b8" }}>
          Objetivo: dia tranquilo = consertar quem está com sinal ruim ANTES
          de virar reclamação/churn.
        </span>
      </p>

      {/* Toggle ON/OFF */}
      <label data-testid="preventive-os-enabled-toggle"
              style={{
                display: "flex", gap: 10, alignItems: "center",
                padding: 14, borderRadius: 12,
                background: form.enabled ? "#f0fdf4" : "#fef2f2",
                border: `2px solid ${form.enabled ? "#86efac" : "#fecaca"}`,
                marginBottom: 14, cursor: "pointer",
              }}>
        <input type="checkbox" checked={form.enabled}
                onChange={(e) => set("enabled", e.target.checked)}
                style={{ width: 20, height: 20 }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 800, color: "#0f172a", fontSize: 15 }}>
            {form.enabled ? "Habilitado" : "Desligado"}
          </div>
          <div style={{ fontSize: 12, color: "#64748b" }}>
            {form.enabled
              ? `Rede IA roda diariamente às ${form.scheduled_hour} BRT.`
              : "Marque pra habilitar o cron diário."}
          </div>
        </div>
      </label>

      {/* Sliders principais */}
      <div style={{ display: "grid",
                     gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))",
                     gap: 12, marginBottom: 14 }}>
        <Field label={`Meta de OS/dia por técnico (${form.target_os_per_day})`}>
          <input type="range" min={1} max={30} value={form.target_os_per_day}
                  data-testid="prev-os-target-input"
                  onChange={(e) => set("target_os_per_day",
                                          Number(e.target.value))}
                  style={{ width: "100%" }} />
        </Field>
        <Field label={`Quantas preventivas adicionar (${form.max_preventive_per_run})`}>
          <input type="range" min={1} max={10}
                  value={form.max_preventive_per_run}
                  data-testid="prev-os-max-input"
                  onChange={(e) => set("max_preventive_per_run",
                                          Number(e.target.value))}
                  style={{ width: "100%" }} />
        </Field>
        <Field label={`Sinal crítico (pior que ${form.signal_threshold_dbm}dBm)`}>
          <input type="range" min={-32} max={-15} step={0.5}
                  value={form.signal_threshold_dbm}
                  data-testid="prev-os-signal-input"
                  onChange={(e) => set("signal_threshold_dbm",
                                          Number(e.target.value))}
                  style={{ width: "100%" }} />
        </Field>
        <Field label={`Piso (ignora sinais piores que ${form.min_signal_floor_dbm}dBm — provável erro)`}>
          <input type="range" min={-40} max={-25} step={0.5}
                  value={form.min_signal_floor_dbm}
                  onChange={(e) => set("min_signal_floor_dbm",
                                          Number(e.target.value))}
                  style={{ width: "100%" }} />
        </Field>
      </div>

      {/* Strategy & extras */}
      <div style={{ display: "grid",
                     gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))",
                     gap: 12, marginBottom: 14 }}>
        <Field label="️ Estratégia de match cliente↔técnico">
          <select style={inputStyle}
                   value={form.match_strategy}
                   data-testid="prev-os-strategy"
                   onChange={(e) => set("match_strategy", e.target.value)}>
            <option value="city">Mesma cidade (recomendado)</option>
            <option value="praca">Mesma praça</option>
            <option value="any">Qualquer técnico (round-robin)</option>
          </select>
        </Field>
        <Field label="⏰ Hora do cron diário (BRT)">
          <input type="time" style={inputStyle}
                  value={form.scheduled_hour}
                  data-testid="prev-os-hour"
                  onChange={(e) => set("scheduled_hour", e.target.value)} />
        </Field>
        <Field label="Rodar em finais de semana?">
          <label style={{ display: "flex", gap: 8, alignItems: "center",
                            padding: 10, fontSize: 13 }}>
            <input type="checkbox" checked={form.include_weekends}
                    onChange={(e) => set("include_weekends",
                                            e.target.checked)} />
            {form.include_weekends ? "Sim" : "Não (só dias úteis)"}
          </label>
        </Field>
      </div>

      {/* Ações */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                     marginBottom: 14 }}>
        <Button data-testid="prev-os-save-btn"
                 onClick={save} disabled={!dirty || busy}>
          {busy ? "..." : "Salvar"}
        </Button>
        <Button data-testid="prev-os-preview-btn"
                 onClick={doPreview} disabled={busy}
                 style={{ background: "#0ea5e9" }}>
          {busy ? "..." : "️ Visualizar (dry-run)"}
        </Button>
        <Button data-testid="prev-os-run-btn"
                 onClick={doRun} disabled={busy || !cfg.enabled}
                 style={{
                   background: cfg.enabled ? "#16a34a" : "#94a3b8",
                   cursor: cfg.enabled ? "pointer" : "not-allowed",
                 }}
                 title={!cfg.enabled
                   ? "Habilite e salve antes de rodar"
                   : "Cria as OS preventivas agora"}>
          {busy ? "..." : "Gerar agora"}
        </Button>
        {msg && (
          <span style={{
            alignSelf: "center", fontSize: 13, fontWeight: 700,
            color: msg.startsWith("✓") ? "#16a34a" : "#dc2626",
          }}>{msg}</span>
        )}
      </div>

      {/* Preview (dry-run) */}
      {preview && (
        <div style={panelStyle}>
          <h4 style={{ margin: "0 0 8px", color: "#0c4a6e", fontSize: 14 }}>
            ️ Pré-visualização ({preview.date})
          </h4>
          {preview.skipped ? (
            <p style={{ color: "#475569", fontSize: 13, margin: 0 }}>
              Não roda hoje: <code>{preview.reason}</code>
              {preview.collaborators && (
                <span style={{ marginLeft: 6 }}>
                  ({preview.collaborators.length} técnicos verificados —
                  cada um já tem ≥ {form.target_os_per_day} OS hoje)
                </span>
              )}
            </p>
          ) : (
            <>
              <p style={{ fontSize: 13, color: "#475569", margin: "0 0 6px" }}>
                <b>{preview.candidates_found || 0}</b> clientes com sinal crítico{" "}
                encontrados · <b>{preview.total_slots_available || 0}</b>{" "}
                slots disponíveis · serão criadas <b>{(preview.would_create
                || []).length}</b> OS preventivas:
              </p>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13,
                             color: "#1e293b" }}>
                {(preview.would_create || []).slice(0, 20).map((w, i) => (
                  <li key={i}>
                    <b>{w.collaborator_name}</b> ← {w.subscriber_name}{" "}
                    <span style={{
                      background: "#fef3c7", color: "#92400e",
                      padding: "1px 6px", borderRadius: 4, fontSize: 11,
                      fontWeight: 800,
                    }}>{w.signal_dbm}dBm</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {/* Último run */}
      {lastRun && (
        <div style={{ ...panelStyle, borderColor: "#bbf7d0",
                       background: "#f0fdf4" }}>
          <h4 style={{ margin: "0 0 8px", color: "#14532d", fontSize: 14 }}>
            ✅ Última execução manual ({lastRun.date})
          </h4>
          <p style={{ fontSize: 13, color: "#1e293b", margin: 0 }}>
            <b>{(lastRun.created || []).length}</b> OS preventivas criadas e{" "}
            colocadas na grade.
          </p>
        </div>
      )}

      {/* Histórico */}
      {hist.length > 0 && (
        <details style={{ marginTop: 14 }}>
          <summary style={{ cursor: "pointer", color: "#475569",
                              fontSize: 13, fontWeight: 700 }}>
            Histórico ({hist.length})
          </summary>
          <table style={{ width: "100%", marginTop: 8, fontSize: 12 }}>
            <thead>
              <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                <th style={thStyle}>Data</th>
                <th style={thStyle}>Rodado em</th>
                <th style={thStyle}>Por</th>
                <th style={thStyle}>Criadas</th>
              </tr>
            </thead>
            <tbody>
              {hist.map((h) => (
                <tr key={h.id} style={{ borderTop: "1px solid #e2e8f0" }}>
                  <td style={tdStyle}>{h.date}</td>
                  <td style={tdStyle}>
                    {(h.ran_at || "").slice(0, 19).replace("T", " ")}
                  </td>
                  <td style={tdStyle}>{h.actor_email}</td>
                  <td style={tdStyle}>
                    <b>{h.summary?.created_count || 0}</b>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </Card>
  );
}

const pillStyle = {
  background: "#e0f2fe", color: "#0c4a6e",
  padding: "1px 6px", borderRadius: 4, fontSize: 12, fontWeight: 700,
};
const panelStyle = {
  marginTop: 12, padding: 12, borderRadius: 10,
  background: "#f0f9ff", border: "1px solid #bae6fd",
};
const thStyle = { padding: 6, fontWeight: 800, color: "#475569" };
const tdStyle = { padding: 6, color: "#1e293b" };
