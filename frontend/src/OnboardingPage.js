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
            Tudo certo! 
          </h2>
          <p style={{ color: "#475569", fontSize: 14, lineHeight: 1.6 }}>
            Recebemos seus documentos e nossa equipe vai validar tudo
            em instantes.
            <br /><br />
            <strong>Ligo Fibra — A Internet que te faz feliz! </strong>
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
        STEPS[activeStep].key === "selfie" ? (
          <LivenessStep
            token={token}
            onComplete={async (result) => {
              if (result.is_live) {
                await reloadSession();
                setTimeout(() => setActiveStep(STEPS.length), 800);
              } else {
                setErr(`Validação falhou: ${result.reason || "tente novamente"}`);
              }
            }}
            uploaded={session?.uploaded?.selfie}
          />
        ) : (
          <CaptureStep
            step={STEPS[activeStep]}
            onCapture={onCapture}
            uploading={uploading}
            uploaded={session?.uploaded?.[STEPS[activeStep].key]}
            plan={session?.plan_name}
            ocrName={session?.ocr_hints?.id_document_name}
          />
        )
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

function LivenessStep({ token, onComplete, uploaded }) {
  // Sequência: 3 capturas guiadas (esquerda, direita, sorriso)
  const POSES = [
    { key: "left", label: "Vire a cabeça pra ESQUERDA",
      hint: "Olhe pra esquerda, sem tirar o documento da mão", emoji: "" },
    { key: "right", label: "Vire a cabeça pra DIREITA",
      hint: "Agora vire devagar pra direita", emoji: "" },
    { key: "smile", label: "Olhe pra frente e SORRIA ",
      hint: "Centralize o rosto no oval e sorria!", emoji: "" },
  ];
  const [poseIdx, setPoseIdx] = useState(0);
  const [captured, setCaptured] = useState({});
  const [verifying, setVerifying] = useState(false);
  const [livenessResult, setLivenessResult] = useState(null);
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const canvasRef = useRef(null);
  const [cameraReady, setCameraReady] = useState(false);
  const [cameraErr, setCameraErr] = useState(null);

  useEffect(() => {
    if (uploaded || livenessResult?.is_live) return;
    let cancelled = false;
    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user", width: 480, height: 640 },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
          setCameraReady(true);
        }
      } catch (e) {
        setCameraErr(
          "Não foi possível acessar a câmera. "
          + "Permita o uso e recarregue a página."
        );
      }
    })();
    return () => {
      cancelled = true;
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
      }
    };
  }, [uploaded, livenessResult]);

  const grabFrame = () => {
    if (!videoRef.current) return null;
    const canvas = canvasRef.current || document.createElement("canvas");
    canvasRef.current = canvas;
    canvas.width = videoRef.current.videoWidth || 480;
    canvas.height = videoRef.current.videoHeight || 640;
    canvas.getContext("2d").drawImage(videoRef.current, 0, 0);
    return new Promise((res) => {
      canvas.toBlob((blob) => res(blob), "image/jpeg", 0.85);
    });
  };

  const captureCurrent = async () => {
    const pose = POSES[poseIdx];
    const blob = await grabFrame();
    if (!blob) return;
    const newCaptured = { ...captured, [pose.key]: blob };
    setCaptured(newCaptured);
    if (poseIdx < POSES.length - 1) {
      setPoseIdx(poseIdx + 1);
      return;
    }
    // Última pose — envia tudo pro backend
    await verify(newCaptured);
  };

  const verify = async (allFrames) => {
    if (verifying) return;
    setVerifying(true);
    try {
      const fd = new FormData();
      fd.append("frame_left", allFrames.left, "left.jpg");
      fd.append("frame_right", allFrames.right, "right.jpg");
      fd.append("frame_smile", allFrames.smile, "smile.jpg");
      const r = await axios.post(
        `${API}/api/onboarding/public/${token}/liveness`, fd,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      setLivenessResult(r.data);
      onComplete(r.data);
      // Para a câmera após verificar
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
      }
    } catch (e) {
      setLivenessResult({
        is_live: false,
        reason: e?.response?.data?.detail || e.message || "Erro de rede",
      });
      onComplete({ is_live: false,
        reason: e?.response?.data?.detail || "Erro" });
    } finally {
      setVerifying(false);
    }
  };

  const restart = () => {
    setPoseIdx(0);
    setCaptured({});
    setLivenessResult(null);
  };

  if (uploaded || livenessResult?.is_live) {
    return (
      <div style={{ padding: 20, textAlign: "center" }}>
        <div style={{
          width: 60, height: 60, borderRadius: "50%",
          background: "#16a34a", margin: "16px auto",
          display: "grid", placeItems: "center",
        }}>
          <Check size={32} color="white" strokeWidth={3} />
        </div>
        <h2 style={{ margin: 0, fontSize: 16, color: "#16a34a" }}>
          Selfie validada com sucesso!
        </h2>
        <p style={{ fontSize: 12, color: "#475569", marginTop: 8 }}>
          Vivacidade confirmada. Vamos pra última etapa…
        </p>
      </div>
    );
  }

  if (livenessResult && !livenessResult.is_live) {
    return (
      <div style={{ padding: 20, textAlign: "center" }}>
        <div style={{
          width: 60, height: 60, borderRadius: "50%",
          background: "#dc2626", margin: "16px auto",
          display: "grid", placeItems: "center",
        }}>
          <AlertCircle size={32} color="white" />
        </div>
        <h2 style={{ margin: 0, fontSize: 16, color: "#dc2626" }}>
          Validação falhou
        </h2>
        <p style={{ fontSize: 12, color: "#475569", marginTop: 8,
                     lineHeight: 1.5 }}>
          {livenessResult.reason || "Tente novamente em local com boa luz."}
        </p>
        <button onClick={restart} data-testid="liveness-retry"
          style={{
            marginTop: 16, padding: "10px 18px",
            background: "#0f766e", color: "white", border: "none",
            borderRadius: 8, fontWeight: 700, fontSize: 14, cursor: "pointer",
          }}>Tentar de novo</button>
      </div>
    );
  }

  const pose = POSES[poseIdx];
  return (
    <div style={{ padding: 20 }}>
      <h2 style={{ margin: 0, fontSize: 18 }}>
        Verificação de Vivacidade {pose.emoji}
      </h2>
      <p style={{ fontSize: 12, color: "#475569", marginTop: 4 }}>
        Captura {poseIdx + 1} de {POSES.length} — antifraude
      </p>
      <div style={{
        marginTop: 12, padding: "8px 12px",
        background: "#f0fdfa", border: "1px solid #ccfbf1",
        borderRadius: 8, fontSize: 13, fontWeight: 700, color: "#0f766e",
        textAlign: "center",
      }}>
        {pose.label}
      </div>
      <p style={{ fontSize: 11, color: "#64748b", marginTop: 6,
                   textAlign: "center" }}>
        {pose.hint}
      </p>

      <div style={{
        marginTop: 12, background: "#0f172a",
        borderRadius: 12, overflow: "hidden",
        position: "relative", aspectRatio: "3/4",
      }}>
        {cameraErr ? (
          <div style={{
            position: "absolute", inset: 0, padding: 20,
            display: "grid", placeItems: "center", color: "white",
            textAlign: "center",
          }}>
            <AlertCircle size={32} /><br />{cameraErr}
          </div>
        ) : (
          <>
            <video ref={videoRef}
              data-testid="liveness-video"
              autoPlay playsInline muted
              style={{
                width: "100%", height: "100%", objectFit: "cover",
                transform: "scaleX(-1)",  // espelha pra parecer espelho
              }}
            />
            {/* Overlay oval */}
            <svg viewBox="0 0 300 400"
              style={{
                position: "absolute", inset: 0, width: "100%", height: "100%",
                pointerEvents: "none",
              }}
            >
              <defs>
                <mask id="ovalmask">
                  <rect width="300" height="400" fill="white" />
                  <ellipse cx="150" cy="190" rx="100" ry="130" fill="black" />
                </mask>
              </defs>
              <rect width="300" height="400" fill="rgba(0,0,0,0.5)"
                     mask="url(#ovalmask)" />
              <ellipse cx="150" cy="190" rx="100" ry="130"
                        fill="none" stroke="#14b8a6"
                        strokeWidth="3" strokeDasharray="6 4" />
            </svg>
            {/* Indicador de pose */}
            <div style={{
              position: "absolute", top: 12, left: 12, right: 12,
              padding: "6px 10px", background: "rgba(15,118,110,0.9)",
              color: "white", borderRadius: 6, fontSize: 12, fontWeight: 700,
              textAlign: "center",
            }}>
              {pose.emoji} {pose.label}
            </div>
          </>
        )}
      </div>

      <div style={{
        marginTop: 10, display: "flex", justifyContent: "center", gap: 6,
      }}>
        {POSES.map((p, i) => (
          <div key={p.key} style={{
            width: 36, height: 4, borderRadius: 2,
            background: i < poseIdx ? "#16a34a"
              : i === poseIdx ? "#0f766e" : "#cbd5e1",
          }} />
        ))}
      </div>

      <button
        onClick={captureCurrent}
        disabled={!cameraReady || verifying}
        data-testid={`liveness-capture-${pose.key}`}
        style={{
          marginTop: 14, width: "100%", padding: 14,
          background: !cameraReady || verifying
            ? "#cbd5e1"
            : "linear-gradient(135deg, #0f766e, #14b8a6)",
          color: "white", border: "none", borderRadius: 10,
          fontSize: 15, fontWeight: 700,
          cursor: !cameraReady || verifying ? "wait" : "pointer",
          display: "flex", alignItems: "center", justifyContent: "center",
          gap: 8,
        }}
      >
        {verifying ? <>
          <RefreshCw size={18} className="animate-spin" /> Validando…
        </> : poseIdx === POSES.length - 1 ? <>
          <ShieldCheck size={18} /> Finalizar verificação
        </> : <>
          <Camera size={18} /> Capturar e prosseguir
        </>}
      </button>
    </div>
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
