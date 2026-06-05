/*
 * FleetEmergencyBlockModal.js — Modal de bloqueio de emergência em sinistro.
 *
 * Fluxo de segurança (anti-acidente):
 *  1. Lista TODOS os veículos rastreados
 *  2. Operador seleciona o veículo
 *  3. Mostra última posição + dados do veículo em destaque
 *  4. Exige DIGITAR a placa para confirmar (proteção contra clique acidental)
 *  5. Campo opcional "Motivo / Nº B.O." (auditoria)
 *  6. Envia comando `block` (RELAY,1<senha>#) para o gateway
 *  7. Mostra confirmação e instrui operador
 *  8. Botão "🔓 Liberar veículo" disponível depois (caso falso alarme)
 */
import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";

export default function FleetEmergencyBlockModal({ vehicles, onClose,
                                                    onActionDone }) {
  const [vid, setVid] = useState("");
  const [placaConfirm, setPlacaConfirm] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [sent, setSent] = useState(null);   // {cmd_id, kind, vehicle}

  const veh = useMemo(
    () => vehicles.find((v) => v.id === vid),
    [vehicles, vid],
  );

  const canSend = veh && placaConfirm.trim().toUpperCase() === veh.placa
    .toUpperCase() && !busy;

  const send = async (kind) => {
    if (!veh) return;
    if (kind === "block" && placaConfirm.trim().toUpperCase()
        !== veh.placa.toUpperCase()) {
      setErr("Digite a placa exatamente como mostrada para confirmar");
      return;
    }
    setBusy(true); setErr("");
    try {
      const r = await api._client.post(
        `/fleet-tracking/vehicles/${veh.id}/command`,
        { kind, payload: { reason: reason || undefined } },
      ).then((x) => x.data);
      setSent({ cmd_id: r.id, kind, vehicle: veh });
      onActionDone?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  };

  // Status do comando
  const [cmdStatus, setCmdStatus] = useState(null);
  useEffect(() => {
    if (!sent) return undefined;
    const id = setInterval(async () => {
      try {
        const list = await api._client.get(
          `/fleet-tracking/vehicles/${sent.vehicle.id}/commands`,
        ).then((x) => x.data);
        const c = list.find((x) => x.id === sent.cmd_id);
        if (c) setCmdStatus(c.status);
      } catch { /* */ }
    }, 3000);
    return () => clearInterval(id);
  }, [sent]);

  return (
    <div style={overlay} data-testid="fleet-emergency-modal">
      <div style={{ ...modal, borderTop: "6px solid #dc2626" }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "flex-start", marginBottom: 8 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 20, color: "#991b1b" }}>
              🚨 Bloqueio de Emergência
            </h2>
            <p style={{ margin: "4px 0 0", fontSize: 12,
                          color: "#64748b" }}>
              Use em caso de <b>sinistro, roubo ou furto</b>. O comando vai
              ao rastreador na próxima conexão TCP (geralmente &lt; 1 min).
            </p>
          </div>
          <button onClick={onClose} style={closeBtn}>✕</button>
        </div>

        {!sent && (
          <>
            <label style={lbl}>
              Veículo a bloquear
              <select value={vid}
                       onChange={(e) => {
                         setVid(e.target.value);
                         setPlacaConfirm("");
                         setErr("");
                       }}
                       style={inp}
                       data-testid="fleet-emergency-vid">
                <option value="">— escolha o veículo —</option>
                {vehicles.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.placa} {v.modelo ? `· ${v.modelo}` : ""}
                    {v.online ? " · 🟢 online" : " · ⚪ offline"}
                  </option>
                ))}
              </select>
            </label>

            {veh && (
              <div style={infoBox}>
                <div style={{ display: "grid",
                                gridTemplateColumns: "1fr 1fr 1fr",
                                gap: 12, fontSize: 13 }}>
                  <div>
                    <div style={infoLbl}>Placa</div>
                    <div style={{ fontWeight: 700, fontSize: 18 }}>
                      {veh.placa}
                    </div>
                  </div>
                  <div>
                    <div style={infoLbl}>Modelo</div>
                    <div>{veh.modelo || "—"} · {veh.cor || "?"}</div>
                  </div>
                  <div>
                    <div style={infoLbl}>Status</div>
                    <div style={{ fontWeight: 700 }}>
                      {veh.online ? "🟢 ONLINE" : "⚪ OFFLINE (cmd fila)"}
                    </div>
                  </div>
                </div>
                {veh.lat && (
                  <div style={{ marginTop: 8, fontSize: 12,
                                  color: "#475569" }}>
                    📍 Última posição: {veh.lat.toFixed(5)},{" "}
                    {veh.lng.toFixed(5)}
                    {" · "}
                    <a target="_blank" rel="noreferrer"
                        href={`https://www.google.com/maps?q=${veh.lat},${veh.lng}`}
                        style={{ color: "#1d4ed8" }}>
                      Abrir no Google Maps ↗
                    </a>
                    <br />
                    {veh.ts && (
                      <span>🕒 Última atualização:{" "}
                        {new Date(veh.ts).toLocaleString("pt-BR")}</span>
                    )}
                    {" · "}
                    🔑 Ignição:{" "}
                    {veh.ignition === true ? "ligada"
                      : veh.ignition === false ? "desligada" : "?"}
                    {" · "}
                    🚗 {(veh.speed_kmh || 0).toFixed(0)} km/h
                  </div>
                )}
              </div>
            )}

            {veh && (
              <>
                <label style={lbl}>
                  Para confirmar, digite a placa <code style={mono}>
                    {veh.placa}
                  </code> exatamente:
                  <input value={placaConfirm}
                          onChange={(e) =>
                            setPlacaConfirm(e.target.value.toUpperCase())}
                          placeholder={veh.placa}
                          style={{ ...inp, fontFamily: "monospace",
                                     fontSize: 16, letterSpacing: 2,
                                     fontWeight: 700,
                                     borderColor: canSend
                                       ? "#16a34a" : "#cbd5e1" }}
                          data-testid="fleet-emergency-confirm-placa"
                          autoComplete="off" />
                </label>
                <label style={lbl}>
                  Motivo (opcional — auditoria)
                  <input value={reason}
                          onChange={(e) => setReason(e.target.value)}
                          placeholder="Ex: B.O. 0001234/2026, ocorrência roubo"
                          style={inp}
                          data-testid="fleet-emergency-reason" />
                </label>
              </>
            )}

            {err && <div style={errBox}>{err}</div>}

            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end",
                            marginTop: 12 }}>
              <button onClick={onClose} disabled={busy} style={secBtn}>
                Cancelar
              </button>
              <button onClick={() => send("block")}
                       disabled={!canSend}
                       style={{ ...dangerBtn,
                                 opacity: canSend ? 1 : 0.4,
                                 cursor: canSend ? "pointer" : "not-allowed" }}
                       data-testid="fleet-emergency-block-confirm">
                {busy ? "Enviando…" : "🔒 BLOQUEAR AGORA"}
              </button>
            </div>
          </>
        )}

        {sent && (
          <div data-testid="fleet-emergency-sent">
            <div style={{ background: sent.kind === "block"
              ? "#fef3c7" : "#dcfce7",
              padding: 14, borderRadius: 8,
              border: `2px solid ${sent.kind === "block"
                ? "#f59e0b" : "#16a34a"}` }}>
              <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 4 }}>
                {sent.kind === "block"
                  ? "🔒 Comando de BLOQUEIO enfileirado"
                  : "🔓 Comando de LIBERAÇÃO enfileirado"}
              </div>
              <div style={{ fontSize: 13 }}>
                Veículo <b>{sent.vehicle.placa}</b> ·
                Comando #<code>{sent.cmd_id}</code>
              </div>
              <div style={{ marginTop: 8, fontSize: 12, color: "#475569" }}>
                Status:{" "}
                <b style={{
                  color: cmdStatus === "ack" ? "#16a34a"
                    : cmdStatus === "failed" ? "#dc2626" : "#f59e0b",
                }}>
                  {cmdStatus === "pending" && "⏳ pending (aguardando o tracker conectar)"}
                  {cmdStatus === "ack" && "✅ ACK — tracker confirmou execução"}
                  {cmdStatus === "failed" && "❌ falhou — tente novamente"}
                  {!cmdStatus && "⏳ pending"}
                </b>
              </div>
              <div style={{ marginTop: 12, padding: 10, background: "white",
                              borderRadius: 6, fontSize: 12,
                              color: "#475569" }}>
                <b>📋 Como funciona:</b>
                <ol style={{ margin: "4px 0 0 18px", padding: 0 }}>
                  <li>Comando fica na fila do backend</li>
                  <li>Gateway TCP (na VPS) puxa a cada 60s</li>
                  <li>Gateway envia <code style={mono}>
                    {sent.kind === "block" ? "RELAY,1<senha>#"
                      : "RELAY,0<senha>#"}
                  </code> via TCP ao rastreador</li>
                  <li>Rastreador aciona/libera o relé (corta/restitui partida)</li>
                  <li>Status muda pra "ack" automaticamente</li>
                </ol>
              </div>
            </div>

            <div style={{ display: "flex", gap: 8,
                            justifyContent: "space-between",
                            marginTop: 12 }}>
              {sent.kind === "block" ? (
                <button onClick={() => {
                  setSent(null);
                  setCmdStatus(null);
                  send("unblock");
                }}
                         disabled={busy}
                         style={{ ...secBtn, color: "#16a34a",
                                    borderColor: "#16a34a" }}
                         data-testid="fleet-emergency-unblock">
                  🔓 Liberar veículo (desfazer)
                </button>
              ) : <div />}
              <button onClick={onClose} style={primaryBtn}>
                Fechar
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const overlay = { position: "fixed", inset: 0,
                    background: "rgba(0,0,0,.5)", display: "flex",
                    alignItems: "center", justifyContent: "center",
                    zIndex: 1100, padding: 16 };
