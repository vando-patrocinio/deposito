/* FleetGpsWizard — Wizard plug-and-play pra colocar um GPS pra funcionar.
 *
 * iter233 — pedido: "ja deixe tudo pronto para apenas colocar as
 * informações e ver ele conectado, simples assim".
 *
 * Fluxo (3 telas):
 *   1) Dados do veículo: placa, marca/modelo, IMEI, motorista
 *   2) Operadora do chip + modelo do rastreador (auto-preenche APN
 *      + comandos de SMS específicos do modelo)
 *   3) Tela final: SMS pronto pra copiar/enviar + polling em tempo real
 *      "Aguardando 1º ping..." → "✓ Conectado!" quando o GPS aparece.
 */
import React, { useEffect, useRef, useState } from "react";
import { api } from "@/api";

const TRACKER_MODELS = [
  {
    id: "GT06", label: "GT06 / Concox / JimiIoT",
    sms_template: (p) => [
      `APN,${p.apn}#`,
      `SERVER,1,${p.host},${p.port},0#`,
      `TIMER,${p.interval_s},${p.interval_s}#`,
    ].join("\n"),
  },
  {
    id: "TK103", label: "TK103 / Coban / Genérico chinês",
    sms_template: (p) => [
      `apn${p.password} ${p.apn}`,
      `adminip${p.password} ${p.host} ${p.port}`,
      `gprs${p.password}`,
      `t030s***n${p.password}`,
    ].join("\n"),
  },
  {
    id: "H02", label: "H02 / Suntech",
    sms_template: (p) => [
      `APN=${p.apn}`,
      `SVR=${p.host}:${p.port}`,
      `RPT=${p.interval_s}`,
    ].join("\n"),
  },
  {
    id: "Queclink", label: "Queclink GV / Meitrack",
    sms_template: (p) => [
      `AT+GTBSI=${p.password},${p.apn},,,,,,FFFF$`,
      `AT+GTSRI=${p.password},3,,2,${p.host},${p.port},0.0.0.0,0,0,0,1,1,,,,,FFFF$`,
      `AT+GTFRI=${p.password},1,0,,,00,00,00,00,0,${p.interval_s * 10},0,0,0,0,,,FFFF$`,
    ].join("\n"),
  },
];

const CARRIERS = [
  { id: "vivo",  label: "Vivo",  apn: "zap.vivo.com.br" },
  { id: "tim",   label: "TIM",   apn: "tim.br" },
  { id: "claro", label: "Claro", apn: "claro.com.br" },
  { id: "oi",    label: "Oi",    apn: "gprs.oi.com.br" },
  { id: "algar", label: "Algar", apn: "algar.com.br" },
  { id: "iot",   label: "Chip IoT (genérico)", apn: "iot.datora.com.br" },
];

