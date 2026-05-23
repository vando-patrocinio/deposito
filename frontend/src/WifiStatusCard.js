import { useEffect, useState } from "react";
import { api } from "./api";

/**
 * WifiStatusCard — status bar de conexão/ONU do assinante.
 *
 * 3 estados visuais:
 *  - "ready"             → status + ações (Trocar Wi-Fi, Reboot)
 *  - "premium_required"  → upsell call-to-action
 *  - "no_onu"            → botão "Vincular ONU"
 *  - "onu_offline"       → status sem ações
 *  - "rate_limited"      → mensagem "limite atingido"
 *
 * Props:
 *   subscriberId      — ID do assinante
 *   subscriberName    — nome (pra modal)
 *   canManage         — bool (atendente vê ações, cliente não)
 *   onOfferUpgrade    — callback opcional pro botão de upsell
 */
export default function WifiStatusCard({
  subscriberId, subscriberName, canManage = true, onOfferUpgrade,
}) {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [showChange, setShowChange] = useState(false);
  const [showLogs, setShowLogs] = useState(false);

  const refresh = async () => {
    if (!subscriberId) return;
    try {
      const r = await api.wifiStatus(subscriberId);
      setStatus(r);
    } catch {
      setStatus({ state: "no_onu" });
    }
  };

  useEffect(() => { refresh(); /* eslint-disable-line */ }, [subscriberId]);

  const autoMatch = async () => {
    setBusy(true);
    try {
      const r = await api.wifiAutoMatch(subscriberId);
      if (r.ok) {
        await refresh();
      } else {
        await window.alert(
          "Sem match automático. Tente vincular manualmente.\n" +
          `Candidatos testados: ${(r.tried_candidates || []).join(", ") || "(nenhum)"}`
        );
      }
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  const unlink = async () => {
    if (!await window.confirm("Desvincular ONU deste assinante?")) return;
    setBusy(true);
    try { await api.wifiUnlinkOnu(subscriberId); await refresh(); }
    catch (e) { await window.alert("Erro: " + e.message); }
    finally { setBusy(false); }
  };

  const reboot = async () => {
    if (!await window.confirm("Reiniciar a ONU agora? Cliente vai ficar sem internet ~30s.")) return;
    setBusy(true);
    try {
      await api.wifiRebootOnu(subscriberId);
      await window.alert("Reboot enviado.");
      setTimeout(refresh, 35000);
    } catch (e) {
      await window.alert("Erro: " + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };

  if (!status) {
    return (
      <div data-testid="wifi-status-loading" className="surface"
           style={{ padding: 14, marginBottom: 14, borderRadius: 12,
                    fontSize: 13, color: "#64748b" }}>
        Carregando status da conexão…
      </div>
    );
  }

  return (
    <>
      <div data-testid="wifi-status-card"
           className="surface"
           style={{ padding: 14, marginBottom: 14, borderRadius: 12,
                    border: "1px solid #e2e8f0",
                    background: stateBg(status.state) }}>
        <StatusBar status={status}
                    onTrocarWifi={() => setShowChange(true)}
                    onRebootOnu={reboot}
                    onAutoMatch={autoMatch}
                    onUnlink={unlink}
                    onShowLogs={() => setShowLogs(true)}
                    onOfferUpgrade={onOfferUpgrade}
                    canManage={canManage}
                    busy={busy} />
      </div>
      {showChange && (
        <WifiChangeModal
          subscriberId={subscriberId}
          subscriberName={subscriberName}
          currentSsid24={status.onu?.wifi_ssid_24}
          currentSsid5={status.onu?.wifi_ssid_5}
          onClose={() => { setShowChange(false); refresh(); }} />
      )}
      {showLogs && (
        <WifiLogsModal
          subscriberId={subscriberId}
          subscriberName={subscriberName}
          onClose={() => setShowLogs(false)} />
      )}
    </>
  );
}

function stateBg(state) {
  switch (state) {
    case "ready":            return "linear-gradient(135deg,#ecfdf5,#f0fdf4)";
    case "premium_required": return "linear-gradient(135deg,#fef3c7,#fffbeb)";
    case "onu_offline":      return "linear-gradient(135deg,#fef2f2,#fff5f5)";
    case "rate_limited":     return "linear-gradient(135deg,#fef3c7,#fef9c3)";
    default:                  return "#f8fafc";
  }
}

function StatusBar({
  status, onTrocarWifi, onRebootOnu, onAutoMatch, onUnlink, onShowLogs,
  onOfferUpgrade, canManage, busy,
}) {
  const { state, onu, plan_premium, recent_changes_24h, rate_limit_max } = status;

  // Pill de status
  const pillColor = onu?.is_online ? "#15803d" :
                     onu?.status ? "#dc2626" : "#94a3b8";
  const pillText  = onu?.is_online ? "🟢 Online" :
                     onu?.status   ? `❌ ${onu.status}` : "📡 Sem ONU";

  if (state === "no_onu") {
    return (
      <div data-testid="wifi-state-no_onu">
        <div style={{ fontSize: 13, color: "#64748b", marginBottom: 8 }}>
          📡 <b>Sem ONU SmartOLT vinculada.</b> Para liberar diagnóstico de
          sinal, reboot e troca de Wi-Fi self-service, vincule uma ONU.
        </div>
        {canManage && (
          <div style={{ display: "flex", gap: 8 }}>
            <button data-testid="wifi-auto-match-btn" className="btn btn-primary"
                    disabled={busy} onClick={onAutoMatch} style={{ fontSize: 13 }}>
              {busy ? "Buscando..." : "🔍 Tentar auto-vinculação"}
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div data-testid={`wifi-state-${state}`}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10,
                     alignItems: "center", fontSize: 13 }}>
        <span style={{ background: pillColor, color: "#fff",
                        padding: "2px 9px", borderRadius: 999,
                        fontSize: 11, fontWeight: 700 }}>
          {pillText}
        </span>
        {onu?.model && (
          <span title="Modelo da ONU"
                style={{ color: "#475569" }}>📟 {onu.model}</span>
        )}
        {onu?.rx_dbm != null && (
          <span title="Sinal óptico RX"
                style={{ color: rxColor(onu.rx_dbm), fontFamily: "monospace" }}>
            RX {onu.rx_dbm.toFixed(2)} dBm
          </span>
        )}
        {onu?.olt && (
          <span style={{ color: "#94a3b8", fontSize: 11 }}>
            OLT: {onu.olt}
          </span>
        )}
        {plan_premium && (
          <span data-testid="premium-badge"
                style={{ background: "#fbbf24", color: "#92400e",
                          padding: "2px 8px", borderRadius: 999,
                          fontWeight: 700, fontSize: 10 }}>
            ⭐ PREMIUM
          </span>
        )}
      </div>

      {state === "premium_required" && (
        <div style={{ marginTop: 10, padding: 10, background: "#fef9c3",
                       border: "1px solid #fde047", borderRadius: 8,
                       fontSize: 12, color: "#713f12" }}>
          💎 <b>Troca de Wi-Fi self-service: disponível no Plano Premium.</b>{" "}
          Faça upgrade pra liberar troca via WhatsApp e atendente.
          {canManage && onOfferUpgrade && (
            <button data-testid="wifi-offer-upgrade-btn"
                    className="btn btn-primary"
                    onClick={onOfferUpgrade}
                    style={{ marginLeft: 10, fontSize: 12 }}>
              Oferecer upgrade
            </button>
          )}
        </div>
      )}

      {state === "onu_offline" && (
        <div style={{ marginTop: 10, padding: 10, background: "#fef2f2",
                       border: "1px solid #fecaca", borderRadius: 8,
                       fontSize: 12, color: "#7f1d1d" }}>
          ❌ ONU offline ({onu.status}). Troca de Wi-Fi indisponível até
          a ONU voltar online.
        </div>
      )}

      {state === "rate_limited" && (
        <div style={{ marginTop: 10, padding: 10, background: "#fef9c3",
                       border: "1px solid #fde047", borderRadius: 8,
                       fontSize: 12, color: "#713f12" }}>
          ⏱️ Limite de {rate_limit_max} troca(s)/24h atingido
          ({recent_changes_24h} troca(s) recente(s)). Atendente humano
          pode forçar.
        </div>
      )}

      {canManage && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6,
                       marginTop: 10 }}>
          {state === "ready" && (
            <button data-testid="wifi-change-btn" className="btn btn-primary"
                    onClick={onTrocarWifi} style={{ fontSize: 12 }}>
              📡 Trocar Wi-Fi
            </button>
          )}
          {(state === "ready" || state === "rate_limited") && (
            <button data-testid="wifi-change-force-btn"
                    className="btn btn-secondary"
                    onClick={onTrocarWifi} style={{ fontSize: 12 }}
                    title="Forçar troca pelo atendente (ignora rate limit)">
              📡 Trocar Wi-Fi (Force)
            </button>
          )}
          {onu?.external_id && (
            <button data-testid="wifi-reboot-btn"
                    className="btn btn-secondary"
                    disabled={busy} onClick={onRebootOnu}
                    style={{ fontSize: 12 }}>
              🔁 Reboot ONU
            </button>
          )}
          <button data-testid="wifi-logs-btn"
                  className="btn btn-secondary"
                  onClick={onShowLogs} style={{ fontSize: 12 }}>
            📜 Logs
          </button>
          {onu?.external_id && (
            <button data-testid="wifi-unlink-btn"
                    className="btn btn-ghost"
                    disabled={busy} onClick={onUnlink}
                    style={{ fontSize: 12, color: "#dc2626" }}>
              Desvincular ONU
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function rxColor(rx) {
  if (rx > -25) return "#15803d";
  if (rx > -28) return "#ca8a04";
  return "#dc2626";
}

// ---------------------------------------------------------------------------
// Modal: trocar Wi-Fi
// ---------------------------------------------------------------------------
function WifiChangeModal({ subscriberId, subscriberName, currentSsid24,
                            currentSsid5, onClose }) {
  const [ssid24, setSsid24] = useState(currentSsid24 || "");
  const [pwd24, setPwd24]   = useState("");
  const [ssid5, setSsid5]   = useState(currentSsid5 || "");
  const [pwd5, setPwd5]     = useState("");
  const [applyBoth, setApplyBoth] = useState(true);
  const [force, setForce]   = useState(false);
  const [busy, setBusy]     = useState(false);
  const [err, setErr]       = useState(null);

  const submit = async () => {
    setErr(null);
    if (!ssid24 && !pwd24 && !ssid5 && !pwd5) {
      setErr("Informe ao menos um campo."); return;
    }
    if (pwd24 && pwd24.length < 8) {
      setErr("Senha 2.4GHz deve ter no mínimo 8 caracteres."); return;
    }
    if (pwd5 && pwd5.length < 8) {
      setErr("Senha 5GHz deve ter no mínimo 8 caracteres."); return;
    }
    setBusy(true);
    try {
      const payload = {
        apply_to_both: applyBoth, force, source: "atendente",
        ssid_24: ssid24 || null, password_24: pwd24 || null,
        ssid_5:  applyBoth ? null : (ssid5 || null),
        password_5: applyBoth ? null : (pwd5 || null),
      };
      await api.wifiChange(subscriberId, payload);
      await window.alert(
        "✅ Wi-Fi atualizado. Roteador do cliente vai reiniciar em ~30s."
      );
      onClose();
    } catch (e) {
      const det = e?.response?.data?.detail;
      const msg = typeof det === "string" ? det : (det?.message || e.message);
      setErr(msg);
    } finally { setBusy(false); }
  };

  return (
    <div data-testid="wifi-change-modal"
         style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.5)",
                   display: "flex", alignItems: "center",
                   justifyContent: "center", zIndex: 9999 }}>
      <div style={{ background: "#fff", padding: 22, borderRadius: 14,
                     width: 480, maxWidth: "95vw",
                     boxShadow: "0 20px 50px rgba(0,0,0,.25)" }}>
        <h3 style={{ margin: "0 0 4px", fontSize: 17, fontWeight: 700 }}>
          📡 Trocar Wi-Fi
        </h3>
        <p style={{ margin: "0 0 16px", color: "#64748b", fontSize: 12 }}>
          {subscriberName} · O roteador vai reiniciar em ~30s após salvar.
        </p>
        <label style={{ display: "block", marginBottom: 12 }}>
          <input type="checkbox" checked={applyBoth}
                 onChange={(e) => setApplyBoth(e.target.checked)}
                 data-testid="wifi-apply-both" />
          {" "}Aplicar a mesma config nas duas frequências (2.4 + 5 GHz)
        </label>
        <Section title={applyBoth ? "Wi-Fi (2.4 + 5 GHz)" : "Wi-Fi 2.4 GHz"}>
          <input className="input" placeholder="SSID (nome da rede)"
                 maxLength={32}
                 value={ssid24} onChange={(e) => setSsid24(e.target.value)}
                 data-testid="wifi-ssid-24" />
          <input className="input" type="password"
                 placeholder="Nova senha (deixe vazio pra manter)"
                 maxLength={63}
                 value={pwd24} onChange={(e) => setPwd24(e.target.value)}
                 data-testid="wifi-pwd-24" />
        </Section>
        {!applyBoth && (
          <Section title="Wi-Fi 5 GHz">
            <input className="input" placeholder="SSID 5GHz"
                   maxLength={32}
                   value={ssid5} onChange={(e) => setSsid5(e.target.value)}
                   data-testid="wifi-ssid-5" />
            <input className="input" type="password"
                   placeholder="Senha 5GHz"
                   maxLength={63}
                   value={pwd5} onChange={(e) => setPwd5(e.target.value)}
                   data-testid="wifi-pwd-5" />
          </Section>
        )}
        <label style={{ display: "block", marginTop: 8, fontSize: 12,
                         color: "#dc2626" }}>
          <input type="checkbox" checked={force}
                 onChange={(e) => setForce(e.target.checked)}
                 data-testid="wifi-force" />
          {" "}Forçar mesmo com rate-limit (atendente humano)
        </label>
        {err && (
          <div data-testid="wifi-change-error"
               style={{ marginTop: 12, padding: 8, background: "#fef2f2",
                         border: "1px solid #fecaca", borderRadius: 6,
                         fontSize: 12, color: "#7f1d1d" }}>
            ⚠️ {err}
          </div>
        )}
        <div style={{ display: "flex", gap: 8, marginTop: 16,
                       justifyContent: "flex-end" }}>
          <button className="btn btn-secondary" onClick={onClose}
                  data-testid="wifi-change-cancel">Cancelar</button>
          <button className="btn btn-primary" onClick={submit} disabled={busy}
                  data-testid="wifi-change-submit">
            {busy ? "Enviando ao SmartOLT..." : "Aplicar"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4,
                     fontWeight: 600, textTransform: "uppercase",
                     letterSpacing: 0.5 }}>{title}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {children}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Modal: histórico de mudanças
// ---------------------------------------------------------------------------
function WifiLogsModal({ subscriberId, subscriberName, onClose }) {
  const [logs, setLogs] = useState(null);
  useEffect(() => {
    api.wifiLogs(subscriberId).then((r) => setLogs(r.items || []))
                                .catch(() => setLogs([]));
  }, [subscriberId]);
  return (
    <div data-testid="wifi-logs-modal"
         style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.5)",
                   display: "flex", alignItems: "center",
                   justifyContent: "center", zIndex: 9999 }}>
      <div style={{ background: "#fff", padding: 22, borderRadius: 14,
                     width: 700, maxWidth: "95vw", maxHeight: "85vh",
                     overflow: "auto",
                     boxShadow: "0 20px 50px rgba(0,0,0,.25)" }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>
            📜 Histórico Wi-Fi · {subscriberName}
          </h3>
          <button className="btn btn-ghost" onClick={onClose}
                  data-testid="wifi-logs-close">×</button>
        </div>
        {logs === null ? <div>Carregando…</div>
         : logs.length === 0 ? <div style={{ color: "#94a3b8" }}>
             Sem mudanças registradas ainda.</div>
         : (
          <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
                <th style={cell}>Data/hora</th>
                <th style={cell}>Por</th>
                <th style={cell}>Fonte</th>
                <th style={cell}>SSID antes → depois</th>
                <th style={cell}>Status</th>
                <th style={cell}>TR-069</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id} data-testid={`wifi-log-${l.id}`}>
                  <td style={cell}>{(l.ts || "").replace("T", " ").slice(0, 19)}</td>
                  <td style={cell}>{l.actor_name || l.actor_email || "—"}</td>
                  <td style={cell}>{l.source}</td>
                  <td style={cell}>
                    {l.ssid_before?.["24"] || "—"} → <b>{l.ssid_after?.["24"] || "—"}</b>
                  </td>
                  <td style={cell}>
                    {l.success
                      ? <span style={{ color: "#15803d" }}>✓ ok</span>
                      : <span style={{ color: "#dc2626" }} title={l.error_reason}>✗ falha</span>}
                  </td>
                  <td style={cell}>{l.tr069_response_time_ms || "—"}ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

const cell = { padding: "6px 8px", borderBottom: "1px solid #e2e8f0" };
