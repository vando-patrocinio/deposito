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
import { Search, LogOut, Play, Tv, Radio, Loader2, AlertCircle, X, Video, MapPin, Plus, CheckCircle2 } from "lucide-react";

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
    let destroyed = false;
    if (Hls.isSupported()) {
      hls = new Hls({
        enableWorker: true,
        lowLatencyMode: false,
        // Estes 4 manifestLoadingMaxRetry + fragLoadingMaxRetry tornam o
        // player tolerante a falhas transitórias (ERR_ABORTED do dev
        // StrictMode, blips de rede). Sem isso, qualquer fetch cancelado
        // virava fatal e o usuário via "Falha ao tocar canal".
        manifestLoadingMaxRetry: 4,
        manifestLoadingRetryDelay: 800,
        fragLoadingMaxRetry: 6,
        fragLoadingRetryDelay: 800,
      });
      hls.loadSource(src);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        if (destroyed) return;
        setLoading(false);
        video.play().catch(() => { });
      });
      hls.on(Hls.Events.ERROR, (_e, data) => {
        if (!data?.fatal || destroyed) return;
        // Tenta recuperar antes de marcar como morto. networkError →
        // startLoad(); mediaError → recoverMediaError(); resto = fatal.
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
          try { hls.startLoad(); return; } catch (_) { }
        }
        if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
          try { hls.recoverMediaError(); return; } catch (_) { }
        }
        setError(`Falha ao tocar (${data.details || data.type}). Tente outro canal.`);
        setLoading(false);
      });
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = src;
      video.addEventListener("loadedmetadata", () => {
        if (destroyed) return;
        setLoading(false);
        video.play().catch(() => { });
      });
      video.addEventListener("error", () => {
        if (destroyed) return;
        setError("Falha ao tocar canal.");
        setLoading(false);
      });
    } else {
      setError("Navegador sem suporte a HLS.");
      setLoading(false);
    }
    return () => {
      destroyed = true;
      try { hls?.destroy(); } catch (_) { }
    };
  }, [src]);

  return (
    <div style={{ position: "relative", width: "100%", paddingTop: "56.25%", background: "#000", borderRadius: 12, overflow: "hidden" }}>
      <video
        ref={videoRef}
        data-testid="ligotv-player-video"
        controls
        playsInline
        muted
        autoPlay
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

// ─────────────────────── YouTube Embed ───────────────────────
function YouTubeEmbed({ channelId, videoId }) {
  // Prefere video_id (estável p/ 24/7 fixos) — channel_id só funciona se
  // o canal tem uma live ativa AGORA (instável).
  const src = videoId
    ? `https://www.youtube.com/embed/${videoId}?autoplay=1&rel=0`
    : `https://www.youtube.com/embed/live_stream?channel=${channelId}&autoplay=1&rel=0`;
  return (
    <div style={{ position: "relative", width: "100%", paddingTop: "56.25%", background: "#000", borderRadius: 12, overflow: "hidden" }}>
      <iframe
        data-testid="ligotv-youtube-iframe"
        src={src}
        title="Live Stream"
        allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture"
        allowFullScreen
        frameBorder="0"
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
      />
    </div>
  );
}

// ─────────────────────────── Hub ───────────────────────────
function Hub({ me, onLogout }) {
  const [section, setSection] = useState("tv"); // 'tv' | 'cameras'
  const [channels, setChannels] = useState([]);
  const [cameras, setCameras] = useState([]);
  const [matchedCep, setMatchedCep] = useState("");
  const [categories, setCategories] = useState([]);
  const [activeCat, setActiveCat] = useState("Todos");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [playing, setPlaying] = useState(null);
  const [requestOpen, setRequestOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const [chR, catR, camR] = await Promise.all([
        api("/api/ligo-tv/channels"),
        api("/api/ligo-tv/categories"),
        api("/api/ligo-tv/cameras"),
      ]);
      setChannels(chR.channels || []);
      setCategories(catR.categories || []);
      setCameras(camR.cameras || []);
      setMatchedCep(camR.matched_cep_prefix || "");
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

  const filteredCams = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return cameras;
    return cameras.filter((c) =>
      (c.name || "").toLowerCase().includes(q)
      || (c.neighborhood || "").toLowerCase().includes(q)
      || (c.city || "").toLowerCase().includes(q)
    );
  }, [cameras, search]);

  const openChannel = async (ch) => {
    try {
      const r = await api(`/api/ligo-tv/channels/${ch.slug}`);
      setPlaying({ kind: "channel", data: r.channel });
    } catch (e) { setErr(e.message); }
  };

  const openCamera = (cam) => {
    setPlaying({ kind: "camera", data: cam });
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
        {/* Tabs TV / Câmeras */}
        <div style={{ display: "flex", gap: 4, background: "#181818", padding: 3, borderRadius: 999 }}>
          {[
            { id: "tv", label: "TV", icon: Tv },
            { id: "cameras", label: "Câmeras", icon: Video },
          ].map((t) => {
            const Icon = t.icon;
            const active = section === t.id;
            return (
              <button
                key={t.id}
                data-testid={`ligotv-section-${t.id}`}
                onClick={() => { setSection(t.id); setActiveCat("Todos"); setSearch(""); }}
                style={{
                  padding: "6px 14px", borderRadius: 999,
                  background: active ? ACCENT : "transparent",
                  color: active ? "white" : TEXT_DIM,
                  border: "none", cursor: "pointer", fontSize: 12, fontWeight: 700,
                  display: "inline-flex", alignItems: "center", gap: 5,
                }}
              ><Icon size={13}/> {t.label}</button>
            );
          })}
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
            placeholder={section === "tv" ? "Buscar canal…" : "Buscar bairro ou câmera…"}
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

      {section === "tv" && (
        <>
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

          {/* Grid de canais */}
          <main style={{ padding: 20 }}>
            {loading && (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 80, gap: 10, color: TEXT_DIM }}>
                <Loader2 className="animate-spin" size={20} color={ACCENT}/> Carregando…
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
                <div style={gridStyle}>
                  {filtered.map((c) => (
                    <ChannelCard key={c.id} c={c} onClick={() => openChannel(c)}/>
                  ))}
                </div>
                {filtered.length === 0 && (
                  <div style={emptyStyle}>Nenhum canal encontrado.</div>
                )}
              </>
            )}
          </main>
        </>
      )}

      {section === "cameras" && (
        <main style={{ padding: 20 }}>
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            marginBottom: 16, gap: 12, flexWrap: "wrap",
          }}>
            {matchedCep ? (
              <div style={{
                padding: 10,
                background: "#0d2c1e", border: "1px solid #166534",
                borderRadius: 8, fontSize: 12, color: "#86efac",
                display: "inline-flex", alignItems: "center", gap: 8,
              }} data-testid="ligotv-cep-badge">
                <MapPin size={12}/> Câmeras da sua região (CEP {matchedCep}…)
              </div>
            ) : <span />}
            <button
              data-testid="ligotv-request-camera-btn"
              onClick={() => setRequestOpen(true)}
              style={{
                padding: "8px 14px", background: ACCENT, color: "white",
                border: "none", borderRadius: 8, cursor: "pointer",
                fontSize: 12, fontWeight: 700,
                display: "inline-flex", alignItems: "center", gap: 6,
              }}
            ><Plus size={13}/> Pedir câmera no meu bairro</button>
          </div>
          {loading ? (
            <div style={{ padding: 80, textAlign: "center", color: TEXT_DIM }}>
              <Loader2 className="animate-spin" size={20} color={ACCENT}/>
            </div>
          ) : (
            <>
              <div style={{ marginBottom: 12, fontSize: 12, color: TEXT_DIM }} data-testid="ligotv-camera-count">
                {filteredCams.length} câmera{filteredCams.length !== 1 ? "s" : ""} disponíveis
              </div>
              <div style={gridStyle}>
                {filteredCams.map((cam) => (
                  <CameraCard key={cam.id} c={cam} onClick={() => openCamera(cam)}/>
                ))}
              </div>
              {filteredCams.length === 0 && (
                <div style={emptyStyle}>Sem câmeras na sua região agora.</div>
              )}
            </>
          )}
        </main>
      )}

      {/* Player modal */}
      {playing && (
        <PlayerModal
          playing={playing}
          onClose={() => setPlaying(null)}
        />
      )}

      {/* Modal pedido de câmera */}
      {requestOpen && (
        <CameraRequestModal onClose={() => setRequestOpen(false)}/>
      )}
    </div>
  );
}

const gridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
  gap: 14,
};

const emptyStyle = {
  padding: 60, textAlign: "center", color: TEXT_DIM, fontSize: 13,
};

function ChannelCard({ c, onClick }) {
  const isYouTube = c.kind === "youtube_live";
  return (
    <button
      data-testid={`ligotv-channel-${c.slug}`}
      onClick={onClick}
      style={cardStyle}
      onMouseEnter={(e) => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.borderColor = ACCENT; }}
      onMouseLeave={(e) => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.borderColor = "#1f1f1f"; }}
    >
      <div style={{
        paddingTop: "56.25%", position: "relative",
        background: c.tile || c.logo ? "#000" : "#1a1a1a",
        backgroundImage: c.tile ? `url(${c.tile})` : (c.logo ? `url(${c.logo})` : undefined),
        backgroundSize: c.tile ? "cover" : "contain",
        backgroundPosition: "center",
        backgroundRepeat: "no-repeat",
      }}>
        {isYouTube && (
          <span style={{
            position: "absolute", top: 6, left: 6,
            background: "rgba(220,38,38,0.9)", color: "white",
            padding: "2px 6px", borderRadius: 4, fontSize: 9, fontWeight: 800,
          }}>YOUTUBE LIVE</span>
        )}
        <div style={cardOverlayStyle}>
          <span style={{ fontWeight: 700, fontSize: 12, color: "white", lineHeight: 1.2 }}>{c.name}</span>
          <span style={liveBadgeStyle}><Radio size={8}/> AO VIVO</span>
        </div>
      </div>
      <div style={{ padding: "8px 12px 12px" }}>
        <div style={{ fontSize: 10, color: TEXT_DIM, marginBottom: 2 }}>
          Canal {c.number || "—"} · {c.category}
        </div>
        {c.summary && <div style={summaryStyle}>{c.summary}</div>}
      </div>
    </button>
  );
}

