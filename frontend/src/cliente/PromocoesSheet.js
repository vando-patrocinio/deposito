/* PromocoesSheet — Card branco que sobrepõe o header do Hub.
 *
 * iter229 — substitui o antigo ProfileSheet (nome/CPF/plano). Mostra
 * preview da vitrine de promoções dos parceiros + 3 pontinhos no canto
 * direito que abrem o QR Code do cliente (com nome/CPF/plano/status).
 *
 * Mostra:
 *  - Header "PROMOÇÕES" + 3 pontinhos
 *  - Lista horizontal scrollável de 3-5 cards de promoção
 *  - Botão "Ver todas →" abre a vitrine completa (PromocoesScreen)
 */
import React, { useEffect, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { ChevronRight, MapPin } from "lucide-react";

import { COLORS, FONT_DISPLAY, sheet } from "@/cliente/ligo-theme";
import PromoDetailModal from "@/cliente/PromoDetailModal";

const API = `${process.env.REACT_APP_BACKEND_URL}/api/parcerias/public`;

const CAT_BADGE = {
  Pizzaria: "#F97316", "Farmácia": "#10b981", Oficina: "#F59E0B",
  Restaurante: "#EF4444", "Padaria": "#FBBF24",
  Mercado: "#3B82F6", "Outros": "#94A3B8",
};

export default function PromocoesSheet({ marginTop = -60, onShowQR, onViewAll }) {
  const [data, setData] = useState({ promotions: [] });
  const [loading, setLoading] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);
  // iter230 — modal de detalhe da promoção
  const [detailPromo, setDetailPromo] = useState(null);

  useEffect(() => {
    axios.get(`${API}/showcase`)
      .then((r) => setData(r.data || { promotions: [] }))
      .catch(() => setData({ promotions: [] }))
      .finally(() => setLoading(false));
  }, []);

  const previewList = (data.promotions || []).slice(0, 6);

  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }}
      transition={{ duration: .55, ease: [0.22, 1, 0.36, 1] }}
      data-testid="cliente-promocoes-sheet"
      style={{
        ...sheet(),
        margin: `${marginTop}px 16px 0`,
        padding: "20px 18px 18px",
        position: "relative", zIndex: 4,
      }}>
      {/* 3 pontinhos no canto direito */}
      <button type="button" data-testid="cliente-profile-menu-btn"
        onClick={(e) => { e.stopPropagation(); setMenuOpen((v) => !v); }}
        aria-label="Mais opções"
        style={{
          position: "absolute", top: 14, right: 14,
          width: 38, height: 38, borderRadius: "50%",
          background: "rgba(124,58,237,.08)",
          border: "1px solid rgba(124,58,237,.18)",
          color: COLORS.purpleBase, cursor: "pointer", padding: 0,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 20, fontWeight: 900, lineHeight: 1, letterSpacing: 1.5,
          zIndex: 5,
        }}>⋮</button>

      {menuOpen && (
        <>
          <div onClick={() => setMenuOpen(false)} style={{
            position: "fixed", inset: 0, zIndex: 9,
          }} />
          <div data-testid="cliente-profile-menu" style={{
            position: "absolute", top: 56, right: 14, zIndex: 10,
            background: "white",
            border: "1px solid #E0D5FF",
            borderRadius: 14, boxShadow: "0 18px 40px rgba(58,15,138,.22)",
            minWidth: 220, overflow: "hidden",
          }}>
            <button type="button" data-testid="cliente-menu-qr"
              onClick={() => { setMenuOpen(false); onShowQR && onShowQR(); }}
              style={{
                display: "flex", alignItems: "center", gap: 10,
                width: "100%", padding: "13px 16px",
                background: "white", border: "none", cursor: "pointer",
                fontSize: 13.5, fontWeight: 700, color: COLORS.slate900,
                textAlign: "left", fontFamily: "inherit",
              }}>
              <span style={{ fontSize: 18 }}>📱</span>
              Meu QR Code de cliente
            </button>
          </div>
        </>
      )}

      {/* Header do sheet */}
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                       paddingRight: 50 }}>
        <span aria-hidden style={{ fontSize: 22,
          filter: "drop-shadow(0 6px 14px rgba(252,211,77,.45))" }}>🎁</span>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{
            fontSize: 11, fontWeight: 800, letterSpacing: 2.4,
            textTransform: "uppercase", color: "#0F766E",
          }}>Vantagens de parceiros</div>
          <div data-testid="cliente-promocoes-title" style={{
            fontSize: 22, fontWeight: 900, letterSpacing: "-.015em",
            color: COLORS.slate900, lineHeight: 1.1, marginTop: 1,
          }}>Promoções</div>
        </div>
      </div>

      {/* Conteúdo: lista horizontal scrollável OU empty/loading */}
      {loading && (
        <div data-testid="promo-sheet-loading" style={{
          marginTop: 16, padding: "26px 12px", textAlign: "center",
          fontSize: 13, color: COLORS.slate500,
        }}>Carregando promoções...</div>
      )}

      {!loading && previewList.length === 0 && (
        <div data-testid="promo-sheet-empty" style={{
          marginTop: 16, padding: "20px 12px", textAlign: "center",
          fontSize: 13, color: COLORS.slate500,
          background: "#F9F7FF", borderRadius: 12,
        }}>Nenhuma promoção disponível no momento.</div>
      )}

      {!loading && previewList.length > 0 && (
        <div className="hide-scrollbar" data-testid="promo-sheet-list"
            style={{
              marginTop: 14, display: "flex", gap: 10, overflowX: "auto",
              paddingBottom: 4, scrollSnapType: "x mandatory",
              margin: "14px -18px 0", padding: "0 18px 8px",
            }}>
          {previewList.map((p, idx) => (
            <PromoMiniCard key={p.id || idx} promo={p}
              testid={`promo-mini-${p.id || idx}`}
              onClick={() => setDetailPromo(p)} />
          ))}
        </div>
      )}

      {/* Ver todas */}
      <button type="button" data-testid="promo-sheet-view-all"
        onClick={onViewAll}
        style={{
          marginTop: 14, width: "100%",
          padding: "13px 16px", borderRadius: 14,
          background: "linear-gradient(135deg, #0F766E, #064E3B)",
          color: "white", border: "none", cursor: "pointer",
          fontWeight: 900, fontSize: 13.5, letterSpacing: .4,
          fontFamily: "inherit",
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          gap: 6,
          boxShadow: "0 14px 30px rgba(15,118,110,.28)",
        }}>
        Ver todas as promoções
        <ChevronRight size={16} strokeWidth={3} />
      </button>

      <PromoDetailModal open={!!detailPromo} promo={detailPromo}
        onClose={() => setDetailPromo(null)}
        onShowQR={() => {
          setDetailPromo(null);
          onShowQR && onShowQR();
        }} />
    </motion.div>
  );
}

