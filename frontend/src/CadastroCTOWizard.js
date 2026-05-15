/* =============================================================
   CadastroCTOWizard — Fluxo 8 passos seguindo o storyboard:
   1. Detecção  → 2. Endereço  → 3. Identificação automática  →
   4. Capacidade  →  5. Tipo rede  →  6. Splitter (se desbal.)  →
   7. Porta cliente  →  8. Resumo + Enviar p/ validação
   Usado pelo CollaboratorApp (PWA do técnico).
============================================================= */
import React, { useState, useEffect, useCallback, useMemo } from "react";
import { api } from "@/api";

// Paleta inline coerente com o app do colaborador (roxo/laranja do storyboard)
const C_BG = "#ffffff";
const C_HEADER_BG = "#5b21b6"; // roxo SmartProv
const C_PRIMARY = "#7c3aed";
const C_PRIMARY_LIGHT = "#ede9fe";
const C_ACCENT = "#f97316";
const C_TEXT = "#0f172a";
const C_MUTED = "#64748b";
const C_BORDER = "#e2e8f0";
const C_SUCCESS = "#16a34a";
const C_DANGER = "#dc2626";

const headerStyle = {
  background: C_HEADER_BG,
  color: "#fff",
  padding: "14px 16px",
  display: "flex", alignItems: "center", justifyContent: "space-between",
  fontWeight: 700, fontSize: 15,
};

const stepBadge = {
  display: "inline-flex", alignItems: "center", justifyContent: "center",
  width: 24, height: 24, borderRadius: "50%",
  background: "rgba(255,255,255,0.2)", color: "#fff",
  fontSize: 12, fontWeight: 800, marginRight: 8,
};

const inputBase = {
  width: "100%", padding: "12px 14px", borderRadius: 12,
  border: `1.5px solid ${C_BORDER}`, fontSize: 15, color: C_TEXT,
  background: "#fff", outline: "none", boxSizing: "border-box",
  fontFamily: "inherit",
};

const labelStyle = {
  fontSize: 12, fontWeight: 600, color: C_TEXT,
  marginBottom: 6, marginTop: 12, display: "block",
};

const primaryBtn = {
  width: "100%", padding: "14px 20px", borderRadius: 12,
  background: C_HEADER_BG, color: "#fff", border: 0,
  fontWeight: 700, fontSize: 15, cursor: "pointer",
};
const secondaryBtn = {
  ...primaryBtn,
  background: "#fff", color: C_TEXT,
  border: `1.5px solid ${C_BORDER}`,
};
const accentBtn = {
  ...primaryBtn,
  background: C_ACCENT,
};

const optionCard = (selected) => ({
  padding: "16px 14px", borderRadius: 14,
  border: `2px solid ${selected ? C_PRIMARY : C_BORDER}`,
  background: selected ? C_PRIMARY_LIGHT : "#fff",
  cursor: "pointer", textAlign: "left",
  display: "flex", alignItems: "center", justifyContent: "space-between",
  fontSize: 14, fontWeight: 600, color: C_TEXT,
});

