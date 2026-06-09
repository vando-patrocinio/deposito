/* ParceiroPWA — App mobile do parceiro comercial.
 *
 * iter230 — fluxo solicitado pelo usuário:
 *   1) Acesso via link único `/parceiro/{magic_token}` (similar ao link
 *      do colaborador). Autologin chama POST /parceiro-portal/auth/magic.
 *   2) Onboarding (perfil): se faltam endereço/WhatsApp/logo → tela de
 *      cadastro obrigatório.
 *   3) Hub: minhas promoções + 3 pontinhos → scanner QR + minhas redenções.
 *   4) Criar/editar promoção: imagem + título + descrição/regras + %.
 *   5) Scanner QR: lê QR do cliente Ligo, cria redenção automaticamente.
 *   6) Redenções: lista clientes que resgataram (visível aqui + no admin
 *      Parcerias Comerciais/Redenções).
 */
import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft, Camera, Check, Edit3, LogOut, MapPin, MoreVertical,
  Plus, QrCode, Receipt, Tag, Upload, X,
} from "lucide-react";

const BACKEND = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND}/api/parceiro-portal`;
const LS_TOKEN = "ligo_parceiro_token";

/* ─────────────────── Feedback sonoro/tátil ───────────────────
   Beep curto via Web Audio (sem precisar de asset) + vibração
   curta. Útil pra confirmar leitura do QR sem o parceiro precisar
   olhar a tela em ambiente barulhento (caixa de loja). */
let _audioCtx = null;
function _ensureAudioCtx() {
  if (typeof window === "undefined") return null;
  if (_audioCtx) return _audioCtx;
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    _audioCtx = new Ctx();
  } catch { _audioCtx = null; }
  return _audioCtx;
}
function _beep(freq, durMs, vol = 0.18) {
  const ctx = _ensureAudioCtx();
  if (!ctx) return;
  try {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine"; osc.frequency.value = freq;
    gain.gain.value = vol;
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + durMs / 1000);
    // fade out pra evitar click
    gain.gain.exponentialRampToValueAtTime(
      0.0001, ctx.currentTime + durMs / 1000);
  } catch { /* */ }
}
function playSuccessFeedback() {
  // 2 beeps ascendentes (Ré → Lá) + vibração curta
  _beep(587, 120);                       // D5
  setTimeout(() => _beep(880, 160), 140); // A5
  try { navigator.vibrate && navigator.vibrate([60, 40, 80]); } catch { /* */ }
}
function playErrorFeedback() {
  // 1 beep grave + vibração padrão de erro
  _beep(220, 280, 0.22);                 // A3
  try { navigator.vibrate && navigator.vibrate([180, 60, 180]); } catch { /* */ }
}

const COLORS = {
  // iter232 — tema claro (era dark slate). Mantém purple + orange Ligo
  // como destaque sobre fundo claro pra ficar coerente com /cliente.
  bg: "#F8F5FF",        // fundo geral lilás clarinho
  surface: "#FFFFFF",   // cards
  surface2: "#F4F1FF",  // inputs / áreas sutis
  text: "#1E1B4B",      // texto principal (purple-deep)
  muted: "#64748B",     // texto secundário
  line: "#E0D5FF",      // bordas (purple-soft)
  brand: "#7c3aed",
  brandSoft: "#a78bfa",
  orange: "#FF6A1A",
  green: "#10b981",
  red: "#ef4444",
};

export default function ParceiroPWA({ magicToken }) {
  const [bootState, setBootState] = useState("loading"); // loading|ok|err|fix-profile
  const [token, setToken] = useState(() => localStorage.getItem(LS_TOKEN) || "");
  const [me, setMe] = useState(null);
  const [bootErr, setBootErr] = useState("");
  const [view, setView] = useState("hub"); // hub|edit-promo|new-promo|scan|redemptions|profile

  // ─── boot: troca magic token por JWT, ou usa sessão local ───
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        let tk = token;
        if (magicToken && magicToken !== "stored") {
          const r = await axios.post(`${API}/auth/magic`,
            { magic_token: magicToken });
          tk = r.data.access_token;
          localStorage.setItem(LS_TOKEN, tk);
          if (!alive) return;
          setToken(tk);
        }
        if (!tk) {
          if (alive) {
            setBootErr("Link inválido. Solicite um novo link à Ligo.");
            setBootState("err");
          }
          return;
        }
        const m = await axios.get(`${API}/me`,
          { headers: { Authorization: `Bearer ${tk}` } }).then((r) => r.data);
        if (!alive) return;
        setMe(m);
        const p = m.partner || {};
        const needsProfile = !p.phone || !p.address || !p.logo_url;
        setBootState(needsProfile ? "fix-profile" : "ok");
        if (needsProfile) setView("profile");
      } catch (e) {
        if (alive) {
          setBootErr(e?.response?.data?.detail || "Não foi possível abrir.");
          localStorage.removeItem(LS_TOKEN);
          setBootState("err");
        }
      }
    })();
    return () => { alive = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [magicToken]);

  const refresh = useCallback(async () => {
    if (!token) return;
    const m = await axios.get(`${API}/me`,
      { headers: { Authorization: `Bearer ${token}` } }).then((r) => r.data);
    setMe(m);
    return m;
  }, [token]);

  const logout = () => {
    localStorage.removeItem(LS_TOKEN);
    window.location.href = "/";
  };

  if (bootState === "loading") {
    return <FullPageMsg msg="Carregando seu painel..." />;
  }
  if (bootState === "err") {
    return <FullPageMsg msg={bootErr} err />;
  }

  return (
    <div data-testid="parceiro-pwa" style={{
      minHeight: "100vh", background: COLORS.bg, color: COLORS.text,
      fontFamily: "'Inter', system-ui, sans-serif",
    }}>
      <style>{`
        body { background: ${COLORS.bg}; }
        .pp-card { background: ${COLORS.surface}; border-radius: 18px;
                    border: 1px solid ${COLORS.line};
                    box-shadow: 0 14px 32px rgba(58,15,138,.08); }
        .pp-cta { background: ${COLORS.orange}; color: #1a0840;
                   border: none; padding: 12px 18px; border-radius: 14px;
                   font-weight: 900; cursor: pointer; font-size: 14px;
                   display: inline-flex; align-items: center; gap: 8px;
                   box-shadow: 0 12px 26px rgba(255,106,26,.32); }
        .pp-input { width: 100%; padding: 12px 14px; border-radius: 12px;
                     background: ${COLORS.surface2}; color: ${COLORS.text};
                     border: 1px solid ${COLORS.line}; font-size: 14px;
                     font-family: inherit; outline: none; box-sizing: border-box; }
        .pp-input:focus { border-color: ${COLORS.brand};
                           box-shadow: 0 0 0 3px ${COLORS.brand}22; }
        .pp-input::placeholder { color: #94A3B8; }
        button { font-family: inherit; }
      `}</style>

      {view === "profile" && (
        <ProfileScreen me={me} token={token}
          mandatory={bootState === "fix-profile"}
          onSaved={async () => { await refresh(); setBootState("ok"); setView("hub"); }}
          onBack={bootState !== "fix-profile" ? () => setView("hub") : null}
          onLogout={logout} />
      )}
      {view === "hub" && me && (
        <HubScreen me={me} token={token}
          onEditPromo={(p) => setView({ name: "edit-promo", promo: p })}
          onNewPromo={() => setView("new-promo")}
          onScan={() => setView("scan")}
          onRedemptions={() => setView("redemptions")}
          onEditProfile={() => setView("profile")}
          onLogout={logout}
          refresh={refresh} />
      )}
      {view === "new-promo" && (
        <PromoForm token={token} me={me}
          onSaved={async () => { await refresh(); setView("hub"); }}
          onBack={() => setView("hub")} />
      )}
      {view && view.name === "edit-promo" && (
        <PromoForm token={token} me={me} promo={view.promo}
          onSaved={async () => { await refresh(); setView("hub"); }}
          onBack={() => setView("hub")} />
      )}
      {view === "scan" && (
        <ScanScreen token={token} me={me}
          onBack={() => setView("hub")}
          onSuccess={async () => { await refresh(); }} />
      )}
      {view === "redemptions" && (
        <RedemptionsScreen token={token}
          onBack={() => setView("hub")} />
      )}
    </div>
  );
}

/* ════════════════════════ FullPageMsg ═════════════════════════ */
function FullPageMsg({ msg, err }) {
  return (
    <div style={{
      minHeight: "100vh", background: COLORS.bg, color: COLORS.text,
      display: "grid", placeItems: "center", padding: 24,
      fontFamily: "'Inter', system-ui, sans-serif", textAlign: "center",
    }}>
      <div data-testid="parceiro-bootmsg" style={{ maxWidth: 360 }}>
        <div style={{
          fontSize: 18, fontWeight: 800,
          color: err ? COLORS.red : COLORS.text,
          marginBottom: 12,
        }}>{err ? "Ops!" : "Aguarde"}</div>
        <p style={{ color: COLORS.muted, lineHeight: 1.5 }}>{msg}</p>
      </div>
    </div>
  );
}

/* ════════════════════════ Top Header ═════════════════════════ */
function Header({ title, subtitle, onBack, onLogout, partner, rightBtn }) {
  return (
    <div data-testid="parceiro-header" style={{
      padding: "18px 18px 14px",
      background: `linear-gradient(135deg, ${COLORS.brand} 0%, #4C1D95 60%, ${COLORS.bg} 100%)`,
      borderBottomLeftRadius: 22, borderBottomRightRadius: 22,
      color: "white", position: "relative",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {onBack && (
            <button onClick={onBack} aria-label="Voltar"
              data-testid="parceiro-header-back"
              style={iconBtn()}><ArrowLeft size={16} /></button>
          )}
          {partner?.logo_url && (
            <img src={partner.logo_url.startsWith("http")
                ? partner.logo_url
                : `${BACKEND}${partner.logo_url}`}
              alt="logo" style={{
                width: 38, height: 38, borderRadius: 12,
                objectFit: "cover",
                border: "1.5px solid rgba(255,255,255,.4)",
              }} />
          )}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {rightBtn}
          {onLogout && (
            <button onClick={onLogout} aria-label="Sair"
              data-testid="parceiro-header-logout"
              style={iconBtn()}><LogOut size={14} /></button>
          )}
        </div>
      </div>
      <div style={{ marginTop: 16 }}>
        {subtitle && (
          <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 2,
                          textTransform: "uppercase", opacity: .8 }}>{subtitle}</div>
        )}
        <h1 style={{ margin: "4px 0 0", fontSize: 26, fontWeight: 900,
                       letterSpacing: "-.02em" }}>{title}</h1>
      </div>
    </div>
  );
}
function iconBtn() {
  return {
    width: 36, height: 36, borderRadius: 10,
    background: "rgba(255,255,255,.15)",
    border: "1px solid rgba(255,255,255,.22)",
    color: "white", cursor: "pointer", padding: 0,
    display: "inline-flex", alignItems: "center", justifyContent: "center",
  };
}

