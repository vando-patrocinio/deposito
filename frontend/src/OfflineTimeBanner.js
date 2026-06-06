import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";

/**
 * OfflineTimeBanner — detecta:
 *  - Dispositivo offline (navigator.onLine)
 *  - Horário do dispositivo dessincronizado com o servidor (se time_sync_enabled em settings)
 *
 * Exporta o estado via prop onStatusChange({offline, time_drift_blocked}) — para outros
 * componentes (Lousa, ClockApp) bloquearem ações quando inseguro.
 */
export default function OfflineTimeBanner({ onStatusChange }) {
  const [offline, setOffline] = useState(typeof navigator !== "undefined" ? !navigator.onLine : false);
  const [drift, setDrift] = useState(null);   // segundos de diferença
  const [maxDrift, setMaxDrift] = useState(60);
  const [syncEnabled, setSyncEnabled] = useState(false);

  // listener online/offline
  useEffect(() => {
    if (typeof window === "undefined") return;
    const on = () => setOffline(false);
    const off = () => setOffline(true);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);

  const checkTime = useCallback(async () => {
    if (offline) return;
    try {
      const r = await api.serverTime();
      const localMs = Date.now();
      const drift_s = Math.round((localMs - r.epoch_ms) / 1000);
      setDrift(drift_s);
      setMaxDrift(r.max_drift_seconds || 60);
      setSyncEnabled(r.sync_enabled);
    } catch (e) {
      // ignora — pode ser auth ou rede
    }
  }, [offline]);

  useEffect(() => {
    checkTime();
    const t = setInterval(checkTime, 60000);  // re-checa a cada 1min
    return () => clearInterval(t);
  }, [checkTime]);

  const driftBlocked = syncEnabled && drift !== null && Math.abs(drift) > maxDrift;
  const driftWarn = !driftBlocked && drift !== null && Math.abs(drift) > maxDrift / 2;

  // Notifica pai
  useEffect(() => {
    if (onStatusChange) onStatusChange({ offline, drift, drift_blocked: driftBlocked });
  }, [offline, drift, driftBlocked, onStatusChange]);

  if (!offline && !driftBlocked && !driftWarn) return null;

  const conf = offline ? {
    bg: "#dc2626", text: "white",
    icon: "️",
    msg: "Dispositivo OFFLINE — a lousa está trancada. Reconecte para continuar.",
  } : driftBlocked ? {
    bg: "#dc2626", text: "white",
    icon: "",
    msg: `Relógio dessincronizado (${drift > 0 ? "+" : ""}${drift}s de diferença) — ações bloqueadas. Sincronize o horário do dispositivo.`,
  } : {
    bg: "#f59e0b", text: "white",
    icon: "⏱️",
    msg: `Aviso: relógio com ${drift > 0 ? "+" : ""}${drift}s de diferença do servidor. Verifique o horário do dispositivo.`,
  };

  return (
    <div
      data-testid={offline ? "offline-banner" : driftBlocked ? "drift-blocked-banner" : "drift-warn-banner"}
      style={{
        background: conf.bg, color: conf.text,
        padding: "10px 14px", textAlign: "center",
        fontWeight: 700, fontSize: 13, position: "sticky",
        top: 0, zIndex: 60, display: "flex",
        alignItems: "center", justifyContent: "center", gap: 10,
      }}
    >
      <span style={{ fontSize: 18 }}>{conf.icon}</span>
      <span>{conf.msg}</span>
    </div>
  );
}
