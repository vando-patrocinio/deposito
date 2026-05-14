/**
 * Helper de sons & notificações do chat WhatsApp.
 * Sem dependência de arquivo MP3 — usa Web Audio API.
 * Falha silenciosa se o browser bloquear áudio/notification.
 */

let _suspendedUntil = 0; // timestamp ms — silencia até essa hora (debounce)

function _now() { return Date.now(); }

function _playTones(tones, gain = 0.18) {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.connect(g); g.connect(ctx.destination);
    osc.type = "sine";
    g.gain.value = gain;
    osc.start();
    let cumulative = 0;
    tones.forEach(([freq, dur]) => {
      setTimeout(() => { osc.frequency.value = freq; }, cumulative);
      cumulative += dur;
    });
    setTimeout(() => {
      g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.15);
      osc.stop(ctx.currentTime + 0.18);
      ctx.close().catch(() => {});
    }, cumulative + 50);
  } catch {
    /* sem áudio */
  }
}

/** Beep alegre tri-tom — quando chega mensagem nova de cliente sem atendente. */
export function chimeNewMessage() {
  if (_now() < _suspendedUntil) return;
  _suspendedUntil = _now() + 2000; // debounce 2s entre alertas
  _playTones([[523, 80], [659, 80], [784, 120]], 0.12);  // C5 → E5 → G5
}

/** Beep de aviso duplo — desconexão WhatsApp / falha crítica. */
export function chimeDisconnect() {
  _playTones([[880, 150], [660, 130]], 0.18);
}

/** Notificação do navegador (silenciosa se sem permissão). */
export function notifyBrowser(title, body, tag = "chat") {
  try {
    if (!("Notification" in window)) return;
    if (Notification.permission !== "granted") return;
    new Notification(title, { body, tag, requireInteraction: false });
  } catch { /* ignore */ }
}

/** Pede permissão de notificação (idempotente). */
export function requestNotificationPermission() {
  try {
    if (!("Notification" in window)) return;
    if (Notification.permission === "default") {
      Notification.requestPermission();
    }
  } catch { /* ignore */ }
}