/* ════════════════════════ HUB ═════════════════════════ */
function HubScreen({ me, token, onEditPromo, onNewPromo, onScan,
  onRedemptions, onEditProfile, onLogout, refresh }) {
  const [promos, setPromos] = useState([]);
  const [menuOpen, setMenuOpen] = useState(false);
  // Live stats do dia (gamificação): atualizado via polling + após cada scan
  const [todayStats, setTodayStats] = useState({
    today_count: 0, today_due: 0, pending_count: 0, pending_due: 0,
  });

  const fetchStats = useCallback(() => {
    if (!token) return;
    axios.get(`${API}/today-stats`,
      { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => setTodayStats(r.data))
      .catch(() => {});
  }, [token]);

  useEffect(() => {
    if (!token) return;
    axios.get(`${API}/promotions`,
      { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => setPromos(r.data || []))
      .catch(() => setPromos([]));
    fetchStats();
    // polling a cada 30s pra refletir scans feitos em outros dispositivos
    const iv = setInterval(fetchStats, 30000);
    return () => clearInterval(iv);
  }, [token, fetchStats]);

  const p = me?.partner || {};

  return (
    <>
      <Header title={p.name || "Meu Negócio"} subtitle="Parceiro Ligo"
        partner={p} onLogout={onLogout}
        rightBtn={
          <div style={{ position: "relative" }}>
            <button data-testid="parceiro-menu-btn"
              onClick={() => setMenuOpen((v) => !v)}
              aria-label="Mais opções"
              style={iconBtn()}><MoreVertical size={16} /></button>
            {menuOpen && (
              <>
                <div onClick={() => setMenuOpen(false)} style={{
                  position: "fixed", inset: 0, zIndex: 8,
                }} />
                <div style={{
                  position: "absolute", top: 44, right: 0, zIndex: 9,
                  background: COLORS.surface, border: `1px solid ${COLORS.line}`,
                  borderRadius: 12, overflow: "hidden", minWidth: 220,
                  boxShadow: "0 18px 40px rgba(58,15,138,.22)",
                }}>
                  <MenuItem icon={<QrCode size={16} />}
                    label="Ler QR Code do cliente"
                    testid="parceiro-menu-scan"
                    onClick={() => { setMenuOpen(false); onScan(); }} />
                  <MenuItem icon={<Receipt size={16} />}
                    label="Resgates de clientes"
                    testid="parceiro-menu-redemptions"
                    onClick={() => { setMenuOpen(false); onRedemptions(); }} />
                  <MenuItem icon={<Edit3 size={16} />}
                    label="Editar dados do negócio"
                    testid="parceiro-menu-profile"
                    onClick={() => { setMenuOpen(false); onEditProfile(); }} />
                </div>
              </>
            )}
          </div>
        }
      />

      <div style={{ padding: 18 }}>
        {/* Live counter do dia (gamificação) */}
        {todayStats.today_count > 0 && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            data-testid="parceiro-today-ribbon"
            style={{
              padding: "14px 16px", borderRadius: 14, marginBottom: 14,
              background: "linear-gradient(120deg, #10B981, #059669)",
              color: "white", display: "flex", alignItems: "center",
              justifyContent: "space-between", gap: 12,
              boxShadow: "0 12px 28px rgba(16,185,129,.28)",
            }}>
            <div>
              <div style={{ fontSize: 11, fontWeight: 800, opacity: .85,
                letterSpacing: 1.4, textTransform: "uppercase" }}>
                Hoje no caixa
              </div>
              <div style={{ fontSize: 20, fontWeight: 900,
                marginTop: 2, letterSpacing: "-.01em" }}>
                {todayStats.today_count} resgate{todayStats.today_count !== 1 ? "s" : ""}
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: 11, fontWeight: 800, opacity: .85,
                letterSpacing: 1.4, textTransform: "uppercase" }}>
                A receber
              </div>
              <div style={{ fontSize: 20, fontWeight: 900,
                marginTop: 2, letterSpacing: "-.01em" }}>
                R$ {Number(todayStats.today_due).toFixed(2).replace(".", ",")}
              </div>
            </div>
          </motion.div>
        )}

        {/* Stats */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                         gap: 10 }}>
          <StatBox label="Resgates pendentes"
            value={todayStats.pending_count || me?.pending_count || 0} />
          <StatBox label="A receber"
            value={`R$ ${Number(todayStats.pending_due || me?.pending_payout || 0).toFixed(2).replace(".", ",")}`} />
        </div>

        {/* Promoções */}
        <div style={{ marginTop: 22, display: "flex",
                         justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 900 }}>
            Minhas promoções
          </h2>
          <button className="pp-cta" onClick={onNewPromo}
            data-testid="parceiro-new-promo-btn">
            <Plus size={16} /> Nova
          </button>
        </div>

        <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
          {promos.length === 0 && (
            <div className="pp-card" style={{ padding: 18, textAlign: "center",
                                                  color: COLORS.muted, fontSize: 13 }}>
              Você ainda não cadastrou promoções.
              <br />Toque em “Nova” para começar.
            </div>
          )}
          {promos.map((promo) => (
            <PromoRow key={promo.id} promo={promo}
              onClick={() => onEditPromo(promo)} />
          ))}
        </div>
      </div>
    </>
  );
}

