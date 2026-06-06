/* ClientPortalApp.js — App do cliente final.
   Acionado por ?portal=cliente
   - Login (email + senha)
   - Lista de promoções disponíveis
   - Menu "3 pontinhos" com o QR code do cliente
*/
import React, { useEffect, useState } from "react";
import axios from "axios";
import { QRCodeSVG } from "qrcode.react";
import "@/parceria/parceria.css";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api/cliente-portal`;
const LS_KEY = "client_portal_token";

export default function ClientPortalApp() {
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
                       reloadMe={() => axios.get(`${API}/me`, {
                         headers: { Authorization: `Bearer ${token}` },
                       }).then((r) => setMe(r.data))}
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
    <div className="pa-public" data-testid="client-portal-login"
          style={{ display: "grid", placeItems: "center",
                     minHeight: "100vh", padding: 20, color: "white" }}>
      <form onSubmit={submit}
              style={{ background: "#0f172a", padding: 32,
                        borderRadius: 16,
                        border: "1px solid rgba(255,255,255,.06)",
                        maxWidth: 420, width: "100%",
                        boxShadow: "0 30px 80px rgba(0,0,0,.5)" }}>
        <div style={{ textAlign: "center", marginBottom: 18 }}>
          <div style={{ fontSize: 38 }}></div>
          <h1 style={{ fontSize: 24, fontWeight: 800,
                         margin: "6px 0 4px",
                         letterSpacing: "-.02em",
                         color: "white" }}>
            App do Cliente Ligo
          </h1>
          <p style={{ color: "rgba(255,255,255,.55)",
                        fontSize: 13, margin: 0 }}>
            Acesse promoções exclusivas e sua identidade Ligo.
          </p>
        </div>
        <div style={{ display: "grid", gap: 12 }}>
          <label style={{ fontSize: 11,
                            color: "rgba(255,255,255,.5)",
                            textTransform: "uppercase",
                            letterSpacing: 1, fontWeight: 700 }}>
            E-mail cadastrado
            <input type="email" required autoFocus value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="seu@email.com"
                    data-testid="client-portal-email"
                    style={inp} />
          </label>
          <label style={{ fontSize: 11,
                            color: "rgba(255,255,255,.5)",
                            textTransform: "uppercase",
                            letterSpacing: 1, fontWeight: 700 }}>
            Senha
            <input type="password" required value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    data-testid="client-portal-password"
                    style={inp} />
          </label>
          {err && (
            <div style={{ background: "rgba(220,38,38,.12)",
                            border: "1px solid rgba(220,38,38,.4)",
                            color: "#fca5a5", borderRadius: 8,
                            padding: "9px 12px",
                            fontSize: 12, fontWeight: 700 }}
                  data-testid="client-portal-err">{err}</div>
          )}
          <button type="submit" disabled={busy}
                   data-testid="client-portal-login-btn"
                   style={{ padding: 13,
                              background: "linear-gradient(135deg,#dc2626,#7f1d1d)",
                              color: "white", border: 0, borderRadius: 10,
                              fontWeight: 800, cursor: "pointer",
                              fontSize: 14,
                              boxShadow: "0 12px 28px rgba(220,38,38,.4)" }}>
            {busy ? "Entrando…" : "Entrar →"}
          </button>
        </div>
      </form>
    </div>
  );
}

function Dashboard({ token, me, reloadMe, onLogout }) {
  const [tab, setTab] = useState("promos");
  const [menu, setMenu] = useState(false);
  const [qr, setQr] = useState(false);
  const [promos, setPromos] = useState([]);
  const [reds, setReds] = useState([]);
  const h = { headers: { Authorization: `Bearer ${token}` } };

  useEffect(() => {
    axios.get(`${API}/promotions`, h).then((r) => setPromos(r.data));
    axios.get(`${API}/my-redemptions`, h).then((r) => setReds(r.data));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const rotate = async () => {
    if (!window.confirm("Gerar um novo QR Code? O antigo será invalidado.")) return;
    await axios.post(`${API}/qr/rotate`, {}, h);
    reloadMe();
  };

  return (
    <div className="pa-client" data-testid="client-portal-dashboard">
      <header className="pa-client-topbar">
        <div className="pa-c-brand">
          <span style={{ fontSize: 26 }}></span>
          <div>
            <div className="pa-c-brand-name">Cliente Ligo</div>
            <div style={{ fontSize: 11, color: "rgba(255,255,255,.5)" }}>
              {me.user.plan_name || "Plano Ligo"}
            </div>
          </div>
        </div>
        <button className="pa-c-dotbtn"
                 onClick={() => setMenu((m) => !m)}
                 aria-label="Menu"
                 data-testid="client-dot-menu">⋯</button>
      </header>

      {menu && (
        <div className="pa-c-menu" data-testid="client-dot-menu-open">
          <button className="pa-c-menu-item"
                   data-testid="client-menu-qr"
                   onClick={() => { setQr(true); setMenu(false); }}>
            <span>🆔</span> Meu QR Code
          </button>
          <button className="pa-c-menu-item"
                   onClick={() => { setTab("history"); setMenu(false); }}>
            <span></span> Meu histórico
          </button>
          <button className="pa-c-menu-item"
                   onClick={() => { setTab("promos"); setMenu(false); }}>
            <span></span> Promoções
          </button>
          <div className="pa-c-menu-divider" />
          <button className="pa-c-menu-item danger"
                   data-testid="client-menu-logout"
                   onClick={onLogout}>
            <span>⎋</span> Sair
          </button>
        </div>
      )}

      <main className="pa-c-content">
        <h2 className="pa-c-hello">Olá, {(me.user.name || "").split(" ")[0]}!</h2>
        <p className="pa-c-status">
          {me.is_eligible
            ? <span className="ok">● Conta ativa · pronta para usar promoções</span>
            : <span className="warn">● Verifique sua mensalidade antes de resgatar</span>}
          {" · "}{me.user.status}
        </p>

        {tab === "promos" && (
          <>
            <h3 style={{ fontSize: 13, fontWeight: 800,
                            letterSpacing: 1, textTransform: "uppercase",
                            color: "rgba(255,255,255,.55)",
                            margin: "12px 0 14px" }}>
              Promoções disponíveis
            </h3>
            {!promos.length && (
              <div style={{ textAlign: "center", padding: 40,
                              color: "rgba(255,255,255,.4)",
                              fontSize: 13 }}>
                Nenhuma promoção ativa agora.
              </div>
            )}
            {promos.map((p) => (
              <article key={p.id} className="pa-c-promo"
                        data-testid={`client-promo-${p.id}`}>
                {p.image_url && (
                  <img src={p.image_url} alt={p.title}
                        className="pa-c-promo-img"
                        onError={(e) => { e.currentTarget.style.display = "none"; }} />
                )}
                <div className="pa-c-promo-body">
                  <div className="pa-c-promo-title">{p.title}</div>
                  <div className="pa-c-promo-partner">
                    {p.partner_name} · {p.partner_category}
                  </div>
                  <div className="pa-c-promo-offer">{p.offer_summary}</div>
                </div>
              </article>
            ))}
          </>
        )}

        {tab === "history" && (
          <>
            <h3 style={{ fontSize: 13, fontWeight: 800,
                            letterSpacing: 1, textTransform: "uppercase",
                            color: "rgba(255,255,255,.55)",
                            margin: "12px 0 14px" }}>
              Meu histórico
            </h3>
            {!reds.length && (
              <div style={{ textAlign: "center", padding: 40,
                              color: "rgba(255,255,255,.4)",
                              fontSize: 13 }}>
                Você ainda não resgatou nenhuma promoção.
              </div>
            )}
            {reds.map((r) => (
              <RedemptionCard key={r.id} r={r} token={token}
                                onRated={() => axios.get(
                                  `${API}/my-redemptions`, h)
                                  .then((x) => setReds(x.data))} />
            ))}
          </>
        )}
      </main>

      {qr && (
        <QrModal qrPayload={me.qr_payload}
                  name={me.user.name}
                  pppoe={me.user.pppoe_user}
                  onClose={() => setQr(false)}
                  onRotate={rotate} />
      )}
    </div>
  );
}

function QrModal({ qrPayload, name, pppoe, onClose, onRotate }) {
  return (
    <div className="pa-qr-overlay" onClick={onClose}
          data-testid="client-qr-modal">
      <div className="pa-qr-card" onClick={(e) => e.stopPropagation()}>
        <button className="pa-qr-close" onClick={onClose}>✕</button>
        <div className="pa-qr-title">SUA IDENTIDADE LIGO</div>
        <div className="pa-qr-name">{name}</div>
        <div className="pa-qr-wrap">
          <QRCodeSVG value={qrPayload} size={240}
                       bgColor="#ffffff" fgColor="#0f172a"
                       level="M" includeMargin={false} />
        </div>
        <div className="pa-qr-foot">
          Mostre este QR ao parceiro Ligo para resgatar uma promoção.<br />
          PPPoE: <b>{pppoe || "—"}</b>
        </div>
        <button className="pa-qr-rotate" onClick={onRotate}>
          Renovar QR (segurança)
        </button>
      </div>
    </div>
  );
}

const inp = {
  width: "100%", padding: "12px 14px",
  background: "rgba(15,23,42,.7)",
  border: "1px solid rgba(255,255,255,.08)",
  color: "white", borderRadius: 10,
  fontSize: 15, outline: "none",
  boxSizing: "border-box", marginTop: 6,
};

// ─── Card de redenção (com avaliação por estrelas) ──────────
function RedemptionCard({ r, token, onRated }) {
  const [rating, setRating] = useState(r.rating || 0);
  const [hover, setHover] = useState(0);
  const [comment, setComment] = useState("");
  const [showComment, setShowComment] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(!!r.rating);

  const submit = async (stars) => {
    setBusy(true);
    try {
      await axios.post(`${API}/rate`,
        { redemption_id: r.id, stars, comment },
        { headers: { Authorization: `Bearer ${token}` } });
      setDone(true); setRating(stars);
      onRated?.();
    } catch (e) {
      if (e?.response?.status === 409) setDone(true);
      else alert(e?.response?.data?.detail || e.message);
    }
    setBusy(false);
  };

  return (
    <div style={{ background: "#0f172a",
                    border: "1px solid rgba(255,255,255,.06)",
                    borderRadius: 10, padding: 14,
                    marginBottom: 8 }}
          data-testid={`client-red-${r.id}`}>
      <div style={{ fontWeight: 800, fontSize: 14 }}>
        ✅ {r.promotion_title}
      </div>
      <div style={{ fontSize: 11, color: "rgba(255,255,255,.5)",
                      marginTop: 4 }}>
        {r.partner_name} ·{" "}
        {new Date(r.redeemed_at).toLocaleString("pt-BR")}
        {" · "}cupom <b>{r.voucher_code}</b>
      </div>
      <div style={{ marginTop: 12, paddingTop: 10,
                      borderTop: "1px solid rgba(255,255,255,.06)" }}>
        {done ? (
          <div style={{ display: "flex", alignItems: "center", gap: 8,
                          fontSize: 12, color: "#fcd34d" }}>
            <span>Sua avaliação:</span>
            {Array.from({ length: 5 }, (_, i) => (
              <span key={i} style={{ fontSize: 18,
                color: i < rating ? "#f59e0b" : "rgba(255,255,255,.2)" }}>
                
              </span>
            ))}
          </div>
        ) : (
          <>
            <div style={{ fontSize: 11, color: "rgba(255,255,255,.6)",
                            marginBottom: 6,
                            textTransform: "uppercase",
                            letterSpacing: 1, fontWeight: 700 }}>
              ⭐ Avalie este resgate
            </div>
            <div style={{ display: "flex", gap: 4,
                            alignItems: "center" }}>
              {Array.from({ length: 5 }, (_, i) => {
                const v = i + 1;
                return (
                  <button key={v} disabled={busy}
                           data-testid={`client-rate-${r.id}-${v}`}
                           onMouseEnter={() => setHover(v)}
                           onMouseLeave={() => setHover(0)}
                           onClick={() => {
                             setRating(v);
                             setShowComment(true);
                           }}
                           style={{
                             background: "transparent", border: 0,
                             cursor: "pointer", fontSize: 26,
                             padding: 2,
                             color: v <= (hover || rating)
                               ? "#f59e0b" : "rgba(255,255,255,.22)",
                             transition: "all .12s",
                           }}>
                    
                  </button>
                );
              })}
              {rating > 0 && !showComment && (
                <button onClick={() => submit(rating)} disabled={busy}
                         style={{ marginLeft: "auto",
                                    padding: "6px 14px",
                                    background: "#6b1fb1",
                                    color: "white",
                                    border: 0, borderRadius: 6,
                                    fontSize: 12, fontWeight: 700,
                                    cursor: "pointer" }}>
                  Enviar
                </button>
              )}
            </div>
            {showComment && (
              <>
                <textarea value={comment}
                            onChange={(e) =>
                              setComment(e.target.value)}
                            placeholder="Deixe um comentário (opcional)…"
                            maxLength={300}
                            style={{ width: "100%",
                                       marginTop: 8,
                                       background: "rgba(255,255,255,.04)",
                                       border: "1px solid rgba(255,255,255,.1)",
                                       color: "white",
                                       padding: "8px 12px",
                                       borderRadius: 8, fontSize: 12,
                                       minHeight: 50,
                                       boxSizing: "border-box" }} />
                <button onClick={() => submit(rating)} disabled={busy}
                         data-testid={`client-rate-${r.id}-submit`}
                         style={{ marginTop: 6,
                                    padding: "7px 16px",
                                    background: "#6b1fb1",
                                    color: "white",
                                    border: 0, borderRadius: 6,
                                    fontSize: 12, fontWeight: 700,
                                    cursor: "pointer" }}>
                  {busy ? "Enviando…" : `Enviar ${rating} estrela${rating === 1 ? "" : "s"}`}
                </button>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
