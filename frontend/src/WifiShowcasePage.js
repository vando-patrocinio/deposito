/* WifiShowcasePage — Vitrine pública dos hotspots WiFi Ligo.
   Acionado por `?showcase=wifi` ou `/wifi-vitrine`.
   Mostra todos os pontos de WiFi gratuito (cafés parceiros, eventos, lojas)
   pro cliente Ligo descobrir onde conectar quando estiver fora de casa.
*/
import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { Wifi, MapPin, Search, ExternalLink } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api/wifi-hotspot/public`;

const COLORS = {
  ink: "#0f172a",
  purple: "#6B2BFB",
  orange: "#FF6A1A",
  bg: "#FAFAF7",
  card: "#FFFFFF",
  line: "#E5E7EB",
  mute: "#64748b",
};

export default function WifiShowcasePage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all"); // all | ligo | parceiro

  useEffect(() => {
    ensureFont();
    axios.get(`${API}/showcase`)
      .then((r) => setItems(r.data?.items || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    return items.filter((v) => {
      if (filter !== "all" && (v.type || "ligo") !== filter) return false;
      if (!term) return true;
      return (
        (v.name || "").toLowerCase().includes(term) ||
        (v.address || "").toLowerCase().includes(term)
      );
    });
  }, [items, q, filter]);

  return (
    <div data-testid="wifi-showcase" style={{
      minHeight: "100vh", background: COLORS.bg, color: COLORS.ink,
      fontFamily: "'Sora', 'Inter', system-ui, sans-serif",
      display: "flex", flexDirection: "column",
    }}>
      <Header />
      <main style={{ flex: 1, width: "100%", maxWidth: 1180,
        margin: "0 auto", padding: "32px 20px 60px", boxSizing: "border-box" }}>
        <div style={{ display: "flex", alignItems: "flex-end",
          justifyContent: "space-between", flexWrap: "wrap", gap: 18,
          marginBottom: 26 }}>
          <div>
            <span style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "5px 12px", borderRadius: 999,
              background: "rgba(107,43,251,.08)", color: COLORS.purple,
              fontSize: 11, fontWeight: 800, letterSpacing: 1.6,
              textTransform: "uppercase",
            }}>
              <Wifi size={13} /> WiFi Ligo · Vitrine pública
            </span>
            <h1 style={{
              margin: "12px 0 6px", fontSize: "clamp(28px, 4vw, 44px)",
              fontWeight: 900, letterSpacing: "-.02em", lineHeight: 1.05,
            }}>
              WiFi grátis perto de você
            </h1>
            <p style={{ margin: 0, color: COLORS.mute,
              fontSize: 15, maxWidth: 600, lineHeight: 1.5 }}>
              Conecte-se em <b>cafés parceiros</b>, lojas, praças e eventos
              <b> Ligo Fibra</b>. Acesso liberado direto pelo app, sem senha.
            </p>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <FilterPill active={filter === "all"}
              onClick={() => setFilter("all")} label="Todos" />
            <FilterPill active={filter === "ligo"}
              onClick={() => setFilter("ligo")} label="Ligo" />
            <FilterPill active={filter === "parceiro"}
              onClick={() => setFilter("parceiro")} label="Parceiros" />
          </div>
        </div>

        <div style={{
          position: "relative", marginBottom: 22, maxWidth: 480,
        }}>
          <Search size={16} color={COLORS.mute}
            style={{ position: "absolute", left: 14, top: 14 }} />
          <input value={q} onChange={(e) => setQ(e.target.value)}
            data-testid="wifi-showcase-search"
            placeholder="Buscar por nome ou endereço…"
            style={{
              width: "100%", padding: "12px 14px 12px 40px",
              borderRadius: 12, border: `1.5px solid ${COLORS.line}`,
              background: "white", fontSize: 14, color: COLORS.ink,
              outline: "none", fontFamily: "inherit",
              boxSizing: "border-box",
            }} />
        </div>

        {loading ? (
          <SkeletonGrid />
        ) : filtered.length === 0 ? (
          <Empty />
        ) : (
          <div style={{
            display: "grid", gap: 16,
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
          }}>
            {filtered.map((v) => <VenueCard key={v.id || v.slug} v={v} />)}
          </div>
        )}
      </main>
      <Footer />
    </div>
  );
}

function Header() {
  return (
    <header style={{
      position: "sticky", top: 0, zIndex: 10,
      background: "rgba(255,255,255,.92)",
      backdropFilter: "blur(20px) saturate(180%)",
      WebkitBackdropFilter: "blur(20px) saturate(180%)",
      borderBottom: `1px solid ${COLORS.line}`,
      padding: "10px 24px",
    }}>
      <div style={{
        maxWidth: 1180, margin: "0 auto",
        display: "flex", justifyContent: "space-between",
        alignItems: "center", gap: 18,
      }}>
        <a href="/" style={{
          display: "flex", alignItems: "center", gap: 10,
          textDecoration: "none", color: COLORS.ink,
        }}>
          <img src="/ligo-logo.svg" alt="Ligo Fibra"
            style={{ height: 120, width: "auto",
              imageRendering: "-webkit-optimize-contrast" }} />
        </a>
        <a href="/cliente" data-testid="wifi-showcase-cta-app"
          style={{
            padding: "9px 18px", borderRadius: 999,
            background: `linear-gradient(120deg, ${COLORS.purple}, ${COLORS.orange})`,
            color: "white", fontSize: 12.5, fontWeight: 800,
            textDecoration: "none", display: "inline-flex",
            alignItems: "center", gap: 6,
            boxShadow: "0 8px 22px rgba(107,43,251,.32)",
          }}>
          Abrir app Ligo <ExternalLink size={13} />
        </a>
      </div>
    </header>
  );
}

function FilterPill({ active, label, onClick }) {
  return (
    <button onClick={onClick}
      data-testid={`wifi-showcase-filter-${label.toLowerCase()}`}
      style={{
        padding: "8px 16px", borderRadius: 999, cursor: "pointer",
        border: `1.5px solid ${active ? COLORS.purple : COLORS.line}`,
        background: active ? COLORS.purple : "white",
        color: active ? "white" : COLORS.ink,
        fontWeight: 800, fontSize: 12.5, letterSpacing: .2,
        fontFamily: "inherit",
        transition: "all .15s",
      }}>{label}</button>
  );
}

function VenueCard({ v }) {
  const isParceiro = (v.type || "ligo") === "parceiro";
  const brand = v.brand || {};
  return (
    <a href={`/wifi/${v.slug}`} target="_blank" rel="noreferrer"
      data-testid={`wifi-showcase-venue-${v.slug}`}
      style={{
        display: "block", textDecoration: "none", color: "inherit",
        background: COLORS.card, borderRadius: 18,
        border: `1px solid ${COLORS.line}`,
        overflow: "hidden", transition: "transform .15s, box-shadow .15s",
        boxShadow: "0 2px 12px rgba(15,23,42,.04)",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = "translateY(-3px)";
        e.currentTarget.style.boxShadow = "0 12px 30px rgba(15,23,42,.10)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = "translateY(0)";
        e.currentTarget.style.boxShadow = "0 2px 12px rgba(15,23,42,.04)";
      }}>
      <div style={{
        height: 130, position: "relative",
        background: brand.background_url
          ? `url(${brand.background_url}) center/cover`
          : `linear-gradient(135deg, ${brand.color_primary || COLORS.purple}, ${brand.color_accent || COLORS.orange})`,
      }}>
        {isParceiro ? (
          <span style={{
            position: "absolute", top: 12, left: 12,
            padding: "4px 10px", borderRadius: 999,
            background: "rgba(255,255,255,.95)",
            fontSize: 10.5, fontWeight: 800,
            letterSpacing: 1.2, textTransform: "uppercase",
            color: COLORS.orange,
          }}>Parceiro</span>
        ) : (
          <span style={{
            position: "absolute", top: 12, left: 12,
            padding: "6px 12px", borderRadius: 999,
            background: "rgba(255,255,255,.95)",
            display: "inline-flex", alignItems: "center",
            boxShadow: "0 2px 8px rgba(15,23,42,.12)",
          }}>
            <img src="/ligo-logo.svg" alt="Ligo"
              style={{ height: 18, width: "auto",
                display: "block" }} />
          </span>
        )}
        {brand.logo_url && (
          <img src={brand.logo_url} alt=""
            style={{
              position: "absolute", bottom: 12, right: 12,
              height: 36, width: "auto",
              filter: "drop-shadow(0 2px 8px rgba(0,0,0,.25))",
            }} />
        )}
      </div>
      <div style={{ padding: 16 }}>
        <div style={{ fontSize: 16, fontWeight: 800, marginBottom: 6,
          lineHeight: 1.25 }}>
          {v.name}
        </div>
        {v.address && (
          <div style={{ display: "flex", alignItems: "flex-start", gap: 6,
            fontSize: 12.5, color: COLORS.mute, lineHeight: 1.4 }}>
            <MapPin size={13} style={{ marginTop: 2, flexShrink: 0 }} />
            <span>{v.address}</span>
          </div>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 8,
          marginTop: 14, paddingTop: 12,
          borderTop: `1px solid ${COLORS.line}` }}>
          <Wifi size={14} color={COLORS.purple} />
          <span style={{ fontSize: 11.5, fontWeight: 700,
            color: COLORS.purple }}>
            Conectar grátis · {v.session_minutes || 60} min
          </span>
        </div>
      </div>
    </a>
  );
}

function SkeletonGrid() {
  return (
    <div style={{
      display: "grid", gap: 16,
      gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
    }}>
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div key={i} style={{
          height: 270, borderRadius: 18, background: "white",
          border: `1px solid ${COLORS.line}`,
          animation: "pulse 1.5s ease-in-out infinite",
        }} />
      ))}
      <style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:.55}}`}</style>
    </div>
  );
}

