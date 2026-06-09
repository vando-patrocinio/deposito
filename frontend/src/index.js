import React from "react";
import ReactDOM from "react-dom/client";
import "@/index.css";
import App from "@/App";
import FleetPortalApp from "@/fleet/FleetPortalApp";
import SecurityPortalApp from "@/security/SecurityPortalApp";
import PartnerPortalApp from "@/parceria/PartnerPortalApp";
import ClientPortalApp from "@/parceria/ClientPortalApp";
import ParceriaPublicPage from "@/parceria/ParceriaPublicPage";
import PartnerDetailPage from "@/parceria/PartnerDetailPage";
import ParceiroPWA from "@/parceria/ParceiroPWA";
import SejaParceiroLanding from "@/parceria/SejaParceiroLanding";
import ReferralLandingPage from "@/ReferralLandingPage";
import ClienteIndicaApp from "@/cliente/ClienteIndicaApp";
import WifiCaptivePortal from "@/WifiCaptivePortal";
import WifiShowcasePage from "@/WifiShowcasePage";
import LousaTvPanel from "@/lousa/LousaTvPanel";
import SmartProvLanding from "@/SmartProvLanding";

// iter212a — Roteamento standalone do portal white-label (Fleet)
// Aciona com `?portal=fleet` OU pathname iniciado em `/fleet-portal`.
const _params = new URLSearchParams(window.location.search);
const _isReferralLanding = window.location.pathname.startsWith("/r/");
const _isClienteIndica = _params.get("portal") === "cliente-indica"
  || window.location.pathname === "/cliente"
  || window.location.pathname.startsWith("/cliente/");
const _refCode = _isReferralLanding
  ? window.location.pathname.replace("/r/", "").split("/")[0] : "";
const _isFleetPortal = _params.get("portal") === "fleet"
  || window.location.pathname.startsWith("/fleet-portal");
const _isSecurityPortal = _params.get("portal") === "security"
  || window.location.pathname.startsWith("/security-portal");
const _isPartnerPortal = _params.get("portal") === "parceiro"
  || window.location.pathname.startsWith("/parceiro-portal");
const _isClientPortal = _params.get("portal") === "cliente"
  || window.location.pathname.startsWith("/cliente-portal");
const _isShowcase = _params.get("showcase") === "parcerias"
  || window.location.pathname.startsWith("/parcerias");
// iter235 — Landing comercial pra captação de novos parceiros
const _isSejaParceiro = window.location.pathname === "/seja-parceiro"
  || window.location.pathname === "/seja-parceiro/"
  || window.location.pathname === "/parcerias/seja-parceiro";
// iter230 — App PWA do parceiro comercial (magic link). Aciona em
// /parceiro/{token} quando o segmento tem >=30 chars (magic_token).
// O PartnerDetailPage continua atendendo slugs curtos (/parceiro/pizza-bella).
const _parceiroSegment = window.location.pathname.startsWith("/parceiro/")
  ? window.location.pathname.replace("/parceiro/", "").split("/")[0]
  : "";
const _isParceiroPWA = _parceiroSegment.length >= 30;
const _isPartnerDetail = !_isParceiroPWA
  && (!!_params.get("parceiro")
       || !!_params.get("p")
       || window.location.pathname.startsWith("/parceiro/"));
const _isWifiCaptive = window.location.pathname.startsWith("/wifi/");
// Vitrine pública dos hotspots WiFi Ligo
const _isWifiShowcase = _params.get("showcase") === "wifi"
  || window.location.pathname === "/wifi-vitrine"
  || window.location.pathname === "/wifi-vitrine/";
// Lousa TV — view-only Kanban para SmartTV (token público)
const _isLousaTv = _params.get("portal") === "lousa-tv"
  || window.location.pathname === "/lousa-tv"
  || window.location.pathname === "/lousa-tv/";
// FASE 9 V5.0 — Landing pública vendável (sem auth, dados reais ao vivo)
const _isSmartProvLanding = window.location.pathname === "/smartprov-ai-center"
  || window.location.pathname === "/smartprov-ai-center/";

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    {_isReferralLanding ? <ReferralLandingPage code={_refCode} />
      : _isWifiCaptive ? <WifiCaptivePortal />
        : _isWifiShowcase ? <WifiShowcasePage />
          : _isLousaTv ? <LousaTvPanel />
            : _isSmartProvLanding ? <SmartProvLanding />
            : _isClienteIndica ? <ClienteIndicaApp />
              : _isParceiroPWA ? <ParceiroPWA magicToken={_parceiroSegment} />
                : _isSejaParceiro ? <SejaParceiroLanding />
                  : _isPartnerDetail ? <PartnerDetailPage />
                    : _isFleetPortal ? <FleetPortalApp />
                      : _isSecurityPortal ? <SecurityPortalApp />
                        : _isPartnerPortal ? <PartnerPortalApp />
                          : _isClientPortal ? <ClientPortalApp />
                            : _isShowcase ? <ParceriaPublicPage />
                              : <App />}
  </React.StrictMode>,
);

// Register service worker for PWA (only in production builds).
// Detecta SW novo, instala em background e quando "activated", recarrega
// automaticamente — assim o usuário vê a versão nova logo após o redeploy,
// sem precisar dar Ctrl+Shift+R.
// iter183 — Habilita SW em prod E em dev quando REACT_APP_ENABLE_SW=1 está
// setado. Útil para validar offline-first (tile cache) no preview.
if ("serviceWorker" in navigator
      && (process.env.NODE_ENV === "production"
            || process.env.REACT_APP_ENABLE_SW === "1")) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/service-worker.js")
      .then((reg) => {
        // Verifica updates a cada 60s (caso o usuário deixe a aba aberta)
        setInterval(() => reg.update().catch(() => {}), 60_000);
        // Quando uma nova versão for instalada, ativa imediatamente
        reg.addEventListener("updatefound", () => {
          const newSW = reg.installing;
          if (!newSW) return;
          newSW.addEventListener("statechange", () => {
            if (newSW.state === "installed" && navigator.serviceWorker.controller) {
              newSW.postMessage({ type: "SKIP_WAITING" });
            }
          });
        });
      })
      .catch((err) => console.warn("SW registration failed:", err));

    // Quando o controller muda (= SW novo assumiu), recarrega 1x.
    let refreshing = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (refreshing) return;
      refreshing = true;
      window.location.reload();
    });
  });
}
