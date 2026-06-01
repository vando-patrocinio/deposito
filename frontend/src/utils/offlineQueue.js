/* offlineQueue.js — iter183
 *
 * Fila offline para cadastros de rede (CTO / CE / Cabo) e quaisquer outras
 * mutações que precisem sobreviver a perda de conexão no campo.
 *
 * Backend: IndexedDB ("smartprov-outbox" / store "registrations")
 * Capacity: ~50MB+ (limite real depende do navegador)
 * Sobrevive a: fechar app, reboot, recarregar página.
 *
 * Schema do item:
 * {
 *   id:           "off-<uuid>"           // gerado localmente
 *   created_at:   ISO string
 *   kind:         "cto" | "ce" | "cabo"  // identifica o tipo
 *   endpoint:     "/api/rede-ia/public/ctos/<collabId>" (ou similar)
 *   method:       "POST" | "PUT"
 *   body:         object                  // payload completo
 *   photo_b64:    string | null           // foto base64 (se houver)
 *   collab_id:    string                  // técnico que criou
 *   collab_name:  string
 *   description:  string                  // resumo p/ exibição na UI
 *   status:       "pending" | "sending" | "synced" | "failed" | "conflict"
 *   last_error:   string | null
 *   attempts:     number
 *   last_attempt_at: ISO string | null
 *   server_id:    string | null            // preenchido após sync OK
 * }
 */

const DB_NAME = "smartprov-outbox";
const DB_VERSION = 1;
const STORE = "registrations";

let _dbPromise = null;

function openDB() {
  if (_dbPromise) return _dbPromise;
  _dbPromise = new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("IndexedDB indisponível neste navegador"));
      return;
    }
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onerror = () => reject(req.error);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: "id" });
        store.createIndex("status", "status", { unique: false });
        store.createIndex("created_at", "created_at", { unique: false });
        store.createIndex("collab_id", "collab_id", { unique: false });
      }
    };
    req.onsuccess = () => resolve(req.result);
  });
  return _dbPromise;
}

function tx(mode = "readonly") {
  return openDB().then((db) => db.transaction(STORE, mode).objectStore(STORE));
}

function uuid() {
  return "off-" + Math.random().toString(36).slice(2, 11)
                   + Date.now().toString(36).slice(-4);
}

// ============================================================
// CRUD
// ============================================================

export async function enqueue({
  kind, endpoint, method = "POST", body,
  photo_b64 = null, collab_id, collab_name, description,
}) {
  const item = {
    id: uuid(),
    created_at: new Date().toISOString(),
    kind, endpoint, method, body, photo_b64,
    collab_id, collab_name, description,
    status: "pending",
    last_error: null,
    attempts: 0,
    last_attempt_at: null,
    server_id: null,
  };
  const store = await tx("readwrite");
  await new Promise((res, rej) => {
    const r = store.add(item);
    r.onsuccess = () => res();
    r.onerror = () => rej(r.error);
  });
  notifyChange();
  return item;
}

export async function listPending(collabId = null) {
  const store = await tx();
  return new Promise((res, rej) => {
    const out = [];
    const req = store.openCursor();
    req.onsuccess = (e) => {
      const cur = e.target.result;
      if (!cur) { res(out); return; }
      const v = cur.value;
      const ok = ["pending", "failed", "conflict", "sending"].includes(v.status)
                   && (!collabId || v.collab_id === collabId);
      if (ok) out.push(v);
      cur.continue();
    };
    req.onerror = () => rej(req.error);
  });
}

export async function listAll() {
  const store = await tx();
  return new Promise((res, rej) => {
    const out = [];
    const req = store.openCursor();
    req.onsuccess = (e) => {
      const cur = e.target.result;
      if (!cur) { res(out); return; }
      out.push(cur.value);
      cur.continue();
    };
    req.onerror = () => rej(req.error);
  });
}

