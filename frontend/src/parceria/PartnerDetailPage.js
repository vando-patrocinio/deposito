/* PartnerDetailPage.js — Página pública individual do parceiro Ligo.
   Acionada por ?parceiro=slug
   - Carrossel auto-rotativo das promoções (com % desconto + rating)
   - Feed de clientes recentes que receberam o benefício (mascarado)
   - Se houver token de parceiro_portal no localStorage → 3-pontinhos
     abre QR scanner (igual ao app do parceiro) e botão "+ Item novo".
*/
import React, { useEffect, useMemo, useState, useRef } from "react";
import axios from "axios";
import { Html5Qrcode } from "html5-qrcode";
import "@/parceria/parceria.css";
import "@/parceria/partner-detail.css";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;
const PARTNER_LS = "partner_portal_token";

export default function PartnerDetailPage() {
  const slug = useMemo(() => {
    const p = new URLSearchParams(window.location.search);
    return p.get("parceiro")
      || window.location.pathname.replace(/^\/parceiro\//, "") || "";
  }, []);
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [carouselIdx, setCarouselIdx] = useState(0);
  const [menu, setMenu] = useState(false);
  const [showScan, setShowScan] = useState(false);
  const [showAddItem, setShowAddItem] = useState(false);
  const [scanResult, setScanResult] = useState(null);

  // Detecta `?p=<magic_token>` UPFRONT pra evitar flash de erro
  const magicParam = useMemo(() =>
    new URLSearchParams(window.location.search).get("p") || "",
    []);
  const [magicBusy, setMagicBusy] = useState(!!magicParam);
  useEffect(() => {
    if (!magicParam) return;
    axios.post(`${API}/parceiro-portal/auth/magic`,
                 { magic_token: magicParam })
      .then((r) => {
        localStorage.setItem(PARTNER_LS, r.data.access_token);
        const targetSlug = r.data.partner?.slug || slug;
        window.location.replace(
          `${window.location.origin}/?parceiro=${targetSlug}`);
      })
      .catch((ex) => {
        setErr(ex?.response?.data?.detail || "Link inválido");
        setMagicBusy(false);
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [magicParam]);

  const [partnerToken, setPartnerToken] = useState(
    typeof window !== "undefined"
      ? localStorage.getItem(PARTNER_LS) : null);

  const refresh = async () => {
    try {
      const r = await axios.get(
        `${API}/parcerias/public/partner/${slug}`);
      setData(r.data);
    } catch (ex) {
      setErr(ex?.response?.data?.detail || "Parceiro não encontrado");
    }
  };
  useEffect(() => { if (slug) refresh(); }, [slug]);

  // auto-rotate carousel
  useEffect(() => {
    if (!data?.promotions?.length) return;
    const id = setInterval(() => {
      setCarouselIdx((i) => (i + 1) % data.promotions.length);
    }, 5500);
    return () => clearInterval(id);
  }, [data?.promotions]);

  const isOwner = partnerToken && data?.partner;
  const [editingPromo, setEditingPromo] = useState(null);

  if (magicBusy) {
    return <div className="pd-loading">Autenticando…</div>;
  }
  if (err) {
    return (
      <div className="pd-error">
        <h1>{err}</h1>
        <a href="/?showcase=parcerias">← Voltar para a vitrine</a>
      </div>
    );
  }
  if (!slug) {
    return (
      <div className="pd-error">
        <h1>Link inválido</h1>
        <a href="/?showcase=parcerias">← Vitrine Ligo</a>
      </div>
    );
  }
  if (!data) {
    return <div className="pd-loading">Carregando…</div>;
  }

  const { partner, promotions, recent_redemptions, ratings,
            rating_avg, rating_count, total_redemptions } = data;
  const current = promotions[carouselIdx];

  return (
    <div className="pd-root" data-testid="partner-detail-page">
      {/* Cover hero */}
      <header className="pd-cover"
                style={{ "--accent": partner.color || "#6b1fb1" }}>
        {partner.cover_url && (
          <img src={partner.cover_url} alt="" className="pd-cover-img"
                onError={(e) => { e.currentTarget.style.display = "none"; }} />
        )}
        <div className="pd-cover-overlay" />

        <nav className="pd-nav">
          <a href="/?showcase=parcerias" className="pd-back">
            ← Vitrine Ligo
          </a>
          <div style={{ flex: 1 }} />
          <button className="pd-dots" onClick={() => setMenu((m) => !m)}
                   data-testid="pd-dots">⋯</button>
          {menu && (
            <div className="pd-menu">
              {isOwner ? (
                <>
                  <button className="pd-menu-item"
                           onClick={() => {
                             setShowScan(true); setMenu(false);
                           }}
                           data-testid="pd-menu-scan">
                    <span></span> Ler QR do cliente
                  </button>
                  <button className="pd-menu-item"
                           onClick={() => {
                             setShowAddItem(true); setMenu(false);
                           }}
                           data-testid="pd-menu-add">
                    <span>＋</span> Adicionar item/promoção
                  </button>
                  <div className="pd-menu-divider" />
                  <button className="pd-menu-item danger"
                           onClick={() => {
                             localStorage.removeItem(PARTNER_LS);
                             window.location.reload();
                           }}>
                    <span>⎋</span> Sair do parceiro
                  </button>
                </>
              ) : (
                <>
                  <button className="pd-menu-item"
                           onClick={() => {
                             window.location.href = "/?portal=parceiro";
                           }}
                           data-testid="pd-menu-login">
                    <span></span> Entrar como parceiro
                  </button>
                  <a className="pd-menu-item"
                      href={`https://api.whatsapp.com/send?phone=${
                        (partner.phone || "").replace(/\D/g, "")}`}
                      target="_blank" rel="noreferrer">
                    <span></span> Falar no WhatsApp
                  </a>
                </>
              )}
            </div>
          )}
        </nav>

        <div className="pd-cover-content">
          {partner.logo_url ? (
            <img src={partner.logo_url} alt={partner.name}
                  className="pd-cover-logo"
                  onError={(e) => {
                    e.currentTarget.style.display = "none";
                  }} />
          ) : (
            <div className="pd-cover-emoji"></div>
          )}
          <h1 className="pd-name">{partner.name}</h1>
          <div className="pd-meta">
            <span>{partner.neighborhood || partner.city}</span>
            <span>·</span>
            <span>{partner.category}</span>
            {partner.phone && (<>
              <span>·</span>
              <span>{partner.phone}</span>
            </>)}
          </div>
          <div className="pd-rating-row">
            <Stars value={rating_avg} />
            <span className="pd-rating-num">
              {rating_avg ? rating_avg.toFixed(1) : "—"}
              <small>({rating_count} avaliaç{rating_count === 1
                ? "ão" : "ões"})</small>
            </span>
            <span className="pd-sep">·</span>
            <span className="pd-rating-stat">
              {total_redemptions} resgate{total_redemptions === 1
                ? "" : "s"}
            </span>
          </div>
        </div>
      </header>

      {/* Owner banner */}
      {isOwner && (
        <div className="pd-owner-banner" data-testid="pd-owner-banner">
          <span>Olá, <b>{partner.name}</b>! Você está no modo
            <b> proprietário</b>.</span>
          <button onClick={() => setShowAddItem(true)}
                   data-testid="pd-owner-add"
                   className="pd-owner-add">
            ＋ Nova promoção
          </button>
        </div>
      )}

      {/* Carrossel */}
      {promotions.length > 0 ? (
        <section className="pd-carousel"
                   data-testid="pd-carousel">
          <div className="pd-slide-wrap">
            {promotions.map((p, i) => (
              <article key={p.id}
                        className={`pd-slide ${i === carouselIdx
                          ? "active" : ""}`}
                        data-testid={`pd-slide-${i}`}>
                <div className="pd-slide-img-wrap">
                  {p.image_url ? (
                    <img src={p.image_url} alt={p.title}
                          className="pd-slide-img"
                          onError={(e) => {
                            e.currentTarget.style.display = "none";
                          }} />
                  ) : (
                    <div className="pd-slide-fallback"
                          style={{ background:
                            `linear-gradient(135deg, ${partner.color}26, ${partner.color}10)` }}>
                      <span style={{ fontSize: 96 }}>
                        {CAT_EMOJI[partner.category] || ""}
                      </span>
                    </div>
                  )}
                  {p.discount_pct > 0 && (
                    <div className="pd-discount-badge">
                      <b>{Math.round(p.discount_pct)}%</b>
                      <small>OFF</small>
                    </div>
                  )}
                  <div className="pd-slide-rating">
                    <Stars value={p.rating_avg} small />
                    {p.rating_count > 0 && (
                      <span>({p.rating_count})</span>
                    )}
                  </div>
                </div>
                <div className="pd-slide-body">
                  <h3>{p.title}</h3>
                  <p className="pd-slide-offer">{p.offer_summary}</p>
                  {(p.original_price > 0 || p.promo_price > 0) && (
                    <div className="pd-prices">
                      {p.original_price > 0 && (
                        <span className="pd-price-old">
                          R$ {p.original_price.toFixed(2)}
                        </span>
                      )}
                      {p.promo_price > 0 && (
                        <span className="pd-price-new">
                          R$ {p.promo_price.toFixed(2)}
                        </span>
                      )}
                    </div>
                  )}
                  {p.description && (
                    <p className="pd-slide-desc">{p.description}</p>
                  )}
                  {p.terms && (
                    <p className="pd-slide-terms">{p.terms}</p>
                  )}
                  {isOwner && (
                    <div className="pd-owner-actions">
                      <button onClick={() => setEditingPromo(p)}
                               data-testid={`pd-edit-${p.id}`}>
                        ✏ Editar
                      </button>
                      <button onClick={async () => {
                        if (!window.confirm("Remover esta promoção?")) return;
                        await axios.delete(
                          `${API}/parceiro-portal/promotions/${p.id}`,
                          { headers: {
                            Authorization: `Bearer ${partnerToken}` } });
                        refresh();
                      }}
                               className="danger"
                               data-testid={`pd-del-${p.id}`}>
                        Remover
                      </button>
                    </div>
                  )}
                </div>
              </article>
            ))}
          </div>
          <div className="pd-dots-row">
            {promotions.map((_, i) => (
              <button key={i}
                       className={`pd-dot ${i === carouselIdx
                         ? "active" : ""}`}
                       onClick={() => setCarouselIdx(i)}
                       aria-label={`Promoção ${i + 1}`} />
            ))}
          </div>
        </section>
      ) : isOwner ? (
        <div className="pd-empty-owner" data-testid="pd-empty-owner">
          <div style={{ fontSize: 56, marginBottom: 10 }}></div>
          <h3>Você ainda não publicou promoções</h3>
          <p>Cadastre sua primeira promoção pra aparecer na vitrine
            Ligo e atrair clientes.</p>
          <button onClick={() => setShowAddItem(true)}
                   className="pd-owner-add"
                   data-testid="pd-empty-add"
                   style={{ marginTop: 10 }}>
            ＋ Cadastrar primeira promoção
          </button>
        </div>
      ) : null}

      {/* Clientes beneficiados */}
      <section className="pd-section">
        <h2 className="pd-section-title">
          <span className="ic"></span> Clientes Ligo que aproveitaram
        </h2>
        {recent_redemptions.length === 0 ? (
          <p className="pd-empty">
            Seja o primeiro a usar uma promoção deste parceiro!
          </p>
        ) : (
          <div className="pd-clients">
            {recent_redemptions.map((r) => (
              <div key={r.id} className="pd-client-chip"
                    data-testid={`pd-client-${r.id}`}>
                <div className="pd-client-avatar">
                  {(r.client_name[0] || "C").toUpperCase()}
                </div>
                <div>
                  <b>{r.client_name}</b>
                  <span>{r.promotion_title}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Avaliações */}
      {ratings.length > 0 && (
        <section className="pd-section">
          <h2 className="pd-section-title">
            <span className="ic">⭐</span> O que estão falando
          </h2>
          <div className="pd-ratings">
            {ratings.slice(0, 8).map((r, i) => (
              <div key={i} className="pd-rating-card">
                <div className="pd-rating-head">
                  <Stars value={r.stars} small />
                  <span className="pd-rating-name">{r.client_name}</span>
                </div>
                {r.comment && <p>“{r.comment}”</p>}
                <small>
                  {r.promotion_title} ·{" "}
                  {new Date(r.created_at).toLocaleDateString("pt-BR")}
                </small>
              </div>
            ))}
          </div>
        </section>
      )}

      {partner.description && (
        <section className="pd-section">
          <h2 className="pd-section-title">
            <span className="ic">ℹ️</span> Sobre
          </h2>
          <p className="pd-about">{partner.description}</p>
        </section>
      )}

      <footer className="pd-footer">
        © 2026 <b>{partner.name}</b> · Parceiro <b>Ligo Vantagens</b>
      </footer>

      {showScan && (
        <ScannerOverlay partner={partner} promotions={promotions}
                          partnerToken={partnerToken}
                          onResult={(r) => {
                            setScanResult(r); setShowScan(false);
                            refresh();
                          }}
                          onClose={() => setShowScan(false)} />
      )}
      {scanResult && (
        <ResultOverlay r={scanResult}
                         onClose={() => setScanResult(null)} />
      )}
      {showAddItem && isOwner && (
        <AddItemModal partnerToken={partnerToken}
                        onClose={() => setShowAddItem(false)}
                        onSaved={() => {
                          setShowAddItem(false); refresh();
                        }} />
      )}
      {editingPromo && isOwner && (
        <AddItemModal partnerToken={partnerToken}
                        initial={editingPromo}
                        onClose={() => setEditingPromo(null)}
                        onSaved={() => {
                          setEditingPromo(null); refresh();
                        }} />
      )}
    </div>
  );
}

// ─── Star rendering ──────────────────────────────────────
function Stars({ value = 0, small = false }) {
  const v = Number(value) || 0;
  const full = Math.floor(v);
  const half = (v - full) >= 0.5;
  const stars = [];
  for (let i = 0; i < 5; i++) {
    if (i < full) stars.push("");
    else if (i === full && half) stars.push("⯨");
    else stars.push("");
  }
  return (
    <span className={`pd-stars ${small ? "sm" : ""}`}>
      {stars.map((s, i) => (
        <span key={i}
                style={{ color: s === "" || s === "⯨"
                  ? "#f59e0b" : "rgba(255,255,255,.45)" }}>
          {s === "⯨" ? "" : s}
        </span>
      ))}
    </span>
  );
}

const CAT_EMOJI = {
  Pizzaria: "", "Farmácia": "", Oficina: "",
  Restaurante: "", "Padaria": "", Mercado: "",
  Outros: "",
};

// ─── Scanner overlay ─────────────────────────────────────
function ScannerOverlay({ partner, promotions, partnerToken,
                            onResult, onClose }) {
  const idRef = useRef("pd-qr-" + Math.random().toString(36).slice(2));
  const [msg, setMsg] = useState("Aponte para o QR do cliente Ligo…");
  const [selPromo, setSelPromo] = useState(promotions[0]?.id || "");
  const [scanner, setScanner] = useState(null);

  useEffect(() => {
    const sc = new Html5Qrcode(idRef.current);
    setScanner(sc);
    sc.start({ facingMode: "environment" },
                { fps: 10, qrbox: { width: 280, height: 280 } },
                async (decoded) => {
                  setMsg("✅ QR detectado…");
                  try { await sc.stop(); } catch { /* */ }
                  try {
                    const r = await axios.post(
                      `${API}/parceiro-portal/scan`,
                      { qr_token: decoded, promotion_id: selPromo },
                      { headers: {
                        Authorization: `Bearer ${partnerToken}` } });
                    onResult({ ...r.data, ok: r.data.ok });
                  } catch (ex) {
                    onResult({ ok: false,
                                  reason: ex?.response?.data?.detail
                                    || ex.message });
                  }
                },
                () => {}).catch((e) =>
                  setMsg("Erro câmera: " + e.message));
    return () => {
      try { sc.stop().catch(() => {}); sc.clear(); } catch { /* */ }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selPromo, partnerToken]);

  const close = () => {
    try { scanner?.stop().catch(() => {}); scanner?.clear(); } catch { /* */ }
    onClose();
  };

  return (
    <div className="pd-scan" data-testid="pd-scanner">
      <header>
        <b>Escanear QR Ligo · {partner.name}</b>
        <button onClick={close} data-testid="pd-scan-close">✕</button>
      </header>
      <div style={{ padding: 12, background: "#0f172a" }}>
        <select value={selPromo}
                 onChange={(e) => setSelPromo(e.target.value)}
                 style={{ width: "100%", padding: "11px 14px",
                            borderRadius: 10,
                            background: "rgba(15,23,42,.95)",
                            border: "1px solid rgba(255,255,255,.1)",
                            color: "white", fontSize: 14,
                            fontWeight: 600 }}>
          {promotions.map((p) => (
            <option key={p.id} value={p.id}>{p.title}</option>
          ))}
        </select>
      </div>
      <div className="pd-scan-cam">
        <div id={idRef.current} style={{ width: "100%",
                                             maxWidth: 480,
                                             margin: "0 auto" }} />
        <div className="pd-scan-frame" />
        <div className="pd-scan-msg">{msg}</div>
      </div>
    </div>
  );
}

function ResultOverlay({ r, onClose }) {
  const isOk = !!r.ok;
  return (
    <div className="pd-result-overlay" onClick={onClose}
          data-testid="pd-result">
      <div className={`pd-result ${isOk ? "ok" : "fail"}`}
            onClick={(e) => e.stopPropagation()}>
        <h2>{isOk ? "✅ Promoção aplicada!" : "Não foi possível"}</h2>
        {r.client && <div className="name">{r.client.name}</div>}
        {r.promotion && (
          <div className="why">
            {r.promotion.title} · {r.promotion.offer_summary}
          </div>
        )}
        {!isOk && r.reason && <div className="why">{r.reason}</div>}
        {isOk && r.voucher_code && (
          <div className="voucher">{r.voucher_code}</div>
        )}
        <button onClick={onClose}
                 style={{ padding: "10px 22px",
                            background: isOk ? "#10b981" : "#475569",
                            color: "white", border: 0,
                            borderRadius: 8, fontWeight: 800,
                            cursor: "pointer", marginTop: 14 }}>
          OK
        </button>
      </div>
    </div>
  );
}

function AddItemModal({ partnerToken, onClose, onSaved, initial }) {
  const [f, setF] = useState({
    title: initial?.title || "",
    offer_summary: initial?.offer_summary || "",
    description: initial?.description || "",
    image_url: initial?.image_url || "",
    discount_pct: initial?.discount_pct || 0,
    original_price: initial?.original_price || 0,
    promo_price: initial?.promo_price || 0,
    max_uses_per_client: initial?.max_uses_per_client || 1,
    period: initial?.period || "month",
    terms: initial?.terms || "",
    active: initial?.active ?? true,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [uploading, setUploading] = useState(false);

  const upload = async (file) => {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      setErr("Imagem muito grande (máx 5MB)");
      return;
    }
    setUploading(true); setErr("");
    try {
      const reader = new FileReader();
      reader.onload = async () => {
        try {
          const r = await axios.post(
            `${API}/parceiro-portal/upload-image`,
            { data_url: reader.result },
            { headers: { Authorization: `Bearer ${partnerToken}` } });
          // backend retorna /api/parcerias/uploads/... — concat com BACKEND_URL
          const fullUrl = r.data.url.startsWith("http")
            ? r.data.url : `${BACKEND_URL}${r.data.url}`;
          setF((s) => ({ ...s, image_url: fullUrl }));
        } catch (ex) {
          setErr(ex?.response?.data?.detail || ex.message);
        }
        setUploading(false);
      };
      reader.onerror = () => {
        setErr("Erro ao ler arquivo"); setUploading(false);
      };
      reader.readAsDataURL(file);
    } catch (ex) {
      setErr(ex.message); setUploading(false);
    }
  };

  const save = async () => {
    setBusy(true); setErr("");
    try {
      const body = { ...f,
        discount_pct: Number(f.discount_pct) || 0,
        original_price: Number(f.original_price) || 0,
        promo_price: Number(f.promo_price) || 0,
        max_uses_per_client: Number(f.max_uses_per_client) || 1,
      };
      if (initial?.id) {
        await axios.put(
          `${API}/parceiro-portal/promotions/${initial.id}`, body,
          { headers: { Authorization: `Bearer ${partnerToken}` } });
      } else {
        await axios.post(`${API}/parceiro-portal/promotions`, body,
          { headers: { Authorization: `Bearer ${partnerToken}` } });
      }
      onSaved();
    } catch (ex) {
      setErr(ex?.response?.data?.detail || ex.message);
    }
    setBusy(false);
  };
  return (
    <div className="pd-modal-overlay" onClick={onClose}
          data-testid="pd-add-item-modal">
      <div className="pd-modal" onClick={(e) => e.stopPropagation()}>
        <h3>{initial ? "✏ Editar promoção" : "＋ Nova promoção"}</h3>

        <label style={{ fontSize: 11, color: "#94a3b8",
                          display: "block", marginBottom: 8,
                          letterSpacing: .5 }}>
          Foto da promoção
          <div className="pd-upload-box"
                data-testid="pd-upload-box"
                style={{ marginTop: 6 }}>
            {f.image_url ? (
              <div style={{ position: "relative" }}>
                <img src={f.image_url} alt=""
                      style={{ width: "100%", maxHeight: 200,
                                objectFit: "cover", borderRadius: 10,
                                display: "block" }} />
                <button type="button"
                         onClick={() => setF({ ...f, image_url: "" })}
                         style={{ position: "absolute", top: 6,
                                    right: 6, background: "rgba(0,0,0,.7)",
                                    border: 0, color: "white",
                                    borderRadius: 999, padding: "4px 8px",
                                    fontSize: 11, cursor: "pointer" }}>
                  ✕ Remover
                </button>
              </div>
            ) : (
              <label className="pd-upload-area"
                      style={{ display: "block", padding: 28,
                                 border: "2px dashed rgba(255,255,255,.18)",
                                 borderRadius: 10, textAlign: "center",
                                 cursor: "pointer",
                                 background: "rgba(255,255,255,.02)" }}>
                <input type="file" accept="image/*"
                        onChange={(e) => upload(e.target.files?.[0])}
                        style={{ display: "none" }}
                        data-testid="pd-upload-input" />
                {uploading ? (
                  <span style={{ color: "#fcd34d" }}>Enviando…</span>
                ) : (
                  <>
                    <div style={{ fontSize: 28, marginBottom: 6 }}></div>
                    <div style={{ color: "white", fontWeight: 700,
                                    fontSize: 13 }}>
                      Carregar foto
                    </div>
                    <div style={{ color: "rgba(255,255,255,.4)",
                                    fontSize: 11, marginTop: 3 }}>
                      JPG, PNG ou WEBP até 5MB
                    </div>
                  </>
                )}
              </label>
            )}
          </div>
        </label>

        <Input lbl="Título da promoção *" value={f.title}
                onChange={(v) => setF({ ...f, title: v })}
                testid="pd-add-title" />
        <Input lbl="Resumo (uma frase) *" value={f.offer_summary}
                onChange={(v) => setF({ ...f, offer_summary: v })} />
        <label style={{ fontSize: 11, color: "#94a3b8",
                         display: "block", marginBottom: 8 }}>
          Descrição completa
          <textarea value={f.description}
                      onChange={(e) =>
                        setF({ ...f, description: e.target.value })}
                      placeholder="Conte detalhes da promoção…"
                      maxLength={400}
                      className="pd-modal-input"
                      style={{ minHeight: 70 }} />
        </label>
        <div className="pd-modal-row">
          <Input lbl="Preço normal" type="number" step="0.01"
                  value={f.original_price}
                  onChange={(v) => setF({ ...f, original_price: v })} />
          <Input lbl="Preço promo" type="number" step="0.01"
                  value={f.promo_price}
                  onChange={(v) => setF({ ...f, promo_price: v })} />
          <Input lbl="% desconto" type="number" min="0" max="100"
                  value={f.discount_pct}
                  onChange={(v) => setF({ ...f, discount_pct: v })}
                  testid="pd-add-discount" />
        </div>
        <div className="pd-modal-row">
          <Input lbl="Limite por cliente" type="number"
                  value={f.max_uses_per_client}
                  onChange={(v) =>
                    setF({ ...f, max_uses_per_client: v })} />
          <label style={{ fontSize: 11, color: "#94a3b8" }}>
            Período
            <select value={f.period}
                     onChange={(e) =>
                       setF({ ...f, period: e.target.value })}
                     className="pd-modal-input">
              <option value="day">Por dia</option>
              <option value="week">Por semana</option>
              <option value="month">Por mês</option>
              <option value="year">Por ano</option>
              <option value="campaign">Total na campanha</option>
              <option value="none">Sem limite</option>
            </select>
          </label>
        </div>
        <label style={{ fontSize: 11, color: "#94a3b8" }}>
          Termos
          <textarea value={f.terms}
                      onChange={(e) =>
                        setF({ ...f, terms: e.target.value })}
                      className="pd-modal-input"
                      style={{ minHeight: 50 }} />
        </label>
        {err && (
          <div style={{ background: "rgba(239,68,68,.15)",
                          color: "#fca5a5",
                          padding: "10px 12px", borderRadius: 6,
                          fontSize: 12, marginTop: 8 }}
                data-testid="pd-add-err">{err}</div>
        )}
        <div style={{ display: "flex", gap: 8,
                        justifyContent: "flex-end",
                        marginTop: 14 }}>
          <button onClick={onClose}
                   style={{ padding: "9px 18px", background: "transparent",
                              color: "white",
                              border: "1px solid rgba(255,255,255,.2)",
                              borderRadius: 8, cursor: "pointer" }}>
            Cancelar
          </button>
          <button onClick={save} disabled={busy || uploading}
                   data-testid="pd-add-save"
                   style={{ padding: "9px 18px",
                              background: "linear-gradient(135deg,#6b1fb1,#581a8f)",
                              color: "white", border: 0,
                              borderRadius: 8,
                              fontWeight: 800, cursor: "pointer" }}>
            {busy ? "Salvando…" : initial ? "Salvar" : "Publicar"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Input({ lbl, value, onChange, type = "text", step,
                   min, max, testid }) {
  return (
    <label style={{ fontSize: 11, color: "#94a3b8",
                     display: "block", marginBottom: 8,
                     letterSpacing: .5 }}>
      {lbl}
      <input type={type} step={step} min={min} max={max}
              value={value ?? ""}
              onChange={(e) => onChange(e.target.value)}
              className="pd-modal-input"
              data-testid={testid} />
    </label>
  );
}