function MenuItem({ icon, label, onClick, testid }) {
  return (
    <button onClick={onClick} data-testid={testid}
      style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "12px 14px", width: "100%", background: "transparent",
        border: "none", borderBottom: `1px solid ${COLORS.line}`,
        color: COLORS.text, fontSize: 13.5, fontWeight: 700,
        cursor: "pointer", textAlign: "left",
      }}>
      {icon}{label}
    </button>
  );
}

function StatBox({ label, value }) {
  return (
    <div className="pp-card" style={{ padding: 14 }}>
      <div style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: 1.6,
                       textTransform: "uppercase", color: COLORS.muted }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 900, marginTop: 4,
                       color: COLORS.text }}>{value}</div>
    </div>
  );
}

function PromoRow({ promo, onClick }) {
  return (
    <button onClick={onClick} className="pp-card"
      data-testid={`promo-row-${promo.id}`}
      style={{
        display: "flex", gap: 12, padding: 12, alignItems: "center",
        cursor: "pointer", textAlign: "left",
        color: COLORS.text, width: "100%",
      }}>
      <div style={{
        width: 60, height: 60, borderRadius: 12, flexShrink: 0,
        background: COLORS.surface2, overflow: "hidden",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        {promo.image_url ? (
          <img src={promo.image_url.startsWith("http")
              ? promo.image_url
              : `${BACKEND}${promo.image_url}`}
            alt={promo.title}
            style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        ) : <Tag size={22} color={COLORS.muted} />}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 800, lineHeight: 1.25,
                         overflow: "hidden", textOverflow: "ellipsis",
                         whiteSpace: "nowrap" }}>{promo.title}</div>
        <div style={{ fontSize: 12, color: COLORS.muted, marginTop: 2 }}>
          {promo.offer_summary || "(sem resumo)"}
        </div>
        <div style={{ marginTop: 5, display: "flex", gap: 6,
                         flexWrap: "wrap" }}>
          {promo.product_category && (
            <span style={pill(COLORS.brandSoft)}>
              {promo.product_category}
            </span>
          )}
          {promo.discount_pct > 0 && (
            <span style={pill(COLORS.orange)}>{promo.discount_pct}% OFF</span>
          )}
          <span style={pill(promo.active ? COLORS.green : COLORS.red)}>
            {promo.active ? "Ativa" : "Inativa"}
          </span>
          <span style={pill(COLORS.muted)}>
            {promo.total_redemptions || 0} resgates
          </span>
        </div>
      </div>
      <Edit3 size={16} color={COLORS.muted} />
    </button>
  );
}
function pill(color) {
  return {
    padding: "2px 8px", borderRadius: 999, fontSize: 10, fontWeight: 800,
    background: `${color}1A`, color, letterSpacing: .4,
  };
}