const modal = { background: "white", borderRadius: 12, padding: 20,
                 maxWidth: 600, width: "100%", maxHeight: "92vh",
                 overflow: "auto",
                 boxShadow: "0 20px 60px rgba(0,0,0,.4)" };
const closeBtn = { background: "transparent", border: 0, fontSize: 20,
                    cursor: "pointer", color: "#94a3b8" };
const lbl = { display: "block", fontSize: 12, color: "#475569",
               marginBottom: 12, fontWeight: 600 };
const inp = { width: "100%", padding: "8px 12px", borderRadius: 6,
                border: "1px solid #cbd5e1", fontSize: 13,
                marginTop: 4, boxSizing: "border-box" };
const infoBox = { background: "#f8fafc", border: "1px solid #e2e8f0",
                    padding: 12, borderRadius: 8, marginBottom: 12 };
const infoLbl = { fontSize: 10, color: "#94a3b8", textTransform: "uppercase",
                    fontWeight: 700, letterSpacing: 0.5 };
const mono = { background: "#0f172a", color: "#fff", padding: "2px 6px",
                 borderRadius: 4, fontFamily: "monospace" };
const primaryBtn = { padding: "8px 16px", background: "#0f172a",
                      color: "white", border: 0, borderRadius: 6,
                      fontWeight: 700, fontSize: 13, cursor: "pointer" };
const secBtn = { ...primaryBtn, background: "white", color: "#475569",
                  border: "1px solid #cbd5e1", fontWeight: 600 };
const dangerBtn = { ...primaryBtn, background: "#dc2626",
                     padding: "10px 20px", fontSize: 14 };
const errBox = { padding: 10, background: "#fee2e2", color: "#991b1b",
                  borderRadius: 6, fontSize: 12, marginTop: 8 };
