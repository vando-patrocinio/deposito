/* =============================================================
   CadastroCTOWizard — Fluxo 8 passos (storyboard oficial):
   1. Detecção do problema
   2. Endereço de referência
   3. Identificação automática (Bairro/GPS/Nomenclatura)
   4. Quantidade de portas
   5. Tipo de rede
   6. Splitter de balanceamento (se desbalanceada)
   7. Porta do cliente
   8. Resumo e confirmação
   Layout: header roxo, cards com radius grande, botão CTA roxo,
   "Salvar cadastro" laranja no passo 8.
============================================================= */
import React, { useState, useEffect, useCallback, useMemo } from "react";
import { api } from "@/api";

// Paleta storyboard
const C_BG = "#f8fafc";
const C_HEADER_BG = "#5b21b6"; // roxo SmartProv
const C_PRIMARY = "#7c3aed";
const C_PRIMARY_LIGHT = "#ede9fe";
const C_ACCENT = "#f97316";
const C_TEXT = "#0f172a";
const C_MUTED = "#64748b";
const C_BORDER = "#e2e8f0";
const C_DANGER = "#dc2626";

const headerStyle = {
  background: C_HEADER_BG,
  color: "#fff",
  padding: "16px 14px",
  display: "flex", alignItems: "center", justifyContent: "space-between",
  fontWeight: 700, fontSize: 16,
  position: "sticky", top: 0, zIndex: 10,
};
const stepBadge = {
  display: "inline-flex", alignItems: "center", justifyContent: "center",
  width: 26, height: 26, borderRadius: "50%",
  background: "rgba(255,255,255,0.2)", color: "#fff",
  fontSize: 13, fontWeight: 800, marginRight: 10,
};
const cardBase = {
  background: "#fff",
  borderRadius: 16,
  border: `1.5px solid ${C_BORDER}`,
  padding: "16px 14px",
  marginBottom: 10,
};
const inputBase = {
  width: "100%", padding: "13px 14px", borderRadius: 12,
  border: `1.5px solid ${C_BORDER}`, fontSize: 15, color: C_TEXT,
  background: "#fff", outline: "none", boxSizing: "border-box",
  fontFamily: "inherit",
};
const labelStyle = {
  fontSize: 13, fontWeight: 600, color: C_TEXT,
  marginBottom: 6, marginTop: 14, display: "block",
};
const primaryBtn = {
  width: "100%", padding: "15px 20px", borderRadius: 14,
  background: C_HEADER_BG, color: "#fff", border: 0,
  fontWeight: 700, fontSize: 15, cursor: "pointer",
  boxShadow: "0 4px 12px rgba(91,33,182,0.3)",
};
const accentBtn = {
  ...primaryBtn,
  background: C_ACCENT,
  boxShadow: "0 4px 12px rgba(249,115,22,0.35)",
};
const optionCard = (selected) => ({
  padding: "16px 14px",
  borderRadius: 14,
  border: `2px solid ${selected ? C_PRIMARY : C_BORDER}`,
  background: selected ? C_PRIMARY_LIGHT : "#fff",
  cursor: "pointer",
  textAlign: "left",
  display: "flex", alignItems: "center", justifyContent: "space-between",
  fontSize: 14, fontWeight: 600, color: C_TEXT,
  marginBottom: 10,
  transition: "background-color .15s, border-color .15s",
});
const checkBox = (selected) => ({
  width: 22, height: 22, borderRadius: 6,
  border: `2px solid ${selected ? C_PRIMARY : "#cbd5e1"}`,
  background: selected ? C_PRIMARY : "#fff",
  color: "#fff", fontSize: 13, fontWeight: 800,
  display: "grid", placeItems: "center", flexShrink: 0,
});

