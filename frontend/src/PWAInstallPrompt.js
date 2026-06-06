/**
 * PWAInstallPrompt — botão flutuante que aparece quando o navegador
 * sinaliza que o app PODE ser instalado (Android Chrome/Edge/Samsung Internet).
 *
 * No iOS Safari não existe `beforeinstallprompt`. Mostramos uma dica
 * separada explicando como adicionar à tela inicial via menu de share.
 *
 * Comportamento:
 *  - Escuta `beforeinstallprompt` e guarda a referência
 *  - Mostra botão "Instalar app" na home do CollaboratorApp
 *  - Se usuário recusar, persiste em localStorage (não incomoda de novo
 *    nas próximas 7 dias)
 *  - Some quando o app já está instalado (`display-mode: standalone`)
 */
import React, { useEffect, useState } from "react";

const SNOOZE_KEY = "pwa_install_snoozed_until";
const SNOOZE_DAYS = 7;

function isIOS() {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  return /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
}

function isStandalone() {
  if (typeof window === "undefined") return false;
  return window.matchMedia?.("(display-mode: standalone)")?.matches
    || window.navigator?.standalone === true;
}

function isSnoozed() {
  try {
    const until = parseInt(localStorage.getItem(SNOOZE_KEY) || "0", 10);
    return until > Date.now();
  } catch { return false; }
}

function snooze() {
  try {
    const until = Date.now() + SNOOZE_DAYS * 24 * 60 * 60 * 1000;
    localStorage.setItem(SNOOZE_KEY, String(until));
  } catch { /* ignore */ }
}

export default function PWAInstallPrompt() {
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [show, setShow] = useState(false);
  const [iosShow, setIosShow] = useState(false);

  useEffect(() => {
    if (isStandalone() || isSnoozed()) return;

    const ios = isIOS();
    if (ios) {
      // No iOS, mostra dica após 5s na tela
      const t = setTimeout(() => setIosShow(true), 5000);
      return () => clearTimeout(t);
    }

    const onBeforeInstall = (e) => {
      e.preventDefault();
      setDeferredPrompt(e);
      // Espera 3s antes de mostrar — evita flash logo na entrada
      setTimeout(() => setShow(true), 3000);
    };
    const onInstalled = () => {
      setShow(false);
      setDeferredPrompt(null);
    };
    window.addEventListener("beforeinstallprompt", onBeforeInstall);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstall);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  const install = async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    try {
      const choice = await deferredPrompt.userChoice;
      if (choice.outcome !== "accepted") {
        snooze();
      }
    } catch { /* ignore */ }
    setDeferredPrompt(null);
    setShow(false);
  };

  const dismiss = () => {
    snooze();
    setShow(false);
    setIosShow(false);
  };

  if (isStandalone()) return null;

  // Android — botão modal
  if (show && deferredPrompt) {
    return (
      <div data-testid="pwa-install-prompt" style={{
        position: "fixed", left: 16, right: 16, bottom: 16, zIndex: 9000,
        background: "linear-gradient(135deg, #0f172a, #1e293b)",
        color: "white", borderRadius: 14, padding: 14,
        boxShadow: "0 8px 24px rgba(0,0,0,.3)",
        display: "flex", alignItems: "center", gap: 12,
        animation: "slideUp .3s ease-out",
      }}>
        <div style={{
          width: 44, height: 44, borderRadius: 12,
          background: "white", padding: 4,
          display: "grid", placeItems: "center",
          flexShrink: 0,
        }}>
          <img src="/icons/icon-192.png" alt="SmartProv"
               style={{ width: "100%", height: "100%", borderRadius: 8 }} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 800, fontSize: 13, marginBottom: 2 }}>
            Instalar app no celular
          </div>
          <div style={{ fontSize: 11, opacity: .85, lineHeight: 1.4 }}>
            Acesso rápido, funciona offline, parece app nativo.
          </div>
        </div>
        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          <button onClick={install}
                  data-testid="pwa-install-btn"
                  style={{
                    background: "#10b981", color: "white",
                    border: 0, padding: "8px 14px",
                    borderRadius: 8, fontSize: 12, fontWeight: 800,
                    cursor: "pointer",
                  }}>
            Instalar
          </button>
          <button onClick={dismiss}
                  data-testid="pwa-install-dismiss"
                  aria-label="Dispensar"
                  style={{
                    background: "transparent", color: "#94a3b8",
                    border: 0, padding: "8px 6px", fontSize: 18,
                    cursor: "pointer", lineHeight: 1,
                  }}>
            ×
          </button>
        </div>
      </div>
    );
  }

  // iOS — instruções via share button
  if (iosShow) {
    return (
      <div data-testid="pwa-ios-hint" style={{
        position: "fixed", left: 16, right: 16, bottom: 16, zIndex: 9000,
        background: "white",
        color: "#0f172a", borderRadius: 14, padding: 14,
        boxShadow: "0 8px 24px rgba(0,0,0,.18)",
        border: "1px solid #e2e8f0",
        animation: "slideUp .3s ease-out",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "flex-start", gap: 10 }}>
          <div style={{ display: "flex", gap: 10, flex: 1, minWidth: 0 }}>
            <div style={{
              width: 36, height: 36, borderRadius: 10,
              background: "#0f172a", padding: 4,
              display: "grid", placeItems: "center", flexShrink: 0,
            }}>
              <img src="/icons/icon-192.png" alt="SmartProv"
                   style={{ width: "100%", height: "100%", borderRadius: 6 }} />
            </div>
            <div style={{ flex: 1, fontSize: 12 }}>
              <div style={{ fontWeight: 800, marginBottom: 4, fontSize: 13 }}>
                Instalar no iPhone
              </div>
              <div style={{ lineHeight: 1.5, color: "#475569" }}>
                Toque em <strong>Compartilhar</strong>{" "}
                <span style={{
                  display: "inline-block", verticalAlign: "middle",
                  width: 16, height: 16, border: "1.5px solid #475569",
                  borderRadius: 4, position: "relative", top: -1, marginRight: 2,
                }}/>{" "}
                e escolha <strong>“Adicionar à Tela de Início”</strong>
              </div>
            </div>
          </div>
          <button onClick={dismiss}
                  data-testid="pwa-ios-dismiss"
                  aria-label="Dispensar"
                  style={{
                    background: "transparent", color: "#94a3b8",
                    border: 0, padding: 0, fontSize: 22,
                    cursor: "pointer", lineHeight: 1, flexShrink: 0,
                  }}>
            ×
          </button>
        </div>
      </div>
    );
  }

  return null;
}
