/**
 * MongoDB Auth State para Baileys 7.x — sessão PERSISTENTE entre restarts.
 *
 * Problema resolvido:
 *   `useMultiFileAuthState` salva em filesystem local. Em containers
 *   Kubernetes / serverless / Docker sem volume mount, o /app é EFÊMERO →
 *   restart do pod = sessão perdida = QR de novo.
 *
 * Solução: persistir creds+keys em MongoDB (collection `wa_auth_state`),
 * que é durável por design.
 *
 * Documento por device (1 só pro nosso caso de Isabella):
 *   { _id: "creds"            , data: <buffer> }
 *   { _id: "key:<type>:<id>"  , data: <buffer> }
 *
 * Interface compatível com Baileys ≥6 (useMultiFileAuthState-like).
 *
 * Uso:
 *   const { state, saveCreds, clear } = await useMongoAuthState(db, "isabella");
 *   const sock = makeWASocket({ auth: state, ... });
 *   sock.ev.on("creds.update", saveCreds);
 *   // limpar tudo (ex: logout): await clear();
 */

const { initAuthCreds, BufferJSON, proto } = require("@whiskeysockets/baileys");

/**
 * @param {import('mongodb').Db} db          Mongo Db handle (connected)
 * @param {string}                 sessionId  identificador da sessão (ex: "isabella")
 * @param {object}                 opts       { collectionName, logger }
 */
async function useMongoAuthState(db, sessionId, opts = {}) {
  const colName = opts.collectionName || "wa_auth_state";
  const logger = opts.logger || console;
  const col = db.collection(colName);
  // Índice composto: sessions diferentes coexistem se quisermos multi-WhatsApp.
  await col.createIndex({ session_id: 1, key: 1 }, { unique: true });

  // Helpers serialização: Baileys usa Buffer + Long + curves; BufferJSON
  // do próprio Baileys faz round-trip seguro.
  const writeData = async (key, data) => {
    if (data === null || data === undefined) {
      await col.deleteOne({ session_id: sessionId, key });
      return;
    }
    const json = JSON.stringify(data, BufferJSON.replacer);
    await col.updateOne(
      { session_id: sessionId, key },
      { $set: { session_id: sessionId, key, value: json,
                  updated_at: new Date() } },
      { upsert: true },
    );
  };
  const readData = async (key) => {
    const doc = await col.findOne(
      { session_id: sessionId, key },
      { projection: { _id: 0, value: 1 } },
    );
    if (!doc || !doc.value) return null;
    try {
      return JSON.parse(doc.value, BufferJSON.reviver);
    } catch (e) {
      logger.warn({ key, err: e.message }, "wa-auth: JSON parse falhou");
      return null;
    }
  };
  const removeData = async (key) => {
    await col.deleteOne({ session_id: sessionId, key });
  };

  // Carrega ou inicializa creds
  let creds = await readData("creds");
  if (!creds) {
    creds = initAuthCreds();
    await writeData("creds", creds);
    logger.info({ sessionId }, "wa-auth: creds NOVAS criadas no Mongo");
  } else {
    logger.info({ sessionId }, "wa-auth: creds existentes carregadas do Mongo");
  }

  return {
    state: {
      creds,
      keys: {
        get: async (type, ids) => {
          const out = {};
          await Promise.all(
            ids.map(async (id) => {
              const v = await readData(`key:${type}:${id}`);
              if (v) {
                if (type === "app-state-sync-key") {
                  out[id] = proto.Message.AppStateSyncKeyData.fromObject(v);
                } else {
                  out[id] = v;
                }
              }
            }),
          );
          return out;
        },
        set: async (data) => {
          const tasks = [];
          for (const category in data) {
            for (const id in data[category]) {
              const value = data[category][id];
              tasks.push(writeData(`key:${category}:${id}`, value || null));
            }
          }
          await Promise.all(tasks);
        },
      },
    },
    saveCreds: async () => {
      await writeData("creds", creds);
    },
    clear: async () => {
      // Apaga TUDO dessa sessão (usado em logout)
      await col.deleteMany({ session_id: sessionId });
      logger.info({ sessionId }, "wa-auth: sessão Mongo LIMPA (logout)");
    },
  };
}

module.exports = { useMongoAuthState };