function CameraCard({ c, onClick }) {
  return (
    <button
      data-testid={`ligotv-camera-${c.id}`}
      onClick={onClick}
      style={cardStyle}
      onMouseEnter={(e) => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.borderColor = ACCENT; }}
      onMouseLeave={(e) => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.borderColor = "#1f1f1f"; }}
    >
      <div style={{
        paddingTop: "56.25%", position: "relative",
        background: "#000",
        backgroundImage: c.thumbnail ? `url(${c.thumbnail})` : undefined,
        backgroundSize: "cover", backgroundPosition: "center",
      }}>
        <span style={{
          position: "absolute", top: 6, left: 6,
          background: "rgba(0,0,0,0.6)", color: "white",
          padding: "2px 6px", borderRadius: 4, fontSize: 9, fontWeight: 800,
          display: "inline-flex", alignItems: "center", gap: 3,
        }}><Video size={8}/> CÂMERA</span>
        <div style={cardOverlayStyle}>
          <span style={{ fontWeight: 700, fontSize: 12, color: "white" }}>{c.name}</span>
          <span style={{ ...liveBadgeStyle, background: "#16a34a" }}>● LIVE</span>
        </div>
      </div>
      <div style={{ padding: "8px 12px 12px" }}>
        <div style={{ fontSize: 10, color: TEXT_DIM, display: "flex", alignItems: "center", gap: 4 }}>
          <MapPin size={9}/> {c.neighborhood} · {c.city}/{c.uf}
        </div>
      </div>
    </button>
  );
}

const cardStyle = {
  textAlign: "left", border: "1px solid #1f1f1f",
  background: BG_CARD, borderRadius: 12, padding: 0,
  cursor: "pointer", color: TEXT, overflow: "hidden",
  transition: "transform .15s, border-color .15s",
};

const cardOverlayStyle = {
  position: "absolute", bottom: 0, left: 0, right: 0,
  background: "linear-gradient(transparent, rgba(0,0,0,0.85))",
  padding: "20px 10px 8px",
  display: "flex", alignItems: "flex-end", justifyContent: "space-between",
  gap: 8,
};

const liveBadgeStyle = {
  display: "inline-flex", alignItems: "center", gap: 3,
  background: ACCENT, padding: "2px 6px", borderRadius: 4,
  fontSize: 9, fontWeight: 800, color: "white",
};

