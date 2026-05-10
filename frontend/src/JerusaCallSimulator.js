import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Phone, PhoneOff, Mic, MicOff, Loader2, AlertTriangle,
} from "lucide-react";
import { api } from "@/api";

/* =============================================================
   Simulador de chamada para a Jerusa via WebRTC (browser).
   Fluxo turno-a-turno:
     1. Usuário clica "Ligar"  → backend retorna mp3 da saudação → toca.
     2. Após o áudio terminar, abre o microfone automaticamente.
     3. Usuário clica "Falar" para gravar (push-to-talk) ou usa VAD simples.
     4. Ao soltar, manda webm pro backend → recebe mp3 da resposta → toca.
     5. Repete até "Desligar".
============================================================= */

const STATE_LABELS = {
  idle:        { label: "Pronto para ligar",      color: "var(--text-muted)" },
  ringing:     { label: "Conectando...",          color: "#0ea5e9" },
  jerusa_speaking: { label: "Jerusa falando...",   color: "#0d9488" },
  listening:   { label: "Pode falar agora",       color: "#16a34a" },
  recording:   { label: "Gravando...",            color: "#dc2626" },
  processing:  { label: "Processando...",         color: "#f59e0b" },
  ended:       { label: "Chamada encerrada",      color: "var(--text-muted)" },
  error:       { label: "Erro",                   color: "#dc2626" },
};

