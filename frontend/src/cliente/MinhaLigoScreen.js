/* MinhaLigoScreen — área de autoatendimento do cliente.
 *
 * Visual replicando o screenshot #1: pill MINHA LIGO (laranja dot) +
 * "Olá, Nome!" (Nome em laranja) + subtitle "Você está com o Ligo X Giga"
 * + badge verde Ativo + sub-cards DOCUMENTO + TELEFONE.
 *
 * Conteúdo mínimo (MVP):
 *   - Header gradient + Voltar / Sair
 *   - Saudação grande no estilo screenshot #1
 *   - Sub-cards DOCUMENTO + TELEFONE (sem 2ª via real ainda — placeholder)
 *   - Próxima fatura (placeholder de "tudo em dia")
 *   - Card "Fale com a gente" (CTA WhatsApp grande)
 */
import React from "react";
import { motion } from "framer-motion";
import { MessageCircle } from "lucide-react";

import { COLORS, FONT_DISPLAY, maskCPF, titleCase } from "@/cliente/ligo-theme";
import {
  Shell, HeaderHero, WhiteCard, OrangeCTA, PillBadge,
} from "@/cliente/components";

export default function MinhaLigoScreen({ me, onBack, onLogout }) {
  const firstName = titleCase((me?.name || "").split(" ")[0] || "Amigo(a)");
  const cpfFromDoc = me?.cpf || me?.document || me?.cpf_cnpj || "";
  const isActive = (me?.status || "").toUpperCase() === "ATIVO";

  /* WhatsApp suporte default — usa env var ou fallback genérico. */
  const supportPhone = (process.env.REACT_APP_SUPPORT_WHATSAPP
    || "5500000000000").replace(/\D/g, "");
  const supportMsg = `Oi! Sou ${me?.name || "cliente Ligo"} `
    + `(CPF ${maskCPF(cpfFromDoc)}) e preciso de ajuda.`;
  const supportLink = `https://wa.me/${supportPhone}`
    + `?text=${encodeURIComponent(supportMsg)}`;

  return (
    <Shell testid="minha-ligo-screen">
      <HeaderHero
        pillLabel="Minha Ligo"
        greeting="Olá,"
        greetingName={firstName}
        greetingEmoji="!"
        subtitle={me?.plan_name ? <>
          Você está com o{" "}
          <span style={{ color: "#FFB070", fontWeight: 900 }}>
            {me.plan_name}
          </span>.
        </> : "Bem-vindo de volta."}
        onBack={onBack}
        onLogout={onLogout}
        height={300}
      />

      {/* Status + sub-cards */}
      <motion.div
        initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }}
        transition={{ duration: .5, ease: [0.22, 1, 0.36, 1] }}
        data-testid="minha-ligo-status-block"
        style={{ margin: "-50px 16px 0", position: "relative", zIndex: 4 }}>
        <WhiteCard testid="minha-ligo-status-card"
          style={{ padding: 20, marginBottom: 12 }}>
          <PillBadge
            color={isActive ? COLORS.green : "#f59e0b"}
            bg={isActive ? "#DCFCE7" : "#FEF3C7"}
            textColor={isActive ? "#065f46" : "#92400e"}>
            {isActive ? "Ativo" : (me?.status || "Sem status")}
          </PillBadge>

          <div style={{
            marginTop: 14, display: "grid",
            gridTemplateColumns: "1fr 1fr", gap: 10,
          }}>
            <SubCard
              testid="minha-ligo-doc-card"
              icon="🪪"
              label="Documento"
              value={maskCPF(cpfFromDoc) || "—"}
            />
            <SubCard
              testid="minha-ligo-phone-card"
              icon="📱"
              label="Telefone"
              value={formatPhone(me?.phone) || "—"}
            />
          </div>
        </WhiteCard>

        {/* Próxima fatura (placeholder) */}
        <WhiteCard testid="minha-ligo-invoice-card"
          style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 1.6,
            textTransform: "uppercase", color: COLORS.orange,
            marginBottom: 8 }}>
            🧾 Próxima fatura
          </div>
          <div style={{
            display: "flex", alignItems: "center",
            justifyContent: "space-between", gap: 12,
            padding: "14px 14px",
            background: "linear-gradient(135deg, #ECFDF5, #D1FAE5)",
            border: "1px solid #86efac",
            borderRadius: 14,
          }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700,
                color: "#065f46" }}>
                Tudo em dia ✨
              </div>
              <div style={{ fontSize: 12, color: "#047857", marginTop: 2,
                fontWeight: 500 }}>
                Em breve você verá seus boletos e 2ª via aqui.
              </div>
            </div>
            <span style={{ fontSize: 30 }}>🎯</span>
          </div>
        </WhiteCard>

        {/* Suporte */}
        <WhiteCard testid="minha-ligo-support-card">
          <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 1.6,
            textTransform: "uppercase", color: COLORS.orange,
            marginBottom: 8 }}>
            💬 Precisa de ajuda?
          </div>
          <p style={{ fontSize: 14, color: COLORS.slate700,
            lineHeight: 1.55, marginTop: 0, marginBottom: 14 }}>
            Nossa equipe responde rapidinho no WhatsApp.
            Internet caiu, mudou de endereço, quer trocar de plano?
            Fala com a gente.
          </p>
          <a href={supportLink} target="_blank" rel="noreferrer"
            data-testid="minha-ligo-whatsapp-btn"
            style={{ textDecoration: "none", display: "block" }}>
            <OrangeCTA testid="minha-ligo-whatsapp-cta"
              style={{
                background: "linear-gradient(135deg, #25D366, #128C7E)",
                boxShadow: "0 16px 36px rgba(37,211,102,.45)",
              }}>
              <MessageCircle size={18} /> Chamar no WhatsApp
            </OrangeCTA>
          </a>
        </WhiteCard>
      </motion.div>

      <p style={{
        margin: "26px 22px 0", textAlign: "center",
        fontSize: 12, fontWeight: 600, color: COLORS.slate500,
      }}>
        Mais funcionalidades (boletos, troca de Wi-Fi, abrir chamado)
        chegam em breve.
      </p>
    </Shell>
  );
}

/* ──────────────── Helpers ──────────────── */
function SubCard({ icon, label, value, testid }) {
  return (
    <div data-testid={testid} style={{
      background: "linear-gradient(135deg, #F4F1FF, #ECE4FF)",
      border: "1px solid #DCCFFF", borderRadius: 16,
      padding: "14px 14px", textAlign: "center",
    }}>
      <div style={{ fontSize: 28, lineHeight: 1 }}>{icon}</div>
      <div style={{
        marginTop: 6, fontSize: 10.5, fontWeight: 800,
        letterSpacing: 1.5, textTransform: "uppercase",
        color: COLORS.purpleBase,
      }}>{label}</div>
      <div style={{
        marginTop: 4, fontSize: 14, fontWeight: 800,
        color: COLORS.slate900, fontFamily: FONT_DISPLAY,
        letterSpacing: .3, wordBreak: "break-all",
      }}>{value}</div>
    </div>
  );
}

function formatPhone(raw) {
  if (!raw) return "";
  const d = String(raw).replace(/\D/g, "");
  if (d.length === 13) {
    return `+${d.slice(0, 2)} (${d.slice(2, 4)}) ${d.slice(4, 9)}-${d.slice(9)}`;
  }
  if (d.length === 11) {
    return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  }
  if (d.length === 10) {
    return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  }
  return raw;
}
