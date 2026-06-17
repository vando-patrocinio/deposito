/* LigoTV — Hub público de canais grátis (Pluto TV) pro assinante Ligo.
 *
 * Auth: CPF + senha (= CPF) — token salvo em localStorage como `ligotv_token`.
 * Routing: `/ligo-tv` (login + grid + player num único componente, gerido
 * por estado interno; sem react-router pra evitar conflito com o App.js).
 *
 * Visual: dark + accent vermelho (estética SKY+/IPTV), sem AI slop.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Hls from "hls.js";
import { Search, LogOut, Play, Tv, Radio, Loader2, AlertCircle, X } from "lucide-react";

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";
const TOKEN_KEY = "ligotv_token";
const ME_KEY = "ligotv_me";

const ACCENT = "#ef4444";
const BG = "#0a0a0a";
const BG_CARD = "#141414";
const BG_HOVER = "#1f1f1f";
const TEXT = "#f5f5f5";
const TEXT_DIM = "#a3a3a3";

const fmtCPF = (s) => {
  const d = (s || "").replace(/\D+/g, "").slice(0, 11);
  if (d.length <= 3) return d;
  if (d.length <= 6) return `${d.slice(0,3)}.${d.slice(3)}`;
  if (d.length <= 9) return `${d.slice(0,3)}.${d.slice(3,6)}.${d.slice(6)}`;
  return `${d.slice(0,3)}.${d.slice(3,6)}.${d.slice(6,9)}-${d.slice(9)}`;
};

async function api(path, opts = {}) {
  const token = localStorage.getItem(TOKEN_KEY) || "";
  const r = await fetch(`${BACKEND}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts.headers || {}),
    },
  });
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try { const j = await r.json(); detail = j?.detail || detail; } catch (_) { }
    throw new Error(detail);
  }
  return r.json();
}

// ─────────────────────────── Login ───────────────────────────
function LoginScreen({ onLogin }) {
  const [cpf, setCpf] = useState("");
  const [pass, setPass] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e?.preventDefault?.();
    setErr("");
    setBusy(true);
    try {
      const cpfClean = cpf.replace(/\D+/g, "");
      const data = await api("/api/ligo-tv/auth/login", {
        method: "POST",
        body: JSON.stringify({ cpf: cpfClean, password: pass.replace(/\D+/g, "") }),
      });
      localStorage.setItem(TOKEN_KEY, data.token);
      localStorage.setItem(ME_KEY, JSON.stringify(data.subscriber));
      onLogin(data.subscriber);
    } catch (e) {
      setErr(e.message || "Falha no login");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div data-testid="ligotv-login" style={{
      minHeight: "100vh", background: BG,
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: 24, color: TEXT,
      backgroundImage:
        "radial-gradient(ellipse at top left, rgba(239,68,68,0.15), transparent 60%), radial-gradient(ellipse at bottom right, rgba(239,68,68,0.1), transparent 50%)",
    }}>
      <div style={{
        width: "100%", maxWidth: 420,
        background: BG_CARD, border: "1px solid #262626",
        borderRadius: 16, padding: 32, boxShadow: "0 20px 60px rgba(0,0,0,0.5)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <Tv color={ACCENT} size={28}/>
          <h1 style={{ margin: 0, fontSize: 22, letterSpacing: 1, fontWeight: 800 }}>
            LIGO <span style={{ color: ACCENT }}>TV</span>
          </h1>
        </div>
        <p style={{ color: TEXT_DIM, marginTop: 0, marginBottom: 28, fontSize: 13, lineHeight: 1.5 }}>
          Mais de 400 canais ao vivo grátis pra você assinante Ligo. Entre com seu CPF.
        </p>
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <label style={{ fontSize: 12, color: TEXT_DIM, fontWeight: 700 }}>
            CPF
            <input
              data-testid="ligotv-login-cpf"
              value={fmtCPF(cpf)}
              onChange={(e) => setCpf(e.target.value)}
              placeholder="000.000.000-00"
              inputMode="numeric"
              autoFocus
              style={inputStyle}
            />
          </label>
          <label style={{ fontSize: 12, color: TEXT_DIM, fontWeight: 700 }}>
            Senha (seu CPF)
            <input
              data-testid="ligotv-login-password"
              value={fmtCPF(pass)}
              onChange={(e) => setPass(e.target.value)}
              type="password"
              placeholder="000.000.000-00"
              style={inputStyle}
            />
          </label>
          {err && (
            <div style={{
              padding: 10, background: "#2a0f0f", border: "1px solid #5b1d1d",
              borderRadius: 8, fontSize: 12, color: "#fda4af",
              display: "flex", alignItems: "center", gap: 8,
            }}>
              <AlertCircle size={14}/> {err}
            </div>
          )}
          <button
            data-testid="ligotv-login-submit"
            type="submit"
            disabled={busy || !cpf || !pass}
            style={{
              marginTop: 6, padding: "12px 16px",
              background: ACCENT, color: "white", border: "none",
              borderRadius: 10, fontWeight: 700, fontSize: 14,
              cursor: busy ? "wait" : "pointer",
              opacity: (!cpf || !pass) ? 0.55 : 1,
              transition: "transform .15s ease",
            }}
            onMouseDown={(e) => e.currentTarget.style.transform = "scale(0.98)"}
            onMouseUp={(e) => e.currentTarget.style.transform = "scale(1)"}
          >
            {busy ? "Entrando…" : "Entrar"}
          </button>
        </form>
        <p style={{ marginTop: 18, fontSize: 11, color: "#6b7280", lineHeight: 1.5 }}>
          A senha inicial é o próprio CPF (apenas dígitos).
          Não tem cadastro? <a href="https://universoligo.com" style={{ color: ACCENT }}>Assine um plano</a>.
        </p>
      </div>
    </div>
  );
}

const inputStyle = {
  display: "block", width: "100%", marginTop: 6,
  padding: "11px 12px", borderRadius: 8,
  background: "#1a1a1a", border: "1px solid #2a2a2a",
  color: TEXT, fontSize: 14, outline: "none",
  letterSpacing: 1.5,
};

// ─────────────────────────── Player ───────────────────────────
function HlsPlayer({ src }) {
  const videoRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setError(null);
    setLoading(true);
    if (!src || !videoRef.current) return;
    const video = videoRef.current;
    let hls;
    if (Hls.isSupported()) {
      hls = new Hls({ enableWorker: true, lowLatencyMode: false });
      hls.loadSource(src);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        setLoading(false);
        video.play().catch(() => { });
      });
      hls.on(Hls.Events.ERROR, (_e, data) => {
        if (data.fatal) {
          setError(`Falha ao tocar canal (${data.type}). Tente outro.`);
          setLoading(false);
        }
      });
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = src;
      video.addEventListener("loadedmetadata", () => {
        setLoading(false);
        video.play().catch(() => { });
      });
      video.addEventListener("error", () => {
        setError("Falha ao tocar canal.");
        setLoading(false);
      });
    } else {
      setError("Navegador sem suporte a HLS.");
      setLoading(false);
    }
    return () => { try { hls?.destroy(); } catch (_) { } };
  }, [src]);

  return (
    <div style={{ position: "relative", width: "100%", paddingTop: "56.25%", background: "#000", borderRadius: 12, overflow: "hidden" }}>
      <video
        ref={videoRef}
        data-testid="ligotv-player-video"
        controls
        playsInline
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%", background: "#000" }}
      />
      {loading && !error && (
        <div style={overlayStyle}><Loader2 className="animate-spin" size={36} color={ACCENT}/></div>
      )}
      {error && (
        <div style={{ ...overlayStyle, color: "#fda4af", fontSize: 13, padding: 16, textAlign: "center" }}>
          <AlertCircle size={28} style={{ marginBottom: 8 }}/>{error}
        </div>
      )}
    </div>
  );
}

const overlayStyle = {
  position: "absolute", inset: 0,
  display: "flex", alignItems: "center", justifyContent: "center",
  flexDirection: "column", background: "rgba(0,0,0,0.7)",
};

// ─────────────────────────── Hub ───────────────────────────
function Hub({ me, onLogout }) {
  const [channels, setChannels] = useState([]);
  const [categories, setCategories] = useState([]);
  const [activeCat, setActiveCat] = useState("Todos");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [playing, setPlaying] = useState(null); // {name, hls_url, ...}

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const [chR, catR] = await Promise.all([
        api("/api/ligo-tv/channels"),
        api("/api/ligo-tv/categories"),
      ]);
      setChannels(chR.channels || []);
      setCategories(catR.categories || []);
    } catch (e) {
      if (String(e.message).toLowerCase().includes("expir") || String(e.message).toLowerCase().includes("inválid")) {
        onLogout();
      } else {
        setErr(e.message);
      }
    } finally {
      setLoading(false);
    }
  }, [onLogout]);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return channels.filter((c) => {
      if (activeCat !== "Todos" && c.category !== activeCat) return false;
      if (!q) return true;
      return (c.name || "").toLowerCase().includes(q)
        || (c.summary || "").toLowerCase().includes(q);
    });
  }, [channels, activeCat, search]);

  const openChannel = async (ch) => {
    try {
      const r = await api(`/api/ligo-tv/channels/${ch.slug}`);
      setPlaying(r.channel);
    } catch (e) {
      setErr(e.message);
    }
  };

  return (
    <div style={{ minHeight: "100vh", background: BG, color: TEXT }}>
      {/* Header */}
      <header style={{
        position: "sticky", top: 0, zIndex: 10,
        background: "rgba(10,10,10,0.92)", backdropFilter: "blur(10px)",
        borderBottom: "1px solid #1f1f1f",
        padding: "12px 20px",
        display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Tv color={ACCENT} size={22}/>
          <span style={{ fontWeight: 800, letterSpacing: 1.5, fontSize: 16 }}>
            LIGO <span style={{ color: ACCENT }}>TV</span>
          </span>
        </div>
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          background: "#1a1a1a", border: "1px solid #2a2a2a",
          borderRadius: 10, padding: "6px 12px", flex: 1, maxWidth: 460,
          minWidth: 200,
        }}>
          <Search size={14} color={TEXT_DIM}/>
          <input
            data-testid="ligotv-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar canal…"
            style={{
              border: "none", background: "transparent", color: TEXT,
              outline: "none", flex: 1, fontSize: 13,
            }}
          />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginLeft: "auto" }}>
          <span style={{ fontSize: 12, color: TEXT_DIM }} data-testid="ligotv-me-name">
            {me?.name?.split(" ")[0] || "Cliente"}
          </span>
          <button
            data-testid="ligotv-logout"
            onClick={onLogout}
            title="Sair"
            style={{
              background: "transparent", color: TEXT_DIM,
              border: "1px solid #262626", borderRadius: 8,
              padding: "6px 10px", cursor: "pointer", fontSize: 12,
              display: "inline-flex", alignItems: "center", gap: 4,
            }}
          ><LogOut size={12}/> Sair</button>
        </div>
      </header>

      {/* Categorias */}
      <nav style={{
        display: "flex", gap: 8, padding: "12px 20px",
        overflowX: "auto", whiteSpace: "nowrap", borderBottom: "1px solid #1a1a1a",
        scrollbarWidth: "none",
      }}>
        {[{ name: "Todos", count: channels.length }, ...categories].map((c) => (
          <button
            key={c.name}
            data-testid={`ligotv-cat-${c.name.replace(/\s+/g, "-").toLowerCase()}`}
            onClick={() => setActiveCat(c.name)}
            style={{
              padding: "6px 14px", borderRadius: 999, cursor: "pointer",
              fontSize: 12, fontWeight: 600, whiteSpace: "nowrap",
              border: `1px solid ${activeCat === c.name ? ACCENT : "#262626"}`,
              background: activeCat === c.name ? ACCENT : "transparent",
              color: activeCat === c.name ? "white" : TEXT_DIM,
              transition: "all .15s",
            }}
          >
            {c.name} <span style={{ opacity: 0.6 }}>· {c.count}</span>
          </button>
        ))}
      </nav>

      {/* Grid */}
      <main style={{ padding: 20 }}>
        {loading && (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 80, gap: 10, color: TEXT_DIM }}>
            <Loader2 className="animate-spin" size={20} color={ACCENT}/> Carregando canais…
          </div>
        )}
        {err && (
          <div style={{
            padding: 12, background: "#2a0f0f", border: "1px solid #5b1d1d",
            borderRadius: 8, color: "#fda4af", fontSize: 13,
          }}>{err}</div>
        )}
        {!loading && !err && (
          <>
            <div style={{ marginBottom: 12, fontSize: 12, color: TEXT_DIM }} data-testid="ligotv-channel-count">
              {filtered.length} canal{filtered.length !== 1 ? "is" : ""}
            </div>
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
              gap: 14,
            }}>
              {filtered.map((c) => (
                <button
                  key={c.id}
                  data-testid={`ligotv-channel-${c.slug}`}
                  onClick={() => openChannel(c)}
                  style={{
                    textAlign: "left", border: "1px solid #1f1f1f",
                    background: BG_CARD, borderRadius: 12, padding: 0,
                    cursor: "pointer", color: TEXT, overflow: "hidden",
                    transition: "transform .15s, border-color .15s",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.transform = "translateY(-2px)";
                    e.currentTarget.style.borderColor = ACCENT;
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = "translateY(0)";
                    e.currentTarget.style.borderColor = "#1f1f1f";
                  }}
                >
                  <div style={{
                    paddingTop: "56.25%", position: "relative",
                    background: c.tile ? "#000" : "#1a1a1a",
                    backgroundImage: c.tile ? `url(${c.tile})` : undefined,
                    backgroundSize: "cover", backgroundPosition: "center",
                  }}>
                    {c.logo && (
                      <img
                        src={c.logo}
                        alt=""
                        style={{
                          position: "absolute", top: 8, left: 8,
                          maxWidth: 60, maxHeight: 28, objectFit: "contain",
                          background: "rgba(0,0,0,0.55)", borderRadius: 6,
                          padding: 4,
                        }}
                      />
                    )}
                    <div style={{
                      position: "absolute", bottom: 0, left: 0, right: 0,
                      background: "linear-gradient(transparent, rgba(0,0,0,0.85))",
                      padding: "20px 10px 8px",
                      display: "flex", alignItems: "flex-end", justifyContent: "space-between",
                      gap: 8,
                    }}>
                      <span style={{ fontWeight: 700, fontSize: 12, color: "white", lineHeight: 1.2 }}>
                        {c.name}
                      </span>
                      <span style={{
                        display: "inline-flex", alignItems: "center", gap: 3,
                        background: ACCENT, padding: "2px 6px", borderRadius: 4,
                        fontSize: 9, fontWeight: 800, color: "white",
                      }}>
                        <Radio size={8}/> AO VIVO
                      </span>
                    </div>
                  </div>
                  <div style={{ padding: "8px 12px 12px" }}>
                    <div style={{ fontSize: 10, color: TEXT_DIM, marginBottom: 2 }}>
                      Canal {c.number || "—"} · {c.category}
                    </div>
                    {c.summary && (
                      <div style={{
                        fontSize: 11, color: "#737373", lineHeight: 1.3,
                        display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
                        overflow: "hidden",
                      }}>{c.summary}</div>
                    )}
                  </div>
                </button>
              ))}
            </div>
            {filtered.length === 0 && (
              <div style={{ padding: 60, textAlign: "center", color: TEXT_DIM, fontSize: 13 }}>
                Nenhum canal encontrado pra esse filtro.
              </div>
            )}
          </>
        )}
      </main>

      {/* Player modal */}
      {playing && (
        <div
          data-testid="ligotv-player-modal"
          onClick={(e) => { if (e.target === e.currentTarget) setPlaying(null); }}
          style={{
            position: "fixed", inset: 0, zIndex: 50,
            background: "rgba(0,0,0,0.85)",
            display: "flex", alignItems: "center", justifyContent: "center",
            padding: 20,
          }}
        >
          <div style={{
            width: "100%", maxWidth: 1100,
            background: BG_CARD, borderRadius: 14, overflow: "hidden",
            border: "1px solid #262626",
          }}>
            <div style={{
              padding: "14px 18px", display: "flex", alignItems: "center", gap: 12,
              borderBottom: "1px solid #1f1f1f",
            }}>
              {playing.logo && <img src={playing.logo} alt="" style={{ maxHeight: 28, maxWidth: 70, objectFit: "contain" }}/>}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: 15 }}>{playing.name}</div>
                <div style={{ fontSize: 11, color: TEXT_DIM }}>
                  Canal {playing.number || "—"} · {playing.category}
                </div>
              </div>
              <button
                data-testid="ligotv-player-close"
                onClick={() => setPlaying(null)}
                style={{
                  background: "transparent", color: TEXT_DIM, border: "none",
                  cursor: "pointer", padding: 6,
                }}
              ><X size={20}/></button>
            </div>
            <div style={{ padding: 16 }}>
              <HlsPlayer src={playing.hls_url}/>
              {playing.summary && (
                <p style={{ color: TEXT_DIM, fontSize: 13, marginTop: 12, lineHeight: 1.5 }}>
                  {playing.summary}
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────── Root ───────────────────────────
export default function LigoTV() {
  const [me, setMe] = useState(() => {
    try {
      const raw = localStorage.getItem(ME_KEY);
      return raw && localStorage.getItem(TOKEN_KEY) ? JSON.parse(raw) : null;
    } catch (_) { return null; }
  });

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(ME_KEY);
    setMe(null);
  }, []);

  if (!me) return <LoginScreen onLogin={setMe}/>;
  return <Hub me={me} onLogout={logout}/>;
}
