/* ClientQRModal — Modal com o QR Code de identidade do cliente.
 *
 * iter228 — pedido do usuário: "no canto do perfil, 3 pontinhos com
 * QR Code slave com nome completo, CPF, plano, ativo/não ativo".
 * iter237 — agora o QR é CRIPTOGRAFADO via Fernet (server-side).
 * O QR carrega APENAS um token opaco curto (LIGO2:...). Só o backend
 * Ligo consegue descriptografar pra ver CPF/nome. Token expira em 90s
 * e é renovado automaticamente a cada 60s.
 *
 * Mantemos o tema dark/purpura do Hub.
 */
import React, { useEffect, useState } from "react";
import axios from "axios";
import { motion, AnimatePresence } from "framer-motion";
import { QRCodeSVG } from "qrcode.react";

import { COLORS, FONT_DISPLAY, titleCase, maskCPF } from "@/cliente/ligo-theme";

const BACKEND = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND}/api/cliente-portal`;

export default function ClientQRModal({ open, onClose, me }) {
  const [qrValue, setQrValue] = useState("");
  const [loading, setLoading] = useState(true);

  const cpfRaw = me?.cpf || me?.document || me?.cpf_cnpj || "";
  const status = me?.status || me?.subscriber_status || "ativo";
  const isActive = String(status).toLowerCase().startsWith("ativ");

  // Busca um token criptografado novo a cada 60s enquanto o modal estiver aberto
  useEffect(() => {
    if (!open || !me) return;
    let alive = true;
    const fetchToken = async () => {
      try {
        const tk = localStorage.getItem("client_portal_token")
          || localStorage.getItem("ligo_cliente_token")
          || localStorage.getItem("ligo_indica_token");
        const r = await axios.get(`${API}/qr-token`, {
          headers: { Authorization: `Bearer ${tk}` },
        });
        if (alive) {
          setQrValue(r.data.qr_payload || "");
          setLoading(false);
        }
      } catch {
        // fallback: gera local sem encriptação (legado, só nome)
        if (alive) {
          setQrValue(JSON.stringify({
            v: 1, name: titleCase(me.name || ""),
            cpf: cpfRaw, sid: me.id || null,
          }));
          setLoading(false);
        }
      }
    };
    fetchToken();
    const iv = setInterval(fetchToken, 60 * 1000);
    return () => { alive = false; clearInterval(iv); };
  }, [open, me, cpfRaw]);

  if (!me) return null;

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          data-testid="client-qr-modal"
          onClick={onClose}
          style={{
            position: "fixed", inset: 0, zIndex: 999,
            background: "rgba(10,4,30,.82)",
            backdropFilter: "blur(8px)",
            display: "flex", alignItems: "center", justifyContent: "center",
            padding: 18,
            fontFamily: "'Inter', system-ui, sans-serif",
          }}>
          <motion.div
            initial={{ scale: .9, opacity: 0, y: 24 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: .9, opacity: 0, y: 24 }}
            transition={{ duration: .35, ease: [0.22, 1, 0.36, 1] }}
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "100%", maxWidth: 380,
              borderRadius: 28, padding: "24px 22px 22px",
              background: "linear-gradient(135deg, #4C1D95 0%, #2e0b70 60%, #1a0840 100%)",
              border: "1px solid rgba(255,255,255,.12)",
              color: "white", position: "relative", overflow: "hidden",
              boxShadow: "0 30px 70px rgba(0,0,0,.55)",
            }}>
            {/* Decor aurora */}
            <div aria-hidden style={{
              position: "absolute", inset: -40, pointerEvents: "none",
              background: `radial-gradient(circle at 85% 0%, rgba(244,114,182,.22), transparent 50%),
                            radial-gradient(circle at 0% 100%, rgba(255,106,26,.18), transparent 55%)`,
            }} />

            <div style={{ position: "relative", zIndex: 2 }}>
              <div style={{ display: "flex", justifyContent: "space-between",
                              alignItems: "center", marginBottom: 14 }}>
                <span style={{
                  display: "inline-flex", padding: "5px 12px", borderRadius: 999,
                  background: "rgba(255,255,255,.14)",
                  border: "1px solid rgba(255,255,255,.22)",
                  fontSize: 10, fontWeight: 800, letterSpacing: 1.8,
                  color: isActive ? "#86efac" : "#fca5a5",
                  textTransform: "uppercase",
                }}>● {isActive ? "Cliente Ligo ATIVO" : "Cliente INATIVO"}</span>
                <button onClick={onClose} type="button"
                  data-testid="client-qr-close"
                  style={{
                    width: 32, height: 32, borderRadius: "50%",
                    background: "rgba(255,255,255,.12)",
                    border: "1px solid rgba(255,255,255,.18)",
                    color: "white", fontSize: 18, fontWeight: 700,
                    cursor: "pointer", display: "flex",
                    alignItems: "center", justifyContent: "center",
                  }}>×</button>
              </div>

              <h2 style={{
                margin: "4px 0 6px", fontFamily: FONT_DISPLAY,
                fontSize: 26, fontWeight: 900, letterSpacing: "-.02em",
                lineHeight: 1.1,
              }}>Meu QR Code</h2>
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.45,
                            color: "rgba(255,255,255,.78)", fontWeight: 500 }}>
                Mostre para o parceiro escanear no caixa e validar suas
                vantagens Ligo.
              </p>

              {/* QR em card branco pra contraste do scanner */}
              <div data-testid="client-qr-canvas" style={{
                marginTop: 18, padding: 18, borderRadius: 22,
                background: "white", display: "flex", justifyContent: "center",
                alignItems: "center", minHeight: 256,
                boxShadow: "0 14px 36px rgba(0,0,0,.35)",
              }}>
                {loading || !qrValue ? (
                  <div style={{
                    width: 220, height: 220, display: "grid",
                    placeItems: "center", color: "#6B2BFB",
                    fontSize: 12, fontWeight: 700,
                    animation: "pulse 1.4s ease-in-out infinite",
                  }}>Gerando QR seguro…</div>
                ) : (
                  <QRCodeSVG value={qrValue} size={220} level="M"
                    bgColor="#ffffff" fgColor={COLORS.purpleDeep || "#1a0840"}
                    includeMargin={false} />
                )}
              </div>
              <div style={{ marginTop: 8, fontSize: 10.5,
                color: "rgba(255,255,255,.55)", letterSpacing: 1.2,
                textTransform: "uppercase", fontWeight: 700 }}>
                QR criptografado · renova a cada 60s
              </div>

              {/* Dados do cliente */}
              <div style={{ marginTop: 18, display: "grid", gap: 10 }}>
                <Row label="Nome" value={titleCase(me.name)} />
                <Row label="CPF" value={maskCPF(cpfRaw)} />
                {me.plan_name && <Row label="Plano" value={me.plan_name} />}
                <Row label="Tempo de cliente"
                  value={
                    <span data-testid="client-qr-tenure"
                          style={{ color: "#fde68a", fontWeight: 800 }}>
                      {(() => {
                        const d = me.installation_date
                          || me.activation_date || me.created_at;
                        const t = formatTenure(d);
                        // iter215 — pra clientes com 5+ anos (fidelidade)
                        try {
                          const years = (new Date() - new Date(d))
                            / (365.25 * 86400000);
                          if (years >= 5) return `${t}`;
                        } catch { /* ignore */ }
                        return t;
                      })()}
                    </span>
                  } />
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function formatTenure(installDateStr) {
  if (!installDateStr) return "—";
  try {
    const start = new Date(installDateStr);
    if (isNaN(start.getTime())) return "—";
    const now = new Date();
    let years = now.getFullYear() - start.getFullYear();
    let months = now.getMonth() - start.getMonth();
    if (now.getDate() < start.getDate()) months -= 1;
    if (months < 0) { years -= 1; months += 12; }
    if (years <= 0 && months <= 0) {
      const days = Math.max(0, Math.floor((now - start) / 86400000));
      return `${days} dia${days === 1 ? "" : "s"}`;
    }
    if (years <= 0) return `${months} ${months === 1 ? "mês" : "meses"}`;
    if (months === 0) return `${years} ${years === 1 ? "ano" : "anos"}`;
    return `${years} ${years === 1 ? "ano" : "anos"} e ${months} ${months === 1 ? "mês" : "meses"}`;
  } catch {
    return "—";
  }
}

function Row({ label, value }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "center",
      padding: "9px 12px", borderRadius: 12,
      background: "rgba(255,255,255,.07)",
      border: "1px solid rgba(255,255,255,.10)",
      fontSize: 13,
    }}>
      <span style={{ color: "rgba(255,255,255,.65)", fontWeight: 700,
                       letterSpacing: 1.4, fontSize: 10.5,
                       textTransform: "uppercase" }}>{label}</span>
      <span style={{ color: "white", fontWeight: 700,
                       maxWidth: "60%", textAlign: "right",
                       overflow: "hidden", textOverflow: "ellipsis",
                       whiteSpace: "nowrap" }}>{value}</span>
    </div>
  );
}
