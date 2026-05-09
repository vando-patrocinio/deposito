import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import { Button, Card } from "@/ui";

const inp = { width: "100%", padding: "9px 11px", border: "1px solid #cbd5e1", borderRadius: 10, fontSize: 13, marginBottom: 8 };
const lbl = { fontSize: 11, fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4, display: "block" };

export default function SmartoltIntegrationCard() {
  const [cfg, setCfg] = useState(null);
  const [form, setForm] = useState({});
  const [msg, setMsg] = useState(null);
  const [testing, setTesting] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async () => {
    try {
      const c = await api.smartoltSettings();
      setCfg(c);
      setForm({
        enabled: c.enabled || false,
        subdomain: c.subdomain || "",
        api_key: "", // sempre vazio (mascarado vem em c.api_key)
        sync_interval_minutes: c.sync_interval_minutes || 240,
        signal_cache_seconds: c.signal_cache_seconds || 60,
        timeout_seconds: c.timeout_seconds || 20,
      });
    } catch (e) {
      setMsg({ type: "err", text: e?.response?.data?.detail || e.message });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setMsg(null);
    try {
      const payload = { ...form };
      if (!payload.api_key) delete payload.api_key;
      await api.smartoltSettingsUpdate(payload);
      setMsg({ type: "ok", text: "Configuração salva." });
      load();
    } catch (e) {
      setMsg({ type: "err", text: e?.response?.data?.detail || e.message });
    }
  };

  const test = async () => {
    setTesting(true); setMsg(null);
    try {
      const r = await api.smartoltTest();
      if (r.ok) {
        setMsg({ type: "ok", text: `Conexão OK · ${r.olts_count} OLT(s) detectada(s): ${(r.olts || []).map((o) => o.name).join(", ")}` });
      } else {
        setMsg({ type: "err", text: `Falha: ${r.error || `HTTP ${r.http_status}`}` });
      }
    } catch (e) {
      setMsg({ type: "err", text: e?.response?.data?.detail || e.message });
    } finally { setTesting(false); }
  };

  const sync = async () => {
    setSyncing(true); setMsg(null);
    try {
      const r = await api.smartoltSync();
      setMsg({ type: "ok", text: `Sync OK · ${r.total} ONUs (${r.inserted} novas, ${r.updated} atualizadas) em ${r.elapsed_seconds}s` });
      load();
    } catch (e) {
      setMsg({ type: "err", text: e?.response?.data?.detail || e.message });
    } finally { setSyncing(false); }
  };

  if (!cfg) return <Card title="📶 SmartOLT (Sinal das ONUs)">Carregando…</Card>;

  return (
    <Card title="📶 SmartOLT — Sinal das ONUs (live)" data-testid="smartolt-card">
      <p style={{ fontSize: 12, color: "#64748b", margin: "0 0 12px" }}>
        Integra com SmartOLT API para mostrar o sinal Rx (dBm) e status (Online/Offline/LOS) de cada cliente direto na bolha da Lousa. Match feito pelo PPPoE do Atlaz ↔ nome da ONU no SmartOLT.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 8, alignItems: "center", marginBottom: 12 }}>
        <input type="checkbox" id="smartolt-enabled" data-testid="smartolt-enabled"
          checked={form.enabled || false} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
        <label htmlFor="smartolt-enabled" style={{ fontWeight: 700 }}>Integração ativa</label>
      </div>

      <label style={lbl}>Subdomain (ex.: ligofibra)</label>
      <input style={inp} value={form.subdomain || ""} onChange={(e) => setForm({ ...form, subdomain: e.target.value })} placeholder="ligofibra" data-testid="smartolt-subdomain" />

      <label style={lbl}>API Token (X-Token) {cfg.api_key && <span style={{ color: "#16a34a", textTransform: "none" }}>· atual: {cfg.api_key}</span>}</label>
      <input type="password" style={inp} value={form.api_key || ""} onChange={(e) => setForm({ ...form, api_key: e.target.value })} placeholder={cfg.api_key ? "••• deixe vazio p/ manter" : "cole o X-Token"} data-testid="smartolt-api-key" />

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginBottom: 8 }}>
        <div>
          <label style={lbl}>Sync (min)</label>
          <input type="number" min="15" max="1440" style={inp} value={form.sync_interval_minutes || 240} onChange={(e) => setForm({ ...form, sync_interval_minutes: parseInt(e.target.value, 10) })} data-testid="smartolt-sync-min" />
        </div>
        <div>
          <label style={lbl}>Cache sinal (s)</label>
          <input type="number" min="10" max="3600" style={inp} value={form.signal_cache_seconds || 60} onChange={(e) => setForm({ ...form, signal_cache_seconds: parseInt(e.target.value, 10) })} data-testid="smartolt-cache-s" />
        </div>
        <div>
          <label style={lbl}>Timeout (s)</label>
          <input type="number" min="5" max="120" style={inp} value={form.timeout_seconds || 20} onChange={(e) => setForm({ ...form, timeout_seconds: parseInt(e.target.value, 10) })} />
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
        <Button onClick={save} data-testid="smartolt-save-btn">💾 Salvar</Button>
        <Button variant="soft" onClick={test} disabled={testing} data-testid="smartolt-test-btn">{testing ? "Testando…" : "🔌 Testar conexão"}</Button>
        <Button variant="soft" onClick={sync} disabled={syncing || !cfg.enabled} data-testid="smartolt-sync-btn">{syncing ? "Sincronizando…" : "🔄 Sincronizar ONUs agora"}</Button>
      </div>

      {cfg.last_sync_at && (
        <div style={{ marginTop: 12, padding: 10, background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 10, fontSize: 12 }}>
          <strong>Último sync:</strong> {new Date(cfg.last_sync_at).toLocaleString("pt-BR")} · <strong>{cfg.last_sync_total} ONUs</strong> em cache
        </div>
      )}

      {msg && (
        <div data-testid="smartolt-msg" style={{
          marginTop: 10, padding: 10, borderRadius: 10, fontSize: 13, fontWeight: 600,
          background: msg.type === "ok" ? "#dcfce7" : "#fee2e2",
          color: msg.type === "ok" ? "#166534" : "#7f1d1d",
        }}>
          {msg.text}
        </div>
      )}
    </Card>
  );
}
