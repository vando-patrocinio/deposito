import React, { useState } from "react";
import { api } from "@/api";

const ACCENT = "#10b981";

/**
 * OnboardingWizard — exibido após signup novo (e antes do app principal).
 * 3 passos: cadastrar 1ª praça → 1º colaborador → "Tudo pronto".
 * Usuário pode pular qualquer passo.
 */
export default function OnboardingWizard({ user, onDone }) {
  const [step, setStep] = useState(1);

  // Praça
  const [pracaName, setPracaName] = useState("");
  const [pracaCity, setPracaCity] = useState("");
  const [pracaState, setPracaState] = useState("");
  const [pracaId, setPracaId] = useState(null);

  // Colab
  const [collabName, setCollabName] = useState("");
  const [collabCpf, setCollabCpf] = useState("");
  const [collabEmail, setCollabEmail] = useState("");
  const [collabPhone, setCollabPhone] = useState("");

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function savePraca() {
    setErr(""); setBusy(true);
    try {
      const p = await api.createPraca({
        name: pracaName.trim(),
        city: pracaCity.trim(),
        state: pracaState.trim().toUpperCase().slice(0, 2),
        full_address: null,
      });
      setPracaId(p.id);
      setStep(2);
    } catch (e) {
      const detail = e?.response?.data?.detail;
      setErr(typeof detail === "string" ? detail : (e.message || "Erro ao criar praça"));
    } finally {
      setBusy(false);
    }
  }

  async function saveCollab() {
    setErr(""); setBusy(true);
    try {
      await api.createCollaborator({
        name: collabName.trim(),
        cpf: collabCpf.trim(),
        email: collabEmail.trim().toLowerCase(),
        phone: collabPhone.trim(),
        role: "Colaborador de Campo",
        company: pracaName || "Operação",
        praca_id: pracaId || null,
        schedule: { entrada: "08:00", saida: "17:00", intervalo_inicio: "12:00", intervalo_fim: "13:00" },
      });
      setStep(3);
    } catch (e) {
      const detail = e?.response?.data?.detail;
      setErr(typeof detail === "string" ? detail : (e.message || "Erro ao criar colaborador"));
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    // Marca onboarding como concluído (localStorage — não impacta backend)
    try { localStorage.setItem("ponto_onboarding_done", "1"); } catch {}
    onDone?.();
  }

  function skipAll() {
    try { localStorage.setItem("ponto_onboarding_done", "1"); } catch {}
    onDone?.();
  }

  const inputStyle = {
    width: "100%", padding: "12px 14px", borderRadius: 12,
    border: "1px solid rgba(255,255,255,.1)",
    background: "rgba(255,255,255,.04)", color: "white",
    fontSize: 14, outline: "none", fontFamily: "inherit",
    boxSizing: "border-box",
  };
  const lbl = { display: "block", color: "#cbd5e1", fontSize: 11, fontWeight: 700, marginBottom: 6, letterSpacing: "0.04em", textTransform: "uppercase" };

  return (
    <div data-testid="onboarding-wizard" style={{
      minHeight: "100vh",
      background: "radial-gradient(ellipse 80% 60% at 50% -20%, rgba(16,185,129,.12) 0%, #0a1322 55%, #050b16 100%)",
      color: "#e2e8f0", fontFamily: "'Inter', system-ui, sans-serif",
      padding: "40px 22px",
    }}>
      <div style={{ maxWidth: 540, margin: "0 auto" }}>
        {/* Progress */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 32, justifyContent: "center" }}>
          {[1, 2, 3].map((n) => (
            <React.Fragment key={n}>
              <div style={{
                width: 32, height: 32, borderRadius: "50%",
                background: step >= n ? ACCENT : "rgba(255,255,255,.08)",
                color: step >= n ? "#050b16" : "#64748b",
                display: "grid", placeItems: "center", fontWeight: 900, fontSize: 13,
                transition: "all .25s",
              }}>{step > n ? "✓" : n}</div>
              {n < 3 && <div style={{ width: 40, height: 2, background: step > n ? ACCENT : "rgba(255,255,255,.08)", transition: "all .25s" }} />}
            </React.Fragment>
          ))}
        </div>

        <div style={{
          background: "rgba(255,255,255,.03)",
          border: "1px solid rgba(255,255,255,.08)",
          borderRadius: 22, padding: 32, backdropFilter: "blur(8px)",
        }}>
          {step === 1 && (
            <div data-testid="wizard-step-praca">
              <div style={{ fontSize: 11, color: "#34d399", fontWeight: 700, letterSpacing: "0.06em" }}>PASSO 1 DE 3</div>
              <h2 style={{ margin: "8px 0 6px", color: "white", fontSize: 24, fontWeight: 800 }}>Sua primeira praça</h2>
              <p style={{ color: "#94a3b8", fontSize: 13.5, lineHeight: 1.5, marginTop: 0 }}>
                Cadastre a cidade onde sua equipe vai operar. A IA descobre os feriados automaticamente.
              </p>

              {err && <div style={{ background: "rgba(239,68,68,.1)", border: "1px solid rgba(239,68,68,.3)", color: "#fca5a5", padding: 10, borderRadius: 10, fontSize: 13, marginBottom: 14 }}>{err}</div>}

              <div style={{ marginBottom: 14 }}>
                <label style={lbl}>Nome da praça *</label>
                <input data-testid="wizard-praca-name" type="text" value={pracaName} onChange={(e) => setPracaName(e.target.value)} placeholder="Ex.: SP Centro" style={inputStyle} />
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 10, marginBottom: 18 }}>
                <div>
                  <label style={lbl}>Cidade *</label>
                  <input data-testid="wizard-praca-city" type="text" value={pracaCity} onChange={(e) => setPracaCity(e.target.value)} placeholder="São Paulo" style={inputStyle} />
                </div>
                <div>
                  <label style={lbl}>UF *</label>
                  <input data-testid="wizard-praca-state" type="text" value={pracaState} onChange={(e) => setPracaState(e.target.value.toUpperCase().slice(0, 2))} placeholder="SP" maxLength={2} style={inputStyle} />
                </div>
              </div>

              <button
                onClick={savePraca}
                disabled={busy || !pracaName || !pracaCity || !pracaState}
                data-testid="wizard-praca-next"
                style={{
                  width: "100%", padding: "13px 18px", borderRadius: 12, border: 0,
                  background: ACCENT, color: "#050b16", fontWeight: 800, fontSize: 14,
                  cursor: busy ? "wait" : "pointer", opacity: busy ? 0.7 : 1,
                }}
              >{busy ? "Salvando..." : "Próximo: cadastrar colaborador →"}</button>
              <button
                onClick={() => setStep(2)}
                data-testid="wizard-praca-skip"
                style={{ width: "100%", marginTop: 8, padding: 10, background: "transparent", color: "#94a3b8", border: 0, fontSize: 12, cursor: "pointer" }}
              >Pular este passo</button>
            </div>
          )}

          {step === 2 && (
            <div data-testid="wizard-step-collab">
              <div style={{ fontSize: 11, color: "#34d399", fontWeight: 700, letterSpacing: "0.06em" }}>PASSO 2 DE 3</div>
              <h2 style={{ margin: "8px 0 6px", color: "white", fontSize: 24, fontWeight: 800 }}>Seu primeiro colaborador</h2>
              <p style={{ color: "#94a3b8", fontSize: 13.5, lineHeight: 1.5, marginTop: 0 }}>
                Adicione 1 pessoa pra começar. Você cadastra a foto de referência depois, em Cadastro.
              </p>

              {err && <div style={{ background: "rgba(239,68,68,.1)", border: "1px solid rgba(239,68,68,.3)", color: "#fca5a5", padding: 10, borderRadius: 10, fontSize: 13, marginBottom: 14 }}>{err}</div>}

              <div style={{ marginBottom: 14 }}>
                <label style={lbl}>Nome completo *</label>
                <input data-testid="wizard-collab-name" type="text" value={collabName} onChange={(e) => setCollabName(e.target.value)} placeholder="Maria Silva" style={inputStyle} />
              </div>
              <div style={{ marginBottom: 14 }}>
                <label style={lbl}>CPF *</label>
                <input data-testid="wizard-collab-cpf" type="text" value={collabCpf} onChange={(e) => setCollabCpf(e.target.value)} placeholder="000.000.000-00" style={inputStyle} />
              </div>
              <div style={{ marginBottom: 14 }}>
                <label style={lbl}>Email</label>
                <input data-testid="wizard-collab-email" type="email" value={collabEmail} onChange={(e) => setCollabEmail(e.target.value)} placeholder="maria@empresa.com" style={inputStyle} />
              </div>
              <div style={{ marginBottom: 18 }}>
                <label style={lbl}>WhatsApp</label>
                <input data-testid="wizard-collab-phone" type="tel" value={collabPhone} onChange={(e) => setCollabPhone(e.target.value)} placeholder="(11) 99999-9999" style={inputStyle} />
              </div>

              <button
                onClick={saveCollab}
                disabled={busy || !collabName || !collabCpf}
                data-testid="wizard-collab-next"
                style={{
                  width: "100%", padding: "13px 18px", borderRadius: 12, border: 0,
                  background: ACCENT, color: "#050b16", fontWeight: 800, fontSize: 14,
                  cursor: busy ? "wait" : "pointer", opacity: busy ? 0.7 : 1,
                }}
              >{busy ? "Salvando..." : "Próximo: tudo pronto! →"}</button>
              <button
                onClick={() => setStep(3)}
                data-testid="wizard-collab-skip"
                style={{ width: "100%", marginTop: 8, padding: 10, background: "transparent", color: "#94a3b8", border: 0, fontSize: 12, cursor: "pointer" }}
              >Pular este passo</button>
            </div>
          )}

          {step === 3 && (
            <div data-testid="wizard-step-done" style={{ textAlign: "center" }}>
              <div style={{
                width: 76, height: 76, borderRadius: "50%", margin: "0 auto 20px",
                background: "linear-gradient(135deg,#10b981,#059669)",
                color: "white", fontSize: 36, fontWeight: 900,
                display: "grid", placeItems: "center",
                boxShadow: "0 18px 40px rgba(16,185,129,.4)",
              }}></div>
              <h2 style={{ margin: "0 0 8px", color: "white", fontSize: 28, fontWeight: 850, letterSpacing: "-0.02em" }}>Tudo pronto, {(user?.name || "gestor").split(" ")[0]}!</h2>
              <p style={{ color: "#94a3b8", fontSize: 14.5, lineHeight: 1.55, marginTop: 0 }}>
                Sua empresa está configurada. Agora é hora de:
              </p>

              <div style={{ display: "grid", gap: 10, margin: "22px 0", textAlign: "left" }}>
                {[
                  { ic: "", t: "Definir cercas virtuais", d: "Em Cadastro → editar colaborador → adicionar cerca por endereço" },
                  { ic: "", t: "Fazer foto de referência", d: "Em Cadastro → editar colaborador → tirar foto de cadastro" },
                  { ic: "", t: "Compartilhar o app", d: "Envie o link da página inicial para o time bater ponto pelo celular" },
                ].map((it, i) => (
                  <div key={i} style={{
                    display: "flex", gap: 12, alignItems: "flex-start",
                    padding: "12px 14px", borderRadius: 12,
                    background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.06)",
                  }}>
                    <div style={{ fontSize: 20 }}>{it.ic}</div>
                    <div style={{ flex: 1 }}>
                      <strong style={{ color: "white", fontSize: 13.5, display: "block" }}>{it.t}</strong>
                      <span style={{ color: "#94a3b8", fontSize: 12 }}>{it.d}</span>
                    </div>
                  </div>
                ))}
              </div>

              <button
                onClick={finish}
                data-testid="wizard-done-btn"
                style={{
                  width: "100%", padding: "14px 20px", borderRadius: 12, border: 0,
                  background: ACCENT, color: "#050b16", fontWeight: 800, fontSize: 14.5,
                  cursor: "pointer",
                  boxShadow: "0 14px 30px rgba(16,185,129,.35)",
                }}
              >Ir para o painel →</button>
            </div>
          )}
        </div>

        {step !== 3 && (
          <div style={{ textAlign: "center", marginTop: 18 }}>
            <button
              onClick={skipAll}
              data-testid="wizard-skip-all-btn"
              style={{ background: "transparent", color: "#64748b", border: 0, fontSize: 12, cursor: "pointer" }}
            >Pular tudo, ir direto pro painel</button>
          </div>
        )}
      </div>
    </div>
  );
}