/* ───────────────────── PromoMiniCard ───────────────────── */
function PromoMiniCard({ promo, testid, onClick }) {
  const cat = promo.partner_category || "Outros";
  const partnerName = promo.partner_name || "";
  const catColor = CAT_BADGE[cat] || promo.partner_color || CAT_BADGE.Outros;
  const summary = promo.offer_summary || promo.description || "";
  const discountLabel = (() => {
    if (promo.discount_pct) return `${promo.discount_pct}% OFF`;
    if (promo.promo_price && promo.original_price) {
      return `R$ ${Number(promo.promo_price).toFixed(2).replace(".", ",")}`;
    }
    return null;
  })();
  return (
    <button type="button" onClick={onClick} data-testid={testid}
      style={{
        flexShrink: 0, width: 198, padding: 0,
        background: "white", border: "1px solid #EAE0FF",
        borderRadius: 18, cursor: "pointer", overflow: "hidden",
        textAlign: "left", fontFamily: "inherit",
        scrollSnapAlign: "start",
        boxShadow: "0 8px 20px rgba(58,15,138,.08)",
      }}>
      {promo.image_url && (
        <div style={{
          width: "100%", aspectRatio: "16/10",
          background: "#F4F1FF", overflow: "hidden",
        }}>
          <img src={promo.image_url} alt={promo.title}
            style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        </div>
      )}
      <div style={{ padding: "10px 11px 12px",
                       display: "flex", flexDirection: "column", gap: 4 }}>
        <span style={{
          alignSelf: "flex-start", padding: "2px 8px", borderRadius: 999,
          background: `${catColor}1A`, color: catColor,
          fontSize: 9, fontWeight: 800, letterSpacing: 1.2,
          textTransform: "uppercase",
        }}>● {cat}</span>
        <div style={{
          fontFamily: FONT_DISPLAY, fontSize: 14, fontWeight: 900,
          letterSpacing: "-.01em", color: COLORS.slate900,
          lineHeight: 1.2, overflow: "hidden",
          display: "-webkit-box", WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
        }}>{promo.title}</div>
        {summary && (
          <div style={{
            fontSize: 11.5, color: COLORS.slate500, lineHeight: 1.35,
            fontWeight: 500, overflow: "hidden",
            display: "-webkit-box", WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
          }}>{summary}</div>
        )}
        {partnerName && (
          <div style={{
            display: "flex", alignItems: "center", gap: 4,
            fontSize: 11, color: COLORS.slate500, fontWeight: 700,
          }}>
            <MapPin size={11} />
            <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                            whiteSpace: "nowrap" }}>{partnerName}</span>
          </div>
        )}
        {discountLabel && (
          <div style={{
            marginTop: 2, padding: "4px 8px", borderRadius: 8,
            background: "linear-gradient(135deg, #FFEDD5, #FED7AA)",
            color: "#9A3412", fontWeight: 900, fontSize: 11,
            textAlign: "center", letterSpacing: .3,
          }}>{discountLabel}</div>
        )}
      </div>
    </button>
  );
}
