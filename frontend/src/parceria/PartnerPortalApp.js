/* PartnerPortalApp.js — App do PARCEIRO comercial.
   Acionado por ?portal=parceiro
   - Login dedicado (partner_portal JWT)
   - KPIs (redenções, valor a receber, promoções ativas)
   - Scanner QR (html5-qrcode) que valida o QR do cliente
   - Histórico de redenções
*/
import React, { useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { Html5Qrcode } from "html5-qrcode";
import "@/parceria/parceria.css";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api/parceiro-portal`;
const LS_KEY = "partner_portal_token";

export default function PartnerPortalApp() {
  const [token, setToken] = useState(
    () => localStorage.getItem(LS_KEY) || "");
  const [me, setMe] = useState(null);

  useEffect(() => {
    if (!token) { setMe(null); return; }
    axios.get(`${API}/me`,
              { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => setMe(r.data))
      .catch(() => { localStorage.removeItem(LS_KEY); setToken(""); });
  }, [token]);

  if (!token || !me) {
    return <Login onLogged={(tk) => {
      localStorage.setItem(LS_KEY, tk); setToken(tk);
    }} />;
  }
  return <Dashboard token={token} me={me}
                       reload={() => axios.get(`${API}/me`,
                         { headers: { Authorization: `Bearer ${token}` } })
                         .then((r) => setMe(r.data))}
                       onLogout={() => {
                         localStorage.removeItem(LS_KEY); setToken("");
                       }} />;
}

function Login({ onLogged }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const r = await axios.post(`${API}/auth/login`,
                                    { email, password });
      onLogged(r.data.access_token);
    } catch (ex) {
      setErr(ex?.response?.data?.detail || "Falha no login");
    }
    setBusy(false);
  };
  return (
    <div data-testid="partner-portal-login"
          style={{ position: "relative",
                     minHeight: "100vh", width: "100%",
                     overflow: "hidden",
                     fontFamily: "'Sora', 'Inter', system-ui, sans-serif",
                     backgroundImage: "url(/partner-login-bg.png)",
                     backgroundSize: "cover",
                     backgroundPosition: "center",
                     backgroundRepeat: "no-repeat" }}>
      <form onSubmit={submit}
              data-testid="partner-portal-login-card"
              style={{ position: "absolute",
                        right: "clamp(16px, 4vw, 56px)",
                        bottom: "clamp(16px, 4vh, 56px)",
                        background: "rgba(255,255,255,.16)",
                        backdropFilter: "blur(28px) saturate(180%)",
                        WebkitBackdropFilter: "blur(28px) saturate(180%)",
                        padding: 32,
                        borderRadius: 24,
                        border: "1px solid rgba(255,255,255,.35)",
                        maxWidth: 400, width: "calc(100% - 32px)",
                        boxShadow: "0 20px 50px rgba(15,23,42,.22)" }}>
        <div style={{ textAlign: "center", marginBottom: 22 }}>
          <img src="/ligo-logo.png" alt="Ligo Fibra"
            style={{ height: 110, width: "auto",
              display: "inline-block", marginBottom: 14,
              background: "transparent" }} />
          <div style={{ fontSize: 10.5, fontWeight: 800,
                            letterSpacing: 2.2, textTransform: "uppercase",
                            color: "#6D28D9",
                            textShadow: "0 1px 0 rgba(255,255,255,.6)",
                            margin: "0 0 6px" }}>
            Portal do Parceiro
          </div>
          <h1 style={{ fontSize: 22, fontWeight: 900,
                         margin: "0 0 6px",
                         letterSpacing: "-.025em",
                         color: "#0F172A",
                         textShadow: "0 1px 0 rgba(255,255,255,.5)" }}>
            Bem-vindo de volta
          </h1>
          <p style={{ color: "#1F2937",
                        fontSize: 12.5, margin: 0, lineHeight: 1.5,
                        fontWeight: 500 }}>
            Acesse pra gerenciar suas promoções e validar QR Code dos
            clientes Ligo no caixa.
          </p>
        </div>
        <div style={{ display: "grid", gap: 12 }}>
          <label style={lbl}>E-mail
            <input type="email" required autoFocus value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="loja@parceiro.com"
                    data-testid="partner-portal-email"
                    style={inp} />
          </label>
          <label style={lbl}>Senha
            <input type="password" required value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    data-testid="partner-portal-password"
                    style={inp} />
          </label>
          {err && (
            <div style={{ background: "#FEE2E2",
                            border: "1px solid #FCA5A5",
                            color: "#991B1B", borderRadius: 10,
                            padding: "9px 12px",
                            fontSize: 12, fontWeight: 700 }}
                  data-testid="partner-portal-err">{err}</div>
          )}
          <button type="submit" disabled={busy}
                   data-testid="partner-portal-login-btn"
                   style={{ padding: 14,
                              background: "#FF6A1A",
                              color: "white", border: 0, borderRadius: 12,
                              fontWeight: 900, cursor: "pointer",
                              fontSize: 14, letterSpacing: .3,
                              boxShadow: "0 14px 30px rgba(255,106,26,.32)" }}>
            {busy ? "Entrando…" : "Entrar →"}
          </button>
        </div>
        <div style={{ marginTop: 16, paddingTop: 14,
                          borderTop: "1px solid rgba(255,255,255,.45)",
                          textAlign: "center", fontSize: 12,
                          color: "#1F2937", lineHeight: 1.55,
                          fontWeight: 500 }}>
          Não tem cadastro?{" "}
          <a href="/seja-parceiro"
            style={{ color: "#6D28D9", fontWeight: 800,
                       textDecoration: "none" }}>
            Quero ser parceiro →
          </a>
        </div>
      </form>
    </div>
  );
}

function Dashboard({ token, me, reload, onLogout }) {
  const [promos, setPromos] = useState([]);
  const [reds, setReds] = useState([]);
  const [history, setHistory] = useState([]);  // iter215bp
  const [historyOpen, setHistoryOpen] = useState(false);  // iter215bp
  const [showScanner, setShowScanner] = useState(false);
  const [selPromo, setSelPromo] = useState("");
  const [result, setResult] = useState(null);
  const h = { headers: { Authorization: `Bearer ${token}` } };

  const loadAll = async () => {
    const [pr, rd] = await Promise.all([
      axios.get(`${API}/promotions`, h),
      axios.get(`${API}/redemptions?limit=80`, h),
    ]);
    setPromos(pr.data); setReds(rd.data);
    if (pr.data?.length && !selPromo) setSelPromo(pr.data[0].id);
  };
  const loadHistory = async () => {
    try {
      const r = await axios.get(`${API}/history?limit=200`, h);
      setHistory(r.data?.items || []);
    } catch { setHistory([]); }
  };
  useEffect(() => { loadAll(); reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const onScanResult = async (qr) => {
    try {
      const r = await axios.post(`${API}/scan`,
                                    { qr_token: qr,
                                      promotion_id: selPromo }, h);
      setResult({ ...r.data, ok: r.data.ok });
    } catch (ex) {
      setResult({ ok: false,
                     reason: ex?.response?.data?.detail || ex.message });
    }
    setShowScanner(false);
    loadAll(); reload();
    if (historyOpen) loadHistory();
  };

  return (
    <div className="pa-partner" data-testid="partner-portal-dashboard">
      <header className="pa-p-topbar">
        <div>
          <div style={{ fontSize: 17, fontWeight: 800 }}>
            {me.partner?.name || me.user.name}
          </div>
          <div style={{ fontSize: 11,
                          color: "rgba(255,255,255,.5)" }}>
            {me.user.email} · {me.user.role}
          </div>
        </div>
        <button onClick={onLogout}
                 data-testid="partner-portal-logout"
                 style={{ background: "transparent",
                            color: "rgba(255,255,255,.8)",
                            border: "1px solid rgba(255,255,255,.15)",
                            padding: "7px 14px", borderRadius: 6,
                            fontSize: 12, cursor: "pointer" }}>
          Sair
        </button>
      </header>

      <main className="pa-p-shell">
        <div className="pa-p-kpis">
          <Kpi label="Promoções ativas" value={promos.length}
                color="#3b82f6" />
          <Kpi label="Redenções pendentes" value={me.pending_count}
                color="#f59e0b" />
          <Kpi label="A receber"
                value={`R$ ${(me.pending_payout || 0).toFixed(2)}`}
                color="#10b981" />
        </div>

        <div className="pa-p-scan-card">
          <h3>Escaneie o QR do cliente</h3>
          <p>
            Selecione a promoção, abra a câmera e aponte para o QR do
            app Ligo.
          </p>
          {!promos.length ? (
            <p style={{ color: "#fca5a5" }}>
              Sem promoções ativas. Contate o gestor Ligo.
            </p>
          ) : (
            <>
              <select value={selPromo}
                       onChange={(e) => setSelPromo(e.target.value)}
                       data-testid="partner-promo-select"
                       style={{ padding: "11px 14px", borderRadius: 10,
                                  background: "rgba(15,23,42,.95)",
                                  border: "1px solid rgba(255,255,255,.1)",
                                  color: "white", fontSize: 14,
                                  marginBottom: 14, minWidth: 260,
                                  fontWeight: 600 }}>
                {promos.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title} · R$ {p.reimbursement_value}
                  </option>
                ))}
              </select>
              <br />
              <button onClick={() => setShowScanner(true)}
                       data-testid="partner-open-scanner"
                       className="pa-p-cta">
                Abrir Scanner
              </button>
            </>
          )}
        </div>

        <div className="pa-p-list">
          <h4>Últimas redenções</h4>
          {!reds.length && (
            <div style={{ color: "rgba(255,255,255,.4)",
                            fontSize: 12, padding: 18,
                            textAlign: "center" }}>
              Sem registros ainda.
            </div>
          )}
          {reds.map((r) => (
            <div key={r.id} className="pa-p-row"
                  data-testid={`partner-red-${r.id}`}>
              <div>
                <b>{r.client_name}</b>
                <div className="meta">
                  {r.promotion_title} · {r.voucher_code} ·{" "}
                  {new Date(r.redeemed_at).toLocaleString("pt-BR")}
                </div>
              </div>
              <div className="val">R$ {r.reimbursement_value?.toFixed(2)}</div>
            </div>
          ))}
        </div>

        {/* iter215bp — Histórico completo (sucessos + recusas + estornos) */}
        <div className="pa-p-list" data-testid="partner-history-section"
              style={{ marginTop: 18 }}>
          <div style={{ display: "flex", alignItems: "center",
                          gap: 10, marginBottom: 8 }}>
            <h4 style={{ margin: 0 }}>Histórico completo</h4>
            <button onClick={() => {
              const next = !historyOpen;
              setHistoryOpen(next);
              if (next && !history.length) loadHistory();
            }} data-testid="partner-history-toggle"
              style={{
                background: "transparent",
                border: "1px solid rgba(255,255,255,.25)",
                color: "rgba(255,255,255,.85)",
                padding: "4px 12px", borderRadius: 14, fontSize: 11,
                fontWeight: 700, cursor: "pointer",
              }}>
              {historyOpen ? "Ocultar" : "Mostrar"}
            </button>
            {historyOpen && (
              <button onClick={loadHistory}
                data-testid="partner-history-reload"
                style={{
                  background: "transparent",
                  border: "1px solid rgba(255,255,255,.15)",
                  color: "rgba(255,255,255,.6)",
                  padding: "4px 10px", borderRadius: 14, fontSize: 10,
                  cursor: "pointer", marginLeft: "auto",
                }}>
                Atualizar
              </button>
            )}
          </div>
          {historyOpen && (
            !history.length ? (
              <div style={{ color: "rgba(255,255,255,.4)",
                              fontSize: 12, padding: 14,
                              textAlign: "center" }}>
                Sem eventos registrados.
              </div>
            ) : (
              history.map((it) => {
                const isOk = it.outcome === "success" && !it.reversed;
                const isReversed = it.reversed || it.outcome === "reversed";
                const color = isReversed ? "#b42318"
                  : (isOk ? "#10b981"
                    : (it.outcome === "duplicate_30s"
                      || it.outcome === "limit_reached" ? "#f28c28"
                      : "#94a3b8"));
                const labels = {
                  success: "Sucesso",
                  duplicate_30s: "Duplicado <30s",
                  limit_reached: "Limite",
                  inactive_client: "Inativo",
                  delinquent: "Inadimplente",
                  too_new: "Contrato novo",
                  promo_inactive: "Promo off",
                  wrong_tenant: "Outra op.",
                  qr_invalid: "QR inválido",
                  qr_expired: "QR expirado",
                  ineligible: "Inelegível",
                  reversed: "Estornado",
                };
                return (
                  <div key={it.id} className="pa-p-row"
                        data-testid={`partner-history-row-${it.id}`}
                        style={isReversed ? { opacity: .55 } : null}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", alignItems: "center",
                                      gap: 8, marginBottom: 2 }}>
                        <span style={{
                          background: color, color: "white",
                          padding: "2px 8px", borderRadius: 10,
                          fontSize: 9, fontWeight: 800,
                          textTransform: "uppercase", letterSpacing: .4,
                        }}>
                          {isReversed && isOk
                            ? "Estornado"
                            : (labels[it.outcome] || it.outcome)}
                        </span>
                        <b style={{ fontSize: 13 }}>
                          {it.client_name || "—"}
                        </b>
                      </div>
                      <div className="meta">
                        {it.promotion_title || "—"}
                        {it.voucher_code && ` · ${it.voucher_code}`}
                        {" · "}
                        {new Date(it.attempted_at).toLocaleString("pt-BR")}
                      </div>
                      {it.reason && (
                        <div style={{ fontSize: 10,
                                        color: "rgba(255,255,255,.45)",
                                        marginTop: 2 }}>
                          {it.reason}
                        </div>
                      )}
                    </div>
                    {isOk && it.reimbursement_value != null && (
                      <div className="val">
                        R$ {Number(it.reimbursement_value).toFixed(2)}
                      </div>
                    )}
                  </div>
                );
              })
            )
          )}
        </div>
      </main>

      {showScanner && (
        <ScannerOverlay onResult={onScanResult}
                          onClose={() => setShowScanner(false)} />
      )}
      {result && (
        <ResultOverlay r={result} onClose={() => setResult(null)} />
      )}
    </div>
  );
}

function Kpi({ label, value, color }) {
  return (
    <div className="pa-p-kpi" style={{ borderTopColor: color }}>
      <div className="pa-p-kpi-val" style={{ color }}>{value}</div>
      <div className="pa-p-kpi-lbl">{label}</div>
    </div>
  );
}

function ScannerOverlay({ onResult, onClose }) {
  const ref = useRef(null);
  const idRef = useRef("pa-qr-region-" + Math.random().toString(36).slice(2));
  const [msg, setMsg] = useState("Aponte para o QR do cliente…");
  const [scanner, setScanner] = useState(null);

  useEffect(() => {
    const id = idRef.current;
    const sc = new Html5Qrcode(id);
    setScanner(sc);
    sc.start({ facingMode: "environment" },
                { fps: 10, qrbox: { width: 280, height: 280 } },
                (decoded) => {
                  setMsg("✅ QR detectado, validando…");
                  sc.stop().catch(() => {});
                  onResult(decoded);
                },
                () => {})
      .catch((e) => setMsg("Erro câmera: " + e.message));
    return () => {
      try { sc.stop().catch(() => {}); sc.clear(); } catch { /* */ }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const close = () => {
    try { scanner?.stop().catch(() => {}); scanner?.clear(); } catch { /* */ }
    onClose();
  };

  return (
    <div className="pa-scan-overlay" data-testid="partner-scanner">
      <div className="pa-scan-header">
        <div style={{ fontWeight: 800 }}>Escanear QR Ligo</div>
        <button onClick={close}
                 data-testid="partner-scanner-close"
                 style={{ background: "transparent",
                            border: 0, color: "white",
                            fontSize: 22, cursor: "pointer" }}>✕</button>
      </div>
      <div className="pa-scan-cam">
        <div id={idRef.current} ref={ref}
              style={{ width: "100%", maxWidth: 480,
                        height: "auto", margin: "0 auto" }} />
        <div className="pa-scan-frame" />
        <div className="pa-scan-msg">{msg}</div>
      </div>
    </div>
  );
}

function ResultOverlay({ r, onClose }) {
  const isOk = !!r.ok;
  return (
    <div className="pa-scan-overlay" data-testid="partner-result"
          onClick={onClose}
          style={{ display: "flex", alignItems: "center",
                     justifyContent: "center" }}>
      <div className={`pa-result ${isOk ? "ok" : "fail"}`}
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: 420, width: "calc(100% - 28px)" }}>
        <h2>{isOk ? "✅ Promoção aplicada!" : "Não foi possível aplicar"}</h2>
        {r.client && <div className="name">{r.client.name}</div>}
        {r.client?.pppoe && (
          <div className="why">PPPoE: {r.client.pppoe}</div>
        )}
        {r.promotion && (
          <div className="why">
            {r.promotion.title} · {r.promotion.offer_summary}
          </div>
        )}
        {!isOk && r.reason && <div className="why">{r.reason}</div>}
        {isOk && r.voucher_code && (
          <div className="voucher">{r.voucher_code}</div>
        )}
        <div style={{ marginTop: 18 }}>
          <button onClick={onClose}
                   data-testid="partner-result-close"
                   style={{ padding: "10px 18px",
                              background: isOk ? "#10b981" : "#475569",
                              color: "white", border: 0,
                              borderRadius: 8, fontWeight: 800,
                              cursor: "pointer" }}>
            OK
          </button>
        </div>
      </div>
    </div>
  );
}

const lbl = { fontSize: 10.5, color: "#0F172A",
                 textTransform: "uppercase", letterSpacing: 1.4,
                 fontWeight: 800,
                 textShadow: "0 1px 0 rgba(255,255,255,.5)" };
const inp = { width: "100%", padding: "12px 14px",
                background: "rgba(255,255,255,.72)",
                border: "1.5px solid rgba(255,255,255,.7)",
                color: "#0F172A", borderRadius: 12,
                fontSize: 15, outline: "none",
                boxSizing: "border-box", marginTop: 6,
                fontFamily: "inherit",
                backdropFilter: "blur(8px)",
                WebkitBackdropFilter: "blur(8px)" };