const summaryStyle = {
  fontSize: 11, color: "#737373", lineHeight: 1.3,
  display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
  overflow: "hidden",
};

// ─────────────────────── Camera Request Modal ───────────────────────
const fmtCEP = (s) => {
  const d = (s || "").replace(/\D+/g, "").slice(0, 8);
  if (d.length <= 5) return d;
  return `${d.slice(0,5)}-${d.slice(5)}`;
};

function CameraRequestModal({ onClose }) {
  const [cep, setCep] = useState("");
  const [address, setAddress] = useState("");
  const [reference, setReference] = useState("");
  const [reason, setReason] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState(false);

  const submit = async (e) => {
    e?.preventDefault?.();
    setErr("");
    if (!consent) {
      setErr("Você precisa concordar com o consentimento LGPD pra prosseguir.");
      return;
    }
    setBusy(true);
    try {
      await api("/api/ligo-tv/camera-requests", {
        method: "POST",
        body: JSON.stringify({
          cep: cep.replace(/\D+/g, ""),
          address: address.trim(),
          reference: reference.trim(),
          reason: reason.trim(),
          lgpd_consent: true,
        }),
      });
      setDone(true);
    } catch (e) {
      setErr(e.message || "Falha ao enviar.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      data-testid="ligotv-request-modal"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{
        position: "fixed", inset: 0, zIndex: 60,
        background: "rgba(0,0,0,0.85)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 20, overflowY: "auto",
      }}
    >
      <div style={{
        width: "100%", maxWidth: 540, maxHeight: "90vh",
        background: BG_CARD, borderRadius: 14, border: "1px solid #262626",
        overflowY: "auto",
      }}>
        <div style={{
          padding: "14px 18px", borderBottom: "1px solid #1f1f1f",
          display: "flex", alignItems: "center", gap: 10,
        }}>
          <Plus color={ACCENT} size={18}/>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, fontSize: 15 }}>Pedir câmera no meu bairro</div>
            <div style={{ fontSize: 11, color: TEXT_DIM }}>Equipe Ligo analisa a viabilidade no quarteirão.</div>
          </div>
          <button onClick={onClose} data-testid="ligotv-request-close"
            style={{ background: "transparent", color: TEXT_DIM, border: "none", cursor: "pointer", padding: 6 }}>
            <X size={20}/>
          </button>
        </div>

        {done ? (
          <div style={{ padding: 40, textAlign: "center" }}>
            <CheckCircle2 size={48} color="#22c55e" style={{ marginBottom: 12 }}/>
            <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 6 }}>
              Pedido recebido!
            </div>
            <p style={{ color: TEXT_DIM, fontSize: 13, lineHeight: 1.5 }}>
              Nossa equipe vai avaliar a viabilidade no seu quarteirão e te
              avisar pelo WhatsApp em até 5 dias úteis. Obrigado por contribuir
              com a segurança da sua região!
            </p>
            <button
              data-testid="ligotv-request-done"
              onClick={onClose}
              style={{
                marginTop: 18, padding: "10px 18px", background: ACCENT,
                color: "white", border: "none", borderRadius: 8,
                cursor: "pointer", fontSize: 13, fontWeight: 700,
              }}
            >Fechar</button>
          </div>
        ) : (
          <form onSubmit={submit} style={{ padding: 18, display: "flex", flexDirection: "column", gap: 12 }}>
            <label style={labelStyle}>
              CEP
              <input
                data-testid="ligotv-request-cep"
                value={fmtCEP(cep)} onChange={(e) => setCep(e.target.value)}
                placeholder="27240-000" inputMode="numeric"
                style={modalInputStyle} required autoFocus
              />
            </label>
            <label style={labelStyle}>
              Endereço (rua, número)
              <input
                data-testid="ligotv-request-address"
                value={address} onChange={(e) => setAddress(e.target.value)}
                placeholder="Rua das Flores, 123"
                style={modalInputStyle} required
              />
            </label>
            <label style={labelStyle}>
              Ponto de referência <span style={{ color: "#6b7280", fontWeight: 400 }}>(opcional)</span>
              <input
                data-testid="ligotv-request-reference"
                value={reference} onChange={(e) => setReference(e.target.value)}
                placeholder="Em frente à padaria do João"
                style={modalInputStyle}
              />
            </label>
            <label style={labelStyle}>
              Motivo do pedido <span style={{ color: "#6b7280", fontWeight: 400 }}>(opcional)</span>
              <textarea
                data-testid="ligotv-request-reason"
                value={reason} onChange={(e) => setReason(e.target.value)}
                placeholder="Aumentou roubo nesse trecho, etc."
                rows={3}
                style={{ ...modalInputStyle, resize: "vertical", minHeight: 60, letterSpacing: 0 }}
              />
            </label>
            <label style={{
              display: "flex", gap: 10, alignItems: "flex-start",
              padding: 10, background: "#1a1a1a",
              border: `1px solid ${consent ? "#166534" : "#2a2a2a"}`,
              borderRadius: 8, cursor: "pointer", fontSize: 11,
              color: TEXT_DIM, lineHeight: 1.5,
            }}>
              <input
                type="checkbox"
                data-testid="ligotv-request-consent"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
                style={{ marginTop: 2, flexShrink: 0 }}
              />
              <span>
                <b style={{ color: TEXT }}>Consentimento LGPD.</b> Autorizo a Ligo a instalar
                câmera em via pública próxima ao endereço acima, gravar imagens 24/7
                pra fins de segurança comunitária, e disponibilizar o stream pra
                assinantes Ligo do mesmo bairro (mesmo prefixo de CEP). Estou ciente
                de que as imagens são armazenadas por até 30 dias e excluídas após.
              </span>
            </label>
            {err && (
              <div style={{
                padding: 10, background: "#2a0f0f", border: "1px solid #5b1d1d",
                borderRadius: 8, fontSize: 12, color: "#fda4af",
                display: "flex", alignItems: "center", gap: 6,
              }}>
                <AlertCircle size={14}/> {err}
              </div>
            )}
            <button
              data-testid="ligotv-request-submit"
              type="submit"
              disabled={busy || !cep || !address || !consent}
              style={{
                padding: "11px 16px", background: ACCENT, color: "white",
                border: "none", borderRadius: 8, fontWeight: 700,
                fontSize: 13, cursor: busy ? "wait" : "pointer",
                opacity: (!cep || !address || !consent) ? 0.55 : 1,
              }}
            >{busy ? "Enviando…" : "Enviar pedido"}</button>
          </form>
        )}
      </div>
    </div>
  );
}

