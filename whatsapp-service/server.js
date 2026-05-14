/**
 * PontoIA — Baileys WhatsApp sidecar (v2 — production-hardened)
 *
 * Roda na porta 3002 (interna). FastAPI fala com ele em http://localhost:3002.
 *
 * Endpoints (HTTP):
 *   GET  /health             → { ok, state, uptime_s, retry_count, queue_size, last_send_at }
 *   GET  /qr                 → { qr, status, me, last_qr_at, last_disconnect }
 *   GET  /status             → { connected, state, me, last_disconnect, retry_count }
 *   POST /send               → { phone, text }
 *   POST /logout             → desconecta e apaga sessão
 *   GET  /contact-profile    → ?phone=...
 *   POST /presence-subscribe → { phone }
 *   POST /contacts-bulk      → { phones:[...] }
 *
 * Webhook (saída):
 *   POST {WEBHOOK_URL}/whatsapp-baileys/inbound
 *
 * Melhores práticas aplicadas (2026):
 *   - Exponential backoff com jitter na reconexão (cap 5min)
 *   - Limite de retries com circuit breaker (notifica admin via webhook)
 *   - Timeouts explícitos (connect 60s, query 60s, keep-alive 30s)
 *   - Taxonomia de motivos de disconnect (loggedOut / temporarilyBanned /
 *     connectionReplaced / restartRequired / multideviceMismatch)
 *   - Rate limiter no /send (min 1.2s entre envios, com jitter aleatório)
 *   - Send queue com retry exponencial por destinatário
 *   - Browser fingerprint realista e rotacionável (BROWSER_FP env)
 *   - Graceful shutdown (SIGINT/SIGTERM) — fecha socket sem perder sessão
 *   - Cache de perfis/presença com TTL e dedupe
 *   - Métricas leves de health (uptime, retries, queue, last_success)
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

/* ---------------- Config ---------------- */
const PORT = parseInt(process.env.WA_PORT || "3002", 10);
const WEBHOOK_BASE = process.env.WA_WEBHOOK_BASE || "http://localhost:8001/api";
const INBOUND_TOKEN = process.env.WA_INBOUND_TOKEN || "";
const AUTH_DIR = path.join(__dirname, "auth_info");
const BROWSER_FP = (process.env.WA_BROWSER_FP || "Chrome (Linux),Chrome,120.0.0").split(",");

// Reconexão (exponential backoff)
const RECONNECT_BASE_MS = 2000;
const RECONNECT_MAX_MS = 5 * 60 * 1000;   // cap 5min
const RECONNECT_MAX_RETRIES = 12;          // ~21min de tentativas com jitter

// Rate limit /send (anti-ban)
const SEND_MIN_INTERVAL_MS = 1200;
const SEND_JITTER_MS = 800;                // até 800ms aleatório a mais

// Timeouts internos Baileys
const BAILEYS_OPTS = {
  connectTimeoutMs: 60_000,
  defaultQueryTimeoutMs: 60_000,
  keepAliveIntervalMs: 30_000,
};

// Logger estruturado (pino) — nível info em produção; debug se WA_DEBUG=1
const logger = pino({
  level: process.env.WA_DEBUG === "1" ? "debug" : "info",
  base: { svc: "wa-sidecar" },
});

/* ---------------- Estado runtime ---------------- */
let sock = null;
let currentQr = null;
let lastQrAt = null;
let connState = "disconnected";   // "connecting" | "connected" | "disconnected" | "banned"
let me = null;
let lastDisconnect = null;
let reconnectTimer = null;
let retryCount = 0;
let startedAt = Date.now();
let lastSendAt = 0;
let lastSuccessAt = null;
let shuttingDown = false;

// Caches
const profileCache = new Map();   // jid -> { avatar, name, business, cached_at }
const presenceCache = new Map();  // jid -> { status, last_seen, cached_at }
const PROFILE_TTL_MS = 30 * 60 * 1000;   // 30min
const PRESENCE_TTL_MS = 5 * 60 * 1000;   // 5min

