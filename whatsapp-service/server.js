/**
 * PontoIA — Baileys WhatsApp sidecar
 *
 * Roda na porta 3002 (interna). FastAPI fala com ele em
 * http://localhost:3002.
 *
 * Endpoints expostos:
 *   GET  /qr           → { qr: <dataURL>|null, status: <string>, me: {...}|null }
 *   GET  /status       → { connected: bool, me: {...}|null, last_disconnect: ... }
 *   POST /send         → { phone, text }  →  envia mensagem WhatsApp
 *   POST /logout       → desconecta + apaga sessão (próxima conexão pede QR novo)
 *
 * Webhook (saída):
 *   POST {WEBHOOK_URL}/whatsapp/inbound  ← entrega msg recebida ao FastAPI
 *
 * Sessão persiste em /app/whatsapp-service/auth_info/ (multi-file).
 */

const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} = require("@whiskeysockets/baileys");
const express = require("express");
const cors = require("cors");
const qrcode = require("qrcode");
const axios = require("axios");
const pino = require("pino");
const fs = require("fs");
const path = require("path");

const PORT = parseInt(process.env.WA_PORT || "3002", 10);
const WEBHOOK_BASE = process.env.WA_WEBHOOK_BASE || "http://localhost:8001/api";
const INBOUND_TOKEN = process.env.WA_INBOUND_TOKEN || "";
const AUTH_DIR = path.join(__dirname, "auth_info");
const logger = pino({ level: "warn" });

// Estado em memória
let sock = null;
let currentQr = null;          // base64 dataURL "data:image/png;base64,..."
let lastQrAt = null;
let connState = "disconnected"; // "connecting" | "connected" | "disconnected"
let me = null;
let lastDisconnect = null;
let reconnectTimer = null;

const app = express();
app.use(cors());
app.use(express.json({ limit: "2mb" }));

/* ---------- Boot Baileys ---------- */
async function startSock() {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  try {
    fs.mkdirSync(AUTH_DIR, { recursive: true });
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: [2, 3000, 0] }));
    connState = "connecting";

    sock = makeWASocket({
      version,
      auth: state,
      printQRInTerminal: false,
      browser: ["PontoIA", "Chrome", "1.0.0"],
      logger,
      syncFullHistory: false,
      markOnlineOnConnect: false,
    });

    sock.ev.on("creds.update", saveCreds);

    // Quando Baileys emite erro fatal de init/stream, normalmente já vai
    // emitir connection:close, mas em algumas builds ele atrasa minutos.
    // Capturamos via `pino` redirecionado pelo logger acima — mas como esse
    // logger filtra warn, escutamos aqui também o stream:error direto.
    try {
      sock.ws?.on?.("error", (e) => {
        console.warn("[wa] ws error:", e?.message || e);
        forceReconnect("ws-error");
      });
      sock.ws?.on?.("close", () => {
        if (connState === "connected") {
          console.warn("[wa] ws closed inesperadamente — forçando reconnect");
          forceReconnect("ws-close");
        }
      });
    } catch (e) { /* ignore */ }

    sock.ev.on("connection.update", async (update) => {
      const { connection, lastDisconnect: ld, qr } = update;
      if (qr) {
        try {
          currentQr = await qrcode.toDataURL(qr, { width: 380, margin: 1 });
          lastQrAt = new Date().toISOString();
          console.log("[wa] novo QR gerado (válido ~60s)");
        } catch (e) { console.error("[wa] qrcode encode err", e); }
      }
      if (connection === "open") {
        currentQr = null;
        connState = "connected";
        me = sock.user || null;
        console.log("[wa] CONECTADO como", me?.id);
      }
      if (connection === "close") {
        connState = "disconnected";
        const code = ld?.error?.output?.statusCode;
        lastDisconnect = { code, reason: String(ld?.error?.message || "") };
        const loggedOut = code === DisconnectReason.loggedOut;
        console.log("[wa] desconectado code=", code, "loggedOut=", loggedOut);
        if (!loggedOut) {
          reconnectTimer = setTimeout(startSock, 3000);
        }
      }
    });

    sock.ev.on("presence.update", (update) => {
      try {
        const { id, presences } = update;
        if (!presences) return;
        for (const [jid, p] of Object.entries(presences)) {
          presenceCache.set(jid, {
            status: p.lastKnownPresence || "unknown",
            last_seen: p.lastSeen || null,
            cached_at: Date.now(),
          });
          // Também atualiza o JID pai (id) se diferente
          if (id && id !== jid) {
            presenceCache.set(id, presenceCache.get(jid));
          }
        }
      } catch (e) { /* ignore */ }
    });

    sock.ev.on("messages.upsert", async (ev) => {
      try {
        if (ev.type !== "notify") return;
        for (const m of ev.messages || []) {
          if (m.key.fromMe) continue;
          const msg = m.message;
          if (!msg) continue;
          const text =
            msg.conversation ||
            msg.extendedTextMessage?.text ||
            msg.imageMessage?.caption ||
            msg.videoMessage?.caption ||
            "";
          const fromJid = m.key.remoteJid || "";
          const fromMe = !!m.key.fromMe;
          const phone = fromJid.split("@")[0];
          // Notifica FastAPI
          try {
            await axios.post(`${WEBHOOK_BASE}/whatsapp-baileys/inbound`, {
              phone,
              jid: fromJid,
              from_me: fromMe,
              text,
              message_id: m.key.id,
              timestamp: m.messageTimestamp,
              push_name: m.pushName || null,
            }, {
              timeout: 15000,
              headers: INBOUND_TOKEN ? { "X-WA-Token": INBOUND_TOKEN } : {},
            });
          } catch (err) {
            console.warn("[wa] webhook FastAPI falhou:", err.message);
          }
        }
      } catch (e) { console.error("[wa] msg handler err", e); }
    });

  } catch (e) {
    console.error("[wa] startSock err", e);
    connState = "disconnected";
    reconnectTimer = setTimeout(startSock, 5000);
  }
}

