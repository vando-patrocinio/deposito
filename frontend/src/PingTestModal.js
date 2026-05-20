/**
 * PingTestModal — Teste de ping/conectividade no app do colaborador.
 *
 * Permite ao técnico digitar IP/hostname da ONT (ou qualquer host) e testar
 * conectividade via TCP (porta 80 por padrão) ou ICMP se disponível.
 * Mostra: alive, RTT médio, packet loss, e histórico das últimas 10 medições.
 *
 * Backend: POST /api/network/ping
 */
import React, { useState, useEffect, useCallback } from "react";
import { api } from "@/api";

const DEFAULT_PORTS = [
  { label: "HTTP (80)", value: 80 },
  { label: "HTTPS (443)", value: 443 },
  { label: "Telnet ONU (23)", value: 23 },
  { label: "SSH (22)", value: 22 },
  { label: "SNMP (161)", value: 161 },
];

export default function PingTestModal({ open, onClose, defaultHost = "", ticketId = null }) {
  const [host, setHost] = useState(defaultHost);
  const [port, setPort] = useState(80);
  const [count, setCount] = useState(4);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);
  const [history, setHistory] = useState([]);

  const loadHistory = useCallback(async () => {
    try {
      const r = await api.networkPingHistory(10);
      setHistory(r.items || []);
    } catch { /* silencioso */ }
  }, []);

  useEffect(() => {
    if (open) {
      setResult(null);
      setErr(null);
      loadHistory();
    }
  }, [open, loadHistory]);

  useEffect(() => { setHost(defaultHost); }, [defaultHost]);

  const submit = async (e) => {
    e?.preventDefault?.();
    const trimmed = host.trim();
    if (!trimmed) { setErr("Digite IP ou hostname"); return; }
    setBusy(true); setErr(null); setResult(null);
    try {
      const r = await api.networkPing({ host: trimmed, count, port, ticketId });
      setResult(r);
      loadHistory();
    } catch (ex) {
      setErr(ex?.response?.data?.detail || ex.message);
    } finally { setBusy(false); }
  };

  if (!open) return null;

  return (
    <div data-testid="ping-test-modal" style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,.7)",
      display: "grid", placeItems: "center", zIndex: 9000, padding: 16,
    }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "white", borderRadius: 16, padding: 18,
        maxWidth: 440, width: "100%", maxHeight: "92vh", overflowY: "auto",
        boxShadow: "0 20px 60px rgba(0,0,0,.3)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10,
                       marginBottom: 14 }}>
          <div style={{
            width: 38, height: 38, borderRadius: 10,
            background: "linear-gradient(135deg, #0ea5e9, #06b6d4)",
            display: "grid", placeItems: "center", color: "white",
            fontWeight: 800, fontSize: 16,
          }}>
            🛰
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 800, fontSize: 16, color: "#0f172a" }}>
              Teste de conectividade
            </div>
            <div style={{ fontSize: 11, color: "#64748b" }}>
              Ping ONU / IP / hostname
            </div>
          </div>
          <button onClick={onClose}
                  data-testid="ping-modal-close"
                  style={{ background: "transparent", border: 0,
                            fontSize: 24, color: "#64748b", cursor: "pointer",
                            lineHeight: 1, padding: 0 }}>×</button>
        </div>

        <form onSubmit={submit}>
          <label style={{ display: "block", fontSize: 11, fontWeight: 700,
                            color: "#475569", marginBottom: 4 }}>
            IP ou hostname
          </label>
          <input
            type="text"
            value={host}
            onChange={(e) => setHost(e.target.value)}
            data-testid="ping-host-input"
            placeholder="192.168.1.1 ou cliente.olt.local"
            autoCapitalize="off" autoCorrect="off" spellCheck={false}
            style={{
              width: "100%", padding: "12px 14px", borderRadius: 8,
              border: "1.5px solid #cbd5e1", fontSize: 15,
              boxSizing: "border-box", marginBottom: 10,
            }}
          />

          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            <div style={{ flex: 1 }}>
              <label style={{ display: "block", fontSize: 11, fontWeight: 700,
                                color: "#475569", marginBottom: 4 }}>
                Porta TCP
              </label>
              <select value={port}
                       onChange={(e) => setPort(parseInt(e.target.value, 10))}
                       data-testid="ping-port-select"
                       style={{
                         width: "100%", padding: "10px 12px",
                         borderRadius: 8, border: "1.5px solid #cbd5e1",
                         fontSize: 13, background: "white",
                       }}>
                {DEFAULT_PORTS.map((p) => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </div>
            <div style={{ width: 100 }}>
              <label style={{ display: "block", fontSize: 11, fontWeight: 700,
                                color: "#475569", marginBottom: 4 }}>
                Pacotes
              </label>
              <input type="number" min={1} max={10}
                     value={count}
                     onChange={(e) => setCount(Math.max(1, Math.min(10, parseInt(e.target.value, 10) || 4)))}
                     data-testid="ping-count-input"
                     style={{
                       width: "100%", padding: "10px 12px",
                       borderRadius: 8, border: "1.5px solid #cbd5e1",
                       fontSize: 13, boxSizing: "border-box",
                     }}/>
            </div>
          </div>

          <button type="submit" disabled={busy}
                  data-testid="ping-submit"
                  style={{
                    width: "100%", padding: "12px 16px",
                    background: busy ? "#94a3b8" : "linear-gradient(135deg, #0ea5e9, #0284c7)",
                    color: "white", border: 0, borderRadius: 10,
                    fontSize: 14, fontWeight: 800,
                    cursor: busy ? "wait" : "pointer",
                    boxShadow: "0 2px 8px rgba(14,165,233,.3)",
                  }}>
            {busy ? "Testando..." : "🛰 Testar agora"}
          </button>
        </form>

        {err && (
          <div data-testid="ping-error" style={{
            marginTop: 12, padding: 10, background: "#fef2f2",
            color: "#991b1b", borderRadius: 8, fontSize: 12, fontWeight: 600,
          }}>⚠️ {err}</div>
        )}

        {result && (
          <>
            <PingResultCard result={result} />
            {ticketId && (
              <div data-testid="ping-saved-on-os" style={{
                marginTop: 8, padding: "8px 10px",
                background: "#ecfdf5", border: "1px solid #6ee7b7",
                borderRadius: 8, fontSize: 11, color: "#065f46",
                display: "flex", alignItems: "center", gap: 6,
              }}>
                📎 <span><strong>Resultado salvo na OS</strong>
                  <span style={{
                    marginLeft: 4, fontFamily: "ui-monospace,monospace",
                    background: "rgba(255,255,255,.7)",
                    padding: "1px 5px", borderRadius: 3,
                  }}>{ticketId}</span></span>
              </div>
            )}
          </>
        )}

        {history.length > 0 && (
          <details style={{ marginTop: 14 }}>
            <summary style={{ cursor: "pointer", fontSize: 12,
                                color: "#475569", fontWeight: 700 }}>
              Histórico (últimos {history.length})
            </summary>
            <div style={{ marginTop: 8, display: "grid", gap: 4 }}>
              {history.map((h, i) => (
                <button key={i} onClick={() => setHost(h.host)}
                        style={{
                          padding: "6px 10px",
                          background: "#f8fafc",
                          border: "1px solid #e2e8f0",
                          borderRadius: 6, textAlign: "left",
                          fontSize: 11, cursor: "pointer",
                          display: "flex", justifyContent: "space-between",
                          alignItems: "center", gap: 6,
                        }}>
                  <span style={{
                    fontFamily: "ui-monospace,monospace",
                    color: "#0f172a", fontWeight: 600,
                  }}>{h.host}</span>
                  <span style={{
                    fontSize: 10, color: h.alive ? "#16a34a" : "#dc2626",
                    fontWeight: 700,
                  }}>
                    {h.alive ? `✓ ${h.avg_ms?.toFixed(1) || "—"}ms` : "✗ falhou"}
                  </span>
                </button>
              ))}
            </div>
          </details>
        )}
      </div>
    </div>
  );
}

