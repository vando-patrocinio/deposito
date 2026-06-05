/* CtoInlineFlow — Cadastro CTO compactado em 2 telas, embutido no fluxo
   de finalização da OS. Tela A: GPS+Foto+VLAN. Tela B: Portas+Tipo+Splitter+Porta.
   Ao submit (botão final na Tela B), cria a CTO no backend público e auto-vincula
   o cliente atual da OS à porta escolhida via callback onCreated. */
import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { api } from "@/api";
import CTOMapPicker from "@/CTOMapPicker";

const C_TEXT = "#0f172a";
const C_MUTED = "#64748b";
const C_BORDER = "#e2e8f0";
const C_PRIMARY = "#1e293b";
const C_PRIMARY_LIGHT = "#f1f5f9";

const labelStyle = {
  fontSize: 11, fontWeight: 700, color: C_MUTED,
  marginBottom: 5, marginTop: 12, display: "block",
  textTransform: "uppercase", letterSpacing: 0.6,
};
const inputBase = {
  width: "100%", padding: "12px 13px", borderRadius: 8,
  border: `1px solid ${C_BORDER}`, fontSize: 14, color: C_TEXT,
  background: "#fff", outline: "none", boxSizing: "border-box",
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
});
const checkBox = (selected) => ({
  width: 20, height: 20, borderRadius: 5,
  border: `1.5px solid ${selected ? C_PRIMARY : "#cbd5e1"}`,
  background: selected ? C_PRIMARY : "#fff",
  color: "#fff", fontSize: 12, fontWeight: 700,
  display: "grid", placeItems: "center", flexShrink: 0,
});

/**
 * Props:
 * - screen: "A" (gps+foto+vlan) | "B" (portas+tipo+splitter+porta)
 * - state, setState: estado controlado externamente (TicketDetail)
 * - collabId
 * - client: { id, name }
 * - technician: { id, name }
 * - onSkipFromA(): técnico clica "Pular" na tela A
 * - onAdvanceFromA(): técnico clica "Continuar" na tela A
 * - onBackFromB(): técnico clica "Voltar" na tela B
 * - onCreated({ cto, port_number }): CTO criada (chama callback final p/ TicketDetail)
 * - onSelectExistingCto(cto): técnico tocou numa CTO existente no mapa
 */