export default function FleetGpsWizard({ initial, onClose, onSaved }) {
  const [step, setStep] = useState(1);
  const [savedId, setSavedId] = useState(initial?.id || null);
  const [gateway, setGateway] = useState({ host: "...", port: 5023 });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [vehicle, setVehicle] = useState({
    placa: initial?.placa || "",
    imei: initial?.imei || "",
    marca: initial?.marca || "",
    modelo: initial?.modelo || "",
    cor: initial?.cor || "",
    ano: initial?.ano || "",
    sim_phone: initial?.sim_phone || "",
    driver_collaborator_id: initial?.driver_collaborator_id || "",
    tracker_model: initial?.tracker_model || "GT06",
    tracker_password: initial?.tracker_password || "123456",
    speed_limit_kmh: initial?.speed_limit_kmh || 80,
    active: initial?.active ?? true,
  });
  const [carrier, setCarrier] = useState("vivo");
  const [interval_s, setIntervalS] = useState(30);
  const [collabs, setCollabs] = useState([]);
  const [connectStatus, setConnectStatus] = useState(null);

  // Carrega gateway-info + colaboradores
  useEffect(() => {
    api._client.get("/fleet-tracking/gateway-info")
      .then((r) => setGateway(r.data))
      .catch(() => {});
    api.listCollaborators?.()
      .then((cs) => setCollabs(cs || []))
      .catch(() => {});
  }, []);

  // Polling do step 3 — checa a cada 4s
  const pollRef = useRef(null);
  useEffect(() => {
    if (step !== 3 || !savedId) return;
    const check = async () => {
      try {
        const r = await api._client.get(
          `/fleet-tracking/vehicles/${savedId}/last-ping`);
        setConnectStatus(r.data);
        if (r.data.connected) clearInterval(pollRef.current);
      } catch { /* */ }
    };
    check();
    pollRef.current = setInterval(check, 4000);
    return () => clearInterval(pollRef.current);
  }, [step, savedId]);

  const set = (k, v) => setVehicle((f) => ({ ...f, [k]: v }));

  const saveAndAdvance = async () => {
    if (!vehicle.placa || !vehicle.imei) {
      setErr("Placa e IMEI são obrigatórios.");
      return;
    }
    setBusy(true); setErr("");
    try {
      const body = { ...vehicle,
        ano: vehicle.ano ? Number(vehicle.ano) : null,
        speed_limit_kmh: Number(vehicle.speed_limit_kmh) || 80,
        driver_collaborator_id: vehicle.driver_collaborator_id || null,
      };
      let id = savedId;
      if (id) {
        await api._client.put(`/fleet-tracking/vehicles/${id}`, body);
      } else {
        const r = await api._client.post("/fleet-tracking/vehicles", body);
        id = r.data.id;
        setSavedId(id);
      }
      setStep((s) => s + 1);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  };

  const tracker = TRACKER_MODELS.find((t) => t.id === vehicle.tracker_model)
                   || TRACKER_MODELS[0];
  const apn = CARRIERS.find((c) => c.id === carrier)?.apn || "internet";
  const smsText = tracker.sms_template({
    apn, host: gateway.host, port: gateway.port,
    interval_s, password: vehicle.tracker_password || "123456",
  });

  return (
    <div onClick={onClose} data-testid="fleet-gps-wizard-backdrop"
        style={{
          position: "fixed", inset: 0, zIndex: 999,
          background: "rgba(15,23,42,.65)",
          backdropFilter: "blur(6px)",
          display: "flex", alignItems: "center", justifyContent: "center",
          padding: 16,
        }}>
      <div onClick={(e) => e.stopPropagation()}
          data-testid="fleet-gps-wizard"
          style={{
            background: "white", borderRadius: 22, padding: 0,
            width: "100%", maxWidth: 560, maxHeight: "92vh",
            overflow: "hidden", display: "flex", flexDirection: "column",
            boxShadow: "0 24px 60px rgba(0,0,0,.35)",
          }}>
        {/* Header */}
        <div style={{
          padding: "18px 22px", borderBottom: "1px solid #E5E7EB",
          background: "linear-gradient(135deg, #7c3aed, #4C1D95)",
          color: "white",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "center" }}>
            <div>
              <div style={{ fontSize: 11, fontWeight: 800, opacity: .8,
                              letterSpacing: 2, textTransform: "uppercase" }}>
                Conectar GPS · Passo {step} de 3
              </div>
              <h2 style={{ margin: "4px 0 0", fontSize: 20, fontWeight: 900 }}>
                {step === 1 && "Dados do veículo"}
                {step === 2 && "Operadora & rastreador"}
                {step === 3 && "Configurar & conectar"}
              </h2>
            </div>
            <button onClick={onClose} aria-label="Fechar"
              data-testid="fleet-gps-wizard-close"
              style={{
                width: 32, height: 32, borderRadius: "50%",
                background: "rgba(255,255,255,.18)",
                border: "1px solid rgba(255,255,255,.3)",
                color: "white", cursor: "pointer", fontSize: 16,
              }}>×</button>
          </div>
          {/* Progress bar */}
          <div style={{ marginTop: 12, height: 4, borderRadius: 999,
                          background: "rgba(255,255,255,.18)" }}>
            <div style={{ width: `${(step / 3) * 100}%`, height: "100%",
                            background: "#FF8A3B", borderRadius: 999,
                            transition: "width .4s" }} />
          </div>
        </div>

        {/* Corpo scrollável */}
        <div style={{ flex: 1, overflowY: "auto", padding: 22 }}>
          {step === 1 && (
            <Step1 vehicle={vehicle} set={set} collabs={collabs} />
          )}
          {step === 2 && (
            <Step2 vehicle={vehicle} set={set}
              carrier={carrier} setCarrier={setCarrier}
              interval_s={interval_s} setIntervalS={setIntervalS} />
          )}
          {step === 3 && (
            <Step3 vehicle={vehicle} gateway={gateway}
              smsText={smsText} carrier={carrier}
              connectStatus={connectStatus} />
          )}
          {err && (
            <div data-testid="fleet-wizard-error" style={{
              marginTop: 14, padding: "10px 14px", borderRadius: 10,
              background: "#FEE2E2", border: "1px solid #FCA5A5",
              color: "#991B1B", fontSize: 13, fontWeight: 600,
            }}>{err}</div>
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: "14px 22px", borderTop: "1px solid #E5E7EB",
          display: "flex", justifyContent: "space-between", gap: 10,
          background: "#FAFAF9",
        }}>
          <button type="button" data-testid="fleet-wizard-back"
            onClick={() => step > 1 ? setStep(step - 1) : onClose()}
            style={btnGhost()}>{step === 1 ? "Cancelar" : "← Voltar"}</button>
          {step < 3 && (
            <button type="button" data-testid="fleet-wizard-next"
              onClick={() => step === 2 ? saveAndAdvance() : setStep(step + 1)}
              disabled={busy}
              style={btnPrimary()}>
              {busy ? "Salvando..." : (step === 2 ? "Salvar e continuar →" : "Continuar →")}
            </button>
          )}
          {step === 3 && (
            <button type="button" data-testid="fleet-wizard-finish"
              onClick={() => { onSaved?.(); onClose(); }}
              style={btnPrimary()}>
              {connectStatus?.connected ? "Concluído ✓" : "Fechar"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Step 1 ── */
function Step1({ vehicle, set, collabs }) {
  return (
    <div style={{ display: "grid", gap: 12 }}>
      <Field label="Placa do veículo *" placeholder="ABC1D23"
        testid="wiz-placa" value={vehicle.placa}
        onChange={(v) => set("placa", v.toUpperCase())} />
      <Field label="IMEI do rastreador *" placeholder="864283120000000"
        testid="wiz-imei" value={vehicle.imei}
        onChange={(v) => set("imei", v.replace(/\D/g, ""))} />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                       gap: 10 }}>
        <Field label="Marca" value={vehicle.marca}
          testid="wiz-marca" onChange={(v) => set("marca", v)} />
        <Field label="Modelo" value={vehicle.modelo}
          testid="wiz-modelo" onChange={(v) => set("modelo", v)} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                       gap: 10 }}>
        <Field label="Cor" value={vehicle.cor}
          testid="wiz-cor" onChange={(v) => set("cor", v)} />
        <Field label="Ano" type="number" value={vehicle.ano}
          testid="wiz-ano" onChange={(v) => set("ano", v)} />
      </div>
      <div>
        <label style={lbl()}>Motorista (opcional)</label>
        <select className="fwz-input" data-testid="wiz-driver"
            value={vehicle.driver_collaborator_id || ""}
            onChange={(e) => set("driver_collaborator_id", e.target.value)}
            style={inputStyle()}>
          <option value="">— Não vincular —</option>
          {collabs.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </div>
    </div>
  );
}

/* ── Step 2 ── */
function Step2({ vehicle, set, carrier, setCarrier, interval_s, setIntervalS }) {
  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div>
        <label style={lbl()}>Operadora do chip do GPS</label>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr",
                         gap: 6 }}>
          {CARRIERS.map((c) => (
            <button key={c.id} type="button"
              data-testid={`wiz-carrier-${c.id}`}
              onClick={() => setCarrier(c.id)}
              style={{
                padding: "10px", borderRadius: 10,
                border: carrier === c.id
                  ? "2px solid #7c3aed" : "1px solid #E5E7EB",
                background: carrier === c.id ? "#EDE9FE" : "white",
                color: carrier === c.id ? "#5b21b6" : "#1E1B4B",
                fontSize: 12.5, fontWeight: 700, cursor: "pointer",
              }}>{c.label}</button>
          ))}
        </div>
        <p style={{ margin: "8px 0 0", fontSize: 11.5, color: "#6B7280" }}>
          APN será: <code style={{ color: "#7c3aed" }}>
            {CARRIERS.find((c) => c.id === carrier)?.apn}
          </code>
        </p>
      </div>

      <div>
        <label style={lbl()}>Modelo do rastreador</label>
        <div style={{ display: "grid", gap: 6 }}>
          {TRACKER_MODELS.map((t) => (
            <button key={t.id} type="button"
              data-testid={`wiz-tracker-${t.id}`}
              onClick={() => set("tracker_model", t.id)}
              style={{
                padding: "10px 14px", borderRadius: 10, textAlign: "left",
                border: vehicle.tracker_model === t.id
                  ? "2px solid #7c3aed" : "1px solid #E5E7EB",
                background: vehicle.tracker_model === t.id ? "#EDE9FE" : "white",
                color: vehicle.tracker_model === t.id ? "#5b21b6" : "#1E1B4B",
                fontSize: 13, fontWeight: 700, cursor: "pointer",
              }}>{t.label}</button>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                       gap: 10 }}>
        <Field label="Telefone do chip (opcional)" placeholder="(11) 99999-0000"
          testid="wiz-sim-phone" value={vehicle.sim_phone}
          onChange={(v) => set("sim_phone", v)} />
        <Field label="Senha do rastreador" value={vehicle.tracker_password}
          testid="wiz-tracker-password"
          onChange={(v) => set("tracker_password", v)} />
      </div>

      <div>
        <label style={lbl()}>Intervalo entre pings (segundos)</label>
        <div style={{ display: "flex", gap: 6 }}>
          {[15, 30, 60, 120].map((v) => (
            <button key={v} type="button"
              data-testid={`wiz-interval-${v}`}
              onClick={() => setIntervalS(v)}
              style={{
                flex: 1, padding: "8px", borderRadius: 8,
                border: interval_s === v
                  ? "2px solid #7c3aed" : "1px solid #E5E7EB",
                background: interval_s === v ? "#EDE9FE" : "white",
                color: interval_s === v ? "#5b21b6" : "#1E1B4B",
                fontSize: 12, fontWeight: 800, cursor: "pointer",
              }}>{v}s</button>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                       gap: 10 }}>
        <Field label="Limite de velocidade (km/h)" type="number"
          testid="wiz-speed-limit"
          value={vehicle.speed_limit_kmh}
          onChange={(v) => set("speed_limit_kmh", v)} />
      </div>
    </div>
  );
}

/* ── Step 3 ── */
function Step3({ vehicle, gateway, smsText, carrier, connectStatus }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(smsText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2200);
    } catch { /* */ }
  };
  const smsLink = vehicle.sim_phone
    ? `sms:${vehicle.sim_phone.replace(/\D/g, "")}?body=${encodeURIComponent(smsText)}`
    : null;
  const isOrphan = !connectStatus?.connected
    && (connectStatus?.orphan_pings_same_imei || 0) > 0;
  return (
    <div style={{ display: "grid", gap: 16 }}>
      {/* Resumo */}
      <div style={{ padding: 12, borderRadius: 12,
                       background: "#F4F1FF", border: "1px solid #E0D5FF" }}>
        <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 1.4,
                         textTransform: "uppercase", color: "#7c3aed" }}>
          Resumo do equipamento
        </div>
        <div style={{ marginTop: 6, fontSize: 13, color: "#1E1B4B",
                         lineHeight: 1.6 }}>
          🚗 <b>{vehicle.placa}</b> — {vehicle.marca} {vehicle.modelo}<br/>
          📡 IMEI {vehicle.imei}<br/>
          📶 Chip {CARRIERS.find((c) => c.id === carrier)?.label}{" "}
            ({CARRIERS.find((c) => c.id === carrier)?.apn})<br/>
          🛰️ Servidor: <code>{gateway.host}:{gateway.port}</code>
        </div>
      </div>

      {/* SMS */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "center", marginBottom: 6 }}>
          <label style={lbl()}>Comandos pra enviar via SMS pro chip do GPS</label>
          <button type="button" onClick={copy}
            data-testid="wiz-copy-sms"
            style={{
              padding: "5px 12px", borderRadius: 999,
              background: copied ? "#10b981" : "#7c3aed",
              color: "white", border: "none", fontSize: 11,
              fontWeight: 800, cursor: "pointer",
            }}>{copied ? "✓ Copiado!" : "📋 Copiar"}</button>
        </div>
        <pre data-testid="wiz-sms-text" style={{
          background: "#0F172A", color: "#FCD34D", padding: 14,
          borderRadius: 12, fontSize: 12.5, fontWeight: 700,
          overflowX: "auto", lineHeight: 1.6, margin: 0,
          fontFamily: "ui-monospace, 'SF Mono', Menlo, monospace",
          whiteSpace: "pre-wrap",
        }}>{smsText}</pre>

        {smsLink && (
          <a href={smsLink} data-testid="wiz-send-sms-link"
            style={{
              display: "block", marginTop: 8, textAlign: "center",
              padding: "12px", borderRadius: 12,
              background: "#10b981", color: "white",
              fontWeight: 900, fontSize: 13.5, textDecoration: "none",
            }}>📨 Abrir SMS pronto pro {vehicle.sim_phone}</a>
        )}

        <p style={{ margin: "10px 0 0", fontSize: 11.5, color: "#6B7280",
                       lineHeight: 1.5 }}>
          Envie pelo seu celular pessoal pro chip que está dentro do GPS.
          Em modelos GT06/H02/Queclink basta enviar tudo num único SMS,
          ou copie linha-a-linha. Depois ligue o veículo e aguarde 1-2 min.
        </p>
      </div>

      {/* Status de conexão */}
      <ConnectionStatus connectStatus={connectStatus} isOrphan={isOrphan} />
    </div>
  );
}

