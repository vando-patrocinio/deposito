/**
 * Onboarding Público — Captura de Documentos do Cliente
 *
 * Rota: /onboarding/:token
 *
 * Página enxuta (mobile-first) com 4 etapas:
 *  1. Comprovante de endereço  (overlay retangular)
 *  2. RG/CNH                    (overlay cartão)
 *  3. Selfie segurando documento (overlay oval estilo banco/ponto)
 *  4. E-mail + dia de vencimento
 *
 * Cada upload faz OCR no backend e pré-preenche o cadastro.
 * Não requer login — autenticação via token HMAC.
 */
import React, { useState, useEffect, useRef } from "react";
import axios from "axios";
import {
  Camera, Check, AlertCircle, Upload, RefreshCw, ChevronRight,
  FileText, IdCard, ScanFace, ShieldCheck, Sparkles,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL || "";

const STEPS = [
  { key: "address_proof", label: "Comprovante de endereço",
    icon: FileText, overlay: "rect" },
  { key: "id_document", label: "Documento (RG ou CNH)",
    icon: IdCard, overlay: "card" },
  { key: "selfie", label: "Selfie segurando o documento",
    icon: ScanFace, overlay: "oval" },
];

export default function OnboardingPage({ token: tokenProp }) {
  // Aceita token via prop (App.js custom router) ou via URL pathname
  const token = tokenProp || (typeof window !== "undefined"
    ? window.location.pathname.replace("/onboarding/", "")
    : "");
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [activeStep, setActiveStep] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [email, setEmail] = useState("");
  const [dueDay, setDueDay] = useState(10);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  // Carrega sessão
  useEffect(() => {
    (async () => {
      try {
        const r = await axios.get(`${API}/api/onboarding/public/${token}`);
        setSession(r.data);
        // Auto-pula pra próxima etapa pendente
        const next = STEPS.findIndex((s) => !r.data.uploaded?.[s.key]);
        if (next >= 0) setActiveStep(next);
        else setActiveStep(STEPS.length); // tudo upado, vai pro form
      } catch (e) {
        setErr(e?.response?.data?.detail || e.message
          || "Sessão inválida ou expirada");
      } finally {
        setLoading(false);
      }
    })();
  }, [token]);

  const reloadSession = async () => {
    try {
      const r = await axios.get(`${API}/api/onboarding/public/${token}`);
      setSession(r.data);
    } catch (e) { /* ignore */ }
  };

  const onCapture = async (file) => {
    if (!file || uploading) return;
    setUploading(true);
    setErr(null);
    try {
      const fd = new FormData();
      fd.append("file_kind", STEPS[activeStep].key);
      fd.append("file", file);
      await axios.post(
        `${API}/api/onboarding/public/${token}/upload`, fd,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      await reloadSession();
      // Avança automaticamente
      setTimeout(() => {
        if (activeStep < STEPS.length - 1) setActiveStep(activeStep + 1);
        else setActiveStep(STEPS.length);
      }, 600);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha no upload");
    } finally {
      setUploading(false);
    }
  };

  const onSubmit = async () => {
    if (submitting) return;
    if (!email.includes("@")) {
      setErr("E-mail inválido"); return;
    }
    setSubmitting(true);
    setErr(null);
    try {
      await axios.post(
        `${API}/api/onboarding/public/${token}/submit`,
        { email, due_day: dueDay },
      );
      setDone(true);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || "Falha ao finalizar");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <Shell><div style={loadingStyle}>
        <RefreshCw className="animate-spin" /> Validando seu link…
      </div></Shell>
    );
  }
  if (err && !session) {
    return (
      <Shell><div style={{ ...loadingStyle, color: "#dc2626" }}>
        <AlertCircle size={32} /><br /><br />
        <strong>Link inválido ou expirado</strong><br /><br />
        <span style={{ fontSize: 12, color: "#475569" }}>
          Entre em contato com a Isabella pra gerar um novo link.
        </span>
      </div></Shell>
    );
  }
  if (done) {
    return (
      <Shell>
        <div style={{ textAlign: "center", padding: 40 }}>
          <div style={{
            width: 72, height: 72, borderRadius: "50%",
            background: "linear-gradient(135deg,#0f766e,#14b8a6)",
            margin: "0 auto", display: "grid", placeItems: "center",
          }}>
            <Check size={36} color="white" strokeWidth={3} />
          </div>
          <h2 style={{ marginTop: 16, color: "#0f766e" }}>
            Tudo certo! 🚀
          </h2>
          <p style={{ color: "#475569", fontSize: 14, lineHeight: 1.6 }}>
            Recebemos seus documentos e nossa equipe vai validar tudo
            em instantes.
            <br /><br />
            <strong>Ligo Fibra — A Internet que te faz feliz! 🤩</strong>
          </p>
        </div>
      </Shell>
    );
  }

  const isFormStep = activeStep >= STEPS.length;

  return (
    <Shell>
      <Stepper activeStep={activeStep} uploaded={session?.uploaded} />
      {err && (
        <div style={errStyle} data-testid="onboarding-error">
          <AlertCircle size={14} /> {err}
        </div>
      )}
      {!isFormStep ? (
        <CaptureStep
          step={STEPS[activeStep]}
          onCapture={onCapture}
          uploading={uploading}
          uploaded={session?.uploaded?.[STEPS[activeStep].key]}
          plan={session?.plan_name}
          ocrName={session?.ocr_hints?.id_document_name}
        />
      ) : (
        <FormStep
          email={email}
          setEmail={setEmail}
          dueDay={dueDay}
          setDueDay={setDueDay}
          onSubmit={onSubmit}
          submitting={submitting}
          ocrHints={session?.ocr_hints}
        />
      )}
    </Shell>
  );
}

// ---------------------------------------------------------------------------

function Shell({ children }) {
  return (
    <div style={{
      minHeight: "100vh",
      background: "linear-gradient(180deg, #0f172a 0%, #1e293b 100%)",
      color: "#0f172a",
      padding: 16,
    }}>
      <div style={{
        maxWidth: 460, margin: "0 auto",
        background: "#fff",
        borderRadius: 16,
        boxShadow: "0 10px 40px rgba(0,0,0,0.3)",
        overflow: "hidden",
      }}>
        <div style={{
          padding: "16px 20px",
          background: "linear-gradient(135deg, #0f766e, #14b8a6)",
          color: "white",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <ShieldCheck size={20} />
            <div>
              <div style={{ fontWeight: 800, fontSize: 14 }}>Ligo Fibra</div>
              <div style={{ fontSize: 10, opacity: 0.9 }}>
                Onboarding seguro · criptografado
              </div>
            </div>
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}

function Stepper({ activeStep, uploaded = {} }) {
  return (
    <div style={{
      display: "flex", padding: 12, gap: 6, background: "#f8fafc",
      borderBottom: "1px solid #e2e8f0",
    }}>
      {STEPS.map((s, i) => {
        const done = uploaded[s.key];
        const active = activeStep === i;
        const Icon = s.icon;
        return (
          <div key={s.key} style={{
            flex: 1, display: "flex", flexDirection: "column", alignItems: "center",
            gap: 4, opacity: done || active ? 1 : 0.4,
          }}>
            <div style={{
              width: 32, height: 32, borderRadius: "50%",
              background: done ? "#16a34a" : active ? "#0f766e" : "#cbd5e1",
              display: "grid", placeItems: "center", color: "white",
            }}>
              {done ? <Check size={16} strokeWidth={3} /> : <Icon size={14} />}
            </div>
            <div style={{ fontSize: 9, textAlign: "center", color: "#475569",
                           fontWeight: 600 }}>
              {s.label.split(" ")[0]}
            </div>
          </div>
        );
      })}
      <div style={{
        flex: 1, display: "flex", flexDirection: "column", alignItems: "center",
        gap: 4, opacity: activeStep >= STEPS.length ? 1 : 0.4,
      }}>
        <div style={{
          width: 32, height: 32, borderRadius: "50%",
          background: activeStep >= STEPS.length ? "#0f766e" : "#cbd5e1",
          display: "grid", placeItems: "center", color: "white",
        }}>
          <Sparkles size={14} />
        </div>
        <div style={{ fontSize: 9, textAlign: "center", color: "#475569",
                       fontWeight: 600 }}>
          Final
        </div>
      </div>
    </div>
  );
}

function CaptureStep({ step, onCapture, uploading, uploaded, plan, ocrName }) {
  const inputRef = useRef(null);
  return (
    <div style={{ padding: 20 }}>
      <h2 style={{ margin: 0, fontSize: 18, color: "#0f172a" }}>
        {step.label}
      </h2>
      <p style={{ fontSize: 12, color: "#475569", marginTop: 4 }}>
        {step.overlay === "oval"
          ? "Centralize seu rosto no oval segurando o documento ao lado."
          : step.overlay === "card"
          ? "Posicione o documento dentro do retângulo. Cuide pra ficar legível."
          : "Tire foto do comprovante de endereço (conta de luz, internet etc)."}
      </p>
      {plan && (
        <div style={{
          marginTop: 8, padding: "6px 10px",
          background: "#f0fdfa", border: "1px solid #ccfbf1",
          borderRadius: 6, fontSize: 11, color: "#0f766e",
        }}>
          Plano selecionado: <strong>{plan}</strong>
        </div>
      )}
      {ocrName && step.key === "id_document" && (
        <div style={{
          marginTop: 8, padding: "6px 10px",
          background: "#fefce8", border: "1px solid #fde68a",
          borderRadius: 6, fontSize: 11, color: "#92400e",
        }}>
          OCR detectou: <strong>{ocrName}</strong>
        </div>
      )}

      {/* Preview com overlay */}
      <div style={{
        marginTop: 16,
        background: "#0f172a",
        borderRadius: 12,
        aspectRatio: step.overlay === "oval" ? "3/4" : "4/3",
        position: "relative",
        overflow: "hidden",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        <OverlayGuide kind={step.overlay} />
        {uploaded && (
          <div style={{
            position: "absolute", inset: 0,
            background: "rgba(15,118,110,0.85)",
            display: "grid", placeItems: "center", color: "white",
          }}>
            <Check size={48} strokeWidth={3} />
            <div style={{ marginTop: 8, fontSize: 12, fontWeight: 700 }}>
              Recebido!
            </div>
          </div>
        )}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture={step.overlay === "oval" ? "user" : "environment"}
        style={{ display: "none" }}
        data-testid={`onboarding-file-${step.key}`}
        onChange={(e) => onCapture(e.target.files?.[0])}
      />
      <button
        onClick={() => inputRef.current?.click()}
        disabled={uploading}
        data-testid={`onboarding-capture-${step.key}`}
        style={{
          marginTop: 16, width: "100%", padding: 14,
          background: "linear-gradient(135deg, #0f766e, #14b8a6)",
          color: "white", border: "none", borderRadius: 10,
          fontSize: 15, fontWeight: 700, cursor: uploading ? "wait" : "pointer",
          display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
        }}
      >
        {uploading ? <>
          <RefreshCw size={18} className="animate-spin" /> Enviando…
        </> : uploaded ? <>
          <Camera size={18} /> Tirar outra
        </> : <>
          <Camera size={18} /> Tirar foto
        </>}
      </button>
    </div>
  );
}

function OverlayGuide({ kind }) {
  if (kind === "oval") {
    return (
      <>
        <svg viewBox="0 0 300 400" style={{ width: "80%" }}>
          <defs>
            <mask id="m">
              <rect width="300" height="400" fill="white" />
              <ellipse cx="150" cy="180" rx="100" ry="130" fill="black" />
            </mask>
          </defs>
          <rect width="300" height="400" fill="rgba(0,0,0,0.6)" mask="url(#m)" />
          <ellipse cx="150" cy="180" rx="100" ry="130" fill="none"
                    stroke="#14b8a6" strokeWidth="3" strokeDasharray="6 4" />
          <text x="150" y="350" textAnchor="middle" fill="white"
                 fontSize="14" fontWeight="bold">
            Centralize o rosto + documento
          </text>
        </svg>
      </>
    );
  }
  if (kind === "card") {
    return (
      <svg viewBox="0 0 400 300" style={{ width: "85%" }}>
        <defs>
          <mask id="m2">
            <rect width="400" height="300" fill="white" />
            <rect x="50" y="60" width="300" height="190" rx="14" fill="black" />
          </mask>
        </defs>
        <rect width="400" height="300" fill="rgba(0,0,0,0.6)" mask="url(#m2)" />
        <rect x="50" y="60" width="300" height="190" rx="14"
               fill="none" stroke="#14b8a6" strokeWidth="3"
               strokeDasharray="8 5" />
        {[0,1,2,3].map((i) => {
          const x = i % 2 === 0 ? 50 : 350;
          const y = i < 2 ? 60 : 250;
          return (
            <g key={i}>
              <line x1={x} y1={y} x2={x + (i%2===0?20:-20)} y2={y}
                     stroke="#14b8a6" strokeWidth="4" />
              <line x1={x} y1={y} x2={x} y2={y + (i<2?20:-20)}
                     stroke="#14b8a6" strokeWidth="4" />
            </g>
          );
        })}
        <text x="200" y="285" textAnchor="middle" fill="white"
               fontSize="13" fontWeight="bold">
          Encaixe o documento no quadro
        </text>
      </svg>
    );
  }
  // rect (comprovante)
  return (
    <svg viewBox="0 0 400 300" style={{ width: "85%" }}>
      <defs>
        <mask id="m3">
          <rect width="400" height="300" fill="white" />
          <rect x="60" y="40" width="280" height="220" rx="10" fill="black" />
        </mask>
      </defs>
      <rect width="400" height="300" fill="rgba(0,0,0,0.6)" mask="url(#m3)" />
      <rect x="60" y="40" width="280" height="220" rx="10"
             fill="none" stroke="#14b8a6" strokeWidth="3"
             strokeDasharray="8 5" />
      <text x="200" y="285" textAnchor="middle" fill="white"
             fontSize="13" fontWeight="bold">
        Comprovante de endereço
      </text>
    </svg>
  );
}

function FormStep({ email, setEmail, dueDay, setDueDay, onSubmit, submitting, ocrHints }) {
  return (
    <div style={{ padding: 20 }}>
      <h2 style={{ margin: 0, fontSize: 18 }}>Último passo! ✨</h2>
      <p style={{ fontSize: 12, color: "#475569", marginTop: 4 }}>
        Confirme seus dados pra finalizar a contratação.
      </p>

      {ocrHints?.id_document_name && (
        <div style={{
          marginTop: 12, padding: 10, background: "#f0fdfa",
          border: "1px solid #ccfbf1", borderRadius: 8, fontSize: 12,
        }}>
          <strong style={{ color: "#0f766e" }}>OCR identificou:</strong><br />
          Nome: <strong>{ocrHints.id_document_name}</strong><br />
          {ocrHints.address_city && (
            <>Cidade: <strong>{ocrHints.address_city}</strong></>
          )}
        </div>
      )}

      <label style={labelStyle}>E-mail</label>
      <input
        type="email"
        data-testid="onboarding-email-input"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="seuemail@exemplo.com"
        style={inputStyle}
      />

      <label style={labelStyle}>Melhor dia de vencimento</label>
      <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
        {[5, 10, 15].map((d) => (
          <button
            key={d}
            onClick={() => setDueDay(d)}
            data-testid={`onboarding-due-${d}`}
            style={{
              flex: 1, padding: "10px 14px",
              background: dueDay === d ? "#0f766e" : "white",
              color: dueDay === d ? "white" : "#0f172a",
              border: `1px solid ${dueDay === d ? "#0f766e" : "#cbd5e1"}`,
              borderRadius: 8, fontWeight: 700, fontSize: 14,
              cursor: "pointer",
            }}
          >dia {d}</button>
        ))}
      </div>

      <button
        onClick={onSubmit}
        disabled={submitting || !email.includes("@")}
        data-testid="onboarding-submit"
        style={{
          marginTop: 20, width: "100%", padding: 14,
          background: "linear-gradient(135deg, #0f766e, #14b8a6)",
          color: "white", border: "none", borderRadius: 10,
          fontSize: 15, fontWeight: 700,
          cursor: submitting ? "wait" : "pointer",
          opacity: !email.includes("@") ? 0.5 : 1,
          display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
        }}
      >
        {submitting ? <>
          <RefreshCw size={18} className="animate-spin" /> Enviando…
        </> : <>
          Finalizar contratação <ChevronRight size={18} />
        </>}
      </button>
    </div>
  );
}

const labelStyle = {
  display: "block", marginTop: 16, fontSize: 11, fontWeight: 700,
  color: "#475569", textTransform: "uppercase", letterSpacing: 0.5,
};
const inputStyle = {
  width: "100%", marginTop: 6, padding: "10px 12px",
  border: "1px solid #cbd5e1", borderRadius: 8,
  fontSize: 14, color: "#0f172a", boxSizing: "border-box",
};
const loadingStyle = {
  padding: 60, textAlign: "center", color: "#0f172a",
};
const errStyle = {
  margin: "8px 20px", padding: "8px 12px",
  background: "#fef2f2", color: "#dc2626", borderRadius: 6,
  fontSize: 12, display: "flex", alignItems: "center", gap: 6,
};
