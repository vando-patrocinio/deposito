/**
 * slaAlerts.js — utilitário de alerta sonoro + notificação para bolhas atrasadas (overdue).
 *
 * - Toca um beep curto (Web Audio API, sem arquivo externo) quando o número
 *   de bolhas overdue aumenta.
 * - Emite Browser Notification se permitido.
 * - O toggle do usuário é persistido em localStorage ('sla_alerts_enabled').
 */

const STORAGE_KEY = "sla_alerts_enabled";

export function isAlertsEnabled() {
  if (typeof window === "undefined") return false;
  // iter215aj — Alertas LIGADOS por padrão. Só fica desligado se o user
  // explicitamente clicou em "Mudo" (chave armazenada como "0").
  const v = window.localStorage.getItem(STORAGE_KEY);
  return v !== "0";  // default true; "0" = desligado pelo user
}

export function setAlertsEnabled(on) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, on ? "1" : "0");
  if (on && typeof Notification !== "undefined" && Notification.permission === "default") {
    try { Notification.requestPermission(); } catch { /* ignore */ }
  }
}

let _ctx = null;
function getCtx() {
  if (typeof window === "undefined") return null;
  if (_ctx) return _ctx;
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return null;
  _ctx = new Ctx();
  return _ctx;
}

/** Toca dois beeps curtos no estilo "alerta de fábrica" */
export function playOverdueBeep() {
  const ctx = getCtx();
  if (!ctx) return;
  // Resume context se suspenso (autoplay policy)
  if (ctx.state === "suspended") {
    try { ctx.resume(); } catch { /* ignore */ }
  }
  const now = ctx.currentTime;
  [0, 0.25].forEach((delay) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "square";
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.0001, now + delay);
    gain.gain.exponentialRampToValueAtTime(0.18, now + delay + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + delay + 0.18);
    osc.connect(gain).connect(ctx.destination);
    osc.start(now + delay);
    osc.stop(now + delay + 0.2);
  });
}

export function notifyOverdue(count) {
  if (typeof Notification === "undefined") return;
  if (Notification.permission !== "granted") return;
  try {
    new Notification("Bolha ATRASADA na lousa", {
      body: `${count} bolha(s) com SLA estourado. Verifique o painel.`,
      tag: "lousa-sla-overdue",
      renotify: true,
    });
  } catch { /* ignore */ }
}

/** Dispara alertas se count subiu E se usuário ativou. Retorna o count para encadear. */
export function maybeFireOverdueAlerts(prevCount, newCount) {
  if (!isAlertsEnabled()) return newCount;
  if (newCount > prevCount && newCount > 0) {
    playOverdueBeep();
    notifyOverdue(newCount);
  }
  return newCount;
}
