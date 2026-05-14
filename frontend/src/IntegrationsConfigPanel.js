import React, { useEffect, useState } from "react";
import { Card } from "@/ui";
import { api } from "@/api";
import WhatsAppInstancePanel from "@/WhatsAppInstancePanel";
import ChatTopologyMap from "@/ChatTopologyMap";
import InlineAgentEditor from "@/InlineAgentEditor";
import {
  CheckCircle2, AlertCircle, RefreshCw, Plug, Wifi, WifiOff,
} from "lucide-react";

/**
 * Painel de Configuração da aba Atendimento IA.
 * Agrega:
 *  - WhatsApp Baileys (Instância — QR, status, número conectado)
 *  - Health-check Twilio + Meta Cloud
 *  - Botão "Verificar e reconectar" — auto-reconecta canais mortos
 */
export default function IntegrationsConfigPanel() {
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [lastAction, setLastAction] = useState(null);

  const loadHealth = async () => {
    try {
      const r = await api.integrationsHealth();
      setHealth(r);
    } catch (e) {
      setHealth({ channels: [], error: e?.response?.data?.detail || e.message });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHealth();
    const id = setInterval(loadHealth, 8000);
    return () => clearInterval(id);
  }, []);

  const autoReconnect = async () => {
    setBusy(true); setLastAction(null);
    try {
      const r = await api.integrationsReconnect();
      setLastAction(r);
      await loadHealth();
    } catch (e) {
      setLastAction({ error: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  return (
    <div data-testid="integrations-config" style={{ display: "grid", gap: 14 }}>
      <Card style={{ padding: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <div style={{
            width: 44, height: 44, borderRadius: 11,
            background: "linear-gradient(135deg,#0f172a,#1e293b)",
            color: "white", display: "grid", placeItems: "center",
          }}>
            <Plug size={20} strokeWidth={1.75} />
          </div>
          <div style={{ flex: 1, minWidth: 240 }}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>
              Saúde dos canais
            </h2>
            <p style={{ margin: "2px 0 0", color: "var(--text-secondary)", fontSize: 12 }}>
              Status em tempo real dos canais de mensageria. Canais mortos são religados automaticamente ao clicar abaixo.
            </p>
          </div>
          <button
            data-testid="integrations-reconnect-btn"
            onClick={autoReconnect}
            disabled={busy}
            style={{
              padding: "9px 16px", borderRadius: 10, border: 0,
              background: busy ? "#94a3b8" : "#0f172a",
              color: "white", fontSize: 13, fontWeight: 700,
              cursor: busy ? "not-allowed" : "pointer",
              display: "inline-flex", alignItems: "center", gap: 8,
            }}
          >
            <RefreshCw size={13} className={busy ? "spin" : ""} />
            {busy ? "Verificando…" : "Verificar e reconectar"}
          </button>
        </div>

        {/* Channel cards */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10, marginTop: 14 }}>
          {loading ? <div style={{ color: "var(--text-muted)", fontSize: 12 }}>Carregando...</div> :
            (health?.channels || []).map((c) => <ChannelTile key={c.channel} c={c} />)}
        </div>

        {lastAction && lastAction.actions && (
          <div style={{ marginTop: 12, padding: 12, background: "rgba(16,185,129,.06)", border: "1px solid rgba(16,185,129,.25)", borderRadius: 8, fontSize: 11.5, color: "#15803d" }}>
            ✓ Ações executadas: {lastAction.actions.map((a) => `${a.channel} (${a.result})`).join(" · ")}
          </div>
        )}
        {lastAction?.error && (
          <div style={{ marginTop: 12, padding: 12, background: "rgba(239,68,68,.06)", border: "1px solid rgba(239,68,68,.25)", borderRadius: 8, fontSize: 11.5, color: "#b91c1c" }}>
            Erro: {lastAction.error}
          </div>
        )}
      </Card>

      {/* Topologia em tempo real */}
      <ChatTopologyMap />

      {/* Editor inline do Agente IA — Personalidade & Modelo */}
      <InlineAgentEditor />

      {/* Painel completo de Instância Baileys (QR, número, auto-reply, etc.) */}
      <WhatsAppInstancePanel />
    </div>
  );
}

function ChannelTile({ c }) {
  const isOk = c.connected;
  const needsAction = c.needs_action;
  const color = isOk ? "#10b981" : needsAction ? "#f59e0b" : "#94a3b8";
  const StatusIcon = isOk ? CheckCircle2 : needsAction ? AlertCircle : WifiOff;
  return (
    <div style={{
      padding: 14, border: `1px solid ${needsAction ? "rgba(245,158,11,.35)" : "var(--border-default)"}`,
      borderRadius: 10, background: "var(--bg-surface)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{
          width: 32, height: 32, borderRadius: 8,
          background: `${color}15`, color, display: "grid", placeItems: "center",
        }}>
          <Wifi size={16} strokeWidth={1.75} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-primary)", overflow: "hidden", textOverflow: "ellipsis" }}>
            {c.label}
          </div>
          <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{c.status}</div>
        </div>
        <StatusIcon size={16} style={{ color }} />
      </div>
      {c.error && (
        <div style={{ marginTop: 8, fontSize: 10, color: "#b91c1c" }}>{c.error}</div>
      )}
    </div>
  );
}
