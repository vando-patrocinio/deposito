/* apiClient.js — Helper unificado de fetch autenticado.
   Centraliza:
   - Chave do token (`ponto_token`) — evita bugs do tipo
     "smartprov_token" usado por engano.
   - Authorization Bearer + Content-Type JSON.
   - Parse + tratamento de erro padronizado.

   Uso:
     import { api } from "@/lib/apiClient";
     const data = await api.get("/api/foo");
     const res = await api.post("/api/foo", { a: 1 });
*/

const API_BASE = process.env.REACT_APP_BACKEND_URL;
const TOKEN_KEY = "ponto_token";

export const getToken = () => {
  try { return localStorage.getItem(TOKEN_KEY) || ""; }
  catch { return ""; }
};

export const setToken = (t) => {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* ignore */ }
};

const request = async (path, opts = {}) => {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const headers = {
    Accept: "application/json",
    ...(opts.body && !(opts.body instanceof FormData)
      ? { "Content-Type": "application/json" } : {}),
    ...(opts.headers || {}),
  };
  const t = getToken();
  if (t && !headers.Authorization) headers.Authorization = `Bearer ${t}`;
  const r = await fetch(url, { ...opts, headers });
  const text = await r.text();
  let data;
  try { data = text ? JSON.parse(text) : null; }
  catch { data = { raw: text }; }
  if (!r.ok) {
    const err = new Error(
      (data && (data.detail || data.error || data.message))
      || `HTTP ${r.status}`,
    );
    err.status = r.status;
    err.response = { status: r.status, data };
    throw err;
  }
  return data;
};

export const api = {
  get: (p) => request(p, { method: "GET" }),
  post: (p, body) => request(p, {
    method: "POST",
    body: body == null ? undefined
      : (body instanceof FormData ? body : JSON.stringify(body)),
  }),
  put: (p, body) => request(p, {
    method: "PUT",
    body: body == null ? undefined : JSON.stringify(body),
  }),
  patch: (p, body) => request(p, {
    method: "PATCH",
    body: body == null ? undefined : JSON.stringify(body),
  }),
  delete: (p) => request(p, { method: "DELETE" }),
  raw: request,
};

export default api;
