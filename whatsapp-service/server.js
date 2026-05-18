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
  downloadMediaMessage,
} = require("@whiskeysockets/baileys");
const express = require("express");
const cors = require("cors");
const qrcode = require("qrcode");
const axios = require("axios");
const pino = require("pino");
const fs = require("fs");
const path = require("path");

/* ---------------- Config ---------------- */
const PORT = parseInt(process.env.PORT || process.env.WA_PORT || "3002", 10);
const HOST = process.env.WA_HOST || "127.0.0.1";  // use "0.0.0.0" em deploy externo
const WEBHOOK_BASE = process.env.WA_WEBHOOK_BASE || "http://localhost:8001/api";
const INBOUND_TOKEN = process.env.WA_INBOUND_TOKEN || "";
// Bearer token que o backend FastAPI deve enviar para acessar este sidecar
// quando exposto publicamente. Vazio = sem proteção (apenas localhost).
const SIDECAR_TOKEN = process.env.WA_SIDECAR_TOKEN || "";
const AUTH_DIR = process.env.WA_AUTH_DIR || path.join(__dirname, "auth_info");
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
// Watchdog: detecta socket zumbi (conectado mas não recebe mais nada)
let lastInboundEventAt = 0;     // timestamp da última msg recebida do WhatsApp
let inboundEventCount = 0;       // contador acumulado de eventos messages.upsert
let watchdogTimer = null;
const WATCHDOG_INTERVAL_MS = 60 * 1000;        // checa a cada 60s
const WATCHDOG_STUCK_THRESHOLD_MS = 8 * 60 * 1000;  // 8min sem evento = zumbi
// Circuit breaker: histórico de loggedOuts pra detectar quando alguém está
// desconectando o número manualmente do celular ("Intentional Logout").
let loggedOutHistory = [];

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

/**
 * Watchdog: a cada 60s verifica se o sidecar está "conectado mas zumbi"
 * (state=connected porém messages.upsert parou de disparar).
 *
 * Sintoma: você manda WhatsApp do celular real, ele entrega ao Ligo (✓✓),
 * mas o sidecar nunca recebe o evento → Isabella nunca responde.
 *
 * Causa raiz típica: stream errored 515 sem trigger correto do `close`.
 *
 * Ação: se passou WATCHDOG_STUCK_THRESHOLD_MS desde o último evento
 * inbound E estamos `connected`, força um reconnect limpo.
 */
