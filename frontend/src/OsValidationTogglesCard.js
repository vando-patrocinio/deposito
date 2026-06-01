/* OsValidationTogglesCard — admin liga/desliga travas no fluxo de
   finalização da OS (Lousa).

   Toggle disponível:
     • Teste IPv6 obrigatório (default: desligado, iter155)

   Backend: GET/PUT /api/settings/os-validation-toggles
*/
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";

const labels = {
  ipv6_test_required: {
    title: "Teste IPv6 obrigatório",
    desc: "Quando ligado, o técnico precisa concluir o Teste IPv6 (Google "
        + "DNS + dual-stack) antes de finalizar OS de instalação, reparo, "
        + "troca, troca de endereço ou ponto adicional. Desligado por padrão.",
    icon: "🌐",
  },
  cto_photo_required: {
    title: "Foto da CTO obrigatória",
    desc: "Quando ligado, o técnico DEVE anexar uma foto da CTO (kind=cto) "
        + "antes de finalizar OS de instalação, reparo, troca ou ponto "
        + "adicional. Bloqueia o botão Finalizar se a foto não estiver "
        + "presente. Desligado por padrão.",
    icon: "📸",
  },
  mac_validation_required: {
    title: "Validar MAC contra SmartOLT",
    desc: "Quando ligado, na instalação/troca o sistema bloqueia a baixa do "
        + "estoque se o MAC informado não bater com o MAC ativo do cliente "
        + "no cache SmartOLT (em vez de marcar como pendente). Use só em "
        + "ambientes com SmartOLT 100% sincronizado. Desligado por padrão.",
    icon: "🔒",
  },
};

const TOGGLE_KEYS = Object.keys(labels);

