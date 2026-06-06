/* ParceriaPublicPage.js — Vitrine pública de parcerias (claro, marketplace).
   Acionada por ?showcase=parcerias OU pelo path /parcerias. */
import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import "@/parceria/parceria.css";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api/parcerias/public`;

const CAT_COLORS = {
  Pizzaria: "#6b1fb1", "Farmácia": "#10b981", Oficina: "#f59e0b",
  Restaurante: "#ef4444", "Padaria": "#f59e0b",
  Mercado: "#3b82f6", "Outros": "#64748b",
};

export default function ParceriaPublicPage() {
  const [data, setData] = useState({ partners: [], promotions: [],
                                       categories: [] });
  const [filter, setFilter] = useState("Todas");

  useEffect(() => {
    axios.get(`${API}/showcase`).then((r) => setData(r.data))
      .catch(() => {});
  }, []);

  const partnersById = useMemo(() => Object.fromEntries(
    (data.partners || []).map((p) => [p.id, p]),
  ), [data.partners]);

  const filtered = useMemo(() => {
    if (filter === "Todas") return data.promotions;
    return (data.promotions || []).filter((p) => {
      const pa = partnersById[p.partner_id];
      return pa && pa.category === filter;
    });
  }, [data.promotions, filter, partnersById]);

  return (
    <div className="pa-public" data-testid="parceria-public-page">
      <nav className="pa-pub-nav">
        <div className="brand">
          <img src="/ligo-logo.svg" alt="Ligo" />
          <span className="brand-sep" />
          <small>Vantagens</small>
        </div>
        <a href="/cliente" className="pa-pub-nav-cta"
            data-testid="pa-pub-nav-cta">
          Sou cliente Ligo →
        </a>
      </nav>

      <header className="pa-hero">
        <span className="pa-hero-pill">Exclusivo para clientes Ligo</span>
        <h1>
          Sua internet vale<br />
          <em>muito mais.</em>
        </h1>
        <p>
          Comércios locais oferecem descontos e brindes apenas para quem é
          cliente Ligo. Mostre o QR do seu app no caixa e aproveite —
          simples assim.
        </p>
        <a href="#promos" className="pa-hero-cta">
          Ver todas as promoções →
        </a>

        <div className="pa-hero-stats">
          <div className="pa-hero-stat">
            <b>{data.partners?.length || 0}+</b>
            <span>Parceiros</span>
          </div>
          <div className="pa-hero-stat-sep" />
          <div className="pa-hero-stat">
            <b>{data.promotions?.length || 0}</b>
            <span>Promoções ativas</span>
          </div>
          <div className="pa-hero-stat-sep" />
          <div className="pa-hero-stat">
            <b>R$ 0</b>
            <span>Para o cliente</span>
          </div>
        </div>
      </header>

      <div className="pa-cat-bar">
        {["Todas", ...(data.categories || [])].map((c) => (
          <button key={c}
                   className={`pa-cat-pill ${filter === c ? "active" : ""}`}
                   onClick={() => setFilter(c)}
                   data-testid={`pa-cat-${c}`}>
            {c === "Todas" ? "Todas" : c}
          </button>
        ))}
      </div>

      <section id="promos" className="pa-promo-section">
        <div className="pa-section-head">
          <h2>
            {filter === "Todas"
              ? "Promoções em destaque"
              : `${filter} · ${filtered.length} promoção${
                filtered.length === 1 ? "" : "ões"}`}
          </h2>
          <span>{filtered.length} resultado{
            filtered.length === 1 ? "" : "s"}</span>
        </div>

        <div className="pa-promo-grid">
          {filtered.length === 0 ? (
            <div className="pa-empty-state">
              <span className="em"></span>
              <h3>Em breve, novidades por aqui</h3>
              <p>
                Estamos negociando com novos parceiros nessa categoria.
                Volte em breve!
              </p>
            </div>
          ) : filtered.map((promo) => {
            const partner = partnersById[promo.partner_id] || {};
            const color = CAT_COLORS[partner.category] || partner.color
              || "#6b1fb1";
            return (
              <PromoCard key={promo.id} promo={promo} partner={partner}
                          color={color} />
            );
          })}
        </div>
      </section>

      <section className="pa-how">
        <h2>Como funciona</h2>
        <p>
          3 passos pra economizar no comércio local — sem cadastro extra,
          sem complicação.
        </p>
        <div className="pa-how-grid">
          <div className="pa-how-step">
            <div className="n">1</div>
            <h4>Abra o app Ligo</h4>
            <p>
              Acesse o app do cliente Ligo, toque nos 3 pontinhos do menu
              e escolha “Meu QR Code”.
            </p>
          </div>
          <div className="pa-how-step">
            <div className="n">2</div>
            <h4>Mostre no caixa</h4>
            <p>
              No comércio parceiro, mostre o QR ao atendente. Ele escaneia
              pelo app do parceiro e valida na hora.
            </p>
          </div>
          <div className="pa-how-step">
            <div className="n">3</div>
            <h4>Aproveite o desconto</h4>
            <p>
              Sistema valida sua conta (ativa e adimplente) e libera a
              promoção. Pronto: você economiza, o parceiro fideliza,
              todo mundo ganha.
            </p>
          </div>
        </div>
      </section>

      <footer className="pa-public-footer">
        © 2026 <b>Ligo</b> · Vantagens com comércio local ·
        Quer ser parceiro? Fale com o time comercial.
      </footer>
    </div>
  );
}

// ─── Promo Card (com imagem lazy + fallback elegante) ───────
const CAT_EMOJI = {
  Pizzaria: "", "Farmácia": "", Oficina: "",
  Restaurante: "", "Padaria": "", Mercado: "",
  Outros: "",
};
function PromoCard({ promo, partner, color }) {
  const [imgState, setImgState] = useState(
    promo.image_url ? "loading" : "none");

  const showImage = imgState === "ok";
  const showFallback = imgState !== "ok";

  return (
    <article className="pa-promo-card"
              data-testid={`pa-promo-${promo.id}`}
              onClick={() => {
                if (partner.slug) {
                  window.location.href = `/?parceiro=${partner.slug}`;
                }
              }}
              style={{ cursor: partner.slug ? "pointer" : "default" }}>
      <div className="pa-promo-media"
            style={{
              "--c1": color + "22",
              "--c2": color + "0a",
            }}>
        {promo.image_url && (
          <img src={promo.image_url} alt={promo.title}
                className="pa-promo-img"
                style={{
                  opacity: showImage ? 1 : 0,
                  pointerEvents: showImage ? "auto" : "none",
                }}
                onLoad={() => setImgState("ok")}
                onError={() => setImgState("err")} />
        )}
        {showFallback && (
          <div className="pa-promo-fallback"
                style={{ background:
                  `linear-gradient(135deg, ${color}26, ${color}0a)` }}>
            <span style={{ fontSize: 64, opacity: .85 }}>
              {CAT_EMOJI[partner.category] || ""}
            </span>
          </div>
        )}
        <div className="pa-promo-badge">Exclusivo Ligo</div>
        {promo.max_uses_per_client && (
          <div className="pa-promo-disc">
            {promo.max_uses_per_client}×/{promo.period === "month"
              ? "mês" : promo.period === "year"
              ? "ano" : promo.period === "week"
              ? "sem" : promo.period === "day"
              ? "dia" : "uso"}
          </div>
        )}
      </div>
      <div className="pa-promo-body">
        <div className="pa-promo-cat">
          <span className="pa-promo-cat-dot"
                 style={{ background: color }} />
          {partner.category || "Parceiro"}
          {partner.neighborhood && ` · ${partner.neighborhood}`}
        </div>
        <h3 className="pa-promo-title">{promo.title}</h3>
        <p className="pa-promo-partner">
          {partner.name || promo.partner_name}
          {partner.city && ` · ${partner.city}`}
        </p>
        <div className="pa-promo-offer">
          <span></span>
          {promo.offer_summary}
        </div>
      </div>
    </article>
  );
}
