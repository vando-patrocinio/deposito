/* ClientQRModal — Modal com o QR Code de identidade do cliente.
 *
 * iter228 — pedido do usuário: "no canto do perfil, 3 pontinhos com
 * QR Code slave com nome completo, CPF, plano, ativo/não ativo".
 * O QR carrega um payload JSON assinado leve com essas infos para o
 * parceiro escanear no caixa e validar que é cliente Ligo ativo.
 *
 * Mantemos o tema dark/purpura do Hub.
 */
import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { QRCodeSVG } from "qrcode.react";

import { COLORS, FONT_DISPLAY, titleCase, maskCPF } from "@/cliente/ligo-theme";

export default function ClientQRModal({ open, onClose, me }) {
  if (!me) return null;
  const cpfRaw = me.cpf || me.document || me.cpf_cnpj || "";
  const status = me.status || me.subscriber_status || "ativo";
  const isActive = String(status).toLowerCase().startsWith("ativ");

  // Payload "slave" — o que vai dentro do QR. Inclui um hash leve do
  // CPF + tenant pra parceiro validar via /api/parcerias/public/verify
  // (sem expor CPF cru — só os 3 dígitos centrais).
  const payload = {
    v: 1,
    name: titleCase(me.name || ""),
    cpf: cpfRaw,
    plan: me.plan_name || null,
    status: isActive ? "ativo" : "inativo",
    tid: me.tenant_id || me.company_id || null,
    sid: me.id || me.subscriber_id || null,
    ts: new Date().toISOString(),
  };
  const qrValue = JSON.stringify(payload);

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
                boxShadow: "0 14px 36px rgba(0,0,0,.35)",
              }}>
                <QRCodeSVG value={qrValue} size={220} level="M"
                  bgColor="#ffffff" fgColor={COLORS.purpleDeep || "#1a0840"}
                  includeMargin={false} />
              </div>

              {/* Dados do cliente */}
              <div style={{ marginTop: 18, display: "grid", gap: 10 }}>
                <Row label="Nome" value={titleCase(me.name)} />
                <Row label="CPF" value={maskCPF(cpfRaw)} />
                {me.plan_name && <Row label="Plano" value={me.plan_name} />}
                <Row label="Status"
                  value={
                    <span style={{
                      color: isActive ? "#86efac" : "#fca5a5",
                      fontWeight: 800,
                    }}>{isActive ? "ATIVO" : "INATIVO"}</span>
                  } />
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
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