/* ════════════════════════ Profile (onboarding/edit) ═════════════════════════ */
function ProfileScreen({ me, token, mandatory, onSaved, onBack, onLogout }) {
  const p = me?.partner || {};
  const [form, setForm] = useState({
    name: p.name || "", phone: p.phone || "",
    address: p.address || "", city: p.city || "",
    neighborhood: p.neighborhood || "",
    description: p.description || "",
    logo_url: p.logo_url || "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const upload = async (file) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const r = await axios.post(`${API}/upload-image`,
          { data_url: reader.result },
          { headers: { Authorization: `Bearer ${token}` } });
        setForm((f) => ({ ...f, logo_url: r.data.url }));
      } catch (e) {
        setErr("Falha ao enviar logo: "
          + (e?.response?.data?.detail || e.message));
      }
    };
    reader.readAsDataURL(file);
  };

  const save = async () => {
    if (!form.phone || !form.address || !form.logo_url) {
      setErr("Preencha WhatsApp, endereço e logo.");
      return;
    }
    setBusy(true); setErr("");
    try {
      await axios.put(`${API}/me`, form,
        { headers: { Authorization: `Bearer ${token}` } });
      onSaved();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Erro ao salvar.");
    } finally { setBusy(false); }
  };

  return (
    <>
      <Header title={mandatory ? "Bem-vindo!" : "Editar perfil"}
        subtitle={mandatory ? "Complete seu cadastro" : "Dados do negócio"}
        partner={p} onBack={onBack} onLogout={onLogout} />
      <div style={{ padding: 18, display: "grid", gap: 14 }}>
        {mandatory && (
          <div style={{
            padding: "12px 14px", borderRadius: 12,
            background: "#FFF8E1",
            border: "1px solid #FBBF24",
            color: "#92400E", fontSize: 13, fontWeight: 600,
          }}>
            Pra começar a publicar promoções, precisamos do seu WhatsApp,
            endereço completo e logo.
          </div>
        )}
        <Field label="Nome do negócio"
          value={form.name} testid="profile-name"
          onChange={(v) => setForm({ ...form, name: v })} />
        <Field label="WhatsApp (com DDD)"
          placeholder="(11) 99999-0000"
          value={form.phone} testid="profile-phone"
          onChange={(v) => setForm({ ...form, phone: v })} />
        <Field label="Endereço (rua + número)"
          value={form.address} testid="profile-address"
          onChange={(v) => setForm({ ...form, address: v })} />
        <div style={{ display: "grid", gridTemplateColumns: "2fr 3fr",
                         gap: 10 }}>
          <Field label="Bairro" value={form.neighborhood}
            testid="profile-neighborhood"
            onChange={(v) => setForm({ ...form, neighborhood: v })} />
          <Field label="Cidade" value={form.city}
            testid="profile-city"
            onChange={(v) => setForm({ ...form, city: v })} />
        </div>
        <Field label="Sobre o seu negócio (opcional)"
          textarea value={form.description} testid="profile-description"
          onChange={(v) => setForm({ ...form, description: v })} />

        {/* Logo */}
        <div>
          <label style={fieldLabel()}>Logo do negócio</label>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{
              width: 80, height: 80, borderRadius: 14,
              background: COLORS.surface2, overflow: "hidden",
              display: "flex", alignItems: "center", justifyContent: "center",
              border: `1.5px dashed ${COLORS.line}`,
            }}>
              {form.logo_url ? (
                <img src={form.logo_url.startsWith("http")
                    ? form.logo_url : `${BACKEND}${form.logo_url}`}
                  alt="logo" data-testid="profile-logo-preview"
                  style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              ) : <Camera size={28} color={COLORS.muted} />}
            </div>
            <label data-testid="profile-logo-upload"
              style={{
                ...buttonStyleGhost(), display: "inline-flex", gap: 8,
                cursor: "pointer", alignItems: "center",
              }}>
              <Upload size={14} /> Enviar logo
              <input type="file" accept="image/*"
                onChange={(e) => upload(e.target.files?.[0])}
                style={{ display: "none" }} />
            </label>
          </div>
        </div>

        {err && (
          <div data-testid="profile-error" style={errBox()}>{err}</div>
        )}

        <button onClick={save} disabled={busy}
          data-testid="profile-save-btn"
          style={{ ...buttonStylePrimary(),
                     opacity: busy ? .7 : 1 }}>
          {busy ? "Salvando..." : (mandatory ? "Começar" : "Salvar")}
        </button>
      </div>
    </>
  );
}

