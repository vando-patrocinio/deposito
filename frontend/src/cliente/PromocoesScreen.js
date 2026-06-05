/* PromocoesScreen — Vitrine de parceiros embarcada no `/cliente`.
 *
 * iter228 — clica no card "Promoções" do Hub e cai aqui. Usa a mesma
 * API pública /api/parcerias/public/showcase do site público, mas em
 * layout mobile-first do tema Ligo (dark/purple + orange CTAs).
 */
import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { MapPin, Search } from "lucide-react";

import { COLORS, FONT_DISPLAY } from "@/cliente/ligo-theme";
import { Shell, HeaderHero } from "@/cliente/components";
import PromoDetailModal from "@/cliente/PromoDetailModal";
import ClientQRModal from "@/cliente/ClientQRModal";

const API = `${process.env.REACT_APP_BACKEND_URL}/api/parcerias/public`;

const CAT_BADGE = {
  Pizzaria: "#F97316", "Farmácia": "#10b981", Oficina: "#F59E0B",
  Restaurante: "#EF4444", "Padaria": "#FBBF24",
  Mercado: "#3B82F6", "Outros": "#94A3B8",
};

export default function PromocoesScreen({ onBack, onLogout, me }) {
  const [data, setData] = useState({ partners: [], promotions: [],
                                       categories: [] });
  const [filter, setFilter] = useState("Todas");
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  // iter230 — modal de detalhe + QR
  const [detailPromo, setDetailPromo] = useState(null);
  const [qrOpen, setQrOpen] = useState(false);

  useEffect(() => {
    axios.get(`${API}/showcase`)
      .then((r) => setData(r.data || {}))
      .catch(() => setData({ partners: [], promotions: [], categories: [] }))
      .finally(() => setLoading(false));
  }, []);

  const partnersById = useMemo(() => Object.fromEntries(
    (data.partners || []).map((p) => [p.id, p]),
  ), [data.partners]);

  const filtered = useMemo(() => {
    let list = data.promotions || [];
    if (filter !== "Todas") {
      list = list.filter((p) => {
        const pa = partnersById[p.partner_id];
        if (pa && pa.category === filter) return true;
        // iter231 — filtro também bate na categoria DO PRODUTO da promoção
        return p.product_category === filter;
      });
    }
    if (q.trim()) {
      const needle = q.trim().toLowerCase();
      list = list.filter((p) => {
        const pa = partnersById[p.partner_id] || {};
        return (
          (p.title || "").toLowerCase().includes(needle) ||
          (p.description || "").toLowerCase().includes(needle) ||
          (p.product_category || "").toLowerCase().includes(needle) ||
          (pa.name || "").toLowerCase().includes(needle)
        );
      });
    }
    return list;
  }, [data.promotions, filter, partnersById, q]);

  // iter231 — junta categoria do parceiro + categoria do produto
  const allCategories = useMemo(() => {
    const set = new Set([...(data.categories || [])]);
    (data.promotions || []).forEach((p) => {
      if (p.product_category) set.add(p.product_category);
    });
    return ["Todas", ...Array.from(set).sort((a, b) => a.localeCompare(b))];
  }, [data.categories, data.promotions]);

  const categories = allCategories;

  return (
    <Shell testid="cliente-promocoes-screen">
      <HeaderHero
        greeting="Suas"
        greetingName="Vantagens"
        greetingEmoji="🎁"
        subtitle="Descontos exclusivos só pra clientes Ligo."
        onBack={onBack}
        onLogout={onLogout}
        height={210}
      />

      <div style={{ position: "relative", zIndex: 3, marginTop: -50,
                       padding: "0 16px" }}>
        {/* Search bar */}
        <div data-testid="promocoes-search"
            style={{
              display: "flex", alignItems: "center", gap: 10,
              background: "white", borderRadius: 18,
              border: "1px solid #E0D5FF",
              padding: "10px 14px",
              boxShadow: "0 18px 40px rgba(58,15,138,.16)",
            }}>
          <Search size={18} color={COLORS.purpleBase} />
          <input value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Buscar promoções, parceiros..."
            style={{
              flex: 1, border: "none", outline: "none",
              fontSize: 14.5, fontWeight: 500, color: COLORS.slate900,
              fontFamily: "inherit", background: "transparent",
            }} />
        </div>

        {/* Category pills */}
        <div className="hide-scrollbar" style={{
          marginTop: 14, display: "flex", gap: 8, overflowX: "auto",
          paddingBottom: 4,
        }}>
          {categories.map((c) => (
            <button key={c} type="button"
              data-testid={`promocoes-cat-${c}`}
              onClick={() => setFilter(c)}
              style={{
                flexShrink: 0, padding: "8px 16px", borderRadius: 999,
                border: filter === c
                  ? `1.5px solid ${COLORS.purpleBase}`
                  : "1.5px solid rgba(124,58,237,.18)",
                background: filter === c ? COLORS.purpleBase : "white",
                color: filter === c ? "white" : COLORS.purpleBase,
                fontSize: 12.5, fontWeight: 800, letterSpacing: .3,
                cursor: "pointer", fontFamily: "inherit",
              }}>{c}</button>
          ))}
        </div>

        {/* Grid */}
        <div data-testid="promocoes-grid" style={{
          marginTop: 18, display: "grid", gap: 12,
          gridTemplateColumns: "1fr",
          paddingBottom: 40,
        }}>
          <style>{`
            @media (min-width: 600px) {
              [data-testid="promocoes-grid"] {
                grid-template-columns: 1fr 1fr;
              }
            }
            @media (min-width: 1000px) {
              [data-testid="promocoes-grid"] {
                grid-template-columns: 1fr 1fr 1fr;
              }
            }
          `}</style>

          {loading && (
            <div data-testid="promocoes-loading"
              style={{ padding: "40px 20px", textAlign: "center",
                         color: COLORS.slate500, fontSize: 14 }}>
              Carregando promoções...
            </div>
          )}

          {!loading && filtered.length === 0 && (
            <div data-testid="promocoes-empty"
              style={{ padding: "40px 20px", textAlign: "center",
                         color: COLORS.slate500, fontSize: 14 }}>
              Nenhuma promoção encontrada.
            </div>
          )}

          {filtered.map((p, idx) => (
            <PromoCard key={p.id || idx}
              promo={p} partner={partnersById[p.partner_id]}
              testid={`promo-card-${p.id || idx}`}
              onClick={() => setDetailPromo(p)} />
          ))}
        </div>
      </div>

      <PromoDetailModal open={!!detailPromo} promo={detailPromo}
        onClose={() => setDetailPromo(null)}
        onShowQR={() => { setDetailPromo(null); setQrOpen(true); }} />
      <ClientQRModal open={qrOpen} me={me}
        onClose={() => setQrOpen(false)} />
    </Shell>
  );
}