export default function OsValidationTogglesCard() {
  const [values, setValues] = useState({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setMsg(null);
    try {
      const r = await api._client.get("/settings/os-validation-toggles");
      setValues(r.data || {});
    } catch (e) {
      setMsg({ type: "err",
                  text: e?.response?.data?.detail || "Falha ao carregar" });
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggle = async (key) => {
    if (busy) return;
    setBusy(true); setMsg(null);
    const next = !values[key];
    // Otimismo local: troca instantânea
    setValues((v) => ({ ...v, [key]: next }));
    try {
      const r = await api._client.put("/settings/os-validation-toggles",
                                          { [key]: next });
      setValues(r.data || {});
      setMsg({ type: "ok", text: `${labels[key]?.title} ${next ? "LIGADO" : "DESLIGADO"}` });
      setTimeout(() => setMsg(null), 2500);
    } catch (e) {
      setValues((v) => ({ ...v, [key]: !next })); // rollback
      setMsg({ type: "err",
                  text: e?.response?.data?.detail || "Falha ao salvar" });
    } finally { setBusy(false); }
  };

  // iter167 — Wizard "Modo Rigoroso" / "Modo Relaxado": 1 clique aplica
  // o preset em todos os toggles simultaneamente.
  const applyPreset = async (preset) => {
    if (busy) return;
    const target = preset === "rigoroso";
    const payload = TOGGLE_KEYS.reduce((acc, k) => ({ ...acc, [k]: target }), {});
    if (!window.confirm(
      preset === "rigoroso"
        ? "Ativar MODO RIGOROSO?\n\nTodas as validações da OS serão LIGADAS:\n• Teste IPv6 obrigatório\n• Foto da CTO obrigatória\n• Validar MAC contra SmartOLT (estrito)\n\nIsso pode bloquear OSs que estavam passando antes."
        : "Ativar MODO RELAXADO?\n\nTodas as validações da OS serão DESLIGADAS. OSs passam sem trava."
    )) return;
    setBusy(true); setMsg(null);
    setValues((v) => ({ ...v, ...payload })); // otimismo
    try {
      const r = await api._client.put("/settings/os-validation-toggles", payload);
      setValues(r.data || {});
      setMsg({ type: "ok",
                  text: preset === "rigoroso"
                    ? "Modo Rigoroso aplicado — todas as travas LIGADAS"
                    : "Modo Relaxado aplicado — todas as travas DESLIGADAS" });
      setTimeout(() => setMsg(null), 3500);
    } catch (e) {
      await load(); // rollback do servidor
      setMsg({ type: "err",
                  text: e?.response?.data?.detail || "Falha ao aplicar preset" });
    } finally { setBusy(false); }
  };

  return (
    <div data-testid="os-validation-toggles-card" style={{
      background: "#ffffff", borderRadius: 14,
      border: "1px solid #e2e8f0", padding: 18, marginBottom: 14,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                       marginBottom: 6 }}>
        <span style={{ fontSize: 22 }}>⚙️</span>
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800,
                         color: "#0f172a", letterSpacing: -0.2 }}>
          Validações da OS · Lousa
        </h3>
      </div>
      <p style={{ margin: "0 0 12px", fontSize: 12, color: "#64748b",
                     lineHeight: 1.5 }}>
        Liga/desliga travas obrigatórias durante a finalização da nota de
        serviço. Mudanças valem para toda a empresa.
      </p>

      {/* iter167 — Presets rápidos */}
      {(() => {
        const allOn = TOGGLE_KEYS.every((k) => values[k]);
        const allOff = TOGGLE_KEYS.every((k) => !values[k]);
        return (
          <div data-testid="os-toggles-presets" style={{
            display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap",
            padding: 10, background: "#f8fafc", borderRadius: 10,
            border: "1px solid #e2e8f0",
          }}>
            <div style={{ flex: "1 1 100%", fontSize: 11, fontWeight: 700,
                              color: "#64748b", textTransform: "uppercase",
                              letterSpacing: 0.5, marginBottom: 2 }}>
              ⚡ Presets rápidos
            </div>
            <button type="button" disabled={busy || loading || allOn}
                    onClick={() => applyPreset("rigoroso")}
                    data-testid="preset-rigoroso"
                    style={{
                      padding: "8px 14px", borderRadius: 8, border: 0,
                      background: allOn ? "#94a3b8" : "linear-gradient(135deg,#dc2626,#991b1b)",
                      color: "#fff", fontSize: 12, fontWeight: 700,
                      cursor: busy || allOn ? "default" : "pointer",
                      opacity: allOn ? 0.7 : 1,
                    }}>
              🔒 Modo Rigoroso {allOn && "(ativo)"}
            </button>
            <button type="button" disabled={busy || loading || allOff}
                    onClick={() => applyPreset("relaxado")}
                    data-testid="preset-relaxado"
                    style={{
                      padding: "8px 14px", borderRadius: 8, border: 0,
                      background: allOff ? "#94a3b8" : "linear-gradient(135deg,#16a34a,#166534)",
                      color: "#fff", fontSize: 12, fontWeight: 700,
                      cursor: busy || allOff ? "default" : "pointer",
                      opacity: allOff ? 0.7 : 1,
                    }}>
              🌿 Modo Relaxado {allOff && "(ativo)"}
            </button>
            <div style={{ flex: "1 1 100%", fontSize: 11, color: "#64748b",
                              lineHeight: 1.4, marginTop: 4 }}>
              <strong>Rigoroso</strong>: liga todas as travas (foto CTO, IPv6, MAC
              estrito) — qualidade máxima.
              {" • "}<strong>Relaxado</strong>: desliga tudo — fluxo mais rápido.
            </div>
          </div>
        );
      })()}

      {msg && (
        <div style={{
          padding: "8px 12px", borderRadius: 8, marginBottom: 12,
          fontSize: 12, fontWeight: 600,
          background: msg.type === "ok" ? "#dcfce7" : "#fee2e2",
          color: msg.type === "ok" ? "#166534" : "#991b1b",
          border: `1px solid ${msg.type === "ok" ? "#86efac" : "#fca5a5"}`,
        }}>{msg.text}</div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {TOGGLE_KEYS.map((k) => {
          const meta = labels[k];
          const on = !!values[k];
          return (
            <label key={k} data-testid={`os-toggle-${k}`}
                     style={{
                       display: "flex", alignItems: "flex-start", gap: 12,
                       padding: 12, borderRadius: 10,
                       border: `1.5px solid ${on ? "#16a34a" : "#e2e8f0"}`,
                       background: on ? "#f0fdf4" : "#f8fafc",
                       cursor: busy || loading ? "wait" : "pointer",
                       transition: "background .15s, border-color .15s",
                     }}>
              <div style={{ fontSize: 24, lineHeight: 1, flexShrink: 0,
                                marginTop: 1 }}>
                {meta.icon}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8,
                                  marginBottom: 3 }}>
                  <span style={{ fontSize: 13.5, fontWeight: 800,
                                    color: "#0f172a" }}>
                    {meta.title}
                  </span>
                  <span style={{
                    fontSize: 9, fontWeight: 800, letterSpacing: 0.5,
                    padding: "2px 6px", borderRadius: 4,
                    background: on ? "#16a34a" : "#94a3b8", color: "#fff",
                  }}>
                    {loading ? "..." : (on ? "LIGADO" : "DESLIGADO")}
                  </span>
                </div>
                <div style={{ fontSize: 11.5, color: "#64748b",
                                  lineHeight: 1.45 }}>
                  {meta.desc}
                </div>
              </div>
              {/* Switch visual */}
              <button
                type="button" disabled={busy || loading}
                onClick={() => toggle(k)}
                data-testid={`os-toggle-switch-${k}`}
                style={{
                  width: 44, height: 24, borderRadius: 999, border: 0,
                  background: on ? "#16a34a" : "#cbd5e1",
                  position: "relative", cursor: busy || loading ? "wait" : "pointer",
                  flexShrink: 0, marginTop: 4, padding: 0,
                  transition: "background .15s",
                }}>
                <span style={{
                  position: "absolute",
                  top: 2, left: on ? 22 : 2,
                  width: 20, height: 20, borderRadius: "50%",
                  background: "#fff",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
                  transition: "left .18s",
                }} />
              </button>
            </label>
          );
        })}
      </div>
    </div>
  );
}
