import React, { useEffect, useState } from "react";
import { api } from "@/api";

const ACCENT = "#10b981";
const BG_DARK = "#0a1322";

/**
 * BillingBanner — banner discreto exibido no topo do app quando:
 *  - status_effective === "trialing" → mostra "Trial: X dias restantes" + botão Assinar
 *  - status_effective === "past_due" → vermelho, exige pagamento
 *  - status_effective === "active" → mostra "Ativo até DD/MM/YYYY" pequeno
 */
export function BillingBanner() {
  const [co, setCo] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    api.saasMe().then((c) => alive && setCo(c)).catch(() => {});
    const t = setInterval(() => api.saasMe().then((c) => alive && setCo(c)).catch(() => {}), 60000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  async function startCheckout() {
    setErr(""); setBusy(true);
    try {
      const origin = window.location.origin;
      const r = await api.saasCheckout(origin);
      window.location.href = r.url;
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
      setBusy(false);
    }
  }

  if (!co) return null;
  if (co.is_super_admin) {
    return null;
  }
  const eff = co.status_effective;

  // Plano FREE: banner especial sempre visível com CTA pra Pro
  if (co.is_free) {
    return (
      <div data-testid="billing-banner-free" style={{
        background: "linear-gradient(90deg,#1e293b,#334155)",
        color: "white", padding: "10px 16px", borderRadius: 12, fontSize: 12,
        display: "flex", justifyContent: "space-between", alignItems: "center",
        gap: 12, flexWrap: "wrap", marginBottom: 12, fontWeight: 600,
        border: "1px solid rgba(16,185,129,.2)",
      }}>
        <span>
          ⚡ Você está no <strong>{co.plan_name}</strong> · {co.collaborators_count}/{co.max_collaborators || 3} colaboradores ·
          <span style={{ color: "#94a3b8", marginLeft: 6 }}>upgrade pro Pro = mais 22 vagas + IA + mapa ao vivo</span>
        </span>
        <button
          onClick={startCheckout}
          disabled={busy}
          data-testid="billing-upgrade-btn"
          style={{
            background: "#10b981", color: "#050b16",
            border: 0, padding: "6px 14px", borderRadius: 8, fontSize: 11,
            fontWeight: 800, cursor: busy ? "wait" : "pointer",
          }}
        >{busy ? "..." : "Upgrade pro Pro"}</button>
        {err && <div style={{ width: "100%", marginTop: 4, fontSize: 11, color: "#fecaca" }}>⚠ {err}</div>}
      </div>
    );
  }

  if (eff === "active") {
    return (
      <div data-testid="billing-banner-active" style={{
        background: "rgba(16,185,129,.08)", border: "1px solid rgba(16,185,129,.25)",
        color: "#34d399", padding: "8px 16px", borderRadius: 12, fontSize: 12,
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginBottom: 12, fontWeight: 600,
      }}>
        <span>✓ {co.plan_name} ativa{co.days_left != null ? ` · renova em ${co.days_left} dia(s)` : ""}</span>
        <button
          onClick={startCheckout}
          disabled={busy}
          data-testid="billing-renew-btn"
          style={{
            background: "transparent", border: "1px solid rgba(16,185,129,.4)",
            color: "#34d399", padding: "4px 12px", borderRadius: 8, fontSize: 11, cursor: "pointer",
            fontWeight: 700,
          }}
        >Renovar agora</button>
      </div>
    );
  }
  const isTrial = eff === "trialing";
  const isPastDue = eff === "past_due";
  return (
    <div data-testid={isPastDue ? "billing-banner-past-due" : "billing-banner-trial"} style={{
      background: isPastDue ? "linear-gradient(90deg,#7f1d1d,#991b1b)" : "linear-gradient(90deg,#0f766e,#0d9488)",
      color: "white", padding: "12px 18px", borderRadius: 14,
      display: "flex", justifyContent: "space-between", alignItems: "center",
      gap: 16, flexWrap: "wrap", marginBottom: 14,
      boxShadow: `0 10px 26px ${isPastDue ? "rgba(127,29,29,.32)" : "rgba(15,118,110,.32)"}`,
    }}>
      <div>
        <strong style={{ fontSize: 14 }}>
          {isPastDue ? "🚨 Sua assinatura expirou" : `⏳ Trial: ${co.days_left ?? 0} dia(s) restantes`}
        </strong>
        <div style={{ fontSize: 12, opacity: 0.9, marginTop: 2 }}>
          {isPastDue
            ? "Para continuar usando, ative sua assinatura mensal."
            : `Assine o ${co.plan_name} (R$ ${(co.plan_price_brl || 99).toFixed(0)}/mês) para garantir o serviço.`}
        </div>
        {err && <div style={{ marginTop: 6, fontSize: 11, color: "#fecaca" }}>⚠ {err}</div>}
      </div>
      <button
        onClick={startCheckout}
        disabled={busy}
        data-testid="billing-subscribe-btn"
        style={{
          background: "white", color: isPastDue ? "#991b1b" : "#0f766e",
          border: 0, padding: "10px 22px", borderRadius: 12,
          fontSize: 13, fontWeight: 800, cursor: busy ? "wait" : "pointer",
          opacity: busy ? 0.7 : 1,
        }}
      >{busy ? "Abrindo..." : "Assinar agora →"}</button>
    </div>
  );
}

/**
 * BillingSuccessPage — mostrada após retornar do Stripe checkout.
 * Faz polling no /saas/billing/status/:session_id até "paid" ou timeout.
 */
export function BillingSuccessPage({ sessionId, onDone }) {
  const [status, setStatus] = useState("checking");
  const [tries, setTries] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!sessionId) { setStatus("error"); setError("Session ID ausente"); return; }
    let cancelled = false;
    let attempts = 0;
    async function poll() {
      attempts += 1;
      setTries(attempts);
      try {
        const r = await api.saasCheckoutStatus(sessionId);
        if (cancelled) return;
        if (r.payment_status === "paid") {
          setStatus("paid");
          return;
        }
        if (r.status === "expired") {
          setStatus("expired");
          return;
        }
        if (attempts >= 8) {
          setStatus("timeout");
          return;
        }
        setTimeout(poll, 2500);
      } catch (e) {
        if (cancelled) return;
        setError(e?.response?.data?.detail || e.message);
        if (attempts < 5) setTimeout(poll, 3000);
        else setStatus("error");
      }
    }
    poll();
    return () => { cancelled = true; };
  }, [sessionId]);

  return (
    <div data-testid="billing-success-page" style={{
      minHeight: "100vh",
      background: `radial-gradient(ellipse 80% 60% at 50% -20%, rgba(16,185,129,.15) 0%, ${BG_DARK} 55%, #050b16 100%)`,
      color: "#e2e8f0", fontFamily: "'Inter', system-ui, sans-serif",
      display: "grid", placeItems: "center", padding: 22,
    }}>
      <div style={{
        maxWidth: 460, width: "100%", textAlign: "center",
        background: "rgba(255,255,255,.03)", border: "1px solid rgba(255,255,255,.08)",
        borderRadius: 22, padding: "40px 30px",
      }}>
        {status === "checking" && (
          <>
            <div style={{ fontSize: 48, marginBottom: 14 }}>⏳</div>
            <h2 style={{ color: "white", margin: 0 }}>Confirmando pagamento...</h2>
            <p style={{ color: "#94a3b8", marginTop: 10, fontSize: 14 }}>Tentativa {tries}/8 — não feche esta página.</p>
          </>
        )}
        {status === "paid" && (
          <>
            <div style={{ fontSize: 56, marginBottom: 14 }}>🎉</div>
            <h2 style={{ color: "white", margin: 0 }}>Pagamento confirmado!</h2>
            <p style={{ color: "#94a3b8", marginTop: 10, fontSize: 14 }}>
              Sua assinatura PontoIA Pro está ativa por 30 dias.
            </p>
            <button
              onClick={onDone}
              data-testid="billing-success-continue"
              style={{
                marginTop: 26, padding: "13px 24px", borderRadius: 12,
                background: ACCENT, color: "#050b16", border: 0, fontSize: 14,
                fontWeight: 800, cursor: "pointer",
                boxShadow: "0 12px 28px rgba(16,185,129,.35)",
              }}
            >Ir para o painel →</button>
          </>
        )}
        {status === "expired" && (
          <>
            <div style={{ fontSize: 48 }}>⌛</div>
            <h2 style={{ color: "white", margin: 0 }}>Sessão expirou</h2>
            <p style={{ color: "#94a3b8", marginTop: 10, fontSize: 14 }}>O pagamento não foi concluído a tempo. Tente novamente.</p>
            <button onClick={onDone} style={{ marginTop: 22, padding: "12px 22px", borderRadius: 12, background: "white", color: "#0a1322", border: 0, fontWeight: 700, cursor: "pointer" }}>Voltar</button>
          </>
        )}
        {status === "timeout" && (
          <>
            <div style={{ fontSize: 48 }}>⏱️</div>
            <h2 style={{ color: "white", margin: 0 }}>Ainda processando...</h2>
            <p style={{ color: "#94a3b8", marginTop: 10, fontSize: 14 }}>O pagamento pode levar alguns minutos. Volte ao painel — atualizamos automaticamente.</p>
            <button onClick={onDone} style={{ marginTop: 22, padding: "12px 22px", borderRadius: 12, background: ACCENT, color: "#050b16", border: 0, fontWeight: 800, cursor: "pointer" }}>Voltar ao painel</button>
          </>
        )}
        {status === "error" && (
          <>
            <div style={{ fontSize: 48 }}>⚠️</div>
            <h2 style={{ color: "white", margin: 0 }}>Erro ao verificar</h2>
            <p style={{ color: "#fca5a5", marginTop: 10, fontSize: 13 }}>{error}</p>
            <button onClick={onDone} style={{ marginTop: 22, padding: "12px 22px", borderRadius: 12, background: "white", color: "#0a1322", border: 0, fontWeight: 700, cursor: "pointer" }}>Voltar</button>
          </>
        )}
      </div>
    </div>
  );
}

