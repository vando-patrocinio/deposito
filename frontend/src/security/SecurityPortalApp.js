/*
 * SecurityPortalApp.js — Portal cliente de Segurança Residencial.
 * Acionado por /?portal=security
 *
 * Layout simples e mobile-first:
 *  - Login dedicado (token security_portal)
 *  - Lista de imóveis com estado armado/desarmado
 *  - Botões grandes: Armar Total / Armar Parcial / Desarmar / PÂNICO
 *  - Feed de alarmes
 */
import React, { useEffect, useState } from "react";
import axios from "axios";
import "@/fleet/fleet-portal.css";   // reusa CSS do fleet portal (dashboard)
import "@/security/security-portal.css"; // overrides do login (Verisure-like)

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api/security-portal`;
const LS_KEY = "security_portal_token";

const ARM_INFO = {
  armed_away: { icon: "", label: "Armado total", color: "#dc2626" },
  armed_stay: { icon: "", label: "Armado parcial", color: "#f59e0b" },
  disarmed: { icon: "", label: "Desarmado", color: "#10b981" },
};

export default function SecurityPortalApp() {
  const [token, setToken] = useState(
    () => localStorage.getItem(LS_KEY) || "");
  const [meta, setMeta] = useState(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-fp-theme", "dark");
    if (!token) { setMeta(null); return; }
    axios.get(`${API}/me`,
                { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => setMeta(r.data))
      .catch(() => { localStorage.removeItem(LS_KEY); setToken(""); });
  }, [token]);

  if (!token || !meta) {
    return <Login onLogged={(tk, info) => {
      localStorage.setItem(LS_KEY, tk);
      setToken(tk); setMeta(info);
    }} />;
  }
  return <Dashboard token={token} meta={meta}
                       onLogout={() => {
                         localStorage.removeItem(LS_KEY);
                         setToken(""); setMeta(null);
                       }} />;
}

function Login({ onLogged }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const submit = async (e) => {
    e?.preventDefault();
    setBusy(true); setErr("");
    try {
      const r = await axios.post(`${API}/auth/login`, { email, password });
      onLogged(r.data.access_token,
                { user: r.data.user, tenant: r.data.tenant });
    } catch (er) {
      setErr(er?.response?.data?.detail || er.message);
    }
    setBusy(false);
  };
  return (
    <div className="sp-login fp-theme-dark"
          data-testid="security-portal-login">
      <div className="sp-login-hero">
        <img src="/security-hero.png" alt=""
              className="sp-hero-img"
              onError={(e) => { e.currentTarget.style.display = "none"; }} />
        <div className="sp-hero-overlay" />
        <div className="sp-hero-vignette" />

        <div className="sp-monitor-pill">
          <span>Central 24h · ao vivo</span>
        </div>

        <div className="sp-hero-content">
          <div className="sp-brand-row">
            <div className="sp-shield">️</div>
            <div>
              <h1 className="sp-brand-name">Smart<span>Home</span></h1>
              <div className="sp-brand-tag">Security Suite · Powered by SmartProv</div>
            </div>
          </div>

          <h2 className="sp-tagline">
            Sua casa,<br />
            <em>sempre protegida.</em>
          </h2>
          <p className="sp-sub">
            Monitoramento profissional 24 horas, controle pelo app e
            resposta imediata em qualquer emergência. Tudo na palma da
            sua mão — armando, desarmando e acionando o pânico em
            1 toque.
          </p>

          <div className="sp-trust">
            <div className="sp-trust-pill">
              <span className="ic">️</span>
              <span>Resposta &lt; 30s</span>
            </div>
            <div className="sp-trust-pill">
              <span className="ic">🆘</span>
              <span>Pânico em 1 toque</span>
            </div>
            <div className="sp-trust-pill">
              <span className="ic"></span>
              <span>Central monitorada</span>
            </div>
            <div className="sp-trust-pill">
              <span className="ic"></span>
              <span>Conexão criptografada</span>
            </div>
          </div>

          <div className="sp-cert-row">
            <b>SMARTHOME PRO</b>
            <span className="sp-cert-dot" />
            <span>ABESE certified</span>
            <span className="sp-cert-dot" />
            <span>LGPD compliant</span>
            <span className="sp-cert-dot" />
            <span>ISO 27001</span>
          </div>
        </div>
      </div>

      <div className="sp-login-side">
        <form onSubmit={submit} className="sp-card">
          <div className="sp-card-mob-brand">
            <div className="sp-shield" style={{ width: 40, height: 40,
                                                   fontSize: 20 }}>️</div>
            <h1>Smart<span>Home</span></h1>
          </div>

          <h3 className="sp-welcome">Acesse sua central</h3>
          <p className="sp-welcome-sub">
            Entre com seu cadastro pra armar e monitorar seus imóveis.
          </p>

          <label className="sp-field">
            <span>E-mail</span>
            <input type="email" value={email} required autoFocus
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="seu@email.com"
                    autoComplete="email"
                    data-testid="security-portal-email" />
          </label>

          <label className="sp-field">
            <span>Senha</span>
            <div className="sp-pwd-wrap">
              <input type={showPwd ? "text" : "password"} value={password}
                      required
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="••••••••"
                      autoComplete="current-password"
                      data-testid="security-portal-password" />
              <button type="button" className="sp-pwd-toggle"
                       onClick={() => setShowPwd((p) => !p)}
                       aria-label="Mostrar senha">
                {showPwd ? "" : ""}
              </button>
            </div>
          </label>

          {err && <div className="sp-err" data-testid="sec-portal-err">
            {err}
          </div>}

          <button type="submit" disabled={busy} className="sp-submit"
                   data-testid="security-portal-login-btn">
            {busy ? "Validando…" : "Entrar com segurança →"}
          </button>

          <div className="sp-help-strip">
            <a href="#esqueci" onClick={(e) => {
              e.preventDefault();
              alert("Entre em contato com o suporte da sua central.");
            }}>Esqueci a senha</a>
            <span className="sp-secure">SSL · Conexão segura</span>
          </div>

          <div className="sp-foot">
            © 2026 <b>SmartHome Security</b> · Powered by SmartProv ·
            Suporte 24h
          </div>
        </form>
      </div>
    </div>
  );
}

function Dashboard({ token, meta, onLogout }) {
  const [sites, setSites] = useState([]);
  const [alarms, setAlarms] = useState([]);
  const [busy, setBusy] = useState(null);  // sid em ação
  const [confirmation, setConfirmation] = useState(null);
  const headers = { Authorization: `Bearer ${token}` };

  const reload = async () => {
    try {
      const [s, a] = await Promise.all([
        axios.get(`${API}/sites`, { headers }),
        axios.get(`${API}/alarms`, { headers }),
      ]);
      setSites(s.data); setAlarms(a.data);
    } catch { /* */ }
  };
  useEffect(() => {
    reload();
    const id = setInterval(reload, 8000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const arm = async (sid, mode) => {
    setBusy(sid);
    try {
      await axios.post(`${API}/sites/${sid}/arm?mode=${mode}`, {},
                          { headers });
      setConfirmation(`✅ ${mode === "away" ? "Armado total"
        : "Armado parcial"} solicitado`);
      reload();
    } catch (e) {
      alert(e?.response?.data?.detail || e.message);
    }
    setBusy(null);
    setTimeout(() => setConfirmation(null), 4000);
  };
  const disarm = async (sid) => {
    setBusy(sid);
    try {
      await axios.post(`${API}/sites/${sid}/disarm`, {}, { headers });
      setConfirmation("✅ Desarme solicitado");
      reload();
    } catch (e) { alert(e?.response?.data?.detail || e.message); }
    setBusy(null);
    setTimeout(() => setConfirmation(null), 4000);
  };
  const panic = async (sid) => {
    if (!window.confirm("ACIONAR PÂNICO? A central será notificada IMEDIATAMENTE.")) {
      return;
    }
    setBusy(sid);
    try {
      await axios.post(`${API}/sites/${sid}/panic`, {}, { headers });
      setConfirmation("PÂNICO ACIONADO · central avisada");
      reload();
    } catch (e) { alert(e?.response?.data?.detail || e.message); }
    setBusy(null);
  };

  return (
    <div className="fp-app fp-theme-dark"
          data-testid="security-portal-dashboard">
      <header className="fp-topbar">
        <div className="fp-topbar-left">
          <div className="fp-brand">
            <span className="fp-brand-icon"></span>
            <div>
              <div className="fp-brand-name">
                {meta.tenant?.name || "SmartHome"}
              </div>
              <div className="fp-brand-tagline">Segurança 24h</div>
            </div>
          </div>
        </div>
        <div className="fp-topbar-right">
          <div className="fp-user-chip">
            <div className="fp-user-avatar">
              {(meta.user?.name || meta.user?.email || "?")[0].toUpperCase()}
            </div>
            <div className="fp-user-info">
              <div className="fp-user-name">
                {meta.user?.name || meta.user?.email}
              </div>
              <div className="fp-user-role">Cliente</div>
            </div>
          </div>
          <button className="fp-icon-btn" onClick={onLogout}
                   title="Sair"
                   data-testid="security-portal-logout">⎋</button>
        </div>
      </header>

      {confirmation && (
        <div style={{ background: "#10b981", color: "white",
                         padding: "10px 20px", textAlign: "center",
                         fontWeight: 700, fontSize: 14 }}
              data-testid="security-portal-confirm">
          {confirmation}
        </div>
      )}

      <main style={{ padding: 16, maxWidth: 1000, margin: "0 auto",
                       width: "100%" }}>
        <h2 style={{ color: "var(--fp-text)", marginTop: 8 }}>
          Meus imóveis ({sites.length})
        </h2>
        {!sites.length && (
          <div style={{ padding: 60, textAlign: "center",
                          color: "var(--fp-text-2)" }}>
            Nenhum imóvel vinculado ao seu acesso.
          </div>
        )}
        {sites.map((s) => {
          const ai = ARM_INFO[s.arm_state || "disarmed"] || ARM_INFO.disarmed;
          return (
            <div key={s.id} data-testid={`security-portal-site-${s.id}`}
                  style={{ background: "var(--fp-bg-2)",
                             border: "1px solid var(--fp-border)",
                             borderRadius: 14,
                             padding: 18, marginBottom: 14 }}>
              <div style={{ display: "flex",
                              justifyContent: "space-between",
                              alignItems: "flex-start",
                              marginBottom: 14, flexWrap: "wrap", gap: 8 }}>
                <div>
                  <div style={{ fontSize: 18, fontWeight: 800,
                                  color: "var(--fp-text)" }}>
                    {s.name}
                  </div>
                  <div style={{ fontSize: 12,
                                  color: "var(--fp-text-2)" }}>
                    {s.address || "—"}
                  </div>
                </div>
                <div style={{ padding: "8px 16px",
                                borderRadius: 8,
                                background: ai.color + "22",
                                color: ai.color,
                                fontWeight: 800,
                                borderLeft: `3px solid ${ai.color}` }}>
                  {ai.icon} {ai.label}
                </div>
              </div>
              <div style={{ display: "grid",
                              gridTemplateColumns:
                                "repeat(auto-fit,minmax(140px,1fr))",
                              gap: 10 }}>
                <button onClick={() => arm(s.id, "away")}
                         disabled={busy === s.id}
                         className="fp-btn fp-btn-danger"
                         data-testid={`security-portal-arm-away-${s.id}`}>
                  Armar Total
                </button>
                <button onClick={() => arm(s.id, "stay")}
                         disabled={busy === s.id}
                         className="fp-btn"
                         style={{ background:
                                    "linear-gradient(135deg,#f59e0b,#d97706)",
                                   color: "white" }}>
                  Armar Parcial
                </button>
                <button onClick={() => disarm(s.id)}
                         disabled={busy === s.id}
                         className="fp-btn fp-btn-success"
                         data-testid={`security-portal-disarm-${s.id}`}>
                  Desarmar
                </button>
                <button onClick={() => panic(s.id)}
                         disabled={busy === s.id}
                         data-testid={`security-portal-panic-${s.id}`}
                         style={{ padding: "12px 16px",
                                    background:
                                      "linear-gradient(135deg,#ef4444,#7f1d1d)",
                                    color: "white",
                                    border: "2px solid #fca5a5",
                                    borderRadius: 8,
                                    fontWeight: 800,
                                    fontSize: 14,
                                    cursor: "pointer",
                                    boxShadow:
                                      "0 4px 14px rgba(239,68,68,.5)",
                                    animation: "fp-cmd-pop .3s ease-out" }}>
                  PÂNICO
                </button>
              </div>
            </div>
          );
        })}

        {alarms.length > 0 && (
          <div style={{ marginTop: 24 }}>
            <h2 style={{ color: "var(--fp-text)" }}>
              Alertas recentes ({alarms.length})
            </h2>
            {alarms.slice(0, 50).map((a) => (
              <div key={a.id} style={{ background: "var(--fp-bg-2)",
                                            border: "1px solid var(--fp-border)",
                                            borderLeft: `3px solid ${
                                              a.severity === "critical" ? "#dc2626"
                                                : a.severity === "high" ? "#ef4444"
                                                  : "#f59e0b"}`,
                                            borderRadius: 8, padding: 12,
                                            marginBottom: 6,
                                            display: "flex", gap: 12,
                                            alignItems: "center" }}>
                <div style={{ fontSize: 22 }}>
                  {a.kind === "panic" ? "🆘"
                    : a.kind?.includes("burglary") ? ""
                      : a.kind === "fire" ? ""
                        : a.kind === "flood" ? ""
                          : ""}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 700,
                                  color: "var(--fp-text)" }}>
                    {a.label}
                  </div>
                  <div style={{ fontSize: 11,
                                  color: "var(--fp-text-2)" }}>
                    {new Date(a.ts).toLocaleString("pt-BR")}
                    {a.contact_zone > 0 && ` · Zona ${a.contact_zone}`}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