export default function CadastroCTOWizard({ onClose, onCreated, technician }) {
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Estado do formulário
  const [address, setAddress] = useState({
    rua: "", numero: "", bairro: "", cidade: "", estado: "", referencia: "",
  });
  const [gps, setGps] = useState({ lat: null, lng: null, accuracy: null });
  const [bairroSelected, setBairroSelected] = useState(null); // {bairro,sigla,vlan,cidade,estado}
  const [bairrosOptions, setBairrosOptions] = useState([]);
  const [ctoNumber, setCtoNumber] = useState(null);
  const [suggestedName, setSuggestedName] = useState("");
  const [capacity, setCapacity] = useState(null);
  const [networkType, setNetworkType] = useState(null);
  const [splitter, setSplitter] = useState(null);
  const [clientPort, setClientPort] = useState(null);

  // ===== Step 2: GPS capture =====
  const captureGps = useCallback(() => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setError("GPS indisponível no dispositivo.");
      return;
    }
    setError("");
    navigator.geolocation.getCurrentPosition(
      (pos) => setGps({
        lat: pos.coords.latitude,
        lng: pos.coords.longitude,
        accuracy: pos.coords.accuracy,
      }),
      (err) => setError(`Falha GPS: ${err.message}`),
      { enableHighAccuracy: true, timeout: 12000 },
    );
  }, []);

  // ===== Step 3: load all bairros for selection =====
  useEffect(() => {
    if (step === 3) {
      api.redeIaBairros().then((r) => {
        setBairrosOptions(r.items || []);
      }).catch(() => setBairrosOptions([]));
    }
  }, [step]);

  // ===== Suggest CTO name once bairro + number known =====
  const refreshSuggestion = useCallback(async (sigla, vlan, number) => {
    try {
      const r = await api.redeIaSuggestName(sigla, vlan, number ?? undefined);
      setSuggestedName(r.suggested_name);
      if (r.exists) {
        setCtoNumber(r.suggested_number);
        setError(`O número ${number} já existe. Sugerido: ${r.suggested_number}.`);
      } else {
        setError("");
        if (number == null) setCtoNumber(r.suggested_number);
      }
    } catch (e) {
      setError("Falha ao consultar nomenclatura");
    }
  }, []);

  // ===== Submit final =====
  const submit = async () => {
    setBusy(true); setError("");
    try {
      const payload = {
        rua: address.rua, numero: address.numero,
        bairro: bairroSelected.bairro, cidade: bairroSelected.cidade || address.cidade,
        estado: bairroSelected.estado || address.estado,
        referencia: address.referencia,
        lat: gps.lat, lng: gps.lng,
        capacity, network_type: networkType,
        splitter: networkType === "desbalanceada" ? splitter : null,
        client_port: clientPort,
        sigla: bairroSelected.sigla,
        vlan: bairroSelected.vlan,
        suggested_name: suggestedName,
        technician_id: technician?.id || null,
        technician_name: technician?.name || "",
      };
      const r = await api.redeIaCtoCreate(payload);
      onCreated?.(r);
    } catch (e) {
      const d = e?.response?.data?.detail;
      if (typeof d === "object" && d?.suggested_name) {
        setError(`${d.msg}. Sugerido: ${d.suggested_name}`);
        setSuggestedName(d.suggested_name);
        setCtoNumber(d.suggested_number);
        setStep(3);
      } else {
        setError(typeof d === "string" ? d : "Falha ao criar CTO.");
      }
    } finally {
      setBusy(false);
    }
  };

  // ===== UI Steps =====
  const totalSteps = networkType === "desbalanceada" ? 8 : 7;
  const stepLabels = useMemo(() => [
    "Início",                  // 1
    "Endereço",                // 2
    "Identificação",           // 3
    "Capacidade",              // 4
    "Tipo de rede",            // 5
    networkType === "desbalanceada" ? "Splitter" : "Porta", // 6
    networkType === "desbalanceada" ? "Porta" : "Resumo",   // 7
    "Resumo",                  // 8
  ], [networkType]);

  return (
    <div data-testid="cto-wizard" style={{
      position: "fixed", inset: 0, background: C_BG, zIndex: 9999,
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      {/* HEADER */}
      <div style={headerStyle}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <button data-testid="cto-back-btn" onClick={() => (step > 1 ? setStep(step - 1) : onClose?.())}
                  style={{ background: "transparent", border: 0, color: "#fff",
                            fontSize: 22, marginRight: 6, cursor: "pointer", padding: 4 }}>
            ←
          </button>
          <span style={stepBadge}>{step}</span>
          <span>Cadastro de CTO</span>
        </div>
        <span style={{ fontSize: 11, opacity: 0.85 }}>{stepLabels[step - 1]}</span>
      </div>

      {/* CONTENT */}
      <div style={{
        flex: 1, overflowY: "auto", padding: 18, fontSize: 14, color: C_TEXT,
        background: "#f8fafc",
      }}>
        {error && (
          <div data-testid="cto-error" style={{
            background: "#fef2f2", color: C_DANGER, borderRadius: 10,
            padding: "10px 14px", marginBottom: 12, fontSize: 13,
            border: "1px solid #fecaca",
          }}>{error}</div>
        )}

        {/* === STEP 1: detecção === */}
        {step === 1 && (
          <div style={{ textAlign: "center", padding: "20px 10px" }}>
            <div style={{
              width: 96, height: 96, margin: "0 auto 16px",
              borderRadius: "50%", background: "#fed7aa",
              display: "grid", placeItems: "center", fontSize: 44, color: C_ACCENT,
            }}>⚠️</div>
            <div style={{ fontSize: 20, fontWeight: 800, marginBottom: 8 }}>
              Cliente não identificado em CTO
            </div>
            <p style={{ color: C_MUTED, fontSize: 13, lineHeight: 1.5, marginBottom: 24 }}>
              Este cliente não está vinculado a nenhuma CTO existente. Cadastre uma nova CTO neste
              endereço para continuar o atendimento.
            </p>
            <button data-testid="cto-start-btn" style={accentBtn} onClick={() => setStep(2)}>
              Cadastrar CTO
            </button>
          </div>
        )}

        {/* === STEP 2: endereço === */}
        {step === 2 && (
          <div>
            <div style={{ fontSize: 17, fontWeight: 800, marginBottom: 4 }}>
              Informe o endereço em frente à casa onde está a CTO
            </div>
            <p style={{ color: C_MUTED, fontSize: 12, marginBottom: 14 }}>
              Esses dados ajudam a rede_IA a identificar bairro, VLAN e sigla automaticamente.
            </p>

            <label style={labelStyle}>Rua</label>
            <input data-testid="cto-rua" style={inputBase} value={address.rua}
              onChange={(e) => setAddress({ ...address, rua: e.target.value })}
              placeholder="Rua das Flores" />

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div>
                <label style={labelStyle}>Número</label>
                <input data-testid="cto-numero" style={inputBase} value={address.numero}
                  onChange={(e) => setAddress({ ...address, numero: e.target.value })}
                  placeholder="125" />
              </div>
              <div>
                <label style={labelStyle}>UF</label>
                <input style={inputBase} value={address.estado}
                  maxLength={2}
                  onChange={(e) => setAddress({ ...address, estado: e.target.value.toUpperCase() })}
                  placeholder="RJ" />
              </div>
            </div>

            <label style={labelStyle}>Referência</label>
            <input data-testid="cto-referencia" style={inputBase} value={address.referencia}
              onChange={(e) => setAddress({ ...address, referencia: e.target.value })}
              placeholder="Casa azul com portão branco" />

            <label style={labelStyle}>Localização GPS</label>
            <button data-testid="cto-gps-btn"
                    onClick={captureGps}
                    style={{
                      ...inputBase, display: "flex", alignItems: "center",
                      justifyContent: "space-between", cursor: "pointer",
                      background: gps.lat ? C_PRIMARY_LIGHT : "#fff",
                      borderColor: gps.lat ? C_PRIMARY : C_BORDER,
                    }}>
              <span>
                {gps.lat
                  ? `📍 ${gps.lat.toFixed(6)}, ${gps.lng.toFixed(6)}`
                  : "Usar localização atual"}
              </span>
              <span style={{ color: C_MUTED }}>›</span>
            </button>

            <button data-testid="cto-step2-continue"
                    onClick={() => {
                      if (!address.rua || !address.numero) {
                        setError("Rua e número são obrigatórios.");
                        return;
                      }
                      setError("");
                      setStep(3);
                    }}
                    style={{ ...primaryBtn, marginTop: 24 }}>
              Continuar
            </button>
          </div>
        )}

        {/* === STEP 3: identificação manual do bairro/VLAN === */}
        {step === 3 && (
          <div>
            <div style={{ fontSize: 17, fontWeight: 800, marginBottom: 4 }}>
              Identifique o bairro da CTO
            </div>
            <p style={{ color: C_MUTED, fontSize: 12, marginBottom: 14 }}>
              Selecione o bairro correspondente. A sigla e a VLAN são preenchidas automaticamente
              pela rede_IA.
            </p>

            {bairrosOptions.length === 0 ? (
              <div style={{
                padding: 16, border: `1px dashed ${C_BORDER}`, borderRadius: 10,
                color: C_MUTED, fontSize: 13, textAlign: "center",
              }}>
                Nenhum bairro cadastrado. Solicite ao admin que cadastre os bairros e VLANs
                no painel "Rede IA → Bairros".
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {bairrosOptions.map((b) => (
                  <button key={b.id} data-testid={`cto-bairro-${b.sigla}`}
                          onClick={() => {
                            setBairroSelected(b);
                            // tenta sugerir nome
                            refreshSuggestion(b.sigla, b.vlan, null);
                          }}
                          style={optionCard(bairroSelected?.id === b.id)}>
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 700 }}>{b.bairro}</div>
                      <div style={{ fontSize: 11, color: C_MUTED, marginTop: 2 }}>
                        Sigla {b.sigla} · VLAN {b.vlan}
                        {b.cidade ? ` · ${b.cidade}` : ""}
                      </div>
                    </div>
                    <span>›</span>
                  </button>
                ))}
              </div>
            )}

            {bairroSelected && (
              <>
                <label style={labelStyle}>Número da CTO</label>
                <input data-testid="cto-number-input" type="number"
                  style={inputBase} value={ctoNumber || ""}
                  onChange={(e) => {
                    const n = parseInt(e.target.value, 10);
                    setCtoNumber(Number.isFinite(n) ? n : null);
                    if (Number.isFinite(n)) {
                      refreshSuggestion(bairroSelected.sigla, bairroSelected.vlan, n);
                    }
                  }}
                  placeholder="Ex: 1" />
                <div style={{
                  marginTop: 14, padding: "12px 14px",
                  background: C_PRIMARY_LIGHT, borderRadius: 10,
                  border: `1.5px solid ${C_PRIMARY}`,
                  fontSize: 13, color: C_TEXT,
                }}>
                  <div style={{ fontSize: 10, color: C_MUTED, marginBottom: 4,
                                  textTransform: "uppercase", letterSpacing: 0.5 }}>
                    Nomenclatura gerada
                  </div>
                  <div style={{ fontWeight: 800, fontSize: 16, color: C_PRIMARY }}>
                    {suggestedName || "—"}
                  </div>
                </div>
              </>
            )}

            <button data-testid="cto-step3-continue"
                    disabled={!bairroSelected || !ctoNumber}
                    onClick={() => { setError(""); setStep(4); }}
                    style={{
                      ...primaryBtn, marginTop: 24,
                      opacity: (!bairroSelected || !ctoNumber) ? 0.5 : 1,
                    }}>
              Continuar
            </button>
          </div>
        )}

        {/* === STEP 4: capacidade === */}
        {step === 4 && (
          <div>
            <div style={{ fontSize: 17, fontWeight: 800, marginBottom: 4 }}>
              Quantas portas tem essa CTO?
            </div>
            <p style={{ color: C_MUTED, fontSize: 12, marginBottom: 18 }}>
              Selecione a capacidade física.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {[4, 8, 16].map((cap) => (
                <button key={cap} data-testid={`cto-cap-${cap}`}
                        onClick={() => setCapacity(cap)}
                        style={optionCard(capacity === cap)}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ fontSize: 22 }}>▦</span>
                    <span>{cap} portas</span>
                  </div>
                  {capacity === cap && <span style={{ color: C_PRIMARY }}>✓</span>}
                </button>
              ))}
            </div>
            <button data-testid="cto-step4-continue"
                    disabled={!capacity}
                    onClick={() => setStep(5)}
                    style={{ ...primaryBtn, marginTop: 24, opacity: !capacity ? 0.5 : 1 }}>
              Continuar
            </button>
          </div>
        )}

        {/* === STEP 5: tipo de rede === */}
        {step === 5 && (
          <div>
            <div style={{ fontSize: 17, fontWeight: 800, marginBottom: 4 }}>
              Tipo de rede
            </div>
            <p style={{ color: C_MUTED, fontSize: 12, marginBottom: 18 }}>
              Selecione o tipo de rede utilizada nesta CTO.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <button data-testid="cto-net-bal"
                      onClick={() => setNetworkType("balanceada")}
                      style={{ ...optionCard(networkType === "balanceada"),
                                flexDirection: "column", alignItems: "flex-start" }}>
                <div style={{ fontSize: 14, fontWeight: 700 }}>⚖️ Rede balanceada</div>
                <div style={{ fontSize: 11, color: C_MUTED, marginTop: 4 }}>
                  Sinal distribuído de forma equilibrada entre as portas.
                </div>
              </button>
              <button data-testid="cto-net-desb"
                      onClick={() => setNetworkType("desbalanceada")}
                      style={{ ...optionCard(networkType === "desbalanceada"),
                                flexDirection: "column", alignItems: "flex-start" }}>
                <div style={{ fontSize: 14, fontWeight: 700 }}>⚙️ Rede desbalanceada</div>
                <div style={{ fontSize: 11, color: C_MUTED, marginTop: 4 }}>
                  Sinal distribuído de forma desbalanceada entre as portas.
                </div>
              </button>
            </div>
            <button data-testid="cto-step5-continue"
                    disabled={!networkType}
                    onClick={() => setStep(networkType === "desbalanceada" ? 6 : 7)}
                    style={{ ...primaryBtn, marginTop: 24, opacity: !networkType ? 0.5 : 1 }}>
              Continuar
            </button>
          </div>
        )}

        {/* === STEP 6: splitter (apenas desbalanceada) === */}
        {step === 6 && networkType === "desbalanceada" && (
          <div>
            <div style={{ fontSize: 17, fontWeight: 800, marginBottom: 4 }}>
              Qual é o splitter de balanceamento?
            </div>
            <p style={{ color: C_MUTED, fontSize: 12, marginBottom: 18 }}>
              Selecione o splitter utilizado na rede desbalanceada.
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              {["1:2", "1:4", "1:8", "Outro"].map((s) => (
                <button key={s} data-testid={`cto-splitter-${s}`}
                        onClick={() => setSplitter(s)}
                        style={{ ...optionCard(splitter === s),
                                  flexDirection: "column", alignItems: "center", padding: "16px 8px" }}>
                  <div style={{ fontSize: 22, marginBottom: 4 }}>▣</div>
                  <div>{s}</div>
                </button>
              ))}
            </div>
            <button data-testid="cto-step6-continue"
                    disabled={!splitter}
                    onClick={() => setStep(7)}
                    style={{ ...primaryBtn, marginTop: 24, opacity: !splitter ? 0.5 : 1 }}>
              Continuar
            </button>
          </div>
        )}

        {/* === STEP 7: porta do cliente === */}
        {step === 7 && (
          <div>
            <div style={{ fontSize: 17, fontWeight: 800, marginBottom: 4 }}>
              Selecione a porta usada pelo cliente
            </div>
            <p style={{ color: C_MUTED, fontSize: 12, marginBottom: 18 }}>
              Capacidade da CTO: {capacity} portas
            </p>
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(4, 1fr)",
              gap: 8,
            }}>
              {Array.from({ length: capacity || 0 }, (_, i) => i + 1).map((p) => (
                <button key={p} data-testid={`cto-port-${p}`}
                        onClick={() => setClientPort(p)}
                        style={{
                          padding: "16px 0", borderRadius: 10,
                          border: `2px solid ${clientPort === p ? C_PRIMARY : C_BORDER}`,
                          background: clientPort === p ? C_PRIMARY : "#fff",
                          color: clientPort === p ? "#fff" : C_TEXT,
                          fontSize: 16, fontWeight: 700, cursor: "pointer",
                        }}>
                  {String(p).padStart(2, "0")}
                </button>
              ))}
            </div>
            {clientPort && (
              <div style={{
                marginTop: 14, padding: "10px 12px",
                background: C_PRIMARY_LIGHT, borderRadius: 8,
                fontSize: 12, color: C_TEXT,
              }}>
                ℹ️ Porta selecionada: <b>{clientPort}</b>
              </div>
            )}
            <button data-testid="cto-step7-continue"
                    disabled={!clientPort}
                    onClick={() => setStep(8)}
                    style={{ ...primaryBtn, marginTop: 24, opacity: !clientPort ? 0.5 : 1 }}>
              Continuar
            </button>
          </div>
        )}

        {/* === STEP 8: resumo === */}
        {step === 8 && (
          <div>
            <div style={{ fontSize: 17, fontWeight: 800, marginBottom: 4 }}>
              Resumo do cadastro
            </div>
            <p style={{ color: C_MUTED, fontSize: 12, marginBottom: 14 }}>
              Confira os dados antes de salvar. A rede_IA vai gerar uma prévia do fluxograma
              e enviar para validação do gestor.
            </p>

            <SummaryRow icon="🏠" label="Endereço de referência"
              value={`${address.rua}, ${address.numero}${address.referencia ? " · " + address.referencia : ""}`} />
            <SummaryRow icon="📍" label="Bairro" value={bairroSelected?.bairro} />
            <SummaryRow icon="🛰" label="GPS"
              value={gps.lat ? `${gps.lat.toFixed(6)}, ${gps.lng.toFixed(6)}` : "Não capturado"} />
            <SummaryRow icon="🏷" label="Nomenclatura" value={suggestedName} highlight />
            <SummaryRow icon="🔢" label="Capacidade" value={`${capacity} portas`} />
            <SummaryRow icon="🔗" label="Tipo de rede" value={networkType} />
            {networkType === "desbalanceada" && (
              <SummaryRow icon="🔀" label="Splitter" value={splitter} />
            )}
            <SummaryRow icon="📥" label="Porta do cliente" value={`Porta ${clientPort}`} />

            <div style={{ display: "flex", gap: 10, marginTop: 22 }}>
              <button data-testid="cto-summary-back" style={secondaryBtn}
                      onClick={() => setStep(7)}>
                ← Voltar e editar
              </button>
              <button data-testid="cto-summary-submit" style={accentBtn}
                      disabled={busy} onClick={submit}>
                {busy ? "Enviando..." : "Enviar p/ validação"}
              </button>
            </div>
          </div>
        )}

        {/* Progress dots */}
        <div style={{
          display: "flex", justifyContent: "center", gap: 6,
          marginTop: 30,
        }}>
          {Array.from({ length: totalSteps }, (_, i) => i + 1).map((n) => (
            <span key={n} style={{
              width: 6, height: 6, borderRadius: 999,
              background: n <= step ? C_PRIMARY : "#cbd5e1",
            }} />
          ))}
        </div>
      </div>
    </div>
  );
}

function SummaryRow({ icon, label, value, highlight }) {
  return (
    <div style={{
      display: "flex", gap: 12, padding: "10px 12px",
      borderBottom: `1px solid ${C_BORDER}`,
      background: highlight ? C_PRIMARY_LIGHT : "transparent",
      borderRadius: highlight ? 8 : 0,
      marginBottom: highlight ? 6 : 0,
    }}>
      <div style={{ fontSize: 16, flexShrink: 0 }}>{icon}</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 10, color: C_MUTED, textTransform: "uppercase",
                       letterSpacing: 0.5, marginBottom: 2 }}>{label}</div>
        <div style={{ fontSize: 13, fontWeight: highlight ? 800 : 600,
                       color: highlight ? C_PRIMARY : C_TEXT }}>{value || "—"}</div>
      </div>
    </div>
  );
}