export async function get(id) {
  const store = await tx();
  return new Promise((res, rej) => {
    const r = store.get(id);
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
}

export async function update(id, patch) {
  const store = await tx("readwrite");
  const cur = await new Promise((res, rej) => {
    const r = store.get(id);
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
  if (!cur) return null;
  const next = { ...cur, ...patch };
  await new Promise((res, rej) => {
    const r = store.put(next);
    r.onsuccess = () => res();
    r.onerror = () => rej(r.error);
  });
  notifyChange();
  return next;
}

export async function remove(id) {
  const store = await tx("readwrite");
  await new Promise((res, rej) => {
    const r = store.delete(id);
    r.onsuccess = () => res();
    r.onerror = () => rej(r.error);
  });
  notifyChange();
}

export async function clearSynced() {
  const items = await listAll();
  const synced = items.filter((i) => i.status === "synced");
  for (const i of synced) await remove(i.id);
  return synced.length;
}

// ============================================================
// Events
// ============================================================

const listeners = new Set();
export function onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }
function notifyChange() {
  for (const fn of listeners) {
    try { fn(); } catch { /* ignore */ }
  }
}

// ============================================================
// Sync engine — tenta enviar todos os pendentes
// ============================================================

let _syncInFlight = false;

export async function syncAll(apiBase = "") {
  if (_syncInFlight) return { ok: 0, fail: 0, skipped: 0 };
  if (typeof navigator !== "undefined" && navigator.onLine === false) {
    return { ok: 0, fail: 0, skipped: 0, reason: "offline" };
  }
  _syncInFlight = true;
  let ok = 0;
  let fail = 0;
  try {
    const items = await listPending();
    for (const item of items) {
      if (item.status === "synced") continue;
      try {
        await update(item.id, {
          status: "sending",
          last_attempt_at: new Date().toISOString(),
        });
        const url = apiBase.replace(/\/$/, "") + item.endpoint;
        // Anexa foto base64 ao body se houver
        const finalBody = item.photo_b64
          ? { ...item.body, photo_base64: item.photo_b64 }
          : item.body;
        const resp = await fetch(url, {
          method: item.method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(finalBody),
        });
        if (resp.ok) {
          let serverData = {};
          try { serverData = await resp.json(); } catch { /* ignore */ }
          await update(item.id, {
            status: "synced",
            server_id: serverData?.id || null,
            attempts: (item.attempts || 0) + 1,
            last_error: null,
          });
          ok += 1;
        } else if (resp.status === 409) {
          // Duplicado / conflito de número
          let errText = "";
          try { errText = (await resp.json())?.detail || ""; } catch { /* ignore */ }
          await update(item.id, {
            status: "conflict",
            last_error: `Conflito (409): ${errText}`,
            attempts: (item.attempts || 0) + 1,
          });
          fail += 1;
        } else {
          let errText = `HTTP ${resp.status}`;
          try {
            const j = await resp.json();
            errText = j?.detail || errText;
          } catch { /* ignore */ }
          await update(item.id, {
            status: "failed",
            last_error: errText,
            attempts: (item.attempts || 0) + 1,
          });
          fail += 1;
        }
      } catch (e) {
        await update(item.id, {
          status: "failed",
          last_error: e?.message || String(e),
          attempts: (item.attempts || 0) + 1,
        });
        fail += 1;
      }
    }
  } finally {
    _syncInFlight = false;
  }
  notifyChange();
  return { ok, fail };
}

// ============================================================
// Auto-sync on online + interval
// ============================================================

let _autoStarted = false;
export function startAutoSync(apiBase = "") {
  if (_autoStarted) return;
  _autoStarted = true;
  if (typeof window === "undefined") return;
  window.addEventListener("online", () => {
    syncAll(apiBase).catch(() => {});
  });
  // Tenta a cada 60s caso esteja online (network flap)
  setInterval(() => {
    if (navigator.onLine) syncAll(apiBase).catch(() => {});
  }, 60000);
  // Tenta uma vez no boot caso já esteja online com pendências
  if (navigator.onLine) syncAll(apiBase).catch(() => {});
}

export function isOnline() {
  return typeof navigator === "undefined" ? true : navigator.onLine;
}

export default {
  enqueue, listPending, listAll, get, update, remove, clearSynced,
  syncAll, startAutoSync, isOnline, onChange,
};
