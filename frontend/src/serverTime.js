/**
 * serverTime.js — Singleton de sincronização com o relógio do servidor.
 *
 * Todo o app deve usar `serverNow()` ao invés de `Date.now()` ou `new Date()`
 * para qualquer cálculo/exibição de tempo. Isso garante que o relógio do
 * dispositivo do usuário não influencie horários (anti-tampering).
 *
 * Sincroniza com /api/server-time a cada 60s usando performance.now() para
 * o tick local (monotônico, imune a ajustes manuais do relógio do device).
 */
import { api } from "@/api";

let offsetMs = null;          // server_ms - performance.now()
let tz = "America/Sao_Paulo";
let synced = false;
let listeners = new Set();
let started = false;

function _perfNow() {
  return (typeof performance !== "undefined" ? performance.now() : Date.now());
}

async function _syncOnce() {
  try {
    const t0 = _perfNow();
    const r = await api.serverTime();
    const t1 = _perfNow();
    const rtt = t1 - t0;
    const serverNow = Number(r.epoch_ms) + rtt / 2;
    offsetMs = serverNow - t1;
    if (r.tz) tz = r.tz;
    synced = true;
    listeners.forEach((fn) => { try { fn(); } catch { /* ignore */ } });
  } catch {
    // Mantém último offset conhecido se houver; senão fica null (caller usa Date.now())
  }
}

export function startServerTime() {
  if (started) return;
  started = true;
  _syncOnce();
  setInterval(_syncOnce, 60_000);
}

/** Retorna timestamp em ms sincronizado com o servidor (cai pra Date.now() se ainda não sincronizado). */
export function serverNow() {
  if (offsetMs == null) return Date.now();
  return _perfNow() + offsetMs;
}

/** Retorna Date object sincronizado. */
export function serverDate() {
  return new Date(serverNow());
}

export function isServerTimeSynced() {
  return synced;
}

export function getServerTimezone() {
  return tz;
}

/** React hook — força re-render quando ticka 1x/s. */
import { useEffect, useState } from "react";
export function useServerNow(intervalMs = 1000) {
  const [, setTick] = useState(0);
  useEffect(() => {
    startServerTime();
    const onSync = () => setTick((x) => x + 1);
    listeners.add(onSync);
    const id = setInterval(() => setTick((x) => x + 1), intervalMs);
    return () => { clearInterval(id); listeners.delete(onSync); };
  }, [intervalMs]);
  return { now: serverNow(), date: serverDate(), tz, synced };
}