/* ---------- HTTP endpoints ---------- */
app.get("/health", (_req, res) => res.json({ ok: true, state: connState }));

app.get("/qr", (_req, res) => {
  res.json({
    qr: currentQr,
    status: connState,
    me,
    last_qr_at: lastQrAt,
    last_disconnect: lastDisconnect,
  });
});

app.get("/status", (_req, res) => {
  res.json({
    connected: connState === "connected",
    state: connState,
    me,
    last_disconnect: lastDisconnect,
  });
});

/** Marca o socket como morto e força reconexão. Usado quando sendMessage
 *  trava ou query retorna timeout — Baileys às vezes não emite o evento
 *  `connection:close` imediatamente nesses casos, e o socket fica zumbi
 *  aceitando sendMessage sem entregar nada. */
function forceReconnect(reason) {
  console.warn("[wa] forçando reconexão:", reason);
  connState = "disconnected";
  lastDisconnect = { code: 0, reason: `forced:${reason}` };
  try { if (sock?.end) sock.end(new Error(reason)); } catch (e) { /* ignore */ }
  try { if (sock?.ws?.close) sock.ws.close(); } catch (e) { /* ignore */ }
  sock = null;
  if (reconnectTimer) { clearTimeout(reconnectTimer); }
  reconnectTimer = setTimeout(startSock, 1500);
}

function withTimeout(promise, ms, label) {
  let to;
  const timeout = new Promise((_resolve, reject) => {
    to = setTimeout(() => reject(new Error(`${label} timeout ${ms}ms`)), ms);
  });
  return Promise.race([
    promise.then((v) => { clearTimeout(to); return v; },
                  (e) => { clearTimeout(to); throw e; }),
    timeout,
  ]);
}

app.post("/send", async (req, res) => {
  if (connState !== "connected" || !sock) {
    return res.status(503).json({ ok: false, error: "WhatsApp não conectado." });
  }
  let { phone, text } = req.body || {};
  if (!phone || !text) return res.status(400).json({ ok: false, error: "phone e text obrigatórios" });
  phone = String(phone).replace(/\D/g, "");
  if (!phone) return res.status(400).json({ ok: false, error: "phone inválido" });
  // Proteção: WhatsApp aceita silenciosamente sendMessage para o próprio número
  //   mas a mensagem nunca chega. Detectamos e retornamos erro claro.
  try {
    const mePhone = String(me?.id || "").split(":")[0].split("@")[0].replace(/\D/g, "");
    if (mePhone && mePhone === phone) {
      return res.status(400).json({
        ok: false,
        error: "Não é possível enviar mensagem para o próprio número conectado.",
      });
    }
  } catch (e) { /* ignore */ }
  const jid = phone.includes("@") ? phone : `${phone}@s.whatsapp.net`;
  try {
    // Timeout duro: se Baileys ficar zumbi, evita pendurar HTTP por minutos.
    const r = await withTimeout(
      sock.sendMessage(jid, { text: String(text) }),
      12000,
      "sendMessage",
    );
    return res.json({ ok: true, message_id: r.key?.id, jid });
  } catch (e) {
    console.error("[wa] send err", e?.message || e);
    // Erros típicos: "Timed Out", "Connection Closed", "send timeout"
    // → socket está morto/zumbi. Força reconexão.
    const msg = String(e?.message || "");
    const fatal = /timeout|closed|terminat|connection|stale/i.test(msg);
    if (fatal) forceReconnect(`send:${msg}`);
    return res.status(502).json({ ok: false, error: msg || "erro desconhecido" });
  }
});

