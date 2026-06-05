/* WifiCaptivePortal — Portal cativo público em `/wifi/{slug}`.
 *
 * Visitante chega na rede WiFi → roteador (Mikrotik/UniFi) redireciona pra cá
 * → preenche dados (validados conforme `require_*` do venue) → recebe
 * release_token que o roteador valida em /api/wifi-hotspot/public/session/{token}/status
 * pra liberar a internet.
 *
 * Layout mobile-first com branding do venue.
 */
import React, { useEffect, useState } from "react";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api/wifi-hotspot`;

export default function WifiCaptivePortal() {
  const slug = window.location.pathname.replace(/^\/wifi\//, "").split("/")[0];
  const [venue, setVenue] = useState(null);
  const [campaign, setCampaign] = useState(null);
  const [err, setErr] = useState("");
  const [form, setForm] = useState({ name: "", phone: "", email: "", cpf: "" });
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);

  useEffect(() => {
    axios.get(`${API}/public/venue/${slug}`)
      .then((r) => { setVenue(r.data.venue); setCampaign(r.data.campaign); })
      .catch((e) => setErr(e?.response?.data?.detail || "Espaço não encontrado."));
  }, [slug]);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const r = await axios.post(`${API}/public/venue/${slug}/connect`, {
        name: form.name,
        phone: form.phone || null,
        email: form.email || null,
        cpf: form.cpf || null,
        ad_id: campaign?.id || null,
      });
      setDone(r.data);
      // Se requer WhatsApp, abre wa.me imediatamente (mesma aba pra não
      // perder o contexto do roteador) — depois polling em status.
      if (r.data.requires_whatsapp && r.data.whatsapp_url) {
        // Pequeno delay pra UI renderizar a tela de "aguardando" primeiro
        setTimeout(() => {
          window.location.href = r.data.whatsapp_url;
        }, 600);
      }
    } catch (ex) {
      setErr(ex?.response?.data?.detail || "Erro ao conectar.");
    } finally { setBusy(false); }
  };

  /* Polling em /session/{token}/status quando está pending_whatsapp */
  useEffect(() => {
    if (!done || !done.requires_whatsapp) return;
    const token = done.release_token;
    let stop = false;
    const tick = async () => {
      if (stop) return;
      try {
        const r = await axios.get(`${API}/public/session/${token}/status`);
        if (r.data.authorized) {
          setDone((d) => ({ ...d, status: "active" }));
          return;
        }
      } catch { /* ignore */ }
      setTimeout(tick, 4000);
    };
    tick();
    return () => { stop = true; };
  }, [done]);

  const onCampaignClick = async () => {
    if (!campaign) return;
    try {
      await axios.post(`${API}/public/campaign/${campaign.id}/click`);
    } catch { /* ignore */ }
    if (campaign.cta_url) window.open(campaign.cta_url, "_blank");
  };

  if (err && !venue) {
    return (
      <Wrap brand={{ color_primary: "#6B2BFB", color_accent: "#FF6A1A" }}>
        <Card>
          <div style={{ textAlign: "center", padding: "30px 0" }}>
            <div style={{ fontSize: 48 }}>📡</div>
            <h2 style={{ color: "#dc2626", marginTop: 12 }}>Ops!</h2>
            <p style={{ color: "#64748b" }}>{err}</p>
          </div>
        </Card>
      </Wrap>
    );
  }
  if (!venue) {
    return <Wrap brand={{ color_primary: "#6B2BFB", color_accent: "#FF6A1A" }}>
      <Loading /></Wrap>;
  }

  if (done) {
    return <Wrap brand={venue.brand}>
      {(done.requires_whatsapp && done.status !== "active")
        ? <PendingWhatsAppCard venue={venue} done={done} />
        : <SuccessCard venue={venue} done={done} />}
    </Wrap>;
  }

  return (
    <Wrap brand={venue.brand}>
      <Card>
        <div style={{ textAlign: "center" }}>
          {venue.brand?.logo_url ? (
            <img src={venue.brand.logo_url} alt={venue.name}
              style={{ height: 56, width: "auto", margin: "0 auto 14px",
                display: "block" }} />
          ) : (
            <img src="/ligo-logo.svg" alt="Ligo Fibra"
              data-testid="captive-card-logo"
              style={{ height: 84, width: "auto",
                margin: "0 auto 16px", display: "block" }} />
          )}
          <div style={{
            display: "inline-block", marginBottom: 10,
            padding: "4px 12px", borderRadius: 999,
            background: "#f1f5f9", fontSize: 11.5,
            color: "#475569", fontWeight: 800,
            letterSpacing: 1.2, textTransform: "uppercase",
          }}>{venue.name}</div>
          <h1 style={{
            fontSize: 24, fontWeight: 900, margin: "0 0 6px",
            letterSpacing: "-.02em", color: "#0f172a", lineHeight: 1.15,
          }}>{venue.brand?.welcome_title || "Bem-vindo ao WiFi grátis"}</h1>
          <p style={{ margin: 0, color: "#64748b", fontSize: 13.5,
            lineHeight: 1.5 }}>
            {venue.brand?.welcome_subtitle || "Conecte-se em poucos segundos"}
          </p>
        </div>

        {campaign && (
          <button onClick={onCampaignClick}
            data-testid="captive-campaign-banner"
            style={{
              marginTop: 20, width: "100%", padding: 0,
              borderRadius: 14, overflow: "hidden", cursor: "pointer",
              border: `2px solid ${venue.brand?.color_accent || "#FF6A1A"}`,
              background: "white", display: "block", textAlign: "left",
            }}>
            {campaign.banner_url && (
              <img src={campaign.banner_url} alt={campaign.title}
                style={{ width: "100%", height: 120, objectFit: "cover" }} />
            )}
            <div style={{ padding: "12px 14px" }}>
              <div style={{ fontWeight: 800, fontSize: 15, color: "#0f172a" }}>
                {campaign.title}
              </div>
              {campaign.subtitle && (
                <div style={{ fontSize: 13, color: "#64748b", marginTop: 4 }}>
                  {campaign.subtitle}
                </div>
              )}
              <div style={{
                marginTop: 10, display: "inline-block",
                padding: "6px 14px", borderRadius: 999,
                background: venue.brand?.color_accent || "#FF6A1A",
                color: "white", fontSize: 12, fontWeight: 800,
              }}>{campaign.cta_label || "Saiba mais"} →</div>
            </div>
          </button>
        )}

        <form onSubmit={submit} style={{ marginTop: 22 }}>
          <Input label="Seu nome *" value={form.name}
            onChange={(v) => setForm({ ...form, name: v })}
            testid="captive-name" required />
          {venue.require_phone && (
            <Input label="Telefone *" type="tel" inputMode="numeric"
              value={form.phone} onChange={(v) => setForm({ ...form, phone: v })}
              testid="captive-phone" required
              placeholder="(11) 98765-4321" />
          )}
          {venue.require_email && (
            <Input label="E-mail *" type="email" value={form.email}
              onChange={(v) => setForm({ ...form, email: v })}
              testid="captive-email" required />
          )}
          {venue.require_cpf && (
            <Input label="CPF *" type="tel" inputMode="numeric"
              value={form.cpf} onChange={(v) => setForm({ ...form, cpf: v })}
              testid="captive-cpf" required />
          )}

          {err && (
            <div style={{
              padding: "10px 12px", borderRadius: 10, marginBottom: 12,
              background: "#fee2e2", color: "#991b1b", fontSize: 13,
              fontWeight: 600,
            }} data-testid="captive-error">{err}</div>
          )}

          <button type="submit" disabled={busy || !form.name}
            data-testid="captive-submit"
            style={{
              width: "100%", padding: "15px 20px", borderRadius: 14,
              border: "none", cursor: busy ? "wait" : "pointer",
              background: `linear-gradient(135deg, ${venue.brand?.color_primary || "#6B2BFB"}, ${venue.brand?.color_accent || "#FF6A1A"})`,
              color: "white", fontWeight: 900, fontSize: 15,
              letterSpacing: .2,
              boxShadow: `0 14px 30px ${(venue.brand?.color_accent || "#FF6A1A")}55`,
              transition: "transform .12s, box-shadow .12s",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.transform = "translateY(-1px)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.transform = "translateY(0)"; }}>
            {busy ? "Conectando…" : "Conectar à internet"}
          </button>
          <p style={{
            marginTop: 14, fontSize: 11, color: "#94a3b8",
            textAlign: "center", lineHeight: 1.5,
          }}>
            Ao clicar você concorda em receber comunicações da
            {" "}<b>Ligo Fibra</b>. Internet liberada por
            {" "}<b>{venue.session_minutes} min</b>.
          </p>
        </form>
      </Card>
      <div style={{ textAlign: "center", marginTop: 18,
        color: "rgba(255,255,255,.8)", fontSize: 11.5, fontWeight: 600,
        letterSpacing: .3 }}>
        Powered by <b style={{ color: "white" }}>Ligo Fibra</b> · Internet de fibra óptica
      </div>
    </Wrap>
  );
}

/* ─────────────────── UI ─────────────────── */
function Wrap({ brand, children }) {
  return (
    <div data-testid="wifi-captive-portal" style={{
      minHeight: "100vh", padding: "30px 16px",
      background: `linear-gradient(140deg, ${brand?.color_primary || "#6B2BFB"} 0%, ${brand?.color_accent || "#FF6A1A"} 130%)`,
      display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: "system-ui, -apple-system, sans-serif",
    }}>
      <div style={{ width: "100%", maxWidth: 440 }}>{children}</div>
    </div>
  );
}

function Card({ children }) {
  return (
    <div style={{
      background: "white", borderRadius: 24, padding: "32px 28px",
      boxShadow: "0 32px 64px rgba(20,8,60,.35)",
      border: "1px solid rgba(255,255,255,.5)",
    }}>{children}</div>
  );
}

function Input({ label, value, onChange, testid, type = "text", ...rest }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ display: "block", fontSize: 11, fontWeight: 800,
        color: "#475569", marginBottom: 6,
        letterSpacing: 1.2, textTransform: "uppercase" }}>{label}</label>
      <input type={type} value={value}
        onChange={(e) => onChange(e.target.value)}
        data-testid={testid}
        style={{
          width: "100%", boxSizing: "border-box",
          padding: "13px 14px", borderRadius: 12,
          border: "1.5px solid #e2e8f0", fontSize: 15,
          outline: "none", background: "#FAFAF7",
          color: "#0f172a", fontFamily: "inherit",
          transition: "border-color .15s, background .15s",
        }}
        onFocus={(e) => {
          e.target.style.borderColor = "#6B2BFB";
          e.target.style.background = "white";
        }}
        onBlur={(e) => {
          e.target.style.borderColor = "#e2e8f0";
          e.target.style.background = "#FAFAF7";
        }}
        {...rest} />
    </div>
  );
}

function Loading() {
  return (
    <Card>
      <div style={{ textAlign: "center", padding: 30, color: "#64748b" }}>
        Carregando…
      </div>
    </Card>
  );
}

function SuccessCard({ venue, done }) {
  return (
    <Card>
      <div data-testid="captive-success" style={{ textAlign: "center" }}>
        <div style={{
          width: 80, height: 80, margin: "0 auto", borderRadius: "50%",
          background: "linear-gradient(135deg, #22c55e, #15803d)",
          display: "grid", placeItems: "center",
          boxShadow: "0 16px 40px rgba(34,197,94,.45)",
        }}>
          <span style={{ fontSize: 40, color: "white" }}>✓</span>
        </div>
        <h1 style={{
          fontSize: 26, fontWeight: 900, marginTop: 18,
          letterSpacing: "-.02em",
        }}>Tudo certo!</h1>
        <p style={{ color: "#64748b", fontSize: 14, marginTop: 8 }}>
          Sua internet foi liberada por <b style={{ color: "#22c55e" }}>
            {done.session_minutes} minutos
          </b>. Bom navegando!
        </p>
        <div style={{
          marginTop: 18, padding: "14px 16px", borderRadius: 14,
          background: "linear-gradient(135deg, #f0fdf4, #dcfce7)",
          border: "1px solid #86efac",
          fontSize: 12, color: "#166534",
        }}>
          💡 <b>Dica:</b> a Ligo Fibra também oferece internet residencial
          de alta velocidade. Cadastre-se na nossa lista de espera!
        </div>
      </div>
    </Card>
  );
}

function PendingWhatsAppCard({ venue, done }) {
  return (
    <Card>
      <div data-testid="captive-pending-whatsapp" style={{ textAlign: "center" }}>
        <div style={{
          width: 80, height: 80, margin: "0 auto", borderRadius: "50%",
          background: "linear-gradient(135deg, #25D366, #128C7E)",
          display: "grid", placeItems: "center",
          boxShadow: "0 16px 40px rgba(37,211,102,.45)",
          animation: "pulse 1.6s ease-in-out infinite",
        }}>
          <span style={{ fontSize: 40, color: "white" }}>💬</span>
        </div>
        <style>{`@keyframes pulse { 0%,100%{transform:scale(1)} 50%{transform:scale(1.06)} }`}</style>
        <h1 style={{
          fontSize: 24, fontWeight: 900, marginTop: 18,
          letterSpacing: "-.02em", color: "#0f172a",
        }}>Falta só 1 passo!</h1>
        <p style={{
          color: "#475569", fontSize: 14, marginTop: 8, lineHeight: 1.55,
        }}>
          Te redirecionamos pro WhatsApp da{" "}
          <b>{venue.name}</b>. <b style={{ color: "#25D366" }}>Envie
          a mensagem</b> que já está pronta e sua internet libera
          em segundos.
        </p>

        {done.unlock_code && (
          <div style={{
            marginTop: 16, padding: "12px 14px", borderRadius: 12,
            background: "#f1f5f9", border: "1px solid #cbd5e1",
          }}>
            <div style={{
              fontSize: 10, fontWeight: 800, letterSpacing: 1.6,
              textTransform: "uppercase", color: "#64748b",
            }}>Seu código</div>
            <div style={{
              fontSize: 24, fontWeight: 900, letterSpacing: 3,
              fontFamily: "monospace", color: "#0f172a", marginTop: 4,
            }}>#{done.unlock_code}</div>
          </div>
        )}

        {done.whatsapp_url && (
          <a href={done.whatsapp_url}
            data-testid="captive-whatsapp-btn"
            style={{
              marginTop: 18, padding: "14px 20px", borderRadius: 14,
              background: "linear-gradient(135deg, #25D366, #128C7E)",
              color: "white", textDecoration: "none",
              fontWeight: 900, fontSize: 15,
              display: "inline-flex", alignItems: "center", gap: 8,
              boxShadow: "0 14px 30px rgba(37,211,102,.45)",
            }}>📲 Abrir WhatsApp agora</a>
        )}

        <div style={{
          marginTop: 22, padding: "10px 14px", borderRadius: 10,
          background: "#fef3c7", border: "1px solid #fcd34d",
          fontSize: 12, color: "#92400e", lineHeight: 1.5,
        }}>
          <b>⏳ Aguardando sua mensagem…</b><br />
          Essa página libera automaticamente assim que recebermos seu
          contato. Não feche o navegador.
        </div>
      </div>
    </Card>
  );
}
