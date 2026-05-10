import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "@/api";

const TOKEN_KEY = "ponto_token";
const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => (typeof window !== "undefined" ? window.localStorage.getItem(TOKEN_KEY) : null));
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  // Persist token in localStorage (read by axios interceptor in api.js)
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  }, [token]);

  // Load /me whenever token changes
  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!token) { setUser(null); setLoading(false); return; }
      try {
        const me = await api.me();
        if (!cancelled) setUser(me);
      } catch (e) {
        if (!cancelled) {
          setToken(null);
          setUser(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    setLoading(true);
    load();
    return () => { cancelled = true; };
  }, [token]);

  const login = useCallback(async (email, password) => {
    const r = await api.login(email, password);
    setToken(r.access_token);
    setUser(r.user);
    return r.user;
  }, []);

  const loginWithGoogle = useCallback(async (session_id) => {
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
    setToken(null);
    setUser(null);
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
  // administrador é super-role e tem acesso a TUDO no app desktop.
  // auditor segue a lista explícita de cada aba (não é wildcard).
  if (user.role === "administrador") return true;
  return roles.includes(user.role);
}