/* ════════════════════════ Promo Form ═════════════════════════ */
function PromoForm({ token, promo, onSaved, onBack }) {
  const isEdit = !!promo;
  const [form, setForm] = useState({
    title: promo?.title || "",
    offer_summary: promo?.offer_summary || "",
    description: promo?.description || "",
    terms: promo?.terms || "",
    product_category: promo?.product_category || "",
    discount_pct: promo?.discount_pct || 0,
    image_url: promo?.image_url || "",
    active: promo?.active ?? true,
    max_uses_per_client: promo?.max_uses_per_client || 1,
    period: promo?.period || "month",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const upload = async (file) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const r = await axios.post(`${API}/upload-image`,
          { data_url: reader.result },
          { headers: { Authorization: `Bearer ${token}` } });
        setForm((f) => ({ ...f, image_url: r.data.url }));
      } catch (e) {
        setErr("Falha ao enviar imagem: " + (e?.response?.data?.detail || ""));
      }
    };
    reader.readAsDataURL(file);
  };

  const save = async () => {
    if (!form.title || !form.offer_summary) {
      setErr("Preencha título e resumo da oferta.");
      return;
    }
    setBusy(true); setErr("");
    try {
      if (isEdit) {
        await axios.put(`${API}/promotions/${promo.id}`, form,
          { headers: { Authorization: `Bearer ${token}` } });
      } else {
        await axios.post(`${API}/promotions`, form,
          { headers: { Authorization: `Bearer ${token}` } });
      }
      onSaved();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Erro ao salvar.");
    } finally { setBusy(false); }
  };

  const remove = async () => {
    if (!window.confirm("Desativar esta promoção?")) return;
    setBusy(true);
    try {
      await axios.delete(`${API}/promotions/${promo.id}`,
        { headers: { Authorization: `Bearer ${token}` } });
      onSaved();
    } finally { setBusy(false); }
  };

  return (
    <>
      <Header title={isEdit ? "Editar promoção" : "Nova promoção"}
        subtitle="Visível pros clientes Ligo"
        onBack={onBack} />
      <div style={{ padding: 18, display: "grid", gap: 14 }}>
        {/* Imagem */}
        <div>
          <label style={fieldLabel()}>Imagem do produto</label>
          <label data-testid="promo-image-upload" style={{
            display: "block", width: "100%",
            aspectRatio: "16/10", borderRadius: 14, cursor: "pointer",
            background: COLORS.surface2, overflow: "hidden",
            border: `1.5px dashed ${COLORS.line}`,
            display: "flex", alignItems: "center", justifyContent: "center",
            color: COLORS.muted, position: "relative",
          }}>
            {form.image_url ? (
              <img src={form.image_url.startsWith("http")
                  ? form.image_url : `${BACKEND}${form.image_url}`}
                alt="promoção" style={{ width: "100%", height: "100%",
                                            objectFit: "cover" }} />
            ) : (
              <div style={{ textAlign: "center" }}>
                <Camera size={32} />
                <div style={{ fontSize: 12, marginTop: 6 }}>Tocar para enviar</div>
              </div>
            )}
            <input type="file" accept="image/*"
              onChange={(e) => upload(e.target.files?.[0])}
              style={{ display: "none" }} />
          </label>
        </div>

        <Field label="Título da promoção"
          value={form.title} testid="promo-title"
          onChange={(v) => setForm({ ...form, title: v })} />
        <Field label="Resumo da oferta (curto)"
          placeholder="Ex: Pizza grande por R$1"
          value={form.offer_summary} testid="promo-summary"
          onChange={(v) => setForm({ ...form, offer_summary: v })} />
        <CategoryPicker
          value={form.product_category}
          onChange={(v) => setForm({ ...form, product_category: v })} />
        <Field label="Descrição completa"
          textarea value={form.description} testid="promo-description"
          onChange={(v) => setForm({ ...form, description: v })} />
        <Field label="Regras da promoção (terms)"
          textarea value={form.terms} testid="promo-terms"
          placeholder="Ex: Válido de segunda a quinta. Apenas 1 por cliente."
          onChange={(v) => setForm({ ...form, terms: v })} />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                         gap: 10 }}>
          <Field label="% de desconto" type="number"
            value={form.discount_pct} testid="promo-discount"
            onChange={(v) => setForm({ ...form, discount_pct: Number(v) })} />
          <Field label="Máx. usos por cliente" type="number"
            value={form.max_uses_per_client} testid="promo-max-uses"
            onChange={(v) => setForm({ ...form, max_uses_per_client: Number(v) })} />
        </div>

        <label style={{ display: "flex", alignItems: "center", gap: 8,
                          color: COLORS.text, fontSize: 13.5,
                          padding: "10px 0" }}>
          <input type="checkbox" checked={form.active}
            data-testid="promo-active"
            onChange={(e) => setForm({ ...form, active: e.target.checked })}
            style={{ width: 18, height: 18 }} />
          Promoção ativa (visível para clientes)
        </label>

        {err && <div data-testid="promo-error" style={errBox()}>{err}</div>}

        <button onClick={save} disabled={busy}
          data-testid="promo-save-btn"
          style={{ ...buttonStylePrimary(),
                     opacity: busy ? .7 : 1 }}>
          {busy ? "Salvando..." : (isEdit ? "Salvar alterações" : "Publicar promoção")}
        </button>
        {isEdit && (
          <button onClick={remove} disabled={busy}
            data-testid="promo-delete-btn"
            style={{ ...buttonStyleGhost(), color: COLORS.red,
                       borderColor: COLORS.red }}>
            Desativar promoção
          </button>
        )}
      </div>
    </>
  );
}