function Empty() {
  return (
    <div data-testid="wifi-showcase-empty" style={{
      textAlign: "center", padding: "60px 20px",
      background: "white", borderRadius: 18,
      border: `1px dashed ${COLORS.line}`,
    }}>
      <Wifi size={36} color={COLORS.mute} />
      <h3 style={{ margin: "16px 0 6px", fontSize: 18, fontWeight: 800 }}>
        Nenhum hotspot encontrado
      </h3>
      <p style={{ margin: 0, color: COLORS.mute, fontSize: 13.5 }}>
        Tente outra busca ou filtro. Novos pontos são adicionados toda semana.
      </p>
    </div>
  );
}

function Footer() {
  return (
    <footer style={{
      background: COLORS.ink, color: "white", padding: "28px 20px",
    }}>
      <div style={{
        maxWidth: 1180, margin: "0 auto",
        display: "flex", justifyContent: "space-between",
        alignItems: "center", flexWrap: "wrap", gap: 14,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <img src="/ligo-logo-white.svg" alt="Ligo Fibra"
            style={{ height: 28, width: "auto", opacity: .9 }} />
          <span style={{ fontSize: 12.5, opacity: .8 }}>
            WiFi Ligo · Hotspots públicos
          </span>
        </div>
        <div style={{ fontSize: 11.5, opacity: .65 }}>
          © {new Date().getFullYear()} Ligo Fibra · Todos os direitos reservados
        </div>
      </div>
    </footer>
  );
}

function ensureFont() {
  if (document.getElementById("sora-font-link")) return;
  const link = document.createElement("link");
  link.id = "sora-font-link";
  link.rel = "stylesheet";
  link.href = "https://fonts.googleapis.com/css2?family=Sora:wght@500;700;800;900&display=swap";
  document.head.appendChild(link);
}