export default function JerusaCallSimulator() {
  const [phase, setPhase] = useState("idle");  // see STATE_LABELS
  const [sessionId, setSessionId] = useState(null);
  const [transcript, setTranscript] = useState([]); // [{role, text}]
  const [errorMsg, setErrorMsg] = useState(null);
  const [stats, setStats] = useState(null); // {stt_ms, llm_ms, tts_ms}
  const [callStartTs, setCallStartTs] = useState(null);
  const [callElapsed, setCallElapsed] = useState(0);

  const audioRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);
  const transcriptEndRef = useRef(null);

  // --- Tick do relógio da chamada ---
  useEffect(() => {
    if (!callStartTs) return undefined;
    const id = setInterval(() => {
      setCallElapsed(Math.floor((Date.now() - callStartTs) / 1000));
    }, 500);
    return () => clearInterval(id);
  }, [callStartTs]);

  // --- Auto-scroll do transcript ---
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  const playAudio = useCallback((b64, mime = "audio/mpeg") => {
    return new Promise((resolve) => {
      const audio = audioRef.current;
      if (!audio) return resolve();
      audio.src = `data:${mime};base64,${b64}`;
      audio.onended = () => resolve();
      audio.onerror = () => resolve();
      audio.play().catch(() => resolve());
    });
  }, []);

  const startCall = async () => {
    setErrorMsg(null);
    setTranscript([]);
    setStats(null);
    setPhase("ringing");
    setCallStartTs(Date.now());
    setCallElapsed(0);

    try {
      const r = await api.voiceStartSession("browser");
      setSessionId(r.session_id);
      setTranscript([{ role: "assistant", text: r.greeting_text }]);
      setPhase("jerusa_speaking");
      // Pede permissão de microfone JÁ (warm up) — usuário já dá ok cedo
      try {
        streamRef.current = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (e) {
        setErrorMsg("Sem permissão de microfone. Permita no navegador para falar com a Jerusa.");
        setPhase("error");
        return;
      }
      await playAudio(r.greeting_audio_b64, r.audio_mime);
      setPhase("listening");
    } catch (e) {
      setErrorMsg(e?.response?.data?.detail || e.message);
      setPhase("error");
    }
  };

  const startRecording = () => {
    if (!streamRef.current) return;
    if (phase !== "listening") return;
    chunksRef.current = [];
    const mr = new MediaRecorder(streamRef.current, {
      mimeType: "audio/webm;codecs=opus",
    });
    mr.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) chunksRef.current.push(ev.data);
    };
    mr.onstop = async () => {
      const blob = new Blob(chunksRef.current, { type: "audio/webm" });
      if (blob.size < 800) {
        // Áudio muito curto — provavelmente clique acidental
        setPhase("listening");
        return;
      }
      setPhase("processing");
      try {
        const r = await api.voiceTurn(sessionId, blob, "turn.webm");
        setStats({ stt_ms: r.stt_ms, llm_ms: r.llm_ms, tts_ms: r.tts_ms });
        if (r.transcript) {
          setTranscript((t) => [...t, { role: "user", text: r.transcript }]);
        }
        setTranscript((t) => [...t, { role: "assistant", text: r.reply_text }]);
        setPhase("jerusa_speaking");
        await playAudio(r.reply_audio_b64, r.audio_mime);
        setPhase("listening");
      } catch (e) {
        setErrorMsg(e?.response?.data?.detail || e.message);
        setPhase("error");
      }
    };
    mediaRecorderRef.current = mr;
    mr.start();
    setPhase("recording");
  };

  const stopRecording = () => {
    const mr = mediaRecorderRef.current;
    if (mr && mr.state === "recording") {
      mr.stop();
    }
  };

  const endCall = async () => {
    try {
      const mr = mediaRecorderRef.current;
      if (mr && mr.state === "recording") mr.stop();
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
      }
      const audio = audioRef.current;
      if (audio) audio.pause();
      if (sessionId) {
        await api.voiceEndSession(sessionId, "user_hangup");
      }
      setPhase("ended");
      setCallStartTs(null);
    } catch (e) {
      setErrorMsg(e?.response?.data?.detail || e.message);
    }
  };

  const fmtTime = (s) => {
    const mm = Math.floor(s / 60).toString().padStart(2, "0");
    const ss = (s % 60).toString().padStart(2, "0");
    return `${mm}:${ss}`;
  };

  const stateInfo = STATE_LABELS[phase] || STATE_LABELS.idle;
  const isCallActive = sessionId && phase !== "idle" && phase !== "ended" && phase !== "error";

  return (
    <div data-testid="jerusa-call-simulator" style={{ display: "grid", gap: 14 }}>
      <style>{`
        @keyframes jerusa-pulse {
          0%, 100% { transform: scale(1); }
          50%      { transform: scale(1.06); }
        }
        @keyframes jerusa-rec-pulse {
          0%, 100% { box-shadow: 0 0 0 0 rgba(220,38,38,.55); }
          50%      { box-shadow: 0 0 0 16px rgba(220,38,38,0); }
        }
      `}</style>

      <audio ref={audioRef} hidden />

      <div className="surface" style={{ padding: 24, borderRadius: 16,
            background: "linear-gradient(135deg, var(--bg-surface) 0%, var(--bg-surface-2) 100%)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 18, flexWrap: "wrap" }}>
          <div style={{
            width: 60, height: 60, borderRadius: "50%",
            background: "linear-gradient(135deg, #0d9488, #0f766e)",
            color: "#fff", display: "grid", placeItems: "center",
            fontSize: 22, fontWeight: 800, letterSpacing: "-0.04em",
            boxShadow: "0 4px 14px rgba(13,148,136,.35)",
            animation: phase === "jerusa_speaking" ? "jerusa-pulse 1.2s ease-in-out infinite" : "none",
          }}>JE</div>
          <div style={{ flex: 1, minWidth: 200 }}>
            <h2 style={{ margin: 0, fontSize: 20, fontWeight: 800, letterSpacing: "-0.02em" }}>
              Jerusa
            </h2>
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
              Atendente Virtual de Voz · Telefonia IA
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div data-testid="jerusa-state" style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "5px 12px", borderRadius: 999,
              background: "var(--bg-surface-2)",
              border: `1px solid ${stateInfo.color}`,
              color: stateInfo.color,
              fontSize: 11, fontWeight: 800, textTransform: "uppercase", letterSpacing: 0.6,
            }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: stateInfo.color }} />
              {stateInfo.label}
            </div>
            {isCallActive && (
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }} className="mono">
                {fmtTime(callElapsed)}
              </div>
            )}
          </div>
        </div>

        {/* Botões principais */}
        {phase === "idle" || phase === "ended" || phase === "error" ? (
          <button
            onClick={startCall}
            data-testid="jerusa-call-start-btn"
            style={{
              width: "100%", padding: "16px 24px", border: "none",
              borderRadius: 14, fontSize: 16, fontWeight: 700,
              background: "linear-gradient(135deg, #0d9488, #0f766e)",
              color: "#fff", cursor: "pointer",
              display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
              boxShadow: "0 4px 14px rgba(13,148,136,.4)",
            }}
          >
            <Phone size={18} /> Ligar para a Jerusa
          </button>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 10 }}>
            {phase === "listening" && (
              <button
                onMouseDown={startRecording} onMouseUp={stopRecording}
                onTouchStart={startRecording} onTouchEnd={stopRecording}
                data-testid="jerusa-talk-btn"
                style={{
                  padding: "14px 20px", border: "1px solid var(--border-default)",
                  borderRadius: 12, fontSize: 14, fontWeight: 700,
                  background: "var(--bg-surface)", color: "var(--text-primary)",
                  cursor: "pointer",
                  display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
                }}
              >
                <Mic size={16} /> Segure para falar
              </button>
            )}
            {phase === "recording" && (
              <button
                onMouseUp={stopRecording} onTouchEnd={stopRecording}
                data-testid="jerusa-talk-btn-recording"
                style={{
                  padding: "14px 20px", border: "1px solid #dc2626",
                  borderRadius: 12, fontSize: 14, fontWeight: 700,
                  background: "#dc2626", color: "#fff",
                  cursor: "pointer",
                  display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
                  animation: "jerusa-rec-pulse 1.2s ease-out infinite",
                }}
              >
                <Mic size={16} /> Solte para enviar
              </button>
            )}
            {(phase === "ringing" || phase === "jerusa_speaking" || phase === "processing") && (
              <button disabled style={{
                padding: "14px 20px", border: "1px solid var(--border-default)",
                borderRadius: 12, fontSize: 14, fontWeight: 700,
                background: "var(--bg-surface-2)", color: "var(--text-muted)",
                display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
                opacity: 0.7,
              }}>
                <Loader2 size={16} className="animate-spin" />
                {phase === "processing" ? "Transcrevendo + pensando..." : "Aguarde..."}
              </button>
            )}
            <button
              onClick={endCall}
              data-testid="jerusa-call-end-btn"
              style={{
                padding: "14px 18px", border: "1px solid #dc2626",
                borderRadius: 12, fontSize: 14, fontWeight: 700,
                background: "transparent", color: "#dc2626", cursor: "pointer",
                display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
              }}
            >
              <PhoneOff size={16} /> Desligar
            </button>
          </div>
        )}

        {errorMsg && (
          <div style={{
            marginTop: 12, padding: 10, borderRadius: 8,
            background: "var(--danger-soft)", color: "var(--danger-soft-fg)",
            fontSize: 12, display: "flex", alignItems: "center", gap: 8,
          }} data-testid="jerusa-error">
            <AlertTriangle size={14} /> {errorMsg}
          </div>
        )}

        {!streamRef.current && phase === "idle" && (
          <div style={{
            marginTop: 14, padding: 10, borderRadius: 8,
            background: "var(--info-soft)", color: "var(--info-soft-fg)",
            fontSize: 12,
          }}>
            <strong>Como funciona:</strong> ao clicar em "Ligar", a Jerusa cumprimenta você em voz.
            Depois é só <em>segurar</em> o botão "Segure para falar" enquanto fala (estilo walkie-talkie)
            e soltar quando terminar — ela responde em voz no mesmo formato que vai responder ao seu
            telefone via SIP/MagnusBilling depois.
          </div>
        )}
      </div>

      {/* Transcript ao vivo */}
      {transcript.length > 0 && (
        <div className="surface" style={{ padding: 16, borderRadius: 12 }}
             data-testid="jerusa-transcript">
          <div style={{ fontSize: 11, fontWeight: 800, color: "var(--text-muted)",
                         textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 10 }}>
            Transcrição da chamada
          </div>
          <div style={{ display: "grid", gap: 8, maxHeight: 260, overflowY: "auto" }}>
            {transcript.map((m, i) => (
              <div key={i} style={{
                display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start",
              }}>
                <div style={{
                  maxWidth: "78%", padding: "8px 12px", borderRadius: 12,
                  background: m.role === "user" ? "#0d9488" : "var(--bg-surface-2)",
                  color: m.role === "user" ? "#fff" : "var(--text-primary)",
                  border: m.role === "user" ? "1px solid #0d9488" : "1px solid var(--border-default)",
                  fontSize: 13, lineHeight: 1.5, whiteSpace: "pre-wrap",
                }}>
                  <div style={{ fontSize: 10, opacity: 0.7, marginBottom: 2,
                                 textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 700 }}>
                    {m.role === "user" ? "Você" : "Jerusa"}
                  </div>
                  {m.text}
                </div>
              </div>
            ))}
            <div ref={transcriptEndRef} />
          </div>
          {stats && (
            <div style={{ marginTop: 10, padding: 8, borderRadius: 8,
                           background: "var(--bg-surface-2)", fontSize: 10,
                           color: "var(--text-muted)", display: "flex", gap: 12 }}
                 data-testid="jerusa-stats" className="mono">
              <span>STT: {stats.stt_ms}ms</span>
              <span>LLM: {stats.llm_ms}ms</span>
              <span>TTS: {stats.tts_ms}ms</span>
              <span style={{ marginLeft: "auto" }}>
                Total turno: {(stats.stt_ms || 0) + (stats.llm_ms || 0) + (stats.tts_ms || 0)}ms
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
