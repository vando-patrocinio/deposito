// Helper de Web Push
import { api } from "@/api";

const SW_URL = "/sw-push.js";

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export async function getPushPermission() {
  if (!("Notification" in window)) return "unsupported";
  return Notification.permission;
}

export async function ensureServiceWorker() {
  if (!("serviceWorker" in navigator)) throw new Error("Service Worker não suportado");
  let reg = await navigator.serviceWorker.getRegistration(SW_URL);
  if (!reg) reg = await navigator.serviceWorker.register(SW_URL, { scope: "/" });
  await navigator.serviceWorker.ready;
  return reg;
}

export async function getCurrentSubscription() {
  if (!("serviceWorker" in navigator)) return null;
  const reg = await navigator.serviceWorker.getRegistration(SW_URL);
  if (!reg) return null;
  return await reg.pushManager.getSubscription();
}

export async function enablePushForGestor() {
  if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)) {
    throw new Error("Seu navegador não suporta Web Push.");
  }
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error("Permissão de notificação negada");

  const reg = await ensureServiceWorker();
  const { public_key } = await api.pushVapidKey();
  if (!public_key) throw new Error("Servidor sem chave VAPID configurada");

  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(public_key),
    });
  }
  await api.pushSubscribe({
    endpoint: sub.endpoint,
    keys: sub.toJSON().keys,
    user_agent: navigator.userAgent,
  });
  return sub;
}

export async function disablePushForGestor() {
  const sub = await getCurrentSubscription();
  if (sub) {
    try { await api.pushUnsubscribe({ endpoint: sub.endpoint }); } catch {}
    try { await sub.unsubscribe(); } catch {}
  }
  return true;
}

export async function sendTestPush() {
  return api.pushTest();
}