/* ════════════════════════ Scan Screen ═════════════════════════ */
function ScanScreen({ token, me, onBack, onSuccess }) {
  const [promos, setPromos] = useState([]);
  const [pickedPromo, setPickedPromo] = useState(null);
  const [qrInput, setQrInput] = useState("");
  const [scanning, setScanning] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");
  // Flash visual no scanner: "ok" (verde) | "err" (vermelho) | null
  const [flash, setFlash] = useState(null);
  // Ref pro Html5Qrcode (precisamos retomar leitura após erro)
  const readerRef = React.useRef(null);
  const triggerFlash = (kind) => {
    setFlash(kind);
    setTimeout(() => setFlash(null), 450);
  };

  useEffect(() => {
    axios.get(`${API}/promotions`,
      { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => setPromos(r.data || []));
  }, [token]);

  /* Inicia leitor html5-qrcode quando promoção foi escolhida */
  useEffect(() => {
    if (!pickedPromo) return;
    let stop = null; let ignore = false;
    (async () => {
      try {
        const { Html5Qrcode, Html5QrcodeSupportedFormats } = await import("html5-qrcode");
        const elId = "parceiro-scanner-box";
        await new Promise((res) => setTimeout(res, 100));
        if (ignore) return;
        const reader = new Html5Qrcode(elId, {
          formatsToSupport: [Html5QrcodeSupportedFormats.QR_CODE],
          verbose: false,
        });
        readerRef.current = reader;
        stop = () => {
          readerRef.current = null;
          return reader.stop().then(() => reader.clear()).catch(() => {});
        };
        await reader.start(
          { facingMode: "environment" },
          {
            fps: 15,
            // Mantém o frame de scan QUADRADO proporcional ao menor lado
            // do viewfinder — corrige enquadramento esticado em retrato.
            qrbox: (vw, vh) => {
              const m = Math.min(vw, vh);
              const side = Math.max(180, Math.floor(m * 0.78));
              return { width: side, height: side };
            },
            aspectRatio: 1.0,
            disableFlip: false,
            videoConstraints: {
              facingMode: "environment",
              focusMode: "continuous",
              advanced: [{ focusMode: "continuous" }],
            },
          },
          async (text) => {
            try { await reader.pause(true); } catch { /* */ }
            handleQr(text);
          },
          () => {},
        );
      } catch (e) {
        setErr("Câmera indisponível. Cole o código manualmente abaixo.");
      }
    })();
    return () => { ignore = true; if (stop) stop(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickedPromo]);

  const handleQr = async (raw) => {
    setScanning(true); setErr(""); setResult(null);
    const rawTrim = (raw || "").trim();
    try {
      // Aceita JSON do QR (cliente Ligo) ou string crua "LIGO:xxxx".
      // Também aceita URL completa caso o QR tenha encodado um link.
      let qr_token = rawTrim;
      let extra = null;   // dados auxiliares para o backend (nome, CPF…)
      // PRIORIDADE: token criptografado V2 — opaco, só backend decifra
      if (rawTrim.startsWith("LIGO2:")) {
        qr_token = rawTrim;
      } else {
        try {
          const obj = JSON.parse(rawTrim);
          // ordem de preferência: token aleatório → subscriber_id → CPF
          if (obj.token) qr_token = obj.token;
          else if (obj.sid) qr_token = `LIGO:${obj.sid}`;
          else if (obj.id) qr_token = `LIGO:${obj.id}`;
          else if (obj.subscriber_id) qr_token = `LIGO:${obj.subscriber_id}`;
          else if (obj.cpf) qr_token = `LIGO:CPF:${String(obj.cpf).replace(/\D/g, "")}`;
          else if (obj.name) qr_token = `LIGO:NAME:${obj.name}`;
          // sempre envia o JSON original como contexto extra
          extra = obj;
        } catch { /* não é JSON */ }
      }
      // Se vier como URL, extrai o token preservando V1/V2 (iter215bm).
      //   /q/<token>   → token simples
      //   /q2/<token>  → LIGO2:<token> (Fernet, opaco)
      if (qr_token.startsWith("http")) {
        try {
          const u = new URL(qr_token);
          const path = u.pathname || "";
          if (path.startsWith("/q2/")) {
            qr_token = `LIGO2:${path.slice(4)}`;
          } else if (path.startsWith("/q/")) {
            qr_token = path.slice(3);
          } else {
            qr_token = u.searchParams.get("qr")
              || u.searchParams.get("token")
              || path.split("/").filter(Boolean).pop()
              || qr_token;
          }
        } catch { /* */ }
      }
      const r = await axios.post(`${API}/scan`,
        { qr_token, promotion_id: pickedPromo.id, qr_payload: extra },
        { headers: { Authorization: `Bearer ${token}` } });
      if (r.data.ok) {
        playSuccessFeedback();
        triggerFlash("ok");
        setResult(r.data);
        onSuccess && onSuccess();
        // Sucesso: mantém pausado, o ScanResultCard assume.
      } else {
        playErrorFeedback();
        triggerFlash("err");
        setErr("Cliente não elegível: " + (r.data.reason || ""));
        // Cliente não elegível: retoma leitura após 2.5s pra evitar
        // ficar com a tela congelada ("Scanner paused").
        scheduleResume();
      }
    } catch (e) {
      playErrorFeedback();
      triggerFlash("err");
      const detail = e?.response?.data?.detail || "QR inválido ou cliente não encontrado.";
      const preview = rawTrim.length > 40 ? rawTrim.slice(0, 40) + "…" : rawTrim;
      setErr(`${detail}\nLido: ${preview || "(vazio)"}`);
      scheduleResume();
    } finally { setScanning(false); }
  };

  // Retoma a câmera após 2.5s pra evitar "Scanner paused" travado.
  const scheduleResume = () => {
    setTimeout(() => {
      try {
        if (readerRef.current && !result) {
          readerRef.current.resume();
          setErr("");      // limpa erro pro próximo tentativa
        }
      } catch { /* */ }
    }, 2500);
  };

  const submitManual = (e) => {
    e.preventDefault();
    if (qrInput.trim()) handleQr(qrInput.trim());
  };

  return (
    <>
      <Header title="Ler QR do cliente" subtitle="Resgate de promoção"
        onBack={onBack} />
      <div style={{ padding: 18, display: "grid", gap: 14 }}>
        {!pickedPromo && (
          <>
            <p style={{ color: COLORS.muted, fontSize: 13, margin: 0 }}>
              Escolha qual promoção o cliente está resgatando:
            </p>
            {promos.length === 0 && (
              <div className="pp-card" style={{ padding: 16, textAlign: "center",
                                                    color: COLORS.muted }}>
                Cadastre uma promoção primeiro.
              </div>
            )}
            {promos.map((p) => (
              <button key={p.id} className="pp-card"
                data-testid={`scan-pick-promo-${p.id}`}
                onClick={() => setPickedPromo(p)}
                style={{ padding: 14, textAlign: "left", color: COLORS.text,
                           border: `1px solid ${COLORS.line}`, cursor: "pointer",
                           background: COLORS.surface, width: "100%" }}>
                <div style={{ fontWeight: 800, fontSize: 14 }}>{p.title}</div>
                <div style={{ fontSize: 12, color: COLORS.muted,
                                  marginTop: 4 }}>{p.offer_summary}</div>
              </button>
            ))}
          </>
        )}

        {pickedPromo && !result && (
          <>
            <div className="pp-card" style={{ padding: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 1.6,
                              textTransform: "uppercase", color: COLORS.brandSoft }}>
                Resgatando
              </div>
              <div style={{ fontSize: 14, fontWeight: 800, marginTop: 2 }}>
                {pickedPromo.title}
              </div>
              <button onClick={() => setPickedPromo(null)}
                data-testid="scan-change-promo"
                style={{ background: "transparent", border: "none",
                            color: COLORS.brandSoft, padding: 0, marginTop: 6,
                            fontSize: 11, fontWeight: 700, cursor: "pointer",
                            textDecoration: "underline" }}>
                trocar promoção
              </button>
            </div>

            <div style={{ position: "relative" }}>
              <div id="parceiro-scanner-box"
                  data-testid="parceiro-scanner-box" style={{
                width: "100%", aspectRatio: "1/1", borderRadius: 18,
                overflow: "hidden", background: "black",
                border: `1px solid ${COLORS.line}`,
              }} />
              <AnimatePresence>
                {flash && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: .18 }}
                    data-testid={`scan-flash-${flash}`}
                    style={{
                      position: "absolute", inset: 0, borderRadius: 18,
                      pointerEvents: "none",
                      background: flash === "ok"
                        ? "rgba(16,185,129,.55)"
                        : "rgba(239,68,68,.55)",
                      boxShadow: flash === "ok"
                        ? "inset 0 0 0 6px #10B981, 0 0 36px rgba(16,185,129,.5)"
                        : "inset 0 0 0 6px #EF4444, 0 0 36px rgba(239,68,68,.5)",
                      display: "grid", placeItems: "center",
                    }}>
                    {flash === "ok"
                      ? <Check size={96} color="white" strokeWidth={3} />
                      : <X size={96} color="white" strokeWidth={3} />}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            <form onSubmit={submitManual} style={{ display: "flex", gap: 8 }}>
              <input className="pp-input" placeholder="Ou cole o código aqui"
                value={qrInput} data-testid="scan-manual-input"
                onChange={(e) => setQrInput(e.target.value)} />
              <button type="submit" className="pp-cta"
                data-testid="scan-manual-submit"
                disabled={scanning}>OK</button>
            </form>
          </>
        )}

        {err && <div data-testid="scan-error" style={errBox()}>{err}</div>}

        {result && (
          <ScanResultCard result={result} promo={pickedPromo}
            onReset={() => { setPickedPromo(null); setResult(null); setErr(""); }} />
        )}
      </div>
    </>
  );
}

function ScanResultCard({ result, promo, onReset }) {
  return (
    <motion.div initial={{ opacity: 0, scale: .9 }}
      animate={{ opacity: 1, scale: 1 }}
      data-testid="scan-result"
      style={{
        padding: 20, borderRadius: 18,
        background: "linear-gradient(135deg, #064E3B, #0F766E)",
        color: "white", textAlign: "center",
      }}>
      <div style={{
        width: 64, height: 64, borderRadius: "50%",
        background: "rgba(255,255,255,.2)",
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        marginBottom: 12,
      }}><Check size={36} /></div>
      <h2 style={{ margin: 0, fontSize: 20, fontWeight: 900 }}>
        Resgate confirmado!
      </h2>
      <div style={{ fontSize: 13, opacity: .85, marginTop: 6 }}>
        Voucher: <b>{result.voucher_code}</b>
      </div>
      {result.client?.is_vip && (
        <div data-testid="vip-banner" style={{
          marginTop: 12, padding: "10px 14px", borderRadius: 14,
          background: "linear-gradient(135deg,#fbbf24,#f59e0b)",
          color: "#7c2d12", fontWeight: 900, fontSize: 13,
          boxShadow: "0 4px 16px rgba(251,191,36,0.6)",
          animation: "vipPulse 1.6s ease-in-out infinite",
        }}>
          Cliente VIP Ligo!
          <div style={{ fontSize: 11, fontWeight: 700, marginTop: 3,
                            opacity: 0.85 }}>
            Há {Math.floor(result.client.tenure_years)} {Math.floor(result.client.tenure_years) === 1 ? "ano" : "anos"} conosco
            — ofereça uma atenção especial 
          </div>
          <style>{`@keyframes vipPulse{0%,100%{transform:scale(1)}50%{transform:scale(1.04)}}`}</style>
        </div>
      )}
      <div style={{ marginTop: 16, padding: 14, borderRadius: 12,
                       background: "rgba(0,0,0,.25)", textAlign: "left" }}>
        <Row k="Cliente" v={result.client?.name} />
        <Row k="PPPoE" v={result.client?.pppoe} />
        <Row k="Cidade" v={result.client?.city || "—"} />
        <Row k="Promoção" v={promo?.title} />
      </div>
      <button onClick={onReset} className="pp-cta"
        data-testid="scan-reset-btn"
        style={{ marginTop: 16, background: "white" }}>
        Resgatar para próximo cliente
      </button>
    </motion.div>
  );
}
function Row({ k, v }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between",
                     padding: "5px 0", fontSize: 12, opacity: .9 }}>
      <span style={{ fontWeight: 700 }}>{k}</span>
      <span>{v || "—"}</span>
    </div>
  );
}

