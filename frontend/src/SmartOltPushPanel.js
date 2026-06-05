/*
SmartOltPushPanel.js — iter211bf

Painel admin "Fila SmartOLT" — mostra CTOs aguardando sincronia com
o SmartOLT, CTOs já sincronizadas e botões para forçar retry/sweep.

Backend:
  • GET  /api/smartolt-push-ctos/queue
  • POST /api/smartolt-push-ctos/run       (sweep imediato)
  • POST /api/smartolt-push-ctos/retry/:id (força uma CTO)
*/
import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";

const TS = (iso) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", {
      day: "2-digit", month: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch { return iso; }
};

export default function SmartOltPushPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [running, setRunning] = useState(false);
  const [lastSweep, setLastSweep] = useState(null);

  const reload = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const r = await api._client.get("/smartolt-push-ctos/queue").then((x) => x.data);
      setData(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setLoading(false);
  }, []);

  useEffect(() => { reload(); }, [reload]);

  // Auto-refresh enquanto houver pendentes
  useEffect(() => {
    if (!data?.pending_count) return undefined;
    const id = setInterval(reload, 15000);
    return () => clearInterval(id);
  }, [data?.pending_count, reload]);

  const runSweep = async () => {
    setRunning(true);
    try {
      const r = await api._client.post("/smartolt-push-ctos/run").then((x) => x.data);
      setLastSweep(r);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setRunning(false);
    reload();
  };

  const retryOne = async (ctoId) => {
    try {
      await api._client.post(`/smartolt-push-ctos/retry/${ctoId}`);
      reload();
    } catch (e) {
      alert("Falha: " + (e?.response?.data?.detail || e.message));
    }
  };

  return (
    <div style={{ padding: "0 4px", display: "grid", gap: 16 }}
          data-testid="smartolt-push-panel">
      <div>
        <h1 style={{ fontSize: 24, fontWeight: 700, margin: 0,
                       color: "var(--text-primary)", letterSpacing: "-0.02em" }}>
          📡 Fila SmartOLT
        </h1>
        <p style={{ color: "#64748b", fontSize: 13, margin: "4px 0 0" }}>
          CTOs criadas localmente que serão registradas no SmartOLT (apenas as
          que estão em VLANs vinculadas a uma OLT cadastrada em Bairros).
        </p>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <button data-testid="smartolt-run-sweep"
                onClick={runSweep} disabled={running}
                style={btnPrimary}>
          {running ? "⏳ Sincronizando…" : "⚡ Forçar sincronia agora"}
        </button>
        {data?.pending_count > 0 && (
          <button data-testid="smartolt-retry-all"
                  onClick={async () => {
                    if (!window.confirm(
                      `Resetar backoff e tentar sincronizar TODAS as ${data.pending_count} CTOs pendentes agora?`
                    )) return;
                    setRunning(true);
                    try {
                      const r = await api._client.post("/smartolt-push-ctos/retry-all").then((x) => x.data);
                      setLastSweep(r.sweep);
                    } catch (e) {
                      setErr(e?.response?.data?.detail || e.message);
                    }
                    setRunning(false);
                    reload();
                  }}
                  disabled={running}
                  style={{
                    ...btnPrimary,
                    background: "linear-gradient(135deg,#f59e0b,#d97706)",
                  }}>
            🔁 Sincronizar TODAS ({data.pending_count})
          </button>
        )}
        <button data-testid="smartolt-reload"
                onClick={reload} disabled={loading} style={btnSecondary}>
          {loading ? "⏳" : "🔄"} Atualizar
        </button>
        {data && (
          <span style={{ fontSize: 12, color: "#64748b" }}>
            {data.pending_count > 0
              ? `🟡 ${data.pending_count} pendente(s) · 🟢 ${data.synced_recent?.length || 0} sincronizadas recentes`
              : "✅ Tudo em dia"}
          </span>
        )}
      </div>

      {err && (
        <div style={{ padding: 12, background: "#fee2e2", color: "#991b1b",
                       borderRadius: 8, fontSize: 13 }}>
          {err}
        </div>
      )}
      {lastSweep && (
        <div style={{ padding: 10, background: "#dbeafe", color: "#1e3a8a",
                       borderRadius: 8, fontSize: 12 }}>
          Último sweep: {lastSweep.processed} processada(s) — ✅ {lastSweep.ok}
          {" · "}❌ {lastSweep.fail} · {TS(lastSweep.ts)}
        </div>
      )}

      {/* Pendentes */}
      <div style={cardStyle} data-testid="smartolt-pending">
        <h3 style={{ margin: "0 0 10px", fontSize: 16, fontWeight: 700,
                      color: "#7c2d12" }}>
          🟡 Aguardando sincronia
        </h3>
        {!data?.pending?.length ? (
          <div style={emptyStyle}>Sem CTOs pendentes. 🎉</div>
        ) : (
          <div style={{ display: "grid", gap: 6 }}>
            {data.pending.map((c) => (
              <div key={c.id} style={rowStyle}>
                <span style={{ ...pillStyle, background: "#fef3c7",
                                  borderColor: "#fde68a", color: "#78350f" }}>
                  {c.name || "(sem nome)"}
                </span>
                <span style={{ fontSize: 11, color: "#475569" }}>
                  VLAN {c.vlan || "?"}
                </span>
                {c.smartolt_olt_name && (
                  <span style={{ fontSize: 10, color: "#0f766e",
                                    fontFamily: "monospace" }}>
                    📡 {c.smartolt_olt_name}
                  </span>
                )}
                {c.smartolt_sync_attempts > 0 && (
                  <span style={{ fontSize: 10, color: "#b91c1c" }}>
                    {c.smartolt_sync_attempts} tentativa(s)
                  </span>
                )}
                <span style={{ flex: 1, fontSize: 11, color: "#dc2626",
                                  overflow: "hidden", textOverflow: "ellipsis",
                                  whiteSpace: "nowrap", minWidth: 0 }}
                        title={c.smartolt_last_error}>
                  {c.smartolt_last_error || "—"}
                </span>
                <button onClick={() => retryOne(c.id)}
                        data-testid={`smartolt-retry-${c.id}`}
                        style={miniBtn}>
                  ↻ Tentar agora
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Sincronizadas recentes */}
      <div style={cardStyle} data-testid="smartolt-synced">
        <h3 style={{ margin: "0 0 10px", fontSize: 16, fontWeight: 700,
                      color: "#065f46" }}>
          🟢 Sincronizadas recentemente
        </h3>
        {!data?.synced_recent?.length ? (
          <div style={emptyStyle}>Nenhuma CTO sincronizada ainda.</div>
        ) : (
          <div style={{ display: "grid", gap: 6 }}>
            {data.synced_recent.map((c) => (
              <div key={c.id} style={rowStyle}>
                <span style={{ ...pillStyle, background: "#ecfdf5",
                                  borderColor: "#a7f3d0", color: "#065f46" }}>
                  {c.name}
                </span>
                <span style={{ fontSize: 11, color: "#475569" }}>
                  VLAN {c.vlan || "?"}
                </span>
                <span style={{ fontSize: 10, color: "#0f766e",
                                  fontFamily: "monospace" }}>
                  📡 {c.smartolt_olt_name || "—"}
                </span>
                <span style={{ flex: 1, fontSize: 11, color: "#64748b" }}>
                  Sincronizada em {TS(c.smartolt_synced_at)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

const btnPrimary = {
  padding: "7px 14px", background: "#0f172a", color: "white",
  border: "none", borderRadius: 6, fontWeight: 700, fontSize: 13,
  cursor: "pointer",
};
const btnSecondary = {
  padding: "7px 14px", background: "white", color: "#475569",
  border: "1px solid #cbd5e1", borderRadius: 6, fontWeight: 600,
  fontSize: 13, cursor: "pointer",
};
const cardStyle = {
  background: "white", border: "1px solid #e2e8f0",
  borderRadius: 12, padding: 16,
  boxShadow: "0 1px 3px rgba(15,23,42,.04)",
};
const rowStyle = {
  display: "flex", alignItems: "center", gap: 10,
  padding: "8px 10px", background: "#f8fafc",
  borderRadius: 8, border: "1px solid #e2e8f0",
  fontSize: 12,
};
const pillStyle = {
  padding: "3px 10px", borderRadius: 6, fontSize: 12, fontWeight: 700,
  border: "1px solid", fontFamily: "monospace",
};
const miniBtn = {
  padding: "4px 10px", background: "#1e3a8a", color: "white",
  border: 0, borderRadius: 6, fontSize: 11, fontWeight: 700,
  cursor: "pointer",
};
const emptyStyle = {
  padding: 16, textAlign: "center", color: "#94a3b8", fontSize: 13,
};
