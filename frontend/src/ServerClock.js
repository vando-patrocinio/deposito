import React, { useEffect, useState, useRef } from "react";
import { api } from "@/api";

/**
 * Relógio sincronizado com o servidor (não usa o relógio do dispositivo).
 *
 * Estratégia:
 * 1. A cada 60s busca /api/server-time e calibra o offset (server_epoch_ms - performance.now()).
 * 2. Tickeia 1x/s usando performance.now() + offset (monotônico, não muda se o usuário ajusta o relógio).
 * 3. Fallback: se /server-time falhar, segue tickando com o último offset conhecido.
 */
export default function ServerClock({ compact = false }) {
  const offsetRef = useRef(null); // server_ms - perf_ms
  const [tick, setTick] = useState(0);
  const [synced, setSynced] = useState(false);
  const [tz, setTz] = useState("America/Sao_Paulo");

  // Sync com servidor
  useEffect(() => {
    let alive = true;
    let timer = null;
    async function sync() {
      try {
        const t0 = (typeof performance !== "undefined" ? performance.now() : Date.now());
        const r = await api.serverTime();
        const t1 = (typeof performance !== "undefined" ? performance.now() : Date.now());
        if (!alive) return;
        const rtt = t1 - t0;
        // Estimativa: hora servidor ≈ epoch_ms + rtt/2 (one-way)
        const serverNow = Number(r.epoch_ms) + rtt / 2;
        offsetRef.current = serverNow - t1;
        setSynced(true);
        if (r.tz) setTz(r.tz);
      } catch {
        if (offsetRef.current == null) {
          // Sem nenhum sync ainda — usa relógio local como fallback (mas marca não-sincronizado)
          offsetRef.current = 0;
        }
      }
    }
    sync();
    timer = setInterval(sync, 60_000);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  // Tick local 1x/s
  useEffect(() => {
    const t = setInterval(() => setTick((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, []);

  function nowMs() {
    const off = offsetRef.current;
    const perf = (typeof performance !== "undefined" ? performance.now() : Date.now());
    return off == null ? Date.now() : perf + off;
  }

  const ms = nowMs();
  // Formata em PT-BR no fuso do servidor
  let label = "--:--";
  let date = "";
  try {
    const d = new Date(ms);
    label = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: compact ? undefined : "2-digit", timeZone: tz });
    date = d.toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit", timeZone: tz });
  } catch { /* ignore */ }

  // tick var é apenas pra forçar re-render
  void tick;

  return (
    <div
      data-testid="server-clock"
      title={synced ? `Hora do servidor (${tz})` : "Sincronizando com servidor..."}
      style={{
        display: "inline-flex", alignItems: "center", gap: 8,
        padding: compact ? "4px 10px" : "6px 12px",
        background: synced ? "linear-gradient(135deg,#0f172a,#1e293b)" : "#94a3b8",
        color: "white", borderRadius: 999,
        boxShadow: "0 2px 8px rgba(15,23,42,.18)",
        fontVariantNumeric: "tabular-nums",
      }}
    >
      <span style={{
        width: 8, height: 8, borderRadius: "50%",
        background: synced ? "#10b981" : "#f59e0b",
        boxShadow: synced ? "0 0 0 3px rgba(16,185,129,.25)" : "0 0 0 3px rgba(245,158,11,.25)",
        animation: synced ? "pulse 2.5s ease-in-out infinite" : "none",
      }} />
      <strong style={{ fontSize: compact ? 13 : 15, letterSpacing: 0.4 }}>{label}</strong>
      {!compact && date && (
        <span style={{ fontSize: 10, color: "#cbd5e1", textTransform: "capitalize" }}>{date}</span>
      )}
    </div>
  );
}