/* ════════════════════════ Redemptions ═════════════════════════ */
function RedemptionsScreen({ token, onBack }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    axios.get(`${API}/redemptions?limit=300`,
      { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => setItems(r.data || []))
      .finally(() => setLoading(false));
  }, [token]);
  return (
    <>
      <Header title="Resgates" subtitle="Clientes Ligo que usaram"
        onBack={onBack} />
      <div style={{ padding: 18, display: "grid", gap: 10 }}>
        {loading && <div style={{ color: COLORS.muted,
                                       textAlign: "center" }}>Carregando...</div>}
        {!loading && items.length === 0 && (
          <div className="pp-card" style={{ padding: 18,
                                                textAlign: "center",
                                                color: COLORS.muted }}>
            Nenhum cliente resgatou suas promoções ainda.
          </div>
        )}
        {items.map((r) => (
          <div key={r.id} className="pp-card"
            data-testid={`redemption-row-${r.id}`}
            style={{ padding: 14 }}>
            <div style={{ display: "flex", justifyContent: "space-between",
                             alignItems: "center", gap: 8 }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontWeight: 800, fontSize: 14,
                                  overflow: "hidden", textOverflow: "ellipsis",
                                  whiteSpace: "nowrap" }}>{r.client_name}</div>
                <div style={{ fontSize: 11, color: COLORS.muted,
                                  marginTop: 2 }}>{r.promotion_title}</div>
              </div>
              <span style={pill(r.paid ? COLORS.green : COLORS.orange)}>
                {r.paid ? "Pago" : "Pendente"}
              </span>
            </div>
            <div style={{ marginTop: 8, display: "flex",
                             justifyContent: "space-between", fontSize: 11,
                             color: COLORS.muted }}>
              <span>{new Date(r.redeemed_at).toLocaleString("pt-BR")}</span>
              <span>Voucher {r.voucher_code}</span>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

/* ════════════════════════ Helpers ═════════════════════════ */
function Field({ label, value, onChange, textarea, type = "text",
  placeholder = "", testid }) {
  const props = {
    className: "pp-input", value: value, type,
    placeholder, "data-testid": testid,
    onChange: (e) => onChange(e.target.value),
  };
  return (
    <div>
      <label style={fieldLabel()}>{label}</label>
      {textarea
        ? <textarea {...props} rows={3} style={{ resize: "vertical",
            ...textareaInline() }} />
        : <input {...props} />}
    </div>
  );
}
function fieldLabel() {
  return {
    display: "block", fontSize: 11, fontWeight: 800, letterSpacing: 1.4,
    textTransform: "uppercase", color: COLORS.muted, marginBottom: 6,
  };
}
function textareaInline() {
  return { width: "100%", padding: "12px 14px", borderRadius: 12,
    background: COLORS.surface2, color: COLORS.text,
    border: `1px solid ${COLORS.line}`, fontSize: 14,
    fontFamily: "inherit", outline: "none", boxSizing: "border-box" };
}
function buttonStylePrimary() {
  return {
    padding: "14px 18px", borderRadius: 14,
    background: COLORS.orange, color: "#1a0840",
    border: "none", fontWeight: 900, fontSize: 14, cursor: "pointer",
    width: "100%", display: "inline-flex", alignItems: "center",
    justifyContent: "center", gap: 8,
    boxShadow: "0 14px 30px rgba(255,106,26,.32)",
  };
}
function buttonStyleGhost() {
  return {
    padding: "12px 16px", borderRadius: 12,
    background: COLORS.surface, color: COLORS.text,
    border: `1.5px solid ${COLORS.line}`, fontWeight: 700, fontSize: 13,
    cursor: "pointer", width: "100%",
  };
}
function errBox() {
  return {
    padding: "10px 14px", borderRadius: 10,
    background: "#FEE2E2",
    border: "1px solid #FCA5A5",
    color: "#991B1B", fontSize: 13, fontWeight: 600,
  };
}

/* iter231 — Picker de categoria do produto/serviço */
const PRODUCT_CATEGORIES = [
  { label: "Alimentação", emoji: "️" },
  { label: "Bebidas", emoji: "" },
  { label: "Sobremesa", emoji: "" },
  { label: "Saúde", emoji: "" },
  { label: "Beleza", emoji: "" },
  { label: "Automotivo", emoji: "" },
  { label: "Mercado", emoji: "" },
  { label: "Pet", emoji: "" },
  { label: "Vestuário", emoji: "" },
  { label: "Lazer", emoji: "" },
  { label: "Serviço", emoji: "️" },
  { label: "Outros", emoji: "✨" },
];

function CategoryPicker({ value, onChange }) {
  const isCustom = value && !PRODUCT_CATEGORIES.find((c) => c.label === value);
  const [customMode, setCustomMode] = useState(isCustom);
  return (
    <div>
      <label style={fieldLabel()}>Categoria do produto/serviço</label>
      <div data-testid="promo-category-picker" style={{
        display: "flex", flexWrap: "wrap", gap: 6,
      }}>
        {PRODUCT_CATEGORIES.map((c) => {
          const active = value === c.label && !customMode;
          return (
            <button key={c.label} type="button"
              data-testid={`promo-cat-${c.label}`}
              onClick={() => { setCustomMode(false); onChange(c.label); }}
              style={{
                padding: "8px 12px", borderRadius: 999,
                border: active ? `1.5px solid ${COLORS.orange}`
                  : `1px solid ${COLORS.line}`,
                background: active ? `${COLORS.orange}28` : COLORS.surface2,
                color: active ? COLORS.orange : COLORS.text,
                fontSize: 12.5, fontWeight: 700, letterSpacing: .2,
                cursor: "pointer", display: "inline-flex",
                alignItems: "center", gap: 6,
              }}>
              <span>{c.emoji}</span>{c.label}
            </button>
          );
        })}
        <button type="button" data-testid="promo-cat-custom-toggle"
          onClick={() => {
            setCustomMode(true);
            if (PRODUCT_CATEGORIES.find((c) => c.label === value)) onChange("");
          }}
          style={{
            padding: "8px 12px", borderRadius: 999,
            border: customMode ? `1.5px solid ${COLORS.brandSoft}`
              : `1px dashed ${COLORS.line}`,
            background: customMode ? `${COLORS.brand}33` : "transparent",
            color: customMode ? COLORS.brandSoft : COLORS.muted,
            fontSize: 12.5, fontWeight: 700, cursor: "pointer",
          }}>+ Outra</button>
      </div>
      {customMode && (
        <input data-testid="promo-cat-custom-input"
          className="pp-input"
          placeholder="Digite a categoria (ex: Tatuagem, Eletrônicos)"
          value={value || ""} maxLength={40}
          onChange={(e) => onChange(e.target.value)}
          style={{ marginTop: 8 }} />
      )}
    </div>
  );
}
