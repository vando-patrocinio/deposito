/* PromoDetailModal — Modal de detalhe da promoção no app do cliente.
 *
 * iter230 — pedido: "quando o cliente clicar na imagem dentro app do
 * cliente que esta sendo promovida a imagem abre, e informa a
 * descriçao das regras da promoção". Mostra imagem grande, título,
 * resumo, descrição/regras, % de desconto e botão "Como usar"
 * (que abre o QR Code do cliente — handoff pro ClientQRModal).
 */
import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { MapPin, QrCode, X } from "lucide-react";

import { COLORS, FONT_DISPLAY } from "@/cliente/ligo-theme";

const BACKEND = process.env.REACT_APP_BACKEND_URL;

const CAT_COLOR = {
  Pizzaria: "#F97316", "Farmácia": "#10b981", Oficina: "#F59E0B",
  Restaurante: "#EF4444", "Padaria": "#FBBF24",
  Mercado: "#3B82F6", "Outros": "#94A3B8",
};

export default function PromoDetailModal({ open, promo, onClose, onShowQR }) {
  if (!open || !promo) return null;
  const cat = promo.partner_category || "Outros";
  const catColor = CAT_COLOR[cat] || promo.partner_color || CAT_COLOR.Outros;
  const summary = promo.offer_summary || "";
  const desc = promo.description || "";
  const terms = promo.terms || "";
  const partnerName = promo.partner_name || "";
  const discountLabel = (() => {
    if (promo.discount_pct) return `${promo.discount_pct}% OFF`;
    if (promo.promo_price && promo.original_price) {
      return `R$ ${Number(promo.promo_price).toFixed(2).replace(".", ",")}`;
    }
    return null;
  })();
  const imageUrl = promo.image_url
    ? (promo.image_url.startsWith("http") ? promo.image_url
       : `${BACKEND}${promo.image_url}`)
    : null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        data-testid="promo-detail-modal"
        onClick={onClose}
        style={{
          position: "fixed", inset: 0, zIndex: 999,
          background: "rgba(10,4,30,.78)",
          backdropFilter: "blur(8px)",
          display: "flex", alignItems: "flex-end", justifyContent: "center",
          padding: 0,
          fontFamily: "'Inter', system-ui, sans-serif",
          overflow: "auto",
        }}>
        <motion.div
          initial={{ y: 60, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 60, opacity: 0 }}
          transition={{ duration: .35, ease: [0.22, 1, 0.36, 1] }}
          onClick={(e) => e.stopPropagation()}
          style={{
            width: "100%", maxWidth: 540,
            background: "white", borderTopLeftRadius: 28,
            borderTopRightRadius: 28, overflow: "hidden",
            color: COLORS.slate900,
            boxShadow: "0 -30px 60px rgba(0,0,0,.4)",
            maxHeight: "92vh", display: "flex", flexDirection: "column",
          }}>
          {/* Imagem hero */}
          {imageUrl && (
            <div style={{
              width: "100%", aspectRatio: "16/10",
              background: "#F4F1FF", overflow: "hidden", flexShrink: 0,
              position: "relative",
            }}>
              <img src={imageUrl} alt={promo.title}
                style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              <button onClick={onClose} type="button"
                data-testid="promo-detail-close"
                aria-label="Fechar"
                style={{
                  position: "absolute", top: 14, right: 14,
                  width: 38, height: 38, borderRadius: "50%",
                  background: "rgba(0,0,0,.55)",
                  border: "1px solid rgba(255,255,255,.25)",
                  color: "white", cursor: "pointer", padding: 0,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  backdropFilter: "blur(6px)",
                }}><X size={18} /></button>
            </div>
          )}

          <div style={{ padding: 22, overflowY: "auto", flex: 1 }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <span style={{
                padding: "3px 10px", borderRadius: 999,
                background: `${catColor}1A`, color: catColor,
                fontSize: 10, fontWeight: 800, letterSpacing: 1.4,
                textTransform: "uppercase",
              }}>● {cat}</span>
              {promo.product_category && (
                <span style={{
                  padding: "3px 10px", borderRadius: 999,
                  background: "#EDE9FE", color: "#7c3aed",
                  fontSize: 10, fontWeight: 800, letterSpacing: 1.4,
                  textTransform: "uppercase",
                }}>{promo.product_category}</span>
              )}
              {discountLabel && (
                <span style={{
                  padding: "3px 10px", borderRadius: 999,
                  background: "linear-gradient(135deg, #FFEDD5, #FED7AA)",
                  color: "#9A3412",
                  fontSize: 11, fontWeight: 900, letterSpacing: .4,
                }}>{discountLabel}</span>
              )}
            </div>

            <h2 style={{
              margin: "12px 0 6px", fontFamily: FONT_DISPLAY,
              fontSize: 26, fontWeight: 900, letterSpacing: "-.02em",
              lineHeight: 1.15, color: COLORS.slate900,
            }}>{promo.title}</h2>

            {summary && (
              <p style={{
                margin: "0 0 14px", fontSize: 15, fontWeight: 600,
                color: "#0F766E", lineHeight: 1.4,
              }}>{summary}</p>
            )}

            {desc && (
              <div data-testid="promo-detail-description"
                style={{ marginTop: 14 }}>
                <SectionLabel>Sobre a promoção</SectionLabel>
                <p style={{ margin: 0, fontSize: 14, lineHeight: 1.55,
                              color: COLORS.slate700,
                              whiteSpace: "pre-line" }}>{desc}</p>
              </div>
            )}

            {terms && (
              <div data-testid="promo-detail-terms"
                style={{ marginTop: 18, padding: 14, borderRadius: 14,
                            background: "#FEF6E7",
                            border: "1px solid #FDBA74" }}>
                <SectionLabel color="#9A3412">Regras e condições</SectionLabel>
                <p style={{ margin: 0, fontSize: 13, lineHeight: 1.55,
                              color: "#7C2D12", whiteSpace: "pre-line",
                              fontWeight: 500 }}>{terms}</p>
              </div>
            )}

            {partnerName && (
              <div style={{ marginTop: 18, display: "flex",
                              alignItems: "center", gap: 8,
                              padding: "12px 14px", borderRadius: 12,
                              background: "#F4F1FF",
                              border: "1px solid #E0D5FF" }}>
                <MapPin size={16} color={COLORS.purpleBase} />
                <div>
                  <div style={{ fontSize: 11, fontWeight: 800,
                                    letterSpacing: 1.2,
                                    textTransform: "uppercase",
                                    color: COLORS.purpleBase }}>
                    Disponível em
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 800,
                                    color: COLORS.slate900,
                                    marginTop: 2 }}>{partnerName}</div>
                </div>
              </div>
            )}
          </div>

          {/* CTA fixo */}
          <div style={{ padding: 18, borderTop: "1px solid #EAE0FF",
                           background: "white" }}>
            <button onClick={onShowQR} type="button"
              data-testid="promo-detail-show-qr"
              style={{
                width: "100%", padding: "14px 18px", borderRadius: 14,
                background: "linear-gradient(135deg, #0F766E, #064E3B)",
                color: "white", border: "none", cursor: "pointer",
                fontWeight: 900, fontSize: 14.5, letterSpacing: .4,
                fontFamily: "inherit",
                display: "inline-flex", alignItems: "center",
                justifyContent: "center", gap: 8,
                boxShadow: "0 14px 30px rgba(15,118,110,.32)",
              }}>
              <QrCode size={18} />
              Mostrar meu QR Code no caixa
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

function SectionLabel({ children, color = "#7c3aed" }) {
  return (
    <div style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: 1.6,
                     textTransform: "uppercase", color, marginBottom: 6 }}>
      {children}
    </div>
  );
}