const labelStyle = { fontSize: 11, color: TEXT_DIM, fontWeight: 700 };
const modalInputStyle = {
  display: "block", width: "100%", marginTop: 5,
  padding: "9px 11px", borderRadius: 8,
  background: "#1a1a1a", border: "1px solid #2a2a2a",
  color: TEXT, fontSize: 13, outline: "none",
  boxSizing: "border-box",
};

// ─────────────────────── Player Modal ───────────────────────
function PlayerModal({ playing, onClose }) {
  const { kind, data } = playing;
  const isYouTube = kind === "channel" && data.kind === "youtube_live";
  const isCamera = kind === "camera";
  return (
    <div
      data-testid="ligotv-player-modal"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
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
          {data.logo && <img src={data.logo} alt="" style={{ maxHeight: 28, maxWidth: 70, objectFit: "contain" }}/>}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 700, fontSize: 15 }}>{data.name}</div>
            <div style={{ fontSize: 11, color: TEXT_DIM }}>
              {isCamera
                ? <>📍 {data.neighborhood} · {data.city}/{data.uf}</>
                : <>Canal {data.number || "—"} · {data.category}</>}
            </div>
          </div>
          <button
            data-testid="ligotv-player-close"
            onClick={onClose}
            style={{
              background: "transparent", color: TEXT_DIM, border: "none",
              cursor: "pointer", padding: 6,
            }}
          ><X size={20}/></button>
        </div>
        <div style={{ padding: 16 }}>
          {isYouTube
            ? <YouTubeEmbed channelId={data.youtube_channel_id} videoId={data.youtube_video_id}/>
            : <HlsPlayer src={data.hls_url}/>}
          {data.summary && (
            <p style={{ color: TEXT_DIM, fontSize: 13, marginTop: 12, lineHeight: 1.5 }}>
              {data.summary}
            </p>
          )}
        </div>
      </div>
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