export function BillingCancelPage({ onDone }) {
  return (
    <div data-testid="billing-cancel-page" style={{
      minHeight: "100vh",
      background: `radial-gradient(ellipse 80% 60% at 50% -20%, rgba(239,68,68,.08) 0%, ${BG_DARK} 55%, #050b16 100%)`,
      color: "#e2e8f0", fontFamily: "'Inter', system-ui, sans-serif",
      display: "grid", placeItems: "center", padding: 22,
    }}>
      <div style={{
        maxWidth: 440, width: "100%", textAlign: "center",
        background: "rgba(255,255,255,.03)", border: "1px solid rgba(255,255,255,.08)",
        borderRadius: 22, padding: "40px 30px",
      }}>
        <div style={{ fontSize: 48, marginBottom: 12 }}>👋</div>
        <h2 style={{ color: "white", margin: 0 }}>Pagamento cancelado</h2>
        <p style={{ color: "#94a3b8", marginTop: 10, fontSize: 14 }}>Tudo bem, seu trial continua. Você pode assinar a qualquer momento pelo painel.</p>
        <button onClick={onDone} style={{ marginTop: 22, padding: "13px 22px", borderRadius: 12, background: ACCENT, color: "#050b16", border: 0, fontWeight: 800, cursor: "pointer" }}>Voltar ao painel</button>
      </div>
    </div>
  );
}
