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
import CTOMapPicker from "@/CTOMapPicker";

// Paleta sóbria/corporate — slate/indigo (sem roxo vibrante, sem laranja)
const C_BG = "#f8fafc";
const C_HEADER_BG = "#0f172a";       // slate-900 (header escuro elegante)
const C_PRIMARY = "#1e293b";          // slate-800 (botão e estados ativos)
const C_PRIMARY_LIGHT = "#f1f5f9";    // slate-100 (cards selecionados)
const C_ACCENT = "#0f766e";           // teal-700 (submit final - sóbrio, transmite "concluir")
const C_TEXT = "#0f172a";
const C_MUTED = "#64748b";
const C_BORDER = "#e2e8f0";
const C_DANGER = "#b91c1c";
const C_SUCCESS = "#15803d";

const headerStyle = {
  background: C_HEADER_BG,
  color: "#fff",
  padding: "14px 16px",
  display: "flex", alignItems: "center", justifyContent: "space-between",
  fontWeight: 600, fontSize: 15, letterSpacing: 0.2,
  position: "sticky", top: 0, zIndex: 10,
  borderBottom: "1px solid rgba(255,255,255,0.06)",
};
const stepBadge = {
  display: "inline-flex", alignItems: "center", justifyContent: "center",
  width: 24, height: 24, borderRadius: 6,
  background: "rgba(255,255,255,0.12)", color: "#fff",
  fontSize: 12, fontWeight: 700, marginRight: 10,
  fontVariantNumeric: "tabular-nums",
};
const cardBase = {
  background: "#fff",
  borderRadius: 10,
  border: `1px solid ${C_BORDER}`,
  padding: "14px 14px",
  marginBottom: 10,
};
const inputBase = {
  width: "100%", padding: "12px 13px", borderRadius: 8,
  border: `1px solid ${C_BORDER}`, fontSize: 14, color: C_TEXT,
  background: "#fff", outline: "none", boxSizing: "border-box",
  fontFamily: "inherit",
};
const labelStyle = {
  fontSize: 11, fontWeight: 700, color: C_MUTED,
  marginBottom: 5, marginTop: 12, display: "block",
  textTransform: "uppercase", letterSpacing: 0.6,
};
const primaryBtn = {
  width: "100%", padding: "13px 20px", borderRadius: 8,
  background: C_PRIMARY, color: "#fff", border: 0,
  fontWeight: 600, fontSize: 14, cursor: "pointer",
  letterSpacing: 0.2,
  boxShadow: "0 1px 2px rgba(15,23,42,0.15)",
};
const accentBtn = {
  ...primaryBtn,
  background: C_ACCENT,
  boxShadow: "0 1px 2px rgba(15,118,110,0.25)",
};
const optionCard = (selected) => ({
  padding: "14px 14px",
  borderRadius: 10,
  border: `1.5px solid ${selected ? C_PRIMARY : C_BORDER}`,
  background: selected ? C_PRIMARY_LIGHT : "#fff",
  cursor: "pointer",
  textAlign: "left",
  display: "flex", alignItems: "center", justifyContent: "space-between",
  fontSize: 14, fontWeight: 500, color: C_TEXT,
  marginBottom: 8,
  transition: "background-color .15s, border-color .15s",
});
const checkBox = (selected) => ({
  width: 20, height: 20, borderRadius: 5,
  border: `1.5px solid ${selected ? C_PRIMARY : "#cbd5e1"}`,
  background: selected ? C_PRIMARY : "#fff",
  color: "#fff", fontSize: 12, fontWeight: 700,
  display: "grid", placeItems: "center", flexShrink: 0,
});

