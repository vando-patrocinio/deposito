import React from "react";
import ReactDOM from "react-dom/client";
import "@/index.css";
import App from "@/App";

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// Register service worker for PWA (only in production builds).
// Detecta SW novo, instala em background e quando "activated", recarrega
// automaticamente — assim o usuário vê a versão nova logo após o redeploy,
// sem precisar dar Ctrl+Shift+R.
if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
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