function ConnectionStatus({ connectStatus, isOrphan }) {
  const connected = !!connectStatus?.connected;
  if (connected) {
    const p = connectStatus.last_position;
    return (
      <div data-testid="wiz-connected" style={{
        padding: 16, borderRadius: 14,
        background: "linear-gradient(135deg, #10b981, #047857)",
        color: "white", textAlign: "center",
      }}>
        <div style={{ fontSize: 32 }}>✓</div>
        <div style={{ fontSize: 16, fontWeight: 900, marginTop: 4 }}>
          GPS conectado!
        </div>
        <div style={{ fontSize: 12, opacity: .9, marginTop: 6 }}>
          Última posição: {p?.lat?.toFixed(5)}, {p?.lng?.toFixed(5)}<br/>
          {p?.speed_kmh?.toFixed(0)} km/h ·{" "}
          {p?.ignition === true ? "ignição ligada"
            : p?.ignition === false ? "parado" : "—"}
        </div>
      </div>
    );
  }
  if (isOrphan) {
    return (
      <div data-testid="wiz-orphan-warning" style={{
        padding: 14, borderRadius: 12,
        background: "#FFFBEB", border: "1px solid #FBBF24",
        color: "#92400E", fontSize: 13, fontWeight: 600, lineHeight: 1.5,
      }}>
        ⚠ Detectamos pings desse IMEI, mas há <b>{connectStatus.orphan_pings_same_imei}</b>{" "}
        registros órfãos. Verifique se o IMEI está digitado corretamente.
      </div>
    );
  }
  return (
    <div data-testid="wiz-waiting" style={{
      padding: 16, borderRadius: 12,
      background: "#F0F9FF", border: "1px dashed #93C5FD",
      color: "#1E40AF", fontSize: 13, fontWeight: 600,
      lineHeight: 1.5, textAlign: "center",
    }}>
      <div style={{ display: "inline-block",
                       animation: "pulse 1.4s ease-in-out infinite",
                       fontSize: 28 }}>📡</div>
      <div style={{ marginTop: 6 }}>Aguardando 1º ping do GPS...</div>
      <div style={{ fontSize: 11, color: "#64748B", marginTop: 4 }}>
        Após enviar o SMS, ligue o veículo. Pode levar 1-2 minutos.
      </div>
      <style>{`@keyframes pulse {
        0%, 100% { opacity: 1; transform: scale(1); }
        50% { opacity: .4; transform: scale(.85); }
      }`}</style>
    </div>
  );
}