export default function CadastroCTOWizard({ onClose, onCreated, technician }) {
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [address, setAddress] = useState({
    endereco: "", numero: "", referencia: "",
    bairro_detected: "", cidade_detected: "", estado_detected: "",
  });
  const [gps, setGps] = useState({ lat: null, lng: null, accuracy: null });
  const [bairros, setBairros] = useState([]);
  const [bairroSelected, setBairroSelected] = useState(null);
  const [bairroAutoMatched, setBairroAutoMatched] = useState(false);
  const [vlanInput, setVlanInput] = useState("");
  const [ensuringBairro, setEnsuringBairro] = useState(false);
  const [suggested, setSuggested] = useState({ name: "", number: null });
  const [capacity, setCapacity] = useState(null);
  const [networkType, setNetworkType] = useState(null);
  const [splitter, setSplitter] = useState(null);
  const [clientPort, setClientPort] = useState(null);
  const [photo, setPhoto] = useState(null); // base64 data url
  const fileInputRef = React.useRef(null);

  // Foto: aceita captura via input file (mobile abre câmera)
  const onPhotoChange = useCallback((e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) {
      setError("Foto muito grande (limite 4MB).");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      // Reduz tamanho usando canvas (max 1280px na maior dimensão)
      const img = new Image();
      img.onload = () => {
        const max = 1280;
        let { width: w, height: h } = img;
        if (w > max || h > max) {
          if (w > h) { h = Math.round(h * max / w); w = max; }
          else { w = Math.round(w * max / h); h = max; }
        }
        const canvas = document.createElement("canvas");
        canvas.width = w; canvas.height = h;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, w, h);
        setPhoto(canvas.toDataURL("image/jpeg", 0.78));
        setError("");
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  }, []);

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

  // Carrega bairros logo após o GPS pegar o bairro (no Step 2) para
  // já fazer o auto-match e poder PULAR o step 3 se houver casamento.
  useEffect(() => {
    if (!address.bairro_detected) return;
    useApi.bairros().then((r) => {
      const list = r.items || [];
      setBairros(list);
      if (list.length === 0) return;
      const norm = (s) => (s || "").toString().normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
      const target = norm(address.bairro_detected);
      const match = list.find((b) => norm(b.bairro) === target)
        || list.find((b) => norm(b.bairro).includes(target) || target.includes(norm(b.bairro)));
      if (match) {
        setBairroSelected(match);
        setBairroAutoMatched(true);
      } else {
        setBairroAutoMatched(false);
      }
    }).catch(() => setBairros([]));
  }, [address.bairro_detected, useApi]);

  // Navegação. NÃO pula mais o step 3 — a VLAN agora é informada pelo
  // técnico (não vem do bairro pré-cadastrado).
  const goNext = () => setStep((s) => s + 1);
  const goBack = () => setStep((s) => (s > 1 ? s - 1 : s));

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
      const splitterValue = (splitter && !splitter.startsWith("Sem"))
        ? splitter : null;
      const r = await useApi.create({
        rua: address.endereco,
        numero: address.numero,
        bairro: bairroSelected.bairro,
        cidade: bairroSelected.cidade || address.cidade_detected || "",
        estado: bairroSelected.estado || address.estado_detected || "",
        referencia: address.referencia,
        lat: gps.lat, lng: gps.lng,
        capacity, network_type: networkType,
        splitter: splitterValue,
        client_port: clientPort,
        sigla: bairroSelected.sigla,
        vlan: bairroSelected.vlan,
        suggested_name: suggested.name,
        technician_id: collabId,
        technician_name: technician?.name || "",
        photo_data_url: photo || null,
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

  const totalSteps = 8;
  const stepLabels = useMemo(() => [
    "Início", "Endereço (mapa)", "Identificação",
    "Capacidade", "Tipo de rede", "Splitter",
    "Porta", "Resumo",
  ], []);

  return (
    <div data-testid="cto-wizard" style={{
      position: "fixed", inset: 0, background: C_BG, zIndex: 9999,
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      <div style={headerStyle}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <button data-testid="cto-back-btn"
                  onClick={() => (step > 1 ? goBack() : onClose?.())}
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

        {/* === STEP 2 — Mapa Uber-like + endereço auto + foto === */}
        {step === 2 && (
          <div style={{ display: "flex", flexDirection: "column",
                          height: "calc(100vh - 110px)", marginTop: -20,
                          marginLeft: -16, marginRight: -16 }}>
            {/* MAPA — ocupa ~62% da tela */}
            <div style={{ flex: "0 0 62%", position: "relative",
                            background: "#e2e8f0" }}>
              <CTOMapPicker
                collabId={collabId}
                onMove={({ lat, lng, address: a }) => {
                  setGps({ lat, lng, accuracy: null });
                  setAddress((prev) => ({
                    ...prev,
                    endereco: a.road || prev.endereco,
                    numero: a.house_number || prev.numero,
                    bairro_detected: a.suburb || "",
                    cidade_detected: a.city || "",
                    estado_detected: a.state || "",
                  }));
                  setError("");
                }}
                onError={(m) => setError(m)}
              />
            </div>

            {/* PAINEL inferior — endereço + foto + continuar */}
            <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px 16px",
                            background: "#fff", borderTopLeftRadius: 16,
                            borderTopRightRadius: 16, marginTop: -16,
                            position: "relative", zIndex: 5,
                            boxShadow: "0 -6px 18px rgba(0,0,0,0.08)" }}>
              <h2 style={{ fontSize: 16, fontWeight: 800,
                              margin: "2px 0 10px", letterSpacing: -0.2 }}>
                Posicione o pino na CTO
              </h2>

              <label style={{ ...labelStyle, marginTop: 4 }}>Endereço (auto)</label>
              <input data-testid="cto-rua" style={inputBase} value={address.endereco}
                onChange={(e) => setAddress({ ...address, endereco: e.target.value })}
                placeholder="Detectado pelo mapa" />

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                              gap: 10 }}>
                <div>
                  <label style={labelStyle}>Número</label>
                  <input data-testid="cto-numero" style={inputBase} value={address.numero}
                    onChange={(e) => setAddress({ ...address, numero: e.target.value })}
                    placeholder="—" />
                </div>
                <div>
                  <label style={labelStyle}>Bairro (auto)</label>
                  <input data-testid="cto-bairro-detected" style={inputBase}
                    value={address.bairro_detected} readOnly
                    placeholder="—" />
                </div>
              </div>

              <label style={labelStyle}>Referência (opcional)</label>
              <input data-testid="cto-referencia" style={inputBase}
                value={address.referencia}
                onChange={(e) => setAddress({ ...address, referencia: e.target.value })}
                placeholder="Casa azul com portão branco" />

              {/* FOTO da CTO — logo após o endereço (movido do step antigo) */}
              <label style={labelStyle}>Foto da CTO (opcional)</label>
              <input ref={fileInputRef} type="file" accept="image/*" capture="environment"
                onChange={onPhotoChange} style={{ display: "none" }}
                data-testid="cto-photo-input" />
              {photo ? (
                <div style={{
                  position: "relative", borderRadius: 12,
                  overflow: "hidden", border: `1.5px solid ${C_BORDER}`,
                  marginBottom: 6,
                }}>
                  <img src={photo} alt="Foto CTO" data-testid="cto-photo-preview"
                    style={{ width: "100%", display: "block",
                              maxHeight: 220, objectFit: "cover" }} />
                  <button data-testid="cto-photo-remove"
                    onClick={() => { setPhoto(null);
                                       if (fileInputRef.current) fileInputRef.current.value = ""; }}
                    style={{
                      position: "absolute", top: 8, right: 8,
                      background: "rgba(0,0,0,0.6)", color: "#fff",
                      border: 0, borderRadius: "50%", width: 28, height: 28,
                      fontSize: 14, fontWeight: 800, cursor: "pointer",
                    }}>×</button>
                </div>
              ) : (
                <button data-testid="cto-photo-btn"
                        onClick={() => fileInputRef.current?.click()}
                        style={{
                          ...inputBase, display: "flex", alignItems: "center",
                          justifyContent: "space-between", cursor: "pointer",
                          padding: "14px 14px",
                        }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ fontSize: 20 }}>📷</span>
                    <span style={{ color: C_TEXT, fontWeight: 600 }}>
                      Tirar foto da CTO
                    </span>
                  </span>
                  <span style={{ color: C_MUTED, fontSize: 20 }}>›</span>
                </button>
              )}

              {/* Feedback do match de bairro */}
              {address.bairro_detected && bairros.length > 0 && (
                <div data-testid="cto-bairro-feedback" style={{
                  marginTop: 10, padding: "8px 10px",
                  borderRadius: 6, fontSize: 11.5, lineHeight: 1.4,
                  background: bairroAutoMatched ? "#f0fdf4" : "#fffbeb",
                  color: bairroAutoMatched ? "#166534" : "#854d0e",
                  border: `1px solid ${bairroAutoMatched ? "#bbf7d0" : "#fde68a"}`,
                  display: "flex", alignItems: "center", gap: 8,
                }}>
                  <span style={{ fontSize: 13 }}>
                    {bairroAutoMatched ? "✓" : "!"}
                  </span>
                  <span>
                    {bairroAutoMatched ? (
                      <>
                        Bairro <strong>{bairroSelected.bairro}</strong> identificado
                        — VLAN <strong>{bairroSelected.vlan}</strong> (sigla{" "}
                        {bairroSelected.sigla}).
                      </>
                    ) : (
                      <>
                        Bairro <strong>{address.bairro_detected}</strong> não está na base.
                        Na próxima tela você escolhe o equivalente.
                      </>
                    )}
                  </span>
                </div>
              )}

              <div style={{ marginTop: 16 }}>
                <button data-testid="cto-step2-continue"
                        onClick={() => {
                          if (!gps.lat || !gps.lng) {
                            setError("Posicione o pino no mapa antes de continuar.");
                            return;
                          }
                          if (!address.endereco) {
                            setError("Endereço não detectado. Mova o pino até a rua.");
                            return;
                          }
                          setError("");
                          goNext();
                        }}
                        style={primaryBtn}>
                  Continuar
                </button>
              </div>
            </div>
          </div>
        )}

        {/* === STEP 3 — VLAN da CTO (sem precisar de bairro pré-cadastrado) === */}
        {step === 3 && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3 }}>
              Qual é a VLAN dessa CTO?
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 18,
                          lineHeight: 1.4 }}>
              Bairro detectado: <strong>{address.bairro_detected || "—"}</strong>.
              Informe o número da VLAN da rede no local. Se já existir um
              cadastro desse bairro nessa VLAN, vamos reusar; caso contrário,
              criamos automaticamente.
            </p>

            {/* VLANs já cadastradas para esse bairro (sugestão de reuso) */}
            {(() => {
              const norm = (s) => (s || "").normalize("NFD")
                .replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
              const target = norm(address.bairro_detected);
              const sameBairro = bairros.filter(
                (b) => norm(b.bairro) === target,
              );
              if (sameBairro.length === 0) return null;
              return (
                <div data-testid="cto-vlan-suggestions" style={{ marginBottom: 16 }}>
                  <div style={{ ...labelStyle, marginTop: 0 }}>
                    Bairro já tem cadastro — toque para reutilizar:
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {sameBairro.map((b) => (
                      <button key={b.id}
                              data-testid={`cto-vlan-chip-${b.vlan}`}
                              type="button"
                              onClick={() => {
                                setVlanInput(String(b.vlan));
                                setBairroSelected(b);
                              }}
                              style={{
                                padding: "8px 12px", borderRadius: 999,
                                border: bairroSelected?.id === b.id
                                  ? `1.5px solid ${C_PRIMARY}` : `1px solid ${C_BORDER}`,
                                background: bairroSelected?.id === b.id
                                  ? C_PRIMARY_LIGHT : "#fff",
                                fontSize: 12, fontWeight: 700, color: C_TEXT,
                                cursor: "pointer",
                              }}>
                        VLAN <strong>{b.vlan}</strong> · {b.sigla}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })()}

            <label style={labelStyle}>VLAN (número de 1 a 4094)</label>
            <input
              data-testid="cto-vlan-input"
              type="number"
              inputMode="numeric"
              min="1" max="4094"
              value={vlanInput}
              onChange={(e) => {
                setVlanInput(e.target.value);
                // Se digitou algo diferente do bairroSelected, limpa seleção
                if (bairroSelected && String(bairroSelected.vlan) !== e.target.value) {
                  setBairroSelected(null);
                }
              }}
              style={{ ...inputBase, fontSize: 18, fontWeight: 700,
                       fontFamily: "monospace", letterSpacing: 1 }}
              placeholder="Ex: 301" />

            {/* Preview da nomenclatura quando já temos VLAN */}
            {vlanInput && parseInt(vlanInput, 10) > 0 && (
              <div style={{
                marginTop: 14, padding: "12px 14px",
                background: "#f1f5f9", borderRadius: 8,
                border: `1px solid ${C_BORDER}`,
                fontSize: 12, color: C_MUTED, lineHeight: 1.5,
              }}>
                {bairroSelected ? (
                  <>
                    ✓ Reutilizando: <strong>{bairroSelected.bairro}</strong>
                    {" "}· sigla <strong>{bairroSelected.sigla}</strong>
                    {" "}· VLAN <strong>{bairroSelected.vlan}</strong>
                  </>
                ) : (
                  <>
                    Será criado: bairro <strong>{address.bairro_detected || "?"}</strong>
                    {" "}· VLAN <strong>{vlanInput}</strong> (sigla auto-gerada)
                  </>
                )}
              </div>
            )}

            {error && step === 3 && (
              <div style={{ marginTop: 12, padding: 10, background: "#fee2e2",
                              color: "#991b1b", borderRadius: 8, fontSize: 12 }}>
                {error}
              </div>
            )}

            <button data-testid="cto-step3-continue"
                    disabled={!vlanInput || parseInt(vlanInput, 10) < 1
                              || parseInt(vlanInput, 10) > 4094 || ensuringBairro}
                    onClick={async () => {
                      const vlanNum = parseInt(vlanInput, 10);
                      if (!vlanNum || vlanNum < 1 || vlanNum > 4094) {
                        setError("VLAN deve ser um número entre 1 e 4094.");
                        return;
                      }
                      setError("");
                      // Se já reusou, segue
                      if (bairroSelected && bairroSelected.vlan === vlanNum) {
                        setStep(4);
                        return;
                      }
                      // Senão, garante (cria ou reusa via backend)
                      setEnsuringBairro(true);
                      try {
                        const fn = collabId
                          ? (data) => useApi.redeIaBairroEnsureFromFieldPublic?.(collabId, data) ?? api.redeIaBairroEnsureFromFieldPublic(collabId, data)
                          : api.redeIaBairroEnsureFromField;
                        const r = await fn({
                          bairro: address.bairro_detected || "Bairro detectado",
                          vlan: vlanNum,
                          cidade: address.cidade_detected || "",
                          estado: address.estado_detected || "",
                        });
                        setBairroSelected(r.bairro);
                        // Atualiza a lista de bairros para refletir o novo
                        if (r.created) {
                          setBairros((prev) => [...prev, r.bairro]);
                        }
                        setStep(4);
                      } catch (e) {
                        setError(e?.response?.data?.detail
                                    || "Falha ao registrar bairro/VLAN.");
                      } finally {
                        setEnsuringBairro(false);
                      }
                    }}
                    style={{ ...primaryBtn,
                              marginTop: 22,
                              opacity: (!vlanInput || ensuringBairro) ? 0.5 : 1 }}>
              {ensuringBairro ? "Registrando..." : "Continuar"}
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
                      onClick={() => setStep(6)}
                      style={{ ...primaryBtn, opacity: !networkType ? 0.5 : 1 }}>
                Continuar
              </button>
            </div>
          </div>
        )}

        {/* === STEP 6 — Splitter (sempre opcional) === */}
        {step === 6 && (
          <div>
            <h2 style={{ fontSize: 19, fontWeight: 800, margin: "4px 0 4px",
                           letterSpacing: -0.3 }}>
              {networkType === "desbalanceada"
                ? "Qual é o splitter de balanceamento?"
                : "Esta CTO tem splitter?"}
            </h2>
            <p style={{ color: C_MUTED, fontSize: 13, marginBottom: 22 }}>
              {networkType === "desbalanceada"
                ? "Selecione o splitter utilizado na rede desbalanceada."
                : "Informe o splitter se houver. Caso não saiba, escolha \"Sem splitter / não informado\"."}
            </p>
            {["1:2", "1:4", "1:8", "5/95", "10/90", "20/80", "35/65", "50/50", "Outro", "Sem splitter / não informado"].map((s) => (
              <button key={s} data-testid={`cto-splitter-${s.replace(/[^a-z0-9]/gi,'_')}`}
                      onClick={() => setSplitter(s)}
                      style={optionCard(splitter === s)}>
                <span style={{ display: "flex", alignItems: "center", gap: 14 }}>
                  <span style={{
                    width: 36, height: 36, borderRadius: 8,
                    background: splitter === s ? "#ddd6fe" : "#f1f5f9",
                    color: C_PRIMARY, display: "grid", placeItems: "center",
                    fontSize: 18, fontWeight: 800,
                  }}>{s.startsWith("Sem") ? "—" : "▣"}</span>
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
                value={`Porta ${clientPort}`} last={!photo} />
              {photo && (
                <div style={{ padding: "12px 14px",
                                 borderTop: `1px solid ${C_BORDER}` }}>
                  <div style={{ fontSize: 10, color: C_MUTED, fontWeight: 700,
                                   textTransform: "uppercase", letterSpacing: 0.5,
                                   marginBottom: 8 }}>
                    📷 Foto da CTO
                  </div>
                  <img src={photo} alt="Foto CTO"
                    style={{ width: "100%", borderRadius: 10,
                              border: `1px solid ${C_BORDER}`,
                              maxHeight: 200, objectFit: "cover" }} />
                </div>
              )}
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

/* ===== Estilos padronizados ===== */
const autoCardStyle = {
  background: "#fff",
  border: `1.5px solid ${C_BORDER}`,
  borderRadius: 14,
  padding: "14px 14px",
  marginBottom: 10,
  display: "flex",
  alignItems: "flex-start",
  gap: 12,
};
const iconBoxStyle = (bg, fg) => ({
  width: 40, height: 40, borderRadius: 10,
  background: bg, color: fg,
  display: "grid", placeItems: "center",
  fontSize: 18, flexShrink: 0,
});
const autoLabelStyle = {
  fontSize: 10, color: C_MUTED, fontWeight: 700,
  textTransform: "uppercase", letterSpacing: 0.5,
  marginBottom: 4,
};
const autoValueStyle = {
  fontSize: 15, fontWeight: 700, color: C_TEXT,
  lineHeight: 1.3,
};
const autoSubStyle = {
  fontSize: 11, color: C_MUTED, marginTop: 4,
};