export default function CtoInlineFlow({
  screen,
  state, setState,
  collabId, client, technician,
  onSkipFromA, onAdvanceFromA, onBackFromB, onCreated,
  onSelectExistingCto,
  isFullUnlock = false,
  // iter211am — toggle global (Configurações > Validações da OS).
  // Quando DESLIGADO, o passo de foto da CTO é totalmente removido.
  ctoPhotoRequired = true,
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const fileInputRef = useRef(null);

  // === Detecção de "cliente já está cadastrado em outra porta" ===
  // Busca a porta atual do cliente (em qualquer CTO da empresa) e, quando
  // o técnico seleciona uma porta diferente, pergunta se quer trocar. Se
  // confirmar, libera a porta antiga e ocupa a nova (e sincroniza com o
  // SmartOLT, se o cadastro original veio de lá).
  const [clientCurrentPort, setClientCurrentPort] = useState(null);
  const [showSwapDialog, setShowSwapDialog] = useState(false);
  const [swapTargetPort, setSwapTargetPort] = useState(null);
  const [swapBusy, setSwapBusy] = useState(false);

  useEffect(() => {
    if (!client?.id || !collabId) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await api.redeIaClientCurrentPort(collabId, client.id);
        if (cancelled) return;
        setClientCurrentPort(r?.found ? r.current : null);
      } catch { /* sem trava se falhar */ }
    })();
    return () => { cancelled = true; };
  }, [client?.id, collabId]);

  // Sigla padrão do bairro detectado (3 primeiras letras maiúsculas, SEM
  // acentos — pra bater com a normalização do backend que armazena
  // siglas ASCII no bairros_vlan_map).
  const autoSigla = useMemo(() => {
    const b = (state?.address?.bairro_detected || "").trim();
    if (!b) return "";
    // Remove acentos via NFD + filtra diacríticos (combining marks)
    const noAccents = b.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    return noAccents.replace(/[^A-Za-z]/g, "").toUpperCase().slice(0, 3);
  }, [state?.address?.bairro_detected]);

  const onPhotoChange = useCallback((e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) {
      setErr("Foto muito grande (máx 4MB).");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
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
        setState((s) => ({ ...s, photo: canvas.toDataURL("image/jpeg", 0.78) }));
        setErr("");
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  }, [setState]);

  async function submitCreate() {
    setBusy(true); setErr("");
    try {
      if (!state.photo && !isFullUnlock && ctoPhotoRequired) throw new Error("Foto da CTO é obrigatória.");
      if (!state.clientPort) throw new Error("Selecione a porta do cliente.");

      // Modo "usar CTO existente" — não cria nova; só vincula via OS
      if (state.existingCtoId) {
        // Retorna a CTO existente (que está em ctoSelected externamente) com a porta
        onCreated?.({
          cto: { id: state.existingCtoId,
                  name: state.address?.endereco ? null : null,
                  ...(state) },
          port_number: state.clientPort,
          photo: state.photo,
        });
        return;
      }

      const vlan = parseInt(state.vlan, 10);
      if (!vlan || vlan < 1 || vlan > 4094) {
        throw new Error("VLAN inválida (1 a 4094).");
      }
      if (!state.gps?.lat || !state.gps?.lng) {
        throw new Error("GPS não capturado. Volte e posicione o pino no mapa.");
      }
      if (!state.address?.endereco) {
        throw new Error("Endereço não detectado.");
      }
      if (!autoSigla || autoSigla.length < 2) {
        throw new Error("Digite o bairro (campo acima) para gerar a sigla.");
      }
      if (!state.capacity) throw new Error("Selecione a quantidade de portas.");
      if (!state.networkType) throw new Error("Selecione o tipo de rede.");
      // iter211ar — splitter agora é selecionado nos 2 tipos de rede.
      if (!state.splitter) {
        throw new Error("Selecione o splitter (ou 'Sem splitter').");
      }
      // iter211aq — Nº da CTO agora é obrigatório (sem auto-numeração).
      // Backend continua bloqueando duplicidade no bairro/VLAN (409).
      const ctoNum = parseInt(state.ctoNumber, 10);
      if (!ctoNum || ctoNum < 1 || ctoNum > 9999) {
        throw new Error("Digite o nº da CTO (1 a 9999).");
      }

      // Garante que o bairro está cadastrado (cria se não existir)
      await api.redeIaBairroEnsureFromFieldPublic(collabId, {
        bairro: state.address.bairro_detected,
        sigla: autoSigla,
        vlan,
        cidade: state.address.cidade_detected || "",
        estado: (state.address.estado_detected || "").toUpperCase(),
      }).catch(() => { /* já existe — ok */ });

      // Cria a CTO via endpoint público (auto-vincula cliente à porta).
      // iter211ar — "Sem splitter" vira null no payload (em qualquer tipo).
      const splitterValue = (state.splitter && !state.splitter.startsWith("Sem"))
        ? state.splitter : null;

      const r = await api.redeIaCtoCreatePublic(collabId, {
        rua: state.address.endereco,
        numero: state.address.numero || "",
        bairro: state.address.bairro_detected,
        cidade: state.address.cidade_detected || "",
        estado: (state.address.estado_detected || "").toUpperCase(),
        referencia: state.address.referencia || "",
        lat: state.gps.lat, lng: state.gps.lng,
        capacity: state.capacity,
        network_type: state.networkType,
        splitter: splitterValue,
        client_port: state.clientPort,
        client_subscriber_id: client?.id || null,
        client_pppoe: null,
        sigla: autoSigla,
        vlan,
        suggested_name: "",
        cto_number: state.ctoNumber ? Number(state.ctoNumber) : null,
        technician_id: technician?.id || collabId,
        technician_name: technician?.name || "",
        photo_data_url: state.photo || null,
      });

      onCreated?.({ cto: r, port_number: state.clientPort });
    } catch (e) {
      const d = e?.response?.data?.detail;
      // Erro 409 = duplicidade. iter211aq — NÃO auto-preenche o sugerido:
      // técnico tem que digitar manualmente. Só mostra a sugestão na msg.
      if (e?.response?.status === 409 && d && d.suggested_number) {
        setErr(
          `❌ ${d.msg || "Esta CTO já existe neste bairro/VLAN."} `
          + `Próximo número livre: ${d.suggested_number}. Digite outro número.`,
        );
      } else {
        setErr(typeof d === "string" ? d : (d?.msg || e.message || "Falha ao criar CTO."));
      }
    } finally {
      setBusy(false);
    }
  }

  // ===== Tela A =====
  if (screen === "A") {
    return (
      <div data-testid="cto-inline-screen-a">
        {/* Mapa GPS — mesmo CTOMapPicker do wizard original */}
        <div style={{ borderRadius: 14, overflow: "hidden",
                        border: `1px solid ${C_BORDER}`, marginBottom: 10,
                        height: 280 }}>
          <CTOMapPicker
            collabId={collabId}
            onSelectExistingCto={onSelectExistingCto}
            onMove={({ lat, lng, address: a }) => {
              setState((s) => ({
                ...s,
                gps: { lat, lng, accuracy: null },
                address: {
                  ...(s.address || {}),
                  endereco: a.road || a.pedestrian || a.cycleway
                              || s.address?.endereco || "",
                  numero: a.house_number || s.address?.numero || "",
                  // Fallback agressivo de bairro: OSM varia bastante nesse campo.
                  bairro_detected: a.suburb
                                    || a.neighbourhood
                                    || a.quarter
                                    || a.city_district
                                    || a.residential
                                    || a.borough
                                    || a.hamlet
                                    || a.village
                                    || "",
                  cidade_detected: a.city || a.town || a.municipality || "",
                  estado_detected: a.state || "",
                  cep: a.postcode || s.address?.cep || "",
                },
              }));
              setErr("");
            }}
            onError={(m) => setErr(m)}
          />
        </div>

        {/* Card visual "Endereço detectado" — substitui os inputs avulsos
            com layout mais polido (ícones + linhas formatadas) */}
        <div data-testid="cto-inline-address-card" style={{
          marginTop: 4, padding: 12, borderRadius: 12,
          background: "linear-gradient(135deg,#f8fafc 0%,#ecfdf5 100%)",
          border: "1px solid #bbf7d0",
        }}>
          <div style={{ display: "flex", alignItems: "center",
                            justifyContent: "space-between", marginBottom: 8 }}>
            <div style={{ fontSize: 10, fontWeight: 800,
                              color: "#065f46", letterSpacing: 0.5,
                              textTransform: "uppercase" }}>
              📍 Endereço da CTO {state.address?.endereco
                ? "· detectado por GPS" : "· aguardando GPS"}
            </div>
          </div>

          <label style={labelStyle}>Logradouro</label>
          <input data-testid="cto-inline-rua" style={inputBase}
                  value={state.address?.endereco || ""}
                  onChange={(e) => setState((s) => ({
                    ...s, address: { ...(s.address || {}),
                                        endereco: e.target.value } }))}
                  placeholder="Detectado pelo mapa" />

          <div style={{ display: "grid", gap: 10, marginTop: 6,
                            gridTemplateColumns: "1fr 1.5fr" }}>
            <div>
              <label style={labelStyle}>
                Número {state.address?.numero
                  ? <span style={{ color: "#065f46" }}>· GPS ✓</span>
                  : <span style={{ color: "#dc2626" }}>· digite</span>}
              </label>
              <input data-testid="cto-inline-numero" style={inputBase}
                      value={state.address?.numero || ""}
                      onChange={(e) => setState((s) => ({
                        ...s, address: { ...(s.address || {}),
                                            numero: e.target.value } }))}
                      placeholder="—" inputMode="numeric" />
            </div>
            <div>
              <label style={labelStyle}>
                Bairro {state.address?.bairro_detected
                  ? <span style={{ color: "#065f46" }}>· GPS ✓</span>
                  : <span style={{ color: "#dc2626" }}>· digite</span>}
              </label>
              <input data-testid="cto-inline-bairro" style={inputBase}
                      value={state.address?.bairro_detected || ""}
                      onChange={(e) => setState((s) => ({
                        ...s, address: { ...(s.address || {}),
                                            bairro_detected: e.target.value } }))}
                      placeholder="Ex.: Centro" />
            </div>
          </div>

          {state.address?.cidade_detected && (
            <div style={{
              marginTop: 8, padding: "6px 10px", borderRadius: 8,
              background: "rgba(16,185,129,0.08)",
              border: "1px solid rgba(16,185,129,0.25)",
              fontSize: 11, color: "#065f46", lineHeight: 1.5,
              display: "flex", alignItems: "center", gap: 8,
            }}>
              <span style={{ fontSize: 14 }}>🌆</span>
              <span>
                <strong>{state.address.cidade_detected}</strong>
                {state.address?.estado_detected
                  ? ` · ${state.address.estado_detected}` : ""}
                {state.address?.cep ? ` · CEP ${state.address.cep}` : ""}
              </span>
            </div>
          )}
        </div>

        {/* Foto — OBRIGATÓRIA */}
        <input ref={fileInputRef} type="file" accept="image/*" capture="environment"
                onChange={onPhotoChange} style={{ display: "none" }}
                data-testid="cto-inline-photo-input" />
        {state.photo && (
          <>
            <label style={labelStyle}>
              Foto da CTO <span style={{ color: "#15803d" }}>✓</span>
            </label>
            <div style={{ position: "relative", borderRadius: 12, overflow: "hidden",
                            border: `1.5px solid #22c55e`, marginBottom: 6 }}>
              <img src={state.photo} alt="Foto CTO"
                    data-testid="cto-inline-photo-preview"
                    style={{ width: "100%", display: "block",
                              maxHeight: 200, objectFit: "cover" }} />
              <button data-testid="cto-inline-photo-remove"
                      onClick={() => setState((s) => ({ ...s, photo: null }))}
                      style={{ position: "absolute", top: 8, right: 8,
                                background: "rgba(0,0,0,0.6)", color: "#fff",
                                border: 0, borderRadius: "50%", width: 28, height: 28,
                                fontSize: 14, fontWeight: 800, cursor: "pointer" }}>×</button>
            </div>
          </>
        )}

        {/* VLAN */}
        <label style={labelStyle}>VLAN (número de 1 a 4094)</label>
        <input data-testid="cto-inline-vlan" style={inputBase}
                value={state.vlan || ""}
                onChange={(e) => setState((s) => ({ ...s, vlan: e.target.value.replace(/[^0-9]/g, "") }))}
                placeholder="Ex.: 313" inputMode="numeric" />

        {err && (
          <div data-testid="cto-inline-err" style={{
            marginTop: 10, padding: 10, borderRadius: 8,
            background: "#fee2e2", color: "#991b1b", fontSize: 12,
          }}>⚠ {err}</div>
        )}

        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <button data-testid="cto-inline-continue-from-a"
                  onClick={() => {
                    if (!state.gps?.lat || !state.gps?.lng) {
                      setErr("Posicione o pino no mapa antes de continuar."); return;
                    }
                    if (!state.address?.endereco) {
                      setErr("Endereço não detectado. Mova o pino até a rua."); return;
                    }
                    if (!state.vlan && !isFullUnlock) {
                      setErr("Informe a VLAN."); return;
                    }
                    if (!state.photo && !isFullUnlock && ctoPhotoRequired) {
                      // Abre câmera; o handler onPhotoChange salva no state.
                      // O técnico clica Continuar novamente após capturar.
                      fileInputRef.current?.click();
                      return;
                    }
                    setErr("");
                    onAdvanceFromA?.();
                  }}
                  style={{ flex: 2, padding: "14px 14px", borderRadius: 10,
                            background: (state.photo || isFullUnlock || !ctoPhotoRequired) ? C_PRIMARY : "#0f172a",
                            border: 0,
                            color: "#fff", fontWeight: 700, fontSize: 14,
                            cursor: "pointer" }}>
            {(state.photo || isFullUnlock || !ctoPhotoRequired) ? "Continuar →" : "📸 Tirar foto da CTO e continuar →"}
          </button>
        </div>
      </div>
    );
  }

  // ===== Tela B =====
  const isExistingMode = !!state.existingCtoId;
  return (
    <div data-testid="cto-inline-screen-b">

      {/* Foto OBRIGATÓRIA também no modo CTO existente — exceto Modo Teste
          iter211am — respeita toggle global cto_photo_required */}
      {isExistingMode && !isFullUnlock && ctoPhotoRequired && (
        <>
          <label style={{ ...labelStyle, marginTop: 4 }}>
            Foto da CTO <span style={{ color: "#dc2626" }}>*</span>
          </label>
          <input ref={fileInputRef} type="file" accept="image/*" capture="environment"
                  onChange={onPhotoChange} style={{ display: "none" }}
                  data-testid="cto-inline-photo-input-b" />
          {state.photo ? (
            <div style={{ position: "relative", borderRadius: 12, overflow: "hidden",
                            border: `1.5px solid #22c55e`, marginBottom: 10 }}>
              <img src={state.photo} alt="Foto CTO"
                    style={{ width: "100%", display: "block",
                              maxHeight: 180, objectFit: "cover" }} />
              <div style={{ position: "absolute", top: 8, left: 8,
                              background: "#15803d", color: "#fff",
                              padding: "2px 8px", borderRadius: 999,
                              fontSize: 10, fontWeight: 800 }}>
                ✓ Foto registrada
              </div>
              <button onClick={() => setState((s) => ({ ...s, photo: null }))}
                      style={{ position: "absolute", top: 8, right: 8,
                                background: "rgba(0,0,0,0.6)", color: "#fff",
                                border: 0, borderRadius: "50%", width: 28, height: 28,
                                fontSize: 14, fontWeight: 800, cursor: "pointer" }}>×</button>
            </div>
          ) : (
            <button data-testid="cto-inline-photo-btn-b"
                    onClick={() => fileInputRef.current?.click()}
                    style={{ ...inputBase, display: "flex", alignItems: "center",
                              justifyContent: "space-between", cursor: "pointer",
                              padding: "14px 14px", marginBottom: 10,
                              border: "1.5px dashed #dc2626",
                              background: "#fef2f2" }}>
              <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ fontSize: 20 }}>📷</span>
                <span style={{ color: "#991b1b", fontWeight: 700 }}>
                  Tirar foto da CTO (obrigatório)
                </span>
              </span>
              <span style={{ color: "#dc2626", fontSize: 20 }}>›</span>
            </button>
          )}
        </>
      )}

      {/* iter211au — Quando a CTO já está cadastrada, NÃO mostramos
          os campos "Quantas portas", "Rede", "Splitter" e nem o "Nº da CTO".
          Mostramos apenas um card com a NOMENCLATURA da CTO (CTO_VLAN_NÚMERO)
          e a porta a selecionar. Toda info de capacity/rede/splitter já vem
          do cadastro da CTO (puxada no state via LousaMobile linha 3060+).
          O card abaixo aparece SÓ no modo existente. */}
      {isExistingMode && (
        <div data-testid="cto-inline-existing-summary" style={{
          marginBottom: 12, padding: "12px 14px", borderRadius: 12,
          background: "linear-gradient(135deg,#ecfdf5,#d1fae5)",
          border: "1px solid #6ee7b7",
        }}>
          <div style={{ fontSize: 10, color: "#065f46", fontWeight: 800,
                          textTransform: "uppercase", letterSpacing: 0.6,
                          marginBottom: 4 }}>
            ✓ CTO já cadastrada
          </div>
          <div style={{ fontSize: 18, fontWeight: 800, color: "#064e3b",
                          fontFamily: "monospace", letterSpacing: 1 }}>
            {state.ctoName
             || (state.vlan && state.ctoNumber
                  ? `CTO_${state.vlan}_${String(state.ctoNumber).padStart(4, "0")}`
                  : "—")}
          </div>
          <div style={{ fontSize: 11, color: "#047857", marginTop: 4 }}>
            {state.capacity ? `${state.capacity} portas` : ""}
            {state.capacity && state.networkType ? " · " : ""}
            {state.networkType === "balanceada" ? "Rede balanceada"
              : state.networkType === "desbalanceada" ? "Rede desbalanceada"
              : ""}
            {state.splitter ? ` · Splitter ${state.splitter}` : ""}
          </div>
        </div>
      )}

      {/* Nº da CTO — só aparece pra CADASTRO de CTO nova
          (modo existente já mostra a nomenclatura no card acima) */}
      {!isExistingMode && (
        <>
          <label style={{ ...labelStyle, marginTop: 4 }}>
            Nº da CTO <span style={{ color: "#dc2626" }}>*</span>
          </label>
          <input
            type="number"
            inputMode="numeric"
            min="1" max="9999"
            required
            data-testid="cto-inline-number-input"
            value={state.ctoNumber || ""}
            placeholder="Digite o número (ex: 27)"
            onChange={(e) => setState((s) => ({ ...s,
                ctoNumber: e.target.value.replace(/\D/g, "") }))}
            style={{
              width: "100%", padding: "12px 14px", borderRadius: 10,
              border: `1.5px solid ${C_BORDER}`, fontSize: 15,
              boxSizing: "border-box", marginBottom: 10,
            }}
          />
        </>
      )}

      {/* iter211au — "Quantas portas", "Rede (Bal/Des)" e "Splitter"
          escondidos no modo CTO existente: dados já cadastrados, técnico
          não precisa re-confirmar nada. */}
      {!isExistingMode && (
        <>
      <label style={{ ...labelStyle, marginTop: 4 }}>
        Quantas portas tem a CTO?
      </label>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
                      gap: 8, marginBottom: 6 }}>
        {[4, 8, 16].map((cap) => (
          <button key={cap} data-testid={`cto-inline-cap-${cap}`}
                  onClick={() => setState((s) => ({ ...s, capacity: cap,
                                                     clientPort: (s.clientPort && s.clientPort <= cap) ? s.clientPort : null }))}
                  style={{ padding: "16px 0", borderRadius: 10,
                            border: `1.5px solid ${state.capacity === cap ? C_PRIMARY : C_BORDER}`,
                            background: state.capacity === cap ? C_PRIMARY_LIGHT : "#fff",
                            color: C_TEXT, fontSize: 16, fontWeight: 700,
                            cursor: "pointer" }}>
            {cap} portas
          </button>
        ))}
      </div>

      {/* Tipo de rede */}
      <label style={{ ...labelStyle }}>
        Rede (Bal/Des)
      </label>
      {[
        { v: "balanceada", l: "Rede balanceada", d: "Sinal igual em todas as portas", icon: "⚖️" },
        { v: "desbalanceada", l: "Rede desbalanceada", d: "Sinal varia por porta (splitter)", icon: "⚙️" },
      ].map((opt) => (
        <button key={opt.v} data-testid={`cto-inline-net-${opt.v.slice(0,3)}`}
                onClick={() => setState((s) => ({ ...s, networkType: opt.v,
                                                   splitter: null }))}
                style={{ ...optionCard(state.networkType === opt.v),
                          alignItems: "flex-start",
                          cursor: "pointer" }}>
          <span style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
            <span style={{ width: 32, height: 32, borderRadius: 8,
                            background: state.networkType === opt.v ? "#ddd6fe" : "#f1f5f9",
                            display: "grid", placeItems: "center", fontSize: 16,
                            flexShrink: 0 }}>{opt.icon}</span>
            <span>
              <div style={{ fontSize: 13, fontWeight: 700 }}>{opt.l}</div>
              <div style={{ fontSize: 10, color: C_MUTED, marginTop: 2,
                              lineHeight: 1.3 }}>{opt.d}</div>
            </span>
          </span>
          <span style={checkBox(state.networkType === opt.v)}>
            {state.networkType === opt.v ? "✓" : ""}
          </span>
        </button>
      ))}

      {/* Splitter — opções dependem do tipo de rede:
          • balanceada: 1:2, 1:4, 1:8, 1:16
          • desbalanceada: 5/95, 10/90, 20/80, 35/65, 50/50
          Em ambos: "Outro" e "Sem splitter".  (iter211ar)
          iter211au — Só aparece pra CADASTRO de CTO nova. */}
      {!isExistingMode && (state.networkType === "balanceada"
        || state.networkType === "desbalanceada") && (
        <>
          <label style={{ ...labelStyle }}>
            Splitter
          </label>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
                          gap: 6, marginBottom: 4 }}>
            {(() => {
              const balOpts = ["1:2", "1:4", "1:8", "1:16"];
              const desbOpts = ["5/95", "10/90", "20/80", "35/65", "50/50"];
              const opts = state.networkType === "balanceada" ? balOpts : desbOpts;
              return [...opts, "Outro", "Sem splitter"];
            })().map((s) => (
              <button key={s} data-testid={`cto-inline-spl-${s.replace(/[^a-z0-9]/gi,'_')}`}
                      onClick={() => setState((st) => ({ ...st, splitter: s }))}
                      style={{ padding: "10px 0", borderRadius: 8,
                                border: `1.5px solid ${state.splitter === s ? C_PRIMARY : C_BORDER}`,
                                background: state.splitter === s ? C_PRIMARY_LIGHT : "#fff",
                                color: C_TEXT, fontSize: 13, fontWeight: 700,
                                cursor: "pointer" }}>
                {s}
              </button>
            ))}
          </div>
        </>
      )}
        </>
      )}
      {/* /iter211au — fecha o wrapper "!isExistingMode" iniciado antes
          de "Quantas portas". A partir daqui o conteúdo aparece em AMBOS
          os modos (criação e CTO existente). */}

      {/* Porta do cliente */}
      {state.capacity && (
        <>
          <label style={{ ...labelStyle }}>Porta do cliente</label>
          {/* iter211as — Legenda visual de status. Antes só tinha cor
              cinza/branca, técnico não sabia que o cinza = em uso. */}
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
                          marginBottom: 8, fontSize: 11, color: "#475569" }}>
            <span style={legendItem}>
              <span style={{ ...legendDot, background: "#fff",
                              border: "1.5px solid #cbd5e1" }} /> Livre
            </span>
            <span style={legendItem}>
              <span style={{ ...legendDot, background: "#334155" }} /> Em uso (outro cliente)
            </span>
            <span style={legendItem}>
              <span style={{ ...legendDot, background: "#ccfbf1",
                              border: "1.5px solid #0d9488" }} /> Cliente atual
            </span>
          </div>
          <div style={{ display: "grid",
                          gridTemplateColumns: `repeat(${Math.min(state.capacity, 4)}, 1fr)`,
                          gap: 8, marginBottom: 6 }}>
            {Array.from({ length: state.capacity }, (_, i) => i + 1).map((p) => {
              const portInfo = (state.existingPorts || []).find((x) => x.number === p);
              const used = portInfo && portInfo.status !== "free";
              // iter211as — É o mesmo cliente? Se sim, libera reuso da porta.
              const sameClient = used && client?.id
                && portInfo.client_subscriber_id === client.id;
              // Marca a porta atual do cliente (vinda de outra CTO ou da mesma)
              const isClientCurrent = sameClient || (clientCurrentPort
                                       && clientCurrentPort.port_number === p
                                       && (state.existingCtoId === clientCurrentPort.cto_id
                                            || !state.existingCtoId));
              return (
                <button key={p} data-testid={`cto-inline-port-${p}`}
                        disabled={used && !isClientCurrent}
                        title={used && !isClientCurrent
                          ? `Porta ${p} está em uso por outro cliente. Selecione uma porta livre.`
                          : used && isClientCurrent
                          ? `Porta ${p} é a porta atual deste cliente.`
                          : `Porta ${p} — livre`}
                        onClick={() => {
                          // iter211as — Mesma porta + mesmo cliente: aceita
                          // sem confirmação (caso o cliente esteja sendo
                          // reconfirmado/refaturado no mesmo ponto físico).
                          if (used && isClientCurrent) {
                            setState((s) => ({ ...s, clientPort: p }));
                            return;
                          }
                          // Se o cliente já tem porta nesta CTO e o técnico
                          // escolheu uma porta DIFERENTE, abre o diálogo de
                          // confirmação de troca.
                          if (clientCurrentPort
                              && state.existingCtoId === clientCurrentPort.cto_id
                              && clientCurrentPort.port_number !== p) {
                            setSwapTargetPort(p);
                            setShowSwapDialog(true);
                            return;
                          }
                          setState((s) => ({ ...s, clientPort: p }));
                        }}
                        style={{ padding: "14px 0", borderRadius: 10,
                                  border: `2px solid ${state.clientPort === p
                                      ? C_PRIMARY
                                      : isClientCurrent ? "#0d9488"
                                      : used ? "#475569" : C_BORDER}`,
                                  background: state.clientPort === p
                                      ? C_PRIMARY
                                      : isClientCurrent ? "#ccfbf1"
                                      : used ? "#334155" : "#fff",
                                  color: state.clientPort === p ? "#fff"
                                      : isClientCurrent ? "#0f766e"
                                      : used ? "#fff" : C_TEXT,
                                  fontSize: 16, fontWeight: 700,
                                  cursor: used && !isClientCurrent ? "not-allowed" : "pointer",
                                  position: "relative",
                                  opacity: used && !isClientCurrent ? 0.95 : 1 }}>
                  {p}
                  {used && !isClientCurrent && (
                    <span style={{ position: "absolute", bottom: 2, left: 0, right: 0,
                                    fontSize: 8, fontWeight: 800,
                                    color: "#cbd5e1", letterSpacing: 0.3 }}>
                      EM USO
                    </span>
                  )}
                  {isClientCurrent && (
                    <span style={{ position: "absolute", bottom: 2, left: 0, right: 0,
                                    fontSize: 8, fontWeight: 800,
                                    color: "#0f766e" }}>
                      {sameClient ? "ESTE CLIENTE" : "ATUAL"}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          {state.clientPort && (
            <div style={{
              padding: "10px 12px", borderRadius: 8,
              background: "#f0fdf4", color: "#15803d", fontSize: 12,
              border: "1px solid #86efac", marginTop: 4,
              display: "flex", alignItems: "center", gap: 8,
            }}>
              <span>✓</span>
              <span>Porta <strong>{state.clientPort}</strong> · {client?.name || "cliente atual"} será vinculado aqui</span>
            </div>
          )}
        </>
      )}

      {err && (
        <div data-testid="cto-inline-err-b" style={{
          marginTop: 10, padding: 10, borderRadius: 8,
          background: "#fee2e2", color: "#991b1b", fontSize: 12,
        }}>⚠ {err}</div>
      )}

      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <button data-testid="cto-inline-back-from-b"
                onClick={onBackFromB} disabled={busy}
                style={{ flex: 1, padding: "12px 14px", borderRadius: 10,
                          background: "#fff", border: `1px solid ${C_BORDER}`,
                          color: C_MUTED, fontWeight: 600, fontSize: 13,
                          cursor: busy ? "wait" : "pointer", opacity: busy ? 0.6 : 1 }}>
          ← Voltar
        </button>
        <button data-testid="cto-inline-submit"
                onClick={submitCreate} disabled={busy}
                style={{ flex: 2, padding: "12px 14px", borderRadius: 10,
                          background: "#0f766e", border: 0,
                          color: "#fff", fontWeight: 700, fontSize: 14,
                          cursor: busy ? "wait" : "pointer", opacity: busy ? 0.7 : 1 }}>
          {busy ? "Salvando..."
            : isExistingMode
              ? "✓ Vincular cliente à porta"
              : "✓ Criar CTO e vincular cliente"}
        </button>
      </div>

      {/* Dialog: Troca de porta (cliente já cadastrado em outra porta da MESMA CTO) */}
      {showSwapDialog && clientCurrentPort && swapTargetPort && (
        <div data-testid="port-swap-dialog"
              onClick={() => !swapBusy && setShowSwapDialog(false)}
              style={{
                position: "fixed", inset: 0, zIndex: 9999,
                background: "rgba(15,23,42,0.65)",
                display: "grid", placeItems: "center", padding: 16,
              }}>
          <div onClick={(e) => e.stopPropagation()}
                style={{
                  background: "white", borderRadius: 14, padding: 20,
                  maxWidth: 360, width: "100%",
                  boxShadow: "0 20px 50px rgba(15,23,42,.4)",
                }}>
            <div style={{ fontSize: 28, textAlign: "center", marginBottom: 8 }}>
              🔄
            </div>
            <h3 style={{ margin: 0, fontSize: 17, fontWeight: 800,
                            color: "#0f172a", textAlign: "center",
                            marginBottom: 8 }}>
              Trocar porta do cliente?
            </h3>
            <p style={{ fontSize: 13, color: "#475569", textAlign: "center",
                          lineHeight: 1.5, marginBottom: 14 }}>
              <strong>{client?.name || "Este cliente"}</strong> já está
              cadastrado na porta{" "}
              <strong style={{ color: "#0f766e" }}>
                {clientCurrentPort.port_number}
              </strong>{" "}
              desta CTO. Deseja trocar para a porta{" "}
              <strong style={{ color: "#0f172a" }}>{swapTargetPort}</strong>?
            </p>

            {clientCurrentPort.from_smartolt && (
              <div style={{
                padding: "8px 10px", background: "#eff6ff",
                border: "1px solid #93c5fd", borderRadius: 8,
                fontSize: 11, color: "#1e40af", marginBottom: 14,
                lineHeight: 1.4,
              }}>
                ℹ️ Esse cadastro veio do SmartOLT — a porta também será
                atualizada lá.
              </div>
            )}

            <div style={{ display: "flex", gap: 8 }}>
              <button data-testid="port-swap-cancel"
                       disabled={swapBusy}
                       onClick={() => { setShowSwapDialog(false);
                                            setSwapTargetPort(null); }}
                       style={{
                         flex: 1, padding: "12px 14px", borderRadius: 10,
                         background: "#fff", border: "1px solid #cbd5e1",
                         color: "#475569", fontWeight: 600, fontSize: 13,
                         cursor: swapBusy ? "wait" : "pointer",
                       }}>
                ← Não trocar
              </button>
              <button data-testid="port-swap-confirm"
                       disabled={swapBusy}
                       onClick={async () => {
                         setSwapBusy(true); setErr("");
                         try {
                           const r = await api.redeIaSwapClientPort(
                             collabId, {
                               subscriber_id: client?.id,
                               cto_id: clientCurrentPort.cto_id,
                               new_port: swapTargetPort,
                             });
                           // Atualiza UI: clientPort = nova porta, current_port
                           // muda pra refletir o novo estado.
                           setState((s) => ({ ...s, clientPort: swapTargetPort }));
                           setClientCurrentPort({
                             ...clientCurrentPort,
                             port_number: swapTargetPort,
                           });
                           setShowSwapDialog(false);
                           setSwapTargetPort(null);
                           if (r?.from_smartolt && !r?.smartolt_synced) {
                             setErr("Porta trocada localmente, mas SmartOLT não sincronizou. Gestor pode confirmar manual.");
                           }
                         } catch (e) {
                           setErr(e?.response?.data?.detail
                                     || e.message || "Falha na troca.");
                         } finally { setSwapBusy(false); }
                       }}
                       style={{
                         flex: 2, padding: "12px 14px", borderRadius: 10,
                         background: "#0f766e", border: 0,
                         color: "#fff", fontWeight: 700, fontSize: 13,
                         cursor: swapBusy ? "wait" : "pointer",
                         opacity: swapBusy ? 0.7 : 1,
                       }}>
                {swapBusy ? "Trocando..."
                  : `✓ Trocar para porta ${swapTargetPort}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// iter211as — estilos da legenda do grid de portas
const legendItem = {
  display: "inline-flex", alignItems: "center", gap: 5,
};
const legendDot = {
  display: "inline-block", width: 10, height: 10, borderRadius: 3,
};

