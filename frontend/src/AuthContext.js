import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "@/api";

const TOKEN_KEY = "ponto_token";
const AuthCtx = createContext(null);

// Chaves do localStorage QUE PERTENCEM AO USUÁRIO (limpas no logout).
// IMPORTANTE: nunca incluir aqui chaves "de dispositivo" como theme ou device_id —
// elas são preferências do navegador, não do usuário. Também NÃO incluímos
// `ponto_active_tab` aqui — última aba é preferência de UI, não dado sensível.
const USER_SCOPED_KEYS = [
  "ponto_token",            // JWT principal
  "ponto_active_company",   // empresa selecionada pelo super_admin
  "ponto_onboarding_done",  // flag de onboarding completo
  "collab_token",           // sessão do colaborador (PWA)
  "collab_id",              // id do colaborador logado
];
// Chaves do sessionStorage (mais simples — mata tudo)
const USER_SCOPED_SESSION_KEYS = [
  "ponto_mode",
];

// Limpa TODOS os dados do usuário anterior. Chamado em logout e antes de cada login.
function purgeUserState() {
  if (typeof window === "undefined") return;
  try {
    USER_SCOPED_KEYS.forEach((k) => window.localStorage.removeItem(k));
    USER_SCOPED_SESSION_KEYS.forEach((k) => window.sessionStorage.removeItem(k));
  } catch (e) {
    console.warn("purgeUserState failed", e);
  }
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => (typeof window !== "undefined" ? window.localStorage.getItem(TOKEN_KEY) : null));
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  // Public token mode: link público (?ptoken=xxx) que dá acesso admin sem login.
  // Persistido em localStorage; o interceptor de api.js injeta o header X-Public-Token.
  const [publicToken, setPublicToken] = useState(() => {
    if (typeof window === "undefined") return null;
    try {
      const url = new URLSearchParams(window.location.search);
      let fromUrl = url.get("ptoken");

      // Captura também token no path: /<token-de-22+-chars-ou-uuid>
      // Útil pra URLs limpas tipo `https://app/c5705a3d-9506-...`
      if (!fromUrl) {
        const path = (window.location.pathname || "").replace(/^\/+|\/+$/g, "");
        // Rotas conhecidas que NÃO devem ser tratadas como token
        const KNOWN_PREFIXES = [
          "app", "login", "signup", "preview", "demo",
          "tv", "quadro", "billing", "holerite", "onboarding",
        ];
        const isKnown = !path || KNOWN_PREFIXES.some(
          (p) => path === p || path.startsWith(p + "/"),
        );
        if (!isKnown && /^[A-Za-z0-9_-]{16,}$/.test(path)) {
          fromUrl = path;
        }
      }

      if (fromUrl) {
        window.localStorage.setItem("smartprov_public_token", fromUrl);
        // Limpa a URL pra "/" pra não vazar em screenshots/share
        window.history.replaceState({}, "", "/");
        return fromUrl;
      }
      return window.localStorage.getItem("smartprov_public_token");
    } catch {
      return null;
    }
  });

  // Persist token in localStorage (read by axios interceptor in api.js)
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  }, [token]);

  // Load /me whenever token (JWT) OR publicToken changes
  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!token && !publicToken) { setUser(null); setLoading(false); return; }
      try {
        const me = await api.me();
        if (!cancelled) setUser(me);
      } catch (e) {
        if (!cancelled) {
          // Só limpa se for 401 REAL — erros de rede/timeout NÃO devem
          // deslogar o usuário (manter sessão e tentar de novo no próximo poll).
          const status = e?.response?.status;
          if (status === 401 || status === 403) {
            setToken(null);
            setUser(null);
            // Public token inválido: também remove
            if (publicToken) {
              try {
                window.localStorage.removeItem("smartprov_public_token");
              } catch { /* ignore */ }
              setPublicToken(null);
            }
            purgeUserState();
          } else {
            // Erro de rede: manter token, mostrar usuário como "carregando"
            // e o componente que renderizar pode tentar de novo.
            console.warn("[auth] /me falhou (rede/timeout):", e?.message);
          }
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    setLoading(true);
    load();
    return () => { cancelled = true; };
  }, [token, publicToken]);

  // Escuta evento global de sessão expirada (disparado pelo interceptor 401
  // em api.js). Quando dispara: limpa o token (que vai cair em /login) sem
  // hard reload — preservando todo o estado da app em memória.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onExpired = (e) => {
      console.warn("[auth] sessão expirada:", e?.detail?.reason);
      setToken(null);
      setUser(null);
      purgeUserState();
    };
    window.addEventListener("smartprov-session-expired", onExpired);
    return () => window.removeEventListener("smartprov-session-expired", onExpired);
  }, []);

  const login = useCallback(async (email, password) => {
    // Antes de aceitar credenciais, limpa qualquer resíduo de outro usuário.
    purgeUserState();
    const r = await api.login(email, password);
    setToken(r.access_token);
    setUser(r.user);
    return r.user;
  }, []);

  const loginWithGoogle = useCallback(async (session_id) => {
    purgeUserState();
    const r = await api.googleLogin(session_id);
    setToken(r.access_token);
    setUser(r.user);
    return r.user;
  }, []);

  // Captura #session_id=... que pode vir do redirect do Google
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!window.location.hash || !window.location.hash.includes("session_id=")) return;
    // Se modo=app, o CollaboratorApp processa (PWA do colaborador)
    const params = new URLSearchParams(window.location.search);
    if (params.get("mode") === "app") return;
    const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const sid = hashParams.get("session_id");
    if (!sid) return;
    (async () => {
      try {
        await loginWithGoogle(sid);
      } catch (e) {
        console.warn("google login failed", e);
      } finally {
        // Limpa o hash mesmo em erro pra não retentar
        const cleanUrl = window.location.pathname + window.location.search;
        window.history.replaceState(null, "", cleanUrl);
      }
    })();
  }, [loginWithGoogle]);

  const logout = useCallback(() => {
    // Tenta avisar o backend (best-effort — não bloqueia se falhar)
    try { api.logout?.(); } catch { /* ignore */ }
    setToken(null);
    setUser(null);
    purgeUserState();
    // Hard reload pra garantir que toda memória do app (axios cache, SWR, polling,
    // event sources, timers) seja descartada. Single-user-per-device garantido.
    if (typeof window !== "undefined") {
      window.location.replace("/login");
    }
  }, []);

  const impersonate = useCallback(async (uid) => {
    const r = await api.impersonate(uid);
    setToken(r.access_token);
    setUser(r.user);
    return r.user;
  }, []);

  const endImpersonation = useCallback(async () => {
    const r = await api.endImpersonation();
    setToken(r.access_token);
    setUser(r.user);
    return r.user;
  }, []);

  return (
    <AuthCtx.Provider value={{
      user, token, loading, login, loginWithGoogle, logout, impersonate, endImpersonation,
      isAuthed: !!user,
      isImpersonating: !!user?.impersonator,
      // Public token mode (link público sem login)
      isPublicAccess: !!publicToken && !token,
      publicToken,
    }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth deve ser usado dentro de AuthProvider");
  return ctx;
}

export function hasRole(user, ...roles) {
  if (!user) return false;
  if (user.role === "auditor" || user.role === "administrador") return true; // super-roles
  return roles.includes(user.role);
}