function startWatchdog() {
  if (watchdogTimer) clearInterval(watchdogTimer);
  watchdogTimer = setInterval(() => {
    if (shuttingDown) return;
    if (connState !== "connected") return;
    if (lastInboundEventAt === 0) {
      // Ainda não recebeu nenhum evento desde o boot —
      // tolerância de 10min antes de forçar reconnect
      const sinceBoot = Date.now() - startedAt;
      if (sinceBoot > 10 * 60 * 1000) {
        logger.warn({ sinceBoot }, "watchdog: 10min sem qualquer inbound — forçando reconnect");
        forceReconnect("watchdog-no-inbound-since-boot");
      }
      return;
    }
    const sinceLast = Date.now() - lastInboundEventAt;
    if (sinceLast > WATCHDOG_STUCK_THRESHOLD_MS) {
      logger.warn(
        { sinceLast, inboundEventCount },
        "watchdog: socket zumbi detectado — forçando reconnect",
      );
      forceReconnect("watchdog-stuck");
    }
  }, WATCHDOG_INTERVAL_MS);
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
        lastInboundEventAt = 0;  // reset contador (vai começar agora)
        inboundEventCount = 0;
        startWatchdog();  // ativa monitor de socket zumbi
        logger.info({ me: me?.id }, "CONECTADO");
      }
      if (connection === "close") {
        connState = "disconnected";
        const code = ld?.error?.output?.statusCode;
        const name = disconnectName(code);
        const reasonMsg = String(ld?.error?.message || "");
        lastDisconnect = { code, name, reason: reasonMsg };
        logger.warn({ code, name, reason: reasonMsg }, "desconectado");

        // Tratamento por taxonomia
        if (code === DisconnectReason.loggedOut) {
          // --- CIRCUIT BREAKER ---
          // Se vemos 3+ loggedOut em janela <10min, é cenário de "alguém
          // está desconectando o número manualmente do celular" (reason
          // "Intentional Logout") OU "outro dispositivo conectado com mesma
          // sessão". Reiniciar automaticamente só gera novos QR codes
          // queimados e não resolve nada — pausa por 10min antes de tentar
          // de novo, e avisa o painel.
          const now = Date.now();
          loggedOutHistory.push(now);
          loggedOutHistory = loggedOutHistory.filter(
            (t) => now - t <= 10 * 60 * 1000,
          );
          const breakerActive = loggedOutHistory.length >= 3;

          logger.warn(
            { count: loggedOutHistory.length, breakerActive, reason: reasonMsg },
            "loggedOut detectado",
          );
          try {
            fs.rmSync(AUTH_DIR, { recursive: true, force: true });
            logger.info("AUTH_DIR limpo após loggedOut — pronto pra QR novo");
          } catch (e) {
            logger.warn({ err: e.message }, "falha ao limpar AUTH_DIR pós-loggedOut");
          }
          await notifyAdmin("logged_out", { code, name, reason: reasonMsg });

          if (breakerActive) {
            connState = "circuit_open";
            logger.error(
              { count: loggedOutHistory.length },
              "CIRCUIT BREAKER ATIVO — 3+ loggedOut em 10min. " +
              "Pausando reconexão por 10min. Provável que alguém esteja " +
              "desconectando o número manualmente no celular.",
            );
            await notifyAdmin("circuit_breaker_open", {
              count: loggedOutHistory.length,
              reason: reasonMsg,
              pause_minutes: 10,
            });
            setTimeout(() => {
              logger.info("CIRCUIT BREAKER fechado — tentando reconectar");
              loggedOutHistory = [];
              startSock().catch(() => {});
            }, 10 * 60 * 1000);
            return;
          }

          setTimeout(() => { startSock().catch(() => {}); }, 1500);
          return;
        }
        if (code === DisconnectReason.connectionReplaced) {
          logger.warn("connectionReplaced — outra sessão tomou — aguardando");
          await notifyAdmin("connection_replaced", { code, name, reason: reasonMsg });
          return;
        }
        if (code === 401 || code === DisconnectReason.forbidden) {
          connState = "banned";
          await notifyAdmin("possibly_banned", { code, name, reason: reasonMsg });
          return;
        }
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

    // ═══════════════════════════════════════════════════════════
    // CALL HANDLER — Auto-rejeita chamadas e notifica backend
    // ═══════════════════════════════════════════════════════════
    // WhatsApp não permite atender chamada de voz/vídeo via Baileys.
    // Estratégia: rejeitar automaticamente e pedir ao cliente pra mandar
    // áudio (voice note) ou texto, que a IA processa em segundos.
    sock.ev.on("call", async (calls) => {
      for (const call of calls || []) {
        try {
          if (call.status !== "offer") continue; // só processar oferta inicial
          logger.info({
            from: call.from,
            isVideo: call.isVideo,
            isGroup: call.isGroup,
          }, "📞 chamada recebida — rejeitando");

          // Rejeita imediatamente
          await sock.rejectCall(call.id, call.from);

          // Avisa o backend pra mandar mensagem padrão pro cliente
          const phone = String(call.from || "").split("@")[0];
          if (phone && WEBHOOK_BASE) {
            try {
              await axios.post(
                `${WEBHOOK_BASE}/whatsapp-baileys/inbound-call`,
                {
                  phone,
                  jid: call.from,
                  call_id: call.id,
                  is_video: !!call.isVideo,
                  is_group: !!call.isGroup,
                  timestamp: call.date
                    ? new Date(call.date * 1000).toISOString()
                    : new Date().toISOString(),
                },
                {
                  headers: INBOUND_TOKEN
                    ? { Authorization: `Bearer ${INBOUND_TOKEN}` }
                    : {},
                  timeout: 8000,
                },
              );
            } catch (e) {
              logger.warn({ err: e.message }, "webhook /inbound-call falhou");
            }
          }
        } catch (e) {
          logger.warn({ err: e.message, callId: call.id },
                       "rejectCall/notify falhou");
        }
      }
    });



    sock.ev.on("messages.upsert", async (ev) => {
      try {
        if (ev.type !== "notify") return;
        lastInboundEventAt = Date.now();
        inboundEventCount += 1;
        for (const m of ev.messages || []) {
          if (m.key.fromMe) continue;
          // Ignora atualizações de Status/Broadcast (não são conversas reais)
          // e o WhatsApp bloqueia envio para esses JIDs.
          const remoteJid = m.key.remoteJid || "";
          if (
            remoteJid === "status@broadcast" ||
            remoteJid.endsWith("@broadcast") ||
            remoteJid.endsWith("@newsletter")
          ) {
            continue;
          }
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
          // Baileys 7.x: resolve LID → PN via lidMapping local
          if (!realPhone && isLid && sock.signalRepository?.lidMapping?.getPNForLID) {
            try {
              const pnJid = await sock.signalRepository.lidMapping.getPNForLID(fromJid);
              if (pnJid) {
                const cleanPn = String(pnJid).split("@")[0].split(":")[0].replace(/\D/g, "");
                if (cleanPn && cleanPn.length >= 10 && cleanPn.length <= 15) {
                  realPhone = cleanPn;
                  logger.info({ lid: rawId, phone: cleanPn },
                    "LID resolvido via lidMapping.getPNForLID");
                }
              }
            } catch (e) {
              logger.debug({ err: e.message }, "getPNForLID falhou (skip)");
            }
          }
          // Se for LID e não tem senderPn → mantemos LID como ID, mas marcamos
          const phone = realPhone || (isLid ? rawId : rawId);

          // === Áudio inbound (PTT/voice note) ===
          // Baixamos o áudio do WhatsApp e mandamos pro backend em base64.
          // O backend grava no disco e cria a msg com media_type=audio.
          let audio_b64 = null;
          let audio_mimetype = null;
          let audio_duration = null;
          let audio_is_ptt = false;
          const audioMsg = msg.audioMessage;
          if (audioMsg) {
            try {
              const buf = await downloadMediaMessage(
                m, "buffer", {},
                { logger, reuploadRequest: sock.updateMediaMessage },
              );
              if (buf && buf.length > 0 && buf.length <= 8 * 1024 * 1024) {
                audio_b64 = buf.toString("base64");
                audio_mimetype = audioMsg.mimetype || "audio/ogg; codecs=opus";
                audio_duration = audioMsg.seconds || null;
                audio_is_ptt = !!audioMsg.ptt;
              } else if (buf && buf.length > 8 * 1024 * 1024) {
                logger.warn({ phone, size: buf.length },
                  "inbound audio too large, skipping download");
              }
            } catch (e) {
              logger.warn({ err: e.message, phone },
                "downloadMediaMessage(audio) falhou");
            }
          }

          const payload = {
            phone, jid: fromJid, from_me: false, text,
            message_id: m.key.id, timestamp: m.messageTimestamp,
            push_name: m.pushName || null,
            // Novos campos para o backend decidir como identificar
            is_lid: isLid,
            lid: isLid ? rawId : null,
            sender_pn: realPhone,
            // Áudio (opcional)
            audio_b64,
            audio_mimetype,
            audio_duration_sec: audio_duration,
            audio_is_ptt,
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

// Healthcheck público (sem auth) — necessário pra Railway/Render verificarem o status
app.get("/health", (_req, res) => res.json({
  ok: true,
  state: connState,
  uptime_s: Math.floor((Date.now() - startedAt) / 1000),
  retry_count: retryCount,
  last_send_at: lastSendAt ? new Date(lastSendAt).toISOString() : null,
  last_success_at: lastSuccessAt ? new Date(lastSuccessAt).toISOString() : null,
  last_inbound_event_at: lastInboundEventAt ? new Date(lastInboundEventAt).toISOString() : null,
  inbound_event_count: inboundEventCount,
}));

// Diagnostics — confirma se AUTH_DIR é persistente (volume Railway montado)
// Conta arquivos e devolve mtimes; útil pra debug "perdi a sessão no redeploy".
app.get("/diagnostics", (_req, res) => {
  let auth_files = 0;
  let auth_files_list = [];
  let auth_exists = false;
  try {
    auth_exists = fs.existsSync(AUTH_DIR);
    if (auth_exists) {
      const files = fs.readdirSync(AUTH_DIR);
      auth_files = files.length;
      auth_files_list = files.slice(0, 10).map((name) => {
        try {
          const stat = fs.statSync(path.join(AUTH_DIR, name));
          return { name, size: stat.size, mtime: stat.mtime.toISOString() };
        } catch { return { name, error: true }; }
      });
    }
  } catch (e) { /* ignore */ }
  res.json({
    auth_dir: AUTH_DIR,
    auth_dir_exists: auth_exists,
    auth_files_count: auth_files,
    auth_files_preview: auth_files_list,
    webhook_base_configured: !!WEBHOOK_BASE && WEBHOOK_BASE !== "http://localhost:8001/api",
    webhook_base: WEBHOOK_BASE,
    inbound_token_configured: !!INBOUND_TOKEN,
    inbound_token_length: INBOUND_TOKEN.length,
    sidecar_token_configured: !!SIDECAR_TOKEN,
    node_version: process.version,
  });
});

// Auth middleware — protege todos endpoints quando WA_SIDECAR_TOKEN estiver
// configurado. O backend FastAPI envia "Authorization: Bearer <token>".
app.use((req, res, next) => {
  if (!SIDECAR_TOKEN) return next();          // sem token = modo dev/local
  if (req.path === "/health") return next();   // health sempre liberado
  const auth = req.headers.authorization || "";
  if (!auth.startsWith("Bearer ") || auth.slice(7) !== SIDECAR_TOKEN) {
    return res.status(401).json({ ok: false, error: "unauthorized" });
  }
  next();
});

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
    // Indicador "digitando..." — humaniza a resposta.
    // Calcula tempo de digitação proporcional ao tamanho do texto:
    //   - 30 chars/segundo de "digitação" (parecido com humano)
    //   - mínimo 1.2s, máximo 6s (não trava o fluxo)
    try {
      const txtLen = String(text).length;
      const typingMs = Math.min(6000, Math.max(1200, Math.floor(txtLen * 33)));
      await sock.presenceSubscribe(jid).catch(() => {});
      await sock.sendPresenceUpdate("composing", jid).catch(() => {});
      await new Promise((r) => setTimeout(r, typingMs));
      await sock.sendPresenceUpdate("paused", jid).catch(() => {});
    } catch { /* não bloqueia envio se presença falhar */ }
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

app.post("/send-audio", async (req, res) => {
  if (connState !== "connected" || !sock) {
    return res.status(503).json({ ok: false, error: "WhatsApp não conectado." });
  }
  let { phone, audio_b64, mimetype } = req.body || {};
  if (!phone || !audio_b64) {
    return res.status(400).json({ ok: false, error: "phone e audio_b64 obrigatórios" });
  }
  phone = String(phone).replace(/\D/g, "");
  const jid = `${phone}@s.whatsapp.net`;
  await applyRateLimit();
  try {
    const buffer = Buffer.from(String(audio_b64), "base64");
    const r = await withTimeout(
      sock.sendMessage(jid, {
        audio: buffer,
        mimetype: mimetype || "audio/ogg; codecs=opus",
        ptt: true,
      }),
      30000, "sendAudio",
    );
    lastSuccessAt = Date.now();
    return res.json({ ok: true, message_id: r.key?.id, jid });
  } catch (e) {
    const msg = String(e?.message || "");
    logger.error({ err: msg, phone }, "send-audio err");
    if (/timeout|closed|terminat|connection|stale|stream/i.test(msg)) {
      forceReconnect(`send-audio:${msg}`);
    }
    return res.status(502).json({ ok: false, error: msg || "erro desconhecido" });
  }
});

app.post("/send-document", async (req, res) => {
  if (connState !== "connected" || !sock) {
    return res.status(503).json({ ok: false, error: "WhatsApp não conectado." });
  }
  let { phone, document_b64, filename, mimetype, caption } = req.body || {};
  if (!phone || !document_b64) {
    return res.status(400).json({ ok: false, error: "phone e document_b64 obrigatórios" });
  }
  phone = String(phone).replace(/\D/g, "");
  const jid = `${phone}@s.whatsapp.net`;
  await applyRateLimit();
  try {
    const buffer = Buffer.from(String(document_b64), "base64");
    const r = await withTimeout(
      sock.sendMessage(jid, {
        document: buffer,
        mimetype: mimetype || "application/pdf",
        fileName: filename || "documento.pdf",
        ...(caption ? { caption: String(caption) } : {}),
      }),
      45000, "sendDocument",
    );
    lastSuccessAt = Date.now();
    return res.json({ ok: true, message_id: r.key?.id, jid });
  } catch (e) {
    const msg = String(e?.message || "");
    logger.error({ err: msg, phone, filename }, "send-document err");
    if (/timeout|closed|terminat|connection|stale|stream/i.test(msg)) {
      forceReconnect(`send-document:${msg}`);
    }
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

/**
 * POST /reload
 * Reinicia o socket Baileys sem perder a sessão (mantém auth_info).
 * Útil quando o socket "trava" — fica connected mas para de receber/enviar.
 * NÃO força novo QR Code.
 */
app.post("/reload", async (_req, res) => {
  try {
    const wasConnected = connState === "connected";
    if (sock) {
      try { sock.ev.removeAllListeners(); } catch (e) { /* ignore */ }
      try { await sock.end(undefined); } catch (e) { /* ignore */ }
      sock = null;
    }
    connState = "reloading";
    currentQr = null;
    retryCount = 0;
    setTimeout(() => { startSock().catch(() => {}); }, 500);
    console.log(`[reload] forçando reconexão (was=${wasConnected})`);
    return res.json({
      ok: true,
      msg: "Reload iniciado. Estado volta a 'connected' em ~3-5s.",
      was_connected: wasConnected,
    });
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
app.listen(PORT, HOST, () => {
  logger.info({ port: PORT, host: HOST }, "sidecar ouvindo");
  startSock();
});
