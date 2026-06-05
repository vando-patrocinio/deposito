/* ClienteIndicaApp — Entry point do app `/cliente`.
 *
 * Fluxo de navegação:
 *
 *    LoginCPF → Hub → Indique e Ganhe
 *                  → Minha Ligo
 *
 *  - Token guardado em `ligo_indica_token` (localStorage)
 *  - Sub-rotas usam estado local (hash sync), não react-router, pra ficar
 *    1 arquivo só e fácil de manter.
 *  - Hash: #hub | #indique | #minha-ligo  (default: #hub)
 */
import React, { useEffect, useState } from "react";
import axios from "axios";

import LoginCPF from "@/cliente/LoginCPF";
import HubScreen from "@/cliente/HubScreen";
import IndiqueScreen from "@/cliente/IndiqueScreen";
import MinhaLigoScreen from "@/cliente/MinhaLigoScreen";
import PromocoesScreen from "@/cliente/PromocoesScreen";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const LS_TOKEN = "ligo_indica_token";

const VALID_VIEWS = ["hub", "indique", "minha-ligo", "promocoes"];

function readHashView() {
  if (typeof window === "undefined") return "hub";
  const h = (window.location.hash || "").replace("#", "");
  return VALID_VIEWS.includes(h) ? h : "hub";
}

export default function ClienteIndicaApp() {
  const [token, setToken] = useState(
    () => localStorage.getItem(LS_TOKEN) || "",
  );
  const [me, setMe] = useState(null);
  const [bootErr, setBootErr] = useState("");
  const [view, setView] = useState(readHashView);

  /* Sync hash → state quando o usuário usa Voltar do navegador. */
  useEffect(() => {
    const onHash = () => setView(readHashView());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  /* Após login: pega /me pra hidratar perfil.
   * Faz MERGE — /customer/me não devolve `status`/`document`/`filial_name`,
   * então preservamos os campos do response do login. */
  useEffect(() => {
    if (!token) { setMe(null); return; }
    axios.get(`${API}/customer/me`,
      { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => setMe((prev) => ({ ...(prev || {}), ...r.data })))
      .catch((e) => {
        setBootErr(e?.response?.data?.detail || "Sessão expirada.");
        localStorage.removeItem(LS_TOKEN);
        setToken("");
      });
  }, [token]);

  const onLogged = (tk, subscriber) => {
    localStorage.setItem(LS_TOKEN, tk);
    setToken(tk);
    setMe(subscriber);
    goView("hub");
  };

  const logout = () => {
    localStorage.removeItem(LS_TOKEN);
    setToken("");
    setMe(null);
    if (window.location.hash) window.location.hash = "";
  };

  const goView = (v) => {
    window.location.hash = v;
    setView(v);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  if (!token || !me) {
    return <LoginCPF onLogged={onLogged} initialErr={bootErr} />;
  }

  if (view === "indique") {
    return (
      <IndiqueScreen token={token} me={me} setMe={setMe}
        onBack={() => goView("hub")}
        onLogout={logout} />
    );
  }
  if (view === "minha-ligo") {
    return (
      <MinhaLigoScreen me={me}
        onBack={() => goView("hub")}
        onLogout={logout} />
    );
  }
  if (view === "promocoes") {
    return (
      <PromocoesScreen me={me}
        onBack={() => goView("hub")}
        onLogout={logout} />
    );
  }
  return (
    <HubScreen me={me}
      onOpenIndique={() => goView("indique")}
      onOpenMinhaLigo={() => goView("minha-ligo")}
      onOpenPromocoes={() => goView("promocoes")}
      onLogout={logout} />
  );
}