/* ── Helpers ── */
function Field({ label, value, onChange, type = "text",
  placeholder = "", testid }) {
  return (
    <div>
      <label style={lbl()}>{label}</label>
      <input className="fwz-input" type={type} value={value || ""}
        placeholder={placeholder} data-testid={testid}
        onChange={(e) => onChange(e.target.value)}
        style={inputStyle()} />
    </div>
  );
}
function lbl() {
  return {
    display: "block", fontSize: 11, fontWeight: 800, letterSpacing: 1.4,
    textTransform: "uppercase", color: "#6B7280", marginBottom: 6,
  };
}
function inputStyle() {
  return {
    width: "100%", padding: "11px 14px", borderRadius: 10,
    border: "1px solid #E5E7EB", background: "white",
    fontSize: 14, color: "#1E1B4B", fontFamily: "inherit",
    outline: "none", boxSizing: "border-box",
  };
}
function btnPrimary() {
  return {
    padding: "12px 22px", borderRadius: 12,
    background: "#7c3aed", color: "white",
    border: "none", cursor: "pointer", fontWeight: 800, fontSize: 13.5,
  };
}
function btnGhost() {
  return {
    padding: "12px 18px", borderRadius: 12,
    background: "white", color: "#1E1B4B",
    border: "1px solid #D1D5DB", cursor: "pointer",
    fontWeight: 700, fontSize: 13,
  };
}
