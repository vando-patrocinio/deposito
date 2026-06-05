/* LoginCPF — Tela de entrada do app /cliente.
 *
 * iter220 — layout reformulado: imagem hero ocupa o viewport inteiro
 *   (full-bleed, inclusive ATRÁS do card de login). O card é incolor
 *   (glass-morphism com backdrop-blur) e tem um "halo" de overlay
 *   escuro suave por trás dele, recortado pro restante da imagem
 *   continuar vívido nas bordas.
 *
 * O endpoint público `/api/referrals/assets/hero.png` serve a imagem
 * (gerada via Gemini Nano Banana — 2 amigos brasileiros comemorando PIX).
 */
import React, { useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";

import {
  COLORS, FONT_DISPLAY,
  ensureSoraFont, formatCPF,
} from "@/cliente/ligo-theme";
import { OrangeCTA, PillBadge } from "@/cliente/components";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const HERO_IMG = `${process.env.REACT_APP_BACKEND_URL}/api/referrals/assets/hero.png`;

export default function LoginCPF({ onLogged }) {
  React.useEffect(() => { ensureSoraFont(); }, []);
  const [cpf, setCpf] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const r = await axios.post(`${API}/customer/login`, { cpf });
      onLogged(r.data.token, r.data.subscriber);
    } catch (ex) {
      setErr(ex?.response?.data?.detail || "Falha no login. Confira seu CPF.");
    } finally { setBusy(false); }
  };

  return (
    <div data-testid="cliente-login-screen" style={{
      minHeight: "100vh", position: "relative", overflow: "hidden",
      fontFamily: "'Inter', system-ui, sans-serif", color: "white",
      // imagem full-bleed — visível inclusive ATRÁS do card.
      backgroundColor: COLORS.purpleDeep,
      backgroundImage: `url('${HERO_IMG}')`,
      backgroundSize: "cover",
      backgroundPosition: "center",
      backgroundAttachment: "fixed",
      // iter222 — card ancorado no canto inferior-esquerdo (desktop).
      // Mobile (<700px): centraliza pra ocupar toda a largura confortável.
      display: "flex",
      alignItems: "flex-end", justifyContent: "flex-start",
      padding: "32px 24px",
    }}>
      {/* Tint global suave — clareado iter227 (era .45/.25/.45). */}
      <div aria-hidden style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        background: `linear-gradient(180deg,
          rgba(46,11,112,.18) 0%,
          rgba(46,11,112,.05) 35%,
          rgba(46,11,112,.18) 100%)`,
      }} />

      {/* Halo radial concentrado atrás do card — clareado iter227. */}
      <div aria-hidden style={{
        position: "absolute",
        left: 24, bottom: 24,
        width: "min(500px, 96vw)", height: "min(700px, 92vh)",
        pointerEvents: "none",
        background: `radial-gradient(ellipse at center,
          rgba(20,8,60,.35) 0%,
          rgba(20,8,60,.20) 45%,
          rgba(20,8,60,.0) 78%)`,
        filter: "blur(10px)",
      }} />

      <style>{`
        @media (max-width: 699px) {
          [data-testid="cliente-login-screen"] {
            align-items: center !important;
            justify-content: center !important;
            padding: 24px 16px !important;
          }
        }
      `}</style>

      {/* CARD incolor — glass com blur. */}
      <motion.div
        initial={{ opacity: 0, y: 24, scale: .96 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: .6, ease: [0.22, 1, 0.36, 1] }}
        data-testid="cliente-login-card"
        style={{
          position: "relative", zIndex: 2,
          width: "100%", maxWidth: 460,
          padding: "34px 28px 30px",
          borderRadius: 28,
          background: "rgba(255,255,255,.04)",
          border: "1px solid rgba(255,255,255,.14)",
          backdropFilter: "blur(22px) saturate(140%)",
          WebkitBackdropFilter: "blur(22px) saturate(140%)",
          boxShadow: "0 30px 70px rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.08)",
        }}>
        {/* Logo */}
        <motion.div
          initial={{ opacity: 0, y: -14, scale: .85 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: .65, ease: [0.22, 1, 0.36, 1] }}
          style={{ display: "flex", justifyContent: "center",
            marginBottom: 14 }}>
          <img src="/ligo-logo-white.svg" alt="Ligo Fibra"
            onError={(e) => { e.target.src = "/ligo-logo-white.png"; }}
            style={{
              height: "clamp(64px, 11vw, 96px)", width: "auto",
              filter: "drop-shadow(0 14px 32px rgba(255,106,26,.45)) drop-shadow(0 4px 14px rgba(0,0,0,.32))",
            }} />
        </motion.div>

        <form onSubmit={submit}
          style={{ display: "flex", flexDirection: "column" }}>
          <motion.div
            initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
            transition={{ delay: .2, duration: .4 }}
            style={{ display: "flex", justifyContent: "center" }}>
            <PillBadge>Indique e Ganhe</PillBadge>
          </motion.div>

          <h1 style={{
            margin: "18px 0 0", fontFamily: FONT_DISPLAY,
            fontSize: "clamp(34px, 7vw, 50px)", fontWeight: 900,
            letterSpacing: "-.025em", lineHeight: 1.0,
            textAlign: "center", color: "white",
            textShadow: "0 6px 30px rgba(0,0,0,.45)",
          }}>
            Bem-vindo<br />
            <span style={{
              background: `linear-gradient(180deg, ${COLORS.orangeSoft}, ${COLORS.orange})`,
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}>de volta.</span>
          </h1>
          <p style={{
            margin: "14px auto 0", maxWidth: 380,
            fontSize: 14.5, fontWeight: 500,
            color: "rgba(255,255,255,.85)", lineHeight: 1.5,
            textAlign: "center",
            textShadow: "0 2px 10px rgba(0,0,0,.35)",
          }}>
            Acompanhe seu plano e ganhe{" "}
            <b style={{ color: "#FFB070" }}>R$ 50 no PIX</b>{" "}
            indicando amigos pra Ligo.
          </p>

          <div style={{ marginTop: 26 }}>
            <label htmlFor="cpf-input" style={{
              display: "block",
              fontSize: 11, fontWeight: 800, letterSpacing: 2.5,
              textTransform: "uppercase", color: "#FFE6D2",
              marginBottom: 10, textShadow: "0 2px 8px rgba(0,0,0,.4)",
            }}>Digite seu CPF</label>
            <input
              id="cpf-input" data-testid="cliente-login-cpf-input"
              type="tel" inputMode="numeric" autoComplete="off"
              placeholder="000.000.000-00"
              value={cpf} onChange={(e) => setCpf(formatCPF(e.target.value))}
              style={{
                width: "100%", boxSizing: "border-box",
                background: "rgba(255,255,255,.06)",
                border: "1px solid rgba(255,255,255,.22)",
                backdropFilter: "blur(12px)",
                WebkitBackdropFilter: "blur(12px)",
                borderRadius: 18, color: "white",
                fontSize: "clamp(22px, 5vw, 28px)", fontWeight: 800,
                letterSpacing: 1.8, padding: "18px 22px",
                textAlign: "center", outline: "none",
                fontFamily: FONT_DISPLAY,
              }}
            />

            {err && (
              <motion.div
                initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                data-testid="cliente-login-error" style={{
                  marginTop: 12, padding: "12px 14px", borderRadius: 12,
                  background: "rgba(248,113,113,.22)",
                  border: "1px solid rgba(248,113,113,.45)",
                  color: "#fecaca", fontSize: 13, fontWeight: 600,
                  textAlign: "center",
                }}>{err}</motion.div>
            )}

            <div style={{ marginTop: 18 }}>
              <OrangeCTA testid="cliente-login-submit-btn"
                type="submit"
                disabled={busy || cpf.replace(/\D/g, "").length < 11}>
                {busy ? "Entrando…" : <>Entrar <span style={{ fontSize: 18 }}>→</span></>}
              </OrangeCTA>
            </div>

            <p style={{
              marginTop: 18, fontSize: 12.5, fontWeight: 500,
              color: "rgba(255,255,255,.7)", lineHeight: 1.55,
              textAlign: "center",
              textShadow: "0 2px 8px rgba(0,0,0,.4)",
            }}>
              Só pra clientes Ligo ativos. Não pedimos senha — seu CPF
              já é sua identidade aqui.
            </p>
          </div>
        </form>
      </motion.div>

      {/* Footer fixo no rodapé direito (esquerda fica com o card) */}
      <div style={{
        position: "absolute", bottom: 16, right: 22,
        zIndex: 2, textAlign: "right",
        fontSize: 11.5, fontWeight: 600,
        color: "rgba(255,255,255,.6)",
        textShadow: "0 2px 8px rgba(0,0,0,.45)",
      }}>
        © Ligo Fibra · Internet de verdade
      </div>
    </div>
  );
}