app.post("/logout", async (_req, res) => {
  try {
    if (sock) {
      try { await sock.logout(); } catch (e) { /* ignore */ }
      sock = null;
    }
    // Apaga sessão para forçar novo QR
    try { fs.rmSync(AUTH_DIR, { recursive: true, force: true }); } catch (e) { /* ignore */ }
    connState = "disconnected";
    currentQr = null; me = null;
    setTimeout(startSock, 800);
    return res.json({ ok: true });
  } catch (e) {
    return res.status(500).json({ ok: false, error: e.message });
  }
});

/* ---------- Contact profile & presence ---------- */
/** Cache simples de avatares e presença pra não esmagar Baileys */
const profileCache = new Map();   // jid -> { avatar, name, cached_at }
const presenceCache = new Map();  // jid -> { status, last_seen, cached_at }

app.get("/contact-profile", async (req, res) => {
  if (!sock || connState !== "connected") {
    return res.status(503).json({ ok: false, error: "WhatsApp não conectado." });
  }
  let phone = String(req.query.phone || "").replace(/\D/g, "");
  if (!phone) return res.status(400).json({ ok: false, error: "phone obrigatório" });
  const jid = phone.includes("@") ? phone : `${phone}@s.whatsapp.net`;
  const cached = profileCache.get(jid);
  if (cached && (Date.now() - cached.cached_at) < 600000) {
    return res.json({ ok: true, ...cached, cached: true });
  }
  let avatar = null;
  let businessProfile = null;
  try {
    avatar = await sock.profilePictureUrl(jid, "image").catch(() => null);
  } catch (e) { /* ignore */ }
  try {
    businessProfile = await sock.getBusinessProfile(jid).catch(() => null);
  } catch (e) { /* ignore */ }
  const presence = presenceCache.get(jid);
  const payload = {
    ok: true,
    jid, phone,
    avatar,
    business: businessProfile,
    presence: presence ? presence.status : "unknown",
    last_seen: presence?.last_seen || null,
    cached_at: Date.now(),
  };
  profileCache.set(jid, payload);
  return res.json(payload);
});

app.post("/presence-subscribe", async (req, res) => {
  if (!sock || connState !== "connected") {
    return res.status(503).json({ ok: false, error: "WhatsApp não conectado." });
  }
  let phone = String(req.body?.phone || "").replace(/\D/g, "");
  if (!phone) return res.status(400).json({ ok: false, error: "phone obrigatório" });
  const jid = phone.includes("@") ? phone : `${phone}@s.whatsapp.net`;
  try {
    await sock.presenceSubscribe(jid);
    return res.json({ ok: true, jid });
  } catch (e) {
    return res.status(502).json({ ok: false, error: e.message });
  }
});

/* Batch: avatares de vários telefones de uma vez (usado pela lista do chat). */
app.post("/contacts-bulk", async (req, res) => {
  if (!sock || connState !== "connected") {
    return res.json({ ok: false, avatars: {}, error: "WhatsApp não conectado." });
  }
  const phones = Array.isArray(req.body?.phones) ? req.body.phones : [];
  const avatars = {};
  // Limite e dedupe pra não sobrecarregar Baileys
  const unique = Array.from(new Set(phones.map((p) => String(p).replace(/\D/g, ""))))
    .filter(Boolean)
    .slice(0, 100);
  await Promise.all(unique.map(async (phone) => {
    const jid = `${phone}@s.whatsapp.net`;
    const cached = profileCache.get(jid);
    if (cached && (Date.now() - cached.cached_at) < 1800000) {
      avatars[phone] = cached.avatar || null;
      return;
    }
    try {
      const url = await sock.profilePictureUrl(jid, "image").catch(() => null);
      profileCache.set(jid, {
        ok: true, jid, phone, avatar: url, business: null,
        presence: "unknown", last_seen: null, cached_at: Date.now(),
      });
      avatars[phone] = url || null;
    } catch (e) {
      avatars[phone] = null;
    }
  }));
  return res.json({ ok: true, avatars, count: unique.length });
});

app.listen(PORT, "127.0.0.1", () => {
  console.log(`[wa] sidecar ouvindo em 127.0.0.1:${PORT}`);
  startSock();
});
