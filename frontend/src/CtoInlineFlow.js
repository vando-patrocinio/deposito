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
 */
export default function CtoInlineFlow({
  screen,
  state, setState,
  collabId, client, technician,
  onSkipFromA, onAdvanceFromA, onBackFromB, onCreated,
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const fileInputRef = useRef(null);

  // Sigla padrão do bairro detectado (fallback simples: 3 primeiras letras maiúsculas)
  const autoSigla = useMemo(() => {
    const b = (state?.address?.bairro_detected || "").trim();
    if (!b) return "";
    return b.replace(/[^A-Za-zÀ-ÿ]/g, "").toUpperCase().slice(0, 3);
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
        throw new Error("Bairro não detectado. Volte e ajuste o pino.");
      }
      if (!state.capacity) throw new Error("Selecione a quantidade de portas.");
      if (!state.networkType) throw new Error("Selecione o tipo de rede.");
      if (state.networkType === "desbalanceada" && !state.splitter) {
        throw new Error("Selecione o splitter (rede desbalanceada).");
      }
      if (!state.clientPort) throw new Error("Selecione a porta do cliente.");

      // Garante que o bairro está cadastrado (cria se não existir)
      await api.redeIaBairroEnsureFromFieldPublic(collabId, {
        bairro: state.address.bairro_detected,
        sigla: autoSigla,
        vlan,
        cidade: state.address.cidade_detected || "",
        estado: (state.address.estado_detected || "").toUpperCase(),
      }).catch(() => { /* já existe — ok */ });

      // Cria a CTO via endpoint público (auto-vincula cliente à porta)
      const splitterValue = state.networkType === "desbalanceada"
        ? state.splitter : (state.splitter && !state.splitter.startsWith("Sem")
            ? state.splitter : null);

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
        technician_id: technician?.id || collabId,
        technician_name: technician?.name || "",
        photo_data_url: state.photo || null,
      });

      onCreated?.({ cto: r, port_number: state.clientPort });
    } catch (e) {
      const d = e?.response?.data?.detail;
      setErr(typeof d === "string" ? d : (d?.msg || e.message || "Falha ao criar CTO."));
    } finally {
      setBusy(false);
    }
  }

  // ===== Tela A =====
  if (screen === "A") {
    return (
      <div data-testid="cto-inline-screen-a">
        <div style={{
          padding: "10px 12px", borderRadius: 12, marginBottom: 12,
          background: "#ecfdf5", border: "1px dashed #10b981",
          display: "flex", alignItems: "flex-start", gap: 10,
        }}>
          <span style={{ fontSize: 22 }}>📍</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 800, color: "#065f46" }}>
              Localização da CTO + Foto + VLAN
            </div>
            <div style={{ fontSize: 10, color: "#475569", marginTop: 2, lineHeight: 1.3 }}>
              Posicione o pino no mapa, tire uma foto e informe a VLAN.
              A IA vai vincular {client?.name ? <strong>{client.name}</strong> : "este cliente"}
              {" "}à porta escolhida na próxima tela.
            </div>
          </div>
        </div>

        {/* Mapa GPS — mesmo CTOMapPicker do wizard original */}
        <div style={{ borderRadius: 14, overflow: "hidden",
                        border: `1px solid ${C_BORDER}`, marginBottom: 10,
                        height: 280 }}>
          <CTOMapPicker
            collabId={collabId}
            onMove={({ lat, lng, address: a }) => {
              setState((s) => ({
                ...s,
                gps: { lat, lng, accuracy: null },
                address: {
                  ...(s.address || {}),
                  endereco: a.road || s.address?.endereco || "",
                  numero: a.house_number || s.address?.numero || "",
                  bairro_detected: a.suburb || "",
                  cidade_detected: a.city || "",
                  estado_detected: a.state || "",
                },
              }));
              setErr("");
            }}
            onError={(m) => setErr(m)}
          />
        </div>

        <label style={labelStyle}>Endereço (auto)</label>
        <input data-testid="cto-inline-rua" style={inputBase}
                value={state.address?.endereco || ""}
                onChange={(e) => setState((s) => ({
                  ...s, address: { ...(s.address || {}), endereco: e.target.value } }))}
                placeholder="Detectado pelo mapa" />

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div>
            <label style={labelStyle}>Número</label>
            <input data-testid="cto-inline-numero" style={inputBase}
                    value={state.address?.numero || ""}
                    onChange={(e) => setState((s) => ({
                      ...s, address: { ...(s.address || {}), numero: e.target.value } }))}
                    placeholder="—" />
          </div>
          <div>
            <label style={labelStyle}>Bairro (auto)</label>
            <input data-testid="cto-inline-bairro" style={{ ...inputBase, background: "#f8fafc" }}
                    value={state.address?.bairro_detected || ""} readOnly
                    placeholder="—" />
          </div>
        </div>

        {/* Foto */}
        <label style={labelStyle}>Foto da CTO (opcional)</label>
        <input ref={fileInputRef} type="file" accept="image/*" capture="environment"
                onChange={onPhotoChange} style={{ display: "none" }}
                data-testid="cto-inline-photo-input" />
        {state.photo ? (
          <div style={{ position: "relative", borderRadius: 12, overflow: "hidden",
                          border: `1.5px solid ${C_BORDER}`, marginBottom: 6 }}>
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
        ) : (
          <button data-testid="cto-inline-photo-btn"
                  onClick={() => fileInputRef.current?.click()}
                  style={{ ...inputBase, display: "flex", alignItems: "center",
                            justifyContent: "space-between", cursor: "pointer",
                            padding: "14px 14px" }}>
            <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 20 }}>📷</span>
              <span style={{ color: C_TEXT, fontWeight: 600 }}>Tirar foto da CTO</span>
            </span>
            <span style={{ color: C_MUTED, fontSize: 20 }}>›</span>
          </button>
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
          <button data-testid="cto-inline-skip-from-a"
                  onClick={onSkipFromA}
                  style={{ flex: 1, padding: "12px 14px", borderRadius: 10,
                            background: "#fff", border: `1px solid ${C_BORDER}`,
                            color: C_MUTED, fontWeight: 600, fontSize: 13,
                            cursor: "pointer" }}>
            Pular CTO →
          </button>
          <button data-testid="cto-inline-continue-from-a"
                  onClick={() => {
                    if (!state.gps?.lat || !state.gps?.lng) {
                      setErr("Posicione o pino no mapa antes de continuar."); return;
                    }
                    if (!state.address?.endereco) {
                      setErr("Endereço não detectado. Mova o pino até a rua."); return;
                    }
                    if (!state.vlan) {
                      setErr("Informe a VLAN."); return;
                    }
                    setErr("");
                    onAdvanceFromA?.();
                  }}
                  style={{ flex: 2, padding: "12px 14px", borderRadius: 10,
                            background: C_PRIMARY, border: 0,
                            color: "#fff", fontWeight: 700, fontSize: 14,
                            cursor: "pointer" }}>
            Continuar →
          </button>
        </div>
      </div>
    );
  }

  // ===== Tela B =====
  return (
    <div data-testid="cto-inline-screen-b">
      <div style={{
        padding: "10px 12px", borderRadius: 12, marginBottom: 12,
        background: "#ecfdf5", border: "1px dashed #10b981",
        display: "flex", alignItems: "flex-start", gap: 10,
      }}>
        <span style={{ fontSize: 22 }}>🔌</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 800, color: "#065f46" }}>
            Portas, tipo de rede e porta do cliente
          </div>
          <div style={{ fontSize: 10, color: "#475569", marginTop: 2, lineHeight: 1.3 }}>
            A IA vai criar a CTO + vincular {client?.name
                ? <strong>{client.name}</strong> : "o cliente"} à porta selecionada
            e atualizar o mapa Rede IA.
          </div>
        </div>
      </div>

      {/* Quantidade de portas */}
      <label style={{ ...labelStyle, marginTop: 4 }}>Quantas portas tem a CTO?</label>
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
      <label style={{ ...labelStyle }}>Rede (Bal/Des)</label>
      {[
        { v: "balanceada", l: "Rede balanceada", d: "Sinal igual em todas as portas", icon: "⚖️" },
        { v: "desbalanceada", l: "Rede desbalanceada", d: "Sinal varia por porta (splitter)", icon: "⚙️" },
      ].map((opt) => (
        <button key={opt.v} data-testid={`cto-inline-net-${opt.v.slice(0,3)}`}
                onClick={() => setState((s) => ({ ...s, networkType: opt.v,
                                                   splitter: opt.v === "balanceada" ? "Sem splitter / não informado" : null }))}
                style={{ ...optionCard(state.networkType === opt.v),
                          alignItems: "flex-start" }}>
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

      {/* Splitter (só se desbalanceada) */}
      {state.networkType === "desbalanceada" && (
        <>
          <label style={{ ...labelStyle }}>Splitter</label>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
                          gap: 6, marginBottom: 4 }}>
            {["1:2", "1:4", "1:8", "5/95", "10/90", "20/80", "35/65", "50/50", "Outro"].map((s) => (
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

      {/* Porta do cliente */}
      {state.capacity && (
        <>
          <label style={{ ...labelStyle }}>Porta do cliente</label>
          <div style={{ display: "grid",
                          gridTemplateColumns: `repeat(${Math.min(state.capacity, 4)}, 1fr)`,
                          gap: 8, marginBottom: 6 }}>
            {Array.from({ length: state.capacity }, (_, i) => i + 1).map((p) => (
              <button key={p} data-testid={`cto-inline-port-${p}`}
                      onClick={() => setState((s) => ({ ...s, clientPort: p }))}
                      style={{ padding: "14px 0", borderRadius: 10,
                                border: `2px solid ${state.clientPort === p ? C_PRIMARY : C_BORDER}`,
                                background: state.clientPort === p ? C_PRIMARY : "#fff",
                                color: state.clientPort === p ? "#fff" : C_TEXT,
                                fontSize: 16, fontWeight: 700, cursor: "pointer" }}>
                {p}
              </button>
            ))}
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
          {busy ? "Criando CTO..." : "✓ Criar CTO e vincular cliente"}
        </button>
      </div>
    </div>
  );
}