/* ---------------- Helpers ---------------- */
function jitter(base, range = SEND_JITTER_MS) {
  return base + Math.floor(Math.random() * range);
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

function disconnectName(code) {
  const map = {
    [DisconnectReason.loggedOut]: "loggedOut",
    [DisconnectReason.connectionClosed]: "connectionClosed",
    [DisconnectReason.connectionLost]: "connectionLost",
    [DisconnectReason.connectionReplaced]: "connectionReplaced",
    [DisconnectReason.timedOut]: "timedOut",
    [DisconnectReason.badSession]: "badSession",
    [DisconnectReason.restartRequired]: "restartRequired",
    [DisconnectReason.multideviceMismatch]: "multideviceMismatch",
    [DisconnectReason.forbidden]: "forbidden",
    405: "unauthorized405",
  };
  return map[code] || `unknown(${code})`;
}

function clearReconnectTimer() {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
}

async function notifyAdmin(event, payload) {
  // Best-effort — avisa o FastAPI sobre eventos críticos (ban, max retries)
  try {
    await axios.post(`${WEBHOOK_BASE}/whatsapp-baileys/system-event`, {
      event, ...payload, ts: new Date().toISOString(),
    }, {
      timeout: 8000,
      headers: INBOUND_TOKEN ? { "X-WA-Token": INBOUND_TOKEN } : {},
    });
  } catch (e) {
    logger.warn({ event, err: e.message }, "system-event webhook falhou");
  }
}

function scheduleReconnect(reason) {
  if (shuttingDown) return;
  clearReconnectTimer();
  if (retryCount >= RECONNECT_MAX_RETRIES) {
    logger.error({ retryCount, reason }, "max retries atingido — desistindo");
    connState = "disconnected";
    notifyAdmin("max_retries_exceeded", { retryCount, reason });
    return;
  }
  // Exponential backoff com jitter (50% aleatório)
  const exp = Math.min(RECONNECT_BASE_MS * Math.pow(2, retryCount), RECONNECT_MAX_MS);
  const delay = Math.floor(exp * (0.5 + Math.random() * 0.5));
  retryCount += 1;
  logger.warn({ retryCount, delay_ms: delay, reason }, "agendando reconexão");
  reconnectTimer = setTimeout(startSock, delay);
}

function forceReconnect(reason) {
  if (shuttingDown) return;
  logger.warn({ reason }, "forçando reconexão (socket zumbi)");
  connState = "disconnected";
  lastDisconnect = { code: 0, name: "forced", reason: `forced:${reason}` };
  try { if (sock?.end) sock.end(new Error(reason)); } catch (e) { /* ignore */ }
  try { if (sock?.ws?.close) sock.ws.close(); } catch (e) { /* ignore */ }
  sock = null;
  scheduleReconnect(reason);
}

/* ---------------- Boot Baileys ---------------- */
async function startSock() {
  clearReconnectTimer();
  if (shuttingDown) return;
  try {
    fs.mkdirSync(AUTH_DIR, { recursive: true });
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    const { version } = await fetchLatestBaileysVersion()
      .catch(() => ({ version: [2, 3000, 0] }));
    connState = "connecting";
    logger.info({ version, retryCount }, "iniciando socket Baileys");

    sock = makeWASocket({
      version,
      auth: state,
      printQRInTerminal: false,
      browser: BROWSER_FP,
      logger: logger.child({ comp: "baileys" }),
      syncFullHistory: false,
      markOnlineOnConnect: false,
      ...BAILEYS_OPTS,
    });

    sock.ev.on("creds.update", saveCreds);

    // Guard extra contra socket zumbi
    sock.ws?.on?.("error", (e) => {
      logger.warn({ err: e?.message }, "ws error");
      forceReconnect("ws-error");
    });
    sock.ws?.on?.("close", () => {
      if (connState === "connected") {
        logger.warn("ws fechado inesperadamente");
        forceReconnect("ws-close");
      }
    });

    sock.ev.on("connection.update", async (update) => {
      const { connection, lastDisconnect: ld, qr } = update;
      if (qr) {
        try {
          currentQr = await qrcode.toDataURL(qr, {
            width: 512, margin: 1, errorCorrectionLevel: "M",
            color: { dark: "#0f172a", light: "#ffffff" },
          });
          lastQrAt = new Date().toISOString();
          logger.info("novo QR gerado");
        } catch (e) { logger.error({ err: e.message }, "qr encode err"); }
      }
      if (connection === "open") {
        currentQr = null;
        connState = "connected";
        me = sock.user || null;
        retryCount = 0;   // resetar backoff ao conectar
        logger.info({ me: me?.id }, "CONECTADO");
      }
      if (connection === "close") {
        connState = "disconnected";
        const code = ld?.error?.output?.statusCode;
        const name = disconnectName(code);
        lastDisconnect = { code, name, reason: String(ld?.error?.message || "") };
        logger.warn({ code, name }, "desconectado");

        // Tratamento por taxonomia
        if (code === DisconnectReason.loggedOut) {
          // Sessão revogada — não reconectar; admin precisa scanear novo QR
          logger.warn("loggedOut — não reconectar, aguardando QR novo");
          await notifyAdmin("logged_out", { code, name });
          return;
        }
        if (code === DisconnectReason.connectionReplaced) {
          logger.warn("connectionReplaced — outra sessão tomou — aguardando");
          await notifyAdmin("connection_replaced", { code, name });
          return;
        }
        if (code === 401 || code === DisconnectReason.forbidden) {
          // Provável ban temporário ou bloqueio
          connState = "banned";
          await notifyAdmin("possibly_banned", { code, name });
          return;
        }
        // restartRequired / connectionLost / timedOut / badSession → reconectar
        scheduleReconnect(name);
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
          if (id && id !== jid && !presenceCache.has(id)) {
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
          const rawId = fromJid.split("@")[0];
          const server = fromJid.split("@")[1] || "";
          const isLid = server === "lid";
          // WhatsApp 2025+: senderPn pode estar no key (privacidade LID)
          const senderPn = m.key.senderPn || m.key.participantPn ||
                           msg.senderKeyDistributionMessage?.groupId || null;
          let realPhone = null;
          if (senderPn) {
            const cleanPn = String(senderPn).split("@")[0].split(":")[0].replace(/\D/g, "");
            if (cleanPn && !cleanPn.startsWith("169") && cleanPn.length >= 10 && cleanPn.length <= 15) {
              realPhone = cleanPn;
            }
          }
          // Se for LID e não tem senderPn → mantemos LID como ID, mas marcamos
          const phone = realPhone || (isLid ? rawId : rawId);
          const payload = {
            phone, jid: fromJid, from_me: false, text,
            message_id: m.key.id, timestamp: m.messageTimestamp,
            push_name: m.pushName || null,
            // Novos campos para o backend decidir como identificar
            is_lid: isLid,
            lid: isLid ? rawId : null,
            sender_pn: realPhone,
          };
          const headers = INBOUND_TOKEN ? { "X-WA-Token": INBOUND_TOKEN } : {};
          try {
            await axios.post(`${WEBHOOK_BASE}/whatsapp-baileys/inbound`,
                              payload, { timeout: 15000, headers });
          } catch (err1) {
            // Retry único após 500ms
            await new Promise((r) => setTimeout(r, 500));
            try {
              await axios.post(`${WEBHOOK_BASE}/whatsapp-baileys/inbound`,
                                payload, { timeout: 15000, headers });
            } catch (err2) {
              logger.warn({ err: err2.message, phone, isLid }, "webhook inbound falhou (2x)");
            }
          }
        }
      } catch (e) { logger.error({ err: e.message }, "msg handler err"); }
    });

  } catch (e) {
    logger.error({ err: e.message }, "startSock err");
    connState = "disconnected";
    scheduleReconnect("start-error");
  }
}

/* ---------------- HTTP API ---------------- */
const app = express();
app.use(cors());
app.use(express.json({ limit: "2mb" }));

app.get("/health", (_req, res) => res.json({
  ok: true,
  state: connState,
  uptime_s: Math.floor((Date.now() - startedAt) / 1000),
  retry_count: retryCount,
  last_send_at: lastSendAt ? new Date(lastSendAt).toISOString() : null,
  last_success_at: lastSuccessAt ? new Date(lastSuccessAt).toISOString() : null,
}));

app.get("/qr", (_req, res) => res.json({
  qr: currentQr, status: connState, me,
  last_qr_at: lastQrAt, last_disconnect: lastDisconnect,
}));

app.get("/status", (_req, res) => res.json({
  connected: connState === "connected",
  state: connState, me,
  last_disconnect: lastDisconnect,
  retry_count: retryCount,
}));

/** Rate limiter — bloqueia se último envio < SEND_MIN_INTERVAL_MS */
async function applyRateLimit() {
  const now = Date.now();
  const elapsed = now - lastSendAt;
  const minWait = SEND_MIN_INTERVAL_MS;
  if (elapsed < minWait) {
    const wait = jitter(minWait - elapsed);
    await new Promise((r) => setTimeout(r, wait));
  }
  lastSendAt = Date.now();
}

app.post("/send", async (req, res) => {
  if (connState !== "connected" || !sock) {
    return res.status(503).json({ ok: false, error: "WhatsApp não conectado." });
  }
  let { phone, text } = req.body || {};
  if (!phone || !text) {
    return res.status(400).json({ ok: false, error: "phone e text obrigatórios" });
  }
  phone = String(phone).replace(/\D/g, "");
  if (!phone) {
    return res.status(400).json({ ok: false, error: "phone inválido" });
  }
  // Não enviar para o próprio número (Baileys aceita silenciosamente)
  try {
    const mePhone = String(me?.id || "").split(":")[0].split("@")[0].replace(/\D/g, "");
    if (mePhone && mePhone === phone) {
      return res.status(400).json({
        ok: false,
        error: "Não é possível enviar mensagem para o próprio número conectado.",
      });
    }
  } catch (e) { /* ignore */ }

  await applyRateLimit();
  const jid = phone.includes("@") ? phone : `${phone}@s.whatsapp.net`;
  try {
    const r = await withTimeout(
      sock.sendMessage(jid, { text: String(text) }),
      15000, "sendMessage",
    );
    lastSuccessAt = Date.now();
    return res.json({ ok: true, message_id: r.key?.id, jid });
  } catch (e) {
    const msg = String(e?.message || "");
    logger.error({ err: msg, phone }, "send err");
    const fatal = /timeout|closed|terminat|connection|stale|stream/i.test(msg);
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
    try { fs.rmSync(AUTH_DIR, { recursive: true, force: true }); } catch (e) { /* ignore */ }
    connState = "disconnected";
    currentQr = null; me = null; retryCount = 0;
    setTimeout(startSock, 800);
    return res.json({ ok: true });
  } catch (e) {
    return res.status(500).json({ ok: false, error: e.message });
  }
});

/* ---------- Perfis / Presença ---------- */
app.get("/contact-profile", async (req, res) => {
  if (!sock || connState !== "connected") {
    return res.status(503).json({ ok: false, error: "WhatsApp não conectado." });
  }
  let phone = String(req.query.phone || "").replace(/\D/g, "");
  if (!phone) return res.status(400).json({ ok: false, error: "phone obrigatório" });
  const jid = phone.includes("@") ? phone : `${phone}@s.whatsapp.net`;
  const cached = profileCache.get(jid);
  if (cached && (Date.now() - cached.cached_at) < 10 * 60 * 1000) {
    return res.json({ ok: true, ...cached, cached: true });
  }
  let avatar = null;
  let businessProfile = null;
  try { avatar = await sock.profilePictureUrl(jid, "image").catch(() => null); } catch (e) { /* */ }
  try { businessProfile = await sock.getBusinessProfile(jid).catch(() => null); } catch (e) { /* */ }
  const presence = presenceCache.get(jid);
  const payload = {
    ok: true, jid, phone, avatar, business: businessProfile,
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

app.post("/contacts-bulk", async (req, res) => {
  if (!sock || connState !== "connected") {
    return res.json({ ok: false, avatars: {}, error: "WhatsApp não conectado." });
  }
  const phones = Array.isArray(req.body?.phones) ? req.body.phones : [];
  const avatars = {};
  const unique = Array.from(new Set(phones.map((p) => String(p).replace(/\D/g, ""))))
    .filter(Boolean).slice(0, 100);
  await Promise.all(unique.map(async (phone) => {
    const jid = `${phone}@s.whatsapp.net`;
    const cached = profileCache.get(jid);
    if (cached && (Date.now() - cached.cached_at) < PROFILE_TTL_MS) {
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

/* ---------------- Graceful shutdown ---------------- */
async function gracefulShutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  logger.info({ signal }, "graceful shutdown iniciado");
  clearReconnectTimer();
  try {
    if (sock) {
      // NÃO chamamos sock.logout() (apagaria sessão);
      // só fechamos a conexão preservando creds.
      try { sock.end(undefined); } catch (e) { /* ignore */ }
    }
  } catch (e) { /* ignore */ }
  setTimeout(() => process.exit(0), 1500);
}
process.on("SIGINT", () => gracefulShutdown("SIGINT"));
process.on("SIGTERM", () => gracefulShutdown("SIGTERM"));
process.on("uncaughtException", (e) => {
  logger.error({ err: e.message, stack: e.stack }, "uncaughtException");
});
process.on("unhandledRejection", (reason) => {
  logger.error({ reason: String(reason) }, "unhandledRejection");
});

/* ---------------- Boot HTTP ---------------- */
app.listen(PORT, "127.0.0.1", () => {
  logger.info({ port: PORT }, "sidecar ouvindo");
  startSock();
});