export default function CadastroCTOWizard({ onClose, onCreated, technician }) {
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [address, setAddress] = useState({
    endereco: "", numero: "", referencia: "",
  });
  const [gps, setGps] = useState({ lat: null, lng: null, accuracy: null });
  const [bairros, setBairros] = useState([]);
  const [bairroSelected, setBairroSelected] = useState(null);
  const [suggested, setSuggested] = useState({ name: "", number: null });
  const [capacity, setCapacity] = useState(null);
  const [networkType, setNetworkType] = useState(null);
  const [splitter, setSplitter] = useState(null);
  const [clientPort, setClientPort] = useState(null);

  // GPS
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

  // Helper: usa endpoint público quando temos o ID do técnico (sem JWT)
  const collabId = technician?.id || null;
  const useApi = useMemo(() => ({
    bairros: () => collabId ? api.redeIaBairrosPublic(collabId) : api.redeIaBairros(),
    suggest: (sigla, vlan, num) => collabId
      ? api.redeIaSuggestNamePublic(collabId, sigla, vlan, num)
      : api.redeIaSuggestName(sigla, vlan, num),
    create: (data) => collabId
      ? api.redeIaCtoCreatePublic(collabId, data)
      : api.redeIaCtoCreate(data),
  }), [collabId]);

  // Carrega bairros ao chegar no passo 3
  useEffect(() => {
    if (step === 3) {
      useApi.bairros().then((r) => setBairros(r.items || []))
        .catch(() => setBairros([]));
    }
  }, [step, useApi]);

  // Sempre que bairro muda no passo 3 → gera nomenclatura automática
  useEffect(() => {
    if (bairroSelected) {
      useApi.suggest(bairroSelected.sigla, bairroSelected.vlan)
        .then((r) => setSuggested({
          name: r.suggested_name,
          number: r.suggested_number,
        }))
        .catch(() => setSuggested({ name: "", number: null }));
    }
  }, [bairroSelected, useApi]);

  // Submit
  const submit = async () => {
    setBusy(true); setError("");
    try {
      const r = await useApi.create({
        rua: address.endereco,
        numero: address.numero,
        bairro: bairroSelected.bairro,
        cidade: bairroSelected.cidade || "",
        estado: bairroSelected.estado || "",
        referencia: address.referencia,
        lat: gps.lat, lng: gps.lng,
        capacity, network_type: networkType,
        splitter: networkType === "desbalanceada" ? splitter : null,
        client_port: clientPort,
        sigla: bairroSelected.sigla,
        vlan: bairroSelected.vlan,
        suggested_name: suggested.name,
        technician_id: collabId,
        technician_name: technician?.name || "",
      });
      onCreated?.(r);
    } catch (e) {
      const d = e?.response?.data?.detail;
      if (typeof d === "object" && d?.suggested_name) {
        setError(`${d.msg}. Sugerido: ${d.suggested_name}`);
        setSuggested({ name: d.suggested_name, number: d.suggested_number });
      } else {
        setError(typeof d === "string" ? d : "Falha ao criar CTO.");
      }
    } finally { setBusy(false); }
  };

  const totalSteps = networkType === "desbalanceada" ? 8 : 7;
  const stepLabels = useMemo(() => [
    "Início", "Endereço", "Identificação",
    "Capacidade", "Tipo de rede",
    networkType === "desbalanceada" ? "Splitter" : "Porta",
    networkType === "desbalanceada" ? "Porta" : "Resumo",
    "Resumo",
  ], [networkType]);

  return (
    <div data-testid="cto-wizard" style={{
      position: "fixed", inset: 0, background: C_BG, zIndex: 9999,
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      <div style={headerStyle}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <button data-testid="cto-back-btn"
                  onClick={() => (step > 1 ? setStep(step - 1) : onClose?.())}
                  style={{ background: "transparent", border: 0, color: "#fff",
                            fontSize: 24, marginRight: 4, cursor: "pointer", padding: 4 }}>
            ←
          </button>
          <span style={stepBadge}>{step}</span>
          <span>Cadastro de CTO</span>
        </div>
        <span style={{ fontSize: 11, opacity: 0.85 }}>{stepLabels[step - 1]}</span>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "20px 16px",
                       fontSize: 14, color: C_TEXT }}>
        {error && (
          <div data-testid="cto-error" style={{
            background: "#fef2f2", color: C_DANGER, borderRadius: 10,
            padding: "10px 14px", marginBottom: 12, fontSize: 13,
            border: "1px solid #fecaca",
          }}>{error}</div>
        )}

        {/* === STEP 1 === */}
        {step === 1 && (
          <div style={{ textAlign: "center", padding: "30px 12px 10px" }}>
            <div style={{
              width: 120, height: 120, margin: "0 auto 20px",
              borderRadius: "50%", background: "#fed7aa",
              display: "grid", placeItems: "center",
            }}>
              <div style={{
                fontSize: 56, color: C_ACCENT, lineHeight: 1,
              }}>⚠</div>
            </div>
            <div style={{ fontSize: 22, fontWeight: 800, marginBottom: 10,
                            letterSpacing: -0.3 }}>
              Cliente não<br />identificado em CTO
            </div>
            <p style={{ color: C_MUTED, fontSize: 13, lineHeight: 1.6,
                          margin: "0 0 30px", padding: "0 10px" }}>
              Este cliente não está vinculado a nenhuma CTO existente.
            </p>
            <button data-testid="cto-start-btn" style={accentBtn}
                    onClick={() => setStep(2)}>
              Cadastrar CTO
            </button>
          </div>
        )}

        {/* === STEP 2 === */}
        {step === 2 && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 14px",
                          letterSpacing: -0.3, lineHeight: 1.3 }}>
              Informe o endereço em frente à casa onde está a CTO
            </h2>

            <label style={labelStyle}>Endereço</label>
            <input data-testid="cto-rua" style={inputBase} value={address.endereco}
              onChange={(e) => setAddress({ ...address, endereco: e.target.value })}
              placeholder="Rua das Flores" />

            <label style={labelStyle}>Número</label>
            <input data-testid="cto-numero" style={inputBase} value={address.numero}
              onChange={(e) => setAddress({ ...address, numero: e.target.value })}
              placeholder="125" />

            <label style={labelStyle}>Referência</label>
            <input data-testid="cto-referencia" style={inputBase}
              value={address.referencia}
              onChange={(e) => setAddress({ ...address, referencia: e.target.value })}
              placeholder="Casa azul com portão branco" />

            <label style={labelStyle}>Localização da CTO</label>
            <button data-testid="cto-gps-btn" onClick={captureGps}
                    style={{
                      ...inputBase, display: "flex", alignItems: "center",
                      justifyContent: "space-between", cursor: "pointer",
                      background: gps.lat ? "#ecfdf5" : "#fff",
                      borderColor: gps.lat ? "#10b981" : C_BORDER,
                      padding: "16px 14px",
                    }}>
              <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ fontSize: 20 }}>📍</span>
                <span style={{ color: gps.lat ? "#065f46" : C_TEXT, fontWeight: 600 }}>
                  {gps.lat
                    ? `${gps.lat.toFixed(6)}, ${gps.lng.toFixed(6)}`
                    : "Usar localização atual (Mapa)"}
                </span>
              </span>
              <span style={{ color: C_MUTED, fontSize: 20 }}>›</span>
            </button>

            <div style={{ marginTop: 28 }}>
              <button data-testid="cto-step2-continue"
                      onClick={() => {
                        if (!address.endereco || !address.numero) {
                          setError("Endereço e número são obrigatórios.");
                          return;
                        }
                        setError("");
                        setStep(3);
                      }}
                      style={primaryBtn}>
                Continuar
              </button>
            </div>
          </div>
        )}

        {/* === STEP 3 — Identificação automática === */}
        {step === 3 && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 18px",
                           letterSpacing: -0.3 }}>
              Dados identificados automaticamente
            </h2>

            <label style={labelStyle}>Selecione o bairro</label>
            <div style={{ marginBottom: 14 }}>
              {bairros.length === 0 ? (
                <div style={{
                  padding: 14, border: `1px dashed ${C_BORDER}`, borderRadius: 12,
                  color: C_MUTED, fontSize: 12, textAlign: "center", background: "#fff",
                }}>
                  Nenhum bairro cadastrado. Peça ao admin para cadastrar bairros e
                  VLANs no painel <strong>Rede IA → Bairros</strong>.
                </div>
              ) : (
                <select data-testid="cto-bairro-select"
                  value={bairroSelected?.id || ""}
                  onChange={(e) => {
                    const b = bairros.find((x) => x.id === e.target.value);
                    setBairroSelected(b || null);
                  }}
                  style={{ ...inputBase, appearance: "none",
                            paddingRight: 34,
                            backgroundImage: "linear-gradient(45deg,transparent 50%,#64748b 50%),linear-gradient(135deg,#64748b 50%,transparent 50%)",
                            backgroundPosition: "calc(100% - 18px) center,calc(100% - 12px) center",
                            backgroundSize: "6px 6px,6px 6px",
                            backgroundRepeat: "no-repeat" }}>
                  <option value="">— Escolha um bairro —</option>
                  {bairros.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.bairro} (sigla {b.sigla} · VLAN {b.vlan})
                    </option>
                  ))}
                </select>
              )}
            </div>

            {bairroSelected && (
              <>
                {/* Bairro card verde */}
                <div data-testid="auto-card-bairro" style={{
                  ...cardBase, background: "#ecfdf5", borderColor: "#a7f3d0",
                  display: "flex", alignItems: "flex-start", gap: 12,
                }}>
                  <div style={{
                    width: 40, height: 40, borderRadius: 10,
                    background: "#d1fae5", display: "grid", placeItems: "center",
                    fontSize: 20, flexShrink: 0,
                  }}>🏠</div>
                  <div>
                    <div style={{ fontSize: 11, color: "#047857", fontWeight: 700,
                                     textTransform: "uppercase", letterSpacing: 0.5 }}>
                      Bairro identificado automaticamente
                    </div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: "#065f46",
                                     marginTop: 2 }}>
                      {bairroSelected.bairro}
                    </div>
                    <div style={{ fontSize: 11, color: "#047857", marginTop: 4 }}>
                      Sigla {bairroSelected.sigla} · VLAN {bairroSelected.vlan}
                      {bairroSelected.cidade ? ` · ${bairroSelected.cidade}` : ""}
                    </div>
                  </div>
                </div>

                {/* GPS card verde */}
                <div data-testid="auto-card-gps" style={{
                  ...cardBase, background: "#ecfdf5", borderColor: "#a7f3d0",
                  display: "flex", alignItems: "flex-start", gap: 12,
                }}>
                  <div style={{
                    width: 40, height: 40, borderRadius: 10,
                    background: "#d1fae5", display: "grid", placeItems: "center",
                    fontSize: 20, flexShrink: 0,
                  }}>📍</div>
                  <div>
                    <div style={{ fontSize: 11, color: "#047857", fontWeight: 700,
                                     textTransform: "uppercase", letterSpacing: 0.5 }}>
                      Posição GPS da CTO
                    </div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: "#065f46",
                                     marginTop: 2, fontFamily: "monospace" }}>
                      {gps.lat
                        ? `${gps.lat.toFixed(6)}, ${gps.lng.toFixed(6)}`
                        : "—  (volte ao passo 2 para capturar)"}
                    </div>
                  </div>
                </div>

                {/* Nomenclatura card roxo */}
                <div data-testid="auto-card-name" style={{
                  ...cardBase, background: C_PRIMARY_LIGHT, borderColor: "#c4b5fd",
                  display: "flex", alignItems: "flex-start", gap: 12,
                }}>
                  <div style={{
                    width: 40, height: 40, borderRadius: 10,
                    background: "#ddd6fe", display: "grid", placeItems: "center",
                    fontSize: 20, flexShrink: 0,
                  }}>🏷</div>
                  <div>
                    <div style={{ fontSize: 11, color: "#5b21b6", fontWeight: 700,
                                     textTransform: "uppercase", letterSpacing: 0.5 }}>
                      Nomenclatura da CTO gerada automaticamente
                    </div>
                    <div style={{ fontSize: 17, fontWeight: 800, color: C_PRIMARY,
                                     marginTop: 4 }}>
                      {suggested.name || "—"}
                    </div>
                  </div>
                </div>

                <div style={{
                  padding: "10px 14px", marginBottom: 16,
                  background: "#f1f5f9", borderRadius: 10,
                  display: "flex", alignItems: "flex-start", gap: 10,
                  fontSize: 12, color: C_MUTED, lineHeight: 1.5,
                }}>
                  <span style={{ fontSize: 16 }}>ℹ️</span>
                  <span>Essas informações foram geradas com base no endereço e na
                    localização informada.</span>
                </div>
              </>
            )}

            <button data-testid="cto-step3-continue"
                    disabled={!bairroSelected || !suggested.name}
                    onClick={() => setStep(4)}
                    style={{ ...primaryBtn,
                              opacity: (!bairroSelected || !suggested.name) ? 0.5 : 1 }}>
              Continuar
            </button>
          </div>
        )}

        {/* === STEP 4 — Quantidade de portas === */}
        {step === 4 && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3 }}>
              Quantas portas tem essa CTO?
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 22 }}>
              Selecione a capacidade física.
            </p>
            {[4, 8, 16].map((cap) => (
              <button key={cap} data-testid={`cto-cap-${cap}`}
                      onClick={() => setCapacity(cap)}
                      style={optionCard(capacity === cap)}>
                <span style={{ display: "flex", alignItems: "center", gap: 14 }}>
                  <span style={{
                    width: 36, height: 36, borderRadius: 8,
                    background: capacity === cap ? "#ddd6fe" : "#f1f5f9",
                    color: C_PRIMARY, display: "grid", placeItems: "center",
                    fontSize: 18, fontWeight: 800,
                  }}>▦</span>
                  <span style={{ fontSize: 15, fontWeight: 700 }}>{cap} portas</span>
                </span>
                <span style={checkBox(capacity === cap)}>
                  {capacity === cap ? "✓" : ""}
                </span>
              </button>
            ))}
            <div style={{ marginTop: 18 }}>
              <button data-testid="cto-step4-continue"
                      disabled={!capacity}
                      onClick={() => setStep(5)}
                      style={{ ...primaryBtn, opacity: !capacity ? 0.5 : 1 }}>
                Continuar
              </button>
            </div>
          </div>
        )}

        {/* === STEP 5 — Tipo de rede === */}
        {step === 5 && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3 }}>
              Tipo de rede
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 22 }}>
              Selecione o tipo de rede utilizada nesta CTO.
            </p>

            {[
              { v: "balanceada", l: "Rede balanceada",
                d: "Sinal distribuído de forma equilibrada entre as portas.",
                icon: "⚖️" },
              { v: "desbalanceada", l: "Rede desbalanceada",
                d: "Sinal distribuído de forma desbalanceada entre as portas.",
                icon: "⚙️" },
            ].map((opt) => (
              <button key={opt.v} data-testid={`cto-net-${opt.v.slice(0,3)}`}
                      onClick={() => setNetworkType(opt.v)}
                      style={{ ...optionCard(networkType === opt.v),
                                alignItems: "flex-start" }}>
                <span style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                  <span style={{
                    width: 38, height: 38, borderRadius: 8,
                    background: networkType === opt.v ? "#ddd6fe" : "#f1f5f9",
                    display: "grid", placeItems: "center", fontSize: 18,
                    flexShrink: 0,
                  }}>{opt.icon}</span>
                  <span>
                    <div style={{ fontSize: 14, fontWeight: 700 }}>{opt.l}</div>
                    <div style={{ fontSize: 11, color: C_MUTED, marginTop: 4,
                                     lineHeight: 1.4 }}>{opt.d}</div>
                  </span>
                </span>
                <span style={checkBox(networkType === opt.v)}>
                  {networkType === opt.v ? "✓" : ""}
                </span>
              </button>
            ))}
            <div style={{ marginTop: 18 }}>
              <button data-testid="cto-step5-continue"
                      disabled={!networkType}
                      onClick={() => setStep(networkType === "desbalanceada" ? 6 : 7)}
                      style={{ ...primaryBtn, opacity: !networkType ? 0.5 : 1 }}>
                Continuar
              </button>
            </div>
          </div>
        )}

        {/* === STEP 6 — Splitter === */}
        {step === 6 && networkType === "desbalanceada" && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3 }}>
              Qual é o splitter de balanceamento?
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 22 }}>
              Selecione o splitter utilizado na rede desbalanceada.
            </p>
            {["1:2", "1:4", "1:8", "Outro"].map((s) => (
              <button key={s} data-testid={`cto-splitter-${s}`}
                      onClick={() => setSplitter(s)}
                      style={optionCard(splitter === s)}>
                <span style={{ display: "flex", alignItems: "center", gap: 14 }}>
                  <span style={{
                    width: 36, height: 36, borderRadius: 8,
                    background: splitter === s ? "#ddd6fe" : "#f1f5f9",
                    color: C_PRIMARY, display: "grid", placeItems: "center",
                    fontSize: 18, fontWeight: 800,
                  }}>▣</span>
                  <span style={{ fontSize: 15, fontWeight: 700 }}>{s}</span>
                </span>
                <span style={checkBox(splitter === s)}>
                  {splitter === s ? "✓" : ""}
                </span>
              </button>
            ))}
            <div style={{ marginTop: 18 }}>
              <button data-testid="cto-step6-continue"
                      disabled={!splitter}
                      onClick={() => setStep(7)}
                      style={{ ...primaryBtn, opacity: !splitter ? 0.5 : 1 }}>
                Continuar
              </button>
            </div>
          </div>
        )}

        {/* === STEP 7 — Porta do cliente === */}
        {step === 7 && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3 }}>
              Selecione a porta usada pelo cliente
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 18 }}>
              Capacidade da CTO: <strong>{capacity} portas</strong>
            </p>
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(4, 1fr)",
              gap: 10, marginBottom: 14,
            }}>
              {Array.from({ length: capacity || 0 }, (_, i) => i + 1).map((p) => (
                <button key={p} data-testid={`cto-port-${p}`}
                        onClick={() => setClientPort(p)}
                        style={{
                          padding: "18px 0", borderRadius: 12,
                          border: `2px solid ${clientPort === p ? C_PRIMARY : C_BORDER}`,
                          background: clientPort === p ? C_PRIMARY : "#fff",
                          color: clientPort === p ? "#fff" : C_TEXT,
                          fontSize: 18, fontWeight: 700, cursor: "pointer",
                          position: "relative",
                        }}>
                  {p}
                  {clientPort === p && (
                    <span style={{
                      position: "absolute", top: 4, right: 6,
                      fontSize: 12, fontWeight: 800,
                    }}>✓</span>
                  )}
                </button>
              ))}
            </div>
            {clientPort && (
              <div style={{
                padding: "12px 14px",
                background: C_PRIMARY_LIGHT, borderRadius: 10,
                fontSize: 13, color: "#5b21b6", fontWeight: 600,
                display: "flex", alignItems: "center", gap: 10,
                border: "1px solid #c4b5fd",
              }}>
                <span style={{ fontSize: 14 }}>ℹ️</span>
                <span>Porta selecionada: <strong>{clientPort}</strong></span>
              </div>
            )}
            <div style={{ marginTop: 24 }}>
              <button data-testid="cto-step7-continue"
                      disabled={!clientPort}
                      onClick={() => setStep(8)}
                      style={{ ...primaryBtn, opacity: !clientPort ? 0.5 : 1 }}>
                Continuar
              </button>
            </div>
          </div>
        )}

        {/* === STEP 8 — Resumo === */}
        {step === 8 && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3, textAlign: "center" }}>
              Resumo do cadastro
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 18,
                          textAlign: "center" }}>
              Confira os dados antes de salvar
            </p>

            <div style={{ ...cardBase, padding: "4px 0" }}>
              <SummaryRow icon="🏠" label="Endereço de referência"
                value={`${address.endereco}, ${address.numero}${address.referencia ? "\n" + address.referencia : ""}`} />
              <SummaryRow icon="🏷" label="Bairro" value={bairroSelected?.bairro} />
              <SummaryRow icon="📍" label="Posição GPS"
                value={gps.lat ? `${gps.lat.toFixed(6)}, ${gps.lng.toFixed(6)}` : "—"} />
              <SummaryRow icon="🏷" label="Nomenclatura da CTO"
                value={suggested.name} highlight />
              <SummaryRow icon="▦" label="Quantidade de portas"
                value={`${capacity} portas`} />
              <SummaryRow icon="🔗" label="Tipo de rede"
                value={networkType === "balanceada" ? "Rede balanceada" : "Rede desbalanceada"} />
              {networkType === "desbalanceada" && (
                <SummaryRow icon="🔀" label="Splitter de balanceamento"
                  value={splitter} />
              )}
              <SummaryRow icon="📥" label="Porta do cliente"
                value={`Porta ${clientPort}`} last />
            </div>

            <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 10 }}>
              <button data-testid="cto-summary-submit" style={accentBtn}
                      disabled={busy} onClick={submit}>
                {busy ? "Salvando..." : "Salvar cadastro"}
              </button>
              <button data-testid="cto-summary-back"
                      onClick={() => setStep(7)}
                      style={{
                        ...primaryBtn,
                        background: "#fff", color: C_TEXT,
                        border: `1.5px solid ${C_BORDER}`,
                        boxShadow: "none",
                      }}>
                Voltar e editar
              </button>
            </div>
          </div>
        )}

        {/* Progress dots */}
        {step >= 2 && (
          <div style={{
            display: "flex", justifyContent: "center", gap: 8,
            marginTop: 30,
          }}>
            {Array.from({ length: totalSteps }, (_, i) => i + 1).map((n) => (
              <span key={n} style={{
                width: 6, height: 6, borderRadius: 999,
                background: n <= step ? C_PRIMARY : "#cbd5e1",
                transition: "background-color .2s",
              }} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function SummaryRow({ icon, label, value, highlight, last }) {
  return (
    <div style={{
      display: "flex", gap: 12, padding: "12px 14px",
      borderBottom: last ? "none" : `1px solid ${C_BORDER}`,
      background: highlight ? C_PRIMARY_LIGHT : "transparent",
    }}>
      <div style={{
        width: 32, height: 32, borderRadius: 8,
        background: highlight ? "#ddd6fe" : "#f1f5f9",
        display: "grid", placeItems: "center", fontSize: 14, flexShrink: 0,
      }}>{icon}</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 10, color: highlight ? "#5b21b6" : C_MUTED,
                       textTransform: "uppercase", letterSpacing: 0.5,
                       fontWeight: 700, marginBottom: 3 }}>{label}</div>
        <div style={{ fontSize: 14, fontWeight: highlight ? 800 : 600,
                       color: highlight ? C_PRIMARY : C_TEXT,
                       whiteSpace: "pre-line", lineHeight: 1.4 }}>
          {value || "—"}
        </div>
      </div>
    </div>
  );
}
