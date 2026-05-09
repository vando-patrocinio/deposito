/* Helpers de auth do colaborador via Emergent Google Auth + device_id estável */

import { api } from "@/api";

const DEVICE_KEY = "pp_device_id";
const TOKEN_KEY = "pp_collab_token";
const COLLAB_KEY = "pp_collab_id";

function genUUID() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return "dev-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function getOrCreateDeviceId() {
  let d = localStorage.getItem(DEVICE_KEY);
  if (!d) {
    d = genUUID();
    localStorage.setItem(DEVICE_KEY, d);
  }
  return d;
}

export function getStoredToken() { return localStorage.getItem(TOKEN_KEY); }
export function getStoredCollabId() { return localStorage.getItem(COLLAB_KEY); }

export function clearLocalSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(COLLAB_KEY);
}

export function startGoogleLogin() {
  // Ao voltar do Google, queremos cair na MESMA URL com mode=app preservado
  // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
  const u = new URL(window.location.href);
  if (u.searchParams.get("mode") !== "app") u.searchParams.set("mode", "app");
  u.hash = "";
  const redirectUrl = u.toString();
  window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
}

export async function processSessionFromUrl() {
  // Verifica se há #session_id=... no URL fragment e processa
  if (!window.location.hash || !window.location.hash.includes("session_id=")) return null;
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const sid = params.get("session_id");
  if (!sid) return null;
  const device_id = getOrCreateDeviceId();
  const r = await api.collabProcessSession({ session_id: sid, device_id });
  if (r?.session_token) {
    localStorage.setItem(TOKEN_KEY, r.session_token);
    if (r.collaborator?.id) localStorage.setItem(COLLAB_KEY, r.collaborator.id);
  }
  // Limpa o hash e o eventual mode=app
  const cleanUrl = window.location.pathname + window.location.search;
  window.history.replaceState(null, "", cleanUrl);
  return r;
}

export async function fetchMe() {
  const token = getStoredToken();
  if (!token) return null;
  try {
    return await api.collabAuthMe(token);
  } catch {
    clearLocalSession();
    return null;
  }
}

export async function logoutCollab() {
  const token = getStoredToken();
  try { if (token) await api.collabLogout(token); } catch {}
  clearLocalSession();
}
