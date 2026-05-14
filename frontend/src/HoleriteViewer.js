import React, { useEffect, useState } from "react";
import { Shield, Eye, EyeOff, Lock, FileText, AlertCircle, CheckCircle2 } from "lucide-react";
import { api, API } from "@/api";

/* =============================================================
   HoleriteViewer — página pública acessada via link WhatsApp
   /holerite/:token

   Fluxo:
   1. Valida token via GET /token/info → mostra "Holerite de mai/2026"
   2. Pede senha do colaborador
   3. POST /token/access → recebe session_token
   4. Stream do PDF via /session/{token}/file em iframe
============================================================= */
export default function HoleriteViewer({ token, onBack }) {
  const [stage, setStage] = useState("loading"); // loading | login | viewing | error
  const [info, setInfo] = useState(null);
  const [password, setPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [sessionToken, setSessionToken] = useState("");

  useEffect(() => {
    if (!token) { setStage("error"); setErr("Token ausente."); return; }
    api.holeriteTokenInfo(token).then((r) => {
      setInfo(r);
      setStage("login");
    }).catch((e) => {
      setErr(extractErr(e));
      setStage("error");
    });
  }, [token]);

  async function authenticate(e) {
    e?.preventDefault?.();
    setErr("");
    if (!password) { setErr("Informe sua senha do SmartProv."); return; }
    setBusy(true);
    try {
      const r = await api.holeriteTokenAccess(token, password);
      if (r.ok && r.session_token) {
        setSessionToken(r.session_token);
        setStage("viewing");
      } else {
        setErr("Falha na autenticação.");
      }
    } catch (e) {
      setErr(extractErr(e));
    } finally { setBusy(false); }
  }

  const pdfUrl = sessionToken
    ? `${API}/holerites/session/${sessionToken}/file`
    : "";

  return (
    <div style={{
      minHeight: "100vh",
      background: "linear-gradient(135deg, #0f172a 0%, #1e293b 100%)",
      display: stage === "viewing" ? "block" : "grid",
      placeItems: stage === "viewing" ? undefined : "center",
      padding: stage === "viewing" ? 0 : 20,
    }}>
      {stage === "loading" && (
        <div style={{ color: "#cbd5e1", textAlign: "center" }}>
          <div style={{ fontSize: 14 }}>Validando link...</div>
        </div>
      )}

      {stage === "error" && (
        <Card>
          <div style={{ textAlign: "center", padding: 30 }}>
            <AlertCircle size={48} color="#dc2626" strokeWidth={1.5}
                          style={{ marginBottom: 12 }} />
            <h2 style={{ margin: 0, fontSize: 20, fontWeight: 800,
                              color: "#0f172a" }}>
              Link inválido
            </h2>
            <p style={{ margin: "8px 0 0", fontSize: 13, color: "#64748b" }}>
              {err || "Este link pode ter expirado, sido revogado ou nunca existiu."}
            </p>
            <p style={{ margin: "16px 0 0", fontSize: 11, color: "#94a3b8" }}>
              Entre em contato com o RH da sua empresa para receber um novo link.
            </p>
          </div>
        </Card>
      )}

      {stage === "login" && info && (
        <Card>
          <form onSubmit={authenticate} data-testid="holerite-viewer-login"
                style={{ padding: 28 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10,
                              marginBottom: 18 }}>
              <div style={{
                width: 44, height: 44, borderRadius: 10,
                background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
                display: "grid", placeItems: "center",
                boxShadow: "0 4px 12px rgba(99,102,241,.35)",
              }}>
                <FileText size={22} color="white" />
              </div>
              <div>
                <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800,
                                  color: "#0f172a", letterSpacing: "-0.02em" }}>
                  Holerite Digital
                </h2>
                <div style={{ fontSize: 11, color: "#64748b" }}>
                  Olá, <strong>{info.first_name}</strong> —
                  competência {info.competence}
                </div>
              </div>
            </div>

            <div style={{
              padding: 10, borderRadius: 8, marginBottom: 16,
              background: "rgba(99,102,241,.08)",
              border: "1px solid rgba(99,102,241,.25)",
              fontSize: 11, color: "#3730a3",
              display: "flex", gap: 8, alignItems: "flex-start",
            }}>
              <Shield size={14} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>
                Para sua segurança, informe a <strong>senha do seu cadastro
                no SmartProv</strong> para acessar este documento.
              </span>
            </div>

            <label style={{ fontSize: 11, fontWeight: 800, color: "#475569",
                              textTransform: "uppercase", letterSpacing: ".05em" }}>
              Senha
            </label>
            <div style={{ position: "relative", marginTop: 6, marginBottom: 14 }}>
              <Lock size={14} style={{ position: "absolute", left: 10, top: 12,
                                            color: "#94a3b8" }} />
              <input type={showPwd ? "text" : "password"}
                     value={password} autoFocus
                     onChange={(e) => setPassword(e.target.value)}
                     data-testid="holerite-viewer-password"
                     placeholder="Sua senha"
                     style={{
                       width: "100%", padding: "10px 38px 10px 32px",
                       border: "1px solid #e2e8f0", borderRadius: 8,
                       fontSize: 13, outline: "none",
                       background: "white", color: "#0f172a",
                     }} />
              <button type="button" onClick={() => setShowPwd((v) => !v)}
                      style={{
                        position: "absolute", right: 8, top: 9,
                        background: "transparent", border: "none",
                        cursor: "pointer", padding: 4, color: "#64748b",
                      }}>
                {showPwd ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>

            {err && (
              <div data-testid="holerite-viewer-error"
                   style={{ background: "#fef2f2", color: "#991b1b",
                               padding: 10, borderRadius: 6,
                               fontSize: 12, fontWeight: 700,
                               marginBottom: 12,
                               display: "flex", alignItems: "center", gap: 6 }}>
                <AlertCircle size={13} /> {err}
              </div>
            )}

            <button type="submit" disabled={busy}
                    data-testid="holerite-viewer-submit"
                    style={{
                      width: "100%", padding: "11px",
                      borderRadius: 8, border: "none",
                      background: busy
                        ? "#94a3b8"
                        : "linear-gradient(135deg, #6366f1, #8b5cf6)",
                      color: "white", fontSize: 13, fontWeight: 800,
                      cursor: busy ? "not-allowed" : "pointer",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      gap: 6,
                    }}>
              {busy ? "Validando..." : (
                <>
                  <Shield size={14} /> Acessar holerite
                </>
              )}
            </button>

            <div style={{ marginTop: 16, fontSize: 10, color: "#94a3b8",
                              textAlign: "center", lineHeight: 1.6 }}>
              Este acesso é auditado.<br/>
              Link expira em {info.expires_at
                ? new Date(info.expires_at).toLocaleString("pt-BR",
                    { dateStyle: "short", timeStyle: "short" })
                : "—"}.
            </div>
          </form>
        </Card>
      )}

      {stage === "viewing" && pdfUrl && (
        <div data-testid="holerite-viewer-pdf"
             style={{ minHeight: "100vh", background: "#1e293b",
                         display: "flex", flexDirection: "column" }}>
          <div style={{
            padding: "10px 16px", background: "#0f172a",
            borderBottom: "1px solid #334155",
            display: "flex", alignItems: "center", gap: 10,
          }}>
            <CheckCircle2 size={16} color="#10b981" />
            <span style={{ fontSize: 12, color: "#e2e8f0", fontWeight: 700 }}>
              Holerite {info.competence} — {info.first_name}
            </span>
            <span style={{ flex: 1 }} />
            <a href={pdfUrl} download
               style={{
                 padding: "6px 14px", borderRadius: 6,
                 background: "#6366f1", color: "white",
                 fontSize: 11, fontWeight: 800, textDecoration: "none",
               }}>
              Baixar PDF
            </a>
          </div>
          <iframe src={pdfUrl} title="Holerite"
                  style={{ flex: 1, border: "none", background: "#1e293b" }}
                  data-testid="holerite-viewer-iframe" />
        </div>
      )}
    </div>
  );
}

function Card({ children }) {
  return (
    <div style={{
      background: "white",
      borderRadius: 16,
      boxShadow: "0 20px 60px rgba(0,0,0,.4)",
      width: 420, maxWidth: "92vw",
      overflow: "hidden",
    }}>
      {children}
    </div>
  );
}

function extractErr(e) {
  const d = e?.response?.data?.detail ?? e?.response?.data ?? e?.message;
  if (!d) return "Erro desconhecido.";
  if (typeof d === "string") return d;
  return JSON.stringify(d);
}