/* ───────────────────────── PromoCard ───────────────────────── */
function PromoCard({ promo, partner, testid, onClick }) {
  // promo já vem embarcado com partner_name / partner_category /
  // partner_color do backend — usamos como fallback se `partner` não veio.
  const category = partner?.category || promo.partner_category || "Outros";
  const partnerName = partner?.name || promo.partner_name || "";
  const catColor = CAT_BADGE[category] || promo.partner_color || CAT_BADGE.Outros;
  const summary = promo.offer_summary || promo.description || "";
  // discount_label sintetizado a partir do que vier no payload
  const discountLabel = (() => {
    if (promo.discount_label) return promo.discount_label;
    if (promo.discount_pct) return `${promo.discount_pct}% OFF`;
    if (promo.promo_price && promo.original_price) {
      return `R$ ${Number(promo.promo_price).toFixed(2).replace(".", ",")} (de R$ ${Number(promo.original_price).toFixed(2).replace(".", ",")})`;
    }
    return null;
  })();
  return (
    <motion.div
      initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }}
      transition={{ duration: .4, ease: [0.22, 1, 0.36, 1] }}
      data-testid={testid}
      onClick={onClick}
      style={{
        background: "white", borderRadius: 20,
        border: "1px solid #EAE0FF",
        boxShadow: "0 14px 32px rgba(58,15,138,.10)",
        overflow: "hidden", display: "flex", flexDirection: "column",
        cursor: onClick ? "pointer" : "default",
      }}>
      {promo.image_url && (
        <div style={{
          aspectRatio: "16/9", overflow: "hidden",
          background: "#F4F1FF",
        }}>
          <img src={promo.image_url} alt={promo.title}
            style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        </div>
      )}
      <div style={{ padding: 14, display: "flex", flexDirection: "column",
                       gap: 8 }}>
        {category && (
          <span style={{
            display: "inline-flex", alignSelf: "flex-start",
            padding: "3px 10px", borderRadius: 999,
            background: `${catColor}1A`, color: catColor,
            fontSize: 10, fontWeight: 800, letterSpacing: 1.4,
            textTransform: "uppercase",
          }}>● {category}</span>
        )}
        <h3 style={{
          margin: 0, fontFamily: FONT_DISPLAY,
          fontSize: 17, fontWeight: 900, letterSpacing: "-.01em",
          lineHeight: 1.2, color: COLORS.slate900,
        }}>{promo.title}</h3>
        {summary && (
          <p style={{
            margin: 0, fontSize: 13, color: COLORS.slate700,
            lineHeight: 1.45, fontWeight: 500,
          }}>{summary}</p>
        )}
        {partnerName && (
          <div style={{
            display: "flex", alignItems: "center", gap: 6,
            fontSize: 12, color: COLORS.slate500, fontWeight: 700,
            marginTop: 4,
          }}>
            <MapPin size={13} />
            {partnerName}
          </div>
        )}
        {discountLabel && (
          <div style={{
            marginTop: 6, padding: "8px 12px", borderRadius: 12,
            background: "linear-gradient(135deg, #FFEDD5, #FED7AA)",
            border: "1px solid #FDBA74", color: "#9A3412",
            fontWeight: 900, fontSize: 13, textAlign: "center",
            letterSpacing: .3,
          }}>{discountLabel}</div>
        )}
      </div>
    </motion.div>
  );
}