function PingResultCard({ result }) {
  const ok = result.alive;
  const bg = ok ? "#ecfdf5" : "#fef2f2";
  const border = ok ? "#86efac" : "#fca5a5";
  const accent = ok ? "#16a34a" : "#dc2626";

  return (
    <div data-testid="ping-result-card" style={{
      marginTop: 14, padding: 12, background: bg,
      border: `1.5px solid ${border}`, borderRadius: 10,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                     marginBottom: 10 }}>
        <div style={{
          width: 38, height: 38, borderRadius: 99, background: accent,
          color: "white", fontSize: 18, fontWeight: 800,
          display: "grid", placeItems: "center",
        }}>{ok ? "✓" : "✗"}</div>
        <div>
          <div style={{ fontWeight: 800, fontSize: 14, color: accent }}>
            {ok ? "Host respondendo" : "Host SEM resposta"}
          </div>
          <div style={{ fontSize: 11, color: "#475569",
                         fontFamily: "ui-monospace,monospace" }}>
            {result.host}{result.port && result.method === "tcp" ? `:${result.port}` : ""}
          </div>
        </div>
      </div>

      <div style={{
        display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 6,
        fontSize: 11,
      }}>
        <Metric label="RTT médio" value={result.avg_ms != null ? `${result.avg_ms.toFixed(1)}ms` : "—"} />
        <Metric label="Packet loss"
                value={result.loss_pct != null ? `${result.loss_pct}%` : "—"}
                warn={result.loss_pct > 0} />
        <Metric label="Min / Max"
                value={result.min_ms != null ? `${result.min_ms.toFixed(1)} / ${result.max_ms.toFixed(1)}ms` : "—"} />
        <Metric label="Pacotes"
                value={`${result.received || 0}/${result.sent || 0}`} />
      </div>

      <div style={{ marginTop: 8, fontSize: 10, color: "#64748b" }}>
        Método: <strong style={{ color: "#475569" }}>
          {result.method === "icmp" ? "ICMP ping" : `TCP connect (porta ${result.port})`}
        </strong>
      </div>

      {ok && result.avg_ms != null && (
        <div style={{
          marginTop: 8, padding: 6, fontSize: 11,
          background: "rgba(255,255,255,.6)", borderRadius: 6,
          color: "#475569", lineHeight: 1.5,
        }}>
          {result.avg_ms < 50 ? "🟢 Latência excelente"
            : result.avg_ms < 150 ? "🟡 Latência ok"
            : "🔴 Latência alta — verifique a rede"}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, warn }) {
  return (
    <div style={{
      padding: "6px 8px", background: "rgba(255,255,255,.7)",
      borderRadius: 6,
    }}>
      <div style={{ fontSize: 9, color: "#64748b",
                     textTransform: "uppercase", letterSpacing: ".06em" }}>
        {label}
      </div>
      <div style={{
        fontSize: 13, fontWeight: 700, marginTop: 2,
        color: warn ? "#dc2626" : "#0f172a",
        fontFamily: "ui-monospace,monospace",
      }}>{value}</div>
    </div>
  );
}
